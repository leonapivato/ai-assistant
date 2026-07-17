"""Permissions: the policy layer that keeps the user in control.

Decides whether a proposed action (tool call, data access, proactive message)
is allowed, and records why. Sits between planning/orchestration and any
side-effecting tool call. Owns the permission model and the audit trail that
makes the assistant's behaviour transparent and reviewable.

Contract: TBD (a ``PermissionChecker`` Protocol lands in ``core.protocols`` as
this subsystem is designed).
"""
