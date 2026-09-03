"""What this page does with an answer it cannot read (#1622, #2005, #2006, ADR-0216 §2).

``renderOutcome`` reads the outcome's members from its first lines, so a ``2xx``
that carries no ``outcome`` throws at the call site — and every entry that renders a
turn called it unguarded. The throw is not uncaught, and where it landed is what made
each entry's ending wrong in its own way. The two ask entries and the spoken one are
awaited inside a ``try`` whose ``catch`` says ``GATEWAY_GONE`` — "The gateway did not
answer, so it may have stopped", with a restart and a fresh bootstrap value as the
remedy — about a gateway that had just answered a turn that had just run. The consent
entry caught its own throw and did the right thing, and folding it into the shared
guard (#2006) is a change to a surface where getting it wrong resolves a park nothing
read — so the ending is driven here rather than only read.

**That is what no reading of the file decides.** ``test_bundle.py`` can pin that the
guard is written at every call site and that each ending names the right sentence;
what it cannot say is where an exception raised four lines inside another function
*lands*, nor what is left on the screen and in the air afterwards — which is the whole
of why the wrong sentence reached the owner. ADR-0216 §2 puts exactly that here —
"behaviour a reading of the file cannot decide" — so the cases below run the page and
read what the owner reads.

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

import json
from typing import TYPE_CHECKING

import pytest
from browser_drive import driving, rendering_of
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


def _spoken_without_an_outcome() -> str:
    """One ``/ask/spoken`` body whose turn carries every member but the outcome.

    The transcript and the rendering are both there and both good — the rendering is
    real audio Chromium can decode — so what the case reads afterwards is the page
    declining to disclose a transcript it holds and declining to play a rendering it
    could, rather than a body that happened to lack them.

    Returns:
        The substituted body, as the page will read it.
    """
    return json.dumps(
        {
            "turn": {
                "heard": "what is on today",
                "spoken": {"content": rendering_of(2.0), "media_type": "audio/webm;codecs=opus"},
                "spoken_degraded": False,
                "episode_id": "ep-1",
            }
        }
    )


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


async def test_a_spoken_answer_that_carries_no_outcome_is_neither_shown_nor_played(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """#2005: the voice entry's ending, and the two things only a drive can read.

    ``renderSpokenTurn`` guards ``turn.outcome === null`` — ADR-0200 §4's pairing, the
    recording that carried no words — and an absent member is not that pair. The body
    here has a transcript and a rendering the browser can really decode, so a page that
    disclosed one or played the other would be saying something about a turn it has just
    reported it cannot read the outcome of. ``playSpoken`` reads
    ``turn.outcome.conversation_id`` for the report it will owe (ADR-0205 §7), which is
    the throw one line past the guard as well as the reason.
    """
    thrown: list[str] = []
    complaints: list[str] = []
    async with driving(gateway_browser, tmp_path) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.page.on("console", lambda message: _note(message, complaints))
        await _substitute(drive, path="/ask/spoken", body=_spoken_without_an_outcome())
        await drive.press()

        said = await _fault(drive)
        assert "could not read an outcome from the answer" in said
        assert "what the turn did is not known" in said
        assert "The turn itself ran" in said
        assert "Nothing of it is shown or spoken here" in said
        assert _GATEWAY_GONE not in said
        # Nothing of the turn on screen: no answer panel, and no transcript beside it
        # even though the body carried one.
        await expect(drive.page.locator("#answer")).to_be_hidden()
        await expect(drive.page.locator("#heard")).to_be_hidden()
        # And nothing in the air. The rendering in that body is decodable audio, so this
        # is Chromium having been asked to start no source rather than having none.
        assert (await drive.probe())["starts"] == []
        # The control comes back, which is #1500's invariant on the ending it did not
        # have: a press that ends in a condition still hands the button over.
        await expect(drive.page.locator("#talk-button")).to_be_enabled()
        assert thrown == []
        assert complaints == []


async def test_a_spoken_reply_this_browser_cannot_read_at_all_reaches_the_same_ending(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The shape the reachable case actually arrives as, one member further out.

    #2005 describes ``turn.outcome === undefined``; what a truncated, reassembled or
    proxy-substituted ``2xx`` produces first is ``readBody``'s ``{}``, so ``body.turn``
    is absent and the pairing check throws on *it*. Both are the same condition and take
    the same ending, which is what ``asObject`` at the top of the entry is for — an
    unreadable member arriving as an absent one rather than as an exception, which is the
    rule the two body readers already state.
    """
    thrown: list[str] = []
    async with driving(gateway_browser, tmp_path) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        await _substitute(drive, path="/ask/spoken", body=_NO_OUTCOME)
        await drive.press()

        said = await _fault(drive)
        assert "what the turn did is not known" in said
        assert _GATEWAY_GONE not in said
        await expect(drive.page.locator("#answer")).to_be_hidden()
        await expect(drive.page.locator("#talk-button")).to_be_enabled()
        assert thrown == []


async def test_a_spoken_turn_whose_answer_was_unreadable_still_spends_its_delivery_report(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Adversarial review, round 1, ``major``. The half of this ending nothing else reads.

    The report a spoken request carries is *taken* from page state before the request
    goes out (ADR-0205 §7 — "there is exactly one place it leaves this page"), and two
    paths put it back: a ``fetch`` that rejected, and a refusal that was not about the
    report itself. Both are requests the hub may never have received. This ending is not
    one of them — the ``2xx`` is the hub having run the turn the report rode in on — so
    the report is spent, and a page that put it back would send the same measurement
    twice for one playback.

    Before this change the report *was* put back here, because the throw reached
    ``sendRecording``'s ``catch``; that is a state no reading of the file can settle and
    no string assertion can observe, since what it is about is what the **next** request
    carries. So the case drives three turns and reads the requests the page sent.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        # Recording from before the first request, because what this case reads is a
        # sequence and the first turn is what puts a report into it.
        await _hold(drive)
        # One answer played, then a press over it: the interrupt is what puts a report
        # in page state, and the second request is what carries it out.
        await drive.press()
        await drive.page.wait_for_function("() => window.__drive.starts.length === 1")
        await _substitute(drive, path="/ask/spoken", body=_NO_OUTCOME)
        await drive.press()

        said = await _fault(drive)
        assert "what the turn did is not known" in said
        assert _GATEWAY_GONE not in said

        # A third turn, answered normally, and what it carries is the whole question.
        await _stop_substituting(drive)
        await drive.press()
        await drive.page.wait_for_function("() => window.__drive.starts.length === 2")

        asked = await _sent(drive, "/ask/spoken")
        assert len(asked) == 3, asked
        # The report really was pending and really did ride out on the unreadable turn —
        # without which the assertion below would hold over a page that never had one.
        assert "delivery" in asked[1], asked[1]
        # And it is not sent again: that request was answered `2xx`, so the hub has it.
        assert "delivery" not in asked[2], asked[2]


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

        said = await _fault(drive, panel="confirmations")
        assert "could not read an outcome from" in said
        assert "what became of the park is not known" in said
        assert "the action may have been carried out" in said
        assert _GATEWAY_GONE not in said
        # Nothing half-rendered left behind the hidden panel, which is what the fold
        # adds: the renderer had written two lines before it threw. Read as
        # ``textContent`` rather than through ``Drive.answer``, because a hidden node's
        # ``innerText`` is empty whether it was cleared or not — which would pass over
        # exactly the state this case exists to read.
        await expect(drive.page.locator("#answer")).to_be_hidden()
        left = await drive.page.locator("#answer-body").text_content()
        assert _HALF_WRITTEN not in (left or ""), left
        assert left == "", left
        assert thrown == []
        assert complaints == []


#: One hold over ``fetch`` that does two things: it records what the page **asked**,
#: and it replaces one path's response **body** after the gateway has written it.
#: Installed in the manner of ``test_browser_conversations``' own hold and
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
#:
#: **What is substituted is held in a variable rather than closed over**, so one case
#: can substitute for one request and let the next through — which is what a case about
#: a *sequence* of turns needs. Installing a second hold instead would leave the first
#: one substituting underneath it.
_HOLDING = """() => {
  if (window.__held !== undefined) {
    return;
  }
  window.__held = null;
  window.__sent = [];
  const realFetch = window.fetch;
  window.fetch = async function (resource, options) {
    const path = new URL(
      typeof resource === "string" ? resource : resource.url,
      location.href
    ).pathname;
    window.__sent.push({
      path,
      body: options === undefined || options.body === undefined ? null : options.body,
    });
    const answered = await realFetch.call(this, resource, options);
    const asked = window.__held;
    if (asked === null || path !== asked.path) {
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


async def _hold(drive: Drive) -> None:
    """Take the hold over ``fetch``, recording from here on. Installed once."""
    await drive.page.evaluate(_HOLDING)


async def _substitute(drive: Drive, *, path: str, body: str) -> None:
    """Let one path's request through, then replace the body of what came back.

    Args:
        drive: The gateway, engine and page under test.
        path: The exact request path to substitute for.
        body: What the page reads in place of the body the gateway wrote.
    """
    await _hold(drive)
    await drive.page.evaluate("(asked) => { window.__held = asked; }", {"path": path, "body": body})


async def _stop_substituting(drive: Drive) -> None:
    """Let every path's own body through again, the hold still recording."""
    await drive.page.evaluate("() => { window.__held = null; }")


async def _sent(drive: Drive, path: str) -> list[dict[str, object]]:
    """Every request body the page sent to one path, parsed, in order.

    Args:
        drive: The gateway, engine and page under test.
        path: The request path to read back.

    Returns:
        One decoded payload per request, oldest first.
    """
    await _hold(drive)
    recorded = await drive.page.evaluate("() => window.__sent")
    return [json.loads(one["body"]) for one in recorded if one["path"] == path and one["body"]]


async def _ask(drive: Drive, question: str) -> None:
    """Ask one question through the page's own form, as the owner does."""
    await drive.page.fill("#utterance", question)
    await drive.page.click("#ask-form button[type=submit]")


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
