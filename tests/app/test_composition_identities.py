"""The composition root's identity store, and the owner's accounts linked at start.

ADR-0366 §11's store is opened on every hub, on its own file in the data directory,
whatever the person-model switch says, since an identity is not a person model (§2:6).
It holds the owner's identity (§2:5) and, as it opens, ties the owner's configured
accounts to it by the owner's ``configured`` act: the hub's own machine, the web door's
hosted device where this hub names one, and the line's Telegram account where the line
is configured (#3642, "already linked"). Nothing reads it yet, so nothing the engine does
changes.

**Nothing here opens a socket.** Every case builds over the hashing embedder and closes
what it built.
"""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.app import build_engine
from ai_assistant.app.composition import IDENTITIES_FILENAME, configured_accounts
from ai_assistant.core.channel_validation import most_sureness
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    OWNER_PERSON_ID,
    Account,
    LinkAct,
    LinkActHow,
    Sureness,
)
from ai_assistant.memory import SqliteIdentityStore

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio

_LINE: Final[dict[str, Any]] = {"telegram_connection": "conn-line", "telegram_user_id": 424242}
_HUB: Final = Account(kind="conversation", identifier=HUB_DEVICE_ID)
_TELEGRAM: Final = Account(kind="telegram", identifier="424242")
_CONFIGURED: Final = LinkAct(how=LinkActHow.CONFIGURED, by=OWNER_PERSON_ID)


def test_a_hub_with_nothing_configured_names_its_own_machine_alone() -> None:
    assert configured_accounts(Settings(embedder=EmbedderKind.HASHING)) == (_HUB,)


def test_the_line_names_the_owners_telegram_account() -> None:
    settings = Settings(embedder=EmbedderKind.HASHING, **_LINE)

    assert configured_accounts(settings) == (_HUB, _TELEGRAM)


def test_the_web_doors_hosted_device_is_named_where_this_hub_is_told_it() -> None:
    # The hosted door's other settings are the gateway's to check; the device is all this
    # reads, so it is set alone, past the cross-checks the whole door owes.
    settings = Settings(embedder=EmbedderKind.HASHING, **_LINE).model_copy(
        update={"gateway_hosted_device": "browser-hosted"}
    )

    assert configured_accounts(settings) == (
        _HUB,
        Account(kind="conversation", identifier="browser-hosted"),
        _TELEGRAM,
    )


def test_every_configured_account_is_of_a_kind_that_gives_normal() -> None:
    """The levels the owner's accounts start at: each kind's declared most (§5:2, §5:3)."""
    settings = Settings(embedder=EmbedderKind.HASHING, **_LINE).model_copy(
        update={"gateway_hosted_device": "browser-hosted"}
    )

    assert {most_sureness(one.kind) for one in configured_accounts(settings)} == {Sureness.NORMAL}


async def test_the_store_is_opened_on_every_hub_holding_the_owner(tmp_path: Path) -> None:
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    await engine.aclose()

    path = tmp_path / IDENTITIES_FILENAME
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    store = SqliteIdentityStore(path=path)
    try:
        owner = await store.identity(OWNER_PERSON_ID)
    finally:
        store.close()
    assert owner is not None
    assert [(one.account, one.act) for one in owner.links] == [(_HUB, _CONFIGURED)]


async def test_the_owners_accounts_are_linked_at_start_and_kept_across_starts(
    tmp_path: Path,
) -> None:
    first = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    await first.aclose()
    # The line set up later: the next start links its account, keeping the first link.
    again = build_engine(Settings(embedder=EmbedderKind.HASHING, **_LINE), data_dir=tmp_path)
    await again.aclose()

    store = SqliteIdentityStore(path=tmp_path / IDENTITIES_FILENAME)
    try:
        owner = await store.identity(OWNER_PERSON_ID)
        line = await store.find_link(_TELEGRAM)
    finally:
        store.close()
    assert owner is not None
    assert [(one.account, one.act) for one in owner.links] == [
        (_HUB, _CONFIGURED),
        (_TELEGRAM, _CONFIGURED),
    ]
    assert line is not None
    assert line.person_id == OWNER_PERSON_ID


async def test_a_setting_cleared_ends_the_link_it_named(tmp_path: Path) -> None:
    """A link stands only while the act it was recorded from stands (ADR-0366 §3:1)."""
    first = build_engine(Settings(embedder=EmbedderKind.HASHING, **_LINE), data_dir=tmp_path)
    await first.aclose()
    again = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    await again.aclose()

    store = SqliteIdentityStore(path=tmp_path / IDENTITIES_FILENAME)
    try:
        owner = await store.identity(OWNER_PERSON_ID)
        line = await store.find_link(_TELEGRAM)
    finally:
        store.close()
    assert line is None
    assert owner is not None
    assert [one.account for one in owner.standing_links] == [_HUB]
    assert [(one.account, one.standing) for one in owner.links] == [
        (_HUB, True),
        (_TELEGRAM, False),
    ]
