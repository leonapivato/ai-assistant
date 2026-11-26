"""``assistant export-domain``: one domain's export as one JSON document (ADR-0385 §6:10).

The command takes ``mine`` (the owner's domain) or ``shared`` (the hub's shared things),
calls ``export_domain`` and writes the export's own JSON to standard output and nothing
else there; a refusal and an error go to standard error with a non-zero exit and no
document (ADR-0186 §9:2's rule for the trail's export, which §6:10 takes).
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Final

import pytest
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import DomainExport, DomainExportResult, RecordHome
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.testing.memories import memory
from ai_assistant.wire.errors import TransportError

if TYPE_CHECKING:
    from collections.abc import Callable

_MINE: Final = RecordHome.owners()
_SHARED: Final = RecordHome.shared()


class _Answering(FakeAssistantEngine):
    """The canonical fake, its export answered by ``answer`` where one is given."""

    def __init__(self, answer: Callable[[], DomainExportResult] | None = None) -> None:
        super().__init__()
        self._answer = answer

    async def export_domain(self, domain: RecordHome, /) -> DomainExportResult:
        if self._answer is None:
            return await super().export_domain(domain)
        self.calls.append(("export_domain", {"domain": domain}))
        return self._answer()


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    """Point the command's startup at ``engine``, through ``_open_engine``."""

    async def _open() -> object:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)


def _seeded() -> _Answering:
    """The canonical fake holding one memory of the owner's and one of the shared things'."""
    engine = _Answering()
    for record_id, words, home in (
        ("m-own", "they like the window seat", _MINE),
        ("m-shared", "the hall light is on a timer", _SHARED),
    ):
        asyncio.run(engine.episode_memory.add(memory(record_id, words, home=home)))
    return engine


@pytest.mark.parametrize(("spelling", "domain"), [("mine", _MINE), ("shared", _SHARED)])
def test_the_export_is_one_json_document_on_standard_output_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch, spelling: str, domain: RecordHome
) -> None:
    """§6:10: the whole stream parses as one document, which validates back as the export."""
    engine = _seeded()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["export-domain", spelling])

    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.endswith("}\n")
    exported = DomainExport.model_validate(json.loads(result.stdout))
    assert exported.domain == domain
    assert [one.id for one in exported.memory] == [f"m-{'own' if spelling == 'mine' else 'shared'}"]
    assert engine.calls == [("export_domain", {"domain": domain})]


def test_a_refusal_goes_to_standard_error_with_no_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused export writes nothing on standard output, and the exit says it failed."""
    _wire(monkeypatch, _Answering(DomainExportResult.not_offered))

    result = CliRunner().invoke(cli.app, ["export-domain", "mine"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "That domain cannot be exported: only yours and the shared things can." in " ".join(
        result.stderr.split()
    )


def test_an_oversized_export_goes_to_standard_error_with_no_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6:7: whole or refused; the refusal is an error on standard error."""

    def _too_big() -> DomainExportResult:
        raise OversizedValueError("the export exceeds the contract limit", limit=1024, size=9999)

    _wire(monkeypatch, _Answering(_too_big))

    result = CliRunner().invoke(cli.app, ["export-domain", "shared"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "the export exceeds the contract limit" in " ".join(result.stderr.split())


def test_an_unreachable_hub_is_reported_on_standard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The transport failure stays off the document's stream too."""

    async def _refuse() -> object:
        raise TransportError("no hub is listening")

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _refuse)

    result = CliRunner().invoke(cli.app, ["export-domain", "mine"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not reachable" in " ".join(result.stderr.split())


@pytest.mark.parametrize("spelling", ["everything", "", "person:sam", "group:house"])
def test_any_other_spelling_is_refused_before_the_hub_is_asked(
    monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    """§2:3: no value means every domain, and no domain is defaulted."""
    engine = _Answering()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["export-domain", spelling])

    assert result.exit_code != 0
    assert result.stdout == ""
    assert engine.calls == []


def test_the_domain_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """§2:3, ADR-0101 §1:5: a bare ``export-domain`` names no domain and exports nothing."""
    engine = _Answering()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["export-domain"])

    assert result.exit_code != 0
    assert engine.calls == []


def test_the_bare_name_export_is_still_not_a_command() -> None:
    """ADR-0186 §9:4, as ADR-0385 §11 keeps it: this command is not named ``export``."""
    result = CliRunner().invoke(cli.app, ["export", "--help"])
    assert result.exit_code != 0
