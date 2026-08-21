// The front end. Two rules shape every line of it.
//
// **Every value the hub returned is inserted as text and never as markup**
// (ADR-0168 §6). An answer is model output, and a model is not a trusted source
// of markup — so this file builds nodes and sets `textContent`, and never touches
// `innerHTML`, `insertAdjacentHTML`, `document.write` or `eval`.
//
// **The header half lives in `localStorage`, which is scoped to scheme, host and
// port and shared across that origin's tabs** (ADR-0168 §6). A cookie is not
// port-scoped, which is the whole reason a session is two values; web storage is,
// so the value at `127.0.0.1:8422` is unreadable from `127.0.0.1:9000`. The other
// half is the `HttpOnly` cookie the gateway set, which this file cannot read and
// never tries to.

"use strict";

const STORAGE_KEY = "assistant.session.header-half";
const SESSION_HEADER = "X-Assistant-Session";

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
  "hub-connection-ceiling":
    "The gateway is already holding as many connections to the hub as it may " +
    "(gateway_max_hub_connections), so this request was refused rather than queued.",
  "request-too-large": "That request was larger than the gateway will read.",
};

function describe(body, status) {
  const known = FAULTS[body.fault];
  const detail = typeof body.detail === "string" && body.detail ? ` ${body.detail}` : "";
  if (known) {
    return known + detail;
  }
  return `The gateway refused that request (HTTP ${status}).`;
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
  el("conversation").textContent = outcome.conversation_id
    ? `Conversation ${outcome.conversation_id}`
    : "";
  show("answer", true);
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
  const response = await fetch("/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bootstrap_value: value }),
  });
  const body = await readBody(response);
  if (!response.ok) {
    fault(describe(body, response.status));
    return;
  }
  el("bootstrap-value").value = "";
  if (!rememberHeaderHalf(body.header_half)) {
    fault("This browser will not store the session, so it cannot hold one.");
    return;
  }
  showConsole();
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
    const response = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", [SESSION_HEADER]: half },
      body: JSON.stringify({ utterance: el("utterance").value }),
    });
    const body = await readBody(response);
    if (response.ok) {
      renderOutcome(body.outcome);
      return;
    }
    show("answer", false);
    fault(describe(body, response.status));
    if (body.fault === "no-live-session" || body.fault === "cookie-half-mismatch") {
      forgetHeaderHalf();
      showBootstrap();
    }
  } catch (_) {
    // `fetch` rejects when the connection itself failed — the gateway is gone,
    // which is a different fault from the hub being gone and is said as one.
    show("answer", false);
    fault("The gateway did not answer. It may have stopped; every session ends when it does.");
  } finally {
    button.disabled = false;
  }
}

function showBootstrap() {
  show("bootstrap", true);
  show("console", false);
}

function showConsole() {
  show("bootstrap", false);
  show("console", true);
  el("utterance").focus();
}

el("bootstrap-form").addEventListener("submit", startSession);
el("ask-form").addEventListener("submit", ask);

if (headerHalf() === null) {
  showBootstrap();
} else {
  showConsole();
}
