"""The activation-understanding types of ADR-0276 §2 and §7, as ADR-0353 §9 and §10 reshape them."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

import ai_assistant.core.types as core_types
from ai_assistant.core.errors import AssistantError, UnderstandingError
from ai_assistant.core.types import (
    UNDERSTANDING_REFERENT_EXCERPT_CHARS,
    ActivationUnderstanding,
    ChannelContext,
    EpisodeProcessingRecord,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    ProposedActivationUnderstanding,
    RecordedChannelTrigger,
    RecordedTextInput,
    StoryMember,
    StoryMemberKind,
    UnclearPoint,
    UnderstandingOmission,
    UnderstandingProducer,
    UnderstandingReferent,
    WholeTextReply,
)
from ai_assistant.testing.activation import ended_pass
from ai_assistant.testing.parties import (
    OWNERS_WORDS,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_INPUT = UnderstandingReferent(kind="input", excerpt="book the dentist")
_EPISODE = UnderstandingReferent(
    kind="episode", id="episode-1", source="conversation", excerpt="the dentist is on Elm"
)


def _understanding(**overrides: object) -> ActivationUnderstanding:
    fields: dict[str, object] = {
        "version": 1,
        "recorded_at": _NOW,
        "producer": UnderstandingProducer.INTERPRETATION,
        "meaning": "book the dentist appointment",
    }
    fields.update(overrides)
    return ActivationUnderstanding.model_validate(fields)


def _record(**overrides: object) -> EpisodeProcessingRecord:
    fields: dict[str, object] = {
        "activation_id": "activation",
        "started_at": _NOW,
        "ended_at": _NOW,
        "trigger": RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="book the dentist"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            parties=OWNERS_WORDS,
        ),
        "status": ProcessingStatus.COMPLETED,
        "reason": ProcessingReason.RETURNED,
        "understanding_omitted": UnderstandingOmission.NOT_REACHED,
        "stages": ended_pass(_NOW),
    }
    fields.update(overrides)
    return EpisodeProcessingRecord.model_validate(fields)


# --- §2: two closed enumerations ---------------------------------------------


def test_the_two_enumerations_carry_exactly_the_members_the_adr_lists() -> None:
    """ADR-0276 §2's tables are complete; a member is valued by its lower-cased name."""
    assert {member.value for member in UnderstandingOmission} == {
        "no_text",
        "failed",
        "not_reached",
    }
    assert {member.value for member in UnderstandingProducer} == {"interpretation"}
    for enum in (UnderstandingOmission, UnderstandingProducer):
        assert all(member.value == member.name.lower() for member in enum)


@pytest.mark.parametrize(
    "name",
    [
        "ProposedReference",
        "ProposedRelationship",
        "ProposedAnswer",
        "UnderstandingReference",
        "UnderstandingRelationship",
        "UnresolvedMatter",
        "UnderstandingGround",
    ],
)
def test_the_seven_retired_types_leave_core(name: str) -> None:
    """ADR-0353 §9:9: removed from ``core/types.py``."""
    assert not hasattr(core_types, name)


def test_processing_reason_gains_understanding_failed() -> None:
    """§6: the reason the classifier will assign to a pass ``UnderstandingError`` ended."""
    assert ProcessingReason.UNDERSTANDING_FAILED.value == "understanding_failed"
    assert ProcessingReason("understanding_failed") is ProcessingReason.UNDERSTANDING_FAILED


# --- ADR-0353 §11:2: no answer pointer -------------------------------------------


def test_neither_the_proposal_nor_the_record_carries_an_answer_pointer() -> None:
    """§9:1, §9:5: ``answers`` is no field of either; a stored one is refused as extra."""
    assert "answers" not in ProposedActivationUnderstanding.model_fields
    assert "answers" not in ActivationUnderstanding.model_fields
    with pytest.raises(ValidationError):
        ProposedActivationUnderstanding.model_validate_json(
            '{"understanding": "yes", "answers": [{"question": "Q1"}]}'
        )
    with pytest.raises(ValidationError):
        _understanding(answers=[{"activation_id": "a-1", "round": "r-1"}])


def test_the_answer_pointers_type_leaves_core_with_the_rules_that_read_it() -> None:
    """ADR-0361 §8:6, §11: ``AnsweredQuestion`` was ADR-0353 §9:9's to keep only while
    authorizing's approval rules held it; they retire, and no stored record holds one."""
    assert not hasattr(core_types, "AnsweredQuestion")


def test_understanding_error_is_an_assistant_error_with_the_standard_constructor() -> None:
    """§6: a new ``AssistantError`` subclass carrying a message and no content field."""
    error = UnderstandingError("second output did not parse")
    assert isinstance(error, AssistantError)
    assert str(error) == "second output did not parse"
    assert not {name for name in vars(error) if name != "details_elided"}


# --- ADR-0353 §9:2: the proposal is the reply ------------------------------------


def test_a_proposal_is_the_replys_six_keys_and_no_identity() -> None:
    """§9:2: the reply's own names, and no id, timestamp, version or producer."""
    proposal = ProposedActivationUnderstanding(
        understanding="Maren asks to compare the two quotes.",
        cites=("H1", "P2", "R1"),
        unclear=(UnclearPoint(gap="which currency", readings=("euros", "dollars")),),
        belongs_to=("S1",),
        meant_for=("R1",),
    )
    assert set(ProposedActivationUnderstanding.model_fields) == {
        "understanding",
        "cites",
        "unclear",
        "belongs_to",
        "meant_for",
        "relayed",
    }
    assert proposal.relayed is False
    for forbidden in ("version", "recorded_at", "producer", "id", "meaning_ground", "answers"):
        with pytest.raises(ValidationError):
            ProposedActivationUnderstanding.model_validate(
                {**proposal.model_dump(), forbidden: "x"}
            )


def test_every_field_but_the_understanding_may_be_empty() -> None:
    """§9:2: ``understanding`` is non-blank text, and each sequence may be empty."""
    proposal = ProposedActivationUnderstanding.model_validate_json('{"understanding": "hi"}')
    assert (
        proposal.cites,
        proposal.unclear,
        proposal.belongs_to,
        proposal.meant_for,
        proposal.relayed,
    ) == ((), (), (), (), False)
    for blank in ("", "   "):
        with pytest.raises(ValidationError):
            ProposedActivationUnderstanding(understanding=blank)
    with pytest.raises(ValidationError):
        ProposedActivationUnderstanding.model_validate_json('{"cites": []}')


def test_a_proposal_carries_its_labels_unjudged() -> None:
    """A label is the stage's to resolve or drop: one naming nothing, or named twice, or
    an ``R`` label in ``cites`` or ``belongs_to``, is no parse failure (§9:10-§9:12)."""
    proposal = ProposedActivationUnderstanding(
        understanding="x",
        cites=("not a label", "R1", "R1"),
        belongs_to=("R2", "M1"),
        meant_for=("H1",),
    )
    assert proposal.cites == ("not a label", "R1", "R1")
    assert proposal.belongs_to == ("R2", "M1")
    assert proposal.meant_for == ("H1",)


# --- ADR-0353 §9:3: an unclear point ----------------------------------------------------


def test_an_unclear_point_holds_a_gap_and_at_least_one_reading() -> None:
    """§9:3: frozen, ``extra="forbid"``, a non-blank gap, and one reading or more."""
    point = UnclearPoint(gap="which Friday", readings=("this Friday",))
    assert point.readings == ("this Friday",)
    assert point.model_config.get("frozen") is True
    with pytest.raises(ValidationError):
        UnclearPoint(gap="which Friday", readings=())
    with pytest.raises(ValidationError):
        UnclearPoint.model_validate({"gap": "which Friday"})
    with pytest.raises(ValidationError):
        UnclearPoint(gap="which Friday", readings=("this Friday", "  "))
    with pytest.raises(ValidationError):
        UnclearPoint(gap="", readings=("this Friday",))
    with pytest.raises(ValidationError):
        UnclearPoint.model_validate({"gap": "g", "readings": ["r"], "why": "w"})


def test_a_gap_with_no_reading_is_refused_in_the_proposal_and_the_record() -> None:
    """§9:3, §16:4: both ``unclear`` fields are sequences of the one type."""
    with pytest.raises(ValidationError):
        ProposedActivationUnderstanding.model_validate_json(
            '{"understanding": "x", "unclear": [{"gap": "which day", "readings": []}]}'
        )
    with pytest.raises(ValidationError):
        _understanding(unclear=[{"gap": "which day", "readings": []}])
    recorded = _understanding(unclear=(UnclearPoint(gap="which day", readings=("Fri", "Sat")),))
    assert recorded.unclear[0].readings == ("Fri", "Sat")


def test_a_recorded_understanding_carries_no_label_and_no_retired_field() -> None:
    """§9:4, §9:5: the record keeps its own names, gains ``unclear``, and loses the five."""
    assert set(ActivationUnderstanding.model_fields) == {
        "version",
        "recorded_at",
        "producer",
        "meaning",
        "meaning_referents",
        # ADR-0353 §9:4: the reply's unclear points, copied unchanged.
        "unclear",
        "grounding_dropped",
        # ADR-0300 §6:7: the matters it belongs to, resolved to story members.
        "story_links",
        # ADR-0349 §10:2: the running activations `meant_for` resolved to.
        "continues",
        # ADR-0351 §5:10: the relay mark this version records on the trigger's input.
        "relayed",
    }
    for retired in ("meaning_ground", "references", "relationships", "unresolved", "answers"):
        with pytest.raises(ValidationError):
            _understanding(**{retired: []})
    assert _understanding().unclear == ()


def test_continues_is_empty_by_default_and_names_activations() -> None:
    """ADR-0349 §10:2, ADR-0353 §10:4: labels in ``meant_for``, activation ids on the record.

    A record written before the field validates unchanged, and the proposal's labels are
    carried unjudged: a label resolving to no shown activation is the stage's to drop,
    and so is one named twice. The record names each activation once, in order.
    """
    assert _understanding().continues == ()
    assert _understanding(continues=("act-on-the-phone",)).continues == ("act-on-the-phone",)
    assert _understanding(continues=("act-2", "act-1")).continues == ("act-2", "act-1")
    with pytest.raises(ValidationError):
        _understanding(continues=("   ",))
    with pytest.raises(ValidationError, match="each activation it continues once"):
        _understanding(continues=("act-1", "act-1"))
    proposal = ProposedActivationUnderstanding(understanding="and Saturday", meant_for=("R1", "R2"))
    assert proposal.meant_for == ("R1", "R2")


def test_continues_is_a_sequence_on_the_wire() -> None:
    """ADR-0349 §10:2: one id or ``null``, as a build before it stored, is no longer read;
    the memory store's upgrade carries a stored one (§10:6)."""
    older = _understanding().model_dump(mode="json")
    for held in ("act-1", None):
        with pytest.raises(ValidationError):
            ActivationUnderstanding.model_validate(older | {"continues": held})
    assert ActivationUnderstanding.model_validate(older | {"continues": ["act-1"]}).continues == (
        "act-1",
    )


def test_story_links_default_to_none_and_name_each_member_once() -> None:
    """ADR-0300 §6:7, §12:1: empty by default, in proposal order, no member twice."""
    story = StoryMember(kind=StoryMemberKind.STORY, id="story:1")
    earlier = StoryMember(kind=StoryMemberKind.ACTIVATION, id="a-1")

    assert _understanding().story_links == ()
    assert _understanding(story_links=(earlier, story)).story_links == (earlier, story)
    with pytest.raises(ValidationError, match="at most once"):
        _understanding(story_links=(story, earlier, story))


def test_a_record_written_before_story_links_validates_unchanged() -> None:
    """ADR-0300 §12:1: the field defaults to empty, so an older record's JSON still reads."""
    older = _understanding().model_dump(mode="json")
    del older["story_links"]

    assert ActivationUnderstanding.model_validate(older).story_links == ()


def test_a_referent_may_name_a_running_activation() -> None:
    """ADR-0353 §10:1: ``running``, by the activation's episode id, its channel and its
    input in brief, and it round-trips on a version."""
    running = UnderstandingReferent(
        kind="running",
        id="activation:act-booking",
        source="conversation:chat-1",
        excerpt="book a table for 4 at Luigi's on Friday at 8",
    )
    recorded = _understanding(meaning_referents=(running,))
    assert ActivationUnderstanding.model_validate_json(recorded.model_dump_json()) == recorded


def test_referent_kinds_and_the_exactly_as_stored_episode_id() -> None:
    """§2: an episode ``id`` is carried exactly as stored, blank included."""
    assert UnderstandingReferent(kind="input", excerpt="").id is None
    item = UnderstandingReferent(kind="channel_item", id=None, source="email", excerpt="x")
    assert item.id is None
    blank = UnderstandingReferent(kind="episode", id="  ", source="conversation", excerpt="x")
    assert blank.id == "  "
    with pytest.raises(ValidationError):
        UnderstandingReferent(kind="record", excerpt="x")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        UnderstandingReferent(kind="episode", id="e", source="", excerpt="x")


def test_an_excerpt_is_bounded_at_two_hundred_and_forty_characters() -> None:
    """§2: a bounded prefix, at most 240 characters, and the bound is a type bound."""
    assert UNDERSTANDING_REFERENT_EXCERPT_CHARS == 240
    UnderstandingReferent(kind="input", excerpt="é" * 240)
    with pytest.raises(ValidationError):
        UnderstandingReferent(kind="input", excerpt="é" * 241)


@pytest.mark.parametrize(
    ("field", "value"),
    [("version", 0), ("version", 2**31), ("grounding_dropped", -1), ("grounding_dropped", 2**31)],
)
def test_version_and_dropped_count_ranges(field: str, value: int) -> None:
    """§2: ``version`` in ``[1, 2**31)`` and ``grounding_dropped`` in ``[0, 2**31)``."""
    with pytest.raises(ValidationError):
        _understanding(**{field: value})
    assert _understanding(version=2**31 - 1, grounding_dropped=2**31 - 1).version == 2**31 - 1


def test_recorded_understanding_round_trips_through_its_dump() -> None:
    """The shape crosses the wire by ``model_dump`` (protocol 58); it decodes to itself."""
    recorded = _understanding(
        meaning_referents=(_INPUT, _EPISODE),
        unclear=(UnclearPoint(gap="which day", readings=("Friday", "Saturday")),),
        grounding_dropped=2,
    )
    assert ActivationUnderstanding.model_validate(recorded.model_dump(mode="json")) == recorded
    assert recorded.model_config.get("frozen") is True


# --- §7: schema_version 2, three fields, exactly one of history and omission ----


def test_the_record_carries_three_understanding_fields_at_the_current_schema_version() -> None:
    """§7's three fields; the literal is ADR-0280 §7's ``3``, which superseded §7's ``2``."""
    record = _record()
    assert record.schema_version == 12
    assert record.understanding == ()
    assert record.understanding_omitted is UnderstandingOmission.NOT_REACHED
    assert record.understanding_elided == 0
    with pytest.raises(ValidationError):
        _record(schema_version=1)
    with pytest.raises(ValidationError):
        EpisodeProcessingRecord.model_validate({**record.model_dump(), "schema_version": 1})


def test_a_record_carries_exactly_one_of_its_understanding_and_an_omission() -> None:
    """§7: exactly one of a non-empty ``understanding`` and a non-``None`` omission value."""
    versions = (_understanding(), _understanding(version=2, meaning="revised"))
    with_versions = _record(understanding=versions, understanding_omitted=None)
    assert with_versions.understanding == versions
    with pytest.raises(ValidationError, match="either its understanding or why it has none"):
        _record(understanding=(), understanding_omitted=None)
    with pytest.raises(ValidationError, match="either its understanding or why it has none"):
        _record(understanding=versions, understanding_omitted=UnderstandingOmission.FAILED)
    for omission in UnderstandingOmission:
        assert _record(understanding_omitted=omission).understanding_omitted is omission


def test_the_elided_count_rides_a_non_empty_history() -> None:
    """§7: ``understanding_elided`` counts dropped versions; the type ties it to nothing."""
    record = _record(
        understanding=(_understanding(),), understanding_omitted=None, understanding_elided=3
    )
    assert record.understanding_elided == 3


@pytest.mark.parametrize("elided", [-1, 2**31])
def test_the_elided_count_is_bounded(elided: int) -> None:
    """§7: ``understanding_elided`` in ``[0, 2**31)``."""
    with pytest.raises(ValidationError):
        _record(understanding_elided=elided)


def test_a_record_with_understanding_round_trips_through_its_dump() -> None:
    """The record crosses the wire inside ``EpisodicMemory.processing_record`` (protocol 54, 59)."""
    record = _record(
        understanding=(_understanding(meaning_referents=(_INPUT,)),),
        understanding_omitted=None,
        understanding_elided=1,
    )
    assert EpisodeProcessingRecord.model_validate(record.model_dump(mode="json")) == record
    assert "understanding_omitted" in record.model_dump()


# --- ADR-0304 §8: a story is a referent -------------------------------------------

_STORY = UnderstandingReferent(
    kind="story", id="story:riverside", source="story", excerpt="Camping at Riverside, 12-14 June"
)


def test_a_referent_may_name_a_story() -> None:
    """§8: ``id`` the story's id, ``source`` the text ``story``, ``excerpt`` its first line."""
    assert (_STORY.kind, _STORY.id, _STORY.source) == ("story", "story:riverside", "story")
    # A withheld or empty summary renders no line, and the excerpt is then empty.
    withheld = UnderstandingReferent(kind="story", id="story:2", source="story", excerpt="")
    assert withheld.excerpt == ""
    # The excerpt is cut on ADR-0276 §2:5's rule, and the bound is the type's.
    with pytest.raises(ValidationError):
        UnderstandingReferent(
            kind="story",
            id="story:1",
            source="story",
            excerpt="é" * (UNDERSTANDING_REFERENT_EXCERPT_CHARS + 1),
        )


def test_a_reading_may_cite_a_story_alone() -> None:
    """§8: a story cited in ``cites`` resolves to its referent and links nothing."""
    recorded = _understanding(meaning_referents=(_STORY,))
    assert recorded.meaning_referents == (_STORY,)
    assert recorded.story_links == ()


def test_a_record_with_a_story_referent_round_trips_at_the_same_schema_version() -> None:
    """§8: the kind rides ``EpisodicMemory.processing_record`` and alters no schema_version."""
    record = _record(
        understanding=(_understanding(meaning_referents=(_INPUT, _STORY)),),
        understanding_omitted=None,
    )
    assert record.schema_version == 12
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record


def test_a_record_written_before_the_story_kind_validates_unchanged() -> None:
    """§8: a record of the four earlier kinds reads back exactly as it was written."""
    earlier = (
        _INPUT,
        _EPISODE,
        UnderstandingReferent(kind="channel_item", id=None, source="email", excerpt="x"),
        UnderstandingReferent(kind="memory", id="m-1", source="semantic memory", excerpt="y"),
    )
    written = _record(
        understanding=(_understanding(meaning_referents=earlier),), understanding_omitted=None
    ).model_dump(mode="json")
    assert EpisodeProcessingRecord.model_validate(written).model_dump(mode="json") == written
