"""Orchestration: the engine that ties everything together.

The heart of the product. **The phases plan every activation** (ADR-0309 §2:6): a
message written into a conversation is taken in by the chat's reader, and an
informational event is admitted by ``Engine.receive``; each runs as one activation
whose stages the controller runs by ADR-0309 §3's table — understanding, recall,
planning, authorizing, acting and the digests — and whose messages the phases
write (ADR-0293 §6, ADR-0307, ADR-0308, ADR-0313 §4).

It depends *only* on the Protocols in ``core.protocols`` — never on concrete
subsystem implementations, which are injected. That inversion is what keeps the
engine testable and the subsystems independently replaceable.

Contract: this package *consumes* contracts; it wires implementations together.

``Engine`` is the concrete class that **satisfies** ``core.protocols``'s
``AssistantEngine`` (ADR-0084 §5, ADR-0085 §1). ADR-0042 §1 declined a Protocol
because there was one engine and one class of consumer, and named its own revisit
trigger — a second implementation; a client satisfying the same surface over a
local transport is that implementation, so the surface is now a contract and the
result types it names live in ``core.types``. Import them from there: this package
exports the engine, the stages, and its own internal DTOs, and no longer
re-exports a promoted type under a second name.

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

``GrantOperations`` is the **grant surface** (ADR-0102 §1, §7): what may be
granted, granting, revoking, and the record of both. It is the only object in the
system holding a ``SourceGrantStore`` (ADR-0097 §3, §9) — every driver holds the
narrow ``SourceGrants`` instead — and ``Engine`` delegates its
``AssistantEngine`` grant methods to it. It lives here because those must be
``AssistantEngine`` methods to be addressable over the socket, and that Protocol is
provided by this package. ``RecipientGrantOperations`` and
``DestinationTrustOperations`` are its siblings over the recipient-grant and
destination-trust stores (ADR-0235 §7, ADR-0242 §4).

``ConnectionOperations`` is the **connection surface** (ADR-0151 §1, §10):
connecting an account, replacing its credential, disconnecting it, and the two
listings that say what is connected now and what was done. It is the only object in
this package holding a ``ConnectionProvisioner``, and ``Engine`` delegates its
``AssistantEngine`` connection methods to it. **Holding that seam is not holding a
keyring face** (ADR-0149 §8, ADR-0125 §8): it names five members over `core` types
and cannot name ``set``, ``delete`` or ``get``.

``ConversationLifecycle`` is the **capture/lifecycle stage** (ADR-0074 §9): the
one layer holding both durable stores, and therefore the owner of every sequence
that spans them — capturing an activation as an ``EpisodicMemory``, carrying out a
conversation-scoped deletion, reclaiming what retention has emptied, and
composing the export a user receives. ADR-0074 §9's coordinator ruling puts those
here precisely because neither store may hold the other (golden rule 1).

``MemoryWriteStage`` is the **write stage** (ADR-0078 §3): the one place a
producer's proposal reaches memory. It holds the ratified ``MemoryWriter`` *and*
the ``DeferralStore``, so an ``ASK_USER`` ruling's question is parked durably
instead of vanishing when the proposal goes out of scope.

``ConsolidationStage`` is the **consolidation stage** (ADR-0106, ADR-0111,
ADR-0114), a producer's stage, and the only one that is also its own
producer. It walks the memory store a bounded chunk at a time from a durable
cursor, asks an injected ``ModelProvider`` what each chunk justifies believing,
and puts every proposal through the write stage — computing the derived-taint
marker itself, from the input set it selected, and discarding whatever the model
emitted for that field (ADR-0106 §3).

``NotificationWriteStage`` is ADR-0130 §3's **producer seam**, concrete: it holds
the deterministic policy and hands it to the store, so the duplicate lookup, the
cap check, the budget read, the ruling and the write stay one atomic act *in the
store* — and then it runs ADR-0131 §3b's live handoff on the way out, which is the
clause that keeps a ruled interruption from waiting for a restart.
``UpcomingEventStage`` is ADR-0132's **upcoming-event producer** and the seam's
first holder: one bounded calendar read per tick, gated on a live ``NOTIFY`` grant
(ADR-0133 §5), one candidate per occurrence starting inside the lead window, and
an expiry at the start instant — which is the only route ADR-0130 §5 offers to an
interruption.
"""

from ai_assistant.orchestration.connections import ConnectionOperations
from ai_assistant.orchestration.consolidation import (
    ConsolidationReport,
    ConsolidationStage,
)
from ai_assistant.orchestration.conversations import (
    AssembledHistory,
    ConversationLifecycle,
)
from ai_assistant.orchestration.destination_trust import DestinationTrustOperations
from ai_assistant.orchestration.engine import (
    Engine,
    belief_from_record,
    belief_summary_from_record,
    conversation_summary,
    presented_confidence,
)
from ai_assistant.orchestration.grants import GrantOperations, HeldSource
from ai_assistant.orchestration.notifications import NotificationWriteStage, hand_off
from ai_assistant.orchestration.payloads import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    ENVELOPE_RESERVE_BYTES,
    MIN_FRAME_BYTES,
    canonical_payload,
)
from ai_assistant.orchestration.recipient_grants import RecipientGrantOperations
from ai_assistant.orchestration.upcoming import UpcomingEventStage
from ai_assistant.orchestration.writes import MemoryWriteStage, WriteOutcome

__all__ = [
    "DEFAULT_MAX_PAYLOAD_BYTES",
    "ENVELOPE_RESERVE_BYTES",
    "MIN_FRAME_BYTES",
    "AssembledHistory",
    "ConnectionOperations",
    "ConsolidationReport",
    "ConsolidationStage",
    "ConversationLifecycle",
    "DestinationTrustOperations",
    "Engine",
    "GrantOperations",
    "HeldSource",
    "MemoryWriteStage",
    "NotificationWriteStage",
    "RecipientGrantOperations",
    "UpcomingEventStage",
    "WriteOutcome",
    "belief_from_record",
    "belief_summary_from_record",
    "canonical_payload",
    "conversation_summary",
    "hand_off",
    "presented_confidence",
]
