"""The architectural constraint, pinned by reading the source.

The orchestrator grades the referee. If it could reach into the referee's
internals to find out what the referee concluded, it would be marking the exam
with the answer key: a change that broke the tool's real output while leaving its
internals intact would still pass, and that is the one result this suite must
never be able to produce.

So `referee.py` talks to the tool as a subprocess and nothing else. This asserts
that by reading the file, because the alternative -- trusting a convention -- is
how the convention gets broken by someone who did not know it existed.

`backends/mock.py` may import the tool, and the distinction is the design:
`MockBMC` is a fake *machine*. It stands in for the thing being audited, not the
thing doing the auditing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "qa_orchestrator"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_the_referee_module_does_not_import_the_referee():
    offending = {m for m in _imported_modules(SRC / "referee.py")
                 if m.split(".")[0] == "bmc_sensor_audit"}
    assert not offending, (
        f"referee.py imports {sorted(offending)}. It must read the tool through "
        f"exit codes, stdout and the JSON report only -- importing it means a "
        f"change that breaks the published output while leaving internals intact "
        f"would still pass here")


def test_the_comparator_does_not_import_the_referee_either():
    """`compare.py` decides whether a verdict was right. Same argument."""
    offending = {m for m in _imported_modules(SRC / "compare.py")
                 if m.split(".")[0] == "bmc_sensor_audit"}
    assert not offending, f"compare.py imports {sorted(offending)}"


def test_only_the_mock_backend_may_import_the_tool():
    """Non-vacuity in the other direction.

    If nothing imported the tool anywhere, the two tests above would pass by
    finding nothing, and the boundary they describe would be untested. The mock
    backend is the one place the import is correct, so its presence is what makes
    the absence elsewhere meaningful.
    """
    mock_imports = _imported_modules(SRC / "backends" / "mock.py")
    assert any(m.startswith("bmc_sensor_audit") for m in mock_imports), (
        "the mock backend no longer imports the tool's MockBMC, so the boundary "
        "tests above are now asserting something nothing could violate")

    for path in SRC.rglob("*.py"):
        if path.name == "mock.py":
            continue
        offending = {m for m in _imported_modules(path)
                     if m.split(".")[0] == "bmc_sensor_audit"}
        assert not offending, (
            f"{path.relative_to(SRC)} imports {sorted(offending)}; only the mock "
            f"backend may, and only because MockBMC is a fake machine rather than "
            f"the referee")


@pytest.mark.parametrize("module", ["referee", "compare", "scenario", "run", "cli"])
def test_every_module_parses(module):
    ast.parse((SRC / f"{module}.py").read_text())
