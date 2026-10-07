"""Draft questions for every concept that has too few, by track (2026-10-07).

    python -m backend_M05_Question_Intelligence.jobs.draft_items [--per-concept 2]
        [--track ml_verbal] [--limit 40] [--dry-run]

Why this exists: the bank was twelve seed items, eleven of them DSA. Every
interview drew from the same handful, and asking for a machine-learning
interview gave DSA, because there was nothing else to ask. The seed file says
what the bank is meant to be — 1,200 items by Phase-1 exit — and that
authoring "is the long pole and it has no code dependency".

**Drafted, not curated.** Every item written here is `provenance: generated`,
`scored_use_approved: false` and `theta_eligible: false`. FR-5.6 requires a
human to approve a generated item before it is used for a score, and a YAML
file is not that human (`bank.py` refuses one that claims otherwise). Until
someone approves them, these items can be practised but not scored.

**The track comes from the ontology's own sections.** Each concept sits under
a heading in M04's file ("CS core · operating systems", "ML · deep learning");
`SECTION_TRACK` maps a heading to the round type its questions are asked in.
Nothing here lists concepts.

**The house style is the seed bank's own** (`bank/dsa_verbal.yaml`'s header):
difficulty is the concept's depth, not the answer's length; key points are
statements that can be entailed or not; the reference answer is a good
answer, not the only one; the first concept is primary, two secondaries at
most.

It resumes: a concept that already has enough items is skipped, so a run that
hits the provider's daily limit is continued by running it again.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import yaml

from ..bank import BANK_DIR
from ..ontology import SNAPSHOT

#: An ontology heading -> the round type its concepts are asked in. First
#: match wins, so the narrower heading comes first.
SECTION_TRACK: list[tuple[str, str]] = [
    ("DSA ·", "dsa_verbal"),
    ("CS core · operating systems", "os_verbal"),
    ("CS core · databases", "dbms_verbal"),
    ("CS core · networks", "cn_verbal"),
    ("CS core · OOP", "oop_verbal"),
    ("CS core · systems", "systems_verbal"),
    ("Communication", "behavioural"),
    ("ML · deep learning", "dl_verbal"),
    ("ML ·", "ml_verbal"),
]

#: What kind of round each track is, for the writer.
TRACK_ROUND: dict[str, str] = {
    "dsa_verbal": "a spoken data structures and algorithms round",
    "os_verbal": "a spoken operating systems round",
    "dbms_verbal": "a spoken databases round (DBMS concepts and SQL, said aloud)",
    "cn_verbal": "a spoken computer networks round",
    "oop_verbal": "a spoken object-oriented programming and language fundamentals round",
    "systems_verbal": "a spoken computer systems and engineering practice round",
    "behavioural": (
        "a behavioural (HR) round: questions about the candidate's own experiences, "
        "judged on how they structure and support the answer, never on facts"
    ),
    "ml_verbal": "a spoken machine learning round",
    "dl_verbal": "a spoken deep learning round",
}

_HEADING = re.compile(r"^\s*#\s*─+\s*(.+?)\s*─+\s*$")
_CONCEPT = re.compile(r"^\s*-\s*id:\s*(concept:[a-z0-9_]+)\s*$")

SYSTEM = """You write questions for the question bank of a mock placement-interview platform for engineering students in India. An interviewer asks each question ALOUD and the student answers aloud: no code editor, no whiteboard, two to four minutes.

House style — follow every rule:
- The stem is one or two spoken sentences, at most 40 words, concrete and answerable in 2-4 minutes. No lists of sub-questions, no "explain everything about X".
- Vary the angle across items: why something holds, compare and contrast, a scenario ("in production you see X — what is happening?"), a trade-off, or debugging.
- difficulty_band is the depth of the CONCEPT being tested (intro, core, hard), never how long the answer takes. A question that is hard only because its wording is unclear is a badly written question.
- key_points: 2 to 4 statements, each one a claim that an answer either makes or does not ("Explains that a collision sends two keys to one bucket"), never a topic ("collisions"). Mark the essential ones required.
- reference_answer: a good spoken answer of 60 to 140 words — a good answer, not the only correct one.
- hints: one or two nudges that point the way without giving the answer.
- secondary_concepts: at most two, ONLY from the list given, and only if the question genuinely also tests them.
- Original wording. Do not copy questions from well-known question banks.
- For a behavioural round: ask about the student's OWN experience (projects, teams, internships, college). Key points describe what a strong answer shows — a specific situation, what THEY did, a result, ideally a number — never facts.
- If this concept cannot sensibly be asked about in this kind of round, return an empty items list."""  # noqa: E501

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "label",
                    "stem",
                    "difficulty_band",
                    "time_budget_s",
                    "secondary_concepts",
                    "reference_answer",
                    "key_points",
                    "hints",
                ],
                "properties": {
                    "label": {"type": "string"},
                    "stem": {"type": "string"},
                    "difficulty_band": {"type": "string", "enum": ["intro", "core", "hard"]},
                    "time_budget_s": {"type": "integer"},
                    "secondary_concepts": {"type": "array", "items": {"type": "string"}},
                    "reference_answer": {"type": "string"},
                    "key_points": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["statement", "required"],
                            "properties": {
                                "statement": {"type": "string"},
                                "required": {"type": "boolean"},
                            },
                        },
                    },
                    "hints": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


def concept_tracks(text: str) -> dict[str, str]:
    """concept id -> round type, from the headings the ontology is written under."""
    out: dict[str, str] = {}
    track: str | None = None
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            title = heading.group(1)
            track = next((t for prefix, t in SECTION_TRACK if title.startswith(prefix)), None)
            continue
        concept = _CONCEPT.match(line)
        if concept and track:
            out[concept.group(1)] = track
    return out


def load_keys() -> None:
    """keys.txt beside the repos into the environment — names only, never values."""
    for parent in Path(__file__).resolve().parents:
        for name in ("Final_Year_Project/keys.txt", "keys.txt"):
            path = parent / name
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    match = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=\s*(.+?)\s*$", line)
                    if match and match.group(1) not in os.environ:
                        os.environ[match.group(1)] = match.group(2).strip().strip('"')
                return


def existing_items() -> dict[str, list[str]]:
    """concept id -> the stems the bank already has for it (any file)."""
    stems: dict[str, list[str]] = {}
    for path in sorted(BANK_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for entry in (raw.get("items") or {}).values():
            concepts = entry.get("concepts") or []
            if not concepts:
                continue
            first = concepts[0]["id"] if isinstance(concepts[0], dict) else concepts[0]
            stems.setdefault(first, []).append(" ".join(str(entry.get("stem", "")).split()))
    return stems


class Writer:
    """One structured call per concept, rotating the provider's keys."""

    def __init__(self) -> None:
        from ai_core.models import resolve

        route = resolve("generation")
        if not route:
            raise SystemExit(f"no model to draft with: {route.unusable}")
        assert route.provider is not None
        self.url = f"{route.provider.base_url}/chat/completions"
        self.model = route.model
        self.keys = route.keys
        self.turn = 0

    def draft(self, user: str) -> list[dict]:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "items", "schema": SCHEMA, "strict": True},
            },
            "temperature": 0.7,
            "max_completion_tokens": 4000,
            "reasoning_effort": "low",
        }
        for attempt in range(8):
            key = self.keys[self.turn % len(self.keys)]
            self.turn += 1
            request = urllib.request.Request(
                self.url,
                data=json.dumps(body).encode(),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "User-Agent": "ai-interviewer-m05-drafting/1",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    data = json.loads(response.read())
                content = data["choices"][0]["message"]["content"]
                return list(json.loads(content).get("items") or [])
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:200]
                if exc.code == 429:
                    wait = float(exc.headers.get("retry-after") or 20)
                    if "tokens per day" in detail or "TPD" in detail:
                        if attempt >= len(self.keys):
                            raise SystemExit(
                                "every key is at its daily limit; run again tomorrow"
                            ) from None
                        continue
                    time.sleep(min(wait, 90))
                    continue
                print(f"    HTTP {exc.code}: {detail}", flush=True)
                time.sleep(5)
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                print(f"    {type(exc).__name__}: {str(exc)[:120]}", flush=True)
                time.sleep(5)
        return []


#: The model writes non-breaking hyphens (U+2011) in "trade-off" and
#: "credit-card": 1,445 of them in the first pass. They look right on screen
#: and are a character the interviewer's voice has to guess at.
HYPHENS = {0x2010: "-", 0x2011: "-"}


def _flat(value: object) -> str:
    return " ".join(str(value).translate(HYPHENS).split())


def valid(item: dict, allowed: set[str], seen: list[str]) -> dict | None:
    """The item as the bank stores it, or None when it breaks the house style."""
    stem = _flat(item.get("stem", ""))
    words = len(stem.split())
    if not 6 <= words <= 60:
        return None
    if any(difflib.SequenceMatcher(None, stem.lower(), s.lower()).ratio() > 0.75 for s in seen):
        return None
    answer = _flat(item.get("reference_answer", ""))
    if not 25 <= len(answer.split()) <= 240:
        return None
    points = [
        kp for kp in item.get("key_points") or [] if len(str(kp.get("statement", "")).split()) >= 4
    ][:5]
    if len(points) < 2:
        return None
    if not any(kp.get("required") for kp in points):
        points[0]["required"] = True
    secondaries = [c for c in item.get("secondary_concepts") or [] if c in allowed][:2]
    return {
        "stem": stem,
        "difficulty_band": item.get("difficulty_band", "core"),
        "time_budget_s": max(120, min(420, int(item.get("time_budget_s") or 240))),
        "secondaries": secondaries,
        "reference_answer": answer,
        "key_points": [
            {"statement": _flat(kp["statement"]), "required": bool(kp["required"])}
            for kp in points
        ],
        "hints": [_flat(h) for h in (item.get("hints") or [])][:2],
        "label": re.sub(r"[^a-z0-9]+", "_", str(item.get("label", "")).lower()).strip("_")[:40]
        or "item",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--per-concept", type=int, default=2, help="items each concept should have")
    parser.add_argument("--track", action="append", help="only these round types")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many concepts")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_keys()
    text = SNAPSHOT.read_text(encoding="utf-8")
    ontology = yaml.safe_load(text) or {}
    concepts = {c["id"]: c for c in ontology.get("concepts") or []}
    tracks = concept_tracks(text)
    stems = existing_items()
    # ML and CS core first: the tracks students asked for and could not get.
    order = [
        "ml_verbal",
        "dl_verbal",
        "os_verbal",
        "dbms_verbal",
        "cn_verbal",
        "oop_verbal",
        "systems_verbal",
        "dsa_verbal",
        "behavioural",
    ]
    todo = [
        cid
        for track in order
        if not args.track or track in args.track
        for cid in concepts
        if tracks.get(cid) == track and len(stems.get(cid, [])) < args.per_concept
    ]
    print(
        f"{len(todo)} concepts need items (of {len(concepts)}); writing with "
        f"{'nothing (dry run)' if args.dry_run else 'the generation tier'}",
        flush=True,
    )
    if args.dry_run:
        for cid in todo:
            print(f"  {tracks[cid]:15s} {cid}  has {len(stems.get(cid, []))}")
        return

    writer = Writer()
    done = 0
    for cid in todo:
        if args.limit and done >= args.limit:
            break
        concept = concepts[cid]
        track = tracks[cid]
        need = args.per_concept - len(stems.get(cid, []))
        related = {p["id"] for p in concept.get("prerequisites") or []}
        related |= {c for c, t in tracks.items() if t == track and c != cid}
        user = (
            f"ROUND: {TRACK_ROUND[track]}\n"
            f"CONCEPT: {concept['name']} ({cid}), level {concept.get('level')}\n"
            f"ALSO CALLED: {', '.join(concept.get('aliases') or [])}\n"
            f"WRITE: {need} item(s), each from a different angle.\n"
            f"SECONDARY CONCEPTS YOU MAY TAG: {', '.join(sorted(related)) or '(none)'}\n"
            f"QUESTIONS ALREADY IN THE BANK FOR THIS CONCEPT (do not repeat their angle):\n"
            + "\n".join(f"- {s}" for s in stems.get(cid, []))
            or "- (none)"
        )
        started = time.time()
        drafted = writer.draft(user)
        kept = []
        for raw in drafted:
            item = valid(raw, related, stems.get(cid, []) + [k["stem"] for k in kept])
            if item:
                kept.append(item)
        write(track, cid, kept[:need], writer.model)
        stems.setdefault(cid, []).extend(k["stem"] for k in kept[:need])
        done += 1
        print(
            f"  {track:15s} {cid}: {len(kept[:need])} of {need} kept "
            f"({len(drafted)} drafted, {time.time() - started:.0f}s)",
            flush=True,
        )


def write(track: str, cid: str, items: list[dict], model: str) -> None:
    """Append to `bank/<track>.drafted.yaml`, keyed so a re-run never collides."""
    if not items:
        return
    path = BANK_DIR / f"{track}.drafted.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    raw = raw or {"items": {}}
    short = cid.split(":", 1)[1]
    for item in items:
        label = f"{short}__{item['label']}"
        n = 2
        while label in raw["items"]:
            label = f"{short}__{item['label']}_{n}"
            n += 1
        raw["items"][label] = {
            "stem": item["stem"],
            "modality": "verbal",
            "round_types": [track],
            "difficulty_band": item["difficulty_band"],
            "time_budget_s": item["time_budget_s"],
            "concepts": [{"id": cid, "weight": 0.7}]
            + [{"id": s, "weight": 0.15} for s in item["secondaries"]],
            "reference_answer": item["reference_answer"],
            "key_points": [
                {"id": f"kp_{i + 1}", "statement": kp["statement"], "required": kp["required"]}
                for i, kp in enumerate(item["key_points"])
            ],
            "hint_ladder": item["hints"],
            # FR-5.6: drafted by a model, so not scored until a person approves.
            "provenance": "generated",
            "scored_use_approved": False,
            "theta_eligible": False,
            "drafted_by": model,
            "drafted_at": date.today().isoformat(),
        }
    header = (
        f"# DRAFTED — {track}. Written by jobs/draft_items.py with a model; NOT reviewed.\n"
        "# provenance: generated + scored_use_approved: false on every item: FR-5.6 needs a\n"
        "# person to approve an item before it counts toward a score. Practise only until then.\n\n"
    )
    path.write_text(
        header + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
