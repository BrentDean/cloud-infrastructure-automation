#!/usr/bin/env python3
"""Static contracts for the Linux hardening and selected RHEL 9 control profiles."""

from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text()


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    hardening = read("ansible/aws-three-tier/hardening.yml")
    baseline = read("ansible/aws-three-tier/roles/linux_baseline/tasks/main.yml")
    baseline_defaults = read("ansible/aws-three-tier/roles/linux_baseline/defaults/main.yml")
    evidence = read("ansible/aws-three-tier/security-evidence.yml")
    runner = read("scripts/run-aws-three-tier.sh")
    rhel = read("ansible/rhel9-security/selected-hardening.yml")
    docs = read("docs/security-controls.md")

    plays = yaml.safe_load(hardening)
    require([play["hosts"] for play in plays] == ["web", "app", "broker", "db"],
            "AWS hardening must cover all four EC2 roles")
    require('DEFAULT_INPUT_POLICY="DROP"' in baseline,
            "AWS host firewall must default-deny inbound traffic")
    require('DEFAULT_OUTPUT_POLICY="ACCEPT"' in baseline,
            "AWS host firewall must retain outbound package/service access")
    require("PermitRootLogin no" in baseline
            and "PasswordAuthentication no" in baseline
            and "KbdInteractiveAuthentication no" in baseline,
            "AWS SSH baseline must enforce key-only non-root remote access")
    require("write_logs = yes" in baseline and "99-labops.rules" in baseline,
            "AWS baseline must configure persistent audit logging")
    require("labops_ssh_config" in baseline_defaults
            and "labops_firewall_config" in baseline_defaults
            and "labops_systemd_units" in baseline_defaults,
            "AWS audit rules must cover SSH, firewall and systemd configuration")
    require("lab_app_runtime | default('systemd')) != 'k3s'" in hardening,
            "k3s app host must explicitly avoid UFW ownership conflict")
    require("ufw_expected_active" in evidence
            and "password_authentication_no" in evidence
            and "auditd_active" in evidence,
            "Evidence playbook must emit machine-readable SSH/firewall/audit results")
    require("hardening-second.log" in runner and "security-evidence.yml" in runner,
            "Live runner must prove hardening idempotency and collect evidence")

    for token in (
        "SELINUX=enforcing",
        "SELINUXTYPE=targeted",
        "policycoreutils",
        "firewalld",
        "write_logs = yes",
        "PermitRootLogin no",
        "UMASK 077",
    ):
        require(token in rhel, f"RHEL 9 selected-control profile missing: {token}")

    for finding in (
        "V-258078",
        "V-258079",
        "V-257935",
        "V-257936",
        "V-258152",
        "V-258170",
        "V-257985",
        "V-258074",
        "V-258171",
    ):
        require(finding in docs, f"Selected STIG mapping missing {finding}")

    require("not a full STIG" in docs,
            "Documentation must explicitly reject a full-STIG compliance claim")

    print("PASS: AWS host firewall/SSH/audit evidence contracts and selected RHEL 9 controls are explicit")


if __name__ == "__main__":
    main()
