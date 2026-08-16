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

**A record is rendered the way the product renders it, one line, and that is the whole
of :func:`render_context`.** It used to dump each record's ``model_dump_json`` — id,
provenance with its entire evidence list, validity window, scores — on the stated
ground that the model should see "what the store holds". That ground was wrong about
the thing the harness exists to mirror: the product shows the answering model one line
per memory, ``  - [kind/source] content`` (``planning.planner._render_record``), and
never the record's machinery. The cost was measured on the pilot-3 partial and it is
not small — a median answer context of 15,922 characters for 15 beliefs and 5
one-line episodes, roughly 800 characters per record against ~150 characters of
content — but the size is the lesser half of it (#1189). The larger half is that a
prompt carrying UUIDs, confidence scores and validity bounds is a *different* prompt
from the product's, so a score computed under it is a score for a system nobody ships.

**Everything the product's line omits is omitted here too, including where the omission
costs the harness something.** ``occurred_at`` is the case worth naming: an episode
carries the instant it happened and ``_render_record`` does not show it, so neither
does this — a harness that added it back would be answering LoCoMo's temporal category
from a field the shipped prompt withholds, which is #1029's P2 measured on the wrong
system. ``outcome`` — the assistant half of a captured episode — is dropped for the
same reason and by the same line, which is a real limitation of the product's renderer
rather than of this mirror, and is filed as its own issue rather than patched here.

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
    "answer_question",
    "render_context",
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

#: The heading the product puts the relevance-retrieved group under, copied verbatim
#: from ``planning.planner._render_request``.
#:
#: Copied rather than imported, under the discipline :data:`SUPPLEMENT_KINDS` is copied
#: under: it is a literal inside a private function and the harness does not get to
#: widen a subsystem's surface for its own convenience. The copy is held honest by
#: ``tests/benchmarks/test_render_context.py``, which renders the same records through
#: the planner's own request renderer and asserts this block appears in it verbatim —
#: an equivalence over behaviour rather than over a string, so it also catches the
#: bullet's shape moving.
#:
#: **It is always the retrieved group's heading and never the tail's**, because the
#: harness cannot produce a tail: ``answer_question`` appends the supplement after the
#: beliefs and ADR-0158 §4's separator rule drops it where the beliefs came back empty,
#: so ``planner._split_conversation_tail`` over these records always returns an empty
#: leading episodic run. A benchmark question is a fresh conversation's first turn and
#: there is no recent conversation to head.
RETRIEVED_HEADING: Final = "Relevant memories about the user:"


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
        retrieved_evidence: The **episode ids** each retrieved record cites, aligned
            with ``retrieved_ids``. This is the retrieval half of #1074's join: the
            corpus names its evidence by turn, ingestion records which episode each
            cited turn became, and this says which episodes stand behind the beliefs
            that actually reached the prompt. Read off ``provenance.evidence``, the
            producer's own citation list, which outlives the episode it names — so the
            join survives a finite ``episode_retention`` that already expired the
            episode itself.
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


def _render_record(record: MemoryRecord) -> str:
    """Render one record as the product's prompt bullet.

    A hand-copy of ``ai_assistant.planning.planner._render_record``, character for
    character, for the reason :data:`RETRIEVED_HEADING` is copied: it is private, and
    an equivalence test rather than an import is what keeps a copy honest here.

    ``record.kind`` is interpolated as it stands rather than through
    :class:`~ai_assistant.core.types.MemoryKind`, because that is what the product's
    line does — the discriminator is a ``Literal`` str, so the two are the same
    characters, and taking the enum's ``.value`` would be a second way to spell it that
    could drift.

    Args:
        record: The record to render.

    Returns:
        The bullet, with the product's two-space indent.
    """
    return f"  - [{record.kind}/{record.provenance.source.value}] {record.content}"


def render_context(records: Sequence[MemoryRecord]) -> str:
    """Render retrieved records as the block the product's answering prompt shows.

    One heading and one line per record — :data:`RETRIEVED_HEADING`, then
    :func:`_render_record` for each — which is exactly what
    ``planning.planner._render_request`` builds for a turn whose memories are all
    relevance-retrieved. That is the whole of the change #1189 asked for, and the
    module docstring holds the argument: a prompt carrying each record's ``id``,
    provenance, validity window and scores is a prompt the product never assembles, so
    a benchmark scored under it scores a system nobody ships.

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
    if question.asked_at is not None:
        harness.clock.set(question.asked_at)
    asked_at = harness.clock().isoformat()

    with correlated_operation() as correlation_id:
        beliefs = tuple(
            await assemble_by_band(
                harness.store,
                question.question,
                limit=harness.retrieval_limit,
                kinds=BELIEF_KINDS,
            )
        )
        records = beliefs + await _supplement(harness, question.question, preceding=beliefs)
        context = render_context(records)
        failure: str | None = None
        answer = ""
        try:
            reply = await harness.model.complete(
                [
                    Message(role=Role.SYSTEM, content=ANSWER_SYSTEM_PROMPT),
                    Message(
                        role=Role.USER,
                        # No "Memory records:" line above the block any more: since
                        # #1189 the block opens with the product's own heading, and a
                        # second heading over it would be a section the product never
                        # emits — reintroducing, one line smaller, exactly the
                        # divergence that change removed.
                        content=f"{context}\n\nQuestion: {question.question}",
                    ),
                ]
            )
        except ModelError as error:
            failure = type(error).__name__
        else:
            answer = reply.content.strip()
    return AnswerAttempt(
        correlation_id=correlation_id,
        answer=answer,
        retrieved_ids=tuple(record.id for record in records),
        retrieved_kinds=tuple(record.kind for record in records),
        retrieved_evidence=tuple(tuple(record.provenance.evidence) for record in records),
        retrieved_evidence_elided=tuple(record.provenance.evidence_elided for record in records),
        context=context,
        asked_at=asked_at,
        failure=failure,
    )
