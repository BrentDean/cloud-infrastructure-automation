# Isolated Hetzner k3s Kubernetes lab — operator runbook

**State: code implemented; a live cloud node and successful remote Kubernetes
run have not yet been independently verified.** GitHub Actions runs offline
Terraform, Ansible, YAML and shell validation; it does not deploy a server.

## Scope and architecture

The existing staging VPS and TorKit, its onion identities, its backup job,
and the previously tested AWS three-tier lab are not touched. This is a
separate Terraform root module, Hetzner server named `k3s-lab-*`, Hetzner
cloud firewall, cloud-init operator, Ansible k3s setup and Kubernetes
namespace `infra-lab`.

```text
Workstation                 Dedicated Hetzner VM (single node)
  | SSH :22 only                k3s API :6443 localhost / not exposed by firewall
  v
labops -> sudo k3s kubectl -> infra-lab namespace
                                 |
               ClusterIP :80 -> Flask Deployment x2
                                 | /readyz checks SELECT 1
                                 v
               ClusterIP :5432 -> PostgreSQL StatefulSet x1
                                 |
                         local-path PVC: 4Gi
```

Cloud firewall permits inbound TCP/22 from the operator IPv4 /32 only.
Remote Kubernetes :6443, HTTP :80/:443 and PostgreSQL :5432 are not
exposed by the firewall. The k3s packaged Traefik and ServiceLB are disabled.
Kubernetes Services are ClusterIP. Use SSH + kubectl or a localhost-only
SSH/kubectl port-forward for interaction.

k3s local-path provisioning persists PostgreSQL data independently of a
*pod*, but remains on **the same VM's disk**: it does NOT survive deletion
of the Hetzner server and is NOT offsite disaster recovery. This project
is single-node, not a high-availability production design. PostgreSQL is
one replica, and app replicas cannot withstand losing the only node.
Do not delete/recreate the PVC when conducting the pod-restart exercise.

## 1. Preconditions and cloud cost approval

Run on your Linux workstation from the repository root. Requirements:
Terraform, Ansible, Docker, SSH, Python 3, a Hetzner Cloud project/token
and a public/private SSH key pair. Keep real tokens, SSH private keys,
`terraform.tfvars`, `terraform.tfstate`, and DB passwords OUT of Git.

Review current Hetzner pricing, available server types, quotas and SSH
public key registrations before `terraform apply`. A running VM and
storage accrue cost even when idle. This lab does not automatically
terminate itself. No cloud actions are performed by checking out a PR
or running the static validation workflows.

```bash
cd /mnt/hyperV/projects/vps-infrastructure
git switch feature/kubernetes-k3s-deployment

cp terraform/hetzner-k3s/terraform.tfvars.example \
   terraform/hetzner-k3s/terraform.tfvars

# EDIT terraform.tfvars: replace 203.0.113.10/32 with YOUR public IPv4 /32,
# set the matching SSH .pub file and confirm VM type/location.
# Use existing_ssh_key_id if this exact key is already in Hetzner Cloud.
export HCLOUD_TOKEN='YOUR_PRIVATE_HETZNER_PROJECT_API_TOKEN'
terraform -chdir=terraform/hetzner-k3s init
terraform -chdir=terraform/hetzner-k3s fmt -check
terraform -chdir=terraform/hetzner-k3s validate
terraform -chdir=terraform/hetzner-k3s plan -out=k3s.tfplan
```

Check plan: **one new, separate** `k3s-lab-*` server and firewall, plus
a new operator SSH key unless `existing_ssh_key_id` was supplied.
Any plan deleting or modifying a staging VPS is wrong: STOP. If your
public IP changes, update `operator_cidr` and apply the new firewall
rule to regain SSH access. The /32 deliberately does not allow everyone.

The Hetzner token may be present in shell history if set using an inline
literal. Prefer a secret manager or a shell session without history.

## 2. Explicit provision and deploy (billable)

```bash
terraform -chdir=terraform/hetzner-k3s apply k3s.tfplan

# Choose the private counterpart to the .pub file in terraform.tfvars.
export SSH_KEY="$HOME/.ssh/id_ed25519"

# Keep this same database password for future deployments to the SAME
# persistent volume; changing the Secret alone does not rotate a DB role.
export LAB_DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

bash scripts/k3s/deploy.sh
```

The script gates on Terraform's `server_name` output beginning with
`k3s-lab-`, waits for SSH, runs Ansible, builds the *same* Flask source
used by AWS, and imports the local Docker image into k3s containerd
namespace `k8s.io`. No registry credentials or public GHCR repository
are required. The Kubernetes image is `localhost/three-tier-api:pr2`
with `imagePullPolicy: Never`, so the container cannot quietly pull a
different image from a public registry. A manual rollout restart makes
an imported replacement image take effect on repeat deployments.

Before applying the app, the script applies the namespace, creates
the `db-auth` Secret from standard input (no plaintext secret manifest),
applies PostgreSQL, and waits for its rollout. Password encryption at
rest is enabled in k3s config. Docker build occurs on the workstation;
no Docker daemon is installed on the VM. The deployment script does
not run `terraform apply` or `destroy`.

If you lose the password after the first deployment, keep in mind the
existing PostgreSQL role still has the old password in its data volume.
Do not overwrite the Secret with a different value and expect it to
work without separately rotating the PostgreSQL role. This will be
addressed more fully in the disaster-recovery milestone.

## 3. Verify actual workload, network and storage

```bash
bash scripts/k3s/verify.sh
```

Verification must show a Ready node, running PostgreSQL StatefulSet,
2/2 available API replicas, `local-path` storage class, PVC
`postgres-data-postgres-0` in `Bound` phase, and successful
`/healthz`, `/readyz`, and legacy `/health` requests through the API
ClusterIP Service DNS. `/readyz` and `/health` must return PostgreSQL
`db_result: 1`. Record actual command output and date in a later
evidence commit; do not claim these checks passed from static CI alone.

To inspect from your own browser/terminal **without exposing port 80**
on the cloud firewall:

```bash
# Terminal 1 (leave running):
bash scripts/k3s/port-forward.sh

# Terminal 2:
curl -fsS http://127.0.0.1:18080/health
curl -fsS http://127.0.0.1:18080/healthz
curl -fsS http://127.0.0.1:18080/readyz
```

Confirm HTTP/6443/5432 are absent from the Hetzner firewall. This does
not mean that local pod-to-pod network restrictions were proved; an
explicit NetworkPolicy/negative-path exercise is a later milestone.

## 4. Reproducibility and caveats

The official k3s installer is downloaded from `https://get.k3s.io`
only when no k3s binary exists. Its stable channel can change; set
`K3S_VERSION` to a verified upstream release to pin a particular
rebuild. Rerunning Ansible preserves the installation and does not
upgrade k3s automatically. The PostgreSQL image is pinned to major
version 16, rather than a specific patch digest.

The Hetzner server is deployed with Ubuntu 24.04, no public IPv6,
no Hetzner backups, no public ingress, a restricted user `labops`,
root SSH disabled and kubeconfig mode 0600. The only remotely reachable
provider-firewall port is SSH from the specified /32. SSH uses
`StrictHostKeyChecking=accept-new` for first boot: check the initial
host key fingerprint through an independent trusted channel before
using the server for anything sensitive.

## 5. Tear down the isolated lab

**Destroying the VM destroys the PostgreSQL local-path data.** For the
disaster-recovery project, establish an independent backup FIRST.

```bash
terraform -chdir=terraform/hetzner-k3s plan -destroy
# Review that only k3s-lab-* resources appear.
terraform -chdir=terraform/hetzner-k3s destroy
terraform -chdir=terraform/hetzner-k3s state list
```

Do not run `terraform destroy` from any other Terraform directory;
the existing AWS and TorKit staging work are separate and untouched.
No Hetzner credentials are stored in GitHub Actions.
