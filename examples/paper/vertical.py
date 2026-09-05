"""A vertical that shares no vocabulary with the first one: requirements in a proposal.

Three things a vertical may bring, all shown here:

- a **substrate**, built on the shipped `memory` tier and adding one thing the
  general protocol has no verb for (one requirement contradicting another);
- a **verb**, `contradict`, so a scenario can ask for that fault by name and
  have it validated at parse time like the built-in five;
- a **referee profile** for `proposal-review`, a program whose command line
  takes positional arguments where the first vertical's takes flags, whose
  report keeps `issues` rather than `findings`, and which reports what it did
  NOT check -- so the scenario can assert on declines and on the denominator.

Nothing here imports, installs or invokes anything from any other vertical.

    PATH=examples/paper/bin:$PATH \\
    qa-orchestrator --plugin examples/paper/vertical.py run examples/paper/withdrawn.yaml
"""

from __future__ import annotations

from typing import Any

from qa_orchestrator import actions, referee, substrate
from qa_orchestrator.actions import Verb, one_of
from qa_orchestrator.substrates.memory import MemorySubstrate
from qa_orchestrator.vocabulary import ScenarioError, SubstrateUnavailable


class PaperSubstrate(MemorySubstrate):
    """A proposal: requirements with an answer each. Values are text, not numbers."""

    name = "paper"

    def contradict(self, entity: str, other: str) -> None:
        self.record(other)
        self.record(entity)["value"] = {"contradicts": other}


def _validate_contradict(payload: Any, where: str, captures: int) -> dict:
    _, entity = one_of(payload, ("entity",), where, "contradict")
    if "with" not in payload:
        raise ScenarioError(f"{where}: contradict needs an entity and the one it contradicts (with)")
    return {"entity": str(entity), "with": str(payload["with"])}


def _apply_contradict(target: Any, payload: dict) -> None:
    if not hasattr(target, "contradict"):
        raise SubstrateUnavailable(
            f"the {getattr(target, 'name', '?')} tier cannot make one requirement "
            f"contradict another; run that phase on the paper tier")
    target.contradict(payload["entity"], payload["with"])


CONTRADICT = Verb("contradict", "make one requirement contradict another",
                  _validate_contradict, apply=_apply_contradict)


PROPOSAL_REVIEW = referee.Tool(
    name="proposal-review",
    executable="proposal-review",
    install_hint="put examples/paper/bin on PATH",
    modes=("review",),
    # Positional, where the first vertical's tool takes --target and --out.
    capture_argv=lambda handle, out: ("record", handle, str(out)),
    validate_argv=lambda path: ("check", str(path)),
    judge_argv=lambda mode, configs, captures: (
        mode,
        *[part for c in configs for part in ("--rules", str(c))],
        *[part for w in captures for part in ("--record", str(w))]),
    json_argv=lambda mode: ("--as-json",),
    report=referee.ReportSchema(
        findings="issues", subject=("requirement",), text=("issue",),
        declines="not_checked", decline_reason=("reason",), decline_subject=("requirement",),
        checked="checked.requirements"),
    digest_pattern=r"\bproposal-[0-9a-f]{8}\b",
)


def register() -> str:
    substrate.register("paper", PaperSubstrate)
    actions.register_verb(CONTRADICT)
    referee.register_tool(PROPOSAL_REVIEW)
    return "substrate paper; verb contradict; referee proposal-review"


def unregister() -> None:
    substrate.unregister("paper")
    actions.unregister_verb("contradict")
    referee.unregister_tool("proposal-review")
