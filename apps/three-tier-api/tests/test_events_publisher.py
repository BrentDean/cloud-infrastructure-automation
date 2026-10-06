"""Unit contracts for the synchronous Flask-to-NATS publisher wrapper."""

import importlib.util
from pathlib import Path
from uuid import UUID

import pytest

SPEC = importlib.util.spec_from_file_location(
    "labops_events", Path(__file__).resolve().parents[1] / "events.py"
)
events = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(events)

INCIDENT_ID = "11111111-2222-4333-8444-555555555555"


def test_disabled_without_nats_url(monkeypatch):
    monkeypatch.delenv("NATS_URL", raising=False)

    async def should_not_run(*_args):
        pytest.fail("NATS coroutine should not run when NATS_URL is absent")

    monkeypatch.setattr(events, "_publish", should_not_run)
    assert events.publish_incident_created({"id": INCIDENT_ID}) is None


def test_builds_incident_created_event(monkeypatch):
    observed = {}

    async def capture(url, event):
        observed["url"] = url
        observed["event"] = event.copy()

    monkeypatch.setenv("NATS_URL", "nats://nats:4222")
    monkeypatch.setattr(events, "_publish", capture)

    event = events.publish_incident_created({"id": INCIDENT_ID})

    assert observed["url"] == "nats://nats:4222"
    assert observed["event"] == event
    assert event["incident_id"] == INCIDENT_ID
    assert event["event_type"] == "incident.created"
    assert str(UUID(event["event_id"])) == event["event_id"]
