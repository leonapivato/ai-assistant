"""ADR-0242's explanation and ADR-0247's authority, driven through the **engine**.

``tests/orchestration/test_search_not_serviced.py`` drives the servicing site and the
loop; this module drives the pipeline **above** them — ``Engine.converse``, the real
``ComposingStage`` it forwards to, and the ``TurnOutcome`` it builds — because ADR-0242
§7's carrier and §9's field are two consumers of one computed member and a lane that
dropped either forwarding would leave every loop-level assertion passing while the user
lost the explanation.

**ADR-0247 §12's Arms A, B and J are here on the same ground**, because each is a
statement about a whole deployment rather than about one servicing: what a turn asks the
user, what the grant seam is consulted for, and what a trust store that cannot be read
decides. ADR-0242 §15's journeys through the trust act are **gone rather than moved** —
ADR-0247 §1 stops the servicing site consulting the store, so ``TRUST_MISSING`` has no
producer on a configured deployment (§6, #2252) and a journey that established trust to
make a search run has no subject. The member, its mapping and its statement all stay
ratified, and the mapping is still asserted over ``not_serviced`` directly.

The harness is ``test_engine``'s, because what these cases are about is the real
pipeline: the production ``ThresholdActionPolicy`` over the destination this deployment
is configured with, the real
:class:`~ai_assistant.orchestration.reads.SearchServicer`, the trust store the
composition root still wires into the ``trust-destinations`` surface, and the capture
point that is "the single place a ``TurnOutcome`` is built".
"""

from __future__ import annotations

from typing import Final

from ai_assistant.core.types import SearchNotServiced

#: A distinctive clause of ADR-0242 §7's ``AUTHORISATION_AWAITED`` fragment, quoted so
#: this module asserts the **fragment** reached the prompt rather than that two prompts
#: differ — which they also do for reasons ADR-0228 §10 owns.
_AWAITED_FRAGMENT: Final = "instead of making that lookup it was put to this person as a question"

#: One distinctive clause per ADR-0242 §7 fragment, for the arm that says a serviced turn
#: is told about no lookup at all. Written out rather than reached for through the
#: composing module's private table, because what is asserted is what the prompt says.
_FRAGMENTS: Final = (
    # ADR-0244 §12's ninth member, first in the enumeration and first here. The
    # discriminator against `_AWAITED_FRAGMENT` below is the whole point of the member:
    # that one says a question is on record for the user to answer *through an act*,
    # this one says a lookup is waiting on their answer — and neither says the lookup
    # produced nothing, which is the literal #2221 records as false.
    "waiting on an answer from this person before it can be made",
    # `SEARCH_DISABLED`'s and `NOT_ADMITTED`'s fragments stood here and are gone with
    # their members (ADR-0247 §6): each was defined over `admit_search`'s refusal and
    # over `Settings.search_calls_per_conversation`'s value, and §5 removes the
    # per-conversation call budget entire.
    "a limit this installation is run under stood in the way",
    "the rules this installation is run under declined it",
    "is not one this person has chosen to have things composed for",
    _AWAITED_FRAGMENT,
    "it was stopped before it came back",
    "that lookup produced nothing this turn could use",
)


# --- §15's journeys, over the state ADR-0247 leaves them in -------------------


def test_the_quoted_fragments_are_the_ones_the_composing_stage_holds() -> None:
    """The clauses above are quotations, and this is what keeps them quotations.

    ADR-0242 §13 fixes the fragments as **literals, one per member**, so a lane editing
    one must edit the arm that reads it too — and a lane adding a member finds this arm
    rather than a prompt with nothing in it. ADR-0244 §12 is the lane that found it: the
    count is read off the vocabulary rather than written out, so the assertion is that
    the table and the enumeration **agree**, which is the property §13 is about.
    """
    from ai_assistant.orchestration import composing  # noqa: PLC0415 — one arm's subject

    written = composing._SEARCH_NOT_SERVICED_PROMPTS

    assert len(written) == len(SearchNotServiced) == len(_FRAGMENTS)
    for quoted in _FRAGMENTS:
        assert sum(quoted in text for text in written.values()) == 1, quoted
