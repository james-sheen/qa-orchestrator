"""Talk to the tool a scenario names. Through its published surfaces, and no other way.

**This module is the architecture.** The orchestrator injects faults and judges
whether the referee caught them, which means the referee is the thing under test
as much as the firmware is. A harness that reached into the referee's internals to
find out what it concluded would be grading the exam with the answer key: any
change that broke the tool's real output but left its internals intact would still
pass, and that is the one result this suite must never be able to produce.

So: the tool is invoked as a subprocess and read through exit codes, stdout, and
the JSON report. Nothing here imports `bmc_sensor_audit`. `test_boundary.py`
asserts that, by reading this file.

**Which tool is a `Tool` profile, not a literal.** The identity, the argv for each
question, the report's key names and the shape of the content handle come from the
profile a scenario names; the subprocess, the `0/1/2` reading and the artifact
judging stay here, because those must behave the same for every vertical.

If a scenario needs something the published surface does not carry, that is a
feature request against the tool -- not a reason to reach past it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Sequence

# The tool's documented CI interface, restated here because this program branches
# on it. `2` is could-not-complete and must never be read as clean.
EXIT_CLEAN, EXIT_REGRESSION, EXIT_INCOMPLETE = 0, 1, 2

VERDICTS = {EXIT_CLEAN: "clean", EXIT_REGRESSION: "regressions",
            EXIT_INCOMPLETE: "incomplete"}


class RefereeUnavailable(RuntimeError):
    """The tool is not installed. Distinct from any verdict it could return."""


def _flagged_judge(mode: str, configs: Sequence[str],
                   walks: Sequence[Path]) -> tuple[str, ...]:
    """`<mode> --config C ... --walk W ...` -- the built-in tool's judge form."""
    argv = [mode]
    for path in configs:
        argv += ["--config", str(path)]
    for walk in walks:
        argv += ["--walk", str(walk)]
    return tuple(argv)


@dataclass(frozen=True)
class Tool:
    """The program a scenario grades, described rather than assumed.

    **What is configurable here, and what deliberately is not.** A profile
    supplies the tool's identity, the argv for each of the three questions this
    module asks, and where a subject name sits in the JSON. It does not supply
    how any answer is read. Spawning the process, interpreting `0/1/2`, and
    judging the artifact stay in this module, because those are the parts that
    must behave identically for every vertical -- a profile that could reinterpret
    an exit code could make `2` read as clean, which is the one result this
    harness must never produce.

    The argv builders return the arguments AFTER the executable. They cannot
    choose the executable, so nothing registered here can run a different program
    from the one it named.
    """

    name: str
    executable: str
    install_hint: str
    modes: tuple[str, ...]
    capture_argv: Callable[[str, Path], Sequence[str]]
    validate_argv: Callable[[Path], Sequence[str]]
    judge_argv: Callable[[str, Sequence[str], Sequence[Path]], Sequence[str]]
    #: Arguments that make `mode` answer in JSON, or `None` where it cannot.
    json_argv: Callable[[str], Sequence[str] | None] | None = None
    #: Where the report keeps its findings, and where a finding keeps its subject.
    findings_key: str = "findings"
    subject_keys: tuple[str, ...] = ("name",)
    #: The content handle in `capture`'s output, matched as a SHAPE. Left here
    #: rather than fixed at `sha256:` because that is the built-in tool's format,
    #: not a property of the question. A tool that prints none returns no digest,
    #: which is why this was easy to miss: it degrades to `None` without failing.
    digest_pattern: str = r"\bsha256:[0-9a-f]{64}\b"


#: The tool this harness was built against.
BMC_SENSOR_AUDIT = Tool(
    name="bmc-sensor-audit",
    executable="bmc-sensor-audit",
    install_hint="pip install 'bmc-sensor-audit[detect]'",
    modes=("detect", "coverage"),
    capture_argv=lambda target, out: (
        "capture", "--target", target, "--out", str(out), "--print-digest"),
    validate_argv=lambda path: ("validate-walk", str(path)),
    judge_argv=_flagged_judge,
    json_argv=lambda mode: ("--json",) if mode == "coverage" else None,
    subject_keys=("name", "sensor"),
)

#: Referees registered at runtime, consulted before the built-in one.
#:
#: WHY THIS EXISTS. The substrate side of this harness became general and this
#: side did not: a vertical could supply its own backend and then had no way to
#: name the program being graded, because the executable was a string literal
#: here. A scenario could describe a paper vertical and could never run one.
_REGISTERED_TOOLS: Dict[str, Tool] = {}

_BUILTIN_TOOLS = (BMC_SENSOR_AUDIT.name,)


def register_tool(tool: Tool) -> None:
    """Make `referee: <tool.name>` in a scenario grade with `tool`.

    Refuses to shadow a built-in, for the reason the backend registry refuses:
    a run that reports the name it was given must have used it.
    """
    if tool.name in _BUILTIN_TOOLS:
        raise RefereeUnavailable(
            f"{tool.name!r} is a built-in referee and cannot be replaced by "
            f"registration; choose another name so a run naming it says what "
            f"graded it")
    _REGISTERED_TOOLS[tool.name] = tool


def known_tools() -> tuple[str, ...]:
    """Every referee a scenario may name. Asked, never copied."""
    return tuple(sorted(set(_BUILTIN_TOOLS) | set(_REGISTERED_TOOLS)))


def profile(name: str) -> Tool:
    """The profile for a referee by name, or raise with the known ones listed."""
    if name in _REGISTERED_TOOLS:
        return _REGISTERED_TOOLS[name]
    if name == BMC_SENSOR_AUDIT.name:
        return BMC_SENSOR_AUDIT
    extra = ", ".join(sorted(_REGISTERED_TOOLS)) or "(none)"
    raise RefereeUnavailable(
        f"unknown referee {name!r}; this build has "
        f"{', '.join(_BUILTIN_TOOLS)}, registered: {extra}")


@dataclass(frozen=True)
class Verdict:
    """One run of the referee, as the outside world can see it."""
    exit_code: int
    stdout: str
    stderr: str
    report: dict | None = None
    #: Copied from the profile that produced this verdict, so reading the report
    #: needs no second lookup and no assumption about whose report it is.
    findings_key: str = "findings"
    subject_keys: tuple[str, ...] = ("name", "sensor")

    @property
    def verdict(self) -> str:
        return VERDICTS.get(self.exit_code, f"unknown({self.exit_code})")

    @property
    def could_not_complete(self) -> bool:
        return self.exit_code == EXIT_INCOMPLETE

    def names_mentioned(self) -> set[str]:
        """Subject names the report names, from the JSON when there is one.

        Falls back to nothing rather than to a guess: a comparator that scraped
        names out of prose would drift the moment the prose was reworded, and
        would report a false match while doing it.
        """
        if not self.report:
            return set()
        found: set[str] = set()
        for finding in self.report.get(self.findings_key, []) or []:
            for key in self.subject_keys:
                name = finding.get(key)
                if name:
                    found.add(str(name))
                    break
        return found


def executable(tool: Tool = BMC_SENSOR_AUDIT) -> str:
    """The tool's console script, or raise. Never silently falls back."""
    found = shutil.which(tool.executable)
    if not found:
        raise RefereeUnavailable(
            f"{tool.executable} is not on PATH. Install it -- "
            f"{tool.install_hint} -- and re-run. This is "
            "reported rather than skipped: a scenario run without a referee "
            "has judged nothing, and must not be able to look like a pass.")
    return found


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


def capture(target: str, out: Path, *, tool: Tool = BMC_SENSOR_AUDIT,
            timeout: float = 60) -> Capture:
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
        [executable(tool), *tool.capture_argv(target, out)],
        capture_output=True, text=True, timeout=timeout)

    if not out.exists():
        raise RuntimeError(
            f"capture wrote no walk and exited {result.returncode}: "
            f"{(result.stderr or result.stdout).strip()[:400]}")

    problems = validate_walk(out, tool=tool, timeout=timeout)
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

    found = re.search(tool.digest_pattern, result.stdout)
    return Capture(path=out, complete=result.returncode == EXIT_CLEAN,
                   digest=found.group(0) if found else None)


def validate_walk(path: Path, *, tool: Tool = BMC_SENSOR_AUDIT,
                  timeout: float = 60) -> str | None:
    """`None` if the file is a well-formed walk, else what the tool said is wrong.

    A separate invocation rather than an inference from `capture`'s exit code,
    because they answer different questions: one is about the run, the other about
    the artifact. It needs no engine and no hardware -- that is the whole reason
    the tool ships it as a subcommand rather than keeping the rule in its own CI.
    """
    result = subprocess.run(
        [executable(tool), *tool.validate_argv(path)],
        capture_output=True, text=True, timeout=timeout)
    if result.returncode == EXIT_CLEAN:
        return None
    return (result.stderr or result.stdout).strip()[:400] or (
        f"validate-walk exited {result.returncode} and said nothing")


def judge(mode: str, config: tuple[str, ...], walks: list[Path], *,
          tool: Tool = BMC_SENSOR_AUDIT, timeout: float = 300) -> Verdict:
    """Run the referee over the walks taken so far, oldest first.

    Every walk is passed, not just the phase's own. Liveness reads a series, and
    a harness that fed it only the latest walk would be asking a different
    question from the one the tool was built to answer.

    The JSON report is fetched in a second invocation rather than parsed out of
    the human output. Two runs over identical inputs is the cost of not writing
    a scraper that silently stops matching when a heading is reworded.
    """
    base = [executable(tool), *tool.judge_argv(mode, config, walks)]

    human = subprocess.run(base, capture_output=True, text=True, timeout=timeout)

    report = None
    machine_argv = tool.json_argv(mode) if tool.json_argv else None
    if machine_argv:
        machine = subprocess.run(base + list(machine_argv), capture_output=True,
                                 text=True, timeout=timeout)
        try:
            report = json.loads(machine.stdout)
        except json.JSONDecodeError:
            report = None

    return Verdict(exit_code=human.returncode, stdout=human.stdout,
                   stderr=human.stderr, report=report,
                   findings_key=tool.findings_key,
                   subject_keys=tool.subject_keys)
