"""The QMP conversation, against a socket that answers.

**This file is the sentence the module claimed.** `qemu.py` said, from its first
release, that its QMP conversation was *tested against a fake socket that speaks
the protocol*. No such test existed -- not here and not in the `backends/`
package the module was moved from, whose own test file had one case about the
tier and it was that the tier refuses without a target. The sentence described
what the module deserved and was read afterwards as a record of what it had.

The socket below is real: a thread on loopback speaking line-delimited JSON, so
what is exercised is the client's own framing and reading rather than a mock of
it. What it still cannot do is stand in for QEMU, and the tier's docstring keeps
that line -- the wire format is verified here, the integration was verified on a
rig, and those are different claims that were once made by one sentence.
"""

from __future__ import annotations

import json
import socket
import threading

import pytest

from qa_orchestrator.verticals.bmc_tiers.qemu import (QemuBackend, QmpClient,
                                                      QmpError)
from qa_orchestrator.vocabulary import SubstrateUnavailable

GREETING = {"QMP": {"version": {"qemu": {"major": 10, "minor": 2, "micro": 1}},
                    "capabilities": []}}


class FakeQemu:
    """A socket that speaks enough QMP to drive a sensor.

    `registers` is the machine state: a `qom-set` writes into it and a `qom-get`
    reads out of it, so a test can express the case that matters -- a property
    that accepts the command and discards the value.
    """

    def __init__(self, *, greeting=GREETING, registers=None, refuse=(),
                 events_before_reply=0, drop_after=None, discard_writes=False):
        self.greeting = greeting
        self.registers = dict(registers or {})
        self.refuse = set(refuse)
        self.events_before_reply = events_before_reply
        self.drop_after = drop_after
        self.discard_writes = discard_writes
        self.seen: list[dict] = []
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.address = "127.0.0.1:%d" % self._server.getsockname()[1]

    def __enter__(self):
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._server.close()

    def _key(self, arguments):
        return (arguments.get("path"), arguments.get("property"))

    def _serve(self):
        try:
            connection, _ = self._server.accept()
        except OSError:                                        # pragma: no cover
            return
        with connection, connection.makefile("rw", encoding="utf-8") as stream:
            if self.greeting is not None:
                stream.write(json.dumps(self.greeting) + "\n")
                stream.flush()
            for line in stream:
                message = json.loads(line)
                self.seen.append(message)
                if self.drop_after is not None and len(self.seen) > self.drop_after:
                    return
                for _ in range(self.events_before_reply):
                    stream.write(json.dumps(
                        {"event": "RTC_CHANGE", "data": {"offset": 1}}) + "\n")
                # A line that is not JSON at all. The client skips it rather
                # than dying, because a monitor is allowed to be chatty.
                stream.write("not json\n")
                stream.write(json.dumps(self._answer(message)) + "\n")
                stream.flush()

    def _answer(self, message):
        execute, arguments = message["execute"], message.get("arguments", {})
        if execute in self.refuse:
            return {"error": {"class": "GenericError",
                              "desc": f"{execute} is not available"}}
        if execute == "qom-get":
            return {"return": self.registers.get(self._key(arguments), 0)}
        if execute == "qom-set":
            if not self.discard_writes:
                self.registers[self._key(arguments)] = arguments["value"]
            return {"return": {}}
        return {"return": {}}


def _backend(fake, **paths):
    return QemuBackend({"target": "https://bmc.invalid", "qmp": fake.address,
                        "entity_paths": paths or {
                            "Inlet": {"path": "/machine/unattached/device[0]",
                                      "property": "temperature0", "scale": 1000}}})


class TestTheConversation:
    def test_the_handshake_is_sent_before_anything_else(self):
        with FakeQemu() as fake:
            client = QmpClient(fake.address)
            greeting = client.connect()
            client.command("qom-get", path="/p", property="x")
            client.close()
        assert greeting["QMP"]["version"]["qemu"]["major"] == 10
        assert [m["execute"] for m in fake.seen] == ["qmp_capabilities", "qom-get"]

    def test_a_greeting_that_is_not_one_is_refused(self):
        with FakeQemu(greeting={"hello": "i am not qemu"}) as fake:
            with pytest.raises(QmpError, match="expected a QMP greeting"):
                QmpClient(fake.address).connect()

    def test_an_error_reply_is_raised_with_what_qemu_said(self):
        with FakeQemu(refuse={"qom-set"}) as fake:
            client = QmpClient(fake.address)
            client.connect()
            with pytest.raises(QmpError, match="qom-set failed: qom-set is not available"):
                client.command("qom-set", path="/p", property="x", value=1)

    def test_events_arriving_before_a_reply_are_not_read_as_the_reply(self):
        """They interleave on a real monitor and they are not answers."""
        with FakeQemu(events_before_reply=3, registers={("/p", "x"): 41}) as fake:
            client = QmpClient(fake.address)
            client.connect()
            assert client.command("qom-get", path="/p", property="x") == 41

    def test_a_closed_connection_is_a_refusal_not_a_hang(self):
        with FakeQemu(drop_after=1) as fake:
            client = QmpClient(fake.address)
            client.connect()
            with pytest.raises(QmpError, match="QEMU closed the connection"):
                client.command("qom-get", path="/p", property="x")

    def test_a_path_is_a_unix_socket_and_a_colon_is_a_port(self, tmp_path):
        """The branch that decides which, exercised on a real unix socket."""
        path = tmp_path / "qmp.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        server.listen(1)

        def serve():
            connection, _ = server.accept()
            with connection, connection.makefile("rw", encoding="utf-8") as stream:
                stream.write(json.dumps(GREETING) + "\n")
                stream.flush()
                stream.readline()
                stream.write(json.dumps({"return": {}}) + "\n")
                stream.flush()

        threading.Thread(target=serve, daemon=True).start()
        try:
            client = QmpClient(str(path))
            assert "QMP" in client.connect()
            client.close()
        finally:
            server.close()


class TestDrivingASensor:
    def test_the_value_is_scaled_and_written(self):
        with FakeQemu() as fake:
            backend = _backend(fake)
            backend.start()
            backend.set_reading("Inlet", 22.0)
            backend.stop()
        written = [m for m in fake.seen if m["execute"] == "qom-set"]
        assert len(written) == 1
        assert written[0]["arguments"]["value"] == 22000
        assert written[0]["arguments"]["property"] == "temperature0"

    def test_the_write_is_read_back(self):
        with FakeQemu() as fake:
            backend = _backend(fake)
            backend.start()
            backend.set_reading("Inlet", 22.0)
            backend.stop()
        assert [m["execute"] for m in fake.seen] == [
            "qmp_capabilities", "qom-set", "qom-get"]

    def test_a_property_that_accepts_the_write_and_discards_it_is_refused(self):
        """The case a read-back exists for: an injection that did not take.

        QEMU answers `qom-set` with a return rather than an error, so nothing
        about the exchange says the value was ignored. Without this the phase
        would be graded against the substrate's old state.

        It takes TWO writes to know. One write that changes nothing is the
        ordinary case of asking for a value the register already holds.
        """
        with FakeQemu(discard_writes=True) as fake:
            backend = _backend(fake)
            backend.start()
            backend.set_reading("Inlet", 22.0)          # nothing to compare yet
            with pytest.raises(SubstrateUnavailable,
                               match=r"read 0 .*after every one of \[22000, 30000\]"):
                backend.set_reading("Inlet", 30.0)

    def test_the_same_value_written_twice_is_not_a_discarded_write(self):
        """THE CASE A REAL GUEST FOUND, one minute after the first rule was written.

        The register quantises, so it holds 21996 for a requested 22000. Ask for
        22.0 again and nothing moves -- and the first version of this check read
        that as a property ignoring writes and refused a perfectly good
        injection. Seventeen tests here were green, because the fake moved by a
        fixed step on every write and never sat still for an honest reason.
        """
        class Quantising(FakeQemu):
            """Minus four, which is what a real tmp421 did to 22000."""

            def _answer(self, message):
                answer = super()._answer(message)
                if message["execute"] == "qom-set":
                    key = self._key(message["arguments"])
                    self.registers[key] -= 4
                return answer

        with Quantising() as fake:
            backend = _backend(fake)
            backend.start()
            backend.set_reading("Inlet", 22.0)
            backend.set_reading("Inlet", 22.0)          # must not raise
            backend.stop()
        assert fake.registers[("/machine/unattached/device[0]", "temperature0")] == 21996

    def test_quantisation_is_not_an_error(self):
        """A real tmp421 returns 21996 for 22000 and that is the machine, not a fault."""
        class Lossy(FakeQemu):
            def _answer(self, message):
                answer = super()._answer(message)
                if message["execute"] == "qom-set":
                    self.registers[self._key(message["arguments"])] -= 4
                return answer

        with Lossy() as fake:
            backend = _backend(fake)
            backend.start()
            backend.set_reading("Inlet", 22.0)          # must not raise
            backend.stop()
        assert fake.registers[("/machine/unattached/device[0]", "temperature0")] == 21996

    def test_a_register_that_cannot_be_read_back_refuses_the_injection(self):
        with FakeQemu(refuse={"qom-get"}) as fake:
            backend = _backend(fake)
            backend.start()
            with pytest.raises(SubstrateUnavailable, match="cannot be read back"):
                backend.set_reading("Inlet", 22.0)

    def test_an_unmapped_entity_says_what_to_add(self):
        with FakeQemu() as fake:
            backend = _backend(fake)
            backend.start()
            with pytest.raises(SubstrateUnavailable, match="no QOM path for 'Outlet'"):
                backend.set_reading("Outlet", 22.0)


class TestWhatThisTierWillNotDo:
    """Each refusal, because a tier that no-ops is worse than one that refuses."""

    @pytest.mark.parametrize("call,match", [
        (lambda b: b.remove("Inlet"), "cannot remove a sensor"),
        (lambda b: b.disable("Inlet"), "cannot disable a sensor"),
        (lambda b: b.fail("/redfish/v1", 500), "cannot make a subtree return"),
        (lambda b: b.state("Inlet"), "cannot report a sensor's state"),
    ], ids=["remove", "disable", "fail", "state"])
    def test_it_refuses_rather_than_pretending(self, call, match):
        with FakeQemu() as fake:
            backend = _backend(fake)
            backend.start()
            with pytest.raises(SubstrateUnavailable, match=match):
                call(backend)

    def test_it_will_not_pretend_to_boot_one(self):
        with pytest.raises(SubstrateUnavailable, match="does not boot one"):
            QemuBackend({"target": "https://bmc.invalid"})
