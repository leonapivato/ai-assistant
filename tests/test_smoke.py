"""Smoke tests to verify the package imports and tooling is wired up."""

import ai_assistant


def test_version_is_exposed() -> None:
    assert ai_assistant.__version__ == "0.1.0"
