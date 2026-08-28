"""ADR-0205's three values, and the partition that makes a report mean something.

§2 fixes the member sets and rules that the three states **partition** the
durations: "No value satisfies two of the three and none satisfies none of them, so
the state is derivable from the durations and cannot disagree with them." That is a
coherence validator in ``DeferredProposal``'s shape, taken for ADR-0130 §2's stated
reason — "a value that has already contradicted itself is not a report, it is a
defect" — so every arm of it is checked here rather than left to the one caller that
happens to build the value today.

§3's member on :class:`~ai_assistant.core.types.ConversationTurn` and §1's member on
:class:`~ai_assistant.core.types.SpokenTurn` are pinned beside them: the counts are
what ADR-0205 §10 partially supersedes, and a sixth arriving unnoticed is exactly
what an enumeration stops.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ConversationTurn,
    SpokenDelivery,
    SpokenDeliveryReport,
    SpokenDeliveryState,
)

_AT: Final = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)

#: A rendering ten seconds long, and a device that played three of them.
_WHOLE: Final = timedelta(seconds=10)
_PART: Final = timedelta(seconds=3)
_NONE: Final = timedelta(0)


def _turn(**overrides: object) -> ConversationTurn:
    """One index row, with whatever member a case is about overridden."""
    fields: dict[str, object] = {
        "conversation_id": "c-1",
        "ordinal": 1,
        "episode_id": "conv:c-1:1",
        "occurred_at": _AT,
    }
    fields.update(overrides)
    return ConversationTurn(**fields)  # type: ignore[arg-type]  # a row assembled from a mapping


# --- §2: the vocabulary ------------------------------------------------------


def test_the_state_is_a_closed_vocabulary_of_exactly_three() -> None:
    # §2: "a closed ``StrEnum`` … with exactly three members. Adding a member is a
    # change to what was decided and takes its own ratified decision, as does
    # removing one." §8 leaves a fourth — for a rendering that never existed —
    # available additively, which is precisely why the count is pinned rather than
    # assumed.
    assert {member.value for member in SpokenDeliveryState} == {
        "unknown",
        "complete",
        "interrupted",
    }


def test_the_fact_and_the_report_carry_exactly_what_adr_0205_names() -> None:
    # §2 fixes both member sets, and the split is load-bearing: the subject is a
    # property of the *report* and not of the turn, because the row §3 stamps
    # already names its own episode and a stored fact repeating that id would be
    # ADR-0084 §3's redundancy.
    assert set(SpokenDelivery.model_fields) == {"state", "played", "rendered"}
    assert set(SpokenDeliveryReport.model_fields) == {"episode_id", "delivery"}


def test_both_are_frozen_and_forbid_extras() -> None:
    fact = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
    with pytest.raises(ValidationError):
        SpokenDelivery(state=SpokenDeliveryState.UNKNOWN, nonsense=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        fact.state = SpokenDeliveryState.COMPLETE
    report = SpokenDeliveryReport(episode_id="conv:c-1:1", delivery=fact)
    with pytest.raises(ValidationError):
        report.episode_id = "conv:c-1:2"


def test_a_report_names_a_turn_and_a_blank_name_is_refused() -> None:
    # §1: "A report **names the turn it is about**". `Identifier` is non-blank, so a
    # report with nothing to name cannot be built at all.
    with pytest.raises(ValidationError):
        SpokenDeliveryReport(
            episode_id="  ", delivery=SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
        )


# --- §2: the partition -------------------------------------------------------


def test_unknown_carries_neither_duration() -> None:
    # §2: "``UNKNOWN`` carries ``played`` and ``rendered`` both ``None``." It is
    # also the value capture writes, so it must be constructible from the state
    # alone — which is the spelling §4 uses.
    fact = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
    assert (fact.played, fact.rendered) == (None, None)


def test_complete_is_equality_and_not_merely_below_or_equal() -> None:
    # §2's own argument, from adversarial review's round-3 blocker: `played <=
    # rendered` would admit `COMPLETE` beside a `played` of zero — "a report saying
    # in one member that nothing was heard and in another that the answer was
    # delivered" — and §5 permits a `COMPLETE` turn to be rendered as nothing, so
    # that value would make an entirely unheard answer disappear from the prompt as
    # delivered.
    whole = SpokenDelivery(state=SpokenDeliveryState.COMPLETE, played=_WHOLE, rendered=_WHOLE)
    assert whole.played == whole.rendered


def test_interrupted_is_strictly_below() -> None:
    part = SpokenDelivery(state=SpokenDeliveryState.INTERRUPTED, played=_PART, rendered=_WHOLE)
    assert part.played is not None
    assert part.rendered is not None
    assert part.played < part.rendered


@pytest.mark.parametrize(
    ("fields", "why"),
    [
        pytest.param(
            {"state": SpokenDeliveryState.UNKNOWN, "played": _PART},
            "UNKNOWN with one duration present",
            id="unknown-with-played",
        ),
        pytest.param(
            {"state": SpokenDeliveryState.UNKNOWN, "rendered": _WHOLE},
            "UNKNOWN with the other present",
            id="unknown-with-rendered",
        ),
        pytest.param(
            {"state": SpokenDeliveryState.COMPLETE, "rendered": _WHOLE},
            "COMPLETE with a duration missing",
            id="complete-without-played",
        ),
        pytest.param(
            {"state": SpokenDeliveryState.INTERRUPTED, "played": _PART},
            "INTERRUPTED with a duration missing",
            id="interrupted-without-rendered",
        ),
        pytest.param(
            {"state": SpokenDeliveryState.COMPLETE, "played": _PART, "rendered": _WHOLE},
            "COMPLETE with played below rendered",
            id="complete-below",
        ),
        pytest.param(
            {"state": SpokenDeliveryState.INTERRUPTED, "played": _WHOLE, "rendered": _WHOLE},
            "INTERRUPTED with the two equal",
            id="interrupted-equal",
        ),
        pytest.param(
            {"state": SpokenDeliveryState.COMPLETE, "played": _NONE, "rendered": _NONE},
            "a rendering of no length at all",
            id="zero-rendered",
        ),
        pytest.param(
            {"state": SpokenDeliveryState.INTERRUPTED, "played": -_PART, "rendered": _WHOLE},
            "a negative played",
            id="negative-played",
        ),
    ],
)
def test_every_value_outside_the_partition_is_refused(fields: dict[str, object], why: str) -> None:
    # §2: "a value outside the partition is refused at validation". The list is
    # ADR-0205 §9's own, written out rather than sampled, because each arm rules out
    # a different lie and a validator missing one of them passes the other seven.
    with pytest.raises(ValidationError):
        SpokenDelivery(**fields)  # type: ignore[arg-type]  # deliberately outside the partition
    assert why


# --- §3: the member on the index row -----------------------------------------


def test_the_turn_carries_the_one_member_adr_0205_adds() -> None:
    # §10 partially supersedes ADR-0074 §9's enumeration in exactly one scope. The
    # count is what says the addition was `delivery` and nothing beside it.
    assert set(ConversationTurn.model_fields) == {
        "conversation_id",
        "ordinal",
        "episode_id",
        "occurred_at",
        "parked",
        "delivery",
    }


def test_a_turn_carries_no_delivery_by_default() -> None:
    # §3: "An absent ``delivery`` means **no delivery fact was recorded for this
    # turn**". The default is what makes every operation but `converse_spoken` leave
    # the row absent without any of them saying so.
    assert _turn().delivery is None


def test_a_turn_can_carry_any_state_the_partition_admits() -> None:
    # §3's last clause: "``UNKNOWN`` is the whole of what is stampable, and a turn
    # whose rendering never existed is stampable like any other" — so the row admits
    # every state, and the eligibility rule lives in `record_delivery` rather than
    # in the type.
    for fact in (
        SpokenDelivery(state=SpokenDeliveryState.UNKNOWN),
        SpokenDelivery(state=SpokenDeliveryState.COMPLETE, played=_WHOLE, rendered=_WHOLE),
        SpokenDelivery(state=SpokenDeliveryState.INTERRUPTED, played=_PART, rendered=_WHOLE),
    ):
        assert _turn(delivery=fact).delivery == fact
