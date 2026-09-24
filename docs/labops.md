# LabOps: persistent security incident workflow (first application milestone)

LabOps is the application built **on** the disposable AWS three-tier lab. It
does not modify LaunchShell, TorKit, or any Hetzner staging service. This first
milestone is an incident-management foundation for future security-event ingestion
and controlled SOAR playbooks; it is **not yet a complete SOAR system**.

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
