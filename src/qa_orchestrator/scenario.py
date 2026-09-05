"""The scenario format: what a run does, and what it expects, in one file.

**Everything checked at parse time, with the phase named.** A phase with no
captures, an `expect` block that sets nothing, a verb this build does not have,
a `drive` with fewer values than captures, an expectation on a report field the
referee's profile does not declare -- all refused before anything runs. Each
would otherwise produce a run that executed, reported clean, and tested nothing,
which is indistinguishable from a real pass at the exit code.

**Every name is asked of a registry, never of a copy kept here.** Substrates,
verbs, referees and the referee's modes come from `substrate`, `actions` and
`referee`. A second copy of any of those lists is what once made `register` a
door into a room with no entrance.

Two formats are read. `qa-scenario/2` is the general vocabulary. `qa-scenario/1`
is what every scenario written before it says -- `backend`, `machine`, `walks`,
`sensors`, `expect.audit`, `expect.firmware` -- and those files are on disk and
published. A file that spells a thing BOTH ways is refused, because a reader
that picked one would drop the other without a word.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import actions, referee, substrate
from .actions import one_of
from .vocabulary import PRESENCE, ScenarioError

FORMATS = ("qa-scenario/1", "qa-scenario/2")
FORMAT = FORMATS[-1]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioError(message)


# -- what a phase expects ------------------------------------------------------

@dataclass(frozen=True)
class FindingsExpectation:
    """Which findings the report should carry, and which subjects it must not name."""

    text: str | None = None
    names: tuple[str, ...] = ()
    not_names: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return self.text is None and not self.names and not self.not_names


@dataclass(frozen=True)
class DeclinesExpectation:
    """Which evaluations the referee should have DECLINED, and said so."""

    reason: str | None = None
    names: tuple[str, ...] = ()
    not_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckedExpectation:
    """How many evaluations the referee should report having attempted."""

    exact: int | None = None
    at_least: int | None = None


@dataclass(frozen=True)
class RefereeExpectation:
    exit_code: int | None = None
    findings: FindingsExpectation | None = None
    declines: DeclinesExpectation | None = None
    checked: CheckedExpectation | None = None

    def is_empty(self) -> bool:
        return (self.exit_code is None and self.findings is None
                and self.declines is None and self.checked is None)


@dataclass(frozen=True)
class SubstrateExpectation:
    """What the substrate itself should look like, read from it, not from the scenario."""

    states: dict[str, str]


@dataclass(frozen=True)
class Phase:
    index: int
    captures: int
    action: tuple[str, Any] | None
    expect_referee: RefereeExpectation | None
    expect_substrate: SubstrateExpectation | None
    note: str | None = None

    @property
    def asserts_anything(self) -> bool:
        return self.expect_referee is not None or self.expect_substrate is not None

    def describe(self) -> str:
        what = f"phase {self.index}"
        if self.note:
            what += f": {self.note}"
        if self.action:
            what += f"  [{self.action[0]}]"
        return f"{what}  ({self.captures} capture(s))"


@dataclass(frozen=True)
class Scenario:
    name: str
    format: str
    substrate: str
    setup: dict[str, Any]
    referee: str
    mode: str
    config: tuple[str, ...]
    phases: tuple[Phase, ...]
    source: Path | None = None

    @property
    def total_captures(self) -> int:
        return sum(p.captures for p in self.phases)

    # 0.2.x spellings, so a caller written against them still reads.
    @property
    def backend(self) -> str:
        return self.substrate

    @property
    def machine(self) -> dict[str, Any]:
        return self.setup


# -- readers -------------------------------------------------------------------

def _names(raw: Any, where: str, key: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    _require(isinstance(raw, list), f"{where}: {key} must be a list of names")
    return tuple(str(n) for n in raw)


def _parse_findings(raw: Any, where: str) -> FindingsExpectation:
    _require(isinstance(raw, dict), f"{where}: findings must be a mapping")
    unknown = set(raw) - {"text", "names", "not_names"}
    _require(not unknown, f"{where}: findings has unknown key(s) {sorted(unknown)}; "
                          f"known keys are text, names, not_names")
    text = raw.get("text")
    _require(text is None or (isinstance(text, str) and text),
             f"{where}: findings.text must be a non-empty string")
    names, not_names = _names(raw.get("names"), where, "names"), _names(raw.get("not_names"), where, "not_names")
    overlap = set(names) & set(not_names)
    _require(not overlap, f"{where}: {sorted(overlap)} is in both names and not_names, "
                          f"which cannot both hold")
    found = FindingsExpectation(text=text, names=names, not_names=not_names)
    _require(not found.is_empty(), f"{where}: findings sets nothing")
    return found


def _parse_declines(raw: Any, where: str, tool: referee.Tool) -> DeclinesExpectation:
    _require(tool.report.declines is not None,
             f"{where}: expects declines, but {tool.name}'s profile declares no "
             f"declines list in its report, so this could never hold")
    _require(isinstance(raw, dict), f"{where}: declines must be a mapping")
    unknown = set(raw) - {"reason", "names", "not_names"}
    _require(not unknown, f"{where}: declines has unknown key(s) {sorted(unknown)}")
    reason = raw.get("reason")
    _require(reason is None or (isinstance(reason, str) and reason),
             f"{where}: declines.reason must be a non-empty string")
    names, not_names = _names(raw.get("names"), where, "names"), _names(raw.get("not_names"), where, "not_names")
    _require(reason is not None or names or not_names, f"{where}: declines sets nothing")
    return DeclinesExpectation(reason=reason, names=names, not_names=not_names)


def _parse_checked(raw: Any, where: str, tool: referee.Tool) -> CheckedExpectation:
    _require(tool.report.checked is not None,
             f"{where}: expects a checked count, but {tool.name}'s profile declares "
             f"no denominator in its report, so this could never hold")
    if isinstance(raw, int) and not isinstance(raw, bool):
        return CheckedExpectation(exact=raw)
    _require(isinstance(raw, dict), f"{where}: checked must be an integer or "
                                    f"{{exact: N}} / {{at_least: N}}")
    unknown = set(raw) - {"exact", "at_least"}
    _require(not unknown, f"{where}: checked has unknown key(s) {sorted(unknown)}")
    _require(bool(raw), f"{where}: checked sets nothing")
    for key, value in raw.items():
        _require(isinstance(value, int) and not isinstance(value, bool) and value >= 0,
                 f"{where}: checked.{key} must be a non-negative integer")
    return CheckedExpectation(exact=raw.get("exact"), at_least=raw.get("at_least"))


def _parse_referee_expectation(raw: Any, where: str, tool: referee.Tool,
                               spelling: str, mode: str) -> RefereeExpectation:
    _require(isinstance(raw, dict), f"{where}: expect.{spelling} must be a mapping")
    if spelling == "audit":
        # v1: `finding`, `names`, `not_names` sit beside `exit`. Lifted into the
        # v2 shape once, here, so the comparator has one thing to read.
        unknown = set(raw) - {"exit", "finding", "names", "not_names"}
        _require(not unknown, f"{where}: expect.audit has unknown key(s) {sorted(unknown)}; "
                              f"known keys are exit, finding, names, not_names")
        lifted = {k: raw[k] for k in ("names", "not_names") if k in raw}
        if "finding" in raw:
            lifted["text"] = raw["finding"]
        raw = {"exit": raw["exit"]} if "exit" in raw else {}
        if lifted:
            raw["findings"] = lifted
    unknown = set(raw) - {"exit", "findings", "declines", "checked"}
    _require(not unknown, f"{where}: expect.referee has unknown key(s) {sorted(unknown)}; "
                          f"known keys are exit, findings, declines, checked")
    exit_code = raw.get("exit")
    _require(exit_code is None or (isinstance(exit_code, int) and not isinstance(exit_code, bool)),
             f"{where}: expect.{spelling}.exit must be an integer")
    expectation = RefereeExpectation(
        exit_code=exit_code,
        findings=_parse_findings(raw["findings"], where) if "findings" in raw else None,
        declines=_parse_declines(raw["declines"], where, tool) if "declines" in raw else None,
        checked=_parse_checked(raw["checked"], where, tool) if "checked" in raw else None)
    _require(not expectation.is_empty(),
             f"{where}: expect.{spelling} sets nothing, so it would assert nothing "
             f"while looking like an assertion")
    # Findings can be judged from prose when a mode has no JSON, and every such
    # mismatch says so. Declines and the denominator cannot: there is no prose
    # shape for *what was not checked* that a comparator could read honestly.
    for what in ("declines", "checked"):
        if getattr(expectation, what) is not None:
            _require(tool.has_json(mode),
                     f"{where}: expects {what}, but {tool.name} has no JSON form for "
                     f"mode {mode!r}, so they could not be read")
    return expectation


def _parse_substrate_expectation(raw: Any, where: str, spelling: str) -> SubstrateExpectation:
    _require(isinstance(raw, dict), f"{where}: expect.{spelling} must be a mapping")
    _require("within_walks" not in raw and "within_captures" not in raw,
             f"{where}: expect.{spelling}.within_* was read by nothing in 0.2.x and is "
             f"not implemented; remove it rather than carry a key that asserts nothing")
    states = {str(k): v for k, v in raw.items()}
    _require(bool(states), f"{where}: expect.{spelling} names no entity states")
    for entity, state in states.items():
        _require(state in PRESENCE,
                 f"{where}: expect.{spelling}.{entity} is {state!r}; expected one of "
                 f"{', '.join(PRESENCE)}")
    return SubstrateExpectation(states={k: str(v) for k, v in states.items()})


def _parse_expect(raw: Any, where: str, tool: referee.Tool, mode: str
                  ) -> tuple[RefereeExpectation | None, SubstrateExpectation | None]:
    if raw is None:
        return None, None
    _require(isinstance(raw, dict), f"{where}: expect must be a mapping")
    unknown = set(raw) - {"referee", "audit", "substrate", "firmware"}
    _require(not unknown, f"{where}: expect has unknown key(s) {sorted(unknown)}; "
                          f"known keys are referee and substrate")

    on_referee = on_substrate = None
    if "referee" in raw or "audit" in raw:
        spelling, block = one_of(raw, ("referee", "audit"), where, "expect.referee")
        on_referee = _parse_referee_expectation(block, where, tool, spelling, mode)
    if "substrate" in raw or "firmware" in raw:
        spelling, block = one_of(raw, ("substrate", "firmware"), where, "expect.substrate")
        on_substrate = _parse_substrate_expectation(block, where, spelling)
    _require(on_referee is not None or on_substrate is not None,
             f"{where}: expect is present and empty")
    return on_referee, on_substrate


def _parse_action(raw: Any, where: str, captures: int) -> tuple[str, Any] | None:
    if raw is None:
        return None
    _require(isinstance(raw, dict), f"{where}: action must be a mapping")
    _require(len(raw) == 1,
             f"{where}: action must name exactly one verb, got {sorted(raw)}. Two "
             f"actions in one phase cannot be attributed when a verdict moves")
    name, payload = next(iter(raw.items()))
    verb = actions.resolve(str(name), where)
    return verb.name, verb.validate(payload, where, captures)


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
    _require(declared in FORMATS,
             f"format is {declared!r}; this build reads {' and '.join(FORMATS)}. The "
             f"version is checked rather than assumed because separate programs "
             f"read this file")
    v1 = declared == FORMATS[0]

    unknown = set(raw) - {"format", "name", "substrate", "backend", "setup", "machine",
                          "referee", "mode", "config", "phases"}
    _require(not unknown, f"unknown top-level key(s) {sorted(unknown)}")

    tiers = substrate.known()
    _, tier = one_of(raw, ("substrate", "backend"), "scenario", "substrate")
    _require(tier in tiers,
             f"substrate is {tier!r}; this build has {list(tiers)}. A vertical's tier "
             f"is registered by loading its plugin")

    setup: dict[str, Any] = {}
    if "setup" in raw or "machine" in raw:
        _, setup = one_of(raw, ("setup", "machine"), "scenario", "setup")
        _require(isinstance(setup, dict), "setup must be a mapping")

    # The referee, and then the modes ITS profile declares. A v1 file that names
    # none means the one program that ever graded v1 files; which program that is
    # belongs to a vertical, and the vertical says so when it registers.
    referee_name = raw.get("referee")
    if referee_name is None:
        _require(v1, "a scenario must name its referee")
        referee_name = referee.legacy_default()
        _require(referee_name is not None,
                 "this qa-scenario/1 file names no referee, and no loaded vertical "
                 "declares the v1 default; load the vertical that grades v1 files, "
                 "or add `referee:`")
    tools = referee.known_tools()
    _require(referee_name in tools,
             f"referee is {referee_name!r}; this build has {list(tools)}. A vertical's "
             f"referee is registered by loading its plugin")
    tool = referee.profile(str(referee_name))

    mode = raw.get("mode", tool.modes[0])
    _require(mode in tool.modes, f"mode is {mode!r}; {tool.name} has {list(tool.modes)}")

    config = raw.get("config")
    _require(config is not None, "a scenario must name a config to judge against")
    config = tuple(str(c) for c in config) if isinstance(config, list) else (str(config),)
    # Relative to the scenario file, not to whoever ran it -- when the profile
    # says configs are files at all.
    if source is not None and tool.configs_are_paths:
        base = Path(source).resolve().parent
        config = tuple(str(Path(entry) if Path(entry).is_absolute()
                           else (base / entry).resolve()) for entry in config)

    raw_phases = raw.get("phases")
    _require(isinstance(raw_phases, list) and bool(raw_phases),
             "a scenario must have at least one phase")

    phases = []
    for index, raw_phase in enumerate(raw_phases, start=1):
        where = f"phase {index}"
        _require(isinstance(raw_phase, dict), f"{where}: must be a mapping")
        unknown = set(raw_phase) - {"captures", "walks", "action", "expect", "note"}
        _require(not unknown, f"{where}: unknown key(s) {sorted(unknown)}")

        captures = 1
        if "captures" in raw_phase or "walks" in raw_phase:
            _, captures = one_of(raw_phase, ("captures", "walks"), where, "captures")
        _require(isinstance(captures, int) and not isinstance(captures, bool) and captures > 0,
                 f"{where}: captures must be a positive integer, got {captures!r}. A "
                 f"phase that takes no capture gathers no evidence")

        action = _parse_action(raw_phase.get("action"), where, captures)
        on_referee, on_substrate = _parse_expect(raw_phase.get("expect"), where, tool, str(mode))
        note = raw_phase.get("note")
        phases.append(Phase(index=index, captures=captures, action=action,
                            expect_referee=on_referee, expect_substrate=on_substrate,
                            note=str(note) if note is not None else None))

    name = raw.get("name") or (source.stem if source else "unnamed")
    return Scenario(name=str(name), format=str(declared), substrate=str(tier),
                    setup=setup, referee=str(referee_name), mode=str(mode),
                    config=config, phases=tuple(phases), source=source)


def load(path: str | Path) -> Scenario:
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as error:
        raise ScenarioError(f"cannot read {path}: {error}") from error
    return parse(text, source=path)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "scenario"
