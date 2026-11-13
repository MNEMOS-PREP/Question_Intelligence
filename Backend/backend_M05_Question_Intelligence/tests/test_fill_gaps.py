"""`jobs/fill_gaps.py`: M22's gap list in, drafted (never scored) items out.

The gap list is M22's `/v1/goals/question-gaps` body, field for field; the
writer is a stand-in for the model, so nothing here calls a provider.
"""

from __future__ import annotations

import yaml

from backend_M05_Question_Intelligence.jobs import draft_items, fill_gaps

GAPS = {
    "bank_available": True,
    "concepts_needed": 300,
    "gaps": [
        {
            "concept_id": "concept:react",
            "name": "React",
            "track": "frontend_verbal",
            "roles": 6,
            "questions": 1,
            "missing_difficulties": ["hard"],
            "types": ["conceptual"],
        },
        {
            "concept_id": "concept:kafka",
            "name": "Apache Kafka",
            "track": "backend_verbal",
            "roles": 2,
            "questions": 5,
            "missing_difficulties": [],
            "types": ["conceptual", "scenario"],
        },
    ],
}


STEMS = [
    "Your React list re-renders every row when one item changes; why, and what would you change?",
    "When would you lift state up in React, and when would a context or a store be better?",
    "A useEffect that fetches data runs twice in development and loops in production. Why?",
]


class FakeWriter:
    model = "fake-model"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def draft(self, user: str) -> list[dict]:
        self.prompts.append(user)
        return [
            {
                "label": f"angle {n}",
                "stem": STEMS[n],
                "difficulty_band": "hard",
                "time_budget_s": 240,
                "secondary_concepts": ["concept:javascript", "concept:not_allowed"],
                "reference_answer": (
                    "A parent state change re-renders its children by default, and a new array or "
                    "callback each render defeats memoisation. Stable keys, memoised rows and "
                    f"stable callbacks let React skip unchanged rows; profiling confirms. Case {n}."
                ),
                "key_points": [
                    {
                        "statement": "Explains that a parent render re-renders its children",
                        "required": True,
                    },
                    {
                        "statement": "Names stable keys and memoised rows as the fix",
                        "required": False,
                    },
                ],
                "hints": ["What does React compare before it skips a child?"],
            }
            for n in range(3)
        ]


def test_the_track_is_described_from_tracks_yaml():
    words = fill_gaps.round_words("frontend_verbal")
    assert words.startswith("a spoken") and "round" in words
    assert fill_gaps.round_words("os_verbal") == draft_items.TRACK_ROUND["os_verbal"]


def test_a_gap_already_filled_is_not_planned():
    todo = fill_gaps.plan(GAPS["gaps"], minimum=4, tracks=None, limit=0)
    assert [(g["concept_id"], n) for g, n in todo] == [("concept:react", 3)]
    assert fill_gaps.plan(GAPS["gaps"], minimum=4, tracks=["backend_verbal"], limit=0) == []


def test_drafts_are_written_unscored_for_the_gaps_track(tmp_path, monkeypatch):
    monkeypatch.setattr(draft_items, "BANK_DIR", tmp_path)
    writer = FakeWriter()
    out = fill_gaps.run(
        minimum=4,
        tracks=None,
        limit=0,
        dry_run=False,
        gaps_source=lambda _m: GAPS,
        writer_factory=lambda: writer,
    )
    assert out == {"planned": 1, "written": 3}
    assert "difficulty hard" in writer.prompts[0] and "6 career role" in writer.prompts[0]
    raw = yaml.safe_load((tmp_path / "frontend_verbal.drafted.yaml").read_text(encoding="utf-8"))
    items = list(raw["items"].values())
    assert len(items) == 3
    for item in items:
        assert item["round_types"] == ["frontend_verbal"]
        assert item["concepts"][0]["id"] == "concept:react"
        assert item["provenance"] == "generated" and item["scored_use_approved"] is False
        assert all(c["id"] != "concept:not_allowed" for c in item["concepts"])


def test_a_dry_run_calls_no_model(monkeypatch):
    def no_writer():
        raise AssertionError("a dry run must not build a writer")

    out = fill_gaps.run(
        minimum=4,
        tracks=None,
        limit=0,
        dry_run=True,
        gaps_source=lambda _m: GAPS,
        writer_factory=no_writer,
    )
    assert out == {"planned": 1, "written": 0}
