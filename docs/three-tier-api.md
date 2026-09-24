# Shared Flask/PostgreSQL application

The application source is maintained once at `apps/three-tier-api/app.py`.
The existing AWS Ansible playbook copies this file to the private EC2 app
host and continues using the Ubuntu-packaged Gunicorn/Flask/psycopg2
runtime and the original systemd service. The Dockerfile packages the
same source for the planned k3s deployment.

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
default, checks both endpoints, stops PostgreSQL, asserts liveness remains
healthy while readiness fails, then restarts PostgreSQL and verifies recovery.
Use `API_TEST_PORT` to choose another free local port. Cleanup destroys
**only that uniquely named test Compose project and its test volume**.

This milestone does not provision k3s, change the existing Hetzner
staging deployment, or independently re-run the billable AWS lab. Before
merging, confirm the GitHub Actions unit/integration jobs pass; when
re-running the AWS lab separately, require the existing idempotency,
network-segmentation, and end-to-end checks to pass before claiming
AWS deployment regression verification.
