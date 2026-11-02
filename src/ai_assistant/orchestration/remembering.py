"""The remember capability: a candidate recorded for the observer (ADR-0329 §§3-5).

Planning remembers by calling this capability. It is an **inside action** (ADR-0292
§12:1): its effect is the assistant's own records, it never leaves the hub, its outcome
is never unknown, and it is **not safe to repeat**, so acting's duplicate backstop
refuses the same call twice in one matter (ADR-0306 §5:9).

**A call records a candidate and writes no memory** (ADR-0329 §2, §3). The observer is
memory's one writer, and a candidate is what planning hands it: the call as its round
records it, joined to its effect record (§3:3). :data:`REMEMBER_CANDIDATE` is the
declaration, :func:`candidate_of` reads a call's arguments, and :class:`CandidateCalls`
is the runner acting reaches through its own-records seam and never through
``ToolInvoker`` (ADR-0306 §3:3). The runner writes no memory, builds no
:class:`~ai_assistant.core.types.UserConfirmation` and passes no ``MemoryPolicy``
(§5:6-§5:7): it looks up the memories similar to the fact and returns their ids for
planning (§4).

**ADR-0328 §13's interim is retired**, with the composition root's switch that kept it.
Under it a call wrote one memory resting on the call itself; ADR-0329 §2:3 has the writer
``remember`` write nothing once the observer runs, and ADR-0345 §2:4 refuses any memory a
remember call backs that is not a record of the saying. What such calls wrote stays as
written (ADR-0345 §13:4), and :data:`STATEMENT_ARGUMENT` stays so the supports pointing at
them still read the statement their round recorded.

**What a call takes.** Planning writes the candidate's arguments (§3:1, §5:1). The hub
fills two more, which the declaration names in ``system_supplied`` (ADR-0254 §3), so
planning is never offered them and the duplicate backstop never compares them (ADR-0306
§2:10): ``episode``, the address of the activation's episode, and
``rests_on_outside_content``, whether that activation's record says it has read outside
content (ADR-0306 §4:5). Authorizing fills both before the candidate fit test, and the
decision's parameters digest binds them.

**It logs stage and code-owned reason only**, never the fact (ADR-0275 §8).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

import structlog

from ai_assistant.core.types import (
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    LabelKind,
    Memory,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.renames import current_arguments, current_name

if TYPE_CHECKING:
    from ai_assistant.core.types import FrozenJson, ToolCall

__all__ = [
    "ASSISTANT_MESSAGES_ARGUMENT",
    "CANDIDATE_LABEL_ARGUMENTS",
    "CONFIRM_ARGUMENT",
    "EPISODE_ARGUMENT",
    "FACT_ARGUMENT",
    "INPUT_ARGUMENT",
    "MEMORY_ARGUMENT",
    "NOTE_ARGUMENT",
    "OUTSIDE_CONTENT_ARGUMENT",
    "REMEMBER_CANDIDATE",
    "REMEMBER_CAPABILITY",
    "RESULTS_ARGUMENT",
    "SIMILAR_KEY",
    "STATEMENT_ARGUMENT",
    "STATEMENT_MAX_CHARS",
    "USER_MESSAGES_ARGUMENT",
    "WHY_ARGUMENT",
    "Candidate",
    "CandidateCalls",
    "NeedsYou",
    "SimilarMemories",
    "candidate_of",
    "candidate_similar",
    "is_candidate_result",
    "is_remember",
]

_log = structlog.get_logger(__name__)

#: The capability planning is offered, ``remember_fact`` since ADR-0364 §8:1. The
#: declaration keeps its id, ``remember``.
REMEMBER_CAPABILITY: Final = "remember_fact"

#: The one argument a remember call took under ADR-0328 §13's interim: the statement it
#: wrote. No call takes it now; it names what the calls earlier rounds recorded stated.
STATEMENT_ARGUMENT: Final = "statement"

#: The hub-filled argument naming the activation's episode.
EPISODE_ARGUMENT: Final = "episode"

#: The hub-filled argument saying whether the activation had read outside content.
OUTSIDE_CONTENT_ARGUMENT: Final = "rests_on_outside_content"

#: The longest fact a call may carry.
STATEMENT_MAX_CHARS: Final = 2000

#: A candidate's fact (ADR-0329 §3:1): one thing, self-contained, in planning's words.
FACT_ARGUMENT: Final = "fact"

#: Whether a candidate rests on this work's stimulus (ADR-0364 §8:2).
INPUT_ARGUMENT: Final = "rests_on_this_stimulus"

#: The earlier episodes, by their ``E`` labels, whose stimulus it rests on.
USER_MESSAGES_ARGUMENT: Final = "rests_on_stimuli"

#: The earlier episodes, by their ``E`` labels, whose response from the system it rests on.
ASSISTANT_MESSAGES_ARGUMENT: Final = "rests_on_responses"

#: The results, by their ``R`` labels, it rests on.
RESULTS_ARGUMENT: Final = "rests_on_results"

#: A short why.
WHY_ARGUMENT: Final = "why"

#: One memory planning was shown, by its ``M`` label, that the fact bears on.
MEMORY_ARGUMENT: Final = "memory"

#: How the fact bears on that memory, in words.
NOTE_ARGUMENT: Final = "note"

#: Whether planning wants the user's yes to the fact's wording first (ADR-0329 §5:1).
CONFIRM_ARGUMENT: Final = "confirm"

#: The longest why or note a candidate carries.
_REASON_MAX_CHARS: Final = 500

#: The key a candidate's result lists the similar memories' ids under (ADR-0329 §4:1),
#: ``null`` where the lookup failed (§4:4).
SIMILAR_KEY: Final = "similar"

_LABELS_SCHEMA_ITEMS: Final[dict[str, FrozenJson]] = {"type": "string", "minLength": 1}

_CANDIDATE_SCHEMA: Final[dict[str, FrozenJson]] = {
    "type": "object",
    "properties": {
        FACT_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "maxLength": STATEMENT_MAX_CHARS,
            "description": (
                "One fact, in your own words, that will still make sense on its own later."
            ),
        },
        WHY_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "maxLength": _REASON_MAX_CHARS,
            "description": "Why it is worth keeping, in a few words.",
        },
        INPUT_ARGUMENT: {
            "type": "boolean",
            "description": "Whether the fact rests on this work's stimulus. Left out: false.",
        },
        USER_MESSAGES_ARGUMENT: {
            "type": "array",
            "items": _LABELS_SCHEMA_ITEMS,
            "description": (
                "Earlier episodes whose stimulus the fact rests on, by E label. Left out: none."
            ),
        },
        ASSISTANT_MESSAGES_ARGUMENT: {
            "type": "array",
            "items": _LABELS_SCHEMA_ITEMS,
            "description": (
                "Earlier episodes whose response from the system the fact rests on, by E label. "
                "Left out: none."
            ),
        },
        RESULTS_ARGUMENT: {
            "type": "array",
            "items": _LABELS_SCHEMA_ITEMS,
            "description": "The results the fact rests on, by R label. Left out: none.",
        },
        MEMORY_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "description": (
                "A memory you were shown that the fact bears on, by M label. Left out: none."
            ),
        },
        NOTE_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "maxLength": _REASON_MAX_CHARS,
            "description": "How the fact bears on that memory. Required with memory.",
        },
        CONFIRM_ARGUMENT: {
            "type": "boolean",
            "description": (
                "Have the fact's wording approved before it is kept: with it, this call needs "
                "approval, so ask for it with request_approval. Left out: false."
            ),
        },
        EPISODE_ARGUMENT: {"type": "string", "minLength": 1},
        OUTSIDE_CONTENT_ARGUMENT: {"type": "boolean"},
    },
    "required": [FACT_ARGUMENT, WHY_ARGUMENT, EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT],
    "additionalProperties": False,
}
REMEMBER_CANDIDATE: Final = ToolDefinition(
    # ADR-0364 §8:1: renamed, keeping its declaration's other fields, its id among them.
    id="remember",
    capability=REMEMBER_CAPABILITY,
    description=(
        "Record a candidate for long-term memory: one fact, what it rests on, and why it is worth "
        "keeping.\n"
        "\n"
        "Record one only where it was asked for, or this work needs something kept now, such as a "
        "fact a task it sets will rely on; anything else is found later from the episode. A "
        "candidate isn't yet a memory: whether and how it is kept is decided later. Ask about a "
        "similar memory its result shows only where it conflicts with the fact and the conflict "
        "matters to what is being done.\n"
        "\n"
        "outcome: done | not done | unknown | refused\n"
        "because: why, with not done, unknown or refused\n"
        "result: with done:\n"
        "  candidate: recorded; whether and how it is kept is decided once this episode leaves "
        "short-term memory\n"
        "  similar_memories: the memories already held like its fact, each as long-term memory "
        "shows one, or none\n"
        "\n"
        "It changes only the system's own records. Not safe to repeat."
    ),
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.RECOVERABLE,
    side_effecting=True,
    reads=(DataTier.PERSONAL,),
    writes=(DataTier.PERSONAL,),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.OWN_RECORDS,
    leaves_hub=False,
    result=CapabilityResult.NO_OUTSIDE_TEXT,
    outcome_can_be_unknown=False,
    safe_to_repeat=False,
    system_supplied=(EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT),
    parameters_schema=_CANDIDATE_SCHEMA,
)
"""The remember capability's declaration (ADR-0306 §2, §3:2; ADR-0329 §3, §4:3, §5:1).

- ``effect=OWN_RECORDS``, ``leaves_hub=False``, ``outcome_can_be_unknown=False`` and
  ``safe_to_repeat=False``: ADR-0306 §3:2 and ADR-0329 §3:7, each as ruled.
- ``result=NO_OUTSIDE_TEXT``: its result lists the similar memories that do not rest on
  outside content, by id, and carries no outside text (§4:2-§4:3), so it goes to
  planning whole (ADR-0306 §5:14).
- ``side_effecting=True`` with ``writes=(PERSONAL,)``: it records a candidate about the
  user, which ADR-0016's consistency rules make side-effecting, and ADR-0306 §2:5 (as
  ADR-0312 §2 leaves it) requires of an effect that is not none.
- ``reads=(PERSONAL,)``: its lookup reads the memories similar to the fact.
- ``reversibility=RECOVERABLE``, ``idempotency=NONE``: a recorded candidate is not
  undone by a symmetric call, and recording one twice records it twice.
- ``risk_level=LOW``, ``discloses=()``, ``cost=FREE``: nothing leaves the device and
  nothing is spent.
- ``system_supplied`` names the two arguments the hub fills (module docstring, §3:4).
"""

#: Which of a candidate's arguments name things by label (ADR-0307 §5:2), which
#: planning's check maps to ids or refuses whole (§5:3, ADR-0329 §3:4).
CANDIDATE_LABEL_ARGUMENTS: Final[Mapping[str, Mapping[str, LabelKind]]] = {
    REMEMBER_CAPABILITY: {
        USER_MESSAGES_ARGUMENT: LabelKind.EPISODE,
        ASSISTANT_MESSAGES_ARGUMENT: LabelKind.EPISODE,
        RESULTS_ARGUMENT: LabelKind.RESULT,
        MEMORY_ARGUMENT: LabelKind.MEMORY,
    }
}


@dataclass(frozen=True, slots=True)
class Candidate:
    """One candidate, as a ``remember`` call records it (ADR-0329 §3:1, §5:1).

    Attributes:
        fact: The fact, in planning's words.
        why: Why it is worth keeping.
        rests_on_input: Whether it rests on the activation's input.
        user_messages: The episodes whose user's message it rests on, by id.
        assistant_messages: The episodes whose assistant's message it rests on, by id.
        results: The results it rests on, by id.
        memory: The memory it bears on, by id, or ``None``.
        note: How it bears on that memory, or ``None``.
        confirm: Whether planning wants the user's yes to its wording first.
    """

    fact: str
    why: str
    rests_on_input: bool = False
    user_messages: tuple[str, ...] = ()
    assistant_messages: tuple[str, ...] = ()
    results: tuple[str, ...] = ()
    memory: str | None = None
    note: str | None = None
    confirm: bool = False


def is_remember(capability: str | None, /) -> bool:
    """Whether a recorded call or effect is a ``remember_fact``, under either name (§8:1).

    ADR-0364 §8:4: a record written before the renames names the tool ``remember``.
    """
    return capability is not None and current_name(capability) == REMEMBER_CAPABILITY


def candidate_of(parameters: Mapping[str, FrozenJson], /) -> Candidate:
    """The candidate a ``remember`` call records, its labels already mapped to ids.

    Args:
        parameters: The call's arguments, the hub-filled ones included or not.

    Returns:
        The candidate.

    Raises:
        ValueError: If the fact or the why is missing or blank, an argument is of the
            wrong type, it rests on nothing (§3:1's "one or more"), or it carries a
            memory without the note §3:1 has it carry, or a note without the memory
            the note is about.
    """
    # ADR-0364 §8:2: a call recorded before the renames names its arguments the old way.
    parameters = current_arguments(REMEMBER_CAPABILITY, parameters)
    fact = parameters.get(FACT_ARGUMENT)
    why = parameters.get(WHY_ARGUMENT)
    if not isinstance(fact, str) or not fact.strip():
        msg = "a candidate states one non-blank fact"
        raise ValueError(msg)
    if not isinstance(why, str) or not why.strip():
        msg = "a candidate says why it is worth keeping"
        raise ValueError(msg)
    rests_on_input = _flag(parameters, INPUT_ARGUMENT)
    user = _ids(parameters, USER_MESSAGES_ARGUMENT)
    assistant = _ids(parameters, ASSISTANT_MESSAGES_ARGUMENT)
    results = _ids(parameters, RESULTS_ARGUMENT)
    if not (rests_on_input or user or assistant or results):
        msg = "a candidate rests on the input, an earlier message or a result"
        raise ValueError(msg)
    memory = _optional_text(parameters, MEMORY_ARGUMENT)
    note = _optional_text(parameters, NOTE_ARGUMENT)
    if note is not None and memory is None:
        msg = "a candidate's note is about the memory it names"
        raise ValueError(msg)
    if memory is not None and note is None:
        msg = "a candidate naming a memory says in a note how the fact bears on it"
        raise ValueError(msg)
    return Candidate(
        fact=fact,
        why=why,
        rests_on_input=rests_on_input,
        user_messages=user,
        assistant_messages=assistant,
        results=results,
        memory=memory,
        note=note,
        confirm=_flag(parameters, CONFIRM_ARGUMENT),
    )


def _flag(parameters: Mapping[str, FrozenJson], name: str) -> bool:
    value = parameters.get(name, False)
    if not isinstance(value, bool):
        msg = f"a candidate's {name} is true or false"
        raise ValueError(msg)
    return value


def _ids(parameters: Mapping[str, FrozenJson], name: str) -> tuple[str, ...]:
    value = parameters.get(name, ())
    if not isinstance(value, list | tuple) or not all(
        isinstance(one, str) and one.strip() for one in value
    ):
        msg = f"a candidate's {name} names things by label"
        raise ValueError(msg)
    return tuple(str(one) for one in value)


def _optional_text(parameters: Mapping[str, FrozenJson], name: str) -> str | None:
    value = parameters.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        msg = f"a candidate's {name} is non-blank text"
        raise ValueError(msg)
    return value


def is_candidate_result(output: object, /) -> bool:
    """Whether ``output`` is what a ``remember`` that recorded a candidate returned.

    Args:
        output: What a done call returned.

    Returns:
        Whether it carries :data:`SIMILAR_KEY`, as a candidate's result always does.
    """
    return isinstance(output, Mapping) and SIMILAR_KEY in output


def candidate_similar(output: object, /) -> tuple[str, ...] | None:
    """The similar memories' ids a candidate's result lists, or ``None`` where it lists none.

    Args:
        output: What a ``remember`` call that recorded a candidate returned.

    Returns:
        The ids, in the order the lookup ranked them; ``None`` where the lookup failed
        (ADR-0329 §4:4) or ``output`` is not a candidate's result.
    """
    if not isinstance(output, Mapping):
        return None
    ids = output.get(SIMILAR_KEY)
    if not isinstance(ids, list | tuple):
        return None
    return tuple(one for one in ids if isinstance(one, str))


@dataclass(frozen=True, slots=True)
class NeedsYou:
    """A call on the assistant's own records that needs the user's yes (ADR-0321 §5:5).

    What a runner on acting's own-records seam answers where nothing was written
    because what the call would write needs the user first. Acting reports it as
    ``needs_you``, never as done or not done, carrying the assertions its question
    shows the call replacing.

    **It has no producer.** Its one producer was ``remember``'s runner under ADR-0328
    §13's interim, whose write-time ask ADR-0329 §20 retires in favour of *confirm*;
    the interim is retired, and acting's seam keeps the answer until the question path
    that shows what a call replaces is retired with it (#3407).

    Declared here rather than in acting, whose seam it is an answer of: acting may
    import this module, and this module may not import acting, because the authorizing
    phase imports it and the phase modules are independent of each other (ADR-0309
    §2:3).

    Attributes:
        replaces: The assertions the question shows the call replacing, as stored:
            what a yes retires, and nothing else. Empty where it replaces none.
    """

    replaces: tuple[Memory, ...] = ()


def _not_done(kind: ToolFailureKind, message: str) -> ToolResult:
    return ToolResult(outcome=ToolOutcome.FAILED, failure=ToolFailure(kind=kind, message=message))


class SimilarMemories(Protocol):
    """The lookup a candidate's runner reads (ADR-0329 §4:1-§4:2).

    Structurally :class:`~ai_assistant.orchestration.lookups.LookUps`, which searches
    under the round's audience: this module may not import it, because the authorizing
    phase imports this module and the look-ups import acting and planning (ADR-0309
    §2:3).
    """

    async def similar(self, fact: str, *, limit: int) -> tuple[Memory, ...] | None:
        """The memories most similar to ``fact``, by relevance alone, or ``None``.

        Only memories that do not rest on outside content, and only those the round's
        audience admits, at most ``limit`` of them, best first; ``None`` where they could
        not be read.
        """
        ...


class CandidateCalls:
    """Record a candidate, and look up the memories similar to it (ADR-0329 §3-§4).

    Structurally acting's ``OwnRecordsCalls``. A
    candidate is the call as its round records it, joined to the effect record acting
    claimed it under (§3:3), so recording it is that record finished done: this runner
    writes nothing, passes no ``MemoryPolicy`` and builds no
    :class:`~ai_assistant.core.types.UserConfirmation` (§5:6-§5:7). It answers
    ``succeeded`` with the similar memories' ids under :data:`SIMILAR_KEY`, ``null``
    where the lookup failed, which leaves the candidate recorded (§4:4); ``failed``
    with a code-owned kind where the call is not a claimed ``remember`` or is malformed;
    never ``indeterminate``.
    """

    def __init__(self, *, similar: SimilarMemories, limit: int) -> None:
        """Wire the runner to the lookup.

        Args:
            similar: The lookup, searching under the round's audience.
            limit: How many similar memories a lookup returns at most: the composition
                root's constant (§4:1).

        Raises:
            ValueError: If ``limit`` is below 1.
        """
        if limit < 1:
            msg = "a candidate's lookup returns at least one memory"
            raise ValueError(msg)
        self._similar = similar
        self._limit = limit

    async def run(self, call: ToolCall) -> ToolResult:
        """Record the candidate ``call`` carries, and return the similar memories' ids.

        Args:
            call: The authorized remember call.

        Returns:
            ``succeeded``, its output the similar memories' ids or ``null``; ``failed``
            where the call is not a claimed remember call or is malformed.
        """
        if call.request.tool.capability != REMEMBER_CAPABILITY or call.decision.effect is None:
            _log.info("candidate_not_done", stage="acting", reason="not_a_remember_call")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "not a claimed remember call")
        try:
            candidate = candidate_of(call.request.parameters)
        except ValueError:
            _log.info("candidate_not_done", stage="acting", reason="malformed")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "the call's arguments are malformed")
        found = await self._similar.similar(candidate.fact, limit=self._limit)
        if found is None:
            _log.info("candidate_recorded", stage="acting", reason="lookup_failed")
            return ToolResult(outcome=ToolOutcome.SUCCEEDED, output={SIMILAR_KEY: None})
        _log.info("candidate_recorded", stage="acting", similar=len(found))
        return ToolResult(
            outcome=ToolOutcome.SUCCEEDED,
            output={SIMILAR_KEY: [record.id for record in found]},
        )
