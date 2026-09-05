"""The comparator, in isolation: did the referee conclude what the scenario said?

Pure functions over a verdict and an expectation -- no I/O, no subprocess, no
substrate -- so the half of a harness that usually cannot be tested at all is.

**Two paths, and which one runs is not the comparator's choice.** A finding is
judged from the JSON report when there is one, and from prose only when the
profile declares no JSON form for the mode. The prose rules are the fiddly ones
and they are the reason `names:` means anything: a name has to appear in the
FINDING, not merely somewhere in a report that lists every declared subject.
"""

from __future__ import annotations

import pytest

from qa_orchestrator.compare import compare_referee, compare_substrate
from qa_orchestrator.referee import ReportSchema, Verdict
from qa_orchestrator.scenario import (FindingsExpectation, RefereeExpectation,
                                      SubstrateExpectation)

# A real report's shape: a coverage table naming every subject, then findings
# naming only some. The distinction the comparator has to respect.
PROSE = """\
Sensor coverage: capture_028.json

  declared              2
  matched               2

Liveness (Stage 2)
------------------
  fed to the engine        2

Findings -- 1
  Inlet: the reading has not changed across 16 of 28 observations in window
"""

SCHEMA = ReportSchema(findings="findings", subject=("sensor",), text=("detail",))


def prose_verdict(exit_code=1, stdout=PROSE):
    """No report: the profile declares no JSON for this mode, so prose is read."""
    return Verdict(exit_code=exit_code, stdout=stdout, stderr="")


def report_verdict(findings, exit_code=1):
    return Verdict(exit_code=exit_code, stdout="", stderr="",
                   report={"findings": list(findings)}, schema=SCHEMA)


def expect(text=None, names=(), not_names=(), exit_code=None):
    return RefereeExpectation(
        exit_code=exit_code,
        findings=FindingsExpectation(text=text, names=tuple(names),
                                     not_names=tuple(not_names)))


class TestTheExitCode:
    def test_a_match_is_silent(self):
        assert compare_referee(RefereeExpectation(exit_code=1), prose_verdict()) == []

    def test_a_mismatch_names_both_sides_in_words(self):
        found = compare_referee(RefereeExpectation(exit_code=0),
                                prose_verdict(exit_code=2))
        assert len(found) == 1
        assert "clean" in str(found[0]) and "incomplete" in str(found[0])

    def test_both_sides_of_a_mismatch_use_the_same_vocabulary(self):
        """They did not, at first: the expected side said *could not complete*
        and the actual side said *incomplete*, for the same number, on the same
        line. One mapping, read from where the verdicts are defined."""
        from qa_orchestrator.compare import _word
        from qa_orchestrator.referee import VERDICTS
        for code, word in VERDICTS.items():
            assert _word(code) == word


class TestNamesAreScopedToTheFindingInProse:
    def test_a_subject_named_in_the_finding_matches(self):
        assert compare_referee(expect("has not changed across", names=("Inlet",)),
                               prose_verdict()) == []

    def test_a_subject_only_in_the_coverage_table_does_not_match(self):
        """The defect this scoping fixes. `Outlet` appears in the report -- it is
        declared -- but the referee said nothing about it, and a harness that
        accepted that would report detection where there was none."""
        found = compare_referee(
            expect("has not changed across", names=("Outlet",)),
            prose_verdict(stdout=PROSE.replace("  declared              2",
                                               "  declared  2   Outlet")))
        assert len(found) == 1 and "Outlet" in str(found[0])

    def test_not_names_catches_a_subject_that_should_not_have_been_flagged(self):
        """Half the acceptance claim. Naming the frozen sensor is one thing;
        showing the control beside it was NOT named is what makes it evidence of
        detection rather than of a check that flags everything."""
        noisy = PROSE + "  Outlet: the reading has not changed across 16 of 28\n"
        found = compare_referee(
            expect("has not changed across", names=("Inlet",), not_names=("Outlet",)),
            prose_verdict(stdout=noisy))
        assert len(found) == 1 and "Outlet" in str(found[0])

    def test_not_names_is_silent_when_the_control_stayed_quiet(self):
        assert compare_referee(
            expect("has not changed across", names=("Inlet",), not_names=("Outlet",)),
            prose_verdict()) == []

    def test_a_name_on_the_header_line_above_the_finding_counts(self):
        """Reports come as stanzas: the subject on one line, the text indented
        under it. A match confined to the finding line found no names at all, so
        `names:` could never hold -- as useless as one that always holds."""
        stanza = ("Declared and not reported at all -- 1 (regression)\n"
                  "  Outlet\n"
                  "      declared by TMP75 in the configuration and not reported "
                  "by the machine at all\n"
                  "      declared in board.json\n")
        assert compare_referee(
            expect("not reported by the machine at all", names=("Outlet",)),
            prose_verdict(stdout=stanza)) == []

    def test_a_neighbouring_stanza_does_not_leak_into_the_block(self):
        """Walking back stops at the nearest shallower line, so a block belongs to
        one subject. Otherwise `not_names` trips on whichever neighbour is near."""
        two = ("Declared and not reported at all -- 1\n"
               "  Outlet\n"
               "      not reported by the machine at all\n"
               "  Inlet\n"
               "      reported and healthy\n")
        assert compare_referee(
            expect("not reported by the machine at all",
                   names=("Outlet",), not_names=("Inlet",)),
            prose_verdict(stdout=two)) == []

    def test_without_a_text_the_whole_report_is_searched(self):
        """The weaker claim, and the one a scenario asks for by not narrowing."""
        assert compare_referee(expect(names=("Inlet",)), prose_verdict()) == []

    def test_three_wrong_things_produce_three_mismatches(self):
        """Every mismatch, not the first: someone reading a failed scenario is
        deciding whether the subject regressed or the harness did, and revealing
        one difference at a time costs a run each."""
        found = compare_referee(
            RefereeExpectation(
                exit_code=0,
                findings=FindingsExpectation(text="no such text",
                                             names=("Nobody",))),
            prose_verdict())
        assert len(found) == 3, [str(m) for m in found]


class TestTheSameQuestionsAgainstTheReport:
    """The path that actually runs for a profile declaring JSON. The prose rules
    above cannot cover it: a report has no stanzas, no indentation and no header
    lines, and reading it was the change that made a wrongly-named text key
    silently unmatchable."""

    def test_a_finding_carrying_the_text_matches(self):
        v = report_verdict([{"sensor": "Inlet", "detail": "has not changed across"}])
        assert compare_referee(expect("has not changed", names=("Inlet",)), v) == []

    def test_a_subject_in_another_finding_does_not_satisfy_the_text(self):
        v = report_verdict([{"sensor": "Inlet", "detail": "has not changed"},
                            {"sensor": "Outlet", "detail": "something else"}])
        found = compare_referee(expect("has not changed", names=("Outlet",)), v)
        assert len(found) == 1 and "Outlet" in str(found[0])

    def test_not_names_catches_a_subject_in_the_matching_finding(self):
        v = report_verdict([{"sensor": "Inlet", "detail": "has not changed"},
                            {"sensor": "Outlet", "detail": "has not changed"}])
        found = compare_referee(
            expect("has not changed", names=("Inlet",), not_names=("Outlet",)), v)
        assert len(found) == 1 and "Outlet" in str(found[0])

    def test_a_text_key_the_report_does_not_use_matches_nothing(self):
        """The Phase 2 defect, pinned. The profile named `finding`/`message`; the
        referee emits `detail`. The comparator found the finding, read no words
        out of it, and reported the text as absent -- with every scenario still
        parsing and the suite still green."""
        wrong = ReportSchema(findings="findings", subject=("sensor",),
                             text=("finding", "message"))
        v = Verdict(exit_code=1, stdout="", stderr="",
                    report={"findings": [{"sensor": "Inlet", "detail": "has not changed"}]},
                    schema=wrong)
        found = compare_referee(expect("has not changed"), v)
        assert len(found) == 1


class TestTheSubstrateIsItsOwnClaim:
    def test_the_state_is_compared_to_what_was_observed(self):
        assert compare_substrate(SubstrateExpectation({"Inlet": "reading"}),
                                 {"Inlet": "reading"}) == []

    def test_an_entity_nobody_observed_is_a_mismatch_not_a_pass(self):
        found = compare_substrate(SubstrateExpectation({"Inlet": "absent"}), {})
        assert len(found) == 1 and "unobserved" in str(found[0])
