"""Command line for the orchestrator.

    qa-orchestrator run scenario.yaml
    qa-orchestrator check some/scenarios/            # parse only, no substrate needed
    qa-orchestrator list                             # what this process can name
    qa-orchestrator --plugin my_vertical run s.yaml  # a vertical not on an entry point

Exit codes are the same three-valued contract the referee uses, because this
program sits in the same pipeline and a fourth vocabulary at this layer would be
one more thing for a gate to get wrong:

    0  every expectation held
    1  a verdict disagreed with the scenario
    2  the run could not be completed

`2` never reads as clean. A scenario that could not reach its substrate or its
referee has judged nothing, and a pipeline that treated that as a pass would
ship on the strength of a check that never ran.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, actions, plugins, referee, substrate
from .run import EXIT_CLEAN, EXIT_INCOMPLETE, EXIT_MISMATCH, run
from .scenario import ScenarioError, load
from .vocabulary import PluginError


def _check(paths: list[str]) -> int:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        files.extend(sorted(path.rglob("*.yaml")) if path.is_dir() else [path])
    if not files:
        print("no scenario files found", file=sys.stderr)
        return EXIT_INCOMPLETE

    bad = 0
    for path in files:
        try:
            scenario = load(path)
        except ScenarioError as error:
            print(f"  REFUSED  {path}\n           {error}", file=sys.stderr)
            bad += 1
            continue
        asserting = sum(1 for p in scenario.phases if p.asserts_anything)
        note = "" if asserting else "   (no phase asserts anything)"
        print(f"  ok       {path}  {scenario.format}  substrate {scenario.substrate}, "
              f"referee {scenario.referee}/{scenario.mode}: {len(scenario.phases)} "
              f"phase(s), {scenario.total_captures} capture(s), {asserting} asserting{note}")
    return EXIT_INCOMPLETE if bad else EXIT_CLEAN


def _run(path: str, workdir: str | None) -> int:
    try:
        scenario = load(path)
    except ScenarioError as error:
        print(f"qa-orchestrator: {error}", file=sys.stderr)
        return EXIT_INCOMPLETE

    print(f"scenario: {scenario.name}   substrate: {scenario.substrate}   "
          f"referee: {scenario.referee}   mode: {scenario.mode}")
    result = run(scenario, workdir=Path(workdir) if workdir else None,
                 on_event=lambda message: print(message))

    print()
    # Printed BEFORE the error branch, so a run that stopped early still leaves
    # the record of what it managed to capture.
    evidence = result.evidence()
    if evidence:
        print("evidence:")
        for line in evidence:
            print(f"  {line}")
        print()

    if result.error:
        print(f"could not complete: {result.error}", file=sys.stderr)
        return EXIT_INCOMPLETE

    print(f"{result.captures_taken} capture(s) taken, {result.assertions} of "
          f"{len(scenario.phases)} phase(s) asserted something; graded by "
          f"{scenario.referee} at {result.referee_path}")
    if not result.assertions:
        print("nothing was asserted, so this run is not evidence of anything",
              file=sys.stderr)

    if result.mismatches:
        print(f"\n{len(result.mismatches)} mismatch(es):", file=sys.stderr)
        for mismatch in result.mismatches:
            print(f"  - {mismatch}", file=sys.stderr)
        return EXIT_MISMATCH

    print("every expectation held")
    return EXIT_CLEAN


def _list(loaded: list[plugins.Loaded]) -> int:
    print("plugins:")
    for item in loaded or ():
        print(f"  {item.spec}  ({item.origin}): {item.summary}")
    if not loaded:
        print("  (none)")
    print(f"substrates: {', '.join(substrate.known())}")
    print(f"verbs:      {', '.join(actions.known_verbs())}")
    print("referees:")
    for name in referee.known_tools() or ():
        tool = referee.profile(name)
        print(f"  {name}  ({tool.executable}; modes {', '.join(tool.modes)})")
    if not referee.known_tools():
        print("  (none -- load a vertical)")
    return EXIT_CLEAN


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qa-orchestrator",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"qa-orchestrator {__version__}")
    parser.add_argument("--plugin", action="append", default=[], metavar="SPEC",
                        help="load a vertical: module, module:callable, or file.py")
    parser.add_argument("--no-entry-points", action="store_true",
                        help="ignore installed entry points; only --plugin and the environment")
    sub = parser.add_subparsers(dest="command", required=True)

    runner = sub.add_parser("run", help="run a scenario against its substrate and referee")
    runner.add_argument("scenario")
    runner.add_argument("--workdir", help="where to keep captures; a temporary directory "
                                          "by default, kept on failure")
    checker = sub.add_parser("check", help="parse scenarios without running them")
    checker.add_argument("paths", nargs="+")
    sub.add_parser("list", help="show the substrates, verbs and referees this process can name")

    args = parser.parse_args(argv)
    try:
        loaded = plugins.load_all(args.plugin, entry_points=not args.no_entry_points)
    except PluginError as error:
        print(f"qa-orchestrator: {error}", file=sys.stderr)
        return EXIT_INCOMPLETE

    if args.command == "list":
        return _list(loaded)
    if args.command == "check":
        return _check(args.paths)
    return _run(args.scenario, args.workdir)


if __name__ == "__main__":
    raise SystemExit(main())
