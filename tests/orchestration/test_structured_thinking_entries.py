"""ADR-0355 §5, §6, §8:2: a structured call's thinking summary reaches its returned entry alone.

Each stage that writes a returned entry for a structured call, driven over the canonical
structured fake with a summary scripted on its exchange: understanding's first completion
and its repair, a digest part, and the observer's scout, framing and placement. Each case
runs the same script with the summary and without it, so a returned entry that differs by
anything but ``thinking``, or a given entry that differs at all, fails it. The repair, the
log lines and a follow-up asked of the call carry nothing of the summary.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from observer_support import (
    AT as OBSERVER_AT,
)
from observer_support import (
    SINCE,
    Harness,
    address,
    episode,
    found,
    framed,
    framing,
    placing,
    scouted,
)
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from structlog.testing import capture_logs

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.types import (
    ActivationDigest,
    ChannelContext,
    ChannelContextItem,
    ChannelIdentity,
    DiagnosticEntry,
    DiagnosticKind,
    DiagnosticSource,
    Memory,
    PlanningLabel,
    Role,
)
from ai_assistant.models.follow_up import FOLLOW_UP_PROMPT, FOLLOW_UP_ROUTES, FollowUpAsker
from ai_assistant.orchestration.digesting import (
    DIGESTING_PROMPT,
    ActivationLabels,
    DigestingStage,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.held_results import HeldResult
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    SuppliedWindow,
    UnderstandingStage,
)
from ai_assistant.testing import FakeDiagnosticSink, default_prompt
from ai_assistant.testing.memories import memory, said_support
from ai_assistant.testing.structured import FakeStructuredCompleter, ScriptedReply

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model

    from ai_assistant.core.protocols import DiagnosticSink

_AT: Final = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
_ACTIVATION: Final = "a-0"
_EVENTS: Final = ChannelIdentity(channel_type="informational_event", instance_id="parks")
_WINDOW: Final = SuppliedWindow(ChannelContext(history=(ChannelContextItem(text="Trip plans"),)))

#: Two summaries no prompt, reply or record holds, so finding either anywhere is a leak.
_FIRST_THOUGHT: Final = "Weighing whether the closure is about the trip zq-first-7731."
_SECOND_THOUGHT: Final = "On the repair the label H1 fits zq-second-4402."
_THOUGHTS: Final = (_FIRST_THOUGHT, _SECOND_THOUGHT)

_CLAIM: Final = "The user prefers window seats."


def _body(entry: DiagnosticEntry) -> dict[str, Any]:
    """An entry's body as plain JSON, as its line in the file holds it."""
    body: dict[str, Any] = json.loads(entry.model_dump_json())["body"]
    return body


def _bodies(sink: FakeDiagnosticSink, source: DiagnosticSource, kind: DiagnosticKind) -> list[Any]:
    return [_body(one) for one in sink.of(source, kind)]


def _without_thinking(bodies: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in one.items() if key != "thinking"} for one in bodies]


def _leaks(held: object) -> list[str]:
    """Each scripted summary found anywhere in ``held``, rendered as text."""
    text = repr(held)
    return [one for one in _THOUGHTS if one in text]


def _thinking(text: str, summary: str | None) -> ScriptedReply:
    return ScriptedReply(text=text, thinking=summary)


# --- understanding ---------------------------------------------------------------------------


def _proposal(**fields: Any) -> str:
    return json.dumps({"understanding": "A park closed."} | fields)


async def _understand(model: FakeStructuredCompleter, sink: DiagnosticSink) -> None:
    stage = UnderstandingStage(
        model=model,
        excerpt_chars=2000,
        prompt=default_prompt(UNDERSTANDING_PROMPT),
        diagnostics=sink,
    )
    with diagnosed_activation(_ACTIVATION, clock=lambda: _AT):
        await stage.understand(
            "Riverside is closed.",
            channel=_EVENTS,
            window=_WINDOW,
            audience=BoundedAudienceSupply(speakable_attested_sources=frozenset()),
            episodes=None,
            version=1,
            now=lambda: _AT,
            deadline=asyncio.get_running_loop().time() + 60,
        )


def _repairing(first: str | None, second: str | None) -> FakeStructuredCompleter:
    """A first reply whose label resolves to nothing, then its repair, each with a summary."""
    return FakeStructuredCompleter.scripted(
        _thinking(_proposal(cites=["H9"]), first), _thinking(_proposal(cites=["H1"]), second)
    )


async def test_understandings_first_completion_and_repair_each_keep_their_summary() -> None:
    """§5:1, §6:1: each returned entry carries its own call's summary under ``thinking``."""
    sink = FakeDiagnosticSink()

    await _understand(_repairing(_FIRST_THOUGHT, _SECOND_THOUGHT), sink)

    first, repair = _bodies(sink, DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED)
    assert (first["thinking"], repair["thinking"]) == (_FIRST_THOUGHT, _SECOND_THOUGHT)


async def test_understanding_writes_no_thinking_key_where_the_exchange_holds_none() -> None:
    """§5:1: no key where the exchange's ``thinking`` is ``None``, one where only one has it."""
    sink = FakeDiagnosticSink()

    await _understand(_repairing(None, _SECOND_THOUGHT), sink)

    first, repair = _bodies(sink, DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED)
    assert "thinking" not in first
    assert repair["thinking"] == _SECOND_THOUGHT


async def test_understandings_entries_differ_by_the_thinking_key_alone() -> None:
    """§5:5: the given entries are as they are without a summary; the returned add one key."""
    kept, plain = FakeDiagnosticSink(), FakeDiagnosticSink()

    await _understand(_repairing(_FIRST_THOUGHT, _SECOND_THOUGHT), kept)
    await _understand(_repairing(None, None), plain)

    given = (DiagnosticSource.UNDERSTANDING, DiagnosticKind.GIVEN)
    returned = (DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED)
    assert _bodies(kept, *given) == _bodies(plain, *given)
    assert len(_bodies(kept, *given)) == 2
    assert not _leaks(_bodies(kept, *given))
    assert _without_thinking(_bodies(kept, *returned)) == _bodies(plain, *returned)


async def test_understandings_repair_carries_the_first_reply_and_nothing_of_its_thinking() -> None:
    """§5:2, ADR-0354 §8:3: the assistant turn is the first reply's text alone."""
    model = _repairing(_FIRST_THOUGHT, _SECOND_THOUGHT)

    await _understand(model, FakeDiagnosticSink())

    first, repair = model.calls
    assert not _leaks(first.messages)
    assert not _leaks(repair.messages)
    turn = repair.messages[len(first.messages)]
    assert (turn.role, turn.content) == (Role.ASSISTANT, _proposal(cites=["H9"]))


async def test_no_log_line_understanding_writes_carries_a_summary() -> None:
    """§5:3: the repair's log line, and any other, carries no summary's text."""
    with capture_logs() as logs:
        await _understand(_repairing(_FIRST_THOUGHT, _SECOND_THOUGHT), FakeDiagnosticSink())

    assert any(one["event"] == "understanding_repair" for one in logs)
    assert not _leaks(logs)


# --- digesting -------------------------------------------------------------------------------


class _DigestRecorder:
    async def record(self, digest: ActivationDigest, labels: tuple[PlanningLabel, ...]) -> None:
        del digest, labels


_HELD: Final = HeldResult(
    result_id="result:1", round_id="r1", decision_id="d1", content="The loop closes on the 15th."
)
_DIGEST_REPLY: Final = json.dumps({"evidence": [{"text": "closes on the 15th", "source": "D1"}]})


async def _digest(summary: str | None, sink: DiagnosticSink) -> FakeStructuredCompleter:
    model = FakeStructuredCompleter(_thinking(_DIGEST_REPLY, summary))
    stage = DigestingStage(
        provider=model,
        recorder=_DigestRecorder(),
        part_chars=10_000,
        now=lambda: _AT,
        diagnostics=sink,
        prompt=default_prompt(DIGESTING_PROMPT),
    )
    with diagnosed_activation(_ACTIVATION, clock=lambda: _AT):
        await stage.digest_result(
            _HELD, question="when", labels=ActivationLabels(), deadline=_AT + timedelta(seconds=30)
        )
    return model


async def test_a_digest_part_keeps_its_summary_and_its_entries_differ_by_that_key_alone() -> None:
    """§5:1, §5:5, §6:1: a part's returned entry carries ``thinking``; its given is unchanged."""
    kept, plain = FakeDiagnosticSink(), FakeDiagnosticSink()

    with capture_logs() as logs:
        model = await _digest(_FIRST_THOUGHT, kept)
    await _digest(None, plain)

    given = (DiagnosticSource.DIGESTING, DiagnosticKind.GIVEN)
    returned = (DiagnosticSource.DIGESTING, DiagnosticKind.RETURNED)
    (with_summary,) = _bodies(kept, *returned)
    (without,) = _bodies(plain, *returned)
    assert with_summary["thinking"] == _FIRST_THOUGHT
    assert "thinking" not in without
    assert _without_thinking([with_summary]) == [without]
    assert _bodies(kept, *given) == _bodies(plain, *given)
    assert not _leaks(_bodies(kept, *given))
    assert not _leaks(model.last_call.messages)
    assert not _leaks(logs)


# --- the observer ----------------------------------------------------------------------------


async def _observe(
    *, scout: str | None, framing_thought: str | None, placement: str | None
) -> tuple[FakeDiagnosticSink, FakeStructuredCompleter, FakeStructuredCompleter, list[Any]]:
    """One processed episode whose finding is framed and placed against a stored memory."""
    harness = Harness()
    await harness.hold(
        episode("past", at=SINCE - timedelta(days=1), text="Window seats."),
        Memory.model_validate(memory("m-seat", _CLAIM, said_support(address("past"))).model_dump()),
    )
    await harness.hold(
        episode("one", at=OBSERVER_AT - timedelta(minutes=3), text="I prefer window seats."),
        episode("two", at=OBSERVER_AT - timedelta(minutes=2), text="What time is it?"),
        episode("three", at=OBSERVER_AT - timedelta(minutes=1), text="Thanks."),
    )
    sink = FakeDiagnosticSink()
    scouting = FakeStructuredCompleter.scripted(_thinking(scouted(found(_CLAIM, "P1")), scout))
    committing = FakeStructuredCompleter.scripted(
        _thinking(framing(framed(_CLAIM, "P1")), framing_thought),
        _thinking(placing(("M1", "unclear", "Which trip is not shown.")), placement),
    )
    observer = harness.observer(scout=scouting, commit=committing, diagnostics=sink)
    with capture_logs() as logs:
        await observer.run()
    return sink, scouting, committing, logs


def _by_stage(sink: FakeDiagnosticSink, kind: DiagnosticKind) -> dict[str, dict[str, Any]]:
    held = [_body(one) for one in sink.of(DiagnosticSource.OBSERVER, kind)]
    called = [one for one in held if one["stage"] in {"scout", "framing", "placement"}]
    assert [one["stage"] for one in called] == ["scout", "framing", "placement"]
    return {one["stage"]: one for one in called}


async def test_the_observers_three_calls_each_keep_their_own_summary() -> None:
    """§5:1, §6:1: the scout's, framing's and placement's returned entries, each its own."""
    sink, _, _, _ = await _observe(
        scout="Scouting zq-first-7731.", framing_thought=_FIRST_THOUGHT, placement=_SECOND_THOUGHT
    )

    returned = _by_stage(sink, DiagnosticKind.RETURNED)
    assert {stage: one["thinking"] for stage, one in returned.items()} == {
        "scout": "Scouting zq-first-7731.",
        "framing": _FIRST_THOUGHT,
        "placement": _SECOND_THOUGHT,
    }


async def test_an_observer_call_with_no_summary_writes_no_thinking_key() -> None:
    """§5:1: each call's entry on its own exchange: no key where it holds ``None``."""
    sink, _, _, _ = await _observe(scout=None, framing_thought=_FIRST_THOUGHT, placement=None)

    returned = _by_stage(sink, DiagnosticKind.RETURNED)
    assert "thinking" not in returned["scout"]
    assert returned["framing"]["thinking"] == _FIRST_THOUGHT
    assert "thinking" not in returned["placement"]


async def test_the_observers_entries_differ_by_the_thinking_key_alone_and_nothing_else_leaks() -> (
    None
):
    """§5:2, §5:3, §5:5: given entries unchanged; no later call, step entry or log holds it."""
    kept, scouting, committing, logs = await _observe(
        scout=_FIRST_THOUGHT, framing_thought=_SECOND_THOUGHT, placement=_FIRST_THOUGHT
    )
    plain, _, _, _ = await _observe(scout=None, framing_thought=None, placement=None)

    assert _by_stage(kept, DiagnosticKind.GIVEN) == _by_stage(plain, DiagnosticKind.GIVEN)
    returned_kept = _by_stage(kept, DiagnosticKind.RETURNED)
    returned_plain = _by_stage(plain, DiagnosticKind.RETURNED)
    assert _without_thinking(list(returned_kept.values())) == list(returned_plain.values())
    # Every other entry the observer writes (findings, outcome, end) is unchanged too.
    steps = [_body(one) for one in kept.of(DiagnosticSource.OBSERVER, DiagnosticKind.STEP)]
    assert steps == [_body(one) for one in plain.of(DiagnosticSource.OBSERVER, DiagnosticKind.STEP)]
    assert not _leaks(steps)
    assert not _leaks([call.messages for call in (*scouting.calls, *committing.calls)])
    assert not _leaks(logs)


# --- a follow-up asked of a call that kept a summary (§5:2, ADR-0337 §8:5) -----------------


class _World:
    """The one model every follow-up goes to, keeping each request it is sent."""

    def __init__(self) -> None:
        self.sent: list[list[ModelMessage]] = []
        self.model = FunctionModel(self._respond, model_name="world")

    def build(self, spec: str) -> Model:
        del spec
        return self.model

    async def _respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        self.sent.append(messages)
        return ModelResponse(parts=[TextPart("I read the label as the park's.")])


async def _asked(sink: FakeDiagnosticSink, count: int) -> None:
    """Wait until the asker has written ``count`` follow-up entries."""
    async with asyncio.timeout(5):
        while len(sink.of(DiagnosticSource.FOLLOW_UP)) < count:  # noqa: ASYNC110 — the asker exposes no signal, by design
            await asyncio.sleep(0.005)


async def test_a_follow_up_of_a_call_that_kept_a_summary_sends_nothing_of_it() -> None:
    """§5:2, ADR-0354 §8:8: the followed reply's text is the assistant turn, and no summary."""
    sink, world = FakeDiagnosticSink(), _World()
    asker = FollowUpAsker(
        sink,
        prompt=default_prompt(FOLLOW_UP_PROMPT),
        routes=dict.fromkeys(FOLLOW_UP_ROUTES, "fake:world"),
        daily_calls=10,
        timeout=30.0,
        now=lambda: _AT,
        build=world.build,
    )
    try:
        await _understand(_repairing(_FIRST_THOUGHT, _SECOND_THOUGHT), asker)
        await _digest(_FIRST_THOUGHT, asker)
        await _asked(sink, 3)
    finally:
        await asker.aclose()

    # The returned entries the asker paired each held a summary it was handed.
    returned = [
        *_bodies(sink, DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED),
        *_bodies(sink, DiagnosticSource.DIGESTING, DiagnosticKind.RETURNED),
    ]
    assert [one["thinking"] for one in returned] == [
        _FIRST_THOUGHT,
        _SECOND_THOUGHT,
        _FIRST_THOUGHT,
    ]
    assert len(world.sent) == 3
    assert not _leaks(world.sent)
    # The followed call's response is the last response of each request: its reply alone.
    followed = [
        [message for message in request if isinstance(message, ModelResponse)][-1]
        for request in world.sent
    ]
    assert [one.text for one in followed] == [one["reply"] for one in returned]
    assert all(isinstance(part, TextPart) for one in followed for part in one.parts)
    assert not _leaks(_bodies(sink, DiagnosticSource.FOLLOW_UP, DiagnosticKind.RETURNED))
