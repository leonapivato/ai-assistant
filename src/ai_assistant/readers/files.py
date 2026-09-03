"""The local-file fetcher: one configured root, listed and read (ADR-0230).

The first concrete :class:`~ai_assistant.core.protocols.Fetcher`. It shows the
supported direct children of one configured directory, most recently modified
first and capped, and reads one entry of that listing into a single attested
record carrying the file's own text.

**Off until configured.** ``Settings.fetch_root_path``'s named default is unset, so
a deployment with no root pays no listing read, renders no listing block, and
cannot service the kind (ADR-0230 §6).

**Three properties are what this module is *for*, and each is written where it can
be checked rather than asserted.**

*The address space is not reachable from model output.* A model names an ordinal;
the loop hands this fetcher an entry **this fetcher minted**, carrying a capability
this fetcher signed. Nothing here ever joins a caller-supplied fragment onto a
root, and the one string that reaches a filesystem call — an entry's ``name`` — has
been established as standing at a signed position of a signed listing before it is
used, and is re-checked to be a single path component besides (ADR-0230 §2, §4).

*Containment is a property of where the open starts, not of a check performed
against a path.* The fetcher holds an **opened directory handle** on its root,
acquired once at construction and held for its life, and every acquisition is a
contained resolution beneath that handle. A root whose *pathname* is replaced after
construction is not the configured root any more: the handle goes on naming the
directory the operator configured, and whatever now occupies the pathname is never
reached (§4).

*A root whose reads would leave the device does not wire.* Construction decides
eligibility in ADR-0230 §6's two fail-closed stages — the platform's own tables
with nothing opened, then the opened mount root's device identity checked against
that claim and the remainder resolved atomically — and a refusal is a configuration
error that stops the deployment, never an empty listing and never a
``FetchRefusal``.

**What the two seams are for.** ``_locality`` is stage 1's view of the platform,
injectable because ADR-0230 §14 item 22's nine arms cannot be staged on a
developer's own disk; ``_descent`` is the one atomic operation both stage 2 and
every acquisition are performed by, and it is the module that says so when a
platform has no such operation at all.

**The injected clock is read on the worker thread, which is this corpus's
established shape for a filesystem producer rather than a new demand on ADR-0026.**
ADR-0230 §4 requires a listing's ``read_at`` to be "captured once **at acquisition**"
and §5 requires a record's instants to be "the instant the file was read", and the
only place those are true is beside the read itself. ``CalendarReader._read_source``
already does exactly this, on ADR-0093 §7b's identical clause, and says why in its own
terms: "anchoring before the read is deterministic and untrue — a capture at 10:00 that
waits on its worker, opens a file replaced at 10:05 and reads it at 10:10 returns
proposals describing the 10:05 file stamped 10:00". So a ``Clock`` that could not be
read off the loop is one neither concrete reader in this tree could be given either,
and the clause the fetch depends on is the clause the calendar reader has depended on
since leg 6. A clock fault reaches the caller unchanged through ``asyncio.to_thread``,
so nothing about the guard (ADR-0026 §7) or the propagation posture moves.

**Blocking work runs off the event loop, and the discipline is deliberately not
ADR-0093 §7's.** That section's daemon-thread rule exists because a reader's
configured path "may still be a stalled mount, and every other bound sits behind an
operation that never returns" — which is exactly the hazard ADR-0230 §6 makes
**unwireable** here: the root is established local, over a local device, before any
handle survives construction. So this module uses ``asyncio.to_thread`` and owns no
thread of its own. Nothing about that weakens a ratified clause: §7's rule binds
``Reader``, ADR-0230 states no thread discipline, and the reason §7 gives for its
own does not reach a root that cannot be on a network filesystem.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import hashlib
import hmac
import os
import secrets
import stat
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import ConfigurationError
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
from ai_assistant.readers._descent import (
    AtomicDescentUnavailableError,
    descent_is_available,
    open_contained,
)
from ai_assistant.readers._extract import (
    SUPPORTED_SUFFIXES,
    ContentTooLargeError,
    ExtractionFailedError,
    extract,
)
from ai_assistant.readers._locality import PlatformTables, ProcPlatformTables

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import MemoryRecord

#: This fetcher type's **declared** identity (ADR-0189 §5, ADR-0190 §1). Tier 2,
#: says what the producer *is* and never what its root holds: a fetcher "names
#: *itself*, never the data it holds", and here the mistake would be one keystroke
#: away in a free-text setting. Bare, in ADR-0190 §4's sense — a deployment
#: configures one fetch root (ADR-0230 §6), so this is the first configured source
#: of its type and may hold the type's bare name.
FILE_FETCHER_NAME: Final = "files"

#: ADR-0230 §4's and §6's named defaults, restated here because the constructor is
#: a second seam a test or a second composition root reaches directly, and §6 puts
#: every refusal at construction rather than at the first fetch (ADR-0093 §5).
DEFAULT_FETCH_LISTING_TTL: Final = timedelta(minutes=5)
DEFAULT_FETCH_LISTING_MAX_ENTRIES: Final = 40
DEFAULT_FETCH_MAX_FILE_BYTES: Final = 4 * 1024 * 1024
DEFAULT_FETCH_MAX_CONTENT_BYTES: Final = 32 * 1024

#: What a fetched record's report is worth (ADR-0230 §5). Below 1.0 — nothing
#: forces that in the ``ATTESTED`` band, since a connected source may legitimately
#: report a fact it is certain of (ADR-0038 §2a) — but a third party's claim about
#: the user is not the user's own word, and 0.9 is the figure the corpus's other
#: attested producers carry.
_ATTESTED_CONFIDENCE: Final = 0.9

#: The flags stage 2's own open of the mount root uses. Read-only, a directory, and
#: closed on exec: a descriptor on the owner's documents must not survive into a
#: child process.
_DIRECTORY_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC

#: The flags an acquisition uses (ADR-0230 §4). ``O_NONBLOCK`` is the load-bearing
#: one: a listed regular file can be replaced between the listing and the fetch by a
#: **named pipe**, and an ordinary read-mode open of a FIFO with no writer blocks
#: until a writer arrives — returning neither a record nor a refusal, "the one
#: outcome §6 says a fetch never has". The flag costs a regular file nothing.
#: Symbolic links need no ``O_NOFOLLOW`` here because the contained resolution
#: refuses one at **every** component, which is strictly wider.
_ACQUIRE_FLAGS: Final = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC

#: How much one ``os.read`` asks for; clamped to the remaining budget, so it bounds
#: nothing on its own.
_CHUNK_BYTES: Final = 1 << 16

#: The domain separators the two signatures are taken under, so that a value minted
#: as one can never verify as the other.
_LISTING_DOMAIN: Final = b"ai-assistant/fetch/listing/v1"
_ENTRY_DOMAIN: Final = b"ai-assistant/fetch/entry/v1"

#: How many ``.``-separated fields a token and a handle carry.
_TOKEN_FIELDS: Final = 4
_HANDLE_FIELDS: Final = 2


class _RefusalError(Exception):
    """A source failure this seam converts into a :class:`FetchRefusal`.

    An **internal vocabulary**, never a `core` error class: ADR-0230 §4 adds none,
    "because there is no failure a caller would handle differently from a refusal it
    must already handle". Each subclass carries the class it becomes, so the
    translation is one lookup at the seam rather than a chain of ``except`` arms that
    could drift from the enumeration.
    """

    classification: FetchRefusal


class _EntryNotFoundError(_RefusalError):
    """The named object is not there (``ENOENT``) — ``NOT_FOUND``."""

    classification = FetchRefusal.NOT_FOUND


class _NotARegularFileError(_RefusalError):
    """The named object is not a regular file — ``NOT_A_FILE``.

    Decided by **what the object is, never by which step discovered it**
    (ADR-0230 §4). Some kinds cannot be held at all — opening a Unix-domain socket
    by its pathname answers ``ENXIO``, and a contained resolution refuses a symbolic
    link with ``ELOOP`` — so this class covers an open that *failed because of the
    object's kind* as well as one that succeeded onto a directory, a FIFO or a
    device. An implementation folding the first into ``UNREADABLE`` would pass the
    directory and FIFO cases and mis-class the socket.
    """

    classification = FetchRefusal.NOT_A_FILE


class _UnreadableError(_RefusalError):
    """The open or the read failed for a reason that is not about the object's kind."""

    classification = FetchRefusal.UNREADABLE


class _FileTooLargeError(_RefusalError):
    """The object supplied more than ``fetch_max_file_bytes`` — ``TOO_LARGE``."""

    classification = FetchRefusal.TOO_LARGE


class _ExtractionRefusedError(_RefusalError):
    """A supported format whose text could not be decoded — ``EXTRACTION_FAILED``."""

    classification = FetchRefusal.EXTRACTION_FAILED


#: The ``errno`` for *there is nothing of that name*, which is ``NOT_FOUND``.
_ENOENT: Final = errno.ENOENT

#: Which ``errno`` means *this object is not a file this seam can hold*. Each is a
#: refusal **about the object's kind** rather than about permission or hardware:
#: ``ELOOP`` a symbolic link the contained resolution would not follow, ``EXDEV`` and
#: ``EAGAIN`` a mount it would not cross or an escape above the root it would not
#: make, ``ENXIO`` an object — a Unix-domain socket, or a character device with no
#: driver behind it — that cannot be opened as a file at all, and
#: ``EISDIR``/``ENOTDIR`` a directory where a file was named or the reverse.
#:
#: ``ENXIO`` is the member that earns this set. Linux answers it for an open of a
#: socket by pathname, and an implementation folding every open *failure* into
#: ``UNREADABLE`` would pass the directory and FIFO arms — both of which open
#: successfully and are caught by the kind check afterwards — while mis-classing the
#: one kind that cannot be held at all (ADR-0230 §4, §14 item 4).
_KIND_ERRNOS: Final = frozenset(
    {errno.EAGAIN, errno.EISDIR, errno.ELOOP, errno.ENOTDIR, errno.ENXIO, errno.EXDEV}
)


@dataclass(frozen=True, slots=True)
class _Listed:
    """One directory entry the listing will show, before its handle is minted.

    ``modified_ns`` is carried beside ``modified_at`` because the sort is taken on
    the integer: ``datetime`` rounds to microseconds, so two files written in the
    same microsecond would sort by name where the filesystem can still tell them
    apart.
    """

    name: str
    size_bytes: int
    modified_at: datetime
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _Deadlines:
    """A listing's two expiry deadlines, in nanoseconds on their own clocks.

    Both are bound into the signed token and **either** expiring refuses the listing
    (ADR-0230 §4). Neither is rendered anywhere and neither outlives the process.
    """

    monotonic: int
    wall: int


@dataclass(frozen=True, slots=True)
class _Authority:
    """What a verified token establishes about the listing that carried it."""

    listing_id: str
    deadlines: _Deadlines


@final
class LocalFileFetcher:
    """One configured local root, listed and read (ADR-0230 §4, §6).

    Conforms to :class:`~ai_assistant.core.protocols.Fetcher`. It holds no store, no
    writer, no policy, no engine and no model: it reads its own configured source and
    returns what it read.

    **Constructed only where a root is configured, and only where that root's reads
    cannot leave the device.** Both refusals are :class:`ConfigurationError` and both
    stop the deployment, exactly as an out-of-range bound does — never an empty
    listing, never a ``FetchRefusal`` and never a degraded turn (ADR-0230 §6).
    """

    def __init__(  # noqa: PLR0913 — one root, two clocks, §6's four figures and the platform view; each is one knob
        self,
        root: Path,
        *,
        now: Clock = lambda: datetime.now(UTC),
        monotonic: Callable[[], int] = time.monotonic_ns,
        listing_ttl: timedelta = DEFAULT_FETCH_LISTING_TTL,
        listing_max_entries: int = DEFAULT_FETCH_LISTING_MAX_ENTRIES,
        max_file_bytes: int = DEFAULT_FETCH_MAX_FILE_BYTES,
        max_content_bytes: int = DEFAULT_FETCH_MAX_CONTENT_BYTES,
        tables: PlatformTables | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Open the configured root, or refuse to exist.

        Args:
            root: The one directory this fetcher lists and reads. **Absolute**, and
                deliberately **not** canonicalised: resolving it would follow the
                symbolic links ADR-0230 §6 requires the descent to refuse.
            now: The wall clock. Read once per listing, at acquisition, for
                :attr:`~ai_assistant.core.types.SourceListing.read_at` and for one of
                the two expiry deadlines; and once per successful fetch, at the
                instant the file was read, for the record's attestation. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §7).
            monotonic: The monotonic source, in nanoseconds, for the other deadline.
                A separate seam because it is a different contract from ``Clock``,
                which is scoped to wall-clock instants — and both bind, because
                "neither clock alone is sufficient" (ADR-0230 §4): a wall clock
                stepped backwards leaves a five-minute window open an hour later,
                and an ordinary monotonic source does not advance while the host is
                suspended.
            listing_ttl: ``fetch_listing_ttl``. Strictly positive.
            listing_max_entries: ``fetch_listing_max_entries``. At least 1.
            max_file_bytes: ``fetch_max_file_bytes``. At least 1.
            max_content_bytes: ``fetch_max_content_bytes``. At least 1.
            tables: The platform's mount and device view for §6's stage 1. Defaults
                to this machine's own ``/proc`` and ``/sys``.
            id_factory: Mints each record's id. Defaulted to a fresh UUID; a caller
                *choosing* an id is not a producer *deriving* one (ADR-0092 §6).

        Raises:
            ConfigurationError: If any figure is outside its domain, if the root is
                relative, if this platform offers no atomic contained resolution
                (ADR-0230 §6's unavailability clause), if the platform will not
                establish the root's locality, if the opened mount root's device
                identity does not match what the tables claimed, or if the descent
                refuses — a mount crossing, a symbolic link at any component, or an
                escape above the start.
        """
        _refuse_out_of_domain(
            listing_ttl=listing_ttl,
            listing_max_entries=listing_max_entries,
            max_file_bytes=max_file_bytes,
            max_content_bytes=max_content_bytes,
        )
        if not root.is_absolute():
            msg = f"the fetch root must be an absolute path, got {str(root)!r} (ADR-0230 §6)"
            raise ConfigurationError(msg)
        self._now = checked_clock(now, owner="LocalFileFetcher")
        self._monotonic = monotonic
        self._listing_ttl_ns = int(listing_ttl.total_seconds() * 1_000_000_000)
        self._listing_max_entries = listing_max_entries
        self._max_file_bytes = max_file_bytes
        self._max_content_bytes = max_content_bytes
        self._id_factory = id_factory
        # Generated here and never leaving: it is what makes a token and a handle
        # unforgeable, and ADR-0230 §4 requires the state be private to the fetcher.
        # A restarted hub mints a new one and refuses every value from before the
        # restart, which is correct rather than a limitation — a turn does not
        # survive a restart either.
        self._key = secrets.token_bytes(32)
        self._root = _acquire_root(root, tables if tables is not None else ProcPlatformTables())

    @property
    def name(self) -> str:
        """This fetcher's declared identity — stable, Tier 2, and never a path."""
        return FILE_FETCHER_NAME

    def close(self) -> None:
        """Release the root handle. Idempotent.

        Not a member of the ``Fetcher`` Protocol, deliberately: that contract stays
        free of lifecycle, and ``app/composition.py`` registers this among the
        resources it has opened, which releases the handle both when a later
        construction step fails and in the façade's ordered shutdown (ADR-0230 §4,
        ADR-0042 §2). A fetcher wired outside that registration would pin its root's
        mount for the life of the process and leak a descriptor per build.
        """
        descriptor, self._root = self._root, -1
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)

    async def listing(self) -> SourceListing:
        """Show the root's supported direct children, newest first and capped.

        Returns:
            One listing, whose ``token`` is minted fresh, commits to the ordered
            entry names, and carries both expiry deadlines. An **empty listing is a
            success**, and a root that can no longer be read produces one too — no
            consumer distinguishes them (ADR-0230 §6).
        """
        # **Both clocks are read at acquisition**, which is ADR-0230 §4's own word for
        # `read_at` — "the instant **this system** listed, captured once at
        # acquisition" — and what makes the two deadlines describe the listing rather
        # than the moment the call was made. A worker-thread backlog between the two
        # would otherwise stamp a listing earlier than the directory was actually read
        # and start its window before the entries existed.
        listed, read_at, monotonic = (
            ([], self._now(), self._monotonic())
            if self._root < 0
            else await asyncio.to_thread(self._scan)
        )
        deadlines = _Deadlines(
            monotonic=monotonic + self._listing_ttl_ns,
            wall=_nanoseconds(read_at) + self._listing_ttl_ns,
        )
        listing_id = secrets.token_hex(16)
        entries = tuple(
            SourceListingEntry(
                name=item.name,
                size_bytes=item.size_bytes,
                modified_at=item.modified_at,
                handle=self._mint_handle(listing_id, position, item.name),
            )
            for position, item in enumerate(listed)
        )
        return SourceListing(
            source=self.name,
            read_at=read_at,
            entries=entries,
            token=self._mint_token(listing_id, deadlines, [item.name for item in listed]),
        )

    async def fetch(self, listing: SourceListing, entry: SourceListingEntry) -> FetchOutcome:
        """Read the file ``entry`` names, once, and mint one record for it.

        Args:
            listing: The listing ``entry`` came from — the authority its membership
                is verified against.
            entry: The entry naming the file to read.

        Returns:
            One outcome carrying a record or a refusal, never both and never neither.
        """
        suffix = self._admit(listing, entry)
        if suffix is None:
            return _refused(FetchRefusal.NOT_FOUND)
        try:
            text, read_at = await self._read(entry.name, suffix)
        except _RefusalError as refusal:
            return _refused(refusal.classification)
        return FetchOutcome(record=self._mint_record(text, read_at))

    def _admit(self, listing: SourceListing, entry: SourceListingEntry) -> str | None:
        """Whether this entry may be read at all, and the suffix it will be read as.

        Every arm here refuses ``NOT_FOUND``, "deliberately the same class an absent
        file yields, so that it discloses nothing about whether a guessed name exists
        under the root" (ADR-0230 §4).

        Returns:
            The entry's lowercased suffix, or ``None`` where the entry is refused.
        """
        if self._root < 0:
            # The root handle is gone — closed, or never survived construction —
            # which §4 makes "the listing is empty and every fetch refuses".
            return None
        names = [member.name for member in listing.entries]
        authority = self._verify_token(listing.token, names)
        if authority is None or self._expired(authority.deadlines):
            return None
        if not self._verify_handle(authority.listing_id, listing.entries, entry):
            return None
        # Re-checked here even though a signed handle already establishes that this
        # fetcher minted the name: ADR-0230 §2 requires that no model-supplied string
        # reach a filesystem call, and this is the last place that can be decided
        # over the value about to be used rather than over how it was obtained.
        suffix = _suffix_of(entry.name)
        if not _is_one_component(entry.name) or suffix not in SUPPORTED_SUFFIXES:
            return None
        return suffix

    async def _read(self, name: str, suffix: str) -> tuple[str, datetime]:
        """Acquire the file's bytes and decode them, both off the event loop.

        Returns:
            The extracted text, and **the instant the file was read** — captured on the
            worker thread the moment the bounded read returned, which is what ADR-0230
            §5 requires of ``reported_at``, ``last_updated`` and ``last_confirmed_at``.
            Reading the clock before the work was dispatched would stamp the record
            with an instant that can precede the read by however long the thread pool
            was busy, and §5's whole argument for admitting this instant at all is that
            "'when the source said so' and 'when we read it' are one event rather than
            two facts of which one stands in for the other".

            The instant is taken after the **acquisition** and not after the
            extraction, because the extraction is a decoding of bytes already in hand:
            it consults no source, so a later instant would describe this process's own
            work rather than the source's answer.

        Raises:
            _RefusalError: Whichever class the acquisition or the extraction produced. The
                two ``_extract`` classes are translated here rather than carried up,
                so that every refusal this seam can produce is one vocabulary.
        """
        data, read_at = await asyncio.to_thread(self._acquire, name)
        try:
            text = await asyncio.to_thread(
                extract, data, suffix, max_rendered_bytes=self._max_content_bytes
            )
        except ContentTooLargeError as exc:
            raise _FileTooLargeError from exc
        except ExtractionFailedError as exc:
            raise _ExtractionRefusedError from exc
        return text, read_at

    # --- what runs on a worker thread ------------------------------------

    def _scan(self) -> tuple[list[_Listed], datetime, int]:
        """List the root and stamp the read, blocking. See :func:`scan`.

        Both clocks are read **here**, on the worker thread, the moment the directory
        has been read — which is what "captured once at acquisition" means (ADR-0230
        §4). A clock fault reaches the caller unchanged through ``asyncio.to_thread``,
        so nothing is lost by reading it off the loop.
        """
        listed = scan(self._root, max_entries=self._listing_max_entries)
        return listed, self._now(), self._monotonic()

    def _acquire(self, name: str) -> tuple[bytes, datetime]:
        """Open and read one entry, and stamp the read. Blocking. See :func:`acquire`."""
        data = acquire(self._root, name, max_bytes=self._max_file_bytes)
        return data, self._now()

    # --- the capability (ADR-0230 §4) ------------------------------------

    def _sign(self, domain: bytes, *parts: bytes) -> str:
        """One keyed digest over a domain-separated, length-prefixed message.

        Length-prefixed so that no two different tuples of parts can produce one
        message: without it, ``("ab", "c")`` and ``("a", "bc")`` would sign the same
        bytes and a handle minted for one entry would verify for another.
        """
        message = bytearray(domain)
        for part in parts:
            message += len(part).to_bytes(8, "big")
            message += part
        return hmac.new(self._key, bytes(message), hashlib.sha256).hexdigest()

    def _mint_token(self, listing_id: str, deadlines: _Deadlines, names: Sequence[str]) -> str:
        """Sign a listing's identity, its deadlines and its ordered entry names.

        The names are **committed to** rather than carried: a digest is what §4's
        "commit to its listing's ordered entry names" requires, and carrying them
        would put the root's contents in a second place for no gain. Verification
        recomputes the digest from the entries it was handed, so an ``entries`` that
        was emptied, shortened, reordered or renamed produces a different digest and
        the signature does not verify.
        """
        body = f"{listing_id}.{deadlines.monotonic}.{deadlines.wall}"
        return f"{body}.{self._sign(_LISTING_DOMAIN, body.encode(), _commitment(names))}"

    def _verify_token(self, token: str, names: Sequence[str]) -> _Authority | None:
        """What this fetcher signed for this listing, or ``None`` if it signed none."""
        fields = token.split(".")
        if len(fields) != _TOKEN_FIELDS:
            return None
        listing_id, monotonic_raw, wall_raw, signature = fields
        body = f"{listing_id}.{monotonic_raw}.{wall_raw}"
        expected = self._sign(_LISTING_DOMAIN, body.encode(), _commitment(names))
        if not hmac.compare_digest(expected, signature):
            return None
        try:
            deadlines = _Deadlines(monotonic=int(monotonic_raw), wall=int(wall_raw))
        except ValueError:  # pragma: no cover — the signature covers the raw text
            return None
        return _Authority(listing_id=listing_id, deadlines=deadlines)

    def _mint_handle(self, listing_id: str, position: int, name: str) -> str:
        """Sign one entry's listing, its position in it and its name."""
        signature = self._sign(
            _ENTRY_DOMAIN, listing_id.encode(), str(position).encode(), name.encode()
        )
        return f"{position}.{signature}"

    def _verify_handle(
        self, listing_id: str, entries: Sequence[SourceListingEntry], entry: SourceListingEntry
    ) -> bool:
        """Whether this fetcher minted ``entry``'s handle for **this** listing.

        Three things and nothing else: that the handle is one this fetcher signed
        over that listing, that position and that name; that the position is inside
        the sequence; and that the name stands at that position of the sequence the
        token committed to — which the caller has already established is the sequence
        in hand, since the token verified over it.
        """
        fields = entry.handle.split(".")
        if len(fields) != _HANDLE_FIELDS:
            return False
        position_raw, signature = fields
        expected = self._sign(
            _ENTRY_DOMAIN, listing_id.encode(), position_raw.encode(), entry.name.encode()
        )
        if not hmac.compare_digest(expected, signature):
            return False
        try:
            position = int(position_raw)
        except ValueError:  # pragma: no cover — the signature covers the raw text
            return False
        return 0 <= position < len(entries) and entries[position].name == entry.name

    def _expired(self, deadlines: _Deadlines) -> bool:
        """Whether **either** of §4's two deadlines has passed.

        Both bind rather than one being chosen, because neither clock alone is
        sufficient: a wall clock stepped backwards leaves a window open long after it
        should have closed, and an ordinary monotonic source does not advance while
        the host is suspended. Refusing on whichever arrives first closes both holes
        with no platform requirement at all.
        """
        return (
            self._monotonic() >= deadlines.monotonic or _nanoseconds(self._now()) >= deadlines.wall
        )

    # --- what a fetch mints (ADR-0230 §5) --------------------------------

    def _mint_record(self, text: str, read_at: datetime) -> MemoryRecord:
        """One ``SEMANTIC``, ``EXTERNAL``-sourced record carrying the file's text.

        **Verbatim**: no model is on this path, and nothing summarises, abridges,
        rewrites, annotates or classifies the text between the file and the record.

        ``reported_by`` is this fetcher's own identity — the **configured root**,
        never whatever wrote the document — and ``reported_at`` is the instant the
        file was read, which is the one scope in which ADR-0092 §3's local-substitute
        clause is superseded: a source this system interrogates directly answers at
        the instant of the read, so "when the source said so" and "when we read it"
        are one event rather than two facts of which one stands in for the other.

        **The file's mtime is never read into an attestation.** ADR-0092 §3's
        prohibition is untouched: an mtime "is a property of the last local write and
        is changed by a copy, a restore or a ``touch`` while the source's claim stays
        where it was". A listing entry's ``modified_at`` is a fact about the
        filesystem, offered so a person or a planner can tell one file from another.
        """
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
                attestation=Attestation(
                    reported_by=self.name,
                    reported_at=read_at,
                    # This producer states no position for the file in the source's
                    # own world: a document has no span (ADR-0117 §2, ADR-0230 §5).
                    extent=None,
                ),
                # Asserts nothing in this band (ADR-0106 §1). The externality this
                # record carries is `MemorySource.EXTERNAL`, which `band_of` places
                # in `ATTESTED`; this field is the `DERIVED` band's question.
                derived_from_external=False,
            ),
            topics=(),
            about_person=None,
        )


def _refused(refusal: FetchRefusal) -> FetchOutcome:
    """One refusal, carrying a class and nothing else (ADR-0230 §6)."""
    return FetchOutcome(refusal=refusal)


def _nanoseconds(instant: datetime) -> int:
    """A wall-clock instant as integer nanoseconds since the epoch."""
    return int(instant.timestamp() * 1_000_000_000)


def _commitment(names: Sequence[str]) -> bytes:
    """A digest over an ordered sequence of names, length-prefixed.

    Length-prefixed for :meth:`LocalFileFetcher._sign`'s reason: without it
    ``("ab", "c")`` and ``("a", "bc")`` would commit to the same bytes, and a
    reordering that happened to preserve the concatenation would go unrefused.
    """
    digest = hashlib.sha256()
    for name in names:
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.digest()


def _suffix_of(name: str) -> str:
    """The entry's lowercased suffix — ``".pdf"`` — or ``""`` where it has none."""
    _, dot, suffix = name.rpartition(".")
    return f".{suffix.lower()}" if dot else ""


def _is_one_component(name: str) -> bool:
    """Whether ``name`` is a single path component that names a child and nothing else.

    ADR-0230 §4 refuses "a name carrying a directory separator or a parent
    reference". Unreachable through an authentic entry — the listing mints one name
    per directory entry — and checked anyway, because §2's property is that no
    model-supplied string reaches a filesystem call and the honest way to hold that
    is to decide it over the value rather than over its provenance.
    """
    return bool(name) and name not in {".", ".."} and not {"/", "\\", "\x00"} & set(name)


def _refuse_out_of_domain(
    *,
    listing_ttl: timedelta,
    listing_max_entries: int,
    max_file_bytes: int,
    max_content_bytes: int,
) -> None:
    """Refuse a figure outside ADR-0230 §6's stated domain, at construction.

    ``Settings`` states the same rules again, and this is not duplication for its own
    sake: §6 puts the refusal at load *and* this constructor is a second seam a test
    or a second composition root reaches directly, so a guard that only fired when a
    caller went through ``Settings`` is not a guard (ADR-0093 §5).

    Raises:
        ConfigurationError: Naming the figure and its domain.
    """
    if listing_ttl <= timedelta(0):
        msg = f"fetch_listing_ttl must be strictly positive, got {listing_ttl!r} (ADR-0230 §6)"
        raise ConfigurationError(msg)
    for label, figure in (
        ("fetch_listing_max_entries", listing_max_entries),
        ("fetch_max_file_bytes", max_file_bytes),
        ("fetch_max_content_bytes", max_content_bytes),
    ):
        if figure < 1:
            msg = f"{label} must be at least 1, got {figure!r} (ADR-0230 §6)"
            raise ConfigurationError(msg)


def _acquire_root(root: Path, tables: PlatformTables) -> int:
    """ADR-0230 §6's two stages, and the handle they leave behind.

    **Stage 1 — admission — reads the platform's own tables and opens nothing.** A
    root that is remote *as configured* is refused having been touched by nothing at
    all, which is what lets §6 claim the refusal costs the network nothing.

    **Stage 2 — acquisition — opens the resolution's start, checks it against the
    claim, and resolves the rest atomically.** The mount root stage 1 named is
    opened; that object's device identity is taken **from its handle** and refused
    unless it matches what stage 1 admitted; and the remainder of the configured path
    is resolved relative to that handle in one operation the platform makes atomic,
    which refuses rather than resolves on a mount crossing, a symbolic link at any
    component, or an escape above the start.

    **That one open is irreducible and is stated rather than hidden** (§6). No
    ordering removes it: a handle is the only thing an object's identity can be taken
    from, and a handle can only be got by opening something. It is a single directory
    open of a mount root the platform's own tables describe as local, with no
    component of the configured path among it, nothing read through it, refused on
    the device-identity mismatch, and survived by no handle. In the racing case it
    contacts a filesystem substituted under that mount root and is refused
    immediately — which the owner's ruling of 2026-09-03 (#1996, comment 5532194014)
    places outside ADR-0017 §1's reach, a scope this module cites rather than an
    argument it makes.

    Returns:
        The root handle every fetch is anchored to, for the fetcher's life.

    Raises:
        ConfigurationError: For every refusal above.
    """
    if not descent_is_available():
        msg = (
            "this platform offers no atomic contained resolution, so the local-file "
            "fetch mechanism is unavailable on it (ADR-0230 §6)"
        )
        raise ConfigurationError(msg)
    claim = tables.claim_for(root)
    if claim is None:
        msg = (
            f"the platform's tables name no mount for the fetch root {str(root)!r}, so its "
            f"locality cannot be established (ADR-0230 §6)"
        )
        raise ConfigurationError(msg)
    if not claim.is_local:
        msg = (
            f"the fetch root {str(root)!r} is on a {claim.filesystem_type!r} filesystem whose "
            f"backing the platform reports as {claim.backing.value!r}; ADR-0230 §6 admits only a "
            f"root whose filesystem and backing device are both established local"
        )
        raise ConfigurationError(msg)
    try:
        start = os.open(claim.mount_point, _DIRECTORY_FLAGS)
    except OSError as exc:
        msg = f"the fetch root's mount root could not be opened: {exc.strerror} (ADR-0230 §6)"
        raise ConfigurationError(msg) from exc
    try:
        if os.fstat(start).st_dev != claim.device:
            msg = (
                "the opened mount root's device identity does not match what the platform's "
                "tables claimed, so the fetch root's locality is unproven (ADR-0230 §6)"
            )
            raise ConfigurationError(msg)
        return _descend(start, root, claim.mount_point)
    finally:
        # The start handle survives nothing: on the refusing paths there is no
        # handle at all, and on the succeeding one the descent's own handle is what
        # every later read is taken on.
        with contextlib.suppress(OSError):
            os.close(start)


def _descend(start: int, root: Path, mount_point: Path) -> int:
    """Resolve the configured path's remainder beneath ``start``, atomically."""
    remainder = os.path.relpath(root, mount_point)
    try:
        return open_contained(start, remainder, flags=_DIRECTORY_FLAGS)
    except AtomicDescentUnavailableError as exc:
        msg = (
            "this platform offers no atomic contained resolution, so the local-file "
            "fetch mechanism is unavailable on it (ADR-0230 §6)"
        )
        raise ConfigurationError(msg) from exc
    except OSError as exc:
        msg = (
            f"the fetch root could not be resolved beneath its own mount root: "
            f"{exc.strerror}. ADR-0230 §6 refuses a resolution that would cross a mount, "
            f"follow a symbolic link at any component, or escape above the start"
        )
        raise ConfigurationError(msg) from exc


def scan(root_fd: int, *, max_entries: int) -> list[_Listed]:
    """The root's supported direct children, newest first and capped. **Blocking**.

    Called only from a worker thread. A module-level function rather than a method so
    a suite can hold a listing at exactly the place a real one blocks — the pattern
    ``tests/readers/test_calendar_contract.py`` already uses for ``acquire``.

    **Direct children only**, decided on each entry's own ``lstat``: no recursion, no
    subdirectory traversal, and a symbolic link is skipped rather than followed, so a
    link pointing out of the root is not listed at all (ADR-0230 §6).

    **An unreadable root is an empty listing**, not an error — §6 makes an empty root
    and an unreadable one indistinguishable to every consumer.
    """
    listed: list[_Listed] = []
    try:
        with os.scandir(root_fd) as entries:
            for entry in entries:
                item = _listable(entry)
                if item is not None:
                    listed.append(item)
    except OSError:
        return []
    # Most recently modified first, with the name as the tie-break so that two files
    # written in the same nanosecond still produce one order rather than the
    # filesystem's. `handle` is minted over the position, so an unstable order would
    # make a listing's own labels unstable.
    listed.sort(key=lambda item: (-item.modified_ns, item.name))
    return listed[:max_entries]


def _listable(entry: os.DirEntry[str]) -> _Listed | None:
    """One directory entry as a listable file, or ``None`` where it is not one."""
    if _suffix_of(entry.name) not in SUPPORTED_SUFFIXES:
        return None
    try:
        entry.name.encode("utf-8")
    except UnicodeEncodeError:
        # A filename the platform holds as bytes that are not UTF-8 arrives as
        # surrogate escapes, which `EncodableText` refuses — so it is a name no
        # listing could carry rather than a file this seam declines to show.
        return None
    try:
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    try:
        modified_at = datetime.fromtimestamp(info.st_mtime, tz=UTC)
    except OSError, OverflowError, ValueError:
        # A modification instant outside what a `datetime` can hold, which
        # `UtcInstant` would refuse. Skipped rather than substituted: ADR-0092 §3's
        # rule against a nearly-right timestamp reaches a display field too.
        return None
    return _Listed(
        name=entry.name,
        size_bytes=max(info.st_size, 0),
        modified_at=modified_at,
        modified_ns=info.st_mtime_ns,
    )


def acquire(root_fd: int, name: str, *, max_bytes: int) -> bytes:
    """Open ``name`` beneath ``root_fd`` and return its bytes. **Blocking**.

    Resolution and acquisition are **one operation** (ADR-0230 §4): the contained
    open refuses a mount crossing, a symbolic link at any component and an escape
    above the root during resolution, and every remaining question — that it is a
    regular file, and that it is within the bound — is decided against **the object
    it has open**, never against a path or a ``stat`` taken before the open.

    **The read is itself bounded**, so a file that grew after its size was observed
    is refused rather than read: at most ``max_bytes + 1`` bytes are consumed, and
    the bound is never taken from the entry the caller was handed.

    Raises:
        _EntryNotFoundError: The named object is not there.
        _NotARegularFileError: It is not a regular file, whichever step found out.
        _UnreadableError: The open or the read failed for a reason that is not about
            the object's kind.
        _FileTooLargeError: The object supplied more than ``max_bytes``.
    """
    try:
        descriptor = open_contained(root_fd, name, flags=_ACQUIRE_FLAGS)
    except AtomicDescentUnavailableError as exc:  # pragma: no cover — refused at construction
        raise _UnreadableError from exc
    except OSError as exc:
        raise _classified(exc) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            msg = "the named object is not a regular file"
            raise _NotARegularFileError(msg)
        return _read_capped(descriptor, max_bytes)
    except OSError as exc:
        raise _UnreadableError from exc
    finally:
        with contextlib.suppress(OSError):
            os.close(descriptor)


def _classified(exc: OSError) -> Exception:
    """Which refusal an open's failure is, by **what the named object is**.

    ADR-0230 §4 draws the line by outcome rather than by step: "where the open
    refuses because the named object is not of a kind that can be opened as a file,
    the class is ``NOT_A_FILE``, and ``UNREADABLE`` is for a failure that is not
    about the object's kind — a permission denial, an I/O error, a resource limit".
    An implementation that classified only what it managed to open, and folded every
    open *failure* into ``UNREADABLE``, would pass the directory and FIFO cases and
    mis-class a Unix-domain socket while satisfying that sentence word for word.
    """
    if exc.errno == _ENOENT:
        return _EntryNotFoundError()
    if exc.errno in _KIND_ERRNOS:
        return _NotARegularFileError()
    return _UnreadableError()


def _read_capped(descriptor: int, max_bytes: int) -> bytes:
    """Read at most ``max_bytes + 1`` bytes, refusing as soon as the cap is passed."""
    chunks: list[bytes] = []
    consumed = 0
    # One byte of headroom, and no more: enough to *observe* that the object is over
    # the bound, never enough to hold a byte the bound forbids.
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(_CHUNK_BYTES, remaining))
        if not chunk:
            break
        consumed += len(chunk)
        if consumed > max_bytes:
            msg = "the named object is larger than the configured bound"
            raise _FileTooLargeError(msg)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
