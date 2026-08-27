# M5 — Question Intelligence: Bank, Generation, IRT/CAT, Freshness

> **Master plan reference:** §31 · **Phase:** 1–2 · **Owner:** E3 · **Depends on:** M4 (ontology, mastery), M2 (coverage plan), M1/M3 (grounding sources) · **Feeds:** M6, M9, M10, M14, M16 · **Research:** Paper 2

> **Revision 2** — reviewed in `M05_REVIEW.md` against the *shipped* code of
> M04 and M13. Five contract breaks, ten internal contradictions and three
> missing sections are corrected here. The largest: **M05 owns the in-session
> provisional θ** (§6.10) — M04 and M06 were both amended to say so and this
> document had not been. The second largest: a grounded item was selectable
> by any candidate, not just its subject (§6.12).

---

## 1. In one paragraph

This module answers the second-most-important question in the platform: **what do we ask next?** It owns the question bank, generates new items grounded in the student's own resume/repo/JD, calibrates every item's difficulty from real response data using Item Response Theory, and selects each next question to extract the maximum information about the student's ability while still covering what the job requires, avoiding repeats, and slipping in exactly one item above their level to find the ceiling. Done well, a 40-minute interview learns more about a student than a 90-minute fixed test. Done badly, it feels like a random quiz — which is what every competitor feels like.

---

## 2. Reverse-thinking: the user

### 2.1 The user never asks for "adaptive testing"

They say four things, and each maps to a mechanism:

| What the student says | What they mean | Mechanism |
|---|---|---|
| *"It felt like it was actually testing me"* | Difficulty tracked ability | CAT via Fisher information |
| *"It asked about MY project"* | Grounded generation | Repo/resume-grounded items |
| *"It didn't waste my time on easy stuff"* | Efficient information gain | θ-targeted selection |
| *"I got the same question again"* ← **the complaint** | Freshness failure | Per-candidate exposure control |

### 2.2 The difficulty experience — the "flow zone"

The felt experience of a good adaptive interview:

```
Q1  ~ability      "OK, standard."
Q2  slightly up   "Hmm, that's a bit harder."      ← they got Q1 right
Q3  up again      "This is genuinely challenging."
Q4  ↓ recovery    "Right, I can do this."           ← they stumbled on Q3
Q5  stretch       "I don't think I can solve this." ← the ceiling probe, ONE per session
Q6  ~ability      "Back on solid ground."           ← never end on the ceiling
```

**The last row is a product rule, not a statistical one.** Ending a session on the item they failed leaves them feeling worse than when they arrived, and a demotivated student doesn't come back. The stretch item is placed at ~70% through the round, never last. This costs a small amount of measurement efficiency and is worth it.

### 2.3 What the student sees

Mostly nothing — and that's correct. Three deliberate exceptions:

**(a) A difficulty indicator, honestly labelled.** Not a "level 7/10" — a relative one:
```
Question 3 of ~6      ● ● ○     ← harder than your last one
```
Why show it at all: students otherwise attribute a hard question to bad luck rather than to progress. Naming it converts frustration into signal.

**(b) After the stretch item:**
```
That one was deliberately above your current level — I use one
per session to find your ceiling. Not solving it costs you nothing.
```
This single sentence prevents the single most common demoralisation event in adaptive testing.

**(c) In the report:**
```
  Difficulty you handled comfortably:   ▓▓▓▓▓▓▓░░░  medium
  Your ceiling today:                    one step above
  Questions needed to work this out:     6  (a fixed test would need ~14)
```
The last line is our differentiation, stated as a benefit to *them*, and it happens to be Paper 2's headline metric.

### 2.4 The freshness contract

Students practise repeatedly and talk to each other. Two failures:

1. **Self-repeat** — "I got this exact question last week." Feels lazy, and destroys the measurement (they memorised the answer, so the score is fake).
2. **Cohort leak** — question X circulates in the batch WhatsApp group by Thursday.

Counters: never repeat an item to a candidate within 90 days unless the Counselor *schedules* it as a re-test (and then we say so: *"You saw this in June — I'm re-testing it deliberately"*), never within a session, and cohort-level Sympson–Hetter exposure control so no item exceeds a 25% exposure rate in a batch.

---

## 3. Reverse-thinking: the developer

### 3.1 The eight traps

**Trap 1 — Calibrating IRT on 5 responses.** Item parameters from tiny samples are noise, and noisy `b` makes selection worse than random. *Counter: an author-set `difficulty_band` mapped through a versioned band→logit table, plus Elo online until n ≥ 30 responses; only then does MML-estimated IRT take over, and only for that item (§6.5). Nobody can reliably author "0.8 logits"; everybody can rank a question against a warm-up.*

**Trap 2 — Using binary 2PL on rubric-scored answers.** An open-ended answer scored 0–4 is ordinal, not binary. Collapsing it to right/wrong throws away most of the information and biases `b`. *Counter: Samejima's Graded Response Model for rubric items, 2PL for auto-gradable, 3PL for MCQ aptitude. Three models, one interface (§6.4).*

**Trap 3 — Pure max-information selection.** It will happily ask six DP questions in a row because DP has the most informative items near θ̂. That is statistically optimal and a terrible interview. *Counter: content balancing via the Weighted Penalty Model over the M2 coverage plan, plus a per-concept cap (§6.6).*

**Trap 4 — Generating questions without verifying them.** LLM-generated items have wrong reference answers roughly 10–15% of the time, ambiguous phrasing more often, and near-duplicates constantly. Shipping unverified items into a *scored* context poisons the ground truth. *Counter: the five-gate verification pipeline (§6.3), with human review mandatory before an item is used for scoring.*

**Trap 5 — Selection latency on the hot path.** The student just finished answering; a 3-second gap before the next question is dead air that breaks the interview illusion. *Counter: pre-compute the top-3 candidate next-items during the student's answer, then pick one when the score lands. Budget: < 300 ms (§6.7).*

**Trap 6 — Forgetting that a question is asked *by a persona in a round*.** A great item selected for the wrong round type or phrased against the persona's register breaks immersion. *Counter: `modality` and `round_type` are hard filters, and the interviewer agent rephrases the stem into its own voice while preserving the semantic content (verified by an entailment check).*

**Trap 7 — Selecting the next item from a score that has not arrived.** M13 evaluates asynchronously at **p95 ≤ 15 s** and its FR-13.19 forbids blocking the conversational hot path. Any design that waits for the real score before choosing the next question either stalls the interview or, far worse, quietly re-selects at an ability estimate that never moved — a fixed-form test wearing a CAT's badge, passing every simulation because no simulation models the gap. *Counter: the branch key is M06's cheap `ProbeStrategist` verdict, not M13's score; M05 holds a **provisional** θ and reconciles with M04's posterior at session end (§6.7, §6.10).*

**Trap 8 — Letting a grounded item escape the student it was built from.** A question generated from a repository contains that student's design decisions, service names and project vocabulary. A selection pool filtered only by round type and freshness will serve it to somebody else, and both sessions will look completely normal. *Counter: `grounded_for_candidate` is a hard filter and a release gate, and grounded items are deleted with the candidate's data because they are the candidate's data (§6.12).*

### 3.2 The non-obvious hard parts

1. **Cold start is 100% of Phase 1.** Everything must work at n=0 items calibrated. Design the Elo path first and treat IRT as the upgrade.
2. **Item exposure and freshness fight each other.** Strict freshness on a small bank means the CAT runs out of good items mid-session. Monitor `bank_exhaustion_rate` per concept per difficulty band; it tells you exactly where to write more items.
3. **A question is not just a stem.** It carries a reference answer, key points, a rubric binding, a follow-up ladder, and a time budget. An item without those is not usable for scoring — the bank's real unit of work is the *package*.
4. **Difficulty ≠ difficulty.** An item can be hard because the concept is advanced, because the phrasing is opaque, or because it needs 20 minutes. Only the first is legitimate. Items with high `b` but low `a` (discrimination) are usually just badly worded — flag and rewrite them.
5. **Grounded items can't be pre-calibrated.** A question about *this student's* repo has been asked once, ever. It gets a prior from its concept + kind and never enters the IRT bank. That's fine — it's used for coverage and diagnosis, not for ability estimation.

---

## 4. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-5.1 | Store question packages (stem, reference answer, key points, rubric, ladder, time budget) | P0 |
| FR-5.2 | Support modalities: verbal, coding, design, mcq, numeric, case, gd_topic | P0 |
| FR-5.3 | Tag every item with concepts, role archetypes, company tags, provenance | P0 |
| FR-5.4 | Generate items grounded in repo / resume claim / JD requirement / company pattern | P0 |
| FR-5.5 | Five-gate verification before an item may be used in a scored context | P0 |
| FR-5.6 | Human review queue for all `generated` items entering scored use | P0 |
| FR-5.7 | Online Elo difficulty from the first response | P0 |
| FR-5.8 | IRT calibration (2PL / GRM / 3PL) once n ≥ 30 | P1 |
| FR-5.9 | CAT selection by maximum Fisher information with constraints | P0 |
| FR-5.10 | Content balancing against the M2 coverage plan | P0 |
| FR-5.11 | Per-candidate freshness: no repeat within 90 days, never within a session | P0 |
| FR-5.12 | Cohort exposure control (Sympson–Hetter), cap 0.25 | P1 |
| FR-5.13 | Exactly one stretch item per round, never last | P0 |
| FR-5.14 | Near-duplicate detection at ingest and at generation | P0 |
| FR-5.15 | Stopping rule: SE < 0.3 or budget exhausted | P0 |
| FR-5.16 | Selection latency p95 < 300 ms (pre-computed) | P0 |
| FR-5.17 | Nightly re-calibration + drift detection with review flags | P1 |
| FR-5.18 | Item quality stats: discrimination, misfire rate, realism votes, abandonment | P1 |
| FR-5.19 | Never select an item the student has flagged as broken | P1 |
| FR-5.20 | Hold the session-scoped **provisional θ**; never persist or display it | P0 |
| FR-5.21 | Select without M13's score, from M06's `ProvisionalOutcome` | P0 |
| FR-5.22 | A grounded item is selectable **only** by the candidate it was built from | P0 |
| FR-5.23 | Honour `forced_item_ids` / `bypass_freshness`, with disclosure to the student | P0 |
| FR-5.24 | On a broken-item flag, retract every observation derived from it via M04 | P0 |
| FR-5.25 | Required-coverage debt outranks the SE stopping rule | P0 |
| FR-5.26 | At most one primary + two secondary concepts per item; secondary is not θ-bearing | P0 |
| FR-5.27 | Run standalone on a committed ontology snapshot when M04 is absent | P0 |
| FR-5.28 | Report `exposure_bypass_rate`; alert when exposure control stops binding | P1 |

---

## 5. Data contracts

```python
class ConceptWeight(BaseModel):
    """At most ONE primary and TWO secondary per item (FR-5.26).

    M13 emits one observation per concept, each carrying the same score and
    the same evidence spans. Six concepts on an item turn one answer into six
    beliefs in M04 with `n_direct` incremented six times — one piece of
    evidence counted six times, in the direction that flatters the student.
    """
    concept_id: str
    weight: float                     # weights across an item sum to <= 1.0
    role: Literal["primary", "secondary"]
    # Only the primary concept may enter a likelihood. Secondary concepts are
    # COVERAGE-bearing: they update counts and evidence and never move theta,
    # which is M04 6.3's admissibility rule rather than a new one.

class GroundingRef(BaseModel):
    kind: Literal["repo_decision", "resume_claim", "jd_requirement", "company_pattern"]
    source_id: str                    # M3 decision id / M1 claim id / M2 requirement id
    source_module: Literal["M01", "M02", "M03", "M15"]
    excerpt: str | None               # never a verbatim quote of a private repo
    authored_confidence: float | None # M3's; below 0.6 the item is not built (EC-5.12)

class ProvisionalOutcome(BaseModel):
    """M06's ProbeStrategist verdict — the ONLY signal fast enough to branch on.

    M13's real evaluation lands up to 15 s later and never feeds selection;
    it corrects the durable record through M04 instead (6.10).
    """
    turn_id: UUID
    band: Literal["below", "at", "above"]   # relative to the item's difficulty
    confidence: float
    latency_ms: int

class KeyPoint(BaseModel):
    id: str
    statement: str            # NLI-checkable: "Mentions that the test set was held out"
    weight: float
    required: bool

class FollowUpTemplate(BaseModel):
    depth: Literal[0,1,2,3,4,5]
    template: str             # may contain {their_answer_span}
    triggers_when: str        # "answer covers kp_1 but not kp_3"

class IRTParams(BaseModel):
    model: Literal["2pl","grm","3pl"]
    a: float                  # discrimination
    b: float | list[float]    # difficulty (list = category thresholds for GRM)
    c: float | None           # guessing (3PL only)
    se_a: float; se_b: float
    n_responses: int
    estimated_at: datetime
    bank_version: str

class QualityStats(BaseModel):
    discrimination: float | None
    misfire_rate: float       # answers our evaluator scored with low confidence
    realism_votes_up: int
    realism_votes_down: int
    abandonment_rate: float   # students who quit on this item
    mean_time_s: float
    flagged_broken: int

class Question(BaseModel):
    id: UUID
    stem: str
    modality: Literal["verbal","coding","design","mcq","numeric","case","gd_topic"]
    #: ELIGIBILITY, not administration. Exactly one is chosen at selection
    #: time and recorded on SelectionResult, because M13 resolves the rubric
    #: from a SINGLE round_type and each rubric has exactly one
    #: concept-bearing dimension. The same item scored under two round types
    #: produces observations about different things from the same stem.
    round_types: list[str]
    concepts: list[ConceptWeight]     # <= 1 primary + 2 secondary (FR-5.26)
    role_archetypes: list[str]
    company_tags: list[str]
    provenance: Literal["curated","synthetic_verified","experience_corpus",
                        "textbook","generated","grounded"]
    grounded_on: GroundingRef | None
    #: THE PRIVACY FILTER (FR-5.22). None = general bank. Set = this item may
    #: only ever be served to this candidate, and dies with their data.
    grounded_for_candidate: UUID | None
    consent_id: UUID | None           # required whenever grounded_on is set
    #: A five-band ordinal an author can actually judge. The band -> logit
    #: table is versioned per round type (6.5), so re-calibrating the mapping
    #: later does not mean re-authoring the bank.
    difficulty_band: Literal["intro","easy","core","hard","stretch"]
    irt: IRTParams | None
    elo: float                        # always present, from first response
    reference_answer: str
    key_points: list[KeyPoint]
    #: M13 resolves the rubric from round_type at scoring time and never reads
    #: an item-level rubric id, so storing one is a field that can silently
    #: disagree with the rubric actually used. Rubrics are semver'd and a bump
    #: re-scores history (M13 6.8), which a bare UUID cannot express.
    rubric_round_type: str
    min_rubric_version: str | None    # only for an anchor added in a later revision
    follow_ups: list[FollowUpTemplate]
    time_budget_s: int
    hint_ladder: list[str]
    stem_simhash: int
    embedding: list[float]
    quality: QualityStats
    status: Literal["draft","in_review","active","retired","broken"]
    scored_use_approved: bool         # FR-5.6 gate
    #: False for every grounded and coverage-only item. M13 copies this into
    #: the observation's `item`, and M04 leaves theta alone when it is absent.
    #: An item can be perfectly good and still not be an instrument.
    theta_eligible: bool

class SelectionRequest(BaseModel):
    candidate_id: UUID
    session_id: UUID
    round_type: str
    #: M05's OWN in-memory estimate, seeded from M04 at session bootstrap and
    #: updated from ProvisionalOutcome. Never persisted, never displayed,
    #: discarded at session end (6.10). Naming it `theta` invited the reading
    #: that M04 supplies it per call — under which it never moves during a
    #: session, and the CAT silently becomes a fixed-form test.
    theta_provisional: dict[str, float]
    theta_seeded_from: str            # M04 snapshot id, or "cold"
    provisional_updates: int          # turns folded in; 0 == still the seed
    se: dict[str, float]
    coverage_debt: dict[str, float]   # requirement_id -> remaining budget
    required_requirement_ids: set[str]  # the subset that outranks SE (6.9)
    seen_item_ids: set[UUID]
    time_remaining_s: int
    stretch_used: bool
    modality_allowed: list[str]
    #: M04 owns the retest_queue row and sets bypass_freshness on it. Without
    #: somewhere to put it, the 90-day filter silently empties both M04's
    #: re-test promise and M13's promise to a disputing student.
    forced_item_ids: list[UUID] = []
    bypass_freshness: bool = False

class SelectionResult(BaseModel):
    question_id: UUID
    #: The ONE round type this administration is under. M13 scores against
    #: the rubric for exactly this value.
    round_type: str
    reason: Literal["max_info","coverage_debt","stretch","warmup","recovery",
                    "forced_retest","forced_review","fallback"]
    expected_information: float
    #: Expected score on the ITEM'S OWN scale, with its category count beside
    #: it. `predicted_p_correct` was Trap 2 in contract form: most of the bank
    #: is rubric-scored 0..4, and a probability of "correct" cannot be formed
    #: for a GRM item without the binary collapse this module exists to avoid.
    predicted_score: float
    n_categories: int                 # 2 for binary; 5 for a 0..4 rubric item
    theta_eligible: bool
    #: Set when freshness was relaxed or a re-test forced. Shown to the
    #: student verbatim (2.4) — a repeat they were warned about is a re-test;
    #: an unannounced one is the complaint this module is named for.
    disclosure: str | None
    alternatives: list[UUID]          # the pre-computed runners-up
```

---

## 6. The pipeline in minute detail

### 6.1 Bank composition targets

| Phase | Items | Composition |
|---|---|---|
| End Phase 1 | 1,200 | 500 DSA · 300 CS core · 150 HR/behavioural · 150 aptitude · 100 ML |
| End Phase 2 | 2,800 | + system design 200 · company-tagged 400 · OA-style 400 |
| End of year | 5,000+ | + GD topics 150 · case 100 · experience-corpus-derived 600 |

**Where they come from:**
- **Curated (30%)** — written by the team + faculty. Slow, highest quality, defines the style guide.
- **Synthetic-then-verified (45%)** — generated from a concept + difficulty spec, then five-gated.
- **Experience corpus (15%)** — real questions students report from real drives (M15). Highest realism, needs cleaning.
- **Grounded (10%, ephemeral)** — per-student from repo/resume/JD. Not part of the calibrated bank.

### 6.2 Generation

Grounding priority (this ordering *is* the personalisation):
```
repo decision (M3)  >  resume claim (M1)  >  JD requirement (M2)
                    >  company pattern (M15)  >  concept-only synthetic
```

Generation prompt gets: concept + level, target difficulty band, an exemplar item in the house style, the round type and persona register, forbidden-topic list, and (for grounded items) the source artifact. Output is the **full package**, not just a stem — a generator that returns a question without key points and a reference answer has done 20% of the job.

### 6.3 The five verification gates

Every generated item passes all five or it does not enter the bank:

| Gate | Check | Method |
|---|---|---|
| **G1 Schema** | All package fields present and well-formed | Pydantic |
| **G2 Answerability** | A second model, given only the stem, produces an answer that entails ≥70% of the key points | Independent model call + NLI |
| **G3 Reference correctness** | The reference answer is factually right | Third model verifies + retrieval fact-check; disagreement → human queue |
| **G4 Uniqueness** | Not a near-duplicate of an existing item | SimHash blocking (Hamming ≤ 6) → cross-encoder ≥ 0.92 → reject |
| **G5 Style & safety** | House style, no discriminatory content, no PII, difficulty band plausible | Rule list + cheap-tier classifier |

Then: `status=in_review`. **`scored_use_approved` requires a human click.** In Phase 1 that's the team (10 items take ~15 minutes); by Phase 3 it's a spot-check of 10% plus auto-approval for items whose G2/G3 confidence is high and whose concept has a mature calibration.

### 6.4 The three IRT models, one interface

```python
class ItemModel(Protocol):
    def p_correct(self, theta: float) -> float: ...
    def information(self, theta: float) -> float: ...
    def log_likelihood(self, theta: float, response: float) -> float: ...

# 2PL  — auto-gradable binary (coding pass/fail, numeric)
#   P = 1/(1+exp(-a(θ-b)))            I = a²P(1-P)
# GRM  — rubric-scored ordinal 0..4 (Samejima)
#   P(X≥k) = 1/(1+exp(-a(θ-b_k)))     P(X=k) = P(X≥k) - P(X≥k+1)
#   I = a² Σ_k [(P'_k)² / P_k]
# 3PL  — MCQ aptitude with guessing
#   P = c + (1-c)/(1+exp(-a(θ-b)))    I = a²(1-c)... (standard form)
```

**GRM is the one that matters** — most of our items are rubric-scored, and this is the detail that makes Paper 2 methodologically sound rather than "we applied IRT to LLM scores".

### 6.5 Calibration lifecycle

```
n = 0        → difficulty_band → logit via the versioned band table, SE = 1.2
n = 1..29    → Elo location only:  R_item ← R_item + K(expected - actual)
                 K = 32 → 16 after n=10;  b̄ = (R_item - 1500) / 173.7
n ≥ 30       → MML estimation nightly (`girth` / `py-irt`), EM over the response matrix
n ≥ 100      → parameters considered stable; drift monitoring begins
```

**The cold start has to produce a *usable* parameter set, not a placeholder.**
§3.2 says cold start is 100% of Phase 1, and most of the bank is rubric-scored
— so if the `n < 30` path cannot yield GRM parameters, `information(θ)` cannot
be evaluated, §6.6's ranking loses its information term, and selection falls
through to coverage and penalties **while every function still returns a
number**. The CAT would not work at all in the phase that is entirely cold
start, and nothing would say so. Two rules close that:

**Elo estimates a location, never a threshold vector.** Elo takes a binary
outcome; a 0–4 rubric score can only be fed to it as `score / (K-1)`, which is
the Trap 2 collapse. That collapse is acceptable for a provisional *location*
`b̄` and for nothing else — it never touches ability estimation, and `b̄` is
discarded the moment MML runs.

**Thresholds come from a spacing prior until MML replaces them.**

```
b_k = b̄ + δ_k       δ from a per-round_type table, e.g. (-1.2, -0.4, +0.4, +1.2)
a   = a_prior        per modality, held fixed until n ≥ 30
```

`IRTParams.params_source` records which of `prior | elo | mml` produced the
numbers in hand. M13's shipped `ItemParams` already carries that field and
defaults it to `"prior"`, so the honesty is already expected downstream — this
is the module that has to supply it.

**The band → logit table is a versioned artifact.** Authors judge
`intro | easy | core | hard | stretch`, which is a judgement a person can
actually make; nobody reliably authors "0.8 logits". Re-calibrating the
mapping is then a table bump, not a re-authoring of the bank.

**Drift detection:** compare the current estimate to the previous; if `|Δb| > 2·se_b` the item is flagged `drifted`. Causes: leaked answer (b drops), rubric change, or seasonal effect. Flagged items go to review, not to auto-retirement.

**Bad-item detection:** `a < 0.4` means the item doesn't discriminate — usually ambiguous phrasing. Auto-flag for rewrite. This single check will improve the bank more than any amount of generation.

### 6.6 Selection: constrained maximum information

```python
def select(req: SelectionRequest) -> SelectionResult:
    # 0. Forced items first: M04 owns the retest queue and M13 promised a
    #    disputing student a fresh look. Both arrive here or nowhere.
    if req.forced_item_ids:
        return forced(req)                     # reason="forced_retest", with disclosure

    # 1. Hard filters
    pool = bank.filter(
        round_types__contains=req.round_type,
        modality__in=req.modality_allowed,
        status="active",
        scored_use_approved=True,
        time_budget_s__lte=req.time_remaining_s,
        id__not_in=req.seen_item_ids,
        flagged_broken=False,
        # FR-5.22. A grounded item carries the student's own repo vocabulary in
        # its stem; without this line it is selectable by the whole cohort and
        # both sessions look entirely normal. Gated by AC-5.11.
        grounded_for_candidate__in=(None, req.candidate_id),
    )
    if not req.bypass_freshness:
        pool = pool.exclude(id__in=recent_90d(req.candidate_id))
    if not pool: return fallback(req)          # §6.8

    # 2. Warm-up rule: first item of a round sits at θ̂ - 0.4 (a gentle open)
    #    θ̂ here is req.theta_provisional — M05's own in-session estimate (§6.10),
    #    NOT a per-call read of M04's posterior, which does not move mid-session.
    target = theta_for(req) - (0.4 if is_first_of_round else 0.0)

    # 3. Stretch rule: exactly one per round, at ~70% through, never last
    if should_stretch(req):
        target = theta_for(req) + 1.2

    # 4. Score each candidate
    for q in pool:
        info      = q.model.information(target)
        coverage  = coverage_gain(q, req.coverage_debt)      # WPM penalty term
        exposure  = sympson_hetter_gate(q)                   # stochastic accept/reject
        concept_pen = 0.5 if concept_count_in_round(q) >= 2 else 1.0
        recency_pen = 0.7 if q.concepts overlap last_item else 1.0
        q.score = info * (1 + 0.8*coverage) * concept_pen * recency_pen * exposure

    # 5. Best item, with the runners-up carried for the pre-compute path
    ranked = top(pool, k=3)
    return SelectionResult(
        question_id=ranked[0].id,
        round_type=req.round_type,          # the ONE administered (§5)
        alternatives=[q.id for q in ranked[1:]],
        ...,
    )
```

**Weighted Penalty Model for content balance:** each unmet coverage requirement contributes a penalty to items that don't address it, scaled by remaining debt / remaining questions. As the round nears its end, coverage dominates information — which is exactly the behaviour a human interviewer shows ("I still need to check DBMS before we finish").

**Sympson–Hetter:** each item carries an exposure parameter `k_i`; when selected, it is *administered* with probability `k_i`, otherwise the next candidate is tried. `k_i` is updated nightly toward a target max exposure of 0.25.

### 6.7 Latency: pre-computation, and the score that has not arrived

The moment the student *starts* answering, we run selection against three
hypothetical outcomes — below / at / above the item's difficulty — and cache
all three top-3 lists in `SessionState`. Picking is then a dictionary lookup,
**< 20 ms**.

**What we branch on is not M13's score.** M13 evaluates asynchronously at
`p95 ≤ 15 s` (AC-13.13) and FR-13.19 forbids blocking the conversation on it.
By the time a real score exists, the next question has been asked and
answered. The branch key is M06's `ProvisionalOutcome` — the cheap ~1.2 s
`ProbeStrategist` verdict M06 §3.1 calls *"the single most important
architectural decision in the module"*.

```
student starts answering  →  precompute 3 branches            (off the hot path)
student stops             →  M06 ProbeStrategist   ~1.2 s
                          →  branch lookup         < 20 ms    →  next question
         ... meanwhile    →  M13 ensemble          ≤ 15 s     →  M04 (durable)
```

Three miss-paths, in order:

1. **The verdict is late or absent** (EC-5.15) — select at *unchanged* θ and
   mark the turn `theta_unadjusted`. Better a question at the last known
   ability than a stalled interview or a guess dressed as measurement.
2. **The verdict is outside all three branches** — live selection, 300 ms
   budget.
3. **That fails too** — the coverage-debt fallback, then §6.8.

**M13's score never re-enters selection.** When it lands it corrects the
*durable* record through M04, and decisions already made stay made. Retro-
fitting them would make a session's question sequence unreproducible from its
own trace, which the platform's replayability rule forbids.

### 6.8 Fallback chain when the pool is empty
```
1. Relax freshness from 90 → 45 days (and tell the student: "you've seen this before —
   let's see if it's stuck")
2. Relax the difficulty band ±0.5
3. Generate a grounded item on the fly (repo/resume) — always available, never repeats
4. Generate a synthetic item with G1/G4/G5 only, marked coverage-only (not used for θ)
5. End the round early with an honest note in the report:
   "I ran out of fresh questions on this topic — that's on us, not you."
```
Point 5 is real and it must be implemented. Silently repeating an item is worse than admitting the bank is thin.

### 6.9 Stopping rule — and what outranks it
```
stop_domain when (SE(θ̂) < 0.30  AND  required_coverage_debt == 0)
           or   items_asked ≥ max_for_round
           or   time_remaining < min_item_time
           or   three consecutive items with information < 0.15 (we've learned all we can)
```

**Required coverage outranks SE, and the conjunction is why.** On a strong
candidate SE collapses in three or four items; stopping there ends the round
with JD requirements unprobed while the report still says it completed. M02's
whole contribution is coverage as a *guarantee* rather than an intention, and
M13 already emits the `scored` transition that makes it auditable — an early
stop turns that back into an intention silently.

So: with required debt outstanding, continue with `reason="coverage_debt"`
until the time budget binds. If it binds first, end and **say so** in the
report, in §6.8 step 5's voice — the shortfall is ours to own, not the
student's to discover.

### 6.10 Who owns θ, and for how long

The most consequential contract this module has, and the one most easily got
wrong by reading a field name.

| | M04 | **M05 (here)** |
|---|---|---|
| Owns | the **durable posterior** per `(candidate, concept)` | **item parameters** `a`, `b`, `c` · the **session provisional θ** |
| Lifetime | forever, versioned | one session |
| Persisted | yes — the only thing stored | **never** |
| Displayed | yes | **never** |
| Changed by | `record()`, from M13's observations | `ProvisionalOutcome`, in memory |

```
session start   M04 posterior ──seed──▶ theta_provisional   (theta_seeded_from)
each turn       ProvisionalOutcome ───▶ theta_provisional   (provisional_updates += 1)
                                          └─ selection only, never written
session end     theta_provisional ──discarded
                M04 recomputes the posterior from observations of record
```

**At session end the posterior wins silently.** M04 recomputes from the
observations of record; if it disagrees with what M05 was steering by, M04 is
right and no one is told. A divergence **> 0.5 logits is logged as a
calibration signal** — it means the ProbeStrategist and the real evaluator
disagree systematically, which is worth knowing and is invisible unless
someone measures it.

**Why the provisional estimate must not be written down.** Two persisted
ability numbers is two answers to "how good is this student", and the cheap
one is the one that would leak into a report. It exists solely so the next
question can be chosen before the real score exists.

### 6.11 Running alone

Every module on this platform clones and runs alone; this one is no different,
and it has a specific reason to be careful. M05 needs **M04's ontology** —
without a concept list there is nothing to tag an item with and nothing to
select against — and M04's ontology ships `reviewed: false` until a faculty
walk lands. Waiting for that would idle M05 for weeks.

| Missing | M05 does | What is lost |
|---|---|---|
| **M04** | loads a committed 120-concept **ontology snapshot**; `ontology_version` stamped on every item | no live mastery; θ starts cold rather than seeded |
| **M02** | selects on information and freshness only | no coverage balancing; the WPM term is inert and `/v1/deps` says so |
| **M01/M03** | concept-only synthetic generation | no grounded items — the personalisation, not the mechanism |
| **M06** | `/v1/questions/select` is callable directly with an explicit θ | no provisional updates; each call stands alone |
| **M13** | items are served and never scored | no responses, therefore no Elo, therefore no calibration |

`GET /v1/deps` names each of these and what it costs, in the sentence a human
can act on. Degrading the *scope* of what M05 can say is fine; degrading the
*quality* silently is not.

### 6.12 Grounded items are the student's data

A grounded item is generated from a repository, a resume or a JD. Its stem
carries that student's design decisions and vocabulary. It is personal data
that happens to be shaped like a question, and it gets treated as such.

- **`grounded_for_candidate` is a hard filter, and a gate.** AC-5.11 asserts
  zero grounded items reach any candidate but their subject. A filter without
  a gate is a filter someone removes during a refactor for being redundant.
- **`consent_id` is required** whenever `grounded_on` is set — no default, the
  same rule M13 enforces on every observation it emits.
- **Deleted with the candidate.** Not archived, not anonymised and kept.
- **Never verbatim from a private repository.** `GroundingRef.excerpt` holds a
  paraphrase of a decision, never copied source.
- **`authored_confidence ≥ 0.6`**, from M03. EC-5.12 already assumes this;
  stating it makes it implementable. Interrogating a student about code they
  did not write is a worse failure than asking a generic question.
- **Never θ-eligible.** `theta_eligible = False`, always: an item asked once
  in history has no calibration and cannot be an instrument (§3.2.5).

**The gates a grounded item runs.** FR-5.5/FR-5.6 require five gates and a
human click before scored use, which cannot hold for an item generated inline
mid-session (§6.8 step 3). The split, stated so both are true:

| | G1 schema | G2 answerability | G3 reference | G4 uniqueness | G5 style/safety | human |
|---|---|---|---|---|---|---|
| Bank item | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Grounded, inline** | ✓ | — | — | ✓ | ✓ | — |

G2 and G3 need extra model calls that the hot path cannot afford; G1, G4 and
G5 are local and cheap. The compensation for skipping them is
`theta_eligible = False` — the item can inform coverage and diagnosis, and it
cannot move a number that follows the student.

---

## 7. API surface

```
GET  /v1/questions/{id}
POST /v1/questions/select               SelectionRequest → SelectionResult   (internal)
POST /v1/questions/precompute           warm the two-branch cache            (internal)
POST /v1/questions/generate             {concept, difficulty, grounding} → draft package
POST /v1/questions/{id}/verify          run gates G1–G5
POST /v1/questions/{id}/approve         human approval for scored use
GET  /v1/questions/review-queue         ?status=in_review
POST /v1/questions/{id}/flag            {reason} — student-facing "this question is broken"
GET  /v1/questions/{id}/stats
POST /v1/bank/recalibrate               nightly job trigger
GET  /v1/bank/health                    coverage × difficulty heatmap, exhaustion rates
GET  /v1/deps                           upstreams, and what is switched off without them
POST /v1/sessions/{id}/theta/seed       seed the provisional θ from M04      (internal)
POST /v1/sessions/{id}/theta/observe    fold in a ProvisionalOutcome         (internal)
POST /v1/sessions/{id}/close            discard provisional θ, log divergence vs M04
```

There is deliberately **no** `GET /v1/sessions/{id}/theta`. The provisional
estimate is not displayable and not durable (§6.10); an endpoint returning it
is the shortest path to it appearing in a report.

---

## 8. UI specification

### 8.1 Student-facing (minimal, three touchpoints)
- `DifficultyPip` — three dots with a relative label. Never a number.
- `StretchNotice` — the one-sentence explainer after a stretch item.
- `FlagQuestionButton` — always present, one tap, free-text optional: *"Something wrong with this question?"* This is our cheapest quality signal and it makes the student a collaborator rather than a subject.

### 8.2 Internal: the bank console (build it — you will live in it)
```
  Bank health                                    1,247 active · 89 in review

  Coverage × difficulty                easy   med   hard   ← exhaustion risk
  DSA / arrays                          42     38     19
  DSA / dynamic programming             12      9      4   ⚠ thin
  DBMS / normalisation                   8      6      2   ⚠ thin
  CS core / OS scheduling               15     11      7

  ⚠ 6 items flagged drifted    ⚠ 14 items a < 0.4 (rewrite)
  ⚠ 3 concepts with exhaustion rate > 15% this week
```
The exhaustion-rate column tells you exactly what to write next week. Without it you will write more array questions because they're easy to write.

---

## 9. Edge cases

| ID | Case | Behaviour |
|---|---|---|
| EC-5.1 | Bank empty for a concept | Fallback chain §6.8; grounded generation always works |
| EC-5.2 | Student's θ is extreme (±3) | Clamp selection target; note "you're at the edge of what this bank measures" |
| EC-5.3 | Student answers everything correctly | SE shrinks fast; stop early; report says "we didn't find your ceiling — try Final Boss" |
| EC-5.4 | Student answers nothing correctly | Difficulty floors, then the round pivots to a diagnostic/teaching mode rather than continuing to fail them |
| EC-5.5 | M13 has no rubric for the item's `rubric_round_type` | Item excluded from scored selection, alert raised. Rubrics load from YAML at M13 boot and a bad one fails the boot, so "deleted" is not a state that exists — an unknown round type is, and is detectable at `GET /v1/rubrics` |
| EC-5.6 | Two items are near-duplicates in the bank | Nightly dedup pass merges stats, retires one |
| EC-5.7 | Generated item fails G3 (wrong reference answer) | Never enters bank; logged; if a concept fails G3 repeatedly, that concept's generation prompt is wrong |
| EC-5.8 | Time remaining < shortest item | Round ends gracefully with a closing question, never mid-air |
| EC-5.9 | Student flags an item mid-answer | Recorded; flag count incremented; excluded from the provisional θ **and** M04's retraction path called for every observation derived from it. M13's emit is async and idempotent, so by flag time the durable belief usually already exists — dropping it from an in-memory estimate that is discarded anyway would leave the broken question still moving their mastery. M04 §6.x names this edge case as a retraction source |
| EC-5.10 | Exposure control blocks every candidate | Bypass exposure (measurement beats leak-prevention in a single session), log, and **increment `exposure_bypass_rate`**. On a thin bank this branch is the steady state rather than the exception, and unmeasured it lets Sympson–Hetter become a no-op while AC-5.6 is still reported as met. Alert above 5% per concept per week — the fix is writing items there |
| EC-5.11 | Concept has items but all seen in 90 d | Freshness relaxed with explicit disclosure |
| EC-5.12 | Grounded item on a repo the student didn't write (low `authored_confidence`) | Excluded by M3; never selected |
| EC-5.13 | Company-tagged item requested but no company set | Falls back to archetype tags |
| EC-5.14 | Calibration job fails | Previous parameters retained; alert; no student impact |
| EC-5.15 | No `ProvisionalOutcome` inside the budget | Select at unchanged θ, mark the turn `theta_unadjusted`, continue. A stalled interview and a guessed ability are both worse than one question chosen at the last known level |
| EC-5.16 | M13's score contradicts the provisional verdict | Nothing is re-selected — decisions already made stay made, or the session is unreproducible from its trace. M04's posterior corrects the durable record; divergence > 0.5 logits is logged (§6.10) |
| EC-5.17 | A grounded item is requested for a candidate who is not its subject | Excluded by the hard filter, logged as a **P0 defect** — reaching this branch means the filter was bypassed somewhere, and AC-5.11 exists to fail the release rather than the request |
| EC-5.18 | Item declares more than 1 primary or 2 secondary concepts | Rejected at ingest by `ontology_lint`; one answer must not become six beliefs in M04 (FR-5.26) |
| EC-5.19 | Candidate deletes their account | Every item with `grounded_for_candidate = them` is deleted, not anonymised (§6.12) |

---

## 10. Failure modes & fallbacks

| Failure | Fallback | User sees |
|---|---|---|
| Selection > 300 ms | Serve pre-computed alternative; if none, serve highest-coverage-debt item | Nothing |
| Generation service down | Bank-only selection | Nothing, unless bank is thin |
| IRT parameters missing | Elo-derived `b` | Nothing |
| Elo missing (brand-new item) | `difficulty_band` → logit table, thresholds from the spacing prior | Nothing |
| Entire selection fails | Fixed fallback playlist per round type (a hand-picked, always-valid list of 10 items per round) | Nothing — this is the last line and it must exist |

**Build the fixed fallback playlist on day one.** It is 30 minutes of work and it guarantees the interview never stalls.

---

## 11. Performance & cost budget

| Operation | p95 | Cost |
|---|---|---|
| Selection (pre-computed hit) | 20 ms | — |
| Selection (live) | 280 ms | — |
| Pre-compute (2 branches × top-3) | 400 ms, off the hot path | — |
| Grounded generation (inline) | 4 s | ₹0.55 |
| Batch generation + 5 gates (per item) | ~25 s, offline | ₹2.10 |
| Nightly recalibration (whole bank) | ~8 min | — |

Bank building is a fixed cost: 3,000 verified items ≈ ₹6,300 in generation + gates, spread over the year. Cheap relative to its value; do not cut corners on the gates to save it.

---

## 12. Test plan

**Unit** — 2PL/GRM/3PL information functions against reference values · Elo→logit conversion · SimHash dedup on 200 near-duplicate pairs · WPM coverage penalty monotonicity · stretch placement (never last, exactly one).

**Simulation [the key test]** — 500 synthetic students with known true θ. Run it **twice**: once with responses generated by the same IRT model the CAT assumes, and once under the **mis-specification grid** below. The first run is a sanity check; only the second is evidence.

> **Why the grid decides whether AC-5.4 means anything.** When both arms are
> driven by the model the selector assumes, the CAT beats fixed-form close to
> by construction, and the gate measures our arithmetic rather than the
> method. M04 learned this and put its grid at milestone M3, *before* its
> estimators — "the harness that catches a bad decay curve in an afternoon
> instead of in a pilot". Same here.
>
> **The grid:** discrimination mis-set by ±0.4 · correlated residuals within a
> concept (a student who is uniformly weak on recursion, not independently so
> per item) · guessing present on items modelled without it · `b` drifting
> mid-cohort (a leaked item) · 20% of items with `a < 0.4` still active ·
> ordinal responses that are not GRM-shaped (a rubric with an unusable middle
> category).

In both runs:
- assert CAT reaches SE ≤ 0.3 in ≤ 60% of the items a fixed-form test needs (this is **AC-5.4 and Paper 2's headline**),
- assert θ̂ recovery r ≥ 0.90 vs truth,
- assert no item exceeds exposure 0.25 across the simulated cohort,
- assert content-balance constraints hold in 100% of runs.

**Integration** — a real session end-to-end: coverage plan honoured, no repeats, difficulty trajectory sane, stopping rule fires.

**Cold start [the Phase-1 test]** — with **zero** calibrated items, assert selection still ranks by information: the band→logit table and the threshold spacing prior must yield a usable GRM parameter set at `n = 0`, and `params_source` must read `prior`. A cold-start path that silently drops the information term and ranks on penalties alone is the failure §6.5 exists to prevent, and it passes every other test in this plan.

**Privacy [gate]** — build grounded items for candidate A, then run 1,000 selections for candidate B across every round type and an emptied bank: **zero** of A's items may appear. Repeat with the freshness bypass set, which is the path most likely to skip a filter.

**Contracts** — a `SelectionResult` round-trips into M13's `QuestionPackage` with `round_type` singular and `item` populated only when `theta_eligible`; a forced re-test survives the freshness filter and carries its disclosure string; a flagged item produces an M04 retraction call.

**Quality** — every item in the bank must have a resolvable rubric for its `rubric_round_type`, ≥2 key points, and a non-empty reference answer. CI check over the whole bank.

**Adversarial** — a student who deliberately answers randomly (θ estimate must not diverge) · a student who answers everything perfectly (must terminate, not loop) · an item with `a=0` (must be excluded) · 100 simultaneous selections for the same rare concept (exposure control under contention).

**Manual QA** (10 min): run a full DSA round; write down the perceived difficulty of each question; confirm the trajectory matches the intended flow-zone shape; confirm the stretch item is announced; flag a question and confirm it's excluded.

---

## 13. Metrics & acceptance gates

Gates are **phased**. A gate that cannot be met in the phase it is written for
is not a standard, it is a note — and the ones needing calibrated items cannot
pass while §3.2's cold start is still true.

| ID | Metric | Target | Phase |
|---|---|---|---|
| AC-5.1 **[GATE]** | No item repeats within a session | 100% | 1 |
| AC-5.2 **[GATE]** | No unapproved `generated` item in a scored context | 100% | 1 |
| AC-5.3 **[GATE]** | Selection p95 | ≤ 300 ms | 1 |
| AC-5.11 **[GATE]** | Grounded items reaching a candidate other than their subject | **0** | 1 |
| AC-5.12 **[GATE]** | Provisional θ persisted or rendered anywhere | **0** | 1 |
| AC-5.13 **[GATE]** | Forced re-tests suppressed by the freshness filter | **0** | 1 |
| AC-5.14 **[GATE]** | Selection ranks on information at n=0 calibrated items | 100% | 1 |
| AC-5.15 **[GATE]** | Items exceeding 1 primary + 2 secondary concepts | **0** | 1 |
| AC-5.16 | Rounds ended by SE with required coverage debt open | **0** | 1 |
| AC-5.4 **[GATE]** | Simulated CAT efficiency vs fixed-form at equal SEM, **under mis-specification** | ≤ 60% of items | 2 |
| AC-5.5 | θ̂ recovery in simulation, under mis-specification | r ≥ 0.90 | 2 |
| AC-5.6 | Cohort exposure max | ≤ 0.25 | 2 |
| AC-5.17 | `exposure_bypass_rate` per concept per week | < 5% | 2 |
| AC-5.7 | Items with `a < 0.4` remaining active | < 5% of bank | 2 |
| AC-5.8 | Student-flagged-broken rate | < 2% of served items | 1 |
| AC-5.9 | Bank exhaustion rate per concept | < 10% weekly | 2 |
| AC-5.10 | G3 failure rate on generated items | < 15%, trending down | 1 |
| AC-5.18 | Provisional-vs-posterior divergence at session end | < 0.5 logits, monitored | 2 |

---

## 14. Build order

**~14 days, in milestones rather than days.** The previous order put the
simulation harness on day 14. The simulator is not a test of the finished
selector — it is the instrument you build the estimators *with*, it costs a
day, and it saves a week of debugging something that looks plausible and is
wrong. M04 puts its grid at M3 for exactly this reason. The old order also
contained no item authoring at all, while M04's granularity linter needs
3+ items across 120 concepts and Phase 1 targets 1,200.

| Milestone | Days | Demoable outcome |
|---|---|---|
| **M0 — Contracts & the seam** | 1–2 | Package schema; **ontology snapshot fixture**; `/health` + `/v1/deps`; `module.json`; **the θ-ownership contract (§6.10) agreed with M04 and M06 in writing**. Item authoring starts today and never stops. |
| **M1 — Bank & fallback** | 2–3 | Tables, embeddings, SimHash; authoring tool; 200 curated items; the **fixed fallback playlist** — 30 minutes, and it guarantees the interview never stalls |
| **M2 — Simulation first** | 3–4 | 500 synthetic students, known θ, and the **mis-specification grid** — before any estimator exists |
| **M3 — Item models** | 4–6 | 2PL/GRM/3PL behind one interface; band→logit table; Elo location + threshold spacing prior; `params_source` honest. **AC-5.14 green** |
| **M4 — Selection v1** | 6–8 | Hard filters incl. **candidate scoping** and **freshness bypass**; θ-target; stretch; WPM coverage; the stopping precedence. **AC-5.11 and AC-5.13 green** |
| **M5 — The session seam** | 8–9 | Provisional θ owned here; three-branch precompute on M06's `ProbeStrategist`; end-of-session reconciliation with M04. **AC-5.12 green** |
| **M6 — Generation & gates** | 9–11 | Generation prompt, full-package output, G1–G5, review queue, the inline grounded path with the G1/G4/G5 split |
| **M7 — Calibration** | 11–13 | Nightly MML, drift detection, bad-item flags, exposure updates |
| **M8 — CAT & console** | 13–14 | Sympson–Hetter, stretch rule, pre-computation, **bank-health console** |
| *(ongoing)* | | Item authoring · exposure monitoring · AC-5.4 under mis-specification once items calibrate |

**Start item authoring on day one.** It has zero engineering dependencies and
it is the long pole: M15's spec gave the same advice about source curation and
was right — *hand it to whoever has spare afternoons in week one, and it will
be finished by the time the code that needs it exists.*

---

## 15. Open decisions

1. **Who approves items for scored use, at scale?** Phase 1: the team. Phase 3+: proposal is 10% human spot-check + auto-approve on high G2/G3 confidence in mature concepts. Needs a decision by Month 5, because it gates bank growth.
2. **Do we show the student their θ?** No (M4 §15.2). But *do* we show "questions needed" in the report? Recommendation: yes — it is our differentiator stated as their benefit.
3. **Company-tagged items: how do we avoid reproducing copyrighted question text?** Policy: store *topic + structure + our own phrasing*, never a verbatim copyrighted stem. Experience-corpus items are students' own recollections, which is different, but still get rewritten before entering the bank.
4. **Stretch item in Final Boss mode?** Everything is a stretch there. Proposal: disable the special stretch and its announcement in Final Boss; the debrief covers it instead.
5. **When do we adopt DKT?** Only if it beats BKT+IRT on held-out AUC by a meaningful margin at ≥20k interactions. Decide in Month 10, report either way.
6. **How is the band→logit table first populated?** Proposal: one calibration
   sitting where three authors independently band 60 items, converted by
   rank-ordering against the few items that do have responses. Needs doing
   before M3, because every cold-start difficulty depends on it.
7. **Does the ProbeStrategist verdict come from M06 or live here?** M06 owns it
   today (§3.1 Trap 2) and that is the right home — it already has the turn
   context. M05 must not grow a second one. Confirm with E2 by M0, because
   §6.7 is unbuildable until it is settled.
8. **How is information compared ACROSS concepts?** Found while building M4:
   §6.6 ranks every candidate by `information(θ)`, but θ is per-concept, so an
   item on a concept never measured (θ = 0, SE = 1.0) sits at its information
   peak while a well-measured concept's items sit off-peak. Raw comparison
   therefore prefers unexplored concepts — which is *defensible* (you learn most
   where you know least) but is nowhere chosen, and it means raising θ on one
   concept does not get a harder item on that concept, it gets a different
   concept. Options: (a) leave it and let the coverage term carry breadth,
   (b) weight information by that concept's SE, making the exploration explicit,
   (c) select the concept first, then the item within it. Recommendation: (b),
   because it keeps one ranking and makes the intent legible. **Decide before
   M05 M4 ships**, since it changes every selection.
9. **What happens to an item whose concept is removed from the ontology?**
   Proposal: `status=retired`, responses retained, θ contributions stand. A
   concept disappearing is an ontology decision and must not silently rewrite
   what a student was measured on.
