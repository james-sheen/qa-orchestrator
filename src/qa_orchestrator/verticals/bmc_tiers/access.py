"""How the referee reaches the machine a tier started.

A handle alone cannot reach a real BMC. Every one ships a self-signed
certificate and wants a credential, and the harness had nowhere to say either:
the profile's capture builder took a target and an output path, and the scenario
format's top-level keys are a closed set. So a scenario pointed at a real
machine captured nothing, twenty-eight times, and the referee answered *could
not complete* to every judgement -- which was found by pointing one at a real
machine and is not visible from any mock.

**What this module is and is not.** It reads the tier's own `machine:` block for
the keys that describe getting IN, and hands them over as a plain mapping. The
core never reads it. Turning it into flags is the referee profile's job, in
`verticals/bmc.py`, because which flag means *do not verify the certificate* is
a fact about one program.

**A password VALUE is refused, not supported.** The referee's own help calls
`--password` discouraged because it crosses argv where `ps` can read it, and a
scenario is a file in a repository, which is worse. `password_env` names the
variable instead, so the value never enters either.
"""

from __future__ import annotations

from typing import Any

from ...vocabulary import SubstrateUnavailable

#: The keys of `machine:` that describe reaching the machine rather than being
#: it. Everything else in that block belongs to the tier.
ACCESS_KEYS = ("username", "password_env", "tls", "timeout")

#: How the certificate is to be treated. One value, not a set of flags, and that
#: is deliberate: the referee refuses a command that asks to verify and not to
#: verify at once, and a shape that cannot express the contradiction cannot
#: produce it.
TLS_CHOICES = ("insecure", "cafile", "pin_sha256")


def access_from(machine: dict) -> dict:
    """The access description in `machine:`, checked but not translated."""
    access = {key: machine[key] for key in ACCESS_KEYS if key in machine}

    if "password" in machine:
        raise SubstrateUnavailable(
            "machine.password puts a secret in a file that lives in a repository, "
            "and passes it through argv where any process on the host can read "
            "it. Name the variable instead -- machine.password_env: BMC_PASSWORD "
            "-- which is what the referee's own help recommends over the flag it "
            "calls discouraged.")

    tls = access.get("tls")
    if tls is not None:
        if isinstance(tls, str):
            if tls != "insecure":
                raise SubstrateUnavailable(
                    f"machine.tls is {tls!r}; as a bare word it may only be "
                    f"'insecure'. To verify against something, give it a mapping: "
                    f"{{cafile: /path}} or {{pin_sha256: <hex>}}.")
        elif isinstance(tls, dict):
            unknown = set(tls) - {"cafile", "pin_sha256"}
            if unknown:
                raise SubstrateUnavailable(
                    f"machine.tls has unknown key(s) {sorted(unknown)}; known "
                    f"keys are cafile and pin_sha256")
            if len(tls) != 1:
                raise SubstrateUnavailable(
                    "machine.tls names one way to treat the certificate, not "
                    "several. A command that asks to verify two ways is one the "
                    "referee refuses, and this shape is why it cannot be written.")
        else:
            raise SubstrateUnavailable(
                f"machine.tls must be 'insecure' or a mapping naming one of "
                f"{', '.join(TLS_CHOICES[1:])}, not {type(tls).__name__}")

    if "password_env" in access and "username" not in access:
        raise SubstrateUnavailable(
            "machine.password_env without machine.username: the referee sends "
            "them together, and half a credential reaches a BMC as none.")
    return access


def refuse_access(machine: dict, tier: str) -> None:
    """For a tier that serves no authenticated interface.

    Ignoring the keys would be worse than refusing them: a scenario carrying a
    credential is a scenario whose author believes it is being used, and the one
    that was is the one that reaches a real machine.
    """
    named = [key for key in (*ACCESS_KEYS, "password") if key in machine]
    if named:
        raise SubstrateUnavailable(
            f"the {tier} tier serves its own machine in this process and reads "
            f"no credential, so machine.{named[0]} would be silently unused. "
            f"Remove it, or run this scenario on a tier that reaches something.")
