"""ADR-0264 §13 item 8: a driven egress step establishes no contact, and is not nothing.

The classification §2's egress clause states is computed **here**, in
:class:`~ai_assistant.orchestration.runner.StepRunner`, from the two facts that stage
holds: the request's own ``EgressBinding``, and — through
:class:`~ai_assistant.orchestration.executor.CallableReach` — the executor's own
pre-callable fact. §11's ownership rule puts these assertions in lane 1 with the code
they are about.

**The contribution is stated over the executor's own fact and never over**
``Disposition.EXECUTED`` (§2, §3). That disposition is returned for the three windows
ADR-0192 §1 places *before* the callable as well as for a call that reached it, so an
implementation reading it would report a refused spend as a send that may have left.
Every arm below therefore drives the real executor over the real seam and reads the
classification off the disposition the runner returns.

The turn-level half of item 8 — "the arm asserts each of those three turns" — is at the
foot of this module, over ADR-0264 §6's own assembly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_runner_egress import (
    ATTEMPT,
    CAPABILITY,
    PATIENT,
    STEP,
    _an_execution,
    _bound_binder,
    _Harness,
    _step,
    _tool,
)

from ai_assistant.core.errors import SpendCeilingError
from ai_assistant.core.types import (
    Disposition,
    OutboundDestination,
    OutboundReach,
    StepStatus,
)
from ai_assistant.orchestration.origin import NOTHING_EXTERNAL
from ai_assistant.orchestration.reads import outbound_statement
from ai_assistant.testing import FakeToolInvoker

if TYPE_CHECKING:
    from ai_assistant.core.types import ToolDefinition

AT: Final = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)


async def _succeeds(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that reaches the callable and returns normally."""


async def _fails(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that reaches the callable and then raises.

    ADR-0029 §5 classifies this as a *result*, not a pre-callable exit — so the
    step's addressed ``StepExecution`` is not ``SUCCEEDED`` and the executor still
    reached the callable. That pair is what §13 item 8's second shape is about: "a
    failed send may still have transmitted".
    """
    msg = "the integration is broken"
    raise RuntimeError(msg)


class _RefusingGate:
    """A ``SpendGate`` that refuses every admission, **before** the callable.

    ADR-0192 §1's second window, and ADR-0194 §4 commits it ``FAILED`` "with the
    refusal's **own** account so a budget stop does not read as an internal fault".
    ADR-0264 §2 reads that as the executor establishing that the call provably never
    reached the callable, so the step contributes nothing rather than
    ``INDETERMINATE``.
    """

    def __init__(self) -> None:
        """Refuse every admission, and count what was asked."""
        self.asked = 0

    async def admit_invocation(self, *, estimate: Any) -> Any:
        """Refuse, having recorded that the seam reached the gate at all."""
        del estimate
        self.asked += 1
        raise SpendCeilingError("the ceiling refused this call")

    def release_admission(self, handle: Any) -> None:
        """Retire a handle this holder never delivered."""


def _egress(*, callable_: Any) -> tuple[ToolDefinition, _Harness]:
    """A runner over one **egress** tool bound to a connected account.

    ``discloses`` is empty so ``FakeActionPolicy`` reaches ``ALLOW`` rather than the
    ``CONFIRM`` ADR-0148 §8's second clause draws for a disclosing tool: this arm is
    about a step that was *driven*, and a parked one drives nothing.
    """
    definition = _tool(egress=True, discloses=())
    harness = _Harness(tool=definition, binder=_bound_binder(definition))
    harness.invoker = FakeToolInvoker(
        [(definition, callable_)], ledger=harness.trail, gate=harness.trail
    )
    return definition, _rewired(harness, definition, callable_, gate=harness.trail)


def _rewired(
    harness: _Harness, definition: ToolDefinition, callable_: Any, *, gate: Any, egress: bool = True
) -> _Harness:
    """Rebuild the harness's runner over a seam with this arm's callable and gate.

    ``_Harness`` wires its invoker in its own constructor, so a case that varies the
    callable or the gate rebuilds the stage rather than reaching into it — which keeps
    the subject under test the production ``StepRunner`` and ``StepExecutor`` over a
    seam a case arranged, and never a patched one.
    """
    from ai_assistant.orchestration import StepExecutor, StepRunner  # noqa: PLC0415 — the subject

    invoker = FakeToolInvoker([(definition, callable_)], ledger=harness.trail, gate=gate)
    harness.invoker = invoker
    harness.runner = StepRunner(
        plans=harness.plans,
        registry=invoker,
        policy=harness.policy,
        trail=harness.trail,
        executor=StepExecutor(
            plans=harness.plans, registry=invoker, invoker=invoker, now=lambda: AT
        ),
        binder=_bound_binder(definition) if egress else None,
        now=lambda: AT,
        id_factory=lambda: next(harness.ids),
    )
    return harness


async def _driven(harness: _Harness) -> Any:
    """Store a plan, open an execution, and drive the one step."""
    state = await _an_execution(harness.plans, _step())
    return await harness.runner.run(
        state,
        STEP,
        attempt_id=ATTEMPT,
        timeout=PATIENT,
        origin=NOTHING_EXTERNAL,
    )


# --- §13 item 8's first two shapes: the callable was reached ------------------


async def test_a_send_whose_callable_was_reached_contributes_indeterminate() -> None:
    """§13 item 8, first shape: reached, and the addressed status is ``SUCCEEDED``.

    "One whose callable was reached and whose addressed ``StepExecution`` is
    ``SUCCEEDED`` … carries ``reach`` **``INDETERMINATE``** with ``destinations``
    empty on a turn with no established search contact."

    **It is not ``REACHED``** (§3): ADR-0192 §4 rules that ``SUCCEEDED`` is "bounded by
    ADR-0031 §4 to exactly three facts — a validated callable return, an unexpired
    deadline, and no increase in the cancellation count — and none of them is a
    transmission", and "an egress callable that returns normally without putting a byte
    on the wire produces ``SUCCEEDED`` like any other".
    """
    _, harness = _egress(callable_=_succeeds)

    disposition = await _driven(harness)

    assert disposition.disposition is Disposition.EXECUTED
    stored = await harness.plans.get_execution(disposition.state.id)
    assert stored is not None
    step = stored.step(STEP)
    assert step is not None
    assert step.status is StepStatus.SUCCEEDED
    assert disposition.outbound is OutboundReach.INDETERMINATE


async def test_a_send_that_failed_after_reaching_the_callable_contributes_it_too() -> None:
    """§13 item 8, second shape: reached, and the addressed status is **not** ``SUCCEEDED``.

    "An implementation gating on ``SUCCEEDED`` fails the second — a failed send may
    still have transmitted." The callable raised, which ADR-0029 §5 classifies as a
    *result*: the send may well have gone out and the provider then refused it, and
    saying the turn reached nothing "would be the false statement §1 ranks below
    silence".
    """
    _, harness = _egress(callable_=_fails)

    disposition = await _driven(harness)

    assert disposition.disposition is Disposition.EXECUTED
    stored = await harness.plans.get_execution(disposition.state.id)
    assert stored is not None
    step = stored.step(STEP)
    assert step is not None
    assert step.status is not StepStatus.SUCCEEDED
    assert disposition.outbound is OutboundReach.INDETERMINATE, (
        "a failed send may still have transmitted (ADR-0264 §13 item 8)"
    )


# --- §13 item 8's third shape: the executor proved the callable unreached -----


async def test_a_send_refused_before_the_callable_contributes_nothing() -> None:
    """§13 item 8, third shape: one of ADR-0192 §1's three pre-callable windows.

    "One the executor exited **before the callable** (ADR-0192 §1's three windows): it
    **contributes nothing**." §2 gives the reason in the executor's own words: the three
    exits are "committed ``FAILED`` for the stated reason that recording
    ``INDETERMINATE`` would be *about a call that provably never reached the
    callable*".

    **The disposition is still ``EXECUTED``**, which is exactly why §2 refuses to be
    stated over it: an implementation reading the disposition would report this refused
    spend as a send that may have left.
    """
    definition = _tool(egress=True, discloses=())
    gate = _RefusingGate()
    harness = _rewired(
        _Harness(tool=definition, binder=_bound_binder(definition)),
        definition,
        _succeeds,
        gate=gate,
    )

    disposition = await _driven(harness)

    assert gate.asked == 1, "the seam reached the gate, and the gate refused before the call"
    assert disposition.disposition is Disposition.EXECUTED, (
        "which is why §2 is stated over the executor's own fact and never over this"
    )
    assert disposition.outbound is None, "nothing was established, so nothing is contributed"


async def test_a_step_carrying_no_egress_binding_contributes_nothing() -> None:
    """§3: the contribution is over a step whose request carried an ``EgressBinding``.

    A non-egress call is not an outbound act at all — "a driven step establishes none,
    whatever its binding, its disposition or its addressed status" — so it contributes
    nothing however it ran, and a turn whose only step was one of these answers
    ``NOT_REACHED`` on its own account.
    """
    definition = _tool(egress=False, discloses=())
    built = _Harness(tool=definition, binder=None)
    harness = _rewired(built, definition, _succeeds, gate=built.trail, egress=False)

    disposition = await _driven(harness)

    assert disposition.disposition is Disposition.EXECUTED
    assert disposition.outbound is None


@pytest.mark.parametrize("skipped", [Disposition.NO_CAPABLE_TOOL])
async def test_a_step_that_was_never_driven_contributes_nothing(skipped: Disposition) -> None:
    """§2: "A step that was refused, denied or never driven contributes nothing".

    The runner never reaches ``_execute`` on such a disposition, so there is no
    executor fact to read and the field keeps its ``None`` default — which is what the
    fold then treats as no contribution at all.
    """
    elsewhere = _tool(egress=True, discloses=(), tool_id="other").model_copy(
        update={"capability": "something-else"}
    )
    built = _Harness(tool=elsewhere, binder=None)
    harness = _rewired(built, elsewhere, _succeeds, gate=built.trail, egress=False)

    state = await _an_execution(harness.plans, _step())
    disposition = await harness.runner.run(
        state, STEP, attempt_id=ATTEMPT, timeout=PATIENT, origin=NOTHING_EXTERNAL
    )

    assert disposition.disposition is skipped, "no tool declares this step's capability"
    assert disposition.outbound is None


# --- §13 item 8's turn-level half: no egress outcome overrides the fold -------


def test_no_egress_outcome_overrides_the_turns_own_answer() -> None:
    """§13 item 8: "**No egress outcome overrides the fold** (§2): the arm asserts each
    of those three turns."

    "A turn whose only other call reached the provider stays ``REACHED``, one whose
    other call established nothing either way stays ``INDETERMINATE``, and one with no
    other call is ``NOT_REACHED``" — asserted here over the pre-callable shape, which
    contributes nothing.

    **And an executed step never mints a contact**: the reached shape contributes
    ``INDETERMINATE``, which cannot outrank a search's ``REACHED`` and cannot name a
    class. "An implementation that mints a contact from an executed step fails this
    arm, **and so does one that answers ``NOT_REACHED``** for a step whose callable was
    reached."
    """
    unreached = outbound_statement(
        search=OutboundReach.REACHED, egress=None, records=1, composed=True
    )
    assert unreached is not None
    assert unreached.reach is OutboundReach.REACHED

    beside_undetermined = outbound_statement(
        search=OutboundReach.INDETERMINATE, egress=None, records=0, composed=True
    )
    assert beside_undetermined is not None
    assert beside_undetermined.reach is OutboundReach.INDETERMINATE

    alone = outbound_statement(search=None, egress=None, records=0, composed=True)
    assert alone is not None
    assert alone.reach is OutboundReach.NOT_REACHED

    reached_callable = outbound_statement(
        search=OutboundReach.REACHED, egress=OutboundReach.INDETERMINATE, records=1, composed=True
    )
    assert reached_callable is not None
    assert reached_callable.reach is OutboundReach.REACHED
    assert reached_callable.destinations == (OutboundDestination.SEARCH_PROVIDER,), (
        "the class is the search's, and no send names one (ADR-0264 §3)"
    )

    send_alone = outbound_statement(
        search=None, egress=OutboundReach.INDETERMINATE, records=0, composed=True
    )
    assert send_alone is not None
    assert send_alone.reach is OutboundReach.INDETERMINATE
    assert send_alone.destinations == (), "no class is named on a send's account"


def test_the_deadline_this_module_drives_under_is_the_harness_s() -> None:
    """A guard on the import above, so a rename in ``test_runner_egress`` is a failure."""
    assert timedelta(seconds=30) == PATIENT
    assert CAPABILITY == "send_email"
