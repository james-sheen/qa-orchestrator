"""The three BMC tiers, moved from the 0.2.x `backends/` package.

They are the first vertical's, not the harness's: a mock BMC, a QEMU machine
running real firmware, and a lab bench. Nothing in the core knows their names --
`bmc.register()` puts them in the substrate registry, and a build without this
module says so rather than pretending.

**The factories are lazy on purpose.** `mock.py` raises at IMPORT time when
`bmc-sensor-audit` is absent, so a `TIERS` holding the classes themselves would
make importing this module raise, and `bmc.register()` catches `ImportError`
only -- the vertical would fail to load at all on a machine without the referee.
Deferring to construction keeps the old behaviour: a scenario may NAME a tier
this build cannot run, and finds out when it tries to build one, loudly.
"""

from __future__ import annotations

from typing import Any, Dict


def _mock(setup: dict) -> Any:
    from .mock import MockBackend
    return MockBackend(setup)


def _qemu(setup: dict) -> Any:
    from .qemu import QemuBackend
    return QemuBackend(setup)


def _testbed(setup: dict) -> Any:
    from .testbed import TestbedBackend
    return TestbedBackend(setup)


#: Read by `bmc.register()`. The names a `qa-scenario/1` file may put in
#: `backend:` and a `/2` file in `substrate:`.
TIERS: Dict[str, Any] = {"mock": _mock, "qemu": _qemu, "testbed": _testbed}
