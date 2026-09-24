#!/usr/bin/env bash
# Isolated integration test: own Compose project, localhost-only port, no staging host.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="$ROOT/apps/three-tier-api/compose.integration.yaml"
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

docker compose -f "$COMPOSE" up -d --build

wait_for_ready() {
  local attempt
  for ((attempt=1; attempt<=60; attempt++)); do
    if curl -fsS --max-time 3 "$BASE_URL/readyz" |
        python3 -c 'import json,sys; data=json.load(sys.stdin); assert data["status"]=="ok" and data["db_result"]==1' >/dev/null 2>&1; then
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
  python3 -c 'import json,sys; data=json.load(sys.stdin); assert data["status"]=="ok" and data["db_result"]==1'

docker compose -f "$COMPOSE" stop postgres

curl -fsS --max-time 5 "$BASE_URL/healthz" |
  python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="ok"'

status="$(curl -sS --max-time 8 -o /dev/null -w '%{http_code}' "$BASE_URL/readyz")"
if [[ "$status" != 503 ]]; then
  echo "Expected readiness 503 during PostgreSQL outage; got $status" >&2
  exit 1
fi

docker compose -f "$COMPOSE" start postgres
wait_for_ready
echo 'PASS: legacy health, liveness, readiness, DB outage, and DB recovery'
