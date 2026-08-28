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
from pathlib import Path
from typing import Final

import pytest

from ai_assistant.core.errors import AssistantError
from ai_assistant.core.types import (
    DEFAULT_NOTIFICATION_REACH,
    BeliefBand,
    DiscloserProvenance,
    GrantScope,
    NotificationCondition,
    NotificationReach,
    RoutableOperation,
    SpokenAudioFormat,
)
from ai_assistant.interfaces.gateway.records import RefusalCondition
from ai_assistant.interfaces.gateway.server import (
    _POLICY,
    _REFUSAL_STATUS,
    _relay_fault,
    packaged_bundle,
)
from ai_assistant.wire.errors import TransportError

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


#: The two statuses ``_REFUSAL_STATUS`` gives to a condition that ends this browser's
#: session, and to no other condition — so the page may read the condition back off the
#: head alone when the body it would otherwise read never arrives (ADR-0182 §6). Named
#: once because two checks below turn on it: that the page maps exactly these, and that
#: the *other* pre-engine table does not duplicate them.
SESSION_REFUSAL_STATUSES: Final = frozenset({401, 409})


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
    assert set(boxes) == {"stream-answer", "band-asserted", "band-derived", "band-attested"}
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
    for identifier in ("new-conversation", "watch-button", "panel-index"):
        assert " hidden" in _tag(document, identifier), identifier
    script = _code("app.js")
    assert 'el("new-conversation").hidden = id === null;' in script
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
    # The page now stores one other thing, and it is **not** a session half: which
    # conversation this view is reading, which is the tab's rather than the origin's.
    # So the clause is asserted where it is about — no half of a session is ever in
    # tab-scoped storage — and the one key that is, is named.
    assert set(re.findall(r"window\.sessionStorage\.\w+\((\w+)", script)) == {"CONVERSATION_KEY"}


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


def test_the_front_end_continues_the_conversation_the_hub_named() -> None:
    """The id the hub hands back is "what a client keeps and presents to continue"
    (ADR-0074 §2), and a page that rendered it without sending it back would start
    a fresh conversation on every question the owner asked.

    Held in the session's own key family, which is the reversal #1429 asks for and
    the milestone-14 phone QA is the evidence behind: an earlier draft kept it in page
    state alone, so a reload silently started a conversation the owner never asked for
    (#1371's first clause). Web storage is scoped to scheme, host and port — the
    property ADR-0168 §6 relies on for the header half — so the id at
    ``127.0.0.1:8422`` is unreadable from ``127.0.0.1:9000``.

    It admits nothing on its own. Every request carrying it is admitted by §6's two
    values and by nothing else, so an id read out of storage without them reaches no
    conversation.
    """
    script = _code("app.js")

    assert "conversationId" in script
    assert "asked.conversation_id = conversationId" in script
    assert "localStorage.setItem(STORAGE_KEY" in script
    assert 'const CONVERSATION_KEY = "assistant.session.conversation-id";' in script
    assert "let conversationId = storedConversation();" in script


def test_the_conversation_a_view_is_reading_is_the_tabs_and_not_the_origins() -> None:
    """ADR-0168 §6 names the difference the two values want. The header half is "shared
    across that origin's tabs" because it admits the browser; which conversation you are
    reading is not — it is what *this view* is looking at, and two tabs are two views.

    In `localStorage` it would be one selection for the whole origin, so a second tab
    choosing a thread would retarget the first tab's next question at its own reload.
    Adversarial review raised that on round 1 and it is right; the tab's own storage
    survives a reload, which is all that was asked, and stops there.
    """
    script = _code("app.js")

    assert "window.sessionStorage.getItem(CONVERSATION_KEY)" in script
    assert "window.sessionStorage.setItem(CONVERSATION_KEY, id)" in script
    assert "localStorage" not in _functions(script)["setConversation"]
    assert "localStorage" not in _functions(script)["storedConversation"]


def test_the_conversation_is_destroyed_with_the_session_it_sits_beside() -> None:
    """Three routes end one and all three go through the same place: this view's
    session half being forgotten, a new bootstrap exchange, and forgetting the
    conversation itself.

    **Tidiness rather than a guarantee, and the difference is worth stating.** A
    conversation is the hub's and outlives every gateway session by construction —
    ``assistant ask --conversation`` at a terminal reaches one under whatever session
    is current — and the id admits nothing on its own (ADR-0168 §6's two values do).
    So this asserts what the page does with its own selection, and claims nothing
    about a second tab that bootstraps a replacement session: that tab clears its own
    and no other, exactly as it did before this file stored one at all.
    """
    functions = _functions(_code("app.js"))

    assert "changeConversation(null);" in functions["forgetHeaderHalf"]
    assert "changeConversation(null);" in functions["startSession"]
    assert "changeConversation(null);" in functions["forgetConversation"]
    assert "window.sessionStorage.removeItem(CONVERSATION_KEY);" in functions["setConversation"]


def test_the_page_says_which_conversation_the_next_question_lands_in() -> None:
    """#1371's first clause, which is the half of that issue #1429 puts in this lane.

    "None yet" is said rather than left blank: the hint was empty until a turn came
    back, and an empty line is what left the owner on the phone unable to tell a fresh
    thread from a continued one. The other two clauses of #1371 — prior turns rendered
    on resume, and a legible outcome for forget — are not taken here.
    """
    script = _code("app.js")
    setter = _functions(script)["setConversation"]

    assert "No conversation yet. Your next question starts one." in setter
    assert "Your next question continues it." in setter
    # Said on load and not only after a turn, which is what makes the persisted id
    # visible at all.
    assert "setConversation(conversationId);" in _functions(script)["showConsole"]


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

    assert 'value.kind === "chunk"' in script
    assert 'value.kind === "notification"' in script
    assert "TERMINAL_KINDS.has(value.kind)" in script


def test_the_page_tells_a_terminal_value_from_a_body_that_simply_stopped() -> None:
    """§2: "a reader that reached a terminal value has the whole of what the gateway
    sent; a reader that did not has a transport failure and the front end reports it
    as one, which is ADR-0168 §9's distinction reaching the browser"."""
    script = _code("app.js")

    assert "terminal === null" in script
    assert "ANSWER_STREAM_CUT" in script
    assert "DELIVERY_STREAM_CUT" in script
    assert script.count("ended before the gateway finished it") == 2


def test_a_cut_answer_stream_leaves_no_partial_answer_on_screen() -> None:
    """§2 makes a body that ended without a terminal value a **transport failure**, and
    ADR-0173 §3 makes the terminal outcome's ``reply`` the answer — "no front end
    treats an accumulated chunk sequence as the record of what the assistant said".

    Leaving the chunks on screen renders a non-answer exactly as ADR-0173 §6's fourth
    shape is rendered: an answer owed and *partly* produced, which arrives as a
    terminal outcome carrying ``reply_degraded`` and is said to be incomplete in the
    same breath. That distinction is what ``renderReply``'s middle branch exists to
    keep, and a cut stream is not that shape.

    Nothing is lost by clearing it: ADR-0175 §10 declines resuming an interrupted
    stream (#1314), so the whole of the recovery is asking again.
    """
    streaming = _functions(_code("app.js"))["askStreaming"]
    cut = streaming.index("if (terminal === null) {")

    assert streaming.index("clearNode(panel);", cut) < streaming.index("ANSWER_STREAM_CUT")
    assert streaming.index('show("answer", false);', cut) < streaming.index("ANSWER_STREAM_CUT")


def test_the_two_stream_endings_are_not_one_message() -> None:
    """One wording served both while the delivery stream was the second reader of it,
    and it told an owner whose notifications had stopped that "the connection carrying
    that answer" had gone.

    The condition is the same one — §2's body that ended without a terminal value —
    and what was cut is not, so the sentence about what to do next is not either.
    """
    script = _code("app.js")

    assert "A cut stream is asked again, not resumed." in script
    assert "this browser has stopped watching" in script
    assert "Start watching again." in script
    assert "ANSWER_STREAM_CUT" in _functions(script)["askStreaming"]
    assert "DELIVERY_STREAM_CUT" in _functions(script)["readDeliveries"]


def test_the_page_renders_the_terminal_reply_over_what_it_accumulated() -> None:
    """§3: "The terminal ``TurnOutcome``'s ``reply`` is the answer; where a rendered
    chunk sequence and it disagree, the front end renders the terminal ``reply``; and
    no front end treats an accumulated chunk sequence as the record of what the
    assistant said."

    ``renderOutcome`` clears the panel before rendering, so the chunks the owner
    watched arrive are replaced by the outcome's own reply rather than left standing
    beside it.
    """
    script = _code("app.js")

    assert "composing.textContent += value.text;" in script
    assert "renderOutcome(terminal.outcome, chosenAt);" in script
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


def test_the_page_offers_both_turn_entries_and_falls_back_to_neither() -> None:
    """§3: keeping the non-streaming entry "is a decision and not inertia" — ADR-0173
    §5 makes a provider that cannot stream a ``ModelError`` before any delta, so a
    browser with only the streaming entry would answer nothing at all on a build where
    the CLI answered normally.

    And the fallback is refused: ADR-0168 §9 forbids the gateway retrying silently,
    ADR-0173 §7 refuses the same fallback one layer in, and "a second attempt is the
    caller asking again" — which is why the choice is a control the owner can see.
    """
    script = _code("app.js")

    assert '"/ask/stream"' in script
    assert '"/ask"' in script
    assert 'el("stream-answer").checked' in script
    # Each entry is named exactly twice — where it is defined, and at the one call
    # site the checkbox reaches. A third mention would be a second way in, which is
    # what an automatic fallback from a failed stream would have to be.
    assert script.count("askWhole(") == 2
    assert script.count("askStreaming(") == 2


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


def test_the_page_records_with_mediarecorder_and_uploads_one_whole_recording() -> None:
    """§10: the front end "records with ``MediaRecorder``", and "the recording is
    uploaded complete, in one request… No WebSocket, no protocol upgrade, no
    ``EventSource`` and no chunked upload".

    The negative half is what the enumeration buys: a page that opened a socket for the
    upload would satisfy every other check in this file.
    """
    script = _code("app.js")

    assert "new MediaRecorder(" in script
    assert '"/ask/spoken"' in script
    assert "WebSocket" not in script
    assert "EventSource" not in script


def test_the_page_sends_the_three_members_the_route_reads_and_no_deadline() -> None:
    """ADR-0200 §10: the body carries "the **browser-owned** arguments of §3's signature
    and no others — ``utterance``, ``plays`` and ``conversation_id``", and the gateway
    supplies the deadline of its own.

    A page that sent one would not be refused — §10 makes a body's ``timeout`` *never
    read* rather than rejected — so nothing at run time would report it, and the front
    end asserting a deadline it has no standing to choose would go unnoticed
    (ADR-0177 §1's fifth clause).
    """
    sending = _functions(_code("app.js"))["sendRecording"]

    assert "asked.utterance" in sending
    assert "asked.plays" in sending
    assert "asked.conversation_id" in sending
    assert "timeout" not in sending


def test_the_formats_the_page_names_are_the_vocabulary_the_surface_carries() -> None:
    """ADR-0200 §9's ``SpokenAudioFormat`` is a closed vocabulary, and a page naming a
    member it does not carry would be refused at the door with nothing to say about why.

    Read against the enum rather than against a list in this file, so a member added on
    a measurement (§9 permits that, and only that) fails here until the page names it.
    """
    declared = _declaration(_code("app.js"), "TALK_FORMATS")

    for member in SpokenAudioFormat:
        assert f'"{member.value}"' in declared, member
    assert declared.count('"audio/') == len(SpokenAudioFormat)


def test_the_rendering_is_played_without_a_url_the_policy_would_refuse() -> None:
    """ADR-0168 §6 serves every response under a policy permitting media "from its own
    origin alone", and `media-src 'self'` matches neither a ``blob:`` nor a ``data:``
    URL — the only two ways to hand a media element bytes the page is holding.

    So the rendering is decoded directly (ADR-0200 §10's "the browser's ordinary audio
    playback", through the Web Audio decoder), and the two URL schemes are absent from
    the script. A lane reaching for one of them would be widening a ratified security
    clause to make one control work, which is the change this pins against.
    """
    script = _code("app.js")

    assert "decodeAudioData(" in script
    assert "createObjectURL(" not in script
    assert "blob:" not in script
    assert "data:audio" not in script
    assert "media-src 'self'" in _POLICY


def test_the_control_ships_hidden_and_is_offered_only_where_a_microphone_can_be() -> None:
    """ADR-0200 §10 and ADR-0202: a browser withholds a microphone from a page whose
    origin it does not consider trustworthy, and gives no legible account of why.

    So the control ships ``hidden`` — whether the browser will hand this page a
    microphone is a fact only a script can ask for — and where the answer is no it is
    revealed **disabled beside the sentence saying why**, which is the legible state an
    owner can act on. Absent and unexplained is not.
    """
    assert "hidden" in _tag(_markup("index.html"), "talk-button")
    offering = _functions(_code("app.js"))["offerTalk"]

    assert "navigator.mediaDevices" in offering
    assert "button.disabled = !usable" in offering
    assert 'saying(usable ? "" : NO_MICROPHONE)' in offering


def test_the_press_is_held_by_pointer_and_by_keyboard_and_never_by_a_click() -> None:
    """A control that is *held* needs the press and the release apart, and a ``click``
    is the two collapsed into one event.

    The pointer pair covers mouse, pen and touch together — a second ``touchstart``
    listener would double-fire wherever a browser sends both — and ``setPointerCapture``
    is what makes a release land here after the finger has drifted off the button.
    ``preventDefault`` on the keyboard pair is what stops a native button turning Space
    and Enter into an activation on top of it (#1429's accessibility floor: the control
    is reachable and operable from the keyboard).
    """
    script = _code("app.js")

    for event in ("pointerdown", "pointerup", "pointercancel", "keydown", "keyup"):
        assert f'talkButton.addEventListener("{event}"' in script, event
    assert "setPointerCapture(" in script
    assert 'talkButton.addEventListener("click"' not in script
    assert 'talkButton.addEventListener("touchstart"' not in script


def test_the_held_control_keeps_the_gesture_the_browser_would_otherwise_take() -> None:
    """A phone claims a press for a scroll or a double-tap zoom, which fires
    ``pointercancel`` a moment in and ends a recording the owner is still speaking into;
    a long press selects the label and raises the selection handles over the control
    being held. Both are declarations rather than script, so they are pinned here."""
    rule = _rule(_style("app.css"), "#talk-button")

    assert "touch-action: none;" in rule
    assert "user-select: none;" in rule


def test_the_transcript_is_shown_outside_the_panel_the_next_turn_clears() -> None:
    """ADR-0200 §4: "``heard`` is disclosed to the caller on every call that produced a
    transcript. A push-to-talk surface that cannot show the user what it heard cannot be
    corrected by them, and a transcript the hub acted on but never showed is the one part
    of this path a user has no other way to inspect."

    Outside ``#answer-body`` because ``renderOutcome`` clears that node on every turn —
    including the typed one an owner asks *because* they read what was heard and it was
    wrong.
    """
    document = _markup("index.html")
    heard = _functions(_code("app.js"))["heardWas"]

    assert 'id="heard"' in document
    assert 'id="answer-body"' not in _tag(document, "heard")
    assert 'el("heard").textContent' in heard


def test_a_recording_with_no_words_and_an_unspoken_answer_are_neither_of_them_faults() -> None:
    """ADR-0200 §4's two shapes a reader should be able to name from the four members.

    A recording that carried no words "is not an error and no exception is raised for
    it", so it is said in the page's own hint rather than in the fault surface, where it
    would teach an owner that a quiet room is something going wrong. An answer that could
    not be spoken is a **degradation**: the answer is on screen and complete, and what is
    missing is the audio — ADR-0170 §6's rule that a degraded turn is a statement and
    never silence, one stage further on.
    """
    rendering = _functions(_code("app.js"))["renderSpokenTurn"]

    assert "saying(HEARD_NOTHING)" in rendering
    assert "turn.spoken_degraded" in rendering
    assert 'line(el("answer-body"), NOT_SPOKEN, "notice")' in rendering
    assert "fault(" not in rendering


def test_a_recorder_that_refuses_to_start_does_not_wedge_the_control() -> None:
    """Found by driving the page, and the reason it is pinned here.

    ``new MediaRecorder`` and ``recorder.start`` both throw **synchronously** — an
    unsupported type at the first, a track the browser will not encode at the second —
    and an escaping throw leaves that press in flight for the life of the page: ``press``
    stays set, so every later press returns at the top of ``startTalking``, and the line
    on screen still reads "Listening". The control is then dead until the page is
    reloaded, which is #1500's failure on a different control.

    Both guards give the microphone back as well, because a page that has stopped
    listening must not leave the browser's recording indicator up.
    """
    starting = _functions(_code("app.js"))["startTalking"]

    assert starting.count("} catch (") == 3
    assert starting.count("fault(RECORDER_REFUSED,") == 2
    assert starting.count("releaseMicrophone(stream)") == 3
    assert starting.count("press = null") == 4


def test_a_spoken_wait_that_never_settles_does_not_hold_the_owners_control_for_ever() -> None:
    """Issue #1500's condition on the third turn entry, found by adversarial review.

    ``sendRecording`` disables ``#talk-button`` before the request goes out and re-enables
    it in a ``finally``; ``fetch`` carries no deadline of its own, so a socket that dies
    without settling leaves that ``await`` pending for ever, the ``finally`` never runs,
    and the owner's one way into the assistant by voice stays greyed out until the page is
    reloaded.

    **The remedy is a control and not a bound** — ADR-0182 §7's fifth clause has the page
    re-issue no request of its own motion, so "offering the owner a visible retry costs
    one control and removes the class". It sends nothing and cancels nothing: a control
    that re-recorded would be the silent retry ADR-0168 §9 forbids wearing a button's
    clothes.

    **Its own control rather than a share of the Ask panel's**, because an owner with a
    typed question out and a recording out has two waits to leave and needs one control
    each.
    """
    script = _code("app.js")
    sending = _functions(script)["sendRecording"]
    abandoning = _functions(script)["abandonSpoken"]

    assert "hidden" in _tag(_markup("index.html"), "stop-talking")
    assert 'el("stop-talking").addEventListener("click", abandonSpoken)' in script
    assert "new AbortController()" in sending
    assert "signal: mine.stopping.signal" in sending
    # **And it is armed with nothing awaited between there and the request** (round 2's
    # first major). `SPOKEN_ABANDONED` says the recording was sent and the turn may have
    # run; offering it while the base64 was still being made would have said that of a
    # press no request had gone out for. The window is closed rather than given a second
    # sentence — encoding is arithmetic and cannot stall the way a socket can.
    assert sending.index("await base64Of(") < sending.index("new AbortController()")
    assert sending.index('el("stop-talking").hidden = false') < sending.index("await fetch(")
    armed = sending.index("new AbortController()")
    assert "await" not in sending[armed : sending.index("await fetch(")]
    assert "mine.stopping.abort()" in abandoning
    assert "fault(SPOKEN_ABANDONED," in abandoning
    # The control comes back through one function, which is what makes it come back on the
    # endings that never settle as well as the ones that do.
    assert "releaseTalk()" in abandoning
    assert "if (press === mine) {" in sending
    # And the wait that was stopped does not then report the gateway as gone: an abort the
    # owner asked for is an act rather than a failure, and `abandonSpoken` has already
    # said what happened.
    assert "if (mine.stopping === null || !mine.stopping.signal.aborted) {" in sending


def test_the_audio_context_is_built_inside_the_press_that_leads_to_the_playback() -> None:
    """Adversarial review, round 1, major. A browser enforcing *transient* activation for
    Web Audio starts a context created after the upload suspended and refuses the
    ``resume`` — so a perfectly good rendering came back and was reported as one this
    browser could not play.

    That is not hypothetical on the browser milestone 19's exit test names: WebKit holds
    the strict rule and the exit test is a phone. ``startTalking`` runs inside the
    ``pointerdown`` or ``keydown`` handler, so the context is built there, **before any
    await**, and held for the life of the page — closing it after a rendering would put
    the next playback back outside a gesture, which is the defect.
    """
    script = _code("app.js")
    starting = _functions(script)["startTalking"]
    playing = _functions(script)["playSpoken"]

    assert starting.index("readyToPlay()") < starting.index("await navigator.mediaDevices")
    assert "new AudioContext()" not in playing
    assert "const context = listeningContext" in playing
    assert script.count("new AudioContext()") == 1
    # Held rather than closed, which is the whole of what makes the *next* playback work.
    assert ".close()" not in playing


def test_a_late_playback_failure_cannot_land_under_a_later_answer() -> None:
    """Adversarial review, round 2, major. ``playSpoken`` awaits the decoder, and while
    that is pending the owner can ask again — ``renderOutcome`` clears ``#answer-body``,
    so a rejection landing after that appended "could not play" under an answer whose
    audio played perfectly, attributing one turn's silence to another.

    The turn keeps a slot of its own for the notice it may owe, and the next render
    detaches it, so ``isConnected`` is the whole test — ``abandonAsk``'s own device for
    the same question about the same panel.
    """
    script = _code("app.js")
    rendering = _functions(script)["renderSpokenTurn"]
    writing = _functions(script)["couldNotPlay"]

    assert 'const slot = line(el("answer-body"), "", "notice")' in rendering
    assert "void playSpoken(turn.spoken, slot" in rendering
    assert "if (!slot.isConnected) {" in writing
    # The notice is written through that one function and nowhere else, so a later caller
    # cannot reach the panel around the check.
    assert script.count("COULD_NOT_PLAY") == 2


def test_a_press_ends_the_answer_that_is_still_being_spoken() -> None:
    """Issue #1696, the owner's ruling of 2026-08-28 from a real iPhone: push-to-talk
    **is an interrupt**.

    A buffer the page had already started kept playing well after the owner had read the
    answer, and pressing to talk did not stop it — while the recording that press began
    was hearing the assistant's own loudspeaker, which is #1318 design note 1 §3(c)'s
    self-hearing case arriving at the page before it arrives at the hub.

    **Ahead of every one of ``startTalking``'s guards**, because what the owner asked for
    by pressing is the silence: a page that stopped the sound only on the presses that
    went on to record something would be answering a different act.

    **A statement and not a fault**, for ``NOT_SPOKEN``'s reason — the interruption is the
    owner's own doing and the answer above it is complete, so what is said is where the
    sound stopped and nothing more.
    """
    script = _code("app.js")
    starting = _functions(script)["startTalking"]
    interrupting = _functions(script)["interruptPlayback"]
    stopping = _functions(script)["stopPlaying"]

    assert starting.index("interruptPlayback()") < starting.index("if (press !== null")
    assert starting.index("interruptPlayback()") < starting.index("readyToPlay()")
    assert "mine.source.stop()" in stopping
    assert "playbackInterrupted(ended.slot)" in interrupting
    assert "fault(" not in interrupting
    assert "fault(" not in stopping
    # Written through that one function and nowhere else, which is `couldNotPlay`'s rule
    # for the other notice this panel takes: a slot the next render detached belongs to an
    # answer that is no longer on screen.
    assert "if (!slot.isConnected) {" in _functions(script)["playbackInterrupted"]
    assert script.count("PLAYBACK_INTERRUPTED") == 2


def test_a_decode_the_press_overtook_starts_no_source() -> None:
    """The half of #1696 that stopping a live ``AudioBufferSourceNode`` does not reach.

    ``playSpoken`` awaits a resume and then a decoder before it has any source to stop, so
    a press landing in that window has nothing to call ``stop`` on. Without the check the
    rendering the owner interrupted would begin speaking a moment *after* they had begun
    — the same defect one beat later, and the harder one to see.

    The record is the identity: ``interruptPlayback`` clears it **before** it stops
    anything, and the comparison after the decoder is what reads that. The source is put
    into the record only once it has started, because a source that has not started cannot
    be stopped and a record naming one would have the interrupt throw rather than
    interrupt.
    """
    script = _code("app.js")
    playing = _functions(script)["playSpoken"]
    stopping = _functions(script)["stopPlaying"]

    assert "playing = mine" in playing
    assert stopping.index("playing = null") < stopping.index("mine.source.stop()")
    assert playing.index("await context.decodeAudioData(") < playing.index("if (playing !== mine)")
    assert playing.index("if (playing !== mine)") < playing.index("soundFrom(context, mine, 0)")
    # A source is armed and started in one place, and taken onto the record only once it
    # has started. A first playing and a resume both reach it (#1701), so neither can grow
    # an order of its own and the check above reads for both.
    sounding = _functions(script)["soundFrom"]
    assert sounding.index("source.start(0, offset)") < sounding.index("mine.source = source")
    assert script.count("createBufferSource()") == 1


def test_one_playback_is_in_the_air_and_taking_the_record_over_ends_it() -> None:
    """Adversarial review, round 1, ``major``.

    The record names the playback this page has in the air, and writing a new one over it
    without ending the old one is a page with two answers sounding at once — where a
    press would then stop only the later of them, leaving the earlier audible into the
    microphone the same press opens.

    **The sequence the finding describes is unreachable through the control**: every
    spoken answer arrives from a press, and the press interrupted before its request went
    out, so there is never a first playback left for the second answer to land on. That
    is why the invariant is stated where the record is taken over rather than left to be
    inferred from the only caller there happens to be today — and it is stated silently,
    because a replacement is not an interruption and the slot the old answer kept has
    been detached by the render that replaced it.
    """
    script = _code("app.js")
    playing = _functions(script)["playSpoken"]

    assert playing.index("stopPlaying()") < playing.index("playing = mine")
    assert playing.index("stopPlaying()") < playing.index("await ")
    # Through the one function that ends a playback, so there is no second way to leave a
    # source sounding with nothing holding it.
    assert script.count("mine.source.stop()") == 1


def test_a_press_landing_after_a_natural_end_does_not_say_it_interrupted_one() -> None:
    """Issue #1705, deferred from PR #1702's adversarial review as a ``minor``.

    ``ended`` is a **queued task** and not a synchronous callback, so a source that
    reached its natural end still names itself in ``playing`` for the moments between the
    two. A press landing in that window found the record, stopped a source that had
    already finished — harmless, and the ``try`` around it exists for exactly that — and
    then wrote "this answer stopped being spoken" under an answer whose audio had been
    heard in full.

    What tells the two apart is where the sound had reached, and it has to be arithmetic
    over the audio context's own clock rather than a second listener: the whole of the
    window is *before* the queued one runs, so there is no event to wait for inside it.
    ``stopPlaying`` stamps the reading before it stops the source, because after ``stop()``
    there is no clock left to read it from and both callers that need it run afterwards.
    """
    script = _code("app.js")
    stopping = _functions(script)["stopPlaying"]
    interrupting = _functions(script)["interruptPlayback"]
    reading = _functions(script)["playedSoFar"]
    elapsed = _functions(script)["playbackElapsed"]

    assert stopping.index("mine.played = playedSoFar(mine)") < stopping.index("mine.source.stop()")
    assert interrupting.index("if (playbackElapsed(ended)) {") < interrupting.index(
        "playbackInterrupted(ended.slot)"
    )
    # The context's clock and not the page's: `currentTime` advances with the audio, so a
    # context the browser suspended part-way through accrues no playback nobody heard.
    assert "listeningContext.currentTime - mine.startedAt" in reading
    assert "Date.now()" not in reading
    assert "mine.buffer.duration" in reading
    assert "mine.played >= mine.buffer.duration" in elapsed
    # Read off the record, never from a second `ended` listener — which is what makes the
    # question answerable inside the window at all. There is one such listener in the file.
    assert "addEventListener" not in elapsed
    assert script.count('addEventListener("ended"') == 1


def test_a_press_that_asked_nothing_gives_the_answer_back_where_it_stopped() -> None:
    """Issue #1701, the owner's direction of 2026-08-28.

    A press is an interrupt (#1696), and an interrupt the owner did not mean to make is a
    silence they did not ask for. ADR-0200 §4's no-words release is the one ending that
    says so: "nothing was asked, so nothing was answered, no turn ran, no episode was
    captured and no conversation was created". The answer that was sounding is still the
    answer and the page is still holding its decoded buffer, so it is given back from
    where the sound stopped.

    **Page-locally, and that is the whole point.** One more source, no request, nothing
    re-rendered — so the accident never reaches the hub as a gap in a delivery it is told
    about. ADR-0205 §8 names this sibling and says what makes that legible: "a resume that
    never left the page produces no report".

    **A record of its own rather than the one the press ended**, because the stopped
    source's ``ended`` listener still names the old record — and a resume that reused it
    would hand that queued task a live playback to let go of, defeating the identity check
    that makes the listener safe.

    **And where it cannot resume, the interruption's own sentence stands.** A context that
    is not running, a slot the next render detached, a source the browser will not start:
    "this answer stopped being spoken" is true in each of those, so it is the fallback
    rather than something to clear first.
    """
    script = _code("app.js")
    rendering = _functions(script)["renderSpokenTurn"]
    interrupting = _functions(script)["interruptPlayback"]
    resuming = _functions(script)["resumeInterrupted"]

    # Held by the press that ended it and dropped at the top of every press, before
    # anything decides to keep one: what a release can resume is its own press's playback
    # or nothing at all.
    assert interrupting.index("held = null") < interrupting.index("held = ended")
    # Consumed on the no-words release and on no other ending — the declaration and its
    # one caller are the two occurrences in the file.
    assert rendering.index("saying(HEARD_NOTHING)") < rendering.index("resumeInterrupted()")
    assert script.count("resumeInterrupted()") == 2
    # Nothing leaves the page.
    assert "fetch(" not in resuming
    assert "/ask/spoken" not in resuming
    assert "fault(" not in resuming
    # One playback in the air, which taking the record over is what ends (PR #1702).
    assert resuming.index("stopPlaying()") < resuming.index("playing = resumed")
    # From where the sound stopped, onto a record of its own.
    assert "played: mine.played" in resuming
    assert "soundFrom(context, resumed, mine.played)" in resuming
    # The two conditions that leave the interruption's sentence standing instead.
    assert "!mine.slot.isConnected" in resuming
    assert 'context.state !== "running"' in resuming
    # The notice replaces that sentence, through the one writer that owns it.
    assert "playbackResumed(resumed.slot)" in resuming
    assert "if (!slot.isConnected) {" in _functions(script)["playbackResumed"]
    assert script.count("PLAYBACK_RESUMED") == 2


def test_how_much_of_an_answer_sounded_is_one_value_across_a_resume() -> None:
    """What #1701's resume owes #1700's report, so that the two do not disagree.

    ADR-0205 §7 has the page report ``COMPLETE`` "where the source ended of its own
    accord", with both durations "the decoded buffer's own", and ``INTERRUPTED`` "where a
    press ended it", with "a measured elapsed ... read only where the playback was cut
    short". A resume that measured only its own source would make an answer taken up again
    and heard to its end report the *remainder* — an answer heard in full reported as
    interrupted, which is the failure that ADR exists to remove arriving from the page.

    So the reading is one value: the offset a source started from plus what the context's
    clock has advanced since, carried across the resume as the new record's offset, and
    stamped by whichever ending got there — the press through ``stopPlaying``, the natural
    end through the buffer's own duration. This lane implements no report; what it owes is
    a value the lane that does can read.
    """
    script = _code("app.js")
    reading = _functions(script)["playedSoFar"]
    sounding = _functions(script)["soundFrom"]
    resuming = _functions(script)["resumeInterrupted"]

    assert "mine.offset + (listeningContext.currentTime - mine.startedAt)" in reading
    assert "Math.min(Math.max(sounded, 0), mine.buffer.duration)" in reading
    # A source that ended by itself played the whole buffer, and the record says so.
    assert "mine.played = mine.buffer.duration" in sounding
    assert sounding.index("mine.offset = offset") < sounding.index("source.start(0, offset)")
    assert "mine.startedAt = context.currentTime" in sounding
    # Carried across the resume rather than restarted at zero: the new source begins at
    # nothing behind it, and what is behind the *playback* is the reading it inherits.
    assert "played: mine.played" in resuming
    assert "offset: 0" in resuming
    # The resumed record keeps the same subject, so a resume that runs to its end
    # reports `COMPLETE` of the turn the press already reported `INTERRUPTED` of —
    # which the hub answers by performing nothing, a turn being stamped once
    # (ADR-0205 §1). The page needs no rule of its own to keep that true.
    assert "episode: mine.episode" in resuming
    assert "conversation: mine.conversation" in resuming
    sending = _functions(script)["sendRecording"]
    assert "asked.utterance" in sending
    assert "asked.plays" in sending
    assert "asked.delivery = played" in sending


def test_a_recorder_that_would_not_start_is_advised_on_what_the_page_actually_knows() -> None:
    """Issue #1694, found by the milestone-19 QA run (#1691) and filed rather than fixed.

    Two claims around a guard that behaves correctly. ``MediaRecorder.isTypeSupported``
    answers ``true`` for a type the browser *recognises*; it promises no encoder for it.
    ``chromium_headless_shell`` answers ``true`` for both members of ``TALK_FORMATS`` and
    then throws ``NotSupportedError: no encoder`` out of ``start()`` — on a live track, and
    identically with no options at all. The comment calling that method "the browser's own
    answer about its own encoder" claimed a guarantee the platform does not give, and the
    claim was load-bearing: it is the stated reason the format is chosen from that call.

    And "holding the button again is the thing to try" is right for a transient refusal and
    wrong for a browser with no encoder, where every press fails identically. Nothing in
    the page can tell those apart — ``start()`` throws the same error for both — so the
    sentence names the two conditions it cannot distinguish instead of advising one of
    them, and keeps the half that works either way.

    **Read from the shipped file and not from :func:`_code`.** What was wrong here was a
    *comment*, and the second of the two claims is one — so the check that it no longer
    stands has to read the text that carries it, which the comment-stripped view by
    construction cannot. The withdrawn phrase is asserted absent from the whole file for
    the same reason: a claim moved into prose is a claim the page still makes.
    """
    script = _code("app.js")
    document = _asset("app.js")
    refused = _constant(script, "RECORDER_REFUSED")

    assert "Holding the button again is the thing to try" not in document
    assert "the page cannot tell" in refused
    assert "Typing works either way." in refused
    # The handling was never what was wrong: both guards stand, and both still say this.
    assert _functions(script)["startTalking"].count("fault(RECORDER_REFUSED,") == 2
    assert "the browser's own answer about its own encoder" not in document
    assert "promises only that the type is one the browser *recognises*" in document
    assert "`start()` is the only real test" in document


def test_the_audio_context_is_resumed_from_every_state_that_is_not_running() -> None:
    """Issue #1690, deferred from PR #1687's adversarial review as a ``minor``.

    ``AudioContextState`` has a third member some browsers use — ``"interrupted"``, where
    WebKit puts a context when a call arrives or another application takes the audio
    session. A branch naming ``"suspended"`` alone leaves a context in it unresumed, and
    the failure is silent in **both** directions: ``decodeAudioData`` still succeeds,
    ``start()`` produces no sound, and nothing throws, so the "could not play" notice is
    never reached either. The owner is left with an answer the page believes it spoke,
    which is the worst of the three outcomes.

    So the resume is fired on every state that is not ``"running"``; its promise is
    awaited in ``playSpoken`` rather than dropped, since ``readyToPlay`` runs inside the
    press and cannot know from there whether it worked; the state is asked again after
    that, because a context can leave ``"running"`` after the press that built it; and a
    context that will not run reaches the notice rather than the silence.
    """
    script = _code("app.js")
    ready = _functions(script)["readyToPlay"]
    playing = _functions(script)["playSpoken"]

    assert 'listeningContext.state !== "running"' in ready
    assert '=== "suspended"' not in ready
    assert "resuming = Promise.resolve(listeningContext.resume())" in ready
    # The rejection is observed where it is started as well as where it is awaited: a
    # press need not produce a spoken answer at all, and a rejection nothing is waiting on
    # is an unhandled rejection in the console — noise this page does not make. Attaching
    # a handler does not consume it, so the `await` below still says so.
    assert "void resuming.catch(() => {});" in ready
    assert playing.index("await resuming") < playing.index("await context.decodeAudioData(")
    assert playing.index("await context.resume()") < playing.index("await context.decodeAudioData(")
    refusing = playing[
        playing.index("await context.resume()") : playing.index("await context.decodeAudioData(")
    ]
    assert 'if (context.state !== "running") {' in refusing
    assert "couldNotPlay(slot)" in refusing


def test_the_recording_this_page_holds_is_bounded_and_bounded_without_a_clock() -> None:
    """Adversarial review, round 3, major. A press with no bound accumulates for as long
    as a finger is down, and nothing discovers it until the upload — where the answer is a
    size refusal after the owner has spoken for minutes.

    **The bound is on what this page holds, and is not a copy of a bound that refuses.**
    ``hub_max_spoken_audio_bytes`` and ``gateway_max_request_bytes`` are the hub's and the
    gateway's, this page is told neither, and a guess at either here would be a second
    place a figure lives with nothing keeping the two in step. What is chosen is a
    browser-memory question, which is this page's own.

    **And it is not a clock**, which is what keeps ADR-0182 §7's own invariant intact:
    this file has exactly one ``setTimeout`` because an owner's wait is the owner's to
    end, and a page-side deadline over a request would abandon a healthy turn and announce
    that its outcome was not known. This bounds a *recording*, before any request exists,
    and what measures it is the recorder handing over what it has.
    """
    script = _code("app.js")
    starting = _functions(script)["startTalking"]

    assert "LONGEST_RECORDING_BYTES = 384 * 1024" in script
    assert "recorder.start(RECORDING_SLICE_MILLISECONDS)" in starting
    # **The prospective total, before the chunk is kept**, which is what makes the bound
    # exact rather than exceeded by whatever the crossing chunk happened to be — a final
    # chunk arriving after the release, or one very large block from a browser that
    # ignored the slice it was asked for. Round 4's major.
    assert "if (mine.held + event.data.size > LONGEST_RECORDING_BYTES) {" in starting
    assert starting.index("LONGEST_RECORDING_BYTES") < starting.index("mine.chunks.push")
    assert "fault(RECORDING_TOO_LONG," in starting
    # **The size check is unconditional and only the stopping is not**: a final chunk
    # arrives after the release, when there is no recorder left to stop, and a check
    # skipped there is exactly the unbounded upload the bound exists to prevent.
    assert "if (!mine.released) {\n        stopTalking();" in starting
    # **And a press that crossed it sends nothing at all** (round 5's major). A recording
    # is a container and its last chunk is where a `MediaRecorder` writes what finishes
    # one, so keeping the chunks before it and uploading them uploads a clip that may not
    # decode — the hub handed something it cannot read, having been told the recording was
    # sent. There is no container-aware middle: this page parses no WebM and no MP4.
    assert "mine.overran = true" in starting
    assert "mine.chunks = []" in starting
    assert "if (mine.overran) {" in _functions(script)["sendRecording"]
    assert "nothing was sent" in _constant(script, "RECORDING_TOO_LONG")
    # And the line that says a press is happening comes off with it. Found by driving:
    # an overrun never reaches `SENDING`, so a release clearing only that one left
    # "Listening" on screen beside a fault saying the press had been stopped.
    assert "if (said === LISTENING || said === SENDING) {" in _functions(script)["releaseTalk"]
    # No clock of its own reaches this control, and the file's one `setTimeout` is still
    # the delivery stream's.
    assert len(_timeouts(script)) == 1
    for name in ("startTalking", "stopTalking", "sendRecording", "abandonSpoken", "releaseTalk"):
        body = _functions(script)[name]
        for clock in ("setTimeout", "setInterval", "HEAD_DEADLINE_MILLISECONDS"):
            assert clock not in body, (name, clock)


def test_the_page_asks_its_encoder_for_the_bitrate_the_adrs_arithmetic_assumes() -> None:
    """ADR-0200 §6 states its ceiling's meaning in seconds — "512 KiB is about three
    minutes of speech at a 24 kbit/s Opus bitrate" — and a ``MediaRecorder`` given no
    figure picks its own, which on some browsers is several times that.

    A page taking the default would reach the hub's ceiling in a fraction of the time the
    ADR's arithmetic says, and would do it opaquely: the refusal names a byte ceiling and
    says nothing about the bitrate that reached it. It is a hint rather than a setting —
    an encoder may honour it approximately or not at all — which is why the bound above is
    on the bytes held and not on this.
    """
    script = _code("app.js")

    assert "TALK_BITS_A_SECOND = 24000" in script
    assert "audioBitsPerSecond: TALK_BITS_A_SECOND" in script


def test_the_page_never_relays_the_browsers_own_words_about_a_microphone() -> None:
    """``getUserMedia``'s refusals are read off the error's ``name``, the one member the
    specification fixes — never off its ``message``, which is the browser's own prose.

    A page that relayed one would be saying something it cannot stand behind about a
    device the owner has to act on, and it is the same rule ADR-0200 §8 states one layer
    in: nothing on this path writes an exception message it did not author.
    """
    refusing = _functions(_code("app.js"))["microphoneRefused"]

    assert "error.name" in refusing
    assert ".message" not in refusing
    for named in ("MICROPHONE_DENIED", "NO_MICROPHONE_DEVICE", "MICROPHONE_UNAVAILABLE"):
        assert named in refusing, named


def test_the_spoken_turn_is_rendered_by_the_same_renderer_as_a_typed_one() -> None:
    """ADR-0200 §4: the outcome "is an ordinary ``TurnOutcome``… This call composes a
    turn; it does not create a second kind of one."

    So a member added to ``renderOutcome`` reaches all three entries. A page with a
    second renderer would be the front end's half of the failure #1337 records at the
    gateway — an answer composed, returned, and dropped one layer short of the person who
    asked for it, on one entry and not the others.
    """
    rendering = _functions(_code("app.js"))["renderSpokenTurn"]

    assert "renderOutcome(turn.outcome, chosenAt)" in rendering


def test_an_ask_whose_answer_never_arrives_does_not_hold_the_owners_control_for_ever() -> None:
    """Issue #1500. ``ask`` disables ``#ask-button`` before the request goes out and
    re-enables it in a ``finally``; ``fetch`` carries no deadline of its own, so a socket
    that dies without settling leaves that ``await`` pending for ever, the ``finally``
    never runs, and the owner's one way into the assistant stays greyed out until the
    page is reloaded. It is #1474's failure on a different request.

    **A different clause of ADR-0182 §7 governs, and it supplies a control rather than a
    bound.** #1474 turns on §7's *third* clause, which is about delivery streams and
    about concurrency, so PR #1496 could bound a duration the clause is silent on. An
    ``ask`` is reached by §7's **fifth** clause — "The page re-issues **no other
    request** of its own motion. Every request that asks the assistant for something …
    is re-issued only on an act by the owner" — and by the paragraph grounding it, which
    names the remedy in terms: re-issuing an ask "is a turn the owner may already have
    had executed", so "offering the owner a visible retry costs **one control** and
    removes the class".

    What is pinned here is the invariant #1500 is about: every exit an ask has, the ones
    that never settle included, goes through the one function that hands the control
    back — and the owner has an act that reaches it while the request is still out.
    """
    script = _code("app.js")
    document = _markup("index.html")
    asking = _functions(script)["ask"]
    abandon = _functions(script)["abandonAsk"]

    # One place re-enables the button, so a path that released the control without
    # saying anything would have to go through the sentence too.
    assert script.count('el("ask-button").disabled = false;') == 1
    assert 'el("ask-button").disabled = false;' in _functions(script)["releaseAsk"]
    # The wait is a controller and not a flag, so aborting it is what makes the pending
    # `fetch` settle rather than merely marking it settled.
    assert "stopping: new AbortController()," in asking
    assert "waiting.stopping.abort();" in abandon
    # Carried into both turn entries, which is what puts the abort on the socket rather
    # than only on this page's own bookkeeping.
    assert "await askStreaming(half, asked, chosenAt, waiting);" in asking
    assert "await askWhole(half, asked, chosenAt, waiting);" in asking
    assert script.count("signal: waiting.stopping.signal,") == 2
    # The owner's act reaches it, from a control that ships nowhere in the document and
    # is built beside the button it stands in for.
    assert 'id="stop-waiting"' not in document
    assert 'stop.addEventListener("click", abandonAsk);' in script
    assert script.count("abandonAsk") == 2
    assert "offerStopWaiting();" in script


def test_stopping_a_wait_says_the_turns_outcome_is_not_known_and_claims_nothing_else() -> None:
    """ADR-0177 §7's fourth clause, which is this surface's own addition to ADR-0139
    §4's three outcomes, reaching the request that asks the assistant for something.

    "A failure of the **browser's own** request to the gateway — the request was sent and
    no response was read — is an outcome that is **not known**, whatever the gateway
    did", and "no front end resolves it by assuming either of the other two". A control
    that simply came back would assume one by omission: a restored control reads as an
    act that finished.

    So the three things the owner cannot otherwise know are each said — the turn may have
    run, nothing was cancelled at the assistant, and asking again is a new question
    rather than a retry of that one, which is ADR-0182 §7's "the page re-asks only when
    the owner asks it to" said where the owner is. The route back is a read rather than
    an assertion (ADR-0177 §7's last clause: no surface states a state it has not read).
    """
    script = _code("app.js")
    abandon = _functions(script)["abandonAsk"]

    assert "const said = waiting.heard ? ASK_ABANDONED_MIDWAY : ASK_ABANDONED;" in abandon
    assert '`${said} ${PARTIAL_CLEARED}` : said, "console"' in abandon
    assert "What became of the turn is not known" in script
    assert "may have carried it out and may never have received it" in script
    assert "Nothing was re-sent and nothing was cancelled" in script
    assert "asks a new question rather than retrying that one" in script
    assert "The conversations listing is where to look for it" in script
    # And it sends nothing at all, which is what keeps a control that ends a wait from
    # being the silent retry ADR-0168 §9 forbids wearing a button's clothes.
    for sends in ("fetch(", "relay(", "act(", "watchDeliveries("):
        assert sends not in abandon, sends
    # Inside the ask form, where a button with no type is a submit button — which would
    # ask the question again from the one control whose whole purpose is that it does not.
    assert 'stop.type = "button";' in script
    # Said while the question is out, too. The sentence promises no deadline, because
    # there is none: what it tells the owner is that this page cannot tell a slow turn
    # from one that will never answer, which is what makes the control theirs to use.
    assert "askWaiting(true);" in _functions(script)["ask"]
    assert "This browser puts no deadline on a turn" in script
    assert "wait is yours to do." in script


def test_the_wait_is_ended_by_the_owner_and_by_no_clock_of_the_pages_own() -> None:
    """The decision #1500 asks a taker to make, pinned where changing it would have to
    pass this test: an automatic deadline on an ask is **declined**, and the page's own
    motion is left exactly as ADR-0182 §7 left it — two events and one clock.

    **Any figure would pace something the gateway paces, and no head discloses it.**
    ``server.py``'s ``_TURN_BUDGET`` gives every turn sixty seconds — ``_ask`` and
    ``_pump_answer`` both pass it — and it reaches the browser in no header, no value and
    no setting. A page-side deadline would be a second number that can silently disagree
    with it, which is ``SILENT_CADENCES``' own argument one surface out, and deriving one
    from ``usableCadence``'s figure would be the substitution that rule refuses.

    **``HEAD_DEADLINE_MILLISECONDS``' argument does not transfer**, which is the trap
    this test exists for. That bound is defensible because what it covers is "a round
    trip and an in-process table read, and nothing else": ``_write_stream`` writes and
    drains the delivery head *before* it awaits the body. An ``/ask`` head is written
    after the whole turn, so the same thirty seconds there would abandon a healthy turn
    that was thinking and announce that its outcome was not known — true, and useless.
    """
    script = _code("app.js")

    # Still one clock, and still the delivery stream's. A second `setTimeout` would be
    # the page taking motion over a request ADR-0182 §7 makes the owner's.
    assert len(_timeouts(script)) == 1
    assert "setInterval" not in script
    # And no deadline reaches the ask at all: neither the delivery bound nor a new one.
    for function in ("ask", "abandonAsk", "askWhole", "askStreaming", "releaseAsk"):
        body = _functions(script)[function]
        for clock in ("setTimeout", "HEAD_DEADLINE_MILLISECONDS", "SILENT_CADENCES", "cadence"):
            assert clock not in body, (function, clock)
    # The one clock there is cannot reach the abandonment either, so the wait is ended
    # by the owner and by nothing this page schedules.
    assert "abandonAsk" not in _timeouts(script)[0]
    assert "releaseAsk" not in _timeouts(script)[0]


def test_a_settled_ask_does_not_hand_back_a_control_a_later_question_took() -> None:
    """The race the remedy creates, closed where it is created.

    Stopping a wait re-enables ``#ask-button``, which is the point of it — so the owner
    can ask again at once, while the abandoned request's promise is still unsettled. That
    promise then rejects, and an unguarded ``finally`` would run `releaseAsk` on the
    *live* turn: the button back in the middle of it, and that turn's own way out hidden.

    The guard is an identity comparison against the controller rather than a flag,
    because what has to be decided is *which ask* is being waited on, and the controller
    is the only thing that is one per ask.
    """
    script = _code("app.js")
    asking = _functions(script)["ask"]

    assert "if (awaited === waiting) {" in asking
    assert asking.index("if (awaited === waiting) {") < asking.index("releaseAsk();")
    # Released before the abort, so the rejection it provokes finds this ask settled.
    abandon = _functions(script)["abandonAsk"]
    assert abandon.index("releaseAsk();") < abandon.index("waiting.stopping.abort();")
    # `awaited` is written in exactly three places — taken, and given back in the one
    # function that hands the control back with it.
    assert len(re.findall(r"(?<!let )awaited = ", script)) == 2
    assert "awaited = null;" in _functions(script)["releaseAsk"]


def test_an_abandoned_ask_leaves_no_answer_shaped_nothing_on_screen() -> None:
    """What an abort must not be allowed to render, on the three paths it can land on.

    ADR-0173 §3 makes the terminal outcome's ``reply`` the answer and forbids treating
    "an accumulated chunk sequence as the record of what the assistant said", so partial
    text has to go the way ``ANSWER_STREAM_CUT`` sends it — cleared, not left standing
    under a fault.

    ``readBody`` is the subtler half. It answers anything unreadable with an empty object
    rather than throwing, which is the right rule for a body the gateway wrote badly and
    the wrong one for a read the owner stopped: ``{}`` rendered as an outcome is an
    answer-shaped nothing, and reported as a refusal it is a condition the gateway never
    named. Both entries check the signal instead of trusting the throw.

    And the guard in ``ask``'s own ``catch`` is the last one: an abort the owner asked
    for is not the gateway having gone, and saying it was would be a wrong explanation
    rather than a missing one — ``readDeliveries``' catch keeps the same distinction.
    """
    script = _code("app.js")
    abandon = _functions(script)["abandonAsk"]

    assert 'clearNode(el("answer-body"));' in abandon
    assert 'show("answer", false);' in abandon
    assert abandon.index("if (mine) {") < abandon.index('clearNode(el("answer-body"));')
    # The two body reads that an abort can land in the middle of.
    assert script.count("if (waiting.stopping.signal.aborted) {") == 2
    whole = _functions(script)["askWhole"]
    assert whole.index("const body = await readBody(response);") < whole.index(
        "if (waiting.stopping.signal.aborted) {"
    )
    # `rindex`, because the render branch is the *second* `if (response.ok)` in this
    # function: the first is the guard that decides whether the turn was heard from.
    assert whole.index("if (waiting.stopping.signal.aborted) {") < whole.rindex(
        "if (response.ok) {"
    )
    stream = _functions(script)["askStreaming"]
    assert stream.index("if (waiting.stopping.signal.aborted) {") < stream.index(
        'show("answer", false);'
    )
    # And the catch, which stays silent for an ending the owner already has words for.
    asking = _functions(script)["ask"]
    assert "if (!waiting.stopping.signal.aborted) {" in asking
    assert asking.index("if (!waiting.stopping.signal.aborted) {") < asking.index(
        'fault(GATEWAY_GONE, "console");'
    )


def test_the_announcement_is_read_off_what_this_browser_actually_observed() -> None:
    """Adversarial review, round 1, blocker and major — both are one mistake: a single
    sentence and a single clearing act, applied to states they are false in.

    ADR-0177 §7's fourth clause makes an outcome not known where "the request was sent
    and **no response was read**". Said after a chunk has been rendered it is factually
    wrong twice over — something here *did* read a reply, and the assistant demonstrably
    *did* receive the question — and ADR-0182 §7 requires the page's announcement to be
    accurate rather than merely present.

    **The two facts are separate and are set by different evidence.** ``heard`` says the
    question reached the assistant, and what proves it differs by entry: ``/ask`` answers
    only once ``converse`` has returned (``_ask`` awaits it), so its response head is the
    proof, while ``/ask/stream``'s head is written and drained *before* ``_pump_answer``
    is awaited (``_write_stream``) and proves nothing about the assistant — there the
    first chunk is. ``composing`` says this turn has taken the answer panel over, which is
    what makes the text in it this turn's to throw away: an owner who asks a second
    question and stops waiting before its head lands still has the *first* question's
    complete answer on screen, and clearing that is destroying a good answer because a
    later request failed.
    """
    script = _code("app.js")
    abandon = _functions(script)["abandonAsk"]
    whole = _functions(script)["askWhole"]
    stream = _functions(script)["askStreaming"]

    # `/ask`: a **successful** head is the proof, and only that. A refusal is decided by
    # `_check_door` or `_session_bound` before `_assistant` is reached, so a refusal head
    # whose body then stalls says the gateway replied and nothing about the assistant.
    assert "if (response.ok) {\n    waiting.heard = true;\n  }" in whole
    assert whole.index("waiting.heard = true;") < whole.index(
        "const body = await readBody(response);"
    )
    assert script.count("waiting.heard = true;") == 2
    # `/ask/stream`: the head takes the panel and claims nothing about the assistant, and
    # the first chunk is what says the question got there.
    assert "waiting.composing = composing;" in stream
    assert stream.index('show("answer", true);') < stream.index("waiting.composing = composing;")
    assert stream.index("waiting.composing = composing;") < stream.index("waiting.heard = true;")
    assert stream.index('if (value.kind === "chunk") {') < stream.index("waiting.heard = true;")
    assert stream.index("waiting.heard = true;") < stream.index("composing.textContent +=")
    # The node is held nowhere else, so the whole entry never clears a panel it never took.
    assert script.count("waiting.composing = ") == 1
    assert "waiting.composing" not in whole
    # And ownership is asked about *now*: the node is in the document exactly while the
    # panel is still this turn's, so a park answered into it — `renderOutcome` replaces
    # the panel — takes it back without any bookkeeping having to be kept in step.
    assert "const mine = waiting.composing !== null && waiting.composing.isConnected;" in abandon
    assert "if (mine) {" in abandon
    assert "mine && waiting.heard ?" in abandon
    # And the two sentences differ in exactly the clauses the evidence decides. The one
    # that claims nothing was received says so only where nothing was; the other says the
    # question got there and narrows what is unknown to the ending.
    assert "may have carried it out and may never have received it" in script
    assert "the question was sent and nothing here read a " in script
    assert "so the assistant did receive the " in script
    assert "how it ended is what is not known" in script
    # What none of them may drop: the act is the same act, so the three things about
    # it that do not depend on how far the answer got are said in all of them.
    #
    # **Five rather than four since ADR-0200 §10**, and the arithmetic is the same one:
    # each constant carries the clause once and is named once at its site, and the third
    # abandonment sentence is `SPOKEN_ABANDONED` — the spoken entry's own, which is
    # `ASK_ABANDONED`'s state rather than `ASK_ABANDONED_MIDWAY`'s because a spoken turn
    # streams nothing and so has no partial reply this browser could have read.
    assert script.count("nothing was cancelled — the assistant was not told to stop.") == 5
    assert script.count("new question rather than retrying that one") == 5
    # The route back is one constant read by all of them, so the endings cannot drift
    # apart on it — and it points rather than promises, because a turn that ran is not
    # thereby a turn that was recorded (`TurnOutcome.capture_degraded`, ADR-0074 §9
    # item 6).
    assert script.count("WHERE_TO_LOOK") == 5
    assert "though a turn whose record " in script
    assert "could not be written does not appear there" in script


def test_a_wait_stopped_after_a_session_refusal_is_re_entry_and_not_an_unknown_outcome() -> None:
    """Adversarial review, round 3, blocker. A wait whose *head* already refused it is not
    a wait whose outcome nobody read, and announcing one as the other is wrong twice.

    **It is factually wrong.** ADR-0177 §7's fourth clause makes an outcome not known
    where "the request was sent and **no response was read**"; a `401` head read before a
    body that then stalls is a response read. ``Gateway._session_bound`` decides both
    ``NO_LIVE_SESSION`` and ``COOKIE_HALF_MISMATCH`` *before* ``_assistant`` is reached,
    so the assistant never received the question and there is no turn that may have run.

    **And it strands the browser.** ADR-0182 §6: "A browser presenting a header half the
    gateway does not admit is shown the bootstrap entry, presented as re-entry rather than
    as a fault." A refusal read to the end reaches that through ``sessionLost``; before
    this, stopping the wait during the stalled body took the generic path instead, leaving
    the dead header half in storage and the console on screen — so the one act an owner
    has for ending a stalled wait was also the one way to be left holding a session the
    gateway will refuse every future request from.

    **The status is enough, and reading it is a read rather than a guess.**
    ``server.py``'s ``_REFUSAL_STATUS`` gives every condition "its own status", because
    ADR-0168 §6 requires the cookie-half fault "never flattened into an expiry, a ceiling
    refusal or an ordinary absent session" and "a status shared with another condition is
    that flattening performed by the response rather than by the record". So this page may
    map back exactly the statuses that name one condition — which is why ``403`` is
    absent: ``_REFUSAL_STATUS`` gives it to two.
    """
    script = _code("app.js")
    abandon = _functions(script)["abandonAsk"]
    whole = _functions(script)["askWhole"]
    stream = _functions(script)["askStreaming"]

    # The table, and the two statuses in it, read off the gateway's own mapping rather
    # than transcribed: a condition given a second condition's status would fail here as
    # well as breaching §6, and a status this page mapped that the gateway shares would
    # be this page performing the flattening §6 forbids.
    statuses = dict(re.findall(r"\[(\d{3}), \"([a-z-]+)\"\],", script))
    assert statuses == {"401": "no-live-session", "409": "cookie-half-mismatch"}
    assert {int(one) for one in statuses} == SESSION_REFUSAL_STATUSES
    for status, fault in statuses.items():
        condition = RefusalCondition(fault)
        assert _REFUSAL_STATUS[condition][0] == int(status), fault
        shared = [one for one in _REFUSAL_STATUS if _REFUSAL_STATUS[one][0] == int(status)]
        assert shared == [condition], (status, shared)
    # And the conditions are the two `sessionLost` acts on, so the two doors into re-entry
    # cannot come to disagree about what ends a session.
    for fault in statuses.values():
        assert f'body.fault === "{fault}"' in _functions(script)["sessionLost"]

    # The head is recorded on both entries, before either touches a body — which is the
    # whole of why it survives a body that never arrives.
    assert "waiting.refusedWith = response.status;" in whole
    assert whole.index("waiting.refusedWith = response.status;") < whole.index(
        "const body = await readBody(response);"
    )
    assert "waiting.refusedWith = response.status;" in stream
    assert stream.index("waiting.refusedWith = response.status;") < stream.index(
        "const body = await readBody(response);"
    )
    assert script.count("waiting.refusedWith = response.status;") == 2
    # `heard` is the other branch of the same test on the entry that has both, so no ask
    # can ever carry a refusal status and a claim that the assistant was reached.
    assert "if (response.ok) {\n    waiting.heard = true;\n  } else {\n" in whole
    assert "waiting.heard" not in stream[: stream.index("waiting.refusedWith")]

    # Stopping the wait then takes re-entry, and takes it *before* the wording and the
    # tidying of an outcome nobody read.
    assert "const ended = SESSION_LOST_STATUS.get(waiting.refusedWith);" in abandon
    assert "if (ended !== undefined) {" in abandon
    assert abandon.index("if (ended !== undefined) {") < abandon.index("const mine =")
    assert abandon.index("if (ended !== undefined) {") < abandon.index("const said =")
    # Through `sessionLost`, which is what forgets the half, stops the stream and shows
    # the bootstrap entry — the three things §6 asks for, none of them re-implemented here.
    assert "sessionLost(named, `${describe(named, waiting.refusedWith)}" in abandon
    for reimplemented in ("forgetHeaderHalf(", "showBootstrap(", "stopWatching("):
        assert reimplemented not in abandon, reimplemented
    # And it is re-entry rather than a fault (§6), so this ending writes no fault at all —
    # the one `fault(` call in the function is on the path this one returns before.
    assert abandon.index("return;", abandon.index("if (ended !== undefined) {")) < abandon.index(
        "fault("
    )
    # What the act says on top of the condition's own words: the same three claims
    # `ASK_ABANDONED` makes are all false here, so none of them is made.
    assert "REFUSED_AT_THE_DOOR" in abandon
    assert "never reached the assistant" in script
    assert "so no turn ran and nothing was left half-done" in script


def test_a_wait_stopped_after_any_other_refusal_head_says_a_reply_was_read() -> None:
    """Adversarial review, round 5, blocker. ``ASK_ABANDONED`` opens with "the question
    was sent and nothing here read a reply", which is false of **every** refusal head — a
    status line is a reply — and goes on to say the assistant "may have carried it out",
    which some statuses make known to be false.

    ADR-0139 §4 governs in both directions: an act is reported as one of exactly three
    outcomes "and never as either of the other two". So a known **not landed** act
    announced as *not known* breaches it exactly as reporting a landed one that way does,
    which is the reading ``relay`` already states of itself one surface over.

    **The status settles it on the two ask paths for exactly three of them.** ``421`` is
    ``HOST_NOT_BOUND`` and ``403`` is ``ORIGIN_NOT_OWN`` or ADR-0174 §4's
    ``DEVICE_NOT_LISTED``, all taken by ``_check_door`` before a session is looked up;
    the other ``403``s ``server.py`` writes are ADR-0177 §3's connection refusals, gated
    on ``_CONNECTION_PATHS``, which neither ask path is. ``503`` is
    ``hub-connection-ceiling``, raised out of ``_take_hub_slot()`` *before* ``_relayed``
    awaits ``call()``.

    **And three are excluded because they are not proof.** ``400`` is shared between
    ``malformed-request`` (before the call) and ``rejected`` (a ``ValueError`` out of it);
    ``502`` is ``hub-unreachable``, and a ``TransportError`` can be raised after the
    request was written; ``422`` is ``assistant-declined``, which ADR-0168 §9 defines as
    "a request the hub **received** and declined". The excluded direction is the
    expensive one: an owner told no turn ran when one did asks it again.
    """
    script = _code("app.js")
    abandon = _functions(script)["abandonAsk"]

    assert "const RELAY_FAULT_STATUS = new Set([400, 422, 502]);" in script
    # **The set is read back out of `_relay_fault` by calling it**, which is the whole
    # point of enumerating this side rather than the other: a lane adding a post-relay
    # status adds it there, because ADR-0168 §9 makes that function what classifies a
    # failed relay, and this fails until the page agrees.
    declared = {int(one) for one in re.findall(r"\d+", _js_set(script, "RELAY_FAULT_STATUS"))}
    assert declared == relayed_statuses()
    # And the statuses decided *before* the relay are outside it — including the parser's
    # `413`, which cost round 7 and which `_REFUSAL_STATUS` never holds at all. That is
    # why deriving the other side from that table could not work, and why this test reads
    # the parser's own status rather than a list.
    assert 413 not in declared
    for taken in SESSION_REFUSAL_STATUSES:
        assert taken not in declared, taken

    # Taken for every refusal head, after the session branch and before the black hole's.
    assert "if (waiting.refusedWith !== null) {" in abandon
    assert abandon.index("if (ended !== undefined) {") < abandon.index(
        "if (waiting.refusedWith !== null) {"
    )
    assert abandon.index("if (waiting.refusedWith !== null) {") < abandon.index("const said =")
    assert 'fault(refusalAbandoned(waiting.refusedWith), "console");' in abandon
    # It is a fault rather than re-entry: nothing about the session ended, so the control
    # comes back into a console that is still the owner's.
    for reentry in ("sessionLost(", "forgetHeaderHalf(", "showBootstrap("):
        assert abandon.count(reentry) == (1 if reentry == "sessionLost(" else 0), reentry

    # What each of the two says, and the clause neither may keep: a refusal head is a
    # reply, so "nothing here read a reply" is false of both.
    assert "The gateway had already answered that question with a refusal" in script
    assert "ever acted on the question is not something a refusal on its own says" in script
    assert "refused that question before the assistant was reached, so no turn ran" in script
    assert script.count("the question was sent and nothing here read a ") == 1
    # And the one that knows no turn ran does not send the owner looking for it: the route
    # back points at the conversations listing, and nothing can be there.
    assert "there is nothing to look for" in script
    unrun = script[script.index("const ASK_REFUSED_UNRUN") :]
    assert "WHERE_TO_LOOK" not in unrun[: unrun.index(";") + 1]


def test_a_declined_turn_is_announced_as_one_the_assistant_did_receive() -> None:
    """Adversarial review, round 6, blocker, and the other half of round 5's.

    ``422`` is ``assistant-declined``, which ADR-0168 §9 defines as "a request the hub
    **received** and declined" — the distinction §9 exists to keep. So it settles the
    same question ``REFUSED_BEFORE_THE_ENGINE`` settles, in the opposite direction, and
    grouping it with the ambiguous statuses said a status said nothing when it says a
    great deal. ``server.py`` writes ``422`` once more, for ``_connection_fault``'s
    ``identity-unusable``, and that serves ADR-0151's connection surface — not either ask
    path.

    **What it must not say in either direction.** A declined turn produced no answer to
    record, so ``WHERE_TO_LOOK``'s pointer at the conversations listing would be a
    promise that cannot hold; and this browser did not read what the hub said, so
    declaring there is nothing to find would state a state it has not read (ADR-0177 §7).
    It says neither, and the enumeration is complete: every status these two paths answer
    with is decided here, taken by the re-entry branch, or deliberately left ambiguous.
    """
    script = _code("app.js")
    choose = _functions(script)["refusalAbandoned"]

    assert "const DECLINED_BY_THE_ASSISTANT = 422;" in script
    assert _relay_fault(AssistantError("no")).status == 422
    assert "if (status === DECLINED_BY_THE_ASSISTANT) {" in choose
    assert "return ASK_REFUSED_DECLINED;" in choose
    # The order is the argument. `422` is itself a member of `RELAY_FAULT_STATUS`, so it
    # has to be taken first or the ambiguous sentence would swallow the one status in
    # that set which is not ambiguous at all.
    assert choose.index("status === DECLINED_BY_THE_ASSISTANT") < choose.index(
        "RELAY_FAULT_STATUS.has(status)"
    )
    # And what falls past both is the default rather than a fourth case nobody wrote: a
    # refusal written before the relay began, which is every status but these three.
    assert choose.rstrip().endswith("return ASK_REFUSED_UNRUN;\n}")
    assert choose.count("return ") == 3
    assert script.count("refusalAbandoned(") == 2
    # The two statuses that cost rounds 5 and 7 land on that default, and so does the
    # parser's `413` — the one no table derived from `_REFUSAL_STATUS` could have held.
    for unrun in (403, 421, 503, 413, 429, 404):
        assert unrun not in relayed_statuses(), unrun
    # `422` is in that set and is still not ambiguous, which is the case the ordering
    # above exists for.
    assert 422 in relayed_statuses()

    # What it says, and the two things it may not say.
    assert "The assistant did receive that question and declined it" in script
    assert "so no answer was produced" in script
    declined = script[script.index("const ASK_REFUSED_DECLINED") :]
    said = declined[: declined.index(";") + 1]
    assert "WHERE_TO_LOOK" not in said
    assert "nothing to look for" not in said


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
    calls = _timeouts(script)
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
    assert "rearm(" not in _timeouts(script)[0]


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
    calls = _timeouts(script)

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
    # connection going away, and a body still open and silent is not.
    assert "stopped saying anything" in script
    assert script.count("ended before the gateway finished it") == 2
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
    browser holds is untouched — and the two keys the page does store are the session's
    header half and the conversation id, neither of which this touches.

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
        "CONVERSATION_KEY",
        "CONVERSATION_KEY",
        "CONVERSATION_KEY",
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
    assert script.count("Start watching again.") == 3


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
    assert watch.index("watching = true;") < watch.index("await readDeliveries(half);")
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
    caught = read[read.index("} catch (_) {") :]

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


def test_the_page_offers_a_way_out_of_the_thread_it_is_reading() -> None:
    """The escape a persisted selection owes, and the one the page did not have.

    Until this file kept a conversation across a reload, a reload *was* how you
    started a fresh one. Now the selection comes back — so a thread the hub will no
    longer accept, destroyed from a terminal or expired, would be re-sent on every
    question with no control on screen to clear it. The conversations listing cannot
    offer one: it can only "Continue" a conversation it is showing, and this is about
    one it is not. Adversarial review found it on round 3.

    **It sends nothing**, which is what keeps it a local act rather than a thirty-first
    operation: the hub is not told, nothing is destroyed, and the conversation it was
    reading is untouched and still in the listing.
    """
    script = _code("app.js")
    document = _asset("index.html")
    fresh = _functions(script)["startFresh"]

    assert 'id="new-conversation"' in document
    assert 'el("new-conversation").addEventListener("click", startFresh);' in script
    assert "changeConversation(null);" in fresh
    for sends in ("fetch(", "relay(", "act("):
        assert sends not in fresh, sends
    # Hidden while there is nothing to leave, so it is never a control that does nothing.
    assert 'el("new-conversation").hidden = id === null;' in _functions(script)["setConversation"]


def test_an_answer_in_flight_cannot_undo_the_owners_own_choice() -> None:
    """Ask under ``C``, then press "Start a new conversation" while that request is
    still out: the selection clears, the answer arrives, and an unguarded
    ``renderOutcome`` puts ``C`` back — so the next question continues the thread the
    owner had just, explicitly, left.

    The Ask button is disabled for the duration and this control deliberately is not:
    leaving a thread is not something to make the owner wait for. So the turn carries
    the count it was sent under instead, and the answer is still rendered whole — it is
    only the *selection* that is not moved. Adversarial review found it on round 4.

    It is this file's third use of the device: ``pendingRun`` for the confirmations
    listing, ``runs`` for the questions listing, and now ``chose`` for the selection.
    """
    script = _code("app.js")
    functions = _functions(script)

    # Read before the request goes out, at both places a turn outcome comes back.
    for entry in ("ask", "answerConfirmation"):
        assert "const chosenAt = chose;" in functions[entry], entry
    # Bumped in exactly one place, so a route that changes the selection cannot forget.
    assert script.count("chose += 1;") == 1
    assert "chose += 1;" in functions["changeConversation"]
    assert "outcome.conversation_id && chose === chosenAt" in functions["renderOutcome"]
    # Every outcome rendered carries a count; one that did not would silently stop
    # continuing the conversation rather than fail.
    #
    # Read as the **second** argument rather than as the last one, which is what #1621
    # made the difference: ``answerConfirmation`` now passes a third — the caveat a
    # re-answered park carries — and a check anchored on the end of the call would have
    # gone on passing while asking nothing.
    rendered = re.findall(r"renderOutcome\(([^)]*)\)", script)
    assert rendered
    for call in rendered:
        assert [one.strip() for one in call.split(",")][1] == "chosenAt", call


def test_a_stale_selection_is_dropped_where_the_gateway_names_the_condition() -> None:
    """The narrow half of the same fix. Only ``/conversation`` answers
    ``no-such-conversation`` — a declined turn arrives as ``assistant-declined``
    whatever the hub declined it for — so this is what the page can do mechanically,
    and the control above is what covers the rest.

    ``sent`` is what the request actually carried, and the comparison is what keeps it
    narrow: forgetting some *other* conversation from the listing and being told it was
    already gone says nothing about the one this view is reading.
    """
    script = _code("app.js")
    lost = _functions(script)["conversationLost"]

    assert 'body.fault === "no-such-conversation"' in lost
    assert "sent === conversationId" in lost
    assert "changeConversation(null)" in lost
    assert "conversationLost(body, payload.conversation_id);" in _functions(script)["relay"]
    assert "conversationLost(body, asked.conversation_id);" in _functions(script)["askWhole"]


def test_the_page_says_why_a_session_ended_while_it_was_only_watching() -> None:
    """ADR-0175 §7: an open stream is **not** use of the session that admitted it.
    ``gateway_session_idle_timeout`` "is refreshed by a request the gateway admits and
    by nothing else — not by a stream's continued existence, not by a value the gateway
    writes on one, and not by a delivery poll", and a stream ends no later than the
    session that admitted it.

    So a page left open and watching, asked nothing, expires exactly on time and the
    stream ends under it — and the bare vocabulary entry for ``no-live-session`` reads,
    to the owner of that page, as though something went wrong.

    The sentence is on the **delivery** ending alone and deliberately: an answer
    stream's own request refreshed the timeout on its way in, so ``no-live-session``
    there is not the hour passing, and saying it was would be a wrong explanation
    rather than a missing one.
    """
    script = _code("app.js")

    assert "gateway_session_idle_timeout" in script
    assert "Watching does not keep a session alive." in script
    assert 'value.fault === "no-live-session"' in _functions(script)["describeDeliveryEnd"]
    assert "describeDeliveryEnd" in _functions(script)["readDeliveries"]
    assert "describeDeliveryEnd" not in _functions(script)["askStreaming"]


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
        '"/observe"',
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


def test_the_page_offers_every_use_a_grant_may_authorise_and_no_proper_subset() -> None:
    """ADR-0139 §3's second clause, restated at the browser by ADR-0177 §6.

    "Wherever a surface offers, enumerates or explains the uses a user may choose
    among, it carries **every** member of ``GrantScope``, named in words" — a user
    cannot choose what they are not shown, and a page is where a two-of-three
    checkbox group is the natural mistake.

    Read off the shipped file against ``core``'s own vocabulary, so a fourth member
    added to the enum fails here rather than reaching a user as a silently absent
    option.

    **Counted inside the declaration and not across the file**, which is issue #1332's
    lesson applied before it bit: a whole-file count of ``label:`` was satisfied by
    ``USES`` alone only while ``USES`` was the only vocabulary the page carried, and
    the notification review surface's reach levels are a second one.
    """
    vocabulary = _declaration(_code("app.js"), "USES")

    for use in GrantScope:
        assert f'value: "{use.value}"' in vocabulary, use.value
    # Named in words rather than by member name: the value is what goes on the wire,
    # and the label beside it is what the person reads.
    assert vocabulary.count("label:") == len(GrantScope)


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
    # half of ADR-0139 §3 and where all three belong.
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
#: is where that is caught — `ask` guards the two turn entries it chooses between, and
#: `relay` is reached from both conversation entries — so the guard is asserted there
#: rather than at the call.
_FETCH_SITES: Final = {
    "startSession": "startSession",
    "askWhole": "ask",
    "askStreaming": "ask",
    "readDeliveries": "readDeliveries",
    "relay": "listConversations",
    # The spoken entry (ADR-0200 §10). Its own guard rather than one shared with `ask`,
    # because it is not reached from there: a press is its own act and the page never
    # falls back between the three entries (§10, ADR-0168 §9).
    "sendRecording": "sendRecording",
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
    "observe",
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
        "console",
        "conversations",
        "confirmations",
        "notifications",
        "acts",
        "sources",
        "standing",
        "history",
        "beliefs",
        "questions",
        "review",
        "tuning",
        "connections",
        "connection-log",
        "observation",
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


def _js_set(script: str, name: str) -> str:
    """The literal text a named ``new Set([...])`` declaration carries.

    Read by name rather than by a bare digit search so that a second table appearing
    in the file cannot answer a question asked about this one.
    """
    opened = script.index(f"const {name} = new Set([")
    return script[opened : script.index("]);", opened)]


def relayed_statuses() -> set[int]:
    """Every status :func:`_relay_fault` writes, by calling it.

    ADR-0168 §9 makes that function what classifies a failed relay, so this is the
    closed set of statuses a refusal head can carry that were written *after* the
    gateway began relaying the turn. The page enumerates this side precisely because
    it is closed; the other side is not, and two review rounds were spent proving it.
    """
    return {
        _relay_fault(TransportError("gone")).status,
        _relay_fault(AssistantError("no")).status,
        _relay_fault(ValueError("bad")).status,
    }


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

    assert "outsideWarrant(belief.rests_on_recorded_external_content)" in derived
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

    assert 'return rests\n    ? " Some of what I worked it out from' in outside
    assert ': "";' in outside, "and the false arm contributes nothing at all"
    assert "band" not in outside, "the answer is read, never recomputed from the band"
    assert "derived_from_external" not in _code("app.js"), (
        "and no client reads the raw field in the predicate's place (ADR-0106 §2)"
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
    """
    script = _code("app.js")
    functions = _functions(script)

    touching = {
        "renderConfirmation",
        "renderOperationConfirmation",
        "offerApproval",
        "answerConfirmation",
        "strand",
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

    The last assertion is what fails on the fourth state coming back:
    ``authorisationWords`` must have exactly three returns, so there is no branch
    left for a pair that never reaches it.
    """
    functions = _functions(_code("app.js"))
    listing, decision = functions["renderRoutedListing"], functions["renderDecisionFields"]

    assert "if (unreadableRecord(record)) {" in listing
    assert "dropped += 1" in listing
    assert "UNREADABLE_RULINGS" in listing
    assert "unreadable" not in decision, "the row is never reached, not branched inside"
    assert len(re.findall(r"\breturn\b", functions["authorisationWords"])) == 3


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
    """
    body = _functions(_code("app.js"))["renderOutcome"]

    assert (
        "if (outcome.steps.length === 0 && outcome.step === null && outcome.routed === null) {"
        in body
    )


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
    assert offer.count("disabled = out || answered;") == 2
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
    # Given back on **one** path and one only: a refusal the gateway *answered*, which
    # is a response this browser read. Every ending that read no reply keeps the token
    # (:func:`test_an_abandoned_park_answer_does_not_give_the_token_back_on_the_act`),
    # and round 4's first blocker was that the rejection path did not.
    assert answering.count("spent.delete(token);") == 1
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
    assert len(_timeouts(script)) == 1
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
    assert "const lost = stopping.signal.aborted ? PARK_UNRESOLVED : PARK_LOST;" in caught
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
    # The token is given back in exactly two places, and each is an ending this page
    # reached by reading a response or failing to: ``strand``, for the four not-known
    # endings, and the one arm that is known *not* to have landed.
    assert len(re.findall(r"spent\.delete\(", script)) == 2
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
    """
    script = _code("app.js")
    offer = _functions(script)["offerApproval"]
    words = _functions(script)["parkWords"]

    assert offer.rstrip().endswith("parkRows.add({ node: item, settle });\n  settle();\n}")
    assert "const answered = spent.has(token);" in offer
    assert "const stranded = unresolved.has(token);" in offer
    assert "said.textContent = parkWords(waiting, out, answered, stranded);" in offer
    assert 'said.hidden = said.textContent === "";' in offer
    # Total over the four states a row can be in, and it takes no token: ADR-0177 §8
    # has the front end render the continuation nowhere.
    assert "token" not in words
    assert words.count("return") == 4


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
    on, and it runs far enough to clear this panel's fault before the sentence is
    written, which is why the sentence comes after it.

    ``readPending``'s own unbounded ``relay`` is otherwise left alone, and that is the
    third question #1536 asks: it disables no control and claims no token, so a listing
    read that never settles strands nothing — the previous list stays on screen and the
    button that asked for it is still pressable.
    """
    body = _functions(_code("app.js"))["answerConfirmation"]

    assert "await readPending(false);" not in body
    assert "readPending(false);" in body
    assert body.index("readPending(false);") < body.index('fault(lost, "confirmations")')


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
    assert relay.index("refused(panelId, body, response.status);") < relay.index("noticed(")
    # And exactly one caller asks. Every other entry point reaching `relay` is unchanged
    # by this, which is the whole reason it is a callback.
    # And exactly one call site passes it, asserted over the *shape* rather than over
    # the identifier: "noticed by" is owner-facing text this file renders for a
    # notification's producer, so a name search counts two unrelated functions.
    # Two: ``relay``'s own trailing parameter, and the single call site that fills it.
    assert len(re.findall(r"\bnoticed\b\s*\)", script)) == 2
    assert "async function relay(half, path, payload, panelId, stopping, noticed) {" in script
    assert "const noticed = (named) => {" in answering
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
    """
    script = _code("app.js")
    answering = _functions(script)["answerConfirmation"]

    assert "  } catch (_) {" in answering
    assert "renderOutcome(body.outcome, chosenAt, " in answering
    render = answering[answering.index("renderOutcome(body.outcome, chosenAt, ") :]
    assert render[: render.index("\n")].endswith(");")
    assert answering[: answering.index("renderOutcome(body.outcome")].rstrip().endswith("try {")
    # No shape check stands in front of it: enumerating members is the thing round 10
    # refuted, so a re-introduced list would be the same defect wearing a guard.
    assert "Array.isArray(outcome)" not in answering
    # The ending is the not-known one, in the order every other arm uses, and it clears
    # whatever the throw left half-rendered rather than leaving it beside the sentence.
    caught = answering[answering.index("renderOutcome(body.outcome, chosenAt, ") :]
    caught = caught[: caught.index("readPending(true)")]
    for step in (
        'show("answer", false);',
        "strand(token);",
        "readPending(false);",
        'fault(PARK_REPLY_UNREADABLE, "confirmations");',
    ):
        assert step in caught, step
    assert "spent.delete" not in caught

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
    # The pair's enabled state is still computed from ``spent`` alone, so a row that is
    # answerable again is answerable wherever it was built.
    offer = _functions(script)["offerApproval"]
    assert "const answered = spent.has(token);" in offer
    assert offer.count("disabled = out || answered;") == 2


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
    # reads belongs above them.
    assert (
        "renderOutcome(body.outcome, chosenAt, unaccounted ? PARK_SETTLED_AFTER_UNKNOWN : null);"
        in answering
    )
    render = _functions(script)["renderOutcome"]
    assert "function renderOutcome(outcome, chosenAt, provenance) {" in render
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
