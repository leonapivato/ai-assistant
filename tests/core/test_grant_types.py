"""``GrantScope`` and ``SourceGrant``'s own invariants (ADR-0097 §10).

ADR-0097 §10 makes these a normative obligation of the triad lane and says why
they cannot live in the store's conformance suite: "every clause in the suite
below starts from a *valid* recorded grant — so an implementation that shipped
the type without the validators would pass the whole suite while admitting an
empty 'grant' that authorises nothing and still occupies §4's
one-live-grant-per-source slot, blocking the real one."

So these are construction-time, independent of any store.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import GrantScope, RiskLevel, SourceGrant

AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def grant(**overrides: object) -> SourceGrant:
    """Build a valid grant, overriding whichever field a case is about."""
    fields: dict[str, object] = {
        "id": "g-1",
        "source": "calendar",
        "scope": (GrantScope.FACET,),
        "decided_at": AT,
    }
    fields.update(overrides)
    return SourceGrant(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


# --- the scope invariants (ADR-0097 §2, §10) ---------------------------------


def test_a_grant_with_a_valid_scope_is_accepted() -> None:
    """The control, so the refusals below are not passing for free."""
    accepted = grant(scope=(GrantScope.FACET, GrantScope.INGEST))

    assert accepted.scope == (GrantScope.FACET, GrantScope.INGEST)


def test_an_empty_scope_is_refused() -> None:
    """A grant naming no use authorises nothing and would still read as a grant.

    And it is worse than inert: it would occupy the source's one live-grant slot
    (ADR-0097 §4), so the real grant could not be recorded until the empty one was
    revoked — a denial of service performed by a record the user never meant to
    make.
    """
    with pytest.raises(ValidationError, match="at least one use"):
        grant(scope=())


def test_a_repeated_use_is_refused() -> None:
    """Refused, not silently folded away (ADR-0097 §10).

    ``(FACET, FACET)`` is a caller that has lost track of what it is asking for,
    and quietly deduplicating would hide that at the one seam whose whole content
    is what the user agreed to.
    """
    with pytest.raises(ValidationError, match="at most once"):
        grant(scope=(GrantScope.FACET, GrantScope.FACET))


def test_scope_is_normalised_into_declaration_order() -> None:
    """The order is canonical however the caller supplied it.

    ADR-0097 §10 gives one reason for the ordering — "so two implementations
    serialise one grant identically", under ADR-0087's canonical wire encoding,
    which is why the field is a tuple and not a ``frozenset``. Normalising
    delivers that reason for every caller rather than only for the ones that
    already sorted; §10 enumerates the refusals it wants (empty, duplicated) and
    does not enumerate this one.
    """
    reversed_order = grant(scope=(GrantScope.INGEST, GrantScope.FACET))

    assert reversed_order.scope == (GrantScope.FACET, GrantScope.INGEST)
    assert reversed_order == grant(scope=(GrantScope.FACET, GrantScope.INGEST))


def test_the_scopes_order_survives_a_json_round_trip() -> None:
    """An invariant nothing serialises is one nothing checks (ADR-0097 §10).

    The tuple was chosen over a ``frozenset`` precisely so ADR-0087's canonical
    encoding has an order to encode, so the round trip is where that choice either
    pays or does not.
    """
    original = grant(scope=(GrantScope.FACET, GrantScope.INGEST))

    reloaded = SourceGrant.model_validate(original.model_dump(mode="json"))

    assert reloaded == original
    assert reloaded.scope == (GrantScope.FACET, GrantScope.INGEST)


def test_notify_normalises_last_because_it_was_declared_last() -> None:
    """ADR-0133 §6: the member is *appended*, so the order records when it was decided.

    Asserted through the record's own normalisation rather than off the enum,
    because that is where the order is load-bearing: two implementations must
    serialise one grant identically (ADR-0097 §10), and a member inserted rather
    than appended would move ``(FACET, INGEST)`` grants that were written down
    before it existed.
    """
    scrambled = grant(scope=(GrantScope.NOTIFY, GrantScope.INGEST, GrantScope.FACET))

    assert scrambled.scope == (GrantScope.FACET, GrantScope.INGEST, GrantScope.NOTIFY)


def test_a_scope_naming_notify_survives_a_json_round_trip_as_its_wire_value() -> None:
    """The new member crosses the wire as ``"notify"`` (ADR-0133 §6).

    The value, not merely the member: ADR-0133 §6 bumps ``PROTOCOL_VERSION``
    because "a new client's ``grant`` argument carrying ``"notify"`` is refused by
    an old hub", and that sentence is only true if this is the string the codec
    puts on the wire. ADR-0097 §10 fixes the enum as a "stable, serialisable"
    vocabulary, so the spelling is part of the contract rather than an
    implementation detail of ``StrEnum``.
    """
    original = grant(scope=(GrantScope.INGEST, GrantScope.NOTIFY))

    encoded = original.model_dump(mode="json")

    assert encoded["scope"] == ["ingest", "notify"]
    assert SourceGrant.model_validate(encoded) == original


def test_a_scope_of_notify_alone_is_accepted() -> None:
    """No member implies another, so ``NOTIFY`` alone is a well-formed scope.

    ADR-0133 §2 rules the three independent — "``NOTIFY`` implies neither
    ``FACET`` nor ``INGEST``, and neither of them implies ``NOTIFY``. A grant's
    scope may name any non-empty subset of the three" — and the sentence the
    member exists to make sayable ("do not raise it with me unprompted") needs its
    converse to be constructible too.
    """
    alone = grant(scope=(GrantScope.NOTIFY,))

    assert alone.scope == (GrantScope.NOTIFY,)


# --- the remaining field invariants ------------------------------------------


def test_a_naive_decided_at_is_refused() -> None:
    """The store is durable *and* ordered, so a naive instant is refused.

    :attr:`PermissionDecision.decided_at`'s reason, and the sharp consequence is
    the same: ``recent`` sorts on this field, so a naive value beside the aware
    ones makes every later read raise on the comparison.
    """
    with pytest.raises(ValidationError):
        grant(decided_at=datetime(2026, 7, 20, 12, 0))  # noqa: DTZ001


@pytest.mark.parametrize("field", ["id", "source"])
def test_a_blank_identifier_is_refused(field: str) -> None:
    """Both are :data:`Identifier`, which refuses a blank string.

    That is the *whole* of what the type can enforce about ``source``, and
    ADR-0097 §9 is explicit about it: ``Identifier`` cannot tell a declared
    identity from a home directory, so the grant surface admits a ``source`` only
    when it equals the ``name`` of a ``Reader`` the hub actually holds. This pins
    the floor, not the rule.
    """
    with pytest.raises(ValidationError):
        grant(**{field: "   "})


def test_a_granting_record_revokes_nothing_by_default() -> None:
    """``revokes`` defaults to ``None``, which is what makes a record a *grant*."""
    assert grant().revokes is None


def test_a_revoking_record_carries_the_pointer_and_the_transcription() -> None:
    """One type is both the act and its undoing (ADR-0097 §10).

    ``PermissionDecision.resolves``'s shape, chosen for its reason: it keeps the
    store's rows homogeneous and its wire encoding undiscriminated, where a
    separate ``GrantRevocation`` would make every query return a union ADR-0096 §5
    would then require to be explicitly discriminated on the wire.

    Nothing here checks the transcription against the grant it names — a record in
    isolation cannot see the record it points at, which is why ADR-0097 §4 puts
    that check inside ``record``, the only place both are in hand.
    """
    revocation = grant(id="r-1", revokes="g-1")

    assert revocation.revokes == "g-1"
    assert revocation.source == "calendar"


def test_a_revocation_may_predate_the_grant_it_revokes() -> None:
    """No ordering invariant lives on this type, and that is deliberate.

    ADR-0097 §4 derives liveness from ``revokes`` alone and never refuses a
    revocation for its timestamp. A validator comparing two instants here would be
    the beginning of the lockout that section refuses: a host clock corrected
    backwards would make a grant permanently unrevokable.
    """
    assert grant(id="r-1", revokes="g-1", decided_at=AT - timedelta(days=365)).revokes == "g-1"


def test_an_unknown_field_is_refused() -> None:
    """``extra="forbid"``, as every boundary-crossing record in this file is."""
    with pytest.raises(ValidationError):
        grant(expires_at=AT)


# --- the enum (ADR-0097 §2, §10) ---------------------------------------------


def test_grant_scope_has_exactly_the_three_ratified_uses() -> None:
    """Three members, each with a consumer decided, and no placeholder among them.

    ``INGEST`` gates ``orchestration``'s ingestion stage, ``FACET`` gates the
    ``context`` adapter ADR-0096 §4 unblocked, and ``NOTIFY`` gates a producer's
    read (ADR-0133 §1) — whose consumer is ADR-0130's producer class, decided and
    sequenced rather than imagined, which is what keeps this from being surface
    with no consumer (ADR-0045 §1, ADR-0028 §7). Content-level scope is still
    deferred with the condition that fires it (ADR-0097 §12, ADR-0133 §7), so a
    fourth member arriving here is a decision, not a tidy-up.

    **The list is asserted in order, not as a set**, because declaration order is
    what :data:`~ai_assistant.core.types._SCOPE_ORDER` is read off and what
    :attr:`SourceGrant.scope` normalises to. ADR-0133 §6 rules the member
    "**appended after ``INGEST``**" so "the order stays a record of when each use
    was decided" — inserting it anywhere else would silently rewrite the
    serialised order of every existing grant that names two uses.
    """
    assert list(GrantScope) == [GrantScope.FACET, GrantScope.INGEST, GrantScope.NOTIFY]
    assert [use.value for use in GrantScope] == ["facet", "ingest", "notify"]


def test_grant_scope_is_a_plain_str_enum_and_carries_no_severity_order() -> None:
    """Not a ``_SeverityScale``, and the difference is a decision (ADR-0097 §10).

    ``PermissionOutcome`` is ordered because outcomes are *ranked* by severity and
    ``_SeverityScale`` combines them with ``max``. Uses of a source are not
    comparable — reading for a facet is not "less" than reading for ingestion — so
    an order would invite a ``max()`` that means nothing. ADR-0133 §2 keeps that
    holding at three: "a third use is not more comparable than the second was",
    and it forbids reading a rank off the declaration order the scope normalises
    to, which is a serialisation convention and nothing else.

    What is asserted is the *absence of the scale*, not the absence of ``str``'s
    own comparisons: ``StrEnum`` members are strings and always compare, which is
    exactly why the canonical order on :attr:`SourceGrant.scope` is taken from the
    declaration rather than from the values. ``RiskLevel`` is the control, so this
    is a statement about a difference rather than about a class in isolation.
    """
    assert isinstance(GrantScope.FACET, str)
    assert GrantScope.__lt__ is str.__lt__
    assert RiskLevel.__lt__ is not str.__lt__
