# LabOps: persistent security operations application

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

The later sections document implemented security-event ingest/deduplication,
incident-event relationships and read-only investigation. Future bounded
milestones include **real** telemetry integrations, authenticated access and
TLS, audited execution history, and carefully constrained response
integrations. None is currently part of the live-verified AWS baseline.


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


## Browser dashboard (PR #6)

The first complete browser workflow is **/dashboard**. This is part of the
same Flask app and uses the same PostgreSQL-backed API in both AWS runtimes.
There is no externally hosted React bundle, CDN, external font, analytics
script, separate front-end host, new EC2 instance, or alternate database.

The dashboard includes:
- Desktop/mobile responsive navigation, incident snapshot (the *latest 100*
  records only, explicitly **not** lifetime/global statistics), and a searchable
  status-filtered incident queue.
- Readable detail and triage form (status/notes), and an explicit create
  incident dialog. Both writes call the existing versioned API; nothing is
  silently simulated by JavaScript.
- Up to 100 latest Cowrie events for the selected incident, time-window and
  threshold controls, source-IP activity bars, and read-only investigation
  results. The UI does **not** infer intent or block an IP.
- Actual loading, empty, database-unavailable, retry and refresh states,
  keyboard navigation, accessible labels and reduced-motion styling.
  API-provided text enters the DOM via textContent, never innerHTML.
- Local static CSS/JS, restrictive dashboard CSP, nosniff, no-store,
  frame denial, and no-referrer headers. Only /dashboard, /api/v1/*,
  /static/labops/* and legacy /health are proxied by Nginx; all other
  web-tier paths continue to return 404.

**The app is an operator-only lab.** The AWS web security group still admits
only the operator IPv4 /32 to port 80. There is not yet application
authentication or TLS. Do not expose the dashboard publicly or load real
honeypot traffic, client data, credentials, or institutional records.

### Explore locally without AWS

Follow the [README's local quickstart](../README.md#run-labops-locally-no-aws)
to launch the real Flask/PostgreSQL dashboard, run the versioned SQL migrations, and
optionally seed four fictional incidents and seven fictional failed-login
events. This demo requires Docker Compose and Python 3, not AWS or T-Pot.
Its browser endpoint is http://127.0.0.1:18080/dashboard.

The Compose project is explicitly named `labops-operator-demo`; the README
saves its secret and loopback port in
`~/.config/labops-demo/compose.env` with private filesystem permissions.
**Reuse that same file for future `up` and `down` commands.** Losing the
shell variables does not mean PostgreSQL lost its password; generating a new
environment variable will not reset a password already stored in the volume.

To stop the demo **while retaining its PostgreSQL volume**:

~~~bash
LABOPS_ENV="$HOME/.config/labops-demo/compose.env"
docker compose --env-file "$LABOPS_ENV" \
  -f apps/three-tier-api/compose.integration.yaml down
~~~

Use `down -v` only when you explicitly want to delete this isolated local
demo's PostgreSQL data. The optional seeder adds records each time it is
run, so run it once unless additional fictional cases are intended.
A Terraform destroy also deletes the disposable AWS database. Independent
long-lived application backups are not implemented.

### Browser regression evidence

The GitHub Actions application workflow runs the full Compose integration
suite *and real headless Chromium* against the localhost dashboard. It
creates/triages through the UI, inserts sanitized events through the API,
checks the source-IP analysis, browser reload persistence, an injected 503
and recovery, and mobile horizontal overflow. Screenshots of the desktop
investigation, degraded state, and mobile layout are uploaded as the
**labops-browser-preview** workflow artifact (synthetic data only; retention
14 days). No AWS credentials or billable cloud resources are required.

These local browser screenshots are **not** evidence that the updated
LabOps dashboard was live-deployed on AWS. The historical September 22/24
infrastructure screenshots remain separate and are labeled as such.

### LaunchShell Dark design system

LabOps uses LaunchShell's public palette without copying the light marketing
site: primary action blue `#1263ff`, healthy-state green `#12c995`, and
dark navy `#061226`. The dashboard retains dark, operator-focused surfaces;
incident severity and threshold signals remain amber/red, while green
continues to mean operational health rather than threat severity. The footer
identifies it as **A LaunchShell project**. No shared CSS dependency, extra
AWS resources, cross-project deployment coupling, external fonts, or new
third-party browser requests are introduced.


## Attach synthetic evidence from the browser (PR #7)

Choose an incident, select **Attach event** in the recent security events panel,
and enter a reserved documentation source IP plus a synthetic attempted
username. The dialog explains the supported Cowrie event type, fixes an
observation time, and creates a per-entry `manual-ui-...` idempotency key.
Its source address entry is restricted to the IPv4 documentation networks
`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, or the IPv6
documentation range `2001:db8::/32`; the Flask API and PostgreSQL continue
to validate the actual address. The UI never collects a password, raw JSON
log, hostname or personal details.

Submitting calls the existing `POST /api/v1/incidents/{uuid}/events` endpoint.
Success closes the modal and refreshes the selected incident's real event
table and read-only failed-login investigation, **without a page reload**.
On a 503 or lost response, the dialog retains the exact event ID, input,
and observed time so retrying can return the original stored event without
creating a duplicate. Editing the inputs deliberately prepares a new event
identity. Switching cases cannot redirect a pending form submission to a
different incident.

This closes the first end-to-end analyst browser path:
create incident → triage → add a synthetic evidence event → investigate →
reload and confirm PostgreSQL durability. Chromium explicitly tests rejected
non-documentation IPs, a simulated 503 and retry with the *same POST payload*,
real PostgreSQL persistence, browser refresh, and mobile layout. The
`desktop-event-intake.png` preview is included in the CI screenshot artifact.

**Boundary:** This is synthetic manual evidence entry; it is not ingestion
from a live honeypot, autonomous correlation or threat response. Authentication
and TLS are necessary before external exposure or real-event intake.


## Durable event path: JetStream + Go worker

The messaging path is now **durable in the local/CI environment** without
changing the verified AWS topology:

~~~text
Flask incident creation
        |
        | JetStream publish + server acknowledgement
        | Nats-Msg-Id: <event UUID>
        v
LABOPS_EVENTS (file storage)
        |
        | durable explicit-ack consumer
        v
 Go event-worker
        |
        v
 PostgreSQL event_deliveries
~~~

After PostgreSQL commits a new incident, Flask publishes a compact JSON event
containing an event UUID, the incident UUID, and `incident.created`. The
Python NATS client uses JetStream publish rather than Core NATS and waits for
the server's publish acknowledgement. The event UUID is also sent as
`Nats-Msg-Id`, enabling broker-side duplicate suppression inside the stream's
configured duplicate window.

The Go service owns the local stream/consumer configuration. It creates or
updates `LABOPS_EVENTS` with single-replica **file storage**, a seven-day
retention bound, message/byte limits, and a ten-minute duplicate window. Its
durable `labops-event-worker` consumer filters
`labops.incident.created`, uses explicit acknowledgements, an acknowledgement
timeout, bounded pending work, and at most five delivery attempts.

A delivery is acknowledged only after PostgreSQL successfully records it.
The worker uses JetStream `DoubleAck` so the acknowledgement itself is
confirmed by the server. A transient PostgreSQL failure receives a delayed
negative acknowledgement and can be redelivered. Invalid/poison JSON is
terminated rather than retried indefinitely. If an acknowledgement is lost
after the database insert, a redelivery is safe because
`event_deliveries.event_id` is unique and the worker acknowledges the
idempotent duplicate.

The Compose NATS service stores JetStream data in its own named volume and
does not publish the client or monitoring port to the host. CI performs the
reliability exercise explicitly:

1. Start Flask, PostgreSQL, NATS/JetStream, and the Go worker.
2. Verify one ordinary event reaches PostgreSQL.
3. Stop the worker.
4. Create two new incidents and confirm their delivery rows are still absent.
5. Restart the NATS server while those messages are queued.
6. Start the worker again.
7. Require both queued events to appear in PostgreSQL.

That last sequence demonstrates that accepted events survive both consumer
absence and a broker-process restart; they are not merely buffered in a live
Core NATS process.

The database commit and broker publish are still **not one atomic transaction**.
If PostgreSQL commits but the subsequent JetStream publish itself fails, the API
logs that failure and preserves the successful incident response rather than
claiming the database write failed. A transactional outbox would be the next
step if atomic database-to-broker handoff were required.

The deployment layer now includes dedicated Ansible roles for NATS and the Go
worker. Non-billable CI installs the pinned NATS release onto an Ubuntu runner,
renders the JetStream and systemd configuration, deploys the controller-built
worker, runs the playbook a second time at `changed=0`, publishes a JetStream
event, and requires its PostgreSQL delivery row.

The existing three-host AWS runner is wired to place these messaging services
on the **private app EC2** as an interim topology: systemd Flask receives
`NATS_URL` directly, while k3s Pods receive the same private endpoint through
a runtime-only ConfigMap. The worker connects to the dedicated PostgreSQL host.
The web tier has no NATS ingress rule, and the AWS smoke play now includes a
negative web→4222 check plus a synthetic API→JetStream→worker→PostgreSQL check.

This is still **not live AWS evidence for the messaging revision**. The
September AWS screenshots predate these changes. A dedicated broker EC2,
broker-specific security group, and a new explicitly recorded live AWS run
remain future milestones.
