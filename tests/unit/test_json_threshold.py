"""Issue #70: the JSON report records the gate that produced `exit_code`.

Two runs over the same WARN-only finding can exit differently because one used `--fail-on warn`
and the other kept the policy's `high`. Without the threshold in the report a consumer cannot
tell a stricter workflow from a policy change, so `ScanReport.fail_on` travels from the one
expression `run_scan` already uses to decide the exit code.

The repository fixture produces one WARN (`cfg-long-line` in a source role) and nothing else, so
the two gates are observably different over identical findings.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from tests.unit.test_cli import scan

from airlock.model import EXIT_FINDINGS, EXIT_PASS, Severity

POLICY_WARN = """version = 1

[policy]
fail_on = "warn"
line_cap = 80
"""

POLICY_HIGH = """version = 1

[policy]
fail_on = "high"
line_cap = 80
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "--initial-branch=main")
    return root


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=airlock-test",
            "-c",
            "user.email=airlock-test@example.invalid",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def seed(root: Path, policy: str) -> None:
    write(root, "airlock.toml", policy)
    write(root, "wasm-manifest.toml", "version = 1\n")
    write(root, "src/app.js", f"const value = {'a' * 120};\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")


def write(root: Path, rel: str, data: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def report(repo: Path, *flags: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    code, out = scan(repo, "--mode", "full", "--format", "json", *flags, capsys=capsys)
    return code, json.loads(out)


def test_the_two_gates_differ_over_the_same_warn_only_report(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(repo, POLICY_HIGH)

    warn_code, warn_report = report(repo, "--fail-on", "warn", capsys=capsys)
    high_code, high_report = report(repo, "--fail-on", "high", capsys=capsys)

    assert warn_report["findings"], "the fixture must carry a WARN finding"
    severities = {finding["severity"] for finding in warn_report["findings"]}
    assert "warn" in severities and "high" not in severities
    assert warn_report["fail_on"] == "warn"
    assert high_report["fail_on"] == "high"
    assert warn_code == EXIT_FINDINGS
    assert high_code == EXIT_PASS
    assert warn_report["exit_code"] == EXIT_FINDINGS
    assert high_report["exit_code"] == EXIT_PASS


def test_with_no_flag_the_field_is_the_policy_fail_on(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(repo, POLICY_WARN)

    code, data = report(repo, capsys=capsys)

    assert data["fail_on"] == "warn"
    assert code == EXIT_FINDINGS


def test_the_field_sits_next_to_exit_code_and_uses_the_severity_label(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(repo, POLICY_HIGH)

    _, data = report(repo, "--fail-on", "warn", capsys=capsys)

    ordered = [key for key in data if key in {"exit_code", "fail_on", "findings"}]
    assert ordered == ["exit_code", "fail_on", "findings"]
    assert data["fail_on"] == Severity.WARN.label


def test_the_default_threshold_is_high(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    seed(repo, POLICY_HIGH)

    _, data = report(repo, capsys=capsys)

    assert data["fail_on"] == "high"
    assert data["exit_code"] == EXIT_PASS
