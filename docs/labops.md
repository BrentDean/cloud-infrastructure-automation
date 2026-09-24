# LabOps: persistent security incident workflow (first application milestone)

LabOps is the application built **on** the disposable AWS three-tier lab. It
does not modify LaunchShell, TorKit, or any Hetzner staging service. The incident-management and sanitized synthetic Cowrie event-ingestion milestones
now support a read-only investigation workflow; **no security response is
executed, and this is not a full SOAR platform**.

## Application contract

The same Flask source and PostgreSQL schema serve both Gunicorn/systemd and
single-node k3s modes. Application state belongs to dedicated PostgreSQL EC2,
never a Pod, local-path PVC, or an in-memory Python dictionary.

| HTTP | Route | Result |
| --- | --- | --- |
| POST | /api/v1/incidents | Validate and create a manually reported incident (201 + Location) |
| GET | /api/v1/incidents?limit=20 | Most recent incidents; limit 1–100 |
| GET | /api/v1/incidents/{uuid} | One incident (404 when absent) |
| PATCH | /api/v1/incidents/{uuid} | Update status and/or operator notes |

Creation requires title (1–120 characters), description (1–2000), and
severity (low, medium, high, critical). All requests must contain a JSON object
and may only contain documented fields. New incidents begin in status open
and source manual. PATCH accepts status open/investigating/resolved and notes up
to 4000 characters. The database adds UUID, timestamps, NOT NULL and CHECK
constraints. Queries use bound parameters, and responses never include raw
PostgreSQL errors or passwords.

Example for the local-only Compose environment:

~~~bash
curl -i -X POST http://127.0.0.1:18080/api/v1/incidents \
  -H 'Content-Type: application/json' \
  --data '{"title":"Synthetic SSH alert","description":"Repeated failed logins in a lab","severity":"high"}'

curl http://127.0.0.1:18080/api/v1/incidents?limit=20
~~~

## Schema and deployment

The initial, versioned migration is
apps/three-tier-api/migrations/0001_incidents.sql. Its DDL is transactional and
idempotent. The database play copies and applies it **on the private database
EC2**, after creating labdb and labuser but before deploying the app. A read-only
check skips the migration on the second Ansible run so changed=0 remains possible.
In local Compose CI, the same SQL runs twice using labuser before the API starts.

The original systemd play now copies both app.py and db.py. The Dockerfile
packages the same files. The Kubernetes Service, two replicas, NodePort,
read-only root filesystem, and /healthz, /readyz and /health probe contracts
remain unchanged. Nginx adds /api/v1/ routing to the existing backend port for
each mode; its other paths still return 404. Terraform has not changed.

Run offline Python and isolated Docker/PostgreSQL tests:

~~~bash
python3 -m pytest -q apps/three-tier-api/tests
bash scripts/test-three-tier-api-container.sh
~~~

The container test creates, lists, and updates a synthetic incident; restarts
Flask; verifies PostgreSQL retained that record; pauses PostgreSQL; confirms
liveness 200 and readiness/incident API 503; restores PostgreSQL and retrieves
the record again. Tests and CI **do not provision AWS**.

## Security and verification limitations

The AWS web security group restricts port 80 and SSH to the operator IPv4 /32,
but HTTP currently has **no TLS or application authentication**. Only
synthetic, non-sensitive event examples belong in this prototype. Do not
submit credentials, production logs, client data, honeypot raw captures, or
institutional records. Do not expose /api/v1/ to the public Internet.

Local tests prove restart durability for the PostgreSQL container's retained
volume, not persistence after Terraform destroy. Existing Kubernetes PVC tests
are unrelated to incident storage. A future explicitly approved live AWS run
must verify Nginx/API access in both runtimes, new schema deployment,
cross-replica retrieval, and successful destruction separately. No new AWS
runtime evidence is claimed by this change.

Later bounded milestones: security-event ingest/deduplication, incident-event
relationships, read-only investigation playbook, audited execution history,
authenticated approvals, and carefully constrained response integrations.


## Security event ingestion: bounded Cowrie failed-login adapter (PR #4)

An operator first creates an incident with POST /api/v1/incidents. The caller
then explicitly attaches synthetic, sanitized Cowrie authentication failures:

~~~http
POST /api/v1/incidents/{incident_uuid}/events
Content-Type: application/json

{
  "source": "cowrie",
  "event_type": "cowrie.login.failed",
  "source_event_id": "synthetic-run-1-attempt-001",
  "source_ip": "198.51.100.23",
  "username": "root",
  "observed_at": "2026-09-24T12:00:00Z"
}
~~~

Only this event type is accepted. The source_event_id is a **stable unique
per-occurrence ID assigned by a future importer**, not Cowrie's eventid
(which is an event type like cowrie.login.failed). source_ip must be valid
IPv4 or IPv6; observed_at must include a timezone. JSON keys are allowlisted;
no raw JSON captures, passwords, passwords attempted, hostnames, or commands
are accepted or stored. Use documentation-reserved IP addresses and test
usernames, not live source telemetry, in this HTTP-only lab.

POST returns 201 for a new event, 200 for an exact idempotent replay, 409
if the same (source, source_event_id) refers to different content or a different
incident, 404 if the incident does not exist, 400/415 for invalid requests and
503 for PostgreSQL failure. A database UNIQUE constraint, transaction, and
ON CONFLICT DO NOTHING prevent duplicate rows across Gunicorn workers or Pods.
GET /api/v1/incidents/{incident_uuid}/events?limit=20 lists recent associated
events (limit 1–100), returning 404 for a nonexistent incident.

The second versioned SQL migration is
apps/three-tier-api/migrations/0002_security_events.sql. It adds a foreign
key to incidents, an INET source address, a global per-source event ID
uniqueness constraint, and an incident/time index. Ansible installs it only
after the incident schema on the existing dedicated database EC2. The local
Docker integration test runs both migrations twice before starting Flask.

**Operational boundary:** This is manual, explicitly incident-linked
ingestion. It does not fetch from T-Pot, auto-correlate incidents, enrich IPs,
execute response actions, call AWS, or change firewalls. Those are separately scoped
and will require authorization, authentication and TLS before exposing a
sensitive or remotely accessible ingestion interface.


## Read-only investigation: failed SSH logins (PR #5)

The first security investigation uses the same sanitized, explicitly
incident-linked Cowrie events already stored in PostgreSQL. It performs
deterministic analysis, not a network scan, attribution, enrichment call,
notification, firewall update, or incident-status change.

~~~http
GET /api/v1/incidents/{incident_uuid}/investigations/ssh-login-failures?as_of=2026-09-24T12:30:00Z&window_minutes=60&threshold=5
~~~

Parameters: window_minutes is 1–1440 (default 60); threshold is 2–1000
(default 5); as_of is optional, defaults to current UTC and accepts only
timezone-aware ISO-8601 timestamps. Supplying as_of explicitly makes the
investigation reproducible for automated tests and incident review.

The queried interval includes both its start and end. Only
cowrie.login.failed events associated with that incident are included.
PostgreSQL groups by the INET source address and returns failed-login count,
distinct attempted usernames, earliest/latest event times, and stable
ordering by descending failure count then IP text. Every source receives
threshold_met as an *investigation signal*, **not proof of an attack**.

The response also reports total_failed_logins and distinct_source_ips across
ALL sources in the selected window. At most 100 source summaries are returned;
source_ips_truncated discloses when more sources match so the capped list is
not mistaken for a complete list. An empty window returns zero counts and
an empty sources list, not a fabricated finding. response_executed is false.

HTTP 400 covers invalid UUID/timestamp/limits; 404 means the incident
does not exist; 503 means PostgreSQL is unavailable. No DB schema or extra
packages are needed. A SQL SELECT with bound parameters performs the
aggregation for both systemd and k3s. The Docker integration test covers
two IPs, duplicate event replay, time window exclusions, changing the
threshold, Flask restart, DB outage and restored results.

**Evidence distinction:** GitHub Actions exercises the local Flask and
PostgreSQL containers. The September 22/24 AWS runtime screenshots predate
LabOps and do not prove this investigation ran on AWS. A future live AWS
exercise requires separate explicit authorization and verified teardown.
