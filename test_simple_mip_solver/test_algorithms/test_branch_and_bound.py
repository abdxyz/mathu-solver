from coinor.cuppy.milpInstance import MILPInstance
from cylp.cy.CyClpSimplex import CyClpSimplex, CyLPArray
import inspect
from math import isclose
import numpy as np
from numpy.testing import assert_allclose
import os
from queue import PriorityQueue
import re
import unittest
from unittest.mock import patch

from simple_mip_solver import BaseNode, BranchAndBound, \
    PseudoCostBranchDepthFirstSearchNode as PCBDFSNode, PseudoCostBranchNode
from simple_mip_solver.algorithms.branch_and_bound import BranchAndBoundTree
from simple_mip_solver.algorithms.utils import Utils
from test_simple_mip_solver.example_models import no_branch, small_branch, infeasible, \
    unbounded, infeasible2, h3p1, h3p1_0, h3p1_1, h3p1_2, h3p1_3, h3p1_4, h3p1_5, square, \
    generate_random_variety
from test_simple_mip_solver import example_models


class TestBranchAndBoundTree(unittest.TestCase):

    def test_get_leaves_fails_asserts(self):
        bb = BranchAndBound(small_branch)
        bb.solve()
        self.assertRaisesRegex(AssertionError, "subtree_root_id must belong to the tree",
                               bb._tree.get_leaves, 20)

    def test_get_leaves(self):
        bb = BranchAndBound(small_branch)
        bb.solve()
        leaves = bb._tree.get_leaves(0)
        for node_id in bb._tree.nodes:
            if node_id in leaves:
                self.assertFalse(bb._tree.get_children(node_id))
            else:
                self.assertTrue(len(bb._tree.get_children(node_id)) == 2)

    def test_get_ancestors_fails_asserts(self):
        bb = BranchAndBound(small_branch)
        bb.solve()
        self.assertRaisesRegex(AssertionError, "node_id must belong to the tree",
                               bb._tree.get_ancestors, 20)

    def test_get_ancestors(self):
        bb = BranchAndBound(small_branch)
        bb.solve()
        self.assertTrue(bb._tree.get_ancestors(12) == [9, 7, 4, 1, 0])

    def test_get_node_instances_fails_asserts(self):
        bb = BranchAndBound(small_branch)
        bb.solve()
        self.assertRaisesRegex(AssertionError, 'must be a list', bb._tree.get_node_instances, 1)
        self.assertRaisesRegex(AssertionError, 'node_ids are not in the tree',
                               bb._tree.get_node_instances, [20])
        del bb._tree.nodes[0].attr['node']
        self.assertRaisesRegex(AssertionError, 'must have an attribute for a node instance',
                               bb._tree.get_node_instances, [0])

    def test_get_node_instances(self):
        bb = BranchAndBound(small_branch)
        bb.solve()
        node1, node2 = bb._tree.get_node_instances([1, 2])
        self.assertTrue(node1.idx == 1, 'we should get node with matching id')
        self.assertTrue(isinstance(node1, BaseNode), 'we should get a node')
        self.assertTrue(node2.idx == 2, 'we should get node with matching id')
        self.assertTrue(isinstance(node2, BaseNode), 'we should get a node')


class TestBranchAndBound(unittest.TestCase):

    def setUp(self) -> None:
        self.bb = BranchAndBound(small_branch)
        self.unbounded_root = BaseNode(small_branch.lp, small_branch.integerIndices)
        self.bound_root = BaseNode(small_branch.lp, small_branch.integerIndices)
        self.bound_root.bound()
        self.root_branch_rtn = self.bound_root.branch()

    def test_init(self):
        bb = BranchAndBound(small_branch)
        self.assertTrue(isinstance(bb, Utils))
        self.assertTrue(bb._global_upper_bound == float('inf'))
        self.assertTrue(bb._node_queue.empty())
        self.assertFalse(bb._unbounded)
        self.assertFalse(bb._best_solution)
        self.assertFalse(bb.solution)
        self.assertTrue(bb.status == 'unsolved')
        self.assertFalse(bb.objective_value)
        self.assertTrue(isinstance(bb._tree, BranchAndBoundTree))
        self.assertTrue(list(bb._tree.nodes.keys()) == [0])
        self.assertTrue(bb._tree.nodes[0].attr['node'] is bb._root_node)

    def test_init_fails_asserts(self):
        bb = BranchAndBound(small_branch)
        queue = PriorityQueue()

        # node_queue asserts
        for func in reversed(bb._queue_funcs):
            queue.__dict__[func] = 5
            self.assertRaisesRegex(AssertionError, f'node_queue needs a {func} function',
                                   BranchAndBound, small_branch, BaseNode, queue)

    def test_solve_optimal(self):
        # check and make sure we're good with both nodes
        for Node in [BaseNode, PCBDFSNode]:
            bb = BranchAndBound(small_branch, Node=Node, pseudo_costs={})
            bb.solve()
            self.assertTrue(bb.status == 'optimal')
            self.assertTrue(all(s.is_integer for s in bb.solution))
            self.assertTrue(bb.objective_value == -2)

    def test_solve_infeasible(self):
        # check and make sure we're good with both nodes
        for Node in [BaseNode, PCBDFSNode]:
            bb = BranchAndBound(infeasible, Node=Node, pseudo_costs={})
            bb.solve()
            self.assertTrue(bb.status == 'infeasible')
            self.assertFalse(bb.solution)
            self.assertTrue(bb.objective_value == float('inf'))

    def test_solve_unbounded(self):
        # check and make sure we're good with both nodes
        for Node in [BaseNode, PCBDFSNode]:
            bb = BranchAndBound(unbounded, Node=Node, pseudo_costs={})
            bb.solve()
            self.assertTrue(bb.status == 'unbounded')

        # check we quit even if node_queue nonempty
        with patch.object(bb, '_evaluate_node') as en:
            bb = BranchAndBound(unbounded)
            bb._unbounded = True
            bb.solve()
            self.assertFalse(en.called)

    def test_solve_past_node_limit(self):
        bb = BranchAndBound(unbounded, node_limit=10)
        # check we quit even if node_queue nonempty
        with patch.object(bb, '_evaluate_node') as en:
            bb._evaluated_nodes = 10
            bb.solve()
            self.assertFalse(en.called, 'were past the node limit')

    def test_evaluate_node_infeasible(self):
        bb = BranchAndBound(infeasible)
        bb._evaluate_node(bb._root_node)

        # check attributes
        self.assertTrue(bb._node_queue.empty(), 'inf model should create no nodes')
        self.assertFalse(bb._best_solution, 'best solution should not change')
        self.assertTrue(bb._global_upper_bound == float('inf'), 'shouldnt change')
        self.assertTrue(bb._global_lower_bound == -float('inf'), 'shouldnt change')
        self.assertTrue(bb._evaluated_nodes == 1, 'only one node should be evaluated')

        # check function calls - recycle object since it has attrs already set
        with patch.object(bb, '_process_rtn') as pr, \
                patch.object(bb, '_process_branch_rtn') as pbr, \
                patch.object(bb._root_node, 'bound') as bd, \
                patch.object(bb._root_node, 'branch') as bh:
            bb._evaluate_node(bb._root_node)
            self.assertTrue(pr.call_count == 1)
            self.assertTrue(pbr.call_count == 0)
            self.assertTrue(bd.call_count == 1)
            self.assertTrue(bh.call_count == 0)

    def test_evaluate_node_fractional(self):
        bb = BranchAndBound(small_branch, Node=PCBDFSNode, pseudo_costs={},
                            strong_branch_iters=5)
        bb._evaluate_node(bb._root_node)

        # check attributes
        self.assertFalse(bb._best_solution, 'best solution should not change')
        self.assertTrue(bb._global_upper_bound == float('inf'), 'shouldnt change')
        self.assertTrue(bb._global_lower_bound > -float('inf'), 'should change')
        self.assertTrue(bb._node_queue.qsize() == 2, 'should branch and add two nodes')
        self.assertTrue(bb._kwargs['pseudo_costs'], 'something should be set')
        self.assertTrue(bb._kwargs['strong_branch_iters'], 'something should be set')
        self.assertTrue(bb._evaluated_nodes == 1, 'only one node should be evaluated')

        # check function calls - recycle object since it has attrs already set
        with patch.object(bb, '_process_rtn') as pr, \
                patch.object(bb, '_process_branch_rtn') as pbr, \
                patch.object(bb._root_node, 'bound') as bd, \
                patch.object(bb._root_node, 'branch') as bh:
            bb._evaluate_node(bb._root_node)
            self.assertTrue(pr.call_count == 1)  # direct calls
            self.assertTrue(pbr.call_count == 1)
            self.assertTrue(0 == pbr.call_args.args[0], 'root node id should be first call arg')
            self.assertTrue(bd.call_count == 1)
            self.assertTrue(bh.call_count == 1)

    def test_evaluate_node_integer(self):
        bb = BranchAndBound(no_branch)
        bb._evaluate_node(bb._root_node)

        # check attributes
        self.assertTrue(all(bb._best_solution == [1, 1, 0]))
        self.assertTrue(bb._global_upper_bound == -2)
        self.assertTrue(bb._global_lower_bound == -float('inf'), 'shouldnt change')
        self.assertTrue(bb._node_queue.empty(), 'immediately optimal model should create no nodes')
        self.assertTrue(bb._evaluated_nodes == 1, 'only one node should be evaluated')

        # check function calls - recycle object since it has attrs already set
        with patch.object(bb, '_process_rtn') as pr, \
                patch.object(bb, '_process_branch_rtn') as pbr, \
                patch.object(bb._root_node, 'bound') as bd, \
                patch.object(bb._root_node, 'branch') as bh:
            bb._evaluate_node(bb._root_node)
            self.assertTrue(pr.call_count == 1)
            self.assertTrue(pbr.call_count == 0)
            self.assertTrue(bd.call_count == 1)
            self.assertTrue(bh.call_count == 0)

    def test_evaluate_node_unbounded(self):
        bb = BranchAndBound(unbounded)
        bb._evaluate_node(bb._root_node)

        # check attributes
        self.assertTrue(bb._unbounded)
        self.assertTrue(bb._evaluated_nodes == 1, 'only one node should be evaluated')

    def test_evaluate_node_properly_prunes(self):
        bb = BranchAndBound(no_branch)
        bb._global_upper_bound = -2
        called_node = BaseNode(bb.model.lp, bb.model.integerIndices, lower_bound=-4)
        pruned_node = BaseNode(bb.model.lp, bb.model.integerIndices, lower_bound=0)
        with patch.object(called_node, 'bound') as cnb, \
                patch.object(pruned_node, 'bound') as pnb:
            cnb.return_value = {}
            pnb.return_value = {}
            bb._node_queue.put(called_node)
            bb._node_queue.put(pruned_node)
            bb._evaluate_node(bb._node_queue.get())
            bb._evaluate_node(bb._node_queue.get())
            self.assertTrue(cnb.call_count == 1, 'first node should run')
            self.assertFalse(pnb.call_count, 'second node should get pruned')
            self.assertTrue(bb._node_queue.empty())
            self.assertTrue(bb._evaluated_nodes == 1,
                            'only one node should be evaluated since other pruned')

    def test_process_branch_rtn_fails_asserts(self):
        self.assertRaisesRegex(AssertionError, 'rtn must be a dictionary',
                               self.bb._process_branch_rtn, 0, 'fish')
        rtn = {'right': 5, 'left': 5}
        self.assertRaisesRegex(AssertionError, 'must be int',
                               self.bb._process_branch_rtn, '0', rtn)
        self.assertRaisesRegex(AssertionError, 'must already exist in tree',
                               self.bb._process_branch_rtn, 1, rtn)
        self.assertRaisesRegex(AssertionError, 'value must be type',
                               self.bb._process_branch_rtn, 0, rtn)
        del rtn['left']
        self.assertRaisesRegex(AssertionError, 'must be in the returned',
                               self.bb._process_branch_rtn, 0, rtn)
        self.root_branch_rtn['right'].idx = 0
        rtn = self.bound_root.branch(next_node_idx=0)
        self.assertRaisesRegex(AssertionError, 'give unique node ID',
                               self.bb._process_branch_rtn, 0, rtn)

    def test_process_branch_rtn(self):
        bb = BranchAndBound(small_branch)
        node = BaseNode(small_branch.lp, small_branch.integerIndices, idx=0)
        node.bound()
        rtn = node.branch(next_node_idx=1)
        left_node = rtn['left']
        right_node = rtn['right']
        bb._process_branch_rtn(node.idx, rtn)

        # check attributes
        self.assertTrue(isinstance(bb._node_queue.get(), BaseNode))
        self.assertTrue(isinstance(bb._node_queue.get(), BaseNode))
        self.assertTrue(bb._node_queue.empty())
        children = bb._tree.get_children(node.idx)
        self.assertTrue(len(children) == 2, 'there should be two kids created')
        for child in children:
            self.assertFalse(bb._tree.get_children(child), 'children shouldnt have kids')

        self.assertTrue(bb._tree.get_node(1).attr['node'] is left_node)
        self.assertTrue(bb._tree.get_node(2).attr['node'] is right_node)

        # check function calls
        bb = BranchAndBound(small_branch)
        node = BaseNode(small_branch.lp, small_branch.integerIndices, 0)
        node.bound()
        rtn = node.branch()
        with patch.object(bb, '_process_rtn') as pr, \
                patch.object(bb._tree, 'add_left_child') as alc, \
                patch.object(bb._tree, 'add_right_child') as arc:
            bb._process_branch_rtn(0, rtn)
            self.assertTrue(pr.call_count == 1, 'should call process rtn')
            self.assertTrue(alc.call_count == 1, 'should call add left child')
            self.assertTrue(arc.call_count == 1, 'should call add right child')

    def test_dual_bound_fails_asserts(self):
        bb = BranchAndBound(small_branch)
        self.assertRaisesRegex(AssertionError, 'must solve this instance before',
                               bb.dual_bound, CyLPArray([2.5, 4.5]))
        bb.solve()
        self.assertRaisesRegex(AssertionError, 'only works with CyLP arrays',
                               bb.dual_bound, np.array([2.5, 4.5]))
        self.assertRaisesRegex(AssertionError, 'shape of the RHS being added should match',
                               bb.dual_bound, CyLPArray([4.5]))

        bb = BranchAndBound(infeasible2)
        bb._root_node.lp += np.matrix([[0, -1, -1]]) * bb._root_node.lp.getVarByName('x') >= CyLPArray([-2.5])
        bb.solve()
        self.assertRaisesRegex(AssertionError, 'feature expects the root node to have a single constraint object',
                               bb.dual_bound, CyLPArray([2.5, 4.5]))

    def test_dual_bound(self):

        # Ensure that BranchAndBound.dual_bound generates the dual function
        # that we saw in ISE 418 HW 3 problem 1
        bb = BranchAndBound(h3p1)
        bb.solve()
        bound = bb.dual_bound(CyLPArray([3.5, -3.5]))
        self.assertTrue(bb.objective_value == bound, 'dual should be strong at original rhs')

        prob = {0: h3p1_0, 1: h3p1_1, 2: h3p1_2, 3: h3p1_3, 4: h3p1_4, 5: h3p1_5}
        sol_new = {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 3}
        sol_bound = {0: 0, 1: .5, 2: 1, 3: 2, 4: 2, 5: 2.5}
        for beta in range(6):
            new_bb = BranchAndBound(prob[beta])
            new_bb.solve()
            bound = bb.dual_bound(CyLPArray(np.array([beta, -beta])))
            self.assertTrue(isclose(sol_new[beta], new_bb.objective_value, abs_tol=.01),
                            'new branch and bound objective should match expected')
            self.assertTrue(isclose(sol_bound[beta], bound),
                            'new dual bound value should match expected')
            self.assertTrue(bound <= new_bb.objective_value + .01,
                            'dual bound value should be at most the value function for this rhs')

        bb = BranchAndBound(small_branch)
        bb.solve()
        bound = bb.dual_bound(CyLPArray([2.5, 4.5]))

        # just make sure the dual bound works here too
        self.assertTrue(bound <= -5.99,
                        'dual bound value should be at most the value function for this rhs')

        # check function calls
        bb = BranchAndBound(small_branch)
        bb.solve()
        bound_duals = [bb._bound_dual(n.lp) for n in bb._tree.get_node_instances([6, 12, 10, 8, 2])]
        with patch.object(bb, '_bound_dual') as bd:
            bd.side_effect = bound_duals
            bound = bb.dual_bound(CyLPArray([3, 3]))
            self.assertTrue(bd.call_count == 5)

        bb = BranchAndBound(small_branch)
        bb.solve()
        bound = bb.dual_bound(CyLPArray([3, 3]))
        with patch.object(bb, '_bound_dual') as bd:
            bound = bb.dual_bound(CyLPArray([1, 1]))
            self.assertFalse(bd.called)

    def test_dual_bound_many_times(self):
        pattern = re.compile('evaluation_(\d+).mps')
        fldr_pth = os.path.join(os.path.dirname(os.path.abspath(inspect.getfile(example_models))),
                                'example_value_functions')
        for count, sub_fldr in enumerate(os.listdir(fldr_pth)):
            print(f'dual bound {count}')
            sub_fldr_pth = os.path.join(fldr_pth, sub_fldr)
            evals = {}
            for file in os.listdir(sub_fldr_pth):
                eval_num = int(pattern.search(file).group(1))
                instance = MILPInstance(file_name=os.path.join(sub_fldr_pth, file))
                bb = BranchAndBound(instance, PseudoCostBranchNode, pseudo_costs={})
                bb.solve()
                evals[eval_num] = bb
            instance_0 = evals[0]
            for bb in evals.values():
                # all problems were given as <=, so their constraints were flipped by default
                self.assertTrue(instance_0.dual_bound(CyLPArray(-bb.model.b)) <=
                                bb.objective_value + .01, 'dual_bound should be less')

    def test_bound_dual(self):
        bb = BranchAndBound(infeasible2)
        bb._root_node.lp += np.matrix([[0, -1, -1]]) * bb._root_node.lp.getVarByName('x') >= CyLPArray([-2.5])
        bb.solve()
        terminal_nodes = bb._tree.get_node_instances(bb._tree.get_leaves(0))
        infeasible_nodes = [n for n in terminal_nodes if n.lp_feasible is False]
        n = infeasible_nodes[0]
        lp = bb._bound_dual(n.lp)

        # test that we get a CyClpSimplex object back
        self.assertTrue(isinstance(lp, CyClpSimplex), 'should return CyClpSimplex instance')

        # same variables plus extra 's'
        self.assertTrue({v.name for v in lp.variables} == {'x', 's_0', 's_1'},
                        'x should already exist and s_1 and s_2 should be added')
        old_x = n.lp.getVarByName('x')
        new_x, s_0, s_1 = lp.getVarByName('x'), lp.getVarByName('s_0'), lp.getVarByName('s_1')

        # same variable bounds, plus s >= 0
        self.assertTrue(all(new_x.lower == old_x.lower) and all(new_x.upper == old_x.upper),
                        'x should have the same bounds')
        self.assertTrue(all(s_0.lower == [0, 0]) and all(s_0.upper > [1e300, 1e300]), 's_0 >= 0')
        self.assertTrue(all(s_1.lower == [0]) and all(s_1.upper > 1e300), 's_1 >= 0')

        # same constraints, plus slack s
        self.assertTrue(lp.nConstraints == 3, 'should have same number of constraints')
        self.assertTrue((lp.constraints[0].varCoefs[new_x] == np.array([[-1, -1, 0], [0, 0, -1]])).all(),
                        'x coefs should stay same')
        self.assertTrue((lp.constraints[0].varCoefs[s_0] == np.matrix(np.identity(2))).all(),
                        's_0 should have coef of 2-D identity')
        self.assertTrue(all(lp.constraints[1].varCoefs[new_x] == np.array([0, -1, -1])),
                        'x coefs should stay same')
        self.assertTrue(lp.constraints[1].varCoefs[s_1] == np.matrix(np.identity(1)),
                        's_0 should have coef of 1-D identity')
        self.assertTrue(all(lp.constraints[0].lower == np.array([1, -1])) and
                        all(lp.constraints[0].upper >= np.array([1e300])),
                        'constraint bounds should remain same')
        self.assertTrue(lp.constraints[1].lower == np.array([-2.5]) and
                        lp.constraints[1].upper >= np.array([1e300]),
                        'constraint bounds should remain same')

        # same objective, plus large s coefficient
        self.assertTrue(all(lp.objective == np.array([-1, -1, 0, bb._M, bb._M, bb._M])))

        # problem is now feasible
        self.assertTrue(lp.getStatusCode() == 0, 'lp should now be optimal')

    def test_bound_dual_fails_asserts(self):
        bb = BranchAndBound(infeasible)
        bb.solve()
        terminal_nodes = bb._tree.get_node_instances(bb._tree.get_leaves(0))
        infeasible_nodes = [n for n in terminal_nodes if n.lp_feasible is False]
        n = infeasible_nodes[0]
        n.lp.addVariable('s_0', 1)
        self.assertRaisesRegex(AssertionError, "variable 's_0' is a reserved name",
                               bb._bound_dual, n.lp)
        self.assertRaisesRegex(AssertionError, "must give CyClpSimplex instance",
                               bb._bound_dual, n)

    def test_find_strong_disjunctive_cut_fails_asserts(self):
        bb = BranchAndBound(small_branch)
        bb.solve()

        self.assertRaisesRegex(AssertionError, 'parent must already exist in tree',
                               bb.find_strong_disjunctive_cut, 50)

        terminal_nodes = bb._tree.get_node_instances(bb._tree.get_leaves(0))
        disjunctive_nodes = [n for n in terminal_nodes if n.lp_feasible is not False]
        n = disjunctive_nodes[0]
        n.lp.addVariable('d', 3)

        self.assertRaisesRegex(AssertionError, 'Each disjunctive term should have the same variables',
                               bb.find_strong_disjunctive_cut, 0)

    def test_find_strong_disjunctive_cut(self):
        bb = BranchAndBound(square)
        bb.solve()
        pi, pi0 = bb.find_strong_disjunctive_cut(0)
        assert_allclose(pi, np.array([-1, 0]), atol=.01)
        self.assertTrue(isclose(pi0, -1))

        bb = BranchAndBound(small_branch)
        bb.solve()
        pi, pi0 = bb.find_strong_disjunctive_cut(0)
        assert_allclose(pi, np.array([0, 0, -.5]), atol=.01)
        self.assertTrue(isclose(pi0, -.5))

    def test_find_strong_disjunctive_cut_many_times(self):
        fldr = os.path.join(
            os.path.dirname(os.path.abspath(inspect.getfile(generate_random_variety))),
            'example_models'
        )
        for i, file in enumerate(os.listdir(fldr)):
            if i >= 10:
                break
            print(f'running test {i + 1}')
            pth = os.path.join(fldr, file)
            model = MILPInstance(file_name=pth)
            bb = BranchAndBound(model)
            bb.solve()
            pi, pi0 = bb.find_strong_disjunctive_cut(0)

            # ensure we cut off the root solution
            self.assertTrue(sum(pi * bb._root_node.solution) <= pi0)

            # ensure we don't cut off disjunctive mins
            for n in bb._tree.get_node_instances(bb._tree.get_leaves(0)):
                if n.lp_feasible:
                    self.assertTrue(sum(pi * n.solution) >= pi0 - .01)


if __name__ == '__main__':
    unittest.main()
