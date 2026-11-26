"""``PROTOCOL_VERSION`` moved for the error a write crossing homes raises (ADR-0124 §9).

ADR-0383 §13 adds :class:`~ai_assistant.core.errors.CrossHomeWriteError`, the memory write
path's refusal of a write that crosses homes (§4:6, §4:7). It is a ``MemoryStoreError``,
which promoted-surface methods that write memory declare, and the wire carries an error's
concrete class name as its code: a peer that does not know the name raises
``ProtocolError`` rather than the declared failure. So the version moves in the change
that adds the class (ADR-0219 §6's ground). A test holds that the number moved, that the
move is accounted for in the log a reviewer reads, and that the error crosses the wire as
itself.
"""

from __future__ import annotations

import inspect
from typing import Final

import pytest

from ai_assistant.core.errors import CrossHomeWriteError, MemoryStoreError
from ai_assistant.wire import envelope
from ai_assistant.wire.errors import error_payload, raise_from_payload

#: The version this lane moves to, read at the moment it landed, and the one it moves
#: from. The absolute figure has one home, ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 140
_MOVED_FROM: Final = 139


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """ADR-0124 §9: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_the_error_and_its_ground() -> None:
    """The entry names the class, ADR-0383 and ADR-0219 §6, and the one before stands."""
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {_MOVED_TO}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    flat = " ".join(line.removeprefix("#:").strip() for line in entry.splitlines())

    assert "CrossHomeWriteError" in flat
    assert "ADR-0383" in flat
    assert "ADR-0219 §6" in flat
    assert f"#: {_MOVED_FROM}: " in source, (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_the_error_crosses_the_wire_as_itself() -> None:
    """ADR-0085 §10a: its code is its own name, and the peer raises the same class."""
    payload = error_payload(CrossHomeWriteError("names a record of another home"), max_bytes=4096)

    assert payload["code"] == "CrossHomeWriteError"
    with pytest.raises(CrossHomeWriteError, match="another home") as raised:
        raise_from_payload(payload)
    assert isinstance(raised.value, MemoryStoreError)
