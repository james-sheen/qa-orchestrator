"""The example vertical is runnable as shipped, not just as the suite repairs it.

`conftest.paper_on_path` copies the example referee and sets the executable bit
on the copy, which is correct for a test and hides a packaging fault: the bit is
metadata, it does not survive every way a tree is distributed, and the tree this
rewrite arrived in had lost it. The example then exits 2 -- correctly, loudly, and
only for someone who tried to run it.

So the bit is asserted here on the file **as it sits in the tree**. Git records
the mode, so a clone gets it; nothing records it in a zip.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "paper"
REFEREE = EXAMPLE / "bin" / "proposal-review"


def _env(referee_dir: Path) -> dict:
    """A child that can find both the referee and the package under test.

    `pythonpath` in `pyproject.toml` configures pytest's own process and reaches
    no subprocess, so the first version of this ran a child that could not import
    the package at all -- and the negative control below still passed, because an
    unimportable module also exits 1.
    """
    env = dict(os.environ)
    env["PATH"] = str(referee_dir) + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return env


class TestTheExampleRefereeIsExecutableAsShipped:
    def test_the_file_is_there(self):
        assert REFEREE.is_file(), f"{REFEREE} is missing; the example cannot run"

    def test_it_carries_the_executable_bit(self):
        """The one assertion. `PATH` lookup needs it and a copy cannot supply it
        for a reader who cloned the tree and typed the README's command."""
        mode = REFEREE.stat().st_mode
        assert mode & stat.S_IXUSR, (
            f"{REFEREE.relative_to(ROOT)} is not executable (mode "
            f"{stat.filemode(mode)}). The README's own command exits 2 on a "
            f"fresh clone, and the suite will not notice because its fixture "
            f"chmods a copy")

    def test_it_runs_from_the_tree_and_answers(self):
        """Non-vacuity for the bit: a mode with nothing behind it proves little."""
        result = subprocess.run([str(REFEREE), "check", str(EXAMPLE / "rules.json")],
                                capture_output=True, text=True, timeout=60)
        assert result.returncode in (0, 1, 2), (
            f"the example referee answered outside the 0/1/2 contract: "
            f"{result.returncode}")


class TestTheExampleRunsEndToEnd:
    """The domain-free demonstration, driven the way the README shows it."""

    def test_the_shipped_scenario_passes(self, paper_on_path, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "qa_orchestrator.cli",
             "--plugin", str(EXAMPLE / "vertical.py"),
             "run", str(EXAMPLE / "withdrawn.yaml")],
            capture_output=True, text=True, timeout=300,
            env=_env(paper_on_path.parent), cwd=ROOT)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "every expectation held" in result.stdout, result.stdout

    def test_a_wrong_expectation_is_refused_with_one_not_two(self, paper_on_path,
                                                             tmp_path):
        """The negative control. Every scenario shipped is expected to pass, so a
        harness that broke into always succeeding sails through all of them.

        `1` and not `2`: a verdict disagreed, rather than a run that fell over --
        those are different facts and a check that accepts either proves neither.
        """
        source = (EXAMPLE / "withdrawn.yaml").read_text()
        assert "exit: 0" in source, "nothing to invert; this control is vacuous"
        wrong = tmp_path / "wrong.yaml"
        wrong.write_text(source.replace("exit: 0", "exit: 1", 1))

        result = subprocess.run(
            [sys.executable, "-m", "qa_orchestrator.cli",
             "--plugin", str(EXAMPLE / "vertical.py"), "run", str(wrong)],
            capture_output=True, text=True, timeout=300,
            env=_env(paper_on_path.parent), cwd=ROOT)
        assert result.returncode == 1, (
            f"expected 1 (a verdict disagreed), got {result.returncode}\n"
            + result.stdout + result.stderr)
        # The exit code alone does NOT establish this. An unimportable package,
        # a missing plugin and a bad argument all exit 1 too, and the first
        # version of this test passed on exactly that. The run has to have
        # reached the comparison and reported the disagreement.
        assert "MISMATCH" in result.stdout, (
            "exit 1 without a reported mismatch: something failed before the "
            "verdict was ever compared\n" + result.stdout + result.stderr)
