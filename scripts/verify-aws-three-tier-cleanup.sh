#!/usr/bin/env bash
# Verify that the disposable AWS lab left no active top-level resources behind.
set -Eeuo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^lab-[a-z0-9]+$ ]]; then
  echo "Usage: $0 lab-RUNID" >&2
  exit 2
fi

RUN_ID="$1"
AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION" AWS_PAGER=''

for cmd in aws; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing prerequisite: $cmd" >&2; exit 1; }
done

caller_arn="$(aws sts get-caller-identity --query Arn --output text)"
[[ "$caller_arn" != *:root ]] || { echo "ERROR: refusing cleanup verification as AWS root" >&2; exit 1; }

collect_residuals() {
  local vpcs instances nat eips keys
  vpcs="$(aws ec2 describe-vpcs \
    --filters "Name=tag:RunId,Values=$RUN_ID" \
    --query 'Vpcs[].VpcId' --output text)"
  instances="$(aws ec2 describe-instances \
    --filters "Name=tag:RunId,Values=$RUN_ID" \
      "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down" \
    --query 'Reservations[].Instances[].InstanceId' --output text)"
  nat="$(aws ec2 describe-nat-gateways \
    --filter "Name=tag:RunId,Values=$RUN_ID" \
    --query 'NatGateways[?State!=`deleted`].NatGatewayId' --output text)"
  eips="$(aws ec2 describe-addresses \
    --filters "Name=tag:RunId,Values=$RUN_ID" \
    --query 'Addresses[].AllocationId' --output text)"
  keys="$(aws ec2 describe-key-pairs \
    --filters "Name=tag:RunId,Values=$RUN_ID" \
    --query 'KeyPairs[].KeyPairId' --output text)"

  printf '%s\n' "$vpcs" "$instances" "$nat" "$eips" "$keys" |
    tr '\t' '\n' | sed '/^[[:space:]]*$/d'
}

timeout_seconds="${LAB_CLEANUP_VERIFY_TIMEOUT_SECONDS:-300}"
[[ "$timeout_seconds" =~ ^[0-9]+$ ]] || { echo "Invalid cleanup verification timeout" >&2; exit 2; }
deadline=$((SECONDS + timeout_seconds))

while :; do
  residuals="$(collect_residuals)"
  if [[ -z "$residuals" ]]; then
    echo "PASS: no active VPC, EC2, NAT gateway, Elastic IP, or key-pair resources remain for $RUN_ID"
    exit 0
  fi

  if (( SECONDS >= deadline )); then
    echo "FAIL: residual AWS resources still tagged RunId=$RUN_ID after ${timeout_seconds}s:" >&2
    printf '%s\n' "$residuals" >&2
    exit 1
  fi

  echo "Waiting for AWS cleanup to settle for $RUN_ID ..."
  sleep 10
done
