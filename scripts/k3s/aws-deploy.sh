#!/usr/bin/env bash
# K3s only on the private AWS application EC2 host, reached through the bastion.
# Called by run-aws-three-tier.sh after PostgreSQL and Nginx are configured.
set -Eeuo pipefail
umask 077

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 <ephemeral-ssh-config> <app-private-ip> <db-private-ip> <evidence-dir>" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SSH_CONFIG="$1"
APP_IP="$2"
DB_IP="$3"
EVIDENCE_DIR="$4"
IMAGE="localhost/three-tier-api:pr2"
ANSIBLE_PLAYBOOK="${ANSIBLE_PLAYBOOK:-$HOME/.local/bin/ansible-playbook}"

[[ "$LAB_APP_RUNTIME" == k3s ]] || { echo 'Refusing k3s install outside opted-in AWS mode.' >&2; exit 1; }
[[ -f "$SSH_CONFIG" && -f "$EVIDENCE_DIR/../inventory.ini" ]] || {
  echo 'Missing ephemeral AWS lab SSH config or inventory.' >&2
  exit 1
}
[[ -n "${LAB_DB_PASSWORD:-}" ]] || { echo 'Missing runtime PostgreSQL password.' >&2; exit 1; }
[[ -x "$ANSIBLE_PLAYBOOK" ]] || { echo "Missing Ansible executable: $ANSIBLE_PLAYBOOK" >&2; exit 1; }

# Ensure the SSH configuration points at the Terraform-created private app
# host, not staging or some other workstation SSH alias.
resolved="$(ssh -F "$SSH_CONFIG" -G aws-lab-app | awk '$1 == "hostname" {print $2; exit}')"
[[ "$resolved" == "$APP_IP" ]] || {
  echo "Refusing SSH target: expected private app $APP_IP, got $resolved" >&2
  exit 1
}
python3 - "$APP_IP" "$DB_IP" <<'PY'
import ipaddress
import sys
for address in sys.argv[1:]:
    ip = ipaddress.ip_address(address)
    if ip.version != 4 or not ip.is_private:
        raise SystemExit("Expected the Terraform-created private app/database IPv4")
PY

remote() { ssh -T -F "$SSH_CONFIG" aws-lab-app "$@"; }

echo "Installing k3s on private AWS app tier $APP_IP through the existing web bastion..."
"$ANSIBLE_PLAYBOOK" -i "$EVIDENCE_DIR/../inventory.ini" \
  --ssh-common-args "-F $SSH_CONFIG" \
  "$ROOT/ansible/k3s/install.yml" | tee "$EVIDENCE_DIR/k3s-ansible.log"

echo 'Building the shared Flask image for EC2 amd64 and importing to private containerd...'
docker build --platform linux/amd64 -t "$IMAGE" "$ROOT/apps/three-tier-api"
docker save "$IMAGE" | remote 'sudo k3s ctr -n k8s.io images import -'

echo 'Creating isolated namespace, runtime-only DB endpoint and DB Secret...'
remote 'sudo k3s kubectl apply -f -' < "$ROOT/kubernetes/k3s/namespace.yaml"
remote "sudo k3s kubectl -n infra-lab create configmap db-endpoint --from-literal=host=$DB_IP --dry-run=client -o yaml | sudo k3s kubectl apply -f -"
printf '%s' "$LAB_DB_PASSWORD" |
  remote 'sudo k3s kubectl -n infra-lab create secret generic db-auth --from-file=password=/dev/stdin --dry-run=client -o yaml | sudo k3s kubectl apply -f -'

echo 'Applying the non-production persistent-volume smoke-test Pod and two API replicas...'
remote 'sudo k3s kubectl apply -f -' < "$ROOT/kubernetes/k3s/storage.yaml"
remote 'sudo k3s kubectl apply -f -' < "$ROOT/kubernetes/k3s/app.yaml"
remote 'sudo k3s kubectl -n infra-lab rollout status deployment/three-tier-api --timeout=360s'
remote 'sudo k3s kubectl -n infra-lab wait --for=condition=Ready pod/pvc-evidence --timeout=240s'
echo 'K3s workload deployment completed; AWS bastion and dedicated PostgreSQL host are unchanged.'
