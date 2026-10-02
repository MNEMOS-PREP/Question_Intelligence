"""Shared fixtures.

**No test in this repo opens a socket or calls a model.** Selection, the item
models, the cold start and the whole simulation are pure arithmetic — that is
what makes the 500-student grid a development instrument rather than a nightly
job, and it means a marker with no API key runs the same suite we do.
"""

from __future__ import annotations

import uuid

import pytest

from backend_M05_Question_Intelligence.contracts import (
    ConceptRole,
    ConceptWeight,
    DifficultyBand,
    GroundingKind,
    GroundingRef,
    ItemStatus,
    KeyPoint,
    Modality,
    Provenance,
    Question,
    SelectionRequest,
)

CANDIDATE = uuid.UUID("00000000-0000-4000-8000-000000000001")
OTHER_CANDIDATE = uuid.UUID("00000000-0000-4000-8000-000000000002")
CONSENT = uuid.UUID("00000000-0000-4000-8000-0000000000c0")


@pytest.fixture(autouse=True)
def _service_secret(monkeypatch):
    """A known platform secret, so no test reads or writes the developer's
    machine secret under their home directory (Platform_Core v0.12.0)."""
    monkeypatch.setenv("SERVICE_SECRET", "m05-test-secret")


def make_question(
    *,
    concept: str = "concept:hashing",
    band: DifficultyBand = DifficultyBand.core,
    round_type: str = "dsa_verbal",
    secondary: list[str] | None = None,
    **overrides,
) -> Question:
    """A valid, selectable bank item. Override any field to break one rule."""
    concepts = [ConceptWeight(concept_id=concept, weight=0.7, role=ConceptRole.primary)]
    for extra in secondary or []:
        concepts.append(
            ConceptWeight(concept_id=extra, weight=0.15, role=ConceptRole.secondary)
        )
    defaults = dict(
        id=uuid.uuid4(),
        stem=f"Explain {concept.split(':')[-1].replace('_', ' ')}.",
        modality=Modality.verbal,
        round_types=[round_type],
        concepts=concepts,
        provenance=Provenance.curated,
        difficulty_band=band,
        reference_answer="A reference answer with enough substance to be scored.",
        key_points=[
            KeyPoint(id="kp_1", statement="States the average-case complexity."),
            KeyPoint(id="kp_2", statement="Explains what happens on a collision."),
        ],
        rubric_round_type=round_type,
        time_budget_s=180,
        status=ItemStatus.active,
        scored_use_approved=True,
        theta_eligible=True,
    )
    defaults.update(overrides)
    return Question(**defaults)


def make_grounded(candidate_id: uuid.UUID, **overrides) -> Question:
    """An item built from one student's repository. It must never reach anyone else."""
    fields = dict(
        provenance=Provenance.grounded,
        grounded_on=GroundingRef(
            kind=GroundingKind.repo_decision,
            source_id="repo:their-project#decision-4",
            source_module="M03",
            excerpt="chose a write-through cache in front of the orders table",
            authored_confidence=0.82,
        ),
        grounded_for_candidate=candidate_id,
        consent_id=CONSENT,
        theta_eligible=False,
        stem="In your project, why a write-through cache in front of the orders table?",
    )
    # `update`, not `**overrides` alongside the literals: a test that overrides
    # one of these is exactly the test that is checking the rule refusing it.
    fields.update(overrides)
    return make_question(**fields)


@pytest.fixture(name="bank")
def bank_fixture() -> list[Question]:
    """A small bank spanning three concepts and the difficulty range."""
    concepts = ["concept:hashing", "concept:recursion", "concept:joins"]
    bands = [
        DifficultyBand.intro,
        DifficultyBand.easy,
        DifficultyBand.core,
        DifficultyBand.hard,
        DifficultyBand.stretch,
    ]
    return [
        make_question(concept=concept, band=band)
        for concept in concepts
        for band in bands
    ]


@pytest.fixture(name="req")
def req_fixture() -> SelectionRequest:
    return SelectionRequest(
        candidate_id=CANDIDATE,
        session_id=uuid.uuid4(),
        round_type="dsa_verbal",
        theta_provisional={
            "concept:hashing": 0.0,
            "concept:recursion": 0.0,
            "concept:joins": 0.0,
        },
        theta_seeded_from="cold",
        time_remaining_s=1800,
    )
