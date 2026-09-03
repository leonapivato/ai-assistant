"""What the ask surface does with an answer it cannot read (#1622, ADR-0216 §2).

``renderOutcome`` reads the outcome's members from its first lines, so a ``2xx``
that carries no ``outcome`` throws at the call site — and until #1622 the two ask
entries called it unguarded. The throw is not uncaught: both are awaited inside
``ask``'s own ``try``, whose ``catch`` says ``GATEWAY_GONE`` — "The gateway did not
answer, so it may have stopped", with a restart and a fresh bootstrap value as the
remedy — about a gateway that had just answered a turn that had just run.

**That is what no reading of the file decides.** ``test_bundle.py`` can pin that the
guard is written at both call sites and that its ``catch`` names the right sentence;
what it cannot say is where an exception raised four lines inside another function
*lands*, which is the whole of why the wrong sentence reached the owner. ADR-0216 §2
puts exactly that here — "behaviour a reading of the file cannot decide" — so the
cases below run the page and read what the owner reads.

**The gateway's own answer, with only the body replaced.** Each case lets the
request reach the gateway, takes the response it wrote, and substitutes the body —
which is the condition #1622 names and the only one that is reachable: every ``2xx``
the gateway writes goes through ``_json_response``, so what produces this is a
truncated, reassembled or proxy-substituted body between the two ends. The head is
therefore genuinely the gateway's and the turn genuinely ran, which is what makes
the sentence the whole entry says ("The turn itself ran") a fact about the drive
rather than a claim the test also fabricated. ADR-0216 §4's clause is untouched:
nothing here substitutes an *asset*, and the page is still loaded from that gateway
and no other origin.
"""

from __future__ import annotations

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

#: A ``2xx`` body carrying no ``outcome`` at all. ``asObject`` normalises anything
#: unreadable to exactly this, so it is both the shape a truncated body arrives as
#: and the one the page's own reader manufactures for one.
_NO_OUTCOME = "{}"

#: A stream that ends in a terminal value of the right ``kind`` and no ``outcome``
#: behind it, after one chunk. ``TERMINAL_KINDS`` is read off ``kind`` and never from
#: what the value contains (ADR-0175 §2), so this is what the page accepts as the end
#: of the answer and then finds it cannot render.
_STREAM_WITH_A_CHUNK = '{"kind": "chunk", "text": "part of an ans"}\n{"kind": "outcome"}\n'

#: The same ending reached before any chunk, which is the other arm of the sentence:
#: nothing was written into the panel, so there is nothing to say was cleared.
_STREAM_WITH_NO_CHUNK = '{"kind": "outcome"}\n'

#: What ``GATEWAY_GONE`` says, and the reason every case below asserts its absence:
#: it is the sentence the unguarded page reached, and it is wrong in every clause —
#: the gateway answered, the turn ran, and nothing about the session ended.
_GATEWAY_GONE = "may have stopped"


async def test_a_whole_answer_that_carries_no_outcome_is_reported_as_a_turn_that_ran(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """``/ask``'s entry, where the head is proof the turn ran and the body is not.

    ``_ask`` awaits ``converse`` and answers with the outcome, so a ``200`` cannot come
    back until the assistant has finished with the question. The page may therefore say
    the turn ran and confine what is unknown to what it did — the narrowing
    ``ASK_ABANDONED_MIDWAY`` performs one ending over, and the direction ADR-0139 §4
    forbids getting wrong either way round.
    """
    thrown: list[str] = []
    complaints: list[str] = []
    async with driving(gateway_browser, tmp_path) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.page.on("console", lambda message: _note(message, complaints))
        await _substitute(drive, path="/ask", body=_NO_OUTCOME)
        await drive.page.uncheck("#stream-answer")
        await _ask(drive, "what is on today")

        said = await _fault(drive)
        assert "could not read an outcome from the answer" in said
        assert "what the turn did is not known" in said
        assert "The turn itself ran" in said
        assert "The conversations listing is where to look for it" in said
        assert _GATEWAY_GONE not in said
        # No answer-shaped nothing left behind it, and the control comes back: the
        # owner's way on from here is asking again, which is a new question.
        await expect(drive.page.locator("#answer")).to_be_hidden()
        await expect(drive.page.locator("#ask-button")).to_be_enabled()
        assert thrown == []
        assert complaints == []


async def test_a_streamed_answer_that_ends_in_an_unreadable_value_clears_what_it_wrote(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """``/ask/stream``'s entry, with a chunk on screen when the terminal value lands.

    ADR-0173 §3 makes the terminal outcome's ``reply`` the answer, so the chunks are
    not "the record of what the assistant said" and leaving them under a fault renders
    a non-answer as one — ``ANSWER_STREAM_CUT``'s own reasoning, reached by a different
    door. And the streamed sentence claims less than the whole entry's: this head is
    written and drained before ``_pump_answer`` is awaited, so nothing here read that
    the turn ran.
    """
    thrown: list[str] = []
    complaints: list[str] = []
    async with driving(gateway_browser, tmp_path) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.page.on("console", lambda message: _note(message, complaints))
        await _substitute(drive, path="/ask/stream", body=_STREAM_WITH_A_CHUNK)
        await _ask(drive, "what is on today")

        said = await _fault(drive)
        assert "could not read an outcome from" in said
        assert "what became of the turn is not known" in said
        assert "The turn itself ran" not in said
        assert _GATEWAY_GONE not in said
        # The clause about the screen, because there was something on it.
        assert "is not the answer and was not kept" in said
        await expect(drive.page.locator("#answer")).to_be_hidden()
        assert "part of an ans" not in await drive.answer()
        await expect(drive.page.locator("#ask-button")).to_be_enabled()
        assert thrown == []
        assert complaints == []


async def test_a_stream_unreadable_before_its_first_chunk_says_nothing_about_the_screen(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The other arm, and the reason the clause is a separate one.

    A stream that ends in an unreadable terminal value before any chunk has arrived
    put an empty panel up and nothing in it. Saying that what had been written was
    cleared would be a sentence about nothing — the division ``abandonAsk`` keeps
    between its two abandonment sentences, arriving on an ending that is not an
    abandonment.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        await _substitute(drive, path="/ask/stream", body=_STREAM_WITH_NO_CHUNK)
        await _ask(drive, "what is on today")

        said = await _fault(drive)
        assert "what became of the turn is not known" in said
        assert "is not the answer and was not kept" not in said
        assert _GATEWAY_GONE not in said
        await expect(drive.page.locator("#answer")).to_be_hidden()


#: Replaces one path's response **body**, after the gateway has written it — installed
#: over ``fetch`` in the manner of ``test_browser_conversations``' own hold and
#: ``browser_drive``'s Web Audio probe, and for both of their reasons.
#:
#: The request really is sent, the gateway really answers it, the turn really runs and
#: the engine really records it; the head, the status and the headers that reach the
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
_SUBSTITUTING = """(asked) => {
  const realFetch = window.fetch;
  window.fetch = async function (resource, options) {
    const path = typeof resource === "string" ? resource : resource.url;
    const answered = await realFetch.call(this, resource, options);
    if (new URL(path, location.href).pathname !== asked.path) {
      return answered;
    }
    await answered.text();
    return new Response(asked.body, {
      status: answered.status,
      statusText: answered.statusText,
      headers: answered.headers,
    });
  };
}
"""


async def _substitute(drive: Drive, *, path: str, body: str) -> None:
    """Let one path's request through, then replace the body of what came back.

    Args:
        drive: The gateway, engine and page under test.
        path: The exact request path to substitute for.
        body: What the page reads in place of the body the gateway wrote.
    """
    await drive.page.evaluate(_SUBSTITUTING, {"path": path, "body": body})


async def _ask(drive: Drive, question: str) -> None:
    """Ask one question through the page's own form, as the owner does."""
    await drive.page.fill("#utterance", question)
    await drive.page.click("#ask-form button[type=submit]")


async def _fault(drive: Drive) -> str:
    """What the console panel is saying, once it is saying anything.

    Waits on the slot being shown rather than on a duration: ``fault`` reveals the
    panel's own slot when it writes a condition into it, which is a state the page
    reaches (ADR-0216 §7).
    """
    slot = drive.page.locator("#console > .fault")
    await slot.wait_for(state="visible")
    return await slot.locator(".fault-text").inner_text()


def _note(message: ConsoleMessage, complaints: list[str]) -> None:
    """Keep every console error but the one the browser makes on its own."""
    if message.type == "error" and not message.location["url"].endswith(_BROWSERS_OWN_PROBE):
        complaints.append(f"{message.location['url']}: {message.text}")
