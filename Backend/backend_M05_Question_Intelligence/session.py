"""The provisional θ — spec §6.10, and the contract M04 and M06 already assume.

**This is the state M05 owns and must never write down.**

M04's spec: *"M04 owns the durable posterior per (candidate, concept) […] M5
owns item parameters and a session-scoped provisional θ held in SessionState —
seeded from M04 at session bootstrap, updated in memory from the provisional
score for item selection only, never persisted, never displayed, discarded at
session end."*

M04's open decision 5 settles it in one line: *"Who owns the in-session ability
estimate? **M5** (provisional, in-memory, discarded at session end)."*

Why it exists at all: M13 evaluates asynchronously at p95 ≤ 15 s and FR-13.19
forbids blocking the conversation on it, so the real score does not exist when
the next question must be chosen. Reading M04's posterior per selection looks
equivalent and is not — it does not move during a session, so the CAT silently
becomes a fixed-form test pinned at entry ability while still reporting itself
as adaptive. Nothing errors, and the simulation never catches it because the
simulation does not model the gap.

Why it must not be persisted: two stored ability numbers is two answers to "how
good is this student", and the cheap one is the one that leaks into a report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from .contracts import OutcomeBand, ProvisionalOutcome

log = logging.getLogger(__name__)

#: How far one provisional verdict moves the estimate. Small on purpose: this
#: is a cheap classifier's opinion, not a measurement, and it exists to keep
#: selection roughly on target rather than to estimate ability.
STEP = {OutcomeBand.above: +0.4, OutcomeBand.at: 0.0, OutcomeBand.below: -0.4}

#: §6.10. Above this, the cheap verdict and the real evaluator disagree
#: systematically — worth knowing, and invisible unless somebody measures it.
DIVERGENCE_ALERT = 0.5

#: EC-5.2. The edge of what a bank can measure; beyond it the estimate is
#: extrapolation dressed as measurement.
THETA_CLAMP = 3.0


class ProvisionalIsNotDurable(RuntimeError):
    """Raised by any attempt to serialise the provisional estimate for storage.

    Deliberately loud. The failure this prevents is not a crash — it is a
    plausible-looking number reaching a report, and by then nobody can tell it
    apart from the one M04 computed properly.
    """


@dataclass
class SessionState:
    """One session's working estimate. Lives in memory and dies with the session."""

    session_id: UUID
    candidate_id: UUID
    theta: dict[str, float] = field(default_factory=dict)
    se: dict[str, float] = field(default_factory=dict)
    seeded_from: str = "cold"
    updates: int = 0
    #: Item ids administered this session, in order. Feeds `seen_item_ids`.
    administered: list[UUID] = field(default_factory=list)

    def theta_for(self, concept_id: str) -> float:
        return self.theta.get(concept_id, 0.0)

    def observe(self, concept_id: str, outcome: ProvisionalOutcome) -> float:
        """Fold in M06's ProbeStrategist verdict. In memory, and only here."""
        current = self.theta_for(concept_id)
        moved = current + STEP[outcome.band] * max(outcome.confidence, 0.25) * 2
        moved = max(-THETA_CLAMP, min(THETA_CLAMP, moved))
        self.theta[concept_id] = round(moved, 4)
        # A cheap verdict narrows uncertainty a little, never to the point where
        # the stopping rule would fire on it alone.
        self.se[concept_id] = max(0.35, self.se.get(concept_id, 1.0) * 0.92)
        self.updates += 1
        return self.theta[concept_id]

    def __getstate__(self):  # pragma: no cover - the point is that it raises
        raise ProvisionalIsNotDurable(
            "the provisional θ is session-scoped and must not be pickled, cached "
            "or written to a row (§6.10). M04 owns the durable posterior; this is "
            "a working estimate that exists only because M13's score has not "
            "arrived yet."
        )


def seed_from_m04(
    session_id: UUID,
    candidate_id: UUID,
    posterior: dict[str, float] | None,
    *,
    snapshot_id: str = "cold",
) -> SessionState:
    """Bootstrap. `None` is the normal case for a new candidate and for a
    checkout with no M04 — θ starts at the prior, which is the honest belief."""
    state = SessionState(session_id=session_id, candidate_id=candidate_id)
    if posterior:
        state.theta = dict(posterior)
        state.seeded_from = snapshot_id
    return state


def reconcile(
    state: SessionState, posterior: dict[str, float]
) -> dict[str, float]:
    """Session end — §6.10. **The posterior wins, silently.**

    M04 recomputes from the observations of record. Where it disagrees with what
    we were steering by, M04 is right and nobody is told: the student's number
    was never ours to set. A divergence beyond `DIVERGENCE_ALERT` is logged as a
    calibration signal, because a ProbeStrategist that systematically disagrees
    with the real evaluator is a fixable problem and an invisible one.
    """
    divergence: dict[str, float] = {}
    for concept_id, durable in posterior.items():
        delta = abs(state.theta_for(concept_id) - durable)
        if delta > DIVERGENCE_ALERT:
            divergence[concept_id] = round(delta, 4)
            log.info(
                "provisional θ diverged from M04's posterior on %s by %.2f logits "
                "(session %s) — calibration signal, not an error",
                concept_id,
                delta,
                state.session_id,
            )
    state.theta.clear()
    state.se.clear()
    return divergence


__all__ = [
    "DIVERGENCE_ALERT",
    "STEP",
    "THETA_CLAMP",
    "ProvisionalIsNotDurable",
    "SessionState",
    "reconcile",
    "seed_from_m04",
]
