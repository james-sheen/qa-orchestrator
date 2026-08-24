"""Talk to the audit tool. Through its published surfaces, and no other way.

**This module is the architecture.** The orchestrator injects faults and judges
whether the referee caught them, which means the referee is the thing under test
as much as the firmware is. A harness that reached into the referee's internals to
find out what it concluded would be grading the exam with the answer key: any
change that broke the tool's real output but left its internals intact would still
pass, and that is the one result this suite must never be able to produce.

So: the tool is invoked as a subprocess and read through exit codes, stdout, and
the JSON report. Nothing here imports `bmc_sensor_audit`. `test_boundary.py`
asserts that, by reading this file.

If a scenario needs something the published surface does not carry, that is a
feature request against the tool -- not a reason to reach past it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# The tool's documented CI interface, restated here because this program branches
# on it. `2` is could-not-complete and must never be read as clean.
EXIT_CLEAN, EXIT_REGRESSION, EXIT_INCOMPLETE = 0, 1, 2

VERDICTS = {EXIT_CLEAN: "clean", EXIT_REGRESSION: "regressions",
            EXIT_INCOMPLETE: "incomplete"}


class RefereeUnavailable(RuntimeError):
    """The tool is not installed. Distinct from any verdict it could return."""


@dataclass(frozen=True)
class Verdict:
    """One run of the referee, as the outside world can see it."""
    exit_code: int
    stdout: str
    stderr: str
    report: dict | None = None

    @property
    def verdict(self) -> str:
        return VERDICTS.get(self.exit_code, f"unknown({self.exit_code})")

    @property
    def could_not_complete(self) -> bool:
        return self.exit_code == EXIT_INCOMPLETE

    def names_mentioned(self) -> set[str]:
        """Sensor names the report names, from the JSON when there is one.

        Falls back to nothing rather than to a guess: a comparator that scraped
        names out of prose would drift the moment the prose was reworded, and
        would report a false match while doing it.
        """
        if not self.report:
            return set()
        found: set[str] = set()
        for finding in self.report.get("findings", []) or []:
            name = finding.get("name") or finding.get("sensor")
            if name:
                found.add(str(name))
        return found


def executable() -> str:
    """The tool's console script, or raise. Never silently falls back."""
    found = shutil.which("bmc-sensor-audit")
    if not found:
        raise RefereeUnavailable(
            "bmc-sensor-audit is not on PATH. Install it -- "
            "pip install 'bmc-sensor-audit[detect]' -- and re-run. This is "
            "reported rather than skipped: a scenario run without a referee "
            "has judged nothing, and must not be able to look like a pass.")
    return found


#: The tool's content handle for a capture: `sha256:` and 64 hex characters.
#: Matched as a SHAPE rather than by the label beside it -- a heading can be
#: reworded and a scraper keyed on one stops matching in silence, which is the
#: reason `judge` below asks for JSON twice rather than parsing prose.
_DIGEST = re.compile(r"\bsha256:[0-9a-f]{64}\b")


@dataclass(frozen=True)
class Capture:
    """One walk, and whether the machine answered for all of it.

    `complete` is False for a walk the tool wrote anyway because a partial
    capture is still evidence -- it records WHICH subtree failed. That is a
    different fact from a capture that could not be made at all, and the two
    used to be one exit code here.
    """

    path: Path
    complete: bool
    digest: str | None = None


def capture(target: str, out: Path, *, timeout: float = 60) -> Capture:
    """Record one walk. The tool's own `capture` subcommand, no substitute.

    **The exit code cannot answer the question this function asks, and reading it
    as though it could disabled a documented feature.** `capture` returns `2` both
    when it could not reach the machine and when it reached the machine and one
    subtree answered with an error -- and the second is a walk the tool
    deliberately writes and keeps, because knowing which subtree failed is the
    point. Raising on any non-zero made the scenario schema's `fail` action --
    *make a subtree answer with an HTTP status (a partial walk)* -- abort the run
    before the referee could be asked anything. Measured: no shipped scenario used
    it and no test exercised it, so it had never once worked.

    So the FILE is judged instead of the exit code. `validate-walk` says whether
    what was written is a well-formed `walk/1`, which is a question about the
    artifact rather than about the run, and the walk's own error list says whether
    the machine answered for all of it. A capture that produced no readable walk
    is still a failure and still raises.
    """
    result = subprocess.run(
        [executable(), "capture", "--target", target, "--out", str(out),
         "--print-digest"],
        capture_output=True, text=True, timeout=timeout)

    if not out.exists():
        raise RuntimeError(
            f"capture wrote no walk and exited {result.returncode}: "
            f"{(result.stderr or result.stdout).strip()[:400]}")

    problems = validate_walk(out, timeout=timeout)
    if problems is not None:
        raise RuntimeError(
            f"capture exited {result.returncode} and wrote a file the tool's own "
            f"validator refuses, so nothing here can be judged from it: {problems}")

    if result.returncode not in (EXIT_CLEAN, EXIT_INCOMPLETE):
        # A code outside the documented interface is not a partial walk. Same rule
        # the pipeline applies to a `127` from a missing command: unrecognised
        # reads as could-not-complete, with the raw code kept beside it.
        raise RuntimeError(
            f"capture exited {result.returncode}, which is outside the tool's "
            f"documented 0/1/2 interface: "
            f"{(result.stderr or result.stdout).strip()[:400]}")

    found = _DIGEST.search(result.stdout)
    return Capture(path=out, complete=result.returncode == EXIT_CLEAN,
                   digest=found.group(0) if found else None)


def validate_walk(path: Path, *, timeout: float = 60) -> str | None:
    """`None` if the file is a well-formed walk, else what the tool said is wrong.

    A separate invocation rather than an inference from `capture`'s exit code,
    because they answer different questions: one is about the run, the other about
    the artifact. It needs no engine and no hardware -- that is the whole reason
    the tool ships it as a subcommand rather than keeping the rule in its own CI.
    """
    result = subprocess.run(
        [executable(), "validate-walk", str(path)],
        capture_output=True, text=True, timeout=timeout)
    if result.returncode == EXIT_CLEAN:
        return None
    return (result.stderr or result.stdout).strip()[:400] or (
        f"validate-walk exited {result.returncode} and said nothing")


def judge(mode: str, config: tuple[str, ...], walks: list[Path], *,
          timeout: float = 300) -> Verdict:
    """Run the referee over the walks taken so far, oldest first.

    Every walk is passed, not just the phase's own. Liveness reads a series, and
    a harness that fed it only the latest walk would be asking a different
    question from the one the tool was built to answer.

    The JSON report is fetched in a second invocation rather than parsed out of
    the human output. Two runs over identical inputs is the cost of not writing
    a scraper that silently stops matching when a heading is reworded.
    """
    base = [executable(), mode]
    for path in config:
        base += ["--config", str(path)]
    for walk in walks:
        base += ["--walk", str(walk)]

    human = subprocess.run(base, capture_output=True, text=True, timeout=timeout)

    report = None
    if mode == "coverage":
        machine = subprocess.run(base + ["--json"], capture_output=True,
                                 text=True, timeout=timeout)
        try:
            report = json.loads(machine.stdout)
        except json.JSONDecodeError:
            report = None

    return Verdict(exit_code=human.returncode, stdout=human.stdout,
                   stderr=human.stderr, report=report)
