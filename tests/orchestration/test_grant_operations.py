"""The grant operations, over the parts no shared suite can reach (ADR-0102 §7).

`tests/orchestration/assistant_engine_contract.py` holds every clause that binds
**every** implementation, and that is where §4's admission rules, §5's minting and
sweep, and §10's local refusals live. What is left for this module is the state a
conforming implementation may be *put into* by a composition root and that the
surface has no operation to produce: a reader whose declared name is not in
canonical form, a configured location with no UTF-8 encoding, and two readers
declaring one identity.

**Those are the ones with no user-facing operation and therefore no suite clause.**
Which sources exist is a property of what the composition root built (§7); nothing
on the engine surface adds to it, and nothing may — a surface that could would be
the free-text route into the store ADR-0097 §1 and §9 exist to close, arriving by
another name. So the only way to reach these cases is to construct the operations
object directly, which is what this module does.

Named ``test_grant_operations`` rather than ``test_grants``: the ``tests/`` tree
carries no ``__init__.py``, so pytest imports each test module by its basename and
``tests/permissions/test_grants.py`` already owns that one. The longer name also
says which of the two subjects this is — the operations, not the store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import UngrantableSourceError
from ai_assistant.core.types import GrantScope
from ai_assistant.orchestration import GrantOperations, HeldSource
from ai_assistant.testing import FakeSourceGrantStore

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

AT = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)

#: A pathname with no UTF-8 encoding. Linux pathnames are bytes and Python surfaces
#: an undecodable one through ``surrogateescape``, so ``str(path)`` really can hold
#: a lone surrogate — which is why ADR-0102 §6 calls its encoding clauses "a real
#: case rather than a defensive one".
UNWRITABLE_PATH = "/srv/\udce9calendar.ics"


def _ids() -> Callable[[], str]:
    """Ids that differ per call, so a second record is never a duplicate."""
    numbers = count(1)
    return lambda: f"grant-{next(numbers)}"


def _operations(sources: Sequence[HeldSource]) -> GrantOperations:
    """The operations over a fake store, holding exactly ``sources``."""
    return GrantOperations(
        store=FakeSourceGrantStore(),
        sources=sources,
        id_factory=_ids(),
        clock=lambda: AT,
    )


# --- §7: what the composition root may and may not supply --------------------


def test_two_readers_declaring_one_identity_deduplicate_to_one_entry() -> None:
    """§7: several instances of one source contribute one entry.

    This is the tree's actual state rather than a hypothetical: ``build_engine``
    builds **two** ``CalendarReader`` instances, because ADR-0093 §7 bounds a reader
    at one outstanding worker per instance and ADR-0096 §5 refuses to let a
    scheduled ingestion read suppress the request-path facet. Both are configured
    from one path, so they agree — and the enumeration must show one source, not the
    same source twice.
    """
    operations = _operations(
        [
            HeldSource("calendar", location="/srv/calendar.ics"),
            HeldSource("calendar", location="/srv/calendar.ics"),
        ]
    )
    assert len(operations._sources) == 1


def test_two_readers_at_differing_locations_refuse_to_build() -> None:
    """§7: a composition supplying two that differ is a configuration error.

    **The failure this closes is invisible from every other angle.** Two conforming
    readers named ``calendar`` at different paths would produce one entry showing
    one location, while a grant on that identity authorised reads of *both* — §6's
    informed-consent property defeated by a wiring detail, with nothing about the
    resulting record looking wrong. Refusing to build is the cheap half of the fix;
    the other candidate, giving each instance its own grantable identity, is
    foreclosed by ADR-0093 §7 and ADR-0097 §9a's named precondition.
    """
    with pytest.raises(ValueError, match="differing"):
        _operations(
            [
                HeldSource("calendar", location="/srv/one.ics"),
                HeldSource("calendar", location="/srv/two.ics"),
            ]
        )


def test_the_refusal_to_build_names_no_path() -> None:
    """§4: no refusal raised by these operations carries a filesystem path.

    Asserted separately from the refusal itself because the two are independent —
    a message that named both paths would satisfy the test above and breach ADR-0004
    §5, and the failure would be a Tier 1 pathname in whatever the operator's
    supervisor captures at start-up.
    """
    with pytest.raises(ValueError, match="differing") as caught:
        _operations(
            [
                HeldSource("calendar", location="/srv/one.ics"),
                HeldSource("calendar", location="/srv/two.ics"),
            ]
        )
    assert "/srv/one.ics" not in str(caught.value)
    assert "/srv/two.ics" not in str(caught.value)


def test_a_source_with_no_configured_location_is_still_grantable() -> None:
    """§6: ``location`` is ``None`` **only** where nothing is configured.

    ADR-0097 §9a's disclosure obligation is vacuous in that case — there is nothing
    to show — so the source is grantable with the field absent. This is the case a
    client must be able to distinguish from the *other* absence, which is why it is
    pinned rather than left to follow from the type.
    """
    operations = _operations([HeldSource("notes")])
    assert operations._sources["notes"].location is None


# --- §4: an inadmissible declared name ---------------------------------------


async def test_a_reader_whose_declared_name_is_not_canonical_is_not_enumerated() -> None:
    """§4, and the enumeration is not refused for it.

    A non-canonical declared name is "a defect in a reader, not a state a user can
    act on" (ADR-0102 §3), so it is omitted rather than listed as unavailable — the
    ``grantable: bool`` field §3 refused as surface with no consumer. The other
    sources still answer, which is the half that keeps one broken reader from taking
    the whole enumeration down.
    """
    operations = _operations(
        [HeldSource("  calendar  ", location="/srv/one.ics"), HeldSource("notes")]
    )
    assert [one.source for one in await operations.grantable_sources()] == ["notes"]


async def test_granting_a_reader_whose_declared_name_is_not_canonical_is_refused() -> None:
    """§4, and the refusal **names that reader**.

    Reachable only because the caller's ``source`` had to survive
    ``NonBlankEncodableText`` to equal a held name at all — so the name is
    encodable and non-blank, and the one condition left to fail is canonical form.
    Naming it is safe by construction: ADR-0093 §7 makes a reader's identity a
    *declared constant*, which "cannot carry personal data at all".
    """
    operations = _operations([HeldSource("  calendar  ", location="/srv/one.ics")])
    with pytest.raises(UngrantableSourceError, match="calendar"):
        await operations.grant("  calendar  ", scope=[GrantScope.FACET])
    assert await operations.recent_grants(limit=50) == ()


async def test_a_refusal_for_an_unknown_source_names_no_value_at_all() -> None:
    """§4: one raised because no held reader declares the value names nothing.

    ADR-0097 §9 forbids a refusal echoing "no caller-supplied string beyond what the
    client already sent", "so a mistyped value cannot reach the log (ADR-0004 §5)".
    Returning nothing rather than the value to the sender is strictly stronger and
    costs a client nothing: it still has what it sent, and the useful remedy is
    ``grantable_sources``.
    """
    operations = _operations([HeldSource("calendar", location="/srv/one.ics")])
    with pytest.raises(UngrantableSourceError) as caught:
        await operations.grant("alice@example.com", scope=[GrantScope.FACET])
    assert "alice@example.com" not in str(caught.value)


# --- §6: a configured location that cannot be shown --------------------------


async def test_a_source_whose_location_has_no_encoding_is_not_enumerated() -> None:
    """§6: it is omitted, and enumeration is not refused for it.

    Without a rule here a deployment with such a path would find
    ``grantable_sources`` raising a ``ValidationError`` from inside the operation —
    enumeration broken by a path the user cannot see and did not ask about.
    """
    operations = _operations(
        [HeldSource("calendar", location=UNWRITABLE_PATH), HeldSource("notes")]
    )
    assert [one.source for one in await operations.grantable_sources()] == ["notes"]


async def test_a_source_whose_location_has_no_encoding_cannot_be_granted() -> None:
    """§6: it fails **closed**, and degrading ``location`` to ``None`` was refused.

    The first draft of §6 degraded it and granted anyway, which made ADR-0097 §9a's
    two halves contradict each other: the source would be offered while no
    conforming client could ever grant it under §6's third clause, and a client that
    ignored that clause would mint precisely the uninformed grant §9a exists to
    prevent. Refusing is ADR-0097 §8's posture, and the remedy is an operator act on
    the operator's own filesystem.
    """
    operations = _operations([HeldSource("calendar", location=UNWRITABLE_PATH)])
    with pytest.raises(UngrantableSourceError, match="calendar"):
        await operations.grant("calendar", scope=[GrantScope.FACET])
    assert await operations.recent_grants(limit=50) == ()


async def test_the_refusal_for_an_unshowable_location_carries_no_path() -> None:
    """§4 and §6: the refusal and the log line name the reader and carry no path.

    Asserted on the message rather than trusted, because the value being kept out is
    exactly the thing the operation was just handed and the tempting message is the
    one that names it.
    """
    operations = _operations([HeldSource("calendar", location=UNWRITABLE_PATH)])
    with pytest.raises(UngrantableSourceError) as caught:
        await operations.grant("calendar", scope=[GrantScope.FACET])
    assert "/srv/" not in str(caught.value)


# --- the enumeration's own content -------------------------------------------


async def test_the_enumeration_carries_the_location_and_the_live_grant() -> None:
    """§3 and §6: three fields, and ``live`` computed hub-side from the store.

    The discriminating case for the enumeration, without which the omissions above
    would pass against an implementation that enumerated nothing.
    """
    operations = _operations([HeldSource("calendar", location="/srv/one.ics")])
    before = await operations.grantable_sources()
    assert before[0].location == "/srv/one.ics"
    assert before[0].live is None

    await operations.grant("calendar", scope=[GrantScope.INGEST])
    after = await operations.grantable_sources()
    assert after[0].live is not None
    assert after[0].live.scope == (GrantScope.INGEST,)


async def test_the_location_reaches_no_recorded_grant() -> None:
    """§6: ``location`` is carried by one response and stored by none.

    ADR-0097 §9a enumerates where it may not come to rest — "not in a log, not on
    any ``SourceGrant``, not in a grant listing, not in ``recent`` and not in
    ``export``" — and every entry on that list is durable or is a read of durable
    state. A ``SourceGrant`` has no field for it, so this asserts the property the
    type already delivers; it is written because the field a later lane would reach
    for is exactly the one this forbids.
    """
    operations = _operations([HeldSource("calendar", location="/srv/one.ics")])
    recorded = await operations.grant("calendar", scope=[GrantScope.FACET])
    assert "/srv/one.ics" not in recorded.model_dump_json()
    page = await operations.recent_grants(limit=50)
    assert all("/srv/one.ics" not in record.model_dump_json() for record in page)
