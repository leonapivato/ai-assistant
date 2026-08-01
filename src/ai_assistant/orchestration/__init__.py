"""Orchestration: the engine that ties everything together.

The heart of the product. For each request it runs the pipeline:
intent understanding → context assembly → memory retrieval → planning →
tool selection → permission checking → execution → learning/memory updates.

It depends *only* on the Protocols in ``core.protocols`` — never on concrete
subsystem implementations, which are injected. That inversion is what keeps the
engine testable and the subsystems independently replaceable.

Contract: this package *consumes* contracts; it wires implementations together.

``LearningLoop`` is the first working slice of that pipeline: the closed
learning loop of ADR-0022 (intent → context → retrieval → planning, then
feedback → proposal → policy → memory).

``StepExecutor`` is the ``execute`` stage (ADR-0029 §8): it claims a plan step,
runs one authorised call through an injected ``ToolInvoker``, and commits what
came back.

``StepRunner`` is the join between them (ADR-0037): the tool-selection and
permission stages. It takes a ``PlanStep``, finds the tool advertising its
capability, has an ``ActionPolicy`` rule on it, records the
``PermissionDecision``, and hands the executor a ``ToolCall`` built from the
audit trail's own copy of that decision — or disposes of the step without
running it, saying durably why.

``Engine`` is the concrete class that **satisfies** ``core.protocols``'s
``AssistantEngine`` (ADR-0084 §5, ADR-0085 §1). ADR-0042 §1 declined a Protocol
because there was one engine and one class of consumer, and named its own revisit
trigger — a second implementation; a client satisfying the same surface over a
local transport is that implementation, so the surface is now a contract and the
twenty-four result types it names live in ``core.types``. Import them from there:
this package exports the engine, the stages, and its own internal DTOs, and no
longer re-exports a promoted type under a second name.

``Engine`` keeps ``start()`` and ``aclose()``, which are deliberately **not** on
the Protocol (ADR-0083 §8): lifecycle belongs to the concrete object the
composition root builds, and a client that could call ``aclose()`` could shut down
the hub from a spoke. A Protocol constrains what an implementation must have, not
what it may not, so the class stays substitutable with both.

The façade carries the **belief inspection surface** (ADR-0073 §7): ``beliefs``
enumerates what the assistant holds as ``BeliefSummary`` — counts, never citation
contents (ADR-0085 §4a) — ``belief`` reads the one a deletion is about to destroy
as a ``Belief`` with its citations resolved, and ``forget`` destroys it. Both
projections apply ``band_of`` here, once, before any adapter sees a record
(``belief_from_record``, ``belief_summary_from_record``), and both state the
confidence lost support has already lowered (``presented_confidence``) rather than
the stored number, which nothing on this path ever writes (ADR-0077 §6).

``payloads`` holds the surface's payload rules: ADR-0087's canonical encoding, and
the contract limit ADR-0084 §4 makes every implementation enforce.

``ConversationLifecycle`` is the **capture/lifecycle stage** (ADR-0074 §9): the
one layer holding both durable stores, and therefore the owner of every sequence
that spans them — capturing a turn as an ``EpisodicMemory``, carrying out a
conversation-scoped deletion, reclaiming what retention has emptied, and
composing the export a user receives. ADR-0074 §9's coordinator ruling puts those
here precisely because neither store may hold the other (golden rule 1).

``MemoryWriteStage`` is the **write stage** (ADR-0078 §3): the one place a proposal
reaches memory. It holds the ratified ``MemoryWriter`` *and* the ``DeferralStore``,
so an ``ASK_USER`` ruling's question is parked durably instead of vanishing when the
proposal goes out of scope — the drop issue #423 reports, closed by a wiring choice
rather than by a new writer. Every producer's stage (``LearningLoop``,
``ObservationStage``) writes through it rather than through a ``MemoryWriter`` handle
of its own, which is the one obligation ADR-0078 §3 places on this lane.

``QuestionStage`` is the **answer path** (ADR-0078 §8, §9): it enumerates the
questions waiting, and the separate list of those whose answer was begun and never
recorded, then runs ``claim`` → ``ingest`` → ``resolve`` to commit an answer. It is
the *only* producer of a ``UserConfirmation``, and only from a deferral it has
claimed — the one authority in this system that has never been delegable.

``ObservationStage`` is the **observation stage** (ADR-0077 §8), the second such
two-store owner: it selects a bounded batch of a conversation's recent episodes,
hands them to the injected ``Observer``, and puts every proposal that comes back
through the ratified write path — reporting what was proposed, what became of it,
and which model route read the episodes (``ObservationReport``,
``ObservedProposal``). The producer holds no store, so selecting the batch could
never have been its job (ADR-0077 §1).
"""

from ai_assistant.orchestration.conversations import (
    AssembledHistory,
    CaptureReport,
    ConversationLifecycle,
    DataExport,
)
from ai_assistant.orchestration.engine import (
    Engine,
    belief_from_record,
    belief_summary_from_record,
    conversation_summary,
    learn_decision,
    learn_outcome,
    presented_confidence,
    queued_question,
)
from ai_assistant.orchestration.executor import StepExecutor
from ai_assistant.orchestration.loop import LearningLoop
from ai_assistant.orchestration.observation import (
    ObservationStage,
    observed_ruled,
    observed_unsupported,
)
from ai_assistant.orchestration.payloads import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    ENVELOPE_RESERVE_BYTES,
    MIN_FRAME_BYTES,
    canonical_payload,
)
from ai_assistant.orchestration.questions import QuestionStage, question_state
from ai_assistant.orchestration.runner import StepDisposition, StepRunner
from ai_assistant.orchestration.writes import MemoryWriteStage, WriteOutcome

__all__ = [
    "DEFAULT_MAX_PAYLOAD_BYTES",
    "ENVELOPE_RESERVE_BYTES",
    "MIN_FRAME_BYTES",
    "AssembledHistory",
    "CaptureReport",
    "ConversationLifecycle",
    "DataExport",
    "Engine",
    "LearningLoop",
    "MemoryWriteStage",
    "ObservationStage",
    "QuestionStage",
    "StepDisposition",
    "StepExecutor",
    "StepRunner",
    "WriteOutcome",
    "belief_from_record",
    "belief_summary_from_record",
    "canonical_payload",
    "conversation_summary",
    "learn_decision",
    "learn_outcome",
    "observed_ruled",
    "observed_unsupported",
    "presented_confidence",
    "question_state",
    "queued_question",
]
