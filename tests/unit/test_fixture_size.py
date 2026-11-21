"""Issue #95 / task 9.71: a fixture half stays small enough to review.

`tests/fixtures/__init__.py` says the caps here are smaller than the shipped policy defaults
because a fixture should be long because the rule says so, not because it is the size of a real
bundle. That was prose. `Case.files` holds `File` objects, and `File.raw` accepts a blob of any
length, so a builder could hand the parametrized gate a payload no reviewer would read. `AGENTS.md`
4 forbids committing the payload itself, which leaves the builder as the only artifact of the case
a reviewer can inspect.

The measurement is `File.content()`, not the length of `File.text`: `raw` is valid input and is
exactly the case a byte cap protects against, so measuring text alone would leave binary fixtures
at zero. A half left `None` is skipped here the way `test_fixtures.py` skips it, because a missing
half is the coverage gate's failure and not a size one.
"""

from __future__ import annotations

from tests.fixtures import Case, File, builders

#: The most bytes one half of one builder may add up to. The largest shipped half is
#: `npm_lockfile_registry` negative at 253 bytes, so this leaves room for a real trigger without
#: admitting a blob. `tests/fixtures/README.md` states the same number, because a cap written in
#: two places is only useful while the two agree.
CAP_BYTES = 1024


def case_bytes(case: Case) -> int:
    """Every byte the collector would receive for one half, raw files included."""
    return sum(len(file.content()) for file in case.files)


def test_every_fixture_half_stays_under_the_cap() -> None:
    oversized: list[str] = []
    for name, build in builders().items():
        fixture = build()
        for half in ("positive", "negative"):
            case = getattr(fixture, half)
            if case is None:
                continue
            size = case_bytes(case)
            if size > CAP_BYTES:
                oversized.append(f"{name}.{half} is {size} bytes, cap is {CAP_BYTES} bytes")

    assert oversized == [], "\n".join(oversized)


def test_raw_bytes_count_toward_the_cap() -> None:
    """A cap that only measured `text` would read every binary fixture as empty."""
    case = Case(files=(File(path="payload.bin", raw=b"\0" * (CAP_BYTES + 1)),))

    assert case_bytes(case) > CAP_BYTES
