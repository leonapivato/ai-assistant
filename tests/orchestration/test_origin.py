"""The two call-level facts one pass computes over one selection set.

ADR-0181 §4 puts computing ``planned_with_external_content`` on the component that
made the selection; ADR-0233 §5 puts computing ``coverage`` on "the component that
**composed the call's arguments**, from the membership and path character of what it
supplied to the operations that produced them". That is the same component, over the
same supply, on the same pass — so
:meth:`~ai_assistant.orchestration.origin.SelectionOrigin.over` computes both, and
this module is the case set for the second of them.

**Three properties, each a distinct way to get it wrong.** The value is decided by
what was *selected from a store*, not by the predicate the sibling fact folds, so a
clean record covers a call exactly as a tainted one does. It is monotone under
combining, so no later selection weakens what an earlier one recorded (ADR-0233 §5's
third clause, ADR-0106 §4). And each selection is read once, so a caller handing an
iterator gets both facts rather than one fact and one accident.

What this module deliberately does not test is the value's arrival at the binding —
that is ``test_runner_egress`` at the stage that writes it and
``test_engine_span_coverage`` end to end, because a computation nothing reads is not
the obligation ADR-0233 §15 states.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    Attestation,
    MemorySource,
    Provenance,
    SemanticMemory,
    SpanCoverage,
    Validity,
)
from ai_assistant.orchestration.origin import NOTHING_EXTERNAL, SelectionOrigin

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ai_assistant.core.types import MemoryRecord

AT: Final = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)


def _belief(record_id: str = "rec-1") -> SemanticMemory:
    """A belief this system authored, carrying no externality mark at all.

    ``OBSERVED`` puts it outside the ``ATTESTED`` band and it carries no
    ``derived_from_external``, so ``rests_on_recorded_external_content`` is false of
    it. That is what makes it the record separating the two facts: it covers a call
    without tainting one.
    """
    return SemanticMemory(
        id=record_id,
        content="the roof needs looking at before winter",
        fact="the roof needs looking at before winter",
        validity=Validity(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.8, last_updated=AT),
    )


def _external_belief(record_id: str = "rec-external") -> SemanticMemory:
    """A belief in the ``ATTESTED`` band, which is where externality is recorded."""
    return SemanticMemory(
        id=record_id,
        content="the invite says the address changed",
        fact="the invite says the address changed",
        validity=Validity(),
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=0.9,
            last_updated=AT,
            attestation=Attestation(reported_by="calendar:work", reported_at=AT),
        ),
    )


def test_a_selection_from_a_store_puts_a_model_call_on_every_covered_path() -> None:
    """ADR-0233 §5, over ADR-0155 §3's first clause: the memory-drawn case.

    Every record in a selection is "a value any component obtained from a store this
    system keeps under ``Settings.data_dir``", so a non-empty selection is covered
    material supplied to the model call whose output composed the request's
    arguments. ADR-0155's own Consequences state the consequence: "once recalled
    records are supplied to the planner's model call, its output is covered content
    all of whose covered paths run through that call" — which is exactly
    ``MODEL_ON_EVERY_PATH``.
    """
    assert SelectionOrigin.over((_belief(),)).coverage is SpanCoverage.MODEL_ON_EVERY_PATH


def test_selecting_nothing_is_a_computed_not_covered_and_not_a_default() -> None:
    """ADR-0233 §4's no-default clause, answered rather than fallen back on.

    Three spellings of "this caller selected nothing" — no selection at all, one
    empty selection, and several — and the constant a caller states in code. All four
    agree, because all four are the same computation: :data:`NOTHING_EXTERNAL` is
    built by calling ``over`` with nothing rather than by restating its answer, so
    the constant and the computation cannot come apart.
    """
    assert SelectionOrigin.over().coverage is SpanCoverage.NOT_COVERED
    assert SelectionOrigin.over(()).coverage is SpanCoverage.NOT_COVERED
    assert SelectionOrigin.over((), (), ()).coverage is SpanCoverage.NOT_COVERED
    assert SelectionOrigin.over() == NOTHING_EXTERNAL
    assert NOTHING_EXTERNAL.coverage is SpanCoverage.NOT_COVERED


def test_a_clean_record_covers_a_call_exactly_as_a_tainted_one_does() -> None:
    """ADR-0233 §4's fifth clause: neither axis is read off the other.

    The case that fails an implementation which computed ``coverage`` from the
    boolean — the cheapest wrong thing to write, and one every other case here would
    pass. A belief this system authored over its own observations carries no
    externality mark, so ``planned_with_external_content`` is ``False``; it was still
    obtained from a store, so the call it was selected into is covered.
    """
    clean = SelectionOrigin.over((_belief(),))
    tainted = SelectionOrigin.over((_external_belief(),))

    assert clean.planned_with_external_content is False
    assert tainted.planned_with_external_content is True
    assert clean.coverage is tainted.coverage is SpanCoverage.MODEL_ON_EVERY_PATH


@pytest.mark.parametrize("clean_first", [True, False])
def test_a_later_clean_selection_never_clears_what_an_earlier_one_recorded(
    *, clean_first: bool
) -> None:
    """ADR-0233 §5's third clause, which is ADR-0106 §4 read on this axis.

    "No component and no later step of a plan weakens a value an earlier one
    recorded." The laundering shape this forecloses is the one ADR-0181 §4 named one
    field over: plan a step over material drawn from the store, re-plan over a clean
    supply, stamp the binding from the last selection, and watch the fact clear. Both
    orders are run because a fold that took the *last* state rather than the
    strongest would pass one of them.
    """
    selections: tuple[tuple[MemoryRecord, ...], ...] = (
        ((), (_belief(),)) if clean_first else ((_belief(),), ())
    )

    assert SelectionOrigin.over(*selections).coverage is SpanCoverage.MODEL_ON_EVERY_PATH


def test_each_selection_is_read_once_so_an_iterator_is_not_exhausted_by_the_first_fold() -> None:
    """The permissive answer must not be reachable by accident.

    ``over`` folds twice over what it is given, and its parameter is an ``Iterable``.
    An implementation folding straight over the caller's object would consume a
    one-shot iterator on the first fold and see an empty selection on the second —
    answering ``NOT_COVERED`` for a call composed over the store, which is the exact
    claim ADR-0233 §4's no-default clause exists to stop anyone making by accident.
    """
    records: Iterator[MemoryRecord] = iter((_external_belief(),))

    origin = SelectionOrigin.over(records)

    assert origin.planned_with_external_content is True
    assert origin.coverage is SpanCoverage.MODEL_ON_EVERY_PATH
