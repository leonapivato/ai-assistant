"""Capture parents cannot outlive the safety work their shutdown drain depends on."""

from __future__ import annotations

import asyncio

import pytest

from ai_assistant.orchestration.activation_cleanup import drain_registered


@pytest.mark.parametrize("cancel_child", [False, True])
async def test_parent_cancellation_waits_for_child_cleanup_even_after_second_cancel(
    cancel_child: bool,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    cleaned = asyncio.Event()
    cancelled = asyncio.Event()

    async def child() -> int:
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        finally:
            await release.wait()
            cleaned.set()
        return 7

    work = asyncio.create_task(child())
    parent = asyncio.create_task(drain_registered(work, cancel_on_interrupt=cancel_child))
    await entered.wait()
    parent.cancel()
    if cancel_child:
        await cancelled.wait()
    else:
        await asyncio.sleep(0)
    parent.cancel()
    await asyncio.sleep(0)
    assert not parent.done()
    assert not work.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await parent
    assert work.done()
    assert cleaned.is_set()
    assert cancelled.is_set() is cancel_child


async def test_ordinary_cleanup_deadline_waits_for_deletion_verification() -> None:
    verifying = asyncio.Event()
    release = asyncio.Event()
    verified = asyncio.Event()
    expire = asyncio.Event()

    async def verification() -> None:
        verifying.set()
        await release.wait()
        verified.set()

    async def writing() -> None:
        try:
            await expire.wait()
        finally:
            task = asyncio.create_task(verification())
            await drain_registered(task, cancel_on_interrupt=False)

    task = asyncio.create_task(writing())
    # First enter the ordinary write. Its cancellation stands for the outer
    # monotonic timeout; the test controls ordering rather than wall time.
    await asyncio.sleep(0)
    task.cancel()
    await verifying.wait()
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert verified.is_set()


async def test_uncancelled_child_result_or_failure_is_preserved() -> None:
    async def successful() -> int:
        return 7

    async def failed() -> int:
        raise RuntimeError("original failure")

    assert await drain_registered(asyncio.create_task(successful()), cancel_on_interrupt=True) == 7
    with pytest.raises(RuntimeError, match="original failure"):
        await drain_registered(asyncio.create_task(failed()), cancel_on_interrupt=True)
