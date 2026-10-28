"""ADR-0345's record in ``core``: holders, people, labels, marks and the placement's shape.

Each rule here is one ``core`` holds for every writer and the upgrade alike (ADR-0016
§2): §2's holder table and what makes two holders one, the names a part gives (§9:3),
the person filter (§9:6), and the shapes a proposal's placement and a memory's new fields
take. What a writer does with them is the shared suites'.
"""

from __future__ import annotations

from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Attestation,
    ChannelContext,
    ChannelIdentity,
    ClaimedAuthor,
    EpisodeProcessingRecord,
    EpisodicMemory,
    HolderKind,
    InputPart,
    LabelBounds,
    MemoryMark,
    MemoryOperation,
    MemoryOperationKind,
    MemoryPlacement,
    MemorySource,
    MemorySupport,
    MemoryUpdateProposal,
    MemoryWriterName,
    PlacedAnswer,
    PlacedPair,
    PlacedRelation,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedTextInput,
    SemanticMemory,
    SituationLabel,
    StatementPart,
    SupportDirection,
    SupportHolder,
    SupportOrigin,
    UnderstandingOmission,
    WholeTextReply,
    names_not_given,
    names_person,
    stamped_support,
    support_holder,
)
from ai_assistant.testing.activation import ended_pass
from ai_assistant.testing.memories import (
    AT,
    confirmed_support,
    inference_support,
    legacy_support,
    memory,
    message_support,
    pinned_support,
    remembered_support,
    said_support,
    sourced_support,
    support_with_origin,
)
from ai_assistant.testing.parties import ASSISTANTS_WORDS, OWNERS_WORDS, line_input

_OWNER: Final = SupportHolder.person(OWNER_PERSON_ID)
_CHANNEL: Final = ChannelIdentity(channel_type="telegram", instance_id="line")


def _episode(
    *messages: RecordedInputMessage, parties: tuple[SupportHolder, ...] | None = None
) -> EpisodicMemory:
    """An episode whose input took ``messages`` in on the line, or carries ``parties``."""
    if parties is None:
        parties, messages = line_input(messages) if messages else (OWNERS_WORDS, ())
    return EpisodicMemory(
        id="activation:held",
        content="",
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
        processing_record=EpisodeProcessingRecord(
            activation_id="held",
            started_at=AT,
            ended_at=AT,
            trigger=RecordedChannelTrigger(
                target=_CHANNEL,
                channel=_CHANNEL,
                payload=RecordedTextInput(text=" ".join(one.text for one in messages)),
                context=ChannelContext(),
                reply=WholeTextReply(),
                parties=parties,
                messages=messages,
            ),
            status=ProcessingStatus.COMPLETED,
            reason=ProcessingReason.RETURNED,
            understanding_omitted=UnderstandingOmission.NOT_REACHED,
            stages=ended_pass(AT),
        ),
    )


def _forward(account: int | None) -> RecordedInputMessage:
    return RecordedInputMessage(
        text="Ana works at Santa Maria.",
        sent_at=AT,
        forwarded_from=ClaimedAuthor(name="Marta", account_id=account),
    )


def _outside(message: int | None = 0) -> MemorySupport:
    return support_with_origin(SupportOrigin.OUTSIDE_INPUT).model_copy(
        update={
            "points_at": InputPart(episode="activation:held", message=message),
            "source_details": None,
        }
    )


# --- §2's table -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("support", "holder"),
    [
        (said_support(), _OWNER),
        (confirmed_support(), _OWNER),
        (pinned_support(), _OWNER),
        (message_support(), SupportHolder.statement(StatementPart.ROUND_MESSAGE)),
        (remembered_support(), SupportHolder.statement(StatementPart.REMEMBER_CALL)),
        (inference_support(), SupportHolder.statement(StatementPart.OBSERVER_INFERENCE)),
        (legacy_support({"id": "old"}), SupportHolder.unknown()),
        (
            sourced_support(Attestation(reported_by="staff-page", reported_at=AT)),
            SupportHolder.source("staff-page", claimed=False),
        ),
        (sourced_support(None), SupportHolder.unknown()),
    ],
    ids=[
        "user-message",
        "confirmation",
        "pin",
        "round-message",
        "remember-call",
        "inference",
        "legacy",
        "evidence-naming-its-source",
        "evidence-naming-none",
    ],
)
def test_each_part_takes_the_holder_the_table_gives_it(
    support: MemorySupport, holder: SupportHolder
) -> None:
    """§2's table, row by row, from the part and the record."""
    assert support_holder(support, _episode()) == holder


def test_a_forward_is_held_by_its_claimed_sender_and_otherwise_unknown() -> None:
    """§2's fourth row, §2:6: a claimed source by the medium's identifier, or unknown."""
    named = _episode(_forward(4242))
    assert support_holder(_outside(), named) == SupportHolder.source("4242", claimed=True)
    assert support_holder(_outside(), _episode(_forward(None))) == SupportHolder.unknown()
    # ADR-0351 §7:1: the input as a whole is held by its one party, and by unknown where
    # it carries several, as a note beside a forward does.
    beside = _episode(RecordedInputMessage(text="Who is she?", sent_at=AT), _forward(4242))
    assert support_holder(_outside(None), beside) == SupportHolder.unknown()
    assert support_holder(_outside(None), named) == SupportHolder.source("4242", claimed=True)


def test_a_gone_episode_leaves_the_origin_alone_to_decide() -> None:
    """§13:2: the owner for their message, and unknown for an outside part."""
    assert support_holder(said_support(), None) == _OWNER
    assert support_holder(_outside(), None) == SupportHolder.unknown()
    details = Attestation(reported_by="staff-page", reported_at=AT)
    assert support_holder(sourced_support(details), None) == SupportHolder.unknown()


def test_a_claimed_source_is_never_the_same_holder_as_an_established_one() -> None:
    """§2:7: whatever identifier either carries."""
    claimed = SupportHolder.source("42", claimed=True)
    established = SupportHolder.source("42", claimed=False)
    assert not claimed.same_as(established)
    assert claimed.same_as(SupportHolder.source("42", claimed=True))


def test_two_parts_under_one_identifier_are_one_holder_and_unknown_is_never_one() -> None:
    """§2:6, §2:3: a connection is enough; unknown and the assistant match nothing."""
    assert SupportHolder.person("sam").same_as(SupportHolder.person("sam"))
    assert not SupportHolder.person("sam").same_as(SupportHolder.person("tom"))
    assert not SupportHolder.unknown().same_as(SupportHolder.unknown())
    statement = SupportHolder.statement(StatementPart.ROUND_MESSAGE)
    assert not statement.same_as(statement)
    assert not _OWNER.same_as(None)


def test_a_holder_carries_exactly_the_fields_its_kind_names() -> None:
    """§2:3: four kinds, each with its own fields."""
    with pytest.raises(ValidationError):
        SupportHolder(kind=HolderKind.PERSON)
    with pytest.raises(ValidationError):
        SupportHolder(kind=HolderKind.OUTSIDE_SOURCE, identifier="x")
    with pytest.raises(ValidationError):
        SupportHolder(kind=HolderKind.UNKNOWN, identifier="x")
    with pytest.raises(ValidationError):
        SupportHolder(kind=HolderKind.ASSISTANT_STATEMENT)


def test_a_support_refuses_a_holder_its_origin_does_not_admit() -> None:
    """§2's table on the record: a user message is a person's, never a source's."""
    with pytest.raises(ValidationError, match="not held by"):
        MemorySupport.model_validate(
            said_support().model_dump() | {"holder": SupportHolder.unknown()}
        )
    with pytest.raises(ValidationError, match="names the part"):
        MemorySupport.model_validate(
            message_support().model_dump()
            | {"holder": SupportHolder.statement(StatementPart.REMEMBER_CALL)}
        )


def test_the_writer_keeps_a_producer_named_person_and_refuses_another_holder() -> None:
    """§2:2: a person the channel established is the producer's to name; nothing else is."""
    sam = said_support().model_copy(update={"holder": SupportHolder.person("sam")})
    assert stamped_support(sam, None).holder == SupportHolder.person("sam")
    assert stamped_support(said_support(), None).holder == _OWNER
    page = sourced_support(Attestation(reported_by="staff-page", reported_at=AT))
    forged = page.model_copy(update={"holder": SupportHolder.source("other", claimed=False)})
    with pytest.raises(ValueError, match="does not give it"):
        stamped_support(forged, _episode())


@pytest.mark.parametrize("message", [None, 0])
@pytest.mark.parametrize(
    "parties", [ASSISTANTS_WORDS, (*ASSISTANTS_WORDS, SupportHolder.unknown())]
)
def test_no_support_points_at_an_input_that_carries_the_assistants_statement(
    message: int | None, parties: tuple[SupportHolder, ...]
) -> None:
    """ADR-0351 §7:3: a scheduled task's instruction, a marked task's too, backs nothing.

    The stamp both writers use refuses it, whatever origin the producer gave it; a support
    of such an episode points at another part of it, such as a round's message.
    """
    scheduled = _episode(parties=parties)
    for origin in (SupportOrigin.USER_MESSAGE, SupportOrigin.OUTSIDE_INPUT):
        pointing = _outside(message) if origin is SupportOrigin.OUTSIDE_INPUT else said_support()
        pointing = pointing.model_copy(
            update={"points_at": InputPart(episode="activation:held", message=message)}
        )
        with pytest.raises(ValueError, match="include the assistant's statement"):
            stamped_support(pointing, scheduled)
    assert stamped_support(message_support(), scheduled).holder is not None


# --- the owner writes labels alone (§7:8) -----------------------------------------------


def test_the_owner_writes_a_label_and_nothing_else() -> None:
    """§7:8: ADR-0328 §5:9's closed set gains ``owner``, for label writes alone."""
    label = SituationLabel(text="when travelling", added_at=AT, added_by=MemoryWriterName.OWNER)
    assert label.added_by is MemoryWriterName.OWNER
    with pytest.raises(ValidationError, match="labels and nothing else"):
        MemorySupport.model_validate(said_support().model_dump() | {"added_by": "owner"})
    with pytest.raises(ValidationError, match="labels and nothing else"):
        MemoryOperation(
            kind=MemoryOperationKind.CREATE,
            cites=said_support().points_at,
            at=AT,
            by=MemoryWriterName.OWNER,
        )


# --- the memory's new fields (§7-§9) -----------------------------------------------------


def test_marks_and_people_are_sets_in_one_order() -> None:
    """§8:1, §9:1: a set of marks, and each field a set of names, given in any order."""
    held = memory(
        "m",
        "c",
        marks=(MemoryMark.OCCASION, MemoryMark.ASSISTANT_STATEMENT, MemoryMark.OCCASION),
        subjects=("Tom", "Ana", "Tom"),
    )
    assert held.marks == (MemoryMark.ASSISTANT_STATEMENT, MemoryMark.OCCASION)
    assert held.subjects == ("Ana", "Tom")


def test_a_memory_carries_one_label_per_wording_and_no_retired_field() -> None:
    """§7:1, §10:1: labels are distinct, and ``topics`` and ``about_person`` are refused."""
    label = SituationLabel(text="at work", added_at=AT, added_by=MemoryWriterName.OBSERVER)
    with pytest.raises(ValidationError, match="one label per wording"):
        memory("m", "c", labels=(label, label))
    with pytest.raises(ValidationError):
        memory("m", "c", topics=("work",))
    with pytest.raises(ValidationError):
        memory("m", "c", about_person="Ana")
    minted = SemanticMemory(
        id="s",
        content="c",
        fact="c",
        about_person="Ana",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=AT),
    )
    assert minted.about_person == "Ana"


def test_a_name_must_be_given_by_a_part_the_owner_aside() -> None:
    """§9:3, §9:4: each name occurs in a part's text; the owner's identifier needs none."""
    episode = EpisodicMemory(
        id="activation:held",
        content="My sister Ana moved to Lisbon.",
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )
    named = memory(
        "m", "Ana is the user's sister", subjects=("Ana", "Bob"), involved=(OWNER_PERSON_ID,)
    )
    assert names_not_given(named, {episode.id: episode}) == ("Bob",)
    assert names_not_given(memory("m", "c"), {}) == ()


def test_the_person_filter_reads_subjects_and_involved_exactly() -> None:
    """§9:6, §9:3: as carried, ``subjects`` alone where asked, and no episode passes."""
    held = memory("m", "c", subjects=("Ana",), involved=("Tom",))
    assert names_person(held, "Ana")
    assert names_person(held, "Tom")
    assert not names_person(held, "Tom", as_subject=True)
    assert not names_person(held, "ana")
    assert names_person(held, None)
    episode = EpisodicMemory(
        id="e",
        content="Ana",
        occurred_at=AT,
        about_person="Ana",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )
    assert not names_person(episode, "Ana")


def test_holders_partial_supporters_and_against_are_computed_from_the_supports() -> None:
    """§2:10: holders back it as worded; a partial supporter is never shown holding it."""
    sam = SupportHolder.person("sam")
    held = memory(
        "m",
        "Ana lives in Lisbon",
        said_support("activation:a").model_copy(update={"holder": _OWNER}),
        said_support("activation:b").model_copy(update={"holder": sam, "backs_as_worded": False}),
        said_support("activation:c", direction=SupportDirection.AGAINST).model_copy(
            update={"holder": SupportHolder.person("tom")}
        ),
    )
    assert held.holders == (_OWNER,)
    assert held.partial_supporters == (sam,)
    assert held.against_holders == (SupportHolder.person("tom"),)
    assert held.held_by(_OWNER)
    assert not held.held_by(sam)


# --- the placement's shape (§4:1) --------------------------------------------------------


def test_a_relation_but_independent_carries_a_note() -> None:
    """§4:1: a note in words on how the two relate, for every relation but ``independent``."""
    PlacedPair(memory="m", revision=1, relation=PlacedRelation.INDEPENDENT)
    with pytest.raises(ValidationError, match="says in words"):
        PlacedPair(memory="m", revision=1, relation=PlacedRelation.UNCLEAR)


def test_a_placement_names_each_memory_once_and_answers_one_it_names() -> None:
    """§4:1: one relation per stored memory, and at most one question on one of them."""
    pair = PlacedPair(memory="m", revision=1, relation=PlacedRelation.SUPPORTS, note="n")
    with pytest.raises(ValidationError, match="each stored memory once"):
        MemoryPlacement(pairs=(pair, pair))
    with pytest.raises(ValidationError, match="on a memory it names"):
        MemoryPlacement(pairs=(pair,), answers=PlacedAnswer(memory="other", question="q"))


def test_a_placed_proposal_names_other_memories_and_carries_no_retiring() -> None:
    """§4:1, §5: the placement names stored memories, and its relations retire."""
    proposed = memory("m", "c")
    own = PlacedPair(memory="m", revision=1, relation=PlacedRelation.RESTATES, note="n")
    with pytest.raises(ValidationError, match="other than the one proposed"):
        MemoryUpdateProposal(
            proposed=proposed, rationale="r", placement=MemoryPlacement(pairs=(own,))
        )


def test_neither_holders_nor_labels_enter_the_fingerprint() -> None:
    """ADR-0328 §11:11 with ADR-0345: a holder is derived from its part, a label is filing."""
    plain = MemoryUpdateProposal(proposed=memory("m", "c"), rationale="r")
    held = MemoryUpdateProposal(
        proposed=memory("m", "c", said_support().model_copy(update={"holder": _OWNER})),
        rationale="r",
    )
    labelled = MemoryUpdateProposal(
        proposed=memory(
            "m",
            "c",
            labels=(SituationLabel(text="x", added_at=AT, added_by=MemoryWriterName.OBSERVER),),
        ),
        rationale="r",
    )
    assert plain.proposal_fingerprint == held.proposal_fingerprint == labelled.proposal_fingerprint
    subject = MemoryUpdateProposal(proposed=memory("m", "c", subjects=("Ana",)), rationale="r")
    assert subject.proposal_fingerprint != plain.proposal_fingerprint


def test_label_bounds_are_positive_and_the_distance_a_cosine_one() -> None:
    """§7:3, §7:5's numbers, as the composition root states them."""
    LabelBounds(max_labels=1, max_chars=1, min_distance=0.0)
    with pytest.raises(ValidationError):
        LabelBounds(max_labels=0, max_chars=1, min_distance=0.1)
    with pytest.raises(ValidationError):
        LabelBounds(max_labels=1, max_chars=1, min_distance=2.5)


def test_a_remember_call_gives_no_name() -> None:
    """§9:3: which call a remember call is lives on its effect record, so none is read."""
    episode = EpisodicMemory(
        id="activation:held",
        content="",
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )
    named = memory("m", "Ada likes tea", remembered_support(), subjects=("Ada",))
    assert names_not_given(named, {episode.id: episode}) == ("Ada",)
