"""The canonical FakeDeferralStore passes the shared conformance suite.

This is what lets other subsystems trust
``ai_assistant.testing.FakeDeferralStore`` as a stand-in for a real store: it is
held to the same contract as ``SqliteDeferralStore``. Beside the binding are the
few properties that are the *fake's own* rather than the contract's — that its
tuning guard refuses what the production store refuses, that its clock guard
raises the error the production store raises, and that its token source is the
``secrets``-backed default rather than something a consumer's test could predict.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from deferral_store_contract import (
    DeferralStoreContract,
    DeferralStoreFactory,
    ScriptedTokens,
    _admit,
)

from ai_assistant.core.errors import DeferralStoreError
from ai_assistant.testing.cancellation import SuspendedMidWrite
from ai_assistant.testing.deferrals import FakeDeferralStore, _secret_claim_id

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from ai_assistant.core.protocols import DeferralStore

_TTL = timedelta(days=7)
_LIMIT = 200


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


class TestFakeDeferralStoreContract(DeferralStoreContract):
    """Runs FakeDeferralStore through the shared DeferralStore conformance suite."""

    @pytest.fixture
    def store(self) -> DeferralStore:
        return FakeDeferralStore(now=_fixed_now)

    @pytest.fixture
    def factory(self) -> DeferralStoreFactory:
        """Build subjects over the injected seams.

        A function rather than the class itself, deliberately: the class object
        *structurally satisfies* ``DeferralStore`` (its methods are attributes of
        it), so handing it over would look to the Protocol-triad check like a second
        subject standing beside the fake — which is exactly what that check refuses.
        """

        def build(
            *,
            now: Callable[[], datetime],
            retention: timedelta | None,
            queue_limit: int,
            new_claim_id: Callable[[], str],
        ) -> DeferralStore:
            return FakeDeferralStore(
                now=now,
                retention=retention,
                queue_limit=queue_limit,
                new_claim_id=new_claim_id,
            )

        return build

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
        *,
        now: Callable[[], datetime],
        retention: timedelta | None = _TTL,
        queue_limit: int = _LIMIT,
        new_claim_id: Callable[[], str] | None = None,
    ) -> AsyncIterator[SuspendedMidWrite[DeferralStore]]:
        """The fake models the resource it does not really own (ADR-0060 §3).

        Dicts need no serialising, so without this the canonical fake could only opt
        out — and the compare-and-set clauses would run solely against the
        ``sqlite3`` store that already holds the invariant. Every operation passes
        through the *one* modelled resource, so ``arm`` ignores which operation it is
        handed: what the parametrised cases buy here is that the same ``held()`` path
        is driven from every angle, and they earn their keep on the ``sqlite3`` store
        where each operation is a separate lock site. Nothing to dispose of, hence
        the bare yield.
        """
        realised = FakeDeferralStore(
            now=now,
            retention=retention,
            queue_limit=queue_limit,
            new_claim_id=new_claim_id or ScriptedTokens([]),
        )
        yield SuspendedMidWrite(
            store=realised,
            log=realised.resource_log,
            arm=lambda _operation: realised.suspend_next_write(),
        )


def test_the_fake_defaults_to_the_secrets_backed_token_source() -> None:
    """A fake that defaulted to a counter would certify a guessable capability.

    ``interrupted`` publishes every claimed question's id to any caller, so a
    predictable token is one a caller can derive from a read — and a consumer's test
    against such a fake would pass while the production store's own default is the
    only thing standing between that read and someone else's claim (ADR-0078 §2).
    """
    assert FakeDeferralStore(now=_fixed_now)._new_claim_id is _secret_claim_id


@pytest.mark.parametrize(
    "queue_limit",
    [0, -1, 2**63, 1.5, True],
    ids=["zero", "negative", "over-wide", "a-float", "a-bool"],
)
def test_the_fake_refuses_a_cap_the_queue_cannot_work_under(queue_limit: object) -> None:
    """A cap of 0 refuses every question while the system reports health (§7).

    Refused at construction in the ``_check_tuning`` shape ADR-0022 §4a ratified,
    and refused by the *fake* too, because a fake looser than the contract certifies
    consumers the real store rejects.
    """
    with pytest.raises(ValueError, match="queue_limit"):
        FakeDeferralStore(now=_fixed_now, queue_limit=queue_limit)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "retention",
    [timedelta(0), -timedelta(days=1), "P7D"],
    ids=["zero", "negative", "not-a-duration"],
)
def test_the_fake_refuses_a_lifetime_the_queue_cannot_work_under(retention: object) -> None:
    with pytest.raises(ValueError, match="retention"):
        FakeDeferralStore(now=_fixed_now, retention=retention)  # type: ignore[arg-type]


async def test_a_fresh_fake_holds_nothing_from_a_prior_instance() -> None:
    """Two fakes are two queues: a consumer's test must not inherit another's state."""
    await _admit(FakeDeferralStore(now=_fixed_now), "d1")

    assert await FakeDeferralStore(now=_fixed_now).export() == []


async def test_the_fake_reports_an_unusable_clock_as_the_stores_own_error() -> None:
    """Not the raw ``ValueError`` ``core`` raises (ADR-0026 §4, §7).

    A fake that leaked it would certify a consumer's error handling against
    behaviour it will never meet in production.
    """
    naive = datetime(2026, 6, 1, tzinfo=UTC).replace(tzinfo=None)  # what a bad clock returns
    store = FakeDeferralStore(now=lambda: naive)

    with pytest.raises(DeferralStoreError):
        await store.pending()
