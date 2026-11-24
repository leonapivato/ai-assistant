"""The composition root's store of whose each thing is, and the start's writes (ADR-0381).

The store is opened on every hub, on its own file in the data directory, owner-only
(ADR-0004 §4, ADR-0381 §3:1). Opening it is the start's writes (§4:1): before the engine
admits any work, each thing the hub holds that has no record is recorded as the owner's —
the system's own chat, the line's place where the line is configured, the schedule, the
approvals, each account connection the hub registers and each source by its reader's
declared identity — and an account linked to identify its person gets none (§2:3). A
second start writes nothing, and a thing the hub holds from a later start is recorded at
that start. Nothing reads the store yet.

**Nothing here opens a socket.** Every case builds over the hashing embedder and closes
what it built.
"""

from __future__ import annotations

import stat
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.app import build_engine
from ai_assistant.app.composition import THING_RECORDS_FILENAME, held_things
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    APPROVALS_CONNECTION,
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    SCHEDULE_CONNECTION,
    ThingKey,
    ThingKind,
    ThingRecord,
)
from ai_assistant.orchestration.approvals import THE_APPROVALS
from ai_assistant.orchestration.channel_kinds import place_of
from ai_assistant.orchestration.task_scheduler import SCHEDULE
from ai_assistant.permissions import SqliteThingRecordStore
from ai_assistant.readers.calendar import CALENDAR_READER_NAME
from ai_assistant.testing import FakeReader

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio

_BOT: Final = "conn-bot"
_CHAT: Final = 424242


def _connection(identifier: str) -> ThingKey:
    return ThingKey(kind=ThingKind.CONNECTION, identifier=identifier)


#: What every hub holds: the system's own chat, the schedule and the approvals.
_ALWAYS: Final = (
    _connection(OWN_CHAT_CONNECTION),
    _connection(SCHEDULE_CONNECTION),
    _connection(APPROVALS_CONNECTION),
)

#: The line's place: one chat of one bot.
_LINE: Final = _connection(f"telegram:{_BOT}/{_CHAT}")

#: The email account, with the endpoint ``send_email`` needs beside it (ADR-0148 §6).
_MAIL: Final = "conn-mail"
_MAIL_ENDPOINT: Final = "smtps://mail.example.invalid:465"


async def _records(directory: Path) -> tuple[ThingRecord, ...]:
    store = SqliteThingRecordStore(path=directory / THING_RECORDS_FILENAME)
    try:
        return await store.export()
    finally:
        store.close()


def _keys(records: tuple[ThingRecord, ...]) -> list[ThingKey]:
    return [one.key for one in records]


def test_the_built_in_places_are_spelled_as_orchestration_names_them() -> None:
    """``core`` spells the schedule and the approvals again; the two must agree."""
    assert place_of(SCHEDULE) == SCHEDULE_CONNECTION
    assert place_of(THE_APPROVALS) == APPROVALS_CONNECTION


def test_a_bare_hub_holds_its_own_chat_the_schedule_and_the_approvals() -> None:
    assert held_things(Settings(embedder=EmbedderKind.HASHING), sources=()) == _ALWAYS


def test_a_configured_hub_holds_every_thing_of_adr_0381_section_2_once() -> None:
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        telegram_connection=_BOT,
        telegram_user_id=_CHAT,
        send_email_connection=_MAIL,
        send_email_endpoint=_MAIL_ENDPOINT,
        web_search_connection="conn-search",
        web_search_origin="https://search.example.invalid",
        forecast_connection="conn-forecast",
        forecast_origin="https://forecast.example.invalid",
        forecast_latitude=45.0,
        forecast_longitude=7.0,
    )
    calendar = FakeReader(name="calendar")

    held = held_things(settings, sources=(calendar, None, calendar))

    assert held == (
        _connection(OWN_CHAT_CONNECTION),
        _LINE,
        _connection(SCHEDULE_CONNECTION),
        _connection(APPROVALS_CONNECTION),
        _connection("account:conn-mail"),
        _connection("account:conn-search"),
        _connection("account:conn-forecast"),
        ThingKey(kind=ThingKind.SOURCE, identifier="calendar"),
    )


def test_no_account_linked_to_identify_its_person_is_held() -> None:
    """ADR-0381 §2:3: a device or the line's Telegram account carries no record here."""
    settings = Settings(
        embedder=EmbedderKind.HASHING, telegram_connection=_BOT, telegram_user_id=_CHAT
    ).model_copy(
        # Unvalidated on purpose: only the hosted device matters here, and the hosted
        # listener it would need is beside the point of what the hub holds.
        update={"gateway_hosted_device": "web-leo"}
    )

    identifiers = {one.identifier for one in held_things(settings, sources=())}

    assert not any("hub" in one or "web-leo" in one for one in identifiers)
    assert f"telegram:{_CHAT}" not in identifiers
    assert identifiers == {one.identifier for one in (*_ALWAYS, _LINE)}


async def test_a_reference_no_key_can_spell_is_left_out_and_the_hub_starts(
    tmp_path: Path,
) -> None:
    """``Settings`` takes a reference verbatim; a thing no key spells is no one's (§5)."""
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        send_email_connection=f" {_MAIL}",
        send_email_endpoint=_MAIL_ENDPOINT,
    )

    assert held_things(settings, sources=()) == _ALWAYS
    engine = build_engine(settings, data_dir=tmp_path)
    await engine.aclose()
    assert _keys(await _records(tmp_path)) == list(_ALWAYS)


async def test_the_store_is_opened_on_every_hub_owner_only_naming_the_owner(
    tmp_path: Path,
) -> None:
    before = datetime.now(UTC)
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    await engine.aclose()

    path = tmp_path / THING_RECORDS_FILENAME
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    records = await _records(tmp_path)
    assert _keys(records) == list(_ALWAYS)
    assert {one.person for one in records} == {OWNER_PERSON_ID}
    assert len({one.recorded_at for one in records}) == 1
    assert records[0].recorded_at >= before


async def test_a_second_start_writes_nothing(tmp_path: Path) -> None:
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        send_email_connection=_MAIL,
        send_email_endpoint=_MAIL_ENDPOINT,
    )
    first = build_engine(settings, data_dir=tmp_path)
    await first.aclose()
    written = await _records(tmp_path)

    again = build_engine(settings, data_dir=tmp_path)
    await again.aclose()

    assert await _records(tmp_path) == written
    assert _keys(written) == [*_ALWAYS, _connection("account:conn-mail")]


async def test_a_thing_held_from_a_later_start_is_recorded_at_that_start(
    tmp_path: Path,
) -> None:
    first = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    await first.aclose()
    written = await _records(tmp_path)

    settings = Settings(
        embedder=EmbedderKind.HASHING,
        send_email_connection=_MAIL,
        send_email_endpoint=_MAIL_ENDPOINT,
        calendar_reader_path=tmp_path / "calendar.ics",
    )
    later = build_engine(settings, data_dir=tmp_path)
    await later.aclose()

    records = await _records(tmp_path)
    assert records[: len(written)] == written
    assert _keys(records[len(written) :]) == [
        _connection("account:conn-mail"),
        ThingKey(kind=ThingKind.SOURCE, identifier=CALENDAR_READER_NAME),
    ]
    assert records[-1].recorded_at > written[0].recorded_at


async def test_the_lines_place_is_recorded_where_the_line_is_configured(tmp_path: Path) -> None:
    settings = Settings(
        embedder=EmbedderKind.HASHING, telegram_connection=_BOT, telegram_user_id=_CHAT
    )
    engine = build_engine(settings, data_dir=tmp_path)
    await engine.aclose()

    assert _connection(f"telegram:{_BOT}/{_CHAT}") in _keys(await _records(tmp_path))
