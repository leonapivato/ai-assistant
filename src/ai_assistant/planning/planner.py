r"""The model-backed planner (ADR-0047).

The production :class:`~ai_assistant.core.protocols.Planner`: it turns a
:class:`~ai_assistant.core.types.Goal` (plus assembled ``context`` and retrieved
``memories``) into a frozen :class:`~ai_assistant.core.types.ActionPlan` by
prompting an injected :class:`~ai_assistant.core.protocols.ModelProvider` for a
JSON envelope and extracting that text into ``PlanStep``\ s.

Two boundaries from ADR-0014 shape the whole module:

- A step names an **abstract capability**, not a tool. This module imports
  nothing from ``tools`` and validates a capability only as a non-blank
  identifier (ADR-0014 §2).
- Model output **never sets execution status** (VISION §7). The planner produces
  an ``ActionPlan`` and nothing else; ids, timestamps and every ``StepStatus``
  stay the property of deterministic code.

Step ids and the plan id are minted here from an injected id factory, never taken
from the model, so unique step ids are guaranteed structurally and the model is
kept out of the id space entirely (ADR-0047 §2).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import ActionPlan, Message, PlanStep, Role

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import CurrentContext, Goal, MemoryRecord

#: Total ``complete`` calls a single ``plan`` may make: one initial request plus
#: one bounded repair round (ADR-0047 §6). The constructor rejects anything < 1.
#: Named distinctly from ``execution.DEFAULT_MAX_ATTEMPTS`` (the retry ceiling),
#: which is a different bound.
DEFAULT_PLAN_ATTEMPTS = 2

#: The most decode **misses** :func:`_extract_object` tolerates in one reply before
#: giving up. A failed ``raw_decode`` costs work proportional to how far into the
#: reply it reached (``JSONDecodeError`` computes a line and column), so attempting
#: it at every brace of a brace-dense malformed reply is quadratic and blocks the
#: event loop; bounding the misses keeps the scan linear. A *decoded* object never
#: counts, so any number of valid JSON fragments may precede the envelope — only
#: unparseable braces are limited. Generous, so a conforming or lightly-wrapped
#: reply is never lost to it; only a reply burying the envelope behind more than
#: this many unparseable braces degrades to bounded repair.
_MAX_EXTRACTION_MISSES = 256

_SYSTEM_PROMPT = """\
You are the planning stage of an AI assistant. Decompose the user's goal into an \
ordered sequence of steps that would accomplish it.

Each step names an abstract CAPABILITY — what must be done — not a specific tool, \
product, or vendor. Use short snake_case names such as `send_email`, \
`search_calendar`, or `book_flight`. Do not name a concrete tool or service.

Reply with a single JSON object and nothing else — no prose, no code fence:

{"rationale": "<one sentence on why these steps>",
 "steps": [
   {"intent": "<human-readable purpose of this step>",
    "capability": "<abstract_capability>",
    "parameters": {"<name>": "<json value>"}}
 ]}

`steps` must be a non-empty list. `parameters` is optional per step and, when \
present, must be a JSON object. Do not include step ids; they are assigned \
downstream."""


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _ExtractionError(Exception):
    """An internal signal that a model reply could not become an ``ActionPlan``.

    Caught within :meth:`ModelBackedPlanner.plan` to drive the bounded repair
    round; converted to :class:`PlanningError` if the attempts are exhausted. Not
    part of the public surface.
    """


class ModelBackedPlanner:
    """A ``Planner`` that decomposes a goal into capabilities with an LLM.

    Structurally implements :class:`~ai_assistant.core.protocols.Planner`. The
    model proposes each step's ``intent``, ``capability`` and ``parameters``; this
    class mints the ids, stamps the timestamp, validates the result into a frozen
    :class:`~ai_assistant.core.types.ActionPlan`, and owns the failure handling
    (ADR-0047).
    """

    def __init__(
        self,
        model: ModelProvider,
        *,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
        max_attempts: int = DEFAULT_PLAN_ATTEMPTS,
    ) -> None:
        """Create a planner over an injected model, clock and id factory.

        Args:
            model: The model seam used to draft the plan. The only dependency on
                the LLM; no provider SDK is imported (golden rule 4).
            now: Clock for ``ActionPlan.created_at``; injectable for deterministic
                tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §7), so a
                non-conforming reading surfaces as ``PlanningError``.
            id_factory: Mints the plan id and every step id; injectable so tests
                assert exact ids (ADR-0047 §2). Defaults to random UUIDs.
            max_attempts: Total ``complete`` calls one ``plan`` may make — one
                request plus up to ``max_attempts - 1`` bounded repair rounds
                (ADR-0047 §6). Must be an ``int`` of at least 1.

        Raises:
            TypeError: If ``max_attempts`` is not an ``int`` (``bool`` included).
            ValueError: If ``max_attempts`` is less than 1.
        """
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            msg = f"max_attempts must be an integer, got {max_attempts!r}"
            raise TypeError(msg)
        if max_attempts < 1:
            msg = f"max_attempts must be at least 1, got {max_attempts}"
            raise ValueError(msg)
        self._model = model
        self._clock = checked_clock(now, owner="ModelBackedPlanner")
        self._id_factory = id_factory
        self._max_attempts = max_attempts

    def _now(self) -> datetime:
        """The guarded clock's reading, translated to this subsystem's error.

        Raises:
            PlanningError: If the injected clock's reading is not a conforming one
                — naive, indeterminate, or outside the localizable range
                (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise PlanningError(str(exc)) from exc

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        """Produce a frozen plan for ``goal`` (ADR-0047).

        Prompts the model for a JSON envelope, extracts and validates it into a
        plan, and retries once on malformed output before giving up. ``context``
        and ``memories`` are rendered into the prompt — the memories are what make
        the plan personal (ADR-0014 §6) — and are never fetched here.

        ``goal`` is observed **once**, on this coroutine's first executed line and
        before the first ``await`` (ADR-0065). ``Goal`` is mutable, the model call
        is the widest suspension window in the system, and a caller that mutated
        its own instance mid-flight would otherwise get an ``ActionPlan`` whose
        frozen, auditable ``goal_id`` names a goal the model was never shown. The
        prompt, the plan's ``goal_id`` and the failure message all derive from
        that one snapshot. ``context`` and ``memories`` need no snapshot: they are
        read once, into the prompt, before the same first ``await`` and never
        again — the other discharge the clause allows.

        Args:
            goal: The objective to plan for.
            context: The situational context assembled for this request.
            memories: Records retrieved as relevant to the goal, best first.

        Returns:
            A frozen :class:`~ai_assistant.core.types.ActionPlan` for ``goal``.

        Raises:
            PlanningError: If no valid plan could be extracted within
                ``max_attempts`` model calls, or if the injected clock misreads.
            ModelError: Propagated unwrapped from the provider — a transport,
                auth, rate-limit or content-filter failure is already a typed,
                actionable error and is not flattened into ``PlanningError``
                (ADR-0047 §6).
        """
        # Deep, so nothing nested stays shared with the caller's instance; a
        # `model_copy(update=...)` here would be shallow and would not detach it.
        snapshot = goal.model_copy(deep=True)
        conversation: list[Message] = [
            Message(role=Role.SYSTEM, content=_SYSTEM_PROMPT),
            Message(role=Role.USER, content=_render_request(snapshot, context, memories)),
        ]

        last_error: _ExtractionError | None = None
        for _ in range(self._max_attempts):
            reply = await self._model.complete(conversation)
            try:
                return self._build_plan(reply.content, snapshot)
            except _ExtractionError as exc:
                last_error = exc
                conversation.append(reply)
                conversation.append(
                    Message(role=Role.USER, content=_repair_prompt(str(exc))),
                )

        msg = f"the model did not return a usable plan for goal {snapshot.id}: {last_error}"
        raise PlanningError(msg)

    def _build_plan(self, content: str, goal: Goal) -> ActionPlan:
        """Extract and validate one model reply into a frozen ``ActionPlan``.

        Raises:
            _ExtractionError: If the text is not the required envelope or the
                constructed plan fails a ``core`` invariant.
        """
        envelope = _extract_object(content)
        raw_steps = _require_steps(envelope)
        rationale = _optional_rationale(envelope)

        step_payloads = [self._step_payload(raw, index) for index, raw in enumerate(raw_steps)]
        try:
            return ActionPlan.model_validate(
                {
                    "id": self._id_factory(),
                    "goal_id": goal.id,
                    "steps": step_payloads,
                    "created_at": self._now(),
                    "rationale": rationale,
                }
            )
        except ValidationError as exc:
            msg = f"the drafted plan is not a valid ActionPlan: {exc}"
            raise _ExtractionError(msg) from exc

    def _step_payload(self, raw: object, index: int) -> PlanStep:
        """Validate one raw step object into a ``PlanStep`` with a minted id.

        Raises:
            _ExtractionError: If the step is not an object with the required
                fields, or fails a ``PlanStep`` invariant (e.g. a blank
                capability, or non-serialisable parameters).
        """
        if not isinstance(raw, dict):
            msg = f"step {index} is not a JSON object"
            raise _ExtractionError(msg)

        intent = raw.get("intent")
        capability = raw.get("capability")
        if not isinstance(intent, str):
            msg = f"step {index} is missing a string 'intent'"
            raise _ExtractionError(msg)
        if not isinstance(capability, str):
            msg = f"step {index} is missing a string 'capability'"
            raise _ExtractionError(msg)

        parameters = raw.get("parameters", {})
        if not isinstance(parameters, dict):
            msg = f"step {index} has non-object 'parameters'"
            raise _ExtractionError(msg)

        try:
            return PlanStep.model_validate(
                {
                    "id": self._id_factory(),
                    "intent": intent,
                    "capability": capability,
                    "parameters": parameters,
                }
            )
        except ValidationError as exc:
            msg = f"step {index} is not a valid PlanStep: {exc}"
            raise _ExtractionError(msg) from exc


def _render_request(
    goal: Goal,
    context: CurrentContext,
    memories: Sequence[MemoryRecord],
) -> str:
    """Render the goal, context and memories into the user-turn prompt.

    The memories are rendered one line each, tagged with kind and provenance
    source, because passing the retrieved user model into the prompt is what makes
    a plan personal rather than generic (ADR-0014 §6).
    """
    lines = [
        "Goal:",
        f"  statement: {goal.statement}",
        f"  status: {goal.status.value}",
        f"  provenance: {goal.provenance.source.value}",
    ]
    if goal.deadline is not None:
        lines.append(f"  deadline: {goal.deadline.isoformat()}")

    lines += [
        "",
        "Current context:",
        f"  now: {context.now.isoformat()}",
        f"  time_of_day: {context.time_of_day.value}",
        f"  is_weekend: {context.is_weekend}",
        f"  within_working_hours: {context.within_working_hours}",
        "",
    ]

    if memories:
        lines.append("Relevant memories about the user:")
        lines += [
            f"  - [{record.kind}/{record.provenance.source.value}] {record.content}"
            for record in memories
        ]
    else:
        lines.append("No stored memories were retrieved for this goal.")

    return "\n".join(lines)


def _repair_prompt(reason: str) -> str:
    """The user turn that asks the model to fix a malformed reply."""
    return (
        f"That response could not be used: {reason}. "
        "Reply with only the JSON object described earlier — no prose, no code "
        "fence — with a non-empty `steps` list."
    )


def _extract_object(content: str) -> dict[str, object]:
    """Decode the JSON envelope embedded in ``content``.

    Scans each ``{`` in ``content`` left to right and attempts to decode an object
    starting there with :meth:`json.JSONDecoder.raw_decode`, which stops at the end
    of the object and ignores any trailing text (ADR-0071). This tolerates a model
    that wraps the object in prose or a Markdown code fence — the goal ADR-0047 §4
    states — including prose that itself contains a brace, which the ADR-0047 §4
    step 1 first-``{``-to-last-``}`` slice ADR-0071 supersedes misreads by spanning
    the prose brace and the envelope's closer at once (#293).

    Where more than one object decodes, the **envelope** is preferred: the first
    whose ``steps`` is a non-empty list — the shape ADR-0047 §4 step 2 requires and
    :func:`_require_steps` accepts — rather than the leftmost object outright, so a
    decoy object in the prose ahead of the envelope is stepped over instead of
    planned from, including one that carries a ``steps`` key of the wrong type or an
    empty list (which would otherwise shadow a valid envelope behind it). Where no
    decoded object is a well-formed envelope, the first decoded object stands in, so
    a single malformed one still reaches :func:`_require_steps` and its precise
    verdict rather than a generic miss. Two genuine envelopes cannot be told apart
    locally and the earlier wins; the outcome stays bounded and is never a corrupt
    plan.

    **A decoded object is advanced *past*, never re-entered:** the scan resumes at
    the object's end, so a nested object is treated as part of its parent, not as a
    separate candidate. An outer envelope whose ``steps`` is empty is therefore
    rejected as an empty plan (§4) rather than being overridden by a non-empty
    ``steps`` nested inside it. Only a brace that does *not* open a decodable object
    — a brace in the surrounding prose, or a fragment — is stepped over one
    character at a time to the next brace.

    A candidate that raises for a bounded reason that is *not* a syntax miss is a
    miss like any other: the digit-limit ``ValueError`` CPython raises for an
    over-limit integer literal and the ``RecursionError`` a pathologically nested
    payload raises are caught here, so no unhandled error escapes and the scan
    carries on to the next brace. A well-formed envelope elsewhere in the reply is
    still found; only where the whole reply yields no envelope does it fall to
    bounded repair.

    At most :data:`_MAX_EXTRACTION_MISSES` decode **misses** are tolerated before
    extraction gives up, which keeps the scan linear. A failed ``raw_decode`` is
    cheap to parse but costs work proportional to how far into the reply it reached
    (``JSONDecodeError`` computes a line and column), so attempting it at *every*
    brace of a brace-dense malformed reply is quadratic and would block the event
    loop this runs synchronously on; bounding the misses bounds that. A decoded
    object does not count as a miss and does not consume the budget, so any number
    of valid JSON fragments may precede the envelope — only unparseable braces are
    limited. The bound is generous, so a conforming reply (whose envelope is the
    first decodable object) is unaffected; a reply that buries the envelope behind
    more than :data:`_MAX_EXTRACTION_MISSES` unparseable braces degrades to bounded
    repair rather than to a stall.

    Raises:
        _ExtractionError: If no decodable object is found within the miss budget.
    """
    decoder = json.JSONDecoder()
    first: dict[str, object] | None = None
    misses = 0
    index = 0
    length = len(content)
    while index < length:
        if content[index] != "{":
            index += 1
            continue
        try:
            # raw_decode from the brace: ValueError covers JSONDecodeError (a
            # subclass) *and* the digit-limit ValueError; RecursionError a
            # pathologically nested payload.
            candidate, end = decoder.raw_decode(content, index)
        except ValueError, RecursionError:
            misses += 1
            # `> budget`, not `>=`: exactly `_MAX_EXTRACTION_MISSES` misses are
            # tolerated (the docstring's "up to"); only the miss *beyond* the budget
            # gives up. Still bounds the worst-case scan to linear time.
            if misses > _MAX_EXTRACTION_MISSES:
                break
            index += 1  # this brace opened nothing usable; try the next one
            continue
        if isinstance(candidate, dict):
            steps = candidate.get("steps")
            if isinstance(steps, list) and steps:
                # A well-formed envelope (a non-empty `steps` list, exactly what
                # `_require_steps` accepts). Preferred over an earlier decoy that
                # only looks envelope-shaped — a `steps` of the wrong type or empty.
                return candidate
            if first is None:
                first = candidate
        index = end  # resume past the decoded object; never re-enter its interior

    if first is not None:
        return first
    msg = "no JSON object found in the model reply"
    raise _ExtractionError(msg)


def _require_steps(envelope: dict[str, object]) -> list[object]:
    """Return the envelope's non-empty ``steps`` list.

    Raises:
        _ExtractionError: If ``steps`` is missing, not a list, or empty.
    """
    steps = envelope.get("steps")
    if not isinstance(steps, list):
        msg = "the plan envelope has no 'steps' list"
        raise _ExtractionError(msg)
    if not steps:
        msg = "the plan has no steps"
        raise _ExtractionError(msg)
    return steps


def _optional_rationale(envelope: dict[str, object]) -> str | None:
    """Return the envelope's ``rationale`` if it is a string, else ``None``.

    Raises:
        _ExtractionError: If ``rationale`` is present but neither a string nor
            null.
    """
    rationale = envelope.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        msg = "'rationale' must be a string or null"
        raise _ExtractionError(msg)
    return rationale


__all__ = ["DEFAULT_PLAN_ATTEMPTS", "ModelBackedPlanner"]
