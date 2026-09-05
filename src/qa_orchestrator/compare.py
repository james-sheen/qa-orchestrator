"""Decide whether a verdict was the right one. Pure functions, no subprocess.

Everything here takes what the referee said and what the scenario expected, and
returns mismatches. Nothing here needs a substrate or a referee, so the
comparison logic is testable without either -- and the comparison logic is what
decides whether the referee regressed or the harness did.

**The report is the evidence, when there is one.** `names` and `not_names` are
judged against the findings in the JSON report, read through the profile's
`ReportSchema`. Only when the profile declares no JSON form for the mode is the
prose read instead, and every mismatch produced that way says `(stdout)` -- so a
reader knows the judgement rests on wording that may be reworded.
"""

from __future__ import annotations

from dataclasses import dataclass

from .referee import Verdict, first_present
from .scenario import (CheckedExpectation, DeclinesExpectation, FindingsExpectation,
                       Phase, RefereeExpectation, SubstrateExpectation)


@dataclass(frozen=True)
class Mismatch:
    where: str
    expected: str
    actual: str

    def __str__(self) -> str:
        return f"{self.where}: expected {self.expected}, got {self.actual}"


def _word(code: int) -> str:
    return {0: "clean", 1: "regressions", 2: "incomplete"}.get(code, "unrecognised")


# -- findings, from the report -------------------------------------------------

def _findings_from_report(expected: FindingsExpectation, verdict: Verdict) -> list[Mismatch]:
    found: list[Mismatch] = []
    schema = verdict.schema
    findings = verdict.findings()
    if expected.text is not None:
        relevant = [f for f in findings
                    if any(expected.text in str(f.get(k, "")) for k in schema.text)]
        if not relevant:
            found.append(Mismatch(
                "finding", f"a finding whose text contains {expected.text!r}",
                f"none among {len(findings)} finding(s) in the report"))
    else:
        relevant = findings
    subjects = {first_present(f, schema.subject) for f in relevant} - {None}
    scope = "the finding carrying that text" if expected.text else "the report's findings"
    for name in expected.names:
        if name not in subjects:
            found.append(Mismatch(f"named subject {name!r}", f"to appear in {scope}",
                                  f"it did not ({', '.join(sorted(subjects)) or 'nothing named'})"))
    for name in expected.not_names:
        if name in subjects:
            found.append(Mismatch(f"unnamed subject {name!r}", f"not to appear in {scope}",
                                  "it did"))
    return found


# -- findings, from prose (only when the profile has no JSON for this mode) ----

def _relevant_lines(stdout: str, text: str | None) -> list[str]:
    """The lines a name assertion is judged against: the finding's own block.

    With a `text`, the region is each line carrying it PLUS the header that owns
    it -- the nearest less-indented line above -- because a tool that reports as
    a stanza puts the subject on the header and the wording beneath. Without
    one, the whole output, which is the weaker claim.
    """
    if not text:
        return stdout.splitlines()
    lines = stdout.splitlines()
    kept: list[str] = []
    for index, line in enumerate(lines):
        if text not in line:
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


def _findings_from_prose(expected: FindingsExpectation, verdict: Verdict) -> list[Mismatch]:
    found: list[Mismatch] = []
    tag = "(stdout; this referee prints no JSON for this mode)"
    if expected.text is not None and expected.text not in verdict.stdout:
        found.append(Mismatch(f"finding {tag}", f"the output to contain {expected.text!r}",
                              "it did not"))
    lines = _relevant_lines(verdict.stdout, expected.text)
    for name in expected.names:
        if not any(name in line for line in lines):
            found.append(Mismatch(f"named subject {name!r} {tag}",
                                  "to appear in the finding" if expected.text else "to be named",
                                  "it did not"))
    for name in expected.not_names:
        offending = [line for line in lines if name in line]
        if offending:
            found.append(Mismatch(f"unnamed subject {name!r} {tag}",
                                  "not to appear in the finding", offending[0].strip()[:110]))
    return found


# -- declines and the denominator ----------------------------------------------

def _declines(expected: DeclinesExpectation, verdict: Verdict) -> list[Mismatch]:
    if verdict.report is None:
        return [Mismatch("declines", "a JSON report to read them from",
                         "the referee printed none this run")]
    schema = verdict.schema
    declines = verdict.declines()
    if expected.reason is not None:
        relevant = [d for d in declines
                    if first_present(d, schema.decline_reason) == expected.reason]
        if not relevant:
            reasons = sorted({first_present(d, schema.decline_reason) or "?" for d in declines})
            return [Mismatch("declines", f"a decline with reason {expected.reason!r}",
                             f"none; reasons reported: {', '.join(reasons) or '(no declines)'}")]
    else:
        relevant = declines
    subjects = {first_present(d, schema.decline_subject) for d in relevant} - {None}
    found: list[Mismatch] = []
    for name in expected.names:
        if name not in subjects:
            found.append(Mismatch(f"declined subject {name!r}", "to be among the declines",
                                  f"it was not ({', '.join(sorted(subjects)) or 'none'})"))
    for name in expected.not_names:
        if name in subjects:
            found.append(Mismatch(f"undeclined subject {name!r}",
                                  "not to be among the declines", "it was"))
    return found


def _checked(expected: CheckedExpectation, verdict: Verdict) -> list[Mismatch]:
    got = verdict.checked()
    if got is None:
        return [Mismatch("checked", "the report to carry a denominator",
                         "it did not (or the referee printed no JSON)")]
    found: list[Mismatch] = []
    if expected.exact is not None and got != expected.exact:
        found.append(Mismatch("checked", f"exactly {expected.exact}", str(got)))
    if expected.at_least is not None and got < expected.at_least:
        found.append(Mismatch("checked", f"at least {expected.at_least}", str(got)))
    return found


# -- the two comparisons -------------------------------------------------------

def compare_referee(expected: RefereeExpectation, verdict: Verdict) -> list[Mismatch]:
    """What the referee should have said, against what it said."""
    found: list[Mismatch] = []
    if expected.exit_code is not None and verdict.exit_code != expected.exit_code:
        found.append(Mismatch("exit code",
                              f"{expected.exit_code} ({_word(expected.exit_code)})",
                              f"{verdict.exit_code} ({verdict.verdict})"))
    if expected.findings is not None:
        if verdict.report is not None:
            found += _findings_from_report(expected.findings, verdict)
        else:
            found += _findings_from_prose(expected.findings, verdict)
    if expected.declines is not None:
        found += _declines(expected.declines, verdict)
    if expected.checked is not None:
        found += _checked(expected.checked, verdict)
    return found


def compare_substrate(expected: SubstrateExpectation,
                      observed: dict[str, str]) -> list[Mismatch]:
    """What the SUBSTRATE should look like, against what it looks like.

    Separate from the referee comparison so a scenario can tell a broken
    injector from a broken referee. If the entity is still there, the referee
    was right not to report it missing, and the harness is the thing at fault.
    """
    found: list[Mismatch] = []
    for entity, want in sorted(expected.states.items()):
        got = observed.get(entity, "unobserved")
        if got != want:
            found.append(Mismatch(f"substrate state of {entity}", want, got))
    return found


@dataclass
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
        return self.phase.asserts_anything
