"""The scout: its call, its reply, and what code keeps of it (ADR-0346 §4).

Driven on values. A finding names parts by label and code maps each back; a label
naming nothing read, or a finding resting on no part of the leaving episode, is dropped
(§3:1, ADR-0329 §9:5); each finding carries the scout's annotations, the owner named by
the owner's identifier (§4:2, ADR-0345 §9:4); every candidate is named by a finding or
declined with a reason, and a reply that leaves one unaccounted is refused (§4:6); and a
finding naming a candidate recorded under an approval rests on the user's yes (ADR-0329
§5:5). Each step's system message is whatever its template renders (ADR-0334 §3:5), and
a step refuses another prompt's template.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from observer_support import (
    AT,
    Harness,
    address,
    episode,
    found,
    framed,
    framing,
    limits,
    read_as,
    reply,
)
from structured_support import structured

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ConfirmationPart,
    InputPart,
    ObservationAttemptEnd,
    PlacementReach,
    QuestionPart,
    Role,
    SupportOrigin,
)
from ai_assistant.orchestration.observer import Observer
from ai_assistant.orchestration.observer.framing import FramingView, framing_messages
from ai_assistant.orchestration.observer.placement import PlacementView, placement_messages
from ai_assistant.orchestration.observer.prompts import (
    OBSERVER_FRAMING_PROMPT,
    OBSERVER_PLACEMENT_PROMPT,
    OBSERVER_SCOUT_PROMPT,
)
from ai_assistant.orchestration.observer.reading import Hint, ReadEpisode, Reading, ReadPart
from ai_assistant.orchestration.observer.replies import ScoutReplyShape
from ai_assistant.orchestration.observer.scout import (
    DROPPED_REASON,
    Proposal,
    proposed,
    scout_messages,
)
from ai_assistant.orchestration.understanding import RecentEpisodes
from ai_assistant.testing import FakeDiagnosticSink, FakeModelProvider, default_prompt, prompt_from
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from ai_assistant.core.prompts import PromptDeclaration

_CLAIM = "The user prefers window seats."


async def _three(harness: Harness) -> None:
    """Three episodes, a minute apart: with a window of two, the oldest has left it."""
    await harness.hold(
        episode("one", at=AT - timedelta(minutes=3)),
        episode("two", at=AT - timedelta(minutes=2), text="What time is it?"),
        episode("three", at=AT - timedelta(minutes=1), text="Thanks."),
    )


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


def _reading(*, hints: tuple[Hint, ...] = ()) -> Reading:
    """A leaving episode with one part, and an earlier one its record points at."""
    leaving = episode("leaving")
    earlier = episode("earlier", at=AT - timedelta(minutes=1))
    return Reading(
        leaving=ReadEpisode(
            handle="E1",
            episode=leaving.id,
            record=leaving,
            parts=(_input("P1", "leaving"),),
        ),
        earlier=(
            ReadEpisode(
                handle="E2",
                episode=earlier.id,
                record=earlier,
                parts=(_input("P2", "earlier", at_minutes=-1),),
            ),
        ),
        hints=hints,
    )


def _proposal(reading: Reading, *findings: dict[str, object], **extra: object) -> Proposal | None:
    reply_read = read_as(reply(findings=list(findings), **extra), ScoutReplyShape)
    assert reply_read is not None
    return proposed(reply_read, reading)


#: A scout reply from a dry run on a copy of live data (2026-10-20): every required field
#: valid, and one finding carrying a key the shape does not name.
_DRY_RUN_REPLY = """{"findings": [
  {"claim": "The user said Zach is their roommate.", "rests_on": ["P1"],
   "candidates": [], "subjects": ["the user", "Zach"]},
  {"command": null, "claim": "The user approved the drafted introduction email.",
   "rests_on": ["P5", "P6"], "candidates": []},
  {"claim": "The user uses more than one chat channel.", "rests_on": ["P3"]}
]}"""


def test_a_reply_parses_whole_or_not_at_all() -> None:
    fenced = "```json\n" + reply(findings=[]) + "\n```"

    assert read_as(fenced, ScoutReplyShape) == ScoutReplyShape()
    assert read_as("not json", ScoutReplyShape) is None
    assert read_as(reply(findings=[{"rests_on": ["P1"]}]), ScoutReplyShape) is None
    assert read_as(reply(findings=[{"claim": "x", "rests_on": "P1"}]), ScoutReplyShape) is None
    assert read_as(reply(findings=[{"claim": ["x"]}]), ScoutReplyShape) is None
    assert read_as(reply(findings=[], declines=[{"candidate": "C1"}]), ScoutReplyShape) is None


def test_a_scout_reply_with_prose_around_its_object_is_no_reply() -> None:
    """ADR-0354 §10:1: the candidate walk is gone, so prose around the object is invalid."""
    findings = reply(findings=[{"claim": _CLAIM, "rests_on": ["P1"]}])

    assert read_as(findings, ScoutReplyShape) == ScoutReplyShape.model_validate_json(findings)
    assert read_as(f"Here is what I found.\n{findings}", ScoutReplyShape) is None
    assert read_as(f"{findings}\nThat is all.", ScoutReplyShape) is None
    assert read_as('I found nothing; {"seat": 1}', ScoutReplyShape) is None


def test_a_key_the_shape_does_not_name_is_dropped_and_the_reply_kept() -> None:
    """A stray key is no reason to discard a reply whose every named field is valid."""
    proposal = read_as(_DRY_RUN_REPLY, ScoutReplyShape)

    assert proposal is not None
    assert [(one.claim, one.rests_on) for one in proposal.findings] == [
        ("The user said Zach is their roommate.", ("P1",)),
        ("The user approved the drafted introduction email.", ("P5", "P6")),
        ("The user uses more than one chat channel.", ("P3",)),
    ]
    assert read_as(reply(findings=[], note="x"), ScoutReplyShape) == ScoutReplyShape()
    assert "command" not in proposal.findings[1].model_dump()


async def test_a_finding_with_a_stray_key_is_committed() -> None:
    """End to end: the attempt finishes and the finding is written."""
    harness = Harness()
    await _three(harness)
    scout = reply(findings=[found(_CLAIM, "P1", command=None)])
    observer = harness.observer(
        scout=FakeModelProvider.scripted(scout),
        commit=FakeModelProvider.scripted(framing(framed(_CLAIM, "P1"))),
    )

    outcome = await observer.run()

    assert outcome.processed == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.attempts[-1].end is ObservationAttemptEnd.FINISHED
    (finding,) = record.findings
    assert finding.claim == _CLAIM
    assert finding.outcome is not None
    assert len(finding.outcome.writes) == 1


async def test_a_scout_reply_missing_a_required_key_still_fails_as_unparsed() -> None:
    """§16:4: a finding with no claim is no proposal; the attempt fails, naming the scout."""
    harness = Harness()
    await _three(harness)
    sink = FakeDiagnosticSink()
    scout = FakeModelProvider.scripted(reply(findings=[{"command": None, "rests_on": ["P1"]}]))

    outcome = await harness.observer(scout=scout, diagnostics=sink).run()

    assert outcome.waiting == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.findings == ()
    assert record.attempts[-1].end is ObservationAttemptEnd.FAILED
    assert json.loads(sink.recorded[-1].model_dump_json())["body"]["failure"] == {
        "class": "unparsed",
        "message": "the scout step's reply did not parse",
    }


def test_a_finding_names_parts_by_label_and_code_maps_them_back() -> None:
    """ADR-0346 §3:1: the parts it rests on, an earlier one the record points at among them."""
    proposal = _proposal(_reading(), found(_CLAIM, "P1", "P2"))

    assert proposal is not None
    (finding,) = proposal.findings
    assert finding.rests_on == (
        InputPart(episode=address("leaving")),
        InputPart(episode=address("earlier")),
    )
    assert finding.id == "f1"


def test_a_finding_naming_a_part_not_read_is_dropped() -> None:
    proposal = _proposal(_reading(), found(_CLAIM, "P9"))

    assert proposal is not None
    assert (proposal.findings, proposal.dropped) == ((), 1)


def test_a_finding_resting_on_no_part_of_the_leaving_episode_is_dropped() -> None:
    """ADR-0346 §3:1: a finding rests on at least one of the leaving episode's parts."""
    proposal = _proposal(_reading(), found(_CLAIM, "P2"))

    assert proposal is not None
    assert (proposal.findings, proposal.dropped) == ((), 1)


def test_the_annotations_are_kept_beside_the_claim() -> None:
    """ADR-0346 §4:2, §4:5: whom, why, when, and the owner named by the owner's id."""
    proposal = _proposal(
        _reading(),
        found(
            "Ana is the user's younger sister.",
            "P1",
            subjects=["Ana", "the user", "Ana"],
            involved=["the user", "Tom"],
            why="  Family.  ",
            situations=["planning a visit", "", "planning a visit"],
        ),
    )

    assert proposal is not None
    (finding,) = proposal.findings
    annotations = finding.annotations
    assert annotations is not None
    assert annotations.subjects == ("Ana", OWNER_PERSON_ID)
    assert annotations.involved == ("Tom",), "a person in both is kept in subjects alone"
    assert annotations.why == "Family."
    assert annotations.situations == ("planning a visit",)
    assert annotations.narrowing is None


def test_any_narrowing_proposed_is_read_as_the_narrower_reach() -> None:
    """ADR-0217 §4, ADR-0346 §4:2: read failing closed, its note kept or code's own."""
    proposal = _proposal(
        _reading(),
        found(_CLAIM, "P1", narrowing={"reach": "owner", "note": "Between us."}),
        found("The user flies.", "P1", narrowing={"reach": "everyone"}),
    )

    assert proposal is not None
    first, second = (one.annotations for one in proposal.findings)
    assert first is not None
    assert second is not None
    assert first.narrowing is not None
    assert (first.narrowing.reach, first.narrowing.note) == (PlacementReach.OWNER, "Between us.")
    assert second.narrowing is not None
    assert second.narrowing.reach is PlacementReach.OWNER
    assert second.narrowing.note


def _hint(handle: str, effect: str, *, confirmation: ReadPart | None = None) -> Hint:
    return Hint(handle=handle, effect=effect, fact="A fact.", confirmation=confirmation)


def test_every_candidate_is_named_or_declined_or_the_reply_is_refused() -> None:
    """ADR-0346 §4:6: one left unaccounted refuses the reply as one that does not parse."""
    reading = _reading(hints=(_hint("C1", "effect-1"), _hint("C2", "effect-2")))

    refused = _proposal(reading, found(_CLAIM, "P1", candidates=["C1"]))
    kept = _proposal(
        reading,
        found(_CLAIM, "P1", candidates=["C1"]),
        declines=[{"candidate": "C2", "reason": "Trivia."}],
    )
    blank = _proposal(
        reading,
        found(_CLAIM, "P1", candidates=["C1"]),
        declines=[{"candidate": "C2", "reason": "  "}],
    )

    assert refused is None
    assert blank is None, "a decline gives a reason"
    assert kept is not None
    (finding,) = kept.findings
    assert finding.candidate == "effect-1"
    (decline,) = kept.declines
    assert (decline.candidate, decline.reason) == ("effect-2", "Trivia.")


def test_a_candidate_whose_finding_code_dropped_is_declined_by_code() -> None:
    """ADR-0346 §4:6: nothing planning recorded disappears unexplained."""
    reading = _reading(hints=(_hint("C1", "effect-1"),))

    proposal = _proposal(reading, found(_CLAIM, "P2", candidates=["C1"]))

    assert proposal is not None
    assert proposal.findings == ()
    (decline,) = proposal.declines
    assert (decline.candidate, decline.reason) == ("effect-1", DROPPED_REASON)


def test_a_finding_naming_several_candidates_accounts_for_each() -> None:
    reading = _reading(hints=(_hint("C1", "effect-1"), _hint("C2", "effect-2")))

    proposal = _proposal(reading, found(_CLAIM, "P1", candidates=["C1", "C2"]))

    assert proposal is not None
    (finding,) = proposal.findings
    assert (finding.candidate, finding.further_candidates) == ("effect-1", ("effect-2",))
    assert proposal.declines == ()


def test_two_labels_naming_one_candidates_effect_name_it_once() -> None:
    """ADR-0346 §4:6: two calls answered by one effect are one candidate on the record."""
    reading = _reading(hints=(_hint("C1", "effect-1"), _hint("C2", "effect-1")))

    proposal = _proposal(reading, found(_CLAIM, "P1", candidates=["C1", "C2"]))

    assert proposal is not None
    (finding,) = proposal.findings
    assert (finding.candidate, finding.further_candidates) == ("effect-1", ())
    assert (proposal.declines, proposal.dropped) == ((), 0)


def test_a_candidate_label_naming_nothing_shown_drops_the_finding() -> None:
    proposal = _proposal(_reading(), found(_CLAIM, "P1", candidates=["C7"]))

    assert proposal is not None
    assert (proposal.findings, proposal.dropped) == ((), 1)


def test_a_finding_naming_a_confirmed_candidate_rests_on_its_yes() -> None:
    """ADR-0329 §5:5: framing sees the words the user approved."""
    yes = ReadPart(
        handle="P3",
        part=ConfirmationPart(
            episode=address("leaving"),
            asking_activation="asking",
            question=QuestionPart(round="r-ask", part=1),
        ),
        episode=address("leaving"),
        occurred_at=AT,
        text=_CLAIM,
        origin=SupportOrigin.CONFIRMATION,
        when=AT,
    )
    reading = _reading(hints=(_hint("C1", "effect-1", confirmation=yes),))

    proposal = _proposal(reading, found("The user likes windows.", "P1", candidates=["C1"]))

    assert proposal is not None
    (finding,) = proposal.findings
    assert finding.rests_on == (InputPart(episode=address("leaving")), yes.part)


def test_the_scout_is_shown_its_instruction_and_the_reading_as_data() -> None:
    messages = scout_messages(
        _reading(), prompt_from(OBSERVER_SCOUT_PROMPT, "Scout.").rendered(flags={"person": False})
    )

    system, user = messages
    assert (system.role, system.content) == (Role.SYSTEM, "Scout.")
    assert user.role is Role.USER
    payload = json.loads(user.content)
    assert set(payload) == {"exchange", "earlier", "memories", "stories", "notes"}


def test_framing_and_placement_are_shown_their_instruction_and_their_view_as_data() -> None:
    reading = _reading()
    leaving = reading.record
    finding = _proposal(reading, found(_CLAIM, "P1"))
    assert finding is not None
    view = FramingView(finding=finding.findings[0], leaving=leaving, parts=reading.leaving.parts)
    held = memory("m-seat", _CLAIM, said_support(address("past")))

    framed_messages = framing_messages(
        view, prompt_from(OBSERVER_FRAMING_PROMPT, "Frame.").rendered(flags={})
    )
    placed_messages = placement_messages(
        PlacementView(framed=held, texts={}, retrieved=()),
        prompt_from(OBSERVER_PLACEMENT_PROMPT, "Place.").rendered(flags={}),
    )

    assert framed_messages[0].content == "Frame."
    shown = json.loads(framed_messages[1].content)
    assert shown["claim"] == _CLAIM
    assert shown["subjects"] == ["the user"], "the owner is named as a model is shown it"
    assert "memories" not in shown, "no stored memory is shown to framing (§5:1)"
    assert placed_messages[0].content == "Place."
    assert set(json.loads(placed_messages[1].content)) == {"memory", "stored"}


@pytest.mark.parametrize(
    "field",
    ["scout_prompt", "framing_prompt", "placement_prompt"],
)
def test_the_observer_refuses_another_prompts_template(field: str) -> None:
    """ADR-0334 §2: each step renders its own prompt's template."""
    harness = Harness()
    wrong: dict[str, PromptDeclaration] = {
        "scout_prompt": OBSERVER_FRAMING_PROMPT,
        "framing_prompt": OBSERVER_PLACEMENT_PROMPT,
        "placement_prompt": OBSERVER_SCOUT_PROMPT,
    }
    prompts = {
        "scout_prompt": default_prompt(OBSERVER_SCOUT_PROMPT),
        "framing_prompt": default_prompt(OBSERVER_FRAMING_PROMPT),
        "placement_prompt": default_prompt(OBSERVER_PLACEMENT_PROMPT),
    }
    prompts[field] = default_prompt(wrong[field])

    with pytest.raises(ValueError, match="prompt"):
        Observer(
            scout=structured(FakeModelProvider.scripted()),
            commit=structured(FakeModelProvider.scripted()),
            memory=harness.memory,
            writes=harness.writes,
            plans=harness.plans,
            stories=harness.stories,
            episodes=RecentEpisodes(memory=harness.memory, limit=2),
            limits=limits(),
            now=harness.clock,
            scout_prompt=prompts["scout_prompt"],
            framing_prompt=prompts["framing_prompt"],
            placement_prompt=prompts["placement_prompt"],
        )
