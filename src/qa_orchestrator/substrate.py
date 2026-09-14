"""The substrate a scenario perturbs: whatever the referee enumerates and reports on.

An **entity** is one thing the referee is expected to enumerate -- a sensor, a
requirement in a proposal, a ledger account, an open matter. Every verb here is
about presence and value, and neither is a domain idea.

A substrate is a **tier**. `memory` is built in and runs in this process. A
vertical supplies its own with `register()`, which is the only door, and the same
door the vertical shipped in this package uses: nothing in this module names it.

The tiers exist so the same scenario can run at increasing cost and realism
without being rewritten. That only holds if a tier that cannot do something
refuses instead of approximating it -- a substrate that quietly no-ops an
injection turns every later phase into a test of nothing, and reports success
while doing it.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Protocol

from .vocabulary import PRESENCE, RegistrationError, SubstrateUnavailable


class Substrate(Protocol):
    """What a scenario needs a substrate to do.

    Deliberately small. Every verb maps to a condition the referee already has a
    documented opinion about -- an entity that vanished, one switched off, a
    region that fails, a value that moved -- so the harness cannot ask a question
    the referee has no answer for. A vertical that needs more registers a verb
    (`actions.register_verb`) whose `apply` calls whatever its own tier offers.
    """

    name: str

    def start(self) -> str:
        """Make the current state observable; return the handle the referee reads it through.

        A URL, a path, a DSN -- whatever the referee is pointed at. The harness
        does not interpret it. Called before EVERY capture, because an injection
        may rebuild whatever serves the handle; a tier for which that is cheap
        simply returns the same handle again.
        """

    def access(self) -> Any:
        """How a referee reaches this substrate, BEYOND the handle `start` returns.

        Optional: a tier that needs nothing more does not define it, and the
        harness supplies an empty description. Whatever is returned is passed to
        the referee profile untouched -- the harness does not read it, exactly as
        it does not read the handle.

        It exists because a handle alone cannot reach a real machine. A scenario
        pointed at one could name the target and nothing else: no credential, no
        certificate choice, no timeout, because the format had nowhere to put
        them and the profile's argv builder took two arguments. A tier could
        inject into real firmware and the referee could never read it, which was
        found by running one.
        """

    def stop(self) -> None:
        """Take it down. Safe to call twice."""

    def remove(self, entity: str) -> None:
        """Make an entity vanish entirely, as if it had never been declared."""

    def disable(self, entity: str) -> None:
        """Switch an entity off; it stays declared and stops reporting a value."""

    def fail(self, region: str, status: Any) -> None:
        """Make a region of the substrate answer with an error, for a partial capture.

        `region` and `status` are the tier's own terms -- an HTTP subtree and a
        code, a glob and an errno, a table and a SQLSTATE. The harness passes
        them through untouched and does not interpret them.
        """

    def set_value(self, entity: str, value: Any) -> None:
        """Move an entity's value. Whatever the tier accepts; the harness does not coerce."""

    def state(self, entity: str) -> str:
        """One of `PRESENCE` -- what the substrate looks like NOW.

        Read from the substrate, never from what the scenario asked for. The whole
        point of a substrate expectation is to catch an injection that did not
        take.
        """


Factory = Callable[[dict], Substrate]


def access_of(substrate: Any) -> Any:
    """A tier's access description, or nothing.

    `getattr` rather than a required member: every tier written before this
    existed is still a tier, and a protocol that breaks its implementors to add
    an optional capability is not optional. A tier whose `access` raises is NOT
    caught here -- a tier refusing to describe itself is refusing, and the run
    must stop rather than fall back to the empty description that means *no
    credential needed*.
    """
    describe = getattr(substrate, "access", None)
    return describe() if callable(describe) else None

#: Tiers a vertical registered at runtime.
_REGISTERED: Dict[str, Factory] = {}

#: The one tier compiled in. It is domain-free -- a dictionary of entities that
#: writes itself to a file -- which is why it can be here and nothing else can.
_BUILTIN = ("memory",)


def register(name: str, factory: Factory) -> None:
    """Make `substrate: <name>` in a scenario construct `factory(setup)`.

    Refuses a name already taken, built in or registered. Silently replacing a
    tier would mean a scenario that names it runs against something else, and
    the run report would still say the name. A vertical that means to replace
    one calls `unregister()` first, so the intent is written down.
    """
    if not isinstance(name, str) or not name.strip():
        raise RegistrationError("a substrate needs a non-empty name")
    if not callable(factory):
        raise RegistrationError(f"substrate {name!r}: factory {factory!r} is not callable")
    if name in _BUILTIN:
        raise RegistrationError(
            f"{name!r} is a built-in tier and cannot be replaced by registration; "
            f"choose another name so a scenario naming it says what it ran")
    if name in _REGISTERED:
        raise RegistrationError(
            f"substrate {name!r} is already registered ({_REGISTERED[name]!r}); "
            f"unregister it first if replacing it is what you mean")
    _REGISTERED[name] = factory


def unregister(name: str) -> None:
    """Forget a registered tier. A built-in cannot be forgotten."""
    if name in _BUILTIN:
        raise RegistrationError(f"{name!r} is built in and cannot be unregistered")
    _REGISTERED.pop(name, None)


def known() -> tuple[str, ...]:
    """Every tier a scenario may name: built in plus registered. Asked, never copied."""
    return tuple(sorted(set(_BUILTIN) | set(_REGISTERED)))


def build(name: str, setup: dict) -> Substrate:
    """Construct a tier by name, or raise with the known tiers listed."""
    if name in _REGISTERED:
        return _REGISTERED[name](setup)
    if name == "memory":
        from .substrates.memory import MemorySubstrate
        return MemorySubstrate(setup)
    registered = ", ".join(sorted(_REGISTERED)) or "(none)"
    raise SubstrateUnavailable(
        f"unknown substrate {name!r}; built in: {', '.join(_BUILTIN)}; "
        f"registered: {registered}. A vertical's tier is registered by loading "
        f"its plugin (--plugin, QA_ORCHESTRATOR_PLUGINS, or an entry point)")


def observe(substrate: Substrate, entity: str) -> str:
    """`substrate.state(entity)`, refused if it is not in `PRESENCE`.

    This is the seam. A tier answering `gone` or `None` would otherwise reach
    the comparator as a plain mismatch -- *expected absent, got gone* -- which
    reads as an injection that did not take, when it is actually a tier speaking
    outside the shared vocabulary. Those are different faults with different
    owners, and the harness exists to keep them apart.
    """
    got = substrate.state(entity)
    if got not in PRESENCE:
        raise SubstrateUnavailable(
            f"{getattr(substrate, 'name', type(substrate).__name__)} reported "
            f"{got!r} for {entity!r}; state() must return one of "
            f"{', '.join(PRESENCE)}")
    return got


def set_value(substrate: Substrate, entity: str, value: Any) -> None:
    """Move a value through whichever spelling the tier implements.

    `set_value` is the protocol's word. `set_reading` is what every tier written
    against 0.2.x implements, and those tiers are on disk and published. Taking
    one and refusing the other would break them for a rename.
    """
    method = getattr(substrate, "set_value", None) or getattr(substrate, "set_reading", None)
    if method is None:
        raise SubstrateUnavailable(
            f"{getattr(substrate, 'name', type(substrate).__name__)} implements "
            f"neither set_value nor set_reading, so no value can be moved on it")
    method(entity, value)
