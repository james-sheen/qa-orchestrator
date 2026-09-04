"""Parse and validate a `qa-scenario/1` file.

A scenario is an ordered list of phases. Each phase does something to the machine,
takes some walks, and states what the referee should conclude. The format is
versioned from the first commit because the orchestrator, the backends and the
pipeline templates all read it, and a format three consumers share is one that
cannot be changed quietly.

**Validation refuses rather than defaults.** A phase naming an action this build
does not implement, an `expect` block with no expectations in it, or a walk count
of zero are all rejected at parse time with the phase index named. The alternative
is a scenario that runs, reports clean, and tested nothing -- which is the failure
this whole family is built to make impossible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import backends
from .referee import known_tools, profile

FORMAT = "qa-scenario/1"

# Every action this build can perform. A closed set, checked at parse time: an
# unrecognised action must stop the run, because the phase that would have
# perturbed the machine is exactly the phase whose absence makes everything
# afterwards pass for the wrong reason.
ACTIONS = {
    "remove":  "make an entity vanish entirely (for a BMC, the firmware-upgrade case)",
    "disable": "switch an entity off; it stays declared and stops reporting",
    "fail":    "make a region answer with an error status (a partial read)",
    "drift":   "move an entity's value, once",
    "drive":   "set an entity's value before each walk of this phase, in order",
}

class ScenarioError(ValueError):
    """A scenario that cannot be run as written. Always names where."""


@dataclass(frozen=True)
class Expectation:
    """What the referee should conclude at the end of a phase.

    `exit` is the tool's own exit code. `finding` is a substring that must appear
    in the human report, `names` are sensors that must be named. All optional
    individually -- but an `expect` block that sets none of them is refused, since
    it would assert nothing while looking like an assertion.
    """
    exit_code: int | None = None
    finding: str | None = None
    names: tuple[str, ...] = ()
    not_names: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return (self.exit_code is None and self.finding is None
                and not self.names and not self.not_names)


@dataclass(frozen=True)
class FirmwareExpectation:
    """What the MACHINE should look like, independent of what the referee said.

    Kept separate from `Expectation` on purpose. *The fan is gone* and *the tool
    noticed the fan is gone* are two different claims, and a scenario that could
    only express the second could never tell a broken injector from a broken
    referee.
    """
    states: dict[str, str] = field(default_factory=dict)
    within_walks: int | None = None


@dataclass(frozen=True)
class Phase:
    index: int
    walks: int
    action: tuple[str, Any] | None = None
    expect: Expectation | None = None
    expect_firmware: FirmwareExpectation | None = None

    def describe(self) -> str:
        if self.action is None:
            return f"phase {self.index}: {self.walks} walk(s), no action"
        verb, payload = self.action
        return f"phase {self.index}: {verb} {payload!r}, then {self.walks} walk(s)"


@dataclass(frozen=True)
class Scenario:
    name: str
    backend: str
    config: tuple[str, ...]
    phases: tuple[Phase, ...]
    machine: dict[str, Any] = field(default_factory=dict)
    mode: str = "detect"
    #: Which program grades the run. Named, because a vertical that supplies its
    #: own substrate has its own tool to grade with, and `mode` means whatever
    #: that tool says it means.
    referee: str = "bmc-sensor-audit"
    source: Path | None = None

    @property
    def total_walks(self) -> int:
        return sum(p.walks for p in self.phases)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioError(message)


def drive_series(payload: dict) -> dict[str, list]:
    """Normalise every form of `drive` to `{entity: [values]}`.

    One reader for all spellings, so the sugar cannot come to mean something
    slightly different from the general form.

    `entity`/`entities` is the backend protocol's vocabulary; `sensor`/`sensors`
    is what every scenario written before it says. Both are read, and no format
    bump goes with the addition: the test for that is whether an OLDER reader
    would SILENTLY IGNORE the new key, and it would not -- it validates the
    action payload and refuses `entity` by name. A loud refusal is a reader
    correctly declining a file it does not understand, which is what the format
    version already means.
    """
    plural = payload.get("entities") or payload.get("sensors")
    if plural:
        return {str(name): list(values) for name, values in plural.items()}
    name = payload.get("entity", payload.get("sensor"))
    return {str(name): list(payload["values"])}


def _parse_expect(raw: Any, where: str) -> tuple[Expectation | None, FirmwareExpectation | None]:
    if raw is None:
        return None, None
    _require(isinstance(raw, dict), f"{where}: expect must be a mapping")

    audit = raw.get("audit")
    expectation = None
    if audit is not None:
        _require(isinstance(audit, dict), f"{where}: expect.audit must be a mapping")
        unknown = set(audit) - {"exit", "finding", "names", "not_names"}
        _require(not unknown,
                 f"{where}: expect.audit has unknown key(s) {sorted(unknown)}; "
                 f"known keys are exit, finding, names, not_names")
        names = audit.get("names") or []
        not_names = audit.get("not_names") or []
        for key, value in (("names", names), ("not_names", not_names)):
            _require(isinstance(value, list),
                     f"{where}: expect.audit.{key} must be a list")
        overlap = set(map(str, names)) & set(map(str, not_names))
        _require(not overlap,
                 f"{where}: {sorted(overlap)} is in both names and not_names, "
                 f"which cannot both hold")
        expectation = Expectation(exit_code=audit.get("exit"),
                                  finding=audit.get("finding"),
                                  names=tuple(str(n) for n in names),
                                  not_names=tuple(str(n) for n in not_names))
        _require(not expectation.is_empty(),
                 f"{where}: expect.audit sets nothing, so it would assert nothing "
                 f"while looking like an assertion")

    # `substrate` is the general spelling; `firmware` is what shipped scenarios
    # say. An older reader given `substrate` refuses it by name below, so this
    # addition has no silent-drop path and needs no format bump.
    firmware = raw.get("substrate", raw.get("firmware"))
    firmware_expectation = None
    if firmware is not None:
        _require(isinstance(firmware, dict), f"{where}: expect.firmware must be a mapping")
        within = firmware.get("within_walks")
        states = {k: str(v) for k, v in firmware.items() if k != "within_walks"}
        _require(bool(states),
                 f"{where}: expect.firmware names no sensor states")
        for sensor, state in states.items():
            _require(state in {"absent", "disabled", "reading"},
                     f"{where}: expect.firmware.{sensor} is {state!r}; "
                     f"expected absent, disabled or reading")
        firmware_expectation = FirmwareExpectation(states=states, within_walks=within)

    unknown = set(raw) - {"audit", "firmware", "substrate"}
    _require(not unknown, f"{where}: expect has unknown key(s) {sorted(unknown)}")
    _require(expectation is not None or firmware_expectation is not None,
             f"{where}: expect is present and empty")
    return expectation, firmware_expectation


def _parse_action(raw: Any, where: str) -> tuple[str, Any] | None:
    if raw is None:
        return None
    _require(isinstance(raw, dict), f"{where}: action must be a mapping")
    _require(len(raw) == 1,
             f"{where}: action must name exactly one verb, got {sorted(raw)}. "
             f"Two actions in one phase cannot be attributed when a verdict moves")
    verb, payload = next(iter(raw.items()))
    _require(verb in ACTIONS,
             f"{where}: unknown action {verb!r}. This build implements "
             f"{', '.join(sorted(ACTIONS))} -- an unrecognised verb is refused rather "
             f"than skipped, because a phase that silently does nothing makes every "
             f"phase after it pass for the wrong reason")
    if verb == "drive":
        # Two forms. `sensors: {name: [...]}` is the general one and `sensor` +
        # `values` is sugar for a single entry.
        #
        # The general form exists because the acceptance scenario demanded it.
        # Showing that the engine names EXACTLY the frozen sensor needs another
        # sensor still moving beside it, and showing it stays quiet during the
        # driven phase needs every sensor moving at once -- neither of which a
        # one-sensor verb can say, and two actions in a phase are refused because
        # a moved verdict could not then be attributed. The specification this was
        # built from says that if the harness cannot express the experiment that
        # already exists, the DSL is wrong. It could not, so this is the fix.
        key = "entities" if "entities" in payload else (
              "sensors" if "sensors" in payload else None)
        if key is not None:
            _require(isinstance(payload[key], dict) and payload[key],
                     f"{where}: drive.{key} must be a non-empty mapping of "
                     f"entity to values")
            for entity, values in payload[key].items():
                _require(isinstance(values, list) and values,
                         f"{where}: drive.{key}.{entity} must be a non-empty list")
        else:
            _require(isinstance(payload, dict)
                     and ("entity" in payload or "sensor" in payload)
                     and "values" in payload,
                     f"{where}: drive needs either entities: {{name: [...]}} or a "
                     f"single entity and values")
            _require(isinstance(payload["values"], list) and payload["values"],
                     f"{where}: drive.values must be a non-empty list")
    if verb == "drift":
        _require(isinstance(payload, dict)
                 and ("entity" in payload or "sensor" in payload) and "to" in payload,
                 f"{where}: drift needs an entity and a value to move it to")
    if verb == "fail":
        _require(isinstance(payload, dict) and "path" in payload and "status" in payload,
                 f"{where}: fail needs a path and an HTTP status")
    return verb, payload


def parse(text: str, source: Path | None = None) -> Scenario:
    """Read a scenario from YAML text. Raises `ScenarioError` with the phase named."""
    try:
        import yaml
    except ImportError as error:                                  # pragma: no cover
        raise ScenarioError("PyYAML is required to read scenario files") from error

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ScenarioError(f"not valid YAML: {error}") from error

    _require(isinstance(raw, dict), "a scenario must be a mapping")
    declared = raw.get("format")
    _require(declared == FORMAT,
             f"format is {declared!r}; this build reads {FORMAT!r}. The version is "
             f"checked rather than assumed because three separate programs read "
             f"this file")

    # Asked of the registry, never of a copy kept here. A second copy of this
    # list is what made `register` a door into a room with no entrance.
    tiers = backends.known()
    backend = raw.get("backend")
    _require(backend in tiers,
             f"backend is {backend!r}; expected one of {list(tiers)}")

    config = raw.get("config")
    _require(config is not None, "a scenario must name a config to judge against")
    config = tuple(config) if isinstance(config, list) else (str(config),)

    # **Relative to the scenario file, not to whoever ran it.** Resolving against
    # the working directory made a scenario runnable only from the directory it
    # happened to sit in: the referee could not find the config, returned exit 2,
    # and every expectation in the file mismatched at once -- so the failure read
    # as "the tool disagrees with all of this" rather than "nobody found the
    # board". A pipeline checks the repository out somewhere else and runs from a
    # workspace root, which is exactly where this bites.
    #
    # Found by composing the suite rather than by testing this repository, which
    # is the argument for the umbrella having its own end-to-end test.
    #
    # Normalised as well as resolved, so `scenarios/../fixtures/board.json` is
    # not what a failure message hands to somebody trying to find the file.
    if source is not None:
        base = Path(source).resolve().parent
        config = tuple(str(Path(entry) if Path(entry).is_absolute()
                           else (base / entry).resolve()) for entry in config)

    # The referee, and then the modes ITS profile declares. `mode` used to be
    # checked against two names written here, which are two of the built-in
    # tool's subcommands -- so a scenario could name another referee and would
    # still be held to this one's vocabulary.
    referee_name = raw.get("referee", "bmc-sensor-audit")
    tiers = known_tools()
    _require(referee_name in tiers,
             f"referee is {referee_name!r}; expected one of {list(tiers)}")
    graded_by = profile(str(referee_name))

    mode = raw.get("mode", graded_by.modes[0])
    _require(mode in graded_by.modes,
             f"mode is {mode!r}; {referee_name} has {list(graded_by.modes)}")

    raw_phases = raw.get("phases")
    _require(isinstance(raw_phases, list) and raw_phases,
             "a scenario must have at least one phase")

    phases = []
    for index, raw_phase in enumerate(raw_phases, start=1):
        where = f"phase {index}"
        _require(isinstance(raw_phase, dict), f"{where}: must be a mapping")
        unknown = set(raw_phase) - {"walks", "action", "expect", "note"}
        _require(not unknown, f"{where}: unknown key(s) {sorted(unknown)}")

        walks = raw_phase.get("walks", 1)
        _require(isinstance(walks, int) and walks > 0,
                 f"{where}: walks must be a positive integer, got {walks!r}. A phase "
                 f"that takes no walk gathers no evidence")

        action = _parse_action(raw_phase.get("action"), where)
        expectation, firmware = _parse_expect(raw_phase.get("expect"), where)

        if action and action[0] == "drive":
            for sensor, values in drive_series(action[1]).items():
                _require(len(values) >= walks,
                         f"{where}: drive supplies {len(values)} value(s) for "
                         f"{sensor} over {walks} walk(s); the last walks would "
                         f"repeat a reading and look frozen when nothing froze them")

        phases.append(Phase(index=index, walks=walks, action=action,
                            expect=expectation, expect_firmware=firmware))

    name = raw.get("name") or (source.stem if source else "unnamed")
    return Scenario(name=str(name), backend=str(backend), config=config,
                    phases=tuple(phases), machine=raw.get("machine") or {},
                    mode=mode, referee=str(referee_name), source=source)


def load(path: str | Path) -> Scenario:
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as error:
        raise ScenarioError(f"cannot read {path}: {error}") from error
    return parse(text, source=path)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "scenario"
