"""Constrained maximum-information selection — spec §6.6, §6.8, §6.9.

Pure functions over a list of `Question`. No database and no clock, because
every rule here is one you want to test exhaustively and none of them needs
persistence to be true.

Four rules are load-bearing and each is enforced rather than documented:

**A grounded item never leaves its subject.** `grounded_for_candidate` is a
hard filter with a gate behind it (AC-5.11). A question generated from someone's
repository carries their service names in the stem; a pool filtered only by
round type and freshness serves it to the cohort while every session still
looks completely normal.

**Forced items are honoured before anything can eliminate them.** M04 owns the
re-test queue and M13 promised a disputing student a fresh question. Both arrive
as `forced_item_ids`, and both die silently if the freshness filter runs first.

**Coverage outranks the SE stopping rule.** On a strong candidate SE collapses
in three or four items; stopping there ends the round with JD requirements
unprobed while the report still says it completed, and M02's guarantee becomes
an intention again.

**A repeat is disclosed, never silent.** §2.4 — an announced repeat is a
re-test; an unannounced one is the complaint this module is named for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from .contracts import (
    ItemStatus,
    ParamsSource,
    Question,
    SelectionReason,
    SelectionRequest,
    SelectionResult,
    StopReason,
)
from .models_irt import build, cold_start

#: §6.6 step 2. The first item of a round opens below ability — a gentle start
#: costs a little information and buys the rest of the round.
WARMUP_OFFSET = 0.4

#: §6.6 step 3. One stretch item per round, placed around 70% through and never
#: last (§2.2) — ending on the item they failed is the single most common
#: demoralisation event in adaptive testing.
STRETCH_OFFSET = 1.2
STRETCH_WINDOW = (0.6, 0.85)

#: §6.6 step 4. Weights for the constrained ranking.
COVERAGE_GAIN = 0.8
#: Per earlier question on the same primary concept in this interview.
CONCEPT_REPEAT_PENALTY = 0.5
#: Sharing a concept with the question just asked.
RECENCY_PENALTY = 0.3
#: Reading like a question already asked: content words shared above
#: `ALIKE_AT` (Jaccard). Two concepts, one question, is still a repeat.
ALIKE_PENALTY = 0.2
ALIKE_AT = 0.25

_WORD = re.compile(r"[a-z][a-z0-9]+")
_FILLER = frozenset(
    "the and for with that this what how why you your would could does when which into "
    "from have has are was were will can its their there them then than about over under "
    "what's explain describe tell given using use used each some any one two "
    # The frames questions are asked in, not what they are about.
    "time when where while during recall situation notice".split()
)


def content_words(text: str) -> frozenset[str]:
    """A stem's words that say what it is about — crude, on purpose."""
    words = (w for w in _WORD.findall(text.lower()) if w not in _FILLER and len(w) > 3)
    return frozenset(w[:-1] if w.endswith("s") and len(w) > 4 else w for w in words)


def alike(a: str, b: str) -> float:
    """Jaccard overlap of two stems' content words."""
    left, right = content_words(a), content_words(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)

#: §6.9.
TARGET_SE = 0.30
MIN_INFORMATION = 0.15

DISCLOSURE_FRESHNESS = (
    "You've seen this one before — I'm asking again deliberately to see if it stuck."
)
DISCLOSURE_RETEST = (
    "This is a re-test on a topic you flagged, so you're seeing a question you've had before."
)


class NoItemAvailable(LookupError):
    """Every path in §6.8 has been exhausted. The caller ends the round and says so."""


@dataclass
class Candidate:
    question: Question
    information: float
    score: float
    reason: SelectionReason


# ─────────────────────────────────────────────────────────────────────────
#  Filters
# ─────────────────────────────────────────────────────────────────────────


def visible_to(question: Question, candidate_id: UUID) -> bool:
    """FR-5.22 — the rule that keeps one student's repository out of another's
    session. Extracted as its own predicate so the gate can assert it directly
    rather than through a whole selection."""
    return (
        question.grounded_for_candidate is None
        or question.grounded_for_candidate == candidate_id
    )


def eligible(
    bank: list[Question],
    req: SelectionRequest,
    *,
    ignore_freshness: bool = False,
) -> list[Question]:
    """§6.6 step 1. Hard filters — everything here is a yes/no, never a penalty."""
    allowed = {m for m in req.modality_allowed}
    out = []
    for question in bank:
        if not question.usable_in(req.round_type):
            continue
        if allowed and question.modality not in allowed:
            continue
        if question.status is not ItemStatus.active:
            continue
        if not question.scored_use_approved and not req.allow_drafts:
            continue
        if question.quality.flagged_broken > 0:
            continue
        if not req.on_concepts(question):
            continue
        if question.time_budget_s > req.time_remaining_s:
            continue
        if question.id in req.seen_item_ids:
            continue
        if not visible_to(question, req.candidate_id):
            continue
        if not ignore_freshness and not req.bypass_freshness:
            if question.id in req.recent_item_ids:
                continue
        out.append(question)
    return out


# ─────────────────────────────────────────────────────────────────────────
#  Ranking
# ─────────────────────────────────────────────────────────────────────────


def target_theta(req: SelectionRequest, question: Question) -> float:
    """Where we want the next item to sit, on the concept it measures — the
    estimate, moved by the caller's offset for that concept (2026-10-22)."""
    concept = question.primary_concept
    return req.theta_for(concept) + req.offset_for(concept)


def should_stretch(req: SelectionRequest) -> bool:
    """Exactly one per round, ~70% through, never last (§2.2, FR-5.13)."""
    low, high = STRETCH_WINDOW
    return not req.stretch_used and low <= req.round_progress <= high


def coverage_gain(question: Question, req: SelectionRequest) -> float:
    """The WPM term. Debt on a requirement this item addresses is what it buys.

    Scaled by remaining debt so coverage dominates as a round nears its end,
    which is the behaviour a human interviewer shows — *"I still need to check
    DBMS before we finish"*.
    """
    if not req.coverage_debt:
        return 0.0
    return sum(
        debt
        for requirement_id, debt in req.coverage_debt.items()
        if requirement_id in {c.concept_id for c in question.concepts}
    )


def parameters_for(question: Question, round_type: str):
    """The item's measurement model, cold-started if it has none yet.

    Never returns None. A caller that has to handle "no parameters" will write
    `if params: rank_by_information() else: rank_by_something_else()`, and the
    else branch is where the CAT quietly stops being adaptive for the whole of
    Phase 1 (§6.5).
    """
    if question.irt is not None:
        return question.irt
    model = "grm" if question.modality not in {"mcq", "numeric"} else "2pl"
    return cold_start(
        band=question.difficulty_band,
        model=model,
        round_type=round_type,
        elo=question.elo if question.quality.mean_time_s else None,
    )


def rank(
    pool: list[Question],
    req: SelectionRequest,
    *,
    last_concepts: set[str] | None = None,
    asked: list[Question] | None = None,
) -> list[Candidate]:
    """§6.6 step 4 — information, constrained.

    `asked` is this interview's questions so far, in order. Until 2026-10-08
    the variety terms read nothing: `last_concepts` was never passed by the
    route, and the repeat count was taken over the POOL (with two drafts per
    concept it penalised every item alike), so nothing stopped the same
    topic coming twice running."""
    asked = asked or []
    last_concepts = set(last_concepts or set())
    if asked:
        last_concepts |= {c.concept_id for c in asked[-1].concepts}
    stretch = should_stretch(req)
    concept_counts: dict[str, int] = {}
    for question in asked:
        primary = question.primary_concept
        concept_counts[primary] = concept_counts.get(primary, 0) + 1
    asked_stems = [q.stem for q in asked]

    ranked: list[Candidate] = []
    for question in pool:
        params = parameters_for(question, req.round_type)
        theta = target_theta(req, question)
        if stretch:
            theta += STRETCH_OFFSET
        elif req.is_first_of_round:
            theta -= WARMUP_OFFSET

        information = build(params).information(theta)
        coverage = coverage_gain(question, req)
        item_concepts = {c.concept_id for c in question.concepts}
        recency = RECENCY_PENALTY if item_concepts & last_concepts else 1.0
        repeat = CONCEPT_REPEAT_PENALTY ** concept_counts.get(question.primary_concept, 0)
        twin = (
            ALIKE_PENALTY
            if any(alike(question.stem, stem) >= ALIKE_AT for stem in asked_stems)
            else 1.0
        )

        score = (
            information * (1.0 + COVERAGE_GAIN * coverage) * recency * repeat * twin
        )
        if stretch:
            reason = SelectionReason.stretch
        elif req.is_first_of_round:
            reason = SelectionReason.warmup
        elif coverage > 0:
            reason = SelectionReason.coverage_debt
        else:
            reason = SelectionReason.max_info
        ranked.append(Candidate(question, information, score, reason))

    ranked.sort(key=lambda c: c.score, reverse=True)
    return ranked


def _result(
    candidate: Candidate,
    req: SelectionRequest,
    *,
    alternatives: list[Question],
    reason: SelectionReason | None = None,
    disclosure: str | None = None,
) -> SelectionResult:
    question = candidate.question
    params = parameters_for(question, req.round_type)
    model = build(params)
    theta = target_theta(req, question)
    return SelectionResult(
        question_id=question.id,
        round_type=req.round_type,
        reason=reason or candidate.reason,
        expected_information=round(candidate.information, 6),
        # Expected score on the item's own scale — never a probability of
        # "correct", which a five-category item cannot express without the
        # collapse §3.1 Trap 2 is about.
        predicted_score=round(model.expected_score(theta), 4),
        n_categories=params.n_categories,
        theta_eligible=question.theta_eligible,
        params_source=params.params_source,
        disclosure=disclosure,
        alternatives=[q.id for q in alternatives],
        scored_use=question.scored_use_approved,
    )


# ─────────────────────────────────────────────────────────────────────────
#  The entry point
# ─────────────────────────────────────────────────────────────────────────


def select(
    bank: list[Question],
    req: SelectionRequest,
    *,
    last_concepts: set[str] | None = None,
    fallback_playlist: list[Question] | None = None,
) -> SelectionResult:
    """Choose the next item. §6.6, falling through §6.8 when the pool empties."""

    # Step 0 — forced items, BEFORE any filter can eliminate them. M04 owns the
    # re-test queue; M13 promised a disputing student a fresh look. Running the
    # freshness filter first is how both promises become empty without anyone
    # noticing, because a filtered-out re-test looks exactly like no re-test.
    if req.forced_item_ids:
        by_id = {q.id: q for q in bank}
        for item_id in req.forced_item_ids:
            forced = by_id.get(item_id)
            if forced is None or not visible_to(forced, req.candidate_id):
                continue
            params = parameters_for(forced, req.round_type)
            candidate = Candidate(
                forced,
                build(params).information(target_theta(req, forced)),
                0.0,
                SelectionReason.forced_retest,
            )
            return _result(
                candidate,
                req,
                alternatives=[],
                reason=SelectionReason.forced_retest,
                disclosure=DISCLOSURE_RETEST,
            )

    by_id = {q.id: q for q in bank}
    asked = [by_id[i] for i in req.asked_this_session if i in by_id]
    pool = eligible(bank, req)
    # An approved item, when one fits, before any draft: a draft's answer is
    # not scored, so it is what a thin track falls back on, never the first
    # choice over a reviewed question.
    approved = [q for q in pool if q.scored_use_approved]
    pool = approved or pool
    if pool:
        ranked = rank(pool, req, last_concepts=last_concepts, asked=asked)
        return _result(ranked[0], req, alternatives=[c.question for c in ranked[1:3]])

    # §6.8 step 1 — relax freshness, and SAY SO. A silent repeat is the failure
    # §2.4 names; an announced one is a re-test the student can reason about.
    relaxed = eligible(bank, req, ignore_freshness=True)
    if relaxed:
        ranked = rank(relaxed, req, last_concepts=last_concepts, asked=asked)
        return _result(
            ranked[0],
            req,
            alternatives=[c.question for c in ranked[1:3]],
            reason=SelectionReason.fallback,
            disclosure=DISCLOSURE_FRESHNESS,
        )

    # §6.8 step 5's last resort before ending the round. The playlist exists so
    # an interview never stalls; it is 30 minutes of work and it is the only
    # thing standing between a thin bank and dead air. It still honours the
    # one filter that is never relaxed: an item already asked in THIS session.
    # Until 2026-10-06 it did not, and a student whose history covered the
    # bank was asked the playlist's first item at the warm-up and again at
    # every round after it — the silent repeat §2.4 names.
    for question in fallback_playlist or []:
        if question.id in req.seen_item_ids or not req.on_concepts(question):
            continue
        if question.usable_in(req.round_type) and visible_to(question, req.candidate_id):
            params = parameters_for(question, req.round_type)
            candidate = Candidate(
                question,
                build(params).information(target_theta(req, question)),
                0.0,
                SelectionReason.fallback,
            )
            return _result(candidate, req, alternatives=[], reason=SelectionReason.fallback)

    raise NoItemAvailable(
        f"no item for round_type={req.round_type!r} after freshness relaxation and "
        "the fallback playlist. End the round and say so — §6.8 step 5. Silently "
        "repeating an item is worse than admitting the bank is thin."
    )


# ─────────────────────────────────────────────────────────────────────────
#  Stopping — §6.9
# ─────────────────────────────────────────────────────────────────────────


def should_stop(
    *,
    se: float,
    required_debt: float,
    items_asked: int,
    max_items: int,
    time_remaining_s: int,
    min_item_time_s: int,
    recent_information: list[float],
) -> StopReason:
    """Whether the round is done, and why.

    **Required coverage outranks SE**, which is the whole reason this returns a
    reason rather than a bool: `SE < 0.30 and debt > 0` is a stop that looks
    correct, ends the round with JD requirements unprobed, and is reported as a
    completed round. M02's contribution is coverage as a *guarantee*.
    """
    if items_asked >= max_items:
        return StopReason.max_items
    if time_remaining_s < min_item_time_s:
        return StopReason.out_of_time
    if se < TARGET_SE and required_debt <= 0:
        return StopReason.measured
    if (
        len(recent_information) >= 3
        and all(i < MIN_INFORMATION for i in recent_information[-3:])
        and required_debt <= 0
    ):
        return StopReason.no_information
    return StopReason.keep_going


__all__ = [
    "COVERAGE_GAIN",
    "DISCLOSURE_FRESHNESS",
    "DISCLOSURE_RETEST",
    "MIN_INFORMATION",
    "STRETCH_OFFSET",
    "TARGET_SE",
    "WARMUP_OFFSET",
    "Candidate",
    "NoItemAvailable",
    "ParamsSource",
    "coverage_gain",
    "eligible",
    "parameters_for",
    "rank",
    "select",
    "should_stop",
    "should_stretch",
    "visible_to",
]
