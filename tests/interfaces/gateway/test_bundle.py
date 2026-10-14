"""The front end ships in this repository, and loads nothing from anywhere else.

ADR-0168 §10 rules both halves: the bundle "lives in this repository, is versioned
with it, and ships inside the same distribution", and "the page it serves loads no
asset, font, style, script or datum from any origin but the gateway's own". §6
adds the two clauses that make the page safe to render model output into — every
value inserted as text and never as markup, and a policy permitting no inline
script.

Read off the shipped files rather than argued from the source, because "the front
end is now inside this repository's gate, review floor and ADR ledger" is only
worth anything if something checks it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from ai_assistant.core.types import (
    DEFAULT_NOTIFICATION_REACH,
    AttemptOutcome,
    BeliefBand,
    BeliefSummary,
    ClarificationWithdrawal,
    DiscloserProvenance,
    DriveWithheld,
    EngagementDisposition,
    ForecastNotRead,
    ForecastRefusal,
    GoalAbandonment,
    GoalStatus,
    GrantScope,
    MemoryKind,
    NotificationCondition,
    NotificationReach,
    ReadAnswerOutcome,
    ReadCancellation,
    ReferenceOutcome,
    RoutableOperation,
    SearchNotServiced,
    SpanCoverage,
)
from ai_assistant.interfaces import cli
from ai_assistant.interfaces.gateway.records import RefusalCondition
from ai_assistant.interfaces.gateway.server import (
    packaged_bundle,
)
from ai_assistant.orchestration.reads import ForecastDisposition
from ai_assistant.wire import GRANTABLE_SCOPES

_ROOT = Path(__file__).resolve().parents[3] / "src" / "ai_assistant" / "interfaces" / "gateway"
_ASSETS = _ROOT / "assets"

#: What the page must never reach for. Every one of these is an origin the gateway
#: does not serve, and a content security policy of `default-src 'none'` would
#: refuse them at run time — this is the earlier check, on the file.
_OFF_ORIGIN = re.compile(r"""(?:src|href|@import|url\()\s*=?\s*['"(]?(?:https?:)?//""")

#: The ways a page turns a string into markup or into code. ADR-0168 §6: the front
#: end "inserts every value the hub returned into the page as **text** and never
#: as markup, and executes nothing derived from one" — and an answer is model
#: output, which is not a trusted source of markup.
_MARKUP_SINKS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(")


#: The smallest target a finger hits reliably, and the floor every control on the page
#: is held to (#1429). Written as the literal the stylesheet carries, because what is
#: being pinned is the declaration and not an arithmetic on it.
_TOUCH_FLOOR: Final = "min-height: 44px;"

#: The one width below which the narrow layout applies (#1429).
_NARROW: Final = "@media (max-width: 480px) {"


def _asset(name: str) -> str:
    """One shipped file, as text."""
    return (_ASSETS / name).read_text(encoding="utf-8")


def _style(name: str) -> str:
    """One shipped stylesheet with its comments removed.

    For :func:`_code`'s reason: the comments in that file *name* the declarations
    under check — `display: none`, which one rule carries and no other may, and a
    clamped line count, which nothing may — so a check reading the whole file would
    be answered by the prose explaining the rule it enforces.
    """
    return re.sub(r"/\*.*?\*/", "", _asset(name), flags=re.DOTALL)


def _rule(stylesheet: str, selector: str) -> str:
    """The declarations of one rule, by the exact selector text that opens it.

    Enough to ask what a *particular* selector declares, which searching the whole
    sheet cannot: a `min-height` counted anywhere would be satisfied by any other
    rule having one.
    """
    opened = stylesheet.index(f"\n{selector} {{") + len(selector) + 4
    return stylesheet[opened : stylesheet.index("\n}", opened)]


def _tag(document: str, identifier: str) -> str:
    """The opening tag of one element, by its id.

    Asked for rather than searched for, so that "this control ships hidden" is decided
    over *that element's* attributes: a ``hidden`` counted anywhere in the document
    would be satisfied by any of the fifteen panels that carry one.
    """
    opened = document.rindex("<", 0, document.index(f'id="{identifier}"'))
    return document[opened : document.index(">", opened) + 1]


def _markup(name: str) -> str:
    """One shipped document with its comments removed.

    The comments in that file *name* what it must not carry, for the same reason
    :func:`_code`'s do — so a check reading the whole file would fail on the prose
    explaining the rule it enforces.
    """
    return re.sub(r"<!--.*?-->", "", _asset(name), flags=re.DOTALL)


def _code(name: str) -> str:
    """One shipped script with its comments removed.

    The comments in that file *name* the sinks below, because saying which ones
    are refused and why is the point of them — so a check reading the whole file
    would fail on the prose explaining the rule it enforces.
    """
    without_blocks = re.sub(r"/\*.*?\*/", "", _asset(name), flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", without_blocks, flags=re.MULTILINE)


def _joined(block: str) -> str:
    """The sentence a run of concatenated JavaScript string literals renders.

    The page builds its longer sentences as ``"..." + "..."`` across lines, so a test
    comparing what it says to what its sibling surface says has to put the halves back
    together. Nothing here interprets an expression: only double-quoted literals are
    read, which is every piece of the two sentences this is used on.
    """
    return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', block))


def _arm(function: str, opening: str) -> str:
    """One arm of a two-armed renderer: the ``return`` its guard opens.

    Sliced rather than searched so that "this arm says X" is decided over *that*
    arm — a sentence counted anywhere in the function would be satisfied by the other
    one.
    """
    body = function[function.index(opening) + len(opening) :]
    return body[: body.index("\n  }") if "\n  }" in body else len(body)]


#: The guard the page's episodic arm opens with, built from ``core``'s own vocabulary
#: rather than spelled out: a kind renamed there fails this file instead of leaving a
#: dead branch behind a literal nothing on the wire ever equals again.
_EPISODIC_GUARD: Final = f'if (belief.kind === "{MemoryKind.EPISODIC.value}") {{'


@pytest.mark.integration
def test_the_bundle_is_read_out_of_the_installed_package() -> None:
    """§10: "The gateway serves only assets that shipped in the installed
    distribution. It fetches nothing at runtime"."""
    bundle = packaged_bundle()

    assert set(bundle) == {"/", "/app.css", "/app.js"}
    assert all(body for body, _ in bundle.values())
    assert bundle["/"][1].startswith("text/html")


def test_the_bundle_lives_inside_the_package_that_ships_it() -> None:
    """Which is what puts it in the wheel: the build target packages
    ``src/ai_assistant``, so a file under it ships and a file beside it does not."""
    assert _ASSETS.parent.name == "gateway"
    assert (_ROOT / "server.py").exists()
    assert {path.name for path in _ASSETS.iterdir()} == {"index.html", "app.css", "app.js"}


@pytest.mark.parametrize("name", ["index.html", "app.css", "app.js"])
def test_no_asset_reaches_off_the_gateways_own_origin(name: str) -> None:
    """§10: "loads no asset, font, style, script or datum from any origin but the
    gateway's own"."""
    assert not _OFF_ORIGIN.search(_asset(name)), name


def test_the_document_carries_no_inline_script() -> None:
    """§6: the policy "permits no inline script", so an inline one would be sent
    and then refused by the browser — a page that only works where the clause is
    not enforced."""
    document = _asset("index.html")

    for opened, closed in re.findall(r"(<script\b[^>]*>)(.*?)</script>", document, re.DOTALL):
        assert "src=" in opened, opened
        assert closed.strip() == "", closed


def test_the_document_carries_no_inline_style() -> None:
    """The same clause one media type over: styles are permitted "from its own
    origin alone", which a `style` attribute is not."""
    document = _asset("index.html")

    assert "<style" not in document
    assert not re.search(r"\sstyle\s*=", document)


@pytest.mark.parametrize("sink", _MARKUP_SINKS)
def test_the_front_end_never_turns_a_value_into_markup_or_code(sink: str) -> None:
    """§6's text-not-markup clause, checked at the only place it could be broken."""
    assert sink not in _code("app.js")


def test_the_page_renders_the_answer_beside_the_step_account() -> None:
    """ADR-0170 §6: the composed answer is rendered "**in addition to** the step
    account it renders today, never instead of it", and the account "is rendered on
    a degraded turn too".

    Read off the shipped script for this file's own reason: the gateway carrying
    ``reply`` is the half of #1337 a Python test can see, and a page that received
    the answer and rendered nothing would leave the browser exactly where the QA run
    found it.

    The account's own renderers are asserted to still be reached on the same pass,
    because "instead of" is the failure the clause names and it would pass a check
    that only looked for the answer.
    """
    script = _code("app.js")

    assert "renderReply(body, outcome);" in script
    assert "line(body, outcome.reply, " in script
    assert "outcome.reply_degraded" in script
    assert "No answer could be composed for this turn" in script
    assert "line(body, outcome.rationale, " in script
    assert "renderStep(body, outcome.step);" in script


def test_the_answer_keeps_the_line_breaks_it_was_composed_with() -> None:
    """The stylesheet's half of rendering model prose as text.

    A composed answer is one value inserted with ``textContent`` — the clause above —
    and a paragraph collapses the newlines in it, so an answer written as two
    paragraphs or as a list arrives intact and is shown as one run-on line. Shaping
    it any other way would mean turning the value into markup, which is the one
    thing this front end never does.
    """
    stylesheet = _asset("app.css")

    assert ".reply {" in stylesheet
    assert "white-space: pre-wrap;" in stylesheet


def test_an_unbreakable_token_wraps_instead_of_running_off_the_page() -> None:
    """The other half of shaping a value inserted as text (issue #1340).

    ``pre-wrap`` keeps the breaks a value was written with; it creates no break
    opportunity *inside* an unbroken token. A tool's failure message, a fault's
    detail, a planner's capability name and a model's reply are all hub values in
    normal-flow elements, so a long opaque identifier in any of them ran off the
    panel rather than wrapping to it.

    Asserted on ``body`` rather than per class because ``overflow-wrap`` inherits:
    one declaration covers every surface on the page, including ones added later,
    where a rule per class would owe each of them a clause. ``anywhere`` is the
    value that also shrinks intrinsic size, which is what a flex item like
    ``.conversation-row .hint`` needs to stop overflowing.
    """
    stylesheet = _asset("app.css")
    declarations = re.search(r"^body \{(.*?)^\}", stylesheet, re.MULTILINE | re.DOTALL)

    assert declarations is not None
    assert "overflow-wrap: anywhere;" in declarations.group(1)


def test_a_checkbox_is_not_stretched_to_the_width_of_its_container() -> None:
    """Issue #1440, and the rule that caused it.

    ``input, textarea { width: 100% }`` had no type filter, so every checkbox on the
    page was stretched to its container — measured 656.6px inside a 44rem shell. A
    ``.choice`` is a flex row, so a box that wide took the whole line and the label it
    belongs to wrapped underneath it: the box rendered above its own words, on every
    checkbox row, at every width.

    Pinned as *what the selector excludes* rather than as the presence of a narrower
    rule somewhere: a later `width` on `input` with the filter dropped again is the
    regression, and only the selector catches it.
    """
    stylesheet = _asset("app.css")

    assert 'input:not([type="checkbox"]):not([type="radio"]),\ntextarea {' in stylesheet
    # And the box has a width of its own rather than merely being spared one, so it is
    # not left to whatever a flex row would negotiate for an item with no basis.
    box = _rule(stylesheet, 'input[type="checkbox"]')
    assert "width: 1.15rem;" in box
    assert "flex: none;" in box
    # The tuning panel's three-type patch is the same bug patched three types at a time
    # in one panel. It stays — those are text fields and do want the field's rule, only
    # not its width — but it is no longer what keeps a checkbox off the whole line.
    assert '#tuning-body input[type="number"] {' in stylesheet


def test_a_checkbox_and_the_words_beside_it_are_one_element() -> None:
    """#1440's other half, and #1429's touch floor at the one control that cannot be
    given a 44px box.

    Flat, a box and its ``<label>`` are two items of a wrapping flex row, so a narrow
    viewport may put the words on the line below the box — and the beliefs panel offers
    three pairs in one row, where a wrap between the third box and its own name is a
    band filtered by a label the owner read against the wrong box (ADR-0130 §6's three
    levels). Nested, the pair is one item and cannot be split.

    It is also what makes the target 44px while the box stays 1.15rem: a label's
    tappable area is the label, so the strip toggles the box.
    """
    document = _markup("index.html")
    script = _code("app.js")
    stylesheet = _asset("app.css")

    assert _TOUCH_FLOOR in _rule(stylesheet, ".check")
    # Every checkbox in the document, and there is no other way to write one: a box
    # outside a `.check` label is the shape this test exists to keep off the page.
    boxes = re.findall(r'<input\s+type="checkbox"[^>]*id="([a-z-]+)"', document)
    assert set(boxes) == {"band-asserted", "band-derived", "band-attested"}
    for box in boxes:
        pair = re.search(
            rf'<label class="check" for="{box}">\s*<input\s+type="checkbox" id="{box}"',
            document,
        )
        assert pair is not None, box
    # And the one place the script builds a checkbox row — the grant scope form, which
    # offers the whole use vocabulary every time (ADR-0139 §3).
    scope = _functions(script)["offerScope"]
    assert 'text.className = "check";' in scope
    assert "text.appendChild(box);" in scope
    assert "text.appendChild(document.createTextNode(use.label));" in scope


def test_every_control_on_the_page_meets_the_touch_floor() -> None:
    """#1429: 44px, at the four rules every control on this page comes through.

    ``button`` is the load-bearing one. Every button on the surface is built through it
    — the panel openers in the document, and the ones a listing builds beside a row: a
    belief's Forget, a notification's Dismiss and Forget, a question's Accept and
    Reject, a confirmation's Yes and No, the fault slot's Dismiss and "Start a new
    conversation". None of them has a size rule of its own, which is the point: there
    is no button that can be added to this page without the floor.

    ``select`` had no rule at all before this and took the browser's own font, which on
    iOS is under 16px — the size at which Safari zooms the page on focus and leaves it
    zoomed. It is the same fault as the touch one, one sense over.
    """
    stylesheet = _asset("app.css")

    for selector in ("button", "select", ".check", ".panel-index a"):
        assert _TOUCH_FLOOR in _rule(stylesheet, selector), selector
    # `inline-flex` is what makes a floor centre its label rather than pin it to the top
    # of a taller box, and the `max-width` is what keeps a long label inside the page:
    # a button that cannot exceed its container wraps between its words instead of
    # pushing the document sideways.
    button = _rule(stylesheet, "button")
    assert "display: inline-flex;" in button
    assert "max-width: 100%;" in button
    # And the field's font is inherited rather than named, so it is the body's 16px.
    assert "font: inherit;" in _rule(stylesheet, "select")


def test_a_control_the_page_hides_is_hidden_by_the_sheet_as_well() -> None:
    """#1475 and #1472, which are one fault: nothing on this page was ever hidden.

    ``[hidden] { display: none }`` is a **user agent** rule and every rule in this
    sheet is an **author** rule, so an author ``display`` beats the attribute whatever
    their selectors say. ``button { display: inline-flex }`` — asserted above, and
    load-bearing for the touch floor — therefore un-hid every button on the page:
    ``el("watch-button").hidden = true`` set the attribute and changed nothing on
    screen, leaving an inert "Watch for notifications" under the line saying watching
    was already happening (#1475), including after ADR-0182 §7's announced re-arm,
    which is where the milestone-16 QA met it (#1472).

    **It is not a fact about buttons.** ``.panel-index`` is the third rule this file
    declares a ``display`` for, and the panel index is a ``nav`` that ships ``hidden``
    — so the index rendered below the floor of two open panels it is supposed to
    appear at. What is pinned here is the attribute beating *every* author ``display``,
    which is why the rule is written for the attribute and carries ``!important``: an
    attribute selector ties with a class on specificity, so a sheet that relied on this
    rule coming last would lose it again to the next class rule added.

    A source check is all this can be — there are no executable front-end tests here
    (#1476) — so what it cannot see is that the box is off screen. That was driven, at
    both viewports and on the re-arm path, and is recorded on the pull request.
    """
    stylesheet = _style("app.css")
    document = _markup("index.html")

    assert _rule(stylesheet, "[hidden]").strip() == "display: none !important;"
    # The sheet's only one, so it hides what carries the attribute and nothing else —
    # never a width, a class, or a panel a script has to reveal (ADR-0182 §6, below).
    assert stylesheet.count("display: none") == 1
    # The three controls that ship hidden and are un-hidden by the script alone. Each
    # carries the attribute in the document, so each was on screen at first paint.
    for identifier in ("chat-follow-again", "watch-button", "panel-index"):
        assert " hidden" in _tag(document, identifier), identifier
    script = _code("app.js")
    assert 'el("chat-follow-again").hidden = !offer;' in script
    assert 'el("watch-button").hidden = watching;' in script
    assert "nav.hidden = open.length < PANEL_INDEX_FLOOR;" in script


def test_the_page_has_one_layout_for_a_phone() -> None:
    """#1429: a narrow layout at 480px and below, driven at 390x844.

    One breakpoint, because there is one question here — what the 44rem column's
    gutters and a panel's inset are worth on a 390px screen — and every width below it
    answers the same way.

    What is asserted is as much what the block does *not* do. Nothing in it hides,
    shortens, clamps or scrolls a panel's content: on a surface whose ADRs spend clause
    after clause on an answer being shown whole (ADR-0139 §3's third clause, ADR-0177
    §6, ADR-0178 §7's "none omitted, none truncated silently"), a responsive rule that
    clipped a confirmation's recipients to fit a phone would breach them from the
    stylesheet, and pass every other check in this file.
    """
    stylesheet = _style("app.css")

    assert _NARROW in stylesheet
    narrow = stylesheet[stylesheet.index(_NARROW) : stylesheet.rindex("\n}")]
    assert ".shell {" in narrow
    assert ".panel {" in narrow
    for forbidden in ("display: none", "max-height", "overflow: hidden", "line-clamp"):
        assert forbidden not in narrow, forbidden
    # The dark-scheme block is still the only *other* media query, so this one is the
    # single breakpoint it claims to be rather than the first of a family.
    assert stylesheet.count("@media") == 2


def test_the_page_indexes_the_panels_that_are_open() -> None:
    """#1429: the thirteen control panels reachable on a phone without scrolling past
    all of them.

    A phone shows about a third of one panel, and this page grows a panel every time a
    listing is read, so by the fourth read the answer to the control the owner pressed
    is a thousand pixels below the button that asked for it.

    The index is rebuilt from ``show``, which is the one place a panel's visibility
    changes, so it cannot disagree with the page — there is no second record of what is
    open — and each name is read off that panel's own heading, so a panel added later
    is indexed without this file or the script learning its name.

    #1429 offers collapsing the panels as the alternative; it was not taken, and the
    check that it was not is above: a surface that can show only the panel it last
    opened decides which question the owner is looking at, on the page whose ADRs
    forbid one answer standing in for another (ADR-0139 §1, ADR-0177 §6).
    """
    script = _code("app.js")
    document = _markup("index.html")

    assert '<nav id="panel-index" class="panel-index"' in document
    assert "indexPanels();" in _functions(script)["show"]
    building = _functions(script)["indexPanels"]
    assert 'document.querySelectorAll("section.panel")' in building
    assert "!panel.hidden" in building
    assert "panel.firstElementChild.textContent" in building
    # Never a link to the panel the reader is on: bootstrap is shown exactly when
    # nothing else is, and an index of one entry is a second heading rather than
    # navigation.
    assert 'panel.id !== "bootstrap"' in building
    assert "nav.hidden = open.length < PANEL_INDEX_FLOOR;" in building
    assert "const PANEL_INDEX_FLOOR = 2;" in script
    # It navigates by fragment: no timer, no request, and nothing that could become one.
    assert "link.href = `#${panel.id}`;" in building
    assert "scrollIntoView" not in script


def test_every_refusal_a_browser_can_provoke_is_a_condition_the_page_reads() -> None:
    """Issue #1438, closed at the enumeration rather than at the one entry that was
    missing.

    ``device-not-listed`` is the one it was, and the worst one to be missing: ADR-0174
    §4 keeps the assets **above** the device check deliberately — "an overlay member
    obtains nothing from them they could not obtain from the distribution" — so an
    unlisted phone loads the page, sees it whole, and is refused at the moment `Start`
    is pressed. Without an entry that arrived as "the gateway refused that request
    (HTTP 403)", from which nobody guesses that the remedy is a setting on the laptop.

    **The other two conditions are absent and must stay absent**, which is the half a
    reading of the enumerations alone gets wrong. ``_check_door`` decides `host` and
    `origin` *before* ``RequestClass.ASSET`` is answered, so a request failing either
    one never receives the bundle: there is no page in which the sentence could be
    rendered, and an entry for one would be prose no browser can reach. If that
    ordering ever changes, this is the check that says the two now owe words.
    """
    script = _code("app.js")
    faults = script[
        script.index("const FAULTS = {") : script.index("\n};", script.index("const FAULTS = {"))
    ]
    named = set(re.findall(r'^\s*"?([a-z-]+)"?:', faults, re.MULTILINE))
    decided_before_the_page_exists = {
        RefusalCondition.HOST_NOT_BOUND.value,
        RefusalCondition.ORIGIN_NOT_OWN.value,
    }

    reachable = {one.value for one in RefusalCondition} - decided_before_the_page_exists
    assert reachable <= named, sorted(reachable - named)
    assert not decided_before_the_page_exists & named
    # The remedy is the setting's name, and §4's own clause is why the last sentence is
    # safe to say: the exchange is refused "without the value being read, compared or
    # consumed", so nothing was spent and nothing needs re-minting.
    assert "gateway_remote_browser_devices" in faults
    assert "The value you pasted was not read, so it is still good." in faults


def test_the_page_states_the_three_conditions_of_the_session_it_runs_under() -> None:
    """ADR-0182 §6: "The page states, in the page and without requiring an interaction
    to reveal it, three conditions of the session it is running under."

    They are in the document rather than written by the script, and outside every
    ``hidden`` panel, which is what makes "without requiring an interaction" a floor
    rather than a description of a click: none of the three is a value, a state or
    anything the page has read, so a block a script had to reveal would be one an owner
    whose script failed never sees.

    It sits between the bootstrap panel and the console because §6's clause is about
    the session the page "is running under" — the audience is an owner holding one, and
    the bootstrap panel is on screen exactly when there is none.
    """
    document = _asset("index.html")
    opened = document.index('<div class="session-conditions">')
    # Collapsed, because the sentences are wrapped to the file's column width and a
    # check reading them line by line would pin where the wrapping happens to fall.
    conditions = " ".join(document[opened : document.index("</div>", opened)].split())

    # 1. The process bound (ADR-0168 §4, kept by ADR-0182 §5).
    assert "Every session ends when the gateway process does." in conditions
    # 2. Both bounds, named as the settings they are, and the clause that surprises —
    #    a stream carries no request, so watching does not refresh the idle timeout
    #    (ADR-0175 §7).
    assert "<code>gateway_session_ttl</code>" in conditions
    assert "<code>gateway_session_idle_timeout</code>" in conditions
    assert "Watching for notifications is not such a request" in conditions
    # 3. The one ADR-0168 §6 corrected itself about: the cookie is a session cookie and
    #    a browser that restores its previous session carries it across a close, so
    #    closing the browser *may* end the session. §6 requires the page to be honest
    #    that the gateway cannot see which.
    assert "may end it and may not" in conditions
    assert "minted at the machine the gateway runs on" in conditions
    # And it is reached by no script and hidden by no rule. The sheet does carry one
    # `display: none` — the rule that makes `[hidden]` hide anything at all (#1475),
    # without which nothing on this page is ever off screen — so the claim is made
    # about what that rule can reach rather than about the string: it is the sheet's
    # only one, it keys on the attribute, and these sentences carry the attribute
    # neither on their own element nor on an ancestor. They sit between two panels
    # rather than inside one, which is what makes the second half decidable here: the
    # last section tag before them is a close.
    assert "session-conditions" not in _code("app.js")
    stylesheet = _style("app.css")
    assert stylesheet.count("display: none") == 1
    assert _rule(stylesheet, "[hidden]").strip() == "display: none !important;"
    assert "hidden" not in document[opened : document.index(">", opened)]
    markup = _markup("index.html")
    sentences = markup.index('<div class="session-conditions">')
    assert markup.rindex("</section>", 0, sentences) > markup.rindex("<section", 0, sentences)


def test_the_page_names_no_signal() -> None:
    """ADR-0182 §1, which is why the sentence above stops at "at the machine the
    gateway runs on".

    The mint act is the delivery of `SIGUSR1`, whose default action terminates the
    process — and a gateway that could install neither the disposition nor an ignore
    "names the act in no disclosure ... No lane may read the disclosure clause below as
    obliging a gateway to advertise a signal that would end every live session". Which
    of those states a gateway is in is not visible from a browser, so a page that named
    the signal would be advertising it on the one deployment where sending it is fatal.

    §10 puts the act in the first-run guide instead, where the gateway's own start
    disclosure is beside it.
    """
    for name in ("index.html", "app.js", "app.css"):
        assert "SIGUSR1" not in _asset(name), name


def test_a_session_that_ended_is_re_entry_and_not_a_fault() -> None:
    """ADR-0182 §6: "A browser presenting a header half the gateway does not admit is
    shown the bootstrap entry, presented as re-entry rather than as a fault. It is not
    rendered in the page's fault surface."

    A session that ran out its idle timeout ended exactly as the sentences above say
    sessions end. #1429's survey found one fault slot at the foot of a thirteen-panel
    page and lane 3 moved the slots beside their panels; putting a legitimate ending in
    any of them is the same lesson one layer on — an owner who is shown ordinary
    endings in the slot kept for things that went wrong learns to stop reading it.

    The condition the gateway named is carried into the hint rather than dropped. §6
    does not oblige the page to distinguish which condition ended the session, but
    where the gateway did name one, trading the words for the placement would be one
    silence swapped for another.
    """
    script = _code("app.js")
    document = _markup("index.html")
    lost = _functions(script)["sessionLost"]

    assert '<p class="hint" id="reentry"></p>' in document
    assert "const RE_ENTRY =" in script
    assert "showBootstrap(said ? `${RE_ENTRY} ${said}` : RE_ENTRY);" in lost
    # Nothing on this path reaches the fault surface — not in `sessionLost`, and not in
    # either caller that used to write the bootstrap slot itself.
    assert "fault(" not in lost
    reporting = _functions(script)["report"]
    assert "if (sessionLost(body, message)) {" in reporting
    assert reporting.index("return;") < reporting.index("fault(message, panelId);")
    assert "sessionLost(body, describe(body, response.status));" in _functions(script)["act"]
    # The bootstrap panel keeps its fault slot, and it is right that it does: a refused
    # *exchange* is a fault about the value that was typed, which is not this clause.
    assert (
        'fault(describe(body, response.status), "bootstrap");' in _functions(script)["startSession"]
    )
    # An explanation is cleared when it stops being true and not by the next click: every
    # act guards a missing half by calling `showBootstrap` with nothing.
    assert "if (because !== undefined) {" in _functions(script)["showBootstrap"]
    assert 'el("reentry").textContent = "";' in _functions(script)["showConsole"]


def test_a_mismatch_is_said_as_the_comparison_it_was_and_asks_for_no_restart() -> None:
    """Issue #1471, found by the milestone-16 QA (#1468, arm B) as a user rather than
    as a reading: a browser closed with the session cookie in it, opened again inside
    the idle timeout, and told that "another local service replaced this gateway's
    cookie" and to "restart the gateway".

    **The cause was asserted and never established.** ``SessionTable.admit`` reaches
    this condition for any cookie count but exactly one — ``len(cookie_halves) != 1``
    — so a browser that dropped a session cookie on close takes the same branch a
    second local service overwriting it does, and the gateway cannot tell them apart.
    ADR-0168 §6 obliges the *distinction* from an ordinary absent session, which the
    sentence keeps; it obliges no story about how the halves came apart, and there is
    none to tell.

    **The remedy was stale rather than merely unnecessary.** ADR-0182 §1 replaced
    "restart the gateway" with a mint the owner performs at the running process, so
    the advice named an act that is no longer the way back — and one that, followed,
    would have ended every other live session to recover this one.

    Nothing takes its place, for the reason the ``no-live-session`` entry beside it
    states: this prose is appended to ADR-0182 §6's re-entry sentence in the bootstrap
    panel's own hint, and that panel already says a value is minted at the machine the
    gateway runs on. It is not said here again, and it is not said with the signal's
    name — :func:`test_the_page_names_no_signal` is why.
    """
    script = _code("app.js")
    opened = script.index("const FAULTS = {")
    faults = script[opened : script.index("\n};", opened)]
    key = faults.index('"cookie-half-mismatch":')
    # To the next key rather than to the next newline, so a future edit that wraps the
    # value across lines is read whole rather than read as its first line.
    after = re.search(r'\n  "?[a-z-]+"?:', faults[key:])
    entry = faults[key : key + (after.start() if after else len(faults) - key)]

    assert "The two halves of this browser's session no longer match." in entry
    assert "local service" not in entry
    assert "restart" not in entry.lower()
    # Which is only the right shape because this condition is never rendered as a
    # fault: every path carrying it reaches `sessionLost` first, and the entry is the
    # `said` that joins the re-entry sentence there.
    assert '"cookie-half-mismatch"' in _functions(script)["sessionLost"]


def test_the_header_half_is_held_in_origin_scoped_storage_shared_across_tabs() -> None:
    """§6: "held in browser storage scoped to **scheme, host and port** and shared
    across that origin's tabs".

    That is what closes the leak the cookie cannot: "web storage *is* origin-scoped
    where a cookie is not, so the value at `127.0.0.1:8422` is unreadable from
    `127.0.0.1:9000`". `sessionStorage` is scoped to a tab rather than shared
    across the origin's, so it is not the storage this clause names.
    """
    script = _code("app.js")

    assert "localStorage" in script
    assert "window.localStorage.setItem(STORAGE_KEY, value)" in script
    # The page stores one other thing, and it is **not** a session half: the chat this
    # view has open, which is the tab's rather than the origin's. So the clause is
    # asserted where it is about — no half of a session is ever in tab-scoped storage —
    # and the keys that are, are named: whether this tab has the chat open and which
    # conversation it reads.
    assert set(re.findall(r"window\.sessionStorage\.\w+\((\w+)", script)) == {
        "CHAT_OPEN_KEY",
        "CHAT_CONVERSATION_KEY",
    }


def test_the_front_end_never_reads_the_cookie_half() -> None:
    """§6: the cookie half "is not readable by any script", which is the property
    that makes a value stolen out of storage not a session on its own."""
    assert "document.cookie" not in _code("app.js")


def test_the_header_half_is_sent_as_a_header_and_never_in_a_url() -> None:
    """§6: "it is sent only as a request header the front end sets… never placed in
    a cookie, in a URL, or in storage that outlives the origin's own scope"."""
    script = _code("app.js")

    assert "X-Assistant-Session" in script
    assert not re.search(r"[?&][A-Za-z_]*(session|token|half)", script)


def test_every_row_of_the_listing_says_which_conversation_it_is() -> None:
    """#1371's first clause, at the place the owner chooses from.

    Found by driving the page rather than by reading it, which is the division
    ADR-0216 §8 keeps: every other line about a conversation names it — the
    indicator, the destroy ceremony, the outcome of a forget — and the listing all
    three send the owner to named none of them. Three rows of two timestamps, and
    the sentence that appears after a tap names an id that had never been on screen.

    Its own full-width line rather than a clause of the instants: an id is a hub
    value of no bounded length, and a row that makes it compete for horizontal space
    with two timestamps is one long id away from #1385's "Remo ve".
    """
    script = _code("app.js")
    stylesheet = _asset("app.css")
    rendering = _functions(script)["renderConversation"]

    assert 'line(item, `Conversation ${summary.id}`, "conversation-name");' in rendering
    # First, so the id is above the row rather than between its two facts.
    assert rendering.index("conversation-name") < rendering.index("Last turn")
    assert "flex: 1 1 100%;" in _rule(stylesheet, ".conversation-name")


def test_a_request_its_caller_stopped_classifies_nothing_even_after_a_head() -> None:
    """Adversarial review round 4: aborting shuts one window and not the other.

    ``fetch`` settles when the *head* lands, so a refusal's head can arrive before the
    abort and its body read reject afterwards. ``readBody`` swallows that rejection —
    right for the refusal path it was written for, because a proxy really can replace
    a condition, and wrong here: ``{}`` comes back and the panel is told "The gateway
    refused that request (HTTP 404)" about a thread the owner has left.

    It throws rather than returning ``null``, because ``null`` says "refused, and the
    condition is already on screen" at nineteen call sites and neither half holds. The
    true statement is that no response was read, which is where ADR-0177 §7's fourth
    clause already puts the other caller that passes a controller.

    **Asserted here rather than driven**, and ADR-0216 §2 is the ground: this is a
    property of the shipped bytes, and the ordering it turns on — a head delivered and
    its body then withheld — is not constructible against a real gateway from a route
    handler. A browser case for it would have to fabricate the gateway's response,
    which is the author's belief checked against itself (ADR-0216 §1) rather than
    evidence. What *is* drivable — an abort before the head — is driven, twice, in
    ``test_browser_conversations.py``.
    """
    relaying = _functions(_code("app.js"))["relay"]

    assert "if (stopping !== undefined && stopping.signal.aborted) {" in relaying
    assert "throw stopping.signal.reason;" in relaying
    # After the body read and before anything is classified from it: an abort that
    # lands *during* the read is the case, so a check before it would miss it.
    assert relaying.index("await readBody(response)") < relaying.index("signal.aborted")
    assert relaying.index("signal.aborted") < relaying.index("refused(panelId")


def test_a_forget_states_what_the_hub_answered_rather_than_what_was_asked() -> None:
    """#1371's third clause, and the half of it that is a correctness fix.

    ``forget_conversation`` answers whether an episode was forgotten (memory-only
    since ADR-0293 §11:4), and this page had once discarded that answer. Both facts
    are said, and they are said differently; the forgotten one says plainly that the
    conversation and its transcript stay and only deleting removes them (§5:7).
    """
    document = _asset("index.html")
    functions = _functions(_code("app.js"))

    assert '<p class="notice" id="forget-outcome" hidden></p>' in document
    assert (
        "sayForgotten(statedForget(id, held, done.destroyed));" in (functions["forgetConversation"])
    )
    stated = functions["statedForget"]
    assert "if (!destroyed)" in stated
    assert "so nothing was forgotten." in stated
    assert "no longer recalls them anywhere else" in stated
    assert "only deleting removes them." in stated
    confirming = functions["forgetConversation"]
    assert "Forget conversation" in confirming
    assert "still reads it while you keep talking there" in confirming


def test_the_forget_outcome_is_written_after_the_refresh_it_triggered() -> None:
    """The order is load-bearing rather than cosmetic.

    ``listConversations`` clears the slot on every read, so an outcome written
    *before* the refresh would be erased by it, and an outcome left standing over a
    listing read afresh from the panel's own button would be a claim about a listing
    it was never made against. Writing after its own refresh is what makes the
    outcome survive exactly one listing and no other.
    """
    functions = _functions(_code("app.js"))
    forgetting = functions["forgetConversation"]

    assert "sayForgotten(null);" in functions["listConversations"]
    assert forgetting.index("await listConversations();") < forgetting.index("sayForgotten(stated")


def test_a_superseded_listing_read_renders_neither_a_list_nor_a_fault() -> None:
    """Adversarial review round 6: the generation guarded the outcome and not the list.

    Two reads of this listing can overlap — a forget's own refresh and the owner
    pressing "Conversations" — and the one that resumes last won the panel whether or
    not it was the newer, re-rendering a snapshot taken before it. A conversation
    destroyed in between came back as a row for a conversation that was gone.

    Both halves are closed and they close different things: stopping the read is what
    keeps ``relay`` from writing that read's *refusal* into the panel before this
    function sees a value, and the comparison is what keeps a body that arrived anyway
    from being rendered. The two together are the reviewer's own direction.
    """
    listing = _functions(_code("app.js"))["listConversations"]

    assert "superseded.abort();" in listing
    assert "const stopping = new AbortController();" in listing
    assert "listing = stopping;" in listing
    assert "if (body === null || mine !== listed) {" in listing
    # And only the newest read is entitled to say the gateway has gone.
    assert "if (mine === listed) {" in listing
    # The stop is registered before the read and taken before the next one begins, so
    # a read can never abort the controller a later one registered.
    assert listing.index("superseded.abort();") < listing.index("listing = stopping;")


def test_a_refresh_that_is_no_longer_the_newest_listing_writes_no_outcome() -> None:
    """Adversarial review round 1: writing after its own refresh is not enough.

    A forget's refresh can lose its race to a listing the owner asked for afterwards,
    and the resuming older call would then write its outcome into a slot the newer
    read had already cleared — above a listing it did not produce. Counting reads as
    they *begin* is what lets the older one see that it is no longer the last word.

    Begun and not finished is the load-bearing half: a counter bumped when a read
    *returns* would be equal again by the time the loser resumed, and would answer
    the wrong question.
    """
    functions = _functions(_code("app.js"))
    listing = functions["listConversations"]

    assert listing.index("listed += 1;") < listing.index("await relay(")
    assert "const mine = listed;" in listing
    # Returned from all five paths, the refusals included: a forget whose refresh
    # failed still destroyed something and still owes the owner the sentence saying
    # so, so a read that ended in a fault must not swallow the outcome as well. Two of
    # the five are #2404's session guard, on the resuming and the failing path, and
    # they return the number for the same reason: a listing dropped because the session
    # under it ended is still a listing that began, and the caller comparing against it
    # is asking which read was last.
    assert listing.count("return mine;") == 5
    assert "if (read === listed) {" in functions["forgetConversation"]


def test_the_forget_ceremony_is_unchanged_and_no_second_one_is_added() -> None:
    """ADR-0175 §6: a front-end confirmation "is not a control and is not required".

    Saying what a forget *did* is legibility and is written after the act. It is not
    a second gate: the conversation surface shows exactly one ceremony, the
    show-then-confirm ADR-0073 §5 asks for, in the one function that destroys — and
    the two functions this lane added or changed beside it raise none.

    The count is taken over that function rather than over the file, because the
    file's other destructive controls each keep a ceremony of their own and this
    case is not about them.
    """
    functions = _functions(_code("app.js"))

    assert functions["forgetConversation"].count("window.confirm(") == 1
    assert "window.confirm(" not in functions["listConversations"]
    assert "window.confirm(" not in functions["statedForget"]


def test_the_front_end_tells_a_transport_failure_apart_from_a_refusal() -> None:
    """§9's distinction has to survive to what the owner reads, not stop at the
    status code: "a transport failure, distinguishable from a request the hub
    received and declined"."""
    script = _code("app.js")

    assert "hub-unreachable" in script
    assert "assistant-declined" in script
    assert "cookie-half-mismatch" in script
    # ADR-0175 §4's poll conditions, each its own: a budget the hub declined, and a
    # poll that failed in neither of §9's two ways and is not reported as either.
    assert "delivery-budget-declined" in script
    assert "delivery-failed" in script


def test_a_fault_is_written_beside_the_act_that_raised_it() -> None:
    """#1429: one slot at the foot of a thirteen-panel page is a condition the owner
    has to scroll to find.

    That is ADR-0083's ruling 4 losing at the last hop it has to survive: ADR-0168 §9
    spends a clause keeping a transport failure distinguishable from a refusal all the
    way to the browser, and a page that then renders it off-screen has flattened it
    into silence after all.

    The panel is asserted per call rather than in aggregate — a page that named one
    panel and sent the other fifteen conditions to the foot would satisfy any count.
    """
    script = _code("app.js")
    document = _asset("index.html")
    sections = set(re.findall(r'<section id="([a-z-]+)"', document))

    named, unnamed = [], []
    for call in _fault_calls(script):
        panel = re.search(r'.,\s*"([a-z-]+)"$', call)
        (named.append(panel.group(1)) if panel else unnamed.append(call))

    assert set(named) == _FAULT_PANELS
    assert sections >= _FAULT_PANELS
    assert tuple(sorted(unnamed)) == _UNNAMED_FAULTS


#: The four panels ``showBootstrap`` names one by one, because for each of them it is
#: saying something rather than closing a control panel: the bootstrap entry is what it
#: opens, and the console, the conversations listing and the notification panel are the
#: three surfaces a session-less page stops *being* rather than stops showing.
_NAMED_BY_SHOW_BOOTSTRAP: Final = frozenset(
    {"bootstrap", "console", "conversations", "notifications"}
)

#: The panels outside the hide sweep on purpose — and there is one, recorded here so
#: that the census below states a decision instead of blessing whatever the list
#: happens to contain.
#:
#: ``answer`` holds the reply to the owner's last question, which is Tier 1 content and
#: on the face of it belongs in the sweep. It is left out **here** because hiding it is
#: not the one line the other panels cost: it is written by a park's answer through
#: ``couldRenderOutcome`` rather than by a listing, and adding it to the sweep without
#: carrying #2404's guard into that path would hide it at session loss only for a reply
#: still in flight to put it back. Filed as #2446 rather than taken here.
_OUTSIDE_THE_HIDE_SWEEP: Final = frozenset({"answer"})


def test_every_panel_a_session_less_page_may_not_show_is_in_the_hide_sweep() -> None:
    """#2395: ``goals`` was in every census of this page except the one that hides it.

    ``showBootstrap`` names four panels itself and sweeps ``CONTROL_PANELS`` for the
    rest, so a panel added to the document and left out of that list is not hidden when
    the session ends — and the goals panel, which renders outcome statements,
    clarification text and goal ids, sat behind the bootstrap form for as long as the
    owner left it open.

    **Taken over the document rather than over the list**, which is the whole point: a
    check that read the panels out of ``CONTROL_PANELS`` would have passed on the day
    ``goals`` went missing from it. Every ``section.panel`` the page ships is either
    named by ``showBootstrap``, in the sweep, or in :data:`_OUTSIDE_THE_HIDE_SWEEP` with
    its reason written down.
    """
    document = _asset("index.html")
    script = _code("app.js")
    sections = set(re.findall(r'<section id="([a-z-]+)" class="panel"', document))
    opened = script.index("const CONTROL_PANELS = [")
    swept = set(re.findall(r'"([a-z-]+)"', script[opened : script.index("];", opened)]))
    sweeping = _functions(script)["showBootstrap"]

    assert "goals" in swept
    assert sections - _NAMED_BY_SHOW_BOOTSTRAP - _OUTSIDE_THE_HIDE_SWEEP == swept
    assert swept <= sections
    assert "CONTROL_PANELS.forEach((panel) => show(panel, false));" in sweeping
    for panel in _NAMED_BY_SHOW_BOOTSTRAP - {"bootstrap"}:
        assert f'show("{panel}", false);' in sweeping
    assert 'show("bootstrap", true);' in sweeping


#: The acts that report what became of *themselves* after their session has ended, and
#: are therefore outside #2404's guard — recorded here so the census states a decision
#: rather than blessing whatever the script happens to do.
#:
#: A listing that outlives its session has nothing to say: its rows are the owner's and a
#: page with no session may not be showing them. An act does: something may have been done
#: to the owner's records, and the account of it is this page's own history, which outlives
#: a session exactly as ``unresolved`` and ``ACCOUNTS`` do. What is *not* settled is
#: whether the account may re-open its panel to be read — ``fault`` shows the panel it
#: writes into — and that is a ruling about what a session-less page owes rather than an
#: extension of this sweep. Filed as #2451, which names this set.
_ACTS_THAT_ACCOUNT_FOR_THEMSELVES: Final = frozenset(
    {
        "answerQuestion",
        "withdrawClarification",
        "abandonGoal",
        "revokeAuthorization",
        "dismissNotification",
    }
)


#: The one *success path* left outside the rule below, as a (function, which
#: ``await relay``) pair — read the constant above first, because this is the same
#: carve-out at a finer grain. ``forgetBelief``'s second request is the destruction
#: itself, and what follows it is the account of what that destruction did: "There was
#: no such belief" for a record the hub no longer held. That is an act reporting itself,
#: and #2451 is the ruling that decides whether such an account may open its panel.
#:
#: **It exempts that path and not the request**, which adversarial review round 6 found
#: the version of this that did not: skipping the whole segment took its
#: transport-failure ``catch`` with it, and the guard could have been deleted from there
#: with every case green while an aborted destruction re-opened the beliefs panel beside
#: the bootstrap form. A failing path is asked its question whatever the segment.
#:
#: Its three siblings need no entry, and not by luck: ``forgetConversation`` says what it
#: destroyed through ``sayForgotten``, which writes into a node *inside* the panel and
#: reveals nothing, and the other two display nothing after their destruction at all.
_SEGMENTS_THAT_ACCOUNT_FOR_AN_ACT: Final = frozenset({("forgetBelief", 2)})


#: The functions that still reach ``sessionLost`` without asking whose session it is,
#: and the issue that empties this set (#2446).
#:
#: ``report`` is ``sessionLost`` at one remove, and ``sessionLost`` calls
#: ``forgetHeaderHalf``, which removes the stored half whatever session that half belongs
#: to. The half is shared by every tab at this origin, so **any** ``report`` or
#: ``refused`` reached after an ``await`` is a door through which a request belonging to a
#: session that has already ended can end the session the owner is actually using. #2404
#: closed every one that goes through ``relay``; #2455 closed the delivery stream's two,
#: which are the ones the census above cannot see because ``readDeliveries`` issues its
#: own ``fetch``.
#:
#: What was left were the **ask** paths, ``askWhole`` and ``sendRecording`` (#2446), and
#: they retired with the Ask panel and push-to-talk (ADR-0309 §5:4, ADR-0313 §3:4). So
#: the set is empty, and it is kept rather than dropped so that a later door reaching
#: ``sessionLost`` unguarded has to be named here rather than slipping past the census.
_REPORTS_WITHOUT_A_SESSION_GUARD: Final[frozenset[str]] = frozenset()


def test_every_resumed_relay_that_displays_anything_compares_its_session() -> None:
    """The rule over the whole script, and the exclusions named (#2404).

    Three things a resumed continuation can put on the screen, and all three are display:
    revealing a panel, putting a ``window.confirm`` in front of the owner with a record's
    content in it, and writing a fault — which ``show``s the panel it writes into. So the
    test is not "every listing" but "every function that awaits ``relay`` and then shows
    the owner something", and what it asks of each is that the comparison comes first.

    Adversarial review round 2 is why it is written this way round: the first version
    selected functions carrying a literal ``show(..., true)``, which stepped straight past
    ``forgetBelief`` and its three siblings — reads taken only to put a record in front of
    the owner before destroying it, whose ``window.confirm`` carries a belief's content, a
    conversation's turn count or a notification's summary onto a page that is asking for a
    session.

    **Every request of a function, and not just its first** — adversarial review round 5,
    ``major``, about the version of this test that sliced from the first ``await relay``
    and read to the end. A guard after a *prerequisite* read satisfied that reading
    whatever the function then did with a second request, so ``writePreferences``' second
    guard could have been deleted with every case here still green. Each request's segment
    is now asked its own question, and the one segment outside the rule is named in
    :data:`_SEGMENTS_THAT_ACCOUNT_FOR_AN_ACT` rather than hidden by a slice.

    The only functions outside it are the acts of :data:`_ACTS_THAT_ACCOUNT_FOR_THEMSELVES`
    and those that display nothing at all, which need no guard and are selected out by the
    same test that selects everything else in.
    """
    functions = _functions(_code("app.js"))
    checked = []
    for name, body in functions.items():
        if "await relay(" not in body or name in _ACTS_THAT_ACCOUNT_FOR_THEMSELVES:
            continue
        sending = [one.start() for one in re.finditer("await relay\\(", body)]
        asked = []
        for which, opened in enumerate(sending, start=1):
            closed = sending[which] if which < len(sending) else len(body)
            segment = body[opened:closed]
            # The failing path is split out and asked its own question, because the
            # exemption above is about an act's *account of itself* and a `catch` is not
            # one: what it writes is a condition, and `fault` opens the panel it writes
            # into whatever the request was.
            resumed, _, failing = segment.partition("} catch (_) {")
            for path, part in (("resumed", resumed), ("failing", failing)):
                if path == "resumed" and (name, which) in _SEGMENTS_THAT_ACCOUNT_FOR_AN_ACT:
                    continue
                shown = [
                    part.index(one)
                    for one in ('show("', "window.confirm(", "fault(")
                    if one in part
                ]
                if shown:
                    asked.append(((name, which, path), part, min(shown)))
        if not asked:
            # Nothing it does after a request is display, so it has nothing to guard --
            # `answerConfirmation` and `cancelRead`, whose endings are records rather
            # than renderings, and `stateAfterAct`, which writes into an act's own log.
            continue
        # Captured before the first request goes out -- an era read on resumption is the
        # value it is being compared against and would never differ from it.
        assert body.index("const era = sessionEra;") < body.index("await relay("), name
        for where, part, displayed in asked:
            checked.append(where)
            assert "if (!sameSession(half, era)) {" in part, where
            assert part.index("if (!sameSession(half, era)) {") < displayed, where

    assert {
        ("readGoals", 1, "resumed"),
        ("readGoals", 1, "failing"),
        ("forgetBelief", 1, "resumed"),
        ("forgetBelief", 2, "failing"),
        ("writePreferences", 2, "resumed"),
    } <= set(checked)
    # And the exclusions are real functions of this script rather than names that have
    # gone stale: a set holding a function that no longer exists silently excuses nothing,
    # which is exactly how a list like this rots into a permission.
    assert set(functions) >= _ACTS_THAT_ACCOUNT_FOR_THEMSELVES


def test_every_listing_that_resumes_asks_whether_its_session_still_stands() -> None:
    """#2404: the generation counters order two listings and say nothing about the
    session under them.

    Let a listing hang, let any other request meet ``no-live-session`` — ``sessionLost``
    forgets the header half and puts the bootstrap entry back — and the hanging run is
    still the latest, so it resumes, renders, and reveals its panel beside a form asking
    the owner to start a session. PR #2393's adversarial review found it at round 9 in
    ``listAuthorizations``; this is the sweep.

    **Universally quantified rather than listed**, so a listing added after this is
    covered by the rule instead of by an enumeration somebody has to remember to
    extend. The named anchors are there only to prove the scan found anything at all:
    a regex that matched nothing would otherwise satisfy every assertion in the loop.
    """
    script = _code("app.js")
    functions = _functions(script)
    checked = []
    for name, body in functions.items():
        if "await relay(" not in body:
            continue
        resumed = body[body.index("await relay(") :]
        if not re.search(r'show\("[a-z-]+", true\)', resumed):
            continue
        checked.append(name)
        # Captured before the request goes out -- an era read on resumption is the
        # value it is being compared against and would never differ from it.
        assert body.index("const era = sessionEra;") < body.index("await relay("), name
        assert "if (!sameSession(half, era)) {" in resumed, name
        assert resumed.index("sameSession(half, era)") < resumed.index('show("'), name
        # And the failing path, which reveals the panel too: `fault` shows the panel it
        # writes into, so a listing whose request fails after its session ended would
        # otherwise re-open a control panel beside the bootstrap form -- moments after
        # `showBootstrap` hid every panel and cleared every fault slot. Adversarial
        # review, round 1, `major`.
        failing = body[body.rindex("} catch (_) {") :]
        assert "if (!sameSession(half, era)) {" in failing, name
        assert failing.index("sameSession(half, era)") < failing.index("fault("), name

    assert {"readGoals", "readBeliefs", "listConnections", "listAuthorizations"} <= set(checked)
    # The one listing that reveals its panel *before* it sends: nothing it does after
    # the await is a reveal, so what the guard has to precede there is the render.
    standing = functions["listStanding"]
    assert standing.index("sameSession(half, era)") < standing.index('el("standing-list")')


def test_a_refusal_the_session_outlived_is_classified_but_not_displayed() -> None:
    """The one place the guard cannot sit at the caller, and what it must not withhold.

    ``relay`` renders a refusal *before* it returns, so a comparison after the ``await``
    is too late for it: a listing released after the owner re-enters carries the old
    header half and the new cookie, the gateway answers ``cookie-half-mismatch``, and
    ``refused`` → ``report`` → ``sessionLost`` forgets the half of the session the owner
    has just started.

    **``noticed`` stays outside the guard**, which adversarial review's round 1 found the
    version of this that did not. It is a fact about the *act* rather than about the
    panel: ``answerConfirmation`` and ``cancelRead`` read the condition to sort ADR-0177
    §7's third clause, and a ``refusal`` left null reads as a refusal the page cannot
    classify at all — stranding a consent token and telling the owner an action the
    gateway refused at the door may have been carried out.
    """
    relaying = _functions(_code("app.js"))["relay"]

    assert relaying.index("const era = sessionEra;") < relaying.index("await fetch(")
    assert relaying.index("noticed(body);") < relaying.index("if (!sameSession(half, era)) {")
    assert relaying.index("if (!sameSession(half, era)) {") < relaying.index("refused(panelId")


def test_every_ending_that_can_end_a_session_asks_whose_session_it_is() -> None:
    """The rule over the doors ``relay`` does not own, and the one gap named (#2455).

    ``test_every_resumed_relay_that_displays_anything_compares_its_session`` is scoped to
    "every function that awaits ``relay``", which is honest and leaves this class
    unclaimed: a caller that issues its own ``fetch`` and then calls ``report`` reaches
    ``sessionLost`` — and therefore ``forgetHeaderHalf`` — with nothing comparing the
    session its request was sent under against the one this browser now holds. The
    delivery stream was the whole of that class in ADR-0175 §4's surface, and it is the
    reachable one: §7 has an idle session expire *under* an open stream, so a stream
    answering ``no-live-session`` for a session that ended an hour ago is the design
    working, and evicting another tab's freshly minted half with it was #2455.

    **Per call site rather than per function.** A single guard before the first
    ``report`` would otherwise satisfy a function with two endings, which is exactly the
    shape ``readDeliveries`` has — a refusal at the head and a terminal value on the body
    — so each call is asked whether a comparison stands between it and the one before it.

    **The exclusions are three and they are named**: ``refused`` and ``relay``, where the
    comparison already sits inside — ``test_a_refusal_the_session_outlived_is_classified``
    ``_but_not_displayed`` is where that is pinned — and
    :data:`_REPORTS_WITHOUT_A_SESSION_GUARD`, which is #2446's open work.
    """
    script = _code("app.js")
    functions = _functions(script)
    checked = []
    for name, body in functions.items():
        if name in {"refused", "relay"} or name in _REPORTS_WITHOUT_A_SESSION_GUARD:
            continue
        calls = [one.start() for one in re.finditer(r'(?<![\w.])(?:report|refused)\("', body)]
        if not calls:
            continue
        checked.append(name)
        previous = 0
        for call in calls:
            assert "if (!sameSession(half, era)) {" in body[previous:call], (name, call)
            previous = call

    # The scan found the surface it is about: a regex that matched nothing would satisfy
    # every assertion in the loop above.
    assert "readDeliveries" in checked
    # And the carve-out names real functions rather than names that have gone stale,
    # which is how a list like this rots into a permission.
    assert set(functions) >= _REPORTS_WITHOUT_A_SESSION_GUARD


def test_the_delivery_stream_carries_the_session_it_was_opened_under() -> None:
    """Why the guard above is reachable at all on this surface (#2455).

    Every other caller reads the half and the era in the same breath and compares them
    after its own ``await``. A delivery stream cannot: the pair has to survive a request
    that is *expected* to outlive its own session, and ``readDeliveries`` is called from
    ``watchDeliveries`` rather than opened where the half was read. So the era is captured
    beside the half in the caller and handed down, which is the second of #2455's two
    directions — the first, comparing inside ``forgetHeaderHalf`` itself, would have to be
    told which half the provoking request carried, and the only way to tell it is through
    ``report``, whose callers are most of this file.

    **Captured before ``watching`` is set**, so that nothing between reading the half and
    committing to the stream can move either part of the pair.
    """
    functions = _functions(_code("app.js"))
    watch = functions["watchDeliveries"]

    assert "const era = sessionEra;" in watch
    assert watch.index("const half = headerHalf();") < watch.index("const era = sessionEra;")
    assert watch.index("const era = sessionEra;") < watch.index("watching = true;")
    assert "await readDeliveries(half, era);" in watch
    assert "async function readDeliveries(half, era) {" in _code("app.js")
    # Neither ending reports before it has compared, and the stream that outlived its
    # session says so in the line that hands the control back rather than in a fault
    # slot: nothing went wrong, and nothing here was ended.
    read = functions["readDeliveries"]
    assert read.count("if (!sameSession(half, era)) {") == 3
    assert read.count("stopWatching(OUTLIVED_ITS_SESSION);") == 3
    assert "forgetHeaderHalf" not in read
    # The third is the `catch`, and it sits below the release and above the
    # classification (adversarial review, round 1). Nothing there can evict a half, but
    # each of the four branches writes a `fault`, and a rule that let a superseded stream
    # report a black hole while refusing it a cut would be two rules for one ending.
    failing = read[read.index("} catch (error) {") :]
    assert failing.index("if (open.released) {") < failing.index("if (!sameSession(half, era)) {")
    assert failing.index("if (!sameSession(half, era)) {") < failing.index("if (stalled) {")


def test_the_session_era_moves_exactly_where_the_stored_half_does() -> None:
    """The count is only worth comparing if it cannot fall out of step with the half.

    Both writers of the stored half bump it, and nothing else does — so there is no
    third place a session can begin or end without the requests in flight being told.
    Asserted as an exact count rather than as two occurrences, because an era bumped
    somewhere else as well is an era that drops answers the page asked for.
    """
    script = _code("app.js")
    functions = _functions(script)

    assert script.count("sessionEra += 1;") == 2
    assert "sessionEra += 1;" in functions["rememberHeaderHalf"]
    assert "sessionEra += 1;" in functions["forgetHeaderHalf"]
    # Counted before the write, so a store that refuses still ends the era: a page that
    # cannot hold a session must not leave an earlier one's answers admissible.
    remembering = functions["rememberHeaderHalf"]
    assert remembering.index("sessionEra += 1;") < remembering.index("setItem")


def test_the_page_foot_keeps_the_slot_for_a_fault_no_panel_owns() -> None:
    """#1429 moves the faults that have a panel and keeps the ones that do not — the
    page's own load, and the session — because those have no panel to sit beside and
    the slot has to exist before anything has been built.

    The slot's text is its own element rather than the container's ``textContent``,
    which is what lets the dismiss control live inside it: writing a message onto the
    container would destroy the button on the first fault.
    """
    document = _markup("index.html")
    script = _code("app.js")

    assert re.search(r'<div id="fault" class="fault" hidden>', document)
    assert '<p class="fault-text"></p>' in document
    assert 'id="fault-dismiss"' in document
    assert 'node.firstElementChild.textContent = message === null ? "" : message;' in script


def test_a_dismiss_control_dismisses_and_does_nothing_else() -> None:
    """A control that quietly re-ran the act would be the silent retry ADR-0168 §9
    forbids wearing a button's clothes — so what is pinned is the absence of anything
    else in it, not the presence of the handler.

    A slot is built by the script rather than written out once per panel in the
    document, so the check is on the builder: it appends a text node and a button, and
    it reaches for no value the hub returned.
    """
    script = _code("app.js")
    builder = _functions(script)["offerDismiss"]

    assert 'dismiss.addEventListener("click", () => fault(null, panelId));' in builder
    assert "fetch(" not in builder
    assert "relay(" not in builder
    assert 'el("fault-dismiss").addEventListener("click", () => fault(null));' in script


def test_a_fault_reveals_the_panel_it_is_written_into() -> None:
    """A read that failed before its panel was ever shown would otherwise write the
    reason into a panel nobody can see, which is the same flattening one layer on.

    The reveal is on the write and not on the clear: `fault(null, …)` must not open a
    panel the owner never asked for, and that is what the second half asserts.
    """
    writer = _functions(_code("app.js"))["fault"]

    assert "if (message !== null && where !== null) {" in writer
    assert writer.index("message !== null && where !== null") < writer.index("show(where, true)")


# --- ADR-0175: the page's half of the streamed surface ----------------------


def test_the_page_reads_a_stream_as_a_response_body_and_opens_no_socket() -> None:
    """§1: the carrier is "the body of the response to one ordinary HTTP request that
    browser made", and the gateway "serves no WebSocket, offers no protocol upgrade…
    and serves nothing a browser reaches with ``EventSource``".

    The reason is mechanical rather than stylistic and it is worth checking on the
    *file*: neither interface lets a page set a request header on the request that
    opens it, so on either one ADR-0168 §6's header half has nowhere to go that §6
    admits — and a request carrying the cookie half alone is refused exactly as one
    carrying neither is.
    """
    script = _code("app.js")

    assert "WebSocket" not in script
    assert "EventSource" not in script
    assert "response.body.getReader()" in script


def test_the_page_resolves_a_stream_value_by_its_kind_and_never_by_its_shape() -> None:
    """§2: "a reader resolves a value's kind from a discriminator the value itself
    carries and never by inspecting what the value contains".

    ADR-0173 §4 requires the same of the reader one hop in, and a browser reading a
    stream is the second reader of that sequence — a surface that made it guess from a
    payload's shape would reintroduce, in the half of the system that renders
    untrusted model output, exactly the ambiguity the wire refuses.
    """
    script = _code("app.js")

    assert 'value.kind === "notification"' in script
    assert "TERMINAL_KINDS.has(value.kind)" in script


def test_the_page_tells_a_terminal_value_from_a_body_that_simply_stopped() -> None:
    """§2: "a reader that reached a terminal value has the whole of what the gateway
    sent; a reader that did not has a transport failure and the front end reports it
    as one, which is ADR-0168 §9's distinction reaching the browser"."""
    script = _code("app.js")

    assert "DELIVERY_STREAM_CUT" in script
    # One stream, and so one sentence, since ADR-0293 §11 retired the streamed answer.
    assert script.count("ended before the gateway finished it") == 1


def test_a_line_that_is_not_one_json_object_is_refused_by_the_reader_that_frames_it() -> None:
    """#2008: ADR-0175 §2's second clause is exhaustive, so this is its second limb.

    "Every stream ends in exactly one of two ways … the gateway wrote a **terminal**
    value, or the body ended without one. A reader that reached a terminal value has the
    whole of what the gateway sent; a reader that did not has a transport failure and
    the front end reports it as one." A reader stopped by a line it cannot read reached
    no terminal value, so reporting it as a transport failure applies that clause rather
    than extending it, and no decision moves.

    **The guard is in the reader and not at each consumer.** "One JSON object per line"
    is ``streamValues``' own contract, so a line breaching it is refused where the
    contract is stated — which is also what makes ``value.kind`` unable to be read off
    something that cannot carry a kind, closing the second of #2008's two throw sites by
    construction rather than by a second check.

    **And it is refused as its own type.** A bare ``SyntaxError`` is indistinguishable
    at the catch that has to choose between four endings — the owner's abort, a failed
    connection, a body given up on, and this — so the throw carries which one it is.
    """
    script = _code("app.js")
    functions = _functions(script)

    assert "class MisframedValue extends Error {}" in script
    framing = functions["frameOf"]
    assert "value = JSON.parse(framed);" in framing
    assert framing.count("throw new MisframedValue();") == 2
    # A value is something a discriminator is read *from* (§2's first clause), and none
    # of these can carry one. An object whose kind this page does not know is a
    # different case and stays a value (ADR-0168 §10).
    assert 'if (value === null || typeof value !== "object" || Array.isArray(value)) {' in framing
    assert "TERMINAL_KINDS" not in framing
    # The reader frames every line through it, and parses none of its own accord.
    assert "yield frameOf(framed);" in functions["streamValues"]
    assert script.count("JSON.parse(") == 1


def test_the_two_misframed_endings_are_not_one_message_either() -> None:
    """One reader, two consumers, and therefore two sentences (adversarial review,
    round 1, ``blocker``).

    ``streamValues`` is read by the answer stream and by the delivery stream, so
    refusing a line there reaches both — and a change that gave only the first of them
    an ending left the second falling through to ``GATEWAY_GONE``, which for a line that
    parses to an array or a scalar was a *regression*: nothing threw on those before,
    so they had reached ``DELIVERY_STREAM_CUT``.

    The split is ``ANSWER_STREAM_CUT``/``DELIVERY_STREAM_CUT``'s own, for its own
    reason: "The condition is the same; what was cut is not", and an owner whose
    notifications stopped is not told about "that answer".
    """
    script = _code("app.js")
    read = _functions(script)["readDeliveries"]
    said = _joined(_constant(script, "DELIVERY_STREAM_MISFRAMED"))

    assert "could not read as a value on it" in said
    assert "has stopped watching" in said
    assert "Start watching again." in said
    # Neither of the two it displaces, and not the answer stream's subject either.
    assert "ended before the gateway finished it" not in said
    assert "may have stopped" not in said
    assert "that answer" not in said
    assert 'fault(DELIVERY_STREAM_MISFRAMED, "notifications");' in read
    assert script.count("DELIVERY_STREAM_MISFRAMED") == 2
    # Below the two aborts, which are this page's own acts, and above the gateway having
    # gone, which is what is left once the stream is known to have carried something.
    assert read.index("if (silent) {") < read.index("error instanceof MisframedValue")
    assert read.index("error instanceof MisframedValue") < read.index('fault(GATEWAY_GONE, "not')


def test_the_page_renders_the_outcome_whole_through_the_guard() -> None:
    """A park's answer is the one entry that renders a turn's outcome since the Ask route
    retired (ADR-0309 §5:4), and its outcome reaches the screen through
    ``couldRenderOutcome`` (#1622): the guard runs the render, and ``renderOutcome`` clears
    the panel before rendering.
    """
    script = _code("app.js")
    caveated = "unaccounted ? PARK_SETTLED_AFTER_UNKNOWN : null"

    assert (
        f"couldRenderOutcome(body.outcome, {caveated})" in _functions(script)["answerConfirmation"]
    )
    assert "renderOutcome(outcome, provenance);" in _functions(script)["couldRenderOutcome"]
    assert "clearNode(body);" in script


def test_the_page_renders_a_partly_composed_answer_as_incomplete() -> None:
    """§3's fourth shape, and the clause exists because a browser surface loses it by
    accident: an outcome carrying a ``reply`` *and* ``reply_degraded`` true "is the
    natural browser rendering of a stream… which displays that outcome identically to
    a complete one".

    ADR-0173 §10's own words are what it owes: never "a silent turn, and never as a
    failure of a step the account records as succeeded". So the partial text is
    rendered *and* said to be incomplete.
    """
    script = _code("app.js")

    assert "That answer is incomplete" in script
    assert "No answer could be composed for this turn" in script


#: The three browser speech APIs ADR-0200 §10 forbids by name, and the one that is a
#: substring of another is written once: checking for ``SpeechRecognition`` catches
#: ``webkitSpeechRecognition`` too, which is the vendor-prefixed spelling a lane
#: reaching for it would most likely use.
_BROWSER_SPEECH: Final = ("SpeechRecognition", "speechSynthesis")


@pytest.mark.parametrize("api", _BROWSER_SPEECH)
def test_the_front_end_runs_no_browser_speech_engine(api: str) -> None:
    """§13's ``§10`` row: "a test asserting the bundle references no
    ``SpeechRecognition`` or ``speechSynthesis``".

    §10's clause is that "The front end records with ``MediaRecorder`` and plays with
    the browser's ordinary audio playback. It does not call ``SpeechRecognition``,
    ``webkitSpeechRecognition`` or ``speechSynthesis``, and no lane may wire one."

    Three reasons and the third survives the other two being argued away: some
    implementations of those APIs transmit to the browser vendor, which is an egress no
    boundary in ADR-0174 §1 authorises; recognition at the edge would decide what a
    submission means, which ADR-0094 §6 forbids; and synthesis at the edge "would speak
    text the hub's disclosure ruling never saw — the front end reading ``outcome.reply``
    aloud is exactly the failure milestone 19's exit test is written to catch, performed
    by the browser instead of by us".

    Read off all three shipped files, because a page can reach an API from markup as
    readily as from a script.
    """
    for name in ("app.js", "index.html", "app.css"):
        source = (
            _code(name)
            if name == "app.js"
            else _markup(name)
            if name.endswith("html")
            else _style(name)
        )
        assert api not in source, name


def test_an_answer_that_cannot_be_put_on_screen_is_not_rendered_as_one() -> None:
    """#1622, #2005 and #2006: every ``renderOutcome`` caller reaches it through the guard.

    ``renderOutcome`` reads the outcome's members from its first lines, so
    ``renderOutcome(undefined, …)`` is a ``TypeError`` at the call site. It is not
    uncaught, and where it landed is what made each entry's ending wrong in its own way.
    The two ask entries and the spoken one, since retired (ADR-0309 §5:4, ADR-0313
    §3:4), were awaited inside a ``try`` whose ``catch`` announced ``GATEWAY_GONE`` —
    "The gateway did not answer, so it may have stopped", with a restart and a fresh
    bootstrap value as the remedy — said of a gateway that answered and a turn that ran.
    ``answerConfirmation``'s throw left a consent token
    ``spent`` and never ``unresolved``, so every row of the park read "That park has been
    answered from this page" for an outcome nothing had read. ADR-0139 §4 reports an act
    as one of exactly three outcomes and never as either of the other two, and those are
    the two other ones: not known announced as known not to have landed, and not known
    announced as landed.

    **The render is the test, and that is the reading rounds 9 and 10 of PR #1612
    reached** one surface over: round 9 checked that the outcome was an object and round
    10 walked ``{}`` straight past it, because ``{}`` still throws on ``steps.length`` and
    any enumeration of members needs re-deriving every time the renderer reads a new one.
    So the guard runs the render and reports whether the answer reached the screen, and a
    shape check that has to know what renders is what it replaces.

    **And ``renderOutcome`` itself is not made tolerant**, which #1622 rules out in terms:
    rendering an answer-shaped nothing is the failure and the throw is not.
    """
    script = _code("app.js")
    functions = _functions(script)
    guard = functions["couldRenderOutcome"]

    # The render is inside the `try`, and the `catch` is what the callers read back.
    assert guard.index("try {") < guard.index("renderOutcome(outcome, provenance);")
    assert guard.index("renderOutcome(outcome, provenance);") < guard.index("catch (_) {")
    # It renders or it reports and never leaves half: what reached the screen before the
    # throw is not an answer, so it does not stay beside a line saying so.
    assert guard.index('clearNode(el("answer-body"));') < guard.index('show("answer", false);')
    assert guard.index('show("answer", false);') < guard.index("return false;")
    assert guard.index("return false;") < guard.index("return true;")
    # The renderer keeps reading the members unguarded — the throw is what the callers
    # answer for, and a renderer that tolerated a missing outcome would render nothing as
    # an answer instead.
    render = functions["renderOutcome"]
    assert "if (outcome.capture_degraded) {" in render
    for tolerated in ("if (!outcome", "outcome === null", "outcome === undefined", "asOutcome"):
        assert tolerated not in render, tolerated
    # The one entry left reaches the render through it, and nothing calls it directly —
    # #1622's "one check, shared". The Ask and push-to-talk entries retired (ADR-0309
    # §5:4, ADR-0313 §3:4). `answerConfirmation` passes a provenance (#1621), so its call
    # is matched on its opening rather than on the whole argument list.
    assert "!couldRenderOutcome(body.outcome, unaccounted ?" in functions["answerConfirmation"]
    # Two occurrences of the renderer's own name with brackets in the whole file — its
    # declaration and the guard's call. `couldRenderOutcome(` carries a capital ``R`` and
    # is not one of them, so a caller that went back to calling the renderer directly
    # would be a third and would be read here whichever entry did it.
    assert script.count("renderOutcome(") == 2


def test_the_page_renders_a_notification_in_the_open_page_and_by_no_other_means() -> None:
    """§9: "A notification is rendered inside the open page and by no other means.
    This ADR authorises no Notification API, no Push API, no service worker, and no
    operating-system notification."

    That is the owner's in-page ruling on #1230 recorded as a clause, and it is also
    what makes milestone 14 reachable: every one of those capabilities needs a secure
    context, and ADR-0174 §7 makes a secure-context requirement a stop condition on
    this lane.
    """
    script = _code("app.js")
    document = _asset("index.html")

    assert "renderNotification" in script
    assert "notification-list" in document
    for capability in ("new Notification", "serviceWorker", "PushManager", "requestPermission"):
        assert capability not in script, capability


def test_a_notifications_text_is_neutralised_exactly_as_a_reply_is() -> None:
    """§9: "A notification's content is engine-supplied text and is neutralised
    exactly as a reply is" — inserted through the document's own text node, never as
    markup and never through any interface that parses markup."""
    script = _code("app.js")

    assert "summary.textContent = value.summary;" in script
    assert "detail.textContent = value.detail;" in script


def test_the_page_never_holds_or_sends_a_delivery_id() -> None:
    """§5: "A ``delivery_id`` never reaches a browser… and no browser request carries
    one. No browser acknowledges, retires, withdraws or dismisses a delivery."

    ADR-0131 §4 makes it a capability held by exactly one device, and ADR-0172 §1
    closes the class of such values a browser holds at three — so a page that named
    one would be the fourth kind that section says takes its own ratified decision.

    **``dismiss`` used to be checked over the whole file and now is not, and the
    narrowing is ADR-0177 §10 arriving rather than the claim weakening.** While no
    record-dismissal existed, "the page never says dismiss" was a sound proxy for
    "the page dismisses no delivery". The review surface dismisses a *record*, and §10
    says in terms that this is "not a route by which" a ``delivery_id`` could reach a
    browser — so what is checked now is the thing itself: the stream's reader and its
    renderer name neither verb and neither path, and no ``delivery_id`` is anywhere.
    """
    script = _code("app.js")
    functions = _functions(script)

    for named in ("delivery_id", "acknowledg"):
        assert named not in script, named
    for named in ("dismiss", "forget", "/notification"):
        assert named not in functions["watchDeliveries"], named
        assert named not in functions["renderNotification"], named


def test_the_page_says_whether_it_is_watching_rather_than_retrying_unseen() -> None:
    """§4 has the gateway poll "only when a browser establishes a delivery stream
    afresh", so re-establishing one is the browser's act — and ADR-0168 §9's rule
    against silent retrying is what keeps that a visible control rather than a timer.

    A page that spun against an unreachable hub would be the same failure wearing the
    front end's clothes.
    """
    script = _code("app.js")
    document = _asset("index.html")

    assert "watch-button" in document
    assert "delivery-state" in document
    # No repeating clock at all, and the one `setTimeout` in the file opens nothing:
    # it ends a stream that has stopped saying anything (#1442) and hands the control
    # back. A timer that *retried* would be ADR-0168 §9's failure in the page's
    # clothes; a timer that stops waiting on a socket nothing is coming out of is the
    # opposite — it is what makes the visible control reachable again.
    assert "setInterval" not in script
    calls = _page_clocks(script)
    assert len(calls) == 1
    for opener in ("fetch(", "watchDeliveries(", "rearm(", "readDeliveries("):
        assert opener not in calls[0], opener


def test_the_delivery_stream_is_re_armed_on_two_events_and_on_no_timer() -> None:
    """#1429's rule, stated as an extension of ADR-0168 §9: re-arming the delivery
    stream on foreground or on network return is permitted **when it is announced in
    the page**, never silently.

    ADR-0175 §4 is why it costs nothing — an abandoned delivery stream costs the
    browser "a reconnect — which is free, because a session outlives its connections".
    §4's last clause is also what makes it necessary: a backgrounded phone has its
    stream abandoned the moment a write to it does not complete, and the panel went on
    reading "Watching for notifications" until the owner noticed.

    The timers stay out. A page that spun against an unreachable hub would be ADR-0168
    §9's failure wearing the front end's clothes, and that is a different thing from
    reconnecting once, on an event the owner caused, and saying so.
    """
    script = _code("app.js")

    assert 'document.addEventListener("visibilitychange"' in script
    assert 'window.addEventListener("online", () => rearm(NETWORK_BACK));' in script
    assert 'document.visibilityState === "visible"' in script
    # The timers stay out of the re-arm, which is the clause rather than the proxy.
    # ADR-0182 §7 forbids re-establishing "on a timer, on a schedule, or on the failure
    # itself", so what is pinned is where a re-arm can come from: the two events, and
    # the one reason `watchDeliveries` held while a stream was still pending. The
    # page's own clock (#1442) is not among them and calls nothing that opens a stream.
    assert "setInterval" not in script
    assert sorted(re.findall(r"(?<![\w.])(?<!function )rearm\(\w+\)", script)) == [
        "rearm(CAME_BACK)",
        "rearm(NETWORK_BACK)",
        "rearm(held)",
    ]
    assert "rearm(" not in _page_clocks(script)[0]


def test_a_delivery_stream_that_stops_saying_anything_is_abandoned_on_a_bound() -> None:
    """Issue #1442. ``fetch`` has no deadline of its own, so a socket that died without
    settling left ``watching`` true for ever — the panel read "Watching for
    notifications", ``deliveryState`` kept ``#watch-button`` hidden because that is what
    ``watching`` means, and ADR-0182 §7's announced re-arm could not fire either,
    because §7 re-establishes a stream "only while it holds none".

    **The bound is on silence and it comes from the gateway's own obligation.**
    ADR-0175 §4 has the gateway write on every open delivery stream "at least once per
    ``gateway_notification_budget``" — a delivery where its poll returned one, "and
    otherwise a value carrying nothing but its own kind" — spent so that "the liveness
    of the gateway, of its hub connection and of the browser's own socket" is
    "observable at a bounded cadence". Silence past a multiple of that is the thing the
    keep-alive exists to expose, observed at the end it was written for.

    **The figure comes off the stream's own head**, so the deadline is armed before the
    first value is read and covers the silence that begins the moment the head lands.
    """
    script = _code("app.js")
    read = _functions(script)["readDeliveries"]
    watch = _functions(script)["watchDeliveries"]
    calls = _page_clocks(script)

    assert len(calls) == 1
    # Derived from what this gateway stated, and from no figure of this page's own: a
    # literal here would be a second claim about the cadence, which is ADR-0175 §8's own
    # argument against a separate heartbeat interval.
    # The deadline is the instant `SILENT_CADENCES` cadences from now, and the timer's
    # own delay is a segment of the wait to it — never a figure of this page's own.
    assert "arm(performance.now() + cadence * SILENT_CADENCES);" in read
    assert calls[0].rstrip().endswith("Math.min(at - performance.now(), TIMER_SEGMENT)")
    # No arm carries an inline figure. The claim about *this* bound is the line above —
    # it is the cadence the gateway stated and nothing else — and #1474's head bound is
    # a page figure on purpose, which is why it is a named constant with its argument
    # attached rather than a number sitting in a call.
    assert not re.search(r"arm\(performance\.now\(\) \+ [\d.]", read)
    assert "const SILENT_CADENCES = 3;" in script
    # Read off the head of the stream it bounds, and armed before a value is read.
    assert "cadence = usableCadence(response.headers.get(KEEP_ALIVE_HEADER));" in read
    assert read.index("cadence = usableCadence(") < read.index("heard();")
    assert read.index("heard();") < read.index("for await (const value of streamValues(")
    # A cadence this page has none of arms nothing, rather than a figure it made up.
    assert "if (cadence !== null) {" in read
    # Restarted by every value that arrives — keep-alive included — so what it measures
    # is silence and never the stream's life.
    assert "signal: reader.signal," in read
    delivered = read[read.index("for await (const value of streamValues(response)) {") :]
    assert delivered.index("heard();") < delivered.index('if (value.kind === "notification")')
    assert "watching" in watch


def test_a_stream_abandoned_for_silence_says_so_and_hands_the_control_back() -> None:
    """ADR-0182 §7's announcement rule reaching the ending this page reached on its own.

    §7 conditions the page's own motion on the owner being able to see it, and an
    ending nobody caused is the one most in need of words: the gateway named no
    condition, because the whole condition is that nothing arrived. ``deliveryState``
    un-hides ``#watch-button`` whenever ``watching`` is false, so the sentence and the
    way back arrive in one line.

    **It is not "the gateway did not answer".** An abort this page asked for is its own
    condition — the gateway may be perfectly alive at the other end of a socket that
    stopped carrying — and reporting it as a gateway that had gone would be a wrong
    explanation rather than a missing one, which is ADR-0168 §9's distinction lost at
    the last hop.
    """
    script = _code("app.js")
    read = _functions(script)["readDeliveries"]

    assert "stopWatching(WENT_SILENT);" in read
    assert 'fault(DELIVERY_STREAM_SILENT, "notifications");' in read
    assert 'el("watch-button").hidden = watching;' in _functions(script)["deliveryState"]
    # The sentence is built from the multiple, so the number in it cannot drift from the
    # number the deadline is armed with — and it says where the figure came from, which
    # is the stream that was abandoned rather than any earlier one.
    assert "${SILENT_CADENCES} times the keep-alive cadence this gateway stated when it" in script
    # A third ending and not a re-wording of the second: a body that ended is the
    # connection going away, and a body still open and silent is not. (One stream since
    # ADR-0293 §11, so the cut has one sentence.)
    assert "stopped saying anything" in script
    assert script.count("ended before the gateway finished it") == 1
    assert read.index("if (silent) {") < read.index("fault(GATEWAY_GONE,")


def test_the_cadence_is_read_off_the_streams_own_head_and_kept_nowhere() -> None:
    """The figure is gateway configuration (ADR-0175 §8) and nothing the page read
    carried it, which is why #1442 could not be fixed in the page alone.

    **A response header, so nothing has to be remembered between streams.** The head is
    the part of a streamed response that exists before its body does — ``fetch``
    settles with the headers in hand and not one value read — so every stream is
    bounded by what *its own* gateway stated, from before its first value. A page that
    kept the last figure instead would hold a gateway reconfigured from a short budget
    to a long one to the short one it no longer serves, abandon every attempt before it
    could learn better, and have no way out that ADR-0182 §7 permits.

    **It is not a session value and is in no ``localStorage`` key at all.** It admits
    nothing
    and is spendable against nothing, so ADR-0172 §1's closed class of three values a
    browser holds is untouched — and the keys the page does store are the session's
    header half and the chat's two, none of which this touches.

    **The exchange carries nothing of it either**, which is ADR-0168 §5: the bootstrap
    exchange "returns nothing but the two session values §6 requires".
    """
    script = _code("app.js")
    functions = _functions(script)

    assert 'const KEEP_ALIVE_HEADER = "X-Assistant-Keep-Alive-Microseconds";' in script
    assert "response.headers.get(KEEP_ALIVE_HEADER)" in functions["readDeliveries"]
    # Nothing about the cadence is stored, so there is no stale figure to be held to:
    # the roster of what this page keeps is pinned whole rather than by absence.
    assert sorted(re.findall(r"(?:local|session)Storage\.\w+\((\w+)", script)) == [
        "CHAT_CONVERSATION_KEY",
        "CHAT_CONVERSATION_KEY",
        "CHAT_CONVERSATION_KEY",
        "CHAT_OPEN_KEY",
        "CHAT_OPEN_KEY",
        "STORAGE_KEY",
        "STORAGE_KEY",
        "STORAGE_KEY",
    ]
    # A figure no deadline can be derived from is `null` rather than a guess.
    assert 'typeof microseconds === "string"' in functions["usableCadence"]
    assert "Number.isFinite(value) && value > 0" in functions["usableCadence"]


def test_a_deadline_longer_than_the_browsers_timer_is_armed_in_segments() -> None:
    """Adversarial review, act one, rounds 1 and 3 — the second correcting the first.

    ``setTimeout`` carries its delay in a signed 32-bit count of milliseconds and
    **clamps** anything larger to fire immediately, so a long cadence armed in one call
    aborts a healthy stream at once: worse than the failure being bounded.
    ``gateway_notification_budget`` is validated as strictly positive and against nothing
    else (ADR-0175 §8, which says in terms that "no load-time check relates it to
    ``hub_max_notification_budget``"), so a budget above about 8.3 days reached that
    ceiling once the multiple was applied.

    Round 1 refused such a figure and left the stream unbounded. Round 3 was right that
    this re-opens #1442 for exactly the configurations it is hardest to notice on, so the
    deadline is now held as the **instant** it falls due and armed in segments. The rule
    is then exact at every figure a gateway may hold: three times the cadence it stated,
    and nothing else.

    **The segments open nothing** (ADR-0182 §7). A segment that finds the instant still
    ahead arms the next one; the last one ends the stream. Nothing here re-establishes
    one, which the timer check above pins over the whole file.
    """
    script = _code("app.js")
    read = _functions(script)["readDeliveries"]
    usable = _functions(script)["usableCadence"]

    assert "const TIMER_SEGMENT = 2147483647;" in script
    # Against an absolute instant, so segments cannot drift the deadline outward.
    assert "arm(performance.now() + cadence * SILENT_CADENCES);" in read
    assert "Math.min(at - performance.now(), TIMER_SEGMENT)" in read
    assert "if (performance.now() < at) {" in read
    assert read.index("if (performance.now() < at) {") < read.index("silent = true;")
    # Monotonic, so a wall-clock step backwards cannot extend the wait.
    assert "Date.now()" not in read
    # And no figure is refused for being large: only one with no instant to compute.
    assert "TIMER_SEGMENT" not in usable
    assert "Number.isFinite(value) && value > 0" in usable


def test_a_head_that_states_no_usable_cadence_leaves_the_stream_unbounded() -> None:
    """Adversarial review, act one, round 2 — and the shape survives the move to a head.

    An earlier draft fell back to a figure from somewhere else where the stated one was
    unusable. What that does is hold a gateway *entitled* to a thirty-day budget, and
    stating it honestly, to the twenty seconds a differently configured process served.
    So an unusable header leaves the stream unbounded, exactly as every stream was
    before the deadline existed: a gateway that says it may be silent for a month is
    believed rather than second-guessed against a figure it never uttered, and one that
    says nothing this page can time has said nothing at all.

    ``Headers.get`` answers ``null`` for a header that was not sent, which
    ``usableCadence`` refuses along with ``""``, ``"0"`` and anything unparseable — the
    guard is on the value and not on the header's presence.
    """
    script = _code("app.js")
    read = _functions(script)["readDeliveries"]
    usable = _functions(script)["usableCadence"]

    # One source for the figure, and no second one to fall back to: the declaration and
    # the single assignment off this stream's head, and nothing else writes to it.
    #
    # The trailing space is what makes this a count of *writes*: ``cadence ===`` is a
    # comparison, and #1474's abort handler reads the field to tell "never opened" from
    # "went quiet". Counting it as an assignment would have this test fail on a change
    # that writes nothing, which is the assertion drifting off its own claim.
    assert read.count("cadence = ") == 2
    assert "cadence = usableCadence(response.headers.get(KEEP_ALIVE_HEADER));" in read
    assert "let cadence = null;" in read
    # `null` is a figure it refuses rather than one it inspects for presence.
    assert usable.rstrip().endswith(": null;\n}")
    assert 'typeof microseconds === "string"' in usable


def test_a_delivery_request_that_never_produced_a_head_is_abandoned_too() -> None:
    """Issue #1474, the residual #1473 stated rather than left to be discovered.

    The cadence deadline is armed off the stream's own head, so a ``fetch`` black-holed
    before a single byte comes back has nothing to arm it from — and that request hung
    for ever: ``watching`` stayed true, ``deliveryState`` kept ``#watch-button`` hidden
    because that is what ``watching`` means, and ADR-0182 §7's announced re-arm could not
    fire, because §7 re-establishes a stream "only while it holds none".

    **The issue states the case as a browser's *first* stream at an origin, and that
    premise does not hold at ``origin/main``.** It rests on the figure being remembered
    per origin, which
    ``test_the_cadence_is_read_off_the_streams_own_head_and_kept_nowhere`` pins as
    emphatically not the design: nothing about the cadence is stored, and ``cadence`` is
    a local of ``readDeliveries``. So every head-less stream is the case — including the
    re-arm a backgrounded phone makes on ``visibilitychange`` into a network that is
    still gone, which is the failure ADR-0182 §7 exists for.

    **The bound is the page's own, and that is not a lapse from the rule above it.**
    ``usableCadence``'s rule — believe the figure the gateway stated, substitute nothing
    — governs a figure the gateway uttered. ADR-0175 §4's write obligation is over "every
    **open** delivery stream", so a request with no head is one the gateway has said
    nothing about at all, and there is no figure to be held to. Deriving one from an
    earlier stream would be that substitution, and would leave a browser's first stream
    unbounded regardless.
    """
    script = _code("app.js")
    read = _functions(script)["readDeliveries"]

    # A named constant carrying its own argument, in the unit its name states.
    assert "const HEAD_DEADLINE_MILLISECONDS = 30000;" in script
    # Armed before the request goes out, so it covers the whole interval a `fetch` can
    # hang in — including a connection that is never made at all.
    assert "arm(performance.now() + HEAD_DEADLINE_MILLISECONDS);" in read
    assert read.index("arm(performance.now() + HEAD_DEADLINE_MILLISECONDS);") < read.index(
        'await fetch("/deliveries"'
    )
    # And spent the moment the head lands, whatever it says: before the refusal path
    # reads a body, and before an unusable cadence would leave it standing.
    after = read[read.index('await fetch("/deliveries"') :]
    assert after.index("hush();") < after.index("if (!response.ok) {")
    hush = read[read.index("const hush = () => {") :]
    assert hush[: hush.index("};")].count("window.clearTimeout(deadline);") == 1
    # The ending is the abort this page already had, so nothing new reaches the socket.
    assert "reader.abort();" in read
    # It opens nothing. ADR-0182 §7 forbids re-establishing "on a timer", and the timer
    # roster above pins that over the whole file; this is the same claim for the one
    # call site #1474 adds.
    assert "watchDeliveries" not in read


def test_a_stream_that_never_opened_is_not_reported_as_one_that_went_quiet() -> None:
    """Issue #1474's second half. ``WENT_SILENT`` says nothing arrived "for
    ``SILENT_CADENCES`` times the keep-alive cadence this gateway stated when it opened
    the stream", and a gateway that never sent a head stated no cadence and opened no
    stream this page saw — so reporting the new ending in that sentence would be a wrong
    explanation rather than a missing one, which is the distinction ``readDeliveries``'
    own ``catch`` was written to keep (ADR-0168 §9 at the last hop).

    Three endings the page can reach on its own, then: a stream that never opened, one
    that opened and went quiet, and a connection that failed. Each says which it was and
    each hands ``#watch-button`` back, because ``deliveryState`` un-hides it whenever
    ``watching`` is false.
    """
    script = _code("app.js")
    read = _functions(script)["readDeliveries"]

    assert "stopWatching(NO_HEAD);" in read
    assert 'fault(DELIVERY_STREAM_STALLED, "notifications");' in read
    # Ordered ahead of the silence branch, because a head that never arrived leaves no
    # cadence and would otherwise fall through to a sentence about one.
    assert read.index("if (stalled) {") < read.index("if (silent) {")
    assert read.index("if (silent) {") < read.index("fault(GATEWAY_GONE,")
    # Which branch is taken is read off `cadence` itself rather than off a second flag
    # set somewhere it could be set wrongly: it is null exactly while no head has landed.
    assert "if (cadence === null) {" in read
    assert read.index("if (cadence === null) {") < read.index("stalled = true;")
    assert read.index("stalled = true;") < read.index("silent = true;")
    # The sentence is built from the figure, so it cannot drift from the deadline — the
    # device ``WENT_SILENT`` already uses for the other bound.
    assert "${HEAD_DEADLINE_MILLISECONDS / 1000} seconds" in script
    # And it is its own wording rather than a second reader of an existing one.
    assert "head of the stream — so this browser abandoned it" in script
    # Four since #2008, and the fourth is the delivery stream's misframed-line ending —
    # its own sentence for the reason the three above are three, and carrying the same
    # way back because the condition is the same: the hub is polled only while a browser
    # is watching, so nothing it holds was taken while nothing here was listening.
    #
    # **Five since #2455**, and the fifth is the one ending that is not a fault at all:
    # a stream opened under a session this browser no longer holds, whose ending belongs
    # to that session and not to this one. It carries the same way back because the
    # control is the way back from every ending — what it does not carry is the outbox
    # sentence, because nothing here stopped watching on the hub's account.
    assert script.count("Start watching again.") == 5
    # And it is stated where a legitimate ending is stated (ADR-0182 §6): the line beside
    # the control, never the fault slot the four above write into.
    assert "fault(OUTLIVED_ITS_SESSION" not in script


def test_the_page_holds_a_stream_from_the_request_and_not_from_its_first_value() -> None:
    """The reading of ADR-0182 §7's third clause that #1474 asks a taker for, pinned
    where a change of mind would have to pass it.

    §7 permits a re-establishment "only while it holds none — one the gateway ended with
    ADR-0175 §4's terminal value, or one whose connection failed", so a ``fetch`` still
    pending has reached neither of the two endings §7 admits and is not "none". The
    clause's own ground says the same: it exists because §4 writes each delivery "to
    **every** delivery stream open at the moment it returned" and because each stream
    "holds a connection against ``gateway_max_browser_connections``" — both counted at
    the *gateway*. A page whose head was black-holed on the way back cannot tell whether
    the gateway opened a stream for it, so a page that read "holds" as "has read a value
    from" would open a second while the gateway held two, defeating the clause precisely
    where nothing can observe it.

    #1474 floats that redefinition as the clean closure and it is refused. What #1474's
    failure actually needs is a bound on how long the holding may last with nothing
    arriving, which §7's third clause says nothing about: it is a rule about concurrency,
    not about duration.
    """
    script = _code("app.js")
    watch = _functions(script)["watchDeliveries"]
    rearm = _functions(script)["rearm"]

    # Held from before the request, not from its first value.
    assert watch.index("watching = true;") < watch.index("await readDeliveries(half, era);")
    # And the two gates that spend it are the same fact, so nothing opens a second.
    assert "if (half === null || watching) {" in watch
    assert "if (watching) {" in rearm
    # `watching` goes false in exactly one place, and it is the one that hands the
    # control back — so a stream cannot be released without the owner being told.
    assert len(re.findall(r"(?<!let )watching = false;", script)) == 1
    assert "watching = false;" in _functions(script)["stopWatching"]
    assert 'el("watch-button").hidden = watching;' in _functions(script)["deliveryState"]


def test_a_session_that_ended_ends_the_delivery_stream_and_not_only_its_line() -> None:
    """#1542, and it is ADR-0182 §7's third clause rather than tidiness.

    §7 has the page hold "at most one delivery stream at a time" and re-establish one
    "only while it holds none — one the gateway ended with ADR-0175 §4's terminal value,
    or one whose connection failed". ``sessionLost`` performs §6's re-entry, and before
    this it changed the page's record and the line beside the button and left the
    request open: the owner pasted a fresh value, ``showConsole`` called
    ``watchDeliveries``, and a **second** stream opened beside a first the gateway was
    still writing to.

    The cost is counted at the gateway, which is why it cannot be waited out: ADR-0175
    §4 writes each delivery "to **every** delivery stream open at the moment it
    returned", forbids the gateway to de-duplicate, and gives each stream one of
    ``gateway_max_browser_connections``. And the ``409`` limb does not close itself —
    ``cookie-half-mismatch`` is answered for a session that is still **live**, so §7's
    fourth clause ends nothing and the duplicate runs for that session's whole life.
    """
    functions = _functions(_code("app.js"))
    lost = functions["sessionLost"]
    release = functions["releaseStream"]
    read = functions["readDeliveries"]

    # The request, not just the record of it: the controller is reachable from outside
    # the function that made it.
    assert "const open = { reader, released: false };" in read
    assert "streaming = open;" in read
    assert read.index("streaming = open;") < read.index("await fetch(")
    assert "open.reader.abort();" in release
    # Ended before the line that describes it, and by the one condition that means the
    # session is gone.
    assert lost.index("releaseStream();") < lost.index("stopWatching();")
    assert lost.index("releaseStream();") < lost.index("showBootstrap(")
    assert (
        'if (body.fault === "no-live-session" || body.fault === "cookie-half-mismatch") {' in lost
    )
    # And it ends a stream and opens none, which is the clause §7 turns on: a release
    # that re-established one would be the page taking motion §7 gives to two events.
    for opening in ("watchDeliveries", "fetch(", "setTimeout", "rearm("):
        assert opening not in release, opening


def test_a_stream_the_page_released_is_not_reported_as_the_gateway_having_gone() -> None:
    """The third ending ``readDeliveries``' catch has to tell apart, added by #1542.

    Two were already there and are kept apart from each other for a stated reason: a
    stream that went quiet broke a cadence the gateway stated, and one that never had a
    head broke nothing the gateway ever said. A stream this page *released* broke
    nothing either, and it is not the gateway having gone — ``sessionLost`` has already
    said what happened, in the surface ADR-0182 §6 rules it must be said in ("presented
    as re-entry rather than as a fault. It is not rendered in the page's fault
    surface").

    A ``GATEWAY_GONE`` written here would be a wrong explanation for an ending the page
    performed, and it would land in a panel ``showBootstrap`` has just hidden.
    """
    read = _functions(_code("app.js"))["readDeliveries"]
    caught = read[read.index("} catch (error) {") :]

    assert caught.index("if (open.released) {") < caught.index("if (stalled) {")
    assert caught.index("if (open.released) {") < caught.index("fault(GATEWAY_GONE,")
    assert caught.index("if (open.released) {") < caught.index("stopWatching(")
    # The registration is given up by whichever of the two ends first, and never by the
    # other one's ending: a `finally` that cleared it unconditionally would drop the
    # record of whatever stream opened next.
    assert "if (streaming === open) {" in read


def test_the_page_holds_one_record_of_the_stream_and_releases_it_in_one_place() -> None:
    """``streaming`` is the request and ``watching`` is what the page says about it, and
    #1542 is what happens when the second is changed without the first.

    So the record is written in exactly the two places that can be true of it — taken
    where the stream opens, given up where it ends — and released from exactly one, the
    one condition under which the page's record and the request can disagree.
    """
    script = _code("app.js")
    functions = _functions(script)

    assert len(re.findall(r"(?<!let )streaming = open;", script)) == 1
    assert len(re.findall(r"(?<!let )streaming = null;", script)) == 2
    assert {name for name, body in functions.items() if "streaming" in body} == {
        "releaseStream",
        "readDeliveries",
    }
    assert {name for name, body in functions.items() if "releaseStream();" in body} == {
        "sessionLost"
    }
    # `watching` is still moved by `stopWatching` alone, so releasing a stream cannot
    # leave the page saying it is watching one.
    assert "watching" not in functions["releaseStream"]


def test_a_re_arm_happens_only_where_there_is_a_session_and_no_open_stream() -> None:
    """The guard is the whole of what keeps a tab switch from costing anything: a
    healthy page re-arms nothing, and a page with no session half re-arms nothing
    either, because there is nothing for the gateway to admit.

    ``watching`` is this page's own record of whether a stream is open, and a socket
    that has died without the ``fetch`` settling still reads as open — so a re-arm
    there does nothing, and forcing a second stream to find out would hold two of one
    browser's ``gateway_max_browser_connections`` for one delivery slot.
    """
    rearm = _functions(_code("app.js"))["rearm"]

    assert "if (headerHalf() === null) {" in rearm
    # No session half is nothing to re-arm and nothing to remember either: the request
    # is held only where there is a stream that will settle and report.
    assert rearm.index("return;") < rearm.index("asked = because;")
    assert rearm.index("asked = because;") < rearm.index("watchDeliveries(")


def test_a_re_arm_says_that_it_happened_why_and_what_it_does_not_promise() -> None:
    """ "Announced in the page" is the condition on which re-arming is permitted at all,
    so the sentence is not decoration.

    The last clause is the one that has to be right rather than reassuring: the gateway
    holds a poll only while a stream is open, so nothing was taken out of the hub's
    durable outbox while this page was not watching (ADR-0175 §4) — but a delivery
    returned in the moment the last stream ended "is written nowhere" and is not
    replayed, and a page promising otherwise would be promising what the gateway
    declines to guarantee.
    """
    script = _code("app.js")
    rearm = _functions(script)["rearm"]

    assert "came back to the foreground with nothing listening" in script
    assert "network came back with nothing listening" in script
    assert "announced here rather than done quietly" in script
    assert "it is polled only while a browser is watching" in script
    assert "is not repeated" in script
    assert "NOTHING_REPLAYED" in rearm
    # The announcement is written where the panel already says whether it is watching,
    # and it is written before anything can arrive on the re-armed stream.
    assert "`Watching for notifications. ${because}`" in _functions(script)["watchDeliveries"]


def test_a_stream_that_opens_clears_what_ended_the_last_one() -> None:
    """Every act on this page clears its own panel before it runs, and watching is an
    act like any other.

    Without it a re-arm that succeeded sits under a standing "the gateway did not
    answer", which is the page contradicting itself on one screen — the failure this
    lane exists to stop, rather than something to leave to a dismiss control. Found by
    driving the page; no check over the source would have asked.
    """
    watch = _functions(_code("app.js"))["watchDeliveries"]

    assert 'fault(null, "notifications");' in watch
    assert watch.index("watching = true;") < watch.index('fault(null, "notifications");')
    assert watch.index('fault(null, "notifications");') < watch.index("deliveryState(")


def test_an_event_arriving_while_the_last_stream_is_pending_is_not_thrown_away() -> None:
    """The phone's own ordering, and the one round 1 caught.

    A backgrounded page has its stream abandoned by the gateway (ADR-0175 §4's last
    clause) and the rejection lands whenever the browser next runs it — which can be
    *after* the owner has brought the page back. ``watching`` still reads true at that
    moment, so a re-arm that simply returned would leave the owner pressing the button
    after all: the failure this section exists to end, one ordering over.

    **One request, not a queue.** It holds the reason to announce, is consumed once,
    and nothing but a fresh foreground or network event sets it again — so a re-armed
    stream that fails at once re-arms nothing. That is what separates honouring an
    event the owner caused from retrying on a timer.
    """
    functions = _functions(_code("app.js"))
    rearm, watch = functions["rearm"], functions["watchDeliveries"]

    assert "asked = because;" in rearm
    assert rearm.index("headerHalf() === null") < rearm.index("if (watching) {")
    # Spent after the ending has been reported, which is why it is not in
    # `stopWatching`: from there it would announce the new stream and then write the
    # old one's condition over the top of it.
    assert "} finally {" in watch
    assert "const held = asked;" in watch
    assert "asked = null;" in watch
    assert watch.index("asked = null;") < watch.index("rearm(held);")


def test_the_page_re_issues_no_operation_of_its_own_motion() -> None:
    """ADR-0182 §7's fifth clause: "The page re-issues **no other request** of its own
    motion. Every request that asks the assistant for something — each of ADR-0177
    §6's operations — is re-issued only on an act by the owner."

    An automatic re-issue can duplicate a turn, which is why the permission §7 grants
    is for the delivery stream and for nothing else. ADR-0182 is not merged at the time
    of writing; §10 names this among the negatives the page lane can actually pin, and
    it is pinned where it would live — in what runs after a request failed.
    """
    blocks = _catch_blocks(_code("app.js"))

    assert blocks
    for block in blocks:
        for reissue in ("fetch(", "relay(", "act(", "watchDeliveries("):
            assert reissue not in block, block


def test_the_page_says_why_a_session_ended_while_it_was_only_watching() -> None:
    """ADR-0175 §7: an open stream is **not** use of the session that admitted it.
    ``gateway_session_idle_timeout`` "is refreshed by a request the gateway admits and
    by nothing else — not by a stream's continued existence, not by a value the gateway
    writes on one, and not by a delivery poll", and a stream ends no later than the
    session that admitted it.

    So a page left open and watching, asked nothing, expires exactly on time and the
    stream ends under it — and the bare vocabulary entry for ``no-live-session`` reads,
    to the owner of that page, as though something went wrong.

    The sentence is on the **delivery** ending, the one stream this page reads since
    ADR-0293 §11 retired the answer stream.

    **And it names all three of a session's endings rather than the idle one** (#2498).
    §7's fourth clause ends a stream for any ending of the session under it, and the
    gateway names them with one condition because one is true of all of them. A sentence
    that said the hour had passed would be false of a session that reached
    ``gateway_session_ttl`` with a request made minutes ago, and of one ADR-0168 §4 ended
    with the gateway process — so all three are named, which adversarial review's round 1
    found this saying only the first of.
    """
    script = _code("app.js")

    assert "Watching does not keep a session alive" in script
    for bound in ("gateway_session_idle_timeout", "gateway_session_ttl", "the gateway process"):
        assert bound in script, bound
    assert 'value.fault === "no-live-session"' in _functions(script)["describeDeliveryEnd"]
    assert "describeDeliveryEnd" in _functions(script)["readDeliveries"]


def test_the_page_says_that_a_session_ends_with_the_gateway() -> None:
    """ADR-0168 §4: a session is "minted at the gateway, held in memory, and dies with
    the process".

    The page meets that condition as a ``fetch`` that rejected, which says only that
    the gateway did not answer — so what the owner needs is the sentence for the
    surprise rather than a restatement of the mechanism: nothing is wrong with the
    browser, nothing is recoverable, and the way back is a fresh bootstrap value.
    """
    script = _code("app.js")

    assert "Every session ends with the gateway" in script
    assert "written down nowhere" in script
    assert "has no memory of this one" in script
    assert "Start the gateway, then start a session with the value it prints." in script


def test_the_page_reaches_what_the_gateway_serves_and_nothing_beyond_it() -> None:
    """ADR-0177 §1's enumeration, at the only other place a path could be written down.

    A path here that the gateway does not serve would be a front end asking for a
    later lane's surface and getting ADR-0168 §6's residual fourth class — and the
    two halves ship in one distribution (ADR-0168 §10), so the disagreement would be
    shipped rather than discovered.

    The negative half is what is **not** here: ``learn`` is admitted by nothing
    (§1, §11). ``/resume`` and ``/pending_confirmations`` stay in that half for a
    different reason now that the CONFIRM pair is served — a shape is a method and a
    path together (ADR-0168 §6), and the pair's paths are ``/confirmation/resume`` and
    ``/confirmations``, so a page reaching for the operation names would get §6's
    residual fourth class.
    """
    script = _code("app.js")

    for served in (
        '"/conversations"',
        '"/conversation"',
        '"/conversation/forget"',
        '"/sources"',
        '"/grant"',
        '"/revoke"',
        '"/grants/recent"',
        '"/grants/standing"',
        '"/beliefs"',
        '"/belief"',
        '"/belief/forget"',
        '"/questions"',
        '"/questions/interrupted"',
        '"/question/answer"',
        '"/question/forget"',
        '"/notifications"',
        '"/notification/dismiss"',
        '"/notification/forget"',
        '"/notification/preferences"',
        '"/notification/preferences/set"',
        '"/connection/connect"',
        '"/connection/reprovision"',
        '"/connection/disconnect"',
        '"/connections"',
        '"/connections/recent"',
        '"/confirmations"',
        '"/confirmation/resume"',
    ):
        assert served in script, served
    for later in ('"/learn"', '"/resume"', '"/pending_confirmations"'):
        assert later not in script, later
    # ADR-0285 §6 removed the route, and a page still reaching for it would get the
    # residual fourth class the paragraph above describes.
    assert '"/observe"' not in script


def test_the_page_offers_every_use_a_new_grant_may_name_and_no_other() -> None:
    """ADR-0139 §3's second clause, restated at the browser by ADR-0177 §6, as
    ADR-0294 §4 narrows the offer.

    "Wherever a surface offers, enumerates or explains the uses a user may choose
    among, it carries **every** member of ``GrantScope``, named in words" — a user
    cannot choose what they are not shown. ADR-0294 §4 then rules that "a surface
    offering the uses for a new grant, including an amendment's new scope, offers
    ``FACET`` and ``NOTIFY`` and not ``INGEST``", so the offer is
    :data:`~ai_assistant.wire.GRANTABLE_SCOPES` and the page may hold no box for the
    member the hub refuses.

    Read off the shipped file against ``core``'s own vocabulary, so a fourth member
    added to the enum fails here rather than reaching a user as a silently absent
    option or as an unlabelled grant.

    **Counted inside each declaration and not across the file**, which is issue
    #1332's lesson: a whole-file count of ``label:`` was satisfied by one vocabulary
    only while it was the only one the page carried.
    """
    script = _code("app.js")
    phrases = _declaration(script, "USE_PHRASES")

    # Every member is named in words, ``INGEST`` included: a recorded grant naming it
    # still renders it (ADR-0294 §4, ADR-0139 §3's third clause).
    for use in GrantScope:
        assert f'value: "{use.value}"' in phrases, use.value
    assert phrases.count("label:") == len(GrantScope)

    # The offer is that vocabulary less exactly the uses a new grant may not name.
    retired = re.search(r"^const RETIRED_USES = \[(.*)\];$", script, re.MULTILINE)
    assert retired is not None
    named = set(re.findall(r'"(\w+)"', retired.group(1)))
    assert named == {use.value for use in GrantScope} - {use.value for use in GRANTABLE_SCOPES}
    assert "const USES = USE_PHRASES.filter((use) => !RETIRED_USES.includes(use.value));" in script
    # And the choice is built from the offer, never from the rendering vocabulary.
    choice = _functions(script)["offerScope"]
    assert "USES.map" in choice
    assert "USE_PHRASES" not in choice


def test_the_page_never_renders_the_uses_a_grant_leaves_out() -> None:
    """ADR-0177 §6's third clause, at the level of the widget it names.

    "A rendering of an existing grant does not display the members the grant leaves
    out, in any form — greyed, disabled, unchecked, struck through, or otherwise
    present-but-negated", because "a control that shows all three states beside a
    grant naming one is that presentation made out of a layout".

    So the rendering path takes the grant's own ``scope`` and maps it, and there is
    no styling for a negated member to wear.
    """
    script = _code("app.js")
    rendering = _functions(script)["renderSource"]

    # The grant branch maps the grant's own scope and reaches `USES` — the choice
    # vocabulary — nowhere. `offerScope` is the *choice* context, which is the other
    # half of ADR-0139 §3 and where the uses a new grant may name belong.
    assert "usePhrase(source.live.scope)" in rendering
    assert "USES" not in rendering
    # `renderGrantFields` is where a live grant's uses are put on screen, and
    # `renderStanding` and the routed account's grant rows both go through it
    # (ADR-0197 §12) — so the clause is checked once, where it can be broken once.
    assert "usePhrase(grant.scope)" in _functions(script)["renderGrantFields"]
    # And no strike-through exists for a member to wear. The stronger half of the
    # claim is the one above — a member the grant does not name is never put in the
    # document at all, so there is nothing for a style to negate — but a rendering
    # that struck one through would be the clause's own worked example, so the
    # stylesheet is checked for it too.
    assert "line-through" not in _asset("app.css")


def test_the_page_keeps_the_two_grant_questions_apart() -> None:
    """ADR-0139 §1 and §3's fourth clause, which a page is more exposed to than a
    terminal is (ADR-0177 §6).

    "No view presents a source's configuration state as part of a grant, and no view
    presents a grant as a statement about whether a source is being read." A command
    line answers one question per invocation; a page shows several at once, and the
    obvious information architecture is the forbidden one.

    Two panels, two reads, two headings — and the sources panel says in the document
    that it is not answering the other question.
    """
    script = _code("app.js")
    document = _asset("index.html")

    assert '"/sources"' in script
    assert '"/grants/standing"' in script
    assert 'id="sources"' in document
    assert 'id="standing"' in document
    assert "It does not say whether anything is being read." in " ".join(document.split())


def test_the_page_says_the_state_is_unread_rather_than_inferring_it() -> None:
    """ADR-0177 §7's seventh clause and ADR-0139 §4's third.

    "No surface infers the source's current grant state from either act's outcome, at
    any point in the flow. In particular a refused ``grant`` is not a statement that
    the source is ungranted, and a landed revocation is not one either."

    So every act reports itself and then says what it did **not** establish, and the
    state that follows comes from a ``standing_grants`` read or is called unread.
    """
    script = _code("app.js")

    assert "Nothing above says what this source is granted for now." in script
    for after in ("grantSource", "revokeSource", "amendSource"):
        assert after in script, after
    # Every act path says it, and every act path then *reads* rather than infers.
    assert script.count("line(panel, STATE_UNREAD") == 4
    assert script.count("await listStanding()") == 4


def test_the_page_reads_a_conversation_before_it_forgets_one() -> None:
    """ADR-0073 §5's show-then-confirm, at the unit the user thinks in: "what will be
    destroyed is shown before consent is taken, in a form a human can judge".

    §6 is explicit that the confirmation "is not a control and is not required here" —
    the origin-resident script the residual is about defeats one — so this is a
    rendering decision made for the owner's benefit, on the CLI's own order.
    """
    script = _code("app.js")

    assert 'relay(half, "/conversation", { conversation_id: id }, "conversations")' in script
    assert "recorded_turns" in script
    assert "window.confirm(" in script


#: Every top-level function that calls ``fetch``, and the entry point each is reached
#: from. A `fetch` rejects where the gateway process has stopped, and the entry point
#: is where that is caught — `relay` is reached from both conversation entries — so the
#: guard is asserted there rather than at the call.
_FETCH_SITES: Final = {
    "startSession": "startSession",
    "readDeliveries": "readDeliveries",
    # The change stream (ADR-0298 §7), its own `fetch` for `readDeliveries`' reason: a
    # stream is read value by value, which `relay` does not do.
    "followChat": "followChat",
    "relay": "listConversations",
}

#: The one ``fetch`` site that deliberately does **not** report a rejection as the
#: gateway having gone (ADR-0177 §7's fourth clause). A rejected `fetch` on a
#: mutating act is an outcome that is **not known** — the request was sent and no
#: response was read, and the gateway may already have called — so reporting it as
#: "the gateway did not answer" would assert the one thing ADR-0139 §4 spends five
#: clauses refusing to let a surface assert.
_ACT_SITE: Final = "act"

#: The ``relay`` entry point that refuses the same report for the same reason, and it
#: is the *only* other one. A park's answer is a mutating act that additionally spends
#: a consent token: a rejected `fetch` there may have left the hub having run the
#: action, so "the gateway did not answer" is a claim this page has not read — and
#: releasing the token on it would let a second ``resume`` go out on a continuation the
#: first resolved, which ADR-0084 §7 makes emphatically not a denial and the gateway
#: nonetheless relays as ``assistant-declined``. Enumerated beside :data:`_ACT_SITE`
#: rather than dropped from the check, so the exception stays one a reader can count.
_UNKNOWN_ON_REJECTION: Final = "answerConfirmation"

#: Every entry point reaching ``relay``, each of which catches a rejected `fetch`
#: itself. Enumerated rather than counted, for the reason issue #1332 records: a
#: threshold satisfied by five of six guards leaves the sixth deletable in silence.
#: ``answerConfirmation`` is deliberately absent: :data:`_UNKNOWN_ON_REJECTION`.
_RELAY_ENTRIES: Final = (
    "forgetConversation",
    "listSources",
    "listStanding",
    "listGrantHistory",
    "readBeliefs",
    "forgetBelief",
    "readQuestions",
    "answerQuestion",
    "forgetQuestion",
    "readNotifications",
    "dismissNotification",
    "forgetNotification",
    "listTuning",
    "writePreferences",
    "listConnections",
    "listConnectionLog",
    "readPending",
)


#: Every panel a fault can be written into (#1429). Enumerated rather than derived
#: from the script, for the reason issue #1332 records one file over: a check that read
#: the panels out of the same expression it is checking would pass whatever that
#: expression became, including a page that had quietly gone back to one slot.
_FAULT_PANELS: Final = frozenset(
    {
        "bootstrap",
        "conversations",
        "confirmations",
        "notifications",
        "acts",
        "sources",
        "standing",
        "history",
        "beliefs",
        "questions",
        "goals",
        "review",
        "tuning",
        "connections",
        "connection-log",
        "authorizations",
        "chat",
    }
)

#: The five ``fault`` calls that do **not** name a panel with a literal, which are the
#: machinery's own: the two that clear the page-foot slot, the two that clear a built
#: one — its dismiss control, and the sweep a session start or end makes over all of
#: them — and `report`, which is handed the panel its caller named.
#:
#: There is no run-time choice of panel here any more. A condition that ended the
#: session used to be sent to the bootstrap panel's fault slot by a ternary in this
#: position; ADR-0182 §6 makes it re-entry instead — "not rendered in the page's fault
#: surface" — so it leaves `report` before `fault` is reached at all.
_UNNAMED_FAULTS: Final = (
    "message, panelId",
    "null",
    "null",
    "null, panelId",
    "null, panelId",
)

#: A guard reporting the gateway having gone, into the panel whose act raised it
#: (#1429). The panel is part of what is pinned: a guard that reported it to the page
#: foot would be legible here and illegible on a page of thirteen panels, which is the
#: whole of what that change was for.
_GATEWAY_GONE: Final = re.compile(r'fault\(GATEWAY_GONE, "[a-z-]+"\)')


def _functions(script: str) -> dict[str, str]:
    """Every top-level function in the script, by name, each to the next declaration.

    They are all declared at column zero and nothing else in this file is, so the
    next declaration is where one ends — enough to ask what a *particular* function
    does, which counting occurrences across the whole file cannot.
    """
    opened = list(re.finditer(r"^(?:async )?function\*? (\w+)\(", script, re.MULTILINE))
    return {
        one.group(1): script[
            one.start() : (opened[index + 1].start() if index + 1 < len(opened) else len(script))
        ]
        for index, one in enumerate(opened)
    }


def _fault_calls(script: str) -> list[str]:
    """The argument text of every ``fault(...)`` call, brackets matched.

    Matched rather than pattern-counted because the argument is sometimes a call and
    sometimes two concatenated strings across three lines, and a regular expression
    that read either would read a truncated one of the other.
    """
    calls = []
    for opened in re.finditer(r"(?<![\w.])fault\(", script):
        if script[: opened.start()].endswith("function "):
            continue
        depth, index = 0, opened.end() - 1
        while index < len(script):
            depth += {"(": 1, ")": -1}.get(script[index], 0)
            if depth == 0:
                break
            index += 1
        calls.append(" ".join(script[opened.end() : index].split()))
    return calls


def _catch_blocks(script: str) -> list[str]:
    """The body of every ``catch`` in the script, brace-matched.

    What a page does *after* a request failed is the whole of ADR-0182 §7's fifth
    clause, and it is the one place an automatic re-issue would sit.
    """
    blocks = []
    for opened in re.finditer(r"catch \(\w+\) \{", script):
        depth, index = 0, opened.end() - 1
        while index < len(script):
            depth += {"{": 1, "}": -1}.get(script[index], 0)
            if depth == 0:
                break
            index += 1
        blocks.append(script[opened.end() : index])
    return blocks


def _constant(script: str, name: str) -> str:
    """One top-level ``const NAME = ...;`` as its source text.

    Asked for by name so that a sentence is checked where it is *declared*, which
    searching the whole file cannot: a phrase counted anywhere would be satisfied by any
    of the thirty other messages this page carries.
    """
    opened = script.index(f"\nconst {name} =")
    return script[opened : script.index(";\n", opened)]


def _timeouts(script: str) -> list[str]:
    """The argument text of every ``setTimeout`` call, brackets matched.

    ``_fault_calls``' device for the same reason: the arguments span a callback body
    and an arithmetic expression across several lines, and a regular expression that
    read either would read a truncated one of the other. What the checks below ask of
    it is what the one clock in the page *does* and what its delay is *derived from* —
    neither of which counting occurrences can answer.
    """
    calls = []
    for opened in re.finditer(r"\bsetTimeout\(", script):
        depth, index = 0, opened.end() - 1
        while index < len(script):
            depth += {"(": 1, ")": -1}.get(script[index], 0)
            if depth == 0:
                break
            index += 1
        calls.append(script[opened.end() : index])
    return calls


def _page_clocks(script: str) -> list[str]:
    """The page's clocks **other than the chat's**, which a test of its own pins.

    The chat follows the change stream (ADR-0296 §4, ADR-0298 §7), and ``followChat``
    bounds that stream exactly as ``readDeliveries`` bounds the delivery stream: a
    deadline on the head and one on silence, opening nothing. Every claim below about
    "the one clock" is about the delivery stream's and the owner's waits, and stays
    exactly as strict: the chat's clock is taken out by where it is declared, and
    nowhere else may a second one appear.
    """
    follow = _functions(script)["followChat"]
    return [call for call in _timeouts(script) if call not in follow]


def _declaration(script: str, name: str) -> str:
    """One top-level ``const NAME = [...]`` declaration, from its name to its close.

    Enough to ask what *that* vocabulary carries, which counting occurrences across
    the whole file cannot once the page carries two.
    """
    opened = script.index(f"const {name} = [")
    return script[opened : script.index("\n];", opened)]


def test_every_fetch_the_page_makes_is_guarded() -> None:
    """A rejected ``fetch`` is the gateway having stopped, which is its own condition
    (ADR-0168 §9) and not silence.

    The bootstrap site is issue #1332's, and the count that used to stand here did not
    pin it: six mentions of ``GATEWAY_GONE`` falling to five still satisfied
    ``>= 5``, so deleting that guard outright left this test green. The enumeration
    is what makes the claim now — a `fetch` in a function not named below fails the
    first assertion, and an entry point that stopped catching fails the second.
    """
    script = _code("app.js")
    functions = _functions(script)

    assert script.count("await fetch(") == script.count("fetch(")
    assert {name for name, body in functions.items() if "fetch(" in body} == set(_FETCH_SITES) | {
        _ACT_SITE
    }
    for called, entry in _FETCH_SITES.items():
        guard = functions[entry]
        assert "} catch (" in guard, called
        assert _GATEWAY_GONE.search(guard), called
    # Every other entry point reaching `relay` is its own, and catches for itself.
    for entry in _RELAY_ENTRIES:
        assert _GATEWAY_GONE.search(functions[entry]), entry
    # And the two that refuse that report do refuse it, rather than having quietly lost
    # a guard: each still catches, and each answers with an outcome that is not known.
    for entry in (_ACT_SITE, _UNKNOWN_ON_REJECTION):
        assert "} catch (" in functions[entry], entry
        assert not _GATEWAY_GONE.search(functions[entry]), entry


def test_a_lost_request_on_a_grant_act_is_reported_as_an_unknown_outcome() -> None:
    """ADR-0177 §7's fourth clause, which is this surface's own addition to
    ADR-0139 §4's three outcomes.

    "A failure of the **browser's own** request to the gateway — the request was sent
    and no response was read — is an outcome that is **not known**, whatever the
    gateway did. It is a third producer of ADR-0139 §4's third outcome that no earlier
    surface had, and no front end resolves it by assuming either of the other two."

    `interfaces/cli.py` holds the socket to the hub itself and has two cases;
    between this page and the store sit its own request, the gateway, and the
    gateway's wire connection.
    """
    functions = _functions(_code("app.js"))
    acting = functions[_ACT_SITE]

    assert "} catch (" in acting
    assert "GATEWAY_GONE" not in acting
    assert "outcome: UNKNOWN" in acting


def test_an_act_reads_its_outcome_from_the_gateways_own_distinction() -> None:
    """ADR-0177 §7's third clause: which of the three an act gets is read from
    ADR-0168 §9's distinction "and from nothing else".

    "A request the hub received and declined is **known not to have landed**; a
    transport failure between the gateway and the hub is **not known**." The gateway
    already writes those two as separate conditions, and this is what that
    distinction is for.
    """
    script = _code("app.js")

    assert 'UNKNOWN_FAULTS = new Set(["hub-unreachable"])' in script
    assert "!named || UNKNOWN_FAULTS.has(body.fault) ? UNKNOWN : NOT_LANDED" in script


def test_a_refusal_this_page_cannot_classify_is_an_unknown_outcome() -> None:
    """The gap between "read a fault" and "read the *right* fault".

    A response cut after its headers leaves ``readBody`` with nothing, so no condition
    is named — and the status may be the ``502`` the gateway writes for a hub it could
    not reach, which ADR-0177 §7's third clause makes **not known**. Treating a missing
    ``fault`` as "not one of the unknown conditions" would report exactly that as known
    not to have landed, which is the assertion ADR-0139 §4 exists to prevent.

    The success branch is deliberately *not* symmetric, and the asymmetry is a fact
    about the gateway rather than a convenience: it writes a success status only after
    the promoted call has returned, so a ``200`` cannot precede the hub's answer. What
    an unreadable body costs there is the detail beside the outcome, and reporting a
    landed act as unknown is forbidden by the same clause that forbids the reverse.
    """
    acting = _functions(_code("app.js"))[_ACT_SITE]

    assert 'const named = typeof body.fault === "string";' in acting
    assert acting.index("if (response.ok)") < acting.index("const named")
    assert "outcome: LANDED" in acting


def test_a_body_that_is_not_an_object_reaches_no_caller_as_one() -> None:
    """``null`` is a valid JSON document, so a reader that returned it would hand
    every caller a value that throws on the first member read.

    On a grant act that throw escapes as "the gateway did not answer" — which is not
    one of the three outcomes ADR-0139 §4 requires an act to be reported as, and is a
    fourth answer arriving by way of an exception. So an unreadable condition arrives
    as an **unnamed** one, which :func:`act` already classifies as not known.

    It is the gateway's own ``_payload`` rule read from this side: a body that is not
    an object is not distinguished from an absent one, because every caller reads
    named members and a second failure mode would be a second way to say the same
    thing.

    The shape rule is its own function so that the two readers can disagree about a
    body that could not be read *at all* while agreeing about this — round 8's blocker,
    pinned in :func:`test_a_body_never_read_is_not_a_response_whatever_the_status_said`.
    """
    functions = _functions(_code("app.js"))
    shape = functions["asObject"]

    assert "parsed !== null" in shape
    assert 'typeof parsed === "object"' in shape
    assert "!Array.isArray(parsed)" in shape
    # And both readers go through it, so the shape rule has one statement. Its own
    # declaration counts as a mention: ``_functions`` attributes it to itself.
    assert {name for name, body in functions.items() if "asObject(" in body} == {
        "asObject",
        "readBody",
        "relay",
    }
    # A refusal's body is still read as far as it can be read, because a refusal that
    # carries no readable condition is one the *caller* classifies (``act``'s rule).
    assert "catch (_) {\n    return {};\n  }" in functions["readBody"]


def test_a_body_never_read_is_not_a_response_whatever_the_status_said() -> None:
    """Round 8's blocker, and ADR-0177 §7's fourth clause on the one path that reached it.

    ``fetch`` settles when the **head** lands, so a body is still arriving when ``relay``
    resumes — and the owner's **Stop waiting** aborts a request whose status has already
    been read. Routing that through ``readBody`` swallowed the abort and returned ``{}``
    for a ``200``, so a park's answer ran straight past its unknown-outcome branch into
    ``renderOutcome(undefined, …)``: an uncaught ``TypeError``, a token left ``spent``
    and never ``unresolved``, and a row reading "That park has been answered from this
    page" for an outcome nothing had read. §7's fourth clause is explicit that "the
    request was sent and no response was read" is an outcome that is **not known**
    "whatever the gateway did", and ADR-0139 §4 forbids the surface resolving it.

    So the rejection is kept on the ``2xx`` path and ``readBody``'s swallow is left to
    the refusal path it was written for. Every caller already runs ``relay`` inside a
    ``try``, and each ``catch`` is the ending it wants: ``GATEWAY_GONE`` for a read, and
    for a park's answer the branch that keeps the continuation.

    The asymmetry is the gateway's own: every ``2xx`` is written through
    ``_json_response``, so a ``2xx`` body that will not parse is a transport truth —
    where a *refusal*'s condition really can be replaced by a proxy.
    """
    script = _code("app.js")
    functions = _functions(script)
    relaying = functions["relay"]

    # The ok path parses for itself and lets the rejection out.
    assert "return asObject(await response.json());" in relaying
    # ``readBody`` is reached only after the ok path has returned, so no swallow can
    # stand between an unread body and a caller's catch.
    assert relaying.index("if (response.ok) {") < relaying.index("await readBody(response)")
    assert relaying.count("readBody(") == 1
    # And the one caller whose catch turns on a consent token is reached by that
    # rejection: it is inside the ``try``, and the branch it takes strands the park —
    # recording that its answer went unread and giving the token back for it (#1621).
    answering = functions["answerConfirmation"]
    assert answering.index("await relay(") < answering.index("} catch (_) {")
    assert answering.index("} catch (_) {") < answering.index("strand(token);")


def test_an_amendment_is_two_requests_and_sends_no_grant_after_an_unresolved_one() -> None:
    """ADR-0177 §7's first and fifth clauses.

    Amending is composed **client-side**, "as ADR-0139 §4's two acts in order —
    ``revoke``, then ``grant`` — carried by two separate browser requests resolving to
    two separate engine calls", and "where the revocation's outcome is not known, the
    front end does **not** send the grant".

    The decision about the new scope is taken before the revocation is sent (§7's
    sixth clause): the scope arrives as an argument, so no path through this function
    can revoke in order to ask.
    """
    amending = _functions(_code("app.js"))["amendSource"]

    assert 'act(half, "/revoke", { source: source.source })' in amending
    assert 'act(half, "/grant", { source: source.source, scope })' in amending
    assert amending.index('"/revoke"') < amending.index('"/grant"')
    assert "if (withdrawal.outcome !== LANDED)" in amending
    assert "I sent no new grant." in amending


def test_the_page_reads_the_belief_again_immediately_before_it_forgets_one() -> None:
    """ADR-0177 §5's second clause, which is the browser-specific half of ADR-0073
    §5's ceremony.

    "The render that ceremony rests on is taken from a ``belief`` read issued
    immediately before the confirmation is offered, and never from an entry of a
    ``beliefs`` listing the page rendered earlier. A page holds its listing until it
    is navigated away from […] and a browser is the first surface where the
    difference is unbounded."

    The band-appropriate warning and the statement of what the consent covers are
    ADR-0073 §5's other two obligations, and they are in the same prompt.
    """
    forgetting = _functions(_code("app.js"))["forgetBelief"]

    assert 'relay(half, "/belief", { record_id: id }, "beliefs")' in forgetting
    assert forgetting.index('"/belief"') < forgetting.index("window.confirm(")
    assert forgetting.index("window.confirm(") < forgetting.index('"/belief/forget"')
    assert "forgetWarning(belief.band)" in forgetting
    assert "which may have changed since it was shown" in forgetting
    # Every field §4 requires, the validity window's end included where one is set. A
    # confirmation showing less than the listing the user came from is the opposite of
    # what a ceremony is for.
    for field in ("belief.band", "belief.kind", "belief.confidence", "belief.content"):
        assert field in forgetting, field
    assert "belief.valid_until === null" in forgetting
    assert "belief.last_updated" in forgetting
    assert "belief.id" in forgetting


def test_the_forget_warning_is_band_appropriate_and_total_over_the_bands() -> None:
    """ADR-0073 §5: the ceremony "is uniform in mechanism and asymmetric in message",
    and "the surface must not represent a deletion as more final than it is, nor as
    less final".

    Destroying an assertion is permanent; destroying a derived or attested belief
    removes the belief and not its origin. Read against ``core``'s own vocabulary, so
    a band added to the enum fails here rather than falling through to a wrong
    warning.
    """
    script = _code("app.js")
    warning = _functions(script)["forgetWarning"]

    for band in BeliefBand:
        # `DERIVED` is the fall-through branch and is named in the prose rather than
        # in a comparison, which is what makes the function total: a band added to
        # the enum lands there and gets a wrong warning, so it is named here too.
        assert f'"{band.value}"' in warning or band is BeliefBand.DERIVED, band.value
    assert "Forgetting it is permanent" in warning
    assert "destroys my copy but not the " in warning
    assert "destroys the belief but not what I worked it " in warning


def test_forgetting_a_question_sends_only_for_one_the_read_returned() -> None:
    """ADR-0177 §5's fifth clause.

    "The browser renders the question it is about to destroy, from a ``questions`` or
    ``interrupted_questions`` read issued immediately before the confirmation, and
    takes the user's answer before calling ``forget_question``. It sends
    ``forget_question`` only for a question that read returned."

    #495's third ground — that a ceremony needs a read the façade does not have — is
    met without adding one: the two list reads return the question whole.
    """
    forgetting = _functions(_code("app.js"))["forgetQuestion"]

    assert 'relay(half, path, { limit: PAGE, offset }, "questions")' in forgetting
    assert "body.questions.find((one) => one.id === id)" in forgetting
    assert "if (question === undefined)" in forgetting
    assert forgetting.index("window.confirm(") < forgetting.index('"/question/forget"')


def test_the_re_read_before_a_question_is_destroyed_asks_for_the_page_it_came_from() -> None:
    """The ceremony's re-read and the listing's paging have to agree.

    ADR-0177 §5's fifth clause has the browser send ``forget_question`` "only for a
    question that read returned" — so a re-read of the *first* page would report a
    question rendered from the second as gone, and the owner would be unable to
    destroy it at all. The offset each row was read at travels with the row.
    """
    functions = _functions(_code("app.js"))

    assert "renderQuestion(list, one, path, offset)" in functions["readQuestions"]
    assert "function renderQuestion(list, question, path, offset)" in functions["renderQuestion"]
    assert "forgetQuestion(question.id, path, offset)" in functions["renderQuestion"]


# --- ADR-0189 §9: the origin reaches the three browser render paths ---------
#
# **Read off the shipped script rather than executed, and the file says why it has
# to be.** This repository has no JavaScript runtime in its gate: every `app.js`
# check in this module asserts over the extracted function body, and adding a
# runtime would be a dependency decision well outside a surface lane's fence. So
# what is pinned here is that each path *builds* the output §4 obliges — the exact
# interpolations, the branch each arm takes, and the element structure that makes
# the attribution unforgeable — and the *rendered* output is recorded in the pull
# request from the page driven at both viewports, which is the observation §9 is
# ultimately about.


def test_the_browsers_attested_line_names_the_source_and_when_that_source_spoke() -> None:
    """ADR-0189 §9's first surface clause, on ``whyHeld``.

    Both halves, because ADR-0073 §4's gate is explicitly both and §9 names
    ``reported_at`` as "the one an implementing lane will drop, because the
    source-naming half is the one everybody is talking about".

    The sentence #1276 tracked is asserted **gone** as well. A negative is worth its
    line here for the reason the CLI's own pin records: nothing else in this module
    would notice the old wording returning under a reworded neighbour, and that wording
    now states a limit this projection does not have.
    """
    why = _functions(_code("app.js"))["whyHeld"]

    assert "${belief.attestation.reported_by}" in why, "the reporting source is named"
    assert "${belief.attestation.reported_at}" in why, "and the instant it spoke"
    assert "cannot show them here" not in why, "#1276's limitation is gone"


def test_the_browser_never_offers_its_own_clock_as_the_sources() -> None:
    """ADR-0073 §4's floor, which ADR-0189 §4 restates and the new line makes riskier.

    §4: a surface "renders ``reported_at`` as the **source's** clock and never as this
    system's, and it does not offer ``last_updated`` in its place". ADR-0189's
    Consequences names the newly-available error in as many words — "naming the source
    while still showing our clock as the source's" — so the two instants stay two, and
    the one this system owns stays labelled as ours.
    """
    functions = _functions(_code("app.js"))

    assert "on its own clock" in functions["whyHeld"], "the source's instant is the source's"
    assert "not when the source spoke" in functions["whyHeld"], "and ours is declared ours"
    assert "last_updated" not in functions["whyHeld"], "this line does not reach for our clock"
    assert "Last revised: ${belief.last_updated}" in functions["renderBeliefFields"], (
        "which is rendered on its own line, as its own fact"
    )


def test_the_browser_reads_the_source_as_a_source_and_never_as_a_person() -> None:
    """ADR-0189 §4's second clause, ADR-0098 §8's third adopted unchanged.

    A surface renders the source "at **source granularity and no finer**", and "a
    surface that rendered ``reported_by`` as though it named a person would assert what
    this system does not hold". ADR-0093 §7 forbids deriving a reader's identity from
    the source's location or contents, so the organiser of an invite and the sender of
    a mail are not on the record and cannot be.

    Pinned on the apposition, because that is the mechanism: there is no list of
    person-words to check a value against, and what makes it unreadable as a person is
    that this file introduces it as a connected source.
    """
    why = _functions(_code("app.js"))["whyHeld"]

    assert "A connected source reported it — ${belief.attestation.reported_by}" in why


def test_the_browser_says_a_derived_warrant_came_from_outside_on_every_count_state() -> None:
    """#1517's first finding, on ``whyHeld`` — and on all four of its count states.

    §9's own matrix has no arm for the derived clause, so a renderer could show
    ``reported_by`` and ``reported_at`` correctly everywhere, omit the marker for every
    ``DERIVED`` record with the predicate ``True``, and pass all eight required tests
    while breaching §4.

    **Appended once rather than per branch**, which is ADR-0107 §5's structural
    argument about the elision ceiling reaching a second clause: §4 binds this to the
    band and not to any of the four count states, so a per-branch append would be four
    chances to forget it. Asserted by counting the appends — one construction, four
    returns — because a marker missing from one branch is exactly what a
    presence-anywhere check would pass.
    """
    derived = _functions(_code("app.js"))["whyDerived"]

    assert "outsideWarrant(belief)" in derived
    assert derived.count("const outside =") == 1, "constructed once"
    returns = derived.split("return ")[1:]
    assert len(returns) == 4, "the four states a derived line renders a count in"
    assert all("outside" in one for one in returns), "and the clause reaches every one"


def test_the_browser_says_nothing_about_the_outside_when_the_predicate_is_false() -> None:
    """The silence is ruled, not an omission (ADR-0098 §5, ADR-0106 §1).

    A ``False`` is *nothing external is recorded in this warrant*, never *nothing
    external influenced it*: text whose recorded origin is not external can still have
    reached a belief, and no field on the record says so. A page printing the negative
    would assert what this system does not hold.

    And the answer is **read**, never recomputed: ADR-0189 §2 forbids a surface
    deriving it from ``band``, and ADR-0106 §2 gives the reason — the hand-rolled
    version "is short enough that every consumer will write it and one of them will
    write only the second half".
    """
    functions = _functions(_code("app.js"))
    outside = functions["outsideWarrant"]

    assert 'if (!belief.rests_on_recorded_external_content) {\n    return "";' in outside
    assert outside.index('return "";') < outside.index(_EPISODIC_GUARD), (
        "the silence is taken before the kind, so no arm can render a false as an "
        "assurance and a third arm could not either (ADR-0223 §5's last clause)"
    )
    assert "band" not in outside, "the answer is read, never recomputed from the band"
    assert "derived_from_external" not in _code("app.js"), (
        "and no client reads the raw field in the predicate's place (ADR-0106 §2)"
    )


def _row(*, kind: MemoryKind, stamped: bool) -> BeliefSummary:
    """One listing row, as either surface is handed it."""
    return BeliefSummary(
        id="rec-1",
        band=BeliefBand.DERIVED,
        kind=kind,
        content="you asked where the office is; I answered Boston",
        confidence=0.5,
        evidence_count=0,
        lost_evidence=0,
        last_updated=datetime(2026, 3, 2, 8, 30, tzinfo=UTC),
        rests_on_recorded_external_content=stamped,
    )


def test_the_browser_gives_a_stamped_episode_an_arm_of_its_own() -> None:
    """ADR-0223 §5's second clause, on the browser half of §10's eighth test.

    This page lists beliefs without a kind filter, so a captured episode is one of the
    rows it renders — and once ADR-0223 §1 stamps the mark on one, the predicate is
    true of a record the belief sentence is false of in every clause: nothing worked
    the episode out, there is nothing it was worked out *from* (ADR-0074 §4 leaves its
    evidence empty by decision), and its warrant is that it happened.

    Asserted in both directions and per arm, because the failure this pins is the
    belief sentence surviving on a row it is false of — which a check for the presence
    of the episodic sentence anywhere in the function would pass.
    """
    outside = _functions(_code("app.js"))["outsideWarrant"]
    episodic = _arm(outside, _EPISODIC_GUARD)

    assert "traces back to a connected source" in _joined(episodic)
    assert "I worked it out from" not in _joined(episodic), (
        "an episode was not worked out from anything (ADR-0223 §5's second condition)"
    )
    assert "warrant" not in _joined(episodic), "and it has no derivation to predicate"
    assert "my own account of what was said" in _joined(episodic), (
        "the content is not re-attributed to the source (§5's first condition)"
    )


def test_the_two_surfaces_say_the_same_two_sentences() -> None:
    """ADR-0223 §5's third clause: both surfaces render the arm, or neither does.

    "A fact stated on one surface and not on its sibling is a fact a user learns to
    distrust on both" — so this asserts the stronger thing the clause makes available:
    not merely that each surface says *something*, but that the browser's sentence is
    the terminal's sentence, character for character, on both arms.

    It is the one check that fails when a lane repairs one renderer and forgets the
    other, which is the failure mode §5 was written against and the one neither file's
    own tests can see.
    """
    outside = _functions(_code("app.js"))["outsideWarrant"]
    episodic = _arm(outside, _EPISODIC_GUARD)
    belief = outside[outside.index("\n  return (") :]

    assert _joined(episodic) == cli._outside_warrant(_row(kind=MemoryKind.EPISODIC, stamped=True))
    assert _joined(belief) == cli._outside_warrant(_row(kind=MemoryKind.SEMANTIC, stamped=True))


def test_the_browser_explains_an_episode_as_a_record_and_never_as_a_derivation() -> None:
    """#1891 on this surface: an episode's ``Why`` is that it happened (ADR-0075 §2).

    This page lists beliefs with no kind filter, so a captured turn is one of the rows
    it renders — and ``whyHeld`` used to hand it to ``whyDerived``, whose line is false
    of it in every clause: nothing worked it out, and there is nothing it was worked out
    *from* because ADR-0074 §4 leaves an episode's evidence empty by decision.

    Asserted over ``whyEpisodic``'s own body rather than over the file, because a
    sentence counted anywhere in the script would be satisfied by the terminal's copy
    of it landing in some other function.
    """
    functions = _functions(_code("app.js"))
    held = functions["whyHeld"]
    episodic = _joined(functions["whyEpisodic"])

    assert _EPISODIC_GUARD in held, "the kind is asked before the derived line is reached"
    assert held.index(_EPISODIC_GUARD) < held.index("return whyDerived(belief);")
    assert "This records an exchange that happened" in episodic
    assert "I worked it out" not in episodic
    assert "no supporting evidence was recorded" not in episodic


def test_the_browser_heads_an_episodes_row_with_a_filing_and_not_a_claim() -> None:
    """#1891's display question, answered where this surface makes it sharpest.

    ``bandWords`` renders a band as a first-person sentence — it is what the page shows
    and what its three filter checkboxes are labelled with. On an episode "I worked it
    out" is not a label but a claim, and a false one (ADR-0075 §2), asserted one line
    above a ``Why`` that denies it. So an episode's row leads with the band's own words
    quoted **as a filing**.

    Both halves are pinned. The band's words stay inside the phrase, because ADR-0073
    §4 requires the band conveyed — "never omitted, never implied by position alone" —
    and because the heading is how a user reads a row back to the box that selected it.
    The confidence is still rendered beside it, for the same section's other clause and
    ADR-0072 §6's; what the figure *means* for an episode is said in the ``Why`` line,
    where there is room to say it.

    And every other kind is left on the bare band, which is the arm the three kinds
    that really are beliefs take.
    """
    functions = _functions(_code("app.js"))
    heading = functions["beliefHeading"]
    fields = functions["renderBeliefFields"]

    assert "${beliefHeading(belief)} · ${belief.kind}" in fields
    assert "confidence ${belief.confidence.toFixed(2)}" in fields, "ADR-0073 §4's other clause"
    assert _EPISODIC_GUARD in heading
    assert "Filed under '${bandWords(belief.band)}'" in heading, (
        "the band's own words survive inside the phrase (ADR-0073 §4)"
    )
    assert heading.count("return bandWords(belief.band);") == 1, (
        "and every other kind leads with the band bare"
    )
    assert "a standing figure rather than a measure of doubt" in _joined(functions["whyEpisodic"])


def test_the_two_surfaces_explain_an_episode_in_the_same_words() -> None:
    """ADR-0223 §5's third clause held to over the head sentence too.

    "A fact stated on one surface and not on its sibling is a fact a user learns to
    distrust on both" — and the reason a captured turn is not a derivation is such a
    fact. So the browser's sentence is the terminal's, character for character, save
    the leading capital: this page capitalises every ``Why:`` line (its asserted arm
    reads "You told me…") and the terminal capitalises none of them (its reads "you
    told me…"), which is a convention that predates this lane on both files.

    Read with the mark **unset**, so the comparison is over the head sentence this lane
    wrote and not over ADR-0223 §5's sentence, which its own case already pins.
    """
    browser = _joined(_functions(_code("app.js"))["whyEpisodic"])
    terminal = cli._why_episodic(_row(kind=MemoryKind.EPISODIC, stamped=False))

    assert terminal[0].islower(), "the terminal's Why line continues its label"
    assert browser == terminal[0].upper() + terminal[1:]


def test_the_browser_renders_a_records_own_line_breaks_in_its_content() -> None:
    """#1890's other surface, verified rather than assumed.

    A captured episode's content is two lines — "The user asked: …" and "The
    assistant's plan: …" — and the terminal was replacing the break between them with
    ``\ufffd``. This page never had that fault, and the two facts that make it so are
    both in the shipped bytes, so they are pinned here rather than restated as a drive
    (ADR-0216 §2: "a property decidable by reading the shipped bytes is asserted in the
    text layer"). The content is inserted as ``textContent``, which carries a newline
    verbatim, into the one class whose rule keeps it — the same ``pre-wrap`` the
    composed answer needs, for the same reason.
    """
    functions = _functions(_code("app.js"))
    fields = functions["renderBeliefFields"]
    styles = _asset("app.css")

    assert 'line(item, belief.content, "reply");' in fields
    assert "p.textContent = text;" in functions["line"], "inserted as text, never as markup"
    assert ".reply {\n  white-space: pre-wrap;" in styles

    # And the terminal's hazard does not arrive here. A break kept in a line the
    # adapter authored forges a second one (ADR-0042 §4), which is why the CLI puts a
    # multi-line content behind a gutter. This page never shared the line: the content
    # is a paragraph of its own in a class the row's own fields do not use, and the
    # stylesheet gives that class its own size and colour — so a forged "Why:" inside
    # the content renders in the content's type, not in a field's.
    assert fields.count('"hint"') == 5, (
        "the band, the why, last-revised, the window's end and the id are the fields"
    )
    assert fields.count('"reply"') == 1, "and the content is the one line that is not a field"
    assert ".hint {\n  font-size: 0.85rem;\n  color: var(--muted);" in styles


def test_the_browser_leaves_an_unstamped_episode_exactly_where_it_was() -> None:
    """The byte-identity half of ADR-0223 §10's eighth test, on this surface.

    The predicate is read before the kind, so an episode nothing external reached
    renders what it rendered before this ADR — the pre-existing oddity of explaining an
    episode through a belief renderer included, which §5 names and deliberately does
    not repair.
    """
    outside = _functions(_code("app.js"))["outsideWarrant"]
    silence = outside[: outside.index(_EPISODIC_GUARD)]

    assert _joined(silence) == "", "the false arm contributes nothing at all"
    assert MemoryKind.EPISODIC.value not in silence, (
        "and it is reached without asking what kind the row is"
    )


def test_the_browser_names_the_source_that_reported_what_would_be_retired() -> None:
    """ADR-0189 §9's first surface clause, on ``renderRetirements``.

    The attested-and-resolved arm: both ``reported_by`` and ``reported_at`` reach the
    output. Read through ``warrant`` rather than off the retirement, which §4 spells in
    the clause itself because an earlier draft named the two facts bare and was not
    implementable as written — ``Retirement`` carries no ``band`` and no
    ``rests_on_recorded_external_content`` of its own. Adversarial review found it on
    ADR-0189's round 3.
    """
    origin = _functions(_code("app.js"))["retirementOrigin"]

    assert "${warrant.attestation.reported_by} reported this" in origin
    assert "${warrant.attestation.reported_at}" in origin
    assert "on that source's own clock" in origin


def test_the_browser_takes_all_three_of_the_retirement_arms_and_keys_them_on_the_band() -> None:
    """ADR-0189 §4's three retirement clauses, which #673 is closed by telling apart.

    Attested content **is** presented as third-party — ADR-0098 §7's first clause,
    satisfiable for the first time. Asserted content is the user's own word (ADR-0038
    §1a) and derived content is this system's own sentence, and §4 rules that no
    surface presents either as third-party.

    An earlier draft of ADR-0189 ruled the third-party presentation unconditionally, so
    a retirement of the user's own assertion would have rendered as somebody else's
    words; architecture review found it on round 3. The band inside the warrant is what
    tells the three apart, and this is the pin that keeps them apart.
    """
    origin = _functions(_code("app.js"))["retirementOrigin"]

    assert 'warrant.band === "attested"' in origin
    assert 'lead: "someone else\'s words —"' in origin
    assert 'warrant.band === "asserted"' in origin
    assert 'lead: "your own words —"' in origin
    assert 'lead: "my own inference —"' in origin
    assert origin.count("someone else's words") == 1, "the third-party lead is one arm's alone"


def test_the_browsers_unresolved_retirement_states_no_band_no_origin_and_no_source() -> None:
    """ADR-0189 §9's tombstone clause, over the browser half of the two retirement paths.

    §4: where the warrant is ``None`` the retired record no longer resolves —
    ``content`` is ``null`` too — "and the surface renders it as *no longer held* … and
    asserts nothing about its band, its origin or its source. It renders no third state
    as ``False`` and no absence as a value."

    **A second test rather than a clause of the first, because the state a single test
    would have named cannot exist**: §2 makes ``warrant`` and ``content`` ``null``
    together, so an unresolved retirement is in no band, carries no attestation, and
    there is no attested tombstone to construct. Adversarial review found it on
    ADR-0189's round 5.

    Asserted on the early return, which is the mechanism: the tombstone branch never
    reaches ``retirementOrigin`` at all, so no arm of it can leak a lead onto a record
    that resolves to nothing.
    """
    retirements = _functions(_code("app.js"))["renderRetirements"]

    assert "if (one.content === null) {" in retirements
    assert (
        "line(item, `${one.record_id} — no longer held, so accepting would not touch it`, "
        '"hint");' in " ".join(retirements.split())
    )
    tombstone = retirements[retirements.index("one.content === null") :]
    tombstone = tombstone[: tombstone.index("return;")]
    for named in ("warrant", "attestation", "band", "someone else", "connected source"):
        assert named not in tombstone, f"the tombstone arm asserts nothing, and {named} is one"


def test_a_retirements_own_syntax_cannot_move_the_attribution_of_any_browser_span() -> None:
    """ADR-0189 §9's marked rendering-security clause, for **this** target.

    §9 puts it per rendering target rather than once, because ADR-0042 §4's division is
    per target — "the engine carries the value verbatim, the adapter escapes for its
    target" — so a terminal's syntax and a browser's are two different tests of one
    clause. This is the browser's, and its two mechanisms are both structural rather
    than remembered:

    * **Every span is a text node.** ``line`` writes through ``textContent``, so a
      retirement's content reaches the page as characters and never as markup (ADR-0168
      §6). The module-wide sink check covers the file; this covers the path.
    * **A newline cannot forge a second span.** The lead this file wrote is written
      *before* the content within its element, and ``.hint`` and ``.notice`` declare no
      ``white-space: pre-wrap`` — unlike ``.reply`` and ``.notification-detail``, which
      do and say why. So a newline inside a content collapses to a space rather than
      opening a line under a marker this file authored, which is #1336's argument for
      ``_safe`` eating ``\\n`` reaching the same conclusion on the other target by a
      different mechanism.
    """
    retirements = _functions(_code("app.js"))["renderRetirements"]
    stylesheet = _style("app.css")

    assert "line(item, `${origin.lead} ${one.content} (${one.record_id})`" in retirements, (
        "the lead this file wrote precedes the content within the element"
    )
    for sink in _MARKUP_SINKS:
        assert sink not in retirements
    for shaped in (".reply", ".notification-detail"):
        assert "white-space: pre-wrap;" in _rule(stylesheet, shaped), (
            f"{shaped} is shaped, and says why"
        )
    for unshaped in (".hint", ".notice"):
        assert "white-space" not in _rule(stylesheet, unshaped), (
            f"{unshaped} carries a retirement's own words and collapses its newlines"
        )


def test_the_browser_renders_an_attested_questions_source_and_its_clock() -> None:
    """ADR-0189 §9's fifth surface clause, on ``renderQuestion``.

    §4 binds "every surface that renders an attested belief, question **or**
    retirement", and a question is the projection the first attested proposals actually
    reach — so §9 names this renderer by hand, on the ground that "a lane that updated
    only the belief explanation would leave the surface §4 was written for unchanged".

    The band line above it stays the conditional it was: nothing here says the proposal
    *is* held, because a pending question is not a belief of any band.
    """
    functions = _functions(_code("app.js"))
    # The fields are `renderQuestionFields`', which is what both the questions panel
    # and a routed `questions` or `forget_question` listing render through (ADR-0197
    # §12) — so §9's clause is checked where it holds for every surface at once.
    question, origin = functions["renderQuestionFields"], functions["proposalOrigin"]

    assert "const origin = proposalOrigin(question);" in question
    assert 'line(item, `Where it came from: ${origin}`, "hint");' in question
    assert "${question.attestation.reported_by}" in origin
    assert "${question.attestation.reported_at}" in origin
    assert "not held yet — I am asking first" in question, "and it is still a conditional"


def test_the_browsers_question_origin_never_answers_for_what_it_would_retire() -> None:
    """ADR-0189 §2's fourth clause, which is the one a renderer would run together.

    "On ``Question``, both fields describe the **proposal** … and describe no entry in
    ``retires``. Each entry in ``retires`` answers for itself through its own
    ``warrant``." The case that makes it concrete is #673's ordinary one: a user's own
    assertion, deferred by the policy, retiring an attested calendar line. One reads
    ``question.attestation``; the other reads ``warrant.attestation``; and neither
    function reaches for the other's value.
    """
    functions = _functions(_code("app.js"))

    assert "warrant" not in functions["proposalOrigin"], "the proposal's origin is its own"
    assert "question" not in functions["retirementOrigin"], "and the retirement's is its own"
    assert (
        'question.band === "derived" && question.rests_on_recorded_external_content'
        in (functions["proposalOrigin"])
    ), "#746's trap: the band alone would call a tainted consolidation purely our own"


def test_the_browser_keys_a_proposals_origin_on_the_band_and_never_on_an_attestation() -> None:
    """ADR-0072 §4: nothing acquires the standing of a band it is not in by decorating.

    ADR-0189 §2 adds no cross-field validator to ``Question``, so a question banded
    ``asserted`` carrying an attestation is model-valid, crosses this wire, and reaches
    this renderer. A page keyed on the attestation's **presence** would introduce the
    user's own word as a connected source's report — the laundering ADR-0072 §4 names
    one type over, where "an attestation on an ``INFERRED`` record would be the same
    laundering by a different field — a derived guess wearing a citation to a system
    that never reported it".

    The attested-with-no-attestation arm is checked in the same test because the two are
    one repair: asking the band first is what creates that arm, and leaving it
    unanswered would trade a lie for a silence on the one band whose whole purpose is
    provenance.
    """
    origin = _functions(_code("app.js"))["proposalOrigin"]

    assert origin.index('question.band === "attested"') < origin.index("question.attestation"), (
        "the band is asked first, so an attestation outside that band selects nothing"
    )
    assert "does not name that source or say when it spoke" in origin
    assert "not recorded" not in origin


def test_every_rendered_line_reaches_the_page_as_a_text_node() -> None:
    """The one builder all three of these paths write through (ADR-0168 §6).

    "The front end inserts every value the hub returned into the page as **text** and
    never as markup, and executes nothing derived from one" — and an origin marker
    beside a retirement's own words is exactly the pair that clause is about.

    The module-wide sink check reads the whole file, which answers "is there a markup
    sink anywhere"; this reads the builder, which answers "does a rendered line still
    reach the page as text". A ``line`` that stopped appending a text node would pass the
    first and fail here, rather than silently weakening every path that calls it.
    """
    builder = _functions(_code("app.js"))["line"]

    assert 'document.createElement("p")' in builder
    assert "p.textContent = text;" in builder
    assert "parent.appendChild(p);" in builder
    for sink in _MARKUP_SINKS:
        assert sink not in builder


def test_a_listing_offers_the_next_page_rather_than_stopping_at_a_full_one() -> None:
    """ADR-0073 §1 makes the belief read an **enumeration** so that what is past a page
    stays reachable, and a rendered row is the browser's only route to ``forget``.

    A listing that stopped silently at a full page would hide a belief the owner
    cannot then delete, which is the promise this milestone exists to keep. "Is there
    more" is answered by asking for the next page and never by a total nobody computed
    (ADR-0073 §2), so a full page is one whose length equals what was asked for — which
    is why the page states its own size instead of inheriting the surface's default.
    """
    script = _code("app.js")
    offering = _functions(script)["offerMore"]

    assert "const PAGE = 25;" in script
    assert "if (returned < PAGE)" in offering
    assert "That is a full page; there may be more." in offering
    for paged in ("readBeliefs", "readQuestions"):
        assert "offerMore(list, body." in _functions(script)[paged], paged
        assert "limit: PAGE" in _functions(script)[paged], paged


def test_an_offset_is_only_spent_against_the_question_that_produced_it() -> None:
    """An offset counted against one filter means nothing against another.

    Unchecking a band between two pages would otherwise skip the beliefs the narrower
    question puts first — and a belief with no rendered row has no ``Forget`` control,
    so the failure costs the owner a control rather than a little tidiness.

    Two mechanisms, because there are two ways to get there. A band change **starts
    the listing again**, which is what makes the offset meaningful; and a page still in
    flight when that happens is **retired**, so a stale answer neither appends rows the
    current filter did not ask for nor moves the offset the next page is read at.
    """
    script = _code("app.js")
    functions = _functions(script)

    assert 'el(box).addEventListener("change", listBeliefs);' in script
    assert "runs.beliefs += 1;" in functions["listBeliefs"]
    assert "run !== runs.beliefs" in functions["readBeliefs"]
    assert "run !== runs[listing.counter]" in functions["readQuestions"]


def test_one_generation_is_taken_for_a_whole_listing_and_carried_into_each_read() -> None:
    """The gap between "check the run" and "check the *right* run".

    ``listQuestions`` starts two listings, so it has two awaits — and a run retired
    during the first would otherwise reach the second and snapshot whatever number is
    current *then*. Two overlapping refreshes would both be accepted, both read offset
    zero, and both advance the same counter, putting the next page past a whole page of
    questions nobody can answer or destroy.

    So the generation is taken once, before any await, and travels into every read and
    into the "Show more" each read offers — never re-read from the shared counter
    inside a function that has already suspended.
    """
    functions = _functions(_code("app.js"))

    assert "generation[listing.counter] = runs[listing.counter];" in functions["listQuestions"]
    assert (
        "readQuestions(path, false, generation[QUESTION_LISTS[path].counter])"
        in functions["listQuestions"]
    )
    assert "async function readQuestions(path, more, run)" in functions["readQuestions"]
    assert "readQuestions(path, true, run)" in functions["readQuestions"]
    assert "readBeliefs(false, runs.beliefs)" in functions["listBeliefs"]
    assert "readBeliefs(true, run)" in functions["readBeliefs"]


# --- ADR-0177 §10: the notification review surface ---------------------------


def test_the_page_offers_every_reach_a_class_may_be_set_to_and_no_proper_subset() -> None:
    """ADR-0130 §6's three levels, wherever the page offers a choice among them.

    ``off`` is the member worth naming: §6 has it reach "every actionable held record
    of that class", so a control that could not send it would leave "never tell me
    this" unreachable from a browser — the same failure a two-of-three scope group
    would be on the grant surface.

    Read against ``core``'s own vocabulary, so a fourth level added to the enum fails
    here rather than reaching a user as a silently absent option.
    """
    vocabulary = _declaration(_code("app.js"), "REACHES")

    for reach in NotificationReach:
        assert f'value: "{reach.value}"' in vocabulary, reach.value
    assert vocabulary.count("label:") == len(NotificationReach)


def test_the_page_states_the_reach_a_class_takes_when_nothing_names_it() -> None:
    """ADR-0130 §6: a class absent from the preference "takes the default reach",
    which is ``hold`` for every class "including one no preference names".

    The tuning panel lists only what the user has set, so without this a reader would
    have no way to tell an unset class from one set to ``hold`` — and the difference
    is the whole of "why did nothing interrupt me?".
    """
    script = _code("app.js")

    assert f'const DEFAULT_REACH = "{DEFAULT_NOTIFICATION_REACH.value}";' in script
    assert "A class you have not set takes the default — ${" in script


def test_every_condition_a_ruling_names_is_rendered_in_words() -> None:
    """ADR-0130 §5 names each condition "so a ruling can be explained", which is what
    makes "why did you tell me that?" and "why didn't you?" answerable.

    Total over the vocabulary, against ``core``'s own: a ninth condition would
    otherwise reach a user as a bare wire value, and the conditions are exactly what
    a user would have to change.
    """
    vocabulary = _code("app.js")
    opened = vocabulary.index("const CONDITIONS = {")
    named = vocabulary[opened : vocabulary.index("\n};", opened)]

    for condition in NotificationCondition:
        assert f"{condition.value}:" in named, condition.value


def test_the_page_keeps_the_record_and_the_delivery_apart() -> None:
    """ADR-0177 §10's first and third clauses, at the level of the layout.

    The delivery list fills from the stream and the review list from
    ``notifications``; they are two elements in two panels, and neither verb of the
    review surface appears in the stream's reader or its renderer. ADR-0175 §10 named
    conflating them as the mistake the deferral existed to prevent, and a browser
    holding both is the first place they are on one screen.
    """
    script = _code("app.js")
    document = _asset("index.html")

    assert "notification-list" in document
    assert "review-list" in document
    assert 'el("review-list")' in _functions(script)["readNotifications"]
    assert 'el("notification-list")' in _functions(script)["renderNotification"]


def test_no_act_on_a_record_is_presented_as_touching_a_delivery() -> None:
    """§10's third clause: "No surface presents dismissing or forgetting a
    notification as affecting whether it was delivered, and none presents having
    received a delivery as affecting the record's disposition. They are two acts on
    two objects and the surface says so."

    Said rather than left to be inferred, in both places a person meets the pair: the
    panel that lists the records, and the confirmation shown before one is destroyed.
    """
    script = _code("app.js")
    document = _asset("index.html")

    assert "Neither is a statement about whether it ever reached a device." in document
    assert "Neither act says anything about whether it reached a device." in script


def test_a_write_of_the_settings_reads_them_first_and_renders_what_came_back() -> None:
    """ADR-0177 §10's fourth clause: the surface "sends the whole
    ``NotificationPreferences`` value it read, renders what the call **returned**
    rather than what it sent, and states no preference state it has not read back".

    A page that rendered its own optimistic view, or that assembled a value from a
    read taken some time ago, would silently revert a preference — the write replaces
    what is held rather than merging into it, and this surface carries no version
    token, so the last write wins.
    """
    write = _functions(_code("app.js"))["writePreferences"]

    assert 'relay(half, "/notification/preferences", {}, "tuning")' in write
    assert '"/notification/preferences/set"' in write
    assert "change(read.preferences)" in write
    assert "renderTuning(written.preferences)" in write


def test_every_edit_of_the_settings_carries_the_members_it_does_not_change() -> None:
    """The same clause from the other side, and the member that proves it.

    ``budget_window`` is on no control the page offers, so it exists only in what is
    read and written back — a mutator that built a fresh object instead of spreading
    the value it read would reset it on every save, and nothing on screen would say
    so. Each edit is checked for the spread rather than the page being checked for a
    control it deliberately does not have.
    """
    functions = _functions(_code("app.js"))

    for edit in ("withReach", "renderQuietWindows", "quietWindowForm", "renderBudget"):
        assert "...held," in functions[edit], edit
    assert "budget_window_microseconds" not in functions["withReach"]


def test_the_page_never_turns_a_setting_it_is_only_carrying_into_a_number() -> None:
    """The same clause where a JSON number stops being exact.

    ``interruption_budget`` is bounded at ``2**63`` and ``budget_window`` has
    microsecond resolution, so both are above what an IEEE-754 double holds — and both
    are members this page mostly just hands back. The gateway spells them as decimal
    strings for that reason, and a page that read one through ``Number`` would undo it
    at the first edit of something else.

    The budget's own field is checked as characters and sent as characters. The one
    ``Number`` in the whole surface builds the sentence that says how long the rolling
    window is, which is a rendering and never travels — asserted by name so that a
    second one cannot appear unnoticed.
    """
    functions = _functions(_code("app.js"))
    budget = functions["renderBudget"]

    assert "count.value = preferences.interruption_budget;" in budget
    assert "const asked = count.value.trim();" in budget
    assert "interruption_budget: asked" in budget
    assert budget.count("Number(") == 1
    assert "Number(preferences.budget_window_microseconds) / 3.6e9" in budget


def test_the_page_reads_the_notification_again_immediately_before_destroying_it() -> None:
    """A destructive act over a row the page has just seen, rather than one it last
    saw minutes ago.

    **This is not ADR-0073 §5's ceremony and the page does not claim it is.** That
    ceremony binds a belief; ADR-0177 §5 carries it to ``forget``,
    ``forget_question`` and ``forget_conversation`` and stops there, and a
    notification is not a belief of any band — which is the reason the command line
    offers none either. What is asserted here is the weaker, real thing: the record
    shown in the confirmation comes from a read issued immediately before it, the
    request is sent only for a record that read returned, and a record that has gone
    says so instead.
    """
    forget = _functions(_code("app.js"))["forgetNotification"]

    assert 'relay(half, "/notifications", { limit: PAGE, offset }, "review")' in forget
    assert "body.notifications.find((one) => one.id === id)" in forget
    assert 'fault(NOTIFICATION_GONE, "review")' in forget
    assert forget.index("window.confirm") < forget.index('"/notification/forget"')


# --- the connection surface (ADR-0177 §3, §4) --------------------------------


def test_no_credential_field_ships_in_the_document() -> None:
    """ADR-0177 §4: "The front end presents no credential field on a page whose own
    origin is not loopback".

    A field that shipped in `index.html` would be in the DOM of a page served over
    the overlay whatever hid it — reachable by a password manager, by an extension,
    and by the owner with the inspector open — so the guarantee is that the document
    carries exactly one password input and it is the bootstrap value's, which
    ADR-0168 §5 already governs and which is not a credential.
    """
    document = _markup("index.html")

    assert document.count('type="password"') == 1
    assert 'id="bootstrap-value"' in document
    assert "credential" not in document.lower()
    assert "password" not in document.lower().replace('type="password"', "")


def test_the_credential_field_is_built_only_on_a_loopback_origin() -> None:
    """§4's fourth clause: the front end "never presents one it knows the gateway will
    refuse".

    "The tidy design is one connection page that works everywhere and reports a
    failure if the gateway refuses — which asks the owner to type a Tier 0 secret into
    a non-secure page and *then* tells them it was pointless." So the origin is read
    by the page itself, the form is not offered off loopback, and the input element is
    created in exactly one function that only a loopback page can reach.
    """
    script = _code("app.js")
    functions = _functions(script)

    assert 'const ON_LOOPBACK = window.location.hostname === "127.0.0.1"' in script
    assert script.count('type = "password"') == 1
    assert 'type = "password"' in functions["askCredential"]
    assert "if (!ON_LOOPBACK) {" in functions["offerConnect"]
    assert functions["offerConnect"].index("if (!ON_LOOPBACK)") < functions["offerConnect"].index(
        "createElement"
    )
    assert "if (ON_LOOPBACK) {" in functions["offerConnectionActs"]


def test_the_connect_form_is_offered_only_after_the_gateway_answered_a_read() -> None:
    """§4's fourth clause again, for the deployment §3's second clause refuses: a
    gateway whose own hub is remote serves none of the five, and the listing is what
    says so. The form is torn down before the read and rebuilt only if it answered."""
    listing = _functions(_code("app.js"))["listConnections"]

    assert listing.index("clearNode(form)") < listing.index('relay(half, "/connections"')
    assert listing.index("if (held === null)") < listing.index("offerConnect(form)")


def test_the_identity_is_shown_and_confirmed_before_the_credential_is_asked_for() -> None:
    """§4's fifth clause: "The identity is rendered, and the user's confirmation of it
    taken, **before** the credential field is presented" — ADR-0149 §4's third answer
    to a credential pasted into the identity field is precisely that the value is
    *seen*, and a page rendering it afterwards shows it once the secret has already
    been typed into the box beside it."""
    functions = _functions(_code("app.js"))

    assert "askCredential" not in functions["offerConnect"]
    assert 'type = "password"' not in functions["confirmIdentity"]
    assert "askCredential(holder, identity, account)" in functions["confirmIdentity"]
    assert "About to connect this account:" in functions["confirmIdentity"]


def test_the_credential_reaches_no_url_and_no_browser_storage() -> None:
    """§4's first clause: the credential "is placed in no URL, no query string, no
    fragment, no path segment, no cookie, no response body, no value the gateway
    writes on a stream, and **no browser storage of any kind**".

    A browser leaks in different places from a terminal — "a URL is written to history
    and to the referrer, `localStorage` outlives the tab, a form that repopulates on
    back-navigation holds the value after the page has apparently gone" — so what is
    asserted is that the two functions holding the value touch none of them, and that
    the field is emptied and torn down the moment it has been read.
    """
    functions = _functions(_code("app.js"))
    holding = functions["askCredential"] + functions["sendConnect"]

    for leak in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "location",
        "href",
        "search",
        "URLSearchParams",
        "encodeURIComponent",
    ):
        assert leak not in holding, leak
    assert 'autocomplete = "off"' in functions["askCredential"]
    assert 'secret.value = ""' in functions["askCredential"]
    assert functions["askCredential"].index('secret.value = ""') < functions["askCredential"].index(
        "sendConnect("
    )
    assert "clearNode(holder)" in functions["askCredential"]


def test_a_pending_record_is_never_rendered_as_something_in_progress() -> None:
    """ADR-0151 §4: "a surface rendering one says the reference is *not connectable*
    and that the remedy is to run the act again, and never that the connection is
    being established, is in progress, or will complete on its own. Nothing is
    running — ADR-0148 §6 rules an interrupted act's state 'refused rather than
    reconciled', and the record is inert until a user acts"."""
    script = _code("app.js")
    words = _functions(script)["stateWords"]

    assert "Not connectable" in words
    assert "Connect it again, or disconnect it." in words
    assert "Nothing is running" in words
    for promise in ("being established", "is in progress", "will complete"):
        assert promise not in script, promise


def test_a_disconnection_that_removed_nothing_is_reported_as_the_one_thing_it_says() -> None:
    """ADR-0151 §8: a ``None`` "is **not** a report of a disconnection: no client
    presents it as one, as a confirmation that a credential was deleted, or as a
    statement that the reference does not exist. It says one thing — no live record
    was removed by this call"."""
    drop = _functions(_code("app.js"))["disconnectReference"]

    assert "result.body.removed === null" in drop
    assert "No live record was removed by that call." in drop
    assert "not a confirmation that a credential was deleted" in drop


def test_every_outcome_class_the_contract_names_has_its_own_words() -> None:
    """ADR-0151 §7 and §8: each condition carries facts a client may not derive from
    anything else, and ``residual-credential`` in particular means the act
    **completed** — "no client reports it as a failed connection or a failed
    disconnection"."""
    script = _code("app.js")
    conditions = script[
        script.index("const CONNECTION_CONDITIONS = {") : script.index(
            "\n};", script.index("const CONNECTION_CONDITIONS = {")
        )
    ]

    for named in (
        "identity-unusable",
        "no-such-connection",
        "provisioning-displaced",
        "provisioning-incomplete",
        "provisioning-outcome-unknown",
        "connection-store-unread",
        "residual-credential",
    ):
        assert f'"{named}"' in conditions, named
    assert conditions.count("stateKnown: true") == 2
    assert "This is not a failed act." in conditions


def test_an_unread_state_is_resolved_by_a_read_and_never_by_re_running_the_act() -> None:
    """ADR-0151 §7: the resolution "is to read ``connected_accounts``, never to re-run
    the act on the assumption it failed", and a read that does not answer leaves the
    state unread rather than assumed — "the alternative is a client that says 'nothing
    is connected' because it could not ask".

    The read is the **browser's** own request: ADR-0177 §1 forbids the gateway
    composing one operation out of two.
    """
    after = _functions(_code("app.js"))["stateAfterAct"]

    assert 'relay(half, "/connections", {}, "connections")' in after
    assert "CONNECTION_STATE_UNREAD" in after
    assert "GATEWAY_GONE" not in after
    assert "/connection/connect" not in after


def test_the_page_keeps_the_two_connection_questions_apart() -> None:
    """ADR-0139 §1 and ADR-0151 §9: "No client derives a reference's current state
    from this", and neither listing is answered with the other. Two reads, two panels,
    and neither function calls the other's path."""
    functions = _functions(_code("app.js"))

    assert "/connections/recent" not in functions["listConnections"]
    assert '"/connections"' not in functions["listConnectionLog"]
    assert "connection-log" not in functions["listConnections"]


def test_the_log_renders_no_time_and_no_claim_about_what_is_connected() -> None:
    """ADR-0151 §9: "It carries no instant… no client presents this order as a timing
    claim, an interval, or a statement about when anything happened", and a removal is
    the absence of the act's record rather than a third state (ADR-0149 §5)."""
    row = _functions(_code("app.js"))["renderConnectionAct"]

    assert "one.account === null" in row
    assert "Disconnected" in row
    for timing in ("noticed_at", "expires", "Instant"):
        assert timing not in row, timing


def test_a_record_an_act_returned_is_not_rendered_as_a_row_of_the_listing() -> None:
    """ADR-0151 §8: what a disconnection returns is "the live record removed, **as it
    stood immediately before the removal entry was appended**".

    So it is not a statement about the store now, and a row offering `Disconnect` on
    it would offer an act on something that no longer exists. The caption is what
    tells the two renderings apart, and only the listing's carries the acts.
    """
    functions = _functions(_code("app.js"))

    assert "offerConnectionActs" in functions["renderAccount"]
    assert "offerConnectionActs" not in functions["renderActRecord"]
    assert "offerConnectionActs" not in functions["renderRecordFields"]
    assert "immediately before it was removed" in functions["reportConnectionAct"]
    assert "renderActRecord" in functions["reportConnectionAct"]
    assert "renderAccount(" not in functions["reportConnectionAct"]


def test_a_refused_identity_does_not_claim_the_credential_stayed_in_the_page() -> None:
    """ADR-0151 §5 raises ``UnusableIdentityError`` "locally, before any I/O, by every
    implementation — the wire client included — so no such call reaches the hub and no
    credential is sent for one".

    The implementation in question is the **gateway's** engine: the browser has
    already put the value in a request body and sent it one hop by the time the
    refusal happens. A page telling the owner the credential never left it would
    reassure them about a Tier 0 value that has in fact travelled — which is the one
    thing ADR-0177 §4 exists to be exact about.
    """
    script = _code("app.js")
    opened = script.index("const CONNECTION_CONDITIONS = {")
    conditions = script[opened : script.index("\n};", opened)]
    refusal = conditions[
        conditions.index('"identity-unusable"') : conditions.index('"no-such-connection"')
    ]

    assert "no credential reached the hub" in refusal
    assert "did reach the gateway on this machine" in refusal
    for false_comfort in ("left this page", "never left", "stayed here"):
        assert false_comfort not in refusal, false_comfort


def test_a_residual_credential_is_reported_as_the_act_it_completed() -> None:
    """ADR-0151 §8: "A client reports the reference as disconnected **and** the
    deletion as incomplete, and never as a failed disconnection" — and §7 the same for
    a re-provisioning, where "the reference is connected at the new revision".

    Two different guarantees, so one shared sentence reports neither. The act's own
    result is said first, and a read taken afterwards — which says what is true *now*
    and can fail — takes nothing back from it.
    """
    script = _code("app.js")
    report = _functions(script)["reportConnectionAct"]
    acts = script[
        script.index("const ACTS = {") : script.index("\n};", script.index("const ACTS = {"))
    ]

    assert "The account is connected." in acts
    assert "connected at the new revision" in acts
    assert "The reference has no live record." in acts
    assert 'result.body.fault === "residual-credential"' in report
    assert report.index("words.residual") < report.index("named.words")
    assert "takes nothing back from what is said above" in script


def test_an_incomplete_act_offers_the_two_remedies_on_the_reference_it_named() -> None:
    """ADR-0151 §7: "A client names the reference, says the act did not complete, says
    the reference's state is unread, and offers ``reprovision_account`` or
    ``disconnect_account`` on it — both safe whoever now owns the record, the first by
    its own compare-and-swap and the second by being idempotent".

    They are offered from the outcome itself and not from a listing row, because the
    listing may be exactly what could not be read — and a row would claim the
    reference is live, which is what the page has just said it cannot state.
    """
    script = _code("app.js")
    functions = _functions(script)

    assert '"provisioning-incomplete": { replace: true, disconnect: true }' in script
    assert "offerRemedies(panel, handle" in functions["reportConnectionAct"]
    assert "Neither is a statement that it is connected" in functions["offerRemedies"]
    assert "disconnectReference(handle, null)" in functions["offerRemedies"]
    assert (
        'offerConnect(el("connect-form"), { reference: handle, identity: "" })'
        in (functions["offerRemedies"])
    )
    # A reference with no live record on screen gets a confirmation about what is
    # actually known, rather than one that invents a record to show.
    assert "No live record for it is on screen" in functions["disconnectReference"]


def test_no_remedy_is_offered_where_the_contract_forbids_retrying_blind() -> None:
    """ADR-0151 §7's silence is load-bearing. On ``provisioning-outcome-unknown`` the
    resolution is "to read ``connected_accounts`` — **never by re-running the act on
    the assumption it failed**, which would rotate a credential that may already be
    live", and on ``provisioning-displaced`` there is "no reason to retry the same act
    blind"."""
    script = _code("app.js")
    prescribed = script[
        script.index("const REMEDIES = {") : script.index(
            "\n};", script.index("const REMEDIES = {")
        )
    ]

    assert '"provisioning-outcome-unknown"' not in prescribed
    assert '"provisioning-displaced"' not in prescribed
    assert '"connection-store-unread"' not in prescribed
    assert '"identity-unusable"' not in prescribed
    assert '"residual-credential": { replace: false, disconnect: true }' in prescribed
    assert "if (!prescribed) {" in _functions(script)["offerRemedies"]


def test_every_connection_condition_the_gateway_writes_is_a_condition_the_page_reads() -> None:
    """ADR-0177 §3 requires its two refusals "reported as its own condition", and
    ADR-0168 §9 requires the same of each relay condition.

    The requirement does not stop at the gateway: a condition the page has no words
    for renders as "the gateway refused that request (HTTP 403)", which is the
    flattening §3 forbids, arriving one layer out. The two vocabularies answer
    different questions and both must be total — ``FAULTS`` is what a **read** shows
    when it could not be taken, ``CONNECTION_CONDITIONS`` what an **act** shows about
    what it did.
    """
    script = _code("app.js")
    faults = script[
        script.index("const FAULTS = {") : script.index("\n};", script.index("const FAULTS = {"))
    ]

    for named in (
        "connections-need-a-local-hub",
        "credential-entry-loopback-only",
        "credential-unusable",
        "identity-unusable",
        "no-such-connection",
        "provisioning-displaced",
        "provisioning-incomplete",
        "provisioning-outcome-unknown",
        "connection-store-unread",
        "residual-credential",
    ):
        assert f'"{named}"' in faults, named
    # And a store that could not be read is not a store that is empty.
    assert "not that nothing is" in faults


# --- the CONFIRM prompt (ADR-0177 §8, ADR-0178 §7) ---------------------------
#
# What these check is the *page*, which is the half #1404's obligations reach that a
# handler test cannot: the gateway builds a view carrying ADR-0178 §7's floor, and a
# page that received it and rendered half of it would still satisfy every case in
# ``test_gateway_confirmations.py``.


def test_the_prompt_panel_ships_and_carries_no_markup_template() -> None:
    """ADR-0177 §8: every value a ``Confirmation`` carries is inserted "as text through
    the document's own text node, never as markup and never through any interface that
    parses markup".

    So the document carries the panel and none of the prompt: a template here would be
    a second place a value could be put, and the one interesting thing about it would
    be that it parses markup.
    """
    document = _asset("index.html")

    assert 'id="confirmations"' in document
    assert 'id="confirmation-list"' in document
    assert 'id="confirmations-button"' in document
    assert "account_identity" not in document
    assert "destinations" not in document


def test_the_page_renders_the_set_it_was_handed_and_derives_none_of_it() -> None:
    """ADR-0178 §3, and #1404's "one further test", at the surface it is about.

    "No lane reimplements the deduplication, the account substitution or the order in
    another language, in ``interfaces/``, or in a page's script" — that would be
    business logic in an adapter (golden rule 3) and a second derivation of one fact,
    and "a page that got any of the three wrong would show a recipient set the ruling
    was not taken over".

    Checked as an absence rather than as a presence, because the failure this guards
    is a lane *adding* a derivation: the page reads ``egress.destinations``, the
    functions that render it hold no set arithmetic at all, and nothing here builds a
    destination out of the occurrences beside it.
    """
    functions = _functions(_code("app.js"))
    rendering = functions["renderEgress"] + functions["destinationWords"]

    assert "egress.destinations.forEach" in functions["renderEgress"]
    for derivation in ("sort(", "new Set", ".filter(", ".reduce(", ".indexOf(", ".includes("):
        assert derivation not in rendering, derivation
    # The account substitution is `core`'s too: the page branches on the member it was
    # handed, and never on whether the occurrences carried a destination. Counted, so
    # the *only* place a destination is spoken of in this function is the set it was
    # given — a lane deriving one from `egress.spans` would break the equality.
    assert "spans" not in functions["destinationWords"]
    egress = functions["renderEgress"]
    assert egress.count("destination") == egress.count("egress.destinations") + egress.count(
        "destinationWords("
    )


def test_the_page_states_the_calls_origin_beside_the_whole_floor_in_both_states() -> None:
    """ADR-0181 §6 and §10's clause for this lane, at the half a handler test cannot reach.

    §10 requires that a confirmation carrying ``True`` render "the fact **and** every
    occurrence ADR-0178 §7's floor already requires", and that ``False`` render the
    fact too. The gateway's own tests pin what crosses; this pins what the *page*
    does with it, which is where a lane could take the boolean and render half of it.

    **The order is asserted, not just the membership** (§6's sixth clause): the new
    line sits after the account and before the recipients, and nothing of the floor
    is displaced by it. It goes there because the fact is a property of the call
    rather than of a span — among the occurrences it would read as the per-span
    attribution ADR-0181 §2's third clause refuses to mint.
    """
    functions = _functions(_code("app.js"))
    body = functions["renderEgress"]

    # The page reads the fact it was handed, and derives nothing (ADR-0178 §3).
    assert "egress.planned_with_external_content" in body

    # Beside the floor, and between the account and the recipients.
    assert body.index("egress.account_identity") < body.index("planned_with_external_content")
    assert body.index("planned_with_external_content") < body.index("egress.destinations")

    # ...and the floor itself, whole and in its own order.
    assert body.index("It would reach:") < body.index("What it describes sending:")
    assert "egress.destinations.forEach" in body
    assert "egress.spans.forEach" in body


def test_neither_arm_of_the_origin_line_names_a_source_a_span_or_a_verdict() -> None:
    """ADR-0181 §6's second, third, fifth and sixth clauses, on the wording itself.

    Both arms are spelled out because the clauses are about what each *says*: no
    source and no kind of source ("from a source you connected" is barred in terms,
    ADR-0098 §1's class being wider than connected sources); the ``False`` arm an
    absence of a marker and never an assurance that no external content was
    involved; no attribution to a span; and no detection, score, risk level or claim
    that the call is malicious.

    Adjacent string literals are joined first, so the assertion reads the sentence
    the browser would show rather than however the source happens to wrap it.
    """
    joined = re.sub(r'"\s*\+\s*"', "", _functions(_code("app.js"))["originWords"])

    assert (
        "material this assistant selected, which includes a record marked as "
        "resting on recorded external content" in joined
    )
    assert (
        "material this assistant selected, in which no record is marked as "
        "resting on recorded external content" in joined
    )

    # §6's second and sixth clauses, as the absences they are stated as.
    for forbidden in (
        "source you connected",
        "connected source",
        "malicious",
        "suspicious",
        "untrusted",
        "risk",
        "warning",
        "attack",
        "injected",
        "unsafe",
    ):
        assert forbidden not in joined.lower(), forbidden

    # §6's fourth clause leaves exactly two arms: the field is required with no
    # default (ADR-0181 §3) and the process that served this script serialised the
    # view, so there is no third state, and inventing one would be a fabrication at
    # the surface where the owner is being asked to approve something.
    assert "undefined" not in joined
    assert "null" not in joined


def test_the_approval_control_is_built_after_the_whole_floor() -> None:
    """ADR-0178 §7's first clause is an ordering obligation: a surface renders the floor
    "**before it collects the user's answer**".

    A page that appended the buttons first would satisfy every content check and still
    offer the owner an approval above the recipients — so the order is asserted, not
    the membership.
    """
    body = _functions(_code("app.js"))["renderConfirmation"]

    assert body.index("renderParameters(") < body.index("offerApproval(")
    assert body.index("renderEgress(") < body.index("offerApproval(")
    assert body.index("confirmation.reason") < body.index("offerApproval(")


def test_a_confirmation_with_no_egress_says_nothing_about_recipients() -> None:
    """ADR-0178 §4's third clause and §7's last.

    ``egress is None`` states that "the ruling was taken over an egress binding, and
    nothing more" — no lane reads it as a warrant that the call transmits nothing,
    discloses nothing, or reaches no recipient. So the branch has no other arm: there
    is nothing for a page to say there, and inventing a sentence would be asserting the
    one thing the discriminator does not carry.
    """
    body = _functions(_code("app.js"))["renderConfirmation"]

    assert "if (confirmation.egress !== null) {" in body
    assert "} else {" not in body


def test_the_token_is_relayed_and_never_rendered_or_stored() -> None:
    """ADR-0177 §8: "The front end parses no part of it, derives nothing from it,
    renders it nowhere, and stores it in no browser storage."

    The four functions below are the whole of what touches it — it reaches the answer
    through a closure — and none of them puts it in a text node, in an attribute or in
    ``localStorage``.

    **``renderOperationConfirmation`` is the fourth and it is a routed park's card**
    (ADR-0197 §7). A routed confirmation carries a ``ContinuationToken`` exactly as a
    tool confirmation does and is answered through the same ``resume``, so §8's rule
    reaches it unchanged — it hands the handle straight to ``offerApproval`` and
    renders nothing of it. The set is asserted rather than the members, so a sixth
    function reaching for a token fails here rather than being noticed.

    **``strand`` is the fifth** (#1621): the one act that gives a token back and records
    that its answer went unread. It compares the handle against two sets and puts it in
    no node, which is §8 obeyed exactly as the four above obey it.

    **``readConfirmation`` is the sixth and it reads the token's *type*** (ADR-0233 §8).
    It asks whether the handle arrived as text and nothing else — it does not parse it,
    derive from it, render it or store it — and it asks because a card whose control
    cannot be answered is a card offering an approval that will fail. The rule it is
    part of is total over every member ``renderConfirmation`` dereferences, and the
    token is one of them.

    **``cancelRead`` is the seventh** (ADR-0244 §11). It relays the handle to
    ``/confirmation/cancel-read`` and keys two registries by it, exactly as
    ``answerConfirmation`` keys three — §8's rule reaching the second act a park can
    carry, unchanged and for its reason: the cancellation is "the act they performed",
    and what the row says about it is computed by ``rowWords``, which takes the member
    and not the handle.

    **The last three are the panel's two accounts** (adversarial review's round 8).
    ``recordAnswerAccount`` and ``releaseAnswerAccount`` hold and drop the park an unread
    answer was about, and ``answerAccountWords`` reads that park's cancellation back out
    of ``cancelled`` and ``cancelling`` to decide what the account now says. All three
    **compare** the handle and nothing else — it is a key into two registries and a
    property of a page-held object, it reaches no text node, no attribute and no storage,
    and ``writeAccount``, which is the only thing here that touches the DOM, never sees
    it. That is ``strand``'s own relationship to §8 one act over: the token is how this
    page knows which park it is talking about, and §8 forbids rendering it, not holding
    it.
    """
    script = _code("app.js")
    functions = _functions(script)

    touching = {
        "renderConfirmation",
        "renderOperationConfirmation",
        "offerApproval",
        "answerConfirmation",
        "strand",
        "readConfirmation",
        "cancelRead",
        "recordAnswerAccount",
        "releaseAnswerAccount",
        "answerAccountWords",
    }
    assert {name for name, body in functions.items() if "token" in body} == touching
    assert not re.search(r"textContent\s*=[^;]*token", script)
    assert not re.search(r"\bline\([^)]*\btoken\b", script)
    for name in touching:
        assert "localStorage" not in functions[name], name


def test_the_answer_supplies_approved_and_nothing_else() -> None:
    """ADR-0177 §8's second clause and §9: "The browser's answer supplies ``resume``'s
    ``approved`` argument and nothing else", and ``timeout`` is the caller-owned
    deadline §1 and §9 place with the gateway.

    Read off the request body the page actually writes, which is where a third member
    would appear.
    """
    script = _code("app.js")
    body = _functions(script)["answerConfirmation"]

    assert re.search(
        r'relay\(\s*half,\s*"/confirmation/resume",\s*\{ token, approved \},\s*'
        r'"confirmations",\s*stopping,\s*noticed,?\s*\)',
        body,
    )
    # The fifth argument is a controller and not a figure: it carries the owner's own
    # act into ``fetch`` and reaches no request body. ``resume`` "is given the same
    # budget a turn is given at this surface" (§9), so a page that supplied one would be
    # supplying a second number able to disagree with ``_TURN_BUDGET`` — and one that
    # armed a deadline of its own would abandon a healthy resumed turn that was thinking.
    assert "timeout" not in body
    assert "AbortSignal" not in script
    assert (
        "signal: stopping === undefined ? undefined : stopping.signal,"
        in _functions(script)["relay"]
    )


def test_pending_confirmations_is_the_pages_one_recovery_route() -> None:
    """ADR-0177 §8: "A browser that has been closed and reopened, and a gateway that has
    been restarted, both recover through this read and through no other route."

    So the page reads it as it loads, without being asked, and re-reads it after an
    answer — which is also how it gets fresh tokens for whatever is left rather than
    keeping the ones it holds (ADR-0052 §1).
    """
    script = _code("app.js")
    functions = _functions(script)

    assert {name for name, body in functions.items() if '"/confirmations"' in body} == {
        "readPending"
    }
    assert "readPending(true)" in functions["showConsole"]
    assert "readPending(true)" in functions["answerConfirmation"]


def test_the_page_says_who_disclosed_a_span_in_every_word_core_has() -> None:
    """ADR-0146 §1's discloser, rendered as **who** and never as a claim about what the
    span holds — ADR-0178 §7 forbids presenting a ``SYSTEM_SELECTED`` marker "as an
    assertion about what the text says".

    Read off `core`'s own vocabulary, so a third member added to the enum fails here
    rather than reaching a person as a bare identifier.
    """
    body = _functions(_code("app.js"))["disclosureWords"]

    for provenance in DiscloserProvenance:
        assert f'"{provenance.value}"' in body, provenance.value


def _vocabulary(script: str) -> str:
    """The ``COVERAGE_WORDS`` map's own text.

    The page's whole vocabulary for ADR-0233 §4's three states — the sentences and the
    enumeration in one place, so ``coverageWords`` and the refusal in ``readEgress``
    cannot come to disagree about which states exist.
    """
    opened = script.index("const COVERAGE_WORDS = {")
    return script[opened : script.index("\n};", opened)]


def test_every_value_is_put_on_the_screen_whole_and_as_a_text_node() -> None:
    """ADR-0233 §8's rendering floor, at the half a reading of the file decides.

    Three clauses meet in one helper. Every value is inserted "as **data**,
    neutralised for that target on render", which here is a text node and nothing
    else — the same rule ADR-0177 §8 already binds this page to, reaching the one
    text on the page whose exact characters are the thing being answered about.
    Every value is rendered **whole**, which for prose means the line breaks survive:
    a paragraph collapses them, so the value gets a block with its own rule rather
    than the tail of its key's line. And nothing may hide part of one, so the class
    it carries has no rule that could.

    The **drive** is what says this works on a screen
    (``test_browser_confirmations.py``, ADR-0233 §15); what a reading decides is that
    there is one helper, that it is the only way a value reaches the card, and that
    it uses none of the markup-parsing sinks this file bars everywhere else.
    """
    functions = _functions(_code("app.js"))
    block = functions["valueBlock"]

    assert "textContent" in block
    assert 'className = "argument-value"' in block
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "createContextualFragment"):
        assert sink not in block, sink
    # One renderer of a confirmation's content, and no second caller: since
    # adversarial review's rounds 3 and 6 the arguments cross decomposed and are
    # rendered exactly once, so nothing on the screen can disagree with anything else
    # on it — and no span carries a copy for it to disagree with.
    assert {name for name, body in functions.items() if "valueBlock(" in body} == {
        "valueBlock",
        "renderParameters",
    }
    assert "span.value" not in _code("app.js")


def test_the_stylesheet_cannot_hide_part_of_a_value() -> None:
    """ADR-0233 §8: a value is "not truncated, not elided, not abbreviated, not
    summarised, not paraphrased, not collapsed behind a control the user must operate
    to see them".

    A stylesheet is where a page that renders a value whole can still show a third of
    it, which is the failure ``.confirmation-row`` already has no rule for. So the
    rule that makes the line breaks render is asserted **present**, and every rule
    that could clip the block is asserted absent — including the scroller, which is
    the tempting answer for a long body on a phone and is the one §8 rules out.
    """
    rule = _rule(_style("app.css"), ".argument-value")

    assert "white-space: pre-wrap;" in rule
    for forbidden in ("max-height", "overflow", "line-clamp", "text-overflow", "display: none"):
        assert forbidden not in rule, forbidden


def test_the_values_are_rendered_before_there_is_anything_to_press() -> None:
    """ADR-0233 §8: "Where a surface has an order, the values precede the controls."

    ADR-0178 §7's own ordering clause is pinned above over the floor's *facts*; this
    is the same obligation over the **content**, and it is a different assertion
    because a lane could put the values after the buttons and leave that one green.

    Every value is rendered by ``renderParameters``, which ``renderConfirmation``
    calls before both the egress facts and the control — so the check is that the one
    renderer of content runs first, and that what it renders is the **locator** every
    span is identified by, which is what makes "every span's value" and "before the
    control" one ordering rather than two.
    """
    functions = _functions(_code("app.js"))
    card = functions["renderConfirmation"]
    arguments = functions["renderParameters"]

    assert card.index("renderParameters(") < card.index("offerApproval(")
    assert card.index("renderEgress(") < card.index("offerApproval(")
    assert card.index("renderParameters(") < card.index("renderEgress(")
    # Every entry the carrier holds, under the locator that names it — the same
    # spelling ``spanWords`` gives a span, which is what joins the two halves of the
    # card and what ``readSpan`` looks a span up by.
    assert "parameters.forEach(" in arguments
    assert "locatorWords(one.key, one.index)" in arguments
    assert "locatorWords(span.argument, span.index)" in functions["spanWords"]


#: Every function ADR-0233 §8's shape rule is written in, so the rule has one text.
#:
#: It is a family rather than one function because the body it reads is nested — an
#: entry inside ``parameters``, a member inside ``destinations``, a recipient inside a
#: span — and a single function walking all of that is one nobody can check against the
#: renderers. What makes it a rule and not a list is that every member the renderers
#: dereference is named somewhere in this text, which is what the test below asks.
_SHAPE_RULE: Final = (
    "isRecord",
    "isText",
    "isPosition",
    "readConfirmation",
    "readParameter",
    "readEgress",
    "readDestination",
    "readSpan",
    "readSpanDestination",
)

#: The functions that dereference a confirmation's own members, and therefore the
#: functions the shape rule has to be total over. ``coverageWords``, ``originWords``,
#: ``disclosureWords`` and ``locatorWords`` are not here: each is handed a value rather
#: than a body, so it reads no member of one.
_CONFIRMATION_RENDERERS: Final = (
    "renderConfirmation",
    "renderParameters",
    "renderEgress",
    "destinationWords",
    "spanWords",
)

#: One chain of members read off a confirmation, an egress binding, an argument entry,
#: a set member or a span — the five identifiers those renderers hold one of the body's
#: own values in.
#:
#: The **whole** chain is captured and split, because a read two deep is still two
#: members read: ``span.destination.supplied`` is where a recipient's supplied form is
#: dereferenced, and a pattern matching only the first segment would leave ``supplied``
#: out of the set this is total over.
_MEMBER_READ: Final = re.compile(
    r"\b(?:confirmation|egress|parameters|one|member|span)((?:\.\w+)+)"
)


def test_a_confirmation_that_cannot_be_shown_whole_is_not_shown_at_all() -> None:
    """ADR-0233 §8's second clause: "A surface that cannot render a value whole renders
    **no** confirmation and says so."

    The guard is asserted to be the **first** thing ``renderConfirmation`` does, ahead
    of the tool line, the arguments, the egress facts and the control — a card refused
    after half of it is on screen is the partial confirmation the clause is against.
    What it says is asserted too, because "and says so" is half the clause.

    **Every test is a type test over a shape, not an equality against one value**
    (adversarial review, rounds 1, 2 and 6). Nothing in this page validates the body it
    was handed, so every member it reads can be absent, a number or an object: a
    ``value`` that is missing is ``undefined``, which a check for ``null`` alone let
    through to be rendered as the word "undefined"; a ``coverage`` outside the three is
    a sentence about the call this page would be inventing; and an ``egress`` or a
    ``spans`` that is absent used to **throw** here, which ``readPending`` caught as
    "the gateway did not answer" — the wrong sentence, and it took the whole listing
    with it.

    **And the rule is asserted total rather than case by case**, which is what rounds
    1, 2, 6 and 7 cost: each named one more member than the last — a span's value, then
    ``coverage``, then the containers, then the entries inside them — and each fix left
    the next member unguarded, because the defect was never the member. So the members
    this asks about are not written down here: they are read **off the renderers**, and
    every one either renderer dereferences must be named by the shape rule. A member
    added to a renderer without a test for it fails this, which is the eighth round not
    being needed.

    **And the locator is a lookup rather than a comparison**, because the content is
    carried once: a span's own value is the argument entry carrying its locator, so
    what is asked is that the locator names exactly one entry. There is no second copy
    for a comparison to be made against (ADR-0233 §2), and what an entry *is* has
    already been asked of every entry before any span is read — which is why the two
    halves are read in that order and the order is pinned.
    """
    script = _code("app.js")
    functions = _functions(script)
    card = functions["renderConfirmation"]

    assert card.index("CONFIRMATION_NOT_WHOLE") < card.index("confirmation.tool_id")
    assert card.index("CONFIRMATION_NOT_WHOLE") < card.index("offerApproval(")
    assert "if (!readConfirmation(confirmation)) {" in card
    assert "so it is not put to you at all" in _joined(
        script[script.index("const CONFIRMATION_NOT_WHOLE") :]
    )

    family = "".join(functions[name] for name in _SHAPE_RULE)
    # The three predicates the rule is written in, each a type test: an object that is
    # an object and not an array or ``null``; text, because a member that did not
    # arrive is ``undefined`` and a template renders that as a word; and ADR-0150 §4's
    # position, which is absent or an integer and nothing else.
    assert "!Array.isArray(value)" in functions["isRecord"]
    assert 'typeof value === "string"' in functions["isText"]
    # And **well-formed**, which is the other half of "as itself": a lone surrogate has
    # no UTF-8 encoding, and a text node holding one renders the replacement character
    # in place of a character the value does not contain (adversarial review, round 11).
    assert "value.isWellFormed()" in functions["isText"]
    assert (
        "index === null || (Number.isSafeInteger(index) && index >= 0)" in functions["isPosition"]
    )
    # Each member is read as `core` **declares** it, the range on the declaration
    # included — and the rule stops there rather than restating the relations *between*
    # members, which are `ActionRequest`'s and which a page cannot state without a
    # second derivation of ADR-0150 §4 (adversarial review, round 8).
    assert "!Number.isSafeInteger(span.extent) || span.extent < 0" in functions["readSpan"]
    # **Safe**, not merely integral: both members cross as JSON numbers, so a value past
    # 2**53 has already been rounded by ``JSON.parse`` and would be rendered as a
    # locator or a count the gateway did not send — ``_parameter_text``'s own
    # losslessness rule reaching the two members that cannot be spelled as text
    # (adversarial review, round 10).
    assert "Number.isInteger" not in family
    # The containers, the vocabulary, and the one member whose absent state would put a
    # sentence on the screen that the page was not told (ADR-0181 §6's ``false`` arm).
    reader = functions["readConfirmation"]
    egress = functions["readEgress"]
    assert "Array.isArray(confirmation.parameters)" in reader
    assert "Array.isArray(egress.spans)" in egress
    assert "Array.isArray(egress.destinations)" in egress
    # Text **before** the lookup, because a property key is coerced: without it the
    # array ``["not_covered"]`` answers the vocabulary as that state's own name
    # (adversarial review, round 9).
    assert "isText(egress.coverage) || !Object.hasOwn(COVERAGE_WORDS, egress.coverage)" in egress
    assert 'typeof egress.planned_with_external_content !== "boolean"' in egress
    # Every entry is read before any span is, so the locator lookup below may ask how
    # many entries carry a locator without asking again what an entry is.
    assert reader.index("readParameter") < reader.index("readEgress")
    assert "one.key === span.argument && one.index === span.index" in functions["readSpan"]

    # **Total over what the renderers read.** The member names are collected from the
    # confirmation renderers themselves rather than listed here, so this cannot fall
    # behind them; the two array methods are the only reads that are not members of the
    # body. The floor on the count is what stops a pattern that matched nothing from
    # passing this vacuously.
    read = set()
    for name in _CONFIRMATION_RENDERERS:
        for chain in _MEMBER_READ.findall(functions[name]):
            read |= set(chain.split(".")[1:])
    read -= {"length", "forEach"}
    assert len(read) >= 20, sorted(read)
    for member in sorted(read):
        assert f".{member}" in family, member


def test_the_call_carries_one_coverage_line_in_every_state_core_has() -> None:
    """ADR-0233 §8's coverage floor, read off `core`'s own vocabulary.

    "A surface renders the call's ``coverage`` … in **all three** states", including
    the one §6 makes unreachable in a confirmation — because "a fact shown only when
    it is alarming is a fact a user learns to read as an alarm, and its absence as
    clearance". A fourth member added to the enum fails here rather than reaching a
    person as a bare identifier, which is ``disclosureWords``' own arrangement.

    **It is the value the page was handed, and the page derives nothing.** ADR-0178 §3
    bars a surface inferring a fact with a rule of its own; the arms branch on
    ``coverage`` and on nothing else, and in particular on neither of the other two
    axes — a page reading the origin boolean or a span's provenance to decide what to
    say here would be asserting a marker no ADR mints (ADR-0233 §4, §8).
    """
    script = _code("app.js")
    functions = _functions(script)
    words = _vocabulary(script)

    assert "egress.coverage" in functions["renderEgress"]
    for state in SpanCoverage:
        assert f"{state.value}:" in words, state.value
    # Three keys and no fourth, so the map the sentences come from and the test the
    # card is refused by (``readEgress``) are one enumeration rather than two that can
    # drift apart.
    assert words.count(":") == len(SpanCoverage)
    assert "return COVERAGE_WORDS[coverage];" in functions["coverageWords"]
    for axis in ("planned_with_external_content", "provenance", "tier", "extent", "span"):
        assert axis not in words, axis


def test_no_arm_of_the_coverage_line_is_an_assurance_a_verdict_or_a_span() -> None:
    """ADR-0233 §8's wording clauses, on the sentences themselves.

    Four of them, each stated as an absence because each is about what the line must
    not say. It is a statement about **the call**, so the lead-in says so and no arm
    names an argument, a position or a destination (§8's sixth clause, ADR-0181 §6's
    fifth read one axis over). ``not_covered`` is **not an assurance** — "it states
    that no covered path was recorded for this call, never that nothing in it relates
    to anything the user has told this system, and never that the send is safe". It is
    not a detection, a score, a risk level, a recommendation or a warning. And it
    names **no record** and no *kind* of source, which is ADR-0150 §10's second clause
    kept: no record identifier, no episode, no store-side key, no schema field, no
    memory.

    Adjacent string literals are joined first, so the assertions read the sentences
    the browser would show rather than however the source happens to wrap them.
    """
    script = _code("app.js")
    functions = _functions(script)
    joined = _joined(_vocabulary(script))

    assert (
        "About this call as a whole: ${coverageWords(egress.coverage)}" in functions["renderEgress"]
    )
    assert (
        "nothing it would send was recorded as drawn from what this system stores, "
        "which is what was recorded and not a statement that the send is safe" in joined
    )
    assert (
        "some of what it would send was composed by a model that had been shown "
        "something this system stores" in joined
    )
    assert "it would send something taken from what this system stores directly" in joined

    for forbidden in (
        "safe",
        "risk",
        "warning",
        "detect",
        "suspicious",
        "malicious",
        "unsafe",
        "score",
        "memory",
        "record id",
        "episode",
        "belief",
        "argument",
        "recipient",
        "source you connected",
    ):
        # "safe" is admitted in exactly one place: the clause saying the line is *not*
        # a statement that the send is safe.
        occurrences = joined.lower().count(forbidden)
        assert occurrences == (1 if forbidden == "safe" else 0), (forbidden, occurrences)


def test_the_page_shows_both_forms_and_reconstructs_neither() -> None:
    """ADR-0178 §7: "No surface reconstructs a ``supplied`` form from a ``canonical``
    one, or presents a canonical form as the form the user or the model wrote."

    ADR-0148 §14 names that reconstruction as a failure in terms, and the binding
    carries both forms so neither has to be guessed — so both are read, each is
    labelled, and nothing here case-folds, trims or normalises either one.
    """
    body = _functions(_code("app.js"))["spanWords"]

    assert "span.destination.canonical" in body
    assert "span.destination.supplied" in body
    assert "as supplied:" in body
    assert "names no destination" in body
    for reconstruction in ("toLowerCase", "toUpperCase", "normalize", "replace(", "trim("):
        assert reconstruction not in body, reconstruction


def test_the_arguments_are_not_presented_as_the_canonical_destination_set() -> None:
    """ADR-0177 §8's surviving sub-clauses, which ADR-0178 §8 leaves binding unchanged.

    "A browser rendering ``to = alice@example.com`` beside a heading that says
    'recipients' would be asserting that the user is looking at the bound canonical
    set, when what they are looking at is the argument the model produced before
    binding." The set now arrives *beside* the arguments rather than instead of them,
    which makes that confusion easier to make and the separation more load-bearing.
    """
    functions = _functions(_code("app.js"))

    assert "as the assistant wrote them" in functions["renderParameters"]
    for claim in ("reach", "recipient", "destination", "account"):
        assert claim not in functions["renderParameters"], claim
    assert "It would reach:" in functions["renderEgress"]


def test_the_routed_account_is_rendered_below_the_answer_and_never_instead_of_it() -> None:
    """ADR-0197 §10's first Normative, which is ADR-0170 §6's rule and binds for its
    reason — sharpened, because on a routed pass the composing stage was handed two
    enum values and nothing else (§6), so the worst prose it can produce is prose
    about the wrong thing while the account beside it is typed data no prompt
    influenced.

    Read off ``renderOutcome``, which is where a renderer that returned early on a
    routed pass would have dropped the reply, and where one that rendered the account
    above it would have put the guarantee where the answer goes.
    """
    body = _functions(_code("app.js"))["renderOutcome"]

    assert "renderReply(body, outcome);" in body
    assert "renderRouted(body, outcome.routed);" in body
    assert body.index("renderReply(body, outcome);") < body.index(
        "renderRouted(body, outcome.routed);"
    )


def test_every_routed_operation_has_an_arm_and_every_arm_has_a_renderer() -> None:
    """ADR-0197 §10: an adapter renders "the listing where one is carried", and the
    clause admits no exception for an arm this page had no panel for.

    An earlier shape of this lane rendered three of the seven and named the CLI for
    the other four, on the reading that ADR-0186 §6 and §10 reserve a browser view of
    either trail for "a later consumer lane with its own ratified decision".
    Adversarial review blocked it, correctly: that bar is on the **route** and not on
    the rendering, a routed pass makes no browser request for any of them, and a
    referral where a listing should be is a turn that did something rendered as a
    turn that did nothing.

    Both maps are read, because a hole in either is the same silent failure: an
    operation with no arm, or an arm with no renderer, renders nothing and says
    nothing about having rendered nothing.
    """
    script = _code("app.js")
    arms = re.search(r"const ROUTED_ARM = \{(.*?)\n\};", script, re.DOTALL)
    renderers = re.search(r"const ROUTED_ARM_RENDERERS = \{(.*?)\n\};", script, re.DOTALL)
    assert arms is not None
    assert renderers is not None

    named = dict(re.findall(r"(\w+): \"(\w+)\"", arms.group(1)))
    assert set(named) == {one.value for one in RoutableOperation}
    assert set(named.values()) <= set(re.findall(r"(\w+): render", renderers.group(1)))


def test_a_routed_ruling_says_it_is_a_ruling_and_not_an_event() -> None:
    """ADR-0186 §8's first and third clauses, on the page's new decision renderer.

    "Liveness is not derivable from history" — a row states that a ruling was made,
    never that it still stands, that a grant is current, that an account is connected
    or that the call ever ran — and no verb here presents a ruling as a transmission.
    The sentence is printed rather than assumed, because the reader who most needs it
    is the one treating this as a permissions screen.

    **No control appears on a row** (§8's last clause): a ruling is answered through
    ``pending_confirmations`` and ``resume``, and a renderer offering an approve or a
    deny here would be a second door onto a decision that was already taken.
    """
    body = _functions(_code("app.js"))["renderDecisionFields"]

    assert "It does not say the ruling still stands" in body
    assert "createElement" not in body, "no control on a history row"
    for verb in ("sent", "delivered", "transmitted", "emailed"):
        assert not re.search(rf"\b{verb}\b", body), verb


def test_a_routed_read_row_never_says_what_a_use_did_with_it() -> None:
    """ADR-0185 §10 and ADR-0186 §8's third clause: a row states what was
    **attempted**, never what any use did with the reading.

    ``remembering`` is what the ``ingest`` scope phrase says the read was *for*, so
    the check is on word boundaries — a substring test would fail on prose that
    claims nothing, which is the CLI's own reason for taking it that way.
    """
    body = _functions(_code("app.js"))["renderReadFields"]

    for verb in ("remembered", "learned", "stored", "notified", "told"):
        assert not re.search(rf"\b{verb}\b", body), verb
    assert "never the thing itself" in body, "a count, said to be one"


def test_the_page_shifts_no_instant_and_reaches_for_no_zone_database() -> None:
    """ADR-0194 §5 and §6: a period bound is read "from the value's **own**
    ``start_offset``/``end_offset``… never from the client's zone and never through
    the client's ``tzdata``".

    So the arithmetic is the gateway's and the page renders what it is handed. This
    is asserted over the whole script rather than over one function, because the
    thing being ruled out is a *reach* — a ``Date`` constructed to shift an instant,
    or a formatter that consults the browser's zone — and it would be as wrong in a
    helper as in the renderer.
    """
    script = _code("app.js")

    assert "new Date(" not in script
    assert "Intl." not in script
    assert "toLocale" not in script
    assert "getTimezoneOffset" not in script


def test_a_ruling_whose_pointers_disagree_is_refused_rather_than_read() -> None:
    """ADR-0193 §11 names exactly **three** authorisation states, and a ruling that
    answers one decision while resting on another is none of them.

    Two shapes were tried and both were blocked. A fourth authorisation line reads as
    a claim about authorisation; a diagnostic row carrying the id is a **partial**
    row, and ADR-0186 §7 is that "a surface that cannot render a row whole renders
    fewer rows, not partial ones". So the row is dropped whole and the listing says
    it was — which is the one thing a dropped row must not be, silent.

    The last assertions are what fail on the fourth state coming back.
    ``authorisationWords`` holds exactly **three** ``if``s — the two pointer tests
    ADR-0193 §11's conditions are read off, and ADR-0247 §2's route-(c) split *inside*
    the second of them — so a branch for a pair that never reaches this function would
    be a fourth. The four returns are those three conditions' lines plus the unguarded
    last one, and the route-(c) line is named rather than counted, because a count alone
    would pass on a fourth state wearing the fourth return.

    **Route (c) is a split and not a state** (ADR-0247 §2): §11's three conditions are
    unchanged, and what the ADR adds is what a surface *renders* for a standing row whose
    ``authorised_subject`` is unset and whose binding is closed-loop — the basis, naming
    no connection reference. The pair this case is about is still none of them.
    """
    functions = _functions(_code("app.js"))
    listing, decision = functions["renderRoutedListing"], functions["renderDecisionFields"]
    words = functions["authorisationWords"]

    assert "if (unreadableRecord(record)) {" in listing
    assert "dropped += 1" in listing
    assert "UNREADABLE_RULINGS" in listing
    assert "unreadable" not in decision, "the row is never reached, not branched inside"
    assert len(re.findall(r"\bif\b", words)) == 3
    assert len(re.findall(r"\breturn\b", words)) == 4
    assert "if (restsOnTheConfiguration(decision)) {" in words, "the fourth is route (c)"


def test_a_routed_total_is_never_presented_as_a_bill() -> None:
    """ADR-0194 §6: a total is the sum of what this system's own tools reported, and
    no surface presents one as an amount billed, owed or charged.

    **And the consequence line comes from that period's own ceiling**, never from the
    absence of a total: §2 refuses nothing on an indeterminate period the owner set
    no ceiling for, so a renderer keying on a missing figure alone tells them their
    calls are blocked when they are not.
    """
    body = _functions(_code("app.js"))["renderSpendFields"]

    assert "not checked against anyone's statement" in body
    assert "total.ceiling === null" in body, "the ceiling decides it, not the total"
    assert "!total.ceiling" not in body, "a configured ceiling of zero refuses the most"


def test_the_routed_listing_renders_every_record_and_summarises_none() -> None:
    """ADR-0197 §5's last clause: "No surface renders fewer candidates than the
    outcome carries or summarises in place of them" — ADR-0186 §7's rule for a trail
    row, applied to a candidate listing.

    The renderer walks the listing whole, and the stylesheet has no rule that could
    hide part of it: a page that rendered them all can still show a few if a fixed
    box scrolls the rest out of sight, which is what the second half checks.

    **The one count read is the zero test and it renders prose rather than a
    figure** (#1648). This case used to forbid ``length`` outright, which was the
    right rule for the wrong reason: what §5 forbids is a *summary standing in for
    the records*, and "3 rows" is that where "the record is empty" is not. So the
    read is pinned to the single occurrence rather than banned, and a second one --
    a slice bound, a count in a sentence, a "and N more" -- still fails here.
    """
    body = _functions(_code("app.js"))["renderRoutedListing"]

    assert "listing.forEach((record) =>" in body
    assert "slice(" not in body
    assert re.findall(r"[\w.]+\.length[^\n]*", body) == ["listing.length === 0) {"], (
        "no count stands in for the records; the only one read chooses the empty state"
    )
    listing_rule = re.search(r"\.routed-listing\s*\{[^}]*\}", _style("app.css"))
    assert listing_rule is not None
    assert "max-height" not in listing_rule.group(0)
    assert "overflow" not in listing_rule.group(0)


def test_an_empty_routed_listing_says_the_record_is_empty_rather_than_nothing() -> None:
    """A defect the browser found once the routed account reached this page (#1648).

    ADR-0197 §10's first Normative is that an adapter renders the routed account "in
    addition to any composed reply, never instead of it, and never in place of it",
    and this renderer built its ``div``, looped zero times over an empty listing and
    appended the empty ``div``. What reached the screen was the composed reply saying
    "you can see it right beside this message", the account saying the record was
    read, and then nothing -- so a reader could not tell **the trail is empty** from
    **the page failed to render the trail**, which are different answers to the same
    question. The CLI has never had the hole: ``_render_routed_listing`` delegates to
    the renderer the typed door already has, and each of those carries its own
    empty-state prose.

    **Empty is the common state**, not an edge: four of the six read-only members are
    empty on a hub with no sources configured.

    **The map is total over ADR-0197 §3's nine operations and every entry speaks.**
    An operation added under §3's widening rule with no entry falls back to a
    sentence rather than to a blank -- the opposite of ``ROUTED_ARM``'s deliberate
    missing key, because there a wrong renderer is worse than none and here silence
    *is* the defect.

    **A bounded record says so.** ``recent_reads`` and ``recent_invocations`` are
    both windows that drop their oldest rows, so an empty one is not a claim that
    nothing ever happened, and saying only the first half would be a stronger claim
    than the record supports.

    Driven in Chromium at 1100x900 and at 390x844 against a real ``Gateway`` over a
    seeded ``FakeAssistantEngine`` before this shipped; #1645 is the standing gap
    that no case here executes the page.
    """
    script = _code("app.js")
    body = _functions(script)["renderRoutedListing"]
    empty = _functions(script)["renderEmptyListing"]

    assert "if (listing.length === 0) {" in body
    assert "renderEmptyListing(list, operation);" in body
    assert body.index("renderEmptyListing") < body.index("listing.forEach"), (
        "the empty listing is answered before the loop, never by counting what it rendered"
    )

    block = re.search(r"const ROUTED_EMPTY = \{(.*?)\n\};", script, re.DOTALL)
    assert block is not None
    named = re.findall(r"\n  (\w+): \[", block.group(1))
    assert set(named) == {one.value for one in RoutableOperation}
    assert len(named) == len(set(named))

    assert "Nothing recorded. No attempt to read a source is in this record." in script
    assert "Nothing recorded. No act on an authorisation is in this record." in script
    assert "Nothing recorded. No ruling has been made yet." in script
    assert "Nothing is waiting on your answer." in script
    assert "You have not granted anything. I am allowed to read no source at all." in script
    assert len(re.findall(r"That is not a claim that nothing was ever ", block.group(1))) == 2, (
        "a bounded record that is empty is not a claim that nothing ever happened"
    )

    assert "|| [ROUTED_EMPTY_UNEXPLAINED]" in empty, "a missing key says something, never nothing"
    assert re.findall(r"line\(", empty) == ["line("], (
        "every sentence reaches the DOM as a text node (ADR-0042 §4, ADR-0168 §6)"
    )
    assert "innerHTML" not in empty


def test_a_resumed_park_is_not_reported_as_a_turn_that_planned_nothing() -> None:
    """A defect the browser found once ``resume`` reached this page (#1404).

    ``steps`` comes from the plan, and a resume driven from a **recovered** park
    carries ``turn`` ``null`` (ADR-0052 §3) — so it has no plan and no steps, and the
    page wrote "No action was needed." directly above "Done. `smtp` ran.". ADR-0170 §6
    is that the deterministic account is what this system guarantees about what it did,
    so a sentence contradicting it on the same screen is the failure that section
    exists to prevent, arriving from the other direction.

    ``step`` present is that account, which is why the condition reads both members
    rather than inferring one from the other.

    **``routed`` is the third member and the same defect one decision over** (ADR-0197
    §8, §10). A routed pass drives no plan and no step — §1 ends the pipeline at a
    taken route — so ``steps`` is empty and ``step`` is ``null`` on a turn that may
    have just destroyed a belief. Without the third conjunct the page would write "No
    action was needed." directly above "Done. That belief is destroyed.", which is
    #1404 reproduced against a surface #1404 could not reach.

    **``read_confirmation`` and ``read_answer`` are the fourth and fifth, and the same
    defect a third decision over** (ADR-0244 §9). A servicing that parks a read happens
    in context assembly and not in a plan step, so a turn carrying the question can reach
    this renderer with no steps, no step account and no route — and "No action was
    needed." directly above a question the owner is being asked to answer is the same
    contradiction on one screen. A ``declined`` answer is the sharper case: ADR-0170 §4's
    second shape gives it ``turn`` and ``reply`` both ``null``, so every term of the
    original condition is empty on an outcome that recorded a ``DENY``.
    """
    body = _functions(_code("app.js"))["renderOutcome"]

    for member in (
        "outcome.steps.length === 0",
        "outcome.step === null",
        "outcome.routed === null",
        "outcome.read_confirmation === null",
        "outcome.read_answer === null",
    ):
        assert member in body, member
    assert body.count('"No action was needed."') == 1


def test_a_slower_listing_read_cannot_put_an_answered_park_back_on_screen() -> None:
    """Two reads of the listing can be in flight at once — the page starts one as it
    loads, and answering a park starts another — and the slower one finishing last
    would clear the list and re-render the snapshot it took before the answer.

    What that costs is specific: a resolved park back on screen with an approval
    control whose token the engine has already spent, so the owner's next click gets
    ``UnknownContinuationError`` — which ADR-0084 §7 makes emphatically *not* a denial
    — reported as a refusal of something that ran. The questions listing carries the
    same device for the same reason.
    """
    body = _functions(_code("app.js"))["readPending"]

    assert "pendingRun += 1" in body
    assert "run !== pendingRun" in body


def test_one_answer_per_park_and_a_second_click_submits_nothing() -> None:
    """A second ``resume`` on a token the first resolved raises
    ``UnknownContinuationError``, and ADR-0084 §7 is that this is never a denial:
    "nobody ruled on this action".

    So a double click would put "the hub received the request and declined it" on
    screen for an action that had in fact just run. Both controls are disabled for the
    request's own window — either one submits — and both come back, because a request
    that *failed* leaves a row that must still be answerable. ``ask`` disables its own
    button across the same window and for the same reason.
    """
    functions = _functions(_code("app.js"))
    offer = functions["offerApproval"]

    # Both controls take one state, computed in one place, so the pair cannot get out of
    # step with itself — and the state is *derived* from the three sets rather than
    # written beside them, which is what makes a row that is no longer answerable render
    # as one wherever it came from (#1536).
    assert "const out = answering.has(token);" in offer
    assert "const answered = spent.has(token);" in offer
    # **A cancellation already recorded is the third fact that disables the pair**
    # (ADR-0244 §11). All three of ``ReadCancellation``'s members leave the park
    # unanswerable — the question withdrawn, a dispatch stopped part-way, or a park that
    # was already settled — so a pair left enabled over one of them would be the silent
    # refusal this surface spends the most words preventing.
    assert offer.count("disabled = out || answered || gone !== null;") == 2
    assert "} finally {" in offer
    # The park is claimed before the row's own request, so a click on either row of one
    # park starts at most one ``resume``.
    assert "if (answering.has(token) || spent.has(token)) {" in offer
    assert offer.index("answering.add(token);") < offer.index("await answerConfirmation(")
    assert "answering.delete(token);" in offer
    # **And the guarantee is per park rather than per row**, because one park is on
    # screen twice: a turn that parks renders its confirmation with the answer, and the
    # recovery listing renders the same park again — carrying the *same* token, since
    # ``pending_confirmations`` "reuses that entry's token rather than minting a second"
    # for a binding the engine already holds. Two rows, one park, and a per-row lock
    # would let the second one submit while the first was in flight.
    answering = functions["answerConfirmation"]
    assert "if (spent.has(token)) {" in answering
    assert "spent.add(token);" in answering
    # Given back on **two** paths and no third: a refusal the gateway *answered*, which
    # is a response this browser read, and an answer whose own member says the question
    # may still stand (ADR-0244 §9's ``OPERATION_CHANGED`` and ``UNAVAILABLE_NOW`` —
    # adversarial review, round 1). Every ending that read no reply keeps the token
    # (:func:`test_an_abandoned_park_answer_does_not_give_the_token_back_on_the_act`),
    # and round 4's first blocker was that the rejection path did not.
    assert answering.count("spent.delete(token);") == 2
    assert "READ_ANSWERS_LEAVING_THE_QUESTION.has(body.outcome.read_answer)" in answering
    assert answering.index("if (body === null) {") < answering.index("spent.delete(token);")


def test_a_stalled_tidy_up_cannot_silently_refuse_another_parks_answer() -> None:
    """``fetch`` carries no deadline of its own, so anything a page holds across a
    request it cannot bound is held for as long as that request hangs.

    A page-wide answer lock held across the post-answer listing read would therefore
    make one stalled read swallow the owner's answer to every *other* park — with no
    request sent and nothing said, which is the one failure a confirmation surface
    cannot have. The guard is claimed per token, and the read that tidies up what is
    left on screen happens after it and is waited on by nothing else.

    **Nor by the row that sent the answer**, which is round 2's finding and the same
    argument one caller out: the tidy-up is *started* and never awaited, so a resume
    that succeeded and a listing read that then hung cannot leave every row of that park
    announcing an answer still in flight. Nothing depends on the read — the outcome is
    already on screen — and what is left is which rows the listing still holds.
    """
    script = _code("app.js")
    body = _functions(script)["answerConfirmation"]

    assert "let answering = " not in script
    # No `finally` here, which is the shape a page-wide lock takes: the guard is given
    # back on the two named refusal paths and on neither of them is the tidy-up waited
    # on first.
    assert "} finally {" not in body
    assert "await readPending(" not in body
    assert body.index("spent.add(token);") < body.index("readPending(true);")
    assert body.index('"/confirmation/resume"') < body.index("readPending(true);")


def test_a_park_answer_that_never_settles_is_ended_by_the_owner_and_by_no_clock() -> None:
    """The decision #1536 asks a taker to make, pinned where changing it would have to
    pass this test: an automatic deadline on a park's answer is **declined**, and the
    remedy is the control ``ask`` already uses.

    **The argument is the one #1500 settled, and ADR-0177 §9 is what carries it here.**
    §9 gives ``resume`` "the same budget a turn is given at this surface" — no
    ``Settings`` field, no second figure — and that budget is ``server.py``'s
    ``_TURN_BUDGET``, which reaches the browser in no header, no value and no setting. A
    page-side deadline would be a second number able to disagree with it, and one short
    enough to be useful would abandon a healthy resumed turn that was thinking and
    announce that its outcome was not known.

    ``HEAD_DEADLINE_MILLISECONDS`` does not transfer either, for the reason it does not
    transfer to an ask: it is defensible because it covers "a round trip and an
    in-process table read, and nothing else", and a ``/confirmation/resume`` head is
    written after the whole resumed turn.
    """
    script = _code("app.js")
    functions = _functions(script)

    # Still one clock, and still the delivery stream's.
    assert len(_page_clocks(script)) == 1
    assert "setInterval" not in script
    assert "AbortSignal" not in script
    for name in ("relay", "answerConfirmation", "offerApproval", "parkWords"):
        body = functions[name]
        for clock in ("setTimeout", "HEAD_DEADLINE_MILLISECONDS", "SILENT_CADENCES", "cadence"):
            assert clock not in body, (name, clock)
    # What ends the wait is a control, built beside the pair it hands back.
    offer = functions["offerApproval"]
    assert "refreshParks();" in offer
    assert 'stop.textContent = "Stop waiting";' in offer
    assert "stopping.abort();" in offer
    assert "stopping = new AbortController();" in offer
    # It aborts and it sends nothing: a control that re-sent the answer would be the
    # silent retry ADR-0168 §9 forbids, wearing a button's clothes.
    handler = offer[offer.index('stop.addEventListener("click"') :]
    assert "answerConfirmation(" not in handler[: handler.index("\n  });")]


def test_an_abandoned_park_answer_asserts_no_outcome_and_offers_the_pair_again() -> None:
    """The consent question #1536 asked, answered again now that ADR-0198 has landed.

    ADR-0177 §7's fourth clause makes an answer whose reply was never read an outcome
    that is **not known** — "the request was sent and no response was read" — and
    ADR-0139 §4 forbids the surface inferring the state from the unresolved act, in
    either direction. **That prohibition is about what the page asserts, and this branch
    still asserts nothing**: ``strand`` records that the answer went unread, the row says
    so, and the sentence beside it says the action may have been carried out.

    What #1612 additionally did — keep the token spent for the life of the page — was
    never that prohibition. It was the consequence of a second ``resume`` raising
    ``UnknownContinuationError``, which ``_relay_fault`` renders as
    ``assistant-declined`` and this page read as "The hub received the request and
    declined it": a denial announced for an action that ran, which ADR-0084 §7 refuses in
    terms. ADR-0198 §1 ends that — a token whose binding is settled restates the recorded
    answer — so the token comes back and the pair is answerable again (#1621).
    """
    script = _code("app.js")
    body = _functions(script)["answerConfirmation"]
    caught = body[body.index("} catch (_) {") : body.index("if (body === null) {")]

    # **What decides it is that no reply was read, not which way the reply was lost.**
    # Round 4's first blocker was a branch: the owner's abort kept the token and an
    # ordinary rejection released it, though ADR-0177 §7's fourth clause covers both in
    # one sentence. So there is no branch left — only the wording differs.
    assert "strand(token);" in caught
    assert "GATEWAY_GONE" not in caught
    assert caught.index("strand(token);") < caught.index("stopping.signal.aborted")
    assert (
        "recordAnswerAccount(token, stopping.signal.aborted ? PARK_UNRESOLVED : PARK_LOST);"
        in caught
    )
    assert "unresolved" not in _functions(script)["relay"]


def test_the_two_halves_of_stranding_a_token_are_one_act() -> None:
    """#1621. Giving the token back and recording that its answer went unread are only
    safe together, so they are one function and every not-known ending calls it.

    Half of it alone is a defect in either direction. A token given back without the
    record re-offers the pair beside a row that says nothing — the silent surface #1536
    is about with the sign reversed, since the owner reads an enabled control as the page
    announcing that nothing happened, which is exactly the inference ADR-0139 §4 refuses.
    The record without the token back is the state ADR-0198 was decided to end.

    It takes the token and no reason: which ending it was is said once, at the ending, in
    the fault line beside the row, and what is still true is the row's own sentence.
    """
    script = _code("app.js")
    functions = _functions(script)

    assert "function strand(token) {\n  unresolved.add(token);\n  spent.delete(token);\n}" in script
    # The three branches that read no outcome, and no fourth: the one both endings that
    # read no reply at all share — the owner's abort and the connection's own failure,
    # which ADR-0177 §7's fourth clause does not distinguish — the refusal §7's third
    # clause leaves not known, and the ``2xx`` whose body carried no outcome this page
    # could render.
    assert len(re.findall(r"\bstrand\(token\);", script)) == 3
    assert len(re.findall(r"\bstrand\(", functions["answerConfirmation"])) == 3


def test_a_listing_read_never_re_offers_a_park_whose_answer_is_unaccounted_for() -> None:
    """Round 7's blocker: a recovery snapshot cannot exclude a resume still in transit.

    An earlier revision handed the token back wherever the listing still offered the
    park, on the reading that ``_resolve_park`` records the answer and evicts the
    binding under the one lock ``_pending_confirmations`` also takes — so a park
    observed pending is one no resume had resolved. That is true and insufficient: the
    lock establishes that no resume *has* resolved the park, never that none *will*.

    An abandoned answer is one that may still be in flight, so a listing read that
    reaches the lock first legitimately returns the park as pending, and a second
    ``resume`` then races the first. Whichever loses raises ``UnknownContinuationError``,
    which reaches this page as ``assistant-declined`` and renders as a denial ADR-0084 §7
    refuses in terms — "never a denial". A consent token is the wrong place to carry that
    race and this surface cannot close it: ``resume`` idempotent per binding, or recovery
    minting a token that invalidates an outstanding one, is reachable from nowhere under
    ``interfaces/gateway/``. That is #1536's residual and is filed as #1621.

    **ADR-0198 closed that at the seam it belonged to, and this prohibition survives it
    whole** (#1621). A settled binding restates rather than raises, so the race is gone —
    but a listing snapshot is still not evidence about a request in flight, and the page
    still un-spends nothing on one. What gives a token back is ``strand``, at the ending,
    on this page's own record of what it did; and the listing could not answer the case
    ADR-0198 exists for in any event, since a settled binding is never listed and never
    re-minted (§4, ADR-0052 §1 step 2).
    """
    script = _code("app.js")
    functions = _functions(script)
    offer = functions["offerApproval"]

    # Nothing un-spends a token on a listing's evidence — not in the function that
    # builds a row from one, not in the read that renders the listing, and not in the
    # render of a turn's own confirmation.
    assert "unresolved.delete" not in script
    for named in ("offerApproval", "readPending", "renderConfirmation"):
        assert "spent.delete" not in functions[named], named
        assert "strand(" not in functions[named], named
    # The token is given back in exactly three places, and each is an ending this page
    # reached by reading a response or failing to: ``strand``, for the four not-known
    # endings; the one arm that is known *not* to have landed; and the one *answer* whose
    # own member says the question may still stand (ADR-0244 §9). The third is still not
    # a listing's evidence — it is the hub's own account of what that answer did, read
    # off ``read_answer`` and off nothing the listing said.
    assert len(re.findall(r"spent\.delete\(", script)) == 3
    assert "spent.delete(token);" in functions["answerConfirmation"]
    assert "spent.delete(token);" in functions["strand"]
    # Read as a use rather than as a mention, because ``_functions`` attributes the
    # declaration itself — it sits between two functions — to whichever one precedes it.
    assert {name for name, body in functions.items() if "unresolved." in body} == {
        "offerApproval",
        "answerConfirmation",
        "strand",
    }
    # ``offerApproval``'s only use is the read that picks the row's sentence.
    assert re.findall(r"unresolved\.\w+", offer) == ["unresolved.has"]
    # And ``answerConfirmation``'s is the one read that separates a first answer from a
    # second — taken *before* the claim, so it cannot see this request's own record.
    assert re.findall(r"unresolved\.\w+", functions["answerConfirmation"]) == ["unresolved.has"]


def test_a_row_holding_a_spent_token_never_offers_a_control_that_submits_nothing() -> None:
    """#1536's residual, which is worse than the disabled pair it was found beside.

    ``pending_confirmations`` "reuses that entry's token rather than minting a second"
    for a binding it already holds, so pressing **Confirmations** renders the park again
    with the **same** token — and ``answerConfirmation`` returns early on
    ``spent.has(token)``. An enabled pair over a spent token therefore submits nothing
    at all, which is the silent refusal this surface spends the most words preventing.

    Closed at the render rather than at one path into it: the pair's enabled state is
    computed from ``spent``, so every route that leaves a token spent renders the row
    the same way and says which of the two things it means.

    **``rowWords`` sits in front of it rather than inside it** (ADR-0244 §11). A park
    this page cancelled, or is cancelling, carries a sentence from a different
    enumeration — one fixed statement per ``ReadCancellation`` member — and folding a
    three-member ``core`` vocabulary into a five-state page-local rule would leave a
    member added to either having to be read against the other's states. Both take the
    member or the flag and never the handle, which is §8's rule holding across the pair.
    """
    script = _code("app.js")
    offer = _functions(script)["offerApproval"]
    words = _functions(script)["parkWords"]
    outer = _functions(script)["rowWords"]

    assert offer.rstrip().endswith("parkRows.add({ node: item, settle });\n  settle();\n}")
    assert "const answered = spent.has(token);" in offer
    assert "const stranded = unresolved.has(token);" in offer
    assert "said.textContent = rowWords(" in offer
    assert "parkWords(waiting, out, answered, stranded)" in offer
    assert 'said.hidden = said.textContent === "";' in offer
    # Total over the four states a row can be in, and it takes no token: ADR-0177 §8
    # has the front end render the continuation nowhere.
    assert "token" not in words
    assert words.count("return") == 4
    assert "token" not in outer
    # Four states: the act's own answer, the act in flight, an act whose reply went
    # unread — where the row says nothing, because every sentence `parkWords` has for
    # this state ends "nothing was cancelled" (round 6) — and the park's own account.
    assert outer.count("return") == 3
    assert 'return unread ? "" : otherwise;' in outer


def test_an_abandoned_park_answer_says_which_of_the_three_outcomes_it_got() -> None:
    """ADR-0139 §4's exactly three, at the surface ADR-0177 §7's fourth clause adds a
    third producer of.

    A row that simply came back enabled would be announcing by omission that nothing
    happened, and one that said "the gateway did not answer" would be announcing a
    transport failure the page did not observe. So the sentence says the outcome is not
    known, says what was *not* done — nothing re-sent, nothing cancelled — and names the
    act that settles it, which is the read ADR-0084 §7 calls the remedy.

    The three sentences are distinct because the states are: an answer that is out, one
    whose fate is unknown, and a row whose park was answered from this page.
    """
    script = _code("app.js")

    unresolved = _constant(script, "PARK_UNRESOLVED")
    lost = _constant(script, "PARK_LOST")
    for said in (unresolved, lost):
        assert "not known" in said
        assert "Nothing was re-sent and nothing was cancelled." in said
        # It does not promise the answer did not land, and does not promise it did.
        assert "may have carried the action out" in said
        assert "may never have received the " in said
        # Both reach the owner's account of where the park can be answered now, and
        # reach the *same* one — the ask's own device, so two endings cannot drift into
        # two different instructions.
        assert said.rstrip().endswith("PARK_WHERE_NOW")
    # Their openings are what differ, because only one of them was an act of the owner's.
    assert unresolved.startswith('\nconst PARK_UNRESOLVED =\n  "You stopped waiting')
    assert "You stopped waiting" not in lost
    assert "connection carrying that answer failed" in lost

    # **The route back states answerability and infers no resolution from an absence**,
    # which is round 4's second blocker. ``AuditTrail.pending_confirmation`` answers
    # ``None`` for a resolved binding *and* for a ``CONFIRM`` whose origin was never
    # recorded, where "the step stays durably ``AWAITING_APPROVAL`` with its ``CONFIRM``
    # unresolved and its row intact… The park is unanswerable, not erased." A page
    # reading absence as a resolution would tell the owner the opposite of the state.
    route = _constant(script, "PARK_WHERE_NOW")
    assert "Press Confirmations" in route
    assert "can still be answered" in route
    assert "nothing here calls it resolved" in route
    assert "was answered" not in route

    # **And it no longer sends the owner to a reload** (#1621), which is the whole of
    # what ADR-0198 changed here. The reload was #1612's answer to round 7 and it could
    # never reach the case the page most needs: a settled binding is never listed and
    # never re-minted (ADR-0198 §4, ADR-0052 §1 step 2), so where the first answer *did*
    # land no reload hands the park back. What can ask is the token, and after §1 a
    # ``resume`` presenting it restates rather than raises.
    assert "Reloading" not in route
    assert "after a reload" not in route
    assert "will not offer that park again" not in route

    # **And it promises no control, because at this point there may be none.** A row is
    # what carries the pair, and a row built from the recovery listing is replaced on
    # the next read — so a park whose first answer landed is dropped from the listing and
    # its row with it (#1665). What is promised is scoped to a park still on screen,
    # which is true whether or not the listing kept it.
    assert "Where this park is still on screen" in route

    # And the wait says there is no deadline, rather than implying one.
    waiting = _constant(script, "PARK_WAITING")
    assert "puts no deadline on it" in waiting
    answered = _constant(script, "PARK_ANSWERED")
    assert "no longer the live one" in answered
    assert len({unresolved, lost, waiting, answered, route}) == 5


def test_the_long_account_of_a_re_offer_is_the_rows_and_not_the_endings() -> None:
    """What driving the page settled, and the file's own division is what decides it.

    Every ending's sentence is written into the panel's fault slot and the row's is
    written beside the pair, so a clause both carry lands on screen twice. ``PARK_ROUTE_BACK``
    was short enough for that to pass unnoticed and this account is not — at a desktop
    width the whole of it rendered twice, three inches apart, and a consent surface that
    is not read is the failure this file spends the most words preventing.

    So the split follows the division the file already keeps: **what happened** is said
    once, at the ending, in the fault line — and **what is still true** is what the row
    carries. The long account of what pressing the pair now means is a fact about the
    pair, so it goes where the pair is; the ending carries the short one, which has to be
    true even where no row survived the listing read that followed it (#1665).
    """
    script = _code("app.js")

    row = _constant(script, "PARK_ASK_AGAIN")
    ending = _constant(script, "PARK_WHERE_NOW")

    # **Three things the row's account has to say, and each is a way of getting it
    # wrong.** That a second answer performs nothing (ADR-0198 §1, ADR-0044 §2b) —
    # without which the pair reads as a way to carry the action out twice. That a
    # recorded answer is the one that stands — without which the pair reads as a way to
    # *change* an answer, which is an act the engine does not have. And that the
    # assistant may hold neither the park nor its answer any longer (§4), which is the
    # arm this page must not render as a refusal.
    assert "answered once" in row
    assert "never carries the action out a second time" in row
    assert "the answer already recorded, and that one stands" in row
    assert "is not a way to change an answer" in row
    assert "send the answer you want rather than a question" in row
    assert "it can no longer say what became of" in row
    assert "rather than call it refused" in row

    # Only the row carries it, and only the endings carry the other.
    assert "PARK_ASK_AGAIN" in _constant(script, "PARK_NOT_KNOWN")
    for named in (
        "PARK_UNRESOLVED",
        "PARK_LOST",
        "PARK_REFUSAL_NOT_KNOWN",
        "PARK_REFUSAL_AFTER_UNKNOWN",
        "PARK_REPLY_UNREADABLE",
    ):
        said = _constant(script, named)
        assert said.rstrip().endswith("PARK_WHERE_NOW"), named
        assert "PARK_ASK_AGAIN" not in said, named
    assert "PARK_WHERE_NOW" not in _constant(script, "PARK_NOT_KNOWN")
    assert ending != row


def test_a_stalled_tidy_up_after_an_abandoned_answer_is_not_waited_on() -> None:
    """The failure being closed, one ordering over.

    ``readPending`` reaches the same unbounded ``relay``, so awaiting it on the
    abandoned path would let one stalled read hold the pair disabled exactly as the
    stalled answer did — #1536 rebuilt inside its own fix. It is started and not waited
    on.

    **The order it is asserted in no longer carries the sentence's survival**
    (adversarial review's round 8). It used to: the account was written into the panel's
    fault slot and this read clears that slot on its way in. The account now has a node
    of its own that no listing read touches, so what the order buys is only that the
    row's state settles before the sentence beside it — and it is still pinned, because
    an ending that wrote the account first would be one nobody had thought about.

    ``readPending``'s own unbounded ``relay`` is otherwise left alone, and that is the
    third question #1536 asks: it disables no control and claims no token, so a listing
    read that never settles strands nothing — the previous list stays on screen and the
    button that asked for it is still pressable.
    """
    body = _functions(_code("app.js"))["answerConfirmation"]

    assert "await readPending(false);" not in body
    assert "readPending(false);" in body
    assert body.index("readPending(false);") < body.index(
        "recordAnswerAccount(token, stopping.signal"
    )


def test_one_parks_two_rows_take_one_state_and_only_one_of_them_submits() -> None:
    """The round-1 adversarial finding, which is #1536's residual surviving inside its
    own fix.

    One park is on screen twice — a turn that parks renders its own confirmation, and
    the recovery listing renders the same park again, "with the *same* token, because
    ``pending_confirmations`` reuses that entry's token rather than minting a second".
    A per-row state therefore left the *other* row enabled over a token
    ``answerConfirmation`` returns early on: a control that submits nothing, which is
    exactly the failure this change exists to close.

    So the rows are registered and every one of them is told when the park's state
    moves. The registry is pruned by ``isConnected`` and by nothing else, which is the
    question ``abandonAsk`` asks of the answer panel and for its reason: ownership of
    what is on screen is a fact about *now*, and ``clearNode`` replaces a whole listing
    on every read.

    **``cancelRead`` is the fourth caller and the park's state moves twice there too**
    (ADR-0244 §11): once when the act goes out, so both rows say it is being cancelled
    rather than one going quiet, and once at the ending, so both carry the statement for
    the member that came back. A cancellation registered on one row and not the other
    would leave the second offering a control over a park that is gone, which is the
    round-1 finding this test is named for, one act over.
    """
    script = _code("app.js")
    functions = _functions(script)
    refresh = functions["refreshParks"]

    assert "parkRows.forEach((row) => {" in refresh
    assert "if (row.node.isConnected) {" in refresh
    assert "row.settle();" in refresh
    assert "parkRows.delete(row);" in refresh
    # Reached where the park's state moves, and from nowhere else — a row is never left
    # rendering a fact that has moved, and nothing re-renders on a schedule.
    # Reached where the park's state moves, and where a container that holds rows is
    # replaced — those two and nothing else. A registry pruned only on a state
    # transition retained every detached row a listing read had ever rendered, which
    # adversarial review found on round 2.
    assert {name for name, body in functions.items() if "refreshParks();" in body} == {
        "offerApproval",
        "readPending",
        "renderOutcome",
        "cancelRead",
    }
    for name in ("readPending", "renderOutcome"):
        cleared = functions[name]
        assert cleared.index("clearNode(") < cleared.index("refreshParks();"), name
    offer = functions["offerApproval"]
    # Two, and no third: the park claimed and the park settled. The third used to be a
    # token handed back on a listing read, which round 7's blocker removed — a recovery
    # snapshot cannot exclude a resume still in transit, so nothing on this page moves a
    # park out of the unaccounted-for state and there is no such transition to announce.
    assert offer.count("refreshParks();") == 2
    assert "parkRows.add({ node: item, settle });" in offer
    # And the second row says an answer is on its way rather than that the park was
    # answered, because ``spent`` is claimed before the request goes out and cannot tell
    # the two apart on its own.
    assert "PARK_ELSEWHERE" in _functions(script)["parkWords"]
    elsewhere = _constant(script, "PARK_ELSEWHERE")
    assert "already on its way" in elsewhere
    assert "not the live control" in elsewhere


def test_a_refusal_the_gateway_answered_is_not_always_one_it_did_not_land() -> None:
    """Round 5's blocker, and it is ADR-0177 §7's third clause read as written.

    Which of ADR-0139 §4's three an act gets is read "from ADR-0168 §9's distinction and
    from nothing else: a request the hub received and declined is **known not to have
    landed**; a transport failure between the gateway and the hub is **not known**". A
    ``502 hub-unreachable`` is the second — ``_relay_fault`` raises it from a
    ``TransportError`` the wire client can raise *after* the call was delivered, so the
    hub may have run the action with only the reply lost. Releasing the continuation
    there lets a second ``resume`` go out on a token the first resolved, which
    ADR-0084 §7 makes emphatically not a denial and the gateway relays as
    ``assistant-declined``.

    ``relay`` hands its caller the body it already read rather than widening its return,
    because ``null`` means "refused, condition already on screen" at every other call
    site and re-reading all of them is its own change (#1619).
    """
    script = _code("app.js")
    functions = _functions(script)
    relay = functions["relay"]
    answering = functions["answerConfirmation"]

    # Told only where the caller asked to be, and only for a refusal — a successful
    # response returns above this.
    assert "if (noticed !== undefined) {" in relay
    assert "noticed(body);" in relay
    assert relay.index("const body = await readBody(response);") < relay.index("noticed(body);")
    # **And before #2404's session guard, which `refused` sits after.** A refusal
    # answered to a request whose session has since ended is still *classified* for the
    # caller that asked to be told — it is a fact about the act — and is no longer
    # *displayed*, because displaying it reveals the panel beside the bootstrap form and,
    # for the two session conditions, ends the session the owner has just re-entered.
    # Withholding it instead reads as "a refusal this page cannot classify at all", which
    # takes the not-known branch below and strands a consent token over a request the
    # gateway refused at the door. Adversarial review of #2404, round 1, `major`.
    assert relay.index("noticed(body);") < relay.index("refused(panelId, body, response.status);")
    # **And nothing is written in its place.** Two rounds answered that in opposite
    # directions — round 3: a page whose ceremony outlived its session is looking at the
    # panel it pressed the control in, and telling it nothing leaves the owner believing
    # a destruction happened; round 4: a panel's fault slot is one slot, so a condition
    # written there after a newer session has re-filled that panel sits above rows it is
    # not about. A per-panel slot cannot be both, and neither ADR settles it, so what
    # ships is the uniform rule with no race in it and #2451 carries the question.
    withheld = relay[relay.index("if (!sameSession(half, era)) {") :]
    assert withheld[: withheld.index("}")].strip().endswith("return null;")
    # And exactly one caller asks. Every other entry point reaching `relay` is unchanged
    # by this, which is the whole reason it is a callback.
    # And exactly one call site passes it, asserted over the *shape* rather than over
    # the identifier: "noticed by" is owner-facing text this file renders for a
    # notification's producer, so a name search counts two unrelated functions.
    # Three: ``relay``'s own trailing parameter and the two call sites that fill it.
    # **The second is the cancellation act** (ADR-0244 §11, adversarial review's round 1),
    # and it asks for the same reason: it mutates, so `FAULTS`'s "nothing was asked" is a
    # claim about a request the hub may in fact have carried out, and the difference
    # between two refusals is what decides whether this page may say the question stands.
    assert len(re.findall(r"\bnoticed\b\s*\)", script)) == 3
    assert "async function relay(half, path, payload, panelId, stopping, noticed) {" in script
    assert "const noticed = (named) => {" in answering
    assert "const noticed = (named) => {" in _functions(script)["cancelRead"]
    # **`act`'s own test, copied rather than re-derived**: a condition this page reads as
    # unknown, *or* a refusal carrying no readable condition at all. ``readBody``
    # normalises a truncated, malformed or proxy-substituted body to ``{}``, and an
    # absent ``fault`` is not evidence the request never landed — "a refusal whose
    # condition this page cannot read is a refusal it cannot classify, and ADR-0139 §4's
    # third outcome is what an unclassifiable one is".
    assert 'const named = refusal !== null && typeof refusal.fault === "string";' in answering
    assert "if (unaccounted || !named || UNKNOWN_FAULTS.has(refusal.fault)) {" in answering
    kept = answering[answering.index("if (unaccounted ||") :]
    unknown = kept[: kept.index("\n    }\n")]
    assert "strand(token);" in unknown
    assert "spent.delete(token);" not in unknown
    assert answering.index("UNKNOWN_FAULTS.has(") < answering.index("spent.delete(token);")
    # The same two-armed shape the grant surface already carries, so neither can be
    # loosened without the other looking wrong beside it.
    assert 'const named = typeof body.fault === "string";' in functions[_ACT_SITE]


def test_a_reply_this_page_cannot_render_resolves_nothing() -> None:
    """Rounds 9 and 10, which are round 8's blocker one and two steps in.

    ``asObject`` answers ``{}`` for a ``2xx`` body that parsed to something that is not
    an object; a well-formed object may still be missing ``outcome``; and an ``outcome``
    that *is* an object may still not carry what ``renderOutcome`` reads. A
    proxy-substituted or reassembled ``200`` is the reachable case, the same one round 6
    admitted for a refusal. ``renderOutcome`` was called **outside** this function's
    ``try``, so any of those threw there: the token stayed ``spent`` and never
    ``unresolved``, the row's ``finally`` cleared ``answering``, and every row of the
    park read "That park has been answered from this page" for an outcome nothing had
    read.

    **The render is the test, and not a shape check.** Round 9 checked that the outcome
    was an object and round 10 walked ``{}`` straight past it — any enumeration of
    members needs re-deriving every time ``renderOutcome`` reads a new one, and getting
    it wrong reinstates the same false resolution silently. What the page needs to know
    is whether it can put the answer on screen, and running the render is what answers
    that. A defect in ``renderOutcome`` itself lands here too, reported as not known:
    the conservative direction, and the right one for a consent surface, because the
    alternative is not a truthful crash but a park announced as answered on the strength
    of an exception.

    A read response is not by itself a landed one. ADR-0177 §7's third clause sorts a
    *refusal* into landed or not-known and says nothing that turns an unrenderable
    success into a resolution, so ADR-0139 §4's third outcome is what this is — and the
    ending is the one every other not-known arm takes.

    **Said through ``couldRenderOutcome`` since #2006**, which is #1622's "one check,
    shared" reaching the site the rule was worked out on. The questions are the ones the
    inline ``try`` was pinned for and they are asked of the new shape: that the render is
    guarded rather than reached directly, and that the three statements of this surface's
    own ending follow a render that failed and nothing else. The ending **records which
    ending it was** rather than choosing a sentence, because a read this page cancelled
    ends every one of these four ways and what the screen then owes depends on what
    ``cancel_read`` answered — which may not have happened yet (ADR-0244 §11, round 8).
    What is no longer here is
    ``show("answer", false)`` — the guard hides the panel *and* clears it, which is what
    the ``try`` named as its intent and did not do.
    """
    script = _code("app.js")
    answering = _functions(script)["answerConfirmation"]

    # The render is guarded, and the guard is what decides the branch — not a `try` this
    # function keeps for it, and not a direct call.
    assert "renderOutcome(" not in answering
    assert "!couldRenderOutcome(body.outcome, " in answering
    guarded = answering[answering.index("!couldRenderOutcome(body.outcome, ") :]
    assert guarded[: guarded.index("\n")].endswith("null)")
    # No shape check stands in front of it: enumerating members is the thing round 10
    # refuted, so a re-introduced list would be the same defect wearing a guard.
    assert "Array.isArray(outcome)" not in answering
    # The ending is the not-known one, in the order every other arm uses, and it follows
    # the failed render rather than standing anywhere else in the function.
    failed = guarded[: guarded.index("READ_ANSWERS_LEAVING_THE_QUESTION")]
    for step in (
        "strand(token);",
        "readPending(false);",
        "recordAnswerAccount(token, PARK_REPLY_UNREADABLE);",
    ):
        assert step in failed, step
    # In the order every other arm uses, so the row's state settles before the sentence
    # beside it. The account's *survival* no longer turns on this: it is written into a
    # node of its own that `readPending` does not touch (round 8).
    assert failed.index("strand(token);") < failed.index("readPending(false);")
    assert failed.index("readPending(false);") < failed.index("recordAnswerAccount(token, PARK_")
    assert "spent.delete" not in failed
    # And the render is not reached again on the way out: the guard rendered it or it
    # took the branch above, so there is no second call to fall through to.
    assert answering.count("couldRenderOutcome(") == 1

    # Its own sentence, because the cause is its own: the gateway answered, and the
    # answer is what could not be read.
    said = _constant(script, "PARK_REPLY_UNREADABLE")
    assert "could not read an outcome from" in said
    assert "not known" in said
    assert "Nothing was re-sent and nothing was cancelled." in said
    assert said.rstrip().endswith("PARK_WHERE_NOW")
    # It does not borrow a cause it has not established.
    for attributed in ("You stopped waiting", "connection carrying", "gateway refused that answer"):
        assert attributed not in said, attributed


def test_a_park_whose_answer_went_unread_is_answerable_again_and_says_what_that_means() -> None:
    """#1621's softer half, which #1612 shipped closed and ADR-0198 makes safe to open.

    Before it, a token whose answer this page never read back stayed spent for the life
    of the page: a second ``resume`` on a binding the first had resolved raised
    ``UnknownContinuationError``, which reaches this page as ``assistant-declined`` and
    reads as "The hub received the request and declined it" — the denial ADR-0084 §7
    refuses in terms. ADR-0198 §1 retains the binding and restates the recorded answer
    instead, so the pair can come back.

    **What it must not come back as is a silent statement that nothing happened.** A row
    that simply re-enabled would be announcing by omission the one thing ADR-0139 §4
    forbids a surface to assert about an unresolved act, so the enabled pair carries a
    sentence saying what pressing it now does — and, because a park is answered once
    (ADR-0044 §2b), that it is not a way to change an answer that landed.
    """
    script = _code("app.js")
    words = _functions(script)["parkWords"]

    # The row is stranded and answerable, which before #1621 was not a state: ``spent``
    # and ``unresolved`` moved together, so every stranded row was a disabled one.
    assert 'return stranded ? PARK_NOT_KNOWN : "";' in words
    said = _constant(script, "PARK_NOT_KNOWN")
    assert "not known" in said
    assert "Nothing was re-sent and nothing was cancelled." in said
    assert said.rstrip().endswith("PARK_ASK_AGAIN")
    # The pair's enabled state is still computed from the park's own sets, so a row that
    # is answerable again is answerable wherever it was built — and a cancellation this
    # page recorded is the one further fact that keeps it disabled (ADR-0244 §11).
    offer = _functions(script)["offerApproval"]
    assert "const answered = spent.has(token);" in offer
    assert offer.count("disabled = out || answered || gone !== null;") == 2


def test_a_refusal_of_a_second_answer_is_never_read_as_a_denial_of_the_first() -> None:
    """The arm the re-offer opens, and the one it would be worst to get wrong (#1621).

    Where the assistant holds neither the park nor its answer any longer — a restart, a
    binding ``pending_confirmations``' own reconciliation evicted (ADR-0052 §2), or a
    settled record discarded under ADR-0198 §4's bound — ``resume`` raises
    ``UnknownContinuationError``. ``_relay_fault`` renders every ``AssistantError`` as
    ``assistant-declined`` and ``FAULTS`` reads that as "The hub received the request and
    declined it": a denial announced for an action that may well have run, which
    ADR-0084 §7 refuses in terms and which is what round 7 blocked #1612 over.

    A refusal of the **second** request establishes nothing about the **first**, so the
    branch is decided on this page's own record and not on the condition — the condition
    is about the wrong request. It is over-cautious in exactly one arm, a park refused
    past its deadline by ``StepRunner._check_fresh`` (ADR-0198 §5), and for a consent
    surface that is the right direction.
    """
    script = _code("app.js")
    answering = _functions(script)["answerConfirmation"]

    assert "if (unaccounted || !named || UNKNOWN_FAULTS.has(refusal.fault)) {" in answering
    # ``unaccounted`` is read first, so a named condition can never reach the
    # known-not-landed arm on a re-answer.
    guard = answering[answering.index("if (unaccounted ||") :]
    assert guard.index("strand(token);") < guard.index("spent.delete(token);")
    # And it gets its own sentence, because ``PARK_REFUSAL_NOT_KNOWN``'s reasoning — the
    # failure was between the gateway and the hub, or the condition could not be read —
    # is false of a condition this page read perfectly well.
    said = _constant(script, "PARK_REFUSAL_AFTER_UNKNOWN")
    assert "does not say what" in said
    assert "not a park it declined" in said
    assert "still not known" in said
    assert said.rstrip().endswith("PARK_WHERE_NOW")
    assert said != _constant(script, "PARK_REFUSAL_NOT_KNOWN")


def test_a_re_answered_park_never_claims_the_record_is_the_answer_just_sent() -> None:
    """A ``resume`` that resolves a recovered park and one that restates a settled
    binding come back in the **same** shape — ``turn`` ``None``, ``routed`` ``None``,
    ``reply`` ``None``, ``reply_degraded`` ``False``, a ``step`` — which is ADR-0170 §4's
    second shape that ADR-0198 §2 obeys rather than widens.

    So nothing on the wire tells the page which it read, and the page does not guess. The
    one structural tell it could reach for — a resume whose outcome names no conversation
    and reports no degraded capture — is an inference from the members the body does
    **not** carry, which is the move ADR-0139 §4 spends five clauses refusing; and
    manufacturing the fact in ``server.py`` would be the gateway authoring a claim the
    engine did not make (ADR-0168 §1). ADR-0198 §7 rules the engine lane touches no file
    under ``interfaces/`` and adds no such member, so there is nothing to read.

    What the page does hold is a fact about **its own** history: it knows this token
    already carried an answer whose reply it never read. That is what it says.
    """
    script = _code("app.js")
    answering = _functions(script)["answerConfirmation"]

    # Read from the page's own record, and read **before** the claim below it — ``strand``
    # writes ``unresolved`` at an ending, so a value read later could be this request's
    # own record rather than the earlier one's.
    assert "const unaccounted = unresolved.has(token);" in answering
    assert answering.index("const unaccounted =") < answering.index("spent.add(token);")
    # Nothing about the body decides it. These are the members a structural guess would
    # have had to read, and none of them is read here.
    for guessed in ("capture_degraded", "conversation_id", "reply_degraded", "outcome.reply"):
        assert guessed not in answering, guessed
    # The caveat is handed to the render rather than appended after it: ``renderOutcome``
    # clears its panel on the way in, and a caveat that changes how everything below it
    # reads belongs above them. Handed **through** the guard since #2006, which carries it
    # untouched — a guard that dropped it would render a re-answered park's outcome with
    # nothing above it saying which of the two answers is on screen.
    caveated = "unaccounted ? PARK_SETTLED_AFTER_UNKNOWN : null"
    assert f"!couldRenderOutcome(body.outcome, {caveated})" in answering
    guard = _functions(script)["couldRenderOutcome"]
    assert "function couldRenderOutcome(outcome, provenance) {" in guard
    assert "renderOutcome(outcome, provenance);" in guard
    render = _functions(script)["renderOutcome"]
    assert "function renderOutcome(outcome, provenance) {" in render
    assert render.index("clearNode(body);") < render.index("if (provenance) {")
    assert render.index("if (provenance) {") < render.index("if (outcome.capture_degraded) {")
    # It is passed and never derived: nothing in the renderer reads a member to decide
    # where the outcome came from.
    assert "line(body, provenance" in render

    # The sentence claims neither reading. It says the answer shown is the one the
    # assistant has **recorded**, that it may be the earlier answer rather than the one
    # just sent, and that this browser cannot tell which.
    said = _constant(script, "PARK_SETTLED_AFTER_UNKNOWN")
    assert "never read back" in said
    assert "the assistant has recorded" in said
    assert "may be that earlier" in said
    assert "cannot tell which of the two" in said
    # And the row carries it too, so a park re-answered from one row does not tell the
    # other that it was simply answered.
    assert (
        "return stranded ? PARK_SETTLED_AFTER_UNKNOWN : PARK_ANSWERED;"
        in _functions(script)["parkWords"]
    )


def test_a_rows_own_line_never_attributes_an_ending_to_the_owner() -> None:
    """Round 5's second finding: a row is re-rendered long after the ending, so the
    sentence it carries cannot be the one that names what happened.

    ``parkWords`` is reached by every later transition — the park's other row answering,
    a listing read, the registry refreshing — and it has no record of *why* the answer
    went unread. A stranded arm returning "You stopped waiting" therefore attributed a
    connection failure to an act the owner did not take, which is the class of wrong
    explanation ``abandonAsk`` keeps three sentences apart for the ask.

    So the division is: what happened is said once, at the ending, in the fault line
    beside the row — three sentences, each naming its own cause — and what is still true
    is what the row carries.
    """
    script = _code("app.js")
    words = _functions(script)["parkWords"]

    assert "return stranded ? PARK_SETTLED_AFTER_UNKNOWN : PARK_ANSWERED;" in words
    assert 'return stranded ? PARK_NOT_KNOWN : "";' in words
    neutral = _constant(script, "PARK_NOT_KNOWN")
    assert "not known" in neutral
    assert neutral.rstrip().endswith("PARK_ASK_AGAIN")
    # Cause-neutral: none of the three endings' own openings appears in it.
    for attributed in ("You stopped waiting", "connection carrying", "gateway refused that answer"):
        assert attributed not in neutral, attributed
    # And the four that *do* name a cause reach the owner through the fault slot only,
    # never through a row that outlives the ending.
    for named in (
        "PARK_UNRESOLVED",
        "PARK_LOST",
        "PARK_REFUSAL_NOT_KNOWN",
        "PARK_REFUSAL_AFTER_UNKNOWN",
        "PARK_REPLY_UNREADABLE",
    ):
        assert named not in words, named
        assert named in _functions(script)["answerConfirmation"], named


# --- ADR-0206 §8: an idle device speaks a notification, and no other does -----


# --- ADR-0244 §13: what a read's question, its answer and its act may say ------


def _map(script: str, name: str) -> str:
    """One top-level ``const NAME = { ... };`` as its source text.

    ``_vocabulary``' device, asked for by name rather than fixed to one map: the page
    now carries three closed vocabularies keyed by a `core` enum, and a test that read
    the whole file would be satisfied by a sentence declared anywhere in it.
    """
    opened = script.index(f"\nconst {name} = {{")
    return script[opened : script.index("\n};", opened)]


def _keys(block: str) -> set[str]:
    """The top-level keys of one such map, and not the lines its sentences wrap onto.

    Counting indented lines would count a wrapped sentence as a member, which is the
    direction that makes a closure test pass vacuously: a map of three members whose
    sentences run to nine lines would satisfy a count of nine.
    """
    return set(re.findall(r"^  (\w+):", block, re.MULTILINE))


def _statements(block: str) -> dict[str, str]:
    """Each top-level entry of one such map, as the sentence it renders.

    :func:`_keys` answers *which* members are declared; this answers *what each one
    says*, which is what a bar stated over the words has to be asserted against. The
    sentences wrap onto continuation lines and are built as ``"..." + "..."``, so the
    halves are put back together by :func:`_joined` — and reading the map whole would let
    a fragment barred from one member be satisfied by its absence from another.
    """
    parts = re.split(r"^  (\w+):", block, flags=re.MULTILINE)
    return {parts[index]: _joined(parts[index + 1]) for index in range(1, len(parts), 2)}


def test_a_reads_question_says_what_answering_yes_does_and_says_no_more() -> None:
    """ADR-0244 §13's third Normative, which is one sentence and so is the page's.

    "It says that answering *yes* dispatches this one read, and it says no more than
    that. No surface states that the read will succeed, that the answer will change,
    that a standing authorisation is being created, that the destination becomes
    trusted, or that any later search is affected."

    The five bars are asserted as absences over the sentence's own text, because each is
    about what it must not say — and "this one" is checked in terms, since it is the word
    that separates answering a question from establishing anything.

    **It is rendered on the discriminator and on nothing else** (§4). A page branching on
    ``tool_id`` would be deriving a fact `core` already carried, and would be wrong for
    the next registered searcher rather than for this one.
    """
    script = _code("app.js")
    said = _constant(script, "READ_DISPATCHES_ONE")
    render = _functions(script)["renderConfirmation"]

    assert "this one lookup" in said
    for barred in ("succeed", "standing", "trust", "later", "next", "again", "will change"):
        assert barred not in said, barred
    assert "if (confirmation.read !== null) {" in render
    assert "tool_id" not in render.split("renderParameters")[1]
    # The floor is whole and on screen before there is anything to press (ADR-0178 §7,
    # ADR-0233 §8), and this sentence sits with the reason rather than after the pair.
    assert render.index("READ_DISPATCHES_ONE") < render.index("offerApproval(")


def test_one_fixed_statement_per_read_answer_member_and_no_member_without_one() -> None:
    """ADR-0244 §13's last clause, read off `core`'s own vocabulary.

    "A surface that renders no statement for a ``ReadAnswerOutcome`` member it was given
    … has not implemented this section — it is **not permissibly degraded**." So the map
    is total over the enum and closed at its count, which is ``coverageWords``' own
    arrangement: an eighth member fails here rather than reaching a person as a bare
    identifier.

    **And the lookup is by ownership rather than by truthiness**, which is the arm a
    plain ``WORDS[member]`` leaves open: a member naming an inherited property —
    ``toString``, ``constructor`` — comes back as a function, and ``line`` would put its
    source text on the screen where a sentence about the owner's own lookup belongs. The
    ``typeof`` in front of it is round 7's: a property key is a coerced one, so
    ``["dispatched"]`` asks for the key ``String(["dispatched"])`` and spells a member.
    """
    script = _code("app.js")
    words = _map(script, "READ_ANSWER_WORDS")
    functions = _functions(script)

    assert _keys(words) == {member.value for member in ReadAnswerOutcome}
    assert (
        'return typeof member === "string" && Object.hasOwn(READ_ANSWER_WORDS, member);'
        in functions["isReadAnswer"]
    )
    assert "isReadAnswer(member)" in functions["readAnswerWords"]
    assert "READ_ANSWER_UNREADABLE" in functions["readAnswerWords"]
    assert "readAnswerWords(member)" in functions["renderReadAnswer"]


def test_a_read_answer_outside_the_enumeration_is_not_an_answer_this_page_has_read() -> None:
    """Adversarial review's round 9, which is round 6's finding one vocabulary over.

    ADR-0244 §9 closes ``ReadAnswerOutcome`` at seven, so a value that is none of them is
    a response this browser read and cannot read *as* an outcome. The page had a sentence
    for it and that was the easy half; the consequence was the defect.
    ``answerConfirmation`` keeps a consent token spent on every reply it **renders** —
    that is what "that park has been answered from this page" means here — so a rendered
    fallback left the pair disabled over a park ``pending_confirmations`` goes on handing
    back, which is #1536's control that submits nothing.

    **And the two members that give the token back are not a place to put it.**
    ``READ_ANSWERS_LEAVING_THE_QUESTION`` releases it for ``OPERATION_CHANGED`` and
    ``UNAVAILABLE_NOW`` *because §9 leaves the park open on them*; inferring one of those
    from a value that is neither is ADR-0139 §4's inference in the other direction.

    So the render refuses and ``couldRenderOutcome`` answers for it, which is the same
    ending a ``2xx`` carrying no outcome at all reaches — the token back, the park's row
    given up, and ``PARK_REPLY_UNREADABLE``. The shape test is ``isCancellation``'s,
    stated once and shared between the reader and the vocabulary.
    """
    functions = _functions(_code("app.js"))

    render = functions["renderReadAnswer"]
    assert "if (!isReadAnswer(member)) {" in render
    assert "throw new TypeError(" in render
    # Refused before anything is written, so nothing half-said stands beside the ending.
    assert render.index("isReadAnswer(member)") < render.index("line(body,")
    # A `null` or an absent member is still not a refusal: an outcome that parked no read
    # and answered none carries neither, and §9 makes the two mutually exclusive.
    assert "if (member === null || member === undefined) {" in render
    assert render.index("member === undefined") < render.index("isReadAnswer(member)")
    # One test for the class, shared with the vocabulary rather than restated in it.
    assert "isReadAnswer(member)" in functions["readAnswerWords"]


def test_no_read_answer_statement_says_why_a_ruling_went_the_way_it_did() -> None:
    """ADR-0244 §9's bar, which is ADR-0242 §9's bar binding on a second vocabulary.

    "No member carries, and no statement rendered for one carries, a destination, a
    host, an origin, a provider name, an account identity, a query or any fragment of
    one, a monetary figure, a budget, a threshold, a ``Settings`` field name or a
    ``SearchDisposition`` value. … **It states what became of the answer and never why a
    ruling went the way it did.**"

    Asserted over the declared sentences as absences, because each is about what they
    must not say. The two that come closest are worth naming: ``expired`` says a deadline
    passed and gives no figure for it, and ``unavailable_now`` names neither of the two
    states that reach it — a deleted conversation and a deployment whose per-conversation
    allowance is zero.
    """
    words = _map(_code("app.js"), "READ_ANSWER_WORDS")

    for barred in (
        "search_calls_per_conversation",
        "parked_read_ttl",
        "conversation was deleted",
        "budget",
        "spend",
        "$",
        "destination",
        "account",
        "provider",
        "query",
        "seconds",
        "minutes",
    ):
        assert barred not in words, barred
    # **And no statement names a member's cause** (adversarial review, round 2). §9 gives
    # ``OPERATION_CHANGED`` three grounds — a rebuilt request that is not the recorded
    # ``CONFIRM``'s own subject, a binding that no longer derives equal, **or a trail that
    # refused the resolving append** — and a sentence saying that what would have been
    # sent is not what was shown is true of two of them and false of the third. The
    # surface is handed the member and nothing else (§13: "no adapter reads a store, joins
    # a row, computes a member"), so it cannot tell the three apart and must not write a
    # sentence that picks one. Asserted over that member's own statement, because this is
    # the one member with more than one ground behind it.
    changed = words[words.index("operation_changed:") + len("operation_changed:") :]
    changed = changed[: changed.index("\n  unavailable_now:")]
    for cause in ("binding", "shown", "subject", "trail", "changed", "append"):
        assert cause not in changed, cause
    # It does not say whether the question still stands either, for the same reason: §9
    # leaves the park ``OPEN`` on two of those grounds and spent on the third.
    assert "still open is not something this answer says" in changed


def test_one_fixed_statement_per_read_cancellation_member_and_none_reads_as_a_denial() -> None:
    """ADR-0244 §11, at the surface that performs the act.

    Three members and three statements, total over the enum for the reason above. What
    each must say is stated in §11 and each of the three has a clause of its own:

    ``withdrawn`` records no answer — "``ActionPolicy.resolve`` is not called, no ruling
    is recorded … which is the whole difference from a denial".

    ``interrupted`` does **not** say the query stayed on the device: "the question was
    answered, the call was made … **no caller assumes the query did not leave**. The
    user's recourse is to ask again."

    ``nothing_to_cancel`` is stated over this assistant and not over the world, because
    "a park settled ``APPROVED`` whose dispatch is running elsewhere answers
    ``NOTHING_TO_CANCEL``, which is true of what this process can do".
    """
    script = _code("app.js")
    words = _map(script, "READ_CANCELLATION_WORDS")
    functions = _functions(script)

    assert _keys(words) == {member.value for member in ReadCancellation}
    assert "Object.hasOwn(READ_CANCELLATION_WORDS, member)" in functions["cancellationWords"]
    # None of the three reports a ruling, a grant, a trust record or a refund, because
    # "cancellation establishes nothing and forfeits nothing".
    for barred in ("denied", "declined", "ruling", "grant", "trust", "refund", "allowance"):
        assert barred not in words, barred
    assert "no answer was recorded" in words
    assert "did not leave" in words
    assert "in this assistant" in words


def test_the_cancellation_act_is_offered_on_a_read_and_on_nothing_else() -> None:
    """ADR-0244 §11: ``cancel_read`` is the cancellation source "**for this operation
    kind alone**", and §4's discriminator is what a surface decides that from.

    So the control is built on ``read !== null`` and not built at all otherwise — a
    park of a plan step can never become a read, so a hidden control on its card would be
    one that can never be shown and an act its token would be refused for. The routed
    act's card passes ``null`` explicitly, because ADR-0197 §7's park is not a
    ``Confirmation`` and carries no discriminator to read.

    **And it stays enabled while an answer is out**, which is the only route to
    ``INTERRUPTED``: that member is defined over "a read this process had dispatched and
    had not completed", so a control disabled by an answer in flight would put the state
    §11 names second out of reach of the surface §13 places the act on.
    """
    script = _code("app.js")
    offer = _functions(script)["offerApproval"]

    assert "const withdraw = read === null ? null : document.createElement" in offer
    assert '"Cancel this lookup"' in offer
    assert "withdraw.disabled = withdrawing || gone !== null;" in offer
    assert "cancelRead(token)" in offer
    assert "offerApproval(item, confirmation.token, confirmation.read);" in script
    assert "offerApproval(item, card.token, null);" in script


def test_the_page_renders_no_statement_for_any_search_not_serviced_member() -> None:
    """ADR-0242 §9's browser deferral, which ADR-0244 leaves entire — a decision this
    lane took rather than an omission it left.

    §9's last clause is explicit about this surface: "the browser, until its own lane
    (§5), renders neither the statement nor the reply's absence of one, because it
    renders the turn exactly as it does today and the field it now receives is one it
    ignores." ADR-0244 supersedes that ADR as to "§9's statement enumeration by **one
    member**. **Nothing else in that ADR**", so the deferral binds and the enumeration
    stays all-or-nothing: "a surface that renders **no** statement for a member is a
    surface that has not implemented this section, not a permitted degradation".

    A page rendering one of the nine is therefore the half-implemented surface §9
    refuses, and one rendering all nine would mint browser wordings for eight members and
    for three acts that exist only in a terminal. So it renders none, the member reaches
    it through no route, and #2237 carries the lane that changes that.

    This assertion is what stops the decision being quietly reversed: the member reaching
    the page at all fails here, and whoever puts it there decides in this docstring
    whether the page sees the whole vocabulary.

    **Asserted over the route first**, because that is the only way a member can arrive:
    ``search_not_serviced`` is the one field that carries it, and a page that never reads
    it renders nothing for any of the nine however the words are spelled.

    **And over the key form for the members that are this enum's alone.** ``declined`` and
    ``interrupted`` are values two of these vocabularies share — ``ReadAnswerOutcome`` has
    the first and ``ReadCancellation`` the second — so a key of that name says nothing
    about which enum it belongs to.

    **``ForecastNotRead`` joins that overlap, which narrows this arm rather than weakening
    it.** ADR-0260 §10 closes that vocabulary at six and this page now renders all six
    (#2474), and three of its values — ``spend_exhausted``, ``authorisation_awaited`` and
    ``unavailable`` — are spelled identically in ``SearchNotServiced``. A key of one of
    those names says nothing about which enum declared it, exactly as ``declined`` already
    said nothing. **The assertion this arm actually rests on is the one above it**: the
    member arrives through ``search_not_serviced`` and through no other route, so a page
    that never reads that field renders nothing for any of the nine however the words are
    spelled. What is left to the key form is ``trust_missing`` and ``answer_awaited``,
    which are this enum's alone and are the two whose acts exist only in a terminal.
    """
    script = _code("app.js")
    shared = (
        {member.value for member in ReadAnswerOutcome}
        | {member.value for member in ReadCancellation}
        | {member.value for member in ForecastNotRead}
    )

    assert "search_not_serviced" not in script
    for member in SearchNotServiced:
        if member.value not in shared:
            assert f"\n  {member.value}:" not in script, member.value


def test_one_fixed_statement_per_forecast_member_and_no_member_without_one() -> None:
    """ADR-0260 §10, read off ``core``'s own vocabulary.

    "A surface renders, beside the reply and never in place of it, **one fixed statement
    per member**", under ADR-0242 §9's rule that "a surface that renders **no** statement
    for a member is a surface that has not implemented this section, not a permitted
    degradation". So the map is total over the enum and closed at its count, which is
    ``READ_ANSWER_WORDS``' own arrangement: a seventh member fails here rather than
    reaching a person as a bare identifier — the #1113 rule, at this vocabulary.

    **And the lookup is by ownership rather than by truthiness**, which is the arm a plain
    ``WORDS[member]`` leaves open: a member naming an inherited property — ``toString``,
    ``constructor`` — comes back as a function and ``line`` would put its source text on
    the screen. The ``typeof`` in front of it is the same round's: a property key is a
    coerced one, so ``String(["declined"])`` spells a member.
    """
    script = _code("app.js")
    words = _map(script, "FORECAST_NOT_READ_WORDS")
    functions = _functions(script)

    assert _keys(words) == {member.value for member in ForecastNotRead}
    assert (
        'return typeof member === "string" && Object.hasOwn(FORECAST_NOT_READ_WORDS, member);'
        in functions["isForecastNotRead"]
    )
    assert "isForecastNotRead(member)" in functions["forecastNotReadWords"]
    assert "FORECAST_NOT_READ_UNREADABLE" in functions["forecastNotReadWords"]
    assert "forecastNotReadWords(member)" in functions["renderForecastNotRead"]


def test_the_page_renders_the_forecast_statement_beside_the_reply_and_not_in_place_of_it() -> None:
    """ADR-0260 §10's placement, and §10's meaning for an absent member.

    The renderer is reached from ``renderOutcome`` **after** ``renderReply``, which is
    ``renderRouted``'s own placement and this page's reading of "beside the reply and
    never in place of it". And ``null`` is silence rather than a refusal: §10 fixes the
    absence's meaning — ``None`` "means the servicing recorded no ``ForecastDisposition``,
    and means nothing else" — so a turn that serviced no forecast read and one the
    provider answered both say nothing about a forecast at all.
    """
    script = _code("app.js")
    functions = _functions(script)
    outcome = functions["renderOutcome"]
    render = functions["renderForecastNotRead"]

    assert "renderForecastNotRead(body, outcome.forecast_not_read);" in outcome
    assert outcome.index("renderReply(body, outcome)") < outcome.index("renderForecastNotRead(")
    assert "if (member === null || member === undefined) {" in render
    assert render.index("member === undefined") < render.index("line(body,")


def test_the_no_action_notice_is_guarded_on_the_forecast_member() -> None:
    """Adversarial review, round 1, ``major``, pinned where the condition is written.

    "No action was needed." above "That forecast read was begun and stopped" is the
    contradiction on one screen that notice's guard exists to prevent, and this lane is
    what would have created it: before ADR-0260 §10's statement the refused read reached
    this page through no route, so the two lines could not sit together.

    Asserted over the condition's own text, beside the executed arms in
    ``test_browser_forecast.py``: a driven case says the notice is absent on the outcomes
    it was driven over, and this says the guard is a term of the condition rather than an
    accident of the shapes those cases happened to use.

    **``search_not_serviced`` is deliberately not a term here.** It is rendered by no
    route on this page at all (ADR-0242 §9's deferral, #2237), so there is no statement
    for the notice to contradict — which is the "a lane closes its own and no more"
    triage ``interfaces/cli.py``'s guard records for ``read_confirmation`` and
    ``read_answer`` (#2329).
    """
    outcome = _functions(_code("app.js"))["renderOutcome"]

    guard = outcome[outcome.index("outcome.steps.length === 0") :]
    guard = guard[: guard.index('line(body, "No action was needed."')]
    assert "outcome.forecast_not_read === null" in guard
    assert "search_not_serviced" not in guard


def test_no_forecast_statement_says_why_a_ruling_went_the_way_it_did() -> None:
    """ADR-0242 §9's bar, which ADR-0260 §10 binds on this vocabulary word for word.

    "**No statement says that performing the act it names will make the next read
    happen**, and none says why a ruling was not an ``ALLOW``. No statement names a floor,
    a threshold, a ``Settings`` field, a configuration value, a provider, an origin, a
    place or a coordinate."

    Asserted over the declared sentences as absences, because each is about what they must
    not say. ``will`` is the whole of the first clause on this surface — a sentence with no
    future tense cannot promise the next read — and ``because`` is the second's: a
    statement that explained itself would be saying why a ruling went the way it did.
    ``ForecastDisposition`` and ``ForecastRefusal`` are asserted from ``orchestration``'s
    and ``core``'s own enumerations rather than spelled out, so a member renamed there
    fails here instead of leaving a stale literal behind.
    """
    said = _statements(_map(_code("app.js"), "FORECAST_NOT_READ_WORDS"))

    assert set(said) == {member.value for member in ForecastNotRead}
    for member, sentence in said.items():
        assert not any(character.isdigit() for character in sentence), member
        for barred in (
            "will",
            "because",
            "http",
            "://",
            "@",
            "$",
            "£",
            "latitude",
            "longitude",
            "budget",
            "threshold",
            "floor",
            "forecast_",
            "settings",
        ):
            assert barred not in sentence.lower(), f"{member}: {barred}"
        for stage in ForecastDisposition:
            assert stage.value not in sentence, f"{member}: {stage.value}"
        for refusal in ForecastRefusal:
            assert refusal.value not in sentence, f"{member}: {refusal.value}"


def test_only_the_awaited_forecast_statement_names_a_command_and_it_names_decisions() -> None:
    """ADR-0260 §10's fixed half: "what is fixed is which command each names and that
    ``UNAVAILABLE`` names none".

    ``AUTHORISATION_AWAITED`` "says the read was put to the user as a question instead of
    being made and that a decision is recorded, naming ``assistant decisions`` as where it
    is read", and it is the only member that names anything at all: ``NOT_CONFIGURED``
    names "no user act", ``SPEND_EXHAUSTED`` "an operator setting and no user act", and
    ``UNAVAILABLE`` "no cause and no act".

    **And it names neither of the acts a parked read would have.** ADR-0260 §11 mints no
    park for a forecast read, so there is nothing to answer from a listing and nothing to
    withdraw — ``assistant resume``, ``assistant cancel-read`` and ``assistant
    remember-recipients`` would each send a user to a listing this read is not in.
    """
    said = _statements(_map(_code("app.js"), "FORECAST_NOT_READ_WORDS"))

    awaited = said[ForecastNotRead.AUTHORISATION_AWAITED.value]
    assert "'assistant decisions'" in awaited
    for barred in ("assistant resume", "assistant cancel-read", "assistant remember-recipients"):
        assert barred not in awaited, barred
    for member in ForecastNotRead:
        if member is not ForecastNotRead.AUTHORISATION_AWAITED:
            assert "assistant " not in said[member.value], member.value


def test_one_fixed_statement_per_attempt_report_member_and_no_member_without_one() -> None:
    """ADR-0262 §6, read off ``core``'s own vocabulary.

    "**One fixed statement per member**, rendered beside the reply and never in place of
    it", under the rule that "a surface that renders no statement for a member has not
    implemented this section and is not a permitted degradation". So the map is total over
    the six §6's report admits and closed at their count, which is
    ``FORECAST_NOT_READ_WORDS``' own arrangement: an eighth ``AttemptOutcome`` arriving
    with the ADR that decides it fails here rather than reaching a person as a bare
    identifier — the #1113 rule, at this vocabulary.

    **``CANCELLED`` is excluded on purpose and its exclusion is asserted.** §4 is explicit
    that it "is reached by no limb" of the comparison, so §6 fixes no statement for it;
    minting one here would be this surface deciding a vocabulary, and a cancelled attempt
    is ADR-0261 §2's act with statements of its own. What it reaches instead is
    ``ATTEMPT_REPORT_UNREADABLE``.

    **And the lookup is by ownership rather than by truthiness**, which is the arm a plain
    ``WORDS[member]`` leaves open: a member naming an inherited property — ``toString``,
    ``constructor`` — comes back as a function and ``line`` would put its source text on
    the screen. The ``typeof`` in front of it is the same round's: a property key is a
    coerced one, so ``String(["failed"])`` spells a member.
    """
    script = _code("app.js")
    words = _map(script, "ATTEMPT_OUTCOME_WORDS")
    functions = _functions(script)

    assert _keys(words) == {member.value for member in AttemptOutcome} - {
        AttemptOutcome.CANCELLED.value
    }
    assert AttemptOutcome.CANCELLED.value not in _keys(words)
    assert (
        'return typeof member === "string" && Object.hasOwn(ATTEMPT_OUTCOME_WORDS, member);'
        in functions["isAttemptOutcome"]
    )
    assert "isAttemptOutcome(member)" in functions["attemptOutcomeWords"]
    assert "ATTEMPT_REPORT_UNREADABLE" in functions["attemptOutcomeWords"]
    assert "attemptOutcomeWords(member)" in functions["renderAttemptReport"]


def test_the_page_renders_the_attempt_statement_beside_the_reply_and_not_in_place_of_it() -> None:
    """ADR-0262 §6's placement, and §6's meaning for an absent member.

    The renderer is reached from ``renderOutcome`` **after** ``renderReply``, which is
    ``renderRouted``'s own placement and this page's reading of "beside the reply and never
    in place of it". And ``null`` is silence rather than a refusal: the member is non-``None``
    "exactly on a turn that ended an attempt under §4", so every turn that ended none — a
    routed operation, ADR-0198 §1's restatement, an attempt still live, **and a turn whose
    ``commit_attempt`` was refused** — says nothing about an attempt at all. §6 fixes that
    last one as "a silence rather than a false claim".
    """
    script = _code("app.js")
    functions = _functions(script)
    outcome = functions["renderOutcome"]
    render = functions["renderAttemptReport"]

    assert "renderAttemptReport(body, outcome.attempt_report);" in outcome
    assert outcome.index("renderReply(body, outcome)") < outcome.index("renderAttemptReport(")
    assert "if (member === null || member === undefined) {" in render
    assert render.index("member === undefined") < render.index("line(body,")


def test_the_no_action_notice_is_guarded_on_the_four_outcomes_that_assert_work() -> None:
    """The contradiction on one screen, at this vocabulary, pinned where the condition is.

    "No action was needed." above "The work failed, and no criterion of this goal was
    established." says both that nothing was owed and that work was attempted and did not
    complete. The comparison runs after the plan, so a turn that planned nothing still ends
    an attempt — limb 1's first arm is an established contradiction read off the goal's own
    earlier records — and this lane is what would have created the pairing.

    **Four of the seven and not the member's presence**, which is where this term differs
    from ``forecast_not_read``'s beside it. ``ForecastNotRead`` "has no member for having
    attempted nothing"; ``AttemptOutcome`` has two, and ADR-0262 §12's first arm is a turn
    of the second kind — "what is two plus two?", no step claimed, the attempt ending
    ``ANSWERED`` — of which the notice is true.

    Asserted over the condition's own text, beside the executed arms in
    ``test_browser_attempt_report.py``: a driven case says the notice is absent on the
    outcomes it was driven over, and this says the guard is a term of the condition rather
    than an accident of the shapes those cases happened to use.
    """
    script = _code("app.js")
    outcome = _functions(script)["renderOutcome"]

    guard = outcome[outcome.index("outcome.steps.length === 0") :]
    guard = guard[: guard.index('line(body, "No action was needed."')]
    assert "!ATTEMPT_OUTCOMES_THAT_ASSERT_WORK.has(outcome.attempt_report)" in guard

    opened = script.index("\nconst ATTEMPT_OUTCOMES_THAT_ASSERT_WORK = new Set([")
    asserting = set(re.findall(r'"([a-z_]+)"', script[opened : script.index("]);", opened)]))
    assert asserting == {
        AttemptOutcome.PARTIAL.value,
        AttemptOutcome.FAILED.value,
        AttemptOutcome.UNCERTAIN.value,
        AttemptOutcome.CONDITION_PREVENTED.value,
    }


def test_no_attempt_statement_asserts_what_the_comparison_did_not_establish() -> None:
    """ADR-0262 §6's bar, over the declared sentences as absences.

    "**No statement asserts anything the record does not carry.** None says that the goal
    is complete unless the member is ``VERIFIED``; none says an effect did not happen; none
    names a criterion, a tool, a destination, a figure, a ``Settings`` field or a cause; and
    ``UNCERTAIN``'s says nothing about whether the call left."

    **And none asserts a commit that has not happened** (§6): the comparison runs before the
    composing stage and both commits after it, so "no statement of this section asserts that
    an attempt was ended, that a status was written, or that a goal is now closed". The
    ``GoalStatus`` words are read from ``core``'s own enumeration rather than spelled out, so
    a member renamed there fails here instead of leaving a stale literal behind.

    **The offer is barred too.** §6 puts it in the reply — "the **reply** carries the offer
    and the **surface** the outcome word" — so a sentence here ending with one would be the
    page composing a reply, which golden rule 3 refuses.
    """
    said = _statements(_map(_code("app.js"), "ATTEMPT_OUTCOME_WORDS"))

    assert set(said) == {member.value for member in AttemptOutcome} - {
        AttemptOutcome.CANCELLED.value
    }
    for member, sentence in said.items():
        assert not any(character.isdigit() for character in sentence), member
        for barred in (
            "because",
            "http",
            "://",
            "@",
            "$",
            "£",
            "threshold",
            "floor",
            "settings",
            "shall i",
            "would you like",
            "try again",
            "never left",
            "did not leave",
            "nothing was sent",
            "nothing was done",
            "did not happen",
            "the attempt was ended",
            "goal is closed",
            "goal is complete",
        ):
            assert barred not in sentence.lower(), f"{member}: {barred}"
        for status in GoalStatus:
            assert status.value not in sentence.lower(), f"{member}: {status.value}"


def test_only_the_two_statements_that_cannot_speak_for_the_status_name_a_command() -> None:
    """ADR-0262 §6's fixed half, on the surface that has no goals listing of its own.

    §6 names ``assistant goals`` in exactly two of the six — ``VERIFIED``'s, which "speaks
    of the criteria **this attempt compared**" and must not claim the goal is closed, and
    ``UNCERTAIN``'s — because each is a statement the goal's own status could stand beside
    differently, so it says where the status is read instead of asserting one. The other
    four name nothing.

    Naming the terminal's command from this page is this surface's own ratified practice
    (``UNREADABLE_RULINGS``, ``FORECAST_NOT_READ_WORDS``): inventing a control here would be
    minting a route no ratified decision gives this surface.
    """
    said = _statements(_map(_code("app.js"), "ATTEMPT_OUTCOME_WORDS"))

    names_goals = {AttemptOutcome.VERIFIED.value, AttemptOutcome.UNCERTAIN.value}
    for member, sentence in said.items():
        assert ("'assistant goals'" in sentence) is (member in names_goals), member
        assert ("assistant " in sentence) is (member in names_goals), member
        for barred in ("assistant resume", "assistant decisions", "assistant cancel-read"):
            assert barred not in sentence, f"{member}: {barred}"


# --- ADR-0261 §7: the withheld drive, as the shipped bundle declares it -------


def test_one_fixed_statement_per_withheld_member_and_no_member_without_one() -> None:
    """ADR-0261 §7, read off ``core``'s own vocabulary.

    §7 closes ``DriveWithheld`` at **exactly seven** members and requires "one fixed
    statement per member ... rendered beside the reply", under ADR-0242 §9's
    all-or-nothing rule. So the map is total over the seven and closed at their count,
    which is ``ATTEMPT_OUTCOME_WORDS``' own arrangement: an **eighth** member arriving with
    the ADR that decides it fails here rather than reaching a person as a bare identifier —
    the #1113 rule, at this vocabulary.

    **And the lookup is by ownership rather than by truthiness**, which is the arm a plain
    ``WORDS[member]`` leaves open: a member naming an inherited property — ``toString``,
    ``constructor`` — comes back as a function and ``line`` would put its source text on
    the screen. The ``typeof`` in front of it is the same round's: a property key is a
    coerced one, so ``String(["goal_blocked"])`` spells a member.
    """
    script = _code("app.js")
    words = _map(script, "DRIVE_WITHHELD_WORDS")
    functions = _functions(script)

    assert _keys(words) == {member.value for member in DriveWithheld}
    assert (
        'return typeof member === "string" && Object.hasOwn(DRIVE_WITHHELD_WORDS, member);'
        in functions["isDriveWithheld"]
    )
    assert "isDriveWithheld(member)" in functions["driveWithheldWords"]
    assert "DRIVE_WITHHELD_UNREADABLE" in functions["driveWithheldWords"]
    assert "driveWithheldWords(member)" in functions["renderDriveWithheld"]


def test_the_page_renders_the_withheld_statement_beside_the_reply_and_not_in_place_of_it() -> None:
    """ADR-0261 §7's placement, and §7's meaning for an absent member.

    The renderer is reached from ``renderOutcome`` **after** ``renderReply``, which is
    ``renderRouted``'s own placement and this page's reading of "beside the reply and never
    in place of it". And ``null`` is silence rather than a refusal: the member is
    non-``None`` "exactly on a turn that *returned* after a ``ClaimRefused`` whose
    post-refusal read established one of the seven states", so every turn that dispatched,
    every turn that stopped on one of ADR-0255 §2's five, every turn that drove nothing and
    ADR-0198 §1's restatement say nothing about a withheld drive at all.
    """
    script = _code("app.js")
    functions = _functions(script)
    outcome = functions["renderOutcome"]
    render = functions["renderDriveWithheld"]

    assert "renderDriveWithheld(body, outcome.drive_withheld);" in outcome
    assert outcome.index("renderReply(body, outcome)") < outcome.index("renderDriveWithheld(")
    assert "if (member === null || member === undefined) {" in render
    assert render.index("member === undefined") < render.index("line(body,")


def test_the_no_action_notice_is_guarded_on_the_withheld_member_being_absent() -> None:
    """The contradiction on one screen, at this vocabulary, pinned where the condition is.

    "No action was needed." above "That goal was cancelled, and this turn did nothing
    further for it." says both that nothing was owed and that a step this turn was driving
    was not claimed.

    **On the member's presence and on all seven**, which is ``forecast_not_read``'s term
    rather than ``attempt_report``'s: ``OutboundReach`` and ``AttemptOutcome`` each have a
    member for having attempted nothing and ``DriveWithheld`` has none — every one of the
    seven is a turn that was driving a step and did not claim it.

    **A membership test and not a presence one**, which is
    ``ATTEMPT_OUTCOMES_THAT_ASSERT_WORK``'s own arrangement and is load-bearing here: an
    **absent** member — what a hub at another version sends — and a value outside the
    vocabulary are both *not* one of the seven, and both belong on the notice's side. A
    ``=== null`` term suppresses a true notice on each, which
    ``test_a_member_outside_the_six_is_said_rather_than_shown_raw`` caught one vocabulary
    over.

    Asserted over the condition's own text, beside the executed arms in
    ``test_browser_cancellation.py``.
    """
    outcome = _functions(_code("app.js"))["renderOutcome"]

    guard = outcome[outcome.index("outcome.steps.length === 0") :]
    guard = guard[: guard.index('line(body, "No action was needed."')]
    assert "!isDriveWithheld(outcome.drive_withheld)" in guard
    assert "outcome.drive_withheld === null" not in guard


def test_no_withheld_statement_asserts_what_the_read_did_not_establish() -> None:
    """ADR-0261 §7's bar, over the declared sentences as absences.

    "**No statement says that the step would have succeeded, that the effect did not
    happen, that no step of this plan was ever started, or why a store refused** — what
    each asserts is what this turn did, which is the only thing the read establishes."

    **And none says why**, which is the limb this vocabulary makes easiest to breach: one
    ``ClaimRefused`` covers both liveness raisers and "the read cannot establish it
    either", so a sentence naming a conjunct, a store, a transition or a version would name
    something nothing established. ADR-0242 §9's own bar carries the rest.

    **And two of them must not say the goal is closed** (§7): ADR-0250 §1 rules ``BLOCKED``
    **open** and ADR-0249 §4 that an attempt reaching a terminal state does not move its
    goal's status, so ``GOAL_BLOCKED``'s and ``ATTEMPT_ENDED``'s sentences are asserted
    against the ``GoalStatus`` words read from ``core``'s own enumeration rather than
    spelled out here.
    """
    said = _statements(_map(_code("app.js"), "DRIVE_WITHHELD_WORDS"))

    assert set(said) == {member.value for member in DriveWithheld}
    for member, sentence in said.items():
        assert not any(character.isdigit() for character in sentence), member
        for barred in (
            "because",
            "http",
            "://",
            "@",
            "$",
            "£",
            "threshold",
            "settings",
            "shall i",
            "would you like",
            "try again",
            "would have",
            "did not happen",
            "nothing was sent",
            "never started",
            "refused",
            "conjunct",
            "version",
            "transition",
        ):
            assert barred not in sentence.lower(), f"{member}: {barred}"

    for member in (DriveWithheld.GOAL_BLOCKED, DriveWithheld.ATTEMPT_ENDED):
        for status in (GoalStatus.ABANDONED, GoalStatus.ACHIEVED):
            assert status.value not in said[member.value].lower(), member


def test_only_the_two_withheld_statements_the_adr_fixes_name_a_command() -> None:
    """ADR-0261 §7's fixed half, on the surface that has a goals listing of its own.

    §7 names ``assistant goals`` in exactly two of the seven — ``GOAL_BLOCKED``'s, because
    the goal "cannot currently be reached and is still open" and the user's question is
    then what it is waiting on, and ``ATTEMPT_PAUSED``'s, because the goal is waiting on
    them. The other five name nothing: there is no act that helps, and naming one that
    cannot help is worse than naming none.

    Naming the terminal's command from this page is this surface's own ratified practice
    (``UNREADABLE_RULINGS``, ``FORECAST_NOT_READ_WORDS``, ``ATTEMPT_OUTCOME_WORDS``), and
    this lane writes both surfaces' prose byte for byte identically so the parity arm in
    ``test_cli_cancellation.py`` asserts an equality rather than the fixed half alone.
    """
    said = _statements(_map(_code("app.js"), "DRIVE_WITHHELD_WORDS"))

    names_goals = {DriveWithheld.GOAL_BLOCKED.value, DriveWithheld.ATTEMPT_PAUSED.value}
    for member, sentence in said.items():
        assert ("'assistant goals'" in sentence) is (member in names_goals), member
        assert ("assistant " in sentence) is (member in names_goals), member
        for barred in ("assistant resume", "assistant decisions", "assistant abandon-goal"):
            assert barred not in sentence, f"{member}: {barred}"


def test_the_two_pairs_the_adr_forbids_collapsing_read_differently_on_the_page() -> None:
    """ADR-0261 §7: "**No lane collapses any two of the seven** — not ``GOAL_CANCELLED``
    with ``ATTEMPT_CANCELLED``, and not ``GOAL_BLOCKED`` with ``ATTEMPT_PAUSED``."

    The one pair that *does* read alike is ``ATTEMPT_CANCELLED`` with ``ATTEMPT_ENDED``,
    which is §7's own arrangement — that section writes the two one sentence — and is
    asserted as such so the equality cannot quietly be extended to a third member.
    """
    said = _statements(_map(_code("app.js"), "DRIVE_WITHHELD_WORDS"))

    assert said[DriveWithheld.GOAL_CANCELLED.value] != said[DriveWithheld.ATTEMPT_CANCELLED.value]
    assert said[DriveWithheld.GOAL_BLOCKED.value] != said[DriveWithheld.ATTEMPT_PAUSED.value]
    assert said[DriveWithheld.ATTEMPT_CANCELLED.value] == said[DriveWithheld.ATTEMPT_ENDED.value]


def test_the_listing_row_says_an_action_is_outstanding_and_asserts_no_outcome() -> None:
    """ADR-0261 §6's statement for a row whose ``effect_in_flight`` is true.

    §6 fixes which fact it names — that an action of this goal "is outstanding — claimed,
    possibly sent, outcome unknown" — and bars the three an adapter would be tempted into:
    "**No statement says that the action did not happen, that it did, or that anything the
    user does will withdraw it.**"

    ***In flight* means the claim landed, never that the call left**, so "may have been
    sent" is the strongest thing the sentence is allowed to say — and it names no tool, no
    destination and no effect key, §6 making *outstanding* "the step's status and never the
    presence of an effect key" with a **read** included deliberately.

    **And it is rendered on the field and on nothing else**: a page that compared a status
    against an attempt state would be deriving a fact the engine already computed, which is
    ``paused``'s own clause one fact over.
    """
    script = _code("app.js")
    said = _constant(script, "EFFECT_IN_FLIGHT")
    render = _functions(script)["renderGoal"]

    assert "outstanding" in said
    assert "claimed" in said
    assert "may have been sent" in said
    for barred in ("did not", "was sent", "withdraw", "undo", "cancel", "key", "tool", "http"):
        assert barred not in said.lower(), barred
    assert "if (goal.effect_in_flight) {" in render
    assert "EFFECT_IN_FLIGHT" in render
    assert "status" not in render.split("effect_in_flight")[1].split("}")[0]


def test_both_accounts_a_park_owes_are_written_where_no_refresh_reaches_them() -> None:
    """ADR-0244 §11 and ADR-0177 §7, and the rule that ends what eight review rounds kept
    finding.

    **One park carries two acts and the panel owes an account of each.** The answer is
    ADR-0177 §7's fourth clause — "the request was sent and no response was read" is an
    outcome that is **not known** — and the cancellation is §11's: "the cancellation is a
    teardown and is converted into neither an outcome nor a refusal … **what tells the
    user is ``cancel_read``'s own answer, which is the act they performed**". The two can
    be in flight together, which is not an edge case but the state ``INTERRUPTED`` is
    defined over.

    **Every other place either account could go is swept, and each sweep was a finding.**
    A row goes when the listing is re-read, and a withdrawn or settled park is not in the
    listing; the panel's fault slot is cleared by every listing read; and a quiet read of
    an empty listing closes the panel outright. *Both* acts start exactly that read on
    their way out — the answer whether it ends in a rejected request, a refusal the page
    classifies as unknown, one it cannot classify, a reply it cannot render or a perfectly
    good ``ALREADY_SETTLED``; the act on every one of its three states. So whichever reply
    lands second erases the first one's account, and which one that is is the network's
    choice.

    Round 3 moved the **act's** account into a node of its own and no finding since was
    about losing it; rounds 6, 7 and 8 were all about the **answer's**, which was still in
    the swept slot. So the placement is the fix for both rather than a ninth guard on a
    ninth path, and this is what pins it: each account has its own node, in the document
    rather than built by a renderer; both are written by one function over the pair of
    states, so no path writes one without recomputing the other; and the only things that
    reach them are that function and the owner's own press of the button that asks what is
    waiting now. ``readPending`` reads them and writes neither, which is what lets a quiet
    close ask whether the *panel* is silent rather than whether the listing is.
    """
    script = _code("app.js")
    functions = _functions(script)
    document = _asset("index.html")

    # A node each, in the document. The act's is a statement about something that
    # succeeded; the answer's carries the fault's ink because what it reports is an
    # outcome that is not known — and it is deliberately not `.fault`, which is the class
    # naming the swept slot.
    assert '<p id="cancellation-said" class="hint" hidden></p>' in document
    assert '<p id="answer-said" class="account" hidden></p>' in document
    # One writer for the pair, reached by node id: the only place either node's
    # `textContent` and `hidden` are set.
    assert "const node = el(nodeId);" in functions["writeAccount"]
    assert {
        name
        for name, body in functions.items()
        if 'el("cancellation-said")' in body or 'el("answer-said")' in body
    } == {"panelIsSilent"}
    assert 'writeAccount("cancellation-said", ACCOUNTS.act);' in functions["renderAccounts"]
    assert 'writeAccount("answer-said", answerAccountWords());' in functions["renderAccounts"]
    # **And the panel each node is in is opened with it** (adversarial review, round 4).
    # The panel really can be closed at this moment — a quiet read of an empty listing
    # closes it, which is right while it says nothing, and either act starts exactly that
    # read — so a node unhidden inside it would be a statement nobody can read.
    #
    # **Opened and never closed**, because taking a statement down is the owner's own
    # press, and that press is a listing read whose own rules decide what the panel then
    # shows. A `show(false)` here would close a panel holding answerable rows.
    assert 'show("confirmations", true);' in functions["writeAccount"]
    assert 'show("confirmations", false)' not in functions["writeAccount"]
    assert functions["writeAccount"].index("node.hidden") < functions["writeAccount"].index(
        'show("confirmations"'
    )
    # Every writer of either account goes through the one render, so a path that moved one
    # state without recomputing the other cannot be added quietly. This is round 8's fix:
    # ordering is irrelevant by construction rather than guarded against per path.
    for name in (
        "recordAnswerAccount",
        "releaseAnswerAccount",
        "recordActAccount",
        "clearAccounts",
    ):
        assert "renderAccounts();" in functions[name], name
    assert {name for name, body in functions.items() if "ACCOUNTS." in body} == {
        "answerAccountWords",
        "recordAnswerAccount",
        "releaseAnswerAccount",
        "recordActAccount",
        "clearAccounts",
        "renderAccounts",
    }
    # Written by the two acts and by the owner's own press, and by nothing else. A third
    # writer is how a sentence starts being swept again.
    assert {name for name, body in functions.items() if "recordActAccount(" in body} == {
        "cancelRead",
        "recordActAccount",
    }
    assert {name for name, body in functions.items() if "recordAnswerAccount(" in body} == {
        "answerConfirmation",
        "recordAnswerAccount",
    }
    assert {name for name, body in functions.items() if "clearAccounts(" in body} == {
        "listPending",
        "clearAccounts",
    }
    assert (
        "recordActAccount(\n    done === CANCELLATION_UNRESOLVED "
        "? READ_CANCEL_LOST : cancellationWords(done)\n  );" in functions["cancelRead"]
    )
    # The act's ending recomputes both accounts on **every** way out, including the named
    # refusal it returns from before it has a statement of its own: `cancelled` and
    # `cancelling` have just moved, and the answer's account is derived from them.
    assert "renderAccounts();" in functions["cancelRead"]
    assert "clearAccounts();" in functions["listPending"]
    # `readPending` reads both nodes to decide whether the panel is silent, and writes
    # neither: a quiet read of an empty listing closes a panel that says nothing, and a
    # panel holding either account is not one.
    assert "if (quiet && panelIsSilent()) {" in functions["readPending"]
    assert (
        'return el("cancellation-said").hidden && el("answer-said").hidden;'
        in functions["panelIsSilent"]
    )
    for name in ("readPending", "listPending"):
        assert "writeAccount(" not in functions[name], name

    # --- what the answer's account says, over the pair of states ----------------
    #
    # The answer's ending records **which ending it reached** and nothing more; this is
    # where that becomes a sentence, and it is re-run whenever either act finishes. Round
    # 8's blocker is exactly that the ending is not the last moment the answer's account
    # can change, because the act's reply may land after it.
    words = functions["answerAccountWords"]
    assert "const recorded = cancelled.get(held.token);" in words
    # An act still out says the least and is asked about first. The row beside it already
    # reads `READ_CANCEL_SENDING`, so a sentence ending "nothing was cancelled" would put
    # the contradiction round 6 closed on one screen for as long as the act is in flight.
    assert "if (cancelling.has(held.token)) {" in words
    assert words.index("cancelling.has(held.token)") < words.index("cancelled.get(held.token)")
    assert "return PARK_LOST_WITH_THE_ACT_STILL_OUT;" in words
    # Two acts out, neither answered: neither may be resolved by omission, and `PARK_LOST`
    # says "nothing was cancelled" (round 6).
    assert "return PARK_LOST_WHILE_CANCELLING;" in words
    # Only the member that ended the answer explains this ending (round 7) — and of the
    # two that did not, only `WITHDRAWN` settles what became of the lost request (round
    # 8). `NOTHING_TO_CANCEL` settles nothing: the park may be `APPROVED` with its
    # dispatch running in another process.
    assert 'if (recorded === "interrupted") {\n    return null;\n  }' in words
    assert (
        'return recorded === "withdrawn"\n'
        "    ? PARK_LOST_BESIDE_A_WITHDRAWAL\n"
        "    : PARK_LOST_BESIDE_A_CANCELLATION;" in words
    )


def test_a_withdrawal_does_not_leave_the_page_saying_the_action_may_have_run() -> None:
    """Adversarial review's round 8, second finding, at the text layer.

    ``WITHDRAWN`` is the one member of ``ReadCancellation`` that settles what became of a
    concurrent answer whose reply this browser never read. ADR-0244 §11 gives it as "an
    ``OPEN`` park was settled ``CANCELLED`` and **nothing was ever sent**", with "the
    park's content … cleared in the same step, so a cancellation and a concurrent answer
    cannot both take effect"; §6's one compare-and-swap is where that happens, and under
    it "neither party acts on a park the other took", so the lost answer returned
    ``ALREADY_SETTLED`` and cannot have dispatched. Had it dispatched first the park would
    have been ``APPROVED`` at the act's swap, and the act would have answered
    ``INTERRUPTED`` or ``NOTHING_TO_CANCEL`` instead.

    So the sentence for that pairing may not say the action may have been carried out —
    it would contradict, on one screen, the ``WITHDRAWN`` statement two nodes above:
    "Nothing was sent for it, and no answer was recorded." What is still owed is ADR-0177
    §7's fourth clause, narrower: the request went out and no reply was read, so what it
    *came back with* is not known.

    ``NOTHING_TO_CANCEL`` establishes none of that — §11's last clause has a park settled
    ``APPROVED`` whose dispatch is running elsewhere answering it — so it keeps the
    sentence that says the action may have run.
    """
    script = _code("app.js")

    withdrawn = _constant(script, "PARK_LOST_BESIDE_A_WITHDRAWAL")
    assert "may have been carried out" not in withdrawn
    assert "nothing was sent for " in withdrawn
    assert "no answer was recorded for it" in withdrawn
    # It is still an account of a request whose reply was not read (ADR-0177 §7).
    assert "no reply this browser could read" in withdrawn
    assert "is not known" in withdrawn
    # And it neither re-sends nor says "nothing was cancelled", which is false the moment
    # a cancellation is asked for (round 6).
    assert "nothing was re-sent" in withdrawn
    assert "nothing was cancelled" not in withdrawn
    assert withdrawn.rstrip().endswith("PARK_WHERE_NOW")

    beside = _constant(script, "PARK_LOST_BESIDE_A_CANCELLATION")
    assert "may have been carried out" in beside
    assert "nothing was cancelled" not in beside

    # The in-flight window has its own sentence for the same reason, and it asserts
    # nothing about an act that has not answered (ADR-0139 §4).
    out = _constant(script, "PARK_LOST_WITH_THE_ACT_STILL_OUT")
    assert "still out and has not been answered" in out
    assert "nothing was cancelled" not in out
    assert "withdrawn" not in out
    assert out.rstrip().endswith("PARK_WHERE_NOW")


# --- ADR-0250 §15: what the goal surface says, and the identifiers it does not


def test_one_fixed_statement_per_member_of_every_vocabulary_adr_0250_adds() -> None:
    """ADR-0250 §15's non-degradation clause, read off ``core``'s own vocabularies.

    "A surface that renders no statement for a ``ReferenceOutcome``, an
    ``EngagementDisposition`` or a ``ClarificationWithdrawal`` member it was given has
    not implemented this section — **it is not permissibly degraded**." ``GoalAbandonment``
    is the fourth vocabulary this decision adds and is held to the same bar, because
    ``abandon_goal``'s answer is nothing else: §12 closes it "at exactly three members"
    and the act has no other result to render.

    So each map is **total over its enumeration and closed at its count**, which is
    ``READ_ANSWER_WORDS``' own arrangement: a fifth member fails here rather than
    reaching a person as a bare identifier.

    **And the lookup is by ownership rather than by truthiness**, with a ``typeof`` in
    front of it — the arm ``READ_ANSWER_WORDS`` leaves open one vocabulary over: a member
    naming an inherited property comes back as a function, and a property key is a
    coerced one, so ``["opened"]`` asks for the key ``String(["opened"])`` and spells a
    member.
    """
    script = _code("app.js")
    functions = _functions(script)

    assert _keys(_map(script, "ENGAGEMENT_WORDS")) == {
        member.value for member in EngagementDisposition
    }
    assert _keys(_map(script, "REFERENCE_WORDS")) == {member.value for member in ReferenceOutcome}
    assert _keys(_map(script, "CLARIFICATION_WITHDRAWAL_WORDS")) == {
        member.value for member in ClarificationWithdrawal
    }
    assert _keys(_map(script, "GOAL_ABANDONMENT_WORDS")) == {
        member.value for member in GoalAbandonment
    }
    # The listing's status words are total over ``GoalStatus`` too. It is **not** one of
    # the vocabularies this decision adds — ADR-0014 §1 declares it — and two of its
    # members have no producer in the tree today (ADR-0250 §20's arm 23), but what the
    # map is for is that a member arriving from a gateway is rendered rather than shown
    # raw, and "no producer today" is not a property of the value this page receives.
    assert _keys(_map(script, "GOAL_STATUS_WORDS")) == {member.value for member in GoalStatus}

    assert (
        'return typeof member === "string" && Object.hasOwn(words, member);'
        in functions["isGoalMember"]
    )
    assert "isGoalMember(words, member)" in functions["goalMemberWords"]
    assert "GOAL_MEMBER_UNREADABLE" in functions["goalMemberWords"]


def test_no_goal_statement_carries_a_record_identifier_or_a_configuration() -> None:
    """ADR-0250 §15's bar, which is ADR-0242 §9's binding on these vocabularies.

    "No statement rendered for any member of this decision's vocabularies carries a
    record identifier other than the question id the answer act requires, a destination,
    an account identity, a provider name, a query or any fragment of one, a monetary
    figure, a budget, a threshold or a ``Settings`` field name."

    **Asserted structurally, over the maps' own source.** Every statement is a literal,
    so the way an identifier could reach one is an interpolation — and there is none:
    a map holding a template placeholder would be a statement assembled from a value,
    which §9 forbids for its own reason one vocabulary over. That is the strongest form
    the assertion takes here, because a literal containing no interpolation cannot carry
    an id whatever the hub sends.

    **The one identifier the surfaces do render is the question id**, and §15 admits it
    in terms — "the question id is rendered because the act takes it" — which is why it
    is rendered by ``renderGoalQuestion`` and by no statement.
    """
    script = _code("app.js")
    maps = [
        _map(script, name)
        for name in (
            "ENGAGEMENT_WORDS",
            "REFERENCE_WORDS",
            "CLARIFICATION_WITHDRAWAL_WORDS",
            "GOAL_ABANDONMENT_WORDS",
        )
    ]

    for block in maps:
        # No interpolation of any kind: a statement is a literal or it is not fixed.
        assert "${" not in block
        assert "goal_id" not in block
        assert "question_id" not in block
        for barred in ("budget", "threshold", "Settings", "provider", "account", "query"):
            assert barred not in block, barred

    # And the id that *is* rendered is rendered beside the question it names, where §15
    # puts it, rather than in a statement about a member.
    assert "clarification.question_id" in _functions(script)["renderGoalQuestion"]


def test_the_page_composes_no_announcement_of_its_own() -> None:
    """ADR-0250 §5's announcement belongs to the reply, and this page writes no second.

    §5 gives the sentence to the reply — one "naming the goal it is about", stating the
    goal's outcome and "every text in ``added``" and "every text in ``removed``" — and
    rules it "composed by ``orchestration`` from the typed value and by no model's
    decision". A page restating those would put the announcement in a second place, and
    on a ``continued`` or an ``opened`` that moved no word it would put one where §5
    rules the turn silent: "announcing it would be noise on every turn … told every time,
    the sentence stops being read."

    So the renderer reads the **disposition** and nothing else off the member.
    """
    render = _functions(_code("app.js"))["renderGoalEngagement"]

    assert "engagement.disposition" in render
    for barred in ("engagement.outcome", "engagement.added", "engagement.removed", "revised"):
        assert barred not in render, barred


def test_an_undecided_turn_and_a_raised_question_are_not_reported_as_needing_no_action() -> None:
    """The contradiction ``read_confirmation`` already closed, two members further on.

    A turn whose planner raised a clarification "drives no step of its plan and produces
    no effect" (ADR-0250 §10), and an undecided turn "engaged neither goal, drove
    nothing" and carries no turn at all (§20's arm 11) — so both reach the renderer with
    no steps, no step account and no route. "No action was needed." above a question the
    owner is being asked to answer is the opposite of what each of those turns says.
    """
    render = _functions(_code("app.js"))["renderOutcome"]

    guard = render[render.index("outcome.steps.length === 0") : render.index('"No action')]
    assert "outcome.clarification === null" in guard
    assert "outcome.disambiguation === null" in guard


def test_the_goal_surface_is_not_the_deferred_question_surface() -> None:
    """ADR-0250 §20's arm 30 at this surface, over the page's own panels and paths.

    "``assistant questions`` and ``assistant answer`` list and answer **memory**
    questions only, and neither lists nor accepts a ``GoalQuestion``; the clarification
    acts neither list nor accept an ADR-0078 ``Question``." §15 states it as a bar on the
    surface: no surface "presents a goal clarification in the same list, the same command
    or the same vocabulary as a memory question".

    Two panels, two controls, two sets of paths — and the goal panel reaches neither of
    the memory question paths, nor the reverse.
    """
    script = _code("app.js")
    document = _asset("index.html")

    assert '<section id="goals"' in document
    assert '<section id="questions"' in document
    assert 'id="goals-button"' in document
    assert 'id="questions-button"' in document

    goals = "".join(
        _functions(script)[name]
        for name in ("readGoals", "renderGoal", "offerGoalActs", "withdrawClarification")
    )
    assert "/questions" not in goals
    assert "/question/answer" not in goals
    assert "/question/forget" not in goals

    questions = "".join(_functions(script)[name] for name in ("readQuestions", "renderQuestion"))
    assert "/goals" not in questions
    assert "/clarification/withdraw" not in questions
    assert "/goal/abandon" not in questions


def test_the_authorization_surface_is_its_own_panel_reached_from_the_goal_it_is_about() -> None:
    """ADR-0254 §11's listing is **per goal**, and the page's shape says so.

    §11 adds no cross-goal read — *"a cross-goal read would have to choose between a
    truncated answer and an unbounded one"* — so there is no button in the choice row
    that would open one, and the panel is reached from a goal row. The id the request
    carries is therefore the row's own rather than one typed into a field.

    **Two paths and no third** (§16's closed roster), and neither reaches the goal acts:
    a page that posted ``/goal/abandon`` from a withdrawal control would give up the
    work when the owner meant to withdraw an authority.
    """
    script = _code("app.js")
    document = _asset("index.html")

    assert '<section id="authorizations"' in document
    assert 'id="authorizations-button"' not in document
    assert 'id="authorization-list"' in document
    # The goal line and the settlements sit **outside** the list, which the listing
    # clears: inside it, a settlement is detached before the owner can read it.
    assert 'id="authorization-goal"' in document

    authorities = "".join(
        _functions(script)[name]
        for name in ("listAuthorizations", "revokeAuthorization", "renderAuthorization")
    )
    assert "/authorizations" in authorities
    assert "/authorization/revoke" in authorities
    assert "/goal/abandon" not in authorities
    assert "/clarification/withdraw" not in authorities

    goals = "".join(_functions(script)[name] for name in ("readGoals", "withdrawClarification"))
    assert "/authorization/revoke" not in goals


def test_one_withdrawal_act_reports_where_no_listing_can_detach_it() -> None:
    """ADR-0254 §11's withdrawal, offered from two places and reported in one way.

    **One act and one result placement**, which is where rounds 1, 3, 4 and 5 converged.
    A panel-wide slot is invisible to an owner who reached the row through a reply
    (r1); an **unattributed** sentence there is read as being about whatever listing the
    panel holds when the answer lands (r3); dropping it because the panel moved on is
    silence about an act that happened (r4); and a node **inside** the row is detached
    with the row the moment the listing is cleared (r5). What survives all four is a node
    the listing does not own carrying a sentence that names the record — which is
    ``actResult`` and ``statedSettlement``.

    **And it re-reads nothing.** A refresh here is one more request to race the owner's
    next, and what the record now says goes into the page's own state instead — which is
    also what retires a record the store says is now ``REVOKED``. **The control is out of
    reach for the duration**, so two presses cannot produce two answers that contradict
    each other.

    **And it holds no element of the row it was taken on**, which is round 7's
    ``blocker``: re-open the same goal mid-act and the listing is rebuilt, so an act
    writing into the elements it closed over reports into detached DOM while the row on
    screen still reads *"still stands"* beside an enabled control. The id goes into the
    two sets and every row drawn for the record is restated from them.
    """
    script = _code("app.js")
    act = _functions(script)["revokeAuthorization"]
    result = _functions(script)["actResult"]

    assert "confirmWithdrawal(view)" in act
    assert "actResult(list, view)" in act
    assert "statedSettlement(view, done.settlement)" in act
    assert "authorizationInFlight.add(view.id)" in act
    assert '"/authorization/revoke",' in act
    assert 'done.settlement === "settled"' in act
    assert "authorizationWithdrawn.add(view.id)" in act
    assert "restateAuthorization(view)" in act
    assert "listAuthorizations" not in act, "an act does not re-read a listing"
    # Nothing the listing can detach is reachable from here: the act names the record
    # and the region, and no element of the row it was pressed on.
    for held in ("row.status", "row.controls", "row.withdraw"):
        assert held not in act, f"the act holds {held}, which a relist detaches"
    # One entry per record, in a region the listing does not own.
    assert "list.parentElement.insertBefore(region, list)" in result
    assert "node.dataset.record = key" in result
    assert 'id="authorization-said"' not in _asset("index.html"), "no slot in the markup"


def test_the_act_is_offered_in_the_panel_and_named_in_a_reply() -> None:
    """ADR-0254 §11 puts the **handle** in front of the owner at the act.

    An announcement sits in a reply the next turn replaces, so a withdrawal taken there
    would report into DOM the page has already thrown away. It names the handle and where
    the act is taken instead — which is what the command line's announcement does, and is
    what keeps the two surfaces stating the same act in the same place. Adversarial
    review, round 6, ``blocker``.
    """
    script = _code("app.js")
    row = _functions(script)["renderAuthorization"]

    assert "if (!withGoal) {" in row
    assert "Withdraw this" in row
    assert "What this authorises" in row
    # Every row names the record it is about and takes its standing from the record,
    # so a row drawn before, during or after an act says the same thing about it.
    assert "item.dataset.authorization = view.id" in row
    assert "showAuthorizationState(item, view)" in row

    state = _functions(script)["showAuthorizationState"]
    assert "authorizationWithdrawn.has(view.id)" in state
    assert "authorizationInFlight.has(view.id)" in state
    assert '"You withdrew this."' in state
    assert "restateAuthorization" in script


def test_a_view_the_record_could_not_have_produced_is_not_rendered() -> None:
    """ADR-0266 §3's kind invariants, mirrored where the page reads a member.

    ``CoverageView`` refuses a ``TERMS`` view carrying a ``MONEY`` bound and a
    ``MONEY`` view carrying a fixed value one layer up, so no conforming hub sends
    either. **This is the page refusing to render what a hub at another version,
    or a wrong one, might still send** — *"the terms: up to 50 GBP"* is a statement
    about the owner's authority that no record could have produced, and an
    undenominated fixed amount is a figure nothing gives a currency to. Adversarial
    review, round 1, ``major``.
    """
    reader = _functions(_code("app.js"))["readCoverageView"]

    assert "view.bound.kind === view.kind" in reader
    assert 'view.kind !== "money"' in reader
    # **And no calendar parsing beside them.** ADR-0266 §3 puts fixed-period validity
    # on the `core` contract and golden rule 3 keeps business logic out of an
    # interface adapter; a round-4 version of this function parsed RFC 3339 here and
    # had drifted from `period_reading_form` in both directions by the next round.
    # Architecture review, round 5, `blocker`.
    assert "Date.UTC" not in reader
    assert "readFixed" not in _code("app.js")


def test_each_bound_kind_is_read_as_the_shape_it_is() -> None:
    """ADR-0254 §2 gives every kind a required set, and a bag test admits none of them.

    A money bound whose amount and currency are both ``null`` passed a field-by-field
    optional test and rendered as ``up to null``; a terms bound with an empty set
    rendered as ``one of:``. Those are states ``ValueBound`` itself refuses, so a page
    presenting them shows a limit the record does not carry. Adversarial review,
    round 5, ``major``.

    **``currency_argument`` is gone and ``maximum_exclusive`` stands in its place**
    (ADR-0266 §3): which key carries the currency is the declaration's and never the
    bound's, while whether the ceiling itself is permitted is a fact about the bound
    that the sentence reads — so the required set moves rather than shrinks. A money
    bound arriving without it would render *"under 100"* as *"up to 100"*, which is a
    limit a cent wider than the record's.

    **An unknown kind still reports rather than refusing the whole view**, which is
    ``boundSentence``'s own arrangement for a hub at another version.
    """
    reader = _functions(_code("app.js"))["readBound"]

    assert 'bound.kind === "money"' in reader
    assert "isText(bound.maximum)" in reader
    assert "isText(bound.currency)" in reader
    assert 'typeof bound.maximum_exclusive === "boolean"' in reader
    # And a flag belonging to the money shape is refused on the other two, which is
    # the `absent` rule reaching a field a `null` test cannot see (a `bool` is not
    # `null`).
    # **Absent-as-`false` and not merely "not `true`"**: the flag is a `bool` with a
    # default, so it crosses on every bound of every kind and the `absent` test
    # cannot see it — `!== true` admitted `null`, `"true"` and `1`, each of which
    # `ValueBound` refuses. Adversarial review, round 7, `major`.
    assert reader.count("bound.maximum_exclusive === false") == 2
    assert "maximum_exclusive !== true" not in reader
    assert 'bound.kind === "period"' in reader
    assert "isText(bound.starts_at)" in reader
    assert "isText(bound.ends_at)" in reader
    # ``minimum`` is the one optional argument in the three shapes: a ``PERIOD`` states
    # its zone, so an interval without one is a different interval in every zone the
    # owner might be in (round 7, ``major``).
    assert "isText(bound.timezone)" in reader
    assert "bound.timezone === null" not in reader
    assert 'bound.kind === "terms"' in reader
    assert "bound.terms.length > 0" in reader
    assert "bound.terms.every(isText)" in reader
    # And every field of another kind must be absent, or a limit the record carries is
    # dropped from the rendering (round 6, ``major``).
    assert "absent(bound," in reader
    assert '"terms"' in reader
    assert '"starts_at"' in reader


def test_only_an_empty_array_is_an_empty_announcement() -> None:
    """ADR-0254 §11's announcement, and what a malformed value must not be read as.

    ``null``, an object or a string are shapes no conforming hub sends, and reading any
    of them as *"this turn opened none"* would silently omit authorities that may have
    come into being — with their revocation handles, which is the one thing §11 puts in
    front of the owner at the act. A malformed **non-empty** array was already reported;
    every other malformed value now is. Adversarial review, round 4, ``major``.

    Pinned over the source rather than only in the browser layer because the distinction
    is a branch, and a branch is exactly what a later edit collapses.
    """
    announcement = _functions(_code("app.js"))["renderOpenedAuthorizations"]

    assert "Array.isArray(opened) && opened.length === 0" in announcement
    assert "!Array.isArray(opened) || !opened.every(readAuthorizationView)" in announcement
    assert "GOAL_MEMBER_UNREADABLE" in announcement


def test_every_settlement_member_has_a_sentence_on_the_page() -> None:
    """ADR-0254 §16's vocabulary is closed at four, and a member with no sentence renders
    as silence.

    ``would_duplicate`` is unreachable on this surface — it is reachable only on a
    settlement to ``ESTABLISHED`` and a withdrawal settles to ``REVOKED`` — and it is
    given a sentence anyway, because the vocabulary crosses a version boundary.
    """
    script = _code("app.js")
    start = script.index("const AUTHORIZATION_SETTLEMENT_WORDS = {")
    words = script[start : script.index("\n};", start)]

    for member in ("settled", "not_at_source", "no_such_authorization", "would_duplicate"):
        assert f"  {member}:" in words, member


def test_the_chat_follows_the_stream_and_reopens_it_only_on_an_event() -> None:
    """ADR-0296 §4 and ADR-0182 §7, read together (the PR description records the reading).

    The chat follows the change stream and no clock reads it: ``chat_changes`` is read
    once, for the cursor the chat opens from, and nowhere else. What keeps the stream
    inside ADR-0182 §7 is pinned here: its clocks end it and open nothing; every ending
    **stops** the following and says so rather than reopening it; one stream is held at
    a time, and following stopping releases it; and what opens it again of the page's
    own motion is §7's two events alone, each announced — from the cursor the page last
    applied (§4:4).
    """
    script = _code("app.js")
    functions = _functions(script)
    follow = functions["followChat"]
    clocks = [call for call in _timeouts(script) if call in follow]

    assert clocks
    for clock in clocks:
        assert "reader.abort();" in clock
        for opener in ("fetch(", "relay(", "followChat(", "startFollowing(", "rearm("):
            assert opener not in clock, opener
    # The stream is asked for from the cursor, and the changes are read for the cursor
    # alone: no clock reads them.
    assert 'await fetch("/chat/follow", {' in follow
    assert "body: JSON.stringify({ after: chat.cursor })," in follow
    assert {name for name, body in functions.items() if '"/chat/changes"' in body} == {
        "readChatCursor"
    }
    # Every ending stops the following, says why, and hands the owner the control.
    for ending in (
        "CHAT_STOPPED_REFUSED",
        "CHAT_STREAM_CUT",
        "CHAT_HUB_ENDED",
        "CHAT_STREAM_STALLED",
        "CHAT_STREAM_SILENT",
        "CHAT_STREAM_MISFRAMED",
        "CHAT_STOPPED_GONE",
    ):
        assert f"stopFollowing({ending}, true);" in follow, ending
    # One stream at a time: only starting opens one, starting is refused while following,
    # and stopping releases the one held.
    assert {name for name, body in functions.items() if "followChat(" in body} == {
        "followChat",
        "startFollowing",
    }
    assert "if (!chat.open || chat.following ||" in functions["startFollowing"]
    assert "releaseChatStream();" in functions["stopFollowing"]
    # A change moves the cursor once it is applied; nothing else moves it forward but the
    # hub's own ending.
    assert "chat.cursor = value.change.seq;" in functions["applyStreamed"]
    # And only ADR-0182 §7's two events start it again of the page's own motion.
    assert 'document.addEventListener("visibilitychange", chatVisibility);' in script
    assert 'window.addEventListener("online", chatOnline);' in script
    starters = {
        name
        for name, body in functions.items()
        if "startFollowing(" in body and name != "startFollowing"
    }
    assert starters == {"loadChat", "chatVisibility", "chatOnline", "followAgain"}
    assert "startFollowing(CHAT_CAME_BACK);" in functions["chatVisibility"]
    assert "startFollowing(CHAT_NETWORK_BACK);" in functions["chatOnline"]
    # Hiding the page pauses it, and says so.
    assert "stopFollowing(CHAT_PAUSED, false);" in functions["chatVisibility"]


def test_a_device_drops_what_it_held_on_removal_and_on_holding_no_role() -> None:
    """ADR-0296 §4:8 and ADR-0298 §7:17, as the page's code states them.

    A change that leaves this device no reader of a conversation drops that
    conversation; a refusal for holding no role — of the stream, or of the changes read
    — drops every one; and no other refusal does, since a device refused for a role
    that does not allow an act still reads what it reads.
    """
    script = _code("app.js")
    functions = _functions(script)

    assert "dropConversation(change.conversation_id);" in functions["applyChanges"]
    assert "if (!readsHere(change.devices)) {" in functions["applyChanges"]
    dropping = functions["dropOnRefusal"]
    assert 'body.fault !== "device-without-role"' in dropping
    assert "chat.listing = [];" in dropping
    assert {name for name, body in functions.items() if "dropOnRefusal(" in body} == {
        "dropOnRefusal",
        "followChat",
        "readChatCursor",
    }
    # The hub's own machine reads every conversation, so it is never dropped from one.
    assert "named === HUB_DEVICE" in functions["readsHere"]


# --- ADR-0309 §5:4 and ADR-0313 §3: what retired from the page -----------------


def test_the_page_offers_no_ask_form_and_no_push_to_talk() -> None:
    """ADR-0309 §5:4: "``ask`` and the gateway's Ask panel retire", and ADR-0313 §3:4:
    "the ``POST /ask/spoken`` route, the 'Hold to talk' control, and the page script
    that records, sends and renders a spoken turn" retire.

    Read off both files: a control left in the document would be one the owner could
    press, and a path left in the script would be a request the gateway answers with a
    ``404``. The chat is the way to talk to the assistant (§5:4).
    """
    script = _code("app.js")
    document = _markup("index.html")

    for path in ('"/ask"', '"/ask/spoken"'):
        assert path not in script, path
    for identifier in ("ask-form", "utterance", "talk-button", "stop-talking", "heard"):
        assert f'id="{identifier}"' not in document, identifier
        assert f'el("{identifier}")' not in script, identifier
    for recording in ("MediaRecorder", "getUserMedia"):
        assert recording not in script, recording
    assert 'id="chat-button"' in document


def test_a_notification_is_shown_as_text_and_never_played() -> None:
    """ADR-0313 §3:5: "The page plays no spoken notification: its playback retires with
    push-to-talk, and a notification is shown as text."

    So the reader renders every notification and does nothing else with it, and nothing
    on the page decodes or plays audio: ``spoken`` is ``null`` on every value the gateway
    writes (§3:6), and a page that still read it would be keeping a playback path alive
    for a member that carries nothing.
    """
    script = _code("app.js")
    reading = _functions(script)["readDeliveries"]

    assert "renderNotification(value);" in reading
    assert "value.spoken" not in script
    for playback in ("AudioContext", "decodeAudioData", "playNotification", "AudioBuffer"):
        assert playback not in script, playback
