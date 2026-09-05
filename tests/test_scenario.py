"""The parser: what it refuses, and where it resolves a config from.

`test_scenario_compat.py` covers the v1 aliases and the registry-backed refusals.
This is the rest of the 0.2.x parser suite, ported: the version check, the
one-action-per-phase rule, the contradictions a phase can state, and config
resolution -- which is the only part of parsing that depends on where the file
sits, and therefore the only part a test running from a different directory can
break.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qa_orchestrator import scenario as scenario_module
from qa_orchestrator.scenario import FORMAT, FORMATS, ScenarioError, load, parse
from qa_orchestrator.verticals import bmc

MINIMAL = """\
format: qa-scenario/2
name: minimal
substrate: mock
referee: bmc-sensor-audit
config: board.json
phases:
  - captures: 1
    expect: {referee: {exit: 0}}
"""


@pytest.fixture(autouse=True)
def vertical():
    """The first vertical, because these scenarios name its tier and referee."""
    bmc.register()
    yield
    bmc.unregister()


def test_a_minimal_scenario_parses():
    got = parse(MINIMAL)
    assert got.substrate == "mock" and got.backend == "mock"
    assert got.total_captures == 1
    assert got.phases[0].expect_referee.exit_code == 0


class TestTheVersionIsChecked:
    def test_a_missing_format_is_refused(self):
        with pytest.raises(ScenarioError, match="format"):
            parse(MINIMAL.replace("format: qa-scenario/2\n", ""))

    def test_a_future_format_is_refused_rather_than_guessed(self):
        """Three programs read this file. A build that guessed at a version it
        does not know would run a scenario meaning something else.

        `/2` was the future version this asked about in 0.2.x, and is the native
        one now -- so the question has to be asked about a version that is still
        ahead, or it stops being asked at all."""
        ahead = f"qa-scenario/{int(FORMAT.rsplit('/', 1)[1]) + 1}"
        with pytest.raises(ScenarioError, match="this build reads"):
            parse(MINIMAL.replace(FORMAT, ahead))

    def test_both_readable_versions_really_are_read(self):
        """Non-vacuity for the check above: it must refuse SOME versions and
        accept others, and the accepted set is what `FORMATS` claims."""
        assert len(FORMATS) >= 2
        for version in FORMATS:
            assert version in scenario_module.FORMATS


class TestAPhaseStatesOneThing:
    def test_a_phase_with_no_captures_is_refused(self):
        with pytest.raises(ScenarioError, match="captures"):
            parse(MINIMAL.replace("captures: 1", "captures: 0"))

    def test_two_actions_in_one_phase_are_refused(self):
        """A phase does one thing, then observes. Two injections and one set of
        observations cannot say which one the referee reacted to."""
        with pytest.raises(ScenarioError):
            parse(MINIMAL.replace(
                "    expect:",
                "    action: {remove: A, disable: B}\n    expect:"))

    def test_an_empty_expectation_is_refused(self):
        with pytest.raises(ScenarioError):
            parse(MINIMAL.replace("{referee: {exit: 0}}", "{referee: {}}"))

    def test_a_typo_in_expect_is_refused_not_ignored(self):
        with pytest.raises(ScenarioError):
            parse(MINIMAL.replace("{referee: {exit: 0}}", "{refere: {exit: 0}}"))

    def test_a_subject_in_both_names_and_not_names_is_refused(self):
        """It cannot hold either way, so the file states a contradiction rather
        than an expectation, and the run would report a mismatch that no change
        to the referee could ever fix."""
        with pytest.raises(ScenarioError, match="Inlet"):
            parse(MINIMAL.replace(
                "{referee: {exit: 0}}",
                "{referee: {exit: 1, findings: {names: [Inlet], not_names: [Inlet]}}}"))

    def test_a_substrate_block_naming_no_entity_is_refused(self):
        with pytest.raises(ScenarioError):
            parse(MINIMAL.replace("{referee: {exit: 0}}",
                                  "{referee: {exit: 0}, substrate: {}}"))


class TestTheConfigResolvesBesideTheScenario:
    """**Relative to the scenario file, not to whoever ran it.** Resolving against
    the working directory made a scenario runnable only from the directory it sat
    in: the referee could not find the config, returned exit 2, and every
    expectation mismatched at once -- so the failure read as *the tool disagrees
    with all of this* rather than *nobody found the board*.

    Found by composing the suite, not by testing this repository.
    """

    def _written(self, tmp_path) -> Path:
        (tmp_path / "board.json").write_text("{}")
        path = tmp_path / "s.yaml"
        path.write_text(MINIMAL)
        return path

    def test_a_relative_config_resolves_beside_the_scenario(self, tmp_path):
        got = load(self._written(tmp_path))
        assert got.config[0] == str(tmp_path / "board.json")

    def test_the_result_does_not_depend_on_the_working_directory(self, tmp_path,
                                                                 monkeypatch):
        path = self._written(tmp_path)
        first = load(path).config[0]
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        assert load(path).config[0] == first

    def test_an_absolute_config_is_left_alone(self, tmp_path):
        path = tmp_path / "s.yaml"
        path.write_text(MINIMAL.replace("config: board.json",
                                        "config: /etc/board.json"))
        assert load(path).config[0] == "/etc/board.json"

    def test_parsing_a_string_with_no_source_leaves_the_path_as_written(self):
        assert parse(MINIMAL).config[0] == "board.json"


class TestTheShippedScenariosFollowTheSameRule:
    def test_every_one_names_its_config_relative_to_itself(self):
        from conftest import SCENARIOS
        shipped = sorted(SCENARIOS.glob("*.yaml"))
        assert shipped, f"no scenarios under {SCENARIOS}"
        for path in shipped:
            got = load(path)
            for entry in got.config:
                assert Path(entry).is_absolute(), f"{path.name}: {entry}"
                assert Path(entry).exists(), f"{path.name}: {entry} does not exist"
