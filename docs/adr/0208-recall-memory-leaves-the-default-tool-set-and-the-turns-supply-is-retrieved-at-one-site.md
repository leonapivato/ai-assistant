# 208. `recall_memory` leaves the default tool set, and the turn's supply is retrieved at one site

- Status: Accepted
- Date: 2026-08-28

## Context

### Where this comes from

The milestone-19 measurement on the deployed hub (**#1699**) put two spoken
utterances through a live turn. *"What is my name?"* composed and was spoken back.
*"What do I take in my coffee?"* reached `AWAITING_CONFIRMATION` in 4.9 s and said
nothing at all: the planner had named a memory lookup, the selection stage found
`recall_memory`, and that tool's `MEDIUM` risk drew a `CONFIRM` under the default
policy. On the tree #1699 measured, a park on the spoken channel was silence
(ADR-0200 §4 — "`spoken` is `None` wherever `outcome.reply` is `None`"), so the owner
held the button, asked, released, and heard nothing while a confirmation card
appeared on a screen they were not looking at. ADR-0207 §1 has since replaced that
clause for this shape: such a pass now says one fixed sentence naming the screen. The
silence is answered; **the park is not**. The owner still asked a question about
their own memory and still did not get it answered, and that is what this decision
is about.

That reading is filed as **#1715**, with the owner's ruling on it: **unregister**.
This ADR is that ruling written down. The useful capability the tool gestured at —
a planner-named second retrieval into the supply — is **#1732**, a separate
decision this ADR defers to by name and does not take.

### The tree, read for what actually happens on a turn

**A turn already reads the store, before it plans.** `ConversationLoop` assembles
the supply ungated: beliefs by band precedence through `assemble_by_band`
(`orchestration/retrieval.py`) under ADR-0072 §5's per-band composition and
ADR-0113's `bands` filter, then a bounded episodic supplement (ADR-0158 §1). That
supply is rendered into the planner's own user message, one line per record
(ADR-0047 §3), and the planner is told in terms to decline "where the goal is
answered from what the turn already carries — the retrieved memories, the assembled
context, and the conversation rendered into this same prompt" (ADR-0176 §4).

**The tool reads the same store, worse.** `RecallMemory` (`tools/builtin.py`) holds
a `MemoryStore` injected at the composition root — wired to the *same* instance the
loop retrieves from, which `build_default_registry`'s own documentation states — and
performs one `MemoryStore.search` call at a caller-supplied `query` and `limit`. It
is band-blind: no band precedence, no per-band budget, no kind filter, none of the
machinery ADR-0072 §5 and ADR-0113 §6 put in `assemble_by_band` because a
band-neutral single read let "a flood of low-confidence inferences … displace an
assertion *below the cut*". And its query is the plan's, not the goal statement the
retrieval stage searched, so the two share a store rather than a result set: the
second read *may* surface a row the first did not.

**That possibility is the tool's one real argument, and it is not being waved
away.** What it is not is an argument for the tool, because a row it surfaces is
surfaced without the precedence, budget and kind filter that decided what the first
read kept, and — as the next section establishes — is surfaced into a payload no
reply is composed from. A find nobody can read is not a find. §4 states the same
thing from the other side, and #1732 is where the capability is actually decided.

### What the tool's result reaches, and what it does not

**It reaches the durable step record.** A `SUCCEEDED` result's `output` is written
into the execution record by the executor's `_record`/`_finish` path, and it is
readable by an operator through the audit surface.

**It reaches no reply.** The composing stage renders a driven step from four closed
vocabularies alone — `Disposition`, `StepStatus`, `SkipReason`, `ToolFailureKind`
(ADR-0170 §5, and §5a's "renders the step account as a **deterministic local
summary** … and passes none of that free text through"). The type the stage is given
does not carry the payload either: `StepOutcome` has `disposition`, `state`,
`step_id`, `tool_id` and `confirmation`, and no output member. So there is no route
by which a recalled record becomes a word the user reads or hears. An approved
`recall_memory` step changes the reply not at all; the answer is composed from the
supply the loop assembled one stage earlier.

That is not an oversight to be repaired by wiring the payload in. ADR-0170 §5a
excludes it deliberately, as a prompt-injection defence: a tool result is a JSON
payload with no per-span provenance, and the stage is a prompt assembler that ADR-0098
§2 binds to presenting external content as third-party data by "data the assembler
holds … never from inspecting the text".

### What the confirmation buys

`RECALL_MEMORY` declares `risk_level=MEDIUM` with `reads=(PERSONAL,)`, and the
default `confirm_at_risk` is `MEDIUM`, so `ThresholdActionPolicy` returns `CONFIRM`
on every invocation. ADR-0048 §2 argued that declaration and was right to: under
ADR-0016 §3 risk is not constrained by `side_effecting`, and under-declaring to make
a demo smoother is the forgetful-author failure that section refuses. Nothing here
disputes the declaration.

What the confirmation *buys* is the question. It gates a read of the owner's own
store that the same turn has already performed ungated one stage earlier, at a
larger and better-ordered budget, whose result is composed into nothing. It costs a
park per firing — on the typed channel a card, on the spoken channel a card and,
since ADR-0207 §1, a sentence naming it (#1699 measured the silence that preceded
that ruling) — and #1715 records the honest summary: "The confirmation protects nothing: same
data, same `search`, already read one stage earlier ungated; the result is composed
into nothing."

The remedy of re-declaring it `LOW` was considered and is in Alternatives. It buys
the park back and leaves everything else standing, including the next paragraph.

### The latent path, stated before the decision

On an operation whose output channel's audience is unbounded, ADR-0203 §1 subtracts
the withheld content from the turn's supply **before the turn plans**, at one site,
and ADR-0204 §3 adds the stamped-record test at that same supply site. A tool
invocation runs downstream of that site and reads the store directly, so a
`recall_memory` result on a spoken turn is band-blind *and* unwithheld: records
ADR-0199 §3 places as unspeakable on that channel — an `about_person` record, a
record whose `Provenance.supplied_withheld_content` is `True` — come back through it
untouched.

That is harmless **today**, and only because ADR-0170 §5a keeps the payload out of
composition. It stops being harmless the moment anyone wires tool output into a
reply, which is exactly the shape #1732 exists to consider. A latency defence that
depends on a second, unrelated clause staying as it is, is a leak with a delay on
it.

### What is not in dispute, and is used as given

- **ADR-0170 §5a's exclusion of tool output from the prompt.** It stands, and this
  ADR neither relaxes it nor leans on relaxing it.
- **ADR-0016 §3's honest-declaration rule and ADR-0021 §5's floors.** Untouched in
  both directions. This decision removes a tool; it re-declares nothing.
- **ADR-0053's alias layer.** Its four-branch resolution, its "an alias only ever
  resolves onto a name the registry *currently advertises*" rule, and its
  "an alias entry whose target is not (yet) advertised is inert" consequence are
  used as given, and §2 below is decided *on* them.
- **ADR-0176's decline.** The decline envelope, its rationale condition and its
  prompt test are used as given and are not reopened.

### An honest statement of what this ADR is not allowed to settle

Whether the planner should be able to ask for a *second* retrieval — into the
supply, with provenance intact, past the disclosure filter, and with no card — is a
real capability question with a real design behind it (#1732 sets out the envelope,
the bound, the ADR-0170 §2 reading it needs, and the measurement that should decide
whether it is worth building). This ADR is not that decision and may not be read as
prejudging it in either direction. What it decides is that the *tool* is not the
mechanism for it, which #1732's own first section already argues from provenance,
disclosure and permission.

Nor does this ADR decide anything about `remember` or any future memory *write*.
ADR-0048 §1 deferred that with its idempotency question and this changes nothing
about it.

## Decision

### 1. `recall_memory` is not a member of the default registry

> **Normative.** The default tool registry `build_default_registry` returns does
> not bind `recall_memory`. After this decision the registry it returns holds
> `current_time`, and the configured egress tool where a deployment has connected
> an account; no memory tool is among them.

> **Normative.** No lane registers a tool whose implementation reads a
> `MemoryStore` into the default registry, or into any registry the turn path
> selects from, without an ADR that decides the question this one leaves to #1732.
> "Re-adding it behind a lower risk level" and "re-adding it under another id" are
> both that registration.

> **Normative.** On the turn path the assistant's own store is read **for
> relevance** — records selected by their bearing on the goal rather than by an
> identifier the turn already holds — at exactly one site: the retrieval stage. One
> site is not one call, and this clause bounds no read that site makes: its per-band
> reads (ADR-0072 §5, ADR-0113) and its episodic supplement (ADR-0158 §1) are
> unchanged, and nothing here removes, merges or budgets any of them.

> **Normative.** That clause binds a relevance selection and nothing else. A **keyed
> load** — records the turn already names, fetched by identifier — is not a second
> retrieval and is untouched in both directions: `ConversationLifecycle.history`
> loading the current conversation's episodes through `MemoryStore.get_many` reads
> the same store on every turn that has history, and goes on doing so. A routed
> pass resolving its own argument (ADR-0201 §5) is likewise untouched; it is not
> the `ConversationLoop` path this clause is stated over.

> **Normative.** A component on the turn path that wants records the supply does
> not hold does not obtain them by invoking a tool.

**Both scoping clauses are marks rather than prose beside one, because each of them
is a rule a lane could otherwise get wrong in a way that costs something real.** A
rule counting *calls* would forbid `assemble_by_band`'s per-band reads — the whole
of ADR-0072 §5's remedy for a band-neutral single read letting "a flood of
low-confidence inferences … displace an assertion *below the cut*" — and would
forbid ADR-0158 §1's episodic supplement beside them. A rule counting *readers of
the store* would forbid the conversation history load, which is how a turn sees the
exchange it is continuing and which selects nothing. What this decision counts is
*relevance selections into the turn's supply*, and after §1 there is one.

**The ground is that the read is already performed, better, one stage earlier.**
Every property the tool lacks, `assemble_by_band` has: band precedence and per-band
budget (ADR-0072 §5, ADR-0113), the belief kind filter, the episodic supplement
(ADR-0158 §1), and — on a channel of unbounded audience — the withholding at the one
site ADR-0203 §1 fixes. The tool's read is the same rows without any of that,
behind a confirmation, into a payload nothing renders.

### 2. What goes with the tool, and what ADR-0048 keeps

> **Normative.** The `RECALL_MEMORY` declaration and the `RecallMemory`
> implementation are deleted from `tools/builtin.py` and from the `tools` package's
> exports, together with the tests that exercise them as shipped tools. Neither is
> retained as a test-only fixture; a test needing a definition with parameters
> constructs its own.

> **Normative.** The eight `CAPABILITY_ALIASES` rows in
> `orchestration/capability_alias.py` whose target is `recall_memory` are deleted
> in the same change: `recall`, `recall_memories`, `search_memory`,
> `search_memories`, `retrieve_memory`, `memory_recall`, `memory_search` and
> `lookup_memory`.

> **Normative.** Deleting those rows is the table maintenance ADR-0053 already
> prescribes and is not a change to what ADR-0053 decided. No record is owed on
> ADR-0053 under ADR-0082 §1, and the whole of ADR-0053's ratified resolution rule
> — its four branches and its live-registry check — is untouched.

**Why deletion rather than leaving the rows inert.** ADR-0053 is explicit that "an
alias entry whose target is not (yet) advertised is inert: the step falls through to
branch 4 and is reported `NO_CAPABLE_TOOL`, exactly as if the alias did not exist",
so behaviour is identical either way and nothing is being *fixed* by removing them.
What a dead row is, is a written claim that this system serves `search_memory` —
maintained under a heading saying the table tracks the shipped tools — and the next
author to add a memory tool would find eight aliases already pointing at whatever
they named it. That is the wrong-tool hazard ADR-0053 says the layer exists to
avoid, arriving through the table rather than through the algorithm.

**Why the class goes too.** Keeping `RecallMemory` as test-only would leave a
working, `MemoryStore`-backed tool implementation in `tools/` that one line in a
factory re-arms, with no ADR between it and the registry. The class is thirty lines
over `MemoryStore.search`; if #1732 or a later decision wants a memory tool, it will
want one shaped by that decision, not this one recovered from history. The corpus
keeps ADR-0048's text, which is where the design is preserved.

> **Normative.** What ADR-0048 §1 demonstrated — that a tool may depend on another
> subsystem only through that subsystem's Protocol, wired at the composition root —
> is not superseded and is not lost. It is the pattern every `orchestration`
> collaborator and the configured egress tool follow, and the retrieval stage
> follows it over the same `MemoryStore`.

### 3. A lookup-shaped step is a planner error the decline rule already covers

> **Normative.** With no memory tool advertised, a plan step naming a memory-lookup
> capability resolves to no advertised name and is reported `NO_CAPABLE_TOOL`
> (ADR-0037 §1). That outcome is correct and is not a capability gap to be closed
> by re-registering a tool.

> **Normative.** A goal answered from the supply the turn already carries is a
> **decline** under ADR-0176 §4's test, not a plan naming a lookup. Where the
> planner names one anyway, the defect is in the plan, and the remedies available
> to a later lane are the ones ADR-0176 and ADR-0170 §5 already provide — the
> prompt's statement of the test, and the composing stage's obligation to state
> what the assistant did not do — not a tool.

ADR-0176 §4 names this exact direction, concretely: *"what do you know about me?"*
declines, "because the beliefs that answer it are already rendered above". A memory
question is the paradigm case of a decline, and the reason it has been reaching a
tool at all is that a tool was there to reach. #1695 records the mirror defect for a
stated *fact* — the planner planned a store step, no tool carried it, and the reply
told the owner it could not remember something that had in fact been captured — and
its remedy is stated in the same register: "the planner should not plan a store step
for a stated fact (a statement is not a task — cf. ADR-0176's planner decline)".

> **Normative.** This ADR does not change `ModelBackedPlanner`, its prompt, the
> decline envelope, or any test of them. §3 states how an existing rule reads after
> §1, and obligates no edit to `planning/`.

### 4. What is not lost

> **Normative.** No capability a user exercises today is removed by §1. A question
> about the owner's own memory is answered from the supply the retrieval stage
> assembled, exactly as it is answered today whenever the planner declines; what is
> removed is a confirmation and a step whose result nothing renders.

Stated as a before-and-after, because "we removed a tool and nothing was lost" is
the kind of claim that deserves the check. Before: the planner names a lookup, the
step parks at `CONFIRM`, the owner approves, the tool re-reads the store band-blind,
the payload lands in the execution record, and the composing stage — which never
sees it — composes the answer from the supply. After: the planner declines (or the
step is `NO_CAPABLE_TOOL`), and the composing stage composes the answer from the
same supply. The composed answer is produced over the same records either way. The
difference is one park, one wasted read, and one durable payload nobody reads.

The one thing genuinely forgone is the *possibility* that the second read finds a
belief the first missed — a belief phrased differently from the question. That was
never realised, because the payload reaches no reply; it is the useful half, and
#1732 is where it is decided.

### 5. Scope: `tools/`, one alias table, and no contract surface

> **Normative.** This decision adds no member to `core/protocols.py` and no member
> to `core/types.py`, changes no Protocol method signature, and moves
> `PROTOCOL_VERSION` not at all. `ToolDefinition` is unchanged; a registry holding
> one fewer tool is not a contract change, and no triad is owed.

> **Normative.** Because no contract surface moves, this decision is Accepted on
> merge rather than ratified contract-first, and is reviewed adversarial-only
> (ADR-0015 §1).

> **Normative.** The audit trail's existing rows are not rewritten, migrated or
> re-resolved. A historical `PermissionDecision` or execution record naming the tool
> id `recall_memory` stays exactly as it was recorded, and nothing re-resolves a
> recorded id against the live registry.

### 6. The tests this decision owes

> **Normative.** The implementing lane pins that the registry
> `build_default_registry` returns advertises no memory capability — asserted over
> the registry's advertised capabilities and its tool ids, not by the absence of an
> import — for a call with an egress integration and for one without.

> **Normative.** The same lane pins that a plan step naming a memory-lookup
> capability the deleted rows used to serve — at least `search_memory` — reaches
> `NO_CAPABLE_TOOL` through the real selection path, rather than selecting a tool
> or reaching a confirmation.

> **Normative.** The same lane pins that `resolve_capability` returns
> `search_memory` unchanged against the registry's live advertised set, which is
> ADR-0053's branch 4 and is what makes the deletion honest rather than merely
> tidy.

> **Normative.** The same lane pins that **no value in `CAPABILITY_ALIASES` is
> `recall_memory`** — asserted over the table's values, so a surviving row fails
> the test whatever key it is written under. This clause pins §2's deletion and
> nothing wider: it is not a rule that the table may hold no inert entry, which is
> a rule ADR-0053 declined to make and this ADR does not make for it.

**Three tests rather than two, because the first two cannot see a row left behind.**
The selection-path test is the one that matters for §1: a lane that deleted the rows
but left the tool bound fails it, where a table-shaped assertion alone would pass.
But it does not run the other way. If a lane deletes the tool and leaves all eight
rows, ADR-0053's live-registry check makes every one of them inert — `search_memory`
folds onto no advertised capability, branch 3's target is not advertised, the name is
returned unchanged, selection reports `NO_CAPABLE_TOOL` — and every test above it
passes while §2's deletion is unperformed and eight dead claims stand. Only the
values assertion fails on that. Neither test subsumes the other, which is why both
are owed.

### 7. What the implementing lane owes

The implementation is one lane, briefed after this ADR merges. It owes:

1. **`tools/`** — `RECALL_MEMORY`, `RecallMemory`, their exports and their tests
   deleted; `build_default_registry` no longer binding a memory tool, with its
   `memory` parameter and its documentation of that parameter removed rather than
   left taking an argument nothing uses.
2. **`orchestration/capability_alias.py`** — the eight rows of §2, and the comment
   paragraph that explains them, which is about a tool that no longer exists.
3. **`app/composition.py`** — the `memory=` argument at the
   `build_default_registry` call site, and the two comment passages that describe
   the registry as holding `current_time` and `recall_memory`.
4. **The tests of §6**, and the repair of the tests that use `RECALL_MEMORY` as a
   fixture for something other than the tool — `tests/core/test_parameter_schema.py`
   uses it as a definition carrying a parameters schema, and constructs its own
   instead.
5. **Closing #1715**, which this decision answers and that lane performs.

> **Normative.** The implementing lane changes nothing in `planning/`, nothing in
> `orchestration/composing.py`, nothing in `orchestration/disclosure.py`, and no
> risk, reversibility or disclosure declaration on any surviving tool. A finding
> that wants any of those is a separate issue.

**The record owed on ADR-0048 is made in the change that carries this ADR**, whose
fence is widened for it, so no later lane can be the one that forgets. ADR-0048's
`Status` reads `Accepted`, a plain line with no leading token, so recording this
partial supersession makes it a leading-token line and ADR-0082 §2 governs the form.

> **Normative.** The record owed on ADR-0048 is one change making two edits
> together: its `Status` line takes the leading `Partially superseded by ADR-0208
> (<scope>)` form of ADR-0070 §4 and `docs/adr/template.md`, and an appended dated
> note records the supersession (ADR-0070 §1). Applying one edit without the other
> is not a partial record.

> **Normative.** The scope is written, in both places, as: §1's `recall_memory`
> half of the first tool set, §2's declaration row for it, and §3's `memory`
> parameter as the dependency the factory binds it with. Nothing else of ADR-0048
> is replaced, and nothing else of ADR-0048 is touched by that change.

**What that scope leaves standing, said plainly, because the section it names does
several things.** ADR-0048 §1's `current_time` half is untouched, and so is every
reason it gives for the set being small — one tool per capability, no egress, no
idempotency window, no spend policy. §1's deferral of `remember` stands. §2's
`current_time` column stands, and so does its argument for `MEDIUM` being the honest
declaration for a Tier 1 read, which this ADR agrees with and does not need to
overturn to reach §1. §3's factory — one object implementing both `ToolRegistry` and
`ToolInvoker`, registration staying inside `tools/`, the composition root supplying
dependencies and taking back a ready registry — stands whole; what is replaced is
`memory` being one of those dependencies.

### 8. What this ADR does not decide

> **Normative.** Beyond §§1–7, this ADR decides nothing. It changes no ADR other
> than the clauses of ADR-0048 named in its header, adds no name to `core`, and
> moves no method signature.

- **A planner-requested second retrieval into the supply** — the useful half — is
  **#1732** and is deferred to it by name. #1732 carries the envelope question, the
  one-per-turn bound, the ADR-0170 §2 reading a loop-level second read needs, where
  the disclosure filter runs over the union, and the measurement that should decide
  whether it is worth building at all. Nothing in this ADR is cited toward that
  decision in either direction.
- **What a parked spoken turn sounds like.** #1699 asked it and **ADR-0207** decided
  it: one fixed sentence naming the screen, partially superseding ADR-0200 §4 for
  that shape. This decision removes the most frequent cause of such a park and
  changes nothing about how one is spoken; ADR-0207 governs that, unchanged and
  uncited toward anything here.
- **A memory *write* tool.** ADR-0048 §1 deferred `remember` with the
  side-effecting-idempotency question it carries, and that deferral is untouched.
  ADR-0053's refusal to alias a write intent onto a read is likewise untouched, and
  is now vacuous rather than wrong.
- **Whether the planner should be published the registry's vocabulary** (#60,
  #296). ADR-0053's deferral stands exactly as it stands.
- **Anything about the declarations of surviving tools.** No risk level moves.

### 9. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**The change to ADR-0048 is a supersession, not an amendment.** A reader holding
only ADR-0048 would today build a default registry binding `recall_memory` and a
factory taking a `MemoryStore`. After this decision they would not. That is a change
to what was decided, and ADR-0070 §1 makes it a supersession. It is **partial** —
ADR-0070 §3 makes that a first-class form — because §1's `current_time` half, §2's
`current_time` row, and the whole of §3's factory arrangement stay accepted.

**No record is owed on ADR-0053.** Applying ADR-0082 §1's test to ADR-0053's text:
no ratified sentence of it becomes false or over-wide. Its resolution algorithm is
unchanged; its live-registry check is unchanged and is what makes the removal safe;
its statement that the table is "hand-maintained" and that "adding a tool with a new
vocabulary means adding entries here" makes deleting a departed tool's entries the
maintenance it prescribes rather than a departure from it. Its Consequences observe
that "a plan naming `search_memory` selects `recall_memory`" — an illustration drawn
from ADR-0048's tool set, which this ADR's record on ADR-0048 is the pointer for, and
which ADR-0053's own inertness clause already tells a reader how to read. A record
demanded on ADR-0053 would be the book-keeping demand ADR-0082 §1 forbids: it names
no sentence that fails the test.

**No record is owed on ADR-0144, ADR-0155 or ADR-0098.** Each names the two shipped
tools in Context or in argument, not in a ruling. ADR-0144's observation that
"`AMBIGUOUS_CAPABILITY` is unreachable in the shipped registry today" is *more* true
after this change, and its ranking rule is stated for a registry of many discovered
tools rather than for this one. ADR-0155 §3's two paths are decided over any
component that introduces a store value into covered content — the retrieval stage
is such a component and remains one — so its ruling is unchanged; what goes stale is
one descriptive clause naming the tool as registered, which is a Context statement
about the tree, not a decision a reader acts on.

**No record is owed on ADR-0170, ADR-0176, ADR-0203, ADR-0204, ADR-0021 or
ADR-0016.** This ADR adds an obligation none of them wrote and contradicts no
sentence any of them wrote — a stacked addition under ADR-0082 §1, recorded here and
nowhere else.

**This ADR is marked** (ADR-0089 §4), so its marked clauses are the whole of what it
obligates, and the prose beside them is read to determine what they mean.

## Consequences

- **A memory question stops parking.** The most frequent `CONFIRM` on the turn path
  disappears, and with it both the silence #1699 measured and the sentence ADR-0207
  put in its place — a park that no longer happens needs neither. The answer is
  composed from the supply, which is where it was composed from all along.
- **One relevance read per turn, at the site that has the machinery.** Band
  precedence, budgets, the kind filter, the episodic supplement and — on an
  unbounded channel — the withholding all apply to it, because there is no longer a
  second relevance read that bypasses them. The conversation history load is
  unaffected and selects nothing.
- **A latent leak path is closed by removal rather than by care.** With no tool
  reading the store downstream of ADR-0203 §1's site, the question of what a future
  wiring of tool output into composition would leak from a spoken turn does not
  arise for this tool at all.
- **The default registry has one local tool and one conditional egress tool.**
  `current_time` is the whole of the local set, which makes ADR-0144's
  `AMBIGUOUS_CAPABILITY` observation still true and makes the tool set smaller than
  it was when ADR-0048 shipped. That is uncomfortable to write and is the honest
  state: the breadth this system needs is actuators (`docs/roadmap.md` item 12), not
  a read of its own store dressed as one.
- **The useful capability is now un-owned until #1732 is decided**, and that is
  visible rather than papered over by a tool that appeared to serve it. #1732 names
  the measurement that should decide it: how often the tool's confirmations were
  drawn on questions the supply did *not* answer.
- **Revisit when** #1732 is ruled, when a memory *write* capability is proposed, or
  when a decision wires tool output into the composed reply — which would need
  ADR-0170 §5a reopened first, and would make this ADR's latency argument load-bearing
  rather than precautionary.

## Alternatives considered

**Keep the tool and declare it `LOW`.** #1715's option 2. The default policy would
`ALLOW`, the park would go, and the change would be two characters. Rejected on
three counts. It is a declaration change to make a workflow smoother, which is the
direction ADR-0016 §1 exists to make expensive — and although the honest argument
for `LOW` exists (the tool discloses nothing off-device and its result reaches no
reader), it is an argument that the read is *pointless*, not that it is *safe*, and
"pointless" is an argument for removal. It leaves the band-blind second read in
place. And it leaves the tool sitting downstream of ADR-0203 §1's withholding site,
which is the half of #1715 that a risk-level edit cannot touch.

**Keep the tool and wire its output into composition.** This is the version where
the second read becomes useful. It requires reopening ADR-0170 §5a — a
prompt-injection defence — for a payload that carries no per-span provenance, and it
reopens #1692's leak on the spoken channel, since the payload is assembled downstream
of the one withholding site. #1732 sets out why the *tool* cannot be the mechanism
and what a loop-level re-retrieval would have to decide instead. Rejected here and
deferred there.

**Keep `RecallMemory` as a test-only fixture.** Rejected in §2: a live,
`MemoryStore`-backed implementation one factory line away from the registry, with no
ADR between it and re-registration, is the arrangement this decision exists to end.

**Leave the eight alias rows in place as inert.** Behaviourally identical under
ADR-0053's own inertness clause, and rejected in §2 for what a dead row asserts to
the next author rather than for what it does.
