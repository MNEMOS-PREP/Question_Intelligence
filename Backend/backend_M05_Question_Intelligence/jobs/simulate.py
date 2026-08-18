"""The full AC-5.4 / AC-5.5 run — §12.

    .venv\Scripts\python -m backend_M05_Question_Intelligence.jobs.simulate

The test suite runs a small cohort so it stays fast. This is the real one: 500
students against the whole mis-specification grid, which is the evidence AC-5.4
actually rests on. Under the model's own assumptions the CAT wins close to by
construction, so only the mis-specified rows say anything.
"""

from __future__ import annotations

import random
import sys
import time

from .. import simulation as sim

CONCEPTS = ("concept:hashing", "concept:recursion", "concept:sorting")


def main(students: int = 500, items: int = 400, form_length: int = 30) -> int:
    print(f"{'world':<46} {'CAT':>5} {'fixed':>6} {'SE':>5} {'eff':>5} {'r':>6}  ")
    print("-" * 80)

    started = time.time()
    worst_efficiency, worst_recovery = 0.0, 1.0

    for mis in sim.GRID:
        rng = random.Random(17)
        bank = sim.make_bank(items, mis=mis, rng=rng, concepts=CONCEPTS)
        cohort = sim.make_cohort(students, mis=mis, rng=rng, concepts=CONCEPTS)
        efficiency, cat, fixed = sim.efficiency_at_equal_sem(
            cohort, bank, form_length=form_length
        )
        target = sum(fixed.final_se) / len(fixed.final_se)

        label = (
            "CLEAN (assumptions hold — not evidence)"
            if mis.is_clean
            else ", ".join(f"{k}={v}" for k, v in vars(mis).items() if v)
        )
        verdict = "ok" if efficiency <= 0.60 and cat.recovery_r >= 0.90 else "FAIL"
        print(
            f"{label[:46]:<46} {cat.mean_items:5.1f} {fixed.mean_items:6.1f} "
            f"{target:5.2f} {efficiency:5.2f} {cat.recovery_r:6.3f}  {verdict}"
        )
        worst_efficiency = max(worst_efficiency, efficiency)
        worst_recovery = min(worst_recovery, cat.recovery_r)

    print("-" * 80)
    print(f"AC-5.4  worst efficiency  {worst_efficiency:.2f}  (target <= 0.60)")
    print(f"AC-5.5  worst recovery r  {worst_recovery:.3f}  (target >= 0.90)")
    print(f"{time.time() - started:.0f}s")

    return 0 if worst_efficiency <= 0.60 and worst_recovery >= 0.90 else 1


if __name__ == "__main__":
    sys.exit(main())
