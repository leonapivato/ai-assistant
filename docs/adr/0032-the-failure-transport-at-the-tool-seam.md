# 32. The failure transport at the tool seam

- Status: Proposed
- Date: 2026-07-21
- Decides what ADR-0031 §3 named and declined — issue #192. ADR-0029 §3
  ratified a vocabulary of eight `ToolFailureKind`s; six of them have no
  carrier, so an integration cannot report any of them. This gives them one.
- Amends on ratification: ADR-0029 §§3–4 and its Consequences, with dated notes on
  ADR-0031 and ADR-0014. The edits are **not** made by this change — §8 records
  their exact form and why they wait, following ADR-0026 §6, ADR-0030 §6 and
  ADR-0031 §7.
- **Additive, and that is the whole argument for the shape chosen.** No
  Protocol signature moves, no type narrows, and `ToolImplementation`'s return
  type is untouched. A tool that raises a plain exception still gets `INTERNAL`,
  exactly as today. It is still a substantive contract ADR — it adds a ninth
  `core` name — so it merges as its own PR ahead of any implementation
  (golden rule 5, ADR-0015 §5).
- Does **not** implement anything, and **does not designate the `tools/` egress
  seam**. ADR-0017 §3's conditions are inherited undischarged, exactly as
  ADR-0029 §7 leaves them.

## Context

`ToolImplementation.__call__` returns `FrozenJson` — the tool's output and
nothing else. So a tool has exactly two channels: return a value, or raise. The
seam turns any escaping exception into `INTERNAL` (ADR-0029 §3), and
`ToolImplementation`'s own docstring records the consequence in terms:

> An implementation **raises** to report a failure it cannot classify; the seam
> turns that into an `INTERNAL` result. One that can classify its own failure
> returns nothing useful by raising — it should be given the vocabulary of
> `ToolFailureKind` by a future integration ADR, which this one does not decide.

That is this ADR.

**Of ADR-0029 §3's eight kinds, two are reachable and both are the seam's own.**
`INTERNAL` is synthesised from an escaping exception; `TIMED_OUT` is synthesised
when this seam's deadline expired. The other six —`INVALID_REQUEST`,
`NOT_AUTHORISED`, `UNAVAILABLE`, `RATE_LIMITED`, `REFUSED` and `CANCELLED` — are
integration-facing by ADR-0029 §3's own table, and none has a carrier.
ADR-0031 §3 moved `CANCELLED` into that group deliberately, taking it from
unreachable-by-construction to unreachable-pending-a-decision, and recorded that
the decision was #192's and not its own.

**The consequence is concrete and it is not cosmetic.** An upstream 429 arrives
as `INTERNAL`, which is not retryable, where `RATE_LIMITED` is. ADR-0029 §5's
retry algebra — the two-conjunct rule, the idempotency window, the fail-closed
clock reading — is inert for every real failure an integration could classify,
because the only kind it will ever see says "the tool implementation is broken".
ADR-0031's Consequences say so: "ADR-0029 §5's retry algebra stays inert until an
integration ADR gives a tool a way to classify its own failure."

**Why this is not a defect in ADR-0029.** ADR-0029 §1 leaves the callable's shape
to `tools/` on ADR-0008's precedent — "How the callable is reached is
`tools/`-internal, and this ADR does not contract it" — and the transport is part
of that shape. Ratifying the vocabulary without the transport was the right
split at the time; landing the transport is the deferral working, not a
correction of it.

**This blocks the executor lane (#187).** An executor's retry decision reads
`result.failure.kind.retryable` (ADR-0029 §5, §8). Written today it would be a
branch with one reachable arm. A decision that leaves the transport ambiguous
unblocks nothing, so the shape is decided here rather than inside an
implementation PR where it would not get architecture review.

**One thing #192 does not name, and it is the piece that makes the transport
honest.** A tool whose HTTP request timed out at the transport layer — the
socket closed with no response — is the **only** party that knows its side
effect may have landed. Its declaration cannot say it (a declaration is static),
the seam cannot say it (its own deadline did not fire), and today the tool
cannot say it either. That is genuinely ADR-0014 §4's ignorance, reached through
a third door, and it has no spelling. §2 gives it one.

## Decision

We will let a tool **raise a `core` exception carrying a `ToolFailure`**, which
the seam translates into a `ToolResult` — and keep the *outcome* the seam's
ruling, computed from the registry's trusted declaration and one fact the tool
reports.

> **Kind is what the tool knows. Outcome is what the seam rules.**

That sentence is the whole design, and every clause below is it applied to one
case.

### 1. `ClassifiedToolError`, in `core/errors.py`

```python
class ClassifiedToolError(AssistantError):
    """A tool reporting a failure it classified itself (ADR-0032 §1).

    Raised by a ``ToolImplementation`` that knows *why* it failed, and caught
    by ``ToolInvoker.invoke``, which turns it into a ``ToolResult``. It never
    escapes ``invoke``.

    Not a ``ToolError``: that branch holds the seam's own faults, which an
    executor must never turn into a retryable result (ADR-0029 §8). This is the
    opposite — a value in flight, on its way to becoming one.
    """

    def __init__(self, failure: ToolFailure, *, effect_may_have_committed: bool) -> None: ...

    failure: ToolFailure
    effect_may_have_committed: bool     # §2 — a fact, not an outcome
```

**It carries a constructed `ToolFailure`, not a `kind` and a `str`.** One
validated value rather than two loose ones, and the validation happens where it
is useful: `ToolFailure._message_is_present` (ADR-0029 §3) fires inside the
tool's own frame, at the raise site, where the author can see it. A tool that
raises with a blank message gets a `ValidationError` before the exception
exists, which escapes as an ordinary exception and becomes `INTERNAL` — the
fail-closed direction, at no cost. That is the *ordinary* path and not a
guarantee: `model_construct` bypasses every validator while still satisfying
`isinstance`, which is why §6 revalidates at the seam rather than trusting that
the raise site did.

**It is an ordinary `Exception` by inheritance and specifically not a
`BaseException`.** ADR-0029 §3 makes `BaseException` propagate unchanged, so a
carrier outside `Exception` would be swallowed by that rule rather than caught
by this one.

**It sits under `AssistantError` but not under `ToolError`, and the placement is
load-bearing.** `ToolError`'s two existing children are `ToolRegistrationError`
and `ToolBindingError` — both faults *the seam raises*, and ADR-0029 §8 spends a
paragraph on why an executor must never derive a retry from either: "retry is
scheduled only from a `ToolResult`, never from an exception". `except ToolError`
is a plausible line for an executor or an interface adapter to write. It must
not catch a carrier, because the carrier's whole purpose is to *become* a result
the executor may retry. Keeping it off that branch means the conflation is not
available. `AssistantError` still holds it, so `core/errors.py`'s stated
invariant — "All errors raised by the application inherit from `AssistantError`"
— is preserved.

**Its home is `core/errors.py`, and the decisive argument is the canonical
fake.** ADR-0029 §1 leaves the callable's shape to `tools/`, so `tools/` is the
obvious home and it is wrong. `ai_assistant.testing.invoker` implements the same
contract and **must not import `ai_assistant.tools`** — ADR-0031 §1 records the
reason in terms: it "re-implements the rules rather than importing
`ai_assistant.tools`: importing it would defeat the purpose, since a consumer's
tests would then pull in the very subsystem the fake stands in for". A
`tools/`-homed carrier leaves the fake two options, and both are the failure
ADR-0031 §1 exists to remove: import `tools/` (golden rule 1, and
`lint-imports` would allow it only because `testing` is not `orchestration` —
the rule's spirit fails either way), or declare a second, structurally-equal
exception type, so that a tool written against one is uncatchable by the other.
An exception type is not a parallel declaration the way `FakeToolImplementation`
is: `FakeToolImplementation` is held to observable behaviour by the shared suite,
whereas two exception classes are held to nothing — `except` keys on identity,
so a divergence is silent and total rather than a test failure.

**And it is not a boundary violation to put it there.** Golden rule 2 is
satisfied trivially: it imports `ToolFailure` from `core/types.py` and nothing
else. Golden rule 1 is satisfied *because* of the placement rather than despite
it — the rule forbids one subsystem importing another's concrete module, and a
`core` home is what lets `tools/`, `testing/`, and any future integration reach
one type without any of them importing each other. `ToolRegistrationError` is
the precedent directly on point: registration is `tools/`-internal by ADR-0016
§5, and its error type lives in `core/errors.py` anyway. And ADR-0031 §8 gives
the ergonomic half of the same argument for `CANCELLED`'s docstring — "A member
docstring in `core` is where an integration author reads the vocabulary."
`ToolFailureKind` is in `core`; the way to raise it should be beside it.

**What is *not* contracted here, so §1 of ADR-0029 stays intact.**
`ToolImplementation`'s signature does not move: its parameters, its
keyword-only `idempotency_key`, and its `FrozenJson` return type are unchanged
and remain `tools/`-internal. What this ADR adds is a `core` exception a
callable of *any* shape may raise. That is why it is additive: the two rejected
options in #192 — returning `FrozenJson | ToolFailure`, or returning a
`ToolResult` — both change the return type, and every implementation with it.

**And the second of those two is rejected for a reason beyond compatibility.**
Returning a `ToolResult` hands the tool `outcome`. ADR-0031 §2 spent a section
making that field tamper-resistant: a delta on `Task.cancelling()` captured
across the call, evaluated on the normal-return path as well as the raising one,
classified from the registry's **trusted binding** rather than the caller's
object, with a precedence rule when a cancellation and a deadline collide. Every
one of those exists because a callable's own account of what happened to it is
not evidence. Letting the callable return the field directly would hand it the
pen on exactly what that work protects, and would additionally require ADR-0029
§4's `INDETERMINATE` rule to be restated as an obligation on every integration
author — a safety-critical rule enforced by documentation, which is the shape
ADR-0031 §1 removed rather than added.

### 2. `effect_may_have_committed` — the fact the tool reports, the outcome the seam rules

**The tool answers one question, and only it can.** A request that failed at the
transport layer — no response, connection reset, a client-side abort after the
bytes went out — may or may not have committed its effect upstream. The
declaration cannot say which: `side_effecting` says the tool *can* act, not
whether this call did. The seam cannot say either: its own deadline did not
fire, so ADR-0029 §4's expiry rule never runs. This is the only fact in the
contract that lives exclusively in the integration.

> **`effect_may_have_committed` is keyword-only and has no default.** The
> raiser answers it explicitly, every time.

**No default, for ADR-0029 §4's reason about `timeout`.** Both candidate
defaults are wrong in a direction, so `core` must not pick one on the author's
behalf. `False` silently records a possibly-committed effect as
certainly-nothing-happened — the one direction ADR-0014 §4 refuses to guess in.
`True` floods the system with `INDETERMINATE`, which is never auto-retried and
must be resolved explicitly, which would disable the retry algebra this ADR
exists to enable. "The contract has no spelling for forever" is the same move:
the argument that cannot be defaulted safely is required instead. The cost is a
keyword on every raise, and it is the point — an author who has to type it has
to think about it once per failure path.

**The seam rules the outcome, and the rule is one line:**

> The outcome of a translated `ClassifiedToolError` is
> **`ToolOutcome.INDETERMINATE` when `effect_may_have_committed` is true *and*
> `definition.interrupted_outcome` is `INDETERMINATE`; `ToolOutcome.FAILED`
> otherwise.**

`definition` is the registry's own declaration for the bound tool, never
`call.request.tool` — ADR-0029 §4's rule, unchanged and for its stated reason.

**This conjoins the tool's fact with ADR-0031 §1's property rather than
restating it, which is deliberate.** ADR-0031 §1 moved the two-field comparison
into `core` precisely so there would be one copy: "two copies of a
safety-critical ordering, free to disagree, with nothing that fails when they
do." A fourth reader is what that clause was built for. Writing
`not side_effecting or idempotency is NATURAL` here would be the fourth copy.

**Why the conjunction and not the fact alone**, taken case by case:

- **A read-only tool reporting a possible commit.** Its declaration — the one
  the policy approved and the registry holds — says the operation has no effect
  to commit. The declaration is the trusted value and the runtime claim is not
  (ADR-0029 §1's chain: "the registry's original ≡ the declaration the policy
  approved ≡ the declaration being executed"). So the fact is ignored and the
  outcome is `FAILED`. Escalating to `INDETERMINATE` on a claim contradicting
  the approved declaration would let a tool manufacture a durable state that is
  never auto-retried and needs a human, on its own say-so.
- **A `NATURAL` tool reporting a possible commit.** Idempotent by nature
  (ADR-0016 §4), so whether it acted does not change what a repeat does.
  Ignorance costs nothing and `FAILED` is correct. This is exactly
  `interrupted_outcome`'s existing reasoning, reused rather than re-derived.
- **A `NONE` or `KEYED` side-effecting tool reporting a possible commit.**
  ADR-0014 §4's case exactly — "cannot be distinguished from a crash *before*
  the effect" — reached through a transport failure rather than through a crash
  or a deadline. Same answer: `INDETERMINATE`.

**The report is monotone: it can only make the outcome more ignorant, never
less.** There is no value of `effect_may_have_committed` that produces
`SUCCEEDED` — a raise is never a success — and none that overrides the seam's
own expiry or cancellation classification, which outrank it entirely (§4). The
worst a lying or careless integration achieves is `INDETERMINATE` for a call
that definitely failed: pessimistic, not auto-retried, resolved explicitly. That
is the direction ADR-0031 §2 calls "the safe direction" when it accepts a
manufactured cancellation delta for the same reason.

**The fact does not survive into `ToolResult`, and that is not an oversight.**
`outcome` is where the ruling lands, and `INDETERMINATE` already means "we do
not know whether the effect happened". A residual boolean on `ToolFailure`
would be a second spelling of the same thing, free to disagree with the field
the executor actually reads, in a value ADR-0029 §3 requires to round-trip into
a durable `StepExecution`. ADR-0029 §3 anticipated additive fields on
`ToolResult` for the disclosure report (#57) and for cost; this is not one of
them, because it is an input to a ruling rather than a report of one.

### 3. `TIMED_OUT` is reserved to the seam and refused; `CANCELLED` is the tool's and accepted

**The seam's deadline is the seam's alone.** ADR-0029 §4 is emphatic:
"`TIMED_OUT` means the seam's own deadline expired, and the seam must establish
that rather than infer it from an exception type", and ADR-0031 §2 named the
mechanism — `asyncio.Timeout.expired()`, "the seam's own state, and no callable
can reset it". A tool raising a failure whose kind is `TIMED_OUT` is the
misclassification §4 refuses, arriving by the front door instead of by
inference. So:

> **A `ClassifiedToolError` whose `failure.kind` is `TIMED_OUT` is refused.**
> The seam discards the tool-authored `ToolFailure` whole and synthesises its
> own `INTERNAL` failure, naming the reserved kind and the tool's id and
> nothing else. `effect_may_have_committed` is carried through unchanged and
> §2's outcome rule runs on it.

**Refused rather than remapped to a neighbour.** `UNAVAILABLE` is what the tool
should have raised and the seam must not choose it on the tool's behalf — that
is the seam interpreting a broken integration's meaning, which is one step from
interpolating its text. `INTERNAL` is what the vocabulary already means by "the
tool implementation is broken" (ADR-0029 §3), and a tool naming a kind the
contract reserves *is* broken. It fails safe: `INTERNAL` is not retryable, so
nothing is retried on the strength of a claim the seam rejected.

**The cost is nil, which is what makes refusal the cheap answer.** A tool whose
upstream reports its own timeout has an honest kind available — `UNAVAILABLE`,
"the upstream is unreachable or failing" — carrying the same `retryable=True`.
Nothing in the retry algebra is lost by the redirection.

**One ratified sentence points the other way, and it is reconciled rather than
ignored.** ADR-0029 §4 ends its interrupted-call rule with: "A tool that *can*
establish it did not act may return `FAILED` with `TIMED_OUT`; nothing can make
it prove the converse." Written when a tool could return nothing but
`FrozenJson`, it described a capability the contract did not yet grant — part of
the same #192 gap — and this ADR is what grants one, so the sentence has to be
answered rather than left standing.

**Its substance survives; its spelling does not.** What it protects is that a
tool which *knows* it did not act should get `FAILED` rather than the
`INDETERMINATE` the seam's own expiry rule would impose. That is exactly
`effect_may_have_committed=False`, and §2 makes it load-bearing: a
side-effecting, non-`NATURAL` tool reporting `False` gets `FAILED`, which is the
outcome §4's sentence asks for and could not previously produce. What does not
survive is the *kind*: the tool says `UNAVAILABLE` and not `TIMED_OUT`, because
under §2 the outcome no longer rides on the kind at all. §4's sentence pairs
them only because, before a transport existed, the kind was the only field a
tool could conceivably have set. Separating them is what lets `TIMED_OUT` keep
meaning "this seam's deadline expired" — the property ADR-0029 §4 spends its
longest paragraph establishing, one clause above the sentence in question.

So §4 is amended, and §8 records it: the sentence is superseded in its naming of
`TIMED_OUT` and honoured in what it was protecting.

**The effect fact survives the refusal, and that is why it is a field on the
exception rather than a field on `ToolFailure`.** A tool that got the kind wrong
may still be telling the truth about its side effect, and discarding that would
record a possible commit as certainly-nothing-happened. Structurally: the seam
can throw away the whole `ToolFailure` and keep the fact, because they are
separable values.

**`CANCELLED` is accepted as raised, and this ADR relies on ADR-0031 §3 rather
than reopening it.** That clause re-scoped the member to "what an integration
reports when its own upstream cancelled or aborted the operation — a remote job
the provider stopped, a batch the service abandoned", and stated that "the seam
never synthesises it". Refusing a raised `CANCELLED` here would leave the member
with no producer at all and contradict a ratified sentence three days old.
ADR-0031 §3 also already states how an integration chooses its outcome for it —
"`FAILED` only if it can establish the effect did not happen; `INDETERMINATE`
otherwise" — which is §2's rule spelled for one kind, and §2 is now the
mechanism that carries it.

**Every other member is accepted as raised, including `INTERNAL`.** The six
integration-facing kinds are the point of the ADR. `INTERNAL` is accepted
because a tool that knows it is broken saying so is not worse than a tool
raising an unclassified exception and being told so — same kind, same
`retryable`, better message. `TIMED_OUT` is therefore the *only* reserved
member, and stating the reservation as an enumeration of one rather than as a
category ("seam-owned kinds") is deliberate: a category drifts as members are
added, and ADR-0031 §5(b) took the same form for the same reason.

### 4. Precedence: a cancellation, then this seam's deadline, then the tool's classification

ADR-0031 §2(d) set precedence between two signals. This adds a third, **below
both**, and changes neither.

> 1. **A cancellation of the invoking task, read as ADR-0031 §2's delta.**
>    `invoke` raises `CancelledError`; no result is constructed, and the
>    carrier is discarded.
> 2. **This seam's deadline, read from `Timeout.expired()`.** `invoke` returns
>    the `TIMED_OUT` result ADR-0029 §4 specifies, with the outcome from
>    `definition.interrupted_outcome`. The carrier is discarded, fact and all.
> 3. **Otherwise, the tool's classification**, translated under §2 and §3.

**Rank 1 is ADR-0031 §2(c)–(d) unchanged.** A result cannot be returned from a
task being torn down, and the classified raise may itself be a consequence of
the cancellation — an SDK mapping its aborted request to `UNAVAILABLE` on the
way out. Answering a cancellation with a value is what ADR-0029 §4 forbids
everywhere.

**Rank 2 over rank 3 is the same "establish, don't infer" rule, applied to a
claim instead of to an exception type.** A tool that maps its aborted request to
`UNAVAILABLE` while the seam's deadline actually fired would, on a side-effecting
non-`NATURAL` tool, produce `FAILED` — certainly-nothing-happened for a call
that outran its budget — where ADR-0029 §4 requires `INDETERMINATE`. The seam
knows and the tool does not, so the seam's knowledge wins. Discarding the
carrier's fact along with it loses nothing: on this path the outcome is
`definition.interrupted_outcome` alone, which is `INDETERMINATE` in every case
where the fact could have mattered.

**This is an ordering, not a new branch, and the distinction matters for what
§8 amends.** ADR-0029 §4's expiry rule and ADR-0031 §2's cancellation rule run
unchanged and neither reads the carrier; ranks 1 and 2 are simply checked first.
The `ClassifiedToolError` handler sits exactly where the `except Exception`
handler sits today — after the interruption check, not before it.

**ADR-0031 §2(b)'s postcondition is untouched and gains a second subject.** As
ratified it reads: "before a `SUCCEEDED` result is constructed, the seam
re-reads the deadline and the cancellation delta, and an interruption found
there wins over the returned value." That sentence names `SUCCEEDED` because a
normal return was the only path that constructed a result from something the
callable produced. This ADR adds a second, so the rule is stated in the form
that covers both:

> **Before *any* result is constructed, the seam re-reads the deadline and the
> cancellation delta**, and an interruption found there wins.

**This is not pedantry: §6's revalidation is tool-supplied code, and it runs
after the check.** A `ToolFailure` subclass whose `model_dump()` calls
`cancel()` on the invoking task and then returns a perfectly valid mapping
raises the delta *between* the interruption check and the result — so a seam
that checked only on entry to the handler would return a `FAILED` result from a
task carrying a pending cancellation, which is rank 1 violated by the mechanism
§6 introduced. Reading the carrier at all is what creates the window, so the
re-read closes it where it is opened.

A callable that catches its own cancellation *and* raises a
`ClassifiedToolError` is covered by rank 1 on the first read; this second read
is for what the carrier does while being read.

### 5. The message crosses the seam by value and unedited, or not at all

ADR-0029 §3 makes `ToolFailure.message` Tier 2 text authored by its producer,
and states the rule in two halves — the integration authors its own text, and a
message the *seam* generates "carries no content it did not author", explicitly
never interpolating `str(exc)`, which `core/logging.py`'s docstring names as the
Tier 1 leak its key-based redactor cannot see. Both halves stand. What changes
is that a **tool-authored** message now crosses the seam directly, where
previously every message on the failure path was the seam's own.

**Where it goes, stated precisely, because "reaches a log" is the imprecision
that would license the seam to log it.** The message lands in
`ToolResult.failure.message` on every translated failure, and nowhere else *by
the seam's hand*: the seam's own log line for a translated failure carries the
tool's id and `failure.kind`, per the enumeration below, and never the message.
Its onward destinations are the executor's — `StepExecution.error` when the
outcome is `FAILED`, and whatever an interface renders. That is exactly what
ADR-0029 §3 means when it says the string "is bound for a log and for
`StepExecution.error`", and it is why the Tier 2 obligation on the producer is
the only defence: the seam declining to log it does not stop it being logged one
frame away.

**And it does not reach `StepExecution.error` when the outcome is
`INDETERMINATE`, an asymmetry inherited rather than chosen.** `StepExecution`
refuses an `error` on any status but `FAILED` — "error is only valid for a
FAILED step" (ADR-0014 §3) — so the message a tool wrote for the case where its
effect *may have landed*, which is the case an operator most needs to read,
survives only in whatever the executor logged. Widening
`StepExecution` is an ADR-0014 change, breaking under golden rule 5 and
belonging to the planning lane; making it from a tools ADR is what ADR-0018 §2
refused and ADR-0031 §5(b) refused again. It is also not new — a deadline expiry
already produces an `INDETERMINATE` whose `TIMED_OUT` message goes nowhere
durable — so this ADR widens the set of failures that hit it rather than
creating it. Filed as **issue #208** rather than fixed, beside ADR-0029 §8's related follow-up
that a failure *kind* does not survive a restart either.

The seam's obligation is stated by enumeration, following ADR-0031 §5(b), so
that what it binds cannot drift:

> **`invoke` either passes the raised `ToolFailure` through by value, or
> discards it whole** (§3's reserved kind, and §4's ranks 1 and 2). There is no
> third behaviour: the seam never edits, wraps, prefixes, truncates or
> re-authors a tool's message.
>
> "By value" is through §6's revalidation, which applies `ToolFailure`'s **own**
> validators and nothing else — so a message is stripped exactly as
> `ToolFailure(...)` would have stripped it at the raise site, and is otherwise
> untouched. That is a no-op for every failure the tool constructed normally,
> since construction already normalised it. What is forbidden is content the
> seam chose.
>
> **And nothing derived from the exception object enters a message or a log.**
> Not `str(exc)`, not `repr(exc)`, not `exc.args`, not `exc.__cause__` or
> `exc.__context__`, not `exc.__notes__`. What the seam may log about a
> translated failure is the tool's id and `failure.kind` — an identifier and a
> member of a closed enum.

**The cause chain is the specific hazard, and it is a new one.** The natural way
to write an integration is `raise ClassifiedToolError(...) from upstream_exc`,
which is good practice and should stay possible — the chain is exactly what a
developer wants in a traceback. It is also where the upstream's error body
lives, quoting a recipient or a subject line, which is the leak ADR-0029 §3
describes. Keeping the chain out of everything the seam renders is what makes
`from` safe to write. `internal_failure` already has the right shape for this
(`error_type=type(exc).__name__`, "The type, never the instance"), and this
extends it to the carrier.

**There is no safety net under the tool's own message, and this ADR widens the
exposure rather than closing it — say so plainly.** ADR-0029 §3 is candid that
the redactor cannot catch a Tier 1 value under an innocuous key, and that the
rule "has to hold at the producer". Until now the producer of every failure
message was `core` or `tools/`. From here it is an integration author, and no
type can check that the string they wrote contains no recipient. Three things
bound it, and none is a claim that it is closed:

- **The obligation is the one ADR-0029 §3 already wrote**, now load-bearing
  rather than aspirational: "Copying an upstream error body into it is the leak,
  not a shortcut to one." That sentence was written for exactly this moment.
- **The seam's half is mechanically pinned** by §9's suite cases, so the half
  that *can* be enforced is.
- **No integration exists to leak yet.** ADR-0017 §3's egress conditions are
  undischarged and `tools/` transmits nothing (ADR-0029 §7), so the first real
  producer of a tool-authored message arrives with its own ADR, which is the
  right place to bind the review obligation.

**The carve-out is narrow on purpose: it is `ToolFailure`'s validators or
nothing.** The seam may not add a rule of its own — no length cap, no character
filter, no redaction pass — because each would be the seam editing text it did
not write, and a truncated message is one the seam partly authored. What §6
re-runs is exactly what the raise site ran.

**Issue #197 is untouched.** Whether an identifier may appear in a log-bound
message is ADR-0031 §5(b)'s recorded non-decision, and nothing here ratifies or
forbids it.

### 6. The carrier is revalidated, and a malformed one is an ordinary escaping exception

ADR-0029 §4 established that "the annotation is not the enforcement", and made
`invoke` check `timeout`'s runtime value rather than trust its type. The same
applies here, and more sharply: an exception's attributes are ordinary
attributes, an integration is not required to have been type-checked, and
**`isinstance` is not evidence that a pydantic model was validated.**
`ToolFailure.model_construct(kind="rate_limited", message=" ")` bypasses every
validator, satisfies `isinstance`, and carries a `str` where a `ToolFailureKind`
belongs — so a downstream `result.failure.kind.retryable` is an `AttributeError`
rather than a retry decision, and the blank message §1 relies on
`_message_is_present` to refuse arrives in a result. `model_validate` on the
instance does not help: pydantic's default `revalidate_instances="never"`
returns it unchanged.

**The round-trip repairs what it can and refuses what it cannot, and the line
between them is pydantic's own.** `"rate_limited"` is a valid `ToolFailureKind`
value, so validation coerces it to the member and the result is a correct
`ToolFailure` — the `AttributeError` above is gone, which is the outcome to
want. A string that names no member, a missing field, an extra one under
`extra="forbid"`, or a message that renders as nothing does not survive, and
that is the refusal. Requiring an exact runtime type instead would refuse a
value pydantic can make correct, for no gain: the seam's obligation is that what
reaches a `ToolResult` is valid, not that the tool built it in the approved way.

So the rule is a revalidation, in ADR-0018 §4's own idiom — the one
`InMemoryToolRegistry` already uses for a definition, `model_dump()` then
`model_validate()`, which is what forces the validators to run:

> **`invoke` revalidates the carrier before reading it, and validates its two
> attributes independently.** The failure it translates is
> `ToolFailure.model_validate(exc.failure.model_dump())` — a validated, detached
> value. `effect_may_have_committed` must be a `bool`.
>
> - **If the failure is absent, is not a `ToolFailure`, or does not survive the
>   round-trip**, the payload is refused: the seam synthesises its own
>   `INTERNAL` failure, with its own message, exactly as for an ordinary
>   escaping exception (ADR-0029 §3).
> - **If `effect_may_have_committed` is absent or is not a `bool`**, the *whole
>   carrier* is refused: the seam synthesises its own `INTERNAL` failure and the
>   outcome is `FAILED`, whatever the payload said.
> - **A `bool` that validates is honoured either way.** §2's outcome rule runs
>   on it even when the payload was refused.
>
> Nothing derived from the `ValidationError` that refusal produces enters a
> message or a log, under §5's enumeration — it is raised *about* the payload
> and would render it.

**The fact survives a refused payload, for §3's reason applied twice.** §3
already keeps `effect_may_have_committed` when it discards a `TIMED_OUT`
failure, because "a tool that got the kind wrong may still be telling the truth
about its side effect, and discarding that would record a possible commit as
certainly-nothing-happened". A tool that built its `ToolFailure` with
`model_construct` is in precisely that position, and its request may still have
landed. Dropping the fact would make §6 the one path in this ADR that resolves
an ambiguity in the direction ADR-0014 §4 refuses — and would do so on the
malformed input most likely to come from a *careless* integration rather than an
adversarial one. So a side-effecting, non-`NATURAL` tool that raises a garbage
payload with `effect_may_have_committed=True` gets `INDETERMINATE` with an
`INTERNAL` kind: the seam says "this tool is broken *and* we do not know whether
it acted", which is both of the true things.

**Reading the two independently is what makes that possible**, and it is the
second reason the fact is a field on the exception rather than on `ToolFailure`
(§2). A `failure` property that explodes must not take the `bool` down with it,
so each attribute is fetched under its own guard and judged on its own.

**The converse does not hold, and the asymmetry is the rule rather than an
inconsistency in it.** A bad payload costs the *kind*; a bad fact costs the
*carrier*. Each defect resolves in its own pessimistic direction, and the two
directions are not the same:

- **Losing the fact would be unsafe**, because the lost value might be `True`
  and the loss records a possible commit as certainly-nothing-happened —
  ADR-0014 §4's forbidden guess. So it is kept.
- **Losing the kind is safe**, because what a refused kind costs is a
  `retryable=True` the seam has no reason to trust. A carrier missing a
  *required, keyword-only* argument never went through `__init__`, so nothing
  about it was checked — and reporting a confident `RATE_LIMITED` from it is the
  seam authorising a retry on the strength of an object that was assembled
  around its own constructor. `INTERNAL` is not retryable, which is the
  fail-closed answer.

So the fact is preserved when the payload is bad, and the payload is discarded
when the fact is bad. Both rules point the same way — toward the outcome that
retries less and knows less — which is the direction every other unclosable
question in this contract resolves (ADR-0031 §2, §4).

**Absent, not merely wrong**, because `del exc.failure` on a constructed carrier
is as reachable as assigning `None` to it, and an implementation that reads the
attribute directly raises a raw `AttributeError` out of `invoke` where the rule
requires a result. The reads are by sentinel, so the total path is total.

**And the reading itself is guarded, because every step of it is code the tool
supplies.** `isinstance` admits a subclass, so `exc.failure.model_dump()` is a
dispatch to a method a tool may have overridden, and `exc.failure` is an
attribute access a tool may have made a property. Either can raise — and an
exception raised inside an `except` body is **not** caught by the sibling
`except` clauses of the same `try`, so it leaves `invoke` uncaught, which is
exactly the outcome §6 exists to prevent, reached by the mechanism §6
introduced.

> **Reading, revalidating and translating the carrier happens inside its own
> guard.** Any `Exception` raised by the attribute access or by the round-trip
> is an ordinary escaping exception: `INTERNAL`, with the seam's own message,
> and nothing derived from it rendered (§5). `BaseException` propagates
> unchanged, as ADR-0029 §3 requires everywhere else.

The general form of the rule, which is the durable part: **the seam's total
failure path may not itself contain an unguarded call into tool-supplied code.**
ADR-0029 §3 draws the same boundary one layer up — "a guard whose own failure
modes bypass the failure path it specifies is enforcing nothing" — and this is
that sentence applied to the guard this ADR adds.

This is ADR-0029 §2's own ordering rule applied one layer down: revalidate and
detach *first*, then read, because "a mutation landed after construction cannot
survive into execution". Letting an unvalidated value through into `ToolResult`
construction instead produces a `ValidationError` from inside `invoke`'s own
frame — the raw-error-out-of-a-classifying-method failure ADR-0029 §2 orders its
three checks to avoid — and letting it through *silently*, which
`model_construct` makes possible, is worse: a broken value in a durable
`StepExecution` rather than a loud rejection.

**A valid failure is unchanged by the round-trip**, so the pass-through §5
requires is exactly a pass-through: `_message_is_present` strips and returns,
and `ToolFailure` is frozen with `extra="forbid"`. The cost is one dump and one
validate on a failure path.

### 7. What this does not change

Named because a transport ADR reads like an invitation to redesign the seam.

- **`ToolImplementation`'s signature.** Parameters, the opaque
  `idempotency_key`, and the `FrozenJson` return type are unchanged and remain
  `tools/`-internal (ADR-0029 §1). Only the docstring's deferral sentence is
  retargeted (§9).
- **Everything in ADR-0029 §4 and ADR-0031 §2 bar one sentence.** The seam's
  ownership of the deadline, the strictly-positive check, the interrupted-call
  rule, `TIMED_OUT` meaning *this* deadline, `Timeout.expired()` as the
  tool-proof signal, the cancellation delta on both paths, and the four declared
  limits — including ADR-0031 §4's `uncancel()` residue and its pinned suite
  case. The exception is §4's "may return `FAILED` with `TIMED_OUT`", withdrawn
  in its kind and preserved in its substance by §3 above.
- **ADR-0031 §1's `interrupted_outcome`**, which this ADR reads and does not
  restate, and ADR-0031 §3's re-scoping of `CANCELLED`, which it relies on.
- **`ToolResult`'s invariants and `retryable`'s values** (ADR-0029 §3). Six
  kinds become producible; not one of them changes meaning.
- **ADR-0029 §5's retry conjunction.** This ADR makes conjunct 1 answer
  something other than `False`; it does not touch conjunct 2, the window, the
  fail-closed clock reading, or the rule that an `Idempotency.NONE`
  side-effecting tool is never auto-retried.
- **ADR-0029 §6's credential rule.** No credential crosses the seam in either
  direction; a `ToolFailure` is not a route around it, and an integration
  quoting a rejected token into a `message` violates the Tier 2 rule §5 states.
- **ADR-0029 §7's exclusions and §8's executor obligations**, which stay #187's.
  In particular, `StepExecution.error` is still an unstructured `str`, so a
  failure kind still does not survive a restart — ADR-0029 §8's recorded
  follow-up, unaffected either way.
- **ADR-0017 §3's egress conditions.** Inherited whole and undischarged.

### 8. What ratification does to ADR-0029, ADR-0031 and ADR-0014

ADR-0017 §7 requires the operation performed on another ADR to be recorded
rather than inferred, and ADR-0026 §6 sets the form for an ADR that merges as
`Proposed`: the edit is **not** made by this change, because writing "amended by
ADR-0032" onto a ratified ADR while ADR-0032 is only proposed is the state claim
ADR-0019 forbids. Recorded here in the exact form to apply on ratification.

**ADR-0029 earns a `Status` change; ADR-0031 and ADR-0014 earn dated notes
only.** ADR-0029 §9 and ADR-0030 §6 set the test between them, and it is applied
rather than asserted:

- **ADR-0029.** ADR-0030 §6's case. §3 ratifies a classification rule — "An
  exception escaping the tool implementation becomes `INTERNAL`" — stated
  without qualification, and this ADR narrows the set of exceptions it covers.
  §4 ratifies a permission — "A tool that *can* establish it did not act may
  return `FAILED` with `TIMED_OUT`" — and §3 above withdraws the kind it names
  while §2 preserves what it protects. Its Consequences ratify an enumeration of
  the `core` surface, already corrected once by ADR-0031 and corrected again
  here. Three ratified sentences now read as false. That is a change to a past
  decision in ADR-0001's sense.

  **§4 is amended in that one sentence and in nothing else**, which is worth
  stating because §4 is long and mostly about the seam's deadline. Its ownership
  of the deadline, its strictly-positive check, its interrupted-call rule, its
  `TIMED_OUT`-means-*this*-deadline rule, its provenance rule and its four
  declared limits all stand exactly as ratified and as ADR-0031 amended them.
- **ADR-0031.** ADR-0029 §9's case, and specifically the ADR-0014 half of it.
  Nothing ADR-0031 *decides* changes: §1's property is read by a new caller
  without its text moving, and §3's re-scoping is relied on rather than altered.
  Its Consequences observe that "five of the eight failure kinds still have no
  carrier (#192)" and that the retry algebra "stays inert until an integration
  ADR gives a tool a way to classify its own failure" — but §3 states in terms
  that "Nothing here decides the transport", so those sentences record a
  deferral with a named owner rather than ratify a rule. A later ADR taking up
  an explicit deferral is that deferral working as designed. The prose still
  becomes wrong for a reader, which is what earns the note.
- **ADR-0014.** ADR-0029 §9's exact precedent, one step on. §4's transition
  table names the trigger for `RUNNING → INDETERMINATE` in prose; ADR-0029 added
  a second, and §2 above adds a third that is neither a deadline nor a
  cancellation. No legal move is added or removed and `PlanExecution` validates
  the move rather than the trigger, so no implementation changes — but "the
  table's trigger column is prose a reader relies on", and ADR-0019's lesson is
  that an unrecorded widening is the kind that goes unnoticed.

#### ADR-0029

- **ADR-0029's `Status` line becomes**
  `- Status: Accepted, §§1, 3–4 and Consequences amended by ADR-0031; §§3–4 and Consequences amended by ADR-0032`.

  ADR-0031's clause is carried forward unchanged rather than replaced: it is not
  withdrawn, and a `Status` line that dropped it would make ADR-0031's amendment
  invisible to a reader who consults ADR-0029 alone.

- **A dated note is appended to ADR-0029's header, after the existing
  `Amended:` block for ADR-0031:**

  `Amended: <ratification date> by ADR-0032 — §3's "an exception escaping the
  tool implementation becomes INTERNAL" now holds for every exception but one. A
  ToolImplementation that can classify its own failure raises
  ClassifiedToolError, an AssistantError in core/errors.py — deliberately not
  under ToolError, whose branch holds seam faults an executor must never retry —
  carrying a constructed ToolFailure and the keyword-only, undefaulted fact
  effect_may_have_committed; invoke translates it into a ToolResult rather than
  into INTERNAL. §3's message rule is unchanged and gains a second half: the
  seam passes a raised ToolFailure through by value or discards it whole, adding
  no rule of its own beyond the revalidation below — which applies ToolFailure's
  own validators and is a no-op on any failure constructed normally — and
  renders nothing derived from the exception —
  str(), repr(), args, __cause__, __context__, __notes__ — into a message or a
  log. Kind is what the tool knows; outcome stays the seam's ruling. The outcome
  is INDETERMINATE when the tool reports the effect may have committed and the
  registry's definition.interrupted_outcome is INDETERMINATE, and FAILED
  otherwise, so a tool's report can only make an outcome more ignorant, never
  less, and never reaches SUCCEEDED. TIMED_OUT is reserved to the seam: a raised
  failure naming it is refused, the tool-authored ToolFailure discarded whole
  for the seam's own INTERNAL, with effect_may_have_committed carried through.
  CANCELLED is the integration's by ADR-0031 §3 and is accepted; every other
  member is accepted as raised. §4's permission for a tool that can establish it
  did not act to return FAILED with TIMED_OUT is withdrawn in its kind and kept
  in its substance: the outcome no longer rides on the kind, so such a tool
  reports effect_may_have_committed=False with an honest kind — UNAVAILABLE for
  an upstream that did not answer — and §2's rule gives it the FAILED that
  sentence was protecting, while TIMED_OUT keeps meaning that this seam's
  deadline expired. §4's precedence gains a third rank below the two
  it has — a pending cancellation, then this seam's expired deadline, then the
  tool's classification — and §4's cancellation and expiry branches are
  themselves unchanged: neither reads the carrier, and both discard it. The
  postcondition ADR-0031 §2(b) states before a SUCCEEDED result is constructed
  holds before any result is constructed, because reading the carrier is itself
  tool-supplied code that can raise the cancellation delta after the handler's
  first check. The
  carrier is revalidated before it is read, in ADR-0018 §4's model_dump() then
  model_validate() idiom, because isinstance is not evidence a pydantic model
  was validated — model_construct bypasses every validator — and a carrier that
  is absent, is not a ToolFailure, or does not survive the round-trip has its
  payload refused for the seam's own INTERNAL. The two attributes are validated
  independently, so a bool that validates is honoured under the outcome rule
  even when the payload was refused — the same preservation §3 makes when it
  refuses a reserved kind — while a fact that is absent or not a bool refuses
  the whole carrier for INTERNAL and FAILED, since a carrier missing a required
  keyword-only argument never went through its constructor and its kind would
  otherwise authorise a retry. Each defect resolves toward retrying less and
  knowing less. Reading
  and revalidating the carrier is itself guarded, since isinstance admits a
  subclass and both the attribute access and model_dump() are then tool-supplied
  code: any Exception they raise is INTERNAL, BaseException still propagates,
  and the seam's total failure path contains no unguarded call into a tool.
  ToolImplementation's signature does not move and its
  shape stays tools/-internal. The new core surface is nine names, not eight.`

- **The note ends by enumerating the sentences it supersedes**, in the same
  block, because a reader consulting ADR-0029 alone must not be able to act on
  one of them:

  `Superseded sentences in ADR-0029, which stand in the document unedited: §3's
  "An exception escaping the tool implementation becomes INTERNAL", which now
  excepts a ClassifiedToolError carrying a ToolFailure; §4's "A tool that can
  establish it did not act may return FAILED with TIMED_OUT", whose FAILED is
  now reached by reporting effect_may_have_committed=False and whose TIMED_OUT
  is refused to INTERNAL, that member being reserved to the seam — the clause
  that follows it, "nothing can make it prove the converse", is unchanged and is
  why the fact is required rather than defaulted; and the Consequences'
  count of the new core surface, "seven" as ratified and "eight" as corrected by
  ADR-0031's note above, now nine. §3's "What is raised instead: ToolBindingError
  … It is the only error this ADR adds" is not superseded and stays exactly true:
  ADR-0032 adds an error, ADR-0029 does not, and no ClassifiedToolError ever
  escapes invoke. §3's "A message the seam generates carries no content it did
  not author" is not superseded either — it binds the seam's own messages, which
  are unchanged.`

- **Nothing in ADR-0029 is edited at all.** The `Status` line and the dated note
  are the whole operation, which is the form ADR-0018 set for ADR-0016,
  ADR-0026 §6 restated, and ADR-0030 §6 and ADR-0031 §7 followed. The cost is
  ADR-0018's, accepted here for the third time in this lane: a reader must
  consult all three.

#### ADR-0031

- **ADR-0031's `Status` line is not touched**, for the test applied above.

- **A dated note is appended to ADR-0031's header, after `Date`:**

  `Note (<ratification date>): §1's ToolDefinition.interrupted_outcome gains a
  third reader from ADR-0032 §2 — the seam, ruling the outcome of a failure a
  tool classified and raised. The property's text, its home, its form and its
  single-copy purpose are unchanged, and the new reader is what §1 exists for:
  the tool reports whether its effect may have committed and the seam conjoins
  that fact with this property, so no further copy of the two-field comparison
  is created. Its docstring's "cut short by a deadline or a cancellation"
  describes two of the three circumstances that now read it. §3's re-scoping of
  CANCELLED stands and ADR-0032 §3 depends on it: an integration may raise
  CANCELLED, and the seam still never synthesises it. §3's sentence that an
  integration reporting CANCELLED "chooses its outcome by the same test §4
  applies to the seam" is honoured by the mechanism rather than by the
  integration: it reports effect_may_have_committed and the seam rules from it,
  so "FAILED only if it can establish the effect did not happen, INDETERMINATE
  otherwise" is what ADR-0032 §2 computes. §3's quotation of ADR-0029 §4's "may
  return FAILED with TIMED_OUT" is a citation of a sentence ADR-0032 §3
  supersedes in its kind and preserves in its substance; ADR-0031 ratifies
  nothing about it. §2's provenance rule and
  §2(d)'s precedence stand and outrank the new transport, which is ranked below
  both. §2(b)'s postcondition is unchanged and acquires a second subject: it
  names SUCCEEDED because a normal return was the only path that built a result
  from what the callable produced, and ADR-0032 §4 states it for any result,
  since reading the carrier is tool-supplied code that can raise the delta after
  the handler's first check. §4's declared limits and §5's rules are untouched,
  and §5(b)'s
  enumerated no-interpolation rule is joined by a second enumeration in
  ADR-0032 §5 rather than widened. The Consequences' "five of the eight failure
  kinds still have no carrier (#192)" and "ADR-0029 §5's retry algebra stays
  inert" record the state at ratification, and ADR-0032 is the integration
  decision §3 named as their owner; the eighth-name count in §7's note and in
  the Consequences becomes nine.`

- **Nothing else in ADR-0031 is edited.**

#### ADR-0014

- **ADR-0014's `Status` line is not touched**, for ADR-0029 §9's reason:
  ADR-0001 reserves a status update to an ADR that *changes* a past decision,
  and ADR-0014's decision — that a step which may or may not have acted becomes
  a durable `INDETERMINATE`, never auto-retried, resolved explicitly — is
  applied to a third circumstance meeting its own stated test, not narrowed.

- **A dated note is appended to ADR-0014's header, after the existing ADR-0029
  note:**

  `Note (<ratification date>): §4's RUNNING → INDETERMINATE transition has a
  third trigger from ADR-0032 §2 — a tool that classifies its own failure and
  reports that its effect may have committed, on a tool whose registry
  declaration is side_effecting and not NATURAL. Unlike the second trigger this
  one involves neither a deadline nor a cancellation: the seam's deadline never
  fired and the failure came back as a value. §4's rule is unchanged and is what
  selects it — such a call cannot be distinguished from one that did not act.
  The transition graph, the retry ceiling, and INDETERMINATE's
  never-auto-retried, resolved-explicitly treatment all stand as ratified.`

#### No other ADR is edited

ADR-0016 gets nothing, not even a note: no field is added to `ToolDefinition`,
`model_dump()`, construction and field-wise `==` are unchanged, and §4's
`Idempotency` vocabulary is read exactly as ratified. ADR-0021 gets nothing:
`authorises`, the by-value declaration and the trail are untouched. ADR-0017
gets nothing: its §3 conditions are inherited undischarged, which ADR-0029 §9
already established is not a noteworthy operation. ADR-0018 gets nothing: §5's
registration rules and §4's detachment requirement are unchanged. By ADR-0029
§9's test — "whether a sentence in the other ADR would now read as false" — no
sentence in any of them does.

### 9. What the implementation PR owes

`ClassifiedToolError` is a `core` addition rather than a new Protocol, so
`CONTRIBUTING.md`'s triad requirement is not re-triggered — there is no new
contract to fake. What is owed is the type, the translation in both conforming
implementations, and the suite cases below. `InMemoryToolRegistry` and
`FakeToolInvoker` must both satisfy every one of them, since the shared suite is
what keeps the fake honest without importing `tools/`.

- **`ToolImplementation`'s docstring is retargeted.** Its recorded deferral —
  "it should be given the vocabulary of `ToolFailureKind` by a future
  integration ADR, which this one does not decide" — becomes a description of
  how, naming `ClassifiedToolError`. `FakeToolImplementation`'s parallel
  docstring gets the same. A callable's docstring is where an integration author
  learns the channel exists, so leaving it describing a deferral is how tools
  keep raising unclassified exceptions.

- **A tool that classifies its own failure**, for each of the six
  integration-facing kinds: the result is `FAILED`, carries that kind, and
  carries the tool's message **verbatim**.

- **The retry algebra's first non-`INTERNAL` exercise**, which is what #192 asks
  for. A `RATE_LIMITED` failure from a `KEYED` side-effecting tool inside its
  window satisfies both of ADR-0029 §5's conjuncts and is retried; the same
  failure from an `Idempotency.NONE` side-effecting tool satisfies conjunct 1
  and fails conjunct 2 and is not. Asserting only the first would certify an
  implementation that reads `retryable` as permission, which is the misreading
  ADR-0029 §3 says the clause exists to prevent.

- **The outcome ruling, as a table over both inputs** — `effect_may_have_committed`
  against `definition.interrupted_outcome` — asserted rather than sampled, in
  the shape ADR-0031 §8 requires of `interrupted_outcome`'s own table. The four
  corners at minimum: fact true on a side-effecting non-`NATURAL` tool →
  `INDETERMINATE`; fact true on a read-only tool → `FAILED`; fact true on a
  `NATURAL` side-effecting tool → `FAILED`; fact false on a side-effecting
  non-`NATURAL` tool → `FAILED`. The two middle cases are the ones that pin the
  conjunction: an implementation reading the fact alone passes the other two.

- **`TIMED_OUT` refused**, with all three of its halves, because an
  implementation can get one right and the others wrong. A tool raising a
  `TIMED_OUT` failure well inside its budget comes back `INTERNAL`; its
  message appears in neither the result nor anything logged; and when it raised
  with `effect_may_have_committed=True` on a side-effecting non-`NATURAL` tool
  the outcome is still `INDETERMINATE`. That last is pinned by nothing else and
  is the clause most likely to be dropped as a simplification.

- **`CANCELLED` accepted**, raised by a tool and returned unchanged — the mirror
  of the case above, and together they are what pin the reservation to one
  member rather than to a category.

- **Every `ToolFailureKind` member raised by a tool**, asserted exhaustively as
  accepted-or-refused rather than sampled, so a member added later cannot become
  silently reachable. The shape ADR-0029 §10 already requires of `retryable`.

- **Precedence, with the carrier against each senior signal.** A callable that
  raises a `ClassifiedToolError` *after* this seam's deadline expired comes back
  `TIMED_OUT` with `interrupted_outcome`'s outcome, not the tool's kind. One
  that raises it with a cancellation delta pending makes `invoke` raise
  `CancelledError` and return no result at all. Each senior signal is otherwise
  tested alone, so an implementation that checks the carrier first passes
  everything else.

- **The seam interpolates nothing.** A fake raising
  `ClassifiedToolError(...) from RuntimeError("recipient alice@example.com rejected")`
  — the cause's text must appear in neither `failure.message` nor anything the
  seam logs, alongside the existing case ADR-0029 §10 requires for the
  `INTERNAL` path. This is the regression test for §5's enumeration, in the
  shape ADR-0031 §8 gave §5(b)'s parameters half.

- **And the seam's log line for a translated failure, asserted positively and
  negatively**: it carries the tool's id and `failure.kind`, and it does **not**
  carry `failure.message`, even though that message is Tier 2 and the tool's own.
  Only the negative half is a rule an implementation can violate silently — the
  natural log line includes the message, because it is the useful part — so a
  suite asserting only that the *cause* text is absent passes it.

- **A blank message never reaches a result, by both routes.** A tool raising
  with a message that renders as nothing fails `ToolFailure`'s own validator in
  its own frame and comes back `INTERNAL`; and a tool that evades that validator
  with `ToolFailure.model_construct(kind=..., message=" ")` comes back
  `INTERNAL` too, from §6's revalidation. The second is the case that fails
  against an `isinstance` check, which is what makes it worth writing: the first
  passes against an implementation that trusts the raise site.

- **And what the round-trip repairs rather than refuses**, asserted so that a
  later implementation cannot tighten it into a refusal without an ADR: a
  `model_construct`ed failure whose `kind` is the string `"rate_limited"` comes
  back as a `RATE_LIMITED` result whose `kind` is the enum member, and one whose
  `message` carries surrounding whitespace comes back stripped — the same
  normalisation `ToolFailure(...)` performs at the raise site, which is why
  §5's pass-through is a pass-through for every normally-constructed failure.

- **A malformed carrier** (§6), across every shape the attribute can take:
  `failure` set to `None`, to a string, to a `ToolFailure`-shaped object of
  another class, and **deleted outright**; `effect_may_have_committed` set to a
  non-`bool` and deleted outright; and a `model_construct`ed `ToolFailure` whose
  `kind` is a string naming no member, or which is missing a field. Each comes
  back `INTERNAL`, and specifically not as an `AttributeError` or a `ValidationError`
  escaping `invoke`. The deletion cases are the ones a natural implementation
  fails — reading `exc.failure` directly raises where the rule requires a result
  — and a suite testing only `None` certifies it.

- **The fact outliving a refused payload** (§6): each of those malformed
  carriers raised with `effect_may_have_committed=True` from a side-effecting
  non-`NATURAL` tool comes back `INDETERMINATE` with kind `INTERNAL`, and with
  `False` comes back `FAILED`. Paired with a carrier whose `failure` is an
  exploding property but whose `bool` is sound, which must still reach
  `INDETERMINATE` — that is what pins the two attributes being read
  independently rather than in one `try`. An implementation that refuses the
  whole carrier on any defect passes every other case in this list.

- **A carrier that fights back** (§6's guard), which is the case every other
  malformed-carrier test passes without: a `ToolFailure` **subclass** whose
  `model_dump()` raises, and a carrier whose `failure` is a property that
  raises. `isinstance` admits both, so the revalidation itself is the thing that
  raises — from inside an `except` body, where no sibling clause catches it.
  Both must come back `INTERNAL`. Paired with a subclass whose `model_dump()`
  raises a `BaseException`, which must propagate, so the guard is not written as
  a bare `except BaseException`.

- **A carrier that cancels while being read** (§4's re-read): a `ToolFailure`
  subclass whose `model_dump()` calls `cancel()` on the invoking task and then
  returns valid data. `invoke` must raise `CancelledError`, not return the
  classified result. Nothing else pins it — every other carrier case leaves the
  delta alone, so an implementation that checks interruption once on entry to
  the handler passes all of them. **And the same carrier on the guard's fallback
  path**: `model_dump()` cancels the task and *then* raises an ordinary
  exception, so the `INTERNAL` §6 synthesises is itself a result the re-read
  must precede. An implementation that re-reads only after a successful
  translation passes both cases above and still returns a result from a
  cancelled task — which is the whole failure §4's "before *any* result" exists
  to name.

- **The plain case still holds.** A tool raising an ordinary `RuntimeError` is
  still `INTERNAL` and a `BaseException` still propagates — ADR-0029 §10's
  existing cases, which an implementation adding a new `except` clause in the
  wrong order can break.

## Consequences

- **The retry algebra becomes live.** An upstream 429 arrives as `RATE_LIMITED`,
  which is retryable, and ADR-0029 §5's two-conjunct rule has something to
  decide for the first time. That is the point of the ADR, and #192 closes with
  it.
- **The executor lane is unblocked** (#187). ADR-0031 removed the reason it
  would have duplicated the interrupted-call rule; this removes the reason its
  retry branch would have had one reachable arm.
- **`core` carries a ninth name for this contract**, and the enumeration is what
  made the addition arrive through an ADR rather than through a commit. That is
  the second time ADR-0029's enumeration has worked as designed, and the second
  time the count has moved — a number in a Consequences list is now a small
  amendment obligation on every future contributor to this seam, which is a real
  cost of having written it.
- **Failure classification is split between two parties, and the split is
  stated rather than emergent.** The tool owns `kind` and one fact; the seam
  owns `outcome`, the deadline and the cancellation. A reader of a `ToolResult`
  can therefore say what a tool could have lied about and in which direction:
  `kind` and `message` freely, and `outcome` **only toward `INDETERMINATE`**,
  since `effect_may_have_committed` is untrusted input to a ruling rather than
  the ruling. So `FAILED` is a floor no tool can push below, `SUCCEEDED` is
  unreachable from a raise, and an `INDETERMINATE` from this path is a tool's
  claim the seam permitted — not evidence the seam established, which is what
  ADR-0029 §4's deadline expiry gives. That is a weaker guarantee than "never
  the outcome" and a stronger one than either rejected option in #192 offers,
  both of which let the tool name the field outright.
- **A tool-authored string now reaches every `ToolResult`, and through the
  executor a log and a durable `StepExecution.error` when the outcome is
  `FAILED`.** The seam does not log it — its own line carries the tool id and
  the kind — but declining to log it one frame from where it will be logged is
  not a mitigation. ADR-0029 §3's Tier 2
  obligation on integration authors becomes load-bearing, and no type enforces
  it. This is a real widening of the Tier 1 exposure surface, mitigated only by
  the fact that no integration exists yet and that the first one arrives with
  the egress ADR ADR-0017 §2 requires. §5 says so rather than implying a net
  that is not there.
- **And an `INDETERMINATE` keeps no durable diagnostic**, because ADR-0014 §3
  allows `StepExecution.error` only on a `FAILED` step. The case where an
  operator most needs to know what the tool said is the case where only the log
  retains it. Pre-existing — a deadline expiry has the same shape — but this ADR
  makes it reachable far more often, and it is the planning lane's to close (**#208**)
  (§5), alongside ADR-0029 §8's follow-up on the kind not surviving a restart.
- **A third route to `INDETERMINATE`**, and the least visible of the three. A
  crash is loud and a deadline expiry is the seam's own event; a transport-layer
  timeout inside an integration is a judgement one author makes in one `except`
  clause. Getting `effect_may_have_committed` wrong there is not detectable by
  anything downstream — the fail-closed direction is `True`, and an author who
  writes `False` out of optimism produces exactly the silent loss ADR-0014 §4
  exists to prevent. Requiring the argument is the only lever available; code
  review of the first integration is the other.
- **`ToolFailureKind` becomes an integration author's vocabulary rather than a
  seam-internal enum**, which raises the cost of ever changing a member's
  meaning: from ratification, a kind is a word third-party-ish code says, not
  just one `core` synthesises. ADR-0031 §3's re-scoping of `CANCELLED` was cheap
  precisely because nothing produced it; the next such re-scoping will not be.
- **The seam's `except` ladder grows a clause, in an order that is now
  normative.** ADR-0031 §2's defects were all ordering and provenance mistakes
  in this exact function, found by writing the code rather than by review. §4
  and §9 state the ordering and pin it, on the assumption that the next
  implementation will make the same class of mistake.
- **`ToolImplementation`'s docstring stops describing a deferral**, which is a
  small thing that matters: it is the one place an integration author reads what
  a failure channel is, and it currently says there is not one.
- **Revisit when** the first real integration lands — does the Tier 2 obligation
  on a tool-authored message need a mechanical half, and does
  `effect_may_have_committed` want a third value for "definitely did not act"
  distinct from the default? — or when `StepExecution` gains a structured
  failure kind (ADR-0029 §8's follow-up), at which point the kind an integration
  reported survives a restart and the retry rule can be made durable.

### The strongest case against this decision

An exception is a strange carrier for a value that is not exceptional. Every
classified failure here is an *expected* outcome — a 429, a rejected argument,
an upstream that declined — and the contract now says: construct a validated
model, wrap it in an exception, throw it, catch it one frame up, unwrap it, and
build a second model from it. ADR-0029 §3 argued at length that failure crosses
this seam as *data* because "`INDETERMINATE` cannot be an exception" and an
executor learning about failure by catching something is "one `except
Exception:` away from recording a completed action as failed" — and this ADR
answers that argument by using an exception, on the inside, for the same class
of information. #192's second option, `FrozenJson | ToolFailure`, is the shape
that matches ADR-0029 §3's own reasoning: a return value for a returned fact.

The answer is that the seam is where the two arguments part, and it is worth
being exact about why rather than resting on "additive". ADR-0029 §3's rule is
about what crosses the *contract* — `invoke`'s caller must never learn of a
failure by catching, and it does not: `ClassifiedToolError` never escapes
`invoke`. Inside, the tool already has a raising channel, ADR-0029 §3 already
requires the seam to interpret it, and adding vocabulary to a channel that
exists is a smaller change than adding a second channel beside it — a union
return type would mean two ways for a tool to report the same failure, and a
contract with two spellings of one thing is the shape ADR-0031 §1 was written to
remove. The union also changes `ToolImplementation`'s return type, which breaks
every implementation for a benefit that is stylistic at the point where it
matters.

What that defence does not cover is the ergonomics. `raise
ClassifiedToolError(ToolFailure(kind=..., message=...),
effect_may_have_committed=False)` is a mouthful on a path an integration author
writes a dozen times, and a mouthful is a thing people work around — a helper
in `tools/` with a `False` default would undo §2's whole argument in four lines
and would look like a kindness. The honest position is that this ADR is buying a
safety property with an ergonomic cost it cannot enforce anyone to pay, and that
the first integration PR is where that pressure will actually arrive.
