"""What a whole pass records about the coverage of the call it emits (ADR-0233 §5).

ADR-0233 §15 assigns the *computation* of ``coverage`` to the composer, and names
``StepRunner._bound`` as the site that writes it. ``test_runner_egress`` pins that
site with the selection stated by the case; this module runs the real engine over a
real supply, so what decides the value is what the pipeline actually retrieved rather
than what a test handed the stage.

**That is the case that fails an implementation which hard-codes.** Two passes over
identically-wired engines differing in **one** thing — whether the store holds a
record the ask retrieves — reach two different recorded bindings. A constant, on
either value, answers the same on both; so does an implementation that read the
answer off the payload, because both passes compose the same arguments.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from test_engine import (
    AT,
    PATIENT,
    Harness,
    bound_binder,
    egress_confirmable,
)

from ai_assistant.core.types import (
    Disposition,
    EgressBinding,
    MemorySource,
    Provenance,
    SemanticMemory,
    SpanCoverage,
    Validity,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import PermissionDecision

#: The ask, carrying the seeded record's own terms so the store's lexical search
#: selects it. A case that silently retrieved nothing would pass an implementation
#: that answers ``NOT_COVERED`` unconditionally, which is the direction ADR-0233 §4
#: calls the one nobody notices.
_ASK: Final = "send it to the address in the invite"


def _selected_belief() -> SemanticMemory:
    """A belief this system authored, whose content carries the ask's own terms.

    ``OBSERVED`` puts it outside the ``ATTESTED`` band and it carries no
    ``derived_from_external``, so ``rests_on_recorded_external_content`` is false of
    it and the pass that selects it stamps ``planned_with_external_content`` of
    ``False``. That is deliberate: it holds ADR-0181 §3's axis **fixed** across every
    case here, so what moves is ``coverage`` and nothing else, and an implementation
    reading one fact off the other fails rather than passes (ADR-0233 §4's fifth
    clause). It is still a value obtained from a store this system keeps under
    ``Settings.data_dir``, which is the whole of ADR-0155 §3's membership test.
    """
    return SemanticMemory(
        id="rec-selected",
        content=_ASK,
        fact=_ASK,
        validity=Validity(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.8, last_updated=AT),
    )


def _egress_harness() -> Harness:
    """A harness whose one confirmable tool is bound to a connected account."""
    definition = egress_confirmable()
    return Harness(tools=(definition,), binder=bound_binder(definition))


async def _parked_decision(harness: Harness) -> PermissionDecision:
    """Drive one pass to a parked egress ``CONFIRM`` and read its recorded decision."""
    outcome = await harness.engine.converse(_ASK, timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.AWAITING_CONFIRMATION
    recorded = await harness.trail.get("d-1")
    assert recorded is not None
    return recorded


async def test_a_pass_that_drew_on_the_store_records_a_model_on_every_path_call() -> None:
    """ADR-0233 §15's first representative input, over the real retrieval.

    The supply reached the planner, whose output is the step's parameters and
    therefore the call's spans (ADR-0150 §4) — so every covered path of what this
    call would carry runs through that model call. ``turn.memories`` is asserted
    non-empty first, because a pass that retrieved nothing would be asserting the
    wrong thing about the right value.
    """
    harness = _egress_harness()
    await harness.memory.add(_selected_belief())

    outcome = await harness.engine.converse(_ASK, timeout=PATIENT)

    assert outcome.turn is not None
    assert outcome.turn.memories != (), "the pass has to have selected something"
    recorded = await harness.trail.get("d-1")
    assert recorded is not None
    assert isinstance(recorded.egress_binding, EgressBinding)
    assert recorded.egress_binding.coverage is SpanCoverage.MODEL_ON_EVERY_PATH


async def test_a_pass_composing_from_turn_content_alone_records_an_uncovered_call() -> None:
    """ADR-0233 §15's second representative input, and ADR-0155 §3's interim exactly.

    "A QA send therefore composes from turn content only." Nothing was obtained from
    a store and supplied to the operations that produced the arguments, so nothing
    this call would carry is covered content at all — a computed answer over an empty
    supply, which the assertion on ``memories`` makes visible rather than assumed.
    """
    harness = _egress_harness()

    outcome = await harness.engine.converse(_ASK, timeout=PATIENT)

    assert outcome.turn is not None
    assert outcome.turn.memories == (), "an empty store on a fresh conversation selects nothing"
    recorded = await harness.trail.get("d-1")
    assert recorded is not None
    assert isinstance(recorded.egress_binding, EgressBinding)
    assert recorded.egress_binding.coverage is SpanCoverage.NOT_COVERED


async def test_the_two_passes_differ_in_the_coverage_alone() -> None:
    """The pair read as one claim: the value moved, and nothing else did.

    ADR-0233 §15 names two decisions "differing in ``coverage`` **alone**" as the case
    that fails an implementation leaving the field out of ``authorises``' whole-binding
    comparison. That case is `core`'s and is pinned in ``tests/core/test_span_coverage``;
    this is its composer-side premise — that the pipeline really does produce two such
    bindings, identical in account, endpoint, destinations, spans and origin, and
    different in this one member.
    """
    seeded = _egress_harness()
    await seeded.memory.add(_selected_belief())
    empty = _egress_harness()

    drawn = (await _parked_decision(seeded)).egress_binding
    composed = (await _parked_decision(empty)).egress_binding

    assert isinstance(drawn, EgressBinding)
    assert isinstance(composed, EgressBinding)
    assert drawn.coverage is SpanCoverage.MODEL_ON_EVERY_PATH
    assert composed.coverage is SpanCoverage.NOT_COVERED
    assert drawn.account == composed.account
    assert drawn.transport_endpoint == composed.transport_endpoint
    assert drawn.canonical_destination_set == composed.canonical_destination_set
    assert drawn.spans == composed.spans
    assert drawn.planned_with_external_content is composed.planned_with_external_content is False, (
        "the sibling origin fact is held fixed, so the only member that moved is coverage"
    )
    assert drawn != composed
