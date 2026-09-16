"""ADR-0260 §13's arm (h), turn-level: the field a surface reads, and the statement.

``test_forecast_servicing.py`` drives the servicing site and asserts what one servicing
**carries**; this module drives the pipeline **above** it — ``Engine.converse`` and the
``TurnOutcome`` it builds — because §10 puts the fold on ``TurnOutcome.forecast_not_read``
and ADR-0264 §6 assembles the statement at the capture point, and a lane that dropped
either forwarding would leave every servicing-level assertion passing while the user lost
both.

**The subject is production throughout**: the real ``Engine``, the real
:class:`~ai_assistant.orchestration.reads.ForecastServicer` over the real binding seam
and the real :class:`~ai_assistant.permissions.ThresholdActionPolicy`, with the canonical
fake standing only for the provider. ``forecast_servicing_harness.py`` records why the
binder is the real one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, final

import pytest
import structlog
from forecast_servicing_harness import (
    FORECAST_DECLARATION,
    NOW,
    binder,
    configured_forecast,
    forecaster,
    servicer,
)
from test_engine import AT, PATIENT, Harness
from test_engine_goal_association import _associating, _goal, _seed
from test_engine_read_envelope import _AskingPlanner
from test_forecast_servicing import _CapturingBinder
from test_loop_search import _CostedSearcher, _servicer

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    AssociationVerdict,
    EvidenceBasis,
    EvidenceStanding,
    ForecastNotRead,
    ForecastRefusal,
    OutboundDestination,
    OutboundReach,
    ReadAsk,
    ReadKind,
    ReadOutcomeKind,
    ReadRequest,
    RiskLevel,
    TimeWindow,
)
from ai_assistant.orchestration import reads
from ai_assistant.orchestration.reads import READ_AUDIT_EVENT, ForecastDisposition
from ai_assistant.permissions import ThresholdActionPolicy
from ai_assistant.testing import (
    DEFAULT_FORECAST_DAYS,
    FakeActionPolicy,
    FakeFetcher,
    FakeForecaster,
    FakeMemoryStore,
    FakePlanStore,
    FakeRecipientGrants,
    FakeWebSearcher,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import TurnOutcome

_UTTERANCE: Final = "what does the weekend look like"


def _asks() -> ReadRequest:
    """A request asking for a forecast and nothing else (ADR-0260 §3)."""
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.FORECAST_READ),))


async def _turn(**knobs: Any) -> TurnOutcome:
    """Drive one turn through the real engine over a configured forecast deployment.

    Args:
        **knobs: Whatever the case varies on the servicing — the seam, or whether the
            deployment configured the pair at all.

    Returns:
        The outcome the capture point built.
    """
    harness = Harness(
        planner=_AskingPlanner(_asks(), rounds=1),
        forecast=servicer(**knobs),
    )
    return await harness.engine.converse(_UTTERANCE, timeout=PATIENT)


async def test_an_answered_read_carries_no_member_and_names_the_forecast_provider() -> None:
    """§13's arm (h), first case, **through to the turn**.

    "A read the provider answered carries ``forecast_not_read`` ``None`` and an outbound
    statement naming ``FORECAST_PROVIDER``." §10's ``None`` "means the servicing recorded
    no ``ForecastDisposition``, and means nothing else" — a turn that serviced no forecast
    read, and a read the provider answered — and the statement beside it is what tells
    those two apart for the user, which is the asymmetry #2268 recorded for search
    arriving at a second seam.

    The records count is ADR-0264 §4's, "how many records this turn's established
    contacts put into the turn's **supply**", so it is what the fourth group admitted and
    not what the provider returned.
    """
    outcome = await _turn()

    assert outcome.forecast_not_read is None, "the provider answered"
    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (OutboundDestination.FORECAST_PROVIDER,)
    assert statement.records == len(DEFAULT_FORECAST_DAYS)
    assert outcome.search_not_serviced is None, "no search was asked for, so no member"


async def test_a_read_the_deployment_could_not_authorise_carries_the_member_and_no_class() -> None:
    """§13's arm (h), second case, through to the turn: the member, and **no** class.

    A deployment that configured no forecast pair takes route (c) in no case — §6's
    fail-closed direction — so the ruling is a ``CONFIRM``, which §11 parks nowhere and
    §10 folds to ``AUTHORISATION_AWAITED`` on the **no-contact** side. So the user is
    told a class of act and the turn says it reached nothing, which are two statements
    ADR-0264 §8 has ride together rather than one suppressing the other.
    """
    outcome = await _turn(configured=False)

    assert outcome.forecast_not_read is ForecastNotRead.AUTHORISATION_AWAITED
    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == ()
    assert statement.records == 0


@pytest.mark.parametrize(
    ("refusal", "member", "reach"),
    [
        (
            ForecastRefusal.UNATTESTED,
            ForecastNotRead.UNAVAILABLE,
            OutboundReach.REACHED,
        ),
        (
            ForecastRefusal.RESPONSE_TOO_LARGE,
            ForecastNotRead.UNAVAILABLE,
            OutboundReach.REACHED,
        ),
        (
            ForecastRefusal.DEADLINE_EXPIRED,
            ForecastNotRead.INTERRUPTED,
            OutboundReach.INDETERMINATE,
        ),
        (
            ForecastRefusal.TRANSPORT_FAILED,
            ForecastNotRead.UNAVAILABLE,
            OutboundReach.INDETERMINATE,
        ),
        (
            ForecastRefusal.PROVIDER_REFUSED,
            ForecastNotRead.UNAVAILABLE,
            OutboundReach.INDETERMINATE,
        ),
        (ForecastRefusal.NO_RESULT, None, OutboundReach.REACHED),
    ],
)
async def test_each_refusal_reaches_the_turn_as_its_member_and_its_reach(
    refusal: ForecastRefusal,
    member: ForecastNotRead | None,
    reach: OutboundReach,
) -> None:
    """§13's arm (h)'s remaining cases, each carried the whole way to the outcome.

    The pairs are §10's and are asserted **together**, because the two facts are
    computed from two rules over one disposition and neither is read off the other:
    ``UNATTESTED`` and ``RESPONSE_TOO_LARGE`` carry ``UNAVAILABLE`` **with** a contact —
    "either folded to ``INDETERMINATE`` would deny a contact the trail recorded" — while
    the three nothing-either-way members carry ``INDETERMINATE`` with **no** class.
    ``NO_RESULT`` is the thirteenth case: it maps to no disposition at all, so the turn
    carries no member and the contact its call established.

    **The count rides with the contact and never without it** (ADR-0264 §4): every one of
    these brought nothing into the supply, and a ``0`` "never suppresses the statement".

    Args:
        refusal: What the provider's answer resolved to.
        member: The member §10 folds it to, or ``None`` where it records no disposition.
        reach: The side of §10's partition it lands on.
    """
    outcome = await _turn(seam=forecaster(refusal=refusal))

    assert outcome.forecast_not_read is member
    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is reach
    assert statement.records == 0, "nothing entered the supply, and the statement stands"
    if reach is OutboundReach.REACHED:
        assert statement.destinations == (OutboundDestination.FORECAST_PROVIDER,)
    else:
        assert statement.destinations == (), "only a contact names a class (ADR-0264 §4)"


async def test_a_turn_that_asked_for_no_forecast_carries_neither_the_member_nor_a_class() -> None:
    """The control every case above rests on: ``None`` on a turn that never asked.

    §10 gives ``None`` exactly two meanings — "a turn that serviced no forecast read,
    and a read the provider answered" — so without this the first case's ``None`` would
    be evidence of nothing. The statement is what separates them: this turn reached
    nothing and says so, where the answered turn names the class it contacted.
    """
    harness = Harness(planner=_AskingPlanner(None, rounds=1), forecast=servicer())

    outcome = await harness.engine.converse(_UTTERANCE, timeout=PATIENT)

    assert outcome.forecast_not_read is None
    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == ()


# --------------------------------------------------------------------------- #
# The arms §13 states over a **turn**, driven through the production pipeline   #
# --------------------------------------------------------------------------- #
#
# ``test_forecast_servicing.py`` discharges these over the servicing and its carriers,
# which is where the rules are computed; what it cannot see is the wiring **above** the
# servicing — the loop's folds and the engine's forwarding — so a lane that dropped
# either would leave those assertions green while the turn reported the wrong thing.
# §13 states four of its arms over a *turn* in terms, and this is where they are met.


@final
class _DenyingNth:
    """A policy that rules ``DENY`` on one call of a turn and normally on the others.

    A revising turn services its forecast **twice** (ADR-0228 §3, ADR-0251 §4), and
    §13's arm (h) is stated over a turn whose two servicings recorded **different**
    dispositions — so something has to differ between the calls. The ruling is the
    honest place for it: ADR-0260 §6's route (c) is taken over the request, and a
    deployment whose policy denies one request and allows another is an ordinary
    deployment rather than an arranged one.

    **Two real policies rather than one edited ruling.** A ruling copied with its
    outcome overwritten would be a value no policy produced, and ``PermissionDecision``
    couples an outcome to the fields beside it; each call here is answered by a policy
    that genuinely reaches the outcome it returns.
    """

    __slots__ = ("_allower", "_calls", "_denier", "_deny")

    def __init__(self, *, deny: int) -> None:
        """Deny the ``deny``-th call of this policy's life.

        Args:
            deny: Which call rules ``DENY`` — ``1`` for a turn's first servicing.
        """
        self._deny = deny
        self._calls = 0
        self._denier = FakeActionPolicy(deny_at=RiskLevel.LOW)
        self._allower = ThresholdActionPolicy(
            grants=FakeRecipientGrants((), now=lambda: NOW),
            configured_forecast=configured_forecast(),
        )

    async def decide(self, request: Any) -> Any:
        """Rule on ``request`` through whichever policy this call belongs to.

        Args:
            request: The request to rule on.

        Returns:
            The ruling.
        """
        self._calls += 1
        chosen = self._denier if self._calls == self._deny else self._allower
        return await chosen.decide(request)

    async def resolve(self, decision: Any, *, approved: bool) -> Any:
        """Never reached: ADR-0260 §11 parks no forecast read.

        Args:
            decision: The decision.
            approved: The answer.

        Returns:
            Whatever the allowing policy resolves.
        """
        return await self._allower.resolve(decision, approved=approved)


async def _revising(*, deny: int, seam: Any) -> TurnOutcome:
    """A turn whose planner asks for a forecast on **both** of its calls.

    Args:
        deny: Which of the two servicings is ruled ``DENY``.
        seam: The forecaster both servicings are answered by.

    Returns:
        The outcome the capture point built.
    """
    harness = Harness(
        planner=_AskingPlanner(_asks(), rounds=2),
        forecast=servicer(seam=seam, policy=_DenyingNth(deny=deny)),
    )
    return await harness.engine.converse(_UTTERANCE, timeout=PATIENT)


@pytest.mark.parametrize("deny", [1, 2])
async def test_a_denied_read_outranks_a_failed_one_in_both_encounter_orders(deny: int) -> None:
    """§13's arm (h)'s revising case, **through the turn** and in both orders.

    "A **revising** turn whose two forecast servicings recorded ``RULING_DENY`` and
    ``TRANSPORT_FAILED`` reports ``DECLINED`` in **both** encounter orders." §10 carries
    "the **earliest-declared** member any servicing of the turn recorded", and
    ``DECLINED`` precedes ``UNAVAILABLE`` in ``ForecastNotRead``'s declared order — so
    the order and not the encounter order decides it. An implementation carrying the
    last member it computed passes one of these rows; one assigning only while the
    carrier is ``None`` passes the other.

    **The contact stands beside it.** The failing servicing's call reached nothing
    either way, so the turn is ``INDETERMINATE`` and names no class — ADR-0264 §8's
    both-statements rule, which is why the member and the statement are asserted
    together rather than one standing for the other.

    Args:
        deny: Which of the two servicings is ruled ``DENY``.
    """
    outcome = await _revising(deny=deny, seam=forecaster(refusal=ForecastRefusal.TRANSPORT_FAILED))

    assert outcome.forecast_not_read is ForecastNotRead.DECLINED
    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.INDETERMINATE
    assert statement.destinations == ()


async def test_a_denied_read_followed_by_an_answered_one_still_reports_declined() -> None:
    """§13's arm (h)'s last revising clause, through the turn.

    "One whose denied read is followed by an answered read still reports ``DECLINED``
    and its statement rather than ``None``", because §10 rules that "a later read does
    not clear an earlier one's member: the user was told about a read this turn did not
    make and a second read does not unmake it".

    **And the contact the second read established still stands**, which is the pair that
    makes this case worth driving whole: the turn carries a member *and* names the class
    it reached, neither suppressing the other.
    """
    outcome = await _revising(deny=1, seam=forecaster())

    assert outcome.forecast_not_read is ForecastNotRead.DECLINED
    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (OutboundDestination.FORECAST_PROVIDER,)
    assert statement.records == len(DEFAULT_FORECAST_DAYS), (
        "ADR-0264 §4 counts what the turn's established contacts put into its supply"
    )


# --------------------------------------------------------------------------- #
# (l) and (m): a turn that reaches both configured providers                    #
# --------------------------------------------------------------------------- #


def _searching(results: int = 1) -> Any:
    """The search servicing a configured deployment holds, at ADR-0231 §5's own cap.

    Args:
        results: How many contents the provider answers with, at most three — which is
            ``search_max_results``' own ceiling and the reason a case needing the
            forecast reached with one slot left lowers the **budget** instead.

    Returns:
        The wired search servicing.
    """
    return _servicer(
        searcher=_CostedSearcher(
            FakeWebSearcher(
                results=tuple(
                    f"A result\nhttps://example.com/{n}\nAbout thing {n}." for n in range(results)
                ),
                max_results=results,
            )
        ),
        granted=True,
    )


def _both_kinds() -> ReadRequest:
    """A request asking for a search **and** a forecast, in that order (ADR-0260 §7)."""
    return ReadRequest(
        asks=(ReadAsk(kind=ReadKind.WEB_SEARCH), ReadAsk(kind=ReadKind.FORECAST_READ))
    )


async def test_a_turn_that_reached_both_providers_names_both_classes_once() -> None:
    """§13's arm (l), **through one production turn**.

    "A turn that reached the configured **search** provider and the configured
    **forecast** provider carries **one** outbound statement naming **both** destination
    classes, in §10's stated order, neither displacing the other — because an
    implementation overwriting ``SEARCH_PROVIDER`` with ``FORECAST_PROVIDER`` would deny
    a contact the trail recorded, which is the asymmetry §10 exists to close."

    Driven whole because the overwrite the arm is about lives in the **wiring**: the
    loop folds two carriers and the engine assembles one statement from them, and a
    single folded value would pass every servicing-level assertion while naming one
    class.

    ADR-0264 §4's count is **one population over the turn**, so it is the sum of what
    both contacts admitted and not one figure per class.
    """
    harness = Harness(
        planner=_AskingPlanner(_both_kinds(), rounds=1),
        search=_searching(),
        forecast=servicer(),
    )

    outcome = await harness.engine.converse(_UTTERANCE, timeout=PATIENT)

    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (
        OutboundDestination.SEARCH_PROVIDER,
        OutboundDestination.FORECAST_PROVIDER,
    ), "both classes, once each, in OutboundDestination's declared order"
    assert statement.records == len(DEFAULT_FORECAST_DAYS) + 1, (
        "one population over the turn: the search's one minted record and the forecast's three days"
    )
    assert outcome.forecast_not_read is None, "both reads were answered"
    assert outcome.search_not_serviced is None


async def test_a_record_the_search_contributed_reaches_the_forecast_binding() -> None:
    """§13's arm (m), over **the search** the arm names and over the binding itself.

    "A turn whose pre-servicing supply carries **no** external record, and whose web
    search then contributes one, builds a forecast binding carrying
    ``planned_with_external_content`` **`True`** — asserted over the binding itself,
    because §7 computes it over the pre-servicing supply **and** over every record this
    servicing has already contributed, and an implementation inspecting only the first
    passes every other arm while writing ``False``."

    The search is what the arm names and is what is driven here: §7 services it
    **second** and the forecast **third**, so the minted search record is in view at the
    instant the forecast request is built, and nothing else in this turn is.
    """
    capturing = _CapturingBinder(binder(FORECAST_DECLARATION))
    harness = Harness(
        planner=_AskingPlanner(_both_kinds(), rounds=1),
        search=_searching(),
        forecast=servicer(binding=capturing),
    )

    outcome = await harness.engine.converse(_UTTERANCE, timeout=PATIENT)

    [provenance] = capturing.carried
    assert provenance.planned_with_external_content is True, (
        "the search's minted record is in view when the forecast request is built"
    )
    assert provenance.forecast_reach is True, "§11's fact, written exactly here"
    assert provenance.closed_loop is False, "closed_loop still means this deployment's search"
    assert outcome.forecast_not_read is None, "and the forecast still ran"


# --------------------------------------------------------------------------- #
# (g): the row a goal turn actually writes                                      #
# --------------------------------------------------------------------------- #


async def _goal_turn(
    *, forecast: Any, request: ReadRequest | None = None, search: Any = None
) -> tuple[FakePlanStore, str]:
    """Run one turn of a goal an earlier turn opened, and hand back what it wrote.

    ADR-0252 §14 produces a row per outcome entry "on a turn working on a goal", so the
    row this arm is about exists only on a turn that has one — which is why this seeds a
    goal and associates the turn with it rather than driving a bare ``converse``.

    Args:
        forecast: The forecast servicing this deployment holds.
        request: What the planner asks for, defaulting to a forecast and nothing else.
        search: The search servicing, where the case needs the budget spent first.

    Returns:
        The plan store the engine was wired with, and the goal's id.
    """
    plans = FakePlanStore(now=lambda: AT)
    harness = Harness(
        planner=_AskingPlanner(_asks() if request is None else request, rounds=1),
        plans=plans,
        forecast=forecast,
        search=search,
        associator=_associating(AssociationVerdict.CONTINUES),
    )
    conversation = (await harness.conversations.begin(None)).id
    goal = await _seed(
        plans,
        _goal("g-forecast", "know what the weekend looks like", conversation=conversation),
        engaged_in=conversation,
    )

    outcome = await harness.engine.converse(
        _UTTERANCE, timeout=PATIENT, conversation_id=conversation
    )

    assert outcome.turn is not None
    return plans, goal.id


async def test_a_goal_turn_writes_the_forecast_row_the_adr_describes() -> None:
    """§13's arm (g), **through the turn that writes the row**.

    "A forecast servicing on a goal turn writes a row whose ``requested`` is absent,
    whose ``records`` is empty, and whose ``supported`` carries one region per record
    the ask returned … applying **only** a window equal to that record's extent."

    Driven whole because every value here is composed at a **different** site: the
    source at the servicing, the instant at the loop's clock, the id at its factory, and
    the row at ``record_evidence``. A lane that dropped ``source`` on the way, or stopped
    forwarding the rows, would leave a composition-level assertion green while the goal's
    history held nothing — which is what §14's production rule is about.
    """
    plans, goal_id = await _goal_turn(forecast=servicer())

    history = await plans.evidence_of(goal_id)
    (written,) = history.rows

    assert written.basis is EvidenceBasis.READ_OUTCOME
    assert written.read_kind is ReadKind.FORECAST_READ
    assert written.requested is None, "§9: this ask has no typed part to compose one from"
    assert written.records == (), "§9: a forecast row names no record; the count stands alone"
    assert written.returned == len(DEFAULT_FORECAST_DAYS)
    assert written.admitted == len(DEFAULT_FORECAST_DAYS)
    assert written.source == "fake forecast", "§9: the forecaster's own name"
    assert written.as_of == NOW, "§9: the Attestation.reported_at the provider declared"
    assert written.verdict == ReadOutcomeKind.RETURNED_RECORDS.value
    assert written.standing is EvidenceStanding.STANDING
    assert len(written.supported) == len(DEFAULT_FORECAST_DAYS)
    for region, day in zip(written.supported, DEFAULT_FORECAST_DAYS, strict=True):
        assert region.window == TimeWindow(
            start=day.extent.extends_from, end=day.extent.extends_until
        ), "the day the provider stated, and no other axis"
        assert region.participants is None
        assert region.topics is None
        assert region.about_person is None


async def test_a_row_carries_a_region_per_returned_day_although_the_budget_admitted_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§13's arm (g)'s own stated case, on the row a goal turn actually wrote.

    "A servicing returning three records of which the budget admits one still writes
    three regions", because ADR-0252 §2 composes ``supported`` from what the read
    **returned** rather than from what the supply took.

    The budget is lowered rather than the caps raised, for the reason
    ``test_forecast_servicing.py``'s own budget arm records: a file is capped at one
    record and a search at three, so at most four of ADR-0226 §6's ten can be spent
    before the forecast is reached, and a case that could only be written by raising a
    cap ADR-0231 §5 closes would be testing a different decision.
    """
    monkeypatch.setattr(reads, "READ_BUDGET", 4)

    plans, goal_id = await _goal_turn(
        forecast=servicer(),
        request=_both_kinds(),
        search=_searching(results=3),
    )

    history = await plans.evidence_of(goal_id)
    [row] = [one for one in history.rows if one.read_kind is ReadKind.FORECAST_READ]

    assert row.returned == len(DEFAULT_FORECAST_DAYS), "three days came back"
    assert row.admitted == 1, "and the budget took one of them"
    assert len(row.supported) == len(DEFAULT_FORECAST_DAYS), (
        "§2 composes supported from what the read returned, not from what fitted"
    )
    assert row.verdict == ReadOutcomeKind.TRUNCATED.value, (
        "ADR-0251 §2: TRUNCATED displaces RETURNED_RECORDS where the budget cut the yield"
    )


# --------------------------------------------------------------------------- #
# (h)'s pre-execution refusal and (n)'s three shapes, through to the turn       #
# --------------------------------------------------------------------------- #


@final
class _ProposingOneReadingAnother:
    """A forecaster that proposes one declaration and checks the call against another.

    **§6's second check, reached genuinely through the canonical fake's own
    implementation of it** (ADR-0029 §2, ADR-0260 §6): ``FakeForecaster.read`` compares
    the call's definition against *its own* registered declaration and refuses an
    unequal one, which §6 names as the check "``authorises`` would otherwise pass".
    Splitting the proposal and the read across two fakes is what gives that check a
    subject from outside the seam, the servicing building the call from whatever
    ``request`` returned.
    """

    __slots__ = ("_proposing", "_reading")

    def __init__(self) -> None:
        """Propose a costed declaration and read against an uncosted one."""
        self._proposing = forecaster()
        self._reading = FakeForecaster(reported_at=NOW)

    @property
    def name(self) -> str:
        """The configured source's own identity, one value for both halves."""
        return self._proposing.name

    async def request(self) -> Any:
        """Propose the declaration the binder holds a registration for.

        Returns:
            The proposal.
        """
        return await self._proposing.request()

    async def read(self, call: Any, /, *, timeout: Any) -> Any:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1); this carries the production signature
        """Refuse: this call names a declaration this half did not register.

        Args:
            call: The authorised call.
            timeout: The bound.

        Returns:
            Never — the fake's own second check raises first.
        """
        return await self._reading.read(call, timeout=timeout)


@final
class _MutatingTheCall:
    """A forecaster whose caller's call is rewritten after the servicing constructed it.

    ``ToolCall``'s validator runs at construction and a ``__dict__`` write defeats
    ``frozen=True``, which is the shape §6's **first** check exists for — "a mutation
    landed after construction cannot survive into the read" — and is how ADR-0260 §13's
    arm (c) drives it over the production forecaster. Delegating to the canonical fake
    afterwards means the refusal comes from a real implementation of the check rather
    than from a raise this test wrote.

    **Two of §6's three origins land on this one check from outside the seam, and that
    is the checks' stated order rather than a gap here**: §6 revalidates *before*
    re-evaluating ``authorises``, and ``ToolCall``'s own validator runs ``authorises``
    itself — so a substituted request is refused at check one with the explicit
    re-evaluation standing behind it, which is exactly what arm (c)'s own third case
    records. Separating the three is that arm's, at the seam, over the production
    forecaster; what arm (h) owes is what each **records through to the turn**.
    """

    __slots__ = ("_inner", "_rewrite")

    def __init__(self, rewrite: Callable[[Any], Any]) -> None:
        """Wrap the canonical fake behind one rewriting of the call.

        Args:
            rewrite: Given the call the servicing built, answers the request to put in
                its place.
        """
        self._inner = forecaster()
        self._rewrite = rewrite

    @property
    def name(self) -> str:
        """The configured source's own identity."""
        return self._inner.name

    async def request(self) -> Any:
        """Propose exactly what the wrapped forecaster proposes.

        Returns:
            The proposal.
        """
        return await self._inner.request()

    async def read(self, call: Any, /, *, timeout: Any) -> Any:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1); this carries the production signature
        """Rewrite the call, then hand it to a real implementation of §6's checks.

        Args:
            call: The authorised call the servicing built.
            timeout: The bound.

        Returns:
            Never — the fake's own checks raise on the rewritten call.
        """
        call.__dict__["request"] = self._rewrite(call)
        return await self._inner.read(call, timeout=timeout)


def _elsewhere(call: Any) -> Any:
    """§6's first origin: arguments rewritten after the call was constructed.

    Args:
        call: The call the servicing built.

    Returns:
        Its request with another origin in place of the configured one.
    """
    return call.request.model_copy(update={"parameters": {"origin": "https://elsewhere"}})


def _another_place(call: Any) -> Any:
    """§6's third origin: a request the recorded decision does not authorise.

    Args:
        call: The call the servicing built.

    Returns:
        Its request naming another coordinate, which the decision was not taken over.
    """
    parameters = {**call.request.parameters, "latitude": 0.0, "longitude": 0.0}
    return call.request.model_copy(update={"parameters": parameters})


@pytest.mark.parametrize(
    "seam",
    [
        pytest.param(lambda: _MutatingTheCall(_elsewhere), id="mutated_after_construction"),
        pytest.param(_ProposingOneReadingAnother, id="foreign_declaration"),
        pytest.param(lambda: _MutatingTheCall(_another_place), id="unauthorised_request"),
    ],
)
async def test_each_pre_execution_refusal_reaches_the_turn_as_binding_failed(
    seam: Callable[[], Any],
) -> None:
    """§13's arm (h)'s last case, over each of §6's three origins, **through the turn**.

    "§6's three pre-execution checks are asserted through to the turn:
    ``BINDING_FAILED`` in the audit, ``UNAVAILABLE`` in ``forecast_not_read``, and
    **no** contact, because a path recording nothing would leave §10's ``None`` saying
    the provider answered."

    The last clause is why this is a **decline** and not ADR-0226 §5's degradation: a
    degraded servicing carries no disposition, and an absent disposition is §10's
    *answered* case — so a lane that let the raise fall through to the degradation would
    tell the user the provider answered a read it refused to make.

    **Which check each origin lands on is the seam's own ordering and is arm (c)'s**, at
    the seam and over the production forecaster; what is asserted here is that every one
    of them records the same triple at the turn.

    Args:
        seam: Builds the forecaster this row drives.
    """
    with structlog.testing.capture_logs() as captured:
        harness = Harness(
            planner=_AskingPlanner(_asks(), rounds=1),
            forecast=servicer(seam=seam()),
        )
        outcome = await harness.engine.converse(_UTTERANCE, timeout=PATIENT)

    [record] = [one for one in captured if one["event"] == READ_AUDIT_EVENT]
    (serviced,) = record["servicings"]
    assert serviced["forecast"] == ForecastDisposition.BINDING_FAILED.value
    assert serviced["forecast_serviced"] is True
    assert serviced["failed"] is False, "a decline is not a degradation"
    assert outcome.forecast_not_read is ForecastNotRead.UNAVAILABLE
    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == (), "no channel was opened, so no class is named"


@final
class _RaisingAfterTheForecast:
    """A store whose ``search`` raises, failing the servicing **after** the forecast.

    ADR-0260 §7 services the sighted query **last**, so a store that raises there fails a
    servicing whose forecast has already been performed — the shape §13's arm (n) is
    stated over.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: FakeMemoryStore) -> None:
        """Wrap a store whose other members answer normally.

        Args:
            inner: The store to delegate to.
        """
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        """Delegate everything this class does not name.

        Args:
            name: The member being reached for.

        Returns:
            The wrapped store's member.
        """
        return getattr(self._inner, name)

    async def search(self, *args: Any, **kwargs: Any) -> Any:
        """Fail the servicing, after the forecast was serviced.

        Args:
            *args: Ignored.
            **kwargs: Ignored.

        Raises:
            MemoryStoreError: Always.
        """
        _ = args, kwargs
        msg = "the store went away after the forecast was read"
        raise MemoryStoreError(msg)


async def _then_failed(*, seam: Any) -> TurnOutcome:
    """A turn whose forecast is serviced and whose later sighted query then raises.

    Args:
        seam: The forecaster the forecast is answered by.

    Returns:
        The outcome the capture point built.
    """
    harness = Harness(
        planner=_AskingPlanner(
            ReadRequest(
                asks=(
                    ReadAsk(kind=ReadKind.FORECAST_READ),
                    ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="anything at all"),
                )
            ),
            rounds=1,
        ),
        memory=_RaisingAfterTheForecast(FakeMemoryStore(now=lambda: AT)),  # type: ignore[arg-type]  # a MemoryStore face, which is what the loop holds
        forecast=servicer(seam=seam),
    )
    return await harness.engine.converse(_UTTERANCE, timeout=PATIENT)


async def test_the_turn_keeps_a_contact_its_failed_servicing_established() -> None:
    """§13's arm (n)'s first case, **through the turn**.

    "A servicing whose forecast read was **answered** and whose **later** read of another
    kind then raises carries ``FORECAST_PROVIDER`` ``REACHED`` with ``records`` ``0`` and
    ``forecast_not_read`` ``None`` — ADR-0226 §5 discarded the servicing's records, and
    §10's quoted clause, *nothing that happens to the enclosing servicing afterwards
    unmakes it*, is what survives them."

    Driven whole because the survival happens in the **wiring**: the servicing carries the
    contact out on its failing path, the loop folds it, and the engine assembles it — and
    a loop that stopped folding carriers from failed servicings would leave the
    servicing-level arm green while the turn lost the contact.
    """
    outcome = await _then_failed(seam=forecaster())

    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (OutboundDestination.FORECAST_PROVIDER,)
    assert statement.records == 0, "ADR-0226 §5 left the supply as planning saw it"
    assert outcome.forecast_not_read is None, "the provider answered"


async def test_an_unattested_read_before_the_failure_reaches_the_turn_as_both() -> None:
    """§13's arm (n)'s second case, through the turn: the contact **and** the member.

    "The same servicing having recorded ``UNATTESTED`` **before** that later failure
    carries the contact **and** ``UNAVAILABLE``" — ADR-0264 §8's both-statements rule
    riding out on a record ADR-0226 §5 emptied.
    """
    outcome = await _then_failed(seam=forecaster(refusal=ForecastRefusal.UNATTESTED))

    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (OutboundDestination.FORECAST_PROVIDER,)
    assert statement.records == 0
    assert outcome.forecast_not_read is ForecastNotRead.UNAVAILABLE


#: What a root the planner can name holds, so ``F1`` resolves to an entry the servicing
#: then fails on rather than to nothing (ADR-0226 §3's silent discard is a different
#: shape and reaches no fetcher).
_ROOT: Final = {"quarter.md": "the quarter went well enough"}


@final
class _RaisingFetcher:
    """A ``Fetcher`` that lists normally and whose ``fetch`` raises.

    The listing is read at the **start** of the turn, before planning, so a fetcher
    that refused there would take the turn down before a plan existed to carry a
    request. What this fails is the **fetch**, which ADR-0260 §7 services first — ahead
    of the forecast, which is the position §13's arm (n)'s third case turns on.
    """

    __slots__ = ("_inner",)

    def __init__(self) -> None:
        """List over a real root and fail every fetch against it."""
        self._inner = FakeFetcher(_ROOT, read_at=AT)

    @property
    def name(self) -> str:
        """This fetcher's identity."""
        return self._inner.name

    async def listing(self) -> Any:
        """The root's own listing, so the planner has an entry to name.

        Returns:
            The listing.
        """
        return await self._inner.listing()

    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        """Fail before the forecast's position in §7's order.

        Args:
            *args: Ignored.
            **kwargs: Ignored.

        Raises:
            MemoryStoreError: Always.
        """
        _ = args, kwargs
        msg = "the file went away"
        raise MemoryStoreError(msg)


async def test_a_turn_whose_servicing_failed_before_the_forecast_names_no_class() -> None:
    """§13's arm (n)'s third case, through the turn: **no** contact and ``None``.

    "One that raised **before** the forecast was serviced, having opened no channel,
    carries **no** contact and ``None``. An implementation computing the fact off the
    ended servicing rather than at the performing site passes every other arm here and
    fails all three."

    The **local file** is serviced ahead of the forecast (§7), so a fetcher that raises
    there fails the servicing before the forecast is reached — and the turn then reports
    reaching nothing, which is what tells this shape from the two above.
    """
    seam = forecaster()
    harness = Harness(
        planner=_AskingPlanner(
            ReadRequest(
                asks=(
                    ReadAsk(kind=ReadKind.LOCAL_FILE, entry="F1"),
                    ReadAsk(kind=ReadKind.FORECAST_READ),
                )
            ),
            rounds=1,
        ),
        fetcher=_RaisingFetcher(),
        forecast=servicer(seam=seam),
    )

    outcome = await harness.engine.converse(_UTTERANCE, timeout=PATIENT)

    statement = outcome.outbound_statement
    assert statement is not None
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == ()
    assert outcome.forecast_not_read is None
    assert seam.requested == [], "no request was composed and no channel was opened"
    assert seam.read_calls == []
