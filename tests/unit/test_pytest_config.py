"""Pytest is held to the same strictness as the other gates (issue #91).

`mypy src` fails on an unannotated line and `ruff check .` fails on an unused import, but until now
pytest tolerated two quiet mistakes: an unregistered marker only warns during collection and the
test runs anyway, and a `DeprecationWarning` prints once and is scrolled past. The second one is
the
reason for the first sentence of `pyproject.toml`'s `requires-python`: the package promises 3.11 to
3.13, and a standard library path that is deprecated on 3.13 stays invisible here until the release
that removes it.

Both are errors now. This module reads the configuration back out of `pyproject.toml` rather than
trusting it, because the failure this guards against is somebody removing one of the two options and
the suite staying green while they do.

Two of the cases run pytest as a subprocess against a throwaway test file. They are the only way to
show that the options bite: an assertion about the text of `pyproject.toml` proves the setting is
there, and a subprocess proves pytest obeys it.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / "pyproject.toml"

#: The exemption spelling: an action, a colon, and a message pattern that is not empty.
_EXEMPTION = re.compile(r"^(ignore|once|default|error|always):(.+)$")


def ini_options() -> dict[str, Any]:
    with CONFIG.open("rb") as handle:
        return tomllib.load(handle)["tool"]["pytest"]["ini_options"]


def filterwarnings_entries(raw: str) -> list[tuple[str, bool]]:
    """Each `filterwarnings` entry with whether a comment documents it.

    The array is read from the text rather than from the parsed TOML because the comment is the
    thing being checked, and a parsed document has already thrown it away. One entry per line is
    part of the contract, so an exemption cannot hide at the end of a line with no room to explain
    itself.
    """
    block = re.search(r"^filterwarnings\s*=\s*\[(.*?)\n\]", raw, re.M | re.S)
    assert block is not None, (
        "filterwarnings is not a multi-line array, so it cannot carry comments"
    )
    entries: list[tuple[str, bool]] = []
    pending_comment = False
    for line in block.group(1).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            pending_comment = True
            continue
        match = re.match(r'"([^"]*)"', stripped)
        if match is not None:
            entries.append((match.group(1), pending_comment))
        pending_comment = False
    return entries


def undocumented_exemptions(entries: list[tuple[str, bool]]) -> list[str]:
    """Exemptions that are not `ignore:` patterns with a documented reason."""
    bad: list[str] = []
    for text, commented in entries[1:]:
        match = _EXEMPTION.match(text)
        if match is None or match.group(1) != "ignore" or not commented:
            bad.append(text)
    return bad


def markers_without_descriptions(markers: list[str]) -> list[str]:
    """Registered markers spelled without the description pytest shows in `--markers`."""
    return [
        marker
        for marker in markers
        if len(marker.split(":", 1)) != 2 or not marker.split(":", 1)[1].strip()
    ]


class TestStrictMarkers:
    def test_the_option_is_set(self) -> None:
        assert "--strict-markers" in ini_options()["addopts"]

    def test_an_unregistered_marker_fails_collection(self, tmp_path: Path) -> None:
        """The behaviour the option exists for, observed rather than inferred from the setting.

        Without `--strict-markers` this run collects one test, prints a warning nobody reads and
        passes; the misspelled marker then matches nothing in a selection, so `-m slow` quietly
        runs the whole suite or none of it.
        """
        probe = tmp_path / "test_typo_marker.py"
        probe.write_text(
            "import pytest\n\n\n"
            "@pytest.mark.typo\n"
            "def test_selected_by_a_marker_nobody_declared():\n"
            "    assert True\n",
            encoding="utf-8",
        )
        result = run_pytest(tmp_path, probe)
        assert result.returncode != 0, result.stdout + result.stderr
        combined = result.stdout + result.stderr
        assert "'typo' not found in `markers` configuration option" in combined, combined


class TestWarningsAsErrors:
    def test_error_is_the_first_entry(self) -> None:
        entries = filterwarnings_entries(CONFIG.read_text(encoding="utf-8"))
        assert entries, "filterwarnings holds no entries at all"
        assert entries[0][0] == "error", f"the first entry is {entries[0][0]!r}, not `error`"

    def test_every_exemption_is_a_documented_ignore(self) -> None:
        bad = undocumented_exemptions(filterwarnings_entries(CONFIG.read_text(encoding="utf-8")))
        assert not bad, (
            f"exemptions must be `ignore:` patterns with a comment naming the reason: {bad}"
        )

    def test_the_exemption_rule_bites_when_an_exemption_appears(self) -> None:
        """The two checks above pass today because the list holds only `error`.

        That makes them vacuous until someone adds an exemption, which is precisely when they are
        needed, so the rule itself is exercised against the spellings a contributor would reach for.
        """
        documented = [("error", False), ("ignore:DeprecationWarning:airlock\\.policy", True)]
        assert undocumented_exemptions(documented) == []

        uncommented = [("error", False), ("ignore:something:airlock.cli", False)]
        assert undocumented_exemptions(uncommented) == ["ignore:something:airlock.cli"]

        wrong_action = [("error", False), ("always:something:airlock.cli", True)]
        assert undocumented_exemptions(wrong_action) == ["always:something:airlock.cli"]

        bare_action = [("error", False), ("ignore:", True)]
        assert undocumented_exemptions(bare_action) == ["ignore:"], (
            "an empty pattern silences every warning in the suite"
        )

    def test_a_warning_reaching_the_suite_is_a_failure(self, tmp_path: Path) -> None:
        """The other half: the configuration is obeyed, not merely present."""
        probe = tmp_path / "test_emits_a_warning.py"
        probe.write_text(
            "import warnings\n\n\ndef test_warns():\n"
            "    warnings.warn(DeprecationWarning('removed in the next release'))\n",
            encoding="utf-8",
        )
        result = run_pytest(tmp_path, probe)
        assert result.returncode != 0, result.stdout + result.stderr
        assert "DeprecationWarning: removed in the next release" in result.stdout + result.stderr


class TestMarkerRegistrations:
    def test_every_registered_marker_explains_itself(self) -> None:
        assert markers_without_descriptions(ini_options().get("markers", [])) == []

    @pytest.mark.parametrize(
        ("marker", "documented"),
        [("slow: takes over a second", True), ("network", False), ("empty:", False)],
    )
    def test_the_description_rule(self, marker: str, documented: bool) -> None:
        bad = markers_without_descriptions([marker])
        assert (bad == []) is documented, f"{marker!r} was classified wrongly"


class TestExistingOptionsSurvive:
    def test_the_import_path_and_test_roots_are_untouched(self) -> None:
        """`mypy src` does not see `tests/`, and other modules import `tests.fixtures` through the
        `pythonpath` entry here. Dropping either while adding strictness breaks collection in a way
        the new options would not report.
        """
        options = ini_options()
        assert options["testpaths"] == ["tests"]
        assert options["pythonpath"] == ["src", "."]


def run_pytest(cwd: Path, target: Path) -> subprocess.CompletedProcess[str]:
    """Run pytest over `target` with this repository's configuration and nothing else.

    `-c` names the real `pyproject.toml` so the options under test apply, and
    `no:cacheprovider` keeps the probe from writing into the temporary directory it is asserting on.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-c",
            str(CONFIG),
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
