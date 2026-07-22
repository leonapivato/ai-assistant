"""Permissions: the policy layer that keeps the user in control.

Decides whether a proposed action is allowed, and records why. Sits between
planning/orchestration and any side-effecting tool call (ADR-0004 §7), and owns
both halves of that sentence: the permission model and the audit trail that
makes the assistant's behaviour transparent and reviewable.

Contracts: :class:`~ai_assistant.core.protocols.ActionPolicy` and
:class:`~ai_assistant.core.protocols.AuditTrail` (ADR-0021), implemented here by
:class:`~ai_assistant.permissions.policy.ThresholdActionPolicy` and
:class:`~ai_assistant.permissions.audit.SqliteAuditTrail` (ADR-0036).

**The policy rules; the caller records.** ADR-0021 §3 keeps ``ActionPolicy`` a
pure function — no clock, no id minting, no store — because a ``CONFIRM`` is
answered by the user long after ``decide`` returns, so a policy that recorded
its own rulings would put half the trail in this subsystem and half in
`orchestration`. Nothing here forces a decision to be recorded; that obligation
sits with the executor holding the ``approval_ref`` (issue #107).

``ActionRequest`` is about invoking a tool. Gating *direct* Tier 0/1 data
access, which ADR-0004 §7 also asks for, is deferred pending issue #74 and will
arrive as a second Protocol rather than by widening this one (ADR-0021 §3).
"""

from __future__ import annotations

from ai_assistant.permissions.audit import SqliteAuditTrail
from ai_assistant.permissions.policy import ThresholdActionPolicy

__all__ = ["SqliteAuditTrail", "ThresholdActionPolicy"]
