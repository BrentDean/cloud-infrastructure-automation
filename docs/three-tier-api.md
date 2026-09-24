# Shared Flask/PostgreSQL application

The application source is maintained once at `apps/three-tier-api/app.py`.
In the default AWS deployment, Ansible copies this file to the private EC2
app host and runs it through the Ubuntu-packaged Gunicorn/Flask/psycopg2
systemd service. In the optional AWS k3s mode, the Dockerfile packages
this **same source** as two non-root Flask Pods on the *same private app EC2*.
Both modes connect to PostgreSQL on the separate private DB EC2.

## HTTP contracts

| Endpoint | Meaning | PostgreSQL outage |
| --- | --- | --- |
| `/health` | Original AWS end-to-end smoke-test contract | HTTP 503 |
| `/healthz` | Process liveness; no DB query | HTTP 200 |
| `/readyz` | Real PostgreSQL `SELECT 1`; database-dependent readiness | HTTP 503 |

Success from `/health` and `/readyz` includes
`{"status":"ok","role":"app","db":"connected","db_result":1}`.
Failure returns `{"status":"error","role":"app","db":"unavailable"}`.
The client response does not include the database exception or credentials.

Configuration: `PGHOST` and `PGPASSWORD` are required;
`PGDATABASE` defaults to `labdb` and `PGUSER` to `labuser`.
Never commit a real password. The AWS runner already generates one at
runtime and the container integration script uses a new temporary value
unless `LAB_DB_PASSWORD` is explicitly provided.

## Verification

Run Python contract tests:

```bash
python3 -m venv /tmp/three-tier-api-venv
/tmp/three-tier-api-venv/bin/pip install -r apps/three-tier-api/requirements.txt pytest
(cd apps/three-tier-api && /tmp/three-tier-api-venv/bin/python -m pytest -q tests)
```

Run a full container/PostgreSQL integration test on a Docker workstation:

```bash
bash scripts/test-three-tier-api-container.sh
```

The integration script builds the API, creates a uniquely named Compose
project and ephemeral database, binds the API only on localhost:18080 by
default, checks both endpoints, pauses PostgreSQL, asserts liveness remains
healthy while readiness fails, then unpauses PostgreSQL and verifies recovery.
Pausing retains the database container network identity and isolates the
application/database failure behavior from Docker DNS alias churn.
Use `API_TEST_PORT` to choose another free local port. Cleanup destroys
**only that uniquely named test Compose project and its test volume**.

Python and Docker integration tests do not provision AWS or k3s. The shared
API was separately verified in containers; the original AWS systemd lab was
verified before k3s mode existed. The optional Kubernetes infrastructure
requires its **own live AWS run** before claiming deployment success. See
[the integrated k3s runbook](kubernetes-k3s.md). The unrelated existing
Hetzner staging server is not changed by either AWS lab mode.
