#!/usr/bin/env bash
# Integration exercise on only the disposable private AWS application EC2:
# live Kubernetes probes, DB SELECT 1, and PVC survival across Pod deletion.
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <ephemeral-ssh-config> <run-id>" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SSH_CONFIG="$1"
RUN_ID="$2"
[[ -f "$SSH_CONFIG" && "$RUN_ID" =~ ^lab-[a-z0-9]+$ ]] || {
  echo 'Invalid ephemeral lab SSH config or AWS run ID.' >&2
  exit 1
}
remote() { ssh -T -F "$SSH_CONFIG" aws-lab-app "$@"; }

echo '=== Private application tier: node, workload and Service ==='
remote 'sudo k3s kubectl get nodes -o wide'
remote 'sudo k3s kubectl get storageclass local-path'
remote 'sudo k3s kubectl -n infra-lab get deployment,svc,pvc,pod -o wide'
remote 'sudo k3s kubectl -n infra-lab rollout status deployment/three-tier-api --timeout=180s'
replicas="$(remote 'sudo k3s kubectl -n infra-lab get deployment three-tier-api -o jsonpath={.status.availableReplicas}')"
[[ "$replicas" == 2 ]] || { echo "Expected 2 ready API replicas, got: $replicas" >&2; exit 1; }
port="$(remote 'sudo k3s kubectl -n infra-lab get service three-tier-api -o jsonpath={.spec.ports[0].nodePort}')"
[[ "$port" == 30080 ]] || { echo "Expected private NodePort 30080, got: $port" >&2; exit 1; }
uid="$(remote 'sudo k3s kubectl -n infra-lab exec deployment/three-tier-api -- id -u')"
[[ "$uid" == 10001 ]] || { echo "API is not running as the expected non-root user: $uid" >&2; exit 1; }

echo '=== In-cluster Service -> Flask -> dedicated EC2 PostgreSQL query ==='
cat <<'PY' | remote 'sudo k3s kubectl -n infra-lab exec -i deployment/three-tier-api -- python -'
import json
from urllib.request import urlopen
for path in ("/healthz", "/readyz", "/health"):
    with urlopen("http://three-tier-api" + path, timeout=10) as response:
        data = json.load(response)
        assert response.status == 200 and data["status"] == "ok", (path, data)
        if path != "/healthz":
            assert data["db"] == "connected" and data["db_result"] == 1, data
    print("PASS:", path)
PY

echo '=== Lab-only persistent volume: survive deletion of the evidence Pod ==='
claim="$(remote 'sudo k3s kubectl -n infra-lab get pvc lab-evidence -o jsonpath={.status.phase}')"
[[ "$claim" == Bound ]] || { echo "Lab PVC is not Bound: $claim" >&2; exit 1; }

remote "sudo k3s kubectl -n infra-lab exec pvc-evidence -- sh -c 'printf %s $RUN_ID > /data/run-marker'"
marker="$(remote 'sudo k3s kubectl -n infra-lab exec pvc-evidence -- cat /data/run-marker')"
[[ "$marker" == "$RUN_ID" ]] || { echo 'PVC marker write/read failed' >&2; exit 1; }
remote 'sudo k3s kubectl -n infra-lab delete pod pvc-evidence --wait=true --timeout=120s'
remote 'sudo k3s kubectl apply -f -' < "$ROOT/kubernetes/k3s/storage.yaml"
remote 'sudo k3s kubectl -n infra-lab wait --for=condition=Ready pod/pvc-evidence --timeout=240s'
marker="$(remote 'sudo k3s kubectl -n infra-lab exec pvc-evidence -- cat /data/run-marker')"
[[ "$marker" == "$RUN_ID" ]] || { echo 'PVC marker lost across Pod deletion' >&2; exit 1; }

echo 'PASS: two non-root Flask replicas, Service/NodePort, dedicated PostgreSQL SELECT 1, and PVC persistence across Pod deletion.'
