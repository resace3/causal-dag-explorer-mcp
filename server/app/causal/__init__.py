"""Causal hypothesis modelling.

This package proposes structure; it never estimates effects. See `knowledge.py`
for the priors and `dag.py` for how a graph is assembled from them.
"""

from .dag import Dag, build_dag, observed_variables
from .knowledge import EDGES, VARIABLES, CausalEdge, Variable, variable

__all__ = [
    "EDGES",
    "VARIABLES",
    "CausalEdge",
    "Dag",
    "Variable",
    "build_dag",
    "observed_variables",
    "variable",
]
