"""A canonical :class:`~ai_assistant.core.protocols.PermissionLineStore` fake (ADR-0367 §3:6).

The shared test double for the lines people make, so the lanes that check a call against
lines (ADR-0367 §4) and those that list, make and remove them for the owner (ADR-0376 §4)
can exercise standing lines, removed ones and a store that fails, without a file. It keeps
everything in memory and follows the contract's every rule, so a consumer's test sees what
the store would do.

**It starts empty**, as the store does: no line is seeded. **It mints each line's
identifier once**: an identifier ``new_id`` mints that a held line already carries, a
removed one's included, is a store fault, raised before anything changes.

**What only a test can ask of it.** :meth:`FakePermissionLineStore.fail_next` makes the
next member called raise :class:`~ai_assistant.core.errors.PermissionLineStoreError`
before it reads or writes anything, as a store fault would.

Every member runs to its end without awaiting, so on one event loop each is one
indivisible step, which is the exclusion the contract asks of it.

Not ADR-0097's source grants, whose fake is :mod:`ai_assistant.testing.grants`
(ADR-0367 §14).
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from typing import TYPE_CHECKING, final

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PermissionLineStoreError
from ai_assistant.core.types import (
    LineMaking,
    LineMakingKind,
    LineParts,
    LineRemoval,
    LineRemovalKind,
    PermissionLine,
    describe_untrusted,
    encodable_text,
)

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["FakePermissionLineStore"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _checked(value: object, *, name: str) -> str:
    """A non-blank ``str`` with a UTF-8 encoding, or a ``ValueError`` before anything is read."""
    if not isinstance(value, str) or not value.strip():
        msg = f"{name} must be a non-blank str, got {describe_untrusted(value)}"
        raise ValueError(msg)
    try:
        return encodable_text(value)
    except ValueError as exc:
        msg = f"{name} must be text with a UTF-8 encoding"
        raise ValueError(msg) from exc


def _parts(value: object) -> LineParts:
    """``value`` as ``LineParts`` whose every field passes validation, or a ``ValueError``.

    An instance is not proof of its own validity: ``model_copy(update=…)`` and
    ``model_construct`` skip validation, so the instance's contents are validated again.
    """
    if not isinstance(value, LineParts):
        msg = f"parts must be a LineParts, got {describe_untrusted(value)}"
        raise ValueError(msg)
    try:
        return LineParts.model_validate(value.model_dump())
    except ValidationError as exc:
        msg = "parts is not a valid LineParts"
        raise ValueError(msg) from exc


@final
class FakePermissionLineStore:
    """An in-memory line store, empty when built (ADR-0367 §3:5, §3:6; ADR-0376 §4:8)."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] = _utcnow,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        """Build the store, holding no line.

        Args:
            now: The clock every instant the store records is read from.
            new_id: Mints a line's identifier; ``line:1``, ``line:2`` and so on where
                ``None``. An identifier it mints that a held line carries is refused as a
                store fault.
        """
        # ADR-0026 §2: every reading aware and converted to UTC, checked where it is read.
        self._clock = checked_clock(now, owner="FakePermissionLineStore")
        numbers = count(1)
        self._new_id = new_id or (lambda: f"line:{next(numbers)}")
        self._lines: dict[str, PermissionLine] = {}
        self._fail = False

    def fail_next(self) -> None:
        """Make the next member called raise ``PermissionLineStoreError``, touching nothing."""
        self._fail = True

    def _fault(self) -> None:
        if self._fail:
            self._fail = False
            msg = "the fake line store was told to fail"
            raise PermissionLineStoreError(msg)

    def _now(self) -> datetime:
        """One reading of the clock, taken before the write it dates changes anything.

        Raises:
            PermissionLineStoreError: If the reading is not an aware instant (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = f"the line store cannot record its clock's reading: {exc}"
            raise PermissionLineStoreError(msg) from exc

    def _mint(self) -> str:
        """A new line's identifier, never one a held line carries, removed ones included.

        Raises:
            PermissionLineStoreError: If the identifier minted is not one, or one a held
                line already carries.
        """
        try:
            minted = _checked(self._new_id(), name="a minted identifier")
        except ValueError as exc:
            msg = "the line store minted an identifier that is not one"
            raise PermissionLineStoreError(msg) from exc
        if minted in self._lines:
            msg = "the line store minted an identifier a line already carries"
            raise PermissionLineStoreError(msg)
        return minted

    async def standing(self) -> tuple[PermissionLine, ...]:
        """Every standing line, in the order made.

        Raises:
            PermissionLineStoreError: If told to fail.
        """
        self._fault()
        return tuple(one for one in self._lines.values() if one.standing)

    async def line(self, line_id: str) -> PermissionLine | None:
        """Read one line by its identifier, standing or removed.

        Raises:
            ValueError: If ``line_id`` is not a non-blank ``str``.
            PermissionLineStoreError: If told to fail.
        """
        held = _checked(line_id, name="line_id")
        self._fault()
        return self._lines.get(held)

    async def record_making(self, parts: LineParts, *, by: str) -> LineMaking:
        """Record a line with ``parts`` by ``by``'s act, or find the standing one it repeats.

        Raises:
            ValueError: If an argument is malformed.
            PermissionLineStoreError: If told to fail, the clock's reading is not an aware
                instant, or an identifier is minted twice; nothing is changed.
        """
        made = _parts(parts)
        maker = _checked(by, name="by")
        self._fault()
        for one in self._lines.values():
            if one.standing and one.parts == made:
                return LineMaking(kind=LineMakingKind.UNCHANGED, line=one)
        # Minted and read before anything held changes, so a fault changes nothing.
        line_id = self._mint()
        line = PermissionLine(id=line_id, **made.model_dump(), made_by=maker, made_at=self._now())
        self._lines[line_id] = line
        return LineMaking(kind=LineMakingKind.MADE, line=line)

    async def record_removal(self, line_id: str, *, by: str) -> LineRemoval:
        """Record the removal of a standing line by ``by``'s act, keeping it.

        Raises:
            ValueError: If an argument is malformed.
            PermissionLineStoreError: If told to fail, or the clock's reading is not an
                aware instant; nothing is changed.
        """
        held = _checked(line_id, name="line_id")
        remover = _checked(by, name="by")
        self._fault()
        line = self._lines.get(held)
        if line is None or not line.standing:
            return LineRemoval(kind=LineRemovalKind.NOT_STANDING)
        removed = PermissionLine.model_validate(
            {**line.model_dump(), "removed_by": remover, "removed_at": self._now()}
        )
        self._lines[held] = removed
        return LineRemoval(kind=LineRemovalKind.REMOVED, line=removed)
