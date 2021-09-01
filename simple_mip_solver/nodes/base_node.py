from __future__ import annotations

from cylp.cy.CyClpSimplex import CyClpSimplex
from cylp.py.modeling.CyLPModel import CyLPArray
from math import floor, ceil
import numpy as np
from typing import Union, List, TypeVar, Dict, Any

T = TypeVar('T', bound='BaseNode')


class BaseNode:
    """ A node off of which all other types of nodes can be built for running
    against objects defined in algorithms. This default implementation includes
    best-first search and most fractional branching.
    """

    def __init__(self: T, lp: CyClpSimplex, integer_indices: List[int], idx: int = 0,
                 lower_bound: Union[float, int] = -float('inf'), b_idx: int = None,
                 b_dir: str = None, b_val: float = None, depth=0):
        """
        :param lp: model object simplex is run against. Assumed Ax >= b
        :param integer_indices: indices of variables we aim to find integer solutions
        :param lower_bound: starting lower bound on optimal objective value
        for the minimization problem in this node
        :param b_idx: index of the branching variable
        :param b_dir: direction of branching
        :param b_val: initial value of the branching variable
        :param depth: how deep in the tree this node is
        """
        assert isinstance(lp, CyClpSimplex), 'lp must be CyClpSimplex instance'
        assert all(0 <= idx < lp.nVariables and isinstance(idx, int) for idx in
                   integer_indices), 'indices must match variables'
        assert isinstance(idx, int), 'node idx must be integer'
        assert len(set(integer_indices)) == len(integer_indices), \
            'indices must be distinct'
        assert isinstance(lower_bound, float) or isinstance(lower_bound, int), \
            'lower bound must be a float or an int'
        assert (b_dir is None) == (b_idx is None) == (b_val is None), \
            'none are none or all are none'
        assert b_idx in integer_indices or b_idx is None, \
            'branch index corresponds to integer variable if it exists'
        assert b_dir in ['right', 'left'] or b_dir is None, \
            'we can only branch right or left'
        if b_val is not None:
            good_left = 0 < b_val - lp.variablesUpper[b_idx] < 1
            good_right = 0 < lp.variablesLower[b_idx] - b_val < 1
            assert (b_dir == 'left' and good_left) or \
                   (b_dir == 'right' and good_right), 'branch val should be within 1 of both bounds'
        assert isinstance(depth, int) and depth >= 0, 'depth is a positive integer'

        lp.logLevel = 0
        self._lp = lp
        self._integer_indices = integer_indices
        self.idx = idx
        self._var_indices = list(range(lp.nVariables))
        self._row_indices = list(range(lp.nConstraints))
        self.lower_bound = lower_bound
        self.objective_value = None
        self.solution = None
        self.lp_feasible = None
        self.unbounded = None
        self.mip_feasible = None
        self._epsilon = .0001
        self._b_dir = b_dir
        self._b_idx = b_idx
        self._b_val = b_val
        self.depth = depth
        self.search_method = 'best first'
        self.branch_method = 'most fractional'

    def _base_bound(self: T) -> None:
        """Solve the current node with simplex to generate a bound on objective
        values of integer feasible solutions of descendent nodes. If feasible,
        save the run solution.

        :return: a placeholder dictionary for return that the branch and bound
        algorithm expects
        """
        # I make the assumption here that dual infeasible implies primal unbounded.
        # I know this isn't always true, but I am making the educated guess that
        # cylp would have to find a dual infeasibility at the root node before a
        # primal infeasibility for dual simplex via its first phase. In later nodes,
        # dual infeasibility is not possible since we start with dual feasible
        # solution
        self._lp.dual(startFinishOptions='x')
        self.lp_feasible = self._lp.getStatusCode() in [0, 2]  # optimal or dual infeasible
        self.unbounded = self._lp.getStatusCode() == 2
        self.objective_value = self._lp.objectiveValue if self.lp_feasible else float('inf')
        # first cyclpsimplex has variables keyed, rest are list
        sol = self._lp.primalVariableSolution
        self.solution = None if not self.lp_feasible else sol['x'] if \
            type(sol) == dict else sol
        int_var_vals = None if not self.lp_feasible else self.solution[self._integer_indices]
        self.mip_feasible = self.lp_feasible and \
            np.max(np.abs(np.round(int_var_vals) - int_var_vals)) < self._epsilon

    def bound(self: T, **kwargs: Any) -> Dict[str, Any]:
        self._base_bound()
        return {}

    def _base_branch(self: T, branch_idx: int, next_node_idx: int = 1,
                     **kwargs: Any) -> Dict[str, T]:
        """ Creates two new copies of the node with new bounds placed on the variable
        with index <idx>, one with the variable's lower bound set to the ceiling
        of its current value and another with the variable's upper bound set to
        the floor of its current value.

        :param branch_idx: index of variable to branch on
        :param next_node_idx: index that should be assigned to the next node created

        :return: dict of Nodes with the new bounds keyed by direction they branched
        """
        assert isinstance(next_node_idx, int), 'next node index should be integer'
        assert self.lp_feasible, 'must solve before branching'
        assert branch_idx in self._integer_indices, 'must branch on integer index'
        b_val = self.solution[branch_idx]
        assert self._is_fractional(b_val), "index branched on must be fractional"

        # get end basis to warm start the children
        # appears to be tuple  (variable statuses, slack statuses)
        basis = self._lp.getBasisStatus()

        # create new lp's for each direction
        children = {'right': CyClpSimplex(), 'left': CyClpSimplex()}
        for direction, lp in children.items():
            x = lp.addVariable('x', self._lp.nCols)
            l = CyLPArray(self._lp.variablesLower.copy())
            u = CyLPArray(self._lp.variablesUpper.copy())
            if direction == 'left':
                u[branch_idx] = floor(b_val)
            else:
                l[branch_idx] = ceil(b_val)
            lp += l <= x <= u
            lp += CyLPArray(self._lp.constraintsLower.copy()) <= self._lp.coefMatrix * x \
                <= CyLPArray(self._lp.constraintsUpper.copy())
            lp.objective = self._lp.objective
            lp.setBasisStatus(*basis)  # warm start

        # return instances of the subclass that calls this function
        return {'left': type(self)(children['left'], self._integer_indices, next_node_idx,
                                   self.objective_value, branch_idx, 'left', b_val,
                                   self.depth + 1),
                'right': type(self)(children['right'], self._integer_indices, next_node_idx + 1,
                                    self.objective_value, branch_idx, 'right', b_val,
                                    self.depth + 1),
                'next_node_idx': next_node_idx + 2}

    def _strong_branch(self: T, idx: int, iterations: int = 5) -> Dict[str, T]:
        """ Run <iterations> iterations of dual simplex starting from the
        optimal solution of this node after branching on index <idx>. Returns
        bounds of both branches if feasible, None if false

        :param idx: which index to branch on
        :param iterations: how many iterations of dual simplex to perform
        :return: dict of nodes with attributes showing changes in bounds for
        feasible branches. Looks like: {'left': <node from branching down/left>,
        'right': <node from branching up/right>}
        """
        assert isinstance(iterations, int) and iterations > 0, \
            'iterations must be positive integer'
        nodes = {k: v for k, v in self._base_branch(idx).items() if k in ['left', 'right']}
        for n in nodes.values():
            n._lp.maxNumIteration = iterations
            n._lp.dual(startFinishOptions='x')
        return nodes

    def _is_fractional(self: T, value: Union[int, float]) -> bool:
        """Returns True if value fractional, False if not.

        :param value: value to check if fractional
        :return: boolean of value is fractional
        """
        assert isinstance(value, (int, float)), 'value should be a number'
        return min(value - floor(value), ceil(value) - value) > self._epsilon

    @staticmethod
    def _get_fraction(value: Union[int, float]) -> Union[int, float]:
        """Returns fractional part of value

        :param value: value to return decimal part from
        :return: decimal part of value
        """
        assert isinstance(value, (int, float)), 'value should be a number'
        return value - floor(value)

    # implementation of most fractional branch
    @property
    def _most_fractional_index(self: T) -> int:
        """ Returns the index of the integer variable with current value furthest from
        being integer. If one does not exist or the problem has not yet been solved,
        returns None.

        :return furthest_index: index corresponding to variable with most fractional
        value
        """
        furthest_index = None
        furthest_dist = self._epsilon
        if self.lp_feasible:
            for idx in self._integer_indices:
                dist = min(self.solution[idx] - floor(self.solution[idx]),
                           ceil(self.solution[idx]) - self.solution[idx])
                if dist > furthest_dist:
                    furthest_dist = dist
                    furthest_index = idx
        return furthest_index

    def branch(self: T, **kwargs: Any) -> Dict[str, T]:
        """ Creates two new nodes which are branched on the most fractional index
        of this node's LP relaxation solution

        :param kwargs: a dictionary to hold unneeded arguments sent by a general
        branch and bound method
        :return: list of Nodes with the new bounds
        """
        branch_idx = self._most_fractional_index
        return self._base_branch(branch_idx, **kwargs)

    # implementation of best first search
    def __eq__(self: T, other):
        if isinstance(other, BaseNode):
            return self.lower_bound == other.lower_bound
        else:
            raise TypeError('A Node can only be compared with another Node')

    # self < other means self gets better priority in priority queue
    # want priority to go to node with lowest lower_bound
    def __lt__(self: T, other):
        if isinstance(other, BaseNode):
            return self.lower_bound < other.lower_bound
        else:
            raise TypeError('A Node can only be compared with another Node')

    @property
    def _sense(self: T):
        inf = self._lp.getCoinInfinity()
        lower_bounded = self._lp.constraintsLower.max() > -inf
        upper_bounded = self._lp.constraintsUpper.min() < inf
        assert not (lower_bounded and upper_bounded),\
            "all constraints should be bounded same way"
        return '<=' if upper_bounded else '>='

    @property
    def _variables_nonnegative(self: T):
        """ Determines if all variables in the lp model are bound to be nonnegative

        :return:
        """
        return (self._lp.variablesLower >= 0).all()
