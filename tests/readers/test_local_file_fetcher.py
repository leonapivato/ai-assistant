"""LocalFileFetcher passes the shared Fetcher suite, plus the clauses only it can.

The binding is the point of a *shared* suite: a clause either binds every
implementation or binds none, so the concrete fetcher is held to exactly what the
canonical fake is held to (``tests/testing/test_fake_fetcher.py``).

Below the binding are the obligations ADR-0230 §13 names as **not** suite clauses and
hands to this lane. Three of the four live here — the listing's order and cap, and
every ``FetchRefusal`` member reached from a **real** source over a **real**
filesystem — and the fourth, §4's race transitions and the escapes from the root, is
``test_fetcher_races.py``, which needs its own scaffolding. ADR-0230 §14 item 22's
nine construction arms are ``test_fetcher_locality.py``'s.
"""

from __future__ import annotations

import asyncio
import os
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path as _Path
from typing import TYPE_CHECKING

import pypdf
import pytest
from fetch_fixtures import fetcher as build
from pdf_fixtures import extracted_text_of, minimal_pdf

sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "core"))

from fetcher_contract import ClockedFetcher, Dial, FetcherContract, GatedFetch, wall_of

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import FetchRefusal
from ai_assistant.readers import FILE_FETCHER_NAME, LocalFileFetcher
from ai_assistant.readers import files as files_module
from ai_assistant.testing.cancellation import ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import Fetcher

#: A distinctive string, used twice: once so a document has something quotable in it,
#: and once so a case can prove it did not reach a record.
DISTINCTIVE = "Ipsissima verba stroopwafel"

#: The TTL the clocked subject is built with, chosen distinct from ADR-0230 §4's
#: five-minute default so a case stepping "past the TTL" steps past *this* subject's.
_TTL = timedelta(minutes=3)


def populate(root: Path) -> Path:
    """Two supported files under ``root``, newest last written."""
    (root / "older.txt").write_text("beta", encoding="utf-8")
    (root / "newest.md").write_text(f"# alpha\n{DISTINCTIVE}", encoding="utf-8")
    return root


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A directory of this test's own, since the fetcher holds a handle on one."""
    directory = tmp_path / "documents"
    directory.mkdir()
    return directory


class TestLocalFileFetcherContract(FetcherContract):
    """Runs LocalFileFetcher through the shared Fetcher conformance suite."""

    @pytest.fixture(autouse=True)
    def _levers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # `clocked` and `gated` are plain methods rather than fixtures, so the two
        # levers they need are parked here where pytest can still undo the patch.
        self._tmp = tmp_path
        self._monkeypatch = monkeypatch

    @pytest.fixture
    def fetcher(self, root: Path) -> Iterator[Fetcher]:
        subject = build(populate(root))
        yield subject
        subject.close()

    @pytest.fixture
    def empty_fetcher(self, tmp_path: Path) -> Iterator[Fetcher]:
        empty = tmp_path / "empty"
        empty.mkdir()
        subject = build(empty)
        yield subject
        subject.close()

    def clocked(self) -> ClockedFetcher:
        directory = self._tmp / f"clocked-{id(self):x}-{len(str(self._tmp))}"
        directory.mkdir(exist_ok=True)
        populate(directory)
        wall = Dial(datetime(2026, 3, 1, 9, 0, tzinfo=UTC).timestamp())
        monotonic = Dial(0)
        return ClockedFetcher(
            fetcher=build(
                directory,
                now=lambda: wall_of(wall),
                monotonic=lambda: int(monotonic.read()),
                listing_ttl=_TTL,
            ),
            ttl=_TTL,
            wall=wall,
            monotonic=monotonic,
        )

    def gated(self) -> GatedFetch:
        """The two blocking calls, each held where a real one blocks.

        Suspending :func:`~ai_assistant.readers.files.scan` and
        :func:`~ai_assistant.readers.files.acquire` rather than contriving a slow
        directory is what makes the case deterministic — and it holds each call at
        exactly the place a real one blocks, on the worker thread, which is the code
        the cancellation clause is about (``test_calendar_contract.py`` makes the same
        move for the same reason).
        """
        directory = self._tmp / "gated"
        directory.mkdir(exist_ok=True)
        populate(directory)
        subject = build(directory)
        return GatedFetch(
            fetcher=subject,
            arm_listing=lambda: self._suspend("scan", files_module.scan),
            arm_fetch=lambda: self._suspend("acquire", files_module.acquire),
        )

    def _suspend(self, name: str, real: object) -> ThreadSuspension:
        """Patch one of the module's blocking calls to hold before it runs."""
        suspension = ThreadSuspension()

        def held(*args: object, **kwargs: object) -> object:
            suspension.hold()
            return real(*args, **kwargs)  # type: ignore[operator]

        self._monkeypatch.setattr(files_module, name, held)
        return suspension


# --- the identity half the shared suite cannot reach (ADR-0190 §3) ----------


def test_the_declared_half_of_the_identity_is_this_fetchers_own_name(root: Path) -> None:
    """The suite decides §4's *form*; only this file can decide the *type*.

    ADR-0190 §3 names this division in advance and says why a suite cannot reach it:
    it holds a ``Fetcher`` and nothing to compare a prefix against, so an
    implementation declaring a colon-bearing name merely *shaped* like a discriminated
    identity passes there while breaching §4.

    ``LocalFileFetcher`` returns a bare identity today, because a deployment configures
    one fetch root (ADR-0230 §6) and the first configured source of a type may hold
    that type's bare name.
    """
    subject = build(root)
    try:
        assert subject.name == FILE_FETCHER_NAME
        assert ":" not in subject.name
        assert subject.name == subject.name.strip()
    finally:
        subject.close()


# --- the listing: bounded, ordered and declared (ADR-0230 §14 item 16) ------


async def test_the_listing_is_ordered_most_recently_modified_first(root: Path) -> None:
    """The clause ADR-0230 §13 keeps out of the suite, decided where it can be.

    §6's ordering is chosen so that "the case the exit names, a file saved yesterday,
    is the case the bound serves best", which is a property of *this* implementation's
    read of the filesystem rather than of any ``Fetcher``.
    """
    for index, name in enumerate(["oldest.txt", "middle.md", "newest.txt"]):
        path = root / name
        path.write_text("x", encoding="utf-8")
        os.utime(path, (1_700_000_000 + index * 60, 1_700_000_000 + index * 60))
    subject = build(root)
    try:
        listing = await subject.listing()
    finally:
        subject.close()

    assert [entry.name for entry in listing.entries] == ["newest.txt", "middle.md", "oldest.txt"]


async def test_the_listing_shows_exactly_the_cap(root: Path) -> None:
    """A root holding more than the cap lists the cap's worth, newest first (§6)."""
    for index in range(7):
        path = root / f"file{index}.txt"
        path.write_text("x", encoding="utf-8")
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
    subject = build(root, listing_max_entries=3)
    try:
        listing = await subject.listing()
    finally:
        subject.close()

    assert [entry.name for entry in listing.entries] == ["file6.txt", "file5.txt", "file4.txt"]


async def test_unsupported_types_directories_and_symlinks_are_not_listed(root: Path) -> None:
    """§6's allow-list, applied where the listing is built, and §6's direct-children rule.

    Applying the allow-list *here* is what makes ``UNSUPPORTED_TYPE`` unnecessary: "the
    only caller who can name an unsupported file is one presenting an entry this
    fetcher never minted", and §4 rules that refusal ``NOT_FOUND``.
    """
    (root / "kept.md").write_text("shown", encoding="utf-8")
    (root / "notes.docx").write_text("hidden", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "buried.txt").write_text("deep", encoding="utf-8")
    (root / "elsewhere.txt").symlink_to("/etc/hostname")
    subject = build(root)
    try:
        listing = await subject.listing()
    finally:
        subject.close()

    assert [entry.name for entry in listing.entries] == ["kept.md"]


async def test_an_empty_root_and_an_unreadable_one_are_indistinguishable(
    tmp_path: Path,
) -> None:
    """§6: "a root that cannot be read and an empty root both produce an empty listing".

    The unreadable root is made so **after** construction, because a root that could
    not be opened at construction would refuse to wire at all — which is a different
    clause and a different outcome.
    """
    if os.geteuid() == 0:
        pytest.skip("a permission denial cannot be staged as root")
    empty = tmp_path / "empty"
    empty.mkdir()
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    (unreadable / "hidden.md").write_text(DISTINCTIVE, encoding="utf-8")
    first = build(empty)
    second = build(unreadable)
    try:
        unreadable.chmod(0o000)
        one = await first.listing()
        other = await second.listing()
    finally:
        unreadable.chmod(0o700)
        first.close()
        second.close()

    assert one.entries == ()
    assert other.entries == ()


# --- the three formats, and refusing rather than truncating -----------------


async def test_a_pdfs_text_reaches_the_record_verbatim(root: Path) -> None:
    """ADR-0230 §5: extraction is a **decoding** and the record's content is verbatim.

    The one line of ADR-0230 that costs a dependency, asserted end to end: a real PDF
    under the root, extracted by the adopted library, arriving as a record whose
    content is the document's text and nothing else.
    """
    lines = [DISTINCTIVE, "second line"]
    (root / "report.pdf").write_bytes(minimal_pdf(lines))
    subject = build(root)
    try:
        listing = await subject.listing()
        outcome = await subject.fetch(listing, listing.entries[0])
    finally:
        subject.close()

    assert outcome.record is not None
    assert outcome.record.content == extracted_text_of(lines)


@pytest.mark.parametrize("name", ["notes.md", "notes.markdown", "notes.txt"])
async def test_a_text_documents_source_is_its_text(root: Path, name: str) -> None:
    """Markdown is read as **source**, not rendered (ADR-0230 §5, §6).

    What §5 requires is the file's text verbatim, and a Markdown document's text is
    its source: a renderer here would be the "rendering" §5 rules extraction is not.
    """
    (root / name).write_text(f"# heading\n\n*{DISTINCTIVE}*\n", encoding="utf-8")
    subject = build(root)
    try:
        listing = await subject.listing()
        outcome = await subject.fetch(listing, listing.entries[0])
    finally:
        subject.close()

    assert outcome.record is not None
    assert outcome.record.content == f"# heading\n\n*{DISTINCTIVE}*\n"


async def test_a_file_over_the_size_bound_is_refused_and_nothing_is_truncated(
    root: Path,
) -> None:
    """§6: "A bound is enforced by refusing, never by truncating"."""
    (root / "big.txt").write_text(DISTINCTIVE * 100, encoding="utf-8")
    subject = build(root, max_file_bytes=64)
    try:
        listing = await subject.listing()
        outcome = await subject.fetch(listing, listing.entries[0])
    finally:
        subject.close()

    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert outcome.record is None


async def test_the_content_bound_is_counted_on_the_quoted_rendering(root: Path) -> None:
    """§6's astral arms, which a source-character or source-byte bound fails.

    An emoji is one source character and **twelve** rendered ones, because
    ``json.dumps`` at ``ensure_ascii=True`` writes it as two surrogate escapes. So a
    bound counted on the source would admit a span twelve times what it claims, which
    ADR-0222 §4 ruled on for a rendered reply and §6 takes for its own.

    Three files rather than three fetchers, each named for what it is: one whose
    rendering is exactly the bound, one a single character over, and one whose *source*
    is well inside the bound while its rendering is not.
    """
    at_limit = "\U0001f600" * 4
    (root / "exact.txt").write_text(at_limit, encoding="utf-8")
    (root / "over.txt").write_text(at_limit + "\U0001f600", encoding="utf-8")
    # Four emoji at twelve rendered characters each, plus the two delimiters §6
    # counts. Written out rather than computed with `json.dumps`, so the arm asserts
    # against the ADR's own arithmetic rather than against the implementation's.
    bound = 4 * 12 + 2
    subject = build(root, max_content_bytes=bound)
    try:
        listing = await subject.listing()
        by_name = {entry.name: entry for entry in listing.entries}
        exact = await subject.fetch(listing, by_name["exact.txt"])
        over = await subject.fetch(listing, by_name["over.txt"])
    finally:
        subject.close()

    assert exact.record is not None
    assert exact.record.content == at_limit
    assert over.refusal is FetchRefusal.TOO_LARGE


# --- every refusal class, from a real source (ADR-0230 §14 item 9) ----------


async def test_a_listed_file_deleted_before_the_fetch_is_not_found(root: Path) -> None:
    """``NOT_FOUND`` from a real absence, which is §4's reason for the shared class."""
    populate(root)
    subject = build(root)
    try:
        listing = await subject.listing()
        (root / listing.entries[0].name).unlink()
        outcome = await subject.fetch(listing, listing.entries[0])
    finally:
        subject.close()

    assert outcome.refusal is FetchRefusal.NOT_FOUND


async def test_a_listed_file_replaced_by_a_directory_is_not_a_file(root: Path) -> None:
    """``NOT_A_FILE`` from an object the open succeeds on and the kind check refuses."""
    (root / "report.md").write_text("text", encoding="utf-8")
    subject = build(root)
    try:
        listing = await subject.listing()
        (root / "report.md").unlink()
        (root / "report.md").mkdir()
        outcome = await subject.fetch(listing, listing.entries[0])
    finally:
        subject.close()

    assert outcome.refusal is FetchRefusal.NOT_A_FILE


async def test_a_listed_file_made_unreadable_is_unreadable(root: Path) -> None:
    """``UNREADABLE`` from a permission denial — a failure that is **not** about kind.

    The class that an implementation folding every open failure into it would over-use,
    and the one ``test_fetcher_races.py``'s socket arm exists to keep honest.
    """
    if os.geteuid() == 0:
        pytest.skip("a permission denial cannot be staged as root")
    path = root / "private.txt"
    path.write_text(DISTINCTIVE, encoding="utf-8")
    subject = build(root)
    try:
        listing = await subject.listing()
        path.chmod(0o000)
        outcome = await subject.fetch(listing, listing.entries[0])
    finally:
        path.chmod(0o600)
        subject.close()

    assert outcome.refusal is FetchRefusal.UNREADABLE


async def test_a_listed_file_grown_past_the_bound_is_too_large(root: Path) -> None:
    """``TOO_LARGE`` from a real growth, and §6 re-applies the bound at ``fetch``.

    "No implementation reads a bound, a type or a size off the entry it was handed" —
    so the entry the fetch is given still says four bytes while the object says more.
    """
    path = root / "growing.txt"
    path.write_text("tiny", encoding="utf-8")
    subject = build(root, max_file_bytes=32)
    try:
        listing = await subject.listing()
        assert listing.entries[0].size_bytes == 4
        path.write_text("x" * 200, encoding="utf-8")
        outcome = await subject.fetch(listing, listing.entries[0])
    finally:
        subject.close()

    assert outcome.refusal is FetchRefusal.TOO_LARGE


@pytest.mark.parametrize(
    ("name", "content"),
    [("broken.txt", b"\xff\xfe\x00 not utf-8"), ("broken.pdf", b"this is not a PDF at all")],
)
async def test_a_supported_file_whose_extraction_fails_is_refused(
    root: Path, name: str, content: bytes
) -> None:
    """``EXTRACTION_FAILED`` — the fifth member, reached from a real source.

    Both arms are files of a **supported** format: the suffix is what the listing
    decides on, so a document whose bytes are not what its suffix names is listed and
    then refuses. A decode substituting replacement characters would put text in a
    record that is not what the file holds, which §5's "verbatim" forbids.
    """
    (root / name).write_bytes(content)
    subject = build(root)
    try:
        listing = await subject.listing()
        outcome = await subject.fetch(listing, listing.entries[0])
    finally:
        subject.close()

    assert outcome.refusal is FetchRefusal.EXTRACTION_FAILED


async def test_an_unsupported_file_is_refused_not_found_and_not_by_a_class_of_its_own(
    root: Path,
) -> None:
    """§14 item 9's arm in the other direction: no sixth ``FetchRefusal`` member.

    A ``.docx`` under the root appears in no listing, so the only way to name it is an
    entry the fetcher never minted — and §4 rules that ``NOT_FOUND``, "deliberately
    the same class an absent file yields, so that it discloses nothing about whether a
    guessed name exists under the root". A distinct class would restore exactly that
    disclosure: it would answer *a file of that name is there, and it is a ``.docx``*
    to a caller holding nothing but a guess.
    """
    (root / "kept.md").write_text("shown", encoding="utf-8")
    (root / "secret.docx").write_bytes(b"PK\x03\x04 zip bytes")
    subject = build(root)
    try:
        listing = await subject.listing()
        assembled = listing.entries[0].model_copy(update={"name": "secret.docx"})
        outcome = await subject.fetch(listing, assembled)
    finally:
        subject.close()

    assert [entry.name for entry in listing.entries] == ["kept.md"]
    assert outcome.refusal is FetchRefusal.NOT_FOUND
    assert set(FetchRefusal) == {
        FetchRefusal.NOT_FOUND,
        FetchRefusal.NOT_A_FILE,
        FetchRefusal.UNREADABLE,
        FetchRefusal.TOO_LARGE,
        FetchRefusal.EXTRACTION_FAILED,
    }


# --- the root handle's life (ADR-0230 §4) -----------------------------------


async def test_a_closed_fetcher_lists_nothing_and_refuses_every_fetch(root: Path) -> None:
    """§4: "Where the handle's directory has been removed or can no longer be used,
    the listing is empty and every fetch refuses — never a read of the substitute"."""
    populate(root)
    subject = build(root)
    listing = await subject.listing()
    subject.close()

    assert (await subject.listing()).entries == ()
    assert (await subject.fetch(listing, listing.entries[0])).refusal is FetchRefusal.NOT_FOUND


def test_close_is_idempotent_and_releases_the_descriptor(root: Path) -> None:
    """The handle a composition root registers is released exactly once.

    Asserted on the descriptor itself rather than on a call count: ADR-0230 §4's
    concern is that a fetcher "would pin its root's mount for the life of the process
    and leak a descriptor per build", which is a fact about the number, not the call.
    """
    subject = build(root)
    descriptor = subject._root  # the resource under test has no public reader
    assert stat.S_ISDIR(os.fstat(descriptor).st_mode)

    subject.close()
    subject.close()

    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(descriptor)


# --- the constructor's own refusals (ADR-0230 §6) ---------------------------


@pytest.mark.parametrize(
    ("figure", "value"),
    [
        ("listing_ttl", timedelta(0)),
        ("listing_ttl", timedelta(seconds=-1)),
        ("listing_max_entries", 0),
        ("listing_max_entries", -1),
        ("max_file_bytes", 0),
        ("max_file_bytes", -1),
        ("max_content_bytes", 0),
        ("max_content_bytes", -1),
    ],
)
def test_a_bound_outside_its_domain_refuses_the_construction(
    root: Path, figure: str, value: object
) -> None:
    """§6 states the domain and ``Settings`` refuses at load; this is the second seam.

    "A guard that only fires when a caller remembered to ask is not a guard": the
    constructor is reachable by a test and by a second composition root, so it states
    the same rules again (ADR-0093 §5).
    """
    with pytest.raises(ConfigurationError, match=r"ADR-0230 §6"):
        build(root, **{figure: value})  # type: ignore[arg-type]


def test_a_relative_root_refuses_the_construction(tmp_path: Path) -> None:
    """A relative value resolves against each process's working directory.

    So the hub started at boot and a test run from a project directory would read the
    same setting and open different directories — which is why absoluteness is a
    property of the *configuration* and is decided before anything is opened.
    """
    with pytest.raises(ConfigurationError, match="absolute"):
        LocalFileFetcher(_Path("documents"))


async def test_a_fetch_never_blocks_the_event_loop_for_the_whole_read(root: Path) -> None:
    """The blocking work runs off the loop, so a turn's other awaits still run.

    Not a performance claim: ADR-0230 §4 requires that a fetch reach an outcome, and
    the extraction of a large PDF on the loop would stall every concurrent turn in the
    hub. Asserted by observing that a second coroutine makes progress while a fetch is
    outstanding, which is only possible if the fetch yielded.
    """
    (root / "report.pdf").write_bytes(minimal_pdf([DISTINCTIVE] * 40))
    subject = build(root)
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)

    try:
        listing = await subject.listing()
        ticker = asyncio.ensure_future(tick())
        outcome = await subject.fetch(listing, listing.entries[0])
        ticker.cancel()
    finally:
        subject.close()

    assert outcome.record is not None
    assert ticks > 0


# --- the instants a record carries (ADR-0230 §5) ----------------------------


async def test_a_records_instants_are_taken_when_the_file_was_read(root: Path) -> None:
    """§5: ``reported_at`` is **the instant the file was read**, not the call's.

    The clock is read on the worker thread the moment the bounded read returns, so a
    thread-pool backlog between the call and the acquisition cannot stamp the record
    with an instant that precedes the read. §5's whole argument for admitting this
    instant at all is that "'when the source said so' and 'when we read it' are one
    event rather than two facts of which one stands in for the other", and a value
    taken before the read is exactly the second of those.

    Staged deterministically by advancing the clock **inside** the acquisition: the
    dial reads one instant when ``fetch`` is entered and a later one by the time the
    bytes are in hand, so a record stamped at either is distinguishable from a record
    stamped at the other.
    """
    (root / "report.md").write_text(DISTINCTIVE, encoding="utf-8")
    entered = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    acquired = datetime(2026, 3, 1, 9, 5, tzinfo=UTC)
    dial = Dial(entered.timestamp())
    real = files_module.acquire

    def slow(*args: object, **kwargs: object) -> bytes:
        data = real(*args, **kwargs)  # type: ignore[arg-type]
        dial.set(acquired.timestamp())
        return data

    subject = build(root, now=lambda: wall_of(dial))
    try:
        listing = await subject.listing()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(files_module, "acquire", slow)
            outcome = await subject.fetch(listing, listing.entries[0])
    finally:
        subject.close()

    record = outcome.record
    assert record is not None
    attestation = record.provenance.attestation
    assert attestation is not None
    assert attestation.reported_at == acquired
    assert record.provenance.last_updated == acquired
    assert record.provenance.last_confirmed_at == acquired


async def test_a_listings_read_at_is_taken_when_the_directory_was_read(root: Path) -> None:
    """§4: ``read_at`` is "captured once **at acquisition**", not at the call.

    The neighbouring half of the clause above, on the other member: a listing stamped
    before the directory was read would claim a state of the root that did not exist
    yet, and would start both expiry deadlines before the entries it vouches for were
    observed.
    """
    populate(root)
    entered = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    acquired = datetime(2026, 3, 1, 9, 5, tzinfo=UTC)
    dial = Dial(entered.timestamp())
    real = files_module.scan

    def slow(*args: object, **kwargs: object) -> object:
        listed = real(*args, **kwargs)  # type: ignore[arg-type]
        dial.set(acquired.timestamp())
        return listed

    subject = build(root, now=lambda: wall_of(dial))
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(files_module, "scan", slow)
            listing = await subject.listing()
    finally:
        subject.close()

    assert listing.read_at == acquired


# --- the extraction's own cost (ADR-0230 §6) --------------------------------


async def test_an_over_bound_pdf_stops_without_extracting_every_page(root: Path) -> None:
    """§6: the bound is enforced **while** extracting, not after.

    Asserted over the pages actually extracted rather than over the class returned,
    because the class is what an implementation that read every page and *then* refused
    would also return. What separates the two is how much work was done before the
    refusal, and that is what this counts.

    Counted on ``pypdf``'s **own** ``PageObject.extract_text``, not on a substituted
    page collection: a double in place of the library's would exercise this test's
    scaffolding rather than the path a real document takes.

    The document is over the content bound from its first page, so a conforming
    implementation stops within a page or two of a forty-page document.
    """
    (root / "long.pdf").write_bytes(minimal_pdf([DISTINCTIVE * 20] * 40))
    extracted: list[object] = []
    real = pypdf.PageObject.extract_text

    def counted(self: object, *args: object, **kwargs: object) -> str:
        extracted.append(self)
        return real(self, *args, **kwargs)  # type: ignore[arg-type]

    subject = build(root, max_content_bytes=64)
    try:
        listing = await subject.listing()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(pypdf.PageObject, "extract_text", counted)
            outcome = await subject.fetch(listing, listing.entries[0])
    finally:
        subject.close()

    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert 0 < len(extracted) < 5, (
        f"extracted {len(extracted)} pages of a 40-page document before refusing; "
        f"§6 requires the bound be applied while extracting rather than after"
    )


async def test_a_pdf_inside_the_bound_extracts_every_page(root: Path) -> None:
    """The arm in the other direction, so the count above is not trivially satisfied.

    An implementation that stopped after one page would pass the case above and lose
    the rest of every document. What makes the pair evidence is that the same code
    reads all forty pages when the bound allows it.
    """
    lines = ["page one", "page two", "page three"]
    (root / "short.pdf").write_bytes(minimal_pdf(lines))
    subject = build(root)
    try:
        listing = await subject.listing()
        outcome = await subject.fetch(listing, listing.entries[0])
    finally:
        subject.close()

    assert outcome.record is not None
    assert outcome.record.content == extracted_text_of(lines)
