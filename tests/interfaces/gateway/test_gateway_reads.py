"""No browser route reaches the read trail (ADR-0186 §10, §6, ADR-0177 §1).

ADR-0186 §10 puts two more operations on the promoted engine surface —
``recent_reads`` and ``export_reads``, over ADR-0185 §12's ``SourceReadTrail``. No
browser request resolves to either, no browser argument reaches either, and the
gateway makes neither call of its own.

**That bar is ADR-0177 §1's own and is not inherited from ADR-0186 §6.** §10's
inheritance list is closed — §2, §3, §7's last two clauses, §8's three bars — and
does not name §6, whose text is written about the operations §1 mints. It does not
need to. §1's *first* clause is an explicit closed enumeration, "exactly these
**thirty** … and no others", which governs every method it does not name, and
ADR-0186's own Context states the general rule: "A method added to the Protocol is
therefore outside that enumeration until an ADR puts it inside, which is the
property ADR-0168 §6 wanted when it chose to name what may appear rather than what
may not." §6 is that conclusion drawn for the decision pair; this module is the same
conclusion checked for the read pair.

**A closed enumeration is a claim about a table, so it is worth checking against the
table.** The rule above makes the bar true by construction, which is exactly the
condition under which nobody looks — and the table lives in ``gateway/server.py``
while the rule lives in an ADR. This module is what keeps the two comparable.

**Later rather than never** (ADR-0186 §6). A browser view of either trail is a later
consumer lane with its own ratified decision, which widens §1's enumeration in its
own text — the route ADR-0177 §1's third clause fixes for ``learn`` and ADR-0175 §6's
third clause fixes generally. It would inherit ADR-0186 §7's rendering floor and §8's
bars, minus the egress content floor §10 rules out for a read record.

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
_TRAIL_READS = frozenset({"recent_reads", "export_reads"})

#: The paths a lane building the browser view would reach for first. Not a claim
#: that these are the paths that view will one day take — that is the later lane's
#: ADR to decide — only that today the router resolves none of them.
_UNSERVED = [
    "/reads",
    "/reads/recent",
    "/reads/export",
    "/source-reads",
    "/source-reads/recent",
    "/source-reads/export",
]


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    """A gateway on ADR-0168 §8's and ADR-0175 §8's own figures."""
    async with _harness() as one:
        yield one


def test_neither_read_trail_operation_is_in_the_enumeration() -> None:
    """ADR-0177 §1: neither is one of the thirty a browser may reach.

    Read off the one table the gateway classifies from, so the ADR and the code are
    one thing to compare rather than two.

    **The count of thirty does not move for this**, and that is the point rather than
    an omission: §1's enumeration counts what a browser may reach, and ADR-0186 adds
    these two to the *promoted surface* while adding none to it. The dated note this
    change appends to ADR-0177 records exactly that distinction, and retires the
    running count of promoted-but-unreachable operations rather than moving it again.
    """
    reached = set(_ASSISTANT_PATHS.values())

    assert not (_TRAIL_READS & reached)


@pytest.mark.parametrize("path", _UNSERVED)
async def test_a_browser_request_naming_the_read_trail_is_refused(
    harness: Harness, path: str
) -> None:
    """ADR-0177 §1 driven rather than read: nothing resolves, and the engine is untouched.

    An admitted browser asking the assistant for nothing it serves is answered
    ``404`` and "the engine is not reached (ADR-0168 §1's biconditional)". The second
    assertion is the one that would catch the interesting failure: a router that
    resolved one of these onto a *neighbouring* operation would answer ``200`` here
    and leave a call behind, and a reader checking only the status would not see it.

    A ``404`` rather than a ``401`` is itself the evidence the request was
    **admitted**: admission is decided before routing, so a session-less request to
    any path answers ``401``. These reached the router and it had nothing for them.
    """
    status, body = await harness.whole("POST", path, {})

    assert status == 404, body
    assert harness.engine.calls == []
