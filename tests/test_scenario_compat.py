"""The three shipped `qa-scenario/1` files LOAD unchanged, and the parser refuses what it should.

**Loading is all this file checks.** It says nothing about whether a scenario
still reaches its verdict, and it stayed green through a migration in which none
of the three did -- `tests/test_bmc_scenarios_run.py` is the half that runs them.

The vertical registers its own tiers, so these read the real thing: `mock` is the
tier the files name, not a stand-in. `parse()` asks the registry for the name and
never constructs one, so none of this needs the referee installed.
"""

from __future__ import annotations

import pytest

from conftest import SCENARIOS
from qa_orchestrator import referee, substrate
from qa_orchestrator.scenario import ScenarioError, load, parse
from qa_orchestrator.substrates.memory import MemorySubstrate
from qa_orchestrator.verticals import bmc


@pytest.fixture
def bmc_vertical():
    bmc.register()
    yield
    bmc.unregister()


class TestTheShippedScenariosReadUnchanged:
    def test_sensor_removed(self, bmc_vertical):
        got = load(SCENARIOS / "sensor-removed.yaml")
        assert got.format == "qa-scenario/1"
        assert got.substrate == "mock" and got.backend == "mock"
        assert got.referee == "bmc-sensor-audit" and got.mode == "coverage"
        assert got.config[0].endswith("fixtures/board.json") and got.config[0].startswith("/")
        assert got.setup["sensors"][0]["name"] == "Inlet" and got.machine is got.setup
        second = got.phases[1]
        assert second.action == ("remove", "Outlet")
        assert second.expect_referee.exit_code == 1
        assert second.expect_referee.findings.text == "not reported by the machine at all"
        assert second.expect_referee.findings.names == ("Outlet",)
        assert second.expect_referee.findings.not_names == ("Inlet",)
        assert second.expect_substrate.states == {"Outlet": "absent", "Inlet": "reading"}
        assert got.phases[2].action == ("disable", "Inlet")

    def test_partial_walk(self, bmc_vertical):
        got = load(SCENARIOS / "partial-walk.yaml")
        second = got.phases[1]
        assert second.action == ("fail", {"region": "/redfish/v1/Chassis/1/Sensors", "status": 500})
        assert second.expect_referee.exit_code == 2
        # Was `walk did not finish` -- the tool's PROSE, which no field of its
        # JSON report carries. From 0.3 a finding is judged from the report, so
        # the file asserts the report's own words for the same fact. The change
        # is the one place a `qa-scenario/1` file did not survive unchanged.
        assert second.expect_referee.findings.text == "absence cannot be distinguished"
        assert second.expect_substrate is None

    def test_stuck_at(self, bmc_vertical):
        got = load(SCENARIOS / "stuck-at.yaml")
        assert got.mode == "detect"
        first, second = got.phases
        assert first.captures == 12 and second.captures == 16
        assert first.action[0] == "drive"
        assert set(first.action[1]) == {"Inlet", "Outlet"}
        assert len(first.action[1]["Inlet"]) == 12
        assert second.action[1] == {"Outlet": second.action[1]["Outlet"]}
        assert len(second.action[1]["Outlet"]) == 16
        assert second.expect_referee.findings.names == ("Inlet",)
        assert second.expect_referee.findings.not_names == ("Outlet",)

    def test_a_v1_file_without_the_vertical_is_refused_by_name(self):
        """No loaded vertical, no v1 default: the file must not silently mean anything.

        The stand-in tier is registered so the refusal that fires is the one under
        test; without it the parser refuses on the substrate first and never
        reaches its subject.
        """
        substrate.register("mock", MemorySubstrate)
        try:
            with pytest.raises(ScenarioError, match="names no referee"):
                parse((SCENARIOS / "partial-walk.yaml").read_text())
        finally:
            substrate.unregister("mock")


V2 = """
format: qa-scenario/2
name: probe
substrate: memory
referee: probe-tool
mode: look
config: rules.json
setup:
  entities: [{name: A, value: 1}, {name: B, value: 2}]
phases:
  - note: probe
    captures: 2
    action: {ACTION}
    expect:
      {EXPECT}
"""


@pytest.fixture
def probe_tool():
    tool = referee.Tool(
        name="probe-tool", executable="probe-tool", install_hint="n/a", modes=("look", "stare"),
        capture_argv=lambda h, o: ("cap", h, str(o)),
        judge_argv=lambda m, c, w: (m,),
        json_argv=lambda m: ("--json",) if m == "look" else None,
        report=referee.ReportSchema(declines="skipped", checked="n"))
    referee.register_tool(tool)
    yield tool
    referee.unregister_tool(tool.name)


def _v2(action: str = "{remove: A}", expect: str = "referee: {exit: 0}") -> str:
    return V2.replace("{ACTION}", action).replace("{EXPECT}", expect)


class TestTheGeneralVocabularyParses:
    def test_a_v2_file(self, probe_tool):
        got = parse(_v2())
        assert got.substrate == "memory" and got.referee == "probe-tool" and got.mode == "look"
        assert got.phases[0].captures == 2

    def test_config_is_verbatim_when_the_profile_says_it_is_not_a_path(self, probe_tool, tmp_path):
        verbatim = referee.Tool(**{**probe_tool.__dict__, "name": "verbatim", "configs_are_paths": False})
        referee.register_tool(verbatim)
        try:
            got = parse(_v2().replace("probe-tool", "verbatim").replace("rules.json", "ruleset-v3"),
                        source=tmp_path / "s.yaml")
        finally:
            referee.unregister_tool("verbatim")
        assert got.config == ("ruleset-v3",)

    def test_set_and_its_v1_alias_normalise_alike(self, probe_tool):
        assert (parse(_v2("{set: {entity: A, to: 5}}")).phases[0].action
                == parse(_v2("{drift: {sensor: A, to: 5}}")).phases[0].action
                == ("set", {"entity": "A", "to": 5}))

    def test_values_pass_through_untouched(self, probe_tool):
        got = parse(_v2('{drive: {entities: {A: ["low", "high"]}}}'))
        assert got.phases[0].action == ("drive", {"A": ["low", "high"]})

    def test_declines_and_checked_expectations(self, probe_tool):
        got = parse(_v2(expect="referee: {declines: {reason: r, names: [A]}, checked: {at_least: 1}}"))
        want = got.phases[0].expect_referee
        assert want.declines.reason == "r" and want.declines.names == ("A",)
        assert want.checked.at_least == 1 and want.checked.exact is None


class TestTheParserRefuses:
    @pytest.mark.parametrize("text, spelled", [
        (_v2().replace("substrate: memory", "substrate: memory\nbackend: memory"), "substrate and backend"),
        (_v2().replace("setup:", "machine: {}\nsetup:"), "setup and machine"),
        (_v2().replace("captures: 2", "captures: 2\n    walks: 2"), "captures and walks"),
        (_v2(expect="referee: {exit: 0}\n      audit: {exit: 0}"), "referee and audit"),
        (_v2(expect="substrate: {A: reading}\n      firmware: {A: reading}"), "substrate and firmware"),
        (_v2("{set: {entity: A, sensor: A, to: 1}}"), "entity and sensor"),
        (_v2("{drive: {entities: {A: [1, 2]}, sensors: {A: [1, 2]}}}"), "entities and sensors"),
        (_v2("{fail: {region: x, path: x, status: 1}}"), "region and path"),
    ])
    def test_a_thing_spelled_both_ways(self, probe_tool, text, spelled):
        with pytest.raises(ScenarioError, match=f"spelled both ways \\({spelled}\\)"):
            parse(text)

    def test_an_unknown_substrate_lists_what_it_has(self, probe_tool):
        with pytest.raises(ScenarioError, match=r"substrate is 'ledger'; this build has \['memory'\]"):
            parse(_v2().replace("substrate: memory", "substrate: ledger"))

    def test_an_unknown_referee_lists_what_it_has(self, probe_tool):
        with pytest.raises(ScenarioError, match=r"referee is 'other'; this build has \['probe-tool'\]"):
            parse(_v2().replace("referee: probe-tool", "referee: other"))

    def test_a_v2_file_must_name_its_referee(self, probe_tool):
        with pytest.raises(ScenarioError, match="must name its referee"):
            parse(_v2().replace("referee: probe-tool\n", ""))

    def test_mode_is_judged_against_that_referees_vocabulary(self, probe_tool):
        with pytest.raises(ScenarioError, match=r"mode is 'detect'; probe-tool has \['look', 'stare'\]"):
            parse(_v2().replace("mode: look", "mode: detect"))

    def test_declines_need_a_json_form(self, probe_tool):
        """`stare` has no JSON, so what was not checked could not be read."""
        with pytest.raises(ScenarioError, match="expects declines, but probe-tool has no JSON form for mode 'stare'"):
            parse(_v2(expect="referee: {declines: {reason: r}}").replace("mode: look", "mode: stare"))

    def test_declines_need_a_profile_that_declares_them(self, probe_tool):
        plain = referee.Tool(**{**probe_tool.__dict__, "name": "plain", "report": referee.ReportSchema()})
        referee.register_tool(plain)
        try:
            with pytest.raises(ScenarioError, match="declares no declines list"):
                parse(_v2(expect="referee: {declines: {reason: r}}").replace("probe-tool", "plain"))
        finally:
            referee.unregister_tool("plain")

    def test_a_state_outside_presence(self, probe_tool):
        with pytest.raises(ScenarioError, match="expected one of absent, disabled, reading"):
            parse(_v2(expect="substrate: {A: gone}"))

    def test_within_is_refused_rather_than_read_by_nothing(self, probe_tool):
        with pytest.raises(ScenarioError, match="within_"):
            parse(_v2(expect="substrate: {A: reading, within_captures: 2}"))

    def test_drive_shorter_than_the_phase(self, probe_tool):
        with pytest.raises(ScenarioError, match="supplies 1 value\\(s\\) for A over 2 capture"):
            parse(_v2("{drive: {entity: A, values: [1]}}"))

    def test_an_empty_expectation(self, probe_tool):
        with pytest.raises(ScenarioError, match="sets nothing"):
            parse(_v2(expect="referee: {}"))

    def test_an_unknown_expect_key(self, probe_tool):
        with pytest.raises(ScenarioError, match=r"unknown key\(s\) \['hardware'\]"):
            parse(_v2(expect="hardware: {A: reading}"))
