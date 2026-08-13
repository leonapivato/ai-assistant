"""Narrowing a corpus down to the cases a run will actually work on.

Two levers, and they are not the same lever. One bounds **how many questions** are
asked; the other bounds **how much conversation** is ingested before they are asked.
Keeping them apart matters because they have opposite relationships to validity: a
smaller question set is a smaller sample of the same experiment, while a shortened
history is a *different* memory and therefore a different experiment.

They live here rather than in the command line so they can be tested without a
fetched corpus and without a terminal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from benchmarks.memory.cases import BenchCase

__all__ = ["first_questions", "first_sessions"]


def first_questions(cases: Sequence[BenchCase], limit: int) -> tuple[BenchCase, ...]:
    """Take the first ``limit`` questions, from as few cases as they fit in.

    **On LoCoMo a question limit is really a case limit**, and that is the point: each
    of its ten dialogues carries ~199 questions, so asking for five questions should
    ingest one dialogue rather than all ten. Truncating each case's question list, and
    stopping once the budget is met, is what makes that true.

    Args:
        cases: The corpus's cases, in order.
        limit: How many questions to keep; ``0`` keeps all.

    Returns:
        Cases whose question lists sum to ``limit`` — or all of them, where the corpus
        holds fewer questions than that.
    """
    if not limit:
        return tuple(cases)
    taken: list[BenchCase] = []
    remaining = limit
    for case in cases:
        if remaining <= 0:
            break
        questions = case.questions[:remaining]
        remaining -= len(questions)
        taken.append(case.model_copy(update={"questions": questions}))
    return tuple(taken)


def first_sessions(cases: Sequence[BenchCase], limit: int) -> tuple[BenchCase, ...]:
    """Keep each case's first ``limit`` sessions.

    **A plumbing lever, never a measurement one.** A shortened history is a different
    memory, so a run using this answers questions about a conversation that did not
    happen — fine for proving the wires carry an answer, and not a score. It exists
    because a full LoCoMo dialogue is ~340 turns and ~18 observation passes, where two
    sessions is one pass: the difference between a live smoke run costing cents and
    costing dollars.

    A case is never emptied: :class:`~benchmarks.memory.cases.BenchCase` requires at
    least one session, and a zero-session case would be a conversation with no history
    at all, which is not a shorter version of the experiment.

    Args:
        cases: The cases to shorten.
        limit: How many sessions to keep; ``0`` keeps all.

    Returns:
        The cases, shortened.

    Raises:
        ValueError: If ``limit`` is negative.
    """
    if limit < 0:
        msg = f"a session limit cannot be negative, got {limit}"
        raise ValueError(msg)
    if not limit:
        return tuple(cases)
    return tuple(case.model_copy(update={"sessions": case.sessions[:limit]}) for case in cases)
