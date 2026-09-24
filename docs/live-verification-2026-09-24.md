# Live AWS k3s verification record — September 24, 2026

**Status: verified in a billable AWS lab in `us-east-1`.** The k3s mode reused the original three-tier Terraform root, Nginx/SSH bastion, and separate PostgreSQL EC2. The test ended with successful Terraform destruction of **28 managed resources**. These observations are separate from the original systemd/Gunicorn deployment verified September 22.

## Deployed infrastructure

| Layer | Live result |
| --- | --- |
| AWS infrastructure | One VPC; one public web subnet; distinct private app and DB subnets; NAT, IGW, security-group boundaries; three EC2 instances |
| Web | `t3.small`, Nginx HTTP `/health`, SSH bastion; public ingress restricted to operator IPv4 `/32` |
| Application | Private `t3.medium` running single-node k3s; Kubernetes node reported `Ready` |
| DB | Private `t3.small` running dedicated PostgreSQL 16; permitted app-only DB traffic |
| API Pods | Deployment `three-tier-api` reported **2/2 available**, both running without root |
| Service | Internal Kubernetes Service with `NodePort 30080`, admitted only from the web security group |
| Test volume | `lab-evidence` PVC reported `Bound`, 1 GiB `local-path` storage |

The workstation built the image, sent it through the existing web SSH bastion to the app host, and imported it into the private node's containerd image store. No EKS cluster, extra public server, or public container registry was required.

## Observed validation

| Check | Observed outcome |
| --- | --- |
| Python process liveness `/healthz` | PASS |
| DB-backed Kubernetes readiness `/readyz` | PASS |
| Original `/health` and dedicated DB `SELECT 1` | PASS |
| Internal Service DNS / application network path | PASS |
| Two non-root replicas and deployment rollout | PASS |
| Test PVC marker after deleting **only the evidence Pod** and recreating it | PASS |
| External workstation → Nginx → private NodePort → Flask → PostgreSQL `SELECT 1` | PASS |
| App EC2 → PostgreSQL TCP 5432 | PASS |
| Web EC2 → application NodePort 30080 | PASS |
| Web EC2 → PostgreSQL TCP 5432 | Blocked, as intended |
| Second Ansible configuration run, web and DB plays | `changed=0`, `failed=0`, `unreachable=0` |
| Terraform cleanup | `Destroy complete! Resources: 28 destroyed.` |

The first Ansible pass configured database and web instances. The systemd application play was tagged out of the k3s variant, so its idempotency is **not** included in the k3s second-pass claim. The separate k3s install play and Kubernetes manifests were exercised successfully in the live run.

### Sanitized terminal excerpt

```text
deployment.apps/three-tier-api     2/2
service/three-tier-api             NodePort 80:30080/TCP
persistentvolumeclaim/lab-evidence Bound

PASS: /healthz
PASS: /readyz
PASS: /health
PASS: two non-root Flask replicas, Service/NodePort,
      dedicated PostgreSQL SELECT 1, and PVC persistence across Pod deletion.
PASS: workstation -> web -> app -> PostgreSQL returned SELECT 1
PASS: three-tier provisioning, configuration idempotency,
      connectivity, network restrictions.

Destroy complete! Resources: 28 destroyed.
```

This is a condensed excerpt based on the captured September 24 operator output, not a verbatim copy of one contiguous log block. Detailed machine logs were retained in the private evidence directory on the operator workstation.

## What the evidence does—and does not—establish

- **Does:** prove a real single-AZ AWS deployment, private Kubernetes workload, two working replicas, end-to-end DB connectivity, a denied network path, Pod-level PVC persistence and full Terraform teardown.
- **Does not:** prove availability across Kubernetes nodes/AZs; a rolling-upgrade or deliberately induced failure recovery test; backup of PostgreSQL outside the DB EC2; persistence through EC2 deletion; a complete second-run idempotency check for all k3s resources; TLS for a publicly accessible application.
- The PVC belongs to the **test-only evidence Pod**. The actual PostgreSQL database stays on the private DB EC2 and is destroyed with the ephemeral lab.

## Operational evidence handling

The runner writes `configure-first.log`, `configure-second.log`, `k3s-ansible.log`, `k3s-deploy.log`, `k3s-verification.log`, `smoke-test.log`, `external-health.json` and `run-summary.txt` to the per-run `evidence/` directory. The parent run directory can also contain Terraform state, database secrets and temporary SSH credentials; **never commit the entire run directory**. Capture screenshots that show system state and test results without publishing secrets.

For reproduction and cost controls, see [the k3s runbook](kubernetes-k3s.md) and [the primary README](../README.md).
