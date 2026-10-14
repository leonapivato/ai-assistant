"""The local tool and the default-registry factory (ADR-0048, ADR-0208).

Two things are proven here: the tool's callable does what its declaration says;
and :func:`build_default_registry` returns a populated one-object registry+invoker
advertising ``current_time`` **and no memory capability** (ADR-0208 §1, §6).

ADR-0208 §6 asks for the registry assertion "for a call with an egress integration
and for one without". The *without* half is here, where the factory's default is;
the *with* half is in ``test_send_email_registration.py``, which owns the
configured branch and the machinery that builds a real integration.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ai_assistant.core.clock import ClockReadingError
from ai_assistant.core.types import ToolDefinition
from ai_assistant.testing import FakeAuditTrail
from ai_assistant.tools import (
    CURRENT_TIME,
    CurrentTime,
    build_default_registry,
)

#: The capability names the eight deleted alias rows used to serve (ADR-0208 §2),
#: plus the id and capability the tool itself advertised. A plan may still emit any
#: of them; none of them may reach a tool.
MEMORY_SYNONYMS = (
    "recall",
    "recall_memories",
    "recall_memory",
    "search_memory",
    "search_memories",
    "retrieve_memory",
    "memory_recall",
    "memory_search",
    "lookup_memory",
)

#: A fixed instant, so nothing here depends on how fast the suite runs.
AT = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def _at() -> datetime:
    return AT


# --- the declarations ---------------------------------------------------


def test_the_local_declaration_is_well_formed_and_local() -> None:
    """The surviving local tool is read-only and discloses nothing (ADR-0048 §2)."""
    assert isinstance(CURRENT_TIME, ToolDefinition)
    assert CURRENT_TIME.side_effecting is False
    assert CURRENT_TIME.discloses == ()  # nothing leaves the device
    assert CURRENT_TIME.writes == ()


async def test_build_default_registry_advertises_no_memory_capability() -> None:
    """The unconfigured registry is ``current_time`` and nothing else (ADR-0208 §1, §6).

    Asserted over the registry's *advertised capabilities and its tool ids*, not by
    the absence of an import: ADR-0208 §6 asks for the property a selection stage
    can observe, and a module that imported nothing could still register a memory
    tool built somewhere else. The exhaustive equalities are the strong half — a
    re-added tool under any id or capability fails them — and the synonym sweep
    below states the same fact in the vocabulary #1715 was filed about.

    The configured half of §6 (a call *with* an egress integration) is
    ``test_send_email_registration.py``'s
    ``test_no_memory_capability_is_advertised_with_an_integration_either``.
    """
    registry = build_default_registry(now=_at, ledger=FakeAuditTrail(), gate=FakeAuditTrail())

    capabilities = await registry.capabilities()
    ids = [definition.id for definition in await registry.all_tools()]

    assert capabilities == ("report_current_time",)
    assert ids == ["current_time"]
    for synonym in MEMORY_SYNONYMS:
        assert synonym not in capabilities
        assert synonym not in ids


# --- current_time -------------------------------------------------------


async def test_current_time_reports_the_injected_clock() -> None:
    """The pure-compute tool returns the clock's instant, ISO-8601, under `utc`."""
    output = await CurrentTime(now=_at)({}, idempotency_key=None)

    assert output == {"utc": AT.isoformat()}


async def test_current_time_rejects_any_argument() -> None:
    """It takes none; its schema declares additionalProperties: false (ADR-0048 §2)."""
    with pytest.raises(ValueError, match="unexpected argument"):
        await CurrentTime(now=_at)({"timezone": "UTC"}, idempotency_key=None)


async def test_current_time_rejects_a_non_conforming_clock() -> None:
    """A naive reading raises rather than emitting a misleading timestamp (ADR-0026 §2)."""
    naive = CurrentTime(now=lambda: datetime(2026, 7, 23, 12, 0))  # noqa: DTZ001 — the bug under test
    with pytest.raises(ClockReadingError):
        await naive({}, idempotency_key=None)
