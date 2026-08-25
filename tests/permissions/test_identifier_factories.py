"""Both identifier factories pass the shared conformance suite (ADR-0192 §2).

The durable ledger's and the canonical fake's, held to one contract. They are two
copies of one construction rather than one import — nothing in
``ai_assistant.testing`` imports a subsystem, and the factory is
``permissions/``-internal by ADR-0192 §2's own words — so a shared suite is what
stops the copies drifting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from identifier_factory_contract import IdentifierFactoryContract

from ai_assistant.permissions.identifiers import IdentifierSpace, ProcessIdentifiers
from ai_assistant.testing.permissions import FakeIdentifiers, FakeIdentifierSpace

if TYPE_CHECKING:
    from collections.abc import Callable


class TestProcessIdentifiersContract(IdentifierFactoryContract):
    """Runs the durable ledger's factory through the shared suite."""

    @pytest.fixture
    def build(self) -> Callable[[], Any]:
        """A shared space rather than :data:`PROCESS_SPACE`, so cases stay isolated.

        Constructed the way the composition root constructs one — no per-instance
        state of its own — which is the property the two-instance cases are about.
        The space is fixed per case rather than per process only so that one case's
        draws cannot make another's assertion true.
        """
        space = IdentifierSpace()
        return lambda: ProcessIdentifiers(space=space)

    @pytest.fixture
    def pinned(self) -> Callable[[str], Any]:
        return lambda nonce: ProcessIdentifiers(space=IdentifierSpace(nonce=nonce))

    @pytest.fixture
    def pinned_pair(self) -> Callable[[str], tuple[Any, Any]]:
        def over_one_space(nonce: str) -> tuple[Any, Any]:
            space = IdentifierSpace(nonce=nonce)
            return ProcessIdentifiers(space=space), ProcessIdentifiers(space=space)

        return over_one_space


class TestFakeIdentifiersContract(IdentifierFactoryContract):
    """Runs the canonical fake's factory through the shared suite."""

    @pytest.fixture
    def build(self) -> Callable[[], Any]:
        space = FakeIdentifierSpace()
        return lambda: FakeIdentifiers(space=space)

    @pytest.fixture
    def pinned(self) -> Callable[[str], Any]:
        return lambda nonce: FakeIdentifiers(space=FakeIdentifierSpace(nonce=nonce))

    @pytest.fixture
    def pinned_pair(self) -> Callable[[str], tuple[Any, Any]]:
        def over_one_space(nonce: str) -> tuple[Any, Any]:
            space = FakeIdentifierSpace(nonce=nonce)
            return FakeIdentifiers(space=space), FakeIdentifiers(space=space)

        return over_one_space


def test_the_default_space_is_shared_by_every_factory_in_this_process() -> None:
    """Two factories built with no arguments must not draw from independent sequences.

    The fixtures above pin a space per case so one case cannot make another's
    assertion true; this is the arm that checks the **default** — the one the
    composition root actually gets, and the one ADR-0192 §2 is written about.
    """
    first = ProcessIdentifiers()
    second = ProcessIdentifiers()

    drawn = [first(), second(), first(), second()]

    assert len(set(drawn)) == len(drawn)


def test_the_fakes_default_space_is_shared_too() -> None:
    first = FakeIdentifiers()
    second = FakeIdentifiers()

    drawn = [first(), second(), first(), second()]

    assert len(set(drawn)) == len(drawn)
