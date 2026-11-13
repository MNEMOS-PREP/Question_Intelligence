"""Draft questions for the competencies career goals need and the bank lacks (2026-11-13).

    python -m backend_M05_Question_Intelligence.jobs.fill_gaps [--min 4] [--limit 20]
        [--track frontend_verbal] [--dry-run]

M22 (Follow Your Goal) turns a student's goal into competencies, and its
`GET /v1/goals/question-gaps` lists the ones any role in its catalogue needs
that this bank holds too few questions for: too few in all, a difficulty band
missing, or only one kind of question. That list is computed from this
module's own `/v1/bank/coverage`, so it is never a copy that drifts.

This job drafts for those gaps, worst first, with `draft_items.py`'s writer,
house style and checks. Everything it writes is `provenance: generated` and
`scored_use_approved: false` — FR-5.6: practised, never scored, until a
reviewer approves it in the queue. It resumes: a gap that is filled drops off
M22's list, so running it again continues where a daily limit stopped it.

The round each track is asked in comes from `bank/tracks.yaml` (its title and
blurb), so a track added there is draftable here without an edit.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

import yaml

from .. import bank as bank_module
from ..bank import BANK_DIR
from ..ontology import SNAPSHOT
from .draft_items import TRACK_ROUND, Writer, load_keys, valid, write

#: Where M22 answers. Its PORTS.txt port; override without editing.
M22_BASE_URL = os.getenv("M22_BASE_URL", "http://127.0.0.1:8122")


def fetch_gaps(min_per_concept: int, base_url: str = M22_BASE_URL) -> dict[str, Any]:
    """M22's gap list, asked as a service (the route is staff or service only)."""
    from ai_core import service

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/goals/question-gaps?min_per_concept={min_per_concept}",
        headers={"Accept": "application/json", **service.headers()},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"M22 did not give its gap list ({base_url}): {exc}") from None


def round_words(track: str) -> str:
    """How the writer is told what round this is: draft_items' own words for the
    tracks it knows, otherwise `tracks.yaml`'s title and blurb."""
    if track in TRACK_ROUND:
        return TRACK_ROUND[track]
    meta = yaml.safe_load((BANK_DIR / "tracks.yaml").read_text(encoding="utf-8")) or {}
    info = (meta.get("tracks") or {}).get(track) or {}
    title = str(info.get("title") or track.replace("_verbal", "").replace("_", " "))
    blurb = str(info.get("blurb") or "").strip()
    kind = "behavioural (HR)" if info.get("kind") == "behavioural" else "spoken"
    return f"a {kind} {title.lower()} round" + (f": {blurb}" if blurb else "")


def bank_stems() -> tuple[dict[str, list[str]], dict[str, set[str]]]:
    """(concept -> stems already asked about it, track -> concepts it holds),
    from the loaded bank — every file format, compact goal banks included."""
    stems: dict[str, list[str]] = {}
    held: dict[str, set[str]] = {}
    for question in bank_module.load(refresh=True).questions:
        stems.setdefault(question.primary_concept, []).append(" ".join(question.stem.split()))
        for track in question.round_types:
            held.setdefault(track, set()).add(question.primary_concept)
    return stems, held


def prompt(concept: dict, gap: dict, need: int, related: set[str], stems: list[str]) -> str:
    bands = gap.get("missing_difficulties") or []
    types = gap.get("types") or []
    angle = []
    if bands:
        angle.append(
            f"The bank has nothing at difficulty {', '.join(bands)} for it: "
            "write at least one there."
        )
    if len(types) < 2:
        have = types[0] if types else "none"
        angle.append(f"Its questions so far are one kind ({have}): use other angles.")
    return (
        f"ROUND: {round_words(gap['track'])}\n"
        f"CONCEPT: {concept['name']} ({concept['id']}), level {concept.get('level')}\n"
        f"ALSO CALLED: {', '.join(concept.get('aliases') or [])}\n"
        f"NEEDED BY: {gap.get('roles', 0)} career role(s) students set as goals.\n"
        f"WRITE: {need} item(s), each from a different angle. {' '.join(angle)}\n"
        f"SECONDARY CONCEPTS YOU MAY TAG: {', '.join(sorted(related)) or '(none)'}\n"
        "QUESTIONS ALREADY IN THE BANK FOR THIS CONCEPT (do not repeat their angle):\n"
        + ("\n".join(f"- {s}" for s in stems) or "- (none)")
    )


def plan(
    gaps: list[dict], *, minimum: int, tracks: list[str] | None, limit: int
) -> list[tuple[dict, int]]:
    """(gap, items to write) worst first: fewest questions, then most roles."""
    todo = []
    for gap in gaps:
        if tracks and gap.get("track") not in tracks:
            continue
        have = int(gap.get("questions") or 0)
        need = max(minimum - have, 1 if gap.get("missing_difficulties") else 0)
        if need > 0:
            todo.append((gap, min(need, 3)))
    return todo[:limit] if limit else todo


def run(
    *,
    minimum: int,
    tracks: list[str] | None,
    limit: int,
    dry_run: bool,
    gaps_source: Callable[[int], dict] = fetch_gaps,
    writer_factory: Callable[[], Any] = Writer,
) -> dict[str, int]:
    body = gaps_source(minimum)
    if not body.get("bank_available", True):
        raise SystemExit(
            "M22 could not read this bank's coverage, so its gap list is empty. Start M05 first."
        )
    todo = plan(body.get("gaps") or [], minimum=minimum, tracks=tracks, limit=limit)
    print(
        f"{len(todo)} of {len(body.get('gaps') or [])} gaps to fill "
        f"({body.get('concepts_needed')} competencies needed)"
    )
    if dry_run:
        for gap, need in todo:
            missing = ",".join(gap.get("missing_difficulties") or []) or "-"
            print(
                f"  {gap['track']:22s} {gap['concept_id']:45s} "
                f"has {gap['questions']}, write {need} (no {missing})"
            )
        return {"planned": len(todo), "written": 0}

    load_keys()
    ontology = {
        c["id"]: c
        for c in (yaml.safe_load(SNAPSHOT.read_text(encoding="utf-8")) or {}).get("concepts") or []
    }
    stems, held = bank_stems()
    writer = writer_factory()
    written = 0
    for gap, need in todo:
        cid, track = gap["concept_id"], gap["track"]
        concept = ontology.get(cid)
        if (
            concept is None
        ):  # M22 names only M04's ids; a stale snapshot here is the one way to miss
            print(
                f"  skip {cid}: not in this module's ontology snapshot "
                "(run jobs/refresh_ontology.py)"
            )
            continue
        related = {p["id"] for p in concept.get("prerequisites") or []} | (
            held.get(track, set()) - {cid}
        )
        drafted = writer.draft(prompt(concept, gap, need, related, stems.get(cid, [])))
        kept: list[dict] = []
        for raw in drafted:
            item = valid(raw, related, stems.get(cid, []) + [k["stem"] for k in kept])
            if item:
                kept.append(item)
        write(track, cid, kept[:need], getattr(writer, "model", "unknown"))
        stems.setdefault(cid, []).extend(k["stem"] for k in kept[:need])
        written += len(kept[:need])
        print(
            f"  {track:22s} {cid}: {len(kept[:need])} of {need} kept ({len(drafted)} drafted)",
            flush=True,
        )
    return {"planned": len(todo), "written": written}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--min", type=int, default=4, help="questions each needed competency should have"
    )
    parser.add_argument("--track", action="append", help="only these round types")
    parser.add_argument(
        "--limit", type=int, default=20, help="stop after this many competencies (0: all)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list the gaps; write nothing, call no model"
    )
    args = parser.parse_args()
    run(minimum=args.min, tracks=args.track, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
