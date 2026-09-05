"""The first vertical's scenarios reach their verdicts, not merely parse.

`test_scenario_compat.py` asserts that the three `qa-scenario/1` files LOAD into
the objects they should. That is a claim about the reader, and it stayed green
through a migration in which all three had stopped passing: the profile named
`finding`/`message` as the report's text keys and the referee emits `detail`, so
the comparator found each finding and read no words out of it.

Parsing green is not running green, and only one of those is the thing the files
are for. These runs need the referee, so they skip where it is absent -- which is
every machine that has not installed the first vertical's extra, and none of CI's
`checks` job.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from conftest import SCENARIOS

TOOL = "qa-orchestrator"
REFEREE = "bmc-sensor-audit"

SHIPPED = sorted(SCENARIOS.glob("*.yaml"))

pytestmark = pytest.mark.skipif(
    shutil.which(REFEREE) is None or shutil.which(TOOL) is None,
    reason=f"needs {REFEREE} and {TOOL} on PATH; install the bmc extra to run these")


def test_there_are_scenarios_to_run():
    """Non-vacuity. A parametrisation over an empty glob is a file full of
    nothing that reports as a clean pass, and the directory just moved."""
    assert SHIPPED, f"no scenarios under {SCENARIOS}"


@pytest.mark.parametrize("scenario", SHIPPED, ids=lambda p: p.stem)
def test_it_reaches_its_expected_verdict(scenario):
    """Exit 0: every expectation in the file held.

    Through the console script rather than an import, because that is what a
    consumer runs and what the packaging has to get right.
    """
    result = subprocess.run([TOOL, "run", str(scenario)],
                            capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, (
        f"{scenario.name} exited {result.returncode}\n"
        + result.stdout + result.stderr)
