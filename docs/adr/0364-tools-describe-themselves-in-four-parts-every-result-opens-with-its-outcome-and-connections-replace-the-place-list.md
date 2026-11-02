# 364. Tools describe themselves in four parts, every result opens with its outcome, and connections replace the place list

- Status: Accepted
- Date: 2026-11-01
- Scope: milestone 18's last design piece, the walk of planning's instruction and of every tool's description. It decides the instruction's changed sections (§2); the Connections section, which replaces the place list (§3); people's `P` labels (§4); the shape of a description (§5) and of a result (§6); the effects line's template (§7); the renames, and how stored records under the old names keep reading (§8); the message tools (§9); approvals (§10); scheduled work (§11); the look-ups (§12); the person model's calls (§13); and the lanes (§14).
- Dependency: [ADR-0356](0356-the-system-briefs-planning-in-one-continuing-exchange-plannings-text-is-its-notes-and-an-episode-is-shown-by-its-short-view.md), [ADR-0357](0357-messages-are-tools-by-modality-planning-chooses-and-tools-carry-out-and-a-rule-about-one-tool-sits-in-its-description.md) and [ADR-0358](0358-planning-keeps-memory-only-on-purpose-a-matter-that-has-changed-is-tidied-in-the-background-and-planning-can-search-past-episodes-read-one-whole-and-read-its-origins-older-history.md), whose exchange, tools and look-ups this decision reshapes; [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md) and [ADR-0362](0362-a-ticket-runs-the-person-models-calls-and-the-task-schedulers-and-a-cards-edit-and-a-taps-answer-need-no-claim-of-the-lines.md), whose approvals it reshapes; and [ADR-0350](0350-every-spawn-is-a-scheduled-task-written-into-the-task-scheduler-whose-sensor-starts-it-when-it-comes-due-and-the-task-manager-is-the-one-way-in-from-outside.md), whose place list it replaces. All Accepted, as their status lines leave them.
- Authorization: the owner walked planning's instruction and all 32 tool descriptions with the coordinator on 2026-11-01 and ruled as they went. On people labels, verbatim: "record it, but build our current stuff around it" (§4). The words of the instruction and of every description are the coordinator's agreed words, routed to the build lane (ADR-0357 §7:5); this decision quotes none of them. The coordinator assigned 0364 and ratifies it once its reviews are green. Where a ruling left a point open, this decision says what it decided, in §15.
- **Contract-surface decision, and a breaking change under golden rule 5.** No Protocol changes. Three `core` types do: `CallResult` gains `outcome`, so that `models/` can flag a failed call to the provider (§6:4); `LabelKind` gains `PERSON`, the `P` label (§4:1); and `RequestedCall` gains `looking_for`, so a request keeps it (§10:6). `PROTOCOL_VERSION` advances where the build lane finds any of them crossing the wire (§14:3).
- **Partially supersedes**, in the clauses §16's first table names: ADR-0260, ADR-0306, ADR-0307, ADR-0338, ADR-0349, ADR-0350, ADR-0356, ADR-0357, ADR-0358 and ADR-0361.

## Context

ADR-0356 and ADR-0357 moved every rule about one tool into that tool's description and left the
words to the coordinator's walk with the owner (ADR-0357 §7:5). The walk happened on 2026-11-01.
It went further than words: the owner ruled on what the context shows, what every result looks
like, what a description holds, the tools' names, and several behaviours the old words hid.

Four things the walk found. The briefing's place list shows where a message may go but not what
the system is connected to, so planning cannot say "your email account" or find a conversation it
was not shown. Results come back in a different shape from each tool, and a failed call looks to
the provider like a success. The names grew one at a time and read unevenly (`text`, `spawn`,
`follow_up`, `forecast_read`). And several descriptions promised what code does not do, such as a
yes to a question running the person model's calls (#3592), or a task's work stopping running work
(#3466, #3559).

**Words.** A **connection** is something the system is connected to: a conversation, the line's
chat, the schedule, the approvals, an email account, the search account, the forecast provider. A
channel with many places, such as the hub chat, is a **many-place connection**, and each of its
places is a connection of its own. The **work** is the activation planning plans (ADR-0356). The
**coordinator's agreed words** are the instruction and the 32 descriptions as the owner agreed them
in the walk.

In this document a bare section reference, such as §6:2, is to this decision's own clauses.

## Decision

We will ship the agreed instruction and descriptions, show planning its connections in place of the
place list, give every tool one result shape with failed calls flagged to the provider, generate
each description's effects line from the tool's declaration, and rename the tools so each is a verb
and what it acts on.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires, adversarial and architecture, have returned green on one tree and
> the coordinator, under the owner's delegation, ratifies it. An assigned number or a green review
> alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule 5,
> ADR-0015 §5).

> **Normative.** Every earlier clause this decision replaces is replaced for an activation the
> phases plan, and for no other.

### 2. The instruction

> **Normative.** The default `src/ai_assistant/orchestration/planning.txt` becomes the coordinator's
> agreed words for the instruction, byte for byte, shipped by the build lane (§14:1) as ADR-0356's P3
> shipped the last one, with no change but what a ratified clause requires. This replaces ADR-0356
> §10:1's text for this version of it.

> **Normative.** The instruction's changed sections are these, and only these: Knowledge gains a
> Connections bullet after the situation and before stimulus origin knowledge, and its situation
> bullet names only the time now and the person's last stimulus; the layout paragraph says that an
> item's `where` is its connection's label, and the stimulus's its origin; acting in rounds defines
> the four outcomes of §6:1; and short-term memory names its items as episodes.

> **Normative.** The list beside `PLANNING_PROMPT` of what the instruction must say (ADR-0356
> §10:2) also names §2:2 and §6:7 of this decision. This adds to ADR-0356 §10:2's list.

### 3. Connections

> **Normative.** The briefing gains a section, **Connections**, under Knowledge, after the
> situation and before stimulus origin knowledge, on every round of every work (ADR-0356 §4:1). It
> replaces the place list wherever it rendered (ADR-0350 §5:10, ADR-0357 §2:13), for every work,
> not only one offered spawn. It is added to ADR-0356 §3:1's sections, and ADR-0356 §3:2's table
> gains its row, the situation's row rendering the time now and the person's last stimulus alone.

> **Normative.** It lists every connection the system has, the system's own channels among them
> (the schedule, the approvals), so that every origin is a connection. An entry is a connection with
> one place, or one place of a many-place connection; a many-place connection's entries are grouped
> under it, and the grouping carries no label.

> **Normative.** Each entry carries: its `L` label; what it is, from its kind's declaration,
> written once in code (`orchestration/channel_kinds.py`, or its account kind's beside it); who it
> reaches, by `P` label (§4); what the system can do with it, sense it, look things up in it or act
> in it, with its limits, such as that it takes text messages or takes no message; and its state,
> only where that is not normal, such as disconnected, pending or gone. This replaces ADR-0350
> §5:12, and ADR-0350 §5:13 now reads of any connection: an `L` label names one, and a call naming
> a label the work was not shown is still refused whole.

> **Normative.** No entry shows a connection's contents, its history, a credential or an
> identifier, an account's own address among them.

> **Normative.** A many-place connection shows its three most recent places, three being a
> composition-root constant. The section also shows the origin, every single-place connection, and
> every connection an item elsewhere in the briefing names by `where`, so every `L` label the
> briefing shows names an entry in it.

> **Normative.** The composition root hands orchestration the account connections it registers,
> each with its kind, as orchestration's own value. No `core` type gains a kind for an account, and
> `ConnectedAccount` is unchanged (ADR-0151 §18).

> **Normative.** A new look-up, `search_connections`, takes a `query` and a `page` and finds the
> connections the section does not show, best first, a page at a time, each shown as the section
> shows an entry and taking its `L` label the first time it is shown. It is a read of the system's
> own records under ADR-0358 §6's rules, the pass's audience among them.

> **Normative.** `search_connections` matches its query against what each connection's entry would
> show, the place's own name where its record has one, and the text of a place whose transcript the
> hub hosts, read through the stores' existing reads. It shows no text it matched against. A store
> query it would need beyond those reads is a Protocol change and takes its own decision first.

> **Normative.** The stimulus's tag carries `where`, its origin's `L` label, and each joined input
> carries its own. Every other item's `where` is its connection's `L` label. This replaces, in what
> ADR-0356 §3:3 brings into planning's briefing alone, ADR-0353 §4:4's `origin` attribute and its
> naming by description.

> **Normative.** For a work the Task Scheduler started, each of its task's suggested connections
> carries `suggested="yes"`.

> **Normative.** A connection that joins mid-work, such as the origin of an input taken by a take,
> is shown in the news under its `L` label, as ADR-0361 §7:3 shows a taken input's place. Nothing
> already sent is re-rendered (ADR-0356 §5:6).

### 4. People's labels

> **Normative.** Planning names a person by a label of a new kind, `P1`, `P2`…, in `LabelKind` as
> `PERSON`. `P1` is the owner, a stable label over ADR-0345 §2:5's identifier, the same in every
> work.

> **Normative.** In planning's briefing a tag's `from` names a person by their `P` label, and the
> person block in always in mind says who each one is. This replaces, in what ADR-0356 §3:3 brings
> into planning's briefing alone, ADR-0353 §4:1's naming by name; understanding's is unchanged.

> **Normative.** A connection's entry names who it reaches by `P` label. An account that sends to
> the addresses a call names, such as an email account, says so in their place. Every other
> connection that reaches anyone today reaches the owner alone (ADR-0361 §7:4).

> **Normative.** No lane builds `G` labels for named groups, or understanding resolving who a
> mention means, under this decision. Both are direction only, and each takes its own decision.

### 5. What a description holds

> **Normative.** Every description has four parts, in this order and with no labels, each left out
> where it does not apply: what the tool does; its rules; what comes back, as its actual structure;
> and its effects (§7). This adds to ADR-0357 §7: the rules its §7:2 table moves land in the
> rules part.

> **Normative.** Each argument has a type, a default and a description, and an optional argument's
> description says what happens when it is left out.

> **Normative.** An example appears only where a format needs one, and its values are placeholders
> that the call's checks would refuse if a copy were sent.

> **Normative.** Descriptions use the instruction's words throughout: stimulus, work, episode,
> matter, connection, and "the person this work is for" where one is meant.

### 6. One result shape

> **Normative.** Every tool's result opens with its outcome, one of done, not done, unknown or
> refused; then, with any but done, why; then the tool's own fields. The one exception is a
> tidy-up that started, whose result says only that, as ADR-0356 §5:3 has it.

> **Normative.** A call stopped before its tool ran, by planning's own check, by authorizing or by
> the repeat backstop, comes back refused. A call whose tool ran, its own checks included, and did
> not do it, comes back not done (ADR-0357 §6:1). An outcome that cannot be established is unknown
> (ADR-0357 §6:2).

> **Normative.** A call needing approval comes back refused, its why saying to ask with
> `request_approval`, and a call the policy denies comes back refused, with its reason. This replaces
> ADR-0306 §4:8's *needing you* and §4:9's *not done*, ADR-0357 §6:3's *goes back as needing them*
> and ADR-0361 §2:4's result, in the outcome planning is shown alone. `CallOutcomeKind` keeps its members, and a recorded `needs_you` is shown
> as refused.

> **Normative.** `CallResult` gains `outcome: CallOutcomeKind | None`, defaulting to `None`: the
> outcome planning is shown, and `None` where it shows none. Its validator refuses `needs_you`.

> **Normative.** Where the provider supports it, `models/` flags a result whose outcome is not done
> or refused as an error, as Anthropic's `is_error`. An unknown is not flagged, and a result with no
> outcome is not.

> **Normative.** The flag is set in `models/` alone, and never by handing pydantic-ai a
> `RetryPromptPart`, whose wording would tell the model to retry.

> **Normative.** The instruction defines the four outcomes once (§2:2). No description restates
> them.

> **Normative.** A result need not repeat a default that its argument's description names. This
> replaces ADR-0357 §5:4's *the result says what was used for each one*, where the tool used that
> default.

### 7. The effects line

> **Normative.** The effects part of every description is generated from the tool's declaration,
> and is never written by hand once lane T2 (§14:2) builds the generator. This replaces ADR-0357
> §5:9's line, which said only whether a call is safe to repeat.

> **Normative.** What it changes: a tool whose `effect` is the world says it acts outside the
> system; one whose effect is the system's own records and whose `writes` is not empty says it
> changes only the system's own records; any other says it changes nothing, and adds that what it
> sends leaves the system where its declaration says `leaves_hub`.

> **Normative.** Undoing: `REVERSIBLE` says it can be undone, `IRREVERSIBLE` says it cannot, and
> `RECOVERABLE` says nothing, since no one phrase fits every tool declared so. A tool that changes
> nothing says nothing of undoing.

> **Normative.** Repeating: the line says whether the call is safe to repeat, from
> `safe_to_repeat`, except for a tool that changes nothing.

> **Normative.** Approval: where a rule always asks for approval of every call to the tool, the line
> says it always needs approval first. The generator and authorizing read that from one register
> in code, the one `_needs_you_by_rule` reads today, moved where both can import it without one
> phase module importing another (ADR-0309 §2:3), so the two cannot disagree. Today that is
> `send_email` and the person model's three calls.

> **Normative.** `run_approved` takes no generated line: its effects are its ticket's call's, which
> its description says.

> **Normative.** `request_approval` stays declared `RECOVERABLE`, never `IRREVERSIBLE`: the default
> policy confirms an irreversible effect, and a request never itself needs approval (ADR-0361 §2:9).

> **Normative.** `spawn_task` is declared `REVERSIBLE`, since `cancel_task` undoes it while it is
> pending, as ADR-0016 reads a calendar event its tool can delete.

### 8. Names

> **Normative.** The tools are renamed as the table below gives. Each keeps its declaration's other
> fields, except as this decision changes them.

| Was | Is |
| --- | --- |
| `text`, `email` | `send_text`, `send_email` |
| `spawn` | `spawn_task` |
| `set_profile`, `pin`, `unpin` | `set_profile_field`, `pin_memory`, `unpin_memory` |
| `search_memory`, `web_search`, `forecast_read` | `search_memories`, `search_web`, `read_forecast` |
| `read_story`, `read_older_history`, `follow_up` | `read_matter`, `read_origin_history`, `reread_result` |
| `stop_activation`, `remember` | `stop_work`, `remember_fact` |
| `start_story`, `note_story`, `link_story`, `unlink_story`, `move_story` | `start_matter`, `note_matter`, `add_to_matter`, `remove_from_matter`, `move_to_matter` |
| `merge_stories`, `split_story`, `group_stories`, `tidy_story` | `merge_matters`, `split_matter`, `group_matters`, `tidy_matter` |
| `look_up_activation` | folded into `read_episode` (§8:3) |

> **Normative.** The arguments are renamed as this table gives:

| Tool | Was | Is |
| --- | --- | --- |
| `send_text` | `via` | `connection` (§9:1) |
| `send_email` | `from`, `assistant` or `user` | `from`, an `L` label (§9:11) |
| `spawn_task` | `places` | `connections` |
| `run_approved` | `label` | `ticket` |
| `request_approval` | `call.capability` | `call.tool` |
| `stop_work` | `activation` | `work` |
| the matter calls | `story`, `stories` | `matter`, `matters` |
| `add_to_matter`, `remove_from_matter` | `member_story`, `member_episode` | `member`, an `E` or `S` label; left out, this work |
| `remember_fact` | `rests_on_input`, `rests_on_user_messages`, `rests_on_assistant_messages` | `rests_on_this_stimulus`, `rests_on_stimuli`, `rests_on_responses` |

> **Normative.** `read_episode` also reads an episode still running, as ADR-0349 §6's peer view
> shows it, by any `E` label the work was shown it under, and `look_up_activation` is no longer
> offered. This replaces ADR-0349 §6:1's and §6:5's separate look-up and ADR-0358 §10:2's *for an
> episode still open it says the work is still running*.

> **Normative.** A name is renamed where planning sees it: the capability, its arguments, its
> description and every result and record shown to planning. No `core` enumeration member and no
> `Settings` field is renamed, `ReadKind` and the `send_email_*` and `web_search_*` settings among
> them.

> **Normative.** No stored record is rewritten. Tickets, requests, effect records, the audit trail,
> plan records and episodes keep the names they were written under, and code reads each old name
> through one table of the renames above, arguments included. This replaces ADR-0361 §2:1's *as a
> capability name*, which `call.tool` now names, and ADR-0361 §7:3's `via`, which is `connection`.

> **Normative.** A waiting request or an unused ticket whose call names an old capability is read
> as the new tool's call, its arguments translated by the table, where the translation sends what
> the old call would have sent: an `email` `from` `user` reads as the person's one email account,
> and `exact` reads as the words wrapped whole (§9:6), any tag they already hold escaped first
> (§9:8), which are sent unchanged today either way (§9:9). The request's `RequestedCall` is read
> with the new tool's declaration and the translated values, and rebound as ADR-0321 §4:2 rebinds.
> One the translation cannot carry, such as a recipient that is not an address, is void, and its
> card and panel say so.

> **Normative.** A grant or authorization that names a tool by its declaration's value covers no
> call to a tool whose declaration changed, as after any description change (ADR-0254 §3:1). This
> decision adds no carry-over, and the deploy names any grant the owner holds that it ends.

> **Normative.** A rename is recorded on the decision that chose the name: ADR-0357's message tools
> (§2:1) and its §7:2 table, and ADR-0338 §8:4's three calls. Every other clause naming a tool by an
> old name binds the same capability under its new name, and its decision is otherwise unchanged
> (ADR-0082 §1).

### 9. The message tools

> **Normative.** `send_text` takes `connection`, required, and `words`, required, and nothing else.
> `to` goes: who a message reaches is its connection's (§3:3), and planning weighs it from there.
> This replaces ADR-0357 §2:2–§2:5's `to` and `via`.

> **Normative.** `connection` is checked by its pattern, an `L` label, with no `enum`, so the offered
> tools stay identical across works (ADR-0356 §4:3). Code refuses a connection that takes no text
> message, and one the work was not shown.

> **Normative.** A work may send a text into any connection it was shown that takes one. This lifts
> the one-place rule of ADR-0306 §4:7, ADR-0356 §7:7 and §7:10 and ADR-0350 §5:11, except where
> §9:4 keeps a list. Code checks no audience yet: every connection a text can go into reaches the
> owner alone (ADR-0361 §7:4).

> **Normative.** A work the Task Scheduler started, and an approval's work, still send only where
> ADR-0350 §6:7, ADR-0361 §6:7 and ADR-0361 §7:3 let them: the connections their task or request
> suggests, the line's chat where the line is connected, and the origin of each input they took by a
> take, where it takes a text. Their inputs carry no person's authority, and this decision widens
> nothing for them.

> **Normative.** `send_text`'s result is its outcome alone (§6:1). Its call's episode entry still
> holds what was sent, where and how (ADR-0357 §3:4). This replaces ADR-0357 §3:1 and §3:2 in what
> the result shows planning, for both message tools.

> **Normative.** `exact` goes from both message tools. Words mark a part to be sent exactly as
> written with an `<exact>` tag and its closing tag, and a message that must go out as written is
> wrapped whole. This replaces ADR-0357 §4:2 and §4:3's `exact`.

> **Normative.** Code checks that each marked part appears verbatim in what is to be sent, and
> where one does not, sends planning's words unchanged instead. It removes the tags either way.

> **Normative.** An unclosed tag, a tag opened inside a marked part, or a closing tag with none open
> comes back not done. A backslash before an opening or a closing tag sends that tag as literal
> text, and two backslashes before a tag send one backslash and leave the tag a tag.

> **Normative.** Until the wording step is built (ADR-0357 §4:5), words are sent as written, with
> the tags removed.

> **Normative.** No message tool's description says that the system never claims to be human. The
> owner holds it as a principle, not a rule about one tool, and where it is said is open
> ([#3600](https://github.com/leonapivato/ai-assistant/issues/3600)). This replaces ADR-0356 §10:6's
> second sentence and ADR-0357 §7:2's row for it.

> **Normative.** `send_email`'s `from` is required, an `L` label naming an email account
> connection the work was shown. Code refuses any other. The account's entry says whose it is. This
> replaces ADR-0357 §2:10.

> **Normative.** Every email needs approval, from whichever account, by rule. This makes ADR-0357
> §2:11 unconditional, as ADR-0021 §5's floor already has it.

> **Normative.** Every recipient is an email address. A recipient that is not one comes back not
> done, saying an address is needed. This replaces ADR-0357 §2:6's *a person as planning was shown
> them* and retires §2:7.

> **Normative.** `attachments` goes until a decision gives a file a label, a holder and a transport
> ([#3598](https://github.com/leonapivato/ai-assistant/issues/3598)). This retires ADR-0357 §2:8 and
> §2:6's `attachments`.

### 10. Approvals

> **Normative.** `request_approval`'s result says, with done, how its card went, one of three: sent;
> not sent, so the approvals panel alone shows it; or unknown; and when the request expires. This
> replaces ADR-0361 §2:7's result.

> **Normative.** `looking_for`, where the requested call takes one, stays in the requested call. The
> request records it beside the call's deliberate-repeat mark, which adds to ADR-0361 §2:6; the
> card never shows it; and it goes to the digest when the ticket's call runs (§10:6).

> **Normative.** `run_approved` takes `ticket`, required, and nothing else. This replaces ADR-0361
> §5:2's argument name; §5:2's one argument stands.

> **Normative.** A `run_approved` that its checks refuse (ADR-0361 §5:3) comes back refused, under
> §6:2, not not done.

> **Normative.** `looking_for` never changes what a call does, since the hub strips it before the
> tool runs (ADR-0306 §2:10), so it is never the person's to approve. A new question of a result is
> `reread_result`'s.

> **Normative.** `RequestedCall` gains `looking_for: NonBlankEncodableText | None`, defaulting to
> `None` and left out of a dump where it is `None`, so a request written before it reads and is
> stored as it was. It is no part of `values`, of the call a ticket runs, of `RequestedCall.request`
> or of `same_call`'s sameness, and no card or panel shows it.

### 11. Scheduled work

> **Normative.** `spawn_task`'s description says that a task's work carries no one's authority: it
> cannot stop running work, and setting a rule or changing a task it did not spawn needs approval
> ([#3466](https://github.com/leonapivato/ai-assistant/issues/3466),
> [#3559](https://github.com/leonapivato/ai-assistant/issues/3559)). The owner took this rule as
> drafted, to be checked again in a later run. It describes what code already enforces, and changes
> no check.

> **Normative.** Its description says that `instruction` says what to do and not where
> ([#3445](https://github.com/leonapivato/ai-assistant/issues/3445)), and that its work speaks only
> in the connections it suggests ([#3450](https://github.com/leonapivato/ai-assistant/issues/3450)).

> **Normative.** A spawn may suggest any connection the work was shown that takes a text message,
> and one naming a connection that takes none is refused whole, with the reason. A spawn from a
> work that keeps a list (§9:4) may suggest only connections on that list, so no task widens where
> such a work may speak. This replaces ADR-0350 §5:6's *only places on its own activation's place
> list*, outside such a work.

> **Normative.** Its result, with done, is the task's `T` label and its read-back alone.

### 12. Look-ups

> **Normative.** `search_web`'s and `read_forecast`'s `origin` is a system-supplied argument
> (ADR-0254 §3:2), filled by the hub and absent from the schema planning is offered. It keeps its
> destination keyword, so the binding and every ruling still range over it.

> **Normative.** `read_forecast`'s `latitude` and `longitude` are planning's: optional, both or
> neither, and, left out, the configured place's. Both-or-neither is the tool's check when called
> (ADR-0357 §5:6). This replaces ADR-0260 §3:2's *none is accepted from one* and §3:4's *names
> nothing at all*, for the two coordinates alone.

> **Normative.** The coordinates are what the call sends, not where it goes: it still reaches only
> the configured provider, and the configured place's coordinates are still never rendered to
> planning. A call carrying coordinates leaves the hub, so the outside-content stand-in (ADR-0306
> §4:4) and the policy rule on it as on any call.

> **Normative.** This decision does not decide whether the forecast keeps its digest
> ([#3599](https://github.com/leonapivato/ai-assistant/issues/3599)).

### 13. The person model's calls

> **Normative.** `set_profile_field`, `pin_memory` and `unpin_memory` are renamed as §8:1 gives and
> carry the always-approval line of §7:5
> ([#3592](https://github.com/leonapivato/ai-assistant/issues/3592)). Their redesign, whose profile
> and whose pins once people have labels, waits for the people-labels work.

### 14. Delivery

> **Normative.** One build lane, B, ships the instruction, every description, the renames,
> Connections and `search_connections`, the result shape and the provider flag. It may touch `core`
> for §4:1's `LabelKind`, §6:4's `CallResult` and §10:6's `RequestedCall`, `testing`, `models/tool_calling.py`,
> `orchestration`, `tools/send_email.py`, `tools/web_search.py`, `tools/forecast.py` and the
> registration that names them, `app/` for §3:5's constant and §3:6's account connections,
> `interfaces/` and `scripts/` where they show a capability's name, for the name alone,
> `prompt_cases/`, and their tests.

> **Normative.** Then lane T2 builds the effects generator (§7) and a test that each offered
> description's effects line equals what the generator writes from its declaration. It may touch
> the module that builds the offered tools, each description's effects line wherever it is
> declared, the register §7:5 names and its two readers, and their tests. The bytes the model is offered do not change under it.

> **Normative.** Where a type this decision changes crosses the wire, B advances
> `PROTOCOL_VERSION`, as ADR-0356 §13 did.

> **Normative.** B's tests include: a not done and a refused result are flagged to an Anthropic
> model as errors and an unknown is not, with no retry wording; a call needing approval comes back
> refused, saying to ask with `request_approval`; a `send_text` into a connection that takes no text,
> or one the work was not shown, is refused; a task's work sending outside its suggested connections
> and the line is refused; an exact part reworded away sends planning's words, and an unclosed tag
> comes back not done; an email `from` a label that is no email account is refused, and every email
> needs approval; a waiting `email` request from before the build runs as the `send_email` it
> translates to; an approved search's `looking_for` survives a restart and reaches its digest when
> the ticket runs; a task's work may reply into the origin of an input it took; a literal tag sent
> escaped arrives as written; Connections shows the origin, every single-place connection and three places of a
> many-place one, and no address; `search_connections` finds an unshown conversation and labels it;
> and the offered tools stay identical across two works. These replace ADR-0357 §10:1's tests of
> `exact` and of an email from the person's address.

> **Normative.** ADR-0137 §1 allows one build lane: its new machinery is orchestration's, and what
> it does in `core`, `models`, `tools`, `app`, `interfaces` and `scripts` is adaptation. Where B
> finds the provider flag is more than adaptation, the seam is `CallResult.outcome`, and the flag
> becomes a `models` lane after B.

> **Normative.** After T2 merges, the prompt suite runs on the shipped instruction and descriptions
> (ADR-0337), then one deploy carries B and T2 together, then the coordinator's QA reads them
> against milestone 18's acceptance issue,
> [#3530](https://github.com/leonapivato/ai-assistant/issues/3530).

### 15. What this decision decided where the rulings left a point open

Each is this decision's, not an owner ruling:

- **Connections' entries and labels** (§3:2, §3:5). An `L` label names a place, since a message goes
  into one, so a many-place connection groups its places unlabelled, as ADR-0350 §5:13 left channel
  headings. Every connection an item names by `where` is shown, so no label points at nothing.
- **Where the account kinds come from** (§3:6): the composition root, so `ConnectedAccount` and its
  Protocols stay as they are.
- **What `search_connections` matches** (§3:8): what the hub already holds, through existing reads,
  so it needs no Protocol change.
- **`from` names a person by `P` label** (§4:2), since a label shown in one place is pointed at
  elsewhere (ADR-0356 §3:2).
- **Which outcome is which** (§6:2–§6:3): refused for a stop before the tool runs, a policy deny
  among them, matching the instruction's definitions.
- **`CallResult` carries the outcome, not a flag** (§6:4): it records a fact, and `models/` maps it
  to whatever field its provider has.
- **Undoing is silent where nothing changes** (§7:3), as the agreed words have it.
- **Stored calls translate where nothing sent would differ** (§8:6), and are void otherwise.
- **A task's work and an approval's work keep their lists** (§9:4): their inputs carry no
  authority, and #3450's rule needs it.
- **A spawn may not suggest a connection that takes no text** (§11:3): its work could never speak
  there.

### 16. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0356 | §3:1's sections, in the addition alone: Connections; §3:2's table, its situation row: the time and the last stimulus alone, and a Connections row; §3:3, in planning's briefing alone: `where` by `L` label and `from` by `P` label; §7:7 and §7:10's second sentence: any shown connection that takes text; §10:1's text, for this version; §10:2's list, in the addition alone; §10:6's second sentence | §2, §3, §4:2, §9:3, §9:10 |
| ADR-0357 | §2:1's and §7:2's names; §2:2–§2:5: `send_text` takes `connection` and `words`; §2:6's person recipient and `attachments`; §2:7 and §2:8, retired; §2:10; §2:11, made unconditional; §2:13; §3:1 and §3:2, in what the result shows planning; §4:2 and §4:3's `exact`; §5:4, where the tool used the default its argument's description names; §5:9's line; §6:3's *goes back as needing them*; §7:2's human row; §10:1's `exact` and email tests | §5, §6, §7, §8, §9 |
| ADR-0350 | §5:6's *only places on its own place list*, outside a work that keeps a list; §5:10, whole; §5:11, outside a task's work; §5:12's description: an entry says what the system can do with it; §5:13, in that an `L` label names any connection | §3, §9:3, §11:3 |
| ADR-0306 | §4:7's one place; §4:8's *needing you* and §4:9's *not done*, in the outcome planning is shown | §6:3, §9:3 |
| ADR-0307 | §5:1's label kinds, in the addition alone: `P` | §4:1 |
| ADR-0361 | §2:1's `capability`: `tool`; §2:4's result: refused; §2:6, in the addition alone: `looking_for`; §2:7's result; §5:2's argument name; §5:3's *not done*: refused; §7:3's `via`: `connection` | §6:3, §8:2, §10 |
| ADR-0349 | §6:1 and §6:5's separate look-up: `read_episode` | §8:3 |
| ADR-0358 | §10:2's *for an episode still open it says the work is still running* | §8:3 |
| ADR-0338 | §8:4's names | §8:1, §13 |
| ADR-0260 | §3:2's *none is accepted from one* and §3:4's *names nothing at all*, for the coordinates alone | §12:2 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0021 §5 | Nothing: its floor already confirms every email, which §9:12 now states |
| ADR-0254 §3 | Nothing: §12:1 applies `system_supplied` as it decides |
| ADR-0345 §2:5 | Nothing: `P1` is a label over its identifier |
| ADR-0350 §6:7, ADR-0361 §6:7 | Nothing: a task's work and an approval's work keep their lists |
| ADR-0353 | Nothing: §3:9 and §4:2 change what ADR-0356 §3:3 brings into planning's briefing, and understanding's is unchanged |
| ADR-0356 §5:3 | Nothing: a tidy-up that started still says only that |
| ADR-0340, ADR-0352, ADR-0362 | Nothing: §11:1 describes what their checks already do |

> **Normative.** This numbered draft records its replacements on the status lines and in a dated
> header note of ADR-0260, ADR-0306, ADR-0307, ADR-0338, ADR-0349, ADR-0350, ADR-0356, ADR-0357,
> ADR-0358 and ADR-0361, atomically with this ADR under ADR-0070 and ADR-0082, preserving their
> ratified bodies. The replacements take effect on this ADR's ratification.

## Consequences

- Planning sees what it is connected to and what it can do with each, and can find the rest, so a
  message can go wherever the person would expect.
- A failed call reads as failed to the provider, and every result reads the same way.
- The descriptions cannot drift from the declarations' effects once T2 lands.
- Code checks no audience for a message yet (§9:3). That is safe while every connection reaches the
  owner alone, and stops being safe the day one does not: the audience design must land before a
  second person's connection does ([#2590](https://github.com/leonapivato/ai-assistant/issues/2590)).
- Nothing says the system never claims to be human until #3600 is ruled.
- A grant held before the deploy may stop covering (§8:7), so the owner may be asked again.

## Alternatives considered

- **A connection `enum` on `send_text`.** Rejected by the owner: the offered tools would differ
  between works, which breaks the cache and ADR-0356 §4:3.
- **Flagging failure through pydantic-ai's retry part.** Rejected: it appends wording that tells
  the model to retry.
- **Rewriting stored records to the new names.** Rejected: the audit trail and the episode store
  are append-only, and a table read in one place does the same work.
- **Keeping `exact` as an argument.** Rejected by the owner: one mechanism covers a part and the
  whole.
