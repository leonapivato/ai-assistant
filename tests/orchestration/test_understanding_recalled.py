"""ADR-0281 §7: the understanding stage reads what recall kept, as a third section."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.types import (
    UNDERSTANDING_REFERENT_EXCERPT_CHARS,
    ActivationRecall,
    Attestation,
    ChannelIdentity,
    EpisodicMemory,
    MemoryKind,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Provenance,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    SemanticMemory,
    UnderstandingGround,
    UnderstandingReferent,
    band_of,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.understanding import (
    ConversationWindow,
    RecentEpisodes,
    UnderstandingStage,
)
from ai_assistant.testing import FakeMemoryStore, FakeModelProvider

if TYPE_CHECKING:
    from ai_assistant.core.types import ActivationUnderstanding, MemoryRecord
    from ai_assistant.orchestration.recall import RecalledRecord

AT: Final = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
EARLIER: Final = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
CONVERSATION: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")
BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
CUES: Final = (RecallCue.ACTIVATION_INPUT,)


def _proposal(**fields: Any) -> str:
    return json.dumps({"meaning": "They mean the dentist.", "meaning_ground": "stated"} | fields)


def _fact(
    memory_id: str,
    fact: str = "The dentist is Dr Rao.",
    source: MemorySource = MemorySource.INFERRED,
) -> SemanticMemory:
    confidence = 1.0 if source is MemorySource.USER_ASSERTED else 0.9
    return SemanticMemory(
        id=memory_id,
        content=fact,
        fact=fact,
        provenance=Provenance(source=source, confidence=confidence, last_updated=EARLIER),
    )


def _episode(episode_id: str, at: datetime = EARLIER) -> EpisodicMemory:
    return EpisodicMemory(
        id=episode_id,
        content="The user asked to book the dentist.",
        occurred_at=at,
        outcome="Booked for Friday.",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=at),
    )


#: What recall decided, and the records of it the understanding phase fetched.
type _Recall = tuple[ActivationRecall, tuple[RecalledRecord, ...]]


def _found(*records: RecalledRecord) -> _Recall:
    items = tuple(
        RecalledItem(
            kind=MemoryKind(record.kind),
            id=record.id,
            excerpt=record.content[:200],
            provenance=RecallProvenance.USER,
            standing=band_of(record.provenance.source),
            rests_on_recorded_external_content=False,
            found_by=CUES,
        )
        for record in records
    )
    return ActivationRecall(outcome=RecallOutcome.FOUND, cues=CUES, items=items), records


def _decided(outcome: RecallOutcome) -> _Recall:
    return ActivationRecall(outcome=outcome, cues=CUES), ()


@dataclass(frozen=True)
class _Staged:
    """The stage, and the episode window the windows stage would hand it over ``records``."""

    stage: UnderstandingStage
    window: tuple[EpisodicMemory, ...]


async def _stage(model: FakeModelProvider, *records: MemoryRecord) -> _Staged:
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.write_atomic(
        [MemoryWrite(record=record, mode=MemoryWriteMode.INSERT_IF_ABSENT) for record in records]
    )
    return _Staged(
        stage=UnderstandingStage(model=model, excerpt_chars=2000),
        window=await RecentEpisodes(memory=memory, limit=10)(frozenset()),
    )


async def _understand(
    staged: _Staged, recalled: _Recall | None, *, episodes: bool = True
) -> ActivationUnderstanding:
    return await staged.stage.understand(
        "Same as before.",
        channel=CONVERSATION,
        window=ConversationWindow(CONVERSATION, ()),
        audience=BOUNDED,
        episodes=staged.window if episodes else None,
        version=1,
        now=lambda: AT,
        deadline=math.inf,
        recall=None if recalled is None else recalled[0],
        recalled=() if recalled is None else recalled[1],
    )


def _sent(model: FakeModelProvider, call: int = 0) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(model.calls[call].messages[1].content)
    return payload


def _instruction(model: FakeModelProvider) -> str:
    return model.calls[0].messages[0].content


# --- rendering --------------------------------------------------------------------------


async def test_no_recall_decision_renders_no_section_and_keeps_the_instruction() -> None:
    model = FakeModelProvider.scripted(_proposal(), _proposal())
    await _understand(await _stage(model), None)
    assert "recalled" not in _sent(model)
    assert "M1" not in _instruction(model)
    # The same instruction a stage built before recall existed renders.
    await _understand(await _stage(model), None)
    assert model.calls[1].messages[0] == model.calls[0].messages[0]


async def test_recalled_records_render_under_m_labels_in_recalls_order() -> None:
    model = FakeModelProvider.scripted(_proposal())
    fact = _fact("fact", source=MemorySource.USER_ASSERTED)
    episode = _episode("episode")
    await _understand(await _stage(model), _found(fact, episode), episodes=False)
    first, second = _sent(model)["recalled"]
    assert first == {
        "label": "M1",
        "item": "a remembered fact: something the user said",
        "last_updated": EARLIER.isoformat(),
        "fact": "The dentist is Dr Rao.",
        "fact_cut_to_first_chars": False,
    }
    assert second["label"] == "M2"
    assert second["item"] == "an earlier exchange on capture modality text"
    assert second["occurred_at"] == EARLIER.isoformat()
    assert second["response"] == "Booked for Friday."
    assert "M1, M2" in _instruction(model)
    assert "provisional, possibly out of date" in _instruction(model)


@pytest.mark.parametrize(
    ("source", "attribution"),
    [
        (MemorySource.USER_ASSERTED, "something the user said"),
        (MemorySource.INFERRED, "something the assistant worked out"),
        (MemorySource.OBSERVED, "something the assistant worked out"),
    ],
)
async def test_a_recalled_fact_is_attributed_by_its_band(
    source: MemorySource, attribution: str
) -> None:
    model = FakeModelProvider.scripted(_proposal())
    await _understand(await _stage(model), _found(_fact("fact", source=source)))
    assert _sent(model)["recalled"][0]["item"] == f"a remembered fact: {attribution}"


async def test_an_attested_fact_is_attributed_to_its_source() -> None:
    reported = SemanticMemory(
        id="reported",
        content="The dentist moved to Elm Street.",
        fact="The dentist moved to Elm Street.",
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=0.9,
            last_updated=EARLIER,
            attestation=Attestation(reported_by="calendar", reported_at=EARLIER),
        ),
    )
    model = FakeModelProvider.scripted(_proposal())
    await _understand(await _stage(model), _found(reported))
    assert _sent(model)["recalled"][0]["item"] == (
        "a remembered fact: something a connected source reported, never something the user said"
    )


async def test_a_recalled_record_already_in_a_window_is_not_rendered_twice() -> None:
    episode = _episode("episode")
    model = FakeModelProvider.scripted(_proposal())
    await _understand(await _stage(model, episode), _found(episode, _fact("fact")))
    sent = _sent(model)
    assert [item["label"] for item in sent["episode_window"]] == ["P1"]
    assert [item["label"] for item in sent["recalled"]] == ["M1"]
    assert sent["recalled"][0]["fact"] == "The dentist is Dr Rao."


async def test_a_section_whose_every_record_is_in_a_window_says_so() -> None:
    episode = _episode("episode")
    model = FakeModelProvider.scripted(_proposal())
    await _understand(await _stage(model, episode), _found(episode))
    assert _sent(model)["recalled"] == (
        "missing: everything recalled is already in the windows above"
    )


async def test_a_fact_longer_than_the_excerpt_bound_renders_cut_with_the_cut_disclosed() -> None:
    long = "Dr Rao " + "x" * 2500
    model = FakeModelProvider.scripted(_proposal())
    await _understand(await _stage(model), _found(_fact("fact", long)))
    rendered = _sent(model)["recalled"][0]
    assert rendered["fact"] == long[:2000]
    assert rendered["fact_cut_to_first_chars"] is True


@pytest.mark.parametrize(
    ("outcome", "statement"),
    [
        (RecallOutcome.NOTHING_FOUND, "missing: nothing was recalled for this input"),
        (RecallOutcome.FAILED, "missing: recall failed, so no memories are shown"),
        (RecallOutcome.TIMED_OUT, "missing: recall failed, so no memories are shown"),
    ],
)
async def test_a_recall_that_kept_nothing_or_failed_says_so(
    outcome: RecallOutcome, statement: str
) -> None:
    model = FakeModelProvider.scripted(_proposal())
    await _understand(await _stage(model), _decided(outcome))
    assert _sent(model)["recalled"] == statement


# --- resolution -----------------------------------------------------------------------


async def test_m_labels_resolve_to_episode_and_memory_referents() -> None:
    model = FakeModelProvider.scripted(
        _proposal(meaning_ground="supplied", meaning_labels=["M1", "M2"])
    )
    understood = await _understand(
        await _stage(model), _found(_episode("episode"), _fact("  fact id ")), episodes=False
    )
    assert understood.meaning_ground is UnderstandingGround.SUPPLIED
    assert understood.meaning_referents == (
        UnderstandingReferent(
            kind="episode",
            id="episode",
            source="capture modality text",
            excerpt="The user asked to book the dentist.",
        ),
        UnderstandingReferent(
            kind="memory",
            id="  fact id ",
            source="semantic memory",
            excerpt="The dentist is Dr Rao.",
        ),
    )
    assert understood.grounding_dropped == 0


async def test_a_memory_referents_excerpt_is_bounded() -> None:
    model = FakeModelProvider.scripted(_proposal(meaning_ground="supplied", meaning_labels=["M1"]))
    understood = await _understand(await _stage(model), _found(_fact("fact", "y" * 2500)))
    (referent,) = understood.meaning_referents
    assert referent.excerpt == "y" * UNDERSTANDING_REFERENT_EXCERPT_CHARS


async def test_the_repair_statement_names_the_recalled_sequence() -> None:
    model = FakeModelProvider.scripted(
        _proposal(meaning_ground="supplied", meaning_labels=["M9"]), _proposal()
    )
    await _understand(await _stage(model), _found(_fact("fact")), episodes=False)
    statement = model.calls[1].messages[3].content
    assert "no H labels (the channel window is empty)" in statement
    assert "no P labels (the episode window is empty) and M1 (the recalled section)" in statement
    assert '"M9"' in statement
