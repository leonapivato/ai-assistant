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

The envelope has **two** legal shapes (ADR-0176 §1). A plan carries a non-empty
``steps`` list; a **decline** carries an empty one *together with*
``"no_capability_needed": true`` and a non-blank ``rationale``, and says that the
goal is answered from what this turn already carries. The second shape is asserted
rather than merely empty, which is what tells it apart from a failure to
decompose — the objection ADR-0047 §4 raised against a bare empty list, and one
that has no purchase on a positive assertion. ``no_capability_needed`` is a key of
this prompt-level envelope only: it never reaches ``ActionPlan``, which crosses the
subsystem boundary carrying empty ``steps`` and a ``rationale`` saying why
(ADR-0176 §8).

**A statement of fact is a decline** (#1695). It asks for nothing, so it wants no
capability, and the prompt works that direction of ADR-0176 §4's test through
explicitly — including what the rationale should say, since on a decline the
rationale is the whole of the plan's content (ADR-0176 §3) and it is what the
composing stage renders (#1355). It is an acknowledgement and not a receipt: this
stage runs before the exchange is recorded, and that write can fail (ADR-0074 §3),
so the rationale claims nothing about retention in either direction.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActionPlan,
    BeliefBand,
    EpisodicMemory,
    MemoryKind,
    Message,
    PlanStep,
    Role,
    band_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import (
        CalendarFacet,
        ContextFacet,
        CurrentContext,
        EmailFacet,
        Goal,
        MemoryRecord,
    )

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

#: The heading the chronological conversation tail is printed under (ADR-0074 §5).
_TAIL_HEADING: Final = "Recent conversation turns, in order:"

#: The heading the relevance-retrieved group is printed under (ADR-0074 §5).
#:
#: Named rather than inlined because it is read outside this module: the benchmark
#: harness assembles the same block for its answering prompt and imports this
#: instead of spelling it a second time (#1181). It stays private — the harness
#: reads a private name knowingly, which is cheaper than widening ``planning``'s
#: public surface for a driver that is not a subsystem.
_RETRIEVED_HEADING: Final = "Relevant memories about the user:"

#: What each band's records are introduced as, for the non-episodic kinds
#: (ADR-0072 §6). One clause per band, saying whose claim the content is: the
#: user's own word, this system's own conclusion, or a connected source's report.
#: §6 fixes *what the assembler must convey* — the band and the confidence — and
#: leaves the wording here, so these are phrases a reader needs no vocabulary for,
#: unlike the ``[kind/source]`` tag they sit beside.
_STANCE: Final[Mapping[BeliefBand, str]] = {
    BeliefBand.ASSERTED: "the user stated",
    BeliefBand.DERIVED: "the assistant believes",
    BeliefBand.ATTESTED: "a source the user connected reported",
}

#: The stated-fact direction of ADR-0176 §4's test, worked through (#1695).
#:
#: A statement of fact asks for nothing, so under §4's test it wants no capability
#: — but the prompt's decline condition reads "answered from what this turn already
#: carries", and a model applying that literally to *"did you know I go to school at
#: Northeastern"* finds nothing to answer and plans a store step instead. On the
#: deployed hub it planned one; nothing carries a memory write (intake is the
#: observer's, ADR-0093, and ADR-0048 §1 declines ``remember`` in terms), so the
#: step reached ``NO_CAPABLE_TOOL`` and ADR-0170 §5's honest account made the reply
#: tell the owner it had no way to remember — false, because ADR-0074 §3 captures
#: every turn as an episode and the belief lands when the observer runs.
#:
#: This block is the decline's *rationale* as much as its shape: ADR-0176 §3 makes
#: the rationale the whole of a declined plan's content, and ``composing``'s
#: ``_render_plan`` renders it on a decline (#1355), so what this asks the model to
#: say is what reaches the composed reply.
#:
#: **It asks the model to acknowledge, never to promise retention**, and the
#: distinction is load-bearing rather than fastidious. Planning runs *before* the
#: exchange is recorded — ``Engine`` composes and only then captures — and ADR-0074
#: §3 makes that write fallible in terms: "a memory-store failure — an embedder
#: fault, a locked database — leaves a turn recorded with **no** episode … and the
#: failure is **reported on the outcome**". A rationale asserting the statement *is*
#: kept would therefore be a claim about something that has not happened yet and
#: can fail, contradicted in the same turn by the outcome that reports the failure.
#: That is the very defect this block exists to remove, pointed the other way. So
#: the rationale says the statement was heard and that taking it in wants no
#: capability — both true at planning time — and asserts nothing about what becomes
#: of it, long-term memory included, since the observer's run is not this turn's
#: (ADR-0093).
#:
#: It is a separate constant so the prompt test can assert it **reaches the model**
#: without string-matching its wording, which ADR-0176 §4 declines to demand of any
#: lane: an assertion on a sentence "fails on every rewording that improves the
#: instruction and passes on every rewording that guts it".
_STATED_FACT_GUIDANCE = """\
Telling you something is not asking you to do something. Where the user states a \
fact about themselves, corrects one, or passes on news, and asks for nothing to be \
done with it, the goal requires no act: what was said is part of the conversation \
set out in the next message, and taking it in is not work a step performs. Reply \
with a DECLINE, and let the rationale say that you heard what the user told you \
and that no capability is needed for it. Do not name a capability for storing, \
saving or remembering it: no capability does that, and a step naming one finds no \
tool, which makes the answer tell the user there is no way to remember what they \
just said — which is false and is the mistake to avoid here. Do not go the other \
way either: recording this exchange happens after you, and separately, so the \
rationale must not say that what you were told has been saved, stored, or put into \
long-term memory."""

#: The two legal envelope shapes and the test between them (ADR-0176 §4).
#:
#: The test is stated as what the goal *requires*, never as a list of request
#: categories, because the material a goal might be answered from is rendered into
#: this same prompt one message below (:func:`_render_request`) — so "can this be
#: answered from what is in front of me?" is a question about the text the model is
#: already holding, and a category list is not (ADR-0176 §4). The stated-fact block
#: sits under the decline shape as one *direction* of that test worked through, in
#: the same requires-terms — the way §4's own prose names the two directions
#: concretely — and the general rule still closes the section.
_SYSTEM_PROMPT = (
    """\
You are the planning stage of an AI assistant. Decide what the user's goal \
requires, then reply with exactly one of the two JSON objects below — a single \
JSON object and nothing else, no prose, no code fence.

A step names an abstract CAPABILITY — what must be done — not a specific tool, \
product, or vendor. Use short snake_case names such as `send_email`, \
`search_calendar`, or `book_flight`. Do not name a concrete tool or service.

Where accomplishing the goal requires the assistant to act in the world, or to \
reach for something this turn has not already given you, decompose it into an \
ordered sequence of steps and reply with a PLAN:

{"rationale": "<one sentence on why these steps>",
 "steps": [
   {"intent": "<human-readable purpose of this step>",
    "capability": "<abstract_capability>",
    "parameters": {"<name>": "<json value>"}}
 ]}

Where the goal is answered from what this turn already carries — the retrieved \
memories, the assembled context and the conversation set out in the next message \
— no capability is wanted at all, and the reply is a DECLINE:

{"rationale": "<one sentence on why no capability is needed>",
 "steps": [],
 "no_capability_needed": true}

"""
    + _STATED_FACT_GUIDANCE
    + """

A decline is an ordinary, expected outcome — not a fallback, not an error, not a \
last resort. Naming a capability for a goal that needs none is the worse answer of \
the two. Judge which shape is wanted by what the goal requires, not by what kind \
of request it looks like.

In a plan, `steps` must be a non-empty list, and `parameters` is optional per step \
and, when present, must be a JSON object. In a decline, `steps` must be the empty \
list, `no_capability_needed` must be the JSON literal true (not 1, not "true"), \
and `rationale` must be a non-empty string. Do not include step ids; they are \
assigned downstream."""
)


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _ExtractionError(Exception):
    """An internal signal that a model reply could not become an ``ActionPlan``.

    Caught within :meth:`ModelBackedPlanner.plan` to drive the bounded repair
    round; converted to :class:`PlanningError` if the attempts are exhausted. Not
    part of the public surface.

    ``declined`` says whether the failed reply **carried the decline marker** and
    failed only ADR-0176 §3's rationale condition. It selects the repair message
    (:func:`_repair_prompt`), and it is a flag on the signal rather than a string
    match on the reason because §5 splits the two failures on evidence of intent:
    only a reply carrying the marker has said what it meant, so only there may the
    repair ask the model to complete the decline. Every other malformed reply —
    a bare empty ``steps`` list included — is unclassified, and its repair presents
    both shapes without naming either as the correction.
    """

    def __init__(self, message: str, *, declined: bool = False) -> None:
        """Record the reason and whether the reply asserted a decline.

        Args:
            message: What was wrong with the reply, echoed into the repair turn.
            declined: Whether the reply carried the ``no_capability_needed``
                marker and failed only the rationale condition (ADR-0176 §5).
        """
        super().__init__(message)
        self.declined = declined


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

        ``memories`` carries what the pipeline assembled for this turn, which
        ADR-0074 §5 widened from "relevant, best first" to the conversation's
        recent turns first and then the relevance-retrieved records. This planner
        renders the sequence **in the order it is handed** and reads no global
        ranking into it, which is exactly what that widening asks of a consumer
        (:meth:`~ai_assistant.core.protocols.Planner.plan`).

        Args:
            goal: The objective to plan for.
            context: The situational context assembled for this request.
            memories: The records the pipeline assembled for this turn — the
                conversation's recent turns in order, then records retrieved as
                relevant, best first within that group (ADR-0074 §5).

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
                    Message(
                        role=Role.USER,
                        content=_repair_prompt(str(exc), declined=exc.declined),
                    ),
                )

        msg = f"the model did not return a usable plan for goal {snapshot.id}: {last_error}"
        raise PlanningError(msg)

    def _build_plan(self, content: str, goal: Goal) -> ActionPlan:
        """Extract and validate one model reply into a frozen ``ActionPlan``.

        A **decline** — an empty ``steps`` list carrying the ``no_capability_needed``
        marker — is constructed by this same path with ``steps=()``, which is why
        ADR-0176 §1 keeps one envelope shape rather than two: the per-step
        validation below is vacuous over it and nothing else branches. Its
        ``rationale`` is required rather than optional (§3), because with no steps
        it is the whole of what the persisted plan says.

        The envelope's keys never reach ``model_validate``: the payload is an
        explicit five-key mapping, so ``no_capability_needed`` cannot leak into the
        durable ``ActionPlan`` (ADR-0176 §8). That is structural, not asserted.

        Raises:
            _ExtractionError: If the text is not one of the two legal envelopes or
                the constructed plan fails a ``core`` invariant.
        """
        envelope = _extract_object(content)
        raw_steps = _require_steps(envelope)
        rationale = _optional_rationale(envelope) if raw_steps else _require_rationale(envelope)

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

    The memories are rendered by :func:`_render_record`, each tagged with its kind,
    its provenance source, its band and its confidence, because passing the
    retrieved user model into the prompt is what makes a plan personal rather than
    generic (ADR-0014 §6). A record is one bullet; an episode that recorded an
    outcome adds one continuation line under its own bullet, which is why the
    groups are assembled by joining rendered records rather than counted as lines.

    ``memories`` carries two groups (ADR-0074 §5) and they are headed separately,
    because one header calling both "relevant memories" tells the model a
    chronological conversation tail is a relevance cut — the strain §5 refused to
    accept in the Protocol's wording. The records are rendered **in the order they
    were handed**, unchanged; the header is inserted at the boundary, nothing is
    reordered or dropped.

    ``context``'s facets are rendered by :func:`_render_facets` under the same
    "Current context:" heading as the four temporal scalars, and **below** them:
    the scalars are this system's own reading of its own clock, a facet is a
    source's report, and ADR-0098 §2 requires the two be distinguishable in the
    assembled prompt. A facet that is ``None`` contributes nothing at all — no
    line, no header, no mention of its source — because ADR-0096 §4 and ADR-0097
    §5 rule ``None`` the single absence that "does not distinguish unconfigured,
    disabled, never-read, ungranted, failed or empty".
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
    ]
    lines += _render_facets(context)
    lines.append("")

    if memories:
        turns, retrieved = _split_conversation_tail(memories)
        if turns:
            lines.append(_TAIL_HEADING)
            lines += [_render_record(record) for record in turns]
            if retrieved:
                lines.append("")
        if retrieved:
            lines.append(_RETRIEVED_HEADING)
            lines += [_render_record(record) for record in retrieved]
    else:
        lines.append("No stored memories were retrieved for this goal.")

    return "\n".join(lines)


def _render_facets(context: CurrentContext) -> list[str]:
    """Render the present facets of ``context``, or nothing at all.

    ``CurrentContext``'s facets are the only part of the assembled prompt this
    system did not itself author, so the block they land in is headed as a
    *report* and each one names the source that made it. That is ADR-0096 §7's
    floor — "a surface that presents a facet's content names the facet's
    ``source``, and may not present that content as the user's own statement, as
    this system's inference, or as a reading of our own clock" — and ADR-0098 §2's
    first clause read on the same spans.

    **An absent facet renders nothing, and the header is not printed either.**
    ADR-0096 §4 fixes ``None`` as the single absence and ADR-0097 §5 adds
    ungranted to what it hides; a header printed over an empty block would be this
    renderer reporting that a source *could* have spoken, which is the "grant
    conversation conducted by a field nobody designed" both sections forbid.

    Args:
        context: The assembled context whose facets are to be rendered.

    Returns:
        The block's lines, or an empty list when every facet is ``None``.
    """
    blocks: list[list[str]] = []
    if context.calendar is not None:
        blocks.append(_render_calendar_facet(context.calendar))
    if context.email is not None:
        blocks.append(_render_email_facet(context.email))
    if not blocks:
        return []

    lines = [
        "  Reported by the sources this system read for this request — each block",
        "  below is that source's own report, not the user's words and not this",
        "  system's own conclusion:",
    ]
    for block in blocks:
        lines += block
    return lines


def _render_calendar_facet(facet: CalendarFacet) -> list[str]:
    """Render one calendar facet's stamp and payload (ADR-0096 §6).

    ``next_starts_at`` being ``None`` is rendered as what §6 says it means — the
    reading found no later occurrence **within the window it covered** — and never
    as "there is nothing next", which §6 forbids a surface from presenting. That is
    also why ``covers_until`` is rendered unconditionally: it is the field §6
    carries so that a ``None`` here means something to a consumer who does not read
    ``Settings``.
    """
    lines = _render_facet_stamp(facet)
    lines.append(f"      entries in progress at that read: {facet.entries_in_progress}")
    if facet.next_starts_at is None:
        lines.append("      no later entry began within the window this reading covered")
    else:
        lines.append(
            f"      the next entry within that window begins at: {facet.next_starts_at.isoformat()}"
        )
    lines.append(
        "      the window this reading covered ended, exclusive, at: "
        f"{facet.covers_until.isoformat()}"
    )
    return lines


def _render_email_facet(facet: EmailFacet) -> list[str]:
    """Render one email facet's stamp and payload (ADR-0140 §6).

    The count's label says *parsed from the store*, because §6 rules that
    ``arrived_in_window`` "is not a claim about the account, is never presented as
    one, and no consumer may read it as a count of mail received" — the store is
    written by a fetcher outside this system whose completeness the reader cannot
    verify. ``covers_from`` is rendered with it for ``covers_until``'s reason
    (ADR-0096 §6): a count means nothing without the interval it counted over, and
    the window's upper edge is ``read_at`` itself (ADR-0140 §3), already on the
    stamp line.
    """
    lines = _render_facet_stamp(facet)
    lines.append(
        "      messages this reader parsed from its own store, arriving since "
        f"{facet.covers_from.isoformat()}: {facet.arrived_in_window}"
    )
    return lines


def _render_facet_stamp(facet: ContextFacet) -> list[str]:
    """Render the source line every facet block opens with (ADR-0096 §2, §7).

    ``read_at`` is labelled as **this system's** read, never as the source's own
    instant, and ``as_of`` — the only instant the source itself declares — is
    rendered only when the source declared one. Where it is ``None`` the block says
    nothing whatever about when the source's picture was current, rather than
    substituting ``read_at`` for it: that substitution is exactly what ADR-0096 §7's
    second clause forbids, and for the two producers that exist ``as_of`` is always
    ``None``, so it is the live case rather than the defensive one.
    """
    lines = [
        f"    - the source {_quoted_span(facet.source)}, which this system read at "
        f"{facet.read_at.isoformat()}:"
    ]
    if facet.as_of is not None:
        lines.append(
            f"      the source says its own picture was current at: {facet.as_of.isoformat()}"
        )
    return lines


def _quoted_span(value: str) -> str:
    """Render one held string so it cannot write this renderer's own syntax.

    ADR-0098 §2 rules that a span's attribution is "not forgeable from inside the
    span" and that "an assembler that embeds a span in a syntax the serialised span
    can itself produce does not conform, whatever labels it emits". This block's
    syntax is line-oriented — a newline, an indent and a ``- the source`` bullet —
    and a facet's ``source`` is the one field of it that is free text:
    ``NonBlankEncodableText`` refuses a blank value and validates UTF-8
    encodability, and permits every newline and bracket in between.

    :func:`json.dumps` is the deterministic transform §2 admits, chosen over an
    invented one because its escaping is total for this target rather than
    plausible: at its default ``ensure_ascii=True`` the result is single-line,
    printable ASCII, delimited by quotes the value can no longer close. So no
    ``source`` — however it was constructed — can open a second bullet, forge a
    second source, or reopen the "Current context:" heading.

    :func:`_render_record` now applies it too, to the two spans a memory record
    controls. It used not to: ADR-0098 §9 states that obligation separately, on the
    prompt-assembly lane filed as #672, and the facet lane discharged §9's third
    bullet — §2 "for any facet field that is ever rendered into a prompt" — and
    nothing more. #672's planner half has since landed and reuses this function
    rather than inventing a second transform, which is the point of naming it here.
    ``observer._render_batch`` is still owed §2 and is what keeps #672 open.

    Args:
        value: The held string, verbatim as this system carries it.

    Returns:
        The quoted, escaped span to interpolate into a prompt line.
    """
    return json.dumps(value)


def _render_record(record: MemoryRecord) -> str:
    """Render one memory record as a prompt bullet, whole and non-forgeably.

    Three obligations meet on this function and are discharged together (#1194,
    #672), because each of them changes the same line and two of them are about the
    spans the third adds.

    **Every span the record controls is quoted** (ADR-0098 §2, §9). This block's
    syntax is line-oriented — a two-space indent, a ``-`` bullet, a ``[kind/source]``
    label, a four-space continuation line, and the two group headings
    :func:`_render_request` prints above it — and ``content`` and ``outcome`` are
    :data:`~ai_assistant.core.types.EncodableText`, which validates UTF-8
    encodability and permits every newline and bracket in between. Left raw, a
    record whose ``content`` carried a newline and a second bullet wrote a bullet
    **claiming a source of its choosing**, ``user_asserted`` included — the concrete
    defect #672 is, and the one ADR-0098 §2's second clause names as
    non-conformance "whatever labels it emits". :func:`_quoted_span` is the
    deterministic transform §2 admits, already used one function above for a
    facet's ``source``; here it is applied to the two spans a record supplies, so
    no record can open a second bullet, forge a label, or reopen a heading. The
    label itself stays derived from held data — ``kind``, ``source``, ``band_of``
    and ``confidence`` — and never from reading the text (§2's third clause).

    **A belief states the standing it is held with** (ADR-0072 §6). "A derived
    belief that reaches a prompt is rendered as a belief, carrying its band and its
    confidence … never as a bare fact indistinguishable from what the user stated",
    and §6 leaves the phrasing to this lane. So each bullet opens with the band, the
    confidence, and a stance clause naming who the record's claim belongs to: the
    user, this system, or a source the user connected. ``[kind/source]`` alone was
    the de facto stand-in, and it is a vocabulary a reader has to already know —
    ``inferred`` and ``observed`` both mean *the assistant worked this out*, and
    neither says so.

    **An episode is rendered whole** (#1194). ``occurred_at`` and ``outcome`` are
    fields capture writes and no prompt has ever shown, so a retrieved episode
    reached the model as a timeless half-exchange: nothing in the pipeline carried
    an instant to a model, and the reply to the recorded turn was dropped. Both are
    rendered here, and the ``outcome`` line is labelled *how it turned out* — the
    words ADR-0074 §4 gives the field — rather than as the assistant's reply.
    Product capture writes a disposition phrase there ("the selected tool ran",
    ``orchestration.engine._outcome_of``); it is the benchmark harness's ingestion
    that puts the other speaker's turn in it. One label has to be true of both, and
    §4's own is.

    **The instant is this prompt's own frame, which is UTC** (#1215). ADR-0156 §2's
    local-calendar clause is scoped in terms to *the observation prompt*, and §3's
    to resolving a relative expression at
    distillation; neither reaches ``planning``, which resolves nothing and holds no
    zone — ``CurrentContext`` carries none, and taking one would be a second
    timezone source to argue (ADR-0008 §6). What this renderer can be is
    *consistent*: ``context.now``, a facet's ``read_at``, a goal's ``deadline`` and
    every other instant in this prompt are ``isoformat()`` with their offset, so an
    episode's ``occurred_at`` is too, and the model can order it against ``now``
    without converting anything. Localising this one field beside a UTC ``now``
    would manufacture, inside a single prompt, the day-boundary error §3 exists to
    prevent.

    Args:
        record: The record to render, verbatim as this system holds it.

    Returns:
        The bullet — one line, plus one continuation line for an episode that
        recorded an outcome.
    """
    provenance = record.provenance
    band = band_of(provenance.source)
    standing = f"{band.value}, confidence {provenance.confidence:.2f}"
    label = f"  - [{record.kind}/{provenance.source.value}]"
    content = _quoted_span(record.content)

    if isinstance(record, EpisodicMemory):
        lines = [
            f"{label} ({standing}) the assistant recorded this exchange at "
            f"{record.occurred_at.isoformat()}: {content}"
        ]
        if record.outcome is not None:
            lines.append(f"    how it turned out: {_quoted_span(record.outcome)}")
        return "\n".join(lines)

    return f"{label} ({standing}) {_STANCE[band]}: {content}"


def _split_conversation_tail(
    memories: Sequence[MemoryRecord],
) -> tuple[Sequence[MemoryRecord], Sequence[MemoryRecord]]:
    """Split ``memories`` into the conversation tail and the retrieved records.

    The tail is the **leading run** of episodic records, not every episodic record:
    ADR-0074 §5 puts the conversation's recent turns first and the
    relevance-retrieved records after, and a prefix split is the only reading of
    that order which cannot reorder the sequence. A partition by kind could.

    **That case has landed, and this split is what it was written to expect.**
    ADR-0158 admits an episodic *supplement* — a second relevance read, under its
    own budget, appended after the retrieved beliefs — so an episode retrieved by
    relevance now arrives after the tail and stays in the trailing group, which is
    the group it belongs to. The belief composition still excludes ``EPISODIC``
    (ADR-0074 §6), so any belief at all between the tail and the supplement is the
    separator that keeps the two apart.

    Where the belief composition is **empty** there is no separator, and this split
    would put the supplement's episodes in the tail — rendering conversations weeks
    old as this one's recent turns. ADR-0158 §4 answers that where it is decidable,
    in ``orchestration``: the supplement is dropped unless something non-``EPISODIC``
    precedes it. Nothing is owed here, and nothing here can tell the two apart —
    which is why the clause lives there and why carrying an explicit boundary
    instead would be a ``Planner`` contract change taking its own ADR.

    Args:
        memories: The records the pipeline assembled for this turn.

    Returns:
        The leading episodic run, then everything after it. Either may be empty.
    """
    boundary = 0
    for record in memories:
        # Via the enum, as `memory.policy` does: the discriminator is a `Literal`
        # str, so comparing it to a member directly is a non-overlapping check.
        if MemoryKind(record.kind) is not MemoryKind.EPISODIC:
            break
        boundary += 1
    return memories[:boundary], memories[boundary:]


def _repair_prompt(reason: str, *, declined: bool = False) -> str:
    """The user turn that asks the model to fix a malformed reply (ADR-0176 §5).

    Two messages, split on whether the reply **asserted** a decline, because the
    two failures carry different evidence of what the model meant.

    - ``declined`` — the reply carried the ``no_capability_needed`` marker and only
      its ``rationale`` was missing, null, non-string or blank. The model has said
      what it meant, so completing the decline is the right ask, and asking for
      steps here would take a correct judgement and instruct the model to invent a
      capability in the next turn — the defect #1315 records, on the reply where
      the judgement was already right.
    - otherwise — unclassified malformed output, a bare empty ``steps`` list
      included. A bare empty list is what a truncation, a template echo or a
      dropped array produces, so offering the decline there would manufacture a
      wrong decline the model never asserted. The message presents both shapes and
      the test between them and asks the model to choose by the goal, naming
      neither as the intended correction.

    Neither message asks for steps, and neither closes by requiring a non-empty
    ``steps`` list — the wording this function used to carry.

    Args:
        reason: What was wrong with the reply, echoed back so the model can see it.
        declined: Whether the reply carried the decline marker (ADR-0176 §5).

    Returns:
        The user turn to append to the conversation before the repair round.
    """
    opening = (
        f"That response could not be used: {reason}. "
        "Reply with only the JSON object described earlier — no prose, no code fence"
    )
    if declined:
        return (
            f'{opening} — keeping `"steps": []` and `"no_capability_needed": true`, '
            'and adding a `"rationale"` whose value is a non-empty string saying why '
            "no capability is needed for this goal."
        )
    return (
        f"{opening}. Either shape is a correct answer; choose between them by what "
        "the goal requires. If accomplishing it requires acting in the world, or "
        "reaching for something this turn has not already given you, send the plan "
        'shape, with `"steps"` listing those steps. If the goal is answered from '
        "what this turn already carries, send the decline shape, with "
        '`"steps": []`, `"no_capability_needed": true`, and a `"rationale"` saying '
        "why no capability is needed."
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
    that is an envelope under :func:`_is_envelope` — a plan or a decline — rather
    than the leftmost object outright, so a decoy object in the prose ahead of the
    envelope is stepped over instead of planned from, including one that carries a
    ``steps`` key of the wrong type, and one whose ``steps`` is an empty list
    *without* the decline marker (either would otherwise shadow a valid envelope
    behind it). Where no decoded object is an envelope, the first decoded object
    stands in, so a single malformed one still reaches :func:`_require_steps` and
    its precise verdict rather than a generic miss. Two genuine envelopes cannot be
    told apart locally and the earlier wins **whatever their shapes** (ADR-0176 §2);
    the outcome stays bounded and is never a corrupt plan.

    **Widening the predicate here is the load-bearing half of ADR-0176.** Relaxing
    only :func:`_require_steps` and leaving this scan at "a non-empty ``steps``
    list" steps straight past a marked decline, records the decoy ahead of it as the
    fall-back, and then rejects the fall-back for carrying no marker — so a reply
    that contained a valid decline falls to bounded repair. The widening is exactly
    one shape, and it is one a decoy does not reach by accident: an empty ``steps``
    list is a plausible fragment or truncation, an empty ``steps`` list *carrying an
    affirmative boolean marker* is something only a deliberate writer produces.

    **A decoded object is advanced *past*, never re-entered:** the scan resumes at
    the object's end, so a nested object is treated as part of its parent, not as a
    separate candidate. An outer object whose ``steps`` is empty and unmarked is
    therefore still refused rather than being overridden by a non-empty ``steps``
    nested inside it. Only a brace that does *not* open a decodable object
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
            if _is_envelope(candidate):
                # A legal envelope, plan-shaped or decline-shaped — exactly what
                # `_require_steps` accepts. Preferred over an earlier decoy that
                # only looks envelope-shaped: a `steps` of the wrong type, or an
                # empty one with no marker behind it.
                return candidate
            if first is None:
                first = candidate
        index = end  # resume past the decoded object; never re-enter its interior

    if first is not None:
        return first
    msg = "no JSON object found in the model reply"
    raise _ExtractionError(msg)


def _declines(envelope: dict[str, object]) -> bool:
    """Whether ``envelope`` carries the decline marker (ADR-0176 §1).

    The marker is the JSON boolean ``true`` **and nothing else**: ``1``, ``1.0``,
    ``"true"``, ``"yes"`` and every other truthy value are not it. The identity
    check is what makes that so — Python's ``bool`` is a subclass of ``int``, so
    ``True == 1`` and ``True == 1.0``, and an equality test would silently execute
    ``{"steps": [], "no_capability_needed": 1}`` as a decline while every other
    clause of ADR-0176 still passed.

    Args:
        envelope: The decoded object to test.

    Returns:
        Whether the object positively asserts that no capability is needed.
    """
    return envelope.get("no_capability_needed") is True


def _is_envelope(candidate: dict[str, object]) -> bool:
    """Whether ``candidate`` is one of the two legal envelope shapes (ADR-0176 §1).

    A **plan envelope** carries a ``steps`` key whose value is a non-empty list
    (ADR-0047 §4 step 2, unchanged). A **decline envelope** carries a ``steps`` key
    whose value is a list of length zero *and* the marker :func:`_declines` tests
    for. Nothing else is an envelope — an object with no ``steps`` key is not one,
    which is what keeps the decline unreachable by *omitting* anything.

    **The marker is consulted only where ``steps`` is empty.** On a non-empty
    ``steps`` it is inert: the object is a plan, its steps are planned, and the
    marker's presence — at any value at all — neither changes that nor is an
    extraction failure. Type-checking the marker before looking at ``steps`` would
    send a perfectly good plan to bounded repair over a key that decides nothing on
    that shape, which ADR-0047 §4 step 2's "other envelope keys are ignored" rule is
    what makes wrong.

    Args:
        candidate: The decoded object to test.

    Returns:
        Whether the object is a plan envelope or a decline envelope.
    """
    steps = candidate.get("steps")
    if not isinstance(steps, list):
        return False
    return bool(steps) or _declines(candidate)


def _require_steps(envelope: dict[str, object]) -> list[object]:
    """Return the envelope's ``steps`` list, empty only where it declines.

    An empty ``steps`` list with no marker is **unclassified malformed output**, not
    a decline (ADR-0176 §5): it is what a truncation, a template echo or a dropped
    array produces, and the reason message says so without naming the decline, so
    the repair turn cannot invite the model to complete a decline it never asserted.

    Raises:
        _ExtractionError: If ``steps`` is missing, not a list, or empty without the
            decline marker.
    """
    steps = envelope.get("steps")
    if not isinstance(steps, list):
        msg = "the reply is not one of the two legal envelopes: it has no 'steps' list"
        raise _ExtractionError(msg)
    if not steps and not _declines(envelope):
        msg = (
            "the reply's 'steps' list is empty and it does not assert "
            "'no_capability_needed': true, so it is neither of the two legal envelopes"
        )
        raise _ExtractionError(msg)
    return steps


def _require_rationale(envelope: dict[str, object]) -> str:
    """Return a decline envelope's non-blank ``rationale`` (ADR-0176 §3).

    A decline has no steps, so ``rationale`` is the whole of what the persisted
    ``ActionPlan`` says about the decision — the sole record of *why* no capability
    was named, and what ADR-0014 §2's audit record rests on at this one shape. It is
    therefore required here where a plan leaves it optional.

    ``core`` does not supply the non-blank condition and is not assumed to:
    ``rationale`` is ``EncodableText | None``, which refuses unwritable text but
    neither refuses nor strips ``"   "``.

    **The type is checked before the value is touched.** Reaching for ``.strip()``
    ahead of the ``isinstance`` would raise ``AttributeError`` on the null case —
    neither ``PlanningError`` nor ``ModelError``, so it would escape
    :meth:`ModelBackedPlanner.plan` as something the ``Planner`` Protocol does not
    document and ADR-0047 §6's bounded repair never sees.

    Args:
        envelope: The decline envelope to read.

    Returns:
        The rationale, verbatim.

    Raises:
        _ExtractionError: If ``rationale`` is absent, null, not a string, or blank.
            Flagged ``declined``, because the reply carried the marker and so said
            what it meant: its repair asks for the rationale, never for steps.
    """
    rationale = envelope.get("rationale")
    if rationale is None:
        stated = "null" if "rationale" in envelope else "missing"
        msg = f"the decline gives no reason: its 'rationale' is {stated}"
        raise _ExtractionError(msg, declined=True)
    if not isinstance(rationale, str):
        msg = "the decline gives no reason: its 'rationale' is not a string"
        raise _ExtractionError(msg, declined=True)
    if not rationale.strip():
        msg = "the decline gives no reason: its 'rationale' is blank"
        raise _ExtractionError(msg, declined=True)
    return rationale


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
