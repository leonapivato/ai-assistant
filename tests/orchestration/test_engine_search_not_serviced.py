"""ADR-0242's explanation and ADR-0247's authority, driven through the **engine**.

``tests/orchestration/test_search_not_serviced.py`` drives the servicing site and the
loop; this module drives the pipeline **above** them — ``Engine.converse``, the real
``ComposingStage`` it forwards to, and the ``TurnOutcome`` it builds — because ADR-0242
§7's carrier and §9's field are two consumers of one computed member and a lane that
dropped either forwarding would leave every loop-level assertion passing while the user
lost the explanation.

**ADR-0247 §12's Arms A, B and J are here on the same ground**, because each is a
statement about a whole deployment rather than about one servicing: what a turn asks the
user, what the grant seam is consulted for, and what a trust store that cannot be read
decides. ADR-0242 §15's journeys through the trust act are **gone rather than moved** —
ADR-0247 §1 stops the servicing site consulting the store, so ``TRUST_MISSING`` has no
producer on a configured deployment (§6, #2252) and a journey that established trust to
make a search run has no subject. The member, its mapping and its statement all stay
ratified, and the mapping is still asserted over ``not_serviced`` directly.

The harness is ``test_engine``'s, because what these cases are about is the real
pipeline: the production ``ThresholdActionPolicy`` over the destination this deployment
is configured with, the real
:class:`~ai_assistant.orchestration.reads.SearchServicer`, the trust store the
composition root still wires into the ``trust-destinations`` surface, and the capture
point that is "the single place a ``TurnOutcome`` is built".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final, final

import structlog
from test_engine import AT, PATIENT, Harness
from test_engine_read_envelope import _AskingPlanner, _recorder
from test_loop_search import (
    _ACCOUNT,
    _CONFIGURED_SEARCH,
    _DEADLINE,
    _binder,
    _CostedSearcher,
    _search,
)

from ai_assistant.core.errors import InvalidDestinationTrustError
from ai_assistant.core.types import (
    PermissionOutcome,
    Role,
    SearchNotServiced,
    SpanCoverage,
)
from ai_assistant.orchestration.reads import SearchServicer
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeDestinationTrustStore,
    FakeMemoryStore,
    FakeQueryComposer,
    FakeRecipientGrantStore,
    FakeWebSearcher,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.orchestration.composing import ComposingStage
    from ai_assistant.testing import FakeModelProvider

_ASKED: Final = "what has changed since we last spoke"

#: A distinctive clause of ADR-0242 §7's ``AUTHORISATION_AWAITED`` fragment, quoted so
#: this module asserts the **fragment** reached the prompt rather than that two prompts
#: differ — which they also do for reasons ADR-0228 §10 owns.
_AWAITED_FRAGMENT: Final = "instead of making that lookup it was put to this person as a question"

#: One distinctive clause per ADR-0242 §7 fragment, for the arm that says a serviced turn
#: is told about no lookup at all. Written out rather than reached for through the
#: composing module's private table, because what is asserted is what the prompt says.
_FRAGMENTS: Final = (
    # ADR-0244 §12's ninth member, first in the enumeration and first here. The
    # discriminator against `_AWAITED_FRAGMENT` below is the whole point of the member:
    # that one says a question is on record for the user to answer *through an act*,
    # this one says a lookup is waiting on their answer — and neither says the lookup
    # produced nothing, which is the literal #2221 records as false.
    "waiting on an answer from this person before it can be made",
    "this installation does not make them at all",
    "no such lookup was made on this occasion",
    "a limit this installation is run under stood in the way",
    "the rules this installation is run under declined it",
    "is not one this person has chosen to have things composed for",
    _AWAITED_FRAGMENT,
    "it was stopped before it came back",
    "that lookup produced nothing this turn could use",
)


def _system_prompt(model: FakeModelProvider, ordinal: int = -1) -> str:
    """The system message the production stage assembled, from the fake's own record.

    ``ordinal`` picks which turn's prompt, defaulting to the **last** — a journey that
    performs an act between two turns composes twice through one stage, and what the arm
    is about is the turn after the act.
    """
    assert model.calls
    return next(one.content for one in model.calls[ordinal].messages if one.role is Role.SYSTEM)


@final
class _CountingGrants:
    """The grant store, wrapped so the policy's reads of it can be counted.

    ADR-0247 §12's Arm A asks for "the grant seam is consulted **zero** times, asserted
    over the seam and not over the ruling", because §2 puts route (c) *before* the seam:
    a policy that looked first and preferred the configuration afterwards passes every
    outcome assertion while making a ruling at the configured provider cite a grant.
    The engine's own establishing act still writes through the wrapped store, so the two
    halves of the journey stay over one set of rows.
    """

    def __init__(self, inner: FakeRecipientGrantStore) -> None:
        self.inner = inner
        self.reads = 0

    def __getattr__(self, name: str) -> Any:
        """Delegate every member this class does not name."""
        return getattr(self.inner, name)

    async def covering(self, request: Any) -> Any:
        """Count the read, then answer exactly as the store would."""
        self.reads += 1
        return await self.inner.covering(request)


@dataclass
class _Wired:
    """The engine, the stores it shares with the servicing site, and the searcher.

    **One trail, one recipient-grant store and one trust store**, which is
    ``app/composition.py``'s own discipline and what ADR-0242 §15's journeys are stated
    over: the ruling the search records is the row ``grantable_decisions`` offers, the
    grant the engine establishes is the one the policy consults on the next search, and
    the trust store is the one the ``trust-destinations`` surface writes. A harness
    holding two of any of them can seed authority and never *perform* it, which is the
    shape round 2 of that lane's review found.

    **The trust store is here and is not read by the search any more** (ADR-0247 §1),
    which is what Arm J below is about: it stays wired because the act and its listing
    stay ratified for every other destination.
    """

    engine: Any
    trail: FakeAuditTrail
    grants: _CountingGrants
    trust: FakeDestinationTrustStore
    searcher: FakeWebSearcher


def _wired(*, composing: ComposingStage | None = None, trust: Any = None) -> _Wired:
    """The real pipeline over shared stores, with nothing seeded.

    That empty state is production's: **no grant and no trust record**, which is the
    premise ADR-0247 §12's Arms A and B are stated over — a deployment whose searches are
    authorised by its own configuration and by nothing a user has recorded.

    **The planner asks for a search on both of a turn's calls**, which is ADR-0231 §12's
    own shape and what lets one ``converse`` reach both a servicing that yields and one
    that is refused: once a minted record is in the turn's supply, the binding of any
    later request in that turn carries ``planned_with_external_content``.
    """
    decisions = count(1)
    # The harness's own instant, so a grant established at AT is live when the next
    # ruling is taken at AT — ADR-0193 §6 refuses an ALLOW sourced from a grant
    # that was not live when the ruling was made, and the trail checks it independently.
    grants = _CountingGrants(FakeRecipientGrantStore(now=lambda: AT))
    trail = FakeAuditTrail(recipient_grants=grants.inner)
    trust = FakeDestinationTrustStore() if trust is None else trust
    searcher = FakeWebSearcher(results=("a result",))
    harness = Harness(
        memory=FakeMemoryStore(now=lambda: AT),
        planner=_AskingPlanner(_search()),
        composing=composing,
        search=SearchServicer(
            composer=FakeQueryComposer(),
            searcher=_CostedSearcher(searcher),
            binder=_binder(),
            # The production policy over the **same** store the engine's establishing act
            # writes to, so a grant the user performs is one the next ruling consults —
            # ADR-0193 §1's narrow face, satisfied by the store structurally.
            #
            # **And over the destination this deployment is configured with**, which is
            # what `app/composition.py` now hands the one policy it builds (ADR-0247 §2,
            # §11's lane 1). It is not an alternative arrangement of the journeys below:
            # ADR-0247 §3 restates `_only_the_disclosure_floor`'s two limbs over *at the
            # configured provider*, so a closed-loop search reaches route (b) in no case
            # and the grant act these cases perform authorises no search by itself. What
            # the acts still decide here is `closed_loop` — ADR-0238 §5's trust read,
            # which lane 3 replaces with the registration fact — so every disposition
            # below is the one ADR-0242 §15 names, reached by the route ADR-0247 §2 now
            # gives it.
            policy=ThresholdActionPolicy(grants=grants, configured_search=_CONFIGURED_SEARCH),
            trail=trail,
            # The harness's own instant, so the ruling the search records and the answer
            # the engine writes when the grant act rides it share one timeline —
            # ADR-0235 §4 refuses a resolution decided before the confirmation it answers.
            now=lambda: AT,
            # **A prefix of its own**, because the harness mints ``d-N`` for the answers
            # its own operations record and the trail is append-only: two writers drawing
            # from one shape is a collision rather than a case.
            id_factory=lambda: f"search-d-{next(decisions)}",
            deadline=_DEADLINE,
            # ADR-0244 §18's lane seam: this module's cases are about ADR-0242 §8's
            # **unparked** rows, which is the state a servicing with no store is in —
            # §1's third clause, and the mapping this module already pins.
            parked_reads=None,
            parked_read_ttl=timedelta(hours=24),
        ),
        trail=trail,
        destination_trust=trust,
        recipient_grants=grants.inner,
    )
    return _Wired(engine=harness.engine, trail=trail, grants=grants, trust=trust, searcher=searcher)


async def _bindings(wired: _Wired) -> list[Any]:
    """Every egress binding the trail recorded, oldest first."""
    ruled = [row for row in await wired.engine.recent_decisions() if row.egress_binding is not None]
    return [row.egress_binding for row in sorted(ruled, key=lambda row: row.id)]


# --- ADR-0247 §12's engine half: the deployment's own search is authorised ----


async def test_a_search_planned_over_outside_content_is_allowed_with_no_grant_record() -> None:
    """ADR-0247 §12's **Arm A**, through the whole pipeline (lane 1 holds the policy half).

    "A turn that has read a local file and then searches, on a deployment whose
    ``RecipientGrants`` store is **empty** and whose ``DestinationTrustStore`` holds **no
    record**, binds ``closed_loop`` ``True``, draws an ``ALLOW`` on route (c) whose
    ``authorised_by`` is the binding's ``account.reference`` and whose
    ``authorised_subject`` is unset, is recorded by ``AuditTrail.record`` rather than
    refused, and asks the user nothing. **The grant seam is consulted zero times**,
    asserted over the seam and not over the ruling."

    **The outside content reaches the second search by the route a real turn has**: the
    planner asks for a search on both of this turn's calls (ADR-0231 §12), so the first
    servicing's minted record is in the turn's supply when the second is bound — which is
    what puts ``planned_with_external_content`` on it. A file read would put it there
    too and is the ADR's own illustration; what the arm turns on is the fact, and this
    module's engine composes a real turn to produce it rather than arranging one.
    """
    wired = _wired()

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.search_not_serviced is None, "the user is told about no lookup"
    assert await wired.engine.pending_confirmations() == (), "and is asked nothing"
    assert len(wired.searcher.searched) == 2, "both servicings reached the provider"
    first, second = await _bindings(wired)
    assert first.closed_loop is True
    assert second.closed_loop is True
    assert second.planned_with_external_content is True, (
        "the first servicing's record is in the turn's supply when the second is bound"
    )
    rulings = [row for row in await wired.engine.recent_decisions() if row.egress_binding]
    assert {row.ruling.outcome for row in rulings} == {PermissionOutcome.ALLOW}
    assert {row.ruling.authorised_by for row in rulings} == {_ACCOUNT.reference}, (
        "route (c) points at the binding's own connection reference"
    )
    assert {row.ruling.authorised_subject for row in rulings} == {None}
    assert list(await wired.grants.standing()) == [], "no grant was established by any of this"
    assert wired.grants.reads == 0, "and the seam was never consulted (ADR-0247 §2)"
    assert await wired.trust.live() == [], "nor was any trust record written"


async def test_a_query_composed_over_stored_records_takes_the_same_route() -> None:
    """ADR-0247 §12's **Arm B**, through the engine.

    "With the supply carrying memory records, so that the binding's ``coverage`` is
    ``MODEL_ON_EVERY_PATH``, the ruling is the same ``ALLOW``, which is the arm that
    asserts §3's **second** retirement rather than only its first." The second servicing
    of this turn composes over the record the first minted, so its coverage is the one
    ADR-0238 §7's second exception admits — and the coverage exception ADR-0233 §9 put
    over it is what §3 retires beside the lineage floor.

    A lane that retired only the lineage limb rules ``CONFIRM`` here and fails.
    """
    wired = _wired()

    await wired.engine.converse(_ASKED, timeout=PATIENT)

    first, second = await _bindings(wired)
    assert first.coverage is SpanCoverage.NOT_COVERED, "the first composed over the utterance"
    assert second.coverage is SpanCoverage.MODEL_ON_EVERY_PATH, (
        "and the second over the record the first minted (ADR-0238 §2)"
    )
    assert second.planned_with_external_content is True
    rulings = [row for row in await wired.engine.recent_decisions() if row.egress_binding]
    assert {row.ruling.outcome for row in rulings} == {PermissionOutcome.ALLOW}
    assert wired.grants.reads == 0


async def test_a_trust_store_that_raises_on_every_call_decides_nothing_here() -> None:
    """ADR-0247 §12's **Arm J**, over the store this deployment still holds.

    "With the ``DestinationTrustStore`` raising on every call, a search at the configured
    provider is unaffected, because §1 stops consulting it — which is the arm that
    asserts the read was **removed** rather than merely made to answer ``USER_CHOSEN``."

    The store is wired exactly where ``app/composition.py`` still wires it, into the
    ``trust-destinations`` surface, and its reads are counted beside the outcome: a lane
    that kept a read and swallowed the fault would leave both searches serviced and this
    count above zero.
    """
    trust = _RaisingTrustStore()
    wired = _wired(trust=trust)

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.search_not_serviced is None
    assert len(wired.searcher.searched) == 2, "both servicings reached the provider"
    assert [binding.closed_loop for binding in await _bindings(wired)] == [True, True]
    assert trust.calls == 0, "the servicing site asked it nothing at all"


@final
class _RaisingTrustStore:
    """A ``DestinationTrustStore`` whose every member raises (ADR-0247 §12 Arm J)."""

    def __init__(self) -> None:
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        """Raise from every member, counting the attempt."""

        async def _raise(*_: Any, **__: Any) -> Any:
            self.calls += 1
            msg = "this store cannot be read"
            raise InvalidDestinationTrustError(msg)

        return _raise


# --- §15's journeys, over the state ADR-0247 leaves them in -------------------


async def test_the_positive_path_services_both_its_searches_and_parks_nothing() -> None:
    """§15 Arm 1's assertion set, over the two servicings one ``converse`` performs.

    "A connection reference and origin configured; a first search recorded
    ``RULING_CONFIRM``; the recipient grant established through
    ``establish_recipient_grant``; trust established through
    ``establish_destination_trust`` over the same decision" — all four performed above —
    "then … each service a search, the second composed over records rather than the
    utterance alone. Asserts: the audit's ``servicings[].disposition`` is ``None`` on
    both, no confirmation is parked, and ``TurnOutcome.search_not_serviced`` is ``None``
    on both."

    Every one of those assertions is made here. What carries them is the **turn's two
    servicings** rather than two turns of the conversation, and the next case records
    why — with an issue against the ADR rather than a silent substitution.
    """
    wired = _wired()

    with structlog.testing.capture_logs() as captured:
        outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    servicings = [row for event in _audits(captured) for row in event["servicings"]]
    assert [row["disposition"] for row in servicings] == [None, None]
    assert [row["supplied"] for row in servicings] == [0, 1], (
        "§15 Arm 1: the second is composed over **records** rather than the utterance "
        "alone, which is ADR-0238 §2's supply widening on a `USER_CHOSEN` destination"
    )
    assert outcome.search_not_serviced is None
    assert outcome.step is None, "no confirmation is parked: this plan drove no step"
    assert await wired.engine.pending_confirmations() == ()


async def test_two_turns_of_one_conversation_each_service_a_search() -> None:
    """§15 Arm 1's cross-turn half, and ADR-0238 §15 Arm 1b through the whole pipeline.

    ADR-0242 §15 Arm 1: "**two turns of one conversation each service a search**, the
    second composed over records rather than the utterance alone", asserting
    ``search_not_serviced`` is ``None`` on both. ADR-0238 §15 Arm 1b states the same
    turn's ruling in its own terms — "A later turn of the same conversation, whose supply
    carries the stamped episode and no minted record of any earlier turn … **rules
    ``ALLOW`` on route (b)** with the binding carrying both
    ``planned_with_external_content`` **and** ``closed_loop`` true" — and ADR-0238 §2 is
    what makes that coherent: "**What a later turn has instead is the captured episode**
    … That is what resolves *find more about that* across turns."

    **This is the arm the servicing seam cannot make**, and why it is written here as
    well as in ``test_closed_loop.py``: nothing is arranged about the second turn's tail
    or about the conversation's stored flag. The first turn searches, is captured with
    the episode ADR-0223 §1 stamps, and folds its own observation onto the record; the
    second turn is an ordinary ``converse`` continuation that finds that episode in front
    of it. It was written as a strict ``xfail`` against #2205 and passes now that
    ``SearchFooting.clean`` admits ADR-0238 §2's first population.
    """
    wired = _wired()
    first = await wired.engine.converse(_ASKED, timeout=PATIENT)

    second = await wired.engine.converse(
        _ASKED, timeout=PATIENT, conversation_id=first.conversation_id
    )

    assert first.search_not_serviced is None
    assert second.search_not_serviced is None
    assert await wired.engine.pending_confirmations() == (), "Arm 1b asks the user nothing"
    ruled = [row for row in await wired.engine.recent_decisions() if row.egress_binding is not None]
    latest = max(ruled, key=lambda row: row.id)
    assert latest.egress_binding is not None
    assert latest.ruling.outcome is PermissionOutcome.ALLOW, "Arm 1b: recorded, not refused"
    assert latest.egress_binding.planned_with_external_content is True
    assert latest.egress_binding.closed_loop is True, "ADR-0238 §15 Arm 1b, on a real turn"


def _audits(captured: Sequence[Any]) -> list[Any]:
    """Every ``turn_read_request`` event in ``captured``, in the order it was written."""
    return [event for event in captured if event["event"] == "turn_read_request"]


async def test_a_turn_that_serviced_every_search_is_told_about_no_lookup_at_all() -> None:
    """§6, §15 Arm 1: the prompt on a turn carrying no member says nothing about one.

    Asserted over the whole vocabulary rather than over one member, so a lane that made
    the carrier unconditional would fail here whichever member it reached for. The
    byte-identity half of §6 is asserted at the loop, where two composes over *one* turn
    can be compared.
    """
    composing, model = _recorder()
    wired = _wired(composing=composing)

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.search_not_serviced is None
    prompt = _system_prompt(model)
    for fragment in _FRAGMENTS:
        assert fragment not in prompt


def test_the_quoted_fragments_are_the_ones_the_composing_stage_holds() -> None:
    """The clauses above are quotations, and this is what keeps them quotations.

    ADR-0242 §13 fixes the fragments as **literals, one per member**, so a lane editing
    one must edit the arm that reads it too — and a lane adding a member finds this arm
    rather than a prompt with nothing in it. ADR-0244 §12 is the lane that found it: the
    count is read off the vocabulary rather than written out, so the assertion is that
    the table and the enumeration **agree**, which is the property §13 is about.
    """
    from ai_assistant.orchestration import composing  # noqa: PLC0415 — one arm's subject

    written = composing._SEARCH_NOT_SERVICED_PROMPTS

    assert len(written) == len(SearchNotServiced) == len(_FRAGMENTS)
    for quoted in _FRAGMENTS:
        assert sum(quoted in text for text in written.values()) == 1, quoted
