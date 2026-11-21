"""Issue #105 / task 9.71: the Pages workflow publishes only what a site change moves.

`tests/unit/test_site.py` reads `pages.yml` for the branch, the manual trigger and four pinned
`uses:` references. It never looks at the `paths:` filter, the permission set or the dependency
between `deploy` and `build`, so `paths: **` or `contents: write` would keep the suite green while
the workflow republished on every push or handed a write token to a job that only reads the tree.

This parses the workflow as text. PyYAML is not a dependency of this repository and adding one to
check six lines would be the wrong trade (`AGENTS.md` 4), so the parser is a narrow line scanner:
find a block by its `key:` header and indentation, then read the entries inside it. It reports the
file and the line of every value it refuses instead of passing because it recognised nothing.

Scope is this one file. `ci.yml` and `roadmap-check.yml` have their own tests.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pages.yml"
NAME = WORKFLOW.relative_to(REPO_ROOT).as_posix()

#: The only inputs that can change what the published site says. A rule change and the page that
#: describes it land together, and an unrelated source edit must not republish.
EXPECTED_PATHS = frozenset(
    {
        "site/**",
        "rules/builtin/**",
        "scripts/build_site.py",
        ".github/workflows/pages.yml",
    }
)

#: The smallest set Pages accepts: read the tree, write the deployment, mint the OIDC token that
#: `deploy-pages` exchanges for it.
EXPECTED_PERMISSIONS = {
    "contents": "read",
    "pages": "write",
    "id-token": "write",
}

#: The check that stops a stale page from publishing.
CHECK_COMMAND = "python scripts/build_site.py --check"

_SHA = re.compile(r"[0-9a-f]{40}")


def _content(line: str) -> str | None:
    """A line with its comment and blank padding removed, or None when nothing is left."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    body = line.split(" #", 1)[0].rstrip() if " #" in line else line.rstrip()
    return body.strip() or None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _key(body: str) -> str:
    """The key of a `key: value` line, or an empty string for a list item."""
    head, sep, _ = body.partition(":")
    return head.strip() if sep and not body.startswith("- ") else ""


def block(lines: list[str], key: str, indent: int, start: int = 0) -> tuple[int, int] | None:
    """The 0-based (first, last exclusive) lines of the `key:` block at `indent`."""
    for index in range(start, len(lines)):
        body = _content(lines[index])
        if body is not None and _indent(lines[index]) == indent and _key(body) == key:
            first = index
            break
    else:
        return None

    last = len(lines)
    for index in range(first + 1, len(lines)):
        body = _content(lines[index])
        if body is not None and _indent(lines[index]) <= indent:
            last = index
            break
    return first, last


def entries(lines: list[str], span: tuple[int, int]) -> Iterator[tuple[int, str, str]]:
    """Every `key: value` line in a block as (one-based line, key, value)."""
    first, last = span
    for index in range(first + 1, last):
        body = _content(lines[index])
        if body is None or body.startswith("- ") or _key(body) == "":
            continue
        _, _, value = body.partition(":")
        yield index + 1, _key(body), value.strip()


def list_items(lines: list[str], span: tuple[int, int]) -> Iterator[tuple[int, str]]:
    """Every list item in a block as (one-based line, value)."""
    first, last = span
    for index in range(first, last):
        body = _content(lines[index])
        if body is None or not body.startswith("- "):
            continue
        yield index + 1, body[2:].strip().strip("\"'")


def test_the_trigger_paths_are_exactly_the_site_inputs() -> None:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    push = block(lines, "push", indent=2)
    assert push is not None, f"{NAME}: no push: trigger under on:"
    paths = block(lines, "paths", indent=4, start=push[0])
    assert paths is not None, f"{NAME}:{push[0] + 1}: push has no paths: filter"

    found = dict(list_items(lines, paths))
    unexpected = {value for value in found.values() if value not in EXPECTED_PATHS}
    missing = EXPECTED_PATHS - set(found.values())

    assert not unexpected, "\n".join(
        f"{NAME}:{number}: unexpected path {value!r}; expected {sorted(EXPECTED_PATHS)}"
        for number, value in found.items()
        if value in unexpected
    )
    assert not missing, f"{NAME}:{paths[0] + 1}: missing path(s) {sorted(missing)}"
    assert len(found) == len(EXPECTED_PATHS), (
        f"{NAME}:{paths[0] + 1}: {len(found)} path entries, expected {len(EXPECTED_PATHS)}"
    )


def test_permissions_are_the_three_pages_needs() -> None:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    permissions = block(lines, "permissions", indent=0)
    assert permissions is not None, f"{NAME}: no top-level permissions: block"

    granted = {(key, value) for _, key, value in entries(lines, permissions)}
    assert granted == set(EXPECTED_PERMISSIONS.items()), (
        f"{NAME}:{permissions[0] + 1}: permissions are {sorted(granted)}, "
        f"expected {sorted(EXPECTED_PERMISSIONS.items())}"
    )


def test_deploy_runs_only_after_build() -> None:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    jobs = block(lines, "jobs", indent=0)
    assert jobs is not None, f"{NAME}: no jobs: block"
    deploy = block(lines, "deploy", indent=2, start=jobs[0])
    assert deploy is not None, f"{NAME}:{jobs[0] + 1}: no deploy job"

    needs = {key: (number, value) for number, key, value in entries(lines, deploy)}
    assert "needs" in needs, f"{NAME}:{deploy[0] + 1}: deploy declares no needs:"
    number, value = needs["needs"]
    assert value == "build", f"{NAME}:{number}: deploy needs {value!r}, expected 'build'"


def test_build_checks_the_rule_reference_before_publishing() -> None:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    jobs = block(lines, "jobs", indent=0)
    assert jobs is not None, f"{NAME}: no jobs: block"
    build = block(lines, "build", indent=2, start=jobs[0])
    assert build is not None, f"{NAME}:{jobs[0] + 1}: no build job"

    runs = [value for _, key, value in entries(lines, build) if key == "run"]
    assert CHECK_COMMAND in runs, (
        f"{NAME}:{build[0] + 1}: the build job runs {runs}, expected a step running "
        f"{CHECK_COMMAND!r}"
    )


def test_the_deploy_step_is_pinned_by_commit() -> None:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    jobs = block(lines, "jobs", indent=0)
    assert jobs is not None, f"{NAME}: no jobs: block"
    deploy = block(lines, "deploy", indent=2, start=jobs[0])
    assert deploy is not None, f"{NAME}:{jobs[0] + 1}: no deploy job"

    references = [(number, value) for number, key, value in entries(lines, deploy) if key == "uses"]
    assert references, f"{NAME}:{deploy[0] + 1}: deploy runs no action"

    for number, reference in references:
        name, _, pinned = reference.partition("@")
        assert name, f"{NAME}:{number}: {reference!r} names no action"
        assert _SHA.fullmatch(pinned), (
            f"{NAME}:{number}: {name} is pinned to {pinned!r}, expected a 40-character commit SHA"
        )
