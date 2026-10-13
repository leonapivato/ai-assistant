"""The held results: acting's part of the working episode, never saved (ADR-0308 §6).

Acting holds each result that carries outside text here, under the result id it mints
when it records the result, which the result's R label names (§6:1, ADR-0307 §5:1).
Digesting reads them, and of the stages it alone does (§6:5): planning never reads
outside text (ADR-0307 §9:2).

**Shared by two phase modules, and a phase module of neither.** No phase module imports
another (ADR-0309 §2:3), so the one shape acting writes and digesting reads lives here,
importing only ``core``. An import-linter contract keeps every other phase module from
importing it, so no stage but digesting can be handed a way to read what is held.

**Never saved** (§6:4, ADR-0282 §1:2). Nothing here is a ``core`` type, so no store and
no wire can take a held result; the holder is a plain object of the activation's working
episode and goes when the activation ends.

**As it arrived, or by id** (§6:2-§6:3). A result is held as its value came back from
the call, never copied into a record; a result of the assistant's own records, such as a
memory search, is held by the ids of its outside records instead, which its digest
fetches under ADR-0282 §2:4-§2:8.

**Offered again** (§6:6-§6:7). A follow-up names a held result, and acting offers it, as
held, to a digest answering the follow-up's question: :meth:`HeldResults.offer_again`
tells the step running digests of it under the follow-up's own round and decision, and
holds nothing again.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import FrozenJsonValue

__all__ = ["HeldResult", "HeldResults"]


@dataclass(frozen=True, slots=True)
class HeldResult:
    """One result carrying outside text, as acting holds it (ADR-0308 §6:1, §6:3).

    Attributes:
        result_id: The id acting minted for it, which its R label names.
        round_id: The planning round whose call brought it.
        decision_id: The id of the decision that allowed the call, which names that
            call alone within its round, so the step running digests beside acting can
            find the call's *looking for* as soon as the result is held (ADR-0308
            §4:2 to §4:3).
        content: The result as it arrived from the call, JSON ``null`` included;
            ``None`` where it is held by id.
        records: For a result of the assistant's own records, the ids of its outside
            records, which is all that is held of it (§6:2); ``None`` for a result
            held as it arrived.
    """

    result_id: str
    round_id: str
    decision_id: str
    content: FrozenJsonValue
    records: tuple[str, ...] | None = None


class HeldResults:
    """One activation's held results, written by acting and read by digesting.

    Acting holds each result as it records it; digesting reads one by its id. The
    optional ``on_hold`` is told of each result as it is held, so the step that runs
    acting and digesting side by side can start a result's digest as soon as acting
    records it (ADR-0308 §4:2, ADR-0309 §3:3).
    """

    def __init__(self, *, on_hold: Callable[[HeldResult], None] | None = None) -> None:
        """Start an empty holder.

        Args:
            on_hold: Told of each result as it is held, after it is held. What it
                raises reaches the call that held the result.
        """
        self._held: dict[str, HeldResult] = {}
        self._on_hold = on_hold

    def hold(self, held: HeldResult) -> None:
        """Hold ``held`` under its result id; acting alone calls this.

        Args:
            held: The result, under the id acting minted for it.

        Raises:
            ValueError: If a result is already held under that id: an id names one
                result for the whole activation.
        """
        if held.result_id in self._held:
            msg = "a result id names one result for the whole activation"
            raise ValueError(msg)
        self._held[held.result_id] = held
        if self._on_hold is not None:
            self._on_hold(held)

    def get(self, result_id: str) -> HeldResult | None:
        """The result held under ``result_id``, or ``None`` where nothing is held.

        Args:
            result_id: The id acting minted for the result.

        Returns:
            The held result, or ``None``.
        """
        return self._held.get(result_id)

    def offer_again(self, result_id: str, *, round_id: str, decision_id: str) -> HeldResult | None:
        """Offer the result held under ``result_id`` to a digest again; acting alone calls this.

        A follow-up's result is the result it names, as held (ADR-0308 §6:7): ``on_hold``
        is told of it under the follow-up's round and decision, so its digest answers
        the follow-up's question, and nothing is held again.

        Args:
            result_id: The id of the result the follow-up names.
            round_id: The planning round whose follow-up names it.
            decision_id: The id of the decision that allowed the follow-up.

        Returns:
            The result as offered, or ``None`` where nothing is held under that id.
        """
        held = self._held.get(result_id)
        if held is None:
            return None
        offered = replace(held, round_id=round_id, decision_id=decision_id)
        if self._on_hold is not None:
            self._on_hold(offered)
        return offered

    def __len__(self) -> int:
        """How many results are held."""
        return len(self._held)
