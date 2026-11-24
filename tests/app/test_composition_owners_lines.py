"""The composition root wires the owner's permission lines (ADR-0376 §4, ADR-0381 §2:1).

The engine's four members for lines answer from the **same** line store the authorizer's
check reads, kept on its own file across starts, against every tool the hub's phases
declare and every connection the hub holds as it starts that a line may name: the system's
own chat, the line's place where it is configured, and each account connection it
registers, and never the schedule or the approvals (ADR-0376 §2:4).

**Nothing here opens a socket.** Every case builds over the hashing embedder and closes
what it built.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.app import build_composition, build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    APPROVALS_CONNECTION,
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    SCHEDULE_CONNECTION,
    GrantHow,
    MakeLineOutcome,
    MakeLineRefusal,
    Sureness,
)
from ai_assistant.orchestration.message_tools import TEXT_CALL
from ai_assistant.permissions import SqlitePermissionLineStore

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio

_BOT: Final = "conn-bot"
_CHAT: Final = 424242
_LINE_PLACE: Final = f"telegram:{_BOT}/{_CHAT}"


def _line_settings() -> Settings:
    return Settings(embedder=EmbedderKind.HASHING, telegram_connection=_BOT, telegram_user_id=_CHAT)


async def test_the_engine_is_handed_the_line_store_the_check_reads(tmp_path: Path) -> None:
    """ADR-0376 §4:9: one store, so a line the owner makes is one the check weighs."""
    composed = build_composition(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        handed = composed.engine._lines
    finally:
        await composed.engine.aclose()

    assert isinstance(handed, SqlitePermissionLineStore)


async def test_a_line_made_is_listed_and_kept_across_starts(tmp_path: Path) -> None:
    """§4:2, §4:8: the made line on the line's place stands at the next start."""
    first = build_engine(_line_settings(), data_dir=tmp_path)
    try:
        made = await first.make_grant(
            who=OWNER_PERSON_ID,
            action=str(TEXT_CALL.capability),
            how=GrantHow.ALLOWED,
            bar=Sureness.NORMAL,
            thing=_LINE_PLACE,
            condition=OWN_CHAT_CONNECTION,
        )
    finally:
        await first.aclose()
    again = build_engine(_line_settings(), data_dir=tmp_path)
    try:
        listed = await again.permission_lines()
    finally:
        await again.aclose()

    assert made.outcome is MakeLineOutcome.MADE
    assert made.line is not None
    shown = [one for one in listed if one.made]
    assert [(one.line_id, one.thing, one.made_by) for one in shown] == [
        (made.line.id, _LINE_PLACE, OWNER_PERSON_ID)
    ]


async def test_every_declared_tool_with_a_default_grant_is_listed(tmp_path: Path) -> None:
    """§5:1, §3:1: ``text`` among them, as every hub's phases declare it last."""
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        listed = await engine.permission_lines()
    finally:
        await engine.aclose()

    defaults = {one.tool_id: one for one in listed if not one.made}
    assert str(TEXT_CALL.id) in defaults
    assert all(one.who == ANYONE_GROUP_ID for one in defaults.values())
    assert len(defaults) == len(listed)


@pytest.mark.parametrize("connection", [SCHEDULE_CONNECTION, APPROVALS_CONNECTION, _LINE_PLACE])
async def test_no_line_names_what_a_bare_hub_does_not_have_or_no_line_names(
    tmp_path: Path, connection: str
) -> None:
    """§2:4, §4:5: the schedule and the approvals are named by no line, and an unconfigured
    line's place is no connection the hub has."""
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        result = await engine.make_limit(
            who=ANYONE_GROUP_ID, action=str(TEXT_CALL.capability), thing=connection
        )
    finally:
        await engine.aclose()

    assert result.refusal is MakeLineRefusal.UNKNOWN_CONNECTION
