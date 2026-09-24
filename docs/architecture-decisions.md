# Architecture decisions: one coherent, disposable AWS portfolio lab

Status: September 24, 2026. Both systemd and optional k3s modes have passed
separate live AWS tests. This record explains the implementation and its limits;
see the [September 24 k3s verification record](live-verification-2026-09-24.md).

## 1. Reuse one three-tier AWS topology

The original Terraform module already provisions a VPC, IGW, NAT, three
subnets, three EC2 instances, security-group boundaries and operator-restricted
access. The optional k3s mode *reuses the same root, runner, credential
generation, SSH bastion and teardown*. It does not need another public server
or a second cloud provider. This yields a traceable before/after architecture:
`systemd` is the unchanged default; `k3s` changes only the private app tier.

The VPC is single-AZ and ephemeral. This explicitly favors bounded cloud
spend and reproducibility over high availability. Infrastructure destroys
after each run when the operator's workstation remains available; a failed
destroy requires manual recovery from the retained Terraform state.

## 2. Use k3s instead of EKS for this milestone

The goal is to demonstrate Kubernetes deployments, Services, NodePort,
Pod probes, image import and workload lifecycle alongside existing AWS
networking and Linux automation. Single-node k3s fits the private app EC2
and avoids creating an EKS control plane for a short-lived learning lab.

The two Flask Pods share one EC2 host: two Pods are **not** two availability
zones or node-level HA. k3s API/cluster credentials remain on the private
app server; operator kubectl access goes through the existing SSH bastion.
The AWS SG admits app NodePort 30080 only from the web SG, never from
the public Internet.

## 3. Preserve PostgreSQL on the dedicated database tier

Moving PostgreSQL into a Pod on the app EC2 would eliminate the project's
independent DB tier. Instead, Kubernetes receives the private DB EC2 IP
from an ephemeral ConfigMap and password from an ephemeral Kubernetes
Secret; the database SG permits TCP 5432 only from the app SG. The Flask
readiness endpoint makes a real database `SELECT 1`; liveness is purposely
independent of DB availability.

The test local-path PVC belongs to a **different, disposable evidence Pod**.
Its marker survives Pod replacement but is not the application's database
volume and is not an off-EC2 backup. Destroying this lab also deletes the
PostgreSQL EC2's root EBS; measuring independent backup and restore is a
later milestone.

## 4. Keep safety constraints consistent at every layer

- AWS runner chooses `LAB_APP_RUNTIME`; Terraform sizes the app instance
  and selects TCP 8000 or 30080, while Ansible configures Nginx and smoke
  tests to use the matching backend port.
- The legacy systemd app Ansible play has a dedicated tag; skipping it does
  not skip dedicated database or public Nginx configuration.
- Static CI checks Terraform, Ansible, Kubernetes manifest structure and
  cross-layer port/runtime consistency **without provisioning AWS resources**.
- The live runner uses ephemeral SSH keys and Terraform state in a private
  run directory, an operator IPv4 /32, a non-root AWS identity preflight,
  and best-effort Terraform teardown. The private directory is not suitable
  for public GitHub uploads.
- The TorKit staging VPS and backup automation remain separate: the AWS
  runner does not connect to or mutate the staging node.

## 5. Make test claims match observed evidence

Keep original AWS systemd deployment results and timestamps separate from
new k3s results. The September 24 live AWS run demonstrated node readiness, two Flask replicas,
Service routing, a DB-backed request through Nginx, a dedicated PostgreSQL
EC2, PVC marker survival across evidence Pod recreation, and successful
cleanup of 28 Terraform resources. The database host uses encrypted EBS;
this is not an independent, off-instance database backup.

The next connected milestones should extend the **same topology and
evidence workflow**: Kubernetes rollout/failure recovery; least-privilege
IAM, CloudWatch and alarm/incident exercise; independent PostgreSQL backup
followed by intentional teardown, fresh apply and measured recovery.
