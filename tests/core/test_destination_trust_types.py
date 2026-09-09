"""``DestinationTrust`` and ``DestinationTrustRecord`` (ADR-0238 §1).

The fact the user sets about a destination, and the record that carries it. The
*store's* clauses are asserted by the shared conformance suite under
``tests/permissions/``; what is here is what the **types** decide, which is every
refusal a producer cannot get past.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    BoundAccount,
    CanonicalDestination,
    DestinationProtocol,
    DestinationTrust,
    DestinationTrustRecord,
    RecipientGrant,
)

AT: Final = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
ALICE: Final = "alice@example.com"
BOB: Final = "bob@example.com"


def member(canonical: str) -> CanonicalDestination:
    return CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical=canonical)


def record(**overrides: object) -> DestinationTrustRecord:
    """A well-formed record, with ``overrides`` applied to its field state."""
    whole: dict[str, object] = {
        "id": "t-1",
        "destinations": (member(ALICE),),
        "trust": DestinationTrust.USER_CHOSEN,
        "established_at": AT,
    }
    return DestinationTrustRecord(**(whole | overrides))  # type: ignore[arg-type]


# --- §1: the vocabulary ------------------------------------------------------


def test_the_vocabulary_is_closed_at_exactly_two_members() -> None:
    """§1: "closed at exactly **two** members", added to and never renamed.

    **Two and not three, unlike the source side.** #2096's source writer-set is
    three-valued because policy there needs two boundaries; the destination side needs
    one, because the question is binary at every seam this corpus has — either the
    user picked this party or nobody did. A third member would be a guess about a
    mechanism no ADR has designed, and the enumeration is extended by ADR precisely so
    that milestone 32 or 33 may add one **when it has a policy that reads it**.

    The *values* are pinned as well as the names, because they are what a stored
    record and a wire frame carry: renaming one silently reinterprets every row.
    """
    assert {member.name: member.value for member in DestinationTrust} == {
        "USER_CHOSEN": "user_chosen",
        "UNCHOSEN": "unchosen",
    }


# --- §1: the record's five fields --------------------------------------------


def test_the_record_carries_five_fields_and_no_sixth() -> None:
    """§1 states the members exactly, and a lane adding one is changing that decision.

    **It carries no tool, no account, no payload, no description and no content**: it
    is a fact about a destination set and nothing else, which is what makes it
    readable for a destination no ``RecipientGrant`` covers — the property milestone
    32 needs and a grant-carried field could not have.
    """
    assert set(DestinationTrustRecord.model_fields) == {
        "id",
        "destinations",
        "trust",
        "established_at",
        "revoked_at",
    }
    assert DestinationTrustRecord.model_config.get("frozen") is True
    assert DestinationTrustRecord.model_config.get("extra") == "forbid"


def test_only_revoked_at_may_be_omitted() -> None:
    """``revoked_at`` defaults to ``None``; every other field is the caller's to state.

    The id in particular: it is **minted by the caller that constructs the record**, as
    ``RecipientGrant``'s is, so the record is a complete value before it reaches any
    store and the store's duplicate refusal is a comparison rather than an allocation.
    """
    required = {
        name for name, field in DestinationTrustRecord.model_fields.items() if field.is_required()
    }

    assert required == {"id", "destinations", "trust", "established_at"}
    assert record().revoked_at is None


def test_a_record_asserting_unchosen_is_refused_at_construction() -> None:
    """§1: ``UNCHOSEN`` is what absence means, so a record asserting it is nothing twice.

    Two spellings of one state is the shape ADR-0217 §1's refusal table exists to
    prevent, and refusing it **on the type** is what stops any producer, decode, test
    double or later lane from building one — so no store ever has to decide which of
    the two an absent-and-present destination is.
    """
    with pytest.raises(ValidationError, match="UNCHOSEN"):
        record(trust=DestinationTrust.UNCHOSEN)


# --- §1: the destination tuple, by ADR-0193 §1's own validator ---------------


def test_the_destination_tuple_takes_the_recipient_grants_own_validator() -> None:
    """§1: "by the same validator and not a second one" — the same three refusals.

    **Without it §1's revocation clause is false**: ``(Alice, Bob)`` and ``(Bob,
    Alice)`` are unequal tuples over one logical set, both would be admitted as live,
    and revoking the record the user was shown would leave the other standing with the
    destination still reading ``USER_CHOSEN``.
    """
    with pytest.raises(ValidationError, match="at least one canonical destination"):
        record(destinations=())
    with pytest.raises(ValidationError, match="once"):
        record(destinations=(member(ALICE), member(ALICE)))
    with pytest.raises(ValidationError, match="canonical order"):
        record(destinations=(member(BOB), member(ALICE)))

    assert record(destinations=(member(ALICE), member(BOB))).destinations == (
        member(ALICE),
        member(BOB),
    )


def test_the_two_records_are_refused_by_one_validator_in_the_same_words() -> None:
    """The shared rule, pinned as *shared* rather than as two agreeing copies.

    ADR-0193 §1's own reason for pinning one spelling at construction is that it "lets
    three separate rules stated over *identity* … each be written as tuple equality and
    each mean set equality", and that stating the duplicate rule over membership
    instead "leaves the comparison free to drift back to tuple equality with no test
    noticing". A second copy of the validator is the same drift one level up, so what
    is asserted is that the two records refuse the same tuple with the same message.
    """
    with pytest.raises(ValidationError) as trust_refusal:
        record(destinations=(member(BOB), member(ALICE)))
    with pytest.raises(ValidationError) as grant_refusal:
        RecipientGrant.model_validate({"destinations": (member(BOB), member(ALICE))}, strict=False)

    assert "canonical order" in str(trust_refusal.value)
    assert "canonical order" in str(grant_refusal.value)


def test_an_account_member_is_admitted_and_orders_before_a_recipient() -> None:
    """The other member shape of a canonical destination set, and the one order.

    Account members first, then selected recipients — the total order
    ``EgressBinding.canonical_destination_set`` already produces. A record over an
    account is what a destination reached *through* a connected account needs, and it
    is not interchangeable with a recipient member of the same identity.
    """
    account = CanonicalDestination(account=BoundAccount(identity=ALICE, reference="conn-0001"))

    held = record(destinations=(account, member(BOB)))

    assert held.destinations == (account, member(BOB))
    with pytest.raises(ValidationError, match="canonical order"):
        record(destinations=(member(BOB), account))


# --- §1: the instants --------------------------------------------------------


def test_a_naive_instant_is_refused_on_both_fields() -> None:
    """The store is durable **and** ordered — ``RecipientGrant.decided_at``'s reason."""
    with pytest.raises(ValidationError):
        record(established_at=datetime(2026, 9, 9, 12, 0))  # noqa: DTZ001
    with pytest.raises(ValidationError):
        record(revoked_at=datetime(2026, 9, 9, 13, 0))  # noqa: DTZ001


def test_a_revocation_earlier_than_the_act_is_admitted_by_the_type() -> None:
    """No ordering invariant between the two instants, and that is deliberate.

    ``RecipientGrant`` refuses a *granting* record that is live for no duration; this
    record has no expiry, so there is no such interval to be empty. Both instants are
    caller-supplied and the store reads no clock on the write path, so a host clock
    corrected backwards would otherwise make a record permanently unrevokable — the
    reason ``SqliteRecipientGrantStore.record`` gives for never refusing a revocation
    on its timestamp.
    """
    held = record(revoked_at=AT - timedelta(days=1))

    assert held.revoked_at is not None
    assert held.revoked_at < held.established_at
