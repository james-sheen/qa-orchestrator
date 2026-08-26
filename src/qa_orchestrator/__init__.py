"""Inject faults, drive walks, and compare the referee's verdict to a written one.

The audit tool judges firmware. This drives both: it perturbs a machine in ways
whose correct verdict is known in advance, and checks that the tool reached it.
That makes the tool the thing under test as much as the firmware is, which is why
it lives outside the tool -- a referee that shipped its own injector would be
certifying itself.
"""

__version__ = "0.2.0"
