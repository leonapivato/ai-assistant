# 83. The hub is a resident process: lifecycle, exclusivity, and an internal scheduler

- Status: Proposed
- Date: 2026-07-31
- **This is the first of leg 5's two decisions.** It decides the *process*: how
  one instance is enforced, how it starts, how it stops, what its exit codes
  mean, what it refuses to start over, and the internal scheduler that is already
  named as the home of five deferred jobs. The **local API** — transport, the DTO
  shape, versioning, and the CLI as a client — is **ADR-0084's**, drafted after
  this one because its choices depend on this process model. §14 states the
  boundary in both directions.
- **New `core` surface, and it is contract surface without being a Protocol.**
  This ADR adds `Settings` fields (§2, §4, §7) and one `core/errors.py` class
  (§6). It touches **no** Protocol in `core/protocols.py` and **no** type in
  `core/types.py`, so golden rule 5's "Protocol change" is not literally
  triggered and no triad is owed. It is contract surface all the same — the
  corpus's own line is the triple ADR-0054's header draws, "no Protocol in
  `core/protocols.py`, no `core` type, and **no `Settings` field**" — and
  ADR-0026's `Clock` alias is the precedent for `core` surface that is not a
  Protocol and takes the architecture review regardless. So this ADR is
  `Proposed`, alone in its PR, and merges ahead of anything implementing against
  it (ADR-0015 §5).
- **No implementation lands with it.** No `src/`, no `tests/`.

## Context

### Nothing in this system is per-process yet

Every unit of composition today is per-invocation. `build_engine` is one function
(`app/composition.py:60`); `interfaces/cli.py` opens a full engine per command
(`_open_engine`, `cli.py:629-654`) and each of its eleven entry points wraps its
body in `asyncio.run`. `Engine.start()` — which already runs the conversation
deletion sweep and the retention reclaim (`engine.py:1017-1048`) — is called only
from `_open_engine`, so those sweeps run once per CLI command and never
otherwise. `Engine.aclose` drains and closes at the end of each command.
`Engine.__init__`'s `max_outstanding_confirmations` default of 1024 is never
passed by `build_engine`, so it is not operator-settable. `Settings` has no
`data_dir` field at all: the data directory exists only as
`build_engine(settings, *, data_dir=None)`, resolved to `~/.ai-assistant` by a
private helper. There is no signal handling, no lock file, no background task and
no scheduler anywhere in `src/ai_assistant/`.

That is a correct shape for a one-shot CLI and the wrong shape for everything the
roadmap's remaining legs need. Sensors (leg 6), consolidation (leg 7) and
proactivity all require something to be awake; the observer (leg 3) shipped with
its cadence explicitly deferred to "leg 5's scheduler"; and five separate ratified
decisions defer a job **by name** to a scheduler that does not exist.

### Five deferrals already name this scheduler

| Job | Deferred by | Words |
| --- | --- | --- |
| `MemoryStore.purge_expired` | ADR-0007 §2 | "callers (a future scheduler) can reclaim space without changing observable behaviour" |
| `DeferralStore.purge` | ADR-0078 §10 item 8 | "It does not get a new one… this store's purge is wired wherever `purge_expired` is wired and inherits the same fate" |
| Confirmation deadlines | ADR-0044 §4, ADR-0059 §1 | the deadline is frozen on the record; nothing sweeps over it |
| Conversation deletion sweep and retention reclaim | ADR-0074 §8 | "run by the deleting call, at engine start, and later by the hub's scheduler (leg 5)" |
| Observation cadence | ADR-0077 §8 | "Leg 5's scheduler owns cadence, and inherits this operation unchanged" |

Two of those carry constraints that bind this ADR rather than merely inviting it.
ADR-0076 §5: "**Leg 5 inherits this method unchanged** — a scheduler is a second
caller of the same read, not a reason to design a different one", so the sweeps
get no new store surface. ADR-0078 §10 item 8: "Inventing a second sweeping
mechanism for one store would be the thing that has to be undone at leg 5."
`tests/app/test_composition.py:771-806` pins that instruction as a static AST scan
asserting that nothing in production code calls `purge`/`purge_expired` at all —
a guard whose own docstring says "it fails the day someone adds the timer leg 5
would have to remove."

### The rulings this ADR is built on

Given by the project owner and treated here as constraints, not as options:

1. **The hub eventually runs on a dedicated, always-on machine.** That is the
   shape to design for. Loopback-first is a consequence of that machine not
   existing yet, not a judgement that local-only is the target.
2. **It runs essentially at all times. If it is not running, there is a reason,
   and the reason is legible.** It is never "I forgot to start it."
3. **No client-driven autostart.** A client has no business spawning the service.
   This rejects *client-driven lifecycle*, not supervision: a supervisor
   restarting a crashed daemon is wanted.
4. **The hub owns the five SQLite databases exclusively.** The API is the only
   door; no other process opens them.
5. **When the hub is not running, a client fails with an instruction** — no
   in-process fallback.

### What makes the lifecycle a decision rather than an implementation detail

`Engine.aclose` → `_drain_and_close` waits on `self._inflight` with an unbounded
`asyncio.gather` (`engine.py:1836-1837`) and its docstring states the rule it is
built on: "Draining is *awaiting*, never cancelling (ADR-0042 §2)." For a one-shot
CLI that is exactly right. Under a supervisor with a stop timeout it ends in
`SIGKILL` — and `SIGKILL` destroys precisely the bookkeeping ADR-0029 §4's
shielded commit exists to preserve, the record of *why* a step ended, committed
under `asyncio.shield` with further cancellations absorbed so that "a shutdown
that stops waiting politely" cannot leave the step `RUNNING` with the
classification unwritten. A hub that routinely dies by `SIGKILL` is a hub that
routinely loses that record. So the drain has to be decided, not inherited.

## Decision

### 1. One resident process, and the presumption ADR-0014 §4 makes becomes true by construction

**The hub is a single, long-lived, foreground process.** It does not fork, does
not daemonise, and writes its log to standard output.

**Exactly one instance runs per data directory, enforced by an exclusive advisory
lock** on `<data_dir>/hub.lock`, taken with `flock(LOCK_EX | LOCK_NB)` **before
any store is opened** and held, unexamined, for the process's whole life. The
kernel releases it when the process dies, so there is no stale-lock problem and no
PID-liveness heuristic to get wrong — a held lock always means a live holder.

A second instance **retries for a bounded few seconds** — absorbing a supervisor
that overlaps a restart with an outgoing hub's drain — and then **exits 1**: a
*restartable* failure, deliberately, and not `78`.

That classification is the one place where an appealing answer is wrong, so the
reasoning is written down. A held lock always means a live holder, and a live
holder is in exactly one of two states, neither of which a human must fix. Either
it is **serving**, in which case the deployment is up and the loser's restart loop
is harmless noise against a healthy peer — and self-limiting, because a supervisor
backs off. Or it is **draining**, in which case a later attempt succeeds. Treating
contention as `78` would make the second case fatal: §4's phase B is unbounded, so
a drain can outlast any retry window this ADR could name, and a `78` there —
which D1 tells the supervisor not to restart — leaves **no** hub running after the
outgoing one exits cleanly, with nothing wrong to fix. `78` means a human must
act (§5); nobody must act here. The retry window is therefore a noise filter, not
a correctness mechanism, and nothing rests on its length.

**The diagnostic names the data directory and the lock path, and reports a pid
only if it can.** `flock` exposes no portable query for its holder, so the holder
writes its pid into the lock file *after* acquiring — which means a contender can
find the file empty (the holder was pre-empted before writing) or stale (a
previous holder's, not yet overwritten). The message therefore says "held by
another instance", and adds the recorded pid as an explicitly advisory hint when
one is present. A diagnostic that unconditionally promises a pid would eventually
print a wrong one, and a wrong pid in an operator message is worse than none.

The lock is **advisory** and it is unreliable on network filesystems. Both are
named rather than papered over: it stops a second *hub*, not an arbitrary process
(§10 is what addresses that), and it is one of the two reasons the data directory
must be local storage (D3 in §3).

**ADR-0014 §4's recovery presumption stops being an assumption.** It says recovery
"scans `active_executions()` at startup, which presumes no executor is live for
those states — true for a single-user local app with one executor. A lease
(`RUNNING` with an expiry, reclaimable by a peer) is the generalisation and is
deferred with the rest of concurrent execution." Exclusivity makes that
presumption true **by construction**: with one process holding the lock, no other
executor can be live over those rows, whatever the deployment. **We decline the
lease, and we decline it deliberately**, not by omission: a lease is durable state
needing renewal and crash-safe expiry, written for a peer that this decision
guarantees does not exist. ADR-0014 §4's own sentences stay true — it says the
lease *is* the generalisation and *is* deferred, and it stays deferred. It becomes
owed again the day exclusivity is relaxed, which is the same day §12's posture on
#505/#526 reopens.

### 2. `data_dir` becomes a `Settings` field

The hub's most basic configuration item does not exist today. It becomes
**`Settings.data_dir: Path`**, defaulted by factory to the same `~/.ai-assistant`
the composition root resolves now, so no existing behaviour changes and
`AI_ASSISTANT_DATA_DIR` starts working for free through pydantic-settings — which
is what `CLAUDE.md`'s "read config through `core.config.Settings`; never touch
`os.environ` directly" asks for.

`build_engine(settings, *, data_dir=None)` **keeps its keyword**, and when given it
overrides the setting. It is the injection seam every existing test uses, and
removing it would rewrite tests this ADR has no business touching. The field is
purely additive.

**`max_outstanding_confirmations` is named here and not decided here.** A one-shot
CLI could not accumulate against a cap of 1024; a process that runs for weeks can,
and §7 explains why nothing on the scheduler relieves it yet — the reclamation
that would is ADR-0059 §3's, deferred as #333. That it is an `Engine.__init__`
default `build_engine` never passes is a config-surface gap the hub makes matter,
and it is filed as an issue rather than settled in a lifecycle ADR. Naming the
two together is the point: the cap becomes reachable and the mechanism that would
drain it does not exist, so a deployment's only lever until #333 lands is the
number itself.

### 3. Startup is a fixed sequence, and readiness is the last thing in it

In order, and no step begins before the previous one has succeeded:

1. **Load `Settings`.** A settings failure is a deployment fault → exit 78.
2. **Resolve `data_dir`, create it if absent, and take the instance lock** (§1).
   A `data_dir` that cannot be created or written → exit 78. **Lock contention →
   exit 1**, for the reason §1 gives.
3. **Build the engine** — `build_engine(settings)`, which opens the five stores.
   A *state* fault here → exit 78 (§6). Any other failure → exit 1.
4. **`Engine.start()`** — the deletion sweep then the retention reclaim, already
   ratified for this position by ADR-0074 §8 ("at engine start") and already
   built. A resident process improves on the CLI here rather than changing
   anything: because the hub restarts after a crash, the reclaim that finishes an
   interrupted deletion now runs after *every* crash instead of at the next
   command the user happens to type.
5. **Start the scheduler** (§7, §8).
6. **Begin accepting requests**, and only then **signal readiness**.

**Nothing in startup may block indefinitely on a network.** Every step is
local-only by construction today, and keeping it so is what makes a supervisor's
start timeout meaningful.

**Readiness means: the lock is held, every store is open, the at-start sweeps have
run, the scheduler is running, and the API is accepting.** It is signalled by two
observables, neither of which requires a supervisor-specific protocol: a
structured log event at `INFO` naming the pid, the data directory and the enabled
job set; and the API accepting connections, which is ADR-0084's mechanism. A
deployment whose supervisor has a richer readiness protocol may adapt these; the
service does not depend on one (§ supervision contract, below).

**Before readiness a supervisor may assume nothing but that the process exists.**
No store is guaranteed open and no request will be served. This yields the one
hard constraint §14 hands ADR-0084: **the transport must not accept before
readiness**, so no request is ever served against a half-built engine.

**The supervision contract.** systemd is named below only as *a* reference
realisation, deliberately not as a binding: the deployment itself changes from a
laptop to a dedicated box, so the supervisor is the one thing not to hard-code.

The service promises:

- **S1.** It runs in the foreground, never forks or daemonises, and logs to
  stdout/stderr.
- **S2.** It exits `0` only after a completed drain.
- **S3.** It exits `78` only when the deployment must change before a restart can
  succeed, and it prints the cause and the operator action before doing so.
- **S4.** Any other exit, and any fatal signal, means the process should be
  restarted.
- **S5.** A stop request reaches §4's cancel-and-await phase within
  `shutdown_drain_seconds`. **It does not promise a hard upper bound on the
  total**, because §4's final await is unbounded by design; what it promises is
  that the wait is on work that is cancelling and observable, never on work that
  has been asked for nothing.
- **S6.** It is safe to start any number of times; at most one instance runs (§1).
- **S7.** It needs no client to start it, and no client can start it (ruling 3).

The deployment must provide:

- **D1.** A supervisor that restarts on S4 and does **not** restart on S3.
- **D2.** A stop timeout comfortably above `shutdown_drain_seconds` — the
  reference margin is `shutdown_drain_seconds` plus thirty seconds. **This is a
  margin, not a proof.** S5 cannot promise a total, so D2 cannot be a guarantee
  either; it is sized so that the unbounded tail, whose expected duration is one
  cancelled operation unwinding, has room it will not normally use. Exceeding it
  means `SIGKILL`, which §4 argues is the correct outcome when it happens.
- **D3.** A `data_dir` on local storage, writable, not shared with another hub.
- **D4.** Start at boot, not ordered after a user login (ruling 2).

*Reference realisation, illustrative only:* a systemd service unit with
`Type=exec`, `Restart=on-failure`, `RestartPreventExitStatus=78`, and
`TimeoutStopSec` set above D2. No unit file is ratified here and none is a
dependency.

### 4. Shutdown is two-phase: bounded where bounding is safe, unbounded where it is not

**Signals.** `SIGTERM` and `SIGINT` both mean *drain and stop*, identically, so
`Ctrl-C` in a foreground run behaves exactly as the supervisor's stop does.
`SIGHUP` is **ignored**, explicitly: there is no configuration reload in this
version, and a signal that silently does nothing is worse than one that is
documented as doing nothing.

**A second stop signal does not escalate.** It is logged as "shutdown already in
progress" and changes nothing. `aclose` is already memoised and cancellation-safe
by design (`engine.py:1799-1805`: "the shutdown task keeps running to completion…
the closers run exactly once"), and an in-process "abrupt" mode would be a second,
weaker way to do what `SIGKILL` already does uninterceptably — while costing the
ADR-0029 §4 bookkeeping that graceful shutdown exists to keep.

**Phase A — bounded.** Stop accepting new calls (`_closing = True`, which
`_reject_if_closing` already enforces at the top of every public method), stop the
scheduler (§8), and wait up to **`Settings.shutdown_drain_seconds`, default 30
seconds**, for the tracked in-flight work to finish on its own.

**Phase B — cancel, then await, and the await is unbounded.** At the budget, the
remaining tracked tasks are **cancelled** and then **awaited to completion**. Only
after every one has completed are the owned resources closed, in the order the
composition root handed them — ADR-0042 §2's obligation, unchanged.

Four things make that the right shape, in the order they bind:

- **Cancelling is not abandoning, and the difference is a connection.** ADR-0054
  establishes, uniformly across all five stores (verified: `_run_to_completion`
  appears in `memory/sqlite_store.py`, `memory/conversation_store.py`,
  `memory/deferral_store.py`, `planning/sqlite_store.py` and
  `permissions/audit.py`, and no `asyncio.to_thread` call survives in any of
  them), that a cancelled store call "keeps the lock until its worker thread
  finishes" and re-raises only then. So a cancelled task's `CancelledError`
  arrives *after* the connection is physically free. Awaiting the cancelled task
  is therefore still ADR-0042 §2's "awaits every tracked underlying operation to
  quiescence… before closing", satisfied literally.
- **Cancelling is what *preserves* the bookkeeping, not what loses it.** ADR-0029
  §4 commits the step's classification under a shield and absorbs further
  cancellations until the write lands. A cancelled step therefore records why it
  ended. A `SIGKILL`ed one does not. Phase A's budget exists so that the process
  reaches phase B *before* the supervisor's stop timeout, i.e. so this path is
  taken instead of `SIGKILL`.
- **ADR-0060 §1 permits it, and permits it for this exact reason.** Its
  propagation clause turns on provenance — "*From outside* is load-bearing. A
  cancellation a method **issues itself**, to enforce a deadline it owns, is its
  own control flow." The shutdown deadline is the service's own. And its resource
  clause is satisfied by the previous point. The unbounded phase-B await is the
  form ADR-0060 §1 names in as many words: "the wait is on something the
  implementation can observe completing, and the deferral is bounded **or
  documented as unbounded**." It is documented as unbounded, here.
- **Bounding phase B is the one thing that must not be done.** Its only
  termination-forcing alternative is abandonment, and an abandoned store call is
  a worker thread still holding a connection that the very next statement closes
  — ADR-0054's bug, deliberately re-created. If phase B ever outlives the
  supervisor's stop timeout, `SIGKILL` is the correct outcome and is strictly
  safer than closing under a live worker: SQLite recovers a journal on next open,
  and has no recovery for a connection closed out from under a running statement.

**ADR-0033's bounded-and-abandon shape is considered and declined.** Its §1 is
sound where it sits and its §2 states why: "the abandoned task is still running…
It can still complete, still log, still perform the late side effect." Its case
rests on a dominance argument — "**Unbounded:** the task runs forever *and* the
caller waits forever. **Bounded:** the task runs forever *and* the caller gets its
failure" — which holds because the assembler *has no third option*: the straggler
it is bounding suppresses cancellation, so awaiting cannot stop it. Here there is
a third option and it is strictly better. Every in-flight party honours
cancellation, ADR-0054 makes cancelling connection-safe, and the abandoned party
would be holding a SQLite connection rather than an HTTP session. The dominance
argument does not transfer, so neither does the conclusion.

`_drain_and_close`'s docstring today asserts the stronger rule "Draining is
*awaiting*, never cancelling (ADR-0042 §2)". That is the implementation's gloss,
not a ratified clause — ADR-0042 §2's own text requires that the façade "must not
`close()` an owned resource while any underlying operation it started might still
touch it" and that shutdown "awaits every tracked underlying operation to
quiescence… before closing", both of which this decision keeps. The docstring must
end up true (ADR-0033 §5's rule, applied to a different file), and that edit
belongs to the implementing lane. §15 records why no amendment is owed on
ADR-0042 itself.

### 5. Exit codes distinguish "come back" from "stay down"

| Code | Meaning | Supervisor should |
| --- | --- | --- |
| `0` | A stop was requested and the drain completed. | Not restart. |
| `1` | An unexpected fault, **or a contended instance lock** (§1). The process should come back. | Restart. |
| `78` | **The deployment is wrong.** This build cannot serve this environment or this state, and restarting changes nothing until a human acts. | **Not restart.** |

`78` is `EX_CONFIG` from `sysexits.h` — an existing convention rather than an
invented number, which is what lets a reference deployment map it with one
directive. It covers exactly three things: settings that will not load, a
`data_dir` that cannot be created or written, and persisted state this build
cannot serve correctly (§6). A contended lock is **not** among them (§1), and the
test for the boundary is one question — *would restarting unchanged ever succeed?*
For a foreign embedding space, never; for a peer that is draining, on the next
attempt.

**Every `78` prints its cause and the operator action before exiting**, to stderr
and to the log, and that is ruling 2 discharged: a hub that is down is down for a
reason a human can read. Those messages are operational text and carry no Tier 0/1
content (ADR-0004 §5) — they name settings keys, paths and identifiers, never
memory content, never a conversation. The distinction the table draws is the whole
point of it: a crash loop is a process that never explains itself, and a fatal
refusal that a supervisor keeps restarting is a crash loop wearing a diagnosis.

### 6. A state fault refuses to start, and the failure class is a deployment fault, not a store fault

**The rule, stated once:**

> The hub refuses to start when the state it would serve **cannot be served
> correctly by this build**, and it stays down. It does **not** refuse merely
> because the state was written by a different build.

The test is whether serving would be **silently wrong** — answers a client cannot
tell from correct ones. It is not "is this state unfamiliar".

**#425 is the first instance and the reason the rule is needed.** Today
`SqliteMemoryStore._verify_or_init_meta` (`memory/sqlite_store.py:346-361`) raises
on an embedder mismatch with "store was built with … but this embedder has …;
re-embedding is required". It raises from `_setup`, which is called from
`__init__` (`:207`, `:240`), so `build_engine` fails and the process dies. That
refusal is **right** and this ADR keeps it: every stored vector is in a different
space, so `search` would rank on nonsense and report nothing wrong. Two things
about it are not right for a resident process:

- **It is a `MemoryStoreError`** — a subsystem error from below the disk line —
  so the entry point cannot tell "this deployment cannot serve this store" from
  "this disk is broken" without matching on a message string.
- **Under a restarting supervisor an unclassified nonzero exit is a crash loop**,
  which is ruling 2's failure exactly: the hub is down and the reason is buried in
  a repeating stack trace.

**So `core/errors.py` gains one class** — a state-incompatibility fault,
`AssistantError`-derived, raised by a store at open when this build cannot serve
what is on disk. It carries what was expected, what was found, and the operator
action. The hub's entry point maps it, and only it, to exit `78`. Placement
follows the corpus: `core` holds errors (`CLAUDE.md`'s map), and a new
`AssistantError` subclass is neither a Protocol nor a `core/types.py` model, so
golden rule 5 is not triggered (ADR-0014 §4 adding `PlanningError` is the
precedent).

**No new migration contract is created, and ADR-0024 §2 stays true.** It holds
that changing `model_id`'s composition "owes no new migration contract:
`SqliteMemoryStore` already raises 're-embedding is required' on any mismatch
(existing §4 behaviour, records intact)". This ADR changes the *class* of that
refusal and its exit code; it does not change what is detected, when, or what
happens to the records. Automating the re-embed remains ADR-0006 §4's and leg 7's.

**The tension with ADR-0064 is real and it resolves cleanly.** ADR-0064 **§3** —
not §2, which is about *where* the check fires — holds that a mark below the
counter "is what a mixed-version deployment looks like — an older build advancing
the counter without the witness — and it must not refuse. It is levelled up
instead." Both rules apply the same test and come out differently because the
facts differ: a lagging high-water mark is state this build **can** serve
correctly (no ordinal was issued twice, and levelling up restores the invariant),
so refusing would cost availability and buy nothing; a foreign embedding space is
state this build **cannot** serve correctly, and serving it returns wrong answers
without saying so. "Must not refuse" is not a general preference for starting; it
is the correct answer for the class of fault ADR-0064 §3 is about. Neither clause
is widened by the other (§15).

### 7. The scheduler: one loop, per-job due instants, serial, fixed delay after completion

**Shape.** One scheduler loop holds a table of jobs, each with a name, an interval
and a next-due instant. The loop runs every due job, in a fixed order, **one at a
time**, then sleeps until the earliest next due instant.

**A job's next run is scheduled from its *completion*, not from its start.** This
is what makes a job structurally unable to overlap itself — which matters because
ADR-0076 §2 requires a sweep to "**drain to an empty batch**… finishing one batch
and stopping is the failure that clause exists to forbid", so a tick is a walk to
exhaustion whose duration is a function of the backlog, not of the interval. A
fixed-rate schedule would let a long walk be re-entered by the next tick; a fixed
delay after completion cannot.

**Jobs run serially, and starvation is accepted rather than engineered away.** A
long job delays its siblings. That is tolerable because **a missed or late tick is
never a correctness bug**: ADR-0007 §2 enforces retention *at read time* — "This
holds regardless of whether `purge_expired` has run, so the privacy guarantee does
not depend on a background job" — and every other job on the list is likewise a
physical reclaim or a re-derivation of something a read path already computes.
Serialising buys a scheduler that is one thing to reason about, one thing to
cancel and one thing to drain, and removes any question of two jobs contending on
one store's connection. Revisit when a job's typical runtime approaches its
interval, which is what consolidation (leg 7) is likely to do first.

**A failing job never takes the process down.** The failure is logged with its
class (ADR-0004 §5) and the job is retried at its next due instant. Nothing in the
job list is load-bearing for correctness, so escalating a sweep failure to a
process exit would trade a harmless backlog for an outage.

**The job list, its defaults, and the ADR each one discharges:**

| Job | Calls | Default | Deferred by |
| --- | --- | --- | --- |
| Retention purge | `MemoryStore.purge_expired` **and** `DeferralStore.purge` | 1 h | ADR-0007 §2; ADR-0078 §10 item 8 |
| Conversation sweep | the deletion sweep, then the retention reclaim | 1 h | ADR-0074 §8 |
| Observation | the `Engine` observation operation | **disabled** | ADR-0077 §8 |

Each interval is a `Settings` field with the default above, which is what ADR-0077
§8 asks for: "Cadence then becomes configuration rather than a contract change."
The defaults are named here rather than left to the implementation, following
ADR-0074 §9.3's rule that "a 'bounded default' with no figure is two conforming
stores handing the same continuation different history."

Four things about that table are decisions, not description:

- **The two purges are one job, not two.** ADR-0078 §10 item 8 says the deferral
  queue's purge "is wired wherever `purge_expired` is wired and inherits the same
  fate", and that "inventing a second sweeping mechanism for one store would be
  the thing that has to be undone at leg 5". One job calling both is that
  instruction taken literally.
- **The conversation sweep is the same pair `Engine.start()` already runs**
  (`engine.py:1017-1048`), at the third of the three positions ADR-0074 §8
  ratified. It is idempotent and "can run any number of times", and ADR-0076 §5
  is explicit that the scheduler "inherits this method unchanged".
- **Confirmation deadlines are named by the roadmap as this scheduler's, and they
  are *not* a job on this list — because the job does not exist to be scheduled.**
  This is the one place the roadmap's leg-5 sentence does not survive contact with
  what is ratified below it, and it is stated rather than papered over. Two
  separate things block it:
  1. **There is no operation to reclaim an expired confirmation.** ADR-0059 §3 is
     explicit: "Durable *reclamation* of a permanently-parked step — cancelling it
     so it stops being rediscovered — is explicitly out of scope and deferred. No
     contract exposes it today: `PlanStore` offers only a single-step
     `commit_transition` and `Engine` no cancellation entry point." A scheduler
     cannot be the second caller of an operation that has no first caller, and
     inventing one here would breach both §7's no-new-store-surface constraint and
     §8's rule that a job holds nothing but the façade. That contract is #333's
     (§13), not this ADR's.
  2. **The deadline it would enforce is not yet written.** ADR-0059 §1 ratified
     freezing `decided_at + confirmation_ttl` onto the record, but its
     `orchestration` half was never wired (**#525**): `runner.py:779-784` calls
     `PermissionDecision.from_request` with no `expires_at` and is the only
     production call site, and `runner.py:708` still computes `age = self._now() -
     confirmed.decided_at`. The column exists and is written
     (`permissions/audit.py:149,539,548`) and every row's value is `None`. A
     deadline job over a column of nulls sweeps nothing and looks healthy doing it.

  **Nothing goes unenforced in the meantime, which is why this is a deferral and
  not a gap.** The lifetime is enforced at *answer* time by `_check_fresh`, as
  ADR-0044 §4 placed it; an expired confirmation is unanswerable whether or not
  anything sweeps. What is deferred is only the *reclamation* — stopping an
  expired park from being rediscovered — and that is what #333 is. When #525 and
  #333 have both landed, this becomes a job on this list by configuration, which
  is the shape §8 is built for.
- **Observation ships disabled, and that is deliberate.** ADR-0077 §8 states
  there is no durable cursor and that re-observation is safe by construction, but
  safe is not free: without a cursor, a periodic run re-reads the same recent
  window and spends a model call each time, and it cannot reach the turns the
  window has already passed. Enabling it on a timer before the cursor exists buys
  repeated cost and no new coverage. The interval exists so that enabling it is
  configuration; the default is off until the cursor lands (§13).

**No job gets new store surface.** Every one of them calls an operation that
already exists, which is ADR-0076 §5's constraint discharged rather than merely
respected — and it is the reason the confirmation reclaim is absent above rather
than listed hopefully.

**Every duration this ADR adds is a `timedelta` refused at load time unless it is
finite and strictly positive**, in the `gt=timedelta(0)` form `confirmation_ttl`
and `conversation_tombstone_grace` already use in `core/config.py`. That is not
housekeeping: on a completion-scheduled loop (above), an interval of zero or below
makes a job due again the instant it finishes, so a misconfiguration turns a
retention purge into a hot loop against SQLite — and a `shutdown_drain_seconds` of
zero silently deletes §4's phase A, which is the whole mechanism keeping the
graceful path reachable. **"Disabled" is `None`, never `0`**, following
`confirmation_ttl`'s and `deferral_ttl`'s existing `None`-means-off convention, so
that "off" and "as fast as possible" cannot be confused by a value — which is the
one confusion a scheduler cannot afford, because the two look identical in a
config file and nothing but load-time validation distinguishes them.

### 8. The scheduler is a peer above the composition root, and every job is an `Engine` call

**It does not live in `orchestration`.** Cadence is a property of a deployment,
not of the request pipeline, and `orchestration` owns the pipeline. It lives in a
new top-level **`ai_assistant/service/`** — the resident process itself: entry
point, signal handling, instance lock, exit-code mapping and the scheduler.
`service` may import `app` (for `build_engine`) and the `Engine` type it returns,
and `core`; nothing may import `service`. The `lint-imports` contract expressing
that belongs to the implementing lane.

**Every scheduler job is a public `Engine` call, and that is what closes the
race.** The residue in choosing between an `Engine`-owned task and a peer is real:
a task the engine does not own is one `aclose` will not wait for, and closing a
connection under live work is the failure ADR-0042 §2 exists to prevent. But the
choice is not between *tracked* and *untracked* — it is between where the cadence
lives. `Engine._tracked` wraps **every public method** (`engine.py:1857-1875`), so
a job whose body is `engine.<operation>(…)` has its underlying store work in
`_inflight` already, and the drain waits for it exactly as it waits for a
`converse`. What is untracked is only the scheduler's own loop, and that is closed
by ordering rather than by ownership:

> **Service shutdown stops and joins the scheduler *before* calling
> `Engine.aclose()`.**

After that join, no job is in flight, so the engine's drain has nothing of the
scheduler's left to wait for. Belt and braces for the race window: the scheduler
treats the `RuntimeError` that `_reject_if_closing` raises ("the engine is
shutting down and is not accepting new work") as **stop**, not as a job failure to
log and retry.

This is also what makes ADR-0076 §5's "a scheduler is a second caller of the same
read" literally true rather than approximately: the scheduler holds an `Engine`
and nothing else — no concrete store, no subsystem import — so it is a client of
the same façade the CLI is a client of.

**The `Engine` therefore grows a maintenance surface** — façade operations for
the retention purge, alongside `start()`'s sweeps and the observation operation
ADR-0077 §9 already owes. That is new *concrete* surface
on a class in `orchestration`, not `core` contract surface, and it belongs to the
implementing lane.

### 9. Elapsed time is `asyncio.sleep`, and ADR-0026's Revisit clause does not fire — yet

ADR-0026's Revisit clause fires "when something needs a **monotonic** clock",
because "`Clock` produces wall-clock instants; measuring an elapsed duration
across a DST transition or an NTP step is a different contract this one does not
provide and should not be stretched to." So the clause has to be examined here.
It does not fire, and the reason is specific:

**The scheduler never measures an elapsed duration across a durable boundary.** It
does two separable things. It *waits* — `asyncio.sleep`, which is loop-monotonic,
needs no contract, and is cancellable, which is how §4's phase A stops it
promptly. And it *compares stored instants* to now — `expires_at` against the
injected `Clock` — which is wall-clock work, is exactly what `Clock` is for, and is
already ADR-0059 §1's shape. Neither is duration measurement. What would require
one is a durable "when did I last run", and **no job has one**: a missed tick is
never a correctness bug (ADR-0007 §2), so there is no catch-up to compute and
nothing to persist.

Two costs of that choice, named rather than discovered later:

- **A suspended host does not advance the sleep.** `asyncio`'s timers rest on
  `CLOCK_MONOTONIC`, which excludes suspend time on Linux, so a laptop that sleeps
  for ten hours resumes with its schedule ten hours behind. On the always-on
  machine ruling 1 designs for this does not arise; on the loopback-first laptop
  it means a job can be exactly that late. Accepted, because late is not wrong.
- **Wall-clock corrections still reach the comparisons.** #277 remains open and is
  unchanged by this ADR: `_check_fresh`'s answer-time comparison is a wall-clock
  bound and a backward correction can still make a past-lifetime confirmation
  answerable. A resident process does not fix it; a deadline anchored on something
  monotonic and durable would, and that is #277's, not this ADR's.

**When a monotonic seam does become owed, it is not the shape the survey assumed.**
The trigger is the first job needing a durable last-run — the observation cursor
with catch-up (§13), or consolidation with a real budget. At that point the
precedent is ADR-0026's own: `Clock` is **not** a Protocol in `core/protocols.py`,
it is a type alias in `core/clock.py:35-49` paired with the `checked_clock` guard,
and ADR-0026 records that this is "*not* a `core/protocols.py` Protocol — a clock
is a constructor parameter, not a Protocol member — so golden rule 5's 'Protocol
change' is not literally triggered. It is contract surface all the same, which is
why it is an ADR and why it takes the architecture review." A monotonic seam
follows that precedent: `core/clock.py`, an alias plus a guard, its own ADR and
architecture review — and **no conformance suite and no canonical fake, because a
triad is what a Protocol owes and this would not be one.** Whichever lane takes it
is a separate lane from any implementing this ADR.

### 10. Exclusivity is the rule; two mechanisms enforce it, and one of them is sequenced

Ruling 4 in this ADR's own words: **the hub is the only process that opens the
five databases, and the API is the only door.** Two mechanisms, doing different
jobs:

- **The instance lock (§1)** stops a second *hub*. It is advisory, so it stops
  nothing else.
- **`lint-imports` stops the in-repo route to a second opener.** `interfaces/cli.py:66`
  imports `build_engine` today, and it is legal because the contract at
  `pyproject.toml:307-328` forbids only a *direct* `interfaces → subsystem` edge:
  it is `type = "forbidden"` with `allow_indirect_imports = "true"`, and its own
  comment says "The indirect chain `interfaces -> app -> subsystem` is the
  sanctioned path and is permitted". **Closing that edge — so no interface adapter
  can build an engine — becomes the mechanical enforcement of exclusivity, and it
  also forecloses the in-process fallback ruling 5 already rejects.**

**That contract edit is sequenced with ADR-0084's lane, not with this ADR.** Today
the CLI *is* the only interface and it builds an engine; forbidding the edge now
would break `main` for a client that does not exist yet. This ADR ratifies that
the edit happens, and that it happens in the change that makes the CLI a client of
the API — not before, and not never.

**Everything else that needs the data goes through the API, or runs while the hub
is stopped.** An offline tool — the re-embedding migration (#425) is the first and
for now the only one — takes the same instance lock, which serialises it against
the hub by construction and needs no new mechanism. A tool that will not take the
lock is outside what this decision can enforce, and saying so is more useful than
implying otherwise.

### 11. The sweep guard test is inverted, not deleted

`tests/app/test_composition.py:771-806` will fail the moment a scheduler is wired:
it is a static AST scan over every `.py` under the package, matching the bare
attribute names `purge`/`purge_expired` with no receiver-type check, asserting
`swept == []`.

**The implementing lane inverts it.** The assertion becomes: `swept` equals
*exactly* the scheduler's own path — the `Engine` maintenance methods' delegating
call sites — so that a second bespoke sweeper added anywhere else still fails.

Deleting it is the wrong move and the reason is in its own docstring: it is the
only mechanical expression of ADR-0078 §10 item 8's "inventing a second sweeping
mechanism for one store would be the thing that has to be undone at leg 5", and it
was written knowing it "fails the day someone adds the timer leg 5 would have to
remove". An instruction not to build a second mechanism is worth exactly as much
as the guard that notices one; inverting keeps the guard and moves the goalpost to
where leg 5 puts it. Its receiver-blindness is a feature here — it is what makes a
sweep added under a different name or a different store still show up.

### 12. #505 and #526 become deliberate rather than urgent, and the roadmap's tail shrinks

The roadmap attaches "the stores' concurrent-access posture" to leg 5, and ADR-0074
§11 defers several questions to "leg 5, whose hardening tail is named as 'the
stores' concurrent-access posture' and **whose process model decides what a second
writer even is**". This ADR answers that question: **there is no second writer.**

- **#526** — `SqliteMemoryStore` is the only store with no `BEGIN IMMEDIATE` (the
  other four carry 14, 5, 4 and 1). Under exclusivity there is one writing process,
  and within it one connection behind an `asyncio.Lock`, so there is no
  cross-process write to be atomic against. It is **consistency work, not a
  defect**: worth doing so five stores read the same way, not worth blocking the
  hub on. It becomes urgent again on exactly one condition — exclusivity being
  relaxed — and that condition is written here so a future reader does not have to
  re-derive the urgency from the asymmetry alone.
- **#505** — WAL is **deliberately deferred, and exclusivity is why.** Its
  headline benefit is a writer concurrent with readers *across processes*, which
  exclusivity removes the demand for; its costs are unchanged and one of them gets
  worse. `synchronous=NORMAL` under WAL can lose the last transactions on power
  loss, and a process that runs for weeks and takes a power cut is a sharper case
  for durability than a CLI command was, not a softer one. WAL also needs a `-shm`
  sidecar and does not work on network filesystems, which is the second reason for
  D3. Staying on the default rollback journal is now a decision with a reason
  rather than an omission (#505's own framing). It still owes its own ADR if taken.
- **What exclusivity does *not* close** is ADR-0074 §8's cross-store window under
  a **process death** — an episode landing after its conversation's tombstone was
  reclaimed. That needs a transaction, not a lock, so ADR-0074 §11's transactional
  posture stays deferred. The hub improves the mitigation without closing the
  window: the reclaim runs at every start (§3 step 4), so a crash is followed by a
  completion pass rather than by whenever the user next runs a command.
- **#305 is not a hub concern.** The roadmap lists the execution-id nonce "under
  multi-process reality" in leg 5's tail, but ADR-0049 §3 is titled for #280 and
  #305 and already applied that fix; what remains on #305 is an `InMemoryPlanStore`
  test seam. Exclusivity removes the multi-process premise as well. It is ordinary
  test-hardening backlog, not leg 5's.

### 13. Deferred, by name

- **The observation cursor.** ADR-0077 §8 files it as leg 5's — "a cursor is
  durable per-user state whose natural owner is the resident process". It is not
  taken here, for a reason worth stating: it is **new durable state**, so it is
  itself subject to §6's upgrade-with-state discipline and needs its own decision
  about what an older or newer build does with a cursor it does not understand.
  Deciding that inside a lifecycle ADR would bury it. §7 ships the observation job
  disabled so nothing depends on the cursor's absence in the meantime.
- **#333, the plan-level reclamation sweep.** ADR-0059 §3 defers "durable
  *reclamation* of a permanently-parked step — cancelling it so it stops being
  rediscovered", noting "no contract exposes it today: `PlanStore` offers only a
  single-step `commit_transition` and `Engine` no cancellation entry point". It is
  a scheduler job the roadmap does not name, and it is genuinely blocked on a
  contract that does not exist — a scheduler cannot call an operation nobody
  offers. **It is also what blocks the one job the roadmap *does* name** (§7):
  confirmation deadlines are not on the job list because reclaiming an expired
  park is this deferral. It stays deferred, and it is named twice so leg 5 does
  not close believing the scheduler's job list is complete.
- **A durable in-flight lease** keeping a slow turn's conversation alive through a
  reclaim (ADR-0074 §11). Not taken, with an observation for whoever does: under
  exclusivity the set of conversations with a live turn is knowable *in memory*,
  in the one process that owns the stores, so the lease may not need to be durable
  at all.
- **Consolidation**, which is leg 7's job on this scheduler.
- **A configuration reload** (§4's `SIGHUP`). A restart is the reload.

### 14. The boundary with ADR-0084

**What this ADR decides that constrains the local API:**

1. One resident process owns the stores; the API is the only door (§1, §10).
2. **The transport must not accept before readiness** (§3), and must stop
   accepting at the start of phase A (§4), so no request is served against a
   half-built or draining engine.
3. Readiness is defined here (§3); ADR-0084 owns how a client *observes* it.
4. **Single-instance enforcement is the lock, not the bind** (§1). ADR-0084 is
   free to choose any transport without exclusivity depending on that choice — a
   unix socket's bind would be a second, weaker instance guard and a TCP port with
   `SO_REUSEADDR` would be none at all.
5. **No client-driven autostart** (ruling 3), and a client meeting a closed door
   reports an instruction rather than falling back in-process (ruling 5).
6. `Settings.data_dir` (§2) is where any socket or transport-local artefact
   belongs, and removing it is part of §4's shutdown.
7. **Continuation tokens do not survive a restart, and the hub will not persist
   the table.** `engine.py:149-153`: "The table lives in the engine object, so a
   handle does not survive a restart." ADR-0052 §1 already provides the durable
   path — "enumerate parked executions and re-mint a continuation", so "durability
   comes from the fact that the handle is *re-derivable from durable state on
   demand*". Persisting the in-memory table would be new durable state under §6's
   discipline, buying what ADR-0052 §1 already gives. **ADR-0084 must therefore
   decide what a client sees when it presents a token minted by a previous process
   life.** (The roadmap's later-arc text claims the opposite about ADR-0042 tokens;
   #527 tracks that correction, and it is not this ADR's to make.)

**What this ADR deliberately does not decide:** the transport and its address
family; the DTO shape and its versioning; the `Engine` façade's public surface as
seen through the API; authentication and authorisation; the CLI's command surface
as a client; and streaming or progress delivery. Where a lifecycle answer above
looks like it settles one of these, it does not — it states the constraint the
answer must satisfy.

**One thing ADR-0084's lane inherits as work, not as a constraint:** making the
CLI a client changes what ADR-0042 §2 and §7 describe. That lane owes ADR-0082
§1's test against ADR-0042, and this ADR does not pre-judge it.

### 15. Amendment records under ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in the later ADR's text: "A later
ADR's change is recorded on the earlier ADR exactly when the later ADR amends a
named clause of that earlier ADR", the test being whether "a reader holding only
the earlier ADR [would] now act differently, or read one of its clauses more widely
than it now holds". Applied here, clause by clause:

**No record is owed on:**

- **ADR-0042 §2.** Its clauses are that the façade "must not `close()` an owned
  resource while any underlying operation it started might still touch it" and
  that shutdown "awaits every tracked underlying operation to quiescence… before
  closing". §4 keeps both exactly: cancellation precedes the await, ADR-0054 makes
  the cancelled call release its connection only after its worker finishes, and
  nothing is closed before quiescence. `_drain_and_close`'s *docstring* states a
  stronger rule than §2's text; a docstring is not a ratified clause, and it is
  the lane's to correct (§4).
- **ADR-0014 §4.** It says the lease "is the generalisation and is deferred". §1
  declines it and it stays deferred. Its "presumes no executor is live… true for a
  single-user local app with one executor" stays true and becomes true for a
  stronger reason.
- **ADR-0064 §3.** "It must not refuse" is the right answer for a lagging mark and
  §6 does not touch that case. §6's rule refuses only where serving is silently
  wrong, which §3's case is not. Neither reads the other more widely.
- **ADR-0026.** Its Revisit clause is examined and does not fire (§9). Examining a
  revisit condition and finding it unmet changes nothing.
- **ADR-0007 §2, ADR-0074 §8, ADR-0076 §5, ADR-0077 §8, ADR-0078 §10 item 8.**
  Each defers a job *to* this scheduler; this ADR is what they deferred to. A
  deferral discharged by the ADR it named is a stacked addition, not an amendment
  — the deferring sentence stays true and now has an answer.
- **ADR-0033.** §1 is scoped to `_gather_contributions`. Declining to extend its
  shape to a different drain leaves every sentence of it true.
- **ADR-0060 §1.** §4's unbounded tail is the "documented as unbounded" form the
  clause names.

**One record *is* owed, and this lane does not write it.** **ADR-0054**'s
Consequences state, as fact, "the composition model does not cancel store writes
in practice", and its Decision rests the choice of mechanism (a) over (b) on the
same fact — "this is correctness insurance for a path the one-event-loop,
drain-on-`aclose` model does not currently exercise — not a hot path — [so] the
smaller mechanism is the right trade." §4 makes that path **live**: shutdown will
cancel store calls, routinely, on every stop that outruns phase A's budget. A
reader holding only ADR-0054 would act differently — they would treat a dormant
guard as dormant, and would read its "if a store ever grows a genuinely unbounded
sync op this trade would need revisiting" clause as hypothetical when it has
become operative. That fails ADR-0082 §1's test, so a record on ADR-0054 is owed:
its `Status` line and an appended dated note (ADR-0082 §2 — ADR-0054's `Status` is
plain `Accepted`, not a leading-token line, so the qualifier belongs on it).

**It is left undone here, and the reason is this lane's scope and nothing else.**
Two things that are *not* the reason are worth ruling out, because both are
plausible and both are wrong:

- **Not because ADR-0082 leaves the timing open.** It decides *whether* a record
  is owed and *where* it goes rather than *when* it is written, and §1's operative
  half — "the judgement is made in the later ADR's text, which is where it is
  reviewed" — is satisfied above. But that is an argument for the record being
  reviewable here, not for it being absent.
- **Not because this ADR is still `Proposed`.** The corpus settles that in the
  other direction, in as many words: ADR-0045's own note says "ADR-0080 lands **in
  the same change as this note**, so this Status line never names an ADR that does
  not exist — the hazard ADR-0070 §1 guards against — and if that change does not
  land, neither does this. While ADR-0080 is still `Proposed`, this line names a
  supersession that is drafted rather than ratified, which is the form ADR-0075
  established and `main` carries three times over." ADR-0074's header carries the
  same sentence about ADR-0076. The existence condition is that the naming ADR
  **ships in the same change**, not that it has ratified. So a record on ADR-0054
  naming this ADR while it is `Proposed` would be well-formed, and the corpus's
  established form is that it lands here.

**The reason is the fence.** This lane was dispatched with `docs/adr/0083-*.md` as
its whole scope and an explicit instruction to flag rather than write a record on
an earlier ADR. Widening a PR into a second `docs/adr/` file is the dispatcher's
call, not the author's, and `docs/adr/**` sits inside ADR-0027 §3's review floor
for every persona, so the edit costs a round wherever it lands. It is therefore
**flagged rather than taken quietly**, and tracked as **#529**, whose earliest
correct home is this ADR's ratification change.

Nothing in this ADR depends on the record existing first: §15's analysis is the
substance and the `Status` edit is its bookkeeping. What the deferral does cost is
real and is named here rather than discovered later — between this ADR's merge and
#529's, `main` carries an ADR-0054 whose Consequences assert something ADR-0083 §4
has made false.

## Consequences

- **The system gains a process, and a package.** `ai_assistant/service/` holds the
  entry point, signal handling, the instance lock, exit-code mapping and the
  scheduler, above `app` and importing no subsystem. A `lint-imports` contract
  expresses that; the edit is the implementing lane's.
- **`core` gains config and one error class**, no Protocol and no `core/types.py`
  model: `Settings.data_dir`, `Settings.shutdown_drain_seconds`, one interval
  field per scheduler job, and a state-incompatibility `AssistantError`. Contract
  surface, so this ADR takes the architecture review — but no triad, because a
  triad is what a Protocol owes.
- **`Engine` gains a maintenance surface** and `_drain_and_close` gains a bounded
  first phase with a cancel-then-await second one. Its docstring must end up true.
- **The one guard on ADR-0078 §10 item 8 inverts rather than dying** (§11). This
  is the change most likely to be done wrong by deletion, which is why it is
  ratified rather than left to the lane.
- **ADR-0054's insurance is cashed.** Its regression tests already cover the path
  §4 makes live; what changes is that a failure there stops being theoretical. The
  amendment record it is owed is flagged, not written (§15).
- **A `SIGKILL`ed hub becomes a deployment misconfiguration rather than normal
  operation** — D2 is the line, and S5 is what makes it checkable.
- **The roadmap's leg-5 job list is one job shorter than it reads.** Confirmation
  deadlines are blocked on a contract ADR-0059 §3 deferred (#333) and on a wiring
  gap (#525), and the deadline itself is enforced at answer time regardless, so
  nothing is unenforced (§7). Both become prerequisites of a named job rather than
  loose bugs.
- **#526, #505 and #305 stop being leg 5 blockers** and become, respectively,
  consistency work, a deliberately deferred durability decision, and ordinary test
  backlog (§12).
- **What is harder:** anything wanting two processes over one data directory now
  argues against a ratified rule, and the argument has to include ADR-0014 §4's
  lease and ADR-0074 §11's transactional posture, both of which exclusivity is
  currently standing in for. That is the intended cost.
- **Revisit when** a second host or spoke makes exclusivity a constraint rather
  than a simplification; when a job's runtime approaches its interval (§7); when a
  job needs a durable last-run, which is what makes a monotonic seam owed (§9); or
  when configuration needs to change without a restart (§13).

## Alternatives considered

- **Bind the ADR to systemd** — a unit file, `sd_notify` readiness, its restart
  semantics as the contract. Rejected: the deployment changes from a laptop to a
  dedicated box (ruling 1), so the supervisor is the one thing not to hard-code.
  §3 states a contract a supervisor satisfies instead, and names systemd only as a
  realisation of it.
- **Client-driven autostart** — the CLI spawns the hub if it is not running.
  Rejected by ruling 3, and independently by ruling 2: a hub that starts because
  someone typed a command has no legible reason for being down, because it never
  visibly is.
- **A lease on `RUNNING`** — ADR-0014 §4's own generalisation. Rejected in §1:
  durable state with renewal and crash-safe expiry, for a peer exclusivity
  guarantees does not exist.
- **Keep the drain unbounded and document it as unbounded** — which ADR-0060 §1
  would permit outright. Rejected for phase A: unbounded means the supervisor's
  stop timeout decides the shutdown, and its verdict is `SIGKILL`, which destroys
  exactly the ADR-0029 §4 bookkeeping the drain exists to preserve. The bound is
  what makes the graceful path reachable.
- **ADR-0033's bounded-and-abandon** — rejected in §4 at length. Its dominance
  argument holds where the straggler suppresses cancellation and awaiting cannot
  stop it; here every party honours cancellation, ADR-0054 makes cancelling
  connection-safe, and the abandoned party would hold a SQLite connection the next
  statement closes.
- **Escalate on a second `SIGTERM`** to an abrupt exit. Rejected in §4: `SIGKILL`
  already provides that, uninterceptably, and an in-process version only adds a
  second way to lose the bookkeeping.
- **The scheduler as `Engine`-owned `asyncio.Task`s.** Rejected in §8: it puts
  cadence inside `orchestration`, and the tracking it would buy is already had,
  because a job whose body is a public façade call is in `_inflight` anyway.
- **A durable schedule** — persist each job's last run, catch up on start.
  Rejected in §7 and §9: a missed tick is never a correctness bug (ADR-0007 §2),
  so there is nothing to catch up, and it would be new durable state under §6's
  discipline bought for nothing.
- **Add a monotonic seam now.** Deferred in §9 with its trigger named, rather than
  ratified speculatively — and, when owed, in ADR-0026's alias-plus-guard shape,
  not as a Protocol.
- **Delete the sweep guard test.** Rejected in §11: it is the only mechanical
  expression of ADR-0078 §10 item 8, and inverting costs one assertion.
- **Use the API's socket bind as the single-instance mechanism.** Rejected in §14:
  it makes exclusivity — a ruling — depend on a transport choice ADR-0084 has not
  made, and some transports provide no such guarantee at all.
