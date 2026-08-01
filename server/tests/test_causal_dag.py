"""The DAG proposes structure. It must never claim to have estimated anything."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.causal.dag import build_dag, observed_variables
from app.causal.knowledge import EDGES, VARIABLES, Graph
from app.main import create_app


@pytest.fixture
def client(repository, sync_service):
    app = create_app()
    routes.configure(repository, sync_service)
    with TestClient(app) as test_client:
        routes.configure(repository, sync_service)
        yield test_client


# --------------------------------------------------------------------------
# The knowledge base itself
# --------------------------------------------------------------------------


def test_the_graph_is_acyclic():
    """A cyclic 'DAG' is not a DAG, and would hang path enumeration."""
    graph = Graph()
    for node in VARIABLES:
        assert node not in graph.descendants(node), f"{node} is its own ancestor"


def test_every_edge_connects_known_variables():
    for edge in EDGES:
        assert edge.source in VARIABLES, f"unknown source {edge.source}"
        assert edge.target in VARIABLES, f"unknown target {edge.target}"


# --------------------------------------------------------------------------
# The whole model — what the DAG tab shows, with no question asked
# --------------------------------------------------------------------------


def test_the_whole_model_holds_every_variable_and_every_arrow():
    """The tab is the model itself, so nothing may be filtered out of it.

    A variable missing here is one no arrow can be drawn to, and the arrows
    worth adding by hand are precisely the ones to variables no source records.
    """
    dag = build_dag()
    assert {node.id for node in dag.nodes} == set(VARIABLES)
    assert len(dag.edges) == len(EDGES)
    assert dag.outcome is None
    assert dag.exposure is None


def test_the_whole_model_assigns_no_roles():
    """Confounder and mediator are relations to a question, not properties.

    Labelling a node "confounder" with no exposure named would be asserting
    something about a comparison nobody has set up.
    """
    dag = build_dag()
    assert {node.role for node in dag.nodes} == {"context"}
    assert dag.adjustment_set == []
    assert dag.mediators == []
    assert dag.colliders == []
    assert not any(edge.on_path for edge in dag.edges)


def test_the_whole_model_still_refuses_to_look_like_an_estimate():
    payload = build_dag().to_dict()
    assert payload["estimated"] is False
    assert "not an estimate" in payload["disclaimer"]


def test_an_exposure_without_an_outcome_is_refused():
    """Half a question is not a question, and would silently show everything."""
    with pytest.raises(ValueError, match="relative to an outcome"):
        build_dag(exposure="exercise")


def test_the_whole_model_says_which_variables_nothing_records():
    dag = build_dag(observed=set())
    assert any("No connected source records" in note for note in dag.notes)


def test_the_api_returns_the_whole_model_when_no_outcome_is_named(client):
    response = client.post("/api/dag", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] is None
    assert len(body["nodes"]) == len(VARIABLES)
    assert body["estimated"] is False


def test_naming_an_outcome_still_narrows_the_graph(client):
    """The whole-model view is the default, not the only thing available.

    `get_expected_dag` and the API still answer a specific question, which is
    what makes the adjustment set and the collider warnings reachable at all.
    """
    whole = client.post("/api/dag", json={}).json()
    narrowed = client.post("/api/dag", json={"outcome": "sleep_duration"}).json()
    assert len(narrowed["nodes"]) < len(whole["nodes"])
    assert narrowed["outcome"] == "sleep_duration"


def test_every_edge_states_a_rationale_and_a_strength():
    """An arrow without a stated reason is an assertion, not a hypothesis."""
    for edge in EDGES:
        assert edge.rationale.strip(), f"{edge.source}->{edge.target} has no rationale"
        assert edge.strength in {"established", "plausible", "speculative"}


def test_unmeasured_variables_exist_in_the_knowledge_base():
    """Omitting unmeasurable causes is how a DAG quietly misleads."""
    unmeasured = {node for node, info in VARIABLES.items() if not info.measured}
    assert {"stress", "alcohol", "illness"} <= unmeasured


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


def test_a_common_cause_is_reported_as_a_confounder():
    dag = build_dag("sleep_duration", "exercise")
    roles = {node.id: node.role for node in dag.nodes}
    # Work schedule causes both exercise and sleep timing.
    assert roles["work_schedule"] == "confounder"
    assert "work_schedule" in dag.unmeasured_confounders


def test_a_variable_on_the_path_is_a_mediator_not_a_confounder():
    dag = build_dag("sleep_onset", "light_evening")
    roles = {node.id: node.role for node in dag.nodes}
    assert roles["circadian_phase"] == "mediator"
    assert "circadian_phase" in dag.mediators
    assert "circadian_phase" not in dag.adjustment_set


def test_the_adjustment_set_never_contains_a_mediator():
    for outcome, exposure in [
        ("sleep_duration", "exercise"),
        ("sleep_onset", "light_evening"),
        ("readiness", "sleep_duration"),
    ]:
        dag = build_dag(outcome, exposure)
        assert not set(dag.adjustment_set) & set(dag.mediators), (
            f"{exposure}->{outcome} would adjust away its own effect"
        )


def test_the_adjustment_set_contains_only_measured_variables():
    dag = build_dag("sleep_duration", "exercise")
    for node in dag.adjustment_set:
        assert VARIABLES[node].measured, f"cannot adjust for unmeasured {node}"


def test_unmeasured_confounders_are_reported_rather_than_dropped():
    dag = build_dag("sleep_duration", "exercise")
    assert dag.unmeasured_confounders
    joined = " ".join(dag.notes)
    assert "cannot be adjusted away" in joined


def test_colliders_are_flagged_with_a_do_not_condition_warning():
    dag = build_dag("sleep_duration", "exercise")
    assert dag.colliders
    assert any("Do not condition on" in note for note in dag.notes)


def test_the_exposure_and_outcome_keep_their_roles():
    dag = build_dag("readiness", "sleep_duration")
    roles = {node.id: node.role for node in dag.nodes}
    assert roles["sleep_duration"] == "exposure"
    assert roles["readiness"] == "outcome"


# --------------------------------------------------------------------------
# Outcome-only mode
# --------------------------------------------------------------------------


def test_without_an_exposure_the_graph_shows_causes_of_the_outcome():
    dag = build_dag("readiness")
    ids = {node.id for node in dag.nodes}
    assert "readiness" in ids
    assert {"hrv", "resting_heart_rate", "sleep_duration"} <= ids
    # Roles like confounder only exist relative to an exposure.
    assert dag.adjustment_set == []
    assert dag.mediators == []
    assert any("Name an exposure" in note for note in dag.notes)


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------


def test_a_cause_is_never_drawn_to_the_right_of_its_effect():
    """Otherwise the arrows read backwards."""
    dag = build_dag("sleep_duration", "exercise")
    layers = {node.id: node.layer for node in dag.nodes}
    for edge in dag.edges:
        assert layers[edge.source] < layers[edge.target], (
            f"{edge.source} (layer {layers[edge.source]}) is drawn at or right of "
            f"{edge.target} (layer {layers[edge.target]})"
        )


def test_layout_holds_for_outcome_only_graphs():
    dag = build_dag("readiness")
    layers = {node.id: node.layer for node in dag.nodes}
    for edge in dag.edges:
        assert layers[edge.source] < layers[edge.target]


# --------------------------------------------------------------------------
# Observation annotation
# --------------------------------------------------------------------------


def test_variables_are_marked_by_whether_the_day_recorded_them():
    observed = observed_variables({"activity", "sleep"})
    dag = build_dag("sleep_duration", "exercise", observed)
    by_id = {node.id: node for node in dag.nodes}

    assert by_id["exercise"].observed is True
    assert by_id["sleep_duration"].observed is True
    assert by_id["hrv"].observed is False
    assert any("not recorded on this day" in note for note in dag.notes)


def test_an_unmeasured_variable_is_never_marked_observed():
    dag = build_dag("sleep_duration", "exercise", observed_variables(set(VARIABLES)))
    for node in dag.nodes:
        if not node.measured:
            assert node.observed is False


# --------------------------------------------------------------------------
# Honesty of the payload
# --------------------------------------------------------------------------


def test_the_payload_says_it_is_not_an_estimate():
    payload = build_dag("sleep_duration", "exercise").to_dict()
    assert payload["estimated"] is False
    assert "not an estimate" in payload["disclaimer"]


def test_no_effect_size_or_p_value_is_ever_reported():
    """The app proposes structure; it must not appear to have measured anything."""
    payload = build_dag("sleep_duration", "exercise").to_dict()
    serialized = str(payload).lower()
    for banned in ("p_value", "p-value", "effect_size", "coefficient", "correlation", "r²"):
        assert banned not in serialized


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def test_the_variables_endpoint_lists_candidates(client):
    body = client.get("/api/dag/variables").json()
    ids = {item["id"] for item in body["variables"]}
    assert {"sleep_duration", "exercise", "stress"} <= ids
    assert any(item["measured"] is False for item in body["variables"])


def test_the_dag_endpoint_builds_a_graph(client):
    response = client.post(
        "/api/dag", json={"outcome": "sleep_duration", "exposure": "exercise"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["estimated"] is False
    assert body["nodes"] and body["edges"]
    assert body["outcome"] == "sleep_duration"


def test_the_dag_endpoint_works_without_an_exposure(client):
    body = client.post("/api/dag", json={"outcome": "readiness"}).json()
    assert body["exposure"] is None
    assert body["nodes"]


def test_an_unknown_variable_is_rejected_with_a_pointer(client):
    response = client.post("/api/dag", json={"outcome": "vibes"})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_causal_question"
    assert "/api/dag/variables" in body["error"]["hint"]


def test_the_same_variable_cannot_be_both_exposure_and_outcome(client):
    response = client.post(
        "/api/dag", json={"outcome": "sleep_duration", "exposure": "sleep_duration"}
    )
    assert response.status_code == 400
    assert "must be different" in response.json()["error"]["message"]
