"""Judge an answer against the corpus's reference answer.

Two graders, and the reason for two is that they answer different questions.

:class:`ExactGrader` makes **no model call at all**. It is what the harness's own
tests run against and what a smoke run uses by default, because a smoke run exists to
prove the plumbing carries an answer end to end and reading its scores is exactly what
#1029's ground rule 1 forbids. It is a poor grader on purpose: a short-answer
benchmark is full of "7 May 2023" against "May 7th, 2023", and a string comparison
calls that wrong.

:class:`ModelGrader` is the grader a scored run would use, because it is what both
benchmarks' published protocols use — LoCoMo and LongMemEval both grade with an
LLM judge, so a score computed any other way is not comparable to the published
numbers this pilot is positioned against.

**Abstention is judged before equivalence, by both graders and by the same rule.**
Whether an answer abstained is a property of the answer's text, and whether abstaining
was right is a property of the question; keeping the two apart is what lets #1029's P7
be measured on the answerable questions as well — an over-answering system is visible
in how rarely it abstains where it should, and a *timid* one in how often it abstains
where it should not. Folding abstention into the judge's verdict would lose both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import Message, Role

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ModelProvider
    from benchmarks.memory.cases import BenchQuestion

__all__ = ["ExactGrader", "Grader", "Grading", "ModelGrader", "Verdict", "is_abstention"]


class Verdict(StrEnum):
    """Whether the answer was right.

    ``UNGRADED`` exists because a judge can fail — a model error, an unparseable
    reply — and a run that recorded that as ``INCORRECT`` would charge a judge
    outage to the system under test. It also covers the answer that never existed,
    where the *answering* seam failed. It is excluded from the denominator, and a run
    with many of them is a run to repeat rather than report.
    """

    CORRECT = "correct"
    INCORRECT = "incorrect"
    UNGRADED = "ungraded"


@dataclass(frozen=True, slots=True)
class Grading:
    """One judged answer.

    Attributes:
        verdict: Whether it was right.
        abstained: Whether the answer declined to answer.
        judge: What judged it — ``"exact"``, or the judge model's route.
        detail: The judge's own words, where it produced any. Free text, and the one
            field in the harness's records that is not a number or an identifier.
    """

    verdict: Verdict
    abstained: bool
    judge: str
    detail: str | None = None


#: Phrasings that count as declining to answer.
#:
#: Anchored at the start, because an answer that *contains* "I don't know" partway
#: through — "The car was red; I don't know what happened to it" — has answered. The
#: system prompt asks for the exact phrase, so this list is a tolerance for models
#: that will not follow it precisely rather than an open-ended intent classifier;
#: anything looser would start deciding, silently, which answers count as abstentions
#: and that is the measurement P7 is about.
_ABSTENTION: Final = re.compile(
    r"^\W*(i\s+don'?t\s+know"
    r"|i\s+do\s+not\s+know"
    r"|no\s+information"
    r"|not\s+enough\s+information"
    r"|insufficient\s+information"
    r"|the\s+(memory\s+)?records\s+do\s+not"
    r"|there\s+is\s+no\s+information"
    r"|unknown)\b",
    re.IGNORECASE,
)


def is_abstention(answer: str) -> bool:
    """Whether an answer declined to answer.

    Args:
        answer: What the model said.

    Returns:
        ``True`` if it opens with one of the declining phrasings, or is blank.
    """
    return not answer.strip() or _ABSTENTION.match(answer) is not None


class Grader(Protocol):
    """Judges an answer against a question's reference answer."""

    @property
    def name(self) -> str:
        """What to record as the judge in a per-question record."""
        ...

    async def grade(self, question: BenchQuestion, answer: str) -> Grading:
        """Judge one answer.

        Args:
            question: The question, carrying the reference answer and whether
                abstaining is the right behaviour.
            answer: What the system said.

        Returns:
            The grading.
        """
        ...


class ExactGrader:
    """A deterministic grader that makes no model call.

    Correct means the reference answer appears in the given answer, case- and
    whitespace-insensitively, or the two are equal after the same normalisation.
    Containment rather than equality because the system prompt asks for a bare
    answer and models supply one wrapped in a sentence anyway.
    """

    @property
    def name(self) -> str:
        """The judge label recorded for this grader."""
        return "exact"

    async def grade(self, question: BenchQuestion, answer: str) -> Grading:
        """Judge by normalised containment.

        Args:
            question: The question.
            answer: What the system said.

        Returns:
            The grading.
        """
        abstained = is_abstention(answer)
        if question.unanswerable:
            return Grading(
                verdict=Verdict.CORRECT if abstained else Verdict.INCORRECT,
                abstained=abstained,
                judge=self.name,
            )
        if abstained:
            return Grading(verdict=Verdict.INCORRECT, abstained=True, judge=self.name)
        reference = _normalised(question.answer)
        correct = bool(reference) and reference in _normalised(answer)
        return Grading(
            verdict=Verdict.CORRECT if correct else Verdict.INCORRECT,
            abstained=False,
            judge=self.name,
        )


#: What the judge model is told. Short, and deliberately not given the retrieved
#: context: the judge decides whether the answer matches the reference, which is a
#: question about two strings. Showing it the evidence would let it re-derive the
#: answer and grade its own reading instead of the system's output.
JUDGE_PROMPT: Final = (
    "You are grading a short answer against a reference answer. "
    "Reply with exactly one word, CORRECT or INCORRECT, and nothing else. "
    "CORRECT means the answer conveys the same fact as the reference, allowing for "
    "different wording, formatting, date format, or extra surrounding words. "
    "INCORRECT means it states something different, is missing the fact, or declines "
    "to answer."
)


class ModelGrader:
    """The LLM judge both benchmarks' published protocols use.

    Attributes are not public; the judge's route is reported through :attr:`name`.
    """

    def __init__(self, model: ModelProvider, *, route: str) -> None:
        """Wire the judge to a model seam.

        Args:
            model: The seam to judge through. Golden rule 4 reaches this harness
                too — this is a ``ModelProvider`` and never a provider SDK.
            route: The ``"provider:model"`` spec, recorded on every grading so a
                run's judge is identifiable from its artifacts alone.
        """
        self._model = model
        self._route = route

    @property
    def name(self) -> str:
        """The judge label recorded for this grader."""
        return f"model:{self._route}"

    async def grade(self, question: BenchQuestion, answer: str) -> Grading:
        """Judge one answer, abstention first.

        An abstention is decided without a model call in both directions: on an
        unanswerable question it is the correct behaviour, and on an answerable one
        it is a failure to answer, and neither is a judgement about wording.

        Args:
            question: The question.
            answer: What the system said.

        Returns:
            The grading. ``UNGRADED`` where the judge failed or replied with
            something other than the two words it was asked for — recorded rather
            than guessed, because a judge that cannot be parsed has not graded.
        """
        abstained = is_abstention(answer)
        if question.unanswerable:
            return Grading(
                verdict=Verdict.CORRECT if abstained else Verdict.INCORRECT,
                abstained=abstained,
                judge=self.name,
                detail="abstention expected",
            )
        if abstained:
            return Grading(
                verdict=Verdict.INCORRECT,
                abstained=True,
                judge=self.name,
                detail="declined to answer an answerable question",
            )
        try:
            reply = await self._model.complete(
                [
                    Message(role=Role.SYSTEM, content=JUDGE_PROMPT),
                    Message(
                        role=Role.USER,
                        content=(
                            f"Question: {question.question}\n"
                            f"Reference answer: {question.answer}\n"
                            f"Answer to grade: {answer}"
                        ),
                    ),
                ]
            )
        except ModelError as error:
            # A judge outage is not evidence about the system under test, and a run of
            # ~2,000 paid questions must not die on one. The class name is recorded and
            # never the message: a provider's error text is untrusted content and this
            # is the one free-text field in the records.
            return Grading(
                verdict=Verdict.UNGRADED,
                abstained=False,
                judge=self.name,
                detail=f"judge failed: {type(error).__name__}",
            )
        said = reply.content.strip().upper()
        if said.startswith("CORRECT"):
            return Grading(verdict=Verdict.CORRECT, abstained=False, judge=self.name)
        if said.startswith("INCORRECT"):
            return Grading(verdict=Verdict.INCORRECT, abstained=False, judge=self.name)
        return Grading(
            verdict=Verdict.UNGRADED,
            abstained=False,
            judge=self.name,
            detail=f"unparseable judge reply: {reply.content[:200]!r}",
        )


def _normalised(text: str) -> str:
    """Lowercase, with runs of non-alphanumerics collapsed to single spaces.

    Args:
        text: The text to normalise.

    Returns:
        The normalised form, stripped.
    """
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
