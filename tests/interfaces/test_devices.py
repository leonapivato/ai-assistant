"""Which device an interface adapter is (ADR-0296 §1, ADR-0298 §3).

Moved here with the rule from ``test_cli_chat.py`` when the gateway came to share it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.interfaces.devices import HUB_DEVICE, this_device

if TYPE_CHECKING:
    from pathlib import Path


def test_on_the_hubs_own_machine_the_device_is_hub(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert HUB_DEVICE == "hub"
    assert this_device(settings, named=None) == "hub"
    assert this_device(settings, named="hub") == "hub"


def test_on_the_hubs_own_machine_no_other_device_can_be_named(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="cannot name another"):
        this_device(Settings(data_dir=tmp_path), named="phone")


def test_on_another_machine_the_device_is_named(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, remote_hub_address="100.64.0.1")

    assert this_device(settings, named="node-laptop") == "node-laptop"
    with pytest.raises(ConfigurationError, match="--device"):
        this_device(settings, named=None)
