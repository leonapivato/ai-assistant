"""ADR-0326 §4:2's test, for ADR-0380 §3:2: a plan store the release before the default grant wrote.

``tests/planning/legacy/plans-before-adr-0380.db`` was written by the previous release's
own ``SqlitePlanStore`` (the build at ``522da83f3``, at the label ``19``), through its
public members alone, never by hand-built SQL. It holds two approval requests for
``person:owner``, each with the effect record that wrote it and each holding by value
the declaration that build declared, which had no default grant:

- ``q-before-email``, a ``send_email``, pending;
- ``q-before-pin``, a ``pin_memory``, approved by a tap, its ticket held.

A declaration with no default grant leaves the field out of its dump, so each stored
request validates unchanged: the upgrade is the empty one ADR-0326 §4's note names, and
the label stays ``19``. The head opens a copy, reads every request back as it was, each
declaration with no default grant (ADR-0380 §3:1), and a request it then writes holds the
declaration this build declares, default grant and all.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from ai_assistant.core.types import (
    ActivationEffect,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalWriteAnswer,
    RequestedCall,
    TicketState,
)
from ai_assistant.orchestration.person_calls import PIN
from ai_assistant.planning import SqlitePlanStore
from ai_assistant.tools.send_email import EMAIL

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "plans-before-adr-0380.db"

#: When the previous release wrote its first request, and when the head opens the file.
_WROTE_AT: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
_NOW: Final = _WROTE_AT + timedelta(hours=1)

_REQUESTS: Final = ["q-before-email", "q-before-pin"]


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A copy of the file the previous release wrote, so the fixture itself never changes."""
    target = tmp_path / "plans.db"
    shutil.copyfile(_FIXTURE, target)
    return target


def _label(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        (value,) = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return str(value)


def _stored_requests(path: Path) -> list[str]:
    """The requests the file holds, as the bytes it holds them in, in the order written."""
    with sqlite3.connect(path) as conn:
        return [
            str(data)
            for (data,) in conn.execute("SELECT data FROM approval_requests ORDER BY written_seq")
        ]


def _open(path: Path) -> SqlitePlanStore:
    return SqlitePlanStore(path=path, now=lambda: _NOW)


def test_the_fixture_is_the_previous_releases_file() -> None:
    """Labelled 19, the requests the docstring names, and no declaration with a grant."""
    assert _label(_FIXTURE) == "19"
    stored = _stored_requests(_FIXTURE)
    assert len(stored) == len(_REQUESTS)
    assert all('"default_grant"' not in data for data in stored)


async def test_every_request_reads_back_as_the_previous_release_wrote_it(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4, ADR-0380 §3:1: each whole, each declaration with no grant."""
    store = _open(legacy)
    try:
        export = await store.export()
        read = await store.approval_requests(_REQUESTS)
    finally:
        store.close()

    requests = {one.id: one for one in export.approval_requests}
    assert list(requests) == _REQUESTS
    assert [(one.call.tool.capability, one.state, one.ticket) for one in requests.values()] == [
        ("send_email", ApprovalRequestState.PENDING, None),
        ("pin_memory", ApprovalRequestState.APPROVED, TicketState.HELD),
    ]
    assert all(one.call.tool.default_grant is None for one in requests.values())
    assert sorted(one.id for one in export.activation_effects) == [
        "effect-q-before-email",
        "effect-q-before-pin",
    ]
    assert [one.model_dump_json() for one in read] == _stored_requests(legacy)
    assert _label(legacy) == "19"


async def test_a_stored_call_differs_from_this_builds_declaration_by_its_grant_alone(
    legacy: Path,
) -> None:
    """The one change across the release, so a held ticket is not this build's call.

    A ticket runs only where the registry still offers the declaration its card showed,
    so the ticket held here does not run under this build, as after any edit to a
    declaration (ADR-0380's consequences).
    """
    store = _open(legacy)
    try:
        email, pin = await store.approval_requests(_REQUESTS)
    finally:
        store.close()

    for request, current in ((email, EMAIL), (pin, PIN)):
        assert current.default_grant is not None
        assert request.call.tool != current
        assert request.call.tool == current.model_copy(update={"default_grant": None})


async def test_a_request_written_after_holds_its_default_grant_across_a_reopen(
    legacy: Path,
) -> None:
    """The opened file keeps a declaration with its grant, at the label it had."""
    request = ApprovalRequest(
        id="q-after-pin",
        person="person:owner",
        activation_id="act-q-after-pin",
        round="r1",
        call=RequestedCall(tool=PIN, values={"memory": "M2"}),
        why="You asked me to.",
        written_at=_NOW,
        expires_at=_NOW + timedelta(hours=24),
    )
    store = _open(legacy)
    try:
        written = await store.write_approval_request(
            request,
            ActivationEffect(
                id="effect-q-after-pin",
                activation_id="act-q-after-pin",
                round="r1",
                capability="request_approval",
                values_digest="e" * 64,
                decision_id="d-ask-q-after-pin",
                claimed_at=_NOW,
                request="q-after-pin",
            ),
            match=None,
        )
    finally:
        store.close()
    assert written.answer is ApprovalWriteAnswer.WRITTEN

    reopened = _open(legacy)
    try:
        (read,) = await reopened.approval_requests(["q-after-pin"])
    finally:
        reopened.close()

    assert read.call.tool == PIN
    assert read.call.tool.default_grant == PIN.default_grant
    assert _label(legacy) == "19"
