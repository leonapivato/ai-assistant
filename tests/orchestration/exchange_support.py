"""What a planning round was shown, read off the exchange it was asked with (ADR-0356 §3, §5).

A work's first round is asked with the briefing: tagged text in a fixed order of sections
(§3:1), each item in a tag whose attributes say who or what it is from (ADR-0353 §3). A
later round is asked with that briefing, byte for byte, and a report after each earlier
round: each call's result, then the news (§5:3-§5:5). A test that asserts what a round
was shown reads it here: a section of the briefing by its heading, the tags a text holds,
each call's result decoded, and the news as its lines.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ai_assistant.core.types import ProposedCall, RoundResponse

if TYPE_CHECKING:
    from ai_assistant.core.types import PlanningExchange
    from ai_assistant.testing.tool_calling import RoundCall

#: One tag's opening: its name and its attributes, and whether it closes itself.
_OPEN = re.compile(r"<([a-z_]+)((?:\s+[a-z_]+=\"[^\"]*\")*)\s*(/?)>")
_ATTRIBUTE = re.compile(r"([a-z_]+)=\"([^\"]*)\"")


@dataclass(frozen=True, slots=True)
class Tag:
    """One tag of the briefing, a report or the news, as a test reads it.

    Attributes:
        name: The tag's name: ``said``, ``memory``, ``episode`` and so on.
        attributes: Its attributes, unescaped.
        text: What it holds, unescaped: a text tag's words, or a container's tags as
            they were written; ``None`` for an empty tag.
        tags: The tags a container holds, in order; empty for a text tag.
    """

    name: str
    attributes: dict[str, str] = field(default_factory=dict)
    text: str | None = None
    tags: tuple[Tag, ...] = ()

    def get(self, key: str) -> str | None:
        """One attribute, or ``None`` where the tag does not carry it."""
        return self.attributes.get(key)

    def held(self, name: str) -> list[Tag]:
        """The tags of ``name`` this container holds, at any depth, in order."""
        return [one for one in walk(self.tags) if one.name == name]


def walk(found: tuple[Tag, ...] | list[Tag]) -> list[Tag]:
    """Every tag of ``found`` and every tag each holds, in document order."""
    every: list[Tag] = []
    for one in found:
        every.append(one)
        every.extend(walk(one.tags))
    return every


def tags(text: str, name: str | None = None, **attributes: str) -> list[Tag]:
    """The top-level tags ``text`` holds, or, with ``name``, every tag of that name at any depth.

    Args:
        text: A briefing, a section of one, a result's value or the news.
        name: The tag name to keep; ``None`` keeps the top-level tags.
        **attributes: Attributes each kept tag carries, with these values.

    Returns:
        The tags, in document order.
    """
    found = _parse(text, 0)[0]
    kept = found if name is None else [one for one in walk(found) if one.name == name]
    return [
        one
        for one in kept
        if all(one.attributes.get(key) == value for key, value in attributes.items())
    ]


def tag(text: str, name: str, **attributes: str) -> Tag:
    """The one tag of ``name`` with these attributes ``text`` holds.

    Raises:
        AssertionError: If it holds none, or more than one.
    """
    found = tags(text, name, **attributes)
    assert len(found) == 1, f"{len(found)} <{name}> tags with {attributes}"
    return found[0]


def labels(text: str, name: str | None = None) -> list[str]:
    """The ``label`` of every tag of ``name`` (any, where ``None``) that carries one."""
    every = walk(_parse(text, 0)[0])
    return [
        label
        for one in every
        if (name is None or one.name == name) and (label := one.get("label")) is not None
    ]


def _parse(text: str, start: int, closing: str | None = None) -> tuple[list[Tag], int]:
    found: list[Tag] = []
    at = start
    while True:
        opened = _OPEN.search(text, at)
        close_at = -1 if closing is None else text.find(f"</{closing}>", at)
        if closing is not None and close_at != -1 and (opened is None or close_at < opened.start()):
            return found, close_at + len(closing) + 3
        if opened is None:
            if closing is not None:
                msg = f"<{closing}> is never closed"
                raise AssertionError(msg)
            return found, len(text)
        name, written, empty = opened.group(1), opened.group(2), opened.group(3)
        attributes = {key: html.unescape(value) for key, value in _ATTRIBUTE.findall(written)}
        if empty:
            found.append(Tag(name, attributes))
            at = opened.end()
            continue
        end = text.find(f"</{name}>", opened.end())
        if end == -1:
            msg = f"<{name}> is never closed"
            raise AssertionError(msg)
        inner = text[opened.end() : end]
        if _OPEN.search(inner) is not None:
            held, at = _parse(text, opened.end(), name)
            found.append(Tag(name, attributes, inner, tuple(held)))
            continue
        found.append(Tag(name, attributes, html.unescape(inner)))
        at = end + len(name) + 3


def section(briefing: str, heading: str) -> str:
    """The text under one heading of the briefing, up to the next heading of any level.

    Args:
        briefing: The briefing.
        heading: The heading, as written: ``## Short-term memory``.

    Returns:
        The lines under it, without the heading, stripped.

    Raises:
        AssertionError: If the briefing holds no such heading.
    """
    lines = briefing.split("\n")
    assert heading in lines, f"no heading {heading!r}"
    at = lines.index(heading) + 1
    held: list[str] = []
    for line in lines[at:]:
        if re.match(r"#{1,3} ", line):
            break
        held.append(line)
    return "\n".join(held).strip()


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


def every_result(exchange: PlanningExchange) -> list[dict[str, Any]]:
    """Every result every report of ``exchange`` holds, decoded, each with its call.

    Each carries ``capability`` and ``arguments``, the call's as its round proposed it,
    beside what came of it, in the order the rounds proposed them.
    """
    results: list[dict[str, Any]] = []
    for step in exchange.steps:
        for call, result in zip(step.response.calls, step.report.results, strict=True):
            results.append(
                {
                    "capability": call.name,
                    "arguments": call.model_dump()["arguments"],
                    **json.loads(result.text),
                }
            )
    return results


def news(call: RoundCall, step: int = -1) -> str:
    """The news one report holds, as text: its lines, or the line that says nothing changed.

    Args:
        call: The round's call, as the fake completer recorded it.
        step: Which earlier round's report, by its index among the steps.

    Returns:
        The news.
    """
    return call.exchange.steps[step].report.news


def text_call(
    words: str, *, call_id: str = "say", connection: str = "L1", **arguments: object
) -> ProposedCall:
    """A ``send_text`` call into a connection, carrying ``words`` (ADR-0364 §9:1).

    A round's own text is its notes alone (ADR-0356 §7:3): what reaches a person comes
    only from a message call, so a scripted round that answers the person makes this.
    ``connection`` is the connection's ``L`` label: ``L1``, the stimulus's origin, which its
    ``where`` names first, unless the case names another. ``arguments`` are any more.
    """
    return ProposedCall(
        call_id=call_id,
        name="send_text",
        arguments={"connection": connection, "words": words, **arguments},  # type: ignore[dict-item]  # JSON values
    )


def says(*words: str, text: str = "", call_id: str = "say") -> RoundResponse:
    """A round that sends each of ``words`` to the user, one ``text`` call each, in order.

    The first call is ``call_id``, each after it ``call_id`` with its ordinal (``say-2``).
    An exchange's call ids are distinct across its steps, so a case scripting two such
    rounds names the second's ``call_id``.
    ``text`` is the round's notes, which reach no one.
    """
    return RoundResponse(
        text=text,
        calls=tuple(
            text_call(one, call_id=call_id if at == 0 else f"{call_id}-{at + 1}")
            for at, one in enumerate(words)
        ),
    )
