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

**Not yet released.** The 0.3 domain-free rewrite, tagged `v0.3.0` when it goes.
Apache-2.0. The published series is 0.2.x, and a `qa-scenario/1` file
written for it still reads here.

Exit codes are the referee's own three: `0` every expectation held, `1` a verdict
disagreed, `2` the run could not be completed. `2` never reads as clean.

[`DESIGN.md`](DESIGN.md) says what was locking the harness to one domain, where each lock
went, the contract a vertical must meet, the scenario format, and how to migrate the
0.2.x repository.

Apache-2.0.
