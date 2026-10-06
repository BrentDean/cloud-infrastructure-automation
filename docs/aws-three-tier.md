# Disposable AWS three-tier infrastructure lab

**Scope:** Portfolio lab; intentionally single-AZ and ephemeral, not production-HA. Does not touch the Hetzner staging VPS or its Ansible/Restic backups.

This document describes the **original/default Gunicorn + systemd application
variant**, verified on September 22, 2026. The same Terraform root and runner
now support an *optional* private EC2 k3s variant selected by
`LAB_APP_RUNTIME=k3s`; see [AWS k3s architecture and runbook](kubernetes-k3s.md).
The historical verification results below describe only systemd mode;
**k3s mode was separately verified on September 24, 2026**. See its
[live verification record](live-verification-2026-09-24.md).

Current topology: a `10.20.0.0/16` VPC with one public web subnet and three
private subnets for application, messaging broker and PostgreSQL. The broker is
a fourth EC2 role with no public IP. The shared private route table gives
app/broker/DB outbound package access through the NAT gateway.

SSH/HTTP to web are allowed **only from your public IPv4 /32**. Application
port 8000 (or k3s NodePort 30080) is permitted only from the web security
group. NATS TCP 4222 on the broker is permitted only from the app security
group. PostgreSQL TCP 5432 is permitted from the app security group for the
API and from the broker security group for the Go consumer. SSH to app,
broker and DB is admitted only from the web/bastion security group.

The current, not-yet-live-reverified revision Ansible-manages NATS JetStream
and the Go event worker on the dedicated broker EC2. NATS monitoring remains
loopback-only. CI proves the roles install, start, run idempotently, and deliver
a JetStream event to PostgreSQL; Terraform and cross-layer tests validate the
new subnet and SG paths. The September 2026 AWS runs do **not** prove this
newer four-host topology.

The API's `/health` performs a real PostgreSQL `SELECT 1`. Ansible tests the permitted and denied network paths, including denied web→PostgreSQL and web→NATS access, verifies the whole chain through Nginx, and creates one synthetic incident to require API→JetStream→Go-worker→PostgreSQL delivery. Configuration runs twice to check that the second run reports `changed=0` for every configured host. A workstation curl verifies the public interface. The runner attempts Terraform destruction on normal completion or test failure while the workstation remains available.

## Prerequisites

Install Terraform and AWS CLI v2 on the **workstation**, not on the VPS. Install Ansible Core 2.19.x (already present at `~/.local/bin/ansible-playbook`). The current runner also builds the Go event-worker binary **before** provisioning; it uses a local Go 1.26+ toolchain when available and otherwise a working Docker daemon. AWS CLI user installer: `curl -fsSL https://awscli.amazonaws.com/v2/install.sh | bash`; run a trusted installer only after reviewing the download. Terraform: https://developer.hashicorp.com/terraform/install .

Configure `vps-lab` AWS CLI profile with appropriately limited IAM access (EC2/VPC, AMI lookup, STS; permissions also needed for tags and key pairs). Prefer AWS IAM Identity Center/SSO. Do not use root-account access keys, and do not commit credentials. Run `AWS_PROFILE=vps-lab aws sts get-caller-identity` and set a modest AWS Budget alert before first apply. A budget alert **does not terminate running resources**.

## Run

```bash
cd /mnt/hyperV/projects/vps-infrastructure
AWS_PROFILE=vps-lab ./scripts/run-aws-three-tier.sh --run
```

For the Kubernetes application variant **using the same three EC2 tiers**,
run the disposable runner with `LAB_APP_RUNTIME=k3s` after reviewing its
[separate runbook](kubernetes-k3s.md). This replaces only the app EC2's
systemd Gunicorn with k3s; the app EC2 is sized to t3.medium by default,
and Nginx reaches its NodePort 30080 only through the web security group.

To inspect the live environment for up to 60 minutes after tests:

```bash
AWS_PROFILE=vps-lab LAB_HOLD_MINUTES=60 ./scripts/run-aws-three-tier.sh --run
```

Use `TF_VAR_instance_type=t3.medium` only after confirming you want more RAM. `AWS_REGION` defaults to `us-east-1`. `LAB_ALLOWED_CIDR` may be set to your public IPv4 `/32` instead of the default checkip lookup. The SSH/HTTP rules are not opened to the whole internet.

Evidence (first and second Ansible passes, smoke test, external health JSON, run summary) is saved under `~/.local/state/vps-infrastructure/aws-three-tier/run.*/evidence/`. Run directories also include **private SSH keys** and Terraform state. Treat the entire run directory as private and never commit it. Successful runs remove their temporary SSH private key. Do not blindly wipe a run directory after a failed destroy; state is needed to retry safely.

## Cost and cleanup

NAT gateway provisioning commonly takes approximately **2–5 minutes**
(sometimes longer). Repeated `aws_nat_gateway.lab: Still creating...` lines
are expected during this AWS resource creation step; keep the runner open
until testing and Terraform teardown complete.

Billable resources in the **current unverified revision**: four EC2 instances by default (web, app, broker and DB; k3s mode uses a t3.medium app while the others default to t3.small), four small gp3 root volumes, one NAT gateway + Elastic IP, one web EC2 public IPv4, and applicable data processing / transfer. The historical September runs used the earlier three-EC2 topology. NAT incurs an hourly charge **even when idle**. `LAB_HOLD_MINUTES` is capped at 180. Run from a workstation that can stay online until destroy completes. `ExpiresAt` tag is **informational**: it does NOT trigger deletion. If the workstation loses power, Terraform cannot automatically destroy the cloud resources. Review the AWS console's EC2 instances, NAT gateways, Elastic IPs, and VPC after each lab run.

If cleanup failed, use the printed run-directory path:

```bash
AWS_PROFILE=vps-lab ./scripts/destroy-aws-three-tier.sh /home/kalibob/.local/state/vps-infrastructure/aws-three-tier/run.YOUR_ID
```

Do not delete the state or the run directory before cleanup succeeds. The manual script destroys only objects in that run's Terraform state. AWS Budgets is a billing alert, not a cap. Never enable unattended GitHub Actions apply/destroy without an independent cloud-side stale-resource cleanup mechanism.

## Portfolio narrative

Built an ephemeral, security-group-segmented AWS application stack with Terraform and cloud-init: public Nginx/bastion, private application tier, dedicated private NATS/Go-worker broker, and private PostgreSQL. Ansible manages host services and the runner exercises positive and denied network paths, database-backed health, messaging delivery, idempotency and automatic teardown. The broker revision is CI/static-validated but awaits a new live AWS run.

## Verified deployment — September 22, 2026

An end-to-end run in `us-east-1` completed successfully:

| Check | Result |
|---|---|
| Terraform apply | 28 resources created |
| Ansible configuration | Web, application, and database configured; 0 failures |
| Ansible idempotency | Second run: `changed=0` on all three hosts |
| Application to PostgreSQL | Passed |
| Web to application | Passed |
| Direct web to PostgreSQL | Blocked as intended |
| Nginx to Python to PostgreSQL | Passed |
| External HTTP `/health` | `status=ok`, `db=connected`, `db_result=1` |
| Terraform destroy | 28 resources destroyed |

The environment was a single-availability-zone demonstration, not a
high-availability production deployment. The public endpoint used HTTP
restricted to the operator's public IPv4 /32; it did not implement TLS.

Private run logs, Terraform state, generated credentials, and SSH keys
are retained outside the Git repository. Only sanitized evidence should
be published.
