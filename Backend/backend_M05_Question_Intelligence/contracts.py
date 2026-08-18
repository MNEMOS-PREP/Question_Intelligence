"""M05 data contracts — spec §5.

These are the shapes five other modules read, so they are the expensive part of
this module to change later. Four rules govern them, and three exist because
the review caught the spec breaking them:

1. **Concepts are not defined here.** `Concept` and `ConceptEdge` live in
   `ai_core.concepts`. M05 *tags against* the ontology; it does not get to
   decide what a concept is. Two copies of that type is how M04's mastery map
   and M05's bank quietly stop meaning the same thing by `concept:hash_maps`.

2. **A grounded item is the student's data.** `grounded_for_candidate` is not
   metadata — it is a hard filter and a release gate (§6.12, AC-5.11). A
   question generated from someone's repository carries their service names in
   its stem, and a selection pool that forgets this serves it to the cohort
   while every session looks entirely normal.

3. **Nothing here reintroduces the binary collapse.** `SelectionResult` carries
   `predicted_score` and `n_categories`, never a probability of "correct". Most
   of the bank is rubric-scored 0..4, and §3.1 Trap 2 is precisely about what
   collapsing that costs — a contract that can only express `p_correct` forces
   the trap on every caller.

4. **θ that must not be persisted is named so you cannot persist it by
   accident.** `theta_provisional`, not `theta` (§6.10).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

#: The rubric scale M13 scores on. Mirrored, not redefined — M05 needs it to
#: size a GRM threshold vector and nothing else.
N_CATEGORIES_RUBRIC = 5

#: FR-5.26. One primary, at most two secondary. M13 emits one observation per
#: concept, each carrying the same score and the same evidence spans, so six
#: concepts turn one answer into six beliefs in M04 with `n_direct` incremented
#: six times. That is one piece of evidence counted six times, in the direction
#: that flatters the student.
MAX_SECONDARY_CONCEPTS = 2

#: §2.4. Never repeat an item to a candidate inside this window unless the
#: caller explicitly asks (FR-5.23).
FRESHNESS_DAYS = 90


class Modality(StrEnum):
    verbal = "verbal"
    coding = "coding"
    design = "design"
    mcq = "mcq"
    numeric = "numeric"
    case = "case"
    gd_topic = "gd_topic"


class Provenance(StrEnum):
    curated = "curated"
    synthetic_verified = "synthetic_verified"
    experience_corpus = "experience_corpus"
    textbook = "textbook"
    generated = "generated"
    grounded = "grounded"


class ItemStatus(StrEnum):
    draft = "draft"
    in_review = "in_review"
    active = "active"
    retired = "retired"
    broken = "broken"


class DifficultyBand(StrEnum):
    """What an author can actually judge.

    Nobody reliably authors "0.8 logits". Everybody can rank a question against
    a warm-up. The band → logit table is versioned per round type (§6.5), so
    recalibrating the mapping later is a table bump rather than a re-authoring
    of the bank.
    """

    intro = "intro"
    easy = "easy"
    core = "core"
    hard = "hard"
    stretch = "stretch"


class ParamsSource(StrEnum):
    """Where the numbers in hand came from. M13's shipped `ItemParams` carries
    this field and defaults it to `prior`, so downstream already expects the
    honesty; this is the module that has to supply it."""

    prior = "prior"
    elo = "elo"
    mml = "mml"


# ─────────────────────────────────────────────────────────────────────────
#  Concepts and grounding
# ─────────────────────────────────────────────────────────────────────────


class ConceptRole(StrEnum):
    primary = "primary"
    secondary = "secondary"


class ConceptWeight(BaseModel):
    """One concept an item measures, and how much.

    Only the **primary** may enter a likelihood. Secondary concepts are
    coverage-bearing: they update counts and evidence and never move θ. That is
    M04 §6.3's admissibility rule, applied here rather than fought.
    """

    concept_id: str
    weight: float = Field(gt=0.0, le=1.0)
    role: ConceptRole = ConceptRole.secondary


class GroundingKind(StrEnum):
    repo_decision = "repo_decision"
    resume_claim = "resume_claim"
    jd_requirement = "jd_requirement"
    company_pattern = "company_pattern"


#: §6.12. Below this, M03 cannot vouch that the student wrote the code, and
#: interrogating someone about work that is not theirs is a worse failure than
#: asking a generic question (EC-5.12).
MIN_AUTHORED_CONFIDENCE = 0.6


class GroundingRef(BaseModel):
    kind: GroundingKind
    source_id: str
    source_module: Literal["M01", "M02", "M03", "M15"]
    #: A paraphrase of a decision. NEVER copied source from a private
    #: repository (§6.12).
    excerpt: str | None = None
    authored_confidence: float | None = None

    @model_validator(mode="after")
    def _authored_enough(self) -> GroundingRef:
        if self.kind is not GroundingKind.repo_decision:
            return self
        confidence = self.authored_confidence
        if confidence is None or confidence < MIN_AUTHORED_CONFIDENCE:
            raise ValueError(
                f"repo-grounded item needs authored_confidence >= "
                f"{MIN_AUTHORED_CONFIDENCE} from M03, got {confidence}. "
                "Questioning a student about code they did not write is worse "
                "than asking a generic question (EC-5.12)."
            )
        return self


# ─────────────────────────────────────────────────────────────────────────
#  Item parameters
# ─────────────────────────────────────────────────────────────────────────


class IRTParams(BaseModel):
    """One item's measurement model.

    `b` is a scalar for 2PL/3PL and a **threshold vector** for GRM. The Elo
    path can only ever produce a location, which is exactly why §6.5 pairs it
    with a spacing prior — without that, the whole of Phase 1 has no evaluable
    `information(θ)` for the majority of the bank, and selection silently
    ranks on penalties alone while every function still returns a number.
    """

    model: Literal["2pl", "grm", "3pl"]
    a: float = Field(gt=0.0)
    b: float | list[float]
    c: float | None = None
    se_a: float = 1.0
    se_b: float = 1.2
    n_responses: int = 0
    params_source: ParamsSource = ParamsSource.prior
    estimated_at: datetime | None = None
    bank_version: str = "dev"

    @model_validator(mode="after")
    def _shape_matches_model(self) -> IRTParams:
        if self.model == "grm":
            if not isinstance(self.b, list):
                raise ValueError(
                    "a GRM item needs a threshold VECTOR, not a scalar difficulty. "
                    "If this came from Elo, pass it through the spacing prior first (§6.5)."
                )
            if len(self.b) != N_CATEGORIES_RUBRIC - 1:
                raise ValueError(
                    f"GRM on a 0..{N_CATEGORIES_RUBRIC - 1} scale needs "
                    f"{N_CATEGORIES_RUBRIC - 1} thresholds, got {len(self.b)}"
                )
            if list(self.b) != sorted(self.b):
                raise ValueError(
                    "GRM thresholds must be non-decreasing; out of order means "
                    "P(X>=k) rises with k, which is not a probability."
                )
        elif isinstance(self.b, list):
            raise ValueError(f"{self.model} takes a scalar difficulty, not a vector")
        if self.model == "3pl" and self.c is None:
            raise ValueError("3PL needs a guessing parameter")
        if self.model != "3pl" and self.c is not None:
            raise ValueError(f"{self.model} has no guessing parameter")
        return self

    @property
    def n_categories(self) -> int:
        return N_CATEGORIES_RUBRIC if self.model == "grm" else 2


class ItemModel(Protocol):
    """§6.4 — three models, one interface."""

    def p_correct(self, theta: float) -> float: ...
    def expected_score(self, theta: float) -> float: ...
    def information(self, theta: float) -> float: ...
    def log_likelihood(self, theta: float, response: float) -> float: ...


class QualityStats(BaseModel):
    discrimination: float | None = None
    #: Answers M13 scored with low confidence — a proxy for an ambiguous stem.
    misfire_rate: float = 0.0
    realism_votes_up: int = 0
    realism_votes_down: int = 0
    abandonment_rate: float = 0.0
    mean_time_s: float = 0.0
    flagged_broken: int = 0


# ─────────────────────────────────────────────────────────────────────────
#  The package
# ─────────────────────────────────────────────────────────────────────────


class KeyPoint(BaseModel):
    id: str
    #: NLI-checkable, e.g. "Mentions that the test set was held out". M13
    #: measures coverage against these, so a vague statement becomes a vague
    #: checklist item a student cannot act on.
    statement: str
    weight: float = 1.0
    required: bool = False


class FollowUpTemplate(BaseModel):
    depth: Literal[0, 1, 2, 3, 4, 5]
    template: str
    triggers_when: str = ""


class Question(BaseModel):
    id: UUID
    stem: str
    modality: Modality
    #: ELIGIBILITY, not administration. Exactly one is chosen at selection time
    #: and recorded on `SelectionResult`, because M13 resolves the rubric from a
    #: SINGLE round type and each rubric declares exactly one concept-bearing
    #: dimension. The same item scored under two round types produces
    #: observations about different things from the same stem.
    round_types: list[str] = Field(min_length=1)
    concepts: list[ConceptWeight] = Field(min_length=1)
    role_archetypes: list[str] = Field(default_factory=list)
    company_tags: list[str] = Field(default_factory=list)
    provenance: Provenance
    grounded_on: GroundingRef | None = None
    #: THE PRIVACY FILTER (FR-5.22). None = general bank. Set = this item may
    #: only ever be served to this candidate, and dies with their data.
    grounded_for_candidate: UUID | None = None
    consent_id: UUID | None = None
    difficulty_band: DifficultyBand = DifficultyBand.core
    irt: IRTParams | None = None
    #: Always present, from the first response. A location only (§6.5).
    elo: float = 1500.0
    reference_answer: str = ""
    key_points: list[KeyPoint] = Field(default_factory=list)
    #: M13 resolves the rubric from the round type at scoring time and never
    #: reads an item-level rubric id, so storing one is a field that can
    #: silently disagree with the rubric actually used.
    rubric_round_type: str
    min_rubric_version: str | None = None
    follow_ups: list[FollowUpTemplate] = Field(default_factory=list)
    time_budget_s: int = 300
    hint_ladder: list[str] = Field(default_factory=list)
    stem_simhash: int = 0
    ontology_version: str = "1.0"
    quality: QualityStats = Field(default_factory=QualityStats)
    status: ItemStatus = ItemStatus.draft
    scored_use_approved: bool = False
    #: False for every grounded and coverage-only item. M13 copies this into
    #: the observation's `item`, and M04 leaves θ alone when it is absent. An
    #: item can be perfectly good and still not be an instrument.
    theta_eligible: bool = True

    @model_validator(mode="after")
    def _concepts_are_bounded(self) -> Question:
        primaries = [c for c in self.concepts if c.role is ConceptRole.primary]
        if len(primaries) != 1:
            raise ValueError(
                f"item declares {len(primaries)} primary concepts; exactly one is "
                "required (FR-5.26). M13 emits one observation per concept from a "
                "single dimension score, so without a primary there is no defined "
                "answer to which concept this item actually measures."
            )
        secondaries = len(self.concepts) - 1
        if secondaries > MAX_SECONDARY_CONCEPTS:
            raise ValueError(
                f"item declares {secondaries} secondary concepts, max is "
                f"{MAX_SECONDARY_CONCEPTS} (FR-5.26). Every extra one turns a single "
                "answer into another belief in M04 carrying the same evidence — one "
                "response counted N times."
            )
        total = sum(c.weight for c in self.concepts)
        if total > 1.0 + 1e-9:
            raise ValueError(f"concept weights sum to {total:.3f}; must be <= 1.0")
        return self

    @model_validator(mode="after")
    def _grounded_items_are_scoped_and_consented(self) -> Question:
        """§6.12 — the rule that keeps one student's repo out of another's session."""
        grounded = self.provenance is Provenance.grounded or self.grounded_on is not None
        if not grounded:
            return self
        if self.grounded_for_candidate is None:
            raise ValueError(
                "a grounded item must name the candidate it was built from "
                "(FR-5.22). Its stem carries their design decisions and service "
                "names; unscoped, it is selectable by the whole cohort and every "
                "session still looks entirely normal."
            )
        if self.consent_id is None:
            raise ValueError("a grounded item requires consent_id — no default (§6.12)")
        if self.theta_eligible:
            raise ValueError(
                "a grounded item has been asked once in history, so it has no "
                "calibration and cannot be an instrument (§3.2.5). Set "
                "theta_eligible=False."
            )
        return self

    @property
    def primary_concept(self) -> str:
        return next(c.concept_id for c in self.concepts if c.role is ConceptRole.primary)

    def usable_in(self, round_type: str) -> bool:
        return round_type in self.round_types


class QuestionPackage(BaseModel):
    """What M13 receives. Its shipped `adapters.QuestionPackage`, exactly.

    `round_type` is singular and `concepts` is a mapping, because that is what
    the consumer's dataclass declares — a contract is what the other side can
    actually parse, not what reads nicely here.
    """

    question_id: UUID
    stem: str
    reference_answer: str
    key_points: list[KeyPoint] = Field(default_factory=list)
    round_type: str
    concepts: dict[str, float] = Field(default_factory=dict)
    item: dict | None = None
    label: str = ""


# ─────────────────────────────────────────────────────────────────────────
#  Selection
# ─────────────────────────────────────────────────────────────────────────


class OutcomeBand(StrEnum):
    below = "below"
    at = "at"
    above = "above"


class ProvisionalOutcome(BaseModel):
    """M06's `ProbeStrategist` verdict — the only signal fast enough to branch on.

    M13's real evaluation lands up to 15 s later (AC-13.13) and never feeds
    selection; it corrects the durable record through M04 instead (§6.10).
    """

    turn_id: UUID
    band: OutcomeBand
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    latency_ms: int = 0


class SelectionReason(StrEnum):
    max_info = "max_info"
    coverage_debt = "coverage_debt"
    stretch = "stretch"
    warmup = "warmup"
    recovery = "recovery"
    forced_retest = "forced_retest"
    forced_review = "forced_review"
    fallback = "fallback"


class SelectionRequest(BaseModel):
    candidate_id: UUID
    session_id: UUID
    round_type: str
    #: M05's OWN in-memory estimate, seeded from M04 at session bootstrap and
    #: updated from `ProvisionalOutcome`. Never persisted, never displayed,
    #: discarded at session end (§6.10). Calling it `theta` invited the reading
    #: that M04 supplies it per call — under which it never moves during a
    #: session, and the CAT silently becomes a fixed-form test at entry ability
    #: while still reporting itself as adaptive.
    theta_provisional: dict[str, float] = Field(default_factory=dict)
    theta_seeded_from: str = "cold"
    provisional_updates: int = 0
    se: dict[str, float] = Field(default_factory=dict)
    coverage_debt: dict[str, float] = Field(default_factory=dict)
    #: The subset that outranks the SE stopping rule (§6.9).
    required_requirement_ids: set[str] = Field(default_factory=set)
    seen_item_ids: set[UUID] = Field(default_factory=set)
    recent_item_ids: set[UUID] = Field(default_factory=set)
    time_remaining_s: int = 1800
    is_first_of_round: bool = False
    stretch_used: bool = False
    round_progress: float = Field(ge=0.0, le=1.0, default=0.0)
    modality_allowed: list[Modality] = Field(default_factory=list)
    #: M04 owns the retest_queue row and sets `bypass_freshness` on it. Without
    #: somewhere to put it, the 90-day filter silently empties both M04's
    #: re-test promise and M13's promise to a disputing student.
    forced_item_ids: list[UUID] = Field(default_factory=list)
    bypass_freshness: bool = False

    def theta_for(self, concept_id: str) -> float:
        return self.theta_provisional.get(concept_id, 0.0)


class SelectionResult(BaseModel):
    question_id: UUID
    #: The ONE round type this administration is under. M13 scores against the
    #: rubric for exactly this value.
    round_type: str
    reason: SelectionReason
    expected_information: float = 0.0
    #: Expected score on the ITEM'S OWN scale, with its category count beside
    #: it. `predicted_p_correct` was Trap 2 in contract form: most of the bank
    #: is rubric-scored 0..4, and a probability of "correct" cannot be formed
    #: for a GRM item without the binary collapse this module exists to avoid.
    predicted_score: float = 0.0
    n_categories: int = 2
    theta_eligible: bool = True
    params_source: ParamsSource = ParamsSource.prior
    #: Set when freshness was relaxed or a re-test forced. Shown to the student
    #: verbatim (§2.4) — a repeat they were warned about is a re-test; an
    #: unannounced one is the complaint this module is named for.
    disclosure: str | None = None
    alternatives: list[UUID] = Field(default_factory=list)


class StopReason(StrEnum):
    measured = "measured"
    max_items = "max_items"
    out_of_time = "out_of_time"
    no_information = "no_information"
    keep_going = "keep_going"


__all__ = [
    "FRESHNESS_DAYS",
    "MAX_SECONDARY_CONCEPTS",
    "MIN_AUTHORED_CONFIDENCE",
    "N_CATEGORIES_RUBRIC",
    "ConceptRole",
    "ConceptWeight",
    "DifficultyBand",
    "FollowUpTemplate",
    "GroundingKind",
    "GroundingRef",
    "IRTParams",
    "ItemModel",
    "ItemStatus",
    "KeyPoint",
    "Modality",
    "OutcomeBand",
    "ParamsSource",
    "Provenance",
    "ProvisionalOutcome",
    "QualityStats",
    "Question",
    "QuestionPackage",
    "SelectionReason",
    "SelectionRequest",
    "SelectionResult",
    "StopReason",
]
