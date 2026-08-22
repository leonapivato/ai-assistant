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
// its connections" (ADR-0175 §4). There is no `setTimeout` and no `setInterval` here.

"use strict";

const STORAGE_KEY = "assistant.session.header-half";
const CONVERSATION_KEY = "assistant.session.conversation-id";
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

// Whether a delivery stream is open. One at a time: a second would be a second poll
// the hub would close under ADR-0131 §2, and the gateway holds one poll however
// many streams watch it (ADR-0175 §4).
let watching = false;

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

function forgetHeaderHalf() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch (_) {
    // Nothing to do: a browser that will not store will not have stored.
  }
  // The conversation goes with the session, in one place rather than at each of the
  // callers: a thread carried into a session the owner started afresh would be this
  // page continuing something the hub was never asked to continue.
  setConversation(null);
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
  setConversation(null);
  el("utterance").focus();
}

function show(id, visible) {
  el(id).hidden = !visible;
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

// One response body, as an object or as nothing.
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
async function readBody(response) {
  try {
    const parsed = await response.json();
    return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed
      : {};
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
  "no-live-session":
    "This browser has no live session. Start one with the value the gateway printed.",
  "cookie-half-mismatch":
    "Another local service replaced this gateway's cookie, so the two halves of " +
    "the session no longer match. Restart the gateway and start a session again.",
  "session-ceiling": "The gateway is holding as many sessions as it admits.",
  "bootstrap-exchange-failed": "That did not start a session.",
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
// **A condition that ended the session is reported in the bootstrap panel instead**,
// because `sessionLost` has just hidden every other one. Writing it into the panel the
// act belonged to would put the reason behind `hidden` and leave the owner looking at
// a bootstrap form that appeared for no stated reason — ADR-0168 §9's distinction
// arriving as silence at the last hop.
function report(panelId, body, message) {
  const lost = sessionLost(body);
  fault(message, lost ? "bootstrap" : panelId);
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
    setConversation(null);
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

function renderOutcome(outcome) {
  const body = el("answer-body");
  clearNode(body);
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
  if (outcome.steps.length === 0 && outcome.step === null) {
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
  // `null` only where nothing could be resolved (a recovered park, a deleted
  // conversation), and the last known id is then kept rather than cleared: the
  // hub decides which conversation a turn ran under, and forgetting one on an
  // answer that names none would silently start a new one on the next question.
  if (outcome.conversation_id) {
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
  line(item, "It would reach:", "hint");
  egress.destinations.forEach((one) => line(item, destinationWords(one), "hint"));
  line(item, "What it describes sending:", "hint");
  if (egress.spans.length === 0) {
    line(item, "the payload description names no span", "hint");
  }
  egress.spans.forEach((one) => line(item, spanWords(one), "hint"));
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

// The answer, offered only once everything above it is on screen.
//
// Two buttons rather than a checkbox and a submit, because each is one act and the
// page never holds a half-made answer. `resume` is answered with `approved` and
// nothing else — the deadline is the gateway's (ADR-0177 §9) and no value from here
// reaches it.
function offerApproval(item, token) {
  const approve = document.createElement("button");
  approve.type = "button";
  approve.textContent = "Yes, do it";
  const decline = document.createElement("button");
  decline.type = "button";
  decline.textContent = "No";
  // **One answer per park, enforced here rather than discovered at the hub.** A
  // second `resume` on a token the first already resolved raises
  // `UnknownContinuationError`, which ADR-0084 §7 makes emphatically *not* a denial —
  // so a double click would put "the hub declined it" on screen for an action that
  // had in fact just run, which is the one thing this surface exists to get right.
  // Both are disabled because either one submits, and both come back where the
  // request failed and the row survives to be answered again — `ask` disables its own
  // button for the same window and for the same reason.
  const answer = async (approved) => {
    approve.disabled = true;
    decline.disabled = true;
    try {
      await answerConfirmation(token, approved);
    } finally {
      approve.disabled = false;
      decline.disabled = false;
    }
  };
  approve.addEventListener("click", () => answer(true));
  decline.addEventListener("click", () => answer(false));
  item.appendChild(approve);
  item.appendChild(decline);
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
// life — a reload starts it empty, which is correct: the engine has evicted every entry
// it resolved, so a spent token is one the listing will never hand back.
const spent = new Set();

// One answer, relayed. The page conveys consent and rules on nothing (ADR-0042 §6):
// a refusal comes back as an ordinary outcome whose step was denied, not as a fault,
// and it is rendered where every other turn's result is rendered.
//
// The listing is read again afterwards, quietly, because answering one park is the
// only thing that changes what is waiting — and re-reading is also how the page gets
// fresh tokens for whatever is left rather than keeping the ones it has.
async function answerConfirmation(token, approved) {
  if (spent.has(token)) {
    return;
  }
  fault(null, "confirmations");
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  // Claimed before the first `await`, so two clicks in one turn of the event loop —
  // the two rows of one park, or one row twice — cannot both get past the guard.
  spent.add(token);
  let body = null;
  try {
    body = await relay(half, "/confirmation/resume", { token, approved }, "confirmations");
  } catch (_) {
    // The gateway is gone. Nothing was answered as far as this page can tell, so the
    // continuation is given back and the row stays answerable.
    spent.delete(token);
    fault(GATEWAY_GONE, "confirmations");
    return;
  }
  if (body === null) {
    // A refusal the gateway named and `relay` already displayed — a full hub, a
    // declined request. It is not a resolution, so the token is given back too.
    spent.delete(token);
    return;
  }
  renderOutcome(body.outcome);
  // Read again, and **after** the guard on this token has done its work rather than
  // inside it: this is the best-effort tidy-up of what is left on screen, and no other
  // park's answer waits on it.
  await readPending(true);
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
  setConversation(null);
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

// A refusal that means this browser's session is gone. Forgetting the half and
// showing the bootstrap panel is the only thing a page can do about either, and
// doing it in one place keeps the two conditions from drifting apart.
function sessionLost(body) {
  if (body.fault === "no-live-session" || body.fault === "cookie-half-mismatch") {
    forgetHeaderHalf();
    stopWatching();
    showBootstrap();
    return true;
  }
  return false;
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
      await askStreaming(half, asked);
    } else {
      await askWhole(half, asked);
    }
  } catch (_) {
    // `fetch` rejects when the connection itself failed — the gateway is gone,
    // which is a different fault from the hub being gone and is said as one.
    show("answer", false);
    fault(GATEWAY_GONE, "console");
  } finally {
    button.disabled = false;
  }
}

async function askWhole(half, asked) {
  const response = await fetch("/ask", {
    method: "POST",
    headers: admitted(half, true),
    body: JSON.stringify(asked),
  });
  const body = await readBody(response);
  if (response.ok) {
    renderOutcome(body.outcome);
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
async function askStreaming(half, asked) {
  const response = await fetch("/ask/stream", {
    method: "POST",
    headers: admitted(half, true),
    body: JSON.stringify(asked),
  });
  if (!response.ok) {
    const body = await readBody(response);
    show("answer", false);
    conversationLost(body, asked.conversation_id);
    refused("console", body, response.status);
    return;
  }
  const panel = el("answer-body");
  clearNode(panel);
  show("answer", true);
  const composing = line(panel, "", "reply");
  let terminal = null;
  for await (const value of streamValues(response)) {
    if (value.kind === "chunk") {
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
  renderOutcome(terminal.outcome);
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
//      `online`, never a timer, a schedule, or the failure itself. There is no
//      `setTimeout` and no `setInterval` in this file.
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

function stopWatching() {
  watching = false;
  deliveryState("Not watching for notifications.");
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
async function readDeliveries(half) {
  try {
    const response = await fetch("/deliveries", { headers: admitted(half, false) });
    if (!response.ok) {
      const body = await readBody(response);
      stopWatching();
      refused("notifications", body, response.status);
      return;
    }
    let terminal = null;
    for await (const value of streamValues(response)) {
      if (value.kind === "notification") {
        renderNotification(value);
      } else if (TERMINAL_KINDS.has(value.kind)) {
        terminal = value;
        break;
      }
      // `alive` is the keep-alive and needs no rendering: what it proves is that
      // the gateway, its hub connection and this socket are all still there, which
      // the absence of an ending already says.
    }
    stopWatching();
    if (terminal === null) {
      fault(DELIVERY_STREAM_CUT, "notifications");
    } else {
      report("notifications", terminal, describeDeliveryEnd(terminal, response.status));
    }
  } catch (_) {
    stopWatching();
    fault(GATEWAY_GONE, "notifications");
  }
}

// --- the conversation surface (ADR-0175 §6) ----------------------------------

async function relay(half, path, payload, panelId) {
  const response = await fetch(path, {
    method: "POST",
    headers: admitted(half, true),
    body: JSON.stringify(payload),
  });
  const body = await readBody(response);
  if (response.ok) {
    return body;
  }
  // Every other request that names a conversation goes through here — the digest, the
  // forget, and `observe`, which sends this view's selection exactly as `ask` does.
  conversationLost(body, payload.conversation_id);
  refused(panelId, body, response.status);
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
    setConversation(summary.id);
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
      setConversation(null);
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
  if (sessionLost(body)) {
    // The act log has just been hidden with the rest of the console, so the condition
    // is restated beside the only act left to take. `reportAct` still writes its own
    // line below, and it is about what the act did rather than about the session.
    fault(describe(body, response.status), "bootstrap");
  }
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
    const text = document.createElement("label");
    text.htmlFor = box.id;
    text.textContent = use.label;
    row.appendChild(box);
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
  const name = document.createElement("p");
  name.className = "source-name";
  name.textContent = grant.source;
  item.appendChild(name);
  line(item, `You authorise ${usePhrase(grant.scope)}.`, "reply");
  line(item, `Decided ${grant.decided_at}`, "hint");
  list.appendChild(item);
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

// Why a belief is held — band-dependent, and the answer is complete for one band
// and owed for two (ADR-0073 §4).
//
// **The floor is what stops the gap being papered over.** A derived belief conveys
// how many citations stand behind it and is never presented as carrying a warrant
// this surface cannot show; an attested one is named as someone else's report, and
// the line says outright that "last revised" is this system's clock rather than the
// source's. Beside any rendered count sits ADR-0107 §5's ceiling, because a
// displaced citation is not a lost one.
function whyHeld(belief) {
  if (belief.band === "asserted") {
    return "You told me, and your own word is the whole of it.";
  }
  if (belief.band === "attested") {
    return (
      "A source you connected reported it — neither your word nor my inference. I " +
      "recorded which source, and when it said so, but cannot show them here, so " +
      "'last revised' is when I changed my mind and not when the source spoke."
    );
  }
  return whyDerived(belief);
}

function whyDerived(belief) {
  const ceiling =
    belief.evidence_elided > 0
      ? ` Up to ${belief.evidence_elided} more piece(s) stood behind it that I no ` +
        "longer keep a reference to — those may still exist; I stopped carrying " +
        "them, they were not lost."
      : "";
  if (belief.evidence_count === 0) {
    return (
      (ceiling
        ? "I worked it out, and I carry no evidence for it now."
        : "I worked it out, and no supporting evidence was recorded.") + ceiling
    );
  }
  if (belief.unsupported) {
    return (
      `I worked it out from ${belief.evidence_count} piece(s) of evidence, none of ` +
      "which still exists. I still hold it — I have not unlearnt it because the " +
      (ceiling ? "evidence went." : "evidence went — but nothing supports it any more.") +
      ceiling
    );
  }
  if (belief.lost_evidence > 0) {
    return (
      `I worked it out from ${belief.evidence_count} piece(s) of evidence, ` +
      `${belief.lost_evidence} of which no longer exists. The confidence shown ` +
      "reflects what is left." +
      ceiling
    );
  }
  return `I worked it out from ${belief.evidence_count} piece(s) of evidence.` + ceiling;
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
function renderQuestion(list, question, path, offset) {
  const item = document.createElement("div");
  item.className = "question-row";
  line(item, question.content, "reply");
  line(
    item,
    `Would be held as: ${bandWords(question.band)} · ${question.kind} ` +
      "(not held yet — I am asking first)",
    "hint"
  );
  line(item, `Why I am asking: ${question.reason}`, "hint");
  line(item, `Proposed because: ${question.rationale}`, "hint");
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
  } else {
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

// Exactly what accepting would retire (ADR-0078 §8), which is not decoration but
// the exact scope the answer authorises. A conflict already retired is rendered as
// no longer held rather than omitted: omitting it would understate the answer's
// scope in one direction and overstate it in the other.
function renderRetirements(item, question) {
  if (question.retires.length === 0) {
    line(item, "Accepting would retire: nothing", "hint");
    return;
  }
  line(item, "Accepting would retire:", "hint");
  question.retires.forEach((one) => {
    line(
      item,
      one.content === null
        ? `${one.record_id} — no longer held, so accepting would not touch it`
        : `${one.content} (${one.record_id})`,
      "hint"
    );
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

function showBootstrap() {
  clearFaults();
  show("bootstrap", true);
  show("console", false);
  show("conversations", false);
  show("notifications", false);
  CONTROL_PANELS.forEach((panel) => show(panel, false));
}

function showConsole() {
  clearFaults();
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
  el("utterance").focus();
  watchDeliveries();
  // A park outlives the page that raised it, so a browser opening onto one has to be
  // told without being asked (ADR-0177 §8). Quiet, because a load that finds nothing
  // waiting has nothing to say.
  readPending(true);
}

el("bootstrap-form").addEventListener("submit", startSession);
el("ask-form").addEventListener("submit", ask);
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
