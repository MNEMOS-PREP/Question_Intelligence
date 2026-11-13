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
    FollowUpTemplate,
    ItemStatus,
    KeyPoint,
    Modality,
    Provenance,
    Question,
    QuestionType,
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
        """Any item this bank can ADMINISTER, playlist included.

        It searched `questions` only, which made the selector and the read
        route disagree: `select()` falls back to the playlist by design
        (§6.8 step 5), and the id it returned then 404'd here — so a caller
        could not fetch the item it had just been given. M06 hit exactly that
        and had to treat a working bank as an unavailable one.
        """
        return next(
            (q for q in (*self.questions, *self.playlist) if q.id == question_id), None
        )

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
        follow_ups=[
            FollowUpTemplate(depth=min(5, i + 1), template=str(text))
            for i, text in enumerate(entry.get("follow_ups") or [])
            if isinstance(text, str)
        ],
        question_type=QuestionType(entry.get("question_type", "conceptual")),
        facet=entry.get("facet"),
        misconceptions=list(entry.get("misconceptions") or []),
        strong_answer=list(entry.get("strong_answer") or []),
        status=ItemStatus(entry.get("status", "active")),
        # Seed items are hand-written by the team, which IS the human review
        # FR-5.6 requires. A `generated` item arriving through this path with
        # approval already set would be the gate quietly bypassed, so it is
        # refused below.
        scored_use_approved=entry.get("scored_use_approved", True),
        theta_eligible=entry.get("theta_eligible", True),
        ontology_version=entry.get("ontology_version", "1.0"),
    )


#: Seconds to answer, by difficulty, for a compact item that does not say.
COMPACT_TIME = {"intro": 150, "easy": 180, "core": 240, "hard": 300, "stretch": 360}
#: A design or project question is spoken longer, whatever its difficulty.
COMPACT_TIME_BY_TYPE = {"design": 420, "project": 300, "coding": 300}


def expand_compact(raw: dict) -> dict:
    """A compact authoring file (`format: compact`) as the bank's own format.

    Written so a reviewer reads one item in a few lines:

        c: [react, javascript]     concepts, primary first ("concept:" implied)
        d: core                    difficulty band
        t: debugging               question type
        f: hooks                   the facet (sub-competency) it is about
        q: ...                     the stem, as spoken
        a: ...                     a good reference answer
        k: ["!...", "..."]         key points; a leading "!" marks a required one
        h, fu, m, s                hints, follow-ups, misconceptions, strong-answer traits
        r: [other_track]           more round types it may be asked under

    Everything else (weights, ids, provenance) comes from the file's header, so
    a file of drafted items cannot have one item claim to be curated.
    """
    track = raw["track"]
    provenance = raw.get("provenance", "generated")
    approved = bool(raw.get("scored_use_approved", False)) and provenance != "generated"
    items: dict[str, dict] = {}
    for label, item in (raw.get("items") or {}).items():
        concepts = [c if c.startswith("concept:") else f"concept:{c}" for c in item["c"]]
        kind = item.get("t", "conceptual")
        band = item.get("d", "core")
        items[label] = {
            "stem": item["q"],
            "modality": "verbal",
            "round_types": [track, *item.get("r", [])],
            "difficulty_band": band,
            "time_budget_s": item.get(
                "time", COMPACT_TIME_BY_TYPE.get(kind, COMPACT_TIME.get(band, 240))
            ),
            "concepts": [
                {"id": c, "weight": 0.7 if i == 0 else 0.15} for i, c in enumerate(concepts[:3])
            ],
            "reference_answer": item["a"],
            "key_points": [
                {
                    "id": f"kp_{n + 1}",
                    "statement": kp.lstrip("!").strip(),
                    "required": kp.startswith("!"),
                }
                for n, kp in enumerate(item.get("k") or [])
            ],
            "hint_ladder": list(item.get("h") or []),
            "follow_ups": list(item.get("fu") or []),
            "question_type": kind,
            "facet": item.get("f"),
            "misconceptions": (
                [item["m"]] if isinstance(item.get("m"), str) else list(item.get("m") or [])
            ),
            "strong_answer": list(item.get("s") or []),
            "provenance": provenance,
            "scored_use_approved": approved,
            "theta_eligible": approved,
        }
    return {"items": items}


def load_file(path: Path, *, known: set[str]) -> list[Question]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("format") == "compact":
        raw = expand_compact(raw)
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

    # Human decisions are replayed over the freshly parsed YAML, so a boot
    # never quietly un-approves (or un-rejects) what a reviewer decided.
    from . import review

    replayed = review.store().replay(questions)
    if replayed:
        log.info("bank: replayed %d review decisions", replayed)

    _cached = Bank(questions=questions, playlist=playlist, by_label=labels)
    return _cached


def _label_of(path: Path, question: Question) -> str:
    return f"{path.stem}:{question.stem[:32]}"


__all__ = ["BANK_DIR", "Bank", "BankError", "item_id", "load", "load_file"]
