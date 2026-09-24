#!/usr/bin/env bash
# Isolated integration test: own Compose project, localhost-only port, no staging host.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="$ROOT/apps/three-tier-api/compose.integration.yaml"
MIGRATION="$ROOT/apps/three-tier-api/migrations/0001_incidents.sql"
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

# Stateful DB, stateless Flask: process restart must not lose the incident.
docker compose -f "$COMPOSE" restart api
wait_for_ready
curl -fsS --max-time 5 "$BASE_URL/api/v1/incidents/$incident_id" |
  python3 -c '
import json,sys
item=json.load(sys.stdin)["incident"]
assert item["title"]=="Synthetic SSH alert" and item["status"]=="investigating"
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

docker compose -f "$COMPOSE" unpause postgres
wait_for_ready
curl -fsS --max-time 5 "$BASE_URL/api/v1/incidents/$incident_id" |
  python3 -c '
import json,sys
item=json.load(sys.stdin)["incident"]
assert item["status"]=="investigating" and item["source"]=="manual"
'
echo 'PASS: migration rerun; incident create/list/update; process restart; DB outage/recovery; original health contracts'
