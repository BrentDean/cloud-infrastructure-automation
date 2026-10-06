#!/usr/bin/env python3
"""Nagios/Icinga-compatible check for LabOps end-to-end HTTP/database health."""

from __future__ import annotations

import sys
from urllib.error import HTTPError, URLError

from labops_plugin import (
    CRITICAL,
    UNKNOWN,
    CheckResult,
    PluginArgumentParser,
    PluginUsageError,
    handle_help_or_version,
    http_json,
    latency_code,
    latency_perfdata,
    print_result,
    validate_latency_thresholds,
    validate_timeout,
)


def build_parser() -> PluginArgumentParser:
    parser = PluginArgumentParser(
        prog="check_labops_http.py",
        add_help=False,
        description="Check LabOps /health and its PostgreSQL-backed contract.",
    )
    parser.add_argument("-u", "--url", default="http://127.0.0.1/health")
    parser.add_argument("-w", "--warning-ms", type=float, default=500.0)
    parser.add_argument("-c", "--critical-ms", type=float, default=2000.0)
    parser.add_argument("-t", "--timeout", type=float, default=5.0)
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("--version", action="store_true")
    return parser


def check(url: str, warning_ms: float, critical_ms: float, timeout: float) -> CheckResult:
    validate_latency_thresholds(warning_ms, critical_ms)
    validate_timeout(timeout)

    try:
        status, payload, elapsed_ms = http_json(url, timeout)
    except HTTPError as exc:
        return CheckResult(CRITICAL, f"LabOps health returned HTTP {exc.code}")
    except URLError as exc:
        return CheckResult(CRITICAL, f"LabOps health unavailable: {exc.reason}")
    except TimeoutError:
        return CheckResult(CRITICAL, "LabOps health timed out")
    except (UnicodeDecodeError, ValueError) as exc:
        return CheckResult(CRITICAL, f"LabOps health response invalid: {exc}")
    except Exception as exc:
        return CheckResult(
            UNKNOWN, f"LabOps HTTP check failed internally: {type(exc).__name__}"
        )

    perfdata = latency_perfdata(elapsed_ms, warning_ms, critical_ms)
    healthy = (
        status == 200
        and payload.get("status") == "ok"
        and payload.get("db") == "connected"
        and payload.get("db_result") == 1
    )
    if not healthy:
        return CheckResult(CRITICAL, "API/database health contract failed", perfdata)

    code = latency_code(elapsed_ms, warning_ms, critical_ms)
    return CheckResult(code, f"API and PostgreSQL healthy in {elapsed_ms:.1f} ms", perfdata)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    special = handle_help_or_version(parser, argv)
    if special is not None:
        return special
    try:
        args = parser.parse_args(argv)
        result = check(args.url, args.warning_ms, args.critical_ms, args.timeout)
    except PluginUsageError as exc:
        result = CheckResult(UNKNOWN, f"invalid arguments: {exc}")
    return print_result(result)


if __name__ == "__main__":
    raise SystemExit(main())
