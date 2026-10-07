"""Contract tests for the shared Flask application."""

import importlib.util
from pathlib import Path

import pytest

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
SPEC = importlib.util.spec_from_file_location("three_tier_api", APP_PATH)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)


@pytest.fixture
def client():
    api.app.config.update(TESTING=True)
    with api.app.test_client() as test_client:
        yield test_client


@pytest.mark.parametrize("endpoint", ["/health", "/readyz"])
def test_database_backed_endpoints_preserve_success_contract(client, monkeypatch, endpoint):
    monkeypatch.setattr(api, "_database_ping", lambda: 1)
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.json == {
        "status": "ok",
        "role": "app",
        "db": "connected",
        "db_result": 1,
    }


@pytest.mark.parametrize("endpoint", ["/health", "/readyz"])
def test_database_outage_returns_503_without_exposing_credentials(
    client, monkeypatch, endpoint
):
    def database_down():
        raise ConnectionError("private-db.internal:5432 password=do-not-expose")

    monkeypatch.setattr(api, "_database_ping", database_down)
    response = client.get(endpoint)
    assert response.status_code == 503
    assert response.json == {
        "status": "error",
        "role": "app",
        "db": "unavailable",
    }
    assert b"do-not-expose" not in response.data


def test_liveness_does_not_depend_on_database(client, monkeypatch):
    def database_down():
        raise ConnectionError("Database unavailable")

    monkeypatch.setattr(api, "_database_ping", database_down)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "role": "app"}


def test_unexpected_database_result_is_not_ready(client, monkeypatch):
    monkeypatch.setattr(api, "_database_ping", lambda: 0)
    response = client.get("/readyz")
    assert response.status_code == 503


def test_database_ping_uses_environment_and_select_one(monkeypatch):
    observed = {}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, sql):
            observed["sql"] = sql

        def fetchone(self):
            return (1,)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return Cursor()

    def connect(**kwargs):
        observed["connect"] = kwargs
        return Connection()

    monkeypatch.setenv("PGHOST", "database.internal")
    monkeypatch.setenv("PGPASSWORD", "private-test-value")
    monkeypatch.delenv("PGDATABASE", raising=False)
    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.setattr(api.psycopg2, "connect", connect)

    assert api._database_ping() == 1
    assert observed["sql"] == "SELECT 1"
    assert observed["connect"] == {
        "host": "database.internal",
        "dbname": "labdb",
        "user": "labuser",
        "password": "private-test-value",
        "connect_timeout": 3,
    }
