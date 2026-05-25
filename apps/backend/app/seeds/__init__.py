"""Lumen — seed bundles.

This package holds focused, additive seed scripts that build on top of the
base seed in :mod:`app.cli` (``python -m app.cli seed``). The base seed
exists to support tests and the dev `make seed` flow; bundles here are for
operator scenarios like the free-tier live-demo deploy (H4).

Currently provided:

- :mod:`app.seeds.demo` — three published courses + a demo student account
  with in-flight progress. Invoked via ``python -m app.cli demo-seed`` or
  ``make demo-seed``.
"""
