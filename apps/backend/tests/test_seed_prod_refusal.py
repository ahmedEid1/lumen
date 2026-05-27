"""Seed-in-prod refusal (L21-Sec)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
import typer

from app.cli import _refuse_prod_seed_or_pass
from app.core.config import Environment, get_settings


def _settings_with_env(env: Environment):
    """Build a Settings whose env attribute is the target value.

    We patch only that attribute rather than rebuilding the whole
    object via env-vars (which would race with the conftest cache
    machinery).
    """
    s = get_settings()
    return patch.object(s, "env", env)


def test_passes_in_non_production() -> None:
    """Dev/test environments should let the seed run unconditionally."""
    with _settings_with_env(Environment.development):
        _refuse_prod_seed_or_pass("seed")  # should not raise


def test_refuses_in_production_by_default() -> None:
    """The default in prod is REFUSE — a fixed-password demo seed must
    not ship to prod by accident."""
    with (
        _settings_with_env(Environment.production),
        patch.dict(os.environ, {}, clear=False),
    ):
        os.environ.pop("LUMEN_ALLOW_PROD_SEED", None)
        with pytest.raises(typer.Exit) as exc_info:
            _refuse_prod_seed_or_pass("demo-seed")
        assert exc_info.value.exit_code == 2


def test_explicit_override_lets_prod_seed_pass() -> None:
    """LUMEN_ALLOW_PROD_SEED=1 unlocks the prod path — for the case
    where an operator really does need to bootstrap a demo account on
    a fresh production deploy."""
    with (
        _settings_with_env(Environment.production),
        patch.dict(os.environ, {"LUMEN_ALLOW_PROD_SEED": "1"}, clear=False),
    ):
        _refuse_prod_seed_or_pass("seed")  # should not raise
