# Go AWS CDK operational layer

This directory is an **additive** AWS CDK v2 stack written in Go. Terraform
continues to own the LabOps VPC, subnets, security groups, EC2 instances, NAT
gateway and key pair.

The CDK stack intentionally owns only operational resources:

- one SNS alarm topic
- one EC2 `StatusCheckFailed` alarm for each Terraform-owned web/app/broker/DB instance
- one broker `CPUUtilization` alarm
- one CloudWatch dashboard showing CPU for all four instances

Terraform exposes the four EC2 IDs through its `instance_ids` output map. The
stack takes those IDs as CloudFormation parameters. It does
not look them up during synthesis and does not create or modify EC2/VPC
resources.

## Why the split exists

Terraform remains the authoritative lifecycle tool for the disposable
application infrastructure. CDK is used here to demonstrate a separate,
programmatic operational layer without creating overlapping ownership of the
same cloud objects.

This keeps the eventual deployment order explicit:

1. Terraform creates the disposable EC2 topology.
2. The four Terraform-created instance IDs are supplied to this CloudFormation/CDK stack.
3. CDK creates only monitoring/notification resources.
4. The CDK stack must be destroyed before Terraform tears down the EC2 targets.

## Local validation

AWS CDK v2.272.0 is pinned in `go.mod`.

~~~bash
cd cdk/operations
go mod verify
go test ./...
go vet ./...
go run .
~~~

`go run .` synthesizes a CloudFormation assembly into `cdk.out/` without
creating AWS resources. CI additionally inspects the synthesized template and
fails if this stack starts owning EC2, VPC, subnet or security-group resources.

## Deployment status

This stack is **synthesized and tested only**. It has not been bootstrapped or
deployed to the AWS lab yet, and no SNS subscription/notification recipient is
configured. The planned consolidated live AWS run can include deployment after
the Terraform topology is available.
