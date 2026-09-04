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

**Released — 0.2.0**, tagged `v0.2.0`, Apache-2.0, on PyPI as `qa-orchestrator`.

**0.2.0 raises the referee floor to 0.2.0 and adds `--version`.** The floor is
the point: from `bmc-sensor-audit` 0.2.0 a command that asks to verify and not
to verify at once is refused rather than run unverified, and a harness that
drives a referee should not be what pins it below its own security fix. This
package's own behaviour is unchanged. The suite now runs on every Python it
claims.

**0.1.2 changes nothing this package does.** It carries the repository's
publication-hygiene tooling: the rules now run over commit messages as well as
files, and a pre-commit hook refuses a commit whose staged content it has not
read. The only differences a reader will find in the installed distribution are
this paragraph and the version number. Nothing here obliges an upgrade.

0.1.1 makes the scenario schema's `fail` action work. It was documented from
the start and had never run: the referee's `capture` exits `2` both when it
cannot reach the machine and when it reached the machine and a subtree
answered with an error, and this harness raised on either — so a scenario that
induced a partial walk aborted before the referee could be asked anything.
Every walk also carries a content handle now. Needs `bmc-sensor-audit` 0.1.1.

```
pip install qa-orchestrator

qa-orchestrator check <scenario.yaml>     # parse only; needs no machine
qa-orchestrator run <scenario.yaml>
```

The two worked scenarios are named with a placeholder above rather than by
filename, because a wheel carries only what lives under the package directory: a
`pip install` gives you the command and not the examples. They ship in this
repository and in the sdist, under `scenarios/`. From a clone,
`pip install -e .` puts the same script on the path and the scenarios beside it.

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

## A fourth tier is yours to add

The three tiers above are all hardware, and for a while the protocol was too: its
verbs took a `sensor`, and `build()` knew three names and no more. Neither is a
branch on a domain, so no gate catches either — one is a parameter name, the other
a closed list of constructors. The effect was a harness whose architecture is
domain-free and whose only door led to a BMC.

The protocol is about **presence and value**, and neither is a hardware idea. An
**entity** is whatever the tool under test enumerates and reports on: a sensor, a
requirement in a proposal, a ledger account, an open matter.

```python
from qa_orchestrator.backends import register

class LedgerBackend:
    name = "ledger"
    def __init__(self, machine): ...
    def start(self):  return "postgres://..."   # the handle the referee reads
    def stop(self):   ...
    def remove(self, entity):            ...    # gone entirely
    def disable(self, entity):           ...    # declared, no longer reporting
    def fail(self, path, status):        ...    # a region refuses, for a partial read
    def set_reading(self, entity, value):...
    def state(self, entity):             ...    # absent | disabled | reading

register("ledger", LedgerBackend)                # then `backend: ledger` in a scenario
```

`state()` returns one of three values, exported as `PRESENCE`. They are not
hardware states: they are the three ways a thing that *should* be there can
actually be — gone, there but not reporting, there and reporting. A boolean would
collapse the middle one, and the middle one is where the interesting faults live: a
sensor switched off at the factory, a requirement present but unanswerable, an
account that exists and has stopped settling.

`register()` refuses to shadow a built-in tier, because silently replacing `mock`
would make a run report a tier it did not use.

**Both vocabularies are read.** `entities:`/`entity:` and `sensors:`/`sensor:` mean
the same thing in a scenario, as do `expect.substrate` and `expect.firmware`. The
scenario format stays `qa-scenario/1`: the test for a format bump is whether an
older reader would *silently ignore* a new key, and it would not — it validates the
action payload and refuses the new spellings by name. A loud refusal is a reader
correctly declining a file it does not understand, which is what the version
already means.

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

## A partial walk is evidence, not a failed run

The audit tool's `capture` exits `2` for two different facts: it could not reach
the machine, and it reached the machine while one subtree answered with an error.
The second is a walk the tool **writes and keeps on purpose**, because knowing
which subtree failed is the point.

This harness used to raise on any non-zero, so the scenario schema's `fail`
action — *make a subtree answer with an HTTP status* — aborted the run before the
referee could be asked anything. No shipped scenario used it and no test
exercised it, so it had never once worked. `scenarios/partial-walk.yaml` is that
scenario, and it now runs.

The fix is to judge the **file** rather than the exit code. `validate-walk` says
whether what was written is a well-formed `walk/1` — a question about the artifact
rather than about the run — and the walk's own error list says whether the machine
answered for all of it. A capture that produced no readable walk is still a
failure and still stops the run.

What it is really testing is the referee's honesty about not knowing. A subtree it
could not read is indistinguishable from a subtree with nothing in it, so the tool
must **not** report absence on a partial walk. Exit `2` is it saying so, and a
tool that rendered a network error as *two sensors missing* would be worse than
useless on a line.

## Every walk gets a content handle

```
evidence:
  walk 001  complete  sha256:81422480ba090695df9f8dabb6aba4cd849048f137ca5707558fbcd03e43950e
  walk 002  PARTIAL   sha256:19cb099c107403ad68a8ce0c29cfc6d0a6724dde688ad815347a8a2192e91835
```

Printed by every run, including one that stopped early. **A clean run deletes its
workdir**, so the run that needs no further explanation is exactly the one whose
walks are gone — the handles outlive them.

They are the tool's own, from `capture --print-digest`: a SHA-256 over the file's
bytes, which `sha256sum` reproduces in any language. Anyone who kept a walk can
match it with no tooling and nothing to trust, and a walk that does not match is
not the walk that was judged. This program reads the handle rather than computing
one, because two definitions of one number is how the two come to disagree.

## Not built yet

- The redundancy scenario against the audit tool's supplemental template.
- The `qemu` boot recipe; this build attaches to a running instance.
- The `testbed` tier, which needs a lab.

Apache-2.0.
