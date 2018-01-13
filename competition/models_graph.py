import logging
import os
from . import lm
# from . import ns
from competition import neostore
from flask import current_app
from flask_login import UserMixin
# from lib import my_env
from py2neo.types import *
from werkzeug.security import generate_password_hash, check_password_hash

# Todo: Get Username / Password from environment settings
neo4j_params = dict(
    user=os.environ.get('Neo4J_User'),
    password=os.environ.get('Neo4J_Pwd'),
    db=os.environ.get('Neo4J_Db')
)
ns = neostore.NeoStore(**neo4j_params)

# Define Node Labels
racelabel = "Race"

# Define Relation Types
catgroup2cat = "memberOf"
org2date = "On"
org2loc = "In"
org2race = "has"
org2type = "type"
person2category = "inCategory"
person2mf = "mf"
person2participant = "is"
race2category = "forCategory"
race2mf = "forMF"

# mf_tx translates from man/vrouw (form value to Node name).
mf_tx = dict(
    man="Heren",
    vrouw="Dames"
)
# mf_tx_inf translates from Node name to man/vrouw value.
mf_tx_inv = {y: x for x, y in mf_tx.items()}


class User(UserMixin):
    """
    The user class manages the registered users of the application. The Person class is for the people that participate
    in the race.
    """
    def __init__(self, user_id=None):
        if user_id:
            self.user_node = ns.node(user_id)
        else:
            self.user_node = "NotDefined"

    def __repr__(self):
        return "<User: {user}>".format(user=self.user_node["name"])

    def find(self, username):
        """
        This function will find the User object for the user with the specified username.
        If found, then the hashed password is returned. If not found, False is returned.
        :param username:
        :return: User node, then the caller can do whatever he wants with the information.
        """
        label = "User"
        props = dict(name=username)
        user_node = ns.get_node(label, **props)
        if user_node:
            try:
                self.user_node = user_node
                return self.user_node
            except KeyError:
                # Password not defined for user, return False
                return False
        else:
            # User not defined
            return False

    def get_id(self):
        return self.user_node["nid"]

    def register(self, username, password):
        if self.find(username):
            return False
        else:
            label = "User"
            props = dict(
                name=username,
                pwd=generate_password_hash(password)
            )
            user_node = ns.create_node(label, **props)
            return user_node["nid"]

    def validate_password(self, name, pwd):
        """
        Find the user. If the user exists, verify the password. If the passwords match, return nid of the User node.
        If the passwords don't match, return False.
        If the user does not exists, return False.
        :param name:
        :param pwd:
        :return:
        """
        if self.find(name):
            return check_password_hash(self.user_node["pwd"], pwd)
        else:
            return False


@lm.user_loader
def load_user(user_id):
    """
    This function will return the User object. user_id is the nid of the User node.
    :param user_id: nid of the user node.
    :return: user object.
    """
    return User(user_id)


class Participant:

    # List of calculated properties for the participant node.
    calc_props = ["nid", "points", "rel_pos"]

    def __init__(self, part_id=None, race_id=None, pers_id=None):
        """
        A Participant Object is the path: (person)-[:is]->(participant)-[:participates]->(race).
        If participant id is provided, then find race id and person id.
        If race id and person id are provided, then try to find participant id. If not successful, then create
        participant id. The application must call the 'add' method to add this participant in the correct sequence.
        At the end of initialization, participant node, id, race id and person id are set.
        When a participant is added or deleted, then the points for the race will be recalculated.
        :param part_id: nid of the participant
        :param race_id: nid of the race
        :param pers_id: nid of the person
        :return: Participant object with participant node and nid, race nid and person nid are set.
        """
        # Todo: rework classes so that objects are kept, not nids - replace race_nid with race_obj, ...
        self.part_node = None
        self.part_id = -1           # Unique ID (nid) of the Participant node
        if part_id:
            # I have a participant ID, find race and person information
            self.part_node = ns.node(part_id)
            self.part_id = part_id
            self.race_id = ns.get_end_node(start_node_id=part_id, rel_type="participates")
            self.pers_id = ns.get_start_node(end_node_id=part_id, rel_type="is")
        elif pers_id and race_id:
            self.race_id = race_id
            self.pers_id = pers_id
            self.part_node = ns.get_participant_in_race(pers_id=pers_id, race_id=race_id)
            if self.part_node:
                self.part_id = self.part_node["nid"]
            else:
                # Participant node not found, so create one.
                # First remember first arrival in the race
                self.first_arrival_in_race = participant_first_id(race_id)
                self.part_id = self.set_part_race()
        else:
            logging.fatal("No input provided.")
            raise ValueError("CannotCreateObject")
        return

    def get_id(self):
        """
        This method will return the Participant Node ID of this person's participation in the race
        :return: Participant Node ID (nid)
        """
        return self.part_id

    def get_person_nid(self):
        """
        This method will return the Person Node ID for this participant.
        :return:
        """
        return self.pers_id

    def get_props(self):
        """
        This method will get the properties for the node. All properties for the participant node will be collected,
        then the calculated properties (points, rel_pos, ...) will be removed from the dictionary.
        collected from the participant node and added to the list of properties that are set by the user.
        :return:
        """
        # Get participant node to ensure latest values for all calculated properties.
        # Ignore the user configurable properties, since these are managed in the **props dictionary.
        self.part_node = ns.node(self.part_id)
        # Convert node to node-dictionary.
        part_dict = dict(self.part_node)
        # Remove calculated properties from dictionary
        for attrib in self.calc_props:
            part_dict.pop(attrib, None)
        return part_dict

    def get_race_nid(self):
        """
        This method will return the Race Node ID for the participant.
        :return: Nid for the Race node.
        """
        return self.race_id

    def set_part_race(self):
        """
        This method will link the person to the race. This is done by creating an Participant Node. This function will
        not link the participant to the previous or next participant.
        The method will set the participant node and the participant nid.
        @return: Node ID of the participant node.
        """
        self.part_node = ns.create_node("Participant")
        self.part_id = self.part_node["nid"]
        race_node = ns.node(self.race_id)
        ns.create_relation(from_node=self.part_node, rel="participates", to_node=race_node)
        pers_node = ns.node(self.pers_id)
        ns.create_relation(from_node=pers_node, rel="is", to_node=self.part_node)
        return self.part_id

    def set_props(self, **props):
        """
        This method will set the properties for the node. The calculated properties (points, rel_pos, ...) will be
        collected from the participant node and added to the list of properties that are set by the user.
        :param props: list of user properties for the participant node.
        :return:
        """
        # ToDo: It may be better to use ns.node_set_attribs.
        # Get participant node to ensure latest values for all calculated properties.
        # Ignore the user configurable properties, since these are managed in the **props dictionary.
        self.part_node = ns.node(self.part_id)
        # Convert node to node-dictionary. This ensures that KeyError exception can be used.
        part_dict = dict(self.part_node)
        for attrib in self.calc_props:
            try:
                props[attrib] = part_dict[attrib]
            except KeyError:
                pass
        return ns.node_update(**props)

    @staticmethod
    def set_relation(next_id=None, prev_id=None):
        """
        This method will connect the next runner with the previous runner. The next runner is after the previous runner.
        @param next_id: Node ID of the next runner
        @param prev_id: Node ID of the previous runner
        @return:
        """
        prev_part_node = ns.node(prev_id)
        next_part_node = ns.node(next_id)
        if neostore.validate_node(prev_part_node, "Participant") \
                and neostore.validate_node(next_part_node, "Participant"):
            ns.create_relation(from_node=next_part_node, rel="after", to_node=prev_part_node)
        return

    def add(self, prev_pers_id=None):
        """
        This method will add the participant in the chain of arrivals. This is required only if there is more than one
        participant in the race.
        First action will be determined, then the action will be executed.
        Is there a previous arrival (prev_pers_id) for this runner? Remember nid for previous arrival. Else this
        participant is the first arrival.
        Is there a next arrival for this runner? Remove relation between previous and next, remember next.
        Now link current participant to previous arrival and to next arrival.
        :param prev_pers_id: nid of previous arrival, or -1 if current participant in first arrival
        :return:
        """
        # Count total number of arrivals. Process required only if there is more than one.
        nr_participants = len(participant_list(self.race_id))
        if nr_participants > 1:
            # Process required only if there is more than one participant in the race
            if prev_pers_id != "-1":
                # There is an arrival before current participant
                # Find participant nid for this person
                prev_arrival_obj = Participant(race_id=self.race_id, pers_id=prev_pers_id)
                prev_arrival_nid = prev_arrival_obj.get_id()
                # This can be linked to a next_arrival. Current participant will break this link
                next_arrival_nid = prev_arrival_obj.next_runner()
                if next_arrival_nid:
                    ns.remove_relation(start_nid=next_arrival_nid, end_nid=prev_arrival_nid, rel_type="after")
            else:
                # This participant is the first one in the race. Find the next participant.
                # Be careful, method 'participant_first_id' requires valid chain. So this needs to run before
                # set_part_race()
                prev_arrival_nid = False
                # Get participant nid for person nid first arrival.
                next_arrival_obj = Participant(race_id=self.race_id, pers_id=self.first_arrival_in_race)
                next_arrival_nid = next_arrival_obj.get_id()
            # Previous and next arrival have been calculated, create relation if required
            if prev_arrival_nid:
                self.set_relation(next_id=self.part_id, prev_id=prev_arrival_nid)
            if next_arrival_nid:
                self.set_relation(next_id=next_arrival_nid, prev_id=self.part_id)
        # Calculate points after adding participant
        points_for_race(self.race_id)
        return

    def prev_runner(self):
        """
        This method will get the node ID for this Participant's previous runner.
        The participant must have been created before.
        @return: ID of previous runner participant Node, False if there is no previous runner.
        """
        if not neostore.validate_node(self.part_node, "Participant"):       # pragma: no cover
            return False
        prev_part_id = ns.get_end_node(start_node_id=self.part_id, rel_type="after")
        return prev_part_id

    def next_runner(self):
        """
        This method will get the node ID for this Participant's next runner.
        The participant must have been created before.
        @return: ID of next runner participant Node, False if there is no next runner.
        """
        if not neostore.validate_node(self.part_node, "Participant"):       # pragma: no cover
            return False
        next_part_id = ns.get_start_node(end_node_id=self.part_id, rel_type="after")
        return next_part_id

    def remove(self):
        """
        This method will remove the participant from the race.
        Recalculate points for the race.
        @return:
        """
        if self.prev_runner() and self.next_runner():
            # There is a previous and next runner, link them
            ns.create_relation(from_node=ns.node(self.next_runner()), rel="after", to_node=ns.node(self.prev_runner()))
        # Remove Participant Node
        ns.remove_node_force(self.part_id)
        # Reset Object
        self.part_id = -1
        self.part_node = None
        points_for_race(self.race_id)
        return


class Person:
    """
    A person is uniquely identified by the name. A person must have link to mf and to one category. The person object
    always has the person node.
    """
    # Todo: add a person.remove() method: remove MF link, check no participant links available.
    # Todo: add voornaam/familienaam

    def __init__(self, person_id=None):
        if person_id:
            self.person_node = self.get_node(person_id)
        else:
            self.person_node = None

    @staticmethod
    def find(name):
        """
        Find ID of the person with name 'name'. Return node ID, else return false.
        This function must be called from add(), so make it an internal function?

        :param name: Name of the person.

        :return: True if found (Person Node will be set in the object), or false if no node could be found.
        """
        props = {
            "name": name
        }
        person_node = ns.get_node("Person", **props)
        if isinstance(person_node, Node):
            return True
        else:
            return False

    def add(self, **props):
        """
        Attempt to add the participant with name 'name'. The name must be unique. Person object is set to current
        participant. Name is set in this procedure, ID is set in the find procedure.

        :param props: Properties (in dict) for the person. Name, mf and category are mandatory.

        :return: True, if registered. False otherwise.
        """
        if self.find(props["name"]):
            # Person is found, Node set, do not create object.
            return False
        else:
            # Person not found, register participant.
            person_props = dict(
                name=props["name"]
            )
            self.person_node = ns.create_node("Person", **person_props)
            # Link to MF
            link_mf(props["mf"], self.person_node, person2mf)
            self.set_category(props["category"])
            return True

    def edit(self, **props):
        """
        This method will update an existing person node. A check is done to guarantee that the name is not duplicated
        to an existing name on another node. Modified properties will be updated and removed properties will be deleted.

        :param props: New set of properties (name, mf (boolean) and category(nid)) for the node

        :return: True - in case node is rewritten successfully.
        """
        # Name change?
        cn = self.get_name()
        if props["name"] != cn:
            if self.find(props["name"]):
                current_app.logger.error("Change name {cn} to new name {nn}, but this exists already!"
                                         .format(cn=cn, nn=props["name"]))
                return False
            else:
                self.set_name(props["name"])
        link_mf(props["mf"], self.person_node, person2mf)
        self.set_category(props["category"])
        return True

    def get_name(self):
        return self.person_node["name"]

    def get_dict(self):
        """
        This function will return a dictionary with the person attributes. This can then be used for display in a
        html macro

        :return: Dictionary with person attributes nid, label, active (True: Active user, cannot be removed,
        False: inactive user, can be removed).
        """
        person_dict = dict(
            nid=self.person_node["nid"],
            label=self.get_name(),
            active=self.active()
        )
        return person_dict


    def get_mf(self):
        """
        This method will get mf node.

        :return: mf node
        """
        return ns.get_endnode(start_node=self.person_node, rel_type=person2mf)


    def get_mf_value(self):
        """
        This method will get mf value to set race in web form.

        :return: mf value (man/vrouw)
        """
        return get_mf_value(node=self.person_node, rel=person2mf)


    def get_node(self, person_id=None):
        """
        This method returns the Person Node, or sets the person node if person_id is provided.

        :param person_id: NID of the person. Optional. If not specified, then the node will be returned. If set, then
        the person node is set.

        :return: Person node.
        """
        if person_id:
            self.person_node = ns.node(person_id)
        return self.person_node

    def get_category(self):
        """
        This method will get the category node for the person.

        :return: Category Node, or False if person not set to category.
        """
        cat_node = ns.get_endnode(start_node=self.person_node, rel_type=person2category)
        if isinstance(cat_node, Node):
            return cat_node
        else:
            return False

    def active(self):
        """
        This method will check if a person is active. For now, this means that a person has 'participates' links.
        If the person is not active, then the person can be removed.

        :return: True if the person is active, False otherwise
        """
        end_node_list = ns.get_endnodes(start_node=self.person_node, rel_type=person2participant)
        if len(end_node_list) == 0:
            # Empty list, so person does not participate in any race.
            return False
        else:
            return True

    def get_races4person(self):
        """
        This method will get a dictionary with information about all the races for the person.

        :return: Dictionary with all information about the races for the person
        """
        return ns.get_race4person(self.person_node["nid"])

    def set_name(self, name):
        """
        This method will update a person name to a new name.

        :param name:

        :return:
        """
        cn = self.get_name()
        if self.find(name):
            current_app.logger.error("Change name {cn} to new name {nn}, but this exists already!"
                                     .format(cn=cn, nn=name))
            return False
        else:
            props = ns.node_props(self.person_node["nid"])
            props["name"] = name
            ns.node_update(**props)
            return True

    def set_category(self, cat_nid):
        """
        This method will set the person in the Category specified by the cat_nid. The assumption is that cat_nid is the
        nid of a category.
        In case the person is already assigned to this category, nothing will be done.

        :param cat_nid:

        :return: True
        """
        current_cat_node = self.get_category()
        if isinstance(current_cat_node, Node):
            if current_cat_node["nid"] == cat_nid:
                # OK, person assigned to required category already
                return
            else:
                # Change category for person by removing Category first
                ns.remove_relation_node(start_node=self.person_node, end_node=current_cat_node, rel_type=person2category)
        # No category for person (anymore), add person to category
        cat_node = ns.node(cat_nid)
        ns.create_relation(from_node=self.person_node, to_node=cat_node, rel=person2category)
        return True


class Organization:
    """
    This class instantiates to an organization.
    If an organization ID is provided, then the corresponding organization object is created. Otherwise an empty
    organization object is created.

    The organization object has the organization node as its property.

    :return: Object
    """
    def __init__(self, org_id=None):
        self.org_node = None
        if org_id:
            self.org_node = self.get_node(org_id)

    def add(self, **org_dict):
        """
        This method will add the organization to the kalender. The organization graph object exists of organization name
        with link to date and city where it is organized.
        The organization instance attributes will be set.
        No checking is done on duplicate organization creations. These will be shown in the list and can be handled
        manually by the user.

        :param org_dict: New set of properties for the node. These properties are: name, location, datestamp and
         org_type. Datestamp needs to be of the form 'YYYY-MM-DD'. if org_type True then deelname otherwise Wedstrijd.

        :return: True if the organization has been registered, False if it existed already.
        """
        # Create the Organization node.
        self.org_node = ns.create_node("Organization", name=org_dict["name"])
        # Organization node known, now I can link it with the Location.
        self.set_location(org_dict["location"])
        # Set Date  for Organization
        self.set_date(org_dict["datestamp"])
        # Set Organization Type
        if org_dict['org_type']:
            self.set_org_type("Deelname")
        else:
            self.set_org_type("Wedstrijd")
        return True

    def edit(self, **properties):
        """
        This method will edit if the organization.
        Edit function needs to redirect relations, so it has begin and end nodes. This function can then remove single
        date nodes and location nodes if required. The Organization delete function will force to remove an organization
        node without a need to find the date and location first. Therefore the delete function requires a more generic
        date and location removal, where a check on all orphans is done.

        :param properties: Modified set of properties for the node. These properties are: name, location, datestamp and
         org_type. Datestamp must be of the form 'YYYY-MM-DD'

        :return: True if the organization has been updated, False if the organization (name, location, date) existed
         already. A change in Organization Type only is also a successful (True) change.
        """
        # Check Organization Type
        if properties['org_type']:
            org_type = "Deelname"
        else:
            org_type = "Wedstrijd"
        if self.set_org_type(org_type):
            # Organization type changed, so re-calculate points for all races in the organization
            racelist = race_list(self.org_node["nid"])
            for rec in racelist:
                # Probably not efficient, but then you should't change organization type too often.
                points_for_race(rec["race_id"])
        # Check Organization name.
        if properties['name'] != self.get_name():
            node_prop = dict(
                name=properties["name"],
                nid=self.org_node["nid"]
            )
            ns.node_update(**node_prop)
        # Check location
        curr_loc_node = self.get_location()
        if properties['location'] != curr_loc_node['city']:
            # Remember current location - before fiddling around with relations!
            # First create link to new location
            self.set_location(properties["location"])
            # Then remove link to current location
            ns.remove_relation_node(start_node=self.org_node, rel_type=org2loc, end_node=curr_loc_node)
            # Finally check if current location is still required. Remove if there are no more links.
            ns.remove_node(curr_loc_node)
        # Check Date
        curr_ds_node = self.get_date()
        if properties["datestamp"] != curr_ds_node["key"]:
            # First create link to new date
            self.set_date(properties["datestamp"])
            # Then remove link from current date
            ns.remove_relation_node(start_node=self.org_node, end_node=curr_ds_node, rel_type=org2date)
            # Finally check if date (day, month, year) can be removed.
            # Don't remove single date, clear all dates that can be removed. This avoids the handling of key
            # because date nodes don't have a nid.
            ns.clear_date()
        return True

    def get_label(self):
        """
        This method will return the label of the Organization. (Organization name, city and date). Assumption is that
        the organization has been set already.
        :return:
        """
        org_name = self.org_node["name"]
        city = self.get_location()["city"]
        ds = self.get_date()
        label = "{org_name} ({city}, {day:02d}-{month:02d}-{year})".format(org_name=org_name,
                                                                           city=city,
                                                                           day=ds["day"],
                                                                           month=ds["month"],
                                                                           year=ds["year"])
        return label

    def get_location(self):
        """
        This method will return the location for the Organization.

        :return: Location node.
        """
        loc_node = ns.get_endnode(self.org_node, org2loc)
        return loc_node

    def get_date(self):
        """
        This method will return the date node for the Organization.

        :return: Date node
        """
        date_node = ns.get_endnode(start_node=self.org_node, rel_type=org2date)
        return date_node

    def get_name(self):
        """
        This method will return the organization name as defined in the node.

        :return: Organization name.
        """
        return self.org_node["name"]

    def get_org_id(self):
        """
        This method will return the nid of the Organization node.
        :return: nid of the Organization node
        """
        return self.org_node["nid"]

    def get_node(self, org_id=None):
        """
        This method returns the Organization Node, or sets the organization node if org_id is provided.

        :param org_id: NID of the organization. Optional. If not specified, then the node will be returned. If set, then
        the organization node is set.

        :return: Organization node.
        """
        if org_id:
            self.org_node = ns.node(org_id)
        return self.org_node

    def get_org_type(self):
        """
        This method will return the organization type(Wedstrijd or Deelname).

        :return: Organization Type. Wedstrijd (Default) or Deelname, or False if not set.
        """
        org_type = ns.get_endnode(self.org_node, "type")
        if isinstance(org_type, Node):
            return org_type["name"]
        else:
            # org_type not yet defined for organization.
            return False

    def set_date(self, ds=None):
        """
        This method will create a relation between the organization and the date. Relation type is 'On'.
        Organization Node must be available for this method.
        @param ds: Datestamp
        @return:
        """
        date_node = ns.date_node(ds)   # Get Date (day) node
        ns.create_relation(from_node=self.org_node, rel=org2date, to_node=date_node)
        return

    def set_location(self, loc=None):
        """
        This method will create a relation between the organization and the location. Relation type is 'In'.
        Organization Node must be available for this method.

        :param loc: city name of the location.

        :return: Nothing - relation between organization and location is established.
        """
        loc_node = Location(loc).get_node()   # Get Location Node based on city
        ns.create_relation(from_node=self.org_node, to_node=loc_node, rel=org2loc)
        return

    def set_org_type(self, org_type):
        """
        This method will set or update the Organization Type. In case of update Organization Type, then the current link
        needs to be removed and the new link is set.


        :param org_type: 'Wedstrijd' or 'Deelname"

        :return: True if org_type is set (or changed), False if org_type is not changed.
        """
        # Todo: Add link to recalculate points in the races (this link is in org edit!)
        if self.get_org_type():
            if self.get_org_type == org_type:
                # All set, return
                return False
            else:
                # Org Type needs to change, remove here.
                org_type_node = ns.get_endnode(start_node=self.org_node, rel_type=org2type)
                ns.remove_relation_node(start_node=self.org_node, rel_type=org2type, end_node=org_type_node)
        # Set the organization type
        org_type_node = get_org_type_node(org_type)
        ns.create_relation(from_node=self.org_node, rel=org2type, to_node=org_type_node)
        return True


class Race:
    """
    This class instantiates to a race. This can be done as a new race that links to an organization, in which case
    org_id needs to be specified, or it can be done as a race node ID (in which case org_id should be none).

    The object has the race node and the organization object. Methods include creating and maintaining the race graph,
    consisting of links to the categories, mf and organization.
    """

    def __init__(self, org_id=None, race_id=None):
        """
        Define the Race object.

        :param org_id: Node ID of the Organization, used to create a new race.

        :param race_id: Node ID of the Race, to handle an existing race. Organization will be calculated from race.

        :return:
        """
        self.org = None
        self.race_node = None
        if org_id:
            self.org = Organization(org_id=org_id)
        elif race_id:
            self.race_node = ns.node(nid=race_id)
            self.set_org()

    def add(self, **props):
        """
        This method will add the race to this organization. This is done by creating a race graph object, consisting of
        a race node, link to mf and optional links to the categories.
        Note that check on duplicate races is not done. If a duplicate race is defined, then the user will see it in the
        list and can remove it again.

        :param props: Dictionary with race properties, including name (optional), categorylist (optional), mf and short
         (for korte cross). Name or categorylist or short (korte cross) is mandatory.

        :return: racename
        """
        raceconfig = race_config(**props)
        race_props = raceconfig["race_props"]
        categorie_nodes = raceconfig["category_nodes"]
        # Create Race Node with attribute name and label
        self.race_node = ns.create_node(racelabel, **race_props)
        # Add Race Node to Organization
        ns.create_relation(from_node=self.org.get_node(), rel=org2race, to_node=self.race_node)
        # Create link between race node and each category - this should also work for empty category list?
        if isinstance(categorie_nodes, list):
            for categorie_node in categorie_nodes:
                ns.create_relation(from_node=self.race_node, rel=race2category, to_node=categorie_node)
        link_mf(mf=props["mf"], node=self.race_node, rel=race2mf)
        return self.race_node["racename"]

    def edit(self, **props):
        """
        This method will update the race.

        :param props: Dictionary with race properties, including name (optional), categorylist (optional), mf and short
         (for korte cross). Name or categorylist or short (korte cross) is mandatory.

        :return: racename
        """
        # Update race_node properties
        raceconfig = race_config(**props)
        race_props = raceconfig["race_props"]
        race_props["nid"] = self.race_node["nid"]
        self.race_node = ns.node_update(**race_props)
        # Rearrange Category links
        # Get required categories
        categorie_nodes = raceconfig["category_nodes"]
        # Get existing categories
        current_cat_nodes = ns.get_endnodes(start_node=self.race_node, rel_type=race2category)
        # Add new links
        add_rels = [node for node in categorie_nodes if node not in current_cat_nodes]
        for end_node in add_rels:
            ns.create_relation(from_node=self.race_node, rel=race2category, to_node=end_node)
        # Remove category links that do no longer exist.
        remove_rels = [node for node in current_cat_nodes if node not in categorie_nodes]
        for end_node in remove_rels:
            ns.remove_relation(start_nid=self.race_node["nid"], end_nid=end_node["nid"], rel_type=race2category)
        link_mf(mf=props["mf"], node=self.race_node, rel=race2mf)
        return self.race_node["racename"]

    def get_cat_nids(self):
        """
        This method will return the nids for the categories in the table. This is to allow to set the selected
        categories when allowing to modify a race.

        :return: list of category nids for the race.
        """
        current_cat_nodes = ns.get_endnodes(start_node=self.race_node, rel_type=race2category)
        cat_nids = [cat["nid"] for cat in current_cat_nodes]
        return cat_nids

    def get_label(self):
        """
        This method will get the display name for the race and organization.

        :return: Race name and organization, for race 'stand-alone' usage.
        """
        org_name = self.org.get_name()
        return "{race_name} ({org_name})".format(race_name=self.get_racename(), org_name=org_name)

    def get_mf_value(self):
        """
        This method will get mf value to set race in web form.

        :return: mf value (man/vrouw)
        """
        return get_mf_value(node=self.race_node, rel=race2mf)

    def get_name(self):
        """
        This method will return the Name attribute from the race node.

        :return: Name attribute of race node, or None if name not available
        """
        return self.race_node["name"]

    def get_node(self):
        """
        This method will return the race_node

        :return: race_node
        """
        return self.race_node

    def get_org_id(self):
        """
        This method returns the org_id for a race object.

        :return: org_id
        """
        return self.org.get_org_id()

    def get_racename(self):
        """
        This method get the display name of the race.

        :return: Display name (racename) for the race.
        """
        return self.race_node["racename"]

    def get_racetype(self):
        """
        This method will return type of the race by returning the organization type (Wedstrijd or Deelname).

        :return: Type of the race: Wedstrijd or Deelname
        """
        return self.org.get_org_type()

    def is_short(self):
        """
        This method will respond to short cross query.

        :return: True - this race is a short cross, False (None)- this race is not a short cross.
        """
        if self.race_node["short"]:
            return True
        else:
            return False

    def set_org(self):
        """
        This method will set the organization object for the race.

        :return: (nothing, organization object will be set.
        """
        org_node = ns.get_startnode(end_node=self.race_node, rel_type=org2race)
        self.org = Organization(org_id=org_node["nid"])
        return


class Location:

    def __init__(self, loc):
        """
        The class will initialize the location object based on city name.

        :param loc: city name for the Location.
        """
        self.loc = loc

    def find(self):
        """
        Find the location node
        @return:
        """
        props = {
            "city": self.loc
        }
        loc = ns.get_node("Location", **props)
        return loc

    def add(self):
        if not self.find():
            ns.create_node("Location", city=self.loc)
            return True
        else:
            return False

    def get_node(self):
        """
        This method will get the node that is associated with the location. If the node does not exist already, it will
        be created.

        :return:
        """
        self.add()    # Register if required, ignore else
        node = self.find()
        return node


def organization_list():
    """
    This function will return a list of organizations. Each item in the list is a dictionary with fields date,
    organization, city, id (for organization nid) and type.

    :return:
    """
    return ns.get_organization_list()


def organization_delete(org_id=None):
    """
    This method will delete an organization. This can be done only if there are no more races attached to the
    organization. If an organization is removed, then check is done for orphan date and orphan location. If available,
    these will also be removed.
    @param org_id:
    @return:
    """
    if ns.get_end_nodes(start_node_id=org_id, rel_type="has"):
        logging.info("Organization with id {org_id} cannot be removed, races are attached.".format(org_id=org_id))
        return False
    else:
        # Remove Organization
        logging.debug("trying to remove org")
        ns.remove_node_force(org_id)
        # Check if this results in orphan dates, remove these dates
        logging.debug("Then trying to remove date")
        ns.clear_date()
        # Check if this results in orphan locations, remove these locations.
        logging.debug("Trying to delete organization")
        ns.clear_locations()
        logging.debug("All done")
        logging.info("Organization with id {org_id} removed.".format(org_id=org_id))
        return True


def get_org_id(race_id):
    """
    This method will return the organization ID for a Race ID: Organization has Race.
    @param race_id: Node ID of the race.
    @return: Node ID of the organization.
    """
    org_id = ns.get_start_node(end_node_id=race_id, rel_type="has")
    return org_id


def get_org_type(org_id):
    """
    This method will get the organization Type for this organization. Type can be 'Wedstrijd' or 'Deelname'.
    @param org_id: Node ID of the Organization.
    @return: Type of the Organization: Wedstrijd or Deelname, or False in case type could not be found.
    """
    org_type_id = ns.get_end_node(start_node_id=org_id, rel_type="type")
    org_type_node = ns.node(org_type_id)
    if org_type_node:
        return org_type_node["name"]
    else:
        return False


def get_org_type_node(org_type):
    """
    This method will find the Organization Type Node.

    :param org_type: "Deelname" or "Wedstrijd".

    :return: Organization Type Node, "Wedstrijd" or "Deelname".
    """
    props = {
        "name": org_type
    }
    return ns.get_node("OrgType", **props)


def get_race_type_node(racetype):
    """
    This method will return the racetype node associated with this racetype.
    @param racetype: Racetype specifier (Hoofdwedstrijd, Bijwedstrijd, Deelname)
    @return: Racetype Node, or False if it could not be found.
    """
    if racetype in ["Hoofdwedstrijd", "Bijwedstrijd", "Deelname"]:
        # RaceType defined, so it must be Hoofdwedstrijd.
        props = {
            "name": racetype
        }
        racetype_node = ns.get_node("RaceType", **props)
        return racetype_node
    else:
        logging.error("RaceType unknown: {racetype}.".format(racetype=racetype))
        return False


def get_races_for_org(org_id):
    """
    This method will return the list of races for an Organization ID: Organization has Race.
    @param org_id: Node ID of the Organization.
    @return: List of node IDs of races.
    """
    races = ns.get_end_nodes(start_node_id=org_id, rel_type="has")
    return races


def get_race_list_attribs(org_id):
    """
    This method will collect the params required for the Race List macro.

    :param org_id: Node ID of the organization.

    :return: Parameters for the Race List macro: org_id, org_label, races (race_list) and remove_org flag.
    """
    org = Organization(org_id=org_id)
    # org.set(org_id)
    races = race_list(org_id)
    if len(races) > 0:
        remove_org = "No"
    else:
        remove_org = "Yes"
    params = dict(
        org_id=org_id,
        org_label=org.get_label(),
        races=races,
        remove_org=remove_org
    )
    return params


def link_mf(mf, node, rel):
    """
    This method will link the node to current mf. If Link does not exist, it will be created. If link is to other
    node, the link will be removed and attached to required mf node.

    :param mf: mf attribute from web form (man/vrouw)

    :param node: Start node for the relation (Person or Race)

    :param rel: relation

    :return:
    """
    current_app.logger.info("mf: {mf}, rel: {rel}".format(mf=mf, rel=rel))
    # Translate web property to node name
    mf_name = mf_tx[mf]
    # Review MF link - update if different from current setting
    current_mf = ns.get_endnode(start_node=node, rel_type=rel)
    if isinstance(current_mf, Node):
        if current_mf["name"] != mf_name:
            # Remove link to current node
            ns.remove_relation_node(start_node=node, end_node=current_mf, rel_type=rel)
        else:
            current_app.logger.info("No changes required...")
            # Link from race to mf exist, all OK!
            return
    # Create link between race node and MF.
    mf_node = get_mf_node(mf_name)
    current_app.logger.info("Creating connection to node {mf}".format(mf=mf_node))
    ns.create_relation(from_node=node, rel=rel, to_node=mf_node)
    return


def race_list(org_id):
    """
    This function will return a list of races for an organization ID

    :param org_id: nid of the organization

    :return: List of races (empty list if there are no races).
    """
    return ns.get_race_list(org_id)


def races4person(pers_id):
    """
    This method is pass-through for a method in neostore module.
    This method will get a list of race_ids per person, sorted on date. The information per race will be provided in
    a list of dictionaries. This includes date, organization, type of race, and race results.

    :param pers_id:

    :return: list of Participant (part),race, date, organization (org) and racetype Node dictionaries in date
    sequence.
    """
    recordlist = ns.get_race4person(pers_id)
    # races = [{'race_id': record["race_id"], 'race_label': race_label(record["race_id"])} for record in recordlist]
    return recordlist


def races4person_org(pers_id):
    """
    This method gets the result of races4person method, then converts the result in a dictionary with key org_nid and
    value race dictionary.

    :param pers_id:

    :return: Dictionary with key org_nid and value dictionary of node race attributes for the person. This can be used
    for the Results Overview page.
    """
    races = races4person(pers_id=pers_id)
    race_org = {}
    for race in races:
        race_org[race["org"]["nid"]] = dict(
            race=race["race"],
            part=race["part"]
        )
    return race_org


def race_config(**params):
    """
    This method will calculate the race configuration from params specified.

    :param params:

    :return: Dictionary containing race_props (Properties for the race Node) and category_nodes (list of category nodes
    for the race. The list category nodes can be empty.
    """
    race_props = {}
    categorie_nodes = None
    mf = mf_tx[params['mf']]
    if params['short']:
        categorie_nodes = get_cat_short_cross()
        race_props['racename'] = "Korte Cross - {mf}".format(mf=mf)
        race_props['short'] = "Yes"
    else:
        if params['categories']:
            categories = params['categories']
            categorie_nodes_uns = [ns.node(nid) for nid in categories]
            categorie_nodes = sorted(categorie_nodes_uns, key=lambda x: x["seq"])
            categorie_label_arr = [cat["name"] for cat in categorie_nodes]
            categorie_label = " - ".join(categorie_label_arr)
            race_props['racename'] = "{c} - {mf}".format(c=categorie_label, mf=mf)
        if params['name']:
            race_props['name'] = params['name']
            # If name is available, I do need to overwrite racename from categories with this one.
            race_props['racename'] = "{n} - {mf}".format(n=params['name'], mf=mf)
    res = dict(
        race_props=race_props,
        category_nodes=categorie_nodes
    )
    return res


def race_delete(race_id=None):
    """
    This method will delete a race. This can be done only if there are no more participants attached to the
    race.

    :param race_id: Node ID of the race to be removed.

    :return: True if race is removed, False otherwise.
    """
    race = Race(race_id=race_id)
    rl = race.get_label()
    if ns.get_startnodes(end_node=race.get_node(), rel_type="participates"):
        msg = "Race {rl} cannot be removed, participants are attached.".format(rl=rl)
        current_app.logger.error(msg)
        return False
    else:
        # Remove Organization
        ns.remove_node_force(race_id)
        msg = "Race {rl} removed.".format(rl=rl)
        current_app.logger.info(msg)
        return True


def person_list():
    """
    Return the list of persons as person objects.

    :return: List of persons objects. Each person is represented as a dictionary with person nid, name, category,
    category sequence (cat_seq), mf and number of races. The list is sorted on Category, MF and name.
    """
    res = ns.get_nodes('Person')
    person_arr = []
    for node in res:
        person = Person(person_id=node["nid"])
        cat_node = person.get_category()
        if cat_node:
            category = cat_node["name"]
            cat_seq = cat_node["seq"]
        else:
            category = "Not defined"
            cat_seq = 100000
        person_dict = dict(
            nid=person.get_node()["nid"],
            name=person.get_name(),
            category=category,
            cat_seq=cat_seq,
            mf=person.get_mf()["name"],
            races=len(person.get_races4person())
        )
        person_arr.append(person_dict)
        persons_sorted = sorted(person_arr, key=lambda x: (x["cat_seq"], x["mf"], x["name"]))
    return persons_sorted


def person4participant(part_id):
    """
    This method will get the person name from a participant ID. First it will convert the participant ID to a
    participant node. Then it gets the (reverse) relation ('is') from participant to person.
    Finally it will return the id and the name of the person in a hash.
    @param part_id: Node ID of the participant.
    @return: Person dictionary with name and nid, or False if no person found for participant id nid.
    """
    person_nid = ns.get_start_node(end_node_id=part_id, rel_type="is")
    if person_nid:
        person_node = ns.node(person_nid)
        person_name = person_node["name"]
        return dict(name=person_name, nid=person_nid)
    else:
        logging.error("Cannot find person for participant node nid: {part_id}".format(part_id=part_id))
        return False


def participant_list(race_id):
    """
    Returns the list of participants in hash of id, name.
    @param race_id: ID of the race for which current participants are returned
    @return: List of Person Objects. Each person object is represented as a list with id, name of the participant.
    """
    res = ns.get_start_nodes(end_node_id=race_id, rel_type="participates")
    part_arr = []
    for part_nid in res:
        person_nid = ns.get_start_node(end_node_id=part_nid, rel_type="is")
        person_node = ns.node(person_nid)
        attribs = [person_node["nid"], person_node["name"]]
        part_arr.append(attribs)
    return part_arr


def get_cat4part(part_nid):
    """
    This method will return category for the participant. Category will be 'Dames' or 'Heren'.
    @param part_nid: Nid of the participant node.
    @return: Category (Dames or Heren), or False if no category could be found.
    """
    return ns.get_cat4part(part_nid)


def get_category_list():
    """
    This method will return the category list in sequence Young to Old. Category items are returned in list of tuples
    with nid and category name

    :return: List of tuples containing nid and category name.
    """
    return [(catn["nid"], catn["name"]) for catn in ns.get_category_nodes()]


def get_cat_short_cross():
    """
    This method will collect the categories for the short cross.

    :return: Category nodes associated with short cross.
    """
    sc_label = "categoryGroup"
    sc_props = dict(
        name="Korte Cross"
    )
    sc_node = ns.get_node(sc_label, **sc_props)
    return ns.get_startnodes(end_node=sc_node, rel_type=catgroup2cat)


def get_location(nid):
    """
    This method will get a location nid and return the city name. This is because the Location class requires city name
    as creator attribute.

    :param nid: nid of the location node, returned by a selection field.

    :return: city name of the location node, or False if no location found.
    """
    loc = ns.get_node("Location", nid=nid)
    if loc:
        return loc["city"]
    else:
        logging.fatal("Location expected but not found for nid {nid}".format(nid=nid))
        return False


def get_location_list():
    """
    This method will return the location list in sequence. Location items are returned in list of tuples
    with nid and city name

    :return: List of tuples containing nid and city.
    """
    return [(locn["nid"], locn["city"]) for locn in ns.get_location_nodes()]


def get_mf_node(prop):
    """
    This method will return the node that corresponds with the selected man/vrouw value.

    :param prop: Heren / Dames

    :return: Corresponding node
    """
    props = dict(name=prop)
    return ns.get_node("MF", **props)


def get_mf_value(node, rel):
    """
    This method will get mf value to set race in web form. The MF Node is on the end of a relation (person or race.)

    :param node: Start Node for the relation (person or race)

    :param rel: Relation type (person2mf or race2mf)

    :return: mf value (man/vrouw)
    """
    mf_node = ns.get_endnode(start_node=node, rel_type=rel)
    mf = mf_node["name"]
    return mf_tx_inv[mf]


def get_ns():
    """
    This method will return the Neostore Connection object. Neostore connection is created here, and as part of
    application creation. So it is available for anyone (including test modules) who want to use it.

    :return:
    """
    return ns


def points_position(pos):
    """
    This method will return points for a specific position.
    Points are in sequence of arrival: 50 - 45 - 40 - 39 - 38 - ...
    :param pos: Position in the race
    :return: Points associated for this position. Minimum is one point.
    """
    if pos == 1:
        points = 50
    elif pos == 2:
        points = 45
    elif pos == 3:
        points = 40
    else:
        points = 39-pos
    if points < 15:
        points = 15
    return points


def points_for_race(race_id):
    """
    This method will calculate the points for a race and the relative position. The relative position is the position
    in relation to other OLSE runners in the race.
    If race type is 'Deelname', then points_deelname function is
    called. Else points for every race in the organization need to be recalculated.
    :param race_id:
    :return:
    """
    race_obj = Race(race_id=race_id)
    race_type = race_obj.get_racetype()
    if race_type == "Deelname":
        points_deelname(race_id)
    else:
        org_id = race_obj.get_org_id()
        races = get_races_for_org(org_id=org_id)
        for rid in races:
            r_obj = Race(race_id=rid)
            r_type = r_obj.get_racetype()
            if r_type == "Hoofdwedstrijd":
                points_hoofdwedstrijd(rid)
            else:
                points_bijwedstrijd(rid)
    return


def points_bijwedstrijd(race_id):
    """
    This method will assign points to participants in a race for type 'Bijwedstrijd'. It will add 'bijwedstrijd' points
    to every participant. Participant list is sufficient, sequence list is not required. But this function does not
    exist (I think).
    :param race_id:
    :return:
    """
    # Get min value from hoofdwedstrijd.
    # If found, go to next value (45,40,39, ...)
    # If not found, assign 50.
    # Count number of Category participants in the Hoofdwedstrijd. Points for participant is next available one, after
    # all participants on main race have been calculated.
    # This allows to calculate points for the participant.
    main_race_id = ns.get_main_race_id(race_id)
    d_parts = ns.get_nr_participants(race_id=main_race_id, cat="Dames")
    m_parts = ns.get_nr_participants(race_id=main_race_id, cat="Heren")
    d_rel_pos = d_parts + 1
    m_rel_pos = m_parts + 1
    d_points = points_position(d_rel_pos)
    m_points = points_position(m_rel_pos)
    # Now add points for everyone in the race.
    node_list = ns.get_participant_seq_list(race_id)
    if node_list:
        for part in node_list:
            mf = get_cat4part(part["nid"])
            if mf == "Heren":
                points = m_points
                rel_pos = m_rel_pos
            else:
                points = d_points
                rel_pos = d_rel_pos
            props = dict(nid=part["nid"], points=points, rel_pos=rel_pos)
            ns.node_set_attribs(**props)
    return


def points_hoofdwedstrijd(race_id):
    """
    This method will assign points to participants in a race. It gets the participant nids in sequence of arrival. For
    each participant, it will extract Category (Dames, Heren) then assign points for the participant.
    This method should be called for 'Hoofdwedstrijd' only.
    :param race_id:
    :return:
    """
    cnt = dict(Dames=0, Heren=0)
    node_list = ns.get_participant_seq_list(race_id)
    if node_list:
        for part in node_list:
            mf = get_cat4part(part["nid"])
            cnt[mf] += 1
            points = points_position(cnt[mf])
            rel_pos = cnt[mf]
            # Set points for participant
            props = dict(nid=part["nid"], points=points, rel_pos=rel_pos)
            ns.node_set_attribs(**props)
    return


def points_deelname(race_id):
    """
    This method will assign points to participants in a race for type 'Deelname'. It will add 'deelname' points to
    every participant. Participant list is sufficient, sequence list is not required. But this function does not
    exist (I think).
    :param race_id:
    :return:
    """
    node_list = ns.get_participant_seq_list(race_id)
    points = 20
    if node_list:
        for part in node_list:
            props = dict(nid=part["nid"], points=points)
            ns.node_set_attribs(**props)
    return


def points_sum(point_list):
    """
    This function will calculate the total of the points for this participant. For now, the sum of all points is
    calculated.

    :param point_list: list of the points for the participant.

    :return: sum of the points
    """
    # Todo: points for 'deelname' should be calculated separately and in full
    nr_races = 7
    add_points_per_race = 10
    max_list = sorted(point_list)[-nr_races:]
    if len(point_list) > nr_races:
        add_points = (len(point_list) - nr_races) * add_points_per_race
    else:
        add_points = 0
    points = sum(max_list) + add_points
    return points


def results_for_category(cat):
    """
    This method will calculate the points for all participants in a category. Split up in points for wedstrijd and
    points for deelname at this point.

    :param cat: Category to calculate the points

    :return: Sorted list with tuples (name, points, number of races, nid for person).
    """
    res = ns.points_per_category(cat)
    # 1. Add points to list per person
    result_list = {}
    result_total = []
    nid4name = {}
    while res.forward():
        rec = res.current()
        # Remember the nid for this participant.
        nid4name[rec["name"]] = rec["nid"]
        try:
            result_list[rec["name"]].append(rec["points"])
        except KeyError:
            result_list[rec["name"]] = [rec["points"]]
    # 2. Calculate points per person
    for name in result_list:
        result_total.append([name, points_sum(result_list[name]), len(result_list[name]), nid4name[name]])
    result_sorted = sorted(result_total, key=lambda x: -x[1])
    return result_sorted


def participant_seq_list(race_id):
    """
    This method will collect the people in a race in sequence of arrival.

    :param race_id: nid of the race for which the participants are returned in sequence of arrival.

    :return: List of participants items in the race. Each item is a tuple of the person dictionary (from the person
     object) and the participant dictionary (the properties of the participant node). False if no participants in the
     list.
    """
    node_list = ns.get_participant_seq_list(race_id)
    if node_list:
        finisher_list = []
        # If there are finishers, then recordlist has one element, which is a nodelist
        for part in node_list:
            part_obj = Participant(part_id=part["nid"])
            person_obj = Person(person_id=part_obj.get_person_nid())
            person_dict = person_obj.get_dict()
            pers_part_tuple = (person_dict, dict(part))
            finisher_list.append(pers_part_tuple)
        return finisher_list
    else:
        return False


def participant_after_list(race_id):
    """
    This method will return the participant sequence list as a SelectField list. It will call participant_seq_list
    and 'prepend' a value for 'eerste aankomer' (value -1).

    :param race_id: Node ID of the race

    :return: List of the Person objects (list of Person nid and Person name) in sequence of arrival and value for
    'eerste aankomer'.
    """
    eerste = [-1, 'Eerste aankomst']
    finisher_tuple = participant_seq_list(race_id)
    if finisher_tuple:
        finisher_list = [[person['nid'], person['label']] for (person, part) in finisher_tuple]
        finisher_list.insert(0, eerste)
    else:
        finisher_list = [eerste]
    return finisher_list


def participant_last_id(race_id):
    """
    This method will return the nid of the last participant in the race. It calls check participant_after_list and
    fetches the last ID of the runner. This way no special treatment is required in case there are no participants. The
    ID of the last runner will redirect to -1 then.

    :param race_id: Node nid of the race.

    :return: nid of the Person Node of the last finisher so far in the race, -1 if no finishers registered yet.
    """
    finisher_list = participant_after_list(race_id)
    part_arr = finisher_list.pop()
    part_last = part_arr[0]
    return part_last


def participant_first_id(race_id):
    """
    This method will get the ID of the first person in the race.
    @param race_id: Node ID of the race.
    @return: Node ID of the first person so far in the race, False if no participant registered for this race.
    """
    finisher_tuple = participant_seq_list(race_id)
    if finisher_tuple:
        (person, part) = finisher_tuple[0]
        person_id = person['nid']
        return person_id
    else:
        return False


def next_participant(race_id):
    """
    This method will get the list of potential next participants. This is the list of all persons minus the people that
    have been selected already in this race. Also all people that have been selected in other races for this
    organization will no longer be available for selection.
    @param race_id:
    @return: List of the Person objects (Person nid and Person name) that can be selected as participant in the race.
    """
    # Todo: extend to participants that have been selected for this organization (one participation per race per org.)
    # Get Organization for this race
    # org_id = get_org_id(race_id)
    org_id = get_org_id(race_id)
    races = get_races_for_org(org_id)
    participants = []
    for race_id in races:
        parts_race = participant_list(race_id)
        participants += parts_race
    persons = person_list()
    next_participants = [part for part in persons if part not in participants]
    return next_participants


def racetype_list():
    """
    This method will get all the race types. It will return them as a list of tuples with race type ID and race type
    name.
    @return:
    """
    race_nodes = ns.get_nodes("RaceType")
    race_types = []
    for node in race_nodes:
        race_tuple = (node["nid"], node["name"])
        race_types.append(race_tuple)
    return race_types


def relations(node_id):
    """
    This method will return True if the node with node_id has relations, False otherwise.
    @param node_id:
    @return:
    """
    return ns.relations(node_id)


def remove_node_force(node_id):
    """
    This function will remove the node with node ID node_id, including relations with the node.
    @param node_id:
    @return: True if node is deleted, False otherwise
    """
    return ns.remove_node_force(node_id)


def set_race_type(race_id=None, race_type_node=None):
    """
    Check if old node type is defined. If so, remove the link.
    Then add new link.

    :param race_id: Node ID for the race

    :param race_type_node:

    :return:
    """
    race_node = ns.node(race_id)
    # Check if there is a link now.
    curr_race_type_id = ns.get_end_node(race_id, "type")
    if curr_race_type_id:
        ns.remove_relation(race_id, curr_race_type_id, "type")
    ns.create_relation(from_node=race_node, to_node=race_type_node, rel="type")
    return
