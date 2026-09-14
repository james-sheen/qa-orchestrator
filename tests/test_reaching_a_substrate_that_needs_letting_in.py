"""A handle is not enough to reach a real machine, and it used to be all there was.

**The defect this file was written for.** A scenario was pointed at a real BMC
under QEMU. The tier drove its registers correctly -- that part was verified on
the machine -- and the referee captured nothing, twenty-eight times, because
every real BMC ships a self-signed certificate and wants a credential and the
harness could express neither. The profile's capture builder took a target and
an output path; the scenario format's top-level keys are a closed set; the only
field a scenario controlled was the target, and putting credentials in the URL
made the referee resolve `root:secret@host` as a hostname. So the tier could
inject into real firmware and the referee could never read it.

The repair is two optional members that answer a question the old pair did not
ask. A tier may describe how a referee gets IN (`Substrate.access`); a profile
may turn that description into its own arguments (`Tool.access_argv`). The core
carries the value between them and never reads it -- which is the property the
first class below is about, because a harness that learned what a credential is
would have learned one domain's idea of one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from qa_orchestrator import referee, substrate
from qa_orchestrator.verticals.bmc import BMC_SENSOR_AUDIT as TOOL
from qa_orchestrator.verticals.bmc_tiers.access import access_from, refuse_access
from qa_orchestrator.vocabulary import SubstrateUnavailable

SENTINEL = object()


def _tool(**kwargs):
    return referee.Tool(
        name="t", executable="t", install_hint="pip install t", modes=("m",),
        capture_argv=lambda target, out: ("grab", target, str(out)),
        judge_argv=lambda mode, configs, captures: (mode,), **kwargs)


@pytest.fixture
def recorded(monkeypatch, tmp_path):
    """Every argv `capture` builds, with the tool's file already on disk."""
    seen = []

    def fake_run(argv, timeout):
        seen.append(list(argv))
        # The tool writes where it was told, which is the argument `capture_argv`
        # put there -- not the last word, because access arguments follow it.
        (tmp_path / "c.json").write_text("{}")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(referee, "executable", lambda tool: "/bin/t")
    monkeypatch.setattr(referee, "_run", fake_run)
    return seen


class TestTheCoreCarriesItWithoutReadingIt:
    def test_the_description_reaches_the_profile_unread(self, recorded, tmp_path):
        """Identity, not equality. Anything the core copied or coerced on the way
        would be the core having an opinion about what a credential is."""
        got = {}
        tool = _tool(access_argv=lambda access: got.setdefault("access", access) and ())
        referee.capture("handle", tmp_path / "c.json", tool=tool, access=SENTINEL)
        assert got["access"] is SENTINEL

    def test_the_arguments_are_appended_not_merged(self, recorded, tmp_path):
        tool = _tool(access_argv=lambda access: ("--in", access))
        referee.capture("handle", tmp_path / "c.json", tool=tool, access="key")
        assert recorded[0] == ["/bin/t", "grab", "handle", str(tmp_path / "c.json"),
                               "--in", "key"]

    def test_a_profile_declaring_none_gets_what_it_got_before(self, recorded, tmp_path):
        """The compatibility property. A profile written before this existed must
        not acquire arguments because a tier started describing itself."""
        referee.capture("handle", tmp_path / "c.json", tool=_tool(), access={"u": "x"})
        assert recorded[0] == ["/bin/t", "grab", "handle", str(tmp_path / "c.json")]

    def test_a_tier_describing_nothing_appends_nothing(self, recorded, tmp_path):
        tool = _tool(access_argv=lambda access: ("--in",))
        referee.capture("handle", tmp_path / "c.json", tool=tool, access=None)
        assert recorded[0] == ["/bin/t", "grab", "handle", str(tmp_path / "c.json")]

    def test_a_tier_without_the_member_is_still_a_tier(self):
        class Old:
            name = "old"

        assert substrate.access_of(Old()) is None

    def test_a_tier_that_refuses_to_describe_itself_is_not_swallowed(self):
        """`None` means *nothing needed*, which is the opposite of *I cannot say*."""
        class Refusing:
            name = "refusing"

            def access(self):
                raise SubstrateUnavailable("no")

        with pytest.raises(SubstrateUnavailable):
            substrate.access_of(Refusing())

    def test_the_core_names_no_flag_of_any_domain(self):
        """The property the whole shape exists to keep."""
        import pathlib
        for module in ("referee.py", "substrate.py", "run.py"):
            text = (pathlib.Path(__file__).resolve().parents[1] / "src"
                    / "qa_orchestrator" / module).read_text()
            for flag in ("--username", "--password", "--insecure", "--cafile",
                         "--pin-sha256"):
                assert flag not in text, f"{module} names {flag}"


class TestTheProfileTurnsItIntoItsOwnFlags:
    @pytest.mark.parametrize("access,expected", [
        ({"username": "root"}, ["--username", "root"]),
        ({"username": "u", "password_env": "P"},
         ["--username", "u", "--password-env", "P"]),
        ({"tls": "insecure"}, ["--insecure"]),
        ({"tls": {"cafile": "/ca.pem"}}, ["--cafile", "/ca.pem"]),
        ({"tls": {"pin_sha256": "ab"}}, ["--pin-sha256", "ab"]),
        ({"timeout": 30}, ["--timeout", "30"]),
        ({}, []),
    ], ids=["user", "user+env", "insecure", "cafile", "pin", "timeout", "empty"])
    def test_each_key(self, access, expected):
        assert list(TOOL.access_argv(access)) == expected

    def test_the_whole_command_is_the_one_that_reaches_a_real_machine(self):
        """Measured against a live guest before it was written here: this exact
        form returned 3 chassis and 28 sensors where the form without it
        returned `CERTIFICATE_VERIFY_FAILED` and exit 2."""
        argv = list(TOOL.capture_argv("https://127.0.0.1:2443", Path("/w/walk.json")))
        argv += list(TOOL.access_argv(
            {"username": "root", "password_env": "BMCPW", "tls": "insecure"}))
        assert argv == ["capture", "--target", "https://127.0.0.1:2443",
                        "--out", "/w/walk.json", "--print-digest",
                        "--username", "root", "--password-env", "BMCPW", "--insecure"]

    def test_the_value_never_enters_argv(self):
        """`--password-env` and never `--password`, which the tool's own help
        calls discouraged because argv is readable by any process on the host."""
        assert "--password" not in TOOL.access_argv({"username": "u", "password_env": "P"})


class TestWhatTheReaderRefuses:
    def test_a_password_value_in_a_scenario(self):
        with pytest.raises(SubstrateUnavailable, match="lives in a repository"):
            access_from({"password": "0penBmc", "username": "root"})

    def test_half_a_credential(self):
        with pytest.raises(SubstrateUnavailable, match="half a credential"):
            access_from({"password_env": "P"})

    def test_a_bare_tls_word_that_is_not_insecure(self):
        with pytest.raises(SubstrateUnavailable, match="as a bare word"):
            access_from({"tls": "verify"})

    def test_two_ways_to_treat_one_certificate(self):
        """The referee refuses a command that asks to verify and not to verify at
        once; a shape that cannot express the contradiction cannot produce it."""
        with pytest.raises(SubstrateUnavailable, match="not several"):
            access_from({"tls": {"cafile": "/ca.pem", "pin_sha256": "ab"}})

    def test_an_unknown_tls_key(self):
        with pytest.raises(SubstrateUnavailable, match="unknown key"):
            access_from({"tls": {"verify": True}})

    def test_only_the_access_keys_are_taken(self):
        """The rest of `machine:` belongs to the tier."""
        assert access_from({"target": "https://h", "qmp": "h:1", "username": "u"}) == {
            "username": "u"}

    def test_a_tier_that_reads_no_credential_says_so_rather_than_ignoring_it(self):
        """A scenario carrying a credential is one whose author believes it is
        being used."""
        with pytest.raises(SubstrateUnavailable, match="would be silently unused"):
            refuse_access({"sensors": [], "username": "root"}, "mock")

    def test_a_tier_that_reads_none_is_fine_without_one(self):
        assert refuse_access({"sensors": []}, "mock") is None
