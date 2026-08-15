"""Answer one benchmark question from retrieved context and nothing else.

**"Reads only retrieved context" is the whole experiment**, so it is enforced by
construction rather than by prompt wording: the only conversation material this module
can reach is the record list ``assemble_by_band`` returned. The corpus is not in
scope here, the case is not passed in, and the question text is the single other input.

**The retrieval path is the product's, not a convenience call.**
``assemble_by_band`` is what ``LearningLoop`` uses, with the same
``BELIEF_KINDS`` filter and the same budget imported from the composition root — one
band-scoped ``search`` per band in precedence order, deduplicated across the calls
(ADR-0072 §5, ADR-0113 §5). A single ``store.search`` would be a different retrieval
system, and the numbers would not be about this one.

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
from ai_assistant.core.types import Message, Role
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
    "AnswerAttempt",
    "answer_question",
    "render_context",
]

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
#: The literal is exported so a run's manifest can record it. A prompt is a
#: configuration of the experiment, and a pilot whose prompt is not recoverable from
#: its artifacts is not reproducible in the only sense a benchmark can be. Two runs
#: whose prompts differ are two arms, which is why this change is a re-run under its
#: own registration and not an amendment to the pilot's numbers.
ANSWER_SYSTEM_PROMPT: Final = (
    "You are answering a question about a person's past conversations. "
    "The only information available to you is the numbered memory records below, "
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
EMPTY_CONTEXT: Final = "(no memory records were retrieved)"


@dataclass(frozen=True, slots=True)
class AnswerAttempt:
    """One question answered, with everything the post-hoc analysis needs.

    Attributes:
        correlation_id: The scope every retrieval trace for this answer carries.
        answer: What the model said.
        retrieved_ids: The records placed in the prompt, in prompt order.
        retrieved_kinds: Each record's ``kind``, aligned with ``retrieved_ids``.
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


def render_context(records: Sequence[MemoryRecord]) -> str:
    """Render retrieved records as the numbered block the model reads.

    Every record is rendered through its own ``model_dump_json``, which is blunt and
    deliberate: a hand-written renderer per kind would be a place for the harness to
    decide what the model gets to see, and the whole point is that it sees what the
    store holds. The one thing dropped is the embedding, which no store returns on a
    record anyway.

    Args:
        records: What retrieval returned, best first.

    Returns:
        The block, or :data:`EMPTY_CONTEXT` when there is nothing.
    """
    if not records:
        return EMPTY_CONTEXT
    return "\n".join(
        f"[{index}] {record.model_dump_json()}" for index, record in enumerate(records, start=1)
    )


async def answer_question(harness: Harness, question: BenchQuestion) -> AnswerAttempt:
    """Retrieve for one question and answer it from what came back.

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

    A *retrieval* failure is deliberately not caught: ``MemoryStoreError`` is not a
    per-question outcome, and a run whose store is failing should stop rather than
    record hundreds of empty answers.

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
        records = await assemble_by_band(
            harness.store,
            question.question,
            limit=harness.retrieval_limit,
            kinds=BELIEF_KINDS,
        )
        context = render_context(records)
        failure: str | None = None
        answer = ""
        try:
            reply = await harness.model.complete(
                [
                    Message(role=Role.SYSTEM, content=ANSWER_SYSTEM_PROMPT),
                    Message(
                        role=Role.USER,
                        content=f"Memory records:\n{context}\n\nQuestion: {question.question}",
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
