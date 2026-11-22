"""Which drafted questions students are actually asked (good_and_bads #4, 2026-11-22).

The review queue was ordered by track, concept and id: the order the bank was
written in. But since 30 Oct, 60 of 85 answers in M06 were to drafts nobody had
reviewed — so they counted for nothing — while the queue started on drafts no
student had met. Reviewing by USE puts first the drafts students keep meeting,
so an hour of a reviewer's time turns the most answers into scored ones.

This module is the only thing that knows: M06 asks it for every question
(`/questions/select`), so each draft it serves is appended here. Append-only
JSONL beside the review log, for the same reason (review.py): a count kept in
memory is lost on restart; a log replayed at load is not.

A count, never a name: a line says which item was served and when, not to whom.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

LOG_ENV = "M05_USAGE_LOG"
DEFAULT_LOG = Path(__file__).resolve().parents[1] / "data" / "usage_log.jsonl"

_lock = threading.Lock()
_cache: tuple[tuple[str, float, int], Counter[str]] | None = None


def path() -> Path:
    return Path(os.environ.get(LOG_ENV) or DEFAULT_LOG)


def record(question_id: str, round_type: str | None = None, *, at: datetime | None = None) -> None:
    """One draft served. Never raises: a count is not worth a failed interview."""
    line = {
        "question_id": str(question_id),
        "round_type": round_type,
        "at": (at or datetime.now(UTC)).isoformat(),
    }
    try:
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with _lock, target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
    except OSError as exc:
        log.warning("M05: usage not recorded for %s: %s", question_id, exc)


def counts() -> Counter[str]:
    """Times each question was served, read from the log (cached by mtime)."""
    global _cache
    target = path()
    try:
        info = target.stat()
    except OSError:
        return Counter()
    # Which file, when and how long: a log moved, or two written in the same
    # instant, is not served another's counts.
    stamp = (str(target), info.st_mtime, info.st_size)
    if _cache is not None and _cache[0] == stamp:
        return _cache[1]
    found: Counter[str] = Counter()
    with target.open(encoding="utf-8") as fh:
        for raw in fh:
            try:
                found[str(json.loads(raw)["question_id"])] += 1
            except (ValueError, KeyError, TypeError):
                continue
    _cache = (stamp, found)
    return found
