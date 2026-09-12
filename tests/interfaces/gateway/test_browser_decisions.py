"""What the page renders as a ruling's basis, driven in a real browser (ADR-0216 §1).

ADR-0247 §2's last normative clause is about what reaches a **reader**: "what a
surface renders for route (c) names the basis and quotes no identifier… it names no
origin, no host, no connection reference, no credential and no ``Settings`` field",
because ``BoundAccount.reference`` is *"never shown to the user"* (ADR-0148 §6, §8's
fourth clause). A route-(c) ``ALLOW`` records that reference as its ``authorised_by``,
so the clause is breached by a *rendering* and not by a value — and the assertion that
answers it is over the text on the screen rather than over the JSON behind it.

**That is why these cases are here and not only in ``test_gateway_routed.py``.** That
module pins what crosses the edge, which is the row and deliberately still carries the
pointer (ADR-0247 §8(d)); ``test_bundle.py`` pins that ``authorisationWords`` holds the
branch. Neither says what a reader sees, and the defect this lane fixes (#2256) was
exactly a value that crossed correctly and was then printed.

**One drive per viewport for the route-(c) case** (ADR-0233 §15's obligation on a
browser lane, read one surface over): the sentence replaces a line that ended in a
64-character-class identifier, so a width is a real variable in whether it is readable
whole.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from browser_drive import DESKTOP, PHONE, driving
from playwright.async_api import expect
from test_gateway_routed import _SEARCH_ACCOUNT, _decision, _routed, _search_binding

from ai_assistant.core.types import RoutableOperation, RouteOutcome

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, ConsoleMessage, ViewportSize

    from ai_assistant.core.types import PermissionDecision

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: The one console error a correct page produces, and it is the browser's rather than
#: the page's: a browser asks for a favicon on its own and admission is decided before
#: routing (ADR-0168 §3), so a session-less request to any path answers 401.
_BROWSERS_OWN_PROBE = "/favicon.ico"

#: ADR-0193 §11's second state, spelled as the page has always spelled it. Pinned as a
#: whole sentence because "route (b) is unchanged" is a claim about bytes.
_NAMES_A_GRANT = (
    "a standing authorisation this ruling names, recorded as g-1 (what the row names, and no more)"
)

#: ADR-0247 §2's line: the basis, and nothing that identifies what was configured.
_NAMES_THE_CONFIGURATION = (
    "this deployment's own configuration: its owner configured this search provider "
    "(the basis, and no identifier of it)"
)


def _note(message: ConsoleMessage, complaints: list[str]) -> None:
    """Keep every console error but the one the browser makes on its own."""
    if message.type == "error" and not message.location["url"].endswith(_BROWSERS_OWN_PROBE):
        complaints.append(f"{message.location['url']}: {message.text}")


async def _listed(drive: Drive, recorded: PermissionDecision) -> str:
    """Route one ask to the decisions listing over ``recorded`` and read the screen.

    The turn is the page's own: the utterance is typed into the page's field and
    submitted through the page's form, and what comes back is the routed account
    ``renderRouted`` writes below the reply (ADR-0197 §10).

    **Unstreamed**, because the subject is the rendered listing and not the transport:
    the streamed entry composes the same terminal outcome through a second path, and a
    case waiting on chunks would be measuring that instead.

    Args:
        drive: The gateway, engine and page under test.
        recorded: The one ruling the routed pass lists.

    Returns:
        Everything the answer panel is saying, listing included.
    """
    drive.engine.turn_outcome = _routed(
        RoutableOperation.RECENT_DECISIONS, RouteOutcome.PERFORMED, listing=(recorded,)
    )
    await drive.page.uncheck("#stream-answer")
    await drive.page.fill("#utterance", "what have you been allowed to do")
    await drive.page.click("#ask-form button[type=submit]")
    await expect(drive.page.locator("#ask-button")).to_be_enabled()
    return await drive.answer()


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_route_c_ruling_names_the_basis_and_the_reference_is_nowhere_on_the_screen(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0247 §2's last normative clause, read where a reader reads it.

    The row is the one that clause is about: a non-resolving ``ALLOW`` whose
    ``authorised_by`` is the binding's ``account.reference``, whose
    ``authorised_subject`` is unset, and whose binding is closed-loop. Before this lane
    the page printed that reference verbatim under ADR-0193 §11's second state, which
    ADR-0148 §6 bars from every surface (#2256).

    **The reference is asserted absent from the whole panel**, not from one line: a
    rendering that moved it into a neighbouring line would satisfy a line assertion and
    breach the clause just as squarely. The account's **identity** and the canonical
    destination are not asserted absent — ADR-0186 §7 obliges the recorded binding to be
    rendered whole, and ADR-0247 §8(d) has an auditor read the account and origin off the
    row; what §2 withholds is the basis text's identifiers and the reference itself.
    """
    thrown: list[str] = []
    complaints: list[str] = []
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.page.on("console", lambda message: _note(message, complaints))

        said = await _listed(
            drive,
            _decision(
                authorised_by=_SEARCH_ACCOUNT.reference,
                resolves=None,
                binding=_search_binding(),
            ),
        )

        assert f"Authorised by: {_NAMES_THE_CONFIGURATION}" in said
        assert _SEARCH_ACCOUNT.reference not in said
        assert "standing authorisation" not in said
        assert thrown == []
        assert complaints == []


async def test_a_standing_row_that_fingerprints_its_grant_renders_exactly_as_it_did(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Route (b) is untouched, asserted over the shape a ``closed_loop`` branch breaks.

    ADR-0247 §2: ``closed_loop`` is route (c)'s **eligibility** and the digest is its
    **discriminator**, and "neither does the other's job". ADR-0238 permits a
    grant-covered ``ALLOW`` over a closed-loop binding, and that row is route (b) because
    it carries a digest — so a page branching on ``closed_loop`` alone would stop naming
    the grant this row rests on, and this is the case that would see it.

    The digest itself is asserted absent from the screen: it crosses so that the page can
    tell the routes apart, and ADR-0193 §11's fifth clause permits rendering it opaque or
    **not at all**, which is what this page does.
    """
    thrown: list[str] = []
    complaints: list[str] = []
    async with driving(gateway_browser, tmp_path) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.page.on("console", lambda message: _note(message, complaints))

        said = await _listed(
            drive,
            _decision(
                authorised_by="g-1",
                resolves=None,
                authorised_subject="b" * 64,
                binding=_search_binding(),
            ),
        )

        assert f"Authorised by: {_NAMES_A_GRANT}" in said
        assert "b" * 64 not in said
        assert thrown == []
        assert complaints == []
