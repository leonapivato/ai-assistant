"""Tests for the offline measure report's entry point (ADR-0120 §9).

The mechanism has its own suites under ``tests/evaluation/``. What is on test
here is everything the entry point owns: the instance lock, the exit codes, the
window arguments, and the fact that this module drives the reader without naming
a single ``evaluation`` type.

Named ``_tool`` rather than mirroring ``service/measures.py`` exactly, for the
reason ``test_reembed_tool.py`` states: ``tests/`` carries no ``__init__.py`` and
two test modules with one basename collide at collection.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import EvaluationTrace, TraceKind, TraceOutcome
from ai_assistant.evaluation import SqliteTraceStore
from ai_assistant.service import measures
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_START = datetime(2026, 7, 1, tzinfo=UTC)
_END = datetime(2026, 8, 1, tzinfo=UTC)
_ARGS = ["--from", "2026-07-01", "--until", "2026-08-01", "--settling-hours", "24"]


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "hub-data"
    directory.mkdir(mode=0o700)
    return directory


@pytest.fixture
def settings(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """The tool's configuration, injected the way ``test_reembed_tool`` injects it."""
    loaded = Settings(data_dir=data_dir, embedder=EmbedderKind.HASHING)
    monkeypatch.setattr(measures, "load_settings", lambda: loaded)
    return loaded


def _seed(data_dir: Path, *traces: EvaluationTrace) -> None:
    """Write ``traces`` into the deployment's real trace store.

    Synchronous, and it drives the loop itself, because every test below calls
    ``main`` — which calls :func:`asyncio.run`, and so cannot be reached from a
    test that is already on a running loop.
    """

    async def seed() -> None:
        store = SqliteTraceStore(path=data_dir / "traces.db")
        try:
            for trace in traces:
                await store.emit(trace)
        finally:
            store.close()

    asyncio.run(seed())


def _retained(data_dir: Path) -> tuple[EvaluationTrace, ...]:
    """Every trace the store holds, read back the same way."""

    async def read() -> tuple[EvaluationTrace, ...]:
        store = SqliteTraceStore(path=data_dir / "traces.db")
        try:
            return (await store.walk(limit=100)).traces
        finally:
            store.close()

    return asyncio.run(read())


def _operation(seam: str, when: datetime) -> EvaluationTrace:
    return EvaluationTrace(
        kind=TraceKind.OPERATION,
        seam=seam,
        occurred_at=when,
        elapsed=timedelta(milliseconds=5),
        outcome=TraceOutcome.OK,
    )


class TestTheReport:
    """The happy paths, over a store this deployment actually holds."""

    def test_a_deployment_with_no_trace_store_says_so_and_succeeds(
        self, settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Not a failure: a hub that has never run has recorded nothing."""
        assert measures.main(_ARGS) == EXIT_OK

        assert "there is no trace store" in capsys.readouterr().out
        assert not (data_dir / "traces.db").exists()

    def test_a_seeded_store_is_walked_and_the_figures_printed(
        self, settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(data_dir, _operation("start", _START), _operation("converse", _END))

        assert measures.main(_ARGS) == EXIT_OK

        printed = capsys.readouterr().out
        assert "memory precision" in printed
        assert "correction rate" in printed
        assert "operation latency" in printed

    def test_an_empty_store_states_the_empty_stream(
        self, settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """§8's clause, reaching the operator through the entry point."""
        _seed(data_dir)

        assert measures.main(_ARGS) == EXIT_OK

        assert "empty" in capsys.readouterr().out

    def test_the_tool_writes_no_trace_of_its_own(self, settings: Settings, data_dir: Path) -> None:
        """§9: "The reporting tool emits no trace and purges none"."""
        _seed(data_dir, _operation("start", _START))
        before = (data_dir / "traces.db").stat().st_mtime_ns

        measures.main(_ARGS)

        assert len(_retained(data_dir)) == 1
        assert (data_dir / "traces.db").stat().st_mtime_ns == before


class TestRefusals:
    """Every way this exits without a figure, and the code each one carries."""

    def test_a_window_before_the_oldest_trace_asks_the_operator_to_act(
        self, settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A refused window is ``78``: the same command would refuse again."""
        _seed(data_dir, _operation("start", datetime(2026, 7, 15, tzinfo=UTC)))

        assert measures.main(_ARGS) == EXIT_DEPLOYMENT

        assert "before the oldest retained trace" in capsys.readouterr().out

    def test_a_held_lock_is_refused_immediately(
        self, settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """§9: "A contended lock is refused immediately… the tool does not retry"."""
        _seed(data_dir, _operation("start", _START))
        holder = InstanceLock(data_dir / LOCK_FILENAME)
        assert holder.acquire()
        try:
            assert measures.main(_ARGS) == EXIT_RESTART
        finally:
            holder.release()

        reported = capsys.readouterr().err
        assert str(data_dir / LOCK_FILENAME) in reported
        assert "Stop the hub" in reported

    def test_a_configuration_failure_asks_a_human_to_act(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def refuse() -> Settings:
            raise ConfigurationError("ASSISTANT_DATA_DIR is not readable")

        monkeypatch.setattr(measures, "load_settings", refuse)

        assert measures.main(_ARGS) == EXIT_DEPLOYMENT

        assert "did not run" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "argv",
        [
            ["--until", "2026-08-01", "--settling-hours", "24"],
            ["--from", "2026-07-01", "--settling-hours", "24"],
            ["--from", "2026-07-01", "--until", "2026-08-01"],
        ],
        ids=["no-start", "no-end", "no-settling"],
    )
    def test_the_window_and_the_settling_are_all_required(self, argv: list[str]) -> None:
        """§1: "a figure reported without both is not one of these measures"."""
        with pytest.raises(SystemExit):
            measures.main(argv)

    def test_an_unparseable_instant_is_refused_by_the_parser(self) -> None:
        with pytest.raises(SystemExit):
            measures.main(["--from", "last tuesday", "--until", "now", "--settling-hours", "1"])


class TestArguments:
    """What the two window arguments mean."""

    def test_a_naive_instant_is_read_as_utc(self) -> None:
        assert measures._instant("2026-07-01") == _START

    def test_an_offset_is_honoured(self) -> None:
        assert measures._instant("2026-07-01T02:00:00+02:00") == _START

    def test_the_resolved_window_is_echoed_in_the_report(
        self, settings: Settings, data_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The assumption above is visible in the output rather than only in a docstring."""
        _seed(data_dir, _operation("start", _START))

        measures.main(_ARGS)

        assert "2026-07-01T00:00:00+0000" in capsys.readouterr().out


class TestSettlingArgument:
    """``--settling-hours`` is a duration, and ``float`` alone does not say so.

    ``float("nan")`` and ``float("inf")`` both parse, and ``timedelta`` then
    raises from a line no ``except`` clause in the tool covers — so the process
    would exit with a traceback rather than with one of the codes it documents.
    """

    @pytest.mark.parametrize("hours", ["nan", "inf", "-inf", "-1", "not-a-number"], ids=str)
    def test_a_value_a_duration_cannot_hold_is_refused_by_the_parser(self, hours: str) -> None:
        with pytest.raises(SystemExit):
            measures.main(
                ["--from", "2026-07-01", "--until", "2026-08-01", "--settling-hours", hours]
            )

    def test_a_settling_longer_than_any_duration_is_refused_by_the_parser(self) -> None:
        with pytest.raises(SystemExit):
            measures.main(
                ["--from", "2026-07-01", "--until", "2026-08-01", "--settling-hours", "1e30"]
            )

    def test_hours_become_the_settling_period(self) -> None:
        assert measures._settling("48") == timedelta(days=2)
        assert measures._settling("0") == timedelta(0)
