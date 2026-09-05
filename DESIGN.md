# qa-orchestrator 0.3 — the domain-free rewrite

A fault-injection harness that grades a **referee** (any program with a capture/judge
command line and a `0/1/2` exit contract) against a **substrate** (anything that
enumerates entities with a presence and a value), where every domain-specific fact —
which tiers exist, which verbs exist, which referee, what its report looks like, what
a `qa-scenario/1` file meant — reaches the core through a registry, and nothing in the
core knows the answer in advance.

## Status, stated plainly

- Written from a static reading of `james-sheen/qa-orchestrator` at `d136ca7` (commit B),
  the two diffs, and the upstream `arbiter` `BRIDGES.md` (the "engine litmus": the engine
  decides nothing by asking which domain it is in, checked structurally).
- **The suite has since been run**, on 2026-09-05, when this tree was migrated into the
  repository. It passed 68 of 68 on the first attempt. Three things it did not cover
  came out of that migration and are fixed here: the module scan located the package by
  a hardcoded relative path, so moving the tree under `src/` made two of its three
  domain-free assertions pass by reading an empty directory; the example referee's
  executable bit does not survive every way a tree is distributed, and the suite could
  not see it because its fixture sets the bit on a copy; and there was no negative
  control, so nothing here could have failed if the harness had broken into always
  reporting success.
- **Migration step 1 below named a symbol that does not exist.** It said to import
  `BackendUnavailable` from `vocabulary`; the exception is `SubstrateUnavailable`.
  Corrected in place.
- **Not carried over**: the three hardware tiers (`mock`, `qemu`, `testbed` — they move,
  see *Migration*), the CI workflow, the hygiene and commit-message tools, and the 0.2.x
  README prose. Nothing here needs `bmc-sensor-audit` to be installed.

## What was locking the harness to one domain, and where each lock went

| # | Lock, as of `d136ca7` | Where it lived | 0.3 |
|---|---|---|---|
| 1 | Five verbs as literals, dispatched by `if/elif`; no way to add one | `scenario.ACTIONS`, `run.py` | `actions.Verb` + `register_verb()`. The built-in five are defined the same way. A verb validates its payload at parse time with the phase named, and does its work at run time. |
| 2 | Every value coerced with `float()` at the harness layer | `run.py` | Values pass through untouched. What a value *is* belongs to the tier. The paper example's values are sentences. |
| 3 | Referee identity, argv, report schema, `sha256:` handle shape as literals | `referee.py` | `referee.Tool` (commit B's idea, completed). **No built-in referee in the core**: `bmc-sensor-audit` is a vertical (`verticals/bmc.py`) registered through an entry point, like any outside vertical. |
| 4 | A `qa-scenario/1` file with no `referee:` meant one program, by name, in the parser | `scenario.py` | `referee.set_legacy_default()` — a slot the vertical fills when it registers. The core carries no name. A v1 file without the vertical loaded is refused by name. |
| 5 | `names`/`not_names` judged by scraping prose in the shape of one tool's stanza; the profile's `findings_key`/`subject_keys` read by nothing on the run path | `compare.py`, `referee.names_mentioned` | The comparator judges from the JSON report through `ReportSchema`. Prose is read **only** when the profile declares no JSON form for the mode, and every such mismatch is tagged `(stdout; this referee prints no JSON for this mode)`. |
| 6 | Nothing could assert on what the referee *did not* check, or on how many evaluations it attempted — the two halves of an arbiter envelope | expectation vocabulary | `expect.referee.declines` and `expect.referee.checked`, read through `ReportSchema.declines` / `.checked`. Refused at parse time when the profile declares no such field or the mode has no JSON. |
| 7 | `register()` was a Python call; `qa-orchestrator check/run` could not reach it | `cli.py` | `plugins.py`: entry points (`qa_orchestrator.plugins`), `QA_ORCHESTRATOR_PLUGINS`, `--plugin`. A plugin that fails is exit 2 with the cause, never a skip. `qa-orchestrator list` shows what a process can name. |
| 8 | `PRESENCE` spelled twice; a tier's `state()` never checked against it | `scenario.py`, `run.py` | One `PRESENCE` in `vocabulary.py`; `substrate.observe()` refuses a tier that answers outside it, so *gone* ends the run as could-not-complete naming the tier, not as a mismatch that reads like an injection that did not take. |
| 9 | A scenario spelling one thing two ways (`substrate` + `firmware`, `entities` + `sensors`, …) read silently, one dropped | five sites | `actions.one_of()` refuses, naming both spellings and the phase. |
| 10 | `config:` always resolved as a file beside the scenario | `scenario.py` | `Tool.configs_are_paths`; a tool that takes a rule-set name or a URL gets it verbatim. |
| 11 | A declared handle shape that never matched degraded to `None`; a tool with no validator could not be profiled | `referee.py` | `Capture.digest_missing` is said per capture and in the evidence block; `validate_argv=None` is allowed and every capture then reads `UNVALIDATED` in the evidence. |
| 12 | No tier a vertical could use without writing one | `backends/` | `memory`: entities in a dictionary, written as a `qa-memory/1` snapshot file on every `start()`. Most verticals whose faults are presence and value need nothing else. |
| 13 | The run never said which referee graded it | `cli.py`, `run.py` | Header line, `referee: <name> at <path>` event, `RunResult.referee_path`, and the summary line. |
| 14 | Registries validated nothing: `Tool(modes=())` became an `IndexError` traceback in `check`; duplicates overwrote silently | `referee.py`, `backends/__init__.py` | `Tool.__post_init__`, `ReportSchema.__post_init__`, `Verb.__post_init__`; duplicates refused; `unregister*()` is the written-down way to replace. |

Items 5–7 are the ones that decide whether "reusable" is true. Without 5 the profile's
report schema is decoration; without 6 an arbiter-based vertical cannot assert on the
engine's most important output; without 7 a vertical cannot run `check` in its own CI.

## Architecture

```
src/qa_orchestrator/          (the tree is a `src/` layout, so an import cannot
                              silently resolve to the checkout instead of the wheel)
  vocabulary.py      PRESENCE and every exception. Names no domain.
  substrate.py       Substrate protocol; register/unregister/known/build; observe() (the PRESENCE seam)
  actions.py         Verb; register_verb/unregister_verb/known_verbs/resolve; one_of(); the built-in five
  referee.py         Tool, ReportSchema, Verdict, Capture; register_tool/…/profile; legacy default slot;
                     executable/capture/validate/judge (the subprocess and 0/1/2 layer — fixed)
  scenario.py        qa-scenario/2, with /1 read through aliases; asks the three registries
  compare.py         pure comparison; report first, prose only when there is no report
  run.py             perturb → capture → observe → judge → compare; never raises, reports
  plugins.py         entry points, environment, --plugin; loud on failure
  cli.py             run / check / list; plugins resolved before any scenario is read
  substrates/memory.py   the one built-in tier
  verticals/bmc.py       the first vertical, as a plugin: its Tool, its v1-default claim, its tiers' hook
examples/paper/        a vertical sharing no vocabulary with the first: tier + verb + referee + scenario
tests/                 run 2026-09-05; see Status
```

Three registries, one shape each: `register` refuses a taken name, `unregister` is the
only way to replace, `known()` is asked by the parser, and an unknown name is refused
with what *is* known listed. The core never imports `verticals/`;
`tests/test_registries.py::TestTheCoreNamesNoVertical` checks it structurally, using the
names the shipped vertical registers rather than a word list.

## The contract: what stays fixed, on purpose

A vertical brings a tier, verbs, a referee profile and scenarios. It cannot change:

- **The referee is a subprocess** found on `PATH` by the name in its profile. A tool that
  is a library or a service needs a small command-line shim, and the shim belongs to the
  vertical. This is the boundary that stops the harness marking the exam with the answer
  key.
- **The exit contract is `0/1/2`**: clean, findings, could-not-complete. `2` never reads as
  clean anywhere. A profile supplies argv after the executable and key names in the
  report; it has no say in how an exit code is read.
- **The three questions**: `capture(handle, out)` writes a file; `validate(path)` (optional)
  says whether it is well formed; `judge(mode, configs, captures)` is handed **every
  capture taken so far, oldest first**. A referee that judges one snapshot takes the last.
- **A phase does one thing**, then takes `captures ≥ 1` observations, then is judged.
- **A tier answers `state()` from itself**, in `PRESENCE`, and is asked for its handle
  before every capture.

## Scenario format

`qa-scenario/2` is the general vocabulary. `qa-scenario/1` files are read unchanged
through the aliases in the table; the three shipped ones parse (see
`tests/test_scenario_compat.py`). A file that uses both spellings of one thing is refused.

```yaml
format: qa-scenario/2
name: a requirement withdrawn, one unanswered, one contradicted
substrate: paper                 # a registered tier; `memory` is built in
referee: proposal-review         # a registered profile; required in v2
mode: review                     # whatever that profile's modes say; default is its first
config: rules.json               # a path beside this file, unless the profile says otherwise

setup:                           # handed verbatim to the tier's factory
  entities:
    - {name: R-3.2, value: "the pump shall stop within 2 s of a level alarm"}

phases:
  - note: R-3.2 is withdrawn
    captures: 1
    action: {remove: R-3.2}      # remove | disable | fail | set | drive | <registered>
    expect:
      referee:
        exit: 1
        findings: {text: "declared and absent", names: [R-3.2], not_names: [R-7.1]}
        declines: {reason: no_answer, names: [R-7.1]}      # only if the profile declares them
        checked: {exact: 1}                                 # or an integer, or {at_least: N}
      substrate: {R-3.2: absent, R-7.1: reading}           # read from the tier, never assumed
```

| v1 | v2 | Note |
|---|---|---|
| `backend:` | `substrate:` | |
| `machine:` | `setup:` | passed verbatim to the tier; a tier's own key aliases are its business |
| `walks:` | `captures:` | |
| `drift:` | `set:` | |
| `sensor` / `sensors` in `set`/`drive` | `entity` / `entities` | |
| `fail: {path, status}` | `fail: {region, status}` | `status` is passed through, not coerced |
| `expect.audit` | `expect.referee` | `finding`, `names`, `not_names` lift into `findings:` |
| `expect.firmware` | `expect.substrate` | `within_walks` is refused: it was read by nothing |
| no `referee:` | (required) | a v1 file means whichever loaded vertical claimed the v1 default |

Refused at parse time, with the phase named: an unknown substrate, referee, mode or verb
(each listing what exists); a `declines`/`checked` expectation against a profile that
declares no such field, or a mode with no JSON; a state outside `PRESENCE`; an empty
expectation; `drive` shorter than the phase; any key spelled both ways.

## The `memory` tier

`setup.entities` is a list of names or `{name, value, …extra}` mappings (`reading` is
accepted as `value` for v1 files). `start()` writes:

```json
{"format": "qa-memory/1",
 "entities": {"R-3.2": {"value": "…"}, "Fan1": {"value": null, "min_rpm": 800}},
 "errors": {"/region": 500}}
```

and returns the path. A removed entity is not in `entities`; a disabled one has `value`
null; `fail` records the region and status under `errors` so a referee can report a
partial capture. Extra fields ride along, so a referee that reads thresholds or roles
beside a value can find them. `record(entity)` is public so a tier built on this one can
add its own verbs against the same records — `examples/paper/vertical.py` adds
`contradict`.

## Writing a vertical

`examples/paper/` is the template. In order:

1. **Tier** — subclass `MemorySubstrate` or implement the six-method protocol. Refuse
   what you cannot do; never no-op.
2. **Verbs** — only for faults the built-in five cannot say. `validate(payload, where,
   captures)` returns the normalised payload or raises `ScenarioError(f"{where}: …")`;
   `apply(substrate, payload)` refuses a tier that lacks the method.
3. **Profile** — a `Tool`. Decide `validate_argv` (None is allowed and visible),
   `json_argv` per mode, the `ReportSchema` keys including `declines` and `checked` if the
   tool reports them, `digest_pattern` (None if it prints no handle), and
   `configs_are_paths`.
4. **`register()`** in one module, returning a one-line summary; **`unregister()`** beside
   it for tests. Declare it on the `qa_orchestrator.plugins` entry point in your own
   `pyproject.toml`, or run with `--plugin path/to/module.py`.
5. **Scenarios** in `qa-scenario/2`. Every phase should carry both a `referee` and a
   `substrate` expectation where it can: *the entity is gone* and *the referee noticed*
   are separate facts, and a scenario that can only say the second cannot tell a broken
   injector from a blind referee.
6. **A wrong-on-purpose scenario** in your CI, as the 0.2.x workflow does with `sed`: a
   harness that broke into always passing sails through every scenario that is expected
   to pass.

## Migrating the 0.2.x repository

1. Move `src/qa_orchestrator/backends/{mock,qemu,testbed}.py` to
   `qa_orchestrator/verticals/bmc_tiers.py` (or a package of that name) and expose
   `TIERS = {"mock": MockBackend, "qemu": QemuBackend, "testbed": TestbedBackend}`.
   Change `from . import BackendUnavailable` to `from ..vocabulary import
   SubstrateUnavailable` -- the exception was renamed with the module, and an earlier
   draft of this line named the old one.
   The tiers' `set_reading` needs no rename: `substrate.set_value()` calls it when
   `set_value` is absent. `fail(path, status)` is called positionally, so its parameter
   names can stay. `verticals/bmc.py::register()` picks the module up when it exists and
   says in its summary when it does not.
2. `tests/test_boundary.py`: the *referee.py does not import the referee* and *compare.py
   does not either* checks stand; the *only the mock backend may import the tool* check
   moves to the vertical (`verticals/bmc_tiers.py` is now the only place the import is
   correct).
3. `tests/test_capture.py`: `executable` takes a required `tool`; pass
   `verticals.bmc.BMC_SENSOR_AUDIT` to `capture`/`judge`. The three-question tests are
   otherwise unchanged in intent.
4. `tests/test_entity_vocabulary.py` and `tests/test_referee_profile.py` are superseded by
   `tests/test_paper_vertical.py` and `tests/test_scenario_compat.py`; keep any case not
   covered (the QMP framing tests belong with the tiers).
5. CI: `pip install -e '.[bmc,dev]'`; `qa-orchestrator check src/qa_orchestrator/verticals/bmc_scenarios/` works because the
   entry point loads the vertical -- the scenarios moved in with the tiers, so they are
   the vertical's and reach the wheel with it; add
   `PATH=examples/paper/bin:$PATH qa-orchestrator --plugin examples/paper/vertical.py run examples/paper/withdrawn.yaml`
   and its wrong-on-purpose twin; keep the `testbed` refusal step, calling
   `substrate.build("testbed", {})` after loading the plugin.
6. `pyproject.toml`: extra `[referee]` becomes `[bmc]`; version `0.3.0`; the scenario
   format bumps to `/2` because a v1 reader given a v2 file would refuse it by name (the
   test the 0.2.x README states), and this time the vocabulary moved, not only grew.
7. README: the "three tiers" table becomes the vertical's; "A fourth tier is yours to add"
   and "And the program that grades it is yours too" collapse into *Writing a vertical*
   above; the exit-code section stands.

## What still does not generalise

- A referee must be a command-line program with the capture/judge shape. That is the
  architecture, not an omission — but it means a vertical whose tool is a library pays for
  a shim.
- `findings.text` is substring matching on a text field the profile names. A tool whose
  findings are coded rather than worded will want `findings.kind` against a declared key.
  `ReportSchema` has no such field yet and neither does the expectation vocabulary, so
  this is an addition rather than a wiring job.

  **Met once already.** `partial-walk.yaml` asserted `walk did not finish`, which is the
  first vertical's referee saying so in PROSE; its report carries the same fact as
  `kind: walk_incomplete`, a top-level `walk_complete: false`, and a `detail` sentence.
  With findings judged from the report, the prose expectation could not hold, and the
  file now asserts the `detail` sentence -- weaker than the coded `kind` and the only
  place a `qa-scenario/1` file did not survive this rewrite unchanged.
- `fail`'s `region` and `status` are passed through unvalidated: the harness cannot know
  what shape a tier takes, so a typo there is the tier's to refuse. The `memory` tier
  accepts anything.
- The example referee and the tests assume a POSIX `PATH` and an executable bit.
- The registries are process-global. A test that registers and does not unregister makes
  the next test refuse the wrong name; `conftest.py` unregisters after every test for
  that reason.
