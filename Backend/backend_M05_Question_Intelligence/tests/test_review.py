"""FR-5.6 — the human review queue.

The property under test is the gate: a drafted item cannot reach scored use
without a logged human decision, and that decision survives a restart.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend_M05_Question_Intelligence import bank as bank_module
from backend_M05_Question_Intelligence import review as review_module
from backend_M05_Question_Intelligence.app import app
from backend_M05_Question_Intelligence.contracts import ItemStatus, Provenance

from .conftest import CANDIDATE, make_question

STAFF = {"X-Role": "admin", "X-Candidate-Id": "reviewer-1"}
REVIEWER = {"X-Role": "reviewer", "X-Candidate-Id": "faculty-1"}
STUDENT = {"X-Role": "student", "X-Candidate-Id": str(CANDIDATE)}


@pytest.fixture(name="draft")
def draft_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv(review_module.LOG_ENV, str(tmp_path / "review.jsonl"))
    draft = make_question(
        concept="concept:hashing",
        provenance=Provenance.generated,
        status=ItemStatus.draft,
        scored_use_approved=False,
    )
    loaded = bank_module.load()
    original = list(loaded.questions)
    # Alone in the bank: the real bank holds hundreds of drafts, and the queue
    # pages 20 at a time, so a test that must see ITS item cannot share it.
    loaded.questions[:] = [draft]
    yield draft
    loaded.questions[:] = original


@pytest.fixture(name="client")
def client_fixture():
    with TestClient(app) as client:
        yield client


def test_a_student_cannot_see_the_queue(client, draft):
    assert client.get("/v1/review/queue", headers=STUDENT).status_code == 403


def test_anonymous_is_refused(client, draft):
    assert client.get("/v1/review/queue").status_code == 401


def test_a_draft_is_queued_and_not_selectable(client, draft):
    body = client.get("/v1/review/queue", headers=STAFF, params={"limit": 20}).json()
    assert str(draft.id) in {i["id"] for i in body["items"]}
    assert draft.status is ItemStatus.draft and not draft.scored_use_approved


def test_approval_makes_the_item_count_and_is_logged(client, draft):
    r = client.post(
        f"/v1/review/{draft.id}/decision", headers=STAFF, json={"action": "approve"}
    )
    assert r.status_code == 200
    assert r.json()["counts_for_scoring"] is True
    assert draft.scored_use_approved and draft.status is ItemStatus.active
    history = client.get(f"/v1/review/{draft.id}/history", headers=STAFF).json()["history"]
    assert [h["action"] for h in history] == ["approve"]
    assert history[0]["reviewer"] == "reviewer-1"


def test_rejection_requires_a_reason(client, draft):
    r = client.post(f"/v1/review/{draft.id}/decision", headers=STAFF, json={"action": "reject"})
    assert r.status_code == 422
    assert not draft.scored_use_approved
    assert client.post(
        f"/v1/review/{draft.id}/decision",
        headers=STAFF,
        json={"action": "reject", "reason": "reference answer is wrong"},
    ).status_code == 200
    assert draft.status is ItemStatus.retired


def test_edit_keeps_it_in_the_queue_and_records_the_diff(client, draft):
    r = client.post(
        f"/v1/review/{draft.id}/decision",
        headers=STAFF,
        json={"action": "edit", "changes": {"difficulty_band": "hard"}},
    )
    assert r.status_code == 200
    assert draft.difficulty_band.value == "hard"
    assert not draft.scored_use_approved
    assert r.json()["decision"]["diff"]["difficulty_band"] == ["core", "hard"]


def test_an_invalid_edit_changes_nothing_and_logs_nothing(client, draft):
    before = draft.key_points
    r = client.post(
        f"/v1/review/{draft.id}/decision",
        headers=STAFF,
        json={"action": "approve", "changes": {"key_points": [{"statement": "only one"}]}},
    )
    assert r.status_code == 422
    assert draft.key_points == before and not draft.scored_use_approved
    assert review_module.store().history(str(draft.id)) == []


def test_uneditable_fields_are_refused(client, draft):
    r = client.post(
        f"/v1/review/{draft.id}/decision",
        headers=STAFF,
        json={"action": "approve", "changes": {"concepts": []}},
    )
    assert r.status_code == 422


def test_decisions_survive_a_reload(client, draft):
    client.post(f"/v1/review/{draft.id}/decision", headers=STAFF, json={"action": "approve"})
    fresh = make_question(
        id=draft.id,
        provenance=Provenance.generated,
        status=ItemStatus.draft,
        scored_use_approved=False,
    )
    assert review_module.store().replay([fresh]) == 1
    assert fresh.scored_use_approved and fresh.status is ItemStatus.active


def test_an_already_decided_item_is_not_decided_twice(client, draft):
    client.post(f"/v1/review/{draft.id}/decision", headers=STAFF, json={"action": "approve"})
    r = client.post(
        f"/v1/review/{draft.id}/decision",
        headers=STAFF,
        json={"action": "reject", "reason": "x"},
    )
    assert r.status_code == 409


def test_progress_counts_per_track(client, draft):
    body = client.get("/v1/review/progress", headers=STAFF).json()
    assert body["totals"]["pending"] >= 1
    assert sum(body["totals"].values()) >= 1
    assert uuid.UUID(str(draft.id))


def test_the_reviewer_role_can_decide_but_a_researcher_cannot(client, draft):
    researcher = {"X-Role": "researcher", "X-Candidate-Id": "r-1"}
    assert client.get("/v1/review/queue", headers=researcher).status_code == 403
    r = client.post(
        f"/v1/review/{draft.id}/decision", headers=REVIEWER, json={"action": "approve"}
    )
    assert r.status_code == 200
    assert r.json()["decision"]["role"] == "reviewer"


def test_bank_health_reports_what_is_awaiting_review(client, draft):
    before = client.get("/v1/bank/health").json()["awaiting_review"]
    assert before >= 1
    client.post(f"/v1/review/{draft.id}/decision", headers=STAFF, json={"action": "approve"})
    assert client.get("/v1/bank/health").json()["awaiting_review"] == before - 1


def test_upstream_drafts_are_active_but_unapproved_and_still_queue(client, draft):
    """`jobs/draft_items.py` writes provenance=generated, scored_use_approved:
    false and leaves status at its `active` default. The queue keys on the
    approval, not the status word."""
    draft.status = ItemStatus.active
    body = client.get("/v1/review/queue", headers=STAFF).json()
    assert body["remaining"] == 1 and body["items"][0]["id"] == str(draft.id)
    client.post(f"/v1/review/{draft.id}/decision", headers=STAFF, json={"action": "approve"})
    assert client.get("/v1/review/queue", headers=STAFF).json()["remaining"] == 0


def test_a_reviewer_can_skip_an_item_without_deciding_it(client, draft):
    """2026-10-14: with a fixed order and no skip, an item a reviewer was
    unsure about (or had just edited) came back first every time."""
    second = make_question(
        concept="concept:recursion",
        provenance=Provenance.generated,
        status=ItemStatus.draft,
        scored_use_approved=False,
    )
    bank_module.load().questions.append(second)
    first = client.get("/v1/review/queue", headers=REVIEWER).json()
    skipped = client.get("/v1/review/queue", headers=REVIEWER, params={"offset": 1}).json()
    assert first["remaining"] == skipped["remaining"] == 2
    assert first["items"][0]["id"] != skipped["items"][0]["id"]
    # Skipping past the last comes back round to the first.
    wrapped = client.get("/v1/review/queue", headers=REVIEWER, params={"offset": 2}).json()
    assert wrapped["items"][0]["id"] == first["items"][0]["id"]
