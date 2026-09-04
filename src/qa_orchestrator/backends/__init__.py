"""The substrate a scenario perturbs, in tiers.

`mock` runs in this process and needs nothing. `qemu` boots real firmware.
`testbed` drives real hardware and **does not exist yet, which it says out loud.**

The tiers exist so the same scenario file can be run at increasing cost and
increasing realism without being rewritten. That only holds if a tier that cannot
do something refuses instead of approximating it -- a backend that quietly no-ops
an injection turns every later phase into a test of nothing, and reports success
while doing it.

WHY THE VOCABULARY HERE IS `entity` AND NOT `sensor`. This protocol had hardware
nouns in it, and a hardware noun in a protocol is a domain lock that no gate can
see: it is not a branch on a domain, so nothing parses it, and it is not a word
list, so nothing greps it. It simply makes the harness unusable by anything that
does not have sensors. The three built-in tiers are all hardware and always were,
so the coupling cost nothing until a second kind of substrate turned up.

An `entity` is whatever the tool under test enumerates and reports on: a sensor, a
requirement in a proposal, a ledger account, an open matter. Every verb below is
about presence and value, and neither of those is a hardware idea.
"""

from __future__ import annotations

from typing import Callable, Dict, Protocol


class BackendUnavailable(RuntimeError):
    """This tier cannot run here, and says why rather than degrading."""


#: The three-valued presence vocabulary, shared so a backend and a scenario
#: expectation cannot spell it two ways.
#:
#: These are not hardware states. They are the three ways a thing that SHOULD be
#: there can actually be: gone, there but not reporting, there and reporting. A
#: boolean would collapse the middle one, and the middle one is where the
#: interesting faults live -- a sensor switched off at the factory, a requirement
#: present in a proposal but unanswerable, an account that exists and has stopped
#: settling. `disabled` keeps its name because it reads correctly in all three.
PRESENCE = ("absent", "disabled", "reading")


class Backend(Protocol):
    """What a scenario needs a substrate to do.

    Deliberately small. Every verb maps to a condition the tool under test already
    has a documented opinion about -- an entity that vanished, one switched off, a
    region that fails, a value that moved -- so the harness cannot ask a question
    the referee has no answer for.
    """

    name: str

    def start(self) -> str:
        """Bring the substrate up; return the handle the referee reads it through.

        A URL for a Redfish tree, a path for a document set, a DSN -- whatever the
        tool under test is pointed at. The harness does not interpret it; it hands
        it to the referee's capture step verbatim.
        """

    def stop(self) -> None:
        """Take it down. Safe to call twice."""

    def remove(self, entity: str) -> None:
        """Make an entity vanish entirely, as if it had never been declared."""

    def disable(self, entity: str) -> None:
        """Switch an entity off; it stays declared and stops reporting a value."""

    def fail(self, path: str, status: int) -> None:
        """Make a region of the substrate answer with an error, for a partial read.

        `path` and `status` are the transport's own terms -- an HTTP subtree and
        code for a Redfish tier. A tier reading files would take a glob and an
        errno. The harness passes them through and does not interpret them.
        """

    def set_reading(self, entity: str, value: float) -> None:
        """Move an entity's value."""

    def state(self, entity: str) -> str:
        """One of `PRESENCE` -- what the substrate looks like NOW.

        Read from the substrate, never from what the scenario asked for. The whole
        point of this expectation is to catch an injection that did not take.
        """


#: Backends registered at runtime, consulted before the built-in tiers.
#:
#: WHY THIS EXISTS. `build()` used to know three names and no more, so a substrate
#: that was not a BMC could not be driven by this harness at all -- the protocol
#: was general and the only door into it was not. Registering is how a vertical
#: supplies its own tier without editing this file, which is what makes the
#: harness reusable rather than merely renameable.
_REGISTERED: Dict[str, Callable[[dict], "Backend"]] = {}

#: The tiers compiled in. Kept separate from `_REGISTERED` so the error message
#: below can tell a caller which names are built in and which were registered --
#: a missing registration and a typo look identical otherwise.
_BUILTIN = ("mock", "qemu", "testbed")


def register(name: str, factory: Callable[[dict], "Backend"]) -> None:
    """Make `backend: <name>` in a scenario construct `factory(machine)`.

    Refuses to shadow a built-in tier. Silently replacing `mock` would mean a
    scenario that names it runs against something else entirely, and the run
    report would still say `mock`.
    """
    if name in _BUILTIN:
        raise BackendUnavailable(
            f"{name!r} is a built-in tier and cannot be replaced by registration; "
            f"choose another name so a scenario naming it says what it ran")
    _REGISTERED[name] = factory


def known() -> tuple[str, ...]:
    """Every tier a scenario may name: the built-in ones plus any registered.

    One place, and it exists because there used to be two. The parser kept its
    own copy of the built-in list and refused a registered tier before `build`
    was ever reached -- so the door `register` opens was shut one module up, and
    a vertical could construct its own backend but could not write a scenario
    that named it. Every test called `build` directly, so nothing could see it.
    """
    return tuple(sorted(set(_BUILTIN) | set(_REGISTERED)))


def build(name: str, machine: dict) -> Backend:
    """Construct a backend by name, or raise with the known tiers listed."""
    if name in _REGISTERED:
        return _REGISTERED[name](machine)
    if name == "mock":
        from .mock import MockBackend
        return MockBackend(machine)
    if name == "qemu":
        from .qemu import QemuBackend
        return QemuBackend(machine)
    if name == "testbed":
        from .testbed import TestbedBackend
        return TestbedBackend(machine)
    known = ", ".join(_BUILTIN)
    extra = ", ".join(sorted(_REGISTERED)) or "(none)"
    raise BackendUnavailable(
        f"unknown backend {name!r}; this build has {known}, registered: {extra}")
