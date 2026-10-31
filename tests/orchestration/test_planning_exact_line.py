"""The exact line's test for every capability (ADR-0321 §2:7, §8:10).

For every capability the composition root registers and planning is offered, a call
sending a value for every argument its selected declaration takes has its exact line
rendered, as an approved action's details are, and the line must show every one of them
but those §2:5 leaves out: the arguments the offered declaration names in
``system_supplied``, the *looking for* and the *deliberate repeat* mark. No message asks
about a call by name any more (ADR-0356 §7:5), so the line is rendered directly. The
capabilities are read from a deployment that configures every provider and keeps the
person model, so a capability added later is covered without a change here. An argument
naming a memory by its id, as a ``pin``'s does, is read as the memory's wording, which
its line shows in the id's place (ADR-0338 §8:6).

**Nothing here opens a socket.** The engine is built over a hashing embedder and closed;
every configured origin is an ``.invalid`` one (RFC 6761 §6.4), and no transport is
driven.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import AskedCall
from ai_assistant.orchestration.matter_calls import MATTER_CAPABILITIES
from ai_assistant.orchestration.person_calls import worded_argument
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.orchestration.planning import DELIBERATE_REPEAT, LOOKING_FOR, exact_line
from ai_assistant.orchestration.task_scheduler import TASK_SCHEDULER_CAPABILITIES

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.types import ToolDefinition

#: The capabilities a deployment configuring every provider must offer, so this test
#: cannot pass over a configuration that registered none of them.
_FLOOR: Final = frozenset(
    {
        "email",
        "book_stay",
        "booking_availability",
        "web_search",
        "remember",
        "set_profile",
        "pin",
        "unpin",
    }
)

#: The wording a memory an argument names by id is shown by (ADR-0338 §8:6).
_WORDING: Final = "Eats no meat."


def _everything() -> Settings:
    """A deployment that configures every provider whose capability planning is offered."""
    return Settings(
        embedder=EmbedderKind.HASHING,
        web_search_connection="conn-search-0001",
        web_search_origin="https://search.example.invalid",
        send_email_connection="conn-mail-0001",
        send_email_endpoint="smtps://mail.example.invalid:465",
        booking_connection="conn-booking-0001",
        booking_endpoint="https://bookings.example.invalid",
        booking_available_from=date(2026, 10, 1),
        booking_available_to=date(2026, 10, 7),
        booking_price_amount=Decimal("120.00"),
        booking_price_currency="EUR",
        booking_billed_amount=Decimal("140.00"),
        booking_billed_currency="EUR",
        booking_retained_records=3,
        # ADR-0338 §11:2: the person model's switch, which offers its three calls.
        person_model=True,
    )


def _value(name: str, schema: dict[str, Any]) -> object:
    """A value the schema admits, distinct per argument so its line can be checked."""
    for combinator in ("anyOf", "oneOf"):
        if combinator in schema:
            return _value(name, schema[combinator][0])
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "array":
        item = _value(f"{name} item", schema.get("items", {"type": "string"}))
        return [item] * max(schema.get("minItems", 1), 1)
    if kind == "string" and (schema.get("format") == "date" or "pattern" in schema):
        return "2026-10-02"
    text = f"the {name} value"
    scalars: dict[object, object] = {
        "string": text[: schema.get("maxLength", len(text))],
        "integer": int(schema.get("minimum", 1)),
        "number": (schema.get("minimum", 0.0) + schema.get("maximum", 2.0)) / 2,
        "boolean": True,
    }
    return scalars.get(kind, {})


def _every_argument(tool: ToolDefinition) -> dict[str, Any]:
    schema = tool.model_dump(mode="json")["parameters_schema"]
    return {name: _value(name, one) for name, one in schema.get("properties", {}).items()}


async def _registered(tmp_path: Path) -> list[tuple[ToolDefinition, ToolDefinition]]:
    """Each offered capability's offered declaration, and the one tool selection picks.

    Every capability is offered on every round (ADR-0356 §4:3); the Task Scheduler's and
    the calls on running work are left out here, as this case covered them before, when
    they were offered only to an activation they could run in.
    """
    engine = build_engine(_everything(), data_dir=tmp_path)
    try:
        phases = engine._phases
        assert isinstance(phases, PhasePath)
        offered: dict[str, ToolDefinition] = {}
        for tool in sorted(await phases._offered(), key=lambda one: str(one.id)):
            if str(tool.capability) in TASK_SCHEDULER_CAPABILITIES | MATTER_CAPABILITIES:
                continue
            offered.setdefault(str(tool.capability), tool)
        pairs: list[tuple[ToolDefinition, ToolDefinition]] = []
        for name, declaration in sorted(offered.items()):
            selected = await phases._tools.find(name)
            pairs.append((declaration, selected[0] if selected else declaration))
        return pairs
    finally:
        await engine.aclose()


async def test_every_capabilitys_exact_line_shows_every_argument_it_sends(
    tmp_path: Path,
) -> None:
    """§8:10: every argument but those the hub fills and the two marks, for every one."""
    pairs = await _registered(tmp_path)
    assert {str(offered.capability) for offered, _ in pairs} >= _FLOOR
    sent = [_every_argument(selected) for _, selected in pairs]
    worded = [worded_argument(str(offered.capability)) for offered, _ in pairs]
    lines = [
        exact_line(
            AskedCall(part=number, tool=selected, values=values),
            filled={*offered.system_supplied, *selected.system_supplied},
            numbered=True,
            worded={} if argument is None else {argument: _WORDING},
        )
        for number, ((offered, selected), values, argument) in enumerate(
            zip(pairs, sent, worded, strict=True), 1
        )
    ]
    missing: dict[str, list[str]] = {}
    for number, ((offered, _), values, line, by_wording) in enumerate(
        zip(pairs, sent, lines, worded, strict=True), 1
    ):
        name = str(offered.capability)
        assert line.startswith(f"{number}. {name}"), line
        left_out = {*offered.system_supplied, LOOKING_FOR, DELIBERATE_REPEAT}
        for argument, value in values.items():
            # §8:6: the memory an argument names is read as its wording, the argument sent.
            read_as = _WORDING if argument == by_wording else value
            shown = f"{argument}: {json.dumps(read_as, ensure_ascii=False)}" in line
            if shown is (argument in left_out):
                missing.setdefault(name, []).append(argument)
    assert missing == {}, "arguments shown or left out wrongly, by capability"
