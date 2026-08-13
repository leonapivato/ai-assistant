"""Parse LoCoMo's published format into :mod:`benchmarks.memory.cases` types.

Three modelling choices are made here rather than downstream, and each one moves a
score, so each is stated where the code that makes it lives.

**Speaker labels are kept in the text.** LoCoMo is a conversation between two named
third parties, and this system's episode model has a user half and an assistant half.
Mapping ``speaker_a`` onto the user half and dropping the names would make "when did
Caroline go to the support group?" unanswerable from an episode that says only "I
went to a support group" — the name is evidence, not framing. So each utterance is
prefixed with its speaker. This is also the corpus's own convention: LoCoMo's
published baselines render the dialogue with speaker names.

**Photo turns become text.** ~1,200 of the ~5,900 turns carry a ``blip_caption``: the
speaker shared an image and the corpus supplies a caption for it. This harness is
text-only, so a caption-bearing turn renders as the utterance plus the caption in
brackets. Dropping the captions instead would silently make a slice of the questions
unanswerable and charge the result to retrieval.

**Session instants are read as UTC.** The corpus states wall-clock times with no zone
("1:56 pm on 8 May, 2023"). UTC is a choice, not a reading; it is consistent across
the corpus and the questions are relative ("how long after", "what happened first"),
so a uniform offset does not disturb them.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn

if TYPE_CHECKING:
    from pathlib import Path

#: How the corpus spells a session's instant, e.g. ``"1:56 pm on 8 May, 2023"``.
_DATE_FORMAT: Final = "%I:%M %p on %d %B, %Y"

#: ``session_12`` -> 12. Sessions are keys of one dict, so the numeric order has to
#: be recovered rather than trusted to insertion order.
_SESSION_KEY: Final = re.compile(r"^session_(\d+)$")

#: The category whose questions have no answer in the conversation. All 446 of them
#: carry an ``adversarial_answer``; this is #1029's P7 population, and it is 22% of
#: the corpus rather than the handful that phrasing might suggest.
ADVERSARIAL_CATEGORY: Final = 5


class LocomoFormatError(ValueError):
    """The file did not have the shape this loader was written against."""


def load(path: Path) -> tuple[BenchCase, ...]:
    """Read ``locomo10.json`` into one case per dialogue.

    Args:
        path: The verified corpus file.

    Returns:
        Ten cases, in file order.

    Raises:
        LocomoFormatError: If the file is not a list of samples, or a sample is
            missing the keys this loader reads.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        msg = f"expected a list of samples at the top level, got {type(raw).__name__}"
        raise LocomoFormatError(msg)
    return tuple(_case(sample) for sample in raw)


def _case(sample: Any) -> BenchCase:
    """Build one case from one LoCoMo sample.

    Args:
        sample: One element of the top-level list.

    Returns:
        The case.

    Raises:
        LocomoFormatError: If a key this loader reads is missing or the wrong type.
    """
    if not isinstance(sample, dict):
        msg = f"expected each sample to be an object, got {type(sample).__name__}"
        raise LocomoFormatError(msg)
    case_key = _string(sample, "sample_id")
    conversation = sample.get("conversation")
    if not isinstance(conversation, dict):
        msg = f"{case_key}: 'conversation' is not an object"
        raise LocomoFormatError(msg)
    speaker_a = _string(conversation, "speaker_a")

    sessions = tuple(
        _session(conversation, ordinal, speaker_a=speaker_a, case_key=case_key)
        for ordinal in _session_ordinals(conversation)
    )
    if not sessions:
        msg = f"{case_key}: no session carried any turns"
        raise LocomoFormatError(msg)

    questions = sample.get("qa")
    if not isinstance(questions, list):
        msg = f"{case_key}: 'qa' is not a list"
        raise LocomoFormatError(msg)
    return BenchCase(
        corpus_key="locomo",
        case_key=case_key,
        sessions=sessions,
        questions=tuple(
            _question(entry, case_key=case_key, ordinal=index)
            for index, entry in enumerate(questions)
        ),
    )


def _session_ordinals(conversation: dict[str, Any]) -> list[int]:
    """The numbers of the sessions that actually carry turns, in order.

    The corpus carries a ``session_N_date_time`` for sessions beyond the last one it
    has content for, so the date-time keys are not the index of what exists.

    Args:
        conversation: The sample's conversation object.

    Returns:
        Session numbers, ascending.
    """
    found: list[int] = []
    for key, value in conversation.items():
        match = _SESSION_KEY.match(key)
        if match is not None and isinstance(value, list):
            found.append(int(match.group(1)))
    return sorted(found)


def _session(
    conversation: dict[str, Any], ordinal: int, *, speaker_a: str, case_key: str
) -> BenchSession:
    """Build one session.

    Args:
        conversation: The sample's conversation object.
        ordinal: Which session.
        speaker_a: The speaker whose turns take the user half of an exchange.
        case_key: For error messages.

    Returns:
        The session.

    Raises:
        LocomoFormatError: If the session has no instant, or its instant does not
            parse.
    """
    key = f"session_{ordinal}"
    stamp = conversation.get(f"{key}_date_time")
    if not isinstance(stamp, str):
        msg = f"{case_key}: {key} has no '{key}_date_time'"
        raise LocomoFormatError(msg)
    try:
        occurred_at = datetime.strptime(stamp, _DATE_FORMAT).replace(tzinfo=UTC)
    except ValueError as exc:
        msg = f"{case_key}: {key} has an unreadable instant {stamp!r}: {exc}"
        raise LocomoFormatError(msg) from exc

    turns = tuple(
        _turn(entry, speaker_a=speaker_a, case_key=case_key, key=key) for entry in conversation[key]
    )
    return BenchSession(session_key=key, occurred_at=occurred_at, turns=turns)


def _turn(entry: Any, *, speaker_a: str, case_key: str, key: str) -> BenchTurn:
    """Build one utterance, rendering a shared photo as text.

    **``dia_id`` is kept, and it is the same id space the questions cite.** A qa
    entry's ``evidence`` is a list of ``dia_id`` values (``["D1:1"]``), so carrying
    each turn's own ``dia_id`` onto the turn is what lets ingestion record which
    captured episode a cited turn became — #1074's join, and the one point in a run
    where both halves of it are in hand.

    It is read leniently: a turn without one takes ``None`` rather than failing the
    load. Nothing this harness *runs* reads the key — a missing pointer costs that
    turn its place in the join and nothing else — so refusing the file over it would
    turn an analysis field into a parsing precondition.

    Args:
        entry: One element of a session's list.
        speaker_a: The speaker whose turns take the user half.
        case_key: For error messages.
        key: For error messages.

    Returns:
        The turn.

    Raises:
        LocomoFormatError: If the entry lacks a speaker or text.
    """
    if not isinstance(entry, dict):
        msg = f"{case_key}/{key}: expected each turn to be an object"
        raise LocomoFormatError(msg)
    speaker = _string(entry, "speaker")
    said = _string(entry, "text")
    caption = entry.get("blip_caption")
    if isinstance(caption, str) and caption.strip():
        said = f"{said} [shared a photo: {caption.strip()}]"
    dia_id = entry.get("dia_id")
    return BenchTurn(
        speaker=speaker,
        text=f"{speaker}: {said}",
        user_side=speaker == speaker_a,
        evidence_key=dia_id if isinstance(dia_id, str) and dia_id else None,
    )


def _question(entry: Any, *, case_key: str, ordinal: int) -> BenchQuestion:
    """Build one graded question.

    LoCoMo gives no per-question id, so one is derived from the sample and the
    question's position — stable across runs because the file is pinned.

    Args:
        entry: One element of ``qa``.
        case_key: The sample this question belongs to.
        ordinal: The question's position in ``qa``.

    Returns:
        The question.

    Raises:
        LocomoFormatError: If the entry has no question text, or no answer of either
            kind.
    """
    if not isinstance(entry, dict):
        msg = f"{case_key}: expected each qa entry to be an object"
        raise LocomoFormatError(msg)
    category = entry.get("category")
    if not isinstance(category, int):
        msg = f"{case_key}#{ordinal}: 'category' is not an integer"
        raise LocomoFormatError(msg)

    # `answer` is absent on 444 of the 446 adversarial questions and present on two
    # of them; `adversarial_answer` is the gold for the category either way, which is
    # how LoCoMo's own evaluation reads it. Preferring it *for that category* rather
    # than preferring whichever key exists is what keeps those two questions graded
    # like their 444 siblings instead of like answerable ones.
    unanswerable = category == ADVERSARIAL_CATEGORY
    gold = entry.get("adversarial_answer") if unanswerable else entry.get("answer")
    if gold is None:
        gold = entry.get("answer") if unanswerable else entry.get("adversarial_answer")
    if gold is None:
        msg = f"{case_key}#{ordinal}: neither 'answer' nor 'adversarial_answer' is present"
        raise LocomoFormatError(msg)

    evidence = entry.get("evidence")
    return BenchQuestion(
        question_id=f"{case_key}#{ordinal}",
        category=str(category),
        question=_string(entry, "question"),
        # Six answers are integers in the corpus (counts and bare years); `str` is
        # applied here rather than at grading time so everything downstream sees one
        # type.
        answer=str(gold),
        unanswerable=unanswerable,
        evidence=tuple(str(item) for item in evidence) if isinstance(evidence, list) else (),
    )


def _string(source: dict[str, Any], key: str) -> str:
    """Read a required string.

    Args:
        source: The object to read from.
        key: The key to read.

    Returns:
        The value.

    Raises:
        LocomoFormatError: If the key is absent or is not a string.
    """
    value = source.get(key)
    if not isinstance(value, str):
        msg = f"expected a string at {key!r}, got {type(value).__name__}"
        raise LocomoFormatError(msg)
    return value
