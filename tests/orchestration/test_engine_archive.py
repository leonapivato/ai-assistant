"""The never-list on a turn, the user's words per call site, and the forget cascade.

ADR-0225 §13 items 1, 7 and 14, driven through the real ``Engine`` over canonical
fakes.

**The first case is the one a later feed-back lane must consciously delete**, which
is the point of it (§13 item 1). It archives a span nothing else in the tree says,
runs a turn on each of the four shapes §13 names — routed and unrouted, spoken and
typed — and asserts the span reaches no prompt any model seam received: the router's,
the planner's, the composing stage's and the observer's. A lane that decided to feed
the archive back into a prompt cannot make it pass; it has to remove it, and removing
it is the moment the ADR §12 defers is owed.
"""

from __future__ import annotations

import json
from base64 import b64encode
from typing import TYPE_CHECKING

import pytest
from test_engine import AT, PATIENT, Harness, confirmable, tool
from test_engine_routing import _UTTERANCE, _parked, _routed_harness, _seed_belief, _token

from ai_assistant.core.errors import TranscriptArchiveError
from ai_assistant.core.types import (
    ExchangeDisposition,
    SpokenAudio,
    SpokenAudioFormat,
    TranscriptEntry,
)
from ai_assistant.orchestration.routing import RoutingStage
from ai_assistant.testing import FakeModelProvider, FakeObserver
from ai_assistant.testing.routing import FakeRoutingRecorder

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ActionPlan, CurrentContext, Goal, MemoryRecord

#: A span nothing else in this tree says, so a match anywhere is this entry's.
ARCHIVED_SPAN = "the lender was Ravensworth and the account was nine-nine-four"


def _recording() -> SpokenAudio:
    """One recording the spoken arm can be driven with, in a declared format."""
    return SpokenAudio(
        content=b64encode(b"a spoken turn").decode("ascii"),
        media_type=SpokenAudioFormat.MP4,
    )


def _entry(address: str = "seeded:1", conversation: str = "seeded") -> TranscriptEntry:
    """One archive entry carrying the distinctive span in both halves."""
    return TranscriptEntry(
        address=address,
        conversation_id=conversation,
        ordinal=1,
        occurred_at=AT,
        asked=ARCHIVED_SPAN,
        replied=ARCHIVED_SPAN,
        disposition=ExchangeDisposition.NO_ACTION_NEEDED,
    )


class RecordingPlanner:
    """A planner that plans nothing and keeps everything it was shown.

    The planner's prompt is assembled inside ``planning``; what ADR-0225 §4 is about
    is what *reaches* it, so this records the supply and the context it is handed —
    the only two channels through which an archive entry could arrive.
    """

    def __init__(self) -> None:
        self.shown: list[tuple[Goal, CurrentContext, Sequence[MemoryRecord]]] = []

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
    ) -> ActionPlan:
        from ai_assistant.core.types import ActionPlan  # noqa: PLC0415 — a fake's own import

        self.shown.append((goal, context, tuple(memories)))
        return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(), created_at=AT)


def _seen_by(harness: Harness, planner: RecordingPlanner, observer: FakeObserver) -> str:
    """Everything any model seam of this turn was shown, rendered for a substring check.

    Deliberately over-wide: it takes the *whole* recorded call rather than the prompt
    string, and the whole supply rather than a field, because §4's clause is that no
    transcript text and "no text derived from one" is rendered into any prompt — so a
    check that looked only where the text was expected would pass on the leak that
    put it somewhere else.
    """
    composing = harness.engine._composing  # the seam under assertion
    seams: list[object] = [
        planner.shown,
        observer.batches,
        getattr(composing, "_model", None) and getattr(composing._model, "calls", None),
    ]
    routing = harness.routing
    if routing is not None:
        seams.append(getattr(routing._model, "calls", None))
    return repr(seams)


# --- §13 item 1: the never-list holds on a turn ------------------------------


@pytest.mark.parametrize("spoken", [False, True], ids=["typed", "spoken"])
async def test_an_archived_span_reaches_no_prompt_on_an_unrouted_turn(spoken: bool) -> None:
    """ADR-0225 §4, and §13 item 1: the test a feed-back lane must consciously delete.

    Nothing retrieves the archive, nothing observes it, and nothing renders it into a
    prompt. That is enforced three ways — the package fence, the seam split and the
    absent embedder — and this is the behavioural assertion over all three at once.
    """
    planner = RecordingPlanner()
    observer = FakeObserver()
    harness = Harness(planner=planner, observer=observer, tools=(tool(),))
    harness.archive.hold(_entry())

    if spoken:
        await harness.engine.converse_spoken(
            _recording(), plays=(SpokenAudioFormat.MP4,), timeout=PATIENT
        )
    else:
        await harness.engine.converse("what did I say about the ledger", timeout=PATIENT)
    await harness.engine.observe()

    assert ARCHIVED_SPAN not in _seen_by(harness, planner, observer)


async def test_an_archived_span_reaches_no_prompt_on_a_routed_turn() -> None:
    """The routed arm of §13 item 1, over the seam a routed pass adds.

    A routed pass reaches no retrieval and no planner, so the seam that could leak
    here is the **router's** — the one model call a routed turn makes before it knows
    it is routed at all.
    """
    planner = RecordingPlanner()
    observer = FakeObserver()
    router = FakeModelProvider(json.dumps({"operation": "beliefs", "query": "ledger"}))
    harness = Harness(
        planner=planner,
        observer=observer,
        routing=RoutingStage(model=router, recorder=FakeRoutingRecorder()),
    )
    harness.archive.hold(_entry())

    await harness.engine.converse("what do you believe about the ledger", timeout=PATIENT)
    await harness.engine.observe()

    assert ARCHIVED_SPAN not in _seen_by(harness, planner, observer)
    assert ARCHIVED_SPAN not in repr(router.calls)


async def test_the_archive_still_holds_the_span_the_turn_never_saw() -> None:
    """The control: the entry was there to leak, so the cases above are not vacuous.

    Without this an archive that quietly failed to hold anything would satisfy every
    assertion above, which is exactly the shape of a never-list test that has stopped
    testing anything.
    """
    harness = Harness(tools=(tool(),))
    harness.archive.hold(_entry())

    await harness.engine.converse("anything at all", timeout=PATIENT)

    held = await harness.archive.entry("seeded:1")
    assert held is not None
    assert held.asked == ARCHIVED_SPAN


# --- §13 item 7: the user's words, threaded per call site --------------------


async def test_an_ordinary_turn_archives_its_goal_statement_and_no_rationale() -> None:
    """ADR-0225 §1's first case, and the whole reason ``content`` is refused.

    The archived half is the user's sentence as they typed it — not the rendering
    ``_exchange_of`` builds, which prefixes it and interleaves the model's own plan
    rationale with it.
    """
    harness = Harness(tools=(tool(),))

    await harness.engine.converse("where did I say that", timeout=PATIENT)

    held = (await harness.archive.entries())[0]
    assert held.asked == "where did I say that"
    assert "The user asked:" not in (held.asked or "")


async def test_a_routed_pass_archives_the_utterance_it_threads() -> None:
    """ADR-0225 §1's second case, at the site ADR-0197 §10 warns a lane will miss.

    A routed pass produces no ``TurnResult``, so a lane that wired routing without
    threading the utterance would archive a turn with the user's own sentence missing
    from it — a silent hole visible only to whoever reads the transcript later.
    """
    harness = Harness(
        routing=RoutingStage(
            model=FakeModelProvider(json.dumps({"operation": "beliefs", "query": "jazz"})),
            recorder=FakeRoutingRecorder(),
        )
    )

    await harness.engine.converse("what do you believe about jazz", timeout=PATIENT)

    entries = await harness.archive.entries()
    assert [one.asked for one in entries] == ["what do you believe about jazz"]


# --- §13 item 14: the record-scoped cascade and its failure path ------------


async def test_forget_discards_the_transcript_before_it_destroys_the_record() -> None:
    """ADR-0225 §5: the archive entry goes first, and the record follows."""
    harness = Harness(tools=(tool(),))
    outcome = await harness.engine.converse("where did I say that", timeout=PATIENT)
    episode = outcome.conversation_id
    assert episode is not None
    (entry,) = await harness.archive.entries()

    assert await harness.engine.forget(entry.address) is True

    assert await harness.archive.entry(entry.address) is None
    assert await harness.memory.get(entry.address) is None


async def test_forget_reaches_the_transcript_of_a_record_that_is_already_gone() -> None:
    """ADR-0225 §5: it attempts the discard whether or not a live record stands there.

    §3 keeps an entry's address valid after its episode has expired, been reclaimed or
    been destroyed, so short-circuiting on an absent memory record would make the
    transcript of an expired turn permanently unreachable by this operation — which
    is ADR-0004 §6's right made conditional on a horizon.
    """
    harness = Harness(tools=(tool(),))
    await harness.engine.converse("where did I say that", timeout=PATIENT)
    (entry,) = await harness.archive.entries()
    assert await harness.memory.delete(entry.address) is True

    assert await harness.engine.forget(entry.address) is False, "no record was destroyed"

    assert await harness.archive.entry(entry.address) is None, "and the transcript still went"


async def test_a_failed_discard_leaves_the_record_the_user_can_still_forget() -> None:
    """ADR-0225 §5, and §13 item 14's first half.

    A failure between the two leaves a record the user can still forget rather than
    text they were told was gone — which is the one residue ADR-0004 §6 cannot
    tolerate, and the reason the order is what it is.
    """
    harness = Harness(tools=(tool(),))
    await harness.engine.converse("where did I say that", timeout=PATIENT)
    (entry,) = await harness.archive.entries()
    harness.archive.fail()

    with pytest.raises(TranscriptArchiveError):
        await harness.engine.forget(entry.address)

    assert await harness.memory.get(entry.address) is not None, "the record still stands"


async def test_a_second_forget_reaches_the_entry_however_the_first_one_failed() -> None:
    """§5: a second attempt at the same id reaches the entry.

    The property that makes the failure above recoverable rather than terminal, and
    it holds even though the *record* half of the first attempt never ran.
    """
    harness = Harness(tools=(tool(),))
    await harness.engine.converse("where did I say that", timeout=PATIENT)
    (entry,) = await harness.archive.entries()
    harness.archive.fail()
    with pytest.raises(TranscriptArchiveError):
        await harness.engine.forget(entry.address)
    harness.archive = harness.archive  # the same object; the fault is cleared below
    harness.archive._failure = None  # clearing the scripted fault

    assert await harness.engine.forget(entry.address) is True

    assert await harness.archive.entry(entry.address) is None


async def test_forget_answers_about_the_record_and_not_about_the_transcript() -> None:
    """§5: the archive discard does not enter the answer.

    The question this operation answers is "was there a belief at that id", and
    reporting a destroyed transcript as a destroyed record would tell the user
    something else — and would make an adapter's exit code mean two things.
    """
    harness = Harness(tools=(tool(),))
    harness.archive.hold(_entry("orphan:1", conversation="orphan"))

    assert await harness.engine.forget("orphan:1") is False

    assert await harness.archive.entry("orphan:1") is None


async def test_a_parked_steps_resolution_archives_no_user_words() -> None:
    """ADR-0225 §1's own clause, and it is a clause rather than an absence of data.

    The parked turn is right there — :meth:`Engine._capture_resumption` is handed it,
    and passes its ``modality`` and its ``supplied_withheld`` along unchanged. What it
    does **not** pass is the user's words, because the utterance that parked was
    archived at its own address by the pass that parked, and repeating it here would
    render one sentence as though the user had said it twice.
    """
    harness = Harness(tools=(confirmable(),))
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None

    await harness.engine.resume(parked.step.confirmation.token, approved=True, timeout=PATIENT)

    # The harness's clock is frozen, so both entries share an instant and §7's
    # **address** tie-break decides the order — ordinal 1 then ordinal 2, which here
    # is the park then its resolution.
    entries = await harness.archive.entries()
    assert [one.asked for one in entries] == ["send it", None], (
        "the park says what was asked; its resolution says nothing"
    )


async def test_a_routed_parks_resolution_archives_no_user_words() -> None:
    """ADR-0225 §1's third case: the pass received no user words at all.

    A ``resume`` is handed an opaque token and a boolean, so there is nothing to
    archive — and unlike the case above, there is not even a turn in front of the
    capture point to be tempted by.
    """
    harness = _routed_harness()
    await _seed_belief(harness.memory)
    parked = await _parked(harness)

    await harness.engine.resume(_token(parked), approved=True, timeout=PATIENT)

    entries = await harness.archive.entries()
    assert [one.asked for one in entries] == [_UTTERANCE, None]
