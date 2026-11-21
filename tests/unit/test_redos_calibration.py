"""Calibrate the ReDoS per-line budget from a baseline measured on this machine (issue #90).

`tests/unit/test_redos.py` has always compared a single wall-clock measurement against
`PER_LINE_BUDGET_MS = 60.0`, a number `PRD.md` 6.x records as measured once, on one machine. A fixed
ceiling cannot tell a slow pattern from a busy runner: the same correct pattern costs two or three
times as much when the machine is compiling something else, and the failure the reader sees says
nothing about which of the two happened.

So the budget gains a second bound, derived here. A cheap literal pattern is timed through the same
child-process harness as everything else, three times, and the median is that machine's cost of the
least work a cap-length line can represent. The ceiling is `max(PER_LINE_BUDGET_MS,
BASELINE_MULTIPLE * baseline)`: the shipped number stays as the absolute cap, and a loaded runner
lifts the bound instead of tripping it.

`test_the_budget_catches_a_pattern_that_backtracks` in `tests/unit/test_redos.py` proves the harness
still notices a backtracking pattern. The last test here proves the calibrated bound is not so
generous that it stops noticing.

The baseline is measured in the child process `worst_line_ms` spawns rather than in the test
process, because a number taken here has to include the same interpreter and regex-compilation
work the measured patterns pay. `import test_redos` sits inside the functions that need it:
`test_redos` imports this module at its top level for the ceiling, and a top-level import in both
directions would fail whichever file pytest loads first.
"""

from __future__ import annotations

import functools
import re
import statistics
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import types as _types

#: A plain literal with no quantifier and no alternation: as close to the floor of what a regex can
#: cost on one line as a real pattern gets. It does not occur in the bait lines it is measured
#: against, so every line is searched end to end rather than matched at offset zero.
BASELINE_SOURCE = "airlock"

#: Three, and the median of them. Two samples would make the median a mean, and a fourth answers a
#: question the third has already settled.
BASELINE_SAMPLES = 3

#: The baseline this constant was derived from, recorded so the arithmetic below can be checked
#: without a machine that matches it. Measured six times on an idle Apple M-series laptop: 0.079 to
#: 0.085 ms, median of medians 0.0836.
REFERENCE_BASELINE_MS = 0.08

#: How much room one line gets, in baseline units.
#:
#: The shipped bound is 60 ms, which `tests/unit/test_redos.py` describes as roughly three times the
#: slowest pattern the rule data contains (about 20 ms). At the reference baseline that 60 ms is 750
#: units, so a machine as fast as the one it was measured on gets the historical bound and nothing
#: looser, while a runner twice as slow gets twice the room. It is a maximum with the absolute cap
#: rather than a replacement for it, so a machine faster than the reference cannot tighten the test.
BASELINE_MULTIPLE = 750.0

#: The ceiling on the ceiling. A baseline measured above this does not mean the runner is loaded, it
#: means something is wrong with the measurement, and a budget derived from it would be meaningless.
BASELINE_SANE_MAX_MS = 1.0


def _redos() -> _types.ModuleType:
    """The harness this module calibrates, imported at call time. See the module docstring."""
    import test_redos

    return test_redos


def baseline_bait(test_redos: _types.ModuleType) -> tuple[str, ...]:
    """The cap-length lines the baseline is timed against, built by the harness's own generator."""
    return test_redos.bait_lines(BASELINE_SOURCE)


def baseline_samples(measurements: int = BASELINE_SAMPLES) -> list[float]:
    """The slowest baseline line, `measurements` times, in milliseconds."""
    test_redos = _redos()
    pattern = re.compile(BASELINE_SOURCE)
    bait = baseline_bait(test_redos)
    return [test_redos.worst_line_ms(pattern, bait) for _ in range(measurements)]


@functools.lru_cache(maxsize=1)
def measure_baseline_ms() -> float:
    """The median of `baseline_samples()`: this machine's cost of the cheapest capped line.

    Cached because both this module and `tests/unit/test_redos.py` ask for it, and the run has one
    machine. `baseline_samples()` stays uncached so the spread test can watch fresh measurements.
    """
    return statistics.median(baseline_samples())


def calibrated_ceiling_ms(baseline_ms: float) -> float:
    """The per-line ceiling a machine with this baseline should be held to."""
    import test_redos

    return max(test_redos.PER_LINE_BUDGET_MS, BASELINE_MULTIPLE * baseline_ms)


@pytest.fixture(scope="session")
def baseline_ms() -> float:
    """One baseline per run: three child processes, not three per parametrized pattern."""
    return measure_baseline_ms()


def test_the_baseline_is_positive_and_small() -> None:
    """The measured number, reported for the record.

    Issue #90 section 9 asks for the spread to be raised rather than multiplied around if the three
    samples disagree by more than half. That is a decision about the constant, not a property of
    every future run, and an assertion here would fail a busy runner for the reason this module
    exists to stop failing it, so the samples are printed and what is checked is that the baseline
    is a plausible floor: some time, and far inside the bound it calibrates.
    """
    samples = baseline_samples()
    median = statistics.median(samples)
    print(
        f"\nbaseline samples (ms): {', '.join(f'{s:.4f}' for s in samples)}, "
        f"median {median:.4f}, widest over narrowest {max(samples) / min(samples):.2f}"
    )
    assert all(sample > 0.0 for sample in samples), samples
    assert median < BASELINE_SANE_MAX_MS, (
        f"a literal scan of one capped line took {median:.3f} ms, which is not a baseline"
    )


def test_the_multiple_reproduces_the_shipped_cap_on_the_reference_machine() -> None:
    """The derivation, as arithmetic a reviewer can check without running anything.

    `BASELINE_MULTIPLE` was chosen so that the number the suite has always used is what a machine
    at the reference baseline gets. Drift here means someone changed the multiple without
    re-deriving it.
    """
    import test_redos

    assert calibrated_ceiling_ms(REFERENCE_BASELINE_MS) == pytest.approx(
        test_redos.PER_LINE_BUDGET_MS, rel=0.06
    )


def test_the_ceiling_never_drops_below_the_absolute_cap() -> None:
    """A faster machine must not be handed a stricter test than the one that already existed."""
    import test_redos

    for baseline in (0.0, 0.001, 0.05, REFERENCE_BASELINE_MS):
        assert calibrated_ceiling_ms(baseline) >= test_redos.PER_LINE_BUDGET_MS


def test_a_slower_runner_is_given_more_room_not_less() -> None:
    """The relief the issue asks for, on the far side of the maximum where it actually bites."""
    healthy = REFERENCE_BASELINE_MS
    loaded = 3 * healthy
    assert calibrated_ceiling_ms(loaded) == pytest.approx(BASELINE_MULTIPLE * loaded)
    assert calibrated_ceiling_ms(loaded) > calibrated_ceiling_ms(healthy)


def test_the_baseline_pattern_clears_both_bounds(baseline_ms: float) -> None:
    """The pattern the scale is built from stays inside the ceiling it calibrates.

    This fails if the multiple is ever set so low that the cheapest line in the harness breaches it,
    which would make every other assertion in the module noise.
    """
    test_redos = _redos()
    measured = test_redos.worst_line_ms(re.compile(BASELINE_SOURCE), baseline_bait(test_redos))
    assert measured < test_redos.PER_LINE_BUDGET_MS
    assert measured < calibrated_ceiling_ms(baseline_ms)


def test_a_super_linear_pattern_breaches_the_calibrated_ceiling(baseline_ms: float) -> None:
    """The canary against the new bound.

    Both numbers in this comparison come from the same machine, which is what keeps the assertion
    honest as the machine changes: measured on an idle one, the canary needs about 270 ms against a
    0.087 ms baseline, so it costs roughly 3100 baseline units and `BASELINE_MULTIPLE` is 750. That
    is a factor of four of room before calibration would lift the ceiling past the canary, and this
    is the test that says so if it ever does.
    """
    test_redos = _redos()
    slowest = test_redos.worst_line_ms(
        re.compile(test_redos.CANARY_PATTERN), (test_redos.CANARY_BAIT,)
    )
    ceiling = calibrated_ceiling_ms(baseline_ms)
    assert slowest > ceiling, (
        f"the calibrated ceiling no longer notices {test_redos.CANARY_PATTERN}: "
        f"{slowest:.1f} ms against {ceiling:.1f} ms "
        f"(baseline {baseline_ms:.4f} ms, cap {test_redos.PER_LINE_BUDGET_MS:.1f} ms)"
    )
