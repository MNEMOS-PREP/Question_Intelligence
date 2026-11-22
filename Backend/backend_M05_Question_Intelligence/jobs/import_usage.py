"""Seed the usage log (usage.py) from the interviews already held.

The log starts counting the day it ships; M06 has asked drafts since October.
This reads M06's own record — every question an interviewer asked from an
unreviewed draft — and appends one usage line per asking, so the review queue
is ordered by use from the first day rather than after weeks of new sessions.

    python -m backend_M05_Question_Intelligence.jobs.import_usage <path to M06's dev.db>

Read-only on M06's database. Run it once: running it again counts twice.
"""

from __future__ import annotations

import sqlite3
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .. import usage


def main(m06_db: str) -> int:
    con = sqlite3.connect(f"file:{Path(m06_db).as_posix()}?mode=ro", uri=True)
    rows = con.execute(
        "select question_id, rubric_round_type, at from m06_turn "
        "where role = 'interviewer' and question_source = 'm05_draft' "
        "and probe_depth = 0 and question_id is not null order by at"
    ).fetchall()
    for question_id, round_type, at in rows:
        when = datetime.fromisoformat(str(at))
        when = when if when.tzinfo else when.replace(tzinfo=UTC)
        usage.record(_uuid(question_id), round_type, at=when)
    print(f"{len(rows)} askings of {len({r[0] for r in rows})} drafts appended to {usage.path()}")
    return 0


def _uuid(raw: str) -> str:
    """M06 stores ids without dashes (SQLite); M05 speaks them with."""
    try:
        return str(uuid.UUID(str(raw)))
    except ValueError:
        return str(raw)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
