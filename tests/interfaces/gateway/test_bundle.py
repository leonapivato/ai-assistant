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

from ai_assistant.core.types import (
    DEFAULT_NOTIFICATION_REACH,
    BeliefBand,
    DiscloserProvenance,
    GrantScope,
    NotificationCondition,
    NotificationReach,
)
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
    assert "setTimeout" not in script
    assert "setInterval" not in script


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
    "answerConfirmation",
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

    assert "relay(half, path, { limit: PAGE, offset })" in forgetting
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

    assert 'relay(half, "/notification/preferences", {})' in write
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

    assert 'relay(half, "/notifications", { limit: PAGE, offset })' in forget
    assert "body.notifications.find((one) => one.id === id)" in forget
    assert "fault(NOTIFICATION_GONE)" in forget
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

    assert 'relay(half, "/connections", {})' in after
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

    The three functions below are the whole of what touches it — it reaches the answer
    through a closure — and none of them puts it in a text node, in an attribute or in
    ``localStorage``.
    """
    script = _code("app.js")
    functions = _functions(script)

    assert {name for name, body in functions.items() if "token" in body} == {
        "renderConfirmation",
        "offerApproval",
        "answerConfirmation",
    }
    assert not re.search(r"textContent\s*=[^;]*token", script)
    assert not re.search(r"\bline\([^)]*\btoken\b", script)
    for name in ("renderConfirmation", "offerApproval", "answerConfirmation"):
        assert "localStorage" not in functions[name], name


def test_the_answer_supplies_approved_and_nothing_else() -> None:
    """ADR-0177 §8's second clause and §9: "The browser's answer supplies ``resume``'s
    ``approved`` argument and nothing else", and ``timeout`` is the caller-owned
    deadline §1 and §9 place with the gateway.

    Read off the request body the page actually writes, which is where a third member
    would appear.
    """
    body = _functions(_code("app.js"))["answerConfirmation"]

    assert 'relay(half, "/confirmation/resume", { token, approved })' in body
    assert "timeout" not in body


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
    """
    body = _functions(_code("app.js"))["renderOutcome"]

    assert "if (outcome.steps.length === 0 && outcome.step === null) {" in body
