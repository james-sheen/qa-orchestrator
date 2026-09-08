# qa-orchestrator

Inject faults into a substrate, drive captures, and check that the referee — the program
being graded — reached the verdict it should have. The harness knows nothing about any
domain: tiers, verbs, referees and report shapes are registered by **verticals**, and the
first vertical (`bmc-sensor-audit` over BMC firmware) is one of them, loaded through the
same door as any other.

```
pip install -e '.[dev]'

qa-orchestrator list           # what this process can name

# The first vertical's scenarios live with the first vertical.
qa-orchestrator check src/qa_orchestrator/verticals/bmc_scenarios/
qa-orchestrator run   src/qa_orchestrator/verticals/bmc_scenarios/sensor-removed.yaml

PATH=examples/paper/bin:$PATH \
qa-orchestrator --plugin examples/paper/vertical.py run examples/paper/withdrawn.yaml
```

The last line grades a proposal's requirements with a checker that has never seen a BMC:
positional arguments where the first vertical's tool takes flags, `issues` where it
keeps `findings`, and a report of what it did **not** check, which the scenario asserts on.

**Released — 0.3.2**, tagged `v0.3.2`, Apache-2.0, on PyPI as `qa-orchestrator`.

**0.3.2 follows the referee's wording.** `bmc-sensor-audit` 0.2.5 reworded the
finding a removed sensor produces -- from the machine to the capture -- and
`sensor-removed.yaml` still expected the old text, so the scenario shipped in
0.3.1 fails against every referee from 0.2.5 on. The `bmc` extra now floors that
dependency at 0.2.5, because everything below it emits the wording the file no
longer expects.

**0.3.1 corrects a pointer.** Two source files named a test file that does not
exist as the guard for the domain-free claim -- the central claim here -- and
0.3.0 shipped that way, so a reader who followed it found nothing and could not
tell whether the guard had been renamed, deleted or never written. Both now name
`tests/test_registries.py` and its class. A check was added that refuses any test
path this package names and cannot resolve, because the two were found by
scanning for the shape rather than by reading the one that was reported, and the
scan found one more than the report did.

**0.3.0 is the domain-free rewrite.** Tiers, verbs, referees and report shapes come
from registries and the core names none of them; the BMC tool, its tiers and its
scenarios are a vertical loaded through an entry point, like any other would be. A
`qa-scenario/1` file written for 0.2.x still reads and still runs.

Exit codes are the referee's own three: `0` every expectation held, `1` a verdict
disagreed, `2` the run could not be completed. `2` never reads as clean.

[`DESIGN.md`](DESIGN.md) says what was locking the harness to one domain, where each lock
went, the contract a vertical must meet, the scenario format, how to write a vertical, and
what changed from 0.2.x for anyone with code written against it.

Apache-2.0.
