#!/usr/bin/env bash
# Private localhost-only access via SSH; no public HTTP / Kubernetes API port.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TF_DIR="$ROOT/terraform/hetzner-k3s"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
LOCAL_PORT="${LOCAL_PORT:-18080}"

[[ "$LOCAL_PORT" =~ ^[0-9]+$ ]] && ((LOCAL_PORT > 1023 && LOCAL_PORT < 65536)) || {
  echo 'LOCAL_PORT must be an unprivileged TCP port' >&2
  exit 1
}
NAME="$(terraform -chdir="$TF_DIR" output -raw server_name)"
[[ "$NAME" == k3s-lab-* ]] || { echo "Refusing non-lab target" >&2; exit 1; }
IP="$(terraform -chdir="$TF_DIR" output -raw server_ipv4)"

echo "From another terminal: curl -fsS http://127.0.0.1:$LOCAL_PORT/health"
exec ssh -T -i "$SSH_KEY" -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=accept-new -o ExitOnForwardFailure=yes \
  -L "127.0.0.1:$LOCAL_PORT:127.0.0.1:18080" "labops@$IP" \
  'sudo k3s kubectl -n infra-lab port-forward --address 127.0.0.1 service/three-tier-api 18080:80'
