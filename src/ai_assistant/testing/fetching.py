"""A canonical :class:`~ai_assistant.core.protocols.Fetcher` fake (ADR-0230 §13).

The shared test double for the ``Fetcher`` contract, so a subsystem that services a
fetch — `orchestration`'s read servicer — can exercise every branch of its own
pipeline without a directory on disk and without importing the concrete fetcher
(``CLAUDE.md`` golden rule 1; ADR-0093 §2 forbids importing ``ai_assistant.readers``
from a subsystem outright).

**It mints and verifies its own tokens and handles, and that is what ADR-0230 §13
requires of it rather than a flourish.** The conformance suite's membership clauses
— that an entry the test assembled is refused, that an authentic entry carried
inside an altered listing is refused, that a faithful copy is fetched — are all
vacuous on a fake that accepts whatever it is handed. So this fake carries the same
four properties §4 fixes: a key generated at construction and never leaving it, a
handle bound to the listing that minted it, a token committing to that listing's
ordered entry names, and verification that retains nothing.

**The mechanism is written out here rather than shared with the concrete fetcher**,
and that is the point rather than duplication to be tidied away: `testing` may not
import `readers` (``lint-imports``), and a conformance suite whose subject and whose
double decided conformance by calling the same code would report every
implementation as conforming with itself. Two independent implementations of §4's
four properties is what makes the suite evidence.

It is scriptable to the states ADR-0230 §6 distinguishes, which is what a consumer
needs to test its own disposition:

* a listing **with entries**, each fetchable into one attested record;
* an **empty** listing — a success, and emphatically not a failure signal, and the
  state a root that cannot be read produces too;
* a fetch that **refuses**, per name, into any :class:`FetchRefusal` member — so a
  consumer can drive the disposition §6 gives a refusal without a filesystem.

**And a fourth, which is what makes the cancellation clause testable at all.** Both
members run inside a :class:`~ai_assistant.testing.cancellation.SuspendableResource`,
so a suite can arm :meth:`FakeFetcher.suspend_next` and cancel a call that has
*demonstrably* arrived at an await. Without it the clause passes vacuously: a fake
that completes immediately can only be cancelled before it starts, which exercises
none of the code an implementation would use to catch a ``CancelledError`` during
source I/O and convert it.

**Not a fault injector.** Everything here conforms. A consumer that needs a fetcher
which *breaks* the contract on purpose — one returning a record for an entry it
never listed, or an outcome carrying both halves — is testing a reaction to a
non-conforming producer and supplies its own stub for it. This fake must stay the
thing a conforming implementation is compared against.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from ai_assistant.core.types import (
    Attestation,
    FetchOutcome,
    FetchRefusal,
    MemorySource,
    Provenance,
    SemanticMemory,
    SourceListing,
    SourceListingEntry,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.types import MemoryRecord
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: The identity this fake declares unless a test names another. Tier 2 and says what
#: the producer *is*, never what its root holds (ADR-0230 §4, ADR-0093 §7). Bare, in
#: ADR-0190 §4's sense.
DEFAULT_FETCHER_NAME: Final = "fake-root"

#: When this fake pretends it listed — **our** clock.
_DEFAULT_READ_AT: Final = datetime(2026, 1, 2, tzinfo=UTC)

#: ADR-0230 §4's named default for ``fetch_listing_ttl``.
_DEFAULT_TTL: Final = timedelta(minutes=5)

#: ADR-0230 §6's named default for ``fetch_listing_max_entries``.
_DEFAULT_MAX_ENTRIES: Final = 40

#: What an attested producer's report is worth (ADR-0230 §5, ADR-0038 §2a).
_ATTESTED_CONFIDENCE: Final = 0.9

#: The domain separators the two signatures are taken under, so a value minted as one
#: can never verify as the other.
_LISTING_DOMAIN: Final = b"ai-assistant/testing/fetch/listing/v1"
_ENTRY_DOMAIN: Final = b"ai-assistant/testing/fetch/entry/v1"

_TOKEN_FIELDS: Final = 4
_HANDLE_FIELDS: Final = 2


@final
class FakeFetcher:
    """A scriptable, conforming ``Fetcher`` over an in-memory root (ADR-0230 §13)."""

    def __init__(  # noqa: PLR0913 — a scripted root, an identity, two clocks and §6's figures
        self,
        files: Mapping[str, str] | None = None,
        *,
        name: str = DEFAULT_FETCHER_NAME,
        read_at: datetime = _DEFAULT_READ_AT,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], int] | None = None,
        listing_ttl: timedelta = _DEFAULT_TTL,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        refusals: Mapping[str, FetchRefusal] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Create a fetcher over a scripted root.

        Args:
            files: What the root holds, as name to text. The listing's order is
                **most recently modified first**, and this fake stamps the first
                entry as the most recent so that the mapping's own order is the
                listing's — a test that writes ``{"newest.md": …, "older.md": …}``
                gets exactly that. ``None`` and ``{}`` both mean an **empty
                listing**, which is a success.
            name: The declared identity. Every listing's ``source`` and every
                attestation's ``reported_by`` is this value.
            read_at: What this fake reports as the instant it listed, where no
                ``now`` is given.
            now: A wall clock, for a suite driving the expiry clauses. Defaults to a
                constant at ``read_at``, so a listing minted by this fake is inside
                its own wall deadline for as long as the test runs.
            monotonic: A monotonic source in nanoseconds, for the other deadline.
                Defaults to a constant, for ``now``'s reason.
            listing_ttl: How long a listing's authority lasts. Both deadlines are
                bound into the signed token and **either** expiring refuses the
                listing, exactly as ADR-0230 §4 requires of a real one.
            max_entries: The listing's cap.
            refusals: Names whose fetch refuses, and the class each refuses with, so
                a consumer can drive every ``FetchRefusal`` member without a
                filesystem. A name here is still **listed** and still has an
                authentic handle: it is the fetch that refuses, which is the state a
                file deleted between the listing and the fetch produces.
            id_factory: Mints each record's id. Defaulted to a fresh UUID; a caller
                *choosing* an id is not a producer *deriving* one (ADR-0092 §6).

        Raises:
            ValueError: If ``name`` is blank, if a scripted name is not a single path
                component, or if ``refusals`` names a file the root does not hold.
                Each would make this fake unable to pass its own conformance suite,
                and the canonical fake must not be configurable into that.
        """
        if not name.strip():
            msg = "a fetcher's declared identity must be non-blank (ADR-0230 §4)"
            raise ValueError(msg)
        scripted = dict(files or {})
        for candidate in scripted:
            if not candidate or candidate in {".", ".."} or {"/", "\\", "\x00"} & set(candidate):
                msg = (
                    f"a listed name is one path component and never a path, got "
                    f"{candidate!r} (ADR-0230 §4)"
                )
                raise ValueError(msg)
        unknown = sorted(set(refusals or {}) - set(scripted))
        if unknown:
            msg = (
                f"a scripted refusal names a file this root does not hold: "
                f"{', '.join(unknown)}; a fetch of an entry no listing showed is "
                f"already NOT_FOUND (ADR-0230 §4)"
            )
            raise ValueError(msg)
        self._name = name
        self._files = scripted
        self._refusals = dict(refusals or {})
        self._read_at = read_at
        self._now = now if now is not None else lambda: read_at
        self._monotonic = monotonic if monotonic is not None else lambda: 0
        self._ttl_ns = int(listing_ttl.total_seconds() * 1_000_000_000)
        self._max_entries = max_entries
        self._id_factory = id_factory
        self._key = secrets.token_bytes(32)
        self._resource = SuspendableResource()
        self._listings = 0
        self._fetches = 0

    @property
    def name(self) -> str:
        """This fetcher's declared identity — stable, and every listing's ``source``."""
        return self._name

    @property
    def listing_count(self) -> int:
        """How many times :meth:`listing` has been called."""
        return self._listings

    @property
    def fetch_count(self) -> int:
        """How many times :meth:`fetch` has been called."""
        return self._fetches

    @property
    def log(self) -> ResourceLog:
        """When each call was inside the modelled root (ADR-0060's case reads it)."""
        return self._resource.log

    def suspend_next(self) -> LoopSuspension:
        """Arm the next call to suspend inside the root it is reading.

        The fourth capability ADR-0230 §13 requires of this fake, and the reason the
        cancellation clause is not vacuous: a suite can wait until a call has
        demonstrably arrived at an await, cancel it *there*, and see what comes back.

        Returns:
            The handle the suite waits on and releases.

        Raises:
            RuntimeError: If a suspension is already armed.
        """
        return self._resource.suspend_next()

    async def listing(self) -> SourceListing:
        """Show the scripted root, newest first and capped."""
        self._listings += 1
        async with self._resource.held():
            read_at = self._now()
            names = list(self._files)[: self._max_entries]
            listing_id = secrets.token_hex(16)
            entries = tuple(
                SourceListingEntry(
                    name=name,
                    size_bytes=len(self._files[name].encode("utf-8")),
                    # Descending, so the sequence's order *is* most-recently-modified
                    # first and a consumer asserting on the ordering has something to
                    # assert on.
                    modified_at=read_at - timedelta(minutes=position),
                    handle=self._mint_handle(listing_id, position, name),
                )
                for position, name in enumerate(names)
            )
            return SourceListing(
                source=self._name,
                read_at=read_at,
                entries=entries,
                token=self._mint_token(listing_id, names),
            )

    async def fetch(self, listing: SourceListing, entry: SourceListingEntry) -> FetchOutcome:
        """Read the scripted file ``entry`` names, verifying its membership first."""
        self._fetches += 1
        async with self._resource.held():
            names = [member.name for member in listing.entries]
            authority = self._verify_token(listing.token, names)
            if authority is None:
                return FetchOutcome(refusal=FetchRefusal.NOT_FOUND)
            listing_id, deadlines = authority
            if self._expired(deadlines):
                return FetchOutcome(refusal=FetchRefusal.NOT_FOUND)
            if not self._verify_handle(listing_id, listing.entries, entry):
                return FetchOutcome(refusal=FetchRefusal.NOT_FOUND)
            scripted = self._refusals.get(entry.name)
            if scripted is not None:
                return FetchOutcome(refusal=scripted)
            # Reached only through a verified handle, so the name is one this fake
            # minted and the lookup cannot miss.
            return FetchOutcome(record=self._mint_record(self._files[entry.name]))

    # --- the capability (ADR-0230 §4) ------------------------------------

    def _sign(self, domain: bytes, *parts: bytes) -> str:
        """One keyed digest over a domain-separated, length-prefixed message."""
        message = bytearray(domain)
        for part in parts:
            message += len(part).to_bytes(8, "big")
            message += part
        return hmac.new(self._key, bytes(message), hashlib.sha256).hexdigest()

    def _mint_token(self, listing_id: str, names: Sequence[str]) -> str:
        """Sign a listing's identity, its two deadlines and its ordered entry names."""
        monotonic = self._monotonic() + self._ttl_ns
        wall = _nanoseconds(self._now()) + self._ttl_ns
        body = f"{listing_id}.{monotonic}.{wall}"
        return f"{body}.{self._sign(_LISTING_DOMAIN, body.encode(), _commitment(names))}"

    def _verify_token(self, token: str, names: Sequence[str]) -> tuple[str, tuple[int, int]] | None:
        """What this fake signed for this listing, or ``None`` if it signed none."""
        fields = token.split(".")
        if len(fields) != _TOKEN_FIELDS:
            return None
        listing_id, monotonic_raw, wall_raw, signature = fields
        body = f"{listing_id}.{monotonic_raw}.{wall_raw}"
        if not hmac.compare_digest(
            self._sign(_LISTING_DOMAIN, body.encode(), _commitment(names)), signature
        ):
            return None
        return listing_id, (int(monotonic_raw), int(wall_raw))

    def _mint_handle(self, listing_id: str, position: int, name: str) -> str:
        """Sign one entry's listing, its position in it and its name."""
        signature = self._sign(
            _ENTRY_DOMAIN, listing_id.encode(), str(position).encode(), name.encode()
        )
        return f"{position}.{signature}"

    def _verify_handle(
        self, listing_id: str, entries: Sequence[SourceListingEntry], entry: SourceListingEntry
    ) -> bool:
        """Whether this fake minted ``entry``'s handle for **this** listing."""
        fields = entry.handle.split(".")
        if len(fields) != _HANDLE_FIELDS:
            return False
        position_raw, signature = fields
        if not hmac.compare_digest(
            self._sign(
                _ENTRY_DOMAIN, listing_id.encode(), position_raw.encode(), entry.name.encode()
            ),
            signature,
        ):
            return False
        position = int(position_raw)
        return 0 <= position < len(entries) and entries[position].name == entry.name

    def _expired(self, deadlines: tuple[int, int]) -> bool:
        """Whether **either** of ADR-0230 §4's two deadlines has passed."""
        monotonic, wall = deadlines
        return self._monotonic() >= monotonic or _nanoseconds(self._now()) >= wall

    def _mint_record(self, text: str) -> MemoryRecord:
        """One ``SEMANTIC``, ``EXTERNAL``-sourced record carrying the text verbatim."""
        read_at = self._now()
        return SemanticMemory(
            id=self._id_factory() if self._id_factory is not None else uuid4().hex,
            content=text,
            fact=text,
            provenance=Provenance(
                source=MemorySource.EXTERNAL,
                confidence=_ATTESTED_CONFIDENCE,
                evidence=(),
                last_updated=read_at,
                last_confirmed_at=read_at,
                attestation=Attestation(reported_by=self._name, reported_at=read_at, extent=None),
                derived_from_external=False,
            ),
            topics=(),
            about_person=None,
        )


def _nanoseconds(instant: datetime) -> int:
    """A wall-clock instant as integer nanoseconds since the epoch."""
    return int(instant.timestamp() * 1_000_000_000)


def _commitment(names: Sequence[str]) -> bytes:
    """A digest over an ordered sequence of names, length-prefixed.

    Length-prefixed so that no two different sequences commit to the same bytes:
    without it ``("ab", "c")`` and ``("a", "bc")`` would be indistinguishable, and a
    reordering that preserved the concatenation would go unrefused.
    """
    digest = hashlib.sha256()
    for name in names:
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.digest()
