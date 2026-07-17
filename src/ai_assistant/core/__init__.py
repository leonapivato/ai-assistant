"""Core: shared types, configuration, errors, and the Protocol contracts.

This package holds the *contracts* the rest of the system is built against.
Every other subsystem (`models`, `memory`, `context`, ...) depends only on the
Protocols and types defined here — never on each other's concrete
implementations. Keeping the contracts in one place is what lets an agent
implement or replace a single subsystem in isolation without breaking others.

Dependency rule: `core` imports from nothing else in `ai_assistant`.
"""
