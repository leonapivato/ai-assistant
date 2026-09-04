"""What a fetch test needs to build a real ``LocalFileFetcher`` over a real directory.

**The platform view is supplied rather than read**, which is ADR-0230 §14 item 22's
own requirement: nine construction arms run "over a fetcher whose view of the
platform's mount and device information the test supplies", and four of them — a
network-attached filesystem, an unrecognised type, ext4 on an iSCSI volume, and the
one that constructs — cannot be staged on a developer's own disk or on a CI runner.

It is also what makes the *rest* of the suite portable. ``ProcPlatformTables`` is
fail-closed by decision: it admits a root only where the platform reports through to
a local bus, and a container's ``overlay`` root or a CI runner's device chain may
legitimately not. A test of the **fetch** has no business being decided by the
machine it runs on, so every fixture here vouches explicitly and the locality arms are
their own file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.readers._locality import DeviceBacking, MountClaim
from ai_assistant.readers.files import LocalFileFetcher

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime, timedelta
    from pathlib import Path

#: A filesystem type ``_locality`` recognises as memory-backed, so a vouching view
#: needs no device chain behind it. Used wherever a test's subject is the *fetch*
#: rather than the eligibility decision.
LOCAL_TYPE: Final = "tmpfs"

#: A filesystem type it recognises as block-backed, so a test can drive the device
#: half of §6's eligibility independently of the type half.
BLOCK_TYPE: Final = "ext4"


@dataclass(frozen=True)
class StubTables:
    """A platform view a test states outright (ADR-0230 §14 item 22).

    Attributes:
        claim: What ``claim_for`` answers for every path. One claim rather than a
            mapping: a fetcher asks exactly once, at construction, so a table keyed by
            path would be machinery no arm uses.
        asked: Every path ``claim_for`` was called with, so an arm can assert that
            stage 1 consulted the tables at all.
    """

    claim: MountClaim | None
    asked: list[Path]

    def claim_for(self, path: Path) -> MountClaim | None:
        """What the tables say about the mount ``path`` falls under."""
        self.asked.append(path)
        return self.claim


def vouching(
    mount_point: Path,
    *,
    filesystem_type: str = LOCAL_TYPE,
    backing: DeviceBacking = DeviceBacking.LOCAL,
    device: int | None = None,
) -> StubTables:
    """A view claiming ``mount_point`` is a local mount, truthfully about its device.

    ``device`` defaults to the mount point's **real** ``st_dev``, so stage 2's check of
    the opened handle against the claim passes — which is what lets every other test in
    this package exercise the fetch rather than the eligibility decision. An arm
    driving the mismatch supplies a device of its own.
    """
    return StubTables(
        claim=MountClaim(
            mount_point=mount_point,
            filesystem_type=filesystem_type,
            device=mount_point.stat().st_dev if device is None else device,
            backing=backing,
        ),
        asked=[],
    )


def fetcher(  # noqa: PLR0913 — a root, a mount point, two clocks and six configured figures
    root: Path,
    *,
    mount_point: Path | None = None,
    now: Callable[[], datetime] | None = None,
    monotonic: Callable[[], int] | None = None,
    listing_ttl: timedelta | None = None,
    listing_max_entries: int | None = None,
    max_file_bytes: int | None = None,
    max_content_bytes: int | None = None,
    max_decoded_bytes: int | None = None,
    max_character_mappings: int | None = None,
) -> LocalFileFetcher:
    """A fetcher over ``root``, with the platform vouching for it.

    ``mount_point`` defaults to ``root`` itself, which makes the descent's remainder
    ``"."`` — the shortest resolution there is. An arm that needs the descent to walk
    components, such as the symbolic-link-ancestor one, names a mount point above the
    root instead.

    Every keyword left ``None`` takes the fetcher's own default, so a caller states
    only the figure its case is about.
    """
    figures = {
        "now": now,
        "monotonic": monotonic,
        "listing_ttl": listing_ttl,
        "listing_max_entries": listing_max_entries,
        "max_file_bytes": max_file_bytes,
        "max_content_bytes": max_content_bytes,
        "max_decoded_bytes": max_decoded_bytes,
        "max_character_mappings": max_character_mappings,
    }
    return LocalFileFetcher(
        root,
        tables=vouching(mount_point if mount_point is not None else root),
        **{name: value for name, value in figures.items() if value is not None},  # type: ignore[arg-type]
    )
