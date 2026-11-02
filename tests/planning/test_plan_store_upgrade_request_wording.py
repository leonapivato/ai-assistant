"""ADR-0326 §4:2's test, for ADR-0338 §8:6: a file the release before the recorded wording wrote.

``tests/planning/legacy/plans-before-request-wording.db`` was written by the previous
release's own ``SqlitePlanStore`` (the build at ``2f300c539``, at the label ``19``),
through its public members alone, never by hand-built SQL. It holds six approval requests
for ``person:owner``, one of every state and ticket that release could write, each with
the effect record that wrote it:

- ``q-before-pin``, a pin, pending, with a card whose buttons carry ``tok-before-pin``;
- ``q-before-unpin``, an unpin, approved, its ticket held, with a card posted with no
  buttons, and its outcome pushed to ``act-before-unpin-approval``;
- ``q-before-remember``, a remember replacing ``assertion:before-1``, denied and pushed;
- ``q-before-stay``, a booking marked a deliberate repeat, approved, its ticket used by
  ``effect-before-stay``;
- ``q-before-void``, a pin, approved, its ticket made void;
- ``q-before-expired``, an unpin left to expire.

A request's call's ``wording`` is left out of a dump where it is unset, so each stored
request validates unchanged: the upgrade is the empty one ADR-0326 §4's note names, and
the label stays ``19``. The head opens a copy, writes nothing to open it, and reads every
record back as it was, each request serialising to the bytes the file holds. The opened
file then holds a pin's request carrying its wording, which outlives a reopen.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from ai_assistant.core.types import (
    ActivationEffect,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalWriteAnswer,
    RequestedCall,
    TicketState,
)
from ai_assistant.planning import SqlitePlanStore

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "plans-before-request-wording.db"

#: When the previous release wrote the first request, and when the head opens the file.
_WROTE_AT: Final = datetime(2026, 11, 1, 12, tzinfo=UTC)
_NOW: Final = _WROTE_AT + timedelta(hours=2)

_TABLES: Final = {
    "meta",
    "stopped_activations",
    "activation_effects",
    "observations",
    "scheduled_tasks",
    "approval_requests",
}

_REQUESTS: Final = [
    "q-before-pin",
    "q-before-unpin",
    "q-before-remember",
    "q-before-stay",
    "q-before-void",
    "q-before-expired",
]


def _now() -> datetime:
    return _NOW


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


def _dump(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every table's rows, read out of band and in a fixed order."""
    with sqlite3.connect(path) as conn:
        tables = [
            str(name)
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        return {
            table: sorted(conn.execute(f"SELECT * FROM {table}").fetchall(), key=repr)  # noqa: S608 — names read from the file's own catalogue
            for table in tables
        }


def _stored_requests(path: Path) -> list[str]:
    """The requests the file holds, as the bytes it holds them in, in the order written."""
    with sqlite3.connect(path) as conn:
        return [
            str(data)
            for (data,) in conn.execute("SELECT data FROM approval_requests ORDER BY written_seq")
        ]


def _open(path: Path) -> SqlitePlanStore:
    return SqlitePlanStore(path=path, now=_now)


def _worded_pin(held: ApprovalRequest) -> ApprovalRequest:
    """A new pin's request, its call the stored pin's with the wording its round read."""
    call = RequestedCall(
        tool=held.call.tool, values={"memory": "m:after-tea"}, wording="Robin takes green tea."
    )
    return held.model_copy(
        update={
            "id": "q-after-pin",
            "activation_id": "act-q-after-pin",
            "call": call,
            "written_at": _NOW,
            "expires_at": _NOW + timedelta(hours=24),
            "cards": (),
        }
    )


def _asking(request: ApprovalRequest) -> ActivationEffect:
    return ActivationEffect(
        id=f"ask-{request.id}",
        activation_id=request.activation_id,
        round=request.round,
        capability="request_approval",
        values_digest="f" * 64,
        decision_id=f"d-ask-{request.id}",
        claimed_at=_NOW,
        request=request.id,
    )


def test_the_fixture_is_the_previous_releases_file() -> None:
    """Labelled 19, the six tables, and the requests the docstring names."""
    dumped = _dump(_FIXTURE)

    assert _label(_FIXTURE) == "19"
    assert set(dumped) == _TABLES
    assert [str(row[0]) for row in dumped["approval_requests"]] == sorted(_REQUESTS)
    assert sorted(str(row[0]) for row in dumped["activation_effects"]) == sorted(
        [*(f"ask-{one}" for one in _REQUESTS), "effect-before-stay"]
    )
    assert all('"wording"' not in data for data in _stored_requests(_FIXTURE))


async def test_the_head_opens_it_writing_nothing_and_keeps_its_label(legacy: Path) -> None:
    """ADR-0326 §4's note: the upgrade is empty, the label stays and no row moves."""
    before = _dump(legacy)

    store = _open(legacy)
    try:
        assert len(await store.approval_requests(_REQUESTS)) == len(_REQUESTS)
    finally:
        store.close()

    assert _label(legacy) == "19"
    assert _dump(legacy) == before


async def test_every_request_reads_back_as_the_previous_release_wrote_it(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4: each record whole, every state and ticket among them."""
    store = _open(legacy)
    try:
        export = await store.export()
        by_token = await store.approval_request_by_token("tok-before-pin")
        pushed = await store.pushed_approval_outcomes()
    finally:
        store.close()

    requests = {one.id: one for one in export.approval_requests}
    assert list(requests) == _REQUESTS
    assert [
        (one.call.tool.capability, one.state, one.ticket, one.spent_by, one.pushed_to)
        for one in requests.values()
    ] == [
        ("pin", ApprovalRequestState.PENDING, None, None, None),
        (
            "unpin",
            ApprovalRequestState.APPROVED,
            TicketState.HELD,
            None,
            "act-before-unpin-approval",
        ),
        ("remember", ApprovalRequestState.DENIED, None, None, "act-before-remember-denial"),
        ("book_stay", ApprovalRequestState.APPROVED, TicketState.USED, "effect-before-stay", None),
        ("pin", ApprovalRequestState.APPROVED, TicketState.VOID, None, None),
        ("unpin", ApprovalRequestState.EXPIRED, None, None, None),
    ]
    assert dict(requests["q-before-pin"].call.values) == {"memory": "m:before-diet"}
    assert requests["q-before-remember"].call.replaces == ("assertion:before-1",)
    assert requests["q-before-stay"].call.deliberate_repeat
    assert [(card.position, card.token) for card in requests["q-before-pin"].cards] == [
        (41, "tok-before-pin")
    ]
    assert [(card.position, card.token) for card in requests["q-before-unpin"].cards] == [
        (42, None)
    ]
    assert by_token == requests["q-before-pin"]
    assert [one.id for one in pushed] == ["q-before-unpin", "q-before-remember"]
    assert all(one.call.wording is None for one in requests.values())


async def test_each_stored_request_serialises_to_the_bytes_the_file_holds(legacy: Path) -> None:
    """A dump leaves ``wording`` out where it is unset, so no stored request moves."""
    store = _open(legacy)
    try:
        read = await store.approval_requests(_REQUESTS)
    finally:
        store.close()

    assert [one.model_dump_json() for one in read] == _stored_requests(legacy)


async def test_the_opened_file_holds_a_worded_request_across_a_reopen(legacy: Path) -> None:
    """ADR-0338 §8:6: a pin's request written with its wording, beside the earlier ones."""
    store = _open(legacy)
    try:
        (held,) = await store.approval_requests(["q-before-pin"])
        request = _worded_pin(held)
        written = await store.write_approval_request(request, _asking(request), match=None)
    finally:
        store.close()
    assert written.answer is ApprovalWriteAnswer.WRITTEN

    reopened = _open(legacy)
    try:
        export = await reopened.export()
    finally:
        reopened.close()

    assert [one.id for one in export.approval_requests] == [*_REQUESTS, "q-after-pin"]
    assert export.approval_requests[-1] == request
    assert export.approval_requests[-1].call.wording == "Robin takes green tea."
    assert export.schema_version == 29
    assert _label(legacy) == "19"
