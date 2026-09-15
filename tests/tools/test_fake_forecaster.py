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

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

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
    from ai_assistant.core.types import ActionRequest

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

    async def refusing(self, refusal: ForecastRefusal) -> ScriptedRefusal:
        forecaster, call = await _prepared(refusal=refusal)
        return ScriptedRefusal(forecaster=forecaster, call=call, timeout=A_BOUND)

    async def gated(self) -> GatedRead:
        forecaster, call = await _prepared()
        return GatedRead(forecaster=forecaster, call=call, arm=forecaster.suspend_next)

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
