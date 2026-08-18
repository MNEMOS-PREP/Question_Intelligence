"""The three item models and the cold start — §6.4, §6.5.

Pure arithmetic, so these are the cheapest tests in the repo and the ones most
worth having: a wrong information function does not raise, it just quietly
picks worse questions for a year.
"""

from __future__ import annotations

import pytest

from backend_M05_Question_Intelligence import models_irt as irt
from backend_M05_Question_Intelligence.contracts import (
    DifficultyBand,
    IRTParams,
    ParamsSource,
)

# ── the cold start (AC-5.14) ─────────────────────────────────────────────


@pytest.mark.gate
def test_a_grm_item_is_usable_at_zero_responses():
    """§6.5. Cold start is 100% of Phase 1 and most of the bank is rubric-scored.

    If this path cannot produce a threshold vector, `information(θ)` is
    unevaluable for the majority of the bank, §6.6's ranking silently loses its
    information term and falls through to penalties — while every function
    still returns a number. The CAT would not work at all in the phase that is
    entirely cold start, and nothing would say so.
    """
    params = irt.cold_start(band=DifficultyBand.core, model="grm")

    assert params.params_source is ParamsSource.prior
    assert isinstance(params.b, list) and len(params.b) == 4
    model = irt.build(params)
    assert model.information(0.0) > 0.0, "an uncalibrated item carries no information"


def test_elo_gives_a_location_and_the_prior_gives_the_thresholds():
    """Elo cannot produce a threshold vector; that is the whole point of §6.5."""
    params = irt.cold_start(band=DifficultyBand.core, model="grm", elo=1700.0, n_responses=12)

    assert params.params_source is ParamsSource.elo
    assert isinstance(params.b, list)
    centre = sum(params.b) / len(params.b)
    assert centre == pytest.approx(irt.elo_to_logit(1700.0), abs=1e-6)
    # ...and the spacing came from the prior, unchanged.
    assert [round(b - centre, 6) for b in params.b] == list(irt.THRESHOLD_SPACING)


def test_bands_are_ordered_and_a_binary_item_stays_scalar():
    logits = [irt.band_to_logit(b) for b in DifficultyBand]
    assert logits == sorted(logits), "a harder band must not map to an easier logit"
    assert isinstance(irt.cold_start(band=DifficultyBand.hard, model="2pl").b, float)


def test_a_grm_item_cannot_be_built_from_a_scalar():
    """The contract refuses the shape rather than letting it fail at scoring."""
    with pytest.raises(ValueError, match="threshold VECTOR"):
        IRTParams(model="grm", a=1.0, b=0.4)


def test_grm_thresholds_must_not_decrease():
    with pytest.raises(ValueError, match="non-decreasing"):
        IRTParams(model="grm", a=1.0, b=[0.4, -0.4, 0.8, 1.2])


# ── GRM (§6.4) ───────────────────────────────────────────────────────────


def _grm(a: float = 1.0) -> irt.GRM:
    return irt.GRM(a=a, b=(-1.2, -0.4, 0.4, 1.2))


def test_category_probabilities_are_a_distribution():
    for theta in (-3.0, -1.0, 0.0, 1.0, 3.0):
        probs = _grm().category_probs(theta)
        assert len(probs) == 5
        assert all(p >= 0 for p in probs)
        assert sum(probs) == pytest.approx(1.0, abs=1e-9)


def test_expected_score_rises_with_ability():
    scores = [_grm().expected_score(t) for t in (-3.0, -1.5, 0.0, 1.5, 3.0)]
    assert scores == sorted(scores)
    assert scores[0] < 1.0 and scores[-1] > 3.0


def test_information_peaks_near_the_items_own_difficulty():
    """A hard item is most informative about strong candidates. If this is
    backwards the CAT walks away from ability instead of toward it, and every
    other test still passes."""
    hard = irt.build(irt.cold_start(band=DifficultyBand.hard, model="grm"))
    easy = irt.build(irt.cold_start(band=DifficultyBand.easy, model="grm"))

    assert hard.information(1.5) > hard.information(-1.5)
    assert easy.information(-1.5) > easy.information(1.5)


def test_discrimination_concentrates_information():
    """Higher `a` buys a taller peak and pays for it in the tails.

    The crossover sits further out than 2PL intuition suggests — a GRM with
    four spread thresholds stays informative across the whole range they span,
    so a sharp item still beats a flat one at θ = 3. Concentration is the
    property that actually holds, so that is what is asserted.
    """
    sharp, flat = _grm(a=1.8), _grm(a=0.6)

    assert sharp.information(0.0) > flat.information(0.0)
    assert sharp.information(5.0) < flat.information(5.0)

    sharp_ratio = sharp.information(0.0) / sharp.information(6.0)
    flat_ratio = flat.information(0.0) / flat.information(6.0)
    assert sharp_ratio > 100 * flat_ratio


def test_grm_p_correct_exists_but_is_not_the_measurement():
    """It satisfies the protocol and nothing in selection may use it — the
    collapse to one probability is exactly §3.1 Trap 2."""
    model = _grm()
    assert 0.0 <= model.p_correct(0.0) <= 1.0
    assert model.expected_score(0.0) == pytest.approx(2.0, abs=0.05)


# ── 2PL / 3PL ────────────────────────────────────────────────────────────


def test_two_pl_is_symmetric_about_its_difficulty():
    model = irt.TwoPL(a=1.2, b=0.5)
    assert model.p_correct(0.5) == pytest.approx(0.5)
    assert model.information(0.5) > model.information(2.5)


def test_three_pl_floors_at_the_guessing_rate():
    model = irt.ThreePL(a=1.2, b=0.0, c=0.25)
    assert model.p_correct(-6.0) == pytest.approx(0.25, abs=1e-3)
    # Guessing destroys information at the bottom, which is why a 3PL item is a
    # poor probe for a weak candidate however easy it looks.
    assert model.information(-4.0) < model.information(0.0)


# ── Elo (§6.5) ───────────────────────────────────────────────────────────


def test_an_item_everyone_passes_gets_easier():
    rating = 1500.0
    for _ in range(20):
        rating = irt.elo_update(
            item_elo=rating, theta=0.0, score=4.0, n_categories=5, n_responses=0
        )
    assert rating < 1500.0, "an item the cohort aces must not stay 'average'"


def test_an_item_everyone_fails_gets_harder():
    rating = 1500.0
    for _ in range(20):
        rating = irt.elo_update(
            item_elo=rating, theta=0.0, score=0.0, n_categories=5, n_responses=0
        )
    assert rating > 1500.0


def test_elo_step_shrinks_once_an_item_is_known():
    assert irt.elo_k(0) > irt.elo_k(15)


# ── EAP ──────────────────────────────────────────────────────────────────


def test_eap_returns_the_prior_with_no_responses():
    mean, sd = irt.eap([])
    assert (mean, sd) == (0.0, 1.0)


def test_eap_moves_toward_ability_and_narrows():
    hard = irt.cold_start(band=DifficultyBand.hard, model="grm")
    responses = [(hard, 4.0)] * 6
    mean, sd = irt.eap(responses)
    assert mean > 0.8, "six top scores on hard items is a strong candidate"
    assert sd < 1.0, "evidence must reduce uncertainty"


def test_eap_is_bounded_by_the_grid():
    """A student who aces everything must not run θ to infinity — EC-5.2 clamps
    at the edge of what the bank can measure."""
    hard = irt.cold_start(band=DifficultyBand.stretch, model="grm")
    mean, _ = irt.eap([(hard, 4.0)] * 40)
    assert mean <= 4.0
