"""Deterministic, read-only SSH failed-login investigation API contracts."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

SPEC = importlib.util.spec_from_file_location(
    "labops_investigation_api", Path(__file__).resolve().parents[1] / "app.py"
)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)

INCIDENT_ID = str(uuid4())
URL = "/api/v1/incidents/" + INCIDENT_ID + "/investigations/ssh-login-failures"
AT = "2026-09-24T12:30:00Z"


@pytest.fixture
def client():
    api.app.config.update(TESTING=True)
    with api.app.test_client() as test_client:
        yield test_client


def evidence():
    return {
        "total_failed_logins": 6,
        "distinct_source_ips": 2,
        "source_ips_truncated": False,
        "sources": [
            {
                "source_ip": "198.51.100.23",
                "failed_logins": 5,
                "distinct_usernames": 2,
                "first_seen": "2026-09-24T12:00:00+00:00",
                "last_seen": "2026-09-24T12:20:00+00:00",
            },
            {
                "source_ip": "203.0.113.7",
                "failed_logins": 1,
                "distinct_usernames": 1,
                "first_seen": "2026-09-24T12:12:00+00:00",
                "last_seen": "2026-09-24T12:12:00+00:00",
            },
        ],
    }


def test_report_is_explainable_and_does_not_execute_response(client, monkeypatch):
    observed = []
    def query(incident_id, since, as_of):
        observed.append((incident_id, since.isoformat(), as_of.isoformat()))
        return evidence()
    monkeypatch.setattr(api.db, "investigate_ssh_login_failures", query)
    response = client.get(URL + "?as_of=" + AT + "&window_minutes=60&threshold=5")
    assert response.status_code == 200
    report = response.json["investigation"]
    assert report["incident_id"] == INCIDENT_ID
    assert report["window_start"] == "2026-09-24T11:30:00+00:00"
    assert report["window_end"] == "2026-09-24T12:30:00+00:00"
    assert report["total_failed_logins"] == 6
    assert report["distinct_source_ips"] == 2
    assert report["source_ips_truncated"] is False
    assert report["response_executed"] is False
    assert report["sources"][0]["threshold_met"] is True
    assert report["sources"][1]["threshold_met"] is False
    assert observed == [(
        INCIDENT_ID,
        "2026-09-24T11:30:00+00:00",
        "2026-09-24T12:30:00+00:00",
    )]


def test_threshold_changes_signal_not_underlying_event_counts(client, monkeypatch):
    monkeypatch.setattr(api.db, "investigate_ssh_login_failures", lambda *_: evidence())
    report = client.get(URL + "?as_of=" + AT + "&threshold=6").json["investigation"]
    assert report["total_failed_logins"] == 6
    assert all(not item["threshold_met"] for item in report["sources"])


def test_empty_incident_report_is_not_a_false_positive(client, monkeypatch):
    monkeypatch.setattr(
        api.db, "investigate_ssh_login_failures",
        lambda *_: {"total_failed_logins": 0, "distinct_source_ips": 0,
                    "source_ips_truncated": False, "sources": []},
    )
    report = client.get(URL + "?as_of=" + AT).json["investigation"]
    assert report["sources"] == []
    assert report["total_failed_logins"] == 0
    assert report["response_executed"] is False


def test_offset_timezone_and_default_parameters(client, monkeypatch):
    observed = []
    def query(identifier, since, as_of):
        observed.append((since, as_of))
        return evidence()
    monkeypatch.setattr(api.db, "investigate_ssh_login_failures", query)
    response = client.get(URL + "?as_of=2026-09-24T08:30:00-04:00")
    assert response.status_code == 200
    assert response.json["investigation"]["threshold"] == 5
    assert response.json["investigation"]["window_minutes"] == 60
    assert observed[0][1].isoformat() == "2026-09-24T12:30:00+00:00"
    assert observed[0][0].isoformat() == "2026-09-24T11:30:00+00:00"


@pytest.mark.parametrize("params", [
    "window_minutes=0", "window_minutes=1441", "window_minutes=1.5",
    "window_minutes=999999999999999999999999999999",
    "threshold=1", "threshold=1001", "threshold=-1",
    "threshold=none", "as_of=tomorrow",
    "as_of=2026-09-24T12:30:00",
    "as_of=2026-09-24T12:30:00Z" + "x" * 100,
])
def test_invalid_parameters_never_query_postgresql(client, monkeypatch, params):
    monkeypatch.setattr(
        api.db, "investigate_ssh_login_failures", lambda *_: pytest.fail("DB queried")
    )
    response = client.get(URL + "?" + params)
    assert response.status_code == 400


def test_invalid_incident_uuid_never_queries_db(client, monkeypatch):
    monkeypatch.setattr(
        api.db, "investigate_ssh_login_failures", lambda *_: pytest.fail("DB queried")
    )
    assert client.get(
        "/api/v1/incidents/nope/investigations/ssh-login-failures"
    ).status_code == 400


def test_missing_incident_returns_404(client, monkeypatch):
    def missing(*_):
        raise api.db.IncidentNotFound()
    monkeypatch.setattr(api.db, "investigate_ssh_login_failures", missing)
    response = client.get(URL + "?as_of=" + AT)
    assert response.status_code == 404
    assert response.json["error"]["code"] == "not_found"


def test_database_outage_returns_503_without_leaking_password(client, monkeypatch):
    def unavailable(*_):
        raise psycopg2.OperationalError("password=private-synthetic")
    monkeypatch.setattr(api.db, "investigate_ssh_login_failures", unavailable)
    response = client.get(URL + "?as_of=" + AT)
    assert response.status_code == 503
    assert response.json["error"]["code"] == "database_unavailable"
    assert b"private-synthetic" not in response.data
