#!/usr/bin/env python3
"""Explicit opt-in, loopback-only synthetic LabOps dashboard demonstration.

Creates genuine PostgreSQL-backed incident/event records through the existing
HTTP API. Does not contact AWS, T-Pot, or any non-loopback network endpoint.
"""

import argparse
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


def http_json(url, value, method="POST"):
    request = Request(
        url,
        method=method,
        data=json.dumps(value).encode(),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        if response.status not in (200, 201):
            raise RuntimeError("Unexpected API response status")
        return json.load(response)


def validate_base_url(value):
    target = urlsplit(value)
    if (
        target.scheme != "http"
        or target.hostname not in ("localhost", "127.0.0.1", "::1")
        or target.username is not None
        or target.password is not None
        or target.path not in ("", "/")
        or target.query
        or target.fragment
    ):
        raise argparse.ArgumentTypeError(
            "Demo seeding accepts only a plain HTTP loopback URL (localhost/127.0.0.1/::1)."
        )
    try:
        if target.port is None:
            raise ValueError("Port required")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Explicit port required") from exc
    return value.rstrip("/")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", type=validate_base_url,
        default="http://127.0.0.1:18080",
        help="A running, isolated local Compose API (default: %(default)s)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Explicitly create synthetic records in the selected local database",
    )
    args = parser.parse_args()

    if not args.run:
        parser.print_help()
        print("\nNo data written. Add --run to seed the local LabOps database.")
        return

    root = args.base_url + "/api/v1/incidents"
    examples = [
        ("Synthetic HTTP anomaly review", "medium", "open"),
        ("Synthetic scheduled health probe failure", "low", "resolved"),
        ("Synthetic unusual login pattern", "critical", "investigating"),
        ("Synthetic repeated SSH login failures", "high", "investigating"),
    ]
    incidents = []
    for title, severity, status in examples:
        incident = http_json(root, {
            "title": title,
            "description": (
                "Fictional event scenario for the LabOps portfolio demo. "
                "No real host, user, password, or telemetry is present."
            ),
            "severity": severity,
        })["incident"]
        if status != "open":
            incident = http_json(root + "/" + incident["id"], {
                "status": status,
                "notes": "Synthetic analyst notes; no security response executed.",
            }, method="PATCH")["incident"]
        incidents.append(incident)

    primary = incidents[-1]["id"]
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    prefix = "synthetic-demo-" + str(uuid4())

    for index in range(5):
        http_json(root + "/" + primary + "/events", {
            "source": "cowrie",
            "event_type": "cowrie.login.failed",
            "source_event_id": prefix + "-primary-" + str(index),
            "source_ip": "198.51.100.23",
            "username": "root" if index < 2 else "admin",
            "observed_at": stamp,
        })
    for index in range(2):
        http_json(root + "/" + primary + "/events", {
            "source": "cowrie",
            "event_type": "cowrie.login.failed",
            "source_event_id": prefix + "-secondary-" + str(index),
            "source_ip": "203.0.113.7",
            "username": "test-user",
            "observed_at": stamp,
        })

    print("Seeded four synthetic incidents and seven synthetic Cowrie events.")
    print("Open:", args.base_url + "/dashboard?incident=" + primary)
    print("Run again only if you want additional demo records.")


if __name__ == "__main__":
    main()
