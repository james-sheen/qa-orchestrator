"""The real-firmware tier: inject into a running QEMU through its QMP socket.

**Scope of this build, stated so it is not mistaken for more.** This backend
*attaches* to an already-running instance whose QMP socket is given in the
scenario. It does not boot one. Owning the boot recipe -- image build id, machine
type, FRU provisioning to instantiate the baseboard -- is real work that belongs
here eventually, and pretending to have it would be worse than not having it.

**What is and is not exercised.** The QMP conversation below is tested against a
fake socket that speaks the protocol, so the greeting, the capabilities handshake,
the command framing and the error path are all covered. What is *not* covered is
any real QEMU: there is none on the machine this was written on. So the wire format
is verified and the integration is not, and those are different claims.

The injection verb is `qom-set` on a device property, which is how the shipped
stuck-at experiment drove a sensor: freezing a register through the monitor. That
is an experiment, not a sensor failing on its own, and a scenario using this tier
inherits that caveat.
"""

from __future__ import annotations

import json
import socket

from ...vocabulary import SubstrateUnavailable


class QmpError(RuntimeError):
    """QEMU refused a command, quoting what it said."""


class QmpClient:
    """The smallest QMP client that can drive a sensor.

    Line-delimited JSON over a socket: a greeting, then `qmp_capabilities`, then
    commands. Kept here rather than taking a dependency, because this tier has to
    run on a bring-up bench where nothing is provisioned -- the same constraint
    the audit tool holds itself to.
    """

    def __init__(self, address: str, *, timeout: float = 10.0) -> None:
        self.address, self.timeout = address, timeout
        self._sock: socket.socket | None = None
        self._reader = None

    def connect(self) -> dict:
        if ":" in self.address and not self.address.startswith("/"):
            host, _, port = self.address.rpartition(":")
            self._sock = socket.create_connection((host, int(port)), self.timeout)
        else:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect(self.address)
        self._reader = self._sock.makefile("r", encoding="utf-8")

        greeting = self._read()
        if "QMP" not in greeting:
            raise QmpError(f"expected a QMP greeting, got {greeting!r}")
        # Required before any other command; QEMU rejects everything until it
        # has been sent, with an error that does not mention the handshake.
        self.command("qmp_capabilities")
        return greeting

    def _read(self) -> dict:
        while True:
            line = self._reader.readline()
            if not line:
                raise QmpError("QEMU closed the connection")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Asynchronous events interleave with replies and are not replies.
            if "event" in message:
                continue
            return message

    def command(self, execute: str, **arguments) -> dict:
        payload = {"execute": execute}
        if arguments:
            payload["arguments"] = arguments
        self._sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        reply = self._read()
        if "error" in reply:
            raise QmpError(f"{execute} failed: {reply['error'].get('desc', reply['error'])}")
        return reply.get("return", {})

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock, self._reader = None, None


class QemuBackend:
    name = "qemu"

    def __init__(self, machine: dict) -> None:
        self.target = machine.get("target")
        self.qmp_address = machine.get("qmp")
        # Both spellings, for the same reason mock.py takes both: published
        # scenarios say `sensor_paths`.
        self.paths: dict[str, dict] = (machine.get("entity_paths")
                                       or machine.get("sensor_paths") or {})
        if not self.target or not self.qmp_address:
            raise SubstrateUnavailable(
                "the qemu backend needs machine.target (the Redfish base URL of "
                "the running instance) and machine.qmp (its QMP socket path or "
                "host:port).\n\n"
                "This build attaches to a running instance; it does not boot one. "
                "Owning the boot recipe -- image build id, machine type, FRU "
                "provisioning -- is not implemented, and claiming it would be "
                "worse than not having it.")
        self._client: QmpClient | None = None

    def start(self) -> str:
        self._client = QmpClient(self.qmp_address)
        self._client.connect()
        return self.target

    def stop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def set_reading(self, entity: str, value: float) -> None:
        """Drive a sensor by setting the device property behind it.

        The mapping from sensor name to QOM path and property is scenario data,
        not something this build can derive: which device backs which sensor is a
        property of the machine model, and guessing it would drive the wrong
        register and report the result as a firmware fact.
        """
        mapping = self.paths.get(entity)
        if not mapping:
            raise SubstrateUnavailable(
                f"no QOM path for {entity!r}. Add it to machine.entity_paths as "
                f"{{{entity}: {{path: /machine/..., property: temperature0, "
                f"scale: 1000}}}} -- which device backs which sensor cannot be "
                f"derived here, and a guess would drive the wrong register.")
        scale = mapping.get("scale", 1)
        self._client.command("qom-set", path=mapping["path"],
                             property=mapping["property"],
                             value=int(float(value) * scale))

    def _unsupported(self, verb: str) -> None:
        raise SubstrateUnavailable(
            f"the qemu tier cannot {verb} a sensor: the firmware decides what it "
            f"exposes, and there is no monitor command that removes one from the "
            f"Redfish tree. Run that phase on the mock tier, or model it as a "
            f"reading driven out of range.")

    def remove(self, entity: str) -> None:
        self._unsupported("remove")

    def disable(self, entity: str) -> None:
        self._unsupported("disable")

    def fail(self, path: str, status: int) -> None:
        raise SubstrateUnavailable(
            "the qemu tier cannot make a subtree return an HTTP status; that is a "
            "property of the webserver, not the machine. Run that phase on mock.")

    def state(self, entity: str) -> str:
        raise SubstrateUnavailable(
            "the qemu tier cannot report a sensor's state without walking it, and "
            "walking is the referee's job. Use expect.audit rather than "
            "expect.firmware on this tier.")
