"""Which device an interface adapter is (ADR-0296 §1, ADR-0298 §3).

Moved here with the rule from ``test_cli_chat.py`` when the gateway came to share it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.interfaces.devices import HUB_DEVICE, this_device
from ai_assistant.wire import OverlayIdentityUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

#: This machine's stable node id, as its overlay agent reports it.
_LAPTOP = "nL4pT0pCNTRL"


class _Agent:
    """This machine's overlay agent: it names this machine, or will not say.

    Attributes:
        asked: How many times this machine's own identity was asked for.
    """

    def __init__(self, own: str | None = _LAPTOP) -> None:
        self._own = own
        self.asked = 0

    async def identify(self, host: str, port: int) -> str:
        """Never asked here: naming a device dials nothing."""
        raise AssertionError((host, port))

    async def own_identity(self) -> str:
        """This machine's node, or the failure the seam declares."""
        self.asked += 1
        if self._own is None:
            msg = "the overlay agent is not running"
            raise OverlayIdentityUnavailableError(msg)
        return self._own


def _remote(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, remote_hub_address="100.64.0.1")


async def test_on_the_hubs_own_machine_the_device_is_hub(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    agent = _Agent()

    assert HUB_DEVICE == "hub"
    assert await this_device(settings, named=None, agent=agent) == "hub"
    assert await this_device(settings, named="hub", agent=None) == "hub"
    assert agent.asked == 0


async def test_on_the_hubs_own_machine_no_other_device_can_be_named(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="cannot name another"):
        await this_device(Settings(data_dir=tmp_path), named="phone", agent=None)


async def test_on_another_machine_the_device_is_read_from_this_machines_agent(
    tmp_path: Path,
) -> None:
    """The identity the hub's enrolment recorded, which the agent here reports too."""
    agent = _Agent()

    assert await this_device(_remote(tmp_path), named=None, agent=agent) == _LAPTOP
    assert agent.asked == 1


async def test_a_named_device_wins_and_the_agent_is_not_asked(tmp_path: Path) -> None:
    """Naming is the fallback for an agent that cannot answer, so it must not need one."""
    agent = _Agent(own=None)

    assert await this_device(_remote(tmp_path), named="node-other", agent=agent) == "node-other"
    assert agent.asked == 0


async def test_an_agent_that_will_not_say_is_refused_naming_the_fallback(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="--device") as raised:
        await this_device(_remote(tmp_path), named=None, agent=_Agent(own=None))

    assert "not running" in str(raised.value)
    assert isinstance(raised.value.__cause__, OverlayIdentityUnavailableError)


async def test_no_agent_and_nothing_named_is_refused_naming_the_fallback(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="--device"):
        await this_device(_remote(tmp_path), named=None, agent=None)
