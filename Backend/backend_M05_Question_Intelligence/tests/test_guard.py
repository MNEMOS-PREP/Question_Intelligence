"""Who may ask — Platform_Core v0.11.0's guard on M05's router.

Until 2026-10-02 M05 had none. Any caller could exclude any item from
selection with the ⚑, and `select` would hand a stranger's request the
provisional estimate of whatever session id it named. Each test below is one of
those doors, asked as somebody who should not get through it.
"""

from __future__ import annotations

import uuid

import pytest
from ai_core.guard import identity_headers
from ai_core.testing import OWNER, assert_refuses_strangers
from fastapi.testclient import TestClient

from backend_M05_Question_Intelligence import bank as bank_module
from backend_M05_Question_Intelligence import router as router_module
from backend_M05_Question_Intelligence import session as session_module
from backend_M05_Question_Intelligence.app import app

STRANGER = uuid.UUID("00000000-0000-4000-8000-0000000b0b00")


@pytest.fixture(name="client")
def client_fixture():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def owned_session():
    """A session seeded for OWNER whose id is OWNER too — the id the shared
    check fills into `{session_id}`, so the guard can resolve it to its owner."""
    sid = uuid.UUID(OWNER)
    router_module._SESSIONS[sid] = session_module.seed_from_m04(sid, uuid.UUID(OWNER), None)
    yield sid
    router_module._SESSIONS.pop(sid, None)


def test_every_session_route_refuses_strangers(client, owned_session):
    """Found from the OpenAPI document, not listed — a session route added
    next month is checked by this test."""
    checked = assert_refuses_strangers(
        client, app, params=("candidate_id", "session_id"), expect_at_least=3
    )
    assert ("POST", "/v1/sessions/{session_id}/theta/observe") in checked
    assert ("POST", "/v1/sessions/{session_id}/close") in checked


def test_the_owner_still_gets_through(client, owned_session):
    response = client.post(
        f"/v1/sessions/{owned_session}/theta/observe",
        json={
            "concept_id": "concept:hashing",
            "outcome": {"turn_id": str(uuid.uuid4()), "band": "at", "confidence": 0.8},
        },
        headers=identity_headers(OWNER),
    )
    assert response.status_code == 200, response.text


def test_select_will_not_read_another_students_session(client, owned_session):
    """The stranger names THEMSELVES in the body — which passes the body check
    — and somebody else's session id, whose estimate `select` would read."""
    response = client.post(
        "/v1/questions/select",
        json={
            "candidate_id": str(STRANGER),
            "session_id": str(owned_session),
            "round_type": "dsa_verbal",
            "time_remaining_s": 1800,
        },
        headers=identity_headers(STRANGER),
    )
    assert response.status_code == 403


def test_select_for_somebody_else_is_refused(client):
    response = client.post(
        "/v1/questions/select",
        json={
            "candidate_id": OWNER,
            "session_id": str(uuid.uuid4()),
            "round_type": "dsa_verbal",
            "time_remaining_s": 1800,
        },
        headers=identity_headers(STRANGER),
    )
    assert response.status_code == 403


def test_seeding_a_session_for_somebody_else_is_refused(client):
    response = client.post(
        f"/v1/sessions/{uuid.uuid4()}/theta/seed",
        json={"candidate_id": OWNER},
        headers=identity_headers(STRANGER),
    )
    assert response.status_code == 403


def test_a_flag_needs_somebody_asking(client):
    """A flag excludes the item for every student, so an anonymous one is
    refused — and one made on somebody else's behalf too."""
    item = bank_module.load().questions[0]
    anonymous = client.post(f"/v1/questions/{item.id}/flag", json={"reason": "unclear"})
    assert anonymous.status_code == 401
    for_another = client.post(
        f"/v1/questions/{item.id}/flag",
        json={"reason": "unclear", "candidate_id": OWNER},
        headers=identity_headers(STRANGER),
    )
    assert for_another.status_code == 403
    own = client.post(
        f"/v1/questions/{item.id}/flag",
        json={"reason": "unclear", "candidate_id": str(STRANGER)},
        headers=identity_headers(STRANGER),
    )
    assert own.status_code == 200
