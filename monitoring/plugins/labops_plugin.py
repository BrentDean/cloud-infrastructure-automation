#!/usr/bin/env python3
"""Shared helpers for Nagios/Icinga-compatible LabOps monitoring plugins."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import time
from urllib.request import Request, urlopen

OK = 0
WARNING = 1
CRITICAL = 2
UNKNOWN = 3

STATUS_NAMES = {OK: "OK", WARNING: "WARNING", CRITICAL: "CRITICAL", UNKNOWN: "UNKNOWN"}
VERSION = "1.0.0"
MAX_RESPONSE_BYTES = 64 * 1024


class PluginUsageError(ValueError):
    """Invalid plugin command-line input."""


class PluginArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise PluginUsageError(message)


@dataclass(frozen=True)
class CheckResult:
    code: int
    summary: str
    perfdata: str = ""

    def line(self) -> str:
        output = f"{STATUS_NAMES[self.code]} - {self.summary}"
        if self.perfdata:
            output += f" | {self.perfdata}"
        return output


def print_result(result: CheckResult) -> int:
    print(result.line())
    return result.code


def validate_latency_thresholds(warning_ms: float, critical_ms: float) -> None:
    if warning_ms < 0 or critical_ms <= 0:
        raise PluginUsageError(
            "latency thresholds must be non-negative and critical must be positive"
        )
    if warning_ms >= critical_ms:
        raise PluginUsageError("warning latency must be lower than critical latency")


def validate_timeout(timeout: float) -> None:
    if timeout <= 0 or timeout > 30:
        raise PluginUsageError(
            "timeout must be greater than 0 and no more than 30 seconds"
        )


def latency_code(elapsed_ms: float, warning_ms: float, critical_ms: float) -> int:
    if elapsed_ms >= critical_ms:
        return CRITICAL
    if elapsed_ms >= warning_ms:
        return WARNING
    return OK


def latency_perfdata(elapsed_ms: float, warning_ms: float, critical_ms: float) -> str:
    return (
        f"'latency'={elapsed_ms:.1f}ms;"
        f"{warning_ms:g};{critical_ms:g};0"
    )


def http_json(url: str, timeout: float) -> tuple[int, dict, float]:
    request = Request(url, headers={"User-Agent": f"labops-monitoring/{VERSION}"})
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("response exceeded 64 KiB")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("response JSON must be an object")
    return status, payload, elapsed_ms


def handle_help_or_version(parser: argparse.ArgumentParser, argv: list[str]) -> int | None:
    if "-h" in argv or "--help" in argv:
        parser.print_help()
        return UNKNOWN
    if "--version" in argv:
        print(f"{parser.prog} {VERSION}")
        return UNKNOWN
    return None
