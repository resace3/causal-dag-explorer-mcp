"""Editing the causal model.

The knowledge base is a published prior. A user may disagree with it, and these
tests pin the two properties that make disagreeing safe: an edit has to change
the conclusions the DAG draws, and it must never turn the graph into something
that is not a DAG.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.causal.dag import build_dag
from app.causal.edits import (
    CausalEditError,
    effective_edges,
    suppressed_edges,
    validate_addition,
)
from app.causal.knowledge import EDGES
from app.main import create_app


class Override:
    """Stands in for a stored row."""

    def __init__(self, source, target, action, rationale="", strength="plausible", lag=None):
        self.source = source
        self.target = target
        self.action = action
        self.rationale = rationale
        self.strength = strength
        self.lag = lag


@pytest.fixture
def client(repository, sync_service):
    app = create_app()
    routes.configure(repository, sync_service)
    with TestClient(app) as test_client:
        routes.configure(repository, sync_service)
        yield test_client


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


def test_a_user_edge_is_added_and_marked_as_theirs():
    edges = effective_edges([Override("device_use", "readiness", "add", "I notice this.")])
    match = [e for e in edges if e.source == "device_use" and e.target == "readiness"]
    assert len(match) == 1
    assert match[0].origin == "user"
    assert match[0].rationale == "I notice this."


def test_a_removed_edge_disappears_from_the_model():
    before = len(effective_edges([]))
    edges = effective_edges([Override("exercise", "sleep_duration", "remove")])
    assert len(edges) == before - 1
    assert not any(e.source == "exercise" and e.target == "sleep_duration" for e in edges)


def test_published_edges_keep_their_origin():
    assert all(edge.origin == "knowledge_base" for edge in effective_edges([]))


def test_a_suppressed_edge_is_reported_so_it_can_be_restored():
    overrides = [Override("exercise", "sleep_duration", "remove")]
    assert [(e.source, e.target) for e in suppressed_edges(overrides)] == [
        ("exercise", "sleep_duration")
    ]


def test_adding_an_edge_the_knowledge_base_already_has_changes_nothing():
    existing = EDGES[0]
    edges = effective_edges([Override(existing.source, existing.target, "add")])
    match = [e for e in edges if e.source == existing.source and e.target == existing.target]
    assert len(match) == 1
    assert match[0].origin == "knowledge_base"


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def test_an_edge_that_would_create_a_cycle_is_refused():
    """A cyclic graph is not a DAG and would hang path enumeration."""
    edges = effective_edges([])
    # sleep_duration -> hrv already exists, so the reverse closes a loop.
    with pytest.raises(CausalEditError, match="cycle"):
        validate_addition("hrv", "sleep_duration", edges)


def test_a_longer_cycle_is_also_refused():
    edges = effective_edges([])
    # readiness is downstream of sleep_duration via hrv and resting heart rate.
    with pytest.raises(CausalEditError, match="cycle"):
        validate_addition("readiness", "sleep_duration", edges)


def test_a_self_loop_is_refused():
    with pytest.raises(CausalEditError, match="same variable"):
        validate_addition("hrv", "hrv", effective_edges([]))


def test_an_unknown_variable_is_refused():
    with pytest.raises(CausalEditError, match="not a variable"):
        validate_addition("vibes", "hrv", effective_edges([]))


def test_a_duplicate_edge_is_refused():
    with pytest.raises(CausalEditError, match="already in the model"):
        validate_addition("exercise", "sleep_duration", effective_edges([]))


def test_a_legitimate_new_edge_passes():
    validate_addition("device_use", "readiness", effective_edges([]))


# --------------------------------------------------------------------------
# The edit has to change the conclusions
# --------------------------------------------------------------------------


def test_removing_an_edge_removes_it_from_the_built_graph():
    edges = effective_edges([Override("exercise", "sleep_duration", "remove")])
    dag = build_dag("sleep_duration", "exercise", edges=edges)
    assert not any(
        e.source == "exercise" and e.target == "sleep_duration" for e in dag.edges
    ), "a removed edge must not be drawn"
    assert any("no directed path" in note for note in dag.notes), (
        "with its only path gone, the DAG should say there is no effect to estimate"
    )


def test_an_added_edge_can_introduce_a_confounder():
    """An edit that changed nothing downstream would be decoration."""
    baseline = build_dag("readiness", "device_use")
    assert "illness" not in baseline.unmeasured_confounders

    # Say illness also keeps you on your phone: now it confounds the pair.
    edges = effective_edges([Override("illness", "device_use", "add")])
    edited = build_dag("readiness", "device_use", edges=edges)
    assert "illness" in edited.unmeasured_confounders


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def test_the_edges_endpoint_labels_origins(client):
    body = client.get("/api/dag/edges").json()
    assert body["edges"]
    assert {edge["origin"] for edge in body["edges"]} == {"knowledge_base"}
    assert body["suppressed"] == []


def test_adding_an_edge_through_the_api_shows_up_in_the_graph(client):
    response = client.post(
        "/api/dag/edges",
        json={"source": "device_use", "target": "readiness", "rationale": "Late scrolling."},
    )
    assert response.status_code == 200

    listed = client.get("/api/dag/edges").json()["edges"]
    mine = [e for e in listed if e["source"] == "device_use" and e["target"] == "readiness"]
    assert mine and mine[0]["origin"] == "user"

    dag = client.post("/api/dag", json={"outcome": "readiness"}).json()
    assert any(
        e["source"] == "device_use" and e["target"] == "readiness" and e["origin"] == "user"
        for e in dag["edges"]
    )


def test_the_api_refuses_an_edge_that_would_create_a_cycle(client):
    response = client.post("/api/dag/edges", json={"source": "hrv", "target": "sleep_duration"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_causal_edge"
    assert "cycle" in response.json()["error"]["message"]


def test_removing_a_published_edge_suppresses_it_restorably(client):
    response = client.delete("/api/dag/edges/exercise/sleep_duration")
    assert response.status_code == 200
    assert response.json()["restorable"] is True

    body = client.get("/api/dag/edges").json()
    assert not any(
        e["source"] == "exercise" and e["target"] == "sleep_duration" for e in body["edges"]
    )
    assert [(s["source"], s["target"]) for s in body["suppressed"]] == [
        ("exercise", "sleep_duration")
    ]

    restored = client.post("/api/dag/edges/exercise/sleep_duration/restore")
    assert restored.status_code == 200
    after = client.get("/api/dag/edges").json()
    assert any(
        e["source"] == "exercise" and e["target"] == "sleep_duration" for e in after["edges"]
    )
    assert after["suppressed"] == []


def test_removing_a_user_edge_deletes_it_outright(client):
    client.post("/api/dag/edges", json={"source": "device_use", "target": "readiness"})
    response = client.delete("/api/dag/edges/device_use/readiness")
    assert response.status_code == 200
    assert response.json()["restorable"] is False

    body = client.get("/api/dag/edges").json()
    assert body["suppressed"] == []
    assert not any(
        e["source"] == "device_use" and e["target"] == "readiness" for e in body["edges"]
    )


def test_removing_an_edge_that_does_not_exist_is_a_404(client):
    response = client.delete("/api/dag/edges/hrv/exercise")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_causal_edge"


def test_an_invalid_strength_is_refused(client):
    response = client.post(
        "/api/dag/edges",
        json={"source": "device_use", "target": "readiness", "strength": "certain"},
    )
    assert response.status_code == 400
    assert "Strength must be one of" in response.json()["error"]["message"]


def test_editing_never_turns_the_dag_into_an_estimate(client):
    client.post("/api/dag/edges", json={"source": "device_use", "target": "readiness"})
    body = client.post("/api/dag", json={"outcome": "readiness"}).json()
    assert body["estimated"] is False
