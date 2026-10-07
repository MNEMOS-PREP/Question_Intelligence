"""Drafted items and the tracks they make (2026-10-07).

The bank was twelve seed items, eleven of them DSA: every interview drew from
the same handful, and a machine-learning interview asked DSA. Drafted items
(`jobs/draft_items.py`) fill the tracks — and FR-5.6 still holds: a generated
item no person has approved is asked only when the caller allows drafts, and
the result says its answer is not to be scored.
"""

from __future__ import annotations

from backend_M05_Question_Intelligence import selection as sel
from backend_M05_Question_Intelligence.contracts import Provenance
from backend_M05_Question_Intelligence.jobs.draft_items import concept_tracks

from .conftest import make_question
from .test_api import client_fixture  # noqa: F401 - the `client` fixture


def draft(**kw):
    return make_question(provenance=Provenance.generated, scored_use_approved=False, **kw)


def test_a_draft_is_never_asked_unless_the_caller_allows_drafts(req):
    item = draft()
    assert item not in sel.eligible([item], req)
    assert item in sel.eligible([item], req.model_copy(update={"allow_drafts": True}))


def test_an_approved_item_is_preferred_over_any_draft(req):
    approved = make_question(concept="concept:hashing")
    drafts = [draft(concept="concept:hashing") for _ in range(5)]
    result = sel.select([*drafts, approved], req.model_copy(update={"allow_drafts": True}))
    assert result.question_id == approved.id
    assert result.scored_use is True


def test_a_draft_fills_the_round_when_nothing_approved_fits_and_says_so(req):
    item = draft(concept="concept:hashing")
    result = sel.select([item], req.model_copy(update={"allow_drafts": True}))
    assert result.question_id == item.id
    assert result.scored_use is False, "a draft's answer must not be scored (FR-5.6)"


def test_a_fresh_draft_beats_repeating_a_recent_approved_item(req):
    seen = make_question(concept="concept:hashing")
    fresh = draft(concept="concept:hashing")
    request = req.model_copy(update={"allow_drafts": True, "recent_item_ids": {seen.id}})
    result = sel.select([seen, fresh], request)
    assert result.question_id == fresh.id and result.disclosure is None


def test_each_concepts_track_comes_from_the_heading_it_is_written_under():
    text = """
  # ─── DSA · trees ────────────────
  - id: concept:binary_search_trees
  # ─── CS core · operating systems ──
  - id: concept:deadlocks
  # ─── ML · deep learning ───────────
  - id: concept:backpropagation
  # ─── ML · models ──────────────────
  - id: concept:decision_trees
  # ─── Communication ────────────────
  - id: concept:answer_structuring
"""
    assert concept_tracks(text) == {
        "concept:binary_search_trees": "dsa_verbal",
        "concept:deadlocks": "os_verbal",
        "concept:backpropagation": "dl_verbal",
        "concept:decision_trees": "ml_verbal",
        "concept:answer_structuring": "behavioural",
    }


def test_the_tracks_route_offers_only_what_the_bank_can_ask(client):
    body = client.get("/v1/bank/tracks").json()
    offered = {t["round_type"]: t for t in body["tracks"]}
    assert "dsa_verbal" in offered
    for track in offered.values():
        assert track["approved"] + track["drafts"] > 0, "a track with nothing to ask"
        assert track["title"] and track["group"] in body["groups"] + ["Other"]
    assert offered["dsa_verbal"]["approved"] >= 1
