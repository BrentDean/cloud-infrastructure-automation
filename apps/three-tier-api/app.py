"""Shared Flask/PostgreSQL API for the AWS and Kubernetes infrastructure labs."""

import os

import psycopg2
from flask import Flask, jsonify

app = Flask(__name__)


def _database_ping():
    """Check the actual database dependency, not just an open TCP port."""
    with psycopg2.connect(
        host=os.environ["PGHOST"],
        dbname=os.getenv("PGDATABASE", "labdb"),
        user=os.getenv("PGUSER", "labuser"),
        password=os.environ["PGPASSWORD"],
        connect_timeout=3,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone()[0]


@app.get("/healthz")
def healthz():
    """Liveness: a database outage must not cause Flask restart loops."""
    return jsonify(status="ok", role="app")


@app.get("/readyz")
def readyz():
    """Readiness: receive requests only while the database is usable."""
    try:
        result = _database_ping()
        if result != 1:
            raise RuntimeError("Database returned an unexpected probe result")
        return jsonify(status="ok", role="app", db="connected", db_result=result)
    except Exception:
        app.logger.exception("Database readiness query failed")
        return jsonify(status="error", role="app", db="unavailable"), 503


@app.get("/health")
def health():
    """Preserve the original AWS end-to-end smoke-test response contract."""
    return readyz()
