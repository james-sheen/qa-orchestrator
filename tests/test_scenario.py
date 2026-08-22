"""The scenario format refuses what it cannot run.

Every test here plants a scenario that is wrong in one specific way and asserts it
is refused with the phase named. A parser that accepted these would produce a run
that executed, reported clean, and tested nothing -- which is indistinguishable
from a real pass at the exit code, and is the whole failure this family exists to
make impossible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qa_orchestrator import scenario
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


class TestAScenarioIsPortable:
    """A scenario names its config relative to itself, not to whoever ran it.

    Resolving against the working directory made every shipped scenario runnable
    only from the repository root. Anywhere else the referee could not find the
    board, returned exit 2, and all four expectations in the file mismatched at
    once -- so the output read as *the tool disagrees with all of this* rather
    than *nobody found the config*.

    It surfaced from the pipeline repository's end-to-end test, which runs the
    scenarios from a temporary workspace the way CI does. Nothing in this
    repository's own suite could see it: every test here already ran from the
    root.
    """

    def _scenario(self, tmp_path, config_line):
        board = tmp_path / "fixtures" / "board.json"
        board.parent.mkdir(parents=True, exist_ok=True)
        board.write_text('{"Name": "B", "Exposes": []}')
        path = tmp_path / "scenarios" / "s.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "format: qa-scenario/1\nname: s\nbackend: mock\n"
            f"config: {config_line}\n"
            "machine: {sensors: [{name: A}]}\n"
            "phases:\n  - walks: 1\n")
        return path, board

    def test_a_relative_config_resolves_beside_the_scenario(self, tmp_path):
        path, board = self._scenario(tmp_path, "../fixtures/board.json")
        assert scenario.load(path).config == (str(board.resolve()),)

    def test_the_result_does_not_depend_on_the_working_directory(self, tmp_path,
                                                                 monkeypatch):
        path, board = self._scenario(tmp_path, "../fixtures/board.json")
        monkeypatch.chdir(tmp_path)
        from_here = scenario.load(path).config
        monkeypatch.chdir("/")
        assert scenario.load(path).config == from_here

    def test_an_absolute_config_is_left_alone(self, tmp_path):
        absolute = tmp_path / "fixtures" / "board.json"
        path, _ = self._scenario(tmp_path, str(absolute))
        assert scenario.load(path).config == (str(absolute),)

    def test_parsing_a_string_with_no_source_leaves_the_path_as_written(self):
        parsed = scenario.parse(
            "format: qa-scenario/1\nname: s\nbackend: mock\n"
            "config: fixtures/board.json\n"
            "machine: {sensors: [{name: A}]}\nphases:\n  - walks: 1\n")
        assert parsed.config == ("fixtures/board.json",)

    def test_every_shipped_scenario_names_its_config_relative_to_itself(self):
        """The shipped files, not a fixture. A scenario carrying a path that
        starts with `scenarios/` is one written against the old rule."""
        root = Path(__file__).resolve().parent.parent / "scenarios"
        for path in sorted(root.glob("*.yaml")):
            for line in path.read_text().splitlines():
                if line.startswith("config:"):
                    named = line.split(":", 1)[1].strip()
                    assert not named.startswith("scenarios/"), (
                        f"{path.name} names {named!r}, which only resolves from "
                        f"the repository root")
                    assert (path.parent / named).exists(), (
                        f"{path.name} names {named!r}, which does not exist "
                        f"beside it")

    def test_the_readme_example_is_written_against_the_same_rule(self):
        """The fix above landed in the loader and in the shipped files, and the
        README kept the old form for a while afterwards -- which is the copy a
        reader starts from. Fixing every instance the tests could see is not the
        same as fixing the class."""
        readme = Path(__file__).resolve().parent.parent / "README.md"
        shown = [line for line in readme.read_text().splitlines()
                 if line.startswith("config:")]
        assert shown, (
            "the README no longer shows a `config:` line, so this check has lost "
            "its subject and would pass by finding nothing")
        for line in shown:
            named = line.split(":", 1)[1].split("#", 1)[0].strip()
            assert not named.startswith("scenarios/"), (
                f"the README shows {named!r}; copied into a scenario file that "
                f"resolves to scenarios/scenarios/, and it is the first thing a "
                f"reader copies")
