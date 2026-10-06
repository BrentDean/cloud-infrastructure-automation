#!/usr/bin/env python3
"""Validate the synthesized Go CDK operations template without AWS access."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


FORBIDDEN_TYPES = {
    "AWS::EC2::Instance",
    "AWS::EC2::VPC",
    "AWS::EC2::Subnet",
    "AWS::EC2::SecurityGroup",
    "AWS::EC2::NatGateway",
    "AWS::EC2::InternetGateway",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_cdk_synth.py <template.json>")

    path = Path(sys.argv[1])
    template = json.loads(path.read_text())
    resources = template.get("Resources", {})
    parameters = template.get("Parameters", {})

    outputs_tf = (
        Path(__file__).resolve().parents[1]
        / "terraform/aws-three-tier/outputs.tf"
    ).read_text()
    require(
        'output "instance_ids"' in outputs_tf,
        "Terraform must expose the CDK EC2 handoff map",
    )
    for role in ("web", "app", "broker", "db"):
        pattern = (
            r"^\s*"
            + re.escape(role)
            + r'\s*=\s*aws_instance\.role\["'
            + re.escape(role)
            + r'"\]\.id\s*$'
        )
        require(
            re.search(pattern, outputs_tf, flags=re.MULTILINE) is not None,
            f"Terraform instance_ids output missing {role}",
        )

    counts = {}
    for resource in resources.values():
        resource_type = resource["Type"]
        counts[resource_type] = counts.get(resource_type, 0) + 1
        require(
            resource_type not in FORBIDDEN_TYPES,
            f"CDK operations layer must not own Terraform infrastructure: {resource_type}",
        )

    require(counts.get("AWS::SNS::Topic") == 1, "expected one SNS alarm topic")
    require(counts.get("AWS::CloudWatch::Alarm") == 5, "expected five CloudWatch alarms")
    require(
        counts.get("AWS::CloudWatch::Dashboard") == 1,
        "expected one CloudWatch dashboard",
    )

    expected_parameters = {
        "WebInstanceId",
        "AppInstanceId",
        "BrokerInstanceId",
        "DatabaseInstanceId",
    }
    actual_parameters = set(parameters)
    require(
        expected_parameters.issubset(actual_parameters),
        "CDK template is missing one or more EC2 handoff parameters",
    )
    allowed_internal_parameters = {"BootstrapVersion"}
    unexpected_parameters = actual_parameters - expected_parameters - allowed_internal_parameters
    require(
        not unexpected_parameters,
        "unexpected CDK parameters: " + ", ".join(sorted(unexpected_parameters)),
    )
    for name in expected_parameters:
        require(
            parameters[name].get("Type") == "AWS::EC2::Instance::Id",
            f"{name} must remain an EC2 instance-id parameter",
        )

    alarms = [
        resource["Properties"]
        for resource in resources.values()
        if resource["Type"] == "AWS::CloudWatch::Alarm"
    ]
    require(
        sum(a.get("MetricName") == "StatusCheckFailed" for a in alarms) == 4,
        "expected one StatusCheckFailed alarm per EC2 tier",
    )
    require(
        sum(a.get("MetricName") == "CPUUtilization" for a in alarms) == 1,
        "expected one broker CPU alarm",
    )
    require(all(a.get("AlarmActions") for a in alarms), "every alarm must publish to SNS")

    print(
        "PASS: Go CDK synth contains 4 EC2 parameters, 5 alarms, 1 SNS topic, "
        "1 dashboard, and no Terraform-owned EC2/VPC resources"
    )


if __name__ == "__main__":
    main()
