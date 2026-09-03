"""FakeFetcher passes the shared Fetcher suite, plus the clauses only it can.

The binding is the point of a *shared* suite: a clause either binds every
implementation or binds none, so the canonical fake is held to exactly what the
concrete fetcher is held to (``tests/readers/test_local_file_fetcher.py``).

Below the binding are the two things this file can decide and the suite cannot: that
the fake's own **scripting surface** refuses a script it could only honour by
breaking its own contract, and that the refusal script reaches every
:class:`~ai_assistant.core.types.FetchRefusal` member — which is what a consumer
needs in order to drive ADR-0230 §6's disposition without a filesystem.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from fetcher_contract import ClockedFetcher, Dial, FetcherContract, GatedFetch, wall_of

from ai_assistant.core.clock import ClockReadingError
from ai_assistant.core.types import FetchRefusal
from ai_assistant.testing import DEFAULT_FETCHER_NAME, FakeFetcher

if TYPE_CHECKING:
    from ai_assistant.core.protocols import Fetcher

#: A root with two files, so the suite's ordering-sensitive and multi-entry clauses
#: have something to quantify over.
_ROOT = {"newest.md": "# alpha\nfirst", "older.txt": "beta"}

#: The TTL the clocked subject is built with, chosen distinct from ADR-0230 §4's
#: five-minute default so a case stepping "past the TTL" is stepping past *this*
#: subject's and not past a constant that happens to agree.
_TTL = timedelta(minutes=3)


class TestFakeFetcherContract(FetcherContract):
    """Runs FakeFetcher through the shared Fetcher conformance suite."""

    @pytest.fixture
    def fetcher(self) -> Fetcher:
        return FakeFetcher(_ROOT)

    @pytest.fixture
    def empty_fetcher(self) -> Fetcher:
        return FakeFetcher()

    def clocked(self) -> ClockedFetcher:
        wall = Dial(datetime(2026, 3, 1, 9, 0, tzinfo=UTC).timestamp())
        monotonic = Dial(0)
        return ClockedFetcher(
            fetcher=FakeFetcher(
                _ROOT,
                now=lambda: wall_of(wall),
                monotonic=lambda: int(monotonic.read()),
                listing_ttl=_TTL,
            ),
            ttl=_TTL,
            wall=wall,
            monotonic=monotonic,
        )

    def gated(self) -> GatedFetch:
        """Both levers are the fake's own suspension gate.

        The fake wraps *both* members in one
        :class:`~ai_assistant.testing.cancellation.SuspendableResource`, so arming it
        holds whichever call comes next — which is why the suite arms per call rather
        than once at construction.
        """
        subject = FakeFetcher(_ROOT)
        return GatedFetch(
            fetcher=subject, arm_listing=subject.suspend_next, arm_fetch=subject.suspend_next
        )


# --- what only this file can decide ----------------------------------------


def test_the_default_identity_is_a_bare_declared_name() -> None:
    """Tier 2, and says what the producer is rather than what its root holds.

    ADR-0093 §7 uses exactly this hazard as its worked example — a producer "names
    *itself*, never the data it holds" — and a fake defaulting to a path-shaped
    identity would teach every consumer's test the wrong shape.
    """
    assert FakeFetcher().name == DEFAULT_FETCHER_NAME
    assert ":" not in DEFAULT_FETCHER_NAME


@pytest.mark.parametrize("refusal", list(FetchRefusal))
async def test_every_refusal_member_is_reachable_from_the_script(
    refusal: FetchRefusal,
) -> None:
    """A consumer drives ADR-0230 §6's disposition without a filesystem.

    The scripted name is still **listed** and still carries an authentic handle: it is
    the *fetch* that refuses, which is the state a file deleted, replaced or grown
    between the listing and the fetch produces. A fake that answered ``NOT_FOUND`` by
    omitting the entry would make the consumer's own resolution path untestable.
    """
    subject = FakeFetcher({"report.md": "text"}, refusals={"report.md": refusal})
    listing = await subject.listing()

    outcome = await subject.fetch(listing, listing.entries[0])

    assert [entry.name for entry in listing.entries] == ["report.md"]
    assert outcome.refusal is refusal
    assert outcome.record is None


@pytest.mark.parametrize("name", ["", "   ", " files ", "files ", "files:0f3c", "a\udc80b"])
def test_a_value_that_is_not_a_declared_name_is_refused_at_construction(name: str) -> None:
    """ADR-0190 §4's declared-name rules, refused rather than repaired.

    The canonical fake must not be configurable into failing its own suite, and a
    **padded** name is the arm that makes the cost concrete rather than formal:
    ``SourceListing.source`` is ``EncodableText`` and does not strip, while
    ``Attestation.reported_by`` is an ``Identifier`` whose validator *returns*
    ``value.strip()`` — so ``" files "`` would put one source into a listing and a
    record under two spellings, from one fetcher, in one turn, and would make it
    ungrantable besides (ADR-0097 §9).

    The colon arm is §4's second form intruding on the first: a declared name carrying
    one is not a declared name, and a value merely *shaped* like a discriminated
    identity is not one either — which is why the discriminator arrives through its own
    parameter rather than being read out of this one.
    """
    with pytest.raises(ValueError, match="ADR-0190 §4"):
        FakeFetcher(name=name)


@pytest.mark.parametrize(
    "discriminator",
    ["", "0f3c", "0F3C9D1A7B45E28C6D90FA3B17E4C852", "0f3c9d1a7b45e28c6d90fa3b17e4c85"],
)
def test_a_value_that_is_not_a_discriminator_is_refused_at_construction(
    discriminator: str,
) -> None:
    """Exactly 32 lowercase hexadecimal characters, and nothing else is one (§4)."""
    with pytest.raises(ValueError, match="ADR-0190 §4"):
        FakeFetcher(discriminator=discriminator)


async def test_a_discriminated_identity_reaches_the_listing_and_the_record() -> None:
    """ADR-0190 §4's second form, composed and carried on both surfaces.

    The form a deployment's **second** configured source of a type holds. A fetch root
    takes the bare form today because a deployment configures one (ADR-0230 §6), so
    this is the arm that keeps the fake able to stand in for the day it does not.
    """
    subject = FakeFetcher(
        {"a.md": "x"}, name="files", discriminator="0f3c9d1a7b45e28c6d90fa3b17e4c852"
    )

    listing = await subject.listing()
    outcome = await subject.fetch(listing, listing.entries[0])

    assert subject.name == "files:0f3c9d1a7b45e28c6d90fa3b17e4c852"
    assert listing.source == subject.name
    assert outcome.record is not None
    attestation = outcome.record.provenance.attestation
    assert attestation is not None
    assert attestation.reported_by == subject.name


@pytest.mark.parametrize(
    ("figure", "value"),
    [
        ("listing_ttl", timedelta(0)),
        ("listing_ttl", timedelta(seconds=-1)),
        ("max_entries", 0),
        ("max_entries", -1),
    ],
)
def test_a_bound_outside_its_domain_is_refused_at_construction(figure: str, value: object) -> None:
    """ADR-0230 §6's domains, on the fake as on the concrete fetcher.

    Both are values the fake could only honour by breaking its own contract. A zero
    ``listing_ttl`` mints a listing that is **already expired**, so its own authentic
    entry can never be fetched — a fetcher that lists what it cannot read. And a
    negative ``max_entries`` reaches ``entries[:-1]``, which "quietly yields all but the
    last entry, so a bound would be defeated by a configuration value rather than
    enforced by one" — the exact reading §6 refuses.
    """
    configured: dict[str, Any] = {figure: value}

    with pytest.raises(ValueError, match="ADR-0230 §6"):
        FakeFetcher({"a.md": "x"}, **configured)


def test_the_clock_is_guarded_like_every_other_seam() -> None:
    """ADR-0026 §7 is "uniformity with **no advisory exemption**", fakes included.

    "The ``testing/`` fakes are in scope for the reason they exist: they are the
    canonical doubles consumers certify against, and a fake looser than the contract
    certifies consumers the real implementation will reject." A naive reading must reach
    a caller as the clock seam's own refusal rather than as an unrelated validation
    error from whichever model happened to be constructed first.
    """
    subject = FakeFetcher({"a.md": "x"}, now=lambda: datetime(2026, 1, 1))  # noqa: DTZ001

    with pytest.raises(ClockReadingError):
        asyncio.run(subject.listing())


@pytest.mark.parametrize("name", ["a/b.md", "../escape.md", "..", ".", "nul\x00.md"])
def test_a_listed_name_that_is_not_one_component_is_refused_at_construction(name: str) -> None:
    """ADR-0230 §4: a listed ``name`` is one path component and never a path.

    Refused here rather than at ``fetch`` time, for the reason every guard on this
    fake is at construction: allowing it would only move the failure far from the
    mistake, and would let a consumer's test certify a resolution this seam forbids.
    """
    with pytest.raises(ValueError, match="one path component"):
        FakeFetcher({name: "text"})


def test_a_scripted_refusal_for_a_file_the_root_does_not_hold_is_refused() -> None:
    """An entry no listing showed is already ``NOT_FOUND`` (ADR-0230 §4).

    So a script naming one is not a second way to say the same thing — it is a script
    whose author expected an entry to exist, and the fake says so rather than silently
    doing nothing.
    """
    with pytest.raises(ValueError, match="does not hold"):
        FakeFetcher({"a.md": "x"}, refusals={"b.md": FetchRefusal.UNREADABLE})


async def test_the_listing_is_capped_and_ordered_newest_first() -> None:
    """The two clauses ADR-0230 §13 keeps out of the suite, decided where they can be.

    A generic suite holding one listing cannot decide the order a root's own
    modification times imply; this fake stamps them, so it can.
    """
    subject = FakeFetcher({f"f{index}.md": "x" for index in range(5)}, max_entries=3)

    listing = await subject.listing()

    assert [entry.name for entry in listing.entries] == ["f0.md", "f1.md", "f2.md"]
    instants = [entry.modified_at for entry in listing.entries]
    assert instants == sorted(instants, reverse=True)


async def test_the_call_counts_are_readable_without_a_mock() -> None:
    """ADR-0230 §14 item 6 asks a consumer to assert a turn paid no fetch.

    Over the audit and the supply rather than over a call count, in that item's own
    terms — but a consumer's *own* wiring test still needs to see that a member was
    not reached, and a counter on the canonical fake is what keeps that from being a
    ``unittest.mock`` in a corpus that otherwise has none.
    """
    subject = FakeFetcher({"a.md": "x"})
    listing = await subject.listing()
    await subject.fetch(listing, listing.entries[0])

    assert (subject.listing_count, subject.fetch_count) == (1, 1)
