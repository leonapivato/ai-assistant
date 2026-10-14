"""The CLI's conversation listing and forgetting, over the root with the phases.

``test_cli`` drives these cases over conversations ``ask`` started, which retires at the
cutover (ADR-0309 §5:1); a conversation is then one the chat's reader answers on. Each
case here is one of ``test_cli``'s over the production root with its phases wired,
the conversations started by messages: the listing shows what a person chooses from and
never a deleted one, and forgetting shows the count and span before destroying, or
leaves the conversation alone (ADR-0074 §2, §8; ADR-0293 §2:4, §5:7).
"""

from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING

import pytest
from phases_composition_support import Phased, build_phased
from rich.console import Console

from ai_assistant.interfaces import cli

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from ai_assistant.core.types import ConversationDigest

pytestmark = pytest.mark.integration


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=100))
    return buffer


@pytest.fixture
async def composed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Phased]:
    """The production root with the phases, over a fresh data directory, started."""
    built = build_phased(tmp_path, monkeypatch)
    await built.engine.start()
    try:
        yield built
    finally:
        await built.engine.aclose()


def _cleared(output: StringIO) -> None:
    output.truncate(0)
    output.seek(0)


def _flat(rendered: str) -> str:
    """The rendered text with its wrapping undone, so a sentence reads as one line."""
    return " ".join(rendered.replace("↳", " ").split())


def _assert_prompt_shown(rendered: str, expected: ConversationDigest, turns: int) -> None:
    """ADR-0074 §8's count and span and ADR-0293 §5:7's disclosure are already on screen.

    Called from inside ``confirm``, so what it reads is what the person saw before
    answering. The span's ends are the digest read before the command ran, rendered as
    the surface renders an instant; the count is the exact line, not any ``2`` the
    output happens to carry (a date has several).
    """
    assert expected.last_turn_at is not None
    lines = [line.strip() for line in rendered.splitlines()]
    assert "About to forget this conversation" in lines
    assert expected.id in lines
    assert f"Started: {cli._when(expected.started_at)}" in lines
    assert f"Turns recorded: {turns}, the last at {cli._when(expected.last_turn_at)}" in lines
    # ADR-0293 §5:7: what forgetting removes, that the conversation is still read,
    # and that only deleting removes it — said before the answer is taken.
    flat = _flat(rendered)
    assert "Forgetting removes its episodes from the assistant's memory" in flat
    assert "so it no longer recalls them anywhere else" in flat
    assert "the assistant still reads it while you keep talking there" in flat
    assert "only deleting removes it." in flat
    assert "Forgotten." not in flat
    assert "Left alone" not in flat


async def test_the_conversations_listing_shows_what_a_person_chooses_from(
    composed: Phased, output: StringIO
) -> None:
    """§2: the id, when it started, and when it was last active."""
    started = (await composed.say("hello")).conversation_id
    _cleared(output)

    code = await cli._drive_conversations(composed.engine, limit=50, offset=0)

    assert code == 0
    rendered = output.getvalue()
    assert started in rendered
    assert "Last active" in rendered


async def test_the_conversations_listing_never_shows_a_deleted_conversation(
    composed: Phased, output: StringIO
) -> None:
    """§8: not because this surface filters, but because the stamp hides it."""
    stamped = (await composed.say("hello")).conversation_id
    assert await composed.conversations.stamp_deleted(stamped) is True
    _cleared(output)

    await cli._drive_conversations(composed.engine, limit=50, offset=0)

    assert stamped not in output.getvalue()
    assert "No conversations yet" in output.getvalue()


async def test_forget_conversation_shows_the_count_and_span_before_destroying(
    composed: Phased, output: StringIO
) -> None:
    """§8: the ceremony is the count and span, not every turn — what a person can judge."""
    existing = (await composed.say("hello")).conversation_id
    await composed.say("again", existing)
    expected = await composed.engine.conversation(existing)
    assert expected is not None
    _cleared(output)
    asked: list[ConversationDigest | None] = []

    def confirm(digest: ConversationDigest | None) -> bool:
        # ADR-0074 §8: shown before consent is taken, so pinned here, not at the end.
        asked.append(digest)
        assert digest is not None
        assert digest.recorded_turns == 2
        assert digest == expected
        _assert_prompt_shown(output.getvalue(), expected, turns=2)
        return True

    code = await cli._drive_forget_conversation(composed.engine, existing, confirm=confirm)

    assert code == 0
    assert len(asked) == 1
    rendered = output.getvalue()
    assert "About to forget this conversation" in rendered
    assert "Turns recorded: 2," in rendered
    assert "Forgotten." in rendered
    # ADR-0293 §5:7's plain disclosure, before and after: what forgetting removes,
    # that the conversation is still read, and that only deleting removes it.
    flat = _flat(rendered)
    assert "removes its episodes from the assistant's memory" in flat
    assert "still reads it while you keep talking there" in flat
    assert "only deleting removes them." in flat
    assert "destroys the conversation" not in flat
    # ADR-0293 §2:4, §11:4: forgetting is memory-only, so the conversation stays.
    assert await composed.conversations.get(existing) is not None
    assert await composed.held(existing) == []


async def test_forget_conversation_leaves_it_alone_when_the_answer_is_no(
    composed: Phased, output: StringIO
) -> None:
    """A refusal is a valid outcome, and it exits 0 — nothing went wrong."""
    existing = (await composed.say("hello")).conversation_id
    expected = await composed.engine.conversation(existing)
    assert expected is not None
    _cleared(output)
    asked: list[ConversationDigest | None] = []

    def confirm(digest: ConversationDigest | None) -> bool:
        # The refusal is to something shown: the prompt is on screen before the no.
        asked.append(digest)
        assert digest is not None
        assert digest.recorded_turns == 1
        assert digest == expected
        _assert_prompt_shown(output.getvalue(), expected, turns=1)
        return False

    code = await cli._drive_forget_conversation(composed.engine, existing, confirm=confirm)

    assert code == 0
    assert len(asked) == 1
    assert "Left alone" in output.getvalue()
    assert await composed.conversations.get(existing) is not None
    assert len(await composed.held(existing)) == 1
