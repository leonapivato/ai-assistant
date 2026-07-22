"""Ingesting proposed memories: conflict detection, policy, and application.

``MemoryIngestor`` closes the propose/dispose/persist loop. Given a
:class:`~ai_assistant.core.types.MemoryUpdateProposal` (the "propose" half), it:

1. detects conflicting existing memories (same kind, highly similar content),
2. asks the injected :class:`~ai_assistant.core.protocols.MemoryPolicy` to rule
   on the proposal given those conflicts (the "dispose" half), and
3. applies the ruling to the injected
   :class:`~ai_assistant.core.protocols.MemoryStore` (the "persist" half).

It depends only on the store and policy contracts, so it is agnostic to which
concrete store or policy is wired in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import TYPE_CHECKING

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryKind,
    Provenance,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore
    from ai_assistant.core.types import MemoryDecision, MemoryRecord, MemoryUpdateProposal

_DEFAULT_CONFLICT_THRESHOLD = 0.75
_DEFAULT_CONFLICT_LIMIT = 5


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check_tuning(*, conflict_threshold: float, conflict_limit: int) -> None:
    """Reject conflict tuning that would disable a stage while looking healthy.

    Relocated from ``LearningLoop`` with the values themselves (ADR-0028 §4a),
    so ADR-0022 §4a's guarantee is moved rather than retired: the same values
    are refused at the same moment, by the object that reads them. Each is a
    *silent* misconfiguration, which is why it is refused at construction rather
    than left to surface as behaviour. ``conflict_limit=0`` hands the policy no
    conflicts, so every proposal is ruled on as though nothing contradicted it,
    and a duplicate is accepted while the caller reports a healthy write. A
    ``NaN`` threshold compares ``False`` against every score and does the same.

    Raises:
        TypeError: If ``conflict_limit`` is not an integer, or
            ``conflict_threshold`` is a ``bool``.
        ValueError: If ``conflict_limit`` is below 1, or ``conflict_threshold``
            is not a finite value in ``[0, 1]`` — the range a
            ``MemoryRecord.score`` occupies.
    """
    # `isinstance` rather than a bare `< 1`, which `1.5` and `inf` both survive
    # — and a non-integral limit reaches `MemoryStore.search`, where a store
    # slicing by it raises `TypeError` far from the mistake. `bool` is excluded
    # because it is an `int` subclass and a flag is not a count.
    if isinstance(conflict_limit, bool) or not isinstance(conflict_limit, int):
        msg = f"conflict_limit must be an integer, got {conflict_limit!r}"
        raise TypeError(msg)
    if conflict_limit < 1:
        msg = f"conflict_limit must be at least 1, got {conflict_limit}"
        raise ValueError(msg)
    # Checked before the range test, which a `bool` silently survives: `bool` is
    # an `int` subclass, so `isfinite(True)` holds and `0.0 <= True <= 1.0` is
    # true — a flag would be read as the threshold 1.0, restricting conflicts to
    # perfect-score matches. Rejected for the same reason the limit rejects one.
    if isinstance(conflict_threshold, bool):
        msg = f"conflict_threshold must be a real number, got {conflict_threshold!r}"
        raise TypeError(msg)
    if not isfinite(conflict_threshold) or not 0.0 <= conflict_threshold <= 1.0:
        msg = f"conflict_threshold must be a finite value in [0, 1], got {conflict_threshold!r}"
        raise ValueError(msg)


#: What a value expressed in UTC must report as its offset.
_NO_OFFSET = timedelta(0)


def _canonical_utc(value: object) -> datetime | None:
    """Rebuild ``value`` as a plain ``datetime`` in UTC, or ``None`` if it is not one.

    The clock-side twin of ``core``'s own check, and separate from it because
    that one is private to ``core.types`` and reached only through a pydantic
    validator this write never touches. ``datetime.utcoffset()`` is overridable
    on a *subclass*, so a reading can carry ``tzinfo is UTC``, answer zero while
    it is checked, and answer ``+02:00`` once it is stored. Rebuilding as a base
    ``datetime`` makes the value's UTC-ness a fact about it rather than a claim
    it keeps making, and only an *exact* ``datetime`` is canonicalised: a
    subclass can execute code between any two checks — flipping its offset while
    the components are read — so no ordering of checks on one is sound, whereas
    the C implementation cannot be intercepted. The clock seams collapse into
    one guard when ADR-0026 lands (#169).
    """
    if type(value) is not datetime or value.tzinfo is not UTC:
        return None
    if value.utcoffset() != _NO_OFFSET:
        return None
    return datetime(
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond,
        tzinfo=UTC,
    )


def _describe(value: object) -> str:
    """``repr`` of an untrusted value, for an error message, never raising.

    ``datetime.__repr__`` embeds ``repr(tzinfo)``, so a clock returning a value
    whose ``tzinfo`` raises from ``__repr__`` would raise from inside the message
    that reports it — replacing this seam's ``MemoryStoreError`` with whatever
    that ``__repr__`` threw. The diagnostic must not destroy the diagnosis.
    """
    try:
        return repr(value)
    except Exception:  # the value cannot describe itself; say so and move on
        return "<a value whose repr() failed>"


def _merge(target: MemoryRecord, incoming: MemoryRecord) -> MemoryRecord:
    """Fold ``incoming`` into ``target``, keeping the target's id.

    Newer content wins; evidence is unioned and confidence taken as the maximum,
    so a merge strengthens rather than weakens what is known.
    """
    provenance = Provenance(
        source=incoming.provenance.source,
        confidence=max(target.provenance.confidence, incoming.provenance.confidence),
        evidence=list(dict.fromkeys([*target.provenance.evidence, *incoming.provenance.evidence])),
        last_updated=incoming.provenance.last_updated,
    )
    return incoming.model_copy(update={"id": target.id, "provenance": provenance})


class MemoryIngestor:
    """Runs a proposed memory through conflict detection, policy, and storage.

    Structurally satisfies :class:`~ai_assistant.core.protocols.MemoryWriter`
    (ADR-0028 §2), which is how `orchestration` reaches this write path without
    importing it.
    """

    def __init__(
        self,
        *,
        store: MemoryStore,
        policy: MemoryPolicy,
        conflict_threshold: float = _DEFAULT_CONFLICT_THRESHOLD,
        conflict_limit: int = _DEFAULT_CONFLICT_LIMIT,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Initialise the ingestor.

        Args:
            store: Where accepted memories are persisted and conflicts sought.
            policy: The deterministic policy that rules on each proposal.
            conflict_threshold: Minimum retrieval score for an existing record to
                count as conflicting with the proposal.
            conflict_limit: Maximum number of conflict candidates to consider.
            now: Clock used to stamp expiry on temporary stores; injectable for
                deterministic tests.

        Raises:
            TypeError: If ``conflict_limit`` is not an integer, or
                ``conflict_threshold`` is a ``bool`` (see :func:`_check_tuning`).
            ValueError: If ``conflict_limit`` is below 1, or
                ``conflict_threshold`` is not a finite value in ``[0, 1]`` (see
                :func:`_check_tuning`).
        """
        _check_tuning(conflict_threshold=conflict_threshold, conflict_limit=conflict_limit)
        self._store = store
        self._policy = policy
        self._conflict_threshold = conflict_threshold
        self._conflict_limit = conflict_limit
        self._now = now

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Detect conflicts, apply the policy, and persist the outcome."""
        conflicts = await self._detect_conflicts(proposal.proposed)
        proposal = proposal.model_copy(update={"conflicts": [record.id for record in conflicts]})
        decision = await self._policy.decide(proposal, conflicts=conflicts)
        record_id = await self._apply(decision, proposal.proposed, conflicts)
        return MemoryIngestResult(decision=decision, record_id=record_id)

    async def _detect_conflicts(self, record: MemoryRecord) -> list[MemoryRecord]:
        # Over-fetch by one, because the store applies the limit before this
        # method can drop the proposal's own record: a re-proposal would
        # otherwise spend a slot on a record that is then discarded, hiding a
        # genuine conflict ranked just below it. One extra suffices — ids are
        # unique in a store, so at most one match can be the proposal itself.
        matches = await self._store.search(
            record.content,
            limit=self._conflict_limit + 1,
            kinds=[MemoryKind(record.kind)],
        )
        conflicts = [
            match
            for match in matches
            if match.id != record.id and (match.score or 0.0) >= self._conflict_threshold
        ]
        return conflicts[: self._conflict_limit]

    async def _apply(
        self,
        decision: MemoryDecision,
        proposed: MemoryRecord,
        conflicts: list[MemoryRecord],
    ) -> str | None:
        match decision.kind:
            case MemoryDecisionKind.ACCEPT:
                return await self._store.add(proposed)
            case MemoryDecisionKind.STORE_TEMPORARY:
                expires_at = self._expiry(decision.ttl)
                return await self._store.add(proposed.model_copy(update={"expires_at": expires_at}))
            case MemoryDecisionKind.MERGE:
                target = next((c for c in conflicts if c.id == decision.merge_into), None)
                if target is None:
                    # A MERGE naming an absent target must fail loudly: silently
                    # storing the proposal as new would create the duplicate the
                    # merge was meant to prevent, while reporting success.
                    msg = f"MERGE target {decision.merge_into!r} is not among the conflicts"
                    raise MemoryStoreError(msg)
                return await self._store.add(_merge(target, proposed))
            case _:  # REJECT, ASK_USER — nothing is written.
                return None

    def _now_utc(self) -> datetime:
        """The injected clock's reading, as UTC — attributed if naive, else converted.

        Load-bearing for :meth:`_expiry`, and the guard ``LearningLoop._now_utc``
        already carries on the identical write. ``model_copy(update=...)`` does
        **not** re-run validators, so an ``expires_at`` installed that way
        reaches the store exactly as this method left it — and since ADR-0023
        makes ``MemoryBase.expires_at`` *reject* a naive value rather than assume
        UTC, there is no longer a validator downstream that would have caught it.
        A naive deadline then raises ``TypeError`` on the first comparison deep
        inside the store, or fails to decode after a round trip through the
        persistent one.

        **Converting, not merely attributing.** ADR-0023 §2 makes UTC storage
        mandatory and uniform, and the qualifier it attaches is precisely this
        one: the invariant holds at the validation boundary, so "a write that
        reaches past it must re-validate". This write does reach past it, so the
        conversion has to happen here or nowhere — a ``+02:00`` deadline would
        otherwise be persisted verbatim, and
        ``SqliteMemoryStore._add_sync``'s expiry index, computed from it, is one
        of the comparisons §2 exists to keep coherent.

        **The indeterminate offset is checked explicitly, not left to
        ``astimezone``.** ADR-0023 §5 spells "aware" as ``utcoffset()``
        returning a value (issue #36), and a ``tzinfo`` that answers ``None``
        satisfies ``tzinfo is not None`` while satisfying nothing else:
        ``astimezone(UTC)`` then treats the value as *host-local* and returns a
        confidently wrong instant, which is precisely the fabrication ADR-0023
        §3 exists to stop. It becomes ``MemoryStoreError`` here — as does a
        ``tzinfo`` that raises — rather than a raw ``TypeError`` from
        ``.timestamp()`` several layers down. Same boundary translation
        :meth:`_expiry` already performs for ``OverflowError``.

        **What it deliberately does not guard is the reading's type.** A clock
        returning something that is not a ``datetime`` at all — ``now=lambda:
        None`` — still raises ``AttributeError`` here. ``mypy --strict`` reports
        an ``isinstance`` check on it as unreachable, because reaching it means
        violating the declared ``Callable[[], datetime]``, so guarding would take
        a ``type: ignore[unreachable]`` for an input the gate already refuses.
        Making the guard total over the reading is ADR-0026 §2's decision, still
        `Proposed`, and taking it at one of ten seams would recreate exactly the
        per-site divergence that ADR exists to end. Tracked in #169.

        This is the shim ADR-0023 §6 requires at a clock-fed field's producer
        until ADR-0026's guard lands; it is deliberately not that guard.

        The converted result is re-checked, exactly as ``core``'s ``UtcInstant``
        does and for the same reason: ``astimezone`` is overridable, this value
        is installed through ``model_copy`` and so never meets that validator,
        and a naive expiry that got past here would surface as a ``TypeError``
        at the first comparison in a store.

        Raises:
            MemoryStoreError: If the clock's reading has no usable UTC form.
        """
        now = self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        unusable = (
            f"the injected clock returned an instant with no UTC representation: {_describe(now)}"
        )
        try:
            offset = now.utcoffset()
        except Exception as exc:  # a tzinfo that raises rather than answering
            raise MemoryStoreError(unusable) from exc
        if offset is None:
            raise MemoryStoreError(unusable)
        try:
            # `object` for the same reason `core`'s `_utc_instant` does it:
            # `astimezone` is annotated to return a datetime and need not.
            converted: object = now.astimezone(UTC)
            canonical = _canonical_utc(converted)
        except Exception as exc:  # incl. OverflowError near datetime.min/max
            raise MemoryStoreError(unusable) from exc
        if canonical is None:
            msg = f"the injected clock did not convert to UTC: {_describe(converted)}"
            raise MemoryStoreError(msg)
        return canonical

    def _expiry(self, ttl: timedelta | None) -> datetime | None:
        """Stamp an expiry ``ttl`` from now, failing loudly if it is unrepresentable."""
        if ttl is None:
            return None
        try:
            return self._now_utc() + ttl
        except OverflowError as exc:
            msg = f"temporary-store ttl {ttl!r} overflows the representable date range"
            raise MemoryStoreError(msg) from exc
