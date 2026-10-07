"""The HTTP surface — §7, and the clone-and-run promise of §6.11."""

from __future__ import annotations

import uuid

import pytest
from ai_core import service
from ai_core.guard import identity_headers
from fastapi.testclient import TestClient

from backend_M05_Question_Intelligence import bank as bank_module
from backend_M05_Question_Intelligence.app import app

from .conftest import CANDIDATE


@pytest.fixture(name="client")
def client_fixture():
    # Signed in as the student these tests act for: M05's routes are guarded
    # (Platform_Core v0.11.0), and every real caller forwards one.
    with TestClient(app, headers=identity_headers(CANDIDATE)) as client:
        yield client


# ── meta ─────────────────────────────────────────────────────────────────


def test_health_says_which_ontology_it_is_running_on(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["module"] == "M05"
    assert body["ontology_source"] == "snapshot"
    # M04's ontology carries reviewed: false until the faculty walk lands, and
    # a bank tagged against an unreviewed ontology is a known state rather than
    # a surprise found in a pilot.
    assert body["ontology_reviewed"] is False
    assert body["calibration"] == "none"


def test_deps_declares_no_required_upstream(client):
    body = client.get("/v1/deps").json()
    assert body["module"] == "M05"
    assert all(not d["required"] for d in body["dependencies"])


def test_deps_names_what_breaks_without_each_upstream(client):
    for dependency in client.get("/v1/deps").json()["dependencies"]:
        assert dependency["on_missing"].strip(), f"{dependency['module_id']} has no story"


def test_the_module_runs_without_m04(client):
    """§6.11 — the whole reason the snapshot exists. M04's ontology ships
    `reviewed: false` until a faculty walk lands, and waiting would idle this
    module for weeks."""
    body = client.get("/v1/ontology").json()
    assert body["source"] == "snapshot"
    assert body["n_concepts"] == 156  # 120 + 36 for ML (2026-10-07)


# ── the bank ─────────────────────────────────────────────────────────────


def test_bank_health_reports_what_to_author_next(client):
    """§8.2. Without the thin list you write more array questions, because
    array questions are easy to write."""
    body = client.get("/v1/bank/health").json()
    assert body["active"] > 0
    assert body["playlist"] > 0, "§6.8 step 5 has no last line without a playlist"
    assert body["n_thin"] > 0
    assert "authoring" in body["note"].lower()


def test_every_seed_item_is_scorable(client):
    """A bank item that M13 cannot score is not an item. Checked over the whole
    bank rather than at authoring time, because the failure arrives when
    somebody adds the 201st."""
    for question in bank_module.load().questions:
        assert question.reference_answer.strip()
        assert len(question.key_points) >= 2
        assert question.rubric_round_type in question.round_types


# ── the package M13 receives ─────────────────────────────────────────────


def test_the_package_matches_what_m13_parses(client):
    """M13's `adapters.QuestionPackage` declares `round_type` singular and
    `concepts` as a mapping. A contract is what the other side can parse."""
    question = next(
        q
        for q in bank_module.load().questions
        if "dsa_verbal" in q.round_types and q.scored_use_approved
    )
    body = client.get(
        f"/v1/questions/{question.id}/package",
        params={"round_type": "dsa_verbal"},
        headers=service.headers(),
    ).json()

    assert body["round_type"] == "dsa_verbal"
    assert isinstance(body["concepts"], dict)
    assert body["stem"] and body["reference_answer"]
    assert len(body["key_points"]) >= 2
    assert body["item"] is not None and body["item"]["irt_model"] == "grm"
    assert body["item"]["params_source"] == "prior"


def test_a_package_for_the_wrong_round_type_is_refused(client):
    question = bank_module.load().questions[0]
    response = client.get(
        f"/v1/questions/{question.id}/package",
        params={"round_type": "hr_behavioural"},
        headers=service.headers(),
    )
    assert response.status_code == 422


# ── selection ────────────────────────────────────────────────────────────


def _request(**overrides) -> dict:
    body = {
        "candidate_id": str(CANDIDATE),
        "session_id": str(uuid.uuid4()),
        "round_type": "dsa_verbal",
        "theta_provisional": {},
        "time_remaining_s": 1800,
    }
    body.update(overrides)
    return body


def test_select_returns_a_real_item_from_a_cold_bank(client):
    body = client.post("/v1/questions/select", json=_request()).json()
    assert bank_module.load().get(uuid.UUID(body["question_id"])) is not None
    assert body["round_type"] == "dsa_verbal"
    assert body["n_categories"] == 5
    assert body["params_source"] == "prior"
    assert body["expected_information"] > 0


def test_a_thin_bank_is_a_409_not_a_500(client):
    """§6.8 step 5 — the caller ends the round and tells the student honestly,
    which it cannot do if this looks like a crash."""
    response = client.post("/v1/questions/select", json=_request(round_type="ml_viva"))
    assert response.status_code == 409
    assert "thin" in response.json()["detail"]


def test_selection_never_repeats_within_a_session(client):
    """AC-5.1. The complaint this module is named for."""
    seen: set[str] = set()
    for _ in range(6):
        body = client.post(
            "/v1/questions/select", json=_request(seen_item_ids=sorted(seen))
        ).json()
        assert body["question_id"] not in seen
        seen.add(body["question_id"])


# ── the session's provisional θ (§6.10) ──────────────────────────────────


def test_a_session_is_seeded_updated_and_discarded(client):
    session_id = str(uuid.uuid4())

    seeded = client.post(
        f"/v1/sessions/{session_id}/theta/seed",
        json={
            "candidate_id": str(CANDIDATE),
            "posterior": {"concept:hashing": 0.5},
            "snapshot_id": "m04:2026-08-18",
        },
    ).json()
    assert seeded["seeded_from"] == "m04:2026-08-18"

    observed = client.post(
        f"/v1/sessions/{session_id}/theta/observe",
        json={
            "concept_id": "concept:hashing",
            "outcome": {"turn_id": str(uuid.uuid4()), "band": "above", "confidence": 0.8},
        },
    ).json()
    assert observed["theta_provisional"] > 0.5, "a strong turn must move the estimate up"

    closed = client.post(
        f"/v1/sessions/{session_id}/close", json={"posterior": {"concept:hashing": 0.55}}
    ).json()
    assert closed["updates"] == 1
    # Closing twice is a 404: the estimate is gone, not archived.
    assert client.post(f"/v1/sessions/{session_id}/close", json={}).status_code == 404


@pytest.mark.gate
def test_the_provisional_estimate_is_not_readable_over_http(client):
    """AC-5.12. Two stored ability numbers is two answers to "how good is this
    student", and the cheap one is the one that leaks into a report. There is
    deliberately no GET for it."""
    session_id = str(uuid.uuid4())
    client.post(
        f"/v1/sessions/{session_id}/theta/seed",
        json={"candidate_id": str(CANDIDATE), "posterior": {"concept:hashing": 1.4}},
    )
    assert client.get(f"/v1/sessions/{session_id}/theta").status_code == 404
    assert client.get(f"/v1/sessions/{session_id}").status_code == 404


def test_divergence_from_m04_is_reported_not_hidden(client):
    """§6.10 — a ProbeStrategist that systematically disagrees with the real
    evaluator is a fixable problem and an invisible one."""
    session_id = str(uuid.uuid4())
    client.post(
        f"/v1/sessions/{session_id}/theta/seed",
        json={"candidate_id": str(CANDIDATE), "posterior": {"concept:hashing": 1.5}},
    )
    closed = client.post(
        f"/v1/sessions/{session_id}/close", json={"posterior": {"concept:hashing": 0.2}}
    ).json()
    assert closed["divergence"]["concept:hashing"] > 0.5


# ── flagging (FR-5.19 / EC-5.9) ──────────────────────────────────────────


def test_flagging_excludes_the_item_and_is_honest_about_what_it_cannot_do(client):
    """M04 names EC-5.9 as a retraction source. That half is not wired, and the
    response says so rather than implying the student has been fully served."""
    question = bank_module.load().questions[-1]
    body = client.post(
        f"/v1/questions/{question.id}/flag", json={"reason": "ambiguous", "note": ""}
    ).json()

    assert body["excluded_from_selection"] is True
    assert body["retraction_sent"] is False
    assert "still be moving mastery" in body["note"]
