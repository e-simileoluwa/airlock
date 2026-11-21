"""`scripts/README.md` must be the directory's index, in both directions (issue #98).

The scripts under `scripts/` are run by hand against this repository, and four of them write into
it. Their safety notes lived only in their own headers, so nothing tied the documentation page to
the directory: a new script could appear with no row, and a row could survive a deleted script. This
module closes both halves by comparing the table with the files.

The comparison is a set difference reported by name rather than one equality, because the two
failures need different repairs. A file with no row means an undocumented entry point; a row with
no file means a page describing something a reader can no longer run.

The test reads files and never executes one, so running the suite cannot reach
`create_wave_issues.sh --apply`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
INDEX = SCRIPTS_DIR / "README.md"

#: The index documents entry points, and the table is the index's own markup rather than a script.
EXCLUDED_NAMES = frozenset({INDEX.name})

#: Purpose, flags, writes and network, next to the name.
COLUMNS = 5

_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|")


def entry_points(directory: Path) -> frozenset[str]:
    """The files in `directory` that a person or a workflow can run.

    Hidden files are placeholders rather than entry points: `.gitkeep` keeps the directory in git,
    and a row for it would push the real documentation down without saying anything.
    """
    return frozenset(
        path.name
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".") and path.name not in EXCLUDED_NAMES
    )


def documented_rows(markdown: str) -> dict[str, list[str]]:
    """Map each backticked script name in a table to the row's cells.

    A row is recognised by a backticked first cell, which is the one thing every entry has in
    common and the thing the comparison turns on.
    """
    rows: dict[str, list[str]] = {}
    for line in markdown.splitlines():
        match = _ROW.match(line)
        if match is not None:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            rows[match.group(1)] = cells
    return rows


def undeclared(entry_files: frozenset[str], rows: frozenset[str]) -> tuple[list[str], list[str]]:
    """Return (files with no row, rows with no file), each sorted."""
    return sorted(entry_files - rows), sorted(rows - entry_files)


def test_every_script_has_a_row_and_every_row_has_a_script() -> None:
    files = entry_points(SCRIPTS_DIR)
    rows = frozenset(documented_rows(INDEX.read_text(encoding="utf-8")))
    missing, orphaned = undeclared(files, rows)
    assert not missing, f"scripts with no row in scripts/README.md: {', '.join(missing)}"
    assert not orphaned, f"scripts/README.md rows naming no file: {', '.join(orphaned)}"


def test_the_index_lists_the_scripts_the_directory_holds() -> None:
    """The other direction of the same equality, stated as content.

    A reader checking whether the guard works needs to know what it is guarding, not only that it
    did not fire: this names the entry points the page is supposed to document.
    """
    files = entry_points(SCRIPTS_DIR)
    rows = documented_rows(INDEX.read_text(encoding="utf-8"))
    assert set(rows) == set(files)
    assert len(files) >= 6, f"the index covers {sorted(files)}, which is fewer scripts than exist"


def test_every_row_states_its_side_effects() -> None:
    """A row that answers only the purpose question is the gap this issue is about.

    Each cell is checked for text rather than for content: whether the sentence is right is a
    review question, and the table is short enough to read.
    """
    rows = documented_rows(INDEX.read_text(encoding="utf-8"))
    assert rows, "no script rows were parsed, so this check would pass on an empty page"
    for name, cells in rows.items():
        assert len(cells) == COLUMNS, f"{name}: the row has {len(cells)} cells, not {COLUMNS}"
        empty = [index for index, cell in enumerate(cells) if not cell or cell == "-"]
        assert not empty, f"{name}: cells {empty} are blank; flags, writes and network stay stated"


def test_a_script_with_no_row_is_named_by_the_guard(tmp_path: Path) -> None:
    """The failure this file exists to produce, exercised rather than recorded once by hand.

    `scripts/scratch.py` is created in a copy of the directory so the check runs against a tree
    that gains an undocumented entry point without the repository noticing it.
    """
    scratch = tmp_path / "scripts"
    scratch.mkdir()
    for name in ("build_site.py", "roadmap_progress.py"):
        (scratch / name).write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    (scratch / ".gitkeep").touch()

    table = "\n".join(
        [
            "| Script | Purpose | Flags | Writes | Network |",
            "|---|---|---|---|---|",
            "| `build_site.py` | does a thing | `--check` | site files | none |",
            "| `roadmap_progress.py` | does another | `--check` | ROADMAP.md | none |",
        ]
    )
    files = entry_points(scratch)
    assert files == frozenset({"build_site.py", "roadmap_progress.py"}), (
        "a hidden file was treated as an entry point"
    )
    assert undeclared(files, frozenset(documented_rows(table))) == ([], [])

    (scratch / "scratch.py").write_text("", encoding="utf-8")
    missing, orphaned = undeclared(entry_points(scratch), frozenset(documented_rows(table)))
    assert missing == ["scratch.py"], missing
    assert orphaned == []
