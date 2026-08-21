"""Did the referee conclude what the scenario said it should?

Pure functions over a verdict and an expectation. No I/O, no subprocess, nothing
that needs a machine -- so the comparison logic is testable without any of the
apparatus, which is the half of a harness that usually cannot be tested at all.

**Every mismatch is reported, not the first.** Someone reading a failed scenario is
deciding whether the firmware regressed or the harness did, and revealing one
difference at a time costs a run each.
"""

from __future__ import annotations

from dataclasses import dataclass

from .referee import VERDICTS, Verdict
from .scenario import Expectation, FirmwareExpectation, Phase


@dataclass(frozen=True)
class Mismatch:
    where: str
    expected: str
    actual: str

    def __str__(self) -> str:
        return f"{self.where}: expected {self.expected}, got {self.actual}"


def compare_audit(expected: Expectation, verdict: Verdict) -> list[Mismatch]:
    """What the referee should have said, against what it said."""
    found: list[Mismatch] = []

    if expected.exit_code is not None and verdict.exit_code != expected.exit_code:
        found.append(Mismatch(
            "exit code",
            f"{expected.exit_code} ({_word(expected.exit_code)})",
            f"{verdict.exit_code} ({verdict.verdict})"))

    if expected.finding and expected.finding not in verdict.stdout:
        found.append(Mismatch(
            "finding", f"the report to contain {expected.finding!r}",
            "it did not"))

    # Names are matched against the lines carrying the finding, not against the
    # whole report.
    #
    # This started as a substring test over all of stdout and was wrong: every
    # declared sensor is listed in the coverage table above the findings, so
    # `names: [Inlet]` passed whether or not the engine had said anything about
    # Inlet. It asserted that a sensor exists, which was never in doubt.
    lines = _relevant_lines(verdict.stdout, expected.finding)
    for name in expected.names:
        if not any(name in line for line in lines):
            found.append(Mismatch(
                f"named sensor {name!r}",
                "to appear in the finding" if expected.finding else "to be named",
                "it did not"))
    for name in expected.not_names:
        offending = [line for line in lines if name in line]
        if offending:
            found.append(Mismatch(
                f"unnamed sensor {name!r}", "not to appear in the finding",
                offending[0].strip()[:110]))
    return found


def _relevant_lines(stdout: str, finding: str | None) -> list[str]:
    """The lines a name assertion is judged against: the finding's own block.

    With a `finding`, the region is each line carrying it **plus the header that
    owns it** -- the nearest less-indented line above. Without one, the whole
    report, which is the weaker claim and is what a scenario asked for by not
    narrowing it.

    The header matters because the tool reports coverage as a stanza:

        Fan1
            declared by AspeedFan in the configuration and not reported ...
            declared in configs/board.json

    The sensor's name is on the header line and the finding text is on the next,
    so a match confined to the finding line alone found no names at all -- and a
    `names:` assertion that could never hold is as useless as one that always
    does. Walking back stops at the nearest shallower line, so the block belongs
    to one sensor and a `not_names` check cannot be tripped by its neighbour.
    """
    if not finding:
        return stdout.splitlines()

    lines = stdout.splitlines()
    kept: list[str] = []
    for index, line in enumerate(lines):
        if finding not in line:
            continue
        indent = len(line) - len(line.lstrip())
        start = index
        for previous in range(index - 1, -1, -1):
            candidate = lines[previous]
            if not candidate.strip():
                continue
            if len(candidate) - len(candidate.lstrip()) < indent:
                start = previous
                break
        kept.extend(lines[start:index + 1])
    return kept


def compare_firmware(expected: FirmwareExpectation,
                     observed: dict[str, str]) -> list[Mismatch]:
    """What the MACHINE should look like, against what it looks like.

    Separate from the audit comparison so a scenario can tell a broken injector
    from a broken referee. If the fan is still there, the tool was right not to
    report it missing, and the harness is the thing at fault.
    """
    found: list[Mismatch] = []
    for sensor, want in sorted(expected.states.items()):
        got = observed.get(sensor, "unknown")
        if got != want:
            found.append(Mismatch(f"machine state of {sensor}", want, got))
    return found


def _word(code: int) -> str:
    """The one vocabulary, read from where the verdicts are defined.

    This was a second private mapping, and it had already drifted: it called
    exit 2 *could not complete* while `Verdict.verdict` called it *incomplete*,
    so a single mismatch line printed both names for the same number. Written
    twice, disagreeing immediately -- which is why it is read from one place now.
    """
    return VERDICTS.get(code, "unknown")


@dataclass(frozen=True)
class PhaseResult:
    phase: Phase
    verdict: Verdict | None
    mismatches: tuple[Mismatch, ...]
    observed: dict[str, str]

    @property
    def passed(self) -> bool:
        return not self.mismatches

    @property
    def asserted_anything(self) -> bool:
        """Whether this phase made a claim at all.

        A scenario of phases that assert nothing runs, reports success, and tests
        nothing. The runner counts these so a summary can say how much of the run
        was actually a check -- a green result over zero assertions is the shape
        this family exists to refuse.
        """
        return self.phase.expect is not None or self.phase.expect_firmware is not None
