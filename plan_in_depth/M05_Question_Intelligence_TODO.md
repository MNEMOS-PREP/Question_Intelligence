# M05 — TODO · Question Intelligence


> **Completion: 84%** — 21 of 28 functional requirements met, 5 partially. Two requirements have no implementation at all — FR-5.6 human review queue, a P0, and FR-5.28 exposure-bypass reporting. Five more are coded with no test behind them. §8.2's bank console (*"build it, you will live in it"*) does not exist.
>
> _Method: `(met + ½ × partial) ÷ total`, audited against shipped code, 2026-08-28; re-checked 2026-10-04: unchanged. One measure applied the same way to all nineteen modules so they compare; it counts requirements, not screens or gates._

Running list for **M05 Question Intelligence**.
Spec: [M05_Question_Intelligence.md](M05_Question_Intelligence.md)

> **Read this first when starting a session on M05.** It is the running state
> of the module: what is done, what is next, and what is deliberately deferred.
> Update it as things land — a stale list is worse than no list, because the
> next session trusts it.

- **Phase:** 1-2 · **Owner:** E3 · **Ports:** API `8105`, web `5205`
- **Repo:** `Question_Intelligence`

Legend: ✅ done · 🟡 partly done · ⬜ not started

### 2026-09-17 — two seams M06 found on its first real call

- **`/questions/select` now fills the provisional θ itself** from the seeded
  session, when the caller sends none. It used to require the caller to pass
  it, which put M06 in an impossible position: §6.10 says the estimate is
  ours, is never persisted and dies at close — and M06 checkpoints its own
  state after every step, so passing it back meant writing it down.
  `ProvisionalIsNotDurable` exists to prevent exactly that. An explicit
  `theta_provisional` still wins, because the simulator passes one.
- **`Bank.get()` searches the fallback playlist too.** `select()` falls back to
  it by design (§6.8 step 5) and the id it returned then 404'd on
  `GET /questions/{id}` — so a caller handed a playlist item had to treat a
  working bank as an absent one, which is what M06 did.

Both are covered by `tests/test_session_seam.py`, and both mutations fail it.

### 2026-10-02 — asks from M06

- ✅ **`POST /questions/{id}/flag` takes any caller** — fixed 2026-10-02. M05 is on
  Platform_Core v0.11.0 with `candidate_guard` on its router. A session's
  routes answer only its owner, and `seed`, `select` and the ⚑ check the
  student their body names. `select` also refuses to read another student's
  seeded estimate. `tests/test_guard.py` covers it, and two mutations fail it.
- ✅ **`GET /questions/{id}` served the answer key to any caller** — fixed
  2026-10-02 on Platform_Core v0.12.0. A browser gets the stem and metadata;
  `reference_answer`, `key_points`, `follow_ups` and `hint_ladder` come back
  empty with `X-Answer-Key: withheld`. A module holding the platform secret
  (`ai_core.service`) or an admin gets the whole item; `/package` is
  service-only. Found on the way: a GROUNDED item (FR-5.22) was readable by
  any student holding its id, though `select` never served it to them — it is
  now its own student's only. `tests/test_answer_key.py`; three mutations fail it.
  M06 and M13 send the secret.
- ⬜ **EC-5.9's retraction is still not wired.** M06's ⚑ tells the student a
  flagged question "won't be picked for anyone again", which is true, and
  deliberately does not say the observations it produced were undone, because
  they are not.
- ⬜ (standing, M06 review Part 5) `difficulty_offset` on `SelectionRequest`,
  so a mode can lean a session harder or easier without M06 second-guessing
  the CAT.
- ⬜ (standing) Per-round-type counts on `/bank/health`. M06's plan-time probe
  asks per round type, and a total hides a thin corner of the bank.

### 2026-10-07/08 — tracks, drafted questions, and not the same question again

- ✅ **Tracks** (`aecd45b`): `GET /v1/bank/tracks` names each round type the
  bank can serve — its title, group, blurb, `kind` (technical or
  behavioural) and counts of approved and drafted items. M06's setup page
  offers exactly these.
- ✅ **Drafted questions for every track** (`c438329`): 292 items written by
  `jobs/draft_items.py` into `bank/*.drafted.yaml`, **unreviewed**. A caller
  that sends `allow_drafts` may be served one when nothing approved fits; the
  response says `scored_use: false`, and M06 asks it, never scores it, never
  moves θ for it. Approving them is FR-5.6's queue — still not built, and the
  approving is the team's decision, not code's.
- ✅ **The ontology snapshot** (`67023fe`): M04's 156 concepts, the 36
  machine-learning ones included (M04 `f710a2c`, the user's decision).
- ✅ **Not the last question again** (`e62ddee`, `tests/test_variety.py`): a
  selection request may carry `asked_this_session`; an item on the concept
  just asked is weighed ×0.3, each repeat of a concept in the session halves
  it again, and a stem whose content words overlap one already asked by a
  quarter or more (Jaccard ≥ 0.25) is weighed ×0.2.

---

## 0. Ideas and scouting

Things worth building that did not come from the spec — usually from reading
somebody else's implementation. **New ideas go at the top of this section.**

The rule we keep arriving at: borrow a **technique**, not a **component**. The
platform's contracts — character offsets, per-fact provenance, permanent
evidence — are more demanding than general-purpose tools assume, so integration
usually costs more than reimplementing the one idea we actually wanted.

### ⬜ Reciprocal Rank Fusion for question selection

From [rohitg00/agentmemory](https://github.com/rohitg00/agentmemory), via M04 —
see [M04_Skill_Graph_Memory_TODO.md](M04_Skill_Graph_Memory_TODO.md) for the
full verdict on the tool itself.

Question selection has several ranking signals and no principled way to combine
them: IRT information at the candidate's theta, resume-claim relevance, recency
of exposure, company-format match from M15. RRF fuses ranked lists without
needing them on a common scale — score each candidate `1 / (k + rank)` summed
across the lists it appears in, k=60.

That last property is the useful one. Normalising an IRT information value
against a cosine similarity against a "days since last asked" is a fudge; RRF
sidesteps it by using only the ordering.

About fifteen lines. No dependency.

---

## 1. Where the module stands

| | |
|---|---|
| Status | **Built.** FR coverage was audited on 2026-08-28 (the header's counts) and re-checked on 2026-10-04. The per-requirement table was never written into this file, and the §13 acceptance gates have not been walked one by one |
| Backend tests passing | **94** |
| Release gates (`-m gate`) | **11** |
| Frontend | **none** — M05 is a service; M06 and M13 are its callers |

*Counted 2026-10-04 by running the suite, not by reading this file.*

> **Re-checked 2026-10-04:** FR-5.6 (the human review queue, a P0) and
> FR-5.28 (exposure-bypass reporting) still have no route.

---

## 2. Next

1. **FR-5.6, the human review queue** — a P0 with no implementation.
   `POST /questions/{id}/flag` records a flag; there is no queue to review one in.
2. **FR-5.28, exposure-bypass reporting.**
3. **Tests for the five requirements coded without one** (the 2026-08-28
   audit's count) — name each here as it gets its test.
4. §8.2's bank console, once there is a queue to put in it.

---

## 3. Deferred — inter-module

Not gaps in M05. Each needs a module that is not built or not wired yet, and
each is listed so it is not mistaken for an oversight.

_To fill in._
