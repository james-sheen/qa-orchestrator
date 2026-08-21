"""The zero-hardware tier: the audit tool's own mock BMC, driven in process.

**On importing from the tool under test.** `referee.py` may not import
`bmc_sensor_audit` at all, because it reads verdicts and would otherwise be
grading with the answer key. This file may, and the distinction is the whole
design: `MockBMC` is a fake *machine*, not the referee. It stands in for the thing
being audited, not the thing doing the auditing. Using the tool's own mock here
means the machine this tier serves is the same one the tool's suite is written
against -- so a disagreement is about the injection, never about two mocks
drifting apart.
"""

from __future__ import annotations

from . import BackendUnavailable

try:
    from bmc_sensor_audit.testing.mock_redfish import MockBMC, MockSensor, serve
except ImportError as error:                                     # pragma: no cover
    raise BackendUnavailable(
        "the mock backend needs bmc-sensor-audit installed for its MockBMC: "
        "pip install 'bmc-sensor-audit[detect]'") from error


class MockBackend:
    name = "mock"

    def __init__(self, machine: dict) -> None:
        sensors = machine.get("sensors") or []
        if not sensors:
            raise BackendUnavailable(
                "the mock backend needs machine.sensors in the scenario -- it has "
                "no firmware to read a sensor list from, so the scenario supplies "
                "it. An empty machine would make every declared sensor absent and "
                "every phase pass for that reason.")
        self._bmc = MockBMC(shape=machine.get("shape", "sensors"))
        for spec in sensors:
            if isinstance(spec, str):
                spec = {"name": spec}
            fields = {k: v for k, v in spec.items() if k != "name"}
            self._bmc.sensors.append(MockSensor(name=spec["name"], **fields))
        self._context = None
        self._url: str | None = None

    def start(self) -> str:
        if self._url is None:
            self._context = serve(self._bmc)
            self._url = self._context.__enter__()
        return self._url

    def stop(self) -> None:
        if self._context is not None:
            self._context.__exit__(None, None, None)
            self._context, self._url = None, None

    # -- injections -------------------------------------------------------
    # Each maps to a documented condition the referee already has an opinion
    # about, so the harness cannot ask a question the tool cannot answer.

    def remove(self, sensor: str) -> None:
        self._require(sensor)
        self._bmc.remove(sensor)
        self._restart()

    def disable(self, sensor: str) -> None:
        self._require(sensor)
        self._bmc.disable(sensor)
        self._restart()

    def fail(self, path: str, status: int) -> None:
        self._bmc.fail[path] = int(status)
        self._restart()

    def set_reading(self, sensor: str, value: float) -> None:
        found = self._require(sensor)
        found.reading = float(value)
        self._restart()

    # -- observation ------------------------------------------------------

    def state(self, sensor: str) -> str:
        for candidate in self._bmc.sensors:
            if candidate.name == sensor:
                if candidate.reading is None or candidate.state != "Enabled":
                    return "disabled"
                return "reading"
        return "absent"

    # -- internals --------------------------------------------------------

    def _require(self, sensor: str) -> MockSensor:
        """Refuse an injection against a sensor that is not there.

        A typo in a scenario would otherwise perturb nothing and let the phase
        pass, which is indistinguishable from the tool failing to notice a real
        fault -- the exact confusion this harness exists to remove.
        """
        for candidate in self._bmc.sensors:
            if candidate.name == sensor:
                return candidate
        known = ", ".join(sorted(s.name for s in self._bmc.sensors)) or "(none)"
        raise BackendUnavailable(
            f"no sensor named {sensor!r} on this machine; it has: {known}")

    def _restart(self) -> None:
        """Re-serve so the next walk sees the change.

        `serve` snapshots the routes when it binds, so a mutation after start is
        invisible until the server is rebuilt. Found by an injection that took in
        the object and never appeared in a walk -- the failure mode this backend
        exists to make impossible.
        """
        if self._url is not None:
            self.stop()
            self.start()
