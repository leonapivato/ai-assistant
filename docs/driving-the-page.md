# Driving the page before review

This is the how-to for the rule in `.claude/agents/worker.md`: a lane whose diff
touches `src/ai_assistant/interfaces/gateway/assets/` drives that page before its
first review invocation — at a desktop width and at an iPhone-class viewport —
and records what it saw in the PR description. Nothing else in the loop looks at
the rendered page: the gate asserts over the bytes the page is built from, and the
reviewer reads the diff. PR #1385 found three defects by looking that had passed
every check this project runs (one filed as #1392).

## Bind the real `Gateway` over a seeded fake

Bind the real `Gateway` in-process over a seeded `FakeAssistantEngine`
(`ai_assistant.testing`), not a live hub. The page is then driven against the
same server the suite binds, with the seed under your control and no data
directory, credential or resident process in the way. PR #1385's description is
the worked shape: Chromium at 1100×900 and at the iPhone 13 Pro viewport, over a
gateway bound to a seeded fake.

## Drive it through the MCP server where one is exposed

This repository's `.mcp.json` declares a project-scope `playwright` server; each
developer approves it once in an interactive session (`/mcp`), and that approval
is recorded outside the repository, so nothing tracked here can pre-approve it.
**Where none is exposed** — not offered to your session, or it will not start —
say so in the PR description and verify the same way by script, driving
Playwright directly. What is owed is the observation; the instrument is not the
point.

**A `Browser "…" is not installed` at the first tool call is an install, not a
fault.** Run it through the launcher — `scripts/playwright-mcp.sh install-browser
chrome-for-testing` — because the browser builds are versioned with the pinned
server, and browsers a stray `npx playwright install` put in the same cache do
not satisfy it.

A lane whose diff touches no file under `assets/` has no page to drive, and is
better off with the server not exposed at all: its tool definitions are context
every turn pays for.

## Two known console false positives

Neither of these is a defect; anything else in the console is the lane's.

- **`favicon.ico … 401` on every load before a session exists.** Admission is
  decided before routing, so a session-less request to *any* path answers 401 —
  including the one the browser makes on its own. An *admitted* request to an
  unserved path answers 404 instead, which
  `tests/interfaces/gateway/test_gateway.py` pins.
- **`Refused to apply a stylesheet … style-src`, under WebKit and only on a
  `fullPage` screenshot.** That is Playwright's own injected screenshot
  stylesheet meeting the gateway's `style-src 'self'` (`gateway/server.py`,
  ADR-0168 §6). The page carries no inline style, and the message is absent
  without the screenshot call — under Chromium it does not appear at all.
