# 351. An input carries the parties whose words it is, and outside content, authority and a support's holder follow from them

- Status: Partially superseded by ADR-0356 (§5:7, for the work's own relayed stimulus alone: planning is shown its words, marked relayed) and ADR-0361 (§3:1's table and §8:5, each in the addition alone: Approvals' inputs carry empty parties, and an input with empty parties is left out of the reading over an activation's inputs)
- Date: 2026-10-25
- Scope: what an input records about whose words it carries, beside who handed it in. An input's **parties** (§2), how each kind of channel sets them (§3), the author kept apart (§4), what follows from the parties: outside content and how a reader attributes an input, with understanding's **relay mark**, that an input carries words its sender did not write themselves, which only lowers what follows (§5), authority (§6), and a support's holder and origin (§7). The retirement of `InputOrigin` and how every reader of it moves over (§8), the upgrade of what is stored (§9), the code it binds and its lanes (§10, §11). Audience, identified people and per-part outside marks are not decided here (§12).
- Dependency: [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md), [ADR-0284](0284-an-episode-is-the-experience-of-processing-its-activation.md), [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md), [ADR-0323](0323-a-telegram-chat-with-the-owners-bot-is-a-line-to-the-assistant-and-connecting-it-approves-what-the-line-carries.md), [ADR-0328](0328-a-memory-is-a-statement-resting-on-supports-its-standing-is-computed-from-them-and-every-change-to-it-is-an-operation-citing-one.md), [ADR-0332](0332-activations-run-side-by-side-across-places-and-one-at-a-time-within-one-a-new-input-joins-the-running-activation-until-it-acts-and-a-place-waits-a-moment-before-it-starts.md), [ADR-0345](0345-a-memory-records-who-holds-it-when-it-lapses-what-it-is-for-and-whom-it-is-about-and-its-producer-places-it-among-what-is-stored.md), [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md), [ADR-0349](0349-a-place-is-only-what-caused-an-activation-a-stop-is-reached-three-ways-running-work-is-shared-by-reading-it-and-the-newest-absorbs-what-it-continues.md) and [ADR-0326](0326-a-persons-memory-carries-across-every-upgrade-each-schema-change-ships-its-migration-and-a-fresh-data-directory-is-the-owners-ruling.md), as their status lines leave them; and [ADR-0350](0350-every-spawn-is-a-scheduled-task-written-into-the-task-scheduler-whose-sensor-starts-it-when-it-comes-due-and-the-task-manager-is-the-one-way-in-from-outside.md), the Task Scheduler, whose `assistant` origin is this decision's stand-in, as their status lines leave them.
- Authorization: the owner decided the design in the controller walk of 2026-10-25. Their words, verbatim: "lets make it a seperate ADR. I agree that the axes are diffrent because hearing mom say something is different than mom emialing something because moms email could have been compramised. I just want to fully understand the cut between the axes. I also think that the origin users set should match the belief holders set very similarly, since that will inform the other set right?" and "observer coordinator is done, start drafting it." This decision writes that design down and settles only what it leaves open, each such point named where it is settled. The owner then reviewed this draft. They added understanding's relay mark: "One thing that could help the pasted content is to allow understanding to decrease authority in some scenarios" (§5:6–§5:13). They kept authority all or nothing per input for now: "for now I think all or nothing is fine, but eventually I think there can be levels to authority" (§6:1, §12). They confirmed the same class for a join and a takeover (§8:5), and asked "the attribution is fully mechanical and done by the sensor, right?", which it is (§2:8, §5:8). The dispatcher assigned 0351. Ratifying it is the owner's, after the owner's own review (§1:1).
- **Contract-surface decision, and a breaking change under golden rule 5.** It changes `core/types.py`: `InputOrigin` retires (§8:1); `RecordedChannelTrigger` and `RecordedInputMessage` gain their parties (§2:1, §2:6); `EpisodeProjection` carries the parties and the relay mark in place of the origin (§8:4); `StatementPart` gains one member (§3:7); `ProposedActivationUnderstanding` and `ActivationUnderstanding` gain the relay mark, `JoinedInput` its record of one a takeover brought, and `EpisodeProcessingRecord` its validators (§5:10, §5:14, §10:4). It changes `core/channel_validation.py`'s declarations (§3:1) and `support_holder`'s rule (§7). No `Protocol` member changes. The episode store ships an upgrade (§9), and `PROTOCOL_VERSION` advances (§10:3).
- **Partially supersedes**, in the clauses §13's first table names: ADR-0098, ADR-0276, ADR-0284, ADR-0292, ADR-0306, ADR-0323, ADR-0328, ADR-0332, ADR-0345, ADR-0349 and ADR-0350.
- Partially superseded: 2026-10-30 by ADR-0356 — §5:7, for the work's own relayed stimulus alone, by the owner's ruling on [#3515](https://github.com/leonapivato/ai-assistant/issues/3515): the planning of the activation whose own input understanding marks relayed, such as a pasted email, is shown that input's words, marked relayed, and counts as having read outside content; a forward and every other outside content stay withheld from planning (ADR-0356 §3:7). Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-31 by [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md) — §3:1's table, in the addition alone: the Approvals channel's inputs carry empty parties, and their author is the request's person, not established as the user (ADR-0361 §3:6, §6:1). §8:5's reading over an activation's inputs, in the addition alone: an input with empty parties is left out of it, neither making the activation outside nor taking away its authority (ADR-0361 §6:6). Every other clause stands. This replacement takes effect on ratification of ADR-0361. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

### What the owner decided

An input carries two different facts, and the hub records only one of them well.

- **Who handed it in** is the author (ADR-0292 §5): the person typing, the mail channel
  delivering a message, the person forwarding someone else's text. The author decides
  authority.
- **Whose words it carries** is what the owner asked for here, the input's **parties**.
  "Hearing mom say something is different than mom emailing something because moms email
  could have been compromised." Mom's enrolled voice, on a speaker that knows who is
  talking, is Mom's word, established. Mom's email is a claim that Mom wrote it.

The owner asked that the parties "match the belief holders set very similarly, since that
will inform the other set". ADR-0345 made every support record its holder, from a closed
set of kinds, set by code from the part it points at. A claim taken from an input is held
by whoever's words it was, so the input's parties and the holders of what is learned from
it are the same thing seen from two ends.

The owner's design, as recorded for this decision:

- **An input carries its parties**, the set of sources whose words it carries, of
  ADR-0345's holder kinds: a person, established or claimed; an outside source,
  established or claimed; the assistant's statement. It may hold several, an audience, and
  members nobody identified. **∅** is an input that carries no one's words, as a doorbell
  does. **`None`** is unknown, or recorded before this decision, read fail-closed. A
  reminder's or a chain step's text is {the assistant}, not ∅.
- **The author stays separate**: you typing; the mail channel delivering Mom's email, Mom
  claimed; you forwarding Sam's message, where the author is you and the party is Sam,
  claimed.
- **Derived, never stored separately:** outside content, from the parties; authority, from
  an established author sending an instruction, covering that author's own words alone;
  and a support's holder, from the party whose words the part was.
- **`InputOrigin` retires**, and every reader moves to the parties and what follows from
  them.
- **Understanding may lower trust in an input, and never raise it.** Added in the owner's
  review. A pasted email, a quoted text or a screenshot's contents arrives as your own
  message, so its party is you, and it would carry your authority and be learned as your
  belief. Understanding may mark that the input carries words its sender did not write
  themselves, and code then treats it as a forward: no authority, outside, and what is
  learned from it held by unknown. The parties stay what code set.

### The two axes, side by side

| Input | Author | Parties | Outside | The user's authority |
| --- | --- | --- | --- | --- |
| You type in the hub chat | you, established | {you} | no | yes |
| You talk to a speaker enrolled to your voice (not built) | you, established | {you} | no | yes |
| Mom talks to it, enrolled (not built) | Mom, established | {Mom} | no | no, it is not the user's |
| Mom emails you (no mail channel is built) | the mail channel, a service | {Mom, claimed} | yes | no |
| You forward Sam's message on the line | you, established | {Sam, claimed} | yes | no |
| You type a note and forward Sam's, taken in together | you, established | {you, Sam claimed} | yes | no |
| You paste Mom's email into the hub chat, and understanding marks it relayed (§5:6) | you, established | {you} | yes, by the relay mark | no, by the relay mark |
| A connected source posts an event | that source's connection, a service | {that source, established} | yes | no |
| A reminder you set comes due | you, as the task's author | {the assistant's statement} | no | no |
| A step a chain spawned comes due | the assistant | {the assistant's statement} | no | no |
| A step spawned after reading a page comes due | the assistant | {the assistant's statement, unknown} | yes | no |
| A doorbell (not built) | the service | ∅ | no | no |
| A kitchen speaker hears someone it does not know (not built) | unknown | {unknown} | yes | no |
| An episode the upgrade could not read (§9) | as recorded | `None` | yes | no |

Mom's email is outside even where the address is hers, because the account could be
someone else's. Her enrolled voice is not, because the spoke's evidence establishes her
as ADR-0292 §5:10 allows. Content never moves an input from one row to another
(ADR-0292 §5:8): an email saying "this is really Mom" is still {Mom, claimed}. The one
exception goes only downward: understanding's reading of what you pasted can move your
message to the paste's row, outside and with no authority, and never to any row above the
one its parties give. Its parties stay {you}.

### What is there today

Surveyed at `77ac36716`, after ADR-0350's lanes TS1, TS1b and TS2 merged.

- **`InputOrigin` has three values,** `user`, `outside` and `assistant` (ADR-0284 §2:1,
  ADR-0350 §12:7), recorded as `RecordedChannelTrigger.origin` from what the channel type
  declares (`core/channel_validation.py`): the hub chat declares `user`, the informational
  event channel `outside`, the line `user`, or `outside` for an input that takes in a
  forward (ADR-0323 §4:11), and the Task Scheduler `assistant`, or `outside` for a task
  carrying the outside-content mark (ADR-0350 §6:3). ADR-0350 names `assistant` this
  decision's stand-in for {the assistant}.
- **The author is not recorded on the trigger.** It is read from the kind: the hub chat
  and the line establish the user, and an input that takes in a forward has, by ADR-0323
  §4:10, the forward's original sender as its author, claimed. A forward's sender is
  recorded per message as `RecordedInputMessage.forwarded_from`.
- **The holder already has the kinds.** `SupportHolder` (`core/types.py`) is ADR-0345 §2:2's
  closed set: a person, named by an identifier and established by construction (§2:7); an
  outside source, named by an identifier and marked established or claimed; the
  assistant's statement, naming the part it made; and unknown.
- **The holder rule keys on the origin.** ADR-0345 §2's table and ADR-0328 §4:2's origin
  table read `InputOrigin` and `forwarded_from`. Because a forward makes the whole input
  `outside`, a support pointing at a message the user typed beside a forward takes
  `outside_input` and an unknown holder (`orchestration/observer/reading.py`), although
  ADR-0323 §4:10 says what the user writes beside a forward is the user's.
- **About thirty readers branch on the origin**, across `core` and `orchestration`: the
  projection and the episode's content, recall's provenance and excerpt, understanding's
  attribution, planning's and the phases' outside-content facts, the join's standing, the
  matters pass, the story tidy-up and standing, the Task Manager's and the Task
  Scheduler's withholding of outside text, and the observer's support origin, which refuses
  a support on an `assistant` input (ADR-0350 §6:11). §8 lists them.
- **Joining and takeover compare origins.** ADR-0332 §3:3 and §4:6 required the same
  origin. ADR-0349, merged since, replaces both with absorbing and taking an offered input,
  and restates the same origin in its §7:5 and its waits, §7:12 and §7:15.
- **ADR-0339 holds no `fetched_outside`.** The dispatch cited it for a `None` read
  fail-closed. `fetched_outside` is a plain flag on `WorkingRecord`
  (`orchestration/authorizer.py`), and the corpus has no `None` reading of it. The
  fail-closed reading of `None` is ruled here on its own (§2:5), and recall already reads an
  unrecorded origin as not the user's (`orchestration/recall.py`).

### Words

An input's **parties** are the sources whose words it carries (§2). A **party** is one of
them. An input is **outside**, **the person's own** or **the assistant's** as §5 derives
it from its parties. An input is **relayed** where understanding marks it as carrying words
its sender did not write themselves, and that is its **relay mark** (§5:6). The **author**
is ADR-0292 §5's. **Holder**, **support** and
**origin** of a support are ADR-0345's and ADR-0328's.

## Decision

We will record on every input the parties whose words it carries, of ADR-0345's holder
kinds and set by code from what the channel's kind establishes, keep the author apart as
who handed it in, and derive outside content, authority and a support's holder from those
two facts, retiring `InputOrigin`. Understanding may mark an input relayed, carrying words
its sender did not write themselves, and the relay mark only lowers what follows: a relayed
input is outside, carries no authority and backs nothing as its sender's, while its parties
stay as code set them.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner, having
> reviewed it, ratifies it. An assigned number or a green review alone does not change its
> status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule
> 5, ADR-0015 §5).

> **Normative.** The implementation is the lanes §11 sets out, cut under ADR-0137, and each
> keeps the gate green.

### 2. An input's parties

> **Normative.** `RecordedChannelTrigger` gains its **parties**: a set of `SupportHolder`
> values, possibly empty, or `None`. Each member is a source whose words the input carries.

> **Normative.** A party is one of ADR-0345 §2:2's four kinds, with that clause's fields: a
> person, named by an identity the channel establishes (ADR-0345 §2:7); an outside source,
> named by an identifier and marked established or claimed; the assistant's statement,
> naming the part it made; and unknown, for a member whose record carries no identifier.
> An author an input only claims, a forward's sender or an email's, is an outside source,
> claimed, never a person (ADR-0345 §2:7).

> **Normative.** The parties hold no member twice, and are carried in one canonical order the
> contract lane fixes. Unknown appears at most once, and stands for one or more members
> nobody identified.

> **Normative.** Empty parties mean the input carries no one's words. A kind declares them
> only for an input whose payload carries none, as a doorbell or a signal does.

> **Normative.** `None` means the parties are unknown. Admission never records `None`. Only
> the upgrade does, for a stored input it cannot read the parties of (§9:3), and every
> reader takes `None` as outside and as neither the person's own nor the assistant's (§5).

> **Normative.** Where a trigger records its messages (ADR-0323 §5:4), each
> `RecordedInputMessage` gains its one **party**, a `SupportHolder` or `None`. Where the
> trigger's parties are a set, each message's party is one of them and the trigger's parties
> are exactly the distinct parties of its messages; where they are `None`, every message's
> party is `None`. The trigger's validator refuses any other. A joined input's messages carry
> their parties the same way (ADR-0332 §3:16).

> **Normative.** A recorded message carrying `forwarded_from` has as its party an outside
> source, claimed, named by the sender's `ClaimedAuthor.account_id`, or unknown where the
> medium reports none, or `None` where its trigger's parties are `None`. The validator
> refuses any other party on it.

> **Normative.** Parties are set by code at admission, from what the channel's kind declares
> and the record its sensor brings, and are fixed on the episode. No model's output sets or
> changes a party. Attribution is mechanical: the sensor's record and the kind's
> declaration, at admission. Understanding's relay mark (§5:6) is a separate fact and
> changes no party.

> **Normative.** A party is set from who wrote or reported the words, never from what they
> say (ADR-0292 §5:8, ADR-0345 §2:8). A message claiming to be from someone, or quoting
> them, has the party of whoever sent it.

> **Normative.** Context a sensor brings in with an input, its window and a replied-to
> message's quotation (ADR-0323 §4:12) included, is not the input and adds no party. It keeps
> the author it is brought in with, and informs as ADR-0292 §10:3 has it.

**Why `SupportHolder` itself.** The owner asked that the two sets match, so they are one
type. A claim taken from a part is then held by that part's party by copying it, with no
mapping to drift (§7). ADR-0345 already settled what the kinds mean, how two are the same
(`SupportHolder.same_as`), and that a person is established by construction. The owner's
"a person, claimed" is ADR-0345 §2:7's claimed outside source, so the four kinds cover
every member the owner named, and no kind is added. The type keeps its name: renaming it
would touch every reader of the holder for no change in meaning.

**Why a party per message.** On the line, one input can carry what you typed and what you
forwarded. A party per message keeps them apart, so the support pointing at your note is
yours and the one pointing at the forward is the sender's, by one rule for every kind.

### 3. How each kind sets them

| Kind | Author | Parties |
| --- | --- | --- |
| The hub chat | the person signed in on the device, established: the owner, today | {that person} |
| The line, a message the configured account wrote | the owner, established (ADR-0323 §4:1) | {the owner} |
| The line, a forward | the owner, established, who forwarded it | {the original sender, claimed}, by §2:7 |
| The line, several messages taken in as one | the owner, established | the distinct parties of its messages (§2:6) |
| The informational event channel | the source's connection, a service, established | {an outside source, established, named by the channel's identity} |
| A pull's late answer, arriving as a push (ADR-0292 §6:6) | the pulled service, established | {the source its record names, established}, or {unknown} where it names none |
| The Task Scheduler (ADR-0350) | the task's author (ADR-0350 §3:7) | {the assistant's statement, naming the task's instruction}, with unknown added where the task carries the outside-content mark |
| A mail channel, when one is built | the mail channel, a service, established | {the sender, an outside source, claimed, named by the address the message gives} |
| A spoke that tells who is talking, when one is built | whoever its evidence establishes, where ADR-0292 §5:10 allows | {that person}, or {unknown} for a speaker it does not establish |

> **Normative.** Each kind declares the parties of its inputs, per input, as the table's row
> for it rules. `core/channel_validation.py` holds the declaration until channels carry
> their own (#2578), and a channel type with no declaration is refused at admission.

> **Normative.** A kind establishes a person as a party only where it establishes that
> person as an author (ADR-0292 §5:4, ADR-0345 §2:7). Until a decision on identified people
> adds others, the one person a party names is the owner, by the identifier ADR-0345 §2:5
> names.

> **Normative.** A mail channel's sender is claimed, whatever the address, until a decision
> on that channel rules how it establishes one. An address that matches a known person
> names an outside source, claimed, and never that person.

> **Normative.** A pull's answer that returns to the activation that asked is not an input.
> It is digested evidence, held as ADR-0345 §2's table rules for an evidence item, and
> gives no input its parties.

> **Normative.** An informational event's party is named by its channel's identity, the
> connected source instance it came from, and is established, because the hub's own admitted
> connection is what delivered it. The identity grants nothing (ADR-0292 §5:9).

> **Normative.** A Task Scheduler input's parties are the assistant's statement alone, or
> that and unknown where its task carries the outside-content mark (ADR-0350 §3:8),
> whoever set the task. A reminder's text and a chain step's are the assistant's, never the
> person's, and never ∅.

> **Normative.** `StatementPart` gains a member for the instruction a scheduled task carries
> (ADR-0350 §3:6), added under ADR-0345 §2:2's closed set, as the part a Task Scheduler
> input's assistant party names.

> **Normative.** No kind declares parties that mix a person and the assistant's statement
> with no outside member, and admission refuses an input that would carry them.

**Why unknown on a marked task.** A step spawned after reading a page carries words the
assistant wrote over what it read, and nothing records which of them came from the page.
Adding unknown says that some of its words may be an unidentified source's, so the input is
outside (§5:1) exactly where ADR-0350 §6:3 made it `outside`, and nothing about the page
is invented. Naming the sources the spawning activation read is left for later (§12).

**Why an event's source is established.** A connected source reports in its own name, as a
digest's evidence item does under `Attestation.reported_by`. Holding what it reported by
that source lets a later event from it withdraw its own claim (ADR-0345 §3), which an
unknown holder never can.

### 4. The author stays separate

> **Normative.** An input's author stays ADR-0292 §5's: who handed the input to the
> assistant, how sure the kind is of them, and when it was written, stated by the hub and
> never by content (ADR-0292 §5:1, §5:8). This decision adds no field for it.

> **Normative.** On the line, a forward's author is the person who forwarded it, established
> as the line establishes the sender (ADR-0323 §4:1), and its original sender is its party,
> claimed. The forward still informs and authorizes nothing (§6).

> **Normative.** No rule reads a party as an author, or an author as a party. Authority reads
> both (§6), and outside content and holders read the parties (§5, §7). Each also reads
> understanding's relay mark, which only lowers what the parties and the author give
> (§5:6–§5:8).

**Where the axes cut.** The author is about the act of handing something in, and the kind
can establish it, because the kind sees the act: the configured account sent this, this
device is signed in. The parties are about the words, and the kind can establish a party
only where it sees who spoke them. You forwarding Sam's message is your act and Sam's
words. Mom's email is the mail channel's delivery and words claimed to be Mom's.

### 5. What follows from the parties

> **Normative.** An input is **outside** where its parties are `None`, or include a member
> that is neither a person nor the assistant's statement: an outside source, established
> or claimed, or unknown. Outside content is computed from the parties wherever it is
> read, and never stored apart from them.

> **Normative.** An input is **the person's own** where its parties are not empty and every
> member is a person. It is **the assistant's** where its parties are not empty and every
> member is the assistant's statement. An input with empty parties is none of the three.

> **Normative.** A trigger whose input is outside is an **outside trigger** (ADR-0306 §4:5).
> An activation whose trigger is the person's own, the assistant's or empty has not read
> outside content through its trigger.

> **Normative.** A reader that attributes an input as a whole attributes it by §5:1 and
> §5:2: as received, never as something anyone said, where it is outside; as the person's
> words where it is the person's own; as written by the assistant where it is the
> assistant's (ADR-0350 §6:12); and as said by no one where its parties are empty.

> **Normative.** A reader that attributes an input's recorded messages one by one attributes
> each by its own party, by the same rule.

**Why the person's own note beside a forward stays outside as an input.** Attribution per
message lets a reader show your note as yours (§5:5) and lets the observer hold it as
yours (§7). The activation as a whole still read Sam's words, so it is still an outside
trigger and its calls that leave the hub still need you (ADR-0306 §4:4). That is the cost
ADR-0323 §4:11's prose accepted, kept, until the outside-content redesign
([#2856](https://github.com/leonapivato/ai-assistant/issues/2856)) marks outside content per
part.

**Understanding's relay mark.** Code sets the parties, and understanding may lower what
follows from them, never raise it.

> **Normative.** Understanding's reply may mark the input it reads **relayed**: carrying
> words its sender did not write themselves, such as a pasted email, a quoted message or the
> text of a screenshot. This is the **relay mark**. It is per input, as authority is (§6:1):
> an understanding version marks its activation's own input, the trigger's, and an input an
> absorption or a take appended to the activation (ADR-0349 §7:7, §7:21) carries its own
> relay mark (§5:14).

> **Normative.** A relay mark counts only on an input whose parties are the person's own or
> the assistant's. Such a relayed input is outside, and neither the person's own nor the
> assistant's. Every clause of this decision that reads §5:1–§5:5, and every reader those
> clauses bind, reads it so. On an input whose parties are already outside, or are `None`
> or empty, a relay mark changes nothing: the parties already record whose the words are,
> so a forward keeps its sender's claimed holder and your note beside it keeps yours (§7:1).

> **Normative.** The relay mark changes no party. An input's parties stay what code set at
> admission (§2:8), and the relay mark is a separate fact, recorded on the understanding
> version (§5:10) or on the joined input (§5:14) and never on the trigger. It only lowers:
> neither the relay mark nor its absence makes an input the person's own, the assistant's,
> or anything its parties do not make it.

> **Normative.** The relay mark holds for the rest of the activation. Where an activation
> records more than one understanding version, each records the relay mark where an earlier
> one did, and `EpisodeProcessingRecord`'s validator refuses a record in which a later
> version drops it.

> **Normative.** `ProposedActivationUnderstanding` gains `relayed: bool = False`, the
> reply's relay mark on the input it reads, and `ActivationUnderstanding` gains `relayed:
> bool = False`, the relay mark that version records on the trigger's input. `False` marks
> nothing. Exact names are the contract lane's.

> **Normative.** A reader reads the trigger's relay mark from the latest understanding
> version its activation records when it reads, and a joined input's from that joined input's
> own record (§5:14). Before any version exists, and where understanding was omitted
> (ADR-0276 §2:1's `UnderstandingOmission`), it reads the trigger's input by its parties
> alone.

> **Normative.** Understanding's instruction gains, in substance, one line: say in `relayed`
> whether the input carries words its sender did not write themselves, such as a pasted
> email or a quoted message. The wording is the lane's, judged on ADR-0337's regression
> suite.

> **Normative.** An activation one of whose inputs is relayed has read outside content
> (ADR-0306 §4:5) from the understanding version that marks it, or from the append that
> brings it (§5:14), as one with an outside trigger has, and where the relayed input is the
> trigger's, its trigger is an outside trigger (§5:3).

> **Normative.** A relay mark travels with every input an absorption or a take moves.
> `JoinedInput` gains `relayed: bool = False`. Where an absorption (ADR-0349 §7:7) or a take
> (ADR-0349 §7:21) appends an input as a `JoinedInput`, it sets `relayed` on it, in the same
> step that appends it, where that input is relayed in the activation it comes from when the
> step reads it (§5:11). That joined input is relayed from that step on, whatever any
> understanding version records, and it stays so on the frozen episode. So a later
> absorption or take of the activation that holds it, before or after any further version,
> finds it relayed and carries it again. Where one `JoinedInput` brings more than one input,
> one relayed input among them is enough, and the relay mark covers all of it.

**Why it only lowers.** A model can only lower trust, so injection gains nothing. Text that
talks understanding into a relay mark costs the person an approval prompt: a call that
leaves the hub asks them, a yes in that input approves nothing and is asked again, and what
they said is learned as received rather than as theirs. Text that talks understanding out of
one finds nothing to undo, since an input it does not mark is read exactly as its parties
already give, which is today's reading. A wrong relay mark costs the person an approval
prompt, and a missed one costs what the paste costs today. That is why the relay mark
changes no party (§5:8): the parties are what code establishes, and nothing a model reads
can move them, up or down.

**Why it holds for the activation.** A later version that dropped the relay mark would raise
trust on a model's word, which §5:8 forbids. And readers run at different times: planning
and authorizing read what is latest when they run, and the observer and recall read the
episode once it is frozen. A relay mark that could disappear would let those readers
disagree about one input. Carried forward, it is on the latest version, which the bound on
retained versions never elides (ADR-0276 §7:4).

**Why per input, on two records.** An activation's understanding reads its own input. An
input an absorption or a take brings is covered by the version or the offer that named it
(ADR-0349 §7:9), so no later reply reads it, and its relay mark was already read where it
came from. The append records it there and then (§5:14), so it survives a second absorption
and a freeze before any further version, and needs no label for the reply to name it. A
support on the trigger's input reads the version alone, so a relay mark on an input that was
brought in never moves the holder of the trigger's. A paste and your own words inside one
input are relayed together, as one input: per-part marks are §12's.

**Why readers before understanding read the parties.** Recall's first run, ahead of
understanding (ADR-0308 §2:1), searches with the input's words before any version exists,
and grants nothing. ADR-0349's waits read a newer input before it is understood, and §8:5
says how its class is read there.

### 6. Authority

> **Normative.** Input carries the user's authority only where its author is established as
> the user, the user sent it as an instruction, and its parties are the user alone. This
> adds the last condition to ADR-0292 §5:5, and everything else still informs and cannot
> authorize.

> **Normative.** A party in what an author relays, forwards or quotes never carries
> authority, its own or the author's, whoever it is.

> **Normative.** ADR-0323 §4:7's reading of ADR-0321 §3:3 also requires the input's parties
> to be the user alone: a yes that comes in with a forward approves nothing.

> **Normative.** A Task Scheduler input carries no authority (ADR-0350 §3:9), and §6:1
> derives that from its parties alone.

> **Normative.** A relayed input (§5:6) carries no authority, whatever its author and its
> parties, and a yes in it approves nothing (ADR-0321 §3:3, as ADR-0323 §4:7 and §6:3 read
> it). An activation holding a relayed input acts with no authority from the understanding
> version that marks it relayed.

**Why the parties condition, and not authority split within an input.** "Covering only
that author's own words" could be read as an input that carries both your note and Sam's
forward having your authority for your note and none for the forward. Authorizing reads one
fact per input (ADR-0323 §4:5), and nothing records which words of an input a planned call
came from, so a split would rest on a model keeping the two apart. The condition gives
every input today exactly the authority it carries now: ADR-0323 §4:6 already refuses it to
an input that takes in a forward. Authority per part waits for the outside-content redesign
(§12).

**All or nothing, for now.** The owner confirmed it: "for now I think all or nothing is
fine, but eventually I think there can be levels to authority." An input carries the user's
authority whole or not at all, and §6:5 takes it away whole. Levels of authority are §12's.

### 7. Holders, and a support's origin

> **Normative.** A support pointing at one of an input's recorded messages is held by that
> message's party, or by unknown where that party is `None`. One pointing at the input as a
> whole is held by its one party, where its parties hold exactly one member, and by unknown
> otherwise, `None` parties included. This replaces the first and
> fourth rows of ADR-0345 §2's table.

> **Normative.** A support pointing at the input or one of its messages takes the origin
> `user_message` where that part's parties are the person's own, and `outside_input` where
> they are outside, `None` included. A message's parties are its one party, or `None` where
> that party is `None`, and the input's are the trigger's. This replaces the first two rows
> of ADR-0328 §4:2's origin table, and the other rows stand.

> **Normative.** No support points at an input, or a message of one, whose parties are empty
> or include the assistant's statement, and the code that sets a support's origin and holder
> refuses one that does. A support of such an activation points at another part of its
> episode, as ADR-0350 §6:11 already has it.

> **Normative.** The holder of a support pointing at an outside part may be an outside source
> marked established, where the part's party is one. ADR-0345 §2's table no longer limits an
> `outside_input` support's holder to a claimed source or unknown.

> **Normative.** Holders are set by code from the parties as the episode stores them, by one
> rule in `core` that every writer and the memory store's upgrade share, and no model's
> output sets one (ADR-0345 §2:1). Understanding's relay mark, which code reads from the
> episode, can make a holder unknown and nothing else (§7:6).

> **Normative.** A support pointing at a relayed input whose relay mark counts (§5:7), or
> one of its messages, takes `outside_input` and is held by unknown, where §7:3 does not
> refuse it. This holds for text the person pasted into a message of their own, in place of
> ADR-0328 §4:4's `user_message` for it: a part whose parties are empty or include the
> assistant's statement is still no support. A round's message and a remember call of an
> activation holding a relayed input take ADR-0328 §4:2's rows for an activation that has
> read outside content (§5:13). ADR-0328 §4's part table, which this decision leaves as it
> is, addresses only the trigger's input and the trigger's recorded messages, so this clause
> binds where the trigger's input is relayed. A joined input is no part a support points at,
> before this decision or after it, and a relay mark on one reaches what is learned through
> §5:13 alone.

**What this changes for what you typed beside a forward.** It was `outside_input`, held by
unknown, because the whole input was `outside`. It is now `user_message`, held by you,
because its party is you. What you forwarded stays `outside_input`, held by its sender,
claimed. A reminder's text is still never a support: what the task rests on is in its
parent's episode, which the observer already read. A step spawned after reading outside
content is no support either, where ADR-0350 let its `outside` input take `outside_input`
held by unknown: its words are the assistant's over an unnamed source, and holding them
as a source's would rank the assistant's paraphrase as what the source said.

**Why a relayed input is held by unknown.** The relay mark says only that the words are not
their sender's. It does not say whose they are, and nothing on the record does: a pasted
email's "From: Mom" is content, which names no party (§2:9). Unknown is never the same
holder as any other (ADR-0345 §2:6), so what you pasted can neither corroborate itself nor
be counted as your belief. Naming whose words a relayed input carries is §12's.

### 8. Every reader moves over

> **Normative.** `InputOrigin` is removed from `core/types.py`, with its members `user`,
> `outside` and `assistant`, and `RecordedChannelTrigger.origin` is removed.

> **Normative.** No reader of a stored episode branches on its channel type, and none reads an
> origin. A reader that needs to know whose words an input carries reads its parties through
> §5's predicates (ADR-0284 §2:3, as this section amends it).

> **Normative.** A clause of a decision ratified before this one that reads an input's or a
> trigger's origin reads, in its place: for `user`, that the input is the person's own; for
> `outside`, that it is outside; and for `assistant`, that it is the assistant's.

> **Normative.** `EpisodeProjection` carries the episode's parties, and the inputs its
> latest understanding version marks relayed (§5:10), in place of its origin, and its input
> text where the input is not outside (§5:1, §5:7), or is outside and `admit_outside_input`
> is true, whatever the party of any one of its messages. An input with empty parties has no
> text to carry (ADR-0284 §8:1, as this section amends it).

> **Normative.** Where a clause requires that two inputs have the same origin, it requires
> that both are outside, or both the person's own, or both the assistant's. Such clauses are
> ADR-0349 §7:5's third condition for an absorption, and through it §7:17's for an offer,
> and ADR-0349 §7:12's and §7:15's waits. An input whose parties are `None` or empty meets
> it with no input. The two inputs' parties need not be equal. An activation holding more
> than one input is read over all of them: outside where any is, and carrying the user's
> authority only where every one does (§5:13, §6:5). Each input is read with its relay mark
> (§5:7, §5:11).
> - In the takeover step (ADR-0349 §7:4), which runs once the version naming `continues` is
>   recorded, this activation is read with that version's relay mark. Each activation it
>   reached is read with its own latest version's, which ADR-0349 §7:15's wait let it
>   record, or by its parties where its understanding was omitted.
> - In ADR-0349 §7:12's and §7:15's waits, an input that no understanding version has yet
>   covered meets the condition both as its parties give it and as a relay mark would leave
>   it: outside, and carrying no authority. So a wait covers every input that a relay mark
>   could bring into the waiting activation's class.
>
> So a typed message absorbs no activation whose input understanding marked relayed, and is
> absorbed by none.

| Reader | What it reads in place of the origin |
| --- | --- |
| `core/channel_validation.py` and `orchestration/channel_kinds.py`, the declaration | Each kind's parties, per input (§3:1) |
| `core/episode_encoding.py`, the episode's content and the projection | The person's own, for the content; outside, for the projection's input (§8:4) |
| `core/types.py`, `support_holder` and the support origin | Each part's parties (§7) |
| `orchestration/observer/reading.py`, a support's origin and the parts it offers | The part's parties (§7:2, §7:3), moved in P1 (§11:1) |
| `orchestration/joining.py` and the takeover stage: absorbing, the offer, the take and the waits (ADR-0349 §7) | Authority (§6:1), the class §8:5 compares, and the relay mark's travel (§5:14) |
| `orchestration/outside_content.py`, `orchestration/phase_path.py` and `orchestration/planning.py`, the outside trigger | Outside (§5:3) |
| `orchestration/phase_path.py`, the user's authority | Authority (§6:1) |
| `orchestration/recall.py`, provenance and excerpt | The person's own, else outside, as today (§5:4) |
| `orchestration/task_manager.py` and `orchestration/task_scheduler.py`, withholding outside text | Outside (§5:1) |
| `orchestration/understanding.py`, `orchestration/matters_pass.py`, `orchestration/story_tidy_up.py` and `orchestration/story_standing.py`, attribution and the outside mark | §5:1, §5:2 and §5:4 |
| `orchestration/understanding.py` and `orchestration/understanding.txt`, the relay mark | The `relayed` line, and its carry to a later version (§5:9, §5:10, §5:12) |

> **Normative.** Every row of the table reads an input with its relay mark (§5:7, §5:11),
> and each reader of the user's authority with §6:5.

**Why the same class and not the same parties.** An absorption's origin condition keeps an
outside activation and one that has not read outside content from mixing, so one
activation's outside fact stays its trigger's (ADR-0306 §4:5). Who said what is already kept
apart: every absorbed or taken input keeps its own messages, each with its own party (§2:6),
so holders are never confused by a merge. Requiring equal parties would also stop two
forwards from different people from being taken in together, which nothing gains from.

**Why a wait reads an input not yet understood both ways.** A wait that read a newer paste by
its parties alone would pass over it while the older activation held a forward, and the
older could act before the paste, once understood and relayed, absorbed it: the newest would
not decide (ADR-0349 §7:12). Reading it both ways costs at most a wait that ends when the
newer records its understanding.

### 9. The upgrade

> **Normative.** The episode store upgrades every stored trigger and joined input in place,
> with no model and nothing dropped (ADR-0326 §4:1), giving each its parties and each
> recorded message its party, by the rule its kind declares (§3) applied to the record as
> stored.

> **Normative.** The upgrade reads a stored record as follows. An input of the hub chat with
> the origin `user`, and each message it or a join on it records, has the owner as its
> party. A message of the line with no `forwarded_from` has the owner, and one with it has
> §2:7's party, whether the trigger or a join records it. An input of the
> informational event channel has the outside source §3:5 names. An input of the Task
> Scheduler has §3:6's parties, by its stored origin: `assistant` for the assistant's
> statement alone, `outside` for that and unknown.

> **Normative.** A stored record the rule above does not cover gets `None` parties, and every
> message it or a join on it records gets `None` as its party, a forwarded one included. §2:6
> and §2:7 admit that record, and §7 reads each such part as outside and held by unknown.

> **Normative.** No support is rewritten. A stored support keeps its origin and the holder it
> was recorded under (ADR-0345 §2:9), and §7 binds only what a write adds after the upgrade.

> **Normative.** The episode store's label advances, a file at the previous label is upgraded
> rather than refused, and the upgrading lane ships ADR-0326 §4:2's test over a file the
> previous release wrote, and raises the episode store's shape in `scripts/upgrade_stores.py`
> with a carry from the shape it replaces (ADR-0326 §7).

> **Normative.** No stored understanding version or joined input is rewritten for the relay
> mark (§5:10, §5:14). One recorded before this decision validates unchanged and marks
> nothing, so every input stored today reads as its parties give, as it was read when it was
> recorded.

**Why derive and not `None` for everything old.** Every stored input was written by a
kind whose declaration fixes its parties, and until now only the owner speaks on any
channel, so the rule recovers them exactly, as ADR-0345 §13:1 recovered holders. Setting
`None` everywhere would make the owner's whole history outside (§2:5), so recall,
understanding and the observer would read every past message of the owner's as a report
received.

### 10. The code it binds

> **Normative.** `core/types.py` gains the parties on `RecordedChannelTrigger` (§2:1) and the
> party on `RecordedInputMessage` (§2:6), with the validators §2:3, §2:6 and §2:7 name, and
> pure functions for §5's three predicates beside the type. Exact names are the contract
> lane's.

> **Normative.** Until the lane that removes `InputOrigin` merges (§11), the trigger and the
> projection keep `origin` as a value computed from the parties and stored nowhere: `user`
> for the person's own, `assistant` for the assistant's, and `outside` otherwise. It reads the
> parties alone: no relay mark is recorded before P2, which records the first and removes
> `origin` in one change (§11).

> **Normative.** `PROTOCOL_VERSION` advances in each lane that changes a shape the wire
> carries, in that change (ADR-0124 §9).

> **Normative.** `core/types.py` gains the relay mark on `ProposedActivationUnderstanding`
> and `ActivationUnderstanding`, with `EpisodeProcessingRecord`'s validators (§5:9, §5:10),
> and `JoinedInput` gains `relayed` (§5:14).
> §10:1's predicates take the relay mark beside the parties, and read a relayed input as
> §5:7 has it. `EpisodeProjection` carries the relay mark (§8:4).

### 11. Delivery

The lanes, each after this decision merges `Accepted`:

1. **P1, the contract unit with its primary implementation** (ADR-0137 §2:1): §10's types
   and the computed `origin`, the declarations (§3:1), the Task Scheduler's included,
   `support_holder`'s rule and the support origin (§7), the observer's support origin and the
   parts it offers as supports (`orchestration/observer/reading.py`), the canonical fakes in
   `ai_assistant.testing`, the episode store's upgrade in `memory/` with its test (§9), the
   relay mark's fields, validators and predicates (§10:4) with the holder and origin of a
   support on a relayed input (§7:6), and the advance of `PROTOCOL_VERSION`.
2. **P2, every reader** (ADR-0137 §4:1), briefed against merged P1: each row of §8's table
   moved to the parties and §5's predicates, the authority rule (§6) and the class an
   absorption, an offer and a wait compare (§8:5), understanding's `relayed` line and its
   carry to a later version (§5:9–§5:12), its travel with every absorbed or taken input
   (§5:14), with their prompt cases, every reader's reading of the relay mark (§5:7, §5:11, §5:13, §6:5, §8:6), and the removal of
   `InputOrigin` and the computed `origin` (§8:1).

> **Normative.** P1 may touch `core`, `testing`, `memory`, `wire` and their tests, and
> `orchestration/` only to set the parties a kind declares and to adapt the observer's
> support origin and the parts it offers as supports to §7, so that what the observer
> proposes is what the writer admits. P2 adapts readers across
> `core`, `orchestration` and `interfaces`, as ADR-0137 §1:2 allows, and may touch
> `prompt_cases/`, and `scripts/prompt_replay.py` with its tests where a case needs it.

> **Normative.** P1's tests include, each failing on an implementation that meets only the
> others: a forward's message has its sender's claimed party and a message you typed beside
> it has yours; a support pointing at each is held by that party and takes `user_message`
> and `outside_input` respectively; a support pointing at a Task Scheduler input is refused,
> a marked task's included; the observer, given an episode in which your note and a forward
> came in together, proposes for your note a `user_message` support held by you, and offers
> no part of a marked task's input as a support; an input mixing a person and the
> assistant's statement alone is refused; an informational event's party is its source,
> established; `None` parties read as outside; and the upgrade gives every row of §9:2 its
> parties and every other record `None`, a record with recorded messages and a forward among
> them included, which then validates, reopens, and gives a support on each of its parts an
> unknown holder and `outside_input`, over a file the previous release wrote. They also
> include: a support pointing at an input the latest understanding version marks relayed, or
> at a message of it, takes `outside_input` and is held by unknown, while one pointing at an
> unmarked message you typed is held by you and takes `user_message`; a relay mark on a Task
> Scheduler input leaves its support refused; a relay mark on an input carrying a forward
> changes nothing, so the forward's support is still held by its sender, claimed, and the
> one on your note beside it by you; a record in which a later version drops a
> relay mark an earlier one recorded is refused; and an understanding version, and a joined
> input, stored before the fields validate unchanged and mark nothing.

> **Normative.** P2's tests include: an input carrying a forward carries no authority and
> its yes approves nothing; a reminder's input carries none; a forward continuing another
> from a different sender absorbs it; your typed message absorbs no activation a forward
> started, and is absorbed by none; and an input whose parties are `None` absorbs nothing
> and is absorbed by nothing. They also include: a pasted email in the hub chat that
> understanding marks relayed carries no authority, its yes approves nothing and its stop
> call is refused, its activation has read outside content, and a support pointing at it is
> held by unknown; an unmarked typed message keeps its authority, its standing and its
> holder; your typed message absorbs no activation whose input understanding marked
> relayed, and is absorbed by none; a forward that absorbs a relayed paste's activation
> records `relayed` on each joined input it appends, which stays relayed where a later
> version of the absorber, if one runs, marks nothing, where a newer activation absorbs the
> absorber, carrying the relay mark again, and where the absorber's episode freezes first; a
> take of an offered relayed input records `relayed` the same way; and an older forward
> about to act waits for a newer paste not yet understood, which, once marked relayed,
> absorbs it.

> **Normative.** P2 adds synthetic prompt cases (ADR-0337 §3) for at least: a pasted email
> with your one line above it, which marks the input; a request you typed, which marks
> nothing; and a request you typed that quotes a few words of someone else's in passing,
> which marks nothing.

### 12. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| Who hears what: audience rules, and how a place's audience reads the parties | The audience design, which this gives the parties set to use |
| People other than the owner as parties and authors, and linking an identifier to a person | A decision on identified people (ADR-0345 §2:5, §2:9) |
| Outside content marked per part, so your note beside a forward or a paste is not outside for the whole activation | The outside-content redesign (#2856, [#2590](https://github.com/leonapivato/ai-assistant/issues/2590)) |
| Levels of authority, and authority per part of an input | A later authority decision, with the outside-content redesign (#2856); §6's all or nothing stands until then |
| Naming whose words a relayed input carries, as a party in place of unknown | A later decision; a party stays what code sets at admission (§2:8) |
| A support pointing at a joined input or one of its messages | A later decision on a support's parts (ADR-0328 §4), which would give it an address and its holder by §7 |
| How a mail channel establishes a sender | That channel's decision (§3:3) |
| Naming, on a marked task, the sources its spawner read, in place of unknown | A later decision, with the digest's source identity (ADR-0308) |
| The rendering of an input with empty parties | The decision that builds the first kind declaring them |

> **Normative.** Each item the table names takes a decision of its own before any lane builds
> it.

### 13. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0276 | §2:1's `ProposedActivationUnderstanding` and `ActivationUnderstanding` field sets, in the additions alone: the relay mark | §5:9, §5:10 |
| ADR-0284 | §2:1, whole: `InputOrigin` and the trigger's origin give way to the parties; §2:2, in what admission sets: the parties a kind declares; §2:3's *reads `origin`*: reads the parties, with the relay mark, through §5's predicates; §8:1, in the projection's origin and its condition for the input text | §2:1, §3:1, §5:7, §8:1–§8:4 |
| ADR-0292 | §5:5, in the addition alone: the input's parties are the user alone, and understanding has not marked it relayed | §6:1, §6:5 |
| ADR-0306 | §4:5, in the addition alone: an input understanding marks relayed is also a record that the activation has read outside content; §4:6's *never from a value a model, a tool or a plan emits*, for the relay mark alone, which can only set that fact | §5:13 |
| ADR-0323 | §4:2, in *a forward's original sender*: it is a party, claimed, not an author; §4:7, in the addition alone: the parties are the user alone, and the input is not relayed; §4:10's *its author is its original sender, claimed*: its author is the person who forwarded it; §4:11, whole: the kind declares parties per message | §2:7, §4:2, §6:3, §6:5, §3:1 |
| ADR-0328 | §4:2's origin table, its first two rows: keyed on the part's parties and the relay mark; §4:4's *text the user pasted into a message of their own takes `user_message`*, for an input understanding marks relayed: it takes `outside_input`, held by unknown | §7:2, §7:3, §7:6 |
| ADR-0098 | §1:2's *decided by recorded origin, never by inspecting the text*, in the addition alone: understanding's relay mark, a reading of the text that is then recorded and only lowers, also makes an input of the person's own outside | §5:6–§5:8 |
| ADR-0332 | §7:1's `JoinedInput` fields, in the addition alone: `relayed` | §5:14 |
| ADR-0349 | §7:5's third condition, §7:12 and §7:15, each in *origin* alone: the class of §8:5, each input read with its relay mark, and an input not yet understood read both ways in a wait; §7:7 and §7:21, in the addition alone: an absorption and a take set `relayed` on each joined input that was relayed where it came from; §10:7's *`JoinedInput` keeps its shape*, in the addition alone: `JoinedInput` gains `relayed` | §5:14, §8:5 |
| ADR-0345 | §2's table, its first and fourth rows, and its limit on an `outside_input` support's holder: keyed on the part's party; §2:2, in the addition alone: `StatementPart` gains the scheduled task's instruction; §2:1 and §2:8, in the addition alone: a part understanding marks relayed is held by unknown | §3:7, §7:1, §7:4, §7:5, §7:6 |
| ADR-0350 | §6:3, in the origins: the parties of §3:6; §6:11, in *an input whose origin is `assistant`*: a part whose parties include the assistant's statement, a marked task's input included; §6:12, in *by its origin*: by its parties, with the relay mark; §12:7, whole: the member retires | §3:6, §5:4, §7:3, §8:1 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0306 §4:4–§4:6, beyond the relay mark | Nothing: an outside trigger is one whose input is outside (§5:3), the same inputs as today, and those with `None` parties |
| ADR-0292 §5:8, ADR-0345 §2:8's *never from what the part says*, beyond the relay mark | Nothing: the relay mark establishes no author and sets no party, and only lowers (§5:8) |
| ADR-0276 §7:7 | Nothing: a recorded understanding still grants no authority and establishes no fact; the relay mark withdraws, and never grants (§5:8) |
| ADR-0340 §2, §4:1, §7:1 | Nothing: a task the person set is known by its author, and its input's parties are still the assistant's statement (§3:6). The rule and the skipped count its input states are the hub's rendering beside the task's instruction, and add no party |
| ADR-0303 §3:2, ADR-0300, ADR-0276 §4:8, ADR-0281 §4:4 and §6:3, ADR-0329 §8:6 | Nothing: each reads an origin, and §8:3 reads it through the predicates, giving today's result for every input recorded today |
| ADR-0284 §8:4 | Nothing: the parties and `derived_from_external` are different facts, and no renderer derives one from the other |
| ADR-0323 §4:6 | Nothing: §6:1 gives every input on the line the authority it states |
| ADR-0349 §5:3–§5:5 | Nothing in their words. A forward's author is now you (§4:2), so understanding of a forward is shown your running work in its in-progress section, under the disclosure predicate. It absorbs only what shares its class and its authority (§8:5): other outside input, never your own |
| ADR-0349 §4:6, §5:6, §6:9, §6:13 | Nothing: a relayed input carries no authority, so its activation is offered no stop call (§6:5); it is outside, so an in-progress entry and the peer view withhold its text (§8:4); and an activation shown one that has read outside content has read it too |
| ADR-0345 §2:2–§2:9, §13 | Nothing beyond the rows above: the kinds, the naming, the claimed rule and the upgrade of stored supports stand |
| ADR-0348 | Nothing: a request to keep is still cited, never backing, whatever its part's party |
| ADR-0339 | Nothing: it holds no reading of `None` that this relies on |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0098, ADR-0276, ADR-0284, ADR-0292, ADR-0306, ADR-0323, ADR-0328,
> ADR-0332, ADR-0349, ADR-0345 and ADR-0350, atomically with this ADR under ADR-0070 and
> ADR-0082, preserving their ratified bodies. The replacements take effect on this ADR's
> ratification.

## Consequences

**What gets easier.**
- **Holders follow from the input.** What you typed is held by you, what you forwarded by
  its sender, claimed, and what a connected source posted by that source, so a later post
  from it can withdraw its own claim.
- **Outside content has one definition**, computed from whose words an input carries, so
  a new kind declares parties and every reader already handles it.
- **The audience design gets its input.** Who was speaking, and who was not identified, is
  on every input, ready for rules about who may hear what.
- **ADR-0350's rules fall out of the parties.** A task's input is the assistant's, carries
  no authority and is never a support, from §5–§7 alone.
- **What you paste is read as received.** A pasted email or a quoted message that
  understanding marks relayed carries no authority, is outside, and is learned as received
  rather than as your belief, while its parties stay what code set.

**What gets harder, and what this leaves.**
- **Two lanes and an upgrade** for a change whose results, today, are nearly all the same.
  The gain is that the next kinds, a voice spoke and a mail channel, need only a
  declaration.
- **A forward now has you as its author.** A forward can absorb another, and a forward's
  understanding sees your other running work. Neither carries authority, and both are
  outside.
- **Your note beside a forward is still outside for its activation.** Per-part marks wait
  for #2856.
- **A relay mark costs an approval, right or wrong.** A paste's activation asks you before
  any call that leaves the hub, a yes in the paste approves nothing, and your words in the
  same input as the paste are held by unknown. A follow-up you type neither absorbs the
  paste's activation nor is absorbed by it, as with a forward, and an older forward about to
  act waits for a newer paste to be understood. A missed relay mark leaves the paste as it
  is today.
- **One more field on understanding and one on `JoinedInput`**, with prompt cases under
  ADR-0337.
- **On top of ADR-0349.** ADR-0349 merged first, so this decision maps its restated
  same-origin rules (§8:5), adds `relayed` to the `JoinedInput` it said keeps its shape
  (§5:14), and records both on its header.

**What would reopen it.** A kind whose words cannot be given a party by its record, or an
audience rule that needs parties per word rather than per message.

## Alternatives considered

- **Keep `InputOrigin` and add values** (`assistant`, then `voice`, `mail`). Not chosen:
  each value mixes who handed something in with whose words it is, and the holder rule
  would keep translating from it.
- **A party type of its own, mapped to the holder.** Not chosen: the owner asked that the
  sets match, and a second type is a mapping that can drift.
- **A claimed person as a kind of its own.** Not chosen: ADR-0345 §2:7 makes any author a
  part only claims a claimed outside source, so a forged "from Mom" can never become Mom's
  belief. A fifth kind would reopen that.
- **`None` for every stored record.** Not chosen: the stored records fix their parties
  exactly, and `None` would read the owner's history as outside (§9).
- **Authority per part of an input.** Not chosen now (§6).
- **The same parties for an absorption or an offer.** Not chosen (§8).
- **A forward's author staying its original sender.** Not chosen: the owner put the forward
  in your hands as author, and the sender in its words as party, which is where the holder
  rule needs it.
- **Understanding setting a pasted input's parties.** Not chosen: attribution is
  mechanical, as the owner confirmed, and a model that could set a party could raise one.
  The relay mark lowers what follows and leaves the parties alone (§5:8).
- **Naming the pasted words' writer, such as "Mom, claimed" from a pasted "From:" line.**
  Not chosen: what an input says names no party (§2:9). Unknown is the one holder the record
  supports (§7:6), and naming one is §12's.
- **A relay mark a later version can drop.** Not chosen: dropping it would raise trust on a
  model's word, and readers running at different times would disagree about one input
  (§5:9).
- **A label per input, for the reply to name which input it marks.** Not chosen: a version
  reads its activation's own input, and every input an absorption or a take brings carries
  its own relay mark from where it came (§5:14), so the reply never needs to name one.
- **Carrying an absorbed input's relay mark into the absorber's next version.** Not chosen:
  under ADR-0349 §7:9 no further version may run, and a second absorption or a freeze could
  come first. The joined input's own record keeps it (§5:14).
- **A relay mark per message, or per span.** Not chosen now: authority is all or nothing per
  input, by the owner's ruling, and marks per part are the outside-content redesign's (§12).
