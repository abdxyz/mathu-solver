from coinor.cuppy.milpInstance import MILPInstance
# so pulp and pyomo don't believe reading in flat files is a worthwhile feature
# so we don't have much of an option here but to use some sort of commercial solver
try:  # if you don't have gurobipy installed, all tests except those using gurobi will run
    import gurobipy as gu
except ImportError:
    gu = None
import inspect
from math import isclose
import os
import unittest

from simple_mip_solver import BranchAndBound
from simple_mip_solver.algorithms.utils import Utils
from test_simple_mip_solver.example_models import generate_random_variety


class TestModels(unittest.TestCase):
    """ A unit testing base class that can be inherited from to test a BaseNode
    subclass against the suite of random milps in the example_models directory.

    Make sure when using that the child class overwrites the Node attribute with
    the class of the node being tested
    """

    Node = None

    def base_test_models(self, standardize_model=False):
        self.assertTrue(gu, 'gurobipy needed for this test')
        fldr = os.path.join(
            os.path.dirname(os.path.abspath(inspect.getfile(generate_random_variety))),
            'example_models'
        )
        for i, file in enumerate(os.listdir(fldr)):
            print(f'running test {i + 1}')
            pth = os.path.join(fldr, file)
            model = MILPInstance(file_name=pth)
            bb = BranchAndBound(model, self.Node, pseudo_costs={})
            bb.solve()
            gu_mdl = gu.read(pth)
            gu_mdl.setParam(gu.GRB.Param.LogToConsole, 0)
            gu_mdl.optimize()
            if not isclose(bb.objective_value, gu_mdl.objVal, abs_tol=.01):
                print(f'different for {file}')
                print(f'mine: {bb.objective_value}')
                print(f'gurobi: {gu_mdl.objVal}')
            self.assertTrue(isclose(bb.objective_value, gu_mdl.objVal, abs_tol=.01),
                            f'different for {file}')
