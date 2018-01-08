"""
This procedure will test the neostore functionality.
"""

import os
import unittest
from competition import create_app
from competition import neostore

# Import py2neo to test on class types
# from py2neo import Node

# @unittest.skip("Focus on Coverage")
class TestNeoStore(unittest.TestCase):

    def setUp(self):
        # Initialize Environment
        self.app = create_app('testing')
        self.app_ctx = self.app.app_context()
        self.app_ctx.push()
        os.environ['Neo4J_User'] = self.app.config.get('NEO4J_USER')
        os.environ['Neo4J_Pwd'] = self.app.config.get('NEO4J_PWD')
        os.environ['Neo4J_Db'] = self.app.config.get('NEO4J_DB')

        neo4j_params = dict(
            user=os.environ.get('Neo4J_User'),
            password=os.environ.get('Neo4J_Pwd'),
            db=os.environ.get('Neo4J_Db')
        )
        # self.ns = models_graph.ns()
        self.ns = neostore.NeoStore(**neo4j_params)
        self.ns.init_graph()
#       my_env.init_loghandler(__name__, "c:\\temp\\log", "warning")

    def tearDown(self):
        self.app_ctx.pop()

    def test_remove_relation(self):
        # First create 2 nodes and a relation
        label = "TestNode"
        node1_params = dict(
            testname="Node1"
        )
        node1_node = self.ns.create_node(label, **node1_params)
        node2_params = dict(
            testname="Node2"
        )
        node2_node = self.ns.create_node(label, **node2_params)
        rel = "TestRel"
        self.ns.create_relation(from_node=node1_node, rel=rel, to_node=node2_node)
        # Then remove the relation
        self.ns.remove_relation_node(start_node=node1_node, end_node=node2_node, rel_type=rel)
        self.ns.remove_node_force(node1_node["nid"])
        self.ns.remove_node_force(node2_node["nid"])

    def test_get_nodes(self):
        # First create 2 nodes and a relation
        label = "Test_Get_Nodes"
        node1_params = dict(
            testname="Node1"
        )
        # Verify that node does not exist
        self.assertFalse(self.ns.get_node(label, **node1_params))
        self.assertFalse(self.ns.get_nodes(label, **node1_params))
        node1_node = self.ns.create_node(label, **node1_params)
        # Test if Nodes are found
        res = self.ns.get_nodes(label, **node1_params)
        self.assertEqual(len(res), 1)
        res_node_1 = res[0]
        self.assertEqual(node1_node, res_node_1)
        self.assertEqual(res_node_1["testname"], "Node1")
        node2_params = dict(
            testname="Node2"
        )
        node2_node = self.ns.create_node(label, **node2_params)
        res = self.ns.get_node(label)
        self.assertEqual(len(res), 2)
        # Remove res_node_1
        self.ns.remove_node_force(res_node_1["nid"])
        # Get remaining node with label Test_Get_Nodes
        res = self.ns.get_nodes(label)
        res_node_2 = res[0]
        self.assertEqual(res_node_2, node2_node)
        self.ns.remove_node_force(res_node_2["nid"])
        # Verify all nodes are removed
        self.assertFalse(self.ns.get_nodes(label))


if __name__ == "__main__":
    unittest.main()
