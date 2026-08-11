"""The custody guard, from the client's end of ADR-0124 §4's hop (#911, #937).

The conditions themselves are exercised once, through the hub, in
``tests/service/test_overlay.py`` — that file is deliberately untouched by the
move, so its passing is the evidence that relocating the guard changed no
behaviour. What is tested here is the half that could not exist before: that a
*client* can reach the same function at all, and that what it tells an operator is
about the client's machine rather than about a hub that may not be running on it.
"""

from __future__ import annotations

import contextlib
import os
import socket
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.service.overlay import HUB_AGENT_SOCKET
from ai_assistant.wire.overlay import (
    CLIENT_AGENT_SOCKET,
    TAILSCALE_SOCKETS,
    AgentSocketTerms,
    check_configured_socket,
    local_agent,
)

if TYPE_CHECKING:
    from pathlib import Path


def _bind(path: Path) -> socket.socket:
    """A real Unix socket at ``path``, so ``S_ISSOCK`` is answered by the kernel."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    return sock


def test_a_client_can_configure_its_own_agent_socket(tmp_path: Path) -> None:
    """The reach #937 is about: the client half driven from configuration.

    Before the guard moved, ADR-0083 §8 put it inside ``service``, which neither
    ``wire`` nor ``interfaces`` may import — so a one-machine run could point the
    hub at an agent socket and had to reach the client's half from outside the
    application entirely.
    """
    path = tmp_path / "tailscaled.sock"
    with contextlib.closing(_bind(path)):
        assert local_agent(str(path)).socket_path == str(path)


def test_an_unconfigured_client_looks_at_the_packaged_defaults(tmp_path: Path) -> None:
    """Unset changes nothing, which is what makes the setting additive.

    The two packaged paths are trusted because the operating system protects them,
    and they are used exactly as before — the custody conditions apply to a path an
    operator named, and to nothing else.
    """
    assert local_agent().socket_path in TAILSCALE_SOCKETS
    assert local_agent(candidates=[str(tmp_path / "absent.sock")]).socket_path == str(
        tmp_path / "absent.sock"
    )


def test_a_client_refusal_names_the_client_setting_and_not_the_hub_s(tmp_path: Path) -> None:
    """The reason the wording is a parameter rather than a constant.

    ``ASSISTANT_HUB_OVERLAY_AGENT_SOCKET`` need not be set on a client's machine at
    all, so a refusal naming it sends the operator to edit a variable that has no
    bearing on what just failed.
    """
    not_a_socket = tmp_path / "ordinary-file"
    not_a_socket.touch()

    with pytest.raises(ConfigurationError) as caught:
        local_agent(str(not_a_socket))

    message = str(caught.value)
    assert "ASSISTANT_CLIENT_OVERLAY_AGENT_SOCKET" in message
    assert "ASSISTANT_HUB_OVERLAY_AGENT_SOCKET" not in message


@pytest.mark.skipif(os.geteuid() == 0, reason="root satisfies every ownership check")
def test_a_client_refusal_speaks_about_the_client_and_not_about_a_hub(tmp_path: Path) -> None:
    """What the agent's answer decides here is which hub *this* client will talk to.

    "which is the identity ADR-0124 §4 admits every device by" is a true sentence
    on a hub and a wrong one on a laptop dialling that hub, which admits nothing.
    The condition is unchanged; only what it is said to be protecting is.

    (``runner`` — "neither root nor the uid N *the hub* runs as" — is the same
    substitution in the ownership branches. Those need a path owned by a third uid
    to reach, so they are pinned structurally below rather than provoked here.)
    """
    loose = tmp_path / "shared"
    loose.mkdir()
    path = loose / "tailscaled.sock"
    with contextlib.closing(_bind(path)):
        loose.chmod(0o777)
        try:
            with pytest.raises(ConfigurationError) as caught:
                local_agent(str(path))
        finally:
            loose.chmod(0o755)

    message = str(caught.value)
    assert "this client" in message
    assert "the hub" not in message


def test_the_two_ends_differ_in_wording_and_in_nothing_else(tmp_path: Path) -> None:
    """``AgentSocketTerms`` selects no behaviour, which is the point of sharing.

    The same path is refused for the same reason under both vocabularies. If the
    terms ever came to gate a *condition*, the two ends would be back to enforcing
    different security rules through one function — which is worse than the two
    copies this move removed, because it would look shared.
    """
    not_a_socket = tmp_path / "ordinary-file"
    not_a_socket.touch()

    with pytest.raises(ConfigurationError) as as_hub:
        check_configured_socket(not_a_socket, terms=HUB_AGENT_SOCKET)
    with pytest.raises(ConfigurationError) as as_client:
        check_configured_socket(not_a_socket, terms=CLIENT_AGENT_SOCKET)

    # Same verdict, same reason, and the only difference is the variable named.
    assert "is not a socket" in str(as_hub.value)
    assert "is not a socket" in str(as_client.value)
    assert str(as_hub.value).replace(HUB_AGENT_SOCKET.setting, CLIENT_AGENT_SOCKET.setting) == str(
        as_client.value
    )


def test_an_accepted_path_is_accepted_under_either_vocabulary(tmp_path: Path) -> None:
    """The other direction of the same claim, since a shared guard that only agreed
    about refusals would still be two rules.
    """
    path = tmp_path / "tailscaled.sock"
    with contextlib.closing(_bind(path)):
        assert check_configured_socket(path, terms=HUB_AGENT_SOCKET) == path
        assert check_configured_socket(path, terms=CLIENT_AGENT_SOCKET) == path


def test_every_slot_a_refusal_can_fill_is_populated_on_both_ends() -> None:
    """A blank field would print a sentence with a hole in it rather than fail.

    Pinned because the fields are pure message text: nothing else in the system
    would notice an empty one, and the failure mode is an operator reading
    "answers for the overlay and decides  (ADR-0124 §4)".
    """
    for terms in (HUB_AGENT_SOCKET, CLIENT_AGENT_SOCKET):
        assert isinstance(terms, AgentSocketTerms)
        assert terms.setting.startswith("ASSISTANT_")
        assert terms.runner
        assert terms.stakes
        assert terms.decides


def test_a_configured_client_socket_is_canonicalised(tmp_path: Path) -> None:
    """ADR-0084 §1's rule, which the client inherits by running the same function.

    Connecting to the name a symlink carries rather than to the path the checks
    were decided about is the gap canonicalisation closes; a client dials the
    resolved path for the same reason a hub does.
    """
    target = tmp_path / "real.sock"
    link = tmp_path / "link.sock"
    with contextlib.closing(_bind(target)):
        link.symlink_to(target)

        assert local_agent(str(link)).socket_path == str(target)
