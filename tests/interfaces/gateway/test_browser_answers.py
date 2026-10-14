"""What this page does with an answer it cannot read (#1622, #2006, #2008, ADR-0216 §2).

``renderOutcome`` reads the outcome's members from its first lines, so a ``2xx``
that carries no ``outcome`` throws at the call site. The consent entry folds its own
throw into the shared guard (#2006), and getting that wrong resolves a park nothing
read — so the ending is driven here rather than only read. The Ask and push-to-talk
entries this module also drove retired with the Ask panel and push-to-talk (ADR-0309
§5:4, ADR-0313 §3:4), and their cases with them.

**That is what no reading of the file decides.** ``test_bundle.py`` can pin that the
guard is written at the call site and that the ending names the right sentence; what
it cannot say is where an exception raised four lines inside another function
*lands*, nor what is left on the screen afterwards. ADR-0216 §2 puts exactly that
here — "behaviour a reading of the file cannot decide" — so the cases below run the
page and read what the owner reads.

**One case here is not about an answer, and it is here because it is not a second
condition.** ``streamValues`` once read an answer stream as well as the delivery stream,
and #2008's misframed-line ending was two sentences at one condition; ADR-0293 §11
retired the answer stream, and the delivery stream's sentence is driven here still.

**The gateway's own answer, with only the body replaced.** Each case lets the
request reach the gateway, takes the response it wrote, and substitutes the body —
which is the condition #1622 names and the only one that is reachable: every ``2xx``
the gateway writes goes through ``_json_response``, so what produces this is a
truncated, reassembled or proxy-substituted body between the two ends. ADR-0216 §4's
clause is untouched: nothing here substitutes an *asset*, and the page is still
loaded from that gateway and no other origin.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from browser_drive import driving
from playwright.async_api import expect

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, ConsoleMessage

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: The one console error a correct page produces, and it is the browser's own: a
#: browser asks for a favicon unprompted and admission is decided before routing, so
#: a session-less request to any path answers 401. Filtered by the URL that produced
#: it, so a 401 against anything the page itself asked for is still a failure.
_BROWSERS_OWN_PROBE = "/favicon.ico"

#: A line that parses to a JSON **array**, which is not one JSON object either and
#: carries no member a discriminator could be read from. It threw nothing before #2008
#: — ``[].kind`` is ``undefined``, so the loop simply ran out — and got the cut's
#: sentence, whose opening clause is as false of it as of any other misframed line.
_STREAM_OF_AN_ARRAY = "[]\n"

#: ``DELIVERY_STREAM_CUT``'s opening, quoted: the sentence a misframed line must **not**
#: get, because a gateway that wrote a whole unreadable line did not stop part way
#: through writing one.
_CUT = "ended before the gateway finished it"

#: Where the page keeps the header half (``STORAGE_KEY`` in ``app.js``). Read back so
#: that "the session was not thrown away" is a fact about storage rather than about a
#: panel that happens to still be showing.
_HEADER_HALF = "assistant.session.header-half"

#: What ``GATEWAY_GONE`` says, and the reason every case below asserts its absence:
#: it is the sentence the unguarded page reached, and it is wrong in every clause —
#: the gateway answered, the turn ran, and nothing about the session ended.
_GATEWAY_GONE = "may have stopped"

#: An outcome that renders **part way** and then throws: ``capture_degraded`` and
#: ``reply`` are read and written into the panel, and ``steps.length`` is where the
#: renderer stops. It is what makes "it renders or it reports, and never leaves half"
#: an observation rather than a claim — a body carrying no ``outcome`` at all throws on
#: the first member read and leaves nothing behind to clear.
_HALF_RENDERABLE_BODY = {
    "outcome": {"capture_degraded": True, "reply": "your calendar is clear today"}
}

#: The half-rendered panel's own first line, quoted from the page: what has to be gone
#: from the screen once the ending says the outcome is not known.
_HALF_WRITTEN = "This turn was not recorded"


async def test_a_misframed_delivery_stream_is_not_reported_as_a_gateway_that_had_gone(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The same reader's condition on the other surface it serves (#2008).

    ``streamValues`` is read by two consumers, so refusing a line there reaches both —
    and the ending each of them gives it is its own. An owner whose notifications
    stopped is not told about "that answer", which is why ``DELIVERY_STREAM_CUT`` was
    split from ``ANSWER_STREAM_CUT`` in the first place, and the misframed pair is split
    for that same reason.

    **This is the case adversarial review's round-1 blocker names**, and the body is an
    array rather than ``null`` deliberately: ``[].kind`` is ``undefined``, so before the
    reader refused it nothing threw here at all and this stream ended in
    ``DELIVERY_STREAM_CUT``. Refusing it in the reader and stopping there would have
    moved it to ``GATEWAY_GONE`` — a regression this change introduced and this case
    would have caught.

    **The real body is cancelled rather than drained**, because a delivery stream is a
    long poll the gateway holds open by design (ADR-0175 §4); a cancelled body is the
    browser going away, which is an ending that gateway is written to meet.
    """
    thrown: list[str] = []
    complaints: list[str] = []
    async with driving(gateway_browser, tmp_path) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.page.on("console", lambda message: _note(message, complaints))
        await _substitute(drive, path="/deliveries", body=_STREAM_OF_AN_ARRAY, drain=False)
        await drive.page.click("#watch-button")

        said = await _fault(drive, panel="notifications")
        assert "could not read as a value on it" in said
        assert "The gateway did answer" in said
        assert "Start watching again." in said
        assert _GATEWAY_GONE not in said
        assert _CUT not in said
        # Not the answer stream's wording: nothing here was an answer.
        assert "that answer" not in said
        # The control is handed back, which is the whole of the way on from this ending.
        await expect(drive.page.locator("#watch-button")).to_be_visible()
        await _still_admitted(drive)
        assert thrown == []
        assert complaints == []


async def test_a_parks_answer_that_cannot_be_rendered_leaves_no_half_answer_behind(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """#2006: the consent surface's ending, driven across the fold into the guard.

    The ending itself is unchanged — the token is stranded, the park's row given up and
    ``PARK_REPLY_UNREADABLE`` named — and what the fold adds is the half of the rule that
    was stated and not performed: the inline ``catch`` hid the answer panel and left what
    the renderer had already written inside it. So the outcome here renders part way and
    *then* throws, which is the only way to tell a panel that was cleared from one that
    was merely hidden, and the ``2xx`` really is the gateway's own — the resume reached
    the engine and resolved the park before its body was replaced.
    """
    thrown: list[str] = []
    complaints: list[str] = []
    async with driving(gateway_browser, tmp_path) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.page.on("console", lambda message: _note(message, complaints))
        drive.engine.park("h-1")
        await drive.page.click("#confirmations-button")
        approve = drive.page.locator("#confirmation-list button", has_text="Yes, do it")
        await approve.wait_for(state="visible")
        await _substitute(
            drive, path="/confirmation/resume", body=json.dumps(_HALF_RENDERABLE_BODY)
        )
        await approve.click()

        # The account is in the node that owns it and not in the panel's fault slot,
        # which every listing read clears on its way in (adversarial review's round 8).
        said = drive.page.locator("#answer-said")
        await said.wait_for(state="visible")
        stated = await said.inner_text()
        assert "could not read an outcome from" in stated
        assert "what became of the park is not known" in stated
        assert "the action may have been carried out" in stated
        assert _GATEWAY_GONE not in await drive.page.inner_text("#confirmations")
        # Nothing half-rendered left behind the hidden panel, which is what the fold
        # adds: the renderer had written two lines before it threw. Read as
        # ``textContent`` rather than ``innerText``, because a hidden node's
        # ``innerText`` is empty whether it was cleared or not — which would pass over
        # exactly the state this case exists to read.
        await expect(drive.page.locator("#answer")).to_be_hidden()
        left = await drive.page.locator("#answer-body").text_content()
        assert _HALF_WRITTEN not in (left or ""), left
        assert left == "", left
        assert thrown == []
        assert complaints == []


#: One hold over ``fetch`` that replaces one path's response **body** after the gateway
#: has written it, installed in the manner of ``test_browser_conversations``' own hold
#: and for its reasons.
#:
#: The request really is sent, the gateway really answers it, and the engine really
#: records it; the head, the status and the headers that reach the
#: page are the ones it wrote, and the real body is read to the end and thrown away.
#: The one thing substituted is what a truncated, reassembled or proxy-substituted
#: response loses. Fabricating the whole response at a Playwright route would also
#: fabricate the half of it the page reads its ``200`` off — which is the half the
#: sentence under test is entitled to say the turn ran from.
#:
#: **And holding it here rather than at a route is what keeps the layer inside its
#: budget.** A registered ``page.route`` costs thirty seconds of the context's teardown
#: on this harness — measured, three cases of ninety-two seconds against ADR-0216 §3's
#: sixty-second budget for the whole layer — which is the same cost
#: ``test_browser_conversations`` records against the same device.
#:
#: **What is substituted is held in a variable rather than closed over**, so one case
#: can substitute for one request and let the next through. Installing a second hold
#: instead would leave the first one substituting underneath it.
_HOLDING = """() => {
  if (window.__held !== undefined) {
    return;
  }
  window.__held = null;
  const realFetch = window.fetch;
  window.fetch = async function (resource, options) {
    const path = new URL(
      typeof resource === "string" ? resource : resource.url,
      location.href
    ).pathname;
    const answered = await realFetch.call(this, resource, options);
    const asked = window.__held;
    if (asked === null || path !== asked.path) {
      return answered;
    }
    if (asked.drain) {
      await answered.text();
    } else {
      await answered.body.cancel();
    }
    return new Response(asked.body, {
      status: answered.status,
      statusText: answered.statusText,
      headers: answered.headers,
    });
  };
}
"""


async def _hold(drive: Drive) -> None:
    """Take the hold over ``fetch``. Installed once."""
    await drive.page.evaluate(_HOLDING)


async def _substitute(drive: Drive, *, path: str, body: str, drain: bool = True) -> None:
    """Let one path's request through, then replace the body of what came back.

    Args:
        drive: The gateway, engine and page under test.
        path: The exact request path to substitute for.
        body: What the page reads in place of the body the gateway wrote.
        drain: Whether to read the real body to its end before replacing it. True for
            a turn, where reading it to the end is what makes "the turn really ran" a
            fact about the drive rather than a claim. False for a **delivery** stream,
            whose body is a long poll the gateway holds open by design (ADR-0175 §4) —
            draining one would wait for a stream written to be waited on, so the real
            body is cancelled instead, which is the browser going away and is what the
            gateway is written to meet.
    """
    await _hold(drive)
    await drive.page.evaluate(
        "(asked) => { window.__held = asked; }", {"path": path, "body": body, "drain": drain}
    )


async def _stop_substituting(drive: Drive) -> None:
    """Let every path's own body through again, the hold still recording."""
    await drive.page.evaluate("() => { window.__held = null; }")


async def _still_admitted(drive: Drive) -> None:
    """The session this page was admitted on is still the one it holds.

    ``GATEWAY_GONE``'s remedy is a fresh bootstrap value, and ``sessionLost`` performs
    it: the header half is forgotten and the bootstrap entry replaces the console. An
    ending that is not a gateway that has gone must do neither, so both halves are read
    — the panel the owner is looking at, and the value behind it.
    """
    await expect(drive.page.locator("#bootstrap")).to_be_hidden()
    await expect(drive.page.locator("#console")).to_be_visible()
    held = await drive.page.evaluate("(key) => window.localStorage.getItem(key)", _HEADER_HALF)
    assert isinstance(held, str), held
    assert held, held


async def _fault(drive: Drive, *, panel: str = "console") -> str:
    """What one panel is saying, once it is saying anything.

    Waits on the slot being shown rather than on a duration: ``fault`` reveals the
    panel's own slot when it writes a condition into it, which is a state the page
    reaches (ADR-0216 §7).

    Args:
        drive: The gateway, engine and page under test.
        panel: Which panel's fault slot to read. Every ending here writes into the
            console's except the consent surface's, which writes beside the park it
            is about — ``fault``'s own second argument, read back.

    Returns:
        The condition the panel is displaying.
    """
    slot = drive.page.locator(f"#{panel} > .fault")
    await slot.wait_for(state="visible")
    return await slot.locator(".fault-text").inner_text()


def _note(message: ConsoleMessage, complaints: list[str]) -> None:
    """Keep every console error but the one the browser makes on its own."""
    if message.type == "error" and not message.location["url"].endswith(_BROWSERS_OWN_PROBE):
        complaints.append(f"{message.location['url']}: {message.text}")
