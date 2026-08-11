"""The canonical notification fakes pass their shared conformance suites.

This is what lets other subsystems trust
:class:`~ai_assistant.testing.FakeNotificationPolicy`,
:class:`~ai_assistant.testing.FakeNotificationStore` and
:class:`~ai_assistant.testing.FakeNotificationWriter` as stand-ins: they are held
to the contract ADR-0130 §9 states, by the same suites any later implementation
will be held to.

Beside the bindings are the few properties that are the *fakes' own* rather than
the contract's — that the store's tuning guard refuses what a real store must
refuse, and that its clock guard raises the store's own error rather than the
raw ``ValueError`` ``core`` raises.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from notification_contract import (
    NOW,
    NotificationPolicyContract,
    NotificationStoreContract,
    NotificationWriterContract,
    StoreFactory,
)

from ai_assistant.core.errors import NotificationStoreError
from ai_assistant.testing import (
    FakeNotificationPolicy,
    FakeNotificationStore,
    FakeNotificationWriter,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import (
        NotificationPolicy,
        NotificationStore,
        NotificationWriter,
    )


def _fixed_now() -> datetime:
    return NOW


class TestFakeNotificationPolicyContract(NotificationPolicyContract):
    """Runs FakeNotificationPolicy through the shared NotificationPolicy suite."""

    @pytest.fixture
    def policy(self) -> NotificationPolicy:
        return FakeNotificationPolicy()

    @pytest.fixture
    def policy_in(self) -> Callable[[str], NotificationPolicy]:
        def build(timezone: str) -> NotificationPolicy:
            return FakeNotificationPolicy(timezone=timezone)

        return build


class TestFakeNotificationStoreContract(NotificationStoreContract):
    """Runs FakeNotificationStore through the shared NotificationStore suite."""

    @pytest.fixture
    def store(self) -> NotificationStore:
        return FakeNotificationStore(now=_fixed_now)

    @pytest.fixture
    def factory(self) -> StoreFactory:
        """Build subjects over the injected seams.

        A function rather than the class itself, deliberately: the class object
        *structurally satisfies* ``NotificationStore`` (its methods are
        attributes of it), so handing it over would look to the Protocol-triad
        check like a second subject standing beside the fake.
        """

        def build(
            *,
            now: Callable[[], datetime],
            retention: timedelta | None = timedelta(days=7),
            cap: int = 100,
        ) -> NotificationStore:
            return FakeNotificationStore(now=now, retention=retention, cap=cap)

        return build

    @pytest.fixture
    def policy(self) -> NotificationPolicy:
        return FakeNotificationPolicy()


class TestFakeNotificationWriterContract(NotificationWriterContract):
    """Runs FakeNotificationWriter through the shared NotificationWriter suite."""

    @pytest.fixture
    def writer(self) -> NotificationWriter:
        return FakeNotificationWriter(
            store=FakeNotificationStore(now=_fixed_now), policy=FakeNotificationPolicy()
        )

    def store_of(self, writer: NotificationWriter) -> NotificationStore:
        assert isinstance(writer, FakeNotificationWriter)
        return writer.store


@pytest.mark.parametrize(
    "cap",
    [0, -1, 2**63, 1.5, True],
    ids=["zero", "negative", "over-wide", "a-float", "a-bool"],
)
def test_the_fake_refuses_a_cap_the_store_cannot_work_under(cap: object) -> None:
    """A cap of 0 is at capacity before its first admission (ADR-0130 §7).

    Refused at construction in the ``_check_tuning`` shape ADR-0022 §4a ratified,
    and refused by the *fake* too, because a fake looser than the contract
    certifies consumers a real store rejects.
    """
    with pytest.raises(ValueError, match="cap"):
        FakeNotificationStore(now=_fixed_now, cap=cap)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "retention",
    [timedelta(0), -timedelta(days=1), "P7D"],
    ids=["zero", "negative", "not-a-duration"],
)
def test_the_fake_refuses_a_retention_the_store_cannot_work_under(retention: object) -> None:
    """A non-positive retention purges a record the instant it ceases."""
    with pytest.raises(ValueError, match="retention"):
        FakeNotificationStore(now=_fixed_now, retention=retention)  # type: ignore[arg-type]


async def test_the_fake_reports_an_unusable_clock_as_the_stores_own_error() -> None:
    """Not the raw ``ValueError`` ``core`` raises (ADR-0026 §4, §7).

    A fake that leaked it would certify a consumer's error handling against
    behaviour it will never meet in production.
    """
    naive = NOW.replace(tzinfo=None)  # what a bad clock returns
    store = FakeNotificationStore(now=lambda: naive)

    with pytest.raises(NotificationStoreError):
        await store.due()


async def test_a_fresh_fake_holds_nothing_from_a_prior_instance() -> None:
    """Two fakes are two stores: a consumer's test must not inherit another's."""
    from notification_contract import candidate  # noqa: PLC0415 — a helper, not a fixture

    policy = FakeNotificationPolicy()
    await FakeNotificationStore(now=_fixed_now).admit(candidate(), policy=policy)

    assert await FakeNotificationStore(now=_fixed_now).export() == []


def test_the_fakes_clock_default_is_the_wall_clock() -> None:
    """A fake defaulting to a fixed instant would certify a frozen deployment."""
    store = FakeNotificationStore()

    assert datetime.now(UTC) - store._clock() < timedelta(seconds=5)
