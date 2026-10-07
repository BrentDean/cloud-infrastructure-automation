import pathlib
import subprocess
import sys
from urllib.error import URLError

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[1] / "plugins"
sys.path.insert(0, str(PLUGIN_DIR))

import check_labops_http as http_check
import check_labops_nats as nats_check
import check_labops_systemd as systemd_check
from labops_plugin import CRITICAL, OK, UNKNOWN, WARNING, CheckResult


def test_monitoring_exit_code_contract():
    assert (OK, WARNING, CRITICAL, UNKNOWN) == (0, 1, 2, 3)


def test_result_renders_standard_status_and_perfdata():
    result = CheckResult(OK, "service healthy", "'latency'=12.5ms;250;1000;0")
    assert result.line() == "OK - service healthy | 'latency'=12.5ms;250;1000;0"


def test_nats_ok_and_warning(monkeypatch):
    monkeypatch.setattr(
        nats_check, "http_json", lambda *_args: (200, {"status": "ok"}, 12.5)
    )
    assert nats_check.check("http://nats", 250, 1000, 5).code == OK

    monkeypatch.setattr(
        nats_check, "http_json", lambda *_args: (200, {"status": "ok"}, 300.0)
    )
    result = nats_check.check("http://nats", 250, 1000, 5)
    assert result.code == WARNING
    assert "'latency'=300.0ms;250;1000;0" in result.line()


def test_nats_bad_health_is_critical(monkeypatch):
    monkeypatch.setattr(
        nats_check,
        "http_json",
        lambda *_args: (200, {"status": "unavailable"}, 4.0),
    )
    assert nats_check.check("http://nats", 250, 1000, 5).code == CRITICAL


def test_nats_connection_failure_is_critical(monkeypatch):
    def fail(*_args):
        raise URLError("connection refused")

    monkeypatch.setattr(nats_check, "http_json", fail)
    result = nats_check.check("http://nats", 250, 1000, 5)
    assert result.code == CRITICAL
    assert "connection refused" in result.summary


def test_http_requires_database_contract(monkeypatch):
    monkeypatch.setattr(
        http_check,
        "http_json",
        lambda *_args: (
            200,
            {"status": "ok", "db": "connected", "db_result": 1},
            22.0,
        ),
    )
    assert http_check.check("http://app/health", 500, 2000, 5).code == OK

    monkeypatch.setattr(
        http_check,
        "http_json",
        lambda *_args: (
            200,
            {"status": "ok", "db": "unavailable", "db_result": None},
            22.0,
        ),
    )
    assert http_check.check("http://app/health", 500, 2000, 5).code == CRITICAL


def test_systemd_active_and_inactive():
    def active(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, stdout="active\n")

    def inactive(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 3, stdout="inactive\n")

    ok = systemd_check.check("labops-event-worker", 5, runner=active)
    bad = systemd_check.check("labops-event-worker", 5, runner=inactive)

    assert ok.code == OK
    assert "'active'=1;;;0;1" in ok.line()
    assert bad.code == CRITICAL
    assert "'active'=0;;;0;1" in bad.line()


def test_systemd_missing_command_is_unknown():
    def missing(*_args, **_kwargs):
        raise FileNotFoundError

    result = systemd_check.check("labops-event-worker", 5, runner=missing)
    assert result.code == UNKNOWN
    assert "'active'=U;;;0;1" in result.line()


def test_invalid_latency_thresholds_return_unknown(capsys):
    code = nats_check.main(["-w", "1000", "-c", "500"])
    output = capsys.readouterr().out

    assert code == UNKNOWN
    assert output.startswith("UNKNOWN - invalid arguments:")


def test_help_uses_unknown_exit_code(capsys):
    code = http_check.main(["--help"])
    output = capsys.readouterr().out

    assert code == UNKNOWN
    assert "Check LabOps /health" in output
