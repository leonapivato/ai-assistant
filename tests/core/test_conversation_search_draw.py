"""``ConversationSearchDraw``: one counter and one flag (ADR-0238 §8, §13).

The read model ``ConversationStore.search_draw`` answers. The *store's* clauses —
the increment, the fold, the lifecycle edges, the atomicity — are asserted by the
shared conformance suite under ``tests/memory/``; what is here is what the **type**
decides, and the one field whose required-ness is load-bearing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    Conversation,
    ConversationExport,
    ConversationSearchDraw,
    ConversationTurn,
)


def test_the_draw_carries_two_fields_and_no_third() -> None:
    """§8 states the members exactly, and "a fourth is added by no lane".

    **One counter and one flag and no content** — no query, no result, no destination,
    no record, no text — which is what keeps a Tier 1 fact about *what a conversation
    searched* from becoming a record of *what it searched for*.
    """
    assert set(ConversationSearchDraw.model_fields) == {"calls", "all_external_user_chosen"}
    assert ConversationSearchDraw.model_config.get("frozen") is True
    assert ConversationSearchDraw.model_config.get("extra") == "forbid"


def test_the_flag_is_required_with_no_default() -> None:
    """§8 says so in terms, and the reason is that a default would fuse two states.

    The value at creation is ``True`` and **only** ``ConversationStore.start`` creates
    it — a conversation ``start`` mints has no turns, so the sentence is vacuously true
    of it. A record written **before** this decision decodes ``False``, which is
    ADR-0181 §12's reading of a pre-existing row and the fail-closed direction. A
    default here would make a store unable to tell the two apart, and whichever value
    it chose would be wrong for one of them: ``True`` would launder every legacy
    conversation clean, and ``False`` would close every fresh one at birth.
    """
    required = {
        name for name, field in ConversationSearchDraw.model_fields.items() if field.is_required()
    }

    assert required == {"calls", "all_external_user_chosen"}
    with pytest.raises(ValidationError, match="all_external_user_chosen"):
        ConversationSearchDraw(calls=0)  # type: ignore[call-arg]


@pytest.mark.parametrize("spent", [-1, -100])
def test_a_negative_count_is_refused(spent: int) -> None:
    """Non-negative, because ``calls`` is what a ceiling is compared against.

    A negative draw would admit searches past the bound while every message still
    named a ceiling, which is the mechanism turned off by a number rather than by an
    operator.
    """
    with pytest.raises(ValidationError):
        ConversationSearchDraw(calls=spent, all_external_user_chosen=True)


def test_zero_is_the_ordinary_starting_value() -> None:
    """The other side of the bound: a fresh conversation has spent nothing."""
    assert ConversationSearchDraw(calls=0, all_external_user_chosen=True).calls == 0


def test_the_conversation_types_gain_no_field_and_the_export_keeps_its_version() -> None:
    """§8 and §13: the draw is the store's **own row state**, not presented model state.

    It holds the position the turn index and ``ParkedBinding``'s uniqueness already
    hold, and ``search_draw`` is the read that presents them — added for
    `orchestration`'s use and not for a surface. So ``ConversationExport.schema_version``
    stays at **2** and ADR-0212 §8 and ADR-0014 §5 are untouched, which §17 names as
    one of two "near misses" this decision avoids by a decision rather than by luck.

    **A lane that finds a user-facing need for the draw moves that version in the same
    change**, with the records that entails, rather than reading this as permission not
    to (§16).
    """
    assert "search_calls" not in Conversation.model_fields
    assert "all_external_user_chosen" not in Conversation.model_fields
    assert "search_calls" not in ConversationTurn.model_fields
    assert ConversationExport(exported_at=datetime(2026, 9, 9, tzinfo=UTC)).schema_version == 2
