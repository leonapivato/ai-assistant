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
by the one :class:`~ai_assistant.permissions.grants.SqliteSourceGrantStore`.

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
nor satisfied by anything here. Standing grants for *actions* stay deferred, and
issue #74's model-provider-credential question is untouched (ADR-0097 §12).
"""

from __future__ import annotations

from ai_assistant.permissions.audit import SqliteAuditTrail
from ai_assistant.permissions.grants import SqliteSourceGrantStore
from ai_assistant.permissions.policy import ThresholdActionPolicy

__all__ = ["SqliteAuditTrail", "SqliteSourceGrantStore", "ThresholdActionPolicy"]
