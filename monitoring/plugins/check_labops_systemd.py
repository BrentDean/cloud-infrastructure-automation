#!/usr/bin/env python3
"""Nagios/Icinga-compatible check for a local systemd service."""

from __future__ import annotations

import re
import subprocess
import sys

from labops_plugin import (
    CRITICAL,
    OK,
    UNKNOWN,
    CheckResult,
    PluginArgumentParser,
    PluginUsageError,
    handle_help_or_version,
    print_result,
    validate_timeout,
)

UNIT_PATTERN = re.compile(r"^[A-Za-z0-9_.@:-]+$")


def build_parser() -> PluginArgumentParser:
    parser = PluginArgumentParser(
        prog="check_labops_systemd.py",
        add_help=False,
        description="Check a local systemd unit using the monitoring-plugin exit-code contract.",
    )
    parser.add_argument("-U", "--unit", default="labops-event-worker")
    parser.add_argument("-t", "--timeout", type=float, default=5.0)
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("--version", action="store_true")
    return parser


def check(unit: str, timeout: float, runner=subprocess.run) -> CheckResult:
    validate_timeout(timeout)
    if not UNIT_PATTERN.fullmatch(unit):
        raise PluginUsageError("unit contains unsupported characters")

    try:
        completed = runner(
            ["systemctl", "is-active", unit],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return CheckResult(UNKNOWN, "systemctl is not available", "'active'=U;;;0;1")
    except subprocess.TimeoutExpired:
        return CheckResult(
            UNKNOWN, f"systemctl timed out checking {unit}", "'active'=U;;;0;1"
        )
    except Exception as exc:
        return CheckResult(
            UNKNOWN,
            f"systemd check failed internally: {type(exc).__name__}",
            "'active'=U;;;0;1",
        )

    state = completed.stdout.strip() or "unknown"
    if completed.returncode == 0 and state == "active":
        return CheckResult(OK, f"{unit} is active", "'active'=1;;;0;1")
    return CheckResult(CRITICAL, f"{unit} is {state}", "'active'=0;;;0;1")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    special = handle_help_or_version(parser, argv)
    if special is not None:
        return special
    try:
        args = parser.parse_args(argv)
        result = check(args.unit, args.timeout)
    except PluginUsageError as exc:
        result = CheckResult(UNKNOWN, f"invalid arguments: {exc}")
    return print_result(result)


if __name__ == "__main__":
    raise SystemExit(main())
