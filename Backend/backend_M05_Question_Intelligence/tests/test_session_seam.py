"""The two seams a caller needs — the ones M06 ran into first.

Both are about the same thing: this module owns the in-session estimate and
forbids persisting it (§6.10), so a caller must never have to hold it, and an
item this module hands out must be one it will hand back.

The θ tests assert on **the `SelectionRequest` the route builds**, not on which
item comes back. With an uncalibrated twelve-item bank every item cold-starts
from its band, so two very different estimates often rank the same item first
— a test on the item id would pass or fail for reasons that have nothing to do
with the seam.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend_M05_Question_Intelligence import bank as bank_module
from backend_M05_Question_Intelligence import router as router_module
from backend_M05_Question_Intelligence import selection as selection_module
from backend_M05_Question_Intelligence.app import app
from backend_M05_Question_Intelligence.contracts import SelectionRequest


@pytest.fixture(name="client")
def client_fixture():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def seen(monkeypatch):
    """Captures the request the route hands to the selector."""
    captured: list[SelectionRequest] = []
    real = selection_module.select

    def spy(questions, request, **kwargs):
        captured.append(request)
        return real(questions, request, **kwargs)

    monkeypatch.setattr(router_module.selection_module, "select", spy)
    return captured


def _select(client, session_id: uuid.UUID, candidate_id: uuid.UUID, **extra):
    response = client.post(
        "/v1/questions/select",
        json={
            "candidate_id": str(candidate_id),
            "session_id": str(session_id),
            "round_type": "dsa_verbal",
            "time_remaining_s": 1800,
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_fallback_item_can_be_fetched_after_it_is_selected(client):
    """`select()` falls back to the playlist by design; the id must resolve.

    `Bank.get()` searched `questions` only, so a caller handed a playlist item
    got a 404 on the very next call and had to treat a working bank as an
    absent one.
    """
    playlist = bank_module.load().playlist
    assert playlist, "the fallback playlist is §6.8 step 5's last line"
    for item in playlist:
        response = client.get(f"/v1/questions/{item.id}")
        assert response.status_code == 200, response.text
        assert response.json()["stem"] == item.stem


def test_selection_uses_the_theta_this_module_owns(client, seen):
    """§6.10: the caller should not have to carry it — or persist it to do so."""
    session_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    seeded = client.post(
        f"/v1/sessions/{session_id}/theta/seed",
        json={
            "candidate_id": str(candidate_id),
            "posterior": {"concept:hashing": 2.5},
            "snapshot_id": "m04-snapshot-1",
        },
    )
    assert seeded.status_code == 200, seeded.text

    # No `theta_provisional` in the request at all.
    _select(client, session_id, candidate_id)
    request = seen[-1]
    assert request.theta_provisional == {"concept:hashing": 2.5}
    assert request.theta_seeded_from == "m04-snapshot-1"


def test_a_verdict_moves_what_the_next_selection_is_given(client, seen):
    """The whole point of the session-scoped estimate: it moves mid-session."""
    session_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    client.post(
        f"/v1/sessions/{session_id}/theta/seed",
        json={"candidate_id": str(candidate_id), "posterior": {"concept:hashing": 0.0}},
    )
    observed = client.post(
        f"/v1/sessions/{session_id}/theta/observe",
        json={
            "concept_id": "concept:hashing",
            "outcome": {"turn_id": str(uuid.uuid4()), "band": "above", "confidence": 0.9},
        },
    )
    assert observed.status_code == 200, observed.text
    moved = observed.json()["theta_provisional"]
    assert moved > 0

    _select(client, session_id, candidate_id)
    assert seen[-1].theta_provisional["concept:hashing"] == moved
    assert seen[-1].provisional_updates == 1


def test_an_explicit_theta_still_wins(client, seen):
    """The simulator passes one, and a test has to be able to."""
    session_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    client.post(
        f"/v1/sessions/{session_id}/theta/seed",
        json={"candidate_id": str(candidate_id), "posterior": {"concept:hashing": 2.5}},
    )
    _select(client, session_id, candidate_id, theta_provisional={"concept:hashing": -2.5})
    assert seen[-1].theta_provisional == {"concept:hashing": -2.5}


def test_an_unseeded_session_selects_at_the_prior(client, seen):
    """A caller with no session here is the normal case, not an error."""
    _select(client, uuid.uuid4(), uuid.uuid4())
    assert seen[-1].theta_provisional == {}
    assert seen[-1].theta_seeded_from == "cold"
