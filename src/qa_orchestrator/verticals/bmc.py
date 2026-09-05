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


BMC_SENSOR_AUDIT = referee.Tool(
    name="bmc-sensor-audit",
    executable="bmc-sensor-audit",
    install_hint="pip install 'bmc-sensor-audit[detect]'",
    modes=("detect", "coverage"),
    capture_argv=lambda target, out: ("capture", "--target", target, "--out", str(out),
                                      "--print-digest"),
    validate_argv=lambda path: ("validate-walk", str(path)),
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
