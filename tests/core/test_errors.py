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
    EmbeddingDeadlineExpiredError,
    MemoryStoreEmbeddingExpiredError,
    MemoryStoreError,
    ModelAuthError,
    ModelContentFilterError,
    ModelError,
    ModelRateLimitError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    UnresolvedEvidenceError,
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


# --- the unresolved-evidence refusal (ADR-0077 §5) ---------------------------
# The subclass ADR-0079 §4 named and left open. Its whole point is that the
# ingesting stage can tell an evidence record that expired under it from a
# producer citing something it was never handed, so the ids it carries are the
# behaviour, not decoration.


def test_unresolved_evidence_is_caught_by_an_existing_memory_store_handler() -> None:
    """Additive under ``except MemoryStoreError`` (ADR-0028 §5 stays true)."""
    error = UnresolvedEvidenceError("cites a record the store does not hold", ["ep-1"])

    assert isinstance(error, MemoryStoreError)
    assert isinstance(error, AssistantError)


def test_unresolved_evidence_carries_the_ids_that_failed_to_resolve() -> None:
    error = UnresolvedEvidenceError("nope", ["ep-1", "ep-2"])

    assert error.unresolved_ids == ("ep-1", "ep-2")
    assert str(error) == "nope"


def test_unresolved_evidence_snapshots_the_ids_it_was_given() -> None:
    """A caller mutating its own list must not rewrite the error after the fact."""
    ids = ["ep-1"]
    error = UnresolvedEvidenceError("nope", ids)
    ids.append("ep-2")

    assert error.unresolved_ids == ("ep-1",)


def test_unresolved_evidence_names_no_ids_when_it_is_given_none() -> None:
    assert UnresolvedEvidenceError("nope").unresolved_ids == ()


# --- the translated embedding expiry (ADR-0118 §5) ---------------------------
# The store's half of the discriminator. Two claims are structural rather than
# behavioural, so they are pinned here rather than at either translating seam:
# the translation is catchable by the family, and it is *not* the seam's own
# class wearing a second name.


def test_a_translated_expiry_is_caught_by_an_existing_memory_store_handler() -> None:
    """Additive under ``except MemoryStoreError`` (ADR-0028 §5 stays true)."""
    error = MemoryStoreEmbeddingExpiredError("embedding outlived its deadline")

    assert isinstance(error, MemoryStoreError)
    assert isinstance(error, AssistantError)


def test_the_translation_and_the_seams_own_class_are_separate_hierarchies() -> None:
    """Neither may be caught by a handler written for the other (ADR-0118 §5).

    The seam's class deliberately does not subclass ``MemoryStoreError`` — it is
    not a store fault — and the translation is not an ``EmbeddingDeadlineExpiredError``,
    so a caller above a store cannot reach past the boundary by catching the
    embedder's class and get lucky.
    """
    assert not issubclass(MemoryStoreEmbeddingExpiredError, EmbeddingDeadlineExpiredError)
    assert not issubclass(EmbeddingDeadlineExpiredError, MemoryStoreError)
