"""The grant operations: what may be granted, granting, revoking, and the record.

ADR-0102 §1 rules that the client surface for grants is exactly four methods on
:class:`~ai_assistant.core.protocols.AssistantEngine`, and §7 rules that they are
implemented **here**, in `orchestration`, "in one object that holds the
``SourceGrantStore``, the declared identities and configured locations of the
readers the composition root built, an id factory and a clock", with ``Engine``
delegating to it. This module is that object.

**`orchestration` is forced rather than chosen** (§7). The operations must be
``AssistantEngine`` methods to be addressable over the socket at all — ADR-0084 §3
makes the envelope's ``method`` member "the ``AssistantEngine`` method name" and
``wire/surface.py`` derives the legal set from the Protocol itself — and
``AssistantEngine`` is provided by `orchestration` and consumed by `interfaces`
(ADR-0085 §1). `service/` holds the listener, not the surface.

**Holding the identities by injection is what makes ADR-0097 §9's check
expressible at all.** §9's admission rule needs to know which reader identities
exist; ADR-0093 §2 forbids any subsystem importing the reader package and
``lint-imports`` holds it, so a `permissions/` store cannot answer, and ADR-0097
§10 excluded the rule from that store's conformance suite for exactly this reason.
Nothing here imports ``ai_assistant.readers`` either: the composition root reads
each identity off the :class:`~ai_assistant.core.protocols.Reader` object it built
and hands over the result, which is golden rule 1 and is what ``IngestionStage``
already does with the reader itself.

**This object is the only holder of a ``SourceGrantStore``** (ADR-0097 §3, §9;
ADR-0102 §7). Every driver — the ingestion stage, the calendar context source —
holds the narrow :class:`~ai_assistant.core.protocols.SourceGrants` instead, which
is the split that makes "only a user act creates a grant" a type rather than a
promise.

**Nothing a model steers can reach any of this** (ADR-0102 §8). No
``ToolDefinition`` binds these operations, no plan step may reach one, and no
model-authored value may become an argument to :meth:`GrantOperations.grant` or
:meth:`GrantOperations.revoke`. Two of ADR-0097 §9's four prohibitions are held
mechanically — ``tools/`` is a subsystem, subsystems never import
``orchestration`` and never import one another — but the clause is written anyway,
because a boundary that happens to hold is not the same as an obligation that is
stated, and what would be inverted is ADR-0005 §3's "the model proposes; a
deterministic policy disposes".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import UngrantableSourceError
from ai_assistant.core.types import (
    GrantableSource,
    GrantScope,
    Identifier,
    SourceGrant,
    encodable_text,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from datetime import datetime

    from ai_assistant.core.protocols import SourceGrantStore

_log = structlog.get_logger(__name__)

#: The validator :attr:`SourceGrant.source` applies, run here **before** a record is
#: constructed so a reader's inadmissible declared name is a typed refusal rather
#: than a ``ValidationError`` escaping the operation (ADR-0102 §4).
_IDENTIFIER: Final = TypeAdapter[str](Identifier)


class HeldSource:
    """One source the composition root built, as this layer sees it (ADR-0102 §7).

    A plain internal class rather than a `core` model, for
    :class:`~ai_assistant.orchestration.ingestion.IngestionReport`'s reason: it
    crosses no subsystem boundary. It is the composition root's *input* to this
    object, and what leaves this object is :class:`GrantableSource`, which is
    `core`'s.

    **Two fields and both raw.** ``identity`` is whatever
    :attr:`~ai_assistant.core.protocols.Reader.name` returned and ``location`` is
    whatever the deployment configured, neither validated on the way in: judging
    them is §4's and §6's job and it happens here, at the one place that can say
    what the consequence is. A composition root that validated them would either
    duplicate those rules or fail a build for a reader defect ADR-0102 §3 rules is
    "a defect in a reader, not a state a user can act on".
    """

    __slots__ = ("identity", "location")

    def __init__(self, identity: str, *, location: str | None = None) -> None:
        """Record one built reader's declared identity and configured location.

        Args:
            identity: What the reader's ``name`` property returned, verbatim.
            location: Where the deployment configured that source to read from, or
                ``None`` where it has no configured location at all. It is a plain
                ``str`` rather than a ``Path`` because §6's hazard is precisely a
                pathname with no UTF-8 encoding, which ``str(path)`` surfaces as a
                lone surrogate — so the string is what has to be judged.
        """
        self.identity = identity
        self.location = location


def _admissible_identity(identity: str) -> bool:
    """Whether a declared identity may be granted at all (ADR-0102 §4).

    Canonical form **and** :data:`~ai_assistant.core.types.Identifier` validity, and
    the second condition is worth its words because without it the failure is
    *undeclared* rather than absent: :attr:`SourceGrant.source` is ``Identifier``,
    so a reader declaring a blank or unencodable name would make ``grant`` raise a
    ``ValidationError`` from inside the operation — and ``wire/server.py`` converts
    an ``AssistantError`` into an error frame and lets anything else close the
    connection, so that would reach a client as a dropped socket. One check turns it
    into a typed refusal.

    ADR-0097 §9 makes canonical form a *necessary* condition for grantability, so
    adding a second necessary condition only shrinks the admissible set and leaves
    §9's sentence true as written.
    """
    if identity != identity.strip():
        return False
    try:
        _IDENTIFIER.validate_python(identity)
    except ValidationError:
        return False
    return True


def _encodable_location(location: str | None) -> tuple[bool, str | None]:
    """Judge a configured location under §6's two separated cases.

    Returns:
        Whether the source stays grantable, and the location to publish. **No
        configured location at all** makes ADR-0097 §9a's disclosure obligation
        vacuous — there is nothing to show — so the source is grantable with
        ``location`` absent. **A configured location that cannot be shown** is the
        hazard itself and fails closed: it is not degraded to ``None``, because
        that made §9a's two halves contradict each other in an earlier draft of
        ADR-0102 §6 — the source would be listed as grantable while no conforming
        client could ever grant it, and a client that ignored the disclosure clause
        would mint precisely the uninformed grant §9a exists to prevent.
    """
    if location is None:
        return True, None
    try:
        return True, encodable_text(location)
    except ValueError:
        return False, None


class GrantOperations:
    """The four grant operations, over one store and the identities the hub holds."""

    def __init__(
        self,
        *,
        store: SourceGrantStore,
        sources: Iterable[HeldSource] = (),
        id_factory: Callable[[], str],
        clock: Callable[[], datetime],
    ) -> None:
        """Wire the operations from the store, the held sources, an id and a clock.

        Args:
            store: The append-only record of what the user granted and withdrew. The
                **wide** seam, and this object is its only holder (ADR-0097 §3, §9):
                a driver handed it would be a scheduler job that can mint its own
                authorisation.
            sources: The declared identity and configured location of every reader
                the composition root built, in the order it built them. A
                **sequence** rather than a mapping, deliberately: §7 rules that
                "several readers declaring one identity carry one configured
                location" and that "a composition supplying two that differ is a
                configuration error and the engine does not build", and a mapping
                would deduplicate that conflict away before anything could see it.
                Entries are keyed by identity and deduplicated here, so several
                instances of one source contribute one entry — which is the state
                the tree is actually in, since ``build_engine`` builds two
                ``CalendarReader`` instances from one configured path (ADR-0096 §5).
            id_factory: Mints each record's id. Injected because a store neither
                mints ids nor reads a clock (ADR-0021 §3), and because a client
                supplying one would be minting into a write-once store (ADR-0102
                §5).
            clock: Reads each record's ``decided_at``. Injected for the same reason
                and one sharper: a client's clock would backdate a user act in a
                store whose entire value is that it says what actually happened.

        Raises:
            ValueError: If two held sources declare one identity at differing
                configured locations. **Refusing to build is the cheap half of a
                fix ADR-0102 §7 has no other move for**: the two instances the tree
                builds today agree by construction, but nothing said so, and two
                conforming readers named ``calendar`` at different paths would
                produce one entry showing one location while a grant on that
                identity authorised reads of both — §6's informed-consent property
                defeated by a wiring detail. Giving each instance its own grantable
                identity is the other candidate and is **foreclosed**: ADR-0093 §7
                makes an identity declared rather than configured, and ADR-0097 §9a
                places a named precondition on ADR-0093 §11's registry lane that "a
                second instance of one source type may not become grantable before
                that rule exists".
        """
        self._store = store
        self._id_factory = id_factory
        self._clock = clock
        self._sources: dict[str, HeldSource] = {}
        for held in sources:
            seen = self._sources.get(held.identity)
            if seen is None:
                self._sources[held.identity] = held
                continue
            if seen.location != held.location:
                msg = (
                    f"two readers declare the identity {held.identity!r} at differing "
                    f"configured locations; one identity carries one location, because a "
                    f"grant on it would otherwise authorise reads of both while the user "
                    f"was shown one (ADR-0102 §7). The paths are not named here "
                    f"(ADR-0097 §9a)"
                )
                raise ValueError(msg)

    # --- what may be granted -----------------------------------------------

    async def grantable_sources(self) -> tuple[GrantableSource, ...]:
        """Enumerate the sources a client may offer, each with its current state.

        In the order the composition root built them, deduplicated by identity. A
        source whose declared name is inadmissible (§4) or whose configured location
        cannot be encoded (§6) is **omitted**, and enumeration is not refused for
        it: the other sources still answer, and the operator log line below is what
        points at the defect. Both cases put the diagnosis where an operator looks,
        which is ADR-0102 §3's reason for refusing a ``grantable: bool`` field.

        Returns:
            One entry per grantable source, each carrying its declared identity, its
            configured location where it has one, and the grant covering it at the
            moment this ran.

        Raises:
            GrantError: If the grant store could not be read.
        """
        rows: list[GrantableSource] = []
        for held in self._sources.values():
            if not _admissible_identity(held.identity):
                # ``!r`` rather than the bare value, so a declared name holding a
                # lone surrogate still produces a log line that can be written down
                # (ADR-0004 §5's rule is about *Tier 1* data, and a declared
                # identity is Tier 2 by ADR-0093 §7's construction).
                _log.warning(
                    "grantable_sources.reader_identity_not_canonical",
                    reader=repr(held.identity),
                    reason="a reader's declared name must equal its own str.strip() "
                    "and validate as an Identifier (ADR-0102 §4)",
                )
                continue
            showable, location = _encodable_location(held.location)
            if not showable:
                # The path itself never reaches the log (ADR-0102 §4, §6): what an
                # operator needs is which reader to look at, and the remedy is an
                # act on their own filesystem.
                _log.warning(
                    "grantable_sources.location_has_no_encoding",
                    reader=held.identity,
                    reason="the configured location has no UTF-8 encoding, so it cannot "
                    "be shown to the user and the source is not grantable (ADR-0102 §6)",
                )
                continue
            rows.append(
                GrantableSource(
                    source=held.identity,
                    location=location,
                    live=await self._live(held.identity),
                )
            )
        return tuple(rows)

    # --- granting and withdrawing ------------------------------------------

    async def grant(self, source: str, *, scope: Sequence[GrantScope]) -> SourceGrant:
        """Admit ``source``, mint the record, and let the store arbitrate.

        ``source`` and ``scope`` have already been validated by the caller
        (``Engine``), which is where ADR-0085 §9's "locally, before any I/O" lives;
        this method owns **admission**, which is a different step and never a
        substitute for that one (§4).

        Args:
            source: The validated, unnormalised source name.
            scope: The validated, materialised uses.

        Returns:
            The recorded grant.

        Raises:
            UngrantableSourceError: If the value is not admissible. Nothing is
                constructed from it, and it reaches no store and no log.
            GrantError: If the store could not be read or written.
            InvalidGrantError: If the store refused the record — reachably, because
                the source already has a live grant. Propagated rather than retried
                or converted into a success (§5).
        """
        held = self._sources.get(source)
        if held is None:
            # **Names no value at all** (§4). ADR-0097 §9 forbids a refusal echoing
            # "no caller-supplied string beyond what the client already sent", "so a
            # mistyped value cannot reach the log (ADR-0004 §5)"; returning nothing
            # rather than the value to the sender is strictly stronger and costs a
            # client nothing it needs, since it still has what it sent and the
            # useful remedy is the enumeration.
            msg = (
                "no source by that name can be granted; call grantable_sources() and "
                "choose one of the identities it returns (ADR-0097 §9)"
            )
            raise UngrantableSourceError(msg)
        if not _admissible_identity(held.identity):
            # **Names that reader** (§4). The value is provably equal to a held
            # reader's declared name, which ADR-0093 §7 makes a declared constant
            # and therefore Tier 2 by construction — and it is reachable only where
            # that name is encodable and non-blank but not canonical, because a
            # caller's ``source`` had to survive ``NonBlankEncodableText`` to equal
            # it at all.
            msg = (
                f"the {held.identity!r} reader declares a name that is not in canonical "
                f"form, so it cannot be granted; the reader must declare a name equal to "
                f"its own str.strip() (ADR-0102 §4)"
            )
            raise UngrantableSourceError(msg)
        showable, _location = _encodable_location(held.location)
        if not showable:
            msg = (
                f"the {held.identity!r} source has a configured location with no UTF-8 "
                f"encoding, so it cannot be shown to you and may not be granted unseen; "
                f"the remedy is on the filesystem (ADR-0102 §6)"
            )
            raise UngrantableSourceError(msg)

        # **No liveness pre-check** (§5). ADR-0021 §4's observation that "an
        # ``await`` between a check and a write is an interleaving point" applies
        # here as much as to the read gate: these run on the hub's one event loop
        # and two clients can be connected at once. ADR-0097 §10 makes ``record``
        # atomic over the duplicate check, the live-grant check, the revocation
        # invariants and the append, so a lost race is a typed ``InvalidGrantError``
        # and never a second live grant. A pre-check would narrow the window without
        # closing it, while inviting a reader to believe it had.
        record = SourceGrant(
            id=self._id_factory(),
            source=held.identity,
            scope=tuple(scope),
            decided_at=self._clock(),
        )
        await self._store.record(record)
        return record

    async def revoke(self, source: str) -> SourceGrant | None:
        """Withdraw the live grant on ``source``, or report that there was none.

        **No admission check at all** (§4). A revocation is refused for no property
        of the source's name, and in particular not because no reader currently
        declares it: ADR-0097 §9 records that "a grant whose reader later disappears
        is not a defect", so an operator who unsets a path leaves a stored grant
        naming a source nothing drives — and an admission check here would make that
        grant **permanently unrevokable**, which is precisely the failure ADR-0097
        §4 refused when it declined an ordering invariant on ``decided_at``.

        Nothing leaks through the opening this leaves: a value no reader declares
        finds no live grant, constructs nothing and records nothing, so the
        free-text route into the store stays closed by there being nothing for the
        value to reach.

        Args:
            source: The validated, unnormalised source name.

        Returns:
            The revoking record, or ``None`` where no live grant covered the source.

        Raises:
            GrantError: If the store could not be read or written.
            InvalidGrantError: If the store refused the revoking record — reachably,
                where it lost a race to another revocation. A refusal rather than a
                silent success is the right answer (§5).
        """
        live = await self._live(source)
        if live is None:
            return None
        # **Transcribed verbatim** — the source and scope of the grant being
        # withdrawn, so the record says what was withdrawn without a join, and the
        # store verifies the transcription (ADR-0097 §4).
        record = SourceGrant(
            id=self._id_factory(),
            source=live.source,
            scope=live.scope,
            decided_at=self._clock(),
            revokes=live.id,
        )
        await self._store.record(record)
        return record

    # --- the record ---------------------------------------------------------

    async def recent_grants(self, *, limit: int) -> tuple[SourceGrant, ...]:
        """Return the most recent records, newest first (ADR-0097 §6, ADR-0102 §11).

        Grants and revocations alike, because revocation retires nothing and a
        source that has been revoked keeps its complete history on file. This is the
        surface that discharges ADR-0097 §4's audit property: the record *is* the
        audit record, so nothing is written to an ``AuditTrail`` for a grant and no
        ``PermissionDecision`` is synthesised for one.

        Args:
            limit: How many records to return. Already validated strictly positive
                by the caller (ADR-0102 §10).

        Returns:
            The page, newest first, ties broken by ``id`` ascending.

        Raises:
            GrantError: If the store could not be read.
        """
        return tuple(await self._store.recent(limit=limit))

    # --- the sweep the liveness answer rests on -----------------------------

    async def _live(self, source: str) -> SourceGrant | None:
        """The live grant covering ``source`` for any use, or ``None`` (ADR-0102 §5).

        **Written over the enum rather than over its members**, which is what makes
        it stay total as ``GrantScope`` grows. The sweep is stated in ADR-0102 §5
        rather than left to be inferred "because the wrong version passes every test
        that exists": ``SourceGrants.live`` takes a ``use``, so an implementation
        querying only ``FACET`` would resolve a ``FACET``-scoped grant and silently
        fail to find an ``INGEST``-only one — leaving that grant unrevokable while
        :meth:`revoke` reported success by returning ``None``.

        Taking the first answer is total because ADR-0097 §2 makes a grant's scope
        non-empty, and unambiguous because §4 allows at most one live grant per
        source at any instant.
        """
        for use in GrantScope:
            found = await self._store.live(source=source, use=use)
            if found is not None:
                return found
        return None


__all__ = [
    "GrantOperations",
    "HeldSource",
]
