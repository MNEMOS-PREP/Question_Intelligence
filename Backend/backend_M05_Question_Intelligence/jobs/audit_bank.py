"""Audit the bank's quality and coverage (2026-11-12).

    python -m backend_M05_Question_Intelligence.jobs.audit_bank [--concepts c1,c2] [--strict]

A question bank grows by drafting, and drafting repeats itself: the same
stem reworded, three "what is X" questions on one concept, a reference
answer of eight words. This is the check that runs before anything is
merged — and in the test suite — so the bank's growth stays honest:

    duplicate        two items with the same stem after normalising
    near_duplicate   two stems on one concept sharing most content words
                     (the same Jaccard the selector uses for "reads alike")
    thin_answer      a reference answer under 25 words, or over 200
    few_key_points   fewer than 2 key points, or none marked required
    bad_facet        a facet that is not one of M04's facets for the concept
    no_spread        a concept with 3+ items all at one difficulty, or all
                     of one question type

and, for the concepts asked about, coverage: items per concept, per
difficulty band and per question type.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

import yaml

from .. import bank as bank_module
from ..ontology import SNAPSHOT
from ..selection import content_words

NEAR_DUPLICATE_AT = 0.6
MIN_ANSWER_WORDS, MAX_ANSWER_WORDS = 25, 200


@dataclass
class Finding:
    code: str
    concept: str
    detail: str


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", " ".join(text.lower().split()))


def facets() -> dict[str, set[str]]:
    raw = yaml.safe_load(SNAPSHOT.read_text(encoding="utf-8")) or {}
    return {c["id"]: set(c.get("facets") or []) for c in raw.get("concepts") or []}


def audit(questions, *, only: set[str] | None = None) -> tuple[list[Finding], dict[str, dict]]:  # noqa: ANN001
    known_facets = facets()
    findings: list[Finding] = []
    by_concept: dict[str, list] = defaultdict(list)
    seen: dict[str, str] = {}
    for q in questions:
        cid = q.primary_concept
        if only and cid not in only:
            continue
        by_concept[cid].append(q)
        key = _norm(q.stem)
        if key in seen:
            detail = f"{q.stem[:60]!r} repeats {seen[key][:40]!r}"
            findings.append(Finding("duplicate", cid, detail))
        seen[key] = q.stem
        words = len(q.reference_answer.split())
        if not MIN_ANSWER_WORDS <= words <= MAX_ANSWER_WORDS:
            findings.append(Finding("thin_answer", cid, f"{words} words: {q.stem[:50]!r}"))
        if len(q.key_points) < 2 or not any(k.required for k in q.key_points):
            findings.append(Finding("few_key_points", cid, q.stem[:60]))
        if q.facet and known_facets.get(cid) and q.facet not in known_facets[cid]:
            findings.append(Finding("bad_facet", cid, f"{q.facet!r} is not a facet of {cid}"))
    coverage: dict[str, dict] = {}
    for cid, items in by_concept.items():
        for i, a in enumerate(items):
            wa = content_words(a.stem)
            for b in items[i + 1:]:
                wb = content_words(b.stem)
                if wa and wb and len(wa & wb) / len(wa | wb) >= NEAR_DUPLICATE_AT:
                    detail = f"{a.stem[:45]!r} ~ {b.stem[:45]!r}"
                    findings.append(Finding("near_duplicate", cid, detail))
        bands = Counter(q.difficulty_band.value for q in items)
        types = Counter(q.question_type.value for q in items)
        # An HR round's questions are all behavioural by nature; elsewhere one
        # type everywhere means the concept is only ever asked one way.
        one_type = len(types) < 2 and set(types) != {"behavioural"}
        if len(items) >= 3 and (len(bands) < 2 or one_type):
            findings.append(Finding("no_spread", cid, f"bands {dict(bands)}, types {dict(types)}"))
        coverage[cid] = {"items": len(items), "bands": dict(bands), "types": dict(types),
                         "facets": sorted({q.facet for q in items if q.facet})}
    return findings, coverage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--concepts", default="", help="comma-separated concept ids to audit")
    parser.add_argument("--strict", action="store_true", help="exit 1 on any finding")
    args = parser.parse_args()
    only = {c.strip() for c in args.concepts.split(",") if c.strip()} or None
    loaded = bank_module.load(refresh=True)
    findings, coverage = audit(loaded.questions, only=only)
    types = Counter(t for c in coverage.values() for t, n in c["types"].items() for _ in range(n))
    total = sum(c["items"] for c in coverage.values())
    print(f"{total} items on {len(coverage)} concepts; types {dict(types)}")
    for code, n in Counter(f.code for f in findings).most_common():
        print(f"  {n:>4}  {code}")
    for f in findings[:40]:
        print(f"  {f.code:15s} {f.concept:38s} {f.detail}")
    if args.strict and findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
