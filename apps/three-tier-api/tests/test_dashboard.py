"""The operator UI is real same-origin Flask content, not a mock landing page."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "labops_dashboard_api", Path(__file__).resolve().parents[1] / "app.py"
)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)


@pytest.fixture
def client():
    api.app.config.update(TESTING=True)
    with api.app.test_client() as flask_client:
        yield flask_client


def test_dashboard_loads_without_database_credentials(client, monkeypatch):
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    html = response.get_data(as_text=True)
    assert "LabOps" in html
    assert 'id="incident-list"' in html
    assert 'id="source-chart"' in html
    assert 'id="create-dialog"' in html
    assert 'id="event-rows"' in html
    assert 'id="count-visible"' in html
    assert '/static/labops/dashboard.css' in html
    assert '/static/labops/dashboard.js' in html
    assert 'src="https://' not in html
    assert 'href="https://' not in html


def test_dashboard_security_headers_and_no_cache(client):
    response = client.get("/dashboard")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Frame-Options"] == "DENY"
    csp = response.headers["Content-Security-Policy"]
    for directive in (
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
    ):
        assert directive in csp
    assert "unsafe-inline" not in csp


@pytest.mark.parametrize("asset,expected_type,needle", [
    ("/static/labops/dashboard.css", "text/css", ".workspace-grid"),
    ("/static/labops/dashboard.js", "text/javascript", "/api/v1/incidents"),
])
def test_static_assets_are_served_locally(client, asset, expected_type, needle):
    response = client.get(asset)
    assert response.status_code == 200
    assert response.mimetype in (
        [expected_type, "application/javascript"] if asset.endswith(".js") else [expected_type]
    )
    assert needle.encode() in response.data


def test_root_is_not_exposed_as_browser_app(client):
    assert client.get("/").status_code == 404
