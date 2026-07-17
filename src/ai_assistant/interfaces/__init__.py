"""Interfaces: adapters that connect the outside world to the core.

Each adapter (CLI now; API/UI later) translates user input into calls on the
`orchestration` engine and renders results back. Adapters are thin: they contain
no business logic, so the same core can be driven by any front end.
"""
