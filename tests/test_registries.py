"""The registries refuse what they should, and the core names no vertical.

The domain-free claim is checked STRUCTURALLY -- imports and string constants,
against the names the shipped vertical actually registers -- rather than against a
word list somebody has to remember to update. What it cannot see is vocabulary:
a core that speaks one domain's language without ever comparing against its names
passes every assertion here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import qa_orchestrator
from qa_orchestrator import actions, referee, substrate
from qa_orchestrator.actions import Verb
from qa_orchestrator.verticals import bmc
from qa_orchestrator.vocabulary import RegistrationError

#: Asked of the package that was actually imported, never guessed from this
#: file's position. The guess was `parents[1] / "qa_orchestrator"`, which is the
#: flat layout; moving the tree under `src/` made it name nothing, and two of the
#: three scans below then passed by reading an empty directory.
SRC = Path(qa_orchestrator.__file__).resolve().parent


def _tool(**overrides) -> referee.Tool:
    base = dict(name="t", executable="t", install_hint="", modes=("m",),
                capture_argv=lambda h, o: (), judge_argv=lambda m, c, w: ())
    return referee.Tool(**{**base, **overrides})


class TestAProfileIsValidatedWhenItIsMade:
    def test_empty_modes_are_refused_at_construction_not_at_parse(self):
        """`modes[0]` in the parser used to be the first thing to notice."""
        with pytest.raises(RegistrationError, match="modes must be a non-empty tuple"):
            _tool(modes=())

    @pytest.mark.parametrize("field, value", [
        ("name", ""), ("executable", " "), ("capture_argv", None), ("judge_argv", "x"),
        ("validate_argv", 3), ("json_argv", 3), ("digest_pattern", "("),
        ("capture_timeout", 0), ("judge_timeout", -1), ("report", {}),
    ])
    def test_a_bad_field(self, field, value):
        with pytest.raises(RegistrationError):
            _tool(**{field: value})

    def test_a_bad_schema(self):
        with pytest.raises(RegistrationError):
            referee.ReportSchema(subject=())
        with pytest.raises(RegistrationError):
            referee.ReportSchema(findings="")

    def test_has_json_follows_the_profile(self):
        tool = _tool(json_argv=lambda m: ("--json",) if m == "m" else None, modes=("m", "n"))
        assert tool.has_json("m") and not tool.has_json("n")
        assert not _tool().has_json("m")


class TestTheRegistriesRefuseAlike:
    def test_a_duplicate_referee(self):
        referee.register_tool(_tool(name="dup"))
        try:
            with pytest.raises(RegistrationError, match="already registered"):
                referee.register_tool(_tool(name="dup"))
        finally:
            referee.unregister_tool("dup")

    def test_a_duplicate_substrate_and_the_built_in(self):
        substrate.register("dup", lambda setup: None)
        try:
            with pytest.raises(RegistrationError, match="already registered"):
                substrate.register("dup", lambda setup: None)
        finally:
            substrate.unregister("dup")
        with pytest.raises(RegistrationError, match="built-in tier"):
            substrate.register("memory", lambda setup: None)
        with pytest.raises(RegistrationError, match="not callable"):
            substrate.register("x", "not a factory")

    def test_a_verb_that_would_do_nothing(self):
        with pytest.raises(RegistrationError, match="would do nothing"):
            Verb("idle", "nothing", lambda p, w, c: p)

    def test_a_verb_that_collides_with_a_built_in_or_an_alias(self):
        for taken in ("remove", "drift"):
            with pytest.raises(RegistrationError, match="already defined"):
                actions.register_verb(Verb(taken, "", lambda p, w, c: p, apply=lambda s, p: None))

    def test_unregister_then_register_is_the_way_to_replace(self):
        actions.register_verb(Verb("twice", "", lambda p, w, c: p, apply=lambda s, p: None))
        actions.unregister_verb("twice")
        actions.register_verb(Verb("twice", "", lambda p, w, c: p, apply=lambda s, p: None))
        actions.unregister_verb("twice")
        assert "twice" not in actions.known_verbs()

    def test_the_legacy_default_must_be_registered_and_is_claimed_once(self):
        with pytest.raises(RegistrationError, match="not registered"):
            referee.set_legacy_default("nobody")
        referee.register_tool(_tool(name="one"))
        referee.register_tool(_tool(name="two"))
        try:
            referee.set_legacy_default("one")
            with pytest.raises(RegistrationError, match="already"):
                referee.set_legacy_default("two")
            referee.unregister_tool("one")
            assert referee.legacy_default() is None
        finally:
            referee.unregister_tool("one")
            referee.unregister_tool("two")


def _modules(root: Path) -> list[Path]:
    """Every core module: the package, minus the verticals it must not name.

    A list rather than a generator, and empty is an ERROR rather than nothing to
    do. Every caller below asserts that no module does something; over an empty
    set each of them is true, so a scan pointed at the wrong directory reports
    the cleanest possible result.
    """
    found = [path for path in sorted(root.rglob("*.py"))
             if "verticals" not in path.relative_to(root).parts]
    if not found:
        raise AssertionError(
            f"no core modules under {root}; this scan would pass by reading "
            f"nothing, which is not the same as finding nothing wrong")
    return found


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(("." * node.level) + (node.module or ""))
            found.update(alias.name for alias in node.names)
    return found


class TestTheCoreNamesNoVertical:
    """The engine litmus, applied to this harness.

    Not a word list: the names checked are whatever the shipped vertical
    REGISTERS, read back from the registries after it registers. A vertical
    that registered nothing would make this vacuous, so that is asserted too.
    """

    @pytest.fixture
    def registered_names(self):
        before_tools, before_tiers = set(referee.known_tools()), set(substrate.known())
        bmc.register()
        try:
            names = (set(referee.known_tools()) - before_tools) | (set(substrate.known()) - before_tiers)
            if referee.legacy_default():
                names.add(referee.legacy_default())
        finally:
            bmc.unregister()
        assert names, "the shipped vertical registered nothing, so this test would check nothing"
        return names

    def test_no_core_module_imports_a_vertical(self):
        for path in _modules(SRC):
            offending = {m for m in _imports(path) if "verticals" in m}
            assert not offending, f"{path.relative_to(SRC)} imports {sorted(offending)}"

    def test_no_core_module_carries_a_registered_name_as_a_constant(self, registered_names):
        for path in _modules(SRC):
            found = _string_constants(path) & registered_names
            assert not found, (
                f"{path.relative_to(SRC)} names {sorted(found)}, which the shipped "
                f"vertical registers; the core must ask the registry, never know the answer")

    def test_the_vertical_itself_does_carry_them(self, registered_names):
        """Non-vacuity: the scan can find these names where they are allowed."""
        found = _string_constants(SRC / "verticals" / "bmc.py") & registered_names
        assert found
