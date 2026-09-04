"""The bytes that would leave, on the screen the owner answers on (ADR-0233 §8, §15).

ADR-0233 §15 obliges this lane, and no other surface's, to drive the page: "'before
the control' is a claim about a rendering that no assertion over the bytes can check".
That is the whole reason this module exists beside ``test_bundle.py``'s text-layer
pins. A reading of ``app.js`` can say that ``valueBlock`` is called before
``offerApproval`` and that ``.argument-value`` carries ``white-space: pre-wrap``; it
cannot say that the paragraph breaks in an email body survive to the screen, that no
ancestor rule clipped a long one into a box, that the value's own pixels sit above the
button's, or that a value carrying ``<button>Yes, do it</button>`` arrives as those
characters rather than as a second control.

**Both widths, because "before the control" is a claim about a width** (§15). The
desktop case and the phone case are the same case parametrised: what changes is how
much of the value fits, which is exactly the pressure ADR-0233 §12 names as the place
this floor matters most and is least likely to be read — "a long body on a small
screen is the case where it most matters and is least likely".

**The gateway is the real one over the canonical fake** (ADR-0216 §4), and each
confirmation is a whole ``Confirmation`` built here rather than through
``FakeAssistantEngine.park``: the cases turn on ``parameters`` as well as on the
binding, and the fake's helper fixes the first — which is
``test_gateway_confirmations.py``'s own reason for building its own.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from browser_drive import DESKTOP, PHONE, driving
from playwright.async_api import expect
from test_browser_answers import _substitute

from ai_assistant.core.types import (
    Confirmation,
    ConfirmationEgress,
    ContinuationToken,
    DestinationProtocol,
    DiscloserProvenance,
    EgressDestination,
    EgressSpan,
    SpanCoverage,
)
from ai_assistant.interfaces.gateway.server import _confirmation_view

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, ConsoleMessage, ViewportSize

    from ai_assistant.core.types import FrozenJson

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: The one console error a correct page produces, and it is the browser's own: a
#: browser asks for a favicon unprompted and admission is decided before routing, so a
#: session-less request to any path answers 401. Filtered by the URL that produced it,
#: so a 401 against anything the page itself asked for is still a failure.
_BROWSERS_OWN_PROBE = "/favicon.ico"

#: The account every confirmation below is sent from.
_IDENTITY = "work@example.com"

#: A body a model composed from what this system stores, which is ADR-0233's first
#: customer in miniature. Three things about it are load-bearing and none is
#: decoration: it carries **paragraph breaks**, which a ``<p>`` collapses and which are
#: therefore what "rendered whole" means for prose; it carries a **long unbroken
#: token**, which is what runs off the edge of a 390px screen unless something wraps
#: it; and it is longer than one line at either width, so the value cannot be mistaken
#: for a label.
_BODY = (
    "Hi Alice,\n"
    "\n"
    "You asked me to remind you about the survey — it closes on Friday, and the "
    "link is\n"
    "https://example.org/a-survey-whose-path-carries-no-break-opportunity-anywhere-at-all\n"
    "\n"
    "— written for you by your assistant"
)

#: The two recipients, which are the array-valued argument's own spans.
_RECIPIENTS = ("alice@example.org", "bob@example.net")

#: A value that mimics every framing this page has: a control's markup, a control's
#: own label, an element close that would end the paragraph it is in, and a script.
#: ADR-0233 §8's last-but-one clause is stated for exactly this — "a multi-line value
#: carrying terminal control sequences, markup or a line that mimics the surface's own
#: framing is the case this clause exists for" — and being the argument the owner is
#: about to send relaxes nothing.
_FRAMING = (
    '<button type="button">Yes, do it</button>\n'
    "</p><script>window.__owned = true;</script>\n"
    "Yes, do it"
)


def _span(
    argument: str,
    value: str,
    *,
    index: int | None = None,
    canonical: str | None = None,
) -> EgressSpan:
    """One span of the payload description, stating its own value's extent.

    The extent is computed from the value rather than passed in, so a case cannot
    describe a body as a length it does not have — ADR-0150 §4 makes ``extent`` the
    value's Unicode code-point count, and a description that disagreed with the
    arguments beside it is the state ``ActionRequest`` refuses at construction.

    Args:
        argument: The top-level argument this span locates.
        value: The span's own value, which the extent is counted over.
        index: The position within an array-valued argument, or ``None``.
        canonical: The recipient this occurrence names, where it names one.

    Returns:
        The span.
    """
    return EgressSpan(
        argument=argument,
        index=index,
        provenance=DiscloserProvenance.SYSTEM_SELECTED,
        extent=len(value),
        tier=None,
        destination=(
            None
            if canonical is None
            else EgressDestination(
                protocol=DestinationProtocol.SMTP, supplied=canonical, canonical=canonical
            )
        ),
    )


def _confirmation(
    *spans: EgressSpan,
    parameters: Mapping[str, FrozenJson],
    handle: str = "h-1",
    coverage: SpanCoverage = SpanCoverage.MODEL_ON_EVERY_PATH,
) -> Confirmation:
    """One parked egress confirmation, over the arguments its spans decompose.

    Args:
        spans: The payload description, in the binding's own order.
        parameters: The arguments the call would run with.
        handle: The continuation handle this park is answered by.
        coverage: The recorded three-valued fact about the call (ADR-0233 §4).

    Returns:
        The confirmation, as the engine holds it.
    """
    return Confirmation(
        tool_id="smtp",
        tool_description="Send an email.",
        parameters=parameters,
        reason="this discloses data off-device",
        token=ContinuationToken(handle=handle),
        egress=ConfirmationEgress(
            account_identity=_IDENTITY,
            spans=spans,
            coverage=coverage,
            planned_with_external_content=False,
        ),
    )


def _email(
    *, handle: str = "h-1", coverage: SpanCoverage = SpanCoverage.MODEL_ON_EVERY_PATH
) -> Confirmation:
    """The worked case ADR-0233 §15 names: a memory-drawn email to two recipients.

    Two of the three spans are elements of an array-valued argument and one is a whole
    string argument, which is ADR-0150 §4's decomposition in both of its shapes — and
    the two shapes reach the screen by different routes on this page, so a case that
    used only one would leave the other unobserved.

    Args:
        handle: The continuation handle.
        coverage: The recorded fact about the call.

    Returns:
        The confirmation.
    """
    return _confirmation(
        _span("body", _BODY),
        _span("to", _RECIPIENTS[0], index=0, canonical=_RECIPIENTS[0]),
        _span("to", _RECIPIENTS[1], index=1, canonical=_RECIPIENTS[1]),
        parameters={"body": _BODY, "to": _RECIPIENTS},
        handle=handle,
        coverage=coverage,
    )


#: What the page's confirmation card looks like, measured in the browser that drew it.
#:
#: Everything here is a question no reading of ``app.js`` answers. ``clipped`` walks
#: every ancestor for a rule that both hides overflow and has more content than box —
#: which is how a value gets truncated by a stylesheet rather than by a renderer.
#: ``beforeEveryControl`` is ``compareDocumentPosition``, so it is document order as
#: the browser resolved it, and ``top`` is the document coordinate, so "above" is the
#: pixels rather than the markup.
_MEASURE = """() => {
  const card = document.querySelector('#confirmation-list .confirmation-row');
  const values = [...card.querySelectorAll('.argument-value')];
  const controls = [...card.querySelectorAll('button')];
  const clipped = (el) => {
    for (let node = el; node !== null; node = node.parentElement) {
      const style = getComputedStyle(node);
      const hides = style.overflow !== 'visible' || style.overflowY !== 'visible';
      if (hides && node.scrollHeight > node.clientHeight + 1) {
        return true;
      }
    }
    return false;
  };
  const box = (el) => {
    const rect = el.getBoundingClientRect();
    return {
      top: rect.top + window.scrollY,
      height: rect.height,
      width: rect.width,
    };
  };
  return {
    values: values.map((el) => ({
      text: el.textContent,
      whiteSpace: getComputedStyle(el).whiteSpace,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      clipped: clipped(el),
      beforeEveryControl: controls.every(
        (button) => (el.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
      ),
      ...box(el),
    })),
    controls: controls.map((el) => ({ text: el.textContent, ...box(el) })),
    inputs: card.querySelectorAll('input, select, textarea').length,
    checked: card.querySelectorAll('[checked], :checked, [autofocus]').length,
    focused: document.activeElement === null ? null : document.activeElement.tagName,
    cardText: card.innerText,
    pageWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  };
}"""


async def _shown(drive: Drive) -> dict[str, Any]:
    """Open the pending listing and measure the card the page drew.

    Args:
        drive: The page, already admitted, whose engine holds the parks.

    Returns:
        The measurements :data:`_MEASURE` takes.
    """
    await drive.page.click("#confirmations-button")
    await drive.page.wait_for_selector("#confirmation-list .confirmation-row")
    measured = await drive.page.evaluate(_MEASURE)
    assert isinstance(measured, dict)
    return measured


def _note(message: ConsoleMessage, complaints: list[str]) -> None:
    """Keep every console error but the one the browser makes on its own."""
    if message.type == "error" and not message.location["url"].endswith(_BROWSERS_OWN_PROBE):
        complaints.append(f"{message.location['url']}: {message.text}")


# --- ADR-0233 §8's rendering floor, at two widths ------------------------------


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_every_spans_value_is_on_the_screen_whole_and_above_the_control(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0233 §8's first three clauses and its ordering clause, driven (§15).

    Four things are asserted and each is one the text layer cannot reach.

    **Every span's value is there, and it is the value.** Three spans decompose two
    arguments — ``body`` whole, ``to[0]`` and ``to[1]`` by position — and all three
    values are on screen. The body is compared **character for character**, because
    §8's "whole" is not a length: a rendering that dropped the blank lines would still
    contain every word.

    **The line breaks survive.** A ``<p>`` collapses runs of whitespace, so a body
    written as three paragraphs would arrive as one run-on line — the value the owner
    did not write, presented as the one they are approving. The computed
    ``white-space`` and the block's own height are both read, so the rule is observed
    working rather than only present.

    **Nothing clipped it.** Every ancestor is walked for a rule that hides overflow
    over content taller than its box: §8 forbids a value "collapsed behind a control
    the user must operate to see them", and a stylesheet is where a page that renders
    a value whole can still show a third of it.

    **The values are above the control, in the markup and in the pixels.** §8's
    "where a surface has an order, the values precede the controls" is checked with
    ``compareDocumentPosition`` for tab order and with document coordinates for
    viewport order, which is what the brief for this lane asks for in terms.
    """
    thrown: list[str] = []
    complaints: list[str] = []
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.page.on("console", lambda message: _note(message, complaints))
        drive.engine.parked["h-1"] = _email()

        shown = await _shown(drive)

        # Every span's own value, each as itself and each **exactly once**: the body
        # whole, and each recipient as the element it is rather than only inside the
        # array's JSON — where a quotation mark is escaped and a newline would be the
        # two characters `\n`. The equality is the half adversarial review's round 3
        # is about: a card rendering the array beside its elements would put one value
        # on the screen twice, free to disagree with itself.
        rendered = [one["text"] for one in shown["values"]]
        assert rendered == [_BODY, *_RECIPIENTS], rendered
        for one in shown["values"]:
            assert one["whiteSpace"] == "pre-wrap", one
            assert not one["clipped"], one
            assert one["scrollHeight"] <= one["clientHeight"] + 1, one
            assert one["beforeEveryControl"], one
            assert one["height"] > 0, one
        body = next(one for one in shown["values"] if one["text"] == _BODY)
        recipient = next(one for one in shown["values"] if one["text"] == _RECIPIENTS[0])
        # The paragraph breaks are rendered rather than merely permitted: the body is
        # six lines and a recipient is one, at every width this page has.
        assert body["height"] > recipient["height"] * 4, (body, recipient)
        # Above every control the owner can press, in the pixels as well as in the
        # markup. Measured over the ones with a box: the third control is the way out
        # of a wait and is `hidden` until there is a wait to leave, so it has no
        # pixels to be below — document order above has it either way.
        pressable = [one for one in shown["controls"] if one["height"] > 0]
        assert len(pressable) == 2, shown["controls"]
        assert max(one["top"] for one in shown["values"]) < min(one["top"] for one in pressable), (
            shown
        )
        # And the page did not grow sideways to hold it, which is the phone's half of
        # the question: `overflow-wrap: anywhere` breaks the long link instead.
        assert shown["pageWidth"] <= shown["viewportWidth"], shown
        assert thrown == []
        assert complaints == []


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_value_that_mimics_this_pages_own_framing_arrives_as_characters(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0233 §8's neutralisation clause, over the value most likely to test it.

    "Every value is inserted into the surface's output as **data**, neutralised for
    that target on render. Being the argument the user is about to send relaxes
    nothing, and a multi-line value carrying terminal control sequences, markup or a
    line that mimics the surface's own framing is the case this clause exists for."

    So the body carries a button's markup, a script, a paragraph close and the
    approval control's **own label**. What is read back is that the card has exactly
    the three controls it builds — a fourth would be one the value drew — that no
    script the value carried ran, and that the characters are on screen as characters.

    Driven at both widths for the reason the case above is: this is where a page that
    reached for ``innerHTML`` to fit a long value on a phone would be caught.
    """
    thrown: list[str] = []
    complaints: list[str] = []
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.page.on("console", lambda message: _note(message, complaints))
        drive.engine.parked["h-1"] = _confirmation(
            _span("body", _FRAMING), parameters={"body": _FRAMING}
        )

        shown = await _shown(drive)

        assert [one["text"] for one in shown["values"]] == [_FRAMING], shown["values"]
        # The three the row builds — the answer, its refusal, and the way out of a
        # wait — and no fourth drawn by the value.
        assert [one["text"] for one in shown["controls"]] == [
            "Yes, do it",
            "No",
            "Stop waiting",
        ], shown["controls"]
        assert shown["inputs"] == 0, shown
        assert await drive.page.evaluate("() => window.__owned === undefined")
        assert thrown == []
        assert complaints == []


# --- ADR-0233 §8's coverage floor ----------------------------------------------


@pytest.mark.parametrize(
    ("coverage", "said"),
    [
        (
            SpanCoverage.NOT_COVERED,
            "nothing it would send was recorded as drawn from what this system stores",
        ),
        (
            SpanCoverage.MODEL_ON_EVERY_PATH,
            "some of what it would send was composed by a model that had been shown",
        ),
        (
            SpanCoverage.PATH_WITHOUT_MODEL,
            "it would send something taken from what this system stores directly",
        ),
    ],
    ids=[one.value for one in SpanCoverage],
)
async def test_all_three_coverage_states_render_as_a_statement_about_the_call(
    gateway_browser: Browser, tmp_path: Path, coverage: SpanCoverage, said: str
) -> None:
    """ADR-0233 §8's coverage clauses, over the rendering rather than over the source.

    All **three** states render, including the one no confirmation can reach —
    ``PATH_WITHOUT_MODEL`` is refused at ``EgressBinding`` construction (§6), and §8
    renders it anyway so that "a surface's rendering is total over the enum rather
    than over the states a lane believes it will meet".

    What is read off the screen is the sentence and its scope: the line announces
    itself as being about **the call as a whole**, and it names no argument, no
    position and no destination — §8's "no surface renders it as a statement about a
    span", which is ADR-0181 §6's fifth clause read one axis over.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.parked["h-1"] = _email(coverage=coverage)

        shown = await _shown(drive)

        text = shown["cardText"]
        assert f"About this call as a whole: {said}" in text, text
        # It is beside the values and never in place of one (§8), so the card still
        # carries every byte the call would send.
        assert _BODY in text, text
        # Not a per-span claim: the sentence itself names no argument, no position and
        # no recipient, whatever the description beside it names.
        sentence = text[text.index("About this call as a whole") :].split("\n")[0]
        for named in ("body", "to[", "alice@", "bob@", _IDENTITY):
            assert named not in sentence, sentence
        # Not a detection, not a warning, not a score — and not an assurance in the
        # state most likely to be read as one.
        for verdict in ("safe to send", "no risk", "warning", "detected", "suspicious"):
            assert verdict not in text.lower(), text


async def test_the_call_level_facts_are_two_sentences_and_neither_is_the_other(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0233 §8's conflation clause, at the surface where the two meet.

    "No surface … conflates it with ``planned_with_external_content``. The two answer
    different questions — where what this call would send came from, and whether the
    material selected into the planning call carried the external mark — and a surface
    that rendered one as the other would be asserting a marker neither ADR mints."

    A card carrying the *strongest* coverage and the *false* origin is the pair that
    catches a conflation in either direction: a page that read one off the other would
    have to render them as agreeing, and here they do not. Both sentences are on
    screen, on their own lines, with ADR-0178 §7's floor unreduced between them.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.parked["h-1"] = _email(coverage=SpanCoverage.MODEL_ON_EVERY_PATH)

        shown = await _shown(drive)
        lines = shown["cardText"].split("\n")

        origin = [one for one in lines if one.startswith("Planned over:")]
        call = [one for one in lines if one.startswith("About this call as a whole:")]
        assert len(origin) == 1, lines
        assert len(call) == 1, lines
        assert "no record is marked as resting on recorded external content" in origin[0]
        assert "composed by a model that had been shown" in call[0]
        # ADR-0178 §7's floor is unreduced beneath both (§8's fourth clause).
        assert f"From the connected account: {_IDENTITY}" in lines
        assert "It would reach:" in lines
        assert "What it describes sending:" in lines


# --- ADR-0233 §8's control floor -----------------------------------------------


async def test_no_control_answers_more_than_one_confirmation_or_defaults_to_approval(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0233 §8's control clause, driven over two parks at once.

    "No surface offers a control that answers more than one confirmation, pre-selects
    an affirmative answer, defaults to one, or presents approval as the lower-effort
    path: no 'approve all', no pre-checked box, no affirmative default on a prompt, and
    no control that both reveals a value and approves it."

    Two parks are on screen together, which is the state an "approve all" would appear
    in and the only state that can show its absence. Answering the first is then
    observed at the **engine**: exactly one ``resume`` goes out, naming one handle, and
    the second park is still there to be answered on its own.

    **And no control reveals a value**, which is this page's easiest breach to make and
    the one §8 names last: there is nothing to press to see a value, because every
    value is already on screen — so the count of controls per card is the same whether
    a value is one line or forty.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.parked["h-1"] = _email(handle="h-1")
        drive.engine.parked["h-2"] = _email(handle="h-2")

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")
        rows = drive.page.locator("#confirmation-list .confirmation-row")
        assert await rows.count() == 2
        # One pair of answers per card and no third control that answers anything: the
        # page offers no "approve all", no checkbox and no pre-selected state.
        assert (
            await drive.page.locator("#confirmation-list button", has_text="Yes, do it").count()
            == 2
        )
        assert await drive.page.locator("#confirmation-list input").count() == 0
        assert await drive.page.locator("#confirmation-list [checked]").count() == 0
        # Nothing in a card is focused, so a stray Return before the owner has read
        # anything presses nothing (§8's "no affirmative default on a prompt"). Read as
        # "not inside the listing" rather than as "the body": the control the case just
        # pressed to *open* the listing holds focus, and that one answers nothing.
        assert await drive.page.evaluate(
            "() => document.activeElement.closest('#confirmation-list') === null"
        )
        await drive.page.keyboard.press("Enter")
        assert [one for one in drive.engine.calls if one[0] == "resume"] == []

        await rows.first.locator("button", has_text="Yes, do it").click()
        await drive.page.wait_for_function(
            "() => document.querySelectorAll('#confirmation-list .confirmation-row').length === 1"
            " || document.querySelector('#answer:not([hidden])') !== null"
        )

        answered = [one for one in drive.engine.calls if one[0] == "resume"]
        assert answered == [("resume", {"token": "h-1", "approved": True})], answered
        assert "h-2" in drive.engine.parked


# --- ADR-0233 §8's refusal ------------------------------------------------------


async def test_a_confirmation_whose_value_cannot_be_located_is_not_put_at_all(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0233 §8's second clause, in the direction that has no control.

    "A surface that cannot render a value whole renders **no** confirmation and says
    so, which is ADR-0178 §9's second clause read one member over: a partial
    content-bearing confirmation is worse than none, because it looks like a whole
    one."

    The state is reachable only through a gateway whose spans and arguments disagree —
    ``ActionRequest`` refuses one at construction (ADR-0150 §4) — and it is driven here
    because what it is about is what is **absent** from the screen: no value, no
    description, and above all no button. A page that rendered the card with a hole in
    it would pass every assertion about what it contains.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.parked["h-1"] = _confirmation(
            _span("body", _BODY),
            _span("subject", "a subject the arguments do not carry"),
            parameters={"body": _BODY},
        )

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")
        card = drive.page.locator("#confirmation-list .confirmation-row")

        said = await card.inner_text()
        assert "so it is not put to you at all" in said, said
        assert "approving what is only partly shown" in said, said
        # Nothing of the confirmation is put: not the values, not the description, not
        # the reason, and not a control to answer it with.
        assert _BODY not in said, said
        assert "Send an email." not in said, said
        assert await card.locator("button").count() == 0


#: Every way the body this page was handed can fail to carry ADR-0233 §8's floor,
#: each as a mutation of the view the gateway itself built. They are stated as
#: mutations rather than as hand-written bodies so that what is under test is one
#: fault at a time against an otherwise correct card — a body written from scratch
#: would be refused for whatever else it got wrong.
#:
#: The first three are a value arriving as something other than the text the gateway
#: spells (adversarial review, round 1). The next two are a **locator** a span cannot
#: be joined to — one that names no entry and one that names two — which is what the
#: page asks instead of comparing two copies, since round 6 left the content carried
#: once. Then a call-level coverage outside the three states §8 obliges the surface to
#: state (round 2), and last the shapes that used to **throw** rather than refuse
#: (round 6): an ``egress`` that is absent, a ``spans`` that is not a list, and a
#: ``parameters`` that is not one either.
#: An integer one past the last a double holds exactly. ``JSON.parse`` reads it as
#: ``9007199254740992``, which is the whole of why the arguments cross this surface as
#: **text**: "a JSON number read by ``JSON.parse`` would be a double, and an integer
#: argument above 2**53 would reach the owner changed". The locator and the extent
#: cross as numbers and cannot be spelled, so what they get instead is a refusal
#: (adversarial review, round 10).
_UNSAFE = 9007199254740993


def _unsafe_position(view: dict[str, Any]) -> None:
    """A locator past the last integer a double holds, on both halves at once.

    Both for :func:`_negative_position`'s reason, and here it is load-bearing twice
    over: the page rounds *both* to the same value, so the join still succeeds and the
    only thing left to refuse the card is the safety of the number itself.

    Args:
        view: The confirmation view to spoil.
    """
    view["parameters"][1]["index"] = _UNSAFE
    view["egress"]["spans"][1]["index"] = _UNSAFE


def _unsafe_extent(view: dict[str, Any]) -> None:
    """An extent past the last integer a double holds.

    Rendered, it would put ``9007199254740992 code points`` on the card as a fact about
    the bytes — a number this page produced by parsing, not one the gateway sent.

    Args:
        view: The confirmation view to spoil.
    """
    view["egress"]["spans"][0]["extent"] = _UNSAFE


def _negative_position(view: dict[str, Any]) -> None:
    """A locator naming a position no decomposition has, on both halves at once.

    Both, because the join is what a one-sided change would be caught by: the page asks
    that a span's locator names exactly one argument entry, so moving only the span
    would be refused for naming none and would say nothing about the bound.
    ``EgressSpan.index`` carries ``ge=0``, so this is a body ``core`` refuses to build.

    Args:
        view: The confirmation view to spoil.
    """
    view["parameters"][1]["index"] = -1
    view["egress"]["spans"][1]["index"] = -1


def _negative_extent(view: dict[str, Any]) -> None:
    """A span describing its value as fewer than no code points.

    ``EgressSpan.extent`` carries ``ge=0`` and ``_span_defect`` checks it against the
    value, so this too is a body ``core`` refuses to build — and rendered, it would put
    "-1 code points" beside the bytes as a fact about them.

    Args:
        view: The confirmation view to spoil.
    """
    view["egress"]["spans"][0]["extent"] = -1


_FAULTS: dict[str, Callable[[dict[str, Any]], None]] = {
    "an omitted value": lambda view: view["parameters"][1].pop("value"),
    "a numeric value": lambda view: view["parameters"][1].update({"value": 12}),
    "an object value": lambda view: view["parameters"][1].update({"value": {"a": "b"}}),
    "a locator no entry carries": lambda view: view["parameters"][1].update({"index": 7}),
    "a locator two entries carry": lambda view: view["parameters"].append(
        dict(view["parameters"][1])
    ),
    "an omitted coverage": lambda view: view["egress"].pop("coverage"),
    "an unknown coverage": lambda view: view["egress"].update({"coverage": "probably_fine"}),
    "a numeric coverage": lambda view: view["egress"].update({"coverage": 1}),
    # A one-element array of a *legitimate* state, which a property key coerces to that
    # state's own name: the one shape where the vocabulary lookup answers yes about a
    # body carrying no ``SpanCoverage`` member (adversarial review, round 9).
    "a coverage that is a list": lambda view: view["egress"].update(
        {"coverage": [SpanCoverage.NOT_COVERED.value]}
    ),
    "an omitted egress": lambda view: view.pop("egress"),
    "spans that are not a list": lambda view: view["egress"].update({"spans": {}}),
    "arguments that are not a list": lambda view: view.update({"parameters": {}}),
    "a negative position": _negative_position,
    "a negative extent": _negative_extent,
    "a locator no double holds": _unsafe_position,
    "an extent no double holds": _unsafe_extent,
}


@pytest.mark.parametrize("fault", list(_FAULTS), ids=list(_FAULTS))
async def test_a_confirmation_this_page_cannot_put_whole_is_not_put_at_all(
    gateway_browser: Browser, tmp_path: Path, fault: str
) -> None:
    """Adversarial review, rounds 1 and 2: the fail-closed tests are type tests.

    ``null`` is what *this* gateway sends for a span its arguments do not locate, and
    a check for it alone reads the body this page was handed as though something had
    validated it. Nothing did: the page parses the response with ``JSON.parse`` and
    reads named members, so a ``value`` that is **absent** is ``undefined``, which is
    not ``null`` — and under the narrower check the card was built and ``valueBlock``
    put the word ``undefined`` on the screen as the bytes being approved. The same
    argument reaches ``coverage``, where an absent one rendered as ``undefined.`` and
    left the controls live.

    **And it reaches the locator**, which is what the page asks instead of comparing
    two copies: the content is carried once (ADR-0233 §2), so a span's own value is the
    argument entry carrying its locator, and a body where that locator names no entry —
    or names two — is one where this page cannot say which text the span describes.

    **Three of them used to throw rather than refuse** (round 6). An absent ``egress``,
    a ``spans`` that is not a list and a ``parameters`` that is not one reached the
    guard's own member reads; the throw was caught by ``readPending`` as "the gateway
    did not answer", which is the wrong sentence about a gateway that had just answered
    — and it discarded the whole listing rather than the one card.

    Every case is driven rather than argued about: the request really goes to the
    gateway, the gateway really answers it, and only the **body** is replaced — the
    condition #1622 names, and the same ``window.fetch`` hold
    ``test_browser_answers.py`` uses for its own unreadable answers. What is read back
    is the refusal, whole: the notice, and no control to answer with.

    Args:
        gateway_browser: The one browser this run launched.
        tmp_path: The case's data directory.
        fault: Which of :data:`_FAULTS` the body carries.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.parked["h-1"] = _email()
        view = _confirmation_view(_email())
        _FAULTS[fault](view)
        await _substitute(drive, path="/confirmations", body=json.dumps({"confirmations": [view]}))

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")
        card = drive.page.locator("#confirmation-list .confirmation-row")

        said = await card.inner_text()
        assert "so it is not put to you at all" in said, (fault, said)
        assert _BODY not in said, (fault, said)
        assert "undefined" not in said, (fault, said)
        assert await card.locator("button").count() == 0


#: What a card refused under ADR-0233 §8 says, and the only part of the sentence this
#: module matches on — the whole of it is pinned in ``test_bundle.py``.
_CANNOT_PUT = "so it is not put to you at all"


def _members(
    view: object, path: str = "", steps: tuple[str | int, ...] = ()
) -> Iterator[tuple[str, object, tuple[str | int, ...]]]:
    """Every member of one confirmation's view, at every depth, with the way to it.

    A list's **elements** are members too, which is not a technicality: ``parameters``
    being a list is what the guard used to ask, and ``parameters: [null, ...]`` is the
    entry inside it — the shape adversarial review's round 7 found still reaching
    ``one.key``.

    Args:
        view: The view, or any part of one.
        path: What to call this part, for the failure message.
        steps: The keys and positions that reach this part from the whole view.

    Yields:
        The path to one member, its value, and the steps that reach it.
    """
    if isinstance(view, dict):
        for key, value in view.items():
            here = f"{path}.{key}" if path else key
            yield here, value, (*steps, key)
            yield from _members(value, here, (*steps, key))
    elif isinstance(view, list):
        for position, value in enumerate(view):
            here = f"{path}[{position}]"
            yield here, value, (*steps, position)
            yield from _members(value, here, (*steps, position))


def _nulled(view: dict[str, Any], steps: tuple[str | int, ...]) -> dict[str, Any]:
    """The view again with one member replaced by ``null``, the rest untouched.

    Round-tripped through JSON rather than deep-copied, so what the page is handed is
    a document that could have arrived over the wire.

    Args:
        view: The confirmation view to copy.
        steps: The keys and positions reaching the member to null.

    Returns:
        The copy.
    """
    copied: dict[str, Any] = json.loads(json.dumps(view))
    target: Any = copied
    for step in steps[:-1]:
        target = target[step]
    target[steps[-1]] = None
    return copied


def _may_arrive_null(view: dict[str, Any]) -> frozenset[str]:
    """Every member of this view a **correct** gateway may send as ``null``.

    Stated rather than discovered, because it is the other half of the property: a
    page that refused every card with a ``null`` anywhere in it would pass "nothing
    throws" by refusing confirmations it is obliged to put.

    Three sources, and no fourth. Whatever this view already carries as ``null`` is a
    member the gateway writes that way — a whole argument's absent position, a
    recipient arm's empty account identity, a span with no tier. ``egress`` is
    ADR-0178 §4's discriminator, and a confirmation over no egress binding is a card
    this page renders. And a span's ``destination`` is optional (ADR-0150 §4), so an
    occurrence naming no recipient is rendered as the payload-description span it is.

    Args:
        view: The confirmation view the case is generated from.

    Returns:
        The paths whose nulling leaves a card this page must still put.
    """
    already = {path for path, value, _ in _members(view) if value is None}
    spans = {
        f"egress.spans[{position}].destination" for position in range(len(view["egress"]["spans"]))
    }
    return frozenset(already | {"egress"} | spans)


#: Both cards of the listing and whether the panel is reporting a fault.
#:
#: The fault is the observable the class turns on. A member read that throws escapes
#: ``renderConfirmation`` into ``readPending``'s ``catch``, which writes "the gateway
#: did not answer" about a gateway that had just answered — and the listing it was
#: half way through rendering is gone.
_LISTING = """() => {
  const rows = [...document.querySelectorAll('#confirmation-list .confirmation-row')];
  const slot = document.querySelector('#confirmations > .fault');
  return {
    rows: rows.map((row) => ({
      text: row.innerText,
      values: [...row.querySelectorAll('.argument-value')].map((el) => el.textContent),
      controls: row.querySelectorAll('button').length,
    })),
    faulted: slot !== null && !slot.hidden,
  };
}"""

#: The condition each case waits on: this case's own companion on the screen, or the
#: panel reporting a fault. Waiting on the companion alone would time out where the
#: listing was lost, which is the failure this case exists to name — so the fault is a
#: state the wait ends in and an assertion reports, rather than a timeout.
_ARRIVED = """(said) => {
  const list = document.querySelector('#confirmation-list');
  const slot = document.querySelector('#confirmations > .fault');
  return list.innerText.includes(said) || (slot !== null && !slot.hidden);
}"""


@pytest.mark.parametrize(
    "seed",
    [
        _email(),
        _confirmation(_span("body", _BODY), parameters={"body": _BODY}),
    ],
    ids=["a set of recipients", "the connected account"],
)
async def test_no_member_of_a_confirmation_is_read_without_the_shape_being_read_for(
    gateway_browser: Browser, tmp_path: Path, seed: Confirmation
) -> None:
    """ADR-0233 §8's refusal as a **property**, over every member of the body.

    Adversarial review named four members in four rounds — a span's ``value``, then
    ``coverage``, then ``egress``, ``spans`` and ``parameters`` as containers, then the
    entries inside those containers and ``destinations`` — and each fix left the next
    member unguarded, because the defect was never the member. It is the class: a
    member read out of a response body nothing validated. Two instances stood at the
    handover and both are here by construction rather than by name:
    ``parameters: [null, ...]`` reaching ``one.key``, and ``destinations: null``
    reaching a ``forEach``.

    So the cases are **generated from the gateway's own view**, one per member at every
    depth, and each one is driven: the request really goes to the gateway, the gateway
    really answers it, and only the body is replaced (#1622). What each case asserts is
    the whole of what the class is about.

    **The listing survives.** A second, unaltered confirmation rides beside the
    mutated one in the same body, and it is on screen whole — its values, its
    controls — in every case. That is the consequence a throw has and a refusal does
    not: ``readPending``'s ``catch`` reports "the gateway did not answer" about a
    gateway that had just answered, and takes every other confirmation waiting for an
    answer with it.

    **The card is one of the two whole states, never a partial one.** Either the page
    refused it — the notice, no value, no control — or it put it whole. Nothing in
    between, and the word ``undefined`` on neither, which is what a member rendered
    without being read for looks like on a screen.

    **And the refusal is not the answer to everything**, which
    :func:`_may_arrive_null` is: three kinds of member arrive ``null`` from a correct
    gateway, and a card carrying one of them is a card this page is obliged to put.

    Both destination shapes are driven, because ``readDestination`` has two arms and
    the account arm's ``protocol`` and ``canonical`` are exactly the members a view
    built from recipients never exercises (ADR-0178 §3).

    Args:
        gateway_browser: The one browser this run launched.
        tmp_path: The case's data directory.
        seed: The confirmation whose view every case is generated from.
    """
    view = _confirmation_view(seed)
    renders = _may_arrive_null(view)
    walked = list(_members(view))
    # A walker that stopped early would pass this whole case vacuously, so the count
    # is floored: the smaller of the two views carries twenty-six members.
    assert len(walked) >= 26, len(walked)

    complaints: list[str] = []
    async with driving(gateway_browser, tmp_path) as drive:
        drive.page.on("console", lambda message: _note(message, complaints))
        drive.engine.parked["h-1"] = seed

        for case, (path, _, steps) in enumerate(walked):
            # The companion is a whole confirmation the gateway itself produced, with
            # one member changed: the reason, which is what this case waits on. A
            # per-case marker is what makes the read the *new* listing rather than the
            # one still on screen from the case before.
            beside = _confirmation_view(_email(handle="h-2"))
            beside["reason"] = f"case {case}"
            await _substitute(
                drive,
                path="/confirmations",
                body=json.dumps({"confirmations": [_nulled(view, steps), beside]}),
            )
            await drive.page.click("#confirmations-button")
            await drive.page.wait_for_function(_ARRIVED, arg=f"case {case}")
            read = await drive.page.evaluate(_LISTING)

            assert not read["faulted"], (path, read)
            rows = read["rows"]
            assert len(rows) == 2, (path, rows)
            assert rows[1]["values"] == [_BODY, *_RECIPIENTS], (path, rows[1])
            assert rows[1]["controls"] == 3, (path, rows[1])

            card = rows[0]
            assert "undefined" not in card["text"], (path, card)
            if path in renders:
                assert _CANNOT_PUT not in card["text"], (path, card)
                assert _BODY in card["values"], (path, card)
                assert card["controls"] == 3, (path, card)
            else:
                assert _CANNOT_PUT in card["text"], (path, card)
                assert card["values"] == [], (path, card)
                assert card["controls"] == 0, (path, card)

        assert complaints == []


async def test_an_argument_carrying_no_span_is_still_a_key_and_a_value_on_the_screen(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0177 §8's "every key and every value the mapping carries", under the
    span-by-span rendering ADR-0233 §8 asks for.

    ADR-0150 §4 gives an **empty JSON array** no span — "a key whose value is an
    empty JSON array is the ``argument`` of **no** span" — so a card that rendered
    only the spans would drop that key silently. It is the one shape where the
    decomposition is not total over the arguments, and the case exists because it is
    exactly the shape a span-by-span renderer loses.

    **The other side of that clause is the case above**, which asserts the rendered
    values are exactly the spans' own: an array-valued argument is on screen as
    ``to[0]`` and ``to[1]``, every key named and every element rendered as itself,
    and its JSON notation is not rendered beside them. §8's own reason is that "a
    confirmation showing **some** of the arguments a call would run with is not a
    confirmation of that call", and nothing here is omitted, truncated or hidden by
    ordering. Adversarial review's round 4 read §8 as requiring the container's
    notation as well; that reading and round 3's ``blocker`` cannot both be built,
    and the PR records which was taken and why.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.parked["h-1"] = _confirmation(
            _span("body", _BODY), parameters={"body": _BODY, "cc": ()}
        )

        shown = await _shown(drive)

        assert [one["text"] for one in shown["values"]] == [_BODY, "[]"], shown["values"]
        assert "cc =" in shown["cardText"], shown["cardText"]


async def test_one_card_this_page_cannot_put_does_not_take_the_listing_with_it(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Adversarial review, round 6, second ``blocker``: the refusal is per card.

    A malformed row used to throw inside the renderer, which ``readPending`` caught as
    ``GATEWAY_GONE`` — "the gateway did not answer, so it may have stopped" — about a
    gateway that had just answered, and the listing it had already written was cleared
    with it. Two parks are answered here, one of them malformed: the bad one says it
    cannot be put, the good one is whole and answerable, and no fault is raised.
    """
    thrown: list[str] = []
    async with driving(gateway_browser, tmp_path) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.engine.parked["h-1"] = _email(handle="h-1")
        drive.engine.parked["h-2"] = _email(handle="h-2")
        views = [_confirmation_view(_email(handle="h-1")), _confirmation_view(_email(handle="h-2"))]
        views[0].pop("egress")
        await _substitute(drive, path="/confirmations", body=json.dumps({"confirmations": views}))

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")
        rows = drive.page.locator("#confirmation-list .confirmation-row")
        await expect(rows).to_have_count(2)

        assert "so it is not put to you at all" in await rows.first.inner_text()
        assert await rows.first.locator("button").count() == 0
        whole = await rows.last.inner_text()
        assert _BODY in whole, whole
        assert await rows.last.locator("button", has_text="Yes, do it").count() == 1
        # The listing survived, so nothing said the gateway had stopped.
        await expect(drive.page.locator("#confirmations > .fault")).to_be_hidden()
        assert thrown == []
