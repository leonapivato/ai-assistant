"""``PROTOCOL_VERSION`` moved once for the person-model act's request form (ADR-0362 §2:3).

§2:3 has the lane that adds ``PersonModelAct``'s request form advance the constant on
ADR-0124 §9's rule, since the change log and the pins cross the wire to the panels. A
test holds that the number moved and that the move is accounted for in the log a reviewer
reads, as ``test_call_showed_protocol_version.py`` does. The cases below send a change of
each form through the codec's own projection and read it back, and hold that an act of
every earlier form is sent exactly as it was (§2:2).
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from typing import Final

import pytest

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    PersonActHow,
    PersonModelAct,
    ProfileChange,
    ProfileField,
    QuestionPart,
)
from ai_assistant.wire import envelope
from ai_assistant.wire.codec import encode_projection, project

#: The version ADR-0362 §2:3 moves to, read at the moment the lane landed, and the one it
#: moves from. The absolute figure has one home,
#: ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 127
_MOVED_FROM: Final = 126

_AT: Final = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

_BY_A_TICKET: Final = PersonModelAct(
    how=PersonActHow.APPROVAL,
    by=OWNER_PERSON_ID,
    request="q-1",
    episode_id="activation:act-approval",
)


def _change(act: PersonModelAct) -> ProfileChange:
    """A change made by ``act``, naming the suggestion an accepted one made it by."""
    return ProfileChange(
        person_id=OWNER_PERSON_ID,
        field=ProfileField.ADDRESS,
        old=None,
        new="Robin",
        at=_AT,
        act=act,
        suggestion_id="suggestion-1" if act.how is PersonActHow.SUGGESTION else None,
    )


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """§2:3: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_its_ground() -> None:
    """The entry names ADR-0362 §2:3 and its ground, and the one it follows stands."""
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {_MOVED_TO}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    flat = " ".join(line.removeprefix("#:").strip() for line in entry.splitlines())

    assert "ADR-0362 §2:3" in flat
    assert "PersonModelAct" in flat
    assert "request" in flat
    assert f"#: {_MOVED_FROM}: " in source, (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_an_act_of_the_request_form_round_trips_through_the_codec() -> None:
    """§2:1: the request a ticket ran under, and the approval's own episode, are sent."""
    sent: dict[str, object] = json.loads(encode_projection(project(_change(_BY_A_TICKET))))

    assert sent["act"] == {
        "how": "approval",
        "by": OWNER_PERSON_ID,
        "approval": None,
        "episode_id": "activation:act-approval",
        "request": "q-1",
    }
    assert ProfileChange.model_validate(sent).act == _BY_A_TICKET


@pytest.mark.parametrize(
    "act",
    [
        PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID),
        PersonModelAct(how=PersonActHow.SEED),
        PersonModelAct(
            how=PersonActHow.APPROVAL,
            by=OWNER_PERSON_ID,
            approval=QuestionPart(round="round-1", part=1),
            episode_id="activation:act-1",
        ),
        PersonModelAct(how=PersonActHow.SUGGESTION, by=OWNER_PERSON_ID, episode_id="act-1"),
    ],
    ids=["panel", "seed", "question", "suggestion"],
)
def test_an_act_of_every_earlier_form_is_sent_as_it_was(act: PersonModelAct) -> None:
    """§2:2: ``request`` is left out where it is unset, so a peer at 126 reads the act."""
    sent: dict[str, object] = json.loads(encode_projection(project(_change(act))))

    assert isinstance(sent["act"], dict)
    assert set(sent["act"]) == {"how", "by", "approval", "episode_id"}
    assert ProfileChange.model_validate(sent).act == act
