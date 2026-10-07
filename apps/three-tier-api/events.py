"""JetStream publication for LabOps domain events."""

import asyncio
import json
import os
from uuid import uuid4

import nats

INCIDENT_CREATED_SUBJECT = "labops.incident.created"
NATS_MSG_ID_HEADER = "Nats-Msg-Id"


def _jetstream_headers(event):
    return {NATS_MSG_ID_HEADER: event["event_id"]}


async def _publish(nats_url, event):
    connection = None
    try:
        connection = await nats.connect(
            servers=[nats_url],
            name="labops-api",
            connect_timeout=1,
            max_reconnect_attempts=0,
        )
        jetstream = connection.jetstream()
        payload = json.dumps(
            event, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        await jetstream.publish(
            INCIDENT_CREATED_SUBJECT,
            payload,
            headers=_jetstream_headers(event),
            timeout=2,
        )
    finally:
        if connection is not None:
            await connection.close()


def publish_incident_created(incident):
    """Publish after the incident transaction commits when NATS is configured.

    JetStream confirms broker persistence before this function returns. The
    database commit and broker publish are still separate operations; the caller
    deliberately keeps an already-committed incident successful if publishing
    later fails.
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
