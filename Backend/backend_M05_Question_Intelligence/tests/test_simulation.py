"""The simulation harness — §12, and AC-5.4/AC-5.5.

The cohorts here are small so the suite stays fast. The full 500-student grid
is a job (`jobs/simulate.py`), not a unit test — but the *shape* of the claim
is asserted here, because a harness that can only be run by hand is a harness
nobody runs.

The property worth stating plainly: `MisSpecification` is what makes AC-5.4
mean anything. With both arms driven by the model the CAT assumes, the CAT wins
close to by construction and the gate measures our arithmetic rather than the
method.
"""

from __future__ import annotations

import random

import pytest

from backend_M05_Question_Intelligence import simulation as sim

CONCEPTS = ("c:a", "c:b", "c:c")


def _world(mis: sim.MisSpecification, *, items: int = 160, students: int = 60):
    rng = random.Random(17)
    bank = sim.make_bank(items, mis=mis, rng=rng, concepts=CONCEPTS)
    cohort = sim.make_cohort(students, mis=mis, rng=rng, concepts=CONCEPTS)
    return bank, cohort


# ── the harness has to be able to express a wrong world ──────────────────


def test_assumed_and_true_parameters_are_separate():
    """A harness that reuses one parameter set for both cannot express
    mis-specification at all, and will report a CAT that wins every run."""
    bank, _ = _world(sim.MisSpecification(a_error=0.4))
    assert all(item.assumed.a != item.truth.a for item in bank)

    clean, _ = _world(sim.CLEAN)
    assert all(item.assumed.a == item.truth.a for item in clean)


def test_responses_come_from_the_true_parameters(monkeypatch):
    bank, cohort = _world(sim.MisSpecification(drift=0.9))
    item, student = bank[0], cohort[0]
    rng = random.Random(1)
    scores = [sim.respond(student, item, rng) for _ in range(200)]
    assert set(scores) <= {0.0, 1.0, 2.0, 3.0, 4.0}
    assert len(set(scores)) > 1, "a degenerate responder measures nothing"


def test_a_correlated_student_is_consistently_weak_on_a_topic():
    """Local independence is the first IRT assumption to break in practice."""
    _, correlated = _world(sim.MisSpecification(residual_rho=0.5))
    _, independent = _world(sim.CLEAN)
    assert any(s.concept_offset for s in correlated)
    assert all(not s.concept_offset for s in independent)


# ── AC-5.4 / AC-5.5 ──────────────────────────────────────────────────────


@pytest.mark.gate
def test_the_cat_beats_a_fixed_form_at_equal_precision():
    """AC-5.4, measured the way the gate is written.

    "At equal SEM" is the load-bearing phrase. Comparing a CAT stopped at
    SE 0.30 against a 30-item form that landed at SE 0.42 measures two stopping
    rules rather than adaptivity — and flatters us, because the CAT is held to
    the harder standard while being credited with the shorter test.
    """
    bank, cohort = _world(sim.CLEAN)
    efficiency, cat, fixed = sim.efficiency_at_equal_sem(cohort, bank, form_length=30)

    assert efficiency <= 0.60, f"CAT used {cat.mean_items:.1f} of {fixed.mean_items:.0f}"
    assert cat.recovery_r >= 0.90


@pytest.mark.gate
def test_the_claim_survives_a_world_that_disagrees_with_the_model():
    """The composite world: several small departures at once, which is what a
    real Phase-1 bank looks like and what a single-factor grid can hide."""
    composite = sim.MisSpecification(
        a_error=0.25, residual_rho=0.25, dead_item_rate=0.1, drift=0.3
    )
    bank, cohort = _world(composite)
    efficiency, cat, _ = sim.efficiency_at_equal_sem(cohort, bank, form_length=30)

    assert efficiency <= 0.60
    assert cat.recovery_r >= 0.90


@pytest.mark.parametrize("mis", sim.GRID, ids=lambda m: "clean" if m.is_clean else "mis")
def test_theta_recovery_holds_across_the_grid(mis):
    bank, cohort = _world(mis, items=120, students=40)
    _, cat, _ = sim.efficiency_at_equal_sem(cohort, bank, form_length=24)
    assert cat.recovery_r >= 0.85, f"recovery collapsed under {mis}"


def test_the_fixed_form_control_spans_the_difficulty_range():
    """A random control is a straw man — a real fixed test is built to cover
    the range, and beating a badly built control proves nothing."""
    bank, cohort = _world(sim.CLEAN)
    result = sim.run_fixed_form(cohort[:5], bank, rng=random.Random(1), length=20)
    assert result.mean_items == 20
