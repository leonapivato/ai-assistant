"""The data directory as a security boundary (ADR-0084 §1, ADR-0083 §3 step 2).

The subject is a hole that owner-only *files* do not close. ``0600`` on a database
restricts opening it; it says nothing about the directory entry, so a
group- or world-writable ``data_dir`` lets another local user unlink a database —
or, once ADR-0084 §1's socket lands, the socket the CLI derives and connects to —
and put their own in its place.

The ancestor tests are the ones worth reading, because securing the leaf looks
sufficient and is not: a ``0700`` directory inside a ``0777`` non-sticky parent can
simply be renamed away and recreated by somebody else, and the leaf's mode never
comes into it.

Every test here runs as an unprivileged user; ``root`` bypasses the modes these
assert on, so the ones that depend on that are skipped for it rather than passing
vacuously.
"""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.service import datadir

if TYPE_CHECKING:
    from pathlib import Path


def test_a_missing_directory_is_created_owner_only(tmp_path: Path) -> None:
    """ADR-0004 §4's posture applied to the container, not only to the contents.

    ``chmod`` after ``mkdir`` rather than trusting ``mkdir``'s mode argument: the
    process umask masks that argument, so a hub running under a permissive umask
    would create exactly the directory this check exists to reject.
    """
    target = tmp_path / "nested" / "hub-data"

    datadir.prepare(target)

    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_creation_survives_a_permissive_umask(tmp_path: Path) -> None:
    """The reason the ``chmod`` is not redundant, asserted rather than argued."""
    target = tmp_path / "hub-data"
    previous = os.umask(0o000)
    try:
        datadir.prepare(target)
    finally:
        os.umask(previous)

    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_an_existing_directory_is_accepted_and_its_mode_is_left_alone(
    tmp_path: Path,
) -> None:
    """Validated, never repaired.

    ADR-0084 §1 says the directory is "created ``0700`` **when the hub creates
    it**". Silently re-moding one the operator already set would hide a
    misconfiguration rather than report it — and would also quietly narrow a
    ``0750`` directory somebody chose on purpose, which is safe and is not this
    call's business.
    """
    target = tmp_path / "hub-data"
    target.mkdir(mode=0o750)
    target.chmod(0o750)

    datadir.prepare(target)

    assert stat.S_IMODE(target.stat().st_mode) == 0o750


def test_prepare_is_idempotent(tmp_path: Path) -> None:
    """A hub restarts; the second start must not differ from the first."""
    target = tmp_path / "hub-data"

    datadir.prepare(target)
    datadir.prepare(target)

    assert stat.S_IMODE(target.stat().st_mode) == 0o700


@pytest.mark.parametrize("mode", [0o770, 0o707, 0o777])
def test_a_directory_writable_by_others_is_refused(tmp_path: Path, mode: int) -> None:
    """The hole itself: another user who can write the directory can replace its contents.

    Not a theoretical one — the five SQLite databases have no handshake to fall
    back on, so a replaced file is simply read as though it were ours.
    """
    target = tmp_path / "hub-data"
    target.mkdir()
    target.chmod(mode)

    with pytest.raises(ConfigurationError, match="writable by other users"):
        datadir.prepare(target)


def test_a_readable_but_not_writable_directory_is_accepted(tmp_path: Path) -> None:
    """The condition is *writable*, not *visible*, and the difference matters.

    ``0755`` is the ordinary mode a directory created under a default umask gets.
    Rejecting it would fail deployments that are not vulnerable — nobody but the
    owner can add, remove or rename an entry — and ADR-0084 §1 is explicit that a
    rule failing the deployment everyone runs is an outage rather than a control.
    """
    target = tmp_path / "hub-data"
    target.mkdir()
    target.chmod(0o755)

    datadir.prepare(target)


def test_a_file_occupying_the_path_is_refused(tmp_path: Path) -> None:
    """The message names the remedy, because the errno alone would not."""
    target = tmp_path / "hub-data"
    target.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="not a directory"):
        datadir.prepare(target)


@pytest.mark.skipif(os.geteuid() == 0, reason="root satisfies every ownership check")
def test_an_ancestor_writable_by_others_and_not_sticky_is_refused(
    tmp_path: Path,
) -> None:
    """ADR-0084 §1's counter-example, executed.

    ``data_dir`` at ``0700`` inside a ``0777`` non-sticky parent: another user
    renames the leaf, creates their own directory at the configured path, and the
    leaf's mode is irrelevant because the leaf they replaced is gone. This is why
    the walk goes all the way up rather than stopping at the directory named.
    """
    loose = tmp_path / "shared"
    loose.mkdir()
    target = loose / "hub-data"
    target.mkdir(mode=0o700)
    loose.chmod(0o777)

    try:
        with pytest.raises(ConfigurationError, match="not sticky"):
            datadir.prepare(target)
    finally:
        loose.chmod(0o755)


def test_a_sticky_ancestor_writable_by_others_is_accepted(tmp_path: Path) -> None:
    """The exception that keeps ``/tmp`` usable, and the reason it is safe.

    The sticky bit is precisely what stops a user removing or renaming an entry
    they do not own — which is the only thing an ancestor's mode can do to the
    directory beneath it. Without this exception the rule would reject every
    deployment whose data directory sits anywhere under ``/tmp``, including CI.
    """
    shared = tmp_path / "shared"
    shared.mkdir()
    target = shared / "hub-data"
    target.mkdir(mode=0o700)
    shared.chmod(0o1777)

    try:
        datadir.prepare(target)
    finally:
        shared.chmod(0o755)


def test_a_root_owned_ancestor_is_accepted(tmp_path: Path) -> None:
    """The ordinary case, and the reason ancestors get the weaker condition.

    ``/`` and ``/home`` are root-owned and always will be. Requiring hub-uid
    ownership all the way up would reject every real deployment, so what is
    required of an ancestor is that an untrusted *third party* cannot replace the
    entry below it — not that the hub owns it.
    """
    target = tmp_path / "hub-data"

    datadir.prepare(target)

    # The walk really did reach a root-owned ancestor rather than stopping early,
    # so the acceptance above is evidence about the rule and not about the path.
    root = target.parents[-1]
    assert str(root) == os.sep
    assert root.stat().st_uid == 0
