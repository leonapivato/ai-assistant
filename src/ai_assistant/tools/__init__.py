"""Tools: the registry and integrations for external services.

Provides a uniform, discoverable interface over calendars, email, notes,
GitHub, smart-home devices, messaging, etc. Each integration is a self-contained
plugin registered here; the orchestration engine selects and invokes tools
without knowing their internals. Every tool invocation is subject to the
`permissions` layer.

Contract: TBD (a ``Tool`` / ``ToolRegistry`` Protocol lands in
``core.protocols`` as this subsystem is designed).
"""
