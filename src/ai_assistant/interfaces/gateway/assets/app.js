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
  sessionLost(body);
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
  fault(null);
  const panel = el("act-log");
  clearNode(panel);
  line(panel, heading, "hint");
  show("acts", true);
  return panel;
}

async function listSources() {
  fault(null);
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const body = await relay(half, "/sources", {});
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
    fault(GATEWAY_GONE);
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
          "is not a grant, and the hub refuses one."
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
    fault(GATEWAY_GONE);
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
    fault(GATEWAY_GONE);
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
    fault(GATEWAY_GONE);
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
    const body = await relay(half, "/grants/standing", {});
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
    fault(GATEWAY_GONE);
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
  fault(null);
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const body = await relay(half, "/grants/recent", {});
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
    fault(GATEWAY_GONE);
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
const readSoFar = { beliefs: 0, questions: 0, interrupted: 0 };

// Which run of each listing is current. An offset is only meaningful against the
// question that produced it, so starting a listing again — a band unchecked, the
// button pressed a second time — retires every page still in flight from the last
// one: a stale answer renders nothing and advances nothing.
//
// Without it a response arriving after the restart appends rows the current filter
// did not ask for and moves the offset the *next* page is read at, which skips
// beliefs — and a belief with no rendered row has no `Forget` control, so the failure
// costs the owner a control rather than a little tidiness.
const runs = { beliefs: 0, questions: 0, interrupted: 0 };

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
  await readBeliefs(false);
}

// One page of beliefs, from the start or from where the last one stopped.
//
// The filter is captured **before** the read and travels with it, so the page that
// arrives is rendered against the question it was asked — and the run check after the
// await is what retires it if the owner has since asked a different one.
async function readBeliefs(more) {
  fault(null);
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const run = runs.beliefs;
  const bands = bandFilter();
  const asked = { limit: PAGE, offset: readSoFar.beliefs };
  if (bands !== null) {
    asked.bands = bands;
  }
  try {
    const body = await relay(half, "/beliefs", asked);
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
    offerMore(list, body.beliefs.length, () => readBeliefs(true));
    show("beliefs", true);
  } catch (_) {
    fault(GATEWAY_GONE);
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
  fault(null);
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const held = await relay(half, "/belief", { record_id: id });
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
    const done = await relay(half, "/belief/forget", { record_id: id });
    if (done === null) {
      return;
    }
    if (!done.destroyed) {
      fault("There was nothing live by that id to destroy.");
    }
    await listBeliefs();
  } catch (_) {
    fault(GATEWAY_GONE);
  }
}

// --- the deferred-question surface (ADR-0078 §8, §9) -------------------------

async function listQuestions() {
  Object.values(QUESTION_LISTS).forEach((listing) => {
    runs[listing.counter] += 1;
    readSoFar[listing.counter] = 0;
  });
  await readQuestions("/questions", false);
  await readQuestions("/questions/interrupted", false);
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
async function readQuestions(path, more) {
  fault(null);
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const listing = QUESTION_LISTS[path];
  const run = runs[listing.counter];
  const offset = readSoFar[listing.counter];
  try {
    const body = await relay(half, path, { limit: PAGE, offset });
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
    offerMore(list, body.questions.length, () => readQuestions(path, true));
    show("questions", true);
  } catch (_) {
    fault(GATEWAY_GONE);
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
  fault(null);
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const panel = beginActs("Answering.");
  try {
    const body = await relay(half, "/question/answer", { question_id: id, accept });
    if (body === null) {
      return;
    }
    renderAnswer(panel, body.answered);
    await listQuestions();
  } catch (_) {
    fault(GATEWAY_GONE);
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
  fault(null);
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  try {
    const body = await relay(half, path, { limit: PAGE, offset });
    if (body === null) {
      return;
    }
    const question = body.questions.find((one) => one.id === id);
    if (question === undefined) {
      fault(QUESTION_GONE);
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
    const done = await relay(half, "/question/forget", { question_id: id });
    if (done === null) {
      return;
    }
    await listQuestions();
  } catch (_) {
    fault(GATEWAY_GONE);
  }
}

// --- looking over a conversation (ADR-0077 §8) -------------------------------
//
// The passive half of accumulation, and it is deliberately explicit: nothing
// triggers it but a caller, which here is the owner pressing a button. The
// conversation id is a **selector rather than a subject** — this one, or the most
// recently active — so the page sends the one it is working in and nothing when it
// holds none.
async function observe() {
  fault(null);
  const half = headerHalf();
  if (half === null) {
    showBootstrap();
    return;
  }
  const asked = conversationId === null ? {} : { conversation_id: conversationId };
  try {
    const body = await relay(half, "/observe", asked);
    if (body === null) {
      return;
    }
    renderObservation(body.observation);
    show("observation", true);
  } catch (_) {
    fault(GATEWAY_GONE);
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
  "control",
  "sources",
  "standing",
  "history",
  "acts",
  "beliefs",
  "questions",
  "observation",
];

function showBootstrap() {
  show("bootstrap", true);
  show("console", false);
  show("conversations", false);
  show("notifications", false);
  CONTROL_PANELS.forEach((panel) => show(panel, false));
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
  // The control surface's own entry points are shown with the console; each panel
  // below them appears when it has been read, so a panel on screen is always a
  // panel showing an answer rather than an empty promise.
  show("control", true);
  el("utterance").focus();
  watchDeliveries();
}

el("bootstrap-form").addEventListener("submit", startSession);
el("ask-form").addEventListener("submit", ask);
el("watch-button").addEventListener("click", watchDeliveries);
el("conversations-button").addEventListener("click", listConversations);
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

stopWatching();
if (headerHalf() === null) {
  showBootstrap();
} else {
  showConsole();
}
