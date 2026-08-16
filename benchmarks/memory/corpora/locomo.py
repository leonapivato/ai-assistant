"""Parse LoCoMo's published format into :mod:`benchmarks.memory.cases` types.

Five modelling choices are made here rather than downstream, and each one moves a
score, so each is stated where the code that makes it lives.

**The whole dialogue is material the user supplied, and none of it is the assistant.**
LoCoMo is a conversation between two named third parties. Neither of them is this
system's user, and the assistant said none of it — so mapping ``speaker_a`` onto the
user half of an exchange and ``speaker_b`` onto the *assistant* half, as this loader
did until #1177, asserted two things the corpus does not contain, and the observer's
first-person contract (ADR-0077 §3 — beliefs about "the user ... or their world") was
being scored against them. The honest frame is the one the questions themselves
assume: **the user is the person who handed the assistant this transcript and is now
asking about it.** So every turn is the user's own side (``user_side=True``), the
session is marked :attr:`~benchmarks.memory.cases.BenchSession.user_supplied` so each
corpus turn becomes one exchange with no assistant half, and the two people in the
transcript are people in the user's *world* rather than the user. What "Caroline: I
went to a support group" then justifies is a belief about Caroline — which lands in
the belief's own sentence and not in ``about_person``, because ADR-0100 §5 forbids an
observer to state a subject at all.

**It is captured as the user's own turn: ``CAPTURE_CONFIDENCE``, and untainted.** The
user told the assistant this, in the ordinary way a user tells it anything, so the
episode carries what every captured turn carries (ADR-0074 §4) and nothing marks it as
recorded external content (ADR-0106 §1). The alternative was considered and is
deliberately *deferred*, not answered here: treating a shared transcript as external
content would make every derived belief resting on it tainted, and an unconfirmed
tainted derived belief is an ``ASK_USER`` by ADR-0106 §6 — so a headless benchmark run
would defer essentially every proposal the corpus produced and measure the harness's
own headlessness instead of the pipeline. That is a real question about what a user
pasting someone else's words means (#1162); it is not one this harness should answer
by picking whichever setting scores better.

**The frame is stated once per session, in the episode text.** Each session's opening
turn is prefixed with a single line, :data:`_FRAME`, so an observation window spanning
a session boundary is told what it is reading. It goes in the *data* and never in a
prompt under ``src/``: tuning the product's own instructions to a corpus would make
the pilot a measurement of the harness. It is on the opening turn only rather than on
every turn, because repeating it across all ~5,900 turns would put identical
boilerplate into every episode's embedding, and ingestion recall is one of the numbers
this pilot exists to measure.

**Speaker labels are kept in the text.** Dropping the names would make "when did
Caroline go to the support group?" unanswerable from an episode that says only "I went
to a support group" — the name is evidence, not framing, and under the frame above it
is also the only thing telling the reader which of two third parties spoke. This is
the corpus's own convention: LoCoMo's published baselines render the dialogue with
speaker names.

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

#: The one line that tells an observation window what it is reading — see the
#: module docstring's third choice. Prefixed to each session's *opening* turn only,
#: so the frame is stated once per session rather than folded into every episode's
#: text. It is data the user supplied, not an instruction to the model: the product's
#: prompts under ``src/`` are untouched by this harness.
_FRAME: Final = "[Transcript the user shared]"

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
    # `speaker_a` is deliberately no longer read. It existed only to decide which
    # speaker took the user half, and under the honest framing every speaker does, so
    # requiring the key would be a parsing precondition for a decision nobody makes.
    sessions = tuple(
        _session(conversation, ordinal, case_key=case_key)
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


def _session(conversation: dict[str, Any], ordinal: int, *, case_key: str) -> BenchSession:
    """Build one session, marked as the user-supplied transcript it is.

    ``user_supplied=True`` is the session-level half of the framing decision: it is
    what makes each corpus turn one exchange with no assistant half, instead of the
    fold in :func:`~benchmarks.memory.ingest.exchanges_of` joining a whole session of
    same-side utterances into a single episode.

    Args:
        conversation: The sample's conversation object.
        ordinal: Which session.
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
        _turn(entry, case_key=case_key, key=key, opening=index == 0)
        for index, entry in enumerate(conversation[key])
    )
    return BenchSession(session_key=key, occurred_at=occurred_at, turns=turns, user_supplied=True)


def _turn(entry: Any, *, case_key: str, key: str, opening: bool) -> BenchTurn:
    """Build one utterance, rendering a shared photo as text.

    **Every turn is the user's side** (``user_side=True``), whichever of the two
    named people spoke it: the user is the person who supplied the transcript, not a
    participant in it, and the assistant is neither. See the module docstring.

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
        case_key: For error messages.
        key: For error messages.
        opening: Whether this is the session's first turn, which carries
            :data:`_FRAME`.

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
    spoken = f"{speaker}: {said}"
    return BenchTurn(
        speaker=speaker,
        text=f"{_FRAME}\n{spoken}" if opening else spoken,
        user_side=True,
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
