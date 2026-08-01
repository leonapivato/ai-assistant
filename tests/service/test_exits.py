"""Which failures come back, and which stay down (ADR-0083 §5).

The subject is one question applied to every fault: *would restarting, unchanged,
ever succeed?* Getting it wrong is expensive in both directions and asymmetrically
so — a spurious restart is recoverable, a spurious stay-down is an outage — which
is why the default is tested as deliberately as the special cases.
"""

from __future__ import annotations

import errno

import pytest

from ai_assistant.core.errors import (
    ConfigurationError,
    IncompatibleStateError,
    MemoryStoreError,
    ModelError,
)
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART, classify


def _state_fault() -> IncompatibleStateError:
    return IncompatibleStateError(
        "store was built with a different embedder",
        expected="embedding_model='v2'",
        found="embedding_model='v1'",
        operator_action="re-embed the store, or configure the embedder it was built with",
    )


def test_the_three_codes_are_the_ratified_numbers() -> None:
    """``78`` in particular is ``EX_CONFIG`` and not an invented number.

    An existing convention is what lets a reference deployment map it with one
    directive (``RestartPreventExitStatus=78``); a bespoke number would need every
    supervisor configuration to be taught it.
    """
    assert (EXIT_OK, EXIT_RESTART, EXIT_DEPLOYMENT) == (0, 1, 78)


def test_a_state_fault_stays_down_and_carries_its_own_remedy() -> None:
    """ADR-0083 §6's class, and why it carries an action rather than being given one.

    The store knows what it expected, what it found, and what a human must do;
    nothing at the entry point does. Sourcing the action from the error is what
    keeps this mapping from having to invent a remedy per fault — the failure mode
    §6 exists to end.
    """
    fault = _state_fault()

    code, action = classify(fault)

    assert code == EXIT_DEPLOYMENT
    assert action == fault.operator_action


def test_a_configuration_error_stays_down() -> None:
    """Every startup misconfiguration already arrives as this one class.

    Settings that will not load, a spec naming an uninstalled vendor, a vendor
    with no credential (#530), an unbuildable embedder, a data directory that
    cannot be prepared. None of them clears itself, so one branch covers all of
    them — and a new one inherits the right answer instead of needing a new case.
    """
    code, action = classify(ConfigurationError("timezone 'Mars/Olympus' is unknown"))

    assert code == EXIT_DEPLOYMENT
    assert action


@pytest.mark.parametrize(
    "code",
    [errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOTDIR, errno.EISDIR],
)
def test_a_filesystem_access_fault_stays_down(code: int) -> None:
    """ADR-0083 §5's sharpest case, in its own words.

    "A directory the process may not write into does not become writable by being
    opened again, and mapping it to ``1`` buys an infinite restart loop against an
    unchanging ``EACCES``" — the owner's legibility ruling failing in its purest
    form, since the hub is down and the reason is buried in a repeating trace.
    """
    verdict, action = classify(OSError(code, "denied", "/data/memory.db"))

    assert verdict == EXIT_DEPLOYMENT
    assert "/data/memory.db" in action


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EMFILE, errno.EIO])
def test_a_fault_that_may_clear_comes_back(code: int) -> None:
    """The other side of the same test, and §5 names these explicitly.

    "A store that fails to open for any reason the test does not reach — a corrupt
    page, an exhausted disk — ``1``, because some of those do clear." An exhausted
    disk is not a deployment mistake, and refusing to restart over one would turn a
    transient into an outage.
    """
    verdict, action = classify(OSError(code, "no space left on device"))

    assert verdict == EXIT_RESTART
    assert action == ""


def test_an_unrecognised_fault_comes_back() -> None:
    """§5's stated default, and it is a decision rather than a fallthrough.

    "Where a new fault does not obviously answer the question, the answer is ``1``:
    a spurious restart is recoverable and a spurious ``78`` is an outage."
    """
    verdict, action = classify(RuntimeError("something nobody enumerated"))

    assert verdict == EXIT_RESTART
    assert action == ""


def test_a_wrapped_filesystem_fault_is_still_found() -> None:
    """§3 step 3's "wherever it surfaces", made mechanical.

    Step 2's writability check is necessary and not sufficient — ``mkdir`` succeeds
    on a directory the process cannot write into, and a database file can be
    unreadable inside a writable one — so the access fault usually arrives already
    retyped by whichever store met it. Reading only the outermost class would put
    it on the restart side and buy the crash loop §5 warns about.
    """
    denied = PermissionError(errno.EACCES, "denied", "/data/plans.db")
    wrapped = MemoryStoreError("failed to open memory store")
    wrapped.__cause__ = denied

    code, _action = classify(wrapped)

    assert code == EXIT_DEPLOYMENT


def test_a_store_fault_from_a_transient_cause_still_comes_back() -> None:
    """The chain walk must not turn every wrapped error into a deployment fault."""
    wrapped = MemoryStoreError("failed to open memory store")
    wrapped.__cause__ = OSError(errno.ENOSPC, "no space left on device")

    code, _action = classify(wrapped)

    assert code == EXIT_RESTART


def test_only_the_explicit_cause_chain_is_followed() -> None:
    """``__context__`` is not evidence, and following it would be a real defect.

    A cause is an author saying "this failure *is* that one, retyped". A context is
    merely whatever happened to be in flight — including an error caught and
    handled correctly somewhere deep inside a store. Letting that decide the hub's
    exit code would let a handled ``EACCES`` on an unrelated optional file keep the
    whole deployment down.
    """
    unrelated = PermissionError(errno.EACCES, "denied", "/var/cache/some-cache")
    failure = ModelError("the provider returned nothing usable")
    failure.__context__ = unrelated
    failure.__cause__ = None

    code, _action = classify(failure)

    assert code == EXIT_RESTART


def test_a_cyclic_cause_chain_terminates() -> None:
    """Defensive: a hand-built cycle must not hang the exit path.

    Nothing in the tree builds one, and that is the point — the classifier runs at
    the worst possible moment, when startup has already failed, so it must not be
    the thing that turns a clean stay-down into a hung process.
    """
    first = RuntimeError("first")
    second = RuntimeError("second")
    first.__cause__ = second
    second.__cause__ = first

    assert classify(first) == (EXIT_RESTART, "")


def test_a_state_fault_beneath_a_store_fault_is_still_found() -> None:
    """The realistic shape of ADR-0083 §6 arriving through a wrapper."""
    wrapped = MemoryStoreError("failed to open memory store")
    wrapped.__cause__ = _state_fault()

    code, action = classify(wrapped)

    assert code == EXIT_DEPLOYMENT
    assert "re-embed" in action
