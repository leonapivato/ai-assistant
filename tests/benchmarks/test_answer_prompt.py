"""What the answering instruction must say, and what it must not.

A prompt is text, and a test over text can only pin the properties the experiment
depends on. These do, and each one is here because something measurable broke or would
break without it (#1029's results comment, and the freeze-relevant follow-up beneath
it, which measured 1,309 of LoCoMo's 1,320 declines on *answerable* questions as one
literal the prompt asked for).

The first group is the pilot-1→2 threshold recalibration:

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

The second group is the pilot-4→5 recalibration (#1210), which leaves that threshold
alone and adds what to *do* with records that already clear it — each clause named by
an error population the pilot-4 anatomy counted:

* **Partial support is support.** 123 LoCoMo questions were declined with the gold
  evidence in the prompt.
* **Aggregate across records.** LongMemEval counts came back off one session when the
  occasions were spread over several.
* **Do the date arithmetic — but claim no rendered field.** Temporal questions were
  abstained on with the dates retrievable; the clause has to hold both before and
  after #1194 renders an episode's ``occurred_at``, so it must not name that field,
  and it must not promise a present moment the prompt does not carry (#1211).
* **The later record wins.** Knowledge-update questions came back with the value the
  records themselves supersede.
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


def test_the_prompt_states_that_partial_support_is_still_support() -> None:
    """123 LoCoMo declines had the gold evidence in the prompt (#1029, pilot-4).

    The threshold above already says "nothing to answer from"; what the anatomy found
    is that a model reads records carrying *part* of what was asked as carrying
    nothing, so the case is stated rather than left to the threshold to imply.
    """
    assert "Partial support is still support" in ANSWER_SYSTEM_PROMPT
    assert "instead of declining because the rest is missing" in ANSWER_SYSTEM_PROMPT


def test_the_prompt_asks_for_aggregation_across_records() -> None:
    """LongMemEval's counts were answered off a single session.

    The occasions a "how many times" question asks about are spread across sessions by
    construction in both corpora, so answering from the best-matching record alone is
    wrong by default rather than occasionally.
    """
    assert "how many, how often, or for a list" in ANSWER_SYSTEM_PROMPT
    assert "gather the answer across all of the records together" in ANSWER_SYSTEM_PROMPT
    assert "Read every record before you answer" in ANSWER_SYSTEM_PROMPT


def test_the_prompt_asks_for_date_arithmetic() -> None:
    """Temporal questions were abstained on with the dates retrievable."""
    assert "Where the records carry dates or times" in ANSWER_SYSTEM_PROMPT
    assert "compute the interval or the elapsed time the question asks for" in (
        ANSWER_SYSTEM_PROMPT
    )
    assert "give an absolute date where the question asks when something happened" in (
        ANSWER_SYSTEM_PROMPT
    )


def test_the_date_clause_falls_back_to_what_the_records_do_fix() -> None:
    """The added clause must not become a new licence to decline.

    Pilot-1's lesson is that a clause naming a condition for *not* answering is read
    generously, so the date clause names what to answer with instead of naming a
    decline: where no absolute date is fixed, the ordering or the gap is still an
    answer the records support.
    """
    assert "Where nothing shown fixes an absolute date" in ANSWER_SYSTEM_PROMPT
    assert "answer with what the records do fix" in ANSWER_SYSTEM_PROMPT


@pytest.mark.parametrize("rendered", ["occurred_at", "timestamp", "the date on each record"])
def test_the_date_clause_names_no_field_the_prompt_may_not_carry(rendered: str) -> None:
    """It has to hold on both sides of #1194, so it is conditioned, not asserted.

    ``_render_record`` mirrors the product's bullet, which drops ``occurred_at``; a
    clause telling the model to read a field the block does not carry is drift the
    harness cannot detect from its own artifacts, since the prompt and the rendering
    are both recorded and neither is compared against the other.
    """
    assert rendered not in ANSWER_SYSTEM_PROMPT


def test_the_prompt_prefers_the_later_of_two_conflicting_records() -> None:
    """Knowledge-update questions returned the superseded value.

    Judged by "whatever the records themselves show" rather than by prompt order,
    because the block is ordered by the retrieval composition (ADR-0072 §5), not by
    time — reading position as recency would be a different instruction that happened
    to score.
    """
    assert "Where two records disagree about something that can change" in ANSWER_SYSTEM_PROMPT
    assert "answer from the later one" in ANSWER_SYSTEM_PROMPT
    assert "treat the earlier as superseded" in ANSWER_SYSTEM_PROMPT


def test_the_recalibration_did_not_move_the_threshold() -> None:
    """The pilot-4 clauses are additive: the decline's condition is untouched.

    Stated as its own test because it is the property the whole change is claimed
    under — an arm that also moved the threshold would not be measuring what #1029
    pre-registers it as measuring, and every unanswerable question's graded behaviour
    rides on this literal.
    """
    assert "Where the records give you nothing to answer from, reply exactly: " in (
        ANSWER_SYSTEM_PROMPT
    )
    assert "being on the topic is not the same as supporting an answer" in ANSWER_SYSTEM_PROMPT
    assert "always answer" not in ANSWER_SYSTEM_PROMPT
    assert "never reply" not in ANSWER_SYSTEM_PROMPT
