"""Fixtures shared by the suite.

The example vertical is loaded from its FILE, the way `--plugin path.py` loads
it, and unregistered after each test so the registries are empty again: a test
that leaked a registration would make the next test's refusal fire on the wrong
name, which is the failure mode `test_an_unregistered_referee_is_still_refused`
in the 0.2.x suite was rewritten to avoid.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXAMPLE = ROOT / "examples" / "paper"
#: The first vertical's scenarios, which moved into it: they are the BMC
#: tiers' files, not the harness's, and they travel with what gives them
#: meaning.
SCENARIOS = ROOT / "src" / "qa_orchestrator" / "verticals" / "bmc_scenarios"


@pytest.fixture
def paper_on_path(tmp_path, monkeypatch):
    """The example referee on PATH, from a copy whose executable bit is certain."""
    binary = tmp_path / "bin" / "proposal-review"
    binary.parent.mkdir(parents=True)
    shutil.copy(EXAMPLE / "bin" / "proposal-review", binary)
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    monkeypatch.setenv("PATH", str(binary.parent) + os.pathsep + os.environ.get("PATH", ""))
    return binary


def load_vertical(name: str = "paper_vertical_under_test"):
    spec = importlib.util.spec_from_file_location(name, EXAMPLE / "vertical.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def paper(paper_on_path):
    """The paper vertical registered, and unregistered afterwards."""
    module = load_vertical()
    module.register()
    yield module
    module.unregister()
