"""Shared conformance suite for the ledger's identifier factory (ADR-0192 §2).

The factory is a **collaborator** of the ledger and not a Protocol in
``core/protocols.py``: it, ``open_invocations`` and ``complete_invocation`` are all
``permissions/``, which is what makes the reservation store-internal — no id
crosses a subsystem boundary to be reserved and no consumer is handed a
reservation call. Its obligation is pinned here, separately from the ledger's,
because it is the collaborator that owes it.

**The obligation is the process and never the instance.** A completion names its
claim by ``id`` alone, so an id reissued after the row it first named was erased
would let a completion held by one call land on a *different* call's claim and be
recorded as that call's outcome and cost — silently. Nothing makes a factory
unreplaceable and ADR-0192 §3 adds no lifecycle obligation to ``ToolInvoker``, so
a second instance can be constructed while an ``invoke`` call still holds a
claim's id.

**What this suite cannot catch, and says so rather than pretending.** A factory
whose non-repetition is only *probable* passes every case below; ADR-0045 §4
already rules that shape out, and §2 puts the obligation on the collaborator for
exactly that reason. The cases here are the ones that catch a **reset** — the
failure a construction actually has — and not a long draw that could only catch a
collision by luck.

Named ``*_contract`` so pytest collects it only via a ``Test``-prefixed subclass.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

_DRAWS = 16


class IdentifierFactoryContract:
    """Behaviour every conforming identifier factory must exhibit."""

    @pytest.fixture
    def build(self) -> Callable[[], Any]:
        """Return a callable building a factory **the way the composition root does**."""
        raise NotImplementedError

    @pytest.fixture
    def pinned(self) -> Callable[[str], Any]:
        """Return a callable building a factory over a space with a fixed nonce.

        The fork arm needs one: two factories in one process share a pid whether it
        was read at allocation or frozen at construction, so only a fixed nonce
        leaves the pid as the single thing that can differentiate two children.
        """
        raise NotImplementedError

    @pytest.fixture
    def pinned_pair(self) -> Callable[[str], tuple[Any, Any]]:
        """Return a callable building **two factories over one pinned space**.

        The two-instance reservation case needs both halves at once: a sequence it
        can predict, so the id it reserves is one the space would really have
        minted, and two instances over that one space, so the reservation is taken
        by a different object than the one that draws.
        """
        raise NotImplementedError

    def test_successive_draws_differ(self, build: Callable[[], Any]) -> None:
        factory = build()

        drawn = [factory() for _ in range(_DRAWS)]

        assert len(set(drawn)) == _DRAWS

    def test_every_draw_is_usable_as_a_durable_identifier(self, build: Callable[[], Any]) -> None:
        """Non-blank text, because that is what a row is stored under."""
        factory = build()

        drawn = factory()

        assert isinstance(drawn, str)
        assert drawn.strip()

    def test_a_reserved_identifier_is_never_returned(self, pinned: Callable[[str], Any]) -> None:
        """The obligation reaches ids it was **given to reserve** as well as issued ones.

        ``open_invocations`` hands back the claims a restarted process reads out of
        the store — ids *this* process never issued, so its own sequence is free to
        mint them, and the ledger's redraw cannot see the reissue once ``clear()``
        has erased the row they named.

        **The reserved ids come from a twin space and never from this one**, which is
        the whole of what makes this case say anything. Ids drawn from the space that
        is about to be asked for more are ones its counter has already moved past, so
        a ``reserve`` that did nothing at all would pass. Two spaces over one nonce
        mint the *same* sequence, so these are exactly the ids this space would have
        returned next — which is also the real shape: a previous process's rows, read
        back out of the store.
        """
        elsewhere = pinned("reserved")
        persisted = [elsewhere() for _ in range(_DRAWS)]
        here = pinned("reserved")
        here.reserve(persisted)

        drawn = [here() for _ in range(_DRAWS)]

        assert not set(drawn) & set(persisted)

    def test_two_instances_in_one_process_draw_from_one_sequence(
        self, build: Callable[[], Any]
    ) -> None:
        """The case that carries the whole difference between process and instance.

        A factory holding a per-instance counter and no per-process part passes
        every case above and fails this one, which is the reset ADR-0192 §2's scope
        is written against.
        """
        first = build()
        second = build()

        drawn = [first() for _ in range(_DRAWS)] + [second() for _ in range(_DRAWS)]

        assert len(set(drawn)) == 2 * _DRAWS

    def test_a_reservation_taken_by_one_instance_binds_the_next(
        self, pinned: Callable[[str], Any], pinned_pair: Callable[[str], tuple[Any, Any]]
    ) -> None:
        """Reservations are process state too, and this is the half that proves it.

        A factory whose *issued* ids are process-global but whose *reservations*
        are instance-local passes both halves of the scope separately and still
        reissues: instance A reserves the persisted claim ``x``, ``clear()`` erases
        it, and instance B mints it — at which point the stale completion lands on
        the new claim.

        ``stale`` is drawn from a twin space for the reason the case above gives: an
        id this space issued is one it has already moved past, so reserving it proves
        nothing. Over one nonce the twin's first id is exactly what ``second`` would
        return first, so the only thing that can keep it back is a reservation the
        *other instance* took.
        """
        stale = pinned("binding")()
        first, second = pinned_pair("binding")
        first.reserve([stale])

        drawn = [second() for _ in range(_DRAWS)]

        assert stale not in drawn

    @pytest.mark.skipif(not hasattr(os, "fork"), reason="platform has no fork")
    def test_two_forked_children_sharing_a_nonce_still_differ(
        self, pinned: Callable[[str], Any]
    ) -> None:
        """ADR-0049 §5's own shape, for ADR-0049 §3's own reason.

        A factory is constructed in the **parent** with a single fixed nonce, then
        forked. A fork copies the nonce and the counter into both children, so the
        only thing that can differentiate their ids is the pid — and only if it is
        read at allocation rather than captured at construction. A factory that
        freezes its prefix at construction passes every same-process case above and
        fails this one.

        **Both children are forked before either allocates**, which is the shape
        ADR-0192 §9 states and not an incidental arrangement. Forking one child,
        reading its id and *reaping* it before forking the second frees its pid for
        the OS to recycle: the second child can then be given the same pid, and with
        the same nonce and the same copied counter a **conforming** factory mints
        the same id — a case that fails at random on the implementation it exists to
        certify. Reaped only after both have minted, so the two pids cannot be equal
        and the assertion is about the factory rather than about the scheduler. The
        gate makes it stronger still: neither child allocates until the parent has
        forked both and closed the write end, which is the literal reading of
        "forked before either allocates".
        """
        factory = pinned("SHARED")
        gate_read, gate_write = os.pipe()  # closed by the parent to release both at once
        reports = [os.pipe(), os.pipe()]
        children: list[int] = []

        try:
            for index, (_, write_fd) in enumerate(reports):
                child = os.fork()
                if child == 0:  # pragma: no cover - the child never reports coverage
                    os.close(gate_write)
                    for other, (read_end, write_end) in enumerate(reports):
                        os.close(read_end)
                        if other != index:
                            os.close(write_end)
                    with os.fdopen(gate_read) as gate:
                        gate.read()  # nothing is allocated until the parent lets go
                    with os.fdopen(write_fd, "w") as pipe:
                        pipe.write(factory())
                    os._exit(0)
                children.append(child)
        finally:
            os.close(gate_write)  # both children are forked; release them together
            os.close(gate_read)
            for _, write_fd in reports:
                os.close(write_fd)

        drawn: list[str] = []
        for child, (read_fd, _) in zip(children, reports, strict=True):
            with os.fdopen(read_fd) as pipe:
                drawn.append(pipe.read())
            os.waitpid(child, 0)  # reaped only now, so neither pid was recyclable

        assert len(drawn) == 2
        assert "SHARED" in drawn[0]
        assert drawn[0] != drawn[1], "forked children sharing a nonce must differ by pid"
