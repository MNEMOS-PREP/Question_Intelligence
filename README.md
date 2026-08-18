# M05 — Question Intelligence

> **What do we ask next.** The bank, the item models, and the selection that
> makes a 40-minute interview learn more than a 90-minute fixed test.
>
> Spec: [plan_in_depth/M05_Question_Intelligence.md](plan_in_depth/M05_Question_Intelligence.md) (Revision 2) · Review that produced it: [M05_REVIEW.md](plan_in_depth/M05_REVIEW.md) · Ports: API `8105` ([PORTS.txt](PORTS.txt))

```bash
git clone https://github.com/MNEMOS-PREP/Question_Intelligence
cd Question_Intelligence/Backend
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest          # 75 passed, no network, no API key
cd .. && start_questions.bat            # API on :8105
```

No API key needed, and **no model is called anywhere in this milestone.**
Selection, the item models, the cold start and the whole simulation are
arithmetic. Generation is the only thing here that will ever need a key, and it
lands in M6.

---

## What is built

Milestones **M0–M4** of the [§14 build order](plan_in_depth/M05_Question_Intelligence.md) — the spine, in the order the revised spec puts them.

| Milestone | What landed |
|---|---|
| **M0 — Contracts & the seam** | `ai_core.concepts` consumed, not redefined · `grounded_for_candidate` · `theta_provisional` · `predicted_score` not `p_correct` · `module.json` · `/health` + `/v1/deps` |
| **M1 — Bank & fallback** | YAML loader validating **at load**, 12 seed items, and the 8-item **fallback playlist** — §6.8's last line |
| **M2 — Simulation first** | 500 synthetic students and the **mis-specification grid**, built before the estimators |
| **M3 — Item models** | 2PL · **GRM** · 3PL behind one interface · band→logit table · Elo location + threshold spacing prior · EAP |
| **M4 — Selection v1** | Hard filters incl. candidate scoping and the freshness bypass · warm-up · stretch · WPM coverage · the stopping precedence |
| *(seam)* | The session's provisional θ: seed, observe, close, reconcile |

**75 tests, 11 release gates, ruff clean, and not one of them opens a socket or calls a model.**

### What is deliberately not built

Generation and the G1–G5 gates, the review queue, nightly MML recalibration, Sympson–Hetter exposure control, and the bank-health console UI — milestones M6–M8. They are **absent, not stubbed**: an endpoint that returns a placeholder is worse than one that does not, because a caller writes against it and finds out later.

**Nothing in the bank is calibrated.** Every parameter set comes from the band table and the spacing prior, and `params_source` says `prior` on every selection rather than in a footnote. That is the honest state of a module whose spec says cold start is 100% of Phase 1.

---

## The four things worth reading the code for

**1. The cold start has to produce a *usable* parameter set, not a placeholder.** [`models_irt.py`](Backend/backend_M05_Question_Intelligence/models_irt.py) · Cold start is all of Phase 1 and most of the bank is rubric-scored. Elo can only ever produce a *location*; GRM needs a threshold vector. Without the bridge — Elo location plus a spacing prior — `information(θ)` is unevaluable for the majority of the bank, §6.6's ranking silently loses its information term and falls through to penalties, and **every function still returns a number**. The CAT would not work at all in the phase that is entirely cold start, and nothing would say so. `AC-5.14` is the gate.

**2. A grounded item never leaves the student it was built from.** [`selection.py`](Backend/backend_M05_Question_Intelligence/selection.py) · A question generated from someone's repository carries their service names in the stem. The original spec's filter list had round type, modality, freshness and status — and no candidate scoping, so it was selectable by the whole cohort. Both sessions complete, both get scored, and the leak is visible only to the student who recognises their own project in someone else's interview. `grounded_for_candidate` is a hard filter, a contract validator, and `AC-5.11`.

**3. The provisional θ is named so you cannot persist it by accident.** [`session.py`](Backend/backend_M05_Question_Intelligence/session.py) · M04 and M06 were both amended to say M05 owns the in-session estimate; this spec had not been. Reading M04's posterior per selection looks equivalent and is not — it does not move during a session, so the CAT becomes a fixed-form test pinned at entry ability *while still reporting itself as adaptive*. `SessionState.__getstate__` raises, and there is deliberately no `GET` for it.

**4. `MisSpecification` is what makes AC-5.4 mean anything.** [`simulation.py`](Backend/backend_M05_Question_Intelligence/simulation.py) · Drive both arms with the model the CAT assumes and the CAT wins by construction — the gate then measures our arithmetic, not the method. Each grid entry is a way reality departs from the textbook: wrong discrimination, correlated residuals, guessing, drift, dead items, a rubric whose middle categories nobody uses.

The harness also caught a flaw in its own first version: it compared a CAT stopped at SE 0.30 against a fixed 30 items *regardless of the precision that reached*. AC-5.4 says "at equal SEM", and under the honest comparison two apparent failures disappeared. Run it yourself:

```bash
.venv/Scripts/python -m backend_M05_Question_Intelligence.jobs.simulate
```

---

## Layout

```
Backend/backend_M05_Question_Intelligence/
  contracts.py     §5 — the shapes five other modules read
  models_irt.py    §6.4/§6.5 — 2PL, GRM, 3PL, the cold start, EAP
  simulation.py    §12 — 500 students and the mis-specification grid
  selection.py     §6.6/§6.8/§6.9 — filters, ranking, fallback, stopping
  session.py       §6.10 — the provisional θ, and why it is not durable
  bank.py          §6.1 — the loader; every rule fails at LOAD
  bank/*.yaml      the items, and the fallback playlist
  ontology.py      §6.11 — concepts, from M04 or from the snapshot
  ontology/        the 120-concept snapshot. Do not hand-edit.
  jobs/simulate.py the full AC-5.4 / AC-5.5 run
```

## Conventions worth knowing before you edit

- **Everything fails at load, not at selection.** A malformed item found mid-interview is a stalled session; the same item found at boot is a line in a log. Concept ids are checked against the ontology — a typo'd `concept:hashng` otherwise produces an item that is selectable, scorable, and contributes mastery to a concept nobody can look up. This caught three invented ids in the seed bank while it was being written.
- **`round_types` is eligibility; `round_type` is administration.** M13 resolves the rubric from a single round type and each rubric has exactly one concept-bearing dimension, so which one was used is a fact about the turn.
- **At most one primary and two secondary concepts.** M13 emits one observation per concept, each carrying the same score and the same evidence. Six concepts turn one answer into six beliefs in M04 — one response counted six times, in the direction that flatters the student.
- **A repeat is disclosed, never silent.** An announced repeat is a re-test; an unannounced one is the complaint this module is named for.

## Before the next milestone

1. **Author items.** The bank has 12 and the playlist 8. Phase 1 targets 1,200, and M04's granularity linter wants 3+ across 120 concepts — `GET /v1/bank/health` currently reports all 120 as thin. This has zero engineering dependencies and it is the long pole.
2. **Settle open decision 7** with E2: the `ProbeStrategist` verdict has to stay in M06. M5 (the session seam) is built against that assumption.
3. **Settle open decision 8** — how information is compared *across* concepts. Found live: with θ = 1.6 on one concept, selection picked an item on a different, never-measured concept, because raw information at a default θ = 0 sits at its peak. Defensible, nowhere chosen, and it changes every selection.
4. **Populate the band→logit table** from a real calibration sitting (open decision 6). Every cold-start difficulty depends on it and it is currently one default row.
