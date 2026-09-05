"""A vertical supplies its own substrate, verb AND referee, and runs -- from a file.

The referee here has positional arguments where the first vertical's tool takes
flags, keeps `issues` where it keeps `findings`, and reports what it did not
check. If any part of the seam were still hardcoded, one of these goes red --
and each has a negative beside it, so a comparator that stopped reading the
report could not pass by reading nothing.
"""

from __future__ import annotations

import dataclasses
import shutil

import pytest

from conftest import EXAMPLE
from qa_orchestrator import cli, referee, substrate
from qa_orchestrator.run import run
from qa_orchestrator.scenario import ScenarioError, load, parse
from qa_orchestrator.vocabulary import SubstrateUnavailable

WITHDRAWN = EXAMPLE / "withdrawn.yaml"


class TestItRunsEndToEnd:
    def test_every_phase_holds(self, paper, tmp_path):
        result = run(load(WITHDRAWN), workdir=tmp_path / "work")
        assert result.error is None, result.error
        assert [p.passed for p in result.phases] == [True, True, True, True]
        assert result.captures_taken == 4
        assert result.exit_code() == 0

    def test_the_evidence_says_validated_and_carries_the_profiles_handle(self, paper, tmp_path):
        result = run(load(WITHDRAWN), workdir=tmp_path / "work")
        for line in result.evidence():
            assert "validated" in line and "UNVALIDATED" not in line
            assert "proposal-" in line, line
        assert all(c.digest and c.digest.startswith("proposal-") for c in result.captures)

    def test_the_run_names_the_referee_and_where_it_found_it(self, paper, tmp_path):
        said: list[str] = []
        result = run(load(WITHDRAWN), workdir=tmp_path / "work", on_event=said.append)
        assert result.referee_path and result.referee_path.endswith("proposal-review")
        assert any(m.startswith("referee: proposal-review at ") for m in said), said

    def test_values_are_not_coerced(self, paper, tmp_path):
        """The proposal's values are sentences. A harness that cast them would fail here."""
        scenario = load(WITHDRAWN)
        assert isinstance(scenario.setup["entities"][0]["value"], str)
        result = run(scenario, workdir=tmp_path / "work")
        assert result.error is None, result.error


class TestNonVacuity:
    """Each claim above must be able to fail. These make one part wrong at a time."""

    def test_the_report_schema_is_load_bearing(self, paper, tmp_path):
        """A profile whose findings key is wrong must go red on `names`, not pass by reading prose."""
        broken = dataclasses.replace(
            paper.PROPOSAL_REVIEW,
            report=dataclasses.replace(paper.PROPOSAL_REVIEW.report, findings="nonsense"))
        referee.unregister_tool(broken.name)
        referee.register_tool(broken)
        result = run(load(WITHDRAWN), workdir=tmp_path / "work")
        assert result.error is None, result.error
        second = result.phases[1]
        assert not second.passed
        assert any("named subject 'R-3.2'" in str(m) for m in second.mismatches), second.mismatches

    def test_a_wrong_decline_reason_is_a_mismatch(self, paper, tmp_path):
        text = WITHDRAWN.read_text().replace("reason: no_answer", "reason: never_seen")
        result = run(parse(text, source=WITHDRAWN), workdir=tmp_path / "work")
        assert result.error is None, result.error
        third = result.phases[2]
        assert not third.passed
        assert any(m.where == "declines" for m in third.mismatches), third.mismatches

    def test_a_wrong_denominator_is_a_mismatch(self, paper, tmp_path):
        text = WITHDRAWN.read_text().replace("checked: 3", "checked: 2")
        result = run(parse(text, source=WITHDRAWN), workdir=tmp_path / "work")
        first = result.phases[0]
        assert not first.passed
        assert any(m.where == "checked" for m in first.mismatches), first.mismatches

    def test_a_missing_handle_is_said_not_swallowed(self, paper, tmp_path):
        """A declared shape the tool never prints must be visible in the evidence."""
        broken = dataclasses.replace(paper.PROPOSAL_REVIEW, digest_pattern=r"\bsha256:[0-9a-f]{64}\b")
        referee.unregister_tool(broken.name)
        referee.register_tool(broken)
        said: list[str] = []
        result = run(load(WITHDRAWN), workdir=tmp_path / "work", on_event=said.append)
        assert result.error is None, result.error
        assert all(c.digest is None and c.digest_missing for c in result.captures)
        assert all("MISSING" in line for line in result.evidence())
        assert any("printed no handle matching" in m for m in said)

    def test_nothing_in_this_run_needs_any_other_program(self, paper, tmp_path, monkeypatch):
        """Only the referee the scenario names may be found on PATH."""
        real = shutil.which
        monkeypatch.setattr(shutil, "which",
                            lambda name, *a, **k: real(name, *a, **k)
                            if name == "proposal-review" else None)
        result = run(load(WITHDRAWN), workdir=tmp_path / "work")
        assert result.error is None, result.error
        assert result.exit_code() == 0


class TestTheVerbTheVerticalBrought:
    def test_it_is_validated_at_parse_time_with_the_phase_named(self, paper):
        text = WITHDRAWN.read_text().replace(
            "{contradict: {entity: R-9.0, with: R-7.1}}", "{contradict: {entity: R-9.0}}")
        with pytest.raises(ScenarioError, match=r"phase 4: contradict needs"):
            parse(text, source=WITHDRAWN)

    def test_it_refuses_a_tier_that_cannot_do_it(self, paper, tmp_path):
        """`memory` has no `contradict`; the verb must say so, not no-op."""
        text = WITHDRAWN.read_text().replace("substrate: paper", "substrate: memory")
        result = run(parse(text, source=WITHDRAWN), workdir=tmp_path / "work")
        assert result.error is not None and "cannot make one requirement contradict" in result.error
        assert result.exit_code() == 2

    def test_an_unknown_verb_lists_what_this_build_has(self, paper):
        text = WITHDRAWN.read_text().replace("{remove: R-3.2}", "{withdraw: R-3.2}")
        with pytest.raises(ScenarioError, match=r"unknown action 'withdraw'.*contradict"):
            parse(text, source=WITHDRAWN)


class TestTheSubstrateSeam:
    def test_a_tier_speaking_outside_presence_ends_the_run_as_incomplete(self, paper, tmp_path):
        """*expected absent, got gone* would read as an injection that did not take."""
        class Gone(paper.PaperSubstrate):
            name = "gone"

            def state(self, entity: str) -> str:
                return "gone"

        substrate.register("gone", Gone)
        try:
            text = WITHDRAWN.read_text().replace("substrate: paper", "substrate: gone")
            result = run(parse(text, source=WITHDRAWN), workdir=tmp_path / "work")
        finally:
            substrate.unregister("gone")
        assert result.error is not None
        assert "must return one of absent, disabled, reading" in result.error
        assert result.exit_code() == 2

    def test_observe_refuses_directly(self):
        class Bad:
            name = "bad"

            def state(self, entity: str):
                return None

        with pytest.raises(SubstrateUnavailable, match="must return one of"):
            substrate.observe(Bad(), "x")


class TestTheCommandLineReachesARegistration:
    """The door `register` opens, from the entrance a pipeline actually uses."""

    def _unload(self):
        import sys
        loaded = sys.modules.pop("qa_orchestrator_plugin_vertical", None)
        if loaded is not None:
            loaded.unregister()

    def test_check_refuses_without_the_plugin_and_passes_with_it(self, paper_on_path, capsys):
        assert cli.main(["--no-entry-points", "check", str(WITHDRAWN)]) == 2
        assert "substrate is 'paper'" in capsys.readouterr().err
        try:
            assert cli.main(["--no-entry-points", "--plugin", str(EXAMPLE / "vertical.py"),
                             "check", str(WITHDRAWN)]) == 0
            out = capsys.readouterr().out
            assert "substrate paper, referee proposal-review/review" in out
        finally:
            self._unload()

    def test_run_reports_the_referee_in_its_header(self, paper_on_path, capsys, tmp_path):
        try:
            code = cli.main(["--no-entry-points", "--plugin", str(EXAMPLE / "vertical.py"),
                             "run", str(WITHDRAWN), "--workdir", str(tmp_path / "work")])
        finally:
            self._unload()
        out = capsys.readouterr().out
        assert code == 0, out
        assert "referee: proposal-review" in out.splitlines()[0]
        assert "graded by proposal-review at" in out

    def test_a_broken_plugin_is_exit_2_not_a_skip(self, tmp_path, capsys):
        broken = tmp_path / "broken.py"
        broken.write_text("def register():\n    raise ValueError('no')\n")
        assert cli.main(["--no-entry-points", "--plugin", str(broken), "list"]) == 2
        assert "failed while registering" in capsys.readouterr().err

    def test_list_says_what_this_process_can_name(self, paper_on_path, capsys):
        try:
            assert cli.main(["--no-entry-points", "--plugin", str(EXAMPLE / "vertical.py"),
                             "list"]) == 0
        finally:
            self._unload()
        out = capsys.readouterr().out
        assert "substrates: memory, paper" in out
        assert "contradict" in out and "proposal-review" in out
