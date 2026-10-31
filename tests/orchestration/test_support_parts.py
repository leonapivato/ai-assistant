"""A support's part resolves to that part's own content (ADR-0328 §15:2, §15:7).

Never to the episode's search text (ADR-0284 §7): each part of one episode reads as
itself, and a part the episode does not hold reads as gone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from story_support import episode

from ai_assistant.core.types import (
    ActionRequest,
    ActivationDigest,
    ActivationEffect,
    AskedCall,
    CallOutcomeKind,
    CapabilityResult,
    ChannelIdentity,
    ConfirmationPart,
    DeliveryStatus,
    DigestOutcome,
    EpisodicMemory,
    EvidenceItem,
    EvidenceItemPart,
    InputPart,
    LegacyPart,
    MemorySource,
    MessageCallPart,
    ObserverInferencePart,
    PinPart,
    PlanningRound,
    ProposedCall,
    Provenance,
    QuestionPart,
    RecordedCall,
    RecordedDelivery,
    RecordedInputMessage,
    RememberCallPart,
    RoundMessagePart,
)
from ai_assistant.orchestration.authorizer import values_digest
from ai_assistant.orchestration.planning import LOOKING_FOR
from ai_assistant.orchestration.remembering import (
    EPISODE_ARGUMENT,
    OUTSIDE_CONTENT_ARGUMENT,
    REMEMBER_CANDIDATE,
    REMEMBER_CAPABILITY,
    STATEMENT_ARGUMENT,
)
from ai_assistant.orchestration.support_parts import (
    INFERENCE_CONTENT,
    PIN_CONTENT,
    episodes_to_read,
    part_content,
    remember_activations,
)
from ai_assistant.testing.memories import (
    confirmed_support,
    memory,
    message_support,
    remembered_support,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import SupportPart

AT: Final = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

_DIGEST_SHA: Final = "0" * 64


def _held(record: EpisodicMemory, **processing: object) -> EpisodicMemory:
    """``record`` with its processing record carrying ``processing``'s fields."""
    assert record.processing_record is not None
    return record.model_copy(
        update={"processing_record": record.processing_record.model_copy(update=processing)}
    )


def _round(round_id: str, text: str = "", **fields: object) -> PlanningRound:
    return PlanningRound(id=round_id, recorded_at=AT, text=text).model_copy(update=fields)


def _remember_call(call_id: str, statement: str) -> ProposedCall:
    """A remember call as planning proposed it, its *looking for* argument still on."""
    return ProposedCall(
        call_id=call_id,
        name=REMEMBER_CAPABILITY,
        arguments={"statement": statement, LOOKING_FOR: "to keep it"},
    )


#: ``remember`` as ADR-0328 §13's interim declared it, which no hub offers now: the records
#: its calls left still carry it, and a support pointing at one reads the statement it took.
REMEMBER = REMEMBER_CANDIDATE.model_copy(
    update={
        "result": CapabilityResult.NONE,
        "parameters_schema": {
            "type": "object",
            "properties": {
                STATEMENT_ARGUMENT: {"type": "string", "minLength": 1},
                EPISODE_ARGUMENT: {"type": "string", "minLength": 1},
                OUTSIDE_CONTENT_ARGUMENT: {"type": "boolean"},
            },
            "required": [STATEMENT_ARGUMENT, EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT],
            "additionalProperties": False,
        },
    }
)


def _ran_digest(statement: str) -> str:
    """The digest acting claims for the remember call it ran with ``statement``.

    Computed by authorizing's twin of acting's digest (a test holds the two to one
    answer), over the values the call ran with: the hub's two filled in, the *looking
    for* argument removed.
    """
    return values_digest(
        ActionRequest(
            tool=REMEMBER,
            parameters={
                "statement": statement,
                EPISODE_ARGUMENT: "activation:a",
                OUTSIDE_CONTENT_ARGUMENT: False,
            },
        )
    )


def _effect(
    effect_id: str, activation_id: str, round_id: str, digest: str = _DIGEST_SHA
) -> ActivationEffect:
    return ActivationEffect(
        id=effect_id,
        activation_id=activation_id,
        round=round_id,
        capability=REMEMBER_CAPABILITY,
        values_digest=digest,
        decision_id="decision-1",
        claimed_at=AT,
    )


def _content(
    part: SupportPart,
    episodes: Mapping[str, EpisodicMemory],
    *,
    effects: Mapping[str, ActivationEffect] | None = None,
    carried: Mapping[str, object] | None = None,
) -> str | None:
    return part_content(part, episodes=episodes, effects=effects or {}, carried=carried)


def test_each_part_of_one_episode_reads_as_itself() -> None:
    """The input, a recorded message, a round's message and an evidence item: four texts."""
    record = _held(
        episode("a", text="the office moved to Boston"),
        rounds=(_round("r-1", "Noted: the office is in Boston."),),
        digests=(
            ActivationDigest(
                question="where is the office?",
                outcome=DigestOutcome.ANSWERED,
                evidence=(EvidenceItem(text="The HQ address is in Boston.", source="R1"),),
                recorded_at=AT,
            ),
        ),
    )
    trigger = record.processing_record.trigger if record.processing_record else None
    assert trigger is not None
    record = _held(
        record,
        trigger=trigger.model_copy(
            update={"messages": (RecordedInputMessage(text="moved to Boston", sent_at=AT),)}
        ),
    )
    episodes = {record.id: record}

    assert _content(InputPart(episode=record.id), episodes) == "the office moved to Boston"
    assert _content(InputPart(episode=record.id, message=0), episodes) == "moved to Boston"
    assert (
        _content(RoundMessagePart(episode=record.id, round="r-1"), episodes)
        == "Noted: the office is in Boston."
    )
    assert (
        _content(EvidenceItemPart(episode=record.id, digest=0, item=0), episodes)
        == "The HQ address is in Boston."
    )


def test_a_part_the_episode_does_not_hold_is_gone() -> None:
    """A position past the end, a round never recorded, a digest never kept: all gone."""
    record = _held(episode("a"), rounds=(_round("r-1", "said"),))
    episodes = {record.id: record}

    assert _content(InputPart(episode=record.id, message=0), episodes) is None
    assert _content(RoundMessagePart(episode=record.id, round="r-9"), episodes) is None
    assert _content(EvidenceItemPart(episode=record.id, digest=0, item=0), episodes) is None
    assert _content(InputPart(episode="activation:absent"), episodes) is None


def _evidence(*texts: str) -> ActivationDigest:
    return ActivationDigest(
        question="where is the office?",
        outcome=DigestOutcome.ANSWERED,
        evidence=tuple(EvidenceItem(text=text, source="R1") for text in texts),
        recorded_at=AT,
    )


def test_each_position_of_an_indexed_collection_reads_as_its_own_part() -> None:
    """A later message, digest or item reads as itself; one past the end of each is gone.

    Each collection holds distinct texts at several positions, so a resolver reading the
    wrong position, or one past the end, reads as another part's text and is caught.
    """
    record = _held(
        episode("a"),
        rounds=(_round("r-1", "first round"), _round("r-2", "second round")),
        digests=(
            _evidence(
                "first digest, first item", "first digest, second item", "first digest, third item"
            ),
            _evidence("second digest, first item"),
        ),
    )
    trigger = record.processing_record.trigger if record.processing_record else None
    assert trigger is not None
    texts = ("the first message", "the second message", "the third message")
    record = _held(
        record,
        trigger=trigger.model_copy(
            update={"messages": tuple(RecordedInputMessage(text=t, sent_at=AT) for t in texts)}
        ),
    )
    episodes = {record.id: record}

    for position, text in enumerate(texts):
        assert _content(InputPart(episode=record.id, message=position), episodes) == text
    assert _content(InputPart(episode=record.id, message=len(texts)), episodes) is None

    for round_id, text in (("r-1", "first round"), ("r-2", "second round")):
        assert _content(RoundMessagePart(episode=record.id, round=round_id), episodes) == text

    def item(digest: int, item: int) -> str | None:
        return _content(EvidenceItemPart(episode=record.id, digest=digest, item=item), episodes)

    assert item(0, 1) == "first digest, second item"
    assert item(0, 2) == "first digest, third item"
    assert item(0, 3) is None, "one past the first digest's items"
    assert item(1, 0) == "second digest, first item"
    assert item(1, 1) is None, "the second digest's own bound, not the first's"
    assert item(2, 0) is None, "one past the digests"


def test_a_round_that_wrote_no_message_has_no_message_to_show() -> None:
    record = _held(episode("a"), rounds=(_round("r-1", ""),))
    assert _content(RoundMessagePart(episode=record.id, round="r-1"), {record.id: record}) is None


def _text_entry(call_id: str, delivered: RecordedDelivery | None) -> RecordedCall:
    return RecordedCall(
        round="r-1",
        call_id=call_id,
        capability="text",
        effect=True,
        outcome=CallOutcomeKind.DONE if delivered is not None else CallOutcomeKind.REFUSED,
        reason=None if delivered is not None else "names a place you were never shown",
        delivered=delivered,
        recorded_at=AT,
    )


def test_a_message_call_reads_as_the_words_it_sent_and_as_nothing_where_it_sent_none() -> None:
    """ADR-0356 §13:2, §14:9: a support at a ``MessageCallPart`` resolves to the words its
    entry holds as delivered, and to nothing for a call that sent none."""
    sent = RecordedDelivery(
        words="It's booked for Thursday.",
        went=ChannelIdentity(channel_type="conversation", instance_id="chat"),
        status=DeliveryStatus.SENT,
    )
    calls = (
        ProposedCall(call_id="c1", name="text", arguments={"words": "Booked."}),
        ProposedCall(call_id="c2", name="text", arguments={"words": "Elsewhere.", "via": "L9"}),
    )
    record = _held(
        episode("a"),
        rounds=(_round("r-1", calls=calls),),
        call_records=(_text_entry("c1", sent), _text_entry("c2", None)),
    )
    held = {record.id: record}

    def part(call_id: str) -> MessageCallPart:
        return MessageCallPart(episode=record.id, round="r-1", call_id=call_id)

    assert _content(part("c1"), held) == "It's booked for Thursday."
    assert _content(part("c2"), held) is None
    assert _content(part("c9"), held) is None
    assert _content(part("c1"), {}) is None
    assert episodes_to_read([memory("m", "said", message_support(record.id))]) == (record.id,)


def test_an_episode_recorded_without_a_processing_record_holds_only_its_input() -> None:
    """Its content is the exchange as it was recorded; it keeps no rounds or messages apart."""
    bare = EpisodicMemory(
        id="ep-bare",
        content="The user asked: is it in Boston?",
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )
    episodes = {bare.id: bare}

    assert _content(InputPart(episode=bare.id), episodes) == "The user asked: is it in Boston?"
    assert _content(InputPart(episode=bare.id, message=0), episodes) is None
    assert _content(RoundMessagePart(episode=bare.id, round="r-1"), episodes) is None


def test_a_confirmation_reads_as_the_statement_its_approved_part_showed() -> None:
    """The asking round's asked call, by part: what the user said yes to (§4:6)."""
    asking = _held(
        episode("ask"),
        rounds=(
            _round(
                "r-ask",
                "Shall I remember that you like tea?",
                asked=(
                    AskedCall(
                        part=1,
                        tool=REMEMBER,
                        values={
                            "statement": "likes tea",
                            EPISODE_ARGUMENT: "activation:ask",
                            OUTSIDE_CONTENT_ARGUMENT: False,
                        },
                    ),
                ),
            ),
        ),
    )
    yes = episode("yes", text="yes")
    episodes = {asking.id: asking, yes.id: yes}
    part = ConfirmationPart(
        episode=yes.id, asking_activation="ask", question=QuestionPart(round="r-ask", part=1)
    )

    assert _content(part, episodes) == "likes tea"
    assert _content(part, {asking.id: asking}) is None, "the yes's episode is gone"
    wrong_part = part.model_copy(update={"question": QuestionPart(round="r-ask", part=2)})
    assert _content(wrong_part, episodes) is None


def test_a_confirmation_for_a_later_part_reads_as_that_parts_statement() -> None:
    """A round asking two parts: a yes to part 2 reads as part 2's statement, not part 1's.

    Parts number from one (ADR-0321 §2:6), so part 2 is the round's last asked call and
    part 3 is one past the end.
    """

    def asked(part: int, statement: str) -> AskedCall:
        return AskedCall(
            part=part,
            tool=REMEMBER,
            values={
                "statement": statement,
                EPISODE_ARGUMENT: "activation:ask",
                OUTSIDE_CONTENT_ARGUMENT: False,
            },
        )

    asking = _held(
        episode("ask"),
        rounds=(
            _round(
                "r-ask",
                "Shall I remember that you like tea, and that you live in Lisbon?",
                asked=(asked(1, "likes tea"), asked(2, "lives in Lisbon")),
            ),
        ),
    )
    yes = episode("yes", text="yes")
    episodes = {asking.id: asking, yes.id: yes}

    def approved(part: int) -> str | None:
        question = QuestionPart(round="r-ask", part=part)
        confirmation = ConfirmationPart(episode=yes.id, asking_activation="ask", question=question)
        return _content(confirmation, episodes)

    assert approved(1) == "likes tea"
    assert approved(2) == "lives in Lisbon"
    assert approved(3) is None, "one past the round's asked parts"


def test_a_confirmed_candidate_reads_as_the_fact_its_approved_part_showed() -> None:
    """ADR-0329 §5:5: once ``remember`` records candidates, the yes approved the fact."""
    asking = _held(
        episode("ask"),
        rounds=(
            _round(
                "r-ask",
                "Want me to remember you like tea?",
                asked=(
                    AskedCall(
                        part=1,
                        tool=REMEMBER_CANDIDATE,
                        values={
                            "fact": "The user likes tea.",
                            "why": "drinks",
                            "rests_on_input": True,
                            "confirm": True,
                            EPISODE_ARGUMENT: "activation:ask",
                            OUTSIDE_CONTENT_ARGUMENT: False,
                        },
                    ),
                ),
            ),
        ),
    )
    yes = episode("yes", text="yes")
    part = ConfirmationPart(
        episode=yes.id, asking_activation="ask", question=QuestionPart(round="r-ask", part=1)
    )

    assert _content(part, {asking.id: asking, yes.id: yes}) == "The user likes tea."


def test_a_remember_call_reads_as_the_statement_of_the_call_its_effect_claims() -> None:
    """The effect record names the round; the round's remember call holds the statement."""
    record = _held(
        episode("a"), rounds=(_round("r-1", calls=(_remember_call("c-1", "likes tea"),)),)
    )
    episodes = {record.id: record}
    part = RememberCallPart(episode=record.id, effect="effect-1")
    effects = {"effect-1": _effect("effect-1", "a", "r-1")}

    assert _content(part, episodes, effects=effects) == "likes tea"
    assert _content(part, episodes) is None, "the plan store holds no such effect record"
    elsewhere = {"effect-1": _effect("effect-1", "other", "r-1")}
    assert _content(part, episodes, effects=elsewhere) is None


def test_the_effects_digest_picks_its_call_among_two_in_one_round() -> None:
    """The effect record carries the digest of the values acting ran: that is the call."""
    record = _held(
        episode("a"),
        rounds=(
            _round(
                "r-1",
                calls=(
                    _remember_call("c-1", "likes tea"),
                    _remember_call("c-2", "prefers coffee"),
                ),
            ),
        ),
    )
    part = RememberCallPart(episode=record.id, effect="effect-1")
    episodes = {record.id: record}

    for statement in ("likes tea", "prefers coffee"):
        effects = {"effect-1": _effect("effect-1", "a", "r-1", _ran_digest(statement))}
        assert _content(part, episodes, effects=effects) == statement


def test_two_remember_calls_no_digest_tells_apart_are_not_resolved() -> None:
    """Where the effect's digest matches no call, two statements leave it unresolved.

    Never resolved by a memory's wording, which a reinforcement keeps as the target's
    (§11:6): "prefers tea" reinforcing "likes tea" would otherwise show the other call.
    """
    record = _held(
        episode("a"),
        rounds=(
            _round(
                "r-1",
                calls=(_remember_call("c-1", "prefers tea"), _remember_call("c-2", "likes tea")),
            ),
        ),
    )
    part = RememberCallPart(episode=record.id, effect="effect-1")
    effects = {"effect-1": _effect("effect-1", "a", "r-1")}

    assert _content(part, {record.id: record}, effects=effects) is None


def test_two_remember_calls_saying_the_same_statement_resolve_to_it() -> None:
    record = _held(
        episode("a"),
        rounds=(
            _round(
                "r-1",
                calls=(_remember_call("c-1", "likes tea"), _remember_call("c-2", "likes tea")),
            ),
        ),
    )
    part = RememberCallPart(episode=record.id, effect="effect-1")
    effects = {"effect-1": _effect("effect-1", "a", "r-1")}

    assert _content(part, {record.id: record}, effects=effects) == "likes tea"


def test_an_observers_inference_reads_as_what_it_is_while_its_episode_is_held() -> None:
    """ADR-0329 §9:7: the part names no text of the episode, and is gone with it."""
    record = _held(episode("a"))
    part = ObserverInferencePart(episode=record.id)

    assert _content(part, {record.id: record}) == INFERENCE_CONTENT
    assert _content(part, {}) is None


def test_a_pin_reads_as_what_it_is_and_is_never_gone() -> None:
    """ADR-0338 §4:4, §4:7: a pin points into no episode and is kept once removed."""
    part = PinPart(pin="pin-1")

    assert _content(part, {}) == PIN_CONTENT


def test_a_legacy_part_reads_as_the_record_it_carries() -> None:
    part = LegacyPart(record="old")
    assert _content(part, {}, carried={"content": "the user likes tea"}) == "the user likes tea"
    assert _content(part, {}, carried={}) is None


def test_the_reads_a_page_needs_are_named_once_each() -> None:
    """The asking activation's episode is read beside the yes's, and each activation once."""
    confirmed = memory("m-1", "likes tea", confirmed_support("activation:yes"))
    remembered = memory("m-2", "likes tea", remembered_support("activation:a"))

    wanted = episodes_to_read((confirmed, remembered))

    assert wanted == ("activation:yes", "activation:act-asking", "activation:a")
    record = episode("a")
    assert remember_activations((remembered,), {record.id: record}) == ("a",)
    assert remember_activations((remembered,), {}) == ()
