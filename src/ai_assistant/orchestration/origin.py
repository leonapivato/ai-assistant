"""What a turn's selections rest on, held as far as the step that emits an egress call.

ADR-0181 §2 rules that the one origin fact recordable at the egress seam is a
property of the **call**: whether the material this system *selected* into the
model call whose output produced the call's arguments included any record for
which :func:`~ai_assistant.core.types.rests_on_recorded_external_content` is true.
ADR-0181 §4 puts computing it on the component that made the selection, which is
this package: `orchestration` chooses which records go in front of the model,
holds them as data it fetched, and evaluates a ratified predicate over them
without asking the model anything. That is a fact about an act this system
performed, not an inference about how a model produced an argument — the shape
ADR-0154 §4's second clause demands.

**Two facts, one selection set, computed together** (ADR-0233 §5). ADR-0233 §4
puts a second call-level fact on the same binding: ``coverage``, which of
ADR-0155 §3's two prohibitions governs what the call would carry. ADR-0233 §5
puts computing it on "the component that **composed the call's arguments**, from
the membership and path character of what it supplied to the operations that
produced them" — the same component, over the same supply, on the same pass. So
it is computed here, in :meth:`SelectionOrigin.over`, beside the fact it rides
with: ADR-0181 §3's pattern and ADR-0223 §1's rule that one pass computes a fact
once and threads it, so two consumers cannot hold two answers to one question.
The two facts are **not** functions of each other and neither is read off the
other (ADR-0233 §4's fifth clause): ``planned_with_external_content`` is a
disjunction of a *predicate* over the selected records, and ``coverage`` is
decided by whether anything was selected from a store at all.

**It is a fact about a selection, and nothing more.** It is **not** a claim that
any argument, destination or span of the request was influenced by external
content, nor that any was not; no consumer, surface or ADR may state or imply that
it detects external content embedded in text whose recorded origin is not external
(ADR-0181 §2's second clause, inheriting ADR-0098 §5 and ADR-0106 §1 verbatim). A
``False`` says *no selected record carried the marker*, never *no external content
was involved*.

**Nothing a producer emits reaches either fact** (ADR-0181 §4's first clause,
ADR-0233 §5's first clause). Whatever a model, a tool, a tool declaration or a
plan says about them is discarded rather than merged: there is no code path here
in which a producer's claim has an effect, which is what makes the guarantee total
rather than a rule someone has to remember. Nor is either derived by inspecting an
argument's value, its field, its shape, or by matching it against anything the user
wrote (ADR-0181 §4's second clause and ADR-0233 §5's second clause, which are
ADR-0146 §2's forbidden inference read on two axes).

**A frozen dataclass in `orchestration` and not on the promoted surface**, for
:class:`~ai_assistant.orchestration.runner.StepDisposition`'s reason one module
over: it crosses no subsystem boundary. What *does* cross are the two values it
holds, on :class:`~ai_assistant.core.types.CarriedProvenance`, which is where
ADR-0181 §3 and ADR-0233 §4 put them — and they cross as members of the binding
rather than beside it, so
:meth:`~ai_assistant.core.types.PermissionDecision.authorises` compares them with
the rest of the binding as one whole.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import SpanCoverage, rests_on_recorded_external_content

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import MemoryRecord


#: ADR-0233 §4's third clause, as data: the total order ``NOT_COVERED <
#: MODEL_ON_EVERY_PATH < PATH_WITHOUT_MODEL`` under which a value combining several
#: states takes the **strongest** of them. Written here rather than on the enum
#: because ADR-0233 §4 gives :class:`~ai_assistant.core.types.SpanCoverage` exactly
#: three members and no ordering, and because the order is a rule about *combining*
#: — which is this module's job, not the type's.
_STRENGTH: Final = (
    SpanCoverage.NOT_COVERED,
    SpanCoverage.MODEL_ON_EVERY_PATH,
    SpanCoverage.PATH_WITHOUT_MODEL,
)


def _strongest(states: Iterable[SpanCoverage]) -> SpanCoverage:
    """The strongest of ``states`` under ADR-0233 §4's order, ``NOT_COVERED`` if none.

    **The fold is what makes the monotonicity structural rather than remembered**
    (ADR-0233 §5's third clause, which is ADR-0106 §4's rule read on this axis).
    Combining can only move the answer up the order, so no selection added to a
    computation weakens what an earlier one contributed and there is no expressible
    shape in which "re-plan over clean material and watch the fact clear" is
    available to a caller.

    Args:
        states: One state per supply the value is being computed over.

    Returns:
        The state ADR-0155 §3's most restrictive reaching clause gives.
    """
    return max(states, key=_STRENGTH.index, default=SpanCoverage.NOT_COVERED)


def _coverage_of(selection: tuple[MemoryRecord, ...]) -> SpanCoverage:
    """What one selection makes of the arguments the model composed over it.

    ADR-0155 §3's first clause defines covered content as "a value any component
    obtained from a store this system keeps under ``Settings.data_dir``" and the
    output of any operation supplied with such a value. Every record in a selection
    is exactly that — ``orchestration`` obtained it from this system's own stores,
    whatever the content itself once derived from — so a **non-empty** selection is
    covered material supplied to the model call whose output composed this request's
    arguments.

    **Every covered path of those arguments therefore contains that model call**,
    which is ADR-0155 §3's third clause's subject and ADR-0233 §4's
    ``MODEL_ON_EVERY_PATH``. ADR-0155's own Consequences state the same derivation
    in the other direction: "once recalled records are supplied to the planner's
    model call, its output is covered content all of whose covered paths run through
    that call". This package introduces no store value into an argument by any other
    route: the arguments of a step are ``PlanStep.parameters``, which are the
    planner's own output, and ADR-0155 §3's prose already records that the two reads
    the pipeline performs on the way to a send "introduce nothing".

    **An empty selection is ``NOT_COVERED`` as a computed answer, not a default.**
    Nothing was obtained from a store and supplied to the operations that produced
    the arguments, so nothing the call would carry is covered content at all — which
    is what ADR-0155 §3's interim leaves: "a QA send therefore composes from turn
    content only".

    **``PATH_WITHOUT_MODEL`` is not reachable from here, and that is a statement
    about this component rather than about the type.** It is the state of a call
    carrying a value some covered path of which contains no model call, and this
    component supplies the model call every one of its covered paths runs through.
    A component that did place a store value into an argument directly would owe
    that value; ADR-0233 §6 refuses the resulting binding at construction.

    Args:
        selection: One selection of material this system put in front of a model on
            the way to the request.

    Returns:
        The state ADR-0155 §3's first clause gives that supply.
    """
    return SpanCoverage.MODEL_ON_EVERY_PATH if selection else SpanCoverage.NOT_COVERED


@dataclass(frozen=True, slots=True)
class SelectionOrigin:
    """What the material selected into a request's model calls rests on (ADR-0181 §2).

    Attributes:
        planned_with_external_content: Whether **any** selection this value was
            computed over contained a record satisfying
            :func:`~ai_assistant.core.types.rests_on_recorded_external_content`.
            This is the value stamped onto
            :class:`~ai_assistant.core.types.CarriedProvenance` before the request
            reaches ``EgressBinder.bind``, and carried from there onto the binding
            the policy rules over.
        coverage: Which of ADR-0155 §3's two prohibitions governs what a call
            composed over these selections would carry (ADR-0233 §4). Stamped onto
            the same carrier, beside the boolean and never derived from it, and
            carried onto the same binding — where ADR-0233 §6 refuses
            ``PATH_WITHOUT_MODEL`` at construction and ADR-0233 §9 makes
            ``MODEL_ON_EVERY_PATH`` approvable only under its four conditions.
    """

    planned_with_external_content: bool
    coverage: SpanCoverage

    @classmethod
    def over(cls, *selections: Iterable[MemoryRecord]) -> SelectionOrigin:
        """Both facts over **every** selection given: a disjunction, and a strongest.

        **Variadic because combining is the primitive, not an afterthought.**
        ADR-0181 §4's third clause states the rule that would otherwise be the
        laundering path: where a request's arguments were produced by more than one
        model call over more than one selection, the value is the disjunction over
        all of them, and no step of a plan clears a value an earlier step's
        selection set. ADR-0233 §5's third clause states the identical rule for
        ``coverage`` — "the value is the strongest of their states under §4's
        order", and "no later step of a plan weakens a value an earlier one
        recorded". A signature taking one selection invites the shape that breaks
        both: plan a step over tainted material, re-plan over clean material, stamp
        the binding from the last selection, and watch the facts clear. This one
        cannot express that — a caller adds a selection, and adding can only move
        either answer one way. "A warrant is never un-received, and neither is a
        selection."

        **Each selection is read once, into a tuple, before either fact is
        computed.** Two folds over one caller-supplied iterable would leave a
        generator exhausted by the first and silently clean for the second, which is
        the permissive answer arriving by accident at exactly the field ADR-0233 §4
        gives no default.

        Args:
            *selections: Each selection of material this system put in front of a
                model on the way to the request, as the records it selected. Order
                is immaterial — one result is a disjunction and the other a maximum
                — and a selection may overlap another. Called with **no** selections
                it answers :data:`NOTHING_EXTERNAL`, which is a caller stating in
                code that it selected nothing rather than defaulting into the
                permissive answer (ADR-0181 §3, ADR-0233 §4's no-default clause).

        Returns:
            What the selections together rest on, and what they make of the call.
        """
        made = tuple(tuple(selection) for selection in selections)
        return cls(
            planned_with_external_content=any(
                rests_on_recorded_external_content(record.provenance)
                for selection in made
                for record in selection
            ),
            coverage=_strongest(_coverage_of(selection) for selection in made),
        )


#: What a caller with no selection in hand states, **deliberately** rather than by
#: default (ADR-0181 §3, ADR-0233 §4). Every construction site says which of the two
#: it means, which is the whole of what ``no default`` on the two ``core`` fields
#: buys: a lane that never wired a selection through cannot get the permissive answer
#: for free. Built by calling :meth:`SelectionOrigin.over` with nothing rather than by
#: restating its answer, so the constant and the computation cannot come apart — the
#: name is ADR-0181's and now under-describes what the value says, because it states
#: both of a caller's facts: nothing external was selected, **and** nothing was
#: obtained from a store to be covered by anything.
NOTHING_EXTERNAL: Final = SelectionOrigin.over()


__all__ = ["NOTHING_EXTERNAL", "SelectionOrigin"]
