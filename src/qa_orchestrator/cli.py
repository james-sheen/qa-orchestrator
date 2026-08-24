"""Command line for the orchestrator.

    qa-orchestrator run scenarios/stuck-at.yaml
    qa-orchestrator check scenarios/            # parse only, no machine needed

Exit codes are the same three-valued contract the audit tool uses, because this
program sits in the same pipeline and a fourth vocabulary at this layer would be
one more thing for a gate to get wrong:

    0  every expectation held
    1  a verdict disagreed with the scenario
    2  the run could not be completed

`2` never reads as clean. A scenario that could not reach its backend has judged
nothing, and a pipeline that treated that as a pass would ship on the strength of
a check that never ran.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .run import EXIT_CLEAN, EXIT_INCOMPLETE, EXIT_MISMATCH, run
from .scenario import ScenarioError, load


def _check(paths: list[str]) -> int:
    """Parse without running. Cheap enough for a pre-commit hook."""
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
        asserting = sum(1 for p in scenario.phases
                        if p.expect is not None or p.expect_firmware is not None)
        note = "" if asserting else "   (no phase asserts anything)"
        print(f"  ok       {path}  {len(scenario.phases)} phase(s), "
              f"{scenario.total_walks} walk(s), {asserting} asserting{note}")
    return EXIT_INCOMPLETE if bad else EXIT_CLEAN


def _run(path: str, workdir: str | None) -> int:
    try:
        scenario = load(path)
    except ScenarioError as error:
        print(f"qa-orchestrator: {error}", file=sys.stderr)
        return EXIT_INCOMPLETE

    print(f"scenario: {scenario.name}   backend: {scenario.backend}   "
          f"mode: {scenario.mode}")
    result = run(scenario, workdir=Path(workdir) if workdir else None,
                 on_event=lambda message: print(message))

    print()
    # Printed BEFORE the error branch, so a run that stopped early still leaves
    # the record of what it managed to walk. That is exactly the run whose walks
    # somebody will want to match against later.
    evidence = result.evidence()
    if evidence:
        print("evidence:")
        for line in evidence:
            print(f"  {line}")
        print()

    if result.error:
        print(f"could not complete: {result.error}", file=sys.stderr)
        return EXIT_INCOMPLETE

    # Reported whether or not anything failed. A run whose phases asserted
    # nothing is green and worthless, and the only place that can be noticed is
    # here -- the exit code cannot distinguish it from a real pass.
    print(f"{result.walks_taken} walk(s) taken, {result.assertions} of "
          f"{len(scenario.phases)} phase(s) asserted something")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qa-orchestrator", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    runner = sub.add_parser("run", help="run a scenario against its backend")
    runner.add_argument("scenario")
    runner.add_argument("--workdir", help="where to keep walks; a temporary "
                                          "directory by default, kept on failure")

    checker = sub.add_parser("check", help="parse scenarios without running them")
    checker.add_argument("paths", nargs="+")

    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args.paths)
    return _run(args.scenario, args.workdir)


if __name__ == "__main__":
    raise SystemExit(main())
