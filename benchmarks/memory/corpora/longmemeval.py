"""Parse LongMemEval's published format into :mod:`benchmarks.memory.cases` types.

**Every question carries its own haystack, so every question is its own case** — and
therefore its own store, its own ingestion and its own cost. That is the fact to hold
on to when sizing a run: fifty questions is fifty ingestions, not one. The loader
makes it structural rather than something a caller has to remember.

**Sessions are ordered by their stated date**, not by their position in the file. The
corpus lists a question's sessions in an order that does not track time — the sample
question's answering sessions arrive 17:50, 14:47, 17:15 — and ingesting them in file
order would present a system whose whole subject is time with a scrambled history.

**Speaker labels are not added**, unlike LoCoMo's loader. Here the two sides genuinely
*are* a user and an assistant, so they map onto the episode's two halves directly and
a name prefix would be invented framing rather than preserved evidence.

The 278 MiB ``longmemeval_s_cleaned.json`` is parsed whole; there is no streaming
parser in the dependency set and adding one for this would be a runtime dependency
bought for a development tool. :func:`write_slice` exists so that cost is paid once:
it materialises a stratified subset that later runs read instead.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

#: How the corpus spells an instant, e.g. ``"2023/04/10 (Mon) 23:07"``.
_DATE_FORMAT: Final = "%Y/%m/%d (%a) %H:%M"

#: The suffix marking an abstention variant — the same question against a haystack
#: that does not answer it (#1029's P7).
ABSTENTION_SUFFIX: Final = "_abs"


class LongMemEvalFormatError(ValueError):
    """The file did not have the shape this loader was written against."""


def load(path: Path, *, corpus_key: str) -> tuple[BenchCase, ...]:
    """Read a LongMemEval split into one case per question.

    **``corpus_key`` has no default, and that is the point.** Two corpora are parsed by
    this one loader — ``longmemeval`` and the upstream-deprecated
    ``longmemeval-original`` — and they are different corpora that do not produce the
    same scores. A case carries its corpus into every ``QuestionRecord``, so a defaulted
    key is how a run of one variant comes to write records labelled as the other while
    its manifest names the variant correctly. Provenance is passed in, never assumed.

    Args:
        path: The verified corpus file.
        corpus_key: The key of the corpus ``path`` belongs to, as
            :mod:`~benchmarks.memory.corpora.provenance` names it.

    Returns:
        One case per question, in file order.

    Raises:
        LongMemEvalFormatError: If the file is not a list, or an entry is missing the
            keys this loader reads.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        msg = f"expected a list of questions at the top level, got {type(raw).__name__}"
        raise LongMemEvalFormatError(msg)
    return tuple(_case(entry, corpus_key=corpus_key) for entry in raw)


def stratified(cases: Sequence[BenchCase], *, total: int, seed: int) -> tuple[BenchCase, ...]:
    """Take ``total`` cases spread as evenly as possible across question types.

    #1029 asks for "~50 questions, stratified evenly across the six categories". Even
    is what this aims at and not always what it reaches: where a category holds fewer
    than its share, the shortfall is redistributed over the categories that can cover
    it, in category-name order, so the total is met rather than silently missed.

    Args:
        cases: The cases to draw from.
        total: How many to return. A ``total`` at or above ``len(cases)`` returns all
            of them, sorted, rather than raising.
        seed: Seeds the draw within each category. A pre-registered slice has to be
            reproducible, so which questions were drawn is a function of this number
            and the pinned corpus and nothing else.

    Returns:
        The selected cases, ordered by question id so a run's order is stable.

    Raises:
        ValueError: If ``total`` is negative. Refused rather than treated as zero,
            because the loop below would otherwise never run and return no cases at
            all — a run that completes, writes a manifest and reports success having
            asked nothing. ``first_questions``, this corpus's counterpart on the
            LoCoMo path, refuses the same value.
    """
    if total < 0:
        msg = f"a question total cannot be negative, got {total}"
        raise ValueError(msg)
    by_category: dict[str, list[BenchCase]] = defaultdict(list)
    for case in cases:
        by_category[case.questions[0].category].append(case)

    rng = random.Random(seed)  # noqa: S311 — sampling a benchmark slice, not a security decision
    pools = {
        name: rng.sample(members, len(members)) for name, members in sorted(by_category.items())
    }
    picked: list[BenchCase] = []
    # Round-robin rather than a computed share, which is what makes the redistribution
    # fall out instead of being a second code path: a drained category simply stops
    # contributing and the remaining ones keep taking turns until the total is met.
    while len(picked) < total and any(pools.values()):
        for pool in pools.values():
            if not pool:
                continue
            picked.append(pool.pop())
            if len(picked) == total:
                break
    return tuple(sorted(picked, key=lambda case: case.case_key))


def write_slice(cases: Sequence[BenchCase], path: Path) -> None:
    """Write cases out in this harness's own shape, for reuse without a reparse.

    Args:
        cases: The cases to write.
        path: Where to write. Parent directories are created.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [case.model_dump(mode="json") for case in cases]
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def read_slice(path: Path) -> tuple[BenchCase, ...]:
    """Read back what :func:`write_slice` wrote.

    Args:
        path: The slice file.

    Returns:
        The cases.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(BenchCase.model_validate(entry) for entry in raw)


def _case(entry: Any, *, corpus_key: str) -> BenchCase:
    """Build one case from one LongMemEval question.

    Args:
        entry: One element of the top-level list.
        corpus_key: The corpus the entry came from, carried onto the case.

    Returns:
        The case.

    Raises:
        LongMemEvalFormatError: If a key this loader reads is missing or misshapen.
    """
    if not isinstance(entry, dict):
        msg = f"expected each question to be an object, got {type(entry).__name__}"
        raise LongMemEvalFormatError(msg)
    question_id = _string(entry, "question_id")
    sessions = entry.get("haystack_sessions")
    dates = entry.get("haystack_dates")
    ids = entry.get("haystack_session_ids")
    if not (isinstance(sessions, list) and isinstance(dates, list) and isinstance(ids, list)):
        msg = f"{question_id}: haystack sessions, dates and ids must all be lists"
        raise LongMemEvalFormatError(msg)
    if not len(sessions) == len(dates) == len(ids):
        msg = (
            f"{question_id}: {len(sessions)} sessions, {len(dates)} dates and "
            f"{len(ids)} ids do not correspond"
        )
        raise LongMemEvalFormatError(msg)

    built = [
        BenchSession(
            session_key=str(session_id),
            occurred_at=_instant(stamp, question_id=question_id),
            turns=tuple(_turn(turn, question_id=question_id) for turn in session),
        )
        for session, stamp, session_id in zip(sessions, dates, ids, strict=True)
    ]
    return BenchCase(
        corpus_key=corpus_key,
        case_key=question_id,
        sessions=tuple(sorted(built, key=lambda session: session.occurred_at)),
        questions=(_question(entry, question_id=question_id),),
    )


def _question(entry: dict[str, Any], *, question_id: str) -> BenchQuestion:
    """Build the one graded question a case carries.

    Args:
        entry: The question object.
        question_id: Its id.

    Returns:
        The question.

    Raises:
        LongMemEvalFormatError: If the answer or type is missing.
    """
    answer = entry.get("answer")
    if answer is None:
        msg = f"{question_id}: no 'answer'"
        raise LongMemEvalFormatError(msg)
    evidence = entry.get("answer_session_ids")
    asked = entry.get("question_date")
    return BenchQuestion(
        question_id=question_id,
        category=_string(entry, "question_type"),
        question=_string(entry, "question"),
        # 32 of the 500 oracle answers are integers; `str` here so everything
        # downstream sees one type.
        answer=str(answer),
        unanswerable=question_id.endswith(ABSTENTION_SUFFIX),
        evidence=tuple(str(item) for item in evidence) if isinstance(evidence, list) else (),
        asked_at=_instant(asked, question_id=question_id) if isinstance(asked, str) else None,
    )


def _turn(entry: Any, *, question_id: str) -> BenchTurn:
    """Build one utterance.

    Args:
        entry: One element of a session's list.
        question_id: For error messages.

    Returns:
        The turn.

    Raises:
        LongMemEvalFormatError: If the entry lacks a role or content.
    """
    if not isinstance(entry, dict):
        msg = f"{question_id}: expected each turn to be an object"
        raise LongMemEvalFormatError(msg)
    role = _string(entry, "role")
    return BenchTurn(speaker=role, text=_string(entry, "content"), user_side=role == "user")


def _instant(stamp: object, *, question_id: str) -> datetime:
    """Parse one of the corpus's instants as UTC.

    Args:
        stamp: The corpus's string.
        question_id: For error messages.

    Returns:
        A timezone-aware instant.

    Raises:
        LongMemEvalFormatError: If it is not a string, or does not parse.
    """
    if not isinstance(stamp, str):
        msg = f"{question_id}: expected an instant string, got {type(stamp).__name__}"
        raise LongMemEvalFormatError(msg)
    try:
        return datetime.strptime(stamp, _DATE_FORMAT).replace(tzinfo=UTC)
    except ValueError as exc:
        msg = f"{question_id}: unreadable instant {stamp!r}: {exc}"
        raise LongMemEvalFormatError(msg) from exc


def _string(source: dict[str, Any], key: str) -> str:
    """Read a required string.

    Args:
        source: The object to read from.
        key: The key to read.

    Returns:
        The value.

    Raises:
        LongMemEvalFormatError: If the key is absent or is not a string.
    """
    value = source.get(key)
    if not isinstance(value, str):
        msg = f"expected a string at {key!r}, got {type(value).__name__}"
        raise LongMemEvalFormatError(msg)
    return value
