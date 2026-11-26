"""ADR-0383 §9:3's shared obligation, in the shape every bound store's suite reuses.

**The obligation.** For every read member of a Protocol ADR-0383 §7:1 names, the answer
of the store bound to a sight equals the answer of the same store holding only the
records that sight sees, totals, pages and "not found" included (§7:2, §8:1, §8:2). A
store that leaks fails it.

**How a suite proves it.** Build two stores of one implementation, both empty, and
write the same history into each through the unbound store: the same records, in the
same order, by the same doors. Then delete from the second every record the sight does
not see, by the one predicate (:meth:`~ai_assistant.core.types.Sight.withheld`). The
second is then *the same store holding only what the sight sees*, down to every
store-wide figure that counts writes (§8:5): a number, a revision or a key issued is
never issued again, so the records it keeps carry exactly the values they carry in the
first. Bind the first to the sight, in the withholding mode, and ask both every call
in a battery covering each read member: :func:`assert_answers_alike` compares the
outcomes, a raised error by its class.

Each conformance suite owns its history and its battery; this module owns the
comparison and the sights every suite proves, so the seven bound stores are held to one
set (B6 the memory store; B7 the other five and the memory writer).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import AssistantError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    AuthorityKind,
    InputSender,
    RecordHome,
    Sight,
    Sureness,
    WorkAuthority,
    WorkFacts,
    WorkFor,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

#: The activation whose work's sights are proved: a suite's history records this
#: activation's own records (its episode, its effects, the approvals it asked), so the
#: §7:4 half of the obligation is reached.
OWN_ACTIVATION: Final = "own"

_OWNER = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)
_UNIDENTIFIED = InputSender(person=None, level=Sureness.NONE)
_FOR_THE_OWNER = WorkFor.for_person(OWNER_PERSON_ID)


def _facts(
    authority: WorkAuthority, level: Sureness, for_whom: WorkFor = _FOR_THE_OWNER
) -> WorkFacts:
    return WorkFacts(for_whom=for_whom, authority=authority, level=level)


#: The sights every bound store's suite proves its obligation under, by name. Each is
#: made by a ``core`` constructor from recorded facts, as ADR-0383 §6:10 has every
#: sight made, and together they reach every bound kind of §6:2 and each reason of
#: §11:2.
SIGHTS: Final[dict[str, Sight]] = {
    # The owner's message: the owner's domain and the shared things (§6's first case).
    "owners-work": Sight.of_work(
        _facts(
            WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,)), Sureness.NORMAL
        ),
        (_OWNER,),
        activation=OWN_ACTIVATION,
    ),
    # An unidentified sender's: nothing but its own records (§6's second case, §7:4).
    "unidentified-senders-work": Sight.of_work(
        _facts(WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True), Sureness.NONE),
        (_UNIDENTIFIED,),
        activation=OWN_ACTIVATION,
    ),
    # A work for no one with no sender: the shared things alone.
    "work-for-no-one": Sight.of_work(
        _facts(WorkAuthority.none(), Sureness.NONE, WorkFor.no_one()),
        (),
        activation=OWN_ACTIVATION,
    ),
    # A producer for an episode that records no facts: an anyone bound alone (§6:7).
    "producer-with-no-facts": Sight.of_producer(None, ()),
    # A run tending the shared things, and one tending the owner's domain (§6:8).
    "run-over-the-shared-things": Sight.of_run(RecordHome.shared()),
    "run-over-the-owners-domain": Sight.of_run(RecordHome.owners()),
}


@dataclass(frozen=True)
class ReadCall[S]:
    """One call of a read member, made the same way on both stores.

    Attributes:
        name: What the call is, for the failure message: the member and its arguments.
        call: Makes the call on the store it is given and returns the answer.
    """

    name: str
    call: Callable[[S], Awaitable[object]]


async def _outcome[S](call: ReadCall[S], store: S) -> tuple[str, object]:
    """The call's answer, or the class of the error it raised (§8:2's "same outcome")."""
    try:
        return ("returned", await call.call(store))
    except (AssistantError, ValueError) as exc:
        return ("raised", type(exc))


async def assert_answers_alike[S](bound: S, holding_only: S, calls: Sequence[ReadCall[S]]) -> None:
    """Assert that every call answers alike on the two stores (ADR-0383 §9:3).

    Args:
        bound: The store bound to the sight, withholding.
        holding_only: The same store holding only the records the sight sees.
        calls: The battery: every read member, with the arguments that reach its
            totals, its pages, its order and "not found".
    """
    for call in calls:
        assert await _outcome(call, bound) == await _outcome(call, holding_only), (
            f"{call.name}: the bound store answered otherwise than the store holding "
            "only what its sight sees"
        )
