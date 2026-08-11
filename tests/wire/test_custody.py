"""The custody walk both the data directory and the agent socket depend on.

These tests are the shared half of ADR-0084 §1's conditions, exercised once here
rather than twice through the two callers. What each caller does with a fault —
the wording, the remedy it suggests — is its own test's subject; what the walk
*finds* is this one's.

The rule under test is deliberately asymmetric, and the tests say why at each
point: an ancestor is trusted when an untrusted **third party** cannot replace
what sits beneath it, which is a weaker condition than owning it, because ``/``
and ``/run`` are root-owned in every real deployment and always will be.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai_assistant.wire.custody import displayable, first_ancestor_fault


def test_a_trustworthy_ancestry_reports_no_fault(tmp_path: Path) -> None:
    """The ordinary case: every ancestor is ours or root's, and none is replaceable."""
    target = tmp_path / "nested" / "leaf"
    target.parent.mkdir()

    assert first_ancestor_fault(target) is None


def test_a_root_owned_ancestor_is_not_a_fault(tmp_path: Path) -> None:
    """The reason ancestors get the weaker condition.

    Requiring hub-uid ownership all the way up would reject every real deployment,
    so the walk must reach a root-owned directory and accept it. Asserted about the
    filesystem rather than assumed, so the acceptance is evidence about the rule.
    """
    target = tmp_path / "leaf"

    assert first_ancestor_fault(target) is None

    root = target.parents[-1]
    assert str(root) == os.sep
    assert root.stat().st_uid == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root satisfies every ownership check")
def test_an_other_writable_non_sticky_ancestor_is_the_fault(tmp_path: Path) -> None:
    """ADR-0084 §1's counter-example: the leaf's own mode is irrelevant once the
    directory above it can be renamed out from under it by anybody.
    """
    loose = tmp_path / "shared"
    loose.mkdir()
    target = loose / "leaf"
    loose.chmod(0o777)

    try:
        fault = first_ancestor_fault(target)
    finally:
        loose.chmod(0o755)

    assert fault is not None
    assert fault.kind == "replaceable"
    assert fault.ancestor == loose
    assert fault.mode == 0o777


def test_a_sticky_other_writable_ancestor_is_not_a_fault(tmp_path: Path) -> None:
    """The exception that keeps ``/tmp`` usable, and the reason it is safe.

    The sticky bit is exactly what stops a user removing or renaming an entry they
    do not own — the only thing an ancestor's mode can do to what sits beneath it.
    Without this the rule would reject every deployment under ``/tmp``, including CI.
    """
    shared = tmp_path / "shared"
    shared.mkdir()
    target = shared / "leaf"
    shared.chmod(0o1777)

    try:
        assert first_ancestor_fault(target) is None
    finally:
        shared.chmod(0o755)


@pytest.mark.skipif(os.geteuid() == 0, reason="root satisfies every ownership check")
def test_the_nearest_fault_is_the_one_reported(tmp_path: Path) -> None:
    """The walk stops at the first fault rather than collecting every one.

    The operator has to fix the nearest before the next becomes reachable, and
    naming one directory is what makes the refusal actionable.
    """
    outer = tmp_path / "outer"
    outer.mkdir()
    inner = outer / "inner"
    inner.mkdir()
    target = inner / "leaf"
    outer.chmod(0o777)
    inner.chmod(0o777)

    try:
        fault = first_ancestor_fault(target)
    finally:
        inner.chmod(0o755)
        outer.chmod(0o755)

    assert fault is not None
    assert fault.ancestor == inner


@pytest.mark.skipif(os.geteuid() == 0, reason="root satisfies every ownership check")
def test_a_path_that_does_not_exist_is_still_walked(tmp_path: Path) -> None:
    """Load-bearing for the overlay agent socket, which a daemon may not have
    created yet.

    Only the parents are examined, so custody can be established for a path before
    anything occupies it — which is what lets the agent's socket be checked without
    probing whether the daemon is running, a question ADR-0124 §3 keeps out of the
    constructor.
    """
    loose = tmp_path / "shared"
    loose.mkdir()
    absent = loose / "never-created.sock"
    assert not absent.exists()
    loose.chmod(0o777)

    try:
        fault = first_ancestor_fault(absent)
    finally:
        loose.chmod(0o755)

    assert fault is not None
    assert fault.ancestor == loose


def test_a_pathname_with_no_utf8_form_is_rendered_rather_than_echoed() -> None:
    """``core/types.py``'s hazard, at the place every custody refusal meets it.

    "Interpolating it raw would build an error message that is itself unencodable,
    so reporting the fault would fail the same way the fault does." A refusal about
    a path is the one message guaranteed to name such a value, so the renderer
    lives beside the predicate rather than in each caller — which is how the
    sibling measurement in ``wire/address.py`` came to be missing it (#940).
    """
    rendered = displayable("/var/run/tailscale/\udcffagent.sock")

    assert R"\xff" in rendered
    rendered.encode("utf-8")  # the point: a message built from this can be reported


def test_an_ordinary_path_survives_rendering_unchanged() -> None:
    """Escaping a value that never needed it costs nothing and must change nothing."""
    assert displayable("/run/tailscale/tailscaled.sock") == "/run/tailscale/tailscaled.sock"
    assert displayable(Path("/run/tailscale/tailscaled.sock")) == "/run/tailscale/tailscaled.sock"


def test_a_value_the_platform_did_not_supply_reads_as_an_absence() -> None:
    """``OSError.filename`` is ``None`` when the platform supplied no path at all.

    Interpolating that raw would put the word "None" where a pathname belongs, and
    an operator would look for a directory called None. It is the easy one to miss
    because it is not a decoding problem at all.
    """
    assert displayable(None) == "an unnamed path"


def test_bytes_are_rendered_from_the_bytes_themselves() -> None:
    """A pathname is bytes on Unix, and ``OSError`` can hand one back as bytes."""
    assert displayable(b"/var/run/agent.sock") == "/var/run/agent.sock"
