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
// **There are two clocks here and neither opens a stream** (#1442). `setInterval` does
// not appear at all. The first `setTimeout` bounds how long a delivery stream may say
// *nothing* before this page abandons it — it ends a stream, restores the owner's own
// control, and re-establishes nothing. ADR-0182 §7 forbids re-arming "on a timer, on a
// schedule, or on the failure itself", and re-arming is exactly what this clock does
// not do: after it fires the page holds no stream, and what opens the next one is one
// of §7's two events or the owner's click. The second follows the chat (ADR-0293
// §11:1): it reads the changes after the page's cursor while the chat is open, and a
// read that fails stops it rather than being tried again.

"use strict";

const STORAGE_KEY = "assistant.session.header-half";

// **Which door served this page** (ADR-0327 §11), read off the document element, where
// `/door.js` wrote it before this file ran. The hosted listener — the one behind the
// sign-in edge — serves a `door.js` that says "hosted", and every other listener serves
// one that does not; that file is the whole of the difference between the two bundles.
//
// On the hosted door the page shows no bootstrap entry and mints its session by the
// exchange, with nothing typed (§11:1). Everything the gateway admits it decides for
// itself, so a page that read this wrong would show the wrong panel and be refused —
// it could never be admitted on the strength of it.
const HOSTED = document.documentElement.dataset.door === "hosted";

// The exchange that takes the bootstrap value's place on the hosted listener (§8): a
// `POST` carrying nothing. The edge adds its assertion on the box; this page never sees
// one (§9:2).
const EDGE_EXCHANGE_PATH = "/session/edge";

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
//
// A fault ends either stream. The change stream has one ending of its own besides: `end`,
// the hub shutting down, with the cursor to follow again from (ADR-0298 §7) — the same
// partition as `streams.TERMINAL_KINDS`, stated on both halves of one distribution.
const TERMINAL_KINDS = new Set(["fault", "end"]);

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

// --- which session a request belongs to (#2404) -------------------------------
//
// **How many sessions this page has been handed**, so that a request sent under one can
// say whether it is still the one this browser holds when its answer comes back.
//
// The generation counters a panel over order two *listings*; they say nothing about the
// session under them. Let a listing hang, let any other request meet `no-live-session` —
// `sessionLost` forgets the header half and puts the bootstrap entry back — and the
// hanging run is still the latest, so it resumes, renders, and reveals its panel: the
// owner's rows on screen beside a form asking them to start a session. PR #2393's
// adversarial review found it at round 9 in one listing and fixed it there; #2404 is the
// same shape at every other one.
//
// **It is counted inside the two functions that write the stored half**, rather than at
// their callers, so it cannot fall out of step with what it counts: there is no third
// place a session begins or ends.
let sessionEra = 0;

// **Whether the session a request was sent under is still the one this page holds.**
//
// Both halves are asked and neither subsumes the other. The count catches a session this
// page lost and re-entered under a value that happens to be identical, where comparing
// the stored half alone would see nothing changed. The half catches a session *another
// tab* started, where the storage this page reads changed under it and nothing here
// counted anything.
//
// **It governs everything a resumed continuation puts on the screen** — the rows, the
// reveal, and the condition. The first draft guarded only the first two, on the reading
// that a panel carrying nothing but a fault says nothing about the owner and that
// ADR-0168 §9's rule against flattening a condition into silence should keep that path;
// adversarial review's round 1 took the reading apart, and it does not hold. `fault`
// reveals the panel it writes into, so a listing whose request fails after its session
// ended re-opens a control panel beside the bootstrap form — moments after
// `showBootstrap` hid every panel and `clearFaults` cleared every slot, and the two
// cannot both be the page's account of itself. §9 is about a condition reaching the
// owner in the act they are waiting on; here the act belonged to a session that no
// longer exists, the page has said so in its own words, and there is nothing the owner
// could do with the condition but start the session the form is already asking for.
function sameSession(half, era) {
  return era === sessionEra && headerHalf() === half;
}

function rememberHeaderHalf(value) {
  // A session handed to this page is a different session from the one before it,
  // whatever the value turns out to be — counted before the write, so that a store
  // which refuses still ends the era every request in flight was sent under.
  sessionEra += 1;
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
  sessionEra += 1;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch (_) {
    // Nothing to do: a browser that will not store will not have stored.
  }
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
// a table here: a second place a panel is called something is a place for one of the
// two to go stale.
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
// answered, and the caller's job is to classify it — `act`'s rule: "a refusal whose
// condition this page cannot read is a refusal it cannot classify, and ADR-0139 §4's
// third outcome is what an unclassifiable one is". So a body that will not parse
// arrives as an unnamed condition rather than as an exception, and the caller decides
// what an unnamed one means.
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
// --- instants (#1392) -----------------------------------------------------------
//
// An instant the hub wrote — ISO-8601 with its offset — said in this browser's own
// language and time zone, everywhere the page prints one. The hub's own zone
// (`Settings.timezone`) is still what a quiet window is read in (ADR-0130 §6): that is
// how the hub *decides*, and this is only how a page *shows* an instant it was sent,
// so no second zone decides anything. A value that is not an instant with an offset —
// a bare date, a time with no zone, a word — is shown as it came, because nothing here
// can know which zone it meant.
const INSTANT_SHAPE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;
const LOCAL_DATE_TIME = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});
// A conversation's name and a message's time: always the whole date, so that a name
// on screen never goes stale as the day turns, and the minute — or the second, where
// two conversations would otherwise share a name (`conversationName`).
const CHAT_TIME = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const CHAT_TIME_SECONDS = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

function instant(iso) {
  if (typeof iso !== "string" || !INSTANT_SHAPE.test(iso)) {
    return null;
  }
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? null : at;
}

function localTime(iso) {
  const at = instant(iso);
  return at === null ? iso : LOCAL_DATE_TIME.format(at);
}

// The headline of each of the hub's three device refusals on the hosted door (below).
const HOSTED_DEVICE_REFUSED = "That didn't go through, so nothing was done.";

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
  // ADR-0327 §7:6 and §11:6: the hosted listener's one refusal for its assertion, its
  // `Host` and its `Origin`, which carries nothing about which of them failed — so the
  // sentence says what the person can do, which is the same whichever it was. It is
  // never shown on another door, which never answers with it.
  "door-refused":
    "The sign-in door refused this request, so nothing was asked. If your sign-in has " +
    "ended, sign in again at the sign-in page.",
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
  // ADR-0293 §4:7 and the gateway's own naming of a browser's device (ADR-0296 §1). The
  // gateway's `detail` says what the bound is, or why it has no name to give.
  "message-too-long": "That message is too long to send, so nothing was sent.",
  "device-unnamed": "This browser cannot write a message through this gateway.",
  // ADR-0298 §6: the hub refused the request for the device this browser is, before
  // it changed anything. One name per reason, so each reads as its own condition; the
  // gateway's `detail` names the device and the command that changes the answer.
  //
  // Through the sign-in door the reader is a person who holds no machine of the hub's
  // and knows no device by name (ADR-0327 §10), so the headline says only that nothing
  // happened: the gateway's `detail` there says, per reason, what is not set up yet and
  // who can set it up.
  "device-not-accepted": HOSTED
    ? HOSTED_DEVICE_REFUSED
    : "The hub does not accept this device through this gateway, so nothing was done.",
  "device-without-role": HOSTED
    ? HOSTED_DEVICE_REFUSED
    : "The hub has not given this device a role yet, so nothing was done.",
  "device-not-allowed": HOSTED
    ? HOSTED_DEVICE_REFUSED
    : "This device's roles do not allow that, so nothing was done.",
  "no-such-belief":
    "No live belief has that id. It may never have existed, or it may have been " +
    "revised or forgotten already — this surface shows and destroys only beliefs " +
    "held right now.",
  "malformed-request":
    "The gateway could not read that request. The page and the gateway ship in one " +
    "distribution, so this means the two halves disagree.",
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

// The ending of a stream that outlived the session it was opened under (#2455), in the
// line that carries the control back rather than in a fault slot. It is not a fault:
// nothing went wrong, the gateway answered, and the session this browser is using was
// never touched — which is the whole of what the owner needs told, because the ending
// this stream really got belongs to a session that is no longer theirs to hear about.
const OUTLIVED_ITS_SESSION =
  "That stream was opened under a session this browser no longer holds, so its ending " +
  "is not this session's to report and nothing about the session in use here was " +
  "changed. Start watching again.";

const DELIVERY_STREAM_CUT =
  "The connection carrying notifications ended before the gateway finished it, so " +
  "this browser has stopped watching. Nothing the hub still holds was lost: it is " +
  "polled only while a browser is watching, so nothing was taken out of its outbox " +
  "while nothing here was listening. Start watching again.";

// The same limb of ADR-0175 §2 on the delivery stream, for a line this page could not
// read as a value on it (#2008). Its own sentence, because an owner whose notifications
// stopped is told about notifications and about nothing else.
//
// **And it is not the cut.** "Ended before the gateway finished it" is false of a
// gateway that wrote a whole line and had it refused here, and this ending is the one an
// array or a scalar on this stream reaches
// — which reached the cut's wording before the reader refused those (adversarial review,
// round 1, `blocker`).
const DELIVERY_STREAM_MISFRAMED =
  "The connection carrying notifications carried a line this browser could not read as " +
  "a value on it, so it read no further and has stopped watching. The gateway did " +
  "answer: what broke is the shape of what was written and not the connection carrying " +
  "it. Nothing the hub still holds was lost: it is polled only while a browser is " +
  "watching, so nothing was taken out of its outbox while nothing here was listening. " +
  "Start watching again.";

// **The gateway is where a session lives, so the gateway stopping is where it ends**
// (ADR-0168 §4: minted at the gateway, held in memory, and dies with the process).
// This is the sentence for the surprise rather than a restatement of the mechanism:
// nothing is wrong with the browser, nothing is recoverable, and the way back is a
// fresh bootstrap value.
//
// **Through the sign-in door the way back is not the owner's to take at the gateway**
// (ADR-0327 §11): the box is the operator's, and a session there is started by the
// exchange, with nothing typed. So the same surprise is said with the hosted remedy —
// try again, and this page starts a new session through the sign-in it already has.
const GATEWAY_GONE = HOSTED
  ? "The gateway did not answer, so it may have stopped. " +
    "Every session ends with the gateway: a session is held in that process's memory " +
    "and written down nowhere, so a gateway that starts again has no memory of this one. " +
    "Try again in a moment, and this page starts a new session through your sign-in."
  : "The gateway did not answer, so it may have stopped. " +
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
//
// **It names every bound rather than the idle one, because the value cannot say which
// fell due** (#2498, adversarial review round 1). §7's fourth clause ends a stream for
// *any* ending of the session under it, and the gateway names all of them with the one
// condition that is true of all of them — there is no live session. A sentence that said
// the hour had passed would be right on the common route and false on the other two: a
// session reaching `gateway_session_ttl` with a request made minutes ago, and a gateway
// going down (ADR-0168 §4's "every session ends when the gateway process ends"). Naming
// the three is what keeps this an explanation rather than a guess, and it is the same
// three the bootstrap panel's own standing text already names.
const IDLE_WHILE_WATCHING =
  "Watching does not keep a session alive: a stream carries no request, so a page " +
  "left watching and asked nothing expires on gateway_session_idle_timeout like any " +
  "other. A session also ends at gateway_session_ttl from when it started, and with " +
  "the gateway process.";

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
// idle timeout on its way in, so the idle bound is not what ended *that* stream's
// session and putting it in front of the owner would be a wrong explanation rather
// than a missing one. A delivery stream carried no request at all, which is the fact
// the sentence is about and the one nobody guesses.
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

// The one thing `streamValues` throws of its own motion, and it has its own type so
// that a reader can tell it from everything else a read can reject with — an abort the
// owner asked for, a connection that failed, a body the browser gave up on. Each of
// those is a different ending and is announced as one, and a bare `SyntaxError` from
// `JSON.parse` is indistinguishable from all of them at the catch that has to choose
// (#2008).
class MisframedValue extends Error {}

// One line of a stream, read as the value that line is supposed to be (ADR-0175 §2).
//
// **A line that is not one JSON object is not a value on this stream at all**, and it
// is refused here rather than at each reader, because "one JSON object per line" is
// this reader's own contract and not something a consumer of it should be re-checking.
// Two shapes breach it: a line `JSON.parse` will not read at all, and a line that reads
// as `null`, as a scalar or as an array — none of which can carry the discriminator
// §2's first clause requires a value to carry, so there is nothing on them a kind could
// be resolved from and reading one off their shape is the guess that same clause
// refuses.
//
// **`{}` is a different case and stays a value.** An object whose `kind` this page does
// not know is the two halves of one distribution disagreeing (ADR-0168 §10), which
// every reader below already ignores rather than guesses at. What is refused here is a
// line that could not carry a kind, never one that carried an unfamiliar one.
function frameOf(framed) {
  let value;
  try {
    value = JSON.parse(framed);
  } catch (_) {
    throw new MisframedValue();
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new MisframedValue();
  }
  return value;
}

// Read one `application/x-ndjson` body: one JSON object per line, each carrying the
// `kind` that says what it is (ADR-0175 §2). A reader resolves a value's kind from
// that member and never by inspecting what the value contains, so nothing below
// guesses from a payload's shape.
//
// **A line this reader cannot read ends the stream here**, as `MisframedValue` rather
// than as whatever `JSON.parse` happened to raise: left unguarded that throw escaped
// every consumer's own ending and reached `ask`'s outer catch, which called it
// `GATEWAY_GONE` — about a gateway that had just written a head and a body (#2008).
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
        yield frameOf(framed);
      }
    }
  }
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
  if (!rememberHeaderHalf(body.header_half)) {
    fault("This browser will not store the session, so it cannot hold one.", "bootstrap");
    return;
  }
  showConsole();
}

// --- the exchange, through the sign-in door (ADR-0327 §8, §11) -------------------
//
// **The page exchanges by itself, on two events only** (§11:2): when it loads holding no
// header half, and when the gateway refuses the half it holds as no live session. Each
// makes at most one exchange, and an exchange already in flight is the one for every
// event that arrives while it is — so a listing and a stream refused together start one
// session, not two.
//
// **After a failed exchange the page makes no further one until the owner acts**
// (§11:3). `exchangeFailed` is set by every failure and cleared by nothing in this file:
// the act is the owner's "Try again", which reloads the page, and a reload is the act
// §11:3 names. So no refusal, however it arrives, becomes a retry loop.
//
// **Three outcomes, each in its own words.** A session — and the page carries on. The
// door refusing (§7:6), which says the sign-in page is where signing in again happens
// (§11:6). Any other failure, which says only that it failed (§8:2) — and the gateway
// not answering at all, which is `GATEWAY_GONE` in the hosted panel's fault slot.
let exchanging = false;
let exchangeFailed = false;

// What the hosted panel says while the exchange is out, and after a session that ended
// was replaced. Neither is a fault: a session ending on its own bounds is how sessions
// end, and the page has already done the one thing there is to do about it.
const SIGNING_IN = "Starting a session through your sign-in.";
const RESUMED =
  "That session ended, so this browser started a new one through your sign-in. " +
  "Nothing you asked was sent again: ask again, and watch again, when you want to.";

// §11:3's other half: what the owner is told after a failure, beside the act that is
// theirs to take.
const TRY_AGAIN = "Nothing more is tried until you try again.";

function exchangeRefused(said) {
  exchangeFailed = true;
  showBootstrap(`${said} ${TRY_AGAIN}`);
  el("hosted-again").hidden = false;
}

async function exchangeSession(resumed) {
  if (exchanging || exchangeFailed) {
    return;
  }
  exchanging = true;
  el("hosted-again").hidden = true;
  showBootstrap(SIGNING_IN);
  let response;
  let body;
  try {
    // No body and no header of this page's own (§8:1): the browser sends the `Origin`
    // and the edge attaches its assertion, and those are the whole of the exchange.
    response = await fetch(EDGE_EXCHANGE_PATH, { method: "POST" });
    body = await readBody(response);
  } catch (_) {
    exchanging = false;
    exchangeFailed = true;
    showBootstrap(TRY_AGAIN);
    el("hosted-again").hidden = false;
    fault(GATEWAY_GONE, "hosted");
    return;
  }
  exchanging = false;
  if (!response.ok || typeof body.header_half !== "string") {
    exchangeRefused(describe(body, response.status));
    return;
  }
  if (!rememberHeaderHalf(body.header_half)) {
    exchangeRefused("This browser will not store the session, so it cannot hold one.");
    return;
  }
  showConsole(resumed);
}

// What the hosted page does with a refusal that ended, or barred, the session it holds
// (§11:2, §11:5, §11:6). Its own function so `sessionLost` keeps the loopback page's
// re-entry exactly as ADR-0182 §6 rules it (§11:8).
function hostedSessionLost(body, said) {
  if (body.fault === "no-live-session") {
    // §11:2's second event: one exchange, and the request that was refused is not sent
    // again (§11:4) — `showConsole` is told it is resuming and re-issues nothing.
    void exchangeSession(true);
    return;
  }
  // The mismatch (§11:5) and the door's refusal (§11:6) are each shown as themselves,
  // and neither makes an exchange: the next attempt is the owner's to make.
  exchangeFailed = true;
  showBootstrap(`${said || describe(body, 0)} ${TRY_AGAIN}`);
  el("hosted-again").hidden = false;
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
  // **The door's refusal ends this page's use of its session as well** (ADR-0327
  // §11:6): nothing more is admitted through a door that refuses, and the half is let
  // go so that trying again starts the one exchange a load holding no session makes —
  // rather than presenting a half the person's ended sign-in can no longer carry.
  const barred = HOSTED && body.fault === "door-refused";
  if (barred || body.fault === "no-live-session" || body.fault === "cookie-half-mismatch") {
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
    if (HOSTED) {
      hostedSessionLost(body, said);
      return true;
    }
    showBootstrap(said ? `${RE_ENTRY} ${said}` : RE_ENTRY);
    return true;
  }
  return false;
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
//      file re-sends an ADR-0177 §6 operation after a refusal; a failed grant or
//      forget is reported and waits for the owner, because an automatic re-issue can
//      duplicate an act.
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
  // **Which session this stream belongs to, read in the same breath as the half it will
  // be sent under** (#2455). A stream outlives its own session by design — ADR-0175 §7
  // has an idle session expire under an open one and end it — so the pair every other
  // caller captures for a request that might be answered late is captured here for a
  // request that is *expected* to be, and it is captured before `watching` is set so
  // that nothing between the two can move either half of it.
  const era = sessionEra;
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
    await readDeliveries(half, era);
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
//
// **Both of its endings are guarded against ending a session they no longer belong to**
// (#2455). `report` is `sessionLost` at one remove, and `sessionLost` calls
// `forgetHeaderHalf`, which removes the stored half whatever session it belongs to. The
// stored half is shared by every tab at this origin, so a stream opened under a session
// that has since expired — which is precisely the stream ADR-0175 §7 describes — could
// answer `no-live-session` and evict the half of a session *another tab* had started in
// the meantime, throwing the tab the owner is actually using back to the bootstrap form.
// #2404 closed that door for every caller that goes through `relay`, by comparing
// `sameSession(half, era)` before `refused`; this is the same comparison at the one
// surface that does not, and it is the last of them.
//
// **The guard is on the endings and not on the values**, which is a distinction this
// stream makes and a listing cannot. A value on an open delivery stream arrives while
// the session holding it is still live — §7 ends the stream with the session, so there
// is no window in which a dead session delivers — and it is the same owner's
// notification either way, so suppressing it would drop a real delivery in silence,
// which is the failure ADR-0175 §4 spends its keep-alive to prevent. An *ending*, by
// contrast, is exactly the thing that is answered for a session that has already gone.
//
// **And the `catch` is guarded on the same terms**, which adversarial review's round 1
// found the version of this that was not. Nothing there can *evict* a half —
// `forgetHeaderHalf` has one caller, `sessionLost`, which releases this stream before it
// does anything else, so a session lost in this page reaches the catch as
// `open.released` and returns. But eviction is not the whole of the rule: the four
// endings the catch classifies each write a `fault`, and a page that refused to let a
// superseded stream report a cut while letting it report a black hole would be applying
// one rule to two halves of one ending. `NO_HEAD` and `WENT_SILENT` are about a cadence
// the *old* session's gateway stated; `GATEWAY_GONE` says the gateway may have stopped,
// which is a statement about the process this page is still happily talking to.
async function readDeliveries(half, era) {
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
      // Not this session's refusal to report (#2455), and asked after the body is read
      // rather than before, so what is compared is the session as it stands at the
      // moment the ending would be acted on.
      if (!sameSession(half, era)) {
        stopWatching(OUTLIVED_ITS_SESSION);
        return;
      }
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
        // Shown as text and never played (ADR-0313 §3:5): the page's playback retired
        // with push-to-talk, and `spoken` is `null` on every value (§3:6).
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
    // Not this session's ending to report (#2455). It stands in front of the whole
    // ending rather than only the `report` that can end a session, and that is a
    // decision rather than the wider of two equal options: a cut and a terminal fault
    // evict nothing, but `fault` reveals the panel it writes into, so either would
    // open the notifications panel with a condition about a stream that is no longer
    // the one serving this browser — "the connection carrying notifications ended
    // before the gateway finished it" reads as a statement about the notifications
    // this page would deliver *now*, and it is not one. What the owner is owed here is
    // the fact that supersedes all of them, and it is one sentence for both doors,
    // which is also the reading with no race in it.
    if (!sameSession(half, era)) {
      stopWatching(OUTLIVED_ITS_SESSION);
      return;
    }
    stopWatching();
    if (terminal === null) {
      fault(DELIVERY_STREAM_CUT, "notifications");
    } else {
      report("notifications", terminal, describeDeliveryEnd(terminal, response.status));
    }
  } catch (error) {
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
    // Not this session's ending to report (#2455), below the release for the reason the
    // release is above everything: one is this page's own act and the other is a fact
    // about the session, and an ending this page performed is the one the owner is told
    // about. Above the classification, because what the four branches below tell apart
    // is *how* a stream this page is being served by ended, and this is not one.
    if (!sameSession(half, era)) {
      stopWatching(OUTLIVED_ITS_SESSION);
      return;
    }
    if (stalled) {
      stopWatching(NO_HEAD);
      fault(DELIVERY_STREAM_STALLED, "notifications");
    } else if (silent) {
      stopWatching(WENT_SILENT);
      fault(DELIVERY_STREAM_SILENT, "notifications");
    } else if (error instanceof MisframedValue) {
      // **Below the two aborts and above the gateway having gone** (#2008). The aborts
      // are this page's own acts and keep their precedence for `open.released`'s reason:
      // a deadline that fired raises on the *next* read, so a line already buffered can
      // be refused after the stream was abandoned, and the act is what the owner is told
      // about. What is left below them is a stream that carried something, which is the
      // one ending here that is not a gateway that stopped saying anything.
      stopWatching();
      fault(DELIVERY_STREAM_MISFRAMED, "notifications");
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

// **`stopping` is the caller's, and it is the only clock this function knows about**.
// The conversations listing passes the controller behind its read so that a newer read
// can stop an older one; every other caller passes none, and `undefined` is what `fetch`
// reads as no signal at all. Nothing here arms a deadline: the page keeps one clock and
// it is the delivery stream's.
//
// **`noticed` is a caller being told *which* refusal it got**, and it is a callback
// rather than a wider return because `null` means "refused, and the condition is
// already on screen" at every call site. The chat's reads pass one, because a
// `no-such-conversation` there means the conversation was deleted elsewhere and the page
// lets it go; every other caller passes none and is untouched.
//
// **The body and not the status**: a status names one condition only for some refusals,
// and `403` "says the gateway refused and does not say why", so classifying by it would
// be the flattening ADR-0168 §6 forbids. The `fault` name is where ADR-0168 §9's
// distinction actually lives.
async function relay(half, path, payload, panelId, stopping, noticed) {
  const era = sessionEra;
  const response = await fetch(path, {
    method: "POST",
    headers: admitted(half, true),
    body: JSON.stringify(payload),
    signal: stopping === undefined ? undefined : stopping.signal,
  });
  if (response.ok) {
    // **The head is not the answer, and a body this browser did not read is not a
    // response** (adversarial review's round-8 blocker; ADR-0177 §7's fourth clause).
    // `fetch` settles when the *head* lands, so the body is still arriving when this
    // resumes, and an abort can land on a request whose status has already been read.
    // Routing that through `readBody` would swallow the abort and return `{}` for a
    // `200` — an answer-shaped nothing.
    //
    // So the rejection is **kept** here and `readBody`'s swallow is left to the refusal
    // path it was written for. Every caller of this function already runs it inside a
    // `try`, and each one's `catch` is the ending it wants.
    //
    // The gateway writes every `2xx` through `_json_response`, so a `2xx` body that
    // will not parse is a transport truth and not a shape this page has to tolerate —
    // which is the asymmetry with a refusal, whose condition a proxy really can replace.
    return asObject(await response.json());
  }
  const body = await readBody(response);
  // **A request the caller stopped classifies nothing, even once a head has arrived**
  // (adversarial review round 4, `major`). `readBody` swallows a rejection, which is
  // right for the refusal path it was written for — a proxy really can replace a
  // condition — and wrong for an abort: the head lands, the caller aborts, the body
  // read rejects, `{}` comes back, and the panel is told "The gateway refused that
  // request (HTTP 404)" about a read nobody is waiting for.
  //
  // **It is thrown rather than returned as `null`**, because a `null` says "refused,
  // and the condition is already on screen" at every call site and neither half of
  // that is true here. `signal.reason` rather than a constructed error: it is what the
  // abort carried, and on an engine too old to supply one this throws `undefined`.
  if (stopping !== undefined && stopping.signal.aborted) {
    throw stopping.signal.reason;
  }
  // **A refusal answered to a request sent under a session this page no longer holds is
  // not reported at all** (#2404). Everywhere else the guard sits at the caller, after
  // this function returns; here it cannot, because `refused` renders *before* the return
  // — which is the shape adversarial review recorded at round 12 of PR #2393, one panel
  // over, and closed there by aborting the superseded listing.
  //
  // **What is at stake is a live session, not a stale panel.** Let a listing hang, let
  // the session end, let the owner re-enter, and then let the held request go: it
  // carries the old header half and the *new* cookie, so the gateway answers
  // `cookie-half-mismatch` — and `refused` → `report` → `sessionLost` forgets the half
  // of the session the owner has just started and throws them back to the bootstrap
  // form. A dead request ending a live session, from the one door a comparison after the
  // `await` cannot reach.
  //
  // **`noticed` is deliberately outside it**, and adversarial review's round 1 found the
  // version where it was not: it is a fact about the request, not about the panel, so
  // its caller classifies the answer it really got; what the guard withholds is the
  // reveal.
  if (noticed !== undefined) {
    noticed(body);
  }
  //
  // **And it is withheld rather than written quietly into the panel's slot**, which is
  // the one question in this sweep two rounds of review answered in opposite directions
  // and neither ADR settles. Round 3: a page whose ceremony outlived its session is
  // *looking at* the panel it pressed the control in, and telling it nothing leaves the
  // owner believing a destruction happened. Round 4: a panel's fault slot is one slot,
  // so a condition written there after a newer session's listing has re-filled that panel
  // sits above rows it is not about. Both are true; a slot that is per-panel cannot be
  // both. What ships is the rule #2404 asked for, uniform and with no race in it — a
  // resumed continuation whose session has ended puts nothing on the screen — and #2451
  // carries the question with both readings written out.
  if (!sameSession(half, era)) {
    return null;
  }
  refused(panelId, body, response.status);
  return null;
}

// How many reads of the conversations listing have been *begun*, which is what a
// forget's outcome has to still be the newest of before it may be written.
//
// **Begun and not finished**, which is the whole point of it and adversarial review
// round 1's second finding. Accept a forget, let its refresh hang, press
// "Conversations", and let the owner's newer read return first: the older refresh
// then resumes and writes its outcome over a listing that was read afterwards and
// had already cleared the slot. Counting reads as they start is what lets the
// resuming one see that it is no longer the last word.
let listed = 0;

// The listing read in flight, or `null`.
//
// **A superseded read must not render either half of what it came back with**
// (adversarial review round 6). Two reads of this listing can overlap — a forget's
// own refresh and the owner pressing "Conversations" — and the one that resumes last
// wins the panel whether or not it is the newer. It re-renders a snapshot taken
// before the newer one, so a conversation destroyed in between comes back as a row
// for a conversation that is gone; and its refusal, if it had one, is written
// into the panel by `relay` before this function sees a value at all.
//
// Stopping the read closes both, which a comparison after the `await` closes only the
// first of.
let listing = null;

// Read the listing, and hand back the generation the read ran under.
//
// The return value is for `forgetConversation` alone and is returned from **every**
// path, the refusals included: a forget whose refresh failed still destroyed
// something and still owes the owner the sentence saying so, so a read that ended in
// a fault must not silently swallow the outcome as well.
async function listConversations() {
  listed += 1;
  if (listing !== null) {
    const superseded = listing;
    listing = null;
    superseded.abort();
  }
  const mine = listed;
  fault(null, "conversations");
  // The outcome of a forget belongs to the forget, not to the panel: reading the
  // listing afresh is a new question, and an outcome left standing above it would be
  // a claim about a listing it was never made against. `forgetConversation` writes
  // its own outcome *after* the refresh it triggers, and only while that refresh is
  // still the newest one, so this clears nothing that is owed.
  sayForgotten(null);
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return mine;
  }
  const stopping = new AbortController();
  listing = stopping;
  const era = sessionEra;
  try {
    const body = await relay(half, "/conversations", {}, "conversations", stopping);
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return mine;
    }
    if (body === null || mine !== listed) {
      return mine;
    }
    listing = null;
    const list = el("conversation-list");
    clearNode(list);
    if (body.conversations.length === 0) {
      line(list, "No conversations yet.", "hint");
    }
    knowStarts(body.conversations);
    body.conversations.forEach((one) => renderConversation(list, one));
    show("conversations", true);
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return mine;
    }
    // An abort is not a transport failure, and only the newest read is entitled to
    // say the gateway has gone.
    if (mine === listed) {
      fault(GATEWAY_GONE, "conversations");
    }
  }
  return mine;
}

// What the Conversations panel calls a conversation it read the digest of: its name
// (`conversationName`), or its start where no listing has named it.
function listedName(held) {
  return conversationName(held.id) || chatTime(held.started_at);
}

function renderConversation(list, summary) {
  const item = document.createElement("div");
  item.className = "conversation-row";
  // Which conversation the row is, for nothing on screen: its name is its start.
  item.dataset.conversation = summary.id;
  // **Which conversation this row is** (#1371's first clause, found by driving the
  // page rather than by reading it). Every other line about a conversation on this
  // page names it — the indicator, the destroy ceremony, the outcome of a forget —
  // and the listing they all send the owner to named none of them: three rows of two
  // timestamps, and the sentence that appears after a tap names an id that was never
  // on screen before the tap.
  //
  // Its own line rather than a clause of the next one, because the name is what the
  // eye is looking for and a phone puts it behind two long instants otherwise. The name
  // is the one the chat gives it — when it started (`chatTime`) — rather than the hub's
  // id, which a person has never been shown anywhere else (#3209's follow-on).
  line(item, conversationName(summary.id), "conversation-name");
  const when = localTime(summary.last_turn_at || summary.last_active_at);
  const active = localTime(summary.last_active_at);
  // Both instants cross and they are different facts (ADR-0074 §2): activity is
  // when someone was last here and orders the list, and `last_turn_at` is when a
  // turn was last recorded. A conversation with no turn says so rather than
  // borrowing the other reading.
  line(
    item,
    summary.last_turn_at
      ? `Last turn ${when} — active ${active}`
      : `No turn yet — active ${active}`,
    "hint"
  );
  // **No "Continue" here** (ADR-0309 §5:4). It continued a conversation into the Ask
  // form, which retired; the chat is where a conversation is continued, and its own
  // listing — the same `/conversations` read — opens each one.
  const forget = document.createElement("button");
  forget.type = "button";
  forget.textContent = "Forget";
  forget.addEventListener("click", () => forgetConversation(summary.id));
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
  const era = sessionEra;
  try {
    const digest = await relay(half, "/conversation", { conversation_id: id }, "conversations");
    // Not this session's answer (#2404). **The confirmation is the display here**: this
    // read exists only to put the record in front of the owner before it is destroyed,
    // and a `window.confirm` carrying a belief's content, a conversation's turn count or
    // a notification's summary is that content on screen over a form asking for a
    // session. Nothing has been destroyed at this point, so there is nothing this owes
    // an account of. Adversarial review, round 2, `major`.
    if (!sameSession(half, era)) {
      return;
    }
    if (digest === null) {
      return;
    }
    const held = digest.conversation;
    knowStarts([held]);
    // ADR-0293 §5:7's plain disclosure: what forgetting removes, that the
    // conversation is still read while the owner talks there, and that only
    // deleting removes it.
    const asked = window.confirm(
      `Forget the conversation from ${listedName(held)}? It holds ` +
        `${held.recorded_turns} recorded ` +
        `turn(s), from ${localTime(held.started_at)} to ` +
        `${held.last_turn_at ? localTime(held.last_turn_at) : "no turn yet"}. ` +
        "Forgetting removes them from the assistant's memory, so it no longer " +
        "recalls them anywhere else. The conversation and its transcript stay: the " +
        "assistant still reads it while you keep talking there, and only deleting " +
        "removes it."
    );
    if (!asked) {
      return;
    }
    const done = await relay(half, "/conversation/forget", { conversation_id: id }, "conversations");
    if (done === null) {
      return;
    }
    const read = await listConversations();
    // **After its own refresh, and only while that refresh is still the newest**
    // (adversarial review round 1). `listConversations` clears this slot on every
    // read, so writing before the refresh would be writing into a slot the refresh
    // then empties — which is what makes the order load-bearing rather than cosmetic.
    // And a refresh that lost its race to a listing the owner asked for afterwards is
    // no longer the last word on what is on screen, so it does not get to write over
    // one: the outcome is dropped rather than restored above a newer listing.
    if (read === listed) {
      sayForgotten(statedForget(held, done.destroyed));
    }
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "conversations");
  }
}

// Whether the forget took effect, said (#1371's third clause).
function sayForgotten(text) {
  const slot = el("forget-outcome");
  slot.textContent = text === null ? "" : text;
  slot.hidden = text === null;
}

// What the hub answered, in words.
//
// **`destroyed` is read rather than assumed.** Since ADR-0293 §11:4
// `forget_conversation` is memory-only and answers whether an episode was forgotten;
// the conversation and its transcript stay either way (§2:4, §5:6). Nothing to forget
// and something forgotten are different facts, and the honest rendering says which.
//
// **The count is the digest's, read before the forget**, which is the only moment it
// was readable — after the forget there is nothing left to count.
function statedForget(held, destroyed) {
  const named = `the conversation from ${listedName(held)}`;
  if (!destroyed) {
    const nothing = "held nothing in the assistant's memory, so nothing was forgotten.";
    return `${capitalised(named)} ${nothing}`;
  }
  return (
    `The assistant has forgotten the ${held.recorded_turns} recorded turn(s) of ${named}, ` +
    "and no longer recalls them anywhere else. The conversation and its transcript " +
    "stay; only deleting removes them."
  );
}

// --- the chat (ADR-0293) -----------------------------------------------------
//
// **Conversations that keep their own transcript.** A message is written into a
// conversation as the owner's act in the medium (§4) and is *received* once the
// conversation has recorded it; the assistant answers by writing a message of its own
// (§6), which reaches this page as a change. What the assistant is doing is the
// conversation's current state, read with it and shown beside the transcript, never in
// it (§8:1).
//
// **Following is the change stream** (ADR-0296 §4, ADR-0298 §7). The page reads the
// chat space's latest sequence number once when the chat opens, then holds one stream
// open from it, through the gateway, and applies each change as it arrives — with the
// snapshot a change carries where it makes this device a reader, the current state of
// a conversation as it is pushed, and this device's roles. It does that while the chat
// is open and the page is visible, **and says so on screen**. A stream that ends —
// refused, cut, gone silent, or ended by a hub shutting down — stops the following and
// says why; nothing opens it again but the owner's press or one of ADR-0182 §7's two
// events, the page becoming visible or the network coming back, each announced. The
// stream it opens then starts **from the last change this page applied** (§4:4), so
// nothing is missed and nothing applied is asked for again.
//
// **The device is the gateway's to name** (ADR-0296's record on ADR-0177 §1:5). This
// page is told which device it is, so it can offer to add itself, and never sends a
// device of its own.

// Whether this browser has the chat open, and which conversation this tab is reading.
//
// **Open is the browser's, in `localStorage`** (#3098): the page is the chat first, so
// once the owner has opened it here every load opens it again, in any tab — the owner's
// one press, kept, rather than a stream opened on a load nobody asked for. It is not a
// session value: it admits nothing, and holds nothing the hub sent.
//
// **Which conversation is the tab's, in `sessionStorage`**: which conversation is open is
// what *this view* is looking at, and two tabs are two views.
const CHAT_OPEN_KEY = "assistant.session.chat-open";
const CHAT_CONVERSATION_KEY = "assistant.session.chat-conversation";

// The surface's own page size (`DEFAULT_PAGE_SIZE`), which is what a full page holds.
const CHAT_PAGE = 50;

// The hub's own machine, as a device (ADR-0298 §3:1). It is an end of every
// conversation, so no change removes it from one and this page never drops one for it.
const HUB_DEVICE = "hub";

const CHAT_CATCHING_UP = "Reading the chat…";
const CHAT_FOLLOWING =
  "Following this chat: messages appear here as they are written, from any of your " +
  "devices.";
const CHAT_PAUSED = "Paused while this page is hidden. It follows again when you come back.";
const CHAT_CAME_BACK = "You came back, so this page is following the chat again.";
const CHAT_NETWORK_BACK = "The network is back, so this page is following the chat again.";
const CHAT_ASKED_AGAIN = "Following the chat again, because you asked.";
const CHAT_STOPPED_GONE =
  "Stopped following the chat: the gateway did not answer. Nothing is retried on its " +
  "own — follow again when you are ready.";
const CHAT_STOPPED_REFUSED =
  "Stopped following the chat: the last read was refused, for the reason above. " +
  "Nothing is retried on its own.";
// How a stream that carried something ended, each its own sentence for the reason the
// delivery stream's are (ADR-0175 §2): a cut, a silence and a head that never came are
// different evidence, and the hub shutting down is no failure at all.
const CHAT_STREAM_CUT =
  "Stopped following the chat: the connection closed with no ending from the gateway. " +
  "Nothing is retried on its own — follow again when you are ready, and this page " +
  "carries on from the last change it showed.";
const CHAT_STREAM_SILENT =
  `Stopped following the chat: nothing arrived — not even the gateway's keep-alive — ` +
  `for ${SILENT_CADENCES} times the keep-alive cadence the gateway stated, so this ` +
  "browser let the connection go. Follow again when you are ready, and this page " +
  "carries on from the last change it showed.";
const CHAT_STREAM_STALLED =
  `Stopped following the chat: nothing answered the request to follow it for ` +
  `${HEAD_DEADLINE_MILLISECONDS / 1000} seconds, so this browser let it go. Follow ` +
  "again when you are ready.";
const CHAT_STREAM_MISFRAMED =
  "Stopped following the chat: the gateway wrote a line this browser could not read, " +
  "so it read no further. Follow again when you are ready.";
const CHAT_HUB_ENDED =
  "Stopped following the chat: the hub is shutting down. Follow again once it is back, " +
  "and this page carries on from the last change it showed.";
// What the page says when it drops what it held (ADR-0298 §7:17, ADR-0296 §4:8).
const CHAT_DROPPED_NO_ROLE =
  "The hub refused this device for holding no role, so this page has let go of every " +
  "conversation it showed. Once the device is given a role, follow again.";

// The current state (ADR-0293 §8), in words. "Working" is informational: the box stays
// open, and a message written meanwhile is taken up on its own (ADR-0349 §8:1).
const CHAT_WORKING = "The assistant is working on this… You can keep writing.";
const CHAT_ENDINGS = {
  done: "The assistant finished what you last asked here.",
  couldnt_finish: "The assistant couldn't finish what you last asked here.",
  interrupted:
    "The assistant was interrupted before it finished what you last asked here. Send " +
    "it again if you still want an answer.",
  stopped: "What you last asked here was stopped.",
};

// What a stop found (ADR-0297 §5), in words: only what each answer means. "Stopped"
// never says the work halted at once — what it was in the middle of finishes first
// (ADR-0297 §4) and anything already sent is not called back (ADR-0295 §2) — and the
// two answers that wrote nothing say so (§5:5, §5:6).
const CHAT_STOPPING = "Stopping…";
const CHAT_STOP_ANSWERS = {
  stopped:
    "Stopped. Nothing new starts in this, and nothing more is written here for it. " +
    "What it was in the middle of finishes first, and anything it already sent is not " +
    "called back.",
  already_ended: "That had already ended, so nothing was stopped.",
  no_such_activation: "The assistant holds nothing that says this ran, so nothing was stopped.",
};
const CHAT_STOP_UNKNOWN = "The stop was answered in a way this page cannot put into words.";

// A device's access, as a conversation's end (ADR-0293 §3:5).
const CHAT_ACCESS = [
  { value: "read_write", label: "Reads and writes" },
  { value: "read", label: "Reads only" },
  { value: "write", label: "Writes only" },
];

// What each act says before it is taken. Deleting and forgetting are two acts and the
// page offers them side by side, never as one (ADR-0293 §2:7); forgetting's sentence
// is §5:7's disclosure.
const CHAT_DELETE_MESSAGE =
  "Delete this message? It is removed from this conversation on every device. A reply " +
  "to it stays, and deleting forgets nothing the assistant remembers.";
const CHAT_DELETE_CONVERSATION =
  "Delete this conversation and its transcript, on every device? This forgets " +
  "nothing: what the assistant remembers from it stays until you forget it.";
const CHAT_FORGET =
  "Forget this conversation? Forgetting removes its episodes from the assistant's " +
  "memory, so it no longer recalls them anywhere else. The assistant still reads the " +
  "conversation while you keep talking there, and only deleting removes the conversation.";

// The pending message's state, in words.
const CHAT_SENT_STATES = {
  sending: "Sending…",
  received: "Received.",
  unknown:
    "No answer came back, so it is not known whether this arrived. Sending it again is " +
    "safe: it is the same message, and it is recorded once.",
  "not-an-end":
    "Not sent: this device is not one of this conversation's devices for writing.",
  "no-such-reply": "Not sent: the message it replies to is not in this conversation.",
  gone: "Not sent: this conversation no longer exists.",
  refused: "Not sent: the gateway refused it, for the reason above.",
};

const chat = {
  open: false,
  // Bumped on every load, so a load that has been superseded stops where it is.
  era: 0,
  // The last sequence number this page applied (ADR-0296 §4:4's cursor).
  cursor: null,
  following: false,
  // Bumped whenever following starts or stops, so a stream left over from before either
  // applies nothing more when its next value comes.
  ticks: 0,
  // The one change stream this page holds, or `null`: its abort controller, and whether
  // this page released it — an ending the page performed, which says nothing about the
  // gateway. One at a time, so no two streams apply changes against one cursor.
  stream: null,
  // `undefined` until read; `null` where the gateway cannot name this browser's device.
  thisDevice: undefined,
  // This device's roles, as the hub's stream last sent them (ADR-0298 §7:9), or
  // `undefined` until it has; an engine followed in-process sends none.
  roles: undefined,
  myDevices: [],
  listing: [],
  listed: 0,
  unread: new Set(),
  // Conversations a change has told this device it no longer reads, since the chat
  // opened. A listing read before that change answered with them, and must not bring
  // one back; a change that makes this device a reader again takes it off.
  dropped: new Set(),
  selected: null,
  // Whether a phone shows the open conversation rather than the list (`renderChatView`):
  // set by opening one, and cleared by the conversation's own control back to the list,
  // which leaves it open and reads nothing.
  reading: false,
  // Bumped on every change of selection, so a read for a conversation the owner left
  // renders nothing.
  chosen: 0,
  entries: new Map(),
  deleted: new Set(),
  // Messages older than what is loaded that a reply on screen names, read for the reply;
  // the positions already asked about, answered or not; and the selection a run of that
  // reading is out for (`resolveReplies`).
  referenced: new Map(),
  unfound: new Set(),
  resolving: null,
  resolveAgain: false,
  oldest: null,
  state: null,
  // The stops this page sent for the activations the state names, or `null`: a map from
  // each id it named to whether its request is out and the answer once read
  // (`renderChatStop`).
  stop: null,
  devices: null,
  pending: [],
  replyTo: null,
  // **The change stream is the authority on every set of devices** (ADR-0293 §5:10):
  // a change is applied always, in sequence order, and is never skipped. A snapshot
  // read is applied only where nothing has set that subject since its request went out
  // (`settle`), so it can put no older state over what the stream already said. `seen` counts each
  // subject's settings: "my devices", the open conversation's devices, and its state.
  seen: { mine: 0, devices: 0, state: 0 },
  // Whether the reads that open the chat all answered. Where one did not, following
  // again opens the chat again, since nothing re-reads it of its own motion.
  loaded: false,
};

// Whether an answer whose request went out when `subject` had been set `before` times
// may set it now; and if so, the subject counted as set again.
function settle(subject, before) {
  if (chat.seen[subject] !== before) {
    return false;
  }
  chat.seen[subject] += 1;
  return true;
}

function chatWasOpen() {
  try {
    return window.localStorage.getItem(CHAT_OPEN_KEY) !== null;
  } catch (_) {
    return false;
  }
}

function storedChatConversation() {
  try {
    return window.sessionStorage.getItem(CHAT_CONVERSATION_KEY);
  } catch (_) {
    return null;
  }
}

function rememberChat() {
  try {
    window.localStorage.setItem(CHAT_OPEN_KEY, "open");
    if (chat.selected === null) {
      window.sessionStorage.removeItem(CHAT_CONVERSATION_KEY);
    } else {
      window.sessionStorage.setItem(CHAT_CONVERSATION_KEY, chat.selected);
    }
  } catch (_) {
    // A browser that will not store keeps the chat open until it reloads, which is all
    // this was for.
  }
}

// The owner opening the chat, or a reload restoring the chat this tab had open.
function openChat() {
  show("chat", true);
  renderChatView();
  if (!chat.open) {
    chat.open = true;
    // Read before anything is written back, so a reload keeps the conversation it had.
    if (chat.selected === null) {
      chat.selected = storedChatConversation();
    }
    rememberChat();
    void loadChat();
    return;
  }
  rememberChat();
}

// The session ended: the chat stops following and forgets what it held.
function closeChat() {
  chat.open = false;
  chat.era += 1;
  stopFollowing(null, false);
  chat.cursor = null;
  chat.roles = undefined;
  chat.selected = null;
  chat.entries = new Map();
  chat.deleted = new Set();
  chat.referenced = new Map();
  chat.unfound = new Set();
  chat.pending = [];
  chat.reading = false;
  el("chat-thread").hidden = true;
  renderChatView();
}

// --- the chat's two halves (#3098) --------------------------------------------
//
// The conversations down the side and the open one beside them, where there is room for
// both; on a phone, one at a time. The width is the stylesheet's one breakpoint, asked of
// the browser here rather than written twice, and what is not on screen is set aside
// with the attribute, the sheet's one way of hiding anything (#1475). Nothing is read
// and nothing is dropped: the list and the open conversation are both kept, and going
// back to the list leaves the conversation open.
const NARROW = window.matchMedia("(max-width: 480px)");

function renderChatView() {
  const open = !el("chat-thread").hidden;
  const narrow = NARROW.matches;
  el("chat-empty").hidden = open;
  el("chat-side").hidden = narrow && open && chat.reading;
  el("chat-main").hidden = narrow && !(open && chat.reading);
  el("chat-back").hidden = !narrow;
  // Back on screen, the open conversation's new messages are no longer news.
  if (chatReadable() && chat.unread.delete(chat.selected)) {
    renderChatListing();
  }
}

// Whether the open conversation's transcript is on screen: there is one, and this is not
// a phone showing the list instead.
function chatReadable() {
  return !el("chat-thread").hidden && (!NARROW.matches || chat.reading);
}

function backToList() {
  chat.reading = false;
  renderChatView();
}

// Catch up from nothing: the cursor first, then what the page shows, then follow. Each
// read after the cursor may already hold a change the cursor is before, and applying a
// change twice changes nothing — so the order is safe.
async function loadChat() {
  chat.era += 1;
  const mine = chat.era;
  chat.loaded = false;
  // The listing below is read afresh, so it says what this device reads now.
  chat.dropped = new Set();
  stopFollowing(CHAT_CATCHING_UP, false);
  fault(null, "chat");
  // Each opening read either answers or stops the chat where it is, with the control
  // that opens it again: nothing here is read again of the page's own motion.
  const opened =
    (await readChatCursor()) &&
    mine === chat.era &&
    (await readMyDevices()) &&
    mine === chat.era &&
    (await listChat(false));
  if (mine !== chat.era) {
    return;
  }
  if (!opened) {
    if (chat.open) {
      stopFollowing(CHAT_STOPPED_REFUSED, true);
    }
    return;
  }
  chat.loaded = true;
  if (chat.selected !== null && !(await selectChat(chat.selected))) {
    return;
  }
  if (mine === chat.era) {
    startFollowing(CHAT_FOLLOWING);
  }
}

// The chat space's latest sequence number, read as the changes to no conversation: the
// answer's `next_after` is the latest number where the page is not full.
async function readChatCursor() {
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return false;
  }
  const era = sessionEra;
  let after = 0;
  let refusal = null;
  try {
    for (;;) {
      const body = await relay(
        half,
        "/chat/changes",
        { after: after, conversation_ids: [] },
        "chat",
        undefined,
        (said) => {
          refusal = said;
        }
      );
      if (!sameSession(half, era)) {
        return false;
      }
      if (body === null) {
        dropOnRefusal(refusal);
        return false;
      }
      after = body.next_after;
      if (body.changes.length < CHAT_PAGE) {
        break;
      }
    }
  } catch (_) {
    if (!sameSession(half, era)) {
      return false;
    }
    fault(GATEWAY_GONE, "chat");
    return false;
  }
  chat.cursor = after;
  return true;
}

// Answers whether "my devices" and this browser's own device were read.
async function readMyDevices() {
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return false;
  }
  const era = sessionEra;
  const before = chat.seen.mine;
  try {
    const body = await relay(half, "/chat/devices", {}, "chat");
    if (!sameSession(half, era)) {
      return false;
    }
    if (body === null) {
      return false;
    }
    chat.thisDevice = body.this_device;
    if (settle("mine", before)) {
      chat.myDevices = body.devices;
    }
    renderMyDevices();
    renderConversationDevices();
    return true;
  } catch (_) {
    if (!sameSession(half, era)) {
      return false;
    }
    fault(GATEWAY_GONE, "chat");
    return false;
  }
}

// --- following ----------------------------------------------------------------

function sayFollowing(text) {
  el("chat-follow").textContent = text;
}

function startFollowing(said) {
  // A chat whose opening reads did not all answer is opened again by the owner's press
  // and by nothing else, so its control stays where it is (`followAgain`).
  if (!chat.open || chat.following || chat.cursor === null || !chat.loaded) {
    return;
  }
  // A page that is hidden by the time it would start waits to be seen again, and says
  // so; coming back is one of ADR-0182 §7's two events, and starts it.
  if (document.visibilityState !== "visible") {
    sayFollowing(CHAT_PAUSED);
    el("chat-follow-again").hidden = true;
    return;
  }
  chat.following = true;
  chat.ticks += 1;
  sayFollowing(said);
  el("chat-follow-again").hidden = true;
  void followChat(chat.ticks);
}

// `said` is what the page now says about following, or `null` to leave it; `offer` is
// whether the owner is handed the control that starts it again. The stream goes with
// it: a page that is not following holds none, and gives its hub connection back.
function stopFollowing(said, offer) {
  chat.following = false;
  chat.ticks += 1;
  releaseChatStream();
  if (said !== null) {
    sayFollowing(said);
  }
  el("chat-follow-again").hidden = !offer;
}

function releaseChatStream() {
  const open = chat.stream;
  if (open === null) {
    return;
  }
  chat.stream = null;
  open.released = true;
  open.reader.abort();
}

// The owner pressing "Follow changes again": the chat opened again where an opening read
// failed or the chat space was started afresh, and following started again otherwise.
function followAgain() {
  if (chat.cursor === null || !chat.loaded) {
    void loadChat();
    return;
  }
  fault(null, "chat");
  startFollowing(CHAT_ASKED_AGAIN);
}

// The change stream, from the last change this page applied, until it ends or this page
// lets it go. It opens nothing else and retries nothing: every ending stops the
// following and says why (ADR-0182 §7). Its deadlines are the delivery stream's, for
// that stream's reasons (`readDeliveries`): one on the head's arrival, and once the head
// has stated the gateway's keep-alive cadence, one on silence.
async function followChat(tick) {
  const half = headerHalf();
  if (half === null) {
    stopFollowing(null, false);
    return;
  }
  const era = sessionEra;
  const reader = new AbortController();
  // `headed` once the gateway has answered with the stream's head: the stream is open.
  const open = { reader, released: false, headed: false };
  chat.stream = open;
  let cadence = null;
  let silent = false;
  let stalled = false;
  let deadline = null;
  const arm = (at) => {
    deadline = window.setTimeout(
      () => {
        if (performance.now() < at) {
          arm(at);
          return;
        }
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
  const hush = () => {
    window.clearTimeout(deadline);
    deadline = null;
  };
  const heard = () => {
    hush();
    if (cadence !== null) {
      arm(performance.now() + cadence * SILENT_CADENCES);
    }
  };
  // A stream released by this page, or one that following has since stopped or started
  // again without, says nothing: what superseded it has already said what is true. One
  // that outlived its session says nothing either (#2455), asked at each ending below.
  const current = () => !open.released && tick === chat.ticks;
  arm(performance.now() + HEAD_DEADLINE_MILLISECONDS);
  try {
    const response = await fetch("/chat/follow", {
      method: "POST",
      headers: admitted(half, true),
      body: JSON.stringify({ after: chat.cursor }),
      signal: reader.signal,
    });
    hush();
    if (!response.ok) {
      const body = await readBody(response);
      if (!sameSession(half, era)) {
        return;
      }
      if (!current()) {
        return;
      }
      dropOnRefusal(body);
      stopFollowing(CHAT_STOPPED_REFUSED, true);
      refused("chat", body, response.status);
      return;
    }
    open.headed = true;
    cadence = usableCadence(response.headers.get(KEEP_ALIVE_HEADER));
    heard();
    // What the conversation on screen is doing now: the stream pushes a state when it
    // changes, so one that changed while nothing here was following is read once. A
    // failure of that read is said in the panel and is not tried again, but it does not
    // stop the stream: what the stream is about to say may be the very reason the read
    // failed — the change that removed this device from the conversation.
    if (chat.selected !== null) {
      void readChatDigest(chat.selected, chat.chosen);
    }
    let terminal = null;
    for await (const value of streamValues(response)) {
      if (!current() || !sameSession(half, era)) {
        return;
      }
      heard();
      if (TERMINAL_KINDS.has(value.kind)) {
        terminal = value;
        break;
      }
      applyStreamed(value);
    }
    if (!sameSession(half, era)) {
      return;
    }
    if (!current()) {
      return;
    }
    if (terminal === null) {
      stopFollowing(CHAT_STREAM_CUT, true);
    } else if (terminal.kind === "end") {
      // Where the hub would have the stream opened again from (`ChatStreamEnd`).
      chat.cursor = Math.max(chat.cursor, terminal.next_after);
      stopFollowing(CHAT_HUB_ENDED, true);
    } else {
      dropOnRefusal(terminal);
      stopFollowing(CHAT_STOPPED_REFUSED, true);
      report("chat", terminal, describe(terminal, response.status));
    }
  } catch (error) {
    if (!current() || !sameSession(half, era)) {
      return;
    }
    if (stalled) {
      stopFollowing(CHAT_STREAM_STALLED, true);
    } else if (silent) {
      stopFollowing(CHAT_STREAM_SILENT, true);
    } else if (error instanceof MisframedValue) {
      stopFollowing(CHAT_STREAM_MISFRAMED, true);
    } else {
      stopFollowing(CHAT_STOPPED_GONE, true);
      fault(GATEWAY_GONE, "chat");
    }
  } finally {
    if (chat.stream === open) {
      chat.stream = null;
    }
    window.clearTimeout(deadline);
  }
}

// One value of the stream that is not its ending. A change moves the cursor once it is
// applied (ADR-0296 §4:4); the other kinds carry no sequence number and move nothing.
function applyStreamed(value) {
  if (value.kind === "change") {
    applyChanges([value.change], value.snapshot);
    chat.cursor = value.change.seq;
  } else if (value.kind === "state") {
    // Always applied: the stream is the authority (`seen`'s comment).
    if (value.conversation_id === chat.selected) {
      chat.seen.state += 1;
      chat.state = value.state;
      renderChatState();
    }
  } else if (value.kind === "roles") {
    chat.roles = value.roles;
    renderMyDevices();
  }
  // `alive` is the keep-alive: it restarts the silence deadline, and that is all.
}

// Whether this device reads a conversation whose devices are `devices`, or whether the
// page cannot tell: the hub's own machine reads every conversation, and a device the
// gateway could not name has nothing to look for in the set.
function readsHere(devices) {
  const named = chat.thisDevice;
  if (named === undefined || named === null || named === HUB_DEVICE) {
    return true;
  }
  return devices.some(
    (one) => one.device_id === named && (one.access === "read" || one.access === "read_write")
  );
}

// Apply changes in sequence order (ADR-0293 §5:10). Each is safe to apply twice, since a
// read made after the cursor may already hold it. `snapshot` is the conversation's
// entries where the change makes this device one of its readers (ADR-0298 §7:6), and
// `null` otherwise. Answers whether the conversation on screen changed.
function applyChanges(changes, snapshot) {
  let touched = false;
  let relist = false;
  changes.forEach((change) => {
    if (change.kind === "message_added") {
      if (change.conversation_id === chat.selected && !chat.deleted.has(change.message.position)) {
        chat.entries.set(change.message.position, change.message);
        touched = true;
        // A phone showing the list is not showing the open conversation, so its new
        // message is marked on its row as any other conversation's is (#3098).
        if (!chatReadable()) {
          chat.unread.add(change.conversation_id);
          relist = true;
        }
      } else {
        chat.unread.add(change.conversation_id);
        relist = true;
      }
    } else if (change.kind === "message_deleted") {
      // §5:12: a device removes the message on seeing its marker.
      if (change.conversation_id === chat.selected) {
        chat.entries.delete(change.position);
        chat.referenced.delete(change.position);
        chat.deleted.add(change.position);
        touched = true;
      }
    } else if (change.kind === "conversation_started") {
      relist = true;
    } else if (change.kind === "conversation_deleted") {
      relist = true;
      chat.unread.delete(change.conversation_id);
      if (change.conversation_id === chat.selected) {
        chatGone(`${capitalised(chatName(change.conversation_id))} was deleted.`);
      }
    } else if (change.kind === "devices_changed") {
      // Always applied: the stream is the authority (`seen`'s comment).
      if (change.conversation_id === null) {
        chat.seen.mine += 1;
        chat.myDevices = change.devices;
        renderMyDevices();
        renderConversationDevices();
      } else if (!readsHere(change.devices)) {
        // The change that removed this device: it drops the conversation (ADR-0296
        // §4:8), and nothing of it stays on screen.
        dropConversation(change.conversation_id);
      } else {
        if (change.conversation_id === chat.selected) {
          chat.seen.devices += 1;
          chat.devices = change.devices;
          renderConversationDevices();
        }
        // A conversation this device has just begun to read is listed.
        chat.dropped.delete(change.conversation_id);
        relist = relist || snapshot !== null;
      }
    }
    // The conversation as it stood at the change that added this device, for the one
    // on screen; any other is read whole when it is opened (ADR-0293 §5:13).
    if (snapshot !== null && change.conversation_id === chat.selected) {
      snapshot.forEach((entry) => applyEntry(entry, chat.entries));
      touched = true;
    }
  });
  if (touched) {
    renderTranscript();
    // A reply that came in may name a message older than what is loaded.
    void resolveReplies(chat.selected, chat.chosen);
  }
  if (relist) {
    void relistChat();
  }
  return touched;
}

// A conversation this device no longer reads, dropped: out of the listing, its unsent
// messages with it, and off the screen where it is open (ADR-0296 §4:8).
function dropConversation(id) {
  // Named while the listing still holds it, since the name is read off the listing.
  const name = chatName(id);
  chat.dropped.add(id);
  chat.listing = chat.listing.filter((summary) => summary.id !== id);
  chat.unread.delete(id);
  chat.pending = chat.pending.filter((one) => one.conversation !== id);
  if (id === chat.selected) {
    chatGone(`This device no longer reads ${name}, so this page has let it go.`);
    return;
  }
  renderChatListing();
}

// A refusal of the change stream or of the changes read for holding no role drops every
// conversation this page holds, as if it had seen the change that removed it from each
// (ADR-0298 §7:17). Only that reason: a device refused for a role that does not allow an
// act still reads what it reads.
function dropOnRefusal(body) {
  if (body === null || body.fault !== "device-without-role") {
    return;
  }
  // A listing read still out was answered for a device that held something: it is
  // dropped with the rest rather than let back in when it lands.
  chat.listed += 1;
  chat.listing = [];
  chat.unread = new Set();
  chat.pending = [];
  el("chat-more").hidden = true;
  chatGone(CHAT_DROPPED_NO_ROLE);
}

// The listing read again because the stream said a conversation came or went. A failure
// is not left for a later change to repair: it stops the following, and the owner's
// press opens the chat again, listing included (`followAgain`).
async function relistChat() {
  const era = sessionEra;
  if (!(await listChat(false)) && era === sessionEra && chat.open) {
    chat.loaded = false;
    stopFollowing(CHAT_STOPPED_REFUSED, true);
  }
}

// ADR-0182 §7's two events, and nothing else, start following again of the page's own
// motion — each announced. Hiding the page pauses it, and says so.
function chatVisibility() {
  if (!chat.open) {
    return;
  }
  if (document.visibilityState === "visible") {
    startFollowing(CHAT_CAME_BACK);
  } else if (chat.following) {
    stopFollowing(CHAT_PAUSED, false);
  }
}

function chatOnline() {
  if (chat.open && document.visibilityState === "visible") {
    startFollowing(CHAT_NETWORK_BACK);
  }
}

// --- the conversations --------------------------------------------------------

// Answers whether the listing was read; a read a newer one replaced is not a failure.
async function listChat(more) {
  chat.listed += 1;
  const mine = chat.listed;
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return false;
  }
  const era = sessionEra;
  const offset = more ? chat.listing.length : 0;
  try {
    const body = await relay(half, "/conversations", { offset: offset }, "chat");
    if (!sameSession(half, era)) {
      return false;
    }
    if (mine !== chat.listed) {
      return true;
    }
    if (body === null) {
      return false;
    }
    // A listing read before a removal reached this page still names what was removed.
    const held = body.conversations.filter((summary) => !chat.dropped.has(summary.id));
    knowStarts(held);
    chat.listing = more ? chat.listing.concat(held) : held;
    el("chat-more").hidden = body.conversations.length < CHAT_PAGE;
    renderChatListing();
    return true;
  } catch (_) {
    if (!sameSession(half, era)) {
      return false;
    }
    if (mine === chat.listed) {
      fault(GATEWAY_GONE, "chat");
      return false;
    }
    return true;
  }
}

// An instant in the chat, as a person reads one: the whole date and the time, in this
// browser's own language and zone (`localTime`), to the second where asked.
function chatTime(iso, seconds = false) {
  const at = instant(iso);
  return at === null ? iso : (seconds ? CHAT_TIME_SECONDS : CHAT_TIME).format(at);
}

// Every conversation this page has been told the start of — by the chat's listing, the
// Conversations panel's, a conversation started or one read whole — which is what names
// are told apart against (`conversationName`). Only ever added to, so that two panels
// holding different pages of conversations name each the same way, and a name is never
// handed on to another conversation when one is dropped from a listing.
//
// Each start is formatted once, as it arrives, and counted under its minute and its
// second, so a name is a lookup and a listing of any length is named in one pass.
const starts = new Map();
const byMinute = new Map();
const bySecond = new Map();

function knowStarts(summaries) {
  summaries.forEach((one) => {
    if (starts.has(one.id)) {
      return;
    }
    const known = { minute: chatTime(one.started_at), second: chatTime(one.started_at, true) };
    starts.set(one.id, known);
    byMinute.set(known.minute, (byMinute.get(known.minute) || 0) + 1);
    bySecond.set(known.second, (bySecond.get(known.second) || 0) + 1);
  });
}

// What a conversation is called (#3209's follow-on): when it started, since the listing
// carries nothing a person wrote — to the minute; to the second where another this
// page knows started in the same minute; and with the hub's id after it only where
// another started in the same second, which no person starting conversations does. So
// no two conversations are ever called the same, and the id is on screen only there.
function conversationName(id) {
  const known = starts.get(id);
  if (known === undefined) {
    return undefined;
  }
  if (byMinute.get(known.minute) === 1) {
    return known.minute;
  }
  return bySecond.get(known.second) === 1 ? known.second : `${known.second} · ${id}`;
}

// What the chat calls one conversation; one not yet in its listing is "this
// conversation".
function chatTitle(id) {
  const name = conversationName(id);
  return name === undefined ? "This conversation" : name;
}

// A sentence's first word, capitalised.
function capitalised(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// The same, inside a sentence. Where the page knows no start for it — every read that
// would have told it failed — it is named by the hub's id instead: a sentence about it
// may land after another conversation has been opened, and "this conversation" would
// then name that one.
function chatName(id) {
  const name = conversationName(id);
  return name === undefined ? `conversation ${id}` : `the conversation from ${name}`;
}

function renderChatListing() {
  // The open conversation is named from the listing, which may land after it opened.
  if (chat.selected !== null && !el("chat-thread").hidden) {
    el("chat-heading").textContent = chatTitle(chat.selected);
  }
  const list = el("chat-conversations");
  clearNode(list);
  if (chat.listing.length === 0) {
    const item = document.createElement("li");
    item.className = "hint";
    item.textContent = "No conversations yet.";
    list.appendChild(item);
    return;
  }
  // Each row is one control that opens its conversation (#3098). The open one is marked
  // as current and opening it again reads nothing: on a phone it only comes back to it.
  chat.listing.forEach((summary) => {
    const item = document.createElement("li");
    item.className = "chat-conversation-row";
    const open = document.createElement("button");
    open.type = "button";
    open.className = "chat-open";
    // Which conversation the row opens, for nothing on screen: its name is its start.
    open.dataset.conversation = summary.id;
    const name = document.createElement("span");
    name.className = "chat-name";
    name.textContent = conversationName(summary.id);
    open.appendChild(name);
    const when = `Last active ${chatTime(summary.last_active_at)}`;
    const said = document.createElement("span");
    said.className = "chat-when";
    said.textContent = chat.unread.has(summary.id) ? `${when} · new messages` : when;
    open.appendChild(said);
    if (summary.id === chat.selected) {
      open.setAttribute("aria-current", "true");
    }
    open.addEventListener("click", () => {
      if (summary.id === chat.selected && !el("chat-thread").hidden) {
        chat.reading = true;
        renderChatView();
        return;
      }
      void selectChat(summary.id);
    });
    item.appendChild(open);
    list.appendChild(item);
  });
}

async function startChat() {
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const era = sessionEra;
  try {
    const body = await relay(half, "/chat/start", {}, "chat");
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null) {
      return;
    }
    sayChat(null);
    void listChat(false);
    knowStarts([body.conversation]);
    await selectChat(body.conversation.id);
    el("chat-text").focus();
  } catch (_) {
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "chat");
  }
}

// Read one conversation: its recent transcript (§5:13), then its state and devices.
// Answers `false` where the state could not be read, and following has stopped for it.
async function selectChat(id) {
  chat.chosen += 1;
  const mine = chat.chosen;
  chat.selected = id;
  chat.entries = new Map();
  chat.deleted = new Set();
  chat.referenced = new Map();
  chat.unfound = new Set();
  chat.oldest = null;
  chat.state = null;
  chat.stop = null;
  chat.devices = null;
  // Nothing read for the conversation left behind may set this one's.
  chat.seen.devices += 1;
  chat.seen.state += 1;
  chat.unread.delete(id);
  setReplyTo(null);
  sayChat(null);
  rememberChat();
  chat.reading = true;
  el("chat-thread").hidden = false;
  renderChatView();
  el("chat-heading").textContent = chatTitle(id);
  renderChatListing();
  renderTranscript();
  renderChatState();
  renderConversationDevices();
  el("chat-reread").hidden = true;
  if (!(await readTranscript(id, mine, null)) && mine === chat.chosen) {
    // Nothing reads the transcript again of its own motion; the owner can.
    el("chat-reread").hidden = false;
  }
  // The state is read with the conversation; a failure of that read stops the following,
  // which would otherwise read it again of its own motion (ADR-0182 §7).
  if (mine === chat.chosen && chat.selected === id && !(await readChatDigest(id, mine))) {
    stopFollowing(CHAT_STOPPED_REFUSED, true);
    return false;
  }
  return true;
}

// The conversation on screen is gone — deleted here, elsewhere, or never there.
function chatGone(said) {
  chat.chosen += 1;
  chat.selected = null;
  chat.entries = new Map();
  chat.deleted = new Set();
  chat.referenced = new Map();
  chat.unfound = new Set();
  chat.state = null;
  chat.stop = null;
  chat.devices = null;
  setReplyTo(null);
  rememberChat();
  chat.reading = false;
  el("chat-thread").hidden = true;
  renderChatView();
  sayChat(said);
  renderChatListing();
}

function sayChat(text) {
  const slot = el("chat-said");
  slot.textContent = text === null ? "" : text;
  slot.hidden = text === null;
}

// Answers `false` where the page could not be read for the conversation still on screen.
async function readTranscript(id, mine, before) {
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return false;
  }
  const era = sessionEra;
  let refusal = null;
  const payload = before === null ? { conversation_id: id } : { conversation_id: id, before: before };
  try {
    const body = await relay(half, "/chat/transcript", payload, "chat", undefined, (said) => {
      refusal = said;
    });
    if (!sameSession(half, era)) {
      return true;
    }
    if (mine !== chat.chosen) {
      return true;
    }
    if (body === null) {
      if (refusal !== null && refusal.fault === "no-such-conversation") {
        chatGone(`${capitalised(chatName(id))} no longer exists.`);
        return true;
      }
      return false;
    }
    const entries = body.transcript.entries;
    // A marker is authoritative whichever arrived first: a page read before a deletion
    // the following has already applied must not bring the message back (§5:12).
    entries.forEach((entry) => applyEntry(entry, chat.entries));
    if (entries.length > 0) {
      const first = entries[0].position;
      chat.oldest = chat.oldest === null ? first : Math.min(chat.oldest, first);
    } else if (before !== null) {
      chat.oldest = 1;
    }
    renderTranscript(before === null);
    void resolveReplies(id, mine);
    return true;
  } catch (_) {
    if (!sameSession(half, era)) {
      return true;
    }
    if (mine === chat.chosen) {
      fault(GATEWAY_GONE, "chat");
      return false;
    }
    return true;
  }
}

// One entry of a transcript read, applied to `into` — the loaded transcript, or the
// replies' targets. A marker is applied everywhere a copy of the message is kept, so
// whichever read brings it, the text leaves the screen (§5:12).
function applyEntry(entry, into) {
  if (entry.deleted) {
    chat.deleted.add(entry.position);
    chat.entries.delete(entry.position);
    chat.referenced.delete(entry.position);
  } else if (!chat.deleted.has(entry.position)) {
    into.set(entry.position, entry);
  }
}

// The messages replies on screen name that are older than what is loaded, each read as
// the one entry before the position after it — a message or its marker — so a reply to
// a deleted message says so (§5:8) however far back that message was. Every target is
// read once, one read at a time; a run asked for while one is out runs again when it
// ends, so a reply arriving meanwhile is not missed. Where a read cannot be made the
// reply names the position, and that target is not read again of the page's own motion.
async function resolveReplies(id, mine) {
  if (chat.resolving === mine) {
    chat.resolveAgain = true;
    return;
  }
  chat.resolving = mine;
  try {
    do {
      chat.resolveAgain = false;
      if (!(await resolveOnce(id, mine))) {
        return;
      }
    } while (chat.resolveAgain && mine === chat.chosen);
  } finally {
    if (chat.resolving === mine) {
      chat.resolving = null;
    }
  }
}

// One pass over the targets not yet known. Answers whether it completed.
async function resolveOnce(id, mine) {
  const half = headerHalf();
  if (half === null) {
    return false;
  }
  const era = sessionEra;
  const wanted = new Set();
  chat.entries.forEach((entry) => {
    const target = entry.replies_to;
    if (
      target !== null &&
      !chat.entries.has(target) &&
      !chat.deleted.has(target) &&
      !chat.referenced.has(target) &&
      !chat.unfound.has(target)
    ) {
      wanted.add(target);
    }
  });
  for (const target of wanted) {
    // Asked about once per selection, answered or not: a lookup that failed is not
    // made again of the page's own motion (ADR-0182 §7); opening the conversation again
    // is the owner's way to ask again.
    chat.unfound.add(target);
    let body;
    try {
      body = await relay(
        half,
        "/chat/transcript",
        { conversation_id: id, before: target + 1, limit: 1 },
        "chat"
      );
    } catch (_) {
      return false;
    }
    if (!sameSession(half, era)) {
      return false;
    }
    if (body === null || mine !== chat.chosen) {
      return false;
    }
    body.transcript.entries.forEach((entry) => {
      if (entry.position === target) {
        chat.unfound.delete(target);
        applyEntry(entry, chat.referenced);
      }
    });
    // On screen before the next lookup is awaited, so what this one brought — a marker
    // above all (§5:12) — is shown whatever becomes of the next.
    renderTranscript();
  }
  return true;
}

// Answers whether the read failed for the conversation still on screen: `false` where it
// was refused or never answered, `true` otherwise — a read for a conversation the owner
// has since left is not a failure of anything they are looking at.
async function readChatDigest(id, mine) {
  const half = headerHalf();
  if (half === null) {
    return false;
  }
  const era = sessionEra;
  const stateBefore = chat.seen.state;
  const devicesBefore = chat.seen.devices;
  try {
    const body = await relay(half, "/conversation", { conversation_id: id }, "chat");
    if (!sameSession(half, era)) {
      return true;
    }
    if (mine !== chat.chosen) {
      return true;
    }
    if (body === null) {
      return false;
    }
    // Its start, for its name: a conversation opened from a page of the listing this
    // page has not read — restored on a reload — is named from here.
    knowStarts([body.conversation]);
    if (chat.selected === id) {
      el("chat-heading").textContent = chatTitle(id);
    }
    if (settle("state", stateBefore)) {
      chat.state = body.conversation.state;
    }
    if (settle("devices", devicesBefore)) {
      chat.devices = body.conversation.devices;
    }
    renderChatState();
    renderConversationDevices();
    return true;
  } catch (_) {
    if (!sameSession(half, era)) {
      return true;
    }
    if (mine === chat.chosen) {
      fault(GATEWAY_GONE, "chat");
      return false;
    }
    return true;
  }
}

function renderChatState() {
  const slot = el("chat-state");
  // The state's line sits under the transcript, so a line appearing shortens the
  // transcript's box: a reader at the newest message is kept there (#3098).
  const list = el("chat-transcript");
  const atEnd = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  let said = "";
  if (chat.state !== null) {
    said = chat.state.working ? CHAT_WORKING : CHAT_ENDINGS[chat.state.last_ended] || "";
  }
  slot.textContent = said;
  slot.hidden = said === "";
  // Marked as well as said, so the line that says the assistant is working looks it.
  slot.classList.toggle("working", chat.state !== null && chat.state.working === true);
  renderChatStop();
  if (atEnd) {
    list.scrollTop = list.scrollHeight;
  }
}

// The activations the state says are running, in its order and each once; empty
// otherwise — nothing running, or running with no id, which cannot be stopped (ADR-0297
// §5's residual of a failed id factory) and is offered no control. The state names every
// running activation started from the conversation (ADR-0349 §10:3), so this is a list.
function runningActivations() {
  if (chat.state === null || !chat.state.working || !Array.isArray(chat.state.activation_ids)) {
    return [];
  }
  const running = [];
  chat.state.activation_ids.forEach((id) => {
    if (typeof id === "string" && id !== "" && !running.includes(id)) {
      running.push(id);
    }
  });
  return running;
}

// The running activations a press would send a stop for: each one with no stop of this
// page's out for it and none landed on it, so a stop still out for one never holds back
// a stop for another the state has named since.
function stoppableActivations(running) {
  return running.filter((id) => {
    const one = chat.stop === null ? undefined : chat.stop.get(id);
    return one === undefined || (!one.sending && one.answer !== "stopped");
  });
}

// The control and what the stops answered. **Each answer is about one activation**, and
// is kept while the state still names that one: once it ends, the state's own ending says
// how (`CHAT_ENDINGS.stopped` for a stop that landed), and a later activation starts with
// no answer beside it. Once every activation the state names has answered "stopped" the
// control is withdrawn, every stop having landed; while any has no answer, or one that
// wrote nothing, it stays, since the state still says working. It is disabled only while
// every one it would name has a stop out.
function renderChatStop() {
  const running = runningActivations();
  if (chat.stop !== null) {
    Array.from(chat.stop.keys()).forEach((id) => {
      if (!running.includes(id)) {
        chat.stop.delete(id);
      }
    });
  }
  const sent = running.map((id) => (chat.stop === null ? undefined : chat.stop.get(id)));
  const sending = sent.some((one) => one !== undefined && one.sending);
  const landed = sent.every((one) => one !== undefined && one.answer === "stopped");
  el("chat-stop-row").hidden = running.length === 0 || landed;
  el("chat-stop").disabled = stoppableActivations(running).length === 0;
  let said = "";
  if (sending) {
    said = CHAT_STOPPING;
  } else {
    // One sentence per distinct answer, in the state's order: two stops that landed say
    // so once, and one that landed beside one that wrote nothing says both.
    const sentences = [];
    sent.forEach((one) => {
      if (one === undefined) {
        return;
      }
      const sentence = Object.prototype.hasOwnProperty.call(CHAT_STOP_ANSWERS, one.answer)
        ? CHAT_STOP_ANSWERS[one.answer]
        : CHAT_STOP_UNKNOWN;
      if (!sentences.includes(sentence)) {
        sentences.push(sentence);
      }
    });
    said = sentences.join(" ");
  }
  const slot = el("chat-stop-said");
  slot.textContent = said;
  slot.hidden = said === "";
}

// The owner pressing **Stop**: one request for each activation the state names that has
// no stop out and none landed (`stoppableActivations`), each naming that one activation
// and all sent together (ADR-0349 §4:3, ADR-0295 §1:1), and their answers said beside the
// control (ADR-0297 §5). Nothing is decided here — whether each was running, had ended or
// was never known is the hub's answer — and nothing is retried: a refusal is on screen
// where `relay` put it, and the control is offered again.
async function stopActivations() {
  const named = stoppableActivations(runningActivations());
  if (named.length === 0) {
    return;
  }
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  if (chat.stop === null) {
    chat.stop = new Map();
  }
  const sent = chat.stop;
  const mine = named.map((id) => ({ id: id, sending: true, answer: null }));
  mine.forEach((one) => sent.set(one.id, one));
  renderChatStop();
  await Promise.all(mine.map((one) => stopOne(half, sent, one)));
}

// One activation's stop, its answer kept only where nothing has replaced it since: a
// conversation left, or an activation the state no longer names, drops what it answered.
// Each is called before the press yields, so the era it reads is the press's own.
async function stopOne(half, sent, mine) {
  const era = sessionEra;
  try {
    const body = await relay(half, "/activation/stop", { activation_id: mine.id }, "chat");
    if (!sameSession(half, era) || chat.stop !== sent || sent.get(mine.id) !== mine) {
      return;
    }
    if (body === null) {
      sent.delete(mine.id);
    } else {
      mine.sending = false;
      mine.answer = body.stop;
    }
    renderChatStop();
  } catch (_) {
    if (!sameSession(half, era)) {
      return;
    }
    if (chat.stop === sent && sent.get(mine.id) === mine) {
      sent.delete(mine.id);
      renderChatStop();
    }
    fault(GATEWAY_GONE, "chat");
  }
}

// --- the transcript -----------------------------------------------------------

// Where a reply points: a deleted message (§5:8), the message itself, or one this page
// has not read.
function quoted(position) {
  // A marker outranks every copy of the text, wherever it was kept (§5:12).
  if (chat.deleted.has(position)) {
    return "In reply to a message that was deleted.";
  }
  const held = chat.entries.has(position)
    ? chat.entries.get(position)
    : chat.referenced.get(position);
  if (held !== undefined) {
    const text = held.text.length > 120 ? `${held.text.slice(0, 120)}…` : held.text;
    return `In reply to: “${text}”`;
  }
  return `In reply to message ${position}.`;
}

// `toEnd` scrolls to the newest message; otherwise the view stays where the owner is
// unless they were already at the end.
function renderTranscript(toEnd) {
  const list = el("chat-transcript");
  const atEnd = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  clearNode(list);
  // A pending message the conversation has since recorded is shown as the record, or not
  // at all where it has since been deleted — found by its position where a receipt said
  // it, and by this device's message id where the receipt was lost (§4:1), so a send
  // whose answer never came is not shown twice.
  const recorded = new Set();
  chat.entries.forEach((entry) => {
    if (entry.author === "user" && entry.device_id === chat.thisDevice) {
      recorded.add(entry.message_id);
    }
  });
  chat.pending = chat.pending.filter(
    (one) =>
      one.conversation !== chat.selected ||
      !(
        (one.position !== null &&
          (chat.entries.has(one.position) || chat.deleted.has(one.position))) ||
        recorded.has(one.messageId)
      )
  );
  const positions = [...chat.entries.keys()].sort((a, b) => a - b);
  const waiting = chat.pending.filter((one) => one.conversation === chat.selected);
  if (positions.length === 0 && waiting.length === 0) {
    const empty = document.createElement("li");
    empty.className = "hint";
    empty.textContent = "No messages yet.";
    list.appendChild(empty);
  }
  positions.forEach((position) => list.appendChild(renderChatMessage(chat.entries.get(position))));
  waiting.forEach((one) => list.appendChild(renderPending(one)));
  el("chat-older").hidden = chat.oldest === null || chat.oldest <= 1;
  // The reply being written names its message as the transcript now has it: a message
  // deleted meanwhile is named as deleted, and its text is not left on screen (§5:12).
  if (chat.replyTo !== null) {
    setReplyTo(chat.replyTo);
  }
  if (toEnd === true || atEnd) {
    list.scrollTop = list.scrollHeight;
  }
}

function chatButton(parent, label, act) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", act);
  parent.appendChild(button);
  return button;
}

function renderChatMessage(message) {
  const item = document.createElement("li");
  const mine = message.author === "user";
  item.className = mine ? "chat-message from-user" : "chat-message from-assistant";
  let who = mine ? "You" : "Assistant";
  if (mine && message.device_id !== chat.thisDevice) {
    who = `You, on ${message.device_id}`;
  }
  // Who wrote it, when, and the message's own controls, on one line above its text.
  const head = document.createElement("div");
  head.className = "chat-head";
  const meta = document.createElement("p");
  meta.className = "hint chat-meta";
  const author = document.createElement("strong");
  author.textContent = who;
  meta.appendChild(author);
  meta.appendChild(document.createTextNode(" · "));
  const when = document.createElement("time");
  when.dateTime = message.written_at;
  when.textContent = chatTime(message.written_at);
  meta.appendChild(when);
  head.appendChild(meta);
  item.appendChild(head);
  if (message.replies_to !== null) {
    line(item, quoted(message.replies_to), "hint chat-quote");
  }
  line(item, message.text, "chat-text");
  // §6:16: a cut-off message is never read as a complete answer.
  if (message.cut_off) {
    line(item, "This message was cut off before it finished.", "notice");
  }
  // Question messages and their answers are not built (ADR-0293 §11:5), so the options
  // are said and not offered as buttons that could answer nothing.
  if (message.options.length > 0) {
    line(item, `It offered: ${message.options.join(" · ")}`, "hint");
  }
  const acts = document.createElement("p");
  acts.className = "choice chat-acts";
  // A reply is also how the assistant is corrected (§4:5).
  chatButton(acts, "Reply", () => {
    setReplyTo(message.position);
    el("chat-text").focus();
  });
  const conversation = chat.selected;
  chatButton(acts, "Delete", () => {
    void deleteChatMessage(conversation, message.position);
  });
  head.appendChild(acts);
  return item;
}

function renderPending(one) {
  const item = document.createElement("li");
  item.className = "chat-message from-user pending";
  line(item, `You · ${CHAT_SENT_STATES[one.status]}`, one.status === "received" || one.status === "sending" ? "hint chat-meta" : "notice chat-meta");
  if (one.repliesTo !== null) {
    line(item, quoted(one.repliesTo), "hint chat-quote");
  }
  line(item, one.text, "chat-text");
  const acts = document.createElement("p");
  acts.className = "choice chat-acts";
  if (one.status === "unknown") {
    chatButton(acts, "Send again", () => {
      void deliverChat(one);
    });
  }
  // Changing a conversation's devices is the command line's for now; once this device
  // is one of its ends, sending again is the same message (§4:2).
  if (one.status === "not-an-end") {
    if (typeof chat.thisDevice === "string") {
      line(
        item,
        "To write here, add this device to the conversation at the command line: " +
          `assistant conversation-devices ${one.conversation} --add ${chat.thisDevice}`,
        "hint"
      );
    }
    chatButton(acts, "Send again", () => {
      void deliverChat(one);
    });
  }
  if (one.status === "no-such-reply") {
    chatButton(acts, "Send it without the reply", () => {
      one.repliesTo = null;
      void deliverChat(one);
    });
  }
  if (one.status !== "sending" && one.status !== "received") {
    chatButton(acts, "Dismiss", () => {
      chat.pending = chat.pending.filter((held) => held !== one);
      renderTranscript();
    });
  }
  if (acts.firstChild !== null) {
    item.appendChild(acts);
  }
  return item;
}

function setReplyTo(position) {
  chat.replyTo = position;
  const said = el("chat-replying");
  said.textContent = position === null ? "" : quoted(position);
  said.hidden = position === null;
  el("chat-reply-cancel").hidden = position === null;
}

// --- writing ------------------------------------------------------------------

// A message id this device chose, unique per device (§4:1). Kept with the message, so
// sending again is the same message (§4:2).
function newMessageId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  return [...bytes].map((one) => one.toString(16).padStart(2, "0")).join("");
}

function sendChat(event) {
  event.preventDefault();
  const box = el("chat-text");
  const text = box.value;
  if (text.trim() === "" || chat.selected === null) {
    return;
  }
  const one = {
    conversation: chat.selected,
    messageId: newMessageId(),
    text: text,
    repliesTo: chat.replyTo,
    status: "sending",
    position: null,
  };
  chat.pending.push(one);
  box.value = "";
  setReplyTo(null);
  void deliverChat(one);
}

// Write one message, or write it again: the same id, so the conversation records it
// once whichever send it was that arrived (§4:2).
async function deliverChat(one) {
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const era = sessionEra;
  one.status = "sending";
  renderTranscript(true);
  let refusal = null;
  try {
    const body = await relay(
      half,
      "/chat/message/write",
      {
        conversation_id: one.conversation,
        message_id: one.messageId,
        text: one.text,
        replies_to: one.repliesTo,
      },
      "chat",
      undefined,
      (said) => {
        refusal = said;
      }
    );
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null) {
      // A refusal is known not to have recorded the message only where it names its
      // condition and that condition is not the hub having gone mid-request; an answer
      // this page could not read is *not known* (ADR-0177 §7), and keeps the resend.
      const named = refusal !== null && typeof refusal.fault === "string";
      if (!named || UNKNOWN_FAULTS.has(refusal.fault)) {
        one.status = "unknown";
      } else if (refusal.fault === "no-such-conversation") {
        one.status = "gone";
      } else {
        one.status = "refused";
      }
      renderTranscript();
      return;
    }
    const outcome = body.receipt.outcome;
    if (outcome === "recorded" || outcome === "repeated") {
      // *Received* (§4:4): the conversation holds it at this position.
      one.status = "received";
      one.position = body.receipt.position;
    } else if (outcome === "not_an_end") {
      one.status = "not-an-end";
    } else {
      one.status = "no-such-reply";
    }
    renderTranscript();
  } catch (_) {
    if (!sameSession(half, era)) {
      return;
    }
    one.status = "unknown";
    renderTranscript();
  }
}

// --- composing ----------------------------------------------------------------
//
// ADR-0332 §5:5: "The hub chat page sends a composing signal for a conversation while the
// person types into that conversation's composer, no more often than once a second." The
// hub keeps the signal live for `chat_composing_lapse` after it arrives (§5:6), so a
// person who keeps typing keeps it renewed, and one who stops lets it lapse.
//
// **It is not input** (§5:8): it starts nothing, joins nothing, and is never written into
// the transcript, any store or any episode. So nothing of it is kept here either — not in
// `chat.pending`, not in the transcript on screen, and not in browser storage. The values
// below are this tab's memory of its own last send, which the cadence is counted from,
// and they are gone with the tab.
//
// **Nothing the signal answers is said on the page.** It is not something the person
// asked for, so a refusal of it (a device that only reads the conversation, which the hub
// refuses under ADR-0298 §5's Writing row), a lost request or a session that has ended is
// left to the message they send next, whose answer says it in full.

// The least time between two signals, which §5:5 bounds at once a second.
const COMPOSING_EVERY_MILLISECONDS = 1000;
// When the last signal was sent, by this page's monotonic clock.
let composingAt = -Infinity;
// Whether a signal is still out. **One out at a time, and it is never replaced**: the
// next is sent only once it has settled, whichever way. A signal the browser abandoned
// is not one the gateway abandoned — the gateway holds one of its few hub connections
// (ADR-0168 §8) until the hub answers the relay, whatever the browser does — so a page
// that replaced a slow signal with a fresh one would take a further connection for each,
// and the person's own message would meet `hub-connection-ceiling`. A page that waits
// takes one at most. While one is out, the typing goes unsignalled: the hub's start wait
// then ends on its own figures, no later than `chat_composing_cap` (§5:2), and a reply
// that crosses a follow-up does no harm, because the next activation sees it (§5).
let composingOut = false;

async function sendComposing() {
  const half = headerHalf();
  const conversation = chat.selected;
  if (half === null || conversation === null || composingOut) {
    return;
  }
  const now = performance.now();
  if (now - composingAt < COMPOSING_EVERY_MILLISECONDS) {
    return;
  }
  composingAt = now;
  composingOut = true;
  try {
    const response = await fetch("/chat/composing", {
      method: "POST",
      headers: admitted(half, true),
      body: JSON.stringify({ conversation_id: conversation }),
    });
    await response.text();
  } catch (_) {
    // A lost signal is a signal not sent, and the next keystroke past the cadence sends
    // another; the gateway having gone is said by whatever the person does next.
  } finally {
    composingOut = false;
  }
}

// --- deleting and forgetting --------------------------------------------------

async function deleteChatMessage(id, position) {
  if (!window.confirm(CHAT_DELETE_MESSAGE)) {
    return;
  }
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const era = sessionEra;
  try {
    const body = await relay(
      half,
      "/chat/message/delete",
      { conversation_id: id, position: position },
      "chat"
    );
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null || chat.selected !== id) {
      return;
    }
    chat.entries.delete(position);
    chat.deleted.add(position);
    if (chat.replyTo === position) {
      setReplyTo(null);
    }
    renderTranscript();
  } catch (_) {
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "chat");
  }
}

async function deleteChat() {
  const id = chat.selected;
  if (id === null || !window.confirm(CHAT_DELETE_CONVERSATION)) {
    return;
  }
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const era = sessionEra;
  try {
    const body = await relay(half, "/chat/conversation/delete", { conversation_id: id }, "chat");
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null) {
      return;
    }
    if (chat.selected === id) {
      chatGone(
        body.deleted
          ? `${capitalised(chatName(id))} was deleted. Nothing was forgotten.`
          : `${capitalised(chatName(id))} was already gone.`
      );
    }
    void listChat(false);
  } catch (_) {
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "chat");
  }
}

async function forgetChat() {
  const id = chat.selected;
  if (id === null || !window.confirm(CHAT_FORGET)) {
    return;
  }
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const era = sessionEra;
  try {
    const body = await relay(half, "/conversation/forget", { conversation_id: id }, "chat");
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null) {
      return;
    }
    sayChat(
      body.destroyed
        ? `The assistant has forgotten ${chatName(id)}: it no longer recalls it anywhere ` +
            "else. The conversation and its transcript stay; only deleting removes them."
        : `${capitalised(chatName(id))} held nothing in the assistant's memory, so nothing ` +
          "was forgotten."
    );
  } catch (_) {
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "chat");
  }
}

// --- devices -----------------------------------------------------------------
//
// Shown and not changed here: which devices see the chat, "my devices" and the open
// conversation's (ADR-0293 §3). Changing either is the command line's for now —
// `assistant my-devices` and `assistant conversation-devices` — and a later lane's here.

function deviceName(device) {
  return device.device_id === chat.thisDevice
    ? `${device.device_id} (this device)`
    : device.device_id;
}

function renderDevice(list, device) {
  const item = document.createElement("li");
  item.className = "chat-device";
  const known = CHAT_ACCESS.find((one) => one.value === device.access);
  line(item, `${deviceName(device)} — ${known ? known.label.toLowerCase() : device.access}`);
  list.appendChild(item);
}

function renderMyDevices() {
  const list = el("chat-my-devices");
  clearNode(list);
  const said = el("chat-this-device");
  const mine = chat.myDevices.find((one) => one.device_id === chat.thisDevice);
  const held = mine !== undefined;
  if (chat.thisDevice === null) {
    said.textContent =
      "This gateway cannot name this browser's device, so it cannot write a message " +
      "from here.";
  } else if (chat.thisDevice === undefined) {
    said.textContent = "";
  } else if (HOSTED) {
    // Through the sign-in door this browser is the person's one hosted browser device,
    // "the web" rather than a machine (ADR-0327 §10), and adding it is the setup's act
    // rather than a command the person can run — so it is said without either.
    // A member for writing alone is not shown a conversation (ADR-0293 §3:5), so the
    // promise is made only to one that reads (#3211).
    if (!held) {
      said.textContent =
        "This page is not one of your devices yet, so a new conversation is not shown " +
        "here on its own. The person who set up your assistant can add it.";
    } else if (mine.access === "write") {
      said.textContent =
        "This page is one of your devices for writing only, so a new conversation is " +
        "not shown here. The person who set up your assistant can change that.";
    } else {
      said.textContent =
        "This page is one of your devices, so every new conversation is shown here.";
    }
  } else if (held) {
    said.textContent = `This browser is device ${chat.thisDevice}, one of your devices.`;
  } else {
    said.textContent =
      `This browser is device ${chat.thisDevice}, which is not one of your devices. ` +
      "Adding a device says its screen is private, and every conversation started from " +
      `then on is shown on it: assistant my-devices --add ${chat.thisDevice}`;
  }
  // The roles the hub's stream last sent (ADR-0298 §7:9), said beside the device.
  const roles = chat.roles === undefined ? "" : rolesSaid(chat.roles);
  if (roles !== "" && said.textContent !== "") {
    said.textContent += ` ${roles}`;
  }
  if (chat.myDevices.length === 0) {
    const none = document.createElement("li");
    none.className = "hint";
    none.textContent = "None yet, so a new conversation is shown on no device.";
    list.appendChild(none);
  }
  chat.myDevices.forEach((device) => renderDevice(list, device));
}

// **An empty set is not the hub's "no role" refusal, and drops nothing.** The roles the
// stream carries are the roster's (ADR-0298 §7:9): a device's membership of "my devices"
// and of conversations is a role the roster does not record (ADR-0296 §2), so a device
// with no roster role may still read and write the conversations it is a device of. What
// drops everything is the refusal for holding no role (§7:17, `dropOnRefusal`).
function rolesSaid(roles) {
  if (HOSTED) {
    return roles.length === 0
      ? "It is not set up to ask or manage anything from here yet, though the " +
          "conversations shown here still work."
      : "";
  }
  if (roles.length === 0) {
    return (
      "The hub's device roster gives it no role, so it cannot ask or manage from here; " +
      "the conversations it is a device of, it still reads and writes."
    );
  }
  const named = roles.join(" and ");
  return `The hub gives it the ${named} role${roles.length === 1 ? "" : "s"}.`;
}

function renderConversationDevices() {
  const list = el("chat-conversation-devices");
  clearNode(list);
  if (chat.devices === null) {
    return;
  }
  if (chat.devices.length === 0) {
    const none = document.createElement("li");
    none.className = "hint";
    none.textContent = "No device: nothing can write in this conversation until one is added.";
    list.appendChild(none);
  }
  chat.devices.forEach((device) => renderDevice(list, device));
}

// --- the grant surface (ADR-0177 §6, §7; ADR-0139) ---------------------------
//
// Two questions and they are never answered with each other (ADR-0139 §1, §3's
// fourth clause). "What may I grant?" is `/sources`; "what do I currently
// authorise?" is `/grants/standing`; and the history at `/grants/recent` answers
// neither. Each has its own panel, its own heading and its own read, and no panel
// annotates one answer with another.

// Every use a grant may name, in words — the vocabulary a recorded grant is
// rendered in (ADR-0139 §3's third clause). It keeps "ingest": a grant recorded
// with it still names it, and a rendering names every use its grant names
// (ADR-0294 §4). "facet" left (ADR-0318 §6:2): nothing reads a source for it.
//
// The phrases say what the reading is *used for* and never what follows from it
// (ADR-0133 §1): granting "notify" decides nothing about whether you are ever
// contacted, so its phrase is about reading, on the same footing as the others.
const USE_PHRASES = [
  { value: "ingest", label: "Durably remember what it says" },
  { value: "notify", label: "Read it to raise things with you unprompted" },
];

// The uses a **new** grant may name, which is what a choice offers (ADR-0294 §4):
// every phrase above but the one a new grant may no longer name, which leaves
// "notify" alone, in words (ADR-0318 §6:2). Nothing reads a
// source under "ingest" any more, and the hub refuses a new grant naming it, so a
// box for it would offer a use the hub refuses — the surface disagreeing with the
// vocabulary that ADR-0139 §3's second clause forbids, from the other side.
const RETIRED_USES = ["ingest"];
const USES = USE_PHRASES.filter((use) => !RETIRED_USES.includes(use.value));

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
      const known = USE_PHRASES.find((one) => one.value === use);
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
  const era = sessionEra;
  try {
    const body = await relay(half, "/sources", {}, "sources");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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

// The choice of uses, offered as every use a new grant may name (ADR-0294 §4) and
// taken **before** anything is sent (ADR-0139 §4's sixth clause, ADR-0177 §7's
// sixth). No surface revokes in order to ask: a user who hesitates over this form,
// or closes the tab while thinking, has withdrawn nothing.
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
  const era = sessionEra;
  try {
    const body = await relay(half, "/grants/standing", {}, "standing");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
  line(item, `Decided ${localTime(grant.decided_at)}`, "hint");
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
  const era = sessionEra;
  try {
    const body = await relay(half, "/grants/recent", {}, "history");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
  line(item, `Decided ${localTime(record.decided_at)}`, "hint");
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
const readSoFar = { beliefs: 0, notifications: 0 };

// Which run of each listing is current. An offset is only meaningful against the
// question that produced it, so starting a listing again — a band unchecked, the
// button pressed a second time — retires every page still in flight from the last
// one: a stale answer renders nothing and advances nothing.
//
// Without it a response arriving after the restart appends rows the current filter
// did not ask for and moves the offset the *next* page is read at, which skips
// beliefs — and a belief with no rendered row has no `Forget` control, so the failure
// costs the owner a control rather than a little tidiness.
const runs = { beliefs: 0, notifications: 0 };

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
  const era = sessionEra;
  const asked = { limit: PAGE, offset: readSoFar.beliefs };
  if (bands !== null) {
    asked.bands = bands;
  }
  try {
    const body = await relay(half, "/beliefs", asked, "beliefs");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "beliefs");
  }
}

// --- the pending candidates (ADR-0329 §18) -------------------------------------
//
// What `remember` has noted and the observer has not yet processed, shown in the belief
// panel each by its fact and marked pending (§18:1), and nothing more (§18:3): no band,
// no standing and no `Forget`, because a candidate is no belief and `forget` names
// nothing by one. The section stays hidden while there is none, which is what a hub
// whose `remember` still writes memories always answers.
//
// Read when the panel is opened, and not from the band checkboxes: a band says nothing
// about a candidate, so a filter changed would only read the same answer again.
const candidateRuns = { current: 0 };

// The panel's own entry: the listing from its first page, then the pending candidates.
//
// **The candidates are read only for the session that opened the panel** (adversarial
// review, round 1, `major`): a listing whose session ended while it was in flight, and
// another began, retires its own answer, and this must not then start a read under the
// new session, whose fault would put the panel on screen though nobody opened it there.
async function openBeliefs() {
  const half = headerHalf();
  const era = sessionEra;
  await readPinning();
  if (half !== null && !sameSession(half, era)) {
    return;
  }
  await listBeliefs();
  if (half === null || !sameSession(half, era)) {
    return;
  }
  await listCandidates();
}

// One read of the pending candidates, rendered whole in place of the last.
//
// The run check retires an answer a later open has overtaken, as the listing's does,
// and the session check one that belongs to a session this page no longer holds.
async function listCandidates() {
  candidateRuns.current += 1;
  const run = candidateRuns.current;
  const half = headerHalf();
  if (half === null) {
    return;
  }
  const era = sessionEra;
  try {
    const body = await relay(half, "/candidates/pending", {}, "beliefs");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null || run !== candidateRuns.current) {
      return;
    }
    const held = Array.isArray(body.candidates) ? body.candidates : [];
    const list = el("pending-list");
    clearNode(list);
    held.forEach((one) => renderCandidate(list, one));
    el("pending-candidates").hidden = held.length === 0;
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "beliefs");
  }
}

// One candidate: the mark first, so it is never read as a belief, then its fact.
function renderCandidate(list, candidate) {
  const item = document.createElement("div");
  line(item, "Pending: not remembered yet", "hint");
  line(item, candidate.fact, "reply");
  list.appendChild(item);
}

// The band's own name, in the words a person reads it in. Every memory carries one
// and it is never left to be implied by position (ADR-0073 §4); the panel's three
// filter checkboxes are labelled with the same words.
function bandWords(band) {
  if (band === "asserted") {
    return "You told me";
  }
  if (band === "derived") {
    return "I worked it out";
  }
  if (band === "attested") {
    return "From a source";
  }
  return band;
}

// A memory's standing in plain words (ADR-0328 §6:1, §15:4). The sibling CLI says the
// same four (`_STANDING_WORDS`).
function standingWords(standing) {
  if (standing === "confirmed") {
    return "you confirmed this wording";
  }
  if (standing === "said") {
    return "you said it";
  }
  if (standing === "source") {
    return "from a source";
  }
  if (standing === "inference") {
    return "my inference";
  }
  return standing;
}

// Where a support came from, in plain words (ADR-0328 §4's origin table), as the CLI
// says it (`_ORIGIN_WORDS`).
const ORIGIN_WORDS = {
  user_message: "your message",
  outside_input: "a report from outside",
  confirmation: "your yes to my question",
  evidence: "outside content I read",
  assistant_message: "my own message",
  assistant_message_over_outside: "my own message, over outside content",
  remembered: "something I chose to remember",
  remembered_over_outside: "something I chose to remember, over outside content",
  legacy: "a record kept before memories had supports",
  legacy_outside: "a record kept before memories had supports, resting on outside content",
  observer_inference: "my inference from the other supports",
  pinned: "your pin",
};

// That some of its warrant came from outside, or nothing (ADR-0189 §4, ADR-0328 §12).
//
// Read off the projection's own `rests_on_outside_content`, never recomputed here
// (ADR-0189 §2). Silent on false rather than negative: a false is *nothing outside is
// recorded in this warrant*, never *nothing outside influenced it* (ADR-0328 §7:7). It
// says nothing about the memory's own wording, which is this system's sentence.
function outsideWarrant(belief) {
  if (!belief.rests_on_outside_content) {
    return "";
  }
  return (
    " Some of what it rests on came from outside rather than from you — the wording " +
    "is still my own sentence, but its warrant is not entirely mine."
  );
}

// How the person confirmed a memory's wording (ADR-0328 §6:1, ADR-0338 §4:3-§4:4): by a
// yes to a question, by a pin, or both (#3333). Read off the counted supports backing it
// where the view carries them; the listing's summary carries none, and there the
// sentence names neither, rather than one that may not be how it was confirmed. The CLI
// says the same (`_confirmed_why`).
function confirmedHow(belief) {
  if (!Array.isArray(belief.supports)) {
    return "You confirmed this wording.";
  }
  const backing = belief.supports.filter((one) => one.counts && one.direction === "for");
  const asked = backing.some((one) => one.origin === "confirmation");
  const pinned = backing.some((one) => one.origin === "pinned");
  if (asked && pinned) {
    return "You confirmed this wording when I asked you, and by pinning it.";
  }
  if (pinned) {
    return "You confirmed this wording by pinning it.";
  }
  if (asked) {
    return "You confirmed this wording when I asked you.";
  }
  return "You confirmed this wording.";
}

// Whether a memory is marked as the assistant's own statement (ADR-0345 §8:1).
function saidByMe(belief) {
  return Array.isArray(belief.marks) && belief.marks.includes("assistant_statement");
}

// Whose belief a support records, in plain words (ADR-0345 §12), as the CLI says it
// (`_holder_words`).
function holderWords(holder) {
  if (holder.kind === "person") {
    return holder.owner ? "you" : `another person (${holder.identifier})`;
  }
  if (holder.kind === "outside_source") {
    return holder.claimed
      ? `a forward claimed to come from ${holder.identifier}`
      : `the source ${holder.identifier}`;
  }
  if (holder.kind === "assistant_statement") {
    return "my own words";
  }
  return "an unknown source";
}

// Why a memory marked as my statement is held (ADR-0345 §12:4): what I said, where and
// when, and who kept it, never as your word or a source's, whatever its standing.
function saidWhy(belief) {
  const when = (belief.statements || [])
    .map((one) => (one.when === null ? "unknown" : localTime(one.when)))
    .join(", ");
  const kept = (belief.holders || []).filter((one) => one.kind === "person");
  const keepers = kept.map(holderWords).join(", ");
  const keeper =
    kept.length > 0
      ? ` ${keepers.charAt(0).toUpperCase()}${keepers.slice(1)} kept it.`
      : " Nobody but me said it.";
  return `I said this, in my message of ${when || "unknown"}; it is a record of what I said.${keeper}`;
}

// Why a memory is held: its standing, said in plain words (ADR-0328 §15:4). An
// inference says its evidence summary, and whether any of it came from outside. A memory
// marked as my statement is said to be what I said (ADR-0345 §12:4).
function whyHeld(belief) {
  if (saidByMe(belief)) {
    return saidWhy(belief);
  }
  if (belief.standing === "confirmed") {
    return confirmedHow(belief);
  }
  if (belief.standing === "said") {
    return "You told me, and your own word is the whole of it.";
  }
  if (belief.standing === "source") {
    // Every origin ranked at source (ADR-0328 §4): an outside report, an evidence item
    // read from outside content, or a message of my own. What it rests on says which.
    return (
      "It came from a source rather than from you — neither your word nor my inference. " +
      "What it rests on says which source."
    );
  }
  const evidence = belief.evidence;
  const against = evidence.against > 0 ? `, ${evidence.against} against it` : "";
  // A legacy support points at no exchange (ADR-0328 §16:4), so a count of none is left
  // unsaid rather than rendered as "across 0 exchange(s)", as the CLI does.
  const across = evidence.episodes > 0 ? ` across ${evidence.episodes} exchange(s)` : "";
  // §7:2's latest `when`, which can be a newer piece against it than As of shows.
  const latest =
    evidence.latest === null
      ? " None of it is dated."
      : ` The latest piece is from ${localTime(evidence.latest)}.`;
  return (
    `I worked it out from ${evidence.supporting} piece(s) of support${across}${against}.` +
    latest +
    outsideWarrant(belief)
  );
}

// The lines ADR-0328 §15:4 requires a surface showing a memory to show, beyond its
// standing and wording: its age, its reading certainty where that is not `sure`,
// every let-down, the legacy mark, and the two marks §7:10 and §15:7 add. One list,
// so the row and the forget confirmation cannot show different facts.
function beliefLines(belief) {
  const lines = [
    `Why: ${whyHeld(belief)}`,
    `Learned: ${belief.learned === null ? "unknown" : localTime(belief.learned)}`,
    `As of: ${belief.as_of === null ? "unknown" : localTime(belief.as_of)}`,
  ];
  const holders = belief.holders || [];
  if (holders.length > 0 && !(holders.length === 1 && holders[0].owner)) {
    // ADR-0345 §12:1: whose belief it is, wherever that is not yours alone.
    lines.push(`Held by: ${holders.map(holderWords).join(", ")}`);
  }
  if (belief.attestation !== null) {
    // ADR-0189 §1, §4: which source its standing rests on, and when that source said so
    // on its own clock (ADR-0328 §2:6), as the CLI says it.
    lines.push(
      `Reported by: ${belief.attestation.reported_by}, as of ` +
        `${localTime(belief.attestation.reported_at)} on its own clock`,
    );
  }
  if (belief.reading_certainty !== "sure") {
    const reading = belief.reading_certainty === null ? "not judged" : belief.reading_certainty;
    lines.push(`How sure the reading was: ${reading}`);
  }
  const track = belief.track_record;
  if (track.let_down > 0) {
    lines.push(`Let you down ${track.let_down} time(s) of the ${track.relied_on} I relied on it.`);
  }
  if (belief.legacy) {
    lines.push(
      "Legacy: kept before memories had supports; what it rested on then is shown as " +
        "it was recorded."
    );
  }
  if (belief.unbacked) {
    lines.push("Nothing that counts backs this wording now.");
  }
  if (belief.supports_gone) {
    lines.push(
      "Everything it rested on is gone. I still hold it — I have not unlearnt it " +
        "because the evidence went."
    );
  }
  if (belief.valid_until !== null) {
    lines.push(`Believed until: ${localTime(belief.valid_until)}`);
  }
  lines.push(`id: ${belief.id}`);
  return lines;
}

// A memory's heading: its band's words and its standing (ADR-0073 §4, ADR-0328 §15:4).
// The attested band holds the one standing "from a source" (§6:4), so where the two
// say the same words they are said once.
function beliefHeading(belief) {
  // ADR-0345 §12:4: a memory marked as my statement is said to be what I said, and its
  // band's words ("You told me", "From a source") are not said of it at all.
  if (saidByMe(belief)) {
    return "What I said";
  }
  const band = bandWords(belief.band);
  const standing = standingWords(belief.standing);
  return band.toLowerCase() === standing.toLowerCase() ? band : `${band} · ${standing}`;
}

// One support of the single view, its part resolved or shown as gone (ADR-0328 §15:2,
// §15:7): never a bare id, never shown as evidence once it is gone.
function supportLine(support) {
  const origin = ORIGIN_WORDS[support.origin] || support.origin;
  // ADR-0189 §4: the source's own reporting instant, said as its clock, beside the
  // `when` this system read the part at.
  const source = support.source_details;
  const named =
    source === null
      ? ""
      : ` · ${source.reported_by}, which said so as of ` +
        `${localTime(source.reported_at)} on its own clock`;
  const when = support.when === null ? "" : ` · ${localTime(support.when)}`;
  const against = support.direction === "against" ? " · against it" : "";
  const stopped = support.counts ? "" : " · no longer counted";
  const said = support.content === null ? "what it pointed at is gone" : support.content;
  return `- ${origin}${named}${when}${against}${stopped}: ${said}`;
}

// One memory on the listing, carrying everything ADR-0328 §15:4 requires.
function renderBeliefFields(item, belief) {
  line(item, beliefHeading(belief), "hint");
  line(item, belief.content, "reply");
  beliefLines(belief).forEach((text) => line(item, text, "hint"));
}

function renderBelief(list, belief) {
  const item = document.createElement("div");
  item.className = "belief-row";
  renderBeliefFields(item, belief);
  offerPinning(item, belief);
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
      "This came from a source, not from you. Forgetting it destroys my copy but not the " +
      "source, so I may come across it again."
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
  const era = sessionEra;
  try {
    const held = await relay(half, "/belief", { record_id: id }, "beliefs");
    // Not this session's answer (#2404). **The confirmation is the display here**: this
    // read exists only to put the record in front of the owner before it is destroyed,
    // and a `window.confirm` carrying a belief's content, a conversation's turn count or
    // a notification's summary is that content on screen over a form asking for a
    // session. Nothing has been destroyed at this point, so there is nothing this owes
    // an account of. Adversarial review, round 2, `major`.
    if (!sameSession(half, era)) {
      return;
    }
    if (held === null) {
      return;
    }
    const belief = held.belief;
    // Every field ADR-0328 §15:4 requires, and every support, from the read just
    // taken. A confirmation that showed the listing's fields but dropped one of them
    // would be showing *less* than the screen the user came from, which is the
    // opposite of what a ceremony is for.
    const supports = belief.supports.map(supportLine).join("\n");
    const asked = window.confirm(
      `About to forget this belief.\n\n${beliefHeading(belief)}\n${belief.content}\n\n` +
        `${beliefLines(belief).join("\n")}\n\nRests on:\n${supports}\n\n` +
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
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "beliefs");
  }
}

// --- the approvals panel (ADR-0361 §4:6-§4:9) ------------------------------------
//
// One read of the person's requests fills the panel: those waiting for an answer, the
// oldest first, each with Approve and Deny, and those answered or expired most recently.
// Every request's text is its card's own, rendered by the hub through the one renderer
// every surface shows a request by (§2:11), so this page words no request itself and
// cannot show one differently from the card in the line's chat. It is shown whole,
// which is where a request too long for one Telegram message is answered (§4:4).
//
// **A tap is a command** (§4:7), sent once and never retried: what it came to is the
// hub's to say, and the panel is read again after it. The first tap to land, here or on
// the card, wins (§4:9), and a later one is said with where the request now stands.
//
// **Carried out only from a device admitted to the hub** (§4:8), which is the hub's
// route table's rule and not this page's: a device without the commands role is refused
// before anything changes, and that refusal reaches the panel as every other does.

// Where a request stands, as its card says it (§2:11, §4:5), for a tap answered with the
// request's state.
const APPROVAL_STATE_WORDS = {
  pending: "Waiting for your answer.",
  approved: "Approved: not used yet.",
  used: "Approved and used.",
  not_used: "Approved, not used.",
  denied: "Denied.",
  expired: "Expired: it was not answered in time.",
};

// Where a tap came from, by the hub's name for who answered (§4:9).
const APPROVAL_GIVER_WORDS = {
  user_tap_on_hub_panel: "on this page",
  user_tap_on_telegram_card: "on its card in Telegram",
};

// What a tap came to, in words.
function approvalTapWords(choice, tap) {
  if (tap.answer === "answered") {
    return choice === "approve"
      ? "Approved. I may now do exactly what it shows, once."
      : "Denied. I will not do it.";
  }
  if (tap.answer === "expired") {
    return "That request expired before your answer arrived, so nothing changed.";
  }
  if (tap.answer === "unknown") {
    return "That request is not one waiting on you here, so nothing changed.";
  }
  const stands = APPROVAL_STATE_WORDS[tap.entry.state] || tap.entry.state;
  return `That was already answered, so nothing changed. It stands: ${stands}`;
}

// When a request was asked, or when and where it was answered.
function approvalWhen(entry) {
  if (entry.answered_by !== null) {
    const where = APPROVAL_GIVER_WORDS[entry.answered_by] || "";
    return `Answered ${where} · ${localTime(entry.answered_at)}`;
  }
  return `Asked ${localTime(entry.written_at)}`;
}

// Which read of the panel is current: an answer to a read the panel has since started
// again — opened from the menu, or read after a tap — renders nothing.
const approvalsRuns = { current: 0 };

// The panel's own entry, and the read every tap ends with. `kept` is whether the line
// saying what the last tap did stays: it does after a tap, and is cleared when the panel
// is opened from the menu.
async function openApprovals(kept) {
  if (kept !== true) {
    el("approvals-outcome").textContent = "";
  }
  approvalsRuns.current += 1;
  const run = approvalsRuns.current;
  fault(null, "approvals");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const era = sessionEra;
  try {
    const body = await relay(half, "/approvals", { limit: PAGE }, "approvals");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null || run !== approvalsRuns.current) {
      return;
    }
    renderApprovals(body.approvals);
    show("approvals", true);
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "approvals");
  }
}

// Both lists from one answer.
function renderApprovals(panel) {
  const pending = el("approvals-pending");
  const recent = el("approvals-recent");
  clearNode(pending);
  clearNode(recent);
  if (panel.pending.length === 0) {
    line(pending, "Nothing is waiting for your answer.", "hint");
  }
  panel.pending.forEach((one) => renderApproval(pending, one, true));
  // More wait than one read holds — past its count, or past the size one answer may be
  // — so the oldest are shown, and the rest follow as these are answered.
  const more = panel.pending_total - panel.pending.length;
  if (more > 0) {
    const waits = more === 1 ? "1 more request waits" : `${more} more requests wait`;
    line(pending, `${waits} after these. Answer these to see the rest.`, "hint");
  }
  if (panel.recent.length === 0) {
    line(recent, "Nothing yet.", "hint");
  }
  panel.recent.forEach((one) => renderApproval(recent, one, false));
}

// What a request too long for any one answer of the hub's to carry says: its card is
// shown by its start, so the state its card ends with is said here instead; and a yes
// is to the exact call shown, so a pending one offers Deny alone.
const APPROVAL_CUT = "This request is too long to show here whole, so only its start is shown.";
const APPROVAL_CUT_PENDING =
  "It cannot be approved here, since it cannot be shown whole. Deny it if you do not " +
  "want it done.";

// One request: its card's text, when, and on a pending one its buttons — Deny alone on
// one that could not be shown whole.
function renderApproval(list, entry, open) {
  const item = document.createElement("div");
  item.className = "approval-row";
  line(item, entry.text, "reply");
  if (entry.whole === false) {
    line(item, APPROVAL_STATE_WORDS[entry.state] || entry.state, "reply");
    line(item, APPROVAL_CUT, "hint");
    if (open) {
      line(item, APPROVAL_CUT_PENDING, "hint");
    }
  }
  line(item, approvalWhen(entry), "hint");
  if (open) {
    const made = [];
    if (entry.whole !== false) {
      made.push(control("Approve", () => tapApproval(entry.request_id, "approve", made)));
    }
    made.push(control("Deny", () => tapApproval(entry.request_id, "deny", made)));
    controls(item, made);
  }
  list.appendChild(item);
}

// One tap, said on the outcome line, then the panel read again. The row's buttons are
// held while it is out, so a second press is not a second tap; a tap that did not land
// is said, and the person may tap again, which the hub answers with the request's state.
async function tapApproval(requestId, choice, buttons) {
  fault(null, "approvals");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const era = sessionEra;
  const hold = (held) => {
    buttons.forEach((one) => {
      one.disabled = held;
    });
  };
  hold(true);
  try {
    const asked = { request_id: requestId, choice: choice };
    const body = await relay(half, "/approval/tap", asked, "approvals");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null) {
      hold(false);
      return;
    }
    el("approvals-outcome").textContent = approvalTapWords(choice, body.tap);
    await openApprovals(true);
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    hold(false);
    fault(GATEWAY_GONE, "approvals");
  }
}

// --- the person model: the About you panel and pinning (ADR-0338 §8:2-§8:3) -------
//
// One read of the person's model fills the panel, every list of it a page beside its
// total (§8:1), and each list's "Show more" reads that list alone, from where it
// stopped. Every value is the hub's: the slot's order and fill, what it left out and
// why, which pins are no longer current, and every wording shown (§4:8, §6). The page
// computes none of them, so it and the command line cannot show two models of one
// person.
//
// **Shown only to the person and the owner** (§8:3), which is the hub's route table's
// rule and not this page's: a device without the commands role is refused the read
// before dispatch, and that refusal reaches the panel as every other does.
//
// **A hub that keeps no person model answers `off`**, and the panel says it is not
// switched on yet. It is a state the hub is in, not a fault, so it is never written in
// the panel's fault slot (`PersonModelOffError`, ADR-0338 §11:2).

// The one person this hub holds (ADR-0338 §2:1), by the id the hub gives them. The page
// names the person whose model it shows, as every caller of the surface does, and the
// gateway supplies no person of its own. `test_bundle.py` pins it to `core`'s constant.
const OWNER_PERSON_ID = "person:owner";

// What the panel says on a hub whose person model is off, and what the belief panel
// says about pinning there. The CLI says the same (`person_inspection.OFF`).
const PERSON_MODEL_OFF =
  "The person model is not switched on on this hub yet, so there is nothing here to " +
  "show or change.";
const PINNING_OFF = "Pinning is not switched on on this hub yet.";
const PINNING_SAYS =
  "Pinning a memory keeps it in mind in every conversation, and confirms its wording " +
  "as yours.";

// The five fields, in ADR-0338 §3's order: what the panel calls each, and what an empty
// one means. An empty field is shown as not set and never as a default presented as the
// person's own (§3:9); where emptiness has a meaning the table gives it, that is said.
// The CLI says the same (`person_inspection.FIELD_WORDS`, `UNSET_WORDS`).
const PROFILE_FIELDS = [
  { field: "name", label: "Your name", unset: "Not set." },
  { field: "address", label: "What I call you", unset: "Not set." },
  // The name an empty one means is the page's own, which is written once, in the
  // document's title (#3113), and is `core`'s `DEFAULT_ASSISTANT_NAME`.
  {
    field: "assistant_name",
    label: "What you call me",
    unset: `Not set: I go by ${document.title}.`,
  },
  {
    field: "time_zone",
    label: "Your time zone",
    unset: "Not set: I use the hub's own time zone.",
  },
  { field: "language", label: "The language I write to you in", unset: "Not set." },
];

// How a change to a field was made (ADR-0338 §3:5), as the CLI says it.
const CHANGE_HOW_WORDS = {
  panel: "by you, on the panel or the command line",
  approval: "by your yes to my question",
  suggestion: "by accepting my suggestion",
  seed: "by the hub, when it was first set up",
};

// Why the slot left a memory out (ADR-0338 §6:2, §6:4), as the CLI says it.
const LEFT_OUT_WORDS = {
  budget: "Left out: there is no room left for it in what I keep in mind.",
  outside_content:
    "Left out: it rests on outside content, which I keep in mind only once you have " +
    "confirmed its wording.",
};

// Why a write was refused, by the refusal's own name: the store's (`PersonModelRefusal`)
// and the two the engine gives before any write (`PersonModelEditRefusal`, §4:2, §6:3).
// Each is the whole sentence, so a refusal is shown in words and never as a code. The
// CLI says the same (`person_inspection.REFUSAL_WORDS`).
const EDIT_REFUSALS = {
  unknown_person: "I hold no profile for you, so nothing was changed.",
  invalid_value: "That value was not saved.",
  invalid_act: "That change cannot be made this way, so nothing was changed.",
  unknown_record: "That is no longer there, so nothing was changed.",
  already_decided: "That suggestion was already accepted or dismissed.",
  not_current: "That memory is no longer current, so it was not pinned.",
  over_budget:
    "Pinning it would take what I keep in mind over its budget, so it was not pinned. " +
    "Unpin something first.",
};

// What each act did, when it wrote and when it changed nothing. The CLI says the same
// (`person_inspection.DONE_WORDS`).
const EDIT_DONE = {
  set: { written: "Saved.", unchanged: "That is what it already was, so nothing changed." },
  clear: { written: "Cleared.", unchanged: "It was not set, so nothing changed." },
  pin: {
    written:
      "Pinned. I keep it in mind in every conversation, and your pin confirms this " +
      "wording as yours.",
    unchanged: "It was already pinned.",
  },
  unpin: {
    written: "Unpinned. The memory itself is kept.",
    unchanged: "No pin showed that memory, so nothing changed.",
  },
  unmark: {
    written: "Removed. I will not mark it again; the memory itself is kept.",
    unchanged: "That was already removed.",
  },
  accept: { written: "Accepted.", unchanged: "It was already pinned." },
  dismiss: { written: "Dismissed. I will not suggest it again.", unchanged: "Dismissed." },
};

// What a panel's write did, in words (ADR-0338 §8:7's spirit on the panel): the refusal
// before any write, the store's refusal with its reason, or what the act did.
function editWords(act, edit) {
  if (edit.refused !== null) {
    return EDIT_REFUSALS[edit.refused] || edit.refused;
  }
  const write = edit.write;
  if (write.kind === "refused") {
    const said = EDIT_REFUSALS[write.refusal] || write.refusal;
    return write.reason === null ? said : `${said} The rule is: ${write.reason}.`;
  }
  const done = EDIT_DONE[act];
  return write.kind === "unchanged" ? done.unchanged : done.written;
}

// A field's label, by its name.
function fieldLabel(field) {
  const known = PROFILE_FIELDS.find((one) => one.field === field);
  return known === undefined ? field : known.label;
}

// A value as a sentence shows it: quoted, or "not set".
function quotedValue(value) {
  return value === null ? "not set" : `“${value}”`;
}

// One control, built rather than written into the document.
function control(text, act) {
  const made = document.createElement("button");
  made.type = "button";
  made.textContent = text;
  made.addEventListener("click", act);
  return made;
}

// A row's controls, on one line that wraps.
function controls(parent, made) {
  const row = document.createElement("p");
  row.className = "choice";
  made.forEach((one) => row.appendChild(one));
  parent.appendChild(row);
}

function aboutRow(list) {
  const item = document.createElement("div");
  item.className = "about-row";
  list.appendChild(item);
  return item;
}

// Which read of the panel is current. A list's "Show more" reads against the model the
// panel last rendered, and an answer to a read the panel has since started again —
// opened from the menu, or re-read after an edit — renders nothing and advances nothing.
const aboutRuns = { current: 0 };

// How far each list has been read in the current run, and the change log.
const aboutRead = {
  kept: 0,
  left_out: 0,
  no_longer_current: 0,
  style_marks: 0,
  suggestions: 0,
  changes: 0,
};

// The five lists: where each renders, its total's member, how one entry renders, what
// an empty one says, and the part of the panel hidden while it is empty.
const ABOUT_LISTS = {
  kept: {
    node: "kept-list",
    total: "kept_total",
    render: renderKept,
    empty: "Nothing yet.",
  },
  left_out: {
    node: "left-out-list",
    total: "left_out_total",
    render: renderLeftOut,
    part: "left-out",
  },
  no_longer_current: {
    node: "no-longer-current-list",
    total: "no_longer_current_total",
    render: renderStalePin,
    part: "no-longer-current",
  },
  style_marks: {
    node: "style-list",
    total: "style_marks_total",
    render: renderStyleMark,
    empty: "Nothing yet.",
  },
  suggestions: {
    node: "suggestion-list",
    total: "suggestions_total",
    render: renderSuggestion,
    empty: "None.",
  },
};

// The panel's own entry, and the read every edit ends with. `kept` is whether the line
// saying what the last edit did stays: it does after an edit, and is cleared when the
// panel is opened from the menu.
async function openAbout(kept) {
  if (kept !== true) {
    el("about-outcome").textContent = "";
  }
  aboutRuns.current += 1;
  const run = aboutRuns.current;
  fault(null, "about");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const era = sessionEra;
  try {
    const asked = { person_id: OWNER_PERSON_ID, limit: PAGE, offset: 0 };
    const body = await relay(half, "/person", asked, "about");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null || run !== aboutRuns.current) {
      return;
    }
    const model = renderAbout(body);
    show("about", true);
    if (model !== null) {
      await readChanges(false, run);
    }
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "about");
  }
}

// The whole panel from one answer, or the state that stands in for it. Returns the
// model, or `null` where there is none to show.
function renderAbout(body) {
  const state = el("about-state");
  if (body.off === true) {
    state.textContent = PERSON_MODEL_OFF;
    el("about-body").hidden = true;
    return null;
  }
  const model = body.person_model;
  if (model === null) {
    state.textContent = "I hold no profile for you.";
    el("about-body").hidden = true;
    return null;
  }
  state.textContent = "";
  el("about-body").hidden = false;
  renderProfile(model.profile);
  el("kept-fill").textContent =
    `Using ${model.kept_chars} of the ${model.budget_chars} characters I keep in mind.`;
  Object.keys(ABOUT_LISTS).forEach((name) => renderAboutList(name, model, false));
  return model;
}

// One list's page, from its first entry or appended to what is on screen.
function renderAboutList(name, model, more) {
  const spec = ABOUT_LISTS[name];
  const list = el(spec.node);
  if (!more) {
    clearNode(list);
    aboutRead[name] = 0;
  }
  const entries = model[name];
  const total = model[spec.total];
  entries.forEach((one) => spec.render(list, one));
  aboutRead[name] += entries.length;
  if (!more && total === 0 && spec.empty !== undefined) {
    line(list, spec.empty, "hint");
  }
  if (spec.part !== undefined) {
    el(spec.part).hidden = total === 0;
  }
  // A total says how many there are, so a list stopped short offers the rest: an entry
  // past a page is one whose control is otherwise unreachable.
  if (aboutRead[name] < total) {
    const run = aboutRuns.current;
    const next = control("Show more", () => {
      list.removeChild(next);
      void readAboutList(name, run);
    });
    list.appendChild(next);
  }
}

// The next page of one list, read alone (ADR-0338 §8:1's `lists`).
async function readAboutList(name, run) {
  if (run !== aboutRuns.current) {
    return;
  }
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const era = sessionEra;
  try {
    const asked = {
      person_id: OWNER_PERSON_ID,
      lists: [name],
      limit: PAGE,
      offset: aboutRead[name],
    };
    const body = await relay(half, "/person", asked, "about");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null || run !== aboutRuns.current) {
      return;
    }
    if (body.off === true || body.person_model === null) {
      renderAbout(body);
      return;
    }
    renderAboutList(name, body.person_model, true);
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "about");
  }
}

// Per field: how many times the person has typed in its box, and which boxes hold text
// they typed and that has not landed. Kept apart from the boxes, which every read of the
// panel builds again, so both survive a rebuild.
const fieldTyping = { revision: {}, draft: new Set() };

// The five fields, each its own form: a Save writes that field and no other.
//
// **A box the person has typed in, and whose text has not landed, keeps what they typed**
// (adversarial review, rounds 1 to 4): every write reads the panel again, which builds
// every form again, and a draft — in another field, refused, never arrived, or typed while
// a write was in flight — would otherwise be lost though it was never stored. Whether
// typing happened is counted, never inferred from the text's value.
function renderProfile(profile) {
  const drafts = {};
  fieldTyping.draft.forEach((field) => {
    const box = el(`field-${field}`);
    if (box !== null) {
      drafts[field] = box.value;
    }
  });
  const fields = el("profile-fields");
  // **The box the person is in when the forms are built again keeps the keyboard, and
  // its caret** (adversarial review, rounds 9 and 10): the box is replaced, by id, at the
  // instant it is rebuilt, so the focus goes neither to the top of the page, losing what
  // is typed meanwhile, nor back to a box saved earlier, while another is being typed in.
  const active = document.activeElement;
  const kept =
    active !== null && active.id !== "" && fields.contains(active)
      ? {
          id: active.id,
          start: active.selectionStart,
          end: active.selectionEnd,
          direction: active.selectionDirection,
        }
      : null;
  clearNode(fields);
  PROFILE_FIELDS.forEach((spec) =>
    renderField(fields, spec, profile[spec.field], drafts[spec.field])
  );
  const again = kept === null ? null : el(kept.id);
  if (again !== null) {
    again.focus();
    if (typeof kept.start === "number" && typeof kept.end === "number") {
      again.setSelectionRange(kept.start, kept.end, kept.direction || "none");
    }
  }
}

// One field's form: its box holds the draft where there is one, and otherwise the value
// the hub holds.
//
// **A value with a line break round-trips unchanged** (adversarial review, round 7):
// ADR-0338 §3 bounds a field only by its length, so a line break set from the command
// line is a valid value, and an `<input type=text>` strips line breaks from its value. A
// box whose text holds one is therefore a `<textarea>`, which shows it, and a Save from a
// box not typed in since it was built sends the value held, verbatim — the box's value
// is the browser's rendering of it, and a `<textarea>` reads a CR back as a LF.
function renderField(fields, spec, value, draft) {
  const form = document.createElement("form");
  form.className = "profile-field";
  const id = `field-${spec.field}`;
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = spec.label;
  form.appendChild(label);
  line(form, value === null ? spec.unset : `Now: ${value}`, "hint");
  const shown = draft !== undefined ? draft : value === null ? "" : value;
  const lines = shown.split(/\r\n|\r|\n/).length;
  const input = document.createElement(lines > 1 ? "textarea" : "input");
  input.id = id;
  input.name = id;
  if (lines > 1) {
    input.rows = lines;
  } else {
    input.type = "text";
  }
  input.autocomplete = "off";
  input.value = shown;
  // Typed in since it was built: a restored draft is typed text too.
  let typed = draft !== undefined;
  input.addEventListener("input", () => {
    typed = true;
    fieldTyping.revision[spec.field] = (fieldTyping.revision[spec.field] || 0) + 1;
    fieldTyping.draft.add(spec.field);
  });
  form.appendChild(input);
  const save = document.createElement("button");
  save.type = "submit";
  save.textContent = "Save";
  const made = [save];
  // Clearing is its own act, offered where there is something to clear: an empty box
  // saved is a value the store refuses, never a clear by another name.
  if (value !== null) {
    made.push(control("Clear", () => setField(spec.field, null)));
  }
  controls(form, made);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void setField(spec.field, typed || value === null ? input.value : value);
  });
  fields.appendChild(form);
}

// One memory the slot shows (§6:2): what keeps it there, its wording, and, for a pin,
// its unpin.
function renderKept(list, kept) {
  const item = aboutRow(list);
  line(item, kept.pinned ? "Pinned" : "How you like me to speak", "hint");
  line(item, kept.content, "reply");
  if (kept.pinned) {
    controls(item, [control("Unpin", () => unpinFromAbout(kept.memory_id))]);
  }
}

// One memory the slot left out, and why (§6:4).
function renderLeftOut(list, left) {
  const item = aboutRow(list);
  line(item, left.pinned ? "Pinned" : "How you like me to speak", "hint");
  line(item, left.content, "reply");
  line(item, LEFT_OUT_WORDS[left.reason] || left.reason, "hint");
  if (left.pinned) {
    controls(item, [control("Unpin", () => unpinFromAbout(left.memory_id))]);
  }
}

// A pin no longer current (§4:8), and what the person can do about it: unpin it, named
// by the memory it was made on.
function renderStalePin(list, stale) {
  const item = aboutRow(list);
  line(item, `Pinned ${localTime(stale.pinned_at)}, and no longer current`, "hint");
  line(item, stale.content, "reply");
  if (stale.rests_on_outside_content) {
    line(item, "It rested on outside content rather than on what you told me.", "hint");
  }
  controls(item, [control("Unpin", () => unpinFromAbout(stale.memory_id))]);
}

// A style memory (§5:3), with its remove control.
function renderStyleMark(list, mark) {
  const item = aboutRow(list);
  line(item, mark.content, "reply");
  if (mark.shows === null) {
    line(item, "No longer current, so I keep it in mind no more.", "hint");
  }
  controls(item, [control("Remove", () => removeStyleMark(mark.mark_id))]);
}

// A pending suggestion (§9:2, §9:5), to accept or dismiss, marked where it rests on
// outside content (§7:9). Accepting a pin suggestion pins its memory, which confirms its
// wording (§4:3), so the wording is shown with what accepting it does.
function renderSuggestion(list, suggestion) {
  const item = aboutRow(list);
  if (suggestion.kind === "pin") {
    line(item, "Keep this in mind:", "hint");
    line(item, suggestion.content, "reply");
    line(item, "Accepting it pins it, which confirms this wording as yours.", "hint");
  } else {
    line(item, `${fieldLabel(suggestion.field)}:`, "hint");
    line(item, `${quotedValue(suggestion.value)}`, "reply");
  }
  if (suggestion.rests_on_outside_content) {
    line(item, "This rests on outside content rather than on what you told me.", "hint");
  }
  controls(item, [
    control("Accept", () => decideSuggestion(suggestion.suggestion_id, "accept")),
    control("Dismiss", () => decideSuggestion(suggestion.suggestion_id, "dismiss")),
  ]);
}

// One page of the change log, the most recent first (§3:5). The log has no total, so a
// full page offers the next, as the belief listing's does (`offerMore`).
async function readChanges(more, run) {
  if (run !== aboutRuns.current) {
    return;
  }
  const half = headerHalf();
  if (half === null) {
    return;
  }
  const era = sessionEra;
  try {
    const asked = {
      person_id: OWNER_PERSON_ID,
      limit: PAGE,
      offset: more ? aboutRead.changes : 0,
    };
    const body = await relay(half, "/person/changes", asked, "about");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null || run !== aboutRuns.current || body.off === true) {
      return;
    }
    const list = el("change-list");
    if (!more) {
      clearNode(list);
      aboutRead.changes = 0;
    }
    if (body.changes.length === 0 && !more) {
      line(list, "No change yet.", "hint");
    }
    body.changes.forEach((one) => renderChange(list, one));
    aboutRead.changes += body.changes.length;
    offerMore(list, body.changes.length, () => readChanges(true, run));
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "about");
  }
}

function renderChange(list, change) {
  const item = aboutRow(list);
  line(
    item,
    `${fieldLabel(change.field)}: ${quotedValue(change.old)} → ${quotedValue(change.new)}`,
    "reply"
  );
  line(
    item,
    `${localTime(change.at)} · ${CHANGE_HOW_WORDS[change.how] || change.how}`,
    "hint"
  );
}

// One write to the person's model from the About you panel, said on its outcome line,
// and then the panel read again. Nothing is retried: a write that did not land is said,
// and the person decides again.
async function aboutEdit(path, payload, act, landed) {
  // **One write at a time** (adversarial review, round 3): two saves of one field in
  // flight could land in either order, and the older could overwrite the newer choice
  // with nothing on screen saying so. A second act while one is out is said and not sent.
  if (writeLocked()) {
    el("about-outcome").textContent = ABOUT_BUSY;
    return;
  }
  fault(null, "about");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const era = sessionEra;
  const lock = takeWriteLock(half, era, true);
  try {
    const asked = Object.assign({ person_id: OWNER_PERSON_ID }, payload);
    let body;
    try {
      body = await relay(half, path, asked, "about");
    } finally {
      // Held for the write and nothing after it: the read that follows is ordered by
      // `aboutRuns`, and a lock held across it would let one stalled read refuse every
      // later write (adversarial review, round 4).
      releaseWriteLock(lock);
    }
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null) {
      return;
    }
    el("about-outcome").textContent =
      body.off === true ? PERSON_MODEL_OFF : editWords(act, body.edit);
    if (body.off !== true && editLanded(body.edit) && landed !== undefined) {
      landed();
    }
    // The panel is built again, and the box the person is in keeps the keyboard
    // (`renderProfile`).
    await openAbout(true);
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "about");
  }
}

// Whether a write to the person's model is in flight, from either panel, and what a
// second act meanwhile is told. One lock for both panels: a pin from the belief panel and
// an unpin from About you act on the same pins, and could land in either order too.
//
// **A lock still at its read binds only its own session, and only its taker releases
// it** (adversarial review, round 8). A belief act takes the lock before the read that
// checks its row, and an act whose session has ended sends no write after that read
// (`sameSession`); a read stalled under an old session would otherwise refuse every write
// of the session after it until it settled. A write that has been sent binds whatever
// session follows, since it can still land. The old act's release is of its own lock,
// never of one a newer act took.
const aboutWriting = { held: null };

function writeLocked() {
  const held = aboutWriting.held;
  return held !== null && (held.sent || sameSession(held.half, held.era));
}

// `sent`: whether the write itself goes out under the lock now, rather than after a read.
function takeWriteLock(half, era, sent) {
  const lock = { half: half, era: era, sent: sent };
  aboutWriting.held = lock;
  return lock;
}

function releaseWriteLock(lock) {
  if (aboutWriting.held === lock) {
    aboutWriting.held = null;
  }
}
const ABOUT_BUSY = "Your last change is still being made, so this one was not sent. Try again.";

// Whether a write did what was asked, or changed nothing as the contract says such a
// write does; a refusal, before the store or by it, did neither.
function editLanded(edit) {
  return edit.refused === null && edit.write.kind !== "refused";
}

// One pin or unpin from the belief panel, said on its outcome line. The listing is not
// read again: a pin changes no row's standing until the observer has recorded it
// (ADR-0338 §9:6), and a listing re-read would lose the page the person had reached.
async function beliefEdit(path, payload, act) {
  fault(null, "beliefs");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const era = sessionEra;
  try {
    const asked = Object.assign({ person_id: OWNER_PERSON_ID }, payload);
    const body = await relay(half, path, asked, "beliefs");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null) {
      return;
    }
    el("belief-outcome").textContent =
      body.off === true ? PINNING_OFF : editWords(act, body.edit);
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "beliefs");
  }
}

function setField(field, value) {
  // **A box stays a draft until its write lands** (adversarial review, round 3): a value
  // the hub refused is what the person corrects, and a write that never arrived is
  // theirs to send again, so neither may be replaced by what the hub held. Once the
  // write lands the box shows what the hub now holds, unless it was typed in since — which
  // the field's typing count says, and never a comparison of text (round 4).
  const sent = fieldTyping.revision[field] || 0;
  const landed = () => {
    if ((fieldTyping.revision[field] || 0) === sent) {
      fieldTyping.draft.delete(field);
    }
  };
  // An absent value is the clear: the gateway reads absent and `null` alike, and sends
  // the hub no value (ADR-0085 §10).
  const payload = value === null ? { field: field } : { field: field, value: value };
  return aboutEdit("/person/field/set", payload, value === null ? "clear" : "set", landed);
}

function unpinFromAbout(memoryId) {
  return aboutEdit("/person/unpin", { memory_id: memoryId }, "unpin");
}

function removeStyleMark(markId) {
  return aboutEdit("/person/style-mark/remove", { mark_id: markId }, "unmark");
}

function decideSuggestion(suggestionId, act) {
  return aboutEdit(`/person/suggestion/${act}`, { suggestion_id: suggestionId }, act);
}

// What the belief panel says where the memory an id now names is not the one its row
// shows, so a pin or unpin by that id would act on a memory the person was not shown.
const NOT_THE_ROWS =
  "That memory is not the one shown here any more, so nothing was changed. Open What I " +
  "believe again to see it as it is now.";

// Pin or unpin the memory a row shows; a pin confirms the wording shown (ADR-0338 §4:3).
//
// **The wording is read again first, by the id the act will name, and the act is made
// only where it is the row's** (adversarial review, rounds 1 and 2): the listing is as old
// as the page's last read, and its id is the listing's, which a belief read normalises
// where the person model does not (§10:4). A pin made by that id on a memory whose
// wording is not the row's would confirm a wording the person never saw, and an unpin
// would take another memory's pin away.
//
// **One write at a time, taken before the read** (adversarial review, round 6): the
// read is the write's first half, so a Pin whose read was slow would otherwise be sent
// after an Unpin pressed later, and leave pinned what the person last unpinned. The lock
// is the About you panel's own, so neither panel's write overtakes the other's.
async function checkedBeliefEdit(belief, path, act) {
  if (writeLocked()) {
    el("belief-outcome").textContent = ABOUT_BUSY;
    return;
  }
  fault(null, "beliefs");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const era = sessionEra;
  const lock = takeWriteLock(half, era, false);
  try {
    const held = await relay(half, "/belief", { record_id: belief.id }, "beliefs");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    if (held === null) {
      return;
    }
    if (held.belief.id !== belief.id || held.belief.content !== belief.content) {
      el("belief-outcome").textContent = NOT_THE_ROWS;
      return;
    }
    lock.sent = true;
    await beliefEdit(path, { memory_id: belief.id }, act);
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    fault(GATEWAY_GONE, "beliefs");
  } finally {
    // Held for the read and the write, and nothing after: no listing is read again.
    releaseWriteLock(lock);
  }
}

// Whether this hub keeps a person model, read when the belief panel opens: its rows
// offer pin and unpin only where it does. The smallest read, filling no list.
const pinning = { on: false };

async function readPinning() {
  pinning.on = false;
  const half = headerHalf();
  if (half === null) {
    return;
  }
  const era = sessionEra;
  try {
    const asked = { person_id: OWNER_PERSON_ID, lists: [], limit: 1, offset: 0 };
    const body = await relay(half, "/person", asked, "beliefs");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null) {
      // Refused, and said in the panel's fault slot — which the listing read next
      // clears, so the state line says it too (adversarial review, round 3).
      el("belief-pin-state").textContent = PINNING_UNREAD;
      return;
    }
    pinning.on = body.off !== true && body.person_model !== null;
    el("belief-pin-state").textContent = body.off === true ? PINNING_OFF : PINNING_SAYS;
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    pinning.on = false;
    el("belief-pin-state").textContent = PINNING_UNREAD;
  }
}

// What the belief panel says where it could not read whether pinning is on.
const PINNING_UNREAD =
  "I could not read whether pinning is switched on, so no memory below offers it. Open " +
  "What I believe again to try again.";

// A current memory's pin and unpin (ADR-0338 §8:2), the pin control saying that pinning
// confirms the wording shown (§4:3).
function offerPinning(item, belief) {
  if (!pinning.on || belief.kind !== "memory" || belief.status !== "current") {
    return;
  }
  controls(item, [
    control("Pin: confirms this wording", () =>
      checkedBeliefEdit(belief, "/person/pin", "pin")
    ),
    control("Unpin", () => checkedBeliefEdit(belief, "/person/unpin", "unpin")),
  ]);
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
  const era = sessionEra;
  try {
    const body = await relay(half, "/notifications", { limit: PAGE, offset }, "review");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
  line(item, `Noticed: ${localTime(record.noticed_at)}`, "hint");
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
    line(item, `Dismissed: ${localTime(record.dismissed_at)}`, "hint");
  }
  if (record.dropped_at) {
    line(item, `Ruled out: ${localTime(record.dropped_at)}`, "hint");
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
      `Expired: ${localTime(record.expires_at)} — it is kept and readable, and it will not ` +
        "reach you",
      "notice"
    );
    return;
  }
  line(item, `Expires: ${localTime(record.expires_at)}`, "hint");
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
  const era = sessionEra;
  try {
    const body = await relay(half, "/notifications", { limit: PAGE, offset }, "review");
    // Not this session's answer (#2404). **The confirmation is the display here**: this
    // read exists only to put the record in front of the owner before it is destroyed,
    // and a `window.confirm` carrying a belief's content, a conversation's turn count or
    // a notification's summary is that content on screen over a form asking for a
    // session. Nothing has been destroyed at this point, so there is nothing this owes
    // an account of. Adversarial review, round 2, `major`.
    if (!sameSession(half, era)) {
      return;
    }
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
        `Noticed: ${localTime(record.noticed_at)}\n\n` +
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
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
  const era = sessionEra;
  try {
    const body = await relay(half, "/notification/preferences", {}, "tuning");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    if (body === null) {
      return;
    }
    renderTuning(body.preferences);
    show("tuning", true);
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
  const era = sessionEra;
  try {
    const read = await relay(half, "/notification/preferences", {}, "tuning");
    // Not this session's answer (#2404) — and here the check comes before the *write*
    // as well as before the render. A read that resumes under a session this page no
    // longer holds would otherwise send the modified value back under the old half:
    // a request answered `no-live-session`, which `sessionLost` would then act on and
    // throw a freshly re-entered session back to the bootstrap form.
    if (!sameSession(half, era)) {
      return;
    }
    if (read === null) {
      return;
    }
    const written = await relay(
      half,
      "/notification/preferences/set",
      change(read.preferences)
    );
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
    if (written === null) {
      return;
    }
    renderTuning(written.preferences);
    show("tuning", true);
  } catch (_) {
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
  const era = sessionEra;
  try {
    // The form is taken down before the read and put back only if the read answered.
    // A gateway that has started refusing — because its own hub moved to the remote
    // listener — must not leave a credential field standing from the last time it did
    // not (ADR-0177 §4's fourth clause).
    clearNode(form);
    const held = await relay(half, "/connections", {}, "connections");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
  if (HOSTED) {
    // ADR-0327 §12:1's reason, which is not the remote listener's: this page is secure,
    // and a credential typed here would still leave this device for the machine the
    // assistant runs on.
    line(
      holder,
      "Connecting an account is available on the machine your assistant runs on only, " +
        "because a credential typed here would leave this device for that machine. " +
        "Disconnecting and reading this list work here.",
      "hint"
    );
    return;
  }
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
  const era = sessionEra;
  try {
    const held = await relay(half, "/connections/recent", { limit: PAGE }, "connection-log");
    // Not this session's answer (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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
    // Not this session's condition to report (#2404).
    if (!sameSession(half, era)) {
      return;
    }
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

const CONTROL_PANELS = [
  "approvals",
  "about",
  "sources",
  "standing",
  "history",
  "acts",
  "beliefs",
  "review",
  "tuning",
  "connections",
  "connection-log",
  // ADR-0293's chat: the owner's messages and the assistant's, which a page with no
  // session may not be showing. `closeChat` stops its following with it.
  "chat",
];

// --- the menu (#3098) ------------------------------------------------------------
//
// Every panel but the chat is opened from one menu in the bar. An entry closes the menu
// and runs the act it always ran, and once that has put its panel on screen the panel's
// heading takes the focus, which brings it into view below the chat. The act is the
// same act it was: the menu adds no request, no timer and nothing that could become one.
function closeMenu() {
  el("menu").open = false;
}

// A panel opened from the menu takes the keyboard to its heading once it has loaded —
// **unless the person has put the focus somewhere since** (adversarial review of #3363,
// round 11): a panel can be shown, and typed in, before the last of its reads lands, and
// a transfer then would take the keyboard out of the box they are typing in.
function fromMenu(panelId, act) {
  return async () => {
    closeMenu();
    const before = document.activeElement;
    await act();
    const now = document.activeElement;
    const moved = now !== null && now !== before && now !== document.body;
    const panel = el(panelId);
    if (!panel.hidden && !moved) {
      const heading = panel.firstElementChild;
      heading.tabIndex = -1;
      heading.focus();
    }
  };
}

// `because` is the re-entry sentence (ADR-0182 §6), and **omitting it leaves whatever
// is there alone** rather than clearing it. Every act on this page guards on a missing
// header half by calling this with nothing, so a sentence cleared by the next click
// would be an explanation the owner had one click to read. It is cleared where it stops
// being true: when a session starts.
//
// **On the hosted door it shows the hosted panel instead**, which carries no bootstrap
// entry (ADR-0327 §11:1): the same sweep, so a session-less page shows nothing of the
// owner's through either door, and `because` is what that panel says.
function showBootstrap(because) {
  clearFaults();
  if (because !== undefined) {
    el(HOSTED ? "hosted-state" : "reentry").textContent = because;
  }
  show("bootstrap", !HOSTED);
  show("hosted", HOSTED);
  show("console", false);
  show("conversations", false);
  show("notifications", false);
  CONTROL_PANELS.forEach((panel) => show(panel, false));
  closeChat();
}

//
// `resumed` is the hosted page's exchange after a session ended under it (ADR-0327
// §11:2): the console comes back, and **nothing the ended session was doing is
// re-issued** (§11:4, ADR-0182 §7:5) — not the delivery stream and not the chat's
// following, each of which is one press away and said so.
function showConsole(resumed) {
  clearFaults();
  // The re-entry sentence stops being true the moment a session exists, and this is the
  // one place that is so.
  el("reentry").textContent = "";
  el("hosted-state").textContent = "";
  show("bootstrap", false);
  show("hosted", false);
  show("console", true);
  // The notification panel is shown before anything has arrived, because what it
  // mostly says is whether this browser is watching at all — and a panel that
  // appeared only on the first delivery would leave the owner unable to tell "no
  // notifications" from "not connected", which is ADR-0083's ruling 4 failure at the
  // one place ADR-0175 §4 spends a keep-alive to prevent it.
  show("notifications", true);
  if (resumed === true) {
    deliveryState(RESUMED);
    return;
  }
  // The control surface's own entry points are in the console's menu; each panel
  // appears when it has been read, so a panel on screen is always a panel showing an
  // answer rather than an empty promise.
  watchDeliveries();
  // The chat this browser has opened before, opened again; a browser that never opened
  // it reads nothing of it until the owner presses Chat.
  //
  // **Through the sign-in door the chat opens on the first load too** (#3209's
  // follow-on): a person who signed in through the edge has asked for their assistant,
  // and a first screen holding only "Watching for notifications" leaves them looking for
  // where to talk. The page has no control that closes the chat, so there is no stored
  // choice that could say otherwise; the loopback and remote doors keep the owner's one
  // press.
  if (chatWasOpen() || HOSTED) {
    openChat();
  }
}

// The page's name is written once, in the document's <title>, and the bar's heading
// takes it from there — so a rename is one edit, and the tab and the heading cannot
// come to disagree.
el("page-name").textContent = document.title;

el("bootstrap-form").addEventListener("submit", startSession);
// The owner's act after a failed exchange (ADR-0327 §11:3): a reload, which starts the
// page over — and with it the one exchange a load holding no session makes.
el("hosted-again").addEventListener("click", () => window.location.reload());
// Wrapped rather than passed, because the listener's argument is a `MouseEvent` and
// `watchDeliveries` reads its first argument as the sentence to announce.
el("watch-button").addEventListener("click", () => watchDeliveries());
el("fault-dismiss").addEventListener("click", () => fault(null));
el("conversations-button").addEventListener("click", fromMenu("conversations", listConversations));
el("chat-button").addEventListener("click", openChat);
el("chat-back").addEventListener("click", backToList);
NARROW.addEventListener("change", renderChatView);
el("chat-follow-again").addEventListener("click", followAgain);
el("chat-start").addEventListener("click", startChat);
el("chat-more").addEventListener("click", () => listChat(true));
el("chat-older").addEventListener("click", () => {
  if (chat.selected !== null && chat.oldest !== null) {
    void readTranscript(chat.selected, chat.chosen, chat.oldest);
  }
});
el("chat-form").addEventListener("submit", sendChat);
el("chat-reread").addEventListener("click", () => {
  if (chat.selected !== null) {
    fault(null, "chat");
    void selectChat(chat.selected);
  }
});
// Control-Enter (Command-Enter) sends; Enter alone is a new line in the message.
el("chat-text").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    el("chat-form").requestSubmit();
  }
});
// Every edit the person makes to the message is typing, on any keyboard (ADR-0332 §5:5).
// `input` and not `keydown`: a phone's keyboard and a pasted word reach the composer
// without a key event a desktop would send, and setting the box's value from the page —
// emptying it once a message is sent — fires neither.
el("chat-text").addEventListener("input", () => {
  void sendComposing();
});
el("chat-reply-cancel").addEventListener("click", () => setReplyTo(null));
el("chat-stop").addEventListener("click", () => {
  void stopActivations();
});
el("chat-delete").addEventListener("click", deleteChat);
el("chat-forget").addEventListener("click", forgetChat);
document.addEventListener("visibilitychange", chatVisibility);
window.addEventListener("online", chatOnline);
el("sources-button").addEventListener("click", fromMenu("sources", listSources));
el("standing-button").addEventListener("click", fromMenu("standing", listStanding));
el("history-button").addEventListener("click", fromMenu("history", listGrantHistory));
el("approvals-button").addEventListener("click", fromMenu("approvals", openApprovals));
el("about-button").addEventListener("click", fromMenu("about", openAbout));
el("beliefs-button").addEventListener("click", fromMenu("beliefs", openBeliefs));
// A band changed is a different question, so it starts the listing again rather than
// filtering what is already on screen: this page holds no beliefs of its own and the
// hub is what answers which ones match.
["band-asserted", "band-derived", "band-attested"].forEach((box) => {
  el(box).addEventListener("change", listBeliefs);
});
el("review-button").addEventListener("click", fromMenu("review", listNotifications));
el("tuning-button").addEventListener("click", fromMenu("tuning", listTuning));
el("connections-button").addEventListener("click", fromMenu("connections", listConnections));
el("connection-log-button").addEventListener(
  "click",
  fromMenu("connection-log", listConnectionLog)
);
// The menu closes on a link of the index it carries, on a press anywhere outside it, and
// on Escape, as a menu does; so does a conversation's details.
el("panel-index").addEventListener("click", closeMenu);
document.addEventListener("click", (event) => {
  if (!el("menu").contains(event.target)) {
    closeMenu();
  }
  const details = document.querySelector(".chat-about");
  if (!details.contains(event.target)) {
    details.open = false;
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && el("menu").open) {
    closeMenu();
    el("menu").querySelector("summary").focus();
  }
});

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
if (HOSTED) {
  // ADR-0327 §11:7 in place of ADR-0182 §6:3's three conditions, which are this page's
  // on every other door: a session here is the gateway's and lasts as ADR-0168 §4 rules,
  // but the person never meets its end — they meet their sign-in's.
  el("session-terms").hidden = true;
  el("hosted-terms").hidden = false;
  // The panels a person on this door cannot act on, out of its menu (#3209's
  // follow-on). Grant history is a ledger of decisions for auditing them, which "What I
  // may read now" answers in the form a person acts on; the log of what was done to
  // connections is the same kind of record, and offers no act at all. The gateway still
  // admits each read (ADR-0327 §12:2); only the page stops offering them.
  //
  // **"Accounts I am connected to" stays**: an owner who connected an account at the
  // gateway's own machine may come in through this door (§13:2), and its Disconnect is
  // theirs to press here (§12:2).
  for (const control of ["history-button", "connection-log-button"]) {
    el(control).hidden = true;
  }
}
if (headerHalf() !== null) {
  showConsole();
} else if (HOSTED) {
  void exchangeSession(false);
} else {
  showBootstrap();
}
