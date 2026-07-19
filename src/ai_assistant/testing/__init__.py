"""Shared test doubles (fakes) for the ``core`` Protocols.

Canonical, contract-correct implementations that any subsystem's tests may import
instead of hand-rolling a mock or reaching into another subsystem's internals
(CLAUDE.md golden rule 1; CONTRIBUTING, "Fakes over mocks"). One shared fake per
Protocol keeps parallel work honest: two subsystems built at once depend on the
*same* stand-in, so a divergent private mock cannot hide an integration mismatch.

Each fake passes its Protocol's conformance suite. This package is for tests
only; production code must not import it (enforced by ``lint-imports``).
"""

from __future__ import annotations

from ai_assistant.testing.memory import FakeMemoryStore

__all__ = ["FakeMemoryStore"]
