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

"use strict";

const STORAGE_KEY = "assistant.session.header-half";
const SESSION_HEADER = "X-Assistant-Session";

// Which stream values end a stream (ADR-0175 §2). A reader that reached one has the
// whole of what the gateway sent; a reader whose body ended without one has a
// transport failure and says so — which is ADR-0168 §9's distinction reaching the
// browser, on a carrier whose status code was written before anything went wrong.
const TERMINAL_KINDS = new Set(["outcome", "fault"]);

// The conversation the last turn ran under, kept in page state alone. The hub
// owns the conversation; this is the id it handed back, held so the next question
// continues the same one rather than starting a fresh one the owner never asked
// for — the same thing `assistant ask --conversation` does at the terminal. It is
// not persisted: a reload is a new page, and the id is the hub's to hand back.
let conversationId = null;

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
}

function show(id, visible) {
  el(id).hidden = !visible;
}

function fault(message) {
  const node = el("fault");
  node.textContent = message;
  show("fault", message !== null);
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

async function readBody(response) {
  try {
    return await response.json();
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
};

// A stream whose body ended without a terminal value (ADR-0175 §2). Not a fault the
// gateway named — it is the connection itself going away, which is exactly what §2
// makes the front end report as a transport failure.
const STREAM_CUT =
  "The connection carrying that answer ended before the gateway finished it. " +
  "Nothing here is the whole answer; ask again.";

const GATEWAY_GONE =
  "The gateway did not answer. It may have stopped; every session ends when it does.";

function describe(body, status) {
  const known = FAULTS[body.fault];
  const detail = typeof body.detail === "string" && body.detail ? ` ${body.detail}` : "";
  if (known) {
    return known + detail;
  }
  return `The gateway refused that request (HTTP ${status}).`;
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
  if (outcome.steps.length === 0) {
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
    conversationId = outcome.conversation_id;
  }
  el("conversation").textContent = conversationId ? `Conversation ${conversationId}` : "";
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
  if (step.awaiting_confirmation) {
    line(
      body,
      "The assistant parked this step for confirmation. The gateway authors no " +
        "permission ruling, so answer it with 'assistant resume' at a terminal.",
      "notice"
    );
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

async function startSession(event) {
  event.preventDefault();
  fault(null);
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
    fault(GATEWAY_GONE);
    return;
  }
  if (!response.ok) {
    fault(describe(body, response.status));
    return;
  }
  el("bootstrap-value").value = "";
  conversationId = null;
  if (!rememberHeaderHalf(body.header_half)) {
    fault("This browser will not store the session, so it cannot hold one.");
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
  fault(null);
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
    fault(GATEWAY_GONE);
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
  fault(describe(body, response.status));
  sessionLost(body);
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
    fault(describe(body, response.status));
    sessionLost(body);
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
    fault(STREAM_CUT);
    return;
  }
  if (terminal.kind === "fault") {
    show("answer", false);
    fault(describe(terminal, response.status));
    sessionLost(terminal);
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
// **It is not restarted automatically.** A stream that ends says so and offers the
// owner a button, rather than reconnecting on a timer nobody can see: ADR-0168 §9's
// rule against silent retrying is the gateway's, and a page that spun against an
// unreachable hub would be the same failure wearing the front end's clothes.
async function watchDeliveries() {
  const half = headerHalf();
  if (half === null || watching) {
    return;
  }
  watching = true;
  deliveryState("Watching for notifications.");
  try {
    const response = await fetch("/deliveries", { headers: admitted(half, false) });
    if (!response.ok) {
      const body = await readBody(response);
      stopWatching();
      fault(describe(body, response.status));
      sessionLost(body);
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
    fault(terminal === null ? STREAM_CUT : describe(terminal, response.status));
    if (terminal !== null) {
      sessionLost(terminal);
    }
  } catch (_) {
    stopWatching();
    fault(GATEWAY_GONE);
  }
}

// --- the conversation surface (ADR-0175 §6) ----------------------------------

async function relay(half, path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: admitted(half, true),
    body: JSON.stringify(payload),
  });
  const body = await readBody(response);
  if (response.ok) {
    return body;
  }
  fault(describe(body, response.status));
  sessionLost(body);
  return null;
}

async function listConversations() {
  fault(null);
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const body = await relay(half, "/conversations", {});
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
    fault(GATEWAY_GONE);
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
    conversationId = summary.id;
    el("conversation").textContent = `Conversation ${conversationId}`;
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
  fault(null);
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const digest = await relay(half, "/conversation", { conversation_id: id });
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
    const done = await relay(half, "/conversation/forget", { conversation_id: id });
    if (done === null) {
      return;
    }
    if (conversationId === id) {
      conversationId = null;
      el("conversation").textContent = "";
    }
    await listConversations();
  } catch (_) {
    fault(GATEWAY_GONE);
  }
}

function showBootstrap() {
  show("bootstrap", true);
  show("console", false);
  show("conversations", false);
  show("notifications", false);
}

function showConsole() {
  show("bootstrap", false);
  show("console", true);
  // The notification panel is shown before anything has arrived, because what it
  // mostly says is whether this browser is watching at all — and a panel that
  // appeared only on the first delivery would leave the owner unable to tell "no
  // notifications" from "not connected", which is ADR-0083's ruling 4 failure at the
  // one place ADR-0175 §4 spends a keep-alive to prevent it.
  show("notifications", true);
  el("utterance").focus();
  watchDeliveries();
}

el("bootstrap-form").addEventListener("submit", startSession);
el("ask-form").addEventListener("submit", ask);
el("watch-button").addEventListener("click", watchDeliveries);
el("conversations-button").addEventListener("click", listConversations);

stopWatching();
if (headerHalf() === null) {
  showBootstrap();
} else {
  showConsole();
}
