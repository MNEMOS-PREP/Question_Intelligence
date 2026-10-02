"""The answer key is for modules, and a grounded item is for its student.

Until 2026-10-02 `GET /v1/questions/{id}` served every item whole to anybody
holding its id — reference answer, key points, follow-ups, the full hint
ladder — and `/package` was the same key in M13's shape. A student with the
network tab open had the marking scheme mid-interview. A grounded item, built
from one student's own repository, was readable by everyone else too, though
`select` had always refused to serve it to them.
"""

from __future__ import annotations

import uuid

import pytest
from ai_core import service
from ai_core.guard import identity_headers
from ai_core.testing import assert_service_only
from fastapi.testclient import TestClient

from backend_M05_Question_Intelligence import bank as bank_module
from backend_M05_Question_Intelligence.app import app
from backend_M05_Question_Intelligence.router import ANSWER_KEY

from .conftest import CANDIDATE, OTHER_CANDIDATE, make_grounded

ADMIN = {"X-Role": "admin", "X-Candidate-Id": "ops"}


@pytest.fixture(name="client")
def client_fixture():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def item():
    return bank_module.load().questions[0]


@pytest.fixture
def grounded():
    """One student's grounded item, in the live bank for the length of a test."""
    bank = bank_module.load()
    theirs = make_grounded(CANDIDATE)
    bank.questions.append(theirs)
    yield theirs
    bank.questions.remove(theirs)


def test_a_browser_gets_the_question_and_not_its_answer(client, item):
    assert item.reference_answer and item.key_points, "the fixture must have a key to hide"
    response = client.get(f"/v1/questions/{item.id}", headers=identity_headers(CANDIDATE))
    assert response.status_code == 200
    body = response.json()
    assert body["stem"] == item.stem
    for field in ANSWER_KEY:
        assert not body[field], field
    assert response.headers["X-Answer-Key"] == "withheld"


def test_nobody_signed_in_gets_no_more(client, item):
    body = client.get(f"/v1/questions/{item.id}").json()
    assert not body["reference_answer"] and not body["key_points"]


def test_a_module_gets_the_whole_item(client, item):
    """M06 probes against the key points; this is the call it makes."""
    response = client.get(f"/v1/questions/{item.id}", headers=service.headers())
    body = response.json()
    assert body["reference_answer"] == item.reference_answer
    assert len(body["key_points"]) == len(item.key_points)
    assert "X-Answer-Key" not in response.headers


def test_an_administrator_may_read_the_key(client, item):
    assert client.get(f"/v1/questions/{item.id}", headers=ADMIN).json()["key_points"]


def test_the_package_is_for_modules_only(client, item):
    """Found from the OpenAPI document: a service-only route added later is
    checked by this test too."""
    checked = assert_service_only(client, app)
    assert ("GET", "/v1/questions/{question_id}/package") in checked
    ok = client.get(
        f"/v1/questions/{item.id}/package",
        params={"round_type": item.rubric_round_type},
        headers=service.headers(),
    )
    assert ok.status_code == 200 and ok.json()["key_points"]


def test_a_grounded_item_is_its_students_and_nobody_elses(client, grounded):
    url = f"/v1/questions/{grounded.id}"
    assert client.get(url, headers=identity_headers(CANDIDATE)).status_code == 200
    assert client.get(url, headers=identity_headers(OTHER_CANDIDATE)).status_code == 403
    assert client.get(url).status_code == 403
    # M06 fetches it for the session it was selected into.
    assert client.get(url, headers=service.headers()).status_code == 200


def test_its_own_student_still_does_not_get_the_key(client, grounded):
    body = client.get(f"/v1/questions/{grounded.id}", headers=identity_headers(CANDIDATE)).json()
    assert body["stem"] == grounded.stem
    assert not body["key_points"]


def test_an_unknown_item_is_a_404_not_a_refusal(client):
    assert client.get(f"/v1/questions/{uuid.uuid4()}").status_code == 404
