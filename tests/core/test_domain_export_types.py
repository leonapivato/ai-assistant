"""The types ``export_domain`` takes and returns (ADR-0385 §6:2, §6:8, §6:9)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import ConversationExport as Conversations
from ai_assistant.core.types import (
    DomainExport,
    DomainExportOutcome,
    DomainExportRefusal,
    DomainExportResult,
    PlanExport,
    RecordHome,
    RecordHomeKind,
    named_domain,
)

_AT: Final = datetime(2026, 11, 26, 12, tzinfo=UTC)


def _empty(domain: RecordHome) -> DomainExport:
    return DomainExport(
        domain=domain,
        exported_at=_AT,
        conversations=Conversations(exported_at=_AT),
        plans=PlanExport(exported_at=_AT),
    )


@pytest.mark.parametrize(
    "domain",
    [
        RecordHome.owners(),
        RecordHome.shared(),
        RecordHome.person("person:sam"),
        RecordHome.group("group:house"),
    ],
)
def test_a_well_formed_home_of_any_domain_is_named_as_cores_own_value(domain: RecordHome) -> None:
    """§6:9 refuses the malformed alone; which domains are offered is §2:1's."""
    named = named_domain(domain)

    assert named == domain
    assert named is not domain


@pytest.mark.parametrize(
    "domain",
    [
        "shared",
        None,
        {"kind": "shared"},
        RecordHome.model_construct(kind="shared"),
        RecordHome.model_construct(kind=RecordHomeKind.SHARED, id="x"),
        RecordHome.model_construct(kind=RecordHomeKind.PERSON),
        RecordHome.model_construct(kind=RecordHomeKind.PERSON, id=""),
        RecordHome.model_construct(kind=RecordHomeKind.PERSON, id=7),
        RecordHome.model_construct(id=None),
    ],
)
def test_a_value_that_is_no_well_formed_home_is_refused_with_value_error(domain: object) -> None:
    """§6:9: a value built round the type's validation is malformed."""
    with pytest.raises(ValueError, match="a domain is a record home"):
        named_domain(domain)


def test_the_outcome_and_the_reason_are_closed_sets_of_the_names_six_two_gives() -> None:
    """§6:8: exactly ``exported`` and ``refused``, and ``not_offered``."""
    assert {one.value for one in DomainExportOutcome} == {"exported", "refused"}
    assert {one.value for one in DomainExportRefusal} == {"not_offered"}


def test_a_result_carries_its_export_exactly_when_exported() -> None:
    """The fields fit the outcome, in both directions."""
    export = _empty(RecordHome.shared())
    assert DomainExportResult.exported(export).export == export
    refused = DomainExportResult.not_offered()
    assert refused.outcome is DomainExportOutcome.REFUSED
    assert refused.refusal is DomainExportRefusal.NOT_OFFERED
    with pytest.raises(ValidationError):
        DomainExportResult(outcome=DomainExportOutcome.EXPORTED)
    with pytest.raises(ValidationError):
        DomainExportResult(
            outcome=DomainExportOutcome.REFUSED,
            refusal=DomainExportRefusal.NOT_OFFERED,
            export=export,
        )
    with pytest.raises(ValidationError):
        DomainExportResult(outcome=DomainExportOutcome.REFUSED)


def test_the_export_carries_its_domain_and_its_instant_and_is_frozen() -> None:
    """§6:8: the domain it was made for and the instant it was made."""
    export = _empty(RecordHome.owners())

    assert export.domain == RecordHome.owners()
    assert export.exported_at == _AT
    assert DomainExport.model_validate_json(export.model_dump_json()) == export
    with pytest.raises(ValidationError):
        export.memory = ()
    with pytest.raises(ValidationError):
        DomainExport.model_validate({**export.model_dump(), "audit": []})
