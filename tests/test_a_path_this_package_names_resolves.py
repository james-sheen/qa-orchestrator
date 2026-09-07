"""A file this package points a reader at is a file that exists.

`vocabulary.py` and `verticals/__init__.py` both named a test file as the guard
for the domain-free claim -- the central claim of this package -- and no file by
that name has ever existed here. Shipped that way in 0.3.0, so the wrong pointer
reached a consumer rather than staying in the tree.

A reader following it finds nothing and cannot tell which happened: renamed,
deleted, or never written. That is worse than no pointer, because a missing
sentence prompts a grep and a wrong one prompts a bug report.

WHY A GUARD AND NOT JUST THE TWO EDITS. The two were found by scanning for the
shape rather than by reading the one that was reported, and the scan found one
more than the report did. A pointer rots silently by construction: renaming a
test file is a normal, correct thing to do, and nothing connects that rename to
the prose naming it. So the connection is made here.

SCOPED TO THE SHIPPED SOURCE. This reads `src/`, never `tests/`, so this file's
own examples cannot be counted as instances of what it hunts -- the trap where a
checker's own text is a false-positive factory.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import qa_orchestrator

#: Asked of the package that was actually imported, never guessed from this
#: file's position, so moving either tree cannot make this scan an empty one.
PACKAGE = Path(qa_orchestrator.__file__).resolve().parent
REPO = PACKAGE.parents[1]

#: A repository-relative path to a Python file under the test directory. Built
#: from parts rather than written whole, so this line is not itself a literal of
#: the form it matches.
NAMED_PATH = re.compile(r"\b" + "tests" + r"/[A-Za-z0-9_/]+\.py\b")


def _named_paths():
    """Every test path the shipped source names, with where it says it."""
    found = []
    for source in sorted(PACKAGE.rglob("*.py")):
        text = source.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for path in NAMED_PATH.findall(line):
                found.append((source.relative_to(PACKAGE), number, path))
    return found


def test_the_scan_finds_something_to_check():
    """Non-vacuity. Every assertion below is a for-loop over this result, and a
    for-loop over nothing passes. The package has named at least one test file
    since before the defect this guards, so an empty scan means the scan broke,
    not that the prose stopped pointing anywhere."""
    assert _named_paths(), (
        "the shipped source names no test file at all; either the pointers were "
        "removed wholesale or this scan is measuring the wrong tree")


@pytest.mark.parametrize("where,line,named", _named_paths())
def test_a_test_file_the_source_names_exists(where, line, named):
    assert (REPO / named).is_file(), (
        f"{where}:{line} sends a reader to {named}, which does not exist. "
        f"Correct the name or remove the sentence -- a pointer to nothing is "
        f"worse than no pointer, because it reads as a checkable claim")
