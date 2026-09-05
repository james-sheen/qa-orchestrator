"""Talk to the program a scenario names. Through its published surfaces, and no other way.

**This module is the architecture.** The harness injects faults and judges
whether the referee caught them, which means the referee is the thing under
test. If this module reached into the referee's internals, a change that broke
the tool's real output while leaving its internals intact would still pass --
marking the exam with the answer key.

So the referee runs as a subprocess. What comes back is exit codes, stdout, and
a JSON report. Nothing here imports any referee, and no profile can make it.

**Which referee is a `Tool` profile, not a literal.** The identity, the argv for
each of the three questions this module asks, and where the report keeps its
findings come from the profile a scenario names. What a profile CANNOT do is as
much the point: spawning the process, interpreting `0/1/2`, and judging the
captured artifact stay here, because those must behave identically for every
vertical -- a profile that could reinterpret an exit code could make `2` read
as clean, which is the one result this harness must never produce. A tool with
a different exit contract needs a shim, and the shim belongs to the vertical.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Sequence

from .vocabulary import CaptureFailed, RefereeUnavailable, RegistrationError

#: The documented CI interface every referee must speak. `2` is
#: could-not-complete and must never be read as clean.
EXIT_CLEAN, EXIT_REGRESSION, EXIT_INCOMPLETE = 0, 1, 2

VERDICTS = {EXIT_CLEAN: "clean", EXIT_REGRESSION: "regressions",
            EXIT_INCOMPLETE: "incomplete"}


@dataclass(frozen=True)
class ReportSchema:
    """Where a referee's JSON report keeps the things a scenario can assert on.

    Key names only. How they are read stays in `Verdict`, for the same reason
    exit codes stay in this module.
    """

    #: The list of findings.
    findings: str = "findings"
    #: Where a finding names its subject; the first present key wins.
    subject: tuple[str, ...] = ("name",)
    #: Where a finding keeps its wording, for `expect.referee.findings.text`.
    text: tuple[str, ...] = ("finding", "message", "text")
    #: The list of evaluations the referee DECLINED to make, or None if the
    #: tool reports none. An engine that reports what it did not check makes
    #: that list the more interesting half of its output.
    declines: str | None = None
    decline_reason: tuple[str, ...] = ("reason",)
    decline_subject: tuple[str, ...] = ("entity", "name")
    #: Dotted path to the denominator -- how many evaluations were attempted --
    #: or None if the tool reports none.
    checked: str | None = None

    def __post_init__(self) -> None:
        for name, value in (("findings", self.findings), ("declines", self.declines),
                            ("checked", self.checked)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise RegistrationError(f"ReportSchema.{name} must be a non-empty key")
        for name, keys in (("subject", self.subject), ("text", self.text),
                           ("decline_reason", self.decline_reason),
                           ("decline_subject", self.decline_subject)):
            if not isinstance(keys, tuple) or not keys or not all(
                    isinstance(k, str) and k for k in keys):
                raise RegistrationError(
                    f"ReportSchema.{name} must be a non-empty tuple of key names")


@dataclass(frozen=True)
class Tool:
    """The program a scenario grades, described rather than assumed.

    The argv builders return the arguments AFTER the executable. They cannot
    choose the executable, so nothing registered here can run a different
    program from the one it named.
    """

    name: str
    executable: str
    install_hint: str
    #: What `mode:` may say in a scenario. The first is the default.
    modes: tuple[str, ...]
    #: `capture_argv(handle, out_path)`: record one observation of the substrate.
    capture_argv: Callable[[str, Path], Sequence[str]]
    #: `judge_argv(mode, configs, captures)`: judge every capture so far, oldest first.
    judge_argv: Callable[[str, Sequence[str], Sequence[Path]], Sequence[str]]
    #: `validate_argv(path)`: say whether a capture file is well formed, or None
    #: if the tool ships no validator. Then a capture is judged by its existence
    #: alone and the evidence block says `unvalidated` for every one of them.
    validate_argv: Callable[[Path], Sequence[str]] | None = None
    #: `json_argv(mode)`: the arguments that make `mode` answer in JSON, or None
    #: where it cannot. A mode without JSON is judged from its prose, and every
    #: mismatch says so.
    json_argv: Callable[[str], Sequence[str] | None] | None = None
    report: ReportSchema = field(default_factory=ReportSchema)
    #: The content handle in `capture`'s stdout, matched as a SHAPE, or None if
    #: the tool prints none. A declared pattern that does not match is said out
    #: loud per capture rather than degrading to nothing.
    digest_pattern: str | None = None
    #: Whether `config:` entries are files to resolve beside the scenario. A
    #: tool that takes a rule-set name or a URL says False and gets them verbatim.
    configs_are_paths: bool = True
    capture_timeout: float = 60.0
    judge_timeout: float = 300.0

    def __post_init__(self) -> None:
        for name in ("name", "executable"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise RegistrationError(f"Tool.{name} must be a non-empty string")
        if (not isinstance(self.modes, tuple) or not self.modes
                or not all(isinstance(m, str) and m for m in self.modes)):
            raise RegistrationError(
                f"Tool {self.name!r}: modes must be a non-empty tuple of names; a "
                f"scenario's `mode:` is checked against it")
        for name in ("capture_argv", "judge_argv"):
            if not callable(getattr(self, name)):
                raise RegistrationError(f"Tool {self.name!r}: {name} must be callable")
        for name in ("validate_argv", "json_argv"):
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise RegistrationError(f"Tool {self.name!r}: {name} must be callable or None")
        if not isinstance(self.report, ReportSchema):
            raise RegistrationError(f"Tool {self.name!r}: report must be a ReportSchema")
        if self.digest_pattern is not None:
            try:
                re.compile(self.digest_pattern)
            except re.error as error:
                raise RegistrationError(
                    f"Tool {self.name!r}: digest_pattern does not compile: {error}") from error
        for name in ("capture_timeout", "judge_timeout"):
            if getattr(self, name) <= 0:
                raise RegistrationError(f"Tool {self.name!r}: {name} must be positive")

    def has_json(self, mode: str) -> bool:
        return bool(self.json_argv and self.json_argv(mode))


# -- registry ------------------------------------------------------------------

#: Referees registered at runtime. There is no built-in one: the referee this
#: harness was first built against ships as a vertical and registers through
#: this door like every other.
_REGISTERED: Dict[str, Tool] = {}


def register_tool(tool: Tool) -> None:
    """Make `referee: <tool.name>` in a scenario grade with `tool`.

    Refuses a name already taken: a run that reports the name it was given must
    have used it. Replace by `unregister_tool()` first, so the intent is written.
    """
    if not isinstance(tool, Tool):
        raise RegistrationError(f"register_tool takes a Tool, got {tool!r}")
    if tool.name in _REGISTERED:
        raise RegistrationError(
            f"referee {tool.name!r} is already registered; unregister it first if "
            f"replacing it is what you mean")
    _REGISTERED[tool.name] = tool


def unregister_tool(name: str) -> None:
    _REGISTERED.pop(name, None)
    if _LEGACY_DEFAULT == name:
        globals()["_LEGACY_DEFAULT"] = None


def known_tools() -> tuple[str, ...]:
    """Every referee a scenario may name. Asked, never copied."""
    return tuple(sorted(_REGISTERED))


def profile(name: str) -> Tool:
    """The profile for a referee by name, or raise with the known ones listed."""
    if name in _REGISTERED:
        return _REGISTERED[name]
    have = ", ".join(sorted(_REGISTERED)) or "(none)"
    raise RefereeUnavailable(
        f"unknown referee {name!r}; registered: {have}. A vertical's referee is "
        f"registered by loading its plugin (--plugin, QA_ORCHESTRATOR_PLUGINS, or "
        f"an entry point)")


#: The referee a `qa-scenario/1` file means when it names none. A v1 file was
#: only ever graded by one program, and that program is a vertical's -- so the
#: vertical says so when it registers, and the core carries no name for it.
_LEGACY_DEFAULT: str | None = None


def set_legacy_default(name: str) -> None:
    """Declare which registered referee a v1 scenario means by default."""
    if name not in _REGISTERED:
        raise RegistrationError(
            f"{name!r} cannot be the v1 default referee: it is not registered")
    if _LEGACY_DEFAULT is not None and _LEGACY_DEFAULT != name:
        raise RegistrationError(
            f"the v1 default referee is already {_LEGACY_DEFAULT!r}; a second "
            f"vertical cannot claim it")
    globals()["_LEGACY_DEFAULT"] = name


def clear_legacy_default() -> None:
    globals()["_LEGACY_DEFAULT"] = None


def legacy_default() -> str | None:
    return _LEGACY_DEFAULT


# -- what comes back -----------------------------------------------------------

def _dig(mapping: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(mapping, dict) or part not in mapping:
            return None
        mapping = mapping[part]
    return mapping


def first_present(record: Any, keys: Sequence[str]) -> str | None:
    """The first of `keys` that `record` carries with a non-empty value, as text."""
    if not isinstance(record, dict):
        return None
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return None


@dataclass(frozen=True)
class Verdict:
    """One run of the referee, as the outside world can see it."""

    exit_code: int
    stdout: str
    stderr: str
    report: dict | None = None
    #: Copied from the profile that produced this verdict, so reading the
    #: report needs no second lookup and no assumption about whose report it is.
    schema: ReportSchema = field(default_factory=ReportSchema)

    @property
    def verdict(self) -> str:
        return VERDICTS.get(self.exit_code, f"unrecognised exit {self.exit_code}")

    @property
    def could_not_complete(self) -> bool:
        return self.exit_code == EXIT_INCOMPLETE

    def findings(self) -> list[dict]:
        if not self.report:
            return []
        found = self.report.get(self.schema.findings) or []
        return [f for f in found if isinstance(f, dict)]

    def declines(self) -> list[dict]:
        if not self.report or self.schema.declines is None:
            return []
        found = _dig(self.report, self.schema.declines) or []
        return [d for d in found if isinstance(d, dict)] if isinstance(found, list) else []

    def checked(self) -> int | None:
        if not self.report or self.schema.checked is None:
            return None
        value = _dig(self.report, self.schema.checked)
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    def names_mentioned(self) -> set[str]:
        """Subject names the report's findings name. Nothing without a report."""
        found: set[str] = set()
        for finding in self.findings():
            name = first_present(finding, self.schema.subject)
            if name:
                found.add(name)
        return found


@dataclass(frozen=True)
class Capture:
    """One observation of the substrate, and what is known about it.

    `complete` is False for a capture the tool wrote anyway with exit 2: a
    partial capture is still evidence, and records WHICH region failed. That is
    a different fact from a capture that could not be made at all.
    """

    path: Path
    complete: bool
    #: True if the tool's own validator accepted the file, False if the profile
    #: declares no validator. Never None: a capture is either validated or it is
    #: said, in the evidence, that it was not.
    validated: bool
    digest: str | None = None
    #: The profile declared a handle shape and the tool printed nothing matching.
    digest_missing: bool = False


def executable(tool: Tool) -> str:
    """The tool's console script, or raise. Never silently falls back."""
    found = shutil.which(tool.executable)
    if not found:
        raise RefereeUnavailable(
            f"{tool.executable} is not on PATH. Install it -- {tool.install_hint} -- "
            f"and re-run. This is reported rather than skipped: a scenario run "
            f"without a referee has judged nothing, and must not be able to look "
            f"like a pass.")
    return found


def _run(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)


def capture(target: str, out: Path, *, tool: Tool) -> Capture:
    """Record one observation. The tool's own capture step, no substitute.

    The FILE is judged, not the exit code: `capture` exits 2 both when it could
    not reach the substrate and when it reached it and one region answered with
    an error -- and the second is a capture the tool deliberately writes, because
    knowing which region failed is the point. A capture that produced no readable
    file is still a failure and still raises.
    """
    result = _run([executable(tool), *tool.capture_argv(target, out)], tool.capture_timeout)

    if not out.exists():
        raise CaptureFailed(
            f"{tool.name} capture wrote no file and exited {result.returncode}: "
            f"{(result.stderr or result.stdout).strip()[:400]}")

    validated = False
    if tool.validate_argv is not None:
        problems = validate(out, tool=tool)
        if problems is not None:
            raise CaptureFailed(
                f"{tool.name} capture exited {result.returncode} and wrote a file "
                f"its own validator refuses, so nothing can be judged from it: "
                f"{problems}")
        validated = True

    if result.returncode not in (EXIT_CLEAN, EXIT_INCOMPLETE):
        # A code outside the documented interface is not a partial capture.
        # Unrecognised reads as could-not-complete, with the raw code beside it.
        raise CaptureFailed(
            f"{tool.name} capture exited {result.returncode}, which is outside the "
            f"documented 0/1/2 interface: {(result.stderr or result.stdout).strip()[:400]}")

    digest = None
    missing = False
    if tool.digest_pattern is not None:
        found = re.search(tool.digest_pattern, result.stdout)
        digest = found.group(0) if found else None
        missing = found is None
    return Capture(path=out, complete=result.returncode == EXIT_CLEAN,
                   validated=validated, digest=digest, digest_missing=missing)


def validate(path: Path, *, tool: Tool) -> str | None:
    """`None` if the tool accepts the file, else what it said is wrong."""
    assert tool.validate_argv is not None
    result = _run([executable(tool), *tool.validate_argv(path)], tool.capture_timeout)
    if result.returncode == EXIT_CLEAN:
        return None
    return (result.stdout + result.stderr).strip()[:400] or f"exit {result.returncode}"


def judge(mode: str, configs: Sequence[str], captures: Sequence[Path], *,
          tool: Tool) -> Verdict:
    """Run the referee over every capture taken so far, oldest first.

    Every capture is passed, not just the phase's own: a referee that reads a
    series is asked the question it was built to answer. A profile for a tool
    that judges one snapshot takes the last one and ignores the rest.

    Asked twice when the mode has a JSON form -- once for the prose a person
    reads, once for the report the comparator reads -- rather than scraping
    names out of prose that stops matching when a heading is reworded.
    """
    base = [executable(tool), *tool.judge_argv(mode, configs, captures)]
    human = _run(base, tool.judge_timeout)

    report = None
    machine_argv = tool.json_argv(mode) if tool.json_argv else None
    if machine_argv:
        machine = _run([*base, *machine_argv], tool.judge_timeout)
        try:
            loaded = json.loads(machine.stdout)
            report = loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            report = None

    return Verdict(exit_code=human.returncode, stdout=human.stdout,
                   stderr=human.stderr, report=report, schema=tool.report)
