"""Best-effort Core NATS publication for LabOps domain events."""

import asyncio
import json
import os
from uuid import uuid4

import nats

INCIDENT_CREATED_SUBJECT = "labops.incident.created"


async def _publish(nats_url, event):
    connection = None
    try:
        connection = await nats.connect(
            servers=[nats_url],
            name="labops-api",
            connect_timeout=1,
            max_reconnect_attempts=0,
        )
        payload = json.dumps(
            event, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        await connection.publish(INCIDENT_CREATED_SUBJECT, payload)
        await connection.flush(timeout=1)
    finally:
        if connection is not None:
            await connection.close()


def publish_incident_created(incident):
    """Publish after the incident transaction commits when NATS is configured.

    Core NATS is deliberately best-effort here. The caller decides how to
    handle publication failures; this function never mutates database state.
    """
    nats_url = os.getenv("NATS_URL", "").strip()
    if not nats_url:
        return None

    event = {
        "event_id": str(uuid4()),
        "incident_id": incident["id"],
        "event_type": "incident.created",
    }
    asyncio.run(_publish(nats_url, event))
    return event
