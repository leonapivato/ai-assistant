"""The context provider: assembles ``CurrentContext`` from internal sources.

``AssemblingContextProvider`` runs its sources concurrently and merges their
contributions into a single :class:`~ai_assistant.core.types.CurrentContext`
(ADR-0008). It is the only piece here that implements the cross-subsystem
``ContextProvider`` contract; the sources it composes are internal.

Assembly is advisory: a source that raises is skipped (its facet degrades to
absent) so a flaky optional source cannot take down the request pipeline. Only a
genuine wiring bug — two sources claiming the same field, or a missing *required*
field — surfaces as :class:`~ai_assistant.core.errors.ContextError`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from ai_assistant.core.errors import ContextError
from ai_assistant.core.types import CurrentContext

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.context.sources import ContextSource

_log = structlog.get_logger(__name__)


def _safe_name(source: ContextSource) -> str:
    """A source's name, or a placeholder if even that access raises."""
    try:
        return source.name
    except Exception:  # a pathological source whose name property fails
        return "<unknown>"


class AssemblingContextProvider:
    """Assembles ``CurrentContext`` by merging a set of internal context sources.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ContextProvider`.
    """

    def __init__(
        self, sources: Sequence[ContextSource], *, source_timeout: float | None = 5.0
    ) -> None:
        """Initialise the provider.

        Args:
            sources: The context sources to compose. Their field contributions
                must be disjoint; overlap is treated as a wiring bug.
            source_timeout: Per-source deadline in seconds; a source that exceeds
                it is skipped (its facet degrades to absent) so a hung source
                cannot stall assembly. ``None`` disables the timeout.
        """
        self._sources = tuple(sources)
        self._source_timeout = source_timeout

    async def assemble(self) -> CurrentContext:
        """Merge all sources' contributions into a single ``CurrentContext``.

        Raises:
            ContextError: If two sources contribute the same field, or the merged
                contributions cannot form a valid context (a required facet is
                missing — e.g. its source failed).
        """
        contributions = await asyncio.gather(
            *(self._safe_contribute(source) for source in self._sources)
        )
        merged: dict[str, object] = {}
        for source, contribution in zip(self._sources, contributions, strict=True):
            for key, value in contribution.items():
                if key in merged:
                    msg = (
                        f"context sources collided on field {key!r} "
                        f"(at source {_safe_name(source)!r})"
                    )
                    raise ContextError(msg)
                merged[key] = value
        try:
            return CurrentContext.model_validate(merged)
        except ValidationError as exc:
            msg = f"could not assemble a valid context: {exc}"
            raise ContextError(msg) from exc

    async def _safe_contribute(self, source: ContextSource) -> Mapping[str, object]:
        """Return a source's contribution, degrading any failure to an empty one.

        Covers a raise, a timeout (a hung source), and a fault raised while
        *consuming* the returned mapping (a lazy/faulting ``Mapping``) — the
        contribution is materialised here, under the guard, so nothing escapes to
        the merge loop.
        """
        try:
            async with asyncio.timeout(self._source_timeout):
                contribution = await source.contribute()
            return dict(contribution)  # materialise now, so a lazy failure degrades here
        except TimeoutError:
            _log.warning(
                "context source timed out; skipping",
                source=_safe_name(source),
                timeout=self._source_timeout,
            )
            return {}
        except Exception as exc:  # advisory: a failing source degrades, not aborts
            # Resolve the name defensively — the degradation path must not itself
            # raise if a misbehaving source's ``name`` also fails.
            _log.warning(
                "context source failed; skipping", source=_safe_name(source), error=str(exc)
            )
            return {}
