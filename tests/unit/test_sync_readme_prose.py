"""Issue #82: the README prose test count is generated with the table beside it.

`sync_readme.py` already rewrote the metrics table and the prose number, but the prose span was a
bare regex, so a hand edit to either number was invisible until the next run replaced it. The
sentence now lives between `TESTS:COUNT` markers that the same `count_tests()` result fills, and
`--check` names the file and the expected sentence when the two disagree.

The repository's own README is the fixture for the round-trip; no collection run happens because
the counts are injected.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "sync_readme.py"
TESTS = 1170
RULES = 28
FAMILIES = 8

README = """# Fixture

<!-- METRICS:START -->
stale table
<!-- METRICS:END -->

| | |
|---|---|
| Works today | scanner; <!-- TESTS:COUNT -->664 tests in CI<!-- /TESTS:COUNT --> |
"""


def load_sync_readme():
    spec = importlib.util.spec_from_file_location("sync_readme_prose_fixture", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sync_readme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = load_sync_readme()
    readme = tmp_path / "README.md"
    readme.write_text(README, encoding="utf-8")
    monkeypatch.setattr(module, "README_PATH", readme)
    monkeypatch.setattr(module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(module, "count_tests", lambda: TESTS)
    monkeypatch.setattr(module, "count_rules", lambda: RULES)
    monkeypatch.setattr(module, "count_families", lambda: FAMILIES)
    return module, readme


def test_one_write_path_fills_the_table_and_the_prose(sync_readme) -> None:
    module, readme = sync_readme

    assert module.sync() is True

    text = readme.read_text(encoding="utf-8")
    assert f"| Test Suite | **{TESTS} passing** |" in text
    assert f"{module.PROSE_START}{TESTS} tests in CI{module.PROSE_END}" in text
    assert text.count(f"{TESTS} tests in CI") == 1


def test_the_marked_spans_round_trip(sync_readme) -> None:
    module, readme = sync_readme

    assert module.sync() is True
    once = readme.read_text(encoding="utf-8")
    assert module.sync() is True
    twice = readme.read_text(encoding="utf-8")

    assert once == twice
    assert module.METRICS_START in twice and module.METRICS_END in twice
    assert module.PROSE_START in twice and module.PROSE_END in twice


def test_check_names_the_file_and_the_expected_count(sync_readme, capsys) -> None:
    module, readme = sync_readme
    assert module.sync() is True
    current = readme.read_text(encoding="utf-8")
    stale = current.replace(f"{TESTS} tests in CI", "663 tests in CI", 1)
    readme.write_text(stale, encoding="utf-8")

    assert module.sync(check=True) is False

    err = capsys.readouterr().err
    assert "README.md" in err
    assert f"expected '{TESTS} tests in CI'" in err
    assert "663 tests in CI" in err
    assert readme.read_text(encoding="utf-8") == stale


def test_main_exits_one_on_a_stale_prose_count_and_zero_after_a_run(
    sync_readme, monkeypatch, capsys
) -> None:
    module, readme = sync_readme
    assert module.sync() is True
    current = readme.read_text(encoding="utf-8")
    readme.write_text(current.replace(f"{TESTS} tests in CI", "0 tests in CI", 1), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--check"])
    assert module.main() == 1
    capsys.readouterr()

    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    assert module.main() == 0
    assert module.sync(check=True) is True
