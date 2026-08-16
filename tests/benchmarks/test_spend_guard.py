"""A paid run stops on its own terms, and the artifacts say so.

Pilot 2 and pilot 3 both ended partway through on a provider refusing a call for want of
credit, and both left a run directory that is neither a measurement nor a legible
failure. Four properties make the difference, and each is a distinct way the guard could
be present and useless:

* **The ceiling binds before the call**, so a bounded run makes exactly its bound and not
  one more.
* **The abort is not a ``ModelError``**, because ``answer_question`` catches those per
  question — an abort wearing that class would be swallowed once per question and the run
  would *complete*, reporting an accuracy collapse that was really a billing event.
* **The records survive and the manifest is rewritten**, which is the whole reason
  ``execute_run`` returns rather than raises.
* **The credit signature is matched narrowly**, and in particular does not fire on a rate
  limit, which is transient and must stay retryable.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn
from benchmarks.memory.corpora.provenance import LOCOMO
from benchmarks.memory.records import QuestionRecord, RunManifest, RunMode, read_jsonl
from benchmarks.memory.run import execute_run, plan_run
from benchmarks.memory.spend import (
    CREDIT_EXHAUSTION_SIGNATURES,
    RunAbortedError,
    SpendGuard,
    is_credit_exhaustion,
)

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import (
    ModelError,
    ModelRateLimitError,
    ModelUnavailableError,
)
from ai_assistant.core.types import Message, Role
from ai_assistant.testing import FakeModelProvider, FakeObserver

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

FIRST = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)
BATCH = 2

#: The text an exhausted Anthropic account comes back with, as it reaches this seam:
#: `models.provider._classify` prefixes it and maps the 400 to a bare `ModelError`.
CREDIT_400 = (
    "model completion failed: status_code: 400, model_name: claude-x, body: "
    "{'type': 'invalid_request_error', 'message': 'Your credit balance is too low to "
    "access the Anthropic API. Please go to Plans & Billing to upgrade or purchase "
    "credits.'}"
)


def _case() -> BenchCase:
    """A one-session case with two questions, so a per-question ceiling is observable.

    Returns:
        The case.
    """
    return BenchCase(
        corpus_key="locomo",
        case_key="spend-test",
        sessions=(
            BenchSession(
                session_key="session_1",
                occurred_at=FIRST,
                turns=(
                    BenchTurn(speaker="Ada", text="Ada: I adopted a dog.", user_side=True),
                    BenchTurn(speaker="Bo", text="Bo: What is her name?", user_side=False),
                    BenchTurn(speaker="Ada", text="Ada: Her name is Juno.", user_side=True),
                    BenchTurn(speaker="Bo", text="Bo: Lovely name.", user_side=False),
                ),
            ),
        ),
        questions=(
            BenchQuestion(
                question_id="spend-test#0",
                category="1",
                question="What did Ada adopt?",
                answer="a dog",
                evidence=("D1:1",),
            ),
            BenchQuestion(
                question_id="spend-test#1",
                category="1",
                question="What is the dog called?",
                answer="Juno",
                evidence=("D1:3",),
            ),
        ),
    )


def _settings(tmp_path: Path) -> Settings:
    """Settings a plumbing check may use, and a scored run may not.

    Args:
        tmp_path: The test's directory.

    Returns:
        The settings.
    """
    return Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        episode_retention=None,
        observation_batch_size=BATCH,
    )


class _FailingProvider:
    """A ``ModelProvider`` that answers ``before`` times and then raises ``error``.

    Hand-written rather than ``FakeModelProvider`` because what is under test is a
    failure *after* some successful work: the guard has to convert the failure while
    leaving everything the run already produced in place.
    """

    def __init__(self, error: ModelError, *, before: int) -> None:
        """Arrange the failure.

        Args:
            error: What to raise once ``before`` calls have been served.
            before: How many calls succeed first.
        """
        self._error = error
        self._before = before
        self.calls = 0

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        """Answer, or raise.

        Args:
            messages: Ignored; the reply is fixed.
            model: Ignored.

        Returns:
            A fixed reply.

        Raises:
            ModelError: Once ``before`` calls have been served.
        """
        self.calls += 1
        if self.calls > self._before:
            raise self._error
        return Message(role=Role.ASSISTANT, content="a dog")


async def test_the_ceiling_binds_before_the_call_rather_than_after() -> None:
    """A bounded run makes exactly its bound, never one more.

    Charging at the attempt is what makes this true, and it is also why a *failed* call
    spends: it may well have been billed, and a guard counting only successes would be
    defeated by the failing run it exists to stop.
    """
    guard = SpendGuard(limit=2)
    provider = guard.wrap(FakeModelProvider("a dog"))
    turn = [Message(role=Role.USER, content="hello")]

    await provider.complete(turn)
    await provider.complete(turn)
    with pytest.raises(RunAbortedError, match="ceiling of 2 model calls"):
        await provider.complete(turn)

    assert guard.calls == 2


async def test_no_ceiling_is_a_counter_and_nothing_else() -> None:
    """The default, asserted because every existing caller depends on it."""
    guard = SpendGuard()
    provider = guard.wrap(FakeModelProvider("a dog"))

    for _ in range(5):
        await provider.complete([Message(role=Role.USER, content="hello")])

    assert guard.calls == 5
    assert guard.limit is None


async def test_a_zero_ceiling_permits_no_call_at_all() -> None:
    """Meaningful rather than degenerate: it is what "plan only" looks like from inside."""
    guard = SpendGuard(limit=0)
    provider = guard.wrap(FakeModelProvider("a dog"))

    with pytest.raises(RunAbortedError):
        await provider.complete([Message(role=Role.USER, content="hello")])

    assert guard.calls == 0


@pytest.mark.parametrize(
    ("limit", "error"),
    [(True, TypeError), (1.5, TypeError), (-1, ValueError)],
    ids=["a flag is not a count", "a float is not a count", "negative"],
)
def test_a_bound_that_is_not_a_count_is_refused(limit: object, error: type[Exception]) -> None:
    """`bool` is the case a type annotation cannot hold: `True` would cap a paid run at one."""
    with pytest.raises(error):
        SpendGuard(limit=limit)  # type: ignore[arg-type]


def test_the_abort_is_not_a_model_error() -> None:
    """The property the whole design turns on.

    `answer_question` catches `ModelError` per question and records it as one failed
    answer. An abort inside that hierarchy would be swallowed once per question, the run
    would finish, and a billing event would be published as a corpus-wide accuracy
    collapse — the failure mode this module exists to prevent, reintroduced by a class
    declaration.
    """
    assert not issubclass(RunAbortedError, ModelError)


@pytest.mark.parametrize("signature", CREDIT_EXHAUSTION_SIGNATURES)
def test_every_signature_is_recognised(signature: str) -> None:
    """Each entry is live: a list nothing matches is a guard that does not guard."""
    assert is_credit_exhaustion(ModelError(f"model completion failed: {signature.upper()}"))


def test_the_real_refusal_is_recognised() -> None:
    """The text pilot 2 and pilot 3 actually died on, as it reaches this seam."""
    assert is_credit_exhaustion(ModelError(CREDIT_400))


@pytest.mark.parametrize(
    "error",
    [
        ModelRateLimitError("model completion failed: status_code: 429, rate limited"),
        ModelUnavailableError("model completion failed: status_code: 503"),
        ModelError("model completion failed: status_code: 400, messages: too many tokens"),
    ],
    ids=["rate limit", "outage", "another 400"],
)
def test_a_transient_or_unrelated_failure_is_not_credit_exhaustion(error: ModelError) -> None:
    """The rate limit is the one that matters: it is transient and must stay retryable.

    A looser pattern — "billing", "quota" on its own — would catch it, and a run stopped
    on a throttle is a run stopped for nothing.
    """
    assert not is_credit_exhaustion(error)


async def test_a_credit_refusal_stops_the_run_and_leaves_its_records(tmp_path: Path) -> None:
    """The end-to-end shape, and the reason `execute_run` returns rather than raises.

    The provider answers the first question and refuses the second, so the assertion is
    that the first question's record survives — a run that dies at question 400 of 2,000
    should leave 399 usable rows. The manifest is read back off disk rather than off the
    returned object, because the file is what a later reader has.
    """
    root = tmp_path / "runs"
    provider = _FailingProvider(ModelError(CREDIT_400), before=1)

    manifest = await execute_run(
        plan_run(LOCOMO, (_case(),), batch_size=BATCH),
        output_root=root,
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=provider,
        observer=FakeObserver(max_batch_size=BATCH),
    )

    assert manifest.aborted is not None
    assert "want of credit" in manifest.aborted
    run_dir = root / manifest.run_id
    written = RunManifest.model_validate_json((run_dir / "manifest.json").read_text("utf-8"))
    assert written.aborted == manifest.aborted
    records = read_jsonl(run_dir / "records.jsonl", QuestionRecord)
    assert len(records) == 1
    assert records[0].question_id == "spend-test#0"


async def test_a_reached_ceiling_stops_the_run_and_records_the_bound(tmp_path: Path) -> None:
    """The ceiling end to end, and the field a reader pairs the abort with.

    The observer is injected and the grader makes no call, so every charge here is an
    answer: a bound of one buys the first question and stops at the second. That is the
    shape a real run stops in — some records kept, the manifest saying why there are no
    more — and it is asserted below rather than left to the abort message.
    """
    root = tmp_path / "runs"

    manifest = await execute_run(
        plan_run(LOCOMO, (_case(),), batch_size=BATCH),
        output_root=root,
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=FakeModelProvider("a dog"),
        observer=FakeObserver(max_batch_size=BATCH),
        max_model_calls=1,
    )

    assert manifest.model_call_ceiling == 1
    assert manifest.aborted is not None
    assert "ceiling of 1 model calls" in manifest.aborted
    written = json.loads((root / manifest.run_id / "manifest.json").read_text("utf-8"))
    assert written["model_call_ceiling"] == 1
    assert written["aborted"] == manifest.aborted
    records = read_jsonl(root / manifest.run_id / "records.jsonl", QuestionRecord)
    assert len(records) == 1
    assert records[0].question_id == "spend-test#0"


async def test_an_unbounded_run_records_no_abort(tmp_path: Path) -> None:
    """The control. Both fields stay `None`, and the manifest is written exactly once.

    The single-write property is asserted through the *returned* manifest matching the
    file: `execute_run` writes the file before any case runs, so an interrupted run
    still says what it was, and the abort path is the only thing that rewrites it.
    """
    root = tmp_path / "runs"

    manifest = await execute_run(
        plan_run(LOCOMO, (_case(),), batch_size=BATCH),
        output_root=root,
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=FakeModelProvider("a dog"),
        observer=FakeObserver(max_batch_size=BATCH),
    )

    assert manifest.aborted is None
    assert manifest.model_call_ceiling is None
    written = RunManifest.model_validate_json(
        (root / manifest.run_id / "manifest.json").read_text("utf-8")
    )
    assert written == manifest
    assert len(read_jsonl(root / manifest.run_id / "records.jsonl", QuestionRecord)) == 2


async def test_an_unrelated_provider_failure_is_still_one_ungraded_question(
    tmp_path: Path,
) -> None:
    """The guard narrowed nothing it should not have.

    A transient fault on one question stays a recorded `ungraded` row and the run
    carries on — the behaviour that keeps a 2,000-question run from dying on a blip, and
    the one an over-eager abort would destroy.
    """
    root = tmp_path / "runs"
    provider = _FailingProvider(ModelUnavailableError("model completion failed: 503"), before=1)

    manifest = await execute_run(
        plan_run(LOCOMO, (_case(),), batch_size=BATCH),
        output_root=root,
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=provider,
        observer=FakeObserver(max_batch_size=BATCH),
    )

    assert manifest.aborted is None
    records = read_jsonl(root / manifest.run_id / "records.jsonl", QuestionRecord)
    assert len(records) == 2
    assert any(record.verdict == "ungraded" for record in records)
