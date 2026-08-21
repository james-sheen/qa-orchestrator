"""The scenario format refuses what it cannot run.

Every test here plants a scenario that is wrong in one specific way and asserts it
is refused with the phase named. A parser that accepted these would produce a run
that executed, reported clean, and tested nothing -- which is indistinguishable
from a real pass at the exit code, and is the whole failure this family exists to
make impossible.
"""

from __future__ import annotations

import pytest

from qa_orchestrator.scenario import ScenarioError, drive_series, parse

MINIMAL = """
format: qa-scenario/1
backend: mock
config: board.json
phases:
  - walks: 1
    expect: {audit: {exit: 0}}
"""


def test_a_minimal_scenario_parses():
    scenario = parse(MINIMAL)
    assert scenario.backend == "mock"
    assert scenario.total_walks == 1
    assert scenario.phases[0].expect.exit_code == 0


class TestTheVersionIsChecked:
    def test_a_missing_format_is_refused(self):
        with pytest.raises(ScenarioError, match="format"):
            parse(MINIMAL.replace("format: qa-scenario/1\n", ""))

    def test_a_future_format_is_refused_rather_than_guessed(self):
        """Three programs read this file. A build that guessed at a version it
        does not know would run a scenario meaning something else."""
        with pytest.raises(ScenarioError, match="qa-scenario/1"):
            parse(MINIMAL.replace("qa-scenario/1", "qa-scenario/2"))


class TestRefusalsThatWouldOtherwiseRunAndTestNothing:
    def test_a_phase_with_no_walks_is_refused(self):
        with pytest.raises(ScenarioError, match="gathers no evidence"):
            parse(MINIMAL.replace("walks: 1", "walks: 0"))

    def test_an_empty_expect_audit_is_refused(self):
        """It would assert nothing while looking like an assertion, which is the
        most expensive kind of green."""
        with pytest.raises(ScenarioError, match="assert nothing"):
            parse(MINIMAL.replace("expect: {audit: {exit: 0}}", "expect: {audit: {}}"))

    def test_an_unknown_action_is_refused_rather_than_skipped(self):
        """A phase that silently did nothing would leave every phase after it
        judging an unperturbed machine, and passing for it."""
        broken = MINIMAL.replace("  - walks: 1",
                                 "  - walks: 1\n    action: {vaporise: fan3}")
        with pytest.raises(ScenarioError, match="unknown action"):
            parse(broken)

    def test_two_actions_in_one_phase_are_refused(self):
        """A moved verdict could not be attributed to either."""
        broken = MINIMAL.replace(
            "  - walks: 1", "  - walks: 1\n    action: {remove: a, disable: b}")
        with pytest.raises(ScenarioError, match="exactly one verb"):
            parse(broken)

    def test_a_typo_in_expect_is_refused_not_ignored(self):
        """`exit_code` instead of `exit` would otherwise be dropped, leaving a
        phase that asserts nothing and says nothing about it."""
        broken = MINIMAL.replace("{audit: {exit: 0}}", "{audit: {exit_code: 0}}")
        with pytest.raises(ScenarioError, match="unknown key"):
            parse(broken)

    def test_a_sensor_in_both_names_and_not_names_is_refused(self):
        broken = MINIMAL.replace(
            "{audit: {exit: 0}}",
            "{audit: {exit: 1, names: [Inlet], not_names: [Inlet]}}")
        with pytest.raises(ScenarioError, match="cannot both hold"):
            parse(broken)


class TestDriveSupplesEnoughValues:
    def test_too_few_values_for_the_walk_count_is_refused(self):
        """The remaining walks would repeat a reading and look frozen when
        nothing froze them -- a scenario that manufactures its own finding."""
        broken = MINIMAL.replace(
            "  - walks: 1",
            "  - walks: 4\n    action: {drive: {sensor: Inlet, values: [1, 2]}}")
        with pytest.raises(ScenarioError, match="look frozen"):
            parse(broken)

    def test_the_check_reaches_every_sensor_in_the_general_form(self):
        broken = MINIMAL.replace(
            "  - walks: 1",
            "  - walks: 3\n    action: {drive: {sensors: {A: [1,2,3], B: [1]}}}")
        with pytest.raises(ScenarioError, match="B"):
            parse(broken)

    def test_both_spellings_normalise_to_the_same_thing(self):
        """One reader for both, so the sugar cannot drift from the general form."""
        assert (drive_series({"sensor": "Inlet", "values": [1, 2]})
                == drive_series({"sensors": {"Inlet": [1, 2]}})
                == {"Inlet": [1, 2]})


class TestFirmwareExpectations:
    def test_an_unknown_state_is_refused(self):
        broken = MINIMAL.replace("{audit: {exit: 0}}",
                                 "{firmware: {Inlet: melted}}")
        with pytest.raises(ScenarioError, match="expected absent, disabled or reading"):
            parse(broken)

    def test_a_firmware_block_naming_no_sensor_is_refused(self):
        broken = MINIMAL.replace("{audit: {exit: 0}}",
                                 "{firmware: {within_walks: 2}}")
        with pytest.raises(ScenarioError, match="names no sensor"):
            parse(broken)
