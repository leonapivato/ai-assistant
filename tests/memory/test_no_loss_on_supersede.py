"""A write never takes a fact out of current memory on similarity alone (ADR-0336).

The first three cases are #3237's reproductions, which were ``xfail(strict=True)`` until
ADR-0336 landed and are its regression tests now (§10:2). Each runs twice: once with no
reconciler, which is §6's floor — nothing labelled, so nothing superseded, swept or asked
about — and once with a stub reconciler supplying the labels the shape calls for.

**The mechanism they reproduced** was the asserted arm of ``DefaultMemoryPolicy`` ruling
on the conflict set — a similarity signal — as if it were a contradiction:

- An ``ASSERTED`` proposal against ``DERIVED`` members ruled ``SUPERSEDE`` (rule 9), and
  the writer retired every ``DERIVED`` or ``ATTESTED`` member it was shown.
- No relation reached that arm, because ADR-0159 §2 invoked no reconciler where the
  proposal or any member was ``ASSERTED``.
- A legacy memory stands at inference (ADR-0328 §16:10), so every memory stored before
  ADR-0328 was in the retirement class, whoever said it.
- An ``ASSERTED`` proposal against an ``ASSERTED`` member that was not a verbatim
  restatement ruled ``ASK_USER`` (rule 8), and the observer raised a question on each
  member the result named.

The cases after them are the rest of what ADR-0336 §10 asks of the lane, driven through
``DefaultMemoryPolicy`` and both writers: ``MemoryIngestor`` and the canonical fake.

The records are invented; the shapes are the ones a rerun over live data produced.
Conflict detection here is the in-memory store's lexical overlap, so the threshold is
lowered to stand in for the embedding similarity that paired these sentences live.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.types import (
    Attestation,
    ConflictRelation,
    EpisodicMemory,
    Memory,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
)
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor
from ai_assistant.memory._reconciler import ReconcilerOutcome, ReconcilerReport
from ai_assistant.testing import FakeMemoryWriter, FakeTraceSink
from ai_assistant.testing.memories import (
    derived_from,
    legacy_support,
    memory,
    said_support,
    sourced_support,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import MemoryWriter
    from ai_assistant.core.types import MemoryIngestResult, MemoryRecord

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


class _Stub:
    """Labels each member by a rule over its wording: what a model would have said.

    Keyed on the stored memory's content rather than its id, so a case states the
    relation of a claim rather than of a record name.
    """

    def __init__(self, label: Callable[[str], ConflictRelation | None]) -> None:
        self._label = label

    async def reconcile(
        self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
    ) -> dict[str, ConflictRelation]:
        """Label every member the rule has an answer for: the canonical fake's seam."""
        labels: dict[str, ConflictRelation] = {}
        for conflict in conflicts:
            relation = self._label(conflict.content)
            if relation is not None:
                labels[conflict.id] = relation
        return labels


class _Reporting:
    """The same stub at ``MemoryIngestor``'s seam, which reads ADR-0164 §3's report.

    It reports ``ANSWERED``, which is what makes the labels installable there.
    """

    def __init__(self, stub: _Stub) -> None:
        self._stub = stub

    async def reconcile(
        self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
    ) -> ReconcilerReport:
        """Answer with the stub's labels, as a reconciler that answered."""
        return ReconcilerReport(
            relations=await self._stub.reconcile(proposal, conflicts),
            outcomes=frozenset({ReconcilerOutcome.ANSWERED}),
        )


def _adds(_: str) -> ConflictRelation:
    """ADR-0336 §8: a narrower claim, a broader one, or another fact — all ``ADDS``."""
    return ConflictRelation.ADDS


def _now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


def _ingestor(store: InMemoryMemoryStore, reconciler: _Stub | None) -> MemoryWriter:
    return MemoryIngestor(
        traces_sink=FakeTraceSink(),
        store=store,
        policy=DefaultMemoryPolicy(),
        now=_now,
        conflict_threshold=_THRESHOLD,
        reconciler=None if reconciler is None else _Reporting(reconciler),
    )


def _fake(store: InMemoryMemoryStore, reconciler: _Stub | None) -> MemoryWriter:
    return FakeMemoryWriter(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=_now,
        conflict_threshold=_THRESHOLD,
        reconciler=reconciler,
    )


@pytest.fixture(params=[_ingestor, _fake], ids=["ingestor", "canonical-fake"])
def build(
    request: pytest.FixtureRequest,
) -> Callable[[InMemoryMemoryStore, _Stub | None], MemoryWriter]:
    """Both writers, which ADR-0336 §5:4 and §7:2 hold to the same rule."""
    builder: Callable[[InMemoryMemoryStore, _Stub | None], MemoryWriter] = request.param
    return builder


#: The two runs §10:2 asks of each reproduction: no reconciler, and a stub supplying the
#: labels the shape calls for — every member ``ADDS``, since none is contradicted.
_RUNS = pytest.mark.parametrize("stub", [None, _Stub(_adds)], ids=["no-reconciler", "stub-adds"])


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


# --- #3237's three reproductions (ADR-0336 §10:2) -------------------------------


@_RUNS
async def test_a_narrower_assertion_never_ends_a_broader_memory(
    build: Callable[[InMemoryMemoryStore, _Stub | None], MemoryWriter], stub: _Stub | None
) -> None:
    store = await _store("said-name")
    await _plant_legacy(store)

    result = await build(store, stub).ingest(_said("narrow", _NARROW, "said-name"))

    # Before ADR-0336: SUPERSEDE at legacy-broad, and the sweep ended legacy-broader.
    assert result.decision.kind is MemoryDecisionKind.ACCEPT
    assert await store.get("legacy-broad") is not None
    assert await store.get("legacy-broader") is not None


@_RUNS
async def test_no_fact_leaves_current_memory_because_of_a_write(
    build: Callable[[InMemoryMemoryStore, _Stub | None], MemoryWriter], stub: _Stub | None
) -> None:
    store = await _store("said-name", "said-address")
    await _plant_legacy(store)
    writer = build(store, stub)
    assert any(_ADDRESS in content for content in await _live(store))

    await writer.ingest(_said("narrow", _NARROW, "said-name"))
    # Before ADR-0336: the narrower memory was asserted and live, so the address
    # finding met an assertion that was not a verbatim restatement of it and deferred.
    address = await writer.ingest(_said("address", _ADDRESS_FINDING, "said-address"))

    assert address.decision.kind is MemoryDecisionKind.ACCEPT
    assert any(_ADDRESS in content for content in await _live(store))


@_RUNS
async def test_an_assertion_about_one_person_asks_nothing_about_another(
    build: Callable[[InMemoryMemoryStore, _Stub | None], MemoryWriter], stub: _Stub | None
) -> None:
    store = await _store("said-lena", "said-zeno")
    lena = _said("lena", "Lena's email address is lena@example.org.", "said-lena")
    await store.add(lena.proposed)

    result: MemoryIngestResult = await build(store, stub).ingest(
        _said("zeno", "Zeno's email address is zeno@example.org.", "said-zeno")
    )

    # Before ADR-0336: ASK_USER naming Lena's memory, on which the observer raised a
    # policy_ask about a claim that says nothing of her.
    assert result.decision.kind is MemoryDecisionKind.ACCEPT
    assert "lena" not in result.contradicted
    assert await store.get("zeno") is not None


# --- the rest of ADR-0336 §10's list --------------------------------------------

_MORNING = "the user prefers morning meetings"
_AFTERNOON = "the user prefers afternoon meetings"


async def _derived(store: InMemoryMemoryStore, *record_ids: str, content: str = _MORNING) -> None:
    """Inferences on one topic, each on a derived stand-in of its own."""
    for record_id in record_ids:
        await store.add(
            memory(record_id, content, *derived_from("said-before", key=record_id, when=_WHEN))
        )


async def test_an_asserted_correction_with_no_reconciler_retires_nothing(
    build: Callable[[InMemoryMemoryStore, _Stub | None], MemoryWriter],
) -> None:
    """§10's first case, inverting ADR-0171 §5's asserted-path test: ``ACCEPT``, beside."""
    store = await _store("said-before", "said-now")
    await _derived(store, "early", "dawn", "sunrise")

    result = await build(store, None).ingest(_said("correction", _AFTERNOON, "said-now"))

    assert result.decision.kind is MemoryDecisionKind.ACCEPT
    assert set(result.conflicts) == {"early", "dawn", "sunrise"}
    for record_id in ("early", "dawn", "sunrise"):
        assert await store.get(record_id) is not None, f"{record_id} was retired"


async def test_an_asserted_correction_retires_only_the_member_labelled_contradicting(
    build: Callable[[InMemoryMemoryStore, _Stub | None], MemoryWriter],
) -> None:
    """§10's third case: ``CONTRADICTS``, ``ADDS`` and unlabelled — only the first goes."""
    store = await _store("said-before", "said-now")
    await _derived(store, "contradicted", content=_MORNING)
    await _derived(store, "added-to", content="the user prefers morning meetings on mondays")
    await _derived(store, "unjudged", content="the user prefers morning meetings in person")
    labels = {
        _MORNING: ConflictRelation.CONTRADICTS,
        "the user prefers morning meetings on mondays": ConflictRelation.ADDS,
    }

    result = await build(store, _Stub(labels.get)).ingest(
        _said("correction", _AFTERNOON, "said-now")
    )

    assert set(result.conflicts) == {"contradicted", "added-to", "unjudged"}
    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    assert result.decision.target_id == "contradicted"
    assert await store.get("contradicted") is None
    assert await store.get("added-to") is not None
    assert await store.get("unjudged") is not None


@pytest.mark.parametrize(
    ("relation", "expected"),
    [
        (ConflictRelation.ADDS, MemoryDecisionKind.ACCEPT),
        (ConflictRelation.CONTRADICTS, MemoryDecisionKind.ASK_USER),
    ],
    ids=str,
)
async def test_an_assertion_beside_an_assertion_asks_only_on_a_contradiction(
    build: Callable[[InMemoryMemoryStore, _Stub | None], MemoryWriter],
    relation: ConflictRelation,
    expected: MemoryDecisionKind,
) -> None:
    """§10's fourth case: ``ADDS`` is no question; ``CONTRADICTS`` names that one alone.

    A second assertion that shares the topic and is left unlabelled sits in the set
    too, so a field naming the whole set fails.
    """
    store = await _store("said-before", "said-other", "said-now")
    await store.add(_said("theirs", _MORNING, "said-before").proposed)
    await store.add(
        _said("bystander", "the user prefers morning meetings remotely", "said-other").proposed
    )

    result = await build(store, _Stub({_MORNING: relation}.get)).ingest(
        _said("correction", _AFTERNOON, "said-now")
    )

    assert result.decision.kind is expected
    assert set(result.conflicts) >= {"theirs", "bystander"}
    if expected is MemoryDecisionKind.ASK_USER:
        assert result.contradicted == ("theirs",)
        assert await store.get("correction") is None
    else:
        assert result.contradicted == ()
        assert await store.get("correction") is not None


async def test_a_narrower_assertion_labelled_restating_leaves_the_broader_memory_unchanged(
    build: Callable[[InMemoryMemoryStore, _Stub | None], MemoryWriter],
) -> None:
    """§10's fifth case: a model's ``RESTATES`` installs beside, whatever the label (§3:3).

    A fold would lift the broader memory to "you said it" on a model's judgement, and
    attach the user's word to the address they did not state.
    """
    store = await _store("said-name")
    await _plant_legacy(store)
    before = await store.get("legacy-broad")

    result = await build(store, _Stub(lambda _: ConflictRelation.RESTATES)).ingest(
        _said("narrow", _NARROW, "said-name")
    )

    assert set(result.conflicts) == {"legacy-broad", "legacy-broader"}
    assert result.decision.kind is MemoryDecisionKind.ACCEPT
    assert await store.get("legacy-broad") == before
    assert await store.get("legacy-broader") is not None
    assert await store.get("narrow") is not None


async def test_a_narrower_attested_claim_labelled_adding_leaves_the_broader_memory_unchanged(
    build: Callable[[InMemoryMemoryStore, _Stub | None], MemoryWriter],
) -> None:
    """§10's sixth case: ``ADDS`` folds nothing, so the broader memory's standing holds.

    ADR-0336 §8's reason for reading a narrower claim as ``ADDS``: a fold of a source's
    report of half the claim would lift the whole broader memory to "from a source".
    """
    store = await _store("read-it")
    await _plant_legacy(store)
    before = await store.get("legacy-broad")
    assert isinstance(before, Memory)
    reported = MemoryUpdateProposal(
        proposed=memory(
            "reported",
            _NARROW,
            sourced_support(
                Attestation(reported_by="contacts:phone", reported_at=_WHEN),
                episode="read-it",
                when=_WHEN,
                added_at=_WHEN,
            ),
        ),
        rationale="a source reported it",
    )

    result = await build(store, _Stub(_adds)).ingest(reported)

    assert "legacy-broad" in result.conflicts
    assert result.decision.kind is MemoryDecisionKind.ACCEPT
    after = await store.get("legacy-broad")
    assert isinstance(after, Memory)
    assert after.supports == before.supports
    assert after.standing is before.standing


@pytest.mark.parametrize(
    ("relation", "expected"),
    [
        (ConflictRelation.ADDS, MemoryDecisionKind.ACCEPT),
        (ConflictRelation.CONTRADICTS, MemoryDecisionKind.ASK_USER),
    ],
    ids=str,
)
async def test_an_inference_beside_an_assertion_asks_only_on_a_contradiction(
    build: Callable[[InMemoryMemoryStore, _Stub | None], MemoryWriter],
    relation: ConflictRelation,
    expected: MemoryDecisionKind,
) -> None:
    """§10's seventh case: a ``DERIVED`` proposal beside an ``ASSERTED`` member (§4)."""
    store = await _store("said-before", "watched")
    await store.add(_said("theirs", _MORNING, "said-before").proposed)
    inference = MemoryUpdateProposal(
        proposed=memory("noticed", _AFTERNOON, *derived_from("watched", key="n", when=_WHEN)),
        rationale="the observer worked it out",
    )

    result = await build(store, _Stub({_MORNING: relation}.get)).ingest(inference)

    assert result.decision.kind is expected
    asked = expected is MemoryDecisionKind.ASK_USER
    assert result.contradicted == (("theirs",) if asked else ())
    assert await store.get("theirs") is not None
