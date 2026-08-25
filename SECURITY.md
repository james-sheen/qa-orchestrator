# Security

## Report privately

**Use GitHub's private vulnerability reporting** — the *Security* tab on this
repository, *Report a vulnerability*. That opens a channel visible only to the
maintainer.

**Do not open a public issue for anything in the list below.** Several of the
failure modes here are ones where *the report itself is the disclosure*: an issue
quoting what a scenario run wrote to a file may publish the thing that should not
have been written.

If private reporting is unavailable to you, open a public issue saying only
**that** you have something to report and nothing about what it is.

## What counts as a security issue here

This package injects faults into a machine under test and drives the referee
against it. It authenticates to infrastructure and it deliberately makes machines
misbehave.

**1. It carries credentials to a BMC.** They are supplied by the caller and never
stored, but:

- **Credentials appearing in output** — in a log line, a URL, an exception, a
  scenario result — are a security issue.
- **A credential reaching `ps`**, through an argument vector rather than an
  environment variable or a file, is a security issue.

**2. It injects faults on purpose, and the blast radius is the point.** A
scenario names one target.

- **Any way a scenario affects a machine it does not name** is a security issue.
- **A fault that is not undone** when the run ends, leaving a machine in the
  injected state without saying so, is a security issue rather than a defect: the
  operator is told the rig was returned and it was not.

**3. It judges the referee.** The whole value is that a deliberate fault produces
a known verdict.

- **Any way to make a scenario report a pass without the referee having reached
  that verdict** is a security issue. A harness that can be made to agree with
  itself is a harness that certifies nothing.

## What does not need private handling

Ordinary defects, scenario parse failures, crashes on malformed YAML, wrong
counts, and a scenario that legitimately cannot run because the referee is not
installed — that is reported in prose and exits clean by design.

## What to expect

A single maintainer, no service-level commitment, and no bounty. You will get an
acknowledgement and an honest answer about whether and when it will be fixed —
including *not soon*, when that is true.

**The supported version is the latest release on PyPI** and nothing older. A fix
lands on the default branch and ships in the next release; the reply will say
which. No version literal appears in this file on purpose — a number here is a
number that goes stale.

## Scope

This repository only. A vulnerability in a BMC, in OpenBMC, or in a vendor's
firmware belongs to that project or vendor. If this tool *surfaces* such a flaw,
the flaw is still theirs — report it to them, and by all means tell us the tool
helped.
