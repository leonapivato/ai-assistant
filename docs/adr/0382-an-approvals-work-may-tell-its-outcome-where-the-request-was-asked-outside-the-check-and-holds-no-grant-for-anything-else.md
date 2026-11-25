# 382. An approval's work may tell its outcome where the request was asked, outside the check, and holds no grant for anything else

- Status: Accepted
- Date: 2026-11-24
- Scope: decision D7 of milestone 21, "Every call checked" (acceptance
  [#3678](https://github.com/leonapivato/ai-assistant/issues/3678), lanes
  [#3679](https://github.com/leonapivato/ai-assistant/issues/3679)). It decides which message of an
  approval's work stays outside the check (§2), that nothing else of that work changes (§3), and
  its edges (§4). §5 records what it does to earlier decisions, §6 what building it needs, and §7
  what it leaves to others.
- Authorization: the owner's answer to one question, with the clauses' detail the coordinator's.
  The coordinator asked, 2026-11-25: "After you answer a card, may the assistant tell you the result
  where you asked: "Yes, it may" or "No, it may not"?" The owner answered, 2026-11-25: "Yes, it
  may". Just before, by the coordinator's account, the owner had asked whether the assistant chooses
  to tell the result, with nothing forced, and the coordinator had answered that this decision only
  permits the message. The owner's answer is to that question alone. Which places, the edges in §4
  and the records in §5 are the coordinator's, told to the owner in outline; the owner ruled no
  edge. #3678 records, among what the owner accepted, "A work that carries no one's authority can
  only answer in its place (ADR-0368 §3:2, §7:5): a message the owner only forwards, what an
  approval's work does beyond running its ticket, and a signal no rule covers." The coordinator
  assigned 0382 and ratifies it under the owner's delegation.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It amends who the check exempts, so it takes the adversarial and the architecture review.
- **Partially supersedes**
  [ADR-0367](0367-grants-say-who-may-do-what-and-how-sure-the-hub-must-be-every-call-is-checked-against-them-and-powers-are-handed-on-in-part.md)
  (§4:7, in the addition alone),
  [ADR-0368](0368-every-work-records-whom-it-is-for-whose-authority-it-carries-and-how-sure-the-hub-is-and-an-instruction-given-in-advance-carries-its-authors.md)
  (§7:5, in the addition alone) and
  [ADR-0370](0370-every-work-carries-a-mark-of-who-may-see-all-it-has-seen-which-starts-at-its-places-audience-and-only-shrinks-and-a-send-reaching-anyone-outside-it-needs-a-yes.md)
  (§5:7 and §5:8, each in the addition alone).

## Context

After a person answers a card, or it expires, the approval's own work plans with its input
([ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md)
§6:5) and tells the outcome with `send_text` into a place on its place list: the place the asking
activation's input came from, where it takes a message, or a task's suggested places, and the
line's chat (ADR-0361 §6:7). That input came from the approvals, which takes no message (ADR-0361
§3:6), and carries no authority (ADR-0361 §6:1; ADR-0368 §7's table: "an approval's outcome", no one, at none). So the text is
not into a place one of the work's own inputs came from (ADR-0367 §4:7), it passes the check, and
ADR-0368 §7:5 allows it nothing.

As the first deploy's rehearsal recorded it at `348ff39e7`: the round of a work that keeps a place
list carries no `input_place`, and `input_places` holds only the approvals' place
(`phase_path._input_places`), so `AuthorizingStage._message_checked` checks the text for
`CheckedFor.no_one()`, and `permission_check.check_call` returns `not_done_no_grant` beside today's
rules, which allow it. As built at `e42a3f881` the text is not even attempted: `CouldUse.shows`
shows a place only where it is among the work's own input places (`phase_path._own_places`) or in
a connection its authority could use, so the asking place is filtered from what the approval's
work is shown. No merged clause gives that work the place. Now that the check decides, a person
who approves, denies or lets a card expire is told nothing, unless the asking work still runs and
takes the outcome over (ADR-0361 §6:4). The card's in-place edit (ADR-0361 §4:5) still shows the request's
state, but not what came of running it.

**Words.** **The check**, **line** and **grant** are ADR-0367's; **work** and **carries** are
ADR-0368's; **an approval's work** is the activation an approval request's outcome starts (ADR-0361
§3:7, §6), and **the asking activation** the one the request names (ADR-0361 §2:6). A bare section
reference, such as §2:1, is to this decision's own clauses.

## Decision

We will keep outside the check an approval's work's message into a place the asking activation's
inputs came from, as if that work were the asking one answering there, and change nothing else.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision rules only which message of an approval's work stays outside the
> check. Who may answer a card and what a tap that does not answer gets (ADR-0377 §3), a forward's
> or a signal's work (ADR-0368 §7:5), and which surface shows a card are not its.

### 2. The outcome, where it was asked

> **Normative.** In an approval's work, a message into a place an input of the asking activation
> came from, its trigger's or one that joined it by an absorption or a take, stays outside the
> check and is checked by its place alone, as ADR-0367 §4:7 keeps a message into a place one of a
> work's own inputs came from. This holds alike where the request was approved, denied or expired.

> **Normative.** Code reads those places from the asking activation the request names, not one
> ADR-0349 §7:4 follows it forward to, as it stands when the approval's place list is built
> (ADR-0361 §6:7): from its running state where it runs, and its episode otherwise. They are kept
> for the work, and no model and nothing the approval's input says adds one.

> **Normative.** §2:1 widens no place a message may go into. ADR-0361 §6:7's place list still says
> where an approval's work may write, and a place §2:1 names that is off that list stays refused by
> its place check.

> **Normative.** Every other check on a message still applies to one §2:1 keeps outside: its place
> (ADR-0361 §6:7) and, once built, its work's mark (ADR-0370 §5:1).

> **Normative.** A place §2:1 keeps outside the check is one an approval's work could use, in
> ADR-0368 §8's sense: it is shown in that work's Connections section and `search_connections`
> finds it (ADR-0368 §8:2), as a place one of a work's own inputs came from is.

The ground is ADR-0361 §6:3. Code records the approval's input as meant for the asking activation,
in `continues`: the outcome is the rest of the answer to what was asked there, and the place check
already rules who can read it there. The asking work could have said it there outside the check;
the approval's work says nothing there the asking work could not. §2:5 follows from ADR-0368 §8's
own reading of *could use*, which includes a connection "which the check would not reach (ADR-0367
§4:7)", and its closing note: "A connection a work's own input came from is one it could use, since
a reply into it is outside the check."

### 3. Nothing else changes for that work

> **Normative.** An approval's work still carries no authority (ADR-0361 §6:1, ADR-0368 §7's
> table), and the check still runs for no one in it.

> **Normative.** A call an approval's work runs under its ticket is checked for its tapper, at the
> level the tap came by (ADR-0367 §5:5).

> **Normative.** Every other call an approval's work makes is not done (ADR-0368 §7:5), a text
> into any connection neither §2:1 nor ADR-0367 §4:7 keeps outside included, such as the line's
> chat where the request was not asked there.

### 4. The edges

> **Normative.** Where the asking activation's inputs came from several places, each stays outside
> under §2:1 alike, and none is preferred. Which of them an approval's work can reach is §2:3's.

> **Normative.** A place whose kind takes no message keeps nothing outside under §2:1.

> **Normative.** An asking activation the Task Scheduler started holds an input from the schedule,
> which takes no message (ADR-0350 §2:6), so §2:1 keeps no place outside for it. Its task's
> suggested places are not places its input came from: a text into one from an approval's work
> passes the check, for no one, and is not done.

> **Normative.** Where neither the asking activation's running state nor its episode can be read
> when the place list is built, §2:1 keeps no place outside, and a text the list allows is not
> done, its reason saying that where the request was asked could not be read.

> **Normative.** Where the asking work takes the approval's input over (ADR-0361 §6:4), §2 does
> not apply: that work answers as itself, its messages checked as ADR-0367 §4:7 has its own, and
> the input adds no authority and lowers no level (ADR-0368 §2:5, §4:1).

So for a task's request the outcome is told only where the task's work takes the input over and
answers as itself, its calls checked for the task's author at the level the task records (ADR-0368
§6:1, §6:2). A task's own text into its suggested place passes the check for its author; an
approval's work, carrying none, gets nothing there that the asking work lacked. Under §4:4 the
place list, built from the same read, holds no asking place either (ADR-0361 §6:7), so what is left
to refuse is a text into the line's chat.

### 5. Relationship to earlier decisions

> **Normative.** This decision partially supersedes ADR-0367 §4:7, in the addition alone: in an
> approval's work, a message into a place an input of the asking activation came from also stays
> outside the check (§2:1).

> **Normative.** This decision partially supersedes ADR-0368 §7:5, in the addition alone: its
> exception for a message ADR-0367 §4:7 keeps outside reaches one §2:1 keeps outside. §7's table
> row for an approval's outcome stands.

> **Normative.** This decision partially supersedes ADR-0370 §5:7 and §5:8, each in the addition
> alone: a message §2:1 keeps outside is checked as §5:7 checks a message into a place one of a
> work's own inputs came from, outside the grant check and against the mark as every send is, and
> is not among §5:8's other sends.

| Clause | What this decision does |
| --- | --- |
| ADR-0367 §4:7 | Partially supersedes it (§5:1) |
| ADR-0368 §7:5 | Partially supersedes it (§5:2) |
| ADR-0361 §6:1, §6:3, §6:4, §6:7 | Reads them through; no record, since no clause of them changes |
| ADR-0306 §4:7, ADR-0356 §7:7, ADR-0364 §9:3, §9:4 | Read through ADR-0367's record; no record |
| ADR-0367 §5:5, ADR-0368 §2:5, §4:1, §6:1, §6:2 | Read through (§3:2, §4) |
| ADR-0370 §5:7, §5:8 | Partially supersedes them (§5:3); §5:1's mark still applies (§2:4) |
| ADR-0368 §8:2 | Read through §5:1: its *could use* names ADR-0367 §4:7, as amended; no record (§2:5) |
| #3678's "can only answer in its place" | Not an ADR: no record; its wording is the coordinator's to edit on the owner's answer |

### 6. What building it needs

> **Normative.** Building this decision changes nothing in `core/protocols.py` or `core/types.py`.

The build hands the places §2:2 reads, which the engine reads where `_approval_context` already
reads the asking place, from `EpisodeProcessingRecord.trigger` and `.joined` or the running state,
to two consumers, both orchestration's own and no Protocol. The round an approval's work authorizes
(`RoundToAuthorize`): `_message_checked` then keeps a text into one of them outside, recorded as
`CallCheckKind.OUTSIDE`, as it does a work's own input places. And what narrows the work's shown
connections (`connections_it_could_use`, whose `CouldUse.shows` then shows them, §2:5). Keeping them
apart from `input_places`, which are the work's own, is the build's call. §4:4's reason is new text; its outcome stays
*not done: no grant covers it* (ADR-0379 §3:1).

### 7. What this decision leaves to others

- **The build:** its fields, its tests, and what it logs.
- **ADR-0377 §3:** who may answer a card, and a tap that does not answer.
- **A later decision:** telling a task's request's outcome when the task's work has ended (§4:3).

## Consequences

- Once built, a person who answers a card asked in the hub chat or on the line is told the
  outcome there, as before the check, whatever they answered.
- A text into the line's chat from an approval's work whose request was asked in the hub chat,
  which the place list allows today, is not done (§3:3); the card's edit still shows the state.
- An approval asked by a task's work is answered only by a takeover (§4:3).
- **Revisit** if an approval's work comes to carry authority, or a place list widens (ADR-0364
  §9:4).

## Alternatives considered

- **Run the outcome's text for the request's person.** Set aside: it gives authority to a work
  ADR-0361 §6:1 gives none, on an input no one sent.
- **Exempt every message of an approval's work.** Set aside: it would let the line's chat and a
  task's suggested places take a text no grant covers, which ADR-0368 §7:5 exists to refuse.
- **Rely on the takeover alone.** Set aside: the asking work has often ended, and the person is
  then told nothing.
