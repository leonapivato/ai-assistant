"""Answer one benchmark question from retrieved context and nothing else.

**"Reads only retrieved context" is the whole experiment**, so it is enforced by
construction rather than by prompt wording: the only conversation material this module
can reach is what the two reads below returned. The corpus is not in scope here, the
case is not passed in, and the question text is the single other input.

**The retrieval path is the product's, not a convenience call.** ``LearningLoop``
assembles an answering turn's ``memories`` from *two* reads since ADR-0158, and both
are mirrored here by hand — the harness must not run the engine (see
:mod:`benchmarks.memory.wiring` for why), so "mirrored by hand" is the only shape
available and the equivalence is held by a test rather than by sharing the code.

1. *The belief composition.* ``assemble_by_band`` is what ``LearningLoop._retrieve``
   uses, with the same ``BELIEF_KINDS`` filter and the same budget imported from the
   composition root — one band-scoped ``search`` per band in precedence order,
   deduplicated across the calls (ADR-0072 §5, ADR-0113 §5). A single ``store.search``
   would be a different retrieval system, and the numbers would not be about this one.
2. *The episodic supplement* (ADR-0158, :func:`_supplement`). A second, separate
   ``search`` for ``EPISODIC`` records in the ``DERIVED`` band under a budget of its
   own, appended after the beliefs. It is what makes the pilot measure the product as
   shipped: 42% of LoCoMo's answerable questions failed the previous run because the
   fact never became a belief while the gold turn sat in the same store and the same
   index, unreachable only because the one read asked for ``BELIEF_KINDS``.

**Both groups render into one block, which is what the product does too.** The
planner splits the records it is handed into the conversation tail and the retrieved
group by the *leading run* of ``EPISODIC`` records and renders the retrieved group as
one undifferentiated list — so a supplemented episode is shown beside the beliefs,
after them, under the same heading (``planning.planner._split_conversation_tail``, and
ADR-0158 §4 quoting it: the episode "arrives after the tail and stays in the retrieved
group, which is the group it belongs to"). Giving the supplement a labelled section of
its own here would be a prompt the product never builds, so :func:`render_context`
gives it none: the episodes are simply the last lines of the one block, under the
retrieved group's own heading, and their kind is legible in each line's own tag.

**A record is rendered by the product's own renderer, and that is the whole of**
:func:`render_context`. It used to dump each record's ``model_dump_json`` — id,
provenance with its entire evidence list, validity window, scores — on the stated
ground that the model should see "what the store holds". That ground was wrong about
the thing the harness exists to mirror: the product shows the answering model a bullet
per memory and never the record's machinery. The cost was measured on the pilot-3
partial and it is not small — a median answer context of 15,922 characters for 15
beliefs and 5 one-line episodes, roughly 800 characters per record against ~150
characters of content — but the size is the lesser half of it (#1189). The larger half
is that a prompt carrying UUIDs, evidence lists and validity bounds is a *different*
prompt from the product's, so a score computed under it is a score for a system nobody
ships.

**The bullet is now called rather than copied** (#1181). It was a hand copy of
``planning.planner._render_record``, character for character, held honest by an
equivalence test. That was defensible while the product's line was one f-string; it
stopped being defensible when the line grew a band, a confidence, an instant, an
outcome and a quoting rule (#1194, #672), because a five-branch copy is drift waiting
for somebody to notice. So this module imports the product's renderer and its heading
and calls them. Nothing in ``planning`` was made public for that — the names are read
privately, knowingly, which is what the equivalence test was already doing.

**What an episode shows is the product's answer, not this harness's.** Since #1194 the
product's bullet carries an episode's ``occurred_at`` and its ``outcome``, so this
prompt carries them too — and it carries them because the shipped renderer does,
which is the only ground on which the harness may show a field at all. The previous
run withheld both, and #1029's P2 was measured against a prompt with no instant in it
anywhere; that measurement is of the older renderer and is not comparable to this one
field by field.

**Which of ADR-0158 §4's rules are live in the harness, and which are vacuous.** The
loop composes ``recent + retrieved + supplement``; this harness has no continuity tail
at all — no conversation is in progress, and ``preceding`` is the belief group and
nothing else. Rule by rule:

* *Ordering* — **live**. Episodes are appended whole after the beliefs and never
  interleaved, because position is how this corpus expresses precedence.
* *Deduplication against the tail* — **vacuous, and written anyway**. There is no
  tail, and ``BELIEF_KINDS`` and :data:`SUPPLEMENT_KINDS` are disjoint, so the
  comparison cannot remove a record here. It is the loop's own line, kept so that the two
  modules read alike; dropping it would read as the harness having decided something.
* *The separator rule* — **live, and the one worth stating**. "Append only where the
  records before it contain a non-``EPISODIC`` record" reduces, with beliefs the only
  thing before it, to "drop the supplement where the belief read came back empty". Its
  stated *reason* — the planner rendering an unbroken episodic run under the tail's
  heading, fabricating continuity — has no analogue in :func:`render_context`, which
  renders one group and never the conversation tail's heading. The rule is kept
  regardless, because the *behaviour* is the
  product's in the product's own matching state: a benchmark question is a fresh
  conversation's first turn, where ``history`` is empty and the loop drops the
  supplement on exactly this condition. A harness that appended there would score a
  system that answers from episodes in a case the shipped one does not.
* *The failure rule* — deliberately **not** mirrored, and that deviation is argued
  in :func:`_supplement`.

**Two things #1029 asks the harness to record, and how each is obtained.**

* *P4 — how many retrieval calls each answer used.* Each question is answered inside
  a :func:`~ai_assistant.core.correlation.correlated_operation` scope, so every
  ``RETRIEVAL`` trace the store emits underneath carries that scope's id
  (ADR-0119 §4). Counting them is then a query over the trace stream rather than a
  number this module asserts, which matters because the count is meant to be
  evidence about the *pipeline* and not about the driver's own bookkeeping.
* *P8 — retrieval-miss versus reader-error.* Each record actually placed in the
  prompt is recorded by id, and so is what the store returned; the same traces carry
  ``returned`` ids, ``limit``, ``fetch_k``, ``candidates`` and ``capped``. **Ids alone
  do not make the split**, which is what #1074 found: a question's evidence is a
  *corpus* pointer and a retrieved id is a *generated* one, and nothing retained
  joined the two id spaces. So each retrieved record's own citations travel with it
  (:attr:`AnswerAttempt.retrieved_evidence`), and ingestion records which episode each
  cited corpus turn became; the intersection of those two is "was the evidence in
  context?", asked of every wrong answer, from the run's own records.

**One thing #1029 assumes that the tree does not provide, recorded here because a
reader will look for it.** ADR-0119's retrieval trace names four per-predicate
exclusion counts — ``excluded_kind``, ``excluded_retention``, ``excluded_window``,
``excluded_band`` — and ``SqliteMemoryStore`` reports all four as a structural zero.
Since ADR-0128 §1 every predicate binds inside the KNN, so no candidate is dropped
after ranking and there is nothing post-hoc to count. The split above does not depend
on them; a prediction phrased in terms of them would.

**Opening a correlation scope here is the harness acting as the operation boundary.**
``core/correlation.py`` says a scope legitimately opens at an ``AssistantEngine``
call, because inside the product that is what an operation is. This harness is not
inside the product: it is an external driver, and answering one benchmark question is
exactly one operation. Nothing in ``ai_assistant`` opens a scope here, so no scope is
being nested or displaced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.correlation import correlated_operation
from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import BeliefBand, MemoryKind, Message, Role
from ai_assistant.orchestration.conversations import BELIEF_KINDS
from ai_assistant.orchestration.retrieval import assemble_by_band
from ai_assistant.planning.planner import _RETRIEVED_HEADING, _render_record

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryRecord
    from benchmarks.memory.cases import BenchQuestion
    from benchmarks.memory.wiring import Harness

__all__ = [
    "ABSTENTION_PHRASE",
    "ANSWER_SYSTEM_PROMPT",
    "RETRIEVED_HEADING",
    "SUPPLEMENT_BANDS",
    "SUPPLEMENT_KINDS",
    "AnswerAttempt",
    "RetrievedContext",
    "answer_messages",
    "answer_question",
    "render_context",
    "retrieve_for",
]

#: The kinds the episodic supplement's read selects (ADR-0158 §3).
#:
#: A two-line copy of ``ai_assistant.orchestration.loop._SUPPLEMENT_KINDS`` rather than
#: an import, because that name is private and the harness does not get to widen a
#: subsystem's surface for its own convenience. The copy is held honest the way
#: ``records.py``'s trace-metric keys are — by a test that fails the day the loop's
#: value moves (``tests/benchmarks/test_harness_contracts.py``) — which is the same
#: trade the composition root's *public* constants do not need.
#:
#: The narrowness is the point: widening this to ``None`` would admit derived
#: *beliefs* into a group appended after the belief group, which is the one way a
#: belief could be shown twice in one prompt.
SUPPLEMENT_KINDS: Final = (MemoryKind.EPISODIC,)

#: The band the episodic supplement's read is pinned to (ADR-0158 §3), copied from
#: ``loop._SUPPLEMENT_BANDS`` under the same discipline as :data:`SUPPLEMENT_KINDS`.
#:
#: Pinned rather than left at ``None``, and not because of an assumption about who
#: writes: capture stamps ``OBSERVED`` so every episode this system writes is
#: ``DERIVED``, but ``EpisodicMemory`` accepts any ``Provenance`` and ``band_of`` maps
#: ``EXTERNAL`` to ``ATTESTED``, so a band-blind read is the one read with no
#: composition to impose ADR-0072 §5's precedence. Nothing in this harness writes a
#: non-``DERIVED`` episode today, which makes the pin inert here — and it is copied
#: anyway, because a harness whose read is only *accidentally* the product's read
#: stops being one the day the corpus grows a channel that writes one.
SUPPLEMENT_BANDS: Final = (BeliefBand.DERIVED,)

#: The phrase the prompt sanctions for declining, exported so the tie between what the
#: model is *asked* to say and what :func:`benchmarks.memory.grade.is_abstention`
#: *detects* is a checkable fact rather than two strings that happen to agree. The
#: detector is deliberately wider than this literal — it tolerates the near-misses a
#: model produces anyway — but this is the phrase the instruction names, so it is the
#: one that must land inside the detector for the measure to hold.
ABSTENTION_PHRASE: Final = "I don't know"

#: The instruction the answering model is given.
#:
#: **It asks for a best effort and it names abstention, and the balance between those
#: two is the decision here.** The first version leaned the other way — "do not guess.
#: If the records do not contain enough information to answer, reply exactly: I don't
#: know" — reasoning that a prompt forbidding abstention would confirm #1029's P7 by
#: construction, so naming abstention would keep the measurement about what retrieval
#: actually supplied. The scored pilot measured what that produced instead: on
#: LoCoMo's *answerable* questions the system declined 1,320 times out of 1,540, and
#: 1,309 of those declines were that exact string (#1029's results comment, and the
#: freeze-relevant follow-up recorded beneath it). The answering model read "do not
#: guess" as a licence to decline on any uncertainty at all, so the headline
#: over-abstention was manufactured by this literal rather than observed in the
#: pipeline. The `deferrals.db` was empty in every case store, which rules the
#: ``ASK_USER`` path out as a cause.
#:
#: So the instruction now asks for the system's best reading of the records and
#: reserves the decline for the case it was meant for. This does not reintroduce the
#: confirm-by-construction problem the first version avoided: abstention is still
#: *named*, still sanctioned, and still the instructed reply where the records do not
#: support an answer, so a system that cannot answer retains a way to say so. What
#: changed is the threshold, from "any uncertainty" to "nothing to answer from".
#:
#: **The decline hinges on support, not on relevance, and the difference is the whole
#: unanswerable population.** A LoCoMo category-5 or LongMemEval ``_abs`` question is
#: unanswerable because the fact is absent from the conversation, not because the
#: conversation never touched the subject — and retrieval, searching with the question's
#: own text, will almost always return records *about* that subject. A threshold phrased
#: as "nothing relevant retrieved" would therefore almost never fire on exactly the
#: questions it exists for, instructing the model to answer where abstaining is the
#: graded-correct behaviour. That would invert the pilot's artifact rather than remove
#: it, so the prompt names the relevant-but-unsupporting case explicitly instead of
#: leaving it to be inferred.
#:
#: **Pilot-4 measured what that threshold change left undone, and these four clauses
#: are the second recalibration.** Moving the threshold worked, and the headline says
#: so: LoCoMo 27.8% → 71.8%, LongMemEval 20% → 68% (#1029's pilot-4 results comment).
#: What is left is not the threshold but *work the instruction never asked for*. Of
#: LoCoMo's 504 errors, **123 are questions declined with the gold evidence in the
#: prompt** — the deep anatomy behind #1210 counts 126 of them — and on LongMemEval,
#: where the gold evidence reached the prompt in 50 questions out of 50, every one of
#: the 16 misses is answer-side: abstentions with the evidence present, a count
#: answered off a single session when the occasions were spread over several,
#: temporal arithmetic not attempted, and a changed fact answered with the value the
#: records themselves supersede. So the instruction now says that partial support is
#: support, asks for every record to be read and aggregated where the question counts
#: or lists, asks for the arithmetic where the records carry dates, and says the later
#: record wins where two disagree about something that changes.
#:
#: **The partial-support clause is bounded, and the boundary is the one the paragraph
#: above draws.** "Partial" means an answer that is *incomplete* — some of a list, a
#: date fixed only to its month — and never a question whose particular fact is
#: absent from records that discuss its subject, which is what every unanswerable
#: question in both corpora looks like. Left unbounded it would read as a licence to
#: name a breed for a cat the records only say was adopted, inverting cat 5 and the
#: ``_abs`` variants exactly as a relevance-conditioned decline would. The clause
#: therefore sits *after* the decline and restates the boundary in its own words
#: rather than beside it, so that the two cannot be read as alternatives to choose
#: between (the adversarial round on #1212 read them that way when they sat the other
#: way round). **None of them touches
#: the threshold**, which the paragraphs above settle and pilot-4 vindicated; they say
#: what to *do* with records that already clear it. This is again a re-run under its
#: own registration, pre-registered as an arm on #1029, and not an amendment to
#: pilot-4's numbers.
#:
#: **Every added clause is conditioned on a signal the rendered block actually
#: carries, and names what to do where it does not, because the block carries almost
#: nothing.** :func:`_render_record` mirrors the product's bullet — kind, source,
#: content — and drops ``occurred_at``, ``provenance`` and every other field; the
#: module docstring argues why the mirror keeps those omissions, and #1194 is the
#: product-side fix that removes the first of them. So a clause telling the model to
#: read "the date of the record" or "the newer record" would describe a prompt this
#: module does not build, which is the drift the "listed"/"numbered" paragraph below
#: exists to prevent — and, worse, would ask for an answer from a field that is not
#: there, against the records-only constraint that is the whole experiment. Three
#: consequences, each of which the adversarial round on #1212 named as its own
#: finding:
#:
#: * *Dates.* The clause fires "where the records carry dates or times", resolves
#:   relative wording against "a date the records actually show", forbids supplying a
#:   date they do not, and asks for the ordering or the interval where nothing fixes
#:   an absolute one. True of the dates inside a record's *content* today, true of a
#:   rendered instant once #1194 lands, and asserting neither.
#: * *Conflicts.* "Which is later" is judged by a date **or by wording that describes
#:   a change** — the signal a knowledge-update belief actually carries in its content
#:   — and explicitly *not* by list position, which is the retrieval composition's
#:   precedence order (ADR-0072 §5) and not chronology. Where neither shows, the
#:   instruction asks for the best-supported value rather than a decline, because a
#:   decline here would be the pilot-1 artifact returning through a side door.
#: * *Counting.* The aggregation clause counts **occasions, not records**. A belief
#:   and the episode it was distilled from are two records describing one occasion and
#:   both reach the prompt — the belief read and the episodic supplement are separate
#:   reads deduplicated by id (ADR-0158 §4), so corroboration is the normal case and
#:   "gather across all the records" alone would inflate every count.
#:
#: **Nothing here gives the model a present moment, and supplying one is not this
#: literal's to do.** :func:`_moved_clock` sets the benchmark clock to the question's
#: stated instant and :attr:`AnswerAttempt.asked_at` records where it landed, but
#: :func:`answer_messages` sends the context block and the question and nothing else —
#: so "how long ago" is relative to an anchor the model is never shown, whatever the
#: records carry. That is a property of the prompt, not a wording defect this clause
#: could repair, and patching it here would be the harness answering a temporal
#: question from something the shipped prompt withholds. It is #1211.
#:
#: **Three clauses exist for the measure rather than for the answer.** The prompt asks
#: for :data:`ABSTENTION_PHRASE` verbatim, because ``is_abstention`` reads the answer's
#: text and the run has no other channel. And it forbids both a stated confidence and
#: an opening caveat, because ``is_abstention`` is anchored at the start: a hedged best
#: effort opening "the records do not clearly say, but ..." is scored as a decline by
#: the detector even though it answered, which would move the artifact from the prompt
#: into the grader instead of removing it. Those two clauses are an instruction and not
#: an enforcement — the residual, and the question of whether the detector itself should
#: read past a caveat, is #1168, deliberately not settled here because narrowing
#: ``is_abstention`` would redefine the measure the pilot's published numbers were
#: computed under.
#:
#: **One clause tracks the renderer rather than the measure.** The instruction names
#: the shape of what follows it, so it says "listed" where it said "numbered":
#: :func:`render_context` renders the product's bullets and numbers nothing (#1189). A
#: prompt describing a format the prompt does not carry is drift the harness cannot
#: detect from its own artifacts, since both are recorded and neither is compared.
#:
#: The literal is exported so a run's manifest can record it. A prompt is a
#: configuration of the experiment, and a pilot whose prompt is not recoverable from
#: its artifacts is not reproducible in the only sense a benchmark can be. Two runs
#: whose prompts differ are two arms, which is why this change is a re-run under its
#: own registration and not an amendment to the pilot's numbers.
ANSWER_SYSTEM_PROMPT: Final = (
    "You are answering a question about a person's past conversations. "
    "The only information available to you is the memory records listed below, "
    "retrieved from a long-term memory store. Answer from those records alone: do "
    "not use general knowledge. "
    "Give your best answer whenever the records plausibly support one — including "
    "when it has to be inferred, pieced together from several records, or read "
    "through wording that differs from the question's, and including when you are "
    "not certain. A best effort from the records is what is wanted. "
    "Where the records give you nothing to answer from, reply exactly: "
    f"{ABSTENTION_PHRASE}. That includes the case where they discuss the subject of "
    "the question but do not contain the fact it asks for — being on the topic is not "
    "the same as supporting an answer. "
    "Partial support is still support: where the records support an answer that is "
    "incomplete or approximate — some of the items a list asks for, a date fixed only "
    "to its month, one of several reasons — give that answer rather than declining "
    "because it is not the whole of what was asked. That does not loosen the rule "
    "above: where the particular fact the question asks for is absent, the records "
    "support no answer at all, however much they say about its subject. "
    "Read every record before you answer, not only the first that looks relevant. "
    "Where the question asks how many, how often, or for a list, gather the answer "
    "across all of the records together: the occasions it asks about are usually "
    "spread over several separate conversations, and one record describing one of "
    "them is rarely the whole count. Count occasions, not records — two records "
    "describing the same occasion, such as a summary of an event and the event "
    "itself, are one occasion and not two. "
    "Where the records carry dates or times, work with them rather than repeating "
    "them: put events in order, compute the interval or the elapsed time the question "
    "asks for, and read any relative wording — 'yesterday', 'last summer' — against a "
    "date the records actually show. Give an absolute date where the question asks "
    "when something happened and the records fix one; never supply a date they do "
    "not. Where nothing shown fixes an absolute date, answer with what the records do "
    "fix, such as the order of the events or the gap between them. "
    "Where two records disagree about something that can change, answer from the "
    "later one and treat the earlier as superseded rather than as an equally good "
    "answer. Judge which is later by what the records themselves show — a date, or "
    "wording that describes a change, such as 'moved to', 'switched to' or 'now' — "
    "and not by the order they are listed in, which is not chronological. Where "
    "nothing shows which of the two is later, give the value the records support "
    "best rather than declining. "
    "When you do answer, answer as briefly as the question allows — a name, a date, a "
    "phrase — with no preamble, no explanation, no statement of how confident you are, "
    "and no opening caveat about the records."
)

#: What the model is shown when retrieval returned nothing at all. Stated rather than
#: sending an empty section, because an empty section reads as a formatting error and
#: this is a real, and predicted, outcome.
#:
#: The product has its own line for this state — ``planning.planner._render_request``
#: emits "No stored memories were retrieved for this goal." — and this one is
#: deliberately *not* a copy of it. That sentence names a goal, and a benchmark
#: question is not one; the equivalence the harness owes is over the rendering of the
#: records it has, which is what :data:`RETRIEVED_HEADING` and :func:`render_context`
#: hold. Nothing downstream reads this literal except ``context_chars``.
EMPTY_CONTEXT: Final = "(no memory records were retrieved)"

#: The heading the product puts the relevance-retrieved group under — the product's
#: own constant, re-exported here under the name this module's callers already use.
#:
#: **Imported rather than copied** (#1181). It used to be a verbatim copy, on the
#: ground that a literal inside a private function is not a surface the harness gets
#: to widen for its own convenience. That ground survives — nothing in ``planning``
#: was made public for this — but the copy did not: the equivalence test caught drift
#: only after somebody wrote it, and #1181 asks for the divergence to be impossible
#: rather than detected. Reading a private name knowingly is the cheaper of the two,
#: and it is what ``tests/benchmarks/test_render_context.py`` already did to check the
#: copy.
#:
#: **It is always the retrieved group's heading and never the tail's**, because the
#: harness cannot produce a tail: ``answer_question`` appends the supplement after the
#: beliefs and ADR-0158 §4's separator rule drops it where the beliefs came back empty,
#: so ``planner._split_conversation_tail`` over these records always returns an empty
#: leading episodic run. A benchmark question is a fresh conversation's first turn and
#: there is no recent conversation to head.
RETRIEVED_HEADING: Final = _RETRIEVED_HEADING


@dataclass(frozen=True, slots=True)
class AnswerAttempt:
    """One question answered, with everything the post-hoc analysis needs.

    Attributes:
        correlation_id: The scope every retrieval trace for this answer carries.
        answer: What the model said.
        retrieved_ids: The records placed in the prompt, in prompt order — the
            belief composition first and then the episodic supplement (ADR-0158 §4),
            which is the order the model read them in.
        retrieved_kinds: Each record's ``kind``, aligned with ``retrieved_ids``.

            **This is the whole of the episodic-rescue attribution**, which replaced
            the beliefs-versus-episodes ablation arm: two arms would have been two
            paid runs, and the same question is answerable post hoc from one. An
            ``EPISODIC`` entry here is a record that reached the prompt through the
            supplement and could have reached it no other way, because the belief
            composition's ``kinds`` filter excludes that kind by construction
            (ADR-0158 §2). Joined against ``retrieved_evidence`` — where a *rescue* is
            a right answer whose supporting episode no retrieved belief cites — this
            says how much of any improvement the supplement bought, per question,
            without a second run.
        retrieved_evidence: The **episode ids standing behind** each retrieved record,
            aligned with ``retrieved_ids``. This is the retrieval half of #1074's join:
            the corpus names its evidence by turn, ingestion records which episode each
            cited turn became, and this says which episodes stand behind what actually
            reached the prompt. For a belief it is ``provenance.evidence``, the
            producer's own citation list, which outlives the episode it names — so the
            join survives a finite ``episode_retention`` that already expired the
            episode itself.

            **For an episode it is the episode's own id, and that is #1187.** An
            episode cites nothing — capture leaves ``evidence`` empty deliberately,
            because "an episode is the terminal citation ... so requiring it to cite
            something would demand a regress"
            (``orchestration.conversations.ConversationLifecycle._episode``). Reading
            the field literally therefore gave every supplemented episode an empty
            tuple, and the pilot-3 partial recorded 6,735 of them: the intersection
            ADR-0158's attribution is defined as was zero *by construction*, so the
            supplement could not be credited with a single rescue however many it made.
            Naming the record itself is not a workaround for that — it is what the
            field already means. ``evidence_episode_ids`` holds generated **episode
            ids** (``IngestionSummary.evidence_episodes`` maps a corpus pointer to the
            ``conv:<conversation>:<ordinal>`` id capture minted), and a retrieved
            episode's own id is drawn from that same space, so
            ``gold ∩ retrieved_evidence`` needs no special case for kind and the
            post-hoc split reads one rule over both groups.
        retrieved_evidence_elided: ``provenance.evidence_elided`` per retrieved
            record, aligned with ``retrieved_ids``. Non-zero means the belief has
            **stopped carrying** some of its citations (ADR-0086 §4), so an empty
            intersection against a question's evidence reads "cannot tell" rather than
            "the evidence was never retrieved". Carried because that is precisely the
            distinction P8 is, and the one an elision silently corrupts.
        context: The rendered context block, exactly as the model saw it.
        asked_at: The instant the clock was set to while answering.
        failure: The class name of the provider error that stopped this answer, or
            ``None`` where one was produced. **Everything above it is still real** —
            retrieval had already run when the failure landed, so the ids and the
            correlation id are the retrieval's own and the telemetry is attributable.
            Only its message is dropped: a provider's error text is untrusted content.
    """

    correlation_id: str
    answer: str
    retrieved_ids: tuple[str, ...]
    retrieved_kinds: tuple[str, ...]
    retrieved_evidence: tuple[tuple[str, ...], ...]
    retrieved_evidence_elided: tuple[int, ...]
    context: str
    asked_at: str
    failure: str | None = None


def render_context(records: Sequence[MemoryRecord]) -> str:
    """Render retrieved records as the block the product's answering prompt shows.

    One heading and the product's own bullet per record — :data:`RETRIEVED_HEADING`,
    then ``planner._render_record`` for each — which is exactly what
    ``planning.planner._render_request`` builds for a turn whose memories are all
    relevance-retrieved. That is the whole of the change #1189 asked for, and the
    module docstring holds the argument: a prompt carrying each record's ``id``,
    provenance, validity window and scores is a prompt the product never assembles, so
    a benchmark scored under it scores a system nobody ships.

    **A record is not always one line.** Since #1194 an episode that recorded an
    outcome renders a continuation line under its own bullet, so this joins rendered
    *records* rather than counting lines, and a reader of the block must not assume
    one line per record either.

    **The supplement needs nothing here**, which is a finding rather than an omission.
    ADR-0158 §4's groups are carried by *position*, and the product's own renderer
    shows the retrieved beliefs and the supplemented episodes as one undifferentiated
    list in that order; each line's ``[kind/source]`` tag already tells the model which
    is which, in the same words the product uses.

    Args:
        records: What retrieval returned — the beliefs, best first, then the
            episodic supplement (ADR-0158 §4).

    Returns:
        The block, or :data:`EMPTY_CONTEXT` when there is nothing.
    """
    if not records:
        return EMPTY_CONTEXT
    return "\n".join([RETRIEVED_HEADING, *(_render_record(record) for record in records)])


async def _supplement(
    harness: Harness, query: str, *, preceding: Sequence[MemoryRecord]
) -> tuple[MemoryRecord, ...]:
    """Retrieve *episodes* relevant to ``query``, to append after the beliefs.

    A hand-mirror of ``ai_assistant.orchestration.loop.LearningLoop._supplement``,
    line for line where the two can be the same. Every argument that keeps this from
    being naive RAG over the transcript is here rather than in a policy: ``kinds`` is
    :data:`SUPPLEMENT_KINDS`, ``bands`` is :data:`SUPPLEMENT_BANDS`, and the budget is
    the harness's own ``episodic_limit``, which is never taken out of the belief
    budget (ADR-0158 §2, §3). Merging the two reads into one kind-blind call is what
    ADR-0158 §2 refuses: ADR-0128 §1 binds ``kinds`` before the KNN cut, so an
    admitted episode spends a candidate slot no later pass can give back, and a store
    holds an episode per turn against a belief per distilled fact — under one shared
    budget the belief layer would be routinely displaced from its own prompt.

    **The separator check is live here and the tail deduplication is not**; the module
    docstring works both through against §4. The check is made *before* the read, as
    the loop makes it, so a dropped supplement also costs no ``RETRIEVAL`` trace — which
    matters more here than there, because those traces are the P4 count.

    **The one deliberate deviation: a store failure is not caught.** ADR-0158 §4 has
    the loop swallow a failed episodic read and keep the beliefs, because a user's
    answer is worth more than the supplement and the alternative is no answer at all.
    A benchmark has the opposite loss function. :func:`answer_question` already
    declines to catch ``MemoryStoreError`` for the belief read, in as many words: it is
    not a per-question outcome, and a run whose store is failing should stop rather
    than record hundreds of answers that look like reader errors. Swallowing it here
    would be worse than there — a systematically failing episodic read would produce a
    whole run of belief-only prompts, scored and published as a measurement of a
    configuration that never ran, with nothing in the artifacts to say so. The mirror
    is therefore exact on every path where the store works, and diverges only in what
    a broken store does to the run.

    Args:
        harness: The wired pipeline, read for the store and the episodic budget.
        query: The question, which is the same text the belief composition was read
            with — the loop passes its goal statement to both reads.
        preceding: The records already assembled, in order. Read for the separator
            rule and for deduplication, never appended to here.

    Returns:
        Up to ``harness.episodic_limit`` episodes, best first, none of them already in
        ``preceding``. Empty where the bound is zero or the separator is absent.

    Raises:
        MemoryStoreError: If the read failed, deliberately unhandled (above).
    """
    if harness.episodic_limit <= 0:
        return ()
    if all(MemoryKind(record.kind) is MemoryKind.EPISODIC for record in preceding):
        return ()
    found = await harness.store.search(
        query,
        limit=harness.episodic_limit,
        kinds=SUPPLEMENT_KINDS,
        bands=SUPPLEMENT_BANDS,
    )
    # `capped` is unwrapped and not acted on, as the loop leaves it (ADR-0128 §6): the
    # offline reading of the same fact is `RetrievalTelemetry.ceiling_bound`, derived
    # from this call's own trace, so nothing is lost by not asserting it here.
    held = {record.id for record in preceding}
    return tuple(record for record in found.records if record.id not in held)


def _standing_evidence(record: MemoryRecord) -> tuple[str, ...]:
    """The episode ids standing behind one retrieved record (#1187).

    A belief stands on the episodes it cites. An **episode stands on itself**: it is
    the terminal citation, so capture writes it with an empty ``evidence`` on purpose,
    and reading that field literally made every supplemented episode contribute nothing
    to the join ADR-0158's attribution is computed from. Both ids come from the same
    space — ``evidence_episode_ids`` holds captured episode ids, and a retrieved
    episode's ``id`` is one — so this makes ``gold ∩ retrieved_evidence`` a single rule
    over both kinds rather than two rules and a branch in every reader.

    The record's own citations are kept after its id rather than replaced by it: an
    episode this harness writes carries none, but ``EpisodicMemory`` does not forbid
    them, and dropping a citation that was there would lose evidence to make a shape
    tidy. The id is filtered out of the tail so a self-citation cannot appear twice and
    inflate a count someone takes over this tuple.

    Args:
        record: A record that reached the prompt.

    Returns:
        The ids, the record's own first where it is an episode.
    """
    cited = tuple(record.provenance.evidence)
    if MemoryKind(record.kind) is not MemoryKind.EPISODIC:
        return cited
    return (record.id, *(identifier for identifier in cited if identifier != record.id))


@dataclass(frozen=True, slots=True)
class RetrievedContext:
    """One question's two reads, assembled into a prompt no model has seen yet.

    **This exists because the batch phase answers hours after it retrieves**, and
    everything #1029 computes about retrieval has to be captured at the moment the
    reads happen rather than at the moment an answer comes back. A synchronous run
    could keep the two together; a batched one cannot, so the split is made once,
    here, and both phases go through it.

    What that buys is that the phases cannot diverge on the thing being measured.
    The reads, their order, the separator rule, the rendering and the correlation
    scope are all in :func:`retrieve_for`, which is the only way either phase gets a
    prompt — so ``retrieved_ids``, ``retrieved_kinds``, ``retrieved_evidence`` and
    the ``RETRIEVAL`` traces behind ``correlation_id`` mean exactly the same thing in
    a ``--phase batch`` run as in a ``--phase sync`` one.

    **The one real difference between the phases, stated rather than left to be
    discovered.** A synchronous answer's model call happens *inside* the correlation
    scope and a batched one happens outside it, long after the scope closed. Nothing
    recorded moves: the model seam emits no trace at all — ``TraceKind`` has five
    members and none of them is a completion — and
    :meth:`~benchmarks.memory.records.TraceCursor.collect` keeps only ``RETRIEVAL``
    traces carrying this id. So the P4 count and the P8 split are computed over the
    same events either way.

    Attributes:
        correlation_id: The scope every ``RETRIEVAL`` trace for this question
            carries, opened and closed around the reads alone.
        messages: The exact conversation to send, system turn first. Held rather
            than rebuilt so a batch item and a synchronous call carry the same bytes.
        retrieved_ids: The records placed in the prompt, in prompt order.
        retrieved_kinds: Each record's ``kind``, aligned with ``retrieved_ids``.
        retrieved_evidence: The episode ids standing behind each retrieved record.
        retrieved_evidence_elided: ``provenance.evidence_elided`` per record.
        context: The rendered context block, exactly as the model will see it.
        asked_at: The instant the clock was set to while retrieving.
    """

    correlation_id: str
    messages: tuple[Message, ...]
    retrieved_ids: tuple[str, ...]
    retrieved_kinds: tuple[str, ...]
    retrieved_evidence: tuple[tuple[str, ...], ...]
    retrieved_evidence_elided: tuple[int, ...]
    context: str
    asked_at: str

    def answered(self, *, answer: str, failure: str | None = None) -> AnswerAttempt:
        """Pair this retrieval with whatever the model eventually said.

        Args:
            answer: The model's reply, stripped, or ``""`` where none came back.
            failure: The class name of what stopped it, or ``None``.

        Returns:
            The attempt, carrying this retrieval's own ids and telemetry scope.
        """
        return AnswerAttempt(
            correlation_id=self.correlation_id,
            answer=answer,
            retrieved_ids=self.retrieved_ids,
            retrieved_kinds=self.retrieved_kinds,
            retrieved_evidence=self.retrieved_evidence,
            retrieved_evidence_elided=self.retrieved_evidence_elided,
            context=self.context,
            asked_at=self.asked_at,
            failure=failure,
        )


def answer_messages(context: str, question: str) -> tuple[Message, ...]:
    """The exact conversation the answering model is shown.

    One function so a batch item and a synchronous call carry the same bytes, which
    is what makes the manifest's recorded ``answer_prompt`` true of both phases.

    Args:
        context: The rendered context block.
        question: The question as asked.

    Returns:
        The system turn and the user turn, in order.
    """
    return (
        Message(role=Role.SYSTEM, content=ANSWER_SYSTEM_PROMPT),
        Message(
            role=Role.USER,
            # No "Memory records:" line above the block any more: since #1189 the
            # block opens with the product's own heading, and a second heading over
            # it would be a section the product never emits — reintroducing, one line
            # smaller, exactly the divergence that change removed.
            content=f"{context}\n\nQuestion: {question}",
        ),
    )


async def _read_for(harness: Harness, question: BenchQuestion) -> tuple[MemoryRecord, ...]:
    """The two reads, in the product's order, with no scope of their own.

    Called only from inside a correlation scope the caller opened, because the
    traces these emit are what that scope exists to collect.

    Args:
        harness: The wired pipeline.
        question: The question to read for.

    Returns:
        The belief composition, then the episodic supplement (ADR-0158 §4).
    """
    beliefs = tuple(
        await assemble_by_band(
            harness.store,
            question.question,
            limit=harness.retrieval_limit,
            kinds=BELIEF_KINDS,
        )
    )
    return beliefs + await _supplement(harness, question.question, preceding=beliefs)


def _moved_clock(harness: Harness, question: BenchQuestion) -> str:
    """Set the benchmark clock to the question's instant, and report where it is.

    Args:
        harness: The wired pipeline.
        question: The question, carrying an instant where its corpus states one.

    Returns:
        The clock's reading, ISO-8601.
    """
    if question.asked_at is not None:
        harness.clock.set(question.asked_at)
    return harness.clock().isoformat()


def _assembled(
    correlation_id: str,
    records: Sequence[MemoryRecord],
    question: BenchQuestion,
    asked_at: str,
) -> RetrievedContext:
    """Turn what the reads returned into the prompt and the record of them.

    Args:
        correlation_id: The scope the reads ran under.
        records: What they returned, in prompt order.
        question: The question.
        asked_at: The clock's reading.

    Returns:
        The assembled context.
    """
    context = render_context(records)
    return RetrievedContext(
        correlation_id=correlation_id,
        messages=answer_messages(context, question.question),
        retrieved_ids=tuple(record.id for record in records),
        retrieved_kinds=tuple(record.kind for record in records),
        retrieved_evidence=tuple(_standing_evidence(record) for record in records),
        retrieved_evidence_elided=tuple(record.provenance.evidence_elided for record in records),
        context=context,
        asked_at=asked_at,
    )


async def retrieve_for(harness: Harness, question: BenchQuestion) -> RetrievedContext:
    """Do everything :func:`answer_question` does except ask the model.

    The batch phase's entry point, and the reason the split exists: an answer batch
    is assembled from thousands of these, submitted once, and read back hours later.
    Its retrieval is this function's, not a copy of it.

    A *retrieval* failure is deliberately not caught here, on either read, for the
    reason :func:`answer_question` gives: ``MemoryStoreError`` is not a per-question
    outcome, and a run whose store is failing should stop rather than assemble a
    batch of empty prompts and pay to have them answered.

    Args:
        harness: The wired pipeline.
        question: The question to retrieve for.

    Returns:
        The assembled prompt and everything the post-hoc analysis reads.

    Raises:
        MemoryStoreError: If either read failed, deliberately unhandled.
    """
    asked_at = _moved_clock(harness, question)
    with correlated_operation() as correlation_id:
        records = await _read_for(harness, question)
        return _assembled(correlation_id, records, question, asked_at)


async def answer_question(harness: Harness, question: BenchQuestion) -> AnswerAttempt:
    """Retrieve for one question and answer it from what came back.

    **Two reads, in the product's order** (ADR-0158): the belief composition through
    ``assemble_by_band``, then :func:`_supplement`'s episodic read appended after it.
    Both run inside the one correlation scope, so the P4 count is now up to *four*
    ``MemoryStore.search`` crossings per answer rather than up to three — three bands
    and the supplement — and every one of them is still evidence read off the traces
    rather than a number this driver asserts.

    The clock is moved to the question's stated instant where the corpus gives one,
    so retrieval's liveness axes are judged at the moment the question is asked rather
    than at the moment the last session was captured. LoCoMo states none; there the
    clock is left where ingestion left it, which is the instant of the final session.

    **A provider failure is returned, not raised**, and the handling is *inside* the
    correlation scope, which is what makes it more than a convenience. Retrieval has
    already run and already emitted its traces by the time the provider is called, so
    a failure caught outside the scope would lose the id those traces carry — and the
    trace cursor, walking forward, would step past them permanently. The result would
    be a record claiming zero retrieval calls for an answer that made one to three,
    which is a false entry in exactly the field #1029's P8 is computed from. Handled
    here, a failed answer keeps its real ids and its real telemetry and reports only
    that no answer came back.

    A *retrieval* failure is deliberately not caught, on **either** read:
    ``MemoryStoreError`` is not a per-question outcome, and a run whose store is
    failing should stop rather than record hundreds of empty answers. For the episodic
    read that is a considered departure from ADR-0158 §4's failure rule, argued in
    :func:`_supplement`.

    Args:
        harness: The wired pipeline.
        question: The question to answer.

    Returns:
        The attempt, carrying :attr:`AnswerAttempt.failure` where the provider failed.
    """
    asked_at = _moved_clock(harness, question)

    # The completion stays *inside* the scope, which is why this does not simply call
    # `retrieve_for`. It costs nothing recorded — the model seam emits no trace — but
    # the scope is also what the failure handling below sits in, and that placement is
    # load-bearing: retrieval has already emitted its traces by the time a provider
    # fails, and a failure caught outside the scope would lose the id those traces
    # carry while the cursor walked past them for good.
    with correlated_operation() as correlation_id:
        records = await _read_for(harness, question)
        prepared = _assembled(correlation_id, records, question, asked_at)
        failure: str | None = None
        answer = ""
        try:
            reply = await harness.model.complete(list(prepared.messages))
        except ModelError as error:
            failure = type(error).__name__
        else:
            answer = reply.content.strip()
    return prepared.answered(answer=answer, failure=failure)
