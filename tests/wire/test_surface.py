"""The reflected surface, and ADR-0173 §4's second adaptation rule.

``wire/surface.py`` reads the method set, the argument types and the result type off
:class:`~ai_assistant.core.protocols.AssistantEngine` rather than transcribing them,
"so a method the Protocol grows is a method this module already knows about". ADR-0173
§4 adds a *rule* to that reflection rather than an exception — "a method whose return
annotation is an async iterator is adapted by **one adapter per member of the yielded
union**, selected by the frame kind being decoded… No method is adapted by both
rules" — and what is checked here is that the rule really is derived and really is
exclusive.
"""

from __future__ import annotations

import pytest

from ai_assistant.core.types import ReplyChunk, TurnOutcome
from ai_assistant.wire.surface import (
    METHODS,
    STREAMING_METHODS,
    chunk_adapter,
    chunk_type,
    parameters,
    return_adapter,
    terminal_adapter,
)


def test_the_streaming_set_is_read_off_the_protocol() -> None:
    """Derived rather than listed, which is what makes it total by construction.

    A second streaming method is one this module already knows about; a table here
    would be a second vocabulary to keep in step with the first, which is the
    objection the module opens with.
    """
    assert STREAMING_METHODS <= METHODS
    assert "converse_streaming" in STREAMING_METHODS
    assert "converse" not in STREAMING_METHODS


def test_a_streaming_method_takes_exactly_the_arguments_the_whole_one_takes() -> None:
    """§4: "exactly ``converse``'s arguments in exactly its shape".

    A wire-visible fact rather than a Python nicety: ``_decode_arguments`` refuses an
    argument a method does not declare, so a surface whose twin diverged by one name
    would fail on the first call rather than at the handshake.
    """
    assert parameters("converse_streaming") == parameters("converse")


def test_a_streaming_method_has_one_adapter_per_member_of_its_union() -> None:
    """§4's rule, both halves, selected by the frame kind rather than the payload."""
    assert chunk_adapter("converse_streaming").validate_python({"text": "half an"}) == ReplyChunk(
        text="half an"
    )
    assert chunk_type("converse_streaming") is ReplyChunk
    outcome = terminal_adapter("converse_streaming").validate_python({"turn": None})
    assert isinstance(outcome, TurnOutcome)


def test_no_method_is_adapted_by_both_rules() -> None:
    """§4 in terms, and the refusal is what keeps the two rules from overlapping.

    A single result adapter over an async-iterator annotation is a value nothing can
    validate, so returning one would be worse than refusing: the failure would
    surface as a decode error inside a call rather than as a build-time mistake.
    """
    with pytest.raises(KeyError):
        return_adapter("converse_streaming")
    for name in ("converse", "resume"):
        with pytest.raises(KeyError):
            chunk_adapter(name)
        with pytest.raises(KeyError):
            terminal_adapter(name)
        with pytest.raises(KeyError):
            chunk_type(name)


def test_a_non_streaming_method_keeps_its_single_result_adapter() -> None:
    """§4: "a non-streaming method keeps its single result adapter"."""
    outcome = return_adapter("converse").validate_python({"turn": None})
    assert isinstance(outcome, TurnOutcome)


def test_an_unknown_method_is_refused_by_every_adapter() -> None:
    """The reflection's existing contract, extended to the two new accessors."""
    for accessor in (return_adapter, chunk_adapter, terminal_adapter, chunk_type):
        with pytest.raises(KeyError):
            accessor("no_such_method")
