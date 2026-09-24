"""LabOps incident HTTP contracts. PostgreSQL integration is tested with Compose."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

SPEC = importlib.util.spec_from_file_location(
    "labops_api", Path(__file__).resolve().parents[1] / "app.py"
)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)

IDENTIFIER = str(uuid4())
RECORD = {
    "id": IDENTIFIER,
    "title": "Investigate SSH failures",
    "description": "Correlate repeated failed logins in a test event stream",
    "severity": "high",
    "status": "open",
    "source": "manual",
    "notes": None,
    "created_at": "2026-09-24T12:00:00+00:00",
    "updated_at": "2026-09-24T12:00:00+00:00",
}
VALID = {
    "title": RECORD["title"],
    "description": RECORD["description"],
    "severity": "high",
}


@pytest.fixture
def client():
    api.app.config.update(TESTING=True)
    with api.app.test_client() as client:
        yield client


def test_create_returns_201_location_and_record(client, monkeypatch):
    observed = {}
    def create(title, description, severity):
        observed["args"] = (title, description, severity)
        return RECORD
    monkeypatch.setattr(api.db, "create_incident", create)
    response = client.post("/api/v1/incidents", json=VALID)
    assert response.status_code == 201
    assert response.json == {"incident": RECORD}
    assert response.headers["Location"] == "/api/v1/incidents/" + IDENTIFIER
    assert observed["args"] == (VALID["title"], VALID["description"], "high")


@pytest.mark.parametrize("payload", [
    {"title": "", "description": "a", "severity": "high"},
    {"title": "a" * 121, "description": "a", "severity": "high"},
    {"title": "a", "description": "", "severity": "high"},
    {"title": "a", "description": "a", "severity": "urgent"},
    {"title": "a", "description": "a", "severity": "high", "status": "resolved"},
    {"title": 42, "description": "a", "severity": "high"},
])
def test_create_rejects_bad_fields_before_database(client, monkeypatch, payload):
    monkeypatch.setattr(api.db, "create_incident", lambda *args: pytest.fail("DB called"))
    response = client.post("/api/v1/incidents", json=payload)
    assert response.status_code == 400
    assert "error" in response.json


def test_requires_json_object(client):
    assert client.post("/api/v1/incidents", data="hello").status_code == 415
    assert client.post("/api/v1/incidents", data="{", content_type="application/json").status_code == 400
    assert client.post("/api/v1/incidents", json=["not", "an", "object"]).status_code == 400


@pytest.mark.parametrize("limit", ["0", "101", "-1", "4.5", "abc"])
def test_list_limit_validation(client, monkeypatch, limit):
    monkeypatch.setattr(api.db, "list_incidents", lambda *_: pytest.fail("DB called"))
    assert client.get("/api/v1/incidents?limit=" + limit).status_code == 400


def test_list_get_and_missing(client, monkeypatch):
    monkeypatch.setattr(api.db, "list_incidents", lambda limit: [RECORD] if limit == 2 else [])
    monkeypatch.setattr(api.db, "get_incident", lambda value: RECORD if value == IDENTIFIER else None)
    assert client.get("/api/v1/incidents?limit=2").json == {"incidents": [RECORD]}
    assert client.get("/api/v1/incidents/" + IDENTIFIER).json == {"incident": RECORD}
    assert client.get("/api/v1/incidents/" + str(uuid4())).status_code == 404
    assert client.get("/api/v1/incidents/not-a-uuid").status_code == 400


def test_patch_status_and_notes(client, monkeypatch):
    observed = {}
    def update(identifier, status, notes):
        observed["args"] = (identifier, status, notes)
        return {**RECORD, "status": status, "notes": notes}
    monkeypatch.setattr(api.db, "update_incident", update)
    response = client.patch("/api/v1/incidents/" + IDENTIFIER, json={
        "status": "investigating", "notes": "Checked synthetic events"
    })
    assert response.status_code == 200
    assert response.json["incident"]["status"] == "investigating"
    assert observed["args"] == (IDENTIFIER, "investigating", "Checked synthetic events")


@pytest.mark.parametrize("payload", [
    {}, {"status": "invalid"}, {"status": None},
    {"notes": None}, {"notes": "x" * 4001}, {"severity": "low"},
])
def test_patch_rejects_invalid_body(client, monkeypatch, payload):
    monkeypatch.setattr(api.db, "update_incident", lambda *args: pytest.fail("DB called"))
    assert client.patch("/api/v1/incidents/" + IDENTIFIER, json=payload).status_code == 400


def test_patch_missing_record(client, monkeypatch):
    monkeypatch.setattr(api.db, "update_incident", lambda *args: None)
    assert client.patch(
        "/api/v1/incidents/" + IDENTIFIER, json={"status": "resolved"}
    ).status_code == 404


@pytest.mark.parametrize("endpoint,method", [
    ("/api/v1/incidents", "get"),
    ("/api/v1/incidents", "post"),
    ("/api/v1/incidents/" + IDENTIFIER, "get"),
    ("/api/v1/incidents/" + IDENTIFIER, "patch"),
])
def test_database_error_is_503_and_never_leaks_credentials(
    client, monkeypatch, endpoint, method
):
    def unavailable(*args):
        raise psycopg2.OperationalError("password=private-test-value")
    monkeypatch.setattr(api.db, {
        ("get", "/api/v1/incidents"): "list_incidents",
        ("post", "/api/v1/incidents"): "create_incident",
        ("get", "/api/v1/incidents/" + IDENTIFIER): "get_incident",
        ("patch", "/api/v1/incidents/" + IDENTIFIER): "update_incident",
    }[method, endpoint], unavailable)
    if method == "post":
        response = client.post(endpoint, json=VALID)
    elif method == "patch":
        response = client.patch(endpoint, json={"status": "investigating"})
    else:
        response = client.get(endpoint)
    assert response.status_code == 503
    assert response.json["error"]["code"] == "database_unavailable"
    assert b"private-test-value" not in response.data


def test_size_limit_is_json(client):
    response = client.post(
        "/api/v1/incidents", data=b"x" * (16 * 1024 + 1),
        content_type="application/json",
    )
    assert response.status_code == 413
    assert response.json["error"]["code"] == "payload_too_large"
