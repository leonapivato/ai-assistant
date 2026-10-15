"""``PROTOCOL_VERSION`` moved once for recipient grants and destination trust retiring.

ADR-0321 §9:2 has each change to a shape the wire carries advance the constant on
ADR-0124 §9's rule. This lane's grounds are the six members §7:1 and §7:2 take off the
promoted ``AssistantEngine`` surface, the two record types only they carried, and the
seven errors that leave ``core.errors``, by whose names the wire rebuilds an error. A
test holds that the number moved and that the move is accounted for in the log a
reviewer reads, which is ``test_yes_path_protocol_version.py``'s reasoning: ADR-0124 §9
makes the bump rule a review obligation and decides no mechanical check.
"""

from __future__ import annotations

import inspect
from typing import Final

import pytest

from ai_assistant.wire import envelope

#: The version ADR-0321 §9:2 moves to for this lane, read at the moment the lane landed,
#: and the one it moves from. The absolute figure has one home,
#: ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 107
_MOVED_FROM: Final = 106


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """§9:2: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision() -> None:
    """The entry names ADR-0321 §9:2, and the one it follows stands unrewritten."""
    entry = _entry_for(_MOVED_TO)

    assert "ADR-0321 §9:2" in entry
    assert f"#: {_MOVED_FROM}: " in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


@pytest.mark.parametrize(
    "ground",
    [
        pytest.param("standing_recipient_grants", id="the recipient-grant listing"),
        pytest.param("recent_recipient_grants", id="the recipient-grant history"),
        pytest.param("revoke_recipient_grant", id="the recipient-grant revocation"),
        pytest.param("establish_destination_trust", id="the trust act"),
        pytest.param("standing_destination_trust", id="the trust listing"),
        pytest.param("revoke_destination_trust", id="the trust revocation"),
        pytest.param("RecipientGrant", id="the grant record"),
        pytest.param("DestinationTrustRecord", id="the trust record"),
        pytest.param("RecipientGrantError", id="the grant store's error"),
        pytest.param("InvalidDestinationTrustError", id="the trust store's error"),
        pytest.param("UntrustableDestinationError", id="the trust act's refusal"),
    ],
)
def test_the_entry_names_each_ground(ground: str) -> None:
    """§9:2: one advance covers every ground, so the entry names every one."""
    assert ground in _entry_for(_MOVED_TO)


def _entry_for(version: int) -> str:
    """The version log's entry for one version, one line, comment prefixes removed.

    Args:
        version: The version whose entry to return.

    Returns:
        That entry's prose.
    """
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {version}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    stripped = (line.removeprefix("#:").strip() for line in entry.splitlines())
    return " ".join(part for part in stripped if part)
