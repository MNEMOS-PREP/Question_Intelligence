"""The three item models, one interface — spec §6.4, and the cold start §6.5.

Pure arithmetic over floats: no database, no network, no model calls. That is
deliberate and it is what makes the simulation harness (§12) able to run a
500-student cohort in a second.

**Read `cold_start()` before anything else here.** §3.2 says cold start is 100%
of Phase 1, and most of the bank is rubric-scored. Elo can only ever produce a
*location*, while GRM needs a threshold vector — so without an explicit bridge,
`information(θ)` is unevaluable for the majority of the bank for the whole of
Phase 1. Selection then silently drops its information term and ranks on
coverage and penalties alone, while every function still returns a number and
every test still passes. That is the failure this module exists to avoid, so it
is the first thing built and it has its own gate (AC-5.14).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .contracts import (
    DifficultyBand,
    IRTParams,
    ParamsSource,
)

#: Logistic scaling. We use the logistic metric throughout (D = 1.0), not the
#: normal-ogive approximation (D = 1.702) — mixing them is a silent factor of
#: 1.7 on every difficulty in the bank.
D = 1.0

#: §6.5. Authors judge a band; this converts. Versioned as an artifact because
#: changing it moves every uncalibrated item's difficulty at once, and a bank
#: whose difficulties shifted without an authoring change has to be able to say
#: so.
BAND_TABLE_VERSION = "1.0.0"

#: Default band → logit centre. Overridable per round type: a "hard" behavioural
#: question and a "hard" DP question are not the same distance from average.
BAND_LOGITS: dict[DifficultyBand, float] = {
    DifficultyBand.intro: -1.6,
    DifficultyBand.easy: -0.8,
    DifficultyBand.core: 0.0,
    DifficultyBand.hard: +0.9,
    DifficultyBand.stretch: +1.8,
}

#: Spacing prior for GRM thresholds around a location (§6.5). Four thresholds
#: for a 0..4 scale. Wide enough that the middle categories are reachable —
#: thresholds packed too tightly make categories 1..3 nearly unobservable and
#: the model degenerates toward binary, which is Trap 2 arriving by the back
#: door.
THRESHOLD_SPACING: tuple[float, ...] = (-1.2, -0.4, 0.4, 1.2)

#: Held fixed until MML runs. 1.0 is the "average discriminating item"
#: convention; assuming better would flatter every uncalibrated item's
#: information and pull selection toward exactly the items we know least about.
DEFAULT_A = 1.0

#: Elo → logit. 173.7 = 400 / ln(10), the standard conversion.
ELO_SCALE = 173.7
ELO_ORIGIN = 1500.0


def band_to_logit(band: DifficultyBand, round_type: str = "") -> float:
    """Author-facing band → the logit scale everything downstream works in."""
    return _ROUND_BAND_OVERRIDES.get(round_type, {}).get(band, BAND_LOGITS[band])


#: Per-round-type overrides. Empty today and that is honest: populating it needs
#: the calibration sitting in §15.6, not a guess made here.
_ROUND_BAND_OVERRIDES: dict[str, dict[DifficultyBand, float]] = {}


def elo_to_logit(rating: float) -> float:
    return (rating - ELO_ORIGIN) / ELO_SCALE


def thresholds_around(location: float) -> list[float]:
    """A GRM threshold vector from a single location, via the spacing prior."""
    return [round(location + delta, 6) for delta in THRESHOLD_SPACING]


def cold_start(
    *,
    band: DifficultyBand,
    model: str,
    round_type: str = "",
    elo: float | None = None,
    n_responses: int = 0,
) -> IRTParams:
    """A **usable** parameter set at n = 0, and honest about where it came from.

    Two rules, both from §6.5:

    * **Elo estimates a location, never a threshold vector.** Elo takes a binary
      outcome; a 0..4 rubric score can only reach it as `score / (K-1)`, which
      is the Trap 2 collapse. That collapse is tolerable for a provisional
      *location* and for nothing else — it never touches ability estimation, and
      the location is discarded the moment MML runs.
    * **Thresholds come from the spacing prior** until MML replaces them.
    """
    if elo is not None and n_responses > 0:
        location = elo_to_logit(elo)
        source = ParamsSource.elo
    else:
        location = band_to_logit(band, round_type)
        source = ParamsSource.prior

    if model == "grm":
        b: float | list[float] = thresholds_around(location)
    else:
        b = round(location, 6)

    return IRTParams(
        model=model,  # type: ignore[arg-type]
        a=DEFAULT_A,
        b=b,
        c=0.25 if model == "3pl" else None,
        se_a=1.0,
        # A prior is a wide belief and should say so. Selection uses this to
        # avoid over-trusting an uncalibrated item.
        se_b=1.2 if source is ParamsSource.prior else 0.6,
        n_responses=n_responses,
        params_source=source,
    )


# ─────────────────────────────────────────────────────────────────────────
#  The models
# ─────────────────────────────────────────────────────────────────────────


def _logistic(x: float) -> float:
    # Guarded: math.exp overflows around |x| > 709 and a θ of ±40 is reachable
    # from a bad fit, which should degrade to a flat 0/1 rather than crash a
    # selection on the hot path.
    if x < -60:
        return 0.0
    if x > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


@dataclass(frozen=True)
class TwoPL:
    """Auto-gradable binary — coding pass/fail, numeric."""

    a: float
    b: float

    def p_correct(self, theta: float) -> float:
        return _logistic(D * self.a * (theta - self.b))

    def expected_score(self, theta: float) -> float:
        return self.p_correct(theta)

    def information(self, theta: float) -> float:
        p = self.p_correct(theta)
        return (D * self.a) ** 2 * p * (1.0 - p)

    def log_likelihood(self, theta: float, response: float) -> float:
        p = min(max(self.p_correct(theta), 1e-12), 1 - 1e-12)
        return response * math.log(p) + (1.0 - response) * math.log(1.0 - p)


@dataclass(frozen=True)
class ThreePL:
    """MCQ aptitude, where guessing is real and ignoring it biases `b` low."""

    a: float
    b: float
    c: float

    def p_correct(self, theta: float) -> float:
        return self.c + (1.0 - self.c) * _logistic(D * self.a * (theta - self.b))

    def expected_score(self, theta: float) -> float:
        return self.p_correct(theta)

    def information(self, theta: float) -> float:
        p = self.p_correct(theta)
        if p <= self.c or p >= 1.0:
            return 0.0
        # I = a² · (P-c)²(1-P) / [(1-c)² · P]
        return (D * self.a) ** 2 * ((p - self.c) ** 2) * (1.0 - p) / ((1.0 - self.c) ** 2 * p)

    def log_likelihood(self, theta: float, response: float) -> float:
        p = min(max(self.p_correct(theta), 1e-12), 1 - 1e-12)
        return response * math.log(p) + (1.0 - response) * math.log(1.0 - p)


@dataclass(frozen=True)
class GRM:
    """Samejima's Graded Response Model — the one that matters.

    Most items here are rubric-scored 0..4, and this is the difference between
    a defensible Paper 2 and a reviewer's first objection. `b` is the vector of
    K-1 category thresholds: `b[k]` is where P(X >= k+1) crosses one half.
    """

    a: float
    b: tuple[float, ...]

    @property
    def n_categories(self) -> int:
        return len(self.b) + 1

    def p_at_least(self, theta: float, k: int) -> float:
        """P(X >= k). Category 0 is certain; anything past the top is impossible."""
        if k <= 0:
            return 1.0
        if k > len(self.b):
            return 0.0
        return _logistic(D * self.a * (theta - self.b[k - 1]))

    def category_probs(self, theta: float) -> list[float]:
        return [
            self.p_at_least(theta, k) - self.p_at_least(theta, k + 1)
            for k in range(self.n_categories)
        ]

    def expected_score(self, theta: float) -> float:
        return sum(k * p for k, p in enumerate(self.category_probs(theta)))

    def p_correct(self, theta: float) -> float:
        """Present only because the `ItemModel` protocol has it.

        Defined as P(top half of the scale) so it is at least well-formed, and
        deliberately NOT used by selection or by `SelectionResult` — collapsing
        a five-category item to one probability is the trap this model exists
        to avoid. Use `expected_score`.
        """
        return self.p_at_least(theta, (self.n_categories + 1) // 2)

    def information(self, theta: float) -> float:
        """I(θ) = a² · Σ_k (P*_k - P*_{k+1})² / P_k, the standard GRM form."""
        total = 0.0
        for k in range(self.n_categories):
            upper = self.p_at_least(theta, k)
            lower = self.p_at_least(theta, k + 1)
            p_k = upper - lower
            if p_k <= 1e-12:
                continue
            # d/dθ of P(X>=k) is a·P*(1-P*) for the logistic.
            d_upper = D * self.a * upper * (1.0 - upper) if 0 < k <= len(self.b) else 0.0
            d_lower = D * self.a * lower * (1.0 - lower) if 0 < k + 1 <= len(self.b) else 0.0
            total += (d_upper - d_lower) ** 2 / p_k
        return total

    def log_likelihood(self, theta: float, response: float) -> float:
        k = int(round(response))
        k = min(max(k, 0), self.n_categories - 1)
        p = self.category_probs(theta)[k]
        return math.log(max(p, 1e-12))


def build(params: IRTParams) -> TwoPL | ThreePL | GRM:
    """`IRTParams` → something you can ask for information at θ."""
    if params.model == "grm":
        assert isinstance(params.b, list)
        return GRM(a=params.a, b=tuple(params.b))
    assert isinstance(params.b, float | int)
    if params.model == "3pl":
        return ThreePL(a=params.a, b=float(params.b), c=params.c or 0.0)
    return TwoPL(a=params.a, b=float(params.b))


# ─────────────────────────────────────────────────────────────────────────
#  Elo — the online path, §6.5
# ─────────────────────────────────────────────────────────────────────────


def elo_k(n_responses: int) -> float:
    """K = 32, dropping to 16 after ten responses (§6.5)."""
    return 32.0 if n_responses < 10 else 16.0


def elo_update(
    *,
    item_elo: float,
    theta: float,
    score: float,
    n_categories: int,
    n_responses: int,
) -> float:
    """One online difficulty update, returning the item's new rating.

    `score / (n_categories - 1)` is the binary collapse Trap 2 warns about, and
    it is confined to this function on purpose: the result is a provisional
    *location* used to rank items before any real calibration exists, it never
    reaches ability estimation, and it is discarded the moment MML runs. That is
    the whole justification, and if this value ever starts feeding θ the
    justification is gone.
    """
    normalised = 0.0 if n_categories <= 1 else score / (n_categories - 1)
    normalised = min(max(normalised, 0.0), 1.0)
    expected_student_wins = _logistic(theta - elo_to_logit(item_elo))
    # The student winning means the item lost, hence the sign.
    return item_elo + elo_k(n_responses) * (expected_student_wins - normalised)


# ─────────────────────────────────────────────────────────────────────────
#  θ estimation — EAP over a fixed grid
# ─────────────────────────────────────────────────────────────────────────

#: −4..4 in 81 steps. Fine enough that the posterior mean is stable to ~0.01
#: logits and coarse enough to stay inside the selection latency budget.
_GRID = [(-4.0 + i * 0.1) for i in range(81)]


def eap(
    responses: list[tuple[IRTParams, float]],
    *,
    prior_mean: float = 0.0,
    prior_sd: float = 1.0,
) -> tuple[float, float]:
    """Posterior mean and SD of θ given (item, score) pairs.

    Used for the **provisional** in-session estimate (§6.10) and by the
    simulation harness. M04 owns the durable posterior and computes its own;
    this one is never persisted.
    """
    if not responses:
        return prior_mean, prior_sd

    weights = []
    for theta in _GRID:
        log_p = -0.5 * ((theta - prior_mean) / prior_sd) ** 2
        for params, score in responses:
            log_p += build(params).log_likelihood(theta, score)
        weights.append(log_p)

    peak = max(weights)
    posterior = [math.exp(w - peak) for w in weights]
    total = sum(posterior)
    if total <= 0:
        return prior_mean, prior_sd

    mean = sum(t * p for t, p in zip(_GRID, posterior, strict=True)) / total
    var = sum(((t - mean) ** 2) * p for t, p in zip(_GRID, posterior, strict=True)) / total
    return mean, math.sqrt(max(var, 1e-9))


__all__ = [
    "BAND_LOGITS",
    "BAND_TABLE_VERSION",
    "DEFAULT_A",
    "GRM",
    "THRESHOLD_SPACING",
    "ThreePL",
    "TwoPL",
    "band_to_logit",
    "build",
    "cold_start",
    "eap",
    "elo_k",
    "elo_to_logit",
    "elo_update",
    "thresholds_around",
]
