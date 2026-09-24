#!/usr/bin/env bash
# Read-only cluster inspection; makes no changes to existing or staging hosts.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TF_DIR="$ROOT/terraform/hetzner-k3s"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
NAME="$(terraform -chdir="$TF_DIR" output -raw server_name)"
[[ "$NAME" == k3s-lab-* ]] || { echo "Not a k3s lab node: $NAME" >&2; exit 1; }
IP="$(terraform -chdir="$TF_DIR" output -raw server_ipv4)"
HOST="labops@$IP"
SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new)
remote() { ssh -T "${SSH_OPTS[@]}" "$HOST" "$@"; }

remote 'sudo k3s kubectl get nodes -o wide'
remote 'sudo k3s kubectl get storageclass local-path'
remote 'sudo k3s kubectl -n infra-lab get deploy,statefulset,svc,pvc,pods -o wide'
remote 'sudo k3s kubectl -n infra-lab rollout status statefulset/postgres --timeout=180s'
remote 'sudo k3s kubectl -n infra-lab rollout status deployment/three-tier-api --timeout=180s'
pvc="$(remote 'sudo k3s kubectl -n infra-lab get pvc postgres-data-postgres-0 -o jsonpath={.status.phase}')"
[[ "$pvc" == Bound ]] || { echo "PostgreSQL PVC not bound: $pvc" >&2; exit 1; }

# Exec into the application to prove cluster DNS -> ClusterIP Service -> Flask
# -> real PostgreSQL SELECT 1, not merely that the Pods report Running.
cat <<'PY' | remote 'sudo k3s kubectl -n infra-lab exec -i deployment/three-tier-api -- python -'
import json
from urllib.request import urlopen

for path in ("/healthz", "/readyz", "/health"):
    with urlopen("http://three-tier-api" + path, timeout=8) as response:
        assert response.status == 200, (path, response.status)
        data = json.load(response)
        assert data["status"] == "ok", data
        if path != "/healthz":
            assert data["db"] == "connected" and data["db_result"] == 1, data
    print("PASS:", path)
PY
echo 'PASS: PVC Bound, application Service DNS, and PostgreSQL query'
