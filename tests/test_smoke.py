"""Smoke tests to verify the package imports and tooling is wired up."""

from typer.testing import CliRunner

import ai_assistant
from ai_assistant.core.config import Settings
from ai_assistant.interfaces.cli import app


def test_version_is_exposed() -> None:
    assert ai_assistant.__version__ == "0.1.0"


def test_settings_load_with_defaults() -> None:
    settings = Settings()
    assert settings.log_level == "INFO"
    assert settings.default_model.startswith("anthropic:")


def test_cli_version_command() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert ai_assistant.__version__ in result.stdout
