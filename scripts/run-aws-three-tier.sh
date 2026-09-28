#!/usr/bin/env bash
# Disposable AWS VPC: Terraform -> cloud-init -> Ansible -> tests -> destroy.
set -Eeuo pipefail
umask 077

if [[ "${1:-}" != '--run' || $# -ne 1 ]]; then
  echo "Usage: AWS_PROFILE=vps-lab $0 --run" >&2
  echo 'Creates BILLABLE AWS resources, then attempts to destroy them on exit.' >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/terraform/aws-three-tier"
ANSIBLE="$ROOT/ansible/aws-three-tier"
ANSIBLE_PLAYBOOK="${ANSIBLE_PLAYBOOK:-$HOME/.local/bin/ansible-playbook}"
RUN_ROOT="${LAB_RUN_ROOT:-$HOME/.local/state/vps-infrastructure/aws-three-tier}"
export AWS_PROFILE="${AWS_PROFILE:-vps-lab}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"
export AWS_PAGER='' ANSIBLE_NOCOLOR=1
LAB_HOLD_MINUTES="${LAB_HOLD_MINUTES:-0}"
LAB_APP_RUNTIME="${LAB_APP_RUNTIME:-systemd}"
export LAB_APP_RUNTIME
if [[ "$LAB_APP_RUNTIME" != systemd && "$LAB_APP_RUNTIME" != k3s ]]; then
  echo 'LAB_APP_RUNTIME must be systemd or k3s.' >&2
  exit 2
fi
if [[ "$LAB_APP_RUNTIME" == k3s ]]; then
  for cmd in docker; do
    command -v "$cmd" >/dev/null || { echo "Missing k3s prerequisite: $cmd" >&2; exit 1; }
  done
  docker info >/dev/null || { echo 'Docker daemon unavailable on workstation.' >&2; exit 1; }
fi
export TF_VAR_app_runtime="$LAB_APP_RUNTIME"

for cmd in terraform aws python3 ssh ssh-keygen openssl curl flock tee; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing prerequisite: $cmd" >&2
    exit 1
  fi
done
if [[ ! -x "$ANSIBLE_PLAYBOOK" ]]; then
  echo "Missing Ansible: $ANSIBLE_PLAYBOOK" >&2
  exit 1
fi
if [[ ! "$LAB_HOLD_MINUTES" =~ ^[0-9]+$ ]] || (( LAB_HOLD_MINUTES > 180 )); then
  echo 'LAB_HOLD_MINUTES must be 0-180.' >&2
  exit 1
fi
if [[ ! -f "$SOURCE/versions.tf" || ! -f "$ANSIBLE/configure.yml" ]]; then
  echo 'Three-tier bundle not installed completely.' >&2
  exit 1
fi

mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"
exec 9>"$RUN_ROOT/.lock"
flock -n 9 || { echo 'Another three-tier lab is running.' >&2; exit 1; }

# Validate credentials and the caller before creating a Terraform state file.
CALLER_ARN="$(aws sts get-caller-identity --query Arn --output text)"

if [[ "$CALLER_ARN" == *:root ]]; then
  echo "ERROR: Refusing to deploy AWS infrastructure as root." >&2
  exit 1
fi

echo "AWS caller: $CALLER_ARN"
if [[ -n "${LAB_ALLOWED_CIDR:-}" ]]; then
  ALLOWED_CIDR="$LAB_ALLOWED_CIDR"
else
  MY_IP="$(curl -4fsS --connect-timeout 10 --max-time 20 https://checkip.amazonaws.com | tr -d '\r\n')"
  ALLOWED_CIDR="$MY_IP/32"
fi
python3 - "$ALLOWED_CIDR" <<'PY'
import ipaddress, sys
network = ipaddress.ip_network(sys.argv[1], strict=True)
if network.version != 4 or network.prefixlen != 32 or not network.network_address.is_global:
    raise SystemExit('Expected a public IPv4 /32 for LAB_ALLOWED_CIDR')
PY

WORK="$(mktemp -d "$RUN_ROOT/run.XXXXXXXX")"
mkdir -p "$WORK/terraform" "$WORK/evidence"
cp "$SOURCE"/*.tf "$SOURCE/cloud-init.yaml" "$SOURCE/.terraform.lock.hcl" "$WORK/terraform/"
chmod 700 "$WORK"
echo "Private run directory: $WORK"
RUN_ID="lab-$(basename "$WORK" | cut -d . -f 2 | tr '[:upper:]' '[:lower:]')"
EXPIRES_AT="$(date -u -d '+4 hours' '+%Y-%m-%dT%H:%M:%SZ')"
ssh-keygen -q -t ed25519 -N '' -C "aws-three-tier-$RUN_ID" -f "$WORK/id_ed25519"

python3 - "$WORK/terraform/lab.auto.tfvars.json" "$RUN_ID" "$EXPIRES_AT" "$ALLOWED_CIDR" "$AWS_REGION" "$WORK/id_ed25519.pub" "$LAB_APP_RUNTIME" <<'PY'
import json, pathlib, sys
p, run_id, expires, cidr, region, pub, app_runtime = sys.argv[1:]
pathlib.Path(p).write_text(json.dumps({
    'run_id': run_id, 'expires_at': expires, 'allowed_cidr': cidr,
    'aws_region': region, 'ssh_public_key': pathlib.Path(pub).read_text().strip(),
    'app_runtime': app_runtime,
}, indent=2) + '\n')
PY

export TF_PLUGIN_CACHE_DIR="${TF_PLUGIN_CACHE_DIR:-$HOME/.cache/terraform-plugin-cache}"
mkdir -p "$TF_PLUGIN_CACHE_DIR"
TF="terraform -chdir=$WORK/terraform"
ARMED=0
cleanup() {
  local prior=$?
  trap - EXIT INT TERM
  if (( ARMED )); then
    echo "Destroying AWS resources for $RUN_ID ..." >&2
    if ! terraform -chdir="$WORK/terraform" destroy -input=false -auto-approve -no-color; then
      echo "CRITICAL: destroy failed. Terraform state and recovery files remain in $WORK" >&2
      echo "Retry: AWS_PROFILE=$AWS_PROFILE $ROOT/scripts/destroy-aws-three-tier.sh $WORK" >&2
      prior=1
    else
      rm -f -- "$WORK/id_ed25519"
      echo "Terraform destroy completed; state and evidence retained at $WORK" >&2
    fi
  fi
  exit "$prior"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

terraform -chdir="$WORK/terraform" init -input=false -backend=false -no-color
terraform -chdir="$WORK/terraform" fmt -check
terraform -chdir="$WORK/terraform" validate -no-color
terraform -chdir="$WORK/terraform" plan -input=false -no-color -out="$WORK/terraform/lab.tfplan"
ARMED=1
echo 'Provisioning AWS infrastructure: NAT gateway creation commonly takes approximately 2–5 minutes (sometimes longer).'
echo 'Repeating "Still creating..." messages are normal; keep this terminal open through testing and teardown.'
terraform -chdir="$WORK/terraform" apply -input=false -auto-approve -no-color "$WORK/terraform/lab.tfplan"

WEB_IP="$(terraform -chdir="$WORK/terraform" output -raw web_public_ip)"
WEB_PRIV="$(terraform -chdir="$WORK/terraform" output -raw web_private_ip)"
APP_IP="$(terraform -chdir="$WORK/terraform" output -raw app_private_ip)"
DB_IP="$(terraform -chdir="$WORK/terraform" output -raw db_private_ip)"
python3 - "$WEB_IP" "$WEB_PRIV" "$APP_IP" "$DB_IP" <<'PY'
import ipaddress, sys
web, webpriv, app, db = (ipaddress.ip_address(x) for x in sys.argv[1:])
if not web.is_global or not all(ip.is_private for ip in (webpriv, app, db)):
    raise SystemExit('Unexpected public/private EC2 IP allocation')
PY

SSH_CONFIG="$WORK/ssh_config"
cat > "$SSH_CONFIG" <<EOF_SSH
Host aws-lab-web
  HostName $WEB_IP
  User ubuntu
  IdentityFile $WORK/id_ed25519
  IdentitiesOnly yes
  BatchMode yes
  StrictHostKeyChecking accept-new
  UserKnownHostsFile $WORK/known_hosts
  ConnectTimeout 8
Host aws-lab-app
  HostName $APP_IP
  User ubuntu
  IdentityFile $WORK/id_ed25519
  IdentitiesOnly yes
  BatchMode yes
  StrictHostKeyChecking accept-new
  UserKnownHostsFile $WORK/known_hosts
  ConnectTimeout 8
  ProxyCommand ssh -F $SSH_CONFIG -W %h:%p aws-lab-web
Host aws-lab-db
  HostName $DB_IP
  User ubuntu
  IdentityFile $WORK/id_ed25519
  IdentitiesOnly yes
  BatchMode yes
  StrictHostKeyChecking accept-new
  UserKnownHostsFile $WORK/known_hosts
  ConnectTimeout 8
  ProxyCommand ssh -F $SSH_CONFIG -W %h:%p aws-lab-web
EOF_SSH

cat > "$WORK/inventory.ini" <<EOF_INVENTORY
[lab_web]
web ansible_host=aws-lab-web lab_private_ip=$WEB_PRIV
[lab_app]
app ansible_host=aws-lab-app lab_private_ip=$APP_IP
[lab_db]
db ansible_host=aws-lab-db lab_private_ip=$DB_IP
[aws_lab:children]
lab_web
lab_app
lab_db
[aws_lab:vars]
ansible_user=ubuntu
ansible_python_interpreter=/usr/bin/python3
EOF_INVENTORY

for role in web app db; do
  echo "Waiting for $role SSH ..."
  ready=0
  for (( attempt=1; attempt<=60; attempt++ )); do
    if ssh -F "$SSH_CONFIG" "aws-lab-$role" true >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 5
  done
  (( ready )) || { echo "SSH never became available for $role" >&2; exit 1; }
done

# Short-lived, local-only database credential; not sent to Terraform or Git.
export LAB_DB_PASSWORD="$(openssl rand -hex 24)"
ANSIBLE_ARGS=(-i "$WORK/inventory.ini" --ssh-common-args "-F $SSH_CONFIG")
CONFIGURE_ARGS=()
if [[ "$LAB_APP_RUNTIME" == k3s ]]; then
  # Keep PostgreSQL and Nginx on their original dedicated EC2 hosts.
  # Replace only the private app tier's systemd Gunicorn with single-node k3s.
  CONFIGURE_ARGS=(--skip-tags systemd_app -e lab_app_port=30080)
fi
"$ANSIBLE_PLAYBOOK" "${ANSIBLE_ARGS[@]}" "${CONFIGURE_ARGS[@]}" "$ANSIBLE/configure.yml" | tee "$WORK/evidence/configure-first.log"
if [[ "$LAB_APP_RUNTIME" == k3s ]]; then
  "$ROOT/scripts/k3s/aws-deploy.sh" "$SSH_CONFIG" "$APP_IP" "$DB_IP" "$WORK/evidence" \
    | tee "$WORK/evidence/k3s-deploy.log"
fi
"$ANSIBLE_PLAYBOOK" "${ANSIBLE_ARGS[@]}" "${CONFIGURE_ARGS[@]}" "$ANSIBLE/configure.yml" | tee "$WORK/evidence/configure-second.log"
python3 - "$WORK/evidence/configure-second.log" "$LAB_APP_RUNTIME" <<'PY'
import pathlib, re, sys
s = pathlib.Path(sys.argv[1]).read_text()
for host in ('web', 'db') if sys.argv[2] == 'k3s' else ('web', 'app', 'db'):
    p = rf'(?m)^\s*{host}\s*:\s*ok=\d+\s+changed=0\s+unreachable=0\s+failed=0\b'
    if not re.search(p, s):
        raise SystemExit(f'Idempotency verification failed for {host}')
print('PASS: second configuration run changed=0 on configured EC2 tiers')
PY
"$ANSIBLE_PLAYBOOK" "${ANSIBLE_ARGS[@]}" "${CONFIGURE_ARGS[@]}" "$ANSIBLE/smoke-test.yml" | tee "$WORK/evidence/smoke-test.log"
if [[ "$LAB_APP_RUNTIME" == k3s ]]; then
  "$ROOT/scripts/k3s/aws-verify.sh" "$SSH_CONFIG" "$RUN_ID" \
    | tee "$WORK/evidence/k3s-verification.log"
fi

curl --fail --silent --show-error --max-time 20 --retry 6 --retry-delay 3 \
  "http://$WEB_IP/health" > "$WORK/evidence/external-health.json"
python3 - "$WORK/evidence/external-health.json" <<'PY'
import json, pathlib, sys
r = json.loads(pathlib.Path(sys.argv[1]).read_text())
if r.get('status') != 'ok' or r.get('db') != 'connected' or r.get('db_result') != 1:
    raise SystemExit('End-to-end public HTTP -> API -> DB smoke test failed')
print('PASS: workstation -> web -> app -> PostgreSQL returned SELECT 1')
PY

printf 'RUN_ID=%s\nREGION=%s\nAPP_RUNTIME=%s\nPUBLIC_WEB_IP=%s\nEXPIRES_AT=%s\n' \
  "$RUN_ID" "$AWS_REGION" "$LAB_APP_RUNTIME" "$WEB_IP" "$EXPIRES_AT" > "$WORK/evidence/run-summary.txt"
echo "PASS: three-tier provisioning, configuration, idempotency, connectivity, network restrictions."
echo "Evidence: $WORK/evidence"
if (( LAB_HOLD_MINUTES > 0 )); then
  echo "Holding the lab for $LAB_HOLD_MINUTES minute(s); Ctrl-C triggers destroy."
  sleep "$(( LAB_HOLD_MINUTES * 60 ))"
fi
