"""ADR-0260's ``core`` vocabularies and what ``ForecastOutcome`` refuses.

§13's arm (j) whole, the model half of its arm (b-prime), and the closures the three
enumerations carry. What a *forecaster* owes over its own output — the confidence, the
``derived_from_external``, the placement and the ``reported_by`` equality — is the
producer's rather than this value's (§4), and lives in ``tests/tools/test_forecast.py``
where a production forecaster can be driven.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    Attestation,
    BoundAccount,
    CarriedProvenance,
    DiscloserProvenance,
    EgressBinding,
    EgressSpan,
    ForecastNotRead,
    ForecastOutcome,
    ForecastRefusal,
    MemoryRecord,
    MemorySource,
    OutboundDestination,
    Placement,
    Provenance,
    ReportedExtent,
    SemanticMemory,
    SpanCoverage,
    TurnOutcome,
    Validity,
)

#: The instant the provider's response declared, which every record below is attested
#: to (ADR-0260 §5, ADR-0092 §3).
_REPORTED_AT: Final = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

#: The day one record is about, as the provider's own declared offset places it.
_EXTENT: Final = ReportedExtent(
    extends_from=datetime(2026, 9, 4, 23, 0, tzinfo=UTC),
    extends_until=datetime(2026, 9, 5, 23, 0, tzinfo=UTC),
)

#: The source instance every record below is attested to.
_SOURCE: Final = "forecast"


def _record(**overrides: Any) -> MemoryRecord:
    """One record ADR-0260 §5 would have minted, with ``overrides`` applied.

    Args:
        overrides: Fields to replace, so that each case names the one clause it breaks
            and nothing else.

    Returns:
        The record.
    """
    provenance_overrides = overrides.pop("provenance", {})
    attestation_overrides = provenance_overrides.pop("attestation", {})
    attestation = (
        None
        if attestation_overrides is None
        else Attestation(
            **{
                "reported_by": _SOURCE,
                "reported_at": _REPORTED_AT,
                "extent": _EXTENT,
                **attestation_overrides,
            }
        )
    )
    provenance = Provenance(
        **{
            "source": MemorySource.EXTERNAL,
            "confidence": 0.9,
            "evidence": (),
            "last_updated": _REPORTED_AT,
            "last_confirmed_at": _REPORTED_AT,
            "attestation": attestation,
            "derived_from_external": False,
            **provenance_overrides,
        }
    )
    fields: dict[str, Any] = {
        "id": "f1",
        "content": "2026-09-05\nClear\n11.4\n19.2\n0.0",
        "fact": "2026-09-05\nClear\n11.4\n19.2\n0.0",
        "provenance": provenance,
        "topics": (),
        "about_person": None,
        **overrides,
    }
    return SemanticMemory(**fields)


def _binding(**overrides: Any) -> EgressBinding:
    """One well-formed binding, so the cases below are about the carried fact alone.

    Its spans, its account and its endpoint are beside the point of every case here:
    what they are about is ADR-0260 §11's boolean, which rides on the value rather than
    on a span.

    Args:
        overrides: Fields to replace.

    Returns:
        The binding.
    """
    fields: dict[str, Any] = {
        "spans": (_span(),),
        "account": BoundAccount(identity="forecast@example.invalid", reference="forecast-account"),
        "transport_endpoint": "https://forecast.example.invalid",
        "planned_with_external_content": False,
        "coverage": SpanCoverage.NOT_COVERED,
        **overrides,
    }
    return EgressBinding(**fields)


def _span() -> EgressSpan:
    """One well-formed span, so a binding below constructs at all.

    Its content is beside the point of every case here: what they are about is the
    carried fact riding on the binding, which ADR-0260 §11 puts on the value rather than
    on a span.

    Returns:
        The span.
    """
    return EgressSpan(
        argument="origin",
        index=None,
        extent=1,
        provenance=DiscloserProvenance.SYSTEM_SELECTED,
    )


# --- the vocabularies (ADR-0260 §4, §10; ADR-0264 §5) -----------------------


def test_the_refusal_vocabulary_is_the_six_the_decision_admits() -> None:
    """ADR-0260 §4: a **closed** enumeration of exactly six, valued by lower-cased name.

    Pinned by value as well as by name, because the spelling is what an audit and a wire
    frame carry: renaming a member would silently invalidate every record already
    written. **The set assertion is what closes it** and is the half that fails on a
    member added without a decision.

    **There is no ``SPEND_REFUSED`` here and that is the design**, not an omission: this
    vocabulary names what a *read* produced, and §8 puts the stages the seam never sees
    — no registration, no budget, no derivable binding, no ``ALLOW`` — in the servicing's
    own ``ForecastDisposition``, which is ``orchestration``'s.
    """
    assert {member.value for member in ForecastRefusal} == {
        "transport_failed",
        "deadline_expired",
        "response_too_large",
        "provider_refused",
        "unattested",
        "no_result",
    }
    assert ForecastRefusal.TRANSPORT_FAILED.value == "transport_failed"
    assert ForecastRefusal.DEADLINE_EXPIRED.value == "deadline_expired"
    assert ForecastRefusal.RESPONSE_TOO_LARGE.value == "response_too_large"
    assert ForecastRefusal.PROVIDER_REFUSED.value == "provider_refused"
    assert ForecastRefusal.UNATTESTED.value == "unattested"
    assert ForecastRefusal.NO_RESULT.value == "no_result"


def test_the_user_facing_vocabulary_is_the_six_in_precedence_order() -> None:
    """ADR-0260 §10: six members, "declared **in precedence order**".

    The **order** is asserted and not only the membership, because §10 makes the
    declaration order the precedence order a revising turn folds by — "the field carries
    the **earliest-declared** member any servicing of the turn recorded" — so a member
    inserted rather than appended would move a fold nobody decided to move.
    """
    assert [member.value for member in ForecastNotRead] == [
        "not_configured",
        "authorisation_awaited",
        "spend_exhausted",
        "declined",
        "interrupted",
        "unavailable",
    ]


def test_the_destination_vocabulary_gained_one_member_and_kept_its_order() -> None:
    """ADR-0260 §10: ``FORECAST_PROVIDER`` renders **after** ``SEARCH_PROVIDER``.

    ADR-0264 §5 makes the declaration order the render order and requires a later seam
    to add "its own member with its own ADR" — so this is that section working rather
    than a departure from it. The order is asserted because an inserted member would
    change what every existing statement renders, and the member is a **class** of
    destination: its value names no provider, host, account, connection or tool.
    """
    assert [member.value for member in OutboundDestination] == [
        "search_provider",
        "forecast_provider",
    ]


# --- ADR-0260 §13's arm (j): the exactly-one rule and the instant with it ---


def test_an_outcome_carrying_records_and_a_refusal_is_refused() -> None:
    """§4: "**exactly one of** a non-empty ``records`` and a non-``None`` ``refusal``".

    A value carrying both would be two answers wearing one outcome's name, and the
    servicing would have to choose which half to honour — a choice ADR-0260 gives
    nobody.
    """
    with pytest.raises(ValidationError, match="never both"):
        ForecastOutcome(
            reported_at=_REPORTED_AT,
            records=(_record(),),
            refusal=ForecastRefusal.NO_RESULT,
        )


def test_an_outcome_carrying_neither_is_refused() -> None:
    """§13's arm (j): the *neither* case, asserted in its own right.

    "An outcome accepted while empty and unrefused is one a servicing can read as an
    answered read — and would then report a provider the turn never reached." That is
    §10's contact rule reading a ``None`` disposition as "the provider answered", so the
    empty-and-unrefused value is the one shape that would make the trail lie.
    """
    with pytest.raises(ValidationError, match="never neither"):
        ForecastOutcome()


def test_records_with_no_report_instant_are_refused() -> None:
    """§4: ``reported_at`` is present **exactly where** ``records`` is.

    A successful read whose outcome declared no instant would carry records attested to
    an instant the outcome does not name — and ADR-0092 §3 makes that instant the
    provider's own statement, with no substitute.
    """
    with pytest.raises(ValidationError, match="declares a report instant"):
        ForecastOutcome(records=(_record(),))


def test_a_refusal_carrying_a_report_instant_is_refused() -> None:
    """§4, the other half: a refused read declares none.

    An instant on a refusal would be this system stating when a provider spoke about a
    read that produced nothing — the one direction ADR-0264 §1 ranks below silence.
    """
    with pytest.raises(ValidationError, match="declares no report instant"):
        ForecastOutcome(reported_at=_REPORTED_AT, refusal=ForecastRefusal.NO_RESULT)


def test_a_conforming_outcome_constructs() -> None:
    """The positive arm, so every refusal above is about the clause it names.

    Two records sharing one ``reported_by`` and one attestation instant, each carrying
    its own bounded extent, is what ADR-0260 §5 mints — and it is what a servicing
    composes an evidence row's ``supported`` from (§9).
    """
    second = _record(
        id="f2",
        provenance={
            "attestation": {
                "extent": ReportedExtent(
                    extends_from=datetime(2026, 9, 5, 23, 0, tzinfo=UTC),
                    extends_until=datetime(2026, 9, 6, 23, 0, tzinfo=UTC),
                )
            }
        },
    )

    outcome = ForecastOutcome(reported_at=_REPORTED_AT, records=(_record(), second))

    assert outcome.refusal is None
    assert len(outcome.records) == 2


def test_a_bare_refusal_constructs_and_carries_a_class_and_nothing_else() -> None:
    """§4: every member is **returned**, so every one of them constructs.

    Parametrised nowhere and walked here instead, because the clause is about the
    vocabulary rather than about an example of it: a seventh member added without a
    producer still has to be a value a seam can return.
    """
    for member in ForecastRefusal:
        outcome = ForecastOutcome(refusal=member)

        assert outcome.refusal is member
        assert outcome.records == ()
        assert outcome.reported_at is None


# --- ADR-0260 §13's arm (b-prime), the model half ---------------------------


@pytest.mark.parametrize(
    ("overrides", "complaint"),
    [
        pytest.param(
            {"provenance": {"source": MemorySource.OBSERVED, "attestation": None}},
            "EXTERNAL",
            id="not-external",
        ),
        pytest.param({"provenance": {"evidence": ("m1",)}}, "no evidence", id="evidence"),
        pytest.param({"topics": ("weather",)}, "no topics", id="topics"),
        pytest.param({"about_person": "Ana"}, "no about_person", id="about-person"),
        pytest.param(
            {"validity": Validity(valid_from=datetime(2026, 9, 5, tzinfo=UTC))},
            "fully open",
            id="validity",
        ),
        pytest.param({"provenance": {"attestation": {"extent": None}}}, "bounded", id="no-extent"),
        pytest.param(
            {
                "provenance": {
                    "attestation": {
                        "extent": ReportedExtent(extends_from=datetime(2026, 9, 5, tzinfo=UTC))
                    }
                }
            },
            "bounded",
            id="unbounded-extent",
        ),
        pytest.param(
            {"provenance": {"attestation": {"reported_at": datetime(2020, 1, 1, tzinfo=UTC)}}},
            "own report instant",
            id="other-instant",
        ),
    ],
)
def test_a_record_the_minting_clause_would_not_have_produced_is_refused(
    overrides: dict[str, Any], complaint: str
) -> None:
    """§4: ``ForecastOutcome`` enforces exactly this list and no others.

    Every condition is **structural** — over the value's own fields — so none reaches
    for a bound, a clock, a store or a configuration, and the model validates
    identically in every deployment. That is what makes it true of every ``Forecaster``
    this system ever wires, **the canonical fake included**.

    The extent cases are two rather than one because a *ray* is not a half-open
    interval: §4 asks for "a constructible half-open interval" and §5 computes it as a
    day's own bounds, so an extent open at one end is a position no goal criterion could
    be checked against — ADR-0252 §3's fail-closed direction read at the value.
    """
    with pytest.raises(ValidationError, match=complaint):
        ForecastOutcome(reported_at=_REPORTED_AT, records=(_record(**overrides),))


def test_records_disagreeing_about_who_reported_them_are_refused() -> None:
    """§4: ``reported_by`` is "one value shared by every record of the outcome".

    **The outcome cannot check the equality §5 actually requires** — that the value is
    the *forecaster's own* ``name`` — because it holds no forecaster (§4). What it can
    check is that the records agree with each other, and it does: an implementation that
    stamped a vendor on one record and a source instance on the next would be attributing
    one read to two parties.
    """
    other = _record(id="f2", provenance={"attestation": {"reported_by": "somewhere else"}})

    with pytest.raises(ValidationError, match="one shared reported_by"):
        ForecastOutcome(reported_at=_REPORTED_AT, records=(_record(), other))


def test_an_outcome_refuses_an_unknown_field() -> None:
    """``extra="forbid"``, for the reason every boundary model here has it.

    A member the contract does not name is a member no reader can be relied on to carry,
    and a tolerated extra on a value that crosses the ``Forecaster`` seam is a shape
    change nothing would report.
    """
    with pytest.raises(ValidationError, match=r"extra_forbidden|Extra inputs"):
        ForecastOutcome(refusal=ForecastRefusal.NO_RESULT, days=3)  # type: ignore[call-arg]  # the point of the case


def test_an_outcome_is_frozen() -> None:
    """Frozen, so what a servicing acts on is not something a later holder can rewrite."""
    outcome = ForecastOutcome(refusal=ForecastRefusal.NO_RESULT)

    with pytest.raises(ValidationError):
        outcome.refusal = ForecastRefusal.UNATTESTED


# --- the carried fact and the folded member (ADR-0260 §10, §11) -------------


def test_forecast_reach_defaults_to_false_on_both_carriers() -> None:
    """§11: "``False`` is the **restrictive** value".

    "A composition site that fails to compute it yields a request that is not at the
    configured forecast provider and rules exactly as ``origin/main`` rules today." It
    is the value ``EgressBinder.rebind`` leaves behind too, because §11 mints **no park**
    for a forecast read and so no forecast binding is ever rebound.
    """
    carried = CarriedProvenance(
        spans={}, planned_with_external_content=False, coverage=SpanCoverage.NOT_COVERED
    )
    binding = _binding()

    assert carried.forecast_reach is False
    assert binding.forecast_reach is False
    assert carried.closed_loop is False
    assert binding.closed_loop is False


def test_forecast_reach_and_closed_loop_are_two_facts_and_neither_reads_the_other() -> None:
    """§11: "``closed_loop`` is **untouched** … and keeps meaning *this deployment's own
    search* and nothing else".

    Widening ``closed_loop`` to carry both kinds "would rewrite every stored row and
    supersede a clause ADR-0247 §4 states as unchanged", so the carrier gains one more
    boolean in that field's own shape. Setting either must leave the other alone, which
    is what an implementation folding the two would break.
    """
    forecast = CarriedProvenance(
        spans={},
        planned_with_external_content=False,
        coverage=SpanCoverage.NOT_COVERED,
        forecast_reach=True,
    )
    search = CarriedProvenance(
        spans={},
        planned_with_external_content=False,
        coverage=SpanCoverage.NOT_COVERED,
        closed_loop=True,
    )

    assert (forecast.forecast_reach, forecast.closed_loop) == (True, False)
    assert (search.forecast_reach, search.closed_loop) == (False, True)


def test_a_ruling_is_bound_to_the_fact_it_was_taken_over() -> None:
    """§11: ``forecast_reach`` is "compared inside ``PermissionDecision.authorises``".

    **Through the whole-value binding conjunct that already compares ``closed_loop``**,
    and by nothing added for it (ADR-0150 §9): the binding is compared whole and by
    value, so two bindings differing only in this member are unequal and a decision
    taken over one does not authorise the other. That is what stops a ruling made about
    a request at the configured provider authorising a request that is not.
    """
    without = _binding()
    with_reach = without.model_copy(update={"forecast_reach": True})

    assert without != with_reach


def test_a_turn_outcome_carries_the_folded_member_and_defaults_to_none() -> None:
    """§10: one field, ``ForecastNotRead | None``, defaulting to ``None``.

    "``None`` means the servicing recorded no ``ForecastDisposition``, and means nothing
    else": a turn that serviced no forecast read, **and** a read the provider answered.
    It is a widening rather than a change — a ``None``-defaulting member alters neither
    ADR-0170 §4's three ``reply``-``None`` shapes nor its one ``reply_degraded`` shape —
    and in particular it does not set ``reply_degraded``.
    """
    silent = TurnOutcome(turn=None)
    told = TurnOutcome(turn=None, forecast_not_read=ForecastNotRead.UNAVAILABLE)

    assert silent.forecast_not_read is None
    assert told.forecast_not_read is ForecastNotRead.UNAVAILABLE
    assert told.reply_degraded is False


def test_the_forecast_member_rides_beside_the_search_one() -> None:
    """§10, ADR-0264 §8: both statements ride together and neither is read off the other.

    A turn that searched and read a forecast may carry both members, "each in its own
    statement" — one says what act would change what a *lookup* produced, the other what
    act would change what a *forecast read* produced, and a surface that suppressed
    either because the other was present would leave a user told about one read and not
    the other.
    """
    from ai_assistant.core.types import SearchNotServiced  # noqa: PLC0415 — one case needs it

    outcome = TurnOutcome(
        turn=None,
        search_not_serviced=SearchNotServiced.UNAVAILABLE,
        forecast_not_read=ForecastNotRead.DECLINED,
    )

    assert outcome.search_not_serviced is SearchNotServiced.UNAVAILABLE
    assert outcome.forecast_not_read is ForecastNotRead.DECLINED


def test_a_record_is_minted_with_the_placement_that_narrows_nothing() -> None:
    """ADR-0260 §5: ``placement`` "is the default that narrows nothing" (ADR-0217 §6).

    Asserted here over the shape the model admits rather than over a producer's output —
    that half is §13's arm (b-prime) over the **production** forecaster — because what
    this value fixes is that a conforming record needs no placement stated for it, so a
    forecaster that narrowed one would be subtracting reach nobody decided to subtract.
    """
    outcome = ForecastOutcome(reported_at=_REPORTED_AT, records=(_record(),))

    assert outcome.records[0].placement == Placement()


def test_an_extent_is_the_day_and_not_the_read_s_own_bound() -> None:
    """ADR-0117 §2 through ADR-0260 §5: an extent is a day, and a day is a day long.

    Not an assertion about the model — ``ReportedExtent`` admits any ordered pair — but
    about what the shape of a *forecast* extent is, pinned so that a later producer
    trimming one to a coverage or widening one past what the source said fails a case
    rather than a review. §5 states both prohibitions in terms.
    """
    outcome = ForecastOutcome(reported_at=_REPORTED_AT, records=(_record(),))
    attestation = outcome.records[0].provenance.attestation

    assert attestation is not None
    assert attestation.extent is not None
    assert attestation.extent.extends_until is not None
    assert attestation.extent.extends_from is not None
    assert attestation.extent.extends_until - attestation.extent.extends_from == timedelta(days=1)
