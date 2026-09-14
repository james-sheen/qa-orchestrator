"""Run a scenario: perturb, capture, judge, compare.

Captures accumulate across phases and every capture taken so far is handed to
the referee at each judgement, oldest first. A referee that reads a series is
asked the question it was built to answer; a profile for one that judges a
snapshot takes the last capture and ignores the rest.

Nothing in this module knows which verbs, tiers or referees exist. It asks.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import actions, referee
from .compare import Mismatch, PhaseResult, compare_referee, compare_substrate
from .scenario import Scenario
from .substrate import build, observe
from .vocabulary import HarnessError

EXIT_CLEAN, EXIT_MISMATCH, EXIT_INCOMPLETE = 0, 1, 2


@dataclass
class RunResult:
    scenario: Scenario
    phases: list[PhaseResult]
    captures_taken: int
    error: str | None = None
    #: One entry per capture, in order.
    captures: tuple[referee.Capture, ...] = ()
    #: The program that graded this run, resolved on PATH -- the thing a reader
    #: wants when the wrong binary answered.
    referee_path: str | None = None

    def evidence(self) -> list[str]:
        """One line per capture: complete or partial, validated or not, and its handle.

        A clean run deletes its workdir, so on the run that most needs no
        further explanation the captures are gone. The handles survive it, in
        whatever shape the profile declared. A profile that declares none says
        `no handle`; one that declared a shape the tool did not print says
        `handle missing` -- the two are different facts.
        """
        lines = []
        for index, taken in enumerate(self.captures, start=1):
            state = "complete" if taken.complete else "PARTIAL"
            checked = "validated" if taken.validated else "UNVALIDATED"
            if taken.digest:
                handle = taken.digest
            elif taken.digest_missing:
                handle = "handle MISSING (the profile declared a shape; nothing matched)"
            else:
                handle = "(no handle; the profile declares none)"
            lines.append(f"capture {index:03d}  {state:8}  {checked:11}  {handle}")
        return lines

    @property
    def mismatches(self) -> list[Mismatch]:
        return [m for p in self.phases for m in p.mismatches]

    @property
    def assertions(self) -> int:
        return sum(1 for p in self.phases if p.asserted_anything)

    @property
    def one_handle_for_every_capture(self) -> str | None:
        """The handle every capture shared, when a whole series produced one.

        A run that observed a substrate it was perturbing, and got back the same
        bytes every time, has evidence of nothing that happened between the
        first capture and the last. It came up on a real BMC: twenty-eight
        captures, one handle, `sha256:850793ab...` twenty-eight times, and the
        evidence table listed all of them as validated without remarking on it.
        The handle was already being computed for every capture; nothing
        compared any two of them.

        **Reported, not graded, and the reason is a real case rather than
        caution.** A referee whose capture is deterministic -- the example
        vertical's is, it hashes the snapshot and nothing else -- returns the
        same handle for two captures of a substrate that did not change, which
        is correct and common. Failing on that would fire at a scenario for
        being honest. The grade for the case that found this is already right:
        the referee said it could not complete, and `exit_code` reads that.

        One capture is not a series, and a profile that declares no handle has
        nothing to compare, so both answer None.
        """
        handles = [capture.digest for capture in self.captures]
        if len(handles) > 1 and all(handles) and len(set(handles)) == 1:
            return handles[0]
        return None

    @property
    def unjudged(self) -> tuple[PhaseResult, ...]:
        """Phases where the referee said it could not complete and the
        expectations then failed.

        Not every could-not-complete verdict belongs here. A phase that EXPECTED
        `2` and got it has no mismatch at all, which is how a scenario asserting
        the referee's honesty about a partial capture stays clean.
        """
        return tuple(phase for phase in self.phases
                     if phase.mismatches and phase.verdict is not None
                     and phase.verdict.could_not_complete)

    def exit_code(self) -> int:
        """`2` when the run could not be completed, `1` when a verdict disagreed.

        Could-not-complete outranks disagreement, because a run that stopped
        early has not evaluated the phases it never reached.

        **A referee that reported could-not-complete is the same fact.** Its `2`
        means it had nothing to judge; calling the resulting failure a
        disagreement claims the substrate was read and answered wrongly, which
        is a claim about the machine nobody made. Found by running a scenario
        against a real BMC this harness cannot authenticate to: twenty-eight
        captures reached zero of everything, the referee answered `2` every
        time, and the run reported three disagreements and exited `1`.
        `Verdict.could_not_complete` was written for this question and nothing
        had ever asked it.
        """
        if self.error is not None:
            return EXIT_INCOMPLETE
        if not self.mismatches:
            return EXIT_CLEAN
        return EXIT_INCOMPLETE if self.unjudged else EXIT_MISMATCH


def run(scenario: Scenario, *, workdir: Path | None = None, on_event=None) -> RunResult:
    """Execute a scenario. Never raises for a scenario-level failure -- reports it."""
    say = on_event or (lambda _message: None)
    owned = workdir is None
    if owned:
        workdir = Path(tempfile.mkdtemp(prefix="qa-orchestrator-"))
    workdir.mkdir(parents=True, exist_ok=True)

    phases: list[PhaseResult] = []
    taken_paths: list[Path] = []
    captures: list[referee.Capture] = []
    substrate = None
    referee_path = None
    error = None

    try:
        # The referee first, before any substrate is touched: a run that cannot
        # be graded should not perturb anything.
        tool = referee.profile(scenario.referee)
        referee_path = referee.executable(tool)
        say(f"referee: {tool.name} at {referee_path}  (mode {scenario.mode})")

        substrate = build(scenario.substrate, scenario.setup)
        handle = substrate.start()
        say(f"substrate: {scenario.substrate} up at {handle}")

        for phase in scenario.phases:
            say(phase.describe())

            verb = payload = None
            if phase.action is not None:
                name, payload = phase.action
                verb = actions.resolve(name, f"phase {phase.index}")
                if verb.apply is not None:
                    verb.apply(substrate, payload)

            for index in range(phase.captures):
                if verb is not None and verb.per_capture is not None:
                    verb.per_capture(substrate, payload, index)
                # Re-read the handle each time: an injection may rebuild
                # whatever serves it, and a stale handle fails in a way that
                # reads like an unreachable substrate.
                target = substrate.start()
                number = len(taken_paths) + 1
                got = referee.capture(target, workdir / f"capture_{number:03d}.json", tool=tool)
                taken_paths.append(got.path)
                captures.append(got)
                if not got.complete:
                    say(f"  capture {number} is PARTIAL -- the substrate did not answer "
                        f"for all of it")
                if got.digest_missing:
                    say(f"  capture {number}: {tool.name} printed no handle matching "
                        f"{tool.digest_pattern!r}")

            observed: dict[str, str] = {}
            if phase.expect_substrate is not None:
                for entity in phase.expect_substrate.states:
                    observed[entity] = observe(substrate, entity)

            verdict = None
            mismatches: list[Mismatch] = []
            if phase.expect_referee is not None:
                verdict = referee.judge(scenario.mode, scenario.config, taken_paths, tool=tool)
                mismatches += compare_referee(phase.expect_referee, verdict)
            if phase.expect_substrate is not None:
                mismatches += compare_substrate(phase.expect_substrate, observed)

            result = PhaseResult(phase=phase, verdict=verdict,
                                 mismatches=tuple(mismatches), observed=observed)
            phases.append(result)
            if result.asserted_anything:
                say("  " + ("ok" if result.passed
                            else "MISMATCH: " + "; ".join(str(m) for m in mismatches)))

    except HarnessError as unavailable:
        error = str(unavailable)
    except Exception as unexpected:                              # noqa: BLE001
        error = f"{type(unexpected).__name__}: {unexpected}"
    finally:
        if substrate is not None:
            try:
                substrate.stop()
            except Exception:                                    # noqa: BLE001
                pass

    result = RunResult(scenario=scenario, phases=phases, captures_taken=len(taken_paths),
                       error=error, captures=tuple(captures), referee_path=referee_path)
    if owned:
        if result.exit_code() == EXIT_CLEAN:
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            say(f"captures kept for inspection in {workdir}")
    return result
