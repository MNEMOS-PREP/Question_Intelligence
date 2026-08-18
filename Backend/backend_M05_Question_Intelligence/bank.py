"""The question bank and the fallback playlist — spec §6.1, §6.8.

Two jobs. Load authored items and validate them hard at **load** time, and
guarantee that selection always has something to return.

**Everything fails at load, not at selection.** A malformed item discovered
mid-interview is a stalled session; the same item discovered at boot is a
sentence in a log. Concept ids are checked against the ontology for the same
reason M04 lints its own: a typo'd `concept:hashng` produces an item that is
selectable, scorable, and contributes to the mastery of a concept that does not
exist.

**The fallback playlist is not a nicety.** §6.8 step 5: it is the last line
before the round ends, it is thirty minutes of work, and without it a thin bank
means dead air in front of a student.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid5

import yaml

from . import ontology as ontology_module
from .contracts import (
    ConceptRole,
    ConceptWeight,
    DifficultyBand,
    ItemStatus,
    KeyPoint,
    Modality,
    Provenance,
    Question,
)

log = logging.getLogger(__name__)

BANK_DIR = Path(__file__).parent / "bank"

#: Item ids are derived from a stable label, not minted fresh, so re-loading the
#: seed bank does not orphan every response ever recorded against it.
ITEM_NAMESPACE = UUID("5f1c1d3e-0000-4000-8000-000000000005")


class BankError(RuntimeError):
    """An authored item is not usable. Raised at load; never at selection."""


@dataclass
class Bank:
    questions: list[Question] = field(default_factory=list)
    playlist: list[Question] = field(default_factory=list)
    version: str = "seed"
    by_label: dict[str, Question] = field(default_factory=dict)

    def get(self, question_id: UUID) -> Question | None:
        return next((q for q in self.questions if q.id == question_id), None)

    def concept_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for question in self.questions:
            counts[question.primary_concept] = counts.get(question.primary_concept, 0) + 1
        return counts


def item_id(label: str) -> UUID:
    return uuid5(ITEM_NAMESPACE, label)


def _parse(entry: dict, *, label: str, known: set[str]) -> Question:
    concepts = []
    for i, raw in enumerate(entry.get("concepts", [])):
        concept_id = raw["id"] if isinstance(raw, dict) else raw
        if concept_id not in known:
            raise BankError(
                f"item {label!r} tags {concept_id!r}, which is not in the ontology. "
                "A typo here produces an item that is selectable, scorable, and "
                "contributes mastery to a concept nobody can look up."
            )
        weight = raw.get("weight", 0.7 if i == 0 else 0.15) if isinstance(raw, dict) else (
            0.7 if i == 0 else 0.15
        )
        concepts.append(
            ConceptWeight(
                concept_id=concept_id,
                weight=weight,
                role=ConceptRole.primary if i == 0 else ConceptRole.secondary,
            )
        )

    key_points = [
        KeyPoint(id=kp.get("id", f"kp_{n + 1}"), statement=kp["statement"],
                 weight=kp.get("weight", 1.0), required=kp.get("required", False))
        for n, kp in enumerate(entry.get("key_points", []))
    ]
    if len(key_points) < 2:
        raise BankError(
            f"item {label!r} has {len(key_points)} key points; at least 2 are needed. "
            "M13 measures coverage against these and renders the checklist a "
            "student actually acts on — one key point is a pass/fail dressed up."
        )
    if not entry.get("reference_answer", "").strip():
        raise BankError(f"item {label!r} has no reference answer, so it cannot be scored")

    round_types = entry.get("round_types") or [entry.get("round_type", "dsa_verbal")]

    return Question(
        id=item_id(label),
        stem=entry["stem"],
        modality=Modality(entry.get("modality", "verbal")),
        round_types=round_types,
        concepts=concepts,
        provenance=Provenance(entry.get("provenance", "curated")),
        difficulty_band=DifficultyBand(entry.get("difficulty_band", "core")),
        reference_answer=entry["reference_answer"],
        key_points=key_points,
        rubric_round_type=entry.get("rubric_round_type", round_types[0]),
        time_budget_s=entry.get("time_budget_s", 240),
        hint_ladder=entry.get("hint_ladder", []),
        status=ItemStatus(entry.get("status", "active")),
        # Seed items are hand-written by the team, which IS the human review
        # FR-5.6 requires. A `generated` item arriving through this path with
        # approval already set would be the gate quietly bypassed, so it is
        # refused below.
        scored_use_approved=entry.get("scored_use_approved", True),
        theta_eligible=entry.get("theta_eligible", True),
        ontology_version=entry.get("ontology_version", "1.0"),
    )


def load_file(path: Path, *, known: set[str]) -> list[Question]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for label, entry in (raw.get("items") or {}).items():
        question = _parse(entry, label=label, known=known)
        if question.provenance is Provenance.generated and question.scored_use_approved:
            raise BankError(
                f"item {label!r} is `generated` and already approved for scored use. "
                "FR-5.6 requires a human click, and a YAML file is not one."
            )
        out.append(question)
    return out


_cached: Bank | None = None


def load(*, refresh: bool = False) -> Bank:
    global _cached
    if _cached is not None and not refresh:
        return _cached

    known = ontology_module.load().ids()
    questions: list[Question] = []
    playlist: list[Question] = []
    labels: dict[str, Question] = {}

    for path in sorted(BANK_DIR.glob("*.yaml")):
        loaded = load_file(path, known=known)
        target = playlist if path.stem.endswith("playlist") else questions
        target.extend(loaded)
        for question in loaded:
            labels[_label_of(path, question)] = question

    if not playlist:
        log.warning(
            "no fallback playlist loaded — §6.8 step 5 has no last line, so a thin "
            "bank means dead air in front of a student"
        )

    _cached = Bank(questions=questions, playlist=playlist, by_label=labels)
    return _cached


def _label_of(path: Path, question: Question) -> str:
    return f"{path.stem}:{question.stem[:32]}"


__all__ = ["BANK_DIR", "Bank", "BankError", "item_id", "load", "load_file"]
