# 54. A cancelled store call must not release its connection while a worker thread still holds it

- Status: Accepted
- Date: 2026-07-24
- **Not a contract change.** This ADR touches no Protocol in
  `core/protocols.py`, no `core` type, and no `Settings` field. It fixes the
  *internals* of three existing durable-store implementations
  (`SqliteMemoryStore`, `SqliteAuditTrail`, `SqlitePlanStore`) so their observable
  behaviour matches the guarantees their contracts already imply. Golden rule 5's
  separate-PR ratification does not apply, so this ADR is **Accepted on merge**,
  landed together with the implementation.

## Context

All three durable stores serialise a single `sqlite3` connection
(`check_same_thread=False`) behind an `asyncio.Lock`, then hand the actual SQL to
a worker thread — the shared house style:

```python
async with self._lock:
    await asyncio.to_thread(self._sync_op, ...)
```

`asyncio.to_thread` cannot interrupt a running worker. If the coroutine awaiting
`to_thread` is **cancelled**, `CancelledError` unwinds the `async with self._lock`
and **releases the lock while the worker thread is still running `self._sync_op`
on the shared connection**. A second coroutine can then acquire the lock and use
the *same* connection concurrently with the still-running first thread. SQLite
refuses concurrent use of one connection, so a valid operation raises
("recursive use of cursors" / database locked), or a transaction boundary the
code assumes is violated — a concurrent read can observe partial, uncommitted
state (for `write_atomic`, a window-close without its paired insert; for `add`, a
record row without its vector row).

This was surfaced by the adversarial reviews of #299 (issue #300) and #309
(issue #312), which are the same bug. It is not urgent today: the system composes
on one event loop (CLAUDE.md), and the Engine façade drains in-flight work on
`aclose` (ADR-0042 §2) rather than cancelling a store mid-write, so a mid-write
cancellation is not a path the architecture currently exercises. But it is a
pre-existing property of the shared pattern, identical across all three stores,
and issue #312 deliberately scopes the fix as one cross-cutting change against
the pattern rather than three divergent per-store patches.

The invariant to establish, uniformly: *the connection is never used by a second
caller while a cancelled call's worker thread still holds it.*

Two mechanisms were on the table. **(a) Shield** the `to_thread` so the lock is
held until the thread actually finishes even under cancellation. **(b) Serial
worker** — route all SQL through a single long-lived DB-worker task that owns the
connection, so no caller ever touches it directly.

## Decision

We will fix this with mechanism **(a), a shield over the worker**, applied
identically in all three stores, but keyed on the worker's *physical* completion
rather than on the cancellable state of any task. Each store gains a private
module-level helper:

```python
async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    done = threading.Event()
    outcome: list[T] = []
    failure: list[Exception] = []

    def worker() -> None:
        try:
            outcome.append(fn(*args))
        except Exception as exc:  # relayed to the caller once the thread has finished
            failure.append(exc)
        finally:
            done.set()

    loop = asyncio.get_running_loop()
    pending: asyncio.Future[Any] = loop.run_in_executor(None, worker)
    cancellation: asyncio.CancelledError | None = None
    while not done.is_set():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError as exc:
            cancellation = exc
            pending = loop.run_in_executor(None, done.wait)
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]
```

Every `await asyncio.to_thread(self._sync_op, ...)` inside a `async with
self._lock` becomes `await _run_to_completion(self._sync_op, ...)`. The helper is
awaited *inside* the lock and does not return (or raise) until the worker thread
has physically finished — signalled by a `threading.Event` the worker sets in a
`finally` — so the lock is held for the whole life of the worker. When the
awaiting coroutine is cancelled, the helper absorbs the cancellation, keeps
waiting on that physical signal, and only then re-raises the `CancelledError`.

Two design points earn the shape:

- **The wait is on the worker's own signal, not on a task's cancelled state.**
  An earlier draft awaited `asyncio.ensure_future(asyncio.to_thread(...))` and, on
  catching a cancellation, checked `task.cancelled()` to decide whether to
  release. But that wrapper is a real `asyncio.Task`, discoverable through
  `asyncio.all_tasks()`; a blanket shutdown sweep cancelling it *after* the OS
  thread had started would make the check release the lock while the thread was
  still on the connection — the very bug. Nothing in the final helper is a
  `Task`: the work runs on an executor *future* and the fallback wait on another,
  so a task sweep finds nothing to cancel out from under the running thread, and
  the lock is released only when `done` is set.
- **An absorbed cancellation takes precedence over the worker's result or
  failure.** If the worker raises as it finishes while a cancellation is pending,
  the caller asked to cancel, so it must see `CancelledError` — not the store
  error the worker happened to raise. The store error is discarded; the connection
  is already safe because the thread has finished.

The helper is **duplicated** in each of the three store modules rather than
shared from a common location. A shared home would have to be `core` (the only
package everything may depend on), and this change deliberately touches no
`core`; a cross-subsystem import from one store into another is forbidden by the
architecture boundaries (golden rules 1–2, enforced by `lint-imports`). Each
store fixing its own internals with an identical helper is the price of keeping
the boundary clean, and is cheap to keep in step.

Mechanism (b), the serial worker, is rejected as heavier than the problem
warrants: it restructures each store's lifecycle (a task to start and to drain on
`close`), adds a queue and result-plumbing, and changes far more than the bug
requires. The helper is a local change per store that establishes the invariant
with no lifecycle surface. Since this is correctness insurance for a path the
one-event-loop, drain-on-`aclose` model does not currently exercise — not a hot
path — the smaller mechanism is the right trade. On the common (uncancelled) path
it uses exactly one worker thread, no more than the pattern it replaces; the
fallback wait spawns a second thread only after a cancellation is absorbed.

## Consequences

- **The invariant holds uniformly.** A cancelled call in any of the three stores
  now keeps the lock until its worker thread finishes, so no second caller can
  ever reuse the connection concurrently. The SQLite "recursive use" / partial-
  state failures the issues describe are unreachable.
- **Cancellation is deferred, not swallowed.** A cancelled caller's task still
  raises `CancelledError`; it just does so after the in-flight worker completes.
  In the pathological case where a worker never returns, the cancellation would
  not take effect until it does — acceptable, because a store `_sync_op`'s only
  blocking wait is SQLite's own, and the composition model does not cancel store
  writes in practice. If a store ever grows a genuinely unbounded sync op this
  trade would need revisiting.
- **A committed cancelled write stays committed.** Because the worker runs to
  completion, a write whose awaiting coroutine was cancelled after the worker
  reached `COMMIT` remains durably written. This matches the connection-safety
  goal (the store is never left inconsistent) and is what the regression tests
  assert.
- **Deterministic regression coverage per store.** Each store gains a test that
  blocks a worker mid-write, cancels the awaiting task, asserts the lock is still
  held (the pre-fix code released it), starts a second write that must queue, and
  after release asserts both writes are intact on a working connection. Each test
  fails on the pre-ADR-0054 pattern and passes on the fix. A further memory-store
  test covers the precedence rule — a cancellation whose worker then raises still
  surfaces `CancelledError`, not the store error — guarding the shared helper's
  logic that is byte-identical across the three modules.
- **The house style gains a rule.** Any future durable store following the
  `async with self._lock: await asyncio.to_thread(...)` pattern must route the
  `to_thread` through the same completion-guaranteeing helper. This ADR is the
  reference for why.
