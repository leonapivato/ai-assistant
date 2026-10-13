# 316. An activation viewer outside the package shows the diagnostic record to the owner on the server

- Status: Proposed
- Date: 2026-10-13
- Scope: the phases, milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)): an owner-run program that shows each activation's flow from [ADR-0314](0314-a-diagnostic-record-keeps-what-each-phase-was-given-and-returned-and-nothing-reads-it-back.md)'s diagnostic record, so the owner can watch activations being processed.
- Authorization: the owner asked for it on 2026-10-13 and ruled its substance: flow first, decisions and content one click away, and separate from the hub. The dispatcher chose where it runs (on the server, on loopback, over an SSH tunnel), assigned 0316, and authorized ratifying it once its reviews are green.
- Changes no `core` type or Protocol, nothing the wire carries, and no file under `src/`.
- **Partially supersedes**
  [ADR-0314](0314-a-diagnostic-record-keeps-what-each-phase-was-given-and-returned-and-nothing-reads-it-back.md)
  (§3:4, in the addition alone: the server's own tools include this viewer).

## Context

The owner wants to watch activations being processed: to understand the system, to see
what works as planned, and to see what differs in daily use, by passively watching. The
diagnostic record holds what is needed. Each activation is one file of JSON lines under
`<data_dir>/diagnostics`, with an entry for each controller step and for what each phase
was given and returned (ADR-0314 §4, §6). Read with `jq` or `less`, though, it shows one
line at a time and not the flow: what ran when, for how long, and over how many rounds.

The record is safe only because nothing reads it back: nothing in `ai_assistant` reads an
entry, no gateway route, command or export serves it (ADR-0314 §3:1), and the owner reads
it on the server with the server's own tools (§3:4). It holds raw outside text and other
people's words. A viewer therefore has to stand outside the package, the hub and every
surface the hub serves, and has to be as careful with that text as the record is.

## Decision

We will add one owner-run program, `scripts/activation_viewer.py`. It stands outside the
`ai_assistant` package and imports nothing from it. The owner starts it by hand on the
server, where it reads the record's files read-only and serves a page on loopback, which
the owner reaches over an SSH tunnel. The page shows each activation's flow first, and
its decisions and content one click away.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the authorization to ratify stands; an assigned number or a green review alone
> does not change its status.

> **Normative.** One lane implements this decision after it merges `Accepted`: the
> program and its tests, in one change that touches nothing under `src/`.

### 2. What it is, and where it lives

> **Normative.** The viewer is one file, `scripts/activation_viewer.py`, holding both its
> server and its page, so the wheel does not carry it and the hub's deploy neither
> installs nor starts it.

> **Normative.** The viewer imports the Python standard library alone. It imports nothing
> from `ai_assistant` or from any other package, and it reads the files' JSON on its own
> terms.

> **Normative.** No dependency is added for it: neither `pyproject.toml` nor `uv.lock`
> changes, and its page is plain HTML, CSS and JavaScript held in the one file.

> **Normative.** Nothing in `ai_assistant` imports the viewer, names its file or starts
> it, and no service unit, deploy or hub surface starts it either.

> **Normative.** The owner starts it by hand on the server, as the hub's user, the one
> account the record's files are readable by (ADR-0314 §2:3). It takes the record's
> directory as its argument, and it runs on the Python version the repository targets,
> so the hub's own interpreter runs it.

`scripts/` is chosen because the gate already covers it: ruff lints it, mypy's `files`
includes it, and `tests/scripts/` runs in `pytest`. `scripts/deploy_hub.py` is operator
tooling there already. The directory is no package and the wheel packages
`src/ai_assistant` alone, so the import-linter contracts and the record's write-only test,
both of which scan `ai_assistant`, hold unchanged. §7:1 adds the reverse check.

The owner copies the one file to the server and starts it there. A tunnel such as
`ssh -L 8765:127.0.0.1:8765 <server>` then reaches the page at `http://127.0.0.1:8765`.

### 3. What it shows

> **Normative.** The viewer lists the activations, newest first. For each it shows the
> input in short, how the activation ended, its duration, its number of planning rounds,
> and badges for: needs you, outside content read, could not finish, digest failed,
> refused, and truncated.

> **Normative.** For one activation, the viewer shows a timeline from the entries'
> instants, with one lane for each of the controller, recall, understanding, planning by
> round, authorizing, acting and digesting.

> **Normative.** Clicking a step or an entry shows its body whole: what a source was given
> and returned, planning's thinking and calls, authorizing's checks and grounds, and a
> digest's question and evidence.

> **Normative.** The timeline marks a message where authorizing allowed one, and does not
> claim it was written: acting and the message writes write no entry (ADR-0314 §4:3).

Where each item comes from, in the bodies ADR-0314's sources write today:

| Shown | From |
| --- | --- |
| Lanes and durations; acting | The controller's step entries: each step's stage, rule, start, end and outcome |
| How it ended; could not finish | The end step's rule, and any step that failed or timed out |
| Rounds | The controller's planning steps |
| Input in short | The user's input in the first request understanding or planning was given |
| Needs you; refused | Authorizing's verdict for each call, and the message's verdict |
| Outside content read | Authorizing's `read_outside_content`, with the grounds that held |
| Digest failed | A digesting entry returned as failed |
| Truncated | The file's truncation marker (ADR-0314 §6:3) |

### 4. Near-live

> **Normative.** The viewer follows the directory as it changes, by polling, so an
> activation appears and grows while it runs. It reads a file only up to its last
> complete line, and drops a file that disappears, as the sweep deletes them (ADR-0314
> §7:2).

### 5. Its contract with the record

> **Normative.** The viewer depends on ADR-0314 §6:2's line alone: one JSON object
> holding `activation_id`, `source`, `kind`, `recorded_at` and `body`.

> **Normative.** The body keys §3 reads are hints. Where one is missing or unrecognised,
> the hint is lost and the entry is still shown, its body whole.

> **Normative.** The viewer copes with what it does not know. It shows a source or kind
> it does not know in a lane of its own. It counts a line that is not such an object as
> unreadable on its activation, and reads on. It shows the truncation marker as the
> file's end, with its instant.

### 6. What it may not do

> **Normative.** It binds `127.0.0.1` alone, and no option or argument binds it anywhere
> else.

> **Normative.** It answers only a request whose `Host` header names `127.0.0.1` or
> `localhost` at its own port, so a page the owner's browser loads elsewhere cannot reach
> it through a rebound name.

> **Normative.** It answers `GET` alone. A request names an activation by an id the viewer
> found in the directory's listing, and never by a path.

> **Normative.** It writes nothing, not even a cache: it opens the record's files read-only
> and creates no file, in the record's directory or anywhere else.

> **Normative.** Every response carries `Cache-Control: no-store`, so the owner's browser
> keeps no copy either.

> **Normative.** It sends nothing anywhere: it opens no outgoing connection, its page loads
> nothing that the viewer does not serve, and a `Content-Security-Policy` header admits no
> origin but the viewer's own.

> **Normative.** The page renders every string taken from an entry as text and never as
> markup, because the record holds raw outside text.

> **Normative.** Nothing it prints is taken from an entry: it prints its address and its
> failures by class, as ADR-0314 §2:4 has the store log them.

### 7. Its tests

> **Normative.** The implementing lane's tests live under `tests/scripts/`, run in the gate
> and load the viewer by path. They check from its source that it imports the standard
> library alone, and that no module under `src/ai_assistant` names it.

> **Normative.** At least one test builds its record with ADR-0314's own store, so that a
> change to the line the viewer cannot read fails the gate.

> **Normative.** The tests pin §6: the bound address, the refused `Host` header and
> method, the response headers, and the record's directory left unchanged by serving it.

### 8. ADR-0314 §3:4

> **Normative.** ADR-0314 §3:4 is amended in the addition alone: the owner reads the record
> on the server with the server's own tools, this viewer among them.

ADR-0314 §3:1–§3:3 stand whole. The viewer is not in `ai_assistant`, so §3:1's "Nothing in
`ai_assistant` reads an entry back" still holds. It is no gateway route, command or export,
and no decision the system makes is conditioned on it. No body reaches a prompt, message,
memory, episode, story, trace or log by it (§3:2). The store is still handed to nothing
(§3:3), since the viewer reads the files, never the store. The page reaches the owner's
browser through the SSH session, as a file printed in a shell over SSH reaches the
owner's terminal.

### 9. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0314 §3:1–§3:3 | Nothing: the viewer is outside `ai_assistant`, and reads the files, not the store |
| ADR-0314 §3:4 | The server's own tools include this viewer (§8) |
| ADR-0314 §2:3, §6 | Nothing: the files stay owner-only, and the viewer reads the line and marker §6 writes |
| ADR-0004 §5 | Nothing: the viewer prints no entry's content |
| ADR-0004 §6, as ADR-0314 amends it | Nothing: the viewer is no surface of the assistant's, and the owner reads the files on the server |

> **Normative.** This numbered draft records its replacement on ADR-0314's status line and
> in a dated header note, atomically with this ADR under ADR-0070 and ADR-0082, preserving
> its ratified body. The replacement takes effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- The owner sees each activation as a flow: what ran when, for how long, over how many
  rounds, and where it needed them, read outside content, or could not finish.
- A day's use can be watched while it happens, and an activation's decisions are a click
  from its timeline.

**What it costs.**
- Any process on the server can reach a loopback port while the viewer runs. The viewer
  adds no authentication of its own, because the owner ruled the server's own login
  enough and the server's accounts are the owner's.
- The viewer reads only the bodies' keys as they are today. A source that changes its
  body can drop one of §3's summaries without failing the gate; the entry is still shown
  whole (§5:2).
- The owner copies the file to the server by hand, and again when it changes.

**What stays open.**
- Whether the learning design wants a viewer of its own over the same record.

## Alternatives considered

- **A gateway route or a hub command.** Rejected: ADR-0314 §3:1 forbids it, and the owner
  ruled the viewer separate from the hub.
- **A module inside `ai_assistant`.** Rejected: §3:1 forbids anything in `ai_assistant`
  reading an entry, and a module there could be imported by a subsystem.
- **A new top-level `tools/` directory.** Not chosen: nothing in the gate covers it yet,
  so lint, type and test configuration would have to grow to reach it, where `scripts/` is
  already covered.
- **A static page opened over copied files.** Rejected: it is not near-live, and the copies
  would leave the server and outlive the record's window.
- **A Unix socket in place of a loopback port.** Not chosen: the server's accounts are the
  owner's, so it narrows nothing that matters, and a port is what a one-line tunnel names.
- **`jq` and `less`, as today.** Kept, and not enough: they read one line at a time and do
  not show the flow.
