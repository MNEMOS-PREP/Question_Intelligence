# M05 — Question Intelligence · deep review

> Reviewed against `M05_Question_Intelligence.md` as written, and against the
> **shipped code** of the two modules M05 has to work with: M04 Skill Graph &
> Memory (137 tests, M0–M5 done) and M13 Evaluation Engine (135 tests, M0–M10
> done). Where the spec and a shipped module disagree, the shipped module is
> the fact.
>
> Companion to `M04_REVIEW.md` and `M13_REVIEW.md`, same standard: every
> finding names a failure, not a preference.

---

## Verdict

**Strong on the parts nobody else will write. Quietly broken on the parts three
modules share.**

What is genuinely good and should not be touched: the six traps are the right
six; GRM-not-2PL is called correctly and is the difference between Paper 2 and a
reviewer's first objection; the fallback chain ending in *"I ran out of fresh
questions on this topic — that's on us, not you"* is the right instinct; the
bank-health console with an exhaustion column is the most useful internal screen
specified anywhere in this project; and §2.2's flow zone, including *never end on
the ceiling*, is a product rule most adaptive-testing systems get wrong.

What is broken follows one pattern, worth naming before the list: **M04 and M06
were both amended to resolve a contract M05 is the third party to, and M05 was
never updated.**

M04's open decision 5 now reads *"Who owns the in-session ability estimate? **M5**
(provisional, in-memory, discarded at session end)."* M06's Trap 2 now reads
*"`ProbeStrategist` (cheap, ~1.2 s) decides the next move on the hot path; the
full evaluation ensemble runs async"* — and calls it *"the single most important
architectural decision in the module."*

M05 mentions neither. Its `SelectionRequest` still takes `theta` as a plain input
from nowhere, and §6.7 still waits for a score that M13 ships at **p95 ≤ 15 s,
async**.

Below: 5 contract breaks against code that exists, 10 internal contradictions,
3 missing sections the platform convention requires, and a build order in the
wrong sequence.

---

# Part 1 — Contract breaks against modules that already exist

### 1.1 M05 owns the provisional θ and does not know it

`SelectionRequest.theta: dict[str, float]`, with no further comment. Read
plainly, that is M04's durable posterior handed in at selection time. M04's spec
forbids exactly that reading:

> **Who owns the ability estimate.** M04 owns the *durable posterior* per
> `(candidate, concept)` […] M5 owns *item parameters* (`a`, `b`, `c`) and a
> *session-scoped provisional θ* held in `SessionState` — seeded from M04 at
> session bootstrap, updated in memory from the provisional score for item
> selection only, **never persisted, never displayed, discarded at session end.**

So `theta` is not an input M04 supplies per selection. It is **M05's own
in-memory state**, seeded once at bootstrap and updated by M05 after each turn.
The spec has no field for the seed, no update rule, no prohibition on persisting
it, and no reconciliation at session end — which M04 also specifies and M05 must
implement half of:

> At session end M04 recomputes the posterior from the observations of record;
> if it disagrees with the provisional estimate the posterior wins silently, and
> a divergence > 0.5 logits is logged as a calibration signal.

**Why this matters beyond tidiness.** An implementer reading `theta` as M04's
posterior will call `GET /v1/skill-graph/theta` before each selection. During a
session that value never moves, because M04's posterior only changes when M13's
async observation lands — after the round. The CAT quietly degrades into a
fixed-form test pinned at the student's *entry* ability, while reporting itself
as adaptive. Nothing errors. AC-5.4 still passes in simulation, because the
simulation never models the async gap.

**Fix.** Rename to `theta_provisional`; add `theta_seeded_from` and
`provisional_updates`; write a new §6.10, *Who owns θ, and for how long*.

### 1.2 §6.7's pre-computation waits for a score that has not arrived

> The moment the student *starts* answering, we run selection against the two
> hypothetical outcomes (they do well / they do badly) […] **When the score
> arrives**, picking is a dictionary lookup — < 20 ms.

M13 ships `AC-13.13 — Evaluation p95 (async) ≤ 15 s` and `FR-13.19 — Never block
the conversational hot path`. The score does not arrive. It arrives up to fifteen
seconds later, by which time the next question has been asked and answered.

The two-branch cache is the right idea aimed at the wrong signal. The branch key
cannot be M13's score. It has to be M06's `ProbeStrategist` verdict — the cheap
~1.2 s call M06 built for precisely this hot path.

The spec's only stated miss-path is *"if the score is a surprise (outside both
branches)"*. The modal case is not a surprising score. It is **no score at all**,
and there is no edge case for it.

**Fix.** §6.7 branches on a `ProvisionalOutcome` from M06, with that contract
stated. Add EC-5.15 for "no provisional verdict inside the budget" → select at
unchanged θ and mark the turn `theta_unadjusted`. §6.10 states that M13's score,
when it lands, corrects the *durable* record through M04 and is never
retro-applied to selection decisions already made.

### 1.3 A grounded item built from one student's repo can be served to another

The most serious finding in this document.

§6.1 describes grounded items as *"per-student from repo/resume/JD"*. §6.6's hard
filters are:

```
round_type · modality · status=active · scored_use_approved · time_budget
· not seen_item_ids · not recent_90d · not flagged_broken
```

There is **no candidate scoping**. A grounded item carries `grounded_on:
GroundingRef` pointing at student A's repository decision, and its stem will
contain A's design choices — plausibly A's service names, schema, or project
name. Nothing in the pool excludes it from student B's session.

That is a personal-data leak between students, in a bank, by default. It is also
the failure shape that is invisible in testing — both students pass, both get
scored — and obvious in a pilot, in front of a placement cell.

**Fix.** `grounded_for_candidate: UUID | None` on `Question`; a hard filter
`grounded_for_candidate in (None, req.candidate_id)`; a **gate** asserting zero
grounded items reach a candidate other than their subject; and a retention rule —
grounded items are deleted with the candidate's data, because they *are* the
candidate's data.

### 1.4 The freshness filter silently voids two other modules' promises

§6.6 applies `id__not_in=recent_90d(req.candidate_id)` as an unconditional hard
filter. §2.4's prose says *"unless the Counselor schedules it as a re-test"* — but
`SelectionRequest` has no field that can express that, so the prose is
unimplementable as written.

Two shipped promises die there:

- **M04** owns the `retest_queue` row and, per M13's `CONTRACTS.md`, carries
  `bypass_freshness` *"so M05's 90-day no-repeat filter cannot silently make the
  promise empty."* M04 already sends the flag. M05 cannot receive it.
- **M13** tells a disputing student, in shipped code: *"I've scheduled a fresh
  question on this topic for your next session either way."* If freshness eats
  the re-test, the product lied to a student who had already complained.

**Fix.** `SelectionRequest.forced_item_ids: list[UUID]` and
`bypass_freshness: bool`, both honoured ahead of the freshness filter, with §2.4's
disclosure string attached to the result so the student is told why.

### 1.5 EC-5.9 is named by M04 as a retraction source and does not retract

M04's spec, on retraction:

> `retracted_at` is set; mastery for that `(candidate, concept)` is **recomputed
> from surviving observations**, never compensated by an inverse update. **M5
> EC-5.9 (student flags an item)**, M13 re-scores, EC-4.7 disputes and EC-4.10
> account merges all route here.

M04 has built the receiving end and named M05 as a caller. M05's EC-5.9 says only
*"Recorded, item excluded from their θ update, flag count incremented."*

By the time a student flags an item, M13 has very likely emitted the observation
already — the flag comes during or after the answer, and the emit is async. And
"excluded from their θ update" can only mean M05's in-memory provisional θ, which
is discarded at session end anyway. The durable belief in M04 survives untouched:
the student flagged a broken question and it still moved their mastery.

**Fix.** EC-5.9 calls M04's retraction path for every observation derived from the
flagged item, and says so.

---

# Part 2 — Where the spec reintroduces its own traps

### 2.1 `predicted_p_correct` is Trap 2, in the contract

Trap 2, stated by this document:

> **Using binary 2PL on rubric-scored answers.** An open-ended answer scored 0–4
> is ordinal, not binary. Collapsing it to right/wrong throws away most of the
> information and biases `b`.

Then: `SelectionResult.predicted_p_correct: float`.

For a GRM item there is no "p correct" — there are five category probabilities.
Any implementer filling that field for the *majority* of the bank (§6.1: most
items are rubric-scored) must pick a threshold and collapse. That is the trap,
now baked into a type M06 and the report will both read.

**Fix.** `predicted_score: float` — expected score on the item's own scale — plus
`n_categories: int`. Binary items become the `n_categories = 2` case, rather than
the general case everything else is squeezed into.

### 2.2 The Elo path cannot produce a GRM parameter set, and cold start is all of Phase 1

§3.2 is emphatic: *"Cold start is 100% of Phase 1. Everything must work at n=0
items calibrated. Design the Elo path first and treat IRT as the upgrade."*

§6.5's Elo path:

```
n = 1..29 → R_item ← R_item + K(expected - actual)
            b_est = (R_item - 1500) / 173.7
```

Two breaks:

1. **`actual` is undefined for a rubric item.** Elo takes a binary outcome. The
   only way to feed it a 0–4 score is `score/4` — the collapse Trap 2 forbids.
2. **`b_est` is a scalar, and GRM needs `b_k` thresholds.** The contract says so
   itself: `b: float | list[float]  # list = category thresholds for GRM`.

So for the whole of Phase 1, across the majority of the bank, there is no defined
parameter set. `information(theta)` cannot be evaluated, so §6.6's ranking loses
its `info` term, so selection silently falls through to coverage and penalties.
**The CAT does not work at all during the phase the spec says is 100% cold
start** — and it will not say so, because every function still returns a number.

**Fix.** §6.5 gains an explicit cold-start construction: Elo estimates a
*location* `b̄`; category thresholds come from a fixed spacing prior
`b_k = b̄ + δ_k`, with `δ` from a per-`round_type` table; `a` holds at its prior
until MML runs. State that `params_source` distinguishes `prior | elo | mml` —
M13's shipped `ItemParams` already carries that field and currently defaults to
`"prior"`.

### 2.3 `round_types: list[str]` collides with how M13 picks a rubric

M05: `Question.round_types: list[str]` — an item may belong to several.

M13, shipped (`service.py`): `active_rubric = rubric or get_rubric(round_type)`,
where `round_type = turn.round_type or package.round_type` — **singular** — and
its `QuestionPackage` declares `round_type: str`.

The rubric is chosen by round type, and each rubric declares **exactly one**
`concept_bearing` dimension (M13 refuses to load one that does not). So the same
item administered in two round types is scored against two rubrics with two
different concept-bearing dimensions, producing observations about different
things from the same stem — and nothing in the data marks them as incomparable.

**Fix.** Keep `round_types` as *eligibility*; add a singular `round_type` to the
package M05 hands over, chosen at selection time and recorded on
`SelectionResult`.

### 2.4 `rubric_id` is dead, and unversioned besides

`Question.rubric_id: UUID`. Nothing in M13 reads it — the rubric resolves from
`round_type`. Worse, M13's rubrics are semver'd and a version bump triggers a
**batch re-score of history** (M13 §6.8), while `rubric_id` is a bare UUID with no
version. EC-5.5 ("item's rubric was deleted") describes a path M13 does not have:
rubrics load from YAML at boot, are validated there, and a bad one fails the boot.

**Fix.** Drop `rubric_id`. Use `rubric_round_type: str` plus an optional
`min_rubric_version: str` for the rare item needing an anchor added in a later
revision. Rewrite EC-5.5 as *"M13 has no rubric for this round type"* — a real
failure, detectable at `GET /v1/rubrics`.

### 2.5 An unbounded `concepts` list multiplies one answer into N beliefs

`concepts: list[ConceptWeight]  # primary + secondary with weights` — no cap.

M13's shipped `observations_for()` fans out **one observation per concept**, each
carrying the same dimension score and the same evidence spans:

```python
out.extend(
    _build(evaluation, package, bearing, cid, weight, bearing_key)
    for cid, weight in sorted(technical.items())
)
```

An item tagged with six concepts turns one answer into six observations. M04
increments `n_direct` six times and, wherever item parameters exist, runs six
likelihood updates from **one** response. That is not six pieces of evidence. It
is one, counted six times, and it inflates confidence in the direction that
flatters the student.

The spec never says what a concept weight *does* downstream, and M13 passes it
through as `concept_weight` without documenting an interpretation either.

**Fix.** Cap at **one primary plus at most two secondary**, enforced in
`ontology_lint` (which M04 already runs in CI); require weights to sum to ≤ 1.0;
and state plainly that secondary concepts are **coverage-bearing, not θ-bearing**
— they update counts and evidence and never enter a likelihood. That matches
M04's existing admissibility rule instead of fighting it.

### 2.6 FR-5.6 and §6.8 contradict each other on grounded items

FR-5.5/FR-5.6: five gates and a **human click** before an item is used in a scored
context. §6.8 fallback step 3: *"Generate a grounded item on the fly
(repo/resume) — always available, never repeats"* — inline, mid-session, no gates,
no human.

A grounded item is scored by M13, so it *is* used in a scored context. Both
statements cannot be true.

**Fix.** State the split: grounded items run **G1, G4, G5 inline** (schema,
uniqueness, safety — all cheap and local), skip G2/G3, and are marked
`theta_eligible = False`. They are legitimate for coverage and diagnosis and never
enter the IRT bank — which §3.2.5 already says, and which simply is not reconciled
with FR-5.6. §6.8 step 4 already uses this exact device for synthetic fallbacks,
so the mechanism exists; it just needs applying consistently.

### 2.7 The stopping rule can fire with coverage debt open, and M02's guarantee is the casualty

§6.9 stops when `SE(θ̂) < 0.30`. §6.6 says coverage dominates as the round ends. No
precedence is stated, so whichever condition fires first wins — and on a strong
candidate SE collapses fast, ending the round with requirements unprobed.

M02's entire contribution is coverage as a *guarantee*, and M13 already emits the
`scored` transition that makes it auditable. A silent early stop turns that
guarantee back into an intention, and the report still says the round completed.

**Fix.** Write the precedence down: coverage debt on **required** requirements
outranks SE. Stop on SE only when required debt is zero; otherwise continue with
`reason="coverage_debt"` until the time budget binds, then end and report the
shortfall honestly — §6.8 step 5 already has the right voice for it.

### 2.8 EC-5.10 makes exposure control decorative and never says so

> **EC-5.10** — Exposure control blocks every candidate → Bypass exposure
> (measurement beats leak-prevention in a single session) and log.

The right call for one session. But on a thin bank that branch is not
exceptional — it is the steady state. Sympson–Hetter becomes a no-op while
`AC-5.6 (cohort exposure ≤ 0.25)` continues to be reported as a target rather
than a measurement.

**Fix.** Count it. `exposure_bypass_rate` per concept per week on the bank-health
console, with an alert above 5% naming the concept — because the fix is writing
items there, which is exactly what that console exists to tell you.

### 2.9 `difficulty_prior` in logits is not a task a human can do

`difficulty_prior: float  # human estimate, logit scale`. Nobody reliably authors
"0.8 logits". They can author *"harder than a typical warm-up, easier than a
typical closing question"*.

**Fix.** A five-band ordinal (`intro | easy | core | hard | stretch`) with a
published band→logit table per round type. The table is a versioned artifact, so
recalibrating the mapping later does not mean re-authoring the bank.

### 2.10 Two smaller contract slips

- §6.6's `select()` ends `return top(pool, k=3)` while its declared return type is
  a single `SelectionResult`. The contract is right — `alternatives` holds the
  runners-up — so the pseudocode should match it.
- `GroundingRef` and `ConceptWeight` are used in §5 and never defined. M13's §5
  defines every type it names; this one should too.

---

# Part 3 — Sections the platform convention requires and this spec lacks

### 3.1 There is no "runs alone" section

Every module in this platform clones and runs alone. M13 §6.11 and M04 both
specify it and both ship it. M05 depends on **M04's ontology** — without it there
is no concept list, so there is nothing to tag an item with and nothing to select
against. The spec never says what M05 does when M04 is absent.

**Fix.** A §6.11 with a committed 120-concept ontology **snapshot** as a fixture,
`ontology_version` recorded on every item, and `/v1/deps` reporting that concepts
are fixture-backed. This is not only convention: it also fixes an ordering
problem, because M05 day 1 needs concepts while M04's ontology ships
`reviewed: false` until the faculty walk lands.

### 3.2 There is no consent, retention or purpose section

M05 generates items from a student's repository, resume and JD. That is personal
data, transformed, stored in a bank, and — per §1.3 — potentially served to other
people. M13 has a consent section and refuses to emit an observation without a
`consent_id`. M04 has an ethics annexe on its critical path. M05 has neither, and
Open Decision 3 covers *copyright* while saying nothing about the student.

**Fix.** A §6.12: grounded items carry `consent_id` and `grounded_for_candidate`;
they are deleted on candidate deletion; generation from a repository requires
M03's `authored_confidence` threshold — EC-5.12 already assumes this and never
states it as a requirement; and no grounded stem may quote a private repository
verbatim.

### 3.3 The gates are not phased, and AC-5.4 is a gate on a simulation the module authors

`AC-5.4 [GATE] — Simulated CAT efficiency vs fixed-form at equal SEM ≤ 60% of
items` cannot pass in Phase 1: it needs calibrated items, and §3.2 says Phase 1 is
100% cold start.

More important is what it measures. Both arms of the simulation are driven by the
same generative IRT model the CAT assumes, so the CAT wins nearly by
construction. M04 learned this and put a **mis-specification grid** at its
milestone M3 — *"built before the estimators are finished, the harness that
catches a bad decay curve in an afternoon instead of in a pilot."* M05's
simulation has no grid.

**Fix.** Phase every gate (Phase 1 / Phase 2 / ongoing). Add the mis-specification
grid — wrong `a`, correlated residuals, guessing on non-3PL items, drifting `b` —
and require AC-5.4 to hold **under mis-specification**, not only under the model's
own assumptions. A CAT that beats fixed-form only when the world matches its
assumptions is not a Paper 2 result.

---

# Part 4 — The build order is in the wrong sequence

The current day list runs: schema → authoring → fallback playlist → Elo →
selection → coverage → generation → gates → review UI → **IRT (day 11)** →
calibration → CAT → **simulation (day 14)**.

Simulation last is the mistake M04 already corrected. The simulator is not a test
of the finished thing; it is the instrument you build the estimators *with*. It
costs a day and saves a week of debugging a selector that looks plausible and is
wrong. M04's order puts it at M3, before its estimators, and explains why.

Second: **nothing in the fourteen days is item authoring**, yet M04 needs
`3+ items per concept × 120 concepts` for its granularity linter to pass, and the
Phase-1 target is 1,200. M15 hit this exact wall and called it correctly —
*"unglamorous human work with zero engineering dependencies; hand it to whoever
has spare afternoons in week one."* The same sentence belongs here, about items.

**Proposed order** (milestones, not days, matching M13's revision):

| Milestone | Days | Demoable outcome |
|---|---|---|
| **M0 — Contracts & the seam** | 1–2 | Package schema; ontology snapshot fixture; `/health` + `/v1/deps`; `module.json`; **the θ-ownership contract written and agreed with M04 and M06**. Item authoring starts today and never stops. |
| **M1 — Bank & fallback** | 2–3 | Tables, embeddings, SimHash; authoring tool; 200 curated items; the **fixed fallback playlist**, on day one, as the spec already says |
| **M2 — Simulation first** | 3–4 | 500 synthetic students, known θ, **mis-specification grid** — before the estimators exist |
| **M3 — Item models** | 4–6 | 2PL/GRM/3PL behind one interface; cold-start construction (Elo location + threshold prior); `params_source` honest |
| **M4 — Selection v1** | 6–8 | Hard filters including **candidate scoping and freshness bypass**; θ-target; stretch; WPM coverage; the precedence rule |
| **M5 — The session seam** | 8–9 | Provisional θ owned here; two-branch precompute keyed on M06's `ProbeStrategist`; end-of-session reconciliation with M04 |
| **M6 — Generation & gates** | 9–11 | Generation prompt, full-package output, G1–G5, review queue, grounded inline path with the G1/G4/G5 split |
| **M7 — Calibration** | 11–13 | Nightly MML, drift detection, bad-item flags, exposure updates |
| **M8 — CAT & console** | 13–14 | Sympson–Hetter, stretch rule, pre-computation path, **bank-health console** |
| *(ongoing)* | | Item authoring; exposure monitoring; AC-5.4 re-run under mis-specification |

---

## Summary of required changes

| # | Change | Severity |
|---|---|---|
| 1 | M05 owns the provisional θ — name it, scope it, reconcile it | **P0 contract** |
| 2 | Branch the precompute on M06's ProbeStrategist, not M13's async score | **P0 contract** |
| 3 | `grounded_for_candidate` + hard filter + gate | **P0 privacy** |
| 4 | `forced_item_ids` / `bypass_freshness` in `SelectionRequest` | **P0 contract** |
| 5 | EC-5.9 calls M04's retraction path | **P0 contract** |
| 6 | `predicted_p_correct` → `predicted_score` + `n_categories` | P0 |
| 7 | Cold-start construction for GRM thresholds | P0 |
| 8 | One administered `round_type`, recorded | P0 |
| 9 | Drop `rubric_id`; rewrite EC-5.5 | P1 |
| 10 | Cap concepts; secondary is coverage-bearing, not θ-bearing | P0 |
| 11 | Reconcile FR-5.6 with the inline grounded path | P1 |
| 12 | Coverage outranks SE in the stopping rule | P0 |
| 13 | Measure `exposure_bypass_rate` | P1 |
| 14 | `difficulty_prior` as an ordinal band | P2 |
| 15 | Define `GroundingRef` and `ConceptWeight`; fix `select()`'s return | P2 |
| 16 | §6.11 — runs alone, on an ontology snapshot | P1 |
| 17 | §6.12 — consent, retention, authored confidence | **P0 ethics** |
| 18 | Phase the gates; AC-5.4 under mis-specification | P1 |
| 19 | Build order: simulation at M2, authoring from day 1 | P1 |
