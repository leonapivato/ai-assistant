# 147. An MCP server describes tools; this repository declares them

- Status: Proposed
- Date: 2026-08-13
- **Decides the integration shape** `docs/roadmap.md` item 12 is built on: how a
  tool a server describes becomes a `ToolDefinition` under ADR-0016 §1, what an
  MCP server is to the egress model, what happens to a schema and to a result,
  and what an id composes from.
- **Names ADR-0017 §2's `tools/` seam module (#66) and designates nothing.** §2
  assigns the naming to "the integration ADR", which this is. Naming is not
  designating: §3 below states in a marked clause that no byte is authorised by
  this ADR and that every one of ADR-0017 §3's fourteen conditions stands
  exactly as written.
- **Adds no `core` surface.** No Protocol, no type, no field, no error class, and
  **no meaning attached to a `core` value that any consumer reads**: §7's
  clauses keep `ToolDefinition.id` an opaque `Identifier` and put the provenance
  fact in the declaration set instead, so nothing outside the composition that
  mints an id may interpret one. `ToolDefinition` is used as ADR-0016 §1 and
  ADR-0018 ratified it, and every rule below is a rule about what may be *put in*
  one.
- **Required review set: adversarial *and* architecture.** **Declared, not
  compelled**, on ADR-0146's grounds read onto this subject:
  `CONTRIBUTING.md` → "Stop when the required reviews are green" makes a change
  contract-surface when it touches `core/protocols.py` or `core/types.py` "**or
  when it is the ADR deciding that surface**", and by the bullet above this ADR
  decides no surface; `scripts/ship.sh` gates the architecture lens on those two
  files changing and would accept adversarial alone. The set is taken anyway,
  because this admits a counterparty into the tool layer and because it names the
  module a later ADR will designate. Reviewed while `Proposed` and ratified only
  after (`CONTRIBUTING.md` → "Finishing an ADR PR").
- **Filed as #1096, lane F.** Refs #66. It **takes up** ADR-0098 §12's "Tool and
  MCP results" deferral, whose trigger fires here, and **discharges nothing** of
  ADR-0017 §3, of ADR-0016 §7's remaining deferrals, or of #74.
- **A stacked addition under ADR-0082 §1; no record is owed on any earlier ADR
  and none is written.** §11 names the clauses and applies the test to each.

## Context

### What leg 12 asks for, and the two ratified rules it meets

`docs/roadmap.md` item 12 is *"Actuators, in bulk. MCP-shaped tool breadth,
behind the decisions it forces"*, and its exit test is *"the assistant completes
a task that changes something in the world, and the user was asked exactly once,
at the moment it mattered."* Design stance 2 has been sequencing the egress
decision here since the roadmap's reorientation: *"Tools that act on the world
arrive later and in bulk (MCP-shaped), behind the contract decisions they
force."*

Two ratified rules meet at that breadth, and they pull in opposite directions.

**ADR-0016 §1 makes every safety-relevant property declared, not inferred**, with
no default on any of them, and it says why in terms that read as though they were
written for this ADR: *"The alternative — deriving risk from the integration's
identity, or from whether the tool's name starts with `send_` — is the
hard-coding this ADR exists to remove, and it fails silently for every tool
nobody thought about."* Its consequence is stated as a rule: *"a tool that does
not declare its reach does not load."*

**Every tool leg 12 adds is a tool nobody in this repository wrote.** Its risk,
its reversibility, its off-device disclosure and its cost are facts about a
program on the other side of a pipe. The only party positioned to state them is
the party that wants them to be low, which is precisely the counterparty. That is
the whole difficulty, and everything in §1 below follows from refusing to resolve
it in the comfortable direction.

### What an MCP server offers, read from the specification rather than remembered

Read against the Model Context Protocol specification, version `2025-06-18`, on
2026-08-13.

- **Discovery.** A client sends `tools/list` and receives tool objects with
  `name`, an optional `title`, a `description`, an `inputSchema`, an optional
  `outputSchema`, and optional `annotations` — "optional properties describing
  tool behavior".
- **The specification does not ask anyone to believe the annotations.** Its own
  warning, verbatim: *"For trust & safety and security, clients **MUST**
  consider tool annotations to be untrusted unless they come from trusted
  servers."* That is ADR-0016 §1's rule arrived at independently by the protocol's
  own authors, and it is the strongest single piece of evidence that §1 below is
  not this repository being precious.
- **Invocation.** `tools/call` with a `name` and an `arguments` object; the result
  carries a `content` array whose items may be `text`, `image`, `audio`,
  `resource_link` or an embedded `resource` — the last two carrying URIs and file
  text — plus an optional `structuredContent` object and an `isError` flag.
- **Transports.** Two are standard: **stdio**, where "the client launches the MCP
  server as a subprocess" and speaks newline-delimited JSON-RPC over its `stdin`
  and `stdout`; and **Streamable HTTP**, an ordinary HTTP endpoint. "Clients
  **SHOULD** support stdio whenever possible." Custom transports are permitted.
- **Two features run the other way, and both are opt-in.** A server may send
  `sampling/createMessage` to ask the *client* to run a model generation, and
  `elicitation/create` to ask the client to *put a question to the user*. Each is
  reachable only if the client declares the matching capability during
  initialization — "Clients that support sampling **MUST** declare the `sampling`
  capability", and the same sentence for `elicitation`.
- **A tool list is not stable.** A server declaring `listChanged` emits
  `notifications/tools/list_changed` when its tool set changes.

### The state of `tools/` and the seam, read rather than remembered

At `origin/main` when this was written, `src/ai_assistant/tools/` holds four
modules — `__init__.py`, `builtin.py`, `invocation.py`, `registry.py` — and not
one of them imports a network client or a subprocess API. `build_default_registry`
in `tools/builtin.py` returns the populated `InMemoryToolRegistry`, the one object
implementing both `ToolRegistry` and `ToolInvoker` (ADR-0029 §1, ADR-0048 §3), and
the two tools it binds are read-only, local, and declare an empty `discloses`
(ADR-0048 §2).

So **`tools/` transmits nothing today**, exactly as ADR-0017 §2 records, and the
seam it approves is still unnamed: issue #66 has been open since architecture
review of PR #64, asking for a name "precise enough for an import-linter contract
to pin the module". `pyproject.toml`'s contract set forbids provider SDKs outside
`models/` and confines `keyring` and `icalendar` to one package each; it says
nothing about network clients under `tools/`.

Three things that were open when the tool layer was designed have since closed,
and it is worth being exact about which:

- **Ranking** is ADR-0144's, so several capable candidates no longer stall a step.
- **Parameter-schema enforcement** is ADR-0145's, which fixes one dialect and
  refuses every other, and rules that an adapter "may not substitute an empty
  `parameters_schema` for one it cannot express".
- **The credential seam** is ADR-0125's: `Secrets` and `SecretStore` exist in
  `core/protocols.py`, and §8 there gives `tools/` the `Secrets` face "at the tool
  that needs one, by injection, for `INTEGRATION`-scoped reads". What has **not**
  closed is #74 — whether reading a credential is itself a permission subject —
  which ADR-0125 §9 leaves open and which is an ADR-0017 §3 condition.

### What already binds, and is not relitigated here

- **ADR-0017 §1**, as replaced by ADR-0124 §1: user data may leave the device only
  from `models/`, from a designated seam inside `tools/`, or across the hub's
  remote transport to an enrolled device. ADR-0124 §1 adds, in a marked clause,
  that "no lane may cite this ADR toward designating that seam".
- **ADR-0017 §3's fourteen conditions**, none discharged, and ADR-0017 §2's rule
  that designation takes a *later* ADR naming the seam, attesting each condition
  and recording the transition.
- **ADR-0098 §1**, whose class already names the subject: *"A source's fields, a
  message body, a feed entry, **a tool or MCP result**, a provider's error text,
  and a third party's speech captured by a spoke are all external content."* Its
  §3 rules that "No actuator is selected, parameterised, or confirmed by external
  content", and its §12 defers "Tool and MCP results" with the trigger "**Fires
  with the first tool that returns text**, which the roadmap places behind MCP".
- **ADR-0029 §1's biconditional** — an id is invocable if and only if it is
  registered — and §6's rule that no credential value crosses the invocation seam.
- **ADR-0016 §5**: one definition advertises one capability; an id is bound for the
  life of the process and a conflicting re-registration is refused; and §6: the
  registry is rebuilt each run and holds configuration, not personal data.
- **ADR-0144 §2's ordering**, which prefers the least severe capable declaration,
  and #1102, which records that this makes under-declaration pay twice.

### What this ADR is not allowed to settle

- **It may not designate the egress seam.** ADR-0017 §2 reserves that to a later
  ADR that attests each §3 condition. Naming the module is this ADR's job by that
  same section's words; attesting is not.
- **It may not narrow ADR-0017 §3, ADR-0021 §6 or ADR-0098 §3.** In particular it
  may not answer ADR-0098 §3's last clause — whether a standing authorisation may
  cover an action a model selected while reading external content — which that
  ADR reserves to the lane that designates an actuation seam, and which this lane
  is not.
- **It may not change `ToolDefinition`.** Every field it constrains is ADR-0016
  §1's and ADR-0018's, and a change to any of them is a `core` decision with its
  own ADR (golden rule 5).
- **It may not decide #74.** Whether reading a credential is a permission subject
  is ADR-0125 §9's open question, and §12 below scopes credential-bearing servers
  out rather than ruling around it.

## Decision

We will treat an MCP server as a **describer of tools and never as a declarer of
them**: the server supplies a name, a schema and a wire endpoint, and this
repository supplies every fact a safety decision is made on. Marked under
ADR-0089: every obligation this ADR imposes is a marked clause, and unmarked text
supplies none.

### 1. A description is not a declaration: no value a server sends reaches a safety field

> **Normative.** Every field of a `ToolDefinition` built for a tool an MCP server
> offers is taken from a **local declaration** — text in this repository or in the
> deployment's own configuration, authored by the operator — and no field is taken
> from, derived from, defaulted from or adjusted by anything the server sent. This
> covers `id`, `capability`, `description`, `risk_level`, `reversibility`,
> `side_effecting`, `reads`, `writes`, `discloses`, `cost`, `idempotency`,
> `idempotency_window` and `latency`. The single exception is `parameters_schema`,
> which §5 governs.

> **Normative.** A tool for which no local declaration resolves is **not
> registered**, whatever the server said about it. There is no partial admission:
> a declaration missing any field ADR-0016 §1 requires does not produce a
> definition, and a definition that does not construct produces no registration.

> **Normative.** An MCP `annotations` object — `readOnlyHint`,
> `destructiveHint`, `idempotentHint`, `openWorldHint`, or any member a later
> protocol version adds — is read by nothing in this system. It may not set a
> field, raise or lower one, warn about one, or be recorded as a reason for one.
> The same holds for a server's `title`, for any experimental or vendor field, and
> for a `description` a server sends.

**This is ADR-0016 §1's argument with the counterparty made explicit, and the
protocol's own authors reached the same place.** ADR-0016 §1 refuses to derive
risk "from the integration's identity, or from whether the tool's name starts with
`send_`", because such a derivation "fails silently for every tool nobody thought
about". Deriving it from the tool's own self-description is worse than either: it
does not merely fail silently, it hands the ceiling to the party with the motive to
lower it. The specification says so itself — clients "**MUST** consider tool
annotations to be untrusted unless they come from trusted servers" — and this ADR
declines to operate the escape hatch in that sentence, because "trusted server" is
a judgement nothing in this system records, and a server trusted on Monday is a
package that updates on Tuesday.

**`description` is a safety field here, and that is the clause a reader will want
argued.** ADR-0016 §1 states its two audiences: "the model, which is told what the
tool does, and the user, who is shown what they are approving". Both are the
attack. The user-facing half is live today — ADR-0144 §5 records that a `CONFIRM`
shows the user a `Confirmation` carrying "`tool_id`, `tool_description`,
`parameters` and `reason`" — so a server-authored description is third-party prose
rendered inside the assistant's own approval frame, which is exactly the phishing
case ADR-0098 §7 exists for: *"Escalating to the user is not a mitigation if the
escalation is where the attacker's sentence is read as ours."* The model-facing
half is not live (no tool description reaches a prompt today; the planner names
capabilities and is kept blind to the tool set, ADR-0048's known caveat and #296)
and it is the one that would be worse. A tool description in front of a model is
text whose entire function is to make the model select and parameterise that tool —
so carrying a server's description there would be external content selecting and
parameterising an actuator, which ADR-0098 §3 forbids in a marked clause. Local
authorship is therefore not caution; on the model-facing half it is compelled.

**What the server's own description is still good for.** It is the material the
operator reads while writing the declaration, and it may be shown to them at that
moment. What it may not do is survive into the definition. A declaration is a
human act performed with the server's claims in view and against them, which is the
same posture ADR-0145 §5 takes for a schema in the wrong dialect: translation is
permitted as "a visible, reviewable act producing a definition that says what it
means".

**The accepted cost is that breadth is bounded by authorship, and this ADR does not
pretend otherwise.** "In bulk" now means bulk *reach* — many servers, many
operations available — and not bulk *trust*: every tool costs a line naming it and a
set of values. §2 makes the values inheritable so the marginal cost of the second
tool on a server is small; nothing makes it zero, and nothing should.

> **Normative.** A declaration may state its values **per server**, in which case
> every tool admitted from that server takes them, or **per tool**, which states
> anything different in either direction. Where both resolve for one tool, the
> per-tool values are the definition's and the server-level ones supply nothing.

**Server-level values are honest because ADR-0016 §3 already made the tuples a
ceiling** — "the *maximum possible* reach, not the reach of any particular call" —
so one declaration covering a server's whole surface is a statement about the
worst of them, which is the direction that section says a bound must err in. The
cost is the one ADR-0016 §5 named: a ceiling stated once makes a mild operation as
gated as a severe one, and "how a permission system trains its user to approve
everything" is the failure at the end of that road. Narrowing is what per-tool
authorship buys, and stating the trade is better than hiding it inside a default.

### 2. Admission is an enumeration this side holds, and a server cannot extend it

> **Normative.** A declaration enumerates, by exact name, the tools admitted from
> a server. A tool the enumeration does not name is not registered, whatever it
> claims about itself and whatever values a server-level declaration would have
> supplied. There is no wildcard, no prefix match and no "admit everything this
> server offers".

> **Normative.** A name in the enumeration that no discovered tool matches is not
> an error and admits nothing. A discovered tool whose name matches no entry is
> dropped, and the drop is reported to the operator rather than passed over in
> silence.

**The enumeration is what stops a server growing an actuator overnight.** Without
it, a server-level declaration is a standing grant over a set the counterparty
controls: publish `delete_everything` on Tuesday, and it loads on Wednesday under
values stated on Monday about a different set of operations. With it, values are
inheritable and *membership* is not — which puts the cheap half on the server's
side of the line and the deciding half on ours. ADR-0093 §7's *"configuration is
not consent"*, as ADR-0097 §8 enforces it for source grants and ADR-0144 §4 for the
preference sequence, is the same shape: a value stated about a class is not
permission for a member nobody named.

**Reporting the drop matters more than it looks.** A tool silently missing is
indistinguishable from a server that is down, from a rename, and from an operator's
typo — and the second of those is how a declaration quietly stops covering the tool
it was written for. This is the one place where saying nothing costs an operator
their only chance to notice.

### 3. The seam is one named module, and the MCP client is not it

> **Normative.** The `tools/` egress seam ADR-0017 §2 anticipates is
> `ai_assistant.tools.egress` — one module, not a package, holding outbound
> transport and nothing else.

> **Normative.** No module under `ai_assistant.tools` other than that one opens a
> network connection or launches a subprocess, by any route: a client library, an
> HTTP or socket API, a standard-library module, or a wrapper around any of them.
> This binds an author and a reviewer; it is not a claim about what a check can
> see.

> **Normative.** An `import-linter` contract in `pyproject.toml` forbids, to every
> module under `ai_assistant.tools` except the seam, an **enumerated** set of
> modules: at minimum `socket`, `ssl`, `http`, `urllib`, `subprocess`,
> `asyncio.subprocess`, and every transport-bearing third-party package this
> repository depends on. The lane that adds any further transport-bearing
> dependency adds it to that enumeration in the same change. This is ADR-0125 §8's
> form for `keyring` and the readers' contract's for `icalendar`, applied to a set
> rather than to one name.

> **Normative.** MCP protocol handling — the JSON-RPC message shapes, discovery,
> the mapping from a declaration to a `ToolDefinition`, and the mapping from a
> result to a `ToolResult` — lives outside that module and holds no transport of
> its own. It receives a connected channel from the seam and never constructs one.

> **Normative.** Naming the seam is not designating it. This ADR designates
> nothing, attests no condition of ADR-0017 §3, and authorises **no byte** to
> leave this device from `tools/`. All fourteen of §3's conditions stand exactly as
> written and undischarged, and no lane may cite this ADR toward any of them. The
> seam stays **approved and undesignated** until every condition holds in code and
> a later ADR ratifies that it does, which is ADR-0017 §2's requirement and is
> untouched here.

**Naming was assigned to this ADR by name, and it is ripe.** ADR-0017 §2: "The
seam is a **named module inside** `tools/`, not the package — `tools/` also owns
definitions and the registry, and neither has any business holding a network
client. Naming it is the integration ADR's job, precise enough for an
import-linter contract to pin the module (issue #66)." This is the integration
ADR, the module it names is one an import contract can pin, and #66 has waited
since PR #64 for a lane with an integration in view.

**The second clause is the substance, and it is not tidiness.** The obvious shape
is that the MCP client *is* the seam, since MCP is the integration and the client
is what talks to it. That shape fails on ADR-0017 §2's own reasoning one level
down: a module holding both the transport and the protocol is a module where the
extent of the egress boundary is "wherever the MCP code goes", and MCP code will
grow — a second transport, a session layer, a reconnect policy, a result mapper.
The property #66 asks for is that a contract can pin the boundary; a boundary that
grows with a protocol implementation is one the contract stops describing. So the
transport is one module and the protocol is a consumer of it, which is ADR-0017
§8's injected-capability shape applied at one boundary rather than ratified across
`core` — §8 defers the general form and this ADR does not reopen it.

**It also constrains the dependency choice without making it.** A client library
that bundles its own transport cannot satisfy the second clause without being
imported into the seam, at which point the seam holds a protocol implementation
again. §12 leaves the library choice to the implementing lane under ADR-0003's
ordinary rule and states the constraint the choice has to meet, because the choice
is one to make with code in hand and the constraint is one that is expensive to
discover afterwards.

**The prohibition and the contract are two clauses because they reach different
distances, and collapsing them would overstate the second.** ADR-0017 §4 already
says why: "an import contract is a net, not a proof. It matches module names, so
it cannot see a subsystem reaching the network through `urllib`, a raw socket, a
library added after the contract was written, or an internal wrapper." A clause
claiming a contract pins a *universal* prohibition would be claiming exactly the
proof §4 denies — a bound stated over something the check cannot obtain, which is
the defect ADR-0098 §3 records itself making twice before a reviewer caught it. So
the rule is stated universally, as a rule, and the contract is stated over an
enumeration, which is what a contract can actually hold. The enumeration names
`urllib` and the raw socket module explicitly, so ADR-0017 §4's first two examples
are inside the net rather than outside it; what stays outside is a dependency
nobody added to the list, and the extension clause is what makes adding one a
change that either updates the list or fails review. What the contract reliably
catches is the realistic accident — `httpx` appearing in the MCP protocol module —
and nothing here upgrades it past that.

Naming the seam therefore does not make the boundary enforceable; it makes it
*describable*, which is the condition ADR-0017 §3 actually states and the first
thing a designating ADR needs to attest against.

### 4. The local/remote line, and why neither transport is connected before a ratified authorisation

> **Normative.** Handing a tool's arguments to an MCP server over a **stdio**
> transport — a subprocess this system launched on the hub's own machine, speaking
> over its `stdin` and `stdout` — is not off-device transmission **by this
> system** and does not engage ADR-0017 §1. The clause is about this system's own
> act and about nothing else.

> **Normative.** No lane, ADR or surface may state or imply that the clause above
> establishes what an admitted server does with what it is handed. This system
> obtains no fact about whether a subprocess transmits, and neither the transport
> distinction nor any declaration is evidence that one does not.

> **Normative.** Reaching an MCP server over a **network** transport — Streamable
> HTTP, the deprecated HTTP+SSE form, or any custom transport that opens a socket
> — is off-device transmission. It is not `models/`, it is not the hub's remote
> transport to an enrolled device, and the `tools/` seam is undesignated, so it
> matches none of ADR-0124 §1's three boundaries and is a bug under it.

> **Normative.** **No MCP server is connected to, over any transport, and no
> MCP-served tool is registered, until a ratified ADR authorises it.** For a
> network transport that ADR is the designating ADR ADR-0017 §2 requires. For a
> stdio transport it is that ADR or another, and what makes one owed there is the
> second clause above rather than ADR-0017 §1: a program this repository did not
> write becomes a recipient of user data, and no ratified decision authorises
> that.

> **Normative.** The ADR that authorises a stdio server settles what makes that
> acceptable, explicitly and in its own text: what bounds the recipient, what an
> operator's claim about it is worth, and what is recorded. It may not infer an
> answer from ADR-0017 §1's device scope, from ADR-0084 §1's loopback reading, or
> from roadmap leg 6's local-file reading, none of which was decided about a
> counterparty holding a socket. **This adds no condition to ADR-0017 §3's list and
> relaxes none of them**; those fourteen stand exactly as written and govern the
> network transport as before.

> **Normative.** Whenever a call is eventually made, what crosses to an MCP server
> is the tool name the enumeration states and the `ActionRequest.parameters`
> mapping, and nothing else. No memory record, no context facet, no conversation
> history, no other tool's result, no plan, no belief and no credential is placed
> in an outbound MCP message, and no such value may be added to one by
> configuration, by a declaration, or by a server asking for it.

**A subprocess is not a device, and it is not this system either, and the second
half is why the fourth clause exists.** ADR-0017 §1's rule is scoped to the
*device*, and the corpus has read it that way twice: ADR-0084 §1 for the hub's own
loopback socket, and roadmap leg 6 for a reader opening a local file — "A file the
hub opens on its own disk leaves no device". A stdio server is on the same side of
that line, and the first clause says so. What neither precedent covers is that this
counterparty has a network stack: a file cannot phone home and the CLI spoke is our
own code, while a stdio MCP server is a program this repository did not write,
running with the hub's privileges, free to open a socket we never see. So the
transport question and the trust question are two questions, the corpus has ratified
an answer to only the first, and the fourth clause refuses to let the first stand in
for the second.

**An earlier draft of this section admitted a stdio server on a declared empty
`discloses`, and it was wrong in a way worth recording.** The reasoning was that
`discloses` is already the declared fact about off-device transmission (ADR-0016
§3), so an operator declaring a local server transmits nothing is making exactly the
claim the seam would otherwise guess at. Both review lenses found the same defect
independently and both were right: a declaration is a claim about a program, it
constrains that program not at all, and the draft's own prose conceded the
subprocess "is free to open a socket we never see" two paragraphs below the clause
admitting it. **A declaration is the right instrument for a fact about *our*
intent and the wrong one for a fact about *their* behaviour**, and ADR-0016 §1's
whole argument — that a declaration is what makes an author state something, not
what makes it true — reads that way once the author and the subject are different
parties. What the draft had built was ADR-0098 §6's forbidden shape with the
detector replaced by a promise: a bound bought from a component whose failure
nobody would notice.

**Neither review's stated direction was available, and the fourth clause is the
third answer.** Adversarial asked for "an enforceable no-network isolation
boundary"; that is platform-specific, costly per server, and — specified from a
prose ADR with no mechanism behind it — the bound-with-nothing-behind-it defect
ADR-0098 §3 records itself making twice. Architecture asked, in the alternative,
that stdio tools not be admitted until contained; that is this clause, reached
without pretending to specify the containment. **#1112** carries the isolation
question with its cost and its platform spread, as an input to the authorising ADR
rather than as a condition this ADR invents.

**Refusing the network transport and refusing the stdio one are refusals for
different reasons, and collapsing them would lose the useful half.** The network
case is settled by a ratified rule: ADR-0124 §1's enumeration is exhaustive, it
names three boundaries, and a remote MCP server is none of them, so no policy could
pass a gate and building the connection would be building the thing ADR-0017 §2 says
does not exist. The stdio case is *unsettled* — ADR-0017 §3's fourteen conditions
have no subject on a subprocess, since recipient authorisation, destination
canonicalisation, multi-recipient sets and transport pinning are all about a
destination chosen at call time from arguments, and ADR-0124 §12 declined to apply
the same list to the hop for exactly that reason. So the fifth clause states what
the authorising ADR owes rather than pointing at a list that does not reach it. This
is ADR-0098 §3's form, deliberately: bind the later lane, name the question, add
nothing to §3.

**What the authorising ADR is likely to admit first, offered as an input and not as
a rule.** Empty `discloses` does not mean read-only: ADR-0016 §3 makes a tool that
writes side-effecting whatever it discloses, and reversibility is independent of
disclosure (§2 there). So a local server that writes files or drives a local
application yields tools that are `side_effecting`, plausibly `IRREVERSIBLE`, and
declare no disclosure — the live case ADR-0021 §5's floors have never had, and the
narrowest thing an authorising ADR could turn on first. Whether the declaration is
worth anything there is exactly what #1112 is about, and this ADR does not decide it.

**What this costs, said without softening.** Leg 12's exit test — *the assistant
completes a task that changes something in the world, and the user was asked exactly
once* — is not reachable on this ADR alone. It needs the authorising ADR, which the
roadmap already sequences into this leg alongside "the deferred egress cluster", and
which #1096 already queues last. An earlier draft claimed the exit was reachable
without it; that claim was true only under the admission this section has now
withdrawn, and it is corrected rather than left standing.

### 5. Schemas are carried or refused, never translated

> **Normative.** A discovered `inputSchema` is carried into
> `ToolDefinition.parameters_schema` **verbatim**, or the tool is not registered.
> No component rewrites, repairs, upgrades, downgrades, prunes, or otherwise
> translates a schema a server sent.

> **Normative.** Where a carried schema is refused at `ToolDefinition`
> construction under ADR-0145 §5 or §6 — a declared dialect other than draft
> 2020-12, an invalid schema, a root `type` excluding `object`, a reference
> breaching §6's model, a reference cycle, or a nesting depth past the bound —
> the tool is not registered and the refusal is reported to the operator with the
> reason the construction gave.

> **Normative.** A server that sends **no** `inputSchema` for a tool yields the
> field's empty default, which ADR-0145 §9 rules is a declaration of no
> constraint. That is a faithful carry and not the substitution §9 forbids. The
> declaration records that the server described no schema, so admitting such a
> tool is a decision the operator took rather than an absence nobody saw.

> **Normative.** A declaration may supply a **locally authored**
> `parameters_schema` in place of the discovered one. Where it does, the local
> schema is the definition's and the discovered one is not consulted at all.

**ADR-0145 §5 offers an adapter two routes and this ADR takes one of them.** Its
words: an adapter meeting a schema in another dialect "may translate it and
declare the translation — a visible, reviewable act producing a definition that
says what it means — or it may refuse the tool (§9)." **Automatic translation is
not a visible, reviewable act.** It is code rewriting a document a hostile party
authored, in the one place where a widening is undetectable: a draft-07 array
bound expressed as `additionalItems` translated wrongly does not fail, it simply
permits more, which is the fail-open direction ADR-0145 §5 refuses at the top of
its argument. So the automatic path is refusal, and the translating path is the
fourth clause — a human writing a schema, which is a declaration like every other
field under §1 and is reviewed the same way.

**A locally authored schema can be wrong, and the direction of the error is
stated.** If it is narrower than what the server accepts, calls the server would
have taken are stopped at the selection stage — a stall, which ADR-0145's
Consequences already name as the safe direction. If it is wider, the extra
arguments reach the server and come back as the tool's own refusal, which
ADR-0145 §3 keeps `ToolFailureKind.INVALID_REQUEST` meaningful for: "arguments a
tool refuses for reasons its schema does not express". Nothing detects the second
case, and nothing here claims to.

**Two smaller notes the implementing lane would otherwise have to derive.** MCP's
tool schemas are described by the specification as "JSON Schema" without pinning a
dialect on the tools page, and schemas in the wild overwhelmingly omit `$schema` —
which ADR-0145 §5 reads as 2020-12, so the ordinary case carries cleanly. And
`outputSchema` is not carried anywhere: `ToolDefinition` declares no output schema,
ADR-0029 §3 makes `output` a `FrozenJsonValue`, and ADR-0145 §14 scopes validating
a result against a declared schema out as an ADR-0016 field change. §12 keeps it
there.

### 6. A result is external content, and the declaration is what marks it

> **Normative.** Every part of a `ToolResult` produced by an MCP-served tool is
> **external content** under ADR-0098 §1 — the text of every content item, an
> embedded resource's text, a `resource_link`'s URI and name, the
> `structuredContent` object in whole and in every leaf, and any message text
> derived from an `isError` result. Nothing about the result narrows the class:
> not its shape, not its declared type, not its passing a schema.

> **Normative.** The fact that marks it is the **declaration set** — configuration
> this system holds, which says of each registered id whether that tool is
> MCP-served — and it is reached by asking that set. No component decides whether a
> result is external by inspecting the result, and **no component derives it by
> parsing a `ToolDefinition.id`**: an id stays an opaque `Identifier` carrying no
> meaning a consumer reads, which is ADR-0016 §5's property and is not weakened
> here.

> **Normative.** Where such a result reaches a model call, ADR-0098 §2 governs it
> in full — presented as third-party data, with the attribution not forgeable from
> inside the span — and ADR-0098 §3's positional clause governs it: never in a
> `Role.SYSTEM` message and never inside the region a `Role.USER` message presents
> as the user's own words.

> **Normative.** No part of such a result selects a tool, supplies or alters a
> parameter, satisfies a confirmation, or contributes to any permission outcome.
> This is ADR-0098 §3's actuator clause read on the results this ADR admits, and
> it holds for a result that has already been recorded as much as for one in
> flight.

> **Normative.** A `resource_link` or an embedded resource in a result is content,
> never an instruction to fetch. Nothing in this system resolves a URI a tool
> result carries, subscribes to it, opens it, or turns it into an ingestion.

> **Normative.** The declaration set answers for every id the registry holds, so
> within a process the origin of any result in hand is always establishable. It
> does **not** answer for a result retained past the process that produced it: a
> consumer holding such a result and unable to establish its origin treats it as
> **external**, and never as this system's own words or the user's.

> **Normative.** `StepExecution.output` is therefore a projection that carries
> content which may be external and carries no origin for it, and is **defective in
> that respect** under ADR-0098 §7's third clause. That obligation falls on the ADR
> that next revises `StepExecution`, never on a surface reading one, and is never
> licence to present the retained span as the assistant's words. This ADR names the
> instance and adds no `core` surface to close it.

**ADR-0098 §12's trigger fires here, and this ADR is what it fires into.** That
bullet — "**Tool and MCP results.** External content by §1, inheriting §2 and §3.
**Fires with the first tool that returns text**, which the roadmap places behind
MCP" — is a deferral being taken up rather than a decision being changed, and §11
below records that no sentence of ADR-0098 becomes false or over-wide by it. The
class was already ADR-0098 §1's, in a marked clause naming "a tool or MCP result"
by name; what was open was what marks such a span, and the second clause above is
the answer, in the form ADR-0098 §2's third clause requires — derived from data the
system holds, never from the text.

**The marker is the declaration rather than a field, and that is why this ADR adds
no `core` surface.** ADR-0098 §12's first deferral is a marker on a record or a
proposal, and §5 there argues it cannot be specified without a producer in hand
under ADR-0073 §4's standing test. Nothing here changes that: a `ToolResult` is
not a memory record, it is not ruled on by `MemoryPolicy`, and the question of
whether an *ingested* record can carry its externality to the ruling point is
untouched. What this ADR needs is much smaller — a caller holding a result knows
which tool produced it, and the declaration set says which tools are MCP-served —
and it is answerable from configuration the composition root already holds.

**The last clause is the one an implementing lane will be tempted to break.** A
`resource_link` looks like an affordance: the server is telling us where more
context lives, and following it seems like completing the tool call. It is a
counterparty naming a location and a program fetching it, which is content
selecting an action (ADR-0098 §3) and, for any non-`file:` URI, an egress from a
module that is not the seam. Refusing it costs a feature nothing in this system
currently wants, and it costs it now rather than after a lane has built on it.

**The cross-restart hole is real, was found by review, and is closed in the only
direction available here.** `StepExecution` persists `bound_tool` and `output` and
plan state is durable (ADR-0014 §5), while ADR-0016 §6 rebuilds the registry from
configuration and persists nothing. So an operator who removes a server from the
declaration set and restarts leaves behind a durable span of external content whose
origin the second clause cannot recover and which §7 forbids recovering from the
id — an earlier draft nonetheless asserted that the fourth clause "holds for a
result that has already been recorded as much as for one in flight", which was a
bound stated over something this system could not obtain, the defect ADR-0098 §5
names and §3 records itself making twice.

The fix that would actually close it is a durable origin beside the output, which
is `core/types.py` surface and therefore an ADR of its own (golden rule 5) — the
same wall ADR-0098 §5 and §12 hit for their own marker, and for the same stated
reason. What is available here is the fail-closed default, and it is available
precisely because it needs nothing new: **unknown origin means external.** That
over-marks a builtin's output whose declaration is in code and cannot vanish, at no
cost, and it under-marks nothing. It is ADR-0098 §1's own posture — a source is
enrolled in the protection by default and "must be argued out of it, not into it" —
read onto a projection instead of onto a `MemorySource`. The durable marker is
**#1114**, filed as the fourth instance of the lossy-projection class ADR-0098 §12
already tracks rather than as a fifth coincidence.

**What is not promised, in ADR-0098 §3's own words.** "A model that reads a
well-marked, correctly positioned external span may still follow an instruction
inside it." Everything above makes this system's own conduct correct and makes the
model less likely to be fooled; the containment that holds whether or not it was
fooled is the permission gate on every invocation (ADR-0016 §3), the declared
ceiling the gate rules against, and the fourth clause's refusal to let a result
reach that ruling as an input.

### 7. Ids are composed on this side; capabilities are not namespaced, and #1100's MCP path closes

> **Normative.** An MCP-served tool's `ToolDefinition.id` is composed from a
> **server alias** and the **tool name the enumeration states**, both of which the
> declaration authors. No value a server sends contributes to an id. The
> composition is injective: the alias excludes the separator, so no pair of alias
> and name composes to the same id as a different pair.

> **Normative.** The composed form carries a fixed leading segment, so that the
> ids of MCP-served tools and the ids this repository composes by any other route
> are **disjoint sets**. A server cannot therefore claim the id of a builtin, and a
> builtin cannot shadow a server's tool.

> **Normative.** That segment exists for disjointness and for nothing else. It is
> **not** a provenance marker: no component outside the composition that builds it
> may read, match, strip or otherwise interpret any part of an id, and nothing
> — a prompt assembler, a policy, a surface, a trace — may establish that a tool is
> MCP-served by looking at its id. §6's declaration set is the only route to that
> fact.

> **Normative.** `capability` is **not** namespaced. It is declared under §1 from
> this repository's own open vocabulary (ADR-0016 §5), and two MCP-served tools
> may share a capability with each other and with a builtin exactly as two
> builtins may.

**Ids are namespaced because a collision there is not a preference question, it is
a substitution.** ADR-0016 §5 binds an id to a definition for the life of the
process and refuses a conflicting re-registration with `ToolRegistrationError`, and
ADR-0029 §1's biconditional makes the registered set and the invocable set one set.
If a server could choose its own id, a server offering a tool named `recall_memory`
would either take the builtin's id or fail the whole registry build depending on
registration order — an availability bug in the good case and, if the ordering ever
went the other way, the substitution ADR-0016 §5 spends its length preventing.
Composing the id from two locally-authored parts closes it by construction rather
than by a check, which is the direction this corpus prefers.

**The leading segment is disjointness and not a namespace anyone reads, and an
earlier draft got that wrong in a way architecture review caught.** That draft
described the segment as "marking the tool as MCP-served" and §6 pointed at
`ToolDefinition.id` as where the marker was "reachable" from. Taken together those
two sentences reserved a semantic namespace inside a shared `core` value and made
a cross-subsystem consumer depend on its spelling — which is a change to what a
`core` type *means* even though it adds no field, and which contradicts ADR-0016
§5's own reason for ordering by id: it is "the one that carries no accidental
meaning". The finding was right and the repair is to separate the two jobs. The
segment does the job an id can do — keep two id spaces from colliding, inside the
composition that mints them — and the provenance fact lives where every other
declared fact in this ADR lives, in the declaration set, which is configuration the
composition root holds rather than a string other subsystems parse. **The
consequence is that this ADR still adds no `core` surface**: `ToolDefinition` gains
no field, no validator, no constraint and no meaning any consumer reads.

**Capabilities are not namespaced, and this is the clause that engages #1100
rather than sidestepping it.** That issue records that ADR-0144 made a
capability-name collision resolve *silently* — before it, two integrations using
one flat string for genuinely different operations stalled the step; after it, the
ordering picks the less severe of two declarations that mean different things.
Namespacing capabilities would be the reflexive fix and it is the wrong one twice
over. It would break the vocabulary a planner names: a plan naming `send_email`
matches neither `mcp:gmail:send_email` nor `mcp:fastmail:send_email`, and the step
becomes `NO_CAPABLE_TOOL` — the #296 alignment problem made structural rather than
merely likely. And it would namespace away the case ADR-0144 exists for: two
tools that genuinely both send email *should* share a capability, and choosing
between them is the rule ADR-0144 ratified, working.

**What actually closes #1100's MCP-shaped path is §1, not a namespace.** #1100's
collision needs two integrations to *independently choose* one flat string for
different operations. Under §1 a server chooses nothing: the capability an
MCP-served tool advertises is written by the declaration's author, from this
repository's vocabulary, with the other declarations in view. So the collision
cannot arrive from the direction MCP breadth was expected to bring it from — the
residue is one author declaring two unlike operations under one name, which is a
mistake no namespace prevents and which the author is positioned to see. **#1100
is narrowed and not closed**, ADR-0016 §7's namespacing deferral stands exactly as
written, and this ADR adds nothing to it: a namespacing convention remains
additive, and the trigger it waits on — collisions becoming real — now has one
fewer way to fire.

### 8. Discovery happens once, and the registry stays configuration

> **Normative.** Discovery runs while the registry is being built, once per
> process. The registry is populated with the tools admitted at that moment and
> gains none afterwards.

> **Normative.** A `notifications/tools/list_changed` notification changes
> nothing about the registry. A tool a server adds mid-process is not registered;
> a tool it withdraws stays registered and stays invocable, because ADR-0016 §5
> binds an id for the life of the process and this ADR does not weaken that.

> **Normative.** A server that re-advertises an admitted tool with a different
> schema between one process and the next is **not detected**, and nothing in
> this ADR claims otherwise. What such a change cannot reach is any safety field,
> because §1 takes every one of them from the declaration; its whole effect is on
> ADR-0145's eligibility filter, which then runs against the new schema.

> **Normative.** A declaration carries no Tier 0 value and no personal data. It
> names servers, aliases, tool names, a launch command and the declared field
> values, all of which are Tier 2 operational configuration under ADR-0004 §1, so
> ADR-0016 §6's finding that the registry carries no export or delete obligation
> holds unchanged.

**One discovery per process is what keeps ADR-0016 §6 true rather than nearly
true.** That section's argument — the registry "is populated at startup from
whatever is registered and rebuilt each run", so "there is nothing to export and
nothing that outlives a process to delete" — depends on the population being a
startup act. A registry that grew during a run on a counterparty's notification
would be a registry whose contents at any moment depend on what a server did, which
is neither configuration nor auditable, and it would put ADR-0016 §5's spent-id
rule under continuous pressure from a party with an interest in rebinding.

**Withdrawal is the asymmetric half and it is deliberate.** A server that stops
offering a tool leaves this system holding an id that still resolves; invoking it
then fails at the transport and comes back as an ordinary `ToolResult` — a
`ToolFailureKind.UNAVAILABLE`, which ADR-0029 §3 makes retryable — rather than as a
registry mutation. That is the same direction ADR-0016 §5 chose when it made
deregistration spend an id: a security control accepts friction rather than letting
a name change meaning.

**The undetected schema change is stated because the alternative would need
pinning.** A declaration could carry a digest of the schema it was written against
and refuse the tool when the server's changed. That is a real design with a real
cost — every upstream improvement becomes a load failure an operator must clear —
and its value depends on how often a server's schemas move, which nobody here
knows. §12 scopes it out with an issue rather than guessing.

### 9. Sampling and elicitation are refused, not deferred

> **Normative.** This system declares neither the `sampling` nor the
> `elicitation` client capability to any MCP server, and implements no handler for
> `sampling/createMessage` or `elicitation/create`. A server sending either
> receives the protocol's error for an unsupported method, and no model call and
> no user question results.

> **Normative.** The same holds for any later protocol feature by which a server
> asks this system to run a model generation, to put a question to a user, or to
> read a location this system holds. Such a feature is refused until an ADR rules
> on it; it is not enabled by a client library's default, by a configuration value,
> or by a declaration.

**Both are opt-in by the protocol's own construction, so refusing costs one line
and buys the two things this corpus is most careful about.** The specification is
explicit that "Clients that support sampling **MUST** declare the `sampling`
capability" and says the same for elicitation, so the refusal is the absence of a
declaration rather than a filter that could be got wrong.

**Sampling is a counterparty composing a prompt and choosing a model.** ADR-0098
§3's actuator clause forbids external content selecting or parameterising an
action; a `sampling/createMessage` request is a server supplying a `systemPrompt`,
a message list and model preferences, which is external content composing a model
call outright. There is no marking scheme that helps, because the span is not
embedded in our prompt — it *is* the prompt.

**Elicitation is a counterparty putting a question to the user in our voice.**
ADR-0144 §5 rules in a marked clause that "The selection stage puts no question to
the user", on the ground that leg 12's exit test is a claim about being asked
*once*; a server free to raise its own dialogue mid-call breaks that from a
direction ADR-0144 never had to consider. And ADR-0098 §7 is the sharper
objection: the escalation surface is where attacker-authored text is read least
examined, and `elicitation/create` is a channel whose entire purpose is to render a
server's own sentence there and collect a typed answer. The specification's own
mitigation — "Servers **MUST NOT** use elicitation to request sensitive
information" — is an obligation on the party we are defending against.

**Refused rather than deferred, because the cost of refusing is nothing today and
the cost of deferring is a default.** Nothing in this system needs either feature,
and every client library that implements them makes enabling them a matter of
passing a handler. A deferral would be read by an implementing lane as permission
to wire one up behind a setting. Revisiting is a later ADR's, with a use case in
hand.

### 10. What the implementing lanes owe

None of this is built here (ADR-0015 §5). What is owed is the evidence for the
claims above that a signature does not show. **Nothing in this list is owed by a
lane before the authorising ADR of §4 lands**, because no server is connected
until it does; what the list fixes is what that lane inherits rather than
rediscovers.

- **§1 as refusals, not as omissions**: a discovered tool with a plausible
  `annotations` object claiming `readOnlyHint` and a declaration stating
  `IRREVERSIBLE` produces a definition that is `IRREVERSIBLE`; a discovered tool
  with no declaration produces **no registration**, asserted against the registry
  rather than against a log line; a declaration missing one required field
  registers nothing, and the definition never constructs.
- **The description substitution, pinned as the thing that leaks if untested**: a
  server whose `description` contains a distinctive string is admitted under a
  local declaration, and that string appears in no `ToolDefinition`, in no
  rendered confirmation, and in no prompt. ADR-0029 §10 and ADR-0145 §13 required
  the same shape of test for the same reason — nothing downstream catches it.
- **§2's enumeration, in both directions**: a tool the enumeration names and the
  server does not offer admits nothing without erroring; a tool the server offers
  and the enumeration does not name is dropped **and reported**.
- **§3's contract, exercised rather than asserted**: `uv run lint-imports` fails
  when a module under `ai_assistant.tools` other than the named seam imports one of
  the enumerated modules, asserted for a standard-library entry (`socket` or
  `urllib`) as well as for a third-party one, so the enumeration is shown to hold
  where ADR-0017 §4's own examples sit. Two things a test does not cover and which
  the lane states rather than implies: that the seam holds no MCP protocol code,
  and that a transport a later dependency brings is inside the enumeration — both
  are review properties, and pretending otherwise is the overstatement §3 splits
  its clauses to avoid.
- **§4's minimisation clause, as what an outbound message contains**: a
  `tools/call` built for a tool whose declaration reads Tier 1 carries the tool
  name and the request's `parameters` and nothing else, asserted against the
  serialised message rather than against a call site. The fixture puts a
  distinctive string into a memory record, the conversation and a context facet,
  and none of the three appears in any byte written to the server.
- **§4's refusal as a construction-time fact**: before the authorising ADR, a
  declaration naming *any* transport yields no connection attempt at all —
  asserted as no socket opened and no subprocess spawned, rather than as a request
  that failed — and the built registry holds no MCP-served tool. Asserting the
  registry matters as much as asserting the absence of I/O, since a test that only
  checks an exception proves nothing about what the composition root ended up
  holding.
- **§5's carry and refusals** (ADR-0145 §13's list applies to the carried
  document): a schema declaring draft-07 refuses the tool; a schema with no
  `$schema` is carried and read as 2020-12; a server sending no `inputSchema`
  yields the empty default and the tool loads; a locally authored schema replaces
  the discovered one and the discovered one is not consulted.
- **§6 as a marking test in ADR-0098 §9's own form**: a result whose text contains
  the prompt assembler's own container syntax leaves the attribution of every span
  unchanged, and a result carrying a `resource_link` produces no fetch of any
  kind. A test asserting only that a label is present does not satisfy this.
- **§6's fail-closed default, asserted on the path that produces it**: a
  `StepExecution` carrying an output is read back after the declaration naming its
  `bound_tool` has been removed, and the span is treated as external — not as the
  assistant's words, and not dropped. Building the fixture by deleting the
  declaration rather than by stubbing a lookup is what makes it the cross-restart
  case rather than a mocked one.
- **§7's injectivity and its opacity**: an alias containing the separator is
  refused where the declaration is read; a server offering a tool named exactly as
  a builtin's id produces two distinct ids and both remain invocable. And the
  opacity is a review property with one testable half — the externality marking of
  §6 is shown to work against a definition whose id was minted with **no** leading
  segment at all, which is what proves the marking reads the declaration set and
  not the string.
- **§9 read off the initialization handshake**: the capabilities this system
  declares contain neither `sampling` nor `elicitation`, asserted against the
  actual `initialize` payload rather than against the absence of a handler.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text, and it is made here.
Its test is whether a reader holding only the earlier ADR "would now act
differently, or read one of its clauses more widely than it now holds". Where the
answer is no, "no record is owed against it at all, on `Status` or in a note", and
the change "is recorded in the ADR that makes it, **and nowhere else**". ADR-0146
§10 is the worked precedent for this section's form.

**ADR-0016 §1 — no record owed.** Its rule is that every safety field is required
and declared. §1 above adds *where the declaration must come from* for one class of
tool. No sentence of §1 becomes false, and a reader holding only ADR-0016 builds a
declaration-taking constructor and is correct, merely silent about the MCP case.

**ADR-0016 §5 and §7 — no record owed.** §5's flat capability strings and §7's
namespacing deferral are untouched: §7 above namespaces `id`, which §5 already
requires to be unique and which §7's deferral does not speak to, and it declines to
namespace `capability`. §5's stated reason for ordering by `id` — that it is "the
one that carries no accidental meaning" — is *preserved* rather than merely
survived: §7's opacity clause forbids any consumer reading meaning out of an id, so
the property §5 relies on holds after this ADR exactly as before it. A reader holding only ADR-0016 reads "names are flat
strings" and acts identically; nothing here makes the deferral narrower, and §7
above says in terms that it is narrowed in its *cause* and not in its text.

**ADR-0016 §6 — no record owed.** The registry stays in-memory, rebuilt each run,
carrying configuration. §8 above holds it to that rather than relaxing it.

**ADR-0017 §2 and §3 — no record owed, and this is the one that needs the
argument.** §2 says the seam is a named module and that naming it is "the
integration ADR's job". This ADR does that job, which is §2 working rather than §2
being amended — the same shape ADR-0146 §10 found for §3's classification
condition: "The condition is not made false or over-wide by being answered." §3's
fourteen conditions stand undischarged and §3 above says so in a marked clause; a
lane holding only ADR-0017 still finds fourteen conditions and still needs a later
ADR to attest them. Note what would have owed a record and is deliberately not
done: attesting condition one — "a named seam and an import-linter contract pinning
it" — is a statement about code, reserved by §2 to the designating ADR, and this
ADR makes no such statement.

**§4's fifth clause is the entry a reviewer should press on, and the test still
comes out no.** It obliges the ADR that authorises a stdio server to settle what
bounds a recipient this repository did not write. That is an obligation on a
*later ADR*, stated in this ADR's text, which is exactly the form ADR-0098 §3 used
for its own actuator clause — "The clause above binds the later ADR that designates
an actuation or egress seam. It adds no condition to ADR-0017 §3's list and relaxes
none of them; those fourteen stand exactly as written." The same two sentences hold
here and the clause says so in its own words. Nothing in ADR-0017 §3 becomes false
or over-wide: the list is fourteen entries before and after, each governs what it
governed, and a lane reading ADR-0017 alone still finds fourteen and still needs the
attesting ADR. What §4 adds is a *different* obligation about a case §3's entries
have no subject for — which under ADR-0082 §1 is a stacked addition and is recorded
here rather than on ADR-0017.

**ADR-0014 §5 and ADR-0098 §7 — no record owed for naming `StepExecution.output`
defective.** ADR-0098 §7's third clause defines the class and assigns the debt "to
the ADR that defines or next revises that projection"; naming a fourth member is
that clause working, and §12 there already tracks three. No sentence of ADR-0014
becomes false: it never claimed `output` carried an origin, and this ADR neither
adds a field to `StepExecution` nor changes what one means. The debt is recorded in
#1114 and against a future revision, which is where §7's own words put it.

**ADR-0124 §1 — no record owed.** Its enumeration is read here and applied, not
widened: §4 above concludes that a remote MCP server matches none of its three
boundaries, which is the enumeration doing exactly what an exhaustive enumeration
is for. Its marked clause that no lane may cite it toward designating the `tools/`
seam is honoured; this ADR cites it toward a refusal.

**ADR-0029 §1, §3 and §6 — no record owed.** The biconditional, the result type
and the credential rule are relied on as they stand. §7 above is what keeps the
biconditional true across a namespace, and §12 keeps credential-bearing servers
out rather than putting a credential anywhere near the invocation seam.

**ADR-0098 §1, §3 and §12 — no record owed.** §1 already names "a tool or MCP
result" as external content in a marked clause, so §6 above adds the marker rather
than the class. §3's actuator clause is applied, and its last clause — whether a
standing authorisation covers a content-triggered action — is left unanswered on
purpose, because ADR-0098 reserves it to "the lane that designates an actuation
seam" and this lane is not that. §12's tool bullet is a deferral whose trigger
fires; taking a deferral up is "that deferral working as designed, not a
supersession" (ADR-0029 §9), and no sentence of §12 becomes false — the bullet
remains a true record of what was deferred and when it would fire.

> **Normative.** Nothing in this ADR answers ADR-0098 §3's last clause. Whether a
> standing authorisation may cover an action a model selected while reading
> external content is still open, still the designating lane's to answer
> explicitly, and no lane may read this ADR's silence, or any clause of §4 or §6,
> as an answer in either direction.

**ADR-0144 and ADR-0145 — no record owed.** Both are consumed as written.
ADR-0144's ordering runs over MCP-served candidates like any other, and §7 above
declines to add an ordering key or read one. ADR-0145 §5 and §6 do the schema
refusing; §5 above chooses between the two routes ADR-0145 §5 already offers rather
than adding a third.

**ADR-0125 §8 — no record owed.** Its clause gives `tools/` the `Secrets` face "at
the tool that needs one". §12 below scopes out passing a credential to a *server*,
which is a different act on a different party, and states that as a scope-out
rather than as a reading of §8.

**No ADR is amended and none is superseded**, so no `Status` line and no appended
note is written anywhere in `docs/adr/` but this file. Under ADR-0082 §1 a reviewer
"may not demand a record, or its removal, on book-keeping grounds alone", and may
require one by "naming the sentence of the earlier ADR that does, or does not,
become false or over-wide" — which is the form a disagreement with this section
takes.

### 12. Explicitly out of scope

Scoping something out is a decision, so each carries its reason (ADR-0029 §7's
form).

- **Designating the `tools/` egress seam.** ADR-0017 §2 requires a later ADR to
  name the module, attest each §3 condition and record the transition. This ADR
  supplies the name and nothing else; every condition — recipient authorisation
  (#68), transport pinning (#83), gated credential access (#74), the payload
  manifest (#57), canonicalisation, multi-recipient sets, attempt identifiers and
  the rest — is inherited unabridged and undischarged. Saying it loudly is the
  point: an integration ADR reads like permission to connect, and it is not.
- **Connecting to any MCP server at all**, per §4, until a ratified ADR
  authorises it. Neither half is deferred for convenience. For a network transport
  ADR-0124 §1's enumeration is exhaustive and a remote server is outside it, so the
  refusal is a consequence of a ratified rule. For stdio the refusal is a
  consequence of the *absence* of one: a program this repository did not write
  becomes a recipient of user data, and §4's fifth clause states what the
  authorising ADR owes rather than pretending ADR-0017 §3's list reaches it.
- **Bounding what an admitted stdio server does, so that "it transmits nothing" is
  a property rather than a claim** — **#1112**, and the input §4's authorising ADR
  most needs. §4 bounds the payload; what it cannot do is bound the program. The close is a network
  namespace, a sandbox profile or a container, which is platform-specific across
  the three deployments this hub is expected to run on, carries a real cost per
  server (an isolated server cannot reach a socket or a config file it
  legitimately needs), and — worst — is the kind of partial mechanism ADR-0098 §6
  forbids buying a bound from if it is reported as more than it is. Specifying one
  from a docs-only ADR would be stating a bound with no mechanism behind it, which
  is the defect ADR-0098 §3 records itself making twice.
- **Passing a credential to an MCP server.** ADR-0125 §8 gives `tools/` a
  `Secrets` face "at the tool that needs one, by injection", and an MCP server is
  not a tool inside `tools/` — it is a separate program, and putting a Tier 0
  value into its environment or its arguments is a disclosure of a credential out
  of this process to a party this repository did not write. Whether reading a
  credential is even a permission subject is #74, an undischarged ADR-0017 §3
  condition that ADR-0125 §9 leaves open by name. So: no declaration carries a
  secret value and this system supplies no credential to a server. A server that
  obtains its own credential from its own configuration is outside this system's
  reach; §4 keeps every such server behind the authorising ADR in any case, and
  #74's answer is one of the things that ADR will need.
- **A durable origin for a retained tool result** — **#1114**. §6 states the
  fail-closed default and names `StepExecution.output` under ADR-0098 §7's third
  clause; the close is a field beside the output or a durable declaration history,
  both `core` decisions with their own ADR and both wanting a producer in hand
  (ADR-0073 §4), which is exactly why ADR-0098 §5 and §12 declined the analogous
  marker.
- **MCP resources and prompts.** The protocol's other two server primitives are
  not tools. A resource is an ingestion source, and this repository already has a
  seam for one — `Reader` (ADR-0093 as renamed by ADR-0095 §1) — with a grant
  model (ADR-0097, ADR-0133) that a tool has no part of. Routing a resource through
  `tools/` would put an ingestion outside the grant surface leg 11 built, which is
  a worse outcome than not having resources. The roadmap's leg 6 note already
  ruled MCP-shaped clients welcome "as sensors only"; a resource is where that
  sentence would be cashed, in a readers lane, not here.
- **Sampling and elicitation** are not deferred at all — §9 refuses them. Listed
  here so a reader looking for them in this list finds the refusal rather than
  concluding they were overlooked.
- **Pinning a tool's schema against change between runs** (§8). It needs a digest
  in the declaration and a policy for what an operator does when a server improves
  its schema, and its value depends on how often that happens, which nobody here
  knows. Filed rather than guessed.
- **Live re-discovery** (§8), for the same reason ADR-0016 §6 keeps the registry a
  startup artifact.
- **Choosing an MCP client library.** ADR-0003's ordinary rule applies — a runtime
  dependency is justified in the change that adds it — and this ADR states the
  constraint rather than the choice: whatever is adopted must satisfy §3's split,
  so a library that welds transport to protocol handling either fits inside the
  named seam or is not adopted. The choice is one to make with code in hand, and it
  narrows once §4 leaves stdio as the only transport in reach. Unlike ADR-0145's
  `jsonschema`, no ratified deferral names this dependency as its blocker, so
  ADR-0003's ordinary route is the right one.
- **Validating a result against a server's `outputSchema`** (§5). `ToolDefinition`
  declares no output schema and ADR-0145 §14 already scopes adding one out as an
  ADR-0016 field change.
- **Per-user tool enablement**, **persistence**, **transacted cost** and
  **per-call data reach** (#57) — ADR-0016 §7's still-open deferrals, unaffected
  and still deferred.
- **Publishing the registry's vocabulary to the planner** (#60, #296). Breadth
  makes the alignment gap wider, and closing it is a planning-contract decision
  ADR-0016 §5 left open. Nothing here depends on it: a plan naming a capability
  nothing implements stays the detectable outcome ADR-0014 reserved
  `SkipReason.NO_CAPABLE_TOOL` for.
- **A user-facing surface for the declaration set** — which servers are connected,
  which tools they offer, what was dropped. ADR-0133 §7 holds the equivalent
  question for sources, and ADR-0094 §10 already expects that decision and #441's
  release ladder to be one decision; a tool-side surface is adjacent enough that
  guessing its shape here would prejudge it.

## Consequences

**What becomes easier.** Leg 12's implementation lanes inherit an answer to the
question each would otherwise have invented separately: where a safety field comes
from, what a schema does, what a result is, and what an id looks like. The
designating ADR inherits a *named* module rather than a phrase, which is what #66
has been asking for since PR #64, and it inherits §4's fifth clause telling it what
the stdio case additionally owes — a question it would otherwise have met with the
code written.

**What becomes harder, and it is the headline cost.** Adding a tool now costs a
human writing a declaration. "In bulk" means many servers reachable, not many tools
trusted, and an operator who expected to point at a server and get its forty tools
gets none of them until they name them. Server-level values make the marginal cost
small and never zero. This is ADR-0016 §1's trade — "Declaring a tool is now
wordy" — paid a second time, by an operator instead of by an integration author,
and it is the thing most likely to be argued about.

**A server can no longer set its own risk ceiling, which is the point.** #1102
records that ADR-0144's ordering makes under-declaration pay twice, and names
declaration *provenance* as the direction a fix would come from "once tools arrive
from third parties … rather than from this repository, where an author
under-declaring their own tool is a bug and not an incentive". §1 is that fix for
the MCP-shaped case, and it is a strong one: the provenance of every MCP-served
declaration is local, so the incentive #1102 describes never attaches. What #1102
still records truly is the residue — a *local* author who under-declares, whether
out of optimism about a server or to make a prompt go away, is unchecked by
anything. What checks it is review of a declaration, which is a weaker instrument
than a validator and a stronger one than an incentive pointed the wrong way.

**Two servers offering the same capability now compete, and that is ADR-0144
working.** Because capabilities are declared on this side (§7), a deployment can
put an MCP-served tool and a builtin under one capability deliberately, and
ADR-0144's ordering picks the less severe. That is the first case that rule has
had which is not hypothetical.

**#1100 loses its expected trigger.** Leg 12 was the leg at which capability
collisions were expected to become real; under §1 and §7 they cannot arrive from a
server, so the deferral ADR-0016 §7 holds waits on an author's mistake instead of
on breadth. The issue stays open and its urgency drops, which is worth saying
plainly because the opposite was expected.

**Nothing connects, and leg 12's exit test moves behind the authorising ADR.**
This is the largest thing the decision costs and the largest thing it changed
between drafts. An earlier §4 admitted a stdio server on a declared empty
`discloses`; both review lenses found that a declaration is a claim about a
program and constrains it not at all, and the admission was withdrawn. So this ADR
fixes the shape and connects nothing, the exit test needs the ADR §4's fourth
clause requires, and #1096 already queues that lane last. **The question is
sharpened rather than merely postponed**: ADR-0017 §3's fourteen conditions have no
subject on a subprocess, so §4's fifth clause states what the authorising ADR must
settle instead — what bounds a recipient this repository did not write — with #1112
carrying the isolation option and its cost.

**The permission machinery's first live case is now that ADR's to deliver.** An
`IRREVERSIBLE`, `side_effecting`, non-disclosing tool from a local server is still
the narrowest thing that exercises ADR-0021 §5's floors and ADR-0029 §5's retry
conjunction against a real effect, and §4 offers it as the input that lane is most
likely to turn on first. It is offered and not ruled, which is the difference this
revision is about.

**A tool result is now a named class of untrusted input.** ADR-0098's posture
acquires its third producer, after `readers/` and the provider's error text, and
the prompt-assembly lane (#672) inherits one more span type to escape. Nothing
downstream detects a result that steers; what bounds it is that no result reaches a
permission ruling as an input (§6) and that every invocation is gated whatever the
model concluded (ADR-0016 §3).

**Revisit when** the authorising ADR of §4 lands and the first server is actually
connected — which is the moment every rule here first meets a real one, and in
particular the moment to ask whether §1's per-tool authorship was priced right; when
a schema change between runs is observed in practice (§8's pinning question); if a
server worth having turns out to need sampling or elicitation (§9); or if the
declaration burden of §1 measurably stops tools being added, which is the failure
mode this ADR most plausibly has.

### The strongest case against this decision

It makes the *breadth* leg the leg with the most authorship per tool, and it does
so on a threat model nobody here has met. Every MCP server an operator would
plausibly connect is one they chose, from a source they trust, doing something they
want — and this ADR treats each as a hostile counterparty, charging a hand-written
declaration per tool to defend against a compromise that has not happened. The
protocol's own answer is milder: read the annotations, trust servers you trust. A
system that made that judgement once, per server, at connection time, would have the
same security posture in every case that actually occurs and a fraction of the
friction — and the friction is not neutral, because a rule that makes adding a tool
expensive is a rule that results in fewer tools, which is the whole of what leg 12
was for.

Three things answer it, and none of them says the concern is wrong.

**The judgement being charged for is one nothing records.** "A server you trust"
has to live somewhere: as a flag, it is a field a compromise flips; as an
operator's memory, it is not a control at all. What §1 charges for is that
judgement written down in the vocabulary a permission decision is actually made in
— which is the same thing, priced honestly, and reviewable afterwards.

**The cheap version fails in exactly the direction that is unrecoverable.** An
under-declared tool is gated more lightly *and*, since ADR-0144, wins selection
against an honest peer — #1102's compounding, arriving through a channel the
counterparty controls. ADR-0016 §1's whole argument is that this class of error is
silent and that a construction error is better; nothing about the error becoming
somebody else's makes it louder.

**There is a second, opposite case against, and it arrived from review rather
than from the author.** Having withdrawn the stdio admission, this ADR now decides
a great deal and connects nothing: no server, no tool, no call, until an ADR that
does not exist. That is a contract ratified without implementation contact, which
`CONTRIBUTING.md` warns about by name, and it means every rule here is judged on
argument rather than on use. The answer is that the alternative was worse in a way
that is not recoverable — an unisolated third-party program admitted as a recipient
of user data, on an operator's word, before any ratified decision authorised it —
and that the shape is what leg 12's remaining lanes are blocked on either way:
#1096 sequences the egress mechanism lanes as "shaped by what ADR-0147 rules". The
honest residual is that the first server will find something here wrong, and §4's
authorising ADR is the near-term lane positioned to say so.

**The cost is bounded by a mechanism this ADR chose for that purpose, and it is
measurable.** Server-level values plus a per-tool name is one line per tool after
the first, and §12 leaves the surface that would make that pleasant to a lane with
a user in view. What would change the verdict is evidence from use: if operators
routinely admit whole servers at a ceiling and never narrow, then §1's per-tool
authorship is buying nothing over a per-server declaration and the enumeration in
§2 is the only part earning its keep. That is measurable once the first servers are
connected, and it is the revisit named above.
