"""ADR-0213's axis at the type: the label's form, the tuple's order, the bound's absence.

§12's representative inputs, the ones that land on ``core`` — tests 2, 3, 4, the
type half of 5 and 25, and 19. What each pins is an *input and its outcome*, not a
file layout: the form is refused rather than folded (§3), the tuple is a set with a
fixed spelling (§1), an absent field is the empty tuple (§7), the cardinality bound
is deliberately **not** on the type (§1), and the field is bookkeeping rather than
belief so it stays out of the proposal fingerprint (§10).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import (
    MAX_TOPIC_LABEL_LENGTH,
    MAX_TOPICS_PER_RECORD,
    DataTier,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
    SemanticMemory,
    TopicLabel,
)

_LABEL: TypeAdapter[str] = TypeAdapter(TopicLabel)

_NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _record(**overrides: object) -> SemanticMemory:
    """A minimal semantic record, varying only what a case is about."""
    fields: dict[str, object] = {
        "id": "r1",
        "content": "the user runs on Tuesdays",
        "fact": "the user runs on Tuesdays",
        "provenance": Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
    }
    return SemanticMemory.model_validate(fields | overrides)


# --- §12.2: the canonical form, refused rather than folded ------------------


@pytest.mark.parametrize(
    "label",
    [
        pytest.param("health", id="one word"),
        pytest.param("car maintenance", id="a single internal space"),
        pytest.param("h", id="one character"),
        pytest.param("x" * MAX_TOPIC_LABEL_LENGTH, id="exactly at the length bound"),
        pytest.param("health2", id="a digit"),
        pytest.param("café", id="non-ascii that survives casefold"),
    ],
)
def test_a_canonical_label_is_admitted(label: str) -> None:
    """The form is thin on purpose: it decides spelling and never meaning (§3)."""
    assert _LABEL.validate_python(label) == label


@pytest.mark.parametrize(
    "label",
    [
        pytest.param("Health", id="an uppercase letter"),
        pytest.param("HEALTH", id="shouted"),
        pytest.param(" health", id="a leading space"),
        pytest.param("health ", id="a trailing space"),
        pytest.param("health  care", id="two consecutive spaces"),
        pytest.param("", id="empty"),
        pytest.param("x" * (MAX_TOPIC_LABEL_LENGTH + 1), id="one past the length bound"),
        pytest.param("health\tcare", id="a tab"),
        pytest.param("health\ncare", id="a newline"),
        pytest.param("health\u00a0care", id="a no-break space"),
        pytest.param("health\u2028care", id="a line separator"),
        pytest.param("health\u3000care", id="an ideographic space"),
    ],
)
def test_a_non_canonical_label_is_refused(label: str) -> None:
    """Refused at construction, never quietly repaired (§3).

    ``U+00A0`` is the case that separates a check written against ``str.isspace()``
    from one written against a two-character list, and §12.2 names it for that
    reason: it is whitespace, it survives ``casefold()``, and it is not ``U+0020``.
    """
    with pytest.raises(ValidationError):
        _LABEL.validate_python(label)


def test_the_refusal_carries_the_value_as_given_rather_than_folded() -> None:
    """A message quoting a folded form would report a value nobody wrote (§3)."""
    with pytest.raises(ValidationError) as caught:
        _LABEL.validate_python("Health")
    assert "'Health'" in str(caught.value)
    assert "'health'" not in str(caught.value)


def test_a_non_canonical_label_is_refused_on_the_record_too() -> None:
    """The field carries the type, so a record cannot slip a label past it."""
    with pytest.raises(ValidationError):
        _record(topics=("Health",))


# --- §12.3: the tuple is a set with one spelling ----------------------------


def test_a_sorted_tuple_is_admitted() -> None:
    assert _record(topics=("health", "sleep")).topics == ("health", "sleep")


@pytest.mark.parametrize(
    "topics",
    [
        pytest.param(("sleep", "health"), id="unsorted"),
        pytest.param(("health", "health"), id="a repeated label"),
        pytest.param(("health", "sleep", "running"), id="unsorted at the tail"),
    ],
)
def test_a_tuple_that_is_not_strictly_increasing_is_refused(topics: tuple[str, ...]) -> None:
    """Order carries no meaning, so fixing one is what makes two equal sets one value (§1)."""
    with pytest.raises(ValidationError):
        _record(topics=topics)


def test_two_spellings_of_one_set_cannot_both_exist() -> None:
    """The property the order buys: serialise-and-reconstruct parity and digest stability."""
    record = _record(topics=("health", "sleep"))
    assert SemanticMemory.model_validate_json(record.model_dump_json()).topics == record.topics
    with pytest.raises(ValidationError):
        _record(topics=("sleep", "health"))


# --- §12.4: an unrecorded topic is the empty tuple --------------------------


def test_a_record_constructed_with_no_topics_carries_the_empty_tuple() -> None:
    """Empty is "no topic was recorded" — neither "no topic" nor "every topic" (§7)."""
    assert _record().topics == ()


def test_a_record_serialised_before_the_field_landed_decodes_to_the_empty_tuple() -> None:
    """The member has a default, which is what ADR-0124 §9's version test rests on (§11)."""
    payload = _record().model_dump(mode="json")
    del payload["topics"]
    assert SemanticMemory.model_validate(payload).topics == ()


# --- §12.5 and §12.25, the type's half: the bound is not here ---------------


def test_a_tuple_of_five_labels_is_admissible_on_the_type() -> None:
    """``MAX_TOPICS_PER_PROPOSAL`` bounds a *producer*, and is not a type rule (§1, §4)."""
    labels = ("a", "b", "c", "d", "e")
    assert _record(topics=labels).topics == labels


def test_a_record_over_the_install_bound_constructs_and_decodes() -> None:
    """The direction a ``max_length`` would have broken (§1, §12.25).

    §1 keeps the bound off the type precisely so that a later ADR raising it changes
    what this deployment *writes* and not what an older peer can *read*: a record
    written at a higher bound must still decode here rather than being refused for a
    reason its owner cannot see and did not cause.
    """
    labels = tuple(f"topic {index:02d}" for index in range(MAX_TOPICS_PER_RECORD + 1))
    record = _record(topics=labels)
    assert record.topics == labels
    assert SemanticMemory.model_validate_json(record.model_dump_json()).topics == labels


# --- §12.19: out of the fingerprint -----------------------------------------


def _proposal(topics: tuple[str, ...]) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(
        proposed=_record(topics=topics),
        rationale="because the episodes support it",
        sensitivity=DataTier.PERSONAL,
    )


def test_two_proposals_differing_only_in_topics_are_one_question() -> None:
    """Topics are how a record is filed, not what is believed (§10, ADR-0078 §7).

    Both layers, because the outer one is what the deferral queue dedups on: a
    difference the user was never shown must not mint a second question.
    """
    plain = _proposal(())
    labelled = _proposal(("health", "sleep"))
    assert plain.proposal_fingerprint == labelled.proposal_fingerprint
    assert plain.question_key == labelled.question_key


def test_a_content_difference_still_separates_two_questions() -> None:
    """The exclusion is of one field, not of the projection's discrimination."""
    labelled = _proposal(("health",))
    other = MemoryUpdateProposal(
        proposed=_record(content="the user swims", fact="the user swims", topics=("health",)),
        rationale="because the episodes support it",
        sensitivity=DataTier.PERSONAL,
    )
    assert labelled.proposal_fingerprint != other.proposal_fingerprint
