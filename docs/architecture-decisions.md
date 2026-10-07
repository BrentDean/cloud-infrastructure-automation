# Architecture decisions: one coherent, disposable AWS portfolio lab

Status: October 6, 2026. The September 2026 systemd and k3s variants passed
separate live AWS tests on the earlier three-host topology. The current design
adds a dedicated private broker and is CI/static-validated but has **not yet**
been re-run live in AWS. See the historical
[September 24 k3s verification record](live-verification-2026-09-24.md).

## 1. Reuse one three-tier AWS topology

The original Terraform module provisioned a VPC, IGW, NAT and three
web/app/DB EC2 roles. The current module retains the same root, runner,
credential generation, SSH bastion and teardown while adding one **private
broker subnet and EC2 role** for NATS JetStream and the Go consumer. The broker
has no public IP and does not create another public entry point or provider.
The application runtime choice remains independent: `systemd` is the default;
`k3s` changes only the private app tier.

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

## 3. Separate messaging from the application host

Core messaging is isolated on a dedicated broker EC2 rather than sharing the
application node. The app security group is the only source admitted to NATS
TCP 4222. The Go consumer runs beside NATS on the broker and reaches
PostgreSQL over TCP 5432 through a broker-specific SG rule. NATS monitoring
binds to loopback, and the web tier has no NATS path.

This creates a clearer failure/security boundary and lets the same broker serve
either systemd Flask or k3s Pods without coupling broker lifecycle to the app
runtime. The cost is one additional small private EC2/root volume per live lab
run. The design remains single-AZ and intentionally does not claim broker HA.

## 4. Preserve PostgreSQL on the dedicated database tier

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

## 5. Keep safety constraints consistent at every layer

- AWS runner chooses `LAB_APP_RUNTIME`; Terraform sizes the app instance
  and selects TCP 8000 or 30080, while Ansible configures Nginx and smoke
  tests to use the matching backend port.
- Terraform and Ansible agree on a fourth `broker` role. The runner inventories
  it through the web bastion; application code receives its private NATS
  endpoint at runtime rather than through a committed credential file.
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

## 6. Keep Terraform authoritative; use Go CDK for the operations layer

Terraform remains responsible for the disposable network, security groups, EC2
roles, NAT and teardown. The Go AWS CDK v2 app under
`cdk/operations-monitoring/` does not recreate or import those resources.
Instead, it accepts the four Terraform-created EC2 instance IDs as
CloudFormation parameters and synthesizes an optional operations stack:
CloudWatch EC2 status alarms, an SNS alert topic encrypted with the AWS-managed
SNS KMS key, and an operations dashboard.

Terraform now exposes the four instance IDs explicitly for that handoff. This
keeps the two IaC tools complementary and provides real Go/CDK implementation
evidence without introducing a second owner for the VPC or EC2 lifecycle. CI
runs CDK assertions, `go vet`, `gofmt`, module verification and
credential-free synthesis; it never runs `cdk deploy`.

## 7. Make test claims match observed evidence

Keep original AWS systemd deployment results and timestamps separate from
new k3s results. The September 24 live AWS run demonstrated node readiness, two Flask replicas,
Service routing, a DB-backed request through Nginx, a dedicated PostgreSQL
EC2, PVC marker survival across evidence Pod recreation, and successful
cleanup of 28 Terraform resources. The database host uses encrypted EBS;
this is not an independent, off-instance database backup.

The next live milestone is one end-to-end AWS run of the **current four-host
topology**, capturing Terraform apply/destroy, broker service health,
app→broker and broker→DB paths, denied web→broker access, messaging delivery,
Linux-hardening evidence and second-pass Ansible idempotency. The optional CDK
operations stack can then be deployed against the Terraform instance-ID outputs
and verified separately before teardown. After that, connected milestones can
add Kubernetes rollout/failure recovery, least-privilege IAM refinements, and
an independent PostgreSQL backup/rebuild exercise.
