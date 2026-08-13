# 141. A notification measure counts rulings, and the ruling seam emits the trace it is counted from

- Status: Proposed
- Date: 2026-08-12
- **This decision adds contract surface, and it is one member.** `TraceKind`
  gains `NOTIFICATION` (§2). That is a `core/types.py` change, so golden rule 5
  and ADR-0015 §5 bind: this ADR is merged, ratified, before anything implements
  against it, and the required review set is adversarial **and** architecture.
  ADR-0119 §13e is the clause that puts the price here — "A member added to
  `TraceKind`, `TraceOutcome`, `TraceRef` or `TraceRecordSet` takes its own
  ratified ADR, merged before anything implements against it" — and §9 records
  that the member is the whole of the addition: no Protocol changes, no
  `Settings` field appears, no `AssistantEngine` method, wire operation or CLI
  command is created, and no other enumeration gains a member.
- **It answers #980 by ruling the measure's definition, and it does not close
  it.** #980 asks for an instrument in the tree. This ADR supplies what an
  instrument needs before it can be written — what is counted, out of what, and
  from where — and the harness itself is the follow-on lane, in the shape
  ADR-0120 §9 already fixed. #980 stays open as that lane's issue.
- **The premise #980 reasons from does not hold, and §Context shows it against
  the merged tree.** #980 proposes a measure "over figures the store already
  holds", concluding that "every input is already durable in `notifications.db`
  and `outbox.db`; none of it needs new recording". Three merged facts refuse
  that: a reconsideration **overwrites** the ruling it replaces, the budget
  ledger **deletes** its own history on every read, and a device's
  acknowledgement is recorded as a **dismissal**. What the stores hold is the
  present state of a set of records; what a measure of proactivity needs is a
  record of the rulings that produced it, and the two differ by exactly the
  events the question is about.
- **This ADR amends nothing and supersedes nothing.** §10 applies ADR-0082 §1's
  test at each place a record looks owed — ADR-0119 §3 most closely — and records
  why none is.
- **It discharges no deferral of ADR-0130 and reverses none.** ADR-0130 §2's
  refusal to carry delivery state stands untouched, and §8 below states what that
  costs this instrument rather than routing around it.

## Context

### Leg 10 left a half of its exit test that nobody can read

`docs/roadmap.md`'s leg 10 exits when "the assistant tells the user something
they did not ask for and were glad to be told, and the user can tune what reaches
them". The second half is mechanical and leg 10 shipped it. The first half is
experiential, and the ruling on #879 defers it: the owner is away, so there is no
daily use for a notification to land in, and no judgement to make about whether
landing was welcome.

That deferral is fine. What is not fine is that when the owner returns and usage
resumes, **there will be nothing to compare against.** #980 is the record of it,
found by leg 10's QA pass (#978) against the pattern
`.claude/skills/qa-leg/SKILL.md` §2 states: "Where a leg ships no instrument, say
so in the run's record — each leg should leave one behind, and its absence is
what makes the next leg's QA expensive." Leg 8 left three measures and a console
script (ADR-0120). Leg 10 left neither, and #978 records the concrete price: every
figure in that run was obtained by writing throwaway drivers and reading timings
out of the hub's structured log by hand, so nothing in the tree reproduces any of
them.

**The arc gate is why this is worth a decision rather than a script.**
`docs/roadmap.md` → "The gate between leg 10 and leg 11" makes leg 8's measures
able to overrule a plan — "if memory precision is flat, or the correction rate is
not falling, through legs 9 and 10, then legs 11 and 12 pause". A notification
figure read off an ad-hoc query has no standing in a conversation like that. A
figure two implementations would compute identically, over a population defined
in a ratified text, does.

### What the chassis actually records, as merged

The definitions below are only as good as their agreement with what is on
`origin/main`, and #980's suggested shape does not survive the check. This is the
inventory each clause was written against.

**The trace stream carries four kinds and four emitters, and no notification
module is among them.** `TraceKind` has `OPERATION`, `RETRIEVAL`, `MEMORY_WRITE`
and `CONFIGURATION` (ADR-0119 §3). The emitting sites are
`orchestration/traces.py` (from `Engine._tracked`), `memory/sqlite_store.py`,
`memory/ingest.py` and `service/configuration.py`. **No notification module holds
a `TraceSink` at all** — not `memory/notification_store.py`, not
`memory/notification_policy.py`, not `memory/notification_outbox.py`, not
`orchestration/notifications.py`, not `orchestration/upcoming.py`.

**What notification work does produce is `OPERATION` traces, one per engine call,
and two of them carry a count.** `Engine._tracked` wraps every public method, so
eight notification-shaped seams appear in the stream today —
`notice_upcoming_events`, `notifications`, `next_notification`,
`dismiss_notification`, `forget_notification`, `notification_preferences`,
`set_notification_preferences` and `reconsider_notifications`. Two carry a metric:
`notice_upcoming_events` carries `noticed`, how many candidates a producer run
offered, and `reconsider_notifications` carries `reconsidered`, how many held
records one sweep re-ruled. Both are literals written in `orchestration/engine.py`
and both are aggregates over a run. **None of the eight is on either seam
allowlist** in `evaluation/_vocabulary.py`, so none contributes to any measure
ADR-0120 defines; they reach the per-seam latency summary and the stream-health
counts and nothing else.

**`notifications.db` holds one row per admitted record**, with columns `id`,
`candidate_key`, `candidate`, `kind`, `reason`, `failed`, `ruled_at`,
`reconsider_at`, `admitted_at`, `retention`, `dismissed_at` and `dropped_at`; a
one-row preferences table; and `notification_interruptions(spent_at)`, the budget
ledger. `outbox.db` holds `outbox(candidate_key, candidate, record_id, sequence,
delivery_id, leased_at, departing, cost)` and a counters row.

Four properties of that inventory decide this ADR, and each is a place #980's
shape would have produced a wrong number that looked right.

**A reconsideration overwrites the ruling it replaces.** ADR-0130 §5 rules that a
reconsidered record "is updated in place with the new disposition", and
`SqliteNotificationStore._write` implements it as one `INSERT OR REPLACE INTO
notifications` on the record's own `id`. So `kind`, `reason`, `failed` and
`ruled_at` describe the **latest** ruling and no other. A candidate held behind a
quiet window, held again behind an exhausted budget, and finally interrupted is
one row reading `interrupt`, with one `ruled_at`. Counting dispositions out of
that table counts *records in their final state* and calls it "what the policy
decided", which is a different quantity that happens to have the same units. It
also undercounts spent budget: ADR-0130 §5 spends a unit at every `INTERRUPT`
including a reconsideration's, and a record can only carry one.

**The budget ledger deletes its own history.** `SqliteNotificationStore._budget`
runs `DELETE FROM notification_interruptions WHERE spent_at <= ?` at the window
floor on **every** read, and says why in its own comment: it "keeps the ledger
bounded by the window rather than by uptime". That table is a rate limiter's
working state, not a record. Any figure about the budget over a past window is
unavailable from it.

**A device's acknowledgement is written as a dismissal.**
`SqliteNotificationOutbox.acknowledge` marks the entry departing, calls
`self._dismiss(entry.record_id)` — which stamps `dismissed_at` on the
`notifications` row — and then deletes the outbox row. So after a delivery
completes, the outbox retains nothing, and the durable record is
indistinguishable from one the owner dismissed by hand. ADR-0131 §3b adds a third
producer of the same stamp: a `TOO_LARGE` or `KEY_COLLISION` refusal "dismisses
the record". `HeldNotification.dismissed_at`'s own description says "When the user
dismissed it", which on two of those three paths it does not mean. #980's "what
was dismissed vs read" is therefore not a distinction the store can draw, and the
half of it that would matter most is worse than unavailable — it is available and
wrong.

**"Seen" is not absent by oversight; it is refused.** ADR-0130 §2: "A candidate
carries no delivery state. Whether contact was attempted, reached a device, or
was seen is not a field of the candidate and not a field of its disposition, and
no clause of this ADR may be read as placing one there." `core/types.py` restates
it over the whole type block. So no instrument built on this chassis can report
whether the user welcomed anything, and §8 says so as a limit rather than
implying otherwise by silence.

### Three constraints this ADR did not choose

**ADR-0119 §5's denominator rule.** "Every measure must be a rate whose
denominator is drawn from the same stream — never from an external count of
turns, rows or runs", because the stream is lossy in principle and "a ratio of
two quantities that lost rows at the same rate survives the loss". ADR-0120 §5's
commentary sharpens it: the two parts must be observed by *one act*, so they are
lost by one act. §5 below draws its numerator and denominator from three keys one
statement writes together, for exactly that reason.

**ADR-0119 §2's content rule.** A trace carries numbers, booleans, enum members,
literals its emitting module wrote, and opaque ids. Nothing else. This is what
forecloses the per-class decomposition #980 asks for, and §8 states it as a limit
rather than reaching for an amendment.

**ADR-0120 §10's one-store rule.** "The reporting tool opens no store but the
trace store, and never resolves a record id against another one", because
"reading only the trace store is what keeps a measure a statement about events" —
a store read is "a measure of the present rather than a record of an event". That
clause was argued about `memory.db`, and the notification store turns out to be
the better example of it: `memory.db` at least keeps a superseded belief's window,
while a reconsidered notification's previous ruling is simply gone.

### What makes this a decision rather than a query somebody writes

Four things, each with a reasonable-looking wrong answer, and the second is the
one that would have cost the most.

1. **The obvious source is the notification store, and it answers a different
   question.** #980 proposes it in as many words. It is the natural instinct —
   the data is right there, no emitter is needed, and the query is short. What
   comes back is a census of records in their final state, over a population the
   retention purge is actively removing (ADR-0130 §7), with the budget's history
   deleted and a dismissal that means three things. §1 refuses it and §Context is
   the showing.
2. **The obvious carrier is `TraceKind.OPERATION`, and using it silently breaks
   ADR-0120 §3.** A notification ruling is an event at a seam, `OPERATION` is the
   kind for events at seams, and nothing in ADR-0119 obviously forbids a second
   one inside a call. But ADR-0120 §3 attributes a memory write by finding "the
   **unique** `OPERATION` trace in the retained stream carrying the same
   `TraceRef.CORRELATION` value", and `evaluation/_stream.py` implements that by
   dropping a correlation it meets twice. One reconsideration sweep rules many
   records under one correlation; one producer run offers many candidates under
   one. Emitting `OPERATION` for each would put several under one correlation, so
   the index entry would be dropped — and every `MEMORY_WRITE` sharing that
   correlation would become **unattributed** and leave ADR-0120's §4, §5 and §6
   populations entirely. A new measure would have quietly degraded three ratified
   ones, and the symptom would have been a rising `unattributed` count in a
   stream-health block nobody reads until something else is wrong. §2 is that
   hazard closed by construction.
3. **The obvious denominator is a count of candidates, and it is not in the same
   stream.** "Interruptions per candidate produced" is the phrasing a person
   reaches for. `noticed` is right there on the producer's `OPERATION` trace. But
   an offer ruled `DROP` writes no durable record (ADR-0130 §8), a producer
   without an outbox hands off nothing, and the producer's count and the store's
   rulings are observed by two acts that can lose rows independently — which is
   precisely the shape ADR-0119 §5's rule forbids. §5's denominator is the ruling
   population itself.
4. **The obvious decomposition is per notification class, and the trace may not
   carry one.** #980 asks for "tellings per class per window" and it is the figure
   an operator would most want, because a rate pooled across classes moves when a
   producer is added. A class is a producer-declared name (ADR-0130 §6), so it is
   a literal in the *producer's* module and not in the module that would emit —
   which is not one of ADR-0119 §2's four permitted string origins as read from
   the emitting seam. §8 states the limit and files the question rather than
   widening a tier rule to buy a breakdown.
