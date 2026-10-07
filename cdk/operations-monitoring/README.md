# Go AWS CDK operations monitoring

This is a deliberately small **AWS CDK v2 application written in Go**. It
complements the repository's Terraform rather than replacing or duplicating it.

Terraform remains authoritative for the VPC, subnets, security groups, EC2
instances, NAT and teardown lifecycle. This CDK stack is an optional
post-provisioning operations layer.

## What it synthesizes

- one SNS topic encrypted with the AWS-managed `alias/aws/sns` key;
- four CloudWatch alarms for the native EC2 `StatusCheckFailed` metric:
  web, app, broker and DB;
- each alarm requires two consecutive one-minute failures;
- all four alarms target the SNS topic;
- one CloudWatch dashboard containing the four alarm widgets;
- outputs for the alert topic ARN and dashboard name.

The stack accepts the four **Terraform-created EC2 instance IDs** as
CloudFormation parameters. It does not look up or create networking resources.

## Local/CI validation

~~~bash
cd cdk/operations-monitoring

go mod tidy
go test ./...
go vet ./...
test -z "$(gofmt -l .)"
rm -rf cdk.out
go run .
test -f cdk.out/LabOpsOperationsMonitoring.template.json
~~~

No AWS credentials are required to synthesize this stack, and the GitHub
workflow does not run `cdk deploy`.

## Future live deployment

A future live AWS run can pass Terraform outputs to this stack after the
four-host infrastructure is healthy. That deployment should be recorded
separately because CloudWatch alarms/dashboard/SNS are not part of the
historical September evidence and are not live-verified by this repository yet.

No email/SMS subscription is created by default. This avoids inventing a
notification recipient and keeps the stack safe to synthesize and review before
a live test.
