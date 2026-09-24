"""Shared Flask API: health contracts and the first persistent LabOps incident workflow."""

import os
from uuid import UUID

import psycopg2
from flask import Flask, jsonify, request, url_for

import db

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

SEVERITIES = {"low", "medium", "high", "critical"}
STATUSES = {"open", "investigating", "resolved"}


def _database_ping():
    """Preserve the original SELECT 1 contract for both AWS application runtimes."""
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
    """Liveness must not restart the process merely because PostgreSQL is down."""
    return jsonify(status="ok", role="app")


@app.get("/readyz")
def readyz():
    """Readiness depends on the existing PostgreSQL SELECT 1 contract."""
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
    """Original AWS end-to-end smoke-test response; do not change its JSON."""
    return readyz()


def _error(code, message, status):
    return jsonify(error={"code": code, "message": message}), status


def _body(allowed):
    if not request.is_json:
        return None, _error("unsupported_media_type", "Expected application/json", 415)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, _error("invalid_json", "Expected a JSON object", 400)
    unexpected = set(payload) - allowed
    if unexpected:
        return None, _error("invalid_fields", "Unrecognized request fields", 400)
    return payload, None


def _text(payload, field, maximum, required=True):
    value = payload.get(field)
    if value is None and not required and field not in payload:
        return None
    if not isinstance(value, str):
        raise ValueError(field + " must be a string")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise ValueError(field + " must contain 1-" + str(maximum) + " characters")
    return value


def _incident_id(raw):
    try:
        return str(UUID(raw))
    except (ValueError, AttributeError):
        return None


def _db_error():
    app.logger.exception("LabOps incident database operation failed")
    return _error("database_unavailable", "Incident storage is unavailable", 503)


@app.errorhandler(413)
def payload_too_large(_exception):
    return _error("payload_too_large", "Request body exceeds 16 KiB", 413)


@app.post("/api/v1/incidents")
def create_incident():
    payload, error = _body({"title", "description", "severity"})
    if error is not None:
        return error
    try:
        title = _text(payload, "title", 120)
        description = _text(payload, "description", 2000)
        severity = payload.get("severity")
        if not isinstance(severity, str) or severity not in SEVERITIES:
            raise ValueError("severity must be low, medium, high, or critical")
    except ValueError as exc:
        return _error("validation_error", str(exc), 400)
    try:
        incident = db.create_incident(title, description, severity)
    except psycopg2.Error:
        return _db_error()
    response = jsonify(incident=incident)
    response.status_code = 201
    response.headers["Location"] = url_for("get_incident", incident_id=incident["id"])
    return response


@app.get("/api/v1/incidents")
def list_incidents():
    raw = request.args.get("limit", "20")
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 3 or not 1 <= int(raw) <= 100:
        return _error("validation_error", "limit must be an integer from 1 to 100", 400)
    try:
        incidents = db.list_incidents(int(raw))
    except psycopg2.Error:
        return _db_error()
    return jsonify(incidents=incidents)


@app.get("/api/v1/incidents/<incident_id>")
def get_incident(incident_id):
    identifier = _incident_id(incident_id)
    if identifier is None:
        return _error("validation_error", "Invalid incident UUID", 400)
    try:
        incident = db.get_incident(identifier)
    except psycopg2.Error:
        return _db_error()
    if incident is None:
        return _error("not_found", "Incident not found", 404)
    return jsonify(incident=incident)


@app.patch("/api/v1/incidents/<incident_id>")
def update_incident(incident_id):
    identifier = _incident_id(incident_id)
    if identifier is None:
        return _error("validation_error", "Invalid incident UUID", 400)
    payload, error = _body({"status", "notes"})
    if error is not None:
        return error
    if not payload:
        return _error("validation_error", "Supply status or notes", 400)
    try:
        status = payload.get("status")
        if "status" in payload and (not isinstance(status, str) or status not in STATUSES):
            raise ValueError("status must be open, investigating, or resolved")
        notes = _text(payload, "notes", 4000, required=False)
    except ValueError as exc:
        return _error("validation_error", str(exc), 400)
    try:
        incident = db.update_incident(identifier, status, notes)
    except psycopg2.Error:
        return _db_error()
    if incident is None:
        return _error("not_found", "Incident not found", 404)
    return jsonify(incident=incident)
