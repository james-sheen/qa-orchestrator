"""The README is the one surface that can promise what no index can deliver.

`bmc-sensor-audit` already carries a pair like this -- its README and its CITATION
file each have to agree with the released state -- but both are anchored on a
version sentinel, `__version__ == "0.0.0"`. That does not transplant here. This
package declares a real `0.1.0` and is on no index, so the sentinel reads
*released*, the check passes, and the README goes on describing an installation
that cannot happen. A mechanism copied without its premise is a check that runs
correctly and asks the wrong question.

This README's failure was the quieter half of the same thing: it showed
`qa-orchestrator run ...` with no way to obtain the command at all. Silence is
not a false claim, but a reader cannot act on it either, and nothing here could
tell the two apart until the state was written down.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from qa_orchestrator import __version__

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
DIST = "qa-orchestrator"

UNRELEASED = "Not yet released"

# The wording `bmc-sensor-audit` announces a release with. Reused verbatim rather
# than invented, so this family has one vocabulary for one fact and a future
# release here needs no new spelling.
RELEASED = re.compile(r"\*\*Released[^*]*?(\d+\.\d+\.\d+)\*\*")

# `pip install qa-orchestrator`, quoted or not, with or without an extra -- the
# form that only works once an index carries the name. The lookahead is what makes
# it usable while unreleased: `pip install "qa-orchestrator @ git+https://..."` is
# a direct reference, not an index lookup, and must not trip this.
#
# Spelled strictly on purpose: a guard with false positives is a guard the next
# person loosens, and a loosened guard stops catching the real thing.
INDEX_INSTALL = re.compile(
    r"pip install\s+(?:-[^\s]+\s+)*['\"]?"
    + re.escape(DIST)
    + r"(?:\[[A-Za-z0-9,_\-]+\])?['\"]?(?!\s*@)")


#: The tag the Status line names, so the two records of one version can be
#: compared without asking git anything.
TAGGED = re.compile(r"tagged `([^`]+)`")

#: The tag namespace this project releases in: `v` and a dotted version.
_TOOL_TAG = re.compile(r"^v(\d+(?:\.\d+)*)$")


def _released_versions(tags):
    """Every tag that names a version of THIS package, as comparable tuples."""
    return [tuple(int(part) for part in match.group(1).split("."))
            for match in (_TOOL_TAG.match(tag) for tag in tags) if match]


def _tags():
    """Repository tags, or None when git cannot answer -- borrowed from
    `bmc-sensor-audit`, caveat included. A checkout with no `.git` exits
    non-zero and an image with no git binary raises; answering `[]` for either
    would turn *cannot tell* into *there are no tags*. A shallow clone fetched
    without tags answers successfully and is still not an answer.
    """
    try:
        listed = subprocess.run(["git", "tag"], cwd=str(ROOT),
                                capture_output=True, text=True)
    except OSError:
        return None
    if listed.returncode != 0:
        return None
    return [line for line in listed.stdout.split() if line]


class TestTheReadmeDoesNotPromiseAnIndex:

    def test_the_readme_states_a_release_state_at_all(self):
        """Non-vacuity, and it is the whole reason this file is not one test.

        Every rule below is conditional on one of these two markers being
        present. Without this, deleting the marker is a way to pass -- the
        prohibition would find nothing and report success, which is the failure
        shape this suite refuses everywhere else.
        """
        readme = README.read_text()
        unreleased = UNRELEASED in readme
        released = RELEASED.search(readme)
        assert unreleased or released, (
            "the README states neither that this is unreleased nor which version "
            f"was released; one of `{UNRELEASED}` or `**Released -- X.Y.Z**` has "
            "to be there for the rest of this file to mean anything")
        assert not (unreleased and released), (
            "the README says both that this is unreleased and that a version was "
            "released; that is two answers to one question")

    def test_it_says_how_to_obtain_the_command_it_demonstrates(self):
        """A page that shows `qa-orchestrator run ...` and never says where the
        script comes from is not wrong, which is exactly why nothing caught it."""
        readme = README.read_text()
        assert f"{DIST} run " in readme, (
            "the README no longer demonstrates the command; if that is deliberate "
            "this check has lost its subject and should go")
        assert "pip install" in readme, (
            f"the README demonstrates `{DIST} run` and never says how to get the "
            f"command; a reader cannot act on it")

    def test_an_index_install_is_not_offered_while_unreleased(self):
        readme = README.read_text()
        if UNRELEASED not in readme:
            return
        found = INDEX_INSTALL.search(readme)
        assert not found, (
            f"the README says {UNRELEASED.lower()} and still tells a reader "
            f"{found.group(0)!r}; that command resolves against an index which "
            f"does not carry this name. Offer the direct reference "
            f"`odm-qa-pipeline` already pins for gate 3, or release it")

    def test_a_released_readme_names_the_version_the_package_reports(self):
        """The other branch, so this file keeps working after publication rather
        than becoming a check that only ever meant something once."""
        readme = README.read_text()
        released = RELEASED.search(readme)
        if not released:
            return
        assert released.group(1) == __version__, (
            f"the README announces {released.group(1)} and the package reports "
            f"{__version__}; both are published records of one fact")

    def test_the_readme_names_the_tag_its_own_version_will_carry(self):
        """The stale-tag-string guard, and it is TREE-LOCAL on purpose.

        The Status line carries two records of one fact -- the version it
        announces and the tag it names -- and until now **nothing compared
        them**. A README announcing 0.1.2 while still naming `v0.1.1` sends a
        reader to a tag that describes different code, and both strings look
        right in isolation.

        Answerable from the tree alone, so it holds in an sdist, in a shallow
        checkout with no tags, and at every instant of a release. The check below
        cannot say that of itself.
        """
        body = README.read_text()
        released = RELEASED.search(body)
        named = TAGGED.search(body)
        if not released:
            assert named is None, (
                f"the README names the tag {named.group(1)!r} while describing "
                f"this project as unreleased; an unreleased tree must not hand a "
                f"reader a tag to check out")
            return
        assert named, (
            f"the README announces {released.group(1)} and names no tag. The "
            f"Status line should read: tagged `v{released.group(1)}`")
        assert named.group(1) == f"v{released.group(1)}", (
            f"the README announces {released.group(1)} and names the tag "
            f"{named.group(1)!r}; they must be `v{released.group(1)}`. A leading "
            f"v dropped from one, or a tag string left behind by a bump, is how "
            f"these two part company")

    def test_an_announced_release_has_a_tag_behind_it(self):
        """A tag is the one part of the claim the tree cannot write about itself.

        **What was wrong with this before.** It tolerated only a repository with
        NO TAGS AT ALL, which stopped being true at the first release -- so from
        then on it went red between the version bump and the tag, every release,
        at exactly the moment somebody is most likely to reach for `--no-verify`.
        The tag is made OF the commit that bumps the version, so that window
        cannot be closed by doing things in a different order.

        Worse than red, it also RACED. CI fetches whatever tags the remote holds
        at checkout, and a release pushes master before the tag -- so the release
        commit's own CI run passed or failed on which push won.

        **The window is carved out precisely rather than widened.** Only this
        version may be untagged, and only while no later version is tagged: a
        release in flight is always the newest one. Reverting a bump while
        leaving its tag, or tagging from the wrong commit, both leave a later tag
        behind and still fail here.

        Whether the tag was ever pushed is a fact about the REMOTE, and no
        assertion from a working tree can reach it. Saying so is the honest
        version; asserting it would be a check that is right by luck.
        """
        released = RELEASED.search(README.read_text())
        if not released:
            return
        tags = _tags()
        if not tags:
            pytest.skip("no tags visible here; *cannot tell* is not *no tags*")

        version = released.group(1)
        if f"v{version}" in tags:
            return

        current = tuple(int(part) for part in version.split("."))
        ahead = sorted(t for t in _released_versions(tags) if t > current)
        assert not ahead, (
            f"v{version} has no tag, and "
            f"{['v' + '.'.join(map(str, t)) for t in ahead]} name later versions. "
            f"A release in flight is the only reason this version should be "
            f"untagged, and a release in flight is always the newest one -- so "
            f"either a bump was reverted with its tag left behind, or a tag was "
            f"made from the wrong commit")
        pytest.skip(
            f"v{version} is not tagged in this tree. The tag is made OF the "
            f"commit that sets the version, so this is the one legitimate window "
            f"and `git tag -a v{version}` closes it. Whether the tag was ever "
            f"pushed is a fact about the remote rather than this tree.")

    def test_the_matcher_finds_a_bare_install_when_there_is_one(self):
        """The prohibition above is only worth as much as the pattern under it."""
        assert INDEX_INSTALL.search(f"pip install {DIST}")
        assert INDEX_INSTALL.search(f"pip install '{DIST}[dev]'")
        assert INDEX_INSTALL.search(f"pip install --quiet {DIST}")
        assert not INDEX_INSTALL.search(
            f'pip install "{DIST} @ git+https://example.invalid/x@master"')
        assert not INDEX_INSTALL.search("pip install -r requirements.txt")
        assert not INDEX_INSTALL.search("pip install -e .")
