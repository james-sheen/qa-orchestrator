"""What `capture` returns, and the documented action it used to make impossible.

**The defect this file was written for.** The referee's `capture` subcommand exits
`2` for two different facts: it could not reach the machine, and it reached the
machine while one subtree answered with an error. The second is a walk the tool
deliberately writes and keeps, because knowing WHICH subtree failed is the point.
This orchestrator raised on any non-zero, so the scenario schema's `fail` action --
*make a subtree answer with an HTTP status (a partial walk)* -- aborted the run
before the referee could be asked anything.

It had never worked. No shipped scenario used the action and no test exercised it,
so nothing in this repository could have noticed. Found by running one.

**The instrument that fixes it arrived in the referee at 0.1.1.** `validate-walk`
answers a question about the ARTIFACT -- is this a well-formed `walk/1` -- which is
a different question from *did the run go well*, and it is the one that separates a
partial capture from a failed one. `--print-digest` came with it, and gives every
walk a content handle that outlives the workdir a clean run deletes.

The branch tests below fake the subprocess, because the point is which exit code
and which file state produce which outcome, and a real tool can only be persuaded
into some of those combinations. The two at the end use the real tool, so the
faking cannot drift from what the tool actually prints.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from qa_orchestrator import referee

WALK = {"format": "bmc-sensor-audit/walk/1", "sensors":
        [{"name": "Inlet", "reading": 21.0}], "errors": []}
PARTIAL = {**WALK, "errors": [["/redfish/v1/Chassis/1/Sensors", "HTTP 500"]]}
DIGEST = "sha256:" + "a" * 64


class _Fake:
    """Stands in for the two subprocess calls `capture` makes.

    `writes` is what lands on disk before the tool exits, so a test can express
    the case that matters most: a non-zero exit that still produced a usable file.
    """

    def __init__(self, *, capture_rc=0, capture_out="", validate_rc=0,
                 validate_err="", writes=WALK):
        self.capture_rc, self.capture_out = capture_rc, capture_out
        self.validate_rc, self.validate_err = validate_rc, validate_err
        self.writes = writes
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[1] == "capture":
            if self.writes is not None:
                Path(argv[argv.index("--out") + 1]).write_text(
                    json.dumps(self.writes))
            return subprocess.CompletedProcess(
                argv, self.capture_rc, self.capture_out, "")
        return subprocess.CompletedProcess(
            argv, self.validate_rc, "", self.validate_err)


@pytest.fixture
def faked(monkeypatch):
    monkeypatch.setattr(referee, "executable", lambda: "bmc-sensor-audit")

    def install(fake):
        monkeypatch.setattr(referee.subprocess, "run", fake)
        return fake
    return install


class TestAPartialWalkIsEvidence:
    def test_exit_two_with_a_readable_walk_is_returned_not_raised(self, faked,
                                                                  tmp_path):
        """The whole defect, in one assertion. This raised before, and the run
        stopped at the phase that induced the fault -- so the referee was never
        asked the question the scenario exists to ask."""
        faked(_Fake(capture_rc=2, writes=PARTIAL))
        taken = referee.capture("http://bmc", tmp_path / "w.json")
        assert taken.path.exists()
        assert taken.complete is False

    def test_a_complete_walk_says_so(self, faked, tmp_path):
        """Non-vacuity: `complete` discriminates rather than always reporting the
        interesting case."""
        faked(_Fake(capture_rc=0, writes=WALK))
        assert referee.capture("http://bmc", tmp_path / "w.json").complete is True

    def test_the_walk_is_validated_rather_than_inferred_from_the_exit_code(
            self, faked, tmp_path):
        """The artifact is judged by the tool that owns the format, not by this
        program deciding what an exit code probably meant."""
        fake = faked(_Fake(capture_rc=2, writes=PARTIAL))
        referee.capture("http://bmc", tmp_path / "w.json")
        assert [c[1] for c in fake.calls] == ["capture", "validate-walk"]


class TestACaptureThatCannotBeJudgedStillRaises:
    def test_no_file_written_raises(self, faked, tmp_path):
        """An unreachable machine produces no walk at all, and that is still a
        failed run rather than a partial one."""
        faked(_Fake(capture_rc=2, writes=None))
        with pytest.raises(RuntimeError, match="wrote no walk"):
            referee.capture("http://bmc", tmp_path / "w.json")

    def test_a_file_the_validator_refuses_raises(self, faked, tmp_path):
        """A file exists and is not a walk. Treating that as a partial capture
        would hand the referee something it cannot read and call it evidence."""
        faked(_Fake(capture_rc=2, validate_rc=1,
                    validate_err="sensors[0] carries no 'name'"))
        with pytest.raises(RuntimeError, match="validator refuses"):
            referee.capture("http://bmc", tmp_path / "w.json")

    def test_an_undocumented_exit_code_raises(self, faked, tmp_path):
        """`127` is command-not-found, not a partial walk. The same rule the
        pipeline applies: anything outside the documented 0/1/2 reads as
        could-not-complete, with the raw code kept beside it."""
        faked(_Fake(capture_rc=127, writes=WALK))
        with pytest.raises(RuntimeError, match="127"):
            referee.capture("http://bmc", tmp_path / "w.json")


class TestTheContentHandle:
    def test_it_is_read_off_the_tool_rather_than_computed_here(self, faked,
                                                               tmp_path):
        """Two definitions of one handle is how the two come to disagree. The
        publisher owns it; this reads what the publisher printed."""
        faked(_Fake(capture_out=f"wrote 1 sensor(s)\n  digest      {DIGEST}\n"))
        assert referee.capture("http://bmc", tmp_path / "w.json").digest == DIGEST

    def test_it_is_matched_by_SHAPE_not_by_the_label_beside_it(self, faked,
                                                              tmp_path):
        """A heading can be reworded; `sha256:` and sixty-four hex characters
        cannot become something else without the format changing."""
        faked(_Fake(capture_out=f"some other wording entirely: {DIGEST}"))
        assert referee.capture("http://bmc", tmp_path / "w.json").digest == DIGEST

    def test_an_absent_handle_is_none_rather_than_a_guess(self, faked, tmp_path):
        """A referee too old to print one, or a flag that stopped working. `None`
        says nothing was read; a computed stand-in would say something false."""
        faked(_Fake(capture_out="wrote 1 sensor(s) to w.json"))
        assert referee.capture("http://bmc", tmp_path / "w.json").digest is None


def _tool() -> str | None:
    return shutil.which("bmc-sensor-audit")


@pytest.mark.skipif(_tool() is None,
                    reason="needs the referee on PATH; the branch tests above "
                           "fake it, these two must not")
class TestAgainstTheRealTool:
    """The faking above is a claim about what the tool prints. These check it.

    Skipped without the tool rather than faked, because a fake that agrees with
    another fake proves only that this file is self-consistent.
    """

    @staticmethod
    def _walk(tmp_path):
        from bmc_sensor_audit.testing.mock_redfish import MockBMC, serve
        bmc = MockBMC(shape="sensors")
        bmc.add("Inlet", reading=21.0, upper_critical=80.0)
        with serve(bmc) as url:
            return referee.capture(url, tmp_path / "real.json")

    def test_the_handle_is_the_one_sha256sum_gives(self, tmp_path):
        """The property that makes it useful to a recipient: no tooling needed,
        and nothing to trust."""
        taken = self._walk(tmp_path)
        assert taken.digest == "sha256:" + hashlib.sha256(
            taken.path.read_bytes()).hexdigest()

    def test_a_real_capture_is_complete_and_validates(self, tmp_path):
        taken = self._walk(tmp_path)
        assert taken.complete is True
        assert referee.validate_walk(taken.path) is None

    def test_the_validator_refuses_a_walk_this_test_breaks(self, tmp_path):
        """Non-vacuity for `validate_walk`: it has to be able to say no, or the
        check above is a function that returns None."""
        taken = self._walk(tmp_path)
        payload = json.loads(taken.path.read_text())
        del payload["sensors"][0]["name"]
        taken.path.write_text(json.dumps(payload))
        assert "name" in (referee.validate_walk(taken.path) or "")


class TestTheEvidenceOutlivesTheWorkdir:
    def test_a_clean_run_deletes_its_walks_and_keeps_their_handles(self):
        """The reason the handles are recorded at all. A run with no mismatches
        removes its workdir, so the run that needs no further explanation is
        exactly the one whose walks are gone."""
        from qa_orchestrator.run import RunResult

        result = RunResult(
            scenario=None, phases=[], walks_taken=2,
            captures=(referee.Capture(Path("/gone/walk_001.json"), True, DIGEST),
                      referee.Capture(Path("/gone/walk_002.json"), False, None)))
        lines = result.evidence()
        assert DIGEST in lines[0] and "complete" in lines[0]
        assert "PARTIAL" in lines[1]
        assert "no handle printed" in lines[1], (
            "a walk whose handle was never read must say so rather than leave a "
            "blank column that reads as one nobody bothered to record")

    def test_a_run_with_no_walks_has_nothing_to_say(self):
        from qa_orchestrator.run import RunResult

        assert RunResult(scenario=None, phases=[], walks_taken=0).evidence() == []


class TestTheShippedScenarioExercisesTheAction:
    """A scenario nobody runs is a claim. This one exists because the action it
    uses was documented, unusable, and covered by nothing."""

    SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"

    def test_a_shipped_scenario_uses_the_fail_action(self):
        yaml = pytest.importorskip("yaml", reason="scenarios are YAML")
        using = []
        for path in self.SCENARIOS.glob("*.yaml"):
            raw = yaml.safe_load(path.read_text())
            for phase in raw.get("phases") or []:
                if isinstance(phase.get("action"), dict) and "fail" in phase["action"]:
                    using.append(path.name)
        assert using, (
            "no shipped scenario uses the `fail` action. It was documented and "
            "unusable for exactly as long as that was true")

    def test_it_expects_the_could_not_complete_verdict(self):
        """The point of the action. A partial walk must produce `2` -- the tool
        saying it does not know -- and not `1`, which would claim sensors were
        missing on evidence it does not have."""
        yaml = pytest.importorskip("yaml", reason="scenarios are YAML")
        raw = yaml.safe_load((self.SCENARIOS / "partial-walk.yaml").read_text())
        failing = [p for p in raw["phases"]
                   if isinstance(p.get("action"), dict) and "fail" in p["action"]]
        assert failing, "partial-walk.yaml no longer induces a partial walk"
        assert failing[0]["expect"]["audit"]["exit"] == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


class TestTheToolCanBeAskedWhatItIs:
    """`--version`, for the same reason the referee needed one.

    `odm-qa-pipeline` runs this as a subprocess resolved on PATH and declares
    `qa-orchestrator>=0.1.1,<0.2` in its manifest. pip enforces that over the
    environment it installed into; PATH decides what actually answers. Without a
    version flag a caller had nothing to ask, and `--version` exited 2 with an
    argparse usage error -- which in this family's vocabulary means
    could-not-complete, indistinguishable from a real refusal.
    """

    def _run(self, *args):
        import os
        import subprocess
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        return subprocess.run(
            [sys.executable, "-m", "qa_orchestrator.cli", *args],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(root / "src")})

    def test_it_exits_clean_on_stdout(self):
        done = self._run("--version")
        assert done.returncode == 0, done.stderr
        assert done.stderr == ""

    def test_it_reports_the_version_the_package_declares(self):
        from qa_orchestrator import __version__
        assert self._run("--version").stdout.strip() == \
            f"qa-orchestrator {__version__}"
