"""A referee that could not complete has not disagreed with anything.

**The defect this file was written for.** A scenario was pointed at a real BMC
and the harness could not authenticate to it -- there is nowhere in the scenario
format to put a credential or a TLS option. So all twenty-eight captures reached
zero of everything, the referee answered `2` to every judgement, and this
orchestrator reported *3 mismatch(es)* and exited `1`.

`1` is *a verdict disagreed*. Nothing had disagreed: the referee said it had
nothing to judge, and a `1` tells a reader the substrate was read and answered
wrongly -- a claim about the machine that nobody made. It is the same shape as
the finding the referee and the certificate renderer were both fixed for, one
layer up, in the harness that grades them.

The information was already there. `Verdict.could_not_complete` existed for
exactly this question and no code had ever asked it.

**The line is the mismatch, not the partiality.** A phase that EXPECTS `2` and
gets it produces no mismatch at all, so the shipped scenario asserting the
referee's honesty about a partial capture is untouched -- and that is the second
test below, which is the one that would go red if this rule were written as
*any partial capture makes a run incomplete*.
"""

from __future__ import annotations

from conftest import EXAMPLE
from qa_orchestrator import cli
from qa_orchestrator.run import run
from qa_orchestrator.scenario import parse

WITHDRAWN = EXAMPLE / "withdrawn.yaml"

HEAD = """format: qa-scenario/2
name: a region stops answering
substrate: paper
referee: proposal-review
mode: review
config: rules.json

setup:
  entities:
    - {name: R-3.2, value: "the pump shall stop within 2 s of a level alarm"}
    - {name: R-7.1, value: "the pump shall restart within 5 s"}
    - {name: R-9.0, value: "manual restart shall be possible at any time"}

phases:
"""

#: The referee answers 2 here: its record carries errors, so it judges nothing.
UNREADABLE = """  - note: the section stops answering, so the record is partial
    action: {fail: {region: /proposal/section-3, status: 500}}
    expect:
      referee: {exit: %d}
"""

#: A real disagreement: a declared requirement is gone and the referee says so.
WITHDRAWN_PHASE = """  - note: R-3.2 is withdrawn, which the referee reports as a finding
    action: {remove: R-3.2}
    expect:
      referee: {exit: %d}
"""


def _run(text, tmp_path):
    return run(parse(HEAD + text, source=WITHDRAWN), workdir=tmp_path / "work")


class TestTheGrade:
    def test_a_referee_that_could_not_complete_is_not_a_disagreement(self, paper, tmp_path):
        """The case from the BMC: expectations fail because nothing was judged."""
        result = _run(UNREADABLE % 0, tmp_path)
        assert result.error is None, result.error
        assert result.mismatches, "the phase should have failed its expectation"
        assert result.phases[0].verdict.could_not_complete
        assert result.exit_code() == 2

    def test_a_phase_that_expected_could_not_complete_is_still_clean(self, paper, tmp_path):
        """The partial-capture scenario, which this rule must not break.

        Written as the negative of the test above and on the same substrate
        state: the only thing that differs is what the scenario asked for.
        """
        result = _run(UNREADABLE % 2, tmp_path)
        assert not result.mismatches
        assert result.phases[0].verdict.could_not_complete
        assert result.exit_code() == 0

    def test_an_ordinary_disagreement_is_still_one(self, paper, tmp_path):
        """The rule must not swallow the code the harness exists to report."""
        result = _run(WITHDRAWN_PHASE % 0, tmp_path)
        assert result.mismatches
        assert not result.phases[0].verdict.could_not_complete
        assert result.exit_code() == 1

    def test_could_not_complete_outranks_a_disagreement(self, paper, tmp_path):
        """Both in one run, and `2` is the statement about the denominator."""
        result = _run(WITHDRAWN_PHASE % 0 + UNREADABLE % 0, tmp_path)
        assert result.exit_code() == 2
        assert [p.phase.index for p in result.unjudged] == [2]


class TestWhatTheCallerIsTold:
    """Through the door a pipeline actually uses."""

    def _unload(self):
        import sys
        loaded = sys.modules.pop("qa_orchestrator_plugin_vertical", None)
        if loaded is not None:
            loaded.unregister()

    def _cli(self, tmp_path):
        scenario = tmp_path / "unreadable.yaml"
        scenario.write_text(HEAD + UNREADABLE % 0)
        # The config is named relative to the scenario, so it has to travel.
        (tmp_path / "rules.json").write_text((EXAMPLE / "rules.json").read_text())
        try:
            return cli.main(["--no-entry-points", "--plugin",
                             str(EXAMPLE / "vertical.py"), "run", str(scenario)])
        finally:
            self._unload()

    def test_it_returns_what_the_result_says(self, paper_on_path, tmp_path, capsys):
        """This branch returned 1 outright while `exit_code` decided otherwise.

        Two places deciding one thing, and only one of them reached the caller --
        so the rule could land in `exit_code` and change nothing a pipeline sees.
        """
        assert self._cli(tmp_path) == 2, capsys.readouterr().err

    def test_it_says_why_rather_than_leaving_the_reader_to_infer(self, paper_on_path,
                                                                 tmp_path, capsys):
        """A list of mismatches above an exit 2 is a reader's puzzle otherwise."""
        self._cli(tmp_path)
        said = capsys.readouterr().err
        assert "could not complete on phase(s) 1" in said
        assert "nothing to judge" in said
