"""Tests for the store-health census's entry point (ADR-0129 §5).

The mechanism has its own suite under ``tests/memory/test_health.py``. What is on
test here is everything the entry point owns: the instance lock (§4's first
clause, the one disposition §8 names that the mechanism cannot reach), the exit
codes, the two arguments, and the fact that this module drives the reader without
naming a single ``memory`` type.

Named ``_tool`` rather than mirroring ``service/store_health.py`` exactly, for the
reason ``test_reembed_tool.py`` states: ``tests/`` carries no ``__init__.py`` and
two test modules with one basename collide at collection.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.app import (
    STORE_HEALTH_DEFAULT_K,
    STORE_HEALTH_DEFAULT_SAMPLE,
    STORE_HEALTH_MAX_K,
)
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import (
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Provenance,
    SemanticMemory,
    Validity,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models import HashingEmbedder
from ai_assistant.service import store_health
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock
from ai_assistant.testing import FakeTraceSink

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_WHEN = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "hub-data"
    directory.mkdir(mode=0o700)
    return directory


@pytest.fixture
def settings(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """The tool's configuration, injected the way ``test_measures_tool`` injects it."""
    loaded = Settings(data_dir=data_dir, embedder=EmbedderKind.HASHING)
    monkeypatch.setattr(store_health, "load_settings", lambda: loaded)
    return loaded


def _seed(data_dir: Path, count: int) -> None:
    """Write ``count`` live records into the deployment's real memory store.

    Synchronous, and it drives the loop itself, because the tool under test is
    synchronous: ``main`` cannot be reached from a test that is already on a
    running loop and would not need one if it could.
    """

    async def seed() -> None:
        store = SqliteMemoryStore(
            path=data_dir / "memory.db",
            embedder=HashingEmbedder(dimensions=16),
            traces_sink=FakeTraceSink(),
            now=lambda: _WHEN,
        )
        try:
            await store.write_atomic(
                [
                    MemoryWrite(
                        record=SemanticMemory(
                            id=f"r{index}",
                            content=f"a stored belief {index}",
                            fact=f"a stored belief {index}",
                            validity=Validity(),
                            provenance=Provenance(
                                source=MemorySource.OBSERVED,
                                confidence=0.6,
                                last_updated=_WHEN,
                            ),
                        ),
                        mode=MemoryWriteMode.INSERT_IF_ABSENT,
                    )
                    for index in range(count)
                ]
            )
        finally:
            store.close()

    asyncio.run(seed())


class TestTheReport:
    """The paths that print something and succeed."""

    def test_a_deployment_with_no_memory_store_says_so_and_succeeds(
        self, settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Not a failure: a hub that has never run has written nothing (§4)."""
        assert store_health.main([]) == EXIT_OK

        printed = capsys.readouterr().out
        assert "no memory store" in printed
        assert not (data_dir / "memory.db").exists()

    def test_the_store_path_is_printed_by_the_tool(
        self, settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """§7 keeps the path off the report, so the tool that owns the diagnostics states it."""
        _seed(data_dir, 8)

        assert store_health.main(["--k", "3"]) == EXIT_OK

        assert str(data_dir / "memory.db") in capsys.readouterr().out

    def test_a_seeded_store_is_counted_and_the_figures_printed(
        self, settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(data_dir, 8)

        assert store_health.main(["--sample", "4", "--k", "3"]) == EXIT_OK

        printed = capsys.readouterr().out
        assert "store health census at" in printed
        assert "neighbourhood closure density" in printed
        assert "closure age" in printed
        assert "band fill" in printed
        assert "sample 4" in printed
        assert "k 3" in printed

    def test_an_empty_store_states_that_it_is_empty(
        self, settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """§4's fourth clause, reaching the operator through the entry point."""
        _seed(data_dir, 0)

        assert store_health.main([]) == EXIT_OK

        assert "holds no record" in capsys.readouterr().out

    def test_the_tool_writes_nothing_to_the_store(self, settings: Settings, data_dir: Path) -> None:
        """§4's second clause, seen from outside: the file does not move."""
        _seed(data_dir, 8)
        store = data_dir / "memory.db"
        before = (store.stat().st_size, store.stat().st_mtime_ns)

        assert store_health.main(["--k", "3"]) == EXIT_OK

        assert (store.stat().st_size, store.stat().st_mtime_ns) == before

    def test_the_defaults_are_the_mechanism_s_own(
        self, settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The two numbers in ``--help`` are the ones the run actually applies.

        They reach the entry point through the composition root rather than being
        restated here, because ADR-0129 §5 keeps this module free of subsystem
        imports and a second copy of a default is a thing that drifts.
        """
        _seed(data_dir, 3)

        assert store_health.main([]) == EXIT_OK

        printed = capsys.readouterr().out
        assert f"sample {STORE_HEALTH_DEFAULT_SAMPLE}" in printed
        assert f"k {STORE_HEALTH_DEFAULT_K}" in printed


class TestRefusals:
    """Every way this exits without a census, and the code each one carries."""

    def test_a_held_lock_is_refused_immediately(
        self, settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """§4: "A contended lock is refused immediately… the tool does not retry".

        The fifth disposition §8 requires a test for, and the only one the
        mechanism cannot reach: the lock is the entry point's, because
        ``InstanceLock`` lives in ``service`` and nothing may import ``service``.
        """
        _seed(data_dir, 8)
        holder = InstanceLock(data_dir / LOCK_FILENAME)
        assert holder.acquire()
        try:
            assert store_health.main(["--k", "3"]) == EXIT_RESTART
        finally:
            holder.release()

        reported = capsys.readouterr().err
        assert str(data_dir / LOCK_FILENAME) in reported, "§4 requires the lock path"
        assert str(data_dir) in reported, "§4 requires the data directory"
        assert "Stop the hub" in reported

    def test_a_configuration_failure_asks_a_human_to_act(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def refuse() -> Settings:
            raise ConfigurationError("ASSISTANT_DATA_DIR is not readable")

        monkeypatch.setattr(store_health, "load_settings", refuse)

        assert store_health.main([]) == EXIT_DEPLOYMENT

        assert "did not run" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "argv",
        [["--k", "0"], ["--k", "-2"], ["--sample", "0"], ["--k", "ten"]],
        ids=["k-zero", "k-negative", "sample-zero", "k-unparseable"],
    )
    def test_a_parameter_outside_its_domain_is_refused_by_the_parser(self, argv: list[str]) -> None:
        """§3's ``k`` domain, held at the command line as well as in the mechanism."""
        with pytest.raises(SystemExit):
            store_health.main(argv)

    def test_a_k_above_the_index_s_ceiling_is_refused_before_the_lock_is_taken(
        self, settings: Settings, data_dir: Path
    ) -> None:
        """The ceiling is the backend's, so the parser knows it through the composition root.

        Refusing here rather than inside the run is what keeps an unservable
        argument from presenting as a store failure — the classification
        ``service/exits.py`` gives a ``MemoryStoreError`` is "try again", and
        trying this again with the same argument would fail the same way.
        """
        _seed(data_dir, 8)

        with pytest.raises(SystemExit):
            store_health.main(["--k", str(STORE_HEALTH_MAX_K + 1)])

        assert not (data_dir / LOCK_FILENAME).exists(), "the lock was taken before the refusal"
