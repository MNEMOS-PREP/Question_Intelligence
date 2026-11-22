"""Review by use (usage.py, good_and_bads #4, 2026-11-22).

Since 30 Oct, 60 of 85 answers in M06 were to drafts nobody had reviewed, while
the queue started wherever the bank happened to be written. Now every draft
served is counted, and the queue puts first the ones students keep meeting.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend_M05_Question_Intelligence import bank as bank_module
from backend_M05_Question_Intelligence import usage
from backend_M05_Question_Intelligence.app import app
from backend_M05_Question_Intelligence.contracts import ItemStatus, Provenance

from .conftest import make_question

STAFF = {"X-Role": "reviewer", "X-Candidate-Id": "reviewer-1"}


@pytest.fixture(name="drafts")
def drafts_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("M05_REVIEW_LOG", str(tmp_path / "review.jsonl"))
    made = [
        make_question(
            concept=c,
            provenance=Provenance.generated,
            status=ItemStatus.draft,
            scored_use_approved=False,
        )
        for c in ("concept:hashing", "concept:sorting", "concept:recursion")
    ]
    loaded = bank_module.load()
    original = list(loaded.questions)
    loaded.questions[:] = made
    yield made
    loaded.questions[:] = original


def test_a_draft_served_is_counted_and_an_approved_one_is_not(drafts):
    usage.record(str(drafts[1].id), "dsa_verbal")
    usage.record(str(drafts[1].id), "dsa_verbal")
    usage.record(str(drafts[2].id), "dsa_verbal")
    got = usage.counts()
    assert got[str(drafts[1].id)] == 2 and got[str(drafts[2].id)] == 1
    assert got[str(drafts[0].id)] == 0


def test_the_queue_puts_the_most_asked_first_and_says_how_often(drafts):
    for _ in range(3):
        usage.record(str(drafts[2].id))
    usage.record(str(drafts[1].id))
    with TestClient(app) as client:
        body = client.get("/v1/review/queue", headers=STAFF, params={"limit": 20}).json()
        ids = [i["id"] for i in body["items"]]
        assert ids[:2] == [str(drafts[2].id), str(drafts[1].id)]
        assert [i["times_asked"] for i in body["items"]] == [3, 1, 0]
        assert body["asked_pending"] == 2
        # The old order is still there for whoever wants it.
        params = {"limit": 20, "order": "track"}
        by_track = client.get("/v1/review/queue", headers=STAFF, params=params).json()
        assert {i["id"] for i in by_track["items"]} == set(ids)
        progress = client.get("/v1/review/progress", headers=STAFF).json()
        assert progress["totals"]["asked_pending"] == 2


def test_an_unreadable_log_counts_nothing_and_breaks_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("M05_USAGE_LOG", str(tmp_path / "nowhere" / "usage.jsonl"))
    assert usage.counts() == {}
    (tmp_path / "bad.jsonl").write_text('not json\n{"question_id": "x"}\n', encoding="utf-8")
    monkeypatch.setenv("M05_USAGE_LOG", str(tmp_path / "bad.jsonl"))
    assert usage.counts() == {"x": 1}
