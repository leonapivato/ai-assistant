"""The observer: memory's one writer, a background stage (ADR-0329 §§7-17, ADR-0346).

When an episode leaves the episode window, the observer reads its record and what that
record points at, each as it stood then (``reading``), proposes findings in one call with
what it knows of the person (``scout``), frames each finding into the memories its parts
bear out in a narrow call that sees only them (``framing``), retrieves what is stored like
each memory and names how it stands to each in a call of its own (``placement``), proposes
each through the write stage as a placed proposal (``writing``), and records what it did
beside the episode on the plan store's observation record (``stage``). Its three
instructions are templates shipped beside ``prompts``, which declares them (ADR-0334).

**A background stage, not an activation** (ADR-0329 §7:4, §15:1). It records no episode,
links nothing to a story and adds nothing the episode selector reads. Its writes are
background maintenance of the assistant's records: planning does not choose them,
authorizing does not check them, and they run on no channel (§15:5). A model call it
makes is processing, through ``models/`` and its egress rule (§15:6), on the two routes
it holds by injection.

**No ``Protocol``, nothing in ``learning/``** (§15:2). It lives here, in
``orchestration``, holding contracts by injection like every other stage. It reads no
held result: an import-linter contract forbids its modules importing
``orchestration.held_results`` (§15:4).
"""

from __future__ import annotations

from ai_assistant.orchestration.observer.stage import Observer, ObserverLimits, RunOutcome

__all__ = ["Observer", "ObserverLimits", "RunOutcome"]
