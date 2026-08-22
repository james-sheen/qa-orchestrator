# qa-orchestrator

Inject faults, drive walks, and check the audit tool reached the verdict it should have.

[`bmc-sensor-audit`](https://github.com/james-sheen/bmc-sensor-audit) judges firmware:
it diffs what an OpenBMC declaration promises against what the machine reports. This
drives both sides. It perturbs a machine in ways whose correct verdict is known in
advance — a sensor removed, one switched off, a reading frozen — and checks the tool
reached it.

## Why this is a separate program

**The audit tool is the judge of the outcome, so it cannot also be the injector.**
A referee that shipped its own fault injection would be certifying itself: every
scenario would be written against the behaviour the tool happens to have, and a
tool that stopped detecting something would quietly stop being asked about it.

So the injector lives outside and consumes only the referee's published surfaces —
exit codes, the JSON report, the attestation. `referee.py` does not import
`bmc_sensor_audit`, and a test asserts that by reading the file. If a scenario needs
something the published surface does not carry, that is a feature request against
the tool, not a reason to reach past it.

## A scenario

```yaml
format: qa-scenario/1
backend: mock
mode: coverage
config: fixtures/board.json          # resolved beside this file, not from the cwd

machine:
  sensors:
    - {name: Inlet,  reading: 21.0, upper_critical: 80, upper_warning: 70}
    - {name: Outlet, reading: 27.5, upper_critical: 80, upper_warning: 70}

phases:
  - walks: 1
    expect:
      audit: {exit: 0}

  - action: {remove: Outlet}
    walks: 1
    expect:
      audit:
        exit: 1
        finding: "not reported by the machine at all"
        names: [Outlet]
        not_names: [Inlet]
      firmware: {Outlet: absent, Inlet: reading}
```

**Not yet released** — no tag, and no index carries this name. Install it from
git, which is the same requirement `odm-qa-pipeline` pins for gate 3:

```
pip install "qa-orchestrator @ git+https://github.com/james-sheen/qa-orchestrator@master"

qa-orchestrator run scenarios/sensor-removed.yaml
qa-orchestrator check scenarios/          # parse only; needs no machine
```

From a clone instead, `pip install -e .` puts the same script on the path.

**`audit` and `firmware` are different claims and both are worth making.** *The
sensor is gone* and *the tool noticed it is gone* are separate facts. A scenario
that could only express the second could never tell a broken injector from a blind
referee — the run would be green either way.

**`not_names` is half of every detection claim.** Naming the frozen sensor shows
the tool found something; showing the sensor beside it was *not* named is what
makes that evidence of detection rather than of a check that flags everything.

## The format refuses what it cannot run

A phase with no walks, an `expect` block that sets nothing, an action verb this
build does not implement, a `drive` with fewer values than walks, `exit_code` where
`exit` was meant — all rejected at parse time with the phase named. Each of them
would otherwise produce a run that executed, reported clean, and tested nothing,
which is indistinguishable from a real pass at the exit code.

## Three tiers, and one of them says so

| Backend | What it is | State |
|---|---|---|
| `mock` | the audit tool's own `MockBMC`, in process | working; needs no hardware |
| `qemu` | attaches to a running instance, injects over QMP | wire format tested, integration not |
| `testbed` | relay boards and real fans | **not implemented, and refuses** |

The tiers exist so one scenario runs at increasing cost and realism without being
rewritten. That only holds if a tier which cannot do something refuses instead of
approximating it. `testbed` raises at construction and its refusal lists what a
real implementation needs — a specification, not an apology. A stub that accepted
injections and did nothing would report that real fans were pulled having touched
nothing, and every phase after it would judge an unperturbed machine and pass.

`qemu` attaches to an already-running instance whose QMP socket the scenario names.
**It does not boot one.** Owning the boot recipe — image build id, machine type, FRU
provisioning — is real work that is not done here, and claiming it would be worse
than not having it. The QMP conversation is tested against a fake socket, so the
greeting, handshake, framing and error path are covered; no real QEMU has run it.

## Exit codes

The same three-valued contract the audit tool uses, because this sits in the same
pipeline and a fourth vocabulary at this layer is one more thing for a gate to get
wrong:

| | |
|---|---|
| `0` | every expectation held |
| `1` | a verdict disagreed with the scenario |
| `2` | the run could not be completed |

**`2` never reads as clean.** A scenario that could not reach its backend has judged
nothing. Could-not-complete outranks disagreement, because a run that stopped early
has not evaluated the phases it never reached.

A run also reports how many phases asserted anything. A scenario of phases that
assert nothing is green and worthless, and the exit code cannot tell that from a
real pass — so it is said in words instead.

## The acceptance scenario

`scenarios/stuck-at.yaml` reproduces the experiment the audit tool already ships: a
sensor driven to a new value before each of twelve walks, then left alone for
sixteen. The engine is silent while everything moves and names exactly the frozen
sensor once one freezes, with a control sensor still moving beside it.

That experiment is the acceptance test for this harness, because its outcome is
already known. **If the orchestrator cannot express it, the DSL is wrong** — and at
first it could not: `drive` took one sensor and a phase may carry only one action,
so there was no way to keep a control moving beside the frozen one. The general
`drive: {sensors: {...}}` form exists because this file needed it.

Two things it does not show. Freezing a reading through a mock is an experiment, not
a sensor failing on its own. And the declaration it runs against carries thresholds
deliberately: a sensor declaring none is excluded from the liveness model entirely,
so a thresholdless board produces an empty model and a clean run that checked
nothing.

## Not built yet

- The redundancy scenario against the audit tool's supplemental template.
- The `qemu` boot recipe; this build attaches to a running instance.
- The `testbed` tier, which needs a lab.

Apache-2.0.
