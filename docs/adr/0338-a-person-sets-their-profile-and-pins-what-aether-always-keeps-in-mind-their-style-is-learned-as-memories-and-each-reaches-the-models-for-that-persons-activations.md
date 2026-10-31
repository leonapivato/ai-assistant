# 338. A person sets their profile and pins what Aether always keeps in mind, their style is learned as memories, and each reaches the models for that person's activations

- Status: Partially superseded by ADR-0342 (§11:1 and §11:2, in the additions alone: the `MemoryStore` history read's lane comes before the observer's and the panels' lanes are briefed, moving the person block onto it is a lane of its own, and going live waits on both) and ADR-0345 (§4:5, in the addition alone: a `pinned` support is also added as `against` where a dispute is recorded) and ADR-0350 (§2:2, in the addition alone: an activation the Task Scheduler starts is for the person its task is for) and ADR-0340 (§3:6, for a zone a spawn names: a local time the spawn states is read in that zone, and a rule naming a zone is computed and rendered in it) and ADR-0353 (§3:11's *Understanding is shown it as a hint for reading their input*: always in mind says the language the person writes in, and the instruction says nothing of it) and ADR-0356 (§3:10's instruction sentence: the person block says it; §5:6's second sentence; §7:8, whole) and ADR-0359 (§7:10's *reaches no later request*, for the later rounds of the work the memory was shown to) and ADR-0360 (§7:1's *The same block reaches every planning round*, in the addition alone: a pin or field the person changed since reaches the later rounds of the work as news)
- Date: 2026-10-21
- Scope: the person model, version 1. It covers one person model per person (§2), the profile's set fields (§3), standing knowledge by pinning (§4), style learned as memories (§5), the slot that carries both (§6), where the model reaches the models (§7), the panels and capabilities (§8), what the observer does with it (§9), and the store and its contract (§10). These are picks 1, 2, 3, 5 and 6 of proposal [#3255](https://github.com/leonapivato/ai-assistant/pull/3255), with the walk's answers 1 to 8. §12 names pick 4, the situation block, as not decided here.
- Dependency: [ADR-0328](0328-a-memory-is-a-statement-resting-on-supports-its-standing-is-computed-from-them-and-every-change-to-it-is-an-operation-citing-one.md), [ADR-0329](0329-the-observer-is-memorys-one-writer-it-commits-what-an-episode-leaving-the-window-shows-and-planning-records-candidates-for-it.md), [ADR-0321](0321-authority-at-the-deploy-is-your-yes-to-a-question-that-showed-the-call.md), [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md), [ADR-0281](0281-recall-runs-before-understanding-and-understanding-reads-what-it-found.md), [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md) and [ADR-0334](0334-a-prompt-is-a-template-the-hub-loads-at-start-the-owners-hub-may-override-it-from-its-data-directory-and-each-model-call-records-the-version-it-sent.md), as their status lines leave them. A one-off style request ("this time") depends on the controller's modes, which are pick 4 of proposal [#3257](https://github.com/leonapivato/ai-assistant/pull/3257) and which no decision has yet made (§5:4).
- Authorization: the coordinator walked proposal #3255 on 2026-10-21 under the owner's standing delegation. The walk's eight answers, and the coordinator's ruling on style posted on #3255 the same day, are what this decision converts. The owner's words on that delegation, verbatim: "Dont draw the line who ratifies what, Ill just check in and if I see something wrong I'll give input to you." On style the owner left the call to the coordinator, verbatim: "Whatever you think for the style dials. If dials are even the right design here." The dispatcher assigned 0338, and ratifies it under that delegation.
- **Adds a `Protocol` and changes `core`, so it is a contract-surface decision and a breaking change under golden rule 5.** `core/protocols.py` gains `PersonModelStore` (§10:1), and `AssistantEngine` gains the panels' members (§8:1). `core/types.py` gains the person model's types (§10:4), and a support part and origin, `pinned` (§4:4). The wire carries the new members, so `PROTOCOL_VERSION` advances.
- **Partially supersedes**, in the clauses §13's first table names: ADR-0005, ADR-0072, ADR-0130, ADR-0217, ADR-0276, ADR-0281, ADR-0307, ADR-0321, ADR-0328 and ADR-0329.
- Partially superseded: 2026-10-21 by ADR-0342 — §11:1, in the addition alone: the `MemoryStore` history read's triad lane merges before lanes 5 and 6 are briefed, and each reads through it in its own lane (ADR-0342 §6:1); moving the person block onto the history read is a lane of its own in `orchestration/`, briefed after the triad lane and lane 1 have merged, or folded into lane 1 where the triad lane merges before lane 1's first review (ADR-0342 §6:2). §11:2, in the addition alone: the person model does not go live on a person's hub before those two lanes have merged (ADR-0342 §6:3). Every other clause stands. This replacement takes effect on ratification of ADR-0342. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-10-23 by ADR-0345 — §4:5, in the addition alone: a `pinned` support is also added, as `against` and backing nothing, where a placed proposal's write records a dispute (ADR-0345 §3:8). Every other clause stands. This replacement takes effect on ratification of ADR-0345. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0350 — §2:2, in the addition alone: an activation the Task Scheduler starts is for the person its task is for, the person the spawning activation was for (ADR-0350 §3:5, §6:4). Every other clause stands. This replacement takes effect on ratification of ADR-0350. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0340 — §3:6, for a zone a spawn names: a local time the spawn states with no offset is read in the IANA zone it names, and a rule naming a zone has its occurrences computed and its times rendered in that zone, not in the person's zone (ADR-0340 §3:2, §4:3, §6:1). Every other clause stands, and ADR-0340 reads it as already reaching a local time stated with no zone, a rule's occurrences and every rendering of a scheduled task's times (ADR-0340 §3:3, §6:1). This replacement takes effect on ratification of ADR-0340. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-27 by ADR-0353 — §3:11's *Understanding is shown it as a hint for reading their input*: always in mind says the language the person writes in, as their own, and understanding's instruction need say nothing of it (ADR-0353 §4:5, §13:3). Every other clause stands. This replacement takes effect on ratification of ADR-0353. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0356 — §3:10's *planning's instruction says that a field outweighs any memory stating another value for it*: the person block says it, as data (ADR-0356 §10:5). §5:6's second sentence: the instruction's line that everything in the context is data to weigh carries it, and each message tool's description says the system never claims to be human (ADR-0356 §10:6). §7:8, whole: using the block and addressing the person are preferences, held as data, and the suggestion line is said by the `set_profile` and `pin` descriptions (ADR-0356 §10:7). Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-31 by [ADR-0359](0359-the-news-reports-a-matter-changed-and-a-memory-forgotten-since-the-work-was-shown-them.md) — §7:10's *reaches no later request*, for the later rounds of the work the memory was shown to: within a work, a memory the store no longer holds stays in the turns already sent and is announced in the next report's news as forgotten and not to be used, since the exchange is append-only (ADR-0359 §4:1, ADR-0356 §5:2). Code still drops it from the block before each round, so a briefing rendered after it is gone never holds it (ADR-0359 §4:2). Every other clause stands. This replacement takes effect on ratification of ADR-0359. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-31 by [ADR-0360](0360-the-news-also-reports-the-time-other-works-starting-and-ending-and-what-the-person-newly-chose-to-keep-in-mind.md) — §7:1's *The same block reaches every planning round*, in the addition alone: the block is not reassembled, but before each round after the first code reads the person's profile and pins, and a memory newly pinned or no longer pinned, as the slot resolves pins, or a field changed since the exchange showed the block is named in the next report's news (ADR-0360 §4:1, §4:4). §7:10 is unchanged. Every other clause stands. This replacement takes effect on ratification of ADR-0360. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**The question.** What does Aether hold about each person it serves, beyond its memories,
and where does that reach the models? The aim is that every exchange starts from "it knows
me" rather than from "it can look me up".

**Where this comes from.**

- **The thesis.** The product's moat is a model of each person that is outstanding and keeps
  changing: their preferences, routines, goals, relationships, communication style and
  decision patterns (VISION, "The Long-Term Moat").
- **The vision.** Aether keeps "a model of each person: their profile, the style they prefer,
  and their boundaries" ("People and Households"). Its personality is adjustable per person,
  on a character that stays the same (Principle 9).
- **What learning v1 left open.** ADR-0328 decided what a memory is, and ADR-0329 made the
  observer memory's one writer. Neither gives the models a picture of who they are talking
  to.
- **The prompt review of 2026-10-20.** It found the live hub telling planning the time in
  UTC, because `ASSISTANT_TIMEZONE` was unset. The owner agreed that a name and an address
  are a new input, not a self-editing prompt: the instruction is the rules (ADR-0334), and a
  model that edits its own rules drifts without review.
- **The owner on the name:** "use Aether for the name, but maybe the user wants to set a
  nickname too, that should work."

**The test.** On 2026-10-21 the owner adopted one test for how Aether handles people: what a
trusted human assistant would do (VISION Principle 3, as
[#3256](https://github.com/leonapivato/ai-assistant/pull/3256) amends it). Such an assistant:

- learns you by watching and asks only when unsure;
- uses what it knows naturally, without reciting it;
- keeps what it knows current as you change;
- and is discreet.

The analogy breaks in four places, and the design answers each with a rule in code rather
than in judgment:

- **This assistant remembers word for word.** So everything is visible on a panel and every
  change is logged.
- **It cannot see who is present.** So the person comes only from the author the hub states.
- **It is easier to manipulate.** So a change needs the person's own yes, and the observer
  only suggests.
- **Its judgment shifts with the model.** So "use it, don't recite it" is a prompt case
  (ADR-0337).

**The walk's answers, which bind this decision.**

1. The set profile is its own store. It supersedes ADR-0072's no-profile-artifact rule for
   the stage 1 fields alone, narrowly.
2. Pinning confirms the wording. Pointing at a note and saying "always keep this in mind"
   endorses what it says.
3. The pin cap is a size budget of about 400 tokens for the standing knowledge, not a count.
4. Style has no dials (the coordinator's comment on #3255):
   - style preferences are memories, learned by the observer and correctable in the panel;
   - they always reach planning in the profile's always-included slot;
   - "this time" is the controller's pending mode, and "from now on" is a stated preference;
   - the moment's tone stays understanding's job, on a stable core;
   - and there is no numeric setting.
5. The observer's suggestions show on the panel, and are mentioned naturally where they
   come up.
6. `ASSISTANT_TIMEZONE` stays as the hub-wide default. A person's profile zone overrides it
   for that person, and the owner's profile is seeded from it.
7. Language is the language Aether writes to the person in, plus a hint for reading their
   input.
8. Two ADRs: this one, the person model, ships first, and the situation block follows.

**What stands on `main`.**

- **There is no profile artifact.** ADR-0072 §1 rules "no `UserProfile` type, no
  `UserProfileStore` Protocol, and no second collection of user facts", because a
  materialised profile would be a cache of the store with no invalidation. §8 declines a
  `UserProfile` type and a second store. ADR-0005 §2 says the same from the storage side.
- **What understanding receives.** ADR-0276 §1:5 names the input and the two windows, "and
  nothing else". ADR-0281 added recall's records and ADR-0300 the candidate stories.
- **What planning is given.** ADR-0307 §6:1 lists it, including "the current time".
  `PlanningStage` gives the time as an ISO instant and a `time_zone` key, both read from
  `Settings.timezone`.
- **The time zone.** `Settings.timezone` is read by planning's clock, the quiet windows,
  which ADR-0130 §6:4 binds to it ("No second timezone source is introduced"), the spend
  limit's day and the calendar reader (ADR-0093 §7b).
- **What the observer reads.** ADR-0329 §8:1 names it, and a profile is not among it.
- **Supports.** A confirmation support comes only from an approved question part (ADR-0328
  §4:5). Every support other than a legacy one points at an episode the store holds (§4:7).
- **Who wrote an input.** The hub states it, never the content (ADR-0292 §5:1, §5:8). In
  code, a kind either establishes the user (`ChannelKind.establishes_the_user`) or records
  a `ClaimedAuthor`.
- **Records and audiences.** The record rule applies at the sites it is applied today, and
  at no new one (ADR-0217 §2:5). A memory resting on outside content reaches planning only
  through a digest (ADR-0328 §15:6).

## Decision

We will key a person model by person and fill it for the owner alone. A profile of five
fields that the person sets will be the source of truth for each field. The memories the
person pins will be shown on every activation, and pinning will confirm each one's wording.
Style will be learned as ordinary memories, which the observer marks and which ride beside
the pins in one bounded slot. The fields and the slot will reach understanding and planning,
and the fields will reach the observer, all through a new store behind a new contract. No
model will edit any of it: the person, with a yes where Aether proposes a change, does.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the authorization to
> ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule
> 5, ADR-0015 §5).

> **Normative.** The implementation is cut into lanes by the dispatcher under ADR-0137, as
> §11 sets out, and each lane keeps the gate green.

### 2. One person model per person

> **Normative.** Everything this decision keeps is keyed by a **person**: a record with a
> stable id, a role and the instant it was created. The store holds one person, the owner,
> created when the store is first created, and no lane adds another person before a decision
> on members does ([#691](https://github.com/leonapivato/ai-assistant/issues/691)).

> **Normative.** Code resolves the person an activation is for from its recorded trigger,
> and never from its content (ADR-0292 §5:8). The activation is the owner's where:
>
> - its input's author is established as the user (ADR-0292 §5:4);
> - its input is a reminder or timer the user set;
> - or its input was pushed by a source the owner connected.
>
> It is no person's otherwise.

> **Normative.** An activation that is no person's, because its input's author is unknown or
> only claimed (a `ClaimedAuthor`), is given no person block, and no field of any profile
> reaches its models.

> **Normative.** A forwarded message's claimed sender selects no profile. The forward is its
> forwarder's input, and the forwarder's person applies.

> **Normative.** The observer resolves the person a leaving episode is for by the same rule,
> from the episode's recorded trigger.

**Why.** The household is the end state, and designing for the end state means a person key
on every read from the start. A single "the user" profile would be quicker now, and would
have to be rebuilt the day a second person arrives. Giving a claimed author the profile it
claims would break ADR-0292 §5:8 and show one person's pins to whoever typed their name.

### 3. The profile: five fields the person sets

| Field | What it is | Valid values |
| --- | --- | --- |
| name | What the person is called, as they write it | Text, or empty |
| address | How Aether addresses them ("Leo", their first name, or by no name) | Text, or empty |
| assistant's name | What this person calls the assistant | Text, or empty, which means `Aether` |
| time zone | The person's zone | An IANA name that `zoneinfo` resolves, or empty |
| language | The language Aether writes to the person in | Text, such as "English" or "Português", or empty |

> **Normative.** A person's profile holds exactly the five fields the table names, each set
> or empty. Each is the source of truth for itself: no memory holds it, and nothing derives
> it.

> **Normative.** Code validates each value on every write: a time zone is a name `zoneinfo`
> resolves, and every other field is text within a length bound that a composition-root
> constant holds. A write that fails validation is refused, and nothing is written.

> **Normative.** A write that sets a field to the value it already holds changes nothing and
> logs nothing.

> **Normative.** A person's profile is written only by the person, for their own, and by the
> owner, for any person's, on the panel (§8:2) or by a `set_profile` call under the person's
> yes (§8:5), and once by the hub, when the store is first created (§3:7). The observer
> writes no field (§9:7), and nothing else writes one.

> **Normative.** Every change to a field is logged with the field, the old value, the new
> value, who made it, when, and how. How is one of: on the panel; by a yes, naming the
> approval and its episode; by an accepted suggestion, naming the episode it rests on; or the
> hub's seed. The log is append-only, and is kept until the person's data is deleted.

**The time zone.**

> **Normative.** `Settings.timezone` stays as the hub-wide default. Where a person's zone is
> set, it is the zone of every time code reads for that person: planning's current time
> (ADR-0307 §6:1) and the quiet windows (ADR-0130 §6:4). Where it is empty, or the activation
> is no person's, those reads use `Settings.timezone`.

> **Normative.** When the store is first created, the owner's zone is seeded from
> `ASSISTANT_TIMEZONE` where that variable is set, and left empty where it is not. The seed
> is logged as the hub's.

> **Normative.** Reads that are about the hub, not a person, stay on `Settings.timezone`:
> the spend limit's day and the calendar reader (ADR-0093 §7b).

> **Normative.** An empty field reaches the models as not set, never as a default presented
> as the person's own. A zone that is not set is shown as not set, beside the hub's default
> zone that the current time is given in.

> **Normative.** Where a memory states a value for one of the five fields, such as an older
> "address the user as Leo", the field governs. The person block says that its fields are
> the person's current choice, and planning's instruction says that a field outweighs any
> memory stating another value for it. No memory is retired, rewritten or withheld for this,
> so its history stays.

**Language.**

> **Normative.** Planning is shown the language as the one Aether writes to the person in.
> Understanding is shown it as a hint for reading their input.

**Why a set profile, against ADR-0072's no-artifact rule (walk answer 1).** ADR-0072
rejected a profile as a cache of memories that drifts from them. These five fields are not a
cache, because nothing else holds them. They are choices, not claims that evidence supports:
"call me Leo" is neither true nor false. Code reads some of them as values, since a quiet
window needs a valid zone. They also change in place, where a memory's wording never does
(ADR-0328 §3:2). And a field the person types on a panel could not be a memory without
breaking the observer's one-writer rule (ADR-0329 §2:1). Facts about the person stay
memories.

**Why the seed reads only a variable that is set (walk answer 6).** An unset variable makes
`Settings.timezone` fall back to UTC, which no one chose. That is the zone the live hub was
found running on. Seeding it would show the hub's default as the owner's own choice, and
would stop Aether noticing that the zone was never given. The read is the same either way,
because an empty zone falls back to `Settings.timezone`.

### 4. Standing knowledge, by pinning

**Standing knowledge** is the few memories that matter in every conversation: a diet, a
standing commitment, the people someone lives with. The person chooses them by pinning.

> **Normative.** A pin is a pointer. It holds the person, the id of the memory it was made
> on, when it was made, who made it, and how: on the panel, or by a yes, naming the approval
> and its episode. Once it is removed, it also holds when. A pin copies nothing of its
> memory.

> **Normative.** Only a current memory may be pinned. It is pinned by the person, for their
> own profile, or by the owner, on the beliefs panel (§8:2) or by a `pin` call under the
> person's yes (§8:5). Pinning a memory the person has already pinned changes nothing.

> **Normative.** Pinning confirms the wording. A pin the person made on their own profile
> raises its memory to "you confirmed this wording" (ADR-0328 §6:1), by a support with the
> origin `pinned`. A pin the owner made on another person's profile adds no support.

> **Normative.** ADR-0328 §4's part table gains one part, **a pin**, addressed by the pin's
> id. Its origin table gains one origin, `pinned`, which ranks at "you confirmed this
> wording" and is not outside. A `pinned` support is `for`, backs the memory as worded, and
> is `sure`. Its `when` is the instant the pin was made, and it carries no about-when and no
> source details.

> **Normative.** A `pinned` support is added only to the memory its pin was made on, and
> only where the person-model store holds the pin when the support is added, whether or not
> the pin has been removed since and whatever the memory's status has become since: the
> confirmation is earned when the pin is made. The observer's code checks both before the
> write, in place of ADR-0328 §4:7's check that a support's episode is held.

> **Normative.** Only the observer adds a `pinned` support (§9:6).

> **Normative.** Unpinning removes the pin from the slot and erases nothing. The store keeps
> the pin, marked removed, so a support pointing at it still resolves. The memory stays as
> it is, and so does its `pinned` support (ADR-0328 §4:9, §5:5), so its standing does not
> fall. Erasing a memory is the beliefs panel's Forget.

> **Normative.** A pin on a memory that is ended or wrong and names a successor shows the
> successor, following the chain to a current memory. The pin is not rewritten, and it adds
> no support to a successor. A pin whose chain reaches no current memory is shown in no
> block, and the panel shows it as no longer current until it is removed.

> **Normative.** Forgetting a memory removes every pin and style mark on it. A pin or mark
> whose memory the store no longer holds is shown nowhere.

**Why a pin confirms (walk answer 2).** By the human-assistant test, pointing at a note and
saying "always keep this in mind" endorses what it says. The panel's pin control shows the
wording and says that pinning confirms it (§8:2), so what the person endorses is the text
they were shown. The support is the same kind of evidence a yes to a shown question is
(ADR-0328 §4:5), reached by a different act.

**Why only the observer adds the support.** ADR-0329 §2:1 makes the observer the one writer
of memories. A pin is an act on the profile, and the support it earns is added by the
observer's next run (§9:6). A writer of its own, named `pin`, would be quicker, at the cost
of a second writer for a rule that is only days old (Alternatives).

**Why a pinned memory may later be retired only as a confirmed one is.** Once confirmed, a
memory is not ended by a lower-standing support (ADR-0328 §6:5). A later "I'm not
vegetarian any more" raises a conflict question, and a yes to a question showing the
replacement retires it (ADR-0329 §12:4, §13:1). That is what a good assistant does with a
note you asked them always to keep in mind: they check before dropping it.

### 5. Style, learned rather than set

> **Normative.** A style preference is a memory like any other. The observer learns it
> under ADR-0329, from what the person says, where an explicit request weighs most (ADR-0329
> §11:1), and from how they react. It shows in the beliefs panel, and is corrected or
> forgotten there as any memory is.

> **Normative.** No field, setting or dial holds a style, and there is no numeric style
> setting.

> **Normative.** The person-model store keeps a **style mark** on each memory the observer
> judges to state how the person wants Aether to speak to them (§9:4). A mark is a pointer
> and copies nothing, it follows a successor as a pin does (§4:8), and the person removes it
> on the panel. A memory whose mark the person removed is not marked again.

> **Normative.** A request about the present exchange alone, such as "be brief this time",
> is not a style preference, and the observer marks no memory for it. Handling it is the
> controller's pending mode, pick 4 of #3257, and this decision decides nothing about it. A
> preference stated for from now on is kept under ADR-0329 §11:1 and marked.

> **Normative.** The register a moment calls for, such as a quick text or bad news, stays
> understanding's reading. Planning applies it over the person's learned style.

> **Normative.** Aether's stable core is the planning template's (ADR-0334), and is the
> same for every person. Planning's instruction says that no style preference, pin or field
> changes what is true, what Aether judges best, or any rule, and that Aether never claims to
> be human. The wording is the template's.

**Why no dials (walk answer 4).** A good assistant does not hand you dials. They notice that
you like short answers, that you joke back or don't, and that a serious matter calls for
another register. They take it when you tell them ("just the gist"), and now and then they
ask when unsure. Memories already do all of that, on the path ADR-0329 built, so nothing new
is needed to store a style. The mark is what lets a style preference reach planning on every
activation, without depending on recall to find it.

### 6. The kept-in-mind slot, and its budget

The **kept-in-mind slot** is the part of the person block that holds memories: the pins
(§4) and the style memories (§5).

> **Normative.** The slot is bounded by a character budget that a composition-root constant
> holds, initially 1,600 characters (about 400 tokens), measured over the wordings it
> shows.

> **Normative.** The slot shows the pinned memories first, oldest pin first, then the style
> memories, the most recently marked first, each memory once. It stops before the first
> memory that would exceed the budget, and says how many memories it left out.

> **Normative.** A pin is refused, with nothing written, where the wordings of the memories
> the person's pins show, together with the new one, would exceed the budget. The panel and
> the call's result say so. The caller checks this against the memory store before the
> write.

> **Normative.** The slot shows no memory that rests on outside content (ADR-0328 §7:6,
> §15:6). A pinned memory that does enters the slot once its `pinned` support has put it in
> band `ASSERTED`. The panel shows the memories the slot leaves out, and why.

> **Normative.** The record rule (ADR-0217 §2) is applied to the slot's memories, and to the
> memories of pin suggestions (§7:9), where the block is assembled, ahead of understanding
> and planning, as it is applied to recall's records.

**Why one budget, not a count (walk answer 3).** A count of 20 bounds nothing that matters:
20 long memories cost as much as a hundred short ones. A budget bounds what every call pays.
Pins go first because they are the person's explicit choice. Style fills what is left, so a
person whose pins fill the budget sees, on the panel, which style memories were left out.

### 7. Where it reaches the models

| Stage | The five fields | Pinned memories | Style memories | Suggestions |
| --- | --- | --- | --- | --- |
| understanding | yes | yes | no | no |
| planning, every round | yes | yes | yes | yes |
| observer, scout and commit | yes | no | no | no |
| digesting, the tidy-up, the matters pass, the reconciler | no | no | no | no |

> **Normative.** Code assembles one **person block** for an activation's person, from the
> person-model store and the memory store, with no model call, once per activation before
> understanding. The same block reaches every planning round of that activation, except as
> §7:10 drops from it.

> **Normative.** Understanding receives the person block's five fields and its pinned
> memories, and nothing else of the person model.

> **Normative.** Planning, in every round, receives the person block's five fields, its
> whole kept-in-mind slot, and the person's pending suggestions (§9:2, §9:5) that §7:9
> admits, each marked as a suggestion and not as the person's profile, newest first, up to a
> number a composition-root constant holds.

> **Normative.** The observer receives the five fields of the leaving episode's person, and
> nothing else of the person model.

> **Normative.** No other stage is given any part of the person model. A recorded call's
> request that ADR-0337's follow-up or ADR-0335's replay re-sends whole is that call's
> request, and is not a further stage given it.

> **Normative.** The person block is data, rendered by code into the stage's data and never
> into an instruction template (ADR-0334). A field or a style memory is rendered as the
> person's own preference, never as an instruction to the model.

> **Normative.** For understanding, a memory the block shows is labelled `M`, in one
> sequence with recall's `recalled` section, the block's memories first. A recalled record
> the block already shows is rendered there only, and not again in `recalled`. For planning,
> a memory takes its label the first time planning is shown it (ADR-0307 §5:1).

> **Normative.** Planning's instruction says to use what the person block holds where it
> helps, as someone who knows the person would, and not to recite it. It says to address
> the person by name as a person would, not in every message. And it says to raise a
> suggestion only where it bears on what is being done, and only by asking with a
> `set_profile` or `pin` call. The wording is the template's.

> **Normative.** A suggestion reaches planning only where nothing in it rests on outside
> content. A field suggestion reaches it only where none of the parts it rests on has an
> outside origin, as code sets origins from the episode's record (ADR-0328 §4:2). A pin
> suggestion reaches it with its memory, labelled as planning labels a memory (ADR-0307
> §5:1, ADR-0328 §15:5), and only where that memory is current, does not rest on outside
> content (ADR-0328 §15:6) and passes the record rule (§6:5). Every other suggestion is
> shown on the panel alone, marked as resting on outside content where it does.

> **Normative.** Before each planning round, the first included, code drops from the block
> every memory the memory store no longer holds, so a memory forgotten while the activation
> runs reaches no later request.

Within a stage's data, the person block comes before the parts that change from round to
round, so that it caches across rounds
([#3084](https://github.com/leonapivato/ai-assistant/issues/3084)).

**Why each stage gets what it gets.** Understanding needs the name, so it can tell that "Leo"
in a forwarded message means the person, and the pins, so it can resolve "my sister".
Planning writes the reply, so it needs all of it. The observer needs the name, so that it
does not commit a memory restating a field (§9:3), and the zone, to turn "next Friday" into a
date. The observer does not need the pins: its own relevance search finds related memories
(ADR-0329 §8:1).

**Privacy is the simple rule for now.** The fields go to the models on every activation of
that person, and today's withholding rules are unchanged: the slot's memories pass the
record rule (§6:5), and every place that exists today is private to the owner. What a shared
or spoken place may show of the block is the privacy redesign's (§12).

### 8. The panels and the capabilities

> **Normative.** `AssistantEngine` gains members that:
>
> - read a person's model, which is the fields, the change log, the slot with its fill and
>   what it left out, the pins no longer current, the style marks and the pending
>   suggestions;
> - set or clear a field;
> - pin and unpin a memory;
> - remove a style mark;
> - and accept or dismiss a suggestion.
>
> The change advances `PROTOCOL_VERSION` (ADR-0124 §9). Exact names and shapes are the
> implementing lane's.

> **Normative.** The web page gains an **About you** panel. It shows the fields, which the
> person edits there, the change log, the kept-in-mind slot with its fill, the style
> memories, each with a remove control, and the suggestions, to accept or dismiss. The
> beliefs panel gains pin and unpin on each current memory, and a pin control that says
> that pinning confirms the wording shown.

> **Normative.** A person's model is shown only to that person and to the owner.

> **Normative.** Planning gains three capabilities:
>
> - `set_profile`, which sets one field to a value, or clears it;
> - `pin`, which pins one memory, named by its `M` label;
> - `unpin`, which unpins one.
>
> Each declares (ADR-0306 §2): its effect is the assistant's own records, it is safe to
> repeat, it never leaves the hub, its outcome is never unknown, and its result carries no
> outside text. Each runs directly against the person-model store (ADR-0306 §3:3).

> **Normative.** Authorizing rules, by rule and with no model, that every `set_profile`,
> `pin` and `unpin` call needs you. Under a yes the call runs as ADR-0321 §4 decides for any
> approved call. These three calls are a source of *needs you* beside the policy's confirm,
> the stand-in's and `remember`'s *confirm* (ADR-0321 §4:4), with the policy's recorded
> allow as the deciding decision (ADR-0321 §4:17).

> **Normative.** The exact line (ADR-0321 §2:5) of a `pin` or `unpin` call shows, in place
> of the memory's label, the memory's wording as the store holds it when the round is
> recorded. ADR-0321 §2:7's test reads that wording as the argument the call sends.

> **Normative.** A `set_profile` call whose value fails §3:2, and a `pin` call that §4:2 or
> §6:3 refuses, are not done, and the result gives the reason.

> **Normative.** A pending suggestion is accepted when its field takes its value, or its
> memory is pinned, by any route. Code marks it so in the same write.

**Why a yes for every change Aether proposes.** The profile and the pins reach every prompt,
so one misreading changes every reply until someone notices, and one yes is cheap. A
forwarded "call me X" from someone else changes nothing. Neither does a page that tells
Aether to remember something: only input that carries the user's authority approves
(ADR-0321 §3:3).

### 9. The observer

> **Normative.** The observer reads the five fields of the leaving episode's person (§7:4),
> beside what ADR-0329 §8:1 names, and both its steps are given them: the scout, and the
> commit step beside what ADR-0329 §9:3 gives it.

> **Normative.** The scout may propose a **field suggestion**: a field and a value, naming
> the episode and the part it rests on. Code validates it (§3:2) and records it as pending,
> except where the profile already holds that value, an equal suggestion is pending, or the
> person has dismissed an equal one. A suggestion changes nothing in the profile.

> **Normative.** A finding whose claim only restates a value of one of the five fields, such
> as "the user's name is Leo", is not kept as a memory, whatever ADR-0329 §11:1 would
> otherwise keep. Where the profile does not hold that value it becomes a field suggestion,
> and otherwise nothing is written. A finding that implies a field without restating it, as a
> move implies a zone, is kept as ADR-0329 rules, and may give a suggestion beside it.

> **Normative.** The commit step, for each memory it creates or adds supports to, says
> whether its claim states how the person wants Aether to speak to them. Where it does, code
> records a style mark on that memory, unless the memory is already marked or the person
> removed its mark.

> **Normative.** The commit step may also propose a **pin suggestion** for a memory it
> creates or adds supports to, where the memory matters in every conversation. Code records
> it as pending, except where the memory is pinned, an equal suggestion is pending, or the
> person dismissed an equal one. A pin suggestion whose memory is not current is shown
> nowhere.

> **Normative.** Each observer run, before its episodes, adds a `pinned` support (§4:4) for
> every pin that a person made on their own profile, removed since or not, whose memory the
> store holds, and which no support of that memory points at yet. It writes through the
> write stage by ADR-0328 §11:3's operation member, one add support each, conditional on the
> revision read, with no model call. A write that fails is tried again on the next run, and
> the pass counts toward no model-call budget (ADR-0329 §16:9).

> **Normative.** The observer writes to the person-model store only suggestions and style
> marks. It writes no field, no pin and no change-log entry.

> **Normative.** The observer holds the person-model store by injection, beside what
> ADR-0329 §15:1 names.

> **Normative.** Before a write that ends, marks wrong or replaces a memory (ADR-0329 §12:4),
> the observer adds the `pinned` support of every pin on that memory that lacks one, as the
> pass of §9:6 does, and reads the memory again, so the retirement is ruled against the
> standing the pins give it (ADR-0328 §6:5).

> **Normative.** A retirement written while a pin on its memory was being made, before that
> pin's support, stands. The pin's support is still added to the retired memory, and the pin
> follows the successor (§4:8).

A suggestion is a background finding, so it messages no one (ADR-0329 §13:6). It shows on
the About you panel, and planning sees it in the person block (§7:3), where it is mentioned
naturally if it comes up.

### 10. The store and its contract

> **Normative.** `PersonModelStore`, a new `Protocol` in `core/protocols.py`, is the only
> route to the person model. It is implemented in `memory/`, as a store of its own in the
> hub's data directory and outside `MemoryStore`'s contract, so ADR-0328 §2:1 and ADR-0329
> §2:1 are unchanged.

> **Normative.** Its members:
>
> - read a person with their profile, pins, style marks, pending suggestions and change log;
> - write one field, recording the change-log entry in the same step;
> - add and remove a pin;
> - add and remove a style mark;
> - record a suggestion, and accept or dismiss one;
> - and export and clear.
>
> Each member that writes does so in one atomic step. Exact signatures are the triad lane's,
> within this list.

> **Normative.** The store holds no memory wording, no episode text and no copy of any
> record of another store: only the person, the fields, the change log, and pointers to
> memories and episodes.

> **Normative.** The person model's types are pydantic models in `core/types.py`: the
> person, the profile, a closed enumeration of the five fields (added to and never renamed),
> a change-log entry, a pin, a style mark and a suggestion. Exact names are the triad lane's.

> **Normative.** Its export carries every record it holds, and its clear erases them all.
> Deleting the owner's data destroys it with the rest of the data directory (ADR-0126 §1).

> **Normative.** It is a store under ADR-0326. The lane that adds it adds it to the upgrade
> check (ADR-0326 §7:3), and every later schema change to it ships its upgrade (ADR-0326
> §4:1).

### 11. Delivery

The lanes, each after this decision merges `Accepted`:

1. **The contract, with its first caller (ADR-0137 §2):**
   - `PersonModelStore` and its types;
   - the conformance suite and the canonical fake;
   - and, in `orchestration/`, resolving the person and assembling the person block for
     understanding and planning (§2, §6, §7), built and tested against the fake.

   The block is the caller whose demands shape the contract: it reads every part of it the
   models see, follows pins through successors, applies the budget and the record rule, and
   leaves out what rests on outside content.
2. **The SQLite store in `memory/`:** creating the owner's person and the seed (§3:7) and
   the wiring, in `app/`, with the store added to the upgrade check (§10:6).
3. **The `pinned` part and origin:** in `core/types.py` and the memory store, as a schema
   change with its upgrade and test (ADR-0326 §4:1, §4:2).
4. **Orchestration's other consumers:** the three capabilities and their *needs you*
   (§8:4–§8:8), and the person's zone on planning's clock (§3:6).
5. **The observer (§9).**
6. **The engine's members, the wire and the panels (§8:1–§8:3).**
7. **The quiet windows in the person's zone (§3:6).** The dispatcher may fold this into
   lane 2.

> **Normative.** Lane 1 merges before lanes 2, 4, 5, 6 and 7, and lane 3 before lane 5. Each
> lane that consumes the contract is briefed after lane 1 has merged (ADR-0137 §4:1).

> **Normative.** The person model goes live on a person's hub in one deploy, after the last
> of its lanes has merged. No build that offers pinning, on the panel or as a capability, is
> deployed to a person's hub before the observer's pin pass (§9:6) is in it.

> **Normative.** Lane 1 adds synthetic prompt cases (ADR-0337 §3) for at least three things:
> a greeting answered without reciting the profile, a pinned memory used without being
> announced, and a style memory that does not override a rule.

### 12. What this decision does not decide

| Not decided here | Why it waits |
| --- | --- |
| The situation block: local time and weekday, the time since the last exchange, the place's affordances, how the input came, and what is pending (#3255's pick 4) | Its own decision, after this one merges (walk answer 8). The proposal's text is kept by the coordinator |
| A one-off style request, as the controller's pending mode (#3257's pick 4) | The modes decision; until it exists, a one-off is planning's reading of the input |
| A second person: who they are, how they are enrolled, and what the owner sees of theirs | The members design ([#691](https://github.com/leonapivato/ai-assistant/issues/691), ADR-0217 §12) |
| Boundaries for autonomy and for speaking first | Authority, which the owner designs |
| What a shared or spoken place may show of the person block | The privacy and audience redesign |
| Whose memories are whose (`about_person`) | The design of other people (ADR-0328 §3:6) |
| Further profile fields, pronouns among them | A field takes a reader and a reason. The coordinator's comment on #3255 named pronouns in passing, and the walk did not take them up |
| Retiring a suggestion when the person declines planning's question | A "no" approves nothing and is not recorded as a refusal (ADR-0321 §3:7). For now the panel dismisses a suggestion |
| The calendar reader's and the spend limit's day in a person's zone | They are about the hub while there is one person (§3:8) |
| A self model beyond a name, such as a voice for spoken replies | Voice returns first ([#2889](https://github.com/leonapivato/ai-assistant/issues/2889)) |
| The `VISION.md` Principle 2 sentence on the profile | The coordinator narrows it after this merges (walk answer 1). No lane edits it under this decision |

> **Normative.** Each item the table names takes a decision of its own before any lane
> builds it.

### 13. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0005 | §2's *not through separate stores or Protocols*, for the five fields alone: they are held in a store of their own, behind a Protocol of their own | §3:1, §10:1 |
| ADR-0072 | §1's *no `UserProfile` type, no `UserProfileStore` Protocol, and no second collection of user facts*, and §8's first two declines (a `UserProfile` type or artifact; a second store or store Protocol), for the five fields alone. Pins and style marks point at memories and copy no fact, so they are no second collection | §3:1, §4:1, §5:3, §10:1–§10:3 |
| ADR-0130 | §6:4's *read in `Settings.timezone`* and *no second timezone source is introduced*: quiet windows are read in the zone of the person they are for, and in `Settings.timezone` where that is empty | §3:6 |
| ADR-0217 | §2:5's *no new site* half, for one further site alone: the person block's memories, those of its kept-in-mind slot and of its pin suggestions, ahead of understanding and planning | §6:5 |
| ADR-0276 | §1:5's *no retrieved memory* and *nothing else*, in the addition alone: the person block's five fields and pinned memories | §7:2 |
| ADR-0281 | §7:2, in the addition alone: the person block's memories are labelled `M` first, the `recalled` section's numbering continues after them, and a recalled record the block shows is rendered there only | §7:7 |
| ADR-0307 | §6:1, in the addition alone: the person block's five fields, its slot and the pending suggestions, with the current time given in the person's zone | §3:6, §7:3 |
| ADR-0321 | §2:5 and §2:7, in the additions alone: a `pin` or `unpin` call's exact line shows the memory's wording in place of its label, and the test reads it as that argument; §4:4 and §4:17, in the additions alone: `set_profile`, `pin` and `unpin` as a source of *needs you* by rule | §8:5, §8:6 |
| ADR-0328 | §4:1's points-at field and §4:2's origin table, in the additions alone: a pin as a part, and the origin `pinned`; §4:7, for that part alone: the pin is checked as held by the person-model store; §4:11 and §4:12, in the additions alone: code sets `sure` on a `pinned` support, and its `when` is the pin's instant | §4:4, §4:5 |
| ADR-0329 | §8:1 and §9:3, in the additions alone: the five fields, read by the observer and given to both its steps; §9:1 and §9:4, in the additions alone: field suggestions, pin suggestions and style marks; §9:6, in the addition alone: a support pointing at a pin; §12:4, in the addition alone: a retiring write first adds its target's pending `pinned` supports; §11:1, for a finding that only restates a field; §15:1, in the addition alone: the person-model store | §9:1–§9:6, §9:8–§9:10 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0329 §2:1 | Nothing: the observer stays memory's one writer, the `pinned` support included, and it writes the person-model store, which is not memory |
| ADR-0328 §2:1, §3:2, §4:5, §6:1–§6:5 | Nothing: the person-model store holds no memory record, no wording changes, a `confirmation` support is still added only from a question part, and standing is still computed from supports |
| ADR-0328 §15:6, ADR-0329 §4:2 | Nothing: the slot shows no memory that rests on outside content (§6:4) |
| ADR-0329 §13:4, §13:6, §18:3 | Nothing: a suggestion is not an open question and messages no one, and §18:3 bounds only what ADR-0329 itself shows |
| ADR-0306 §2, §3:3, §4:1, §4:8 | Nothing: the three capabilities declare the five properties, run against their store, and are checked by rule. Their *needs you* is a rule authorizing applies, as `remember`'s *confirm* is (ADR-0329 §5:2) |
| ADR-0321 §2–§4 | Nothing beyond the table above: the three calls are asked about and approved as any call is |
| ADR-0292 §5 | Nothing: the person is read from the author the hub states (§2:2) |
| ADR-0008 §5, ADR-0093 §7b | Nothing: `Settings.timezone` stays, as the hub's default and for the calendar reader |
| ADR-0334 | Nothing: the person model is data, and the templates stay the rules (§7:6) |
| ADR-0335 §4, ADR-0337 §6 | Nothing: a replay or a follow-up re-sends a recorded request whole, the person block in it included (§7:5) |
| ADR-0326, ADR-0126 §1 | Nothing: the new store is a store under ADR-0326, and lies in the data directory the delete destroys |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0005, ADR-0072, ADR-0130, ADR-0217, ADR-0276, ADR-0281, ADR-0307,
> ADR-0321, ADR-0328 and ADR-0329, atomically with this ADR under ADR-0070 and ADR-0082,
> preserving their ratified bodies. The replacements take effect on this ADR's ratification.

## Consequences

**What becomes possible.**

- Every exchange with the owner starts from their name, how they like to be addressed, what
  they call the assistant, their zone and their language, set by them and visible to them.
- The few memories that matter everywhere reach every reply without depending on recall,
  and the person has picked each one and confirmed its wording.
- Style is learned the way a good assistant learns it, kept on the path ADR-0329 built, and
  corrected in the panel where every other memory is.
- Planning tells the time in the person's own zone, and a hub whose variable was never set
  shows the owner that their zone is not set.
- A second person needs only a decision on members. Every read is already keyed.

**What it costs.**

- **Prompt growth.** Each understanding call and each planning round gains about 300
  characters of fields and up to 1,600 characters of slot, plus the suggestions for
  planning: at most about 500 tokens. The observer's calls gain about 300 characters. The
  block is stable within an activation, so it caches across rounds.
- **Machinery.** A new store behind a new Protocol, three capabilities, an About you panel,
  pin controls on the beliefs panel, the engine's new members and a `PROTOCOL_VERSION`
  advance.
- **Records.** Header records on ten ADRs.
- **A delay.** A pin confirms its wording at the observer's next run, not at once (§9:6). A
  pinned memory that rests on outside content waits that long to enter the slot (§6:4).
- **A suggestion can come back up.** A suggestion the person declines in conversation stays
  pending until it is dismissed on the panel (§12), so planning may raise it again in a later
  exchange that has lost the earlier one.
- **Two places can disagree for a while.** The quiet windows follow the person's zone, but
  the calendar reader and the spend limit's day stay on the hub's (§3:8). The two differ
  once the owner sets a zone other than `ASSISTANT_TIMEZONE`.

**The proposal's questions, as the walk answered them.**

| # | Question | Here |
| --- | --- | --- |
| 1 | The set profile as its own store | Yes, narrowly superseding ADR-0072 for the five fields (§3, §13) |
| 2 | Does pinning confirm? | Yes, by a `pinned` support (§4:3–§4:6) |
| 3 | The pin cap | A budget of about 400 tokens over the slot (§6) |
| 4 | Style dials | None: style is learned as memories and marked (§5) |
| 5 | The observer's suggestions | On the panel, and in planning's block (§7:3, §9) |
| 6 | The time zone | `ASSISTANT_TIMEZONE` stays as the default, and the profile overrides it (§3:6–§3:8) |
| 7 | Language | What Aether writes in, and a hint for reading (§3:11) |
| 8 | Conversion | Two ADRs. This one first, and the situation block next (§12) |

**What would reopen it.**

- A slot that the budget keeps full, so that style is routinely crowded out.
- A pin that people make without meaning to confirm what it says.
- A style mark the observer sets so loosely that ordinary facts fill the slot.
- A profile field that turns out to want evidence rather than a setting.

## Alternatives considered

- **Three style dials and a note** (the proposal's pick 5). Rejected by the walk: a good
  assistant learns style rather than handing over dials, and dials are a second store of a
  preference that memories already hold.
- **A pin as attention only, raising no standing** (the proposal's pick). Rejected by the
  walk: "always keep this in mind" endorses what the note says.
- **A cap of 20 pins.** Rejected by the walk for a size budget, which bounds what a call
  actually pays.
- **Retiring `ASSISTANT_TIMEZONE` after the seed** (the proposal's pick). Rejected by the
  walk: it stays as the hub's default.
- **Suggestions on the panel only.** Rejected by the walk: a good assistant mentions a
  change where it comes up.
- **The profile as memories said by the user** (ADR-0072 as it stands). Rejected for the
  five fields, for the reasons in §3, and kept for every fact.
- **The profile in configuration**, as `ASSISTANT_TIMEZONE` is. Rejected: configuration is
  per hub, needs a restart to change, cannot be edited on the page, and is where the live
  hub's zone went wrong unnoticed.
- **Aether setting a field from "call me Leo" with no yes.** Rejected: one misreading would
  change every reply.
- **A self-editing prompt.** Declined by the owner on 2026-10-20.
- **A `pinned` support written at once, by a writer of its own named `pin`.** Not chosen.
  It would end the delay of §9:6, but it adds a second writer of memories beside the
  observer, against ADR-0329 §2:1 only days after that rule was ratified.
- **A conversational pin confirmed through its question part**, as a `confirmation` support.
  Not chosen: the panel's pin has no question, so the two routes would earn two kinds of
  support for one act.
- **A style flag on the memory itself.** Rejected: it adds a field to every memory (ADR-0328
  §3:1) for what is a fact about how the person model reads the memory, and the person
  could not remove the mark without changing the memory.
- **A fixed second recall for style, or for standing knowledge**, with a cue such as "how
  the user likes to be spoken to". Rejected: the person can neither see nor steer it, it
  drifts as memories accumulate, and it costs a search on every activation.
- **Automatic selection by track record.** Rejected as the source of pins, because it is
  opaque. It stays open as a later reason for a pin suggestion.
- **One hub-wide profile with no person key.** Rejected: it builds "the user" in exactly
  where the household needs a key.
- **The person model in planning alone.** Rejected: understanding would then misread names
  that the block would settle.
- **The person model in the instruction template.** Rejected: it mixes data into the rules,
  and puts it on ADR-0334's override and promotion path, which is meant for rules.
