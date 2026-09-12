"""ADR-0248's arms: the request as a value of its own, and the no-op it is.

§6's six arms and §10's first three, driven through the **real** ``Engine`` over the
canonical fakes. §6's closing clause is what fixes the shape of every case here:

> No arm may establish the no-op by constructing a turn whose ``utterance`` the test
> itself sets to the goal statement. The arms drive the production path from an
> utterance, which is the only construction under which the equality is the system's
> claim rather than the test's.

So nothing below builds a :class:`~ai_assistant.core.types.TurnResult`. Every case starts
at ``converse`` — or, on the parked path, at ``converse`` and then ``resume`` — and reads
what the archive, the episode store and the model seam were actually handed. A case that
asserted ``turn.utterance == turn.goal.statement`` over a turn it had assembled itself
would pass against an implementation that read the request off the goal, which is exactly
the implementation ADR-0248 §1 forbids.

**What "unchanged across the change" is asserted as.** Each capture-path arm pins the
*literal* the pre-decision tree produced: the archived half is the user's sentence byte
for byte, and the episode's ``content`` opens ``The user asked: <that sentence>``. Those
are the bytes ``turn.goal.statement`` produced before ADR-0248 and the bytes
``turn.utterance`` produces after it, which is §6's byte-equality stated where a reader
can check it rather than inferred from the two fields agreeing.

**The store's own arms are not here.** §10's park arms — the round trip, the settlement
clearing a fourth field, the schema upgrade and the trigger refusals — belong to
``tests/permissions/`` beside the store and the shared conformance suite.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import PATIENT, Harness, NoStepPlanner, confirmable, tool
from test_engine_parked_reads import _ASKED, _parked, _wired
from test_engine_read_envelope import _recorder
from test_engine_routing import _UTTERANCE, _routed_harness, _seed_belief, _token
from test_engine_routing import _parked as _routed_park

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import EpisodicMemory, ReadAnswerOutcome, Role, TurnResult
from ai_assistant.orchestration.loop import LearningLoop

if TYPE_CHECKING:
    from ai_assistant.core.types import TranscriptEntry

#: One sentence no other case in this tree says, so a match anywhere is this turn's. It
#: carries a quotation mark and a non-ASCII character because the composing arm is over
#: ``_quoted_span``'s rendering of it, and a plain ASCII word would leave that escaping
#: unexercised while still passing.
_SAID: Final = 'where did I leave the "café" receipt'

#: The same sentence with surrounding whitespace, for the one-normalisation arm.
_PADDED: Final = f"  \n{_SAID}\t "


async def _entries(archive: Any) -> list[TranscriptEntry]:
    """Every archive entry this engine wrote, in write order."""
    return list(await archive.entries())


async def _episodes(memory: Any) -> list[EpisodicMemory]:
    """Every captured exchange this engine's memory store holds, in write order."""
    return [record for record in await memory.export() if isinstance(record, EpisodicMemory)]


# --- §6(a) and §6(b): the two turn-carrying capture paths ---------------------


@pytest.mark.parametrize(
    "wiring",
    [{"planner": NoStepPlanner()}, {"tools": (tool(),)}],
    ids=["a-drove-no-step", "b-drove-one-step"],
)
async def test_a_turn_archives_and_renders_the_request_it_received(
    wiring: dict[str, Any],
) -> None:
    """§6's arms (a) and (b): the archived user words and the episode are unchanged.

    The two branches are the two ``_capture`` calls in ``Engine._run_turn``, and they are
    parametrised together because ADR-0248 §5 classifies them identically and the whole
    point of the pair is that they cannot drift apart: an implementation that moved one
    and left the other is the shape this case exists to catch.
    """
    harness = Harness(**wiring)

    outcome = await harness.engine.converse(_SAID, timeout=PATIENT)

    (entry,) = await _entries(harness.archive)
    assert entry.asked == _SAID, "ADR-0225 §1's first case, taken from the turn's own request"
    (episode,) = await _episodes(harness.memory)
    assert episode.content.startswith(f"The user asked: {_SAID}"), (
        "ADR-0005 §1's content and ADR-0074 §4's rendering, byte for byte what they were"
    )
    assert outcome.turn is not None
    assert outcome.turn.utterance == _SAID
    assert outcome.turn.utterance == outcome.turn.goal.outcome, (
        "§6: byte-equal on every path that carries a turn, and this turn came off the "
        "production path rather than out of this test"
    )


async def test_the_pass_normalises_once_so_the_request_and_the_statement_cannot_diverge() -> None:
    """§1: "the pass strips the text it received **once**".

    The whitespace is the observable: a lane that stripped for the goal and copied the
    raw text to the turn would leave the two fields unequal here while passing every
    case above, which is the failure §1's one-normalisation clause exists to prevent.
    Nothing downstream sees the padding either — not the archive, not the episode.
    """
    harness = Harness(planner=NoStepPlanner())

    outcome = await harness.engine.converse(_PADDED, timeout=PATIENT)

    assert outcome.turn is not None
    assert outcome.turn.utterance == _SAID
    assert outcome.turn.goal.outcome == _SAID
    (entry,) = await _entries(harness.archive)
    assert entry.asked == _SAID


# --- §6(c): the routed pass, whose utterance was already threaded -------------


async def test_a_routed_pass_still_archives_the_utterance_it_threads() -> None:
    """§6's arm (c): a routed pass "was already threaded and stays so".

    ADR-0197 §10 is the contrast that proves ADR-0248 §2's rule rather than an exception
    to it — a routed pass produces **no** ``TurnResult``, so a threaded argument is the
    only carrier available and is correct. This arm is what would fail if a lane read
    §2's "not a threaded argument" as reaching here too.
    """
    harness = _routed_harness()
    await _seed_belief(harness.memory)

    outcome = await harness.engine.converse(_UTTERANCE, timeout=PATIENT)

    assert outcome.turn is None, "a routed pass produces no turn to read words off"
    (entry,) = await _entries(harness.archive)
    assert entry.asked == _UTTERANCE


# --- §6(d): the resolution of a parked read ----------------------------------


async def test_a_parked_reads_resolution_archives_the_parked_passs_request() -> None:
    """§6's arm (d), and §3's "the value belongs to **the pass**".

    The resumed turn is assembled from durable state, so its request is the **parked**
    pass's — read off the park, which retained it for ADR-0244 §2's own reason: §8
    composes over it and would otherwise fabricate it. A lane that supplied this pass's
    words instead would archive a sentence the user never said on the turn being
    rendered.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    assert park.utterance == _ASKED, "the park retained the turn's own request (§3)"

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert outcome.turn is not None
    assert outcome.turn.utterance == _ASKED
    entries = await _entries(wired.archive)
    assert [one.asked for one in entries] == [_ASKED, _ASKED], (
        "the parking turn's entry and the resolution's, each carrying the same request "
        "— which is what this decision preserves rather than changes (§8, #2265)"
    )
    episodes = await _episodes(wired.memory)
    assert episodes[-1].content.startswith(f"The user asked: {_ASKED}")


async def test_a_park_written_without_an_utterance_falls_back_to_its_goal_statement() -> None:
    """§3's one fallback, at the only site in the system that may take it.

    A park predating ADR-0248 decodes with ``utterance`` ``None`` and stays answerable
    (ADR-0244 §15). Its resolution then renders the parked goal's outcome, which §3
    proves **is** the user's own words for every such row: it was minted by ``_goal_from``
    from the user's stripped utterance, and a park written after this decision always
    carries its own request, so the fallback can never reach an outcome minted under
    any other meaning.

    **The accessor moved and the bytes did not** (ADR-0249 §12): a converted park carries
    a ``GoalBrief``, which has no ``statement``, so the fallback reads
    ``park.goal.outcome`` — "the value is the **same bytes**", and §3's "that reading is
    exact for the whole life of the fallback" stays true.

    Reached by writing the park back without the field — which is the shape the store
    holds for a row written by an earlier release — rather than by editing the engine.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    legacy = park.model_copy(update={"utterance": None})
    assert legacy.disposition is park.disposition, "still OPEN, still answerable"
    wired.parks._records[:] = [legacy]

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert outcome.turn is not None
    assert outcome.turn.utterance == _ASKED, "the parked goal's outcome, which is those words"
    assert (await _entries(wired.archive))[-1].asked == _ASKED


# --- §6's further arm: a pass that received no user words at all --------------


async def test_the_resolution_of_a_parked_step_archives_no_user_words() -> None:
    """§6's further arm, first case, and ADR-0225 §1's own clause rather than a gap.

    The parked turn is right there, and its utterance was archived at its own address by
    the pass that parked; repeating it would render one sentence as though the user had
    said it twice.
    """
    harness = Harness(tools=(confirmable(),))
    parked = await harness.engine.converse(_SAID, timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None

    await harness.engine.resume(parked.step.confirmation.token, approved=True, timeout=PATIENT)

    assert [one.asked for one in await _entries(harness.archive)] == [_SAID, None]


async def test_a_resumption_recovered_from_durable_state_archives_no_user_words() -> None:
    """§6's further arm, second case: no turn at all, so there are no words to carry.

    The in-memory handle is dropped and the park is recovered through
    ``pending_confirmations``, which is what a restarted process does — so the resolution
    runs with ``parked.turn`` ``None`` and ``_exchange_of`` renders the answer line alone.
    """
    harness = Harness(tools=(confirmable(),))
    parked = await harness.engine.converse(_SAID, timeout=PATIENT)
    assert parked.step is not None
    harness.engine._parked.clear()

    (recovered,) = await harness.engine.pending_confirmations()
    resumed = await harness.engine.resume(recovered.token, approved=True, timeout=PATIENT)

    assert resumed.turn is None, "a recovered resume carries no live turn"
    assert [one.asked for one in await _entries(harness.archive)] == [_SAID, None]
    assert not (await _episodes(harness.memory))[-1].content.startswith("The user asked:")


async def test_the_resolution_of_a_routed_park_archives_no_user_words() -> None:
    """§6's further arm, third case, at the routed seam."""
    harness = _routed_harness()
    await _seed_belief(harness.memory)
    outcome = await _routed_park(harness)

    await harness.engine.resume(_token(outcome), approved=True, timeout=PATIENT)

    assert [one.asked for one in await _entries(harness.archive)] == [_UTTERANCE, None]


# --- §6's composing arm ------------------------------------------------------


async def test_the_composed_user_prompt_renders_the_request_under_its_heading() -> None:
    """§6's composing arm: the reader §5 moves that the archive arms do not cover.

    **The heading is a claim about the text beneath it** (§4), so the assertion is over
    the exact two lines — the heading, and ``_quoted_span``'s rendering of the request —
    rather than over a substring. Those are byte for byte the lines the pre-decision tree
    assembled, because ``_goal_from`` minted the statement from this very string.

    The production :class:`ComposingStage` assembles the prompt and the fake merely
    records it, which is ADR-0227 §7's rule about not substituting the renderer the
    assertion is about.
    """
    composing, model = _recorder()
    harness = Harness(planner=NoStepPlanner(), composing=composing)

    await harness.engine.converse(_SAID, timeout=PATIENT)

    prompt = next(one.content for one in model.calls[0].messages if one.role is Role.USER)
    assert prompt.splitlines()[:2] == [
        "The user said, in their own words:",
        f"  {json.dumps(_SAID)}",
    ]


# --- source selection: the day the goal stops being the utterance -------------
#
# Every arm above runs where the request and the goal statement are byte-equal, which is
# what §6 asks for and what makes this decision a no-op. It is also what those arms cannot
# tell apart: an implementation that kept reading `goal.statement` passes all of them. So
# the cases below drive the same production paths with the two values **deliberately
# different**, which is the property §5's table is actually about — and the state this
# tree enters the day A1 gives the goal its intended meaning.


#: What an assistant that had understood the request might make the goal say. Nothing in
#: it overlaps :data:`_SAID`, so an assertion cannot pass on a shared substring.
_INTERPRETED: Final = "locate the outstanding expense claim and file it"


async def test_every_moved_reader_takes_the_request_when_the_goal_says_something_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0248 §4 and §5, over a turn whose goal is **not** its request.

    The goal minting is replaced so the pass produces the shape A1 will produce for real:
    a turn whose ``goal.outcome`` is the assistant's reading of the user and whose
    ``utterance`` is what they actually said. Every reader §5 moves must then say the
    user's words — the archive's user half, the episode's ``content`` and the composing
    prompt's quoted span — and none of them may say the reading.

    This is the case that fails if a reader is reverted, and the reason the no-op arms
    above cannot be the whole of §10: they run where the two values agree, so they pass
    against exactly the implementation this decision replaces.

    **Only the minting is replaced**, at the one seam ADR-0228 §1 owns and A1 supersedes.
    The engine, the capture point, the archive, the episode writer and the production
    composing stage are all the real ones.
    """
    composing, model = _recorder()
    harness = Harness(planner=NoStepPlanner(), composing=composing)
    # The seam ADR-0228 §1 owns and A1 supersedes, replaced with the real minting called
    # on a reading — so the goal is genuinely built, and only its statement diverges.
    loop = harness.engine._loop
    minted = loop._goal_from
    monkeypatch.setattr(
        loop,
        "_goal_from",
        lambda _request, *, conversation_id: minted(_INTERPRETED, conversation_id=conversation_id),
    )

    outcome = await harness.engine.converse(_SAID, timeout=PATIENT)

    assert outcome.turn is not None
    assert outcome.turn.goal.outcome == _INTERPRETED, "the goal really did diverge"
    assert outcome.turn.utterance == _SAID
    (entry,) = await _entries(harness.archive)
    assert entry.asked == _SAID, "ADR-0225 §1: the user's own words, unrewritten"
    (episode,) = await _episodes(harness.memory)
    assert episode.content.startswith(f"The user asked: {_SAID}")
    assert _INTERPRETED not in episode.content
    prompt = next(one.content for one in model.calls[0].messages if one.role is Role.USER)
    assert prompt.splitlines()[:2] == [
        "The user said, in their own words:",
        f"  {json.dumps(_SAID)}",
    ], "the heading is a claim about the text beneath it (§4)"
    assert _INTERPRETED not in prompt.split("\n\n")[0]


async def test_a_park_carrying_its_own_request_is_never_read_off_its_goal() -> None:
    """ADR-0248 §3: "**No lane widens it**: not to a park that carries an ``utterance``".

    The fallback is for a park older than the field and for nothing else, so a park that
    carries one must be read from it even where its goal says something different. Driven
    by rewriting the stored row — the state A1 produces for real, where the parked goal is
    an interpretation — and asserted on the resumed turn and on what the resolution
    archived.

    Together with :func:`test_a_park_written_without_an_utterance_falls_back_to_its_goal_statement`
    this is the whole of §3's branch: one case per side, each with values that tell the two
    sides apart.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    assert park.goal is not None
    diverged = park.model_copy(
        update={
            "utterance": _SAID,
            "goal": park.goal.model_copy(update={"outcome": _INTERPRETED}),
        }
    )
    wired.parks._records[:] = [diverged]  # the row A1 produces: a park whose goal is a reading

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.turn is not None
    assert outcome.turn.goal.outcome == _INTERPRETED, "the parked goal really did diverge"
    assert outcome.turn.utterance == _SAID, "the park's own request, not its goal statement"
    assert (await _entries(wired.archive))[-1].asked == _SAID
    assert _INTERPRETED not in (await _episodes(wired.memory))[-1].content


# --- §10's first three arms --------------------------------------------------


def test_a_turn_result_cannot_be_constructed_without_a_request() -> None:
    """§1: "required with no default".

    A defaulted field would be exactly the *"second authority"* ADR-0225 §1's
    handed-to-capture clause exists to prevent — a turn whose request nobody set,
    rendering as the empty string under a heading that says the words are the user's.
    """
    with pytest.raises(ValueError, match="utterance"):
        TurnResult()  # type: ignore[call-arg]


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "], ids=["empty", "spaces", "mixed"])
async def test_a_blank_utterance_is_refused_on_the_production_path_as_it_was(blank: str) -> None:
    """§10: refused "at the same point and with the same error it is refused at today".

    The refusal moved method — ``LearningLoop._goal_from`` raised it before ADR-0248 and
    ``_request_of`` raises it now — but not its point in the pass, its class or its
    message. It is a :class:`PlanningError` rather than a ``ValidationError`` because
    this stage owes its caller an ``AssistantError`` (ADR-0026 §4), which is the whole
    reason the check is taken here rather than left to the field's own validator.
    """
    harness = Harness(planner=NoStepPlanner())

    with pytest.raises(PlanningError, match="a turn needs a non-empty utterance"):
        await harness.engine.converse(blank, timeout=PATIENT)

    assert await _entries(harness.archive) == [], "nothing was captured for a turn that never ran"


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "], ids=["empty", "spaces", "mixed"])
def test_the_field_itself_refuses_a_blank_request(blank: str) -> None:
    """§1: ``NonBlankEncodableText`` "tightened by a rejection alone" (ADR-0096 §2).

    Stated over the field rather than over the pass, because the pass's refusal is what
    a caller meets and this is what makes the type honest independently of it: a second
    producer of a ``TurnResult`` cannot put a blank where the user's words go.
    """
    with pytest.raises(ValueError, match="blank"):
        TurnResult.model_validate({"utterance": blank})


def test_the_one_normalisation_is_the_one_the_goal_is_minted_from() -> None:
    """§1, over the function that holds it.

    The behavioural arms above show the two values agreeing; this names the reason they
    must. ``_request_of`` is where the turn path strips, ``_goal_from`` takes what it
    returned and strips nothing further, and the turn is handed that same string — so
    there is no second normalisation that could come to disagree with the first, which is
    the property §6's byte-equality actually rests on.
    """
    request = LearningLoop._request_of(_PADDED)

    assert request == _SAID
    assert LearningLoop._request_of(request) == request, "normalising twice changes nothing"
