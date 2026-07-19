"""Tests pinning the model-failure taxonomy's behavioural flags.

``retryable`` and ``routable`` are read by the resilience wrappers to decide
whether to try again and whether to fall back. Consumers branch on them, so a
changed value silently alters behaviour everywhere at once — ADR-0011 calls this
out as the taxonomy's one genuinely dangerous edit. The matrix below exists so
that such a change has to be made deliberately, in a diff a reviewer can see,
rather than by editing one class attribute in passing.
"""

from __future__ import annotations

import pytest

from ai_assistant.core.errors import (
    AssistantError,
    ModelAuthError,
    ModelContentFilterError,
    ModelError,
    ModelRateLimitError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)

# (error type, retryable, routable)
TAXONOMY: list[tuple[type[ModelError], bool, bool]] = [
    (ModelError, False, False),
    (ModelAuthError, False, True),
    (ModelRateLimitError, True, True),
    (ModelTimeoutError, True, True),
    (ModelUnavailableError, True, True),
    (ModelContentFilterError, False, False),
    (ModelResponseError, False, True),
]


@pytest.mark.parametrize(("error_type", "retryable", "routable"), TAXONOMY)
def test_taxonomy_flags_are_pinned(
    error_type: type[ModelError], *, retryable: bool, routable: bool
) -> None:
    assert error_type.retryable is retryable
    assert error_type.routable is routable


@pytest.mark.parametrize(("error_type", "retryable", "routable"), TAXONOMY)
def test_flags_are_readable_from_an_instance(
    error_type: type[ModelError], *, retryable: bool, routable: bool
) -> None:
    # The wrappers catch an exception and read the flags off the caught object,
    # not off the class, so the ClassVar must resolve through an instance.
    error = error_type("boom")

    assert error.retryable is retryable
    assert error.routable is routable


@pytest.mark.parametrize(("error_type", "_retryable", "_routable"), TAXONOMY)
def test_every_model_error_is_catchable_as_the_family(
    error_type: type[ModelError], _retryable: bool, _routable: bool
) -> None:
    # A caller that does not care about the cause must still be able to catch
    # the whole family with one handler, per the module's contract.
    with pytest.raises(ModelError):
        raise error_type("boom")

    with pytest.raises(AssistantError):
        raise error_type("boom")


def test_the_conservative_default_is_inherited_not_repeated() -> None:
    # A future subclass that declares neither flag must default to the safe
    # answer: no retry storm, and no silently widening which providers see the
    # prompt. This pins the base-class default, not any one subclass.
    class NewlyAddedModelError(ModelError):
        """A subclass added later without thinking about the flags."""

    assert NewlyAddedModelError.retryable is False
    assert NewlyAddedModelError.routable is False
