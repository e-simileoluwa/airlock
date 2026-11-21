"""Issue #106 / task 9.71: the generated site does not depend on the machine that wrote it.

`tests/unit/test_build_site.py` calls the generator twice in one process and compares two pages.
Both runs share an interpreter, a hash seed and a locale, so that proves idempotence, not that two
machines produce the same bytes, which is what `scripts/build_site.py --check` needs to mean when
`.github/workflows/pages.yml` runs it on a hosted runner.

This runs the generator as a subprocess against copies of its inputs, under both hash seeds and
both locales, and compares the output trees by relative path and bytes. Isolation comes from the
environment rather than an in-process `locale` call (`AGENTS.md` 5: no dependency, no global
mutation), and every run asserts exit 0 before its tree is read.

The locale half skips on a host without `C.UTF-8` rather than pretending to have run it; the skip
message names the package that provides the locale.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests.unit.test_build_site import copy_inputs

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_site.py"

#: The seeds and locales the matrix pairs. A hash seed changes set iteration order and a locale
#: changes collation, which are the two ways a generated page can depend on the writer's machine.
HASH_SEEDS = ("0", "1")
BASE_LOCALE = "C"
UTF8_LOCALE = "C.UTF-8"

#: Files the generator writes. At least these must survive a run for a comparison to mean anything.
GENERATED = ("data/rules.json", "rules.html", "index.html")


def build(root: Path, *, hash_seed: str, locale: str) -> dict[str, bytes]:
    """Run the generator over one copy and return its output tree, by relative path."""
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = hash_seed
    environment["LC_ALL"] = locale
    environment["LANG"] = locale

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, (
        f"build_site.py failed with PYTHONHASHSEED={hash_seed} LC_ALL={locale}: {result.stderr}"
    )

    site = root / "site"
    return {
        path.relative_to(site).as_posix(): path.read_bytes()
        for path in sorted(site.rglob("*"))
        if path.is_file()
    }


def first_difference(left: dict[str, bytes], right: dict[str, bytes]) -> str | None:
    """The first differing path and line between two trees, or None when they are identical."""
    for name in sorted(set(left) | set(right)):
        if name not in left:
            return f"{name} is missing from the reference tree"
        if name not in right:
            return f"{name} is missing from the comparison tree"
        if left[name] == right[name]:
            continue
        first = left[name].decode("utf-8", "replace").splitlines()
        second = right[name].decode("utf-8", "replace").splitlines()
        for number, (a, b) in enumerate(zip(first, second, strict=False), start=1):
            if a != b:
                return f"{name}:{number}: {a!r} != {b!r}"
        return f"{name}: {len(first)} lines vs {len(second)} lines"
    return None


def utf8_locale_available() -> bool:
    """Whether this host lists `C.UTF-8`, under any of the spellings `locale -a` uses."""
    result = subprocess.run(["locale", "-a"], capture_output=True, text=True, check=False)
    names = {
        line.strip().lower().replace("-", "").replace("_", "")
        for line in result.stdout.splitlines()
    }
    return "c.utf8" in names


def assert_present(tree: dict[str, bytes]) -> None:
    for name in GENERATED:
        assert name in tree, f"{name} was not generated"


def test_hash_seed_does_not_change_the_generated_site(tmp_path: Path) -> None:
    reference_root = copy_inputs(tmp_path / "reference")
    comparison_root = copy_inputs(tmp_path / "comparison")

    reference = build(reference_root, hash_seed="0", locale=BASE_LOCALE)
    assert_present(reference)

    for seed in HASH_SEEDS:
        built = build(comparison_root, hash_seed=seed, locale=BASE_LOCALE)
        difference = first_difference(reference, built)

        assert difference is None, f"PYTHONHASHSEED={seed} changed the site: {difference}"


@pytest.mark.skipif(
    not utf8_locale_available(),
    reason=(
        "C.UTF-8 is not installed on this host; on Debian and Ubuntu the locales package "
        "provides it, and current releases ship it in libc-bin"
    ),
)
def test_locale_does_not_change_the_generated_site(tmp_path: Path) -> None:
    reference_root = copy_inputs(tmp_path / "reference")
    comparison_root = copy_inputs(tmp_path / "comparison")

    reference = build(reference_root, hash_seed="0", locale=BASE_LOCALE)
    assert_present(reference)

    for seed in HASH_SEEDS:
        built = build(comparison_root, hash_seed=seed, locale=UTF8_LOCALE)
        difference = first_difference(reference, built)

        assert difference is None, (
            f"LC_ALL={UTF8_LOCALE} with PYTHONHASHSEED={seed} changed the site: {difference}"
        )
