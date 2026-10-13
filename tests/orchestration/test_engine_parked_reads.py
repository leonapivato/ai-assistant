"""ADR-0244's parked read, driven through the **engine** (§19).

The representative-input tests §18's last clause and §19 name, at the seams they are
about. §18 is explicit that four of this decision's rulings are **deliberately not**
suite clauses — "a generic conformance suite cannot see a wiring or the absence of a
call" — and names the three that this module is the site for: that **no model call
precedes a dispatch**, that **the value sent is the park's own ``parameters``**, and the
arms §19 lists. ``tests/permissions/parked_reads_contract.py`` carries Arm 9, the
store's own suite.

**Driven through the engine rather than through the servicing site**, because every arm
here is about something only the pipeline above that site has: the question is assembled
at the capture point, the answer runs through ``resume``, the continuation is a turn, and
``grantable_decisions`` is an engine operation. A loop-level case can reach none of them.

**The pipeline is the real one.** The production ``ThresholdActionPolicy`` over the same
recipient-grant store the engine's own act writes to, the real
:class:`~ai_assistant.orchestration.reads.SearchServicer`, the canonical
``FakeParkedReads`` wired as **one instance** into that servicer and the engine alike
(ADR-0244 §18's Lane 2 obligation, held here by the case), and the capture point that is
"the single place a ``TurnOutcome`` is built".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import AT, Harness
from test_engine_read_envelope import _AskingPlanner
from test_loop_search import (
    _CONFIGURED_SEARCH,
    _DEADLINE,
    _binder,
    _CostedSearcher,
    _search,
)

from ai_assistant.core.errors import (
    UnknownContinuationError,
)
from ai_assistant.core.types import (
    ContinuationToken,
    MemorySource,
    Placement,
    Provenance,
    SemanticMemory,
)
from ai_assistant.orchestration.reads import SearchServicer, admitted_fourth_group
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    FAKE_WEB_SEARCH,
    FakeAuditTrail,
    FakeEgressBinder,
    FakeMemoryStore,
    FakeParkedReads,
    FakeQueryComposer,
    FakeRecipientGrantStore,
    FakeWebSearcher,
)

if TYPE_CHECKING:
    from ai_assistant.orchestration.composing import ComposingStage

_ASKED: Final = "what has changed since we last spoke"

#: ADR-0244 §3's lifetime for these cases. Long enough that nothing expires by accident;
#: the expiry arms move the **clock** rather than shortening this, because ADR-0059 §1's
#: comparison is against the clock's reading and a test advances it rather than waits.
_TTL: Final = timedelta(hours=24)


@dataclass
class _Wired:
    """The engine and the stores it shares with the servicing site.

    **One trail, one recipient-grant store and one parked-read store**, which is
    ``app/composition.py``'s own discipline and what every arm here is stated over: the
    ruling the search records is the row the park names, and the park the servicing wrote
    is the one ``resume`` settles. A harness holding two of any of them can seed a state
    and never *reach* it.
    """

    engine: Any
    trail: FakeAuditTrail
    parks: FakeParkedReads
    searcher: FakeWebSearcher
    composer: FakeQueryComposer
    memory: FakeMemoryStore
    clock: _Clock
    #: The seam the servicing bound through, kept so a case can perform a **provisioning
    #: act on it** between the park and the answer — which is what ADR-0247 §12's Arms F
    #: and F' are driven by, and the one thing a re-derived binding is compared against.
    binder: FakeEgressBinder


class _Clock:
    """An injected clock a case advances rather than waits on (ADR-0009, ADR-0059 §1)."""

    def __init__(self) -> None:
        self.now = AT

    def __call__(self) -> Any:
        return self.now

    def advance(self, by: timedelta) -> None:
        """Move the reading forward, so a deadline passes without a case sleeping."""
        self.now += by


def _wired(
    *,
    composing: ComposingStage | None = None,
    configured: bool = False,
) -> _Wired:
    """The real pipeline over shared stores, with a parked-read store wired.

    Nothing is seeded: no recipient grant, so the production policy rules ``CONFIRM`` on
    the first search — which is the state #2221 records on the owner's own store and the
    one every arm below starts from.

    ``configured`` is ADR-0247's deployment, and it is a **different ground for the same
    park**: the policy is handed the destination this deployment is configured with, so
    §3's two retired floors no longer draw the ``CONFIRM``, and what draws it instead is
    the per-call cost ADR-0236 §4 leaves ``UNKNOWN`` where the operator declared no
    figure — which is exactly the shape §12's Arm E names. The searcher is then the bare
    fake and the seam holds its **uncosted** declaration, because a binding seam holding
    a different declaration refuses the request before any ruling is sought.
    """
    decisions = count(1)
    clock = _Clock()
    grants = FakeRecipientGrantStore(now=clock)
    trail = FakeAuditTrail(recipient_grants=grants)
    searcher = FakeWebSearcher(results=("a result about the bell tower",))
    composer = FakeQueryComposer()
    store = FakeParkedReads()
    memory = FakeMemoryStore(now=clock)
    binder = _binder(definition=FAKE_WEB_SEARCH) if configured else _binder()
    harness = Harness(
        memory=memory,
        # **One asking round** (ADR-0251 §4). ADR-0228 §2(e) used to end this turn
        # after the first servicing, because a search that parked admitted no record;
        # §4 dissolves (e), so a planner that went on asking would park, be handed
        # `REFUSED` (§2), and ask again — a second park attempt on a conversation
        # ADR-0244 §3 allows one open park in. Every case here is about the **one**
        # lookup that parked, so the planner says one round and settles.
        planner=_AskingPlanner(_search(), rounds=1),
        composing=composing,
        now=clock,
        search=SearchServicer(
            composer=composer,
            searcher=searcher if configured else _CostedSearcher(searcher),
            binder=binder,
            policy=ThresholdActionPolicy(
                grants=grants,
                configured_search=_CONFIGURED_SEARCH if configured else None,
            ),
            trail=trail,
            now=clock,
            # **A prefix of its own**, because the harness mints ``d-N`` for the answers
            # its own operations record and the trail is append-only.
            id_factory=lambda: f"search-d-{next(decisions)}",
            deadline=_DEADLINE,
            # ADR-0244 §18's one-instance obligation: the **same** object the engine
            # answers through, so the park this servicing writes is the park that
            # ``resume`` settles.
            parked_reads=store,
            parked_read_ttl=_TTL,
        ),
        parked_reads=store,
        trail=trail,
        recipient_grants=grants,
    )
    return _Wired(
        engine=harness.engine,
        trail=trail,
        parks=store,
        searcher=searcher,
        composer=composer,
        memory=memory,
        clock=clock,
        binder=binder,
    )


async def _parked(wired: _Wired) -> Any:
    """The one open park this deployment holds, read through the contract."""
    [held] = await wired.parks.outstanding()
    return held


# --- Arm 7: cancellation ------------------------------------------------------


async def test_an_unknown_token_is_refused_and_never_denied() -> None:
    """ADR-0244 §11, ADR-0084 §7: an unknown token raises, exactly as ``resume`` does.

    **Never a ``NOTHING_TO_CANCEL``**, which would tell a caller its question was already
    gone when in fact this engine never held it.
    """
    wired = _wired()

    with pytest.raises(UnknownContinuationError):
        await wired.engine.cancel_read(ContinuationToken(handle="never-minted"))


# --- what the continuation owes the turn it composes -------------------------


def test_the_resumed_fourth_group_is_bounded_and_deduplicated() -> None:
    """ADR-0244 §7: the minted records are admitted under ADR-0226 §6's budget of ten.

    "They are deduplicated and admitted under ADR-0226 §6's budget of ten", so an
    eleventh admits nothing — and the deduplication is over the **whole union**, which
    is the half a seen-set that never advances would fail: two records of one batch
    sharing an id would otherwise both enter the supply the reply is composed over.

    **Driven at the function that states the two rules rather than through the engine**,
    because a dispatch cannot reach either bound: ADR-0231 §5 caps
    ``Settings.search_max_results`` at three, so one approved read mints at most three
    records and neither an eleventh nor a repeated id is constructible through the seam.
    The rules are stated anyway — ADR-0244 §7 retains them by name — and this is the
    site where a rule stated for a bound no input reaches can still be checked. The
    engine-level case below asserts what the pipeline *can* show: that the union it
    composes over holds each record once.
    """
    held = (_minted("already-held"),)

    assert [
        record.id
        for record in admitted_fourth_group(tuple(_minted(f"r-{n}") for n in range(12)), held=held)
    ] == [f"r-{n}" for n in range(10)], "ADR-0226 §6's budget of ten, and no eleventh"
    assert admitted_fourth_group((_minted("already-held"),), held=held) == (), (
        "a record the supply already holds keeps its place there and consumes no slot"
    )
    assert [
        record.id for record in admitted_fourth_group((_minted("r-1"), _minted("r-1")), held=())
    ] == ["r-1"], "and the seen set advances, so one batch's duplicate enters once"


def test_a_record_the_supply_holds_is_one_it_holds_under_either_of_its_names() -> None:
    """#2364: ADR-0226 §7's sameness, in both directions, at the one function.

    §7 names no field: "A record the servicer returns that the supply already holds is
    deduplicated out", applying ADR-0158 §4's rule "for its reason" — what a prompt may
    not repeat — and naming the mischief as a servicer that would "render one record
    twice and spend two of the ten on it". Two cases reach that mischief by different
    routes and a test keyed on one field can only catch one of them.

    **The same words under a fresh id**, which is every minted record: its id "is minted
    for one turn … and resolves in no store" (ADR-0231 §16, ADR-0230 §10), so two
    servicings of one turn that are handed the same result mint two ids that can never
    match. The three instants a re-reading moves are stepped over with it, because a
    provider re-read declares a later one (ADR-0231 §10) for the same words.

    **The same id over moved words**, which is what a store that revised a record
    between two of a turn's reads hands back: ADR-0113 §5 gives "no cross-call read
    consistency of any kind", and ADR-0251 §7 quotes it for this case. Rendering both
    copies is the same mischief read from the other side.
    """
    held = _minted("already-held")
    twin = held.model_copy(
        update={
            "id": "minted-afresh",
            "provenance": held.provenance.model_copy(update={"last_updated": AT + timedelta(6)}),
        }
    )
    revised = held.model_copy(update={"content": "the same record, saying something else"})

    assert admitted_fourth_group((twin,), held=(held,)) == (), (
        "the same words under a fresh id and a later reading are a record the supply holds"
    )
    assert admitted_fourth_group((revised,), held=(held,)) == (), (
        "and so is a revision the store handed back under the id the supply holds it by"
    )
    assert [record.id for record in admitted_fourth_group((twin,), held=())] == ["minted-afresh"], (
        "while a supply holding neither name admits it, which is what keeps this a test"
    )


def _minted(record_id: str) -> SemanticMemory:
    """A record shaped as a search mints one, for the admission rules alone."""
    return SemanticMemory(
        id=record_id,
        content=f"a result under {record_id}",
        fact=f"a result under {record_id}",
        placement=Placement(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=AT),
    )
