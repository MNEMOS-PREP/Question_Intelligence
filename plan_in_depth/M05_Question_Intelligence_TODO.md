# M05 — TODO · Question Intelligence


> **Completion: 84%** — 21 of 28 functional requirements met, 5 partially. Two requirements have no implementation at all — FR-5.6 human review queue, a P0, and FR-5.28 exposure-bypass reporting. Five more are coded with no test behind them. §8.2's bank console (*"build it, you will live in it"*) does not exist.
>
> _Method: `(met + ½ × partial) ÷ total`, audited against shipped code, 2026-08-28. One measure applied the same way to all nineteen modules so they compare; it counts requirements, not screens or gates._

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

- ⬜ **`POST /questions/{id}/flag` takes any caller.** There is no identity
  guard, so anybody can exclude any item from selection. M06's ⚑ forwards the
  student (`candidate_id` in the body) and M05 should check who is asking —
  Platform_Core v0.10.0's `candidate_guard`; M05 is still on v0.6.0.
- ⬜ **EC-5.9's retraction is still not wired.** M06's ⚑ tells the student a
  flagged question "won't be picked for anyone again", which is true, and
  deliberately does not say the observations it produced were undone, because
  they are not.

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
| Status | **Built, and not yet audited against the spec.** |
| Backend tests passing | **75** |
| Release gates (`-m gate`) | **11** |
| Route decorators | **13** |
| Frontend | **none on disk** |

*Counted 2026-08-25, by running the suite — not by reading this file. This row
replaced "Not started", which was written before the module was and had become
the kind of line the header above warns about: the next session trusts it.*

> **What has NOT been done is the audit.** Nobody has walked M05's functional
> requirements one at a time and checked each against the code. A green suite
> says the tests that exist pass; it does not say which requirements have tests.
> M01 learned that the expensive way — its FR table read 98% complete while the
> §13 KPI had no numerator, the semantic tier was absent and ten endpoints had
> no client. Every one of those was invisible from a passing suite.
>
> The next session on M05 should start there, and write what it finds here.
| Spec | Written — see the link above |

_Fill this in when work on M05 begins: tests passing, gates, FR coverage,
and what is actually blocking._

---

## 2. Next

_To fill in._ The spec's §4 functional requirements and §13 acceptance
gates are the natural first pass — copy them in as a checklist, then mark what
already exists.

---

## 3. Deferred — inter-module

Not gaps in M05. Each needs a module that is not built or not wired yet, and
each is listed so it is not mistaken for an oversight.

_To fill in._
