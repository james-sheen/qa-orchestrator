"""The machine a scenario perturbs, in three tiers.

`mock` runs in this process and needs nothing. `qemu` boots real firmware. `testbed`
drives real hardware and **does not exist yet, which it says out loud.**

The tiers exist so the same scenario file can be run at increasing cost and
increasing realism without being rewritten. That only holds if a tier that cannot
do something refuses instead of approximating it -- a backend that quietly no-ops
an injection turns every later phase into a test of nothing, and reports success
while doing it.
"""

from __future__ import annotations

from typing import Protocol


class BackendUnavailable(RuntimeError):
    """This tier cannot run here, and says why rather than degrading."""


class Backend(Protocol):
    """What a scenario needs a machine to do.

    Deliberately small. Every verb here maps to one the audit tool already has a
    documented opinion about -- a sensor that vanished, one switched off, a subtree
    that fails, a reading that moved -- so the harness cannot ask a question the
    referee has no answer for.
    """

    name: str

    def start(self) -> str:
        """Bring the machine up; return the Redfish base URL to walk."""

    def stop(self) -> None:
        """Take it down. Safe to call twice."""

    def remove(self, sensor: str) -> None:
        """Make a sensor vanish from the tree entirely."""

    def disable(self, sensor: str) -> None:
        """Switch a sensor off; it stays declared and stops reading."""

    def fail(self, path: str, status: int) -> None:
        """Make a subtree answer with an HTTP status, for a partial walk."""

    def set_reading(self, sensor: str, value: float) -> None:
        """Move a sensor's reading."""

    def state(self, sensor: str) -> str:
        """`absent`, `disabled`, or `reading` -- what the machine looks like now.

        Read from the machine, never from what the scenario asked for. The whole
        point of a firmware expectation is to catch an injection that did not take.
        """


def build(name: str, machine: dict) -> Backend:
    """Construct a backend by name, or raise with the known tiers listed."""
    if name == "mock":
        from .mock import MockBackend
        return MockBackend(machine)
    if name == "qemu":
        from .qemu import QemuBackend
        return QemuBackend(machine)
    if name == "testbed":
        from .testbed import TestbedBackend
        return TestbedBackend(machine)
    raise BackendUnavailable(f"unknown backend {name!r}; this build has mock, qemu, testbed")
