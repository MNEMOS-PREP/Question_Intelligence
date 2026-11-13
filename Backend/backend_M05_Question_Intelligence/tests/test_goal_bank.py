"""The goal bank (2026-11-12): the questions written for M22's career goals.

What has to stay true as the bank grows: every concept a role needs has
questions at more than one difficulty, the questions are not the same one
reworded, each names a real sub-competency of its concept, and none of them
skipped the human review FR-5.6 requires before an answer counts.
"""

from __future__ import annotations

import pytest
import yaml
from ai_core.guard import identity_headers
from fastapi.testclient import TestClient

from backend_M05_Question_Intelligence import bank as bank_module
from backend_M05_Question_Intelligence.app import app
from backend_M05_Question_Intelligence.contracts import Provenance
from backend_M05_Question_Intelligence.jobs import audit_bank
from backend_M05_Question_Intelligence.ontology import SNAPSHOT

from .conftest import CANDIDATE

#: The concepts M04 had before career goals; everything after is the goal graph.
ORIGINAL = 165


@pytest.fixture(name="client")
def client_fixture():
    with TestClient(app, headers=identity_headers(CANDIDATE)) as client:
        yield client


def _goal_concepts() -> list[str]:
    raw = yaml.safe_load(SNAPSHOT.read_text(encoding="utf-8"))
    return [c["id"] for c in raw["concepts"]][ORIGINAL:]


def test_every_goal_concept_has_questions_at_several_difficulties():
    loaded = bank_module.load()
    findings, coverage = audit_bank.audit(loaded.questions)
    goal = _goal_concepts()
    assert len(goal) >= 150
    thin = [c for c in goal if coverage.get(c, {}).get("items", 0) < 3]
    assert thin == [], f"concepts with fewer than three questions: {thin}"
    flat = [c for c in goal if len(coverage[c]["bands"]) < 2]
    assert flat == [], f"concepts asked at only one difficulty: {flat}"


def test_the_bank_has_no_duplicates_or_bad_facets():
    findings, _ = audit_bank.audit(bank_module.load().questions)
    assert [f for f in findings if f.code in ("duplicate", "near_duplicate", "bad_facet",
                                               "thin_answer", "few_key_points")] == []
    assert [f for f in findings if f.code == "no_spread"] == []


def test_goal_items_wait_for_a_reviewer():
    """FR-5.6: a drafted item is practised, never scored, until a person approves it."""
    goal = set(_goal_concepts())
    items = [q for q in bank_module.load().questions if q.primary_concept in goal]
    assert len(items) >= 450
    assert all(q.provenance is Provenance.generated for q in items)
    assert not any(q.scored_use_approved or q.theta_eligible for q in items)


def test_question_types_and_metadata_are_carried():
    items = [q for q in bank_module.load().questions if q.facet]
    kinds = {q.question_type.value for q in items}
    assert {"conceptual", "debugging", "scenario", "design", "tradeoff", "practical",
            "optimisation", "behavioural"} <= kinds
    sample = next(q for q in items if q.primary_concept == "concept:react")
    assert sample.misconceptions and sample.strong_answer and sample.follow_ups


def test_the_coverage_route_counts_by_difficulty_and_type(client):
    body = client.get("/v1/bank/coverage").json()
    react = body["concepts"]["concept:react"]
    assert react["total"] >= 3 and len(react["by_difficulty"]) >= 2
    assert sum(react["by_type"].values()) == react["total"]
    assert "frontend_verbal" in react["tracks"] and react["facets"]


def test_every_goal_track_is_offered(client):
    offered = {t["round_type"] for t in client.get("/v1/bank/tracks").json()["tracks"]}
    for track in ("frontend_verbal", "backend_verbal", "system_design_verbal", "devops_verbal",
                  "data_eng_verbal", "analytics_verbal", "ai_apps_verbal", "security_verbal",
                  "embedded_verbal", "testing_verbal", "languages_verbal", "mobile_verbal",
                  "product_verbal", "aptitude_verbal"):
        assert track in offered, track


def test_a_browser_does_not_get_the_answer_key(client):
    item = next(q for q in bank_module.load().questions if q.primary_concept == "concept:react")
    body = client.get(f"/v1/questions/{item.id}").json()
    assert body["misconceptions"] == [] and body["strong_answer"] == []
    assert body["question_type"] == item.question_type.value
