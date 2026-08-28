# 209. A floor base move costs a review round only where the moved text and the PR name each other

- Status: Proposed
- Date: 2026-08-28
- **Partially supersedes:** ADR-0027 §3's floor clause — the enumeration whose
  every entry "invalidates the artifact outright". The scope, written verbatim on
  ADR-0027's `Status` line by this change (§9): **§3's floor clause, narrowed — its
  `docs/adr/**` and contract-surface entries invalidate an artifact only where one
  of four tests binds; §3's refusal of path disjointness, its rename-aware
  both-endpoints reading, its `docs/review/**`, `CLAUDE.md`, `CONTRIBUTING.md` and
  `scripts/codex-review.sh` entries, and §§1–2 and 4–7 all stand.** §9 applies
  ADR-0070 §1's test and shows why this is a supersession and not an amendment.
- **Records made in this change.** ADR-0027's `Status` line and an appended dated
  note, in the form §9 states. ADR-0082 §1's test is applied there to ADR-0020,
  ADR-0165 and ADR-0138 as well; none of the three is owed a record, and §9 says
  why for each.
- **Follow-on:** the implementation is a separate lane, briefed after this merges
  (§10). Nothing implements against this ADR before then (ADR-0015 §5).
- Resolves: #1743 (a `docs/adr/**` or contract-surface base move costs a round
  whether or not the moved text bears on the PR).
- Refs: #124 (the objection §3 answers), #1709 and #1730 (the batch the evidence
  is drawn from), #751 (why one implementation serves `ship` and its drill).

## Context

### What ADR-0027 §3 decided, and what it refused

ADR-0027 §1 splits the question a review artifact answers in two: **coverage** —
did a reviewer read *this* content — and **currency** — does the change still
hold on today's base. It keeps the artifact for coverage and leaves currency to
the gate. §2 anchors coverage on the reviewed patch identity, so a base move
outside the reviewed hunks no longer invalidates.

§3 then refuses **path disjointness** as the acceptance test, on #124's own
ground: a change can break on a base it shares no path with — a conftest, a
renamed helper, a dependency bump, a new lint rule — and no enumeration of "the
files that could matter" survives a repository's growth. The answer §3 gives is
not that the objection is wrong; it is that every example it names is
**gate-detectable**, so the objection lands on currency, which the gate holds,
and ADR-0027 reuses only coverage.

What survives the objection is the floor. §3's own words for it: "One class of
base move is invisible to the gate *and* changes what a reviewer would say." Its
members are `src/ai_assistant/core/protocols.py` and
`src/ai_assistant/core/types.py`; `docs/review/**`, `CLAUDE.md`,
`CONTRIBUTING.md` and `scripts/codex-review.sh`; and `docs/adr/**`. A base move
touching any of them invalidates the artifact outright — "no patch-identity
relief, no drift disclosure".

§3 gives its own reason for the `docs/adr/**` entry, and it is a **relation**,
not a path: "An ADR merged under an open lane can contradict the one that lane is
writing; the gate cannot see it and no path test will catch it." The contract
entry reads the same way: a base move landing new contract surface "changes what
the architecture lens would say about a diff that consumes it or now should".
§3 records that the `docs/adr/**` cost is "the clause that costs the most, and
it is taken deliberately", and ADR-0027's Consequences repeat it: the floor
"keeps the tax on any base move that merges an ADR, which on a repo running
parallel docs lanes is a large share of them".

### The floor is a proxy, and what it proxies is now checkable

The floor is a **path** test standing in for a **relation** — "the moved text
bears on this PR". It was chosen as a path test because in July 2026 the relation
was not mechanically checkable. Since then `scripts/brief_check.py` has been
written and is in daily use: it extracts, from an arbitrary body of prose, every
`ADR-NNNN` reference (`_ADR_RE`), every backticked token, and a classification of
each token into a repository path, a bare filename or a Python symbol
(`classify`, `_PATH_PREFIXES`). ADR-0088 §1 requires a code citation to name the
symbol, and ADR-0088 §5 forbids a line number, so the corpus this extraction runs
over is written in exactly the form the extraction reads.

That is the whole of what has changed since ADR-0027. The relation §3's own
justification is about can now be computed from the two bodies of text, in the
same run that already computes the base move's file set.

### The evidence: one day's floor crossings

Nine floor crossings were recorded across batch #1709 on 2026-08-28 (#1743):

| PR | crossed | PR names / is named by the moved text? | what the paid round found |
| --- | --- | --- | --- |
| #1711 ADR-0205 | ADR-0204 merge | yes (cites by number) | 1 major — about its own Protocol text, not the base |
| #1712 ADR-0206 | ADR-0204 + ADR-0205 merges | yes | real: an ADR-0135 keep-alive contradiction (rounds 5–7) |
| #1722 harness | ADR-0206 merge | **no** | one pre-existing finding restated five times (#1730); nothing about the base |
| #1724 ADR-0204 impl | ADR-0206 merge | **no** | the same `minor` as its round 1 (#1728) |
| #1725 planner | ADR-0206 merge | **no** | `APPROVE`, no findings |
| #1713 ADR-0207 | `core/types.py` | arguable — the ADR names `SpokenTurn`; the move changed `Provenance` | a real §5 contradiction, introduced by the lane's own prior edit, not by the base |
| #1713, #1739, #1738 | `docs/review/**` + `scripts/codex-review.sh` | the reviewer itself changed — always | owed under any rule |

Three of the nine were paid by a PR that neither names nor is named by the moved
text, and none of the three found anything the base move caused. Every round that
found a real defect was on a PR that *did* name the moved text, or crossed the
review contracts.

**The sample is one day, one repository, nine crossings.** It is enough to show
the tax is real and that its cheapest third is recoverable; it is not enough to
establish a rate, and the Revisit condition in Consequences is written against
that limit rather than around it.

### What this ADR does not reopen

§3's refusal of path disjointness stands, and this ADR does not argue with it. A
base move that breaks a change it shares no path with is still a currency
question the gate answers, and the branch is still rebased and fully re-gated
before it merges. Nothing here touches branch protection's `strict` setting,
which is §1's currency half — one CI run, on the combination.

## Decision

### 1. The standing review contracts stay absolute

> **Normative.** A base move whose file set carries, at either endpoint of any
> entry, a path under `docs/review/`, or `CLAUDE.md`, `CONTRIBUTING.md` or
> `scripts/codex-review.sh`, invalidates every artifact of every persona
> outright. No test in §§3–4 relieves it, and nothing in this ADR bears on it.

This half of §3 is not narrowed and is not a proxy for anything. A review run
against a superseded rubric is not a review under this repository's standard
whatever its verdict says, and `scripts/codex-review.sh` is on the same footing
because it assembles the prompt — the ADR-0020 §1 preamble, the persona rubric,
the verdict contract. Those paths move rarely; §3's judgement that when they move
"everything open should be re-reviewed" is correct and is retained verbatim.

The evidence table agrees: the one crossing class that was owed under any rule is
this one.

### 2. The other half binds only where the two texts name each other

> **Normative.** A base move whose floor entries are all under `docs/adr/` or are
> `src/ai_assistant/core/protocols.py` or `src/ai_assistant/core/types.py`
> invalidates an artifact only where at least one test in §3 or §4 binds. Where
> none binds, ADR-0027 §3's floor is **cleared** for ADR-0027 §2(b)'s purposes,
> and the base move is published under ADR-0027 §4 exactly as a non-floor move is.

> **Normative.** Every test in §§3–4 is persona-agnostic. A test that binds costs
> the round for every persona the change requires, and a floor cleared under §2 is
> cleared for every persona.

The second clause retains ADR-0027 §3's withdrawal of a per-persona floor and
does not reopen it. §3 withdrew that split because "the authority hierarchy in
`guide.md` is not scoped by persona" and because "adversarial would probably not
have noticed" is a prediction about a reviewer rather than a property of the
content. Both objections stand against a per-persona split and neither reaches a
test computed from the two texts, which is a property of the content and predicts
nothing about a reviewer.

### 3. A moved ADR binds where either text names the other

> **Normative.** A moved `docs/adr/NNNN-*.md` binds where the PR's text contains
> the token `ADR-NNNN` for that file's number.

> **Normative.** A moved `docs/adr/NNNN-*.md` binds where the file's text, at
> either endpoint of the move, names a path the PR's diff touches or names a
> symbol occurring in an added or removed line of the PR's diff.

**The first test is the direction a lane already knows about.** A PR that cites a
moved ADR by number has declared that the ADR bears on it, and #1743's table
records that every round which found a real defect was on such a PR (#1711,
#1712) or crossed §1's contracts.

**The second test is the direction §3 worries about, made mechanical.** §3's
hazard is "an ADR merged under an open lane can contradict the one that lane is
writing" — a decision that governs the PR *whether or not the PR knew to cite
it*. A new decision that governs what this PR implements is written in ADR-0088's
citation form: it names the paths it governs and the symbols it constrains. So
the ADR naming the PR's own ground is the checkable form of "it can contradict
what that lane is writing", and it does not require the lane to have known.

**Both endpoints, because §3 already reads both.** §3 makes the base-move listing
rename-aware "and a floor path appearing as either endpoint — source or
destination — is a breach, as is its deletion", for the reason that a
`--name-only` listing reports only a rename's destination. The same reading
governs the extraction: an ADR renamed within `docs/adr/` is read at both of its
names, and one renamed *out* of the tree is read at the name it had. Nothing here
narrows that.

### 4. A moved contract file binds where new surface lands, or where the PR reaches the moved surface

> **Normative.** A base move that adds a `Protocol` class to
> `src/ai_assistant/core/protocols.py`, or that widens any `Protocol`'s
> **effective member surface** — the members it declares, a method, a property or
> an annotated attribute, together with those it inherits from its `Protocol`
> bases — binds unconditionally.

> **Normative.** That limb is decided by reading the file structurally at both
> endpoints of the move and comparing each `Protocol`'s effective member surface,
> never by matching the move's hunk lines against a pattern. An endpoint that
> cannot be parsed binds, and so does every other case in which this limb cannot
> be decided — §6's first clause governs it.

> **Normative.** A class in `src/ai_assistant/core/protocols.py` is a `Protocol`
> when one of its bases resolves to `typing.Protocol`, and a base resolves to
> `typing.Protocol` when the name it is written under is bound to it by that
> module's own imports: the bare name bound by `from typing import Protocol`, an
> alias bound by `from typing import Protocol as P`, or an attribute access on a
> name bound to the `typing` module by `import typing` or `import typing as t`.
> `typing_extensions` is read as `typing` wherever this clause names it. Identity
> is decided by that resolution and never by the base's spelling alone, and a
> base resolving neither to `typing.Protocol` nor to a class the same file
> declares binds under §6.

> **Normative.** Any other move touching `src/ai_assistant/core/protocols.py` or
> `src/ai_assistant/core/types.py` binds where the PR's diff touches a path under
> `src/ai_assistant/core/`, or where a name whose definition the move changed in
> either file occurs in the PR's text.

**The unconditional limb exists because §3's stated ground demands it.** §3 puts
the contract surface in the floor because a base move landing new contract
surface "changes what the architecture lens would say about a diff that consumes
it **or now should**". "Or now should" is a relation the PR's own text cannot
witness: a diff that ought to consume a Protocol landed an hour ago names nothing
about it, precisely because it has not been written to consume it yet. A
citation test cannot see that case, so the case is not given to a citation test.
New Protocol surface is rare — golden rule 5 and ADR-0015 §5 make each instance
its own PR behind its own merged ADR — so the limb costs little and closes the
one fail-open §3 argued for by name.

**Every new member, not only a new method, and the reason is the same one.** An
annotated attribute or a property added to an existing `Protocol` is a new
structural requirement on every implementation of it: a lane whose open PR
implements that Protocol outside `core/` now fails to satisfy it, and its diff
names nothing about the member because the member did not exist when the diff was
written. That is "or now should" exactly, so the limb reaches it. What the limb
does not reach is a member's *removal* or a change to an existing one, which the
second limb and §3's tests judge on their merits.

**The surface is the effective one, because this repository composes Protocols.**
`InvocationLedger(InvocationCompleter, Protocol)`,
`TraceStore(TraceSink, TraceRetention, Protocol)` and
`SecretStore(Secrets, Protocol)` each acquire their bases' members without
declaring them. A base move that adds a `Protocol` base to an existing `Protocol`
therefore adds every member of that base to what an implementation must satisfy,
while adding neither a class nor a member in the child's own body. Comparing
declared members alone would clear the floor on that move, and the open lane
implementing that Protocol outside `core/` would reuse a review taken before its
required interface expanded — the same fail-open the limb exists to close,
reached through inheritance instead of through a new `def`. So the comparison is
of the effective surface at each endpoint, and adding a base is a widening like
any other.

**Structurally, because the two spellings differ and only one of them is safe.**
ADR-0027 §2 fixed `git patch-id --verbatim` in the ADR rather than leaving it to
the implementation, for the reason that the safe and unsafe spellings looked
alike. The same holds here: a pattern over the move's hunk lines cannot tell a
member added to a `Protocol` from one added to a neighbouring dataclass, from a
line that merely moved, or from one inside a docstring, and it reads a hunk
rather than a class. Comparing the declared members of each `Protocol` at the two
endpoints answers the question that is actually asked, and an endpoint that
cannot be parsed binds rather than clears, on the same fail-closed footing as §6.

**And identity is resolved rather than spelled, because those spellings are not
interchangeable to a reader that matches an identifier.** The structural limb is
a claim about what the file *declares*, so an implementation of it must decide,
class by class, whether `Protocol` is among the bases — and keyed on the bare
identifier that decision is wrong on three spellings this repository already
writes elsewhere. `src/ai_assistant/wire/surface.py` does a bare `import typing`;
`src/ai_assistant/tools/egress.py` and `src/ai_assistant/tools/egress_binder.py`
each bind a protocol class under an alias (`DestinationProtocol as
SeamProtocol`); and `core/protocols.py`'s own module docstring names its
contracts in the qualified form while every base in the file is written bare. A
base move rewriting that file to `from typing import Protocol as P` and widening
`class Child(Base, P)` is a widening on which **both endpoints parse perfectly**,
so §4's parse-failure limb never fires and a bare-identifier reading clears the
floor for an open lane whose required interface just grew. Import resolution is
the reading that answers the question the limb actually asks, and it is the same
move §4 makes twice already: read the structure, not the token.

**Nothing in the file is spelled that way today, and the clause is worth its
lines anyway.** `core/protocols.py` declares 49 `Protocol` classes, and the only
bases across all of them are the bare `Protocol` and four classes the same file
declares (`InvocationCompleter`, `Secrets`, `TraceRetention`, `TraceSink`). So
this is a defect in the specification rather than a live fail-open, and it is
priced accordingly: the limb already binds unconditionally on a widening, and
this clause changes no outcome for any move the repository could make this week.
What it changes is what a future edit to that file costs — an edit written in a
spelling the project uses in three other modules would otherwise silently move
the limb from unconditional to occasional.

**The limb is scoped to `core/protocols.py` deliberately.** A field added to a
`core/types.py` model, or a new value class there, obliges no open PR to do
anything: the "now should consume" hazard is a *Protocol* hazard, and golden rule
5, ADR-0015 §5 and the architecture lens all attach to that surface. #1743's one
contract crossing is the case this scoping frees — the base move changed
`Provenance` while the PR's ADR named `SpokenTurn`, and the round it bought found
a defect the lane's own prior edit had introduced.

**The second limb reads a definition, not a mention.** What binds is a name whose
*definition* the move changed — a class, a `def`, or an enum member in the moved
hunks of those two files — not every identifier the hunks happen to contain. A
mention that is not a definition tells a PR nothing it could act on.

### 5. What the two texts are, exactly

> **Normative.** The **PR's diff** is `git diff <merge base>...<HEAD>` over the
> same range ADR-0027 §2's patch identity is computed on, re-anchored to `HEAD`'s
> parent where ADR-0165 §3 re-anchors that loop.

> **Normative.** The **PR's text** is the added and removed lines of the PR's
> diff, together with the PR description as GitHub holds it when the acceptance
> rule runs.

> **Normative.** The **PR's files** are the complete contents of every path the
> PR's diff touches, at each of that path's two endpoints **that exists**.

> **Normative.** A **moved file's text** is that file's whole content at each
> endpoint of the move **that exists**.

> **Normative.** An endpoint that does not exist is not a failure to read one. A
> file the PR adds has no base-side endpoint, a file it deletes no head-side one,
> and a rename has one of each under two names; each is read on the side it has,
> and §6's fail-closed rule reaches only an endpoint that exists and cannot be
> read.

> **Normative.** The extractions are `scripts/brief_check.py`'s, reused and not
> restated: `ADR-NNNN` by `_ADR_RE`, backticked tokens by `_BACKTICK_RE`, and
> their classification into a path, a bare filename or a symbol by `classify`.
> A `path` token names a path the PR's diff touches when it equals, or is a
> directory prefix of, either endpoint of an entry of that diff; a `file` token
> when it equals such an endpoint's basename; a `symbol` token when the whole
> token occurs as a word in an added or removed line of that diff, or — for a
> dotted token — when its **last** part occurs as a word in such a line **and**
> every other part occurs as a word in one of the PR's files, or as a component
> of a path that diff touches — a directory name, or a filename with its
> extension removed.

> **Normative.** The PR description is admitted to the PR's text so that it can
> add a binding, never so that it can remove one. Where a review artifact has
> been recorded for this PR, a lane that then removes from its description,
> before the acceptance rule next runs, a citation which would have bound a test
> against the base move being published owes that round — whatever the
> acceptance rule computes over the description the lane leaves behind. An edit
> made before any artifact was recorded is outside this clause, and so is one
> that removes a citation binding no test.

**Each input is its own clause, because each moves separately.** ADR-0089 §2 is
explicit that a passage stating two separable obligations is two clauses, and
these four are separable in the sharpest way available: the PR description is the
one input that is author-controlled and mutable, and a later decision to stop
reading it has to be able to move **the PR's text** without disturbing what **the
PR's files** or **a moved file's text** are. Under one mark it could not, because
a superseding ADR names a clause and gets all four.

**A dotted symbol is split, because a definition never carries its own
qualification.** ADR-0088 §1's citation form is `MemoryStore.ingest` — the class
and the member — and `classify` keeps that as a single token. A PR adding or
changing that member writes `async def ingest(...)`; no line of its diff carries
the dotted string, and the enclosing `class MemoryStore` may be unchanged and
therefore absent from the diff entirely. Matching the whole token clears the
floor on exactly the PR the moved ADR is about. Matching the last part alone is
the other error: a bare `ingest`, `close` or `read` would bind almost every diff
and the rule would buy nothing.

**So the two parts are asked different questions, and neither is asked of the
hunk window.** The *member* must be touched: its name occurs in a line the diff
adds or removes, which is what makes this a statement about the change rather
than about its neighbourhood. The *qualifier* need only be present: its name
occurs somewhere in one of the PR's files — the complete content, at either
endpoint, of a path the diff touches. A PR appending a method to `MemoryStore`
names `MemoryStore` in that file whether the class header sits three lines above
the hunk or three hundred, so nothing here turns on how much context `git diff`
was asked for. A PR adding an unrelated `ingest` to a file that never mentions
`MemoryStore` binds nothing.

**Absence and unreadability are different, and only one of them binds.** A PR
that adds a file has no base-side content for it, which is the ordinary shape of
adding a file rather than evidence that anything went wrong; reading it as a
failed read would charge a round on every PR that adds a file. So the rule reads
the sides a path has and no more. What §6 binds on is the other case — an
endpoint that exists and will not come back — where the input the test needs is
genuinely missing and clearing would be a guess.

**A qualifier may be a module rather than a class, so the path answers too.**
`classify` returns a symbol for `memory.store.SqliteStore` exactly as it does for
`MemoryStore.ingest`, and there the qualifier names where the symbol lives. A PR
adding `class SqliteStore` to `src/ai_assistant/memory/store.py` need not write
the words `memory` or `store` anywhere in that file: the module path is the
statement, and it is carried by the filename. So a qualifier part is satisfied by
a path component of a file the diff touches as well as by a word in one — the
same question asked of the other place the answer is written.

**Two rules were considered and are not what is decided.** Reading the
qualifier from the diff's *context lines* is the one this section carried for a
round, and it is wrong for the reason above: the context window is a rendering
option, and a member appended to a large class clears the floor because its class
header did not fit. Resolving each definition's enclosing scope from the complete
endpoint files with a Python parse is sound and more precise, and it is declined
for cost rather than correctness — it buys precision in the direction this ADR
already spends (§5 prices over-binding and forbids under-binding), it needs a
parse where a word search needs none, and a file it cannot parse would have to
bind anyway. Where the word rule and the scope rule differ, the word rule binds
more.

**The PR description is admitted because it can only cost rounds.** It is
author-controlled and mutable, which would be disqualifying for an input that
could *clear* the floor. This one cannot: every test is a reason to charge, so
adding text to the description can only add bindings, and removing text can only
lose bindings the diff may still supply. A lane that deletes a citation to a
governing ADR in order to avoid a round has written a PR whose description no
longer states its own grounds, which the review reads and the coordinator
verifies; that is a conduct failure this rule does not need to price.

**That conduct rule is marked, because otherwise it is not a rule.** The floor
test is computed once, when the acceptance rule runs, so a description edited
between the recorded review and `ship` is simply the description the test reads
— and a lane could edit out a citation that a base move has since made binding.
The clause above is the answer this ADR gives, and it is an obligation on the
lane rather than a computation: under ADR-0089 §3 the paragraph alone would have
obligated nothing at all.

**The window and the exceptions are inside the clause, because they have to be.**
ADR-0089 §3 requires a marked clause to state its own scope, and an unbounded
reading of this one would charge a lane for tidying a draft description months
before any review existed. So the clause opens only once an artifact has been
recorded and closes when the acceptance rule next runs, and it exempts both the
pre-artifact edit and the removal of a citation that bound nothing. What follows
is a lane's obligation and **not** a claim that the acceptance rule got the
answer wrong: the rule reads the description in front of it and is right to, the
removal is not observable to it, and §6 does not reach it because nothing failed
to be read. A PR can therefore be cleared by the rule and still owe the round
under this clause — which is the ordinary shape of a conduct rule, not a
contradiction, and it is why the obligation names the lane rather than `ship`. Binding the description *mechanically* to the recorded
artifact — snapshotting the retrieved body and refusing a cleared floor when it
has changed — is the stronger answer and is deliberately not taken here: it
would put a second input into every review artifact, which is a change to what
`scripts/codex-review.sh` records rather than to what the floor test decides. It
is filed as #1750 against the implementation.

**The extraction reads fenced blocks too.** `brief_check` strips them for its own
purpose — reporting a brief's broken citations — where a false positive is the
expensive direction. Here the expensive direction is the opposite: a missed
binding is a round not charged. So the text is read whole, and a quoted or
displayed citation binds like any other. Over-binding is the cost this ADR
accepts and prices; under-binding is the failure it must not have.

### 6. Fail closed, disclose either way, and one implementation

> **Normative.** A test that cannot be computed binds. An unreadable endpoint, an
> unparseable listing, a PR description that cannot be retrieved, and any error
> reaching the extraction each make the round owed.

> **Normative.** One implementation of §§1–5 serves `scripts/ship.sh`'s
> acceptance loop and its `--drill` mode alike, never two statements of one rule.

> **Normative.** ADR-0027 §4's disclosure is unchanged and applies to a cleared
> floor exactly as to any base move: the whole file set, never a bounded
> rendering, and a set that does not fit the publishing budget still makes path
> (b) unavailable. The record additionally names, for each floor path in the set,
> the test that bound it or that every test cleared it.

The single-implementation clause is ADR-0165 §6's principle applied to a second
rule, and #751 is why it is normative rather than advisory: a hand-built replica
of `ship`'s floor test returned "floor clear" for a base move that in fact
breached the floor, twice, because the replica and the rule had drifted apart.
This ADR adds a second, richer test to the same surface, so the same discipline
is owed on it before it is written rather than after.

The disclosure clause is what keeps §4's function intact. Under ADR-0027 the
published file set is the evidence a human weighs at merge, and §4 is explicit
that it is "not context for a decision, it *is* the decision". Narrowing what the
floor *charges for* does not narrow what is *shown*: the merge reviewer sees the
same whole set, plus the reason each floor path was cleared, which is strictly
more than they see today.

### 7. Why this is not the test §3 refused

Path disjointness asked: **does the PR touch the moved file?** This asks: **do
the moved text and the PR's text name each other?** They are different questions
and they fail differently.

§3's objection to path disjointness is that a change can break on a base it
shares no path with, and every example it gives — a conftest, a renamed helper, a
dependency bump, a lint rule — is a *behavioural* coupling with no textual trace.
That objection is exactly right, and it is why this ADR leaves the objection
where §3 put it: on currency, held by the gate, on a branch that is rebased and
re-gated before it merges.

The tests here are not about breakage at all. They ask whether the moved text
could change **what a reviewer would say** about this diff — §3's own criterion
for what belongs in the floor. A reviewer's authority over a diff runs through
text: `docs/review/guide.md` §1 makes the ADRs binding, and a reviewer applies a
ratified decision to a diff by reading what that decision says about the diff's
paths and symbols. A floor file that neither names nor is named by the PR can
change what a reviewer says about it only if the reviewer supplies the connection
itself — and a reviewer reads the diff against its own base, never the two
changes side by side.

The asymmetry with §1 is the same asymmetry. `docs/review/**`, `CLAUDE.md`,
`CONTRIBUTING.md` and `scripts/codex-review.sh` are not judged by whether they
name the PR, because they bind *every* diff by construction — they are the
instructions the reviewer is conducted under. An ADR binds a diff only through
what it decides about that diff's ground.

### 8. What this does not change

> **Normative.** Nothing in this ADR bears on ADR-0027 §1's coverage/currency
> split, §2's patch identity and its two properties, §3's refusal of path
> disjointness, §3's rename-aware both-endpoints reading, §4's disclosure,
> ADR-0165 §§2–3's ratification-flip exemption, ADR-0020 §3's unmoved-base tree
> comparison, or branch protection's `strict` currency requirement.

> **Normative.** Clearing the floor remains necessary and not sufficient. A base
> move that changes the reviewed patch identity, a recorded base that is not a
> proper ancestor of the merge base, an entry with neither a hunk nor an `index`
> line, and a drift set that exceeds the publishing budget each cost the round
> under ADR-0027 §2 and §4 whatever §§1–4 here say.

Two of those deserve their own sentence because a reader could plausibly expect
this ADR to touch them.

**The ratification-flip exemption is untouched.** ADR-0165 §3 rules that "Nothing
here bears on ADR-0027 §3's floor or §4's disclosure. Those govern a **base
move** ... and a ratification flip is a commit the PR itself carries." That
clause is a deferral to whatever ADR-0027 §3's floor contains, and this ADR
changes what it contains without touching the deferral: a floor breach still
costs its round whether or not `HEAD` is a flip, and a cleared floor is still
cleared whether or not `HEAD` is a flip. §9 applies ADR-0082 §1's test to that
clause and records the result.

**The dispatcher's ordering discipline is the complement, not a casualty.** Even
under this rule a floor PR merged into a queue of PRs that cite it costs one round
per citing PR — which is correct, since each of those PRs names it. That residual
is an *ordering* cost, and #1743 records the discipline that removes it: merge
non-floor PRs first, and let a floor PR merge into an empty queue. This ADR
decides nothing about dispatch; it removes the tax on the moves the discipline
cannot reach, and the two together are what leave the loop paying only for rounds
that could find something.

### 9. Records, and the three ADRs that get none

ADR-0070 §1's test decides amendment against supersession: an amendment "changes
no decision", such that a reader "would act **identically** before and after";
"any change to what was decided requires a new ADR that supersedes the old one",
wholly or partially.

**This is a partial supersession of ADR-0027 §3, and the test is met plainly.** A
reader holding ADR-0027 §3 alone refuses to ship a PR whose base move merged an
uncited ADR; under this ADR the same reader ships it and publishes the drift.
That is acting differently, so it is not an amendment. It is **partial** in
ADR-0070 §3's sense: §3's refusal of path disjointness, its both-endpoints
reading, its review-contract entries and §§1–2 and 4–7 are all untouched and stay
live.

ADR-0027's `Status` line therefore becomes, in this change:

```text
- Status: Partially superseded by ADR-0209 (§3's floor clause, narrowed — its `docs/adr/**` and contract-surface entries invalidate an artifact only where one of four tests binds; §3's refusal of path disjointness, its rename-aware both-endpoints reading, its `docs/review/**`, `CLAUDE.md`, `CONTRIBUTING.md` and `scripts/codex-review.sh` entries, and §§1–2 and 4–7 all stand)
```

**The `- Status: Accepted` token is dropped and the ADR-0165 qualifier moves off
the line**, per ADR-0082 §2: on a line carrying the leading `Partially superseded
by` token no amendment qualifier is written, because ADR-0070 §4's invariant reads
every `ADR-NNNN` after that token as a supersession target, and ADR-0165 is not
one. Nothing is lost: ADR-0027's header already carries the
`Amended: 2026-08-20 by ADR-0165` note stating that amendment in full, which is
the half ADR-0082 §2 calls the invariant one. A dated note recording this
supersession, and recording that the qualifier moved, is appended to ADR-0027's
header after that note.

**ADR-0020 is owed no record.** ADR-0082 §1 asks whether a clause of the earlier
ADR's own text becomes false or over-wide. ADR-0020 §3 decides that an artifact
is accepted when its recorded base and tree both match; it decides nothing about
a floor, which is ADR-0027's construct entirely. §§1–2 are untouched. What
ADR-0020's header does carry is ADR-0027's own dated note enumerating the floor —
but that note is ADR-0027's record of ADR-0027's decision, dated 2026-07-21, and
under ADR-0070 §1 a dated note is never rewritten. It stays true as history, and
ADR-0070 §4's consumer rule sends a reader who relies on a qualifier to the ADR it
names — ADR-0027, whose `Status` line now leads to this one. A record here would
be a record on a record, which ADR-0082 §1 does not ask for and ADR-0070 §1's
append-only form does not permit.

**ADR-0165 is owed no record, and this is the closest of the three.** Its §3
carries a marked clause reading in part "A base move touching `docs/adr/**` still
breaches the floor and still costs its round, whether or not `HEAD` is a
ratification flip." Read as a free-standing assertion about the floor's contents,
that sentence is over-wide after this ADR. It is not free-standing. ADR-0089 §2
makes a clause "one obligation", and this clause's obligation is stated in its own
first sentence — "Nothing here bears on ADR-0027 §3's floor or §4's disclosure" —
which is a **deferral**: it fixes the scope of the flip exemption against whatever
ADR-0027 §3 contains, and the sentence quoted is that deferral worked through on
the instance of the day. A deferral tracks its target. After this ADR the same
clause holds word for word in the sense it obliges: the flip exemption reaches
neither the floor nor the disclosure, a floor breach costs its round whether or
not `HEAD` is a flip, and this ADR moves neither. A reader is sent to ADR-0027 §3
by the clause itself, and finds the leading token there.

**ADR-0138 is owed no record.** Its handoff arms count rounds a lens has actually
recorded and the churn ratio `scripts/codex-review.sh` actually prints. This ADR
changes how many rounds are *owed*, not how a recorded round is counted; every
sentence of ADR-0138 stays true, joined by an obligation stated here. That is
ADR-0082 §1's stacked addition, recorded in this ADR and nowhere else.

**ADR-0025 is likewise untouched**, for completeness: ADR-0027 §7 scoped its
qualifier to §4's *description of the anchor*, and this ADR changes the anchor's
floor test rather than the anchor, leaving that description exactly as stale, and
as qualified, as ADR-0027 left it.

### 10. What the implementation owes

> **Normative.** §§1–6 are implemented by a separate lane, in one PR, confined to
> `scripts/`, to `tests/scripts/`, and to the documents that restate the rule.

> **Normative.** That PR implements §§1–6 in `scripts/ship.sh`, in the acceptance
> loop and in `--drill` alike. §6's single-implementation clause and its
> drift-record clause govern that implementation and are not restated here.

> **Normative.** That PR brings `docs/review/guide.md` and `CONTRIBUTING.md` →
> "Report the review, then mark it ready" into line with §§1–6, in place of the
> flat floor path list each states the rule as today.

> **Normative.** That PR adds tests under `tests/scripts/`: a test per clause of
> §§1–6, not a happy path.

> **Normative.** Those tests include at least the following cases, each
> asserting what is named for it.
>
> - A base move merging an ADR the PR names by number in its diff (owed).
> - The same move where the only such reference is in a PR description that was
>   retrieved successfully, the diff carrying none (owed — §5 admits the
>   description into the PR's text, and this is the path a diff-only reading
>   clears).
> - The same move with no such reference anywhere in the PR's text (free).
> - A moved ADR naming a path the PR's diff touches (owed).
> - A moved ADR naming a symbol the PR's diff adds (owed).
> - A moved ADR renamed within `docs/adr/`, and one renamed out of it, each read
>   at both endpoints (owed where either name's text binds).
> - A `docs/review/**` move, and a `scripts/codex-review.sh` move (owed, no test
>   consulted).
> - A `core/protocols.py` move adding a `Protocol`, against a PR touching nothing
>   in `core/` (owed).
> - A move adding an annotated attribute, and one adding a property, to an
>   existing `Protocol`, each against the same PR (owed under §4's first limb,
>   which a method-only reading would clear).
> - A move adding a `Protocol` base to an existing `Protocol` and declaring
>   nothing in its body (owed, which a declared-members-only reading would
>   clear).
> - A move widening a `Protocol` whose `typing.Protocol` base is written under an
>   alias (`from typing import Protocol as P`, `class Child(Base, P)`), and one
>   where it is written as an attribute access (`import typing`,
>   `class Child(Base, typing.Protocol)`), each against a PR touching nothing in
>   `core/` (owed — the two cases a bare-identifier reading clears).
> - A `core/protocols.py` endpoint that will not parse (owed).
> - A `core/types.py` move the PR neither touches `core/` for nor names (free).
> - A move changing a definition the PR's text names (owed).
> - A moved ADR citing `Class.member`, against a PR whose diff adds
>   `class Class` on one line and `def member` on another (owed).
> - The same citation against a PR adding `def member` to an existing
>   `class Class` whose header is **outside** the hunk's context window (owed —
>   the case a context-line reading clears, and the one that must be written with
>   a class long enough to put the header out of any default window).
> - The same citation against a PR adding `def member` to a file that never names
>   `Class` (free).
> - The same citation against a PR that touches a file naming `Class` without
>   adding or removing `member` (free).
> - The same citation against a PR whose diff names only the qualifier (free).
> - A moved ADR citing `pkg.mod.Symbol`, against a PR adding `class Symbol` to
>   `src/ai_assistant/pkg/mod.py` whose contents name neither `pkg` nor `mod`
>   (owed — the path supplies both qualifiers, and a contents-only reading clears
>   it).
> - A PR that **adds** the file carrying the cited member, and one that
>   **deletes** it, each judged on the endpoint it has and neither charged as a
>   failed read.
> - An unreadable PR file, an unreadable endpoint, an unparseable base-move
>   listing, an unretrievable PR description, and any other error reaching the
>   extraction (owed — §6's fail-closed inputs, each tested on its own).
> - Every existing ADR-0027 §§2–4 case, still refusing exactly as it does today.

**§10 is marked because in a marked ADR nothing else binds.** ADR-0089 §3 is
flat: unmarked text "is read to determine what a marked clause *means*; it never
supplies an obligation". This ADR carries marked clauses, so it is a *marked*
ADR under ADR-0089 §4, and every obligation of it has to be inside one. §10
stated the whole of what the implementation owes — the deliverables and every
required test — as unmarked prose and a bulleted list, which obligated the
implementation lane to nothing at all. That is ADR-0089 §4's under-marking hazard
exactly, and it is worth recording that it survived six adversarial rounds of
this document's own review before the seventh named it; ADR-0138 §4 records the
same defect being found in its own round 1.

**Four deliverable clauses and not one, for §5's reason.** The lane's
confinement, the `scripts/ship.sh` implementation, the two restating documents
and the test suite are separately movable: a later decision to drop the
`CONTRIBUTING.md` restatement, or to move the implementation to a Python module
`ship.sh` calls, has to reach one of them without reopening the others. The
confinement clause names `tests/scripts/` among the permitted paths because,
standing alone, it has to: unmarked, it was a lead-in to a list whose third item
was the test suite, and a clause that states its own scope (ADR-0089 §3) cannot
borrow that from the text below it.

**The enumeration is one clause, because it is one obligation with a stated
content.** Its cases are not a set of rules a lane could obey severally; they
are the floor under a single requirement — that the test suite cover these — and
a lane that writes all of them but one has failed that one requirement once. A
bulleted list is admissible inside a mark: ADR-0089 §2's grammar asks only that
every physical line be `> ` or a bare `>` at column 0, and what it forbids is the
converse — a mark *inside* a list item, where the block boundary would depend on
the enclosing structure.

**Two cases were re-attached to the citation they test.** The two free cases
above that turn on a PR touching a file which names the qualifier were written
trailing the `pkg.mod.Symbol` case while naming `Class` and `member`, which are
the *other* citation's names — an artefact of the round-4 insertion of the
module-qualifier case into the middle of the `Class.member` chain. They are
stated here against `Class.member`, the only citation whose names they use. No
case is added, removed or given a different outcome.

## Alternatives considered

**Leave §3 as it is and rely on ordering alone.** Rejected: the dispatcher's
discipline removes the queue half of the cost and nothing else. #1743's three
free rounds were on PRs merged behind a floor PR they had no relation to, which
is the half ordering cannot reach without serialising every lane behind every
docs lane — the axis ADR-0015 deliberately runs hot.

**Narrow the `docs/adr/**` entry to a ratification rather than any edit under the
tree.** This is ADR-0027's own first Revisit suggestion, on the ground that a
`Proposed` ADR "binds no reviewer". Rejected as insufficient rather than wrong:
every one of #1743's three wasted rounds crossed a *ratified* ADR merge, so this
narrowing would have saved none of them. It is also nearly free to add later on
top of the tests here, and doing both at once would confound the evidence for
each.

**A per-persona floor.** Not reopened. ADR-0027 §3 withdrew it and its grounds
are undisturbed; §2's persona-agnostic clause is what binds here.

**Drop the contract-surface entry entirely and rely on the gate.** Rejected on
§3's ground, unchanged: adding a Protocol breaks no gate, and ADR-0015 §5 treats
the surface as the class needing a second reviewer. §4's unconditional limb is
this alternative's refusal made narrow.

**Require the PR to cite, and drop the "moved ADR names the PR" direction.**
Rejected: it makes the saving depend on an author's discipline in exactly the
case §3 worries about, where the lane does not know the decision exists. §3's
hazard is a decision the lane never saw; a rule that only reads what the lane
wrote cannot see it either.

**Compute the relation with a model rather than an extraction.** Rejected: it
prices a round down to answer a question a regular expression answers, it is not
reproducible between two runs of the same inputs, and the acceptance rule is a
fail-closed surface where the two implementations — `ship` and its drill — must
agree by construction (§6, #751).

## Consequences

**Easier.** The rounds #1743 measured as unable to find anything stop being
charged. The saving is concentrated exactly where the evidence puts it: a lane
whose diff adds and removes no symbol any moved ADR names, merging behind an ADR
it does not cite. A process or docs lane is the clearest case; the drill and the
ship comment gain a per-path reason, so "why did this cost a round" stops being a
question anyone reconstructs by hand.

**Harder.** `ship` gains an extraction it did not have, over inputs it did not
previously read — a moved file's full text at both endpoints, and the PR
description. Each is a new failure surface, which §6 answers by binding on any
failure rather than by handling it. The rule is also longer to state than "these
paths cost a round", and a lane predicting its own cost now has four tests to
predict against rather than one path list. `--drill` is what removes that cost in
practice, and the drill's report already exists to be read rather than
reconstructed.

**A code lane will often still pay, and this is a prediction, not a hope.** Test
3's second limb binds whenever a moved ADR names a symbol the PR's diff adds or
removes, and the ADR corpus is dense with backticked symbols. A lane touching
`src/` under an active ADR wave should expect to keep paying; the saving lands on
lanes whose diffs are prose, scripts or tests naming nothing a moved ADR names.
If that prediction is wrong in either direction the evidence will show it, which
is what the Revisit condition in Consequences is for.

**The failure mode accepted, stated rather than argued away.** A moved ADR can
bear on a PR while neither text names the other. For that to happen the ADR must
state an obligation reaching this PR while naming no path the PR touches and no
symbol its diff adds or removes, *and* the PR must never write `ADR-NNNN` for it
in its diff or its description. ADR-0088 §1's citation form works against the
first — a decision about code names the code — and the dispatch practice works
against the second, since a lane's brief cites the ADRs that govern it and
`.claude/agents/worker.md` puts that pre-flight in the PR description. The
residual that survives both is a decision stated purely conceptually, naming no
ground: "no subsystem may do X". Such a rule normally lives in `CLAUDE.md`'s
golden rules or `CONTRIBUTING.md`, which §1 keeps absolute — so the shape most
likely to escape the tests is the shape least likely to be written in
`docs/adr/**` alone. It is not silent either way: §4's whole file set is still
published, now with the clearing reason beside each path, in front of the human
who owns the merge.

**Revisit if** a base move cleared under §§2–4 is followed by a finding a
re-review would have caught — which argues these tests, not §1's split. Or if the
three-in-nine figure does not hold over a larger sample, in either direction: a
much smaller saving argues the rule is not worth its own surface, and a much
larger one argues the `Proposed`-versus-ratified narrowing above is worth adding
on top. Or if the extraction is observed binding on almost every base move, which
would mean the rule has bought disclosure and complexity and no rounds.

**The strongest case against this decision.** §3's floor was chosen to be the
part of ADR-0027 "that has to be sound", and soundness there was bought by
refusing to predict anything about a reviewer. These tests predict something: that
a reviewer's judgement of a diff travels through text that names the diff's ground.
That is a strong regularity in this corpus and it is not a law. The honest answer
is that the prediction is checkable in a way the withdrawn per-persona split was
not — it reads what the ADR says rather than guessing what a persona would notice
— and that the case it can miss now arrives with the whole file set published
beside it. That is a bounded, disclosed risk against a measured, recurring cost,
which is the trade ADR-0027 itself made twice.
