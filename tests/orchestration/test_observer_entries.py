"""What the observer gives the diagnostic record (ADR-0333 §2, §4).

Driven over the canonical fakes, with :class:`~ai_assistant.testing.FakeDiagnosticSink`
as the record: its ``recorded`` is the test's window, and nothing the observer holds can
read it (§4:1). The run's own behaviour is ``test_observer_stage.py``'s; these cases hold
what each attempt writes, under which activation, and that writing changes nothing.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import structlog.testing
from observer_support import (
    AT,
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

from ai_assistant.core.diagnostics import DIAGNOSTIC_NOT_WRITTEN
from ai_assistant.core.errors import PlanningError
from ai_assistant.core.reply_shapes import reply_shape_version
from ai_assistant.core.types import (
    DiagnosticEntry,
    DiagnosticKind,
    DiagnosticSource,
    EpisodicMemory,
    Memory,
    MemorySource,
    ObservationAttemptEnd,
    ObservationState,
    ObserverStep,
    Provenance,
    ReplyFailure,
    ReplyUsage,
    Role,
)
from ai_assistant.core.types import Message as MessageType
from ai_assistant.orchestration.observer.entries import Diagnosed, ObserverEntries
from ai_assistant.orchestration.observer.prompts import (
    OBSERVER_FRAMING_PROMPT,
    OBSERVER_SCOUT_PROMPT,
)
from ai_assistant.orchestration.observer.replies import FramingReplyShape, ScoutReplyShape
from ai_assistant.testing import FakeDiagnosticSink, FakeModelProvider, default_prompt
from ai_assistant.testing.memories import memory, said_support
from ai_assistant.testing.structured import (
    DEFAULT_STRUCTURED_MODEL,
    FakeStructuredCompleter,
    ScriptedReply,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import Message

_PREFERENCE = "I prefer window seats when I fly."
_CLAIM = "The user prefers window seats."


async def _three(harness: Harness, *, text: str = _PREFERENCE) -> None:
    """Three episodes, a minute apart: with a window of two, the oldest has left it."""
    await harness.hold(
        episode("one", at=AT - timedelta(minutes=3), text=text),
        episode("two", at=AT - timedelta(minutes=2), text="What time is it?"),
        episode("three", at=AT - timedelta(minutes=1), text="Thanks."),
    )


def _scout(*parts: str, claim: str = _CLAIM) -> str:
    return scouted(found(claim, *parts))


def _create(part: str = "P1") -> str:
    return framing(
        {
            "wording": _CLAIM,
            "supports": [
                {
                    "part": part,
                    "direction": "for",
                    "backs_as_worded": True,
                    "how_sure": "sure",
                    "note": "the user said so",
                }
            ],
            "subjects": [],
            "involved": [],
            "labels": ["booking a flight"],
            "note": "a stated preference",
        }
    )


def _failing(message: str = "the route is down") -> FakeModelProvider:
    def fail(_messages: Sequence[Message]) -> str:
        raise RuntimeError(message)

    return FakeModelProvider(reply=fail)


def _answering(decide: Callable[[dict[str, Any]], str]) -> FakeModelProvider:
    """A commit route that answers from what it was shown."""

    def answer(messages: Sequence[Message]) -> str:
        return decide(json.loads(messages[-1].content))

    return FakeModelProvider(reply=answer)


def _body(entry: DiagnosticEntry) -> Any:
    """An entry's body as plain JSON, as its line in the file holds it."""
    return json.loads(entry.model_dump_json())["body"]


def _stages(sink: FakeDiagnosticSink) -> list[tuple[str, str]]:
    return [(str(_body(one)["stage"]), one.kind.value) for one in sink.recorded]


async def test_a_processed_episode_writes_its_calls_findings_outcome_and_end() -> None:
    """§2:1-§2:6: every entry, in order, as the observer, under the episode's activation."""
    harness = Harness()
    await _three(harness)
    sink = FakeDiagnosticSink()
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_create()),
        diagnostics=sink,
    )

    await observer.run()

    assert _stages(sink) == [
        ("scout", "given"),
        ("scout", "returned"),
        ("findings", "step"),
        ("framing", "given"),
        ("framing", "returned"),
        ("outcome", "step"),
        ("end", "step"),
    ]
    assert {one.activation_id for one in sink.recorded} == {"one"}
    assert {one.source for one in sink.recorded} == {DiagnosticSource.OBSERVER}
    assert {one.recorded_at for one in sink.recorded} == {AT}
    for one in sink.recorded:
        assert _body(one)["episode"] == address("one")
        assert _body(one)["attempt_started_at"] == AT.isoformat()


async def test_a_calls_entries_hold_its_request_and_its_reply() -> None:
    """§2:1's table: the rendered request naming its step and its prompt, the finding, the reply.

    The prompt is the template the system message was rendered from (ADR-0334 §8:2).
    """
    harness = Harness()
    await _three(harness)
    sink = FakeDiagnosticSink()
    scout, commit = FakeModelProvider.scripted(_scout("P1")), FakeModelProvider.scripted(_create())
    observer = harness.observer(scout=scout, commit=commit, diagnostics=sink)

    await observer.run()

    given, returned, _findings, commit_given, commit_returned = sink.recorded[:5]
    (call,) = scout.calls
    assert given.kind is DiagnosticKind.GIVEN
    assert _body(given)["messages"] == [one.model_dump(mode="json") for one in call.messages]
    # ADR-0335 §9:1: each prompt's one flag, false where no person-model store is wired
    # (ADR-0338 §11:2), as the instruction was rendered under it.
    assert _body(given)["prompt"] == {
        "name": "observer_scout",
        "version": default_prompt(OBSERVER_SCOUT_PROMPT).version,
        "origin": "default",
        "flags": {"person": False},
    }
    # ADR-0346 §10:1: framing declares no flag.
    assert _body(commit_given)["prompt"] == {
        "name": "observer_framing",
        "version": default_prompt(OBSERVER_FRAMING_PROMPT).version,
        "origin": "default",
        "flags": {},
    }
    assert _body(returned)["reply"] == _scout("P1")
    finding = _body(commit_given)["finding"]
    assert {key: finding[key] for key in ("id", "claim", "rests_on", "candidate")} == {
        "id": "f1",
        "claim": _CLAIM,
        "rests_on": [{"part": "input", "episode": address("one"), "message": None}],
        "candidate": None,
    }
    assert finding["annotations"]["subjects"] == ["person:owner"]
    (decided,) = commit.calls
    messages = _body(commit_given)["messages"]
    assert messages == [one.model_dump(mode="json") for one in decided.messages]
    # ADR-0354 §7:1: each structured call names the shape it asks for, and its version.
    assert _body(given)["reply_shape"] == {
        "name": "ScoutReplyShape",
        "version": reply_shape_version(ScoutReplyShape),
    }
    assert _body(commit_given)["reply_shape"] == {
        "name": "FramingReplyShape",
        "version": reply_shape_version(FramingReplyShape),
    }
    # §7:2: the reply as written, and what came back with it.
    assert _body(commit_returned) == {
        "episode": address("one"),
        "attempt_started_at": AT.isoformat(),
        "stage": "framing",
        "finding": "f1",
        "reply": _create(),
        "model": DEFAULT_STRUCTURED_MODEL,
        "mode": "native",
        "finish_reason": "stop",
        "refusal": None,
        "refusal_category": None,
        "usage": ReplyUsage().model_dump(mode="json"),
    }


async def test_a_calls_returned_entry_keeps_the_usage_and_a_returned_failure() -> None:
    """ADR-0354 §7:2, §12:7: usage and the model that answered; a failure's kind, first."""
    harness = Harness()
    await _three(harness)
    sink = FakeDiagnosticSink()
    usage = ReplyUsage(input_tokens=1200, output_tokens=80, cache_read_tokens=1000)
    scout = FakeStructuredCompleter.scripted(
        ScriptedReply(text=_scout("P1"), usage=usage, model="anthropic:claude-sonnet-5-5")
    )
    commit = FakeStructuredCompleter.scripted(
        ScriptedReply(text=_create(), failure=ReplyFailure.CUT)
    )
    observer = harness.observer(scout=scout, commit=commit, diagnostics=sink)

    await observer.run()

    returned = [_body(one) for one in sink.recorded if one.kind is DiagnosticKind.RETURNED]
    scouted, framed = (
        next(one for one in returned if one.get("stage") == stage) for stage in ("scout", "framing")
    )
    assert (scouted["model"], scouted["usage"]) == (
        "anthropic:claude-sonnet-5-5",
        usage.model_dump(mode="json"),
    )
    assert "failure" not in scouted
    # The entry is written before the failure is acted on: the attempt fails unparsed.
    assert (framed["failure"], framed["finish_reason"], framed["reply"]) == (
        "cut",
        "length",
        _create(),
    )
    ended = [_body(one) for one in sink.recorded if _body(one).get("stage") == "end"]
    assert [one["failure"]["class"] for one in ended] == ["unparsed"]


async def test_the_findings_entry_holds_each_claim_its_parts_and_the_dropped_count() -> None:
    """§2:4: each finding's id, claim, parts and origin, and how many were dropped."""
    harness = Harness()
    await _three(harness)
    sink = FakeDiagnosticSink()
    proposed = scouted(found(_CLAIM, "P1"), found("Rests on nothing read.", "P99"))
    observer = harness.observer(
        scout=FakeModelProvider.scripted(proposed),
        commit=FakeModelProvider.scripted(_create()),
        diagnostics=sink,
    )

    await observer.run()

    (findings,) = [one for one in sink.recorded if _body(one)["stage"] == "findings"]
    assert _body(findings)["dropped"] == 1
    assert [one["claim"] for one in _body(findings)["findings"]] == [_CLAIM]
    assert _body(findings)["findings"][0]["rests_on"] == [
        {"part": "input", "episode": address("one"), "message": None}
    ]
    assert _body(findings)["declines"] == []


async def test_an_outcome_entry_holds_the_outcome_and_what_framing_decided() -> None:
    """§2:5: the record's outcome, each framed memory as framed, and its placement."""
    harness = Harness()
    await _three(harness)
    sink = FakeDiagnosticSink()
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_create()),
        diagnostics=sink,
    )

    await observer.run()

    (outcome,) = [one for one in sink.recorded if _body(one)["stage"] == "outcome"]
    (record,) = await harness.plans.observations([address("one")])
    (finding,) = record.findings
    assert finding.outcome is not None
    assert _body(outcome)["finding"] == "f1"
    assert _body(outcome)["claim"] == _CLAIM
    assert _body(outcome)["outcome"] == finding.outcome.model_dump(mode="json")
    decided = _body(outcome)["decided"]
    (one,) = decided["framed"]
    assert (one["wording"], one["refused"]) == (_CLAIM, None)
    (support,) = one["framed"]["supports"]
    assert support["part"] == {"part": "input", "episode": address("one"), "message": None}
    assert (support["direction"], support["note"]) == ("for", "the user said so")
    assert one["framed"]["labels"] == ["booking a flight"]
    (write,) = finding.outcome.writes
    (placed,) = decided["placed"]
    assert placed == {
        "wording": _CLAIM,
        "relations": [],
        "ruling": "accept",
        "kept": [write.memory],
        "refused": None,
        "unclear": [],
    }


async def test_nothing_kept_says_why_in_framings_own_words() -> None:
    """§2:5, ADR-0346 §5:6: an outcome that wrote nothing gives framing's reason."""
    harness = Harness()
    await _three(harness)
    sink = FakeDiagnosticSink()
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(framing(nothing="said once, in passing")),
        diagnostics=sink,
    )

    await observer.run()

    (outcome,) = [one for one in sink.recorded if _body(one)["stage"] == "outcome"]
    assert _body(outcome)["outcome"]["unwritten"] == "not_kept"
    assert _body(outcome)["decided"] == {
        "framed": [],
        "failed": 0,
        "nothing": "said once, in passing",
        "placed": [],
        "set_aside": [],
    }


async def test_an_unclear_placement_is_in_the_outcome_entry() -> None:
    """ADR-0346 §6:5: on the outcome, and so in the diagnostic record, with its note."""
    harness = Harness()
    await harness.hold(
        episode("past", at=SINCE - timedelta(days=1), text="Window seats."),
        Memory.model_validate(memory("m-seat", _CLAIM, said_support(address("past"))).model_dump()),
    )
    await _three(harness)
    sink = FakeDiagnosticSink()
    observer = harness.observer(
        scout=FakeModelProvider(reply=_scout("P1")),
        commit=FakeModelProvider.scripted(
            framing(framed(_CLAIM, "P1")), placing(("M1", "unclear", "Which trip is not shown."))
        ),
        diagnostics=sink,
    )

    await observer.run()

    (outcome,) = [
        one
        for one in sink.recorded
        if _body(one)["stage"] == "outcome" and one.activation_id == "one"
    ]
    assert _body(outcome)["outcome"]["unclear"] == [
        {"memory": "m-seat", "wording": _CLAIM, "note": "Which trip is not shown."}
    ]
    (placed,) = _body(outcome)["decided"]["placed"]
    assert placed["relations"] == [{"memory": "m-seat", "relation": "unclear"}]
    assert placed["unclear"] == [
        {"memory": "m-seat", "wording": _CLAIM, "note": "Which trip is not shown."}
    ]


async def test_what_code_set_aside_of_a_placement_reply_is_in_the_outcome_entry() -> None:
    """#3398: a list of answers is read, and every entry not taken is shown, not lost."""
    harness = Harness()
    await harness.hold(
        episode("past", at=SINCE - timedelta(days=1), text="Window seats."),
        Memory.model_validate(memory("m-seat", _CLAIM, said_support(address("past"))).model_dump()),
    )
    await _three(harness)
    sink = FakeDiagnosticSink()
    observer = harness.observer(
        scout=FakeModelProvider(reply=_scout("P1")),
        commit=FakeModelProvider.scripted(
            framing(framed(_CLAIM, "P1")),
            json.dumps(
                {
                    "relations": [{"memory": "M1", "relation": "restates", "note": "Same."}],
                    "answers": [{"memory": "M1", "question": "Q4"}],
                }
            ),
        ),
        diagnostics=sink,
    )

    await observer.run()

    (outcome,) = [
        one
        for one in sink.recorded
        if _body(one)["stage"] == "outcome" and one.activation_id == "one"
    ]
    assert _body(outcome)["outcome"]["writes"], "the attempt was not failed for the list"
    assert _body(outcome)["decided"]["set_aside"] == [
        {
            "wording": _CLAIM,
            "set_aside": [
                {
                    "answer": {"memory": "M1", "question": "Q4"},
                    "why": "no open question shown under these labels",
                }
            ],
        }
    ]


async def test_an_episode_skipped_by_rule_is_given_its_end_entry_alone() -> None:
    """§2:6: nothing to read, no call, and one entry saying how the attempt ended."""
    harness = Harness()
    await _three(harness, text="")
    sink = FakeDiagnosticSink()

    await harness.observer(diagnostics=sink).run()

    (end,) = [one for one in sink.recorded if one.activation_id == "one"]
    assert end.kind is DiagnosticKind.STEP
    assert _body(end) == {
        "episode": address("one"),
        "attempt_started_at": AT.isoformat(),
        "stage": "end",
        "end": ObservationAttemptEnd.FINISHED.value,
        "state": ObservationState.SKIPPED.value,
        "skipped": "nothing_to_read",
    }


async def test_an_episode_with_no_processing_record_writes_nothing() -> None:
    """§2:8: no processing record, no activation, and so no entry."""
    harness = Harness()
    await harness.hold(
        EpisodicMemory(
            id="harness:bare",
            content="the user said they like tea",
            occurred_at=AT - timedelta(minutes=9),
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
        )
    )
    await _three(harness)
    sink = FakeDiagnosticSink()
    scout = FakeModelProvider.scripted(scouted())

    outcome = await harness.observer(scout=scout, diagnostics=sink).run()

    assert (outcome.skipped, outcome.processed) == (1, 1)
    assert {one.activation_id for one in sink.recorded} == {"one"}
    assert all(_body(one)["episode"] != "harness:bare" for one in sink.recorded)


async def test_a_failed_call_writes_the_failure_and_the_attempts_end() -> None:
    """§2:2, §2:6: the returned entry is the failure; the end names its class and message."""
    harness = Harness()
    await _three(harness)
    sink = FakeDiagnosticSink()

    await harness.observer(scout=_failing(), diagnostics=sink).run()

    given, returned, end = sink.recorded
    assert (_body(given)["stage"], given.kind) == ("scout", DiagnosticKind.GIVEN)
    assert _body(returned)["failure"]["class"] == "ModelError"
    assert "reply" not in _body(returned)
    assert _body(end)["end"] == "failed"
    assert _body(end)["state"] == "waiting"
    assert _body(end)["failure"]["class"] == "ModelError"


async def test_a_reply_that_does_not_parse_ends_failed_naming_its_step() -> None:
    """§2:6: an unparsed reply is a failure whose message says which step's it was."""
    harness = Harness()
    await _three(harness)
    sink = FakeDiagnosticSink()

    await harness.observer(
        scout=FakeModelProvider.scripted("not json"), diagnostics=sink, stuck_after=1
    ).run()

    returned, end = sink.recorded[1:]
    assert _body(returned)["reply"] == "not json"
    assert _body(end)["state"] == "stuck"
    assert _body(end)["failure"] == {
        "class": "unparsed",
        "message": "the scout step's reply did not parse",
    }


async def test_a_call_the_budget_holds_writes_no_given_entry_and_ends_held() -> None:
    """§2:2: a given entry once the budget admits the call; none where it does not."""
    harness = Harness()
    await _three(harness)
    sink = FakeDiagnosticSink()

    outcome = await harness.observer(diagnostics=sink, daily_calls=0).run()

    assert outcome.held
    (end,) = sink.recorded
    assert (_body(end)["end"], _body(end)["state"]) == ("held", "waiting")


async def test_a_retry_names_its_own_attempts_start() -> None:
    """§2:3: every body names the instant its attempt started."""
    harness = Harness()
    await _three(harness)
    sink = FakeDiagnosticSink()
    observer = harness.observer(scout=_failing(), diagnostics=sink)
    await observer.run()
    harness.clock.advance(timedelta(minutes=1))

    await observer.run()

    starts = [_body(one)["attempt_started_at"] for one in sink.recorded]
    later = (AT + timedelta(minutes=1)).isoformat()
    assert starts == [AT.isoformat()] * 3 + [later] * 3


async def _run_with(sink: FakeDiagnosticSink | None) -> tuple[Any, ...]:
    harness = Harness()
    await _three(harness)
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_create()),
        diagnostics=sink,
    )
    outcome = await observer.run()
    records = await harness.plans.observations([address("one")])
    memories = sorted(
        (one.content for one in await harness.memory.export() if isinstance(one, Memory)),
    )
    return outcome, [one.model_copy(update={"revision": 0}) for one in records], memories


async def test_a_failing_record_changes_no_attempt_and_logs_no_content() -> None:
    """§2:11, §4:2: the attempt runs as it would with the record off; one line per entry."""
    failing = FakeDiagnosticSink()
    failing.fail_write()

    with structlog.testing.capture_logs() as captured:
        written = await _run_with(failing)

    assert written == await _run_with(None)
    dropped = [one for one in captured if one["event"] == DIAGNOSTIC_NOT_WRITTEN]
    assert len(dropped) == 7
    assert {(one["activation_id"], one["source"]) for one in dropped} == {("one", "observer")}
    assert _CLAIM not in repr(captured)
    assert _PREFERENCE not in repr(captured)


class _Raising:
    """A sink that breaks its contract by raising, or is cancelled mid-write."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def write(self, entry: DiagnosticEntry) -> None:
        raise self.error


def _target(activation_id: str = "act", episode_id: str = "activation:act") -> Diagnosed:
    return Diagnosed(activation_id=activation_id, episode=episode_id, started_at=AT)


_ASKED = (MessageType(role=Role.USER, content="{}"),)
_SCOUT_PROMPT = default_prompt(OBSERVER_SCOUT_PROMPT).rendered(flags={"person": False})


async def test_one_call_over_several_episodes_writes_under_each_activation() -> None:
    """§2:9: a call reading several due episodes is written under each of their activations."""
    sink = FakeDiagnosticSink()
    entries = ObserverEntries(sink, now=lambda: AT)
    targets = (_target("a", "activation:a"), _target("b", "activation:b"))

    await entries.given(targets, ObserverStep.SCOUT, _ASKED, prompt=_SCOUT_PROMPT)
    await entries.returned(targets, ObserverStep.SCOUT, reply="{}")

    assert [(one.activation_id, one.kind.value) for one in sink.recorded] == [
        ("a", "given"),
        ("b", "given"),
        ("a", "returned"),
        ("b", "returned"),
    ]
    assert [_body(one)["episode"] for one in sink.recorded] == [
        "activation:a",
        "activation:b",
    ] * 2


async def test_with_the_record_off_nothing_is_built() -> None:
    """§2:7: no sink, no entry, and no body built."""
    entries = ObserverEntries(None, now=lambda: pytest.fail("no entry is stamped"))

    await entries.given((_target(),), ObserverStep.SCOUT, _ASKED, prompt=_SCOUT_PROMPT)
    await entries.ended(_target(), ObservationAttemptEnd.FINISHED, ObservationState.PROCESSED)


async def test_a_sink_that_raises_costs_only_the_entry() -> None:
    """§2:11: logged by activation, source and class, and the caller goes on."""
    entries = ObserverEntries(_Raising(RuntimeError("the user's words")), now=lambda: AT)

    with structlog.testing.capture_logs() as captured:
        await entries.ended(_target(), ObservationAttemptEnd.FINISHED, ObservationState.PROCESSED)

    (line,) = captured
    assert (line["event"], line["activation_id"], line["source"], line["error_class"]) == (
        DIAGNOSTIC_NOT_WRITTEN,
        "act",
        "observer",
        "RuntimeError",
    )
    assert "the user's words" not in repr(captured)


async def test_a_cancellation_reaching_a_write_is_re_raised() -> None:
    """§2:11, ADR-0314 §2:5: a cancellation is not a failure to write."""
    entries = ObserverEntries(_Raising(asyncio.CancelledError()), now=lambda: AT)

    with pytest.raises(asyncio.CancelledError):
        await entries.ended(_target(), ObservationAttemptEnd.FINISHED, ObservationState.PROCESSED)


class _CancelledAtOutcome(FakeDiagnosticSink):
    """A record whose first outcome entry's write is reached by a cancellation."""

    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False

    async def write(self, entry: DiagnosticEntry) -> None:
        if not self.cancelled and entry.body.get("stage") == "outcome":
            self.cancelled = True
            raise asyncio.CancelledError
        await super().write(entry)


async def test_a_cancelled_outcome_write_never_commits_its_finding_again() -> None:
    """§1:3, §2:11: the outcome is on the record before its entry is written."""
    harness = Harness()
    await _three(harness)
    sink = _CancelledAtOutcome()
    commit = FakeModelProvider.scripted(_create())
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")), commit=commit, diagnostics=sink
    )

    with pytest.raises(asyncio.CancelledError):
        await observer.run()
    await observer.run()

    assert len(commit.calls) == 1
    created = [one for one in await harness.memory.export() if isinstance(one, Memory)]
    assert [one.content for one in created] == [_CLAIM]
    (record,) = await harness.plans.observations([address("one")])
    assert record.state is ObservationState.PROCESSED


async def test_an_outcome_whose_record_failed_to_be_written_still_has_its_entry() -> None:
    """§2:5: the next attempt restores the decided finding, so its entry is not deferred."""
    harness = Harness()
    await _three(harness)
    write_observation = harness.plans.write_observation
    refused = False

    async def failing_outcome(record: Any, *, expected_revision: int) -> Any:
        nonlocal refused
        if not refused and any(one.outcome is not None for one in record.findings):
            refused = True
            msg = "the plan store could not write"
            raise PlanningError(msg)
        return await write_observation(record, expected_revision=expected_revision)

    harness.plans.write_observation = failing_outcome  # type: ignore[method-assign]  # one outage
    sink = FakeDiagnosticSink()
    commit = FakeModelProvider.scripted(_create())
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")), commit=commit, diagnostics=sink
    )

    await observer.run()
    await observer.run()

    (record,) = await harness.plans.observations([address("one")])
    assert record.state is ObservationState.PROCESSED
    assert len(commit.calls) == 1
    (outcome,) = [one for one in sink.recorded if _body(one)["stage"] == "outcome"]
    assert _body(outcome)["decided"]["framed"][0]["wording"] == _CLAIM
    assert [_body(one)["state"] for one in sink.recorded if _body(one)["stage"] == "end"] == [
        "processed"
    ]


async def test_a_cancelled_outcome_write_after_a_restart_never_commits_again() -> None:
    """§1:3: the outcome is durable before its entry, so a new observer finds it decided."""
    harness = Harness()
    await _three(harness)
    sink = _CancelledAtOutcome()
    commit = FakeModelProvider.scripted(_create())
    first = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")), commit=commit, diagnostics=sink
    )
    with pytest.raises(asyncio.CancelledError):
        await first.run()

    restarted = harness.observer(commit=commit, diagnostics=sink)
    await restarted.run()

    assert len(commit.calls) == 1
    (record,) = await harness.plans.observations([address("one")])
    assert record.state is ObservationState.PROCESSED
