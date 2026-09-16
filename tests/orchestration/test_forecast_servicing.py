"""ADR-0260 §13's L3 arms (f), (g), (h), (l), (m) and (n), at the servicing site.

**The subject is production throughout** — ``service_read_request``, the
:class:`~ai_assistant.orchestration.reads.ForecastServicer` it is handed, the real
:class:`~ai_assistant.tools.egress_binder.EgressBindingSeam` that derives the binding
and the real :class:`~ai_assistant.permissions.ThresholdActionPolicy` that rules on it.
What stands in for the provider is the canonical fake ADR-0260 §12 lands beside the
contract; §13's preamble governs assertions about the *forecaster*, and every one of
those is L1's. ``tests/orchestration/forecast_servicing_harness.py`` says why the binder is the
real one.

**Arm (k) is ``test_forecast_outcomes.py``'s** — the classifier, the fold and the
establishment partition each walked totally over their own domain — and arm (h)'s
**turn-level** half, the field a surface reads and the statement beside it, is
``test_engine_forecast.py``'s. What is discharged here is what one servicing does.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final, final

import pytest
from forecast_servicing_harness import (
    FORECAST_DECLARATION,
    GOAL,
    NOW,
    belief,
    binder,
    clock,
    forecast_request,
    forecaster,
    plan,
    servicer,
)
from test_loop_search import _CostedSearcher, _footing, _servicer

from ai_assistant.core.errors import (
    AuditError,
    EgressBindingError,
    MemoryStoreError,
    PermissionDeniedError,
    SecretStoreError,
    ToolBindingError,
)
from ai_assistant.core.types import (
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
    StructuredAsk,
    TimeWindow,
)
from ai_assistant.orchestration import reads
from ai_assistant.orchestration.evidence import (
    as_of_of,
    composed_row,
    records_of,
    requested_of,
    supported_of,
)
from ai_assistant.orchestration.reads import (
    ForecastDisposition,
    ServicedCarriers,
    TurnReadAudit,
    earliest_not_read,
    forecast_contact_of,
    forecast_not_read,
    outbound_statement,
    service_read_request,
)
from ai_assistant.testing import (
    DEFAULT_FORECAST_DAYS,
    FakeActionPolicy,
    FakeAuditTrail,
    FakeFetcher,
    FakeForecaster,
    FakeMemoryStore,
    FakeWebSearcher,
)

if TYPE_CHECKING:
    from datetime import timedelta as TimeDelta  # noqa: N812 — only a type alias

    from ai_assistant.core.protocols import Fetcher, Forecaster
    from ai_assistant.core.types import (
        ForecastOutcome,
        MemoryRecord,
        SourceListing,
        ToolCall,
    )
    from ai_assistant.orchestration.reads import ForecastServicer

_UTTERANCE: Final = "what does the weekend look like"

#: A root the local file ask can be serviced against, for the six-kind order arm.
_ROOT: Final = {"quarter.md": "the quarter went well enough"}


#: How many records a search may put into the fourth group ahead of the forecast.
#: ADR-0231 §5 caps ``search_max_results`` at three, and ADR-0230 §1 caps the file at
#: one, so **four** is the most any deployment can spend before §7's third kind is
#: reached.
_AHEAD: Final = 3


def _spending() -> Any:
    """A search servicing that admits :data:`_AHEAD` records ahead of the forecast.

    §7 services the search **second** and the forecast **third**, so the search is the
    only kind whose yield a case can size. The servicer is ``test_loop_search``'s, over
    the canonical fake at ADR-0231 §5's own ceiling.

    Returns:
        The wired search servicing.
    """
    return _servicer(
        searcher=_CostedSearcher(
            FakeWebSearcher(
                results=tuple(
                    f"A result\nhttps://example.com/{n}\nAbout thing {n}." for n in range(_AHEAD)
                ),
                max_results=_AHEAD,
            )
        ),
        granted=True,
    )


def _searched_ids(serviced: Any) -> set[str]:
    """The ids the **search** minted into this servicing's fourth group.

    Args:
        serviced: The record the servicing wrote.

    Returns:
        Every id whose record the search minted, read off the attestation the search
        stamps with its own source name.
    """
    return {
        one.id
        for one in serviced.records
        if one.provenance.attestation is not None
        and one.provenance.attestation.reported_by != "fake forecast"
    }


def _forecast_ask() -> ReadAsk:
    """The ask, which carries nothing at all (ADR-0260 §3)."""
    return ReadAsk(kind=ReadKind.FORECAST_READ)


async def _service(  # noqa: PLR0913 — one keyword per seam or ask a case varies; the site itself takes one per kind
    *,
    request: ReadRequest | None = None,
    forecast: ForecastServicer | None = None,
    wired: bool = True,
    supply: tuple[MemoryRecord, ...] = (),
    store: Any = None,
    fetcher: Fetcher | None = None,
    listing: SourceListing | None = None,
    search: Any = None,
    audit: TurnReadAudit | None = None,
) -> tuple[ServicedCarriers, TurnReadAudit]:
    """Service one emission at the one site ADR-0260 §7 admits.

    Args:
        request: The emission, defaulting to a forecast ask and nothing else.
        forecast: The wired servicer, defaulting to a configured deployment's.
        wired: ``False`` hands the site **no** servicer at all, which is §8's first
            route to ``NOT_CONFIGURED`` — a caller stating the fact rather than a
            servicer computing it, exactly as ``fetcher`` and ``search`` are.
        supply: The three groups the planner was passed.
        store: The memory store, defaulting to the canonical fake.
        fetcher: The file seam, where a case asks for one.
        listing: The turn's own listing.
        search: The search servicing, where a case needs the budget spent ahead of the
            forecast — §7 puts the search second and the forecast third, so the search
            is the only kind that can leave a slot count the forecast's own clause
            turns on.
        audit: The record, defaulting to a fresh one.

    Returns:
        What the servicing carried back, and the audit it wrote into.
    """
    written = TurnReadAudit() if audit is None else audit
    carried = await service_read_request(
        FakeMemoryStore(now=clock) if store is None else store,
        forecast_request() if request is None else request,
        supply=supply,
        fetcher=fetcher,
        listing=listing,
        search=search,
        forecast=(servicer() if forecast is None else forecast) if wired else None,
        utterance=_UTTERANCE,
        audit=written,
        goal=GOAL,
        plan=plan(),
        footing=None if search is None else _footing(),
    )
    return carried, written


# --------------------------------------------------------------------------- #
# (f) The budget and the order                                                 #
# --------------------------------------------------------------------------- #


async def test_a_servicing_with_one_slot_left_admits_one_day_and_records_the_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§13's arm (f), first case: the slots ahead take all but one, and the cut is recorded.

    §7 states this kind's budget clause over the kind rather than over the union —
    "where the slots remaining when the forecast is reached are fewer than the days
    minted, the servicer admits the records that fit, in the order §5 minted them, and
    admits no more" — and ADR-0226 §6's truncation record is the same list every other
    kind writes to. **Not a second budget and not a share**: the slots here are spent by
    the **search**, which §7 services second, and nothing funds this kind by lowering
    another's.

    **The arm's "nine slots" figure is unreachable at the caps this tree ships**, which
    is why the budget is the value under the test's control rather than the yield. A
    file is capped at one record and a search at three, so at most **four** of ADR-0226
    §6's ten can be spent before the forecast is reached — §7 states this clause "as a
    rule rather than as an impossibility", exactly as ADR-0231 §11 states the search's
    own budget branch, and a case that could only be written by raising a cap ADR-0231
    §5 closes would be testing a different decision. Lowering the **budget** leaves
    every rule this arm is about — the order, the one union, the admit-what-fits and
    the truncation record — running in production code over production values.
    """
    monkeypatch.setattr(reads, "READ_BUDGET", _AHEAD + 1)
    request = ReadRequest(asks=(ReadAsk(kind=ReadKind.WEB_SEARCH), _forecast_ask()))

    carried, audit = await _service(request=request, search=_spending())

    serviced = audit.servicings[-1]
    assert serviced.new == _AHEAD + 1, "the budget was filled"
    minted = [one for one in serviced.records if one.id not in _searched_ids(serviced)]
    assert len(minted) == 1, "one forecast record fitted, and no more were admitted"
    assert serviced.truncated_kinds == (ReadKind.FORECAST_READ,)
    assert serviced.forecast is None, "a read the provider answered records no disposition"
    assert carried.forecast_records == 1, "ADR-0264 §4 counts what entered the supply"


async def test_a_forecast_given_every_remaining_slot_is_not_recorded_as_truncated() -> None:
    """§13's arm (f)'s own control, at the budget ADR-0226 §6 actually ships.

    With the file capped at one and the search at three, a forecast is reached with at
    least six of the ten slots free on every deployment — so its three days all fit and
    the kind is **not** in ``truncated_kinds``. This is what makes the case above
    evidence of the cut rule rather than of the lowered budget, and it is the state a
    real deployment is in.
    """
    request = ReadRequest(asks=(ReadAsk(kind=ReadKind.WEB_SEARCH), _forecast_ask()))

    carried, audit = await _service(request=request, search=_spending())

    serviced = audit.servicings[-1]
    assert serviced.new == _AHEAD + len(DEFAULT_FORECAST_DAYS)
    assert serviced.truncated_kinds == (), "the whole remainder is not a truncation"
    assert carried.forecast_records == len(DEFAULT_FORECAST_DAYS)


async def test_a_forecast_reached_with_no_slot_composes_nothing_and_earns_no_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§13's arm (f), second case: no request, no channel, and **no outcome entry**.

    §7: "where fewer than one slot remains when the forecast is reached, no request is
    composed, no ruling is sought and no channel is opened", and §8's classifier
    "produces **no outcome entry at all** for the ask" — ADR-0251 §2's precedence case
    1, because "a read the budget did not reach is not in it". **A read the budget
    prevented is not a read that found nothing**, and the assertions below are what
    keeps the implementation from conflating them.

    The budget is lowered for the reason the case above records.
    """
    monkeypatch.setattr(reads, "READ_BUDGET", _AHEAD)
    seam = forecaster()
    request = ReadRequest(asks=(ReadAsk(kind=ReadKind.WEB_SEARCH), _forecast_ask()))

    carried, audit = await _service(
        request=request, search=_spending(), forecast=servicer(seam=seam)
    )

    serviced = audit.servicings[-1]
    assert serviced.forecast is ForecastDisposition.NO_BUDGET
    assert serviced.forecast_serviced is True, "the ask was reached; the budget was not"
    assert seam.requested == [], "no request was composed"
    assert seam.read_calls == [], "no channel was opened"
    assert [one.ask.kind for one in carried.yields] == [ReadKind.WEB_SEARCH], (
        "§8's one stated exception: NO_BUDGET earns no entry at all"
    )
    assert carried.forecast_contact is OutboundReach.NOT_REACHED, (
        "§10 places NO_BUDGET in the no-contact group: no channel was opened"
    )
    assert carried.forecast_not_read is ForecastNotRead.UNAVAILABLE


async def test_an_emission_of_all_six_kinds_is_serviced_in_the_stated_order() -> None:
    """§13's arm (f), third case: **all six**, over the whole sequence.

    §7 fixes the order as "local file, then web search, then forecast read, then
    citation hop, then structured read, then sighted query", by ADR-0226 §6's own rule
    and not by preference — the capped read ahead of the uncapped one, with the tiebreak
    that "where two kinds declare the same cap the earlier-admitted kind is serviced
    first". Asserted **over the whole sequence and not only over the kinds ahead of the
    forecast**, so that no later kind can take the slot this one was reached with.

    The search is absent here because no searcher is wired, which is §8's
    ``NOT_CONFIGURED`` — an entry all the same, in its own position, which is exactly
    what makes the ordering assertion cover the kind rather than skip it.
    """
    store = FakeMemoryStore(now=clock)
    cited = belief("cited-1", "the boiler was serviced in march")
    naming = belief("naming-1", "the boiler question", evidence=("cited-1",))
    await store.add(cited)
    await store.add(naming)
    await store.add(
        belief("by-query", "the plumber is booked for tuesday"),
    )
    fetcher = FakeFetcher(_ROOT, read_at=NOW)
    listing = await fetcher.listing()
    request = ReadRequest(
        asks=(
            ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="plumber booked tuesday"),
            ReadAsk(kind=ReadKind.STRUCTURED_READ, structure=StructuredAsk(topics=("boiler",))),
            ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1",)),
            ReadAsk(kind=ReadKind.WEB_SEARCH),
            _forecast_ask(),
            ReadAsk(kind=ReadKind.LOCAL_FILE, entry="F1"),
        )
    )

    carried, _ = await _service(
        request=request, store=store, supply=(naming,), fetcher=fetcher, listing=listing
    )

    assert [one.ask.kind for one in carried.yields] == [
        ReadKind.LOCAL_FILE,
        ReadKind.WEB_SEARCH,
        ReadKind.FORECAST_READ,
        ReadKind.CITATION_HOP,
        ReadKind.STRUCTURED_READ,
        ReadKind.SIGHTED_QUERY,
    ], "§7's order, asserted over the whole emission and not only ahead of the forecast"


# --------------------------------------------------------------------------- #
# (g) The evidence row                                                         #
# --------------------------------------------------------------------------- #


def _regions(carried: ServicedCarriers) -> tuple[Any, ...]:
    """The forecast ask's returned records, as §9 composes ``supported`` from them.

    Args:
        carried: What the servicing carried back.

    Returns:
        The records the forecast ask returned.
    """
    [yielded] = [one for one in carried.yields if one.ask.kind is ReadKind.FORECAST_READ]
    return yielded.records


async def test_the_row_is_composed_with_no_requested_no_record_and_one_region_per_day() -> None:
    """§13's arm (g), over every value ``orchestration`` composes a forecast row from.

    §9 applies ADR-0252 §3 unbent. ``requested`` is composed "from the **typed** part of
    the ask and from nothing else", and ADR-0260 §3 gives this ask **no part at all** —
    so no lane composes one from the configured place, the configured horizon, the
    provider's answer or the days it returned. ``records`` is empty, this kind being on
    ADR-0252 §1's **ephemeral** side, so "a forecast row names no record and its count
    stands alone". ``as_of`` is "the ``Attestation.reported_at`` the provider declared",
    and ``source`` is the forecaster's own ``name`` (§9), which is what makes ADR-0252
    §8's limb 3 finer than the kind. ``supported`` is "one region per record the ask
    returned, composed from that record's own values", its window applied "from the
    record's ``Provenance.attestation.extent`` and from nowhere else" — and **no other
    axis**: a forecast record carries ``topics`` empty, ``about_person`` ``None`` and no
    participants, so each region applies its window and nothing else, and in particular
    none is derived from the configured place, "a fact about where we asked and not
    about what the answer established".

    **Asserted over the assembled row and over every value it is composed from**, which
    are two different failures: a composer that filled ``requested`` and a validator
    that refused the assembly are both caught, and neither catches the other.
    """
    carried, _ = await _service()
    [yielded] = [one for one in carried.yields if one.ask.kind is ReadKind.FORECAST_READ]

    row = composed_row(
        row_id="row-1",
        goal_id=GOAL.goal_id,
        attempt_id="attempt-1",
        ask=yielded.ask,
        outcome=yielded.outcome,
        records=yielded.records,
        admitted=yielded.admitted,
        read_at=NOW,
        source=yielded.source,
    )

    assert row.basis is EvidenceBasis.READ_OUTCOME
    assert row.read_kind is ReadKind.FORECAST_READ
    assert row.requested is None
    assert row.records == (), "ADR-0252 §1's ephemeral side, as ADR-0260 §15 amends it"
    assert row.returned == len(DEFAULT_FORECAST_DAYS)
    assert row.admitted == len(DEFAULT_FORECAST_DAYS)
    assert row.source == "fake forecast"
    assert row.as_of == NOW
    assert row.verdict == ReadOutcomeKind.RETURNED_RECORDS.value
    assert row.standing is EvidenceStanding.STANDING
    assert requested_of(yielded.ask) is None, "the ask has no typed part, so §3 composes none"
    assert records_of(yielded.ask.kind, yielded.records) == (), (
        "ADR-0252 §1's ephemeral side: the count stands alone"
    )
    assert as_of_of(yielded.ask.kind, yielded.records) == NOW, (
        "the instant the provider declared, and no clock of ours"
    )
    assert yielded.source == "fake forecast", "§9's source is the forecaster's own name"
    regions, elided = supported_of(yielded.records)
    assert elided == 0
    assert row.supported == regions, "the row carries exactly what §3 composes"
    assert row.supported_elided == 0
    assert len(regions) == len(DEFAULT_FORECAST_DAYS)
    for region, record in zip(regions, yielded.records, strict=True):
        attestation = record.provenance.attestation
        assert attestation is not None
        extent = attestation.extent
        assert extent is not None
        assert region.window == TimeWindow(start=extent.extends_from, end=extent.extends_until), (
            "the window is the day the provider stated, and nothing else"
        )
        assert region.participants is None
        assert region.topics is None
        assert region.about_person is None


async def test_three_returned_and_one_admitted_still_writes_three_regions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§13's arm (g)'s own stated case: ``supported`` is composed from what **returned**.

    "A servicing returning three records of which the budget admits one still writes
    three regions", because ADR-0252 §2 composes ``supported`` from what the read
    returned rather than from what the supply took — and §13's own arm over
    ``ForecastOutcome``'s boundaries already refuses a record with no extent at
    construction, so no forecast servicing can present one.
    """

    monkeypatch.setattr(reads, "READ_BUDGET", _AHEAD + 1)
    request = ReadRequest(asks=(ReadAsk(kind=ReadKind.WEB_SEARCH), _forecast_ask()))

    carried, audit = await _service(request=request, search=_spending())

    returned = _regions(carried)
    assert len(returned) == 3, "the ask returned three days"
    assert audit.servicings[-1].truncated_kinds == (ReadKind.FORECAST_READ,)
    assert carried.forecast_records == 1, "one entered the supply"
    regions, elided = supported_of(returned)
    assert len(regions) == 3, "three regions, from what returned and not from what fitted"
    assert elided == 0


# --------------------------------------------------------------------------- #
# (h) The statement and the contact, at the servicing site                     #
# --------------------------------------------------------------------------- #


async def test_a_read_the_provider_answered_carries_no_member_and_a_contact() -> None:
    """§13's arm (h), first case: ``None`` and a contact at ``FORECAST_PROVIDER``.

    §10's thirteenth case — "a forecast read establishes an outbound contact where its
    call completed and recorded no ``ForecastDisposition``" — and §8's rule that such a
    read records none at all, which is what makes ``None`` mean *answered* here rather
    than *never asked*.
    """
    carried, audit = await _service()

    assert audit.servicings[-1].forecast is None
    assert carried.forecast_not_read is None
    assert carried.forecast_contact is OutboundReach.REACHED
    statement = outbound_statement(
        search=None, forecast=carried.forecast_contact, egress=None, records=3, composes=True
    )
    assert statement is not None
    assert statement.destinations == (OutboundDestination.FORECAST_PROVIDER,)


async def test_a_read_refused_before_the_send_carries_the_member_and_no_class() -> None:
    """§13's arm (h), second case: the folded member, its statement, **no** destination.

    A ``CONFIRM`` at the ruling is a stage before the send: §11 mints no park for this
    kind, so the read "is recorded, is not made, is not parked", and §10 places the
    member on the no-contact side. Driven through a deployment that configured no
    forecast pair, which is §6's fail-closed direction — route (c) is unreachable and
    the ruling is what ``origin/main`` gives an unconfigured destination.
    """
    seam = forecaster()

    carried, audit = await _service(forecast=servicer(seam=seam, configured=False))

    assert audit.servicings[-1].forecast is ForecastDisposition.RULING_CONFIRM
    assert carried.forecast_not_read is ForecastNotRead.AUTHORISATION_AWAITED
    assert carried.forecast_contact is OutboundReach.NOT_REACHED
    assert seam.read_calls == [], "nothing was sent"
    statement = outbound_statement(
        search=None, forecast=carried.forecast_contact, egress=None, records=0, composes=True
    )
    assert statement is not None
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == ()


@pytest.mark.parametrize(
    "refusal",
    [
        ForecastRefusal.TRANSPORT_FAILED,
        ForecastRefusal.DEADLINE_EXPIRED,
        ForecastRefusal.PROVIDER_REFUSED,
    ],
)
async def test_each_indeterminate_refusal_carries_nothing_either_way(
    refusal: ForecastRefusal,
) -> None:
    """§13's arm (h), third case, **asserted separately** for each of the three.

    "A transport failure, a deadline expiry and a ``PROVIDER_REFUSED`` each carry
    ``INDETERMINATE`` with ``destinations`` empty, asserted separately so that none can
    regress to ``REACHED`` or ``NOT_REACHED`` while the others hold." §10 takes the
    least-claiming direction deliberately, and ADR-0264 §1 ranks silence above a false
    claim.
    """
    carried, audit = await _service(forecast=servicer(seam=forecaster(refusal=refusal)))

    assert audit.servicings[-1].forecast is ForecastDisposition(refusal.value)
    assert carried.forecast_contact is OutboundReach.INDETERMINATE
    statement = outbound_statement(
        search=None, forecast=carried.forecast_contact, egress=None, records=0, composes=True
    )
    assert statement is not None
    assert statement.reach is OutboundReach.INDETERMINATE
    assert statement.destinations == ()


def test_provider_refused_establishes_nothing_over_both_of_its_causes() -> None:
    """§13's arm (h)'s "**over both its causes**", and the arm it inherits.

    §10 records ``PROVIDER_REFUSED`` for **a response the provider gave and this system
    refused** and for **ADR-0148 §6's pre-transmit refusal**, "whose limbs discard the
    credential and open no channel" — and "**it carries no value separating them**", so
    a site holding it cannot tell whether octets arrived. The member is therefore one
    value with one classification: reading it as a response at one seam and as a
    non-send at another "is what ADR-0264 §13's third arm exists to catch", and this
    asserts that the classification is a property of the member and not of the path
    that produced it.
    """
    assert forecast_contact_of(ForecastDisposition.PROVIDER_REFUSED) is (
        OutboundReach.INDETERMINATE
    )
    assert forecast_not_read(ForecastDisposition.PROVIDER_REFUSED) is ForecastNotRead.UNAVAILABLE


@pytest.mark.parametrize(
    "refusal",
    [ForecastRefusal.RESPONSE_TOO_LARGE, ForecastRefusal.UNATTESTED],
)
async def test_octets_that_arrived_carry_unavailable_and_a_contact(
    refusal: ForecastRefusal,
) -> None:
    """§13's arm (h)'s fifth case, **asserted separately** for each of the two.

    "``RESPONSE_TOO_LARGE`` and ``UNATTESTED`` each carry ``UNAVAILABLE`` with
    ``FORECAST_PROVIDER`` ``REACHED``", because §10 classes both as reached from octets
    this system took off the channel — "either folded to ``INDETERMINATE`` would deny a
    contact the trail recorded". **A contact and an ``UNAVAILABLE`` ride together where
    both hold**, which is ADR-0264 §8's both-statements rule and not an exception to it.
    """
    carried, audit = await _service(forecast=servicer(seam=forecaster(refusal=refusal)))

    assert audit.servicings[-1].forecast is ForecastDisposition(refusal.value)
    assert carried.forecast_not_read is ForecastNotRead.UNAVAILABLE
    assert carried.forecast_contact is OutboundReach.REACHED


@final
class _RefusingBinding:
    """A forecaster whose ``read`` raises, standing for §6's three pre-execution checks.

    §6 makes :meth:`~ai_assistant.core.protocols.Forecaster.read` perform ADR-0029 §2's
    three checks itself and raise ``ToolBindingError`` at any of them, "before any
    credential is read and any channel is opened". **Which check fired, and that the
    production forecaster fires them in that order, is ADR-0260 §13's arm (c) and is
    L1's**; what this arm is about is the sentence that follows — such a failure "**is
    recorded by the servicing as** ``BINDING_FAILED``" — so the subject here is the
    servicing and the seam is scripted to reach it.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: Forecaster) -> None:
        """Wrap a forecaster whose ``request`` answers normally.

        Args:
            inner: The forecaster to propose through.
        """
        self._inner = inner

    @property
    def name(self) -> str:
        """The wrapped source's own identity."""
        return self._inner.name

    async def request(self) -> Any:
        """Propose exactly what the wrapped forecaster proposes.

        Returns:
            The proposal.
        """
        return await self._inner.request()

    async def read(self, call: ToolCall, /, *, timeout: TimeDelta) -> ForecastOutcome:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1); this stands in for the production forecaster and carries its signature
        """Refuse the call the way §6's three checks refuse one.

        Args:
            call: The authorised call, which this never reads.
            timeout: The bound, which this never reaches.

        Raises:
            ToolBindingError: Always.
        """
        _ = call, timeout
        msg = "this call does not survive revalidation (ADR-0029 §2, ADR-0260 §6)"
        raise ToolBindingError(msg)


async def test_a_refused_pre_execution_check_is_recorded_and_establishes_no_contact() -> None:
    """§13's arm (h)'s last case, asserted through to the servicing's carriers.

    "§6's three pre-execution checks are asserted through to the turn: ``BINDING_FAILED``
    in the audit, ``UNAVAILABLE`` in ``forecast_not_read``, and **no** contact, because a
    path recording nothing would leave §10's ``None`` saying the provider answered."
    The last clause is the whole reason the raise is a **decline** here and not ADR-0226
    §5's degradation: a degraded servicing carries no disposition, and an absent
    disposition is §10's *answered* case.
    """
    seam = _RefusingBinding(forecaster())

    carried, audit = await _service(forecast=servicer(seam=seam))

    assert audit.servicings[-1].forecast is ForecastDisposition.BINDING_FAILED
    assert audit.servicings[-1].failed is False, "a decline is not a degradation"
    assert carried.forecast_not_read is ForecastNotRead.UNAVAILABLE
    assert carried.forecast_contact is OutboundReach.NOT_REACHED


def test_a_denied_read_outranks_a_later_failure_in_both_encounter_orders() -> None:
    """§13's arm (h)'s revising case: ``DECLINED`` in **both** orders, and after a yield.

    §10 declares the members "in precedence order" and applies ADR-0242 §7's rule at
    this seam unchanged: the field carries "the **earliest-declared** member any
    servicing of the turn recorded". **The order and not the encounter order decides
    it**, which is why both directions are asserted — an implementation carrying the
    last member it computed passes one of them and an implementation assigning only
    while the carrier is ``None`` passes the other.

    "**A later read does not clear an earlier one's member**: a turn that was denied and
    then answered still reports ``DECLINED``, because the user was told about a read
    this turn did not make and a second read does not unmake it."
    """
    denied = ForecastNotRead.DECLINED
    failed = ForecastNotRead.UNAVAILABLE

    assert earliest_not_read(earliest_not_read(None, denied), failed) is denied
    assert earliest_not_read(earliest_not_read(None, failed), denied) is denied
    assert earliest_not_read(earliest_not_read(None, denied), None) is denied, (
        "an answered second read clears nothing"
    )


# --------------------------------------------------------------------------- #
# (l) Two seams, one statement                                                 #
# --------------------------------------------------------------------------- #


def test_a_turn_that_reached_both_providers_names_both_classes_once() -> None:
    """§13's arm (l): **one** statement, **both** classes, in §10's stated order.

    "An implementation overwriting ``SEARCH_PROVIDER`` with ``FORECAST_PROVIDER`` would
    deny a contact the trail recorded, which is the asymmetry §10 exists to close."
    ADR-0264 §4 makes the classes a **set of kinds** rather than an enumeration of
    servicings, and §5's declared order is what the statement renders in — asserted here
    and validated again on the model, so the two cannot come apart.
    """
    both = outbound_statement(
        search=OutboundReach.REACHED,
        forecast=OutboundReach.REACHED,
        egress=None,
        records=4,
        composes=True,
    )

    assert both is not None
    assert both.reach is OutboundReach.REACHED
    assert both.destinations == (
        OutboundDestination.SEARCH_PROVIDER,
        OutboundDestination.FORECAST_PROVIDER,
    )
    assert both.records == 4, "one population over the turn, and not one count per class"


@pytest.mark.parametrize(
    ("search", "forecast", "expected"),
    [
        (OutboundReach.REACHED, None, (OutboundDestination.SEARCH_PROVIDER,)),
        (None, OutboundReach.REACHED, (OutboundDestination.FORECAST_PROVIDER,)),
        (
            OutboundReach.NOT_REACHED,
            OutboundReach.REACHED,
            (OutboundDestination.FORECAST_PROVIDER,),
        ),
        (
            OutboundReach.REACHED,
            OutboundReach.INDETERMINATE,
            (OutboundDestination.SEARCH_PROVIDER,),
        ),
    ],
)
def test_each_class_is_named_from_its_own_seams_answer(
    search: OutboundReach | None,
    forecast: OutboundReach | None,
    expected: tuple[OutboundDestination, ...],
) -> None:
    """§13's arm (l)'s converse: a class is named by **its own** seam and no other.

    ADR-0264 §3 as ADR-0260 §15 amends it — "each kind's contact is established by its
    own call" — so a search that reached names no forecast provider and a forecast that
    reached names no search provider, whatever the other seam did. The fourth row is the
    one an implementation naming every class on a ``REACHED`` fold fails.

    Args:
        search: What the turn's searches established.
        forecast: What its forecast reads established.
        expected: The classes the statement names.
    """
    statement = outbound_statement(
        search=search, forecast=forecast, egress=None, records=1, composes=True
    )

    assert statement is not None
    assert statement.destinations == expected


# --------------------------------------------------------------------------- #
# (m) The carried external-content fact                                        #
# --------------------------------------------------------------------------- #


@final
class _CapturingBinder:
    """A binding seam that records the ``CarriedProvenance`` it was handed.

    §13's arm (m) is stated "over the binding itself", and the value the servicing
    **wrote** is what that clause is about: "an implementation inspecting only the
    first passes every other arm while writing ``False``". So this wraps the real seam
    rather than replacing it — the binding the policy then rules on is the one
    ``EgressBindingSeam`` derived.
    """

    __slots__ = ("_inner", "carried")

    def __init__(self, inner: Any) -> None:
        """Wrap one seam.

        Args:
            inner: The real binding seam.
        """
        self._inner = inner
        self.carried: list[Any] = []

    async def bind(self, tool: Any, *, parameters: Any, provenance: Any) -> Any:
        """Record the carrier and derive through the real seam.

        Args:
            tool: The declaration to bind.
            parameters: Its arguments.
            provenance: The carrier ``orchestration`` built.

        Returns:
            Whatever the real seam derived.
        """
        self.carried.append(provenance)
        return await self._inner.bind(tool, parameters=parameters, provenance=provenance)

    async def rebind(self, tool: Any, *, parameters: Any, approved: Any) -> Any:
        """Rebind through the real seam, which no forecast read reaches (ADR-0260 §11).

        Args:
            tool: The declaration.
            parameters: Its arguments.
            approved: The approved binding.

        Returns:
            Whatever the real seam derived.
        """
        return await self._inner.rebind(tool, parameters=parameters, approved=approved)


async def test_an_external_record_this_servicing_contributed_reaches_the_binding() -> None:
    """§13's arm (m): the fact is a disjunction over the supply **and** the servicing.

    §7 computes ``planned_with_external_content`` "over the turn's pre-servicing supply
    **and** over every record this servicing has already contributed", at the moment the
    request is built. Here the pre-servicing supply carries **no** external record and a
    read serviced **ahead** of the forecast contributes one, so the binding carries
    ``True`` — and "an implementation inspecting only the first passes every other arm
    while writing ``False``".

    The contributing read is the **local file**, which ADR-0230 §5 makes always
    ``EXTERNAL`` and §7 serviced first. A web search would serve equally; the file needs
    no second egress seam wired to make the point.
    """
    capturing = _CapturingBinder(binder(FORECAST_DECLARATION))
    fetcher = FakeFetcher(_ROOT, read_at=NOW)
    listing = await fetcher.listing()
    request = ReadRequest(asks=(ReadAsk(kind=ReadKind.LOCAL_FILE, entry="F1"), _forecast_ask()))

    carried, audit = await _service(
        request=request,
        forecast=servicer(binding=capturing),
        fetcher=fetcher,
        listing=listing,
        supply=(),
    )

    [provenance] = capturing.carried
    assert provenance.planned_with_external_content is True, (
        "the fetched file is in view, so §7's disjunction is True at the moment "
        "the request is built"
    )
    assert provenance.forecast_reach is True, "§11's fact, written exactly here"
    assert provenance.closed_loop is False, "closed_loop still means this deployment's search"
    assert audit.servicings[-1].forecast is None, "and the read still ran"
    assert carried.forecast_contact is OutboundReach.REACHED


async def test_a_supply_carrying_nothing_external_builds_a_binding_carrying_false() -> None:
    """§13's arm (m)'s own control: the fact is computed and never defaulted ``True``.

    ADR-0181 §4's value is a fact about an act this system performed, so a turn whose
    supply holds nothing external and whose servicing has contributed nothing external
    carries ``False`` — which is what makes the ``True`` above evidence of the
    disjunction rather than of a constant.
    """
    capturing = _CapturingBinder(binder(FORECAST_DECLARATION))

    await _service(forecast=servicer(binding=capturing), supply=(belief("b-1", "a held thing"),))

    [provenance] = capturing.carried
    assert provenance.planned_with_external_content is False


# --------------------------------------------------------------------------- #
# (n) The contact that outlives the servicing                                  #
# --------------------------------------------------------------------------- #


@final
class _RaisingAfterTheForecast:
    """A store whose ``search`` raises, so the **sighted query** fails the servicing.

    §7 services the sighted query **last**, so a store that raises there fails a
    servicing whose forecast has already been performed — which is the shape §13's arm
    (n) is stated over.
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
        """Fail the servicing, after the forecast has been serviced.

        Args:
            *args: Ignored.
            **kwargs: Ignored.

        Raises:
            MemoryStoreError: Always.
        """
        _ = args, kwargs
        msg = "the store went away after the forecast was read"
        raise MemoryStoreError(msg)


async def _serviced_then_raised(
    *, seam: Forecaster | None = None
) -> tuple[ServicedCarriers, TurnReadAudit]:
    """A servicing whose forecast runs and whose later sighted query then raises.

    Args:
        seam: The forecaster, defaulting to a configured deployment's.

    Returns:
        What the degraded servicing carried back, and the audit it wrote.
    """
    request = ReadRequest(
        asks=(_forecast_ask(), ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="anything"))
    )
    return await _service(
        request=request,
        store=_RaisingAfterTheForecast(FakeMemoryStore(now=clock)),
        forecast=servicer(seam=forecaster() if seam is None else seam),
    )


async def test_a_contact_survives_a_servicing_that_later_raised() -> None:
    """§13's arm (n), first case: ``REACHED``, ``records`` ``0``, ``None``.

    "ADR-0226 §5 discarded the servicing's records, and §10's quoted clause — *nothing
    that happens to the enclosing servicing afterwards unmakes it* — is what survives
    them." An implementation computing the fact off the **ended servicing** rather than
    at the performing site passes every other arm here and fails this one.
    """
    carried, audit = await _serviced_then_raised()

    serviced = audit.servicings[-1]
    assert serviced.failed is True
    assert serviced.records == (), "ADR-0226 §5 leaves the supply as planning saw it"
    assert carried.forecast_contact is OutboundReach.REACHED
    assert carried.forecast_records == 0, "a failed servicing entered nothing"
    assert carried.forecast_not_read is None, "the provider answered"
    assert serviced.forecast_serviced is True, "and the ask was reached"


async def test_an_unattested_read_before_the_failure_carries_the_contact_and_the_member() -> None:
    """§13's arm (n), second case: the contact **and** ``UNAVAILABLE``.

    "The same servicing having recorded ``UNATTESTED`` **before** that later failure
    carries the contact **and** ``UNAVAILABLE``" — ADR-0264 §8's both-statements rule
    riding out on a record ADR-0226 §5 emptied.
    """
    carried, audit = await _serviced_then_raised(
        seam=forecaster(refusal=ForecastRefusal.UNATTESTED)
    )

    assert audit.servicings[-1].failed is True
    assert audit.servicings[-1].forecast is ForecastDisposition.UNATTESTED
    assert carried.forecast_contact is OutboundReach.REACHED
    assert carried.forecast_not_read is ForecastNotRead.UNAVAILABLE
    assert carried.forecast_records == 0


async def test_a_servicing_that_raised_before_the_forecast_carries_no_contact() -> None:
    """§13's arm (n), third case: **no** contact and ``None``, having opened no channel.

    The pair §10 says no site can tell apart from the ended servicing's record — an
    absent disposition covers both a read that was answered and a servicing that never
    reached its forecast — which is why the fact is computed at the performing site and
    carried, and why ``forecast_serviced`` is the field that separates them in the
    audit.

    The **local file** is serviced ahead of the forecast (§7), so a fetcher that raises
    there fails the servicing before the forecast is reached.
    """
    seam = forecaster()
    fetcher = _RaisingFetcher()
    request = ReadRequest(asks=(ReadAsk(kind=ReadKind.LOCAL_FILE, entry="F1"), _forecast_ask()))

    carried, audit = await _service(
        request=request,
        forecast=servicer(seam=seam),
        fetcher=fetcher,
        listing=await FakeFetcher(_ROOT, read_at=NOW).listing(),
    )

    serviced = audit.servicings[-1]
    assert serviced.failed is True
    assert serviced.forecast is None
    assert serviced.forecast_serviced is False, "the forecast was never reached"
    assert carried.forecast_contact is None, "no call was performed"
    assert carried.forecast_not_read is None
    assert seam.requested == [], "no request was composed and no channel was opened"
    assert seam.read_calls == []


@final
class _RaisingFetcher:
    """A ``Fetcher`` whose ``fetch`` raises, failing a servicing at its **first** kind."""

    __slots__ = ()

    @property
    def name(self) -> str:
        """This fetcher's identity."""
        return "raising fetcher"

    async def listing(self) -> Any:
        """Never reached: the loop passes the listing it already read.

        Raises:
            MemoryStoreError: Always.
        """
        msg = "the root went away"
        raise MemoryStoreError(msg)

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


# --------------------------------------------------------------------------- #
# §8's producer paths, and the mark a failing stage leaves behind              #
# --------------------------------------------------------------------------- #
#
# §13's enumeration "is a floor and not a ceiling", and "a lane adds the arm a normative
# clause needs whether or not that clause is listed here". §8 requires **each member to
# name the stage that produced it**, so a servicing that reported one stage's outcome
# under another stage's member would breach a clause with no lettered arm above it —
# and the vocabulary's own tests cannot catch it, feeding already-constructed members
# into the downstream tables rather than driving the branches that mint them.


@final
class _RaisingBinder:
    """A binding seam that raises what ADR-0152 §1 contracts (``EgressBindingError``)."""

    __slots__ = ()

    async def bind(self, tool: Any, *, parameters: Any, provenance: Any) -> Any:
        """Refuse by raising.

        Args:
            tool: The declaration, never read.
            parameters: Its arguments, never read.
            provenance: The carrier, never read.

        Raises:
            EgressBindingError: Always.
        """
        _ = tool, parameters, provenance
        msg = "this deployment's forecast registration could not be derived"
        raise EgressBindingError(msg)

    async def rebind(self, tool: Any, *, parameters: Any, approved: Any) -> Any:
        """Never reached: ADR-0260 §11 rebinds no forecast binding.

        Args:
            tool: The declaration.
            parameters: Its arguments.
            approved: The approved binding.

        Raises:
            EgressBindingError: Always.
        """
        _ = tool, parameters, approved
        msg = "no forecast binding is ever rebound (ADR-0260 §11)"
        raise EgressBindingError(msg)


@final
class _RaisingPolicy:
    """An ``ActionPolicy`` whose ``decide`` raises — §8's ``RULING_UNAVAILABLE``, limb 1."""

    __slots__ = ()

    async def decide(self, request: Any) -> Any:
        """Raise rather than rule.

        Args:
            request: The request, never read.

        Raises:
            PermissionDeniedError: Always.
        """
        _ = request
        msg = "the policy could not be consulted"
        raise PermissionDeniedError(msg)

    async def resolve(self, decision: Any, *, approved: bool) -> Any:
        """Never reached on this path.

        Args:
            decision: The decision.
            approved: The answer.

        Raises:
            PermissionDeniedError: Always.
        """
        _ = decision, approved
        msg = "no forecast decision is resolved (ADR-0260 §11)"
        raise PermissionDeniedError(msg)


@final
class _RaisingTrail:
    """A trail whose ``record`` raises — §8's ``RULING_UNAVAILABLE``, limb 2."""

    __slots__ = ("_inner",)

    def __init__(self) -> None:
        """Delegate every member but the append."""
        self._inner = FakeAuditTrail()

    def __getattr__(self, name: str) -> Any:
        """Delegate what this class does not name.

        Args:
            name: The member being reached for.

        Returns:
            The wrapped trail's member.
        """
        return getattr(self._inner, name)

    async def record(self, decision: Any) -> str:
        """Refuse the append.

        Args:
            decision: The decision to record.

        Raises:
            AuditError: Always.
        """
        _ = decision
        msg = "the append was refused"
        raise AuditError(msg)


@final
class _LosingTrail:
    """A trail that accepts the append and hands nothing back (§8's second limb).

    ADR-0192 §1 keys a seam's own claim on the decision the store holds under that id,
    so a trail that accepted a write and lost it would have the servicing open a channel
    under a decision nothing holds. §8 resolves it to ``RULING_UNAVAILABLE`` rather than
    letting the send proceed.
    """

    __slots__ = ("_inner",)

    def __init__(self) -> None:
        """Delegate every member but the read-back."""
        self._inner = FakeAuditTrail()

    def __getattr__(self, name: str) -> Any:
        """Delegate what this class does not name.

        Args:
            name: The member being reached for.

        Returns:
            The wrapped trail's member.
        """
        return getattr(self._inner, name)

    async def get(self, decision_id: str) -> None:
        """Answer that the trail holds nothing under this id.

        Args:
            decision_id: The id just written.
        """
        _ = decision_id


#: The one row that wires **no** servicer at all — §8's first route to
#: ``NOT_CONFIGURED``, which is a caller stating the fact rather than a servicer
#: computing it, exactly as ``fetcher`` and ``search`` are.
_UNWIRED: Final = "unwired"


def _producers() -> list[tuple[str, dict[str, Any], ForecastDisposition, ForecastNotRead]]:
    """Every branch of :meth:`ForecastServicer.service` that mints a disposition.

    One row per **stage** §8 names, because §8's whole discipline is that "each member
    names the stage that produced it": a servicing reporting one stage's outcome under
    another's would satisfy every mapping test above and still be wrong.

    Returns:
        The label, the servicer's knobs, the member §8 gives that stage, and the member
        §10 folds it to.
    """
    unregistered = FORECAST_DECLARATION.model_copy(update={"id": "forecast.unregistered"})
    return [
        (
            # §8's first route: no forecaster is wired into the loop at all. Driven
            # through the servicing site, which is where the `None` is answered.
            _UNWIRED,
            {},
            ForecastDisposition.NOT_CONFIGURED,
            ForecastNotRead.NOT_CONFIGURED,
        ),
        (
            # §4's second route: a wired forecaster whose `request` answers `None`
            # because the four-field registration is absent — "a configuration fact and
            # never a failure". The fake carries **no cost pair** here, which is its own
            # shape of ADR-0236 §2's registration-whole refusal rather than a knob this
            # case chose: a per-call figure for a forecaster that proposes nothing is a
            # value nothing reads.
            "proposes_nothing",
            {"seam": FakeForecaster(reported_at=NOW, origin=None)},
            ForecastDisposition.NOT_CONFIGURED,
            ForecastNotRead.NOT_CONFIGURED,
        ),
        (
            # ADR-0152 §9's `None`: the seam holds no registration for this declaration,
            # which for the one integration §6 registers is a mis-wiring and is
            # fail-closed — "a forecast sent under no binding is a send to a destination
            # no policy ruled on".
            "binder_holds_no_registration",
            {"binding": binder(unregistered)},
            ForecastDisposition.BINDING_FAILED,
            ForecastNotRead.UNAVAILABLE,
        ),
        (
            "binder_raises",
            {"binding": _RaisingBinder()},
            ForecastDisposition.BINDING_FAILED,
            ForecastNotRead.UNAVAILABLE,
        ),
        (
            # §8's own member for a policy the operator set against this read.
            "ruling_deny",
            {"policy": FakeActionPolicy(deny_at=RiskLevel.LOW)},
            ForecastDisposition.RULING_DENY,
            ForecastNotRead.DECLINED,
        ),
        (
            "policy_raises",
            {"policy": _RaisingPolicy()},
            ForecastDisposition.RULING_UNAVAILABLE,
            ForecastNotRead.UNAVAILABLE,
        ),
        (
            "trail_refuses_the_append",
            {"trail": _RaisingTrail()},
            ForecastDisposition.RULING_UNAVAILABLE,
            ForecastNotRead.UNAVAILABLE,
        ),
        (
            "trail_hands_nothing_back",
            {"trail": _LosingTrail()},
            ForecastDisposition.RULING_UNAVAILABLE,
            ForecastNotRead.UNAVAILABLE,
        ),
    ]


@pytest.mark.parametrize(
    ("label", "knobs", "disposition", "member"),
    [pytest.param(one[0], one[1], one[2], one[3], id=one[0]) for one in _producers()],
)
async def test_each_stage_records_its_own_member_and_opens_no_channel(
    label: str,
    knobs: dict[str, Any],
    disposition: ForecastDisposition,
    member: ForecastNotRead,
) -> None:
    """Every branch §8 names as a decline, driven over the production servicing.

    **Each member names the stage that produced it** (§8), so this asserts the exact
    member per stage rather than that *some* decline happened — a servicing collapsing
    two stages onto one member passes every mapping test in
    ``test_forecast_outcomes.py`` and fails here.

    **And no channel is opened on any of them** (§7's "bind, then rule, then record,
    then send": "no channel is opened before a recorded ``ALLOW`` exists"). Asserted
    over the seam's own record of calls rather than over the absence of records,
    because a read that was made and yielded nothing looks identical in the counts.

    Args:
        label: Which stage this row drives.
        knobs: What this row replaces on the servicer.
        disposition: The member §8 gives that stage.
        member: The member §10 folds it to.
    """
    seam = knobs.get("seam", forecaster())

    carried, audit = await _service(
        forecast=None if label == _UNWIRED else servicer(**{**knobs, "seam": seam}),
        wired=label != _UNWIRED,
    )

    serviced = audit.servicings[-1]
    assert serviced.forecast is disposition
    assert serviced.forecast_serviced is True, "the ask reached the forecast stage"
    assert serviced.failed is False, "a decline is not a degradation (ADR-0226 §5)"
    assert carried.forecast_not_read is member
    assert carried.forecast_contact is OutboundReach.NOT_REACHED, (
        "§10 places every stage before the send on the no-contact side"
    )
    assert carried.forecast_records == 0
    assert seam.read_calls == [], "no channel was opened before a recorded ALLOW"


@final
class _FaultingForecaster:
    """A forecaster whose ``read`` raises a fault §8 gives no member (ADR-0226 §5).

    ADR-0260 §8 closes its vocabulary at twelve with **no member for a fault at the
    send** — ``SearchDisposition.SEARCH_FAILED`` has no forecast twin and §12 forbids a
    lane adding one — so the ratified answer is the all-or-nothing degradation, which
    is what this case drives. §6's three pre-execution checks are **not** this: those
    raise ``ToolBindingError`` and are recorded as ``BINDING_FAILED``, which
    :class:`_RefusingBinding` above drives.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: Forecaster) -> None:
        """Wrap a forecaster whose ``request`` answers normally.

        Args:
            inner: The forecaster to propose through.
        """
        self._inner = inner

    @property
    def name(self) -> str:
        """The wrapped source's own identity."""
        return self._inner.name

    async def request(self) -> Any:
        """Propose exactly what the wrapped forecaster proposes.

        Returns:
            The proposal.
        """
        return await self._inner.request()

    async def read(self, call: ToolCall, /, *, timeout: TimeDelta) -> ForecastOutcome:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1); this stands in for the production forecaster and carries its signature
        """Raise a fault no ``ForecastRefusal`` member names.

        Args:
            call: The authorised call.
            timeout: The bound.

        Raises:
            SecretStoreError: Always — the credential slot could not be read, which is
                a fault and not a source reason.
        """
        _ = call, timeout
        msg = "the credential slot could not be read"
        raise SecretStoreError(msg)


async def test_a_fault_raised_by_the_forecast_stage_still_records_that_the_ask_was_put() -> None:
    """ADR-0260 §7's first audit field, over the one servicing that makes it earn its keep.

    §8 closes the vocabulary at twelve with no member for a fault at the send, so a
    forecaster that raises one degrades the turn (ADR-0226 §5) and the record carries
    **no disposition**. An absent disposition is §10's *answered* case, so without the
    boolean beside it this turn would be indistinguishable in the audit from one whose
    planner never asked for a forecast — which is the collapse §7's pair exists to
    close, and it closes only if the mark is taken **before** the stage is awaited.

    Everything else is ADR-0226 §5 unchanged: the supply is left as planning saw it,
    every count is zero, ``failed`` is true, and nothing raises out of the turn.
    """
    seam = _FaultingForecaster(forecaster())

    carried, audit = await _service(forecast=servicer(seam=seam))

    serviced = audit.servicings[-1]
    assert serviced.failed is True, "ADR-0226 §5's degradation, not a decline"
    assert serviced.forecast is None, "§8 gives a fault at the send no member"
    assert serviced.forecast_serviced is True, (
        "and the boolean is what says the ask was put to the seam all the same"
    )
    assert serviced.records == ()
    assert serviced.new == 0
    assert carried.forecast_not_read is None
    assert carried.forecast_contact is None, "no outcome was read, so nothing either way"
    assert carried.forecast_records == 0


async def test_a_cancellation_inside_the_forecast_stage_leaves_the_same_mark() -> None:
    """The second half of the clause above: a cancellation carries the frame away.

    ADR-0060 lets a ``CancelledError`` pass through untouched — it is a
    ``BaseException`` and neither handler in ``service_read_request`` catches it — so
    ADR-0226 §9's record is written from the ``finally`` on a path that returned nothing
    at all. A mark taken from the returned value would be ``False`` there; taken before
    the await it is ``True``, which is what the record needs to say of a turn whose
    forecast was genuinely begun.

    **The record is still written, and it is still honest** (ADR-0226 §9's "one record,
    on every path out of this function — the completed servicing, the degraded one, and
    the one a cancellation carried away").
    """
    seam = forecaster()
    audit = TurnReadAudit()
    suspension = seam.suspend_next()
    servicing = asyncio.ensure_future(_service(forecast=servicer(seam=seam), audit=audit))
    await suspension.reached()

    servicing.cancel()
    # The suspension **defers** a cancellation rather than absorbing it (ADR-0054's
    # `_run_to_completion` in miniature), so the read is released to finish its own work
    # and the cancellation is re-raised after it — which is the shape a real seam holding
    # a resource has, and is why the record below is written from the `finally` rather
    # than lost with the frame.
    suspension.release()
    with pytest.raises(asyncio.CancelledError):
        await servicing

    serviced = audit.servicings[-1]
    assert serviced.failed is True, "the servicing did not complete"
    assert serviced.forecast is None, "no outcome was read"
    assert serviced.forecast_serviced is True, (
        "the ask was put to the seam, which is what the mark taken before the await says"
    )
    assert serviced.records == ()
