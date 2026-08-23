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

**It is a fact about a selection, and nothing more.** It is **not** a claim that
any argument, destination or span of the request was influenced by external
content, nor that any was not; no consumer, surface or ADR may state or imply that
it detects external content embedded in text whose recorded origin is not external
(ADR-0181 §2's second clause, inheriting ADR-0098 §5 and ADR-0106 §1 verbatim). A
``False`` says *no selected record carried the marker*, never *no external content
was involved*.

**Nothing a producer emits reaches it** (ADR-0181 §4's first clause). Whatever a
model, a tool, a tool declaration or a plan says about this fact is discarded
rather than merged: there is no code path here in which a producer's claim has an
effect, which is what makes the guarantee total rather than a rule someone has to
remember. Nor is it derived by inspecting an argument's value, its field, its
shape, or by matching it against anything the user wrote (ADR-0181 §4's second
clause, which is ADR-0146 §2's forbidden inference read on the second axis).

**A frozen dataclass in `orchestration` and not on the promoted surface**, for
:class:`~ai_assistant.orchestration.runner.StepDisposition`'s reason one module
over: it crosses no subsystem boundary. What *does* cross is the boolean it holds,
on :class:`~ai_assistant.core.types.CarriedProvenance`, which is where ADR-0181 §3
puts it — and it crosses as a member of the binding rather than beside it, so
:meth:`~ai_assistant.core.types.PermissionDecision.authorises` compares it with the
rest of the binding as one whole.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import rests_on_recorded_external_content

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import MemoryRecord


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
    """

    planned_with_external_content: bool

    @classmethod
    def over(cls, *selections: Iterable[MemoryRecord]) -> SelectionOrigin:
        """The disjunction of the predicate over **every** selection given.

        **Variadic because combining is the primitive, not an afterthought.**
        ADR-0181 §4's third clause states the rule that would otherwise be the
        laundering path: where a request's arguments were produced by more than one
        model call over more than one selection, the value is the disjunction over
        all of them, and no step of a plan clears a value an earlier step's
        selection set. A signature taking one selection invites the shape that
        breaks it — plan a step over tainted material, re-plan over clean material,
        stamp the binding from the last selection, and watch the fact clear. This
        one cannot express that: a caller adds a selection, and adding can only move
        the answer one way. "A warrant is never un-received, and neither is a
        selection."

        Args:
            *selections: Each selection of material this system put in front of a
                model on the way to the request, as the records it selected. Order
                is immaterial — the result is a disjunction — and a selection may
                overlap another. Called with **no** selections it answers
                :data:`NOTHING_EXTERNAL`, which is a caller stating in code that it
                selected nothing rather than defaulting into the permissive answer
                (ADR-0181 §3).

        Returns:
            What the selections together rest on.
        """
        return cls(
            planned_with_external_content=any(
                rests_on_recorded_external_content(record.provenance)
                for selection in selections
                for record in selection
            )
        )


#: What a caller with no selection in hand states, **deliberately** rather than by
#: default (ADR-0181 §3). Every construction site says which of the two it means,
#: which is the whole of what ``no default`` on the ``core`` field buys: a lane that
#: never wired a selection through cannot get the permissive answer for free.
NOTHING_EXTERNAL: Final = SelectionOrigin(planned_with_external_content=False)


__all__ = ["NOTHING_EXTERNAL", "SelectionOrigin"]
