"""The `memory` tier: entities in a dictionary, observable as a JSON file.

The only tier the core ships, and it can be here because it has no domain in
it. A vertical whose faults are all presence and value -- most are -- needs no
tier of its own: its referee reads the snapshot this writes, and the scenario
says `substrate: memory`. A vertical that needs more subclasses it (see
`examples/paper`) or brings its own.

Snapshot shape, `qa-memory/1`:

    {"format": "qa-memory/1",
     "entities": {"R-3.2": {"value": 1.0}, "Fan1": {"value": null, "min_rpm": 800}},
     "errors": {"/region/x": 500}}

A removed entity is not in `entities`. A disabled one is there with `value`
null. Extra fields declared in the scenario ride along untouched, so a referee
that reads thresholds or roles beside a value can find them.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..vocabulary import ABSENT, DISABLED, READING, SubstrateUnavailable

FORMAT = "qa-memory/1"


class MemorySubstrate:
    name = "memory"

    def __init__(self, setup: dict) -> None:
        declared = setup.get("entities") or []
        if not declared:
            raise SubstrateUnavailable(
                "the memory tier needs setup.entities in the scenario -- it has "
                "nothing to enumerate from, so the scenario supplies the list. An "
                "empty substrate would make every declared entity absent and every "
                "phase pass for that reason.")
        self._entities: dict[str, dict[str, Any]] = {}
        for spec in declared:
            if isinstance(spec, str):
                spec = {"name": spec}
            if not isinstance(spec, dict) or not spec.get("name"):
                raise SubstrateUnavailable(
                    f"the memory tier needs each entity as a name or a mapping with "
                    f"a name, got {spec!r}")
            record = {k: v for k, v in spec.items() if k not in ("name", "value", "reading")}
            if "value" in spec and "reading" in spec:
                raise SubstrateUnavailable(
                    f"entity {spec['name']!r} gives both value and reading; write one")
            record["value"] = spec.get("value", spec.get("reading", 1.0))
            self._entities[str(spec["name"])] = record
        self._gone: set[str] = set()
        self._errors: dict[str, Any] = {}
        given = setup.get("state_file")
        self._owned = given is None
        if given is None:
            handle, path = tempfile.mkstemp(prefix="qa-memory-", suffix=".json")
            os.close(handle)
            self._path = Path(path)
        else:
            self._path = Path(str(given))

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> str:
        """Write the current state and return the file's path as the handle."""
        live = {name: record for name, record in self._entities.items()
                if name not in self._gone}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(
            {"format": FORMAT, "entities": live, "errors": self._errors}, indent=1))
        return str(self._path)

    def stop(self) -> None:
        if self._owned:
            try:
                self._path.unlink()
            except OSError:
                pass

    # -- injection ------------------------------------------------------------

    def remove(self, entity: str) -> None:
        self.record(entity)
        self._gone.add(entity)

    def disable(self, entity: str) -> None:
        self.record(entity)["value"] = None

    def fail(self, region: str, status: Any) -> None:
        self._errors[str(region)] = status

    def set_value(self, entity: str, value: Any) -> None:
        self.record(entity)["value"] = value

    # -- observation ----------------------------------------------------------

    def state(self, entity: str) -> str:
        if entity in self._gone or entity not in self._entities:
            return ABSENT
        return DISABLED if self._entities[entity]["value"] is None else READING

    # -- internals ------------------------------------------------------------

    def record(self, entity: str) -> dict[str, Any]:
        """The live record for an entity, or refuse: it is not there.

        Public, so a tier built on this one can add its own verbs against the
        same records (see `examples/paper`).

        A typo in a scenario would otherwise perturb nothing and let the phase
        pass, which is indistinguishable from the referee failing to notice a
        real fault -- the exact confusion this harness exists to remove.
        """
        if entity in self._entities and entity not in self._gone:
            return self._entities[entity]
        known = ", ".join(sorted(n for n in self._entities if n not in self._gone)) or "(none)"
        raise SubstrateUnavailable(f"no entity named {entity!r} on this substrate; it has: {known}")
