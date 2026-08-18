"""Upstream probing — spec §6.11, `module.json`.

Platform Rule 2, applied to services rather than students: **a missing
dependency narrows the SCOPE of what this module produces, never the quality,
and never silently.** For M05 that means:

* **M04 absent** — concepts come from the committed ontology snapshot, stamped
  with its `ontology_version`. Items are authored, selected and calibrated
  normally; θ starts cold rather than seeded, which is the honest belief about
  a candidate nobody has measured.
* **M13 absent** — items are served and never scored, so no responses accrue:
  Elo stays at its prior and the bank cannot calibrate. Selection still works,
  which is exactly what the cold-start path in §6.5 is for.

M05 declares no `required: true` dependency, and it is the module with the
strongest reason not to: it sits on the interview's hot path, and a student
cannot be told "no questions today, the memory service is restarting".
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ai_core.dependencies import DependencyRegistry

MANIFEST = Path(__file__).resolve().parents[2] / "module.json"


@lru_cache(maxsize=1)
def deps() -> DependencyRegistry:
    return DependencyRegistry.from_manifest(MANIFEST)


def reload() -> None:
    deps.cache_clear()


__all__ = ["MANIFEST", "deps", "reload"]
