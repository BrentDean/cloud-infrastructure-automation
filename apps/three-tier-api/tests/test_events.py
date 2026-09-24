"""Synthetic Cowrie ingestion contracts; real persistence is exercised in Compose."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

SPEC = importlib.util.spec_from_file_location(
    "labops_events_api", Path(__file__).resolve().parents[1] / "app.py"
)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)

INCIDENT_ID = str(uuid4())
EVENT_ID = str(uuid4())
OTHER_ID = str(uuid4())
URL = "/api/v1/incidents/" + INCIDENT_ID + "/events"
BODY = {
    "source": "cowrie",
    "event_type": "cowrie.login.failed",
    "source_event_id": "synthetic-001",
    "source_ip": "198.51.100.23",
    "username": "root",
    "observed_at": "2026-09-24T12:00:00Z",
}
EVENT = {
    "id": EVENT_ID,
    "incident_id": INCIDENT_ID,
    **{k: v for k, v in BODY.items() if k != "observed_at"},
    "observed_at": "2026-09-24T12:00:00+00:00",
    "ingested_at": "2026-09-24T12:00:01+00:00",
}


@pytest.fixture
def client():
    api.app.config.update(TESTING=True)
    with api.app.test_client() as flask_client:
        yield flask_client


def test_first_ingestion_and_replay_share_the_same_id(client, monkeypatch):
    observed = []
    def persist(*args):
        observed.append(args)
        return EVENT, len(observed) == 1
    monkeypatch.setattr(api.db, "ingest_cowrie_event", persist)
    created = client.post(URL, json=BODY)
    replay = client.post(URL, json=BODY)
    assert created.status_code == 201
    assert replay.status_code == 200
    assert created.json == replay.json == {"event": EVENT}
    assert observed[0][:4] == (
        INCIDENT_ID, "synthetic-001", "198.51.100.23", "root"
    )
    assert observed[0][4].isoformat() == "2026-09-24T12:00:00+00:00"


def test_ingestion_normalizes_ip_and_timezone(client, monkeypatch):
    captured = []
    monkeypatch.setattr(
        api.db, "ingest_cowrie_event",
        lambda *args: (captured.append(args) or EVENT, True)
    )
    payload = {**BODY, "source_ip": "2001:0db8::1",
               "observed_at": "2026-09-24T08:00:00-04:00"}
    response = client.post(URL, json=payload)
    assert response.status_code == 201
    assert captured[0][2] == "2001:db8::1"
    assert captured[0][4].isoformat() == "2026-09-24T12:00:00+00:00"


@pytest.mark.parametrize("change", [
    {"source": "suricata"}, {"event_type": "cowrie.session.connect"},
    {"source_event_id": ""}, {"source_event_id": "x" * 129},
    {"source_event_id": 1}, {"source_ip": "999.999.999.999"},
    {"source_ip": "example.com"}, {"username": ""},
    {"username": "x" * 129}, {"observed_at": "yesterday"},
    {"observed_at": "2026-09-24T12:00:00"},
    {"observed_at": None}, {"password": "should-not-store"},
])
def test_bad_ingestion_rejected_before_database(client, monkeypatch, change):
    monkeypatch.setattr(
        api.db, "ingest_cowrie_event", lambda *_: pytest.fail("DB called")
    )
    response = client.post(URL, json={**BODY, **change})
    assert response.status_code == 400


def test_invalid_uuid_and_json_body(client, monkeypatch):
    monkeypatch.setattr(
        api.db, "ingest_cowrie_event", lambda *_: pytest.fail("DB called")
    )
    assert client.post("/api/v1/incidents/nope/events", json=BODY).status_code == 400
    assert client.post(URL, data="text").status_code == 415
    assert client.post(URL, json=["not", "object"]).status_code == 400


@pytest.mark.parametrize("exception,code,status", [
    (api.db.IncidentNotFound, "not_found", 404),
    (api.db.EventConflict, "event_conflict", 409),
    (psycopg2.OperationalError, "database_unavailable", 503),
])
def test_ingestion_domain_and_db_failures(client, monkeypatch, exception, code, status):
    def fail(*_):
        raise exception("password=private-synthetic")
    monkeypatch.setattr(api.db, "ingest_cowrie_event", fail)
    response = client.post(URL, json=BODY)
    assert response.status_code == status
    assert response.json["error"]["code"] == code
    assert b"private-synthetic" not in response.data


def test_event_listing_and_limit(client, monkeypatch):
    observed = []
    monkeypatch.setattr(
        api.db, "list_incident_events",
        lambda incident_id, limit: (observed.append((incident_id, limit)) or [EVENT]),
    )
    assert client.get(URL + "?limit=3").json == {"events": [EVENT]}
    assert observed == [(INCIDENT_ID, 3)]


@pytest.mark.parametrize("limit", ["0", "101", "-1", "4.2", "abc", "9" * 999])
def test_event_limit_must_be_bounded(client, monkeypatch, limit):
    monkeypatch.setattr(
        api.db, "list_incident_events", lambda *_: pytest.fail("DB called")
    )
    assert client.get(URL + "?limit=" + limit).status_code == 400


def test_event_listing_missing_incident_and_database_outage(client, monkeypatch):
    def missing(*_):
        raise api.db.IncidentNotFound()
    monkeypatch.setattr(api.db, "list_incident_events", missing)
    assert client.get(URL).status_code == 404

    def unavailable(*_):
        raise psycopg2.OperationalError("password=private-synthetic")
    monkeypatch.setattr(api.db, "list_incident_events", unavailable)
    response = client.get(URL)
    assert response.status_code == 503
    assert response.json["error"]["code"] == "database_unavailable"
    assert b"private-synthetic" not in response.data


def test_event_list_rejects_invalid_uuid(client):
    assert client.get("/api/v1/incidents/nope/events").status_code == 400
