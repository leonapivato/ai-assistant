"""Grading: abstention detection, the offline grader, and the LLM judge.

The judge is exercised against `FakeModelProvider`, so no test here makes a live model
call — which is both the project's rule and #1029's, since a graded answer from a live
model is a scored measurement whatever it is called.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from benchmarks.memory.cases import BenchQuestion
from benchmarks.memory.grade import ExactGrader, ModelGrader, Verdict, is_abstention

from ai_assistant.core.errors import ModelError, ModelRateLimitError
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import Message

ANSWERABLE = BenchQuestion(
    question_id="q1", category="1", question="What did Ada adopt?", answer="a dog"
)
UNANSWERABLE = BenchQuestion(
    question_id="q2",
    category="5",
    question="Did Ada adopt a cat?",
    answer="No such information",
    unanswerable=True,
)


@pytest.mark.parametrize(
    "answer",
    [
        "I don't know.",
        "I do not know",
        "I DON'T KNOW",
        "  I don't know",
        "No information is available about that.",
        "Not enough information in the records.",
        "The memory records do not mention a cat.",
        "unknown",
        "",
        "   ",
    ],
)
def test_a_declining_answer_is_an_abstention(answer: str) -> None:
    assert is_abstention(answer) is True


@pytest.mark.parametrize(
    "answer",
    [
        "a dog",
        # Anchored: an answer that *contains* the phrase partway through has answered.
        "The car was red; I don't know what happened to it.",
        "She adopted a dog, though I don't know its name.",
        "No such information was requested, but the answer is a dog.",
    ],
)
def test_an_answer_that_answers_is_not_an_abstention(answer: str) -> None:
    assert is_abstention(answer) is False


async def test_exact_grader_accepts_a_normalised_containment() -> None:
    grading = await ExactGrader().grade(ANSWERABLE, "She adopted A DOG last spring.")

    assert grading.verdict is Verdict.CORRECT
    assert grading.judge == "exact"


async def test_exact_grader_rejects_a_different_fact() -> None:
    grading = await ExactGrader().grade(ANSWERABLE, "a cat")

    assert grading.verdict is Verdict.INCORRECT


async def test_exact_grader_counts_an_abstention_on_an_answerable_question_wrong() -> None:
    grading = await ExactGrader().grade(ANSWERABLE, "I don't know.")

    assert grading.verdict is Verdict.INCORRECT
    assert grading.abstained is True


async def test_exact_grader_counts_an_abstention_on_an_unanswerable_question_right() -> None:
    """#1029's P7 population: the graded behaviour is declining to answer."""
    grading = await ExactGrader().grade(UNANSWERABLE, "I don't know.")

    assert grading.verdict is Verdict.CORRECT
    assert grading.abstained is True


async def test_exact_grader_counts_an_answer_to_an_unanswerable_question_wrong() -> None:
    """Over-answering is exactly what P7 predicts, so it must score as a failure."""
    grading = await ExactGrader().grade(UNANSWERABLE, "Yes, a tabby.")

    assert grading.verdict is Verdict.INCORRECT
    assert grading.abstained is False


async def test_model_grader_reads_a_correct_verdict() -> None:
    model = FakeModelProvider("CORRECT")

    grading = await ModelGrader(model, route="anthropic:x").grade(ANSWERABLE, "a puppy")

    assert grading.verdict is Verdict.CORRECT
    assert grading.judge == "model:anthropic:x"


async def test_model_grader_reads_an_incorrect_verdict() -> None:
    model = FakeModelProvider("INCORRECT")

    grading = await ModelGrader(model, route="anthropic:x").grade(ANSWERABLE, "a cat")

    assert grading.verdict is Verdict.INCORRECT


async def test_model_grader_records_an_unparseable_reply_rather_than_guessing() -> None:
    """A judge that cannot be parsed has not graded, and charging that to the system
    under test would make a judge outage look like a failure."""
    model = FakeModelProvider("Well, it depends on how you read the question.")

    grading = await ModelGrader(model, route="anthropic:x").grade(ANSWERABLE, "a dog")

    assert grading.verdict is Verdict.UNGRADED
    assert grading.detail is not None
    assert "unparseable" in grading.detail


async def test_model_grader_decides_an_abstention_without_a_model_call() -> None:
    """Whether an answer declined is a property of its text, not a judgement of wording."""
    model = FakeModelProvider("CORRECT")

    grading = await ModelGrader(model, route="anthropic:x").grade(UNANSWERABLE, "I don't know")

    assert grading.verdict is Verdict.CORRECT
    assert model.calls == []


async def test_model_grader_makes_no_call_for_an_abstained_answerable_question() -> None:
    model = FakeModelProvider("CORRECT")

    grading = await ModelGrader(model, route="anthropic:x").grade(ANSWERABLE, "I don't know")

    assert grading.verdict is Verdict.INCORRECT
    assert model.calls == []


async def test_the_judge_is_not_shown_the_retrieved_context() -> None:
    """Showing it the evidence would let it re-derive the answer and grade its own
    reading rather than the system's output."""
    model = FakeModelProvider("CORRECT")

    await ModelGrader(model, route="anthropic:x").grade(ANSWERABLE, "a dog")

    sent = "\n".join(message.content for message in model.calls[0].messages)
    assert "a dog" in sent
    assert "memory record" not in sent.lower()


async def test_model_grader_records_a_judge_failure_rather_than_raising() -> None:
    """A judge outage is not evidence about the system under test, and a run of ~2,000
    paid questions must not die on one."""

    class _FailingProvider:
        async def complete(
            self, messages: Sequence[Message], *, model: str | None = None
        ) -> Message:
            raise ModelRateLimitError("slow down")

    grading = await ModelGrader(_FailingProvider(), route="anthropic:x").grade(ANSWERABLE, "a dog")

    assert grading.verdict is Verdict.UNGRADED
    assert grading.detail == "judge failed: ModelRateLimitError"


async def test_a_judge_failure_records_the_class_and_never_the_message() -> None:
    """A provider's error text is untrusted content, and `detail` is the one free-text
    field in the records."""

    class _FailingProvider:
        async def complete(
            self, messages: Sequence[Message], *, model: str | None = None
        ) -> Message:
            raise ModelError("secret internal detail")

    grading = await ModelGrader(_FailingProvider(), route="anthropic:x").grade(ANSWERABLE, "a dog")

    assert grading.detail is not None
    assert "secret internal detail" not in grading.detail
