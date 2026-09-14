"""Three things a second vertical could not describe or diagnose.

All three were reported from outside, by somebody writing a profile for a tool
this harness had never graded. Each is about the REPORT half of a profile: where
a referee keeps its lists, whether one spelling can cover every mode, and what
the harness says when there is no report to read.

Each test fails against the code it replaces; that was checked by reverting each
change and re-running rather than assumed.
"""
from __future__ import annotations

import pytest

from qa_orchestrator.compare import _checked, _declines, _findings_from_prose
from qa_orchestrator.referee import RegistrationError, ReportSchema, Tool, Verdict
from qa_orchestrator.scenario import CheckedExpectation, DeclinesExpectation, FindingsExpectation


def _tool(**over) -> Tool:
    fields = dict(
        name="probe", executable="probe", install_hint="pip install probe",
        modes=("presence", "regression"),
        capture_argv=lambda target, out: ["capture", target],
        judge_argv=lambda mode, configs, captures: [mode],
        json_argv=lambda mode: ("--json",),
    )
    fields.update(over)
    return Tool(**fields)


class TestFindingsAreReadLikeTheirSiblings:
    """`declines` and `checked` resolved a dotted path and `findings` did not,
    so a referee keeping its findings nested reported zero of them -- green."""

    def test_a_dotted_path_resolves(self):
        verdict = Verdict(
            exit_code=1, stdout="", stderr="",
            report={"checked": {"invariants_attempted": 12,
                                "findings_verbatim": [{"entity_id": "ST-03"}]}},
            schema=ReportSchema(findings="checked.findings_verbatim",
                                checked="checked.invariants_attempted"))
        assert verdict.findings() == [{"entity_id": "ST-03"}]
        assert verdict.checked() == 12

    def test_a_plain_key_still_resolves(self):
        """The control: every published profile names a top-level key."""
        verdict = Verdict(exit_code=1, stdout="", stderr="",
                          report={"findings": [{"name": "a"}]},
                          schema=ReportSchema())
        assert verdict.findings() == [{"name": "a"}]

    def test_a_path_that_reaches_something_that_is_not_a_list_is_not_a_finding(self):
        verdict = Verdict(exit_code=1, stdout="", stderr="",
                          report={"checked": {"findings_verbatim": 3}},
                          schema=ReportSchema(findings="checked.findings_verbatim"))
        assert verdict.findings() == []


class TestAToolWhoseKeysVaryByMode:
    """One `ReportSchema` covered every mode, so a tool naming its list
    differently per mode could not be described at all."""

    def test_a_callable_answers_per_mode(self):
        tool = _tool(report=lambda mode: ReportSchema(
            findings="changes" if mode == "regression" else "findings"))
        assert tool.report_for("presence").findings == "findings"
        assert tool.report_for("regression").findings == "changes"

    def test_a_plain_schema_still_answers_for_every_mode(self):
        tool = _tool(report=ReportSchema(findings="findings"))
        assert tool.report_for("presence").findings == "findings"
        assert tool.report_for("regression").findings == "findings"

    def test_a_callable_that_answers_the_wrong_thing_is_refused_at_registration(self):
        with pytest.raises(RegistrationError) as refused:
            _tool(report=lambda mode: {"findings": "changes"})
        assert "report(" in str(refused.value)

    def test_the_refusal_names_the_mode_it_asked_about(self):
        with pytest.raises(RegistrationError) as refused:
            _tool(report=lambda mode: None if mode == "regression" else ReportSchema())
        assert "regression" in str(refused.value)

    def test_a_tuple_is_still_refused(self):
        """Unchanged, and deliberately: a per-mode difference is a per-mode
        answer, not two keys tried in order."""
        with pytest.raises(RegistrationError):
            ReportSchema(findings=("findings", "changes"))


class TestWhyThereIsNoReport:
    """`report is None` had three causes and three messages asserted one."""

    def _verdict(self, unread):
        return Verdict(exit_code=1, stdout="some prose", stderr="",
                       report=None, schema=ReportSchema(declines="declines",
                                                        checked="checked"),
                       unread=unread)

    @pytest.mark.parametrize("unread", [
        "no json_argv for mode 'regression'",
        "the output would not parse (Extra data at line 2): '{...}\\nnotes'",
        "the output parsed to a list, not an object",
    ])
    def test_every_channel_names_the_cause_it_was_given(self, unread):
        verdict = self._verdict(unread)
        said = " ".join(
            m.actual for m in
            _declines(DeclinesExpectation(reason="r", names=(), not_names=()), verdict)
            + _checked(CheckedExpectation(exact=1), verdict))
        assert unread in said, said
        prose = _findings_from_prose(
            FindingsExpectation(text="absent", names=(), not_names=()), verdict)
        assert any(unread in m.where for m in prose), [m.where for m in prose]

    def test_no_channel_asserts_a_cause_it_was_not_told(self):
        verdict = self._verdict("the output would not parse (Extra data at line 2)")
        said = " ".join(
            m.actual + m.where for m in
            _declines(DeclinesExpectation(reason="r", names=(), not_names=()), verdict)
            + _checked(CheckedExpectation(exact=1), verdict))
        assert "prints no JSON" not in said and "printed none" not in said, said

    def test_a_verdict_carrying_no_reason_still_says_something(self):
        """Every Verdict built by this harness carries one; a hand-built one
        from a caller's own test does not, and must not print an empty clause."""
        verdict = self._verdict(None)
        got = _declines(DeclinesExpectation(reason="r", names=(), not_names=()),
                        verdict)[0].actual
        assert got.strip()
