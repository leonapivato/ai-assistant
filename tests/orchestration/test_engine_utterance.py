"""ADR-0248's arms: the request as a value of its own, and the no-op it is.

§6's six arms and §10's first three, driven through the **real** ``Engine`` over the
canonical fakes. §6's closing clause is what fixes the shape of every case here:

> No arm may establish the no-op by constructing a turn whose ``utterance`` the test
> itself sets to the goal statement. The arms drive the production path from an
> utterance, which is the only construction under which the equality is the system's
> claim rather than the test's.

So nothing below builds a :class:`~ai_assistant.core.types.TurnResult`. Every case starts
at ``converse`` — or, on the parked path, at ``converse`` and then ``resume`` — and reads
what the episode store and the model seam were actually handed. A case that
asserted ``turn.utterance == turn.goal.statement`` over a turn it had assembled itself
would pass against an implementation that read the request off the goal, which is exactly
the implementation ADR-0248 §1 forbids.

**What "unchanged across the change" is asserted as.** The episode's ``content`` is no
longer a rendering of the turn: ADR-0284 §7 derives it by one rule from the record, and
the user's sentence is in it because the trigger recorded it as the user's input — which
is what the episode arms below assert. The archive arms these cases carried went with
the archive (ADR-0287 §2, §5).

**The store's own arms are not here.** §10's park arms — the round trip, the settlement
clearing a fourth field, the schema upgrade and the trigger refusals — belong to
``tests/permissions/`` beside the store and the shared conformance suite.
"""

from __future__ import annotations

from typing import Final

import pytest

from ai_assistant.core.types import TurnResult
from ai_assistant.orchestration.loop import LearningLoop

#: One sentence no other case in this tree says, so a match anywhere is this turn's. It
#: carries a quotation mark and a non-ASCII character because the composing arm is over
#: ``_quoted_span``'s rendering of it, and a plain ASCII word would leave that escaping
#: unexercised while still passing.
_SAID: Final = 'where did I leave the "café" receipt'

#: The same sentence with surrounding whitespace, for the one-normalisation arm.
_PADDED: Final = f"  \n{_SAID}\t "


# --- §10's first three arms --------------------------------------------------


def test_a_turn_result_cannot_be_constructed_without_a_request() -> None:
    """§1: "required with no default".

    A defaulted field would be exactly the *"second authority"* ADR-0225 §1's
    handed-to-capture clause exists to prevent — a turn whose request nobody set,
    rendering as the empty string under a heading that says the words are the user's.
    """
    with pytest.raises(ValueError, match="utterance"):
        TurnResult()  # type: ignore[call-arg]


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "], ids=["empty", "spaces", "mixed"])
def test_the_field_itself_refuses_a_blank_request(blank: str) -> None:
    """§1: ``NonBlankEncodableText`` "tightened by a rejection alone" (ADR-0096 §2).

    Stated over the field rather than over the pass, because the pass's refusal is what
    a caller meets and this is what makes the type honest independently of it: a second
    producer of a ``TurnResult`` cannot put a blank where the user's words go.
    """
    with pytest.raises(ValueError, match="blank"):
        TurnResult.model_validate({"utterance": blank})


def test_the_one_normalisation_is_the_one_the_goal_is_minted_from() -> None:
    """§1, over the function that holds it.

    The behavioural arms above show the two values agreeing; this names the reason they
    must. ``_request_of`` is where the turn path strips, ``_goal_from`` takes what it
    returned and strips nothing further, and the turn is handed that same string — so
    there is no second normalisation that could come to disagree with the first, which is
    the property §6's byte-equality actually rests on.
    """
    request = LearningLoop._request_of(_PADDED)

    assert request == _SAID
    assert LearningLoop._request_of(request) == request, "normalising twice changes nothing"
