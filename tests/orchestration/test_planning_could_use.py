"""Planning's side of the filter (ADR-0368 §8): the offer it is handed, and what it shows.

The first round is offered only the capabilities the work's authority could use, every
later round the same (§8:1); a call to one it left out is still judged and handed on to
authorizing, whose check decides it (§8:5). A place the work may not be shown is left out
of Connections, a place on its list included, and an item from it carries no ``where``
(§8:2).
"""

from __future__ import annotations

from dataclasses import replace

from exchange_support import section, tags
from test_tool_descriptions_build import _connections, _inputs, _stage

from ai_assistant.core.types import (
    OWN_CHAT_CONNECTION,
    ChannelIdentity,
    ProposedCall,
    RoundResponse,
)
from ai_assistant.orchestration.could_use import CouldUse
from ai_assistant.orchestration.task_scheduler import ListedPlace

_SEARCH = ProposedCall(
    call_id="c1", name="search_web", arguments={"query": "q", "looking_for": "the weather"}
)


async def test_the_first_round_is_offered_what_the_work_could_use_and_every_round_after() -> None:
    """§8:1: fixed at the first round; a later round's ``could_use`` changes nothing."""
    stage, completer = _stage(RoundResponse(), RoundResponse())
    inputs = _inputs(could_use=frozenset({"send_email"}))

    first = await stage.plan(inputs)
    await stage.plan(
        replace(
            inputs,
            work=first.work,
            rounds=(first.round,),
            labels=(*inputs.labels, *first.labels),
            could_use=None,
        )
    )

    assert [one.name for one in completer.calls[0].tools] == ["send_email", "run_approved"]
    assert completer.calls[1].tools == completer.calls[0].tools


async def test_a_call_to_a_capability_the_offer_left_out_is_handed_on_to_be_checked() -> None:
    """§8:5: judged as any call is, and handed to authorizing, not refused by planning."""
    stage, _ = _stage(RoundResponse(calls=(_SEARCH,)))

    planned = await stage.plan(_inputs(could_use=frozenset({"send_email"})))

    assert planned.refused == ()
    assert [one.call.name for one in planned.calls] == ["search_web"]


async def test_a_place_the_work_may_not_be_shown_is_left_out_of_connections() -> None:
    """§8:2: a place on a task's list, as one the hub lists, is shown only where it may be."""
    line = ListedPlace(
        channel=ChannelIdentity(channel_type="telegram", instance_id="line"),
        heading="Telegram",
        description="the messaging line",
        suggested=True,
    )
    listed = tuple(one for one in _connections() if one.place != "telegram:line")

    async def shown(**fields: object) -> list[str]:
        stage, completer = _stage(RoundResponse())
        await stage.plan(_inputs(connections=listed, places=(line,), **fields))
        entries = tags(
            section(completer.last_call.exchange.briefing, "## Connections"), "connection"
        )
        return [one.text or "" for one in entries]

    assert any("Telegram" in one for one in await shown())
    assert not any(
        "Telegram" in one
        for one in await shown(
            shows=CouldUse(connections=frozenset({OWN_CHAT_CONNECTION}), own=frozenset()).shows
        )
    )


async def test_where_an_approvals_request_was_asked_is_shown_though_the_hub_did_not_hand_it() -> (
    None
):
    """ADR-0382 §2:5: a place an input of the asking activation came from, such as one
    that joined it and is no longer among the hub chat's recent conversations, has an
    entry of its own, once, and only where the work may be shown it (ADR-0368 §8:2)."""
    older = "conversation:c-older"
    approvals = CouldUse(
        connections=frozenset(), own=frozenset({"approvals:approvals"}), asked=frozenset({older})
    )

    async def shown(**fields: object) -> list[str]:
        stage, completer = _stage(RoundResponse())
        await stage.plan(_inputs(**fields))
        briefing = completer.last_call.exchange.briefing
        return [one.text or "" for one in tags(section(briefing, "## Connections"), "connection")]

    # The hub's connections as the phases hand them after narrowing: none it could use.
    assert await shown(connections=(), asked=(older,), shows=approvals.shows) == [
        "a conversation in the system's own chat"
    ]
    assert await shown(asked=("conversation:c-two",)) == await shown(), "once, as handed"
    hidden = CouldUse(connections=frozenset(), own=frozenset({"approvals:approvals"}))
    assert await shown(connections=(), asked=(older,), shows=hidden.shows) == []
