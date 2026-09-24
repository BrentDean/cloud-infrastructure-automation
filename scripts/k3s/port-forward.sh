#!/usr/bin/env bash
# Use while LAB_HOLD_MINUTES keeps the temporary AWS three-tier lab alive.
# The private app host is reached through the existing web SSH bastion.
set -Eeuo pipefail
if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <private-run-directory/ssh_config>" >&2
  exit 2
fi
SSH_CONFIG="$1"
[[ -f "$SSH_CONFIG" ]] || { echo "Missing ephemeral AWS SSH config: $SSH_CONFIG" >&2; exit 1; }
LOCAL_PORT="${LOCAL_PORT:-18080}"
[[ "$LOCAL_PORT" =~ ^[0-9]+$ ]] && (( LOCAL_PORT > 1023 && LOCAL_PORT < 65536 )) || {
  echo 'LOCAL_PORT must be an unprivileged TCP port' >&2
  exit 1
}
echo "While this runs, use: curl -fsS http://127.0.0.1:$LOCAL_PORT/health"
exec ssh -T -F "$SSH_CONFIG" \
  -o ExitOnForwardFailure=yes \
  -L "127.0.0.1:$LOCAL_PORT:127.0.0.1:18080" aws-lab-app \
  'sudo k3s kubectl -n infra-lab port-forward --address 127.0.0.1 service/three-tier-api 18080:80'
