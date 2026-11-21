"""Issue #71: reject a comparison flag the resolved trust model ignores.

`--base` is read only in pr mode and `--before` only in push mode. A scan that accepts either
elsewhere reports a tree scan while the operator believes they compared a change, so each
unusable pair is exit 2 before any file or policy is read.

The six rows below are the three modes against the two flags: four are refused, and the two the
mode actually reads still reach `run_scan`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from tests.unit.test_cli import scan, seed

from airlock.cli import DEFAULT_ROLES_FILE, DEFAULT_RULES_DIR, main
from airlock.model import EXIT_CONFIG

INVALID_PAIRS = [
    ("full", "--base", "full"),
    ("full", "--before", "full"),
    ("pr", "--before", "pr"),
    ("push", "--base", "push"),
]
VALID_PAIRS = [
    ("pr", "--base"),
    ("push", "--before"),
]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=airlock-test",
            "-c",
            "user.email=airlock-test@example.invalid",
            "init",
            "-q",
            "--initial-branch=main",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return root


@pytest.mark.parametrize(("mode", "flag", "resolved"), INVALID_PAIRS)
def test_a_flag_the_mode_does_not_read_exits_two(
    repo: Path,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    flag: str,
    resolved: str,
) -> None:
    base = seed(repo)
    code = main(
        [
            "scan",
            str(repo),
            "--rules-dir",
            str(DEFAULT_RULES_DIR),
            "--roles",
            str(DEFAULT_ROLES_FILE),
            "--mode",
            mode,
            flag,
            base,
        ]
    )
    captured = capsys.readouterr()

    assert code == EXIT_CONFIG
    assert captured.out == ""
    message = captured.err
    assert message.count("\n") == 1
    assert message.startswith(f"airlock: {flag} is only read in ")
    assert f"not {resolved}" in message
    assert "Traceback" not in message


def test_a_base_with_an_event_implied_full_mode_is_rejected(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = seed(repo)
    code = main(
        [
            "scan",
            str(repo),
            "--rules-dir",
            str(DEFAULT_RULES_DIR),
            "--roles",
            str(DEFAULT_ROLES_FILE),
            "--event",
            "workflow_dispatch",
            "--base",
            base,
        ]
    )
    captured = capsys.readouterr()

    assert code == EXIT_CONFIG
    assert captured.out == ""
    assert "--base is only read in pr mode, not full" in captured.err


@pytest.mark.parametrize(("mode", "flag"), VALID_PAIRS)
def test_the_flag_the_mode_reads_still_reaches_the_scan(
    repo: Path,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    flag: str,
) -> None:
    base = seed(repo)
    code, _ = scan(repo, "--mode", mode, flag, base, capsys=capsys)

    assert code != EXIT_CONFIG


def test_an_event_implied_pr_mode_accepts_a_base(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = seed(repo)
    code, _ = scan(repo, "--event", "pull_request", "--base", base, capsys=capsys)

    assert code != EXIT_CONFIG


def test_an_event_implied_push_mode_accepts_a_before(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = seed(repo)
    code, _ = scan(repo, "--event", "push", "--before", base, capsys=capsys)

    assert code != EXIT_CONFIG
