"""The fetch root's handle is released on both paths (ADR-0230 §14 item 23).

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

**The platform view is supplied**, for ``tests/readers/fetch_fixtures.py``'s reason:
``ProcPlatformTables`` is fail-closed by decision, so a container's ``overlay`` root
or a CI runner's device chain may legitimately refuse — and a test of the *wiring* has
no business being decided by the machine it runs on.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path as _Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "readers"))

from fetch_fixtures import vouching

from ai_assistant.app import composition
from ai_assistant.app.composition import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.readers import LocalFileFetcher

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
