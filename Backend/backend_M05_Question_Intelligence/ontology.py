"""The concept list every item is tagged against — spec §6.11.

M05 does not own the ontology; M04 does. What lives here is a **snapshot**, and
the reason it exists is scheduling rather than architecture: M05 needs concepts
on day one, and M04's ontology carries `reviewed: false` until a faculty walk
lands. Waiting would idle this module for weeks.

So: prefer the live service, fall back to the snapshot, and **always say which**
(`/v1/deps`). Every item records the `ontology_version` it was tagged against,
so reconciling later is a diff rather than an archaeology exercise.

`Concept` itself comes from `ai_core.concepts` — two definitions of what a
concept is, is how M04's mastery map and this bank quietly stop meaning the same
thing by `concept:hash_maps`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from ai_core.concepts import Concept

log = logging.getLogger(__name__)

SNAPSHOT = Path(__file__).parent / "ontology" / "concepts.snapshot.yaml"

#: FR-5.26 / M04's granularity check. A concept with fewer than this many items
#: cannot be measured; one with more than the ceiling is mis-sized and should be
#: split. M04 runs this in CI once M05 is seeded — the numbers live here because
#: this is the module that can actually count.
MIN_ITEMS_PER_CONCEPT = 3
MAX_ITEMS_PER_CONCEPT = 40


class OntologyError(RuntimeError):
    """The concept list could not be loaded. There is no sensible default —
    an empty ontology means every item is untaggable and every selection is
    unconstrained, which is worse than refusing to start."""


@dataclass
class Ontology:
    concepts: dict[str, Concept] = field(default_factory=dict)
    version: str = "unknown"
    #: `snapshot` or `m04`. Travels with the data because the two can differ,
    #: and a bank tagged against one and selected against the other is a bug
    #: nobody can see.
    source: str = "snapshot"
    reviewed: bool = False

    def __contains__(self, concept_id: str) -> bool:
        return concept_id in self.concepts

    def __len__(self) -> int:
        return len(self.concepts)

    def get(self, concept_id: str) -> Concept | None:
        return self.concepts.get(concept_id)

    def ids(self) -> set[str]:
        return set(self.concepts)


_cached: Ontology | None = None


def load(*, refresh: bool = False) -> Ontology:
    """The ontology in use. Snapshot today; M04 when it is wired."""
    global _cached
    if _cached is not None and not refresh:
        return _cached
    _cached = _load_snapshot()
    return _cached


def _load_snapshot() -> Ontology:
    if not SNAPSHOT.exists():
        raise OntologyError(
            f"no ontology snapshot at {SNAPSHOT}. This module cannot select "
            "against an empty concept list, and starting with one would make "
            "every item untaggable while every endpoint kept answering."
        )
    raw = yaml.safe_load(SNAPSHOT.read_text(encoding="utf-8")) or {}
    entries = raw.get("concepts", raw if isinstance(raw, list) else [])

    concepts: dict[str, Concept] = {}
    for entry in entries:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        try:
            concept = Concept.model_validate(entry)
        except Exception as exc:  # noqa: BLE001 - one bad row must not lose 119 good ones
            log.warning("ontology: skipping %s — %s", entry.get("id"), exc)
            continue
        concepts[concept.id] = concept

    if not concepts:
        raise OntologyError(f"{SNAPSHOT} parsed to zero concepts")

    return Ontology(
        concepts=concepts,
        version=str(raw.get("ontology_version", "1.0")),
        source="snapshot",
        reviewed=bool(raw.get("reviewed", False)),
    )


def granularity(counts: dict[str, int], ontology: Ontology | None = None) -> dict[str, list[str]]:
    """M04's granularity check, run from the side that can count items.

    Returns the concepts that are unmeasurable and the ones that are mis-sized.
    `thin` is the actionable half and it is what the bank-health console's
    exhaustion column is for — without it you write more array questions,
    because array questions are easy to write.
    """
    ontology = ontology or load()
    thin, fat, unknown = [], [], []
    for concept_id in sorted(ontology.ids()):
        n = counts.get(concept_id, 0)
        if n < MIN_ITEMS_PER_CONCEPT:
            thin.append(concept_id)
        elif n > MAX_ITEMS_PER_CONCEPT:
            fat.append(concept_id)
    for concept_id in sorted(set(counts) - ontology.ids()):
        unknown.append(concept_id)
    return {"thin": thin, "fat": fat, "unknown": unknown}


__all__ = [
    "MAX_ITEMS_PER_CONCEPT",
    "MIN_ITEMS_PER_CONCEPT",
    "SNAPSHOT",
    "Ontology",
    "OntologyError",
    "granularity",
    "load",
]
