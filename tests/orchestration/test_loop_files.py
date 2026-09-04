"""The listing across the planning seam (ADR-0230 §13's Lane C2, loop side).

ADR-0230 §14's representative-input tests that are decidable **here** — where the
listing is read, projected and threaded — and no others. **Item 20** in full: the
value passed to ``Planner.plan`` is a sequence of ``ShownFile``, one per entry in
the listing's own order; no ``SourceListingEntry``, ``SourceListing``, ``token`` or
``handle`` reaches `planning` in any argument of any call; and the containment is
asserted both structurally and behaviourally, over a planner double that renders
every field of every value it receives. **Item 7**'s two arms that turn on this
lane rather than on a fetch: that a turn's two planner calls are handed the **same**
sequence, so a label's meaning is stable across them (ADR-0228 §8's deliberate
difference), and that no listing survives its turn.

Item 20's remaining clause — "``F``\\ *n* fetches the entry at position *n* of the
listing the loop holds" — and every other item of §14 turn on a fetch, a servicing,
an audit field, a ``Settings`` bound or a version move. Those are Lane C1's and Lane
C3's. **Between C2 and C3 there is no mechanism**: a ``LOCAL_FILE`` ask emitted on
one of these turns reaches no fetcher, adds no record to any supply and changes no
reply, and the cases below assert that rather than working around it.

Every case is a test over behaviour, as §14 requires: what the planner was handed,
and what a prompt assembled from it carries. Where ``listing_count`` appears it is
never the assertion — the behavioural arm is that a fetcher whose root **changed**
between two reads is not read twice, which is checkable from the sequences the
planner received and would pass on a call count that happened to be one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    ActionPlan,
    EpisodicMemory,
    FetchOutcome,
    MemorySource,
    Placement,
    PlanStep,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadRequest,
    SemanticMemory,
    ShownFile,
    SourceListing,
    SourceListingEntry,
)
from ai_assistant.orchestration import MemoryWriteStage
from ai_assistant.orchestration.disclosure import (
    BoundedAudienceSupply,
    UnboundedAudienceSupply,
)
from ai_assistant.orchestration.loop import ConversationalOperation, LearningLoop
from ai_assistant.testing import (
    FakeContextProvider,
    FakeDeferralStore,
    FakeFeedbackProcessor,
    FakeFetcher,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakePlanner,
    FakeToolRegistry,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import Fetcher, MemoryStore, Planner
    from ai_assistant.core.types import CurrentContext, Goal, MemoryRecord

_NOW: Final = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)

#: A root with three entries, so a case has positions to be wrong about.
_ROOT: Final = {
    "quarterly-review.pdf": "the margin held at 41 percent",
    "notes.md": "a note",
    "roster.txt": "who is on call",
}


def _clock() -> datetime:
    return _NOW


def _loop(
    *,
    planner: Planner | None = None,
    fetcher: Fetcher | None = None,
    memory: MemoryStore | None = None,
) -> LearningLoop:
    """A loop over canonical fakes, with the fetcher a case supplies (or none)."""
    store = memory if memory is not None else FakeMemoryStore()
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


def _file_request(entry: str = "F1") -> ReadRequest:
    """A request naming one file and nothing else (ADR-0230 §1)."""
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.LOCAL_FILE, entry=entry),))


def _belief(record_id: str, content: str, *, evidence: tuple[str, ...] = ()) -> SemanticMemory:
    """A belief, optionally citing the exchange it was drawn from."""
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


async def _revising_memory() -> FakeMemoryStore:
    """A store whose first plan's hop yields a record the supply did not hold.

    ADR-0228 §2(e) admits a revision only where the servicing added something, so a
    turn that iterates needs a belief that is retrieved and an episode that is not —
    the episodic supplement is off, so the episode arrives only through the hop.
    """
    memory = FakeMemoryStore()
    await memory.add(_belief("belief-1", "the quarterly margin", evidence=("episode-1",)))
    await memory.add(_episode("episode-1", "Ada: the margin came up in March."))
    return memory


class _RevisingPlanner(FakePlanner):
    """A fake scripted to make a turn iterate, so both calls are observable.

    A ``FakePlanner`` scripted with a ``revision`` answers a turn's second call with
    it (ADR-0228 §3); the first plan's ``read_request`` is what makes the loop service,
    and the hop's yield is what satisfies §2(e) so that a second call happens at all.
    Subclassed rather than parameterised because the revision's plan has to carry an id
    the first plan does not (ADR-0014 §2).
    """

    def __init__(self) -> None:
        super().__init__(
            now=_clock,
            read_request=ReadRequest(asks=(ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1",)),)),
            revision=ActionPlan(
                id="plan-2",
                goal_id="goal-1",
                steps=(),
                created_at=_NOW,
                rationale="answered from what the read returned",
            ),
        )


class _ChangingFetcher:
    """A ``Fetcher`` whose root differs on every ``listing()`` call.

    The behavioural instrument for ADR-0230 §3's "once per turn": a loop that read
    twice would hand its two planner calls two *different* sequences, which is
    observable from what the planner recorded and is not observable from a call
    count that happened to be one.
    """

    def __init__(self) -> None:
        self._roots = [
            {"first-read.md": "a"},
            {"second-read.md": "b"},
            {"third-read.md": "c"},
        ]
        self._inner = FakeFetcher(self._roots[0], read_at=_NOW)
        self._reads = 0

    @property
    def name(self) -> str:
        return self._inner.name

    async def listing(self) -> SourceListing:
        root = self._roots[min(self._reads, len(self._roots) - 1)]
        self._reads += 1
        return await FakeFetcher(root, read_at=_NOW).listing()

    async def fetch(
        self,
        listing: SourceListing,
        entry: SourceListingEntry,
    ) -> FetchOutcome:  # pragma: no cover
        """Lane C2 fetches nothing (ADR-0230 §13), so reaching this is the defect."""
        msg = f"no fetch is performed before Lane C3: {listing.source}, {entry.name}"
        raise AssertionError(msg)


class _RenderingPlanner:
    """A planner that renders **every field of every value** it is handed.

    ADR-0230 §14 item 20's behavioural half: the containment is a property of the
    types, so a planner doing the worst thing an implementation could do — writing
    each value it received into the prompt it assembles — must still produce a prompt
    carrying no token and no handle, because there is none on the value to disclose.
    A structural assertion alone would pass on a `ShownFile` that had grown a
    capability field nobody rendered yet.
    """

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
    ) -> ActionPlan:
        """Write everything down, then answer a plan that asks for nothing."""
        self.prompts.append(
            "\n".join(
                repr(shown.model_dump()) + repr(shown) + repr(list(shown.model_fields_set))
                for shown in files
            )
        )
        return ActionPlan(
            id=f"{goal.id}-plan",
            goal_id=goal.id,
            steps=(PlanStep(id="s1", intent="answer", capability="report_current_time"),),
            created_at=_NOW,
            rationale="answered",
        )


# --------------------------------------------------------------------------- #
# §14 item 20: the projection is positional, and no capability crosses         #
# --------------------------------------------------------------------------- #


async def test_the_planner_is_handed_one_shown_file_per_entry_in_the_listings_order() -> None:
    """§14 item 20: "one per entry in the listing's own order".

    The projection ADR-0230 §4 requires is "positional, in order, one for one, the
    whole sequence", and this is the arm that fails on any implementation projecting
    a filtered, reordered or partial one — which would put ``F``-plus-*n* on the
    planner's side and position *n* on the loop's side out of step with nothing else
    to catch it, since §2 has neither side consult the other.
    """
    fetcher = FakeFetcher(_ROOT, read_at=_NOW)
    planner = FakePlanner(now=_clock)

    await _loop(planner=planner, fetcher=fetcher).respond(
        "how did the quarter go", narrow=_bounded()
    )

    listing = await fetcher.listing()
    [call] = planner.calls
    shown = call[4]
    assert [one.name for one in shown] == [entry.name for entry in listing.entries]
    assert [one.name for one in shown] == list(_ROOT)
    assert [one.size_bytes for one in shown] == [entry.size_bytes for entry in listing.entries]


async def test_every_value_the_planner_receives_is_a_shown_file() -> None:
    """§14 item 20, asserted structurally: "the planner-facing type has no field a
    capability could sit in".

    ``ShownFile`` forbids extra fields and declares three, none of which is a handle
    or a token — so a ``SourceListingEntry`` cannot be passed here by accident, and an
    implementation that widened the projection to carry one would fail this before it
    reached a prompt.
    """
    planner = FakePlanner(now=_clock)

    await _loop(planner=planner, fetcher=FakeFetcher(_ROOT, read_at=_NOW)).respond(
        "how did the quarter go", narrow=_bounded()
    )

    [call] = planner.calls
    shown = call[4]
    assert shown, "the fixture's root holds three files"
    for one in shown:
        assert type(one) is ShownFile
        assert set(type(one).model_fields) == {"name", "size_bytes", "modified_at"}


async def test_no_token_or_handle_reaches_a_planner_that_renders_everything() -> None:
    """§14 item 20's behavioural half, over the worst implementation the seam admits.

    A planner double that writes every field of every value it receives into its own
    prompt produces a prompt "in which no token and no handle of that turn appears".
    That is ADR-0230 §4's containment stated as a property rather than as a rule the
    planner is trusted to keep, and it is why the projection exists at all.
    """
    fetcher = FakeFetcher(_ROOT, read_at=_NOW)
    listing = await fetcher.listing()
    planner = _RenderingPlanner()

    await _loop(planner=planner, fetcher=fetcher).respond(
        "how did the quarter go", narrow=_bounded()
    )

    [prompt] = planner.prompts
    assert listing.token not in prompt
    for entry in listing.entries:
        assert entry.handle not in prompt
        assert entry.name in prompt, "the names it *was* shown are there, so the arm is not vacuous"


async def test_the_loop_holds_the_listing_and_the_planner_holds_none() -> None:
    """§3: the ``SourceListing`` itself is retained in `orchestration`.

    The value that crosses is the projection; the listing — and with it the token, the
    entry handles and the ``read_at`` §4 authenticates against — is what the loop keeps
    for the fetch a later lane performs. Asserted at the seam: nothing a planner was
    handed is a ``SourceListing`` or carries one.
    """
    planner = FakePlanner(now=_clock)

    await _loop(planner=planner, fetcher=FakeFetcher(_ROOT, read_at=_NOW)).respond(
        "how did the quarter go", narrow=_bounded()
    )

    [call] = planner.calls
    for argument in call:
        assert not isinstance(argument, SourceListing)
    assert all(not isinstance(one, SourceListing) for one in call[4])


# --------------------------------------------------------------------------- #
# §3: read once per turn, the same sequence on both calls                      #
# --------------------------------------------------------------------------- #


async def test_a_turns_two_planner_calls_are_handed_the_same_sequence() -> None:
    """§3, and §14 item 7's last arm: "the same label resolves to the same entry on
    **both** planner calls of a revising turn".

    "The loop reads the listing **once per turn** … and passes the **same** sequence
    to both planner calls", so a label's meaning is stable across a turn — which is
    where this scheme differs from ADR-0226 §3's on purpose: ADR-0228 §8 lets an ``M``
    label name different records on a turn's two calls because the supply grows, and a
    listing does not.

    The fetcher's root **changes on every read**, so a loop that read twice would hand
    the two calls two different sequences. That is what makes this an assertion about
    behaviour rather than about a call count.
    """
    fetcher = _ChangingFetcher()
    planner = _RevisingPlanner()

    await _loop(planner=planner, fetcher=fetcher, memory=await _revising_memory()).respond(
        "the quarterly margin",
        narrow=_bounded(),
        operation=ConversationalOperation.CONVERSE,
    )

    first, second = planner.calls
    assert [one.name for one in first[4]] == ["first-read.md"]
    assert first[4] == second[4], "one read, one sequence, both calls"


async def test_no_listing_survives_the_turn_that_read_it() -> None:
    """§14 item 7: "no listing survives its turn", over two consecutive turns.

    §3 makes the listing this turn's: a second turn renders its own, and turn 1's
    entries reach no call of turn 2. The fetcher's root changes between the two, so a
    loop caching a listing across turns would hand turn 2 turn 1's entries — the
    implementation §15 names as the residual a turn identity on the ``Fetcher``
    contract would close.

    Both turns run inside the fake's own TTL, so the arm turns on §3's discipline and
    not on §4's expiry: a retained listing would still verify at the seam.
    """
    fetcher = _ChangingFetcher()
    planner_one = FakePlanner(now=_clock)
    planner_two = FakePlanner(now=_clock)
    memory = FakeMemoryStore()

    await _loop(planner=planner_one, fetcher=fetcher, memory=memory).respond(
        "turn one", narrow=_bounded()
    )
    await _loop(planner=planner_two, fetcher=fetcher, memory=memory).respond(
        "turn two", narrow=_bounded()
    )

    [first] = planner_one.calls
    [second] = planner_two.calls
    assert [one.name for one in first[4]] == ["first-read.md"]
    assert [one.name for one in second[4]] == ["second-read.md"]
    assert not set(first[4]) & set(second[4]), "turn 1's entries reach no call of turn 2"


# --------------------------------------------------------------------------- #
# §3: the absent cases, which are one case                                     #
# --------------------------------------------------------------------------- #


async def test_a_deployment_with_no_fetcher_shows_no_file() -> None:
    """§3: "A deployment with no ``Fetcher`` wired passes ``()``".

    Not an error, not a degradation and not an instruction to fetch a default — the
    semantically correct answer for a turn on which no file is nameable, and the state
    every deployment with no configured root is in.
    """
    planner = FakePlanner(now=_clock)

    responded = await _loop(planner=planner, fetcher=None).respond(
        "how did the quarter go", narrow=_bounded()
    )

    [call] = planner.calls
    assert call[4] == ()
    assert responded.turn.plan.read_request is None


async def test_an_empty_listing_is_the_same_case_as_no_fetcher() -> None:
    """§3: an empty listing "is the same case for the turn", carrying no further meaning.

    It "does not distinguish unconfigured, an empty root, an unreadable root or a
    failed read, and no consumer may infer which it was" — ``CurrentContext``'s own
    ruling for a ``None`` facet, applied here. So what reaches the planner is
    byte-for-byte what an unwired deployment's does.
    """
    unwired = FakePlanner(now=_clock)
    empty = FakePlanner(now=_clock)

    await _loop(planner=unwired, fetcher=None).respond("q", narrow=_bounded())
    await _loop(planner=empty, fetcher=FakeFetcher({}, read_at=_NOW)).respond(
        "q", narrow=_bounded()
    )

    assert unwired.calls[0][4] == empty.calls[0][4] == ()


# --------------------------------------------------------------------------- #
# §7: the channel scopes the servicing and never the emission                  #
# --------------------------------------------------------------------------- #


async def test_an_unbounded_audience_turn_is_still_shown_the_listing() -> None:
    """ADR-0230 §7, ADR-0226 §5: what is scoped is the **servicing**.

    "A planner on such a turn is not told; what is scoped is the servicing, so the
    trigger goes on being measured on every channel." A loop that withheld the listing
    on ``converse_spoken`` would be telling the planner — by handing it §3's "no file
    is nameable" — and would make §14 item 14's turn structurally unreachable, since a
    ``LOCAL_FILE`` ask cannot be emitted over a listing that was never shown.
    """
    planner = FakePlanner(now=_clock, read_request=_file_request())

    responded = await _loop(planner=planner, fetcher=FakeFetcher(_ROOT, read_at=_NOW)).respond(
        "how did the quarter go", narrow=_unbounded()
    )

    [call] = planner.calls
    assert [one.name for one in call[4]] == list(_ROOT)
    assert responded.turn.plan.read_request == _file_request(), "the emission is not suppressed"


# --------------------------------------------------------------------------- #
# §13: between C2 and C3 there is no mechanism                                 #
# --------------------------------------------------------------------------- #


async def test_a_local_file_ask_reaches_no_fetcher_and_changes_no_supply() -> None:
    """§13's stated intermediate state, asserted rather than assumed.

    "A C2 turn's ``LOCAL_FILE`` ask reaches no fetcher, adds no record to any supply,
    changes no reply and changes nothing a capture records." The fetch is Lane C3's, so
    this is what a merged C2 must be — and the arm that fails on a lane that reached
    across its fence to service the ask it had just taught the planner to emit.
    """
    fetcher = FakeFetcher(_ROOT, read_at=_NOW)
    planner = FakePlanner(now=_clock, read_request=_file_request())
    before = fetcher.fetch_count

    responded = await _loop(planner=planner, fetcher=fetcher).respond(
        "how did the quarter go", narrow=_bounded()
    )

    assert fetcher.fetch_count == before
    assert responded.turn.plan.read_request == _file_request()
    assert responded.turn.memories == planner.calls[0][2], "no fourth group"
    for record in responded.turn.memories:
        assert "the margin held at 41 percent" not in record.content
