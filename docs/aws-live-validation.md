# AWS Live Validation runner

This workflow is the controlled path for the **next** billable AWS validation of
the current LabOps architecture. It is manual-only and has not yet been used as
published evidence.

Workflow: `.github/workflows/aws-live-validation.yml`

## Purpose

The runner proves one bounded story:

1. validate Terraform, Ansible, shell and the Go worker without AWS;
2. obtain short-lived AWS credentials through GitHub OIDC;
3. deploy the disposable web/app/broker/database topology;
4. configure and harden the Linux hosts;
5. exercise database, messaging, monitoring and network-isolation checks;
6. run the selected systemd or k3s application path;
7. destroy Terraform-managed resources;
8. independently verify that no active top-level lab resources remain.

It does **not** run on pushes or pull requests.

## GitHub Environment gate

Create a GitHub Environment named `aws-live-lab` before the first live run.
Configure a required reviewer so billable deployment cannot start immediately
after someone clicks **Run workflow**.

Add these Environment variables:

- `AWS_ROLE_ARN` — ARN of the least-privilege IAM role GitHub may assume.
- `AWS_ACCOUNT_ID` — the expected 12-digit account ID used as an account guard.

The role ARN is not a secret. Do not store long-lived AWS access keys in GitHub.

## AWS OIDC trust

The IAM role should trust the repository only through GitHub's OIDC provider,
and the subject should be restricted to the protected Environment:

```json
{
  "Effect": "Allow",
  "Principal": {
    "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
  },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": {
      "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
    },
    "StringLike": {
      "token.actions.githubusercontent.com:sub": "repo:BrentDean/cloud-infrastructure-automation:environment:aws-live-lab"
    }
  }
}
```

The role needs only the permissions required by the Terraform root and cleanup
verification: the EC2/VPC resources in this lab, key-pair lifecycle, AMI and
resource describe calls, tagging, and STS identity inspection. Keep the role
separate from unrelated AWS workloads.

## Starting a run

From the Actions UI, choose **AWS Live Validation**, select `k3s` or
`systemd`, and type `DEPLOY` exactly.

The workflow uses a pinned `ubuntu-24.04` GitHub-hosted runner and a
repository-wide concurrency lock, so only one live lab can run at once.

The first job is non-billable. The second job is attached to the
`aws-live-lab` Environment and therefore waits for its approval gate before
OIDC credentials are requested or AWS resources are created.

## Cleanup contract

The existing `scripts/run-aws-three-tier.sh` remains responsible for normal
Terraform teardown through its EXIT trap. The workflow then:

- retries `terraform destroy` if state still contains resources;
- checks for active VPC, EC2 instance, NAT gateway, Elastic IP and key-pair
  resources carrying the run's `RunId` tag;
- waits briefly for AWS deletion to settle;
- fails the workflow if tagged residual resources remain.

This is intentionally stricter than merely seeing `terraform destroy` return
success.

## Evidence handling

Raw Terraform state, generated SSH keys and full private logs are never uploaded
as Actions artifacts. The workflow creates a sanitized artifact containing only:

- a Markdown validation summary;
- the external health JSON when produced;
- the event-worker binary checksum;
- cleanup-verification output.

IPv4 addresses are redacted from extracted PASS lines. Review every artifact
before copying it into the repository as permanent portfolio evidence.

A successful workflow is evidence only for the exact commit and runtime shown in
that run. Do not update the README's live-verification claims until the run has
completed successfully and the artifact has been reviewed.
