"""Selection, the contracts, and the rules that have to be structural — §6.6.

The gates in here are the ones that fail a release. Each corresponds to a
failure that is invisible in normal use: both sessions look fine, both students
get scored, and the damage is only visible from outside the system.
"""

from __future__ import annotations

import uuid

import pytest

from backend_M05_Question_Intelligence import selection as sel
from backend_M05_Question_Intelligence.contracts import (
    ConceptRole,
    ConceptWeight,
    DifficultyBand,
    ItemStatus,
    ParamsSource,
    Question,
    SelectionReason,
    StopReason,
)

from .conftest import CANDIDATE, OTHER_CANDIDATE, make_grounded, make_question

# ── AC-5.11 · a grounded item never leaves its subject ───────────────────


@pytest.mark.gate
def test_a_grounded_item_is_invisible_to_everyone_else(bank, req):
    """FR-5.22, and the reason it is a gate rather than a filter.

    The stem carries the other student's service names and design decisions.
    Unscoped, it is selectable by the whole cohort — and nothing looks wrong:
    both sessions complete, both get scored, and the leak is only visible to
    the student who recognises their own project in someone else's interview.
    """
    theirs = make_grounded(OTHER_CANDIDATE)
    pool = sel.eligible([*bank, theirs], req)

    assert theirs not in pool
    assert all(sel.visible_to(q, CANDIDATE) for q in pool)


@pytest.mark.gate
def test_the_scoping_survives_every_relaxation(req):
    """The freshness bypass is the path most likely to skip a filter, because
    it is the one written as an exception."""
    theirs = make_grounded(OTHER_CANDIDATE)
    relaxed = req.model_copy(update={"bypass_freshness": True})

    assert sel.eligible([theirs], relaxed) == []
    assert sel.eligible([theirs], req, ignore_freshness=True) == []
    with pytest.raises(sel.NoItemAvailable):
        sel.select([theirs], relaxed)


def test_a_candidate_does_see_their_own_grounded_item(req):
    mine = make_grounded(CANDIDATE)
    assert sel.eligible([mine], req) == [mine]
    assert sel.select([mine], req).question_id == mine.id


@pytest.mark.gate
def test_a_grounded_item_cannot_be_theta_eligible():
    """§3.2.5 — asked once in history, so it has no calibration and cannot be
    an instrument. The contract refuses it rather than trusting an author."""
    with pytest.raises(ValueError, match="theta_eligible=False"):
        make_grounded(CANDIDATE, theta_eligible=True)


def test_a_grounded_item_must_name_a_candidate():
    with pytest.raises(ValueError, match="must name the candidate"):
        make_grounded(CANDIDATE, grounded_for_candidate=None)


def test_repo_grounding_needs_m03_to_vouch_for_authorship():
    """EC-5.12. Interrogating a student about code they did not write is a
    worse failure than asking something generic."""
    from backend_M05_Question_Intelligence.contracts import GroundingKind, GroundingRef

    with pytest.raises(ValueError, match="authored_confidence"):
        GroundingRef(
            kind=GroundingKind.repo_decision,
            source_id="repo:x#1",
            source_module="M03",
            authored_confidence=0.3,
        )


# ── AC-5.13 · a forced re-test survives the freshness filter ─────────────


@pytest.mark.gate
def test_a_forced_retest_outranks_freshness(bank, req):
    """M04 owns the retest_queue row and M13 promised a disputing student a
    fresh question. Both arrive here as `forced_item_ids`, and if the freshness
    filter runs first they die silently — a suppressed re-test is
    indistinguishable from no re-test."""
    target = bank[3]
    forced = req.model_copy(
        update={
            "forced_item_ids": [target.id],
            "recent_item_ids": {q.id for q in bank},  # everything is stale
        }
    )

    result = sel.select(bank, forced)

    assert result.question_id == target.id
    assert result.reason is SelectionReason.forced_retest
    assert result.disclosure, "a repeat the student was not told about is the complaint"


def test_a_forced_item_belonging_to_someone_else_is_still_refused(bank, req):
    """Forcing outranks freshness. It does not outrank privacy."""
    theirs = make_grounded(OTHER_CANDIDATE)
    forced = req.model_copy(update={"forced_item_ids": [theirs.id]})

    result = sel.select([*bank, theirs], forced)
    assert result.question_id != theirs.id


def test_a_relaxed_repeat_is_disclosed(bank, req):
    """§6.8 step 1 — the relaxation is fine; doing it silently is not."""
    stale = req.model_copy(update={"recent_item_ids": {q.id for q in bank}})
    result = sel.select(bank, stale)

    assert result.disclosure == sel.DISCLOSURE_FRESHNESS
    assert result.reason is SelectionReason.fallback


def test_an_empty_bank_ends_the_round_rather_than_repeating(req):
    with pytest.raises(sel.NoItemAvailable, match="admitting the bank is thin"):
        sel.select([], req)


def test_the_fallback_playlist_is_the_last_line(req):
    """§6.8 — 30 minutes of work, and it guarantees the interview never stalls."""
    playlist = [make_question(concept="concept:hashing")]
    result = sel.select([], req, fallback_playlist=playlist)
    assert result.question_id == playlist[0].id
    assert result.reason is SelectionReason.fallback


def test_the_playlist_never_repeats_an_item_within_the_session(req):
    """§6.6's hard filter holds at the last resort too. A live M06 run asked
    the playlist's first item at the warm-up and again at the next round
    (2026-10-06): the student's history had emptied the bank, and the playlist
    ignored what this session had already asked."""
    first = make_question(concept="concept:hashing")
    second = make_question(concept="concept:recursion")
    asked = req.model_copy(update={"seen_item_ids": {first.id}})
    result = sel.select([], asked, fallback_playlist=[first, second])
    assert result.question_id == second.id
    spent = req.model_copy(update={"seen_item_ids": {first.id, second.id}})
    with pytest.raises(sel.NoItemAvailable, match="admitting the bank is thin"):
        sel.select([], spent, fallback_playlist=[first, second])


# ── AC-5.14 · selection works with nothing calibrated ────────────────────


@pytest.mark.gate
def test_selection_ranks_on_information_with_a_cold_bank(bank, req):
    """§6.5 / §3.2 — cold start is 100% of Phase 1.

    If `parameters_for` could return None, a caller would branch, and the else
    branch is where the CAT silently stops being adaptive for a whole phase
    while every function still returns a number.
    """
    assert all(q.irt is None for q in bank)

    ranked = sel.rank(sel.eligible(bank, req), req)

    assert all(c.information > 0 for c in ranked)
    assert len({c.information for c in ranked}) > 1, "every item equally informative == no CAT"
    assert sel.select(bank, req).params_source is ParamsSource.prior


def test_a_cold_selection_targets_the_students_ability(bank, req):
    """A strong candidate gets a harder item — the whole product claim."""
    strong = req.model_copy(update={"theta_provisional": {"concept:hashing": 1.8}})
    weak = req.model_copy(update={"theta_provisional": {"concept:hashing": -1.8}})
    only_hash_maps = [q for q in bank if q.primary_concept == "concept:hashing"]

    def band_of(request):
        chosen = sel.select(only_hash_maps, request).question_id
        return next(q.difficulty_band for q in only_hash_maps if q.id == chosen)

    hard_bands = {DifficultyBand.hard, DifficultyBand.stretch}
    easy_bands = {DifficultyBand.intro, DifficultyBand.easy}
    assert band_of(strong) in hard_bands
    assert band_of(weak) in easy_bands


# ── the contract SelectionResult carries ─────────────────────────────────


def test_the_result_reports_an_expected_score_not_a_probability(bank, req):
    """§3.1 Trap 2 in contract form. Most of the bank is rubric-scored 0..4 and
    a 'p correct' cannot be formed for it without the collapse."""
    result = sel.select(bank, req)

    assert result.n_categories == 5
    assert 0.0 <= result.predicted_score <= 4.0
    assert not hasattr(result, "predicted_p_correct")


def test_the_result_names_the_one_round_type_it_was_administered_under(bank, req):
    """M13 resolves the rubric from a single round type, and each rubric has
    exactly one concept-bearing dimension."""
    assert sel.select(bank, req).round_type == req.round_type


# ── warm-up, stretch, and the flow zone (§2.2) ───────────────────────────


def test_the_first_item_of_a_round_opens_below_ability(bank, req):
    opening = req.model_copy(update={"is_first_of_round": True})
    assert sel.select(bank, opening).reason is SelectionReason.warmup


def test_the_stretch_item_lands_in_its_window_and_only_once():
    assert not sel.should_stretch(_at(0.2))
    assert sel.should_stretch(_at(0.7))
    assert not sel.should_stretch(_at(0.95)), "never last — §2.2"
    assert not sel.should_stretch(_at(0.7, used=True))


def _at(progress: float, *, used: bool = False):
    from backend_M05_Question_Intelligence.contracts import SelectionRequest

    return SelectionRequest(
        candidate_id=CANDIDATE,
        session_id=uuid.uuid4(),
        round_type="dsa_verbal",
        round_progress=progress,
        stretch_used=used,
    )


def test_the_stretch_item_is_above_ability(bank, req):
    stretching = req.model_copy(update={"round_progress": 0.7})
    result = sel.select(bank, stretching)
    assert result.reason is SelectionReason.stretch


# ── hard filters ─────────────────────────────────────────────────────────


def test_unapproved_and_broken_items_never_reach_a_student(bank, req):
    draft = make_question(status=ItemStatus.draft)
    unapproved = make_question(scored_use_approved=False)
    broken = make_question()
    broken.quality.flagged_broken = 1

    pool = sel.eligible([*bank, draft, unapproved, broken], req)
    for excluded in (draft, unapproved, broken):
        assert excluded not in pool


def test_an_item_longer_than_the_time_left_is_not_offered(bank, req):
    rushed = req.model_copy(update={"time_remaining_s": 60})
    assert sel.eligible(bank, rushed) == []


def test_a_wrong_round_type_is_a_hard_filter(bank, req):
    hr = make_question(round_type="hr_behavioural")
    assert hr not in sel.eligible([*bank, hr], req)


# ── FR-5.26 · one answer must not become six beliefs ─────────────────────


@pytest.mark.gate
def test_an_item_cannot_declare_more_than_three_concepts():
    """M13 emits one observation per concept, each with the same score and the
    same evidence. Six concepts turn one answer into six beliefs in M04 with
    `n_direct` incremented six times — one response counted six times, in the
    direction that flatters the student."""
    with pytest.raises(ValueError, match="secondary concepts"):
        make_question(secondary=["concept:a", "concept:b", "concept:c"])


def test_an_item_needs_exactly_one_primary_concept():
    with pytest.raises(ValueError, match="primary concepts"):
        Question(
            id=uuid.uuid4(),
            stem="x",
            modality="verbal",
            round_types=["dsa_verbal"],
            concepts=[
                ConceptWeight(concept_id="concept:a", weight=0.4, role=ConceptRole.primary),
                ConceptWeight(concept_id="concept:b", weight=0.4, role=ConceptRole.primary),
            ],
            provenance="curated",
            rubric_round_type="dsa_verbal",
        )


def test_concept_weights_cannot_exceed_one():
    with pytest.raises(ValueError, match="sum to"):
        Question(
            id=uuid.uuid4(),
            stem="x",
            modality="verbal",
            round_types=["dsa_verbal"],
            concepts=[
                ConceptWeight(concept_id="concept:a", weight=0.8, role=ConceptRole.primary),
                ConceptWeight(concept_id="concept:b", weight=0.5, role=ConceptRole.secondary),
            ],
            provenance="curated",
            rubric_round_type="dsa_verbal",
        )


# ── AC-5.16 · coverage outranks the SE stopping rule ─────────────────────


@pytest.mark.gate
def test_a_round_does_not_stop_measured_with_required_coverage_open():
    """On a strong candidate SE collapses in three or four items. Stopping
    there ends the round with JD requirements unprobed while the report still
    says it completed — and M02's guarantee becomes an intention again."""
    common = dict(
        items_asked=4,
        max_items=12,
        time_remaining_s=900,
        min_item_time_s=120,
        recent_information=[0.9, 0.8, 0.7],
    )
    assert sel.should_stop(se=0.2, required_debt=0.0, **common) is StopReason.measured
    assert sel.should_stop(se=0.2, required_debt=0.6, **common) is StopReason.keep_going


def test_the_time_budget_still_binds_over_coverage():
    """Coverage outranks SE. It does not outrank the clock — §6.8 step 5 ends
    the round and says so rather than running over."""
    assert (
        sel.should_stop(
            se=0.9,
            required_debt=0.9,
            items_asked=2,
            max_items=12,
            time_remaining_s=30,
            min_item_time_s=120,
            recent_information=[],
        )
        is StopReason.out_of_time
    )


def test_a_round_stops_when_it_has_stopped_learning():
    assert (
        sel.should_stop(
            se=0.5,
            required_debt=0.0,
            items_asked=8,
            max_items=12,
            time_remaining_s=900,
            min_item_time_s=120,
            recent_information=[0.05, 0.04, 0.03],
        )
        is StopReason.no_information
    )
