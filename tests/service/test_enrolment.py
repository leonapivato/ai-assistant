"""The enrolment record and the registry over it (ADR-0124 §6, §7, §8).

The listener is tested in ``test_remote_listener.py``. What is here is what the
record itself promises: one live enrolment per device, a revocation that is
recorded rather than erased, a verifier the credential cannot be read back from,
and a rotation that has no intermediate state.
"""

from __future__ import annotations

import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.service.enrolment import (
    ENROLMENTS_FILENAME,
    DeviceRegistry,
    EnrolmentStore,
    Refusal,
)
from ai_assistant.wire.credential import mint_credential, verifier_for

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_LAPTOP: Final = "nLAPTOP1CNTRL"
_PHONE: Final = "nPHONE22CNTRL"
_HUB: Final = "nHUBAAAACNTRL"
_MOMENT: Final = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[EnrolmentStore]:
    """One enrolment record inside a temporary data directory."""
    opened = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def registry(store: EnrolmentStore) -> DeviceRegistry:
    """The live view over it, with this hub's own overlay identity."""
    return DeviceRegistry(store, hub_identity=_HUB)


def test_the_record_lives_inside_the_data_directory_and_is_owner_only(tmp_path: Path) -> None:
    """ADR-0124 §6 puts it "inside ``data_dir`` under ADR-0083's layout", and
    ADR-0004 §4 is what fixes its mode.

    The mode is read off the file the store actually created rather than off a
    constant, so a creation that ran under a permissive umask and forgot the
    ``chmod`` fails here rather than leaving a Tier 1 record other users can open.
    """
    opened = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    try:
        assert opened.path.parent == tmp_path
        assert stat.S_IMODE(opened.path.stat().st_mode) == 0o600
    finally:
        opened.close()


def test_an_enrolment_discloses_the_credential_and_the_hub_identity_together(
    registry: DeviceRegistry,
) -> None:
    """ADR-0124 §6: "the two values travel together: the client holds both, and
    holding the credential without the hub identity is an incomplete enrolment the
    client refuses to connect on".

    Returned from one act rather than discovered separately, because an owner who
    has to go and find the second value is an owner who will hand over only the
    first.
    """
    minted = registry.enrol(_LAPTOP, now=_MOMENT)
    assert minted.hub_identity == _HUB
    assert minted.credential
    assert minted.enrolment.overlay_identity == _LAPTOP
    assert minted.enrolment.is_live
    assert not minted.rotated


def test_the_hub_keeps_a_verifier_and_never_the_credential(
    registry: DeviceRegistry, store: EnrolmentStore, tmp_path: Path
) -> None:
    """ADR-0124 §6: "the hub retains only a verifier from which the credential
    cannot be recovered, so the hub holds no device's Tier 0 secret at rest".

    Asserted against the **bytes on disk** rather than against the object, because
    an implementation that kept the credential in a column would still return the
    right verifier from its API. The file is read whole: a secret written anywhere
    in it — a second column, a journal of the insert — fails here.
    """
    minted = registry.enrol(_LAPTOP, now=_MOMENT)
    store.close()
    written = (tmp_path / ENROLMENTS_FILENAME).read_bytes()
    assert minted.credential.encode() not in written
    assert verifier_for(minted.credential).encode() in written


def test_the_record_survives_a_restart(tmp_path: Path) -> None:
    """ADR-0124 §6: the record is "durable state the hub owns… surviving a hub
    restart", and §11's step 8 is the operator's version of this check.

    Both halves are exercised — an enrolment still admits and a revocation still
    refuses — because a store that dropped its revocations on reopen would readmit
    a device the owner expelled, which is the worse of the two failures.
    """
    first = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    live = DeviceRegistry(first, hub_identity=_HUB)
    kept = live.enrol(_LAPTOP, now=_MOMENT)
    live.enrol(_PHONE, now=_MOMENT)
    live.revoke(_PHONE, now=_MOMENT + timedelta(minutes=1))
    first.close()

    second = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    try:
        reopened = DeviceRegistry(second, hub_identity=_HUB)
        assert reopened.verify(_LAPTOP, kept.credential).enrolment_id is not None
        assert reopened.verify(_PHONE, kept.credential).refusal is Refusal.REVOKED
    finally:
        second.close()


def test_the_two_facts_are_both_required(registry: DeviceRegistry) -> None:
    """ADR-0124 §7: "the overlay identity §4 obtained names a device whose enrolment
    is live, and the frame's credential member verifies against that device's
    verifier. **Neither fact admits a connection on its own.**"

    The three cases are the two halves and the pair: a live device with the wrong
    credential, an unenrolled device holding a real credential minted for another,
    and the device that holds both.
    """
    laptop = registry.enrol(_LAPTOP, now=_MOMENT)
    assert registry.verify(_LAPTOP, laptop.credential).enrolment_id is not None
    assert registry.verify(_LAPTOP, mint_credential()).refusal is Refusal.CREDENTIAL
    assert registry.verify(_PHONE, laptop.credential).refusal is Refusal.NOT_ENROLLED


def test_the_three_refusals_are_distinguished(registry: DeviceRegistry) -> None:
    """ADR-0124 §7: a refusal "distinguishes an unenrolled device, a revoked device,
    and a credential that did not verify".

    "An owner who cannot tell 'I never enrolled this laptop' from 'I revoked it last
    week' from 'I pasted the wrong string' is ADR-0083's ruling 4 failure." The
    login-surface reflex of one flat "no" would pass every other test in this file.
    """
    laptop = registry.enrol(_LAPTOP, now=_MOMENT)
    assert registry.verify(_PHONE, laptop.credential).refusal is Refusal.NOT_ENROLLED
    assert registry.verify(_LAPTOP, mint_credential()).refusal is Refusal.CREDENTIAL
    registry.revoke(_LAPTOP, now=_MOMENT + timedelta(minutes=1))
    assert registry.verify(_LAPTOP, laptop.credential).refusal is Refusal.REVOKED


def test_a_revocation_is_recorded_rather_than_erasing_the_enrolment(
    registry: DeviceRegistry,
) -> None:
    """ADR-0124 §6: "a revocation is recorded rather than erasing the enrolment it
    revokes, so the record says what the owner actually decided and when".

    A store that deleted the row would satisfy every admission test in this file and
    lose the one thing the record exists to hold.
    """
    registry.enrol(_LAPTOP, now=_MOMENT)
    later = _MOMENT + timedelta(days=3)
    assert registry.revoke(_LAPTOP, now=later)

    ((recorded,), total) = registry.enrolments()
    assert total == 1
    assert recorded.overlay_identity == _LAPTOP
    assert recorded.enrolled_at == _MOMENT
    assert recorded.revoked_at == later
    assert not recorded.is_live


def test_revoking_a_device_that_holds_nothing_changes_nothing(registry: DeviceRegistry) -> None:
    """Not an error: the owner asked for a state that already holds.

    Reported as ``False`` so the surface can say so rather than claiming an act it
    did not perform — the same honesty ADR-0124 §8 requires of the delete surface.
    """
    assert registry.revoke(_LAPTOP, now=_MOMENT) is False
    assert registry.enrolments() == ([], 0)


def test_re_enrolling_rotates_in_one_act_and_leaves_one_live_enrolment(
    registry: DeviceRegistry,
) -> None:
    """ADR-0124 §6: "a **single act** that revokes the existing enrolment… and mints
    the replacement; the two halves are not separable, and no intermediate state has
    two live enrolments for one identity, or none".

    "If an identity could carry two live enrolments, 'its credential' would name two
    values and an implementation revoking the record it happened to find would leave
    the other one admitting the very device the owner just expelled."
    """
    first = registry.enrol(_LAPTOP, now=_MOMENT)
    second = registry.enrol(_LAPTOP, now=_MOMENT + timedelta(days=1))

    assert second.rotated
    assert second.credential != first.credential
    assert registry.verify(_LAPTOP, second.credential).enrolment_id == second.enrolment.enrolment_id
    assert registry.verify(_LAPTOP, first.credential).refusal is Refusal.CREDENTIAL
    # Newest first, so the live replacement leads and the revoked original follows.
    assert [one.is_live for one in registry.enrolments()[0]] == [True, False]


def test_a_revoked_credential_is_never_reinstated(registry: DeviceRegistry) -> None:
    """ADR-0124 §8: "Re-enrolling a device that was revoked mints a new credential
    under §6 and is a new enrolment. A revoked credential is never reinstated."

    §11's step 6 checks the same thing on two machines: "re-enrolling mints a new
    credential against which the old one still verifies against nothing".
    """
    first = registry.enrol(_LAPTOP, now=_MOMENT)
    registry.revoke(_LAPTOP, now=_MOMENT + timedelta(minutes=1))
    second = registry.enrol(_LAPTOP, now=_MOMENT + timedelta(minutes=2))

    assert registry.verify(_LAPTOP, first.credential).refusal is Refusal.CREDENTIAL
    assert registry.verify(_LAPTOP, second.credential).enrolment_id is not None


def test_the_database_itself_refuses_two_live_enrolments_for_one_device(
    store: EnrolmentStore,
) -> None:
    """§6's uniqueness rule is in the schema, not only in the code above it.

    An implementation that reached the insert without the revoking update — a future
    edit, a second writer — is refused by the partial unique index rather than
    quietly producing the state §8's promise cannot be kept over.
    """
    store.enrol(_LAPTOP, verifier=verifier_for(mint_credential()), now=_MOMENT)
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(  # the schema's own guarantee, reached directly
            "INSERT INTO enrolments (overlay_identity, verifier, enrolled_at, revoked_at) "
            "VALUES (?, ?, ?, NULL)",
            (_LAPTOP, "sha256:second", _MOMENT.isoformat()),
        )


def test_a_revoked_identity_may_be_enrolled_again(store: EnrolmentStore) -> None:
    """The discriminating half of the index: uniqueness is over the *live* rows.

    A plain unique index would satisfy the test above and make re-enrolment
    impossible, which ADR-0124 §8 requires to work.
    """
    store.enrol(_LAPTOP, verifier=verifier_for(mint_credential()), now=_MOMENT)
    store.revoke(_LAPTOP, now=_MOMENT + timedelta(minutes=1))
    store.enrol(_LAPTOP, verifier=verifier_for(mint_credential()), now=_MOMENT + timedelta(hours=1))
    rows, total = store.recent_enrolments(limit=10)
    assert total == 2
    assert [one.is_live for one in rows] == [True, False]


def test_liveness_is_keyed_to_the_enrolment_a_connection_claimed(
    registry: DeviceRegistry,
) -> None:
    """ADR-0124 §8's compare-and-claim, at the registry.

    A rotation must stop a connection admitted under the previous enrolment, which is
    §6's "leaving its credential verifying against nothing" seen from the connection.
    A liveness test keyed only on the *identity* would keep that connection alive
    across a rotation, and §11's step 9 is where that failure shows.
    """
    first = registry.enrol(_LAPTOP, now=_MOMENT)
    held = first.enrolment.enrolment_id
    assert registry.is_live(_LAPTOP, held)

    second = registry.enrol(_LAPTOP, now=_MOMENT + timedelta(minutes=1))
    assert not registry.is_live(_LAPTOP, held)
    assert registry.is_live(_LAPTOP, second.enrolment.enrolment_id)

    registry.revoke(_LAPTOP, now=_MOMENT + timedelta(minutes=2))
    assert not registry.is_live(_LAPTOP, second.enrolment.enrolment_id)


def test_an_expulsion_is_announced_for_a_revocation_and_for_a_rotation(
    registry: DeviceRegistry,
) -> None:
    """ADR-0124 §8: "revoking a device closes any connection that device currently
    holds", and §6's rotation revokes "with §8's full finality".

    Both are announced, and the reason differs, because §11's step 9 checks the
    rotation case specifically: "enrolling the second device again while it is
    enrolled and connected closes that connection".
    """
    expelled: list[tuple[str, str]] = []
    registry.when_expelled(lambda identity, reason: expelled.append((identity, reason)))

    registry.enrol(_LAPTOP, now=_MOMENT)
    assert expelled == []
    registry.enrol(_LAPTOP, now=_MOMENT + timedelta(minutes=1))
    registry.revoke(_LAPTOP, now=_MOMENT + timedelta(minutes=2))
    assert expelled == [(_LAPTOP, "rotated"), (_LAPTOP, "revoked")]


def test_one_device_is_not_another(registry: DeviceRegistry) -> None:
    """ADR-0124 §5: "admission is decided per device and revocation acts on a device".

    Revoking one leaves the other untouched — the property a registry keyed on
    something coarser than the overlay identity would lose.
    """
    laptop = registry.enrol(_LAPTOP, now=_MOMENT)
    phone = registry.enrol(_PHONE, now=_MOMENT)
    registry.revoke(_LAPTOP, now=_MOMENT + timedelta(minutes=1))

    assert registry.verify(_LAPTOP, laptop.credential).refusal is Refusal.REVOKED
    assert registry.verify(_PHONE, phone.credential).enrolment_id is not None
