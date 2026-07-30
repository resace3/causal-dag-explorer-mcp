"""Build an expected causal graph for an outcome, optionally given an exposure.

Nothing here is estimated. The output is the set of assumptions you would have
to be willing to make *before* running an N-of-1 analysis, drawn from the
knowledge base in `knowledge.py`. Its value is in what it forces you to write
down: which confounders you cannot measure, which mediators would absorb the
effect if you adjusted for them, and which colliders would create a spurious
association if you did.

Roles follow the standard definitions:

* **confounder** — a common cause of exposure and outcome. Adjust for it.
* **mediator** — sits on a directed path from exposure to outcome. Adjusting
  for it removes the very effect you are trying to see.
* **collider** — a common *effect* of two variables. Adjusting for it opens a
  path that was closed, manufacturing an association.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .knowledge import EDGES, Graph, variable

MAX_ANCESTOR_DEPTH = 2


@dataclass
class DagNode:
    id: str
    label: str
    description: str
    role: str
    measured: bool
    lane: str | None
    unit: str | None
    observed: bool = False
    """Whether this variable actually has data on the day being viewed."""

    layer: int = 0
    order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "role": self.role,
            "measured": self.measured,
            "lane": self.lane,
            "unit": self.unit,
            "observed": self.observed,
            "layer": self.layer,
            "order": self.order,
        }


@dataclass
class DagEdge:
    source: str
    target: str
    rationale: str
    strength: str
    lag: str | None
    on_path: bool = False
    """True when the edge lies on a directed exposure → outcome path."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "rationale": self.rationale,
            "strength": self.strength,
            "lag": self.lag,
            "onPath": self.on_path,
        }


@dataclass
class Dag:
    outcome: str
    exposure: str | None
    nodes: list[DagNode] = field(default_factory=list)
    edges: list[DagEdge] = field(default_factory=list)
    adjustment_set: list[str] = field(default_factory=list)
    unmeasured_confounders: list[str] = field(default_factory=list)
    mediators: list[str] = field(default_factory=list)
    colliders: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "exposure": self.exposure,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "adjustmentSet": self.adjustment_set,
            "unmeasuredConfounders": self.unmeasured_confounders,
            "mediators": self.mediators,
            "colliders": self.colliders,
            "notes": self.notes,
            "estimated": False,
            "disclaimer": (
                "Hypothesised structure, not an estimate. Every arrow is an "
                "assumption drawn from published physiology, not something "
                "measured in your data. No effect has been calculated."
            ),
        }


def build_dag(
    outcome: str,
    exposure: str | None = None,
    observed: set[str] | None = None,
) -> Dag:
    """Assemble the expected DAG for `outcome`, optionally given `exposure`."""
    graph = Graph()
    observed = observed or set()

    if outcome not in {edge.target for edge in EDGES} | {edge.source for edge in EDGES}:
        raise ValueError(f"'{outcome}' is not a variable in the causal knowledge base.")
    if exposure == outcome:
        raise ValueError("The exposure and the outcome must be different variables.")

    dag = Dag(outcome=outcome, exposure=exposure)

    if exposure:
        included, mediators, confounders, colliders = _exposure_outcome(graph, exposure, outcome)
    else:
        included, mediators, confounders, colliders = _outcome_only(graph, outcome)

    paths = graph.directed_paths(exposure, outcome) if exposure else []
    path_edges = {
        (path[index], path[index + 1]) for path in paths for index in range(len(path) - 1)
    }

    roles = {node: "context" for node in included}
    roles[outcome] = "outcome"
    if exposure:
        roles[exposure] = "exposure"
    for node in confounders:
        roles.setdefault(node, "confounder")
        if roles[node] == "context":
            roles[node] = "confounder"
    for node in mediators:
        if roles.get(node) == "context":
            roles[node] = "mediator"
    for node in colliders:
        if roles.get(node) == "context":
            roles[node] = "collider"
    for node in included:
        if roles[node] == "context" and node in graph.parents(outcome):
            roles[node] = "direct cause"

    for node in sorted(included):
        info = variable(node)
        dag.nodes.append(
            DagNode(
                id=node,
                label=info.label,
                description=info.description,
                role=roles[node],
                measured=info.measured,
                lane=info.lane,
                unit=info.unit,
                observed=node in observed,
            )
        )

    for edge in EDGES:
        if edge.source in included and edge.target in included:
            dag.edges.append(
                DagEdge(
                    source=edge.source,
                    target=edge.target,
                    rationale=edge.rationale,
                    strength=edge.strength,
                    lag=edge.lag,
                    on_path=(edge.source, edge.target) in path_edges,
                )
            )

    _layout(dag, graph, exposure, outcome)

    measured_confounders = sorted(c for c in confounders if variable(c).measured)
    dag.unmeasured_confounders = sorted(c for c in confounders if not variable(c).measured)
    dag.adjustment_set = measured_confounders
    dag.mediators = sorted(mediators)
    dag.colliders = sorted(colliders)
    dag.notes = _notes(dag, exposure, outcome, observed)
    return dag


def _exposure_outcome(
    graph: Graph, exposure: str, outcome: str
) -> tuple[set[str], set[str], set[str], set[str]]:
    """Nodes relevant to an exposure → outcome question."""
    paths = graph.directed_paths(exposure, outcome)
    on_paths = {node for path in paths for node in path}
    mediators = on_paths - {exposure, outcome}

    exposure_ancestors = graph.ancestors(exposure)
    outcome_ancestors = graph.ancestors(outcome)
    exposure_descendants = graph.descendants(exposure)

    # A confounder is a common cause that is not itself caused by the exposure.
    confounders = {
        node
        for node in exposure_ancestors & outcome_ancestors
        if node not in exposure_descendants and node not in {exposure, outcome}
    }

    # Colliders worth warning about: common effects of two included variables.
    candidates = on_paths | confounders | {exposure, outcome}
    colliders = set()
    for node in {edge.target for edge in EDGES}:
        if node in candidates:
            continue
        parents = set(graph.parents(node))
        if len(parents & candidates) >= 2:
            colliders.add(node)

    included = on_paths | confounders | colliders | {exposure, outcome}
    return included, mediators, confounders, colliders


def _outcome_only(graph: Graph, outcome: str) -> tuple[set[str], set[str], set[str], set[str]]:
    """Without an exposure, show what is believed to cause the outcome."""
    included = {outcome}
    frontier = [outcome]
    for _ in range(MAX_ANCESTOR_DEPTH):
        next_frontier: list[str] = []
        for node in frontier:
            for parent in graph.parents(node):
                if parent not in included:
                    included.add(parent)
                    next_frontier.append(parent)
        frontier = next_frontier

    # With no exposure named, nothing is a confounder or a mediator yet: those
    # roles only exist relative to a specific exposure.
    return included, set(), set(), set()


def _layout(dag: Dag, graph: Graph, exposure: str | None, outcome: str) -> None:
    """Layer nodes left to right by distance from the outcome."""
    depth: dict[str, int] = {outcome: 0}
    included = {node.id for node in dag.nodes}

    changed = True
    while changed:
        changed = False
        for node in included:
            for child in graph.children(node):
                if child in depth and depth.get(node, -1) < depth[child] + 1:
                    depth[node] = depth[child] + 1
                    changed = True

    # Nodes with no directed path to the outcome are its *effects* (colliders,
    # for instance). They have no depth from the loop above, so place them one
    # column right of their deepest parent — otherwise their arrows would be
    # drawn pointing backwards.
    unresolved = [node.id for node in dag.nodes if node.id not in depth]
    for _ in range(len(unresolved) + 1):
        for node_id in unresolved:
            if node_id in depth:
                continue
            parent_depths = [depth[p] for p in graph.parents(node_id) if p in depth]
            if parent_depths:
                depth[node_id] = min(parent_depths) - 1

    max_depth = max(depth.values(), default=0)
    min_depth = min(depth.values(), default=0)
    for node in dag.nodes:
        node.layer = max_depth - depth.get(node.id, min_depth)

    # Longest-path-to-outcome already gives a correct left-to-right ordering:
    # a cause always lands left of its effect. Forcing the exposure to column
    # zero would push its own causes to the right of it, which reads backwards.

    by_layer: dict[int, list[DagNode]] = {}
    for node in sorted(dag.nodes, key=lambda item: (item.layer, item.label)):
        by_layer.setdefault(node.layer, []).append(node)
    for nodes in by_layer.values():
        for index, node in enumerate(nodes):
            node.order = index


def _notes(dag: Dag, exposure: str | None, outcome: str, observed: set[str]) -> list[str]:
    notes: list[str] = []
    outcome_label = variable(outcome).label

    if exposure:
        exposure_label = variable(exposure).label
        if not any(edge.on_path for edge in dag.edges):
            notes.append(
                f"This model contains no directed path from {exposure_label} to "
                f"{outcome_label}. On these assumptions, there is no effect to estimate."
            )
        if dag.mediators:
            labels = ", ".join(variable(node).label for node in dag.mediators)
            notes.append(
                f"Mediators on the path: {labels}. Adjusting for a mediator removes "
                "part of the very effect you are trying to measure."
            )
        if dag.adjustment_set:
            labels = ", ".join(variable(node).label for node in dag.adjustment_set)
            notes.append(f"Measured variables to adjust for: {labels}.")
        else:
            notes.append(
                "No measured confounders were identified for this pair, which is "
                "not the same as there being none."
            )
    else:
        notes.append(
            f"Showing what is believed to cause {outcome_label}. Name an exposure to "
            "see confounders, mediators and an adjustment set for a specific question."
        )

    if dag.unmeasured_confounders:
        labels = ", ".join(variable(node).label for node in dag.unmeasured_confounders)
        notes.append(
            f"Unmeasured common causes: {labels}. No connected source records these, "
            "so their confounding cannot be adjusted away with the data you have."
        )

    unobserved = [
        node.label for node in dag.nodes if node.measured and not node.observed
    ]
    if unobserved:
        notes.append(
            "Measurable but not recorded on this day: "
            + ", ".join(sorted(unobserved))
            + "."
        )

    if dag.colliders:
        labels = ", ".join(variable(node).label for node in dag.colliders)
        notes.append(
            f"Do not condition on: {labels}. These are common effects; adjusting for "
            "one opens a path and can create an association that is not there."
        )

    return notes


#: Which lanes count as evidence that a variable was observed on a given day.
OBSERVED_BY_LANE = {
    "activity": {"exercise", "step_count"},
    "sleep": {"sleep_duration", "sleep_onset", "sleep_efficiency"},
    "heart_rate": {"resting_heart_rate"},
    "hrv": {"hrv"},
    "readiness": {"readiness"},
    "environment": {"light_evening", "light_morning", "room_temperature"},
    "temperature": {"skin_temperature"},
    "presence": {"device_use", "time_away"},
    "location": {"location"},
}


def observed_variables(available_lane_ids: set[str]) -> set[str]:
    """Variables backed by a lane that actually has data on the viewed day."""
    observed = {"day_of_week"}  # always known from the calendar
    for lane, variables in OBSERVED_BY_LANE.items():
        if lane in available_lane_ids:
            observed |= variables
    return observed
