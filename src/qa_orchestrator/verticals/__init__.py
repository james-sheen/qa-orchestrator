"""Verticals shipped in this package.

Each is a plugin: a module with a `register()` that adds its tiers, verbs and
referee profiles through the same registries any outside vertical uses. The
core never imports this package; `tests/test_domain_free.py` checks that.
"""
