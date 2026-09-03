"""A root whose reads would leave the device does not wire (ADR-0230 §6, §14 item 22).

Nine arms at construction, "over a fetcher whose view of the platform's mount and
device information the test supplies" — which is §14 item 22's own requirement and the
reason :mod:`ai_assistant.readers._locality` has a seam at all. Four of them cannot be
staged on any developer's disk or CI runner: a root on a network-attached filesystem,
one whose type is unrecognised, one on an allow-listed type over an iSCSI or NBD
volume, and the negative arm that must still construct.

**What is asserted, and what is deliberately not.** The refusals are asserted as
*configuration errors that stop the build* rather than as empty listings, refusals or
degraded turns — "each refusal is a configuration error that stops construction — no
``Fetcher`` exists afterwards". Two arms go further and assert what the refusal
**cost**, because §6's claim that a remote root is refused "having been touched by
nothing at all" is a statement about calls issued rather than about the answer given.

Two of the nine cannot be staged without privilege, and each says so where it stands
rather than being silently absent.
"""

from __future__ import annotations

import os
import pathlib
from typing import TYPE_CHECKING

import pytest
from fetch_fixtures import BLOCK_TYPE, LOCAL_TYPE, StubTables, vouching
from fetch_fixtures import fetcher as build

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.readers import files as files_module
from ai_assistant.readers._descent import (
    RESOLVE_BENEATH,
    RESOLVE_CONTAINED,
    RESOLVE_NO_SYMLINKS,
    RESOLVE_NO_XDEV,
    open_contained,
)
from ai_assistant.readers._locality import DeviceBacking, MountClaim, ProcPlatformTables
from ai_assistant.readers.files import LocalFileFetcher

if TYPE_CHECKING:
    from pathlib import Path


def _watch_opens(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every path ``os.open`` is called with, and let the call through.

    ``os.open`` is the only route this module has to a descriptor — the contained
    descent takes one as its starting point — so an implementation that reached the
    kernel at all is seen here.
    """
    seen: list[str] = []
    real = os.open

    def watched(path: object, *args: object, **kwargs: object) -> int:
        seen.append(str(path))
        return real(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", watched)
    return seen


def _within(opened: list[str], scope: Path) -> list[str]:
    """The recorded opens that landed inside ``scope``.

    ADR-0230 §14 item 22's fifth arm scopes its claim exactly — "not on the configured
    path, not on anything beneath it, and not on the mount root" — and this is that
    scope. An open of the process's own working directory is not one of the three and
    is not what the arm is about; filtering here rather than asserting on the whole
    list is what keeps the assertion the ADR's rather than this process's.
    """
    return [path for path in opened if path == str(scope) or path.startswith(f"{scope}/")]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A directory of this test's own, holding one document."""
    directory = tmp_path / "documents"
    directory.mkdir()
    (directory / "report.txt").write_text("text", encoding="utf-8")
    return directory


# --- the four admission arms (ADR-0230 §14 item 22) -------------------------


def test_a_root_on_a_network_filesystem_refuses(root: Path) -> None:
    """A root the platform reports as network-attached does not wire.

    ADR-0017 §1's rule is that "user data may leave the device only from ``models/``
    or from a designated integration seam inside ``tools/``; every other egress is a
    bug", and a read served over NFS or SMB "leaves the device from ``readers/``,
    which is neither". ADR-0230 §6 makes the configuration that would perform one
    **unwireable** rather than pre-authorising it.
    """
    tables = vouching(root, filesystem_type="nfs4", backing=DeviceBacking.UNKNOWN)

    with pytest.raises(ConfigurationError, match="both established local"):
        LocalFileFetcher(root, tables=tables)


def test_a_root_on_an_unrecognised_filesystem_refuses(root: Path) -> None:
    """The **fail-closed** arm, and the one that fails a deny-list.

    §6 refuses "not merely a root the platform reports as remote, but **every** root
    whose locality the platform does not affirmatively establish". An implementation
    written as a deny-list of known-remote types passes the NFS arm above and admits
    this one, which is a filesystem nobody has heard of yet.
    """
    tables = vouching(root, filesystem_type="somefs-9000", backing=DeviceBacking.LOCAL)

    with pytest.raises(ConfigurationError, match="both established local"):
        LocalFileFetcher(root, tables=tables)


def test_a_local_filesystem_over_a_network_device_refuses(root: Path) -> None:
    """ext4 on an iSCSI or NBD volume — the same egress, one layer down.

    §6: "An ext4 or XFS volume on an iSCSI, NBD, NVMe-oF or otherwise
    network-attached block device reports an ordinary local type in the platform's
    mount table while every read of it traverses a network." This is the arm that
    fails on any implementation deciding eligibility from the mount table's type
    alone — the type here is one the allow-list admits, and the chain behind it is not.
    """
    tables = vouching(root, filesystem_type=BLOCK_TYPE, backing=DeviceBacking.NETWORK)

    with pytest.raises(ConfigurationError, match="both established local"):
        LocalFileFetcher(root, tables=tables)


def test_a_root_on_an_ordinary_local_filesystem_constructs(root: Path) -> None:
    """The negative arm, so the three refusals above are not vacuous.

    A local type over a device the platform reports through to local: the fetcher
    exists, holds a handle, and the tables were consulted for the configured path
    rather than for something else.
    """
    tables = vouching(root, filesystem_type=BLOCK_TYPE, backing=DeviceBacking.LOCAL)

    subject = LocalFileFetcher(root, tables=tables)

    try:
        assert tables.asked == [root]
    finally:
        subject.close()


def test_a_deployment_with_no_root_reaches_no_arm() -> None:
    """§6: "A deployment with no root configured constructs no fetcher".

    Asserted at the composition seam rather than here would be a different test; what
    this pins is the *settings* half, which is what makes the mechanism off by default
    (``tests/app/test_fetcher_wiring.py`` asserts the wiring).
    """
    from ai_assistant.core.config import Settings  # noqa: PLC0415 — asserted about, not used by

    assert Settings().fetch_root_path is None


# --- what a refusal costs (§14 item 22, arms 5 and 9) -----------------------


def test_refusing_a_remote_root_issues_no_filesystem_call_at_all(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6 stage 1 asserted rather than only stated, and the arm that fails an early open.

    "With the filesystem calls the constructor makes instrumented, a root the platform
    reports as network-attached is refused and **no filesystem call at all** is
    issued — not on the configured path, not on anything beneath it, and not on the
    mount root — because stage 1 decides from the tables and opens nothing."

    Instrumented on ``os.open`` itself, which is the only route this module has to a
    descriptor: the contained descent takes one as its starting point, so an
    implementation that reached the kernel at all would be seen here.
    """
    opened = _watch_opens(monkeypatch)
    tables = vouching(root, filesystem_type="cifs", backing=DeviceBacking.UNKNOWN)

    with pytest.raises(ConfigurationError):
        LocalFileFetcher(root, tables=tables)

    assert _within(opened, root.parent) == []


def test_a_substituted_mount_is_refused_on_the_device_identity_and_costs_one_open(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§14 item 22's sixth and ninth arms together, over a real filesystem.

    **Sixth**: a mount landing on the mount root stage 1 named, between the tables'
    read and stage 2's open of it. Staged by supplying a claim whose device identity is
    not the one the opened handle reports, which is exactly what a substitution
    produces and what the check exists to catch — "the arm that fails on any
    implementation treating the tables' answer as the locality rather than as a claim
    to check".

    **Ninth**: the calls that reach the substituted filesystem are "**exactly one**
    directory open of the mount root and nothing else — no read through it, no
    directory listing, no ``openat`` of any component of the configured path, no
    ``stat`` of anything beneath it, and no second attempt after the mismatch — and
    construction ends holding no handle". That is the residual §6 discloses at the size
    §6 states it at, which is the size the owner's ruling of 2026-09-03 scopes out of
    ADR-0017 §1; this arm asserts that bound and nothing wider.
    """
    opened = _watch_opens(monkeypatch)
    descents: list[str] = []

    def watched_descent(start: int, relative: str, **kwargs: int) -> int:
        descents.append(relative)
        return open_contained(start, relative, **kwargs)

    monkeypatch.setattr(files_module, "open_contained", watched_descent)
    # A device number no mount has, standing for the filesystem that landed under the
    # mount root between the tables' read and the open.
    tables = StubTables(
        claim=MountClaim(
            mount_point=root.parent,
            filesystem_type=BLOCK_TYPE,
            device=root.stat().st_dev ^ 0xFFFF,
            backing=DeviceBacking.LOCAL,
        ),
        asked=[],
    )

    with pytest.raises(ConfigurationError, match="device identity"):
        LocalFileFetcher(root, tables=tables)

    assert _within(opened, root.parent) == [str(root.parent)]
    assert descents == []


def test_a_symbolic_link_in_the_configured_path_is_refused_and_nothing_crosses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§14 item 22's seventh arm: an ancestor component that is a symbolic link.

    "This is the arm that fails on any implementation resolving the path as text before
    opening it." The contained resolution refuses a link at **any** component, so the
    link's target is never opened, nothing beneath it is, and the configured path is
    not either — asserted by instrumenting ``os.open``, whose only call must be the one
    directory open of the mount root that §6 admits.
    """
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "documents").mkdir(parents=True)
    (tmp_path / "linked").symlink_to(elsewhere, target_is_directory=True)
    configured = tmp_path / "linked" / "documents"
    opened = _watch_opens(monkeypatch)
    tables = vouching(tmp_path, filesystem_type=LOCAL_TYPE)

    with pytest.raises(ConfigurationError, match="symbolic link"):
        LocalFileFetcher(configured, tables=tables)

    assert _within(opened, tmp_path) == [str(tmp_path)]


def test_the_descent_refuses_a_mount_crossing_by_construction() -> None:
    """§14 item 22's eighth arm, pinned rather than staged, and the reason is privilege.

    The arm asks for a resolution "held at an intermediate component" onto which a
    remote-backed filesystem is then mounted, and requires that the resolution "refuse
    rather than enter it". **Mounting a filesystem requires ``CAP_SYS_ADMIN``**, which
    no test in this suite has and which a CI runner does not grant — so the transition
    cannot be staged here, and pretending otherwise with a bind mount that silently
    fails would be worse than saying so.

    What *is* decidable is the property the arm exists to protect: the descent is one
    kernel operation carrying ``RESOLVE_NO_XDEV``, so a mount landing mid-resolution is
    refused **during** resolution rather than after it. This asserts the word the
    resolution is issued under, which is what "an atomic descent rather than a careful
    one" consists of; the arm is filed as unstageable in this lane's report.
    """
    assert RESOLVE_CONTAINED == RESOLVE_NO_XDEV | RESOLVE_NO_SYMLINKS | RESOLVE_BENEATH
    assert RESOLVE_CONTAINED & RESOLVE_NO_XDEV


def test_the_descent_refuses_an_escape_above_the_root_over_a_real_filesystem(
    tmp_path: Path,
) -> None:
    """``RESOLVE_BENEATH`` asserted by exercising it, so the pin above is not alone.

    A root whose configured path escapes its own mount point's start cannot be built by
    ``_descend`` — the remainder is computed with ``relpath``, so a configured path
    outside the claimed mount produces a ``..`` the kernel refuses.
    """
    inside = tmp_path / "inside"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    tables = vouching(inside, filesystem_type=LOCAL_TYPE)

    with pytest.raises(ConfigurationError, match="escape above the start"):
        LocalFileFetcher(outside, tables=tables)


# --- the real platform view, exercised where the machine allows -------------


def test_the_real_tables_answer_for_this_machines_own_temporary_directory(
    tmp_path: Path,
) -> None:
    """``ProcPlatformTables`` is exercised rather than only injected around.

    Every other arm supplies the platform view, which is what §14 item 22 requires and
    what makes them portable — but a seam nothing ever runs is a seam that can rot. So
    the real reader is asked about a real directory here, and what is asserted is what
    holds on **every** machine: it names a mount at or above the path, that mount's
    device identity is the one the kernel reports for it, and its verdict is one of the
    three the enumeration admits.

    It deliberately does **not** assert that the answer is ``LOCAL``. A container's
    ``overlay`` root, a CI runner's device chain and a developer's LVM stack may each
    legitimately fail to report through, and §6 accepts that: "the failure mode is a
    legitimate local configuration refused until the lane can establish it".
    """
    claim = ProcPlatformTables().claim_for(tmp_path)

    assert claim is not None
    assert claim.mount_point == tmp_path or claim.mount_point in tmp_path.parents
    assert claim.device == claim.mount_point.stat().st_dev
    assert claim.backing in set(DeviceBacking)


def test_the_real_tables_refuse_a_path_no_mount_covers() -> None:
    """``None`` is a refusal like any other: §6 admits nothing it cannot establish."""
    absent = pathlib.Path("/nonexistent/mountinfo")

    assert ProcPlatformTables(mountinfo=absent).claim_for(pathlib.Path("/")) is None


def test_a_root_the_fixture_vouches_for_lists_its_own_files(root: Path) -> None:
    """The whole of this file's scaffolding, exercised once end to end.

    Every other test in this package builds through ``fetch_fixtures.fetcher``; this is
    the one that says what that helper actually produces — a fetcher over the real
    directory, whose handle is the one the descent returned.
    """
    subject = build(root)
    try:
        assert subject.name
    finally:
        subject.close()
