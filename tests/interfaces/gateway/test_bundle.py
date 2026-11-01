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
    BeliefBand,
    BeliefSummary,
    GrantScope,
    MemoryStanding,
    NotificationCondition,
    NotificationReach,
    SupportOrigin,
    belief_view,
)
from ai_assistant.interfaces import cli
from ai_assistant.interfaces.gateway.records import RefusalCondition
from ai_assistant.interfaces.gateway.server import (
    packaged_bundle,
)
from ai_assistant.testing.memories import memory_in_band
from ai_assistant.wire import GRANTABLE_SCOPES

_ROOT = Path(__file__).resolve().parents[3] / "src" / "ai_assistant" / "interfaces" / "gateway"
_ASSETS = _ROOT / "assets"
_FONTS = _ASSETS / "fonts"

#: The faces the page is set in (#3113), each a file in the bundle. Written out rather
#: than read off the directory, so a face added to the sheet and not to the bundle — or
#: the reverse — is a difference between two lists and not two readings of one.
_FACES: Final = (
    "cormorant-garamond-latin-500-normal",
    "cormorant-garamond-latin-600-normal",
    "manrope-latin-400-normal",
    "manrope-latin-500-normal",
    "manrope-latin-600-normal",
    "jetbrains-mono-latin-400-normal",
)

#: The three families, each shipped with its licence beside it (SIL OFL 1.1).
_FAMILIES: Final = ("cormorant-garamond", "manrope", "jetbrains-mono")

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


@pytest.mark.integration
def test_the_bundle_is_read_out_of_the_installed_package() -> None:
    """§10: "The gateway serves only assets that shipped in the installed
    distribution. It fetches nothing at runtime"."""
    bundle = packaged_bundle()

    assert set(bundle) == {
        "/",
        "/app.css",
        "/app.js",
        "/door.js",
        *(f"/fonts/{face}.woff2" for face in _FACES),
    }
    assert all(body for body, _ in bundle.values())
    assert bundle["/"][1].startswith("text/html")
    for face in _FACES:
        body, media_type = bundle[f"/fonts/{face}.woff2"]
        assert media_type == "font/woff2", face
        # The file is a WOFF2 and not a page or a stub that happens to have the name.
        assert body[:4] == b"wOF2", face


@pytest.mark.integration
def test_the_hosted_bundle_differs_from_the_others_in_one_file() -> None:
    """ADR-0327 §11: the hosted listener serves this repository's page (§3:1, §4:7),
    and the one thing it serves differently is the file that says which door it is.

    So the page learns it is behind the sign-in door without asking the gateway anything
    before a session exists, which §7:4 would refuse — and both files ship in the
    distribution, so nothing is generated or transformed at serve time.
    """
    local = packaged_bundle()
    hosted = packaged_bundle(hosted=True)

    assert set(hosted) == set(local)
    differing = {path for path in local if local[path] != hosted[path]}
    assert differing == {"/door.js"}
    assert b'dataset.door = "local"' in local["/door.js"][0]
    assert b'dataset.door = "hosted"' in hosted["/door.js"][0]
    assert hosted["/door.js"][1] == local["/door.js"][1]


def test_the_bundle_lives_inside_the_package_that_ships_it() -> None:
    """Which is what puts it in the wheel: the build target packages
    ``src/ai_assistant``, so a file under it ships and a file beside it does not."""
    assert _ASSETS.parent.name == "gateway"
    assert (_ROOT / "server.py").exists()
    assert {path.name for path in _ASSETS.iterdir()} == {
        "index.html",
        "app.css",
        "app.js",
        "door.js",
        "door-hosted.js",
        "fonts",
    }
    # The faces, and each family's licence with them: the SIL Open Font License lets a
    # face be redistributed only with its copyright notice and the licence, so the
    # distribution that carries the one carries the other.
    assert {path.name for path in _FONTS.iterdir()} == {
        *(f"{face}.woff2" for face in _FACES),
        *(f"{family}-OFL.txt" for family in _FAMILIES),
    }
    for family in _FAMILIES:
        licence = (_FONTS / f"{family}-OFL.txt").read_text(encoding="utf-8")
        assert "SIL Open Font License, Version 1.1" in licence, family
        assert licence.startswith("Copyright"), family


def test_every_face_the_sheet_names_is_one_the_gateway_serves() -> None:
    """ADR-0168 §10's origin clause, at the one rule that loads a font (#3113).

    A ``url()`` in an ``@font-face`` is a request the page makes, so a face the sheet
    names that the bundle does not carry is a 404 on every load and a page set in the
    fallback — and one named by any path but the gateway's own is the off-origin load
    the clause forbids. Read both ways: every source the sheet asks for is a served
    path, and every face the bundle serves is one the sheet asks for, so nothing ships
    that nothing loads.
    """
    stylesheet = _style("app.css")
    asked = re.findall(r'url\("([^"]+)"\)', stylesheet)

    assert sorted(asked) == sorted(f"/fonts/{face}.woff2" for face in _FACES)
    assert stylesheet.count("@font-face {") == len(_FACES)
    assert set(asked) <= set(packaged_bundle())


def test_the_pages_name_is_written_once() -> None:
    """The name the page goes by is one edit to change (#3113).

    It is written in the document's ``<title>`` and nowhere else in the bundle: the
    bar's heading is empty in the document and takes the title's text at load, so the
    tab and the heading cannot disagree and a rename cannot miss one of them.
    """
    document = _markup("index.html")
    title = re.search(r"<title>([^<]+)</title>", document)

    assert title is not None
    name = title.group(1)
    assert name == "Aether"
    assert '<h1 id="page-name"></h1>' in document
    assert 'el("page-name").textContent = document.title;' in _code("app.js")
    for asset in ("index.html", "app.js", "app.css"):
        source = _markup(asset) if asset == "index.html" else _code(asset)
        assert source.count(name) == (1 if asset == "index.html" else 0), asset


@pytest.mark.parametrize("name", ["index.html", "app.css", "app.js", "door.js", "door-hosted.js"])
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
    belief's Forget, a notification's Dismiss and Forget, the fault slot's Dismiss and
    "Start a new conversation". None of them has a size rule of its own, which is the point: there
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
    clipped a value to fit a phone would breach them from the stylesheet, and pass every
    other check in this file.
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
    # ADR-0327 §7:7's seven are recorded and never answered: a browser on the hosted
    # listener is told `door-refused` whichever check failed (§7:6), and that one is
    # reachable — an assertion can lapse under a page that is already loaded.
    recorded_and_never_answered = {
        RefusalCondition.ASSERTION_ABSENT.value,
        RefusalCondition.ASSERTION_MALFORMED.value,
        RefusalCondition.ASSERTION_SIGNATURE.value,
        RefusalCondition.ASSERTION_ISSUER.value,
        RefusalCondition.ASSERTION_AUDIENCE.value,
        RefusalCondition.ASSERTION_SUBJECT.value,
        RefusalCondition.ASSERTION_TIMES.value,
    }

    reachable = (
        {one.value for one in RefusalCondition}
        - decided_before_the_page_exists
        - recorded_and_never_answered
    )
    assert reachable <= named, sorted(reachable - named)
    assert not decided_before_the_page_exists & named
    assert not recorded_and_never_answered & named
    assert RefusalCondition.DOOR_REFUSED.value in named
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

    It sits outside every panel, as a footnote at the page's foot (#3098), so it is under
    whichever of the bootstrap panel and the console is up: §6's clause is about the
    session the page "is running under" — the audience is an owner holding one, and the
    bootstrap panel is on screen exactly when there is none.
    """
    document = _asset("index.html")
    opened = document.index('<div class="session-conditions" id="session-terms">')
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
    # The one script that reaches it is the hosted page's, which hides it in favour of
    # ADR-0327 §11:7's statement — on the door whose page §15 supersedes ADR-0182 §6:3
    # for, and on no other (``test_the_hosted_page_states_how_long_it_stays_signed_in``).
    reaching = [line for line in _code("app.js").splitlines() if '"session-terms"' in line]
    assert reaching == ['  el("session-terms").hidden = true;']
    stylesheet = _style("app.css")
    assert stylesheet.count("display: none") == 1
    assert _rule(stylesheet, "[hidden]").strip() == "display: none !important;"
    assert "hidden" not in document[opened : document.index(">", opened)]
    markup = _markup("index.html")
    sentences = markup.index('<div class="session-conditions" id="session-terms">')
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
    # The page stores two other things, and neither is a session half: whether this
    # browser has the chat open (the browser's, so every load of a chat-first page opens
    # it again, #3098), and which conversation this tab reads (the tab's rather than the
    # origin's). So the clause is asserted where it is about — no half of a session is
    # ever in tab-scoped storage — and the key that is, is named.
    assert set(re.findall(r"window\.sessionStorage\.\w+\((\w+)", script)) == {
        "CHAT_CONVERSATION_KEY",
    }
    assert set(re.findall(r"window\.localStorage\.\w+\((\w+)", script)) == {
        "STORAGE_KEY",
        "CHAT_OPEN_KEY",
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

    Its own full-width line rather than a clause of the instants. The name is the one
    the chat gives a conversation — when it started — rather than the hub's id, which
    the chat no longer shows anywhere (#3209's follow-on); the id stays on the row for
    nothing on screen, as the chat's own rows carry it.
    """
    script = _code("app.js")
    stylesheet = _asset("app.css")
    rendering = _functions(script)["renderConversation"]

    assert 'line(item, conversationName(summary.id), "conversation-name");' in rendering
    assert "item.dataset.conversation = summary.id;" in rendering
    assert "summary.id}" not in rendering
    # First, so the name is above the row rather than between its two facts.
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
    assert "sayForgotten(statedForget(held, done.destroyed));" in functions["forgetConversation"]
    stated = functions["statedForget"]
    assert "if (!destroyed)" in stated
    assert "so nothing was forgotten." in stated
    assert "no longer recalls them anywhere else" in stated
    assert "only deleting removes them." in stated
    confirming = functions["forgetConversation"]
    assert "Forget the conversation from ${listedName(held)}?" in confirming
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
    {"bootstrap", "hosted", "console", "conversations", "notifications"}
)

#: The panels outside the hide sweep on purpose, recorded here so that the census below
#: states a decision instead of blessing whatever the list happens to contain.
#:
#: There are none. The one there was, ``answer``, held the reply a park's answer
#: rendered, and #2446 was filed against leaving it out; it retired with the
#: confirmations panel (ADR-0309 §5). The set is kept rather than dropped so that a
#: later panel left out of the sweep has to be named here with its reason.
_OUTSIDE_THE_HIDE_SWEEP: Final[frozenset[str]] = frozenset()


def test_every_panel_a_session_less_page_may_not_show_is_in_the_hide_sweep() -> None:
    """#2395: ``goals`` was in every census of this page except the one that hides it
    (the goals panel has since retired, ADR-0309 §5).

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

    assert sections - _NAMED_BY_SHOW_BOOTSTRAP - _OUTSIDE_THE_HIDE_SWEEP == swept
    assert swept <= sections
    assert "CONTROL_PANELS.forEach((panel) => show(panel, false));" in sweeping
    for panel in _NAMED_BY_SHOW_BOOTSTRAP - {"bootstrap", "hosted"}:
        assert f'show("{panel}", false);' in sweeping
    # Which of the two it opens is the door's (ADR-0327 §11:1): the bootstrap entry on
    # every door but the hosted one, and the hosted panel there.
    assert 'show("bootstrap", !HOSTED);' in sweeping
    assert 'show("hosted", HOSTED);' in sweeping


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
_ACTS_THAT_ACCOUNT_FOR_THEMSELVES: Final = frozenset({"dismissNotification"})


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
            # `stateAfterAct`, for one, which writes into an act's own log.
            continue
        # Captured before the first request goes out -- an era read on resumption is the
        # value it is being compared against and would never differ from it.
        assert body.index("const era = sessionEra;") < body.index("await relay("), name
        for where, part, displayed in asked:
            checked.append(where)
            assert "if (!sameSession(half, era)) {" in part, where
            assert part.index("if (!sameSession(half, era)) {") < displayed, where

    assert {
        ("readBeliefs", 1, "resumed"),
        ("readBeliefs", 1, "failing"),
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
    ``listAuthorizations``, since retired with its panel (ADR-0309 §5); this is the sweep.

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

    assert {"readBeliefs", "listConversations", "listConnections"} <= set(checked)
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
    version of this that did not. It is a fact about the *request* rather than about the
    panel: the chat's reads are told which refusal they got — a ``no-such-conversation``
    there is a conversation deleted elsewhere, which the page lets go — and a refusal
    withheld from them would be one the page cannot classify at all.
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
    # The conditions that mean the session is gone, and on the hosted door the one that
    # means nothing more is admitted through it (ADR-0327 §11:6).
    assert 'const barred = HOSTED && body.fault === "door-refused";' in lost
    assert (
        'if (barred || body.fault === "no-live-session" || body.fault === "cookie-half-mismatch") {'
    ) in lost
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
    (§1, §11), and the routes ADR-0309 §5 retires with the confirmations, questions,
    goals and authorizations panels are served by nothing either — so a page still
    reaching for one would get §6's residual fourth class.
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
        '"/candidates/pending"',
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
    ):
        assert served in script, served
    for unserved in (
        '"/learn"',
        '"/resume"',
        '"/pending_confirmations"',
        *(f'"{path}"' for path in _RETIRED_WITH_THEIR_PANELS),
    ):
        assert unserved not in script, unserved
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
    member the hub refuses. ADR-0318 §6:2 takes ``FACET`` out of the vocabulary, so
    the offer is ``NOTIFY`` alone, named in words.

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
    # ADR-0318 §6:2: the use nothing reads for is neither offered nor phrased.
    assert '"facet"' not in script

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
    # `renderStanding` goes through it — so the clause is checked once, where it can be
    # broken once.
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
    # ADR-0327 §8's exchange, the hosted page's stand-in for the bootstrap exchange.
    "exchangeSession": "exchangeSession",
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

#: The one ``fetch`` site whose answer, failure included, the page says nothing about:
#: ADR-0332 §5:5's composing signal. It is not something the person asked for and not
#: input (§5:8), so a rejected ``fetch`` there is a signal not sent and is not reported
#: as the gateway having gone — the person's next act, which is, says that in full.
_SIGNAL_SITE: Final = "sendComposing"

#: Every entry point reaching ``relay``, each of which catches a rejected `fetch`
#: itself. Enumerated rather than counted, for the reason issue #1332 records: a
#: threshold satisfied by five of six guards leaves the sixth deletable in silence.
_RELAY_ENTRIES: Final = (
    "forgetConversation",
    "listSources",
    "listStanding",
    "listGrantHistory",
    "readBeliefs",
    "forgetBelief",
    "listCandidates",
    "readNotifications",
    "dismissNotification",
    "forgetNotification",
    "listTuning",
    "writePreferences",
    "listConnections",
    "listConnectionLog",
)


#: Every panel a fault can be written into (#1429). Enumerated rather than derived
#: from the script, for the reason issue #1332 records one file over: a check that read
#: the panels out of the same expression it is checking would pass whatever that
#: expression became, including a page that had quietly gone back to one slot.
_FAULT_PANELS: Final = frozenset(
    {
        "bootstrap",
        "conversations",
        "notifications",
        "acts",
        # ADR-0338 §8:2's About you panel.
        "about",
        # ADR-0361 §4:6's approvals panel.
        "approvals",
        "sources",
        "standing",
        "history",
        "beliefs",
        "review",
        "tuning",
        "connections",
        "connection-log",
        "chat",
        # ADR-0327 §11: the hosted exchange's own `fetch`, whose rejection is the
        # gateway not answering, said beside the panel that is up while it is out.
        "hosted",
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
        _ACT_SITE,
        _SIGNAL_SITE,
    }
    for called, entry in _FETCH_SITES.items():
        guard = functions[entry]
        assert "} catch (" in guard, called
        assert _GATEWAY_GONE.search(guard), called
    # Every other entry point reaching `relay` is its own, and catches for itself.
    for entry in _RELAY_ENTRIES:
        assert _GATEWAY_GONE.search(functions[entry]), entry
    # And the one that refuses that report does refuse it, rather than having quietly
    # lost a guard: it still catches, and answers with an outcome that is not known.
    assert "} catch (" in functions[_ACT_SITE]
    assert not _GATEWAY_GONE.search(functions[_ACT_SITE])
    # The composing signal catches too, and reports nothing: no fault of any kind.
    assert "} catch (" in functions[_SIGNAL_SITE]
    assert "fault(" not in functions[_SIGNAL_SITE]


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
    resumes — and a caller can abort a request whose status has already been read.
    Routing that through ``readBody`` swallowed the abort and returned ``{}`` for a
    ``200``: an answer-shaped nothing. §7's fourth clause is explicit that "the request
    was sent and no response was read" is an outcome that is **not known** "whatever the
    gateway did", and ADR-0139 §4 forbids the surface resolving it. The park's answer
    that reached it retired with the confirmations panel (ADR-0309 §5); the rule stands
    for every caller.

    So the rejection is kept on the ``2xx`` path and ``readBody``'s swallow is left to
    the refusal path it was written for. Every caller already runs ``relay`` inside a
    ``try``, and each ``catch`` is the ending it wants.

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
    ``beliefs`` listing the page rendered earlier."

    The band-appropriate warning and the statement of what the consent covers are
    ADR-0073 §5's other two obligations, and they are in the same prompt.
    """
    forgetting = _functions(_code("app.js"))["forgetBelief"]

    assert 'relay(half, "/belief", { record_id: id }, "beliefs")' in forgetting
    assert forgetting.index('"/belief"') < forgetting.index("window.confirm(")
    assert forgetting.index("window.confirm(") < forgetting.index('"/belief/forget"')
    assert "forgetWarning(belief.band)" in forgetting
    assert "which may have changed since it was shown" in forgetting
    # Every field ADR-0328 §15:4 requires, through the one list the row renders too, and
    # every support from the read just taken (§15:2). A confirmation showing less than
    # the listing the user came from is the opposite of what a ceremony is for.
    for field in (
        "beliefHeading(belief)",
        "belief.content",
        "beliefLines(belief)",
        "belief.supports.map(supportLine)",
    ):
        assert field in forgetting, field
    assert "confidence" not in forgetting, "a memory carries none (ADR-0328 §15:3)"


def test_the_forget_warning_is_band_appropriate_and_total_over_the_bands() -> None:
    """ADR-0073 §5: the ceremony "is uniform in mechanism and asymmetric in message".

    Destroying an assertion is permanent; destroying a derived or attested memory
    removes the memory and not its origin. Read against ``core``'s own vocabulary.
    """
    script = _code("app.js")
    warning = _functions(script)["forgetWarning"]

    for band in BeliefBand:
        # `DERIVED` is the fall-through branch and is named in the prose rather than
        # in a comparison, which is what makes the function total.
        assert f'"{band.value}"' in warning or band is BeliefBand.DERIVED, band.value
    assert "Forgetting it is permanent" in warning
    assert "destroys my copy but not the " in warning
    assert "destroys the belief but not what I worked it " in warning


# --- ADR-0328 §15:4: what the panel shows of a memory ------------------------------
#
# **Read off the shipped script rather than executed**: this repository has no
# JavaScript runtime in its gate, so what is pinned is that each path *builds* the
# output §15:4 obliges, and the *rendered* output is recorded in the pull request from
# the page driven at both viewports.


def test_the_panel_says_every_standing_in_the_terminals_words() -> None:
    """ADR-0328 §15:4: the standing in plain words, the same on both surfaces.

    Total over ``core``'s :class:`MemoryStanding` and read against the CLI's own table,
    so a standing added in ``core`` or reworded on one surface fails here.
    """
    words = _functions(_code("app.js"))["standingWords"]

    for standing in MemoryStanding:
        assert f'if (standing === "{standing.value}") {{' in words, standing.value
        assert f'return "{cli._STANDING_WORDS[standing]}";' in words, standing.value


def test_the_panel_names_every_origin_in_the_terminals_words() -> None:
    """ADR-0328 §15:2's support lines: each origin in plain words, as the CLI says it."""
    script = _code("app.js")
    table = script[script.index("const ORIGIN_WORDS = {") :]
    table = table[: table.index("};")]

    for origin in SupportOrigin:
        assert f'{origin.value}: "{cli._ORIGIN_WORDS[origin]}"' in table, origin.value


def test_the_panel_shows_what_adr_0328_s15_4_requires() -> None:
    """Its age, its evidence summary where it is an inference, its reading certainty
    where that is not ``sure``, every let-down, and the legacy mark (§15:4); and the two
    marks §7:10 and §15:7 add. One list, which the row and the confirmation share.
    """
    functions = _functions(_code("app.js"))
    lines = functions["beliefLines"]

    assert '`Learned: ${belief.learned === null ? "unknown" : localTime(belief.learned)}`' in lines
    assert '`As of: ${belief.as_of === null ? "unknown" : localTime(belief.as_of)}`' in lines
    assert 'if (belief.reading_certainty !== "sure") {' in lines
    assert "if (track.let_down > 0) {" in lines
    assert "if (belief.legacy) {" in lines
    assert "if (belief.unbacked) {" in lines
    assert "if (belief.supports_gone) {" in lines
    assert "`id: ${belief.id}`" in lines
    why = functions["whyHeld"]
    assert "${evidence.supporting} piece(s) of support${across}${against}." in why, (
        "an inference says its evidence summary"
    )
    for name in ("beliefLines", "whyHeld", "renderBeliefFields", "beliefHeading"):
        assert "confidence" not in functions[name], f"{name} shows no confidence (§15:3)"


def test_a_gone_support_is_shown_as_gone_and_never_by_an_id() -> None:
    """ADR-0328 §15:7: a support whose part no longer resolves is a tombstone.

    The view carries no id for a support at all, so the line is built from its origin,
    source, instant and content, and a ``null`` content says it is gone.
    """
    support = _functions(_code("app.js"))["supportLine"]

    assert '"what it pointed at is gone"' in support
    assert "support.content === null" in support
    assert "points_at" not in support
    assert "id" not in re.findall(r"support\.(\w+)", support)


def test_a_supports_source_is_shown_with_its_own_report_time() -> None:
    """ADR-0189 §4 on each support: the source's reporting instant, said as its clock.

    Read off ``source_details.reported_at`` beside the source's name, never substituted
    by the support's ``when`` (when this system read the part), and in the terminal's
    words.
    """
    support = _functions(_code("app.js"))["supportLine"]

    assert "source.reported_by" in support
    assert "source.reported_at" in support
    assert "on its own clock" in support
    assert "support.when" in support  # the encounter time stays, apart from the report


def test_the_panel_says_the_evidences_latest_date_and_the_source_its_standing_rests_on() -> None:
    """§7:2's latest date for an inference, and ADR-0189 §4's source and clock on a row."""
    functions = _functions(_code("app.js"))

    assert "evidence.latest" in functions["whyHeld"]
    assert "None of it is dated." in functions["whyHeld"]
    assert "belief.attestation.reported_by" in functions["beliefLines"]
    assert "belief.attestation.reported_at" in functions["beliefLines"]
    assert "on its own clock" in functions["beliefLines"]


def test_the_browser_says_a_warrant_from_outside_in_the_terminals_sentence() -> None:
    """ADR-0189 §4's clause, read through ADR-0328 §12, the same on both surfaces.

    Read off ``rests_on_outside_content`` and never recomputed from the band (ADR-0189
    §2), silent on false rather than negative (ADR-0328 §7:7), and character for
    character the terminal's sentence: "a fact stated on one surface and not on its
    sibling is a fact a user learns to distrust on both".
    """
    functions = _functions(_code("app.js"))
    outside = functions["outsideWarrant"]

    assert 'if (!belief.rests_on_outside_content) {\n    return "";' in outside
    assert "band" not in outside, "the answer is read, never recomputed from the band"
    assert "outsideWarrant(belief)" in functions["whyHeld"]
    stamped = BeliefSummary.model_validate(
        belief_view(
            memory_in_band("rec-1", "the user likes jazz", BeliefBand.DERIVED, outside=True),
            now=datetime(2026, 3, 2, 8, 30, tzinfo=UTC),
            contents={},
        ).model_dump(exclude={"supports"})
    )
    returned = outside[outside.index('return "";') + len('return "";') :]
    assert _joined(returned) == cli._outside_warrant(stamped)
    assert "derived_from_external" not in _code("app.js"), (
        "and no client reads the raw field in the predicate's place (ADR-0106 §2)"
    )


def test_the_browser_renders_a_records_own_line_breaks_in_its_content() -> None:
    """#1890's other surface, verified rather than assumed.

    The content is inserted as ``textContent``, which carries a newline verbatim, into
    the one class whose rule keeps it (ADR-0216 §2: a property decidable by reading the
    shipped bytes is asserted in the text layer).
    """
    functions = _functions(_code("app.js"))
    fields = functions["renderBeliefFields"]
    styles = _asset("app.css")

    assert 'line(item, belief.content, "reply");' in fields
    assert "p.textContent = text;" in functions["line"], "inserted as text, never as markup"
    assert ".reply {\n  white-space: pre-wrap;" in styles

    # And the terminal's hazard does not arrive here: the content is a paragraph of its
    # own in a class the row's own fields do not use, so a forged "Why:" inside it
    # renders in the content's type, not in a field's.
    assert fields.count('"hint"') == 2, "the heading, and every line of beliefLines"
    assert fields.count('"reply"') == 1, "and the content is the one line that is not a field"
    assert ".hint {\n  font-size: 0.85rem;\n  color: var(--muted);" in styles


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
    reading = _functions(script)["readBeliefs"]
    assert "offerMore(list, body." in reading
    assert "limit: PAGE" in reading


def test_one_generation_is_taken_for_a_whole_listing_and_carried_into_each_read() -> None:
    """The gap between "check the run" and "check the *right* run".

    A run read back from the shared counter after an ``await`` is whatever number is
    current *then*, so two overlapping refreshes would both be accepted, both read
    offset zero, and both advance the same counter, putting the next page past a whole
    page of beliefs nobody can forget. (``listQuestions``, whose two listings made this
    sharpest, retired with the questions panel, ADR-0309 §5.)

    So the generation is taken once, before any await, and travels into every read and
    into the "Show more" each read offers — never re-read from the shared counter
    inside a function that has already suspended.
    """
    functions = _functions(_code("app.js"))

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


# --- ADR-0194 §5 and §6: the page shifts no instant -----------------------------


def test_the_page_renders_no_spend_bound_so_adr_0194_s6_has_no_renderer_here() -> None:
    """ADR-0194 §5 and §6: a spend period's bound is read "from the value's **own**
    ``start_offset``/``end_offset``… never from the client's zone and never through
    the client's ``tzdata``".

    The page renders no ``SpendTotal`` any more, so that clause has no renderer here,
    and the page-wide ban that stood for it gave way to #1392's ruling: an instant is
    shown in this browser's own zone (below). Should a spend bound come back to the
    page, this fails, so that its renderer is held to §6 rather than to the helper.
    """
    script = _code("app.js")

    for field in ("start_offset", "end_offset", "period_start", "period_end"):
        assert field not in script, field


def test_an_instant_is_shown_in_the_browsers_zone_through_one_helper() -> None:
    """#1392, ruled on #3209's follow-on: every instant the page prints is said in the
    browser's own language and zone — through one set of helpers, so a zone is reached
    for in one place, and only for a value that carries its own offset."""
    script = _code("app.js")
    functions = _functions(script)

    assert script.count("new Date(") == functions["instant"].count("new Date(") == 1
    assert "new Date(iso)" in functions["instant"]
    assert "INSTANT_SHAPE.test(iso)" in functions["instant"]
    assert "(Z|[+-]\\d{2}:\\d{2})$/" in script  # an instant without an offset is not one
    for line in script.splitlines():
        if "Intl." in line:
            assert line.startswith(("const LOCAL_", "const CHAT_TIME")), line
    assert "toLocale" not in script
    assert "getTimezoneOffset" not in script
    # The instants the panels print, each through the helper rather than as written.
    for shown in (
        "localTime(grant.decided_at)",
        "localTime(record.noticed_at)",
        "localTime(record.expires_at)",
        "localTime(belief.attestation.reported_at)",
        "chatTime(message.written_at)",
    ):
        assert shown in script, shown


# --- ADR-0296 §4: the chat and the devices it reaches ----------------------------


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


# --- ADR-0309 §5 and ADR-0313 §3: what retired from the page --------------------

#: The routes ADR-0309 §5 retires with the confirmations, questions, goals and
#: authorizations panels — and with What happened, which only a park's answer filled.
_RETIRED_WITH_THEIR_PANELS: Final = (
    "/confirmations",
    "/confirmation/resume",
    "/confirmation/cancel-read",
    "/questions",
    "/questions/interrupted",
    "/question/answer",
    "/question/forget",
    "/goals",
    "/clarification/withdraw",
    "/goal/abandon",
    "/authorizations",
    "/authorization/revoke",
)

#: The panels ADR-0309 §5 retires, and the controls that opened them — "What is waiting
#: for your answer" among them.
_RETIRED_PANELS: Final = ("answer", "confirmations", "questions", "goals", "authorizations")
_RETIRED_CONTROLS: Final = ("confirmations-button", "questions-button", "goals-button")


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


def test_the_page_offers_none_of_the_panels_adr_0309_retires() -> None:
    """ADR-0309 §5: the gateway loses What happened, the confirmations, questions, goals
    and authorizations panels, "and their routes with them".

    Read off both files, for the reason the case above gives: a panel or control left in
    the document is one the owner could open, and a path left in the script is a request
    the gateway now answers with a ``404``. The renderers go with them — the outcome a
    park's answer rendered, and the routed account inside it — so nothing in the script
    reads a turn's outcome at all. What stays is pinned beside it: the console offers the
    chat, and its menu the conversations listing and the control surface's panels, and
    nothing else (#3098 moved the control surface's openers into the console's menu).
    """
    script = _code("app.js")
    document = _markup("index.html")

    for path in _RETIRED_WITH_THEIR_PANELS:
        assert f'"{path}"' not in script, path
    for panel in _RETIRED_PANELS:
        assert f'<section id="{panel}"' not in document, panel
        assert f'"{panel}"' not in script, panel
    for control in _RETIRED_CONTROLS:
        assert f'id="{control}"' not in document, control
        assert f'el("{control}")' not in script, control
    for renderer in ("renderOutcome", "couldRenderOutcome", "renderConfirmation", "cancelRead"):
        assert renderer not in script, renderer
    console = document[document.index('<section id="console"') :]
    console = console[: console.index("</section>")]
    assert re.findall(r'<button type="button" id="([a-z-]+)"', console) == [
        "chat-button",
        # ADR-0361 §4:6's approvals panel, first in the menu: what waits on the owner.
        "approvals-button",
        "conversations-button",
        "about-button",
        "beliefs-button",
        "sources-button",
        "standing-button",
        "history-button",
        "review-button",
        "tuning-button",
        "connections-button",
        "connection-log-button",
    ]


def test_the_hosted_panel_offers_nothing_to_type() -> None:
    """ADR-0327 §11:1: "On the hosted listener the page shows no bootstrap entry. It
    mints its session by §8's exchange, with nothing typed." The hosted panel carries a
    line and one control, and the exchange sends no body (§8:1)."""
    document = _markup("index.html")
    opened = document.index('<section id="hosted" class="panel" hidden>')
    panel = document[opened : document.index("</section>", opened)]
    exchange = _functions(_code("app.js"))["exchangeSession"]

    assert "<input" not in panel
    assert "<form" not in panel
    assert '<button type="button" id="hosted-again" hidden>Try again</button>' in panel
    assert 'await fetch(EDGE_EXCHANGE_PATH, { method: "POST" });' in exchange
    assert "body:" not in exchange


def test_the_door_is_read_before_the_page_runs() -> None:
    """ADR-0327 §11: the page knows which door served it before it decides anything —
    `/door.js` is a parser-blocking script in the head, so it has run before `app.js`,
    which is the last thing in the body, reads it."""
    document = _markup("index.html")
    head = document[: document.index("</head>")]

    assert '<script src="/door.js"></script>' in head
    assert 'const HOSTED = document.documentElement.dataset.door === "hosted";' in _code("app.js")


def test_a_failed_exchange_is_followed_by_none_the_owner_did_not_ask_for() -> None:
    """ADR-0327 §11:3: no further exchange "until the owner acts, a reload included".
    Every failure sets the flag, nothing in the page clears it, and the owner's act is a
    reload — so no refusal, however it arrives, becomes a retry loop."""
    script = _code("app.js")
    functions = _functions(script)

    assert "if (exchanging || exchangeFailed) {" in functions["exchangeSession"]
    # Its declaration is the one place it is ever false.
    assert script.count("exchangeFailed = false") == 1
    assert script.count("let exchangeFailed = false;") == 1
    assert 'el("hosted-again").addEventListener("click", () => window.location.reload());' in script


def test_a_session_replaced_through_the_door_re_issues_nothing() -> None:
    """ADR-0327 §11:4: "The page re-issues no request a refusal interrupted." The console
    a resumed exchange brings back opens no stream of its own motion."""
    console = _functions(_code("app.js"))["showConsole"]
    resumed = console[console.index("if (resumed === true) {") :]

    assert resumed.index("return;") < resumed.index("watchDeliveries();")
    assert resumed.index("return;") < resumed.index("openChat();")


def test_a_pending_candidate_is_shown_by_its_fact_marked_pending_and_nothing_more() -> None:
    """ADR-0329 §18:1 and §18:3: each pending candidate by its fact, marked pending.

    The mark is a line of its own, before the fact, so no candidate reads as a belief;
    and a candidate carries no control, since ``forget`` names nothing by one. The
    section sits inside the belief panel and is hidden until a read finds one.
    """
    script = _code("app.js")
    functions = _functions(script)
    document = _markup("index.html")

    rendering = functions["renderCandidate"]
    assert rendering.index('"Pending: not remembered yet"') < rendering.index("candidate.fact")
    assert "button" not in rendering
    assert "candidate.episode_id" not in rendering
    assert 'relay(half, "/candidates/pending", {}, "beliefs")' in functions["listCandidates"]
    assert 'el("pending-candidates").hidden = held.length === 0;' in functions["listCandidates"]
    assert functions["openBeliefs"].index("listBeliefs()") < functions["openBeliefs"].index(
        "listCandidates()"
    )
    assert 'fromMenu("beliefs", openBeliefs)' in script
    panel = document[document.index('<section id="beliefs"') :]
    panel = panel[: panel.index("</section>")]
    assert '<div id="pending-candidates" hidden>' in panel
    assert '<div id="pending-list"></div>' in panel


def test_no_top_level_function_is_declared_twice() -> None:
    """A second declaration of one name replaces the first silently, page-wide.

    A script's function declarations are hoisted and the last one wins, so a panel that
    reuses a name another panel already declared breaks that other panel with no error
    anywhere — which is what a ``renderPending`` for the pending candidates did to the
    chat's own before it was renamed.
    """
    declared = re.findall(r"^(?:async )?function (\w+)\(", _code("app.js"), flags=re.MULTILINE)

    assert sorted(name for name in set(declared) if declared.count(name) > 1) == []
