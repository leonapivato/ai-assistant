"""The exact line's test for every capability (ADR-0321 §2:7, §8:10).

For every capability the composition root registers and planning is offered, a call
sending a value for every argument its selected declaration takes is asked about, and
its exact line must show every one of them but those §2:5 leaves out: the arguments the
offered declaration names in ``system_supplied``, the *looking for* and the *deliberate
repeat* mark. The capabilities are read from a deployment that configures every
provider, so a capability added later is covered without a change here.

**Nothing here opens a socket.** The engine is built over a hashing embedder and closed;
every configured origin is an ``.invalid`` one (RFC 6761 §6.4), and no transport is
driven.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from test_planning import _earlier, _inputs, _stage

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import ActionRequest, ProposedCall, RoundResponse
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.orchestration.planning import (
    DELIBERATE_REPEAT,
    LOOKING_FOR,
    CallOutcome,
    CallOutcomeKind,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.types import ToolDefinition

#: The capabilities a deployment configuring every provider must offer, so this test
#: cannot pass over a configuration that registered none of them.
_FLOOR: Final = frozenset(
    {"send_email", "book_stay", "booking_availability", "web_search", "remember"}
)


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
    """Each offered capability's offered declaration, and the one tool selection picks."""
    engine = build_engine(_everything(), data_dir=tmp_path)
    try:
        phases = engine._phases
        assert isinstance(phases, PhasePath)
        offered: dict[str, ToolDefinition] = {}
        for tool in sorted(await phases._offered(), key=lambda one: str(one.id)):
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
    calls = tuple(
        ProposedCall(call_id=f"c{n}", name=str(offered.capability))
        for n, (offered, _) in enumerate(pairs, 1)
    )
    earlier = _earlier(calls=calls)
    sent = [_every_argument(selected) for _, selected in pairs]
    outcomes = tuple(
        CallOutcome(
            earlier.id,
            call.call_id,
            CallOutcomeKind.NEEDS_YOU,
            request=ActionRequest(tool=selected, parameters=values),
        )
        for call, (_, selected), values in zip(calls, pairs, sent, strict=True)
    )
    asks = tuple(f"1.{n}" for n in range(1, len(pairs) + 1))
    stage, _, _ = _stage(RoundResponse(text="Shall I?", asks=asks))
    planned = await stage.plan(
        _inputs(
            capabilities=tuple(offered for offered, _ in pairs),
            rounds=(earlier,),
            outcomes=outcomes,
        )
    )
    assert len(planned.round.asked) == len(pairs)
    lines = planned.round.text.splitlines()[-len(pairs) :]
    missing: dict[str, list[str]] = {}
    for number, ((offered, _), values, line) in enumerate(zip(pairs, sent, lines, strict=True), 1):
        name = str(offered.capability)
        assert line.startswith(f"{number}. {name}"), line
        left_out = {*offered.system_supplied, LOOKING_FOR, DELIBERATE_REPEAT}
        for argument, value in values.items():
            shown = f"{argument}: {json.dumps(value, ensure_ascii=False)}" in line
            if shown is (argument in left_out):
                missing.setdefault(name, []).append(argument)
    assert missing == {}, "arguments shown or left out wrongly, by capability"
