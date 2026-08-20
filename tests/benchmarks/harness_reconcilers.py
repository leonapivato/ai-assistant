"""An offline reconciler for every harness test that ingests.

Since #1293 the harness wires ADR-0159's reconciler, which means a
:func:`~benchmarks.memory.wiring.build_harness` left to the settings builds a
*live* ``PydanticAIProvider`` and a test that ingests anything will reach the
network — quietly, because ADR-0159 §3's never-raises clause turns the resulting
failure into an unlabelled conflict set rather than an error. The observable
symptom is a test that got nine seconds slower, which is exactly the kind of
signal a suite absorbs without anyone noticing.

So the reconciler is injected, on the terms every other model seam in this suite is
injected on: the *provider* is a :class:`~ai_assistant.testing.FakeModelProvider`
and everything around it is the production object — a real
``ModelBackedReconciler``, on a real route, under a real bound. The reconciler is
therefore genuinely exercised: it is consulted, it renders its prompt, it reads the
reply back and fails to find an envelope in it, and it reports
:attr:`~ai_assistant.memory._reconciler.ReconcilerOutcome.FAILED` — a determinate
outcome ADR-0164 §3 names, and the one every test here wants, since none of them is
about what a labeller decides.

Shared as a bare module rather than a fixture because ``tests/conftest.py`` says why
there is only one conftest in this corpus (mypy refuses a second module of that
name); it is the arrangement ``tests/core/reader_contract.py`` already has.

Tests whose subject *is* the real wiring — the equivalence check in
``test_harness_contracts.py`` — deliberately do not use this, and build what the
settings name.
"""

from __future__ import annotations

from typing import Final

from benchmarks.memory.wiring import Reconciliation

from ai_assistant.testing import FakeModelProvider

__all__ = ["OFFLINE_ROUTE", "offline_reconciler"]

#: The route the injected reconciler names.
#:
#: Deliberately not a real ``"provider:model"`` spec: nothing resolves it, because
#: nothing may. A test asserting on a manifest's ``reconciler`` field can match this
#: and know the value came from the injected object rather than from ``Settings``.
OFFLINE_ROUTE: Final = "fake:reconciler"


def offline_reconciler(*, max_conflicts: int = 3) -> Reconciliation:
    """Build the production reconciler over an offline provider.

    Args:
        max_conflicts: ADR-0159 §3's bound to construct it under.

    Returns:
        The reconciler and its description, in the shape ``build_reconciler``
        returns — so a test injecting one exercises the same field the manifest
        reads and the same object the ingestor holds.
    """
    return Reconciliation(
        model=FakeModelProvider("no envelope here"),
        route=OFFLINE_ROUTE,
        max_conflicts=max_conflicts,
    )
