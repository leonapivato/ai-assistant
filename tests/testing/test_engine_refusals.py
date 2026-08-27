"""What the canonical fake engine *says* when it refuses a token (#1653).

:class:`~ai_assistant.testing.FakeAssistantEngine` passes the shared
``AssistantEngine`` suite in ``tests/orchestration/test_fake_engine.py``, and that
suite holds it to the contract: an unresolvable token raises
``UnknownContinuationError`` and never a denial (ADR-0084 §7). It does not — and
should not — pin the *message*, because message text is not part of the Protocol.

But the fake is what every interface adapter's tests are written against, so a
surface that renders the error's text learns its remedy from here. ADR-0197 §7 rules
that ``pending_confirmations`` "does **not** list a routed park", so a refusal naming
only that remedy teaches the one route back that cannot help a routed token. These
tests pin the two remedies the sentence has to carry, and nothing about how it is
worded.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from ai_assistant.core.errors import UnknownContinuationError
from ai_assistant.core.types import ContinuationToken, RoutableOperation
from ai_assistant.testing import FakeAssistantEngine

#: The caller's budget, which none of these paths spends: every refusal below is
#: decided from a table lookup before anything is awaited.
_TIMEOUT = timedelta(seconds=30)


async def test_a_claimed_routed_tokens_refusal_names_the_remedy_that_can_help() -> None:
    """ADR-0197 §7: a routed park is "claimed once, atomically", is never listed by
    ``pending_confirmations`` and is never recovered — so its remedy is §7's own
    sentence: nothing has happened yet, ask for the operation again rather than
    resuming this token.

    The fake pops the entry before it performs anything, so a second presentation of
    the same token reaches the unknown-token refusal — the very path a surface renders
    when a user double-taps a confirmation. Before #1653 that refusal named
    ``pending_confirmations`` alone, which for this token re-mints nothing.
    """
    engine = FakeAssistantEngine()
    held = engine.hold("rec-routed", content="the user likes jazz")
    engine.park_routed("routed-1", operation=RoutableOperation.FORGET, subject=(held,))
    token = ContinuationToken(handle="routed-1")
    await engine.resume(token, approved=True, timeout=_TIMEOUT)

    with pytest.raises(UnknownContinuationError) as refusal:
        await engine.resume(token, approved=True, timeout=_TIMEOUT)

    assert "ask for the operation again" in str(refusal.value)


async def test_the_refusal_still_names_the_step_parks_re_mint() -> None:
    """The routed remedy is added *beside* the step park's, not in place of it.

    At this point the two kinds of park are indistinguishable — one handle space, one
    method, and nothing left in either table to tell them apart — so the sentence
    states both routes back and lets the reader pick the one their token had.
    """
    engine = FakeAssistantEngine()

    with pytest.raises(UnknownContinuationError) as refusal:
        await engine.resume(
            ContinuationToken(handle="h-never-minted"), approved=True, timeout=_TIMEOUT
        )

    assert "pending_confirmations()" in str(refusal.value)
    assert "ask for the operation again" in str(refusal.value)
