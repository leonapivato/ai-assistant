"""The scout: its call, its reply, and what code keeps of it (ADR-0329 §8:2, §9:1, §5:5).

Driven on values. A finding names parts by label and code maps each back; a label
naming nothing read, or a finding resting on no part of the leaving episode, is dropped
(§8:2, §9:5); a reliance finding rests on what later episodes show (§14:1); and a
candidate recorded under an approval always gives a finding (§5:5, §11:1). The two
instructions and the replies code parses are held to one shape.
"""

from __future__ import annotations

import json
from datetime import timedelta

from observer_support import AT, address, episode, reply

from ai_assistant.core.types import (
    ConfirmationPart,
    InputPart,
    QuestionPart,
    Role,
    SupportOrigin,
)
from ai_assistant.orchestration.observer.commit import CommitReply
from ai_assistant.orchestration.observer.prompts import COMMIT_INSTRUCTION, SCOUT_INSTRUCTION
from ai_assistant.orchestration.observer.reading import (
    Hint,
    ReadEpisode,
    Reading,
    ReadPart,
    Reliance,
)
from ai_assistant.orchestration.observer.scout import (
    ScoutReply,
    parsed,
    proposed_findings,
    scout_messages,
)
from ai_assistant.testing.memories import memory, said_support


def _input(handle: str, name: str, *, at_minutes: int = 0) -> ReadPart:
    occurred = AT + timedelta(minutes=at_minutes)
    return ReadPart(
        handle=handle,
        part=InputPart(episode=address(name)),
        episode=address(name),
        occurred_at=occurred,
        text="words",
        origin=SupportOrigin.USER_MESSAGE,
        when=occurred,
    )


def _reading(*, hints: tuple[Hint, ...] = (), reliances: tuple[Reliance, ...] = ()) -> Reading:
    leaving = episode("leaving")
    later = episode("later", at=AT + timedelta(minutes=1))
    return Reading(
        leaving=ReadEpisode(handle="E1", record=leaving, parts=(_input("P1", "leaving"),)),
        later=(
            ReadEpisode(handle="E2", record=later, parts=(_input("P2", "later", at_minutes=1),)),
        ),
        hints=hints,
        reliances=reliances,
    )


def _scouted(reading: Reading, *findings: dict[str, object]) -> tuple[list[str], int]:
    proposal = parsed(reply(findings=list(findings)), ScoutReply)
    assert proposal is not None
    kept, dropped = proposed_findings(proposal, reading)
    return [one.claim for one in kept], dropped


def test_a_reply_parses_whole_or_not_at_all() -> None:
    fenced = "```json\n" + reply(findings=[]) + "\n```"

    assert parsed(fenced, ScoutReply) == ScoutReply()
    assert parsed("not json", ScoutReply) is None
    assert parsed(reply(findings=[{"claim": "x", "extra": 1}]), ScoutReply) is None


def test_a_finding_names_parts_by_label_and_code_maps_them_back() -> None:
    """§9:1, §9:5: the parts it rests on, by the addresses the reading holds."""
    proposal = parsed(
        reply(findings=[{"claim": "The user prefers window seats.", "rests_on": ["P1", "P2"]}]),
        ScoutReply,
    )
    assert proposal is not None

    (finding,), dropped = proposed_findings(proposal, _reading())

    assert dropped == 0
    assert finding.id == "f1"
    assert finding.episode == address("leaving")
    assert finding.rests_on == (
        InputPart(episode=address("leaving")),
        InputPart(episode=address("later")),
    )
    assert finding.outcome is None


def test_a_finding_naming_a_part_not_read_is_dropped() -> None:
    claims, dropped = _scouted(_reading(), {"claim": "x", "rests_on": ["P1", "P9"]})

    assert (claims, dropped) == ([], 1)


def test_a_finding_from_a_later_episode_alone_waits_for_it() -> None:
    """§8:2: only findings that come from the leaving episode are committed."""
    claims, dropped = _scouted(_reading(), {"claim": "x", "rests_on": ["P2"]})

    assert (claims, dropped) == ([], 1)


def test_a_reliance_finding_rests_on_what_later_episodes_show() -> None:
    """§14:1-§14:2: kept where it names a memory a reliance call named."""
    held = memory("m-seat", "The user prefers window seats.", said_support(address("past")))
    reading = _reading(
        reliances=(Reliance(handle="M1", memory=held, shaped="the seat", relied_at=AT),)
    )
    proposal = parsed(
        reply(
            findings=[
                {"claim": "The seat held up.", "rests_on": ["P2"], "relied_on": "M1"},
                {"claim": "Another.", "rests_on": ["P2"], "relied_on": "M7"},
            ]
        ),
        ScoutReply,
    )
    assert proposal is not None

    kept, dropped = proposed_findings(proposal, reading)

    assert [(one.claim, one.relied_on) for one in kept] == [("The seat held up.", "m-seat")]
    assert dropped == 1


def test_a_candidate_is_named_by_its_effect_record() -> None:
    """§3:3: a finding names the candidate it came from by the record that shows it done."""
    reading = _reading(hints=(Hint(handle="C1", effect="effect-1", fact="x"),))
    proposal = parsed(
        reply(findings=[{"claim": "x", "rests_on": ["P1"], "candidate": "C1"}]), ScoutReply
    )
    assert proposal is not None

    (finding,), _ = proposed_findings(proposal, reading)

    assert finding.candidate == "effect-1"


def test_a_candidate_the_user_confirmed_always_gives_a_finding() -> None:
    """§5:5, §11:1: where the scout proposed none, code adds one resting on the yes."""
    yes = ReadPart(
        handle="P3",
        part=ConfirmationPart(
            episode=address("leaving"),
            asking_activation="asking",
            question=QuestionPart(round="r", part=1),
        ),
        episode=address("leaving"),
        occurred_at=AT,
        text="The user prefers window seats.",
        origin=SupportOrigin.CONFIRMATION,
        when=AT,
    )
    reading = _reading(
        hints=(Hint(handle="C1", effect="effect-1", fact=yes.text, confirmation=yes),)
    )

    proposal = parsed(reply(findings=[]), ScoutReply)
    assert proposal is not None
    (finding,), _ = proposed_findings(proposal, reading)

    assert (finding.claim, finding.rests_on, finding.candidate) == (
        "The user prefers window seats.",
        (yes.part,),
        "effect-1",
    )


def test_the_scout_is_shown_its_instruction_and_the_reading_as_data() -> None:
    """§8:5: the reading reaches the model as one JSON object of quoted source data."""
    system, user = scout_messages(_reading())

    assert (system.role, system.content) == (Role.SYSTEM, SCOUT_INSTRUCTION)
    assert user.role is Role.USER
    assert json.loads(user.content) == _reading().payload()


def test_each_instruction_names_every_field_code_reads_of_its_reply() -> None:
    """The prompts and the parsed replies are one shape: no field code reads goes unasked."""
    for name in ("findings", "claim", "rests_on", "candidate", "relied_on"):
        assert f'"{name}"' in SCOUT_INSTRUCTION
    for name in CommitReply.model_fields:
        assert f'"{name}"' in COMMIT_INSTRUCTION
    for name in ("part", "direction", "backs_as_worded", "how_sure", "about_when", "note"):
        assert f'"{name}"' in COMMIT_INSTRUCTION


def test_a_reliance_finding_resting_on_the_leaving_episode_is_dropped() -> None:
    """§14:2: a reliance is judged on what later episodes show, never on its own episode."""
    held = memory("m-seat", "The user prefers window seats.", said_support(address("past")))
    reading = _reading(
        reliances=(Reliance(handle="M1", memory=held, shaped="the seat", relied_at=AT),)
    )

    claims, dropped = _scouted(
        reading,
        {"claim": "Held up.", "rests_on": ["P1"], "relied_on": "M1"},
        {"claim": "Held up too.", "rests_on": ["P1", "P2"], "relied_on": "M1"},
    )

    assert (claims, dropped) == ([], 2)


def test_a_finding_naming_a_confirmed_candidate_rests_on_its_yes() -> None:
    """§5:5: the commit step sees the words the user approved, whatever else was named."""
    yes = ReadPart(
        handle="P3",
        part=ConfirmationPart(
            episode=address("leaving"),
            asking_activation="asking",
            question=QuestionPart(round="r", part=1),
        ),
        episode=address("leaving"),
        occurred_at=AT,
        text="The user prefers window seats.",
        origin=SupportOrigin.CONFIRMATION,
        when=AT,
    )
    reading = _reading(
        hints=(Hint(handle="C1", effect="effect-1", fact=yes.text, confirmation=yes),)
    )
    proposal = parsed(
        reply(findings=[{"claim": "Window seats.", "rests_on": ["P1"], "candidate": "C1"}]),
        ScoutReply,
    )
    assert proposal is not None

    (finding,), _ = proposed_findings(proposal, reading)

    assert finding.rests_on == (InputPart(episode=address("leaving")), yes.part)
