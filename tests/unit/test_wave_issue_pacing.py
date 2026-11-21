"""Issue #81: the Wave publication script survives a secondary rate limit.

A stub `gh` on PATH records every call, fails the first two creates with a 403 secondary limit and
then succeeds. The script must make three attempts for that issue, edit it once, and spend the
delays the helper chose rather than the wall clock: `AIRLOCK_WAVE_SLEEP_LOG` records them.

The other cases are the shapes that must not retry or must fail: a 404, a 429 that never clears,
and a successful exit with no URL.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "create_wave_issues.sh"

STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$GH_STUB_LOG"
cmd=$1
if [ "$cmd" = "api" ]; then
    exit 0
fi
if [ "$cmd" != "issue" ]; then
    exit 0
fi
verb=$2
if [ "$verb" = "edit" ]; then
    exit 0
fi
count=$(cat "$GH_STUB_CREATE_COUNT" 2>/dev/null || printf '0')
count=$((count + 1))
printf '%s' "$count" > "$GH_STUB_CREATE_COUNT"
case "${GH_STUB_MODE:-retry}" in
    retry)
        if [ "$count" -le 2 ]; then
            printf 'HTTP 403: You have exceeded a secondary rate limit. Retry-After: 7\\n' >&2
            exit 1
        fi
        printf 'https://github.com/owner/name/issues/%s\\n' "$count"
        ;;
    empty)
        exit 0
        ;;
    notfound)
        printf 'HTTP 404: Not Found\\n' >&2
        exit 1
        ;;
    denied)
        printf 'HTTP 403: Resource not accessible by integration\\n' >&2
        exit 1
        ;;
    always)
        printf 'HTTP 429: rate limited\\n' >&2
        exit 1
        ;;
esac
"""

ISSUES = {
    "01-first.md": """---
title: First issue
labels: bug, Stellar Wave
roadmap: 9.63
---
Body with a self reference {{issue:self}}.
""",
    "02-second.md": """---
title: Second issue
labels: bug, Stellar Wave
roadmap: 9.64
---
Body that blocks on {{issue:first}}.
""",
}


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    issues = tmp_path / "issues"
    issues.mkdir()
    for name, text in ISSUES.items():
        (issues / name).write_text(text, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gh"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)
    return {
        "issues": issues,
        "bin": bin_dir,
        "log": tmp_path / "calls.log",
        "count": tmp_path / "create.count",
        "sleep": tmp_path / "sleep.log",
    }


def run(workspace: dict[str, Path], *, mode: str = "retry", apply: bool = True):
    env = dict(os.environ)
    env["PATH"] = f"{workspace['bin']}{os.pathsep}{env['PATH']}"
    env["GH_STUB_LOG"] = str(workspace["log"])
    env["GH_STUB_CREATE_COUNT"] = str(workspace["count"])
    env["GH_STUB_MODE"] = mode
    env["AIRLOCK_WAVE_SLEEP_LOG"] = str(workspace["sleep"])
    command = [shutil.which("sh") or "sh", str(SCRIPT)]
    if apply:
        command.append("--apply")
    command += ["--repo", "owner/name", "--dir", str(workspace["issues"])]
    return subprocess.run(command, capture_output=True, text=True, check=False, env=env)


def calls(workspace: dict[str, Path]) -> list[str]:
    if not workspace["log"].exists():
        return []
    return workspace["log"].read_text(encoding="utf-8").splitlines()


def test_two_rate_limits_are_retried_then_the_batch_finishes(workspace) -> None:
    result = run(workspace)

    assert result.returncode == 0, result.stderr
    creates = [call for call in calls(workspace) if call.startswith("issue create")]
    edits = [call for call in calls(workspace) if call.startswith("issue edit")]
    assert len(creates) == 4
    assert sum("First issue" in call for call in creates) == 3
    assert len(edits) == 1
    assert "created #3  First issue" in result.stdout
    assert "created #4  Second issue" in result.stdout
    assert workspace["sleep"].read_text(encoding="utf-8").split() == ["7", "7"]


def test_the_backoff_is_exponential_without_a_retry_after_header(workspace) -> None:
    module_stub = workspace["bin"] / "gh"
    module_stub.write_text(STUB.replace(" Retry-After: 7", ""), encoding="utf-8")

    result = run(workspace)

    assert result.returncode == 0, result.stderr
    delays = [int(value) for value in workspace["sleep"].read_text(encoding="utf-8").split()]
    assert len(delays) == 2
    assert 2 <= delays[0] <= 4
    assert 4 <= delays[1] <= 6


def test_a_non_rate_limit_404_fails_without_retrying(workspace) -> None:
    result = run(workspace, mode="notfound")

    assert result.returncode != 0
    creates = [call for call in calls(workspace) if call.startswith("issue create")]
    assert len(creates) == 1
    assert "HTTP 404: Not Found" in result.stderr
    assert not workspace["sleep"].exists()


def test_a_403_that_is_not_a_rate_limit_fails_without_retrying(workspace) -> None:
    result = run(workspace, mode="denied")

    assert result.returncode != 0
    creates = [call for call in calls(workspace) if call.startswith("issue create")]
    assert len(creates) == 1
    assert "Resource not accessible" in result.stderr
    assert not workspace["sleep"].exists()


def test_exhausted_attempts_name_the_count_and_the_last_error(workspace) -> None:
    result = run(workspace, mode="always")

    assert result.returncode != 0
    creates = [call for call in calls(workspace) if call.startswith("issue create")]
    assert len(creates) == 5
    assert "after 5 attempts" in result.stderr
    assert "HTTP 429: rate limited" in result.stderr
    assert len(workspace["sleep"].read_text(encoding="utf-8").split()) == 4


def test_a_successful_create_with_no_url_is_a_failure(workspace) -> None:
    result = run(workspace, mode="empty")

    assert result.returncode != 0
    assert "returned no URL" in result.stderr
    assert not workspace["sleep"].exists()


def test_the_dry_run_calls_nothing(workspace) -> None:
    result = run(workspace, apply=False)

    assert result.returncode == 0
    assert "dry run" in result.stdout
    assert calls(workspace) == []
