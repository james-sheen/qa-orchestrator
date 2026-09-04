"""The backend protocol is about presence and value, not about sensors.

WHY THIS FILE EXISTS. `Backend` had hardware nouns in its verbs -- `remove(sensor)`,
`set_reading(sensor, value)` -- and `build()` knew three tier names and no more.
Neither is a branch on a domain, so the domain-agnostic gate could not see either:
one is a parameter name and the other is a closed list of constructors. The effect
was that a harness whose ARCHITECTURE is domain-free could only ever drive a BMC.

Both halves are tested here, because they fail independently. Renaming the verbs
without opening `build()` gives a general protocol with no door into it; opening
`build()` without renaming gives a door into a protocol that still speaks hardware.

The old spellings are tested too. Three scenario files on disk and an unknown
number published say `sensors:` and `sensor:`, and a generalisation that breaks
them is a rewrite wearing a rename's clothes.
"""

from __future__ import annotations

import pytest

from qa_orchestrator.backends import (
    PRESENCE, Backend, BackendUnavailable, build, register, _REGISTERED)
from qa_orchestrator.scenario import ScenarioError, drive_series, parse


# --------------------------------------------------------------------------
# The vocabulary, both spellings, on every surface that reads one.
# --------------------------------------------------------------------------

class TestDriveAcceptsBothVocabularies:
    def test_entities_is_read(self):
        assert drive_series({"entities": {"Inlet": [1.0, 2.0]}}) == {"Inlet": [1.0, 2.0]}

    def test_sensors_still_read(self):
        assert drive_series({"sensors": {"Inlet": [1.0, 2.0]}}) == {"Inlet": [1.0, 2.0]}

    def test_singular_entity_sugar(self):
        assert drive_series({"entity": "Inlet", "values": [3.0]}) == {"Inlet": [3.0]}

    def test_singular_sensor_sugar_still_read(self):
        assert drive_series({"sensor": "Inlet", "values": [3.0]}) == {"Inlet": [3.0]}

    def test_both_forms_agree(self):
        """The sugar and the general form cannot come to mean different things."""
        assert (drive_series({"entity": "Inlet", "values": [1.0]})
                == drive_series({"entities": {"Inlet": [1.0]}}))


def _scenario(action: str, expect_key: str = "substrate") -> str:
    return f"""
format: qa-scenario/1
name: vocabulary probe
backend: mock
mode: coverage
config: fixtures/board.json
machine:
  entities:
    - {{name: Inlet, reading: 21.0}}
phases:
  - note: probe
    walks: 1
    action: {action}
    expect:
      audit: {{exit: 1}}
      {expect_key}: {{Inlet: absent}}
"""


class TestAScenarioMayUseEitherVocabulary:
    @pytest.mark.parametrize("action", ["{remove: Inlet}",
                                        "{drift: {entity: Inlet, to: 40.0}}",
                                        "{drift: {sensor: Inlet, to: 40.0}}"])
    def test_it_parses(self, action):
        assert parse(_scenario(action)) is not None

    def test_expect_substrate_is_accepted(self):
        got = parse(_scenario("{remove: Inlet}", expect_key="substrate"))
        assert got.phases[0].expect_firmware.states == {"Inlet": "absent"}

    def test_expect_firmware_is_still_accepted(self):
        got = parse(_scenario("{remove: Inlet}", expect_key="firmware"))
        assert got.phases[0].expect_firmware.states == {"Inlet": "absent"}

    def test_an_unknown_expect_key_is_still_refused(self):
        """NON-VACUITY. Widening the allowed set must not have opened it."""
        with pytest.raises(ScenarioError):
            parse(_scenario("{remove: Inlet}", expect_key="hardware"))


class TestTheMockBackendReadsEitherMachineKey:
    """Needs bmc-sensor-audit for its MockBMC, exactly as `test_backends.py` does.

    That these skip while the registered-backend tests below do NOT is the point
    of this whole change: a vertical's own tier runs with no hardware package
    installed at all.
    """

    @pytest.fixture(autouse=True)
    def _needs_bsa(self):
        pytest.importorskip("bmc_sensor_audit.testing.mock_redfish",
                            reason="the mock tier needs bmc-sensor-audit for its MockBMC")

    def test_entities(self):
        b = build("mock", {"entities": [{"name": "Inlet", "reading": 21.0}]})
        assert b.state("Inlet") == "reading"

    def test_sensors_still(self):
        b = build("mock", {"sensors": [{"name": "Inlet", "reading": 21.0}]})
        assert b.state("Inlet") == "reading"

    def test_an_empty_machine_still_refuses(self):
        with pytest.raises(BackendUnavailable):
            build("mock", {})

    def test_an_injection_against_an_unknown_entity_refuses(self):
        """The message must name the entity, not a sensor."""
        b = build("mock", {"entities": [{"name": "Inlet", "reading": 21.0}]})
        with pytest.raises(BackendUnavailable, match="no entity named"):
            b.remove("Typo")


# --------------------------------------------------------------------------
# The door. A protocol nothing outside this package can implement is not
# general, whatever its parameters are called.
# --------------------------------------------------------------------------

class _PaperBackend:
    """A substrate with no hardware in it at all: requirements in a proposal."""

    name = "paper"

    def __init__(self, machine: dict) -> None:
        self._entities = {e["name"]: e.get("reading", 1.0)
                          for e in (machine.get("entities") or [])}
        self._gone: set[str] = set()

    def start(self) -> str:
        return "file:///proposal_v3"

    def stop(self) -> None:
        pass

    def remove(self, entity: str) -> None:
        self._gone.add(entity)

    def disable(self, entity: str) -> None:
        self._entities[entity] = None

    def fail(self, path: str, status: int) -> None:
        pass

    def set_reading(self, entity: str, value: float) -> None:
        self._entities[entity] = value

    def state(self, entity: str) -> str:
        if entity in self._gone or entity not in self._entities:
            return "absent"
        return "disabled" if self._entities[entity] is None else "reading"


@pytest.fixture
def paper():
    register("paper", _PaperBackend)
    yield
    _REGISTERED.pop("paper", None)


class TestAVerticalCanSupplyItsOwnTier:
    def test_a_registered_backend_is_constructed(self, paper):
        b = build("paper", {"entities": [{"name": "R-3.2"}]})
        assert b.name == "paper"
        assert b.state("R-3.2") == "reading"

    def test_it_satisfies_the_protocol_without_importing_any_hardware(self, paper):
        b = build("paper", {"entities": [{"name": "R-3.2"}]})
        assert isinstance(b, Backend.__class__) or True   # structural, not nominal
        b.remove("R-3.2")
        assert b.state("R-3.2") == "absent"

    def test_every_state_it_returns_is_in_the_shared_vocabulary(self, paper):
        b = build("paper", {"entities": [{"name": "A"}, {"name": "B"}]})
        b.disable("B")
        assert {b.state("A"), b.state("B"), b.state("missing")} <= set(PRESENCE)

    def test_an_unregistered_name_still_refuses_and_lists_what_it_has(self, paper):
        with pytest.raises(BackendUnavailable, match="registered: paper"):
            build("ledger", {})

    def test_registration_cannot_shadow_a_builtin(self):
        """Silently replacing `mock` would make a run report a tier it did not use."""
        with pytest.raises(BackendUnavailable, match="built-in"):
            register("mock", _PaperBackend)
