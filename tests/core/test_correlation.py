"""The ambient correlation carrier ADR-0119 §4 leaves to the implementing lane.

§4 states the requirement and refuses the obvious mechanism: "a measure over a
pair of events is computable from the stream alone: by the correlation identifier
where the pair falls inside one operation", and the identifier "is **not** added
to ``MemoryStore``, ``MemoryWriter`` or any other existing Protocol's signature".
What is left is a carrier that must be ambient, must be readable from every
subsystem, and must not confuse two concurrent operations.

The last of those is the one worth testing hardest, because it is the one a
plausible wrong implementation — an attribute on the engine, a module-level
string — gets wrong only under concurrency, which is to say only in production.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from ai_assistant.core.correlation import correlated_operation, current_correlation

#: The shape §4's identifier is minted in — the same 32 hex characters
#: ``EvaluationTrace.id`` is bound to, though this one is checked here rather
#: than by a type, because ``refs`` values are ``Identifier`` (§13a: "the type
#: closes the field this ADR mints, and review closes the fields it borrows").
_MINTED = re.compile(r"[0-9a-f]{32}")


def test_no_operation_in_scope_reads_as_absent() -> None:
    """``None`` outside a scope, which is what an emitter records as absent.

    A hub startup's ``CONFIGURATION`` trace (§9) is emitted outside any
    ``AssistantEngine`` operation, and so is any subsystem a test drives directly.
    Neither has a correlation to carry, and §3's observation rule says the answer
    to "not observed" is an absent key rather than a stand-in value — so the
    carrier has to be able to say "nothing", and an empty string would not.
    """
    assert current_correlation() is None


def test_a_scope_mints_an_opaque_identifier_and_yields_it() -> None:
    """The value is minted here and read back, and it is not derived from anything.

    §2 admits an identifier into a trace on its **origin** — "an opaque value
    minted by this system" — and the module has no setter at all, so origin is a
    property of the code rather than a promise about callers.
    """
    with correlated_operation() as correlation:
        assert _MINTED.fullmatch(correlation)
        assert current_correlation() == correlation


def test_two_operations_mint_different_identifiers() -> None:
    """A join key that repeated would join unrelated events into one operation."""
    with correlated_operation() as first:
        pass
    with correlated_operation() as second:
        pass
    assert first != second


def test_leaving_a_scope_restores_what_was_there() -> None:
    """The reset uses the token, so an inner scope leaves the outer one intact.

    Nested operations are not a shape this system produces today — a public
    ``Engine`` call does not call another — but the difference between a token
    reset and a re-set to ``None`` is invisible until one appears, at which point
    the second silently erases the enclosing operation's identifier and every
    trace emitted after the inner one closes joins to nothing.
    """
    with correlated_operation() as outer:
        with correlated_operation() as inner:
            assert current_correlation() == inner
            assert inner != outer
        assert current_correlation() == outer
    assert current_correlation() is None


def test_a_raising_body_still_unbinds() -> None:
    """The unbind is in a ``finally``, because the fault path is the traced one.

    §8's whole reason for the engine-boundary trace is that a failing operation
    still emits one (ADR-0074's deferral discharged), so a scope that leaked on the
    raising path would leak on exactly the operations this instrument exists for.
    """
    with pytest.raises(RuntimeError), correlated_operation():
        raise RuntimeError("the operation failed")
    assert current_correlation() is None


async def test_two_concurrent_operations_do_not_see_each_other() -> None:
    """The property that decides the mechanism (§4).

    Each task gets its own copy of the context, so a ``ContextVar`` set inside one
    is invisible to the other. An attribute on the engine would pass every test
    above and fail this one — and would fail it by attributing a turn's retrieval
    to a scheduled job that happened to overlap it, which is a wrong measurement
    rather than a crash.
    """
    started = asyncio.Event()
    ids: dict[str, str | None] = {}

    async def first() -> None:
        with correlated_operation() as correlation:
            ids["first_own"] = correlation
            started.set()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            ids["first_after"] = current_correlation()

    async def second() -> None:
        await started.wait()
        with correlated_operation() as correlation:
            ids["second_own"] = correlation
            await asyncio.sleep(0)
            ids["second_after"] = current_correlation()

    async with asyncio.TaskGroup() as group:
        group.create_task(first())
        group.create_task(second())

    assert ids["first_after"] == ids["first_own"]
    assert ids["second_after"] == ids["second_own"]
    assert ids["first_own"] != ids["second_own"]


async def test_a_child_task_inherits_the_operation_it_was_created_inside() -> None:
    """What makes a subsystem's emitter reachable at all (§4, §8).

    §4 names this by mechanism — "asyncio propagates a context into tasks created
    inside it, which is what ``Engine._tracked``'s shielded task is" — and §8 needs
    it for the seams below the engine: a ``RETRIEVAL`` trace emitted by a store
    call several awaits deep has to reach the same identifier the operation's
    envelope carries, or the pair §4 requires cannot be joined.
    """
    seen: list[str | None] = []

    async def deep() -> None:
        await asyncio.sleep(0)
        seen.append(current_correlation())

    with correlated_operation() as correlation:
        await asyncio.create_task(deep())

    assert seen == [correlation]


async def test_the_scope_does_not_escape_into_a_task_that_outlives_it() -> None:
    """A task created *outside* the scope reads nothing from it.

    The complement of the inheritance above, and the reason it is safe: context
    propagation is by copy at task creation, so the binding travels down and never
    sideways. A carrier that leaked sideways would attribute one operation's
    traces to a concurrent one.
    """
    with correlated_operation():
        pass

    async def after() -> str | None:
        return current_correlation()

    assert await asyncio.create_task(after()) is None
