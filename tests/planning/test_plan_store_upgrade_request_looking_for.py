"""ADR-0326 §4:2's test, for ADR-0364 §10:6: a file the release before the kept *looking for* wrote.

``tests/planning/legacy/plans-before-request-looking-for.db`` was written by the previous
release's own ``SqlitePlanStore`` (the build at ``7e96d3c09``, the code the live hub runs,
at the label ``19``), through its public members alone, never by hand-built SQL. It holds
three approval requests for ``person:owner``, each with the effect record that wrote it:

- ``q-before-search``, a ``web_search``, approved, its ticket held, its outcome pushed to
  ``act-before-search-approval``, with no *looking for*, which that release did not keep;
- ``q-before-email``, an ``email`` from ``user`` marked ``exact``, approved, its ticket
  held, which ADR-0364 §8:6 reads as the ``send_email`` it translates to;
- ``q-before-pin``, a ``pin`` carrying its wording, pending, with a card whose buttons
  carry ``tok-before-pin``.

A request's call's ``looking_for`` is left out of a dump where it is unset, so each stored
request validates unchanged: the upgrade is the empty one ADR-0326 §4's note names, and
the label stays ``19``. The head opens a copy, writes nothing to open it, and reads every
record back as it was, each request serialising to the bytes the file holds. The opened
file then holds a search's request carrying its *looking for*, which outlives a reopen.
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
from ai_assistant.orchestration.renames import translated
from ai_assistant.planning import SqlitePlanStore
from ai_assistant.tools.send_email import EMAIL
from ai_assistant.tools.web_search import WEB_SEARCH

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "plans-before-request-looking-for.db"

#: When the previous release wrote the first request, and when the head opens the file.
_WROTE_AT: Final = datetime(2026, 11, 1, 12, tzinfo=UTC)
_NOW: Final = _WROTE_AT + timedelta(hours=2)

_REQUESTS: Final = ["q-before-search", "q-before-email", "q-before-pin"]


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


def _stored_requests(path: Path) -> list[str]:
    """The requests the file holds, as the bytes it holds them in, in the order written."""
    with sqlite3.connect(path) as conn:
        return [
            str(data)
            for (data,) in conn.execute("SELECT data FROM approval_requests ORDER BY written_seq")
        ]


def _open(path: Path) -> SqlitePlanStore:
    return SqlitePlanStore(path=path, now=_now)


def test_the_fixture_is_the_previous_releases_file() -> None:
    """Labelled 19, the requests the docstring names, and no request keeping a looking for."""
    assert _label(_FIXTURE) == "19"
    stored = _stored_requests(_FIXTURE)
    assert len(stored) == len(_REQUESTS)
    assert all('"looking_for"' not in data for data in stored)


async def test_every_request_reads_back_as_the_previous_release_wrote_it(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4: each record whole, and none keeping a looking for."""
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
        (one.call.tool.capability, one.state, one.ticket, one.pushed_to)
        for one in requests.values()
    ] == [
        (
            "web_search",
            ApprovalRequestState.APPROVED,
            TicketState.HELD,
            "act-before-search-approval",
        ),
        ("email", ApprovalRequestState.APPROVED, TicketState.HELD, None),
        ("pin", ApprovalRequestState.PENDING, None, None),
    ]
    assert all(one.call.looking_for is None for one in requests.values())
    assert requests["q-before-pin"].call.wording == "Robin is vegetarian."
    assert by_token == requests["q-before-pin"]
    assert [one.id for one in pushed] == ["q-before-search"]
    assert export.schema_version == 29


async def test_each_stored_request_serialises_to_the_bytes_the_file_holds(legacy: Path) -> None:
    """A dump leaves ``looking_for`` out where it is unset, so no stored request moves."""
    store = _open(legacy)
    try:
        read = await store.approval_requests(_REQUESTS)
    finally:
        store.close()

    assert [one.model_dump_json() for one in read] == _stored_requests(legacy)
    assert _label(legacy) == "19"


async def test_the_stored_email_runs_as_the_send_email_it_translates_to(legacy: Path) -> None:
    """ADR-0364 §8:6: an unused ticket under an old name is read as the new tool's call."""
    store = _open(legacy)
    try:
        (held,) = await store.approval_requests(["q-before-email"])
    finally:
        store.close()

    read = translated(held.call, {"send_email": EMAIL}.get)

    assert isinstance(read, RequestedCall)
    assert read.tool == EMAIL
    assert dict(read.values) == {
        "to": "maren@example.org",
        "subject": "Dinner",
        "words": "See you at 8.",
        "from": "user",
    }


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


async def test_the_opened_file_holds_a_kept_looking_for_across_a_reopen(legacy: Path) -> None:
    """ADR-0364 §10:2, §10:6: a search's request written with its looking for, kept."""
    store = _open(legacy)
    try:
        (held,) = await store.approval_requests(["q-before-search"])
        call = RequestedCall(
            tool=WEB_SEARCH,
            values={"origin": "https://search.example.com", "query": "museum hours sunday"},
            looking_for="When does it open on Sunday?",
        )
        request = held.model_copy(
            update={
                "id": "q-after-search",
                "activation_id": "act-q-after-search",
                "call": call,
                "written_at": _NOW,
                "expires_at": _NOW + timedelta(hours=24),
                "state": ApprovalRequestState.PENDING,
                "answer": None,
                "ticket": None,
                "pushed_to": None,
                "cards": (),
            }
        )
        written = await store.write_approval_request(request, _asking(request), match=None)
    finally:
        store.close()
    assert written.answer is ApprovalWriteAnswer.WRITTEN

    reopened = _open(legacy)
    try:
        export = await reopened.export()
    finally:
        reopened.close()

    assert [one.id for one in export.approval_requests] == [*_REQUESTS, "q-after-search"]
    assert export.approval_requests[-1].call.looking_for == "When does it open on Sunday?"
    assert export.schema_version == 29
    assert _label(legacy) == "19"
