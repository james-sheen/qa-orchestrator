"""A vertical supplies its own substrate AND its own referee, and runs.

The substrate side became general first: `register` lets a vertical supply a
backend. That was half a door. The program being graded was still a string
literal in `referee.py` -- `bmc-sensor-audit`, its subcommands, its flag names
and its report schema -- so a scenario could describe a paper vertical and could
never run one, and the only evidence the harness was general was a backend
constructed directly in a test and never driven through `run`.

This file drives one. The backend is requirements in a proposal; the referee is a
program with a deliberately different command line -- positional arguments where
the built-in tool takes flags, and different words for the same three questions.
Nothing here installs, imports or invokes `bmc-sensor-audit`. If any of the three
argv shapes were still hardcoded, the end-to-end test below could not pass.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from qa_orchestrator import backends, referee
from qa_orchestrator.run import run
from qa_orchestrator.scenario import parse

# --------------------------------------------------------------------------
# A substrate with no hardware in it: requirements in a proposal.
# --------------------------------------------------------------------------


class _PaperBackend:
    """`start()` returns a FILE the referee reads the substrate through.

    Which is the contract as generalised: a handle, not a URL. The handle being a
    path rather than a URL is the whole reason this vertical can be graded by a
    program that has never heard of a BMC.
    """

    name = "paper"

    def __init__(self, machine: dict) -> None:
        self._where = Path(machine["state_file"])
        self._entities = {e["name"]: e.get("reading", 1.0)
                          for e in (machine.get("entities") or [])}
        self._gone: set[str] = set()

    def start(self) -> str:
        live = {name: value for name, value in self._entities.items()
                if name not in self._gone}
        self._where.write_text(json.dumps({"requirements": live}))
        return str(self._where)

    def stop(self) -> None:
        pass

    def remove(self, entity: str) -> None:
        self._gone.add(entity)

    def disable(self, entity: str) -> None:
        self._entities[entity] = None

    def fail(self, path: str, status: int) -> None:
        pass

    def set_reading(self, entity: str, value: float) -> None:
        self._entities[entity] = value

    def state(self, entity: str) -> str:
        if entity in self._gone or entity not in self._entities:
            return "absent"
        return "disabled" if self._entities[entity] is None else "reading"


# --------------------------------------------------------------------------
# A referee that is not the built-in tool, and does not resemble its CLI.
# --------------------------------------------------------------------------

_PROGRAM = r'''#!/usr/bin/env python3
"""A requirements checker. Positional arguments, and its own words."""
import json, sys

argv = sys.argv[1:]
if argv[0] == "record":                       # record <handle> <out>
    out = argv[2]
    with open(argv[1]) as handle:
        json.dump(json.load(handle), open(out, "w"))
    print("stored as proposal-5f3a9c1d")
    sys.exit(0)

if argv[0] == "check":                        # check <file>
    try:
        json.load(open(argv[1]))
    except Exception as problem:
        print(problem); sys.exit(2)
    sys.exit(0)

if argv[0] == "review":                       # review --rules R --record W ...
    rules, records = [], []
    index = 1
    while index < len(argv):
        if argv[index] == "--rules":
            rules.append(argv[index + 1]); index += 2
        elif argv[index] == "--record":
            records.append(argv[index + 1]); index += 2
        elif argv[index] == "--as-json":
            index += 1
        else:
            print("unknown argument " + argv[index]); sys.exit(2)
    declared = json.load(open(rules[0]))["declared"]
    latest = json.load(open(records[-1]))["requirements"]
    missing = [name for name in declared if name not in latest]
    if "--as-json" in argv:
        print(json.dumps({"issues": [{"requirement": m} for m in missing]}))
        sys.exit(1 if missing else 0)
    for name in missing:
        print(name)
        print("    the requirement is declared and absent from the proposal")
    sys.exit(1 if missing else 0)

print("unknown subcommand"); sys.exit(2)
'''


def _paper_tool() -> referee.Tool:
    return referee.Tool(
        name="proposal-review",
        executable="proposal-review",
        install_hint="pip install proposal-review",
        modes=("review",),
        # Positional, where the built-in tool takes --target and --out.
        capture_argv=lambda target, out: ("record", target, str(out)),
        validate_argv=lambda path: ("check", str(path)),
        judge_argv=lambda mode, configs, walks: (
            mode,
            *[part for c in configs for part in ("--rules", str(c))],
            *[part for w in walks for part in ("--record", str(w))]),
        json_argv=lambda mode: ("--as-json",),
        findings_key="issues",
        subject_keys=("requirement",),
        # Not `sha256:`. That shape belongs to the built-in tool, and a capture
        # whose handle does not match simply returns None -- so this was the one
        # part of the seam that could stay hardcoded without failing anything.
        digest_pattern=r"\bproposal-[0-9a-f]{8}\b",
    )


@pytest.fixture
def vertical(tmp_path, monkeypatch):
    """Register both halves and put the fake referee on PATH."""
    binary = tmp_path / "bin" / "proposal-review"
    binary.parent.mkdir(parents=True)
    binary.write_text(_PROGRAM)
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    monkeypatch.setenv("PATH", str(binary.parent) + os.pathsep + os.environ["PATH"])

    backends.register("paper", _PaperBackend)
    referee.register_tool(_paper_tool())
    yield tmp_path
    backends._REGISTERED.pop("paper", None)
    referee._REGISTERED_TOOLS.pop("proposal-review", None)


def _scenario(tmp_path, *, action: str | None) -> str:
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"declared": ["R-3.2", "R-7.1"]}))
    phase = f"""
  - note: the requirement is withdrawn
    walks: 1
    action: {action}
    expect:
      audit:
        exit: 1
        names: [R-3.2]
""" if action else ""
    return f"""
format: qa-scenario/1
name: a proposal, graded by a program that has never seen a BMC
backend: paper
referee: proposal-review
mode: review
config: {rules}

machine:
  state_file: {tmp_path / "substrate.json"}
  entities:
    - {{name: R-3.2, reading: 1.0}}
    - {{name: R-7.1, reading: 1.0}}

phases:
  - note: everything declared is present
    walks: 1
    expect:
      audit: {{exit: 0}}
{phase}"""


class TestTheRegistryRefusesTheSameThingsTheBackendOneDoes:
    def test_a_builtin_cannot_be_shadowed(self):
        """Silently replacing it would make a run report a referee it did not use."""
        with pytest.raises(referee.RefereeUnavailable, match="built-in"):
            referee.register_tool(referee.Tool(
                name="bmc-sensor-audit", executable="x", install_hint="",
                modes=("detect",), capture_argv=lambda t, o: (),
                validate_argv=lambda p: (), judge_argv=lambda m, c, w: ()))

    def test_an_unknown_referee_lists_what_it_has(self, vertical):
        with pytest.raises(referee.RefereeUnavailable, match="proposal-review"):
            referee.profile("ledger-audit")


class TestAScenarioMayNameEitherHalf:
    def test_a_registered_backend_can_be_named_in_a_scenario(self, vertical):
        """The door `register` opened. The parser kept its own list of tiers and
        refused this before `build` was ever reached."""
        scenario = parse(_scenario(vertical, action=None), source=None)
        assert scenario.backend == "paper"

    def test_a_registered_referee_can_be_named_in_a_scenario(self, vertical):
        scenario = parse(_scenario(vertical, action=None), source=None)
        assert scenario.referee == "proposal-review"

    def test_the_mode_is_judged_against_that_referees_vocabulary(self, vertical):
        """`detect` is the built-in tool's word and means nothing to this one."""
        broken = _scenario(vertical, action=None).replace(
            "mode: review", "mode: detect")
        with pytest.raises(Exception, match="review"):
            parse(broken, source=None)

    def test_an_unregistered_referee_is_still_refused(self, tmp_path):
        """With the backend registered and the referee not, so the refusal that
        fires is the one under test. Written without the backend at first, and it
        refused on the backend instead -- a check that never reached its subject."""
        backends.register("paper", _PaperBackend)
        try:
            with pytest.raises(Exception, match="referee is"):
                parse(_scenario(tmp_path, action=None), source=None)
        finally:
            backends._REGISTERED.pop("paper", None)


class TestItRunsEndToEnd:
    """The differential run: the same stage, a domain sharing no vocabulary."""

    def test_a_clean_proposal_passes(self, vertical):
        result = run(parse(_scenario(vertical, action=None), source=None),
                     workdir=vertical / "work")
        assert result.error is None, result.error
        assert result.walks_taken == 1
        assert result.phases[0].verdict.exit_code == 0
        assert result.phases[0].passed

    def test_a_withdrawn_requirement_is_caught_and_named(self, vertical):
        result = run(parse(_scenario(vertical, action="{remove: R-3.2}"),
                           source=None),
                     workdir=vertical / "work")
        assert result.error is None, result.error
        assert [p.passed for p in result.phases] == [True, True]
        assert result.phases[1].verdict.exit_code == 1

    def test_the_content_handle_shape_is_read_from_the_profile(self, vertical):
        """A handle this tool prints, in a shape the built-in one never emits."""
        result = run(parse(_scenario(vertical, action=None), source=None),
                     workdir=vertical / "work")
        assert [c.digest for c in result.captures] == ["proposal-5f3a9c1d"]

    def test_the_report_schema_is_read_from_the_profile(self, vertical):
        """`issues` / `requirement`, not `findings` / `name`."""
        result = run(parse(_scenario(vertical, action="{remove: R-3.2}"),
                           source=None),
                     workdir=vertical / "work")
        assert result.phases[1].verdict.names_mentioned() == {"R-3.2"}

    def test_nothing_in_this_run_touched_the_built_in_tool(self, vertical,
                                                           monkeypatch):
        """Non-vacuity: the run above must not have quietly used the real tool.

        If `bmc-sensor-audit` were still reachable, a hardcoded path could pass
        while looking like this. Removing it from PATH must change nothing.
        """
        import shutil as _shutil
        real = _shutil.which
        monkeypatch.setattr(_shutil, "which",
                            lambda name, *a, **k: None
                            if name == "bmc-sensor-audit" else real(name, *a, **k))
        result = run(parse(_scenario(vertical, action=None), source=None),
                     workdir=vertical / "work")
        assert result.error is None, result.error
        assert result.phases[0].passed
