"""The first vertical's tiers, registered through the same door as any other.

They were `backends/{mock,qemu,testbed}.py` in the core. Nothing about them was
ever general: a mock BMC, a QEMU machine running real firmware, and a lab bench
with a relay board. They are here because they belong to the vertical, and the
core is what had no business naming them.

**The factories are lazy, and that is a behaviour worth pinning.** `mock.py`
raises at import when `bmc-sensor-audit` is absent, so a registry holding the
classes would make the whole vertical fail to load on a machine without the
referee -- and a scenario could then not even be PARSED, which is a different and
much worse failure than one that cannot be RUN.
"""

from __future__ import annotations

import pytest

from qa_orchestrator import substrate
from qa_orchestrator.verticals import bmc
from qa_orchestrator.verticals.bmc_tiers import TIERS
from qa_orchestrator.vocabulary import SubstrateUnavailable


@pytest.fixture
def vertical():
    bmc.register()
    yield
    bmc.unregister()


class TestTheVerticalBringsItsTiers:
    def test_all_three_are_registered(self, vertical):
        for name in ("mock", "qemu", "testbed"):
            assert name in substrate.known(), f"{name} did not reach the registry"

    def test_the_core_still_has_its_own(self, vertical):
        """Non-vacuity in the other direction: the vertical adds, never replaces."""
        assert "memory" in substrate.known()

    def test_they_are_gone_again_afterwards(self):
        for name in ("mock", "qemu", "testbed"):
            assert name not in substrate.known()


class TestNamingATierNeedsNoReferee:
    """The lazy-factory contract. `check` must work on a machine with nothing
    installed; only `run` needs the referee."""

    def test_the_registry_holds_callables_not_classes(self):
        assert all(callable(f) for f in TIERS.values())

    def test_importing_the_package_does_not_import_the_referee(self):
        """If it did, this import would raise on a machine without the tool, and
        the vertical would not load at all."""
        import qa_orchestrator.verticals.bmc_tiers as tiers
        assert tiers.TIERS


class TestTheLabTierRefuses:
    """It has no hardware behind it. The day this stops raising is the day a
    scenario can claim it pulled a real fan while touching nothing."""

    def test_it_refuses_to_construct(self, vertical):
        with pytest.raises(SubstrateUnavailable, match="not implemented"):
            substrate.build("testbed", {})

    def test_it_says_what_a_real_one_would_need(self, vertical):
        """A refusal that does not say what is missing reads as a bug."""
        with pytest.raises(SubstrateUnavailable) as refusal:
            substrate.build("testbed", {})
        said = str(refusal.value)
        assert "relay" in said and "Redfish" in said, said

    def test_it_is_refused_and_not_merely_absent(self, vertical):
        """Different faults. A tier that vanished would also stop a scenario, and
        would do it with a message about an unknown name -- which sends the reader
        to the scenario instead of to the hardware that is not there."""
        assert "testbed" in substrate.known()
