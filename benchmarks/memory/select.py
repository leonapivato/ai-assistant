"""Narrowing a corpus down to the cases a run will actually work on.

Two levers, and they are not the same lever. One bounds **how many questions** are
asked; the other bounds **how much conversation** is ingested before they are asked.
Keeping them apart matters because they have opposite relationships to validity: a
smaller question set is a smaller sample of the same experiment, while a shortened
history is a *different* memory and therefore a different experiment.

They live here rather than in the command line so they can be tested without a
fetched corpus and without a terminal.

**What the session lever did travels with the cases it did it to.**
:func:`first_sessions` hands back a :class:`CaseSelection` rather than a bare tuple,
because the run's gate has to know whether the histories were shortened and asking the
caller was the defect #1052 records: shortening happens here and the declaration was a
separate argument to ``execute_run``, so a caller could truncate and declare nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from benchmarks.memory.cases import BenchCase

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = ["CaseSelection", "first_questions", "first_sessions"]


class CaseSelection(tuple[BenchCase, ...]):
    """The cases a run will work on, carrying the session bound actually applied.

    **A tuple subclass, because the provenance has to travel where the cases travel.**
    Every seam downstream takes a ``Sequence[BenchCase]`` and passes it along, so a
    wrapper type would have to be unwrapped at each one — and the first seam that
    unwrapped it would drop the fact the gate needs. Being a tuple, this reaches
    :func:`~benchmarks.memory.run.plan_run` through code that was never told about it,
    and :class:`~benchmarks.memory.run.RunPlan` records what it says.

    **The bound is derived from what the shortening did, not from what was asked
    for.** A limit no case ever reached shortened nothing, so it records ``0`` — the
    histories *are* whole and a manifest saying otherwise would be false in the
    direction that matters least but false all the same.

    **The trust boundary, stated rather than implied.** Nothing stops a caller
    constructing one of these around hand-truncated cases and calling it whole. What
    it removes is the *omission*: the bound is no longer a separate argument that can
    disagree with the data, and a scored run refuses a plan whose cases carry no
    selection at all (:func:`~benchmarks.memory.run.refuse_ineligible_scored_run`), so
    the false manifest has to be constructed deliberately rather than fallen into.
    """

    #: Set in ``__new__`` and read through the property below. Not a ``__slots__``
    #: entry: a variable-length tuple is already variable-size, and CPython refuses a
    #: non-empty ``__slots__`` on such a subtype.
    _max_sessions: int

    def __new__(cls, cases: Iterable[BenchCase], *, max_sessions: int) -> Self:
        """Build a selection around ``cases``.

        Args:
            cases: The cases, as the selection leaves them.
            max_sessions: The bound their histories were shortened to; ``0`` where
                they are whole. Keyword-only, so it can never be mistaken for a
                second positional sequence.

        Returns:
            The selection.

        Raises:
            ValueError: If ``max_sessions`` is negative.
        """
        if max_sessions < 0:
            msg = f"a session bound cannot be negative, got {max_sessions}"
            raise ValueError(msg)
        selection = super().__new__(cls, cases)
        selection._max_sessions = max_sessions
        return selection

    @property
    def max_sessions(self) -> int:
        """The bound these histories were shortened to; ``0`` where they are whole."""
        return self._max_sessions


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

    Raises:
        ValueError: If ``limit`` is negative. Refused rather than treated as zero,
            because the loop below would otherwise break on its first iteration and
            return no cases at all — a run that completes, writes a manifest and
            reports success having asked nothing. Its sibling below refuses the
            analogous value, and an asymmetry there is a trap.
    """
    if limit < 0:
        msg = f"a question limit cannot be negative, got {limit}"
        raise ValueError(msg)
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


def first_sessions(cases: Sequence[BenchCase], limit: int) -> CaseSelection:
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
        The cases, shortened, in a :class:`CaseSelection` recording the bound that was
        *applied* rather than the one that was asked for: a ``limit`` no case reached
        left every history whole, and the selection says ``0``. That is what the run's
        gate reads, so the difference decides whether a scored run is refused.

    Raises:
        ValueError: If ``limit`` is negative.
    """
    if limit < 0:
        msg = f"a session limit cannot be negative, got {limit}"
        raise ValueError(msg)
    if not limit:
        return CaseSelection(cases, max_sessions=0)
    kept = tuple(case.model_copy(update={"sessions": case.sessions[:limit]}) for case in cases)
    # Read off the cases themselves rather than assumed from `limit`: a case with fewer
    # sessions than the limit is returned untouched, and where that is true of every
    # case the run is over whole histories whatever was asked for.
    shortened = any(
        len(short.sessions) < len(case.sessions) for short, case in zip(kept, cases, strict=True)
    )
    return CaseSelection(kept, max_sessions=limit if shortened else 0)
