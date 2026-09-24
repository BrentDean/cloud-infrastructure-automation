# Cloud Infrastructure Automation

[![AWS three-tier validation](https://github.com/BrentDean/cloud-infrastructure-automation/actions/workflows/aws-three-tier-validation.yml/badge.svg?branch=main)](https://github.com/BrentDean/cloud-infrastructure-automation/actions/workflows/aws-three-tier-validation.yml)
[![Python API validation](https://github.com/BrentDean/cloud-infrastructure-automation/actions/workflows/python-api-validation.yml/badge.svg?branch=main)](https://github.com/BrentDean/cloud-infrastructure-automation/actions/workflows/python-api-validation.yml)

**A reproducible, disposable AWS infrastructure lab:** provision three isolated
EC2 tiers with Terraform; configure Linux services with Ansible; deploy the
same database-backed Python API using either systemd/Gunicorn or optional k3s;
test real network boundaries and application health; retain private run
evidence; and destroy billable infrastructure when finished.

The point is the *entire infrastructure lifecycle*, not a permanently hosted
demo endpoint. The original systemd variant was deployed and verified on
**September 22, 2026**. The k3s variant is implemented in
[draft PR #2](https://github.com/BrentDean/cloud-infrastructure-automation/pull/2)
and must still pass a live AWS run before being described as deployed.

## Architecture

```text
Linux workstation (Terraform + Ansible + Docker + AWS CLI)
     |
     | SSH and demo HTTP from operator's public IPv4 /32 only
     v
Public EC2  | Nginx reverse proxy + SSH bastion
     |
     | Private application SG allows only this web tier
     | TCP 8000 (systemd) or TCP 30080 (k3s NodePort)
     v
Private app EC2
     |-- baseline: Flask / Gunicorn / systemd
     `-- opt-in: k3s / Flask Deployment (2 Pods) / Service / probes
                    |
     | PostgreSQL TCP 5432, permitted from app SG only
     v
Private DB EC2 | PostgreSQL 16 / encrypted gp3 EBS
```

One VPC, three subnets, security-group-segmented traffic, public Internet
gateway, NAT gateway for private package installation, and one ephemeral
SSH key. The application and database EC2s have no public IPs. No EKS,
extra k3s server, public Kubernetes API, or public database endpoint.

| Engineering concern | Implementation |
| --- | --- |
| Provision and teardown | [Terraform AWS three-tier root](terraform/aws-three-tier/), [ephemeral runner](scripts/run-aws-three-tier.sh) |
| Configuration and verification | [Ansible plays](ansible/aws-three-tier/) and [app-tier k3s install](ansible/k3s/install.yml) |
| Shared application | [Flask API + container](apps/three-tier-api/) with `/health`, `/healthz`, `/readyz` |
| Workload orchestration | [Kubernetes manifests](kubernetes/k3s/): two replicas, probes, private-only NodePort |
| Storage exercise | Local-path PVC survives a test Pod replacement; **PostgreSQL stays on DB EC2** |
| Checks | [AWS IaC CI](.github/workflows/aws-three-tier-validation.yml), [Python/container CI](.github/workflows/python-api-validation.yml), [k3s contract CI](.github/workflows/k3s-validation.yml) |
| Security boundaries | Operator-/32 web ingress; SG-limited app/database ingress; non-root API container; runtime-only DB credential |
| Reproducibility | Fresh per-run SSH key and Terraform state, Ansible idempotency, smoke tests, destroy/recovery script |

[Architecture decisions and trade-offs](docs/architecture-decisions.md) ·
[Original AWS architecture and runbook](docs/aws-three-tier.md) ·
[Optional k3s runbook](docs/kubernetes-k3s.md) ·
[API contract and local tests](docs/three-tier-api.md)

## Verification record — distinguish observed from planned

| Capability | Evidence and status |
| --- | --- |
| Original AWS three-tier deployment | **Verified September 22, 2026** in `us-east-1`; 28 AWS resources provisioned and destroyed |
| Three-tier Ansible configuration | Verified on all three original EC2 hosts; second pass `changed=0` |
| Network boundaries | Original web→app, app→DB allowed; direct web→DB denied |
| End-to-end API | Original workstation→Nginx→Flask→PostgreSQL returned `SELECT 1` |
| Shared API container | Python tests and isolated Docker/PostgreSQL outage/recovery integration passed |
| AWS k3s optional mode | Code and offline CI implemented; **live deployment not yet verified** |
| k3s rolling updates and failure injection | Follow-up exercise; do not claim operational verification yet |
| CloudWatch/IAM/incident exercise | Planned next portfolio milestone |
| Independent PostgreSQL backup and restore with measured RPO/RTO | Planned disaster-recovery milestone |

Historical evidence from the verified **systemd** run is below. The existing
screenshots must not be represented as Kubernetes deployment evidence.

![Three AWS EC2 instances passing status checks](screenshots/aws-three-tier/01-ec2-instances.png)

![Static GitHub Actions checks](screenshots/aws-three-tier/02-github-actions-success.png)

![Provisioning, Ansible idempotency and network checks](screenshots/aws-three-tier/03-verified-run-results.png)

## Run a disposable lab

**Creating the VPC, NAT gateway, EIP and three EC2 instances incurs AWS
charges.** Check your AWS profile/account, quotas and prices first. Run from
a workstation that can remain online through teardown.

```bash
# Existing verified deployment path: original Gunicorn/systemd application
AWS_PROFILE=vps-lab bash scripts/run-aws-three-tier.sh --run

# Optional Kubernetes application variant from PR #2 (live test pending)
AWS_PROFILE=vps-lab LAB_APP_RUNTIME=k3s \
  bash scripts/run-aws-three-tier.sh --run
```

The runner restricts web access to the current operator IPv4 /32,
rejects AWS root credentials, creates an isolated private run directory,
configures and verifies infrastructure, then **attempts Terraform destroy
even on test failure**. If destroy fails, use the printed manual recovery
command and confirm cloud resources are actually gone. An AWS Budget
alert is not a spending cap, and automated workstation cleanup cannot
recover from a workstation power loss.

Terraform state, temporary SSH keys, database credentials and raw run
evidence belong **outside Git**. See
[the AWS runbook](docs/aws-three-tier.md) for cleanup and account checks.
GitHub Actions does not run `terraform apply` or `terraform destroy`.

## Supporting operational automation

The repository retains [Ansible backup automation](ansible/backup.yml)
and [infrastructure audit automation](ansible/audit.yml) for the
**separate existing Hetzner staging VPS**. They are not a deployment
target for the AWS k3s work, and the abandoned standalone Hetzner
Kubernetes proposal is not part of this project.
