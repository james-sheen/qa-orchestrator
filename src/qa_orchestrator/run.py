"""Run a scenario: perturb, walk, judge, compare.

Walks accumulate across phases and every walk taken so far is handed to the
referee at each evaluation, oldest first. That is not an optimisation to avoid --
liveness reads a *series*, and a harness that passed only the newest walk would be
asking a different question from the one the tool was built to answer, then
reporting the answer as if it were the same.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import referee
from .backends import BackendUnavailable, build
from .compare import Mismatch, PhaseResult, compare_audit, compare_firmware
from .scenario import Scenario, drive_series

EXIT_CLEAN, EXIT_MISMATCH, EXIT_INCOMPLETE = 0, 1, 2


@dataclass
class RunResult:
    scenario: Scenario
    phases: list[PhaseResult]
    walks_taken: int
    error: str | None = None
    #: One entry per walk, in order. Carries each walk's content handle and
    #: whether the machine answered for all of it.
    captures: tuple = ()

    def evidence(self) -> list[str]:
        """One line per walk: its content handle, and whether it was complete.

        **A clean run deletes its workdir**, so on the run that most needs no
        further explanation the walks are gone. The handles survive it. They are
        the tool's own -- `sha256:` over the file's bytes -- so anyone who kept a
        walk can match it with `sha256sum` and no tooling at all, and a walk that
        cannot be matched is not the walk that was judged.
        """
        lines = []
        for index, taken in enumerate(self.captures, start=1):
            state = "complete" if taken.complete else "PARTIAL"
            lines.append(f"walk {index:03d}  {state:8}  "
                         f"{taken.digest or '(no handle printed)'}")
        return lines

    @property
    def mismatches(self) -> list[Mismatch]:
        return [m for p in self.phases for m in p.mismatches]

    @property
    def assertions(self) -> int:
        return sum(1 for p in self.phases if p.asserted_anything)

    def exit_code(self) -> int:
        """`2` when the run could not be completed, `1` when a verdict disagreed.

        The same three-valued contract the referee uses, for the same reason: a
        harness that could not run must not report as a harness that found
        nothing wrong. Could-not-complete outranks disagreement, because a run
        that stopped early has not evaluated the phases it never reached.
        """
        if self.error is not None:
            return EXIT_INCOMPLETE
        return EXIT_MISMATCH if self.mismatches else EXIT_CLEAN


def run(scenario: Scenario, *, workdir: Path | None = None,
        on_event=None) -> RunResult:
    """Execute a scenario. Never raises for a scenario-level failure -- reports it."""
    say = on_event or (lambda _message: None)
    # mkdtemp, not TemporaryDirectory. The latter registers a finaliser that
    # removes the directory when the object is collected or the process exits --
    # so skipping `.cleanup()` to keep the walks after a failure kept nothing,
    # while the run cheerfully printed the path they were kept in. The directory
    # was gone before anyone could look. Removal is explicit below instead.
    owned = workdir is None
    if owned:
        workdir = Path(tempfile.mkdtemp(prefix="qa-orchestrator-"))
    workdir.mkdir(parents=True, exist_ok=True)

    phases: list[PhaseResult] = []
    walks: list[Path] = []
    captures: list[referee.Capture] = []
    backend = None
    error = None

    try:
        backend = build(scenario.backend, scenario.machine)
        url = backend.start()
        say(f"{scenario.backend} backend up at {url}")

        for phase in scenario.phases:
            say(phase.describe())

            driven: dict[str, list] = {}
            if phase.action is not None:
                verb, payload = phase.action
                if verb == "remove":
                    backend.remove(str(payload))
                elif verb == "disable":
                    backend.disable(str(payload))
                elif verb == "fail":
                    backend.fail(str(payload["path"]), int(payload["status"]))
                elif verb == "drift":
                    backend.set_reading(str(payload["sensor"]), float(payload["to"]))
                elif verb == "drive":
                    driven = drive_series(payload)

            for index in range(phase.walks):
                for sensor, values in driven.items():
                    backend.set_reading(sensor, float(values[index]))
                # Re-read the URL each time: an injection rebuilds the server, so
                # the port moves. Capturing against a stale URL would fail in a
                # way that reads like an unreachable BMC.
                target = backend.start()
                taken = referee.capture(
                    target, workdir / f"walk_{len(walks) + 1:03d}.json")
                walks.append(taken.path)
                captures.append(taken)
                if not taken.complete:
                    # Said out loud, because a partial walk changes what every
                    # verdict below it can mean: the referee withholds absence
                    # findings on one, so a phase that expected a sensor to be
                    # reported missing will not see it reported at all.
                    say(f"  walk {len(walks)} is PARTIAL -- the machine did not "
                        f"answer for all of it")

            observed: dict[str, str] = {}
            if phase.expect_firmware is not None:
                for sensor in phase.expect_firmware.states:
                    observed[sensor] = backend.state(sensor)

            verdict = None
            mismatches: list[Mismatch] = []
            if phase.expect is not None:
                verdict = referee.judge(scenario.mode, scenario.config, walks)
                mismatches += compare_audit(phase.expect, verdict)
            if phase.expect_firmware is not None:
                mismatches += compare_firmware(phase.expect_firmware, observed)

            result = PhaseResult(phase=phase, verdict=verdict,
                                 mismatches=tuple(mismatches), observed=observed)
            phases.append(result)
            if result.asserted_anything:
                say("  " + ("ok" if result.passed
                            else "MISMATCH: " + "; ".join(str(m) for m in mismatches)))

    except (BackendUnavailable, referee.RefereeUnavailable) as unavailable:
        error = str(unavailable)
    except Exception as unexpected:                              # noqa: BLE001
        error = f"{type(unexpected).__name__}: {unexpected}"
    finally:
        if backend is not None:
            try:
                backend.stop()
            except Exception:                                    # noqa: BLE001
                pass

    result = RunResult(scenario=scenario, phases=phases,
                       walks_taken=len(walks), error=error,
                       captures=tuple(captures))
    if owned:
        if result.exit_code() == EXIT_CLEAN:
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            # The walks ARE still here. Checked by a test, because the previous
            # version of this line was a true-sounding sentence about a directory
            # that had already been deleted.
            say(f"walks kept for inspection in {workdir}")
    return result
