"""The hardware-lab tier. It does not exist, and this is where that is said.

**This file is deliberately not a stub that works.** A backend that accepted every
injection and quietly did nothing would let a `backend: testbed` scenario run green
on a machine with no lab attached -- reporting that real fans were pulled and real
sensors went absent, having touched nothing. Every phase after the first would then
be testing an unperturbed machine and passing for it.

So it refuses at construction, names what is missing, and points at the tier that
does work. When a lab exists, this file is where it gets wired, and the refusal
below is the specification of what has to be provided.
"""

from __future__ import annotations

from . import BackendUnavailable

# What a real implementation needs, written down now so the refusal is a
# specification rather than an apology.
REQUIRES = (
    "a relay board addressable from the runner, for cutting fan and PSU power",
    "a BMC on the network with credentials, reachable over Redfish",
    "a declaration for the board under test, matching the unit wired up",
    "a documented safe state to return the unit to when a run ends or aborts",
)


class TestbedBackend:
    name = "testbed"

    def __init__(self, machine: dict) -> None:
        raise BackendUnavailable(
            "the testbed backend is not implemented: there is no hardware lab "
            "behind it yet.\n\n"
            "This refuses rather than no-opping. A backend that accepted "
            "injections and did nothing would report that a fan was pulled when "
            "nothing was touched, and every phase after it would pass against an "
            "unperturbed machine.\n\n"
            "What a real implementation needs:\n"
            + "\n".join(f"  - {item}" for item in REQUIRES)
            + "\n\nUntil then, run the scenario with `backend: mock` for the "
              "zero-hardware tier, or `backend: qemu` for real firmware.")
