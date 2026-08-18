"""The simulation harness — spec §12, milestone M2.

**Built before the estimators, on purpose.** This is not a test of the finished
selector; it is the instrument you build the selector *with*. M04 made the same
call and said why: it catches a bad curve in an afternoon instead of in a pilot.

The part that decides whether AC-5.4 means anything is `MisSpecification`. When
both arms of the comparison are driven by the very model the CAT assumes, the
CAT wins close to by construction and the gate measures our arithmetic rather
than the method. So every headline number is reported twice — once under the
model's own assumptions, once under a world that disagrees with it — and only
the second is evidence.

No database, no network. A 500-student cohort runs in about a second, which is
what makes it usable as a development instrument rather than a nightly job.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .contracts import IRTParams, ParamsSource
from .models_irt import _GRID, GRM, ThreePL, TwoPL, build


@dataclass(frozen=True)
class MisSpecification:
    """A world that disagrees with the model the selector assumes (§12).

    Every field is a way reality departs from the textbook, and each is one we
    have concrete reason to expect:

    `a_error`            authored/estimated discrimination is off
    `residual_rho`       a student is uniformly weak on recursion rather than
                         independently weak per item — the assumption of local
                         independence is the first one to break in practice
    `guessing`           multiple-choice-ish items modelled without a lower
                         asymptote
    `drift`              `b` moves mid-cohort, which is what a leaked item
                         looks like
    `dead_item_rate`     items with a < 0.4 still active in the bank
    `threshold_squash`   a rubric whose middle categories are barely used, so
                         the response is not GRM-shaped at all
    """

    a_error: float = 0.0
    residual_rho: float = 0.0
    guessing: float = 0.0
    drift: float = 0.0
    dead_item_rate: float = 0.0
    threshold_squash: float = 0.0

    @property
    def is_clean(self) -> bool:
        return self == CLEAN


CLEAN = MisSpecification()

#: The grid AC-5.4 must hold under. Deliberately not extreme — each value is
#: near what a real Phase-1 bank plausibly looks like.
GRID: tuple[MisSpecification, ...] = (
    CLEAN,
    MisSpecification(a_error=0.4),
    MisSpecification(a_error=-0.4),
    MisSpecification(residual_rho=0.35),
    MisSpecification(guessing=0.2),
    MisSpecification(drift=0.6),
    MisSpecification(dead_item_rate=0.2),
    MisSpecification(threshold_squash=0.6),
    # The realistic composite: several small departures at once, which is what
    # a bank actually looks like and what a single-factor grid can hide.
    MisSpecification(a_error=0.25, residual_rho=0.25, dead_item_rate=0.1, drift=0.3),
)


@dataclass
class SimItem:
    """An item with BOTH sets of parameters.

    `assumed` is what the selector sees. `truth` is what generates responses.
    Keeping them as separate fields is the whole design — a harness that reuses
    one set for both cannot express mis-specification at all, and will report a
    CAT that beats fixed-form on every run.
    """

    item_id: int
    assumed: IRTParams
    truth: IRTParams
    concept: str = "concept:general"
    true_guessing: float = 0.0

    @property
    def n_categories(self) -> int:
        return self.assumed.n_categories


@dataclass
class SimStudent:
    student_id: int
    true_theta: float
    #: Per-concept offset drawn once, so a student is consistently weak on a
    #: topic rather than independently weak per item (`residual_rho`).
    concept_offset: dict[str, float] = field(default_factory=dict)

    def theta_for(self, concept: str) -> float:
        return self.true_theta + self.concept_offset.get(concept, 0.0)


def make_bank(
    n_items: int,
    *,
    mis: MisSpecification = CLEAN,
    rng: random.Random,
    model: str = "grm",
    concepts: tuple[str, ...] = ("concept:general",),
) -> list[SimItem]:
    """A bank whose assumed parameters differ from its true ones by `mis`."""
    items: list[SimItem] = []
    for i in range(n_items):
        location = rng.uniform(-2.0, 2.0)
        a_true = rng.uniform(0.7, 1.6)

        if rng.random() < mis.dead_item_rate:
            a_true = rng.uniform(0.1, 0.39)

        a_assumed = max(0.05, a_true + mis.a_error)
        b_true_location = location + rng.uniform(-mis.drift, mis.drift)

        if model == "grm":
            spread = 1.0 - mis.threshold_squash
            deltas = [d * spread for d in (-1.2, -0.4, 0.4, 1.2)]
            truth = IRTParams(
                model="grm",
                a=a_true,
                b=[round(b_true_location + d, 6) for d in deltas],
                params_source=ParamsSource.mml,
            )
            assumed = IRTParams(
                model="grm",
                a=a_assumed,
                b=[round(location + d, 6) for d in (-1.2, -0.4, 0.4, 1.2)],
                params_source=ParamsSource.prior,
            )
        else:
            truth = IRTParams(
                model="2pl", a=a_true, b=b_true_location, params_source=ParamsSource.mml
            )
            assumed = IRTParams(
                model="2pl", a=a_assumed, b=location, params_source=ParamsSource.prior
            )

        items.append(
            SimItem(
                item_id=i,
                assumed=assumed,
                truth=truth,
                concept=concepts[i % len(concepts)],
                true_guessing=mis.guessing,
            )
        )
    return items


def make_cohort(
    n: int,
    *,
    mis: MisSpecification = CLEAN,
    rng: random.Random,
    concepts: tuple[str, ...] = ("concept:general",),
) -> list[SimStudent]:
    students = []
    for i in range(n):
        offsets = (
            {c: rng.gauss(0.0, mis.residual_rho) for c in concepts}
            if mis.residual_rho
            else {}
        )
        students.append(
            SimStudent(student_id=i, true_theta=rng.gauss(0.0, 1.0), concept_offset=offsets)
        )
    return students


def respond(student: SimStudent, item: SimItem, rng: random.Random) -> float:
    """Generate a response from the item's TRUE parameters, never its assumed."""
    theta = student.theta_for(item.concept)
    model = build(item.truth)

    if item.true_guessing and rng.random() < item.true_guessing:
        # Guessed it. On a graded item a lucky guess lands mid-scale, not top —
        # you can bluff structure without bluffing depth.
        return float(item.n_categories - 1) if isinstance(model, TwoPL | ThreePL) else 2.0

    if isinstance(model, GRM):
        probs = model.category_probs(theta)
        roll = rng.random()
        cumulative = 0.0
        for k, p in enumerate(probs):
            cumulative += p
            if roll <= cumulative:
                return float(k)
        return float(len(probs) - 1)

    return 1.0 if rng.random() < model.p_correct(theta) else 0.0


# ─────────────────────────────────────────────────────────────────────────
#  The two arms
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class RunResult:
    items_used: list[int]
    theta_hat: list[float]
    theta_true: list[float]
    final_se: list[float]
    exposure: dict[int, int]

    @property
    def mean_items(self) -> float:
        return sum(self.items_used) / len(self.items_used) if self.items_used else 0.0

    @property
    def recovery_r(self) -> float:
        return _pearson(self.theta_hat, self.theta_true)

    @property
    def max_exposure(self) -> float:
        if not self.exposure or not self.items_used:
            return 0.0
        return max(self.exposure.values()) / len(self.items_used)


def run_cat(
    students: list[SimStudent],
    bank: list[SimItem],
    *,
    rng: random.Random,
    target_se: float = 0.30,
    max_items: int = 30,
) -> RunResult:
    """Adaptive: pick the item with maximum information at the current θ̂."""
    used, hats, truths, ses = [], [], [], []
    exposure: dict[int, int] = {}

    for student in students:
        seen: set[int] = set()
        # The log-posterior is carried and added to, not rebuilt. Recomputing
        # every previous item's likelihood at each step is O(n^2) and made the
        # full grid a four-minute job rather than a development instrument.
        log_post = _prior_log()
        theta_hat, se = 0.0, 1.0

        for _ in range(max_items):
            pool = [i for i in bank if i.item_id not in seen]
            if not pool:
                break
            best = max(pool, key=lambda it: build(it.assumed).information(theta_hat))
            seen.add(best.item_id)
            exposure[best.item_id] = exposure.get(best.item_id, 0) + 1
            score = respond(student, best, rng)
            model = build(best.assumed)
            for gi, theta in enumerate(_GRID):
                log_post[gi] += model.log_likelihood(theta, score)
            theta_hat, se = _summarise(log_post)
            if se < target_se:
                break

        used.append(len(seen))
        hats.append(theta_hat)
        truths.append(student.true_theta)
        ses.append(se)

    return RunResult(used, hats, truths, ses, exposure)


def run_fixed_form(
    students: list[SimStudent],
    bank: list[SimItem],
    *,
    rng: random.Random,
    length: int = 30,
) -> RunResult:
    """The control: the same form for everyone, spread across the difficulty range.

    Spread rather than random, because a random form is a straw man — a real
    fixed test is built to cover the range, and beating a badly built control
    proves nothing.
    """
    ordered = sorted(bank, key=lambda it: _location(it.assumed))
    if len(ordered) <= length:
        form = ordered
    else:
        step = len(ordered) / length
        form = [ordered[int(i * step)] for i in range(length)]

    used, hats, truths, ses = [], [], [], []
    exposure: dict[int, int] = {}

    for student in students:
        log_post = _prior_log()
        for item in form:
            exposure[item.item_id] = exposure.get(item.item_id, 0) + 1
            score = respond(student, item, rng)
            model = build(item.assumed)
            for gi, theta in enumerate(_GRID):
                log_post[gi] += model.log_likelihood(theta, score)
        theta_hat, se = _summarise(log_post)
        used.append(len(form))
        hats.append(theta_hat)
        truths.append(student.true_theta)
        ses.append(se)

    return RunResult(used, hats, truths, ses, exposure)


def efficiency(cat: RunResult, fixed: RunResult) -> float:
    """Items the CAT needed as a fraction of the fixed form's — AC-5.4.

    Only meaningful when the two arms reached the SAME precision. Use
    `efficiency_at_equal_sem()`, which arranges that; this is the raw ratio and
    is kept because it is what the console shows.
    """
    if fixed.mean_items <= 0:
        return 1.0
    return cat.mean_items / fixed.mean_items


def efficiency_at_equal_sem(
    students: list[SimStudent],
    bank: list[SimItem],
    *,
    rng_seed: int = 3,
    form_length: int = 30,
    max_items: int = 60,
) -> tuple[float, RunResult, RunResult]:
    """AC-5.4, measured the way the gate is written.

    The fixed form runs first and reports the precision it actually achieved;
    the CAT then targets **that** SE. Comparing a CAT stopped at SE 0.30 with a
    fixed form of 30 items that landed at SE 0.42 is not a measurement of
    adaptivity, it is a measurement of two different stopping rules — and it
    flatters us, because the CAT is being held to the harder standard while
    being credited with the shorter test.

    `max_items` is deliberately larger than `form_length`: under
    mis-specification the CAT can legitimately need MORE items than the fixed
    form, and a cap at the form length would hide exactly that failure.
    """
    fixed = run_fixed_form(students, bank, rng=random.Random(rng_seed), length=form_length)
    target = sum(fixed.final_se) / len(fixed.final_se)
    cat = run_cat(
        students, bank, rng=random.Random(rng_seed), target_se=target, max_items=max_items
    )
    return efficiency(cat, fixed), cat, fixed


def _prior_log() -> list[float]:
    """Standard normal prior over the θ grid, in log space."""
    return [-0.5 * theta * theta for theta in _GRID]


def _summarise(log_post: list[float]) -> tuple[float, float]:
    """Posterior mean and SD from an unnormalised log-posterior."""
    peak = max(log_post)
    weights = [math.exp(w - peak) for w in log_post]
    total = sum(weights)
    if total <= 0:
        return 0.0, 1.0
    mean = sum(t * w for t, w in zip(_GRID, weights, strict=True)) / total
    var = sum(((t - mean) ** 2) * w for t, w in zip(_GRID, weights, strict=True)) / total
    return mean, math.sqrt(max(var, 1e-9))


def _location(params: IRTParams) -> float:
    return sum(params.b) / len(params.b) if isinstance(params.b, list) else float(params.b)


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else 0.0


__all__ = [
    "CLEAN",
    "GRID",
    "MisSpecification",
    "RunResult",
    "SimItem",
    "SimStudent",
    "efficiency",
    "efficiency_at_equal_sem",
    "make_bank",
    "make_cohort",
    "respond",
    "run_cat",
    "run_fixed_form",
]
