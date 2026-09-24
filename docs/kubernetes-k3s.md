# AWS three-tier infrastructure — optional private k3s application runtime

**Implementation status:** **live verified in AWS on September 24, 2026**.
The private k3s application variant passed two-replica rollout, DB-backed
health, network isolation, Pod-level PVC persistence and complete Terraform
teardown (28 managed resources destroyed). See the [live verification record](live-verification-2026-09-24.md).
The original systemd/Gunicorn variant was separately verified on September 22.

## Architecture

Use the original `terraform/aws-three-tier` root and
`scripts/run-aws-three-tier.sh`, not a fourth VM or a second provider.
The default `LAB_APP_RUNTIME=systemd` preserves the existing application
delivery. Set `LAB_APP_RUNTIME=k3s` to switch *only* the private application
tier; the original PostgreSQL database and Nginx bastion tiers remain intact.

```text
Workstation /32 -> web EC2 (public subnet)
                    Nginx /health + SSH bastion
                         |
                    TCP 30080, web SG only
                         v
                    app EC2 (private subnet; t3.medium default)
                    k3s NodePort 30080 -> Flask Service
                                             |
                                Flask Deployment, 2 non-root Pods
                                liveness /healthz, readiness /readyz
                                             |
                            PostgreSQL TCP 5432, app SG only
                                             v
                    db EC2 (private subnet): PostgreSQL 16
                    encrypted gp3 root EBS 12 GiB
```

The original mode still proxies web -> app:8000 with systemd Gunicorn.
In k3s mode the AWS security-group rule changes to port 30080; Ansible
configures Nginx and the smoke test to use that same port, and skips only
the systemd application play. DB-to-app access remains security-group
restricted, and the web tier cannot connect directly to PostgreSQL.

The k3s Kubernetes API (6443), NodePort (30080), pod network, and
PostgreSQL are not exposed to the workstation or Internet through AWS
security-group ingress. Port 80 and SSH on web are restricted to the
operator's public IPv4 /32. An SSH config in the private temporary run
directory reaches the app via the existing bastion; no additional
jumpbox, ELB, EKS cluster, public container registry, or extra EC2
instance is required.

**Persistence distinctions:** PostgreSQL data resides on the dedicated
DB EC2's encrypted gp3 root EBS, with `delete_on_termination=true`;
destroying the full lab removes that data. The additional 1 GiB
Kubernetes local-path PVC is intentionally **only a non-production test
volume**. Its marker persists across deletion/replacement of its Pod,
but not across deletion of the EC2 app instance. Neither volume is an
off-instance disaster-recovery backup. Independent DB backups and measured
restore are planned for Project 3.

## Prerequisites and cost controls

Requires existing configured, non-root AWS CLI credentials, AWS account
permission/quota to create the original VPC/EC2/NAT/EIP resources,
Terraform, Ansible, Python 3, SSH, and a running local Docker daemon.
Ansible defaults to `~/.local/bin/ansible-playbook`; set
`ANSIBLE_PLAYBOOK` if installed elsewhere. The original script generates
a fresh SSH key, restricts access to the current public /32, creates
an isolated private Terraform state, generates a new ephemeral database
password, and attempts destruction in its EXIT trap.

AWS resources cost money during the run, especially the NAT gateway,
EIP, three EC2 instances and EBS volumes. NAT gateway provisioning commonly
takes approximately **2–5 minutes** (sometimes longer). Terraform may print
repeated `aws_nat_gateway.lab: Still creating...` lines during this stage;
keep the runner open through testing and cleanup. The app instance defaults to
`t3.medium` (two vCPU/four GiB), while web and DB remain `t3.small`
unless overridden. Default local hold time is zero; `LAB_HOLD_MINUTES`
may be 0–180. No GitHub Actions workflow provisions cloud resources.
Review EC2/NAT pricing, quotas and AWS Budget notifications separately:
budget alerts are not a hard spending cap.

An unsuccessful `terraform destroy` is not silent: the original runner
prints its private recovery directory and the
`scripts/destroy-aws-three-tier.sh` recovery command. Independently
check AWS resources and billing after each run. Do not delete the private
state directory while any AWS lab resource still exists.

## Launch and verify (explicitly billable)

On your workstation, after reviewing the code and billable resources:

```bash
cd /mnt/hyperV/projects/vps-infrastructure
git switch main

# Confirm your intended AWS CLI profile, not an account root identity.
AWS_PROFILE=vps-lab aws sts get-caller-identity

# Check Docker access before any cloud provisioning:
docker info >/dev/null

# One command reproduces the September 24 live-verified path:
# Terraform provision -> Ansible -> k3s ->
# Kubernetes Service/DB/PVC checks -> negative network smoke ->
# external /health verification -> Terraform destroy.
AWS_PROFILE=vps-lab LAB_APP_RUNTIME=k3s \
  bash scripts/run-aws-three-tier.sh --run
```

If your local Ansible is elsewhere, set
`ANSIBLE_PLAYBOOK=/absolute/path/to/ansible-playbook`.
Run the script from a terminal you will not close prematurely;
Ctrl-C also attempts Terraform destroy. The runner prints the
private run directory and retains evidence there. Examples:

```text
$HOME/.local/state/vps-infrastructure/aws-three-tier/run.XXXXXXXX/
  evidence/
    configure-first.log
    configure-second.log
    k3s-ansible.log
    k3s-deploy.log
    k3s-verification.log
    smoke-test.log
    external-health.json
    run-summary.txt
```

During the run it builds the **same Flask source** used by the systemd
variant with `docker build --platform linux/amd64`, imports the image
through the SSH bastion to private k3s containerd, and deploys
`localhost/three-tier-api:pr2` with `imagePullPolicy: Never`.
PostgreSQL remains installed through the existing AWS DB playbook.
Kubernetes gets DB private IP through a runtime ConfigMap and password
through a runtime Secret, not a committed manifest or Terraform state.
Secrets encryption at rest is enabled for the single-node k3s datastore.

Verification asserts two available Flask Pods, a non-root process,
Cluster Service DNS, `/healthz`, `/readyz`, and the legacy `/health`
with a real `SELECT 1` from the dedicated DB EC2 instance. The
web host can reach the app NodePort but not the DB port directly;
external operator-/32 Nginx -> k3s -> DB health JSON is also saved.

The Kubernetes PVC smoke test writes a run marker, deletes **only**
the dedicated non-production `pvc-evidence` Pod (not the PVC), recreates
that Pod, and verifies the marker survived. It is explicitly a
Pod-lifecycle test, not full EC2 or region disaster recovery.

To inspect the API over a private SSH tunnel before automatic teardown,
set a temporary hold for the live demo:

```bash
AWS_PROFILE=vps-lab LAB_APP_RUNTIME=k3s LAB_HOLD_MINUTES=30 \
  bash scripts/run-aws-three-tier.sh --run

# In a second terminal while the first is holding resources:
bash scripts/k3s/port-forward.sh "/path/printed/by/runner/ssh_config"
curl -fsS http://127.0.0.1:18080/readyz
```

Do not commit the private run directory, credentials, Terraform state,
or any database passwords. Once the run returns, confirm the output
says Terraform destruction completed. Do not leave the hold set for
unattended runs.

## Operator checks

Run the non-billable checks anytime:

```bash
terraform fmt -check -recursive terraform/aws-three-tier
terraform -chdir=terraform/aws-three-tier init -backend=false
terraform -chdir=terraform/aws-three-tier validate
python3 scripts/k3s/validate_manifests.py  # needs PyYAML
bash -n scripts/k3s/*.sh scripts/run-aws-three-tier.sh
```

The Kubernetes CI workflow and original AWS Terraform/Ansible workflow
run automatically on PRs and never create cloud resources. Successful static checks and local Docker integration tests are distinct
from the **September 24 live AWS deployment** documented in the
[live verification record](live-verification-2026-09-24.md).

## Teardown and later milestones

The original AWS runner attempts Terraform destroy even after failure.
Use its printed recovery command if teardown fails. Retain any needed
evidence **after verifying no billable lab resources remain**. Planned extensions to this same portfolio asset include Kubernetes
rollout/failure-recovery exercises, CloudWatch/IAM incident response,
and a genuinely independent PostgreSQL backup/rebuild test with measured
RPO/RTO. These are not part of the completed September 24 verification.
