"""The comparator, exercised in both directions.

Pure functions over a verdict and an expectation, so all of this runs with no
machine, no subprocess and no referee installed -- which matters, because the
comparison is the half of a harness that usually cannot be tested at all.

**The load-bearing case is `names` scoped to the finding.** It started as a
substring test over the whole report and was wrong: every declared sensor appears
in the coverage table above the findings, so `names: [Inlet]` passed whether or
not the engine had said anything about Inlet. It asserted that a sensor exists,
which was never in doubt.
"""

from __future__ import annotations

import pytest

from qa_orchestrator.compare import compare_audit, compare_firmware
from qa_orchestrator.referee import Verdict
from qa_orchestrator.scenario import Expectation, FirmwareExpectation

# The shape of a real report: a coverage table naming every sensor, then findings
# naming only some. The distinction the comparator has to respect.
REPORT = """\
Sensor coverage: walk_028.json

  declared              2
  matched               2

Liveness (Stage 2)
------------------
  fed to the engine        2

Findings -- 1
  Inlet: the reading has not changed across 16 of 28 observations in window
"""


def verdict(exit_code=1, stdout=REPORT):
    return Verdict(exit_code=exit_code, stdout=stdout, stderr="")


class TestTheExitCode:
    def test_a_match_is_silent(self):
        assert compare_audit(Expectation(exit_code=1), verdict()) == []

    def test_a_mismatch_names_both_sides_in_words(self):
        found = compare_audit(Expectation(exit_code=0), verdict(exit_code=2))
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


class TestNamesAreScopedToTheFinding:
    def test_a_sensor_named_in_the_finding_matches(self):
        expectation = Expectation(finding="has not changed across", names=("Inlet",))
        assert compare_audit(expectation, verdict()) == []

    def test_a_sensor_present_only_in_the_coverage_table_does_not_match(self):
        """The defect this scoping fixes. `Outlet` appears in the report -- it is
        a declared sensor -- but the engine said nothing about it, and a harness
        that accepted that would report detection where there was none."""
        expectation = Expectation(finding="has not changed across", names=("Outlet",))
        found = compare_audit(expectation, verdict(
            stdout=REPORT.replace("  declared              2",
                                  "  declared  2   Outlet")))
        assert len(found) == 1
        assert "Outlet" in str(found[0])

    def test_not_names_catches_a_sensor_the_engine_should_not_have_flagged(self):
        """Half the acceptance claim. Naming the frozen sensor is one thing;
        showing the control beside it was NOT named is what makes it evidence of
        detection rather than of a check that flags everything."""
        noisy = REPORT + "  Outlet: the reading has not changed across 16 of 28\n"
        expectation = Expectation(finding="has not changed across",
                                  names=("Inlet",), not_names=("Outlet",))
        found = compare_audit(expectation, verdict(stdout=noisy))
        assert len(found) == 1
        assert "Outlet" in str(found[0])

    def test_not_names_is_silent_when_the_control_stayed_quiet(self):
        expectation = Expectation(finding="has not changed across",
                                  names=("Inlet",), not_names=("Outlet",))
        assert compare_audit(expectation, verdict()) == []

    def test_a_name_on_the_header_line_above_the_finding_counts(self):
        """The tool reports coverage as a stanza: the sensor's name on one line,
        the finding text indented under it. A match confined to the finding line
        found no names at all, so `names:` could never hold on any coverage
        scenario -- as useless as one that always holds."""
        stanza = ("Declared and not reported at all -- 1 (regression)\n"
                  "  Outlet\n"
                  "      declared by TMP75 in the configuration and not reported "
                  "by the machine at all\n"
                  "      declared in board.json\n")
        expectation = Expectation(finding="not reported by the machine at all",
                                  names=("Outlet",))
        assert compare_audit(expectation, verdict(stdout=stanza)) == []

    def test_a_neighbouring_stanza_does_not_leak_into_the_block(self):
        """Walking back stops at the nearest shallower line, so a block belongs to
        one sensor. Otherwise `not_names` would trip on whichever sensor happened
        to be reported just above."""
        two = ("  Outlet\n"
               "      declared by TMP75 and not reported by the machine at all\n"
               "  Inlet\n"
               "      declared by TMP75 and not reported by the machine at all\n")
        expectation = Expectation(finding="not reported by the machine at all",
                                  names=("Outlet", "Inlet"))
        assert compare_audit(expectation, verdict(stdout=two)) == []

        only_one = ("  Outlet\n"
                    "      declared by TMP75 and not reported by the machine at all\n"
                    "  Inlet\n"
                    "      reading 21.0\n")
        strict = Expectation(finding="not reported by the machine at all",
                             names=("Outlet",), not_names=("Inlet",))
        assert compare_audit(strict, verdict(stdout=only_one)) == []

    def test_without_a_finding_the_whole_report_is_searched(self):
        """The weaker claim, which is what a scenario asks for by not narrowing."""
        assert compare_audit(Expectation(names=("Inlet",)), verdict()) == []


class TestEveryMismatchIsReported:
    def test_three_wrong_things_produce_three_mismatches(self):
        """Someone reading a failure is deciding whether the firmware regressed or
        the harness did. Revealing one difference at a time costs a run each."""
        expectation = Expectation(exit_code=0, finding="absent", names=("Fan1",))
        found = compare_audit(expectation, verdict())
        assert len(found) == 3


class TestFirmwareIsComparedSeparately:
    def test_the_machine_state_is_its_own_claim(self):
        """*The fan is gone* and *the tool noticed* are different facts. A harness
        that could only express the second could never tell a broken injector from
        a broken referee."""
        found = compare_firmware(FirmwareExpectation(states={"Fan1": "absent"}),
                                 {"Fan1": "reading"})
        assert len(found) == 1
        assert "Fan1" in str(found[0])

    def test_a_sensor_nobody_observed_is_a_mismatch_not_a_pass(self):
        found = compare_firmware(FirmwareExpectation(states={"Fan1": "absent"}), {})
        assert len(found) == 1
        assert "unknown" in str(found[0])


@pytest.mark.parametrize("code,word", [(0, "clean"), (1, "regressions"),
                                       (2, "incomplete")])
def test_the_verdict_vocabulary_matches_the_tools(code, word):
    """The same three words at every layer. A fourth vocabulary here would be one
    more thing for a pipeline to get wrong."""
    assert Verdict(exit_code=code, stdout="", stderr="").verdict == word
