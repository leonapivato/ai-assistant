"""The one rule the phases' glue and authorizing count a shown episode by (ADR-0303 §3:2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from test_authorizer import _digest, _episode, _marked_round, _version

from ai_assistant.core.types import (
    ChannelIdentity,
    DigestOutcome,
    EpisodicMemory,
    JoinedInput,
    RecordedInputMessage,
    SupportHolder,
)
from ai_assistant.orchestration.outside_content import (
    carries_evidence,
    from_outside,
    holds_outside,
    is_outside_episode,
    joined_parties,
    rests_on_outside_content,
)
from ai_assistant.testing.memories import memory, said_support
from ai_assistant.testing.parties import OWNERS_WORDS, UNIDENTIFIED_WORDS

_AT: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("record", "rests", "outside"),
    [
        pytest.param(_episode(), False, False, id="clean"),
        pytest.param(_episode(parties=UNIDENTIFIED_WORDS), True, True, id="from-outside"),
        pytest.param(_episode(understanding=(_version(relayed=True),)), True, True, id="relayed"),
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


def test_only_an_input_outside_by_its_parties_or_its_relay_mark_is_from_outside() -> None:
    """ADR-0351 §5:1, §5:7, §8:3: the parties, read with the latest version's relay mark."""
    assert from_outside(_episode(parties=UNIDENTIFIED_WORDS))
    assert from_outside(_episode(understanding=(_version(relayed=True),)))
    assert not from_outside(_episode())
    assert not from_outside(_episode(understanding=(_version(relayed=False),)))
    assert not from_outside(_episode().model_copy(update={"processing_record": None}))


def _joined(*, relayed: bool, party: SupportHolder | None = OWNERS_WORDS[0]) -> JoinedInput:
    return JoinedInput(
        joined_at=_AT,
        channel=ChannelIdentity(channel_type="conversation", instance_id="c1"),
        messages=(RecordedInputMessage(text="and the school's", sent_at=_AT, party=party),),
        relayed=relayed,
    )


def test_an_activation_holds_outside_input_where_any_input_it_holds_is() -> None:
    """ADR-0351 §8:5, §5:13-§5:14: a joined input is read by its own relay mark."""
    record = _episode().processing_record
    assert record is not None
    trigger = record.trigger
    assert not holds_outside(trigger, (), ())
    assert not holds_outside(trigger, (), (_joined(relayed=False),))
    assert holds_outside(trigger, (), (_joined(relayed=True),))
    assert holds_outside(trigger, (_version(relayed=True),), ())
    assert holds_outside(trigger, (), (_joined(relayed=False, party=None),)), "unknown parties"


def test_a_joined_inputs_parties_are_its_messages_or_unknown() -> None:
    """ADR-0351 §2:6, §9:3."""
    assert joined_parties(_joined(relayed=False)) == OWNERS_WORDS
    assert joined_parties(_joined(relayed=False, party=None)) is None


def test_a_memory_record_carries_no_evidence() -> None:
    fact = memory("fact", "The 9:10 runs.", said_support(when=_AT, added_at=_AT))
    assert not carries_evidence(fact)
