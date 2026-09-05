"""Words every module shares, and the errors every module raises.

Nothing in this file -- or anywhere under `qa_orchestrator/` outside
`verticals/` -- names a domain. `tests/test_domain_free.py` checks that
structurally: the core may not import a vertical, and may not carry as a string
constant any name a vertical registers.
"""

from __future__ import annotations

#: The three ways a thing that SHOULD be there can actually be: gone, there but
#: not reporting a value, there and reporting one. A boolean would collapse the
#: middle one, and the middle one is where the interesting faults live.
#:
#: Shared so a substrate's `state()` and a scenario's `expect.substrate` cannot
#: spell it two ways. `substrate.observe()` refuses a value outside it.
PRESENCE = ("absent", "disabled", "reading")
ABSENT, DISABLED, READING = PRESENCE


class HarnessError(RuntimeError):
    """The harness cannot proceed, and says why rather than degrading."""


class SubstrateUnavailable(HarnessError):
    """This substrate tier cannot run here, or cannot do what was asked."""


class RefereeUnavailable(HarnessError):
    """The referee cannot be run. Distinct from any verdict it could return."""


class CaptureFailed(HarnessError):
    """The referee's capture step produced nothing that can be judged."""


class PluginError(HarnessError):
    """A plugin the caller named could not be loaded or refused to register."""


class RegistrationError(ValueError):
    """A registry refused an entry: a duplicate name or an invalid definition."""


class ScenarioError(ValueError):
    """A scenario that cannot be run as written. Always names where."""


#: The 0.2.x name, kept so a vertical written against it still imports.
BackendUnavailable = SubstrateUnavailable
