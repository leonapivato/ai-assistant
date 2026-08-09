"""MemoryIngestor — the production writer — passes the shared MemoryWriter suite.

The triad check demands only the *fake's* binding, so this file is what ADR-0028
§8 adds on top: a suite bound only to the double certifies the double while the
production writer drifts, and ``MemoryIngestor`` is what ``LearningLoop``
delegates to. ``test_ingest.py`` stays implementation tests and is not this
binding.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from memory_writer_contract import MemoryWriterContract, WriterFactory

from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor
from ai_assistant.testing import FakeTraceSink

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore, MemoryWriter


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


class TestMemoryIngestorContract(MemoryWriterContract):
    """Runs MemoryIngestor through the shared MemoryWriter conformance suite."""

    @pytest.fixture
    def make_writer(self) -> WriterFactory:
        def build(
            store: MemoryStore,
            policy: MemoryPolicy,
            *,
            id_factory: Callable[[], str] | None = None,
            conflict_limit: int | None = None,
        ) -> MemoryWriter:
            # Each `None` leaves the ingestor's own default, which is what the
            # suite's seams mean by "this obligation does not drive it".
            seams: dict[str, Any] = {}
            if id_factory is not None:
                seams["id_factory"] = id_factory
            if conflict_limit is not None:
                seams["conflict_limit"] = conflict_limit
            # A sink per writer, and one the suite never sees: ADR-0119 §7 makes it
            # a required constructor argument, and the shared suite is deliberately
            # not asked to assert that anything is emitted — emission is a property
            # of the wired deployment, not of the ``MemoryWriter`` contract this
            # suite is about.
            return MemoryIngestor(
                store=store,
                policy=policy,
                traces_sink=FakeTraceSink(),
                now=_fixed_now,
                **seams,
            )

        return build

    @pytest.fixture
    def writer(self) -> MemoryWriter:
        return MemoryIngestor(
            traces_sink=FakeTraceSink(),
            store=InMemoryMemoryStore(now=_fixed_now),
            policy=DefaultMemoryPolicy(),
            now=_fixed_now,
        )
