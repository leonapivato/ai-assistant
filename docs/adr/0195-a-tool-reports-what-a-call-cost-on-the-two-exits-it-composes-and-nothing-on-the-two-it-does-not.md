# 195. A tool reports what a call cost on the two exits it composes, and nothing on the two it does not

- Status: Proposed
- Date: 2026-08-26
- **Decides `core/types.py` and `core/errors.py` surface and implements none of it
  (golden rule 5).** It adds **one** `core/types.py` model, `ReportedOutput`, and
  **one** keyword-only, defaulted field on the `core/errors.py` class ADR-0032
  specified but never built, `ClassifiedToolError.incurred_cost` — which this ADR
  neither builds nor commissions a lane to build (§3, §11). It adds **no** Protocol to
  `core/protocols.py`, so **no triad is owed** (`CONTRIBUTING.md` → "Adding a
  Protocol"), and it moves no member of `ToolInvoker`, `InvocationLedger` or
  `AuditTrail`. The two `tools/`-internal callable Protocols widen their return
  annotation to admit the new model; that half is ADR-0029 §1's to give away and
  §9 records that it is given rather than taken.
- **Required review set: adversarial *and* architecture.** Compelled rather than
  declared: `CONTRIBUTING.md` → "Stop when the required reviews are green" makes a
  change contract-surface when it is the ADR deciding that surface, and the bullet
  above says which surface (ADR-0015 §1).
- **Amends ADR-0032 §1 and §6** — the enumeration of `ClassifiedToolError`'s fields
  and the revalidation rule over them, which gain a third attribute read
  independently of the other two — and **ADR-0192 §5**, whose "no integration can
  populate this field yet, and this ADR mints no channel by which one could" is the
  deferral this ADR discharges. §10 applies ADR-0070 §1 and ADR-0082 §1 to each,
  and states why neither is a supersession.
- **Depends on ADR-0192 and ADR-0194 by number, and reshapes no field of either.**
  ADR-0192 §5 fixed the destination — `ToolResult.incurred_cost`, the completion
  row it maps onto, and the `UNKNOWN` that stands until something reaches it — and
  this ADR supplies the carrier that reaches it. ADR-0194's arithmetic, its two
  refusal classes, its allowance and its ordering are all read and none is touched.
- **Closes #1558 on ratification.** That issue asked for the decision, and §11
  carries with it the end-to-end case ADR-0192 §9 deferred to whichever ADR minted
  the channel.

## Context

`ToolResult.incurred_cost` exists and nothing can fill it.

ADR-0192 §5 landed the field so that a budget ceiling would have a stable place to
read, and said in terms that no registered integration can populate it:
`ToolImplementation` returns `FrozenJson` and nothing else, ADR-0029 §1 leaves the
callable's shape to `tools/` and "does not contract it", and no ADR owned minting a
carrier. So `tools/consume.py` maps `None` to a `ToolCost` whose basis is
`UNKNOWN`, every completion row records that, and ADR-0194's accounted total is
made of figures nobody reported.

**That interim state is fail-closed and it is not free.** ADR-0194 §2 makes an
`UNKNOWN` reported cost render its period **indeterminate** where no allowance is
configured, and §4's fifth ground refuses the next call on it. The milestone-25 QA
run (#1601, findings S1–S3 and S8) drove exactly this and measured what it means:
with no `world_spend_unknown_allowance`, one completed call makes its period
unmeasurable until the period rolls over and the ceiling never bites; with an
allowance set, `UNKNOWN` acquires a number on both the declared and the reported
side, the period is determinate, and the ceiling is an ordinary working bound —
equality admitted at 4.50, excess refused at 5.00, observed end to end at a user
surface.

**So the allowance already makes the ceiling work, and this ADR is not what rescues
it.** What the allowance is, ADR-0194 §2 says plainly: the user stating a per-call
worst case for a price the tool's author could not state. It is a real bound and it
is the user's own number. What it is not is a *measurement*. Every call in a period
is accounted at the same configured figure whatever it actually cost, the ceiling
holds against the user's stated worst case rather than against what happened, and a
tool that *does* know its price has no way to say so. This ADR closes that last
gap and nothing else: it lets the one party who can know a call's price put that
number on the record, and it leaves every clause of ADR-0194 exactly where it
stands for the calls where nobody knows.

**#192 is closed and does not cover this, which is ADR-0192 §5's own statement.**
#192 asked for a *failure* transport; ADR-0032 answered it with
`ClassifiedToolError`, an exception carrying a `ToolFailure`, and its "What is *not*
contracted here" keeps `ToolImplementation`'s `FrozenJson` return type on purpose —
rejecting both a widened return type and a returned `ToolResult`. An exception is by
construction unavailable to a call that **succeeded**, which is the case a cost
matters for most.

**Those two refusals are the constraint this decision is built against, and they are
not equally binding here.** The second is absolute and this ADR obeys it whole:
returning a `ToolResult` hands the callable `outcome`, and ADR-0031 §2 spent a
section making that field tamper-resistant precisely because "a callable's own
account of what happened to it is not evidence". Nothing below lets a tool state an
outcome, a failure kind, or anything the seam rules. The first is narrower than it
reads, and the Alternatives section takes it apart clause by clause: ADR-0032
refused a union return **as a second spelling of a channel that already existed**,
and there is no cost channel to be the first spelling of.

**A cost is the same class of fact as the two things ADR-0032 already lets a tool
report.** ADR-0032's design sentence is "Kind is what the tool knows. Outcome is
what the seam rules", and §2 adds `effect_may_have_committed` on the ground that the
tool "is the **only** party that knows". A price is that shape exactly. The seam
cannot compute it: it sees a coroutine return, not a tariff. The declaration cannot
supply it: ADR-0016 §4 makes `cost` a *declared* estimate and ADR-0192 §5 forbids
copying it onto a row labelled incurred, because that "would discharge the deferral
in appearance and reproduce the estimate underneath". The transport cannot supply
it either, and ADR-0191 §4 says why in its own division of labour — a capability
"is not the party that knows, so it is not the party that decides". What is left is
the integration, and it has no channel.

**One of those two exits is ratified and does not exist yet, and this ADR is
written knowing it.** `ClassifiedToolError` appears nowhere under `src/` or
`tests/` — ADR-0032 is `Accepted` and its §9, "What the implementation PR owes",
never ran. The tree already records the fact and its consequence:
`tests/tools/test_consume.py` says so in terms ("That ADR is Accepted and
**unimplemented**: the symbol appears nowhere under `src/`, which is what issue
#596 records"), and #1583 records a ratified ADR-0192 §9 test arm that has no
producer because of it. So the classified-failure exit is a **contract** exit and
not yet a reachable one, §3 decides the cost field on it without implementing it,
and §11 puts that half of the work where it belongs — with the carrier's own lane,
not this one. The gap itself is filed as **#1614** rather than absorbed (§11).

**One shape question is already answered in the tree and it is the strongest
evidence available.** `ToolImplementation` is no longer the only callable shape:
`EgressToolImplementation` sits beside it with an `invoke_bound` method, resolved
once at registration by `resolved_implementation`, and it was minted **without an
ADR** on ADR-0029 §1's deferral — no document in `docs/` mentions either name. So
the callable's shape genuinely is `tools/`-internal in practice as well as in
principle, and the part of this decision that needs an ADR at all is the part that
puts a name in `core`: a carrier `ai_assistant.testing`'s fake invoker must reach
without importing `ai_assistant.tools`, which is ADR-0032's own decisive argument
for `ClassifiedToolError`'s home, one type over.

## Decision

We will let a tool report what a call cost **on the two exits it composes itself** —
the value it returns and the failure it classifies — and report nothing on the two
it does not compose, where the row records `UNKNOWN` because that is the truth.

> **The tool reports a price. The seam still rules the outcome, and records the
> price without reading it.**

### 1. Four exits, two of them the tool's to speak on

> **Normative.** An invocation leaves the callable by exactly four routes **the
> contract admits**, and this ADR decides all four rather than deferring any: a
> **value returned**; a **`ClassifiedToolError` raised** (ADR-0032 §1); **any other
> exception escaping**, which the seam turns into `INTERNAL` (ADR-0029 §3); and
> **this seam's deadline expiring or a cancellation being delivered**, which
> ADR-0029 §4 and ADR-0031 classify.

> **Normative.** Three of the four are reachable in the tree today. The second is
> ratified and unbuilt: `ClassifiedToolError` exists in no module, so no callable
> can raise one and the seam catches none. This ADR decides that exit's cost field
> anyway, because deciding one exit's carrier while leaving its sibling's to a later
> reader is how two spellings of one fact get minted — and it implements neither
> (§3, §11).

> **Normative.** On the first two the tool **may** report a figure, by the carriers
> §2 and §3 define. On the second two it reports nothing and no carrier is minted
> for it: the completion row records a `ToolCost` whose basis is `UNKNOWN`, exactly
> as `tools/consume.py` records today for an interrupted call.

> **Normative.** That is a decision and not a gap. On the third route the tool did
> not compose an exit — it crashed, and a figure recovered from an object it did not
> intend to hand over is not a report. On the fourth the seam stopped waiting while
> the callable was still running (ADR-0029 §4: "what it buys is that the seam stops
> waiting, not that the tool stops working"), so there is nothing the tool has
> finished saying. In both, `UNKNOWN` states the true fact — this system does not
> know what the call cost — and ADR-0194 §2 then makes the period indeterminate or
> charges the allowance, which is the conservative direction and the one already
> ruled.

> **Normative.** No mechanism is added by which a tool reports a cost **outside** an
> exit it composes. No sink, context object, out-parameter, module-level reporter,
> `ContextVar` or post-return callback is minted here, and no lane may add one
> without its own ratified decision. A channel a tool can write to *after* the seam
> has read it is a channel by which a row is written from outside the act it
> records, and every one of the shapes above is that channel.

### 2. `ReportedOutput`, in `core/types.py` — the exit a successful call composes

> **Normative.** `core/types.py` gains one model:

```python
class ReportedOutput(BaseModel):
    """A successful call's output together with what that call cost (ADR-0195 §2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    output: FrozenJsonValue = None
    incurred_cost: ToolCost
```

> **Normative.** `incurred_cost` is **required**. A tool with nothing to report
> returns its output bare, which is what every tool does today, and an envelope
> whose cost was optional would be a second spelling of that — the shape ADR-0031 §1
> exists to remove.

> **Normative.** `output` carries `FrozenJsonValue`, the same annotation
> `ToolResult.output` carries, so the envelope adds **no** route by which content
> reaches a result that a bare return does not already reach. A value
> `FrozenJsonValue` refuses inside an envelope raises at the envelope's own
> construction, in the tool's frame, and escapes as an ordinary exception —
> `INTERNAL`, which is where the same value lands today when the seam validates a
> bare return (ADR-0029 §3). Nothing about how a bad output is classified moves.

> **Normative.** A `ReportedOutput` cannot nest: `FrozenJsonValue` admits no
> `BaseModel`, so `output` can never hold another envelope and no unwrapping loop is
> owed.

> **Normative.** The two `tools/`-internal callable Protocols widen their return
> annotation to `FrozenJson | ReportedOutput` — `ToolImplementation.__call__` and
> `EgressToolImplementation.invoke_bound`, identically, and
> `ai_assistant.testing`'s `FakeToolImplementation` with them. **No third callable
> shape is minted.** The cost channel is orthogonal to the egress split and is
> added in the return position, which both shapes already share; adding it as a
> shape instead would make the registry's resolution a two-by-two matrix, and a
> contract with four spellings of one seam is the direction ADR-0031 §1 and
> ADR-0029 §1's "the surface should not widen to cover a concern its consumers do
> not have" both refuse.

> **Normative.** A **widening** return type conforms every existing implementation
> rather than breaking one: a callable returning `FrozenJson` satisfies the wider
> annotation, since a return type is covariant. Every registered tool in the tree
> continues to type-check and to run unchanged, and no integration author is
> obliged to learn this channel exists.

> **Normative.** The seam discriminates the two arms with `isinstance` against
> `ReportedOutput` and by no other test. `FrozenJson` is `str | int | float | bool |
> None | Sequence | Mapping`, and a pydantic model is none of them, so the
> discrimination is total and no value is ambiguous. No implementation sniffs for a
> `dict` with an `incurred_cost` key, or for any other structural signal: a tool
> returning JSON that happens to carry that key returns JSON.

> **Normative.** `isinstance` admits a **subclass**, so **both** of the envelope's
> fields are tool-authored reads and neither is read bare. The seam reads `output`
> and `incurred_cost` **once each, under the guard §4 puts on a cost read**, into
> local values, and reads neither off the envelope again. A subclass overriding
> `__getattribute__`, or a field shadowed by a property, is therefore a defect the
> seam absorbs rather than an exception escaping after ADR-0192 §1's claim has been
> appended — which would leave a claim with no completion, exactly as §4 says of the
> cost read and for the same reason.

> **Normative.** The two reads' defects resolve **differently**, on §4's own subject
> test rather than on their shared mechanism. A read of `incurred_cost` that raises
> yields `UNKNOWN` and costs nothing else. A read of `output` that raises leaves the
> seam with nothing to record as the call's result, so it takes the `INTERNAL` path
> an unrepresentable output already takes (ADR-0029 §3) — **and the reported cost is
> discarded with it**, because the two came off one object and a seam that kept half
> of a misbehaving carrier would be arbitrating between two accounts a tool gave of
> its own call, which ADR-0032 §6 declines to do.

> **Normative.** Both reads precede §4's interruption re-read. That is what the
> order there is for: an accessor that delivers a cancellation or lets the deadline
> expire is seen by the check that follows **every** read of tool-authored state, and
> the result is then discarded with its figure.

> **Normative.** The envelope is **unwrapped at the seam and travels no further**.
> `ToolResult.output` receives the **local** captured by the single guarded read
> above, never a second access to the envelope; `ToolResult.incurred_cost` receives
> the validated cost derived from the other local (§4). Every later rule in this ADR
> naming the envelope's `output` or its cost names those two locals: a subclass whose
> first access succeeds and whose second raises or answers differently must not find
> two instructions to choose between, and one read per field is what leaves it none. No `ReportedOutput` reaches a `ToolResult`, a
> `StepExecution`, an audit row, the wire or any consumer of `ToolInvoker`, so
> ADR-0087's encoding is untouched and no `PROTOCOL_VERSION` bump is owed on this
> ground (§9).

### 3. `ClassifiedToolError.incurred_cost` — the exit a classified failure composes

> **Normative.** `ClassifiedToolError` **as ADR-0032 §1 specifies it** gains one
> keyword-only field, `incurred_cost: ToolCost | None = None`, and changes in no
> other way: its base class, its placement outside `ToolError`, its `failure`, its
> `effect_may_have_committed` and its rule that it never escapes `invoke` all stand
> as that section ratified them.

> **Normative.** **This ADR does not implement ADR-0032 and does not oblige any
> lane to.** The carrier is ratified and absent from the tree, so this section binds
> a specification rather than a class: the field lands **with** the carrier,
> whenever ADR-0032 §9's lane runs, and until then nothing in `tools/` catches
> anything for it to be read from. A cost lane that landed the carrier in order to
> have somewhere to put the field would be implementing a second ratified ADR
> inside this one's PR, which is the scope failure `CLAUDE.md`'s one-subsystem rule
> and ADR-0015 §5's sequencing both exist to prevent.

> **Normative.** Deciding it here rather than leaving it to that lane is the
> narrower risk of the two. A cost field invented later, beside a carrier already
> built, would be decided in an implementation PR — the exact placement ADR-0032
> itself refused for the failure transport — and it would be decided without the
> §4 rules that make the two carriers behave identically.

> **Normative.** It is **defaulted** where `effect_may_have_committed` is
> deliberately not, and the asymmetry is argued rather than inherited. ADR-0032 §2
> leaves that fact undefaulted because a default would let a forgetful author
> silently assert the *safe-looking* half of a safety claim — "nothing committed" —
> which is the claim ADR-0014 §4 refuses to have made by omission. A defaulted
> `None` here asserts "no figure", which is identical to what silence already means
> everywhere else in this ADR and is the fail-closed direction under ADR-0194 §2.
> Requiring it would break every existing raise site to make authors type the answer
> that silence already gives.

> **Normative.** A failed call may genuinely have cost money — an upstream that
> billed a request it then rejected, a message accepted and not delivered — and
> ADR-0194 §2 already requires such a row to be counted, "including one whose
> outcome is `INDETERMINATE`". Without this field that row could only ever record
> `UNKNOWN`, so a priced integration would poison its own period on every failure.
> This is the clause that stops the channel working only while nothing goes wrong.

> **Normative.** The field states what the call cost and **never** whether the
> effect committed. The two are independent: a tool may report a charge for a call
> whose effect it knows did not land, and `effect_may_have_committed` is unchanged
> and unread by anything here. No implementation infers one from the other.

### 4. What the seam does with a reported figure, and what it refuses to do

> **Normative.** `invoke` **revalidates** a reported cost before reading it, in
> ADR-0032 §6's own idiom and for its own reason — `ToolCost.model_construct`
> bypasses every validator while satisfying `isinstance`, so a `PER_CALL` basis with
> no amount, a `NaN`, a negative amount or a `str` where a `CostBasis` belongs would
> otherwise reach a row and, through it, ADR-0194's arithmetic. The cost the seam
> reads is `ToolCost.model_validate(reported.model_dump())`: a validated, detached
> value, on both carriers.

> **Normative.** **The whole read runs under its own `Exception` guard**, and this
> is not a refinement of the clause above but the half that makes it safe. Every
> step of it executes tool-authored code: the attribute access can be a property, and
> `model_dump()` can be overridden by a `ToolCost` subclass — ADR-0032 §6 rules that
> such an override is legitimate and that "the round-trip's result is what crosses",
> which this ADR inherits whole. So an `Exception` raised by the attribute access,
> the dump or the validation is caught **there** and yields `UNKNOWN`, exactly as a
> value that fails validation does. It is the same guard ADR-0032 §6 already
> requires for the same reason — "a `failure` property that explodes must not take
> the `bool` down with it, so each attribute is fetched under its own guard and
> judged on its own" — with a third attribute under it.

> **Normative.** That guard is load-bearing rather than tidy, because of **where**
> the read sits. It happens after ADR-0192 §1's claim has been appended, so an
> exception escaping it would leave a claim with no completion — the state ADR-0192
> §3 requires a completion attempt on every exit to prevent — and would do so over an
> accounting field, on a call that already ran. No implementation lets a cost read
> escape `invoke`, and none synthesises a failure from one: the outcome, the output
> and the failure are decided by the rules that already decide them.

> **Normative.** A `BaseException` that is not an `Exception` — a `CancelledError`
> delivered from outside above all — is **propagated unchanged** and is never
> absorbed by that guard. ADR-0029 §3, ADR-0032 §4 and ADR-0194 §4 all take that
> exemption and this ADR takes it identically: a cancellation is not an accounting
> fact.

> **Normative.** **The order is fixed: the cost is read and validated first, and the
> seam's interruption state is read after it.** Reading a reported cost runs the
> tool's code, so a deadline can expire and a cancellation can be delivered *inside*
> the read. An implementation that checked interruption before the read would build a
> result carrying a figure obtained after the seam had stopped waiting; one that
> never re-read it would let the discard rule below silently not fire. So the
> sequence at each exit is: read every tool-authored value under the guard — the
> envelope's two fields at the success exit (§2), the carrier's three attributes at
> the classified-failure exit — then evaluate interruption, then build the result — and where interruption answers, the cost is
> discarded with the classification it accompanied.

> **Normative.** A cost that does **not** survive the round-trip **or whose read
> raised** is **discarded, and nothing else is**. The outcome stands, the output stands, the failure and
> `effect_may_have_committed` stand, and the row records a `ToolCost` whose basis is
> `UNKNOWN`.

> **Normative.** That is ADR-0032 §6's structure extended rather than departed from:
> that section reads the carrier's attributes **independently** and lets "each
> defect resolve in its own pessimistic direction". A malformed payload costs the
> *kind*; a malformed fact costs the *carrier*; a malformed cost costs the *cost*.
> The pessimistic direction for a cost is `UNKNOWN`, because ADR-0194 §2 already
> refuses to read `UNKNOWN` as zero — it makes the period indeterminate or charges
> the allowance, and either way the next call is measured conservatively.

> **Normative.** A malformed cost therefore does **not** turn a successful call into
> `INTERNAL`, and the difference from the bare-output case is the subject rather
> than the severity. An output that `FrozenJsonValue` refuses leaves the seam with
> nothing to record as the call's result, so `INTERNAL` is the only honest answer.
> A malformed cost leaves the result entirely intact; discarding a real success —
> an act that already happened, possibly irreversibly — over an accounting field
> would destroy the record ADR-0192 exists to write, to reach a fail-closed state
> that is already reachable through the row.

> **Normative.** Nothing derived from the `ValidationError` a refusal produces
> enters a message or a log, under ADR-0032 §5's enumeration: it is raised *about*
> the reported value and would render it.

> **Normative.** Where ADR-0032 §4's precedence discards the tool's classification —
> a cancellation, or this seam's deadline, pre-empting what the tool said — the
> reported cost is **discarded with it**, and the row records `UNKNOWN`. One
> carrier has one fate: a row citing a figure from a report the seam ruled
> inadmissible would attribute to the tool a statement about a call the seam has
> just said the tool did not get to finish. The same rule governs the returned
> envelope: where the seam converts a normal return into an interrupted result,
> the envelope's figure goes with the outcome it accompanied.

> **Normative.** The seam performs **no arithmetic and no policy** on a reported
> figure. It does not compare the currency against `world_spend_currency`, does not
> convert, does not compare against `ToolDefinition.cost`, does not clamp, does not
> round, and does not refuse a call because of what was reported. ADR-0194 §2 owns
> every one of those readings, on rows, at the next admission; `tools/` records and
> nothing more, which is what keeps budget policy out of the subsystem that performs
> the act.

> **Normative.** Nothing about the budget is passed **to** the callable. No ceiling,
> no accounted total, no allowance, no projected total, no admission handle and no
> currency reaches a tool through this channel or any other. The channel is one-way
> and write-only from the tool's side, which is what keeps ADR-0194 §4's "nothing a
> turn can reach lifts a refusal" true by construction rather than by review.

### 5. Who may report, and from what

> **Normative.** The figure is the **integration's**, and its origin is something
> the integration itself learned about **this** call: a charge the upstream returned
> in its own response, a metered quantity that response carried, or a tariff the
> integration's provider publishes and the integration applies. ADR-0192 §5's rule
> is unchanged and binds here in full — a tool reports a figure only where it
> **knows** one, and never a number it constructed to fill the field.

> **Normative.** A tool that cannot price the call **returns its output bare** or
> raises without the field. `UNKNOWN` in an envelope is permitted and lands
> identically to reporting nothing: the row records `UNKNOWN` either way, and no
> implementation treats the two differently, at the seam, on the row, or in the
> total. It is permitted rather than refused because an integration computing a
> `ToolCost` from a tariff table that sometimes yields `UNKNOWN` would otherwise have
> to branch at its return statement to avoid tripping a validator, and because
> refusing a value that is *true* would convert an honest report into a failed call.

> **Normative.** No **transport** reports a cost. `OutboundTransport`, `ByteChannel`
> and everything else ADR-0191 injects gain no cost surface and are handed no
> figure, on ADR-0191 §4's own division of labour: a capability "is not the party
> that knows, so it is not the party that decides". A transport sees octets and a
> connection; a price is the integration's knowledge about its own provider.

> **Normative.** No figure is derived from `ToolDefinition.cost`, from
> `core.config.Settings`, from `world_spend_unknown_allowance`, or from any other
> value this system holds rather than the call produced. ADR-0192 §5 forbids the
> first in terms; the rest are the same substitution reached by a longer route, and
> a reported figure that came from configuration would be the user's declaration
> wearing a measurement's name.

> **Normative.** A reported figure is an **estimate unless the integration's own
> source says otherwise**, and this ADR mints no way to tell the two apart: no
> fourth `CostBasis` member, no `estimated` flag, and no settled-later state. The
> caveat ADR-0016's Consequences record for the declared side — "a wrong number will
> mislead a spend policy, and no mechanism detects the drift" — now reaches the
> reported side too, and ADR-0194 §2 already states the bound that survives it.
> Splitting the basis would be a new policy question about what a ceiling does with
> an estimate, and that is the budget ADR's to open, not this one's to pre-empt.

> **Normative.** `incurred_cost` is the **price of the invocation** and is never
> money the tool moved (ADR-0016 §4, ADR-0192 §5). A payments integration reporting
> the amount it transferred would be filling this field with the value ADR-0016 §7
> declines to model, and no lane reads it as a transacted amount.

### 6. The mapping, and the three things that are not reconciled

> **Normative.** The mapping is **ADR-0192 §5's, unchanged and restated rather than
> redecided**: `ToolResult.incurred_cost` reaches `ToolInvocation.incurred_cost`
> unaltered where the result carries a figure, and a `None` becomes a `ToolCost`
> whose basis is `UNKNOWN`. This ADR adds no step to that path, no field to either
> type and no branch to `tools/consume.py`'s completion beyond the two carriers §2
> and §3 define feeding `ToolResult.incurred_cost`.

> **Normative.** The **reservation is not adjusted**. ADR-0194 §3's reservation is
> retired by releasing its handle and carries the **declared** amount for its whole
> life; no implementation replaces it with the reported figure, tops it up, or
> refunds a difference. The reported figure enters the **accounted total** and
> nothing else, which is the separation ADR-0194 §2 keeps between the number used
> for admission arithmetic and the number written to a row.

> **Normative.** **No delta is computed and no reconciliation record is minted.**
> Where a reported figure differs from the declaration that admitted the call, the
> difference is not stored, not logged as a discrepancy, not surfaced as its own
> reading and not attributed to anything. What the difference does is exactly what
> ADR-0194 §2 already says: it lands in the accounted total, it is readable there
> (§6), and it bites the **next** admission.

> **Normative.** **Nothing is lifted, retroactively refused or written back.** A
> reported figure never lifts a refusal — ADR-0194 §4's closed direction is
> untouched, and a report is not a thing a turn can reach in that clause's sense
> either, since a tool can only report about a call that was already admitted. A
> call that ran does not become refused because its report exceeded its declaration;
> that is ADR-0194 §2's stated overrun and this ADR neither narrows nor widens it.
> And **no lane writes a reported figure back onto `ToolDefinition.cost`** or onto
> any declaration: a declaration learned from measurements would make the admission
> arithmetic depend on a history nobody ruled, and would erase the distinction
> ADR-0192 §5 exists to keep.

> **Normative.** ADR-0194's **allowance is untouched**. Where a tool reports nothing
> the row still records `UNKNOWN` and `world_spend_unknown_allowance` still governs
> it; where a tool reports a figure the allowance is not consulted for that row. No
> implementation charges both.

### 7. `send_email` reports nothing, and this ADR is ahead of its producer

> **Normative.** `send_email` reports **no** figure under this ADR, and its declared
> `ToolCost(basis=UNKNOWN)` is correct and stays. SMTP carries no price: the tariff,
> where one exists at all, belongs to the provider behind the connected account, the
> protocol returns nothing about it, and `ai_assistant.tools.egress` sees a
> connection and octets. The integration does not know, so under §5 it says nothing.

> **Normative.** The classified-failure exit has neither a producer **nor a
> carrier**: `ClassifiedToolError` is unbuilt (§1, §3), so §3's field has nothing to
> sit on until ADR-0032's lane runs. Both halves of that are stated rather than
> discovered later.

> **Normative.** **No integration in this tree reports a figure at ratification, and
> the ADR says so rather than manufacturing one.** The channel's first real producer
> is whichever integration lands with a provider that returns a per-request charge
> or publishes a tariff the integration can apply; none exists today, and this ADR
> names none.

> **Normative.** The implementing lane therefore proves the channel against a
> **test-only priced integration** and **never** by teaching `send_email` to report.
> A production integration that reported a number nobody measured, in order to make
> an end-to-end case pass, would be the fiction ADR-0016 §4 refused and ADR-0192 §5
> forbids on the declaration side, reached from the other end (§11).

> **Normative.** Deciding the shape ahead of its producer is deliberate, on
> ADR-0032's own precedent: that ADR decided the failure transport ahead of the
> executor lane because "a decision that leaves the transport ambiguous unblocks
> nothing, so the shape is decided here rather than inside an implementation PR
> where it would not get architecture review". A cost carrier invented inside a
> future integration's PR is the same failure, with a `core` type in it.

> **Normative.** Until a producer exists, the behaviour of the running system is
> **unchanged in every observable respect**: every row records `UNKNOWN` exactly as
> it does today, the QA record's measured behaviour (#1601, S1–S3) stands
> unmodified, and `world_spend_unknown_allowance` remains what makes the ceiling a
> working bound. This ADR adds capacity, not a change of behaviour, and no user-
> visible surface moves.

### 8. What this ADR does not decide

> **Normative.** Each of these is out of scope with the trigger that would bring it
> in, and none is silently left open.

- **Pricing policy of any kind.** What a call *ought* to cost, whether a ceiling
  should differ per tool, and any per-tool budget are not decided. Trigger: a user
  need for a bound narrower than ADR-0194 §1's two periods.
- **Currency conversion.** A reported figure in a currency other than
  `world_spend_currency` is ADR-0194 §2's to handle and is never converted here.
  Trigger: ADR-0194 §8's own, unchanged.
- **A `CostBasis` member for an estimate, a pending settlement or a refund.**
  Trigger: a producer whose provider distinguishes them and a ceiling rule that
  reads the distinction.
- **Reconciliation of a declaration against a report** (§6). Trigger: a measured
  drift that a user surface needs to explain rather than merely total.
- **Concurrency atomicity of the invocation seam** — #1553 and ADR-0194 §8's item,
  untouched. This ADR adds no shared mutable state to `invoke` and no ordering
  obligation, which is the second reason §1 refuses a sink.
- **Model-provider spend.** ADR-0194 §2 puts it out of scope and nothing here folds
  a model ledger into this one.
- **The disclosure report.** ADR-0029 §3's other omission and issue #57 are
  untouched; this ADR adds no field to `ToolResult`.
- **Transacted amounts** — money a tool moves. ADR-0016 §7's deferral, unaffected
  (§5's last clause).
- **Implementing ADR-0032.** The failure transport's carrier is ratified and
  unbuilt, and this ADR neither builds it nor commissions a lane that does (§3,
  §11). Trigger: ADR-0032 §9's own, unchanged, tracked on **#1614**.
- **Any recovery-scan cost.** `orchestration/recovery.py` completes an abandoned
  claim with `UNKNOWN` and continues to: there is no tool frame to report from, and
  a claim completed by a scan is §1's fourth route by another name.

### 9. What this changes in other ADRs, clause by clause

**ADR-0192 §5's no-channel clause.** Its sentence — "**No integration can populate
this field yet, and this ADR mints no channel by which one could**" — names #1558 as
the owner and says the ADR "neither pre-empts the shape #1558 lands nor blocks on
it". This is that shape. A reader holding only ADR-0192 would read the no-channel
state as still standing and would be wrong about the tree, which is exactly the
reading ADR-0194 §9 took on ADR-0021 §6 and ADR-0029 §7. A record is owed (§10).
**Everything else of §5 stands and this ADR rests on it**: the field, its `None`
meaning, the naming apart from `ToolDefinition.cost`, the know-it-or-report-`UNKNOWN`
rule, the summing clause, the open-claim clause, the prohibition on copying the
declaration, and the statement that `incurred_cost` is never a transacted amount.

**ADR-0032 §1's field enumeration and §6's revalidation rule.** §1 specifies
`ClassifiedToolError` in full and §6 states the round-trip over its **two**
attributes. After this ADR there are three, and the third is revalidated
independently like the other two. A reader holding only ADR-0032 would build a seam
that ignores a field the contract now carries — ADR-0082 §1's "reads one of its
clauses more widely than it now holds". A record is owed (§10). **Nothing ADR-0032
decided is reversed**: the carrier is still an exception, still an `Exception` and
not a `BaseException`, still outside `ToolError`, still homed in `core/errors.py`,
still never escapes `invoke`; `effect_may_have_committed` is still keyword-only and
undefaulted; §2's outcome rule, §3's `TIMED_OUT` reservation, §4's precedence and
§5's by-value message rule are untouched and this ADR relies on all five.
**That the carrier is unbuilt changes neither the record nor its class.** ADR-0070
§1's test is over what a reader of the earlier ADR would do, and a reader of
ADR-0032 §1 today is a reader about to *write* the class; leaving the enumeration
un-recorded would send them to write it with two fields.

**ADR-0032 §1's "What is *not* contracted here" and §7's first bullet — a stacked
addition, and no record is owed.** Both say `ToolImplementation`'s `FrozenJson`
return type is unchanged and "remain[s] `tools/`-internal (ADR-0029 §1)". They stay
true of ADR-0032, which changed it and does not; and the clause that would be read
too widely — the rejection of a union return — is refused **as a failure transport**
and stays refused as one. This ADR makes no `ToolFailure` returnable and adds no
second spelling of the failure channel. The tree also already answers the general
question: `EgressToolImplementation` moved the callable's shape with no ADR and no
record on ADR-0032, on the same deferral. The Alternatives section engages the
union's *grounds* rather than resting on this paragraph.

**ADR-0029 §1's "How the callable is reached is `tools/`-internal, and this ADR does
not contract it" — a stacked addition, and no record is owed.** The sentence stays
true: ADR-0029 does not contract it, and this ADR does not make it do so. What §2
above widens is a `tools/`-internal annotation, which that deferral hands to
`tools/` and which `tools/` has already exercised once. What this ADR *decides* is
the `core` name the annotation admits, which is not the callable's shape but a type
beside it, exactly as `ClassifiedToolError` is.

**ADR-0029 §3's "the result crosses the seam as data".** Relied on and unchanged.
The envelope is a return value, not an exception, and the exception §3 already
tolerates gains a field rather than a role. The one sentence of §3 that reached
cost — "`ToolResult` carries no cost" — was already superseded by ADR-0192, and this
ADR touches neither it nor the disclosure half.

**ADR-0029 §4 and ADR-0031 §§1–2.** Untouched. The seam still owns the deadline, the
tool still never states an outcome, `interrupted_outcome` still classifies an
interruption, and §4 above hands a discarded classification's cost the same fate the
classification gets.

**ADR-0194 in its entirety — a stacked addition, and no record is owed.** No clause
of it becomes false and none is read more widely: §2's totals, the never-zero rule
and the allowance; §3's admission, reservation and release; §4's six grounds, their
order and both classes; §7's derivation and erasure rules. What changes is which
values its arithmetic reads, which is the mechanism working rather than a decision
moving. Its "estimate can understate what a call turns out to have cost" bound is
unchanged: a reported figure is still not a reservation.

**ADR-0016 §4 and §7.** Untouched. `cost` is still the declared price of one
invocation, and money a tool moves is still out of scope (§5, §8).

**ADR-0087.** Untouched, and measured rather than assumed: the envelope never
crosses the wire (§2), no promoted method's signature moves, and `ToolCost` with its
`Decimal` already reaches the encoding under ADR-0194's own partial supersession. No
`PROTOCOL_VERSION` bump is owed on this ADR's ground (ADR-0124 §9).

**ADR-0148 and ADR-0154.** Untouched. The egress seam's authorisation, its pinning
comparison and its fourteen attested conditions are unaffected: this ADR adds no
value the binding carries, no route around the endpoint comparison, and no
credential in either direction (ADR-0029 §6).

### 10. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a
reader holding only that ADR now act differently, or read one of its clauses more
widely than it now holds?

**ADR-0192 §5 — a record is owed, and it is an amendment.** The clause states that
no integration can populate `ToolResult.incurred_cost` and that ADR-0192 mints no
channel; after this ADR a channel exists. It is an **amendment** rather than a
supersession because nothing §5 *decided* is reversed and every operative rule it
states is relied on here: the destination field, the `None`-to-`UNKNOWN` mapping,
the prohibition on the declaration, the summing and open-claim clauses. A reader
implementing §5's mapping writes the same code before and after — the mapping is
`tools/consume.py`'s today and this ADR adds no branch to it — and what lapses is
the currency of a deferral whose owner §5 named. That is ADR-0194 §10's treatment of
ADR-0021 §6 and ADR-0029 §7, applied to the deferral this ADR discharges rather than
the ones that one did. The record is a `Status` qualifier naming this ADR and an
appended dated note on ADR-0192, per ADR-0082 §2; ADR-0192's `Status` line reads
`Accepted` and is not led by `Partially superseded by`, so the qualifier is not
excluded.

**ADR-0032 §1 and §6 — a record is owed, and it is an amendment.** §1 enumerates
`ClassifiedToolError`'s fields and §6 states the revalidation over them; both now
reach a third. It is an **amendment** because the enumeration grows rather than
changes: every field ADR-0032 named keeps its type, its default and its rule, the
new one is defaulted so every raise site written against ADR-0032 still constructs a
valid carrier, and §6's structure — read each attribute independently, resolve each
defect in its own pessimistic direction — is applied rather than altered. A reader
holding only ADR-0032 does not act *wrongly*; they act *incompletely*, which is what
ADR-0082 §1 puts on the amendment side. The record is a `Status` qualifier and an
appended dated note on ADR-0032.

**Everything else in §9 is a stacked addition and no record is owed.** ADR-0029
§§1, 3–4; ADR-0031 §§1–2; ADR-0016 §§4, 7; ADR-0087; ADR-0148; ADR-0154; ADR-0194
throughout. For each, every sentence stays true and the obligation this ADR adds is
stated here. ADR-0082 §1 is explicit that a record demanded on book-keeping grounds
alone is not owed, and none is taken.

**This ADR supersedes nothing and withdraws nothing.** It adds one `core` model, one
defaulted field on an existing `core` error class, and one widened `tools/`-internal
annotation, and it discharges one named deferral.

**The two records are stated here in their exact form and are not made by this
change** (ADR-0026 §6, ADR-0030 §6, ADR-0032 §8): writing "amended by ADR-0195" onto
a ratified ADR while ADR-0195 is only `Proposed` is the state claim ADR-0019
forbids.

- **ADR-0192's `Status` line becomes**
  `- Status: Accepted, §5's no-channel clause amended by ADR-0195`.
- **A dated note is appended to ADR-0192's header:**
  `Amended: <ratification date> by ADR-0195 — §5's "No integration can populate this
  field yet, and this ADR mints no channel by which one could" no longer describes
  the tree. ADR-0195 mints the channel §5 named #1558 as the owner of: a successful
  call reports a figure by returning core/types.py's ReportedOutput, which the seam
  unwraps, and a classified failure reports one on ClassifiedToolError's new
  keyword-only incurred_cost. Everything else in §5 stands and ADR-0195 rests on it:
  the field and its None meaning, the naming apart from ToolDefinition.cost, the
  report-only-what-you-know rule, the mapping onto the completion row, the summing
  clause, the open-claim clause and the prohibition on copying the declaration.
  ADR-0195 adds no field to ToolResult and no branch to the mapping. Refs #1558,
  ADR-0195 §2, §3, §9, §10.`
- **ADR-0032's `Status` line becomes**
  `- Status: Accepted, §5 amended by ADR-0039; §§1 and 6 amended by ADR-0195`.
  ADR-0039's clause is carried forward unchanged rather than replaced, for the
  reason ADR-0032 §8 itself gives about ADR-0031's.
- **A dated note is appended to ADR-0032's header, after the existing `Amended:`
  block for ADR-0039:**
  `Amended: <ratification date> by ADR-0195 — ClassifiedToolError carries a third
  attribute, keyword-only and defaulted: incurred_cost: ToolCost | None = None, what
  the call cost as the tool reports it (ADR-0192 §5). §6's revalidation reaches it
  and reads it independently of the other two, in that section's own idiom —
  ToolCost.model_validate(cost.model_dump()) — and a cost that does not survive is
  discarded alone: the outcome, the output, the failure and effect_may_have_committed
  all stand and the row records an UNKNOWN basis, which is §6's "each defect resolves
  in its own pessimistic direction" applied to a field whose pessimistic direction
  ADR-0194 §2 already fixes. The field is defaulted where §2 leaves
  effect_may_have_committed undefaulted, because silence about a price already means
  "no figure" while silence about a side effect would assert one. Nothing else moves:
  the carrier's base class, its placement outside ToolError, its core/errors.py home,
  its never-escaping-invoke rule, §2's outcome rule, §3's TIMED_OUT reservation, §4's
  precedence — which discards a reported cost together with the classification it
  pre-empts — and §5's by-value message rule are untouched. §1's "What is not
  contracted here" and §7's first bullet are untouched as statements about ADR-0032;
  the return type they describe is tools/-internal by ADR-0029 §1 and ADR-0195 §9
  records why no separate note is owed for widening it. Refs #1558, ADR-0195 §3, §4,
  §9, §10.`

### 11. What the implementing lane owes

> **Normative.** **One lane, one PR**, sequenced behind this ADR's ratification
> (ADR-0015 §5, golden rule 5) and behind ADR-0192's and ADR-0194's implementations,
> both of which are merged.

> **Normative.** **No triad is owed.** This ADR adds no Protocol to
> `core/protocols.py`, so `CONTRIBUTING.md` → "Adding a Protocol" is not engaged and
> ADR-0137 §2's pairing clause has no triad to pair.

> **Normative.** The lane touches `core/types.py`, `tools/` and
> `ai_assistant.testing`, and it is **one** lane under **ADR-0137 §1** on that
> section's own test — not under §2's pairing clause, which this ADR does not reach
> and does not ask to be widened. §1 admits a slice as one lane where it "puts
> substantial **new machinery** into at most one subsystem", and draws the line at
> new machinery against adaptation: machinery is "a store, a loop, a codec, a
> producer, a policy engine", and "adaptation does not count against the bound …
> A lane may carry adaptation across any number of subsystems."

> **Normative.** Applied here: the **new machinery is the unwrap-and-revalidate rule
> at the invocation seam, and it is in `tools/` alone**. `ReportedOutput` is a frozen
> two-field data model with no behaviour beyond declarative validation — every item
> in §1's enumeration is a *behaviour*, and a data type in `core/types.py` is the
> shared vocabulary every subsystem depends on under golden rule 2 rather than one
> subsystem's machine. `ai_assistant.testing`'s change is adaptation in §1's own
> words — "an implementation of a Protocol method a subsystem already almost
> satisfied" — since the fake invoker already implements the whole of `invoke`'s
> rules and gains the same one branch. The compounding §1 is about does not arise:
> the lane presents one new behaviour, which draws one class of finding.

> **Normative.** Splitting it would be worse and not merely inconvenient. A first PR
> adding `ReportedOutput` alone would be a contract-only PR whose type nothing
> constructs — the shape ADR-0194's own header calls "the contract-only PR followed
> by an implementation PR that §2 exists to prevent" — and the fake cannot be split
> from the seam at all: `ai_assistant.testing.invoker` "re-implements the rules rather
> than importing `ai_assistant.tools`" (ADR-0031 §1) and the shared conformance suite
> holds the two to one observable behaviour, so a PR moving either alone leaves the
> suite asserting a rule one side does not have. The lane is small: one model, one
> branch at the return site, one guarded revalidation, and the fake's mirror of them.

> **Normative.** The lane lands the **success exit only**, because that is the exit
> whose carrier exists. What lands:
> 1. `core/types.py`: `ReportedOutput` exactly as §2 states, exported.
> 2. `tools/invocation.py`: the widened return annotations on both callable
>    Protocols and on `EntersCallable`/`EnteredCallable`; the `isinstance` unwrap at
>    the success exit; §4's revalidation of the returned cost; §4's
>    discard-with-the-outcome rule where a return is converted into an interrupted
>    result.
> 3. `tools/consume.py`: the reported figure reaching `ToolResult.incurred_cost`.
>    `unknown_cost()` and the `None`-to-`UNKNOWN` mapping are unchanged.
> 4. `ai_assistant.testing`: `FakeToolImplementation`'s widened return and the fake
>    invoker's identical unwrap, revalidation and discard rules.
> 5. `ToolResult.incurred_cost`'s docstring, whose "**Nothing populates it yet**"
>    becomes false on this lane and is corrected with it.

> **Normative.** **`ClassifiedToolError.incurred_cost` is not this lane's**, and no
> lane implements ADR-0032 to make room for it (§3). It lands in ADR-0032 §9's own
> implementation lane, together with the carrier, and §3 and §4 bind that lane when
> it runs: the field's type, its default, its independent revalidation, its discard
> alone on a failed round-trip, and its discard with a classification ADR-0032 §4's
> precedence pre-empts. That lane is not commissioned here, and the gap it would
> close is filed as **#1614** rather than absorbed into this ADR's scope.

> **Normative.** What the lane proves, each case named so none is negotiated later.
> Every one is reachable against the tree as it stands:
> - a returned `ReportedOutput` reaches `ToolInvocation.incurred_cost` unaltered,
>   through **both** callable shapes;
> - a `ReportedOutput` carrying an `UNKNOWN` basis lands identically to a bare
>   return;
> - a `ToolCost.model_construct`-built cost that fails revalidation is discarded
>   **alone** — the outcome and the output survive and the row records `UNKNOWN`;
> - an envelope whose `output` `FrozenJsonValue` refuses yields `INTERNAL`, exactly
>   as a bare return of the same value does today;
> - a deadline expiry and a delivered cancellation each discard a reported cost with
>   the classification they pre-empt, and the row records `UNKNOWN`;
> - a returned JSON mapping carrying an `incurred_cost` key is output, not a report;
> - a `ReportedOutput` **subclass** whose `output` accessor raises takes the
>   `INTERNAL` path with its reported cost discarded, the completion written and the
>   claim closed;
> - a `ReportedOutput` subclass whose `output` accessor **cancels the invoking task**
>   has its result and its figure discarded: the cancellation propagates unchanged
>   and the interruption re-read is what sees it;
> - a `ReportedOutput` subclass whose `incurred_cost` accessor **raises** yields
>   `UNKNOWN` with the successful output and outcome intact, the completion written
>   and the claim closed;
> - a `ReportedOutput` subclass whose `incurred_cost` accessor **cancels the invoking
>   task** propagates the cancellation unchanged, and the row it leaves records
>   `UNKNOWN`;
> - a `ToolCost` subclass whose `model_dump()` **raises** yields `UNKNOWN` with the
>   outcome and output intact, the completion written and the claim closed — nothing
>   escapes `invoke` and no claim is left open;
> - a `model_dump()` that **cancels the invoking task** and returns a valid value has
>   its figure discarded: the cancellation is propagated unchanged and the
>   interruption re-read after the cost read is what sees it;
> - a `model_dump()` that returns a **different** valid cost crosses as the
>   round-trip's result, which is ADR-0032 §6's rule inherited rather than a new one;
> - **the end-to-end case ADR-0192 §9 deferred**: a registered tool that reports a
>   `PER_CALL` figure, through `invoke`, onto a completion row, into ADR-0194 §2's
>   accounted total, refusing a later call at a configured ceiling — driven against a
>   **test-only** priced integration and never against `send_email` (§7);
> - the fake invoker and the real seam agree on every case above.

> **Normative.** Three further cases are owed by ADR-0032's lane and are named here
> so they are not lost: a `ClassifiedToolError` carrying a cost lands it on the row
> with the failure kind and outcome unchanged; a cost on that carrier that fails
> revalidation is discarded alone, leaving the failure and
> `effect_may_have_committed` intact; and a classification ADR-0032 §4's precedence
> pre-empts takes its reported cost with it.

> **Normative.** The lane also applies §10's two records to ADR-0192 and ADR-0032,
> if this ADR's own PR has not, and files nothing else against them.

## Consequences

**A tool that knows its price can finally say so, and nothing else about the system
moves.** Until an integration reports one, every row records `UNKNOWN` exactly as it
does today and the QA record's measured behaviour stands unchanged. The change is
capacity, and it is visible only when a producer arrives.

**The ceiling gets a second, better mode without losing its first.** Where nothing
reports, `world_spend_unknown_allowance` remains what makes ADR-0194's ceiling a
working bound, and the user's stated worst case is what the arithmetic runs on.
Where something reports, the accounted total is made of measured figures and the
allowance is not consulted for those rows. The two coexist per row rather than per
configuration, which is what lets a partly-priced tool set behave sensibly.

**The overrun ADR-0194 §2 states gets smaller and does not go away.** A ceiling is
still enforced against declarations at admission and reconciled against reports only
in arrears, and this ADR deliberately adds no mechanism to close that: no reservation
adjustment, no retroactive refusal, no delta record. What it changes is that the
arrears figure is now true.

**`ClassifiedToolError` is specified more crowded before it is built.** It will hold
three independently-judged attributes, and ADR-0032's own strongest-case admission —
that raising a constructed model is "a mouthful on a path an integration author
writes a dozen times" — gets one field longer before anyone has typed the first two.
The ergonomic pressure that ADR predicted is real and this ADR increases it. The
mitigation is that the new field is defaulted, so nobody who does not need it types
it.

**Half of this decision has nowhere to land yet, and that is stated rather than
hidden.** The classified-failure exit is ratified by ADR-0032 and unbuilt, so §3 is a
specification waiting on a lane this ADR does not commission. A reader checking the
tree after ratification will find one carrier of the two, which is the correct state
and is why §1, §3, §7 and §11 each say so rather than leaving it to be discovered.

**A second return shape at the seam is a branch that did not exist.** `invoke`'s
success path now asks one `isinstance` question before building a `ToolResult`, and
the answer decides where the output comes from. It is one branch in one place, and
the fake invoker has to carry the same one — which is the cost of `ai_assistant.testing`
not importing `tools/`, paid once more.

**Nothing detects a tool that lies about its price**, and nothing here pretends to.
An integration reporting `0.0001` per call when it is billed `1.00` produces a
ceiling that does not bind, and the system has no second source to check it against.
That is ADR-0016's "a wrong number will mislead a spend policy, and no mechanism
detects the drift", now reaching a second field. The mitigations are the ones that
already exist: the tool is registered code, `ToolDefinition.cost` is the user-visible
declaration a policy floor already reads (ADR-0021 §5), and the allowance is
available for anyone who does not want to trust a report.

**The channel is decided before it has a producer**, which is a real cost: the shape
is fixed by argument rather than by contact with a paying upstream, and the first
producer may find it awkward in a way no reviewer here can see. ADR-0137 §2 exists
precisely because a contract hardened before its first real caller is a contract the
caller must bend around. What makes this the better trade is the alternative:
whichever integration lands first would otherwise mint a `core` type inside an
integration PR, where the architecture lens does not run.

## Alternatives considered

**A union return that carries a `ToolFailure`, i.e. #192's second option.** Not
proposed and still refused. ADR-0032's grounds hold whole: a tool already has a
raising channel for a failure, so a union arm would be a second spelling; and
ADR-0031 §2's tamper-resistance argument bites on any return that reaches the
outcome. `ReportedOutput` carries neither an outcome nor a failure and cannot be
made to: the model has two fields, `extra="forbid"`, and `output` admits no model.

**Returning a `ToolResult`.** Refused, and this is the refusal that transfers
without qualification. It hands the callable `outcome` — the field ADR-0031 §2
built a cancellation delta, a trusted-binding classification and a precedence rule
to protect — and it would restate ADR-0029 §4's `INDETERMINATE` rule as an
obligation on every integration author, enforced by documentation. Everything below
keeps the outcome the seam's.

**A union return carrying a cost, i.e. what §2 decides — weighed against ADR-0032's
own objections to a union.** Three objections, taken in turn.

*"A contract with two spellings of one thing."* The objection is precise and it does
not transfer. ADR-0032 refused a union arm for a fact the tool could **already**
report by raising; there is no cost channel for `ReportedOutput` to be the second of.
§2 then forecloses the failure mode from inside: the envelope's cost is required, so
"return the value bare" and "return an envelope" are not two ways to say the same
thing, and §5 states in terms that an `UNKNOWN` envelope lands identically to silence
so that no reader can build a distinction on it.

*"Changes `ToolImplementation`'s return type, which breaks every implementation."*
True of returning a `ToolResult`, which replaces the return position and obliges
every tool to construct one. Not true of a **widening** union in a structurally-typed
world: a callable returning `FrozenJson` satisfies `FrozenJson | ReportedOutput` by
covariance, and every registered tool in this tree keeps type-checking untouched.
The only party that must change is the seam, which this ADR changes anyway. This is
the one place where ADR-0032's sentence reads more widely than its own argument
supports, and §9 records that as a stacked addition rather than a correction: the
sentence is true of the option ADR-0032 was actually deciding.

*"ADR-0029 §3 argued failure crosses as data; an exception is a strange carrier."*
That argument is ADR-0032's own strongest case against itself, and it points the same
way here: "#192's second option is the shape that matches ADR-0029 §3's own
reasoning — a return value for a returned fact." A cost from a successful call is a
returned fact with no exception in sight, so the return position is where it belongs.
§3's addition to `ClassifiedToolError` is the narrow converse — a failed call's price
travelling on the carrier that failed call already composes, rather than a second
mechanism beside it.

**A context object, sink or out-parameter the seam passes and the tool writes to.**
Rejected, and it is the strongest rejected candidate, because it is the only shape
that covers all four exits including the two §1 declines to cover. Four counts
against it. It is **mutable state crossing the seam**, in a contract whose every
neighbouring rule — `ToolCall`'s frozen fields, ADR-0021 §4's detached snapshots,
ADR-0192 §2's detached rows — exists to stop a value being rewritten after it was
read; a tool that retains the sink can write to it after the row is written, and the
rule that this must not matter would be enforced by documentation. It requires a
**parameter** on both callable shapes, which unlike a widened return really does
break every implementation, or else a third and fourth shape and a two-by-two
registry resolution. Its extra coverage is **coverage of exits where there is nothing
to report**: on an escaping exception the tool did not compose an exit, and on an
expired deadline the callable is still running, so a sink read at those moments reads
a value written by a frame that had not finished. And it adds a shared object to
`invoke` at exactly the moment #1553 and ADR-0194 §8 have the seam's concurrency
open. The honest summary is that it buys reach into two cases whose right answer is
already `UNKNOWN`, and pays for it in the coin this corpus is least willing to spend.

**A `ContextVar` the seam binds and the tool writes through.** Rejected, though it
answers the parameter objection completely: no signature moves, no shape multiplies,
both existing shapes and every future one compose with it, and per-invocation
isolation falls out of asyncio's context copying. It is rejected because the channel
would be **invisible in every type signature** — an integration author learns it
exists from prose or not at all, which is the "safety-critical rule enforced by
documentation" ADR-0031 §1 was written to remove; because a tool that does its work
in a spawned task or a thread would silently write into a copied context; and because
`core` would gain module-level mutable state that a test must remember to reset.
The counter-argument is real and worth recording: this convention's failure mode is
`UNKNOWN`, which is the conservative direction, unlike ADR-0029 §4's rule whose
failure mode was unsafe. It was not enough. A channel nobody can see in a signature
is a channel nobody uses, and the one thing this ADR must produce is a shape an
integration author will actually reach for.

**A per-registration declaration of a measured tariff.** Rejected on ADR-0192 §5's
existing prohibition, which forbids the declaration reaching a row labelled incurred,
and on ADR-0016 §4's, which refused a declaration standing in for a measurement. The
honest version of this idea already exists and is ADR-0194 §1's
`world_spend_unknown_allowance`: the user, who is the party who actually knows what
their connected account is charged, stating a per-call worst case in configuration,
outside any turn, where it feeds the **arithmetic** and touches no row. This ADR
leaves that untouched and adds the other party's channel beside it.

**A figure the seam computes.** Rejected because the seam never can. It sees a
coroutine returning and a clock, and #1558's own framing hedges it — "where the seam
can see one". ADR-0191 §4 puts the general principle where it belongs: the party that
does not know is not the party that decides. Deriving one from `ToolDefinition.cost`
is the previous alternative wearing the seam's name.

**A second face on the definition — a registered "cost reporter" the seam asks after
the call.** Rejected on correlation. Such a face is asked "what did the last call
cost", and ADR-0194 §3 records that more than one invocation is in flight today
(#1561), so "the last call" is a race the reporter would have to resolve with a
token the seam would have to mint and pass — which is the sink, reached by a longer
route and with an extra object in it.

### The strongest case against this decision

It decides a `core` type for a producer that does not exist, and it decides it in the
narrowest way available — two exits, not four — which means the first real producer
may arrive wanting exactly the coverage §1 declined. An integration whose upstream
bills a request that then times out will find that this ADR has ruled its price
unreportable by construction, and the answer it gets is "the row records `UNKNOWN`,
which is the truth" — true, and no comfort to someone whose ceiling is now
indeterminate on every timeout. The sink shape would have covered it, and the
argument against the sink is largely an argument from this corpus's aesthetics about
mutable state rather than from a demonstrated failure.

The answer is that the two uncovered exits are the two where the tool demonstrably did
not finish speaking, and a channel that let it speak anyway would be reading a value
out of a frame the seam has just declared abandoned — which is the same error as
letting the callable state its own outcome, one field over. And the cost of being
wrong here is bounded and legible: `UNKNOWN` is not a silent zero, ADR-0194 §2 makes
it visible as an indeterminate period, and the allowance is a configuration the user
already has. If a real producer arrives and the two exits bite, the trigger is
recorded in §8 and the remedy is an ADR that widens this one — with a paying upstream
in hand, which is more than this decision has.

A second thing it does not cover is that §3 decides a field on a class nobody has
written. If ADR-0032's lane never runs, §3 is dead text; if it runs and finds the
carrier wants a different shape, §3 is text that lane must argue with. Deciding it
anyway is the lesser of the two available errors — the alternative is that lane
minting a cost field in an implementation PR, unreviewed by the architecture lens and
free to diverge from §4's rules — but it is an error either way if the lane never
comes.

What this defence does not cover is the timing. ADR-0137 §2 exists because a contract
hardened before its first real caller is one the caller must bend around, and this ADR
hardens one with no caller at all. The reason it is written now rather than later is
ADR-0032's — an integration PR is not where a `core` type gets architecture review —
and that reason is about *where* the review happens, not about whether the shape is
right. The shape is an argument. It has not met a bill.
