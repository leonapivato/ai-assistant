"""What a planning round was shown, read off the exchange it was asked with (ADR-0356 §5).

A work's later round is asked with the briefing its first round rendered, byte for byte,
and a report after each earlier round: each call's result, then the news. A test that
asserts what a later round was shown reads it here, from the briefing and the reports
together, rather than from a briefing re-rendered each round as before ADR-0356.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai_assistant.core.types import PlanningExchange
    from ai_assistant.testing.tool_calling import RoundCall


def shown_text(call: RoundCall) -> str:
    """Everything one round was shown, as text: the briefing, then each report in order.

    Args:
        call: The round's call, as the fake completer recorded it.

    Returns:
        The briefing, then each step's results' texts and its news, one per line.
    """
    parts = [call.exchange.briefing]
    for step in call.exchange.steps:
        parts.extend(one.text for one in step.report.results)
        parts.append(step.report.news)
    return "\n".join(parts)


def reported(call: RoundCall, step: int = -1) -> list[dict[str, Any]]:
    """The results one report holds, each decoded, in its round's call order.

    Args:
        call: The round's call, as the fake completer recorded it.
        step: Which earlier round's report, by its index among the steps.

    Returns:
        Each call's result, as code rendered it.
    """
    return [json.loads(one.text) for one in call.exchange.steps[step].report.results]


def request_view(exchange: PlanningExchange) -> dict[str, Any]:
    """A round's exchange read as one request, as a test that routes on it reads it.

    The briefing, decoded, with what the reports since brought laid over it: ``rounds``
    is each earlier round's text and calls, each call with its arguments and its result;
    ``offers`` are the offers open now, those the briefing showed and those news opened,
    less those news closed; ``earlier_work`` and ``understanding`` are the latest the news
    brought; the evidence each result and each news carried joins ``evidence``; and a
    round whose text news says was never written carries that as ``text_was``. A
    waiting round is only ever a work's first, so ``waiting_on`` goes once there are
    steps. This reads what the exchange shows; it is no request any round is sent.

    Args:
        exchange: The exchange a round was asked with.

    Returns:
        The request as one object.
    """
    view: dict[str, Any] = json.loads(exchange.briefing)
    offers: list[Any] = list(view.get("offers") or ())
    evidence: list[Any] = list(view.get("evidence") or ())
    earlier: dict[str, Any] = {one["episode"]: one for one in view.get("earlier_work") or ()}
    rounds: list[dict[str, Any]] = []
    for number, step in enumerate(exchange.steps, 1):
        calls: list[dict[str, Any]] = []
        for call, result in zip(step.response.calls, step.report.results, strict=True):
            shown = json.loads(result.text)
            evidence.extend(shown.get("evidence") or ())
            calls.append(
                {"capability": call.name, "arguments": call.model_dump()["arguments"], **shown}
            )
        rounds.append({"round": number, "text": step.response.text, "calls": calls})
        try:
            news = json.loads(step.report.news)
        except ValueError:
            continue
        if "text_was" in news:
            rounds[-1]["text_was"] = news["text_was"]
        offers.extend(news.get("offers_open") or ())
        closed = set(news.get("offers_closed") or ())
        offers = [one for one in offers if one.get("offer") not in closed]
        earlier |= {one["episode"]: one for one in news.get("earlier_work") or ()}
        if "understanding" in news:
            view["understanding"] = news["understanding"]
        view["place_window"] = [*view.get("place_window", []), *(news.get("place_window") or ())]
        evidence.extend(news.get("evidence") or ())
    view["rounds"] = rounds
    view["evidence"] = evidence
    if offers:
        view["offers"] = offers
    else:
        view.pop("offers", None)
    if earlier:
        view["earlier_work"] = list(earlier.values())
    if exchange.steps:
        view.pop("waiting_on", None)
    return view


def news(call: RoundCall, step: int = -1) -> dict[str, Any] | str:
    """The news one report holds: decoded, or the line that says nothing changed.

    Args:
        call: The round's call, as the fake completer recorded it.
        step: Which earlier round's report, by its index among the steps.

    Returns:
        What changed, by kind, or the sentence saying nothing did.
    """
    text = call.exchange.steps[step].report.news
    try:
        decoded = json.loads(text)
    except ValueError:
        return text
    return decoded if isinstance(decoded, dict) else text
