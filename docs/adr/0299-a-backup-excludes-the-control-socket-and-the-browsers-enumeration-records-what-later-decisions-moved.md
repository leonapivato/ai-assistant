# 299. A backup excludes the control socket, and the browser's enumeration records what later decisions moved

- Status: Accepted
- Date: 2026-10-05
- Scope: record-keeping the device-session and conversation work left: [#2721](https://github.com/leonapivato/ai-assistant/issues/2721) (the backup and `admin.sock`), [#2714](https://github.com/leonapivato/ai-assistant/issues/2714) (`stop_activation` and ADR-0177), and the two older gaps of the same shape on the same clause, [#2274](https://github.com/leonapivato/ai-assistant/issues/2274) (`cancel_read`) and [#2394](https://github.com/leonapivato/ai-assistant/issues/2394) (`standing_authorizations` and `revoke_authorization`).
- Authorization: the dispatcher, under the owner's standing direction that the overnight run may open issues and keep records straight. The dispatcher assigned 0299.
- **Decides no `core` surface.** No Protocol and no type changes. The implementation of §1 is a later lane, not this change; §2 and §3 record what the gateway already serves.
- **Partially supersedes** [ADR-0123](0123-a-backup-is-the-cold-data-directory-encrypted-to-a-passphrase-the-operator-holds.md) — **one scope.** **§3:2's exclusions, in the addition alone**: the backup also excludes `admin.sock` (§1 below). §3:3's rule that each excluded path comes from the module owning its name, §3:4's exact matching, §3:5's sidecars and every other clause stand, and bind the new entry as they bind the others.
- **Partially supersedes** [ADR-0177](0177-the-browsers-control-surface-is-thirty-operations-and-a-credential-is-entered-only-on-a-loopback-origin.md) — **one scope.** **§1:1's enumeration**, which gains `cancel_read`, `standing_authorizations`, `revoke_authorization` and `stop_activation`, and loses `converse_streaming` (§2 below). §1:5's class of caller-owned deadlines gains no member, and every other clause stands.
- **Partially supersedes** [ADR-0175](0175-a-browser-stream-is-a-response-body-on-the-request-the-browser-made-and-one-delivery-fans-out-to-every-open-stream.md) — **one scope.** **§3:4's *"Both turn entries reach the browser"***: of those two, `converse` does and `converse_streaming` does not (§3 below). ADR-0200's `converse_spoken` is not one of the two and is untouched. The rest of §3:4, and §3:1–§3:3 and §3:5, stand.

## Context

Decisions that are already merged left two kinds of record unwritten.

**A crashed hub's control socket makes the backup refuse.** ADR-0123 §1:2 has the
backup refuse a data directory holding an entry that is "neither a regular file, nor a
directory, nor one §3 excludes by name", and §3:2 excludes exactly `hub.lock` and
`hub.sock`. The hub also binds `<data_dir>/admin.sock`, the control socket
`ai-assistant-device` uses (`wire/address.py`, `admin_socket_path`). A hub that is
killed rather than drained leaves the file behind, so a backup taken before the next
clean start refuses with exit `78`. Until ADR-0298 this reached only a hub with a remote
listener. ADR-0298 §4:15 binds the socket "wherever the hub runs", so it now reaches
every hub (#2721). The refusal is safe: no bad artifact is written. But it is the exact
failure ADR-0123 §3 excluded `hub.sock` to prevent: "a socket left behind by a killed hub
would otherwise refuse every backup taken before the next clean start".

ADR-0123 §3:6 does not cover this case. Its forward clause binds a lane that writes into
the data directory "a file subject to a clause forbidding it to leave the device", and no
such clause covers `admin.sock`. The socket is process state, like `hub.sock`. So adding
it to the exclusions is a decision about ADR-0123 §3:2, not the discharge of an
obligation §3:6 set.

**ADR-0177 §1:1's closed enumeration no longer matches the browser's surface.** The
clause reads "A browser request resolves to calls on exactly these **thirty** operations
of the promoted engine surface and no others". Each later decision that moved it has
recorded the move on ADR-0177's `Status` line: ADR-0200, ADR-0250, ADR-0285 and ADR-0296.
Four decisions moved the gateway's surface without that record:

- **ADR-0244 §13:4** — *"The command line and the browser each render the pending read,
  collect the answer, and offer the cancellation act"* — so `cancel_read` reaches the
  browser (#2274).
- **ADR-0254 §11:7 and §20:1** — *"The surfaces this decision owes are a listing and a
  revocation"*, built by *"the interface adapters that render them"* — so
  `standing_authorizations` and `revoke_authorization` reach the browser (#2394).
- **ADR-0297 §6:4** — *"the command line and the gateway's stop control land last"* — with
  ADR-0295 §1:2's stop control beside "working…", so `stop_activation` reaches the
  browser (#2714).
- **ADR-0293 §11:2** replaces `converse_streaming`, and it has left `AssistantEngine`. The
  browser's streamed turn went with it, and that turn is what ADR-0175 §3:4 says reaches
  the browser.

The gateway follows those decisions. Its route table (`interfaces/gateway/server.py`,
`_ASSISTANT_PATHS`) maps a route to each of the four added operations and none to
`converse_streaming`. A reader holding only ADR-0177 §1:1 would call those four routes a
breach of a closed enumeration, and would build a `converse_streaming` route the hub
cannot answer. A
reader holding only ADR-0175 §3:4 would build a streamed turn. Under ADR-0070 §1's test
both readers act differently, so each record is a partial supersession.

**None of the four ADRs states the clause it moved.** ADR-0082 §1 requires the later
ADR to name the earlier ADR's clause "in its own text", because that is where the
judgement is reviewed. ADR-0244 and ADR-0254 do not mention ADR-0177. ADR-0293 §12:1 and
ADR-0297 §7:1 each say the ADR supersedes the ADRs in its header "and no clause of any
other ADR", and neither header names ADR-0177 or ADR-0175. A header line naming one of
them as the superseding ADR would record a classification that ADR never made, and that
two of them expressly deny. §4 explains why this ADR makes the records itself instead.

## Decision

### 1. The backup excludes `admin.sock`

> **Normative.** The backup excludes `admin.sock`, beside `hub.lock` and `hub.sock`.

> **Normative.** The backup tool obtains `admin.sock`'s path from `wire/address.py`,
> which owns the name, and no tool and no registry restates it.

It is excluded for the reason `hub.sock` is, and for no other. It is process state and
not data. A restored copy would grant nothing, because the hub unlinks a stale file before
it binds (`service/admin.py`, `AdminListener.start`). Naming it keeps ADR-0123 §1:2's
refusal of an entry that is not a regular file from refusing every backup of a crashed
hub. ADR-0123 §3:3 to §3:5 bind the new entry unchanged. It is matched exactly as a
data-directory-relative path, its sidecar names are excluded with it, and its owner is
the module that already defines the `hub.sock` name. The backup tool already reaches
that module.

**Excluding sockets by file type instead was considered and refused.** It would also
cover the next socket a lane adds, but only by changing ADR-0123 §1:2 for every entry
of that type. ADR-0123 keeps §1:2 a refusal list on purpose: an entry the backup has
never heard of is refused, so the operator sees it and nothing passes unnoticed.
Exclusion by name keeps that property. The cost is one decision per new socket, which
is this one.

Restore is untouched. A backup never carries `admin.sock`, so a restored directory
holds none until the hub binds it.

### 2. ADR-0177 §1:1's enumeration gains four operations and loses one

> **Normative.** ADR-0177 §1:1's enumeration gains `cancel_read`,
> `standing_authorizations`, `revoke_authorization` and `stop_activation`.

> **Normative.** ADR-0177 §1:1's enumeration loses `converse_streaming`.

The substance of each move is the decision cited in the Context. Here it is stated
against the clause that it moves. Each added operation is reached with the arguments
the promoted surface declares and no others, under ADR-0177 §1:4, which binds them as
it binds every other member.

**ADR-0177 §1:5's class of caller-owned deadlines gains no member.** None of the four
added operations takes a turn budget. The class's first member still names
`converse_streaming`, but it now governs `converse` and `resume` and nothing else. A
reader acting on it acts identically, so ADR-0250's precedent applies: §1:5 binds
entire. ADR-0177 §1:3, `learn` being unreached, also binds unchanged. ADR-0293 §11:5
retired `learn`, and ADR-0177's own header already reads the clause, without a count,
as the rule that a method stays outside the browser until an ADR puts it inside. That
rule stays true.

`follow_chat`, which the gateway serves at `POST /chat/follow`, needs no record here.
It is the change stream, which ADR-0296's record on ADR-0177 §1:1 already adds, and
ADR-0296 §5:1 is the clause that brings it to a browser.

`converse` stays in the enumeration. ADR-0293 §11:2 replaces it for the conversation,
but the gateway still serves it, for a turn carrying a reference. Its removal is
recorded when it lands, not before.

### 3. ADR-0175 §3:4: of its two turn entries, one reaches the browser

> **Normative.** Of the two turn entries ADR-0175 §3:4 names, `converse` reaches the
> browser and `converse_streaming` does not.

This is what remains of ADR-0175 §3:4's *"Both turn entries reach the browser"* once
`converse_streaming` has left the surface (ADR-0293 §11:2). It decides nothing about
any other entry: `converse_spoken`, which ADR-0200 put on the browser's surface as a
third entry, is not one of ADR-0175's two and still reaches the browser exactly as
ADR-0200 decides. The rest of §3:4 binds as
written: the gateway never substitutes one entry for another, and *"a turn the browser
asked for whole is answered by `converse` and never from a stream"*. §3:1 to §3:3 govern
a streamed turn the browser no longer reaches, and none of them becomes false. §3:5's
closing of *"every engine stream it opened"* binds every engine stream the gateway still
opens. This ADR decides nothing about how pieces of a message reach a device (ADR-0293
§6, ADR-0296).

### 4. Why the records are this ADR's, and not header lines naming the four

This ADR takes the supersession itself rather than writing header lines that name
ADR-0244, ADR-0254, ADR-0293 and ADR-0297, for three reasons.

- **ADR-0082 §1 puts the clause-level judgement in the later ADR's text.** None of the
  four makes it, so the only way to make it in reviewed text is in a new ADR.
- **A pair names its target.** ADR-0070 §4 reads every `ADR-NNNN` after the leading
  `Partially superseded by` as the ADR that replaced the scope. A pair naming ADR-0293
  would point the reader at an ADR whose §12:1 says it replaced no clause of ADR-0177.
  A pair naming ADR-0299 points at text that states the clause and applies the test.
- **No sentence of the four becomes false.** ADR-0293 §12:1 and ADR-0297 §7:1 state
  what those ADRs supersede, and that stays true. ADR-0244 and ADR-0254 are silent on
  ADR-0177. So under ADR-0082 §1 nothing is recorded on any of the four.

Whether ADR-0293 §12:1 and ADR-0297 §7:1 should have named ADR-0177 is not reopened.
After this ADR, ADR-0177's and ADR-0175's records are accurate either way.

### 5. What the check found not owed

ADR-0293 retired `learn`, `converse_streaming` and `receive_streaming`. Every ADR clause
naming one of them was read against ADR-0082 §1's test. A record is owed only where the
clause states that the member is reached or served, so that a reader would build it. A
clause that names a retired member as one member of a set it governs (the passes a stage
runs on, the outcomes a type carries, the seams a trace attributes) is not falsified by
the member's absence. It now governs one member fewer, and a reader acting on it acts
identically.

- **Already recorded by ADR-0293:** ADR-0022 §1 (`learn`), ADR-0085 (the surface),
  ADR-0173 §4 (`converse_streaming`), and ADR-0274 §2–§6 for a typed text input. That
  last scope covers `receive_streaming` whole, because its one admitted combination is
  the text conversation (ADR-0274 §4).
- **Not owed:** ADR-0177 §1:3 and §1:5, and ADR-0175 §3:1–§3:3 and §3:5 (above); ADR-0175
  §6:1, which ADR-0177 already superseded, so a reader following it reaches this record
  through ADR-0070 §4's walk; ADR-0197 §1:4, ADR-0228, ADR-0242, ADR-0244 §9, ADR-0250
  §11 and §15, ADR-0251 §5 and ADR-0276 §5:1, each naming `converse_streaming` among the
  passes or outcomes it governs; ADR-0120 §3:2's seam sets, ADR-0122 and ADR-0028, each
  naming `learn` among the seams it governs; ADR-0073 §6 and ADR-0078, which name `learn`
  as the correction path by reference to ADR-0022's loop, whose route ADR-0293 records
  at its source, and whose own decisions (inspection adds no second correction path, and
  a correction destroys nothing) stand; ADR-0285 §9:1, which says what ADR-0285 itself
  leaves as it was, and stays true of ADR-0285; and ADR-0298 §5:1's table, which names
  all three in its legacy-turn row and still classifies every method on the surface in
  exactly one row.

### 6. Relationship to earlier decisions

> **Normative.** This ADR supersedes ADR-0123, ADR-0177 and ADR-0175 in the scopes its
> header names, and no clause of any other ADR.

> **Normative.** This numbered draft records its replacements on the status line and in
> a dated header note of each ADR it supersedes in part, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies, and each replacement takes
> effect on this ADR's ratification.

| Earlier decision | Where it goes |
| --- | --- |
| ADR-0123 §3:2's exclusions | §1 (`admin.sock` added) |
| ADR-0177 §1:1's enumeration | §2 (four added, `converse_streaming` removed) |
| ADR-0175 §3:4's two turn entries | §3 (`converse` alone of the two) |

## Consequences

**What becomes clear.** A backup of a crashed hub's data directory runs without the
operator first removing a socket. ADR-0177's enumeration, read together with its
`Status` line, carries the five moves that were missing from it. #2274, #2394 and
#2714 are discharged by the record. #2721 is discharged by §1's decision and closes when the
implementing lane lands.

**What it costs.** A later socket in the data directory needs its own decision on this
clause, as `admin.sock` did. This is ADR-0123's refusal-list trade, kept on purpose
(§1).

**What follows from it.**

1. **The backup lane** (`service/backup.py`): add `admin.sock`'s name, read from
   `wire/address.py`, to `_excluded_paths`, with a test that a backup of a data
   directory holding a stale `admin.sock` succeeds and its artifact carries no such
   entry.
2. Nothing for the gateway: its route table already matches §2 and §3.
