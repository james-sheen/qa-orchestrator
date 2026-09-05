"""What a phase may do to the substrate, as a registry rather than a closed list.

0.2.x generalised the nouns (`entity`) and opened the door for tiers
(`register`), and left the verbs as five literals dispatched by `if/elif`. A
vertical whose faults are not *gone / switched off / region fails / value moved*
-- a double posting, two requirements that contradict each other, events out of
order -- could not say so without editing three modules of this package. A verb
is now a `Verb`: how to validate its payload at parse time, and what to do with
the substrate at run time. The five built-ins are defined the same way.

**Every verb validates at parse time and names the phase.** An action that is
malformed would otherwise perturb nothing and let the phase pass, which is
indistinguishable from the referee failing to notice a real fault -- the exact
confusion this harness exists to remove.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Sequence

from .substrate import Substrate, set_value
from .vocabulary import RegistrationError, ScenarioError

Validate = Callable[[Any, str, int], Any]
Apply = Callable[[Substrate, Any], None]
PerCapture = Callable[[Substrate, Any, int], None]


@dataclass(frozen=True)
class Verb:
    """One thing a phase can do.

    `validate(payload, where, captures)` returns the normalised payload or raises
    `ScenarioError` naming `where`. `apply(substrate, payload)` runs once, before
    the phase's captures. `per_capture(substrate, payload, index)` runs before
    capture `index` (0-based) -- for a verb that changes something each time.
    """

    name: str
    describe: str
    validate: Validate
    apply: Apply | None = None
    per_capture: PerCapture | None = None
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise RegistrationError("a verb needs a non-empty name")
        if not callable(self.validate):
            raise RegistrationError(f"verb {self.name!r}: validate is not callable")
        if self.apply is None and self.per_capture is None:
            raise RegistrationError(
                f"verb {self.name!r} would do nothing: give it apply or per_capture")
        for hook in (self.apply, self.per_capture):
            if hook is not None and not callable(hook):
                raise RegistrationError(f"verb {self.name!r}: {hook!r} is not callable")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioError(message)


def one_of(payload: Any, keys: Sequence[str], where: str, what: str) -> tuple[str, Any]:
    """The one key of `keys` present in `payload`, and its value.

    A scenario that spells a thing both ways is refused, with both spellings
    named. `get(new, get(old))` would pick one and drop the other without a
    word -- a file that says two things and is read as one is exactly the case
    that executes, reports clean, and tests nothing.
    """
    _require(isinstance(payload, dict), f"{where}: {what} must be a mapping")
    present = [key for key in keys if key in payload]
    _require(len(present) <= 1,
             f"{where}: {what} is spelled both ways ({' and '.join(present)}); "
             f"they mean the same thing, so write one")
    _require(bool(present), f"{where}: {what} needs {' or '.join(keys)}")
    return present[0], payload[present[0]]


# -- registry ------------------------------------------------------------------

_REGISTERED: Dict[str, Verb] = {}
_BUILTIN: Dict[str, Verb] = {}
_ALIASES: Dict[str, str] = {}


def _install(verb: Verb, into: Dict[str, Verb]) -> None:
    taken = set(_BUILTIN) | set(_REGISTERED) | set(_ALIASES)
    for name in (verb.name, *verb.aliases):
        if name in taken:
            raise RegistrationError(
                f"verb {name!r} is already defined; unregister it first if "
                f"replacing it is what you mean")
    into[verb.name] = verb
    for alias in verb.aliases:
        _ALIASES[alias] = verb.name


def register_verb(verb: Verb) -> None:
    """Make `action: {<verb.name>: ...}` in a scenario do what `verb` says."""
    _install(verb, _REGISTERED)


def unregister_verb(name: str) -> None:
    if name in _BUILTIN:
        raise RegistrationError(f"{name!r} is a built-in verb and cannot be unregistered")
    verb = _REGISTERED.pop(name, None)
    if verb is not None:
        for alias in verb.aliases:
            _ALIASES.pop(alias, None)


def known_verbs() -> tuple[str, ...]:
    """Every verb a scenario may use, canonical names only."""
    return tuple(sorted(set(_BUILTIN) | set(_REGISTERED)))


def resolve(name: str, where: str = "action") -> Verb:
    """The verb for a name or alias, or a `ScenarioError` listing what exists."""
    canonical = _ALIASES.get(name, name)
    verb = _BUILTIN.get(canonical) or _REGISTERED.get(canonical)
    if verb is None:
        raise ScenarioError(
            f"{where}: unknown action {name!r}. This build has "
            f"{', '.join(known_verbs())} -- an unrecognised verb is refused rather "
            f"than skipped, because the phase that failed to perturb the substrate "
            f"is exactly the phase whose absence makes everything afterwards pass")
    return verb


# -- the built-in five ---------------------------------------------------------

def _entity_name(payload: Any, where: str, verb: str) -> str:
    _require(isinstance(payload, str) and bool(payload.strip()),
             f"{where}: {verb} takes an entity name, got {payload!r}")
    return payload


def _validate_remove(payload: Any, where: str, captures: int) -> str:
    return _entity_name(payload, where, "remove")


def _validate_disable(payload: Any, where: str, captures: int) -> str:
    return _entity_name(payload, where, "disable")


def _validate_fail(payload: Any, where: str, captures: int) -> dict:
    _, region = one_of(payload, ("region", "path"), where, "fail")
    _require("status" in payload, f"{where}: fail needs a region and a status")
    unknown = set(payload) - {"region", "path", "status"}
    _require(not unknown, f"{where}: fail has unknown key(s) {sorted(unknown)}")
    # `status` is passed through as written. It is the tier's own term -- an
    # HTTP code, an errno, a SQLSTATE -- and coercing it here would decide a
    # shape on the tier's behalf.
    return {"region": str(region), "status": payload["status"]}


def _validate_set(payload: Any, where: str, captures: int) -> dict:
    _, entity = one_of(payload, ("entity", "sensor"), where, "set")
    _require("to" in payload, f"{where}: set needs an entity and a value to move it to")
    unknown = set(payload) - {"entity", "sensor", "to"}
    _require(not unknown, f"{where}: set has unknown key(s) {sorted(unknown)}")
    return {"entity": str(entity), "to": payload["to"]}


def _validate_drive(payload: Any, where: str, captures: int) -> dict[str, list]:
    """Normalise every form of `drive` to `{entity: [values]}`.

    One reader for all spellings, so the sugar cannot come to mean something
    slightly different from the general form. Values are lists and are not
    coerced: what a value IS belongs to the tier.
    """
    _require(isinstance(payload, dict), f"{where}: drive must be a mapping")
    plural = [k for k in ("entities", "sensors") if k in payload]
    singular = [k for k in ("entity", "sensor") if k in payload]
    _require(not (plural and singular),
             f"{where}: drive mixes the general form ({plural[0] if plural else ''}) "
             f"with the single-entity sugar; write one")
    if plural:
        key, series = one_of(payload, ("entities", "sensors"), where, "drive")
        unknown = set(payload) - {key}
        _require(not unknown, f"{where}: drive.{key} form has unknown key(s) {sorted(unknown)}")
        _require(isinstance(series, dict) and bool(series),
                 f"{where}: drive.{key} must be a non-empty mapping of entity to values")
        normalised = {str(name): values for name, values in series.items()}
    else:
        key, entity = one_of(payload, ("entity", "sensor"), where, "drive")
        _require("values" in payload,
                 f"{where}: drive needs either entities: {{name: [...]}} or a single "
                 f"entity and values")
        unknown = set(payload) - {key, "values"}
        _require(not unknown, f"{where}: drive has unknown key(s) {sorted(unknown)}")
        normalised = {str(entity): payload["values"]}
    for name, values in normalised.items():
        _require(isinstance(values, list) and bool(values),
                 f"{where}: drive values for {name} must be a non-empty list")
        _require(len(values) >= captures,
                 f"{where}: drive supplies {len(values)} value(s) for {name} over "
                 f"{captures} capture(s); the last captures would repeat a value and "
                 f"look frozen when nothing froze them")
    return {name: list(values) for name, values in normalised.items()}


def _apply_remove(substrate: Substrate, entity: str) -> None:
    substrate.remove(entity)


def _apply_disable(substrate: Substrate, entity: str) -> None:
    substrate.disable(entity)


def _apply_fail(substrate: Substrate, payload: dict) -> None:
    substrate.fail(payload["region"], payload["status"])


def _apply_set(substrate: Substrate, payload: dict) -> None:
    set_value(substrate, payload["entity"], payload["to"])


def _drive_one(substrate: Substrate, series: dict[str, list], index: int) -> None:
    for entity, values in series.items():
        set_value(substrate, entity, values[index])


for _verb in (
    Verb("remove", "make an entity vanish entirely, as if never declared",
         _validate_remove, apply=_apply_remove),
    Verb("disable", "switch an entity off; it stays declared and stops reporting",
         _validate_disable, apply=_apply_disable),
    Verb("fail", "make a region answer with an error status, for a partial capture",
         _validate_fail, apply=_apply_fail),
    Verb("set", "move an entity's value, once", _validate_set, apply=_apply_set,
         aliases=("drift",)),
    Verb("drive", "set an entity's value before each capture of this phase, in order",
         _validate_drive, per_capture=_drive_one),
):
    _install(_verb, _BUILTIN)
