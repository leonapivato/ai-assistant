# 140. The email source is a file the fetcher replaces whole, and the reader proposes envelopes, never bodies

- Status: Proposed
- Date: 2026-08-12

## Context

Leg 11's second half is source breadth, and email is the source the corpus has
been writing toward since leg 6. ADR-0095 §Context names the arrangement it
expects — "an RSS-to-maildir daemon running *on the hub box*, with the reader
reading their output" — and #664's library survey records the candidate stack:
`imap-tools` in a co-located fetcher, the reader parsing with stdlib `mailbox`,
`watchfiles` for noticing writes. **#664 is a survey of candidates and says so in
its own words** — "These are **candidates, not decisions** — each adoption that
touches a contract or the dependency set goes through its own change (and ADR
where owed)" — so nothing in it binds this decision, and the arrangement below
departs from it in one respect and says why.

### What is already decided, read rather than remembered

The seam exists and is exercised. `Reader` is a `core` Protocol with a
conformance suite and a canonical fake (ADR-0095 §3); `SourceReading` is a frozen
`core` type; `CalendarReader` is the one implementation; `GrantScope` carries
three members; `standing_grants` reads the store. What this ADR adds is a
*second* implementation of a settled contract, plus the facet field and the
figures that implementation needs, plus the four rulings the corpus has left
open specifically against email's arrival.

- **ADR-0093** rules what a reader is and what it may propose: attested beliefs,
  never an episode, never an absence (§4); a bound that is a function of the
  clock, configuration and the source's content, enforced by refusing and never
  by truncating (§5); a filesystem source opened non-blockingly and checked on
  the descriptor to be a regular file (§7); a read that either completes or
  raises (§8).
- **ADR-0095** renames the seam and re-tests its placement, and leaves every
  other ADR-0093 ruling standing under the substituted names (§5).
- **ADR-0096** fixes what a facet is and what an absent one means, and rules that
  the calendar facet carries no entry text (§6).
- **ADR-0097** makes a grant a recorded user act keyed on a reader's declared
  identity (§1), scoped by use (§2), gating the read by construction (§5);
  **ADR-0133** adds `NOTIFY`; **ADR-0139** makes the standing set readable from
  the store and fixes what a surface may present (§3).
- **ADR-0098** rules ingested content data-never-instruction with the blast
  radius bounded by construction, and states honestly what it cannot enforce
  (§5).
- **ADR-0110** makes coverage the thing that warrants an absence (§2, §3);
  **ADR-0117** puts an entry's position in an extent rather than in the envelope
  validity window, and rules what generalises (§8).

### The three questions this decision cannot start without

**#649 — a maildir is a directory and ADR-0093 §7 refuses one.** The issue is
open, its firing condition is "any co-located fetcher whose natural output is a
directory (an RSS-to-maildir daemon is one, and maildir is a directory by
definition)", and it enumerates what widening §7 would reopen: whether the byte
cap is per file or summed, whether §7b's single acquisition instant survives a
directory walk, and mid-read mutation — "a fetcher writing into the directory
while the reader walks it can produce a reading that corresponds to no state the
directory ever held". The calendar escaped by using `vdirsyncer`'s `singlefile`
storage. Email has no such off-the-shelf escape, so this ADR either finds one or
supersedes §7.

**#668 — ingested email is attacker-authored input to model calls.** ADR-0098 is
the answer the corpus gave, and it was written while the only source was a
calendar file. #668 asks whether that posture suffices *before email
specifically*. Two facts bear on how it is read today. First, ADR-0098 as
**ratified** already carries both corrections #674 raised against its `Proposed`
text: §5's mis-grounding on ADR-0075 §2 is corrected in place ("**It would
not.**", with the three real grounds enumerated), and §12's mixed-origin trigger
is "written as fired rather than as pending". So #674's first two items are
discharged on `main`, and only its third — consolidation as an unnamed §12
trigger — is live. Second, ADR-0098 §5 states plainly what it cannot enforce:
"on the live chain of the Context, externality is not recoverable at all", and
§12 defers the seam that would make it recoverable.

**Coverage and absence.** ADR-0110 §2 makes a declared coverage the only thing
that warrants an absence; ADR-0117 §5 rules that an unaccounted read declares
none, and §8 rules what generalises — "where a source's entries have a position
in that source's world, that position is producer testimony and is carried by the
extent". **#837** is open against ADR-0117 §5: its coverage withholding is
reading-wide, so one uninterpretable entry suppresses demotion for a whole
reading. #837 is not this ADR's to resolve, and this ADR states its relation to
it rather than leaning on either outcome (§8).

### The clause the brief for this lane did not name, and it is the larger one

ADR-0093 §5 does not merely leave a mailbox undecided. It rules on it:

> **Normative.** The `Sensor` contract carries no cursor and no durable
> per-source state, and a conforming sensor may not introduce one. A source that
> cannot be re-read in full within its bound — an append-only feed, a paginated
> API, **a mailbox** — is out of this contract's scope and owes its own decision.

and §11 defers it by name — "**A source that cannot be re-read in full** — a
feed, a paginated API, a mailbox — and therefore the cursor. §5 scopes this
contract to re-readable sources; ADR-0083 §13's upgrade-with-state discipline
governs whoever takes it." **This ADR is that deferral's decision**, and §3 below
is where it is taken. Both sentences lead with the *predicate* and put the
examples in a dash, which is what makes the answer available: the question is not
whether a thing is called a mailbox, it is whether the source the reader opens
can be re-read in full within its bound.

ADR-0093 §7a's closing paragraph also predicts, in unmarked prose, that "a
mailbox's [dimensions] would not be a time window". §12 finds otherwise. Under
ADR-0089 §3 unmarked text in a marked ADR supplies no obligation, so nothing is
superseded by disagreeing with it — but it is a prediction this ADR contradicts
and it is answered rather than passed over (§3).

### An honest statement of what this ADR is not allowed to settle

- **ADR-0098's posture.** It is ratified. §10 rules whether it suffices for email
  and narrows what email contributes; it re-decides no clause of it.
- **#837.** §8 states the relation and takes neither side.
- **#649 in general.** §2 removes email as a forcing case for a directory source.
  Whether a reader may ever read a directory is still #649's, unchanged.
- **The prompt assembler.** ADR-0098 §2 and §9 own it and it is still unbuilt
  (#672). This ADR adds spans it must escape; it does not build it.
- **A source registry, a display label, an instance-distinguishing identity.**
  ADR-0093 §11 defers all three at the third source and the second instance. This
  is the second source and the first instance of its type, so none fires.
- **Sending email.** An actuator, governed by ADR-0017 §1 and ADR-0021 §6, and
  categorically not reachable from a read-only seam.

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none.

### 1. The arrangement is three parts, and the file is the boundary between them

> **Normative.** The email source is a **co-located fetcher** that holds the
> account credential and writes a local store, and an `EmailReader` in `readers/`
> that opens that store and returns a `SourceReading`. The two share no process,
> no memory and no state but the store file.

> **Normative.** The fetcher is a **deployment component and not part of this
> system**. No Protocol describes it, no `Settings` field configures it, and
> nothing in `src/` starts, stops, supervises or health-checks it. What this ADR
> states about it is confined to the **file boundary** — what the store must
> contain, and how it must be published there (§2, §5, §13) — and each of those
> is a requirement of the arrangement, met by a deployment and unverifiable by
> the reader. Nothing on the far side of that boundary is governed here: its
> protocol, its schedule, its retries, its process model and its internal state
> are its own.

> **Normative.** The reader treats everything the store contains as **external
> content** under ADR-0098 §1, and treats the store's completeness as
> unverifiable. It may not derive any claim about the mail account from the store,
> and may not treat the fetcher's behaviour as an input to any bound it declares.

**The boundary is where it is because that is what buys every other result in
this ADR.** ADR-0095 §2 already argued the placement from this shape — "the
fetcher does the network, the reader reads its output off disk" — and rejected
`tools/` partly on the strength of it. Naming the boundary as the *file* rather
than as a vaguer co-location makes three later sections mechanical rather than
argued: §3's re-readability is a property of a file, §7's refusal to declare
coverage is a property of not being the fetcher, and §11's "no network call" is a
property of the reader having no other input.

**The fetcher being outside the system is a real cost and is not hidden.** It
means a fetcher that stops running produces a store that goes stale, and the
reader cannot tell a stale store from a quiet week — it will read the same
messages and propose the same beliefs, reporting health. That is the same class
of blindness ADR-0096 §4 accepts for an absent facet and ADR-0093 §8 accepts for
an empty reading, and the remedy is the operator's: the fetcher is monitored where
the operator monitors processes, not through this system's surfaces. §7's refusal
to declare coverage is what keeps that blindness from becoming a *wrong* belief
rather than merely a stale one.

### 2. The store is one regular file the fetcher replaces whole — ADR-0093 §7 is satisfied as ruled, not superseded

> **Normative.** The store is a **single regular file** in the mbox family,
> readable by stdlib `mailbox`. The email source is not a directory, and no
> clause of ADR-0093 §7 is narrowed, widened or excepted by this ADR.

> **Normative.** The fetcher writes the store by building a complete replacement
> and moving it into place with `rename(2)` on the same filesystem. It does not
> append to the store in place and does not edit it in place. This is a
> **requirement of the arrangement**, stated so a deployment can meet it; the
> reader cannot verify it and may not assume it has been met.

> **Normative.** The snapshot property is bought by the `rename(2)` requirement
> and is **not** a property the reader can establish from the bytes it reads.
> Where the requirement is violated the reader may observe a store no complete
> version ever held, and no clause of this ADR may be read as a guarantee that it
> cannot.

> **Normative.** A message the reader cannot interpret — torn, truncated or
> malformed — is **skipped** under §5's skip rule, and a skip raises nothing.

**This is #649's escape, and it is the same escape the calendar took, found
rather than inherited.** #649's own text names `vdirsyncer`'s `singlefile`
storage as the shape that "satisfies §7 exactly as ratified", and observes that
the concrete calendar lane therefore "owes nothing here". Email's version of that
shape is an mbox the fetcher replaces whole, and it satisfies §7 for the same
three reasons #649 enumerates as the ones a directory would reopen:

- **The byte cap is unambiguous.** One file, one `calendar_max_bytes`-shaped
  figure (§12's `email_max_bytes`), enforced on the read itself at most one byte
  past the cap, exactly as ADR-0093 §7's second clause requires. There is no
  per-file-versus-summed question because there is one file.
- **§7b's single acquisition instant is real.** One `open`, one bounded read, and
  `read_at` captured once at the instant the bytes are acquired. Every membership
  test in the read is evaluated against that one instant, which is what §7b's
  truthfulness argument requires and what a directory walk cannot supply.
- **Mid-read mutation is closed by the kernel rather than by a rule.** The reader
  holds an open descriptor; a `rename(2)` over the path leaves that descriptor
  pointing at the old inode, so the read completes against a file that was
  complete when it was opened. This is the property #649 identifies as the one a
  single file has and a directory does not — "A single file has no equivalent
  hazard: it is one `open` and one bounded read" — and it is why the atomicity
  requirement is on the *replacement* rather than on the fetcher's manners.

**The third and fourth clauses say what the first one buys and what it does not,
and separating them is a repair rather than a hedge.** An earlier draft of this
section promised that a torn store "may never produce a proposal the store's
intact content did not support", and adversarial review was right that the reader
cannot hold it: a writer editing an already-open inode in place can leave two
separately-read regions that never coexisted, and nothing in the resulting bytes
says so. **A clause whose truth depends on a fact the bound component cannot
observe is not a bound**, which is the lesson ADR-0098 §3 records against its own
earlier drafts — they "reached past" the span to conditions "whose truth depends
on an inference nobody can make deterministically", and the repair there was to
rule on what the component *does*. So the guarantee is stated as conditional on
the write discipline, the reader's own obligation is the skip, and §4 is where a
violated write's consequence is bounded — by clauses that hold whatever the bytes
turn out to be.

**Maildir is declined, and the survey's premise survives the decline intact.**
#664's candidate is "imap-tools … in a co-located fetcher writing a maildir,
reader parses with stdlib `mailbox`". Both halves of that are kept except the
word *maildir*: `imap-tools` still holds IMAP and TLS, and stdlib `mailbox` still
parses, because `mailbox.mbox` is the same module. What is given up is maildir's
per-file delivery atomicity — which is real, and which is atomicity of *each
file* and says nothing about the *set*, so it does not answer #649's third bullet
at all. A fetcher delivering into `new/` while the reader walks the directory
still produces a reading corresponding to no state the directory held.

**And the atomicity requirement is why the fetcher is a small script rather than a
mature daemon, which inverts one of ADR-0095's own reasons and is worth stating.**
ADR-0095 rates co-located fetchers strongest because the pattern "delegates
credential handling, network failure and protocol drift to mature tools instead of
to a connector this project would write and then own". `offlineimap` and `mbsync`
are those mature tools and both write incrementally, which is precisely the
discipline the clause above forbids. So the delegation is kept where it is
expensive — `imap-tools` owns IMAP, TLS and protocol drift — and given up where it
is cheap: building a file and renaming it is a dozen lines, and it is the dozen
lines that make §7's descriptor check and the kernel's inode semantics do the work
three clauses would otherwise have to do badly.

**#649 is narrowed and not closed.** What this ADR removes is #649's premise that
the strongest pattern *requires* a directory: for email it does not, and the
single-file arrangement is better on grounds that have nothing to do with §7
compliance. #649's general question — whether a reader may ever read a directory
source, and what happens to the three clauses if it does — is untouched and still
fires on the first source whose natural output really is a directory.

### 3. Re-readability: this is ADR-0093 §5's deferred decision, and the answer is still no cursor

> **Normative.** The `EmailReader` carries **no cursor and no durable per-source
> state**, and ADR-0093 §5's prohibition binds it unchanged. It is not out of
> ADR-0093's scope, because the source it opens is re-readable in full within its
> bound.

> **Normative.** The reader's bound is a **clock-relative window over arrival
> instants**: it proposes from the messages the store holds whose delivery instant
> lies in `[read_at - email_window_past, read_at)`, half-open, evaluated against
> the single `read_at` of ADR-0093 §7b.

> **Normative.** The window is the **reader's own** bound. The reader makes no
> claim about messages the store does not hold, may not assume the fetcher retains
> any interval, and may not widen or narrow its window on anything the fetcher
> does.

> **Normative.** Every instant this ADR's sections compute **saturates** at the
> representable bounds: where `read_at - email_window_past` is not representable
> the lower edge is the minimum representable instant, and likewise at the maximum.
> This governs §6's `covers_from` as well as the window edge, and none of this
> arithmetic raises.

**The saturation clause is stated here rather than inherited, and adversarial
review was right that inheriting it does not work.** ADR-0093 §7b's saturation
rule is scoped in its own words to "every instant **these sections** compute" —
its sections, about its window and its seek anchor — so it does not reach a second
reader, and an earlier draft of §12 claimed it in unmarked prose, which ADR-0089
§3 makes an obligation on nobody. The hazard is §7b's own and transfers exactly:
§12's range check makes an overflow unreachable from configuration alone but not
from configuration *and* a clock, and "a sensor is not entitled to assume where in
time the clock sits". Without the clause, one implementation clamps and reads the
store while another raises a wrapped overflow that escapes ADR-0093 §8's two
outcomes entirely. Saturation is chosen for §7b's reason unchanged: it loses
nothing, because there is no instant before the minimum for a message to have been
delivered at, so the clamped window and the ideal one select the same messages —
and it is deliberately not a refusal, because a clock that near the limit is a
wiring problem the reader neither causes nor can diagnose.

**The unboundedness is real and it is on the fetcher's side of the file.** A mail
account grows forever, which is why ADR-0093 §5 named a mailbox among the sources
that cannot be re-read in full. What §5's clause actually predicates on is the
source *the reader opens*, and here that is a file the fetcher replaces whole
containing the recent traffic. A read of it is one `open` and one bounded read,
and every read gets everything the file then holds. So the predicate is satisfied
and the clause does not reach this source — not because a mailbox has been
reclassified, but because the mailbox is not what the reader reads.

**§5's own argument transfers, clause for clause, and this is the check that
matters.** §5 removes the cursor by showing that observation's two failures do
not arise for a clock-relative window:

- **The coverage failure.** §5's calendar argument is that "the window *moves with
  the clock*, so every run's window is recomputed from scratch and an entry inside
  it is read whether or not any previous run read it. There is no accumulating
  backlog for a cursor to track." That holds here with one added condition, stated
  rather than assumed: it is true for as long as the fetcher's retention exceeds
  the reader's window, and its window exceeds its interval. Where it does not — a
  hub down for a week against three days of retention — messages are lost to
  ingestion permanently. **That is exactly the cost §5 already accepted** ("An
  entry that falls outside the window before any run reads it is never proposed …
  the price of not carrying a cursor"), arriving here through the fetcher rather
  than through the clock, and the operator's remedy is the same one: lengthen the
  retention or shorten the interval, knowingly.
- **The cost failure.** §5's second half is that a reader "reads a file and parses
  it" rather than spending a model call. Unchanged, and cheaper here than for the
  calendar: §5's own worked hazard is recurrence expansion, and a mailbox has no
  generator — a message is a message.

**A cursor would also be the wrong instrument even if it were permitted**, and
saying so is what keeps a later lane from adding one as an optimisation. What a
cursor would buy is reaching a message that fell out of the window, and it cannot:
the message is not in the store either, because the fetcher's retention is what
removed it. A cursor over a store the reader does not control is a durable record
of where we were in a file somebody else rewrites, which is ADR-0083 §13's
upgrade-with-state discipline paid for nothing.

**ADR-0093 §7a's prediction is answered rather than ignored.** Its closing
paragraph says "A second sensor names its own dimensions — a mailbox's would not
be a time window — and inherits the obligation, not the table." The prediction is
unmarked prose and binds nothing (ADR-0089 §3), and it is wrong for a reason worth
recording: it supposed the reader would face the account. Facing a
retention-windowed file instead, a time window is not merely available, it is the
only bound that satisfies §5's requirement that the bound be "a function of the
clock, its configuration and the source's own content, and of nothing else" — a
message *count* would make what a read sees depend on how much arrived, and a
cursor is forbidden. §12's table is genuinely derived from that and is not the
calendar's copied: it has one window edge rather than two, and no expansion
budget.

### 4. Nothing the store says is authenticated, and no field of a message is an identity

> **Normative.** No component of this system treats any header field of a message
> as authenticated. A sender address, a display name, a `Message-ID` or any other
> field is **what the store says**, never a verified fact, and no band,
> confidence, precedence, permission, grant, routing or ranking decision may be
> made on the strength of one.

> **Normative.** What the clause above forbids is granting a message **standing**
> on the strength of a field — authority, identity, trust, precedence, or a claim
> on any surface. It does not forbid deciding whether the reader looks at a
> message at all, and §5's window membership is that decision and only that: it
> is taken on `X-Assistant-Delivered-At` and confers nothing. A message admitted
> to the window is proposed in the `ATTESTED` band under every clause of this
> section, exactly as one the fetcher dated honestly. A message that forges the
> header — reachable only where the fetcher's strip has failed — buys its own
> admission to a window it could have reached by being sent again, which is not a
> capability, and buys no other field's standing.

> **Normative.** An address or display name drawn from a message is **never an
> identity** in this system. It may not be matched against the user, against a
> `SourceGrant`, against a spoke's enrolment (ADR-0124), or against any other
> subject, and may not be used to raise what a proposal drawn from that message
> may become.

> **Normative.** A reader mints its own id per proposal, opaque to the source
> (ADR-0092 §6). A message's `Message-ID` may not be used as, or derived into, a
> record id.

**This is the clause that makes the format choice safe rather than merely
defensible, and it is stated before the format's weakness is named.** An mbox
delimits messages with an in-band `From ` line, and a writer that fails to escape
a body line beginning `From ` splits one message into two — at which point the
second fragment's apparent headers are text the message's author chose. So an
attacker can manufacture a store entry that appears to come from someone else.

**That attack gains the attacker nothing, and the reason is the reason the clause
is general.** Anyone who can send mail can already put any `From:` they like on a
real message; SMTP has never authenticated it, and no system that reads a mailbox
may assume otherwise. The mbox splitting hazard therefore adds volume, not
capability — and the defence against both is the same clause, which is why it is
written about *every* field rather than about mbox. The `ATTESTED` band is exactly
the right home for this: its whole standing is that somebody else said it
(ADR-0093 §1), and a belief that the store attributes to Alice is a belief about
what the store said, ruled on by the gate like every other.

**The escaping requirement still belongs on the fetcher, and what it actually
costs when it fails is stated rather than minimised.** A split message does three
things. It inflates §6's facet count and consumes §12's message cap — both our own
claims about what the reader parsed, which §6's third clause says in as many words
and never as claims about the account. And it puts **body text into a proposal**,
wearing an envelope's clothes: the fragment's apparent `Subject` is a sentence the
message's author wrote, and §5's body prohibition cannot see it. That is the honest
residual of choosing an in-band-delimited format, it is why §5's clause is stated
over the framing rather than over the bytes, and it is bounded rather than
prevented — the fragment lands in the `ATTESTED` band like every other proposal,
under §4's clauses (no authority, no identity, nothing authenticated), under
ADR-0098's ceilings, inside §12's message cap, and visible and killable by the
user (ADR-0073 §5).

**Two requirements have to fail together to reach it, which is worth stating
precisely rather than leaving as reassurance.** The splitting hazard needs a
`From ` line *in a body*, so it is unreachable when §5's envelopes-only
requirement is met: a store the fetcher built from header blocks alone contains no
body for an attacker to hide a separator in. It needs escaping to fail *as well*,
and it additionally needs the fetcher to have written a header value containing a
bare line break, or the fragment carries no valid `X-Assistant-Delivered-At` and
§5 skips it. Note what the delivery header does **not** buy here: an attacker who
splices a plausible `X-Assistant-Delivered-At` into their own body gives the
fragment exactly one such header, so the duplicate rule does not catch it. The
skip catches the careless case and §4 catches the careful one, and neither is
offered as catching both.

Under ADR-0098 §6 no bound in this corpus may be bought from a filter, and none is
bought here: the clauses above are total, and the escaping is hygiene stated as
hygiene.

### 5. What the reader proposes: the envelope, and no body span at all

> **Normative.** For each in-window message the store holds, the `EmailReader`
> proposes **one** attested belief drawn from a fixed field set: the sender as the
> store gives it, the subject as the store gives it, and the message's delivery
> instant. Every proposal is in the `ATTESTED` band and carries
> `sensitivity=DataTier.PERSONAL`, stated and never defaulted (ADR-0093 §4).

> **Normative.** `Attestation.reported_at` carries the message's own `Date`
> header — the sender's clock, which is what a report time is (ADR-0092 §3). The
> **delivery instant** is a different fact and is what §3's window membership is
> decided on. The two are never merged and neither is substituted for the other.

> **Normative.** The delivery instant is carried in **one** header the fetcher
> writes, `X-Assistant-Delivered-At`, whose value is a single timestamp and
> nothing else, drawn from **this closed subset of RFC 3339 and no wider**:
> `YYYY-MM-DDTHH:MM:SS`, optionally followed by `.` and one to six digits, then a
> **determinate** offset. The date-time separator is an upper-case `T`; `SS` is
> `00` through `59`; and the offset is an upper-case `Z` or a numeric `+HH:MM` or
> `-HH:MM` that is not `-00:00`. The fetcher writes it from what the server
> recorded, and **strips every copy the message itself carried** before writing
> its own.

> **Normative.** That subset is the accepted value **in full**, and it is closed
> by construction rather than by a list of exclusions. A value RFC 3339 admits
> but the subset does not — a leap second, a lower-case `t` or `z`, a fractional
> part finer than a microsecond — is not an accepted value here, whether or not
> it is well-formed, and reaches the skip rule below. The reader never
> **normalises a value onto the subset**: it does not roll a leap second to the
> following instant, case-fold a separator, or drop precision to make a value
> acceptable. It checks the spelling against the subset itself and **does not
> delegate acceptance to a more permissive parser**, whose accepting a value is
> not this clause's test.

> **Normative.** The reader decides membership on that header and on nothing else.
> It never derives a delivery instant from the mbox `From ` line, from a
> `Received` header, from `Date`, or from the file's modification time.

> **Normative.** A message carrying no `X-Assistant-Delivered-At`, more than one,
> or one whose value is not exactly a timestamp in the form the clauses above fix
> — the closed subset in full, not merely a well-formed RFC 3339 timestamp — is
> **skipped**, as is a message the reader cannot otherwise interpret. Nothing is
> substituted for a fact the source did not make, and a skip raises nothing.

> **Normative.** `Date` is read under that same rule, because it is the other
> field carrying an instant. A message with **no** `Date`, with more than one, or
> with a `Date` the reader cannot resolve to a determinate instant — RFC 5322's
> `-0000` and an absent zone alike — is **skipped**. The delivery instant is
> never substituted for it, the reader never selects among several `Date` values,
> and `reported_at` is never defaulted, omitted, or filled from any other field.

> **Normative.** The sender and the subject are **not** read under that rule and
> are never on their own a reason to skip. A message with no `Subject`, or with
> more than one, is proposed with the subject **empty** and no selection made
> among the candidates; the sender is treated identically. Neither field carries
> an instant, neither is an identity (§4), and a message that legitimately
> carries no subject is ordinary mail rather than a fault.

> **Normative.** The reader acquires the store's bytes whole and bounded, and
> traverses its framing, exactly as ADR-0093 §7's byte cap requires. Nothing in
> this section restricts which bytes it reads or scans past.

> **Normative.** The reader **interprets** only what the store's framing presents
> as a message's **header block**. What that framing presents as a **body** is
> traversed and discarded: it is never parsed for meaning, never materialised into
> a proposal, a facet or any value that leaves the reader, and this ADR opens no
> path by which such a span reaches a model call.

> **Normative.** Whether the framing is honest is the fetcher's, and the reader
> may not assume it. Where the framing is violated, text a message's author wrote
> may present itself to the reader as another message's envelope; §4 is what
> bounds that, and no clause of this ADR may be read as a guarantee that it cannot
> happen.

> **Normative.** The store the arrangement requires contains **envelopes only** —
> per message, the header fields above, `X-Assistant-Delivered-At`, and what the
> format needs to delimit it. This is a requirement of the arrangement in §2's
> sense; the clauses above bind the reader whether or not it is met.

**Two clocks, and the security half is why they are separated rather than merely
distinguished.** `Date:` is the sender's claim, which is precisely
`Attestation.reported_at`'s meaning and precisely the thing an attacker controls.
Deciding window membership on it would let a sender hold a message in every future
window by writing a future date, or drop out of every window by writing a past
one. The delivery instant is written by the fetcher from what the server recorded;
it is not a field the message's author sets. The corpus already keeps two clocks
apart at the reading level — `read_at` and `as_of`, "two different clocks and …
never merged" — and this is the same discipline one level down, taken for a
second reason.

**The header, its syntax and its strip-and-skip rule are pinned here rather than
left to the lane, because "the delivery instant the store records" was not a
specification and adversarial review showed why.** An mbox has a Unix-`From `
line, a `Received` chain and a `Date`, and two lanes choosing differently among
them put the same stored message in different windows while each believes it
conforms — which is ADR-0103 §9's test failed exactly ("could two lanes make
incompatible choices and both claim compliance?"), and the reason ADR-0110 §2
pinned coverage's domain rather than its spelling. Three things therefore had to
be decided and are:

- **Which field**, because the alternatives are worse in a specific way. The
  Unix-`From ` line is reachable by §4's splitting hazard and its timestamp has
  never had one syntax; `Received` is a chain of hops whose earliest entries are
  written by machines the sender may control; `Date` is the sender's own. A header
  the *fetcher* writes is the only one whose author is on our side of the file.
- **Its syntax**, and pinned as a **closed subset** rather than as RFC 3339 minus
  a list of exclusions — because the list did not stay closed. "A timestamp"
  admits a dozen parsers that disagree about offsets, and the corpus's one instant
  type is tz-aware, so RFC 3339 is the right base: it is what a fetcher can emit
  in one line and a reader can parse without a policy. But three separate literals
  sit *inside* that grammar, and each fails ADR-0103 §9's test on its own.

  - **`-00:00`.** The reason is not the one it looks like: RFC 3339 §4.3 makes it
    a *determinate* UTC instant whose offset to local time is merely unknown, so
    the value does establish a delivery time. What it does not establish is
    agreement — `datetime.fromisoformat` reads it as UTC while
    `email.utils.parsedate_to_datetime` treats the `-0000` form as carrying no
    usable zone at all, so two conforming lanes admit and exclude the same message
    at a window edge.
  - **A leap second.** RFC 3339 §5.6's `time-second` admits `60`, so
    `2016-12-31T23:59:60Z` is well-formed and its offset is determinate. Python's
    `datetime` cannot hold second 60 at all and both stdlib parsers raise on it,
    so a lane built on either skips the message — while a lane whose parser
    accepts the grammar as written is left to decide for itself whether to clamp
    to `:59` or roll to the following second. Three incompatible outcomes, each
    claiming compliance.
  - **A lower-case `t` or `z`.** RFC 3339 §5.6 permits both spellings by name, so
    a parser conforming to the grammar must accept `2016-12-31t23:59:59z`, and
    `datetime.fromisoformat` raises on it. What diverges here is not a microsecond
    at an edge: the message is present in one lane's reading and absent from
    another's.

  Three literals found one at a time, the second only after the first had been
  excluded and the third only when the second was being fixed, is the shape that
  says the **list** is the defect rather than any entry on it. So the
  clause states the admissible set once and declares it complete. Every value the
  subset admits is one `UtcInstant` holds exactly, so no conforming lane is ever
  left a normalisation choice to make — and a fourth literal found later is
  already excluded rather than owing a fourth exclusion. Closing it costs an
  honest fetcher nothing, in the same way excluding `-00:00` cost it nothing: a
  fetcher that knows the instant writes it upper-case, to second `00`–`59`, with
  an offset it actually knows. A fetcher that writes anything else is broken or
  forging, and §5 skips it either way, which is the fail-closed direction.
- **What happens to a message-supplied copy**, because a header the fetcher writes
  is a header an attacker can also write. The fetcher strips; the reader skips on
  a duplicate rather than picking one. **Skipping is fail-closed and is the whole
  point**: the worst an attacker achieves by forging the header is that their own
  message is not proposed, which is not an attack. Picking the first occurrence
  would have made forgery *work* wherever a fetcher's strip failed.

**Envelopes only, and the argument is minimisation before it is injection.** Three
things follow from the body never being present, and each is a bound obtained by
construction rather than by a rule someone must remember:

- **The tier stays honest.** `sensitivity` is chosen for what the source holds
  (ADR-0093 §4), and a mailbox's bodies hold everything from a newsletter to a
  password-reset link — Tier 0 by ADR-0004's own classification. No per-message
  classifier could tell them apart, and #659 records that a `SECRET`-tier ruling
  made on the ingestion path reaches no surface, so a wrong classification would
  also be an invisible one. An envelope is `PERSONAL` and is uniformly
  `PERSONAL`.
- **The byte cap becomes a bound rather than a lottery.** A single 25 MiB
  attachment would exceed any figure a table could defend, and ADR-0093 §5 makes a
  cap refuse rather than truncate — so one large message would take the whole
  source offline until an operator intervened. Two thousand envelopes are a few
  megabytes.
- **§10's narrowing is structural.** There is no body in the store to read, so the
  deferral in §14 is not a discipline the next lane must hold; it is a shape.

**The body clause is stated over the framing rather than over the bytes, and two
earlier drafts were not holdable.** The first said the reader "materialises no
span of a message body" and added that the clause binds "whether or not" the
envelopes-only requirement is met — impossible to obey, because an unescaped
`From ` line inside a body splits one message into two and the second fragment's
apparent `Subject` *is* body text the reader has no way to recognise as such. The
second said the reader "does not read, parse or materialise" a body-presented
span, which is unsatisfiable for a different reason adversarial review found:
ADR-0093 §7 requires the source read to be bounded on the read itself, and an
in-band-delimited store cannot be traversed at all without scanning past bodies to
reach the next delimiter. **Reading a byte and interpreting it are two acts**, and
only the second is what this section is about — so the clauses now separate them:
acquisition and framing are unrestricted and are what ADR-0093 §7 already
governs, and the prohibition is on interpretation and materialisation.

A clause the reader must breach to function is worse than no clause, because a
later lane reads it as a guarantee somebody checked. The case where the framing
lies is handled where it is actually bounded, in §4. This is the same repair §2's
third clause takes, for the same reason, and ADR-0098 §3 is the corpus's precedent
for making it — its own earlier drafts "reached past" the span to conditions
nobody could evaluate, and the fix was to rule on what the component does.

**What is deliberately left out of the field set.** `To:` and `Cc:` are not
carried: they multiply Tier-1 addresses by every recipient of every mailing list,
and the useful question they would answer — *was this addressed to me* — needs the
user's own addresses, which the reader does not have and must not guess.
`Message-ID` is not carried into content and may not become an id, per §4's third
clause. Threading headers are not carried, because reconstructing a conversation
from `References` is an inference and ADR-0093 §2 rules that "a reader infers
nothing: it reads a file and reports what the file says". §14 defers each with its
condition.

**A skip rather than a refusal, and the line is ADR-0117 §5's.** A message with no
delivery instant is an entry the source holds and the read cannot account for.
`CalendarReader` skips exactly this shape — an occurrence whose `DTSTAMP` is
absent, "because ADR-0092 §3 permits no substitute for a report time the source
did not make" — and withholds coverage on the strength of it. The email reader
skips for the same reason and withholds nothing, because §7 gives it no coverage
to withhold.

**Re-reading duplicates rather than folds, and the reader inherits that unchanged.**
ADR-0093 §5's honest half applies: a proposal is minted at an id opaque to the
source, so an unchanged message re-read is folded by *similarity* at the gate and
not by identity (#631). Email is the friendlier case — a delivered message is
immutable, so the rewrite arm of #631 has no subject here — but the guarantee this
ADR relies on is the narrower one §5 relies on: a re-read destroys nothing.

### 6. What the reader facets: two scalars, and no span of a message

> **Normative.** `CurrentContext` gains `email: EmailFacet | None = None`.
> `EmailFacet` extends `ContextFacet` with two fields: `arrived_in_window`, a
> non-negative `int` counting the messages the read proposed from; and
> `covers_from`, a `UtcInstant` being the inclusive lower edge of the arrival
> window the reading covered.

> **Normative.** The email facet carries **no span of any message**. It carries no
> sender, address, display name, subject, body, identifier or per-message instant.

> **Normative.** `arrived_in_window` is a count of what **this reader parsed from
> the store**. It is not a claim about the account, is never presented as one, and
> no consumer may read it as a count of mail received.

> **Normative.** `SourceReading.facet` is widened from `CalendarFacet | None` to
> `CalendarFacet | EmailFacet | None`, as ADR-0096 §5 requires of each later ADR
> that adds a facet.

> **Normative.** That union is made explicitly **discriminated** on a new field
> `kind`, carried by every concrete facet type as its own `Literal` tag —
> `CalendarFacet` gains `kind: Literal["calendar"]` and `EmailFacet` declares
> `kind: Literal["email"]`. Every facet type added later carries one.

> **Normative.** `kind` is defaulted to its type's own tag, so every existing
> construction site of `CalendarFacet` is unchanged and every existing fixture and
> fake stays valid.

> **Normative.** The default does **not** make a *serialised* facet payload
> lacking `kind` loadable, and no clause here may be read as claiming it does: a
> discriminated union extracts its tag from the input before it selects a member,
> so the default never runs. A lane that gives `SourceReading` or `CurrentContext`
> a persisted or wire-carried form owes the compatibility step with it, and owes it
> in a shape that cannot mask a genuinely invalid payload.

> **Normative.** The name `kind` is **reserved for the discriminator** across the
> facet hierarchy. Declaring it as a `Literal` tag is what a concrete facet type
> is required to do; what no facet may do is give the name a payload meaning, and
> no type below a concrete facet may redefine it.

**This is ADR-0096 §5's second clause discharged at the moment its condition
fires, and the lane owed it rather than the implementation.** §5 rules that the
annotation is "widened by each later ADR that adds a facet", and that "when a
second concrete type joins that annotation, the union is made explicitly
**discriminated**, each member carrying its own literal tag, so that no payload's
facet type is decided by inference". **This ADR is that second type**, so both
clauses fire here and nowhere else — an implementation lane that met the first and
missed the second would ship a smart union in which "two facets that differ only in
a scalar could parse as each other, quietly", which is §5's own stated defect. An
earlier draft of §13 listed only `EmailFacet` and `CurrentContext.email`, leaving
`SourceReading.facet` annotated `CalendarFacet | None` and the reader-to-context
handoff with no satisfiable contract at all; adversarial review found it.

**A separate `kind` rather than reusing `source`, and the reason is the validator
one section over.** `source` looks like a free discriminator — it already carries
the reader's declared identity, and the two values would agree. It cannot be one:
ADR-0096 §5's model validator requires `facet.source` to equal the *reading's*
`source`, which is a plain `str` carrying `Reader.name`, so making the facet's
`source` a `Literal` would constrain by type a value that is cross-checked against
free text, and a mismatch would surface as a union-resolution failure naming the
wrong fact. The two are different facts and stay two fields: `source` says who
produced the value, `kind` says which payload shape it is. Defaulting `kind` is
what keeps the widening additive, which is ADR-0008 §1's pattern and the property
§5 relied on when it called this "one more line in the change that ADR
authorises".

**What the default buys is bounded, and the bound is stated because an earlier
draft over-claimed it.** That draft said no "fixture, fake or **persisted** value"
is invalidated. The first two are true and the third was a claim about a class of
value that does not exist, asserted as though it had been checked. It has now been
checked: no store writes a `SourceReading` or a `CurrentContext` and no wire frame
carries one — both are in-process values passed from a reader to `orchestration`
and to the ingest, and the only `model_validate` calls on them are tests
round-tripping a payload their own run just dumped. **So there is no legacy
payload to invalidate.** The clause is nonetheless worth its second half, because
the underlying pydantic behaviour is real and counter-intuitive: tag extraction
precedes member selection, so a model-field default cannot rescue an input that
omits the discriminator. Adversarial review raised this as a compatibility break;
the break does not exist, and the sentence that implied it had been ruled out for
a *general* class of value is the defect. A later lane that persists one of these
types will hit it, and now finds it written down rather than in a stack trace.

**The reservation is worded over the *name's meaning* rather than over
redefinition, because the obvious wording contradicts the clause above it.** An
earlier draft said `kind` is reserved "exactly as `source`, `read_at` and `as_of`
are — no subclass redefines it", and adversarial review was right that this makes
the union unsatisfiable: those three live on `ContextFacet` and a subclass must
leave them alone, whereas a discriminated union requires each *concrete* member to
declare its own distinct literal, which is the one thing a no-redefinition rule
forbids. A shared `kind` on the base discriminates nothing. So the two rules are
different in kind and are stated differently: the base's three stamp fields are
reserved against redefinition, and `kind` is reserved against acquiring a second,
payload meaning while each concrete type is *required* to declare it.

**ADR-0096 §5's other three clauses bind this facet unchanged and are not
restated as though they were new**: the facet's stamp is the reading's, the model
validator refuses a facet stamped otherwise, and the `context/` adapter
contributes under the field it was wired for and raises `ContextError` on a type
mismatch. The last of those acquires a second instance here for the first time,
which is exactly the wiring bug it was written against.

**The facet's job is the one thing the beliefs cannot answer at request time, and
for email that is volume rather than presence.** ADR-0096 §6 chose the calendar's
three scalars by asking what a scan of stored beliefs could not cheaply supply —
*is something happening right now, and when is the next thing*. The email analogue
is *how much has arrived lately*, and the reason it is worth a field is that a
turn's answer changes with it: "you have had two messages today" and "you have had
ninety" are different situations, and neither is legible from a belief the
retrieval budget may not have selected.

**`covers_from` is `covers_until`'s mirror and exists for the identical reason.**
ADR-0096 §6 carries `covers_until` because "`next_starts_at` being `None` means
nothing to a consumer who does not know how far ahead we looked — and a consumer
of `CurrentContext` does not read `Settings`, so the horizon has to travel with
the value or not exist". A count of zero is exactly the same shape from the other
side: it means nothing without the interval it counted over. ADR-0117 §8
anticipated the symmetry when it observed that "a backward-looking source would
have hit the same collision from the other side"; this is that source, and only
the one edge is carried because email has only the one.

**No entry text, and the rule is stronger here than ADR-0096 §6 needed it to be.**
That section kept titles and locations out of the calendar facet because
`CurrentContext` is rendered into every prompt and those are "the most disclosing
thing it holds". A subject line is that and one thing more: it is attacker-chosen
text on the advisory path, where a failure is silent and where ADR-0098 §2's
escaping obligation falls on an assembler that does not yet exist (#672). Two
scalars need no content budget, no truncation rule and no escaping at all, which
is what makes the facet safe to ship before the assembler lands. §14 leaves the
additive door ADR-0096 §6 left, with the condition that opens it.

**A count rather than a boolean, for ADR-0096 §6's reason exactly.** `busy: bool`
failed there because deciding what counts as busy is a judgement about the user's
day; `has_new_mail: bool` fails here because deciding what counts as new is a
judgement about the user's attention, and the reader holds no read/unread state
and must not infer one. A count is a fact about what was parsed.

### 7. The reader declares no coverage, and no email belief is ever absence-demotable

> **Normative.** The `EmailReader` declares **no coverage** under ADR-0110 §2 and
> **no extent** under ADR-0117 §2. No reading it produces warrants an absence, and
> no belief it proposes is absence-demotable.

> **Normative.** No later lane may give this source a coverage on the fetcher's
> testimony — on a retention setting, on a manifest the fetcher writes, or on any
> other statement by a component outside the read.

**Coverage is what a read *exhausted*, and this read exhausts a file rather than a
world.** ADR-0110 §2 is explicit that a coverage "is never widened to what the
reader was configured to cover, to what the source is presumed to hold". The
reader exhausts the store; whether the store holds every message that arrived in
any interval is the fetcher's property, and the reader has no way to check it. A
coverage declared here would be a claim about the mail account made on testimony,
which is the one thing §2 forbids. §1's third clause is where that unverifiability
is fixed, and this is the section that spends it.

**And the demotion it would buy is not wanted, which is the decisive half.** This
is mechanical rather than philosophical. The fetcher's retention window guarantees
that **every message eventually leaves the store**. Under a coverage-declaring
email reader, ADR-0110 §3's conditions would then be met for every belief the
reader ever proposed, one retention period after it was proposed, and ordinary
retention would retire the entire email half of memory on a schedule. Nothing
about that is a truth the system learned; it is a fetcher's disk-space setting
reaching through the seam and closing windows.

**The asymmetry with the calendar is real and it is worth naming, because it is
why one source wants demotion and the other does not.** A calendar entry is a
standing claim about the world that can be *withdrawn* — a meeting is cancelled,
and the entry's disappearance is the source telling us so. A delivered message is a
**completed event**: it arrived, and it said what it said. Deleting it from a
mailbox does not make it untrue that it arrived, so its absence from a later
reading is evidence of nothing at all — which is ADR-0093 §4's original rule
("An entry missing from a later reading is not evidence that the entry was
withdrawn") holding here in the unnarrowed form, rather than in the exception
ADR-0110 §3 carved for a covered reading.

**No extent, and ADR-0117 §6 supplies the precedent rather than this ADR inventing
one.** A message's position in the source's world is an instant, not a span, and
an extent is a half-open interval in which a zero-width value "would be contained
by every coverage and would make such a record demotable by any reading at all,
which is the unsound direction". ADR-0117 §6 met that shape in the zero-duration
occurrence and ruled that the proposal declares no extent and "is simply never
absence-demotable". The same answer arrives here for the same reason, and it costs
nothing that §7's first clause has not already declined. A later ADR that gives
this source a coverage owes the point-position convention with it.

**This is ADR-0117 §8's rule applied and its judgement honoured, not stretched.**
§8 rules that whether a source's entries have a position worth stating "belongs to
the lane that holds the source, which is the lane that can say whether 'absent'
means anything for it at all", and that a source which declares none "is not
thereby deficient". This is that lane, and the answer is that "absent" means
nothing for email.

### 8. #837 is neither engaged nor resolved, and this ADR is evidence in it for neither side

#837 is open against ADR-0117 §5: coverage withholding is reading-wide, so one
entry the calendar reader cannot interpret suppresses demotion for a whole
reading. It asks for evidence that real sources carry such entries routinely, and
for a decision about what a finer-grained coverage would mean.

**The mechanism has no subject here.** §7 gives the email reader no coverage at
all, so §5's withholding never runs: there is nothing to withhold, and §5's
reading-wide coarseness costs this source nothing. The message §5 would have
withheld on — one the reader cannot interpret — is simply skipped under §5's third
clause above.

**So this ADR must not be read as evidence in #837 in either direction.** It is
not a case of the withholding biting, because nothing withholds. It is not a case
of the withholding being harmless, because nothing was at stake. And a resolution
of #837 in either direction — a set-valued coverage, a position-scoped withholding,
or a decision to leave §5 as it stands — changes nothing decided here, because §7's
refusal is grounded in the fetcher's unverifiability and in retention eating the
memory, and neither of those is a coverage-granularity question. A lane taking
#837 gains one datum and it is a negative one: the second source in the corpus
turned out not to want a coverage, so the evidence #837 asks for still has to come
from the calendar.

### 9. The grant is on the read, the fetcher is not granted, and refusing it does not stop the mail

> **Normative.** The email source is one grantable source whose subject is the
> reader's declared identity, `"email"` (ADR-0097 §1). It is granted, revoked,
> reported by `standing_grants` and rendered by a client exactly as every other
> source is, and this ADR adds no grant mechanism, no scope member and no
> exception.

> **Normative.** Where no live grant names the use, the store is **not opened** —
> not resolved, not opened, not parsed (ADR-0097 §5, ADR-0133 §2).

> **Normative.** A grant on this source authorises **this system's read of the
> store**. It does not authorise, describe, start, stop or bear on the fetcher,
> and no surface may present a grant as a statement about whether mail is being
> fetched, retained or deleted.

> **Normative.** Withdrawing the grant stops the reading and does not stop the
> fetcher. No surface may state or imply that revoking it prevents mail arriving
> on the box or removes the store from disk.

**The three scopes each mean something here, which is what keeps this from being a
member with no consumer.** `FACET` authorises §6's two scalars at assembly time;
`INGEST` authorises §5's proposals into memory; `NOTIFY` is available and this ADR
mints no producer that uses it, so nothing reads it for this source until one
exists (ADR-0133 §7's last bullet governs a fourth member and ADR-0130 §10 governs
which producers exist). A user who grants `FACET` alone gets a count and no
durable belief, which is exactly the sentence ADR-0097 §2 says the axis exists to
make sayable.

**The fourth clause is the one this arrangement makes newly necessary, and it is
not the calendar's situation.** For a local `.ics` file, revoking the grant left a
file the user already had. Here a *process the operator started* holds a
credential and pulls mail onto the box whether or not any grant exists — so a
surface that says "revoked: your email is no longer being read" is true and a
surface that says "revoked: we are no longer collecting your email" is false. This
is ADR-0133 §2's shape exactly — "The guarantee is over the **read**, and it is not
a guarantee that nothing the user is ever told can be traced back to that source" —
applied to a source whose collection happens outside the boundary. ADR-0139 §3's
fourth clause already forbids presenting configuration state as part of a grant,
and this clause is that rule reaching one step further out, to a component
`grantable_sources` cannot even see.

**Configuration is not a grant, and here it is not even ours.** ADR-0093 §7's
clause — "Configuration is not a grant, and no surface may present it as one" —
holds with more force rather than less: `email_source_path` being set means an
operator pointed the hub at a file, and the fetcher running means an operator
started a process, and neither is a user act through a client (ADR-0097 §3). The
disabled-by-default rule (ADR-0093 §7) binds this reader unchanged, and §12's
default is `None`.

**One account, and the deferrals that would change that do not fire.** A grant
keys on a declared identity that "is not yet instance-distinguishing" (ADR-0097
§9a), and ADR-0093 §11 defers a source registry "at the third source" and an
instance-distinguishing identity "at the second instance of one source type". This
is the second source and the first instance of its type, so a second mail account
is not configurable and the deferrals stand untouched. That is a real limitation
and §14 records it as one.

### 10. The injection posture: ADR-0098 governs unchanged, and what email changes is volume rather than mechanism

> **Normative.** Every span the `EmailReader` draws from the store is **external
> content** under ADR-0098 §1 — the sender, the display name, the address and the
> subject alike — and every clause of ADR-0098 binds a consumer of it unchanged.

> **Normative.** Until ADR-0098 §12's externality-recoverable seam is ratified and
> implemented, the email source contributes to memory only through §5's envelope
> field set, and contributes to `CurrentContext` only through §6's two scalars.

> **Normative.** A lane rendering an email-derived span into a prompt owes ADR-0098
> §2 and §9's marked test for its assembler's own container syntax. This ADR adds
> spans to that obligation and discharges no part of it.

**#668 asks whether ADR-0098's posture suffices before email, and the answer is
that it suffices for what email contributes here — with the reason stated against
#668's own list rather than asserted.** #668 asks for five things and ADR-0098
rules on all five: provenance through the prompt (§2, non-forgeably), a band
ceiling on what external evidence may become (§4), instructions-are-data and the
no-authority-for-an-action rule (§3), detection explicitly not being the plan
(§6), and audit legibility (§8). Nothing in email changes what any of those
decides. Each is a **total** rule — a function of recorded origin, a band that is
a total function of `MemorySource`, a prohibition on a span — and none of them is a
rate, a threshold or a heuristic, so none degrades as the input grows.

**Three things email genuinely changes, named precisely so the fourth is
believable.**

- **Volume.** An attacker can send arbitrarily many messages. A crafted invite
  requires a calendar the attacker can write to; a crafted email requires an
  address.
- **Unsolicited reach.** Anyone who learns the address can put text on the box
  with no prior relationship, whereas a calendar invite implies a channel the user
  established.
- **Selection.** The attacker chooses arrival time and may retry indefinitely,
  which turns a probabilistic weakness into one they can grind at.

**What all three move is the probability that ADR-0098 §5's stated residual gets
exercised, and not the enforceability of anything.** §5's residual is precise:
"on the live chain of the Context, externality is not recoverable at all" — an
attacker's sentence reaches a durable belief through a plan rationale our own
model authored and the engine recorded truthfully, and "there is no field to
read". §5 argues that adding one is deferred on three grounds, of which the live
one is that ADR-0073 §4 wants it decided "with a producer in hand". **Nothing about
email makes that field obtainable**, so re-ruling §5 here would be re-arguing an
unobtainability with no new fact — and ADR-0098 §12 already carries the seam with
its trigger.

**So the honest move is the second clause above: bound what email may reach until
that seam exists, rather than re-decide a posture that has not become wrong.** The
narrowing is not caution added to ADR-0098 — it is ADR-0098 §6's own construction
posture applied to a new source. What §5 cannot bound is a *body* of arbitrary
attacker-composed prose reaching a model and steering it; an envelope is a sender
string, a subject string and two instants, so the payload an attacker gets to
place is a subject line inside a rendered sentence in the `ATTESTED` band, with
§4's ceilings and §3's data-not-instruction rule over it and the user able to see
and kill it (ADR-0073 §5). That is not a claim that a subject line is harmless. It
is a claim that the surface is small, fixed and legible, and that widening it to
bodies is a decision to take when there is something to recover externality with —
which is exactly the trade §14 records with its condition.

**And the narrowing is structural rather than remembered**, per §5's last clause:
the store the arrangement requires has no bodies in it. A lane that ignored the
prohibition would have to change the fetcher's contract to find the text.

**#668 does not close.** Its subject is the posture, ADR-0098 is the posture, and
this ADR neither ratifies nor amends it — it rules the posture sufficient for one
source's bounded contribution and records the residual it is relying on. #668's own
framing ("this wants an ADR-shaped decision **before the second reader lands**")
is met by ADR-0098 having landed; what stays live in it is ADR-0098 §12's seam,
which is tracked there.

### 11. This system makes no network call, and no credential enters it

> **Normative.** Nothing in `src/` opens a network connection for this source.
> `EmailReader` speaks no IMAP, POP or SMTP, resolves no host, and has no input
> but the store file and the clock.

> **Normative.** The account credential is the **operator's and the fetcher's**. It
> is not a `Settings` field, is not written to or read from `secret_store/`, is not
> passed to the hub by any means, and no `core` type carries it.

> **Normative.** ADR-0093 §11's networked-source deferral is untouched. A reader
> that itself spoke a mail protocol would engage ADR-0017 §1 and would owe that
> decision; this ADR does not reach it and may not be cited as having.

**This is the whole reason the arrangement is worth its awkwardness.** ADR-0093
§11 rules that a networked source "cannot be reached by changing a path to a URL",
because it "transmits a credential and a request, so it engages [ADR-0017] §1".
Everything in that sentence is true of talking to an IMAP server, and none of it
is true of this system, because the process that does it is not this system (§1).
What the hub does is open a file, which is what it already does for a calendar.

**The credential clause is written because the helpful mistake is obvious.** A
later lane looking at `secret_store/` and at an email source will see a natural
home for an IMAP password, and putting it there would move the network into the
hub by the shortest available path — the hub would then need to *use* it, which
means speaking IMAP, which is the deferral above. The credential staying outside
is not an inconvenience to be tidied up; it is what makes the boundary in §1 a
boundary rather than a diagram.

### 12. Configuration and figures, named here rather than left to the lane

ADR-0093 §5 invokes ADR-0074 §9.3's rule that a bounded default with no figure is
two conforming implementations diverging while each believes it conforms, so the
figures are named. **Seven fields, and the table is derived from this source
rather than copied from the calendar's nine** — which §3 is the argument for.

> **Normative.** `Settings` carries exactly these seven fields, with these
> defaults and these ranges, and refuses a value outside its range at load. The
> table is the clause and not an illustration of one: ADR-0089 §3 makes unmarked
> text incapable of supplying an obligation, so figures left beside a marked
> clause rather than inside it would name no default any lane owed — which is
> the divergence ADR-0074 §9.3 is invoked above to prevent, reintroduced by the
> marking.
>
> | Field | Default | Range | What it bounds |
> | --- | --- | --- | --- |
> | `email_source_path` | `None` | absolute path | the source; `None` is disabled |
> | `email_reader_interval` | `None` | `> 0` | the cadence; `None` is disabled (ADR-0093 §7) |
> | `email_window_past` | 7 days | `(0, 3650 days]` | how far back the clock-relative arrival window reaches |
> | `email_max_messages` | 2,000 | `[1, 2**63)` | framed messages in the store, and so proposals |
> | `email_max_bytes` | 8 MiB | `> 0` | the store read **before** parsing |
> | `email_read_timeout` | 10 s | `> 0` | the reader's deadline on its own read (ADR-0093 §7) |
> | `email_max_content_bytes` | 4 MiB | `> 0` | proposal content materialised across the whole read |

> **Normative.** A configuration with `email_reader_interval` set and
> `email_source_path` unset is refused at load with a `ConfigurationError`, on
> ADR-0093 §7a's rule for the equivalent pair.

> **Normative.** The caps are `email_max_bytes`, `email_max_messages` and
> `email_max_content_bytes`, named rather than counted. Each refuses rather than
> truncates, and exceeding any raises under ADR-0093 §8 (ADR-0093 §5).
> `email_read_timeout` is a deadline and not one of them; `email_window_past` is
> a window edge and bounds nothing.

> **Normative.** `email_max_messages` counts the messages the store's framing
> yields, counted **as they are framed** — before any header is interpreted,
> before the window is applied, and before §5's skip rule runs. A store yielding
> more than the cap raises, whatever the reader would later have made of them.

> **Normative.** The email source ships **disabled by default** — both nullable
> fields `None` — and the reason is ADR-0093 §7's: nothing may read a user's
> personal files because a default said so.

**Four of the seven fields are decisions rather than numbers, and a fifth
decision is a field that is not there.**

- **One window edge, not two.** A calendar is asymmetric because the future is
  what the assistant needs; a mailbox has no future, so `email_window_future` would
  bound nothing. The remaining edge may **not** be zero, for ADR-0093 §7a's reason
  applied unchanged: a zero-width window is a reader that reads nothing while
  reporting health. It is bounded above at ten years for ADR-0093 §7b's overflow
  reason — the ceiling makes an overflow unreachable from configuration alone, and
  §3's own saturation clause covers the case a clock can still reach.
- **No expansion budget.** `calendar_max_expansion` exists because one `VEVENT`
  can generate hundreds of thousands of occurrences, so neither the byte cap nor
  the entry cap bounds the work of finding them. A mailbox has no generator: the
  messages in the store are the messages, so the byte cap bounds the parse and the
  message cap bounds the output, and a third figure would bound nothing the first
  two do not.
- **`email_max_bytes` is separate from `email_max_messages` and is the one that
  must exist**, on ADR-0093 §7a's ordering argument unchanged: a message cap can
  only be applied after parsing, so a cap on messages alone lets a 2 GiB store be
  fully parsed before anything refuses it. It is enforced on the read itself, at
  most the cap plus one byte consumed (ADR-0093 §7).
- **`email_max_messages` counts framed messages rather than in-window ones, and
  the ordering is the point rather than the wording.** The obvious spelling —
  "in-window messages" — cannot be enforced, because deciding whether a message is
  in the window means reading its delivery header, which is the very step §5's
  skip rule turns on. A store of 2,001 messages none of which carries a valid
  `X-Assistant-Delivered-At` would then be skipped message by message and returned
  as a **successful empty reading**: a busted cap wearing the clothes of a quiet
  week, which is exactly what ADR-0093 §5's refuse-don't-truncate rule exists to
  prevent and exactly the ordering ADR-0117 §5 records the calendar taking, "so
  that a source that busts its cap cannot be turned into a successful 'your
  calendar is clear'". Counting at the framing is the only point before
  interpretation at which a message exists to be counted. It still bounds
  proposals, transitively and strictly, and it bounds the *work* besides — an
  over-large store is refused whether or not its messages parse. The cost is that
  a reader pointed at a large archive refuses rather than reading the recent tail
  of it; that is the loud direction, and the operator's remedy is to shorten the
  fetcher's retention or raise the cap, knowingly (ADR-0093 §5).
- **`email_max_content_bytes` bounds the output, which none of the others do.**
  A subject header may be folded across many lines, and 2,000 of them inside every
  other cap can still materialise more content than any consumer wants. It is a
  single accumulator across the read, checked before each proposal is
  materialised, exactly as `calendar_max_content_bytes` is and for the same
  reason.

**The default window is seven days rather than the calendar's one**, and the
asymmetry is deliberate: a calendar's past is wanted only so "this morning" stays
in view, while a mailbox's whole content is its past, and a window shorter than the
gap between two runs of a hub that is occasionally off loses mail permanently (§3).
Seven days is small enough to be a bounded payload of Tier 1 data — ADR-0093 §7a's
posture, "a bound nobody argued is a payload nobody measured" — and large enough
that the §3 loss needs a week of downtime to reach.

**The reader's identity is declared and is not in the table.** It is `"email"`,
never the account. ADR-0093 §7 and `Reader.name`'s own docstring use exactly this
source as the worked counter-example — a reader "names *itself* (`"calendar"`),
never the data it holds (`"alice@example.com calendar"`)" — and here the mistake
would be one keystroke away in a `Settings` field, which is why there is no field.

### 13. The contract surface owed, and what the implementing lanes owe

> **Normative.** The lane implementing this ADR adds this surface to `core` and
> no other. It is a breaking change under golden rule 5 and lands after this ADR
> merges.
>
> - **`core/types.py`** gains `EmailFacet` and the optional field
>   `CurrentContext.email` (§6).
> - **`core/types.py`** widens `SourceReading.facet` to
>   `CalendarFacet | EmailFacet | None`, made an explicitly **discriminated** union
>   on a new `kind` field, and adds `kind` to `CalendarFacet` with its tag as the
>   default (§6, ADR-0096 §5). **This is a change to a ratified type and is the one
>   place this ADR touches an existing shape**; it is additive and defaulted, so
>   every existing construction site stays valid, which is ADR-0008 §1's pattern and
>   the property ADR-0096 §5 was counting on.
> - **`tests/core/test_facet_coverage.py`** grows a second property beside the
>   reserved-name one it already enforces for `source`, `read_at` and `as_of`: that
>   every concrete facet type declares a `kind` whose `Literal` value is distinct
>   across the union, and that no facet gives the name a payload meaning (§6). It is
>   the file-level check ADR-0096 §1 chose over a convention held by review, applied
>   to the field that makes the union resolvable.
> - **`core/config.py`** gains §12's seven `Settings` fields with their ranges and
>   the load-time refusal.

**Both work orders in this section sit inside marked clauses, and so does §12's
table, because otherwise this ADR obligates almost nothing it was written to
obligate.** §15 puts this document in ADR-0089's marked regime, where unmarked
text "never supplies an obligation" — and §13 carried no mark at all, so the
`core` surface, the drivers, the fetcher documentation and every owed test bound
nobody, while §12 named its caps in a marked clause and left all seven figures in
a table beside it. That is exactly the case ADR-0089 §3's second clause names:
"Where the surrounding argument is what establishes *that* an obligation exists,
or how far it reaches, the marking is not finished." A work order is the
obligation rather than the argument for one, so it goes inside the mark; the
paragraphs around it say what the clauses mean and stay outside. **ADR-0093 §7a's
equivalent table is unmarked and is not thereby defective** — its own ADR governs
it, nothing here reaches it, and §15 records that no note is owed on it.

**No new Protocol is minted and no triad is owed**, and that is worth stating
because a lane may reach for one by analogy. `Reader` already describes this seam
member for member, and ADR-0095 §3 anticipated this exact lane when it argued the
triad's value: "A synced-vault reader and a co-located maildir reader are two
implementations of one behaviour, which is precisely and only what a shared
conformance suite is for … Two implementations is the condition under which that
suite starts paying." This is that second implementation, so the obligation it
carries is to **pass** the existing suite, not to write one.

> **Normative.** The lanes implementing this ADR owe each of the following, and
> the test list is part of the obligation rather than advice about it.
>
> - The `EmailReader` concrete in `readers/`, conforming to the shared suite, with
>   ADR-0093 §7's whole discipline held rather than re-derived: the non-blocking
>   open, the descriptor check, the byte cap on the read itself, the whole read off
>   the event loop on a terminable worker the reader owns, the deadline, the
>   one-outstanding-worker reservation released on the worker, no lifecycle method,
>   and `ReaderError` with a **payload-free message** carrying the identity and the
>   failure's class and never the path.
> - The `context/` adapter contributing §6's facet, gated on a live `FACET` grant.
> - The ingestion wiring, gated on a live `INGEST` grant, and the scheduler job as
>   an `Engine` call holding no reader (ADR-0083 §8).
> - **The composition-root registration in `app/`**, which is what makes §9's
>   first clause true of a running hub rather than of a fixture: with
>   `email_source_path` set, the source is offered by `grantable_sources()` under
>   the reader's declared identity `"email"` and both consumers above are wired
>   into the engine; with it unset, none of the three is registered at all,
>   because a source with nothing to read is "I/O on personal data in exchange for
>   nothing" — which is what §9 already binds this reader to ADR-0093 **§7's**
>   disabled-by-default clause for, and §12's default is `None`. This is named as
>   its own deliverable rather than left implicit in the two above because they are
>   *objects* and this is the wiring that puts them in the engine — a different
>   thing to omit, and the one omission that leaves a fully conforming
>   `EmailReader` a module nothing calls.
> - **Deployment documentation for the fetcher** — that it writes header blocks and
>   no bodies; that it writes exactly one `X-Assistant-Delivered-At` per message in
>   the closed RFC 3339 subset §5 fixes — upper-case `T` and `Z`, second `00`–`59`,
>   at most microsecond precision, and a determinate offset that is never `-00:00`
>   — from the server's own record, after stripping
>   every copy the message carried; that it emits no header value containing a bare
>   line break and escapes the format's separator; that it replaces the store by
>   `rename(2)` on the same filesystem; that its retention exceeds the reader's
>   window; and that its credential never enters the hub. This is documentation and
>   not `src/`, and §1's second clause is why: the fetcher is not ours to ship.
> - Tests for the clauses a lane can satisfy in prose and breach in code —
>   fifteen, each named by the breach it catches. The list is scoped to **every
>   deliverable named above** and not to the reader alone, which is stated because
>   for several rounds it read as the reader's list while the `context/` adapter,
>   the ingestion wiring and the widened type owed nothing at all. A deliverable
>   this section names owes its item here; an omission is a defect rather than a
>   scoping choice.
>
>   - **The body never leaves the reader (§5).** A message carrying a body still
>     yields its envelope proposal and is still counted in the facet, while no byte
>     of that body reaches that proposal, the facet, or any other value leaving the
>     reader. Both halves are asserted, because a test checking only the sentinel's
>     absence is passed by a reader that drops the message entirely.
>   - **The window's edges are asserted, not implied (§3).** Against a fixed clock,
>     a message delivered exactly at `read_at - email_window_past` **is** proposed
>     and a message delivered exactly at `read_at` is **not** — §3's window is
>     closed at the bottom and open at the top, and the ADR states that once. §6's
>     `arrived_in_window` is asserted beside the proposals in both cases, because a
>     reader can decide membership correctly and count it wrongly, and
>     `covers_from` is asserted equal to the lower edge itself. The lower edge is
>     the direction that matters: a reader admitting only `lower < delivered_at`
>     loses the edge message **permanently** rather than late, because by the next
>     run the window has moved past it and §3 leaves no cursor to notice.
>   - **The window arithmetic saturates rather than raising (§3).** With a
>     `read_at` close enough to the minimum representable instant that
>     `read_at - email_window_past` is not representable, the read **completes**:
>     the window's lower edge and `covers_from` are both the minimum representable
>     instant, and nothing raises. §12's ten-year ceiling makes this unreachable
>     from configuration alone, so it is reachable only from configuration *and* a
>     clock — the case a lane that builds the window as a bare subtraction never
>     runs and never sees, whose failure escapes ADR-0093 §8's two outcomes
>     entirely rather than arriving as a `ReaderError`. There is no upward
>     direction to test: email has the one edge, and `read_at` is representable by
>     construction.
>   - **An unusable delivery header is skipped, never defaulted (§5).** A message
>     with zero, two, or an unparseable `X-Assistant-Delivered-At` is skipped
>     rather than dated by any fallback.
>   - **A *parseable* value outside §5's closed subset is skipped on the same
>     terms**, tested in both directions of the seam, because the accept/reject
>     boundary has to be the subset rather than whichever library a lane reached
>     for. A space separator, a comma fractional separator, an offset carrying
>     seconds, an omitted `SS` and a `+0000` written without its colon are each
>     **accepted** by `datetime.fromisoformat`, so a reader that delegates
>     acceptance to it passes the test above and still admits what §5 excludes. A
>     lower-case `t` or `z` and a leap second are each **accepted** by a parser
>     conforming to RFC 3339 while `fromisoformat` rejects them, so the skip is
>     owed on §5's terms rather than as a side effect of the stdlib's narrowness.
>     The **accepting** direction is asserted in the same test and is not
>     redundant: a value sitting on each of the subset's own boundaries — second
>     `59`, one fractional digit and six, an upper-case `Z`, and a `+00:00` that
>     is the excluded `-00:00`'s mirror — is proposed. Every skip clause in this
>     list is satisfied by a reader that skips everything, so without this
>     direction the subset is pinned only from outside and its inside is a
>     lane's guess.
>   - **`Date` is never a delivery instant (§5).** A store whose messages carry
>     only a `Date` header proposes nothing.
>   - **Membership is decided on the delivery instant while `reported_at` carries
>     `Date`, with both present and disagreeing (§5).** A message whose `Date` is
>     far outside the window but whose `X-Assistant-Delivered-At` is inside it
>     **is** proposed; a message whose `Date` is inside the window but whose
>     delivery instant is outside it is **not**; and in the proposed case
>     `Attestation.reported_at` is the `Date` and not the delivery instant. §5
>     separates the two clocks as a security property before a modelling one — a
>     sender who can move the window by writing a future `Date` holds a message in
>     every window there will ever be — and every other test in this list is
>     passed by a reader that reads both fields into one variable, because on
>     honest mail they agree.
>   - **`Date` is required and singular, and the delivery instant is never
>     substituted for it (§5).** A message with a valid in-window
>     `X-Assistant-Delivered-At` but no `Date`, or two `Date` headers, or a `Date`
>     **the reader cannot resolve to a determinate instant**, is **skipped** — not
>     proposed with the delivery instant standing in as `reported_at`, which is
>     the substitution a reader reaches for precisely because it has a usable
>     instant in hand. That third arm is tested at §5's predicate rather than at
>     the two values §5 offers to illustrate it, because they are not the whole of
>     it and are the easier half: `-0000` and an absent zone both *parse* and then
>     resolve to nothing usable, while a malformed or impossible `Date` does not
>     parse at all — so a lane that handles only the illustrations reaches either
>     the fallback or an escaping parser error, and the second breaches §5's rule
>     that a skip raises nothing while every other test here still passes. The
>     delivery-header item above already reads its own clause this way, and the
>     two are the same rule. The
>     converse is asserted in the same test so the skip is not quietly generalised
>     to every field the rule does not reach: a message with **no** `Subject` and
>     a message with **two** both still propose, with the subject empty in each
>     and no selection made among the candidates, and the sender is asserted on
>     the same terms. The duplicate is the case a lane breaches while passing the
>     absent one, because `email.message.Message`'s own mapping returns the
>     *first* occurrence of a repeated header and says nothing — which is exactly
>     the selection §5 forbids, reaching the opposite outcome from the duplicate
>     `Date` immediately above it.
>   - **§12's table is refused where §12 says it is, and the calendar's is where a
>     lane gets it wrong (§12).** Three directions, each named: both nullable
>     fields default to `None`, so a fresh install reads no mail; an
>     `email_reader_interval` set with `email_source_path` unset raises
>     `ConfigurationError` at load; and a figure outside its stated range is
>     refused at load. The range worth the test is `email_window_past`'s **open**
>     lower bound — `calendar_window_past` may be zero and
>     `tests/readers/test_calendar_settings.py` asserts that it is accepted, while
>     this one may not be, so a lane that reaches for the neighbouring field
>     declaration inherits a `ge=0` and ships §12's reader that reads nothing while
>     reporting health. The only other item here that observes the configuration
>     layer is the registration one below, and it reads whether a value is *set*
>     rather than whether the layer refuses one.
>   - **Every cap §12 names owes a refusal test, one each (§12).**
>     `email_max_bytes`, on a store larger than the cap, refusing on the read
>     itself rather than after parsing; and `email_max_content_bytes`, on an
>     in-window message whose folded `Subject` materialises past a deliberately
>     small aggregate budget, asserted to fail **before** the over-budget proposal
>     is materialised. A reader that never charges the content accumulator, or
>     enforces the byte cap only after reading the whole store, passes every other
>     test in this list. `email_max_messages` is the third cap and its refusal is
>     the item below, which pins the cap's *ordering* in the same assertion. The
>     rule is stated per cap rather than per figure so that a cap added later
>     arrives owing its test.
>   - **The cap is applied at the framing (§12).** A store of
>     `email_max_messages + 1` framed messages **none** of which carries a valid
>     `X-Assistant-Delivered-At` **refuses** rather than returning a successful
>     empty reading. This is the cap's *ordering* rather than its figure, and it is
>     the one §12 property every other test in this list passes while breached: an
>     implementation that skips invalid messages first and counts what survives
>     satisfies all fourteen others and still turns a busted cap into a quiet week.
>   - **No grant, no read — and the whole of ADR-0097 §5a's lifecycle, on the
>     adapter and on the ingestion path separately (§9).** §9's second clause is
>     "not resolved, not opened, not parsed", so the first thing asserted is a spy
>     reader's **call count** rather than the reading it returns. That is the entry
>     case and not the item: what the two drivers this ADR adds owe is the set
>     ADR-0097 §5a's clauses form, which
>     `tests/context/test_calendar_context_source.py` and
>     `tests/orchestration/test_ingestion.py` already carry case by case — no
>     grant, and a live grant naming the other scope, each leave the count at
>     zero; a `live()` that raises **before** the read opens nothing and lets the
>     `GrantError` propagate rather than becoming a silent empty result; a
>     revocation landing between the gate's check and `read()` returning
>     **discards** the reading, with the count at one and nothing proposed or
>     contributed from it; an unanswerable **re-check** discards it on the same
>     terms; and the granted case reads, without which the refusals prove nothing.
>     The two paths refuse differently and both are asserted: an ungranted
>     ingestion pass raises `SourceNotGrantedError` and is never a successful pass
>     (ADR-0097 §5), while an ungranted facet is simply **absent** and says nothing
>     about why, and on the facet path a `GrantError` propagates from the adapter
>     with the assembler being what leaves the facet absent. ADR-0097 §5a states
>     these as obligations on a driver rather than as owed tests; they are owed
>     *here* because this ADR is what adds the drivers, and an item naming only the
>     entry case would ship a gate that authorises the read and then ignores the
>     revocation landing inside it. This is the breach with the worst consequence
>     in the document, and every other test in this list passes while it happens:
>     most never leave the reader at all, and the two below that do assert the
>     **granted** path, where a revocation landing inside the read never arises.
>     The calendar's two modules are the
>     shape to follow and are not coverage: this is new wiring and they do not
>     reach it.
>   - **A granted read's facet reaches the field the adapter was wired for, and no
>     other (§6).** Under a live `FACET` grant, an adapter handed a reading
>     carrying an `EmailFacet` contributes it under `email` and the assembled
>     `CurrentContext.email` **is** that facet; a reading whose facet is of some
>     other type raises `ContextError` rather than being contributed under either
>     field. The **accepting** direction is the load-bearing half, and is why this
>     is a separate item from the one above rather than a clause inside it: every
>     assertion there is a refusal or a call count, so an adapter that reads under
>     a live grant and then contributes nothing — or contributes the facet under
>     `calendar` — satisfies the whole grant lifecycle while
>     `CurrentContext.email` is permanently absent. The wrong-key shape is not
>     hypothetical: the calendar adapter in `src/ai_assistant/context/sources.py`
>     writes its field as a literal in the mapping it returns, so a lane copying
>     that module and changing only the reader ships it. §6 records ADR-0096 §5's
>     contribute-and-raise clause acquiring "a second instance here for the first
>     time, which is exactly the wiring bug it was written against" — and without
>     this item that observation is made in prose and tested nowhere.
>     `tests/context/test_calendar_context_source.py` carries the shape for the
>     calendar and, as with the item above, is not coverage for this one.
>   - **The configured source is registered and the unconfigured one is not
>     (§9).** With `email_source_path` set, `grantable_sources()` offers the
>     source under the identity `"email"`, and the built engine reaches **both**
>     consumers this ADR adds — the facet adapter and the ingestion driver; with
>     it unset, none of the three is registered. This is the only item that
>     observes the composition root, and it is owed because §9's first clause —
>     granted, revoked, reported by `standing_grants` and rendered by a client
>     "exactly as every other source is" — is satisfied by no test of a reader,
>     an adapter or a driver a fixture handed to itself. Every other item here
>     constructs its subject directly, so every one of them passes on an engine
>     that wires none of them, and the reader this ADR spends most of this list
>     specifying is then a module nothing calls. `tests/app/test_composition.py`
>     carries the calendar's cases at this exact boundary — including the
>     unconfigured direction, which is the half a lane omits because a hub with
>     no mail configured looks like nothing to assert — and, as with the two
>     items above, is not coverage for this one.
>   - **The facet union discriminates at validation, not by declaration (§6).** A
>     tagged calendar payload and a tagged email payload each resolve through
>     `SourceReading` to their own type; a payload carrying `kind: "email"` **and**
>     calendar-shaped fields resolves to `EmailFacet`; and a payload carrying no
>     `kind` is **rejected** rather than inferred, which is the half §6 spends a
>     paragraph on because the field's default cannot rescue it. The static
>     property `tests/core/test_facet_coverage.py` gains is necessary and not
>     sufficient: it proves each concrete type declares a distinct `Literal`, and
>     an ordinary union satisfies that while the annotation carries no
>     `Field(discriminator="kind")` and pydantic resolves by inference. That is
>     §6's own stated defect — "two facets that differ only in a scalar could parse
>     as each other, quietly" — surviving the check written against it.
>     `MemoryRecord` is the corpus's worked shape for the annotation.

### 14. Deferred, by name, each with the condition that fires it

- **Message bodies, in any form — full, truncated, summarised or embedded.**
  Fires when ADR-0098 §12's externality-recoverable seam is ratified and
  implemented, which is what §10's second clause conditions on. A lane taking it
  owes the byte and tier consequences §5 enumerates, not only the injection one.
- **Attachments, and a reader over them.** #664's `Docling` candidate is the
  natural home and the batch that briefed this lane deferred it explicitly. Fires
  with that lane, and it inherits the body deferral above rather than routing
  around it.
- **`To:`, `Cc:` and "was this addressed to me".** Fires when the system holds the
  user's own addresses as something other than a guess — which is a user-model
  question, not a reader's.
- **Threading and conversation reconstruction.** Fires with a consumer that needs
  it, and it must argue past ADR-0093 §2's "a reader infers nothing" or move the
  work to a producer that is allowed to infer.
- **A second mail account.** Fires with ADR-0093 §11's source registry (at the
  third source) and its instance-distinguishing identity (at the second instance
  of one source type). Neither fires here (§9).
- **A coverage, an extent, and therefore absence-demotion for email.** Fires only
  if an arrangement exists whose completeness over an interval the reader can
  verify **without** the fetcher's testimony. §7's second clause forecloses the
  cheap route deliberately, and this deferral is recorded in the expectation that
  its condition may never be met.
- **A self-delimiting store format the reader can frame without trusting a
  writer.** Fires with the body deferral above, and would fire early if a
  deployment is ever found that cannot hold §5's envelopes-only requirement. §4's
  splitting hazard is bounded rather than closed today, and it is closed by
  construction the moment the store stops being delimited in-band; the trade is
  weighed in Alternatives considered.
- **Event-driven reading.** #664 lists `watchfiles` for "the hub noticing fetcher
  writes". This reader is scheduler-driven per ADR-0093 §6. Fires with a decision
  about read cadence, which is a different question from this source and would
  reach every reader.
- **Sending email.** An actuator. ADR-0017 §1 and ADR-0021 §6 govern, a read-only
  seam cannot reach it, and it is named here only so nothing reads this ADR as a
  step toward it.

### 15. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 puts the judgement in the later ADR's text, where it is reviewed, and
fixes the test: *would a reader holding only the earlier ADR now act differently,
or read one of its clauses more widely than it now holds?* Applied clause by
clause to the ADRs this one leans on hardest, **the answer is that no earlier
ADR's `Status` line is edited and no dated note is owed on any of them.** Every
change here is a stacked addition or a deferral discharged on its own terms.

- **ADR-0093 §7** — the regular-file clause. §2 supplies a source that satisfies
  it as ratified. A reader holding only §7 opens the store, checks the descriptor,
  finds a regular file and proceeds — identically before and after. **Addition,
  and #649 is narrowed rather than answered by a supersession.**
- **ADR-0093 §5** — the no-cursor clause and its out-of-scope sentence. This is
  the clause where the classification has to be made carefully rather than
  asserted, because ADR-0093's own header records ADR-0110 losing this argument on
  §4. The distinction is that ADR-0110 put a case *inside* a rule §4 excluded,
  narrowing it by exception; §3 puts nothing inside §5. §5's sentence predicates on
  a source that **cannot be re-read in full within its bound**, and §3's source
  can, so the sentence is as true after this ADR as before and a reader applying
  its predicate reaches this ADR's answer. The dash-list naming "a mailbox" is
  illustration: both §5 and §11 lead with the bolded predicate and put the
  examples after a dash, and §11 states the operative rule in its own words — "§5
  scopes this contract to re-readable sources". **Addition.** The no-cursor
  prohibition itself is not merely unamended, it is restated and bound in §3's
  first clause.
- **ADR-0093 §11's fifth deferral** — "A source that cannot be re-read in full …
  and therefore the cursor." This ADR **discharges** it, and a discharge is not a
  supersession: §11 defers work and qualifies no rule, and its own entry says such
  a source "owes its own decision". The precedent is ADR-0096 §4 on ADR-0093 §7a's
  reserved state — "Nothing in §7a is edited or narrowed — its clause names the
  event that ends the reservation, and this ADR is that event." **Addition.**
- **ADR-0093 §7a** — its unmarked prediction that a mailbox's dimensions "would
  not be a time window". Unmarked text in a marked ADR supplies no obligation
  (ADR-0089 §3), so there is no clause to fail the test. §3 answers it in text so
  the disagreement is legible. **No record owed, and none available.**
- **ADR-0093 §4** — attested beliefs, never an episode, never an absence. §5
  proposes in the `ATTESTED` band and §7 declares no coverage, so §4's absence
  refusal binds this reader in its **unnarrowed** form rather than in ADR-0110
  §3's exception. Nothing is read more widely. **Addition, and the narrowest
  possible use of a clause that has an exception available.**
- **ADR-0096 §1 and §6** — one optional `CurrentContext` field per facet, every
  facet a `ContextFacet`, no entry text in the calendar facet. §6 adds a second
  facet in exactly that shape and states the no-text rule for its own payload.
  ADR-0096 §6's sentences are about the *calendar* facet and stay true of it. §6's
  reservation of `kind` extends ADR-0096 §1's reserved-name rule to a fourth name
  by the same argument that section makes for the first three. **Addition.**
- **ADR-0096 §5** — the `facet` field, its widening and its discriminator. §6
  widens the annotation and makes the union discriminated because **§5 instructs
  the later facet ADR to do exactly that**, at the condition §5 names ("when a
  second concrete type joins that annotation"). Doing what a clause instructs is
  not amending it: a reader holding only ADR-0096 §5 and confronted with a second
  facet reaches §6's answer, and every sentence of §5 stays true — including its
  three clauses this ADR does not touch, which §6 records as binding unchanged.
  Adding a defaulted `kind` to `CalendarFacet` is the mechanical consequence §5
  called "one more line in the change that ADR authorises". **Addition, and a
  clause discharged at its own stated trigger.**
- **ADR-0097 §1, §2, §5 and ADR-0133 §1** — the grant model. §9 adds a source to
  it and adds no member, no mechanism and no exception. §9's fourth clause is a new
  obligation on a *surface*, stated about a component ADR-0097 could not see; it
  contradicts no sentence of ADR-0097 or ADR-0133, both of which are silent about
  anything outside the process. **Addition.**
- **ADR-0139 §3** — what a client may present. §9's fourth clause is §3's fourth
  clause read one step further out. §3's own sentences — about configuration state
  and about whether a read happened — are untouched and still bind. **Addition.**
- **ADR-0098** — the whole of it. §10's first clause enrols this source's spans in
  §1's class, which §1 already does by its own terms ("Membership of the class is
  decided by **recorded origin**"). §10's second clause bounds what *this source*
  contributes and imposes nothing on any consumer of ADR-0098. No ceiling is
  relaxed, no clause is narrowed, and §5's residual is cited as it stands rather
  than re-argued. **Addition.**
- **ADR-0110 §2 and ADR-0117 §2, §5, §6, §8** — coverage, extent, and what
  generalises. §7 declines both, which every one of those sections expressly
  permits: ADR-0110 §2 makes coverage optional and its absence meaningful,
  ADR-0117 §6 rules an unexpressible extent as none, and §8 rules that a source
  declaring none "is not thereby deficient". **Addition, and §8's judgement
  exercised rather than stretched.**
- **ADR-0117 §5 and #837.** §8 states the relation and rules on nothing. #837 is
  an open issue and not an ADR; nothing here is a record against ADR-0117.

- **ADR-0089 §3 — applied to this ADR's own marks, and reaching no other ADR.**
  §12's figures table and §13's two work orders sit inside marked clauses,
  because a marked ADR that leaves its defaults and its owed tests in unmarked
  prose obligates neither, which is §3's second clause failing on this document
  rather than on any earlier one. It is this ADR finishing its own marking and
  not a rule proposed for others: ADR-0093 §7a's table is unmarked, nothing here
  edits or narrows it, and a reader holding only ADR-0093 acts exactly as
  before. **No record owed, and none available.**

**This ADR is marked under ADR-0089** and is in the marked regime: its unmarked
prose supplies no obligation and exists to determine what the marked clauses mean
(ADR-0089 §3). It follows the practice ADR-0098 §11 records — marks stated while
#622's question about ADR-0089's own status is open — and resolves nothing there.

**This branch touches one file**, which is the mechanical consequence of the
paragraphs above.

## Consequences

- **The email source is buildable against a settled contract.** No Protocol
  changes, no triad is owed, and `Reader`'s conformance suite gets the second
  implementation ADR-0095 §3 said it was waiting for.
- **The facet union becomes discriminated, which is the second facet's bill and
  not this source's.** ADR-0096 §5 conditioned it on a second concrete type
  arriving, and one has. Every later facet pays a smaller version: a `Literal` tag
  and a line in the annotation.
- **#649 stops blocking email and stays open for what it is actually about.** The
  single-file arrangement satisfies ADR-0093 §7 as ratified, and it is chosen on
  three correctness properties rather than on compliance, so the choice survives
  any later widening of §7.
- **ADR-0093 §5's mailbox deferral is discharged without a cursor**, and the
  reason is transferable: the unboundedness sits with the fetcher, and the reader's
  source is a re-readable file. The next source that looks unbounded should be
  asked the same question before it is granted durable state.
- **Email is never absence-demotable, permanently in practice.** That is the
  correct answer for a completed-event source and it is also the one that stops a
  disk-space setting from retiring beliefs. It costs the ability to notice that a
  message was deleted, which is not a fact this system wants.
- **The injection surface for email is a subject line and a sender string.** That
  is small, fixed, legible, and bounded by ADR-0098's existing construction rules;
  it is not zero, and §10 says so rather than claiming a prevention. The one way
  body text reaches a proposal is §4's in-band splitting hazard, which needs two
  deployment requirements to fail together, is skipped in its careless form and
  bounded in its careful one, and is **stated as a residual rather than closed** —
  §14 carries the format change that would close it.
- **Two clauses are conditional on the fetcher and say so.** The snapshot property
  (§2) and the envelopes-only store (§5) are requirements a deployment meets, not
  facts the reader can check, and each is paired with what the reader does anyway.
  A clause the reader would have to breach to function is worse than no clause,
  and this ADR carries none.
- **The credential and the network stay outside the hub**, which keeps ADR-0017
  §1 and ADR-0093 §11's networked-source deferral untouched and keeps `secret_store/`
  free of an account password a later lane would otherwise have put there.
- **The operator owns a small script.** ADR-0095 preferred co-located fetchers
  partly to avoid owning a connector, and §2 gives back a dozen lines of that in
  exchange for atomic replacement. The protocol work — the expensive, drifting
  half — still belongs to `imap-tools`.
- **The blindness is named.** A stopped fetcher looks like a quiet week, and
  nothing in this system can tell the difference. §7's refusal to declare coverage
  is what keeps that from becoming a wrong belief, and monitoring the fetcher is
  the operator's.
- **#668 does not close and #649 does not close.** #668's subject is ADR-0098's
  posture and its live residual is ADR-0098 §12's seam; #649's is whether a reader
  may read a directory. Both are recorded here with what changed.

## Alternatives considered

- **Read a maildir and supersede ADR-0093 §7.** The route the batch's brief
  anticipated. Rejected because #649's three consequences are real and only one of
  them is about the descriptor check: the byte cap acquires a per-file-versus-summed
  question, §7b's single acquisition instant has no meaning across a directory walk,
  and mid-read mutation is unclosable — maildir's atomicity is per file, and the
  reader reads a set. Paying a partial supersession of a ratified clause to acquire
  three problems, when a `rename(2)` closes all of them, is the wrong trade. #649
  keeps the question for a source that has no alternative.
- **Read the account directly over IMAP.** Rejected on ADR-0093 §11, which
  forecloses it in as many words: a networked source "cannot be reached by changing
  a path to a URL" and owes its own decision engaging ADR-0017 §1. It would also
  put a credential in the hub (§11) and put protocol drift in `src/`.
- **Give the reader a cursor over an append-only store.** The shape ADR-0093 §5
  and §11 assumed a mailbox would need. Rejected because it buys nothing: the
  message a cursor would reach is gone from the store, removed by the retention the
  fetcher enforces, so the durable state would record a position in a file somebody
  else rewrites. §3 argues it in full.
- **Declare a coverage from the fetcher's retention setting.** Tempting because it
  is one configuration field away and would make email absence-demotable. Rejected
  twice over: it is a claim about the account made on testimony from outside the
  read, which ADR-0110 §2 forbids in its own words; and if it worked it would retire
  every email belief one retention period after it was proposed (§7). §7's second
  clause forecloses it explicitly rather than leaving it to be re-tried.
- **Propose from message bodies now, with ADR-0098's ceilings as the bound.**
  Rejected on ADR-0098 §5's own residual: the ceilings bound what a *proposal*
  becomes and do not bound a steered model's plan rationale, and §5 says externality
  is "not recoverable at all" on that chain. Deferring bodies until §12's seam
  exists costs a capability; shipping them costs a bound nobody can state. §14
  carries it with the condition.
- **Carry the subject in the facet.** Rejected on ADR-0096 §6's ground and one
  more: `CurrentContext` reaches every prompt, the assembler that would escape it
  does not exist yet (#672), and a subject line is attacker-chosen text. Two scalars
  need no escaping at all.
- **`has_new_mail: bool` instead of a count.** Rejected for ADR-0096 §6's
  `busy: bool` reason: deciding what counts as *new* is a judgement about the user's
  attention, and the reader holds no read/unread state and may not infer one.
- **Key the window on the `Date:` header.** Rejected because it is the one clock in
  the message the sender controls, so a sender could hold a message in every future
  window or keep it out of all of them. The delivery instant the store records is
  not attacker-set, and §5 keeps the two apart as two facts rather than choosing
  between them.
- **A length-prefixed store the reader can frame unambiguously**, instead of an
  in-band-delimited mbox. It would close §4's splitting hazard by construction
  rather than by requiring two deployment properties to hold together, which is
  the stronger form of argument this ADR uses everywhere else. Rejected on
  balance, and it is the closest call here: it abandons stdlib `mailbox` — the one
  half of #664's premise that is doing real work, since the format would then be
  ours to define, version and parse — and §5's envelopes-only requirement already
  removes the body a separator hides in, so the framing would be buying a
  guarantee against a hazard that needs a *second* requirement to fail first. §14
  records it with the condition that would change the balance: a store that must
  carry bodies.
- **Take the first `X-Assistant-Delivered-At` when a message carries several**,
  rather than skipping. Rejected because it makes a forged header *work* wherever
  a fetcher's strip fails — the attacker writes theirs above the fetcher's, and
  ordering decides membership. Skipping costs an attacker their own message and
  costs an honest deployment nothing, because an honest fetcher writes one.
- **Use `Message-ID` as the record id.** Rejected on ADR-0092 §6, which rules that
  an import proposes "each record at an id it mints, opaque to the source" and may
  never use the source's own key. §4's third clause states it for this source
  because the header is unusually inviting.
