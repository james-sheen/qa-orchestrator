"""The real-firmware tier: inject into a running QEMU through its QMP socket.

**Scope of this build, stated so it is not mistaken for more.** This backend
*attaches* to an already-running instance whose QMP socket is given in the
scenario. It does not boot one. Owning the boot recipe -- image build id, machine
type, FRU provisioning to instantiate the baseboard -- is real work that belongs
here eventually, and pretending to have it would be worse than not having it.

**What is and is not exercised.** The QMP conversation below is tested against a
fake socket that speaks the protocol, so the greeting, the capabilities handshake,
the command framing, the event interleaving and the error path are all covered.

That sentence stood here from the first release and was **false**: no such test
existed, in this build or in the `backends/` package this module came from. It
was written as a description of what the module deserved and read afterwards as
a record of what it had. It is true as of 2026-09-14, and the way it stopped
being a claim about intentions is that somebody ran the tier against a real
QEMU 10.2.1 and found out what it did.

The integration IS now exercised too, but not from here: a rig is not a test
suite, and the measurements it produced are recorded in `set_reading` below.

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


def _hashable(values):
    """The set, or None if these cannot form one.

    A QOM property need not answer with a scalar, and a `TypeError` from a set
    literal is a traceback where *this check has nothing to say* belongs.
    """
    try:
        return set(values)
    except TypeError:                                          # pragma: no cover
        return None


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
        #: (path, property, requested, stored) for every write this session, so
        #: the question *is this property following?* can be asked of more than
        #: one write. It cannot be answered by one.
        self._writes: list[tuple[str, str, float, object]] = []

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

        **WHAT ARRIVES IS NOT WHAT WAS WRITTEN, and the mock does not tell you
        that.** Measured against a real bletchley guest under QEMU 10.2.1, a
        tmp421 on the baseboard:

            written    QOM stores    firmware reports    delta
            22.0000       21.9960            21.9380    -0.0620
            30.0000       29.9960            29.9380    -0.0620
            37.5000       37.4960            37.4380    -0.0620
            41.2500       41.2460            41.1880    -0.0620
            55.0000       54.9960            54.9380    -0.0620

        Two lossy steps -- the property rounds, and the guest's driver quantises
        what it reads back out of the register. The offset is constant, so a
        scenario CAN compensate; what it cannot do is assume. The mock tier
        round-trips a driven reading exactly, so anything written against it and
        moved here arrives silently wrong. No shipped scenario is affected: the
        format cannot assert a reading at all today, only a presence state. This
        is recorded so that the day it can, nobody discovers the offset the way
        it was discovered here.

        **The write is read back.** Not to check the arithmetic above -- that
        loss is expected -- but because a property can exist, accept `qom-set`
        and ignore it, and an injection nobody confirmed is the case this whole
        harness exists to rule out: a broken injector and a blind referee look
        identical from the outside.

        **One write cannot tell you that, and the first version of this check
        thought it could.** It refused when the register did not move, which is
        wrong the moment the register already holds the quantised image of what
        you asked for: set 22.0 twice and the second write changes nothing and
        landed perfectly. A real guest refused a valid injection that way within
        a minute of the rule being written, and seventeen green tests here had
        not, because the fake moved by a fixed step on every write.

        So the question is asked across the session instead, and with no
        threshold in it: a property that is following turns distinct requests
        into distinct stored values, whatever it rounds them to. More than one
        value asked for and exactly one ever stored is a property that is not
        listening. The first repair of this did compute a tolerance -- twice the
        largest rounding seen -- and it was wrong in the one case it existed
        for, because a property that answers 0 to everything reports a rounding
        of the whole requested value and raises its own bar out of reach.

        What it cannot separate: two requests that quantise onto the same stored
        value, which on this machine means two requests closer together than the
        property's own resolution. That is a refusal rather than a silent pass,
        and it is the narrow end of the trade.
        """
        mapping = self.paths.get(entity)
        if not mapping:
            raise SubstrateUnavailable(
                f"no QOM path for {entity!r}. Add it to machine.entity_paths as "
                f"{{{entity}: {{path: /machine/..., property: temperature0, "
                f"scale: 1000}}}} -- which device backs which sensor cannot be "
                f"derived here, and a guess would drive the wrong register.")
        scale = mapping.get("scale", 1)
        path, prop = mapping["path"], mapping["property"]
        wanted = int(float(value) * scale)

        self._client.command("qom-set", path=path, property=prop, value=wanted)
        after = self._read_back(path, prop, entity)
        self._writes.append((path, prop, wanted, after))

        session = [(w, a) for p, r, w, a in self._writes if (p, r) == (path, prop)]
        asked = {w for w, _ in session}
        stored = _hashable({a for _, a in session})
        if len(asked) > 1 and stored is not None and len(stored) == 1:
            raise SubstrateUnavailable(
                f"{path}.{prop} has read {after!r} for {entity!r} after every "
                f"one of {sorted(asked)!r}. A property that is following turns "
                f"different requests into different values, whatever it rounds "
                f"them to, so this one is accepting `qom-set` and discarding it "
                f"-- and a phase driven through it would grade the substrate's "
                f"old state as its new one. Check that the property is the one "
                f"backing this sensor.")

    def _read_back(self, path: str, prop: str, entity: str):
        """The register's value, or a refusal saying the injection is unverifiable.

        A tier that cannot confirm its own injection is worse than one that
        cannot inject: the second is reported, and the first is graded.
        """
        try:
            return self._client.command("qom-get", path=path, property=prop)
        except QmpError as error:
            raise SubstrateUnavailable(
                f"{path}.{prop} cannot be read back, so an injection on "
                f"{entity!r} cannot be confirmed to have landed and this run "
                f"would be grading an unverified change: {error}") from error

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
