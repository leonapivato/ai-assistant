"""What the answering instruction must say, and what it must not.

A prompt is text, and a test over text can only pin the properties the experiment
depends on. Four do, and each one is here because something measurable broke or would
break without it (#1029's results comment, and the freeze-relevant follow-up beneath
it, which measured 1,309 of LoCoMo's 1,320 declines on *answerable* questions as one
literal the prompt asked for).

* **Best effort, not conservatism.** The prompt must ask for an answer where the
  records plausibly support one. The pilot's headline over-abstention was this clause
  inverted.
* **Abstention survives, mechanically.** The phrase the prompt sanctions has to be one
  ``is_abstention`` detects, or P7's measure — LoCoMo category 5, LongMemEval's
  ``_abs`` variants — stops being computable from a run's records. This is the test
  that fails if either side of that pair is edited alone.
* **The decline hinges on support, not relevance.** Those same unanswerable questions
  are ones whose subject *was* discussed and whose fact is absent, so a decline
  conditioned on relevance would not fire on the population it exists for.
* **No hedged preamble.** ``is_abstention`` is anchored at the start of the answer, so
  an answer prefaced with a caveat is scored as a decline however well it answered.
* **Records only.** The ban on general knowledge is the experiment itself and is not
  what changed.
"""

from __future__ import annotations

import re

import pytest
from benchmarks.memory.answer import ABSTENTION_PHRASE, ANSWER_SYSTEM_PROMPT
from benchmarks.memory.cases import BenchQuestion
from benchmarks.memory.grade import ExactGrader, Verdict, is_abstention

UNANSWERABLE = BenchQuestion(
    question_id="q1",
    category="5",
    question="Did Ada adopt a cat?",
    answer="No such information",
    unanswerable=True,
)


def test_the_prompt_sanctions_a_phrase_the_grader_detects() -> None:
    """The one hard tie between the instruction and the measure.

    Both halves are asserted so that editing either alone fails: the phrase has to
    appear in the prompt the model actually reads, and it has to be an abstention as
    far as the grader is concerned.
    """
    assert ABSTENTION_PHRASE in ANSWER_SYSTEM_PROMPT
    assert is_abstention(ABSTENTION_PHRASE) is True


async def test_the_sanctioned_phrase_still_scores_an_unanswerable_question_correct() -> None:
    """P7's measure end to end: the instructed decline, on the population it is for."""
    grading = await ExactGrader().grade(UNANSWERABLE, f"{ABSTENTION_PHRASE}.")

    assert grading.abstained is True
    assert grading.verdict is Verdict.CORRECT


def test_the_prompt_asks_for_an_answer_where_the_records_plausibly_support_one() -> None:
    """The behavioural change: uncertainty is no longer grounds to decline."""
    assert re.search(
        r"best answer whenever the records plausibly support one", ANSWER_SYSTEM_PROMPT
    )
    assert "when you are not certain" in ANSWER_SYSTEM_PROMPT


def test_the_prompt_conditions_the_decline_on_support_rather_than_relevance() -> None:
    """The threshold moved from "any uncertainty" to "nothing to answer from"."""
    assert "Where the records give you nothing to answer from" in ANSWER_SYSTEM_PROMPT
    assert "nothing relevant" not in ANSWER_SYSTEM_PROMPT


def test_the_prompt_names_the_relevant_but_unsupporting_case_as_a_decline() -> None:
    """The whole unanswerable population has this shape, so it is not left to inference.

    A category-5 or ``_abs`` question is unanswerable because the fact is absent, not
    because the subject was never discussed — and retrieval, searching with the
    question's own text, returns records about that subject anyway. A decline
    conditioned on relevance would therefore almost never fire on the questions it
    exists for, which is why the prompt states this case rather than implying it.
    """
    assert "discuss the subject of the question but do not contain the fact" in (
        ANSWER_SYSTEM_PROMPT
    )
    assert "being on the topic is not the same as supporting an answer" in ANSWER_SYSTEM_PROMPT


@pytest.mark.parametrize("banned", ["do not guess", "not contain enough information"])
def test_the_prompt_does_not_carry_the_clauses_that_manufactured_the_abstention(
    banned: str,
) -> None:
    """Named literally, because these are the two the pilot measured the cost of."""
    assert banned not in ANSWER_SYSTEM_PROMPT


def test_the_prompt_forbids_a_hedged_opening() -> None:
    """A hedged opening is read as a decline by a start-anchored detector.

    The second assertion is the failure these clauses exist to prevent, stated as a fact
    about the grader rather than as a claim about the prompt: a best-effort answer that
    opens with a caveat is recorded as an abstention even though it answered. The prompt
    is an instruction and not an enforcement, so that residual is real; #1168 holds the
    question of whether the detector should read past a caveat, deliberately open
    because narrowing it would redefine the measure rather than fix a defect.
    """
    assert "no statement of how confident you are" in ANSWER_SYSTEM_PROMPT
    assert "no opening caveat about the records" in ANSWER_SYSTEM_PROMPT
    assert is_abstention("The records do not clearly say, but Ada adopted a dog.") is True


def test_the_prompt_still_confines_the_model_to_the_retrieved_records() -> None:
    """Unchanged, and the reason the harness exists — asserted so it stays that way."""
    assert "Answer from those records alone" in ANSWER_SYSTEM_PROMPT
    assert "do not use general knowledge" in ANSWER_SYSTEM_PROMPT
