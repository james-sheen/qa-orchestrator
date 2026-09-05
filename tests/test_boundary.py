"""The architectural constraint, pinned by reading the source.

The orchestrator grades the referee. If it could reach into the referee's
internals to find out what the referee concluded, it would be marking the exam
with the answer key: a change that broke the tool's real output while leaving its
internals intact would still pass, and that is the one result this suite must
never be able to produce.

So the core talks to a referee as a subprocess and nothing else. This asserts that
by reading the files, because the alternative -- trusting a convention -- is how
the convention gets broken by someone who did not know it existed.

**What changed in 0.3.** The exception used to be one file, `backends/mock.py`:
`MockBMC` is a fake *machine*, standing in for the thing being audited rather than
the thing doing the auditing. That file is now `verticals/bmc_tiers/mock.py`, and
the rule generalises with it -- a VERTICAL may import its own tool, the core may
not. The allowed region is derived from the package layout rather than named, so
a second vertical needs no edit here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import qa_orchestrator

#: Asked of the package that was imported, never guessed from this file's
#: position. `test_registries.py` carries the same note and the same scar: a
#: relative guess named nothing once the tree moved under `src/`, and scans that
#: assert *no module does X* all passed by reading an empty directory.
SRC = Path(qa_orchestrator.__file__).resolve().parent

#: Where a vertical's own code lives. Everything else is the core.
VERTICALS = SRC / "verticals"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _modules(root: Path) -> list[Path]:
    found = sorted(p for p in root.rglob("*.py"))
    if not found:
        raise AssertionError(
            f"no modules under {root}; every assertion below is true of an empty "
            f"set, so this would report the cleanest possible result")
    return found


def _core_modules() -> list[Path]:
    return [p for p in _modules(SRC) if VERTICALS not in p.parents]


def _tool_imports(path: Path) -> set[str]:
    """Imports of the first vertical's tool. The one package the core must not name."""
    return {m for m in _imported_modules(path) if m.split(".")[0] == "bmc_sensor_audit"}


class TestTheCoreNeverImportsAReferee:
    def test_no_core_module_imports_the_tool(self):
        for path in _core_modules():
            offending = _tool_imports(path)
            assert not offending, (
                f"{path.relative_to(SRC)} imports {sorted(offending)}. The core "
                f"must read a referee through exit codes, stdout and the JSON "
                f"report only -- importing one means a change that breaks the "
                f"published output while leaving internals intact still passes here")

    @pytest.mark.parametrize("module", ["referee", "compare"])
    def test_the_two_that_decide_a_verdict_especially(self, module):
        """Named because they are the ones the argument is about: `referee.py`
        obtains the verdict and `compare.py` judges it. The sweep above covers
        them, and a sweep that started scanning nothing would still be green."""
        assert not _tool_imports(SRC / f"{module}.py")

    def test_a_vertical_does_import_it(self):
        """Non-vacuity, and the whole reason the rule is worth stating.

        If nothing imported the tool anywhere, every assertion above would pass by
        finding nothing and the boundary would be untested. A tier importing the
        tool's own mock BMC is the correct case: a fake machine, not the referee.
        """
        importers = [p for p in _modules(VERTICALS) if _tool_imports(p)]
        assert importers, (
            "no vertical imports the tool any more, so the tests above assert "
            "something nothing could violate")


class TestEveryModuleParses:
    """Derived from the tree, not from a list written when it had five modules.

    The 0.2.x version named `referee, compare, scenario, run, cli`. The rewrite
    added `actions`, `plugins`, `substrate` and `vocabulary`, none of which that
    list would have covered, and nothing would have gone red to say so.
    """

    def test_all_of_them(self):
        for path in _modules(SRC):
            ast.parse(path.read_text())

    def test_there_are_more_than_the_original_five(self):
        assert len(_modules(SRC)) > 5, "the derived list found fewer files than the written one had"
