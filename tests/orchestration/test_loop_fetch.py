"""Servicing the file a planner named (ADR-0230 §13's Lane C3).

ADR-0230 §14's representative-input tests that turn on a **fetch, a servicing or an
audit field**, at the seam that owes them. The items this module discharges are
numbered in the case that takes each: **1** end to end over a real root through the
production renderer, **2**'s two resolution arms, **6**, **7**'s fetching arms and
item 20's remaining clause, **11**, **12**, **13**, **14**, **15** and **18**.

Item **10** is engine-level — a *subsequent* turn of a conversation reaching the
egress seam — and lives in ``test_engine_capture_origin.py`` beside ADR-0223's other
end-to-end arms. Items **3**, **4**, **5**, **8**, **9**, **16**, **21**, **22** and
**23** are the contract's and the concrete fetcher's and were discharged by Lane C1;
items **17**, **19** and **20**'s projection half are C1's models and C2's seam.

**What this module is about is the loop's half of the mechanism**: that an ordinal
resolves into the listing this turn read and into nothing else, that the fetch is
serviced ahead of the hop for one slot of ADR-0226 §6's budget, that a refusal
resolves the outcome without degrading anything, and that §9's record gains the one
field ADR-0230 gives it and no address of any kind.

Every case is a test over behaviour, as §14 requires: what the supply carried, what
the reply was assembled from, and what the audit recorded. Where ``fetch_count``
appears it is §14 item 6's and item 14's own assertion — "a turn whose supply sufficed
pays no fetch", "performs no filesystem read for the request" — and never a stand-in
for the behaviour itself.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path as _Path
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    ActionPlan,
    BeliefBand,
    EpisodicMemory,
    FetchRefusal,
    MemorySource,
    Placement,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadRequest,
    Role,
    SemanticMemory,
    band_of,
    rests_on_recorded_external_content,
)
from ai_assistant.orchestration import LearningLoop, MemoryWriteStage
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.disclosure import (
    BoundedAudienceSupply,
    UnboundedAudienceSupply,
)
from ai_assistant.orchestration.loop import ConversationalOperation
from ai_assistant.orchestration.reads import READ_AUDIT_EVENT, READ_BUDGET, resolve_entry
from ai_assistant.testing import (
    FakeContextProvider,
    FakeDeferralStore,
    FakeFeedbackProcessor,
    FakeFetcher,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeModelProvider,
    FakePlanner,
    FakeStreamingCompleter,
    FakeToolRegistry,
)

sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "readers"))

from fetch_fixtures import fetcher as real_fetcher
from pdf_fixtures import minimal_pdf

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import Fetcher, MemoryStore, Planner
    from ai_assistant.core.types import MemoryRecord, SourceListing, SourceListingEntry
    from ai_assistant.orchestration.loop import RespondedTurn

_NOW: Final = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)

#: The word the exit's disk clause turns on: it is in a document under the root and
#: in nothing the store holds, so a reply carrying it can only have come from disk.
_DISTINCTIVE: Final = "quinoa-flavoured stroopwafel"

#: A root with three entries, so a case has positions to be wrong about. The first is
#: what ``F1`` names, because :class:`FakeFetcher` lists in the mapping's own order.
_ROOT: Final = {
    "quarterly-review.md": f"the margin held at 41 percent, over a {_DISTINCTIVE}",
    "notes.md": "a note about nothing in particular",
    "roster.txt": "who is on call this week",
}


def _clock() -> datetime:
    return _NOW


#: The operation a revising case runs on. ADR-0228 §2(a) admits a second planner call
#: only where the turn's operation **declares a planning budget**, so a case that
#: wants a revision names one rather than relying on a default: "an undeclared budget
#: is not a default, not unknown-and-therefore-permitted".
_REVISING: Final = ConversationalOperation.CONVERSE


# --------------------------------------------------------------------------- #
# Records                                                                      #
# --------------------------------------------------------------------------- #


def _belief(record_id: str, content: str, *, evidence: tuple[str, ...] = ()) -> SemanticMemory:
    """A belief the turn's own retrieval selects, optionally citing an exchange."""
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        placement=Placement(),
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.6,
            last_updated=_NOW,
            evidence=evidence,
        ),
    )


def _episode(record_id: str, content: str) -> EpisodicMemory:
    """A captured turn, as ``orchestration.conversations`` stamps one."""
    return EpisodicMemory(
        id=record_id,
        content=content,
        occurred_at=_NOW,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_NOW),
    )


# --------------------------------------------------------------------------- #
# Requests                                                                     #
# --------------------------------------------------------------------------- #


def _file(entry: str = "F1") -> ReadRequest:
    """A request naming one file and nothing else (ADR-0230 §1)."""
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.LOCAL_FILE, entry=entry),))


def _file_and_hop(entry: str, *labels: str) -> ReadRequest:
    """A request naming a file **and** a hop, with the hop listed first.

    The order in ``asks`` is deliberately the reverse of the servicing order ADR-0230
    §7 fixes, so an implementation following the tuple rather than §7 fails.
    """
    return ReadRequest(
        asks=(
            ReadAsk(kind=ReadKind.CITATION_HOP, labels=labels),
            ReadAsk(kind=ReadKind.LOCAL_FILE, entry=entry),
        )
    )


def _file_and_query(entry: str, text: str) -> ReadRequest:
    """A request naming a file and a sighted query."""
    return ReadRequest(
        asks=(
            ReadAsk(kind=ReadKind.LOCAL_FILE, entry=entry),
            ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=text),
        )
    )


# --------------------------------------------------------------------------- #
# The loop, and readers over what it wrote                                     #
# --------------------------------------------------------------------------- #


def _loop(
    *,
    planner: Planner | None = None,
    fetcher: Fetcher | None = None,
    memory: MemoryStore | None = None,
    retrieval_limit: int = 30,
) -> LearningLoop:
    """A loop over canonical fakes, with the fetcher a case supplies (or none).

    The episodic supplement is **off**, for ``test_loop_reads.py``'s reason: a case's
    supply is then exactly the beliefs it seeded, so "what the servicing added" is a
    reading rather than a subtraction.
    """
    store = memory if memory is not None else FakeMemoryStore(now=_clock)
    return LearningLoop(
        context=FakeContextProvider(),
        memory=store,
        writes=MemoryWriteStage(
            writer=FakeMemoryWriter(store=store, policy=FakeMemoryPolicy(), now=_clock),
            deferrals=FakeDeferralStore(now=_clock),
        ),
        planner=planner if planner is not None else FakePlanner(now=_clock),
        registry=FakeToolRegistry(),
        feedback=FakeFeedbackProcessor(),
        fetcher=fetcher,
        retrieval_limit=retrieval_limit,
        episodic_limit=0,
        now=_clock,
        id_factory=lambda: "goal-1",
    )


def _bounded() -> BoundedAudienceSupply:
    """The filter ``converse`` supplies: evaluates, and subtracts nothing."""
    return BoundedAudienceSupply(speakable_attested_sources=frozenset())


def _unbounded() -> UnboundedAudienceSupply:
    """The filter ``converse_spoken`` supplies: ADR-0199 §3's subtraction."""
    return UnboundedAudienceSupply(speakable_attested_sources=frozenset())


def _record(captured: Sequence[MutableMapping[str, Any]]) -> Mapping[str, Any]:
    """The one audit record ADR-0226 §9 obliges this turn to have written."""
    [only] = [event for event in captured if event["event"] == READ_AUDIT_EVENT]
    return only


def _serviced(captured: Sequence[MutableMapping[str, Any]], ordinal: int = 0) -> Mapping[str, Any]:
    """One servicing's entry in this turn's record (ADR-0228 §9)."""
    return _record(captured)["servicings"][ordinal]  # type: ignore[no-any-return]


def _ids(memories: Sequence[MemoryRecord]) -> list[str]:
    return [record.id for record in memories]


def _external(memories: Sequence[MemoryRecord]) -> list[MemoryRecord]:
    """The records ``rests_on_recorded_external_content`` is true of (ADR-0223 §1)."""
    return [one for one in memories if rests_on_recorded_external_content(one.provenance)]


def _contents(memories: Sequence[MemoryRecord]) -> str:
    """Every record's content run together, for an "appears nowhere" assertion."""
    return "\n".join(record.content for record in memories)


async def _prompt_over(responded: RespondedTurn) -> str:
    """The user-turn prompt the **production** renderer assembles for one turn.

    ADR-0227 §7's fidelity rule forbids substituting "the renderer whose output the
    assertion is about" and permits a fake ``ModelProvider``, so the production
    :class:`~ai_assistant.orchestration.composing.ComposingStage` assembles the prompt
    and the fake merely records it. ADR-0230 §14 item 1 binds this module to it: a
    case asserting what a model was shown runs the production renderer for that
    surface, over records shaped as the production capture site writes them — here,
    the record a real ``LocalFileFetcher`` minted from a real file.
    """
    model = FakeModelProvider("answer")
    stage = ComposingStage(model=model, streaming=FakeStreamingCompleter())
    await stage.compose(
        turn=responded.turn, step=None, undriven=(), hop_reached=responded.hop_reached
    )
    [call] = model.calls
    return next(one.content for one in call.messages if one.role is Role.USER)


# --------------------------------------------------------------------------- #
# §14 item 1: the exit's disk clause answers from disk                         #
# --------------------------------------------------------------------------- #


@pytest.fixture
def documents(tmp_path: Path) -> Path:
    """A real root holding a real PDF whose text carries the distinctive word."""
    root = tmp_path / "documents"
    root.mkdir()
    (root / "quarterly-review.pdf").write_bytes(
        minimal_pdf(["The quarterly review", f"The margin held, over a {_DISTINCTIVE}."])
    )
    return root


async def test_a_turn_whose_supply_knows_nothing_answers_from_the_document(
    documents: Path,
) -> None:
    """§14 item 1: the reply carries the word, and it came from disk.

    "A turn whose supply holds nothing about a document; a root holding a PDF whose
    text carries a distinctive word; the listing shows it; the planner names its
    label; the fetch mints one record; and **the reply carries the word**."

    **Everything on the path is the production article but the model and the
    planner**: a real ``LocalFileFetcher`` over a real directory, a real PDF, a real
    extraction, the real servicer, and ``composing.py``'s own renderer — which is
    ADR-0227's lesson applied, and what makes this the exit's disk clause rather than
    a restatement of the servicer's unit tests. A ``FakeModelProvider`` reads the
    assembled prompt and a ``FakePlanner`` names ``F1``, because neither a completion
    nor a model's choice of label is what this case is about.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "the quarterly numbers came up last week"))
    planner = FakePlanner(now=_clock, read_request=_file("F1"))

    responded = await _loop(
        planner=planner, fetcher=real_fetcher(documents), memory=memory
    ).respond("summarise the PDF I saved yesterday", narrow=_bounded())

    assert _DISTINCTIVE not in _contents(planner.calls[0][2]), (
        "the supply the planner saw held nothing about the document"
    )
    fetched = [record for record in responded.turn.memories if _DISTINCTIVE in record.content]
    assert len(fetched) == 1, "the fetch minted exactly one record (ADR-0230 §5)"
    assert _DISTINCTIVE in await _prompt_over(responded), (
        "the production renderer put the document's own text in front of the model"
    )


async def test_the_record_the_fetch_minted_is_the_one_adr_0230_s5_describes(
    documents: Path,
) -> None:
    """§5's shape, over the record a **real** fetcher wrote from a **real** file.

    The externality mark is the milestone's control rather than its cost (§5), so the
    fields it rests on are asserted where the record actually enters a supply: a
    ``SEMANTIC`` record in the ``ATTESTED`` band, ``EXTERNAL``-sourced, attested to
    the fetcher's own source instance, carrying no evidence and — ADR-0092 §3
    untouched — no instant taken from the file's mtime.
    """
    planner = FakePlanner(now=_clock, read_request=_file("F1"))
    fetcher = real_fetcher(documents)

    responded = await _loop(planner=planner, fetcher=fetcher).respond(
        "summarise the PDF I saved yesterday", narrow=_bounded()
    )

    [record] = [one for one in responded.turn.memories if _DISTINCTIVE in one.content]
    assert isinstance(record, SemanticMemory), "ADR-0230 §5: exactly one SEMANTIC record"
    assert record.provenance.source is MemorySource.EXTERNAL
    assert band_of(record.provenance.source) is BeliefBand.ATTESTED
    assert rests_on_recorded_external_content(record.provenance) is True
    assert record.provenance.evidence == ()
    assert record.provenance.derived_from_external is False
    attestation = record.provenance.attestation
    assert attestation is not None
    assert attestation.reported_by == fetcher.name, "the root, never whatever wrote it"
    assert str(documents) not in repr(record), "no path is on the record (ADR-0230 §5)"


# --------------------------------------------------------------------------- #
# §14 item 2: an address outside the listing resolves to nothing               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "label",
    ["F4", "F99", "M1", "F0", "F01", "f1", "F1 ", "", "F", "../etc/passwd", "quarterly-review.md"],
    ids=[
        "one_past_the_end",
        "far_past_the_end",
        "the_other_kinds_namespace",
        "below_one",
        "padded",
        "lowercase",
        "trailing_space",
        "empty_is_refused_by_the_model",
        "no_ordinal",
        "a_path",
        "a_name_rather_than_an_ordinal",
    ],
)
def test_a_label_outside_the_listing_resolves_to_nothing(label: str) -> None:
    """§2 and §14 item 2's first two arms, at the resolution itself.

    "A string that does not match the form, an *n* below 1, and an *n* beyond the
    sequence's length" all resolve to nothing, "not an error, not a park, not a
    degradation of the turn". The two arms §14 item 2 adds to those — an entry whose
    ``name`` carries a separator, and one naming a symbolic link out of the root — are
    the fetcher's and are asserted over a real filesystem in
    ``tests/readers/test_fetcher_races.py``.

    **A path and a filename are in the parameter list on purpose.** They are the two
    shapes a model would produce if it had been taught to name an address, and both
    resolve to nothing here rather than to a file — which is §2's claim that "no string
    a model produced is ever interpreted as a filesystem address, in any form" at the
    one function that could break it.
    """
    listing = _listing_of(_ROOT)

    assert resolve_entry(label, listing) is None
    if label:
        assert resolve_entry(label, None) is None, "and on a turn that showed no listing"


def _listing_of(files: Mapping[str, str]) -> SourceListing:
    """A listing a case constructs directly, so resolution is checkable in isolation.

    §14 item 7 asks that the two packages be shown to agree "with no shared table,
    asserted by resolving an ask against a listing the test constructs directly".
    """
    return asyncio.run(FakeFetcher(dict(files), read_at=_NOW).listing())


async def test_an_unresolvable_ordinal_is_audited_and_renders_nothing() -> None:
    """§2 and §9: unresolved, no record, no refusal, no failure, and no fetch.

    §9 separates the two facts in terms: "a label that resolved to nothing never
    reached the fetcher and counts in the existing unresolved-label count; a refusal
    is a label that resolved to an entry the fetcher then declined". This is the first
    of the pair, and the ``refusal`` field being ``None`` is what says the servicer did
    not collapse them.
    """
    fetcher = FakeFetcher(_ROOT, read_at=_NOW)
    planner = FakePlanner(now=_clock, read_request=_file("F9"))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(planner=planner, fetcher=fetcher).respond(
            "how did the quarter go", narrow=_bounded()
        )

    assert fetcher.fetch_count == 0, "an unresolved label never reached the fetcher"
    serviced = _serviced(captured)
    assert serviced["labels_unresolved"] == 1
    assert serviced["refusal"] is None, "an unresolved label is not a refusal"
    assert serviced["new"] == 0
    assert serviced["failed"] is False, "not an error, not a park, not a degradation"
    assert responded.turn.memories == tuple(planner.calls[0][2]), "the supply is unchanged"
    assert _DISTINCTIVE not in await _prompt_over(responded)


async def test_a_named_file_on_a_turn_that_showed_no_listing_resolves_to_nothing() -> None:
    """§2: "a turn on which the loop passed no listing is a turn on which no file is
    nameable" — and §3, which makes no fetcher and an empty root the same case."""
    for fetcher in (None, FakeFetcher({}, read_at=_NOW)):
        planner = FakePlanner(now=_clock, read_request=_file("F1"))

        with structlog.testing.capture_logs() as captured:
            responded = await _loop(planner=planner, fetcher=fetcher).respond(
                "how did the quarter go", narrow=_bounded()
            )

        assert _serviced(captured)["labels_unresolved"] == 1
        assert _serviced(captured)["refusal"] is None
        assert responded.turn.memories == tuple(planner.calls[0][2])


# --------------------------------------------------------------------------- #
# §14 item 6: a turn whose supply sufficed pays no fetch                       #
# --------------------------------------------------------------------------- #


async def test_a_turn_whose_supply_sufficed_pays_no_fetch() -> None:
    """§14 item 6, over the audit and the supply as the item requires.

    "The plan carries no request, the fetcher is asked for no file, the supply is
    byte-for-byte the three groups it was, and the audit records a turn on which the
    trigger did not fire." The listing is still read — §3 makes that once per turn and
    unconditional, because the planner cannot name what it was not shown — and the
    fetch is what does not happen.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "the quarterly margin held at 41 percent"))
    fetcher = FakeFetcher(_ROOT, read_at=_NOW)
    planner = FakePlanner(now=_clock)

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(planner=planner, fetcher=fetcher, memory=memory).respond(
            "how did the quarter go", narrow=_bounded()
        )

    assert fetcher.listing_count == 1, "§3: once per turn, before the first planner call"
    assert fetcher.fetch_count == 0
    assert responded.turn.memories == tuple(planner.calls[0][2])
    assert _record(captured)["trigger"] == "not_fired"
    assert _record(captured)["servicings"] == ()


# --------------------------------------------------------------------------- #
# §14 items 7 and 20: F*n* fetches the entry at position *n*                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("label", "position"), [("F1", 0), ("F2", 1), ("F3", 2)])
async def test_the_ordinal_fetches_the_entry_at_that_position(label: str, position: int) -> None:
    """§14 item 20's remaining clause: "``F``\\ *n* fetches the entry at position *n*".

    The arm that fails on any implementation projecting a filtered, reordered or
    partial sequence — and the one that fails on an off-by-one, which every other case
    in this module would survive because they all name ``F1``.
    """
    fetcher = _RecordingFetcher(_ROOT)
    planner = FakePlanner(now=_clock, read_request=_file(label))

    responded = await _loop(planner=planner, fetcher=fetcher).respond(
        "how did the quarter go", narrow=_bounded()
    )

    assert [entry.name for entry in fetcher.fetched] == [list(_ROOT)[position]]
    fourth = responded.turn.memories[len(planner.calls[0][2]) :]
    assert [record.content for record in fourth] == [list(_ROOT.values())[position]]


async def test_the_same_label_names_the_same_entry_on_both_calls_of_a_revising_turn() -> None:
    """§14 item 7's last clause, on the fetching side of it.

    "The same label resolves to the same entry on **both** planner calls of a revising
    turn." §3 is why: the listing is read once per turn and the *same* sequence is
    passed to both calls, so ``F1`` is stable across them where ADR-0228 §8 makes an
    ``M`` label deliberately unstable — the supply grows and the listing does not.
    """
    fetcher = _RecordingFetcher(_ROOT)
    planner = FakePlanner(
        now=_clock,
        read_request=_file("F1"),
        revision=ActionPlan(
            id="plan-2",
            goal_id="goal-1",
            steps=(),
            created_at=_NOW,
            rationale="asked for the same file again",
            read_request=_file("F1"),
        ),
    )

    await _loop(planner=planner, fetcher=fetcher).respond(
        "how did the quarter go", narrow=_bounded(), operation=_REVISING
    )

    assert len(planner.calls) == 2, "the turn revised (ADR-0228 §2)"
    assert [entry.name for entry in fetcher.fetched] == ["quarterly-review.md"] * 2
    assert fetcher.listing_count == 1, "§3: no lane re-reads it between a turn's two calls"


class _RecordingFetcher:
    """A ``FakeFetcher`` that records the **entries** it was asked to fetch.

    The behavioural instrument for item 20's positional clause: what a case needs is
    which entry of the listing reached ``fetch``, which is a fact about the argument
    and not about the outcome. Delegating rather than subclassing keeps the canonical
    fake's own verification — a handle this wrapper altered would still be refused.
    """

    def __init__(self, files: Mapping[str, str], **kwargs: Any) -> None:
        self._inner = FakeFetcher(dict(files), read_at=_NOW, **kwargs)
        self.fetched: list[SourceListingEntry] = []

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def listing_count(self) -> int:
        return self._inner.listing_count

    @property
    def fetch_count(self) -> int:
        return self._inner.fetch_count

    async def listing(self) -> SourceListing:
        return await self._inner.listing()

    async def fetch(self, listing: SourceListing, entry: SourceListingEntry) -> Any:
        self.fetched.append(entry)
        return await self._inner.fetch(listing, entry)


# --------------------------------------------------------------------------- #
# §14 item 11: the fetch is serviced before the hop and takes one slot         #
# --------------------------------------------------------------------------- #


async def test_the_fetch_is_serviced_before_the_hop_and_takes_one_slot() -> None:
    """§14 item 11, and ADR-0230 §7's precedence with it.

    "A request carrying a ``LOCAL_FILE`` ask and a ``CITATION_HOP`` whose evidence
    would fill the budget produces a fourth group holding the fetched record first and
    exactly nine hop records after it, in that order, with the truncation in the
    audit."

    The request lists the hop **first** in ``asks``, so an implementation following the
    tuple rather than §7 fails this — and the reverse order is exactly the failure §7
    argues against: "the reverse order would let a hop that reached ten records starve
    the one read the user pointed at".
    """
    memory = FakeMemoryStore(now=_clock)
    cited = tuple(f"cited-{n}" for n in range(1, 13))
    await memory.add(_belief("belief-1", "the quarterly margin", evidence=cited))
    for record_id in cited:
        await memory.add(_belief(record_id, "an earlier quarterly exchange"))
    planner = FakePlanner(now=_clock, read_request=_file_and_hop("F1", "M1"))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=planner,
            fetcher=FakeFetcher(_ROOT, read_at=_NOW),
            memory=memory,
            retrieval_limit=1,
        ).respond("how did the quarter go", narrow=_bounded())

    fourth = responded.turn.memories[1:]
    assert len(fourth) == READ_BUDGET, "one budget of ten, shared by the two kinds"
    assert fourth[0].content == _ROOT["quarterly-review.md"], "the file first (ADR-0230 §7)"
    assert _ids(fourth[1:]) == list(cited[:9]), "and exactly nine of the hop's after it"
    serviced = _serviced(captured)
    assert serviced["truncated_kinds"] == (ReadKind.CITATION_HOP.value,)
    assert serviced["new"] == READ_BUDGET
    assert serviced["refusal"] is None


async def test_the_fetch_is_never_the_kind_the_budget_truncates() -> None:
    """ADR-0230 §1's cap of one, read off the audit rather than asserted in prose.

    The fetch is serviced first and admits at most one record into ten empty slots, so
    ``local_file`` cannot appear in ``truncated_kinds`` however full the servicing gets
    — which is why the servicer writes no branch for it. This is that reachability
    argument turned into an assertion, on a servicing whose query is cut by the budget
    and would have taken every slot had it been serviced first.
    """
    memory = await _loose_notes(20, "an unfiled quarterly note")
    planner = FakePlanner(now=_clock, read_request=_file_and_query("F1", "unfiled quarterly note"))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=planner,
            fetcher=FakeFetcher(_ROOT, read_at=_NOW),
            memory=memory,
            retrieval_limit=1,
        ).respond("how did the quarter go", narrow=_bounded())

    serviced = _serviced(captured)
    assert serviced["returned"] == READ_BUDGET, (
        "the fetch's one candidate, and the nine slots it left the query"
    )
    assert serviced["truncated_kinds"] == (ReadKind.SIGHTED_QUERY.value,), (
        "the query is what the budget cut"
    )
    assert ReadKind.LOCAL_FILE.value not in serviced["truncated_kinds"]
    assert responded.turn.memories[1].content == _ROOT["quarterly-review.md"]


# --------------------------------------------------------------------------- #
# §14 item 12: a refusal degrades nothing                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("refusal", list(FetchRefusal))
async def test_a_refusal_takes_no_slot_and_discards_nothing(refusal: FetchRefusal) -> None:
    """§14 item 12, one arm per member of ADR-0230 §6's closed enumeration.

    "A request carrying a ``LOCAL_FILE`` ask that refuses and a ``SIGHTED_QUERY`` that
    returns produces a fourth group holding the query's records **in full**: the
    refusal takes no slot, discards nothing, and is recorded as a refusal rather than
    as a servicing failure."

    "In full" is asserted against a **control** — the same turn with the same store
    and the same query, asked without the ``LOCAL_FILE`` ask at all — so the claim is
    that the refusal changed nothing rather than that a hand-counted number came back.

    This is the arm that distinguishes §6's refusal disposition from ADR-0226 §5's
    all-or-nothing failure posture, where a *failure* would have zeroed the query's
    yield too and where a refusal recorded as one would be indistinguishable from a
    store outage.
    """
    query = "unfiled quarterly note"
    control = await _query_only_fourth_group(query)

    memory = await _loose_notes(4, query)
    fetcher = FakeFetcher(_ROOT, read_at=_NOW, refusals={"quarterly-review.md": refusal})
    planner = FakePlanner(now=_clock, read_request=_file_and_query("F1", query))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=planner, fetcher=fetcher, memory=memory, retrieval_limit=1
        ).respond("how did the quarter go", narrow=_bounded())

    fourth = responded.turn.memories[1:]
    assert _ids(fourth) == control, "the query's records in full — the refusal took no slot"
    assert _DISTINCTIVE not in _contents(responded.turn.memories), "and minted nothing"
    serviced = _serviced(captured)
    assert serviced["refusal"] == refusal.value
    assert serviced["failed"] is False, "a refusal is a resolved outcome and never a failure"
    assert serviced["labels_unresolved"] == 0, "the label resolved; the fetcher declined"
    assert serviced["new"] == len(control)


async def _loose_notes(count: int, content: str) -> FakeMemoryStore:
    """A store holding ``count`` beliefs a sighted query for ``content`` matches."""
    memory = FakeMemoryStore(now=_clock)
    for n in range(1, count + 1):
        await memory.add(_belief(f"loose-{n}", content))
    return memory


async def _query_only_fourth_group(query: str) -> list[str]:
    """The fourth group of the same turn asked **without** a ``LOCAL_FILE`` ask.

    The control the case above compares against: what the sighted query alone puts in
    the fourth group, over an identical store and an identical retrieval.
    """
    memory = await _loose_notes(4, query)
    planner = FakePlanner(
        now=_clock,
        read_request=ReadRequest(asks=(ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=query),)),
    )
    responded = await _loop(planner=planner, memory=memory, retrieval_limit=1).respond(
        "how did the quarter go", narrow=_bounded()
    )
    return _ids(responded.turn.memories[1:])


async def test_a_refusal_renders_no_name_no_excerpt_and_no_library_message() -> None:
    """§6 and §9: the class is the whole of the value, so there is nothing to render.

    A refusal "names a **class** and carries no path, no name, no excerpt and no
    message from an underlying library", and the servicer adds no record for one — so
    neither the prompt the production renderer assembles nor the reply has anything of
    the file in it, and the audit carries a closed-enumeration member and no more.
    """
    fetcher = FakeFetcher(
        _ROOT, read_at=_NOW, refusals={"quarterly-review.md": FetchRefusal.EXTRACTION_FAILED}
    )
    planner = FakePlanner(now=_clock, read_request=_file("F1"))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(planner=planner, fetcher=fetcher).respond(
            "summarise the quarterly review", narrow=_bounded()
        )

    prompt = await _prompt_over(responded)
    for secret in (_DISTINCTIVE, "quarterly-review.md", "quarterly-review", ".md"):
        assert secret not in prompt, f"{secret!r} reached the prompt"
    assert responded.turn.memories == tuple(planner.calls[0][2])
    assert _serviced(captured)["refusal"] == FetchRefusal.EXTRACTION_FAILED.value


# --------------------------------------------------------------------------- #
# §14 item 13: a serviced fetch may revise the plan                            #
# --------------------------------------------------------------------------- #


async def test_a_serviced_fetch_revises_the_plan_and_each_servicing_draws_its_own_budget() -> None:
    """§14 item 13, over the supply and the audit's per-servicing entries.

    "A turn whose first plan names a file and whose second plan, made over the fetched
    record, names a different one; both fetches are serviced, the fourth group holds
    both records in servicing order, and each servicing draws its own budget."

    ADR-0228 §2's seven conditions are unchanged and none of them is about the kind
    (ADR-0230 §7): a fetch that added a record satisfies §2(e) exactly as a hop that
    did, and no lane "suppresses a revision because the read was outward".
    """
    fetcher = _RecordingFetcher(_ROOT)
    planner = FakePlanner(
        now=_clock,
        read_request=_file("F1"),
        revision=ActionPlan(
            id="plan-2",
            goal_id="goal-1",
            steps=(),
            created_at=_NOW,
            rationale="the review pointed at the roster",
            read_request=_file("F3"),
        ),
    )

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(planner=planner, fetcher=fetcher).respond(
            "how did the quarter go", narrow=_bounded(), operation=_REVISING
        )

    assert [entry.name for entry in fetcher.fetched] == ["quarterly-review.md", "roster.txt"]
    fourth = [record.content for record in responded.turn.memories[len(planner.calls[0][2]) :]]
    assert fourth == [_ROOT["quarterly-review.md"], _ROOT["roster.txt"]], "in servicing order"
    record = _record(captured)
    assert record["planner_calls"] == 2
    assert len(record["servicings"]) == 2, "one entry per servicing (ADR-0228 §9)"
    for ordinal in (0, 1):
        entry = _serviced(captured, ordinal)
        assert entry["kinds"] == (ReadKind.LOCAL_FILE.value,)
        assert entry["new"] == 1, "each servicing draws its own budget (ADR-0228 §7)"
        assert entry["refusal"] is None


async def test_the_second_plan_sees_the_supply_the_first_fetch_produced() -> None:
    """ADR-0228 §1 over an outward read, and §7's monotonicity with it.

    A revision is "the model's judgement over a wider supply", and ADR-0230 §7 admits
    it here rather than preventing it: "a document the planner asked for is exactly the
    material a second judgement is worth making over". §8 is where that steering is
    faced and it is faced by there being nowhere to steer to, not by filtering the
    fourth group — so this asserts that the second call really did see the file.
    """
    planner = FakePlanner(
        now=_clock,
        read_request=_file("F1"),
        revision=ActionPlan(
            id="plan-2",
            goal_id="goal-1",
            steps=(),
            created_at=_NOW,
            rationale="answered from the document",
        ),
    )

    await _loop(planner=planner, fetcher=FakeFetcher(_ROOT, read_at=_NOW)).respond(
        "how did the quarter go", narrow=_bounded(), operation=_REVISING
    )

    first, second = planner.calls
    assert _DISTINCTIVE not in _contents(first[2])
    assert _DISTINCTIVE in _contents(second[2]), "the second call ran over the fetched record"
    assert first[4] == second[4], "and over the same listing (ADR-0230 §3)"


# --------------------------------------------------------------------------- #
# §14 item 14: an unbounded-audience operation fetches nothing                 #
# --------------------------------------------------------------------------- #


async def test_an_unbounded_audience_turn_performs_no_fetch_and_records_the_decline() -> None:
    """§14 item 14, and ADR-0226 §5's channel scoping reaching the third kind.

    "A turn on ``converse_spoken`` whose planner emits a ``LOCAL_FILE`` ask reaches
    the composing stage with the three groups ADR-0203 §1 narrowed, performs no
    filesystem read for the request, and records the emission as declined."

    What is scoped is the **servicing** and never the emission, so the listing is still
    shown and the ask is still emitted — which is what keeps the trigger measured on
    every channel and what makes this turn reachable at all.
    """
    fetcher = FakeFetcher(_ROOT, read_at=_NOW)
    planner = FakePlanner(now=_clock, read_request=_file("F1"))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(planner=planner, fetcher=fetcher).respond(
            "how did the quarter go", narrow=_unbounded()
        )

    assert fetcher.fetch_count == 0, "no filesystem read for the request"
    assert fetcher.listing_count == 1, "but the listing is still shown (ADR-0230 §3)"
    assert responded.turn.plan.read_request == _file("F1"), "the emission is not suppressed"
    assert _DISTINCTIVE not in _contents(responded.turn.memories)
    record = _record(captured)
    assert record["trigger"] == "fired"
    assert record["servicing"] == "declined"
    assert record["servicings"] == ()


# --------------------------------------------------------------------------- #
# §14 item 15: no address in the audit, no capability anywhere                 #
# --------------------------------------------------------------------------- #


async def test_the_audit_carries_no_address_and_the_capability_reaches_nothing() -> None:
    """§14 item 15, over the emitted event's own fields and over the prompt.

    "A turn that fetches a file whose name carries a distinctive string emits a record
    in which that string appears nowhere — no path, no name, no extension, no size, no
    excerpt — the refusal field is a closed-enumeration member or absent, and the
    ambient correlation id is the only identifier on the event." Asserted over the
    event's own fields and **not** over the redaction net (ADR-0004 §5, ADR-0226 §9).

    "Separately, the ``token`` and the entry handles of that turn's listing appear in
    **no** prompt the turn assembled, in no log line and on no field of the record the
    fetch minted" — the invariant being where a capability may **go**, since §4 has the
    fetcher hand entries to `orchestration` and take them back on ``fetch``.
    """
    named = "salary-negotiation-with-priya.md"
    fetcher = _RecordingFetcher({named: f"a document holding a {_DISTINCTIVE}"})
    planner = FakePlanner(now=_clock, read_request=_file("F1"))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(planner=planner, fetcher=fetcher).respond(
            "how did the quarter go", narrow=_bounded()
        )

    listing = await fetcher.listing()  # a fresh one; its shape is what a case reads
    lines = repr(captured)
    for address in (named, "salary-negotiation", ".md", _DISTINCTIVE, str(len(named))):
        assert address not in lines, f"{address!r} reached the log"
    assert _record(captured)["correlation_id"] is None
    assert _serviced(captured)["refusal"] is None

    prompt = await _prompt_over(responded)
    [fetched] = [one for one in responded.turn.memories if _DISTINCTIVE in one.content]
    for capability in (listing.token, *(entry.handle for entry in listing.entries)):
        assert capability not in prompt, "no capability reaches a prompt"
        assert capability not in lines, "no capability reaches a log line"
        assert capability not in repr(fetched), "no capability reaches the minted record"


async def test_a_refusals_class_is_the_only_thing_the_audit_learns_of_the_file() -> None:
    """§9's field is "a member of a closed enumeration and never free text".

    The complement of the case above: a refusal *does* put a value on the record, and
    this is what pins that the value is the class and nothing beside it.
    """
    named = "salary-negotiation-with-priya.md"
    fetcher = FakeFetcher({named: "text"}, read_at=_NOW, refusals={named: FetchRefusal.TOO_LARGE})
    planner = FakePlanner(now=_clock, read_request=_file("F1"))

    with structlog.testing.capture_logs() as captured:
        await _loop(planner=planner, fetcher=fetcher).respond("q", narrow=_bounded())

    serviced = _serviced(captured)
    assert serviced["refusal"] == FetchRefusal.TOO_LARGE.value
    assert serviced["refusal"] in {member.value for member in FetchRefusal}
    assert "salary" not in repr(captured)


# --------------------------------------------------------------------------- #
# §14 item 18: nothing is written                                              #
# --------------------------------------------------------------------------- #


async def test_a_turn_that_fetched_writes_no_fetched_record_to_the_store() -> None:
    """§14 item 18, asserted over the store rather than over a writer mock.

    "A turn that fetches leaves the ``MemoryStore`` byte-for-byte as it was but for
    the ordinary capture: no fetched record is ingested, none is retrievable on a later
    turn, and its id resolves in no store." ADR-0230 §10: a fetched record "is supply
    and never a store write", and it reaches ``MemoryWriter.ingest`` at no point.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "the quarterly numbers came up last week"))
    before = {record.id for record in (await memory.search("", limit=100)).records}
    planner = FakePlanner(now=_clock, read_request=_file("F1"))

    responded = await _loop(
        planner=planner, fetcher=FakeFetcher(_ROOT, read_at=_NOW), memory=memory
    ).respond("how did the quarter go", narrow=_bounded())

    [fetched] = [one for one in responded.turn.memories if _DISTINCTIVE in one.content]
    after = (await memory.search("", limit=100)).records
    assert {record.id for record in after} == before, "the store is as it was"
    assert await memory.get(fetched.id) is None, "the minted id resolves in no store"
    assert _DISTINCTIVE not in _contents(after)


async def test_a_later_turn_retrieves_nothing_of_a_file_an_earlier_one_fetched() -> None:
    """§10's turn-scoping, read from the next turn rather than from the store.

    "Its ``id`` is minted for one turn … and no later turn reaches it." A second turn
    over the same store and the same loop, whose planner names no file, sees a supply
    with nothing of the document in it — which is the property a store assertion alone
    would leave open, since a record could be reachable through retrieval without being
    ``get``-able by the id this test happens to hold.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "the quarterly margin came up last week"))
    await memory.add(_episode("episode-1", "Ada: how did the quarter go?"))
    fetcher = FakeFetcher(_ROOT, read_at=_NOW)
    first = _loop(
        planner=FakePlanner(now=_clock, read_request=_file("F1")), fetcher=fetcher, memory=memory
    )
    await first.respond("how did the quarter go", narrow=_bounded())

    second = _loop(planner=FakePlanner(now=_clock), fetcher=fetcher, memory=memory)
    later = await second.respond("and the margin?", narrow=_bounded())

    assert _DISTINCTIVE not in _contents(later.turn.memories)


# --------------------------------------------------------------------------- #
# ADR-0223 §§1-3: the stamp is computed over the **final** supply              #
# --------------------------------------------------------------------------- #


async def test_a_fetched_record_is_in_the_supply_the_evaluation_is_taken_over() -> None:
    """ADR-0230 §7 and ADR-0223 §2: one evaluation, over the turn's final supply.

    A fetched record is ``EXTERNAL``-sourced and so
    ``rests_on_recorded_external_content`` is true of it (ADR-0230 §5) — which makes it
    a record that stamps the turn. This is the loop-level half: the evaluation is taken
    after the last servicing, so the fourth group is in the supply it ran over. The
    end-to-end half — the capture's own stamp, and the conversation asking thereafter —
    is §14 item 10's and lives in ``test_engine_capture_origin.py``.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "the quarterly numbers came up last week"))
    planner = FakePlanner(now=_clock, read_request=_file("F1"))

    responded = await _loop(
        planner=planner, fetcher=FakeFetcher(_ROOT, read_at=_NOW), memory=memory
    ).respond("how did the quarter go", narrow=_bounded())

    assert _external(planner.calls[0][2]) == [], (
        "the three groups the planner saw held nothing external"
    )
    [tainting] = _external(responded.turn.memories)
    assert _DISTINCTIVE in tainting.content, (
        "the final supply the evaluation is taken over holds the fetched record"
    )


async def test_a_control_turn_that_fetched_nothing_leaves_the_supply_unstamped() -> None:
    """The control for the case above: the mark comes from the fetch.

    Without it the assertion would pass on an implementation that stamped every turn a
    fetcher was wired into, which is exactly what a mark computed before the servicing
    could not distinguish.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "the quarterly numbers came up last week"))

    responded = await _loop(fetcher=FakeFetcher(_ROOT, read_at=_NOW), memory=memory).respond(
        "how did the quarter go", narrow=_bounded()
    )

    assert _external(responded.turn.memories) == []


# --------------------------------------------------------------------------- #
# ADR-0226 §5's failure posture, unwidened by this kind                        #
# --------------------------------------------------------------------------- #


async def test_a_refusal_before_a_failing_hop_is_recorded_beside_the_failure() -> None:
    """ADR-0230 §9's two absences, and neither of them is this turn.

    §9 says the refusal field is empty "where the fetch returned a record or where no
    ``LOCAL_FILE`` ask was made". A fetch that refused and a hop that then raised is
    neither, so the class rides on the failing record — where §5's zeroed counts say a
    *yield* was discarded and a refusal had none to discard. Dropping it would make
    this turn indistinguishable from one whose planner named no file at all.
    """
    memory = _FailingKeyedLoad(now=_clock)
    await memory.add(_belief("belief-1", "the quarterly margin", evidence=("cited-1",)))
    fetcher = FakeFetcher(
        _ROOT, read_at=_NOW, refusals={"quarterly-review.md": FetchRefusal.NOT_A_FILE}
    )
    planner = FakePlanner(now=_clock, read_request=_file_and_hop("F1", "M1"))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=planner, fetcher=fetcher, memory=memory, retrieval_limit=1
        ).respond("how did the quarter go", narrow=_bounded())

    serviced = _serviced(captured)
    assert serviced["failed"] is True, "the hop's store read raised (ADR-0226 §5)"
    assert serviced["refusal"] == FetchRefusal.NOT_A_FILE.value
    assert serviced["failed_after_read_returned"] is False, "the fetch returned no record"
    assert serviced["new"] == 0
    assert responded.turn.memories == tuple(planner.calls[0][2])


async def test_a_fetch_that_returned_before_a_failing_hop_records_the_partial_fact() -> None:
    """ADR-0226 §9's second failure field is stated over **reads**, and a fetch is one.

    "A read it had already performed had returned records when it did." The fetch came
    back with a record and the hop's keyed load then raised, so this servicing is the
    partial one §5 discards the yield of — and the record says so, rather than calling
    it a total failure. The fetched record is discarded with the rest, which is §5's
    all-or-nothing posture binding this kind exactly as it binds the other two.
    """
    memory = _FailingKeyedLoad(now=_clock)
    await memory.add(_belief("belief-1", "the quarterly margin", evidence=("cited-1",)))
    planner = FakePlanner(now=_clock, read_request=_file_and_hop("F1", "M1"))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=planner,
            fetcher=FakeFetcher(_ROOT, read_at=_NOW),
            memory=memory,
            retrieval_limit=1,
        ).respond("how did the quarter go", narrow=_bounded())

    serviced = _serviced(captured)
    assert serviced["failed"] is True
    assert serviced["failed_after_read_returned"] is True
    assert serviced["refusal"] is None, "the fetch returned a record, so there is no class"
    assert serviced["new"] == 0
    assert _DISTINCTIVE not in _contents(responded.turn.memories), (
        "§5 discards a partial read's records with the rest"
    )


class _FailingKeyedLoad(FakeMemoryStore):
    """A store whose ``get_many`` raises, so the hop fails after the fetch returned."""

    async def get_many(self, ids: Sequence[str]) -> dict[str, MemoryRecord]:
        """Raise the failure ADR-0226 §5 degrades on.

        Args:
            ids: The identifiers the hop resolved.

        Raises:
            MemoryStoreError: Always.
        """
        msg = "the store is unavailable"
        raise MemoryStoreError(msg)


# --------------------------------------------------------------------------- #
# ADR-0230 §2: nothing here composes a filesystem address                      #
# --------------------------------------------------------------------------- #


async def test_the_entry_handed_to_the_fetcher_is_the_one_the_fetcher_minted() -> None:
    """§2's containment, asserted at the one call that could break it.

    "The loop passes the fetcher an entry the fetcher itself minted, carrying the
    capability §4 requires; it never constructs a path, never joins a model-supplied
    fragment to a root, never assembles a ``SourceListingEntry`` of its own, and never
    hands a model-supplied string to any filesystem call."

    So the entry that reaches ``fetch`` must be **identical** to a member of the
    listing this turn read — which is what the fetcher's own verification would refuse
    were it otherwise, and which this asserts directly rather than through that
    refusal.
    """
    fetcher = _CapturingFetcher(_ROOT)
    planner = FakePlanner(now=_clock, read_request=_file("F2"))

    await _loop(planner=planner, fetcher=fetcher).respond("q", narrow=_bounded())

    [listing] = fetcher.produced
    [(handed_listing, entry)] = fetcher.calls
    assert handed_listing == listing, "the very listing this turn read"
    assert entry == listing.entries[1], "the entry at F2's position, unaltered"
    assert entry.handle == listing.entries[1].handle, "capability and all"


class _CapturingFetcher(_RecordingFetcher):
    """Records the listings it produced and the pair each ``fetch`` was handed."""

    def __init__(self, files: Mapping[str, str], **kwargs: Any) -> None:
        super().__init__(files, **kwargs)
        self.produced: list[SourceListing] = []
        self.calls: list[tuple[SourceListing, SourceListingEntry]] = []

    async def listing(self) -> SourceListing:
        listing = await super().listing()
        self.produced.append(listing)
        return listing

    async def fetch(self, listing: SourceListing, entry: SourceListingEntry) -> Any:
        self.calls.append((listing, entry))
        return await super().fetch(listing, entry)


async def test_a_stale_listing_is_never_carried_into_a_later_turn(tmp_path: Path) -> None:
    """§3's discipline, over a **real** fetcher and inside its own TTL.

    §14 item 7's last arm asks for two consecutive turns "whose roots have changed
    between them, with the second turn beginning **inside** ``fetch_listing_ttl`` of
    the first — the interval in which a retained listing would still verify, so the arm
    turns on §3's discipline and not on the expiry". Turn 2 renders its own listing and
    ``F1`` on turn 2 fetches turn 2's first entry.

    Run against a real ``LocalFileFetcher`` because the property is about a listing
    that would still *verify*: a fake could satisfy it by minting nothing reusable.
    """
    root = tmp_path / "documents"
    root.mkdir()
    (root / "first.md").write_text(f"turn one holds a {_DISTINCTIVE}", encoding="utf-8")
    fetcher = real_fetcher(root, listing_ttl=timedelta(hours=1))
    memory = FakeMemoryStore(now=_clock)

    first = await _loop(
        planner=FakePlanner(now=_clock, read_request=_file("F1")), fetcher=fetcher, memory=memory
    ).respond("what did I save", narrow=_bounded())
    assert _DISTINCTIVE in _contents(first.turn.memories)

    (root / "first.md").unlink()
    (root / "second.md").write_text("turn two holds something else", encoding="utf-8")
    second_planner = FakePlanner(now=_clock, read_request=_file("F1"))
    second = await _loop(planner=second_planner, fetcher=fetcher, memory=memory).respond(
        "and now", narrow=_bounded()
    )

    assert [one.name for one in second_planner.calls[0][4]] == ["second.md"]
    assert "turn two holds something else" in _contents(second.turn.memories)
    assert _DISTINCTIVE not in _contents(second.turn.memories), (
        "turn one's entries reached no fetch of turn two"
    )
