"""``ConversationSearchDraw``: one counter and one flag (ADR-0238 §8, §13).

The read model ``ConversationStore.search_draw`` answers. The *store's* clauses —
the increment, the fold, the lifecycle edges, the atomicity — are asserted by the
shared conformance suite under ``tests/memory/``; what is here is what the **type**
decides, and the one field whose required-ness is load-bearing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant import orchestration
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


# --- §8's flag is read and folded together, or not at all (ADR-0137 §2's seam cut) ---


#: The three names ADR-0238 §8 makes one mechanism: the read that presents the footing,
#: and the fold that maintains it. ``admit_search`` is deliberately **not** here — §8
#: says in terms that it "does not consult the flag" and that "no member of this store
#: gates admission on the footing", so a lane wiring admission alone changes nothing
#: about what the flag means.
_FOOTING_READ: Final = "search_draw"
_FOOTING_FOLD: Final = "observe_search"


def _orchestration_sources() -> str:
    """Every line of ``ai_assistant.orchestration``, concatenated.

    A text scan rather than an import graph, because what is being asked is whether a
    *call site exists at all* — the cheapest possible question, and one that cannot be
    answered by wiring, since ADR-0238 §8's members are reached through a Protocol the
    subsystem already holds for other reasons.
    """
    package = Path(orchestration.__file__).parent
    return "\n".join(module.read_text(encoding="utf-8") for module in sorted(package.rglob("*.py")))


def test_the_footing_is_read_and_folded_in_one_change_or_in_neither() -> None:
    """The half-wired state ADR-0238 §8's flag semantics would be false in.

    §8 makes the flag mean *every turn this decision has observed was clean*, and that
    sentence is only true where `orchestration` both **reads** it at build time and
    **folds** it — at admission of a disqualifying span, and again at capture. A tree
    that read the footing without folding it would report a conversation clean on the
    strength of turns nobody observed, which is the exact misreading §13's decoded
    ``False`` exists to prevent one epoch earlier.

    **So this is a biconditional, not a prohibition.** It passes on the contract lane's
    tree, where neither name appears and the mechanism is legible and inert — the
    posture ADR-0238's own exit note describes and ADR-0231 §9 recorded for the search
    itself. It passes again once the consumer lane wires both. It fails on exactly one
    state: the half where a reader has landed and its folds have not.

    **Why a test rather than a note.** ADR-0238's implementation was cut at its contract
    seam under ADR-0137 §2, and §4 of that decision makes every further consumer group a
    follow-on lane briefed against the merged contract. What a seam cut cannot leave
    behind is a rule kept by whoever reads the brief; this is that rule as a mechanism,
    and it is the one thing the contract lane can do about a state it does not itself
    reach. The lane that lands the consumer group deletes nothing here — it makes both
    halves true.

    The residue this does *not* close is filed: a conversation started between the two
    lanes carries a ``True`` neither lane observed, which #2186 records with what would
    fire a decision about it.
    """
    sources = _orchestration_sources()

    reads = _FOOTING_READ in sources
    folds = _FOOTING_FOLD in sources

    assert reads == folds, (
        f"`orchestration` {'reads' if reads else 'folds'} ADR-0238 §8's footing without "
        f"{'folding' if reads else 'reading'} it. The flag means *every turn this decision "
        f"has observed was clean*, which is false of a tree that maintains it on only one "
        f"side — see ADR-0238 §8 and §13."
    )
