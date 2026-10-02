"""HTTP surface — spec §7.

Only endpoints this module can honestly serve today. Generation, the G1–G5
gates, the review queue and nightly recalibration are milestones M6 and M7 and
are **absent rather than stubbed**: an endpoint that exists and returns a
placeholder is worse than one that does not, because a caller writes against it
and finds out later.

The session endpoints are the interesting half. They exist because M05 owns the
in-session provisional θ (§6.10), and there is deliberately **no**
`GET /v1/sessions/{id}/theta` — the estimate is not displayable and not durable,
and an endpoint returning it is the shortest path to it appearing in a report.

Who may ask (Platform_Core v0.11.0's `candidate_guard`, on the router): a
session's routes answer only the student whose session it is — the id resolves
to its owner — and the routes whose BODY names a student (`seed`, `select`,
the ⚑) check that student in the handler. Until 2026-10-02 none of this
existed, and any caller could exclude any item from selection or read another
student's provisional estimate through `select`.
"""

from __future__ import annotations

import logging
import uuid

from ai_core import service
from ai_core.guard import candidate_guard, require_candidate
from ai_core.identity import Principal, Role
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import bank as bank_module
from . import ontology as ontology_module
from . import selection as selection_module
from . import session as session_module
from .contracts import (
    ProvisionalOutcome,
    Question,
    QuestionPackage,
    SelectionRequest,
    SelectionResult,
)
from .dependencies import deps
from .models_irt import BAND_TABLE_VERSION

log = logging.getLogger(__name__)


def _session_owner(session_id: str) -> str | None:
    """The student a seeded session belongs to, or None for one nobody seeded
    — the guard then lets the handler 404 rather than confirm it exists."""
    try:
        state = _SESSIONS.get(uuid.UUID(session_id))
    except ValueError:
        return None
    return str(state.candidate_id) if state is not None else None


guard = candidate_guard({"session_id": _session_owner})
router = APIRouter(prefix="/v1", tags=["questions"], dependencies=[Depends(guard)])

#: Sessions live in memory and die with the process — that is the contract, not
#: a shortcut (§6.10). A restart loses provisional estimates and costs nothing
#: durable, because M04 holds everything that matters.
_SESSIONS: dict[uuid.UUID, session_module.SessionState] = {}


class SeedRequest(BaseModel):
    candidate_id: uuid.UUID
    #: M04's posterior per concept. Absent is the normal case for a new
    #: candidate and for a checkout with no M04 running.
    posterior: dict[str, float] = Field(default_factory=dict)
    snapshot_id: str = "cold"


class ObserveRequest(BaseModel):
    concept_id: str
    outcome: ProvisionalOutcome


class CloseRequest(BaseModel):
    #: M04's recomputed posterior. It wins, silently (§6.10).
    posterior: dict[str, float] = Field(default_factory=dict)


class FlagRequest(BaseModel):
    reason: str
    note: str = ""
    candidate_id: uuid.UUID | None = None


# ── meta ─────────────────────────────────────────────────────────────────


@router.get("/deps")
def dependencies() -> dict:
    """Which upstreams are up, and what breaks without them (§6.11)."""
    concepts = ontology_module.load()
    return {
        "module": "M05",
        "dependencies": [d.model_dump(mode="json") for d in deps().statuses()],
        "degraded": [f.model_dump(mode="json") for f in deps().degraded()],
        "ontology_source": concepts.source,
        "ontology_reviewed": concepts.reviewed,
        "band_table_version": BAND_TABLE_VERSION,
        # No item in the bank has been calibrated. Every parameter set comes
        # from the band table and the spacing prior, and `params_source` on a
        # selection says so per item rather than in aggregate.
        "calibration": "none",
    }


@router.get("/ontology")
def read_ontology() -> dict:
    concepts = ontology_module.load()
    counts = bank_module.load().concept_counts()
    return {
        "version": concepts.version,
        "source": concepts.source,
        "reviewed": concepts.reviewed,
        "n_concepts": len(concepts),
        "granularity": ontology_module.granularity(counts, concepts),
    }


# ── the bank ─────────────────────────────────────────────────────────────


#: The fields that answer the question. A module asking for an item gets them —
#: M06 probes against the key points, M13 scores against the reference — and a
#: browser does not.
ANSWER_KEY = ("reference_answer", "key_points", "follow_ups", "hint_ladder")


#: Each answer field at its own empty default, read from the model rather than
#: restated, so a field added to `ANSWER_KEY` cannot be blanked with the wrong type.
_WITHHELD = {
    name: Question.model_fields[name].get_default(call_default_factory=True) for name in ANSWER_KEY
}


def _may_have_the_key(request: Request, principal: Principal | None) -> bool:
    return service.is_service(request) or (principal is not None and principal.role is Role.admin)


@router.get("/questions/{question_id}", response_model=Question)
def read_question(
    question_id: uuid.UUID,
    request: Request,
    response: Response,
    principal: Principal | None = Depends(guard),
) -> Question:
    """One item — and its answer key only for a module (or an administrator).

    Until 2026-10-02 this served every item whole to anybody holding its id:
    the reference answer, the key points M06 probes against, the follow-ups
    and the full hint ladder. A student who opened the network tab mid-
    interview had the marking scheme. The stem and the item's metadata are
    still public — they are what the student is being asked — and the four
    answer fields come back empty, with `X-Answer-Key: withheld` saying so
    rather than letting "no key points" pass for a fact about the item.

    A GROUNDED item (FR-5.22) is built from one student's own repository, and
    its stem carries their design decisions. It is theirs: anybody else is
    refused, exactly as `select` already refuses to serve it to them.
    """
    question = bank_module.load().get(question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="no such question")
    keyed = _may_have_the_key(request, principal)
    if question.grounded_for_candidate is not None and not keyed:
        require_candidate(principal, question.grounded_for_candidate)
    if keyed:
        return question
    response.headers["X-Answer-Key"] = "withheld"
    return question.model_copy(update=_WITHHELD)


@router.get(
    "/questions/{question_id}/package",
    response_model=QuestionPackage,
    dependencies=[Depends(service.require_service)],
)
def read_package(question_id: uuid.UUID, round_type: str) -> QuestionPackage:
    """What M13 receives. Its `adapters.QuestionPackage`, exactly.

    Service-only (Platform_Core v0.12.0): a package is the item's answer key
    and nothing else, so only a module holding the platform secret gets one.

    `round_type` is a required query parameter rather than a field on the item,
    because M13 resolves the rubric from a single round type and each rubric
    declares exactly one concept-bearing dimension. An item eligible in two
    round types has two packages, and which one was administered is a fact
    about the turn, not about the item.
    """
    question = bank_module.load().get(question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="no such question")
    if not question.usable_in(round_type):
        raise HTTPException(
            status_code=422,
            detail=f"item is not eligible in {round_type!r}; it allows {question.round_types}",
        )
    return _package(question, round_type)


def _package(question: Question, round_type: str) -> QuestionPackage:
    params = selection_module.parameters_for(question, round_type)
    return QuestionPackage(
        question_id=question.id,
        stem=question.stem,
        reference_answer=question.reference_answer,
        key_points=question.key_points,
        round_type=round_type,
        concepts={c.concept_id: c.weight for c in question.concepts},
        # `item` is what makes an observation θ-eligible in M04. A grounded or
        # coverage-only item sends None, and M04 then updates counts and
        # evidence and leaves the ability estimate alone — which is correct,
        # not a degradation.
        item=(
            {
                "question_id": str(question.id),
                "irt_model": params.model,
                "a": params.a,
                "b": params.b,
                "params_source": str(params.params_source),
                "bank_version": params.bank_version,
            }
            if question.theta_eligible
            else None
        ),
    )


@router.get("/bank/health")
def bank_health() -> dict:
    """§8.2. The exhaustion column is what tells you what to author next —
    without it you write more array questions, because those are easy to write."""
    loaded = bank_module.load()
    counts = loaded.concept_counts()
    gaps = ontology_module.granularity(counts)
    return {
        "active": len(loaded.questions),
        "playlist": len(loaded.playlist),
        "concepts_covered": len(counts),
        "concepts_total": len(ontology_module.load()),
        "thin": gaps["thin"][:40],
        "n_thin": len(gaps["thin"]),
        "counts": counts,
        "note": (
            f"{len(gaps['thin'])} of {len(ontology_module.load())} concepts have fewer than "
            f"{ontology_module.MIN_ITEMS_PER_CONCEPT} items, so M04's granularity check "
            "cannot pass yet. Authoring is the long pole and it has no code dependency."
        ),
    }


@router.post("/questions/{question_id}/flag")
def flag_question(
    question_id: uuid.UUID,
    request: FlagRequest,
    principal: Principal | None = Depends(guard),
) -> dict:
    """FR-5.19 / EC-5.9 — the cheapest quality signal this module has.

    The half that is NOT built yet is the important half: M04's spec names
    EC-5.9 as a retraction source, so flagging must also retract every
    observation derived from the item. That needs M13's turn history and lands
    with the M04 client — the response says so rather than implying the student
    has been fully served.
    """
    # A flag excludes the item for everybody, so somebody has to be asking —
    # and when the body says on whose behalf, it has to be them.
    if principal is None:
        raise HTTPException(status_code=401, detail="Sign in to flag a question.")
    if request.candidate_id is not None:
        require_candidate(principal, request.candidate_id)
    question = bank_module.load().get(question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="no such question")
    question.quality.flagged_broken += 1
    log.warning("item %s flagged: %s %s", question_id, request.reason, request.note)
    return {
        "question_id": str(question_id),
        "flagged_broken": question.quality.flagged_broken,
        "excluded_from_selection": True,
        "retraction_sent": False,
        "note": (
            "The item is excluded from future selection. Retracting observations "
            "already sent to M04 (EC-5.9) is not wired yet, so a flagged item may "
            "still be moving mastery until it is."
        ),
        "student_message": (
            "Thanks — I've pulled that question, and you won't see it again."
        ),
    }


# ── selection ────────────────────────────────────────────────────────────


@router.post("/questions/select", response_model=SelectionResult)
def select(
    request: SelectionRequest, principal: Principal | None = Depends(guard)
) -> SelectionResult:
    """§6.6. The provisional theta comes from THIS module unless the caller says.

    `SelectionRequest.theta_provisional` used to be required of the caller,
    which put a caller in an impossible position: §6.10 says this estimate is
    ours, is never persisted and dies with the session — and any caller that
    checkpoints its own state (M06 does, after every step) would have been
    persisting it to pass it back. `ProvisionalIsNotDurable` exists to stop
    precisely that.

    So: the seeded session's estimate is the default, and an explicit
    `theta_provisional` still wins — the simulator passes one, and a test
    needs to.
    """
    require_candidate(principal, request.candidate_id)
    loaded = bank_module.load()
    state = _SESSIONS.get(request.session_id)
    if state is not None:
        # The seeded estimate is read below; it must be this student's. A
        # stranger naming themselves in the body and somebody else's session
        # id would otherwise be selected for with that person's θ.
        require_candidate(principal, state.candidate_id)
    if state is not None and not request.theta_provisional:
        request = request.model_copy(
            update={
                "theta_provisional": dict(state.theta),
                "se": dict(state.se) or request.se,
                "theta_seeded_from": state.seeded_from,
                "provisional_updates": state.updates,
                # Items already administered in this session, from the state
                # that recorded them. A caller may add its own durable history.
                "seen_item_ids": set(request.seen_item_ids) | set(state.administered),
            }
        )
    try:
        return selection_module.select(
            loaded.questions, request, fallback_playlist=loaded.playlist
        )
    except selection_module.NoItemAvailable as exc:
        # 409, not 500. The bank being thin for this round type is a known
        # state with a specified behaviour (§6.8 step 5) — the caller ends the
        # round and tells the student honestly, which it cannot do if this
        # looks like a crash.
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ── the session's provisional θ (§6.10) ──────────────────────────────────


@router.post("/sessions/{session_id}/theta/seed")
def seed_theta(
    session_id: uuid.UUID, request: SeedRequest, principal: Principal | None = Depends(guard)
) -> dict:
    # A new session has no owner for the guard to resolve; the body names one.
    require_candidate(principal, request.candidate_id)
    state = session_module.seed_from_m04(
        session_id,
        request.candidate_id,
        request.posterior or None,
        snapshot_id=request.snapshot_id,
    )
    _SESSIONS[session_id] = state
    return {
        "session_id": str(session_id),
        "seeded_from": state.seeded_from,
        "concepts": len(state.theta),
        "note": (
            "This estimate is session-scoped, is never persisted or displayed, and "
            "is discarded at close. M04 owns the durable posterior."
        ),
    }


@router.post("/sessions/{session_id}/theta/observe")
def observe(session_id: uuid.UUID, request: ObserveRequest) -> dict:
    state = _SESSIONS.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="no such session; seed it first")
    moved = state.observe(request.concept_id, request.outcome)
    return {
        "concept_id": request.concept_id,
        "theta_provisional": moved,
        "updates": state.updates,
    }


@router.post("/sessions/{session_id}/close")
def close_session(session_id: uuid.UUID, request: CloseRequest) -> dict:
    """§6.10 — the posterior wins, silently, and divergence is a signal."""
    state = _SESSIONS.pop(session_id, None)
    if state is None:
        raise HTTPException(status_code=404, detail="no such session")
    divergence = session_module.reconcile(state, request.posterior)
    return {
        "session_id": str(session_id),
        "updates": state.updates,
        "divergence": divergence,
        "note": (
            "Provisional θ discarded. Where M04's posterior disagreed with it, M04 "
            "is right and the student is told nothing — the number was never ours "
            "to set. Divergence beyond 0.5 logits is a calibration signal."
        ),
    }
