"""ADR-0281's recall stage: what it searches, keeps, labels and records (§3 to §6)."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    UNDERSTANDING_REFERENT_EXCERPT_CHARS,
    ActivationUnderstanding,
    Attestation,
    BeliefBand,
    ChannelContext,
    ChannelIdentity,
    EpisodeProcessingRecord,
    EpisodeResponseKind,
    EpisodicMemory,
    MemoryKind,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    NewConversation,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecallCue,
    RecallOutcome,
    RecallProvenance,
    RecordedChannelTrigger,
    RecordedResumeTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    SemanticMemory,
    SpokenAudioFormat,
    SpokenReply,
    UnderstandingGround,
    UnderstandingOmission,
    UnderstandingProducer,
    WholeTextReply,
)
from ai_assistant.orchestration.disclosure import (
    BoundedAudienceSupply,
    UnboundedAudienceSupply,
)
from ai_assistant.orchestration.recall import RecallStage
from ai_assistant.testing import FakeMemoryStore
from ai_assistant.testing.activation import ended_pass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryRecord, MemorySearchResult, RecordedActivationTrigger
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.recall import Recalled

AT: Final = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
CONVERSATION: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")
EVENTS: Final = ChannelIdentity(channel_type="informational_event", instance_id="parks")
BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())
CUE: Final = "dentist appointment"
BUDGET: Final = timedelta(seconds=2)


def _provenance(source: MemorySource = MemorySource.USER_ASSERTED) -> Provenance:
    attestation = (
        Attestation(reported_by="calendar", reported_at=AT)
        if source is MemorySource.EXTERNAL
        else None
    )
    confidence = 1.0 if source is MemorySource.USER_ASSERTED else 0.9
    return Provenance(
        source=source, confidence=confidence, last_updated=AT, attestation=attestation
    )


def _fact(  # noqa: PLR0913 — one knob per field a case varies
    memory_id: str,
    content: str = "The dentist appointment is on Friday.",
    *,
    source: MemorySource = MemorySource.USER_ASSERTED,
    fact: str | None = None,
    placement: Placement | None = None,
    about: str | None = None,
) -> SemanticMemory:
    return SemanticMemory(
        id=memory_id,
        content=content,
        fact=content if fact is None else fact,
        provenance=_provenance(source),
        placement=Placement() if placement is None else placement,
        about_person=about,
    )


def _processing(
    trigger: RecordedActivationTrigger,
    *,
    understanding: tuple[ActivationUnderstanding, ...] = (),
    failed: bool = False,
) -> EpisodeProcessingRecord:
    resumed = isinstance(trigger, RecordedResumeTrigger)
    return EpisodeProcessingRecord(
        activation_id="4f1d7c0e-1a2b-4c3d-8e9f-0a1b2c3d4e5f",
        started_at=AT,
        ended_at=AT,
        trigger=trigger,
        status=ProcessingStatus.FAILED if failed else ProcessingStatus.COMPLETED,
        reason=ProcessingReason.TRANSCRIPTION_FAILED if failed else ProcessingReason.RETURNED,
        response_kind=EpisodeResponseKind.NONE,
        model_eligible=not failed,
        understanding=understanding,
        understanding_omitted=None if understanding else UnderstandingOmission.NOT_REACHED,
        stages=() if resumed else ended_pass(AT),
    )


def _text_trigger(text: str, channel: ChannelIdentity = CONVERSATION) -> RecordedChannelTrigger:
    event = channel.channel_type == "informational_event"
    return RecordedChannelTrigger(
        target=channel,
        channel=channel,
        payload=RecordedTextInput(text=text),
        context=ChannelContext(),
        conversation=None,
        reply=None if event else WholeTextReply(),
    )


def _understood(meaning: str) -> ActivationUnderstanding:
    return ActivationUnderstanding(
        version=1,
        recorded_at=AT,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning=meaning,
        meaning_ground=UnderstandingGround.STATED,
    )


def _episode(
    episode_id: str,
    content: str = "The dentist appointment was booked.",
    *,
    processing: EpisodeProcessingRecord | None = None,
    placement: Placement | None = None,
) -> EpisodicMemory:
    return EpisodicMemory(
        id=episode_id,
        content=content,
        occurred_at=AT,
        provenance=_provenance(MemorySource.OBSERVED),
        placement=Placement() if placement is None else placement,
        processing_record=processing,
    )


@dataclass(frozen=True)
class _Search:
    query: str
    limit: int
    kinds: tuple[MemoryKind, ...] | None
    bands: tuple[BeliefBand, ...] | None
    eligible: bool | None


class _Recording(FakeMemoryStore):
    """The canonical fake, recording each search's arguments."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.searches: list[_Search] = []

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
        episode_model_eligible: bool | None = None,
        **axes: Any,
    ) -> MemorySearchResult:
        self.searches.append(
            _Search(
                query,
                limit,
                None if kinds is None else tuple(kinds),
                None if bands is None else tuple(bands),
                episode_model_eligible,
            )
        )
        return await super().search(
            query,
            limit=limit,
            kinds=kinds,
            bands=bands,
            episode_model_eligible=episode_model_eligible,
            **axes,
        )


class _Unscored(FakeMemoryStore):
    """A store returning its matches with no score."""

    async def search(self, query: str, **kwargs: Any) -> MemorySearchResult:
        found = await super().search(query, **kwargs)
        return found.model_copy(
            update={"records": tuple(r.model_copy(update={"score": None}) for r in found.records)}
        )


class _Slow(FakeMemoryStore):
    """A store whose search outlasts any budget a case sets."""

    async def search(self, query: str, **kwargs: Any) -> MemorySearchResult:
        await asyncio.sleep(10)
        return await super().search(query, **kwargs)


class _OwnTimeout(FakeMemoryStore):
    """A store raising a ``TimeoutError`` of its own, not recall's budget."""

    async def search(self, query: str, **kwargs: Any) -> MemorySearchResult:
        msg = "the store's own timeout"
        raise TimeoutError(msg)


async def _seed[S: FakeMemoryStore](memory: S, *records: MemoryRecord) -> S:
    await memory.write_atomic(
        [MemoryWrite(record=record, mode=MemoryWriteMode.INSERT_IF_ABSENT) for record in records]
    )
    return memory


async def _store(*records: MemoryRecord) -> _Recording:
    return await _seed(_Recording(now=lambda: AT), *records)


def _stage(
    memory: FakeMemoryStore,
    *,
    threshold: float = 0.5,
    limit: int = 3,
    budget: timedelta = BUDGET,
) -> RecallStage:
    return RecallStage(memory=memory, threshold=threshold, limit=limit, budget=budget)


async def _recall(
    stage: RecallStage,
    text: str = CUE,
    *,
    audience: TurnSupply = BOUNDED,
    deadline: float = math.inf,
) -> Recalled:
    return await stage.recall(text, audience=audience, deadline=deadline)


def _ids(recalled: Recalled) -> list[str]:
    assert [item.id for item in recalled.result.items] == [r.id for r in recalled.records]
    return [record.id for record in recalled.records]


# --- §3: what it searches ------------------------------------------------------------


async def test_it_searches_each_band_in_precedence_order_with_the_input_alone() -> None:
    memory = await _store()
    await _recall(_stage(memory), "the dentist, as before")
    both = (MemoryKind.EPISODIC, MemoryKind.SEMANTIC)
    assert memory.searches == [
        _Search("the dentist, as before", 3, both, (band,), None)
        for band in (BeliefBand.ASSERTED, BeliefBand.ATTESTED, BeliefBand.DERIVED)
    ]


async def test_an_assertion_is_kept_ahead_of_higher_scoring_inferences() -> None:
    inferred = [
        _fact(f"inferred-{n}", "dentist appointment", source=MemorySource.INFERRED)
        for n in range(3)
    ]
    asserted = _fact("asserted", "the dentist is Dr Rao")
    recalled = await _recall(_stage(await _store(*inferred, asserted)))
    assert _ids(recalled) == ["asserted", "inferred-0", "inferred-1"]


async def test_a_record_below_the_threshold_is_not_kept() -> None:
    half = _fact("half", "the dentist is Dr Rao")
    whole = _fact("whole", "dentist appointment on Friday")
    recalled = await _recall(_stage(await _store(half, whole), threshold=0.75))
    assert _ids(recalled) == ["whole"]


async def test_it_keeps_at_most_the_limit_and_stops_searching_once_filled() -> None:
    memory = await _store(*(_fact(f"m{n}") for n in range(5)))
    recalled = await _recall(_stage(memory, limit=2))
    assert len(recalled.records) == 2
    assert [search.bands for search in memory.searches] == [(BeliefBand.ASSERTED,)]


async def test_a_record_returned_with_no_score_is_not_kept() -> None:
    memory = await _seed(_Unscored(now=lambda: AT), _fact("m"))
    recalled = await _recall(_stage(memory))
    assert recalled.result.outcome is RecallOutcome.NOTHING_FOUND


async def test_it_requests_no_eligibility_so_an_ineligible_episode_is_reached() -> None:
    ineligible = _episode(
        "event",
        processing=_processing(
            _text_trigger("parks", EVENTS), understanding=(_understood("closed"),)
        ).model_copy(update={"model_eligible": False}),
    )
    recalled = await _recall(_stage(await _store(ineligible)))
    assert _ids(recalled) == ["event"]


# --- §4: audience ----------------------------------------------------------------


async def test_the_audience_predicate_filters_before_anything_is_kept() -> None:
    owner = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=AT)
    records = (
        _fact("owner-only", placement=owner),
        _fact("about-someone", about="Sam"),
        _fact("attested", source=MemorySource.EXTERNAL),
        _fact("speakable"),
    )
    spoken = await _recall(_stage(await _store(*records), limit=4), audience=UNBOUNDED)
    assert _ids(spoken) == ["speakable"]
    assert UNBOUNDED.withheld is False
    bounded = await _recall(_stage(await _store(*records), limit=4))
    assert sorted(_ids(bounded)) == ["about-someone", "attested", "owner-only", "speakable"]


async def test_an_unbounded_audience_searches_and_keeps_no_episode() -> None:
    """Keyed on the posture: the same episode, admitted by the predicate, is kept only
    on a bounded pass — recall is told no operation, modality or channel at all."""
    episode = _episode("episode")
    memory = await _store(episode)
    spoken = await _recall(_stage(memory), audience=UNBOUNDED)
    assert spoken.result.outcome is RecallOutcome.NOTHING_FOUND
    assert {search.kinds for search in memory.searches} == {(MemoryKind.SEMANTIC,)}
    bounded = await _recall(_stage(await _store(episode)))
    assert _ids(bounded) == ["episode"]


# --- §4, §6: provenance and structured origin ---------------------------------------------


async def test_each_kept_record_carries_its_provenance_and_structured_origin() -> None:
    records = (
        _fact("said"),
        _fact("reported", source=MemorySource.EXTERNAL),
        _episode("exchange", processing=_processing(_text_trigger("the dentist appointment"))),
        _episode("event", processing=_processing(_text_trigger("parks", EVENTS))),
    )
    recalled = await _recall(_stage(await _store(*records), limit=4))
    items = {item.id: item for item in recalled.result.items}
    assert {key: item.provenance for key, item in items.items()} == {
        "said": RecallProvenance.USER,
        "reported": RecallProvenance.OUTSIDE,
        "exchange": RecallProvenance.USER,
        "event": RecallProvenance.OUTSIDE,
    }
    reported = items["reported"]
    assert (reported.standing, reported.rests_on_recorded_external_content) == (
        BeliefBand.ATTESTED,
        True,
    )
    assert reported.attestation == Attestation(reported_by="calendar", reported_at=AT)
    said = items["said"]
    assert (said.kind, said.standing, said.rests_on_recorded_external_content) == (
        MemoryKind.SEMANTIC,
        BeliefBand.ASSERTED,
        False,
    )
    assert said.attestation is None
    # An informational event's episode is `outside` while its origin is not external.
    event = items["event"]
    assert (event.kind, event.standing, event.rests_on_recorded_external_content) == (
        MemoryKind.EPISODIC,
        BeliefBand.DERIVED,
        False,
    )
    assert all(item.found_by == (RecallCue.ACTIVATION_INPUT,) for item in items.values())
    assert recalled.result.cues == (RecallCue.ACTIVATION_INPUT,)


# --- §6: excerpts ------------------------------------------------------------------------


async def test_an_outside_episodes_excerpt_never_carries_its_raw_input() -> None:
    understood = _episode(
        "understood",
        processing=_processing(
            _text_trigger("RAW-SENTINEL", EVENTS),
            understanding=(_understood("An old reading."), _understood("The park closed.")),
        ),
    )
    bare = _episode("bare", processing=_processing(_text_trigger("RAW-SENTINEL", EVENTS)))
    recalled = await _recall(_stage(await _store(understood, bare)))
    excerpts = {item.id: item.excerpt for item in recalled.result.items}
    assert excerpts == {
        "understood": "The park closed.",
        "bare": "a report received on informational_event:parks",
    }


async def test_another_episodes_excerpt_is_its_input_text_or_its_content() -> None:
    speech = RecordedChannelTrigger(
        target=NewConversation(),
        channel=None,
        payload=RecordedSpeechInput(media_type=SpokenAudioFormat.WEBM_OPUS, transcript=None),
        context=ChannelContext(),
        conversation=None,
        reply=SpokenReply(plays=(SpokenAudioFormat.WEBM_OPUS,)),
    )
    records = (
        _episode("typed", processing=_processing(_text_trigger("Book the dentist."))),
        _episode(
            "resumed", processing=_processing(RecordedResumeTrigger(channel=None, approved=True))
        ),
        _episode("untranscribed", processing=_processing(speech, failed=True)),
        _episode("unprocessed"),
    )
    recalled = await _recall(_stage(await _store(*records), limit=4))
    content = "The dentist appointment was booked."
    assert {item.id: item.excerpt for item in recalled.result.items} == {
        "typed": "Book the dentist.",
        "resumed": content,
        "untranscribed": content,
        "unprocessed": content,
    }


async def test_a_semantic_excerpt_is_its_fact_cut_to_the_referent_bound() -> None:
    long = "dentist appointment " + "x" * UNDERSTANDING_REFERENT_EXCERPT_CHARS
    recalled = await _recall(_stage(await _store(_fact("long", "dentist appointment", fact=long))))
    assert recalled.result.items[0].excerpt == long[:UNDERSTANDING_REFERENT_EXCERPT_CHARS]


# --- §5, §6: outcomes, failure and the two deadlines -----------------------------------


async def test_a_found_recall_carries_its_items_and_records() -> None:
    recalled = await _recall(_stage(await _store(_fact("m"))))
    assert recalled.result.outcome is RecallOutcome.FOUND
    assert recalled.error is None


async def test_nothing_above_the_threshold_is_nothing_found() -> None:
    recalled = await _recall(_stage(await _store(_fact("m"))), "yes")
    assert (recalled.result.outcome, recalled.result.items, recalled.records) == (
        RecallOutcome.NOTHING_FOUND,
        (),
        (),
    )


async def test_a_store_failure_is_a_failed_decision_returned_not_raised() -> None:
    memory = await _seed(FakeMemoryStore(now=lambda: AT, failure="down"), _fact("m"))
    recalled = await _recall(_stage(memory))
    assert (recalled.result.outcome, recalled.records) == (RecallOutcome.FAILED, ())
    assert isinstance(recalled.error, MemoryStoreError)


async def test_a_spent_budget_is_a_timed_out_decision_returned_not_raised() -> None:
    stage = _stage(await _seed(_Slow(now=lambda: AT)), budget=timedelta(milliseconds=10))
    recalled = await _recall(stage)
    assert (recalled.result.outcome, recalled.records) == (RecallOutcome.TIMED_OUT, ())
    assert isinstance(recalled.error, TimeoutError)


async def test_the_pass_deadline_caps_the_budget() -> None:
    stage = _stage(await _seed(_Slow(now=lambda: AT)))
    started = asyncio.get_running_loop().time()
    recalled = await _recall(stage, deadline=started + 0.01)
    assert recalled.result.outcome is RecallOutcome.TIMED_OUT
    assert asyncio.get_running_loop().time() - started < BUDGET.total_seconds()


async def test_a_passed_deadline_raises_and_searches_nothing() -> None:
    memory = await _store(_fact("m"))
    with pytest.raises(TimeoutError, match="before recall"):
        await _recall(_stage(memory), deadline=asyncio.get_running_loop().time())
    assert memory.searches == []


async def test_a_timeout_that_is_not_the_budgets_escapes() -> None:
    with pytest.raises(TimeoutError, match="the store's own timeout"):
        await _recall(_stage(_OwnTimeout(now=lambda: AT)))


# --- construction ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("limit", "budget"),
    [(0, BUDGET), (17, BUDGET), (3, timedelta(0))],
    ids=["no-limit", "above-the-ceiling", "no-budget"],
)
def test_the_stage_refuses_a_limit_or_budget_outside_its_bounds(
    limit: int, budget: timedelta
) -> None:
    with pytest.raises(ValueError, match="ADR-0281"):
        RecallStage(memory=FakeMemoryStore(), threshold=0.5, limit=limit, budget=budget)
