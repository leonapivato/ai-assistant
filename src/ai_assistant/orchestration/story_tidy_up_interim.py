"""The engine's interim tidy-up run, test-hub scaffolding (ADR-0300 §5, "before the phases").

**Delete this module at the cutover.** Until the phases replace the turn loop, the
engine starts a tidy-up by rule, without waiting for it, for each story into which
the story-links stage (§6) links an activation and on whose page anything is
pending. It is scaffolding for the test hub, it is not an action under ADR-0292
§12:1-§12:2 in the scope ADR-0300's header gives, and it is **never** the phases'
route to the tidy-up: once they land, the tidy-up is a call planning chooses (§10:4)
and nothing adds it by rule.

Everything the rule needs is here, so removing it is this file, the engine's
``interim_tidy_up`` parameter with the one call after the story-links stage that
uses it, and the composition root's wiring of it — each of which names this module.
:class:`~ai_assistant.orchestration.story_tidy_up.StoryTidyUp` itself stays.

**Nobody waits for it** (§5:11). The engine hands each run to its own tracked task
and returns to the pass; a run's finishing starts nothing. **"Anything pending"** is
the run's own first read: a story with no note pending and no frozen episode pending
makes no completion and writes nothing, and the activation that linked it, still
open while it runs, stays pending for a later run (§5:2). **One run per story at a
time** is the operation's own rule, so a story linked by two activations at once is
tidied by the first and the second does not start (§5:10).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from ai_assistant.orchestration.story_links import StoryLinksDecision
    from ai_assistant.orchestration.story_tidy_up import StoryTidyUp

__all__ = ["InterimTidyUp"]

_log = structlog.get_logger(__name__)


class InterimTidyUp:
    """Start a tidy-up for each story the story-links stage linked into (ADR-0300 §5).

    Test-hub scaffolding, removed at the cutover; see the module docstring.
    """

    def __init__(self, *, tidy_up: StoryTidyUp) -> None:
        """Wire the rule to the operation it starts.

        Args:
            tidy_up: The tidy-up operation, the same one planning's call will reach.
        """
        self._tidy_up = tidy_up

    def runs(self, decision: StoryLinksDecision) -> tuple[Coroutine[None, None, None], ...]:
        """One run for each story the decision linked the activation into, each once.

        The stories it was linked into, a story it already belonged to included, and
        the story the rule start minted. A failed decision's links made before the
        failure stand in the store (§6:13), so they count too.

        Args:
            decision: The story-links stage's decision for the pass.

        Returns:
            The runs, for the caller to start without awaiting them.
        """
        started = () if decision.started is None else (decision.started,)
        return tuple(
            self._run(story_id) for story_id in dict.fromkeys((*decision.linked, *started))
        )

    async def _run(self, story_id: str) -> None:
        """Run one tidy-up, logging rather than raising whatever escapes it.

        Nobody awaits this coroutine's result, so an unexpected error is logged here
        rather than left for the event loop to report as never retrieved. It is
        logged by its class alone, with no message and no traceback: either could
        carry a note's or an episode's words (ADR-0275 §8).
        """
        try:
            await self._tidy_up.run(story_id)
        except Exception as exc:
            _log.error("story_tidy_up_crashed", stage="tidy_up", error=type(exc).__name__)
