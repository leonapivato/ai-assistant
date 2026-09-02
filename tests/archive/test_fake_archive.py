"""The two canonical archive fakes, run through their shared suites (ADR-0225 §10).

One binding per Protocol, because the triad is per Protocol:
``FakeTranscriptArchiveWriter`` answers for ``TranscriptArchiveWriter`` and
``FakeTranscriptArchive`` for ``TranscriptArchive``. Neither answers for the other,
and that is the arrangement rather than an omission — the writer carries no read and
the archive carries no ``append``, so a holder of either cannot reach what §4
withholds from it even in a test.

Beside the contract runs, the cases at the bottom pin what is the *fakes'* own
business rather than the contract's: the failure lever, the window the suites look
through, and the seam disjointness that makes the two fakes two fakes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from transcript_archive_contracts import (
    NOW,
    TranscriptArchiveContract,
    TranscriptArchiveWriterContract,
    entry,
)

from ai_assistant.core.protocols import TranscriptArchive, TranscriptArchiveWriter
from ai_assistant.testing import FakeTranscriptArchive, FakeTranscriptArchiveWriter

if TYPE_CHECKING:
    from datetime import timedelta

    from ai_assistant.core.types import TranscriptEntry


class TestFakeTranscriptArchiveWriterContract(TranscriptArchiveWriterContract):
    """Runs ``FakeTranscriptArchiveWriter`` through the shared writer suite."""

    @pytest.fixture
    def writer(self) -> TranscriptArchiveWriter:
        return FakeTranscriptArchiveWriter()

    async def held(self, writer: TranscriptArchiveWriter) -> dict[str, TranscriptEntry]:
        assert isinstance(writer, FakeTranscriptArchiveWriter)
        return writer.recorded

    def failing_writer(self) -> TranscriptArchiveWriter:
        failing = FakeTranscriptArchiveWriter()
        failing.fail()
        return failing


class TestFakeTranscriptArchiveContract(TranscriptArchiveContract):
    """Runs ``FakeTranscriptArchive`` through the shared archive suite."""

    @pytest.fixture
    def archive(self) -> TranscriptArchive:
        return FakeTranscriptArchive(now=lambda: NOW)

    async def store(self, archive: TranscriptArchive, *entries: TranscriptEntry) -> None:
        assert isinstance(archive, FakeTranscriptArchive)
        archive.hold(*entries)

    def failing_archive(self) -> TranscriptArchive:
        failing = FakeTranscriptArchive(now=lambda: NOW)
        failing.fail()
        return failing

    def reopened(
        self, archive: TranscriptArchive, retention: timedelta | None
    ) -> TranscriptArchive:
        assert isinstance(archive, FakeTranscriptArchive)
        return archive.reopened(retention)


async def test_the_two_fakes_satisfy_one_seam_each_and_never_both() -> None:
    """ADR-0225 §10's split, asserted where a test could otherwise assume it.

    ``TranscriptArchive`` is **not** a subclass of ``TranscriptArchiveWriter`` and
    neither fake bridges them: a test holding the writer cannot reach a read through
    it, and one holding the archive cannot append. That is what makes the fakes
    usable as evidence about §4's fence rather than merely convenient.
    """
    writer = FakeTranscriptArchiveWriter()
    archive = FakeTranscriptArchive()

    assert isinstance(writer, TranscriptArchiveWriter)
    assert not isinstance(writer, TranscriptArchive)
    assert isinstance(archive, TranscriptArchive)
    assert not isinstance(archive, TranscriptArchiveWriter)


async def test_the_writers_window_is_not_a_seam_the_code_under_test_can_reach() -> None:
    """``recorded`` is the suite's window and is absent from the Protocol.

    Pinned because the fake is what a capture test is handed: if ``recorded`` were on
    the seam, a stage could read an entry back through the object it was given to
    write with, and every mypy-level guarantee §10 buys would be false in tests.
    """
    assert not hasattr(TranscriptArchiveWriter, "recorded")
    assert not hasattr(TranscriptArchiveWriter, "fail")


async def test_the_fake_writer_refuses_a_repeat_before_it_refuses_nothing_else() -> None:
    """The scripted fault takes precedence over the collision, so a failing store fails.

    A fake that checked the address first would answer a collision on a store that is
    not answering at all — which is the one case ADR-0225 §2's degraded report and its
    loud fault would be told apart by.
    """
    writer = FakeTranscriptArchiveWriter()
    await writer.append(entry())
    writer.fail()

    with pytest.raises(Exception, match="failed to append"):
        await writer.append(entry())


async def test_reopening_the_fake_shares_its_storage_rather_than_copying_it() -> None:
    """What makes the suite's retention cases read-time cases (ADR-0225 §6).

    A ``reopened`` that copied would let an implementation pass by sweeping: the two
    views would be independent and a write to one invisible to the other. Sharing is
    what makes "nothing was written and nothing was swept" true of the assertion.
    """
    archive = FakeTranscriptArchive(now=lambda: NOW)
    twin = archive.reopened(None)

    archive.hold(entry())

    assert [one.address for one in await twin.entries()] == ["c1:1"]
    assert await twin.discard("c1:1") is True
    assert await archive.entries() == []
