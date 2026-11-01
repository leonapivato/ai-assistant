"""``remember`` recording a candidate (ADR-0329 §§3-5).

The candidate's declaration and what a call records, its runner over a lookup, and the
lookup itself under the round's audience. ADR-0328 §13's interim, under which a call
wrote a memory, is retired with the composition root's switch.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from test_lookups import BOUNDED, UNBOUNDED, _Down, _fact, _Searched, _store

from ai_assistant.core.types import (
    ActionRequest,
    CapabilityEffect,
    CapabilityResult,
    LabelKind,
    Memory,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ToolCall,
    ToolDefinition,
    ToolFailureKind,
    ToolOutcome,
)
from ai_assistant.orchestration.lookups import LookUps
from ai_assistant.orchestration.planning import offered_tools
from ai_assistant.orchestration.remembering import (
    CANDIDATE_LABEL_ARGUMENTS,
    CONFIRM_ARGUMENT,
    EPISODE_ARGUMENT,
    OUTSIDE_CONTENT_ARGUMENT,
    REMEMBER_CANDIDATE,
    REMEMBER_CAPABILITY,
    SIMILAR_KEY,
    Candidate,
    CandidateCalls,
    candidate_of,
    candidate_similar,
    is_candidate_result,
)

_AT: Final = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

#: The hub-filled arguments, as authorizing fills them (ADR-0329 §3:4).
_FILLED: Final = {EPISODE_ARGUMENT: "activation:a1", OUTSIDE_CONTENT_ARGUMENT: False}


def _arguments(**fields: Any) -> dict[str, Any]:
    return {"fact": "The user prefers window seats.", "why": "a travel preference", **fields}


def _call(
    parameters: dict[str, Any],
    *,
    tool: ToolDefinition = REMEMBER_CANDIDATE,
    effect: str | None = "effect-1",
) -> ToolCall:
    request = ActionRequest(tool=tool, parameters=parameters)
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    decision = PermissionDecision.from_request(
        request, ruling, id="d1", decided_at=_AT, effect=effect
    )
    return ToolCall(request=request, decision=decision)


class _Similar:
    """A ``SimilarMemories`` stub: what it finds, and what it was asked."""

    def __init__(self, found: tuple[Memory, ...] | None) -> None:
        self.found = found
        self.asked: list[tuple[str, int]] = []

    async def similar(self, fact: str, *, limit: int) -> tuple[Memory, ...] | None:
        self.asked.append((fact, limit))
        return self.found


# --- the declaration (§3:7, §4:3, §5:1) ---------------------------------------------------


def test_the_candidates_declaration_is_as_ruled() -> None:
    """ADR-0306 §3:2, §3:7: own records, not safe to repeat, never leaves the hub, never unknown.

    §4:3: its result carries no outside text, so it goes to planning whole. The hub
    fills the episode and the outside mark (§3:4).
    """
    assert REMEMBER_CANDIDATE.id == REMEMBER_CAPABILITY
    assert REMEMBER_CANDIDATE.capability == REMEMBER_CAPABILITY
    assert REMEMBER_CANDIDATE.effect is CapabilityEffect.OWN_RECORDS
    assert REMEMBER_CANDIDATE.leaves_hub is False
    assert REMEMBER_CANDIDATE.outcome_can_be_unknown is False
    assert REMEMBER_CANDIDATE.safe_to_repeat is False
    assert REMEMBER_CANDIDATE.system_supplied == (EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT)
    assert REMEMBER_CANDIDATE.result is CapabilityResult.NO_OUTSIDE_TEXT


def test_confirm_is_an_ordinary_argument_planning_is_offered() -> None:
    """§5:1: among the values the backstop compares and the exact line shows."""
    (offered,) = offered_tools([REMEMBER_CANDIDATE])
    properties = offered.parameters["properties"]
    assert isinstance(properties, Mapping)
    assert CONFIRM_ARGUMENT in properties
    assert CONFIRM_ARGUMENT not in REMEMBER_CANDIDATE.system_supplied
    # Neither of the hub's own is offered (ADR-0254 §3), and no *looking for* is added,
    # since the result carries no outside text (ADR-0306 §2:9).
    assert EPISODE_ARGUMENT not in properties
    assert OUTSIDE_CONTENT_ARGUMENT not in properties
    assert "looking_for" not in properties


def test_a_candidate_names_earlier_messages_results_and_a_memory_by_label() -> None:
    """§3:1, §3:4: each label argument is checked as ADR-0307 §5:3 checks one."""
    assert CANDIDATE_LABEL_ARGUMENTS == {
        REMEMBER_CAPABILITY: {
            "rests_on_user_messages": LabelKind.EPISODE,
            "rests_on_assistant_messages": LabelKind.EPISODE,
            "rests_on_results": LabelKind.RESULT,
            "memory": LabelKind.MEMORY,
        }
    }


# --- what a call records (§3:1-§3:2, §5:1) -------------------------------------------------


def test_a_call_records_one_fact_what_it_rests_on_and_why() -> None:
    candidate = candidate_of(
        _arguments(
            rests_on_input=True,
            rests_on_user_messages=["activation:e1"],
            rests_on_results=["result:r1"],
            memory="m1",
            note="it narrows that",
            confirm=True,
            **_FILLED,
        )
    )
    assert candidate == Candidate(
        fact="The user prefers window seats.",
        why="a travel preference",
        rests_on_input=True,
        user_messages=("activation:e1",),
        results=("result:r1",),
        memory="m1",
        note="it narrows that",
        confirm=True,
    )


@pytest.mark.parametrize(
    ("arguments", "fault"),
    [
        pytest.param(_arguments(), "rests on the input", id="rests-on-nothing"),
        pytest.param(
            _arguments(rests_on_input=False, rests_on_results=[]),
            "rests on the input",
            id="rests-on-nothing-said-twice",
        ),
        pytest.param(_arguments(fact=" ", rests_on_input=True), "non-blank fact", id="blank"),
        pytest.param({"fact": "x", "rests_on_input": True}, "why it is worth keeping", id="no-why"),
        pytest.param(
            _arguments(rests_on_input=True, note="bears on it"), "the memory it names", id="note"
        ),
        pytest.param(
            _arguments(rests_on_input=True, memory="m1"), "says in a note how", id="memory"
        ),
        pytest.param(_arguments(rests_on_input="yes"), "true or false", id="flag"),
        pytest.param(_arguments(rests_on_user_messages=[3]), "names things by label", id="labels"),
        pytest.param(
            _arguments(rests_on_input=True, confirm=1), "true or false", id="confirm-type"
        ),
    ],
)
def test_a_malformed_candidate_is_refused(arguments: dict[str, Any], fault: str) -> None:
    with pytest.raises(ValueError, match=fault):
        candidate_of(arguments)


# --- the runner (§3:3, §4:1, §4:4, §5:3, §5:7) --------------------------------------------


async def test_a_candidate_is_recorded_with_the_similar_memories_ids_and_nothing_written() -> None:
    """§4:1: the lookup's memories, by id; §5:7: no memory written, no confirmation built.

    The runner holds no writer at all: recording a candidate is its effect record
    finished done (§3:3).
    """
    similar = _Similar((_fact("m1", "prefers aisle seats"), _fact("m2", "flies often")))
    runner = CandidateCalls(similar=similar, limit=3)

    result = await runner.run(_call(_arguments(rests_on_input=True, **_FILLED)))

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.output == {SIMILAR_KEY: ("m1", "m2")}
    assert is_candidate_result(result.output)
    assert candidate_similar(result.output) == ("m1", "m2")
    assert similar.asked == [("The user prefers window seats.", 3)]


async def test_a_failed_lookup_leaves_the_candidate_recorded_and_says_so() -> None:
    """§4:4: the call is done, and its result says the memories could not be read."""
    runner = CandidateCalls(similar=_Similar(None), limit=3)

    result = await runner.run(_call(_arguments(rests_on_input=True, **_FILLED)))

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.output == {SIMILAR_KEY: None}
    assert is_candidate_result(result.output)
    assert candidate_similar(result.output) is None


async def test_a_candidate_a_tap_approved_is_recorded_the_same_way() -> None:
    """§5:3, ADR-0361 §5:10: under a ticket it records the candidate, and nothing else."""
    runner = CandidateCalls(similar=_Similar(()), limit=3)
    call = _call(_arguments(rests_on_input=True, confirm=True, **_FILLED))

    result = await runner.run(call)

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.output == {SIMILAR_KEY: ()}


async def test_an_unclaimed_call_is_not_done() -> None:
    """§3:3: a candidate is joined to its effect record, so one claimed under none is not."""
    runner = CandidateCalls(similar=_Similar(()), limit=3)

    result = await runner.run(_call(_arguments(rests_on_input=True, **_FILLED), effect=None))

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.INVALID_REQUEST


async def test_a_malformed_candidate_is_not_done_and_looks_nothing_up() -> None:
    similar = _Similar(())
    runner = CandidateCalls(similar=similar, limit=3)

    result = await runner.run(_call(_arguments(**_FILLED)))

    assert result.outcome is ToolOutcome.FAILED
    assert similar.asked == []


def test_a_lookup_returns_at_least_one_memory() -> None:
    with pytest.raises(ValueError, match="at least one"):
        CandidateCalls(similar=_Similar(()), limit=0)


def test_only_a_candidates_result_reads_as_one() -> None:
    assert not is_candidate_result(None)
    assert not is_candidate_result({"records": []})
    assert candidate_similar({"records": ["m1"]}) is None


# --- the lookup (§4:1-§4:2) ----------------------------------------------------------------


async def test_the_lookup_is_one_search_by_relevance_alone() -> None:
    """§4:1, ADR-0328 §7:12: one search, no band searched on its own."""
    store = _Searched()
    look_ups = LookUps(memory=store, views=None, search_limit=5)

    with look_ups.scope(audience=BOUNDED, owner_records=True):
        await look_ups.similar("window seats", limit=4)

    (search,) = store.searches
    assert search["query"] == "window seats"
    assert search["limit"] == 4
    assert [kind.value for kind in search["kinds"]] == ["memory"]
    assert search.get("bands") is None


async def test_the_lookup_keeps_no_memory_resting_on_outside_content() -> None:
    """§4:2: such a memory reaches planning only through a digest; the lookup digests none."""
    store = await _store(
        _fact("said", "window seats on long flights"),
        _fact("reported", "window seats booked by the airline", outside=True),
    )
    look_ups = LookUps(memory=store, views=None, search_limit=5)

    with look_ups.scope(audience=BOUNDED, owner_records=True):
        found = await look_ups.similar("window seats", limit=5)

    assert found is not None
    assert [one.id for one in found] == ["said"]


async def test_the_lookup_reads_under_the_rounds_audience() -> None:
    """ADR-0282 §2:8: a fact about someone else is not kept on an unbounded audience."""
    store = await _store(
        _fact("said", "window seats please"),
        _fact("about-sam", "window seats for Sam", subjects=("Sam",)),
    )
    look_ups = LookUps(memory=store, views=None, search_limit=5)

    with look_ups.scope(audience=UNBOUNDED, owner_records=False):
        found = await look_ups.similar("window seats", limit=5)

    assert found is not None
    assert [one.id for one in found] == ["said"]


async def test_a_lookup_that_cannot_read_answers_none() -> None:
    """§4:4: no scope, or a store that cannot be searched, is a lookup that failed."""
    look_ups = LookUps(memory=_Down(), views=None, search_limit=5)
    with look_ups.scope(audience=BOUNDED, owner_records=True):
        assert await look_ups.similar("window seats", limit=5) is None

    unscoped = LookUps(
        memory=await _store(_fact("said", "window seats")), views=None, search_limit=5
    )
    assert await unscoped.similar("window seats", limit=5) is None
