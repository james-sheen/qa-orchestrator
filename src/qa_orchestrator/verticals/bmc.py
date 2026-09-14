"""The vertical this harness was first built against, as a plugin.

`bmc-sensor-audit` judges BMC firmware. Everything about it that used to be a
literal in the core -- its name, its subcommands, its flag names, its report
schema, the `sha256:` shape of its content handle -- is here, and reaches the
core through `register()` exactly as an outside vertical's would. The core
never imports this module; `pyproject.toml` names it on an entry point, so a
`pip install` of this package still finds it.

The three hardware tiers (`mock`, `qemu`, `testbed`) are registered from
`qa_orchestrator.verticals.bmc_tiers` -- the 0.2.x `backends/` package moved
verbatim. They implement `set_reading`; the core's `substrate.set_value` adapter
calls it, so they need no edit to run under the general protocol. When that
module is absent, `register()` says so in its summary rather than pretending
the tiers exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .. import referee, substrate


def _flagged_judge(mode: str, configs: Sequence[str], captures: Sequence[Path]) -> tuple[str, ...]:
    """`<mode> --config C ... --walk W ...`: the tool's judge form. It reads a series."""
    argv = [mode]
    for path in configs:
        argv += ["--config", str(path)]
    for capture in captures:
        argv += ["--walk", str(capture)]
    return tuple(argv)


def _access_argv(access: dict) -> tuple[str, ...]:
    """`machine:`'s access keys as this tool's flags.

    The mapping lives here rather than in the tier because which flag means *do
    not verify the certificate* is a fact about one program, and a second
    vertical's referee spells all of this differently or not at all.

    `--password-env` and never `--password`: the value stays in the environment
    and out of argv, which is the tool's own recommendation and the reason the
    reader refuses a literal password before this is ever called.
    """
    argv: list[str] = []
    if "username" in access:
        argv += ["--username", str(access["username"])]
    if "password_env" in access:
        argv += ["--password-env", str(access["password_env"])]
    tls = access.get("tls")
    if tls == "insecure":
        argv += ["--insecure"]
    elif isinstance(tls, dict) and "cafile" in tls:
        argv += ["--cafile", str(tls["cafile"])]
    elif isinstance(tls, dict) and "pin_sha256" in tls:
        argv += ["--pin-sha256", str(tls["pin_sha256"])]
    if "timeout" in access:
        argv += ["--timeout", str(access["timeout"])]
    return tuple(argv)


BMC_SENSOR_AUDIT = referee.Tool(
    name="bmc-sensor-audit",
    executable="bmc-sensor-audit",
    install_hint="pip install 'bmc-sensor-audit[detect]'",
    modes=("detect", "coverage"),
    capture_argv=lambda target, out: ("capture", "--target", target, "--out", str(out),
                                      "--print-digest"),
    validate_argv=lambda path: ("validate-walk", str(path)),
    # How to get IN, which `capture_argv` above has nowhere to put: it answers
    # what to record and where to write it, the same question on a mock and on a
    # machine in a rack. Every real BMC ships a self-signed certificate and wants
    # a credential, and a scenario could express neither -- so the qemu tier
    # could inject into real firmware and this referee could never read it.
    access_argv=_access_argv,
    judge_argv=_flagged_judge,
    json_argv=lambda mode: ("--json",) if mode == "coverage" else None,
    # DERIVED from a report this tool wrote, not from what a report might
    # plausibly call things. It was `("finding", "message")` and the tool emits
    # NEITHER: the text is `detail`. Every `findings.text` expectation in the
    # three shipped scenarios failed against it, and only running one could show
    # that -- the comparator found the finding, read no text out of it, and said
    # the text did not match.
    report=referee.ReportSchema(findings="findings", subject=("sensor", "name"),
                                text=("detail",)),
    digest_pattern=r"\bsha256:[0-9a-f]{64}\b",
)


def register() -> str:
    referee.register_tool(BMC_SENSOR_AUDIT)
    # A `qa-scenario/1` file that names no referee means this one. The format
    # predates `referee:`, and this is the only program that ever graded it.
    referee.set_legacy_default(BMC_SENSOR_AUDIT.name)
    try:
        from . import bmc_tiers                                   # noqa: WPS433
    except ImportError:
        return (f"referee {BMC_SENSOR_AUDIT.name} (v1 default); tiers NOT registered "
                f"(qa_orchestrator.verticals.bmc_tiers is not present in this build)")
    registered = []
    for name, factory in bmc_tiers.TIERS.items():
        substrate.register(name, factory)
        registered.append(name)
    return f"referee {BMC_SENSOR_AUDIT.name} (v1 default); tiers {', '.join(registered)}"


def unregister() -> None:
    referee.unregister_tool(BMC_SENSOR_AUDIT.name)
    for name in ("mock", "qemu", "testbed"):
        substrate.unregister(name)
