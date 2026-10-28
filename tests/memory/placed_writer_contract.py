"""Shared conformance suite for ADR-0345's write: holders, placements, labels, people.

Every ``MemoryWriter`` implementation must pass this suite beside
``memory_writer_contract.py`` (CONTRIBUTING, "Protocol conformance suites"). A concrete
test subclasses :class:`PlacedWriterContract` and overrides one fixture,
``make_placed_writer``: a factory building the writer under test over a *given* store
and policy, optionally wired with label bounds and the embedder labels are compared by
(ADR-0345 §7:3, §7:5).

The cases are ADR-0345 §15:2's, each stated on the record a write leaves, so each fails
on a writer that implements only the others: the holder rule of §3, the placed write of
§5, the record of the saying of §2:4 and §8, a future validity end (§6), labels (§7),
people (§9), and each step of §5's worked example, ending in its table.

**Holders.** A support a producer builds with no holder is given the one §2's table
gives it, by the writer: a part the user wrote is the owner's (§2:5,
:data:`~ai_assistant.core.types.OWNER_PERSON_ID`). Sam and Tom, who in the worked
example speak to a device that knows who is talking, are people their producer names
(a person holder's identifier is the channel's to establish); the staff page is a source
its evidence's details name, established.

This module is intentionally not named ``test_*`` so pytest does not collect the
abstract base directly; it is collected via a ``Test``-prefixed subclass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Protocol

import pytest

from ai_assistant.core.channel_validation import declared_input
from ai_assistant.core.errors import MemoryStoreError, MemoryStoreStaleError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Attestation,
    ChannelContext,
    ChannelIdentity,
    ClaimedAuthor,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputPart,
    LabelBounds,
    Memory,
    MemoryChange,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryLabelChange,
    MemoryMark,
    MemoryOperation,
    MemoryOperationKind,
    MemoryPlacement,
    MemoryRecord,
    MemorySource,
    MemoryStatus,
    MemorySupport,
    MemoryUpdateProposal,
    MemoryWrite,
    MemoryWriterName,
    OpenQuestionKind,
    PlacedAnswer,
    PlacedPair,
    PlacedRelation,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    ProposedCall,
    Provenance,
    QuestionPart,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedTextInput,
    SituationLabel,
    StatementPart,
    SupportDirection,
    SupportHolder,
    SupportOrigin,
    UnderstandingOmission,
    UserConfirmation,
    Validity,
    WholeTextReply,
    belief_summary,
)
from ai_assistant.testing import FakeEmbedder, FakeMemoryPolicy, FakeMemoryStore
from ai_assistant.testing.activation import ended_pass
from ai_assistant.testing.memories import (
    confirmed_support,
    inference_support,
    memory,
    message_support,
    pinned_support,
    said_support,
    sourced_support,
)
from ai_assistant.testing.parties import line_input

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import Embedder, MemoryPolicy, MemoryStore, MemoryWriter
    from ai_assistant.core.types import MemoryIngestResult

#: The write's instant, and every store's read instant unless a case moves it.
_AT: Final = datetime(2026, 10, 21, 12, tzinfo=UTC)
#: A month before it: when Ana moved to Porto, by the worked example's step 6.
_LAST_MONTH: Final = _AT - timedelta(days=30)
#: The parts' own instant: before the write, as a recorded message is.
_SAID_AT: Final = _AT - timedelta(hours=1)

_SAM: Final = SupportHolder.person("sam")
_TOM: Final = SupportHolder.person("tom")
_OWNER: Final = SupportHolder.person(OWNER_PERSON_ID)
_PAGE_ID: Final = "santa-maria-staff-page"
_PAGE: Final = SupportHolder.source(_PAGE_ID, claimed=False)

#: The composition-root numbers the label cases wire a writer with.
_BOUNDS: Final = LabelBounds(max_labels=3, max_chars=40, min_distance=0.1)


class PlacedWriterFactory(Protocol):
    """Builds the writer under test over a store and a policy, its labels optional.

    ``labels`` is the bounds and the embedder a writer compares a new label by
    (ADR-0345 §7:3, §7:5); ``None`` wires none, which every case but the label ones
    runs with.
    """

    def __call__(
        self,
        store: MemoryStore,
        policy: MemoryPolicy,
        *,
        labels: tuple[LabelBounds, Embedder] | None = None,
    ) -> MemoryWriter: ...


def _address(name: str) -> str:
    return f"activation:{name}"


def _episode(name: str, text: str = "") -> EpisodicMemory:
    """An episode the store holds, so a support pointing into it resolves (ADR-0328 §4:7)."""
    return EpisodicMemory(
        id=_address(name),
        content=text or f"what was said in {name}",
        occurred_at=_SAID_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_SAID_AT),
    )


def _forwarded(name: str, account: int) -> EpisodicMemory:
    """An episode whose one message is a forward from a claimed sender (ADR-0323 §4:10)."""
    channel = ChannelIdentity(channel_type="telegram", instance_id="line")
    # ADR-0351 §2:7: the forward's party is its sender, claimed.
    parties, messages = line_input(
        (
            RecordedInputMessage(
                text="Ana works at Santa Maria Hospital.",
                sent_at=_SAID_AT,
                forwarded_from=ClaimedAuthor(name="someone", account_id=account),
            ),
        )
    )
    return EpisodicMemory(
        id=_address(name),
        content="forwarded",
        occurred_at=_SAID_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_SAID_AT),
        processing_record=EpisodeProcessingRecord(
            activation_id=name,
            started_at=_SAID_AT,
            ended_at=_SAID_AT,
            trigger=RecordedChannelTrigger(
                target=channel,
                channel=channel,
                payload=RecordedTextInput(text="Ana works at Santa Maria Hospital."),
                context=ChannelContext(),
                reply=WholeTextReply(),
                parties=parties,
                messages=messages,
            ),
            status=ProcessingStatus.COMPLETED,
            reason=ProcessingReason.RETURNED,
            understanding_omitted=UnderstandingOmission.NOT_REACHED,
            stages=ended_pass(_SAID_AT),
        ),
    )


def _scheduled(name: str) -> EpisodicMemory:
    """An episode a marked task's occurrence started: the assistant's words and unknown.

    ADR-0351 §3:6: the parties the Task Scheduler declares for a task carrying the
    outside-content mark, so no part of its input backs anything (§7:3).
    """
    schedule = ChannelIdentity(channel_type="task_scheduler", instance_id="schedule")
    parties, _ = declared_input(schedule, carries_outside_mark=True)
    return EpisodicMemory(
        id=_address(name),
        content="checked the listing",
        occurred_at=_SAID_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_SAID_AT),
        processing_record=EpisodeProcessingRecord(
            activation_id=name,
            started_at=_SAID_AT,
            ended_at=_SAID_AT,
            trigger=RecordedChannelTrigger(
                target=schedule,
                channel=schedule,
                payload=RecordedTextInput(text="Check whether the listing is still up."),
                context=ChannelContext(),
                reply=None,
                parties=parties,
            ),
            status=ProcessingStatus.COMPLETED,
            reason=ProcessingReason.RETURNED,
            understanding_omitted=UnderstandingOmission.NOT_REACHED,
            stages=ended_pass(_SAID_AT),
        ),
    )


#: The channel the record-order cases' episodes are on, so the store numbers them.
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="owner-line")


def _on_line(name: str, *texts: str, by: SupportHolder | None = None) -> EpisodicMemory:
    """An episode on :data:`_LINE`, its trigger recording ``texts`` as the user's messages.

    The store numbers it as it inserts it (ADR-0283 §1), so the episodes a case adds in
    turn are in the record's order (ADR-0348 §3:2), whatever their clock readings say.
    ``by`` is another person whose words they are, for a case standing in for a channel
    that establishes them, which no kind does yet (ADR-0351 §3:2): each message's party
    and the input's, so a support on it is held by them (§7:1).
    """
    said = texts or (f"what was said in {name}",)
    parties, messages = line_input(
        tuple(RecordedInputMessage(text=one, sent_at=_SAID_AT) for one in said)
    )
    if by is not None:
        parties = (by,)
        messages = tuple(one.model_copy(update={"party": by}) for one in messages)
    return EpisodicMemory(
        id=_address(name),
        content=" ".join(said),
        occurred_at=_SAID_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_SAID_AT),
        processing_record=EpisodeProcessingRecord(
            activation_id=name,
            started_at=_SAID_AT,
            ended_at=_SAID_AT,
            trigger=RecordedChannelTrigger(
                target=_LINE,
                channel=_LINE,
                payload=RecordedTextInput(text=said[-1]),
                context=ChannelContext(),
                reply=WholeTextReply(),
                parties=parties,
                messages=messages,
            ),
            status=ProcessingStatus.COMPLETED,
            reason=ProcessingReason.RETURNED,
            understanding_omitted=UnderstandingOmission.NOT_REACHED,
            stages=ended_pass(_SAID_AT),
        ),
    )


def _at_message(
    name: str, message: int, *, direction: SupportDirection = SupportDirection.FOR
) -> MemorySupport:
    """A support pointing at one of ``name``'s recorded messages, the user's own."""
    support = _said(name, direction=direction)
    return support.model_copy(
        update={"points_at": InputPart(episode=_address(name), message=message)}
    )


def _kept(name: str) -> MemorySupport:
    """A person's request to keep a claim stated elsewhere: cited ``for``, backing nothing.

    ADR-0348 §2:1: "remember that" is a part that only asks to keep a claim.
    """
    return _said(name).model_copy(update={"backs_as_worded": False})


def _said(
    name: str,
    who: SupportHolder | None = None,
    *,
    about_when: datetime | None = None,
    direction: SupportDirection = SupportDirection.FOR,
) -> MemorySupport:
    """A support pointing at ``name``'s input, held by ``who``, or by the owner by rule."""
    support = said_support(_address(name), when=_SAID_AT, added_at=_SAID_AT, direction=direction)
    return support.model_copy(update={"holder": who, "about_when": about_when})


def _page(name: str, reported_by: str = _PAGE_ID) -> MemorySupport:
    """An evidence item read from a page, its source the record names (§2's table)."""
    return sourced_support(
        Attestation(reported_by=reported_by, reported_at=_SAID_AT),
        episode=_address(name),
        when=_SAID_AT,
        added_at=_SAID_AT,
    )


def _forward(name: str) -> MemorySupport:
    """A support pointing at ``name``'s one forwarded message: ``outside_input``."""
    return MemorySupport(
        points_at=InputPart(episode=_address(name), message=0),
        origin=SupportOrigin.OUTSIDE_INPUT,
        direction=SupportDirection.FOR,
        backs_as_worded=True,
        when=_SAID_AT,
        added_at=_SAID_AT,
        added_by=MemoryWriterName.OBSERVER,
    )


def _message(name: str, *, backs: bool = True) -> MemorySupport:
    """A support pointing at ``name``'s round message: the assistant's statement."""
    support = message_support(_address(name), when=_SAID_AT, added_at=_SAID_AT)
    return support.model_copy(update={"backs_as_worded": backs})


def _placed(
    proposed: Memory, *pairs: PlacedPair, answers: PlacedAnswer | None = None
) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(
        proposed=proposed,
        rationale="placed against what its producer retrieved",
        placement=MemoryPlacement(pairs=pairs, answers=answers),
    )


def _pair(stored: Memory, relation: PlacedRelation, note: str = "") -> PlacedPair:
    worded = note or f"{relation.value}: how the two relate"
    return PlacedPair(memory=stored.id, revision=stored.revision, relation=relation, note=worded)


async def _all(store: MemoryStore) -> dict[str, Memory]:
    """Every memory the store holds, live or not, by id."""
    return {one.id: one for one in await store.export() if isinstance(one, Memory)}


def _counted_holders(memory_: Memory, direction: SupportDirection) -> list[SupportHolder]:
    return [
        one.holder
        for one in memory_.counted_supports
        if one.direction is direction and one.holder is not None
    ]


class _RulingPolicy:
    """A policy ruling one fixed kind, a target or none, for the placed ruling cases."""

    def __init__(self, kind: MemoryDecisionKind) -> None:
        self._kind = kind

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
        relations: object = None,
    ) -> MemoryDecision:
        del proposal, relations
        folds = self._kind in {MemoryDecisionKind.REINFORCE, MemoryDecisionKind.SUPERSEDE}
        target = conflicts[0].id if conflicts and folds else None
        return MemoryDecision(kind=self._kind, reason="ruled", target_id=target)


class PlacedWriterContract:
    """ADR-0345's obligations on every ``MemoryWriter`` (§15:2)."""

    @pytest.fixture
    def make_placed_writer(self) -> PlacedWriterFactory:  # pragma: no cover - overridden
        raise NotImplementedError

    # --- helpers that write through the writer under test -----------------------------

    async def _world(self, *names: str) -> FakeMemoryStore:
        store = FakeMemoryStore(now=lambda: _AT)
        for name in names:
            await store.add(_episode(name))
        return store

    async def _write(
        self, make: PlacedWriterFactory, store: MemoryStore, proposal: MemoryUpdateProposal
    ) -> MemoryIngestResult:
        return await make(store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)).ingest(proposal)

    async def _hold(
        self, make: PlacedWriterFactory, store: MemoryStore, proposed: Memory, *pairs: PlacedPair
    ) -> Memory:
        """Write ``proposed`` placed against ``pairs``, and read back what it became."""
        result = await self._write(make, store, _placed(proposed, *pairs))
        assert result.record_id is not None
        return (await _all(store))[result.record_id]

    # --- §3: a memory changes only in its holder's beliefs ------------------------------

    async def test_another_holders_no_longer_true_installs_beside_and_stops_nothing(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§3:3: Tom holds nothing on the owner's memory, so nothing on it stops counting."""
        store = await self._world("owner", "tom")
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )
        porto = memory("m-porto", "Ana lives in Porto", _said("tom", _TOM))

        await self._write(
            make_placed_writer,
            store,
            _placed(porto, _pair(lisbon, PlacedRelation.NO_LONGER_TRUE)),
        )

        held = await _all(store)
        after = held["m-lisbon"]
        assert after.status is MemoryStatus.CURRENT
        assert after.holders == (_OWNER,)
        assert not any(op.kind is MemoryOperationKind.STOP_COUNTING for op in after.operations)
        assert _counted_holders(after, SupportDirection.AGAINST) == [_TOM]
        assert held["m-porto"].holders == (_TOM,)

    async def test_a_contradiction_from_another_holder_is_recorded_on_both_memories(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§3:1, §3:5: the dispute is visible from either memory."""
        store = await self._world("owner", "tom")
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-porto", "Ana lives in Porto", _said("tom", _TOM)),
                _pair(lisbon, PlacedRelation.NEVER_TRUE),
            ),
        )

        held = await _all(store)
        assert _counted_holders(held["m-lisbon"], SupportDirection.AGAINST) == [_TOM]
        assert _counted_holders(held["m-porto"], SupportDirection.AGAINST) == [_OWNER]
        assert held["m-lisbon"].status is MemoryStatus.CURRENT

    async def test_the_owners_no_longer_true_against_their_own_memory_retires_it(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§3:3, §3:4, §5:4: the owner's support stops, nothing backs it, and it ends."""
        store = await self._world("owner", "later")
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )
        porto = memory("m-porto", "Ana lives in Porto", _said("later"))

        await self._write(
            make_placed_writer, store, _placed(porto, _pair(lisbon, PlacedRelation.NO_LONGER_TRUE))
        )

        held = await _all(store)
        ended = held["m-lisbon"]
        assert ended.status is MemoryStatus.ENDED
        assert ended.is_unbacked
        stop = next(op for op in ended.operations if op.kind is MemoryOperationKind.STOP_COUNTING)
        assert stop.stops == InputPart(episode=_address("owner"))
        assert stop.cites == InputPart(episode=_address("later"))
        end = ended.operations[-1]
        assert (end.kind, end.cites, end.successor) == (
            MemoryOperationKind.END,
            InputPart(episode=_address("later")),
            "m-porto",
        )
        assert held["m-porto"].operations[0].replaces == ("m-lisbon",)

    async def test_one_of_two_holders_withdrawing_leaves_the_memory_current(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§3:4: a memory some other holder still holds stays current."""
        store = await self._world("tom", "sam", "sam-again")
        porto = await self._hold(
            make_placed_writer, store, memory("m-porto", "Ana lives in Porto", _said("tom", _TOM))
        )
        porto = await self._hold(
            make_placed_writer,
            store,
            memory("m-porto-sam", "Ana lives in Porto", _said("sam", _SAM)),
            _pair(porto, PlacedRelation.RESTATES),
        )
        assert set(porto.holders) == {_TOM, _SAM}

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-lisbon", "Ana lives in Lisbon", _said("sam-again", _SAM)),
                _pair(porto, PlacedRelation.NO_LONGER_TRUE),
            ),
        )

        after = (await _all(store))["m-porto"]
        assert after.status is MemoryStatus.CURRENT
        assert after.holders == (_TOM,)

    async def test_two_holders_backing_one_proposal_each_withdraw_and_retire_it(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§3:3, §3:4: each holder's support stops, citing that holder's own backing."""
        store = await self._world("tom", "sam", "tom-2", "sam-2")
        porto = await self._hold(
            make_placed_writer, store, memory("m-porto", "Ana lives in Porto", _said("tom", _TOM))
        )
        porto = await self._hold(
            make_placed_writer,
            store,
            memory("m-porto-sam", "Ana lives in Porto", _said("sam", _SAM)),
            _pair(porto, PlacedRelation.RESTATES),
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory(
                    "m-braga",
                    "Ana lives in Braga",
                    _said("tom-2", _TOM),
                    _said("sam-2", _SAM),
                ),
                _pair(porto, PlacedRelation.NO_LONGER_TRUE),
            ),
        )

        after = (await _all(store))["m-porto"]
        assert after.status is MemoryStatus.ENDED
        stops = {
            (op.stops, op.cites)
            for op in after.operations
            if op.kind is MemoryOperationKind.STOP_COUNTING
        }
        assert stops == {
            (InputPart(episode=_address("tom")), InputPart(episode=_address("tom-2"))),
            (InputPart(episode=_address("sam")), InputPart(episode=_address("sam-2"))),
        }

    async def test_a_claimed_author_is_never_the_same_holder_as_an_established_one(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§2:7: a forward's sender and a reporting source, one identifier, two holders."""
        store = await self._world("page")
        await store.add(_forwarded("forward", account=42))
        page = await self._hold(
            make_placed_writer,
            store,
            memory("m-page", "Ana works at Santa Maria Hospital", _page("page", reported_by="42")),
        )
        assert page.holders == (SupportHolder.source("42", claimed=False),)

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-forward", "Ana works at Santa Maria Hospital", _forward("forward")),
                _pair(page, PlacedRelation.NEVER_TRUE),
            ),
        )

        held = await _all(store)
        assert held["m-page"].status is MemoryStatus.CURRENT
        assert held["m-forward"].holders == (SupportHolder.source("42", claimed=True),)

    async def test_no_holder_a_producer_names_lets_a_part_take_an_origin_its_parties_refuse(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """ADR-0351 §7:2, §7:3: whatever holder it names, a forward is not your saying,
        and no part of a marked task's input backs anything."""
        store = await self._world()
        await store.add(_forwarded("forward", account=42))
        await store.add(_scheduled("task"))
        await store.add(_on_line("own", "Ana works at Santa Maria Hospital."))
        yours = _forward("forward").model_copy(
            update={"origin": SupportOrigin.USER_MESSAGE, "holder": _OWNER}
        )
        task = _forward("task").model_copy(
            update={
                "points_at": InputPart(episode=_address("task")),
                "holder": SupportHolder.unknown(),
            }
        )
        # ADR-0351 §7:1, §7:5: the owner's own message is the owner's, not another person's.
        toms = _at_message("own", 0).model_copy(update={"holder": _TOM})

        for support in (yours, task, toms):
            with pytest.raises(MemoryStoreError):
                await self._write(
                    make_placed_writer,
                    store,
                    _placed(memory("m-ana", "Ana works at Santa Maria Hospital", support)),
                )

        assert await _all(store) == {}

    async def test_a_part_saying_what_another_believes_is_held_by_its_sender(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§2:8: Sam saying "the user agrees" holds that belief himself; the owner's stays."""
        store = await self._world("owner")
        await store.add(_episode("sam", "The user agrees with me: Ana is in Porto now."))
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-porto", "Ana lives in Porto", _said("sam", _SAM)),
                _pair(lisbon, PlacedRelation.NO_LONGER_TRUE),
            ),
        )

        held = await _all(store)
        assert held["m-porto"].holders == (_SAM,)
        assert held["m-lisbon"].status is MemoryStatus.CURRENT
        assert held["m-lisbon"].holders == (_OWNER,)

    async def test_two_parts_under_one_identifier_are_one_holder(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§2:6: Sam's two messages are one holder, so his second ends his first."""
        store = await self._world("sam", "sam-later")
        tagus = await self._hold(
            make_placed_writer,
            store,
            memory("m-tagus", "Ana's flat overlooks the Tagus", _said("sam", _SAM)),
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory(
                    "m-no-tagus",
                    "Ana's flat no longer overlooks the Tagus",
                    _said("sam-later", _SAM),
                ),
                _pair(tagus, PlacedRelation.NO_LONGER_TRUE),
            ),
        )

        assert (await _all(store))["m-tagus"].status is MemoryStatus.ENDED

    async def test_a_partial_supporter_is_not_a_holder(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§2:10, §5's ``supports``: Sam's support counts for the memory and backs nothing."""
        store = await self._world("owner", "sam")
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-tagus", "Ana's flat overlooks the Tagus", _said("sam", _SAM)),
                _pair(lisbon, PlacedRelation.SUPPORTS),
            ),
        )

        after = (await _all(store))["m-lisbon"]
        assert after.holders == (_OWNER,)
        assert after.partial_supporters == (_SAM,)
        assert belief_summary(after, now=_AT, supports_gone=False).partial_supporters == (_SAM,)

    async def test_a_contained_from_another_holder_installs_beside(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:3: Sam's narrower claim is his own memory, and a partial support for the owner's."""
        store = await self._world("owner", "sam")
        broad = await self._hold(
            make_placed_writer,
            store,
            memory("m-broad", "Ana lives in Lisbon and teaches piano", _said("owner")),
        )

        result = await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-narrow", "Ana lives in Lisbon", _said("sam", _SAM)),
                _pair(broad, PlacedRelation.CONTAINED),
            ),
        )

        held = await _all(store)
        assert result.record_id == "m-narrow"
        assert result.folded == ()
        assert held["m-narrow"].holders == (_SAM,)
        assert held["m-broad"].partial_supporters == (_SAM,)
        assert held["m-broad"].holders == (_OWNER,)

    async def test_a_contained_adds_supports_without_raising_standing(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5's ``contained``: the owner's support on the page's memory backs nothing."""
        store = await self._world("page", "owner")
        page = await self._hold(
            make_placed_writer,
            store,
            memory("m-page", "Ana works as a nurse at Santa Maria", _page("page")),
        )
        before = page.standing

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-nurse", "Ana works as a nurse", _said("owner")),
                _pair(page, PlacedRelation.CONTAINED),
            ),
        )

        after = (await _all(store))["m-page"]
        assert after.standing is before
        assert after.partial_supporters == (_OWNER,)

    # --- §2:4, §8: the assistant's statement ------------------------------------------

    async def test_a_memory_the_assistants_statement_backs_without_both_marks_is_refused(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§2:4, §8:3: a round's message backs only a record of the saying."""
        store = await self._world("said")
        claim = memory("m-car", "X is the best car for the commute", _message("said"))

        with pytest.raises(MemoryStoreError):
            await self._write(make_placed_writer, store, _placed(claim))

        assert await _all(store) == {}
        saying = memory(
            "m-said",
            "On Oct 20 the assistant said X is the best car for the commute",
            _message("said"),
            marks=(MemoryMark.ASSISTANT_STATEMENT, MemoryMark.OCCASION),
        )
        held = await self._hold(make_placed_writer, store, saying)
        assert held.holders == (SupportHolder.statement(StatementPart.ROUND_MESSAGE),)

    async def test_a_kept_statement_ends_when_the_person_who_kept_it_withdraws(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§2:4, §8 prose: the person's request backs it, the message only cites it."""
        store = await self._world("said", "kept", "withdrawn")
        kept = await self._hold(
            make_placed_writer,
            store,
            memory(
                "m-kept",
                "X is the best car for the commute",
                _said("kept"),
                _message("said", backs=False),
                marks=(MemoryMark.ASSISTANT_STATEMENT,),
            ),
        )
        assert kept.holders == (_OWNER,)

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-not", "X is not the best car for the commute", _said("withdrawn")),
                _pair(kept, PlacedRelation.NEVER_TRUE),
            ),
        )

        assert (await _all(store))["m-kept"].status is MemoryStatus.WRONG

    async def test_a_record_of_the_saying_stays_current_under_another_holders_contradiction(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§2:3, §3: nobody's word ends a record of what was said; it stays true it was said."""
        store = await self._world("said", "owner")
        saying = await self._hold(
            make_placed_writer,
            store,
            memory(
                "m-said",
                "On Oct 20 the assistant said X is the best car",
                _message("said"),
                marks=(MemoryMark.ASSISTANT_STATEMENT, MemoryMark.OCCASION),
            ),
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-not", "The assistant never said X is the best car", _said("owner")),
                _pair(saying, PlacedRelation.NEVER_TRUE),
            ),
        )

        after = (await _all(store))["m-said"]
        assert after.status is MemoryStatus.CURRENT
        assert _counted_holders(after, SupportDirection.AGAINST) == [_OWNER]

    async def test_an_assistant_statement_memory_cites_the_message_or_is_refused(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§8:3, §12:4: the mark needs the message, and the projection cites it."""
        store = await self._world("said", "kept")
        bare = memory(
            "m-bare",
            "X is the best car for the commute",
            _said("kept"),
            marks=(MemoryMark.ASSISTANT_STATEMENT,),
        )
        with pytest.raises(MemoryStoreError):
            await self._write(make_placed_writer, store, _placed(bare))

        cited = await self._hold(
            make_placed_writer,
            store,
            memory(
                "m-cited",
                "X is the best car for the commute",
                _said("kept"),
                _message("said", backs=False),
                marks=(MemoryMark.ASSISTANT_STATEMENT,),
            ),
        )
        summary = belief_summary(cited, now=_AT, supports_gone=False)
        assert [(one.episode, one.round, one.when) for one in summary.statements] == [
            (_address("said"), "round-1", _SAID_AT)
        ]

    # --- §5: the write a placement yields -----------------------------------------------

    async def test_a_restates_that_would_raise_standing_installs_beside(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:2: the owner's word does not lift the page's wording to "you said it"."""
        store = await self._world("page", "owner")
        page = await self._hold(
            make_placed_writer, store, memory("m-page", "Ana is a nurse", _page("page"))
        )

        result = await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-owner", "Ana works as a nurse", _said("owner")),
                _pair(page, PlacedRelation.RESTATES),
            ),
        )

        held = await _all(store)
        assert result.record_id == "m-owner"
        assert held["m-page"] == page

    async def test_a_restates_at_equal_standing_folds_with_no_new_memory(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:2, §5:3: a repeat dates the memory again and makes no duplicate."""
        store = await self._world("tom", "sam")
        porto = await self._hold(
            make_placed_writer, store, memory("m-porto", "Ana lives in Porto", _said("tom", _TOM))
        )

        result = await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-again", "Ana is living in Porto", _said("sam", _SAM)),
                _pair(porto, PlacedRelation.RESTATES),
            ),
        )

        held = await _all(store)
        assert "m-again" not in held
        assert (result.record_id, result.folded) == ("m-porto", ("m-porto",))
        assert set(held["m-porto"].holders) == {_TOM, _SAM}

    async def test_an_unclear_writes_nothing_to_the_stored_memory_and_installs(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§4:3, §5's ``unclear``: a doubt loses nothing and changes nothing."""
        store = await self._world("owner", "later")
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )

        result = await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-maybe", "Ana may move", _said("later")),
                _pair(lisbon, PlacedRelation.UNCLEAR),
            ),
        )

        held = await _all(store)
        assert result.record_id == "m-maybe"
        assert held["m-lisbon"] == lisbon

    async def test_a_restates_that_folds_beside_an_unclear_installs_nothing(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:3: one disposition, a fold, and the unclear pair is left as it was."""
        store = await self._world("tom", "owner", "sam")
        porto = await self._hold(
            make_placed_writer, store, memory("m-porto", "Ana lives in Porto", _said("tom", _TOM))
        )
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lived in Lisbon", _said("owner"))
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-again", "Ana lives in Porto", _said("sam", _SAM)),
                _pair(porto, PlacedRelation.RESTATES),
                _pair(lisbon, PlacedRelation.UNCLEAR),
            ),
        )

        held = await _all(store)
        assert "m-again" not in held
        assert held["m-lisbon"] == lisbon

    async def test_a_fold_beside_a_no_longer_true_ends_the_retired_memory_naming_no_successor(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:4: the memory folded into already states what holds instead."""
        store = await self._world("owner", "owner-porto", "owner-again")
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )
        porto = await self._hold(
            make_placed_writer,
            store,
            memory("m-porto", "Ana lives in Porto", _said("owner-porto")),
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-again", "Ana lives in Porto now", _said("owner-again")),
                _pair(porto, PlacedRelation.RESTATES),
                _pair(lisbon, PlacedRelation.NO_LONGER_TRUE),
            ),
        )

        ended = (await _all(store))["m-lisbon"]
        assert ended.status is MemoryStatus.ENDED
        assert ended.operations[-1].successor is None

    async def test_a_claimed_too_much_installs_beside_a_restates_that_would_fold(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:3: a replace names the narrower memory it creates, so it is installed."""
        store = await self._world("owner", "owner-nurse", "owner-narrow")
        broad = await self._hold(
            make_placed_writer,
            store,
            memory("m-broad", "Ana is a nurse and a doctor", _said("owner")),
        )
        nurse = await self._hold(
            make_placed_writer, store, memory("m-nurse", "Ana is a nurse", _said("owner-nurse"))
        )

        result = await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-narrow", "Ana is a nurse, not a doctor", _said("owner-narrow")),
                _pair(broad, PlacedRelation.CLAIMED_TOO_MUCH),
                _pair(nurse, PlacedRelation.RESTATES),
            ),
        )

        held = await _all(store)
        assert result.record_id == "m-narrow"
        assert held["m-nurse"] == nurse
        replaced = held["m-broad"].operations[-1]
        assert (replaced.kind, replaced.successor) == (MemoryOperationKind.REPLACE, "m-narrow")

    async def test_a_holders_fold_stops_their_own_against_support(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§3:7: a holder's new word on the whole claim ends their own dispute with it."""
        store = await self._world("tom", "owner", "owner-again")
        porto = memory(
            "m-porto",
            "Ana lives in Porto",
            _said("tom", _TOM),
            _said("owner", direction=SupportDirection.AGAINST),
        )
        porto = await self._hold(make_placed_writer, store, porto)
        assert _counted_holders(porto, SupportDirection.AGAINST) == [_OWNER]

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-again", "Ana lives in Porto", _said("owner-again")),
                _pair(porto, PlacedRelation.RESTATES),
            ),
        )

        after = (await _all(store))["m-porto"]
        assert _counted_holders(after, SupportDirection.AGAINST) == []
        assert set(after.holders) == {_TOM, _OWNER}

    async def test_a_contained_fold_keeps_an_against_supports_direction(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5's ``contained``: each of the proposal's supports in its own direction."""
        store = await self._world("owner", "owner-again", "owner-doubt")
        broad = await self._hold(
            make_placed_writer,
            store,
            memory("m-broad", "Ana lives in Lisbon and teaches piano", _said("owner")),
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory(
                    "m-narrow",
                    "Ana lives in Lisbon",
                    _said("owner-again"),
                    _said("owner-doubt", direction=SupportDirection.AGAINST),
                ),
                _pair(broad, PlacedRelation.CONTAINED),
            ),
        )

        after = (await _all(store))["m-broad"]
        assert "m-narrow" not in await _all(store)
        doubt = after.support_at(InputPart(episode=_address("owner-doubt")))
        assert doubt is not None
        assert doubt.direction is SupportDirection.AGAINST
        again = after.support_at(InputPart(episode=_address("owner-again")))
        assert again is not None
        assert not again.backs_as_worded

    async def test_a_contained_fold_stops_none_of_the_holders_against_supports(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§3:7: a contained fold states only part of the claim, so it ends no dispute."""
        store = await self._world("owner", "owner-against", "owner-again")
        broad = await self._hold(
            make_placed_writer,
            store,
            memory(
                "m-broad",
                "Ana lives in Lisbon and teaches piano",
                _said("owner"),
                _said("owner-against", direction=SupportDirection.AGAINST),
            ),
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-narrow", "Ana lives in Lisbon", _said("owner-again")),
                _pair(broad, PlacedRelation.CONTAINED),
            ),
        )

        after = (await _all(store))["m-broad"]
        assert _counted_holders(after, SupportDirection.AGAINST) == [_OWNER]

    async def test_a_confirmation_on_a_memory_left_current_is_added_to_the_proposal_as_against(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§3:5, §3:8: a confirmation is added, against and backing nothing, to the dispute."""
        store = await self._world("yes", "tom")
        confirmed = await self._hold(
            make_placed_writer,
            store,
            memory(
                "m-confirmed",
                "Ana lives in Lisbon",
                confirmed_support(_address("yes"), when=_SAID_AT, added_at=_SAID_AT),
            ),
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-porto", "Ana lives in Porto", _said("tom", _TOM)),
                _pair(confirmed, PlacedRelation.NO_LONGER_TRUE),
            ),
        )

        porto = (await _all(store))["m-porto"]
        added = [one for one in porto.supports if one.origin is SupportOrigin.CONFIRMATION]
        assert [(one.direction, one.backs_as_worded) for one in added] == [
            (SupportDirection.AGAINST, False)
        ]

    async def test_an_inference_on_a_memory_left_current_is_added_to_the_proposal_as_against(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§3:8: an observer's inference goes, as ``against``, where a dispute is recorded."""
        store = await self._world("drawn", "tom")
        drawn = memory(
            "m-drawn",
            "Ana lives in Lisbon",
            inference_support(_address("drawn"), when=_SAID_AT, added_at=_SAID_AT),
            _said("drawn").model_copy(
                update={"backs_as_worded": False, "added_by": MemoryWriterName.OBSERVER}
            ),
        )
        await store.add(drawn)
        stored = (await _all(store))["m-drawn"]

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-porto", "Ana lives in Porto", _said("tom", _TOM)),
                _pair(stored, PlacedRelation.NO_LONGER_TRUE),
            ),
        )

        porto = (await _all(store))["m-porto"]
        added = [one for one in porto.supports if one.origin is SupportOrigin.OBSERVER_INFERENCE]
        assert [(one.direction, one.backs_as_worded) for one in added] == [
            (SupportDirection.AGAINST, False)
        ]

    async def test_a_backdated_correction_closes_the_end_at_its_own_about_when(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5's ``no_longer_true``: closed at the cited support's about-when (ADR-0328 §5:10)."""
        store = await self._world("owner", "later")
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory(
                    "m-porto",
                    "Ana moved to Porto last month",
                    _said("later", about_when=_LAST_MONTH),
                ),
                _pair(lisbon, PlacedRelation.NO_LONGER_TRUE),
            ),
        )

        assert (await _all(store))["m-lisbon"].validity.valid_until == _LAST_MONTH

    async def test_a_recheck_adds_no_support_and_leaves_its_memory_undisputed(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:9: the question rests on the memory's own backing, in the relation's words."""
        store = await self._world("page", "tom")
        page = await self._hold(
            make_placed_writer, store, memory("m-page", "Ana works at Santa Maria", _page("page"))
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-porto", "Ana lives in Porto", _said("tom", _TOM)),
                _pair(page, PlacedRelation.RECHECK, "she moved, so the hospital may have changed"),
            ),
        )

        after = (await _all(store))["m-page"]
        assert after.supports == page.supports
        assert after.evidence_summary.against == 0
        (question,) = after.open_questions
        assert question.kind is OpenQuestionKind.RECHECK
        assert question.asks == "she moved, so the hospital may have changed"
        assert question.rests_on == (page.supports[0].points_at,)

    async def test_a_recheck_on_a_memory_with_no_counted_backing_rests_on_what_it_carries(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:9: where nothing backs it, every support it carries."""
        store = await self._world("owner", "doubt", "tom")
        unbacked = _unbacked("m-unbacked")
        await store.add(unbacked)
        stored = (await _all(store))["m-unbacked"]

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-porto", "Ana lives in Porto", _said("tom", _TOM)),
                _pair(stored, PlacedRelation.RECHECK),
            ),
        )

        (question,) = (await _all(store))["m-unbacked"].open_questions
        assert question.rests_on == tuple(one.points_at for one in stored.supports)

    async def test_a_retiring_relation_against_an_unbacked_memory_cites_the_first_backing(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§3:4: nothing stops, nothing backs it, and its end cites the first backing support."""
        store = await self._world("owner", "doubt", "later", "later-2")
        await store.add(_unbacked("m-unbacked"))
        stored = (await _all(store))["m-unbacked"]

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-porto", "Ana lives in Porto", _said("later"), _said("later-2")),
                _pair(stored, PlacedRelation.NO_LONGER_TRUE),
            ),
        )

        end = (await _all(store))["m-unbacked"].operations[-1]
        assert (end.kind, end.cites) == (
            MemoryOperationKind.END,
            InputPart(episode=_address("later")),
        )

    async def test_an_answer_the_memory_carries_no_backing_of_leaves_the_question_open(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """ADR-0348 §4:3: open where the memory carries no backing support of the answer."""
        store = await self._world("page", "owner")
        asked = await self._asked(make_placed_writer, store)

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-aside", "Ana likes her work", _said("owner")),
                _pair(asked, PlacedRelation.INDEPENDENT),
                answers=PlacedAnswer(memory=asked.id, question="recheck-1"),
            ),
        )

        (question,) = (await _all(store))["m-page"].open_questions
        assert not question.resolved

    async def test_an_answer_resolves_the_question_citing_what_its_relation_added(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:5, §5:9: answered whether or not the proposal is installed."""
        store = await self._world("page", "owner")
        asked = await self._asked(make_placed_writer, store)

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-confirm", "Ana still works at Santa Maria", _said("owner")),
                _pair(asked, PlacedRelation.SUPPORTS),
                answers=PlacedAnswer(memory=asked.id, question="recheck-1"),
            ),
        )

        (question,) = (await _all(store))["m-page"].open_questions
        assert question.resolved_by == InputPart(episode=_address("owner"))

    async def test_an_answer_closes_its_question_on_a_support_the_memory_already_carried(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """ADR-0348 §4:3: resolved citing a backing support the memory carries, added or not.

        #3413: the owner's word already joined the memory, so the answering relation adds
        nothing there, and the question still closes on it.
        """
        store = await self._world("page", "owner")
        asked = await self._asked(make_placed_writer, store)
        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-first", "Ana still works at Santa Maria", _said("owner")),
                _pair(asked, PlacedRelation.SUPPORTS),
            ),
        )
        carried = (await _all(store))["m-page"]
        assert carried.support_at(InputPart(episode=_address("owner"))) is not None
        assert not carried.open_questions[0].resolved

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-again", "Ana works at Santa Maria this winter", _said("owner")),
                _pair(carried, PlacedRelation.SUPPORTS),
                answers=PlacedAnswer(memory=carried.id, question="recheck-1"),
            ),
        )

        after = (await _all(store))["m-page"]
        assert after.supports == carried.supports, "the relation added nothing there"
        (question,) = after.open_questions
        assert question.resolved_by == InputPart(episode=_address("owner"))

    async def test_a_recheck_on_a_memory_holding_an_open_one_writes_nothing_to_it(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """ADR-0348 §4:1: one open check per memory, so a second raises nothing (#3413)."""
        store = await self._world("page", "owner")
        asked = await self._asked(make_placed_writer, store)

        result = await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-pool", "The pool rebalances its winter slots", _said("owner")),
                _pair(asked, PlacedRelation.RECHECK, "so this relation is not needed"),
            ),
        )

        held = await _all(store)
        assert held["m-page"] == asked
        assert result.record_id == "m-pool", "the proposal is still installed"
        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-confirm", "Ana still works at Santa Maria", _said("owner")),
                _pair(asked, PlacedRelation.SUPPORTS),
                answers=PlacedAnswer(memory=asked.id, question="recheck-1"),
            ),
        )
        (question,) = (await _all(store))["m-page"].open_questions
        assert question.resolved, "the one open check closes, and none is left behind"

    async def test_a_recheck_on_a_memory_whose_check_was_answered_raises_one_again(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """ADR-0348 §4:1 reads an *open* question: a resolved one does not hold the next."""
        store = await self._world("page", "owner", "later")
        asked = await self._asked(make_placed_writer, store)
        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-confirm", "Ana still works at Santa Maria", _said("owner")),
                _pair(asked, PlacedRelation.SUPPORTS),
                answers=PlacedAnswer(memory=asked.id, question="recheck-1"),
            ),
        )
        answered = (await _all(store))["m-page"]

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-moved", "Ana is moving again", _said("later")),
                _pair(answered, PlacedRelation.RECHECK, "a new move may change the hospital"),
            ),
        )

        questions = (await _all(store))["m-page"].open_questions
        assert [one.resolved for one in questions] == [True, False]

    async def _asked(self, make: PlacedWriterFactory, store: MemoryStore) -> Memory:
        """The page's memory carrying one open recheck question."""
        await store.add(_episode("tom"))
        page = await self._hold(
            make, store, memory("m-page", "Ana works at Santa Maria", _page("page"))
        )
        await self._write(
            make,
            store,
            _placed(
                memory("m-tom", "Ana moved to Porto", _said("tom", _TOM)),
                _pair(page, PlacedRelation.RECHECK),
            ),
        )
        return (await _all(store))["m-page"]

    async def test_a_relations_note_is_on_what_it_wrote(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:7: every support a relation adds, and every operation it causes, carries its note."""
        store = await self._world("owner", "later")
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )
        note = "says she moved to Porto last month"

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-porto", "Ana lives in Porto", _said("later")),
                _pair(lisbon, PlacedRelation.NO_LONGER_TRUE, note),
            ),
        )

        after = (await _all(store))["m-lisbon"]
        added = after.support_at(InputPart(episode=_address("later")))
        assert added is not None
        assert added.note == note
        assert {op.note for op in after.operations[len(lisbon.operations) :]} == {note}

    async def test_a_stale_revision_refuses_the_whole_proposal(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§4:7: nothing written, and the result names the memory that moved."""
        store = await self._world("owner", "later")
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )
        await store.add(lisbon.model_copy(update={"marks": (MemoryMark.OCCASION,)}))
        before = await _all(store)

        result = await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-porto", "Ana lives in Porto", _said("later")),
                _pair(lisbon, PlacedRelation.NO_LONGER_TRUE),
            ),
        )

        assert (result.record_id, result.stale) == (None, ("m-lisbon",))
        assert await _all(store) == before

    async def test_a_placed_proposal_carrying_an_inference_or_a_pin_is_refused(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:10: an inference is the observer's own, a pin's support §9:6's pass's."""
        store = await self._world("owner")
        inferred = memory(
            "m-inferred",
            "Ana likes Lisbon",
            inference_support(_address("owner"), when=_SAID_AT, added_at=_SAID_AT),
            _said("owner").model_copy(
                update={"backs_as_worded": False, "added_by": MemoryWriterName.OBSERVER}
            ),
        )
        pinned = memory("m-pinned", "Ana likes Lisbon", _said("owner"), pinned_support())
        for proposed in (inferred, pinned):
            with pytest.raises(MemoryStoreError):
                await self._write(make_placed_writer, store, _placed(proposed))
        assert await _all(store) == {}

    async def test_a_floor_ruling_on_a_placed_proposal_is_final_and_any_other_fold_refused(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§4:5, §4:6: the floor's ``REJECT`` writes nothing; a fold ruling is refused."""
        store = await self._world("owner", "later")
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )
        before = await _all(store)
        proposal = _placed(
            memory("m-porto", "Ana lives in Porto", _said("later")),
            _pair(lisbon, PlacedRelation.NO_LONGER_TRUE),
        )

        rejected = await make_placed_writer(store, _RulingPolicy(MemoryDecisionKind.REJECT)).ingest(
            proposal
        )
        assert rejected.record_id is None
        with pytest.raises(MemoryStoreError):
            await make_placed_writer(store, _RulingPolicy(MemoryDecisionKind.REINFORCE)).ingest(
                proposal
            )
        assert await _all(store) == before

    # --- §6: a memory that lapses ---------------------------------------------------------

    async def test_a_create_with_a_future_validity_end_drops_out_of_live_reads_after_it(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§6:1, §6:2: created with its end, it is live before it and not after."""
        clock = [_AT]
        store = FakeMemoryStore(now=lambda: clock[0])
        await store.add(_episode("owner"))
        flight = _AT + timedelta(days=5)
        proposed = memory(
            "m-flight",
            "The user flies to Lisbon on the 5th",
            _said("owner", about_when=flight),
            validity=Validity(valid_until=flight),
        )

        await self._write(make_placed_writer, store, _placed(proposed))

        assert await store.get("m-flight") is not None
        clock[0] = flight + timedelta(hours=1)
        assert await store.get("m-flight") is None
        assert "m-flight" in await _all(store)
        unnamed = proposed.model_copy(update={"id": "m-unnamed", "supports": (_said("owner"),)})
        clock[0] = _AT
        with pytest.raises(MemoryStoreError):
            await self._write(make_placed_writer, store, _placed(unnamed))

    # --- §7: labels -----------------------------------------------------------------------

    async def test_a_near_duplicate_label_is_refused(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§7:5: not added, and the write says so, at a create and at a label write."""
        store = await self._world("owner")
        labels = (_BOUNDS, FakeEmbedder(dimensions=256))
        writer = make_placed_writer(store, FakeMemoryPolicy(), labels=labels)
        proposed = memory(
            "m-labelled",
            "The user is allergic to peanuts",
            _said("owner"),
            labels=(_label("when booking a restaurant"), _label("When booking a restaurant")),
        )

        result = await writer.ingest(_placed(proposed))

        held = (await _all(store))["m-labelled"]
        assert [one.text for one in held.labels] == ["when booking a restaurant"]
        assert result.refused_labels == ("When booking a restaurant",)
        written = await writer.write_labels(
            MemoryLabelChange(
                memory=held,
                labels=("when booking a restaurant", "WHEN booking a restaurant", "at a bakery"),
                by=MemoryWriterName.OBSERVER,
            )
        )
        assert [one.text for one in written.labels] == ["when booking a restaurant", "at a bakery"]
        assert written.refused == ("WHEN booking a restaurant",)

    async def test_a_label_records_its_episode_and_the_owners_write_names_the_owner(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§7:1, §7:8: each new label's instant, writer and suggesting episode are recorded."""
        store = await self._world("owner")
        writer = make_placed_writer(
            store, FakeMemoryPolicy(), labels=(_BOUNDS, FakeEmbedder(dimensions=256))
        )
        proposed = memory("m-plain", "The user is allergic to peanuts", _said("owner"))
        await writer.ingest(_placed(proposed))
        held = (await _all(store))["m-plain"]

        written = await writer.write_labels(
            MemoryLabelChange(
                memory=held,
                labels=("when eating out",),
                by=MemoryWriterName.OWNER,
                episode=_address("owner"),
            )
        )

        (label,) = written.labels
        assert (label.added_by, label.episode, label.added_at) == (
            MemoryWriterName.OWNER,
            _address("owner"),
            _AT,
        )
        stored = (await _all(store))["m-plain"]
        assert stored.labels == (label,)
        assert stored.supports == held.supports
        assert stored.operations == held.operations

    async def test_a_writer_wired_with_no_label_bounds_writes_no_label(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§7:3: the bounds are the composition root's, and a writer without them refuses."""
        store = await self._world("owner")
        proposed = memory(
            "m-labelled",
            "The user is allergic to peanuts",
            _said("owner"),
            labels=(_label("when eating out"),),
        )
        with pytest.raises(MemoryStoreError):
            await self._write(make_placed_writer, store, _placed(proposed))

    # --- §9: whom a memory is about -------------------------------------------------------

    async def test_people_are_named_as_the_parts_give_them_and_an_unset_field_stays_none(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§9:2-§9:5: one field each, a name a part gives, and ``None`` left unset."""
        store = FakeMemoryStore(now=lambda: _AT)
        await store.add(_episode("owner", "My sister Ana moved to Lisbon."))
        named = memory(
            "m-named",
            "Ana is the user's sister",
            _said("owner"),
            subjects=("Ana",),
            involved=(OWNER_PERSON_ID,),
        )
        held = await self._hold(make_placed_writer, store, named)
        assert (held.subjects, held.involved) == (("Ana",), (OWNER_PERSON_ID,))
        plain = await self._hold(
            make_placed_writer, store, memory("m-plain", "Ana moved", _said("owner"))
        )
        assert (plain.subjects, plain.involved) == (None, None)
        with pytest.raises(MemoryStoreError):
            await self._write(
                make_placed_writer,
                store,
                _placed(memory("m-bob", "Bob is a friend", _said("owner"), subjects=("Bob",))),
            )

    # --- round 1's findings: every write path, every revision, every label ----------------

    async def test_a_fold_takes_the_placements_meet(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """ADR-0217 §3, kept by ADR-0328 §11:9: a narrower proposal narrows its fold."""
        store = await self._world("tom", "sam")
        porto = await self._hold(
            make_placed_writer, store, memory("m-porto", "Ana lives in Porto", _said("tom", _TOM))
        )
        narrow = Placement(
            reach=PlacementReach.OWNER, set_by=PlacementSetter.PROPOSED, set_at=_SAID_AT
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-again", "Ana lives in Porto", _said("sam", _SAM), placement=narrow),
                _pair(porto, PlacedRelation.RESTATES),
            ),
        )

        assert (await _all(store))["m-porto"].placement == porto.placement.folded_with(narrow)
        assert (await _all(store))["m-porto"].placement.reach is PlacementReach.OWNER

    async def test_a_confirmed_supersede_on_a_stale_placement_writes_nothing(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§4:6, §4:7: the confirmation rule's ruling is final, but a stale read is refused."""
        store = await self._world("owner", "yes")
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )
        await store.add(lisbon.model_copy(update={"marks": (MemoryMark.OCCASION,)}))
        before = await _all(store)
        proposal = _placed(
            memory("m-porto", "Ana lives in Porto", _said("yes")),
            _pair(lisbon, PlacedRelation.NO_LONGER_TRUE),
        ).model_copy(
            update={
                "confirmation": UserConfirmation(
                    question=QuestionPart(round="round-1", part=1),
                    question_key="0" * 64,
                    confirmed_at=_AT,
                    retires=("m-lisbon",),
                )
            }
        )

        result = await make_placed_writer(
            store, _RulingPolicy(MemoryDecisionKind.SUPERSEDE)
        ).ingest(proposal)

        assert (result.record_id, result.stale) == (None, ("m-lisbon",))
        assert await _all(store) == before

    async def test_a_placed_write_is_one_atomic_batch(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:6: a memory moved between the read and the write leaves nothing written."""
        store = _MovingStore()
        for name in ("owner", "owner-2", "later"):
            await store.add(_episode(name))
        first = await self._hold(
            make_placed_writer, store, memory("m-first", "Ana lives in Lisbon", _said("owner"))
        )
        second = await self._hold(
            make_placed_writer,
            store,
            memory("m-second", "Ana lives near the Tagus", _said("owner-2")),
        )
        before = await _all(store)
        store.move_on_write = second

        result = await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-porto", "Ana lives in Porto", _said("later")),
                _pair(first, PlacedRelation.NO_LONGER_TRUE),
                _pair(second, PlacedRelation.WEAKENS),
            ),
        )

        after = await _all(store)
        assert result.stale == ("m-second",)
        assert "m-porto" not in after
        assert after["m-first"] == before["m-first"]
        (batch,) = store.batches
        assert {write.record.id for write in batch} == {"m-porto", "m-first", "m-second"}

    async def test_an_unbacked_proposal_is_refused_before_anything_is_written(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§3:2: a retiring relation cites the proposal's backing, so it must have some."""
        store = await self._world("owner", "doubt", "stored")
        stored = await self._hold(
            make_placed_writer, store, memory("m-stored", "Ana lives in Lisbon", _said("stored"))
        )
        before = await _all(store)

        with pytest.raises(MemoryStoreError):
            await self._write(
                make_placed_writer,
                store,
                _placed(_unbacked("m-unbacked"), _pair(stored, PlacedRelation.NO_LONGER_TRUE)),
            )

        assert await _all(store) == before

    async def test_an_ordinary_create_is_held_to_the_rules_on_a_create(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§6:1, §8:3, §8:4 bind every create, a proposal with no placement's included."""
        store = await self._world("owner")
        tomorrow = _AT + timedelta(days=1)
        for proposed in (
            memory(
                "m-occasion",
                "The user flew on the 21st",
                _said("owner"),
                marks=(MemoryMark.OCCASION,),
                validity=Validity(valid_until=tomorrow),
            ),
            memory(
                "m-lapse",
                "The user is in Lisbon",
                _said("owner"),
                validity=Validity(valid_until=tomorrow),
            ),
            memory("m-said", "X is best", _said("owner"), marks=(MemoryMark.ASSISTANT_STATEMENT,)),
        ):
            unplaced = MemoryUpdateProposal(proposed=proposed, rationale="unplaced")
            with pytest.raises(MemoryStoreError):
                await self._write(make_placed_writer, store, unplaced)
        assert await _all(store) == {}

    async def test_a_successor_is_held_to_the_label_bounds(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§7:7: a create carrying labels is written under the bounds, an operation's too."""
        store = await self._world("owner", "later")
        held = await self._hold(
            make_placed_writer,
            store,
            memory("m-broad", "Ana is a nurse and a doctor", _said("owner")),
        )
        before = await _all(store)
        later = _said("later")
        successor = memory(
            "m-narrow",
            "Ana is a nurse",
            later,
            labels=(_label("at work"),),
            operations=(
                MemoryOperation(
                    kind=MemoryOperationKind.CREATE,
                    cites=later.points_at,
                    at=_SAID_AT,
                    by=later.added_by,
                    replaces=("m-broad",),
                ),
            ),
        )
        against = later.model_copy(
            update={"direction": SupportDirection.AGAINST, "backs_as_worded": False}
        )
        change = MemoryChange(
            memory=held,
            operation=MemoryOperation(
                kind=MemoryOperationKind.REPLACE,
                cites=later.points_at,
                at=_AT,
                by=later.added_by,
                successor="m-narrow",
            ),
            support=against,
            successor=successor,
        )

        with pytest.raises(MemoryStoreError):
            await make_placed_writer(store, FakeMemoryPolicy()).apply(change)

        assert await _all(store) == before

    async def test_a_name_in_a_sibling_call_is_not_given_by_the_round_message(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§9:3: a round's message gives its own text, never its calls' arguments."""
        store = FakeMemoryStore(now=lambda: _AT)
        await store.add(_with_round("said", text="The weather is clear.", query="Ada"))
        proposed = memory(
            "m-ada",
            "On Oct 20 the assistant said the weather is clear",
            _message("said"),
            subjects=("Ada",),
            marks=(MemoryMark.ASSISTANT_STATEMENT, MemoryMark.OCCASION),
        )

        with pytest.raises(MemoryStoreError):
            await self._write(make_placed_writer, store, _placed(proposed))

    async def test_a_label_write_on_a_memory_another_writer_moved_is_refused(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§7:6: conditional on the revision read, even where the labels are those read."""
        store = await self._world("owner")
        writer = make_placed_writer(store, FakeMemoryPolicy(), labels=(_BOUNDS, _Embedded()))
        await writer.ingest(_placed(memory("m", "The user is allergic to peanuts", _said("owner"))))
        read = (await _all(store))["m"]
        await store.add(read.model_copy(update={"labels": (_label("a"),)}))

        with pytest.raises(MemoryStoreStaleError):
            await writer.write_labels(
                MemoryLabelChange(memory=read, labels=(), by=MemoryWriterName.OBSERVER)
            )

        assert [one.text for one in (await _all(store))["m"].labels] == ["a"]

    async def test_a_near_duplicate_is_judged_by_its_distance(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§7:5: within the bound, at it, or beyond it, by cosine distance and not by equality."""
        store = await self._world("owner")
        writer = make_placed_writer(store, FakeMemoryPolicy(), labels=(_BOUNDS, _Embedded()))
        proposed = memory(
            "m",
            "The user is allergic to peanuts",
            _said("owner"),
            labels=(_label("a"), _label("near"), _label("far")),
        )

        result = await writer.ingest(_placed(proposed))

        assert [one.text for one in (await _all(store))["m"].labels] == ["a", "far"]
        assert result.refused_labels == ("near",)
        held = (await _all(store))["m"]
        written = await writer.write_labels(
            MemoryLabelChange(
                memory=held, labels=("a", "far", "edge"), by=MemoryWriterName.OBSERVER
            )
        )
        assert written.refused == ("edge",)

    async def test_more_labels_or_a_longer_one_than_the_bounds_admit_is_refused(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§7:3: at a create and at a label write, with nothing written."""
        store = await self._world("owner")
        writer = make_placed_writer(store, FakeMemoryPolicy(), labels=(_BOUNDS, _Embedded()))
        too_many = tuple(_label(text) for text in ("a", "far", "other", "fourth"))
        too_long = (_label("x" * (_BOUNDS.max_chars + 1)),)
        for labels in (too_many, too_long):
            with pytest.raises(MemoryStoreError):
                await writer.ingest(
                    _placed(memory("m", "The user is allergic", _said("owner"), labels=labels))
                )
        assert await _all(store) == {}
        await writer.ingest(_placed(memory("m", "The user is allergic", _said("owner"))))
        held = (await _all(store))["m"]
        for texts in (("a", "far", "other", "fourth"), ("x" * (_BOUNDS.max_chars + 1),)):
            with pytest.raises(MemoryStoreError):
                await writer.write_labels(
                    MemoryLabelChange(memory=held, labels=texts, by=MemoryWriterName.OBSERVER)
                )
        assert (await _all(store))["m"] == held

    # --- round 2's findings ---------------------------------------------------------------

    async def test_a_restates_weighs_and_adds_only_the_supports_that_count(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5:2: a support the proposal stopped neither lifts the target nor is revived on it."""
        store = await self._world("page", "page-2", "owner", "doubt")
        page = await self._hold(
            make_placed_writer, store, memory("m-page", "Ana is a nurse", _page("page"))
        )
        said = _said("owner")
        doubt = _said("doubt", direction=SupportDirection.AGAINST)
        evidence = _page("page-2")
        create = MemoryOperation(
            kind=MemoryOperationKind.CREATE, cites=evidence.points_at, at=_SAID_AT, by=said.added_by
        )
        stop = MemoryOperation(
            kind=MemoryOperationKind.STOP_COUNTING,
            cites=doubt.points_at,
            at=_SAID_AT,
            by=said.added_by,
            stops=said.points_at,
        )
        proposed = memory(
            "m-again", "Ana works as a nurse", evidence, said, doubt, operations=(create, stop)
        )

        result = await self._write(
            make_placed_writer, store, _placed(proposed, _pair(page, PlacedRelation.RESTATES))
        )

        after = (await _all(store))["m-page"]
        assert result.folded == ("m-page",)
        assert after.standing is page.standing
        assert after.support_at(said.points_at) is None

    async def test_a_confirmed_supersede_creates_nothing_a_create_may_not_carry(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§8:3: the confirmation rule's ruling writes no memory the rules on a create refuse."""
        store = await self._world("owner", "yes")
        lisbon = await self._hold(
            make_placed_writer, store, memory("m-lisbon", "Ana lives in Lisbon", _said("owner"))
        )
        before = await _all(store)
        proposal = _placed(
            memory(
                "m-porto",
                "Ana lives in Porto",
                _said("yes"),
                marks=(MemoryMark.ASSISTANT_STATEMENT,),
            ),
            _pair(lisbon, PlacedRelation.NO_LONGER_TRUE),
        ).model_copy(
            update={
                "confirmation": UserConfirmation(
                    question=QuestionPart(round="round-1", part=1),
                    question_key="0" * 64,
                    confirmed_at=_AT,
                    retires=("m-lisbon",),
                )
            }
        )

        with pytest.raises(MemoryStoreError):
            await make_placed_writer(store, _RulingPolicy(MemoryDecisionKind.SUPERSEDE)).ingest(
                proposal
            )

        assert await _all(store) == before

    async def test_a_fold_keeps_the_labels_its_target_carries(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§7:6, §7:9: a fold writes no label, so the target's labels stay whole."""
        store = await self._world("tom", "sam", "owner")
        labelled = memory(
            "m-porto",
            "Ana lives in Porto",
            _said("tom", _TOM),
            labels=(_label("when visiting family"),),
        )
        await store.add(labelled)
        porto = (await _all(store))["m-porto"]

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-again", "Ana lives in Porto", _said("sam", _SAM)),
                _pair(porto, PlacedRelation.RESTATES),
            ),
        )
        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory("m-part", "Ana lives in Portugal", _said("owner")),
                _pair((await _all(store))["m-porto"], PlacedRelation.SUPPORTS),
            ),
        )

        assert (await _all(store))["m-porto"].labels == porto.labels

    async def test_an_ordinary_reinforcement_keeps_the_labels_its_target_carries(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§7:9, §10:1: an unplaced fold unions no topic and drops no label."""
        store = await self._world("owner", "owner-again")
        labelled = memory(
            "m-tea",
            "The user prefers green tea",
            _said("owner"),
            labels=(_label("when ordering drinks"),),
        )
        await store.add(labelled)
        before = (await _all(store))["m-tea"]

        result = await make_placed_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE)
        ).ingest(
            MemoryUpdateProposal(
                proposed=memory("m-again", "The user prefers green tea", _said("owner-again")),
                rationale="the same claim, again",
            )
        )

        assert result.record_id == "m-tea"
        assert (await _all(store))["m-tea"].labels == before.labels

    async def test_a_label_write_removing_labels_is_still_held_to_the_count(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§7:3: a memory carries at most the bound, whatever the write adds."""
        store = await self._world("owner")
        writer = make_placed_writer(store, FakeMemoryPolicy(), labels=(_BOUNDS, _Embedded()))
        texts = ("a", "far", "other", "fourth", "fifth")
        await store.add(
            memory(
                "m",
                "The user is allergic",
                _said("owner"),
                labels=tuple(_label(text) for text in texts),
            )
        )
        held = (await _all(store))["m"]

        with pytest.raises(MemoryStoreError):
            await writer.write_labels(
                MemoryLabelChange(memory=held, labels=texts[:4], by=MemoryWriterName.OBSERVER)
            )

        assert (await _all(store))["m"] == held

    async def test_a_retained_label_keeps_its_entry_and_every_kept_label_its_bound(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§7:1, §7:3, §7:6: a kept label keeps who added it and when; each is bounded."""
        store = await self._world("owner")
        writer = make_placed_writer(store, FakeMemoryPolicy(), labels=(_BOUNDS, _Embedded()))
        kept = SituationLabel(
            text="a", added_at=_SAID_AT, added_by=MemoryWriterName.OWNER, episode="activation:x"
        )
        overlong = _label("y" * (_BOUNDS.max_chars + 1))
        await store.add(
            memory("m", "The user is allergic", _said("owner"), labels=(kept, overlong))
        )
        held = (await _all(store))["m"]

        written = await writer.write_labels(
            MemoryLabelChange(
                memory=held, labels=("a", "far"), by=MemoryWriterName.OBSERVER, episode="e"
            )
        )

        assert written.labels[0] == kept
        assert (await _all(store))["m"].labels[0] == kept
        again = (await _all(store))["m"]
        moved = again.model_copy(update={"labels": (kept, overlong)})
        await store.add(moved)
        moved = (await _all(store))["m"]
        with pytest.raises(MemoryStoreError):
            await writer.write_labels(
                MemoryLabelChange(
                    memory=moved, labels=(overlong.text,), by=MemoryWriterName.OBSERVER
                )
            )
        assert (await _all(store))["m"] == moved

    async def test_a_malformed_embedding_refuses_the_label_write(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """An embedder's malformed vectors are the writer's error, and nothing is written."""
        store = await self._world("owner")
        await store.add(memory("m", "The user is allergic", _said("owner"), labels=(_label("a"),)))
        held = (await _all(store))["m"]

        for embedder in (_Ragged(), _Unsized()):
            writer = make_placed_writer(store, FakeMemoryPolicy(), labels=(_BOUNDS, embedder))
            with pytest.raises(MemoryStoreError):
                await writer.write_labels(
                    MemoryLabelChange(memory=held, labels=("a", "b"), by=MemoryWriterName.OBSERVER)
                )

        assert (await _all(store))["m"] == held

    async def test_a_label_at_exactly_the_distance_is_a_near_duplicate(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§7:5: "within" the distance includes it, at a distance exactly representable."""
        store = await self._world("owner")
        bounds = LabelBounds(max_labels=3, max_chars=40, min_distance=1.0)
        writer = make_placed_writer(store, FakeMemoryPolicy(), labels=(bounds, _Embedded()))
        proposed = memory(
            "m", "The user is allergic", _said("owner"), labels=(_label("a"), _label("far"))
        )

        result = await writer.ingest(_placed(proposed))

        assert result.refused_labels == ("far",)

    # --- ADR-0348 §3: a holder's newer word supersedes their older one -------------------

    async def _line(self, *episodes: EpisodicMemory) -> FakeMemoryStore:
        """A store holding ``episodes``, numbered in the order given (ADR-0283 §1)."""
        store = FakeMemoryStore(now=lambda: _AT)
        for one in episodes:
            await store.add(one)
        return store

    async def test_a_correction_leaves_its_new_memory_undisputed_by_its_holder(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """ADR-0348 §3:1 (#3403): the owner's Monday, cited against Tuesday, stops counting.

        The correction marks Monday wrong, and its own older statement, framed as
        ``against`` the new memory, stops in the same write, citing the correction: the
        new memory is not "disputed by the user", and the history keeps what was said.
        """
        store = await self._line(
            _on_line("e-monday", "My next dentist appointment is Monday at 3pm."),
            _on_line("e-tuesday", "No, it's Tuesday."),
        )
        monday = await self._hold(
            make_placed_writer,
            store,
            memory("m-monday", "The user's dentist appointment is Monday", _said("e-monday")),
        )

        await self._write(
            make_placed_writer,
            store,
            _placed(
                memory(
                    "m-tuesday",
                    "The user's dentist appointment is Tuesday",
                    _said("e-tuesday"),
                    _said("e-monday", direction=SupportDirection.AGAINST),
                ),
                _pair(monday, PlacedRelation.NEVER_TRUE, "the user corrected the day"),
            ),
        )

        held = await _all(store)
        assert held["m-monday"].status is MemoryStatus.WRONG
        tuesday = held["m-tuesday"]
        older = InputPart(episode=_address("e-monday"))
        assert tuesday.against_holders == ()
        assert tuesday.holders == (_OWNER,)
        assert tuesday.support_at(older) is not None, "stopped, not dropped"
        assert older in tuesday.stopped
        (stop,) = [one for one in tuesday.operations if one.stops == older]
        assert (stop.kind, stop.cites) == (
            MemoryOperationKind.STOP_COUNTING,
            InputPart(episode=_address("e-tuesday")),
        )

    async def test_a_restates_fold_stops_the_proposals_own_older_word_on_the_memory_it_leaves(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """ADR-0345 §3:7 on the memory the write leaves, ADR-0348 §3 (#3418).

        A restatement that cites the holder's corrected word ``against`` folds that word
        in, stopped, citing the restatement; one citing a later doubt of theirs folds it
        in counted, since newer evidence counts.
        """
        store = await self._line(
            _on_line("e-monday", "My dentist is Monday."),
            _on_line("e-tuesday", "No, it's Tuesday."),
            _on_line("e-again", "Yes, Tuesday, not Monday."),
            _on_line("e-vegetarian", "I'm vegetarian."),
            _on_line("e-still", "Still vegetarian."),
            _on_line("e-chicken", "I had chicken yesterday."),
        )
        tuesday = await self._hold(
            make_placed_writer,
            store,
            memory("m-tuesday", "The user's dentist appointment is Tuesday", _said("e-tuesday")),
        )
        vegetarian = await self._hold(
            make_placed_writer,
            store,
            memory("m-vegetarian", "The user is vegetarian", _said("e-vegetarian")),
        )

        corrected = await self._write(
            make_placed_writer,
            store,
            _placed(
                memory(
                    "m-again",
                    "The user's dentist appointment is Tuesday",
                    _said("e-again"),
                    _said("e-monday", direction=SupportDirection.AGAINST),
                ),
                _pair(tuesday, PlacedRelation.RESTATES, "the same claim"),
            ),
        )
        doubted = await self._write(
            make_placed_writer,
            store,
            _placed(
                memory(
                    "m-still",
                    "The user is vegetarian",
                    _said("e-still"),
                    _said("e-chicken", direction=SupportDirection.AGAINST),
                ),
                _pair(vegetarian, PlacedRelation.RESTATES, "the same claim"),
            ),
        )

        assert (corrected.folded, doubted.folded) == (("m-tuesday",), ("m-vegetarian",))
        held = await _all(store)
        folded = held["m-tuesday"]
        older = InputPart(episode=_address("e-monday"))
        assert folded.support_at(older) is not None, "folded in, stopped, not dropped"
        assert folded.against_holders == ()
        (stop,) = [one for one in folded.operations if one.stops == older]
        assert stop.cites == InputPart(episode=_address("e-again"))
        assert held["m-vegetarian"].against_holders == (_OWNER,), "a later doubt counts"

    async def test_a_holders_newer_doubt_keeps_counting_against_their_memory(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """ADR-0348 §3:3: a part after the holder's backing part is evidence, and counts."""
        store = await self._line(
            _on_line("e-vegetarian", "I'm vegetarian."),
            _on_line("e-chicken", "I had chicken yesterday."),
        )

        kept = await self._hold(
            make_placed_writer,
            store,
            memory(
                "m-vegetarian",
                "The user is vegetarian",
                _said("e-vegetarian"),
                _said("e-chicken", direction=SupportDirection.AGAINST),
            ),
        )

        assert kept.against_holders == (_OWNER,)
        assert kept.stopped == frozenset()

    async def test_within_one_episode_the_earlier_message_is_the_older_word(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """ADR-0348 §3:2: within an episode, an earlier part comes before a later one."""
        store = await self._line(
            _on_line("e-both", "My dentist is Monday.", "No, it's Tuesday, not Monday.")
        )

        corrected = await self._hold(
            make_placed_writer,
            store,
            memory(
                "m-tuesday",
                "The user's dentist appointment is Tuesday",
                _at_message("e-both", 1),
                _at_message("e-both", 0, direction=SupportDirection.AGAINST),
            ),
        )
        doubted = await self._hold(
            make_placed_writer,
            store,
            memory(
                "m-monday",
                "The user said their dentist is Monday",
                _at_message("e-both", 0),
                _at_message("e-both", 1, direction=SupportDirection.AGAINST),
            ),
        )

        assert corrected.against_holders == ()
        assert corrected.stopped == frozenset({InputPart(episode=_address("e-both"), message=0)})
        assert doubted.against_holders == (_OWNER,), "a later message is newer evidence"

    async def test_another_holders_older_word_keeps_counting_on_the_install(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """ADR-0348 §3:1 binds a holder's own older word alone: Sam's dispute stands."""
        store = await self._line(_on_line("e-sam", by=_SAM), _on_line("e-owner"))

        installed = await self._hold(
            make_placed_writer,
            store,
            memory(
                "m-porto",
                "Ana lives in Porto",
                _said("e-owner"),
                _said("e-sam", _SAM, direction=SupportDirection.AGAINST),
            ),
        )

        assert installed.against_holders == (_SAM,)

    async def test_parts_the_record_does_not_order_keep_counting(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """ADR-0348 §3:2: only the record's order stops a part; where it gives none, it counts.

        Two episodes on no channel carry no number the writer reads, so nothing orders
        them, and no clock reading may (ADR-0275 §4:9).
        """
        store = await self._world("earlier", "later")

        installed = await self._hold(
            make_placed_writer,
            store,
            memory(
                "m-tuesday",
                "The user's dentist appointment is Tuesday",
                _said("later"),
                _said("earlier", direction=SupportDirection.AGAINST),
            ),
        )

        assert installed.against_holders == (_OWNER,)

    # --- §5's worked example ----------------------------------------------------------------

    async def test_the_worked_example_ends_in_its_table(
        self, make_placed_writer: PlacedWriterFactory
    ) -> None:
        """§5's worked example, step by step, from the same placements, ending in its table."""
        store = await self._world("e1", "e2", "e3", "e4", "e5", "e6", "e7")
        make = make_placed_writer

        # 1. The owner: three memories, each backed by the owner.
        m1 = await self._hold(make, store, memory("M1", "Ana is the user's sister", _said("e1")))
        m2 = await self._hold(make, store, memory("M2", "Ana lives in Lisbon", _said("e1")))
        m3 = await self._hold(make, store, memory("M3", "Ana works as a nurse", _said("e1")))
        assert m1.holders == m2.holders == m3.holders == (_OWNER,)

        # 2. Sam: M4, held by Sam, supports M2: Sam is M2's partial supporter.
        m4 = await self._hold(
            make,
            store,
            memory("M4", "Ana's flat overlooks the Tagus", _said("e2", _SAM)),
            _pair(m2, PlacedRelation.SUPPORTS, "the Tagus runs through Lisbon"),
        )
        m2 = (await _all(store))["M2"]
        assert (m4.holders, m2.partial_supporters) == ((_SAM,), (_SAM,))

        # 3. The page, and the owner's "remember that": M5, held by the page alone and
        # citing the request (ADR-0348 §2:2), supports M3 and M2.
        m5 = await self._hold(
            make,
            store,
            memory("M5", "Ana works at Santa Maria Hospital", _page("e3"), _kept("e3")),
            _pair(m3, PlacedRelation.SUPPORTS, "a nurse at a hospital"),
            _pair(m2, PlacedRelation.SUPPORTS, "Santa Maria is in Lisbon"),
        )
        assert m5.holders == (_PAGE,)
        assert m5.support_at(InputPart(episode=_address("e3"))) is not None, "the request is cited"
        held = await _all(store)
        m2, m3 = held["M2"], held["M3"]

        # 4. Tom: M6, no_longer_true against M2, weakens M4, recheck on M5.
        m6 = await self._hold(
            make,
            store,
            memory("M6", "Ana lives in Porto", _said("e4", _TOM)),
            _pair(m2, PlacedRelation.NO_LONGER_TRUE, "says she moved to Porto last month"),
            _pair(m4, PlacedRelation.WEAKENS, "a flat in Porto is not by the Tagus"),
            _pair(m5, PlacedRelation.RECHECK, "she moved, so the hospital may have changed"),
        )
        held = await _all(store)
        m2, m4, m5 = held["M2"], held["M4"], held["M5"]
        assert m2.status is MemoryStatus.CURRENT
        assert _counted_holders(m2, SupportDirection.AGAINST) == [_TOM]
        assert _counted_holders(m6, SupportDirection.AGAINST) == [_OWNER]
        assert _counted_holders(m4, SupportDirection.AGAINST) == [_TOM]
        assert [one.kind for one in m5.open_questions] == [OpenQuestionKind.RECHECK]

        # 5. Sam: "Ana lives in Porto" folds into M6; the flat claim ends Sam's own M4.
        await self._write(
            make,
            store,
            _placed(
                memory("M6-sam", "Ana lives in Porto", _said("e5", _SAM)),
                _pair(m6, PlacedRelation.RESTATES, "the same claim"),
                _pair(m2, PlacedRelation.NO_LONGER_TRUE, "she moved to Porto"),
            ),
        )
        held = await _all(store)
        m2, m6 = held["M2"], held["M6"]
        await self._write(
            make,
            store,
            _placed(
                memory("M4-ended", "Ana's flat no longer overlooks the Tagus", _said("e5", _SAM)),
                _pair(held["M4"], PlacedRelation.NO_LONGER_TRUE, "the flat she had is gone"),
            ),
        )
        held = await _all(store)
        assert "M6-sam" not in held
        assert set(held["M6"].holders) == {_TOM, _SAM}
        assert held["M2"].status is MemoryStatus.CURRENT
        assert _SAM not in held["M2"].partial_supporters
        assert held["M4"].status is MemoryStatus.ENDED
        m2, m6 = held["M2"], held["M6"]

        # 6. The owner: folds into M6, ending the owner's dispute on it, and ends M2.
        await self._write(
            make,
            store,
            _placed(
                memory("M6-owner", "Ana moved to Porto", _said("e6", about_when=_LAST_MONTH)),
                _pair(m6, PlacedRelation.RESTATES, "the same claim"),
                _pair(m2, PlacedRelation.NO_LONGER_TRUE, "moved to Porto last month"),
            ),
        )
        held = await _all(store)
        assert "M6-owner" not in held
        assert _counted_holders(held["M6"], SupportDirection.AGAINST) == []
        assert held["M2"].validity.valid_until == _LAST_MONTH
        assert held["M2"].operations[-1].successor is None
        m5 = held["M5"]

        # 7. The owner: M7 is no_longer_true against M5 and answers its question.
        await self._write(
            make,
            store,
            _placed(
                memory("M7", "Ana works at São João Hospital", _said("e7")),
                _pair(m5, PlacedRelation.NO_LONGER_TRUE, "she is at São João now"),
                answers=PlacedAnswer(memory="M5", question=m5.open_questions[0].id),
            ),
        )

        held = await _all(store)
        table = {
            key: (
                set(held[key].holders),
                held[key].status,
                set(held[key].against_holders),
            )
            for key in ("M1", "M2", "M3", "M4", "M5", "M6", "M7")
        }
        assert table == {
            "M1": ({_OWNER}, MemoryStatus.CURRENT, set()),
            "M2": (set(), MemoryStatus.ENDED, {_TOM, _SAM, _OWNER}),
            "M3": ({_OWNER}, MemoryStatus.CURRENT, set()),
            "M4": (set(), MemoryStatus.ENDED, {_TOM, _SAM}),
            "M5": ({_PAGE}, MemoryStatus.CURRENT, {_OWNER}),
            "M6": ({_TOM, _SAM, _OWNER}, MemoryStatus.CURRENT, set()),
            "M7": ({_OWNER}, MemoryStatus.CURRENT, {_PAGE}),
        }
        assert held["M2"].validity.valid_until == _LAST_MONTH
        assert held["M3"].partial_supporters == (_PAGE,)
        assert all(one.resolved for one in held["M5"].open_questions)


#: The vectors :class:`_Embedded` gives each label the distance cases use: ``near`` at a
#: cosine distance of 0.05 from ``a``, ``edge`` at exactly the bound's 0.1, and ``far``
#: and ``other`` well beyond it, so a writer comparing for equality admits ``near``.
_VECTORS: Final[dict[str, tuple[float, float]]] = {
    "a": (1.0, 0.0),
    "near": (0.95, (1 - 0.95**2) ** 0.5),
    "edge": (0.9, (1 - 0.9**2) ** 0.5),
    "far": (0.0, 1.0),
    "other": (-1.0, 0.0),
    "fourth": (0.0, -1.0),
}


class _Embedded:
    """An embedder giving each label the vector :data:`_VECTORS` names, unit length."""

    @property
    def model_id(self) -> str:
        return "placed-suite-2"

    @property
    def dimensions(self) -> int:
        return 2

    async def embed(self, texts: Sequence[str]) -> list[Sequence[float]]:
        return [list(_VECTORS.get(text, (0.6, 0.8))) for text in texts]


class _Ragged(_Embedded):
    """An embedder whose vectors are of different widths."""

    async def embed(self, texts: Sequence[str]) -> list[Sequence[float]]:
        return [[1.0, 0.0] if index == 0 else [1.0] for index, _ in enumerate(texts)]


class _Unsized(_Embedded):
    """An embedder answering a vector that is no vector at all."""

    async def embed(self, texts: Sequence[str]) -> list[Sequence[float]]:
        return [[1.0, 0.0] if index == 0 else None for index, _ in enumerate(texts)]  # type: ignore[misc]  # malformed on purpose


class _MovingStore(FakeMemoryStore):
    """A store that moves one memory as the first write arrives, and records each batch."""

    def __init__(self) -> None:
        super().__init__(now=lambda: _AT)
        self.move_on_write: Memory | None = None
        self.batches: list[tuple[MemoryWrite, ...]] = []

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        moving, self.move_on_write = self.move_on_write, None
        if moving is not None:
            self.batches.append(tuple(writes))
            await self.add(moving.model_copy(update={"marks": (MemoryMark.OCCASION,)}))
        return await super().write_atomic(writes)


def _with_round(name: str, *, text: str, query: str) -> EpisodicMemory:
    """An episode whose one round says ``text`` and calls a search for ``query``."""
    base = _forwarded(name, account=1)
    record = base.processing_record
    assert record is not None
    return base.model_copy(
        update={
            "processing_record": record.model_copy(
                update={
                    "rounds": (
                        PlanningRound(
                            id="round-1",
                            recorded_at=_SAID_AT,
                            text=text,
                            calls=(
                                ProposedCall(
                                    call_id="c1", name="search_web", arguments={"query": query}
                                ),
                            ),
                        ),
                    )
                }
            )
        }
    )


def _label(text: str) -> SituationLabel:
    return SituationLabel(text=text, added_at=_SAID_AT, added_by=MemoryWriterName.REMEMBER)


def _unbacked(record_id: str) -> Memory:
    """A memory whose one backing support another support explains away (ADR-0328 §5:8)."""
    backing = _said("owner")
    doubt = _said("doubt", direction=SupportDirection.AGAINST)
    create = MemoryOperation(
        kind=MemoryOperationKind.CREATE, cites=backing.points_at, at=_SAID_AT, by=backing.added_by
    )
    stop = MemoryOperation(
        kind=MemoryOperationKind.STOP_COUNTING,
        cites=doubt.points_at,
        at=_SAID_AT,
        by=backing.added_by,
        stops=backing.points_at,
    )
    return memory(
        record_id,
        "Ana lives in Lisbon",
        backing.model_copy(update={"holder": _OWNER}),
        doubt.model_copy(update={"holder": _OWNER}),
        operations=(create, stop),
    )
