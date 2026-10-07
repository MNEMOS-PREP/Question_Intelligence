"""Refresh M05's ontology snapshot from M04's file.

    python -m backend_M05_Question_Intelligence.jobs.refresh_ontology [PATH]

M04 owns the ontology (`packages/knowledge/ontology/concepts.yaml` in the
Memory repo); M05 keeps a snapshot so it can clone and run alone (spec 6.11).
The snapshot is this module's own header, then M04's file exactly. PATH
defaults to the Memory repo checked out beside this one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from ..ontology import SNAPSHOT

#: The snapshot's own header ends at this line; M04's file follows it.
HEADER_END = "#  Refresh with:  jobs/refresh_ontology.py\n"


def sibling_ontology() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "Memory" / "packages" / "knowledge" / "ontology" / "concepts.yaml"
        if candidate.exists():
            return candidate
    raise SystemExit("M04's ontology was not found beside this repo; pass its path.")


def refresh(source: Path) -> int:
    text = source.read_text(encoding="utf-8")
    count = len((yaml.safe_load(text) or {}).get("concepts") or [])
    if not count:
        raise SystemExit(f"{source} declares no concepts; the snapshot is left alone.")
    current = SNAPSHOT.read_text(encoding="utf-8")
    cut = current.index(HEADER_END) + len(HEADER_END)
    header = current[:cut]
    # The header's closing rule, then M04's file as it is.
    SNAPSHOT.write_text(f"{header}{'#' + ' ' + '=' * 77}\n\n{text}", encoding="utf-8")
    return count


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else sibling_ontology()
    print(f"snapshot refreshed from {path}: {refresh(path)} concepts")
