// The front end. Three rules shape every line of it.
//
// **Every value the hub returned is inserted as text and never as markup**
// (ADR-0168 §6, ADR-0175 §9). An answer is model output, a notification's summary
// and detail are producer text, and neither is a trusted source of markup — so this
// file builds nodes and sets `textContent`, and never touches `innerHTML`,
// `insertAdjacentHTML`, `document.write` or `eval`.
//
// That immunity belongs to the *mechanism* rather than to care taken here, which is
// why ADR-0175 §9 states the alternative rather than assuming it: a DOM text node
// has no escaping step to split, so appending two text nodes produces two text
// nodes. A front end that ever rendered a hub value *by markup* would lose that and
// inherit ADR-0173 §10's boundary clause whole — neutralisation applied to text it
// has accumulated, on boundaries its own renderer controls, and never independently
// to each chunk as it arrives.
//
// **The header half lives in `localStorage`, which is scoped to scheme, host and
// port and shared across that origin's tabs** (ADR-0168 §6). A cookie is not
// port-scoped, which is the whole reason a session is two values; web storage is,
// so the value at `127.0.0.1:8422` is unreadable from `127.0.0.1:9000`. The other
// half is the `HttpOnly` cookie the gateway set, which this file cannot read and
// never tries to.
//
// **Every stream is a response body on a request this page made** (ADR-0175 §1).
// There is no `WebSocket` and no `EventSource` here, and their absence is
// mechanical rather than stylistic: neither lets a page set a request header on the
// request that opens it, so on either one the header half above has nowhere to go
// that ADR-0168 §6 admits — and a request carrying the cookie half alone is refused
// exactly as one carrying neither is.
//
// **A fault is written beside the act that raised it** (#1429). One slot at the foot
// of a thirteen-panel page is a condition the owner has to go and find, which is
// ADR-0083's ruling 4 losing at the last hop: the difference between a transport
// failure and a refusal survives the whole system and then arrives off-screen. Each
// panel carries its own slot and its own dismiss control, and the foot slot is kept
// for the faults no panel owns — the page's own load, and the session.
//
// **Nothing here retries on a timer and nothing re-arms in silence.** ADR-0168 §9
// forbids the gateway retrying silently, and a page spinning against an unreachable
// hub would be that failure in the front end's clothes — so what is forbidden is the
// silence, not the reconnect. This file re-establishes the delivery stream when the
// owner brings the page back to the foreground or the device's network returns, and
// **says in the page that it did and why**. That costs nothing: an abandoned delivery
// stream costs the browser "a reconnect — which is free, because a session outlives
// its connections" (ADR-0175 §4).
//
// **There is one clock here and it opens nothing** (#1442). `setInterval` does not
// appear at all, and the single `setTimeout` bounds how long a delivery stream may
// say *nothing* before this page abandons it — it ends a stream, restores the
// owner's own control, and re-establishes nothing. ADR-0182 §7 forbids re-arming "on
// a timer, on a schedule, or on the failure itself", and re-arming is exactly what
// this clock does not do: after it fires the page holds no stream, and what opens
// the next one is one of §7's two events or the owner's click.

"use strict";

const STORAGE_KEY = "assistant.session.header-half";
const CONVERSATION_KEY = "assistant.session.conversation-id";

// The response header a delivery stream states its own keep-alive cadence in, as a
// decimal count of microseconds (#1442, ADR-0175 §4, §8).
//
// **Read off the head, so nothing has to be remembered between streams.** The figure
// is a fact about the gateway process serving *this* stream, and the head is the part
// of a streamed response that exists before the body does — `fetch` settles with the
// headers in hand and not one value read. So a stream is bounded by what its own
// gateway said, from before its first value, and a gateway reconfigured between two
// streams is never held to the figure the earlier one served.
//
// **It is not a session value and is stored nowhere.** It admits nothing and is
// spendable against nothing, so ADR-0172 §1's closed class of three values a browser
// holds is untouched — and it is not in `localStorage` at all, which is what keeps a
// stale figure from bounding a stream that never uttered it.
//
// Same-origin, so every response header is readable here without the gateway exposing
// any: ADR-0168 §6 admits a request only with both halves of a web session, and the
// header half travels "only as a request header the front end sets", which no
// cross-origin page can do.
const KEEP_ALIVE_HEADER = "X-Assistant-Keep-Alive-Microseconds";
const SESSION_HEADER = "X-Assistant-Session";

// Which stream values end a stream (ADR-0175 §2). A reader that reached one has the
// whole of what the gateway sent; a reader whose body ended without one has a
// transport failure and says so — which is ADR-0168 §9's distinction reaching the
// browser, on a carrier whose status code was written before anything went wrong.
const TERMINAL_KINDS = new Set(["outcome", "fault"]);

// The conversation the last turn ran under. The hub owns the conversation; this is
// the id it handed back, held so the next question continues the same one rather than
// starting a fresh one the owner never asked for — the same thing
// `assistant ask --conversation` does at the terminal.
//
// **It is persisted, under the session's own scoping argument** (ADR-0168 §6, #1429).
// Web storage is scoped to scheme, host and port, which is exactly the property that
// makes it fit to hold the header half: the id at `127.0.0.1:8422` is unreadable from
// `127.0.0.1:9000`. An earlier draft of this file kept it in page state alone, and the
// milestone-14 phone QA found what that costs — a reload silently started a
// conversation the owner never asked for, and the page could not say which one the
// next question would land in (#1371's first clause).
//
// **In `sessionStorage`, which is the tab's, and deliberately not beside the header
// half.** The two values want opposite scopes, and §6 names the difference: the header
// half is "shared across that origin's tabs", because it admits the browser. Which
// conversation you are reading is not — it is what *this view* is looking at, and two
// tabs are two views. Put in `localStorage` it would be one selection for the origin,
// so a second tab choosing a thread would silently retarget the first one's next
// question at its own reload; adversarial review raised that on round 1 and it is
// right. The tab's own storage survives a reload, which is the whole of what was
// asked, and stops there.
//
// The lifetime is also the closer match. The cookie half is a session cookie, so
// closing the browser generally strands the session anyway (ADR-0168 §6's own note on
// what a restoring browser does) — a thread outliving the tab would point into a
// session that is gone.
//
// **It is an id and not a capability.** It admits nothing on its own: every request
// carrying it is admitted by ADR-0168 §6's two values and by nothing else, so a
// conversation id read out of storage without them reaches no conversation.
//
// **Which is why clearing it is tidiness rather than a guarantee, and this comment
// says so rather than claiming the stronger thing.** It goes when *this view* forgets
// its session half and when the conversation itself is forgotten, and that is the
// whole of it. A second tab that bootstraps a replacement session clears its own
// selection and no other, so this tab's next question can continue the thread it was
// already reading under the new session — which is not a fault to engineer against: a
// conversation is the hub's, it outlives every gateway session by construction, and
// `assistant ask --conversation` at a terminal does exactly the same thing. The hint
// says which conversation it is, so nothing about it is silent. Adversarial review
// raised it on round 2 against an earlier draft of this paragraph that overclaimed;
// what was wrong was the sentence, and this is the correction.
let conversationId = storedConversation();

// How many times the selection has been changed by anything other than a turn's own
// answer. A turn carries the count it was sent under, and the conversation the hub
// names is adopted only if that count still stands.
//
// **Without it the owner's act loses a race to a slow answer.** Ask under `C`, then
// press "Start a new conversation" while that request is still out: the selection
// clears, the answer arrives, and `renderOutcome` puts `C` back — so the next question
// continues the thread the owner had just, explicitly, left. The Ask button is
// disabled for the duration and this control is not, deliberately: leaving a thread is
// not something to make the owner wait for. Adversarial review found it on round 4.
//
// It is the questions listing's own device (`runs`) and the confirmations listing's
// (`pendingRun`), at the third place in this file where two acts race over one value.
let chose = 0;

// How many disclosed cadences of silence end a delivery stream (#1442).
//
// **Derived rather than chosen, which is why there is no second figure to configure.**
// ADR-0175 §4 obliges the gateway to write on every open delivery stream "at least
// once per `gateway_notification_budget`" — a delivery where its poll returned one,
// and otherwise a value carrying nothing but its own kind — so one missed write is
// within what jitter, a slow overlay hop and a backgrounded tab's throttled timers can
// each produce on a stream that is perfectly alive. Three is the smallest multiple
// that survives one late write and still bounds detection to a minute at ADR-0175 §8's
// twenty-second default. It is a front-end constant and not a `Settings` field on
// purpose: ADR-0168 §12 leaves the page's own behaviour to the lane that ships it,
// because the page and the gateway version in one distribution, and a second
// configurable duration would be a number that can disagree with the one §8 names —
// which is §8's own argument against a separate heartbeat interval.
const SILENT_CADENCES = 3;

// The longest one `setTimeout` can be asked for. It carries its delay in a signed
// 32-bit count of milliseconds and **clamps** anything above this to fire *immediately*,
// so a deadline past it is not a long wait — it is an instant abort wearing one's
// clothes. A deadline longer than this is therefore armed in segments against an
// absolute instant rather than refused, which is what keeps the rule exact: the bound is
// three times the cadence the gateway disclosed, whatever the gateway disclosed.
//
// **An earlier draft treated an unrepresentable figure as no figure at all**, leaving
// such a stream unbounded — and adversarial review was right on round 3 that this
// re-opens #1442 for exactly the configurations it is hardest to notice on.
// `gateway_notification_budget` is validated as strictly positive and against nothing
// else (ADR-0175 §8), so a budget above about 8.3 days reached the ceiling once the
// multiple was applied. A representability limit is not a policy, and this is the
// platform's own number rather than a figure this page chose — which is why naming it
// is not a second claim about the cadence.
const TIMER_SEGMENT = 2147483647;

// How long a delivery request may be outstanding with **no head at all** before this
// page abandons it (#1474). It is the one duration in this file that comes from nowhere
// but the page, and it is owed a harder argument than the multiple above for exactly
// that reason.
//
// **No figure of the gateway's reaches this interval, because ADR-0175 §4's obligation
// begins at an open stream.** §4 has the gateway write on "every **open** delivery
// stream" at least once per `gateway_notification_budget`; a request whose head has not
// arrived is not a stream the gateway has said anything about, so there is no disclosed
// figure to derive from and none to hold it to. That is why `usableCadence`'s rule —
// believe what the gateway stated, substitute nothing — does not govern here: it is
// about a figure the gateway uttered, and here it has uttered none. Deriving one from
// an earlier stream's head would be exactly the substitution that rule refuses, and it
// would leave #1474's own case unbounded anyway, because that browser has no earlier
// stream.
//
// **What it bounds is a round trip and an in-process table read, and nothing else.**
// `server.py` writes `render_stream_head` and drains it *before* it awaits the body, and
// `_deliveries` builds that head from `DeliveryFanOut.open()` and a settings field — so
// a healthy head waits on no poll, no hub, no model and no assistant. Both ends of
// ADR-0174's split are near by construction: the loopback listener is the same machine,
// and the remote listener is one overlay hop to a device on the owner's own tailnet.
// Thirty seconds is orders of magnitude above either in health, and it sits under the
// minute `SILENT_CADENCES` bounds the other half of this failure to at ADR-0175 §8's
// twenty-second default — so a head that never came never strands the owner longer than
// a body that went quiet.
//
// A front-end constant and not a `Settings` field, for `SILENT_CADENCES`' reason:
// ADR-0168 §12 leaves the page's own behaviour to the lane that ships it, and this
// figure paces nothing the gateway does, so it is not a second number that can disagree
// with the one ADR-0175 §8 names. It is stated in milliseconds and says so in its name,
// which is `KEEP_ALIVE_HEADER`'s own principle one surface out: a bare number whose unit
// lives only in a comment is the one thing a reader misreads silently.
const HEAD_DEADLINE_MILLISECONDS = 30000;

// Whether a delivery stream is open. One at a time: a second would be a second poll
// the hub would close under ADR-0131 §2, and the gateway holds one poll however
// many streams watch it (ADR-0175 §4).
//
// **A request that has produced no value is held, and that is a reading of ADR-0182 §7
// rather than an implementation convenience** (#1474). §7's third clause permits a
// re-establishment "only while it holds none — one the gateway ended with ADR-0175 §4's
// terminal value, or one whose connection failed", and a `fetch` still pending has
// reached neither of the two endings §7 admits, so on §7's own text it is not none. The
// clause's ground says the same thing louder: it exists because §4 writes each delivery
// "to **every** delivery stream open at the moment it returned" and because each stream
// "holds a connection against `gateway_max_browser_connections`", and both of those are
// counted at the *gateway*. A page whose head was black-holed on the way back cannot
// tell that the gateway did not open a stream for it — so a page that read "holds" as
// "has read a value from" would open a second while the gateway held two, defeating the
// clause exactly where nothing can observe it. #1474 floats that redefinition and it is
// refused here on those grounds. What is bounded instead is how long the holding may
// last with nothing arriving, which §7's third clause says nothing about: it is a rule
// about concurrency, not about duration.
let watching = false;

// The delivery stream this page is reading, or `null` while it holds none (#1542).
//
// **Beside `watching` rather than a second copy of it**, because the two answer
// different questions: `watching` is what the page *says* it is doing and what
// `deliveryState` renders the owner's control from, and this is the request itself,
// held so that something outside `readDeliveries` can end it. Before it existed the
// controller was a local of that function and nothing could reach it, so `sessionLost`
// changed the line and the button and left the socket open — and the owner's re-entry
// then opened a **second** stream while the gateway still held the first.
//
// **Which is ADR-0182 §7's third clause breached at the one place nothing can observe
// it.** §7 has the page hold "at most one delivery stream at a time" and re-establish
// one "only while it holds none", and the cost is counted at the *gateway*: ADR-0175 §4
// writes each delivery "to **every** delivery stream open at the moment it returned",
// forbids the gateway to de-duplicate, and gives each stream one of
// `gateway_max_browser_connections`. So the browser renders every notification twice
// and nothing at either end can tell why.
//
// **The `409` is the case that does not close itself, and it is why this is not a
// race worth leaving.** `no-live-session` is answered for a session that is gone, and
// ADR-0175 §7 ends every stream that session held, so the first stream settles on its
// own; `cookie-half-mismatch` is answered for a session that is **live**, the gateway
// ends nothing, and the duplicate stream runs for as long as that session lasts.
//
// `released` is carried on the record rather than in a variable of this file, so the
// ending is read off the stream it belongs to: a stream this page let go is not the
// gateway having gone and must not be announced as one.
let streaming = null;

const el = (id) => document.getElementById(id);

function headerHalf() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch (_) {
    // A browser with storage denied cannot hold half a session, which is a
    // legible "start a session" rather than an error: the bootstrap panel is
    // shown and the exchange will fail the same way on the next attempt.
    return null;
  }
}

function rememberHeaderHalf(value) {
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
    return true;
  } catch (_) {
    return false;
  }
}

// One decimal count of microseconds, as milliseconds, or `null` where it is not a
// figure a deadline can be derived from. `Headers.get` answers `null` for a header
// that was not sent, and the guard is on the *value* rather than on its presence:
// `""`, `"0"` and anything unparseable would each arm a timer that fired at once or
// never.
//
// **A header this page cannot use leaves the stream unbounded**, exactly as every
// stream was before the deadline existed, and no other figure is substituted. That is
// the conservative direction and adversarial review settled it in act one: falling
// back to some earlier figure holds a gateway *entitled* to a thirty-day budget, and
// disclosing it honestly, to the twenty seconds a differently configured process
// served — and then repeats the false timeout on every stream after it. A gateway that
// says it may be silent for a month is believed rather than second-guessed against a
// figure it never uttered.
//
// **Every strictly positive figure is usable, however large**, because the deadline is
// armed in segments (`TIMER_SEGMENT`) rather than in one `setTimeout` call. `Infinity`
// is not one: a non-finite value is a figure with no instant to compute.
//
// **There is no floor either, and none is owed.** A gateway configured to write every
// microsecond has promised something no network delivers, so a page that abandons the
// stream is applying ADR-0175 §4's rule faithfully rather than misreading it — and it
// says so, naming the setting, every time.
function usableCadence(microseconds) {
  const value = Number(microseconds);
  return typeof microseconds === "string" && Number.isFinite(value) && value > 0
    ? value / 1000
    : null;
}

function forgetHeaderHalf() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch (_) {
    // Nothing to do: a browser that will not store will not have stored.
  }
  // The conversation goes with the session, in one place rather than at each of the
  // callers: a thread carried into a session the owner started afresh would be this
  // page continuing something the hub was never asked to continue.
  changeConversation(null);
}

function storedConversation() {
  try {
    return window.sessionStorage.getItem(CONVERSATION_KEY);
  } catch (_) {
    return null;
  }
}

// Which conversation the next question lands in, held and said (#1371's first clause).
//
// **"None yet" is said rather than left blank.** The hint used to be empty until a
// turn came back, and an empty line is what left the owner unable to tell a fresh
// thread from a continued one on the phone.
// Every route that changes the selection **except** a turn's own answer: the owner
// leaving a thread or continuing one, a session starting or ending, and a selection
// the gateway has told this page is stale. Each of them outranks an answer that was
// already in flight, and bumping the count in one place is what says so.
function changeConversation(id) {
  chose += 1;
  setConversation(id);
}

function setConversation(id) {
  conversationId = id;
  try {
    if (id === null) {
      window.sessionStorage.removeItem(CONVERSATION_KEY);
    } else {
      window.sessionStorage.setItem(CONVERSATION_KEY, id);
    }
  } catch (_) {
    // A browser that will not store still holds the id for this page's life. What it
    // loses is the thread surviving a reload, and nothing else.
  }
  el("conversation").textContent =
    id === null
      ? "No conversation yet. Your next question starts one."
      : `Conversation ${id}. Your next question continues it.`;
  el("new-conversation").hidden = id === null;
}

// Leave the thread this view is reading, and do nothing else.
//
// **It sends nothing.** Which conversation the next question lands in is this page's
// own selection, and dropping it is a local act — the hub is not told, nothing is
// destroyed, and the conversation it was reading is untouched and still in the
// listing. Forgetting a conversation is the other control and it is a different act.
//
// **It is the escape a persisted selection owes.** Before this file kept one, a
// reload started a fresh thread; now it does not, so a thread the hub will no longer
// accept has to have a way out that does not depend on the page being able to tell
// *why* — and it cannot: the gateway reports a declined turn as `assistant-declined`
// whatever the hub declined it for, so a page clearing the selection on that name
// would drop the owner's thread on any refusal at all.
function startFresh() {
  fault(null, "console");
  changeConversation(null);
  el("utterance").focus();
}

function show(id, visible) {
  el(id).hidden = !visible;
  indexPanels();
}

// --- the index of what is on screen (#1429) ----------------------------------
//
// **A phone is about a third of one panel tall, and this page grows a panel every time
// a listing is read.** By the fourth read the answer to the control the owner pressed
// is a thousand pixels below the button that asked for it, and the only way to any of
// the thirteen is to scroll past all of them.
//
// **Rebuilt from `show`, which is the one place a panel's visibility changes.** So the
// index cannot disagree with the page: there is no second record of what is open, and
// a panel added later is indexed without this function learning its name.
//
// **Each name is the panel's own heading**, read off the document rather than held in
// a table here, for the reason the confirmation prompt has no template: a second place
// a panel is called something is a place for one of the two to go stale.
//
// **It adds nothing and hides nothing.** The alternative #1429 offers — collapsing the
// panels and keeping one open — was not taken: a surface that can show only the panel
// it last opened decides for the owner which question they are looking at, and this is
// the page whose ADRs spend clause after clause on one answer never standing in for
// another (ADR-0139 §1, ADR-0177 §6). A long page with an index is the weaker claim
// and the correct one. Nothing here is a timer and nothing here is a request: an
// in-page link is the browser scrolling the document it already has.
//
// **The floor is two.** An index listing the one panel it sits under is not navigation,
// it is a second heading for it.
const PANEL_INDEX_FLOOR = 2;

function indexPanels() {
  const nav = el("panel-index");
  clearNode(nav);
  const open = [...document.querySelectorAll("section.panel")].filter(
    // The bootstrap panel is never indexed: it is on screen exactly when nothing else
    // is, so a link to it could only ever point at the page the reader is already on.
    (panel) => !panel.hidden && panel.id !== "bootstrap"
  );
  open.forEach((panel) => {
    const link = document.createElement("a");
    link.href = `#${panel.id}`;
    // The heading, which `faultSlot` inserts *after*, so this stays the heading even
    // in a panel that is carrying a fault.
    link.textContent = panel.firstElementChild.textContent;
    nav.appendChild(link);
  });
  nav.hidden = open.length < PANEL_INDEX_FLOOR;
}

// --- where a fault is written (#1429) ----------------------------------------
//
// **Beside the act that raised it.** A panel's slot is built here rather than written
// out thirteen times in `index.html`: it is the page's own furniture, no hub value
// reaches it as anything but `textContent`, and a fragment repeated once per panel is
// thirteen places for one of them to drift. The slot sits immediately under the
// panel's heading, above whatever the panel last managed to render.
//
// **`null` names the page foot**, which keeps its slot for the faults no panel owns:
// the page's own load, and the session. That slot is in the document, because it has
// to exist before anything has been built.
const faultSlots = new Map();

function faultSlot(panelId) {
  if (panelId === null) {
    return el("fault");
  }
  const held = faultSlots.get(panelId);
  if (held !== undefined) {
    return held;
  }
  const node = document.createElement("div");
  node.className = "fault";
  node.hidden = true;
  const text = document.createElement("p");
  text.className = "fault-text";
  node.appendChild(text);
  node.appendChild(offerDismiss(panelId));
  const panel = el(panelId);
  panel.insertBefore(node, panel.firstElementChild.nextSibling);
  faultSlots.set(panelId, node);
  return node;
}

// **Dismissing takes the condition off the screen and does nothing else.** It retries
// nothing, sends nothing, and asserts nothing about whether the condition still holds
// — a control that quietly re-ran the act would be exactly the silent retry ADR-0168
// §9 forbids, wearing a button's clothes.
function offerDismiss(panelId) {
  const dismiss = document.createElement("button");
  dismiss.type = "button";
  dismiss.className = "fault-dismiss";
  dismiss.textContent = "Dismiss";
  dismiss.addEventListener("click", () => fault(null, panelId));
  return dismiss;
}

function fault(message, panelId) {
  const where = panelId === undefined ? null : panelId;
  const node = faultSlot(where);
  node.firstElementChild.textContent = message === null ? "" : message;
  node.hidden = message === null;
  if (message !== null && where !== null) {
    // A read that failed before its panel was ever shown would otherwise write the
    // reason into a panel nobody can see, which is the flattening ADR-0168 §9 forbids
    // arriving as silence. A panel carrying a fault is still a panel showing an
    // answer: the answer is that the read did not happen.
    show(where, true);
  }
}

// Every slot at once, for the two moments the page changes what it is — a session
// starting and a session ending. Nothing else clears a panel it is not acting in: a
// fault about the connection surface is still true while the owner reads beliefs.
function clearFaults() {
  fault(null);
  faultSlots.forEach((_, panelId) => fault(null, panelId));
}

function clearNode(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

function line(parent, text, className) {
  const p = document.createElement("p");
  if (className) {
    p.className = className;
  }
  p.textContent = text;
  parent.appendChild(p);
  return p;
}

// One parsed JSON document as an object, or `{}` for anything else.
//
// **A body that is not an object is not distinguished from an absent one**, which is
// the gateway's own `_payload` rule read from this side: every caller reads named
// members, so a second failure mode would be a second way to say the same thing.
//
// The normalisation is load-bearing rather than tidy. `null` is a valid JSON document,
// so a reader returning it hands every caller a value that throws on the first member
// read — and on a grant act that throw would escape as "the gateway did not answer",
// which is not one of the three outcomes ADR-0139 §4 requires the act to be reported
// as. An unreadable condition has to arrive as an unnamed one, not as an exception.
//
// **It is the shape rule and nothing else**, which is what lets the two readers below
// disagree about a body that could not be read at all while agreeing about this.
function asObject(parsed) {
  return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
}

// One **refusal's** body, read as far as it can be read.
//
// A refusal that carries no condition this page can read is still a refusal the gateway
// answered, and the caller's job is to classify it — `act`'s rule, which round 6 brought
// to a park's answer: "a refusal whose condition this page cannot read is a refusal it
// cannot classify, and ADR-0139 §4's third outcome is what an unclassifiable one is". So
// a body that will not parse arrives as an unnamed condition rather than as an exception,
// and the caller decides what an unnamed one means.
//
// **This is not the rule for a body the gateway answered `2xx` with**, and conflating
// the two was adversarial review's round-8 blocker: see `relay`.
async function readBody(response) {
  try {
    return asObject(await response.json());
  } catch (_) {
    return {};
  }
}

// What a refusal or a fault means, in the owner's words. Each one is its own
// condition rather than a flattened "something went wrong" — ADR-0168 §6 requires
// the cookie-half fault "reported to the owner as its own condition, and never
// flattened into an expiry, a ceiling refusal or an ordinary absent session", and
// ADR-0168 §9 requires a transport failure distinguishable from a request the hub
// received and declined.
//
// The same vocabulary serves a fault that arrived as a response and one that
// arrived as a stream's terminal value, because the gateway writes the same names
// on both — so §9's distinction survives to what the owner reads rather than
// stopping at a status code a stream cannot revise.
const FAULTS = {
  // The remedy is no longer here: under ADR-0182 §1 a value is printed at start **and**
  // whenever the owner mints one, so "the value the gateway printed" had become the
  // wrong half of a sentence — and §6 gives re-entry its own words, which say what to
  // do. This states the condition and stops.
  "no-live-session": "This browser has no live session.",
  // The same treatment, and it was owed twice over (#1471). This named a cause the
  // gateway had not established — "another local service replaced this gateway's
  // cookie" — when what it compared was two values: `admit` takes this branch for any
  // cookie count but exactly one, so a browser that dropped a session cookie when it
  // closed arrives here by precisely the path a second local service does. The
  // milestone-16 QA reached it the ordinary way and was told to go looking for an
  // intruder.
  //
  // And it carried the stale remedy on top: a restart, which ADR-0182 §1 replaced with
  // a mint the owner performs at the running process. None is restated in its place,
  // for the entry above's reason — §6 gives re-entry its own words, and the bootstrap
  // panel this is appended to already says where a fresh value comes from. So this
  // states the condition, which is the whole of what the gateway learned, and stops.
  "cookie-half-mismatch": "The two halves of this browser's session no longer match.",
  "session-ceiling": "The gateway is holding as many sessions as it admits.",
  "bootstrap-exchange-failed": "That did not start a session.",
  // ADR-0174 §4, and the one refusal on this page whose remedy no status code hints at
  // (#1438). The assets are served to **any** device of the overlay — §4 keeps them
  // above the device check deliberately, because "an overlay member obtains nothing
  // from them they could not obtain from the distribution" — so the page loads, looks
  // right, and refuses at the moment `Start` is pressed. Without a sentence here that
  // arrived as "the gateway refused that request (HTTP 403)", from which nobody guesses
  // that the answer is a setting on another machine.
  //
  // The setting is named because naming it is the whole remedy, and the last sentence
  // is §4's own: the exchange is refused "without the value being read, compared or
  // consumed", so unlike a failed exchange this one has not spent anything.
  "device-not-listed":
    "This device may not start a session at this gateway. Add its overlay identity to " +
    "gateway_remote_browser_devices, on the machine the gateway runs on, and start the " +
    "gateway again. The value you pasted was not read, so it is still good.",
  "hub-unreachable":
    "The hub is not reachable, so nothing was asked. This is the gateway " +
    "reporting a transport failure — it is not an answer, and nothing was queued.",
  "assistant-declined": "The hub received the request and declined it.",
  "delivery-failed":
    "The gateway could not complete its notification poll, so it stopped watching. " +
    "This is neither the hub being unreachable nor a request it declined — it is a " +
    "third condition, and it is said as one. Start watching again to retry.",
  "delivery-budget-declined":
    "The hub declined the poll's budget: gateway_notification_budget is above the " +
    "hub's own hub_max_notification_budget. Nothing is retried; lower one figure or " +
    "raise the other.",
  "hub-connection-ceiling":
    "The gateway is already holding as many connections to the hub as it may " +
    "(gateway_max_hub_connections), so this request was refused rather than queued. " +
    "A delivery stream holds one of them for as long as it is open.",
  "request-too-large": "That request was larger than the gateway will read.",
  "no-such-conversation": "There is no conversation of that name.",
  "no-such-belief":
    "No live belief has that id. It may never have existed, or it may have been " +
    "revised or forgotten already — this surface shows and destroys only beliefs " +
    "held right now.",
  "malformed-request":
    "The gateway could not read that request. The page and the gateway ship in one " +
    "distribution, so this means the two halves disagree.",
  // ADR-0200 §9. Its own condition rather than `malformed-request`, because the two
  // say different things: that one means the page and the gateway disagree about the
  // *shape*, and this one means the recording itself is not something the surface can
  // carry. **The gateway's `detail` says which**, and it is the gateway's own sentence
  // rather than the validator's — a pydantic error carries the value it rejected
  // whatever its message says, and §9 forbids a refused recording travelling inside
  // its own refusal.
  "recording-unusable": "That recording is not one the assistant can take.",
  // ADR-0205 §7, on `recording-unusable`'s reasoning exactly: its own condition
  // rather than `malformed-request`, because a well-shaped report whose two
  // durations do not satisfy §2's partition is not the page and the gateway
  // disagreeing about the shape. It is this page's own measurement, and the sentence
  // says so — nothing the owner did is wrong, and the answer they just asked for did
  // not run.
  "delivery-unusable":
    "The page's account of how much of the last answer was played out was not one " +
    "the gateway would carry, so nothing was asked. Press and speak again.",
  // ADR-0200 §4. A transcription failure **fails** the call where a synthesis failure
  // degrades it — "the line is whether an answer exists yet" — so this is a fault and
  // "answer shown, not spoken" is not.
  //
  // **The classification reaches the owner as words, in the `detail`.** §4 puts a
  // `SpeechFailure` on the error precisely because the seam's own exception does not
  // cross, and the gateway writes this project's own sentence for the member it
  // carries; `describe` appends it to this one. So a deadline and an unclassified
  // failure read differently here without this page holding a second copy of either
  // sentence — which is the drift a per-member table in the front end would be.
  "transcription-failed": "That recording was not turned into words, so nothing was asked.",
  rejected: "The hub refused that as badly formed, so nothing was written.",
  // The connection surface's own conditions (ADR-0177 §3, ADR-0151 §7). They are here
  // as well as in `CONNECTION_CONDITIONS` because the two answer different questions
  // and both have to be answerable: this vocabulary is what a **read** shows when it
  // could not be taken, and that one is what an **act** shows about what it did. A
  // condition missing here rendered as "the gateway refused that request (HTTP 403)",
  // which is the flattening ADR-0177 §3 forbids arriving one layer out.
  "connections-need-a-local-hub":
    "Connections are managed on the machine the hub is on. This gateway reaches its " +
    "hub over the network, and a credential does not cross that hop (ADR-0151 §13), " +
    "so none of the connection surface is served here.",
  "credential-entry-loopback-only":
    "Entering a credential is available on the gateway's own machine only, because " +
    "your browser cannot protect a secret typed into a page it does not consider " +
    "secure. Disconnecting and reading the lists work here.",
  "credential-unusable": "That credential cannot be used, so nothing was sent.",
  "identity-unusable": "That account name cannot be used.",
  "no-such-connection": "There is no connection under that reference.",
  "provisioning-displaced": "Another act took that connection record over.",
  "provisioning-incomplete": "A connection act did not complete.",
  "provisioning-outcome-unknown": "The outcome of a connection act is not known.",
  "connection-store-unread":
    "The connection store could not be read or written, so this says nothing about " +
    "what is connected — not that nothing is.",
  "residual-credential":
    "The act completed and a credential it was to delete did not go, so an " +
    "unreferenced credential remains.",
};

// A stream whose body ended without a terminal value (ADR-0175 §2). Not a fault the
// gateway named — it is the connection itself going away, which is exactly what §2
// makes the front end report as a transport failure.
//
// **Two of them, because they end two different things.** One message served both
// while the delivery stream was the second reader of one wording, and it told an owner
// whose notifications had stopped that "the connection carrying that answer" had gone.
// The condition is the same; what was cut is not.
const ANSWER_STREAM_CUT =
  "The connection carrying that answer ended before the gateway finished it. What had " +
  "been written is not the answer and was not kept, so it has been cleared rather " +
  "than left on screen looking like one. A cut stream is asked again, not resumed.";

// A delivery stream this page abandoned because it went quiet, which is an ending the
// gateway did not name and could not: the whole condition is that nothing arrived
// (#1442). It is stated as what it is rather than folded into the cut above — a body
// that ended is the connection going away, and a body that is still open and silent is
// not, however alike they look from the panel.
const DELIVERY_STREAM_SILENT =
  "The connection carrying notifications stopped saying anything, so this browser " +
  "abandoned it and stopped watching. The gateway writes on an open delivery stream " +
  "at least once per gateway_notification_budget even when it has nothing to deliver, " +
  "so a stream silent for several of those is one something has happened to rather " +
  "than a quiet assistant. Nothing the hub still holds was lost: it is polled only " +
  "while a browser is watching. Start watching again.";

// The same ending, in the line that carries the control back. Written from the
// multiple rather than around it, so the number in the sentence cannot drift from the
// number the deadline is armed with.
const WENT_SILENT =
  `Nothing arrived on that stream — not even the gateway's keep-alive — for ` +
  `${SILENT_CADENCES} times the keep-alive cadence this gateway stated when it opened ` +
  `the stream, so it was abandoned.`;

// A delivery stream this page abandoned before it ever had one: the request went out
// and nothing came back at all, not even the head (#1474). Stated apart from the
// silence above because the evidence behind the two is different — a stream that went
// quiet broke a cadence the gateway had stated in its own head, and this one broke
// nothing the gateway ever said, because nothing arrived to say it in. Folding them
// into one sentence would tell an owner the gateway had promised something it had not.
const DELIVERY_STREAM_STALLED =
  "The request for notifications went out and nothing came back at all — not even the " +
  "head of the stream — so this browser abandoned it and stopped watching. That is a " +
  "request that was sent and never answered rather than a gateway that refused, and " +
  "the gateway may be perfectly alive at the other end of it: what this browser can " +
  "say is that nothing arrived. Nothing the hub still holds was lost: it is polled " +
  "only while a browser is watching. Start watching again.";

// The same ending, in the line that carries the control back. Written from the figure
// rather than around it, exactly as WENT_SILENT is, so the number in the sentence
// cannot drift from the number the deadline is armed with.
const NO_HEAD =
  `That stream was never opened: nothing answered the request for ` +
  `${HEAD_DEADLINE_MILLISECONDS / 1000} seconds, so it was abandoned.`;

const DELIVERY_STREAM_CUT =
  "The connection carrying notifications ended before the gateway finished it, so " +
  "this browser has stopped watching. Nothing the hub still holds was lost: it is " +
  "polled only while a browser is watching, so nothing was taken out of its outbox " +
  "while nothing here was listening. Start watching again.";

// **The gateway is where a session lives, so the gateway stopping is where it ends**
// (ADR-0168 §4: minted at the gateway, held in memory, and dies with the process).
// This is the sentence for the surprise rather than a restatement of the mechanism:
// nothing is wrong with the browser, nothing is recoverable, and the way back is a
// fresh bootstrap value.
const GATEWAY_GONE =
  "The gateway did not answer, so it may have stopped. " +
  "Every session ends with the gateway: a session is held in that process's memory " +
  "and written down nowhere, so a gateway that starts again has no memory of this one. " +
  "Start the gateway, then start a session with the value it prints.";

// Why a delivery stream can end in `no-live-session` when nothing was refused and the
// owner did nothing — the one condition on this page that nobody guesses right.
//
// An open stream is **not** use of the session that admitted it:
// `gateway_session_idle_timeout` "is refreshed by a request the gateway admits and by
// nothing else — not by a stream's continued existence, not by a value the gateway
// writes on one, and not by a delivery poll" (ADR-0175 §7). So a page left open and
// watching, asked nothing for an hour, expires exactly on time, and the stream ends
// with the session that held it (§7's fourth clause).
const IDLE_WHILE_WATCHING =
  "Watching does not keep a session alive. A session ends an hour after the last " +
  "thing you asked (gateway_session_idle_timeout), and a stream carries no request, " +
  "so a page left watching and asked nothing expires on time.";

function describe(body, status) {
  const known = FAULTS[body.fault];
  const detail = typeof body.detail === "string" && body.detail ? ` ${body.detail}` : "";
  if (known) {
    return known + detail;
  }
  return `The gateway refused that request (HTTP ${status}).`;
}

// The same, for a value that ended a **delivery** stream. The extra sentence is on
// this ending alone and deliberately: an answer stream's own request refreshed the
// idle timeout on its way in, so `no-live-session` there is not the hour passing and
// saying it was would be a wrong explanation rather than a missing one.
function describeDeliveryEnd(value, status) {
  const said = describe(value, status);
  return value.fault === "no-live-session" ? `${said} ${IDLE_WHILE_WATCHING}` : said;
}

// One condition, reported where the act that raised it is.
//
// **A condition that ended the session is re-entry and takes that path instead**, and
// no fault is written for it at all (ADR-0182 §6). `sessionLost` has just hidden every
// other panel, so writing it into the panel the act belonged to would put the reason
// behind `hidden` — ADR-0168 §9's distinction arriving as silence at the last hop —
// and writing it into the bootstrap panel's fault slot, which is what this did before
// §6 was ratified, puts a legitimate ending in the surface kept for things that went
// wrong. The message goes with it either way; only the slot changes.
function report(panelId, body, message) {
  if (sessionLost(body, message)) {
    return;
  }
  fault(message, panelId);
}

function refused(panelId, body, status) {
  report(panelId, body, describe(body, status));
}

// A refusal that means the conversation **this view is holding** is gone. The
// conversation half of `sessionLost`, and it exists for the same reason: forgetting
// the value is the only thing a page can do about it.
//
// **It is the cost of keeping the selection across a reload, and it has to be paid
// here.** A thread destroyed from a terminal or from another tab used to cost this
// page nothing, because a reload dropped the id; now the id comes back, is re-sent on
// every question, and is refused every time — with no control on screen to clear it,
// because the conversations listing cannot offer "Continue" for a conversation that is
// not in it. Adversarial review found it on round 3 and it is a real regression rather
// than a pre-existing edge.
//
// **`sent` is what the request actually carried**, and the comparison is what keeps
// this narrow: forgetting some *other* conversation from the listing and being told it
// was already gone says nothing about the one this view is reading, and must not clear
// it.
function conversationLost(body, sent) {
  if (body.fault === "no-such-conversation" && conversationId !== null && sent === conversationId) {
    changeConversation(null);
  }
}

// Read one `application/x-ndjson` body: one JSON object per line, each carrying the
// `kind` that says what it is (ADR-0175 §2). A reader resolves a value's kind from
// that member and never by inspecting what the value contains, so nothing below
// guesses from a payload's shape.
async function* streamValues(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const step = await reader.read();
    if (step.done) {
      return;
    }
    buffer += decoder.decode(step.value, { stream: true });
    for (;;) {
      const newline = buffer.indexOf("\n");
      if (newline < 0) {
        break;
      }
      const framed = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      if (framed) {
        yield JSON.parse(framed);
      }
    }
  }
}

function renderOutcome(outcome, chosenAt, provenance) {
  const body = el("answer-body");
  clearNode(body);
  // The other container a park row is rendered into, pruned where it is replaced for
  // `readPending`'s reason: a turn that parks leaves a row here, and the next answer
  // detaches it.
  refreshParks();
  // **What the caller knows about where this outcome came from, and nothing this
  // function inferred** (#1621). One caller has such a fact: `answerConfirmation`, when
  // it re-answers a park whose earlier answer this page never read back, where what
  // comes back may be the answer already recorded rather than the one just sent
  // (ADR-0198 §§1-2). It is written first because it qualifies everything below it, and
  // it is passed rather than derived because deriving it would mean reading a
  // restatement off the members the outcome does *not* carry — the inference from
  // absence ADR-0139 §4 refuses. `ask` and `askStreaming` pass none and get none.
  if (provenance) {
    line(body, provenance, "notice");
  }
  if (outcome.capture_degraded) {
    line(body, "This turn was not recorded, so it will not be part of this conversation.", "notice");
  }
  if (outcome.memory_degraded) {
    line(body, "Personal memory was unavailable, so this answer is generic.", "notice");
  }
  renderReply(body, outcome);
  if (outcome.rationale) {
    line(body, outcome.rationale, "rationale");
  }
  // **A plan with no steps, and not merely a turn with no plan.** `steps` comes from
  // the plan, and a resume driven from a **recovered** park carries `turn` `null`
  // (ADR-0052 §3) — so it has no plan, no steps, and nothing here that says the turn
  // planned nothing. Saying "no action was needed" above "Done. `smtp` ran." is a
  // contradiction on one screen, and the browser only started meeting it when
  // `resume` reached this page (#1404). `step` being present is the deterministic
  // account that a step was driven, which is exactly ADR-0170 §6's reason to trust it
  // over anything inferred.
  if (outcome.steps.length === 0 && outcome.step === null && outcome.routed === null) {
    line(body, "No action was needed.", "notice");
  }
  const list = document.createElement("ol");
  outcome.steps.forEach((step) => {
    const item = document.createElement("li");
    item.textContent = `${step.intent} (${step.capability})`;
    list.appendChild(item);
  });
  body.appendChild(list);
  renderStep(body, outcome.step);
  // ADR-0197 §8 makes `routed` and `step` mutually exclusive and gives a routed pass
  // no turn, so nothing above this line rendered anything for one — no plan, no
  // steps, no step account. The routed account is the whole of what a routed pass
  // deterministically did, and it goes **below** the reply and never in place of it
  // (§10). A page that read `steps.length === 0` as "no action was needed" would say
  // exactly that over a turn that had just destroyed a belief, which is why the
  // notice above is guarded on `step === null` **and** on there being no route.
  renderRouted(body, outcome.routed);
  // `null` only where nothing could be resolved (a recovered park, a deleted
  // conversation), and the last known id is then kept rather than cleared: the
  // hub decides which conversation a turn ran under, and forgetting one on an
  // answer that names none would silently start a new one on the next question.
  // `chose === chosenAt` is the owner not having chosen since this turn was sent.
  // Where they have, the hub's answer is still rendered whole — it is only the
  // *selection* that is not moved, because moving it would undo an act the owner took
  // after asking.
  if (outcome.conversation_id && chose === chosenAt) {
    setConversation(outcome.conversation_id);
  }
  show("answer", true);
}

// The composed answer, or a statement that composing one failed (ADR-0170 §6).
//
// **Beside the step account, never instead of it.** Everything `renderOutcome`
// rendered before this function existed is still rendered below it — the plan, the
// disposition line, the named step's status and failure. The account is what the
// system guarantees about what it did and the answer is not, so a model that
// claims it sent the email is contradicted on the same screen by a line saying no
// tool was available.
//
// **A degraded turn is a statement and never silence** (ADR-0170 §6). A turn that
// sent an email and could not then describe it still says the email was sent; the
// only thing missing is the prose that was going to sit above it, and saying so is
// what lets the owner tell that apart from a turn that owed no answer.
//
// **All four of ADR-0173 §6's shapes are read from the two members, and the fourth
// is the one this surface would otherwise lose** (ADR-0175 §3). An answer owed and
// *partly* produced carries `reply` set **and** `reply_degraded` true, and the
// natural rendering of a stream — show the chunks, then stop — displays it
// identically to a complete answer. So the partial text is rendered *and* said to be
// incomplete: never as a whole answer, and never as a silent turn.
//
// A `null` reply with the flag unset is one of ADR-0170 §4's other two shapes — a
// parked confirmation, whose question `renderStep` renders instead, or a resume
// driven from a recovered park, which persisted nothing to compose from. Neither
// writes anything here: this renderer has no text of its own to put in an answer's
// place, and inventing one would be prose about a turn nobody composed for.
//
// The answer is model output, so it goes in as text through `line`, exactly as the
// rationale and every other hub value on this page does (ADR-0168 §6).
function renderReply(body, outcome) {
  if (outcome.reply) {
    line(body, outcome.reply, "reply");
  }
  if (!outcome.reply_degraded) {
    return;
  }
  if (outcome.reply) {
    line(
      body,
      "That answer is incomplete: composing it stopped part-way, so what is above " +
        "is only what had been written. The record below is complete.",
      "notice"
    );
    return;
  }
  line(
    body,
    "No answer could be composed for this turn, so what follows is the record " +
      "of what was done and nothing more.",
    "notice"
  );
}

// Only `succeeded` is success, and taking the rule that way round is the
// load-bearing half — the CLI's `_render_step` learned it as issue #531, and a
// renderer written as "not failed means done" reproduces it one status over.
function renderStep(body, step) {
  if (step === null) {
    return;
  }
  // A park is rendered as the parked action, never as a boolean saying one happened
  // (#1404). ADR-0177 §8 makes this page a place a confirmation can be **answered**,
  // and ADR-0178 §7 states what has to be on screen before the answer is collected —
  // so what used to be a line telling the owner to go and find a terminal is now the
  // question itself, put here.
  if (step.confirmation !== null) {
    line(body, "This step is parked until you answer it.", "notice");
    renderConfirmation(body, step.confirmation);
    return;
  }
  const tool = step.tool_id || "the selected tool";
  if (step.disposition !== "executed") {
    line(body, `The permission gate returned '${step.disposition}' for ${tool}.`, "notice");
    return;
  }
  if (step.status === "succeeded") {
    line(body, `Done. ${tool} ran.`);
    return;
  }
  if (step.status === null) {
    line(body, "The step's own execution record could not be found.", "failed");
    return;
  }
  const because = step.failure ? ` ${step.failure.message}` : "";
  const kind = step.failure && step.failure.kind ? ` (${step.failure.kind})` : "";
  line(body, `${tool} is '${step.status}'.${because}${kind}`, "failed");
}

// --- the CONFIRM prompt (ADR-0177 §8, ADR-0178 §7) ---------------------------
//
// **Everything below renders; nothing below derives.** The canonical destination set
// is the one `core` computed, read from the view the gateway built in its own Python
// process (ADR-0178 §3) — this file never deduplicates destinations, never orders
// them, never substitutes the account for an empty set, and never builds a set out of
// the occurrences beside it. A deduplication, an account substitution and a
// code-point order reimplemented here would be business logic in an adapter (golden
// rule 3) and a second derivation of one fact, and a page that got any of the three
// wrong would show a recipient set the ruling was not taken over.
//
// **The approval control is built last, after the whole floor is on screen**, which
// is §7's "before it collects the user's answer" read as an ordering obligation on
// this renderer and not only as a wording one.
//
// **The token is relayed and never rendered** (ADR-0177 §8). It reaches
// `answerConfirmation` through a closure, so it is in no text node, no attribute and
// no browser storage; this page parses no part of it and derives nothing from it.

function renderConfirmation(parent, confirmation) {
  const item = document.createElement("div");
  item.className = "confirmation-row";
  line(item, `${confirmation.tool_id} — ${confirmation.tool_description}`, "reply");
  renderParameters(item, confirmation.parameters);
  // `egress` absent is ADR-0178 §4's discriminator, and all it states is that the
  // ruling was taken over no egress binding. So this branch renders the four other
  // members and says **nothing** about recipients — not that there are none, and not
  // that the call transmits nothing. Neither is a fact this page was given.
  if (confirmation.egress !== null) {
    renderEgress(item, confirmation.egress);
  }
  line(item, `Why you are being asked: ${confirmation.reason}`, "notice");
  offerApproval(item, confirmation.token);
  parent.appendChild(item);
}

// Every argument the call would run with — every key and every value, none omitted
// and none truncated (ADR-0177 §8).
//
// **These are the arguments and they are not the canonical destination set** (§8's
// surviving sub-clauses). A flat `to` among them is what the model produced before
// binding, so it is presented under a heading that says so; the bound set, where
// there is one, is rendered separately below by `renderEgress` and is the only thing
// on this page called a destination.
//
// The values arrive already spelled as text by the gateway, losslessly — a JSON
// number read by `JSON.parse` would be a double, and an integer argument above 2**53
// would reach the owner changed.
function renderParameters(item, parameters) {
  if (parameters.length === 0) {
    line(item, "It would run with no arguments.", "hint");
    return;
  }
  line(item, "It would run with these arguments, as the assistant wrote them:", "hint");
  parameters.forEach((one) => line(item, `${one.key} = ${one.value}`, "hint"));
}

// ADR-0148 §8's fourth clause, before the answer is collected: the connected
// account's identity, the canonical destination set in both forms, and the payload
// description.
//
// The set **and** the occurrences are both shown, which is not redundancy: the set is
// what the policy ruled over and is deduplicated, so it says how many people this is
// going to; the occurrences are ADR-0150 §10's third clause, so one recipient named by
// `to` and again by `bcc` is one member of the set and two disclosures here.
function renderEgress(item, egress) {
  line(item, `From the connected account: ${egress.account_identity}`, "hint");
  line(item, `Planned over: ${originWords(egress.planned_with_external_content)}`, "hint");
  line(item, "It would reach:", "hint");
  egress.destinations.forEach((one) => line(item, destinationWords(one), "hint"));
  line(item, "What it describes sending:", "hint");
  if (egress.spans.length === 0) {
    line(item, "the payload description names no span", "hint");
  }
  egress.spans.forEach((one) => line(item, spanWords(one), "hint"));
}

// The call's origin, at the strength the recorded predicate carries (ADR-0181 §6).
//
// **A property of the call, never of a span.** The boolean records whether the material
// this system *selected* into the model call that produced this request included any
// record marked as resting on recorded external content. ADR-0181 §2's third clause
// refuses to mint a per-span marker, so neither arm names an argument, a position, a
// destination or a payload span, and the line is rendered beside the occurrences rather
// than against one.
//
// **Neither arm names a source, or a kind of source** — §6's second clause bars "from a
// source you connected" in terms, because ADR-0098 §1's class is wider than connected
// sources, reaching a tool or MCP result, a provider's error text and a third party's
// speech captured by a spoke.
//
// **The `false` arm is not an assurance.** It says no selected record carried the
// marker, never that no external content was involved (§6's third clause; §7 names the
// residual it does not close). Each arm is a whole sentence rather than a "yes"/"no"
// against the other's wording, because a reader in one state never sees the other.
//
// **There is no third arm to render.** `ConfirmationEgress.planned_with_external_content`
// is required with no default (ADR-0181 §3), and the process that serialised this view
// is the one that served this script, so the key is always present and always a boolean.
// An "unknown" arm would be inventing a state the model cannot hold, at the surface
// where the owner is being asked to approve something.
function originWords(plannedWithExternalContent) {
  if (plannedWithExternalContent) {
    return (
      "material this assistant selected, which includes a record marked as " +
      "resting on recorded external content"
    );
  }
  return (
    "material this assistant selected, in which no record is marked as " +
    "resting on recorded external content"
  );
}

// One member of the set `core` derived, in the two shapes it has and no third.
//
// **The account arm is named as a destination rather than as an absence** (ADR-0178
// §7): where the spans carry no destination the set is the connected account, which is
// ADR-0148 §2's third clause, and a page showing "no recipients" there would be
// telling the owner the opposite of what the ruling was taken over.
function destinationWords(member) {
  if (member.account_identity !== null) {
    return `the connected account ${member.account_identity}`;
  }
  return `${member.canonical} (${member.protocol})`;
}

// One occurrence of the payload description, whole.
//
// **A description, never the payload.** A span states an argument, a position, a
// provenance, an extent and sometimes a tier; it holds no content, so nothing here
// presents an extent as the text or a provenance as an assertion about what the text
// says.
//
// **Both forms where the occurrence carries a destination, and neither invented where
// it does not.** A destination-less span is rendered as the payload-description span
// it is and names no recipient; dropping it, or rendering it as though it named one,
// would fail the whole-rendering clause in the two opposite directions.
function spanWords(span) {
  const where = span.index === null ? span.argument : `${span.argument}[${span.index}]`;
  const facts = [disclosureWords(span.provenance), `${span.extent} code points`];
  if (span.tier !== null) {
    facts.push(`tier ${span.tier}`);
  }
  const head =
    span.destination === null
      ? "names no destination"
      : `to ${span.destination.canonical} (${span.destination.protocol}), ` +
        `as supplied: ${span.destination.supplied}`;
  return `${where} — ${head}; ${facts.join("; ")}`;
}

// Who disclosed one span, in words (ADR-0146 §1). It says **who**, and nothing about
// what the value holds: ADR-0178 §7 forbids presenting a `system_selected` marker as
// an assertion about what the text says, and ADR-0146 §2 makes provenance carried
// rather than derived. A member this page has no words for is shown as the value it
// is, which is `bandWords`' own arrangement one surface over.
function disclosureWords(provenance) {
  if (provenance === "user_authored") {
    return "you composed it";
  }
  if (provenance === "system_selected") {
    return "this system selected it";
  }
  return provenance;
}

// --- the four arms this page had no panel for (ADR-0197 §10) ------------------
//
// **They render here because §10 is unqualified.** ADR-0177 §1's enumeration has
// never admitted `recent_reads`, `recent_invocations`, `recent_decisions` or
// `spend_totals` to a *browser request*, and ADR-0186 §6 and §10 keep it that way —
// but that bar is on the **route** and not on the rendering. A routed pass makes no
// browser request for any of them: the hub decided the route (ADR-0197 §12), and
// what reaches this page is a result it must render or misreport. An earlier shape
// of this lane named the CLI instead, and adversarial review blocked it correctly.
//
// **Each of the four owes what its own decision already obliges of every surface
// that renders it**, inherited rather than invented, and the wording is the CLI's
// because the two render the same record: ADR-0186 §7's enumeration and §8's bars
// for a ruling and a read, ADR-0192 §4's two-rows rule for an act, ADR-0194 §5 and
// §6 for a total. Where the CLI's own renderer says something, this says it in the
// same words, so the two surfaces cannot drift into two vocabularies for one fact.
//
// **None of it is a panel.** No control appears on a row (ADR-0186 §8's last
// clause), nothing here is offered as something to answer or revoke, and no path
// resolves to any of the four operations. A browser panel for them is the later
// consumer lane ADR-0186 §6 names, and is #1642.

// How a read attempt ended, and what that states about opening — the pair
// `interfaces/cli._read_ending` returns, in the same words (ADR-0185 §1).
const READ_ENDINGS = {
  completed: ["completed", "opened, and the grant still stood at the re-check"],
  refused: ["refused", "not opened: you allowed no live grant for it"],
  unanswered: ["unanswered", "not opened: I could not find out whether you allowed it"],
  failed: ["failed", "the read raised; whether it was opened is not recorded"],
  discarded: [
    "discarded",
    "opened, then the grant was gone at the re-check, so the reading was dropped whole",
  ],
  unconfirmed: [
    "unconfirmed",
    "opened, then the re-check could not be answered, so the reading was dropped whole",
  ],
};

// Which grant an attempt cited, or why it cited none. **It is not looked up now**
// (ADR-0186 §8's first clause): the row says what the attempt cited then, and this
// page derives no liveness, no scope and no grant history from it.
function readGrantWords(record) {
  if (record.grant !== null) {
    return `${record.grant} (what the attempt cited then; it is not looked up now)`;
  }
  if (record.outcome === "unanswered") {
    return "none cited — the check did not answer, so whether you allowed it is unknown";
  }
  return "none — you had allowed no live grant when I checked";
}

// One recorded read attempt, whole (ADR-0185 §2, ADR-0186 §7).
//
// All seven fields, none summarised. **`produced` is a count and is labelled as
// one**: the record holds no content, no entry and no path, so a line reading "what
// it said" would be reaching for something ADR-0004 §5 forbids being written down.
function renderReadFields(item, record) {
  const ending = READ_ENDINGS[record.outcome] || [record.outcome, ""];
  line(item, `${ending[0]} — ${record.checked_at}`, "reply");
  if (ending[1]) {
    line(item, ending[1], "hint");
  }
  line(item, `Source: ${record.source} (as the reader declares it)`, "hint");
  line(item, `Read for: ${usePhrase([record.use])}`, "hint");
  line(item, `Under grant: ${readGrantWords(record)}`, "hint");
  line(
    item,
    `Produced: ${record.produced} item(s) (a count of what the source returned, ` +
      "never the thing itself)",
    "hint"
  );
  line(item, `id: ${record.id}`, "hint");
}

// How an attempted call ended, and what that does and does not state — the pair
// `interfaces/cli._invocation_outcome` returns. The `succeeded` arm differs on an
// outbound call, because "attempted and reported success" is the whole of what this
// system observes of one (ADR-0192 §4).
function invocationEnding(outcome, egressCall) {
  if (outcome === "succeeded") {
    return egressCall
      ? "the tool reported success. This was an outbound call, and what that states " +
          "is that it was attempted and reported success — no more than that"
      : "the tool reported success";
  }
  if (outcome === "failed") {
    return "the tool reported that the call did not succeed";
  }
  if (outcome === "indeterminate") {
    return (
      "the tool could not say whether the call took effect, and I cannot resolve " +
      "that in either direction"
    );
  }
  return "";
}

// What a call cost, in the three states ADR-0195 gives it. **`free` and `not known`
// are different statements and neither is a number**, which is why the basis decides
// this line and the amount never does.
function costWords(cost) {
  if (cost.basis === "free") {
    return "free (the tool reported this invocation carried no charge)";
  }
  if (cost.basis === "unknown") {
    return (
      "not known (the tool reported no cost for this invocation; that is not the " +
      "same as free)"
    );
  }
  return `${cost.amount} ${cost.currency}`;
}

// One recorded act on an authorisation (ADR-0192 §4).
//
// **A claim and a completion are two rows and are said to be**, and nothing here
// pairs them or counts them as one. **Nothing names who or where an outbound call
// went**: `egress_call` says only whether the ruling this row names carried an
// outbound binding.
function renderInvocationFields(item, row) {
  const claim = row.completes === null;
  line(item, `${claim ? "call begun" : "call finished"} — ${row.recorded_at}`, "reply");
  line(
    item,
    claim
      ? "a claim: I spent an authorisation and attempted a call. It does not say the " +
          "tool itself was entered, and it says nothing about how the call ended"
      : "a completion: how an attempted call ended, written after it",
    "hint"
  );
  line(item, `Tool: ${row.tool} (capability ${row.capability})`, "hint");
  line(
    item,
    `Outbound call: ${row.egress_call ? "yes" : "no"} (whether the ruling this row ` +
      "names carried an outbound binding; who or where is not on this row)",
    "hint"
  );
  line(
    item,
    `Under authorisation: ${row.decision_id} (what it cited then; it is not looked up now)`,
    "hint"
  );
  if (row.outcome !== null) {
    line(item, `Ended: ${row.outcome} — ${invocationEnding(row.outcome, row.egress_call)}`, "hint");
    if (row.outcome !== "succeeded") {
      line(
        item,
        `Failure kind: ${row.failure_kind === null ? "none was reported — the record holds no kind for this one" : row.failure_kind}`,
        "hint"
      );
    }
    if (row.cost !== null) {
      line(item, `Cost: ${costWords(row.cost)}`, "hint");
    }
  }
  line(item, `id: ${row.id}`, "hint");
}

// What a ruling was — a verdict, and never an event (ADR-0186 §8's third clause).
function decisionWords(outcome) {
  if (outcome === "allow") {
    return "allowed";
  }
  if (outcome === "deny") {
    return "refused";
  }
  return "asked (a question put to you)";
}

// What authorised an `allow`, in exactly the three states ADR-0193 §11 names, read
// off the pair the row carries and off no field that pre-computes it (§6).
//
// **The second state says exactly what the row says and nothing more**: that this
// decision *names* a standing authorisation. It does not state that the named grant
// exists, is held, is live, is unrevoked or covers anything now — ADR-0186 §8's
// first clause, read on this fact.
//
// **A row whose pointers contradict each other never reaches here** — `unreadable`
// keeps it out of the listing entirely, which is what holds this function to §11's
// three states and stops a fourth being invented in the gap.
function authorisationWords(decision) {
  if (decision.authorised_by === null) {
    return "the policy's own rules, resting on no decision of yours";
  }
  if (decision.resolves === null) {
    return (
      "a standing authorisation this ruling names, recorded as " +
      `${decision.authorised_by} (what the row names, and no more)`
    );
  }
  // The pair having reached here at all means it matched, because a row whose
  // pointers differ never gets past `renderDecisionFields`' first branch. So this is
  // the third of ADR-0193 §11's three states and there is no fourth to fall through
  // to.
  return `a decision you took about this call, recorded as ${decision.authorised_by}`;
}

// The call's origin as the recorded predicate carries it, including the arm that
// carries none. **ADR-0184 §2's unrecorded arm states nothing either way**, and a
// renderer reading its absence as "no external content" would make a claim the
// record does not.
function recordedOriginWords(binding) {
  if (binding.origin_unrecorded) {
    return (
      "not recorded — this ruling was made before this assistant kept the origin of " +
      "a call, so the record states nothing either way about the material it selected"
    );
  }
  return originWords(binding.planned_with_external_content);
}

// The binding a ruling was taken over (ADR-0186 §7, ADR-0178 §7's facts).
//
// **The labels are what change from the card's** (ADR-0186 §8's third clause): a
// card says where a call is going because it has not gone; a row says what a ruling
// was taken over, because the trail bounds resolutions and no row knows whether
// anything ran. "Goes to" on a history row would be a transmission claim in two
// words.
//
// **Every span, none omitted, none reordered, none truncated** (§7's
// last-but-one clause), through the same `spanWords` and `destinationWords` the card
// uses — one vocabulary, so a history cannot render a disclosure the card did not.
function renderRecordedBinding(item, binding) {
  line(item, `Account: ${binding.account_identity}`, "hint");
  line(item, `Planned over: ${recordedOriginWords(binding)}`, "hint");
  line(item, "Ruled over these recipients:", "hint");
  binding.destinations.forEach((one) => line(item, destinationWords(one), "hint"));
  line(item, "Payload described as:", "hint");
  if (binding.spans.length === 0) {
    line(item, "the payload description names no span", "hint");
  }
  binding.spans.forEach((one) => line(item, spanWords(one), "hint"));
}

// One recorded ruling, whole (ADR-0186 §7).
//
// **What is deliberately absent is as load-bearing as what is here.** No `reads`,
// `writes` or `discloses` — they are ceilings rather than per-call measurements
// (§8's fifth clause) — nothing computes `authorises` (§8's second), and no answer,
// approve or deny control appears on a row (§8's last). **A liveness sentence is
// printed rather than assumed**, because the reader who most needs it is the one
// treating this as a permissions screen.
function renderDecisionFields(item, decision) {
  line(item, `${decisionWords(decision.outcome)} — ${decision.decided_at}`, "reply");
  line(item, `Tool: ${decision.tool_id} (capability ${decision.capability})`, "hint");
  line(item, `Why: ${decision.reason}`, "hint");
  line(item, `Digest: ${decision.parameters_digest} (a digest, never the arguments)`, "hint");
  if (decision.resolves !== null) {
    line(item, `Answers the question: ${decision.resolves}`, "hint");
  }
  if (decision.outcome === "allow") {
    line(item, `Authorised by: ${authorisationWords(decision)}`, "hint");
  }
  if (decision.binding !== null) {
    renderRecordedBinding(item, decision.binding);
  }
  line(item, `id: ${decision.id}`, "hint");
  line(
    item,
    "This is a ruling that was made. It does not say the ruling still stands, that a " +
      "grant is current, that an account is still connected, or that the tool is still " +
      "registered under the identifier above — and it does not say the call ever ran.",
    "hint"
  );
}

const PERIOD_NAMES = { calendar_day: "Today", calendar_month: "This month" };

// One period's total, in the states ADR-0194 §5 and §6 give it.
//
// **An absence is rendered as the state it is, and `currency` tells the two apart**:
// `currency` null means none is configured and no total was computed; a currency
// beside a null `accounted` means the period could not be measured. Collapsing them
// would tell an owner "no total" while their calls are being refused.
//
// **The consequence line is printed from that period's own ceiling and never from
// the absence of a total** — a renderer keying on a missing figure alone tells an
// owner their calls are blocked when they are not — and **nothing here reads
// falsiness of a ceiling**, because a configured ceiling of zero refuses the most.
function renderSpendFields(item, total) {
  line(item, PERIOD_NAMES[total.period] || total.period, "reply");
  // **Each bound arrives already rendered from its own offset** (ADR-0194 §6), and
  // the label beside it is that same offset. The arithmetic is the gateway's, in
  // Python, because §5 bars this bound from being read "from the client's zone" or
  // "through the client's `tzdata`" — and a browser shifting an instant is exactly
  // the code that would reach for one. An earlier shape of this page printed the UTC
  // instant beside the label, which is a bound in one offset labelled with another.
  line(item, `from ${total.period_start} ${total.start_offset}`, "hint");
  line(item, `up to (not including) ${total.period_end} ${total.end_offset}`, "hint");
  if (total.currency === null) {
    line(item, "No spend currency is configured, so I am not keeping a total.", "hint");
    return;
  }
  if (total.accounted === null) {
    line(
      item,
      `Not measurable. Something in this period has no price I may add — a call still ` +
        `in flight, or one whose cost nobody reported — so I will not state a ` +
        `${total.currency} figure I would be inventing.`,
      "notice"
    );
    line(
      item,
      total.ceiling === null
        ? "Nothing is being refused on that account: you have set no ceiling for this period."
        : `Nothing further will run in this period while that is so: there is a ceiling ` +
            `of ${total.ceiling} ${total.currency} here and I cannot tell whether a call ` +
            "would cross it.",
      total.ceiling === null ? "hint" : "failed"
    );
    return;
  }
  line(
    item,
    total.ceiling === null
      ? `${total.accounted} ${total.currency} — no ceiling set for this period.`
      : `${total.accounted} ${total.currency} of a ceiling of ${total.ceiling} ${total.currency}`,
    "reply"
  );
  line(
    item,
    "These are the prices my own tools reported for the calls I made. They are not a " +
      "bill, not an amount owed, and not checked against anyone's statement.",
    "hint"
  );
}

// --- the routed account (ADR-0197 §10) ---------------------------------------
//
// **Beside the reply, never instead of it, and never suppressed.** §10 is ADR-0170
// §6's rule and it binds here for its reason, sharpened: on a routed pass the
// composing stage was handed two enum values and nothing else (§6), so the worst
// prose it can produce is prose about the wrong thing, while the account beside it
// is typed data from the store that no prompt influenced. Where the two disagree the
// account is correct by construction, and nothing on this page resolves that
// disagreement in the reply's favour.
//
// **Everything below renders; nothing below derives** — `renderConfirmation`'s own
// rule, and ADR-0197 §12's last Normative names it for this lane: the gateway "makes
// no routing decision — the hub does". This file reads the arm off `operation` and
// never off the shape of the records, chooses no candidate, orders nothing, counts
// nothing and composes no argument.
//
// **Every value goes in through `line`, as a text node** (ADR-0168 §6, ADR-0042 §4).
// A belief's content is the user's own words and a grant's source is the identity a
// reader declared; neither may reach this page as markup.

// What the ask was routed to, in words. One entry per member of ADR-0197 §3's
// vocabulary — the whole of it, so a member added under §3's widening rule renders
// as an empty sentence here rather than as a raw enum value somewhere.
const ROUTED_ASKED = {
  questions: "list what is waiting on your answer",
  recent_reads: "list the attempts to read your sources",
  recent_invocations: "list what I did on an authorisation",
  recent_decisions: "list what the permission layer ruled",
  standing_grants: "list the sources you allow me to read",
  spend_totals: "report what the world has cost",
  forget: "forget one belief",
  revoke: "withdraw the grant on one source",
  forget_question: "forget one deferred question",
};

// What did **not** happen, for every ending that performed nothing. Phrased per
// operation because "nothing was done" is the sentence a reader cannot act on: what
// they need to know is that the belief is still held.
const ROUTED_UNDONE = {
  questions: "nothing was listed",
  recent_reads: "nothing was listed",
  recent_invocations: "nothing was listed",
  recent_decisions: "nothing was listed",
  standing_grants: "nothing was listed",
  spend_totals: "no total was reported",
  forget: "the belief is still held",
  revoke: "the grant still stands",
  forget_question: "the question is still there",
};

// What a confirm-owed operation did, once it has run. Reached only from `performed`,
// and only for the three members ADR-0197 §3 tags confirm-owed: a read-only
// `performed` has a listing to show and shows it.
const ROUTED_DONE = {
  forget: "Done. That belief is destroyed.",
  revoke: "Done. That grant is withdrawn — I may no longer read that source.",
  forget_question: "Done. That question is destroyed.",
};

// The sentences a routed confirm card carries around its subject.
//
// **Every word is this page's own, selected by the enum member** (ADR-0197 §7). No
// free text the router produced reaches the card — the query included — which is
// what lets a person trust it to describe the act rather than to describe how the
// act was asked for.
//
// A `forget` card takes its band-appropriate warning from `forgetWarning` in
// addition to these, because ADR-0073 §5's ceremony binds the routed `forget` whole
// (ADR-0197 §7's last clause) and the warning is the half of it that changes with
// the belief.
const ROUTED_CARD_NOTES = {
  forget: [
    "This destroys the record: nothing of it is kept, not even in an export. To fix " +
      "it instead, tell me it is wrong in a conversation.",
    "You are forgetting whatever belief that id names when you answer, which may " +
      "have changed since it was shown.",
  ],
  revoke: [
    "This stops me reading that source from now on. It destroys nothing I have " +
      "already learned from it, and you can grant it again.",
  ],
  forget_question: [
    "This destroys the record of having been asked. Nothing I believe changes, and " +
      "you can tell me the same thing again yourself.",
  ],
};

// Which of ADR-0197 §8's arms each operation lists, read off `operation` and never
// off the value's shape — §8 in terms, because "an empty tuple is a legal value of
// every arm, so the shape decides nothing on exactly the case a listing is most
// likely to take".
//
// **Total over the nine operations**, so §10's "the listing where one is carried"
// has a renderer for every listing that can arrive. A member added under ADR-0197
// §3's widening rule renders nothing here until it is added, which is why the
// omission is a missing key rather than a silent fallback.
const ROUTED_ARM = {
  questions: "question",
  forget_question: "question",
  forget: "belief",
  revoke: "grant",
  standing_grants: "grant",
  recent_reads: "read",
  recent_invocations: "invocation",
  recent_decisions: "decision",
  spend_totals: "spend",
};

// The renderer for each arm — the one this page uses for that record wherever it
// appears, so a routed listing and a panel cannot render one record two ways.
const ROUTED_ARM_RENDERERS = {
  belief: renderBeliefFields,
  question: renderQuestionFields,
  grant: renderGrantFields,
  read: renderReadFields,
  invocation: renderInvocationFields,
  decision: renderDecisionFields,
  spend: renderSpendFields,
};

// What became of the routed operation, in this page's own words. Total over
// ADR-0197 §8's eight members.
//
// **`unrecorded` and `failed` say opposite things and are worded to** (§8, and §12's
// discrimination clause, which requires a surface rendering the two alike to fail a
// test). `unrecorded` means the operation was never called and nothing was
// destroyed; `failed` means it was called and raised, and whether it took effect is
// not asserted.
//
// **`unrecorded` says to ask again and never to answer the card again** (§7): the
// park is already claimed by the time that ending is reached, so offering a retry
// would be offering a token that now raises.
//
// **`refused` is a ruling and not an error** (§7). No policy was consulted and no
// decision recorded, so there is nothing here for a refusal to be except the answer
// the owner gave, and it is worded as one.
function routedHeadline(routed) {
  const asked = ROUTED_ASKED[routed.operation] || routed.operation;
  const undone = ROUTED_UNDONE[routed.operation] || "nothing was done";
  if (routed.outcome === "performed") {
    return ROUTED_DONE[routed.operation] || `I read my own record for that — you asked me to ${asked}.`;
  }
  if (routed.outcome === "refused") {
    return `Not done. You said no, so ${undone}.`;
  }
  if (routed.outcome === "ambiguous") {
    return (
      `More than one thing matches that. I will not guess which you meant, so ` +
      `${undone}. Here is everything that matched — say which one, or use the ` +
      `command for it directly.`
    );
  }
  if (routed.outcome === "ambiguous_truncated") {
    return (
      `More than one thing matches that, and more than I can show. I will not guess ` +
      `which you meant, so ${undone}. Here are the matches I can show — narrow it ` +
      `down, or use the command for it directly.`
    );
  }
  if (routed.outcome === "not_found") {
    return `Nothing matches that. I found nothing to act on, so ${undone}.`;
  }
  if (routed.outcome === "unrecorded") {
    return (
      `Not attempted. I could not write the record that has to exist before I act, ` +
      `so I did not act: ${undone}. Nothing is waiting on you and there is nothing ` +
      `to retry — ask me again.`
    );
  }
  if (routed.outcome === "failed") {
    return `Failed. I tried to ${asked} and it raised. Whether it took effect is not something I can tell you.`;
  }
  // `awaiting_confirmation` renders as the card and reaches here only if a park
  // crossed with no confirmation, which `RoutedOperation`'s own validator forbids —
  // and a ninth member of `RouteOutcome` would land here too. Neither is rendered as
  // success: a sentence naming the value is the honest reading of "this page does not
  // know what that means".
  return `That request was routed to ${asked}, and this page cannot say what became of it.`;
}

// Which class the headline takes, so an ending that failed does not read like one
// that succeeded. `notice` is the page's own "something to know" and `failed` its
// "this did not work" — the two `renderStep` already uses one member over.
function routedClass(outcome) {
  if (outcome === "unrecorded" || outcome === "failed") {
    return "failed";
  }
  if (outcome === "performed") {
    return "reply";
  }
  return "notice";
}

function renderRouted(body, routed) {
  if (routed === null) {
    return;
  }
  // A park renders as the question and nothing else (ADR-0197 §10's third clause):
  // the composing stage is not reached on one, "for its own reason: the confirmation
  // is what the user must answer, and prose beside it competes with the question".
  if (routed.confirmation !== null) {
    renderOperationConfirmation(body, routed.confirmation);
    return;
  }
  line(body, routedHeadline(routed), routedClass(routed.outcome));
  if (routed.listing !== null) {
    renderRoutedListing(body, routed.operation, routed.listing);
  }
}

// A ruling that answers one decision while resting on another (ADR-0193 §11, and
// adversarial review's rounds 2 and 4).
//
// **It is not rendered, and it is not rendered in part.** ADR-0186 §7 is that "a
// surface that cannot render a row whole renders fewer rows, not partial ones", and
// §11 names exactly three authorisation states of which this pair is none. The trail
// refuses to record one, so a row reaching a reader with it is a value no store this
// system wrote would hold. `interfaces/cli._authorisation_line` raises and the whole
// listing ends there.
//
// **This drops the row rather than the answer, and says so.** Refusing the routed
// outcome through `_relay_fault` was the other way, and it was declined for a reason
// on this page rather than a preference: its two conditions are `hub-unreachable` and
// `assistant-declined`, and this page renders the second as "The hub received the
// request and declined it" — which would be false, since the hub answered. ADR-0168
// §9 requires those two to stay distinguishable and forbids presenting either as
// something it is not, and minting a third condition is a gateway-surface decision
// this consumer lane does not own. So the row goes, nothing of it is shown, and the
// listing states that it went — the one thing a dropped row must not be is silent.
const UNREADABLE_RULINGS =
  "Some rulings in this record could not be read and are not shown: a ruling that " +
  "answers one decision while resting on another is not one an audit trail accepts, " +
  "and nothing of what such a row says is shown in part. 'assistant export-decisions' " +
  "writes the record as it stands.";

// Whether a record is one this page will render at all. Nothing else is filtered:
// this is the single condition ADR-0186 §7 makes a row unrenderable, and every other
// record of every arm is rendered whole.
function unreadableRecord(record) {
  return record.unreadable === true;
}

// What an empty routed listing says, per operation (#1648).
//
// **A listing that carries no records is a state, and this page says which state it
// is.** ADR-0197 §10's first Normative is that an adapter renders the routed account
// "in addition to any composed reply, never instead of it, and never in place of
// it", and an empty `div` suppresses it in exactly the case a reader most needs it:
// the composed reply says the list is beside this message, so a reader who sees no
// list cannot tell "the record is empty" from "the page failed to render the
// record". Those two are materially different answers to the same question, and a
// blank is how a surface gives the wrong one silently.
//
// **Empty is the common state and not the edge.** Four of the six read-only members
// — `recent_reads`, `recent_invocations`, `recent_decisions` and `standing_grants` —
// are empty on a hub with no sources configured, and `questions` is empty on one
// with nothing deferred.
//
// **The words are the CLI's, because the two doors answer alike.** ADR-0197 §12's
// last Normative has each adapter render the routed account "with the renderer it
// already has for the operation", and `interfaces/cli._render_routed_listing` gets
// its empty-state prose for free by delegating to `_render_reads`, `_render_standing`
// and their siblings. This page renders each arm's *fields* through the renderer it
// already has (`ROUTED_ARM_RENDERERS`) but owns the listing frame itself, so the
// sentences those renderers carry are restated here rather than inherited.
//
// **The first line states it and the rest qualify it**, which is the CLI's own split
// between the sentence and the caveat below it: a bounded record that is empty is
// not a claim that nothing ever happened, and saying only the first half would be a
// stronger claim than the record supports.
//
// **Total over ADR-0197 §3's nine operations**, for `ROUTED_ARM`'s reason. The three
// confirm-owed members and `spend_totals` reach here only through a state their own
// decisions forbid — §5 reaches an ambiguity on more than one match, and
// `AssistantOperations.spend_totals` returns "both entries whatever is configured" —
// so each says the page cannot account for what it was handed. That is the honest
// reading of an impossible value, and it is still a sentence rather than a blank.
const ROUTED_EMPTY_UNEXPLAINED =
  "There is nothing here to show, and this page cannot say why: this answer carries " +
  "a listing, and an empty one is not a state the hub produces for what was asked.";

const ROUTED_EMPTY = {
  questions: ["Nothing is waiting on your answer."],
  recent_reads: [
    "Nothing recorded. No attempt to read a source is in this record.",
    "That is not a claim that nothing was ever read: this record states what it " +
      "holds, the oldest attempts are dropped as it fills, and a fault can leave a " +
      "read with no row.",
  ],
  recent_invocations: [
    "Nothing recorded. No act on an authorisation is in this record.",
    "That is not a claim that nothing was ever attempted: this record states what " +
      "it holds, and a fault can leave an act with fewer rows than it made.",
  ],
  recent_decisions: ["Nothing recorded. No ruling has been made yet."],
  standing_grants: [
    "You have not granted anything. I am allowed to read no source at all.",
    "'Sources you can connect me to' lists what is configured, and is where you " +
      "grant one.",
  ],
  spend_totals: [ROUTED_EMPTY_UNEXPLAINED],
  forget: [ROUTED_EMPTY_UNEXPLAINED],
  revoke: [ROUTED_EMPTY_UNEXPLAINED],
  forget_question: [ROUTED_EMPTY_UNEXPLAINED],
};

// The empty state for one operation, into the listing's own node so that what the
// account carries stays inside the account.
//
// **A member added under ADR-0197 §3's widening rule falls back to a sentence and
// never to silence.** `ROUTED_ARM`'s omission is deliberately a missing key, because
// a record rendered by the wrong renderer is worse than one not rendered at all.
// Here the opposite holds: the whole defect this fixes is a listing that said
// nothing, so the one thing a missing key must not produce is a blank.
function renderEmptyListing(list, operation) {
  const said = ROUTED_EMPTY[operation] || [ROUTED_EMPTY_UNEXPLAINED];
  said.forEach((text, index) => line(list, text, index === 0 ? "notice" : "hint"));
}

// Every record the listing carries, in the order it carries them.
//
// **Never fewer, and never a summary of them** (ADR-0197 §5's last clause, which is
// ADR-0186 §7's rule for a trail row applied to a candidate listing). A narrow
// screen gets a longer page, not a shorter list. The one row that is not rendered is
// the one §7 itself makes unrenderable, and the listing says when that happened.
//
// **A listing carrying no records is answered before the loop and never by it**
// (#1648). The two absences are different facts and are kept apart: an empty listing
// is a record with nothing in it, while a listing whose every row was dropped is a
// record with something in it this page may not show. Keying the empty state on the
// records rendered would collapse them and report the second as the first, telling a
// reader nothing was ever ruled on when the truth is that the rulings could not be
// read — so the zero test is on what arrived, and `UNREADABLE_RULINGS` stays the only
// thing said about what went.
function renderRoutedListing(body, operation, listing) {
  const list = document.createElement("div");
  list.className = "routed-listing";
  if (listing.length === 0) {
    renderEmptyListing(list, operation);
    body.appendChild(list);
    return;
  }
  let dropped = 0;
  listing.forEach((record) => {
    if (unreadableRecord(record)) {
      dropped += 1;
      return;
    }
    const item = document.createElement("div");
    item.className = "routed-row";
    renderRoutedRecord(item, operation, record);
    list.appendChild(item);
  });
  body.appendChild(list);
  if (dropped > 0) {
    line(body, UNREADABLE_RULINGS, "failed");
  }
}

// One record, rendered with the renderer this page already has for its arm — which
// is ADR-0197 §12's last Normative and the whole of why this is a consumer group.
function renderRoutedRecord(item, operation, record) {
  const render = ROUTED_ARM_RENDERERS[ROUTED_ARM[operation]];
  if (render) {
    render(item, record);
  }
}

// The routed confirm card (ADR-0197 §7).
//
// **This is not a `Confirmation` and is not rendered as one.** A routed act has no
// tool, no arguments and no policy ruling, so three of that type's four content
// members would have to be filled with something invented — the
// falsehood-in-durable-state failure ADR-0170 §3 refused, arriving in a value a
// person reads. What is on screen is what §7 says the card carries: the operation,
// and the resolved subject as a typed value.
//
// **The approval control is built last, after the whole card is on screen**, which
// is `renderConfirmation`'s own rule read here: §7's "before it collects the user's
// answer" is an ordering obligation on the renderer and not only a wording one.
//
// **The token is relayed and never rendered.** `offerApproval` takes it into a
// closure, so it is in no text node, no attribute and no browser storage — and it
// reaches the hub through the same `/confirmation/resume` request every other park
// is answered with, because ADR-0197 §7 answers a routed park through
// `AssistantEngine.resume` "and through no other method".
//
// **A routed park is not recoverable and this page does not offer to recover one**
// (§7): it is never listed by `pending_confirmations`, and it does not survive a
// restart. What a lost routed park costs is one repeated sentence — nothing has
// happened yet — so the note says to ask again rather than pointing at the recovery
// listing, which would point at something that will never hold it.
function renderOperationConfirmation(parent, card) {
  const item = document.createElement("div");
  item.className = "confirmation-row";
  line(item, `About to ${ROUTED_ASKED[card.operation] || card.operation}.`, "reply");
  card.subject.forEach((record) => renderRoutedRecord(item, card.operation, record));
  if (card.operation === "forget") {
    card.subject.forEach((record) => line(item, forgetWarning(record.band), "notice"));
  }
  (ROUTED_CARD_NOTES[card.operation] || []).forEach((note) => line(item, note, "notice"));
  line(
    item,
    "If this browser loses the answer, nothing will have happened — ask me again " +
      "rather than looking for this in Confirmations, which does not hold it.",
    "hint"
  );
  offerApproval(item, card.token);
  parent.appendChild(item);
}

// The answer, offered only once everything above it is on screen.
//
// Two buttons rather than a checkbox and a submit, because each is one act and the
// page never holds a half-made answer. `resume` is answered with `approved` and
// nothing else — the deadline is the gateway's (ADR-0177 §9) and no value from here
// reaches it.
// Said while an answer is out. **It does not promise a deadline**, because there is
// none here, and that is `ASKING`'s decision one surface over rather than a second one:
// ADR-0177 §9 gives `resume` "the same budget a turn is given at this surface" —
// `server.py`'s `_TURN_BUDGET` — and that figure reaches the browser in no header, in
// no value and in no setting. A page-side deadline would be a second number that can
// silently disagree with it, and one short enough to be useful would abandon a healthy
// resumed turn that was thinking and announce that its outcome was not known. So the
// page puts no clock on this request, says so, and puts the control beside the
// sentence.
const PARK_WAITING =
  "Sending that answer. This browser puts no deadline on it and cannot tell an answer " +
  "that is taking a while from one whose reply will never arrive, so stopping the wait " +
  "is yours to do.";

// What stopping that wait did, and — the whole of why it is long — what it did not
// (#1536).
//
// ADR-0177 §7's fourth clause is the rule: a failure of "the **browser's own** request
// to the gateway — the request was sent and no response was read — is an outcome that
// is **not known**, whatever the gateway did", and "no front end resolves it by
// assuming either of the other two". ADR-0139 §4 is the same prohibition in both
// directions, so a row that simply came back enabled would be announcing by omission
// that nothing happened.
//
// **And it names the act that settles it, which is where a park differs from an ask.**
// An abandoned ask has nowhere to look but the conversations listing; a park has
// `pending_confirmations`, which ADR-0084 §7 names as the remedy for exactly this — "The
// remedy is `pending_confirmations()`" — and ADR-0177 §8 makes this surface's one
// recovery route.
//
// **It is the owner's act and not this page's, which is ADR-0182 §7's fifth clause.**
// Nothing is re-sent here and nothing is offered again on this page's own reading of a
// listing: the read is a read. What comes back is the pair, for the owner to press or
// not — see `PARK_ASK_AGAIN` for what pressing it now means.

// What answering again does, shared by every ending that read no reply because it does
// not depend on which of them happened — `WHERE_TO_LOOK`'s device, one surface over.
//
// **It reads presence as answerability and absence as nothing at all**, which is
// adversarial review's round-4 blocker on #1612 and it is right. An earlier draft said a
// park the listing no longer offers "was answered", and that is an inference from
// absence the engine refuses to license: `AuditTrail.pending_confirmation` answers
// `None` for a binding already resolved **and** for a `CONFIRM` whose origin was never
// recorded — a row written before ADR-0181 §3, decoding to an `OriginUnrecordedBinding`
// (ADR-0184 §2), for which "nothing is written, so the step stays durably
// `AWAITING_APPROVAL` with its `CONFIRM` unresolved and its row intact… The park is
// unanswerable, not erased." So the enumeration walks past a park that no answer has
// resolved, and a page reading that as a resolution would tell the owner the opposite of
// the state. ADR-0139 §4 is the rule and it does not soften for an absence.
//
// **This constant used to be `PARK_ROUTE_BACK` and used to say the route back was a
// reload. ADR-0198 is why it is not.** The reload was #1612's answer to adversarial
// review's round-7 blocker, and that blocker was right on the facts it had: the page had
// been un-spending a token wherever `pending_confirmations` still listed the park, on
// the reading that `_resolve_park` records the answer and evicts the binding under the
// one lock `_pending_confirmations` also takes — so a park observed pending is one no
// resume had resolved. True and insufficient. The lock establishes that no resume *has*
// resolved the park, never that none *will*; an abandoned answer may still be in
// transit, a listing read that reaches the lock first legitimately returns the park as
// pending, and a second `resume` then raced the first. The loser raised
// `UnknownContinuationError`, which reaches this page as `assistant-declined` and
// renders as a denial ADR-0084 §7 refuses in terms. That was #1536's residual, filed as
// #1621 and reachable from nowhere under `interfaces/gateway/`.
//
// **The engine seam has since been decided, and the race is closed there.** ADR-0198 §1
// retains a resolved binding under its handle and makes a later `resume` presenting that
// token **restate** the recorded answer: it "returns a `TurnOutcome` describing the
// settled binding and raises no `UnknownContinuationError`", performing nothing whatever
// the call's `approved` carries. §7 pins the concurrent case in the shared contract —
// two `resume` calls for one token both return the one settled outcome and the trail
// holds one resolution. So the loser of that race is answered instead of refused, and
// re-answering is **safe** rather than merely deliberate, which is ADR-0198's own second
// Consequence naming this page.
//
// **And a reload is not merely unnecessary now; for the case this page most needs, it
// never worked.** A settled binding is never listed and never re-minted (ADR-0198 §4,
// ADR-0052 §1 step 2), so where the first answer *did* land, no reload and no listing
// read can hand that park back. The only thing that can ask "did my answer land?" is the
// token this page is still holding, which is ADR-0198's first Consequence exactly. So
// what un-spends a token is what **this page** did to it (`strand`), never a snapshot it
// read — round 7's actual prohibition is untouched — and `spent` is given back at the
// ending rather than at the next listing read.
//
// **What this has to say, and what it must not.** It must not offer the pair as a way to
// *change* an answer: a park is answered once (ADR-0044 §2b), so a second answer
// disagreeing with a first that landed changes nothing, and a page that let the owner
// believe otherwise would be inventing an act the engine does not have. It must not
// promise the question is always answerable either — a settled record is discarded once
// `max_outstanding_confirmations` other parks have settled, and a restart empties the
// table (ADR-0198 §4) — after which the token names nothing and the engine says so.
// Neither of those is a denial, and `PARK_REFUSAL_AFTER_UNKNOWN` is where this page
// keeps that promise.
//
// **It is the *row's* account and not the ending's, which is what driving the page
// settled.** Both used to end in `PARK_ROUTE_BACK` and a reload was short enough for
// that to pass unnoticed; this is not, and at a desktop width the whole of it landed on
// screen twice — once in the fault line and once in the row three inches below it. A
// consent surface that is not read is the failure this file spends the most words
// preventing, so the long account goes where the pair is and the ending carries
// `PARK_WHERE_NOW` instead. The file's own division is what decides which: what happened
// is said once, at the ending; what is still true is what the row carries.
const PARK_ASK_AGAIN =
  "The controls have come back, and pressing one is safe: a park is answered once, so " +
  "a second answer never carries the action out a second time. If the first answer did " +
  "arrive, what comes back is the answer already recorded, and that one stands — this " +
  "is not a way to change an answer. If it never arrived, the one you send now is the " +
  "one that stands, so send the answer you want rather than a question. And if the " +
  "assistant is holding neither that park nor its answer any longer, after a restart " +
  "or once enough other parks have been answered, it can no longer say what became of " +
  "yours: this browser will say so rather than call it refused.";

// Where to answer it now, shared by every ending that read no reply.
//
// **It promises no control, because at this point there may be none.** The pair comes
// back on the token, but a *row* is what carries it, and a row built from the recovery
// listing is replaced on the next read — so a park whose first answer did land is
// dropped from the listing (a settled binding is never listed, ADR-0198 §4) and its row
// goes with it. What survives is a row a turn of this page's own parked, which lives in
// the answer panel and no listing read clears. So this says "where this park is still on
// screen", which is true either way, and #1665 carries the case it leaves: a stranded
// token whose row the listing has dropped can no longer ask what was decided, though
// ADR-0198 would now answer it.
//
// **And it keeps round 4's second blocker whole**: absence is read as nothing at all.
// `AuditTrail.pending_confirmation` answers `None` for a binding already resolved *and*
// for a `CONFIRM` whose origin was never recorded (ADR-0184 §2), for which "the step
// stays durably `AWAITING_APPROVAL` with its `CONFIRM` unresolved and its row intact…
// The park is unanswerable, not erased" — so a page reading a missing entry as a
// resolution would tell the owner the opposite of the state.
const PARK_WHERE_NOW =
  "Where this park is still on screen you can answer it again: a park is answered " +
  "once, so a second answer never carries the action out twice, and the row says what " +
  "pressing one now means. Press Confirmations to read what is still waiting — a park " +
  "still listed there is one that can still be answered. A park the listing no longer " +
  "offers is one this browser cannot answer from it: the listing says which parks are " +
  "answerable and not why one is missing, so nothing here calls it resolved.";

// **What a row carries while its token is claimed and its answer went unread.**
//
// Cause-neutral, deliberately, and that is adversarial review's round-5 finding: a row
// is re-rendered by every later transition — the park's other row answering, a listing
// read, the registry refreshing — and the sentence it takes is chosen then, long after
// the ending. A row that said "You stopped waiting" after a *connection* failed would
// attribute to the owner an act they did not take, which is the same class of wrong
// explanation `abandonAsk` keeps three sentences apart for the ask.
//
// So the division is: **what happened** is said once, at the ending, in the fault line
// beside the row — one of the three below, each naming its own cause — and **what is
// still true** is what the row carries, which is this. Neither restates the other.
//
// **This is the sentence beside a pair that has come back enabled**, so it is the one
// that has to explain what pressing it now does: it ends in `PARK_ASK_AGAIN`, which says
// a park is answered once, that an answer already recorded is the one that stands, and
// that the engine may no longer hold either. An enabled control that gave no account of
// itself would be the same silent surface #1536 is about with the sign reversed — the
// owner would read the pair coming back as this page announcing that nothing happened,
// which is the inference ADR-0139 §4 forbids in exactly that direction.
const PARK_NOT_KNOWN =
  "This browser sent an answer for this park and never read a reply, so what became of " +
  "it is not known: the assistant may have carried the action out and may never have " +
  "received the answer at all. Nothing was re-sent and nothing was cancelled. " +
  PARK_ASK_AGAIN;

// **What is still true of a park this page answered *after* an answer it never read
// back** (#1621, ADR-0198). The row is not lying about the outcome — one was read and
// rendered — but it cannot say whose: `resume` answers the park where the first answer
// never arrived and restates the recorded one where it did, and the two come back in the
// same shape (ADR-0170 §4's second shape, ADR-0198 §2). Nothing on the wire distinguishes
// them, which is deliberate rather than missing: ADR-0198 §7 forbids the engine lane a
// file under `interfaces/`, `TurnOutcome` gains no member saying "this was a
// restatement", and the one structural tell this page could reach for — a resume whose
// outcome names no conversation and reports no degraded capture — is an inference from
// absence, which is the move ADR-0139 §4 spends five clauses refusing.
//
// So the page states the fact it actually holds, which is a fact about **its own**
// history: an earlier answer of its own went unread, so the record it is now looking at
// may be that one. That is honest under either outcome and asserts neither.
const PARK_SETTLED_AFTER_UNKNOWN =
  "An earlier answer this browser sent for this park was never read back, so the answer " +
  "shown for it is the one the assistant has recorded — which may be that earlier " +
  "answer rather than the one just sent. A park is answered once, and this browser " +
  "cannot tell which of the two the record is.";

const PARK_UNRESOLVED =
  "You stopped waiting for that answer, so this browser is no longer listening for it. " +
  "What became of it is not known: the answer was sent and nothing here read a reply, " +
  "so the assistant may have carried the action out and may never have received the " +
  "answer at all. Nothing was re-sent and nothing was cancelled. " +
  PARK_WHERE_NOW;

// **A refusal the gateway answered, that is nonetheless not known** (rounds 5 and 6).
// ADR-0177 §7's third clause is read from ADR-0168 §9's distinction "and from nothing
// else": "a request the hub received and declined is **known not to have landed**; a
// transport failure between the gateway and the hub is **not known**".
//
// **Two refusals reach it and `act` already sorts both, in these words.** One is named:
// a `502 hub-unreachable`, which `_relay_fault` raises from a `TransportError` the wire
// client can raise *after* the call was delivered, so the hub may have run the action
// with only the reply lost — `UNKNOWN_FAULTS` is this page's own record of which
// conditions those are. The other names nothing: `readBody` normalises a truncated,
// malformed or proxy-substituted body to `{}`, and "a refusal whose condition this page
// cannot read is a refusal it cannot classify, and ADR-0139 §4's third outcome is what
// an unclassifiable one is" — `act`'s own sentence, whose reachable case is "a response
// cut after its headers: the status may be the `502` the gateway writes for a hub it
// could not reach". Reading either as known-not-landed releases a continuation the hub
// may already have resolved, which is the inference ADR-0139 §4 forbids.
//
// **One sentence for both, and it names what is common rather than picking one.** What
// the owner needs is that the refusal does not establish the answer never arrived; which
// of the two ways it fails to establish it is said in the clause, so neither state
// borrows the other's explanation.
//
// **It states that rather than restating `FAULTS`'s sentence for `hub-unreachable`.**
// That entry reads "so nothing was asked … nothing was queued", which is a claim about
// whether the hub *received* the request — true enough of a read, and exactly what §7's
// third clause forbids asserting of a mutating act. It is shared by every `relay`
// caller, several of which mutate, so correcting it is #1619's and not this lane's;
// what this does is not put the contradiction on one screen.
const PARK_REFUSAL_NOT_KNOWN =
  "The gateway refused that answer, and what it refused with does not establish that " +
  "the answer never reached the assistant — either the failure was between the gateway " +
  "and the hub, or this browser could not read the condition at all. So what became of " +
  "it is not known: the action may have been carried out, with only the reply lost. " +
  "Nothing was re-sent and nothing was cancelled. " +
  PARK_WHERE_NOW;

// **A refusal of a *second* answer, which says nothing about the first** (#1621).
//
// This is the arm the re-offer opens and the one it would be worst to get wrong. Where
// the assistant no longer holds the park **or** its answer — a restart, a binding
// reconciled away under ADR-0052 §2, or a settled record discarded once
// `max_outstanding_confirmations` others have settled (ADR-0198 §4) — `resume` raises
// `UnknownContinuationError`, `_relay_fault` renders every `AssistantError` as
// `assistant-declined`, and `FAULTS` reads that as "The hub received the request and
// declined it". ADR-0084 §7 refuses that reading in terms: an unresolvable token is
// **never a denial**, and announcing one for an action that may well have run is the
// precise failure round 7 blocked #1612 over.
//
// **So a named refusal is not read as known-not-landed on a re-answer, whatever it
// names.** The page's own record is what decides that: it knows this token already
// carried an answer whose reply it never read, and no refusal of the *second* request
// can establish what became of the *first*. The branch is therefore taken on this
// page's history rather than on the condition, which is the only fact of the two that
// is actually about the earlier answer.
//
// **It is over-cautious in exactly one arm, and that is the right direction.** A park
// answered past its deadline is refused by `StepRunner._check_fresh` with
// `PermissionDeniedError` before anything is authored (ADR-0198 §5), so there the first
// answer is known not to have landed and this sentence says less than is known. For a
// consent surface the alternative is to read one condition as covering the other, and
// the condition the page can read is the one about the wrong request.
const PARK_REFUSAL_AFTER_UNKNOWN =
  "The assistant refused that second answer, and a refusal of it does not say what " +
  "became of the first: it may be holding neither that park nor its answer any longer — " +
  "after a restart, or once enough other parks have been answered — and a park it can " +
  "no longer find is not a park it declined. So what became of the earlier answer is " +
  "still not known: the action may have been carried out. Nothing was re-sent and " +
  "nothing was cancelled. " +
  PARK_WHERE_NOW;

// **A reply that was read and cannot be made into an answer** (rounds 9 and 10), which
// is round 8's blocker one step in: `asObject` answers `{}` for a `2xx` body that
// parsed to something that is not an object, a well-formed object may still be missing
// `outcome`, and an `outcome` that is present may still not carry what `renderOutcome`
// reads. A proxy-substituted or truncated-then-reassembled `200` is the reachable case,
// the same one round 6 admitted for a refusal.
//
// A read response is not by itself a landed one, and this is the arm where the page
// read a response and still cannot say what happened: ADR-0177 §7's third clause sorts
// a *refusal* into landed or not-known, and says nothing that turns an unreadable
// success into a resolution. ADR-0139 §4's third outcome is what this is.
//
// **Cause-neutral about which of the three shapes it was**, for `PARK_NOT_KNOWN`'s
// reason: the owner's position is the same in all of them, and naming the one that
// happened would be a distinction drawn from a body this page could not read.
const PARK_REPLY_UNREADABLE =
  "The gateway answered that request and this browser could not read an outcome from " +
  "the answer. So what became of the park is not known: the action may have been " +
  "carried out, with only the account of it lost. " +
  "Nothing was re-sent and nothing was cancelled. " +
  PARK_WHERE_NOW;

// **The same ending, reached without the owner asking for it**, which is round 4's
// first blocker. A `fetch` that rejects is the browser's own request failing with no
// response read — ADR-0177 §7's fourth clause exactly, "the request was sent and no
// response was read", which is an outcome that is **not known** "whatever the gateway
// did". The page used to call it `GATEWAY_GONE` and hand the token back, which asserts
// the one thing ADR-0139 §4 spends five clauses refusing to let a surface assert: the
// gateway may have relayed the call and the hub may have run it, with only the answer
// lost on the way home.
//
// **`act` is the precedent and it is in this file**: the grant surface's own `fetch`
// site is the one that deliberately does not report a rejection as the gateway having
// gone, for this reason and in these words. A park's answer is the same class of act
// and spends a consent token besides, so it joins it.
//
// Its own sentence rather than `PARK_UNRESOLVED`'s, because that one opens with "You
// stopped waiting", which is false here — nobody stopped anything. Everything after
// that opening is the same, because none of it turns on which way the reply was lost.
const PARK_LOST =
  "The connection carrying that answer failed before this browser read a reply. What " +
  "became of it is not known: the answer was sent and nothing here read a reply, so " +
  "the assistant may have carried the action out and may never have received the " +
  "answer at all. Nothing was re-sent and nothing was cancelled. " +
  PARK_WHERE_NOW;

// **A row that is no longer the live one, said rather than left looking answerable**
// (#1536). `spent` is per park and one park is on screen twice — a turn that parks
// renders its confirmation with the answer, and the recovery listing renders the same
// park again with the *same* token — so answering either leaves the other holding a
// token `answerConfirmation` returns early on. An enabled control that submits nothing
// is the silent refusal this surface spends the most words preventing, so the pair is
// disabled and the row says why.
// **The other row of the same park, while the answer is still out.** One park is on
// screen twice and `spent` is claimed before the request goes out, so without this the
// second row would say the park had been answered while its answer was in flight —
// which is a state this page has not read. It says what it does know: an answer is on
// its way, this is not the control that sent it, and where the outcome will appear.
const PARK_ELSEWHERE =
  "An answer for this park is already on its way, sent from the other place it is " +
  "shown on this page. This row is not the live control, and what became of that " +
  "answer will be said where it was sent from.";

const PARK_ANSWERED =
  "That park has been answered from this page, so this row is no longer the live one. " +
  "Press Confirmations to read what is still waiting.";

// Which sentence a row carries, from the three facts that decide it and from no
// fourth — and it is a function so that the *token* is not one of them: ADR-0177 §8
// has the front end render the continuation nowhere, so nothing that computes a text
// node takes one.
//
// **Five states rather than four, because `stranded` no longer implies `answered`**
// (#1621). Before ADR-0198 a token whose answer went unread stayed spent, so the two
// facts moved together and the only stranded row was a disabled one. Now `strand` gives
// the token back, and the pair of them names two distinct rows: one whose earlier answer
// is unaccounted for and which is answerable again (`PARK_NOT_KNOWN`), and one that was
// answered again afterwards and whose record may be the earlier answer rather than the
// later (`PARK_SETTLED_AFTER_UNKNOWN`).
function parkWords(mine, out, answered, stranded) {
  if (mine) {
    return PARK_WAITING;
  }
  if (out) {
    return PARK_ELSEWHERE;
  }
  if (answered) {
    return stranded ? PARK_SETTLED_AFTER_UNKNOWN : PARK_ANSWERED;
  }
  return stranded ? PARK_NOT_KNOWN : "";
}

function offerApproval(item, token) {
  // **Nothing *here* gives a token back, and that is still the rule** (#1536, and
  // adversarial review's round-7 blocker on #1612). A row built here is built from
  // `pending_confirmations`, or from a `Confirmation` a turn just returned, and an
  // earlier draft treated either as the engine's own statement that the park is still
  // answerable and un-spent the token on it. It is not. `_resolve_park` records the
  // answer and evicts the binding under the one lock `_pending_confirmations` also
  // takes, so a park observed pending is one no resume *has* resolved — and an abandoned
  // answer may still be in transit, so nothing there says none *will*. A listing snapshot
  // is not evidence about a request in flight, and that is as true after ADR-0198 as
  // before it.
  //
  // **What changed is where the evidence comes from, not that the pair comes back.**
  // ADR-0198 §1 retains a resolved binding under its handle and makes a second `resume`
  // restate the recorded answer rather than raise, so the race round 7 blocked over is
  // closed at the seam it belonged to — and re-answering became safe rather than merely
  // deliberate (#1621, ADR-0198's second Consequence). The token is therefore given back
  // by `strand`, at the ending, on this page's own knowledge of what it did; nothing in
  // this function and nothing in `readPending` gives one back on a listing's evidence.
  //
  // The pair it renders is enabled or disabled from the three sets alone, so a row that
  // is answerable again is answerable wherever it was built, and `PARK_ASK_AGAIN` beside
  // it says what pressing it now means.
  const approve = document.createElement("button");
  approve.type = "button";
  approve.textContent = "Yes, do it";
  const decline = document.createElement("button");
  decline.type = "button";
  decline.textContent = "No";
  // The way out of a wait this page will not bound (#1536), built here rather than
  // shipped in `index.html` for `offerStopWaiting`'s reason: it belongs to a request
  // and not to the surface, and there is one of these per row.
  const stop = document.createElement("button");
  stop.type = "button";
  stop.textContent = "Stop waiting";
  stop.hidden = true;
  const said = document.createElement("p");
  said.className = "hint";
  // **One answer per park, enforced here rather than discovered at the hub.** A
  // second `resume` on a token the first already resolved raises
  // `UnknownContinuationError`, which ADR-0084 §7 makes emphatically *not* a denial —
  // so a double click would put "the hub declined it" on screen for an action that
  // had in fact just run, which is the one thing this surface exists to get right.
  // Both are disabled because either one submits, and both come back where the
  // request failed and the row survives to be answered again — `ask` disables its own
  // button for the same window and for the same reason.
  //
  // **What this row is, said and enabled in one place** so the pair, the sentence and
  // the way out cannot get out of step with each other — `askWaiting`'s device, one
  // surface over.
  //
  // **Every state but one is the park's, read off the three sets rather than held
  // beside them**, which is what closes #1536's residual: a row over a token that is
  // claimed renders disabled and says which of the three things that means, wherever
  // the row came from and whichever path left the token that way. `waiting` is the one
  // fact that is this row's — it is the row that has a wait to leave — and it is why
  // the control is per row while the pair is per park.
  //
  // **And it is reached for every row of the park, not just this one**, which is what
  // the registry above buys. Adversarial review found the gap on round 1: answering
  // from the listing's row left the answer panel's row for the same park enabled over a
  // token `answerConfirmation` returns early on — a control that submits nothing, which
  // is the residual surviving inside its own fix.
  let waiting = false;
  const settle = () => {
    const out = answering.has(token);
    const answered = spent.has(token);
    const stranded = unresolved.has(token);
    approve.disabled = out || answered;
    decline.disabled = out || answered;
    stop.hidden = !waiting;
    said.textContent = parkWords(waiting, out, answered, stranded);
    said.hidden = said.textContent === "";
  };
  let stopping = null;
  // **It aborts and it announces, and it sends nothing** — `abandonAsk`'s own rule, and
  // for its reason: the abort is what makes the pending `fetch` settle, so the promise
  // the row is waiting on stops being one that never resolves, and a control that
  // quietly re-sent the answer would be the silent retry ADR-0168 §9 forbids wearing a
  // button's clothes.
  stop.addEventListener("click", () => {
    if (stopping !== null) {
      stopping.abort();
    }
  });
  const answer = async (approved) => {
    // The park's own guard, taken before the row's: a click on a row the registry has
    // not reached yet — one rendered in the same turn of the event loop as the answer —
    // must not start a second request either.
    if (answering.has(token) || spent.has(token)) {
      return;
    }
    waiting = true;
    answering.add(token);
    stopping = new AbortController();
    refreshParks();
    try {
      await answerConfirmation(token, approved, stopping);
    } finally {
      waiting = false;
      answering.delete(token);
      refreshParks();
    }
  };
  approve.addEventListener("click", () => answer(true));
  decline.addEventListener("click", () => answer(false));
  item.appendChild(approve);
  item.appendChild(decline);
  item.appendChild(stop);
  item.appendChild(said);
  parkRows.add({ node: item, settle });
  settle();
}

// The one recovery route (ADR-0177 §8). A browser that has been closed and reopened,
// and a gateway that has been restarted, both get back to a park through this read and
// through no other — which is why the page holds no confirmation of its own between
// loads and caches no token: `pending_confirmations` mints a fresh one per call, and a
// remembered one names an entry in a handle table a restart emptied (ADR-0052 §1).
async function listPending() {
  await readPending(false);
}

// Which read of the listing is the live one. The questions listing's own device, for
// the reason it states: two reads can be in flight at once — the page starts one as it
// loads and an answered park starts another — and the slower one finishing last would
// clear the list and re-render the snapshot it took *before* the answer. That puts a
// resolved park back on screen with an approval control whose token the engine has
// already spent, so the owner's next click reports a refusal for something that ran.
// Only the most recently started read renders.
let pendingRun = 0;

// Read it, and say so or not.
//
// `quiet` is the difference between the owner asking what is waiting and the page
// looking on its own as it loads: an empty answer to a question nobody asked is a
// panel that says nothing, so it stays closed, and an empty answer to the button is
// the answer and is shown.
async function readPending(quiet) {
  fault(null, "confirmations");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  pendingRun += 1;
  const run = pendingRun;
  try {
    const body = await relay(half, "/confirmations", {}, "confirmations");
    if (body === null || run !== pendingRun) {
      return;
    }
    const list = el("confirmation-list");
    clearNode(list);
    // **Every row this read replaces leaves the registry here** (adversarial review,
    // round 2). `parkRows` holds a strong reference to each row's node, and pruning it
    // only on a park's state transition meant a listing read with nothing answered
    // retained every detached row it had ever rendered. A prune is what `refreshParks`
    // does on the way past, so the clear and the prune are one line apart and cannot
    // drift.
    refreshParks();
    if (body.confirmations.length === 0) {
      if (quiet) {
        show("confirmations", false);
        return;
      }
      line(list, "Nothing is waiting for your answer.", "hint");
    }
    body.confirmations.forEach((one) => renderConfirmation(list, one));
    show("confirmations", true);
  } catch (_) {
    fault(GATEWAY_GONE, "confirmations");
  }
}

// The continuations this page has spent, or is spending now.
//
// **Per park, because one park is on screen twice.** A turn that parks renders its
// confirmation with the answer, and the recovery listing renders the same park again —
// with the *same* token, because the engine "reuses that entry's token rather than
// minting a second" for a binding it already holds. Two rows, one park; answering both
// resolves it with one request and gets the other refused as an unknown continuation,
// which ADR-0084 §7 makes emphatically not a denial and this page would report as one.
// Disabling a row's own pair is the visible half and is not the guarantee.
//
// **Per park rather than one flag for the page**, which a stalled request is what
// distinguishes: `fetch` has no deadline of its own, so a page-wide lock held across a
// hung request would silently refuse the owner's answer to every *other* park, and a
// silent refusal is the one thing this surface cannot do. A token is guarded on its
// own and nothing else waits on it.
//
// It is held in page state and in no browser storage (ADR-0177 §8), the token is
// compared and never read, and the set is bounded by the parks answered in one page's
// life.
//
// **A token stays in it for the life of the page only where a reply was read**, which
// is where ADR-0198 moved the line (#1621). A resolution this page read is final: the
// binding is settled, the listing will never hand it back, and pressing the pair again
// would ask a question the row's own sentence has already answered. An ending that read
// *no* reply is the opposite case — the token is the only thing that can ask what became
// of the answer, and a settled binding is never listed, so nothing a reload or a listing
// read can reach would ask it. `strand` gives that one back at the ending.
//
// A reload still starts it empty, and that is now an ordinary consequence of holding the
// set in page state rather than a route the page has to point at.
const spent = new Set();

// The parks this page answered and never read a reply for (#1536, #1621).
//
// **A second set rather than a flag on `spent`**, because the two record different
// facts: `spent` is the guard that stops one park being answered twice *while the answer
// stands*, and this is the record of an answer of this page's own whose outcome
// ADR-0177 §7's fourth clause makes **not known** — "the request was sent and no response
// was read". The two are no longer nested. A token here and not in `spent` is one the
// pair may submit again, and one in **both** is one that was answered again afterwards
// and whose record may be the earlier answer rather than the later; `parkWords` gives
// each its own sentence.
//
// **It is written and never deleted from, which is what makes the caveat durable.** An
// answer of this page's own that went unread stays a fact about this page's history for
// the life of the page, whatever it does afterwards — so a park re-answered successfully
// still says that the record shown for it may be the earlier answer, and a second strand
// adds nothing that is not already true. **And nothing a listing read returns undoes it**
// — round 7's blocker and the ruling on it, which ADR-0198 does not touch: what it
// licenses is re-answering on the strength of the token, never on the strength of a
// snapshot (`PARK_ASK_AGAIN`, `offerApproval`).
//
// Held in page state and in no browser storage, compared and never read, and bounded by
// the parks answered in one page's life — `spent`'s own properties, for `spent`'s own
// reasons. A reload starts both empty, which is correct: recovery is
// `pending_confirmations`, and a park it hands back after a reload is one the engine
// still holds.
const unresolved = new Set();

// The tokens an answer is out on **right now**, which is the fact neither set above
// carries. `spent` is claimed before the request and never given back on a resolution,
// so it cannot tell an answer that is in flight from one that settled; and the
// difference is a sentence the owner reads: a second row of the same park may not say
// "that park has been answered" while the answer is still on its way.
//
// Adversarial review found the gap on round 1, in the shape the file already warns
// about two comments up — one park is on screen twice.
const answering = new Set();

// Every park row on screen, so one park's state reaches all of its rows.
//
// **A registry rather than a lookup by token**, because two rows of one park are two
// nodes in two panels — the answer panel, where a turn that parked renders its own
// confirmation, and the recovery listing — and neither knows about the other. Before
// it, answering from one row disabled that row and left the other enabled over a token
// `answerConfirmation` returns early on: a control that submits nothing, which is the
// residual #1536 is about, surviving inside its own fix.
//
// **A row is pruned when it leaves the document, and by nothing else.** `clearNode`
// replaces a whole listing on every read, so a registry that waited to be told would
// grow one entry per row ever rendered; `isConnected` is the same question
// `abandonAsk` asks of the answer panel, and for its reason — ownership of what is on
// screen is a fact about *now*, and no bookkeeping has to be kept in step to know it.
const parkRows = new Set();

// Every row still on screen, told what its park is now. Called where the state changes
// and nowhere else, so a row cannot be left rendering a fact that has moved.
function refreshParks() {
  parkRows.forEach((row) => {
    if (row.node.isConnected) {
      row.settle();
    } else {
      parkRows.delete(row);
    }
  });
}

// **One ending whose outcome is not known, recorded as one act.** The token comes back —
// nothing else on this page ever gives one back — and the fact that its earlier answer
// went unread is written down in the same breath, because the two are one statement: the
// pair may be pressed again, and what pressing it produces may be the record of the
// answer that went unread rather than of the answer just sent.
//
// **A function rather than two lines at four call sites**, because the halves are only
// safe together. Giving the token back without recording why would re-offer the pair
// with a row that says nothing — the silent surface #1536 is about, sign reversed, since
// the owner would read the enabled control as this page announcing that nothing happened
// (ADR-0139 §4 forbids exactly that inference). Recording why without giving the token
// back is the state ADR-0198 was decided to end.
//
// It takes the token and no reason: which ending it was is said once, at the ending, in
// the fault line beside the row, and what is still true is the row's own sentence —
// `PARK_NOT_KNOWN`'s division, and the reason `strand` has nothing to choose between.
function strand(token) {
  unresolved.add(token);
  spent.delete(token);
}

// One answer, relayed. The page conveys consent and rules on nothing (ADR-0042 §6):
// a refusal comes back as an ordinary outcome whose step was denied, not as a fault,
// and it is rendered where every other turn's result is rendered.
//
// The listing is read again afterwards, quietly, because answering one park is the
// only thing that changes what is waiting — and re-reading is also how the page gets
// fresh tokens for whatever is left rather than keeping the ones it has.
async function answerConfirmation(token, approved, stopping) {
  if (spent.has(token)) {
    return;
  }
  fault(null, "confirmations");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  // **Whether this page already has an unaccounted-for answer out on this park**, read
  // before the claim below and never after: `strand` writes `unresolved` at an ending,
  // so a value read later could be this request's own record rather than the earlier
  // one's (#1621). It is the only fact that separates a first answer from a second, and
  // the outcome cannot supply it — a `resume` that resolves the park and one that
  // restates a settled binding come back in the same shape (ADR-0170 §4's second shape,
  // ADR-0198 §2), and telling them apart from what the body does *not* carry is the
  // inference from absence ADR-0139 §4 refuses. So the page reads its own history, which
  // is the one thing here that is actually about the earlier answer.
  const unaccounted = unresolved.has(token);
  // Claimed before the first `await`, so two clicks in one turn of the event loop —
  // the two rows of one park, or one row twice — cannot both get past the guard.
  spent.add(token);
  // A resumed park answers with a turn outcome exactly as an ask does, so it carries
  // the same count for the same reason.
  const chosenAt = chose;
  let body = null;
  // What the gateway refused with, where it refused — kept because `relay` displays the
  // condition and returns a bare `null`, and this is the one caller for which the
  // difference between two refusals decides whether a consent token comes back.
  let refusal = null;
  const noticed = (named) => {
    refusal = named;
  };
  try {
    body = await relay(
      half,
      "/confirmation/resume",
      { token, approved },
      "confirmations",
      stopping,
      noticed
    );
  } catch (_) {
    // **No response was read, and that is the whole of what decides this** (#1536, and
    // adversarial review's round-4 blocker). Two things reach here — the owner ending
    // the wait, and the request failing on its own — and ADR-0177 §7's fourth clause
    // does not distinguish them: a failure of "the **browser's own** request to the
    // gateway — the request was sent and no response was read — is an outcome that is
    // **not known**, whatever the gateway did". So both take the same branch, and only
    // the sentence differs.
    //
    // **The token comes back and the outcome is still not asserted**, which are two
    // things and only the second was ever in doubt. ADR-0139 §4 forbids inferring the
    // state from the unresolved act, and this branch infers nothing: `strand` records
    // that the answer went unread, the row says so, and the sentence beside it says the
    // action may have been carried out. What #1612 additionally did — keep the token
    // spent for the life of the page — was not that prohibition but the consequence of a
    // second `resume` raising `UnknownContinuationError`, which reaches this page as
    // `assistant-declined` and renders as a denial ADR-0084 §7 refuses in terms. ADR-0198
    // §1 ends that: a token whose binding is settled restates the recorded answer instead
    // of raising. So the token is given back here (#1621), and it is given back on what
    // this page did rather than on a listing's evidence — round 7's prohibition, which
    // still holds.
    //
    // **So this is the one `relay` entry point that does not report a rejection as
    // `GATEWAY_GONE`**, and it is the second such site rather than the first: `act`
    // already refuses that report, in these words and for this reason. A park's answer
    // is the same class of act and spends a consent token besides.
    //
    // **The tidy-up is started and not waited on**, which is the difference that
    // matters to the row: `readPending` reaches the same unbounded `relay`, so
    // awaiting it here would let one stalled read hold this pair disabled all over
    // again — the failure being closed, one ordering over. It runs far enough to clear
    // this panel's fault before the sentence below is written, which is why the
    // sentence comes after it.
    strand(token);
    readPending(false);
    const lost = stopping.signal.aborted ? PARK_UNRESOLVED : PARK_LOST;
    fault(lost, "confirmations");
    return;
  }
  if (body === null) {
    // A refusal the gateway named and `relay` already displayed. A response *was* read,
    // so this is not the clause above — but a read response is not by itself a landed
    // or a not-landed one, and ADR-0177 §7's third clause is what sorts them.
    //
    // **The test is `act`'s, copied rather than re-derived**: a condition this page
    // reads as unknown, *or* a refusal carrying no condition it can read at all. The
    // second is the arm round 6 found missing — `readBody` answers `{}` for a body that
    // was truncated, malformed or replaced by a proxy, and an absent `fault` is not
    // evidence that the request never landed. `refusal` being null is the same nothing
    // and takes the same branch, which is why the guard is written this way round.
    //
    // **And a re-answer takes this branch whatever the condition names** (#1621). A
    // refusal of the *second* request establishes nothing about the *first*: where the
    // assistant holds neither the park nor its answer any more — a restart, a binding
    // reconciled away under ADR-0052 §2, a settled record discarded under ADR-0198 §4 —
    // `resume` raises `UnknownContinuationError`, which `_relay_fault` renders as
    // `assistant-declined` like every other `AssistantError`. Reading that as "the hub
    // declined it" is the denial ADR-0084 §7 refuses in terms, announced for an action
    // that may have run. `unaccounted` is what forecloses it, and it is the honest test:
    // the condition is about this request and the page's own history is about the one
    // that went unread.
    const named = refusal !== null && typeof refusal.fault === "string";
    if (unaccounted || !named || UNKNOWN_FAULTS.has(refusal.fault)) {
      strand(token);
      readPending(false);
      fault(unaccounted ? PARK_REFUSAL_AFTER_UNKNOWN : PARK_REFUSAL_NOT_KNOWN, "confirmations");
      return;
    }
    // A condition the gateway named and this page reads as a request the hub received
    // and declined, which is known **not** to have landed — so the park was not
    // resolved and the row stays answerable.
    spent.delete(token);
    return;
  }
  // **An answer this page cannot put on screen is not one it has read** (rounds 9 and
  // 10). `renderOutcome` reads the outcome's members from its first lines —
  // `capture_degraded`, then `reply`, then `steps.length` — and it was called *outside*
  // the `try` above. A `2xx` carrying no outcome, or one whose members are not the ones
  // this page renders, threw there: the token stayed `spent` and never `unresolved`,
  // the row's `finally` cleared `answering`, and every row of the park then read "That
  // park has been answered from this page" for an outcome nothing had read. That is
  // exactly the resolution ADR-0139 §4 forbids, reached through the last door in this
  // function.
  //
  // **The render is the test, rather than a shape check that has to enumerate what
  // renders.** Round 9 checked that the outcome was an object and round 10 walked `{}`
  // straight past it: any list of members would need re-deriving every time
  // `renderOutcome` reads a new one, and getting it wrong reinstates the same false
  // resolution silently. What this page actually needs to know is whether it can put
  // the answer on screen, and running the render is the only thing that answers that.
  //
  // A defect in `renderOutcome` itself therefore also lands here, reported as an
  // outcome that is not known. That is the conservative direction and the right one for
  // a consent surface: the alternative on offer is not a truthful crash, it is a park
  // announced as answered on the strength of an exception.
  //
  // `ask` and `askStreaming` reach `renderOutcome` the same unchecked way and are left
  // alone here: neither spends a consent token, so a throw there is a console error and
  // a panel that does not update rather than a park falsely reported as resolved. Still
  // wrong, and filed as #1622 rather than absorbed.
  //
  // **The caveat is handed to the render rather than appended after it** (#1621), because
  // it changes how everything below it is read and `renderOutcome` clears its panel on
  // the way in. Where this page already had an unaccounted-for answer out on the park,
  // what is on screen is the answer the assistant has **recorded** for it, which may be
  // that earlier one rather than the one just sent (ADR-0198 §1 — the recorded answer
  // stands whatever the second call's `approved` carries). The page says that and stops:
  // it does not claim which of the two it is reading, because nothing it can read tells
  // it, and it does not withhold the account either, which would be silence about a step
  // that ran.
  try {
    renderOutcome(body.outcome, chosenAt, unaccounted ? PARK_SETTLED_AFTER_UNKNOWN : null);
  } catch (_) {
    // Whatever reached the screen before the throw is not an answer, so it does not
    // stay beside a line saying the outcome is not known — `ask`'s own move where what
    // came back was not an answer.
    show("answer", false);
    strand(token);
    readPending(false);
    fault(PARK_REPLY_UNREADABLE, "confirmations");
    return;
  }
  // Read again, and **after** the guard on this token has done its work rather than
  // inside it: this is the best-effort tidy-up of what is left on screen, and no other
  // park's answer waits on it.
  //
  // **Started and not waited on**, which is the abandoned path's rule arriving on the
  // one that settled — adversarial review found on round 2 that awaiting it was the
  // difference. `readPending` reaches the same unbounded `relay`, so a resume that
  // *succeeded* and a listing read that then hung left this call pending: the row's
  // `finally` never ran, every row of the park went on saying an answer was on its way,
  // and the way out beside it aborted a controller whose request had already finished.
  // A resolved park announced as one still in flight is a state this page has read and
  // is misreporting, which is worse than the silence it replaced.
  //
  // Nothing here depends on the read: `renderOutcome` above has already put the answer
  // on screen, and what is left is which rows the listing still holds.
  readPending(true);
}

async function startSession(event) {
  event.preventDefault();
  fault(null, "bootstrap");
  const value = el("bootstrap-value").value.trim();
  let response;
  let body;
  try {
    response = await fetch("/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bootstrap_value: value }),
    });
    body = await readBody(response);
  } catch (_) {
    fault(GATEWAY_GONE, "bootstrap");
    return;
  }
  if (!response.ok) {
    fault(describe(body, response.status), "bootstrap");
    return;
  }
  el("bootstrap-value").value = "";
  changeConversation(null);
  if (!rememberHeaderHalf(body.header_half)) {
    fault("This browser will not store the session, so it cannot hold one.", "bootstrap");
    return;
  }
  showConsole();
}

// One request the gateway admits, with both halves of the session presented as
// ADR-0168 §6 requires: the header this page sets, and the cookie the browser
// attaches on its own.
function admitted(half, extra) {
  const headers = { [SESSION_HEADER]: half };
  if (extra) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

// **Re-entry, and it is not a fault** (ADR-0182 §6). A refusal that means this
// browser's session is gone: forgetting the half and showing the bootstrap panel is
// the only thing a page can do about either, and doing it in one place keeps the two
// conditions from drifting apart.
//
// §6 rules where it is said as well as that it is said — "shown the bootstrap entry,
// presented as re-entry rather than as a fault. It is not rendered in the page's fault
// surface" — so this writes the panel's own hint and nothing here reaches `fault`. A
// session that ran out its idle timeout ended exactly as this page says sessions end;
// rendering that in the slot kept for things that went wrong is how an owner learns to
// stop reading the slot.
//
// **`said` is the condition the gateway named, restated rather than dropped.** §6 does
// not oblige the page to distinguish which condition ended the session and the gateway
// does not always let it — but where there are words, losing them to satisfy a clause
// about *where* a sentence goes would be trading one silence for another. It joins the
// re-entry sentence in the hint, so §6's placement holds and nothing is lost.
const RE_ENTRY =
  "That session has ended, so this browser was asked to start a new one. Nothing was " +
  "lost: a conversation belongs to the hub and outlives every session. Paste a fresh " +
  "bootstrap value to carry on.";

function sessionLost(body, said) {
  if (body.fault === "no-live-session" || body.fault === "cookie-half-mismatch") {
    forgetHeaderHalf();
    // **The stream goes with the session, and it goes first** (#1542). `stopWatching`
    // below changes what the page says and what the owner can press; this ends the
    // request those two describe, without which re-entry opens a second stream beside
    // a first the gateway is still writing to. `releaseStream` carries the reading of
    // ADR-0182 §7's third clause that puts it here rather than there.
    //
    // Before the half is gone rather than after would be the same act; after it is
    // deliberate, so that the rejection this provokes reaches `watchDeliveries`' own
    // `finally` — which spends any held re-arm — with `headerHalf()` already null, and
    // `rearm` refuses on that. A re-arm firing into a session that has just ended
    // would be the page re-establishing a stream of its own motion, which §7 permits
    // on `visibilitychange` and `online` and on nothing else.
    releaseStream();
    stopWatching();
    showBootstrap(said ? `${RE_ENTRY} ${said}` : RE_ENTRY);
    return true;
  }
  return false;
}

// **The same two conditions, named by the response head alone.**
//
// `sessionLost` reads the condition out of the *body*, which is right everywhere a body
// was read — and is exactly what a request whose body read the owner stopped does not
// have. For these two conditions the head is enough on its own, and reading it is a read
// rather than a guess: `server.py`'s `_REFUSAL_STATUS` gives every refusal condition
// "its own status", because ADR-0168 §6 requires the cookie-half fault "reported to the
// owner as its own condition, and never flattened into an expiry, a ceiling refusal or
// an ordinary absent session" — and "a status shared with another condition is that
// flattening performed by the response rather than by the record". So `401` names
// `NO_LIVE_SESSION` and `409` names `COOKIE_HALF_MISMATCH`, and nothing else answers
// with either.
//
// **A status is in this table only where it names one condition**, which is the whole of
// what the table is for. `403` is deliberately absent: `_REFUSAL_STATUS` gives it to
// `ORIGIN_NOT_OWN` and to `DEVICE_NOT_LISTED` both, so a `403` head says the gateway
// refused and does not say why — and mapping it here would be this page performing the
// flattening §6 forbids the response to perform.
const SESSION_LOST_STATUS = new Map([
  [401, "no-live-session"],
  [409, "cookie-half-mismatch"],
]);

// --- an ask that never answers, and the wait the owner can end (#1500) -------
//
// `fetch` carries no deadline of its own, so a socket that dies without settling — a
// phone whose network went away without an RST, a black-holed connection — leaves the
// `await` below pending for ever. `ask` disables `#ask-button` before the request goes
// out and re-enables it in a `finally`, so that `finally` never ran: the owner's one
// way into the assistant stayed greyed out until the page was reloaded. It is #1474's
// failure on a different request, and it is closed differently, because a different
// clause of ADR-0182 §7 governs.
//
// **Which clause, and what it does and does not say.** #1474 is a *delivery stream*,
// and §7's third clause is about those: it permits a re-establishment "only while it
// holds none", which is a rule about concurrency, so a bound on how long a head-less
// one may be held closes a gap the clause is silent on. An `ask` is reached by §7's
// **fifth** clause instead — "The page re-issues **no other request** of its own
// motion. Every request that asks the assistant for something — each of ADR-0177 §6's
// operations — is re-issued only on an act by the owner" — and by the paragraph that
// grounds it: re-issuing an ask "is a turn the owner may already have had executed",
// so "offering the owner a visible retry costs one control and removes the class".
// Nothing here re-issues anything, so the fifth clause is not breached; what §7 does
// supply is the *shape* of the remedy, and it is a control.
//
// **So the wait is bounded by the owner's own act and by no clock of this page's**,
// which is a decision rather than the easier half of one. An automatic deadline was
// considered and is declined on three grounds:
//
// - **Any figure would pace something the gateway paces, and no head discloses it.**
//   `server.py`'s `_TURN_BUDGET` gives every turn sixty seconds — `_ask` and
//   `_pump_answer` both pass it — and it reaches the browser in no header, in no value
//   and in no setting. A page-side deadline would therefore be a second number that
//   can silently disagree with it, which is `SILENT_CADENCES`' own argument one
//   surface out, and deriving one from `usableCadence`'s figure would be exactly the
//   substitution that rule refuses: `gateway_notification_budget` paces a delivery
//   stream and says nothing about a turn.
// - **`HEAD_DEADLINE_MILLISECONDS`' argument does not transfer.** That figure is
//   defensible because what it bounds is "a round trip and an in-process table read,
//   and nothing else" — the delivery head is written before the poll is awaited. An
//   `/ask` head is written *after* the whole turn: `_ask` awaits `converse` and
//   answers with the outcome. A thirty-second bound there would abandon a healthy
//   turn that was thinking, and announce that its outcome was not known — true, and
//   useless.
// - **It would cover one of the three places the socket can die anyway.** A black hole
//   before the head, one between the head and the first chunk, and one mid-stream are
//   one failure to the owner, and only a control the owner can press at any moment
//   ends all three.
//
// The honest cost is the one thing a control cannot do: an owner who never looks is
// never recovered. That is bounded by where the control sits — beside the greyed-out
// button, which is the thing the owner is looking at when they wonder why they cannot
// ask — and by the page saying, while it waits, that it is waiting and that no deadline
// of its own will end it.

// The ask this page is waiting on an answer to, or `null` while nothing is outstanding.
// One at a time, because `#ask-button` is disabled for exactly that window.
//
// **It carries what was observed and not only the abort**, because ADR-0177 §7's fourth
// clause is conditioned on what was *read*: it makes an outcome not known where "the
// request was sent and no response was read", and a page that said that after reading
// half an answer would be announcing a state it is not in. So the record holds two
// facts, each set at the moment its evidence arrives:
//
// - `heard` — something of this turn's own answer reached this browser, so the question
//   demonstrably got past the gateway to the assistant. What sets it is not the same
//   event on the two entries, and the difference is load-bearing: `/ask` answers only
//   once `converse` has returned, so its response head is proof the turn ran, while
//   `/ask/stream`'s head is written *before* the engine is called (`_write_stream`
//   drains it, then awaits the body) and proves nothing about the assistant at all. On
//   that entry the first chunk is the evidence.
// - `composing` — the node this turn writes its chunks into, or `null` on the entry that
//   has none. It is held as the **node** rather than as a flag because ownership of the
//   answer panel is a fact about *now* and not about the past: a question asked after an
//   answered one leaves the previous answer standing there, and a park answered while
//   this turn is still out replaces the panel through `renderOutcome`. In both cases
//   what is on screen belongs to something else, and clearing it would destroy a
//   complete answer because a later request failed. A node that is still `isConnected`
//   is this turn's panel; one that has been replaced is not, and no bookkeeping has to
//   be kept in step to know it. Adversarial review found the flag version on round 2.
// - `refusedWith` — the status of a refusal head, or `null` where none came back. The
//   head is read whole before the body is touched, so a status is in hand even where the
//   body then stalls, and for two of them the status alone names the condition
//   (`SESSION_LOST_STATUS`). Kept because discarding it is discarding an outcome this
//   browser *did* read: adversarial review found round 2's fix announcing an unknown
//   outcome for a `401` whose body the owner stopped waiting on, which is both false and
//   the one shape that strands a browser holding a header half the gateway will refuse
//   every future request from.
//
// `heard` and `refusedWith` are mutually exclusive by construction — one entry sets
// `heard` on a successful head and the other sets `refusedWith` on the refusal branch it
// returns from — and so are `composing` and `refusedWith`, since the panel is taken only
// after a successful head. Neither pairing has to be reasoned about below.
let awaited = null;

// Said while a question is out. **It does not promise a deadline**, because there is
// none here: what it does is tell the owner that the page cannot tell a turn that is
// taking a while from one whose answer will never arrive, which is the fact that makes
// the control beside it the owner's to use rather than a button that ought to be
// unnecessary.
const ASKING =
  "Waiting for an answer. This browser puts no deadline on a turn and cannot tell one " +
  "that is taking a while from one whose answer will never arrive, so stopping the " +
  "wait is yours to do.";

// What stopping the wait did, and — the whole of why this sentence is long — what it
// did **not**.
//
// ADR-0177 §7's fourth clause is the rule: "A failure of the **browser's own** request
// to the gateway — the request was sent and no response was read — is an outcome that
// is **not known**, whatever the gateway did", and "no front end resolves it by
// assuming either of the other two". A page that handed the button back saying nothing
// would be assuming one of them by omission, because a control that comes back looks
// like an act that finished. So the three things the owner cannot otherwise know are
// each said: the turn may have run, nothing was cancelled at the assistant, and asking
// again is a new question rather than a retry of that one — which is ADR-0182 §7's own
// "the page re-asks only when the owner asks it to", said where the owner is.
//
// The route back, shared by both endings because it does not depend on how far the
// answer got. **It points rather than promises**, and adversarial review was right on
// round 2 that the first wording promised: a turn that ran is not thereby a turn that
// was recorded. `TurnOutcome.capture_degraded` is precisely that shape — the exchange
// "went **unrecorded**" while "the answer is still the answer", because ADR-0074 §9
// item 6 degrades a turn rather than failing it — so an owner told the listing *will*
// show their turn would be told something the contract explicitly allows to be false.
// It is stated as the place to look, with the one case it does not cover named, which
// is this page's rule everywhere: state no state you have not read (ADR-0177 §7).
const WHERE_TO_LOOK =
  "The conversations listing is where to look for it — though a turn whose record " +
  "could not be written does not appear there, however completely it ran.";

// What stopping the wait says where **no response head came back at all** — which is the
// only state its opening clause is true in. A refusal head is a reply this browser read,
// so the two branches above take every wait that saw one, and what is left here is the
// black hole #1500 is about: a socket that produced nothing.
const ASK_ABANDONED =
  "You stopped waiting for that answer, so this browser is no longer listening for it. " +
  "What became of the turn is not known: the question was sent and nothing here read a " +
  "reply, so the assistant may have carried it out and may never have received it. " +
  "Nothing was re-sent and nothing was cancelled — the assistant was not told to stop. " +
  "Asking again asks a new question rather than retrying that one. " +
  WHERE_TO_LOOK;

// **The same act, said where some of it is already known.** Adversarial review found
// the sentence above being used for a wait ended *after* part of the answer had
// arrived, where two of its clauses are false: something here had read a reply, and the
// assistant demonstrably had received the question. ADR-0177 §7's fourth clause is
// conditioned on "no response was read", so applying its words to a state where one was
// is not caution — it is an inaccurate announcement, which ADR-0182 §7 requires the page
// not to make.
//
// So what is unresolved is stated narrowly: the turn reached the assistant, and its
// *ending* is what nobody here read. Everything else is the same act and says the same
// things — nothing re-sent, nothing cancelled, a fresh question rather than a retry —
// because none of that changes with how far the answer got.
const ASK_ABANDONED_MIDWAY =
  "You stopped waiting for that answer, so this browser is no longer listening for it. " +
  "Part of that turn had already reached this browser, so the assistant did receive the " +
  "question and had begun on it; how it ended is what is not known. Nothing was re-sent " +
  "and nothing was cancelled — the assistant was not told to stop. Asking again asks a " +
  "new question rather than retrying that one. " +
  WHERE_TO_LOOK;

// And the clause for the screen, added only where there was something on it. It is
// `ANSWER_STREAM_CUT`'s sentence for `ANSWER_STREAM_CUT`'s reason — ADR-0173 §3 makes
// the terminal outcome's `reply` the answer, so an accumulated chunk sequence is not
// "the record of what the assistant said" — and it is a separate clause because the two
// facts it joins are independent: a whole `ask` abandoned while its body was being read
// has been heard from and has put nothing on screen, and a stream abandoned between its
// head and its first chunk has put an empty panel up and been heard from by nothing.
// Saying either sentence in the other's state would be a wrong explanation rather than a
// missing one, which is the distinction this page keeps everywhere else.
const PARTIAL_CLEARED =
  "What had been written into the answer is not the answer and was not kept, so it has " +
  "been cleared rather than left on screen looking like one.";

// **And the ending where the outcome is not unknown at all**, which adversarial review
// found on round 3. A head this page already read can name the outcome: an expired
// session or a mismatched cookie half is answered by `_session_bound` — `401` and `409`
// respectively — and the body stalling after it changes nothing about what the head
// said. Announcing `ASK_ABANDONED` there would be wrong in every clause that matters:
// the outcome *is* known, the assistant never received the question, and there is no
// turn that may have run. ADR-0177 §7's fourth clause is conditioned on "no response was
// read", and one was.
//
// **What such a refusal means is re-entry** (ADR-0182 §6): "A browser presenting a
// header half the gateway does not admit is shown the bootstrap entry, presented as
// re-entry rather than as a fault." That is the behaviour `sessionLost` performs, and
// stopping the wait must reach it by the same route a refusal read to the end does —
// otherwise the one way an owner has of ending a stalled wait is also the one way they
// can be left holding a dead header half, staring at a console the gateway will refuse
// every request from.
//
// This sentence is what the *act* did, added to the condition's own words rather than
// replacing them: `describe` says which of the two conditions the head named, so this
// says nothing about which — it says only what is true of both. `_session_bound` decides
// both of them before `_assistant` is reached, so "never reached the assistant" is read
// off the gateway's own ordering rather than assumed.
const REFUSED_AT_THE_DOOR =
  "The question you were waiting on never reached the assistant: the gateway refused it " +
  "at the door, so no turn ran and nothing was left half-done. Asking it again once you " +
  "are back in costs nothing.";

// **And a refusal that is not a session's ending**, which adversarial review found on
// round 5. `ASK_ABANDONED` opens by saying "the question was sent and nothing here read
// a reply" — false of *every* refusal head, because a status line is a reply — and goes
// on to say the assistant "may have carried it out", which for most of those statuses is
// known to be false. ADR-0139 §4 is the rule in both directions: an act is reported as
// one of exactly three outcomes "and never as either of the other two", so a known
// not-landed act announced as not known breaches it exactly as the reverse does. This
// page already says so of itself, one surface over, in `relay`: "reporting a landed act
// as 'not known' is forbidden by the same clause that forbids the reverse".
//
// **What separates the sentences is whether the engine could have been reached, and the
// small set is the one that says yes.** The first draft of this enumerated the statuses
// decided *before* the engine and let everything else fall through to "not known".
// Adversarial review then spent two rounds handing back statuses that list had missed —
// `503` on round 5, `413` on round 7, the latter written by `read_request`'s parser and
// so absent from `_REFUSAL_STATUS` entirely, which is where the list had been derived
// from. That is a table this page cannot keep in step with a file it does not import,
// and the fix is to stop keeping it.
//
// **So the page enumerates the other side, which is closed and stays closed.** A refusal
// head is written after the relay began only by `_relay_fault`, the one function
// ADR-0168 §9 makes responsible for a failed relay — "a transport failure
// distinguishable from a request the hub received and declined" — and it writes exactly
// three statuses. Everything else the two ask paths can answer with is decided before
// `_relayed` awaits `call()`: the door's `421` and `403`, the parser's `413` and
// `malformed-request`, `_ceiling`'s `503`, and any status a later lane refuses with
// before it relays. So the default is "no turn ran", and it is right by construction
// rather than by a list being complete.
//
// **The one coupling this keeps is nameable and tested.** A lane adding a *post*-relay
// status would add it to `_relay_fault`, because that is what §9 makes that function
// for, and `test_bundle.py` reads these three back out of it by calling it — so the two
// halves cannot drift without the gate saying so. `400` is here because `_relay_fault`
// writes it for a `ValueError` out of the call, even though the parser writes the same
// status before one: shared, therefore not proof, therefore not claimed.
const RELAY_FAULT_STATUS = new Set([400, 422, 502]);

// **And the one status that proves the opposite half**, which adversarial review found
// on round 6. `422` is `assistant-declined`, and ADR-0168 §9 defines it as "a request
// the hub **received** and declined" — the very distinction §9 requires the gateway to
// keep. So it is the one member of `RELAY_FAULT_STATUS` that is not ambiguous at all:
// it is proof the assistant was reached, and is taken before that set is consulted.
// Grouping it with `400` and `502` said the status said nothing, and it says a great
// deal.
//
// It is decisive on these two paths only. `server.py` writes `422` in one other place —
// `_connection_fault`'s `identity-unusable` — and that serves ADR-0151's connection
// surface, which neither ask path is.
const DECLINED_BY_THE_ASSISTANT = 422;

// The refusal whose reason went unread, and all that is known of the turn.
const ASK_REFUSED_UNREAD =
  "You stopped waiting for that answer, so this browser is no longer listening for it. " +
  "The gateway had already answered that question with a refusal, and this browser " +
  "stopped before reading which one — so no answer came back, and whether the assistant " +
  "ever acted on the question is not something a refusal on its own says. " +
  "Nothing was re-sent and nothing was cancelled — the assistant was not told to stop. " +
  "Asking again asks a new question rather than retrying that one. " +
  WHERE_TO_LOOK;

// The same, where the status settles it. **`WHERE_TO_LOOK` is deliberately absent**: it
// points at the conversations listing for a turn that may have run, and here none did —
// sending an owner to look for something that cannot be there is the same wrong
// explanation in a friendlier register.
const ASK_REFUSED_UNRUN =
  "You stopped waiting for that answer, so this browser is no longer listening for it. " +
  "The gateway refused that question before the assistant was reached, so no turn ran " +
  "and there is nothing to look for — though this browser stopped before reading which " +
  "refusal it was. Nothing was re-sent and nothing was cancelled. Asking again is a " +
  "fresh question, and worth trying once whatever the gateway refused it for has passed.";

// The same act where the status says the assistant was reached and said no.
//
// **It points at no listing and denies none either.** A declined turn produced no answer
// to record, so promising the conversations listing would be `WHERE_TO_LOOK` used where
// it is not true; but a decline is the hub's own act and this page did not read what it
// said about it, so declaring there is nothing to find would be asserting a state it has
// not read — the rule this file keeps everywhere (ADR-0177 §7). Saying neither is the
// accurate option, and the missing sentence is what an unread reason costs.
const ASK_REFUSED_DECLINED =
  "You stopped waiting for that answer, so this browser is no longer listening for it. " +
  "The assistant did receive that question and declined it, so no answer was produced — " +
  "and this browser stopped before reading the reason it gave. " +
  "Nothing was re-sent and nothing was cancelled — the assistant was not told to stop. " +
  "Asking again asks a new question rather than retrying that one.";

// Which of the three a refusal head earns, and the whole enumeration in one place.
// `401` and `409` never arrive here — the re-entry branch above takes them, because
// ADR-0182 §6 gives them a remedy as well as a sentence.
function refusalAbandoned(status) {
  if (status === DECLINED_BY_THE_ASSISTANT) {
    return ASK_REFUSED_DECLINED;
  }
  if (RELAY_FAULT_STATUS.has(status)) {
    return ASK_REFUSED_UNREAD;
  }
  return ASK_REFUSED_UNRUN;
}

// The control, and the line beside it. Built here rather than shipped in `index.html`
// because it belongs to a request and not to the surface — the page already builds a
// fault's Dismiss (`offerDismiss`), a park's pair (`offerApproval`) and the credential
// field this way — and because the sheet reaches it wherever it is created: `button` is
// the one rule every control on this page comes through, so the 44px touch floor and
// the `max-width: 100%` that keeps a long label inside a phone's width are not this
// function's to remember.
function offerStopWaiting() {
  const said = document.createElement("p");
  said.className = "hint";
  said.id = "ask-state";
  said.hidden = true;
  const stop = document.createElement("button");
  // Inside the ask form, where a button with no type is a submit button — which would
  // ask the question again, on the one control whose entire purpose is that it sends
  // nothing (ADR-0182 §7's fifth clause).
  stop.type = "button";
  stop.id = "stop-waiting";
  stop.textContent = "Stop waiting";
  stop.hidden = true;
  stop.addEventListener("click", abandonAsk);
  const form = el("ask-form");
  form.appendChild(said);
  form.appendChild(stop);
}

// Whether a question is out, said and offered in one place so the sentence and the
// control cannot get out of step with each other.
function askWaiting(is) {
  el("ask-state").textContent = is ? ASKING : "";
  el("ask-state").hidden = !is;
  el("stop-waiting").hidden = !is;
}

// The control handed back and the wait ended, whatever ended it. This is the invariant
// #1500 is about: it runs on every exit an ask has, the ones that never settle
// included, and it is the only thing that re-enables the button.
function releaseAsk() {
  awaited = null;
  askWaiting(false);
  el("ask-button").disabled = false;
}

// The owner's act, and the only thing on this page that ends a turn's wait early.
//
// **It aborts and it announces, and it sends nothing.** The abort is what makes the
// pending `fetch` settle, so the promise this page is waiting on stops being one that
// never resolves; the sentence is what keeps the restored control from reading as an
// act that finished. A control that quietly re-ran the question would be the silent
// retry ADR-0168 §9 forbids wearing a button's clothes — `offerDismiss` says the same
// of itself, one surface over.
function abandonAsk() {
  const waiting = awaited;
  if (waiting === null) {
    return;
  }
  // Released before the abort, so the rejection it provokes finds this ask already
  // settled and `ask`'s own `finally` leaves the control alone.
  releaseAsk();
  waiting.stopping.abort();
  // **A refusal the head already named is not an unknown outcome, and re-entry is what
  // it means.** Taken before everything below, because everything below is the wording
  // and the tidying of a wait whose outcome nobody read — and this is a wait whose
  // outcome was read off the status line before the body ever stalled.
  const ended = SESSION_LOST_STATUS.get(waiting.refusedWith);
  if (ended !== undefined) {
    const named = { fault: ended };
    // The screen a refusal read to the end leaves, left the same way by a refusal whose
    // body the owner stopped reading: both turn entries hide the answer panel before
    // reporting one, and this is the same refusal reported through a different door.
    show("answer", false);
    sessionLost(named, `${describe(named, waiting.refusedWith)} ${REFUSED_AT_THE_DOOR}`);
    return;
  }
  // **Every other refusal head, which is a reply this browser read and did not
  // understand.** It is not re-entry — nothing about the session ended — so the control
  // simply comes back, with the two things the status does say and without the sentence
  // below, whose opening clause a refusal head makes false.
  if (waiting.refusedWith !== null) {
    // The screen an ordinary refusal leaves, for the reason the branch above leaves it.
    show("answer", false);
    fault(refusalAbandoned(waiting.refusedWith), "console");
    return;
  }
  // **The partial text goes with it, and nothing else does.** ADR-0173 §3 makes the
  // terminal outcome's `reply` the answer, so an accumulated chunk sequence is not "the
  // record of what the assistant said" and leaving it on screen renders a non-answer as
  // one; there is nothing to be done with it either way, since ADR-0175 §10 declines
  // resuming a cut stream and this one was not even cut, it was let go.
  //
  // **Only where the panel is still this turn's**, which is a question about now and
  // not about the past — the two rounds of adversarial review that found this are two
  // instances of one mistake. An owner who asks a second question and stops waiting
  // before its head lands still has the *first* question's answer on screen; an owner
  // who answers a park while this turn is out has that park's outcome on screen, put
  // there by `renderOutcome`. In both cases clearing would destroy a complete answer
  // because a later request failed. The composing node answers it without bookkeeping:
  // it is in the document exactly while the panel is still this turn's.
  const mine = waiting.composing !== null && waiting.composing.isConnected;
  if (mine) {
    clearNode(el("answer-body"));
    show("answer", false);
  }
  // Which sentence is which fact, and the clause about the screen is added only where
  // there was text on it: a stream abandoned between its head and its first chunk holds
  // an empty node, and clearing that is not something to announce.
  const said = waiting.heard ? ASK_ABANDONED_MIDWAY : ASK_ABANDONED;
  fault(mine && waiting.heard ? `${said} ${PARTIAL_CLEARED}` : said, "console");
}

async function ask(event) {
  event.preventDefault();
  fault(null, "console");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const button = el("ask-button");
  button.disabled = true;
  // Read before the request goes out, so that what is compared on the way back is the
  // selection this turn was sent under and not the one it is landing into.
  const chosenAt = chose;
  // The record of this one ask: what can stop it, and what has been observed of it.
  // Every observation starts empty and is set only by its own evidence arriving.
  const waiting = {
    stopping: new AbortController(),
    heard: false,
    composing: null,
    refusedWith: null,
  };
  awaited = waiting;
  askWaiting(true);
  try {
    const asked = { utterance: el("utterance").value };
    if (conversationId !== null) {
      asked.conversation_id = conversationId;
    }
    // **Which entry is the owner's choice, and the gateway never chooses between
    // them** (ADR-0175 §3). ADR-0173 §5 makes a provider that cannot stream a
    // `ModelError` before any delta, degrading to no answer at all — so on such a
    // build every streamed turn answers nothing while the CLI on the same machine
    // answers normally. The non-streaming entry is the path that still works, and
    // it is here rather than reached for automatically because a silent fallback is
    // forbidden twice over: ADR-0168 §9 has the gateway not retry silently, and
    // ADR-0173 §7 refuses the same fallback one layer in. A second attempt is the
    // owner asking again, visibly.
    if (el("stream-answer").checked) {
      await askStreaming(half, asked, chosenAt, waiting);
    } else {
      await askWhole(half, asked, chosenAt, waiting);
    }
  } catch (_) {
    // An abort this owner asked for is not the gateway having gone, and saying it was
    // would be a wrong explanation rather than a missing one — `readDeliveries`' own
    // catch keeps the same distinction. `abandonAsk` has already said what happened, in
    // the one place that knows it was an act rather than a failure, so this branch
    // stays silent for it. Whatever the abort provoked lands here — the `fetch`
    // rejecting, the stream's reader erroring, a body half-read — and one check covers
    // them all, because what makes them one condition is the signal and not the throw.
    if (!waiting.stopping.signal.aborted) {
      // `fetch` rejects when the connection itself failed — the gateway is gone,
      // which is a different fault from the hub being gone and is said as one.
      show("answer", false);
      fault(GATEWAY_GONE, "console");
    }
  } finally {
    // **Only while this ask is still the one being waited on.** An owner who stopped
    // waiting and then asked afresh leaves this promise to settle *after* the next
    // question has taken the control, and a `finally` that re-enabled the button then
    // would hand it back in the middle of a live turn — and hide that turn's own way
    // out. The comparison is against the controller rather than a flag, so it is the
    // identity of the ask that decides it.
    if (awaited === waiting) {
      releaseAsk();
    }
  }
}

async function askWhole(half, asked, chosenAt, waiting) {
  const response = await fetch("/ask", {
    method: "POST",
    headers: admitted(half, true),
    body: JSON.stringify(asked),
    signal: waiting.stopping.signal,
  });
  // **A successful head on this entry is proof the turn ran**, which is why it is the
  // evidence here and the head of `/ask/stream` is not: `_ask` awaits `converse` and
  // answers with the outcome, so a `200` cannot come back until the assistant has
  // finished with the question. The status is carried in the head, so this is known
  // before the body — which is the read an abort lands in.
  //
  // **A refusal is not proof of anything**, and adversarial review found round 1's fix
  // treating it as some: an expired session, a malformed payload or the connection
  // ceiling is answered by `_check_door` or `_session_bound` *before* `_assistant` is
  // reached, so a refusal head whose body then stalls says only that the gateway
  // replied. Announcing that the assistant had begun on the question there would be
  // exactly the inaccuracy this pair of sentences exists to avoid.
  //
  // **What a refusal head is proof of is itself**, and that is worth keeping rather than
  // discarding: two of the statuses name their condition on their own, and a wait
  // stopped during the stalled body is announced from the status rather than from the
  // body that never arrived (`SESSION_LOST_STATUS`, `abandonAsk`).
  if (response.ok) {
    waiting.heard = true;
  } else {
    waiting.refusedWith = response.status;
  }
  const body = await readBody(response);
  // **A body abandoned part-way through is not a body this page can read**, and
  // `readBody` cannot tell the difference: it answers anything unreadable with an empty
  // object, which is the right rule for a body the gateway wrote badly and the wrong
  // one for a read the owner stopped. Rendering `{}` here would put an answer-shaped
  // nothing on screen for a turn whose outcome is not known; reporting it as a refusal
  // below would be worse. The owner has already been told what happened.
  if (waiting.stopping.signal.aborted) {
    return;
  }
  if (response.ok) {
    renderOutcome(body.outcome, chosenAt);
    return;
  }
  show("answer", false);
  conversationLost(body, asked.conversation_id);
  refused("console", body, response.status);
}

// One streamed turn (ADR-0175 §3): zero or more chunk values, then one terminal
// value carrying the outcome or the fault the exchange ended in.
//
// **The terminal outcome is the answer** (ADR-0173 §3). The chunks are rendered as
// they arrive so the owner sees the answer being written, and `renderOutcome` then
// clears the panel and renders the outcome's own `reply` — so where a rendered chunk
// sequence and the terminal reply disagree, what stands is the terminal reply. No
// accumulated chunk sequence is kept, and none is treated as the record of what the
// assistant said.
async function askStreaming(half, asked, chosenAt, waiting) {
  const response = await fetch("/ask/stream", {
    method: "POST",
    headers: admitted(half, true),
    body: JSON.stringify(asked),
    signal: waiting.stopping.signal,
  });
  if (!response.ok) {
    // Recorded before the body is touched, and for `askWhole`'s reason: the head is what
    // survives a body that stalls, and for two statuses it names the condition on its
    // own. This entry's head proves nothing about the *assistant* — `_write_stream`
    // drains it before `_pump_answer` is awaited — but that argument is about a
    // successful head, and a refusal never reaches `_write_stream` at all.
    waiting.refusedWith = response.status;
    const body = await readBody(response);
    // `askWhole`'s reason, on the one path here that reads a body rather than a stream:
    // a refusal whose body the owner stopped reading is not a refusal this page can
    // put into words, and it has already said what it did.
    if (waiting.stopping.signal.aborted) {
      return;
    }
    show("answer", false);
    conversationLost(body, asked.conversation_id);
    refused("console", body, response.status);
    return;
  }
  const panel = el("answer-body");
  clearNode(panel);
  show("answer", true);
  const composing = line(panel, "", "reply");
  // The node this turn composes into, kept so that abandoning it can ask whether the
  // panel is *still* this turn's rather than whether it ever was. The head alone says
  // nothing about the assistant — the gateway writes and drains it *before*
  // `_pump_answer` is awaited — so it takes the panel and nothing more.
  waiting.composing = composing;
  let terminal = null;
  for await (const value of streamValues(response)) {
    if (value.kind === "chunk") {
      // The first chunk is what proves the question reached the assistant on this
      // entry, and it is the fact a wait abandoned from here is announced with.
      waiting.heard = true;
      composing.textContent += value.text;
    } else if (TERMINAL_KINDS.has(value.kind)) {
      terminal = value;
      break;
    }
    // A kind this page does not know is ignored rather than guessed at. The
    // enumeration is closed and the gateway ships with this file, so meeting one
    // means the two halves of one distribution disagree (ADR-0168 §10).
  }
  if (terminal === null) {
    // **The partial text is cleared rather than left under the fault.** A body that
    // ended without a terminal value is a transport failure and not an answer
    // (ADR-0175 §2), and ADR-0173 §3 makes the terminal outcome's `reply` the answer
    // — "no front end treats an accumulated chunk sequence as the record of what the
    // assistant said". Leaving the chunks on screen renders a non-answer exactly as
    // ADR-0173 §6's fourth shape is rendered: an answer owed and *partly* produced,
    // which arrives as a terminal outcome carrying `reply_degraded` and is said to be
    // incomplete in the same breath. Losing that distinction is what this renderer
    // spends its `renderReply` branch preventing, and a cut stream is not that shape.
    //
    // The alternative — label the text unmistakably as partial — was declined for the
    // same reason: it would give a transport failure the wording of an answer the
    // assistant did produce, and there is nothing to be done with the text either way.
    // ADR-0175 §10 declines resuming an interrupted stream (#1314), so the whole of
    // the recovery is asking again — and **ADR-0182 §7** states this outcome in terms:
    // a cut answer stream "is not resumed and its partial text is not left standing as
    // an answer". Not merged at the time of writing; it ratifies the choice rather
    // than prompting it.
    clearNode(panel);
    show("answer", false);
    fault(ANSWER_STREAM_CUT, "console");
    return;
  }
  if (terminal.kind === "fault") {
    show("answer", false);
    conversationLost(terminal, asked.conversation_id);
    refused("console", terminal, response.status);
    return;
  }
  renderOutcome(terminal.outcome, chosenAt);
}

// --- push to talk (ADR-0200 §10) ---------------------------------------------
//
// **This page runs no speech engine.** It records with `MediaRecorder` and plays what
// the hub sent back, and it calls neither `SpeechRecognition` nor `speechSynthesis` —
// §10 forbids both by name, and `test_bundle.py` asserts the shipped script mentions
// neither. Recognition here would make the edge decide what a submission means
// (ADR-0094 §6, §7); synthesis here would speak text the hub's disclosure ruling never
// saw (ADR-0199), which is the failure milestone 19's exit test is written to catch.
//
// **One request, answered whole.** The press ends before the request begins, so there
// is nothing to stream: the recording goes up complete and the rendering comes back on
// that request's response. No socket, no upgrade, no `EventSource`, no chunked upload
// (ADR-0175 §1).
//
// **And it is a third entry, never a fallback from either other one** (ADR-0168 §9,
// ADR-0200 §10). A spoken turn that fails is a spoken turn that failed; the typed form
// is above it and the owner uses it or does not.

// The container-and-codec members `SpokenAudioFormat` carries, in this page's own
// preference order. Two facts are read off it and they are different questions: what
// this browser can *encode* decides what is recorded, and what it can *decode* is what
// `plays` tells the hub. A browser can be able to do one and not the other.
//
// Spelled as the enum's own values, parameters included, because that is what crosses:
// `audio/webm` alone names a container two codecs can fill, and `MediaRecorder` wants
// the codec named.
const TALK_FORMATS = ["audio/webm;codecs=opus", "audio/mp4"];

// **The bitrate this page asks its encoder for**, and the reason it asks at all.
// ADR-0200 §6's own arithmetic is written against it — "512 KiB is about three minutes
// of speech at a 24 kbit/s Opus bitrate" — and a `MediaRecorder` given no figure picks
// its own, which on some browsers is five times that. A page taking the default would
// hit `hub_max_spoken_audio_bytes` in half a minute where the ADR's arithmetic says
// three, and would do it silently: the refusal is the gateway's, and the ceiling it
// names says nothing about the bitrate that reached it. It is a hint rather than a
// setting — an encoder may honour it approximately or not at all — which is exactly why
// the bound below is on the *press* and not on this.
const TALK_BITS_A_SECOND = 24000;

// **The most this page will hold of one recording.** A press with no bound accumulates
// for as long as a finger is down, and nothing discovers it until the upload — where the
// answer is a size refusal after the owner has spoken for minutes. Adversarial review
// found the class in round 3.
//
// **A bound on what this page holds, and not a copy of a bound that refuses.**
// `hub_max_spoken_audio_bytes` and `gateway_max_request_bytes` are the hub's and the
// gateway's, this page is told neither, and a guess at either here would be a second
// place a figure lives with nothing keeping the two in step. What is chosen here is a
// browser-memory question, which is this page's own — and it is chosen to sit inside
// ADR-0200 §6's *default* arithmetic rather than to reproduce it: 384 KiB of audio is
// under §6's 512 KiB default and its base64 is under `gateway_max_request_bytes`' 1 MiB
// default with room for the head. Where an operator has set either lower, their refusal
// still governs and is reported as itself.
//
// **It is asked before a chunk is kept, so what is held never exceeds it** — not by one
// slice, not by a final chunk arriving after the release, and not by a browser that
// hands over one very large block instead of the slices it was asked for. Asking about
// the *prospective* total rather than the running one answers all three with one
// comparison.
//
// **And a press that crosses it sends nothing at all**, which is the second half and the
// one two rounds of review arrived at together. A recording is a container, and its last
// chunk is where a `MediaRecorder` writes what finishes one; keeping the chunks before it
// and uploading them is uploading a clip that may not decode — so the hub would be handed
// something it cannot read, having been told the recording was sent. There is no
// container-aware middle: this page does not parse WebM or MP4 and must not learn to.
// Discarding is also the honest reading of what happened — the question ran past what
// this page will hold, so there is no complete question to ask — and at this size it is a
// runaway press rather than an ordinary one: two minutes of speech at the bitrate below.
//
// **And it is not a clock.** ADR-0182 §7 makes an owner's wait the owner's to end, and
// this file keeps exactly one `setTimeout` for that reason — a page-side deadline over a
// request would abandon a healthy turn and announce that its outcome was not known. This
// bounds a *recording*, before any request exists and with no turn to be wrong about;
// what measures it is the recorder handing over what it has, not a timer.
const LONGEST_RECORDING_BYTES = 384 * 1024;

// How often the recorder hands over what it has. Without an argument `MediaRecorder`
// delivers everything once, at `stop` — which is exactly too late to bound anything, and
// is why this figure exists rather than a clock.
const RECORDING_SLICE_MILLISECONDS = 1000;

const LISTENING = "Listening — let go when you have finished.";
const SENDING = "Sending what you said…";

// **Disabled and explained, rather than absent** (ADR-0200 §10, ADR-0202). A browser
// withholds a microphone from a page whose origin it does not consider trustworthy,
// and it gives no legible account of why — so a control that simply was not there
// would leave an owner with nothing to act on. The two origins that work are named,
// because naming them is the whole remedy.
const NO_MICROPHONE =
  "This browser will not hand this page a microphone. That is a property of the " +
  "origin rather than of the assistant: a microphone is offered on the gateway's own " +
  "machine at its http://127.0.0.1 address, and on another device at the https:// " +
  "address docs/guide/phone.md sets up. Typing works everywhere.";

// The two ways `getUserMedia` says no that an owner can do something about, and a
// third for everything else. Read off the error's `name`, which is the one member the
// specification fixes — its `message` is the browser's own prose and differs between
// them.
const MICROPHONE_DENIED =
  "This browser did not give the page the microphone. Nothing was recorded and " +
  "nothing was sent. The permission is the browser's, not the assistant's: allow the " +
  "microphone for this site and hold the button again.";
const NO_MICROPHONE_DEVICE =
  "This device has no microphone the browser will offer. Nothing was recorded and " +
  "nothing was sent.";
const MICROPHONE_UNAVAILABLE =
  "The microphone could not be opened, so nothing was recorded and nothing was sent. " +
  "Something else may be holding it.";

// The recorder refusing what the microphone gave it, which is a **third** condition and
// not either of the two above: the browser handed the page a track and then would not
// encode it. Found by driving the page — a `MediaRecorder` handed a track that had
// already ended throws `NotSupportedError` out of `start`, and without the guard below
// that throw escaped `startTalking` and left the control saying "Listening" with no
// press it would ever accept again.
//
// **It advises what is known, and a retry is not it** (#1694). The milestone-19 QA run
// met this line in a build whose refusal is *permanent* — `chromium_headless_shell`,
// which recognises both formats and has an encoder for neither — where "holding the
// button again is the thing to try" is advice an owner follows several times before
// giving up. Nothing here can tell that browser from the transient case: `start()`
// throws the same `NotSupportedError` for a track that has just ended and for a build
// that will never encode anything. So the sentence says which two conditions it cannot
// distinguish, and offers the one route that works under either.
const RECORDER_REFUSED =
  "This browser would not start recording, so nothing was recorded and nothing was " +
  "sent. The microphone was opened and the recorder would not take it. Whether that " +
  "was this press or is this browser, the page cannot tell: pressing again may work, " +
  "and a browser with no encoder for either format this page records refuses every " +
  "press the same way. Typing works either way.";

// The press that reached :data:`LONGEST_RECORDING_BYTES`. Said rather than silent,
// because a recording that stopped while the owner was still speaking is a question with
// its end missing, and an owner who is not told will read the answer as the assistant
// having misunderstood them. **Stopped and sent, not stopped and discarded**: what they
// said up to here is a real question, and throwing it away to enforce a bound this page
// chose would cost them the whole press.
const RECORDING_TOO_LONG =
  "That press ran past the longest recording this page holds, so it was stopped and " +
  "nothing was sent: a recording cut off part-way through is not one the assistant can " +
  "read, and sending it would ask a question this browser had already broken. Hold the " +
  "button for a shorter question, ask it in parts, or type it.";

// A press that produced no bytes at all — a tap rather than a hold, or a recorder that
// was stopped before it had written anything. Said rather than sent: an empty
// recording is not a question, and posting one would spend a turn to be told so.
const NOTHING_RECORDED =
  "That press was too short to record anything, so nothing was sent. Hold the button " +
  "down while you speak, and let go when you have finished.";

// ADR-0200 §4's no-words shape, which is **not** an error: "nothing was asked, so
// nothing was answered, no turn ran, no episode was captured and no conversation was
// created". So it is said in the page's own hint rather than in the fault surface,
// where it would teach an owner that a quiet room is something going wrong.
const HEARD_NOTHING =
  "I heard nothing in that recording, so nothing was asked and nothing was answered.";

// ADR-0200 §4's fourth degradation: an answer existed and speaking it did not
// complete. **A statement rather than a fault**, for ADR-0170 §6's reason applied one
// stage further on — the answer is on screen and is the whole of what was said, so
// what is missing is the audio and nothing else.
const NOT_SPOKEN =
  "That answer is shown here and was not spoken: composing it worked and rendering it " +
  "as speech did not. Nothing of the answer is missing — what is above is all of it.";

// The rendering arrived and this browser could not play it. Distinct from the line
// above, and the difference is where the failure was: the hub rendered speech and sent
// it, and it is this browser that could not turn it back into sound.
const COULD_NOT_PLAY =
  "That answer was spoken and this browser could not play the audio. The answer above " +
  "is the same words, complete.";

// The press that ended an answer's playback (#1696). Said rather than silent, because an
// answer that stopped sounding part-way through is otherwise indistinguishable from one
// that finished: the words stay on screen either way, so an owner who is not told will
// read the truncation as the whole of what was spoken aloud.
//
// **A statement and not a fault**, for `NOT_SPOKEN`'s reason — the interruption is the
// owner's own act and the answer above it is complete, so what it reports is where the
// sound stopped and nothing more.
const PLAYBACK_INTERRUPTED =
  "You pressed to talk, so this answer stopped being spoken. Nothing of the answer is " +
  "missing — what is above is all of it.";

// The press that ended a playback and then asked nothing (#1701, the owner's direction
// of 2026-08-28). Written into the slot the sentence above was written into, because it
// **replaces** it: an answer that picked up where it stopped did not stop being spoken,
// and leaving the earlier sentence standing would be the page's account of the sound
// disagreeing with the sound.
const PLAYBACK_RESUMED =
  "That press asked nothing, so this answer picked up where the sound stopped. It is " +
  "the same answer, played on from there rather than started again — nothing was " +
  "re-asked and no new turn ran.";

// What stopping a spoken wait says. #1500's condition on the third entry, and the
// wording is `ASK_ABANDONED`'s because the state is the same one: the request went out
// and no response was read, so the turn may have run and was certainly never called
// back. It is **not** `ASK_ABANDONED_MIDWAY` — a spoken turn streams nothing, so there
// is no partial reply this browser could have read.
const SPOKEN_ABANDONED =
  "You stopped waiting for that answer, so this browser is no longer listening for it. " +
  "What became of the turn is not known: the recording was sent and nothing here read a " +
  "reply, so the assistant may have carried it out and may never have received it. " +
  "Nothing was re-sent and nothing was cancelled — the assistant was not told to stop. " +
  "Holding the button again asks a new question rather than retrying that one. " +
  WHERE_TO_LOOK;

// **One audio context for the page, built and resumed inside the press.**
//
// Adversarial review found the fix for a defect this replaces: a context created after
// the upload had settled is created *outside* the gesture that led to it, and a browser
// enforcing transient activation for Web Audio starts it suspended and refuses the
// `resume` — so a perfectly good rendering came back and was reported as one this
// browser could not play. That is not a hypothetical on the browser milestone 19's exit
// test names: WebKit's rule is the strict one, and the exit test is a phone.
//
// So it is built where the activation is: `startTalking` runs inside the `pointerdown`
// or `keydown` handler, and `readyToPlay` is its first act, before any `await`. It is
// then held for the life of the page rather than closed after a rendering, because
// closing it would put the next playback back outside a gesture — which is the defect.
let listeningContext = null;

// The resume the press started, or `null` where no resume was owed. **Held rather than
// dropped** (#1690): a `resume()` whose promise nobody observes is a failure nobody hears
// about, and the caller that needs the answer is `playSpoken`, one `await` later.
let resuming = null;

function readyToPlay() {
  try {
    if (listeningContext === null) {
      listeningContext = new AudioContext();
    }
    // **Every state that is not `"running"`, rather than `"suspended"` alone** (#1690).
    // `AudioContextState` has a third member some browsers use — `"interrupted"`, which
    // is where WebKit puts a context when a call arrives or another application takes
    // the audio session — and a context left in it fails silently in *both* directions:
    // `decodeAudioData` still succeeds, `start()` produces no sound, and nothing throws,
    // so the notice saying the audio was lost is never reached either. Which is the
    // worst of the three outcomes: an answer the page believes it spoke.
    if (listeningContext.state !== "running") {
      resuming = Promise.resolve(listeningContext.resume());
      // Observed here as well as awaited there, because a press need not produce a
      // spoken answer at all — a rejection nothing is waiting on is an unhandled
      // rejection in the console, which is noise this page does not make. Attaching a
      // handler does not consume the rejection: the `await` in `playSpoken` still sees
      // it, and still says so.
      void resuming.catch(() => {});
    }
  } catch (_) {
    // A browser with no Web Audio at all. The recording still goes up and the answer is
    // still shown and read; what is lost is hearing it, which `playSpoken` says.
    listeningContext = null;
    resuming = null;
  }
}

// **The playback this page has in the air**, or `null` when nothing is sounding and
// nothing is on its way to sounding. A record rather than the source itself, because the
// interrupt has to reach a playback that has no source yet: `playSpoken` awaits a resume
// and a decoder before it has anything to stop, and a press landing in that window must
// leave nothing behind that will start afterwards.
//
// **What a record carries**, beside the source and the slot the notices go into: the
// decoded `buffer`, the `offset` into it the current source started at, the audio
// context's `startedAt` instant it started on, and `played` — where the sound had
// reached when the playback ended, stamped by whichever ending got there. Together they
// answer "how much of this answer sounded" from the record alone, which is what
// `playedSoFar` reads and what #1705 needs answered in the window a second `ended`
// listener cannot reach.
//
// **And two names, so the report has a subject** (ADR-0205 §1, §7): `episode`, the
// `episode_id` the response carrying this rendering disclosed, and `conversation`, the
// conversation that response named. Both are carried on the record rather than read off
// the page's current selection when the playback ends, because by then the owner may
// have chosen another conversation — and a report is about the turn it names, which is
// a fact settled when the answer arrived and not when the sound stopped.
let playing = null;

// **The playback a press ended that may turn out to have been an accident** (#1701), or
// `null` where there is none. Held from the press until the answer to it comes back,
// because whether the press asked anything is not known until then: ADR-0200 §4's
// no-words release is the one ending that resumes it, and every other ending drops it —
// which `interruptPlayback` does at the top of every press, before anything decides to
// keep one.
let held = null;

// **The report the next spoken request carries**, or `null` where this page holds
// none (ADR-0205 §7). It says how much of one earlier answer this device played, and
// it names that answer by the `episode_id` the response carrying it disclosed — never
// by a position, an ordinal or anything this page counted, which is what makes a
// report that arrives after another turn has been captured land on the turn it is
// actually about rather than on whichever turn is newest.
//
// **Written where a playback ends and nowhere else**: `soundFrom`'s `ended` listener
// for a source that ran to its end, and `interruptPlayback` for one a press cut short.
// Both readings come off the record `stopPlaying` stamps, so there is one arithmetic
// for "how much sounded" and not two.
//
// **Held rather than sent at once.** There is no route for it and ADR-0205 §1 declines
// to add one: the fact's only reader is the composing stage of the *next* turn, so it
// rides the request that turn already makes. The honest cost is the owner who
// interrupts and never speaks again — that report is never sent and the hub's record
// stays `UNKNOWN`, which is the correct account of it rather than a gap.
let pendingDelivery = null;

// **A press is an interrupt** (#1696, the owner's ruling of 2026-08-28, from a real
// iPhone). Pressing to talk over an answer that is still being spoken is the same act as
// speaking over a person: it ends what was being said. Two things made it necessary, and
// either alone would have — the page opens the microphone into a room its own
// loudspeaker is filling, so the recording hears the assistant's own voice; and an owner
// who had read the answer had no way to stop it short of leaving the page.
//
// **It reaches the decode as well as the source.** Stopping only a live
// `AudioBufferSourceNode` would leave a rendering whose decode was still pending to
// start a moment later — the same defect one beat on, and the harder one to see.
//
// **And it is the activation's, not the recording's.** It runs before every one of
// `startTalking`'s guards, so a press that goes on to record nothing still stops the
// sound: what the owner asked for by pressing is the silence, and a page that gave it to
// them only on the presses that happened to record would be answering a different act.
function interruptPlayback() {
  const ended = stopPlaying();
  // **Dropped on every press, before anything decides to keep one.** What `held` names
  // is this press's playback or it is nothing: a press that goes on to ask a question,
  // or that never reaches a recorder at all, must not leave a buffer behind for some
  // later press's silence to resume.
  held = null;
  if (ended === null) {
    return;
  }
  // **A playback that had already elapsed was not interrupted** (#1705). `ended` is a
  // queued task and not a synchronous callback, so a source that reached its natural end
  // still names itself in `playing` for the moments between the two — and a press
  // landing there found a record, stopped a source that had already finished, and wrote
  // "this answer stopped being spoken" under an answer that had been heard in full. The
  // sentence was wrong about a few milliseconds of the world, which is a small thing to
  // be wrong about and the page's own account of the sound to be wrong in.
  //
  // Decided from where the sound had reached, which `stopPlaying` has just stamped, and
  // not from a second listener: the whole of the window is *before* the queued one runs.
  if (playbackElapsed(ended)) {
    // It played out, so that is what is reported — the press is not what ended it
    // (ADR-0205 §7). The `ended` listener cannot do it here: `stopPlaying` has already
    // cleared the record, so the queued task finds `playing !== mine` and returns.
    reportDelivery(ended, "complete");
    return;
  }
  reportDelivery(ended, "interrupted");
  playbackInterrupted(ended.slot);
  // Kept for the release that turns out to have asked nothing (#1701). Nothing here
  // resumes it — this runs inside the press, and whether that press was an accident is
  // not known until its answer comes back.
  held = ended;
}

// End whatever is in the air, let go of the record, and hand back what it named — or
// `null` where there was nothing. **It says nothing of its own**, because what is owed
// depends on *why* the playback ended and only the caller knows that: a press is an
// interruption the owner is told about, and an answer taking the record over is not.
function stopPlaying() {
  const mine = playing;
  if (mine === null) {
    return null;
  }
  // Cleared first, so a decode this overtook finds the record already gone and starts
  // nothing — see `playSpoken`, where that comparison is made.
  playing = null;
  // **Where the sound had reached, stamped before the source is stopped.** After `stop()`
  // there is no clock left to read it from, and both callers that need it run afterwards:
  // the notice this ending may owe (#1705) and the resume that may follow it (#1701).
  mine.played = playedSoFar(mine);
  if (mine.source !== null) {
    try {
      mine.source.stop();
    } catch (_) {
      // A source that has already finished. Stopping one is not a failure worth
      // reporting to anybody: what this asked for is what is already true.
    }
    mine.source = null;
  }
  return mine;
}

// How much of a playback's buffer has sounded, in seconds: what was already behind its
// source when that source started, plus what the audio context's clock has advanced
// since.
//
// **The context's clock and not the page's.** `currentTime` advances with the audio the
// context is playing, so a context the browser suspended part-way through accrues no
// playback nobody heard — which a wall clock would. Clamped to the buffer, because a
// source that has run past its end goes on advancing `currentTime` and what is being
// asked about is the answer and not the clock.
//
// **One value whatever ended the playback, and one across a resume.** A resumed playback
// starts with the interrupted one's reading as its `offset` (#1701), so an answer taken
// up again and allowed to finish reads as the whole buffer rather than as the remainder
// — which is what "played N of M s" has to mean for the report ADR-0205 §7 defines to be
// able to say `COMPLETE` of it.
function playedSoFar(mine) {
  if (mine.buffer === null) {
    return 0;
  }
  if (mine.source === null || listeningContext === null) {
    return mine.offset;
  }
  const sounded = mine.offset + (listeningContext.currentTime - mine.startedAt);
  return Math.min(Math.max(sounded, 0), mine.buffer.duration);
}

// Whether a playback reached the end of its buffer, read off the two values its record
// carries. **Answerable in the window a second `ended` listener cannot reach** (#1705):
// the whole of that window is between the natural end and the queued task, so what
// decides it has to be arithmetic over the clock rather than another event.
//
// A record with no buffer has not elapsed and cannot have: it is a playback whose decode
// the press overtook, which never sounded at all and is an interruption exactly as one
// cut off mid-sentence is.
function playbackElapsed(mine) {
  return mine.buffer !== null && mine.played >= mine.buffer.duration;
}

// **Record what this device played of one answer, for the next request to carry**
// (ADR-0205 §7). `state` is `"complete"` where the source ended of its own accord and
// `"interrupted"` where a press ended it — a distinction this page already draws, and
// one it never invents: nothing here guesses at a state from a duration.
//
// **Reported only where there is a pair to report**: an answer this page holds an
// `episode_id` for, in a conversation the hub named, whose buffer it actually decoded.
// A playback whose decode a press overtook has no measurement to report and produces
// no report at all, which ADR-0205 §3 names as the ordinary case rather than a gap —
// and a turn nobody reports on stays `UNKNOWN`, which is the true account of it.
//
// **The durations are whole microseconds**, `timedelta`'s own resolution and the
// spelling this gateway reads every duration in. Where the two round to the same
// microsecond the report is `complete`: ADR-0205 §2 makes equality the definition of
// having played the answer out, and a difference below a microsecond is not a
// difference — sending `interrupted` with two equal numbers would be a value the
// promoted surface refuses, which is the page reporting nothing at all in place of
// reporting a rounding.
function reportDelivery(mine, state) {
  if (mine.episode === null || mine.conversation === null || mine.buffer === null) {
    return;
  }
  const rendered = Math.round(mine.buffer.duration * MICROSECONDS);
  if (!Number.isFinite(rendered) || rendered <= 0) {
    return;
  }
  const played = state === "complete" ? rendered : Math.round(mine.played * MICROSECONDS);
  if (!Number.isFinite(played) || played < 0) {
    return;
  }
  pendingDelivery = {
    conversation: mine.conversation,
    report: {
      episode_id: mine.episode,
      delivery: {
        state: played >= rendered ? "complete" : state,
        played_microseconds: String(Math.min(played, rendered)),
        rendered_microseconds: String(rendered),
      },
    },
  };
}

// The report to send with a request against `conversation`, or `null` (ADR-0205 §7).
//
// **Only where it is about the conversation being sent.** A report names a turn, and
// the hub discards one naming a turn the conversation does not carry — but sending it
// there would be this page asserting a pairing it has no reason to assert, and §7 says
// it reports "the playback it last had in the air **for the conversation it is
// sending**".
//
// **Taken rather than read**: a report that goes out is let go of, so a second press
// does not re-send it. Where it is not about this conversation it is *kept*, because
// the fact stays true and stays this page's last playback — the next request against
// the conversation it names carries it, and the hub applies it to the turn it names
// however many turns have been captured since.
function takeDelivery(conversation) {
  if (pendingDelivery === null || conversation === null) {
    return null;
  }
  if (pendingDelivery.conversation !== conversation) {
    return null;
  }
  const report = pendingDelivery.report;
  pendingDelivery = null;
  return report;
}

// Microseconds in a second, so the two conversions read as arithmetic.
const MICROSECONDS = 1000000;

// The press being served, or `null` between presses.
//
// **A record rather than a flag**, because a release can land before the browser has
// answered the permission prompt: the release marks *that* press abandoned, and the
// code that resumes after the prompt checks that it is still the press it started as
// rather than that some press is in flight.
let press = null;

// What this browser says it can encode, or `null` where it names none of them. Asked of
// `MediaRecorder` rather than assumed from the user agent, which is as close to an
// honest answer as the platform offers.
//
// **It is an answer about recognition and not about encoding** (#1694). The method
// promises only that the type is one the browser *recognises*; it does not promise an
// encoder for it. Driving the page found the gap rather than reasoning to it:
// `chromium_headless_shell` answers `true` for both members of `TALK_FORMATS`, then
// throws `NotSupportedError: no encoder` out of `start()` — on a live track, and
// identically with no options at all. So `start()` is the only real test, which is why
// `startTalking` guards it and says what happened rather than trusting this call.
function recordableFormat() {
  if (typeof window.MediaRecorder !== "function") {
    return null;
  }
  if (typeof MediaRecorder.isTypeSupported !== "function") {
    return null;
  }
  return TALK_FORMATS.find((one) => MediaRecorder.isTypeSupported(one)) ?? null;
}

// What this browser can decode, which is what `plays` says (ADR-0200 §3): "what the
// caller can *render*, not who can *hear*". In preference order, because the hub
// renders in "the **first** member of `plays` that the synthesizer's `formats` property
// also names" — so the order here is a real choice and not a formality.
//
// **The recorded format is the floor.** `canPlayType` answers about the media element's
// decoders and can be empty on a browser that plainly has the codec, since it just
// encoded with it; sending an empty `plays` is refused by the promoted surface, and
// sending nothing at all would silence a turn this browser could have heard.
function playableFormats(recorded) {
  const probe = document.createElement("audio");
  const playable = TALK_FORMATS.filter((one) => probe.canPlayType(one) !== "");
  return playable.length > 0 ? playable : [recorded];
}

// What the page says about the microphone, in one place so the sentence and the
// control cannot get out of step.
function saying(text) {
  el("talk-state").textContent = text;
  el("talk-state").hidden = text === "";
}

// What the hub heard, disclosed on every call that produced a transcript (ADR-0200 §4).
// Inserted as text like every other value the hub returns (ADR-0168 §6): a transcript
// is model output.
function heardWas(text) {
  el("heard").textContent = text === null ? "" : `Heard: ${text}`;
  el("heard").hidden = text === null;
}

// Whether this browser will let the page record at all, decided on load and said on
// screen either way. Three things have to be true and each is a different question:
// the page must be able to *ask* for a microphone, it must have a recorder, and that
// recorder must be able to produce a format this surface carries.
function offerTalk() {
  const button = el("talk-button");
  const usable =
    navigator.mediaDevices !== undefined &&
    typeof navigator.mediaDevices.getUserMedia === "function" &&
    recordableFormat() !== null;
  button.hidden = false;
  button.disabled = !usable;
  el("stop-talking").hidden = true;
  saying(usable ? "" : NO_MICROPHONE);
}

// Which of `getUserMedia`'s refusals this was, from the one member the specification
// fixes. The browser's own `message` is never rendered: it is prose this project did
// not author, and a page that relayed it would be saying something it cannot stand
// behind about a device the owner has to act on.
function microphoneRefused(error) {
  const named = error && typeof error.name === "string" ? error.name : "";
  if (named === "NotAllowedError" || named === "SecurityError") {
    return MICROPHONE_DENIED;
  }
  if (named === "NotFoundError" || named === "OverconstrainedError") {
    return NO_MICROPHONE_DEVICE;
  }
  return MICROPHONE_UNAVAILABLE;
}

// Give the microphone back the moment the recording ends. A track left live is a
// browser still showing the recording indicator over a page that has stopped
// listening, which is a claim about this page that would not be true.
function releaseMicrophone(stream) {
  if (stream === null) {
    return;
  }
  stream.getTracks().forEach((track) => track.stop());
}

async function startTalking() {
  // **First of all, and before the guards**: the owner's press ends the answer that is
  // still being spoken (#1696). See `interruptPlayback` for why it is the activation
  // that carries this rather than the recording that may follow it.
  interruptPlayback();
  const button = el("talk-button");
  if (press !== null || button.disabled) {
    return;
  }
  const format = recordableFormat();
  if (format === null) {
    return;
  }
  // **First, and before any `await`**: this function is running inside the press, and
  // the audio context has to be built where that activation is.
  readyToPlay();
  fault(null, "console");
  heardWas(null);
  const mine = {
    format,
    released: false,
    recorder: null,
    stream: null,
    chunks: [],
    held: 0,
    overran: false,
    stopping: null,
  };
  press = mine;
  saying(LISTENING);
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (refusal) {
    press = null;
    saying("");
    fault(microphoneRefused(refusal), "console");
    return;
  }
  // **The release that landed while the prompt was up.** The owner let go, and what
  // they let go of was this press: the microphone is handed straight back and nothing
  // is recorded or sent. Checking the identity rather than a flag is what keeps a
  // *later* press from being abandoned by an earlier one's release.
  if (press !== mine || mine.released) {
    releaseMicrophone(stream);
    if (press === mine) {
      press = null;
      saying("");
    }
    return;
  }
  mine.stream = stream;
  // **Guarded, because the failure here is the one that wedges the control.** Both the
  // constructor and `start` throw synchronously — an unsupported type at the first, a
  // track the browser will not encode at the second — and an escaping throw would leave
  // this press in flight for the life of the page: `press` stays set, so every later
  // press returns at the top, and the line on screen still says "Listening". The
  // microphone goes back at the same time, because a page that has stopped listening
  // must not leave the browser's recording indicator up.
  let recorder;
  try {
    recorder = new MediaRecorder(stream, {
      mimeType: format,
      audioBitsPerSecond: TALK_BITS_A_SECOND,
    });
  } catch (_) {
    releaseMicrophone(stream);
    press = null;
    saying("");
    fault(RECORDER_REFUSED, "console");
    return;
  }
  mine.recorder = recorder;
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size === 0) {
      return;
    }
    // **The prospective total, before the chunk is kept.** Asking about the running
    // total after appending bounds nothing: the chunk that crosses is already held, and
    // a browser handing over one very large block crosses by as much as that block is.
    // So the chunk that would cross is not kept, and the press ends.
    //
    // **The size check is unconditional and only the stopping is not.** A final chunk
    // arrives *after* the release, when there is no recorder left to stop, and a check
    // that skipped it would leave exactly the unbounded upload this bound exists to
    // prevent. `stopTalking` is the same act the release performs, so it is one ending
    // of the press rather than a second path through it.
    if (mine.held + event.data.size > LONGEST_RECORDING_BYTES) {
      mine.overran = true;
      // Let go of what was kept at the moment it stops being worth keeping, rather than
      // holding a recording nothing will send until the press record is collected.
      mine.chunks = [];
      mine.held = 0;
      fault(RECORDING_TOO_LONG, "console");
      if (!mine.released) {
        stopTalking();
      }
      return;
    }
    mine.chunks.push(event.data);
    mine.held += event.data.size;
  });
  // The upload is hung off `stop` rather than off the release, because the recorder
  // writes its last block as it stops: sending from the release would send a recording
  // missing its own ending.
  recorder.addEventListener("stop", () => {
    void sendRecording(mine);
  });
  try {
    recorder.start(RECORDING_SLICE_MILLISECONDS);
  } catch (_) {
    mine.recorder = null;
    releaseMicrophone(stream);
    press = null;
    saying("");
    fault(RECORDER_REFUSED, "console");
    return;
  }
  // **The release that landed while the recorder was being built.** `stopTalking` marks
  // the press released and stops a recorder only if there is one in `state`
  // `"recording"`, and until this line there was not — so a press let go in that window
  // would record until the page was closed. Taken after `start` rather than before,
  // because a recorder that has not started cannot be stopped, and taken through
  // `stopTalking` rather than around it so the bound above is disarmed with it.
  if (mine.released) {
    stopTalking();
  }
}

function stopTalking() {
  const mine = press;
  if (mine === null) {
    return;
  }
  mine.released = true;
  if (mine.recorder !== null && mine.recorder.state === "recording") {
    mine.recorder.stop();
  }
}

// The control handed back and the press ended, whatever ended it — including the
// endings that never settle, which is why this is a function and not a `finally` body.
// It is the invariant #1500 is about, on the third entry: it runs on every exit a spoken
// turn has, and it is the only thing that re-enables the button.
function releaseTalk() {
  press = null;
  el("talk-button").disabled = false;
  el("stop-talking").hidden = true;
  // **Only the sentences that describe a press still happening.** `NOTHING_RECORDED` and
  // `HEARD_NOTHING` are written on the way out and are the answer rather than a state, so
  // clearing them would take the reply off the screen.
  //
  // `LISTENING` belongs here as well as `SENDING`, which driving the page is what found:
  // a press that ran past `LONGEST_RECORDING_BYTES` never reaches `SENDING`, so a release
  // that cleared only that one left "Listening — let go when you have finished." on
  // screen beside a fault saying the recording had been stopped and the button handed
  // back.
  const said = el("talk-state").textContent;
  if (said === LISTENING || said === SENDING) {
    saying("");
  }
}

// The owner's act, and the only thing that ends a spoken turn's wait early (#1500,
// ADR-0182 §7's fifth clause).
//
// **It aborts and it announces, and it sends nothing.** The abort is what makes the
// pending `fetch` settle, so the promise this page is waiting on stops being one that
// never resolves; the sentence is what keeps the restored control from reading as an act
// that finished. A control that quietly re-recorded would be the silent retry ADR-0168 §9
// forbids wearing a button's clothes — `abandonAsk` says the same of itself one entry
// over, and this is that entry's copy because the two waits are different waits: an owner
// with a question out and a recording out has two things to stop and one control each.
function abandonSpoken() {
  const mine = press;
  if (mine === null || mine.stopping === null) {
    return;
  }
  // Released before the abort, so the rejection it provokes finds this press already
  // settled and `sendRecording`'s own `finally` leaves the control alone.
  releaseTalk();
  mine.stopping.abort();
  show("answer", false);
  fault(SPOKEN_ABANDONED, "console");
}

async function sendRecording(mine) {
  releaseMicrophone(mine.stream);
  const half = headerHalf();
  if (half === null) {
    releaseTalk();
    showBootstrap();
    return;
  }
  const asked = {};
  try {
    // **A press that ran past the bound sends nothing**, and the fault slot has already
    // said so — at the moment it happened, while the owner was still holding the button.
    // Taken before everything below, because everything below is about a recording there
    // is something to do with.
    if (mine.overran) {
      return;
    }
    const recording = new Blob(mine.chunks, { type: mine.format });
    if (recording.size === 0) {
      saying(NOTHING_RECORDED);
      return;
    }
    saying(SENDING);
    el("talk-button").disabled = true;
    // Read before the request goes out, so what is compared on the way back is the
    // selection this turn was sent under and not the one it is landing into — `ask`'s
    // own rule, and the reason is the same on either entry.
    const chosenAt = chose;
    asked.utterance = { content: await base64Of(recording), media_type: mine.format };
    asked.plays = playableFormats(mine.format);
    if (conversationId !== null) {
      asked.conversation_id = conversationId;
    }
    // **The report about the answer this press interrupted, or nothing** (ADR-0205
    // §7). It rides the request this turn already makes: there is no route for it and
    // ADR-0205 §1 declines to add one, because its only reader is the composing stage
    // of the very turn this request is asking for.
    const played = takeDelivery(conversationId);
    if (played !== null) {
      asked.delivery = played;
    }
    // **The way out, armed with nothing awaited between here and the request.**
    // `fetch` carries no deadline of its own, so a socket that dies without settling
    // leaves the `await` below pending for ever and the `finally` never runs: without
    // this the owner's one way into the assistant by voice stays greyed out until the
    // page is reloaded, which is #1500 exactly.
    //
    // **After the encoding rather than before it**, which adversarial review found the
    // second round: `SPOKEN_ABANDONED` says the recording was sent and that the turn may
    // have run, and offering it while the base64 was still being made would have said
    // that of a press no request had yet gone out for. The window is closed rather than
    // given a second sentence, because there is nothing there worth a control — encoding
    // half a megabyte is arithmetic, and it cannot stall the way a socket can.
    mine.stopping = new AbortController();
    el("stop-talking").hidden = false;
    const response = await fetch("/ask/spoken", {
      method: "POST",
      headers: admitted(half, true),
      body: JSON.stringify(asked),
      signal: mine.stopping.signal,
    });
    const body = await readBody(response);
    // **A body abandoned part-way through is not a body this page can read**, and
    // `readBody` cannot tell the difference: it answers anything unreadable with an
    // empty object, which is the right rule for a body the gateway wrote badly and the
    // wrong one for a read the owner stopped. The owner has already been told what
    // happened.
    if (mine.stopping.signal.aborted) {
      return;
    }
    if (!response.ok) {
      show("answer", false);
      conversationLost(body, asked.conversation_id);
      refused("console", body, response.status);
      return;
    }
    renderSpokenTurn(body.turn, chosenAt);
  } catch (_) {
    // An abort this owner asked for is not the gateway having gone, and saying it was
    // would be a wrong explanation rather than a missing one; `abandonSpoken` has
    // already said what happened, in the one place that knows it was an act rather than
    // a failure. Everything else lands here — `fetch` rejecting because the connection
    // itself failed, which is a different fault from the hub being gone and is said as
    // one, exactly as `ask`'s own catch draws the line.
    if (mine.stopping === null || !mine.stopping.signal.aborted) {
      show("answer", false);
      fault(GATEWAY_GONE, "console");
    }
  } finally {
    // **Only while this press is still the one being waited on.** An owner who stopped
    // waiting leaves this promise to settle afterwards, and a `finally` that re-enabled
    // the button then could hand it back in the middle of a later press — and hide that
    // press's own way out. The comparison is against the record rather than a flag, so
    // it is the identity of the press that decides it (`ask`'s own rule).
    if (press === mine) {
      releaseTalk();
    }
  }
}

// The four members of a `SpokenTurn`, each rendered as ADR-0200 §4 describes it.
//
// **The turn inside is rendered by `renderOutcome` and by nothing else.** §4 makes it
// "an ordinary `TurnOutcome`… This call composes a turn; it does not create a second
// kind of one" — so a spoken answer and a typed one are the same rendering, and a
// member added to one reaches both.
function renderSpokenTurn(turn, chosenAt) {
  // §4: "`heard` is `None` **exactly when** `outcome` is `None`, and that pair is the
  // recording that carried no words". Not an error, and said where the page says
  // things about the microphone rather than in the fault surface.
  if (turn.outcome === null) {
    heardWas(null);
    saying(HEARD_NOTHING);
    // The press ended a playback and then asked nothing, which is the accident #1701 is
    // about: the answer that was sounding is still the answer, so it is given back where
    // it stopped rather than left stopped. Here rather than in `sendRecording`, because
    // this is the one place that knows the release carried no words.
    resumeInterrupted();
    return;
  }
  heardWas(turn.heard);
  renderOutcome(turn.outcome, chosenAt);
  if (turn.spoken !== null) {
    // **A place kept by this turn for a notice this turn's playback may owe.**
    // `playSpoken` awaits the decoder, and while it is pending the owner can ask
    // again — `renderOutcome` clears `#answer-body`, so a rejection landing after that
    // would append "could not play" under an answer whose audio played perfectly.
    // Adversarial review found it the second round. The node is detached by the next
    // render, so `isConnected` is the whole test, which is `abandonAsk`'s own device for
    // the same question about the same panel.
    const slot = line(el("answer-body"), "", "notice");
    slot.hidden = true;
    // The two names the report will need (ADR-0205 §7), taken from **this** response
    // rather than from the page's current selection: the id is "the one the response
    // carrying that rendering disclosed and never one it derived, counted or guessed",
    // and where it disclosed `null` there is nothing to report about this turn.
    void playSpoken(turn.spoken, slot, turn.episode_id, turn.outcome.conversation_id);
    return;
  }
  // Carried rather than inferred from the `null` above it: §4 gives `spoken` two `null`
  // shapes and only one of them is an answer that could not be spoken.
  if (turn.spoken_degraded) {
    line(el("answer-body"), NOT_SPOKEN, "notice");
  }
}

// Play the rendering the hub sent, and nothing else — the browser's ordinary audio
// decoding of bytes this system produced (ADR-0200 §10). No `speechSynthesis`: the
// words that reach a loudspeaker are the ones ADR-0199's disclosure ruling composed
// for that channel, rendered by the hub's own synthesizer.
//
// **Through the Web Audio decoder rather than an `<audio>` element**, and the reason is
// a ratified clause rather than a preference: ADR-0168 §6 serves every response under a
// policy permitting media "from its own origin alone", and `media-src 'self'` does not
// match a `blob:` or a `data:` URL — the only two ways to get bytes the page is holding
// into a media element. So element playback of a hub-supplied rendering is refused by
// the browser, and the alternative was widening a ratified security clause to make one
// control work. `decodeAudioData` takes the octets directly, engages no fetch and no
// URL, and is subject to no directive at all.
//
// **The context is `readyToPlay`'s and is never built here**, because here is after the
// upload and outside the gesture that led to it — see that function for the defect this
// arrangement exists to avoid.
async function playSpoken(spoken, slot, episode, conversation) {
  const context = listeningContext;
  if (context === null) {
    couldNotPlay(slot);
    return;
  }
  // **One playback in the air, and taking the record over ends the one it named.**
  // Adversarial review, round 1, `major`. The sequence the finding describes — a second
  // spoken answer arriving over a first one still sounding — is unreachable through the
  // control, because every spoken answer arrives from a press and the press has already
  // interrupted; and that is exactly why the invariant is held here rather than left to
  // be inferred from the only caller there happens to be today.
  stopPlaying();
  const mine = {
    source: null,
    slot,
    buffer: null,
    offset: 0,
    startedAt: 0,
    played: 0,
    episode,
    conversation,
  };
  playing = mine;
  try {
    // **The press's resume, awaited rather than assumed** (#1690). `readyToPlay` starts
    // it where the activation is, which is the only place it can be started; what it
    // cannot do from there is know whether it worked.
    if (resuming !== null) {
      await resuming;
    }
    // **And a state entered after that press** — the call that arrives while the turn is
    // out, the other application that takes the audio session. One more resume, awaited
    // like the first, because a context this page has not looked at since the press is a
    // context it knows nothing about.
    if (context.state !== "running") {
      await context.resume();
    }
    if (context.state !== "running") {
      // A context that will not run decodes perfectly and sounds nothing, so this is the
      // one place the silence can be caught: after here, nothing throws and nothing is
      // heard. Said as what it is — a rendering this browser could not play.
      forgetPlaying(mine);
      couldNotPlay(slot);
      return;
    }
    const decoded = await context.decodeAudioData(bytesOf(spoken.content).buffer);
    // **The press that landed while this was decoding** (#1696). `interruptPlayback`
    // cleared the record, and starting a source now would be the answer the owner
    // interrupted beginning to speak *after* they had begun — which is the failure the
    // interrupt exists to remove, arriving a moment late.
    if (playing !== mine) {
      return;
    }
    mine.buffer = decoded;
    soundFrom(context, mine, 0);
  } catch (_) {
    // **Only while this is still the playback in the air.** An interrupt has already
    // said what happened, in the one place that knows it was an act rather than a
    // failure — `sendRecording` draws the same line one entry over.
    if (playing === mine) {
      forgetPlaying(mine);
      couldNotPlay(slot);
    }
  }
}

// Start the record's buffer sounding from `offset` seconds in, and take the source onto
// the record.
//
// **The one place a playback begins.** Where it started and how much of the buffer is
// already behind it are written where the source is started, so the two cannot drift
// apart — a first playing passes zero, and a resume passes what the press it is
// recovering from had already sounded (#1701).
function soundFrom(context, mine, offset) {
  const source = context.createBufferSource();
  source.buffer = mine.buffer;
  source.connect(context.destination);
  // Cleared where the playback ends of its own accord, so the next press does not report
  // an answer that finished as one it interrupted. `ended` fires on `stop()` too, where
  // the record has already moved on and been stamped — the identity check is what tells
  // the two apart. A source that ended by itself played the whole buffer, and the record
  // says so before it is let go, so `played` reads the same however the playback ended.
  source.addEventListener("ended", () => {
    if (playing !== mine) {
      return;
    }
    mine.played = mine.buffer.duration;
    // A source that ended of its own accord played the buffer, so the buffer's own
    // duration is both numbers — which is what ADR-0205 §2's equality requires of
    // `COMPLETE` and what it costs the device to say it: nothing.
    reportDelivery(mine, "complete");
    forgetPlaying(mine);
  });
  mine.offset = offset;
  mine.startedAt = context.currentTime;
  source.start(0, offset);
  // After `start`, because a source that has not started cannot be stopped and a record
  // naming one would have `interruptPlayback` throw rather than interrupt.
  mine.source = source;
}

// **The answer an accidental press ended, taken up where the sound stopped** (#1701, the
// owner's direction of 2026-08-28). ADR-0200 §4's no-words release is the one ending
// this runs on: nothing was asked, no turn ran, nothing was captured and no conversation
// was created — so the press turned out to be an accident, and the answer on screen is
// still the answer.
//
// **Page-locally, with no hub call.** The decoded buffer is still held and where it
// stopped is still on the record, so the whole of this is one more source: nothing is
// re-sent, nothing is re-rendered, and the interruption never reaches the hub as a gap
// in a delivery it is told about — ADR-0205 §8 names this sibling and says why that is
// legible, "a resume that never left the page produces no report".
//
// **A record of its own rather than the one the press ended.** The stopped source's
// `ended` listener still names the old record, and a resume that reused it would hand
// that queued task a live playback to let go of — the identity check that makes
// `forgetPlaying` and the listener safe is exactly what a reused record defeats.
//
// **And where it cannot resume it leaves the interruption's own sentence standing**: a
// context that is not running, a slot the next render detached, a source this browser
// will not start. That sentence is true in each of those cases, which is why it is the
// fallback rather than something to clear first.
function resumeInterrupted() {
  const mine = held;
  held = null;
  if (mine === null || mine.buffer === null || !mine.slot.isConnected) {
    return;
  }
  const context = listeningContext;
  if (context === null || context.state !== "running") {
    return;
  }
  stopPlaying();
  const resumed = {
    source: null,
    slot: mine.slot,
    buffer: mine.buffer,
    offset: 0,
    startedAt: 0,
    played: mine.played,
    // The same answer, so the same subject: a resume that runs to its end reports
    // `COMPLETE` of the turn the press already reported `INTERRUPTED` of, and the hub
    // performs nothing on the second — a turn is stamped once (ADR-0205 §1), and the
    // page needs no rule of its own to keep that true.
    episode: mine.episode,
    conversation: mine.conversation,
  };
  playing = resumed;
  try {
    soundFrom(context, resumed, mine.played);
  } catch (_) {
    forgetPlaying(resumed);
    return;
  }
  playbackResumed(resumed.slot);
}

// Let go of a playback that is over, and only where it is still the one being held: a
// record the next press or the next answer has already replaced belongs to neither.
function forgetPlaying(mine) {
  if (playing === mine) {
    playing = null;
  }
}

// The notice, written into the turn that owed it **or nowhere**. A slot the next render
// detached belongs to an answer that is no longer on screen, and saying its audio failed
// under the answer that replaced it would attribute one turn's silence to another.
function couldNotPlay(slot) {
  if (!slot.isConnected) {
    return;
  }
  slot.textContent = COULD_NOT_PLAY;
  slot.hidden = false;
}

// The interruption, under the same rule and for the same reason: a slot the next render
// detached belongs to an answer that is no longer on screen, and saying *that* one was
// interrupted under the answer that replaced it would attribute one turn's silence to
// another. Its own function rather than a shared writer taking the sentence as an
// argument, so each notice reaches the panel through exactly one place and a check can
// say so of each.
function playbackInterrupted(slot) {
  if (!slot.isConnected) {
    return;
  }
  slot.textContent = PLAYBACK_INTERRUPTED;
  slot.hidden = false;
}

// The resume, under the same rule and for the same reason, and its own function for the
// same one: each notice reaches this panel through exactly one place, so a check can say
// so of each. It writes over the interruption's sentence rather than beside it, because
// the two are accounts of the same sound and only the later one is true.
function playbackResumed(slot) {
  if (!slot.isConnected) {
    return;
  }
  slot.textContent = PLAYBACK_RESUMED;
  slot.hidden = false;
}

// The recording as `SpokenAudio.content` wants it: standard RFC 4648 §4 base64, padded
// and canonical, which is exactly what `btoa` produces. Never normalised afterwards —
// what this sends is what the hub validates and what `decoded()` reverses (ADR-0200
// §9).
//
// Chunked because `String.fromCharCode.apply` takes its bytes as arguments, and a
// second of audio is more arguments than a stack frame holds.
const BASE64_STRIDE = 0x8000;

async function base64Of(recording) {
  const bytes = new Uint8Array(await recording.arrayBuffer());
  let binary = "";
  for (let at = 0; at < bytes.length; at += BASE64_STRIDE) {
    binary += String.fromCharCode.apply(null, bytes.subarray(at, at + BASE64_STRIDE));
  }
  return btoa(binary);
}

// The reverse, for the rendering. `atob` is the pair of `btoa` and neither normalises.
function bytesOf(content) {
  const binary = atob(content);
  const bytes = new Uint8Array(binary.length);
  for (let at = 0; at < binary.length; at += 1) {
    bytes[at] = binary.charCodeAt(at);
  }
  return bytes;
}

// --- notifications, in the open page and by no other means (ADR-0175 §9) -----
//
// This page asks for no Notification API, no Push API, no service worker and no
// operating-system notification. That is the owner's ruling on #1230 recorded as a
// clause, and it is also what makes milestone 14 reachable at all: every one of
// those needs a secure context, and ADR-0174 §7 makes a secure-context requirement
// a stop condition on this lane.

function deliveryState(text) {
  el("delivery-state").textContent = text;
  el("watch-button").hidden = watching;
}

// --- coming back, and saying so (ADR-0182 §7, ADR-0175 §4) -------------------
//
// ADR-0168 §9 rules out the gateway retrying *silently*, and **ADR-0182 §7** states
// the rule for this page — not merged at the time of writing, in its final review
// round on `web-client/sessions-adr`, and §10 assigns "§7's announced re-arm" to this
// lane by name. Every clause of it is met here and each is worth naming, because the
// permission is conditional and a lane that met four of five would read as compliant:
//
//   1. **Only a delivery stream, and only on an event** — `visibilitychange` and
//      `online`, never a timer, a schedule, or the failure itself. `rearm` is reached
//      from those two listeners and from `watchDeliveries`' own `finally`, and from
//      nowhere else; no clock in this file calls it and none opens a stream.
//   2. **The attempt and its outcome are both announced**, at the surface the stream
//      feeds rather than at the page's foot: the attempt in `#delivery-state`, the
//      outcome either as the stream running on or as `stopWatching` plus a condition
//      in the notifications panel.
//   3. **One stream at a time, re-established only while the page holds none.** An
//      event arriving while one is open opens nothing — it leaves a reason behind,
//      and that reason is spent in `watchDeliveries`' `finally`, which runs after the
//      stream ended in one of the two ways §7 names: the gateway's terminal value, or
//      a connection that failed.
//   4. **A failed re-establishment attempts no other.** `asked` is consumed once and
//      only a fresh event sets it, so nothing here becomes a retry loop.
//   5. **No other request is re-issued of the page's own motion.** Nothing in this
//      file re-sends an ADR-0177 §6 operation after a refusal; a failed ask, grant,
//      forget or resume is reported and waits for the owner, because an automatic
//      re-issue can duplicate a turn.
//
// ADR-0175 §4 is why it costs nothing — an abandoned delivery stream costs the
// browser "a reconnect — which is free, because a session outlives its connections".
//
// **This is the failure the phone kept hitting.** A backgrounded page has its stream
// abandoned by the gateway the moment a write to it does not complete (§4's last
// clause), and the panel went on reading "Watching for notifications" until the owner
// noticed and pressed the button. Two events replace that, and no timer does.
//
// **An event that arrives while the last stream is still pending is held, not thrown
// away.** `watching` is this page's own record of whether a stream is open, and a
// socket that died without its `fetch` settling still reads as open — which is exactly
// the phone's own case, because the stream is abandoned while the page is in the
// background and the rejection lands whenever the browser next runs it. Dropping the
// event there would leave the owner pressing the button after all, one ordering over
// (adversarial review, round 1). So the reason is kept and spent when the truth
// arrives, and a second stream is never forced to find out — that would hold two of
// one browser's `gateway_max_browser_connections` for one delivery slot.
//
// **One request, and it is not a queue.** It holds the reason to announce, it is
// consumed once, and nothing but a fresh foreground or network event sets it again —
// so a re-armed stream that fails at once re-arms nothing. That is the difference
// between honouring an event the owner caused and retrying on a timer, which is what
// ADR-0168 §9 forbids.
let asked = null;
const CAME_BACK =
  "This page came back to the foreground with nothing listening, so it started " +
  "watching again — announced here rather than done quietly.";

const NETWORK_BACK =
  "This device's network came back with nothing listening, so it started watching " +
  "again — announced here rather than done quietly.";

// What a re-arm does **not** promise. The gateway holds a poll only while a stream is
// open, so nothing was taken out of the hub's durable outbox while this page was not
// watching (ADR-0175 §4) — but a delivery returned in the moment the last stream ended
// "is written nowhere" and is not replayed, and a page claiming otherwise would be
// promising a guarantee the gateway declines to make.
const NOTHING_REPLAYED =
  "Nothing waiting at the hub was lost: it is polled only while a browser is watching. " +
  "A notification written in the moment the last stream ended is not repeated.";

function rearm(because) {
  if (headerHalf() === null) {
    return;
  }
  if (watching) {
    asked = because;
    return;
  }
  watchDeliveries(`${because} ${NOTHING_REPLAYED}`);
}

// **`because` is the reason this browser stopped, said in the one line that also
// restores the owner's control** — `deliveryState` un-hides `#watch-button` whenever
// `watching` is false, so the sentence and the way back arrive together. Every ending
// the gateway named is explained in the notifications panel beside it; this argument
// is for the one ending the gateway did not name, because the page reached it on its
// own (#1442). Omitting it leaves the line as it was before that case existed.
// End the request behind the stream this page is reading, if it is reading one
// (#1542).
//
// **Session loss is the caller and it is the only one**, which is why this is not part
// of `stopWatching`. Every ordinary ending — the gateway's terminal value, a refusal, a
// body that stopped, either of `readDeliveries`' two deadlines — is reached from inside
// that function with the request already over, and `stopWatching` is the line and the
// control rather than the socket. A session that has ended is the one case where the
// page's record and the request disagree, and the request is what has to be settled:
// ADR-0182 §7 counts a `fetch` still pending as a stream this page holds, so re-entry
// with one outstanding re-establishes while holding one.
//
// **It ends a stream and opens none**, which is the clause §7 turns on: nothing reached
// from here re-establishes anything, and what opens the next stream is the owner's own
// re-entry through `showConsole`.
//
// Idempotent, and safe on a stream that has already finished — `abort` on a settled
// request is a no-op. The record is cleared before the abort so that a rejection
// landing in `readDeliveries`' catch finds this stream already released.
function releaseStream() {
  const open = streaming;
  if (open === null) {
    return;
  }
  streaming = null;
  open.released = true;
  open.reader.abort();
}

function stopWatching(because) {
  watching = false;
  deliveryState(
    because ? `Not watching for notifications. ${because}` : "Not watching for notifications."
  );
}

function renderNotification(value) {
  const list = el("notification-list");
  const item = document.createElement("li");
  const summary = document.createElement("p");
  summary.className = "notification-summary";
  summary.textContent = value.summary;
  item.appendChild(summary);
  if (value.detail) {
    const detail = document.createElement("p");
    detail.className = "notification-detail";
    detail.textContent = value.detail;
    item.appendChild(detail);
  }
  const source = document.createElement("p");
  source.className = "hint";
  // The class the producer declared, presented as what it is. ADR-0099 §4's floor
  // and ADR-0073 §4's before it forbid a surface lending a value a warrant it does
  // not carry, so this says a notification arrived and what it was about — never
  // that the assistant vouches for it.
  source.textContent = `Notification: ${value.notification_class}`;
  item.appendChild(source);
  list.insertBefore(item, list.firstChild);
}

// One delivery stream (ADR-0175 §4). The gateway writes on it at least once per
// `gateway_notification_budget` — a delivery where its poll returned one, and
// otherwise a value carrying nothing but its own kind — so a stream that has gone
// quiet for longer than that cadence is one something has happened to, which is
// what the keep-alive exists to make observable at either end.
//
// **It is never restarted on a timer, and never restarted in silence.** A stream that
// ends says so and offers the owner a button; a stream re-armed by `rearm` above says
// that it was and why, in this panel, before anything arrives on it. ADR-0168 §9's
// rule against silent retrying is the gateway's, and a page that spun against an
// unreachable hub would be the same failure wearing the front end's clothes — so
// `because` is not decoration, it is the condition on which re-arming is permitted at
// all, and a caller with nothing to say is the owner's own click.
async function watchDeliveries(because) {
  const half = headerHalf();
  if (half === null || watching) {
    return;
  }
  watching = true;
  // The condition that ended the *last* stream is cleared here, as every other act
  // clears its own panel before it runs. A re-arm that succeeded above a standing
  // "the gateway did not answer" is a page contradicting itself on one screen, which
  // is the thing this lane exists to stop rather than a thing to leave to a dismiss
  // control. Found by driving the page, not by any check over its source.
  fault(null, "notifications");
  deliveryState(
    because ? `Watching for notifications. ${because}` : "Watching for notifications."
  );
  try {
    await readDeliveries(half);
  } finally {
    // The stream has ended and this page knows it now, so an event held while it was
    // still pending is spent here — **after** the ending has been reported, which is
    // why this is not in `stopWatching`: re-arming from there would announce the new
    // stream and then write the old one's condition over the top of it.
    const held = asked;
    asked = null;
    if (held !== null) {
      rearm(held);
    }
  }
}

// The read itself, split out so that the `finally` above wraps the whole of a
// stream's life — its opening, its ending, and the reporting of that ending — rather
// than one `try` inside another. Nothing else calls it.
//
// **The deadline is the one clock in this file, and what it does is end a stream**
// (#1442). `fetch` has no deadline of its own, so a socket that dies without settling
// — a phone whose network went away without an RST, a black-holed connection — left
// this `await` pending for ever: `watching` stayed true, the panel went on reading
// "Watching for notifications", `deliveryState` kept `#watch-button` hidden because
// that is what `watching` means, and reloading the page was the only way back.
// ADR-0182 §7's announced re-arm could not fire either, because §7 re-establishes a
// stream "only while it holds none" and this page believed it held one.
//
// **What makes a silent stream distinguishable from a quiet one is the gateway's own
// obligation.** ADR-0175 §4 has it write on every open delivery stream at least once
// per `gateway_notification_budget` — "a delivery where the poll returned one, and
// otherwise a value carrying nothing but its own kind" — and §4 spends that keep-alive
// precisely to make "the liveness of the gateway, of its hub connection and of the
// browser's own socket observable at a bounded cadence". So silence past a multiple of
// the disclosed figure is not an assistant with nothing to say; it is the one thing
// the keep-alive exists to expose, observed at the end it was written for.
//
// **The gateway states the cadence in the stream's own head** — the
// `X-Assistant-Keep-Alive-Microseconds` response header. ADR-0175 §2 leaves the
// framing to this lane and ADR-0168 §5 closes the other candidate in terms (the
// bootstrap exchange "returns nothing but the two session values §6 requires"), so the
// choice was between a header and an opening value on the body. The header wins on the
// clause that governs values: §4 holds "at most one value pending per stream" and ends
// one whose write has not completed when the next is due, which is a rule about a
// browser that stopped reading and not about a preamble. A header is in hand the
// instant `fetch` settles, before a single value is read, so it takes no place in the
// ordering and cannot be abandoned — and the deadline is armed from it rather than from
// any figure this page kept, which is why nothing here is remembered between streams
// and no reconfigured gateway can be held to a figure it never uttered.
//
// **And a `fetch` that never settles at all is bounded too, by the page's own figure**
// (#1474). The head is what carries the cadence, so a request black-holed before a
// single byte comes back has nothing to arm a cadence deadline from — and that left one
// stream stalling exactly as every stream did before any of this existed, with
// `watching` true, the button hidden and §7's re-arm unreachable. #1474 states that
// case as a browser's *first* stream at an origin, on the premise that the figure is
// remembered per origin. It is not: `KEEP_ALIVE_HEADER` below is emphatic that nothing
// about the cadence is kept between streams, and `cadence` is a local of this function.
// So the case is every head-less stream, first or thousandth — including the re-arm a
// backgrounded phone makes on `visibilitychange` into a network that is still gone,
// which is the very failure ADR-0182 §7 exists for. `HEAD_DEADLINE_MILLISECONDS` carries
// the argument for bounding it from the page rather than from the gateway.
//
// **Two bounds, one timer, and which one fell due is read off `cadence`.** The head's
// bound is armed before the request goes out and spent the moment the head lands,
// whatever it says; the cadence's bound is armed from that head and restarted by every
// value. `cadence` is null exactly while no head has landed — it has one assignment and
// `heard` arms nothing until it is not null — so the abort handler needs no second flag
// to tell "never opened" from "went quiet", and the two cannot disagree about which
// happened.
//
// **The residual that survives is the one ADR-0175 §8 requires to survive.** A head that
// states no usable cadence still leaves that stream's *body* unbounded, because a
// gateway entitled to a month of silence and saying so is believed rather than
// second-guessed. That is deliberate and is not what #1474 is about: the head arrived,
// so this page knows a stream exists.
//
// **The deadline is restarted by every value that arrives, keep-alive included**, so
// what it measures is silence and never the stream's total life: a stream delivering
// notifications for a week is never abandoned by it.
//
// **And it re-establishes nothing, which is the clause ADR-0182 §7 turns on.** §7
// forbids re-arming "on a timer, on a schedule, or on the failure itself" and forbids
// converting an event-driven re-arm into a retry loop. This ends a stream, says so in
// the page, and hands the owner back the control §7's last paragraph calls "one
// control" that "removes the class". What opens the next stream is one of §7's two
// events or the owner's click, exactly as before — and where an event arrived while
// this stream was still pending, `watchDeliveries`' `finally` spends the one reason it
// held, once, which is the owner's own act being honoured rather than a loop.
async function readDeliveries(half) {
  const reader = new AbortController();
  // This stream, reachable from outside so that a session that ended can end it
  // (#1542). Registered before anything is armed and cleared in the `finally`, so the
  // window in which something can release it is exactly the window in which there is
  // something to release.
  const open = { reader, released: false };
  streaming = open;
  // Null until this stream's head says otherwise, and never carried over from another
  // stream: see `KEEP_ALIVE_HEADER`.
  let cadence = null;
  let silent = false;
  // The head never arrived, which is its own ending and not the one above (#1474).
  let stalled = false;
  let deadline = null;
  // One deadline, held as the **instant** it falls due and armed in segments no longer
  // than `setTimeout` can express. A single call cannot carry a delay past a signed
  // 32-bit count of milliseconds — it is clamped to fire at once — so a long cadence
  // armed in one call would abort a healthy stream immediately, which is worse than the
  // failure being bounded. Segments keep the rule exact at every figure a gateway may
  // hold: the bound is three times the cadence it disclosed, and nothing else.
  //
  // **On `performance.now()` and not on `Date.now()`, because the wall clock moves.**
  // A device whose clock steps back an hour — a time-zone correction, an NTP
  // adjustment, an owner setting it — makes a segment that reads the wall clock find
  // the instant still an hour ahead and arm another hour of waiting, so a black-holed
  // stream would hold the panel for an hour instead of the minute the cadence promised.
  // `performance.now()` is monotonic from page load and is unaffected by any of them.
  // Adversarial review found it on round 4.
  //
  // This opens no stream and re-establishes nothing (ADR-0182 §7): a segment that finds
  // the instant still ahead arms the next one, and the last one ends the stream.
  const arm = (at) => {
    deadline = window.setTimeout(
      () => {
        if (performance.now() < at) {
          arm(at);
          return;
        }
        // Which of the two bounds fell due is which figure armed it, and `cadence` is
        // already the record of that: null exactly while no head has landed. So the two
        // endings are told apart from the state that decides them rather than from a
        // second flag that could be set in the wrong place.
        if (cadence === null) {
          stalled = true;
        } else {
          silent = true;
        }
        reader.abort();
      },
      Math.min(at - performance.now(), TIMER_SEGMENT)
    );
  };
  // Disarming is its own act because the head's bound is spent the moment the head
  // lands, whatever the head says — before the refusal path below reads a body, which
  // would otherwise run under a deadline meant for the head's arrival and report a
  // refusal the gateway did answer as a request nothing answered.
  const hush = () => {
    window.clearTimeout(deadline);
    deadline = null;
  };
  // Restarted by every value the stream delivers, so the bound is on silence — and
  // armed only where a cadence is actually known, because a deadline derived from
  // nothing is a figure this page would have made up.
  const heard = () => {
    hush();
    if (cadence !== null) {
      arm(performance.now() + cadence * SILENT_CADENCES);
    }
  };
  // The head's own bound, armed before the request goes out so that it covers the whole
  // interval a `fetch` can hang in (#1474). Like every other segment this arms, it ends
  // a stream and opens none: ADR-0182 §7 forbids re-establishing "on a timer", and
  // nothing reached from here re-establishes anything.
  arm(performance.now() + HEAD_DEADLINE_MILLISECONDS);
  try {
    const response = await fetch("/deliveries", {
      headers: admitted(half, false),
      signal: reader.signal,
    });
    // The head has landed, so the bound on its arrival is spent — here rather than
    // below, so that neither a refusal's body nor an unusable cadence leaves it armed.
    hush();
    if (!response.ok) {
      const body = await readBody(response);
      stopWatching();
      refused("notifications", body, response.status);
      return;
    }
    // The cadence *this* stream will be written at, off this stream's own head — armed
    // before the first value is read, so the bound covers the silence that begins the
    // moment the head arrives, and derived from what the gateway said rather than from
    // any figure of this page's. A head that carried none, or one no deadline can be
    // computed from, leaves this stream unbounded: `usableCadence` has the reason.
    cadence = usableCadence(response.headers.get(KEEP_ALIVE_HEADER));
    heard();
    let terminal = null;
    for await (const value of streamValues(response)) {
      heard();
      if (value.kind === "notification") {
        renderNotification(value);
      } else if (TERMINAL_KINDS.has(value.kind)) {
        terminal = value;
        break;
      }
      // `alive` is the keep-alive and needs no rendering: what it proves is that
      // the gateway, its hub connection and this socket are all still there, which
      // the absence of an ending already says. It restarts the deadline above and
      // that is the whole of its effect here — which is what §4 spends it on.
    }
    stopWatching();
    if (terminal === null) {
      fault(DELIVERY_STREAM_CUT, "notifications");
    } else {
      report("notifications", terminal, describeDeliveryEnd(terminal, response.status));
    }
  } catch (_) {
    // An abort this page asked for is not the gateway having gone, and saying it was
    // would be a wrong explanation rather than a missing one: the gateway may be
    // perfectly alive at the other end of a socket that stopped carrying. The two
    // aborts are kept apart from each other for the same reason — a stream that went
    // quiet broke a cadence the gateway stated, and one that never had a head broke
    // nothing the gateway ever said, so WENT_SILENT's sentence would be false of it.
    //
    // **And a stream this page released is a third ending, told apart from both**
    // (#1542). `sessionLost` has already forgotten the header half, stopped watching
    // and put the re-entry sentence on screen, so there is nothing left here to say —
    // and ADR-0182 §6 rules where it is said as well as that it is said, keeping this
    // ending out of the fault surface entirely. A `GATEWAY_GONE` written here would be
    // a wrong explanation for an ending this page performed, and it would land in a
    // panel `showBootstrap` has just hidden.
    if (open.released) {
      return;
    }
    if (stalled) {
      stopWatching(NO_HEAD);
      fault(DELIVERY_STREAM_STALLED, "notifications");
    } else if (silent) {
      stopWatching(WENT_SILENT);
      fault(DELIVERY_STREAM_SILENT, "notifications");
    } else {
      stopWatching();
      fault(GATEWAY_GONE, "notifications");
    }
  } finally {
    // Only where this stream is still the one on record: a release has already cleared
    // it, and clearing it again would drop the registration of whatever opened next.
    if (streaming === open) {
      streaming = null;
    }
    window.clearTimeout(deadline);
  }
}

// --- the conversation surface (ADR-0175 §6) ----------------------------------

// **`stopping` is the owner's, and it is the only clock this function knows about**
// (#1536). One caller — a park's answer — hands the owner a control that ends its wait,
// and passes the controller behind it here; every other caller passes none, and
// `undefined` is what `fetch` reads as no signal at all. Nothing here arms a deadline:
// `resume` rides the gateway's turn budget (ADR-0177 §9) and that figure reaches the
// browser in nothing, so a page-side one would be a second number able to disagree with
// it. The page keeps one clock and it is the delivery stream's.
//
// **`noticed` is that same caller being told *which* refusal it got**, and it is a
// callback rather than a wider return for the reason a wider return would be a
// different change: `null` means "refused, and the condition is already on screen" at
// nineteen call sites, several of which branch on it, and re-reading all nineteen
// against ADR-0139 §4's three outcomes is its own lane (#1619). One caller needs more
// than `null` — a park's answer, because ADR-0177 §7's third clause makes a
// gateway-to-hub transport failure **not known** while an ordinary decline is known not
// to have landed, and only the first of those may keep its continuation. So it is
// handed the body this function already read, and every other caller is untouched.
//
// **The body and not the status**, which is a rule this file already keeps: a status is
// in `SESSION_LOST_STATUS` only where it names one condition, because `403` "says the
// gateway refused and does not say why" and mapping it would be the flattening
// ADR-0168 §6 forbids. The `fault` name is where ADR-0168 §9's distinction actually
// lives, so that is what a caller classifying an outcome is given — and handing the
// status beside it would invite reading the condition off the wrong half.
async function relay(half, path, payload, panelId, stopping, noticed) {
  const response = await fetch(path, {
    method: "POST",
    headers: admitted(half, true),
    body: JSON.stringify(payload),
    signal: stopping === undefined ? undefined : stopping.signal,
  });
  if (response.ok) {
    // **The head is not the answer, and a body this browser did not read is not a
    // response** — adversarial review's round-8 blocker, and ADR-0177 §7's fourth
    // clause in terms: a failure of "the browser's own request to the gateway — the
    // request was sent and no response was read — is an outcome that is **not known**".
    //
    // `fetch` settles when the *head* lands, so the body is still arriving when this
    // resumes, and the owner's **Stop waiting** aborts a request whose status has
    // already been read. Routing that through `readBody` swallowed the abort and
    // returned `{}` for a `200`, and a park's answer then ran straight past its
    // unknown-outcome branch into `renderOutcome(undefined, …)`: an uncaught
    // `TypeError`, a token left `spent` and never `unresolved`, and a row reading "That
    // park has been answered from this page" for an outcome nothing had read. That is
    // the resolution-from-an-unresolved-act ADR-0139 §4 forbids, arriving through the
    // one door the rest of this lane closed.
    //
    // So the rejection is **kept** here and `readBody`'s swallow is left to the refusal
    // path it was written for. Every caller of this function already runs it inside a
    // `try`, and each one's `catch` is the ending it wants: `GATEWAY_GONE` for a read,
    // and for a park's answer the not-known branch that keeps the continuation.
    //
    // The gateway writes every `2xx` through `_json_response`, so a `2xx` body that
    // will not parse is a transport truth and not a shape this page has to tolerate —
    // which is the asymmetry with a refusal, whose condition a proxy really can replace.
    return asObject(await response.json());
  }
  const body = await readBody(response);
  // Every other request that names a conversation goes through here — the digest, the
  // forget, and `observe`, which sends this view's selection exactly as `ask` does.
  conversationLost(body, payload.conversation_id);
  refused(panelId, body, response.status);
  if (noticed !== undefined) {
    noticed(body);
  }
  return null;
}

async function listConversations() {
  fault(null, "conversations");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const body = await relay(half, "/conversations", {}, "conversations");
    if (body === null) {
      return;
    }
    const list = el("conversation-list");
    clearNode(list);
    if (body.conversations.length === 0) {
      line(list, "No conversations yet.", "hint");
    }
    body.conversations.forEach((one) => renderConversation(list, one));
    show("conversations", true);
  } catch (_) {
    fault(GATEWAY_GONE, "conversations");
  }
}

function renderConversation(list, summary) {
  const item = document.createElement("div");
  item.className = "conversation-row";
  const when = summary.last_turn_at || summary.last_active_at;
  // Both instants cross and they are different facts (ADR-0074 §2): activity is
  // when someone was last here and orders the list, and `last_turn_at` is when a
  // turn was last recorded. A conversation with no turn says so rather than
  // borrowing the other reading.
  line(
    item,
    summary.last_turn_at
      ? `Last turn ${when} — active ${summary.last_active_at}`
      : `No turn yet — active ${summary.last_active_at}`,
    "hint"
  );
  const resume = document.createElement("button");
  resume.type = "button";
  resume.textContent = "Continue";
  resume.addEventListener("click", () => {
    changeConversation(summary.id);
    el("utterance").focus();
  });
  const forget = document.createElement("button");
  forget.type = "button";
  forget.textContent = "Forget";
  forget.addEventListener("click", () => forgetConversation(summary.id));
  item.appendChild(resume);
  item.appendChild(forget);
  list.appendChild(item);
}

// Read the conversation, then forget it — the CLI's own order, which ADR-0175 §6
// names as the pattern available here. It is a *rendering* decision and not a
// control: ADR-0168 §6's residual is a script on this origin issuing requests the
// browser will authenticate, which defeats a confirmation as surely as it defeats
// both session halves. Showing the count and the span before destroying is
// ADR-0073 §5's show-then-confirm for the owner's benefit, not a defence.
async function forgetConversation(id) {
  fault(null, "conversations");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const digest = await relay(half, "/conversation", { conversation_id: id }, "conversations");
    if (digest === null) {
      return;
    }
    const held = digest.conversation;
    const asked = window.confirm(
      `Destroy conversation ${held.id}? It holds ${held.recorded_turns} recorded ` +
        `turn(s), from ${held.started_at} to ${held.last_turn_at || "no turn yet"}. ` +
        "The episodes its turns index are destroyed with it."
    );
    if (!asked) {
      return;
    }
    const done = await relay(half, "/conversation/forget", { conversation_id: id }, "conversations");
    if (done === null) {
      return;
    }
    if (conversationId === id) {
      changeConversation(null);
    }
    await listConversations();
  } catch (_) {
    fault(GATEWAY_GONE, "conversations");
  }
}

// --- the grant surface (ADR-0177 §6, §7; ADR-0139) ---------------------------
//
// Two questions and they are never answered with each other (ADR-0139 §1, §3's
// fourth clause). "What may I grant?" is `/sources`; "what do I currently
// authorise?" is `/grants/standing`; and the history at `/grants/recent` answers
// neither. Each has its own panel, its own heading and its own read, and no panel
// annotates one answer with another.

// Every use a grant may authorise, named in words (ADR-0139 §3's second clause).
// **All three, wherever a choice is offered**, and never a proper subset: "no
// client may offer, enumerate or explain a proper subset of the members its own
// type admits", because a user cannot choose what they are not shown.
//
// The phrases say what the reading is *used for* and never what follows from it
// (ADR-0133 §1): granting the third decides nothing about whether you are ever
// contacted, so its phrase is about reading, on the same footing as the others.
const USES = [
  { value: "facet", label: "Look at it while answering you" },
  { value: "ingest", label: "Durably remember what it says" },
  { value: "notify", label: "Read it to raise things with you unprompted" },
];

// ADR-0139 §4's exactly three outcomes for one act of an amendment.
const LANDED = "landed";
const NOT_LANDED = "not-landed";
const UNKNOWN = "unknown";

// Which faults mean an act's outcome is **not known** (ADR-0177 §7's third
// clause). Read from ADR-0168 §9's distinction and from nothing else: the hub
// being unreachable is a transport failure between the gateway and the hub, so
// the hub may well have committed first. Everything else the gateway answers with
// is a request that reached a decision before any write — a refusal at the door,
// at the connection ceiling, or by the hub itself — and is known not to have
// landed.
const UNKNOWN_FAULTS = new Set(["hub-unreachable"]);

const STATE_UNREAD =
  "Nothing above says what this source is granted for now. An act's outcome is a " +
  "fact about that act; what stands is a fact only the hub can state.";

const QUESTION_GONE =
  "That question was not in the list I just read, so I sent nothing. It may have " +
  "been answered or destroyed since the page last showed it.";

// Say what a scope allows, in words rather than in the values on the wire.
//
// **Exactly the uses the grant names** (ADR-0139 §3's third clause): nothing is
// added and nothing is dropped, and in particular a use the vocabulary above does
// not carry is still rendered — dropping it would omit a use the grant names,
// which is the half of the clause a lookup table gets wrong.
function usePhrase(scope) {
  if (scope.length === 0) {
    return "nothing";
  }
  return scope
    .map((use) => {
      const known = USES.find((one) => one.value === use);
      return known ? known.label.toLowerCase() : use;
    })
    .join(", and ");
}

// One act of the grant surface, classified as one of ADR-0139 §4's three outcomes.
//
// **The browser's own request failing is the third producer of the third outcome**
// (ADR-0177 §7's fourth clause), and it is the one no earlier surface had: the CLI
// holds the socket to the hub itself, while between this page and the store sit its
// own request, the gateway, and the gateway's wire connection. So a rejected `fetch`
// is *not known* rather than "it did not happen" — the gateway may already have
// called, and ADR-0085 §8e's residual has a second instance here.
async function act(half, path, payload) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: admitted(half, true),
      body: JSON.stringify(payload),
    });
  } catch (_) {
    return { outcome: UNKNOWN, body: {} };
  }
  const body = await readBody(response);
  if (response.ok) {
    // **The status line is itself the statement that the act landed**, and that is
    // why a body this page then cannot read does not move the outcome. The gateway
    // relays one call and writes a success status only after that call has returned,
    // so a `200` cannot precede the hub's answer. What an unreadable body costs is
    // the detail beside the outcome, not the outcome — and reporting a landed act as
    // "not known" is forbidden by the same clause that forbids the reverse: each act
    // is reported as one of exactly three, "and never as either of the other two".
    return { outcome: LANDED, body };
  }
  // The act log has just been hidden with the rest of the console, so the condition is
  // restated beside the only act left to take — as re-entry rather than as a fault
  // (ADR-0182 §6), which is the one thing that changed here. `reportAct` still writes
  // its own line below, and it is about what the act did rather than about the session.
  sessionLost(body, describe(body, response.status));
  // A refusal whose condition this page cannot read is a refusal it cannot classify,
  // and ADR-0139 §4's third outcome is what an unclassifiable one is. The reachable
  // case is a response cut after its headers: the status may be the `502` the gateway
  // writes for a hub it could not reach, which is *not known*, and reading a missing
  // `fault` as "not one of the unknown conditions" would report exactly that as known
  // not to have landed.
  const named = typeof body.fault === "string";
  return {
    outcome: !named || UNKNOWN_FAULTS.has(body.fault) ? UNKNOWN : NOT_LANDED,
    body,
  };
}

// Say what one act did, as one of exactly three things (ADR-0139 §4's second
// clause). "Not merely failed" is the whole of it: a user who reads a failure as
// "the amendment did not happen" goes away with a source that has stopped being
// read, silently.
//
// Each phrasing is about **this act** and never about the source (§4's third
// clause). A withdrawal that landed is not a statement that the source is
// ungranted, and a refused grant is not one either.
function reportAct(panel, what, result) {
  const detail = typeof result.body.detail === "string" ? ` ${result.body.detail}` : "";
  if (result.outcome === LANDED) {
    line(panel, `The ${what} landed.`, "reply");
    return;
  }
  if (result.outcome === NOT_LANDED) {
    line(
      panel,
      `The ${what} is known not to have landed — I was refused, so nothing was ` +
        `written.${detail}`,
      "failed"
    );
    return;
  }
  line(
    panel,
    `The outcome of the ${what} is not known.${detail} I did not get an answer ` +
      "back, and it may have been done anyway.",
    "notice"
  );
}

// Open the act log fresh, so what is on screen is this act and never the last one.
function beginActs(heading) {
  fault(null, "acts");
  const panel = el("act-log");
  clearNode(panel);
  line(panel, heading, "hint");
  show("acts", true);
  return panel;
}

async function listSources() {
  fault(null, "sources");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const body = await relay(half, "/sources", {}, "sources");
    if (body === null) {
      return;
    }
    const list = el("source-list");
    clearNode(list);
    if (body.sources.length === 0) {
      line(
        list,
        "Nothing is configured for me to read. Configuration says where a source " +
          "is; a grant says whether I may read it, and neither stands in for the " +
          "other — so there is nothing to grant until something is configured.",
        "hint"
      );
    }
    body.sources.forEach((one) => renderSource(list, one));
    show("sources", true);
  } catch (_) {
    fault(GATEWAY_GONE, "sources");
  }
}

// One grantable source: what it is, where it reads from, and what you decided.
//
// **The location is rendered and an explicit act is taken before any grant is
// sent** (ADR-0139 §5, ADR-0102 §6) — including the granting half of an amendment,
// which is the case §5 exists for.
//
// **An absent location is not the case that clause fails closed on, and the two are
// easy to run together.** ADR-0102 §6 is normative that `location` is `None` "only
// where the source has **no** configured location at all", and that a configured
// location which cannot be shown makes the source *not grantable* — the hub omits it
// from this listing entirely. So a source that reaches this page with no location is
// one where "§9a's obligation [is] vacuous — there is nothing to show — and the
// source is grantable with `location` absent". Withholding the grant control from it
// would make a grantable source ungrantable from a browser and reach nothing: the
// hazard §6 is about never arrives here.
//
// **A grant renders exactly the uses it names, and the uses it leaves out are not
// on screen in any form** (ADR-0177 §6's third clause). No greyed row, no unchecked
// box, no strike-through: a control showing all three states beside a grant naming
// one is the user's decision presented as a half-filled form.
function renderSource(list, source) {
  const item = document.createElement("div");
  item.className = "source-row";
  const name = document.createElement("p");
  name.className = "source-name";
  name.textContent = source.source;
  item.appendChild(name);
  line(
    item,
    source.location === null
      ? "Reads from: not configured"
      : `Reads from: ${source.location}`,
    "hint"
  );
  if (source.live === null) {
    line(item, "You have not granted this. I read nothing from it.", "hint");
    offerScope(item, source, "Grant this", null);
  } else {
    line(item, `Granted for ${usePhrase(source.live.scope)}.`, "reply");
    offerScope(item, source, "Change what it may do", source.live);
    const withdraw = document.createElement("button");
    withdraw.type = "button";
    withdraw.textContent = "Withdraw";
    withdraw.addEventListener("click", () => revokeSource(source.source));
    item.appendChild(withdraw);
  }
  list.appendChild(item);
}

// The choice of uses, offered as all three and taken **before** anything is sent
// (ADR-0139 §4's sixth clause, ADR-0177 §7's sixth). No surface revokes in order to
// ask: a user who hesitates over this form, or closes the tab while thinking, has
// withdrawn nothing.
function offerScope(item, source, label, live) {
  const open = document.createElement("button");
  open.type = "button";
  open.textContent = label;
  const form = document.createElement("div");
  form.className = "scope-form";
  form.hidden = true;
  const boxes = USES.map((use) => {
    const row = document.createElement("p");
    row.className = "choice";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.id = `use-${source.source}-${use.value}`;
    // The box goes *inside* its label, as it does in the document (#1440): the pair is
    // one flex item that a narrow viewport cannot split, and the tap target becomes the
    // whole strip rather than a 1.15rem square. Still one text node and still never
    // markup — `use.label` is this file's own vocabulary either way.
    const text = document.createElement("label");
    text.className = "check";
    text.htmlFor = box.id;
    text.appendChild(box);
    text.appendChild(document.createTextNode(use.label));
    row.appendChild(text);
    form.appendChild(row);
    return { box, value: use.value };
  });
  const send = document.createElement("button");
  send.type = "button";
  send.textContent = live === null ? "Grant" : "Change it";
  send.addEventListener("click", () => {
    const scope = boxes.filter((one) => one.box.checked).map((one) => one.value);
    if (scope.length === 0) {
      fault(
        "Choose at least one thing I may do with it. A grant authorising nothing " +
          "is not a grant, and the hub refuses one.",
        "sources"
      );
      return;
    }
    if (live === null) {
      grantSource(source, scope);
    } else {
      amendSource(source, scope);
    }
  });
  form.appendChild(send);
  open.addEventListener("click", () => {
    form.hidden = !form.hidden;
  });
  item.appendChild(open);
  item.appendChild(form);
}

// One grant, sent after its disclosure and its explicit act (ADR-0139 §5).
async function grantSource(source, scope) {
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const panel = beginActs(`Granting ${source.source}.`);
  try {
    reportAct(panel, "grant", await act(half, "/grant", { source: source.source, scope }));
    line(panel, STATE_UNREAD, "hint");
    await listStanding();
    await listSources();
  } catch (_) {
    fault(GATEWAY_GONE, "acts");
  }
}

async function revokeSource(source) {
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const panel = beginActs(`Withdrawing ${source}.`);
  try {
    const withdrawal = await act(half, "/revoke", { source });
    reportAct(panel, "withdrawal", withdrawal);
    if (withdrawal.outcome === LANDED && withdrawal.body.revoked === null) {
      line(panel, "There was no live grant for it to withdraw.", "hint");
    }
    if (withdrawal.outcome === LANDED) {
      line(
        panel,
        "I will start no further read of it, and nothing a read still running " +
          "produces will be used. What I already believe from it is untouched.",
        "hint"
      );
    }
    line(panel, STATE_UNREAD, "hint");
    await listStanding();
    await listSources();
  } catch (_) {
    fault(GATEWAY_GONE, "acts");
  }
}

// An amendment: **two browser requests, composed here** (ADR-0177 §7's first
// clause). The gateway serves no shape that performs both, holds no state between
// them, and does not know the two are related — which is what puts the intermediate
// state where this surface can report it (ADR-0139 §4).
//
// It is never presented as atomic and never as leaving the source continuously
// granted: there is a moment in which nothing is granted, and each act gets its own
// line saying which of three things it did.
//
// **Where the withdrawal did not plainly land, no grant is sent** (§7's fifth
// clause). The clause requires this for the *unknown* branch; a refused withdrawal
// stops here too, on `interfaces/cli.py`'s own stated conservatism — sending the
// grant anyway invites reasoning backwards from its result, which is exactly the
// inference §7's seventh clause forbids, because a refusal is equally consistent
// with another client having granted in between.
async function amendSource(source, scope) {
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const panel = beginActs(
    `Changing what ${source.source} may do. This is two acts — a withdrawal, then a ` +
      "new grant — and there is a moment between them in which nothing is granted."
  );
  try {
    const withdrawal = await act(half, "/revoke", { source: source.source });
    reportAct(panel, "withdrawal", withdrawal);
    if (withdrawal.outcome !== LANDED) {
      line(
        panel,
        withdrawal.outcome === UNKNOWN
          ? "I sent no new grant. I could not tell whether the withdrawal happened, " +
              "and sending a second act to find out would only give me an answer I " +
              "could not read. The amendment is incomplete."
          : "I sent no new grant. The amendment is incomplete.",
        "notice"
      );
      line(panel, STATE_UNREAD, "hint");
      await listStanding();
      return;
    }
    reportAct(panel, "grant", await act(half, "/grant", { source: source.source, scope }));
    line(panel, STATE_UNREAD, "hint");
    await listStanding();
    await listSources();
  } catch (_) {
    fault(GATEWAY_GONE, "acts");
  }
}

// What the user currently authorises, from the store and from nothing else
// (ADR-0139 §2). This is the read that resolves every ambiguity the two acts above
// leave: a client that lost a response, or was refused by a race, asks what stands
// and is told.
//
// **A page that has not read this says the state is unread** (ADR-0177 §7's seventh
// clause), which is why the panel carries a state line rather than an empty list
// that could be mistaken for "nothing is granted".
async function listStanding() {
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  el("standing-state").textContent = "";
  show("standing", true);
  try {
    const body = await relay(half, "/grants/standing", {}, "standing");
    const list = el("standing-list");
    clearNode(list);
    if (body === null) {
      el("standing-state").textContent =
        "I could not read what you currently authorise, so it is unread. Nothing " +
        "below states it.";
      return;
    }
    el("standing-state").textContent =
      body.standing.length === 0
        ? "Read just now: you authorise nothing."
        : "Read just now.";
    body.standing.forEach((one) => renderStanding(list, one));
  } catch (_) {
    el("standing-state").textContent =
      "I could not read what you currently authorise, so it is unread.";
    fault(GATEWAY_GONE, "standing");
  }
}

// One standing grant. **The set is presented whole** (ADR-0139 §3's first clause):
// a grant on a source no held reader declares is exactly what this operation exists
// to show, and dropping it, or merging it into the sources panel, would hide it
// again.
function renderStanding(list, grant) {
  const item = document.createElement("div");
  item.className = "grant-row";
  renderGrantFields(item, grant);
  list.appendChild(item);
}

// What a live grant says, without the row it sits in — so a routed `standing_grants`
// listing and a routed `revoke`'s candidates read exactly as this panel does
// (ADR-0197 §12). **Exactly the uses the record names**, which is `renderStanding`'s
// own rule: adding the members a grant leaves out would present the owner's decision
// as a half-filled form (ADR-0139 §3's third clause).
function renderGrantFields(item, grant) {
  const name = document.createElement("p");
  name.className = "source-name";
  name.textContent = grant.source;
  item.appendChild(name);
  line(item, `You authorise ${usePhrase(grant.scope)}.`, "reply");
  line(item, `Decided ${grant.decided_at}`, "hint");
}

// The history (ADR-0097 §4). **No row here is presented as live or as withdrawn on
// its own** (ADR-0139 §3's fifth clause, ADR-0102 §3): liveness is computed hub-side
// from the `revokes` relation, and a clock corrected backwards can put a revoking
// record on a different page from the grant it revokes. So a row says which kind of
// record it is and stops there.
async function listGrantHistory() {
  fault(null, "history");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const body = await relay(half, "/grants/recent", {}, "history");
    if (body === null) {
      return;
    }
    const list = el("history-list");
    clearNode(list);
    if (body.grants.length === 0) {
      line(list, "You have granted and withdrawn nothing yet.", "hint");
    }
    body.grants.forEach((one) => renderHistory(list, one));
    show("history", true);
  } catch (_) {
    fault(GATEWAY_GONE, "history");
  }
}

function renderHistory(list, record) {
  const item = document.createElement("div");
  item.className = "grant-row";
  const name = document.createElement("p");
  name.className = "source-name";
  name.textContent = record.source;
  item.appendChild(name);
  line(
    item,
    record.revokes === null
      ? `You granted ${usePhrase(record.scope)}.`
      : `You withdrew a grant of ${usePhrase(record.scope)}.`,
    "hint"
  );
  line(item, `Decided ${record.decided_at}`, "hint");
  list.appendChild(item);
}

// --- the belief surface (ADR-0073, ADR-0077 §6, ADR-0177 §5) -----------------

// How many rows one read asks for. The **page size is this front end's**, which
// ADR-0177 §11 leaves it: "the request shapes, paths, framing and media types" for
// everything §1 admits are the implementing lane's, and the front end and the gateway
// ship and version in one distribution.
//
// It is stated rather than inherited from the surface's own default because the page
// has to *know* it: "is there more" is answered by asking for the next page and never
// by a total nobody computed (ADR-0073 §2), so a full page is a page whose length
// equals what was asked for — and a reader that did not ask cannot tell.
const PAGE = 25;

// How far each listing has read. Not a count of what exists: a total is not available
// and would be a claim this page cannot make.
const readSoFar = { beliefs: 0, questions: 0, interrupted: 0, notifications: 0 };

// Which run of each listing is current. An offset is only meaningful against the
// question that produced it, so starting a listing again — a band unchecked, the
// button pressed a second time — retires every page still in flight from the last
// one: a stale answer renders nothing and advances nothing.
//
// Without it a response arriving after the restart appends rows the current filter
// did not ask for and moves the offset the *next* page is read at, which skips
// beliefs — and a belief with no rendered row has no `Forget` control, so the failure
// costs the owner a control rather than a little tidiness.
const runs = { beliefs: 0, questions: 0, interrupted: 0, notifications: 0 };

// A full page says so and offers the next one.
//
// **A listing that stopped silently would hide a belief the owner cannot then
// delete**, which is this surface's whole promise — ADR-0073 §1 makes the read an
// enumeration precisely so what is past a page stays reachable, and the browser's
// only route to `forget` is a rendered row.
function offerMore(list, returned, again) {
  if (returned < PAGE) {
    return;
  }
  const note = line(list, "That is a full page; there may be more.", "hint");
  const more = document.createElement("button");
  more.type = "button";
  more.textContent = "Show more";
  more.addEventListener("click", () => {
    list.removeChild(note);
    list.removeChild(more);
    again();
  });
  list.appendChild(more);
}

function bandFilter() {
  const chosen = [
    { value: "asserted", box: el("band-asserted") },
    { value: "derived", box: el("band-derived") },
    { value: "attested", box: el("band-attested") },
  ].filter((one) => one.box.checked);
  // All three checked sends **no** filter rather than a list of three. The two are
  // the same answer today and not tomorrow: an absent filter means every band, and
  // stays right if a band is ever added, while a list of three would quietly become
  // a proper subset.
  return chosen.length === 3 ? null : chosen.map((one) => one.value);
}

// Start the belief listing again, from the first page. Reached from the panel's own
// button and from every band checkbox, because an offset counted against one filter
// means nothing against another: a band unchecked between two pages would otherwise
// skip the beliefs the narrower question puts first.
async function listBeliefs() {
  runs.beliefs += 1;
  readSoFar.beliefs = 0;
  await readBeliefs(false, runs.beliefs);
}

// One page of beliefs, from the start or from where the last one stopped.
//
// The filter is captured **before** the read and travels with it, so the page that
// arrives is rendered against the question it was asked — and the run check after the
// await is what retires it if the owner has since asked a different one.
async function readBeliefs(more, run) {
  fault(null, "beliefs");
  if (run !== runs.beliefs) {
    return;
  }
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const bands = bandFilter();
  const asked = { limit: PAGE, offset: readSoFar.beliefs };
  if (bands !== null) {
    asked.bands = bands;
  }
  try {
    const body = await relay(half, "/beliefs", asked, "beliefs");
    if (body === null || run !== runs.beliefs) {
      return;
    }
    const list = el("belief-list");
    if (!more) {
      clearNode(list);
    }
    if (body.beliefs.length === 0 && !more) {
      line(list, "No live belief matches.", "hint");
    }
    body.beliefs.forEach((one) => renderBelief(list, one));
    readSoFar.beliefs += body.beliefs.length;
    offerMore(list, body.beliefs.length, () => readBeliefs(true, run));
    show("beliefs", true);
  } catch (_) {
    fault(GATEWAY_GONE, "beliefs");
  }
}

// The band's own name, in the words a person reads it in. Every belief carries one
// and it is never left to be implied by position (ADR-0073 §4).
function bandWords(band) {
  if (band === "asserted") {
    return "You told me";
  }
  if (band === "derived") {
    return "I worked it out";
  }
  if (band === "attested") {
    return "A connected source reported it";
  }
  return band;
}

// Why a belief is held — band-dependent, and the answer is complete for all three
// bands since ADR-0189 §2 gave the projection somewhere to put the attestation.
//
// **The floor is what stops the gap being papered over.** A derived belief conveys
// how many citations stand behind it and is never presented as carrying a warrant
// this surface cannot show; an attested one **names the reporting source and states
// the instant that source said the fact was current** (ADR-0189 §4), and the line
// still says outright that "last revised" is this system's clock rather than the
// source's — which matters more now, not less, because there are two instants on the
// screen and ADR-0073 §4 forbids offering ours as the source's. Beside any rendered
// count sits ADR-0107 §5's ceiling, because a displaced citation is not a lost one.
//
// This line used to say the source and the instant were recorded and could not be
// shown here. That was true while the projection dropped them, and it is the
// limitation #1276 tracked; ADR-0189 §2 removed the limitation, so the sentence goes.
//
// **The source is named at source granularity and no finer.** ADR-0098 §8's third
// clause is adopted unchanged by ADR-0189 §4: no surface claims to identify the author
// within a source, so the value is apposed to "a connected source" and cannot be read
// as a person. ADR-0093 §7 forbids deriving a reader's identity from the source's
// location or contents, so the organiser of an invite and the sender of a mail are not
// on the record and cannot be. Where a display label exists it renders in the
// identity's place and the identity is the fallback (ADR-0189 §5, ADR-0093 §7's own
// wording) — no label is configured anywhere yet, ADR-0189 §8 leaves the mechanism to
// the registry lane, and no response on this surface carries one.
function whyHeld(belief) {
  if (belief.band === "asserted") {
    return "You told me, and your own word is the whole of it.";
  }
  if (belief.band === "attested") {
    // Off-contract rather than impossible: ADR-0189 §2 adds no cross-field validator
    // to the belief DTOs, so the type admits a state no store produces. Claiming
    // nothing was recorded would err in the direction ADR-0073 §4 forgives least, and
    // the old sentence would claim a limit this projection no longer has — what is
    // true either way is that this surface was not handed it.
    if (belief.attestation === null) {
      return (
        "A source you connected reported it — neither your word nor my inference. " +
        "What reached me here does not name that source or say when it spoke, so " +
        "'last revised' is when I changed my mind and not when the source spoke."
      );
    }
    return (
      `A connected source reported it — ${belief.attestation.reported_by}, neither ` +
      "your word nor my inference. That source said this was current as of " +
      `${belief.attestation.reported_at}, on its own clock; 'last revised' is when ` +
      "I changed my mind and not when the source spoke."
    );
  }
  return whyDerived(belief);
}

// That a **derived** belief's warrant came from outside, or nothing (ADR-0189 §4).
//
// Read off the projection's own field beside its band, and never recomputed from the
// band: ADR-0189 §2 forbids that in as many words, and a client re-deriving the
// disjunction is exactly how its second half gets dropped (ADR-0106 §2).
//
// **It says nothing about the belief's own content, and that prohibition is the
// clause itself.** §4: a surface "does **not** present the record's own content as
// third-party text on that ground: the content is a sentence this system's model
// wrote". ADR-0098 §7's own round-6 draft made that reach and had to be repaired, so
// this names the warrant and affirms the words are ours in one breath.
//
// **And it is silent on false rather than negative.** A false is *nothing external is
// recorded in this warrant*, never *nothing external influenced it* (ADR-0098 §5) —
// the link is unrecoverable once a model's output is recorded truthfully, so a line
// claiming the negative would assert what no field holds.
function outsideWarrant(rests) {
  return rests
    ? " Some of what I worked it out from came from a connected source rather than " +
        "from you — the belief above is still my own sentence, but its warrant is " +
        "not entirely mine."
    : "";
}

function whyDerived(belief) {
  const ceiling =
    belief.evidence_elided > 0
      ? ` Up to ${belief.evidence_elided} more piece(s) stood behind it that I no ` +
        "longer keep a reference to — those may still exist; I stopped carrying " +
        "them, they were not lost."
      : "";
  // Appended once here rather than per branch, for the ceiling's own reason: ADR-0189
  // §4 binds the clause to the band and not to any of the four count states, so a
  // per-branch append would be four chances to forget it — and the belief whose
  // warrant came from outside is the one a user needs told on every one of them.
  const outside = outsideWarrant(belief.rests_on_recorded_external_content);
  if (belief.evidence_count === 0) {
    return (
      (ceiling
        ? "I worked it out, and I carry no evidence for it now."
        : "I worked it out, and no supporting evidence was recorded.") +
      ceiling +
      outside
    );
  }
  if (belief.unsupported) {
    return (
      `I worked it out from ${belief.evidence_count} piece(s) of evidence, none of ` +
      "which still exists. I still hold it — I have not unlearnt it because the " +
      (ceiling ? "evidence went." : "evidence went — but nothing supports it any more.") +
      ceiling +
      outside
    );
  }
  if (belief.lost_evidence > 0) {
    return (
      `I worked it out from ${belief.evidence_count} piece(s) of evidence, ` +
      `${belief.lost_evidence} of which no longer exists. The confidence shown ` +
      "reflects what is left." +
      ceiling +
      outside
    );
  }
  return (
    `I worked it out from ${belief.evidence_count} piece(s) of evidence.` + ceiling + outside
  );
}

// One belief, carrying everything ADR-0073 §4 requires of both views: the band, the
// confidence, the kind, the content, why it is held, when it was last revised, the
// end of its validity window where one is set, and its id.
function renderBeliefFields(item, belief) {
  line(
    item,
    `${bandWords(belief.band)} · ${belief.kind} · confidence ${belief.confidence.toFixed(2)}`,
    "hint"
  );
  line(item, belief.content, "reply");
  line(item, `Why: ${whyHeld(belief)}`, "hint");
  line(item, `Last revised: ${belief.last_updated}`, "hint");
  if (belief.valid_until !== null) {
    line(item, `Believed until: ${belief.valid_until}`, "hint");
  }
  line(item, `id: ${belief.id}`, "hint");
}

function renderBelief(list, belief) {
  const item = document.createElement("div");
  item.className = "belief-row";
  renderBeliefFields(item, belief);
  const forget = document.createElement("button");
  forget.type = "button";
  forget.textContent = "Forget";
  forget.addEventListener("click", () => forgetBelief(belief.id));
  item.appendChild(forget);
  list.appendChild(item);
}

// What destroying a belief in this band costs (ADR-0073 §5). The ceremony is
// uniform in mechanism and asymmetric in message, because the consequence is: the
// surface must represent a deletion as neither more final than it is nor less.
function forgetWarning(band) {
  if (band === "asserted") {
    return "You told me this. Forgetting it is permanent — nothing can work it out again.";
  }
  if (band === "attested") {
    return (
      "A connected source reported this. Forgetting it destroys my copy but not the " +
      "source, so a later sync may bring it back."
    );
  }
  return (
    "I worked this out. Forgetting it destroys the belief but not what I worked it " +
    "out from, so I may reach it again."
  );
}

// Show, then confirm (ADR-0073 §5, ADR-0177 §5).
//
// **The render comes from a `belief` read issued immediately before the
// confirmation**, and never from the listing this page is displaying. A page holds
// its listing until it is navigated away from, so a listing is not a read taken "as
// late as it can be" — and a browser is the first surface where the difference is
// unbounded.
//
// What the confirmation covers is stated as ADR-0073 §5 states it: consent to
// forget the belief that id names, not a guarantee that the bytes destroyed are the
// bytes rendered.
async function forgetBelief(id) {
  fault(null, "beliefs");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const held = await relay(half, "/belief", { record_id: id }, "beliefs");
    if (held === null) {
      return;
    }
    const belief = held.belief;
    // Every field ADR-0073 §4 requires, from the read just taken — the window's end
    // included, where one is set. A confirmation that showed the listing's fields but
    // dropped one of them would be showing *less* than the screen the user came from,
    // which is the opposite of what a ceremony is for.
    const until =
      belief.valid_until === null ? "" : `\nBelieved until: ${belief.valid_until}`;
    const asked = window.confirm(
      `About to forget this belief.\n\n${bandWords(belief.band)} · ${belief.kind} · ` +
        `confidence ${belief.confidence.toFixed(2)}\n${belief.content}\n\n` +
        `Why: ${whyHeld(belief)}\nLast revised: ${belief.last_updated}${until}\n` +
        `id: ${belief.id}\n\n` +
        `${forgetWarning(belief.band)}\n\nThis destroys the record: nothing of it is ` +
        "kept, not even in an export. To fix it instead, tell me it is wrong in a " +
        "conversation.\n\nYou are forgetting whatever belief that id names when you " +
        "answer, which may have changed since it was shown."
    );
    if (!asked) {
      return;
    }
    const done = await relay(half, "/belief/forget", { record_id: id }, "beliefs");
    if (done === null) {
      return;
    }
    if (!done.destroyed) {
      fault("There was nothing live by that id to destroy.", "beliefs");
    }
    await listBeliefs();
  } catch (_) {
    fault(GATEWAY_GONE, "beliefs");
  }
}

// --- the deferred-question surface (ADR-0078 §8, §9) -------------------------

// Start both question listings again.
//
// **One generation is taken for the whole invocation and carried into each read.**
// Two listings means two awaits, and a run that is retired during the first one would
// otherwise reach the second and snapshot whatever number is current *then* — so two
// overlapping refreshes would both be accepted, both read offset zero, and both
// advance the same counter, putting the next page past a whole page of questions
// nobody can answer or destroy.
async function listQuestions() {
  const generation = {};
  Object.values(QUESTION_LISTS).forEach((listing) => {
    runs[listing.counter] += 1;
    generation[listing.counter] = runs[listing.counter];
    readSoFar[listing.counter] = 0;
  });
  for (const path of Object.keys(QUESTION_LISTS)) {
    await readQuestions(path, false, generation[QUESTION_LISTS[path].counter]);
  }
}

//: Which listing is which, in one place: the path it is read from, the node it is
//: rendered into, the counter it advances, and what an empty one says. Two listings
//: rather than one filtered, because they answer different questions (ADR-0078 §9).
const QUESTION_LISTS = {
  "/questions": {
    node: "question-list",
    counter: "questions",
    empty: "Nothing is waiting for you.",
  },
  "/questions/interrupted": {
    node: "interrupted-list",
    counter: "interrupted",
    empty: "No answer was begun and left unrecorded.",
  },
};

// One page of one question listing. Paged for `readBeliefs`' reason one surface over:
// a question past the first page would be one the owner can neither answer nor
// destroy, and a rendered row is the only route to either.
async function readQuestions(path, more, run) {
  fault(null, "questions");
  const listing = QUESTION_LISTS[path];
  if (run !== runs[listing.counter]) {
    return;
  }
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const offset = readSoFar[listing.counter];
  try {
    const body = await relay(half, path, { limit: PAGE, offset }, "questions");
    if (body === null || run !== runs[listing.counter]) {
      return;
    }
    const list = el(listing.node);
    if (!more) {
      clearNode(list);
    }
    if (body.questions.length === 0 && !more) {
      line(list, listing.empty, "hint");
    }
    // The offset each row was read at travels with it, because the ceremony that
    // destroys a question re-reads the listing it came from and must ask for the same
    // window — a re-read of the first page would report a question on the second as
    // gone (ADR-0177 §5's fifth clause).
    body.questions.forEach((one) => renderQuestion(list, one, path, offset));
    readSoFar[listing.counter] += body.questions.length;
    offerMore(list, body.questions.length, () => readQuestions(path, true, run));
    show("questions", true);
  } catch (_) {
    fault(GATEWAY_GONE, "questions");
  }
}

// One question, with everything ADR-0078 §8 requires it to convey — worded as the
// conditional it is, because a pending question is not a belief of any band.
// Everything ADR-0078 §8 requires a question to convey, without the controls the
// panel puts beside it — so a routed `questions` listing and a routed
// `forget_question`'s candidates read exactly as this panel does, and carry no
// answer or destroy control of their own (ADR-0197 §12, ADR-0186 §8's last clause
// read one record kind over). The interrupted notice is a **fact about the
// question** and belongs here; answering it is a control and does not.
function renderQuestionFields(item, question) {
  line(item, question.content, "reply");
  line(
    item,
    `Would be held as: ${bandWords(question.band)} · ${question.kind} ` +
      "(not held yet — I am asking first)",
    "hint"
  );
  line(item, `Why I am asking: ${question.reason}`, "hint");
  line(item, `Proposed because: ${question.rationale}`, "hint");
  const origin = proposalOrigin(question);
  if (origin) {
    line(item, `Where it came from: ${origin}`, "hint");
  }
  renderRetirements(item, question);
  line(item, `Asked: ${question.asked_at}`, "hint");
  line(
    item,
    question.expires_at === null
      ? "Answerable: indefinitely"
      : `Answerable until: ${question.expires_at}`,
    "hint"
  );
  if (question.state === "interrupted") {
    line(
      item,
      "An answer to this was begun and its outcome was never recorded. I cannot " +
        "tell you whether the change landed, so there is nothing to retry — dispose " +
        "of it, then check what I believe.",
      "notice"
    );
  }
}

function renderQuestion(list, question, path, offset) {
  const item = document.createElement("div");
  item.className = "question-row";
  renderQuestionFields(item, question);
  if (question.state !== "interrupted") {
    offerAnswer(item, question);
  }
  renderSuccessor(item, question.successor);
  const destroy = document.createElement("button");
  destroy.type = "button";
  destroy.textContent = "Forget the question";
  destroy.addEventListener("click", () => forgetQuestion(question.id, path, offset));
  item.appendChild(destroy);
  list.appendChild(item);
}

// Where the **proposal** came from, or nothing to say (ADR-0189 §4, §9).
//
// Both fields read here describe the record that would be written if the question were
// accepted — the same reading `band` already has on this type — and describe **no
// entry in `retires`** (ADR-0189 §2). Each retirement answers for itself through its
// own `warrant`, which `retirementOrigin` reads, and the two must not be run together:
// a question proposing the user's own assertion routinely retires an attested calendar
// line, so one answer could never serve for both.
//
// **The attested arm is why ADR-0189 §9 names this renderer by hand.** §4 binds every
// surface that renders an attested belief, question or retirement, and a question is
// the projection the first attested proposals actually reach — a lane that rewrote
// only the belief explanation would have left the surface §4 was written for
// unchanged. Nothing here says the proposal *is* held: a pending question is not a
// belief of any band, and the band line above it stays the conditional it was.
//
// **The band selects the arm, and an attestation's presence never does.** ADR-0189 §2
// adds no cross-field validator to this type, so a question banded `asserted` carrying
// an attestation is model-valid and crosses this wire — and a renderer keyed on the
// attestation would introduce the user's own word as a connected source's report. That
// is the laundering ADR-0072 §4 forbids in its own words: classification is keyed on
// the source and never on a decoration, so "nothing may acquire the standing of a band
// it is not in by decorating itself".
//
// The attested-with-no-attestation arm gets the honest sentence `whyHeld` gives its
// own, for the same reason: this projection is not what dropped the fact, so "not
// recorded" would err in the direction ADR-0073 §4 forgives least, and silence would
// leave the one band whose whole purpose is provenance saying nothing.
function proposalOrigin(question) {
  if (question.band === "attested") {
    if (question.attestation === null) {
      return (
        "A source you connected reported it, and what reached me here " +
        "does not name that source or say when it spoke."
      );
    }
    return (
      `A connected source reported it — ${question.attestation.reported_by}, which ` +
      `said this was current as of ${question.attestation.reported_at}, on that ` +
      "source's own clock."
    );
  }
  if (question.band === "derived" && question.rests_on_recorded_external_content) {
    return (
      "I worked it out, and some of what I worked it out from came from a connected " +
      "source rather than from you."
    );
  }
  return "";
}

// How a retired record's content is introduced, and what is said about it (§4).
//
// ADR-0189 §4 rules three arms over a retirement, and telling them apart is the whole
// of what #673 asked for. Before `warrant` existed this list rendered
// attacker-authorable calendar text under "Accepting would retire:" with **no origin
// marker at all** — a third party's sentence carried on the assistant's authority, at
// the one screen where the user is deciding. ADR-0098 §7 names that as the failure
// escalation is meant to prevent: "Escalating to the user is not a mitigation if the
// escalation is where the attacker's sentence is read as ours."
//
// * **attested** — the content **is** presented as third-party content, and the source
//   and the instant it spoke are named beside it.
// * **asserted** — the user's own word (ADR-0038 §1a), and §4 forbids presenting it as
//   third-party.
// * **derived** — this system's own sentence, likewise not third-party; where its
//   *warrant* rests on recorded external content that is said about the warrant and
//   never about the words.
//
// An earlier draft of ADR-0189 ruled the third-party presentation unconditionally and
// architecture review caught it on round 3: it would have rendered a retirement of the
// user's own assertion as somebody else's words. The band decides, and the band lives
// inside `warrant` rather than on the retirement, which is why it is read there.
//
// **The lead comes before the content and not after it.** A marker read *after* the
// sentence it qualifies has already let that sentence land as ours, and this is a
// confirmation prompt — the user is deciding while they read.
function retirementOrigin(warrant) {
  // Off-contract rather than impossible: ADR-0189 §2 puts the content/warrant tie on
  // the producer and adds no validator. It is not rendered as *no longer held* — the
  // content is right there — and it asserts no band, no origin and no source.
  if (warrant === null) {
    return {
      lead: "origin unrecorded —",
      note: "I cannot say how this was held or what reported it.",
      className: "hint",
    };
  }
  if (warrant.band === "attested") {
    return {
      lead: "someone else's words —",
      note:
        warrant.attestation === null
          ? "A connected source reported this. These are not my words and not yours."
          : `${warrant.attestation.reported_by} reported this, and said it was ` +
            `current as of ${warrant.attestation.reported_at}, ` +
            "on that source's own clock. These are not my words and not yours.",
      className: "notice",
    };
  }
  if (warrant.band === "asserted") {
    return {
      lead: "your own words —",
      note: "You told me this; it is neither a source's report nor my inference.",
      className: "hint",
    };
  }
  return {
    lead: "my own inference —",
    note:
      "I worked this out, so these are my words rather than a source's." +
      (warrant.rests_on_recorded_external_content
        ? " Some of what I worked it out from came from a connected source rather " +
          "than from you."
        : ""),
    className: "hint",
  };
}

// Exactly what accepting would retire (ADR-0078 §8, ADR-0189 §4), which is not
// decoration but the exact scope the answer authorises. A conflict already retired is
// rendered as no longer held rather than omitted: omitting it would understate the
// answer's scope in one direction and overstate it in the other.
//
// The **unresolved** entry deliberately gains nothing. ADR-0189 §4's last retirement
// clause: where the warrant is absent the surface "renders it as *no longer held* …
// and asserts nothing about its band, its origin or its source. It renders no third
// state as `false` and no absence as a value." There is no attested tombstone to
// build — §2 makes `warrant` and `content` null together — so this line is exactly the
// sentence it was.
//
// Every value on both arms reaches the page through `line`, which writes into the
// document's own text node and never as markup (ADR-0168 §6, ADR-0042 §4, ADR-0189
// §9's last clause but one). A `reported_by` is a value this system declared and a
// `reported_at` is an instant, but a retirement's `content` is neither, and the line
// that renders them together neutralises all of them the same way.
//
// **Two properties are what make the attribution unforgeable, and both are structural
// rather than remembered.** The adapter-authored lead is written *before* the content
// within its element, so the first attribution a reader meets is always ours; and
// `.hint` and `.notice` declare no `white-space: pre-wrap` — unlike `.reply` and
// `.notification-detail`, which do and say why — so a newline inside a content
// collapses to a space instead of forging a second line under a marker this file
// wrote. That is #1336's argument for `_safe` eating `\n`, reaching the same
// conclusion on the other target by a different mechanism.
function renderRetirements(item, question) {
  if (question.retires.length === 0) {
    line(item, "Accepting would retire: nothing", "hint");
    return;
  }
  line(item, "Accepting would retire:", "hint");
  question.retires.forEach((one) => {
    if (one.content === null) {
      line(item, `${one.record_id} — no longer held, so accepting would not touch it`, "hint");
      return;
    }
    const origin = retirementOrigin(one.warrant);
    line(item, `${origin.lead} ${one.content} (${one.record_id})`, origin.className);
    line(item, origin.note, "hint");
  });
}

// The question an answer already raised, rendered **by its own state** (ADR-0078
// §9): only a waiting successor is something the user can go and answer, and
// calling a declined or interrupted one "the follow-on question" advertises
// something they cannot act on.
function renderSuccessor(item, successor) {
  if (successor === null) {
    return;
  }
  if (successor.state === "open") {
    line(item, `Your answer raised a further question, which is waiting: ${successor.id}`, "notice");
    return;
  }
  if (successor.state === "declined") {
    line(
      item,
      `Your answer landed on a question you had already declined: ${successor.id} ` +
        "(forget it to be asked again)",
      "notice"
    );
    return;
  }
  if (successor.state === "interrupted") {
    line(
      item,
      `Your answer landed on another interrupted answer: ${successor.id} (dispose of that one too)`,
      "notice"
    );
    return;
  }
  line(item, `Your answer raised a further question, since settled: ${successor.id}`, "hint");
}

function offerAnswer(item, question) {
  const accept = document.createElement("button");
  accept.type = "button";
  accept.textContent = "Yes, believe it";
  accept.addEventListener("click", () => answerQuestion(question.id, true));
  const reject = document.createElement("button");
  reject.type = "button";
  reject.textContent = "No";
  reject.addEventListener("click", () => answerQuestion(question.id, false));
  item.appendChild(accept);
  item.appendChild(reject);
}

async function answerQuestion(id, accept) {
  fault(null, "questions");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const panel = beginActs("Answering.");
  try {
    const body = await relay(half, "/question/answer", { question_id: id, accept }, "questions");
    if (body === null) {
      return;
    }
    renderAnswer(panel, body.answered);
    await listQuestions();
  } catch (_) {
    fault(GATEWAY_GONE, "questions");
  }
}

// What one answer did, as one of five outcomes (ADR-0078 §5, §9). A re-deferral is
// reported as a **completed** answer carrying the next question rather than as a
// failure: the answer was used, and it raised something new.
function renderAnswer(panel, outcome) {
  if (outcome.kind === "applied") {
    line(panel, `Applied. That is what I believe now (${outcome.record_id}).`, "reply");
  } else if (outcome.kind === "rejected") {
    line(
      panel,
      "Declined. Nothing was written, and I will not ask you this again — forget " +
        "the question if you want to be asked.",
      "reply"
    );
  } else if (outcome.kind === "stale") {
    line(
      panel,
      "Not applied. What that question was about no longer applies, so accepting it " +
        "would have stored a belief that was already out of date.",
      "notice"
    );
  } else if (outcome.kind === "not_open") {
    line(
      panel,
      "That question is not open. It may never have existed, or it may have lapsed, " +
        "been answered, or have an answer already in flight.",
      "notice"
    );
  } else {
    line(
      panel,
      "Not applied yet. Your answer was used, but it turned out to contradict " +
        "something else you told me that you had not been shown.",
      "notice"
    );
    if (outcome.successor === null && outcome.successor_refused) {
      line(
        panel,
        "The question queue is full, so I could not put the follow-up to you. Answer " +
          "or forget some of what is waiting, then teach me the correction again.",
        "notice"
      );
    }
  }
  renderSuccessor(panel, outcome.successor);
  if (outcome.disposed) {
    line(
      panel,
      "That question was destroyed while your answer was being applied, so no record " +
        "of the answer was kept.",
      "hint"
    );
  }
}

// The ceremony ADR-0177 §5 gives this verb at this surface: the question is
// rendered from a listing read **immediately before** the confirmation, and
// `forget_question` is sent only for a question that read returned.
//
// No single-question read is added and none is needed (#495's third ground, cited
// and not absorbed): the two listings ADR-0078 §8 already gives return the question
// whole, and re-reading one is a call this page already makes.
async function forgetQuestion(id, path, offset) {
  fault(null, "questions");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const body = await relay(half, path, { limit: PAGE, offset }, "questions");
    if (body === null) {
      return;
    }
    const question = body.questions.find((one) => one.id === id);
    if (question === undefined) {
      fault(QUESTION_GONE, "questions");
      await listQuestions();
      return;
    }
    const asked = window.confirm(
      `About to destroy this question.\n\n${question.content}\n\n` +
        `Would be held as: ${bandWords(question.band)} · ${question.kind}\n` +
        `Why I am asking: ${question.reason}\nAsked: ${question.asked_at}\n\n` +
        "Destroying it means I will not put it to you again, and its subject can be " +
        "raised afresh. It does not answer it, and it writes nothing."
    );
    if (!asked) {
      return;
    }
    const done = await relay(half, "/question/forget", { question_id: id }, "questions");
    if (done === null) {
      return;
    }
    await listQuestions();
  } catch (_) {
    fault(GATEWAY_GONE, "questions");
  }
}

// --- the notification review surface (ADR-0177 §10; ADR-0130 §6, §7, §9) -----
//
// **What everything below acts on is the notification *record*.** The panel further
// up fills from the delivery stream and is about a *delivery*; these are two objects
// and the surface says so. Nothing here acknowledges, retires, withdraws or
// completes a delivery, no `delivery_id` is read or sent, and dismissing a record
// says nothing about whether it was ever delivered — nor does having received a
// delivery say anything about the record's disposition.

// How far a class may reach you, named in words. **All three, wherever a choice is
// offered**: `off` in particular is the act ADR-0130 §6 makes reach "every actionable
// held record of that class", so a control that could not send it would leave "never
// tell me this" unreachable from a browser.
const REACHES = [
  { value: "off", label: "Never tell me this" },
  { value: "hold", label: "Keep it for when I next look" },
  { value: "interrupt", label: "May reach me at the time" },
];

// What a class takes when no preference names it (ADR-0130 §6). Stated here because
// the tuning panel lists only the classes the user has set, and a reader has to be
// told what everything else does.
const DEFAULT_REACH = "hold";

// What each condition of a ruling means, in words rather than in the values on the
// wire. Total over the vocabulary: a ruling rendered with a missing explanation
// would answer "why did you not tell me?" with nothing, and the conditions are
// exactly what a user would have to change.
//
// Each is worded in the one polarity it is ever shown in, which the vocabulary makes
// safe — the four drop conditions are a DROP's reason and the four interrupt
// conditions appear only in a HOLD's failed set, where every entry is a condition
// that did **not** hold.
const CONDITIONS = {
  expired: "it had already perished by the time I ruled on it",
  reach_off: "you have set that class to never tell you",
  duplicate: "I am already holding the same thing",
  at_cap: "I am holding as many notifications as I may",
  perishable: "it names no moment it stops mattering, so nothing makes it urgent",
  reach_interrupt: "that class is not set to interrupt you",
  quiet_window: "it fell inside your quiet hours",
  budget: "your interruption budget for that window was already used up",
};

const NOTIFICATION_GONE =
  "That notification was not in the list I just read, so I sent nothing. It may " +
  "have been forgotten already since the page last showed it.";

// A condition named by a ruling, in words — and never dropped when it is a name this
// page does not carry. Rendering the bare name says less than the phrase and far
// more than nothing, which is what omitting it would say.
function conditionPhrase(name) {
  return CONDITIONS[name] || name;
}

// Start the listing again, from the first page.
async function listNotifications() {
  runs.notifications += 1;
  readSoFar.notifications = 0;
  await readNotifications(false, runs.notifications);
}

// One page of held notifications, oldest first (ADR-0130 §7).
//
// **Everything retained is here, an expired record included.** Expiry ends
// interruptibility and actionability and deletes nothing, so a listing that hid one
// would hide a record the owner can still destroy — and destroying it is the only
// way its subject can be raised afresh.
async function readNotifications(more, run) {
  fault(null, "review");
  if (run !== runs.notifications) {
    return;
  }
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const offset = readSoFar.notifications;
  try {
    const body = await relay(half, "/notifications", { limit: PAGE, offset }, "review");
    if (body === null || run !== runs.notifications) {
      return;
    }
    const list = el("review-list");
    if (!more) {
      clearNode(list);
    }
    if (body.notifications.length === 0 && !more) {
      line(
        list,
        "I am holding nothing for you. Nothing reaches you unprompted until you say " +
          "it may — see what you have decided, above.",
        "hint"
      );
    }
    body.notifications.forEach((one) => renderHeldNotification(list, one, offset));
    readSoFar.notifications += body.notifications.length;
    offerMore(list, body.notifications.length, () => readNotifications(true, run));
    show("review", true);
  } catch (_) {
    fault(GATEWAY_GONE, "review");
  }
}

// One held record, with what a person needs in order to act on it.
//
// **A record still actionable is offered the two acts ADR-0130 §6 names in one step**
// — dismissing it, and changing how far its class may reach — and both are offered on
// a held record and not on an interruption alone, a held one being exactly what a
// person wants to dispose of or to unblock.
//
// **Actionability is read in two parts, and the split is about whose clock decided
// each.** A dismissal and a reconsideration's ruling-out are stamped by the hub, so
// either ends the offer whatever any clock here reads; expiry is the limb with
// nothing stored, and the gateway answers it by asking the record's own predicate at
// one reading for the whole page.
function renderHeldNotification(list, record, offset) {
  const item = document.createElement("div");
  item.className = "notification-row";
  line(item, record.summary, "notification-summary");
  if (record.detail) {
    line(item, record.detail, "notification-detail");
  }
  // The class and the producer are producer-declared text and are presented as what
  // they are: this says a notification is held and what it is about, never that the
  // assistant vouches for it.
  line(item, `Class: ${record.notification_class} (noticed by ${record.producer})`, "hint");
  renderRuling(item, record);
  line(item, `Noticed: ${record.noticed_at}`, "hint");
  renderExpiry(item, record);
  offerNotificationActs(item, record, offset);
  list.appendChild(item);
}

// What was decided about one record and why.
//
// A held record is explained by its **whole** failed set rather than by its reason
// alone: the reason is the set's first member, so naming it by itself would answer
// with one of several true answers and hide the rest.
function renderRuling(item, record) {
  if (record.kind === "interrupt") {
    line(item, "Ruled: to reach you at the time", "hint");
  } else if (record.kind === "hold") {
    line(item, "Ruled: held for when you next look", "hint");
  } else {
    line(item, `Ruled: ruled out — ${conditionPhrase(record.reason)}`, "hint");
  }
  record.failed.forEach((condition) => {
    line(item, `Not now, because: ${conditionPhrase(condition)}`, "hint");
  });
  if (record.dismissed_at) {
    line(item, `Dismissed: ${record.dismissed_at}`, "hint");
  }
  if (record.dropped_at) {
    line(item, `Ruled out: ${record.dropped_at}`, "hint");
  }
}

// Which side of its expiry a record is on (ADR-0130 §7), from the gateway's own
// answer rather than from a comparison restated here. A record that declares no
// moment has not perished and never will, which is a third state and not the absence
// of the other two.
function renderExpiry(item, record) {
  if (record.expires_at === null) {
    line(item, "Expires: never — which is why it is held rather than urgent", "hint");
    return;
  }
  if (record.expired) {
    line(
      item,
      `Expired: ${record.expires_at} — it is kept and readable, and it will not reach you`,
      "notice"
    );
    return;
  }
  line(item, `Expires: ${record.expires_at}`, "hint");
}

function offerNotificationActs(item, record, offset) {
  const actionable = !record.dismissed_at && !record.dropped_at && !record.expired;
  if (actionable) {
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.textContent = "Dismiss";
    dismiss.addEventListener("click", () => dismissNotification(record.id));
    item.appendChild(dismiss);
  }
  const destroy = document.createElement("button");
  destroy.type = "button";
  destroy.textContent = "Forget";
  destroy.addEventListener("click", () => forgetNotification(record.id, offset));
  item.appendChild(destroy);
  // The second of the two acts §6 says a surface rendering one should offer, on the
  // record's own class. It is offered whatever the ruling, because the setting is
  // about the class and not about this record — and a record whose failed set names
  // the perishable condition is reached by no setting at all, which the line above
  // has already said in words.
  item.appendChild(
    reachControl(
      `How far may "${record.notification_class}" reach you?`,
      record.notification_class,
      null
    )
  );
}

// Deal with one notification and keep the record (ADR-0130 §9).
//
// **This is not an acknowledgement.** What ends is the record's actionability; it
// stays readable and stays in the export, and whether it ever reached a device is a
// different question about a different object.
async function dismissNotification(id) {
  fault(null, "review");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const done = await relay(half, "/notification/dismiss", { notification_id: id }, "review");
    if (done === null) {
      return;
    }
    if (!done.dismissed) {
      fault(
        "There was nothing actionable by that id to dismiss — it may have been " +
          "dismissed, ruled out or expired already.",
        "review"
      );
    }
    await listNotifications();
  } catch (_) {
    fault(GATEWAY_GONE, "review");
  }
}

// Destroy one notification, so its subject can be raised again (ADR-0130 §9).
//
// **The confirmation here is not ADR-0073 §5's ceremony and does not claim to be.**
// That ceremony binds a belief, and ADR-0177 §5 carries it to `forget`,
// `forget_question` and `forget_conversation` and stops there — a notification is not
// a belief of any band. What this is, is a plain confirmation of a destructive act,
// over a record re-read immediately before it is offered so that what is destroyed is
// something the page has just seen rather than something it last saw minutes ago.
async function forgetNotification(id, offset) {
  fault(null, "review");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const body = await relay(half, "/notifications", { limit: PAGE, offset }, "review");
    if (body === null) {
      return;
    }
    const record = body.notifications.find((one) => one.id === id);
    if (record === undefined) {
      fault(NOTIFICATION_GONE, "review");
      await listNotifications();
      return;
    }
    const asked = window.confirm(
      `About to destroy this notification.\n\n${record.summary}\n\n` +
        `Class: ${record.notification_class} (noticed by ${record.producer})\n` +
        `Noticed: ${record.noticed_at}\n\n` +
        "This destroys the record: it leaves your export, and the same thing can be " +
        "raised afresh afterwards. To deal with it and keep the record, dismiss it " +
        "instead. Neither act says anything about whether it reached a device."
    );
    if (!asked) {
      return;
    }
    const done = await relay(half, "/notification/forget", { notification_id: id }, "review");
    if (done === null) {
      return;
    }
    await listNotifications();
  } catch (_) {
    fault(GATEWAY_GONE, "review");
  }
}

// --- the standing settings (ADR-0130 §6, ADR-0177 §10) -----------------------
//
// **A read-modify-write, treated as one.** Every control below re-reads the whole
// value, changes the one thing it names, sends the whole value back, and renders
// what the call **returned** rather than what it sent. The write replaces what is
// held rather than merging into it, so a form that assembled a partial value from a
// read taken some time ago would silently revert a setting — and an act's outcome is
// a fact about that act, where what stands is a fact only the hub can state.

async function listTuning() {
  fault(null, "tuning");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const body = await relay(half, "/notification/preferences", {}, "tuning");
    if (body === null) {
      return;
    }
    renderTuning(body.preferences);
    show("tuning", true);
  } catch (_) {
    fault(GATEWAY_GONE, "tuning");
  }
}

// One act on the standing settings: read it whole, change the one thing named, write
// it whole, and render what came back.
async function writePreferences(change) {
  fault(null, "tuning");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const read = await relay(half, "/notification/preferences", {}, "tuning");
    if (read === null) {
      return;
    }
    const written = await relay(
      half,
      "/notification/preferences/set",
      change(read.preferences)
    );
    if (written === null) {
      return;
    }
    renderTuning(written.preferences);
    show("tuning", true);
  } catch (_) {
    fault(GATEWAY_GONE, "tuning");
  }
}

// The whole value with one class's reach changed, in place where the class is
// already named and appended where it is not. Nothing else is touched.
function withReach(held, notificationClass, reach) {
  const named = held.reaches.some((row) => row.notification_class === notificationClass);
  const reaches = held.reaches.map((row) =>
    row.notification_class === notificationClass
      ? { notification_class: notificationClass, reach }
      : row
  );
  if (!named) {
    reaches.push({ notification_class: notificationClass, reach });
  }
  return { ...held, reaches };
}

// Minutes since local midnight, as the wire carries them, rendered as a clock face.
function clockFace(minutes) {
  const hours = Math.floor(minutes / 60);
  return `${String(hours).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

// The other direction: what an `<input type="time">` holds, or `null` where it holds
// nothing readable. A blank field is not an hour and is not read as midnight.
function minuteOfDay(value) {
  const parts = /^(\d{2}):(\d{2})$/.exec(value);
  if (parts === null) {
    return null;
  }
  return Number(parts[1]) * 60 + Number(parts[2]);
}

// One reach chooser, carrying every member of the vocabulary and no proper subset.
// `current` is the level in force where the caller knows it, and `null` where the
// control sits beside a record rather than beside a setting — there the page has not
// read what the class is set to, and pre-selecting a level would state a setting it
// has not read back.
function reachControl(label, notificationClass, current) {
  const wrapper = document.createElement("p");
  wrapper.className = "choice";
  const caption = document.createElement("label");
  caption.textContent = label;
  const chooser = document.createElement("select");
  if (current === null) {
    const unread = document.createElement("option");
    unread.value = "";
    unread.textContent = "Choose a level";
    chooser.appendChild(unread);
  }
  REACHES.forEach((one) => {
    const option = document.createElement("option");
    option.value = one.value;
    option.textContent = one.label;
    option.selected = one.value === current;
    chooser.appendChild(option);
  });
  chooser.addEventListener("change", () => {
    if (chooser.value === "") {
      return;
    }
    writePreferences((held) => withReach(held, notificationClass, chooser.value));
  });
  wrapper.appendChild(caption);
  wrapper.appendChild(chooser);
  return wrapper;
}

function renderTuning(preferences) {
  const body = el("tuning-body");
  clearNode(body);
  renderReaches(body, preferences);
  renderQuietWindows(body, preferences);
  renderBudget(body, preferences);
}

function renderReaches(body, preferences) {
  const heading = document.createElement("h4");
  heading.textContent = "How far each class may reach you";
  body.appendChild(heading);
  if (preferences.reaches.length === 0) {
    line(body, "You have set none, so every class is held for when you next look.", "hint");
  }
  preferences.reaches.forEach((row) => {
    body.appendChild(reachControl(row.notification_class, row.notification_class, row.reach));
  });
  // The label is used as it is written. Case-folding it to fit mid-sentence turned
  // "Keep it for when I next look" into "keep it for when i next look", which is a
  // rendering deciding how a word is spelled — so the sentence is built around the
  // label rather than the label bent to fit the sentence.
  line(
    body,
    `A class you have not set takes the default — ${
      REACHES.find((one) => one.value === DEFAULT_REACH).label
    }.`,
    "hint"
  );
  const named = document.createElement("input");
  named.type = "text";
  named.id = "reach-class";
  named.placeholder = "A class, as a notification above names it";
  const caption = document.createElement("label");
  caption.textContent = "Set a class you have not set before";
  caption.htmlFor = "reach-class";
  const chooser = document.createElement("select");
  REACHES.forEach((one) => {
    const option = document.createElement("option");
    option.value = one.value;
    option.textContent = one.label;
    chooser.appendChild(option);
  });
  const save = document.createElement("button");
  save.type = "button";
  save.textContent = "Set";
  save.addEventListener("click", () => {
    if (named.value.trim() === "") {
      fault("Name the class to set. Every notification above prints its own.", "tuning");
      return;
    }
    writePreferences((held) => withReach(held, named.value, chooser.value));
  });
  const form = document.createElement("div");
  form.className = "scope-form";
  form.appendChild(caption);
  form.appendChild(named);
  form.appendChild(chooser);
  form.appendChild(save);
  body.appendChild(form);
}

function renderQuietWindows(body, preferences) {
  const heading = document.createElement("h4");
  heading.textContent = "Hours during which nothing interrupts";
  body.appendChild(heading);
  if (preferences.quiet_windows.length === 0) {
    line(body, "None, so no hour is quiet.", "hint");
  }
  preferences.quiet_windows.forEach((quiet, index) => {
    const row = document.createElement("p");
    row.className = "choice";
    const said = document.createElement("span");
    // Read in your own timezone, and the endpoints carry none: a quiet window is a
    // statement about the user's day.
    said.textContent = `${clockFace(quiet.start)} to ${clockFace(quiet.end)}${
      quiet.start > quiet.end ? ", crossing midnight" : ""
    }`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      writePreferences((held) => ({
        ...held,
        quiet_windows: held.quiet_windows.filter((_, at) => at !== index),
      }));
    });
    row.appendChild(said);
    row.appendChild(remove);
    body.appendChild(row);
  });
  body.appendChild(quietWindowForm());
}

function quietWindowForm() {
  const form = document.createElement("div");
  form.className = "scope-form";
  const caption = document.createElement("label");
  caption.textContent = "Add quiet hours (they may cross midnight)";
  const from = document.createElement("input");
  from.type = "time";
  from.id = "quiet-from";
  const to = document.createElement("input");
  to.type = "time";
  to.id = "quiet-to";
  const add = document.createElement("button");
  add.type = "button";
  add.textContent = "Add";
  add.addEventListener("click", () => {
    const start = minuteOfDay(from.value);
    const end = minuteOfDay(to.value);
    if (start === null || end === null) {
      fault("Give both an hour to start and an hour to end.", "tuning");
      return;
    }
    // Refused here rather than sent, because the refusal is about what was typed and
    // a person can act on it: a window whose endpoints are the same minute is
    // unreadable as either "nothing" or "everything", and a setting whose meaning a
    // reader has to guess at silently stops every interruption.
    if (start === end) {
      fault("A quiet window has to start and end at different times.", "tuning");
      return;
    }
    writePreferences((held) => ({
      ...held,
      quiet_windows: [...held.quiet_windows, { start, end }],
    }));
  });
  form.appendChild(caption);
  form.appendChild(from);
  form.appendChild(to);
  form.appendChild(add);
  return form;
}

// **The budget and the rolling window are strings and are kept as strings.** A JSON
// number is read into a double, so an integer above 2**53 does not survive the trip —
// and both of these are bounded well above it. The gateway spells them as decimal
// digits for that reason, and this page hands back the characters it was given: an
// edit to a reach must not quietly rewrite a budget nobody touched.
//
// The one place a number is made of one is the sentence below, and it never travels.
function renderBudget(body, preferences) {
  const heading = document.createElement("h4");
  heading.textContent = "How often I may interrupt you";
  body.appendChild(heading);
  const hours = Number(preferences.budget_window_microseconds) / 3.6e9;
  line(
    body,
    `${preferences.interruption_budget} interruption(s) per rolling ` +
      `${Number.isFinite(hours) ? hours : "?"} hour(s).` +
      (preferences.interruption_budget === "0"
        ? " Zero means never — it is a setting, not a fault."
        : ""),
    "hint"
  );
  const form = document.createElement("div");
  form.className = "scope-form";
  const caption = document.createElement("label");
  caption.textContent = "Interruptions per rolling window";
  caption.htmlFor = "budget";
  const count = document.createElement("input");
  count.type = "number";
  count.id = "budget";
  count.min = "0";
  count.step = "1";
  count.value = preferences.interruption_budget;
  const save = document.createElement("button");
  save.type = "button";
  save.textContent = "Save";
  save.addEventListener("click", () => {
    // Checked as characters and sent as characters: `Number` would accept the value
    // and then hand back a different one, which is the whole reason this member does
    // not travel as a number.
    const asked = count.value.trim();
    if (!/^[0-9]{1,20}$/.test(asked)) {
      fault("Give a whole number of interruptions, zero or more.", "tuning");
      return;
    }
    writePreferences((held) => ({ ...held, interruption_budget: asked }));
  });
  form.appendChild(caption);
  form.appendChild(count);
  form.appendChild(save);
  body.appendChild(form);
  // The rolling window itself is on no control here and travels untouched: it is one
  // of the three settings ADR-0130 §6 holds, the surface writes the value whole, and
  // a page that dropped it — or that rounded it by holding it as a number — would
  // reset it on every save.
}

// --- the connection surface (ADR-0177 §3, §4; ADR-0151; ADR-0149) ------------
//
// **A credential is entered on a loopback origin and nowhere else** (ADR-0177 §3).
// A page served from `http://127.0.0.1:8422` is a potentially trustworthy origin and
// one served from `http://100.x.y.z:8422` is not, whatever tunnel the second is
// inside (ADR-0174 §7) — so on the second the browser withholds every protection it
// has for a secret and tells the owner, correctly, that the page is not secure. This
// file reads its own origin rather than being told one, and the gateway decides the
// same thing from the listener the request arrived on, so neither half rests on the
// other being right.
//
// **The field is built here rather than shipped in the document, and never before
// the gateway has answered a read.** §4's fourth clause forbids presenting a
// credential field the gateway will refuse: "a surface that asked for a secret in
// order to discover it could not be used would be disclosing it to obtain a refusal".
// So the form exists only on a loopback page whose listing came back — which is also
// what covers the deployment §3's second clause refuses, where the gateway's own hub
// is remote and the listing is what says so.
//
// **What the value never touches**: no URL, no query string, no fragment, no cookie,
// no `localStorage` and no `sessionStorage`. It is read out of one input, sent in one
// JSON body, and the input is cleared and removed in the same breath. There is no
// `<form>` around it either, so there is no submission path that could put it in a
// query string even with the policy's `form-action 'none'` lifted.

// Whether this page's own origin is one a credential may be typed into (ADR-0177 §3,
// §4). `127.0.0.1` and nothing else, because that is the single authority the
// gateway's loopback listener admits a `Host` for — a page reachable at any other
// name is on the remote browser listener, where the two credential-carrying
// operations are refused.
const ON_LOOPBACK = window.location.hostname === "127.0.0.1";

// ADR-0151 §7's and §8's classification, keyed by the condition the gateway named.
//
// **Three facts a client may not derive from anything else**: whether the act landed,
// whether the reference exists, and whether the reference's state can be stated
// without a read. Each condition therefore gets its own sentence rather than one of
// three shared phrasings — `residual-credential` in particular means the act
// **completed**, and §8 forbids reporting it as a failed connection or disconnection.
//
// `stateKnown` is the CLI's own test one surface over: exactly two conditions settle
// the reference's state without a read, and both are refusals that never reached an
// act. Everything else leaves it unread, which §7 says is resolved by reading the
// connections and never by re-running the act.
const CONNECTION_CONDITIONS = {
  "identity-unusable": {
    // **What this may not claim is that the credential stayed here.** ADR-0151 §5
    // raises this "locally, before any I/O, by every implementation — the wire
    // client included — so no such call reaches the hub and no credential is sent
    // for one", and the implementation in question is the *gateway's* engine: the
    // value has already crossed the one hop this page controls by the time the
    // refusal happens. Telling an owner otherwise would reassure them about a Tier 0
    // value that has in fact travelled.
    words:
      "That account name was refused before the act began, so nothing was written " +
      "and no credential reached the hub. It did reach the gateway on this machine, " +
      "which held it for the call and kept nothing. Use a different name.",
    stateKnown: true,
  },
  "no-such-connection": {
    words:
      "There is no connection under that reference, so nothing was written. Read " +
      "the list again — a reference is minted by the hub and cannot be typed.",
    stateKnown: true,
  },
  "provisioning-displaced": {
    words:
      "Another act took the record over, so no record this act wrote is the live " +
      "one. That is not the same as nothing having been written, and nothing was " +
      "rolled back.",
    stateKnown: false,
  },
  "provisioning-incomplete": {
    words:
      "The act did not complete, and the reference it names exists. Nothing this " +
      "act wrote is the live credential, or ever becomes it.",
    stateKnown: false,
  },
  "provisioning-outcome-unknown": {
    words:
      "The outcome is not known. The reference exists, and whether the act " +
      "completed cannot be said either way — do not run it again on the assumption " +
      "it failed, which would replace a credential that may be live.",
    stateKnown: false,
  },
  "connection-store-unread": {
    words:
      "The connection store could not answer, so the outcome of this act is not " +
      "known — there may or may not be a reference.",
    stateKnown: false,
  },
  "residual-credential": {
    // **The only condition whose act *completed*, and the only one whose sentence is
    // therefore the act's own.** ADR-0151 §7 and §8 each guarantee a different
    // result — "after ``reprovision_account`` the reference is connected at the new
    // revision; after ``disconnect_account`` the reference has no live record" — so
    // one shared sentence would report neither. :js:data:`RESIDUAL` carries the
    // guaranteed half and this carries the residue they share.
    words:
      "What failed is deleting a credential the act was to remove, so an " +
      "unreferenced credential remains, named by the store and read by no call. " +
      "This is not a failed act. Disconnecting that reference again is what removes " +
      "the residue.",
    stateKnown: false,
  },
};

//: What each act guarantees, said before anything else and never withdrawn.
//
// The success line and the residual line are the same fact arriving two ways, which
// is why they sit together: ADR-0151 §8 requires a residual reported as a
// disconnection "and never as a failed disconnection", and §7 the same for a
// re-provisioning. A read taken afterwards says what is true *now* and can fail; what
// the act did is settled and is not revisited by it.
const ACTS = {
  connect: {
    landed: "Connected.",
    residual: "The account is connected.",
  },
  reprovision: {
    landed: "The credential was replaced.",
    residual: "The credential was replaced — the account is connected at the new revision.",
  },
  disconnect: {
    landed: "Disconnected. No live record names any credential for that reference any more.",
    residual: "Disconnected. The reference has no live record.",
  },
};

// Which remedies a condition prescribes on the reference it names, and which it does
// not. ADR-0151 §7 is explicit for two of them and silent for the rest, and the
// silence is load-bearing: on ``provisioning-outcome-unknown`` the resolution is "to
// read ``connected_accounts`` — **never by re-running the act on the assumption it
// failed**, which would rotate a credential that may already be live", and on
// ``provisioning-displaced`` there is "no reason to retry the same act blind". So a
// condition not named here offers nothing, and the read is what the page says instead.
const REMEDIES = {
  // "A client names the reference, says the act did not complete, says the
  // reference's state is unread, and offers ``reprovision_account`` or
  // ``disconnect_account`` on it — both safe whoever now owns the record, the first
  // by its own compare-and-swap and the second by being idempotent."
  "provisioning-incomplete": { replace: true, disconnect: true },
  // ADR-0149 §5 and ADR-0151 §7: an unreferenced credential is "removed by a
  // disconnection of that reference and by ADR-0149 §8's purge". Replacing is a
  // normal act rather than the remedy, so it is not offered as one.
  "residual-credential": { replace: false, disconnect: true },
};

const CONNECTION_STATE_UNREAD =
  "Nothing here says what that reference holds now: the read that would have stated " +
  "it did not answer. That takes nothing back from what is said above — an act's " +
  "outcome is a fact about that act, and the reference's state is a fact only the " +
  "hub can state.";

// What a live record's provisioning state means, in words (ADR-0148 §6, ADR-0151 §4).
//
// **A pending record is never rendered as something in progress.** ADR-0148 §6 rules
// an interrupted act's state "refused rather than reconciled": nothing is running,
// the act that wrote it is gone, and the remedy is for the owner to run the act
// again. Saying it "is being established" would promise a completion that no code
// anywhere will deliver.
function stateWords(state) {
  if (state === "active") {
    return "Connected.";
  }
  if (state === "pending") {
    return (
      "Not connectable. Nothing is running — the act that wrote this is gone and " +
      "nothing repairs it. Connect it again, or disconnect it."
    );
  }
  return `State: ${state}`;
}

async function listConnections() {
  fault(null, "connections");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const panel = el("connection-list");
  const form = el("connect-form");
  try {
    // The form is taken down before the read and put back only if the read answered.
    // A gateway that has started refusing — because its own hub moved to the remote
    // listener — must not leave a credential field standing from the last time it did
    // not (ADR-0177 §4's fourth clause).
    clearNode(form);
    const held = await relay(half, "/connections", {}, "connections");
    if (held === null) {
      show("connections", true);
      clearNode(panel);
      return;
    }
    clearNode(panel);
    show("connections", true);
    if (held.accounts.length === 0) {
      line(panel, "Nothing is connected.", "hint");
    }
    held.accounts.forEach((account) => renderAccount(panel, account));
    offerConnect(form);
  } catch (_) {
    fault(GATEWAY_GONE, "connections");
  }
}

// The three lines every rendering of a live record carries.
function renderRecordFields(item, account) {
  // The identity is the user-recognisable name they supplied, byte for byte, and it
  // is inserted as text (ADR-0151 §5, ADR-0168 §6).
  line(item, account.identity, "connection-identity");
  line(item, stateWords(account.state), account.state === "active" ? "hint" : "notice");
  // The reference is a minted, non-secret handle (ADR-0151 §3) and the revision is
  // reported exactly as the store holds it (§4) — never renumbered, and never
  // presented as a count of anything.
  line(item, `Reference: ${account.reference} · revision ${account.revision}`, "hint");
}

function renderAccount(list, account) {
  const item = document.createElement("div");
  item.className = "connection-row";
  renderRecordFields(item, account);
  offerConnectionActs(item, account);
  list.appendChild(item);
}

// A record inside the act log, which is a different thing from a row of the listing
// and is rendered as one.
//
// **No act buttons here, and the reason is ADR-0151 §8.** What a disconnection
// returns is "the live record removed, **as it stood immediately before the removal
// entry was appended**" — so a row offering `Disconnect` on it would be offering an
// act on something that no longer exists, and rendering it as a listing row would be
// this surface presenting an act's result as a statement about the store. The caption
// is what says which of the two this is.
function renderActRecord(panel, account, caption) {
  const item = document.createElement("div");
  item.className = "connection-row";
  line(item, caption, "hint");
  renderRecordFields(item, account);
  panel.appendChild(item);
}

// The two acts a row offers. Re-provisioning carries a credential, so it is offered
// only where one may be entered; disconnecting carries a reference, which ADR-0151 §3
// designed so that it is not a credential, so it is offered wherever the page is.
function offerConnectionActs(item, account) {
  if (ON_LOOPBACK) {
    const again = document.createElement("button");
    again.type = "button";
    again.textContent = "Replace the credential";
    again.addEventListener("click", () => offerConnect(el("connect-form"), account));
    item.appendChild(again);
  }
  const drop = document.createElement("button");
  drop.type = "button";
  drop.textContent = "Disconnect";
  drop.addEventListener("click", () => disconnectReference(account.reference, account));
  item.appendChild(drop);
}

// Step one of the ceremony ADR-0177 §4's fifth clause fixes: the identity is
// rendered, and the user's confirmation of it taken, **before** the credential field
// is presented.
//
// **The ordering is the whole point and it is not a courtesy.** ADR-0149 §4's third
// answer to a credential pasted into the identity field is precisely that the value
// is *seen*, and a page that showed the name after the secret had been typed into the
// box beside it would show it too late to be that answer.
function offerConnect(holder, account) {
  clearNode(holder);
  if (!ON_LOOPBACK) {
    line(
      holder,
      "Connecting an account is available on the gateway's own machine only. This " +
        "page is not on one, so your browser cannot protect a credential typed into " +
        "it — it would have no password manager, and no lock in the address bar. " +
        "Disconnecting and reading these lists work here.",
      "hint"
    );
    return;
  }
  line(
    holder,
    account
      ? `Replacing the credential under ${account.reference}. The account name may ` +
          "change with it."
      : "Connect an account. The hub mints the reference — you never type one, so " +
          "this can never overwrite a connection you already have.",
    "hint"
  );
  const name = document.createElement("input");
  name.type = "text";
  name.autocomplete = "off";
  name.spellcheck = false;
  name.placeholder = "The account name you will recognise";
  if (account) {
    name.value = account.identity;
  }
  holder.appendChild(name);
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "Continue";
  next.addEventListener("click", () => confirmIdentity(holder, name.value, account));
  holder.appendChild(next);
}

// Step two: show what was typed, and take the answer. Nothing has been asked for yet.
function confirmIdentity(holder, identity, account) {
  if (identity === "") {
    fault("An account name is needed before a credential is asked for.", "connections");
    return;
  }
  fault(null, "connections");
  clearNode(holder);
  line(holder, "About to connect this account:", "hint");
  // Rendered on its own line and as text, so a name with markup in it, or one that is
  // in fact a pasted token, is legible as exactly the characters that were typed.
  line(holder, identity, "connection-identity");
  const yes = document.createElement("button");
  yes.type = "button";
  yes.textContent = "That is the account — ask for the credential";
  yes.addEventListener("click", () => askCredential(holder, identity, account));
  holder.appendChild(yes);
  const back = document.createElement("button");
  back.type = "button";
  back.textContent = "Change it";
  back.addEventListener("click", () => offerConnect(holder, account));
  holder.appendChild(back);
}

// Step three, and the only step at which a credential field exists at all.
//
// `autocomplete` is off because ADR-0177 §4 puts the credential in "no browser
// storage of any kind", and inviting the browser to keep it is asking for exactly
// that. The field is cleared and the whole step torn down as soon as the value has
// been read, so a back-navigation or a second glance finds nothing to repopulate.
function askCredential(holder, identity, account) {
  clearNode(holder);
  line(holder, `Credential for ${identity}`, "hint");
  line(
    holder,
    "It goes to the hub in the body of one request and is kept nowhere here — not " +
      "in this page's storage, not in the address bar, and not in anything the " +
      "gateway writes down.",
    "hint"
  );
  const secret = document.createElement("input");
  secret.type = "password";
  secret.autocomplete = "off";
  secret.spellcheck = false;
  holder.appendChild(secret);
  const send = document.createElement("button");
  send.type = "button";
  send.textContent = account ? "Replace the credential" : "Connect";
  send.addEventListener("click", () => {
    const typed = secret.value;
    secret.value = "";
    clearNode(holder);
    sendConnect(identity, typed, account);
  });
  holder.appendChild(send);
  secret.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      send.click();
    }
  });
  secret.focus();
}

// One provisioning act, reported as ADR-0151 §7 reports it and never as anything
// else. Two entries and never one: `connect_account` mints its reference and cannot
// be aimed at an existing record, which is what makes creating a second connection
// where a replacement was meant unreachable rather than merely visible (§2, §3).
async function sendConnect(identity, credential, account) {
  const panel = beginActs(account ? "Replacing a credential" : "Connecting an account");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const result = account
    ? await act(half, "/connection/reprovision", {
        reference: account.reference,
        identity,
        credential,
      })
    : await act(half, "/connection/connect", { identity, credential });
  await reportConnectionAct(
    panel,
    half,
    result,
    account ? account.reference : null,
    account ? ACTS.reprovision : ACTS.connect
  );
  await listConnections();
}

// Disconnect one reference, and say exactly what that did and did not do.
//
// The confirmation is a plain one over the row on screen and is **not** ADR-0073 §5's
// ceremony: ADR-0177 §5 binds that ceremony to `forget`, `forget_question` and
// `forget_conversation` by name and stops there, and nothing here claims otherwise.
// What it does carry is ADR-0151 §8's own warning, which is about the act rather than
// about consent: a disconnection is prospective.
async function disconnectReference(reference, account) {
  // A reference with no live record on screen is the state an act that did not
  // complete leaves behind (ADR-0151 §7), and disconnecting it is one of the two
  // remedies that class prescribes — so the confirmation shows what is actually
  // known rather than inventing a record to show.
  const shown = account
    ? `${account.identity}\nReference: ${reference} · revision ${account.revision}`
    : `Reference: ${reference}\n(No live record for it is on screen. This is the ` +
      "reference an act that did not complete left behind.)";
  const asked = window.confirm(
    `About to disconnect this account.\n\n${shown}\n\n` +
      "This appends a removal entry and then deletes the credentials. It does not " +
      "stop anything already in flight, does not cancel an act in progress, and is " +
      "not a guarantee that the keyring holds nothing for this reference — what it " +
      "guarantees is that no live record names any credential for it.\n\n" +
      "This is not the same as deleting your data, and it does not discharge it."
  );
  if (!asked) {
    return;
  }
  const panel = beginActs("Disconnecting an account");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const result = await act(half, "/connection/disconnect", { reference });
  if (result.outcome === LANDED && result.body.removed === null) {
    // ADR-0151 §8: a `null` says **one** thing. It is not a report of a
    // disconnection, not a confirmation that a credential was deleted, and not a
    // statement that the reference does not exist.
    line(
      panel,
      "No live record was removed by that call. That is all it says — it is not a " +
        "disconnection, not a confirmation that a credential was deleted, and not a " +
        "statement that the reference does not exist.",
      "notice"
    );
  } else {
    await reportConnectionAct(panel, half, result, reference, ACTS.disconnect);
  }
  await listConnections();
}

// Say what one connection act did, from the condition the gateway named and from
// nothing else — then, where the condition leaves the reference's state unread, take
// the read that states it.
//
// **The read is a second browser request rather than something the gateway did.**
// ADR-0177 §1 forbids the gateway composing one operation out of two, so the resolve
// step ADR-0151 §7 prescribes — "read `connected_accounts`, never re-run the act" —
// is issued from here.
async function reportConnectionAct(panel, half, result, reference, words) {
  if (result.outcome === LANDED) {
    // A provisioning act answers under `account` and a disconnection under
    // `removed`, because they are different answers: one is the record this act
    // wrote and the other is the record it took away (ADR-0151 §8). Both are worth
    // rendering, and rendering neither would leave the owner told that something
    // happened without being told what.
    const written = result.body.account;
    const removed = result.body.removed;
    line(panel, words.landed, "reply");
    if (written) {
      renderActRecord(panel, written, "The record this act wrote:");
    } else if (removed) {
      renderActRecord(
        panel,
        removed,
        "The record as it stood immediately before it was removed. It says what was " +
          "there, and nothing about what is there now:"
      );
    }
    return;
  }
  const named = CONNECTION_CONDITIONS[result.body.fault];
  const handle = typeof result.body.reference === "string" ? result.body.reference : reference;
  if (result.body.fault === "residual-credential") {
    // Said **first**, and as the act's own result rather than as a failure: this is
    // the one condition on which the act completed, and ADR-0151 §8's "no client
    // reports it as a failed connection or a failed disconnection" is a rule about
    // the first thing the owner reads.
    line(panel, words.residual, "reply");
  }
  if (named) {
    line(panel, named.words, named.stateKnown ? "failed" : "notice");
  } else {
    reportAct(panel, "act", result);
  }
  if (named && named.stateKnown) {
    return;
  }
  if (handle) {
    line(panel, `Reference: ${handle}`, "hint");
    offerRemedies(panel, handle, REMEDIES[result.body.fault]);
  } else {
    line(
      panel,
      "No reference came back with that, so there is none to read — the list below " +
        "is what says whether anything was made.",
      "hint"
    );
  }
  await stateAfterAct(panel, half, handle);
}

// The acts a condition prescribes on the reference it named, offered on that
// reference and on nothing else.
//
// **These are not a row of the listing and the wording says so.** The listing answers
// "what is connected now"; this answers "what is safe to do about the reference this
// act left", which ADR-0151 §7 makes a different question with a different answer —
// and offering them inside a row would be this surface claiming the reference is
// live, which is precisely what it has just said it cannot state.
function offerRemedies(panel, handle, prescribed) {
  if (!prescribed) {
    return;
  }
  line(
    panel,
    "These act on that reference. Neither is a statement that it is connected — they " +
      "are the acts that are safe whichever record is live now.",
    "hint"
  );
  if (prescribed.replace && ON_LOOPBACK) {
    const again = document.createElement("button");
    again.type = "button";
    again.textContent = "Replace the credential on that reference";
    again.addEventListener("click", () => {
      show("connections", true);
      offerConnect(el("connect-form"), { reference: handle, identity: "" });
    });
    panel.appendChild(again);
  }
  if (prescribed.disconnect) {
    const drop = document.createElement("button");
    drop.type = "button";
    drop.textContent = "Disconnect that reference";
    drop.addEventListener("click", () => disconnectReference(handle, null));
    panel.appendChild(drop);
  }
}

// Re-read what is connected and state the reference from it, or say it is unread.
//
// A failed read leaves the state **unread** rather than assumed, which is the only
// safe answer: the alternative is a page that says "nothing is connected" because it
// could not ask.
async function stateAfterAct(panel, half, reference) {
  let held = null;
  try {
    held = await relay(half, "/connections", {}, "connections");
  } catch (_) {
    held = null;
  }
  if (held === null) {
    line(panel, CONNECTION_STATE_UNREAD, "notice");
    return;
  }
  if (reference === null) {
    return;
  }
  const found = held.accounts.find((one) => one.reference === reference);
  if (!found) {
    line(panel, "That reference has no live record now.", "hint");
    return;
  }
  line(panel, `That reference now: ${stateWords(found.state)}`, "hint");
}

async function listConnectionLog() {
  fault(null, "connection-log");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const held = await relay(half, "/connections/recent", { limit: PAGE }, "connection-log");
    if (held === null) {
      return;
    }
    const list = el("connection-log-list");
    clearNode(list);
    show("connection-log", true);
    if (held.acts.length === 0) {
      line(list, "Nothing has been done to a connection.", "hint");
    }
    held.acts.forEach((one) => renderConnectionAct(list, one));
  } catch (_) {
    fault(GATEWAY_GONE, "connection-log");
  }
}

// One row of the log. A removal is the **absence** of the act's record and not a
// third state (ADR-0149 §5), and no time is rendered because a connection record has
// none (ADR-0151 §9) — so nothing here is a claim about when anything happened.
function renderConnectionAct(list, one) {
  const item = document.createElement("div");
  item.className = "connection-row";
  if (one.account === null) {
    line(item, "Disconnected", "connection-identity");
    line(item, "This act removed the live record for that reference.", "hint");
  } else {
    line(item, one.account.identity, "connection-identity");
    // The row carries "the furthest provisioning state that act reached" (ADR-0151
    // §9), which is a fact about the act and not about the reference now — so it is
    // introduced as one, and the panel above says no row here states what is
    // connected.
    line(item, "A provisioning act. What it left:", "hint");
    line(item, stateWords(one.account.state), "hint");
  }
  line(item, `Reference: ${one.reference} · revision ${one.revision}`, "hint");
  list.appendChild(item);
}

// --- looking over a conversation (ADR-0077 §8) -------------------------------
//
// The passive half of accumulation, and it is deliberately explicit: nothing
// triggers it but a caller, which here is the owner pressing a button. The
// conversation id is a **selector rather than a subject** — this one, or the most
// recently active — so the page sends the one it is working in and nothing when it
// holds none.
async function observe() {
  fault(null, "observation");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const asked = conversationId === null ? {} : { conversation_id: conversationId };
  try {
    const body = await relay(half, "/observe", asked, "observation");
    if (body === null) {
      return;
    }
    renderObservation(body.observation);
    show("observation", true);
  } catch (_) {
    fault(GATEWAY_GONE, "observation");
  }
}

// What one pass did. The three discard counts are kept apart because they are three
// different facts, and `decision` being absent means **no ruling was ever made** —
// which is not the same as a ruling that rejected the proposal.
function renderObservation(report) {
  const body = el("observation-body");
  clearNode(body);
  line(
    body,
    report.conversation_id === null
      ? `Read ${report.episodes_read} episode(s).`
      : `Read ${report.episodes_read} episode(s) of conversation ${report.conversation_id}.`,
    "hint"
  );
  if (report.route !== null) {
    line(body, `Route: ${report.route}`, "hint");
  }
  line(
    body,
    `${report.discarded_unusable} proposal(s) could not be used, ` +
      `${report.discarded_over_limit} were over the producer's limit, and ` +
      `${report.dropped_unsupported} were dropped for want of support.`,
    "hint"
  );
  if (report.proposals.length === 0) {
    line(body, "Nothing was proposed.", "hint");
  }
  report.proposals.forEach((one) => renderProposal(body, one));
}

function renderProposal(body, proposal) {
  const item = document.createElement("div");
  item.className = "belief-row";
  line(item, proposal.content, "reply");
  line(
    item,
    `${proposal.kind} · ${proposal.step} · confidence ${proposal.confidence.toFixed(2)}`,
    "hint"
  );
  line(item, `Because: ${proposal.rationale}`, "hint");
  line(
    item,
    proposal.decision === null
      ? `No ruling was made on it. ${proposal.reason}`
      : `Ruling: ${proposal.decision}. ${proposal.reason}`,
    "hint"
  );
  body.appendChild(item);
}

const CONTROL_PANELS = [
  "confirmations",
  "control",
  "sources",
  "standing",
  "history",
  "acts",
  "beliefs",
  "questions",
  "review",
  "tuning",
  "connections",
  "connection-log",
  "observation",
];

// `because` is the re-entry sentence (ADR-0182 §6), and **omitting it leaves whatever
// is there alone** rather than clearing it. Every act on this page guards on a missing
// header half by calling this with nothing, so a sentence cleared by the next click
// would be an explanation the owner had one click to read. It is cleared where it stops
// being true: when a session starts.
function showBootstrap(because) {
  clearFaults();
  if (because !== undefined) {
    el("reentry").textContent = because;
  }
  show("bootstrap", true);
  show("console", false);
  show("conversations", false);
  show("notifications", false);
  CONTROL_PANELS.forEach((panel) => show(panel, false));
}

function showConsole() {
  clearFaults();
  // The re-entry sentence stops being true the moment a session exists, and this is the
  // one place that is so.
  el("reentry").textContent = "";
  show("bootstrap", false);
  show("console", true);
  // Which conversation the next question lands in, said before the first one is asked
  // — including after a reload, which now keeps the thread rather than starting one
  // the owner never asked for (#1371's first clause).
  setConversation(conversationId);
  // The notification panel is shown before anything has arrived, because what it
  // mostly says is whether this browser is watching at all — and a panel that
  // appeared only on the first delivery would leave the owner unable to tell "no
  // notifications" from "not connected", which is ADR-0083's ruling 4 failure at the
  // one place ADR-0175 §4 spends a keep-alive to prevent it.
  show("notifications", true);
  // The control surface's own entry points are shown with the console; each panel
  // below them appears when it has been read, so a panel on screen is always a
  // panel showing an answer rather than an empty promise.
  show("control", true);
  // Whether this browser will let the page record at all, asked once a session exists
  // and said on screen either way (ADR-0200 §10). Here rather than at load, because the
  // control lives in the console panel and there is nothing to offer while the
  // bootstrap panel is up.
  offerTalk();
  el("utterance").focus();
  watchDeliveries();
  // A park outlives the page that raised it, so a browser opening onto one has to be
  // told without being asked (ADR-0177 §8). Quiet, because a load that finds nothing
  // waiting has nothing to say.
  readPending(true);
}

el("bootstrap-form").addEventListener("submit", startSession);
el("ask-form").addEventListener("submit", ask);
// The way out of a wait, built once and hidden until there is a wait to leave (#1500).
offerStopWaiting();
// Push to talk, on the three ways a control is held down (ADR-0200 §10).
//
// **Pointer events cover mouse, pen and touch in one pair**, which is why there is no
// `touchstart` handler beside them: a second set would double-fire on every browser
// that sends both. `setPointerCapture` is what makes the release land here even when
// the finger or the cursor has left the button by the time it lifts — without it a
// press that drifts is a recording that never stops.
//
// **The keyboard is its own pair rather than a `click`**, because a click is the whole
// press-and-release collapsed into one event and this control needs the two apart. The
// default has to go with it: a native button treats Space and Enter as a click, so
// leaving it would fire an activation on top of the pair. `repeat` is the key
// auto-repeating while held, which is not a second press.
const talkButton = el("talk-button");
talkButton.addEventListener("pointerdown", (event) => {
  // The recording first and the capture second, because the capture is an improvement
  // on the mechanism rather than the mechanism: it is what makes the release land here
  // after the pointer has drifted off the button, and a browser that will not give it
  // should cost the drift case rather than the whole control.
  void startTalking();
  talkButton.setPointerCapture(event.pointerId);
});
talkButton.addEventListener("pointerup", stopTalking);
talkButton.addEventListener("pointercancel", stopTalking);
talkButton.addEventListener("keydown", (event) => {
  if (event.key !== " " && event.key !== "Enter") {
    return;
  }
  event.preventDefault();
  if (event.repeat) {
    return;
  }
  void startTalking();
});
talkButton.addEventListener("keyup", (event) => {
  if (event.key !== " " && event.key !== "Enter") {
    return;
  }
  event.preventDefault();
  stopTalking();
});
el("stop-talking").addEventListener("click", abandonSpoken);
el("new-conversation").addEventListener("click", startFresh);
// Wrapped rather than passed, because the listener's argument is a `MouseEvent` and
// `watchDeliveries` reads its first argument as the sentence to announce.
el("watch-button").addEventListener("click", () => watchDeliveries());
el("fault-dismiss").addEventListener("click", () => fault(null));
el("conversations-button").addEventListener("click", listConversations);
el("confirmations-button").addEventListener("click", listPending);
el("sources-button").addEventListener("click", listSources);
el("standing-button").addEventListener("click", listStanding);
el("history-button").addEventListener("click", listGrantHistory);
el("beliefs-button").addEventListener("click", listBeliefs);
// A band changed is a different question, so it starts the listing again rather than
// filtering what is already on screen: this page holds no beliefs of its own and the
// hub is what answers which ones match.
["band-asserted", "band-derived", "band-attested"].forEach((box) => {
  el(box).addEventListener("change", listBeliefs);
});
el("questions-button").addEventListener("click", listQuestions);
el("observe-button").addEventListener("click", observe);
el("review-button").addEventListener("click", listNotifications);
el("tuning-button").addEventListener("click", listTuning);
el("connections-button").addEventListener("click", listConnections);
el("connection-log-button").addEventListener("click", listConnectionLog);

// Two events, no timer (#1429). Both go through `rearm`, which does nothing at all
// unless a stream is actually shut and this browser still holds a session half — so a
// tab switch on a healthy page costs one comparison and says nothing.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    rearm(CAME_BACK);
  }
});
window.addEventListener("online", () => rearm(NETWORK_BACK));

stopWatching();
if (headerHalf() === null) {
  showBootstrap();
} else {
  showConsole();
}
