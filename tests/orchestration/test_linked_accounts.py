"""The owner's linked accounts beyond the shared suite (ADR-0373 §2:4, §4).

The shared suite (``linked_accounts_contract``) holds the engine, the fake and the wire
client to every outcome. This holds what only the module answering them, or the tree as
a whole, can show:

* **§4:1 and §4:6, whose act**: no tool, capability, plan step, work, task, upkeep job,
  gateway route, page panel, Telegram command or spoke calls one of the three members,
  and no model-authored value reaches an argument, because nothing but the command line
  calls them: the names occur only where the surface is declared, implemented, carried
  and called from the command line;
* **§2:4's order under a race**, where the store decides after the module's read;
* **a store that answers what its contract rules out** for the owner's act on the
  owner's link, raised as its fault rather than rendered as an outcome.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

import ai_assistant
from ai_assistant.core.errors import IdentityStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    LinkRefusal,
    LinkWrite,
    LinkWriteKind,
    LowerLinkOutcome,
    LowerLinkRefusal,
    Sureness,
    WithdrawLoweringOutcome,
)
from ai_assistant.orchestration import linked_accounts as owners_links
from ai_assistant.testing import FakeIdentityStore

if TYPE_CHECKING:
    from collections.abc import Callable

_LINE: Final = Account(kind="telegram", identifier="424242")

#: The package's root, every file under which is scanned.
_PACKAGE: Final = Path(ai_assistant.__file__).resolve().parent

#: The three members' names, as an identifier anywhere in a file: a call, a string, a
#: route, a capability name or a tool's.
_NAMES: Final = re.compile(r"\b(linked_accounts|lower_link|withdraw_lowering)\b")

#: Every file that may name one: the contract, the engine and the module answering it,
#: the canonical fake, the wire's client, route table and version record, the command
#: line and its rendering, and the identity store's own ``withdraw_lowering`` (Protocol,
#: store and fake), which is the store's member and no engine call.
_MAY_NAME: Final = frozenset(
    {
        "core/protocols.py",
        "core/types.py",
        "orchestration/engine.py",
        "orchestration/linked_accounts.py",
        "testing/engine.py",
        "testing/identities.py",
        "memory/identity_store.py",
        "wire/client.py",
        "wire/routes.py",
        "wire/envelope.py",
        "interfaces/cli.py",
        "interfaces/link_inspection.py",
    }
)


def _naming() -> set[str]:
    named: set[str] = set()
    for path in _PACKAGE.rglob("*"):
        if path.suffix not in {".py", ".js", ".html", ".json", ".toml", ".md", ".txt"}:
            continue
        if _NAMES.search(path.read_text(encoding="utf-8", errors="replace")):
            named.add(path.relative_to(_PACKAGE).as_posix())
    return named


def test_nothing_but_the_command_line_reaches_the_three_members() -> None:
    """§4:1, §4:6: no tool, plan step, work, gateway, page, Telegram or spoke names one.

    So no capability binds one, nothing in a work calls one, and no model-authored value
    becomes an argument: the only caller is the command line, which sends what the owner
    typed. The wire server dispatches by ``METHODS``, read off the Protocol, and names
    none of them.
    """
    assert _naming() <= _MAY_NAME, sorted(_naming() - _MAY_NAME)


def test_the_scan_sees_the_files_that_do_name_them() -> None:
    """The scan is not vacuous: it finds the engine, the client and the command line."""
    assert {
        "orchestration/engine.py",
        "wire/client.py",
        "interfaces/cli.py",
        "interfaces/link_inspection.py",
    } <= _naming()


def test_the_gateway_and_the_line_reach_none() -> None:
    """§4:6 by name: the gateway, its page and the Telegram line hold none of them."""
    named = _naming()
    assert not {one for one in named if one.startswith("interfaces/gateway/")}
    assert not {one for one in named if "telegram" in one}
    assert not {one for one in named if one.startswith(("tools/", "planning/", "permissions/"))}


class _Answering:
    """A store whose reads are a real fake's and whose writes answer as scripted."""

    def __init__(
        self,
        held: FakeIdentityStore,
        *,
        lower: Callable[[], LinkWrite] | None = None,
        withdraw: Callable[[], LinkWrite] | None = None,
    ) -> None:
        self._held = held
        self._lower = lower
        self._withdraw = withdraw

    async def identity(self, person_id: str) -> object:
        return await self._held.identity(person_id)

    async def lower(self, link_id: str, level: Sureness, *, by: str) -> LinkWrite:
        if self._lower is None:
            return await self._held.lower(link_id, level, by=by)
        return self._lower()

    async def withdraw_lowering(self, lowering_id: str, *, by: str) -> LinkWrite:
        if self._withdraw is None:
            return await self._held.withdraw_lowering(lowering_id, by=by)
        return self._withdraw()


def _refused(refusal: LinkRefusal) -> LinkWrite:
    return LinkWrite(kind=LinkWriteKind.REFUSED, refusal=refusal)


async def _line(store: FakeIdentityStore) -> str:
    held = await store.find_link(_LINE)
    assert held is not None
    return held.id


async def test_a_link_that_ends_before_the_write_is_an_unknown_link() -> None:
    """§2:4's first step, decided by the store when the link ended after the read."""
    held = FakeIdentityStore(configured=(_LINE,))
    store = _Answering(held, lower=lambda: _refused(LinkRefusal.UNKNOWN_RECORD))

    result = await owners_links.lower_link(store, await _line(held), Sureness.NONE)  # type: ignore[arg-type]

    assert result.outcome is LowerLinkOutcome.REFUSED
    assert result.refusal is LowerLinkRefusal.UNKNOWN_LINK


@pytest.mark.parametrize("refusal", [LinkRefusal.UNKNOWN_PERSON, LinkRefusal.NOT_ALLOWED])
async def test_a_refusal_the_owners_lowering_cannot_meet_is_a_store_fault(
    refusal: LinkRefusal,
) -> None:
    """The owner's identity is the store's from its creation, and the owner may lower any
    link: a store answering otherwise is not the store the contract describes."""
    held = FakeIdentityStore(configured=(_LINE,))
    store = _Answering(held, lower=lambda: _refused(refusal))

    with pytest.raises(IdentityStoreError, match=refusal.value):
        await owners_links.lower_link(store, await _line(held), Sureness.NONE)  # type: ignore[arg-type]


async def test_a_lowering_withdrawn_before_the_write_is_not_standing() -> None:
    held = FakeIdentityStore(configured=(_LINE,))
    made = await held.lower(await _line(held), Sureness.NONE, by=OWNER_PERSON_ID)
    assert made.record_id is not None
    store = _Answering(
        held, withdraw=lambda: LinkWrite(kind=LinkWriteKind.UNCHANGED, record_id=made.record_id)
    )

    result = await owners_links.withdraw_lowering(store, made.record_id)  # type: ignore[arg-type]

    assert result.outcome is WithdrawLoweringOutcome.NOT_STANDING


async def test_a_withdrawal_the_owner_may_not_make_is_a_store_fault() -> None:
    """Every lowering is the owner's (§4:3), so ``not_allowed`` is the store's fault."""
    held = FakeIdentityStore(configured=(_LINE,))
    made = await held.lower(await _line(held), Sureness.NONE, by=OWNER_PERSON_ID)
    assert made.record_id is not None
    store = _Answering(held, withdraw=lambda: _refused(LinkRefusal.NOT_ALLOWED))

    with pytest.raises(IdentityStoreError):
        await owners_links.withdraw_lowering(store, made.record_id)  # type: ignore[arg-type]
