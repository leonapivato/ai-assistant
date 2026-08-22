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

from ai_assistant.core.types import BeliefBand, GrantScope
from ai_assistant.interfaces.gateway.server import packaged_bundle

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


def _asset(name: str) -> str:
    """One shipped file, as text."""
    return (_ASSETS / name).read_text(encoding="utf-8")


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
    assert "sessionStorage" not in script


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

    Held in page state rather than in browser storage: the hub owns the
    conversation, a reload is a new page asking the hub again, and nothing about a
    conversation belongs beside the session half.
    """
    script = _code("app.js")

    assert "conversationId" in script
    assert "asked.conversation_id = conversationId" in script
    assert "localStorage.setItem(STORAGE_KEY" in script
    assert 'setItem("assistant.conversation' not in script


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
    assert "STREAM_CUT" in script
    assert "ended before the gateway finished it" in script


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
    assert "renderOutcome(terminal.outcome);" in script
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
    """
    script = _code("app.js")

    for named in ("delivery_id", "acknowledg", "dismiss"):
        assert named not in script, named


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
    assert "setTimeout" not in script
    assert "setInterval" not in script


def test_the_page_reaches_what_the_gateway_serves_and_nothing_beyond_it() -> None:
    """ADR-0177 §1's enumeration, at the only other place a path could be written down.

    A path here that the gateway does not serve would be a front end asking for a
    later lane's surface and getting ADR-0168 §6's residual fourth class — and the
    two halves ship in one distribution (ADR-0168 §10), so the disagreement would be
    shipped rather than discovered.

    The negative half is what is **not** this lane's: ``learn`` is admitted by
    nothing (§1, §11), the CONFIRM pair's act is blocked until #1366's contract lands
    (§8), and the notification review five and the connection five belong to lanes
    that have not run.
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
    ):
        assert served in script, served
    for later in ('"/learn"', '"/resume"', '"/pending_confirmations"', '"/notifications"'):
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
    """
    script = _code("app.js")

    for use in GrantScope:
        assert f'value: "{use.value}"' in script, use.value
    # Named in words rather than by member name: the value is what goes on the wire,
    # and the label beside it is what the person reads.
    assert script.count("label:") == len(GrantScope)


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
    assert "usePhrase(grant.scope)" in _functions(script)["renderStanding"]
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

    assert 'relay(half, "/conversation", { conversation_id: id })' in script
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
    "watchDeliveries": "watchDeliveries",
    "relay": "listConversations",
}

#: The one ``fetch`` site that deliberately does **not** report a rejection as the
#: gateway having gone (ADR-0177 §7's fourth clause). A rejected `fetch` on a
#: mutating act is an outcome that is **not known** — the request was sent and no
#: response was read, and the gateway may already have called — so reporting it as
#: "the gateway did not answer" would assert the one thing ADR-0139 §4 spends five
#: clauses refusing to let a surface assert.
_ACT_SITE: Final = "act"

#: Every entry point reaching ``relay``, each of which catches a rejected `fetch`
#: itself. Enumerated rather than counted, for the reason issue #1332 records: a
#: threshold satisfied by five of six guards leaves the sixth deletable in silence.
_RELAY_ENTRIES: Final = (
    "forgetConversation",
    "listSources",
    "listStanding",
    "listGrantHistory",
    "listBeliefs",
    "forgetBelief",
    "listQuestions",
    "answerQuestion",
    "forgetQuestion",
    "observe",
)


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
        assert "fault(GATEWAY_GONE)" in guard, called
    # Every other entry point reaching `relay` is its own, and catches for itself.
    for entry in _RELAY_ENTRIES:
        assert "fault(GATEWAY_GONE)" in functions[entry], entry


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
    """
    reading = _functions(_code("app.js"))["readBody"]

    assert "parsed !== null" in reading
    assert 'typeof parsed === "object"' in reading
    assert "!Array.isArray(parsed)" in reading


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

    assert 'relay(half, "/belief", { record_id: id })' in forgetting
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

    assert "relay(half, path, {})" in forgetting
    assert "body.questions.find((one) => one.id === id)" in forgetting
    assert "if (question === undefined)" in forgetting
    assert forgetting.index("window.confirm(") < forgetting.index('"/question/forget"')
