"""What each done call's entry keeps of what it showed, as the phases record it.

ADR-0358 §11:2-§11:4, driven over :class:`PhaseWorking` as acting hands its calls back:
a memory search keeps the records it showed by id, record by record, and nothing of
those its digest read; one no round followed keeps the ids it listed; an episode
look-up keeps the episodes it read; a call not done keeps nothing; and what is kept is
cut to the composition root's bound, the cut carried.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from test_phases_exchange import _AT, _call, _planned, _working
from test_planning import _episode

from ai_assistant.core.types import (
    ActionRequest,
    Attestation,
    CallShowed,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ShownRecord,
    ShownRecordKind,
    ToolCall,
    ToolDefinition,
)
from ai_assistant.orchestration.acting import ActedCall, ActedOutcome, AuthorizedCall, ResultRoute
from ai_assistant.orchestration.authorizer import CallVerdict, RoundAuthorization, Verdict
from ai_assistant.orchestration.lookups import SEARCH_EPISODES, SEARCH_MEMORY
from ai_assistant.orchestration.planning import CallOutcomeKind, EpisodesFound, EpisodeShown
from ai_assistant.testing.memories import memory, said_support, sourced_support

if TYPE_CHECKING:
    from ai_assistant.orchestration.phase_path import PhaseWorking


def _allowed(tool: ToolDefinition, decision: str, **parameters: Any) -> ToolCall:
    request = ActionRequest(tool=tool, parameters=parameters)
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    return ToolCall(
        request=request,
        decision=PermissionDecision.from_request(request, ruling, id=decision, decided_at=_AT),
    )


def _acted(
    tool: ToolDefinition, *, output: object, route: ResultRoute = ResultRoute.PLANNING, **args: Any
) -> PhaseWorking:
    """A working set whose one round's one call acting handed back done."""
    working = _working()
    working.planned(_planned(_call("c1", str(tool.capability), **args)))
    working.latest.authorization = RoundAuthorization(
        activation_id="activation",
        round_id="round-1",
        verdicts=(CallVerdict("c1", Verdict.ALLOWED, decision_id="d1"),),
    )
    working.latest.acted_one(
        ActedCall(
            AuthorizedCall(_allowed(tool, "d1", **args)),
            ActedOutcome.DONE,
            output=output,  # type: ignore[arg-type]  # JSON values
            route=route,
            result_id="result:1",
        )
    )
    return working


def test_a_search_keeps_the_records_planning_was_shown_by_id() -> None:
    """§11:2-§11:3: each record shown by id, one resting on outside content left out."""
    working = _acted(SEARCH_MEMORY, output={"records": ["said", "turned"]}, query="dentist")
    said = memory("said", "dentist with Dr Rao", said_support(when=_AT, added_at=_AT))
    turned = memory(
        "turned",
        "moved",
        sourced_support(Attestation(reported_by="mail", reported_at=_AT), when=_AT, added_at=_AT),
    )
    working.searched["result:1"] = (said, turned)

    (entry,) = working.call_entries(_AT)

    assert entry.outcome is CallOutcomeKind.DONE
    assert entry.showed == CallShowed(parts=(ShownRecord(kind=ShownRecordKind.MEMORY, id="said"),))
    assert "Dr Rao" not in entry.model_dump_json()


def test_a_search_no_round_followed_keeps_the_ids_it_listed() -> None:
    """§11:2: the records it listed for planning, by id, never fetched."""
    working = _acted(SEARCH_MEMORY, output={"records": ["said"]}, query="dentist")

    (entry,) = working.call_entries(_AT, freezing=True)

    assert entry.showed == CallShowed(parts=(ShownRecord(kind=ShownRecordKind.MEMORY, id="said"),))


def test_a_result_held_for_a_digest_keeps_nothing() -> None:
    """§11:3: a result held for a digest keeps nothing; its digests are on the record."""
    working = _acted(SEARCH_MEMORY, output=None, route=ResultRoute.DIGEST, query="dentist")
    working.searched["result:1"] = ()

    (entry,) = working.call_entries(_AT)

    assert entry.showed == CallShowed()
    assert entry.marked


def test_an_episode_search_keeps_each_episode_it_showed() -> None:
    """§11:2: the episodes it read, held by the glue under its result, by id."""
    working = _acted(SEARCH_EPISODES, output={"looked_up": "search_episodes"}, query="dentist")
    working.looked["result:1"] = EpisodesFound(
        episodes=(EpisodeShown(record=_episode("activation:one")),)
    )

    (entry,) = working.call_entries(_AT)

    assert entry.showed == CallShowed(
        parts=(ShownRecord(kind=ShownRecordKind.EPISODE, id="activation:one"),)
    )


def test_what_an_entry_keeps_is_cut_to_the_bound_and_the_cut_carried() -> None:
    """§11:4: past the composition root's bound the rest is left out, and the entry says so."""
    working = _acted(SEARCH_MEMORY, output={"records": ["aaaa", "bbbb"]}, query="dentist")

    (entry,) = working.call_entries(_AT, freezing=True, showed=5)

    assert entry.showed == CallShowed(
        parts=(ShownRecord(kind=ShownRecordKind.MEMORY, id="aaaa"),), cut=True
    )


def test_a_call_not_done_keeps_nothing_of_what_it_showed() -> None:
    """§11:2: only a done call's entry keeps what it showed."""
    working = _working()
    working.planned(_planned(_call("c1", "search_memory", query="x"), refused=("c1",)))

    (entry,) = working.call_entries(_AT)

    assert entry.outcome is CallOutcomeKind.REFUSED
    assert entry.showed is None
