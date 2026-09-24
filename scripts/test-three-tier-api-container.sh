#!/usr/bin/env bash
# Isolated integration test: own Compose project, localhost-only port, no staging host.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="$ROOT/apps/three-tier-api/compose.integration.yaml"
MIGRATION="$ROOT/apps/three-tier-api/migrations/0001_incidents.sql"
EVENT_MIGRATION="$ROOT/apps/three-tier-api/migrations/0002_security_events.sql"
export COMPOSE_PROJECT_NAME="three-tier-api-test-$$"
export LAB_DB_PASSWORD="${LAB_DB_PASSWORD:-$(python3 -c 'import secrets; print(secrets.token_hex(24))')}"
export API_TEST_PORT="${API_TEST_PORT:-18080}"
BASE_URL="http://127.0.0.1:$API_TEST_PORT"

for cmd in docker curl python3; do
  command -v "$cmd" >/dev/null || { echo "Missing: $cmd" >&2; exit 1; }
done

cleanup() {
  docker compose -f "$COMPOSE" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Apply schema before Flask starts, exactly as the AWS DB play does. Repeat to
# establish migration idempotency without touching a real server.
docker compose -f "$COMPOSE" up -d postgres
for ((attempt=1; attempt<=60; attempt++)); do
  if docker compose -f "$COMPOSE" exec -T postgres \
      psql -U labuser -d labdb -tAc 'SELECT 1' >/dev/null 2>&1; then
    break
  fi
  if (( attempt == 60 )); then
    echo 'Timed out waiting for isolated PostgreSQL.' >&2
    exit 1
  fi
  sleep 2
done
for pass in first second; do
  docker compose -f "$COMPOSE" exec -T postgres \
    psql -U labuser -d labdb -v ON_ERROR_STOP=1 < "$MIGRATION" >/dev/null
  docker compose -f "$COMPOSE" exec -T postgres \
    psql -U labuser -d labdb -v ON_ERROR_STOP=1 < "$EVENT_MIGRATION" >/dev/null
done

docker compose -f "$COMPOSE" up -d --build api

wait_for_ready() {
  local attempt
  for ((attempt=1; attempt<=60; attempt++)); do
    if curl -fsS --max-time 3 "$BASE_URL/readyz" 2>/dev/null |
        python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["status"]=="ok" and d["db_result"]==1' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo 'Timed out waiting for database-backed readiness.' >&2
  docker compose -f "$COMPOSE" logs --tail 60 >&2
  return 1
}

wait_for_ready
curl -fsS --max-time 5 "$BASE_URL/health" |
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["status"]=="ok" and d["db_result"]==1'

echo '=== LabOps incident persistence through the actual API and PostgreSQL ==='
created="$(curl -fsS --max-time 8 -X POST "$BASE_URL/api/v1/incidents" \
  -H 'Content-Type: application/json' \
  --data '{"title":"Synthetic SSH alert","description":"Local-only test event","severity":"high"}')"
incident_id="$(printf '%s' "$created" | python3 -c '
import json,sys,uuid
record=json.load(sys.stdin)["incident"]
assert record["status"]=="open" and record["source"]=="manual"
assert record["title"]=="Synthetic SSH alert" and record["severity"]=="high"
print(uuid.UUID(record["id"]))
')"
curl -fsS --max-time 5 "$BASE_URL/api/v1/incidents/$incident_id" |
  python3 -c 'import json,sys; assert json.load(sys.stdin)["incident"]["title"]=="Synthetic SSH alert"'
curl -fsS --max-time 5 "$BASE_URL/api/v1/incidents?limit=2" |
  python3 -c 'import json,sys; assert len(json.load(sys.stdin)["incidents"])==1'
curl -fsS --max-time 5 -X PATCH "$BASE_URL/api/v1/incidents/$incident_id" \
  -H 'Content-Type: application/json' \
  --data '{"status":"investigating","notes":"Reviewed synthetic events"}' |
  python3 -c '
import json,sys
item=json.load(sys.stdin)["incident"]
assert item["status"]=="investigating" and item["notes"]=="Reviewed synthetic events"
'


echo '=== Attach synthetic Cowrie event; retry and conflict must not duplicate ==='
event_body='{"source":"cowrie","event_type":"cowrie.login.failed","source_event_id":"synthetic-run-1-attempt-001","source_ip":"198.51.100.23","username":"root","observed_at":"2026-09-24T12:00:00Z"}'
events_url="$BASE_URL/api/v1/incidents/$incident_id/events"
event_response="$(curl -sS --max-time 8 -w '\n%{http_code}' -X POST "$events_url" \
  -H 'Content-Type: application/json' --data "$event_body")"
[[ "${event_response##*$'\n'}" == 201 ]] || { echo 'Expected first event ingestion 201' >&2; exit 1; }
event_payload="${event_response%$'\n'*}"
event_uuid="$(printf '%s' "$event_payload" | python3 -c '
import json,sys,uuid
item=json.load(sys.stdin)["event"]
assert item["source_ip"]=="198.51.100.23"
assert item["source"]=="cowrie" and item["event_type"]=="cowrie.login.failed"
assert item["username"]=="root" and item["observed_at"]=="2026-09-24T12:00:00+00:00"
print(uuid.UUID(item["id"]))
')"
replay_response="$(curl -sS --max-time 8 -w '\n%{http_code}' -X POST "$events_url" \
  -H 'Content-Type: application/json' --data "$event_body")"
[[ "${replay_response##*$'\n'}" == 200 ]] || { echo 'Expected idempotent event replay 200' >&2; exit 1; }
printf '%s' "${replay_response%$'\n'*}" | python3 -c '
import json,sys
assert json.load(sys.stdin)["event"]["id"]==sys.argv[1]
' "$event_uuid"
conflict_status="$(curl -sS --max-time 8 -o /dev/null -w '%{http_code}' \
  -X POST "$events_url" -H 'Content-Type: application/json' \
  --data '{"source":"cowrie","event_type":"cowrie.login.failed","source_event_id":"synthetic-run-1-attempt-001","source_ip":"198.51.100.23","username":"admin","observed_at":"2026-09-24T12:00:00Z"}')"
[[ "$conflict_status" == 409 ]] || { echo "Expected conflicting event replay 409, got $conflict_status" >&2; exit 1; }
curl -fsS --max-time 5 "$events_url" | python3 -c '
import json,sys
items=json.load(sys.stdin)["events"]
assert len(items)==1 and items[0]["source_event_id"]=="synthetic-run-1-attempt-001"
'


echo '=== Read-only failed-login investigation: aggregation and time-window boundaries ==='
INCIDENT_ID="$incident_id" python3 - <<'PY'
import json
import os
from urllib.request import Request, urlopen

root = f"http://127.0.0.1:{os.environ['API_TEST_PORT']}/api/v1/incidents/{os.environ['INCIDENT_ID']}"
events = root + "/events"
investigation = root + "/investigations/ssh-login-failures"


def create_event(event_id, ip, username, observed_at):
    payload = json.dumps({
        "source": "cowrie",
        "event_type": "cowrie.login.failed",
        "source_event_id": event_id,
        "source_ip": ip,
        "username": username,
        "observed_at": observed_at,
    }).encode()
    req = Request(events, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=8) as response:
        assert response.status == 201
        return json.load(response)["event"]


def investigate(query):
    with urlopen(investigation + query, timeout=8) as response:
        assert response.status == 200
        return json.load(response)["investigation"]


for attempt in range(2, 6):
    create_event(f"synthetic-run-1-attempt-{attempt:03d}", "198.51.100.23",
                 "root" if attempt == 2 else "admin", "2026-09-24T12:00:00Z")
create_event("synthetic-second-ip", "203.0.113.7", "root", "2026-09-24T12:05:00Z")
create_event("synthetic-too-old", "198.51.100.23", "root", "2026-09-24T10:00:00Z")
create_event("synthetic-future", "198.51.100.23", "root", "2026-09-24T13:00:00Z")

query = "?as_of=2026-09-24T12:30:00Z&window_minutes=60&threshold=5"
report = investigate(query)
assert report["window_start"] == "2026-09-24T11:30:00+00:00"
assert report["window_end"] == "2026-09-24T12:30:00+00:00"
assert report["total_failed_logins"] == 6
assert report["distinct_source_ips"] == 2
assert report["source_ips_truncated"] is False
assert report["response_executed"] is False
assert len(report["sources"]) == 2
assert report["sources"][0]["source_ip"] == "198.51.100.23"
assert report["sources"][0]["failed_logins"] == 5
assert report["sources"][0]["distinct_usernames"] == 2
assert report["sources"][0]["threshold_met"] is True
assert report["sources"][1]["source_ip"] == "203.0.113.7"
assert report["sources"][1]["failed_logins"] == 1
assert report["sources"][1]["threshold_met"] is False

higher = investigate("?as_of=2026-09-24T12:30:00Z&threshold=6")
assert higher["total_failed_logins"] == 6
assert not any(source["threshold_met"] for source in higher["sources"])
empty = investigate("?as_of=2026-09-24T12:30:00Z&window_minutes=10")
assert empty["total_failed_logins"] == 0 and empty["sources"] == []
print("PASS: deterministic read-only investigation; per-source threshold, replay, and time filtering")
PY

investigation_url="$BASE_URL/api/v1/incidents/$incident_id/investigations/ssh-login-failures?as_of=2026-09-24T12:30:00Z"

# Stateful DB, stateless Flask: process restart must not lose the incident.
docker compose -f "$COMPOSE" restart api
wait_for_ready
curl -fsS --max-time 5 "$BASE_URL/api/v1/incidents/$incident_id" |
  python3 -c '
import json,sys
item=json.load(sys.stdin)["incident"]
assert item["title"]=="Synthetic SSH alert" and item["status"]=="investigating"
'
curl -fsS --max-time 5 "$events_url" | python3 -c '
import json,sys
assert len(json.load(sys.stdin)["events"])==8
'
curl -fsS --max-time 5 "$investigation_url" | python3 -c '
import json,sys
report=json.load(sys.stdin)["investigation"]
assert report["total_failed_logins"]==6 and report["sources"][0]["failed_logins"]==5
'

# Pause PostgreSQL without removing its Compose DNS alias. Both the existing
# readiness contract and the new incident endpoint must fail safely.
docker compose -f "$COMPOSE" pause postgres
curl -fsS --max-time 5 "$BASE_URL/healthz" |
  python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="ok"'
status="$(curl -sS --max-time 8 -o /dev/null -w '%{http_code}' "$BASE_URL/readyz")"
[[ "$status" == 503 ]] || { echo "Expected readiness 503; got $status" >&2; exit 1; }
status="$(curl -sS --max-time 8 -o /dev/null -w '%{http_code}' \
  "$BASE_URL/api/v1/incidents/$incident_id")"
[[ "$status" == 503 ]] || { echo "Expected incident API 503; got $status" >&2; exit 1; }
status="$(curl -sS --max-time 8 -o /dev/null -w '%{http_code}' "$events_url")"
[[ "$status" == 503 ]] || { echo "Expected security events API 503; got $status" >&2; exit 1; }
status="$(curl -sS --max-time 8 -o /dev/null -w '%{http_code}' "$investigation_url")"
[[ "$status" == 503 ]] || { echo "Expected investigation API 503; got $status" >&2; exit 1; }

docker compose -f "$COMPOSE" unpause postgres
wait_for_ready
curl -fsS --max-time 5 "$BASE_URL/api/v1/incidents/$incident_id" |
  python3 -c '
import json,sys
item=json.load(sys.stdin)["incident"]
assert item["status"]=="investigating" and item["source"]=="manual"
'
curl -fsS --max-time 5 "$events_url" | python3 -c '
import json,sys
items=json.load(sys.stdin)["events"]
assert len(items)==8 and items[0]["source_event_id"]=="synthetic-future"
'
curl -fsS --max-time 5 "$investigation_url" | python3 -c '
import json,sys
report=json.load(sys.stdin)["investigation"]
assert report["total_failed_logins"]==6 and report["sources"][0]["threshold_met"]
'
echo 'PASS: incident/event persistence, repeatable SSH investigation, restart, DB outage/recovery, health contracts'
