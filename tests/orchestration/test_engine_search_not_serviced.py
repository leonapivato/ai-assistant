"""ADR-0242's explanation, driven through the **engine** (§15).

``tests/orchestration/test_search_not_serviced.py`` drives the servicing site and the
loop; this module drives the pipeline **above** them — ``Engine.converse``, the real
``ComposingStage`` it forwards to, and the ``TurnOutcome`` it builds — because §7's
carrier and §9's field are two consumers of one computed member and a lane that dropped
either forwarding would leave every loop-level assertion passing while the user lost the
explanation.

The harness is ``test_engine``'s, because what these cases are about is the real
pipeline: the production ``ThresholdActionPolicy``, the real
:class:`~ai_assistant.orchestration.reads.SearchServicer`, the trust store the
composition root wires into the one servicing site, and the capture point that is "the
single place a ``TurnOutcome`` is built".
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from test_engine import AT, PATIENT, SEARCH_DESTINATIONS, Harness
from test_engine_read_envelope import _AskingPlanner, _recorder
from test_loop_search import _CostedSearcher, _search, _servicer

from ai_assistant.core.types import (
    DestinationTrust,
    DestinationTrustRecord,
    Role,
    SearchNotServiced,
)
from ai_assistant.testing import (
    FakeDestinationTrustStore,
    FakeMemoryStore,
    FakeWebSearcher,
)

if TYPE_CHECKING:
    from ai_assistant.orchestration.composing import ComposingStage
    from ai_assistant.testing import FakeModelProvider

_ASKED: Final = "what has changed since we last spoke"

#: A distinctive clause of ADR-0242 §7's ``AUTHORISATION_AWAITED`` fragment, quoted so
#: this module asserts the **fragment** reached the prompt rather than that two prompts
#: differ — which they also do for reasons ADR-0228 §10 owns.
_AWAITED_FRAGMENT: Final = "instead of making that lookup it was put to this person as a question"

#: One distinctive clause per ADR-0242 §7 fragment, for the arm that says a serviced turn
#: is told about no lookup at all. Written out rather than reached for through the
#: composing module's private table, because what is asserted is what the prompt says.
_FRAGMENTS: Final = (
    "this installation does not make them at all",
    "no such lookup was made on this occasion",
    "a limit this installation is run under stood in the way",
    "the rules this installation is run under declined it",
    "is not one this person has chosen to have things composed for",
    _AWAITED_FRAGMENT,
    "it was stopped before it came back",
    "that lookup produced nothing this turn could use",
)


def _system_prompt(model: FakeModelProvider) -> str:
    """The system message the production stage assembled, from the fake's own record."""
    assert len(model.calls) == 1
    return next(one.content for one in model.calls[0].messages if one.role is Role.SYSTEM)


def _chosen() -> DestinationTrustRecord:
    """A live record over the destination set this deployment's search binds to."""
    return DestinationTrustRecord(
        id="t-1",
        destinations=SEARCH_DESTINATIONS,
        trust=DestinationTrust.USER_CHOSEN,
        established_at=AT - timedelta(days=1),
    )


def _harness(*, granted: bool, trusted: bool, composing: ComposingStage | None = None) -> Harness:
    """The real pipeline, with the two knobs ADR-0242 §8's rows are decided on.

    ``granted`` decides the **ruling** — with a standing recipient grant the production
    ``ThresholdActionPolicy`` reaches ADR-0148 §3's route (b), without it every ruling is
    the ``CONFIRM`` ADR-0231 §9 describes. ``trusted`` decides the **``trust_of``
    answer**, over the store ADR-0238 §14 wires into the one servicing site.

    **The planner asks for a search on both of a turn's calls**, which is ADR-0231 §12's
    own shape and what makes a single ``converse`` reach both a servicing that yields and
    one that is refused: once a minted record is in the turn's supply, the binding of any
    later request in that turn carries ``planned_with_external_content``.
    """
    harness = Harness(
        memory=FakeMemoryStore(now=lambda: AT),
        planner=_AskingPlanner(_search()),
        composing=composing,
        search=_servicer(
            searcher=_CostedSearcher(FakeWebSearcher(results=("a result",))), granted=granted
        ),
    )
    if trusted:
        harness.destination_trust = FakeDestinationTrustStore([_chosen()])
    return harness


async def _driven(
    *, granted: bool, trusted: bool = False, composing: ComposingStage | None = None
) -> Any:
    """One ``converse`` through the real engine, over the real servicing path."""
    return await _harness(granted=granted, trusted=trusted, composing=composing).engine.converse(
        _ASKED, timeout=PATIENT
    )


# --- §7 and §9 are two consumers of one member -------------------------------


async def test_the_engine_puts_the_members_fragment_into_the_prompt_it_assembles() -> None:
    """§7: the carrier reaches the **composing stage**, through the engine's own forwarding.

    Asserted with the production ``ComposingStage`` and a fake ``ModelProvider`` that
    merely records the prompt, which is ADR-0227 §7's fidelity rule: the renderer whose
    output the assertion is about is never substituted.

    An engine that computed the member and forwarded it only to ``TurnOutcome`` would
    pass every field assertion below and compose a reply that says nothing about a lookup
    that did not happen — which is the half of #2168 the owner's amendment names. The
    baseline is a turn that **serviced** its searches, whose prompt §6 leaves
    byte-identical to what it was before this decision.
    """
    composing, model = _recorder()
    bare_composing, bare_model = _recorder()

    outcome = await _driven(granted=False, composing=composing)
    serviced = await _driven(granted=True, trusted=True, composing=bare_composing)

    assert outcome.search_not_serviced is SearchNotServiced.AUTHORISATION_AWAITED
    assert serviced.search_not_serviced is None
    carried, bare = _system_prompt(model), _system_prompt(bare_model)
    assert _AWAITED_FRAGMENT in carried
    # §6 on the other side: a turn that serviced every search it asked for is told
    # **nothing** about a lookup that did not happen. Asserted over the whole vocabulary
    # rather than over one member, so a lane that made the carrier unconditional would
    # fail here whichever member it reached for. (The byte-identity half of §6 is
    # asserted at the loop, where two composes over *one* turn can be compared.)
    for fragment in _FRAGMENTS:
        assert fragment not in bare


async def test_the_engine_carries_the_same_member_onto_the_turn_outcome() -> None:
    """§9: "the same member §7 computed, **by value**, and never a second computation".

    The capture point is the one place a ``TurnOutcome`` is built, and a surface names the
    act from this field — so an engine that recomputed it here could disagree with the
    reply the model was told to compose, which is the drift §9's by-value clause exists
    to prevent.
    """
    composing, model = _recorder()

    outcome = await _driven(granted=False, composing=composing)

    assert outcome.search_not_serviced is SearchNotServiced.AUTHORISATION_AWAITED
    fragment = _system_prompt(model)
    assert "would have looked something up outside this system" in fragment, (
        "one member, two renderings: the field and the prompt are the same computation"
    )
    assert outcome.reply_degraded is False, "§6: a turn that could not search still composed"


async def test_a_turn_whose_searches_were_serviced_carries_no_member_through_the_engine() -> None:
    """§6, §15 Arm 1: ``None`` where every servicing yielded records.

    The grant and the trust record together are what make **both** of this turn's
    servicings ``ALLOW``: the second is composed over what the first returned, which is
    ADR-0238 §5's closed loop closing — and §15 Arm 1 asserts exactly that
    ``search_not_serviced`` is ``None`` on both.
    """
    outcome = await _driven(granted=True, trusted=True)

    assert outcome.search_not_serviced is None


async def test_the_trust_read_discriminates_the_two_confirm_rows_through_the_engine() -> None:
    """§8's finding, at the engine: one disposition, two acts, two members.

    The two turns differ in what the ``trust_of`` read answers — over the store the
    composition root wires into the one servicing site — and in nothing else. ADR-0242
    §8's whole argument is that "an explanation derived from the disposition alone would
    send half of milestone 31's users to the wrong command", and this is that claim made
    checkable above the loop.
    """
    first = await _driven(granted=False)
    follow_up = await _driven(granted=True, trusted=False)

    assert first.search_not_serviced is SearchNotServiced.AUTHORISATION_AWAITED, (
        "no grant, a clean footing: the act is ADR-0235's and the decision one it may ride"
    )
    assert follow_up.search_not_serviced is SearchNotServiced.TRUST_MISSING, (
        "a grant, a follow-up composed over what the first search returned, and a "
        "destination the user has not chosen"
    )


async def test_the_act_does_not_repair_the_conversation_it_was_prompted_by() -> None:
    """§15 Arm 2c's end, through the engine and over one conversation.

    ADR-0238 §5's recorded half is monotone over a conversation: once a record has
    arrived from an ``UNCHOSEN`` destination that conversation "fails the recorded half
    for every later turn", and a trust record established afterwards does not lift it. So
    the same follow-up retried in the same conversation is still refused and now carries
    ``UNAVAILABLE`` — the member that names no act — which is why §9 bars
    ``TRUST_MISSING``'s statement from promising the act repairs *this* conversation.
    """
    harness = _harness(granted=True, trusted=False)

    refused = await harness.engine.converse(_ASKED, timeout=PATIENT)
    await harness.destination_trust.record(_chosen())
    retried = await harness.engine.converse(
        _ASKED, timeout=PATIENT, conversation_id=refused.conversation_id
    )

    assert refused.search_not_serviced is SearchNotServiced.TRUST_MISSING
    assert retried.search_not_serviced is SearchNotServiced.UNAVAILABLE, (
        "the act was performed and this conversation is still closed — naming an act "
        "that cannot help is worse than naming none (§8)"
    )


def test_the_quoted_fragments_are_the_eight_the_composing_stage_holds() -> None:
    """The clauses above are quotations, and this is what keeps them quotations.

    ADR-0242 §13 fixes the fragments as **eight literals, one per member**, so a lane
    editing one must edit the arm that reads it too — and a lane adding a ninth member
    finds this arm rather than a prompt with nothing in it.
    """
    from ai_assistant.orchestration import composing  # noqa: PLC0415 — one arm's subject

    written = composing._SEARCH_NOT_SERVICED_PROMPTS

    assert len(written) == len(SearchNotServiced) == len(_FRAGMENTS)
    for quoted in _FRAGMENTS:
        assert sum(quoted in text for text in written.values()) == 1, quoted
