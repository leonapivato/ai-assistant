"""The two loaders, against fixtures in each corpus's published shape.

The fixtures are hand-written miniatures rather than slices of the real files: the
corpora are 2.8 MiB and 278 MiB, git-ignored, and fetched on demand, so a test that
needed them would be a test that fails on a clean clone. Every shape they carry is one
observed in the real data — LoCoMo's `blip_caption` photo turns, its integer answers,
its category-5 `adversarial_answer`, its date-time keys for sessions that have no
content; LongMemEval's out-of-order sessions, its `_abs` abstention ids, its sessions
that open on the assistant.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from benchmarks.memory.corpora import locomo, longmemeval

if TYPE_CHECKING:
    from pathlib import Path


def _locomo_sample() -> list[dict[str, Any]]:
    """One LoCoMo sample carrying every shape the loader handles.

    Returns:
        The sample list, ready to write as JSON.
    """
    return [
        {
            "sample_id": "conv-1",
            "conversation": {
                "speaker_a": "Ada",
                "speaker_b": "Bo",
                "session_1_date_time": "1:56 pm on 8 May, 2023",
                "session_1": [
                    {"speaker": "Ada", "dia_id": "D1:1", "text": "I adopted a dog."},
                    {"speaker": "Bo", "dia_id": "D1:2", "text": "What is its name?"},
                    {
                        "speaker": "Ada",
                        "dia_id": "D1:3",
                        "text": "Here she is",
                        "blip_caption": "a brown dog on a sofa",
                    },
                ],
                "session_2_date_time": "9:05 am on 12 June, 2023",
                "session_2": [{"speaker": "Ada", "dia_id": "D2:1", "text": "She is settling in."}],
                # A date-time for a session the corpus has no content for. The real
                # file carries these up to session 34; the loader must not invent one.
                "session_3_date_time": "9:05 am on 13 June, 2023",
            },
            "qa": [
                {
                    "question": "What did Ada adopt?",
                    "answer": "a dog",
                    "evidence": ["D1:1"],
                    "category": 1,
                },
                {"question": "How many dogs?", "answer": 1, "evidence": [], "category": 1},
                {
                    "question": "Did Ada adopt a cat?",
                    "adversarial_answer": "No such information",
                    "evidence": [],
                    "category": 5,
                },
                # Category 5 carrying both keys — two of the real corpus's 446 do.
                {
                    "question": "Is the dog blue?",
                    "answer": "No",
                    "adversarial_answer": "Yes",
                    "evidence": ["D1:3"],
                    "category": 5,
                },
            ],
        }
    ]


@pytest.fixture
def locomo_file(tmp_path: Path) -> Path:
    """A LoCoMo file on disk."""
    path = tmp_path / "locomo10.json"
    path.write_text(json.dumps(_locomo_sample()), encoding="utf-8")
    return path


def test_locomo_builds_one_case_per_dialogue(locomo_file: Path) -> None:
    cases = locomo.load(locomo_file)

    assert len(cases) == 1
    assert cases[0].case_key == "conv-1"
    assert cases[0].corpus_key == "locomo"


def test_locomo_skips_a_session_that_has_only_a_date(locomo_file: Path) -> None:
    """`session_3_date_time` exists without `session_3`; two sessions, not three."""
    sessions = locomo.load(locomo_file)[0].sessions

    assert [session.session_key for session in sessions] == ["session_1", "session_2"]


def test_locomo_reads_the_stated_instant_as_utc(locomo_file: Path) -> None:
    first = locomo.load(locomo_file)[0].sessions[0]

    assert first.occurred_at == datetime(2023, 5, 8, 13, 56, tzinfo=UTC)


def test_locomo_keeps_speaker_names_in_the_text(locomo_file: Path) -> None:
    """The name is evidence — "when did Ada…" is unanswerable without it."""
    first = locomo.load(locomo_file)[0].sessions[0].turns[0]

    assert first.text == "Ada: I adopted a dog."
    assert first.user_side is True


def test_locomo_puts_speaker_b_on_the_assistant_side(locomo_file: Path) -> None:
    second = locomo.load(locomo_file)[0].sessions[0].turns[1]

    assert second.speaker == "Bo"
    assert second.user_side is False


def test_locomo_renders_a_shared_photo_as_text(locomo_file: Path) -> None:
    """Dropping the caption would make a slice of questions unanswerable in silence."""
    third = locomo.load(locomo_file)[0].sessions[0].turns[2]

    assert third.text == "Ada: Here she is [shared a photo: a brown dog on a sofa]"


def test_locomo_stringifies_an_integer_answer(locomo_file: Path) -> None:
    """Six of the real corpus's answers are integers; everything downstream sees str."""
    questions = locomo.load(locomo_file)[0].questions

    assert questions[1].answer == "1"


def test_locomo_marks_category_five_unanswerable(locomo_file: Path) -> None:
    questions = locomo.load(locomo_file)[0].questions

    assert [question.unanswerable for question in questions] == [False, False, True, True]


def test_locomo_prefers_the_adversarial_answer_for_category_five(locomo_file: Path) -> None:
    """The two questions carrying both keys are graded like their 444 siblings."""
    both = locomo.load(locomo_file)[0].questions[3]

    assert both.answer == "Yes"


def test_locomo_derives_a_stable_question_id(locomo_file: Path) -> None:
    """The corpus gives none, and a pinned file makes position a stable substitute."""
    ids = [question.question_id for question in locomo.load(locomo_file)[0].questions]

    assert ids == ["conv-1#0", "conv-1#1", "conv-1#2", "conv-1#3"]


def test_locomo_carries_evidence_through_untouched(locomo_file: Path) -> None:
    """P8's split is computed against these pointers."""
    assert locomo.load(locomo_file)[0].questions[0].evidence == ("D1:1",)


def test_locomo_refuses_a_file_that_is_not_a_list(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"sample_id": "x"}', encoding="utf-8")

    with pytest.raises(locomo.LocomoFormatError, match="list of samples"):
        locomo.load(path)


def test_locomo_refuses_an_unreadable_instant(tmp_path: Path) -> None:
    sample = _locomo_sample()
    sample[0]["conversation"]["session_1_date_time"] = "sometime last May"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(sample), encoding="utf-8")

    with pytest.raises(locomo.LocomoFormatError, match="unreadable instant"):
        locomo.load(path)


def _longmemeval_sample() -> list[dict[str, Any]]:
    """LongMemEval questions carrying every shape the loader handles.

    Returns:
        The question list, ready to write as JSON.
    """
    return [
        {
            "question_id": "q_alpha",
            "question_type": "multi-session",
            "question": "What did I buy?",
            "answer": "a bicycle",
            "question_date": "2023/04/10 (Mon) 23:07",
            # Deliberately not in time order: the real corpus is not either.
            "haystack_session_ids": ["s_late", "s_early"],
            "haystack_dates": ["2023/03/02 (Thu) 10:00", "2023/01/05 (Thu) 09:30"],
            "haystack_sessions": [
                [{"role": "user", "content": "I bought a bicycle.", "has_answer": True}],
                # A session opening on the assistant — five of the real oracle's do.
                [
                    {"role": "assistant", "content": "Good morning."},
                    {"role": "user", "content": "Morning."},
                ],
            ],
            "answer_session_ids": ["s_late"],
        },
        {
            "question_id": "q_beta_abs",
            "question_type": "temporal-reasoning",
            "question": "Which came first?",
            "answer": 3,
            "question_date": "2023/05/01 (Mon) 08:00",
            "haystack_session_ids": ["s_one"],
            "haystack_dates": ["2023/04/01 (Sat) 08:00"],
            "haystack_sessions": [[{"role": "user", "content": "Nothing relevant."}]],
        },
    ]


@pytest.fixture
def longmemeval_file(tmp_path: Path) -> Path:
    """A LongMemEval split on disk."""
    path = tmp_path / "longmemeval_s_cleaned.json"
    path.write_text(json.dumps(_longmemeval_sample()), encoding="utf-8")
    return path


def test_longmemeval_gives_every_question_its_own_case(longmemeval_file: Path) -> None:
    """Fifty questions is fifty ingestions; the loader makes that structural."""
    cases = longmemeval.load(longmemeval_file)

    assert len(cases) == 2
    assert all(len(case.questions) == 1 for case in cases)


def test_longmemeval_orders_sessions_by_their_stated_date(longmemeval_file: Path) -> None:
    """File order does not track time, and ingesting out of order scrambles history."""
    sessions = longmemeval.load(longmemeval_file)[0].sessions

    assert [session.session_key for session in sessions] == ["s_early", "s_late"]


def test_longmemeval_adds_no_speaker_prefix(longmemeval_file: Path) -> None:
    """Unlike LoCoMo: here the two sides genuinely are a user and an assistant."""
    late = longmemeval.load(longmemeval_file)[0].sessions[1].turns[0]

    assert late.text == "I bought a bicycle."
    assert late.user_side is True


def test_longmemeval_marks_the_abstention_variant(longmemeval_file: Path) -> None:
    """`_abs` is the corpus's own marker for a haystack that does not answer."""
    verdicts = [case.questions[0].unanswerable for case in longmemeval.load(longmemeval_file)]

    assert verdicts == [False, True]


def test_longmemeval_stringifies_an_integer_answer(longmemeval_file: Path) -> None:
    """32 of the real oracle's 500 answers are integers."""
    assert longmemeval.load(longmemeval_file)[1].questions[0].answer == "3"


def test_longmemeval_reads_the_question_instant(longmemeval_file: Path) -> None:
    """The clock is moved to it before answering, so it has to survive the load."""
    asked = longmemeval.load(longmemeval_file)[0].questions[0].asked_at

    assert asked == datetime(2023, 4, 10, 23, 7, tzinfo=UTC)


def test_longmemeval_refuses_mismatched_haystack_lengths(tmp_path: Path) -> None:
    """Sessions, dates and ids correspond positionally; a mismatch is unrecoverable."""
    sample = _longmemeval_sample()
    sample[0]["haystack_dates"] = sample[0]["haystack_dates"][:1]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(sample), encoding="utf-8")

    with pytest.raises(longmemeval.LongMemEvalFormatError, match="do not correspond"):
        longmemeval.load(path)


def test_stratified_spreads_across_categories(longmemeval_file: Path) -> None:
    cases = longmemeval.load(longmemeval_file)

    picked = longmemeval.stratified(cases, total=2, seed=1029)

    assert {case.questions[0].category for case in picked} == {
        "multi-session",
        "temporal-reasoning",
    }


def test_stratified_is_reproducible_from_its_seed(longmemeval_file: Path) -> None:
    """A pre-registered slice has to be redrawable from the seed and the pinned file."""
    cases = longmemeval.load(longmemeval_file)

    first = longmemeval.stratified(cases, total=1, seed=7)
    again = longmemeval.stratified(cases, total=1, seed=7)

    assert [case.case_key for case in first] == [case.case_key for case in again]


def test_stratified_redistributes_when_a_category_runs_short(longmemeval_file: Path) -> None:
    """Asking for more than one category can supply still meets the total."""
    cases = longmemeval.load(longmemeval_file) * 3

    picked = longmemeval.stratified(cases, total=5, seed=1029)

    assert len(picked) == 5


def test_stratified_returns_everything_when_asked_for_more_than_exists(
    longmemeval_file: Path,
) -> None:
    cases = longmemeval.load(longmemeval_file)

    assert len(longmemeval.stratified(cases, total=99, seed=1029)) == len(cases)


def test_a_slice_round_trips_through_disk(longmemeval_file: Path, tmp_path: Path) -> None:
    """The 278 MiB parse is paid once; later runs read what this wrote."""
    cases = longmemeval.load(longmemeval_file)
    path = tmp_path / "slice" / "cases.json"

    longmemeval.write_slice(cases, path)

    assert longmemeval.read_slice(path) == cases
