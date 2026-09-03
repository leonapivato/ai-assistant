"""No browser route reaches the audit trail (ADR-0186 §6, ADR-0177 §1).

ADR-0186 §1 puts two operations on the promoted engine surface, and §6 rules that
neither is one of ADR-0177 §1's **thirty**: "No browser request resolves to either,
no browser argument reaches either, and the gateway makes neither call of its own."
That is the property ADR-0168 §6 wanted when it chose to name what may appear rather
than what may not — a method added to the Protocol is outside the enumeration until
an ADR puts it inside — and this module is what makes it a fact rather than a
reading of the router.

**Later rather than never, and the reason is sequencing rather than doubt**
(ADR-0186 §6). A browser history view is a later consumer lane with its own ratified
decision, which widens §1's enumeration in its own text — the route ADR-0177 §1's
third clause fixes for ``learn`` and ADR-0175 §6's third clause fixes generally. It
inherits ADR-0186 §7's rendering floor and §8's bars without restating them.

Both halves are asserted, because either alone is weak. The table says the
enumeration does not name them; the driven requests say the router really answers
nothing for the shapes a lane would reach for, and — the half that matters — that
the **engine is not reached** on the way to saying so (ADR-0168 §1's biconditional).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from test_gateway_streams import Harness, _harness

from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

#: The two operations, as ``wire/surface.py`` reads them off the Protocol.
_AUDIT_READS = frozenset({"recent_decisions", "export_decisions"})

#: The paths a lane building the browser view would reach for first. Not a claim
#: that these are the paths that view will one day take — that is the later lane's
#: ADR to decide — only that today the router resolves none of them.
_UNSERVED = [
    "/decisions",
    "/decisions/recent",
    "/decisions/export",
    "/audit",
    "/audit/recent",
    "/audit/export",
]


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    """A gateway on ADR-0168 §8's and ADR-0175 §8's own figures."""
    async with _harness() as one:
        yield one


def test_neither_audit_read_is_in_the_enumeration() -> None:
    """ADR-0186 §6: neither is one of ADR-0177 §1's thirty.

    Read off the one table the gateway classifies from, so the ADR and the code are
    one thing to compare rather than two — ``test_gateway_connections``' own form for
    the five that *are* admitted.

    **The count of thirty does not move for this**, and that is the point rather than
    an omission: §1's enumeration counts what a browser may reach, and ADR-0186 adds
    two operations to the *promoted surface* while adding none to it. The dated note
    ADR-0186 §13 places on ADR-0177 records exactly that distinction.
    """
    reached = set(_ASSISTANT_PATHS.values())

    assert not (_AUDIT_READS & reached)


@pytest.mark.parametrize("path", _UNSERVED)
async def test_a_browser_request_naming_the_trail_is_refused(harness: Harness, path: str) -> None:
    """ADR-0186 §6: no browser request resolves to either, and the engine is not reached.

    An admitted browser asking the assistant for nothing it serves is answered
    ``404`` and "the engine is not reached (ADR-0168 §1's biconditional)". The second
    assertion is the one that would catch the interesting failure: a router that
    resolved one of these onto a *neighbouring* operation would answer ``200`` here
    and leave a call behind, and a reader checking only the status would not see it.
    """
    status, body = await harness.whole("POST", path, {})

    assert status == 404, body
    assert harness.engine.calls == []
