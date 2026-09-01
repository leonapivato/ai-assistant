r"""The model-backed observer (ADR-0077).

The production :class:`~ai_assistant.core.protocols.Observer`: it reads a bounded
batch of :class:`~ai_assistant.core.types.EpisodicMemory` records — what actually
happened — and proposes what the system should believe about the user as a
result, by prompting an injected
:class:`~ai_assistant.core.protocols.ModelProvider` for a JSON envelope and
distilling that text into :class:`~ai_assistant.core.types.MemoryUpdateProposal`\ s.

It lives in `learning` because that is the subsystem ADR-0005 §3 gives the
observations-to-proposals job, and it is the placement ADR-0077 §9.5 names.
These boundaries shape the module:

- **It holds no store and no writer.** Episodes in, proposals out; the scope of
  observation is a property of the seam rather than of this code (ADR-0077 §1),
  and the ingesting stage — never this class — puts each proposal through the
  ratified ``MemoryPolicy`` gate. ADR-0075 §2 names this producer as the paradigm
  case the gate exists for, and it is not exempt from it.
- **The citations are ours, never the model's.** The prompt labels each episode
  and the model cites labels; this module maps every label back to the id of the
  episode it actually read (ADR-0047 §2's rule applied to evidence). A model that
  can write an id can write one for an episode it never saw.
- **The confidence is ours, never the model's.** :func:`_confidence` is a pure
  function of the epistemic step and the number of distinct supporting episodes —
  no clock, no randomness, nothing from the response — so re-observing the same
  episodes cannot inflate a belief through a ``REINFORCE`` that takes the maximum
  (ADR-0077 §5, §8).
- **The model may narrow a record's placement and may never widen it**
  (ADR-0217 §4). This producer is the one the ADR names as proposing, and the
  proposal **rides the pass rather than opening a seam of its own**: it is one
  optional key in the envelope the model already fills in, so this class makes
  the provider calls it always made and no read path gains one. What a proposal
  writes is reach ``OWNER`` with setter ``PROPOSED`` and the instant of the pass;
  no value the model can emit makes a record *more* speakable, an unusable value
  leaves ADR-0217 §6's default standing, and the owner lifts the narrowing in one
  act (§7).
- **The prompt is a rendering target, and no span may write its syntax**
  (ADR-0098 §2). Every span a record controls — its ``content``, and the
  assistant half of the exchange — goes through :func:`_quoted_span` before it
  reaches a line of the batch, so no episode can open a second ``[E<n>]`` entry,
  reopen the header, or write an ``Assistant:`` line of its own. The attribution
  the batch expresses is therefore a function of the batch this module was
  handed and of nothing inside it — which is what the distinct-support count of
  the bullet above actually rests on.
- **A malformed response degrades; a model failure propagates.** Entries that
  cannot be used are discarded and *counted* rather than repaired, invented, or
  re-prompted for: an observation has nothing waiting on it, so the cheap remedy
  is a later run rather than a second call inside this one (ADR-0077 §4).

The envelope schema below is this implementation's, not the ``Observer`` seam's.
ADR-0077 §9.5 deliberately declines to ratify one — a second observer would
legitimately prompt differently, as a second ``Planner`` would — so it is fixed
here, in the lane that runs it against a real model, exactly as ADR-0047 §4 fixed
the planner's.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, assert_never
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import (
    MAX_TOPICS_PER_PROPOSAL,
    ExchangeDisposition,
    MemorySource,
    MemoryUpdateProposal,
    Message,
    ObservationOutcome,
    Placement,
    PlacementReach,
    PlacementSetter,
    PreferenceMemory,
    ProceduralMemory,
    Provenance,
    Role,
    SemanticMemory,
    TopicLabel,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import EpisodicMemory, MemoryRecord

#: The batch bound ADR-0077 §1 names and the proposal bound §2 names, as
#: defaults. Both are *also* ``Settings`` fields, so the composition root passes
#: the operator's values; these are what the class does when nobody says.
#:
#: **The proposal bound is 40 and its ground is cost, not selectivity** (ADR-0162
#: §6). Under ADR-0077 §2's warrant bar, five *was* the selectivity rule expressed
#: as a number — "a batch that genuinely yields more durable beliefs than that is a
#: batch worth observing twice". ADR-0162 §1 replaces that bar for an episode
#: recording what the user told the assistant, and the number does not survive with
#: the ground: what bounds the return value now is one pass's cost and egress and
#: nothing else. The probe measured 8.7, 9.1 and 9.0 proposals per pass over three
#: conversations at a batch of 20, under a cap of 60 that never bound; 40 is more
#: than four times that mean — two records per episode in the batch — which is
#: headroom for a stretch of unusually dense turns while staying a bound rather than
#: an absence of one.
#:
#: **A pass in which it binds is an incomplete pass, not a compliant one** (§6). The
#: cap truncates by *position* in a model's reply, and position is not a ranking:
#: under ADR-0077 §2 the tail it dropped was the least selective end of an
#: already-selected set, and under complete intake there is no selection for it to be
#: the tail of. So ``discarded_over_limit`` above zero is read as a defect with a
#: stated response — raise this bound, lower the batch size, or both — and never as
#: the intended steady state. The two knobs are a pair because raising this one alone
#: only relocates the boundary while halving the batch halves the material each pass
#: must fit.
#:
#: **The batch bound is unchanged and is coupled to it.** 40 is per call and 20 is
#: turns per call, so a deployment that raises the batch raises expected proposals
#: proportionally and will make 40 bind; no clause ties the two, because a formula
#: would ratify a linearity nothing has measured. That is what the counter is for.
DEFAULT_OBSERVATION_BATCH_SIZE: Final = 20
DEFAULT_OBSERVATION_MAX_PROPOSALS: Final = 40

#: The most decode **misses** :func:`_extract_object` tolerates in one reply
#: before giving up, for the reason ``planning.planner`` records: a failed
#: ``raw_decode`` costs work proportional to how far into the reply it reached, so
#: attempting it at every brace of a brace-dense reply is quadratic and blocks the
#: event loop. Bounding the misses keeps the scan linear.
_MAX_EXTRACTION_MISSES: Final = 256

#: This producer's confidence ladder: ``(base, ceiling)`` per epistemic step, plus
#: what one further distinct supporting episode adds. The *values* are this
#: implementation's — ADR-0077 §5 ratifies the properties and leaves the constants
#: to the lane, as ADR-0074 §4 did for capture — but the shape is contract:
#: strictly below 1.0 always, ``OBSERVED`` above ``INFERRED`` on equal support
#: (the latter took a step the evidence does not entail), non-decreasing in
#: support, under a ceiling, and a pure function of those two inputs alone.
#:
#: The ceilings are what keep the ladder honest at the top: an observation is
#: never as good as being told, however many times it recurs, and without a
#: ceiling a long enough batch would walk a derived belief up to the standing only
#: the user's own word carries.
_LADDER: Final[dict[MemorySource, tuple[float, float]]] = {
    MemorySource.OBSERVED: (0.55, 0.85),
    MemorySource.INFERRED: (0.35, 0.70),
}
_SUPPORT_INCREMENT: Final = 0.05

#: How many *distinct* supporting episodes each step needs before a belief may be
#: proposed at all (ADR-0077 §5). An ``OBSERVED`` belief restates what its
#: evidence directly shows, so one episode entails it; an ``INFERRED`` belief
#: generalises beyond the evidence, and a generalisation from a single instance is
#: the exact shape of "a single unusual interaction hardens into a permanent,
#: wrong preference" (ADR-0005 §Context).
_EVIDENCE_FLOOR: Final[dict[MemorySource, int]] = {
    MemorySource.OBSERVED: 1,
    MemorySource.INFERRED: 2,
}

#: The record kinds an observer may propose. ``EPISODIC`` is absent by decision,
#: not by omission: an episode is a record that something happened, and the only
#: thing entitled to write one is the deterministic capture path that was present
#: when it happened (ADR-0077 §2).
_PROPOSABLE_KINDS: Final = frozenset({"semantic", "preference", "procedural"})

#: How an episode's ``occurred_at`` is written into the prompt once localised: the
#: weekday, the calendar date, the wall clock and the numeric UTC offset. The
#: weekday is there for the resolution ADR-0156 §3 asks for — *"last Friday"* cannot
#: be worked out against a date whose day of week the reader has to derive — and the
#: date is ISO-ordered so it cannot be read the American way round.
#:
#: **The offset is what makes a wall clock in the fold unambiguous.** At a DST
#: fall-back the same local reading names two instants an hour apart — in
#: ``America/New_York``, ``2023-11-05T05:30Z`` and ``2023-11-05T06:30Z`` are both
#: *"Sun 2023-11-05 01:30"* — so a sub-day expression resolved against the bare
#: reading can land on either side of local midnight. The offset separates them and
#: costs six characters. What the *model* writes is prose and is its own (ADR-0156
#: §8's format clause); this is only what it is shown.
_INSTANT_FORMAT: Final = "%a %Y-%m-%d %H:%M %z"

#: What a line carries where the instant has no representation in the configured
#: calendar at all — see :func:`_localised`.
_INSTANT_UNAVAILABLE: Final = "(recorded time unavailable)"

#: The prompt's opening, which says nothing about time and is shared by both
#: variants below. After the framing come, in order: the **recording rule**
#: ADR-0162 §1 states as a producer-side obligation, the one-record-one-thing
#: clause beside it, ADR-0162 §8's boundary between what the user said and what
#: this assistant asserted, **how a belief that clears the rule is phrased**, the
#: two epistemic steps, the citation rule, ADR-0213 §4's filing words, and
#: ADR-0217 §4's placement flag.
#:
#: **The recording rule replaces ADR-0077 §2's warrant bar here** (ADR-0162 §1),
#: and the replacement is what the prompt had to carry: the measurement says the
#: filter's false-negative rate is the system's dominant loss, and the question
#: the model can actually answer from the batch in front of it is *did the user say
#: this?* rather than *would this change a later answer?*. Three of the old
#: paragraph's four sentences were the bar and are gone; "proposing nothing is a
#: perfectly good answer" is **relocated rather than repealed** (§1's third
#: paragraph) and now names filler explicitly, because unqualified beside a
#: completeness instruction it is the sentence a model reaches for when a batch is
#: dense. Nothing here states a *number*: the cap is post-hoc truncation and the
#: prompt has never mentioned it (#1029), which is exactly why ADR-0162 §6 rules a
#: binding cap a defect rather than a design.
#:
#: **The scope is not in the prompt, and that is ADR-0162 §2 rather than an
#: omission.** §1's rule reaches only an episode recording what the user told the
#: assistant, and §2 defers the carrier of that distinction to the ADR introducing
#: the second class of episode while forbidding anything to enter this payload to
#: carry it. So this prompt is written for §1's class outright, and the fail-closed
#: obligation sits on the stage that selects the batch — today the only construction
#: site for an ``EpisodicMemory`` under ``src/`` is the conversation capture path,
#: so every episode reaching here is already §1's.
#:
#: **The assistant paragraph partitions by what a record claims** (ADR-0162 §8),
#: which is the one place this text could most easily have breached §1's own
#: boundary. An act the episode witnesses — that the assistant was asked something,
#: answered, did a thing, and when — is supported by the ``outcome`` half alone. The
#: proposition inside that answer is not: adopting it would let the assistant
#: launder its own assertions into the user's model, a belief citing an episode that
#: witnesses only the *saying*. The citation clause is in the same paragraph because
#: the prompt now shows two texts under one label and ADR-0077 §5's floor counts
#: labels — a split episode would let one episode supply the two distinct supports
#: an ``INFERRED`` record owes.
#:
#: **The specificity paragraph is about wording, not about which beliefs**, and the
#: order is what keeps it so: it opens on "when you do propose a belief", it sits
#: after the paragraphs that decide whether, and it closes by handing that decision
#: back. Its closing sentence used to add "and a retelling of what happened is
#: refused however specific it is", which was the bar speaking; under §1 a record of
#: what happened is the point, so the clause is dropped rather than reworded. Its
#: exclusion of incidental particulars is scoped in terms to *this belief's
#: sentence*, because under §1 the fellow diner the third sentence keeps out of a
#: vegan-meal preference is themselves a thing the user named — and §1 records that
#: as a belief of its own. The two rules are about different questions and now have
#: to say so; ADR-0162 §3 rules the growth in third-party content deliberate and
#: leaves the subject axis where ADR-0100 put it.
#: It is there because the void run's dominant loss is a belief that cleared the
#: bar and then abstracted the evidence away — *"Caroline is passionate about
#: supporting the LGBTQ+ community"* distilled from an episode naming the group,
#: the speech and the day, citation intact and every particular gone, so the
#: answerer correctly declines a question the evidence could have answered
#: (62 of 149 records on #1029's paired prefix; 416 of 1,540 in pilot 1). ADR-0156
#: §6's first bullet names that loss and scopes it out of *that* decision as an
#: ingestion question — which is what this paragraph is, and why it changes no
#: ratified clause: ADR-0077 §2's bar is untouched, and a `content` sentence is
#: wholly model-authored prose (ADR-0156 §1), so what is written here is guidance
#: on writing it, not a new field, predicate or licence.
#:
#: **Times are carved out of it in terms, because the two rules would otherwise
#: read as contradicting each other.** "Keep the particulars the evidence gives"
#: would, applied to an episode reading *"on 7 May I told Alex I enjoy climbing"*,
#: invite the mention date onto a trait — which is exactly the naive implementation
#: ADR-0156 §2's third clause exists to refuse ("a lasting trait acquires no date
#: from the day it happened to be mentioned"), and it would cost the embedding
#: dilution §2 priced. So the enumeration names no dates, and the paragraph hands
#: every time question to the section that follows it in both assembled variants.
#: A date the belief *is* entitled to state is not lost by the carve-out: §2's
#: second clause requires it, in the section that decides it, and that section is
#: more precise about which date than this paragraph could be.
#:
#: **The particulars are scoped to the belief, and the incidental ones are excluded
#: in terms, for the same reason at a different seam.** An unscoped "keep the
#: particulars the evidence gives" would, on *"at Acme's dinner with Priya I
#: realised I prefer vegan meals"*, retain Acme and Priya inside a belief neither
#: identifies nor qualifies — third-party personal data kept at indefinite retention
#: because it shared a sentence with something durable. That is ADR-0077 §2's
#: transcript failure mode arriving one belief at a time instead of twenty, and it
#: is more than ADR-0004 §7's minimisation allows. The test is the particular's
#: *role*, not its category: a named person who is the thing believed (*"the user's
#: manager is Priya"*) is kept by the first sentence, and the same name as a fellow
#: diner is dropped by the third.
#:
#: **And the paragraph adds no particulars, which is the failure mode specific to
#: asking for them.** An instruction to be concrete is an invitation to be concrete
#: beyond the evidence — to read one climbing session into *"goes every Tuesday"*,
#: which would be a fabricated routine wearing an ``OBSERVED`` label the citation
#: check cannot catch, since that check verifies the episodes exist and not what
#: they support. Two things answer it. The paragraph says it in terms — a particular
#: not in a cited episode is an invention, and one occasion is not a routine — and
#: **the worked example's two halves make the same claim**, differing only in the
#: particular: *"owns a 2012 Honda Civic"* against *"owns a car"*, one predicate,
#: one thing believed, one more detail. That shape is what makes it safe to imitate,
#: and it took three review rounds to find: every pair that changed predicate as
#: well as detail (*"climbs at Boulder Barn"* against *"enjoys climbing"*) could be
#: paired with some episode supporting the vague half and not the specific one, so
#: the example modelled a leap rather than a rewording. Here the only thing the
#: preferred half adds is the particular, which the sentence beside it already
#: conditions on the evidence. The example is the one line of a prompt a model
#: imitates rather than reasons about, which is why it is pinned by exact text
#: below. Beyond the prompt, the mechanism still bites where the model labels the
#: leap honestly: ``INFERRED`` from a single episode is refused by the evidence
#: floor (§5, and ``_EVIDENCE_FLOOR`` above), which is why the paragraph sits
#: directly above the two epistemic steps rather than anywhere else.
#:
#: **The placement paragraph is last, and it is asked per belief rather than per
#: category** (ADR-0217 §4). It comes after everything that decides *whether* a
#: belief is proposed and *what it says*, because it decides neither: a flag on an
#: entry changes who may receive the record and nothing else, and putting it
#: earlier would invite a model to weigh disclosure when deciding whether to
#: record at all — which would silently reintroduce the selectivity bar ADR-0162
#: §1 replaced, and lose the belief instead of narrowing it.
#:
#: **It states the effect, the asymmetry and the correction, because all three
#: are what calibrate it.** A model told only "flag the sensitive ones" has no way
#: to price a mistake. It is told that a guarded belief is still recorded,
#: retrieved and spoken where the user alone is listening (ADR-0217 §2's bounded
#: channel, where nothing is withheld on this field's account); that the flag can
#: only narrow, so there is no value it can emit that makes a record more
#: speakable than ADR-0199 §3 already places it (ADR-0217 §6); and that the owner
#: lifts it in one act (§7) — which is ADR-0217 §4's own answer to ADR-0130 §11
#: put in front of the thing making the judgement. The closing sentence is the
#: counterweight and is deliberate: over-flagging is the failure this text can
#: actually cause, it is silent, and it costs exactly the exit test ADR-0199 §3
#: and ADR-0217 §6 were written to keep answerable.
#:
#: **Nothing here decides a class, which is what keeps it outside ADR-0199 §2's
#: prohibition** — and §4 states the ground rather than leaving it to be
#: reconstructed. §2 forbids deciding *a class* by reading content, at a supply
#: site, on every read. This is a producer recording a value once, over the record
#: it is about to write; §2's classes are unmoved, ADR-0199 §3's placement of them
#: is computed exactly as it was, and every later read is a field read.
_PROMPT_HEAD: Final = """\
You are the observation stage of an AI assistant. You are shown a batch of \
recorded episodes — things that happened — and you propose what the assistant \
should durably believe about the user as a result.

Record what the user told you, completely. Propose one belief for each distinct \
thing the user stated that a later question could ask about: an event that \
happened, a person, place, organisation or thing they named, a durable fact, a \
preference, a workflow they follow. That a thing merely happened is not a reason \
to leave it out, and neither is a judgement that it may not matter later — the \
user chose to tell an assistant whose job is to remember them, and that is the \
signal you are reading. Pass over pure conversational filler — a greeting, an \
acknowledgement, a restatement of something you yourself just said — and pass \
over nothing else. Proposing nothing is still the right answer for a batch that \
is only filler.

One belief states ONE thing. Do not fold several distinct facts or events into a \
single sentence: the unit is the thing a later question could ask about, because \
that is the unit a search returns.

An episode may also carry what the assistant said back, on an "Assistant:" line. \
That half is evidence about what HAPPENED, never about what is TRUE. You may \
propose a belief about the assistant's own act — that it was asked something, \
that it answered or did a particular thing, and when. You may NOT take a claim \
the assistant asserted and record it as a fact about the world or about the user; \
record such a fact only where the USER stated it, and the assistant's words may \
then corroborate it but never stand in for it. Either way you cite the episode \
whole: one episode is one label and one support, whichever half of it you read.

When you do propose a belief, keep the concrete particulars the belief is about — \
the proper names, places, organisations and quantities that identify or qualify \
the thing believed — rather than abstracting over them. Two ways of writing the \
same belief are not equally useful: "owns a 2012 Honda Civic" beats "owns a car". \
Keep only those: whoever happened to be present, wherever the conversation \
happened and whatever else was going on are the exchange, not this belief, and \
are left out of its sentence — which decides what THIS belief says and never \
whether a person or place the user named gets a belief of its own. Add nothing \
the evidence does not give — a particular you cannot point to in a cited episode \
is an invention, and one occasion is not a routine — and where it gives no \
particular the belief is about, state the trait alone. Times are the one \
exception: the section below decides which of them a belief states, and keeping \
the particulars is never a reason to date a belief it says states none. This \
governs how a belief is written, never whether: the rule above decides that.

Each belief takes one of two epistemic steps:
- "observed" — the cited episodes directly show it. One episode may be enough.
- "inferred" — you generalised beyond what the episodes show. Cite at least TWO \
different episodes; a generalisation from a single episode will be discarded.

Cite episodes by the labels in brackets, exactly as they appear. Never invent a \
label, and never cite one that is not in the batch.

Say what each belief is ABOUT, in its `topics` list: at most FOUR short filing \
words, the ones under which someone looking for "everything about X" should find \
it later. Each is lower case, one to a few plain words separated by single \
spaces, at most 64 characters, with no leading or trailing space — "health", \
"sleep", "car maintenance". Use the SAME word for the same subject across every \
belief in this reply, and do not repeat a word within one belief. Where no short \
honest word fits, give an empty list: a label stretched to fit is worse than \
none, and the list is how the belief is filed rather than a second statement of \
what it says.

Last, set a belief's `guarded` flag where hearing it said out loud, in a room \
where someone other than the user might be listening, would be unwelcome to \
them — the kind of thing about health, money, relationships, convictions or \
trouble that a person tells one confidant and not a room. A guarded belief is \
still recorded, still retrieved and still said back where the user alone is \
listening; the only thing it loses is being spoken where anyone nearby would \
hear it. The flag goes one way in your hands: you can hold a belief back, you \
can never make one more speakable than it already is, and the user can lift your \
flag on any belief in a single act. So flag what a careful person would not want \
overheard and leave everything else unflagged — most of what anyone says is \
ordinary, and flagging the ordinary leaves the assistant unable to answer aloud \
the questions the user most wants answered."""

#: What a producer holding the zone says about time (ADR-0156 §2, §3). Four things,
#: in the order they bite: what the rendered instant *is*, when a belief states a
#: time, that a relative expression is resolved here and never written through, and
#: when a belief states none. The last paragraph is §2's fourth clause — the anchor
#: widens the utility bar by nothing.
#:
#: **That last paragraph is stated symmetrically, and the symmetry is a fix rather
#: than a softening.** §2's fourth clause says the bar is applied *unchanged*, and
#: unchanged cuts both ways: a date is no reason to propose a belief the bar
#: refuses, and the want of one is no reason to withhold a belief the bar admits.
#: Shipped as a brake alone, the section reads as four restraints in a row —
#: "state none", "acquires no date", "not worth holding with one" — arriving after
#: a head that has already said "do not summarise", "do not propose what merely
#: happened" and "proposing nothing is a perfectly good answer". The measurement
#: says the cumulative reading is the one a model takes: re-ingesting LoCoMo
#: conv-26 three times per tree, the pre-anchor tree distilled {28, 26, 25} beliefs
#: against this tree's {19, 22, 24} — non-overlapping ranges, about 18% fewer, with
#: preferences hit hardest (6/7/5 against 2/5/4) — and the time section is the only
#: prompt text that differs. The proposal cap binds equally on both and is not the
#: cause. So this restores the bar the anchor accidentally narrowed; it does not
#: move it, which §2's fourth clause and ADR-0156 §6 would both forbid.
_PROMPT_TIME_WITH_ZONE: Final = """\
Each episode is shown with the local time it was RECORDED, in {zone}. That is \
when the user spoke, not when the thing they describe happened.

Where the cited episodes establish when something happened — an event the belief \
asserts, or the onset or change of a state it asserts — say so in the belief's \
own sentence, as a calendar date: "on 7 May 2023", "in the week before 9 June \
2023". Where an episode dates it only relatively — "yesterday", "last weekend", \
"last Friday" — work the date out against that episode's recorded time and write \
the result. Never write the relative words themselves: the episode they point at \
will not outlive the belief. Be no more precise than the evidence is; a week or a \
month is a good answer where that is all the evidence gives.

Where the cited episodes establish no such time, state none. The recorded time is \
not one on its own: a lasting trait acquires no date from the day it happened to \
be mentioned, and a date beside one would be read as an event.

A date is never a reason to propose a belief, and the absence of one is never a \
reason to withhold one. The bar above is unchanged, in both directions: if the \
belief would not be worth holding without its date, it is not worth holding with \
one — and a belief that clears the bar is proposed whether or not the evidence \
lets you date it. These instructions change what a belief says, not how many you \
propose."""

#: And what a producer *without* the zone says (ADR-0156 §3's second clause). It is
#: shown no instants at all — :func:`_render_batch` withholds them — so this asks
#: for no resolution, and forbids in terms the two fallbacks a model would otherwise
#: reach for. A date the evidence states outright needs no calendar, so §2's second
#: clause still applies to it.
#:
#: This variant carries the same counterbalance as the zoned one, for the same
#: reason and in its own terms. It has no fourth-clause paragraph to restate —
#: nothing here invites a date the bar would refuse — but it is *more* restraint per
#: word than the zoned text, not less: three prohibitions and no permission. The
#: measured sparsity was not run against this variant and could not have been:
#: ``Settings.timezone`` is a non-optional field defaulting to ``"UTC"``, so the
#: composition root and the benchmark harness both build the zoned producer and only
#: a direct construction reaches this text. The counterbalance here is therefore
#: prophylactic — it states the half of §2's fourth clause that holds whatever
#: calendar the producer has, so the two variants cannot drift on the point.
_PROMPT_TIME_NO_ZONE: Final = """\
The episodes are shown without the times they were recorded, so you cannot know \
what day any of them falls on. Do not work a date out from context, and do not \
guess one.

Where a cited episode itself names a calendar date for something the belief \
asserts, state that date in the belief's own sentence. Otherwise state no time, \
and never write a relative expression such as "yesterday" or "last week" — it \
would point at an episode the belief will outlive.

Stating no time is never a reason to withhold a belief. These instructions change \
what a belief says, not how many you propose: propose exactly what you would have \
proposed without them."""

#: The envelope, and the ban ADR-0156 §7 narrows rather than lifts: the model still
#: supplies no value for a field the producer computes, and a date it is entitled
#: to state goes in the sentence, where nothing mechanises it (§1).
#:
#: **``guarded`` is the one key whose absence is a stated answer** rather than a
#: gap: ADR-0217 §6's default is what a belief carries when nothing narrows it, so
#: an envelope written before this key existed — or by a model that ignores it —
#: is complete and not degraded. The line says only ``true`` narrows, because the
#: producer refuses everything else (:func:`_placement`) and a schema that let a
#: model believe ``"yes"`` or ``1`` would work is a schema that loses narrowings
#: silently.
_PROMPT_ENVELOPE: Final = """\
Reply with a single JSON object and nothing else — no prose, no code fence:

{"beliefs": [
   {"kind": "semantic" | "preference" | "procedural",
    "step": "observed" | "inferred",
    "content": "<the belief, in one sentence>",
    "evidence": ["<label>", ...],
    "topics": ["<filing word>", ...],
    "guarded": true | false,
    "rationale": "<why the cited episodes justify it>",
    "steps": ["<ordered step>", ...]}
 ]}

`beliefs` must be a list, and may be empty. `steps` applies to a "procedural" \
belief only and is otherwise ignored. `topics` must be a list of strings and may \
be empty; a `topics` list this system cannot use is dropped and the belief is \
kept, so a belief is never worth omitting over its filing words. `guarded` is \
optional and defaults to false: write the literal `true` to flag a belief, and \
anything else — `false`, "true", 1, or leaving the key out — leaves the belief \
unflagged. Do not include ids, confidence values, or any timestamp field of your \
own; those are assigned downstream. A date you are entitled to state belongs in \
the belief's `content` sentence and nowhere else."""


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _confidence(step: MemorySource, supports: int) -> float:
    """This producer's confidence for ``supports`` distinct episodes taken by ``step``.

    Pure in exactly the two inputs ADR-0077 §5 allows, so the same evidence yields
    the same number however many times it is derived. That is what closes the
    repetition route to inflation: a second pass over one batch re-proposes the
    belief, the gate folds it as a ``REINFORCE``, and the fold's maximum finds
    nothing higher.
    """
    base, ceiling = _LADDER[step]
    return min(base + _SUPPORT_INCREMENT * (supports - 1), ceiling)


class ModelBackedObserver:
    """An ``Observer`` that distils beliefs out of episodes with an LLM.

    Structurally implements :class:`~ai_assistant.core.protocols.Observer`. The
    model proposes each belief's kind, epistemic step, content, citations and — on
    ADR-0217 §4 — whether it should be narrowed to the owner; this class mints the
    ids, maps the citations back onto the episodes it actually read, computes the
    confidence, stamps the timestamp, decides what a narrowing flag actually
    writes, applies its own bound, and counts everything it threw away (ADR-0077).
    """

    def __init__(  # noqa: PLR0913 — one model, one clock, one id factory, one calendar and the two bounds; each is one knob a deployment sets on its own
        self,
        model: ModelProvider,
        *,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
        timezone: str | None = None,
        max_batch_size: int = DEFAULT_OBSERVATION_BATCH_SIZE,
        max_proposals: int = DEFAULT_OBSERVATION_MAX_PROPOSALS,
    ) -> None:
        """Create an observer over an injected model, clock and id factory.

        Args:
            model: The model seam that reads the episodes. The only dependency on
                the LLM; no provider SDK is imported (golden rule 4). **It must
                not fall back** — ADR-0077 §3 rules that an observation's failure
                is never re-sent to a second provider, because fallback buys
                reliability by widening the set of providers that see a prompt and
                an observation is deferrable, so the reliability is worth nothing
                and the widening is the one cost that matters. That is a property
                of the provider the composition root builds and hands in; this
                class cannot enforce it and does not pretend to.
            now: Clock for each proposal's ``provenance.last_updated``; injectable
                for deterministic tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §7).
            id_factory: Mints the id of every proposed record; injectable so tests
                assert exact ids (ADR-0047 §2). Defaults to random UUIDs.
            timezone: IANA name of the local calendar each episode's
                ``occurred_at`` is shown in, and the one a relative expression is
                resolved against (ADR-0156 §2, §3). ``Settings.timezone``, the same
                value ADR-0008 §5 gives the temporal context — this producer is a
                third consumer of it, not a fourth source of truth (ADR-0008 §6).
                **``None`` withholds the instants entirely**: a producer without a
                calendar cannot say what day an instant falls on, and ADR-0156 §3's
                second clause refuses both fallbacks it would otherwise reach for —
                UTC, and the host's locale — because either states a calendar date
                the deployment never authorised. Unknown is a state, not a licence
                to invent (ADR-0109 §3).
            max_batch_size: The largest batch this observer accepts. A longer one
                is refused, never truncated (ADR-0077 §1).
            max_proposals: The most proposals one call may return. Usable beliefs
                beyond it are discarded and counted, never queued (ADR-0077 §2).

        Raises:
            TypeError: If either bound is not an ``int`` (``bool`` included).
            ValueError: If either bound is below 1. A zero batch bound observes
                nothing while reporting health; a zero proposal bound could never
                propose anything.
            ConfigurationError: If ``timezone`` is not a known IANA zone. Refused
                at construction, like the bounds and for ADR-0022 §4a's reason:
                a zone the caller got wrong should fail at startup rather than on
                the first observation that silently states nothing.
        """
        _check_bound("max_batch_size", max_batch_size)
        _check_bound("max_proposals", max_proposals)
        self._model = model
        self._clock = checked_clock(now, owner="ModelBackedObserver")
        self._id_factory = id_factory
        self._zone = _zone_of(timezone)
        # Fixed at construction, because the calendar is: a prompt that promised
        # recorded times a batch renderer then withheld — or the reverse — would ask
        # the model to resolve against instants it cannot see.
        self._system_prompt = _system_prompt(self._zone)
        self._max_batch_size = max_batch_size
        self._max_proposals = max_proposals

    @property
    def max_batch_size(self) -> int:
        """The largest batch this observer accepts."""
        return self._max_batch_size

    @property
    def max_proposals(self) -> int:
        """The most proposals one ``observe`` call may return."""
        return self._max_proposals

    async def observe(self, episodes: Sequence[EpisodicMemory]) -> ObservationOutcome:
        """Propose what ``episodes`` justifies believing about the user.

        The batch is observed **once**, on this coroutine's first executed line
        and before the first ``await`` (ADR-0065). A shallow tuple is a complete
        snapshot: the container is the caller's and mutable, while every
        :class:`~ai_assistant.core.types.EpisodicMemory` in it is frozen
        (ADR-0068). Without it, a caller mutating its own list across the model
        round trip — the widest suspension window in the system — would get
        beliefs whose citations name episodes the model was never shown.

        An **empty batch reaches no model**: there is nothing to observe, and
        sending an empty prompt would spend an egress of the most sensitive data
        the system holds to be told nothing.

        Args:
            episodes: The batch to observe, as a set of at most
                :attr:`max_batch_size` records.

        Returns:
            The proposals distilled from the batch, and the two counts of what was
            thrown away getting there.

        Raises:
            ValueError: If ``episodes`` exceeds :attr:`max_batch_size` or repeats
                an episode id — refused rather than truncated or de-duplicated
                (ADR-0077 §1) — or if the injected clock's reading does not
                conform (a :class:`~ai_assistant.core.clock.ClockReadingError`,
                which is a ``ValueError`` and is left unwrapped: `learning` has no
                error class of its own to translate it into, and the distinct
                subclass keeps it separable from a malformed batch).
            ModelError: Propagated unwrapped from the provider, its classification
                intact (ADR-0013 §5). The caller asked for observation and it did
                not happen; returning "no beliefs" would be indistinguishable from
                "nothing to learn" (ADR-0022 §3).
        """
        batch = tuple(episodes)
        _check_batch(batch, self._max_batch_size)
        if not batch:
            return ObservationOutcome()

        # Read **once**, and before the model call: once, so every proposal in one
        # outcome carries the same transaction time rather than a spread of them
        # from a clock that moved while the loop ran; and before, so a
        # misconfigured clock costs no egress of the batch to find out.
        now = self._clock()
        labels = {f"E{index + 1}": record.id for index, record in enumerate(batch)}
        # Taken from the batch *this module selected*, beside the labels and for
        # the same reason: a `DERIVED` belief's confirming instant is the latest
        # `occurred_at` among the episodes it cites (ADR-0103 §9), and it is ours
        # to compute rather than the model's to emit (ADR-0109 §4, ADR-0106 §3).
        # Snapshotted here, off the same frozen tuple, so it cannot come apart
        # from `labels` across the model round trip.
        occurred = {record.id: record.occurred_at for record in batch}
        conversation = [
            Message(role=Role.SYSTEM, content=self._system_prompt),
            Message(role=Role.USER, content=_render_batch(batch, self._zone)),
        ]
        reply = await self._model.complete(conversation)
        return self._distil(reply.content, labels, occurred, now)

    def _distil(
        self,
        content: str,
        labels: dict[str, str],
        occurred: Mapping[str, datetime],
        now: datetime,
    ) -> ObservationOutcome:
        """Turn one model reply into proposals and the two discard counts.

        **Validate every entry first, then apply the bound to the survivors**, in
        that order, because both halves of it are observable and ADR-0077 §4
        ratifies it rather than leaving it to be discovered. Capping first would
        put an unusable entry into ``discarded_over_limit`` when it happened to
        sit past the cut and into ``discarded_unusable`` when it did not — two
        conforming producers reporting different outcomes for one response — and,
        worse, would let a malformed entry occupy a slot a good one could have
        filled, so six entries of which one was junk would yield four proposals
        instead of five.
        """
        entries = _entries(content)
        if entries is None:
            # An envelope that does not decode, or that carries no `beliefs` list,
            # counts as exactly one entry and that entry is unusable (ADR-0077
            # §4). Without the synthetic unit, "I cannot help" yields zero
            # proposals and zero discards, which is indistinguishable from a model
            # that read the batch and honestly proposed nothing — the one
            # confusion this counting exists to remove.
            return ObservationOutcome(discarded_unusable=1)

        usable: list[MemoryUpdateProposal] = []
        unusable = 0
        for entry in entries:
            proposal = self._to_proposal(entry, labels, occurred, now)
            if proposal is None:
                unusable += 1
            else:
                usable.append(proposal)
        return ObservationOutcome(
            proposals=tuple(usable[: self._max_proposals]),
            discarded_unusable=unusable,
            discarded_over_limit=max(len(usable) - self._max_proposals, 0),
        )

    def _to_proposal(
        self,
        entry: object,
        labels: dict[str, str],
        occurred: Mapping[str, datetime],
        now: datetime,
    ) -> MemoryUpdateProposal | None:
        """Build one proposal, or ``None`` where the entry cannot be used.

        Every refusal here is counted as ``discarded_unusable`` by the caller and
        none is repaired: an unmappable citation is dropped rather than replaced,
        and a belief left citing nothing is discarded rather than propped up with
        the batch wholesale. Evidence attached to satisfy a rule is not evidence,
        and it would make the "why do you believe that?" answer a list of
        everything the observer happened to be reading (ADR-0077 §5).

        **The placement is written here, at construction, and ``now`` is the
        instant it carries** (ADR-0217 §4). ADR-0217 §3 admits a proposal "only
        where the record's placement is reach ``ANYONE`` with setter ``None``",
        and that holds by construction rather than by a check: this method mints
        the record, so the slot is empty until :func:`_record` fills it and no
        stored placement is in reach — which is the same clause's "never runs on a
        record already in the store", read from the producing side. The instant is
        the pass's, read once before the model call, so every proposal in one
        outcome carries the instant of the pass that made it.
        """
        if not isinstance(entry, dict):
            return None
        kind = entry.get("kind")
        step = _step_of(entry.get("step"))
        text = entry.get("content")
        if kind not in _PROPOSABLE_KINDS or step is None:
            return None
        if not isinstance(text, str) or not text.strip():
            return None

        cited = _resolve(entry.get("evidence"), labels)
        if len(cited) < _EVIDENCE_FLOOR[step]:
            return None

        rationale = entry.get("rationale")
        provenance = Provenance(
            source=step,
            confidence=_confidence(step, len(cited)),
            evidence=cited,
            last_updated=now,
            # The band's confirming event (ADR-0103 §9, ADR-0109 §4): the latest
            # `occurred_at` among the episodes cited, never the moment of
            # derivation — `now` is transaction time and is already above. Taken
            # over the ids *this module* resolved the citations to, so a value the
            # model emitted for it could not reach the field even if it tried
            # (ADR-0106 §3). Stored as it stands, so an episode dated in our
            # future is neither dropped nor clamped (ADR-0109 §4's fourth clause).
            last_confirmed_at=_latest_occurred(cited, occurred),
        )
        try:
            record = _record(
                str(kind),
                text.strip(),
                entry.get("steps"),
                provenance,
                self._id_factory(),
                _topics(entry.get("topics")),
                _placement(entry.get("guarded"), now),
            )
        except ValidationError:
            # A `core` invariant the entry's own text broke. Counted like any
            # other refusal rather than raised: one bad belief in a batch is a
            # degradation, not a failed observation (ADR-0077 §4).
            return None
        return MemoryUpdateProposal(
            proposed=record,
            rationale=rationale.strip()
            if isinstance(rationale, str) and rationale.strip()
            else f"observed across {len(cited)} episode(s)",
        )


def _check_bound(name: str, value: int) -> None:
    """Refuse a non-positive or non-integral bound at construction.

    Validated here rather than at first use, for ADR-0022 §4a's reason: a bound
    the caller got wrong should fail where it was set, not on the first
    observation that silently does half the work.

    Raises:
        TypeError: If ``value`` is not an ``int`` (``bool`` included).
        ValueError: If ``value`` is below 1.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{name} must be an integer, got {value!r}"
        raise TypeError(msg)
    if value < 1:
        msg = f"{name} must be at least 1, got {value}"
        raise ValueError(msg)


def _check_batch(batch: Sequence[EpisodicMemory], maximum: int) -> None:
    """Refuse an oversized or repeating batch (ADR-0077 §1).

    Raises:
        ValueError: If ``batch`` is longer than ``maximum``, or names one episode
            twice. Neither is repaired: a silent truncation disables half the work
            while the caller keeps reporting health, and a silent de-duplication
            hides a selection bug — the route by which one episode becomes the two
            distinct supports an ``INFERRED`` belief owes.
    """
    if len(batch) > maximum:
        msg = (
            f"batch of {len(batch)} episodes exceeds the configured maximum of "
            f"{maximum}; it is refused, never truncated"
        )
        raise ValueError(msg)
    ids = [record.id for record in batch]
    if len(set(ids)) != len(ids):
        msg = (
            "a batch is a set: an episode appears in it at most once, and a repeat "
            "would let one observation supply two distinct supports"
        )
        raise ValueError(msg)


def _zone_of(timezone: str | None) -> ZoneInfo | None:
    """The local calendar named, or ``None`` where none was supplied (ADR-0156 §3).

    Raises:
        ConfigurationError: If ``timezone`` names no known IANA zone. ``Settings``
            validates its own value at load, so this bites only a caller that
            constructed the producer directly — which is exactly where a silent
            fallback to UTC would be least visible.
    """
    if timezone is None:
        return None
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        msg = f"unknown timezone {timezone!r}"
        raise ConfigurationError(msg) from exc


def _system_prompt(zone: ZoneInfo | None) -> str:
    """The system turn, whose middle section depends on whether a calendar is held.

    Two variants rather than one, because a single text would have to be true both
    with instants and without them: ADR-0156 §2's first clause has the prompt state
    each ``occurred_at``, and §3's second clause has a producer lacking the zone
    render none and resolve nothing. Telling a model to work a date out from
    recorded times it was never shown invites it to invent one, which is the
    fallback §3 refuses in terms.
    """
    time_section = (
        _PROMPT_TIME_WITH_ZONE.format(zone=zone.key) if zone is not None else _PROMPT_TIME_NO_ZONE
    )
    return "\n\n".join((_PROMPT_HEAD, time_section, _PROMPT_ENVELOPE))


def _localised(instant: datetime, zone: ZoneInfo) -> str:
    """``instant`` in ``zone``, or :data:`_INSTANT_UNAVAILABLE` where it has none.

    ``EpisodicMemory.occurred_at`` is bounded only by ``datetime``'s own range and
    ADR-0092 §3 forbids refusing or rewriting a source instant, so an episode within
    one UTC offset of ``datetime.max`` or ``datetime.min`` is well-formed and
    storable while having **no** representation in a zone that shifts it past the
    boundary: ``9999-12-31T23:59Z`` raises ``OverflowError`` on conversion to
    ``Pacific/Kiritimati``. Reachable only from a clock reading at the end of the
    representable calendar, but the alternatives to handling it are an unrelated
    exception escaping ``observe`` and a batch of otherwise good episodes failing
    with it.

    **Withheld for that episode, never refused for the batch and never rewritten.**
    Refusing would let one unrepresentable instant disable observation of the
    nineteen episodes beside it, and clamping would state a calendar date the
    evidence does not support — the invention ADR-0156 §3 refuses over an unknown
    calendar, arriving by a different route. An episode shown no time is one
    ADR-0156 §2's third clause already governs: the evidence establishes none, so
    the belief states none.
    """
    try:
        return instant.astimezone(zone).strftime(_INSTANT_FORMAT)
    except OverflowError:
        return _INSTANT_UNAVAILABLE


def _quoted_span(value: str) -> str:
    """Render one held string so it cannot write this assembler's own syntax.

    ADR-0098 §2 rules that a span's attribution is "not forgeable from inside the
    span", and that "an assembler that embeds a span in a syntax the serialised span
    can itself produce does not conform, whatever labels it emits". This batch's
    syntax is line-oriented — a header line, a two-space ``[E<n>]`` label per
    episode, and a deeper-indented ``Assistant:`` continuation line — and the spans
    reaching it are :data:`~ai_assistant.core.types.EncodableText`, which validates
    UTF-8 encodability and permits every newline and bracket in between.

    **Here the forgery is worse than cosmetic, which is why ADR-0098 §2 names this
    assembler as well as the planner's.** :func:`_resolve` maps a cited label back to
    the id of an episode this module actually read, so a label naming nothing in the
    batch is dropped; what that mapping cannot see is one episode's text presenting
    itself as several. Left raw, an episode whose ``content`` carried a newline and a
    well-formed ``[E2]`` wrote a second entry under a label that *maps* — to a real
    id, of an episode that said no such thing — and ADR-0077 §5's ``INFERRED`` floor
    counts distinct cited ids. The two distinct supports that floor exists to require
    could then both come from one episode's own span, and the floor would be
    satisfied by an episode corroborating itself. **The ``INFERRED`` support count
    rests on this function**, which is what ADR-0098 §9's second bullet asks this
    lane to record.

    :func:`json.dumps` is the deterministic transform §2 admits — §2 removed the
    unguessable-terminator alternative in terms, so there is one admissible
    construction and this is it — and it is used at its default
    ``ensure_ascii=True``: the result is single-line printable ASCII, delimited by
    quotes the value can no longer close. Single-line is not a bonus but the *second*
    thing ADR-0221 §13 asks of a reader of this batch — "#672's escaping fix **and**
    newline normalisation" — because a newline inside a span becomes the
    two-character escape JSON writes for it rather than a line boundary; the two
    halves are discharged by one transform rather than by two mechanisms. The ASCII
    part is load-bearing for the same reason: ``ensure_ascii=False`` emits U+2028 and
    U+2029 literally, which JSON does not escape and which ``str.splitlines`` treats
    as line boundaries, so a span carrying one could still open a line.

    **This is ``planning._quoted_span``'s transform and deliberately not its
    function.** Golden rule 1 keeps two subsystems assembling their own prompts out of
    one another's modules; what they share is ADR-0098 §2's admitted construction,
    exactly as ADR-0221 §3 has three render sites hold three copies of one phrase
    table rather than import one.

    Args:
        value: The held string, verbatim as this system carries it.

    Returns:
        The quoted, escaped span to interpolate into a line of the batch.
    """
    return json.dumps(value)


def _render_batch(batch: Sequence[EpisodicMemory], zone: ZoneInfo | None) -> str:
    """Render the batch as the labelled user turn.

    **The payload is the batch and nothing else** (ADR-0077 §3, as partially
    superseded by ADR-0156): each episode's canonical ``content`` (ADR-0005 §1),
    the label the model cites it by, that episode's own ``occurred_at`` since
    ADR-0156 §2, and its ``outcome`` since ADR-0162 §8. Still not the user's
    existing beliefs, not the profile, not a context facet, not a plan: each of the
    two added fields is admitted precisely because it is a field of the very
    records whose ``content`` is already here rather than a second class of data,
    so ADR-0004 §7's minimisation is satisfied rather than strained and §3's four
    refusals stand verbatim. De-duplication remains the gate's job,
    deterministically and locally.

    Not the store ids either, and that is the same rule from the other side: the
    model has no use for an id it is not allowed to cite, and an id in the prompt
    is an id a model can echo back.

    **The instant is localised or it is withheld** (ADR-0156 §3). ``occurred_at``
    is a ``UtcInstant`` (ADR-0030 §4) while *"yesterday"* is said in the speaker's
    calendar, so for any deployment west of UTC an evening utterance falls on the
    following UTC day: rendering the instant in UTC would misdate a fixed fraction
    of all evidence by one day, always in the same direction. Without a zone the
    header says the times are withheld and the lines carry none — the state the
    system prompt's second variant is written against.

    **And the assistant's half is rendered where the episode carries one**
    (ADR-0162 §8, as ADR-0221 §3 replaces its first clause): the phrase for the
    episode's ``disposition`` where it records one, and its ``outcome`` where it
    does not. It has been stored and outside the prompt since the field existed:
    the harness pairs a user turn with the assistant turn that follows it and puts
    the latter here, so under the pre-#1184 LoCoMo mapping roughly half the corpus
    was never visible to distillation at all (#1185). No supersession is owed for
    admitting it, on ADR-0156 §2's own ground — it is a field of the very records
    whose ``content`` ADR-0077 §3 already sends, not a second class of data, so
    §3's four refusals stand verbatim; ADR-0162 §8's four remaining clauses bind
    unchanged, and :func:`_outcome_lines` is where §3's rule is applied.

    **Under the same label, on a continuation line, and never as a second entry.**
    An episode is cited whole (ADR-0162 §8): the model is shown two texts and the
    evidence floor counts labels, so splitting the halves into two labels would let
    one episode supply the two *distinct* supports an ``INFERRED`` record owes —
    the failure ADR-0077 §5's distinct-id counting exists to prevent. The line is
    prefixed ``Assistant:`` because the system prompt names that word when it
    partitions what the half supports, and an episode carrying neither a
    ``disposition`` nor an ``outcome`` grows no such line at all.

    **And no span may reach that outcome by writing this syntax itself**
    (ADR-0098 §2, §9). Every part of a line that is *not* a span goes on held data
    the batch was handed — the label from this loop's index, the header and the
    instant from the zone this producer was built with — and the two parts that are
    spans go through :func:`_quoted_span`. So the line count of this batch is the
    header plus one line per episode plus one per assistant half, whatever any
    episode's ``content`` says, and the label a model is shown maps to the episode
    this module read under it. That is the same argument the paragraph above makes
    about *this module's* rendering choice, closed on the other side: it would be no
    use declining to split an episode into two labels if an episode could split
    itself.
    """
    if zone is None:
        lines = ["Episodes (recorded times withheld: no local calendar is configured):"]
        for index, record in enumerate(batch):
            lines.append(f"  [E{index + 1}] {_quoted_span(record.content)}")
            lines.extend(_outcome_lines(record))
        return "\n".join(lines)
    lines = [f"Episodes (each carries the local time it was recorded, in {zone.key}):"]
    for index, record in enumerate(batch):
        lines.append(
            f"  [E{index + 1}] {_localised(record.occurred_at, zone)} — "
            f"{_quoted_span(record.content)}"
        )
        lines.extend(_outcome_lines(record))
    return "\n".join(lines)


def _outcome_lines(record: EpisodicMemory) -> list[str]:
    """The episode's assistant half as its own continuation line, or nothing.

    **The phrase where the episode records a ``disposition``, its ``outcome`` where
    it does not** (ADR-0221 §3), which partially supersedes ADR-0162 §8's first
    clause and replaces it with exactly this rule. The two populations render the
    same string for the same fact: a record captured before ADR-0221 holds the
    phrase in ``outcome`` and renders it; one captured after holds the composed
    reply there and a member of :class:`~ai_assistant.core.types.ExchangeDisposition`
    beside it, and renders :func:`_disposition_phrase` of that member — which is the
    phrase the older record carries, byte for byte. A benchmark row holds the other
    speaker's turn and no disposition, and renders that text exactly as it did.

    **The reply reaches no prompt, and that is the point rather than a side effect**
    (ADR-0221 §3). Reading it here would make the observer an accidental reader of
    model prose, which is a decision and not a rendering detail — so the arm above is
    read first and the field is not consulted at all where a ``disposition`` is
    present. What ADR-0221 §13 leaves to whoever *does* decide to read it has since
    narrowed: two of the three things it names — "#672's escaping fix **and** newline
    normalisation" — are discharged here, because :func:`_quoted_span` escapes and
    normalises every span this function interpolates, this one included. The render
    budget none of the three prompts has today is what remains, and it is the half a
    transform cannot supply: a quoted reply is one line but is as long as the reply.

    **Both spans go through :func:`_quoted_span`, and the phrase is not exempt.**
    ADR-0221 §3 makes the two populations render the same bytes for the same fact,
    and a phrase interpolated raw beside an ``outcome`` interpolated quoted would
    break that identity for every one of the sixteen members. The phrase is this
    system's own text and could not forge anything; it is quoted because the
    *identity* is the clause, which is the same reason ``planning._render_record``
    quotes it.

    Empty where the episode carries neither, which is what keeps a corpus with no
    assistant half — LoCoMo under #1177's framing, where every exchange carries
    ``outcome=None`` — a batch of one line per episode, as it was before ADR-0162 §8
    added this function. The indent is deeper than the label's so the two texts read
    as one entry rather than two.
    """
    if record.disposition is not None:
        return [f"       Assistant: {_quoted_span(_disposition_phrase(record.disposition))}"]
    if record.outcome is None:
        return []
    return [f"       Assistant: {_quoted_span(record.outcome)}"]


def _disposition_phrase(disposition: ExchangeDisposition) -> str:  # noqa: C901, PLR0911, PLR0912 — one return per member, so the totality `assert_never` rests on is visible; collapsing them would hide it
    """ADR-0221 §2's phrase for one disposition, written out at this site.

    **This table is not shared and must not become shared** (ADR-0221 §3). It is one
    of three copies of the same sixteen strings — the others are in
    ``planning/planner.py`` and ``orchestration/composing.py`` — and no
    implementation extracts them into a shared module, a ``core`` mapping, a method
    on the enum or a helper any two of the three import. Golden rule 1 is the
    reason: three subsystems rendering their own prompts do not reach into one
    another, and what they share is the ADR's table rather than a module.

    Total over :class:`~ai_assistant.core.types.ExchangeDisposition` and
    mechanically so — the wildcard does nothing but ``assert_never`` — so a member
    added to that enum without a phrase here fails the gate at this site rather than
    rendering an episode whose assistant half reads as empty.

    Args:
        disposition: The member the episode records.

    Returns:
        §2's phrase for it, byte for byte.
    """
    match disposition:
        case ExchangeDisposition.NO_ACTION_NEEDED:
            return "no action was needed"
        case ExchangeDisposition.STEP_EXECUTED:
            return "the selected tool ran"
        case ExchangeDisposition.STEP_DENIED:
            return "the action was refused by the permission policy"
        case ExchangeDisposition.STEP_AWAITING_CONFIRMATION:
            return "the action was parked for the user to confirm"
        case ExchangeDisposition.STEP_NO_CAPABLE_TOOL:
            return "no tool advertised the capability the step needed"
        case ExchangeDisposition.STEP_AMBIGUOUS_CAPABILITY:
            return "several tools advertised the capability, so none was chosen"
        case ExchangeDisposition.STEP_INVALID_PARAMETERS:
            return "the step's arguments did not fit the declared schema of any capable tool"
        case ExchangeDisposition.STEP_EGRESS_UNBINDABLE:
            return "the outbound call could not be described, so nothing was asked or sent"
        case ExchangeDisposition.ROUTED_PERFORMED:
            return "the assistant performed the operation the user asked for"
        case ExchangeDisposition.ROUTED_AWAITING_CONFIRMATION:
            return "the operation was parked for the user to confirm"
        case ExchangeDisposition.ROUTED_REFUSED:
            return "the user declined, so the operation was not performed"
        case ExchangeDisposition.ROUTED_AMBIGUOUS:
            return "more than one record matched, so nothing was performed"
        case ExchangeDisposition.ROUTED_AMBIGUOUS_TRUNCATED:
            return "more records matched than could be shown, so nothing was performed"
        case ExchangeDisposition.ROUTED_NOT_FOUND:
            return "nothing matched, so nothing was performed"
        case ExchangeDisposition.ROUTED_UNRECORDED:
            return "the decision could not be recorded, so nothing was performed"
        case ExchangeDisposition.ROUTED_FAILED:
            return "the operation was attempted and failed"
        case _:  # pragma: no cover - exhaustive
            assert_never(disposition)


def _step_of(raw: object) -> MemorySource | None:
    """Map the envelope's ``step`` onto an epistemic step, or ``None``."""
    match raw:
        case "observed":
            return MemorySource.OBSERVED
        case "inferred":
            return MemorySource.INFERRED
        case _:
            return None


def _resolve(raw: object, labels: dict[str, str]) -> tuple[str, ...]:
    """Map cited labels back onto the ids of the episodes actually read.

    A label that does not map is **dropped**, never repaired (ADR-0077 §5), and
    the result is de-duplicated in citation order: two labels resolving to one
    episode are one support, which is the same rule the duplicate-batch refusal
    enforces from the input side.
    """
    if not isinstance(raw, list):
        return ()
    resolved = [labels[label] for label in raw if isinstance(label, str) and label in labels]
    return tuple(dict.fromkeys(resolved))


#: ADR-0213 §3's canonical form, read as a **check** rather than as a
#: construction. The producer consults it before the record exists, because §4
#: rules that a topics entry it cannot use is *ignored* — and a bad label reaching
#: :class:`MemoryBase` construction would raise a ``ValidationError`` that
#: :meth:`ModelBackedObserver._to_proposal` counts as an unusable entry, trading a
#: belief for a filing word. Checking here is what keeps the two apart.
_TOPIC_LABEL: Final[TypeAdapter[str]] = TypeAdapter(TopicLabel)


def _topics(raw: object) -> tuple[str, ...]:
    """The entry's topics in canonical order, or ``()`` where it cannot be used.

    ADR-0213 §4's rule, whole: a response naming more than
    :data:`MAX_TOPICS_PER_PROPOSAL` labels, naming a value §3's canonical form
    refuses, or naming none yields **no topics on that record**. The entry is
    **ignored** — never repaired, never truncated to the bound, never re-prompted
    for and never inferred locally — and the proposal that carried it is unaffected.

    **Ignored rather than counted**, which is where this takes half of ADR-0077 §4
    and deliberately leaves the other. The *not repaired, not re-prompted* half
    transfers whole; the *counted* half must not, because
    :class:`~ai_assistant.core.types.ObservationOutcome`'s two counts are exhaustive
    and disjoint over what the model emitted, so counting a usable entry whose
    topics were bad would report one proposal and one discard for one entry.

    **Sorted, and that is not the normalisation §3 forbids.** Nothing here
    case-folds, strips, stems, aliases or de-duplicates a *label*: a value that is
    not already canonical is refused and the whole entry is dropped, including one
    that merely repeats a label. What is fixed is the **tuple's** order, which §1
    requires of the stored value precisely so that order carries no meaning — and
    §8 keeps admission order and storage order as two different things for the same
    reason. A model emits a list; putting that list in the order the field is stored
    in changes no label.

    Args:
        raw: Whatever the entry's ``topics`` key held — absent, null, not a list, a
            list of the wrong things, or a usable list of labels.

    Returns:
        The labels in code-point order, or the empty tuple.
    """
    if not isinstance(raw, list) or not raw or len(raw) > MAX_TOPICS_PER_PROPOSAL:
        return ()
    labels = [label for label in raw if isinstance(label, str)]
    if len(labels) != len(raw) or len(set(labels)) != len(labels):
        return ()
    try:
        for label in labels:
            _TOPIC_LABEL.validate_python(label)
    except ValidationError:
        return ()
    return tuple(sorted(labels))


def _placement(raw: object, now: datetime) -> Placement:
    """The placement the entry's ``guarded`` key proposes, or the default.

    ADR-0217 §4's proposal, and the whole of what a model may say about who
    receives a record. A flag writes reach ``OWNER`` with setter ``PROPOSED`` and
    the instant of the pass; anything else leaves ``Placement()``, which is
    ADR-0217 §6's default — ADR-0199 §3's placement of the record's class,
    subtracting nothing. There is no third answer, because the mechanism has no
    widening direction to express: §3 gives the proposal reach ``OWNER`` or
    nothing at all.

    **Only the literal ``True``**, and ``is`` rather than a truth test, because
    every other reading of this key is a route by which something that is not a
    model's judgement becomes a narrowing. JSON's ``1`` and Python's ``True`` are
    equal and ``isinstance(True, int)`` holds, so ``raw == True`` would let a
    count, an index or a bare ``1`` place a record; a truthiness test would let a
    non-empty string, list or object do it. The model is told in the envelope that
    only ``true`` flags a belief, and this is that sentence enforced.

    **An unusable value leaves the default rather than narrowing, and that
    direction is decided rather than assumed.** Fail-closed is the rule where a
    system must choose *what to do with a narrowing it holds*, and every such
    clause of ADR-0217 keeps it — §3's ratchet, the fold's meet, the refusal to
    widen a ``DERIVED`` placement. This is the prior question: whether a proposal
    was made at all. A value the model did not write is not a proposal, and
    treating one as such would attribute to the model a judgement it never made,
    on the exact input — a malformed reply — where its judgement is least
    evidenced. ADR-0217 §4 rules the unproposed case explicitly: a record carrying
    the default "is not a degraded state", and §6 is what makes that true.

    **Ignored rather than counted**, on :func:`_topics`' reasoning exactly:
    :class:`~ai_assistant.core.types.ObservationOutcome`'s two counts are
    exhaustive and disjoint over what the model emitted, so counting a usable
    entry whose flag was malformed would report one proposal *and* one discard for
    one entry.

    Args:
        raw: Whatever the entry's ``guarded`` key held — absent, null, a boolean,
            or any other JSON value.
        now: The instant of the pass, which a proposal records as ``set_at``.
            ADR-0217 §1 requires one on a ``PROPOSED`` placement and refuses the
            value without it, so this argument is not optional in either sense.

    Returns:
        The narrowed placement, or ADR-0217 §6's default.
    """
    if raw is not True:
        return Placement()
    return Placement(
        reach=PlacementReach.OWNER,
        set_by=PlacementSetter.PROPOSED,
        set_at=now,
    )


def _latest_occurred(cited: Sequence[str], occurred: Mapping[str, datetime]) -> datetime | None:
    """A ``DERIVED`` belief's confirming instant (ADR-0103 §9, ADR-0109 §4).

    The **latest** ``occurred_at`` among the episodes ``cited`` names — "the belief
    was seen to hold again *when that observation happened*" — and never the moment
    of derivation. ``cited`` is already the output of :func:`_resolve`, so every id
    in it came from ``labels`` and is therefore a key of ``occurred``: the lookup is
    total by construction, and a citation the model invented was dropped before it
    reached here.

    ``None`` where nothing is cited, which no proposal reaching this point can be
    (:data:`_EVIDENCE_FLOOR` refuses it) but which is the honest answer over an
    empty set rather than a substitute instant (ADR-0109 §4's second clause).
    """
    return max((occurred[episode_id] for episode_id in cited), default=None)


def _record(  # noqa: PLR0913 — the record's own axes: kind, text, steps, warrant, topics, placement, id
    kind: str,
    content: str,
    raw_steps: object,
    provenance: Provenance,
    record_id: str,
    topics: tuple[str, ...],
    placement: Placement,
) -> MemoryRecord:
    """Build the typed record the entry names.

    ``episodic`` is unreachable: :data:`_PROPOSABLE_KINDS` refuses it before this
    is called, which is why there are three arms and no fourth.

    ``topics`` is already :func:`_topics`' output — checked against ADR-0213 §3 and
    in §1's order — so the field's validators cannot refuse what this passes them.
    That is the point of checking before constructing rather than after: §4 forbids
    a bad filing word discarding the belief that carried it.

    ``placement`` is :func:`_placement`'s output and is passed on **every** arm,
    which is ADR-0217 §1's field being on ``MemoryBase``: the flag says who may
    receive the record and says nothing about what kind of record it is, so a kind
    this producer proposes and forgot to pass it to would be a narrowing the model
    made and this module dropped — the one failure here that no counter reports
    and no later read could detect.
    """
    match kind:
        case "preference":
            return PreferenceMemory(
                id=record_id,
                content=content,
                provenance=provenance,
                preference=content,
                topics=topics,
                placement=placement,
            )
        case "procedural":
            steps = (
                tuple(step.strip() for step in raw_steps if isinstance(step, str) and step.strip())
                if isinstance(raw_steps, list)
                else ()
            )
            return ProceduralMemory(
                id=record_id,
                content=content,
                provenance=provenance,
                situation=content,
                steps=steps,
                topics=topics,
                placement=placement,
            )
        case _:
            return SemanticMemory(
                id=record_id,
                content=content,
                provenance=provenance,
                fact=content,
                topics=topics,
                placement=placement,
            )


def _entries(content: str) -> list[object] | None:
    """The envelope's ``beliefs`` list, or ``None`` where there is no usable one.

    ``None`` is the synthetic single unusable entry of ADR-0077 §4 — a reply that
    decodes to no object at all, or to one carrying no ``beliefs`` list. An
    envelope whose ``beliefs`` is present and *empty* is not that case: it is a
    model that read the batch and honestly proposed nothing, which is a normal
    outcome and must not be reported as a discard.
    """
    envelope = _extract_object(content)
    if envelope is None:
        return None
    beliefs = envelope.get("beliefs")
    return beliefs if isinstance(beliefs, list) else None


def _extract_object(content: str) -> dict[str, object] | None:
    """Decode the JSON envelope embedded in ``content``, or ``None``.

    ADR-0071's scan, duplicated from ``planning.planner`` rather than promoted:
    ADR-0077 §9.5 rules that the extraction helper stays in the producing
    subsystem, because two implementations of one scan is cheaper than promoting a
    non-contract helper into `core` on speculation — and the *third* model-backed
    producer is the trigger to promote it, the discipline ADR-0028 §7 and ADR-0045
    §1 each applied. What must not happen is a producer re-deriving ADR-0047 §4
    step 1's superseded first-``{``-to-last-``}`` slice, which spans a prose brace
    and the envelope's closer at once (#293).

    Each ``{`` is tried left to right with :meth:`json.JSONDecoder.raw_decode`,
    which stops at the end of the object and ignores trailing text, so a model
    that wraps the object in prose or a code fence is tolerated. The **envelope**
    is preferred over the leftmost object: the first candidate carrying a
    ``beliefs`` list wins, so a decoy object in the prose ahead of it is stepped
    over rather than distilled from. Where none is well-formed the first decoded
    object stands in, so a single malformed envelope reaches the caller's precise
    verdict rather than a generic miss. A decoded object is advanced *past*, never
    re-entered, so a nested object is part of its parent rather than a separate
    candidate.

    At most :data:`_MAX_EXTRACTION_MISSES` decode **misses** are tolerated, which
    keeps the scan linear; a decoded object never counts as a miss, so any number
    of valid JSON fragments may precede the envelope. A candidate raising for a
    bounded reason that is not a syntax miss — CPython's digit-limit
    ``ValueError``, a ``RecursionError`` on a pathologically nested payload — is a
    miss like any other, so nothing escapes this scan.
    """
    decoder = json.JSONDecoder()
    first: dict[str, object] | None = None
    misses = 0
    index = 0
    length = len(content)
    while index < length:
        if content[index] != "{":
            index += 1
            continue
        try:
            candidate, end = decoder.raw_decode(content, index)
        except ValueError, RecursionError:
            misses += 1
            if misses > _MAX_EXTRACTION_MISSES:
                break
            index += 1
            continue
        if isinstance(candidate, dict):
            if isinstance(candidate.get("beliefs"), list):
                return candidate
            if first is None:
                first = candidate
        index = end
    return first


__all__ = [
    "DEFAULT_OBSERVATION_BATCH_SIZE",
    "DEFAULT_OBSERVATION_MAX_PROPOSALS",
    "ModelBackedObserver",
]
