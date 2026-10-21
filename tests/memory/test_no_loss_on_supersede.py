"""A write never takes a fact out of current memory: the reproduction of SUP's defect.

Each case below states the property the write path is expected to hold and is marked
``xfail(strict=True)``, because on this tree it does not hold and the change that would
make it hold is ADR-level (the lane stopped for a ruling). Strict, so the change that
fixes it has to remove the marker rather than pass silently around it.

**The mechanism all three share** is the asserted arm of ``DefaultMemoryPolicy`` ruling
on the conflict set — a similarity signal — as if it were a contradiction:

- An ``ASSERTED`` proposal against ``DERIVED`` members rules ``SUPERSEDE`` (rule 9,
  ADR-0038 §1-§2), and the writer retires every ``DERIVED`` or ``ATTESTED`` member it is
  shown (ADR-0050 §1, ADR-0079 §3). ADR-0171 §2's third clause leaves that sweep whole,
  because the writer holds no relations there.
- It holds none because ADR-0159 §2 invokes no reconciler where the proposal is
  ``ASSERTED`` or any member is — so ADR-0159 §5's spare of a ``RESTATES``/``ADDS``
  member, and ``_refuse_retiring_a_related_conflict``, never reach this arm.
- A legacy memory stands at inference (ADR-0328 §16:10), so every memory stored before
  ADR-0328 is in the retirement class, whoever said it.
- An ``ASSERTED`` proposal against an ``ASSERTED`` member that is not a verbatim
  restatement rules ``ASK_USER`` (rule 8, ADR-0050 §2), and the observer raises a
  question on each member the result names (ADR-0329 §13:1).

The records are invented; the shapes are the ones a rerun over live data produced.
Conflict detection here is the in-memory store's lexical overlap, so the threshold is
lowered to stand in for the embedding similarity that paired these sentences live.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.types import (
    EpisodicMemory,
    Memory,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
)
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor
from ai_assistant.testing import FakeTraceSink
from ai_assistant.testing.memories import legacy_support, memory, said_support

if TYPE_CHECKING:
    from ai_assistant.core.types import MemoryIngestResult

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: Low enough that the lexical store pairs the sentences an embedding paired live.
_THRESHOLD = 0.5

_ADDRESS = "mira@example.org"
_BROAD = f"The user's sister is named Mira, and her email address is {_ADDRESS}."
_BROADER = (
    f"The user's sister is named Mira and her email address is {_ADDRESS}; the user is "
    "willing to have the assistant email her."
)
_NARROW = "The user's sister is named Mira."
_ADDRESS_FINDING = f"The email address of the user's sister Mira is {_ADDRESS}."

_STOPPED = (
    "SUP: the asserted arm rules on similarity alone (ADR-0038 §1-§2, ADR-0050 §1-§2, "
    "ADR-0079 §3, ADR-0159 §2, ADR-0171 §2); changing it is ADR-level"
)


def _now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


async def _store(*episodes: str) -> InMemoryMemoryStore:
    """A store holding ``episodes``, so the supports below resolve (ADR-0328 §4:7)."""
    store = InMemoryMemoryStore()
    for episode in episodes:
        await store.add(
            EpisodicMemory(
                id=episode,
                content=f"the exchange {episode} records",
                occurred_at=_WHEN,
                provenance=Provenance(
                    source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN
                ),
            )
        )
    return store


def _ingestor(store: InMemoryMemoryStore) -> MemoryIngestor:
    return MemoryIngestor(
        traces_sink=FakeTraceSink(),
        store=store,
        policy=DefaultMemoryPolicy(),
        now=_now,
        conflict_threshold=_THRESHOLD,
    )


def _said(record_id: str, content: str, episode: str) -> MemoryUpdateProposal:
    """What the observer proposes from something the user said: band ``ASSERTED``."""
    return MemoryUpdateProposal(
        proposed=memory(record_id, content, said_support(episode, when=_WHEN, added_at=_WHEN)),
        rationale="the user said it",
    )


async def _plant_legacy(store: InMemoryMemoryStore) -> None:
    """Two memories stored before ADR-0328: each stands at inference (§16:10)."""
    for record_id, content in (("legacy-broad", _BROAD), ("legacy-broader", _BROADER)):
        await store.add(memory(record_id, content, legacy_support({"id": record_id})))


async def _live(store: InMemoryMemoryStore) -> list[str]:
    """The wording of every memory live on the read path."""
    return [
        record.content
        for record in await store.export()
        if isinstance(record, Memory) and await store.get(record.id) is not None
    ]


@pytest.mark.xfail(strict=True, reason=_STOPPED)
async def test_a_narrower_assertion_never_ends_a_broader_memory() -> None:
    store = await _store("said-name")
    await _plant_legacy(store)

    await _ingestor(store).ingest(_said("narrow", _NARROW, "said-name"))

    # Today: SUPERSEDE at legacy-broad, and the sweep ends legacy-broader beside it.
    assert await store.get("legacy-broad") is not None
    assert await store.get("legacy-broader") is not None


@pytest.mark.xfail(strict=True, reason=_STOPPED)
async def test_no_fact_leaves_current_memory_because_of_a_write() -> None:
    store = await _store("said-name", "said-address")
    await _plant_legacy(store)
    ingestor = _ingestor(store)
    assert any(_ADDRESS in content for content in await _live(store))

    await ingestor.ingest(_said("narrow", _NARROW, "said-name"))
    # Today: the narrower memory is now asserted and live, so the address finding meets
    # an assertion that is not a verbatim restatement of it and defers (ADR-0050 §2).
    await ingestor.ingest(_said("address", _ADDRESS_FINDING, "said-address"))

    assert any(_ADDRESS in content for content in await _live(store))


@pytest.mark.xfail(strict=True, reason=_STOPPED)
async def test_an_assertion_about_one_person_asks_nothing_about_another() -> None:
    store = await _store("said-lena", "said-zeno")
    lena = _said("lena", "Lena's email address is lena@example.org.", "said-lena")
    await store.add(lena.proposed)

    result: MemoryIngestResult = await _ingestor(store).ingest(
        _said("zeno", "Zeno's email address is zeno@example.org.", "said-zeno")
    )

    # Today: ASK_USER naming Lena's memory, on which the observer raises a policy_ask
    # (ADR-0329 §13:1) about a claim that says nothing of her.
    asked = result.decision.kind is MemoryDecisionKind.ASK_USER
    assert not (asked and "lena" in result.conflicts)
