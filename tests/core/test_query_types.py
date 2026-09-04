"""``QueryOutcome`` and ``QueryRefusal``: the composer's half of a search (ADR-0231 §3).

**The vocabulary is asserted whole**, which is ADR-0231 §18's arm 9a read at the one
enumeration this lane lands: "``QueryRefusal`` holds exactly its four members …
asserted over the enums themselves, so a member added without an arm fails". The
other two enumerations that arm names — ``SearchRefusal`` and ``SearchDisposition``
— arrive with the lanes that decide them, and the mapping between them is asserted
where all three exist.

**And the structural condition is asserted at the model**, because §3 puts it there
rather than on the composer: "an outcome carrying both or neither is not a value this
corpus admits". Every ``QueryComposer`` this system wires inherits it, the canonical
fake included, without any of them being trusted to keep it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import QueryOutcome, QueryRefusal


def test_the_refusal_vocabulary_is_exactly_the_four_members_the_decision_names() -> None:
    """§3's closed enumeration, by name and by value.

    The values are pinned as well as the names because §3 fixes both — ``declined``,
    ``unavailable``, ``malformed``, ``too_long`` — and because a ``StrEnum``'s value
    is what a serialised outcome carries: renaming one silently would change a wire
    representation while every ``is`` comparison in the tree kept passing. §3 rules
    the vocabulary "added to and never renamed".
    """
    assert [(member.name, member.value) for member in QueryRefusal] == [
        ("DECLINED", "declined"),
        ("UNAVAILABLE", "unavailable"),
        ("MALFORMED", "malformed"),
        ("TOO_LONG", "too_long"),
    ]


@pytest.mark.parametrize("refusal", list(QueryRefusal))
def test_an_outcome_carries_any_one_refusal(refusal: QueryRefusal) -> None:
    """Every member is constructable as an outcome, so none is decorative."""
    outcome = QueryOutcome(refusal=refusal)

    assert outcome.refusal is refusal
    assert outcome.query is None


def test_an_outcome_carries_a_composed_query() -> None:
    """The other half, byte for byte: nothing here normalises what it was given."""
    outcome = QueryOutcome(query="  Porto's  tallest  building  ")

    assert outcome.query == "  Porto's  tallest  building  "
    assert outcome.refusal is None


def test_an_outcome_carrying_both_answers_is_refused() -> None:
    """§3's exactly-one rule: two answers wearing one outcome's name."""
    with pytest.raises(ValidationError, match="never both"):
        QueryOutcome(query="porto", refusal=QueryRefusal.DECLINED)


def test_an_outcome_carrying_neither_answer_is_refused() -> None:
    """The other arm, and the one a defaulted model reaches by omission.

    Both fields default to ``None``, so ``QueryOutcome()`` is the value a composer
    that forgot to say anything would emit — the outcome §3 says a composition never
    has, "neither succeeding nor failing".
    """
    with pytest.raises(ValidationError, match="never neither"):
        QueryOutcome()


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_a_blank_query_is_not_a_query(blank: str) -> None:
    """``NonBlankEncodableText`` is what enforces §17's "a returned query is non-blank".

    Decided at the field rather than in each composer: a blank query is a search for
    nothing, and it would reach the seam as an authorised request carrying no
    question.
    """
    with pytest.raises(ValidationError):
        QueryOutcome(query=blank)


def test_a_query_with_no_utf_8_encoding_is_refused() -> None:
    """The other half of the field's type: what cannot be written down cannot be sent."""
    with pytest.raises(ValidationError):
        QueryOutcome(query="porto \ud800")


def test_an_outcome_refuses_an_unknown_field() -> None:
    """``extra="forbid"``: a bound, a provider, an origin or a rationale is not one.

    §3 gives this value exactly two fields, and the bound in particular is named as
    *not* being one — ``QueryOutcome`` "carries no bound, is configuration-independent,
    and validates identically in every deployment".
    """
    with pytest.raises(ValidationError):
        QueryOutcome.model_validate({"query": "porto", "max_chars": 256})


def test_an_outcome_is_frozen() -> None:
    """Nothing edits a composition after the fact (§4's no-augmentation clause)."""
    outcome = QueryOutcome(query="porto")

    with pytest.raises(ValidationError):
        outcome.query = "porto portugal"


def test_an_outcome_round_trips_through_its_own_serialisation() -> None:
    """The validator binds on the way back in, not only at first construction."""
    for original in (QueryOutcome(query="porto"), QueryOutcome(refusal=QueryRefusal.TOO_LONG)):
        assert QueryOutcome.model_validate(original.model_dump()) == original
