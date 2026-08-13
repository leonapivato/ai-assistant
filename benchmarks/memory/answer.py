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
  ``returned`` ids, ``limit``, ``fetch_k``, ``candidates`` and ``capped``. That is
  enough to ask "was the evidence in context?" of every wrong answer, which is the
  split P8 predicts.

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
from ai_assistant.core.types import Message, Role
from ai_assistant.orchestration.conversations import BELIEF_KINDS
from ai_assistant.orchestration.retrieval import assemble_by_band

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryRecord
    from benchmarks.memory.cases import BenchQuestion
    from benchmarks.memory.wiring import Harness

__all__ = ["ANSWER_SYSTEM_PROMPT", "AnswerAttempt", "answer_question", "render_context"]

#: The instruction the answering model is given.
#:
#: **It names abstention explicitly**, and that is a decision worth arguing rather
#: than assuming. #1029's P7 predicts we over-answer because "nothing in the pipeline
#: currently signals 'retrieval found nothing sufficient'". That prediction is about
#: the *pipeline*, and a prompt that forbade abstention would confirm it by
#: construction while a prompt that never mentioned it would leave the result
#: dependent on the answering model's habits. Naming it makes the measurement about
#: what retrieval actually supplied: the model is told it may say it does not know,
#: so an over-answer is the pipeline's, not the prompt's.
#:
#: The literal is exported so a run's manifest can record it. A prompt is a
#: configuration of the experiment, and a pilot whose prompt is not recoverable from
#: its artifacts is not reproducible in the only sense a benchmark can be.
ANSWER_SYSTEM_PROMPT: Final = (
    "You are answering a question about a person's past conversations. "
    "The only information available to you is the numbered memory records below, "
    "retrieved from a long-term memory store. Answer from those records alone: do "
    "not use general knowledge, and do not guess. If the records do not contain "
    "enough information to answer, reply exactly: I don't know. "
    "Otherwise answer as briefly as the question allows — a name, a date, a phrase — "
    "with no preamble and no explanation."
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
        context: The rendered context block, exactly as the model saw it.
        asked_at: The instant the clock was set to while answering.
    """

    correlation_id: str
    answer: str
    retrieved_ids: tuple[str, ...]
    retrieved_kinds: tuple[str, ...]
    context: str
    asked_at: str


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

    Args:
        harness: The wired pipeline.
        question: The question to answer.

    Returns:
        The attempt.
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
        reply = await harness.model.complete(
            [
                Message(role=Role.SYSTEM, content=ANSWER_SYSTEM_PROMPT),
                Message(
                    role=Role.USER,
                    content=f"Memory records:\n{context}\n\nQuestion: {question.question}",
                ),
            ]
        )
    return AnswerAttempt(
        correlation_id=correlation_id,
        answer=reply.content.strip(),
        retrieved_ids=tuple(record.id for record in records),
        retrieved_kinds=tuple(record.kind for record in records),
        context=context,
        asked_at=asked_at,
    )
