"""The canonical ``Forecaster`` fake, against the same suite the real one passes.

``CONTRIBUTING.md`` requires that "each Protocol gets a shared test suite that every
implementation must pass", and ADR-0260 §13's preamble says so in terms: the production
rule it states "reaches the shared conformance suite not at all … and the canonical fake
passes it exactly as the production forecaster does".

**Here rather than beside the fake**, following ``test_fake_web_searcher.py``: the suite
lives in this package because the production implementation does, and a subclass has to
sit where the suite is importable from.

**And one assertion in this file is the preamble's single allowance.** §13 admits exactly
one assertion over the canonical fake — "(c)'s ``request`` limb … because §4 lets a
``request`` answer from held configuration with no await, so the contract does not oblige
that member to suspend and a production arm would be asserting a suspension point no
implementation owes". The unconfigured arm is the other half of the same shape: the
production forecaster is built only where a provider is configured, so the ``None`` arm is
a state only this implementation has.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, final

import pytest
from forecaster_contract import (
    A_BOUND,
    ConfiguredProvider,
    ForecasterContract,
    GatedRead,
    ScriptedRead,
    ScriptedRefusal,
)

from ai_assistant.core.types import (
    ActionRequest,
    ForecastRefusal,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ToolCall,
)
from ai_assistant.testing import (
    DEFAULT_FORECAST_LATITUDE,
    DEFAULT_FORECAST_LONGITUDE,
    DEFAULT_FORECAST_ORIGIN,
    DEFAULT_MAX_DAY_CHARS,
    DEFAULT_MAX_FORECAST_DAYS,
    FAKE_FORECAST_READ,
    FakeForecaster,
    ScriptedDay,
    forecast_day,
)
from ai_assistant.tools.egress_declaration import DESTINATION_KEYWORD, TIER_KEYWORD

if TYPE_CHECKING:
    from ai_assistant.core.protocols import Forecaster

#: When the one decision every call here carries was taken.
_DECIDED_AT: Final = datetime(2026, 9, 4, 11, 30, tzinfo=UTC)

#: A content bound small enough that the boundary cases script a handful of characters.
_SMALL_CONTENT_BOUND: Final = 64


def _authorised(proposal: ActionRequest) -> ToolCall:
    """One authorised call for ``proposal``.

    Args:
        proposal: The request to authorise.

    Returns:
        The call, which is unconstructable unless the decision authorises it.
    """
    decision = PermissionDecision.from_request(
        proposal,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="the owner configured this"),
        id="d-fake-forecast-1",
        decided_at=_DECIDED_AT,
    )
    return ToolCall(request=proposal, decision=decision)


async def _prepared(**arrangement: Any) -> tuple[FakeForecaster, ToolCall]:
    """A fake and the authorised call that reaches its scripted answer.

    Args:
        arrangement: Passed straight to :class:`FakeForecaster`.

    Returns:
        The forecaster and the call.
    """
    forecaster = FakeForecaster(max_day_chars=_SMALL_CONTENT_BOUND, **arrangement)
    proposal = await forecaster.request()
    assert proposal is not None
    return forecaster, _authorised(proposal)


def _days(count: int) -> tuple[ScriptedDay, ...]:
    """``count`` distinct short days, in the order a provider returned them.

    Distinct so an implementation minting one record per day and one minting the same
    record twice are told apart; short so none of them meets the small content bound
    this harness configures.

    Args:
        count: How many to script.

    Returns:
        The days.
    """
    return tuple(
        forecast_day(2026, 9, 5 + index, offset=timedelta(hours=1), content=f"d{index}")
        for index in range(count)
    )


class TestFakeForecasterContract(ForecasterContract):
    """``FakeForecaster`` against the shared suite (ADR-0260 §12)."""

    @pytest.fixture
    def forecaster(self) -> Forecaster:
        return FakeForecaster()

    def days_bound(self) -> int:
        return DEFAULT_MAX_FORECAST_DAYS

    def content_bound(self) -> int:
        return _SMALL_CONTENT_BOUND

    async def reading(self, days: int) -> ScriptedRead:
        forecaster, call = await _prepared(days=_days(days))
        return ScriptedRead(forecaster=forecaster, call=call)

    async def naming_one_day_twice(self) -> ScriptedRead:
        # Two well-formed scripted rows naming one day between them, and nothing else:
        # both are short enough for the content bound and each would be minted alone, so
        # what drops them is only that the script named their day twice.
        script = (
            forecast_day(2026, 9, 5, offset=timedelta(hours=1), content="one"),
            forecast_day(2026, 9, 5, offset=timedelta(hours=1), content="the other"),
        )
        forecaster, call = await _prepared(days=script)
        return ScriptedRead(forecaster=forecaster, call=call)

    async def refusing(self, refusal: ForecastRefusal) -> ScriptedRefusal:
        forecaster, call = await _prepared(refusal=refusal)
        return ScriptedRefusal(forecaster=forecaster, call=call, timeout=A_BOUND)

    async def gated(self) -> GatedRead:
        forecaster, call = await _prepared()
        return GatedRead(forecaster=forecaster, call=call, arm=forecaster.suspend_next)

    async def another_declaration(self) -> ScriptedRead:
        # This fake holds no binding and derives none, so "fully bound" is vacuous for
        # it: what the shared case needs is a *valid, separately authorised* call whose
        # declaration is not this fake's own registered copy, and that is what this is.
        forecaster = FakeForecaster(max_day_chars=_SMALL_CONTENT_BOUND)
        proposal = await forecaster.request()
        assert proposal is not None
        weakened = proposal.tool.model_copy(update={"description": "nobody registered this"})
        rewritten = ActionRequest(tool=weakened, parameters=dict(proposal.parameters))
        return ScriptedRead(forecaster=forecaster, call=_authorised(rewritten))

    async def elsewhere(self) -> ScriptedRead:
        # This fake holds no binding and derives none, so "fully bound" is vacuous for
        # it: what the shared case needs is a *valid, separately authorised* call naming
        # another place, and that is what this is.
        forecaster = FakeForecaster(max_day_chars=_SMALL_CONTENT_BOUND)
        proposal = await forecaster.request()
        assert proposal is not None
        moved = {
            name: (0.0 if isinstance(value, float) else value)
            for name, value in proposal.parameters.items()
        }
        somewhere_else = ActionRequest(tool=proposal.tool, parameters=moved)
        return ScriptedRead(forecaster=forecaster, call=_authorised(somewhere_else))

    async def configured(self) -> ConfiguredProvider:
        forecaster, _ = await _prepared()
        return ConfiguredProvider(
            forecaster=forecaster,
            origin=DEFAULT_FORECAST_ORIGIN,
            latitude=DEFAULT_FORECAST_LATITUDE,
            longitude=DEFAULT_FORECAST_LONGITUDE,
            declaration=FAKE_FORECAST_READ,
        )

    async def unconfigured(self) -> Forecaster:
        return FakeForecaster(origin=None)


# --- what only this implementation can exhibit (ADR-0260 §4, §13's preamble) ---


async def test_request_answers_none_where_no_provider_is_configured() -> None:
    """§4's ``None`` arm, which only an implementation with an absent provider has.

    "It returns ``None`` where the deployment has configured no forecast provider, which
    is a configuration fact and never a failure." That value is what ``orchestration``
    computes ``CarriedProvenance.forecast_reach`` from (§11) and what the servicing
    records as ``NOT_CONFIGURED`` (§8) — so a fake that raised instead would make a
    consumer's whole ``NOT_CONFIGURED`` branch unreachable.
    """
    forecaster = FakeForecaster(origin=None)

    assert await forecaster.request() is None
    assert forecaster.requested == [None]


async def test_a_cancelled_request_is_delivered_onward_unchanged() -> None:
    """ADR-0260 §13's arm (c), its ``request`` limb — and the preamble's one allowance.

    "**``request`` is asserted over the canonical fake**, under the preamble's one
    allowance and only where an implementation suspends in it — ``WebSearcher``'s own
    shape, which tests cancellation on the suspendable member and models the rest on its
    fake." §4 lets a ``request`` answer from held configuration with no await, so the
    contract obliges no implementation to suspend there and **a production arm would be
    asserting a suspension point no implementation owes**; this fake's own lever is
    therefore the only subject the clause has.

    Held at that suspension and cancelled *there*, because a call cancelled before it
    starts exercises none of the code an implementation would use to convert one — and
    what ADR-0060 §1 forbids is converting one: the cancellation leaves as itself, and
    neither a proposal nor a ``None`` is returned in its place.
    """
    forecaster = FakeForecaster()
    gate = forecaster.suspend_next_request()
    proposal = asyncio.ensure_future(forecaster.request())
    await gate.reached()

    proposal.cancel()
    gate.release()

    with pytest.raises(asyncio.CancelledError):
        await proposal


async def test_an_unarmed_request_answers_without_suspending() -> None:
    """The lever is armed or it is absent, which keeps every other case ordinary.

    A fake that suspended on every proposal would make every consumer's ``request`` a
    scheduling point, and §4's "answers from held configuration" would stop being what
    this fake exhibits. Armed once, it holds once.
    """
    forecaster = FakeForecaster()

    assert await forecaster.request() is not None
    assert await forecaster.request() is not None
    assert forecaster.requested == [None, None]


async def test_a_read_is_recorded_on_entry_so_its_absence_is_assertable() -> None:
    """What makes "``read`` was never reached" the absence of a row.

    A consumer asserting that a ruling stopped before the seam wants the absence of a
    row rather than the absence of a *completed* one, so the call is appended on entry —
    which is also why the timeout guard fires **before** the append.
    """
    forecaster, call = await _prepared()

    assert forecaster.read_calls == []

    await forecaster.read(call, timeout=A_BOUND)

    assert forecaster.read_calls == [call]


@pytest.mark.parametrize(
    "bound", [timedelta(0), timedelta(seconds=-1), "30s"], ids=["zero", "negative", "a-string"]
)
async def test_a_refused_bound_is_refused_before_the_call_is_recorded(bound: object) -> None:
    """ADR-0241 §1's guard, stated by the fake rather than inherited.

    "There is always a bound" is a claim about **every** implementation, so the canonical
    fake states it too — and refuses before recording, so a consumer asserting that a
    refused value reached nothing has the absence of a row to assert over.
    """
    forecaster, call = await _prepared()

    with pytest.raises(ValueError, match="timeout"):
        await forecaster.read(call, timeout=bound)  # type: ignore[arg-type]  # the point of the case

    assert forecaster.read_calls == []


def test_the_fake_declares_the_keywords_tools_reads_by() -> None:
    """The two spellings ADR-0152 §3 fixes, pinned against the constants ``tools/`` uses.

    The fake spells them out rather than importing them, so that the canonical fake
    reaches into no subsystem — and this is the case that stops the two spellings
    drifting without anything noticing, which is
    ``test_fake_web_searcher.py``'s own arrangement one kind over.
    """
    properties = FAKE_FORECAST_READ.parameters_schema["properties"]
    assert isinstance(properties, Mapping)
    origin = properties["origin"]
    assert isinstance(origin, Mapping)
    assert origin[DESTINATION_KEYWORD] == "https"
    assert origin[TIER_KEYWORD] == "operational"
    for name in ("latitude", "longitude"):
        coordinate = properties[name]
        assert isinstance(coordinate, Mapping)
        assert TIER_KEYWORD in coordinate
        assert DESTINATION_KEYWORD not in coordinate


def test_the_fake_declares_the_production_safety_fields() -> None:
    """A fake ruled on more leniently than the real thing is the failure this refuses.

    "A fake ruled on more leniently than the real thing would let a consumer's policy
    test pass for a reason no deployment enjoys." The four fields a ruling depends on are
    the production declaration's, argued in ADR-0016 §1 and ADR-0260 §6.
    """
    assert FAKE_FORECAST_READ.side_effecting is True
    assert [tier.value for tier in FAKE_FORECAST_READ.discloses] == ["personal"]
    assert [tier.value for tier in FAKE_FORECAST_READ.reads] == ["secret"]
    assert FAKE_FORECAST_READ.cost.basis.value == "unknown"


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        pytest.param({"max_days": 4}, ValueError, id="days-above-the-ceiling"),
        pytest.param({"max_days": 0}, ValueError, id="days-zero"),
        pytest.param({"max_days": True}, TypeError, id="days-a-flag"),
        pytest.param({"max_day_chars": 0}, ValueError, id="chars-zero"),
        pytest.param({"latitude": 90.1}, ValueError, id="latitude-out-of-range"),
        # ``float(10**10000)`` raises ``OverflowError``, which is not a ``ValueError``:
        # a caller catching the class this constructor documents would meet one it never
        # declared. The production forecaster refuses it for the same reason.
        pytest.param({"latitude": 10**10000}, ValueError, id="latitude-too-large-for-a-float"),
        pytest.param({"longitude": -(10**10000)}, ValueError, id="longitude-too-small-for-a-float"),
        pytest.param({"longitude": float("nan")}, ValueError, id="longitude-nan"),
        pytest.param({"name": " forecast "}, ValueError, id="a-name-identifier-would-strip"),
        pytest.param({"name": ""}, ValueError, id="a-blank-name"),
        pytest.param({"refusal": "no_result"}, TypeError, id="a-refusal-that-is-a-string"),
        pytest.param(
            {"reported_at": datetime(2026, 9, 4, 12, 0)},  # noqa: DTZ001 — the point of the case
            ValueError,
            id="a-naive-instant",
        ),
    ],
)
def test_the_fake_refuses_every_state_a_deployment_cannot_be_in(
    fields: dict[str, Any], error: type[Exception]
) -> None:
    """The canonical fake must not be the looser of the two (ADR-0236 §7's posture).

    "A canonical fake configurable into a state no deployment can be in would let a
    consumer's test pass over a supply this system can never actually assemble", and each
    refusal is at construction rather than at an arbitrary later call — which is the one
    thing ADR-0260 §4 says never leaves either member.
    """
    with pytest.raises(error):
        FakeForecaster(**fields)


@final
class _Shifty(float):
    """A ``float`` subclass whose ``__float__`` answers differently on each call.

    The shape a guard that validates one conversion and stores another cannot see:
    ``float()`` consults ``__float__`` on a subclass, so two calls are two values. It is
    the hostile-``__repr__`` hazard one axis over, and this repository's own threat model
    admits it (ADR-0018 §3, §4).
    """

    __slots__ = ("_calls",)

    _calls: list[float]

    def __new__(cls, *, first: float, then: float) -> _Shifty:
        """Answer ``first`` once and ``then`` afterwards.

        Args:
            first: What the first conversion sees — a value inside the domain.
            then: What every later one sees — a value outside it.

        Returns:
            The value.
        """
        value = super().__new__(cls, first)
        value._calls = [first, then]
        return value

    def __float__(self) -> float:
        """The next answer in the script.

        Returns:
            ``first`` on the first call and ``then`` on every one after it.
        """
        return self._calls.pop(0) if len(self._calls) > 1 else self._calls[0]


def test_a_coordinate_that_answers_twice_is_stored_as_the_value_that_was_judged() -> None:
    """One conversion, and the guard's own — never the guard's and then the store's.

    ``float()`` consults ``__float__`` on a subclass, so a value that answers ``0.0``
    to the check and ``999.0`` to the store passes every domain assertion and leaves the
    fake configured for a place no deployment can be in — and ADR-0260 §4 says
    ``request`` returns an ``ActionRequest`` or ``None``, where this fake would then
    raise from its own schema. **A fake configurable into a state no deployment can be
    in is the failure this module refuses**, and the production forecaster's guard
    returns its value for the same reason.
    """
    shifty = _Shifty(first=41.0, then=999.0)

    forecaster = FakeForecaster(latitude=shifty)

    assert forecaster._latitude == pytest.approx(41.0)
    assert type(forecaster._latitude) is float


def test_a_cost_pair_with_no_provider_is_refused() -> None:
    """ADR-0236 §2's registration-whole refusal, in the shape this fake has for it.

    ``origin=None`` **is** "a deployment that configured no provider", so a per-call
    figure there is a value nothing reads: ``request`` answers ``None``, and the figure
    would reach no declaration and no policy.
    """
    with pytest.raises(ValueError, match="origin is None"):
        FakeForecaster(origin=None, cost_per_call=Decimal("0.001"), cost_currency="EUR")


async def test_a_configured_cost_reaches_the_fake_s_own_declaration() -> None:
    """ADR-0236 §1, §7: the pair becomes a ``PER_CALL`` cost on a per-instance copy.

    The module constant is never mutated, and where the pair is unset the constant itself
    is carried rather than an equal copy of it — which is what keeps
    :data:`FAKE_FORECAST_READ` the object a consumer can compare against.
    """
    forecaster = FakeForecaster(cost_per_call=Decimal("0.002"), cost_currency="EUR")

    proposal = await forecaster.request()

    assert proposal is not None
    assert proposal.tool.cost.basis.value == "per_call"
    assert proposal.tool.cost.amount == Decimal("0.002")
    assert FAKE_FORECAST_READ.cost.basis.value == "unknown"


async def test_the_fake_drops_a_day_past_its_content_bound_and_never_truncates() -> None:
    """ADR-0260 §5's drop, counted on the quoted rendering as ADR-0230 §6 counts it.

    The siblings are still minted, and where the drop takes the last one the read yielded
    nothing rather than failing — which is what makes a consumer's ``EMPTY`` branch
    reachable without a provider.
    """
    long_day = forecast_day(2026, 9, 5, content="x" * (_SMALL_CONTENT_BOUND + 1))
    short_day = forecast_day(2026, 9, 6, content="fine")

    kept, call = await _prepared(days=(long_day, short_day))
    outcome = await kept.read(call, timeout=A_BOUND)

    assert [record.content for record in outcome.records] == ["fine"]

    empty, other = await _prepared(days=(long_day,))
    refused = await empty.read(other, timeout=A_BOUND)

    assert refused.refusal is ForecastRefusal.NO_RESULT


async def test_the_fake_mints_at_most_its_bound_and_takes_them_from_the_front() -> None:
    """ADR-0260 §5: the cap is taken over the survivors and taken **from the front**.

    Asserted over the canonical fake as well as over the production forecaster, because
    the suite deliberately does not pin the direction — a generic suite cannot tell a
    subject what order its provider returned anything in — and a fake that took the last
    that many would satisfy every count the suite asserts.
    """
    forecaster, call = await _prepared(days=_days(5), max_days=2)

    outcome = await forecaster.read(call, timeout=A_BOUND)

    assert [record.content for record in outcome.records] == ["d0", "d1"]


async def test_the_fake_caps_what_survived_and_not_what_was_scripted() -> None:
    """ADR-0260 §5: the cap is taken **over the surviving days**, and from the front.

    "Where more days survive the drop rule below than ``forecast_max_days`` admits, the
    records minted are the *first* that many." An implementation that sliced first would
    let an oversized early day consume the only slot and answer ``NO_RESULT`` about a
    response that described a usable later one — a read the provider answered reported
    as one that yielded nothing.
    """
    oversized = forecast_day(2026, 9, 5, content="x" * (_SMALL_CONTENT_BOUND + 1))
    usable = forecast_day(2026, 9, 6, content="fine")
    forecaster, call = await _prepared(days=(oversized, usable), max_days=1)

    outcome = await forecaster.read(call, timeout=A_BOUND)

    assert [record.content for record in outcome.records] == ["fine"]


async def test_the_fake_drops_every_row_of_a_day_the_script_named_twice() -> None:
    """ADR-0260 §5: "A day the response names more than once is dropped in **every one of
    its rows**".

    Asserted over the canonical fake because the obligation is the *contract's*: a fake
    that minted the first of two rows naming one day would be scriptable into a state no
    response can put the production forecaster in, and a consumer's suite would pass over
    an answer no deployment can produce. The siblings are still minted, which is what
    makes this a drop rather than a failure.
    """
    first = forecast_day(2026, 9, 5, content="one")
    again = forecast_day(2026, 9, 5, content="the other")
    sibling = forecast_day(2026, 9, 6, content="fine")

    forecaster, call = await _prepared(days=(first, sibling, again))
    outcome = await forecaster.read(call, timeout=A_BOUND)

    assert [record.content for record in outcome.records] == ["fine"]


async def test_the_fake_drops_a_day_named_twice_in_two_declared_offsets() -> None:
    """§5's key is the day the provider **named**, not the instant that day starts at.

    The two rows lie in different offsets, so their extents differ by an hour and a fake
    keying on :attr:`ScriptedDay.extent` would count two days and mint both — the clause
    read backwards. The production forecaster reads its key off the row's own ``date``
    field, independently of the offset, and this is that property at the canonical fake.
    """
    here = forecast_day(2026, 9, 5, offset=timedelta(hours=1), content="one")
    there = forecast_day(2026, 9, 5, offset=timedelta(hours=2), content="the other")

    forecaster, call = await _prepared(days=(here, there))
    outcome = await forecaster.read(call, timeout=A_BOUND)

    assert outcome.refusal is ForecastRefusal.NO_RESULT
    assert outcome.records == ()


async def test_the_fake_drops_a_duplicate_that_sits_beyond_its_cap() -> None:
    """ADR-0260 §13(b-prime): the duplicate drop is **before** the cap.

    "An implementation capping before it looks for duplicates mints the first row and
    passes every arm that keeps the duplicate inside the cap." Four days and a cap of
    three: the second naming of the first day sits fourth, so a fake that sliced first
    would never see it and would mint a day its script described twice.
    """
    script = (
        forecast_day(2026, 9, 5, content="d0"),
        forecast_day(2026, 9, 6, content="d1"),
        forecast_day(2026, 9, 7, content="d2"),
        forecast_day(2026, 9, 5, content="d0 again"),
    )

    forecaster, call = await _prepared(days=script, max_days=3)
    outcome = await forecaster.read(call, timeout=A_BOUND)

    assert [record.content for record in outcome.records] == ["d1", "d2"]


async def test_the_fake_counts_a_named_day_before_it_drops_on_the_content_bound() -> None:
    """§5's duplicate clause meeting its content clause, which are two drops and one day.

    The oversized row is dropped on its own account and still **named** its day, so the
    ordinary row is a second description of a day the script described twice. A fake
    applying the content bound before counting the names would keep the ordinary one,
    which is this system preferring one of the provider's rows over another.
    """
    ordinary = forecast_day(2026, 9, 5, content="short")
    oversized = forecast_day(2026, 9, 5, content="x" * (_SMALL_CONTENT_BOUND + 1))
    sibling = forecast_day(2026, 9, 6, content="fine")

    forecaster, call = await _prepared(days=(ordinary, oversized, sibling))
    outcome = await forecaster.read(call, timeout=A_BOUND)

    assert [record.content for record in outcome.records] == ["fine"]


def test_a_scripted_day_whose_extent_is_not_its_named_day_is_unconstructable() -> None:
    """The pair is one fact, so a script cannot put a day's content outside its own day.

    ADR-0260 §5 computes an extent "from the day the provider named and the UTC offset the
    provider's own response declared for it, and from nothing else" — so the two fields
    are recoverable from each other and a mismatch is a record placing a day somewhere its
    own date does not lie. Refused at construction, because a fake that took it would mint
    evidence ADR-0252 §3 would compose a window from that no response can produce.
    """
    elsewhere = forecast_day(2026, 9, 9).extent

    with pytest.raises(ValueError, match="ADR-0260"):
        ScriptedDay(content="misplaced", extent=elsewhere, named=(2026, 9, 5))

    with pytest.raises(ValueError, match="calendar"):
        ScriptedDay(content="no such day", extent=elsewhere, named=(2026, 2, 30))


def test_the_default_answer_is_three_dated_days_each_declaring_its_own_offset() -> None:
    """ADR-0260 §12: "It answers with **dated days, each declaring the UTC offset it is
    in**".

    The default script exists so that a consumer wiring this fake gets the shape §5
    mints rather than having to build one — and each day's extent is a day long, computed
    from the day and the offset and from nothing else.
    """
    from ai_assistant.testing import DEFAULT_FORECAST_DAYS  # noqa: PLC0415 — one case needs it

    assert len(DEFAULT_FORECAST_DAYS) == DEFAULT_MAX_FORECAST_DAYS
    for scripted in DEFAULT_FORECAST_DAYS:
        assert scripted.extent.extends_from is not None
        assert scripted.extent.extends_until is not None
        assert scripted.extent.extends_until - scripted.extent.extends_from == timedelta(days=1)
    assert DEFAULT_MAX_DAY_CHARS == 2048
