#!/usr/bin/env python3
"""Offline contract between AWS Terraform, Ansible, k3s YAML, and lab runner.

This test NEVER connects to AWS, SSH, Docker, Terraform state, or Kubernetes.
The assertion messages identify architectural drift before a billable apply.
"""
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def resource(name: str, source: str) -> str:
    match = re.search(
        r'^resource "[^"]+" "' + re.escape(name) +
        r'" \{(?P<body>.*?)(?=^resource |^data |^locals \{|\Z)',
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    require(match is not None, "Terraform resource missing: " + name)
    return match.group("body")


def main() -> None:
    vars_tf = read("terraform/aws-three-tier/variables.tf")
    compute = read("terraform/aws-three-tier/compute.tf")
    networking = read("terraform/aws-three-tier/networking.tf")
    playbook = read("ansible/aws-three-tier/configure.yml")
    smoke = read("ansible/aws-three-tier/smoke-test.yml")
    k3s_play = read("ansible/k3s/install.yml")
    runner = read("scripts/run-aws-three-tier.sh")
    deploy = read("scripts/k3s/aws-deploy.sh")
    verify = read("scripts/k3s/aws-verify.sh")
    app_docs = list(yaml.safe_load_all(read("kubernetes/k3s/app.yaml")))
    service, deployment = app_docs

    require('default     = "systemd"' in vars_tf, "Baseline app runtime must stay systemd")
    require('contains(["systemd", "k3s"], var.app_runtime)' in vars_tf,
            "Runtime must explicitly restrict its allowed values")
    require('var.app_runtime == "k3s" && each.key == "app"' in compute,
            "Only private app EC2 should grow for k3s")
    require('var.k3s_app_instance_type : var.instance_type' in compute,
            "k3s instance size is not app-tier conditional")
    require('for_each                    = local.instances' in compute,
            "Original three-role EC2 resource must be retained")
    for role in ("web", "app", "db"):
        require(re.search(r'^\s*' + role + r'\s*=\s*\{\s*subnet_id', compute, re.MULTILINE)
                is not None, "AWS EC2 role missing: " + role)

    app_ingress = resource("app_http", networking)
    require('referenced_security_group_id = aws_security_group.web.id' in app_ingress,
            "App HTTP ingress must come only from web security group")
    for field in ("from_port", "to_port"):
        require(re.search(field + r'\s*= var.app_runtime == "k3s" \? 30080 : 8000',
                          app_ingress) is not None,
                "App SG " + field + " must choose NodePort 30080 / legacy 8000")

    db_ingress = resource("db_postgres", networking)
    require('referenced_security_group_id = aws_security_group.app.id' in db_ingress,
            "Database SG must admit only app-tier security group")
    require(re.search(r'from_port\s*= 5432', db_ingress) is not None,
            "DB ingress should be restricted to PostgreSQL TCP 5432")

    plays = yaml.safe_load(playbook)
    require(len(plays) == 3, "Exactly three Ansible configuration roles are expected")
    require([p["hosts"] for p in plays] == ["db", "app", "web"],
            "Dedicated database, app, and public web Ansible roles must remain")
    require(plays[1].get("tags") == ["systemd_app"],
            "k3s mode must skip only the original systemd app play")
    proxy = next(t for t in plays[2]["tasks"]
                 if t.get("name") == "Configure application reverse proxy")
    content = proxy["ansible.builtin.copy"]["content"]
    require("lab_app_port | default(8000)" in content,
            "Nginx must choose the runtime-specific backend port")
    require("location = /health" in content, "Original end-to-end health route must remain")
    require("location ^~ /api/v1/" in content,
            "LabOps API must be routed via the existing operator-restricted web tier")
    require("0001_incidents.sql" in playbook and "db.py" in playbook,
            "Both AWS app runtimes require shared LabOps schema and Python module")
    require("lab_app_port | default(8000) | int" in smoke,
            "Smoke test must select the same backend port as Nginx")

    k3s = yaml.safe_load(k3s_play)
    require(len(k3s) == 1 and k3s[0]["hosts"] == "app",
            "k3s play must target only the AWS private app host")
    require("secrets-encryption: true" in k3s_play, "k3s must encrypt its local Secrets")
    require("write-kubeconfig-mode:" in k3s_play, "kubeconfig permissions missing")

    require(service["kind"] == "Service" and service["spec"]["type"] == "NodePort",
            "Flask API must be reachable by restricted private NodePort")
    require(service["spec"]["ports"][0]["nodePort"] == 30080,
            "Kubernetes Service port has drifted from SG and Ansible")
    require(deployment["kind"] == "Deployment"
            and deployment["spec"]["replicas"] == 2,
            "Expected two app Pods in the one-node Kubernetes demo")
    env = {item["name"]: item for item in
           deployment["spec"]["template"]["spec"]["containers"][0]["env"]}
    require(env["PGHOST"]["valueFrom"]["configMapKeyRef"]["name"] == "db-endpoint",
            "Private EC2 DB IP must come from runtime ConfigMap")
    require(env["PGPASSWORD"]["valueFrom"]["secretKeyRef"]["name"] == "db-auth",
            "PostgreSQL password must come from runtime-only Secret")

    require('export LAB_APP_RUNTIME' in runner
            and 'export TF_VAR_app_runtime="$LAB_APP_RUNTIME"' in runner,
            "Runner must pass k3s selection to Terraform AND remote helper")
    require('CONFIGURE_ARGS=(--skip-tags systemd_app -e lab_app_port=30080)' in runner,
            "Runner must skip only the legacy app and set reverse-proxy NodePort")
    require('scripts/k3s/aws-deploy.sh' in runner
            and 'scripts/k3s/aws-verify.sh' in runner,
            "AWS runner must invoke real k3s installation and verification")
    require('trap cleanup EXIT' in runner
            and 'terraform -chdir="$WORK/terraform" destroy' in runner,
            "Runner must retain best-effort Terraform teardown on all outcomes")
    require('aws sts get-caller-identity' in runner,
            "Runner should check account identity before a billable apply")
    require('aws-lab-app' in deploy and 'aws-lab-app' in verify,
            "k3s SSH scripts must address ephemeral AWS private app alias")
    require('terraform/hetzner-k3s' not in deploy,
            "Superseded Hetzner-k3s dependency must not return")
    require(not (ROOT / "terraform/hetzner-k3s").exists(),
            "Do not recreate a redundant Hetzner Kubernetes Terraform root")
    require(not (ROOT / "kubernetes/k3s/postgres.yaml").exists(),
            "PostgreSQL must remain on dedicated EC2, not in Kubernetes")

    print("PASS: three AWS tiers, optional private k3s app, ports, runtime credentials,")
    print("      retained systemd baseline, single AWS runner, teardown, and no Hetzner k3s")


if __name__ == "__main__":
    main()
