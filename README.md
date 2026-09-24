# Cloud Infrastructure Automation

[![AWS Three-Tier Infrastructure Validation](https://github.com/BrentDean/cloud-infrastructure-automation/actions/workflows/aws-three-tier-validation.yml/badge.svg?branch=main)](https://github.com/BrentDean/cloud-infrastructure-automation/actions/workflows/aws-three-tier-validation.yml)

Infrastructure automation and cloud engineering projects using Terraform,
Ansible, Linux, and supporting operational tooling.

This repository includes automation for an existing Hetzner VPS and a
disposable AWS three-tier environment built to exercise infrastructure
provisioning, configuration management, network segmentation, testing,
and teardown.

## AWS three-tier infrastructure lab

An ephemeral, single-availability-zone AWS environment provisioned with
Terraform and configured with Ansible.

```text
Workstation
    |
    | HTTP / SSH (operator IPv4 /32 only)
    v
Public subnet — Nginx + SSH bastion
    |
    | HTTP :8000
    v
Private application subnet — Python API
    |
    | PostgreSQL :5432
    v
Private database subnet — PostgreSQL 16
```

The VPC also includes an internet gateway and NAT gateway. Security groups
restrict inbound traffic between tiers; the database is not directly
accessible from the web tier.

### Verified deployment

On September 22, 2026, an end-to-end run in `us-east-1` completed:

| Verification | Result |
|---|---|
| Terraform provisioning | 28 resources created |
| Ansible configuration | Three hosts configured; zero failures |
| Ansible idempotency | Second run made zero changes |
| Application → PostgreSQL | Passed |
| Web → application | Passed |
| Direct web → PostgreSQL | Blocked as intended |
| External database-backed HTTP health check | Passed; PostgreSQL returned `SELECT 1` |
| Terraform teardown | 28 resources destroyed |
| Independent AWS cleanup checks | No remaining lab EC2 instances, NAT gateways, Elastic IPs, or VPCs |

The environment is deliberately temporary, single-AZ, and not a
high-availability production deployment. The demonstration endpoint uses
operator-restricted HTTP rather than public HTTPS.

**[Architecture, implementation, costs, and recovery instructions](docs/aws-three-tier.md)**

**Source:** [Terraform](terraform/aws-three-tier/) ·
[Ansible](ansible/aws-three-tier/) ·
[Deployment runner](scripts/run-aws-three-tier.sh) ·
[Static validation workflow](.github/workflows/aws-three-tier-validation.yml)

The GitHub Actions workflow checks Terraform and Ansible without creating
billable AWS infrastructure.

## Shared Python application

The same Flask/PostgreSQL health API is now maintained in
[apps/three-tier-api/](apps/three-tier-api/). The AWS Ansible playbook installs
that source file rather than embedding Python in YAML. The container image and
isolated Docker Compose integration test are the foundation for the planned
k3s Kubernetes project. The legacy AWS `/health` contract is preserved; the
new `/healthz` (process) and `/readyz` (database) endpoints support distinct
Kubernetes liveness and readiness checks.

See [application testing and architecture](docs/three-tier-api.md).
The opt-in AWS k3s deployment code is available below; live AWS Kubernetes
provisioning and end-to-end cluster validation must be performed separately.

## Optional AWS k3s application runtime

The existing **three-EC2 AWS three-tier Terraform plan** now supports an
opt-in Kubernetes runtime on its private application server. The public web
EC2 still hosts Nginx and the bastion, while PostgreSQL stays on its own
private EC2 and encrypted gp3 EBS volume. Only the application tier
changes from Gunicorn/systemd to single-node k3s with **two Flask replicas**.

```text
Workstation --operator /32--> Public EC2: Nginx + SSH bastion
                                  |
                        private NodePort :30080
                                  v
                         Private app EC2: k3s
                         Flask Deployment (2 Pods)
                         /healthz + /readyz
                                  |
                             TCP :5432
                                  v
                         Private DB EC2: PostgreSQL 16
```

The k3s application VM is sized separately (`t3.medium` by default).
A small local-path PVC demonstrates persistence across test Pod replacement;
**the database remains on the dedicated EC2 instance** rather than running
as a Kubernetes StatefulSet. No public Kubernetes API or NodePort is opened.

Run the existing ephemeral runner with `LAB_APP_RUNTIME=k3s` to select
this variant; the original `systemd` mode remains the default. Both
variants attempt automated AWS teardown after collecting verification
evidence. No live k3s AWS deployment has yet been verified.

[Architecture and runbook](docs/kubernetes-k3s.md) ·
[Static CI checks](.github/workflows/k3s-validation.yml) ·
[Kubernetes manifests](kubernetes/k3s/).

## Hetzner VPS automation

The repository also contains Ansible automation for an existing Hetzner VPS,
including [backup and recovery workflows](ansible/backup.yml).

## Security and cost controls

Cloud credentials, private SSH keys, generated database credentials,
Terraform state, and private run evidence are not intended for Git.

AWS infrastructure created by the lab is billable. The runner attempts
teardown after testing, and a separate recovery script is provided for
interrupted runs. AWS Budget alerts are notifications, not spending caps.

### Deployment evidence

Screenshots from the verified September 22, 2026 deployment.
The AWS infrastructure was subsequently destroyed.

**Three EC2 instances running with passing status checks**

![AWS EC2 instances](screenshots/aws-three-tier/01-ec2-instances.png)

**Successful GitHub Actions validation**

![GitHub Actions success](screenshots/aws-three-tier/02-github-actions-success.png)

**Ansible configuration, idempotency, network tests, and Terraform lifecycle**

![Verified deployment results](screenshots/aws-three-tier/03-verified-run-results.png)
