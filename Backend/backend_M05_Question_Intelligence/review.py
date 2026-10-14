"""The human review queue — FR-5.6, spec §6.7.

A drafted item may not be used in a scored context until a person has read it.
Selection already refuses an item that is not `active` and `scored_use_approved`
(`selection.py`); this module is the only thing that moves an item across that
line, and it does so by writing a decision to an append-only log.

**The log is the source of truth, not the YAML.** The bank is authored in YAML
files that are re-read at every boot. A decision held only in memory would be
lost on restart and the item would silently fall back to whatever the file says.
So decisions are appended to a JSONL file, replayed over the bank at load, and
never rewritten. An approval is therefore an auditable fact — who, when, what
they changed and why — which is exactly what the M13 human-agreement chapter
needs and what an ethics reviewer will ask for.

**A rejection needs a reason.** A bare "no" is data that cannot be learned from:
G3 failures are how a concept's generation prompt gets fixed (EC-5.7).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ai_core.identity import Principal, Role

from . import ontology as ontology_module
from .contracts import DifficultyBand, ItemStatus, KeyPoint, Provenance, Question

log = logging.getLogger(__name__)

#: Who may decide: the dedicated reviewer role (faculty, seniors) plus staff.
REVIEWER_ROLES = frozenset({Role.admin, Role.placement_officer, Role.reviewer})

LOG_ENV = "M05_REVIEW_LOG"
DEFAULT_LOG = Path(__file__).resolve().parents[1] / "data" / "review_log.jsonl"

#: What a reviewer may change. Concepts, provenance and round types are
#: deliberately absent: they decide what M04 believes about a student, and that
#: is the ontology's review, not this one's.
EDITABLE = ("stem", "reference_answer", "key_points", "difficulty_band", "time_budget_s")

Action = Literal["approve", "edit", "reject"]

_DUP_THRESHOLD = 0.8


class ReviewError(ValueError):
    """The decision cannot be applied. Carries a message safe to show a reviewer."""


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


def log_path() -> Path:
    return Path(os.environ.get(LOG_ENV) or DEFAULT_LOG)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def track_of(question: Question) -> str:
    """The reviewer's unit of progress: the track (round type) a student picks.

    Matches `bank/tracks.yaml` and `GET /v1/bank/tracks`, so "DSA: 93 drafts"
    on the review page is the same number a student's setup page counts against.
    """
    return question.round_types[0]


def automatic_checks(question: Question, others: list[Question]) -> list[Check]:
    """The cheap local gates, recomputed on read so they can never be stale.

    G2/G3 (answerability, reference correctness) need a model call and are not
    run here — saying so in the payload is the point: a reviewer must know the
    reference answer has NOT been machine-checked and is theirs to verify.
    """
    known = ontology_module.load().ids()
    checks = [
        Check(
            "schema",
            len(question.key_points) >= 2 and bool(question.reference_answer.strip()),
            f"{len(question.key_points)} key points",
        ),
        Check(
            "ontology",
            all(c.concept_id in known for c in question.concepts),
            ", ".join(c.concept_id for c in question.concepts),
        ),
    ]
    mine = _tokens(question.stem)
    closest, score = None, 0.0
    for other in others:
        if other.id == question.id:
            continue
        s = _jaccard(mine, _tokens(other.stem))
        if s > score:
            closest, score = other, s
    checks.append(
        Check(
            "uniqueness",
            score < _DUP_THRESHOLD,
            f"closest stem {score:.0%} similar"
            + (f" to “{closest.stem[:60]}”" if closest and score >= 0.5 else ""),
        )
    )
    checks.append(
        Check(
            "grounding_scope",
            question.provenance is not Provenance.grounded,
            "grounded items are per-candidate and are never queued for scored use",
        )
    )
    return checks


class ReviewStore:
    """In-process queue state plus the on-disk log. One per bank."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path or log_path()

    # ── log ──────────────────────────────────────────────────────────────

    def history(self, question_id: str | None = None) -> list[dict[str, Any]]:
        path = self.path
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # A torn final line after a crash must not take the queue down.
                log.warning("review log: skipping unreadable line")
                continue
            if question_id is None or record.get("question_id") == question_id:
                out.append(record)
        return out

    def _append(self, record: dict[str, Any]) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ── replay ───────────────────────────────────────────────────────────

    def replay(self, questions: list[Question]) -> int:
        """Re-apply every logged decision over the freshly loaded bank."""
        by_id = {str(q.id): q for q in questions}
        applied = 0
        for record in self.history():
            question = by_id.get(record.get("question_id", ""))
            if question is None:
                continue
            try:
                _apply(question, record["action"], record.get("changes") or {})
                applied += 1
            except (ReviewError, KeyError) as exc:
                log.warning("review log: skipped %s — %s", record.get("question_id"), exc)
        return applied

    # ── decide ───────────────────────────────────────────────────────────

    def decide(
        self,
        question: Question,
        *,
        action: Action,
        principal: Principal,
        reason: str = "",
        changes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if principal.role not in REVIEWER_ROLES:
            raise PermissionError("only staff may review questions")
        if question.provenance is Provenance.grounded:
            raise ReviewError("grounded items are per-candidate and are not reviewable here")
        reason = reason.strip()
        changes = dict(changes or {})
        if action == "reject" and not reason:
            raise ReviewError("a rejection needs a reason — it is how the generator gets fixed")
        if action == "edit" and not changes:
            raise ReviewError("an edit with no changes is not an edit")

        with self._lock:
            before = _snapshot(question)
            _apply(question, action, changes)  # validates; raises before any log write
            diff = {
                k: [before[k], _snapshot(question)[k]]
                for k in EDITABLE
                if before[k] != _snapshot(question)[k]
            }
            record = {
                "ts": datetime.now(UTC).isoformat(),
                "question_id": str(question.id),
                "action": action,
                "reviewer": principal.subject,
                "role": principal.role.value,
                "reason": reason,
                "changes": changes,
                "diff": diff,
                "status_after": question.status.value,
                "scored_use_approved_after": question.scored_use_approved,
            }
            try:
                self._append(record)
            except OSError:
                # An approval that is not on disk is one that vanishes at the
                # next boot while a student has already been scored against it.
                _restore(question, before)
                raise
        return record


def _snapshot(question: Question) -> dict[str, Any]:
    return {
        "stem": question.stem,
        "reference_answer": question.reference_answer,
        "key_points": [kp.model_dump() for kp in question.key_points],
        "difficulty_band": question.difficulty_band.value,
        "time_budget_s": question.time_budget_s,
        "status": question.status,
        "scored_use_approved": question.scored_use_approved,
    }


def _restore(question: Question, snap: dict[str, Any]) -> None:
    question.stem = snap["stem"]
    question.reference_answer = snap["reference_answer"]
    question.key_points = [KeyPoint(**kp) for kp in snap["key_points"]]
    question.difficulty_band = DifficultyBand(snap["difficulty_band"])
    question.time_budget_s = snap["time_budget_s"]
    question.status = snap["status"]
    question.scored_use_approved = snap["scored_use_approved"]


def _apply(question: Question, action: str, changes: dict[str, Any]) -> None:
    """Mutate `question`, all-or-nothing."""
    snap = _snapshot(question)
    try:
        unknown = set(changes) - set(EDITABLE)
        if unknown:
            raise ReviewError(f"not editable in review: {', '.join(sorted(unknown))}")
        if "stem" in changes:
            stem = str(changes["stem"]).strip()
            if not stem:
                raise ReviewError("stem cannot be empty")
            question.stem = stem
        if "reference_answer" in changes:
            ref = str(changes["reference_answer"]).strip()
            if not ref:
                raise ReviewError("reference answer cannot be empty")
            question.reference_answer = ref
        if "key_points" in changes:
            raw = changes["key_points"]
            points = [
                KeyPoint(
                    id=kp.get("id") or f"kp_{n + 1}",
                    statement=str(kp["statement"]).strip(),
                    weight=kp.get("weight", 1.0),
                    required=kp.get("required", False),
                )
                for n, kp in enumerate(raw)
                if isinstance(kp, dict) and str(kp.get("statement", "")).strip()
            ]
            if len(points) < 2:
                raise ReviewError("at least 2 key points are needed (M13 scores coverage)")
            question.key_points = points
        if "difficulty_band" in changes:
            try:
                question.difficulty_band = DifficultyBand(changes["difficulty_band"])
            except ValueError:
                raise ReviewError("unknown difficulty band") from None
        if "time_budget_s" in changes:
            budget = int(changes["time_budget_s"])
            if not 30 <= budget <= 1800:
                raise ReviewError("time budget must be 30–1800 seconds")
            question.time_budget_s = budget

        if action == "approve":
            if len(question.key_points) < 2 or not question.reference_answer.strip():
                raise ReviewError("cannot approve an item without a reference and 2 key points")
            question.status = ItemStatus.active
            question.scored_use_approved = True
        elif action == "reject":
            question.status = ItemStatus.retired
            question.scored_use_approved = False
        elif action == "edit":
            question.status = ItemStatus.in_review
            question.scored_use_approved = False
        else:
            raise ReviewError(f"unknown action {action!r}")
    except Exception:
        _restore(question, snap)
        raise


def in_queue(question: Question) -> bool:
    return (
        not question.scored_use_approved
        and question.status not in (ItemStatus.retired, ItemStatus.broken)
        and question.provenance is not Provenance.grounded
    )


_store = ReviewStore()


def store() -> ReviewStore:
    return _store


__all__ = [
    "EDITABLE",
    "REVIEWER_ROLES",
    "Check",
    "ReviewError",
    "ReviewStore",
    "automatic_checks",
    "in_queue",
    "store",
    "track_of",
]
