"""Planning: turns complex requests into executable plans.

Breaks a request into ordered steps, tracks progress, and decides what to do
next. Consumes the model layer for reasoning and the tool registry for the
actions a plan can take; owns the plan/step data model and its lifecycle.

Contract: TBD (added here as this subsystem is designed).
"""
