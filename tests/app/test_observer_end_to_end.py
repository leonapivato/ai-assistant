"""The observer wired and on, driven end to end through the production root (ADR-0346).

#3154's first scenario, in process: "remember I'm allergic to peanuts" records a
candidate (§3:1), which the panel shows pending (§18:1); once ten more activations have
pushed its episode out of the episode window, the run the last freeze starts (§7:6)
reads the episode's record (ADR-0346 §2), scouts it, frames the memory and, with nothing
stored like it, proposes it with nothing to place (§5, §6), at "you said it", citing the
user's message; it records the episode processed (§16:1), and the candidate is pending no
more.

The substitutes are the model-facing seams alone, as every ``tests/app`` phases suite
substitutes them (:mod:`phases_composition_support`): planning's rounds are scripted, and
the provider's ``complete`` answers understanding with a stated reading and the
observer's steps from what each is shown. **No call leaves the process**, and
nothing contacts a hub.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

from phases_composition_support import (
    UNDERSTANDING_INSTRUCTIONS,
    build_phased,
    structured_through,
    until,
)

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    InputPart,
    Memory,
    MemoryOperationKind,
    MemoryStanding,
    ObservationState,
    ObserverStep,
    ProposedCall,
    Role,
    RoundResponse,
    SupportOrigin,
)
from ai_assistant.core.types import Message as ModelMessage
from ai_assistant.models import PydanticAIProvider
from ai_assistant.orchestration.observer.prompts import (
    OBSERVER_FRAMING_PROMPT,
    OBSERVER_SCOUT_PROMPT,
)
from ai_assistant.testing import FakeToolCallingCompleter, default_renderings

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import pytest

    from ai_assistant.core.types import Message, OfferedTool, PlanningExchange

_FACT: Final = "The user is allergic to peanuts."
_ASKED: Final = "remember I'm allergic to peanuts"
_UNDERSTOOD: Final = json.dumps({"understanding": "As said."})
#: The observer's steps' calls, told apart by their default's renderings, not words.
_SCOUT: Final = default_renderings(OBSERVER_SCOUT_PROMPT)
_FRAMING: Final = default_renderings(OBSERVER_FRAMING_PROMPT)


class _Planning:
    """Planning's rounds: ``remember`` on the request, then a plain reply to everything.

    Each reply is a ``text`` call (a round's own text is its notes alone, ADR-0356 §7:3),
    and each work's round after its first proposes nothing, so the work ends.
    """

    def __init__(self) -> None:
        self.recorded = False

    def __call__(self, exchange: PlanningExchange, _tools: Sequence[OfferedTool]) -> RoundResponse:
        if exchange.steps:
            return RoundResponse()
        if _ASKED in exchange.briefing and not self.recorded:
            self.recorded = True
            call = ProposedCall(
                call_id="c1",
                name="remember_fact",
                arguments={"fact": _FACT, "why": "health", "rests_on_this_stimulus": True},
            )
            return RoundResponse(calls=(_text("Got it, I'll remember."), call))
        return RoundResponse(calls=(_text("Noted."),))


def _text(words: str) -> ProposedCall:
    return ProposedCall(
        call_id="say", name="send_text", arguments={"connection": "L1", "words": words}
    )


class _Models:
    """The provider's ``complete``: understanding, the scout and framing."""

    def __init__(self) -> None:
        self.steps: list[ObserverStep] = []
        self.scouted: list[dict[str, Any]] = []

    def __call__(self, messages: Sequence[Message]) -> str:
        system = messages[0].content
        if system in UNDERSTANDING_INSTRUCTIONS:
            return _UNDERSTOOD
        if system in _SCOUT:
            self.steps.append(ObserverStep.SCOUT)
            return self._scout(json.loads(messages[-1].content))
        if system in _FRAMING:
            self.steps.append(ObserverStep.FRAMING)
            return self._frame(json.loads(messages[-1].content))
        return "Noted."

    def _scout(self, shown: dict[str, Any]) -> str:
        self.scouted.append(shown)
        leaving = shown["exchange"]
        findings = [
            {
                "claim": hint["fact"],
                "rests_on": [
                    part["part"] for part in leaving["parts"] if part["from"] == "the user"
                ],
                "candidates": [hint["candidate"]],
                "subjects": ["the user"],
                "involved": [],
                "why": "Health.",
                "situations": ["choosing where to eat"],
            }
            for hint in leaving["candidates"]
        ]
        return json.dumps({"findings": findings, "declines": []})

    def _frame(self, shown: dict[str, Any]) -> str:
        supports = [
            {"part": part["part"], "direction": "for", "backs_as_worded": True, "how_sure": "sure"}
            for part in shown["parts"]
        ]
        memory = {
            "wording": shown["claim"],
            "supports": supports,
            "subjects": ["the user"],
            "involved": [],
            "labels": ["choosing where to eat"],
        }
        return json.dumps({"memories": [memory]})


async def test_a_request_to_remember_is_pending_then_kept_once_it_leaves_the_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3, §7, §9, §11:1, §12, §16, §18:1, through the composed engine."""
    planning = _Planning()
    phased = build_phased(tmp_path, monkeypatch, completer=FakeToolCallingCompleter(planning))
    models = _Models()

    async def complete(
        _self: PydanticAIProvider, messages: Sequence[Message], *, model: str | None = None
    ) -> Message:
        del model
        return ModelMessage(role=Role.ASSISTANT, content=models(messages))

    monkeypatch.setattr(PydanticAIProvider, "complete", complete)
    monkeypatch.setattr(PydanticAIProvider, "complete_structured", structured_through(complete))
    engine = phased.engine
    plans = engine._plans
    try:
        await engine.start()
        conversation = await phased.start_conversation()
        asked = await phased.say(_ASKED, conversation)

        assert "Got it, I'll remember." in await phased.answered(conversation)
        (pending,) = await engine.pending_candidates()
        assert (pending.episode_id, pending.fact) == (asked.address, _FACT)
        assert [one for one in await phased.memory.export() if isinstance(one, Memory)] == []

        # Nine more: the window holds ten, so the request's episode is still in it.
        for turn in range(9):
            await phased.say(f"thanks, number {turn}", conversation)
        assert models.steps == [], "nothing has left the window, so nothing was read"
        assert await plans.observations([asked.address]) == ()

        # The tenth pushes it out, and the run its freeze starts commits it.
        await phased.say("one more thing", conversation)

        async def processed() -> bool:
            held = await plans.observations([asked.address])
            return bool(held) and held[0].state is ObservationState.PROCESSED

        await until(processed, what="the request's episode to be processed")
        (record,) = await plans.observations([asked.address])
        (attempt,) = record.attempts
        assert [one.step for one in attempt.calls] == [ObserverStep.SCOUT, ObserverStep.FRAMING]
        (finding,) = record.findings
        assert finding.candidate is not None
        assert finding.written == ()
        assert finding.outcome is not None
        (write,) = finding.outcome.writes
        assert write.operations == (MemoryOperationKind.CREATE,)

        kept = await phased.memory.get(write.memory)
        assert isinstance(kept, Memory)
        assert (kept.content, kept.subjects, [one.text for one in kept.labels]) == (
            _FACT,
            (OWNER_PERSON_ID,),
            ["choosing where to eat"],
        )
        assert kept.standing is MemoryStanding.SAID
        (support,) = kept.supports
        assert support.origin is SupportOrigin.USER_MESSAGE
        assert isinstance(support.points_at, InputPart)
        assert support.points_at.episode == asked.address
        assert support.added_by.value == "observer"
        # The scout read the request's own words, quoted, with its candidate as a hint.
        (shown,) = models.scouted
        assert any(_ASKED in part["text"] for part in shown["exchange"]["parts"])
        assert engine._observer is not None
        assert await engine.pending_candidates() == ()
    finally:
        await engine.aclose()
