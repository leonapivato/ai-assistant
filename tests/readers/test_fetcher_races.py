"""The transitions ADR-0230 §4 admits are possible, refused (§13, §14 item 4).

These are the arms ADR-0230 §13 names as **not** suite clauses and hands to the
concrete fetcher: "a generic suite cannot replace an arbitrary fetcher's root, so
these arms are the concrete fetcher's and not the suite's". Each is over a **real**
filesystem, and each is a transition the ADR states is possible rather than one this
implementation happens to be able to stage.

**Where the transition lands, and why that is exact rather than approximate.** §14
item 4 asks that each land "**between** the fetcher's validation and its
acquisition". In this implementation that window is empty by construction —
verification is a keyed digest over values already in hand and touches no filesystem
state, so the next thing to reach the kernel *is* the acquiring open. The arms below
land the transition inside :func:`~ai_assistant.readers.files.acquire`'s own call
site anyway, by patching the module's blocking entry point to mutate the root and
then call the real one: that is the window, named exactly, rather than a mutation
before ``fetch`` that would land in the same place by accident.

**Nothing here asserts only the returned class.** Each arm also asserts that the
substituted object's own distinctive text reached nothing, because "None of the three
yields a record mixing one object's metadata with another's content" is the property,
and a refusal that had read the wrong file first would satisfy the class assertion
alone.
"""

from __future__ import annotations

import asyncio
import os
import socket
from typing import TYPE_CHECKING, Final

import pytest
from fetch_fixtures import fetcher as build

from ai_assistant.core.types import FetchRefusal
from ai_assistant.readers import files as files_module

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ai_assistant.core.types import FetchOutcome
    from ai_assistant.readers.files import LocalFileFetcher

#: What sits in the file the fetch was *shown*.
LISTED = "the document the listing showed"

#: What sits in the object substituted for it. It must appear nowhere.
SUBSTITUTED = "Bezugloe Vyshegorodskoe substituted content"

#: The deadline the named-pipe arm fails on. "A hang is not a wrong answer this suite
#: could otherwise observe" (§14 item 4), so the arm is asserted under a clock rather
#: than by inspecting the class alone — and it is the arm that fails on any
#: implementation whose acquiring open is not non-blocking.
_NO_HANG: Final = 5.0


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A directory of this test's own, holding one listed document."""
    directory = tmp_path / "documents"
    directory.mkdir()
    (directory / "report.txt").write_text(LISTED, encoding="utf-8")
    return directory


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A directory **outside** the root, holding a file of the same name."""
    directory = tmp_path / "outside"
    directory.mkdir()
    (directory / "report.txt").write_text(SUBSTITUTED, encoding="utf-8")
    return directory


@pytest.fixture
def transition(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable[[], None]], None]:
    """Arms one mutation to run **between** the fetch's validation and its acquisition.

    Patches the module's blocking entry point rather than reaching into the fetcher,
    which is the pattern ``test_calendar_contract.py`` established for its own gate:
    the transition lands at the one place the ADR names, and the real acquisition runs
    immediately after it on the same thread.
    """
    real = files_module.acquire
    armed: list[Callable[[], None]] = []

    def held(*args: object, **kwargs: object) -> bytes:
        while armed:
            armed.pop()()
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(files_module, "acquire", held)
    return armed.append


async def _fetch_once(subject: LocalFileFetcher, *, deadline: float | None = None) -> FetchOutcome:
    """List, then fetch the one entry, optionally under a deadline the arm fails on."""
    listing = await subject.listing()
    assert [entry.name for entry in listing.entries] == ["report.txt"]
    if deadline is None:
        return await subject.fetch(listing, listing.entries[0])
    async with asyncio.timeout(deadline):
        return await subject.fetch(listing, listing.entries[0])


def _assert_untouched(outcome: FetchOutcome) -> None:
    """No record here may carry the substituted object's text, whatever else it does."""
    if outcome.record is not None:
        assert SUBSTITUTED not in outcome.record.content


def _substitute_the_roots_pathname(root: Path, outside: Path) -> None:
    """Rename the configured root away and put a link to ``outside`` in its place."""
    root.rename(root.parent / "moved-away")
    root.symlink_to(outside, target_is_directory=True)


# --- §14 item 4's five transitions ------------------------------------------


async def test_a_file_replaced_by_a_symbolic_link_out_of_the_root_is_refused(
    root: Path, outside: Path, transition: Callable[[Callable[[], None]], None]
) -> None:
    """``NOT_A_FILE``, and nothing is read from the link's target.

    The contained resolution refuses a symbolic link at **every** component, so the
    link is not followed rather than followed-and-then-rejected — which is the
    difference between reading the outside file and never reaching it.
    """
    subject = build(root)
    listed = root / "report.txt"

    def swap() -> None:
        listed.unlink()
        listed.symlink_to(outside / "report.txt")

    transition(swap)
    try:
        outcome = await _fetch_once(subject)
    finally:
        subject.close()

    assert outcome.refusal is FetchRefusal.NOT_A_FILE
    _assert_untouched(outcome)


async def test_a_file_that_grows_past_the_bound_is_refused_with_no_prefix_kept(
    root: Path, transition: Callable[[Callable[[], None]], None]
) -> None:
    """``TOO_LARGE``, and no prefix of the grown content goes anywhere.

    §4: "An implementation reads at most ``fetch_max_file_bytes`` plus one byte from
    the open object and refuses as ``TOO_LARGE`` where the object supplies more; it
    does not decide the bound from a size it observed earlier and then read to end of
    file."
    """
    subject = build(root, max_file_bytes=128)
    listed = root / "report.txt"

    def grow() -> None:
        listed.write_text(SUBSTITUTED * 50, encoding="utf-8")

    transition(grow)
    try:
        outcome = await _fetch_once(subject)
    finally:
        subject.close()

    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert outcome.record is None


async def test_the_roots_own_pathname_replaced_by_a_link_reaches_the_original(
    root: Path, outside: Path
) -> None:
    """The arm that fails any implementation storing the root as a pathname (§4).

    "List ``report.txt`` under the configured root, then rename the root away and put
    a symbolic link of its pathname in its place pointing at an outside directory
    holding another ``report.txt``, and the next fetch follows the substituted root and
    reads the outside file — while satisfying the membership check, the deadlines, the
    final-component clause and the bounded read, every one of them."

    Here the handle is a reference to the directory itself rather than to a name for
    it, so "the handle goes on naming the directory the operator configured, and
    whatever now occupies the pathname is never reached". The fetch therefore either
    reads the original object or refuses; what it may never do is read the outside one.

    The transition is staged **between the listing and the fetch**, which is where §14
    item 4 puts it — the root's pathname is not consulted at fetch time at all, so
    there is no narrower window to aim at.
    """
    subject = build(root)
    try:
        listing = await subject.listing()
        _substitute_the_roots_pathname(root, outside)
        outcome = await subject.fetch(listing, listing.entries[0])
    finally:
        subject.close()

    assert outcome.record is None or outcome.record.content == LISTED
    _assert_untouched(outcome)


async def test_a_file_replaced_by_a_named_pipe_refuses_within_the_turn(
    root: Path, transition: Callable[[Callable[[], None]], None]
) -> None:
    """``NOT_A_FILE`` **under a deadline**, not a wedged call (§4, §14 item 4).

    "An ordinary read-mode open of a FIFO with no writer **blocks until a writer
    arrives**", so an implementation that opened and only then asked what it was
    holding would return neither a record nor a refusal — "the one outcome §6 says a
    fetch never has". The acquiring open is non-blocking, which costs a regular file
    nothing.

    The deadline is what makes this arm reach the property: an assertion about the
    *returned* class cannot observe a call that never returns.
    """
    subject = build(root)
    listed = root / "report.txt"

    def swap() -> None:
        listed.unlink()
        os.mkfifo(listed)

    transition(swap)
    try:
        outcome = await _fetch_once(subject, deadline=_NO_HANG)
    finally:
        subject.close()

    assert outcome.refusal is FetchRefusal.NOT_A_FILE


async def test_a_file_replaced_by_a_unix_socket_is_not_a_file_and_not_unreadable(
    root: Path, transition: Callable[[Callable[[], None]], None]
) -> None:
    """The kind that cannot be held at all, classed by **what it is** (§4, §14 item 4).

    "Opening a Unix-domain socket by its pathname fails rather than yielding a
    descriptor there is anything to inspect — Linux answers ``ENXIO``." This is the arm
    that fails on any implementation classifying only what it managed to open and
    folding every open *failure* into ``UNREADABLE``, "which passes the directory and
    FIFO arms while mis-classing this one".
    """
    subject = build(root)
    listed = root / "report.txt"
    endpoint = socket.socket(socket.AF_UNIX)

    def swap() -> None:
        listed.unlink()
        endpoint.bind(str(listed))

    transition(swap)
    try:
        outcome = await _fetch_once(subject)
    finally:
        endpoint.close()
        subject.close()

    assert outcome.refusal is FetchRefusal.NOT_A_FILE


# --- the escapes from the root (ADR-0230 §13, §14 item 2) -------------------


@pytest.mark.parametrize("name", ["../report.txt", "sub/report.txt", "..", "."])
async def test_a_name_that_is_not_one_component_is_refused_before_any_filesystem_call(
    root: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """§4 refuses "a name carrying a directory separator or a parent reference".

    Asserted **as a refusal and as an absence of a call**, because §2's property is the
    stronger of the two: "it never constructs a path, never joins a model-supplied
    fragment to a root, and never hands a model-supplied string to any filesystem
    call". A test asserting only the class would pass on an implementation that tried
    the open and was saved by the kernel.

    Unreachable through an authentic entry — the listing mints one name per directory
    entry — so the entry here is one the test assembled, which is refused for its
    handle before the name is even read. Both refusals are ``NOT_FOUND``, which is
    exactly §4's point about disclosing nothing.
    """
    subject = build(root)
    reached: list[str] = []

    def record(_root_fd: int, entry_name: str, **_bounds: int) -> bytes:
        reached.append(entry_name)
        return b""

    monkeypatch.setattr(files_module, "acquire", record)
    try:
        listing = await subject.listing()
        outcome = await subject.fetch(listing, listing.entries[0].model_copy(update={"name": name}))
    finally:
        subject.close()

    assert outcome.refusal is FetchRefusal.NOT_FOUND
    assert reached == []


async def test_a_symbolic_link_out_of_the_root_is_never_listed_and_never_fetched(
    root: Path, outside: Path
) -> None:
    """The static half of the escape, beside the racing half above (§13).

    A link is not a direct child this listing shows — §6 lists "no following of
    symbolic links out of the root" — so it is not listed, and an entry assembled for
    it is refused for its handle. Neither route reads the target.
    """
    (root / "elsewhere.txt").symlink_to(outside / "report.txt")
    subject = build(root)
    try:
        listing = await subject.listing()
        assembled = listing.entries[0].model_copy(update={"name": "elsewhere.txt"})
        outcome = await subject.fetch(listing, assembled)
    finally:
        subject.close()

    assert [entry.name for entry in listing.entries] == ["report.txt"]
    assert outcome.refusal is FetchRefusal.NOT_FOUND
    _assert_untouched(outcome)
