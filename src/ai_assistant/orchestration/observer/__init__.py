"""The observer: memory's one writer, a background stage (ADR-0329 §§7-17).

When an episode leaves the episode window, the observer reads it with what came after
(``reading``), proposes findings in one broad call (``scout``), decides each in a narrow
call that sees only what the finding rests on (``commit``), writes what it decides
through the write stage (``writing``), and records what it did beside the episode on
the plan store's observation record (``stage``). Its two instructions are templates
shipped beside ``prompts``, which declares them (ADR-0334).

**A background stage, not an activation** (§7:4, §15:1). It records no episode, links
nothing to a story and adds nothing the episode selector reads. Its writes are
background maintenance of the assistant's records: planning does not choose them,
authorizing does not check them, and they run on no channel (§15:5). A model call it
makes is processing, through ``models/`` and its egress rule (§15:6), on the two routes
it holds by injection.

**No ``Protocol``, nothing in ``learning/``** (§15:2). It lives here, in
``orchestration``, holding contracts by injection like every other stage. It reads no
held result: an import-linter contract forbids its modules importing
``orchestration.held_results`` (§15:4).

**Built and tested, not yet wired.** The composition root builds it, its settings and
its scheduler row in the lane that turns ``remember``'s candidates on (§19:3); until
then nothing constructs :class:`Observer`.
"""

from __future__ import annotations

from ai_assistant.orchestration.observer.stage import Observer, ObserverLimits, RunOutcome

__all__ = ["Observer", "ObserverLimits", "RunOutcome"]
