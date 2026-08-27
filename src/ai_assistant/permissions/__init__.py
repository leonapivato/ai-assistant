"""Permissions: the policy layer that keeps the user in control.

Decides whether a proposed action is allowed, and records why. Sits between
planning/orchestration and any side-effecting tool call (ADR-0004 §7), and owns
both halves of that sentence: the permission model and the audit trail that
makes the assistant's behaviour transparent and reviewable.

Contracts: :class:`~ai_assistant.core.protocols.ActionPolicy` and
:class:`~ai_assistant.core.protocols.AuditTrail` (ADR-0021), implemented here by
:class:`~ai_assistant.permissions.policy.ThresholdActionPolicy` and
:class:`~ai_assistant.permissions.audit.SqliteAuditTrail` (ADR-0036); plus
:class:`~ai_assistant.core.protocols.SourceGrants` and
:class:`~ai_assistant.core.protocols.SourceGrantStore` (ADR-0097), both satisfied
by the one :class:`~ai_assistant.permissions.grants.SqliteSourceGrantStore`; and
:class:`~ai_assistant.core.protocols.SourceReadRecorder` and
:class:`~ai_assistant.core.protocols.SourceReadTrail` (ADR-0185), both satisfied
by the one :class:`~ai_assistant.permissions.reads.SqliteSourceReadTrail`; and
:class:`~ai_assistant.core.protocols.RoutingRecorder` and
:class:`~ai_assistant.core.protocols.RoutingTrail` (ADR-0197 §9), both satisfied by
the one :class:`~ai_assistant.permissions.routing.SqliteRoutingTrail`.

**ADR-0004 §7's other half, for source access.** ADR-0097 built the *gate* — "is
this source granted for this use" — and ADR-0185 builds the *record of the access
itself*, which ADR-0139 §6 ruled the grant store does not discharge: that store
records the authorisation, and granting is not access. Every attempt to read a
source is one row, refusals included, written by the driver that held the gate.

**The policy rules; the caller records.** ADR-0021 §3 keeps ``ActionPolicy`` a
pure function — no clock, no id minting, no store — because a ``CONFIRM`` is
answered by the user long after ``decide`` returns, so a policy that recorded
its own rulings would put half the trail in this subsystem and half in
`orchestration`. Nothing here forces a decision to be recorded; that obligation
sits with the executor holding the ``approval_ref`` (issue #107).

**Two subjects, and they are governed separately.** ``ActionRequest`` is about
invoking a tool; a ``SourceGrant`` is about reading a connected source. ADR-0021
§3 named a second Protocol beside ``ActionPolicy`` as the presumptive shape for
gating direct Tier 0/1 data access rather than widening ``decide``, and ADR-0097
takes it for the *source* slice of that deferral. The two may not be joined:
ADR-0097 §7 rules that a ``SourceGrant`` may never be cited as
``PermissionRuling.authorised_by`` and that no ``ActionPolicy`` implementation
may consult a grant seam, so ADR-0021 §5's disclosure floor is neither relaxed
nor satisfied by anything here. Issue #74's model-provider-credential question is
untouched (ADR-0097 §12).

**A fourth row kind, and it is about neither a tool nor a source.** ADR-0197 §9 puts
the routing trail here for the reason ADR-0097 §3 put the read trail here: a routed
operation is a decision a **model** took about the user's own stores, and every other
place a model's choice reaches an effect already leaves a durable record. It joins
neither of ADR-0186 §10's two partitions — a routed operation is never a
``PermissionDecision`` and never a ``SourceReadRecord`` — and being a fourth row kind is
a statement about what a row *is* rather than about which package the store is built in;
the two questions are answered separately. The row is written **before** the act it
precedes, so it states what was decided and never what happened, and a row that cannot
be written stops the act. Nothing can read it yet: §9 mints the store and no engine
method, and §11 leaves the read surface to its own decision on ADR-0185 → ADR-0186's
sequence.

**A third subject, and it is the one ADR-0021 §6 deferred.** A
:class:`~ai_assistant.core.types.RecipientGrant` is about *sending* — one
declaration, one connected account, one canonical destination set, until one
instant — and ADR-0193 lands the store ADR-0021 §6 called "a store, not a field"
for the recipient axis. Three faces on one
:class:`~ai_assistant.permissions.recipient_grants.SqliteRecipientGrantStore`:
:class:`~ai_assistant.core.protocols.RecipientGrants` for the policy's one lookup
per ruling, :class:`~ai_assistant.core.protocols.RecipientGrantResolution` for the
trail's resolution read, and
:class:`~ai_assistant.core.protocols.RecipientGrantStore` for the operations that
append and erase.

**The two grant seams stay unjoined, in both directions.** ADR-0097 §7 stands
verbatim — a source grant may never be an action authorisation and no
``ActionPolicy`` may consult either source-grant seam — and ADR-0193 §13 restates
it. A recipient grant cannot authorise a read either: the two stores hold
different records, are consulted by different components, neither Protocol is
reachable from the other's holder, and their error classes are deliberately
separate families so one handler cannot join them. Standing grants for actions
*other* than egress at the designated seam stay deferred and unnarrowed
(ADR-0193 §6).
"""

from __future__ import annotations

from ai_assistant.permissions.audit import SqliteAuditTrail
from ai_assistant.permissions.grants import SqliteSourceGrantStore
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.permissions.reads import SqliteSourceReadTrail
from ai_assistant.permissions.recipient_grants import SqliteRecipientGrantStore
from ai_assistant.permissions.routing import SqliteRoutingTrail

__all__ = [
    "SqliteAuditTrail",
    "SqliteRecipientGrantStore",
    "SqliteRoutingTrail",
    "SqliteSourceGrantStore",
    "SqliteSourceReadTrail",
    "ThresholdActionPolicy",
]
