"""Unit tests for the model-backed planner (ADR-0047).

Drives :class:`~ai_assistant.planning.ModelBackedPlanner` through the shared
``PlannerContract`` and against :class:`FakeModelProvider`, so extraction,
malformed-output handling, the bounded repair round, and memory personalization
are asserted deterministically — a fixed clock and a counter id factory make each
plan reproducible byte-for-byte.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from planner_contract import PlannerContract
from pydantic import ValidationError

from ai_assistant.core.errors import ModelError, PlanningError
from ai_assistant.core.types import (
    CurrentContext,
    EpisodicMemory,
    Goal,
    MemorySource,
    Message,
    PreferenceMemory,
    Provenance,
    Role,
    TimeOfDay,
)
from ai_assistant.planning import ModelBackedPlanner
from ai_assistant.planning.planner import (
    _MAX_EXTRACTION_MISSES,
    _extract_object,
    _ExtractionError,
)
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import Planner
    from ai_assistant.core.types import MemoryRecord

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _fixed_now() -> datetime:
    return _WHEN


def _counter() -> Callable[[], str]:
    """A deterministic id factory: ``id-0``, ``id-1``, ... in call order."""
    count = 0

    def factory() -> str:
        nonlocal count
        value = f"id-{count}"
        count += 1
        return value

    return factory


def _goal(goal_id: str = "g1") -> Goal:
    return Goal(
        id=goal_id,
        statement="relocate to Lisbon",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN
        ),
        created_at=_WHEN,
    )


def _context() -> CurrentContext:
    return CurrentContext(
        now=_WHEN,
        time_of_day=TimeOfDay.MORNING,
        is_weekend=False,
        within_working_hours=True,
    )


def _preference() -> PreferenceMemory:
    """A relevance-retrieved belief — the second group of ``memories``."""
    return PreferenceMemory(
        id="m1",
        content="prefers a quiet neighbourhood",
        preference="quiet neighbourhood",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.8, last_updated=_WHEN),
    )


def _turn(record_id: str, content: str) -> EpisodicMemory:
    """A captured conversation turn — the first group of ``memories`` (ADR-0074 §5)."""
    return EpisodicMemory(
        id=record_id,
        content=content,
        occurred_at=_WHEN,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_WHEN),
    )


_VALID_REPLY = json.dumps(
    {
        "rationale": "two steps to relocate",
        "steps": [
            {
                "intent": "find a place",
                "capability": "search_housing",
                "parameters": {"city": "Lisbon"},
            },
            {"intent": "book the move", "capability": "book_movers", "parameters": {}},
        ],
    }
)


def _planner(reply: str = _VALID_REPLY) -> ModelBackedPlanner:
    return ModelBackedPlanner(
        FakeModelProvider(reply),
        now=_fixed_now,
        id_factory=_counter(),
    )


class TestModelBackedPlannerContract(PlannerContract):
    """Runs ModelBackedPlanner through the shared Planner conformance suite."""

    @pytest.fixture
    def planner(self) -> Planner:
        return _planner()


async def test_extracts_capabilities_in_order() -> None:
    plan = await _planner().plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]
    assert [step.intent for step in plan.steps] == ["find a place", "book the move"]
    assert plan.rationale == "two steps to relocate"
    assert dict(plan.steps[0].parameters) == {"city": "Lisbon"}


async def test_ids_are_minted_from_the_factory_not_the_model() -> None:
    """The plan id and step ids come from the injected factory, in call order."""
    plan = await _planner().plan(_goal(), context=_context())

    # Steps are validated first (id-0, id-1), then the plan id (id-2).
    assert [step.id for step in plan.steps] == ["id-0", "id-1"]
    assert plan.id == "id-2"
    assert plan.goal_id == "g1"
    assert plan.created_at == _WHEN


async def test_tolerates_prose_and_code_fence_around_the_object() -> None:
    wrapped = f"Sure! Here is the plan:\n```json\n{_VALID_REPLY}\n```\nHope that helps."
    plan = await _planner(wrapped).plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(_VALID_REPLY, id="bare-object"),
        pytest.param(f"```json\n{_VALID_REPLY}\n```", id="code-fenced-object"),
        pytest.param(f"Here is {{the requested plan}}:\n{_VALID_REPLY}", id="brace-in-prose"),
    ],
)
async def test_the_envelope_decodes_through_a_brace_bearing_wrapper(reply: str) -> None:
    """The envelope is decoded past prose that itself contains a brace (#293).

    A first-``{``-to-last-``}`` slice spans the prose brace in ``Here is {...}:``
    and the envelope's closing brace at once, so ``json.loads`` receives both
    fragments and fails on a reply that *did* carry a valid object. Scanning each
    ``{`` with ``raw_decode`` skips the prose brace and accepts the envelope. The
    bare and code-fenced forms, which already worked, must keep working.
    """
    plan = await _planner(reply).plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]


async def test_a_decoy_object_ahead_of_the_envelope_is_stepped_over() -> None:
    """Scanning prefers the envelope (a non-empty ``steps`` list), not the leftmost.

    A brace-bearing prose fragment can itself be a *valid* JSON object — ``Note:
    {"tip": "be concise"}`` — that decodes before the real envelope. Accepting the
    leftmost decodable object outright would plan from the decoy; preferring the
    first well-formed envelope steps over it and reaches the plan.
    """
    reply = f'Note: {{"tip": "be concise"}}\n{_VALID_REPLY}'
    plan = await _planner(reply).plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]


@pytest.mark.parametrize(
    "decoy",
    [
        pytest.param('{"steps": "not a list"}', id="steps-wrong-type"),
        pytest.param('{"steps": []}', id="steps-empty-list"),
    ],
)
async def test_a_malformed_steps_decoy_does_not_shadow_the_envelope(decoy: str) -> None:
    """Preferring merely a ``steps`` *key* would let a malformed decoy shadow the plan.

    A decoy whose ``steps`` is the wrong type or an empty list carries the key but
    is not the envelope shape §4 step 2 accepts. Selecting it would fail extraction
    on the decoy and exhaust bounded repair while a valid envelope sits behind it,
    so the predicate is a **non-empty ``steps`` list**, not the key's presence.
    """
    reply = f"Here is the plan: {decoy}\n{_VALID_REPLY}"
    plan = await _planner(reply).plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]


async def test_a_nested_decoy_does_not_override_an_empty_plan() -> None:
    """A plan-shaped object nested in the envelope's metadata cannot rescue it (#405).

    The top-level envelope has an empty ``steps`` — an empty plan, which §4 rejects.
    Because the scan resumes *past* a decoded object rather than re-entering it, the
    non-empty ``steps`` nested in ``metadata`` is never a separate candidate, so the
    empty top-level plan stands and is refused (a bounded ``PlanningError``) instead
    of a malformed decision becoming a valid audit record.
    """
    reply = '{"steps": [], "metadata": {"steps": [{"intent": "x", "capability": "do_x"}]}}'
    with pytest.raises(PlanningError):
        await _planner(reply).plan(_goal(), context=_context())


async def test_prose_with_many_unparseable_braces_before_the_envelope_decodes() -> None:
    """The miss budget counts *unparseable* braces, and is generous (#405).

    Prose peppered with brace fragments ahead of the envelope — well within
    ``_MAX_EXTRACTION_MISSES`` — is stepped over and the envelope is still found.
    """
    reply = ("{x} " * (_MAX_EXTRACTION_MISSES // 4)) + _VALID_REPLY
    plan = await _planner(reply).plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]


async def test_the_envelope_at_exactly_the_miss_budget_still_decodes() -> None:
    """Exactly ``_MAX_EXTRACTION_MISSES`` misses are *tolerated* — the on-boundary case.

    The bound is "up to N misses" (ADR-0071), so an envelope behind exactly N
    unparseable braces is still found; only the miss *beyond* N gives up. This pins
    the off-by-one: a `>=` break would reject this reply.
    """
    reply = ("{x} " * _MAX_EXTRACTION_MISSES) + _VALID_REPLY
    plan = await _planner(reply).plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]


async def test_the_envelope_is_given_up_past_the_miss_budget() -> None:
    """Past the miss budget extraction gives up — the documented tolerance boundary.

    Burying the envelope behind more than ``_MAX_EXTRACTION_MISSES`` unparseable
    braces degrades to bounded repair (a clean ``PlanningError``), the deliberate
    price of bounding the scan against adversarial brace-dense input (ADR-0071).
    """
    reply = ("{x} " * (_MAX_EXTRACTION_MISSES + 1)) + _VALID_REPLY
    with pytest.raises(PlanningError):
        await _planner(reply).plan(_goal(), context=_context())


async def test_a_deep_nesting_miss_does_not_discard_a_later_envelope() -> None:
    """A ``RecursionError`` fragment is a miss; the scan continues to the envelope (#405).

    A pathologically nested payload raises ``RecursionError`` — not a
    ``JSONDecodeError``. ADR-0071 treats it as a miss and keeps scanning, so a valid
    envelope *after* it is still returned rather than the failure discarding it. (The
    deep-nesting error test only covers a wholly bad reply, which would pass even if
    this terminated the scan.)
    """
    depth = sys.getrecursionlimit() + 100
    fragment = '{"a": ' + "[" * depth + "]" * depth + "}"
    reply = f"{fragment}\n{_VALID_REPLY}"
    plan = await _planner(reply).plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]


async def test_an_over_limit_integer_miss_does_not_discard_a_later_envelope() -> None:
    """An over-limit-integer ``ValueError`` fragment is a miss; the scan continues (#405).

    An over-limit integer literal raises a plain ``ValueError``, not a
    ``JSONDecodeError``, and ADR-0071 treats it as a miss and keeps scanning. The
    digit limit is pinned to a known, *enabled* value for the test — it can be
    disabled (``sys.get_int_max_str_digits() == 0``) in some configurations, under
    which a fixed-length literal would parse and the ``ValueError`` path would go
    silently unexercised — and restored afterwards.
    """
    original = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(640)  # the minimum enabled limit; 1000 digits is over it
    try:
        reply = f'{{"n": {"1" * 1000}}}\n{_VALID_REPLY}'
        plan = await _planner(reply).plan(_goal(), context=_context())
    finally:
        sys.set_int_max_str_digits(original)

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]


async def test_memories_reach_the_prompt() -> None:
    """Retrieved memory is rendered into the prompt — what makes a plan personal."""
    model = FakeModelProvider(_VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    await planner.plan(_goal(), context=_context(), memories=[_preference()])

    user_turn = model.last_messages[1]
    assert user_turn.role is Role.USER
    assert "prefers a quiet neighbourhood" in user_turn.content


async def test_no_memories_is_a_generic_request() -> None:
    model = FakeModelProvider(_VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    await planner.plan(_goal(), context=_context())

    assert "No stored memories" in model.last_messages[1].content


async def test_a_conversation_tail_is_not_headed_as_a_relevance_cut() -> None:
    """The two groups ADR-0074 §5 defines get their own headers.

    Heading a chronological tail "relevant memories about the user" is the strain
    §5 refused to accept in the Protocol's wording (#456).
    """
    model = FakeModelProvider(_VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    await planner.plan(
        _goal(),
        context=_context(),
        memories=[_turn("t1", "user: I'm moving to Lisbon"), _preference()],
    )

    prompt = model.last_messages[1].content
    turns_at = prompt.index("Recent conversation turns")
    retrieved_at = prompt.index("Relevant memories about the user")
    # The tail is headed as turns, above the retrieved group's own header.
    assert turns_at < prompt.index("I'm moving to Lisbon") < retrieved_at
    assert retrieved_at < prompt.index("prefers a quiet neighbourhood")


async def test_only_retrieved_records_renders_exactly_the_old_prompt() -> None:
    """With no episodic prefix — every caller today — the prompt is unchanged."""
    model = FakeModelProvider(_VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    await planner.plan(_goal(), context=_context(), memories=[_preference()])

    prompt = model.last_messages[1].content
    assert "Recent conversation turns" not in prompt
    assert prompt.endswith(
        "Relevant memories about the user:\n  - [preference/observed] prefers a quiet neighbourhood"
    )


async def test_only_a_tail_renders_no_relevance_header() -> None:
    """A turn with nothing retrieved is not announced as a relevance cut either."""
    model = FakeModelProvider(_VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    await planner.plan(_goal(), context=_context(), memories=[_turn("t1", "user: hello")])

    prompt = model.last_messages[1].content
    assert "Recent conversation turns" in prompt
    assert "Relevant memories about the user" not in prompt


async def test_the_split_never_reorders_what_it_was_handed() -> None:
    """The tail is the *leading* run, so a later episode stays where it was.

    ADR-0074 §6 keeps episodic records out of relevance retrieval today, so this
    sequence is not one the pipeline produces — it pins that the split is a prefix
    cut rather than a partition by kind, which would move the last record up.
    """
    model = FakeModelProvider(_VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())
    memories: list[MemoryRecord] = [
        _turn("t1", "user: first turn"),
        _preference(),
        _turn("t2", "recalled: an older episode"),
    ]

    await planner.plan(_goal(), context=_context(), memories=memories)

    prompt = model.last_messages[1].content
    assert (
        prompt.index("user: first turn")
        < prompt.index("prefers a quiet neighbourhood")
        < prompt.index("recalled: an older episode")
    )
    # The trailing episode sits under the retrieved header, not the tail's.
    assert prompt.index("Relevant memories about the user") < prompt.index("an older episode")


async def test_unparseable_output_raises_planning_error() -> None:
    with pytest.raises(PlanningError):
        await _planner("I cannot help with that.").plan(_goal(), context=_context())


async def test_empty_steps_raises_planning_error() -> None:
    reply = json.dumps({"rationale": "nothing to do", "steps": []})
    with pytest.raises(PlanningError):
        await _planner(reply).plan(_goal(), context=_context())


async def test_blank_capability_raises_planning_error() -> None:
    reply = json.dumps({"steps": [{"intent": "x", "capability": "  "}]})
    with pytest.raises(PlanningError):
        await _planner(reply).plan(_goal(), context=_context())


async def test_non_object_parameters_raises_planning_error() -> None:
    reply = json.dumps({"steps": [{"intent": "x", "capability": "do_x", "parameters": [1, 2]}]})
    with pytest.raises(PlanningError):
        await _planner(reply).plan(_goal(), context=_context())


async def test_step_missing_capability_raises_planning_error() -> None:
    reply = json.dumps({"steps": [{"intent": "x"}]})
    with pytest.raises(PlanningError):
        await _planner(reply).plan(_goal(), context=_context())


async def test_repair_round_recovers_after_one_malformed_reply() -> None:
    """A malformed first reply is retried once; the second, valid reply wins."""
    model = FakeModelProvider.scripted("not json at all", _VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    plan = await planner.plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]
    assert model.call_count == 2


async def test_repair_is_bounded_by_max_attempts() -> None:
    """Two malformed replies exhaust the default two attempts, then it gives up."""
    model = FakeModelProvider.scripted("garbage one", "garbage two")
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    with pytest.raises(PlanningError):
        await planner.plan(_goal(), context=_context())
    assert model.call_count == 2


async def test_single_attempt_does_not_repair() -> None:
    model = FakeModelProvider("not json")
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter(), max_attempts=1)

    with pytest.raises(PlanningError):
        await planner.plan(_goal(), context=_context())
    assert model.call_count == 1


async def test_repair_prompt_echoes_the_reason_and_carries_the_bad_reply() -> None:
    model = FakeModelProvider.scripted("nope", _VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    await planner.plan(_goal(), context=_context())

    # The second call's conversation carries the bad reply and a repair turn.
    second_call = model.calls[1].messages
    assert any(m.role is Role.ASSISTANT and m.content == "nope" for m in second_call)
    assert second_call[-1].role is Role.USER
    assert "only the JSON object" in second_call[-1].content


async def test_max_attempts_above_two_allows_multiple_repair_rounds() -> None:
    """Two malformed replies then a valid one succeeds at max_attempts=3."""
    model = FakeModelProvider.scripted("bad one", "bad two", _VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter(), max_attempts=3)

    plan = await planner.plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]
    assert model.call_count == 3


async def test_max_attempts_three_exhausts_after_three_calls() -> None:
    model = FakeModelProvider.scripted("bad one", "bad two", "bad three")
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter(), max_attempts=3)

    with pytest.raises(PlanningError):
        await planner.plan(_goal(), context=_context())
    assert model.call_count == 3


async def test_max_attempts_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        ModelBackedPlanner(FakeModelProvider(_VALID_REPLY), max_attempts=0)


@pytest.mark.parametrize("bad", [1.5, True, "2", None])
async def test_non_int_max_attempts_is_rejected(bad: object) -> None:
    """A non-int (bool included) is a TypeError at construction, not a later crash."""
    with pytest.raises(TypeError, match="max_attempts"):
        ModelBackedPlanner(FakeModelProvider(_VALID_REPLY), max_attempts=bad)  # type: ignore[arg-type]


async def test_deeply_nested_json_becomes_planning_error() -> None:
    """A pathologically nested payload enters the repair path, not a RecursionError."""
    depth = sys.getrecursionlimit() + 100
    reply = '{"steps":' + "[" * depth + "]" * depth + "}"

    with pytest.raises(PlanningError):
        await _planner(reply).plan(_goal(), context=_context())


async def test_oversized_integer_becomes_planning_error() -> None:
    """An over-limit integer literal raises a plain ValueError; it is still bounded."""
    big = "1" * (sys.get_int_max_str_digits() + 100)
    reply = '{"steps":[{"intent":"x","capability":"do_x","parameters":{"n":' + big + "}}]}"
    model = FakeModelProvider(reply)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    with pytest.raises(PlanningError):
        await planner.plan(_goal(), context=_context())
    assert model.call_count == 2


def test_the_scan_stops_at_the_miss_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scan is bounded: it makes exactly ``_MAX_EXTRACTION_MISSES + 1`` attempts (#405).

    A failed ``raw_decode`` costs work proportional to how far into the reply it
    reached (``JSONDecodeError`` computes a line and column), so attempting it at
    every brace of a brace-dense reply is quadratic and, before the miss budget, hung
    the scan on the event loop. Counting the ``raw_decode`` calls on
    ``'{"x":"' * 100_000`` — where every brace is a miss — pins the bound
    *deterministically*: the scan stops one miss past the budget, then gives up.
    Merely asserting ``PlanningError`` would not — the superseded first-``{``/last-
    ``}`` slice raised it too, so that assertion passes even if the bound regresses.
    """
    calls = 0
    real = json.JSONDecoder.raw_decode

    def counting(self: json.JSONDecoder, s: str, idx: int = 0) -> tuple[object, int]:
        nonlocal calls
        calls += 1
        return real(self, s, idx)

    monkeypatch.setattr(json.JSONDecoder, "raw_decode", counting)

    with pytest.raises(_ExtractionError):
        _extract_object('{"x":"' * 100_000)

    assert calls == _MAX_EXTRACTION_MISSES + 1


async def test_model_error_propagates_unwrapped() -> None:
    """A provider transport failure stays a ModelError, not a PlanningError."""

    def boom(_messages: object) -> str:
        raise RuntimeError("provider down")

    model = FakeModelProvider(boom)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    with pytest.raises(ModelError):
        await planner.plan(_goal(), context=_context())


async def test_clock_misread_surfaces_as_planning_error() -> None:
    """A naive clock reading is a PlanningError, not a raw ValueError (ADR-0026)."""

    def naive() -> datetime:
        return datetime(2026, 1, 1)  # noqa: DTZ001 - intentionally naive for the test

    planner = ModelBackedPlanner(FakeModelProvider(_VALID_REPLY), now=naive, id_factory=_counter())

    with pytest.raises(PlanningError):
        await planner.plan(_goal(), context=_context())


# --- one observation of the caller's goal (ADR-0065) -------------------------


class _GatedModel:
    """A ``ModelProvider`` that parks the first call until the test releases it.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ModelProvider`. ``FakeModelProvider``
    cannot express this: its ``complete`` never suspends, so a caller has no
    moment at which ``plan`` is genuinely parked. Here the first ``complete``
    announces that ``plan`` has reached its first — and widest — suspension
    point, then waits, which hands control back to the test's own task while
    ``plan`` is still in flight. Later calls (the bounded repair round) answer
    immediately, so only one window has to be coordinated.
    """

    def __init__(self, *replies: str) -> None:
        self._replies = deque(replies)
        self.reached = asyncio.Event()
        self.resume = asyncio.Event()
        self.calls: list[tuple[Message, ...]] = []

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,  # part of the ModelProvider signature; unused here
    ) -> Message:
        """Record the conversation, park the first call, then reply."""
        self.calls.append(tuple(m.model_copy(deep=True) for m in messages))
        if not self.reached.is_set():
            self.reached.set()
            await self.resume.wait()
        return Message(role=Role.ASSISTANT, content=self._replies.popleft())


async def test_a_goal_cannot_be_mutated_during_the_model_call() -> None:
    """ADR-0068 freezes ``Goal``, so the mid-call tear ADR-0065 guarded is unrepresentable.

    The mutation would land while ``plan`` is parked inside ``complete`` — not
    before the call and not after it returned, which is the only window that
    distinguishes one observation from two. Freezing makes it raise rather than
    tear, so the plan necessarily names the single goal the prompt was rendered
    from, permanently correct in the auditable record (ADR-0014 §2, ADR-0068 §4).
    """
    model = _GatedModel(_VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())
    goal = _goal("g1")

    task = asyncio.ensure_future(planner.plan(goal, context=_context()))
    await model.reached.wait()
    with pytest.raises(ValidationError):
        goal.id = "g-tampered"
    with pytest.raises(ValidationError):
        goal.statement = "relocate to Berlin"
    model.resume.set()
    plan = await task

    assert plan.goal_id == "g1"
    # ...and that id agrees with the single observation the prompt was rendered
    # from, which is the property: one result, one version of the input.
    prompt = model.calls[0][1].content
    assert "relocate to Lisbon" in prompt
    assert "Berlin" not in prompt


async def test_the_exhaustion_message_names_the_goal_the_call_began_with() -> None:
    """The give-up message names the single goal the call began with (ADR-0065, ADR-0068 §4).

    The message is read after every model call — the second post-await read of the
    caller's goal — and it names a goal in an error a human acts on. ADR-0068
    freezes ``Goal``, so the mid-call mutation raises rather than reaching that
    read.
    """
    model = _GatedModel("garbage one", "garbage two")
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())
    goal = _goal("g1")

    task = asyncio.ensure_future(planner.plan(goal, context=_context()))
    await model.reached.wait()
    with pytest.raises(ValidationError):
        goal.id = "g-tampered"
    model.resume.set()

    with pytest.raises(PlanningError) as caught:
        await task
    assert "g1" in str(caught.value)
    assert "g-tampered" not in str(caught.value)
