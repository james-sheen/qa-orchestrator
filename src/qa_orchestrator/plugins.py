"""How a vertical's registrations reach a process that did not import it.

`register()` on the three registries is a Python call. The command line never
made one, so a vertical could construct its own tier and referee in a test and
could not run `qa-orchestrator check` on a scenario that named them -- the door
existed and the entrance most consumers use did not reach it.

Three ways in, all resolved before a scenario is read:

- an entry point in the group `qa_orchestrator.plugins`, declared by the
  vertical's own package (this package declares one for the vertical it ships);
- `QA_ORCHESTRATOR_PLUGINS`, a `os.pathsep`-separated list of specs;
- `--plugin SPEC`, repeatable.

A spec is `module.path`, `module.path:callable`, or `path/to/file.py[:callable]`.
The callable defaults to `register`. It may return a short string saying what it
registered, which the run header prints.

**A plugin that fails is a failure**, not a skip. A scenario naming a tier that
a broken plugin would have registered must be refused by name, not by a
traceback from somewhere else.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .vocabulary import PluginError

ENTRY_POINT_GROUP = "qa_orchestrator.plugins"
ENVIRONMENT_VARIABLE = "QA_ORCHESTRATOR_PLUGINS"


@dataclass(frozen=True)
class Loaded:
    origin: str
    spec: str
    summary: str


def _call(register, spec: str, origin: str) -> Loaded:
    try:
        summary = register()
    except PluginError:
        raise
    except Exception as error:                                   # noqa: BLE001
        raise PluginError(f"plugin {spec!r} ({origin}) failed while registering: "
                          f"{type(error).__name__}: {error}") from error
    return Loaded(origin=origin, spec=spec, summary=str(summary) if summary else "registered")


def load_spec(spec: str, origin: str = "--plugin") -> Loaded:
    target, _, attribute = spec.partition(":")
    attribute = attribute or "register"
    try:
        if target.endswith(".py") or os.sep in target:
            path = Path(target)
            name = f"qa_orchestrator_plugin_{path.stem}"
            location = importlib.util.spec_from_file_location(name, path)
            if location is None or location.loader is None:
                raise PluginError(f"plugin {spec!r}: cannot load {path}")
            module = importlib.util.module_from_spec(location)
            sys.modules[name] = module
            location.loader.exec_module(module)
        else:
            module = importlib.import_module(target)
    except PluginError:
        raise
    except Exception as error:                                   # noqa: BLE001
        raise PluginError(f"plugin {spec!r} ({origin}) could not be imported: "
                          f"{type(error).__name__}: {error}") from error
    register = getattr(module, attribute, None)
    if not callable(register):
        raise PluginError(f"plugin {spec!r} ({origin}) has no callable {attribute!r}")
    return _call(register, spec, origin)


def _entry_points():
    from importlib.metadata import entry_points
    found = entry_points()
    if hasattr(found, "select"):
        return list(found.select(group=ENTRY_POINT_GROUP))
    return list(found.get(ENTRY_POINT_GROUP, []))                 # pragma: no cover


def load_all(explicit: Iterable[str] = (), *, entry_points: bool = True,
             environment: bool = True) -> list[Loaded]:
    """Load every plugin from every source, in that order, and say what loaded."""
    loaded: list[Loaded] = []
    if entry_points:
        for point in _entry_points():
            try:
                register = point.load()
            except Exception as error:                           # noqa: BLE001
                raise PluginError(f"entry point {point.name!r} ({point.value}) could not "
                                  f"be loaded: {type(error).__name__}: {error}") from error
            loaded.append(_call(register, point.value, f"entry point {point.name}"))
    if environment:
        for spec in filter(None, os.environ.get(ENVIRONMENT_VARIABLE, "").split(os.pathsep)):
            loaded.append(load_spec(spec, ENVIRONMENT_VARIABLE))
    for spec in explicit:
        loaded.append(load_spec(spec))
    return loaded
