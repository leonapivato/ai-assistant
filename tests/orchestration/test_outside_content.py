"""The one rule the phases' glue and authorizing count a shown episode by (ADR-0303 §3:2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from test_authorizer import _digest, _episode, _marked_round

from ai_assistant.core.types import (
    DigestOutcome,
    EpisodicMemory,
    InputOrigin,
    MemorySource,
    Provenance,
    SemanticMemory,
)
from ai_assistant.orchestration.outside_content import (
    carries_evidence,
    from_outside,
    is_outside_episode,
    rests_on_outside_content,
)

_AT: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("record", "rests", "outside"),
    [
        pytest.param(_episode(), False, False, id="clean"),
        pytest.param(_episode(origin=InputOrigin.OUTSIDE), True, True, id="from-outside"),
        pytest.param(_episode(derived_from_external=True), True, True, id="marked-provenance"),
        pytest.param(
            _episode(digests=(_digest(DigestOutcome.ANSWERED, "the 9:10"),)),
            True,
            True,
            id="evidence",
        ),
        pytest.param(
            _episode(digests=(_digest(DigestOutcome.ANSWERED),)),
            False,
            False,
            id="an-answer-with-no-evidence",
        ),
        # A marked note is counted where planning is shown it, and from its label.
        pytest.param(_episode(rounds=(_marked_round(),)), False, True, id="a-marked-note"),
    ],
)
def test_an_episode_is_outside_by_its_record(
    record: EpisodicMemory, *, rests: bool, outside: bool
) -> None:
    assert rests_on_outside_content(record) is rests
    assert is_outside_episode(record) is outside


def test_only_an_outside_origin_is_from_outside() -> None:
    assert from_outside(_episode(origin=InputOrigin.OUTSIDE))
    assert not from_outside(_episode())
    assert not from_outside(_episode().model_copy(update={"processing_record": None}))


def test_a_memory_record_carries_no_evidence() -> None:
    fact = SemanticMemory(
        id="fact",
        content="The 9:10 runs.",
        fact="The 9:10 runs.",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AT),
    )
    assert not carries_evidence(fact)
