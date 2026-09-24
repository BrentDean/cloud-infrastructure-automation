#!/usr/bin/env bash
# Deploy only to a Terraform-managed, disposable k3s-lab-* Hetzner node.
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TF_DIR="$ROOT/terraform/hetzner-k3s"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
IMAGE="localhost/three-tier-api:pr2"
NAMESPACE="infra-lab"

for bin in terraform ansible-playbook docker ssh python3; do
  command -v "$bin" >/dev/null || { echo "Missing dependency: $bin" >&2; exit 1; }
done
[[ -f "$SSH_KEY" ]] || { echo "SSH private key not found: $SSH_KEY" >&2; exit 1; }
[[ -n "${LAB_DB_PASSWORD:-}" ]] || {
  echo 'Set LAB_DB_PASSWORD in the current shell (do not save it in Git).' >&2
  exit 1
}

NAME="$(terraform -chdir="$TF_DIR" output -raw server_name)"
[[ "$NAME" == k3s-lab-* ]] || { echo "Refusing non-lab Terraform target: $NAME" >&2; exit 1; }
IP="$(terraform -chdir="$TF_DIR" output -raw server_ipv4)"
[[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "Expected IPv4 output, received: $IP" >&2
  exit 1
}
HOST="labops@$IP"
SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=12)
remote() { ssh -T "${SSH_OPTS[@]}" "$HOST" "$@"; }

INVENTORY="$(mktemp)"
trap 'rm -f "$INVENTORY"' EXIT
printf '[k3s]\n%s\n' "$IP" > "$INVENTORY"

echo "Target: $NAME ($IP). Existing staging VPS is not contacted."
echo 'Waiting for SSH on the dedicated node...'
available=false
for ((i=1; i<=40; i++)); do
  if remote 'true' >/dev/null 2>&1; then available=true; break; fi
  sleep 5
done
[[ "$available" == true ]] || { echo "SSH unavailable: $HOST" >&2; exit 1; }

echo 'Installing/configuring k3s using Ansible...'
ANSIBLE_SSH_COMMON_ARGS='-o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes' \
  ansible-playbook -i "$INVENTORY" -u labops --private-key "$SSH_KEY" \
  "$ROOT/ansible/k3s/install.yml"

echo 'Building the shared Flask image locally; importing into private k3s containerd...'
docker build -t "$IMAGE" "$ROOT/apps/three-tier-api"
docker save "$IMAGE" | remote 'sudo k3s ctr -n k8s.io images import -'

echo 'Applying namespace and private database Secret...'
remote 'sudo k3s kubectl apply -f -' < "$ROOT/kubernetes/k3s/namespace.yaml"
printf '%s' "$LAB_DB_PASSWORD" |
  remote "sudo k3s kubectl -n $NAMESPACE create secret generic db-auth --from-file=password=/dev/stdin --dry-run=client -o yaml | sudo k3s kubectl apply -f -"

echo 'Deploying persistent PostgreSQL, then the application...'
remote 'sudo k3s kubectl apply -f -' < "$ROOT/kubernetes/k3s/postgres.yaml"
remote "sudo k3s kubectl -n $NAMESPACE rollout status statefulset/postgres --timeout=300s"
remote 'sudo k3s kubectl apply -f -' < "$ROOT/kubernetes/k3s/app.yaml"
# Importing the same local image tag is not itself a Deployment spec change.
remote "sudo k3s kubectl -n $NAMESPACE rollout restart deployment/three-tier-api"
remote "sudo k3s kubectl -n $NAMESPACE rollout status deployment/three-tier-api --timeout=300s"

echo 'Running in-cluster API, PostgreSQL, and volume checks...'
SSH_KEY="$SSH_KEY" "$ROOT/scripts/k3s/verify.sh"
echo 'PASS: isolated k3s deployment and in-cluster database-backed service'
