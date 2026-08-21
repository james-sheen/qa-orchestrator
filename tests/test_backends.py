"""The backends refuse rather than approximate.

The three tiers exist so one scenario file can be run at increasing cost and
realism without rewriting. That only holds if a tier which cannot do something
says so. A backend that quietly no-opped an injection would leave every later
phase judging an unperturbed machine and passing for it -- and the run would be
green, which is worse than red.
"""

from __future__ import annotations

import pytest

from qa_orchestrator.backends import BackendUnavailable, build

mock_backend = pytest.importorskip(
    "bmc_sensor_audit.testing.mock_redfish",
    reason="the mock tier needs bmc-sensor-audit for its MockBMC")

MACHINE = {"sensors": [{"name": "Inlet", "reading": 21.0},
                       {"name": "Outlet", "reading": 27.5}]}


class TestTheTestbedTierRefuses:
    """It has no hardware behind it, and that is the whole test.

    A stub that accepted injections and did nothing would let a `backend: testbed`
    scenario report that real fans were pulled having touched nothing.
    """

    def test_it_cannot_be_constructed(self):
        with pytest.raises(BackendUnavailable) as raised:
            build("testbed", {})
        assert "not implemented" in str(raised.value)

    def test_the_refusal_specifies_what_a_real_one_would_need(self):
        """The refusal is a specification, not an apology -- when a lab exists,
        this is the list to satisfy."""
        with pytest.raises(BackendUnavailable) as raised:
            build("testbed", {})
        message = str(raised.value)
        for required in ("relay", "credentials", "declaration", "safe state"):
            assert required in message

    def test_it_points_at_the_tier_that_does_work(self):
        with pytest.raises(BackendUnavailable) as raised:
            build("testbed", {})
        assert "backend: mock" in str(raised.value)


class TestTheQemuTierRefusesWithoutATarget:
    def test_it_will_not_pretend_to_boot_one(self):
        """This build attaches to a running instance. Claiming the boot recipe
        would be worse than not having it."""
        with pytest.raises(BackendUnavailable) as raised:
            build("qemu", {})
        assert "does not boot one" in str(raised.value)


class TestTheMockTier:
    def test_an_empty_machine_is_refused(self):
        """Every declared sensor would be absent and every phase would pass for
        that reason."""
        with pytest.raises(BackendUnavailable, match="machine.sensors"):
            build("mock", {})

    def test_an_injection_against_an_unknown_sensor_is_refused(self):
        """A typo would otherwise perturb nothing and let the phase pass, which is
        indistinguishable from the referee failing to notice a real fault."""
        backend = build("mock", MACHINE)
        with pytest.raises(BackendUnavailable) as raised:
            backend.remove("Inlt")
        assert "Inlet" in str(raised.value), "the refusal should list what is there"

    def test_removal_and_disabling_are_different_states(self):
        """Three-valued presence is the tool's whole argument; a backend that
        collapsed two of them could not exercise it."""
        backend = build("mock", MACHINE)
        assert backend.state("Inlet") == "reading"
        backend.disable("Inlet")
        assert backend.state("Inlet") == "disabled"
        backend.remove("Inlet")
        assert backend.state("Inlet") == "absent"
        backend.stop()

    def test_state_is_read_from_the_machine_not_from_what_was_asked(self):
        """The point of a firmware expectation is to catch an injection that did
        not take, which needs the observation to be independent of the request."""
        backend = build("mock", MACHINE)
        assert backend.state("NeverExisted") == "absent"
        backend.stop()

    def test_an_injection_is_visible_to_the_next_walk(self):
        """`serve` snapshots the routes when it binds, so a mutation after start
        is invisible until the server is rebuilt. Found by an injection that took
        in the object and never appeared in a walk."""
        import json
        import urllib.request

        backend = build("mock", MACHINE)
        url = backend.start()
        backend.remove("Inlet")
        url = backend.start()          # the port moves; re-read it
        with urllib.request.urlopen(f"{url}/redfish/v1/Chassis/1/Sensors",
                                    timeout=10) as response:
            listing = json.loads(response.read())
        served = {member["@odata.id"].rsplit("/", 1)[-1]
                  for member in listing.get("Members", [])}
        backend.stop()
        assert not any("Inlet" in name for name in served), (
            f"Inlet was removed and the served tree still lists {sorted(served)}")
