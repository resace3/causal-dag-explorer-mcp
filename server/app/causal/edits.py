"""Resolve the user's edits against the published causal priors.

The knowledge base in `knowledge.py` is a literature prior and stays read-only.
A user who disagrees with it — or who knows something about themselves that no
paper does — records an *override* instead, and this module folds the two into
the edge list the rest of the app reasons over.

Keeping edits separate from the priors is what lets the app keep answering
"where did this arrow come from?". A user-drawn arrow is still a hypothesis,
exactly like a published one, but it is not the *same* hypothesis, and the
`origin` field carries that distinction through to the drawing.

Adding an edge is checked, not just stored: an arrow that would make the graph
cyclic is rejected, because a cyclic "DAG" breaks path enumeration and is not a
causal model anyone can reason about.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from .knowledge import EDGES, VARIABLES, CausalEdge, Graph, variable


class EdgeOverride(Protocol):
    """The shape `Repository.get_edge_overrides` returns."""

    source: str
    target: str
    action: str
    rationale: str
    strength: str
    lag: str | None


class CausalEditError(ValueError):
    """A rejected edit, with a message meant for the user."""


@dataclass(frozen=True)
class SuppressedEdge:
    """A built-in edge the user has switched off."""

    source: str
    target: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "sourceLabel": variable(self.source).label,
            "targetLabel": variable(self.target).label,
        }


def effective_edges(overrides: Iterable[EdgeOverride]) -> list[CausalEdge]:
    """The knowledge base with the user's additions and removals applied."""
    removed = {(o.source, o.target) for o in overrides if o.action == "remove"}
    edges = [edge for edge in EDGES if (edge.source, edge.target) not in removed]

    known = {(edge.source, edge.target) for edge in edges}
    for override in overrides:
        if override.action != "add":
            continue
        if (override.source, override.target) in known:
            continue  # the knowledge base already says this; nothing to add
        edges.append(
            CausalEdge(
                source=override.source,
                target=override.target,
                rationale=override.rationale or "Added by the user.",
                strength=override.strength or "plausible",  # type: ignore[arg-type]
                lag=override.lag,
                origin="user",
            )
        )
    return edges


def suppressed_edges(overrides: Iterable[EdgeOverride]) -> list[SuppressedEdge]:
    """Built-in edges the user has removed, so they can be put back."""
    removed = {(o.source, o.target) for o in overrides if o.action == "remove"}
    return [
        SuppressedEdge(edge.source, edge.target)
        for edge in EDGES
        if (edge.source, edge.target) in removed
    ]


def validate_addition(source: str, target: str, edges: list[CausalEdge]) -> None:
    """Reject an edge that cannot exist, before it reaches the database."""
    for node, role in ((source, "source"), (target, "target")):
        if node not in VARIABLES:
            raise CausalEditError(
                f"'{node}' is not a variable in the causal model ({role}). "
                "Call GET /api/dag/variables for the list."
            )
    if source == target:
        raise CausalEditError("An arrow cannot start and end at the same variable.")

    if any(edge.source == source and edge.target == target for edge in edges):
        raise CausalEditError(
            f"{variable(source).label} → {variable(target).label} is already in the model."
        )

    # `target` reaching `source` already means this arrow would close a loop.
    if source in Graph(edges=edges).descendants(target, depth=len(VARIABLES)):
        raise CausalEditError(
            f"{variable(source).label} → {variable(target).label} would create a cycle: "
            f"{variable(target).label} already leads back to {variable(source).label}. "
            "A causal graph has to stay acyclic."
        )


def describe(edges: list[CausalEdge]) -> list[dict[str, Any]]:
    """Every effective edge, labelled, for the edge editor."""
    return [
        {
            "source": edge.source,
            "target": edge.target,
            "sourceLabel": variable(edge.source).label,
            "targetLabel": variable(edge.target).label,
            "rationale": edge.rationale,
            "strength": edge.strength,
            "lag": edge.lag,
            "origin": edge.origin,
        }
        for edge in sorted(edges, key=lambda item: (variable(item.source).label, variable(item.target).label))
    ]


def user_strength(value: str | None) -> str:
    """Normalise a submitted strength, defaulting to the cautious option."""
    allowed = {"established", "plausible", "speculative"}
    if value is None:
        return "plausible"
    if value not in allowed:
        raise CausalEditError(f"Strength must be one of: {', '.join(sorted(allowed))}.")
    return value


__all__ = [
    "CausalEditError",
    "SuppressedEdge",
    "describe",
    "effective_edges",
    "suppressed_edges",
    "user_strength",
    "validate_addition",
]
