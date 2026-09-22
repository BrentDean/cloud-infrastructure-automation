#!/usr/bin/env bash
# Manual recovery when the normal runner could not destroy the temporary lab.
set -Eeuo pipefail
if [[ $# -ne 1 || ! -d "$1/terraform" || ! -f "$1/terraform/terraform.tfstate" ]]; then
  echo "Usage: AWS_PROFILE=vps-lab $0 /absolute/path/to/run.DIRECTORY" >&2
  exit 2
fi
RUN_DIR="$(cd "$1" && pwd)"
export AWS_PROFILE="${AWS_PROFILE:-vps-lab}" AWS_PAGER=''
echo "Destroying only resources recorded in: $RUN_DIR/terraform/terraform.tfstate" >&2
terraform -chdir="$RUN_DIR/terraform" destroy -input=false -auto-approve
terraform -chdir="$RUN_DIR/terraform" state list | cat
echo 'Inspect AWS EC2, NAT gateways, Elastic IPs, and VPC to confirm cleanup.'
