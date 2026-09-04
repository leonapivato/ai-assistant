"""The fetch root's wiring: handed to the loop, and released on both paths.

ADR-0230 §14 item 23, and the join #2027 records.

Item 23 asks for three arms over ``app/composition.py``: "a built engine's ``aclose``
closes the fetcher, and a construction step that fails **after** the fetcher was built
closes it before the error propagates. Asserted **on the handle itself** — the
descriptor the fetcher held is closed — and not on a call count, and with a third arm
that repeated build-and-shutdown cycles leave no descriptor accumulating."

"This is ADR-0042 §2's *no half-built engine leaks a connection* asserted for this
resource, and it is the arm that fails on any wiring constructing a ``Fetcher``
without registering its ``close``."

**The descriptor is the subject rather than a mock**, because what §4 is about is a
number: "a fetcher wired outside that registration would pin its root's mount for the
life of the process and leak a descriptor per build". A call count would pass on a
wiring that called ``close`` on a second object.

**And the fetcher the root builds is the fetcher the loop reads from** (#2027,
ADR-0230 §3, §13). §13 assigns composition to Lane C1 and the loop's ``fetcher``
parameter to Lane C2, and named the joining line in neither — so a deployment could
(and for one merge did) construct a fetcher, hold its root handle open, and show no
listing to any planner. The arm below is the one that fails on that: it asserts the
**identity** of the two objects, because a second fetcher over the same root would
satisfy every other case in this file while pinning the mount twice and leaving the
one the loop read from outside the ordered shutdown.

**It is a structural arm and says so.** Driving a turn through a built engine would
need a ``ModelProvider``, and ``build_engine`` takes no seam for one; what is
checkable without it is which object the loop holds, which is exactly the fact #2027
is about. Every *behavioural* consequence of that object — the listing read once per
turn, the ordinal resolved into it, the record entering the fourth group — is asserted
over a ``LearningLoop`` under ``tests/orchestration/``.

**The platform view is supplied**, for ``tests/readers/fetch_fixtures.py``'s reason:
``ProcPlatformTables`` is fail-closed by decision, so a container's ``overlay`` root
or a CI runner's device chain may legitimately refuse — and a test of the *wiring* has
no business being decided by the machine it runs on.

**And every configured bound reaches the fetcher, which is its own arm** (ADR-0232 §9,
ADR-0234 §8, which repeats the clause for its own field in as many words: "without it an
operator's configured value reaches ``readers`` never, and the bound is a field nothing
enforces").
The bounds are passed explicitly here and the fetcher defaults each one, so a figure
left off this call site is not a build failure: it is an operator's configured value
silently ignored, while the field goes on validating at load and the fetcher goes on
enforcing a number nobody chose. The last arm in this file is the one that fails on
that, and it supplies the platform view a second way — patching the tables the *real*
:func:`~ai_assistant.app.composition._build_local_file_fetcher` builds for itself,
rather than standing in for that function — because a double reproducing the call site
cannot tell anyone whether the call site is right.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path as _Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "readers"))

from fetch_fixtures import vouching
from pdf_fixtures import bfrange_cmap, drawing, mapped_font_pages_pdf, pages_sharing_a_font

from ai_assistant.app import composition
from ai_assistant.app.composition import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import FetchRefusal
from ai_assistant.readers import LocalFileFetcher
from ai_assistant.readers import files as files_module

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A configured fetch root holding one document."""
    directory = tmp_path / "documents"
    directory.mkdir()
    (directory / "report.md").write_text("text", encoding="utf-8")
    return directory


@pytest.fixture
def vouched(monkeypatch: pytest.MonkeyPatch) -> list[LocalFileFetcher]:
    """Make every fetcher the composition root builds vouch for its own root.

    Returns the fetchers actually built, so an arm can read the descriptor off the
    object the wiring holds rather than off one of its own.
    """
    built: list[LocalFileFetcher] = []
    real = composition._build_local_file_fetcher

    def watched(settings: Settings) -> LocalFileFetcher | None:
        if settings.fetch_root_path is None:
            return real(settings)
        fetcher = LocalFileFetcher(
            settings.fetch_root_path,
            tables=vouching(settings.fetch_root_path),
            listing_ttl=settings.fetch_listing_ttl,
            listing_max_entries=settings.fetch_listing_max_entries,
            max_file_bytes=settings.fetch_max_file_bytes,
            max_content_bytes=settings.fetch_max_content_bytes,
            max_decoded_bytes=settings.fetch_max_decoded_bytes,
            max_character_mappings=settings.fetch_max_character_mappings,
        )
        built.append(fetcher)
        return fetcher

    monkeypatch.setattr(composition, "_build_local_file_fetcher", watched)
    return built


def _settings(root: Path | None) -> Settings:
    """A build's settings, with or without a fetch root."""
    return Settings(embedder=EmbedderKind.HASHING, fetch_root_path=root)


def _descriptor_of(fetcher: LocalFileFetcher) -> int:
    """The root handle the fetcher is holding, read off the object under test."""
    return fetcher._root  # the resource under test has no public reader


def _open_descriptors() -> int:
    """How many descriptors this process holds open, as Linux reports them."""
    return len(list(_Path("/proc/self/fd").iterdir()))


def _is_open(descriptor: int) -> bool:
    """Whether a descriptor still names an open object in this process."""
    try:
        os.fstat(descriptor)
    except OSError:
        return False
    return True


async def test_a_deployment_with_no_root_builds_no_fetcher(
    tmp_path: Path, vouched: list[LocalFileFetcher]
) -> None:
    """§6: "a deployment with no root configured constructs no fetcher".

    The shipping default, and a consent decision rather than a technical one: "nothing
    may read a user's personal files because a default said so".
    """
    engine = build_engine(_settings(None), data_dir=tmp_path / "data")
    await engine.aclose()

    assert vouched == []


async def test_a_built_engines_shutdown_closes_the_fetcher(
    tmp_path: Path, root: Path, vouched: list[LocalFileFetcher]
) -> None:
    """The first arm: ``aclose`` releases the root handle.

    Both directions are asserted, because only the pair is evidence: the descriptor is
    open *before* the shutdown — otherwise a build that opened nothing would satisfy
    the second half — and closed after it.
    """
    engine = build_engine(_settings(root), data_dir=tmp_path / "data")

    assert len(vouched) == 1
    descriptor = _descriptor_of(vouched[0])
    assert _is_open(descriptor)

    await engine.aclose()

    assert not _is_open(descriptor)


def test_a_construction_step_that_fails_after_the_fetcher_closes_it(
    tmp_path: Path, root: Path, vouched: list[LocalFileFetcher], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second arm: ADR-0042 §2's "no half-built engine leaks a connection".

    A step **after** the fetcher was built is made to fail, and the handle must be
    released before the error propagates — which is what registering ``close`` among
    the opened resources buys, and what a fetcher wired outside that registration would
    not have.

    The failing step is chosen for its position rather than its identity: what the arm
    is about is that *something later* failed, so any later step will do and naming one
    keeps the case readable.
    """
    failure = RuntimeError("a later construction step failed")

    def explode(*_args: object, **_kwargs: object) -> object:
        raise failure

    monkeypatch.setattr(composition, "_build_transcriber", explode)

    with pytest.raises(RuntimeError, match="a later construction step failed"):
        build_engine(_settings(root), data_dir=tmp_path / "data")

    assert len(vouched) == 1
    assert not _is_open(_descriptor_of(vouched[0]))


async def test_repeated_builds_accumulate_no_descriptor(
    tmp_path: Path, root: Path, vouched: list[LocalFileFetcher]
) -> None:
    """The third arm: the count, which is what §4's "leak a descriptor per build" is about.

    Asserted over the process's own open descriptors rather than over the fetchers'
    handles, because a wiring that closed each fetcher's handle and leaked something
    beside it would pass the first arm and fail the deployment.
    """
    before = _open_descriptors()

    for cycle in range(3):
        engine = build_engine(_settings(root), data_dir=tmp_path / f"data{cycle}")
        await engine.aclose()

    assert len(vouched) == 3
    assert all(not _is_open(_descriptor_of(fetcher)) for fetcher in vouched)
    # One descriptor of slack: the census reads `/proc/self/fd` through a descriptor of
    # its own, and the arm is about accumulation rather than about an exact number.
    assert _open_descriptors() <= before + 1


async def test_the_loop_reads_from_the_fetcher_this_root_built(
    tmp_path: Path, root: Path, vouched: list[LocalFileFetcher]
) -> None:
    """#2027: the constructed fetcher reaches ``LearningLoop``, and it is the same one.

    Without this line ``files`` is ``()`` on every production turn — the planner is
    never shown a listing, so no ``LOCAL_FILE`` ask it could emit resolves to anything,
    and ADR-0230's mechanism is inert in the one deployment that has a root.
    """
    engine = build_engine(_settings(root), data_dir=tmp_path / "data")
    try:
        assert len(vouched) == 1
        assert engine._loop._fetcher is vouched[0], (  # no public reader on either
            "the loop reads from the very object whose close this root registered"
        )
    finally:
        await engine.aclose()


async def test_a_deployment_with_no_root_leaves_the_loop_no_fetcher(tmp_path: Path) -> None:
    """ADR-0230 §3: ``None`` is the ordinary case and never an error.

    "A deployment with no ``Fetcher`` wired passes ``()``, renders no listing into any
    prompt, and can service no ``LOCAL_FILE`` ask." The negative half of the arm above,
    and what says the wiring is conditional on the configuration rather than on a
    default that happens to be unset.
    """
    engine = build_engine(_settings(None), data_dir=tmp_path / "data")
    try:
        assert engine._loop._fetcher is None  # no public reader on either
    finally:
        await engine.aclose()


@pytest.mark.parametrize("configured_below_the_documents_charge", [True, False])
async def test_a_configured_decoded_bound_reaches_the_fetcher(
    tmp_path: Path,
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured_below_the_documents_charge: bool,
) -> None:
    """ADR-0232 §9's wiring clause, over the **real** builder and over behaviour.

    "Without it an operator's configured value reaches ``readers`` never, and the bound
    is a field nothing enforces." ``LocalFileFetcher`` defaults every figure, so a bound
    missing from ``_build_local_file_fetcher`` builds and runs and refuses nothing an
    operator asked it to — which is why this arm cannot be a call-count or a keyword
    assertion and cannot go through the ``vouched`` double above: both would be
    asserting about a copy of the call site rather than about the call site.

    So the *real* builder runs, with the platform view supplied by patching the tables
    it constructs for itself, and the same document is fetched under two configured
    values either side of its counted quantity. Only the pair is evidence: the refusal
    alone would pass on a fetcher refusing everything, and the fetch alone on one
    refusing nothing — and **both** values are non-default, so a wiring that dropped the
    figure would take the 1 MiB default and admit the document in both directions.
    """
    document = pages_sharing_a_font([drawing(10_000)])
    (root / "drawn.pdf").write_bytes(document)
    charge = len(drawing(10_000))
    assert charge < 1024 * 1024, "the shipped default must admit this document"
    configured = charge - 1 if configured_below_the_documents_charge else charge

    monkeypatch.setattr(files_module, "ProcPlatformTables", lambda: vouching(root))
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        fetch_root_path=root,
        fetch_max_decoded_bytes=configured,
    )
    fetcher = composition._build_local_file_fetcher(settings)

    assert fetcher is not None
    try:
        listing = await fetcher.listing()
        entry = next(one for one in listing.entries if one.name == "drawn.pdf")
        outcome = await fetcher.fetch(listing, entry)
    finally:
        fetcher.close()

    if configured_below_the_documents_charge:
        assert outcome.refusal is FetchRefusal.TOO_LARGE
        assert outcome.record is None
    else:
        assert outcome.refusal is None
        assert outcome.record is not None


@pytest.mark.parametrize("configured_below_the_documents_charge", [True, False])
async def test_a_configured_mapping_bound_reaches_the_fetcher(
    tmp_path: Path,
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured_below_the_documents_charge: bool,
) -> None:
    """ADR-0234 §8's wiring clause, over the **real** builder and over behaviour.

    The sibling of the arm above, one field over, and it needs its own document rather
    than sharing that one: a page of drawing operators builds no ``/ToUnicode`` mapping
    at all, so it could not tell a wired mapping bound from an unwired one. This document
    carries a font whose ``/ToUnicode`` is 178 bytes of ``bfrange`` declaring a thousand
    mappings — a quantity the *byte* bound cannot see, which is the whole reason
    ADR-0234 §2 makes it a second field and the reason a second wiring arm is owed.

    Both configured values are non-default, so a wiring that dropped the figure would
    take the 400,000 default and admit the document in both directions; and only the pair
    is evidence, since the refusal alone would pass on a fetcher refusing everything.
    """
    cmap = bfrange_cmap(1_000)
    document = mapped_font_pages_pdf(pages=1, cmap=cmap)
    (root / "mapped.pdf").write_bytes(document)
    charge = 1_000
    assert charge < 400_000, "the shipped default must admit this document"
    configured = charge - 1 if configured_below_the_documents_charge else charge

    monkeypatch.setattr(files_module, "ProcPlatformTables", lambda: vouching(root))
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        fetch_root_path=root,
        fetch_max_character_mappings=configured,
    )
    fetcher = composition._build_local_file_fetcher(settings)

    assert fetcher is not None
    try:
        listing = await fetcher.listing()
        entry = next(one for one in listing.entries if one.name == "mapped.pdf")
        outcome = await fetcher.fetch(listing, entry)
    finally:
        fetcher.close()

    if configured_below_the_documents_charge:
        assert outcome.refusal is FetchRefusal.TOO_LARGE
        assert outcome.record is None
    else:
        assert outcome.refusal is None
        assert outcome.record is not None
