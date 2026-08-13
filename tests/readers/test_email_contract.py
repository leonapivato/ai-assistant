"""EmailReader passes the shared Reader suite, plus the clauses only it can.

The binding is the point of a *shared* suite: a clause either binds every
implementation or binds none, so this reader is held to exactly what
``CalendarReader`` and the canonical fake are held to. ADR-0095 §3 named this
lane in advance when it argued the suite's value — "A synced-vault reader and a
co-located maildir reader are two implementations of one behaviour, which is
precisely and only what a shared conformance suite is for … Two implementations
is the condition under which that suite starts paying" — so what ADR-0140 §13
asks of this reader is to **pass** the suite, not to write one, and no Protocol
is minted and no triad is owed.

Below the binding are the obligations ADR-0093 §10 names as **not** suite clauses
and hands to a concrete reader's lane, tracked by **#648**: that a *real*
unreadable source is what raises, that the underlying failure survives as
``__cause__``, and that the message is payload-free.

**§10's third case has no subject here, and that is a finding rather than a
gap.** For the calendar, a document that cannot be parsed at all is a real state
and raises. An mbox has no document-level structure to violate: a store of
arbitrary bytes frames zero messages, and one whose messages are unreadable skips
each of them under ADR-0140 §5. Both are **successful empty readings**, which
ADR-0093 §8 rules a success in as many words, and
:func:`test_a_store_of_arbitrary_bytes_is_an_empty_reading_and_not_a_fault`
asserts it rather than leaving the absence to be read as an omission. What this
reader raises on instead are its own three refusals — the byte cap, the message
cap and the content budget — each tested in ``test_email_bounds.py`` against a
real store.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path as _Path
from typing import TYPE_CHECKING

import pytest
from mbox_fixtures import NOW, envelope, facet_of, message, reader, store

sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "core"))

from reader_contract import GatedRead, ReaderContract, assert_conforms

from ai_assistant.core.errors import ReaderError
from ai_assistant.readers import EMAIL_READER_NAME, _source
from ai_assistant.readers import email as email_module
from ai_assistant.testing.cancellation import ThreadSuspension

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.protocols import Reader

#: A distinctive subject, used twice: once so a failing read has something
#: quotable to leak, and once so a case can prove it did not.
SENSITIVE_SUBJECT = "Oncology follow-up with Dr Halvorsen"

#: An hour inside the fixtures' two-hour window, for the subjects whose point is
#: that they proposed something.
_IN_WINDOW = NOW - timedelta(hours=1)


def _root(exc: BaseException) -> BaseException:
    """The deepest link of an exception's cause chain."""
    while exc.__cause__ is not None:
        exc = exc.__cause__
    return exc


class TestEmailReaderContract(ReaderContract):
    """Runs EmailReader through the shared Reader conformance suite."""

    @pytest.fixture(autouse=True)
    def _levers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # `gated_read` is a plain method rather than a fixture, so the two levers
        # it needs are parked here where pytest can still undo the patch.
        self._tmp = tmp_path
        self._monkeypatch = monkeypatch

    @pytest.fixture
    def reader(self, tmp_path: Path) -> Reader:
        # Delivered an hour before the frozen clock, so it is inside the window
        # the fixtures' reader carries: several suite cases quantify over
        # ``proposals`` and would exercise nothing against a subject with none.
        return reader(store(tmp_path, envelope(delivered_at=_IN_WINDOW)))

    @pytest.fixture
    def empty_reader(self, tmp_path: Path) -> Reader:
        return reader(store(tmp_path, name="empty.mbox"))

    @pytest.fixture
    def failing_reader(self, tmp_path: Path) -> Reader:
        return reader(tmp_path / "absent.mbox")

    def gated_read(self) -> GatedRead:
        """A read held inside the acquisition it is performing.

        Suspending :func:`~ai_assistant.readers._source.acquire` rather than
        contriving a slow file is what makes the case deterministic — and it holds
        the read at exactly the place a real one blocks, on the worker thread,
        which is the code the cancellation clause is about.
        """
        suspension = ThreadSuspension()
        real = _source.acquire

        def held(path: Path, *, max_bytes: int) -> bytes:
            suspension.hold()
            return real(path, max_bytes=max_bytes)

        self._monkeypatch.setattr(email_module, "acquire", held)
        return GatedRead(
            reader=reader(store(self._tmp, envelope(), name="gated.mbox")), gate=suspension
        )


# --- what an unreadable source does, and what an unreadable *message* does ---


async def test_a_missing_source_raises(tmp_path: Path) -> None:
    """A file that is not there is an ordinary state of the world, not a defect.

    A reader's source is a file the system does not own, so unreadability is
    expected — which is why ADR-0083 §7 logs and retries rather than exiting, and
    why ADR-0093 §7 checks existence at run time rather than refusing to start.
    Here it is expected twice over: the store's writer is a process outside this
    system entirely (ADR-0140 §1), so "the fetcher has not run yet" is a first-boot
    state rather than a fault.
    """
    with pytest.raises(ReaderError) as raised:
        await reader(tmp_path / "absent.mbox").read()

    assert isinstance(_root(raised.value), FileNotFoundError)


async def test_an_unreadable_source_raises(tmp_path: Path) -> None:
    """A permission denial is a different operator action from a missing file.

    Preserving ``__cause__`` is what keeps the wrapping from destroying the
    diagnosis: ADR-0083 §7 logs a failed job "with its class", and a store the
    fetcher has not written, one it wrote as another user, and one that busts a
    cap are three different things to do about it.
    """
    path = store(tmp_path, envelope())
    path.chmod(0o000)
    try:
        with pytest.raises(ReaderError) as raised:
            await reader(path).read()
    finally:
        path.chmod(0o600)

    assert isinstance(_root(raised.value), PermissionError)


async def test_a_directory_raises_rather_than_being_walked(tmp_path: Path) -> None:
    """ADR-0093 §7's descriptor check, which ADR-0140 §2 satisfies as ratified.

    The email source is **not** a directory and no clause of §7 is narrowed,
    widened or excepted for it: a maildir is declined and #649's question — whether
    a reader may ever read a directory — is left exactly where it was. This is the
    assertion that keeps the decline from being a sentence in a docstring.
    """
    maildir = tmp_path / "Maildir"
    (maildir / "new").mkdir(parents=True)

    with pytest.raises(ReaderError) as raised:
        await reader(maildir).read()

    assert isinstance(_root(raised.value), _source.SourceNotRegularFileError)


async def test_a_store_of_arbitrary_bytes_is_an_empty_reading_and_not_a_fault(
    tmp_path: Path,
) -> None:
    """The case ADR-0093 §10's "malformed source" has no subject for here.

    An mbox has no document-level structure to violate, so bytes that frame no
    ``From `` line frame no message, and there is nothing for a parse to fail on.
    ADR-0093 §8 rules an empty ``proposals`` tuple a **success**, and every clause
    of the suite still binds on it — which is asserted rather than assumed,
    because the nothing-to-say path is exactly where an implementation stops
    bothering.
    """
    path = store(tmp_path, b"\x00\xffnot a mailbox at all\nFrom: not a message\n")

    reading = await reader(path).read()

    assert reading.proposals == ()
    assert facet_of(reading).arrived_in_window == 0
    assert_conforms(reading, EMAIL_READER_NAME)


async def test_an_uninterpretable_message_is_skipped_rather_than_raising(
    tmp_path: Path,
) -> None:
    """ADR-0140 §5's skip rule reaching the whole store, in one assertion.

    Every message being unreadable is not a read that could not complete — it is a
    read that accounted for nothing, and this reader has no coverage to withhold
    on the strength of it (§7). The neighbouring case that *does* raise is the
    message cap, which is applied at the framing precisely so that this shape
    cannot launder a busted cap into a quiet week (``test_email_bounds.py``).
    """
    path = store(tmp_path, message("Subject: no delivery header", "Date: nonsense"))

    reading = await reader(path).read()

    assert reading.proposals == ()
    assert_conforms(reading, EMAIL_READER_NAME)


# --- §8's two neighbouring obligations on that raise (#648) -----------------


async def test_the_underlying_failure_survives_as_the_cause(tmp_path: Path) -> None:
    """``__cause__`` is the whole diagnosis, and wrapping must not destroy it."""
    with pytest.raises(ReaderError) as raised:
        await reader(tmp_path / "absent.mbox").read()

    chain: list[BaseException] = []
    current: BaseException | None = raised.value
    while current is not None:
        chain.append(current)
        current = current.__cause__

    assert any(isinstance(link, FileNotFoundError) for link in chain), chain


async def test_a_missing_paths_failure_does_not_put_that_path_in_the_message(
    tmp_path: Path,
) -> None:
    """The message an operator's log receives names no file (ADR-0093 §8, ADR-0004 §5).

    ``raise ReaderError(str(exc)) from exc`` satisfies every word of §8's wrapping
    rule and, for a missing ``/home/alice/mail/alice@example.com.mbox``, produces
    a message that **is** that path — which ADR-0083 §7 then writes to a log. A
    mail store's path is if anything worse than a calendar's: a directory names
    the user and a filename can name the account.
    """
    path = tmp_path / "mail" / "alice@example.com.mbox"
    path.parent.mkdir()

    with pytest.raises(ReaderError) as raised:
        await reader(path).read()

    message_text = str(raised.value)
    assert str(path) not in message_text
    assert path.name not in message_text
    assert str(tmp_path) not in message_text
    # Identity and classes, which is the whole of what §8 permits — and the
    # cause's class is the useful half, because it tells an operator which action
    # to take and they already know the path, having configured it.
    assert message_text.startswith(f"{EMAIL_READER_NAME}: ")
    assert "FileNotFoundError" in message_text


async def test_a_refused_stores_message_quotes_neither_the_store_nor_its_contents(
    tmp_path: Path,
) -> None:
    """A refusal reached *through* the messages leaks neither them nor the path.

    The byte cap is the refusal a real store hits, and it is the one whose
    exception is built from figures rather than from content — so the case worth
    asserting is that the *subject lines the read had already traversed* are not
    in the message either. §8 forbids the source's contents as squarely as it
    forbids its location.
    """
    path = store(
        tmp_path,
        envelope(subject=SENSITIVE_SUBJECT, delivered_at=_IN_WINDOW),
        name="alice@example.com.mbox",
    )

    with pytest.raises(ReaderError) as raised:
        await reader(path, max_bytes=16).read()

    message_text = str(raised.value)
    assert SENSITIVE_SUBJECT not in message_text
    assert "Halvorsen" not in message_text
    assert str(path) not in message_text
    assert path.name not in message_text
    assert message_text.startswith(f"{EMAIL_READER_NAME}: ")
