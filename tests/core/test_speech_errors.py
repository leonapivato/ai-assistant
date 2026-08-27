"""The speech failure vocabulary, and what ADR-0200 §1 leaves untouched.

Two halves, and the second is the load-bearing one. ``SpeechError`` and
``SpeechTimeoutError`` carry the axes ADR-0011 §1 and ADR-0013 §1 fixed, with the
conservative defaults; and ``ModelError``, its taxonomy and ``ModelProvider``'s
member set are **unchanged**, which is what "a sibling, not a widening" means when
it is checked rather than asserted.
"""

from __future__ import annotations

import inspect

import pytest

from ai_assistant.core import errors as errors_module
from ai_assistant.core.errors import (
    AssistantError,
    ModelAuthError,
    ModelContentFilterError,
    ModelError,
    ModelRateLimitError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    SpeechError,
    SpeechTimeoutError,
)
from ai_assistant.core.protocols import ModelProvider, SpeechSynthesizer, SpeechTranscriber


def _proper_subclasses(base: type) -> set[type]:
    """Every class in this module that inherits ``base``, excluding ``base``."""
    return {
        value
        for value in vars(errors_module).values()
        if isinstance(value, type) and issubclass(value, base) and value is not base
    }


# --- the taxonomy is two classes --------------------------------------------


def test_the_proper_subclass_set_is_exactly_the_timeout() -> None:
    # ADR-0200 §1: "This ADR adds exactly **one** proper subclass of
    # `SpeechError` and no more". A third would also owe a `SpeechFailure` member
    # under §4's bijection, so it cannot land quietly.
    assert _proper_subclasses(SpeechError) == {SpeechTimeoutError}


def test_a_speech_error_is_an_assistant_error_and_not_a_model_error() -> None:
    # The whole of "a sibling, not a widening": a caller's `except ModelError`
    # must not swallow a speech failure, and `except AssistantError` must.
    assert issubclass(SpeechError, AssistantError)
    assert not issubclass(SpeechError, ModelError)
    assert not issubclass(ModelError, SpeechError)


def test_the_base_is_conservatively_neither_retryable_nor_routable() -> None:
    assert SpeechError.retryable is False
    assert SpeechError.routable is False


def test_the_timeout_is_both_retryable_and_routable() -> None:
    assert SpeechTimeoutError.retryable is True
    assert SpeechTimeoutError.routable is True


def test_the_flags_are_readable_from_an_instance() -> None:
    # Class attributes, but a handler holds an instance, so this is the access
    # path that actually matters.
    assert SpeechTimeoutError("expired").retryable is True
    assert SpeechError("something").routable is False


def test_a_speech_error_carries_only_a_message() -> None:
    # What lets ADR-0085 §10a reconstruct one from its message alone. A subclass
    # that grew structured state would need `wire/errors.py` to carry it.
    assert list(inspect.signature(SpeechError.__init__).parameters) == ["self", "args"]


# --- what stays untouched ----------------------------------------------------


def test_the_model_error_taxonomy_is_unchanged() -> None:
    # ADR-0200 §12: `ModelError` and its taxonomy are left "byte-unchanged and
    # unwidened". Enumerated rather than counted, so a *replacement* is caught as
    # well as an addition.
    assert _proper_subclasses(ModelError) == {
        ModelAuthError,
        ModelContentFilterError,
        ModelRateLimitError,
        ModelResponseError,
        ModelTimeoutError,
        ModelUnavailableError,
    }


def test_the_model_provider_member_set_is_unchanged() -> None:
    # ADR-0200 §1's first clause, and §13's first row: no member is added to
    # `ModelProvider`. A structural `@runtime_checkable` Protocol makes this
    # sharper than it looks — one new member silently unsatisfies every existing
    # implementation and every fake at once.
    assert set(ModelProvider.__protocol_attrs__) == {"complete"}  # type: ignore[attr-defined]


def test_neither_speech_protocol_inherits_from_another() -> None:
    # ADR-0200 §1: "neither new Protocol inherits from another". Structurally an
    # object may satisfy both; nothing requires that one does.
    #
    # Asserted over the MRO rather than with `issubclass`, which a
    # `@runtime_checkable` Protocol carrying a *property* refuses outright — and
    # nominal inheritance is what the clause is about anyway.
    assert SpeechSynthesizer not in SpeechTranscriber.__mro__
    assert SpeechTranscriber not in SpeechSynthesizer.__mro__
    assert ModelProvider not in SpeechTranscriber.__mro__
    assert ModelProvider not in SpeechSynthesizer.__mro__


@pytest.mark.parametrize(
    ("protocol", "member"),
    [(SpeechTranscriber, "transcribe"), (SpeechSynthesizer, "synthesize")],
)
def test_each_speech_protocol_has_two_members_and_no_more(protocol: type, member: str) -> None:
    # ADR-0200 §1 fixes the count on both seams, and in particular admits no
    # timeout parameter — the deadline is a decorator (§1, ADR-0118 §2).
    assert set(protocol.__protocol_attrs__) == {"formats", member}  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("protocol", "member"),
    [(SpeechTranscriber, "transcribe"), (SpeechSynthesizer, "synthesize")],
)
def test_neither_seam_takes_a_deadline(protocol: type, member: str) -> None:
    parameters = set(inspect.signature(getattr(protocol, member)).parameters)

    assert not parameters & {"timeout", "timeout_seconds", "deadline"}


def test_the_synthesizer_takes_one_positional_subject_and_a_keyword_format() -> None:
    # ADR-0085 §2's convention, which ADR-0200 §1 keeps: the subject is
    # positional and every other argument is keyword-only.
    parameters = inspect.signature(SpeechSynthesizer.synthesize).parameters

    assert parameters["text"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["format"].kind is inspect.Parameter.KEYWORD_ONLY
