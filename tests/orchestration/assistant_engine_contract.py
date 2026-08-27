"""Shared conformance suite for the AssistantEngine Protocol.

Every ``AssistantEngine`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`AssistantEngineContract` and overrides its four fixtures.

**This suite is why the Protocol is worth having.** ADR-0084 §4 promotes the
engine surface so that a client over a transport and the in-process engine are
substitutable, and it names six clauses that *no type expresses* — ADR-0085's
Consequences list them. Every one of them is a way two implementations could
answer the same call differently while both looking correct, so each is asserted
here rather than left to each implementation's own tests:

1. **The page-size default is normative** (§3a). A default in a ``Protocol``
   signature binds nobody; a client defaulting to 100 against an engine defaulting
   to 50 returns a different page for one call.
2. **Every identifier argument is validated *and normalised* before any I/O**
   (§3c). The normalisation is the load-bearing half: without it ``belief(" x ")``
   answers ``None`` in-process and finds the record over a wire client that
   deserialises through ``Identifier``.
3. **The two filters are materialised before the first ``await``** (§3d).
4. **A malformed page argument and a blank identifier are refused locally** (§9),
   so neither implementation is silently more permissive.
5. **The size limit is enforced in both directions** (§8c) — an oversized result
   coming back is refused exactly as an oversized argument going in.
6. **An error type's structured state round-trips through its own constructor**
   (§10a), with ``details_elided`` marking a reconstruction that lost it.

Two shapes the *types* enforce are asserted too, because a suite that only tested
prose would leave a reader unsure whether the guarantee exists: the listing
returns :class:`~ai_assistant.core.types.BeliefSummary` and therefore cannot ship
a citation's content (§4a), and every enumeration returns a tuple (§3b).

**The grant surface adds a second list of behavioural clauses** (ADR-0102 §12
item 2): "the ``AssistantEngine`` conformance suite gains a clause per ruling above
that a store cannot exhibit, which is the whole of §4, §5 and §10's local-refusal
clause". They live here for the same reason the six above do — each is a way two
implementations could answer one call differently while both looking correct — and
two of them are worth naming as the ones nothing else would catch. A ``source``
differing from a held reader's name only by whitespace must be **refused rather
than matched**, which the wire implementation alone could have got wrong, since it
validates each argument against the Protocol's own annotation before dispatch. And
a grant revoked by a record timestamped *earlier* than itself must read as
withdrawn, which an implementation deriving liveness from a time-ordered page gets
wrong on the one deployment where a clock moved.

**Lifecycle is deliberately not asserted.** ``start`` and ``aclose`` are not on
the Protocol (ADR-0084 §5, ADR-0083 §8) — a client that could call ``aclose()``
could shut down the hub from a spoke — so an implementation without a lifecycle
conforms, and this suite must never reach for one.

**``RuntimeError`` on a shutting-down engine is likewise not required** (ADR-0085
§1): it is a property of one object's lifecycle rather than of the contract, and a
client never observes it.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import TYPE_CHECKING, Final

import pytest
from pydantic import SecretStr

from ai_assistant.core import errors as error_module
from ai_assistant.core import protocols as protocols_module
from ai_assistant.core.errors import (
    AssistantError,
    AuditError,
    IncompleteProvisioningError,
    InvalidGrantError,
    OversizedValueError,
    PlanningError,
    ReadTrailError,
    UngrantableSourceError,
    UnknownConnectionError,
    UnknownContinuationError,
    UnknownConversationError,
    UnresolvedEvidenceError,
    UnusableIdentityError,
)
from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    ACCOUNT_IDENTITY_MAX_BYTES,
    DEFAULT_PAGE_SIZE,
    SECRET_VALUE_MAX_BYTES,
    ActionRequest,
    AnswerKind,
    BeliefBand,
    BeliefSummary,
    BoundAccount,
    ContinuationToken,
    CostBasis,
    Disposition,
    EgressBinding,
    FeedbackEvent,
    FeedbackKind,
    GrantScope,
    Idempotency,
    MemoryKind,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ProvisioningState,
    RecordedInvocation,
    ReplyChunk,
    Reversibility,
    RiskLevel,
    RouteOutcome,
    SourceReadRecord,
    SpendPeriod,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    TurnOutcome,
    secret_value,
)
from ai_assistant.testing import (
    Disclosure,
    FakeAuditTrail,
    FakeSourceReadTrail,
    SecretMethod,
    source_read_record,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable, Sequence

    from ai_assistant.core.types import SecretValue
    from ai_assistant.testing import FakeConnectionProvisioner
    from ai_assistant.testing.permissions import MintsIdentifiers

#: A credential over :data:`_TINY_LIMIT` and comfortably under
#: :data:`~ai_assistant.core.types.SECRET_VALUE_MAX_BYTES`, so ``secret_value``
#: accepts it and the **only** thing that can refuse the call is the frame bound.
#: A value at or above the secret bound would be refused a step earlier by a
#: different clause, which would leave ADR-0151 §11 untested by a case that passed.
_OVERSIZED_CREDENTIAL_BYTES = 712


#: A generous per-turn budget: nothing in this suite is about a deadline.
_PATIENT = timedelta(seconds=30)

#: A limit large enough that an ordinary ``learn`` call — argument *and* result —
#: fits inside it, and small enough that a handful of stored beliefs does not.
#:
#: **Both halves matter.** Too small and every call is refused on its arguments,
#: which is how a suite ends up "testing" result enforcement with a case that never
#: reaches a result: with a 64-byte limit a ``learn`` whose event carries any
#: content at all is refused before the write, so an implementation that had removed
#: its result check entirely would still pass. At 512 the argument object of every
#: setup call is comfortably inside the bound and only the *page* crosses it.
_TINY_LIMIT = 512

#: The one grantable identity every ``granting_engine`` fixture holds. A declared
#: constant, which is what a reader's ``name`` is (ADR-0093 §7) and therefore what
#: the admissible set is made of.
_SOURCE = "calendar"

#: A held source whose configured location has no UTF-8 encoding. Linux pathnames
#: are bytes and Python surfaces an undecodable one through ``surrogateescape``, so
#: ``str(path)`` really can hold a lone surrogate — which is why ADR-0102 §6 calls
#: its encoding clauses "a real case rather than a defensive one".
_UNWRITABLE_SOURCE = "notes"
_UNWRITABLE_LOCATION = "/srv/\udce9notes.md"

#: A held source whose *declared identity* is not in canonical form (ADR-0102 §4).
#: A caller can name it exactly — ``NonBlankEncodableText`` does not strip — which
#: is what makes the refusal reachable rather than theoretical.
_NOT_CANONICAL = "  mail  "

#: A source with a **live grant and no held reader** — the state ADR-0139 §1 is
#: about, and the whole reason ``standing_grants`` exists. Reached by an operator
#: unsetting a configured path, or by a reader leaving the tree, and it is not a
#: defect: ADR-0097 §9 records that "a grant whose reader later disappears is not a
#: defect", and ADR-0102 §4 keeps such a grant revocable on purpose. What was
#: missing was any operation that would *name* it.
_UNHELD_SOURCE = "journal"

#: How many live grants the oversized fixture holds. Six, because the canonical
#: encoding of one ``SourceGrant`` runs about 120 bytes and :data:`_TINY_LIMIT` is
#: 512 — so the set is comfortably over the bound while any single record is
#: comfortably under it, which is what keeps the case about the *set* being refused
#: rather than about a record nothing could ever return.
_OVERFULL_GRANTS = 6


#: The account identity every connection case supplies. Deliberately **not** in
#: canonical form: ADR-0151 §5 forbids stripping, case-folding or Unicode-normalising
#: a caller-supplied identity anywhere on the path, so an identity that would survive
#: normalisation unchanged could not tell a conforming implementation from one that
#: normalises. The leading and trailing spaces are the test.
_IDENTITY = "  Ada@Example.COM  "

#: A second identity differing from :data:`_IDENTITY` only by case, for the same
#: clause read the other way.
_IDENTITY_OTHER_CASE = "  ada@example.com  "

#: A reference no store holds. Well-formed as an ``Identifier`` — the refusal under
#: test is "this store does not hold it" and not "this is not a reference".
_UNHELD_REFERENCE = "0f9c2e13-6b4a-4d2f-9f11-5c8a7e3b1d40"


def _credential(plaintext: str = "hunter2-correct-horse") -> SecretValue:
    """One credential, built the only supported way (ADR-0125 §3).

    Through :func:`secret_value` rather than ``SecretStr`` directly, because
    :data:`~ai_assistant.core.types.SecretValue` is an ``Annotated`` alias whose
    validator runs only when a model carrying the field is validated — so a
    directly-constructed holder satisfies every static check while the validator
    never runs, which is precisely the hazard §3 names.
    """
    return secret_value(SecretStr(plaintext))


async def _drain(stream: AsyncIterator[ReplyChunk | TurnOutcome]) -> list[ReplyChunk | TurnOutcome]:
    """Read one streamed turn to its end, closing it however it ends (ADR-0173 §4)."""
    async with closing_stream(stream) as values:
        return [value async for value in values]


async def _outcome_of(stream: AsyncIterator[ReplyChunk | TurnOutcome]) -> TurnOutcome:
    """The terminal outcome of one streamed turn, which §4 makes always the last."""
    terminal = (await _drain(stream))[-1]
    assert isinstance(terminal, TurnOutcome)
    return terminal


def _feedback(content: str) -> FeedbackEvent:
    """One piece of feedback, as an adapter hands it over."""
    return FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        memory_kind=MemoryKind.SEMANTIC,
        content=content,
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )


@dataclass(frozen=True, slots=True)
class ConnectionSubject:
    """An engine on the connection surface, and the provisioner standing behind it.

    Attributes:
        engine: The subject under test, at its ordinary contract limit.
        provisioner: The canonical fake the engine ultimately delegates to. Read by
            a case as a **negative control** — ``entries`` says what was written,
            and an act that must write nothing is checked against it — and driven by
            one for the single state the surface cannot produce: a live record left
            ``PENDING`` by a keyring that failed mid-act.
    """

    engine: AssistantEngine
    provisioner: FakeConnectionProvisioner


#: When the seeded trail's first ruling was made. Fixed, so an ordering assertion
#: is about the values under test rather than about how fast the suite runs.
_RULED_AT: Final = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)

#: The rows every seeded trail holds, as ``(id, seconds after`` :data:`_RULED_AT`
#: ``)``, **in the order they are recorded**. Two properties are deliberate and each
#: is a case below (ADR-0186 §11). The recording order is not the ``decided_at``
#: order, so an implementation relaying insertion order is caught; and ``d-3`` and
#: ``d-4`` share an instant **and are recorded in the wrong order for it**, so the
#: ``id`` tie-break is *exercised* rather than assumed. Both halves are needed: rows
#: at distinct instants leave an implementation with no tie-break at all passing,
#: and a tie whose recording order already agrees with the tie-break leaves one
#: passing that merely relies on its sort being stable.
_SEEDED_DECISIONS: Final[tuple[tuple[str, int], ...]] = (
    ("d-1", 2),
    ("d-2", 0),
    ("d-4", 1),
    ("d-3", 1),
)

#: ADR-0186 §2's total order over :data:`_SEEDED_DECISIONS`: ``decided_at``
#: descending, ties broken by ``id`` ascending. Written out rather than computed, so
#: the expectation is something a reader checks against the ADR rather than against
#: a second copy of the implementation.
_DECISION_ORDER: Final[tuple[str, ...]] = ("d-1", "d-3", "d-4", "d-2")

#: A contract limit that holds **one** ``PermissionDecision`` and not three.
#:
#: A constant of its own rather than :data:`_TINY_LIMIT`, because one decision
#: encodes to something over 600 bytes — it embeds a whole ``ToolDefinition``
#: (ADR-0021 §1) — so at 512 the *page* would be refused too and the case would
#: assert nothing about the export in particular. Both halves matter here for
#: :data:`_TINY_LIMIT`'s reason: large enough that ``recent_decisions(limit=1)``
#: answers, small enough that the whole trail does not fit.
_DECISION_LIMIT = 1024

#: How many rulings the overfull subject's trail holds. Three, which is over
#: :data:`_DECISION_LIMIT` while each row is comfortably under it — so what is
#: refused is the **artifact**, which is the only thing that distinguishes a
#: complete export from a truncated one (ADR-0186 §3).
_OVERFULL_DECISIONS = 3

#: The declaration every seeded ruling is recorded over. The least severe
#: representable one, for ``permission_builders.tool``'s reason: nothing in these
#: cases is about severity, and a decision embeds its definition by value.
_RULED_TOOL: Final = ToolDefinition(
    id="smtp",
    capability="send_email",
    description="Send an email.",
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
)


def _ruling(decision_id: str, *, at: datetime) -> PermissionDecision:
    """One recorded ``ALLOW``, built through the sanctioned construction path.

    ``from_request`` rather than the constructor even in a builder: it is what the
    contract asks callers to use, and it is what makes a decision's subject agree
    with the request it was ruled over by construction rather than by care
    (ADR-0021 §1).
    """
    return PermissionDecision.from_request(
        ActionRequest(tool=_RULED_TOOL, parameters={"to": "a@example.com"}, step_id="step-1"),
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="within policy"),
        id=decision_id,
        decided_at=at,
    )


class SeededAuditTrail(FakeAuditTrail):
    """A conforming ``AuditTrail`` that logs its reads and can unorder its export.

    Two capabilities the canonical fake does not owe a consumer, each of which
    ADR-0186 §11 makes a suite case need.

    **``reads`` is the negative control** for §3's "locally and before any I/O": an
    assertion that a malformed ``limit`` was refused is worth little unless a case
    can see the read it did not cause. It is the role
    ``FakeConnectionProvisioner.entries`` already plays for the connection clauses.

    **``ordered_export=False`` exercises the contract's own freedom**, and it is not
    a contrived fixture — it is the only one that tests the clause.
    ``AuditTrail.export``'s Protocol docstring states **no** order, which is exactly
    why ADR-0186 §2 puts the obligation on the engine operation; but both shipped
    trails promise ``recent``'s order in their own docstrings ("Return every
    recorded decision, in the same order as ``recent``", in ``permissions/audit.py``
    and in ``testing/permissions.py`` alike). So a case driven through either of
    them passes for an engine that writes ``tuple(await trail.export())`` and never
    sorts — and the day a conforming trail returns insertion order, the exports are
    wrong and §2's prefix guarantee is gone with them.

    Reversed rather than shuffled, so the wrong answer is **deterministic**: a
    relaying implementation fails every run rather than most of them.
    """

    def __init__(  # noqa: PLR0913 — one keyword per ADR-0194 §1 setting, injected explicitly
        self,
        *,
        ordered_export: bool = True,
        now: Callable[[], datetime] | None = None,
        identifiers: MintsIdentifiers | None = None,
        currency: str | None = None,
        day_ceiling: Decimal | None = None,
        month_ceiling: Decimal | None = None,
        allowance: Decimal | None = None,
        timezone: str = "UTC",
    ) -> None:
        """Create an empty trail.

        Args:
            ordered_export: Whether ``export`` hands back the order ``recent`` uses.
                ``False`` returns the reverse, which the store's contract permits.
            now: The clock the ledger stamps an invocation row's ``recorded_at``
                from. Passed through so :func:`seeded_invocation_trail` can put
                rows at instants it names rather than at whatever the wall clock
                read while the fixture ran — ADR-0192 §4's order is over that
                value, so a fixture racing a real clock states no order at all.
            identifiers: The factory each invocation row's ``id`` is minted from,
                passed through for the same reason: the tie-break is on that id,
                so a suite that cannot name it cannot exercise the tie.
            currency: ADR-0194 §1's reporting currency, or ``None``. Passed through
                because the states ADR-0194 §5 asks a *reader* to tell apart are all
                facts about the **producer's** configuration: with no currency both
                totals carry ``accounted=None`` for one reason and with a currency
                and an unmeasurable row for a different one.
            day_ceiling: The ``CALENDAR_DAY`` ceiling, or ``None``.
            month_ceiling: The ``CALENDAR_MONTH`` ceiling, or ``None``.
            allowance: What an unpriced call is accounted at, or ``None``.
            timezone: The zone the calendar periods are computed in.
        """
        # The wall clock spelled out rather than reached for through the fake's
        # private default: every case but the invocation ones injects nothing and
        # cares about no instant the ledger stamps, and a test module importing a
        # ``_``-prefixed name from the package it is a double for is a coupling
        # worth one line to avoid.
        super().__init__(
            now=now if now is not None else (lambda: datetime.now(UTC)),
            identifiers=identifiers,
            currency=currency,
            day_ceiling=day_ceiling,
            month_ceiling=month_ceiling,
            allowance=allowance,
            timezone=timezone,
        )
        #: Which reads reached the store, in the order they arrived.
        self.reads: list[str] = []
        #: Scripted, and when set **every** read raises it instead of answering.
        #:
        #: A store that cannot be read is a declared failure of both operations —
        #: ``SqliteAuditTrail.recent`` and ``export`` raise ``AuditError`` "if the
        #: trail cannot be read, or holds a row that no longer validates" — and it
        #: is the one failure no sequence of surface calls produces, since nothing a
        #: caller can do corrupts a database. Scripted here for
        #: ``FakeConnectionProvisioner.secrets.fail``'s reason: a knob on the object
        #: standing behind the subject is how a suite reaches a state the surface
        #: cannot ask for, and it reaches it identically through a seam and a socket.
        self.fail_with: AuditError | None = None
        self._ordered_export = ordered_export

    async def recent(self, *, limit: int = 50) -> list[PermissionDecision]:
        """Log the read, then raise :attr:`fail_with` or answer as the fake does."""
        self.reads.append("recent")
        if self.fail_with is not None:
            raise self.fail_with
        return await super().recent(limit=limit)

    async def export(self) -> list[PermissionDecision]:
        """Log the read, then raise :attr:`fail_with` or hand back this trail's order."""
        self.reads.append("export")
        if self.fail_with is not None:
            raise self.fail_with
        rows = await super().export()
        return rows if self._ordered_export else list(reversed(rows))

    async def recent_invocations(self, *, limit: int = 50) -> list[RecordedInvocation]:
        """Log the read, then raise :attr:`fail_with` or answer as the fake does."""
        self.reads.append("recent_invocations")
        if self.fail_with is not None:
            raise self.fail_with
        return await super().recent_invocations(limit=limit)

    async def export_invocations(self) -> list[RecordedInvocation]:
        """Log the read, then raise :attr:`fail_with` or answer as the fake does.

        **No ``ordered_export`` limb, and its absence is the contract's.**
        ``AuditTrail.export`` states *no* order, which is why that read has one; the
        invocation twin states one in terms — "in the same order and joined the same
        way" — so a trail answering otherwise would be non-conforming, and a case
        driven through one would prove nothing about a conforming implementation.
        :class:`FakeSourceReadTrail` gets the same treatment for the same reason.
        """
        self.reads.append("export_invocations")
        if self.fail_with is not None:
            raise self.fail_with
        return await super().export_invocations()


async def seeded_trail(
    *, ordered_export: bool = True, rows: tuple[tuple[str, int], ...] = _SEEDED_DECISIONS
) -> SeededAuditTrail:
    """A trail holding ``rows``, recorded in that order.

    Shared so the three bindings cannot arrange three different premises for one
    clause, exactly as :func:`backwards_clock` is.

    Args:
        ordered_export: Handed to :class:`SeededAuditTrail`.
        rows: What to record, as ``(id, seconds after`` :data:`_RULED_AT` ``)``.

    Returns:
        The seeded trail, with :attr:`SeededAuditTrail.reads` cleared — so a case
        reading it reads what the *subject* caused rather than what the setup did.
    """
    trail = SeededAuditTrail(ordered_export=ordered_export)
    for decision_id, offset in rows:
        await trail.record(_ruling(decision_id, at=_RULED_AT + timedelta(seconds=offset)))
    trail.reads.clear()
    return trail


@dataclass(frozen=True, slots=True)
class DecisionSubject:
    """An engine on the audit surface, and the trail standing behind it.

    Attributes:
        engine: The subject under test.
        trail: The seeded trail the engine ultimately reads, reached from the test
            process rather than through the surface. Read by a case as a **negative
            control** — a ``limit`` ADR-0186 §3 refuses locally must leave ``reads``
            empty — and as the evidence that the unordered binding is not vacuous,
            since a case can ask the trail directly what order it handed over.
    """

    engine: AssistantEngine
    trail: SeededAuditTrail


#: When the seeded invocation trail's first row was appended. Fixed, for
#: :data:`_RULED_AT`'s reason.
_RECORDED_AT: Final = datetime(2026, 3, 3, 11, 0, 0, tzinfo=UTC)

#: The invocation rows every seeded trail holds, **in the order they are
#: appended**, as ``(row id, seconds after`` :data:`_RECORDED_AT` ``, the decision
#: it runs under, the completion to write or ``None``)``.
#:
#: :data:`_SEEDED_DECISIONS`' two deliberate properties, one row kind over
#: (ADR-0192 §9). The append order is not the ``recorded_at`` order, so an
#: implementation relaying insertion order is caught; and ``i-4`` and ``i-3`` share
#: an instant **and are appended in the wrong order for it**, so the ``id``
#: tie-break is *exercised* rather than assumed. Both halves are needed: rows at
#: distinct instants leave an implementation with no tie-break at all passing, and a
#: tie whose append order already agrees with the tie-break leaves one passing that
#: merely relies on its sort being stable.
#:
#: **A clock that steps backwards is not a contrived fixture here**, it is the state
#: ADR-0192 §2 writes the store's own ordering rule against: the ledger decides every
#: admission on its durable append order precisely "so a wall clock that steps
#: backwards cannot make a completed act stop being the most recent one". §4's
#: *listing* order is nonetheless on ``recorded_at``, and these two facts living
#: side by side is what the ordering cases below are for.
#:
#: **One claim per decision**, because :data:`_RULED_TOOL` is side-effecting with
#: ``Idempotency.NONE`` and ADR-0192 §1's consume refuses a second claim under such
#: a decision. That is the contract working rather than a limit on the fixture: four
#: attempts are four authorisations, which is what the ADR is about.
_SEEDED_INVOCATIONS: Final[tuple[tuple[str, int, str, ToolOutcome | None], ...]] = (
    ("i-1", 2, "d-1", None),
    ("i-2", 0, "d-2", None),
    ("i-4", 1, "d-2", ToolOutcome.SUCCEEDED),
    ("i-3", 1, "d-3", None),
)

#: ADR-0192 §4's total order over :data:`_SEEDED_INVOCATIONS`: the row's
#: ``recorded_at`` descending, ties broken by the row's ``id`` ascending. Written
#: out rather than computed, so the expectation is something a reader checks against
#: the ADR rather than against a second copy of the implementation.
_INVOCATION_ORDER: Final[tuple[str, ...]] = ("i-1", "i-3", "i-4", "i-2")

#: How many invocation rows the overfull subject's trail holds.
#:
#: Larger than :data:`_OVERFULL_DECISIONS` and at a **smaller** limit, and the
#: arithmetic is ADR-0192 §4's own point: "a ``RecordedInvocation`` is one small
#: row, two identifiers and a boolean, where a ``PermissionDecision`` measured 858
#: bytes in this tree carrying a whole ``ToolDefinition`` and an egress binding". So
#: the export of invocations reaches a given ceiling later than the export of
#: decisions does, and a fixture that did not say so would be asserting the refusal
#: over a store shape the ADR expressly says is smaller.
_OVERFULL_INVOCATIONS = 6

#: A contract limit that holds **one** ``RecordedInvocation`` and not six.
_INVOCATION_LIMIT = 512


def overfull_invocation_rows() -> tuple[tuple[str, int, str, ToolOutcome | None], ...]:
    """:data:`_OVERFULL_INVOCATIONS` claims, each under an authorisation of its own.

    One claim per decision for :data:`_SEEDED_INVOCATIONS`' reason — ADR-0192 §1's
    consume admits no second claim under a side-effecting, non-idempotent ruling —
    and shared so the three bindings arrange one premise rather than three.

    Returns:
        The rows, for :func:`seeded_invocation_trail`.
    """
    return tuple(
        (f"o-{index}", index, f"od-{index}", None) for index in range(_OVERFULL_INVOCATIONS)
    )


class _ScriptedIdentifiers:
    """An identifier factory that hands out a written-down sequence (ADR-0192 §2).

    The store mints every invocation row's id from an injected factory and accepts
    none from a caller, which is what makes the ids unguessable in a real store and
    unnameable in a fixture. ADR-0192 §4's tie-break is *on that id*, so a suite
    with no way to name one cannot state the order it is asserting — which is the
    whole reason this exists rather than the fixture reading ids back and sorting
    them, an assertion that would pass for any order at all.

    ``reserve`` is honoured rather than ignored, because ``open_invocations``
    reserves every claim id it returns and a factory that then reissued one would
    let a completion the recovery scan is holding land on a different call's claim
    (ADR-0192 §2). Nothing in this block calls it, and a factory that quietly
    dropped the promise would be a fixture teaching the wrong shape.
    """

    def __init__(self, ids: Sequence[str]) -> None:
        """Draw from ``ids`` in order.

        Args:
            ids: The identifiers to mint, one per append.
        """
        self._remaining = list(ids)
        self._reserved: set[str] = set()
        self._beyond = count()

    def __call__(self) -> str:
        """Return the next scripted identifier, or a generated one past the script.

        **The fallback is not a loosening**, it is what lets a case append rows the
        fixture did not name — the default-page case wants fifty more rows and cares
        about none of their ids. What the script pins is what an assertion names;
        past it the sequence is still unique, which is all the store asks of a
        factory.
        """
        while self._remaining:
            drawn = self._remaining.pop(0)
            if drawn not in self._reserved:
                return drawn
        while True:
            drawn = f"beyond-the-script-{next(self._beyond)}"
            if drawn not in self._reserved:
                return drawn

    def reserve(self, ids: Iterable[str]) -> None:
        """Promise that none of ``ids`` will be returned by any later call."""
        self._reserved.update(ids)


async def seeded_invocation_trail(
    *,
    rows: tuple[tuple[str, int, str, ToolOutcome | None], ...] = _SEEDED_INVOCATIONS,
) -> SeededAuditTrail:
    """A trail holding ``rows`` as invocation records, appended in that order.

    Shared so the three bindings cannot arrange three different premises for one
    clause, exactly as :func:`seeded_trail` is — and built **through the ledger**
    rather than by writing rows into the store, because the id and the instant are
    the store's to mint and stamp (ADR-0192 §2). A fixture that reached past that
    would be seeding a shape no conforming store can produce.

    The decisions the rows run under are seeded first — every distinct one they
    name, in first-appearance order — since ADR-0192 §1 refuses a claim under an
    authorisation the trail did not record and §2's join refuses to return a row it
    cannot pair. Derived from ``rows`` rather than fixed at
    :data:`_SEEDED_DECISIONS`, so a larger fixture is a longer list of rows rather
    than two lists that have to agree.

    Args:
        rows: What to append, as :data:`_SEEDED_INVOCATIONS` describes.

    Returns:
        The seeded trail, with :attr:`SeededAuditTrail.reads` cleared — so a case
        reading it reads what the *subject* caused rather than what the setup did.
    """
    scripted = iter([_RECORDED_AT + timedelta(seconds=offset) for _, offset, _, _ in rows])
    beyond = count(1)

    def reading() -> datetime:
        """The next scripted instant, or one **before** the seeded window past it.

        Backwards rather than forwards so rows a case appends for itself sort below
        the ones the fixture names, and the ordering assertions stay about the four
        rows they enumerate. The decision block's default-page case back-dates its
        extra rulings for the same reason and by the same arithmetic.
        """
        stamped = next(scripted, None)
        if stamped is not None:
            return stamped
        return _RECORDED_AT - timedelta(seconds=next(beyond))

    trail = SeededAuditTrail(
        now=reading,
        identifiers=_ScriptedIdentifiers([row_id for row_id, _, _, _ in rows]),
    )
    for index, decision_id in enumerate(dict.fromkeys(row[2] for row in rows)):
        await trail.record(_ruling(decision_id, at=_RULED_AT + timedelta(seconds=index)))
    open_claims: dict[str, str] = {}
    for row_id, _, decision_id, outcome in rows:
        if outcome is None:
            claim = await trail.claim_invocation(decision=await _recorded(trail, decision_id))
            open_claims[decision_id] = claim.id
            assert claim.id == row_id, "the scripted identifier sequence has drifted"
            continue
        completion = await trail.complete_invocation(
            claim_id=open_claims[decision_id],
            outcome=outcome,
            incurred_cost=ToolCost(basis=CostBasis.FREE),
        )
        assert completion.id == row_id, "the scripted identifier sequence has drifted"
    trail.reads.clear()
    return trail


async def _recorded(trail: SeededAuditTrail, decision_id: str) -> PermissionDecision:
    """The stored decision under ``decision_id``, for the ledger to claim against.

    ADR-0192 §1's consume compares the decision it was **passed** against the one
    the store holds and refuses if they differ, so a fixture handing over a
    freshly-built copy would be testing the equality rather than the seeding. The
    store's own copy is what a real caller holds too: it comes back from the
    permission stage that recorded it.
    """
    stored = await trail.get(decision_id)
    assert stored is not None, "the fixture must seed the decision before the act under it"
    return stored


@dataclass(frozen=True, slots=True)
class InvocationSubject:
    """An engine on the invocation surface, and the trail standing behind it.

    :class:`DecisionSubject`'s shape over ADR-0192 §4's pair, and it is a separate
    class rather than a reuse for the reason the two operations are separate: the
    trail is the same object, and what a case reaches for on it is not. A shared
    subject would let a case about the invocation order be written against
    ``recent`` by accident and pass.

    Attributes:
        engine: The subject under test.
        trail: The seeded trail the engine ultimately reads, reached from the test
            process rather than through the surface. Read as a **negative
            control** — a ``limit`` ADR-0192 §4 refuses locally must leave
            ``reads`` empty — and as the evidence that each operation reaches its
            own store read rather than the other's.
    """

    engine: AssistantEngine
    trail: SeededAuditTrail


@dataclass(frozen=True, slots=True)
class SpendSubject:
    """An engine on ADR-0194 §6's read, and the ledger standing behind it.

    :class:`InvocationSubject`'s shape over a third face of the same store, and a
    separate class for the same reason: what a case reaches for on the ledger is
    not what an invocation case reaches for, and a shared subject would let a case
    about the period order be written against the wrong read and pass.

    Attributes:
        engine: The subject under test.
        ledger: The seeded holder the engine ultimately reads, reached from the test
            process rather than through the surface — there being no producer for a
            row on this surface at all, since the two appends live on
            ``InvocationLedger`` behind the tool seam and the admission on
            ``SpendGate`` behind it.
    """

    engine: AssistantEngine
    ledger: SeededAuditTrail


#: A payload limit two ``SpendTotal`` values cannot fit inside, for ADR-0194 §6's
#: ``OversizedValueError``. Small rather than realistic: §6 declares the class
#: without claiming the state is remote, and what a suite can arrange cheaply is
#: the limit rather than the ten thousand rows a genuinely large total needs.
_SPEND_LIMIT: Final = 64

#: The reporting currency every spend fixture here is configured in.
SPEND_CURRENCY: Final = "USD"

#: A **zero** ceiling, which ADR-0194 §11 makes the consumer group carry through
#: every seam: the relay, the wire, and §6's rendering. It is the configuration
#: that refuses the most, so a producer or a renderer reading falsiness of a
#: ceiling is furthest from the truth exactly here — and invisible at every other
#: ceiling value.
SPEND_ZERO_CEILING: Final = Decimal("0")


async def seeded_spend_ledger(  # noqa: PLR0913 — one keyword per ADR-0194 §1 setting, plus the open claim
    *,
    currency: str | None = SPEND_CURRENCY,
    day_ceiling: Decimal | None = None,
    month_ceiling: Decimal | None = None,
    allowance: Decimal | None = None,
    timezone: str = "UTC",
    open_claim: bool = False,
) -> SeededAuditTrail:
    """A ledger configured as ADR-0194 §1 admits, optionally holding an open claim.

    Shared so the three bindings cannot arrange three different premises for one
    clause, exactly as :func:`seeded_invocation_trail` is. The claim is appended
    **through the ledger** rather than written into the store, because the id and
    the instant are the store's to mint and stamp (ADR-0192 §2).

    Args:
        currency: The reporting currency, or ``None`` for the other absence.
        day_ceiling: The ``CALENDAR_DAY`` ceiling, or ``None``.
        month_ceiling: The ``CALENDAR_MONTH`` ceiling, or ``None``.
        allowance: What an unpriced call is accounted at, or ``None``.
        timezone: The zone the calendar periods are computed in.
        open_claim: Whether to leave one claim standing with no completion, which
            ADR-0194 §2 makes its period's accounted total **indeterminate**.

    Returns:
        The configured ledger, with :attr:`SeededAuditTrail.reads` cleared.
    """
    ledger = SeededAuditTrail(
        currency=currency,
        day_ceiling=day_ceiling,
        month_ceiling=month_ceiling,
        allowance=allowance,
        timezone=timezone,
    )
    if open_claim:
        await ledger.record(_ruling("spend-open", at=_RULED_AT))
        await ledger.claim_invocation(decision=await _recorded(ledger, "spend-open"))
    ledger.reads.clear()
    return ledger


#: When the seeded read trail's first grant check resolved. Fixed, for
#: :data:`_RULED_AT`'s reason.
_CHECKED_AT: Final = datetime(2026, 3, 2, 14, 0, 0, tzinfo=UTC)

#: The rows every seeded read trail holds, as ``(id, seconds after``
#: :data:`_CHECKED_AT` ``)``, **in the order they are recorded** — which is the
#: order that decides this surface, because ADR-0185 §6 orders this store by
#: recording order and "never by ``checked_at``".
#:
#: **Every plausible wrong ordering of these four rows is a different sequence from
#: the right one, and that is the whole design of the fixture.** The right answer is
#: :data:`_READ_ORDER`. Against it: relaying the store's ``export`` gives the
#: recorded order below; ``checked_at`` descending gives ``r-4, r-3, r-2, r-1`` and
#: ascending its reverse; ``id`` ascending gives ``r-1 … r-4`` and descending
#: ``r-4 … r-1``. None of the five equals :data:`_READ_ORDER`, so a case asserting
#: the sequence positively also refutes each of them — which a fixture with sorted
#: ids or monotonic instants would not, and this one deliberately has neither.
#:
#: ``r-3`` and ``r-2`` share an instant, so the "a tie in ``checked_at`` is not a tie
#: in this order" case is exercised over rows that really tie rather than assumed.
_SEEDED_READS: Final[tuple[tuple[str, int], ...]] = (
    ("r-3", 2),
    ("r-1", 0),
    ("r-4", 3),
    ("r-2", 2),
)

#: ADR-0186 §10's order over :data:`_SEEDED_READS`: newest-**recorded** first, which
#: is the recorded sequence reversed. Written out rather than computed, so the
#: expectation is something a reader checks against the ADR rather than against a
#: second copy of the implementation.
_READ_ORDER: Final[tuple[str, ...]] = ("r-2", "r-4", "r-1", "r-3")

#: How many read records the overfull subject's trail holds. Six, which is over
#: :data:`_TINY_LIMIT` while a single row — about 134 bytes, a record carrying no
#: content at all (ADR-0185 §10) — is comfortably under it. So what is refused is
#: the **artifact**, which is the only thing that distinguishes a complete export
#: from a truncated one (ADR-0186 §3).
#:
#: :data:`_TINY_LIMIT` itself rather than a constant of its own, unlike
#: :data:`_DECISION_LIMIT`: that one exists because a single ``PermissionDecision``
#: embeds a whole ``ToolDefinition`` and overruns 512 bytes on its own, and a read
#: record embeds nothing.
_OVERFULL_READS = 6


def _attempt(record_id: str, *, at: datetime) -> SourceReadRecord:
    """One recorded ``COMPLETED`` read, through the canonical builder.

    ``source_read_record`` rather than the model's constructor, for
    :func:`_ruling`'s reason: the helper derives the ``grant`` pointer from the
    outcome, so a row's grant agrees with what §2 permits for that outcome by
    construction rather than by care (ADR-0185 §2).
    """
    return source_read_record("calendar", record_id=record_id, checked_at=at, produced=1)


class SeededReadTrail:
    """A conforming ``SourceReadTrail`` that logs which read reached it.

    The one capability the canonical fake does not owe a consumer, and the one the
    suite cases below need. §11's clauses are written about the decision pair and
    are not in §10's inheritance list; they are followed here because §10 makes this
    pair a mirror of §1's, so the same cases are the ones worth having. ``reads`` is the **negative
    control** for §3's "locally and before any I/O": an assertion that a malformed
    ``limit`` was refused is worth little unless a case can see the read it did not
    cause. It is the role :attr:`SeededAuditTrail.reads` plays one store over.

    **It wraps the canonical fake rather than subclassing it**, which is the one
    structural difference from :class:`SeededAuditTrail` and is not a preference:
    ``FakeSourceReadTrail`` is ``@final``, and that marker is ADR-0185's lane's
    decision rather than this suite's to quietly lift. Delegation costs nothing here
    because every Protocol in ``core/protocols.py`` is satisfied **structurally** —
    an object carrying the four members is a ``SourceReadTrail``, whatever it
    inherits — so what the bindings hand the engine is a conforming store either
    way. The conformance itself is not taken on trust: the suite's own
    ``test_it_satisfies_the_protocol`` covers the *engine*, and every case below
    drives this object through one.

    **No ``ordered_export`` knob here, and its absence is the contract rather than an
    omission.** :class:`SeededAuditTrail` needs one because ``AuditTrail.export``
    states *no* order, so the only way to catch an engine that relays is to hand it
    a conforming trail that answers unordered. ``SourceReadTrail.export`` states its
    order — "every record the store holds, in recording order" — so a trail
    answering in any other order would not be conforming, and a double that did so
    would test an implementation against a store no implementation may be. What
    catches a relaying engine here instead is the **direction**: recording order is
    the reverse of the listing's, so relaying it fails
    :meth:`AssistantEngineContract.test_the_read_export_is_reversed_and_not_relayed`
    over any trail with two rows in it.
    """

    def __init__(self) -> None:
        """Create an empty trail that logs its reads."""
        self._trail = FakeSourceReadTrail()
        #: Which reads reached the store, in the order they arrived.
        self.reads: list[str] = []

    def fail_read(self) -> None:
        """Arm both reads to raise ``ReadTrailError``.

        Relayed to the canonical fake's own lever. "The store could not be read" is
        the one failure no sequence of surface calls produces — nothing a caller can
        do corrupts a database — so a suite case for it needs a knob on the object
        standing behind the subject, which reaches that state identically through a
        seam and through a socket.
        """
        self._trail.fail_read()

    async def record(self, read: SourceReadRecord) -> str:
        """Append ``read`` and return its id. Not logged: only *reads* are controls."""
        return await self._trail.record(read)

    async def recent(self, *, limit: int = 50) -> list[SourceReadRecord]:
        """Log the read, then answer as the canonical fake does."""
        self.reads.append("recent")
        return await self._trail.recent(limit=limit)

    async def export(self) -> list[SourceReadRecord]:
        """Log the read, then answer as the canonical fake does."""
        self.reads.append("export")
        return await self._trail.export()

    async def clear(self) -> int:
        """Delete every record, returning the number removed.

        Carried so this object satisfies ``SourceReadTrail`` **whole** rather than
        only the two members the engine calls. Nothing on the promoted surface
        reaches it — ``SourceReadTrail.clear`` stays unpromoted on ADR-0186 §4's
        reasoning read one store over, §4 not being in §10's inheritance list — and
        a double that omitted it would be a narrower seam than the
        one the engine is wired with, which is how a fixture starts proving less
        than it appears to.
        """
        return await self._trail.clear()


async def seeded_read_trail(
    rows: tuple[tuple[str, int], ...] = _SEEDED_READS,
) -> SeededReadTrail:
    """A read trail holding ``rows``, recorded in that order.

    Shared so the three bindings cannot arrange three different premises for one
    clause, exactly as :func:`seeded_trail` is.

    Args:
        rows: What to record, as ``(id, seconds after`` :data:`_CHECKED_AT` ``)``.

    Returns:
        The seeded trail, with :attr:`SeededReadTrail.reads` cleared — so a case
        reading it reads what the *subject* caused rather than what the setup did.
    """
    trail = SeededReadTrail()
    for record_id, offset in rows:
        await trail.record(_attempt(record_id, at=_CHECKED_AT + timedelta(seconds=offset)))
    trail.reads.clear()
    return trail


@dataclass(frozen=True, slots=True)
class ReadSubject:
    """An engine on the read surface, and the trail standing behind it.

    Attributes:
        engine: The subject under test.
        trail: The seeded trail the engine ultimately reads, reached from the test
            process rather than through the surface. Read by a case as a **negative
            control** — a ``limit`` ADR-0186 §3 refuses locally must leave ``reads``
            empty — and as the evidence that the reversal case is not vacuous, since
            a case can ask the trail directly what order it handed over.
    """

    engine: AssistantEngine
    trail: SeededReadTrail


@dataclass(frozen=True, slots=True)
class RoutedParkSubject:
    """An engine holding one answerable **routed** park, and what it is about (§7).

    ADR-0197 §12 puts the routed resume's coverage in this shared suite rather than in
    one implementation's own tests, "because every implementation of that surface owes
    it": ``resume``'s *contract* moved, and a contract that moved for one implementation
    only is not a contract.

    **A subject rather than a bare engine**, because the clauses are about what did and
    did not happen to the user's own data, and the only way to ask that through the
    promoted surface is to know which record the park is about. Everything the cases
    below read is on the surface itself — ``belief`` says whether the destruction ran,
    ``export_decisions`` says whether a ruling was recorded — so the three bindings
    arrange the *premise* and share every assertion.

    Attributes:
        engine: The subject under test.
        token: The continuation the routed park is answered by. It is the card's own
            token, handed over rather than re-minted: ADR-0197 §7 makes a routed park
            doubly unreachable from the surface — ``pending_confirmations`` does not
            list it and no durable store recovers it — so a case that had to ask for
            the token could not exist.
        belief_id: The belief the parked ``forget`` would destroy. ``forget`` is the
            member chosen because its effect is observable through the promoted surface
            in both directions: ``belief`` answers the record before and ``None`` after.
    """

    engine: AssistantEngine
    token: ContinuationToken
    belief_id: str


#: The ceiling ADR-0198 §4's bound is built at, for the subject that observes it.
#: **One**, because §4 reuses ``max_outstanding_confirmations`` as the size of the
#: retained set and one is the smallest value at which a discard is reachable in two
#: settlements rather than in a thousand. It is a construction-time property of a
#: deployment, so it is a separate subject rather than a knob a case turns —
#: :attr:`AssistantEngineContract.tiny_engine`'s reasoning, one setting over.
SETTLED_SINGLE_SLOT: Final = 1


@dataclass(frozen=True, slots=True)
class SettledParkSubject:
    """An engine whose park is **settled**, and the token that still names it (§1).

    **A subject rather than a bare engine, because a settled binding is not
    enumerable.** ADR-0052 §1 step 2 skips a binding the trail no longer holds
    pending, and ADR-0198 §4 rules that ``pending_confirmations`` neither lists a
    settled binding nor mints a token for one — that is the whole reason a
    restatement had to become a `resume` and could not be a listing. So a case that
    had to *ask* for the token could not exist, and the fixture hands it over.

    Attributes:
        engine: The subject under test, holding the settled record.
        token: The continuation the settled binding is restated by.
    """

    engine: AssistantEngine
    token: ContinuationToken


@dataclass(frozen=True, slots=True)
class SingleSlotParkSubject:
    """A subject at :data:`SETTLED_SINGLE_SLOT` that has settled one park and holds one.

    **Its existence is the first of §4's three facts.** At a ceiling of one, a second
    park can only have been admitted beside :attr:`settled`'s record if that record
    holds **no** ceiling slot — which is §4's rule, and the one an implementation
    that counted retention with the parks would fail before a case ran. The fixture
    settles the first park and parks the second, in that order, because that order is
    the only one the ceiling admits.

    Attributes:
        engine: The subject under test.
        settled: The token of the **older**, already-answered binding, retained at
            the moment the fixture hands the subject over.
        parked: The token of the **newer**, still-answerable park.
    """

    engine: AssistantEngine
    settled: ContinuationToken
    parked: ContinuationToken


class AssistantEngineContract(ABC):
    """What every ``AssistantEngine`` implementation must do."""

    @pytest.fixture
    @abstractmethod
    def engine(self) -> AssistantEngine:
        """The subject, at its ordinary contract limit."""

    @pytest.fixture
    @abstractmethod
    def tiny_engine(self) -> AssistantEngine:
        """The same implementation, with the contract limit set to :data:`_TINY_LIMIT`.

        A separate subject rather than a knob on the first, because the limit is a
        construction-time property of an implementation — a deployment's frame size
        — and not something a caller changes mid-flight.
        """

    @pytest.fixture
    @abstractmethod
    def granting_engine(self) -> AssistantEngine:
        """A subject holding **exactly one** grantable source, named :data:`_SOURCE`.

        A separate subject rather than a step in a test, for ``parked_engine``'s
        reason: which sources exist is a property of what the composition root
        *built* (ADR-0102 §7), not something the surface can be asked to change. An
        implementation has to be handed to the suite already holding one.

        It must hold no grant on that source, so the first ``grant`` in each test
        below is the first grant. It must carry a configured location for it, so
        §6's disclosure is a value a client can render.
        """

    @pytest.fixture
    @abstractmethod
    def defective_source_engine(self) -> AssistantEngine:
        """A subject holding :data:`_SOURCE` **and** two sources that are not grantable.

        One whose configured location has no UTF-8 encoding (:data:`_UNWRITABLE`),
        and one whose declared identity is not in canonical form
        (:data:`_NOT_CANONICAL`). Both are states a real hub can be built into —
        Linux pathnames are bytes, and a reader may declare whatever it likes — and
        neither is reachable through the surface, so an implementation has to be
        handed to the suite already holding them.

        :data:`_SOURCE` is held alongside them because the clause has two halves and
        the second is the one an over-eager implementation fails: enumeration of the
        others must be **unaffected**, so one defective source may not take the whole
        response down.
        """

    @pytest.fixture
    @abstractmethod
    def back_dated_engine(self) -> AssistantEngine:
        """:attr:`granting_engine`'s subject, whose clock runs **backwards**.

        Each record it mints is stamped *earlier* than the one before, so a
        ``grant`` followed by a ``revoke`` produces the pair ADR-0102 §12's
        normative clause requires: a revocation whose ``decided_at`` predates the
        grant it revokes.

        **A fixture because no sequence of surface calls can produce it.** ADR-0102
        §5 puts the clock on the implementation and keeps it away from every client,
        which is what stops a caller backdating a user act — so the only way to
        reach the state ADR-0097 §4 explicitly permits is to hand an implementation
        a clock that has been corrected backwards, which is exactly the deployment
        the clause is about.
        """

    @pytest.fixture
    @abstractmethod
    def disagreeing_engine(self) -> AssistantEngine:
        """A subject whose two grant answers **disagree**, which is legitimate (ADR-0139 §1).

        It holds :data:`_SOURCE` as a grantable reader with **no grant on it**, and
        a **live grant on** :data:`_UNHELD_SOURCE`, which no held reader declares.
        So ``grantable_sources`` names one source and ``standing_grants`` names the
        other, and the two sets are disjoint.

        **A fixture because no sequence of surface calls reaches it.** ``grant``
        admits only a held reader's declared name (ADR-0102 §4) and nothing on the
        surface unholds one, so a grant on a source the hub does not hold can only
        be handed to the suite — which is exactly how it arises in a deployment,
        through a configuration edit rather than through a request.

        It is the state the whole operation exists for: before it, such a grant was
        live, read-authorising, revocable, and reported by nothing.
        """

    @pytest.fixture
    @abstractmethod
    def overfull_granting_engine(self) -> AssistantEngine:
        """A subject at :data:`_TINY_LIMIT` holding :data:`_OVERFULL_GRANTS` live grants.

        Enough that the live set does not fit the contract limit, and small enough
        that each individual record does — so the refusal under test is about the
        **set**, which is the only thing that distinguishes a complete answer from
        a paged one (ADR-0139 §2).

        A fixture for :attr:`granting_engine`'s reason and one of its own: granting
        six sources through the surface would need six held readers *and* would run
        each ``grant``'s own result past the same bound, so the setup would be
        refused before the case began.
        """

    @pytest.fixture
    @abstractmethod
    def connections(self) -> ConnectionSubject:
        """A subject with **no** connection, paired with the provisioner behind it.

        **Why the provisioner comes with it.** Several of ADR-0151's surface
        clauses are negative — a refused act "writes nothing", a refusal happens
        "without reaching the store" — and an assertion that nothing was written is
        worth nothing unless a case can see the log it was not written to. The
        canonical fake's ``entries`` is that negative control, and its
        ``secrets.fail`` is how the one state the surface cannot otherwise reach —
        a **pending** live record — is produced.

        **The same object stands behind all three bindings**, which is what keeps
        these clauses shared rather than three parallel sets: the concrete engine
        wires it through ``ConnectionOperations``, the canonical fake holds one as
        ``connections``, and the client's hub serves a fake that holds one. So a
        clause here is judged against one provisioner and three surfaces, which is
        the split the suite exists to police.

        **What is deliberately not here.** ADR-0151 §16 opens item 2 with "a clause
        per ruling above that a store cannot exhibit", and §7's classification —
        which failure becomes which class, at each of ADR-0148 §6's write points —
        is a ruling a store *can* exhibit and is pinned where it belongs, against
        every ``ConnectionProvisioner`` in
        ``tests/tools/connection_provisioner_contract.py``. Restating it here would
        bind the same subject twice through a longer path and would drift.
        """

    @pytest.fixture
    @abstractmethod
    def tiny_connections(self) -> ConnectionSubject:
        """:attr:`connections`' subject at :data:`_TINY_LIMIT`, and its provisioner.

        **A separate subject for the reason :attr:`tiny_engine` is one**: the limit
        is a construction-time property of a deployment rather than something a
        caller changes mid-flight. It exists because a credential is the one
        argument on this surface whose *size* can decide a call, and because the
        three implementations reach that decision by different routes — the wire
        client measures a payload it is about to serialise, and the in-process ones
        measure a payload nobody will. ADR-0084 §4 requires them to agree anyway,
        and only a shared clause at a reachable limit says whether they do.
        """

    @pytest.fixture
    @abstractmethod
    def routed_park(self) -> RoutedParkSubject:
        """A subject holding **exactly one** answerable routed park, on a ``forget``.

        The routed twin of :attr:`parked_engine`, and it is a fixture for that one's
        reason twice over. A park is reached inside a turn, so an implementation has to
        be handed to the suite already holding one — and a *routed* park is not reachable
        even then: ADR-0197 §7 rules that ``pending_confirmations`` does not list it and
        that it is not recovered across a restart, so there is no surface call that
        produces or re-mints its token.

        The belief the park is about must be **held** by the subject, so a case can ask
        the surface whether the destruction ran. The subject must have recorded no
        permission decision for the park, so ``export_decisions`` is a usable control.
        """

    @pytest.fixture
    @abstractmethod
    def parked_engine(self) -> AssistantEngine:
        """A subject holding **exactly one** answerable parked confirmation, on an egress call.

        The resume path cannot be reached by calling the surface: parking is the
        *policy's* ruling, reached inside a turn, so an implementation has to be
        handed to the suite already in that state. It is a fixture rather than a
        step in a test for that reason — and it is the shape ADR-0042 §4's whole
        park/render/relay sequence depends on, so a suite that skipped it would
        leave a client with no shared account of the one interaction a human is in
        the middle of.

        **The park is on an *egress* call** (ADR-0178 §3, §5). The clause below
        binds every producer of a
        :class:`~ai_assistant.core.types.ConfirmationEgress`, and a fixture that
        parked a non-egress call would leave it vacuous for that subject — which is
        exactly how a canonical fake comes to assemble the member some other way
        and still pass a suite. What the confirmation carries is otherwise
        unconstrained: which account, which arguments and how many occurrences are
        each implementation's own.
        """

    @pytest.fixture
    @abstractmethod
    def settled_park(self) -> SettledParkSubject:
        """A subject whose park is **settled**, and the token that still names it (§1).

        The fixture answers the park; what the cases below do is present its token a
        second time. It is a fixture rather than two lines in each case for the reason
        :attr:`parked_engine` is one and one of its own: settling needs a park, which
        parking is the policy's ruling reached inside a turn, and the answered token is
        then unreachable — ADR-0198 §4 rules that ``pending_confirmations`` neither
        lists a settled binding nor mints a token for one.

        The subject must have settled **exactly one** park and must still retain it, so
        the restatement under test is the record §1 installs rather than an accident of
        a table too small or too large.
        """

    @pytest.fixture
    @abstractmethod
    def settled_park_without_its_execution(self) -> SettledParkSubject:
        """:attr:`settled_park`'s subject whose plan store **no longer holds** the execution.

        ADR-0198 §2 rules that a restatement's ``StepOutcome.state`` is re-read from the
        plan store at the moment of the restatement and is never a snapshot cached at
        settlement — ``StepOutcome.state`` is "the durable execution state after the
        last transition committed", and a cached value stops being that as soon as
        anything advances the execution (ADR-0139 §2). Where the execution is no longer
        held there is nothing to read, and §2's answer is a ``PlanningError`` rather than
        an assertion about an outcome the engine cannot see.

        **A fixture because no call on this surface removes an execution.** The
        promoted surface reaches plan state through no member at all, so the state has
        to be arranged behind the engine — which is how it arises in a deployment, when
        a user erases their history under ADR-0119 or a store is rebuilt beneath a
        process that is still running.

        **Without it an implementation that cached the outcome passes every other case
        in this section** and answers with an ``ExecutionState`` the store has stopped
        holding.
        """

    @pytest.fixture
    @abstractmethod
    def single_slot_parks(self) -> SingleSlotParkSubject:
        """A subject at :data:`SETTLED_SINGLE_SLOT` holding one settled record and one park.

        The shape the suite already uses for a zero-ceiling ledger
        (:data:`SPEND_ZERO_CEILING` behind :attr:`spending`), one setting over: a
        ceiling is a construction-time property of a deployment rather than something a
        caller changes mid-flight, so the subject is built at it and handed over.

        The fixture settles one park and then parks another, in that order — the only
        order a ceiling of one admits, and the order that makes the subject's *existence*
        evidence for ADR-0198 §4's first clause.

        **Without it an implementation that retained every settled record forever, or
        discarded the newest instead of the oldest, passes every other case in this
        section**, because each of them presents one token to a table nothing has
        crowded.
        """

    @pytest.fixture
    @abstractmethod
    def decisions(self) -> DecisionSubject:
        """A subject over a trail holding :data:`_SEEDED_DECISIONS`, and that trail.

        **A fixture because nothing on this surface writes one.** ADR-0186 §4
        refuses a promoted ``record`` — a client that could append to the audit
        record of what was permitted could fabricate history — so the only way a
        case reaches a trail with rows in it is to be handed an implementation
        already holding them. :func:`seeded_trail` builds it, so the three bindings
        cannot arrange three different premises for one clause.

        **The trail comes with it** for :attr:`connections`' reason: ADR-0186 §3's
        local refusals are negative clauses — refused "before any I/O" — and an
        assertion that no read happened is worth nothing unless a case can see the
        log it did not reach. It is read from the test process rather than through
        the surface, which is the point of a negative control.

        Its export is **ordered**, so the two cases about the order over an ordinary
        conforming trail stay separate from the one that exercises the store
        contract's own freedom (:attr:`unordered_decisions`).
        """

    @pytest.fixture
    @abstractmethod
    def unordered_decisions(self) -> DecisionSubject:
        """:attr:`decisions`' subject over a trail whose ``export`` is **unordered**.

        The same rows, handed back by ``AuditTrail.export`` in an order ADR-0021 §4
        does not state and ADR-0186 §2 does not inherit —
        ``seeded_trail(ordered_export=False)``.

        **The case that separates an engine which sorts from one which relays**, and
        the only one of the three order cases that does (ADR-0186 §11). Both shipped
        trails promise ``recent``'s order for ``export`` in their own docstrings, so
        every case driven through either of them passes for an implementation that
        writes ``tuple(await trail.export())`` and never sorts. A fixture rather
        than a step in a test, because no caller can ask a trail to answer
        differently.
        """

    @pytest.fixture
    @abstractmethod
    def overfull_decisions(self) -> AssistantEngine:
        """A subject at :data:`_DECISION_LIMIT` holding :data:`_OVERFULL_DECISIONS` rulings.

        Enough that the whole trail does not fit the contract limit, and few enough
        that a single row does — so what is refused is the **artifact**, which is
        the only thing that distinguishes a complete export from a truncated one
        (ADR-0186 §3).

        A fixture for :attr:`decisions`' reason, and one of its own: at a limit this
        small the *setup* would be refused if it ran through the surface, exactly as
        :attr:`overfull_granting_engine`'s six grants would be.
        """

    @pytest.fixture
    @abstractmethod
    def invocations(self) -> InvocationSubject:
        """A subject over a trail holding :data:`_SEEDED_INVOCATIONS`, and that trail.

        **A fixture because nothing on this surface writes one**, on
        :attr:`decisions`' reason and a sharper version of it: ADR-0192 §4 promotes
        exactly two operations and both are reads, the two *appends* live on
        :class:`~ai_assistant.core.protocols.InvocationLedger` behind the tool seam,
        and ``AuditTrail.open_invocations`` is deliberately unpromoted. So the only
        route to a trail with rows in it is to be handed an implementation already
        holding them, and :func:`seeded_invocation_trail` builds it so the three
        bindings cannot arrange three different premises for one clause.

        **The trail comes with it** for :attr:`decisions`' reason: ADR-0192 §4's
        local refusals are negative clauses — refused "before any I/O" — and an
        assertion that no read happened is worth nothing unless a case can see the
        log it did not reach.

        There is no unordered sibling to this fixture, and the reason is
        :attr:`reads`': ``AuditTrail.export_invocations`` *states* its order — "the
        unbounded twin, in the same order and joined the same way" — where
        ``AuditTrail.export`` states none, so a trail answering otherwise would be
        non-conforming rather than exercising a freedom. What catches an
        implementation whose sort is wrong is the fixture's own shape instead: every
        plausible wrong ordering of these four rows is a different sequence from
        :data:`_INVOCATION_ORDER`.
        """

    @pytest.fixture
    @abstractmethod
    def overfull_invocations(self) -> AssistantEngine:
        """A subject at :data:`_INVOCATION_LIMIT` holding :data:`_OVERFULL_INVOCATIONS` rows.

        Enough that the whole trail does not fit the contract limit, and few enough
        that a single row does — :attr:`overfull_decisions`' shape, at a **smaller**
        limit and over **more** rows, which is ADR-0192 §4's own arithmetic about
        this projection being bounded by construction where a decision carries a
        whole ``ToolDefinition``.
        """

    @pytest.fixture
    @abstractmethod
    def reads(self) -> ReadSubject:
        """A subject over a trail holding :data:`_SEEDED_READS`, and that trail.

        **A fixture because nothing on this surface writes one**, on
        :attr:`decisions`' reason arriving from the other side: there a promoted
        ``record`` is *refused* (ADR-0186 §4), here there was never one to refuse —
        a read is authored on the seam that gated it (ADR-0185 §5), and ADR-0186
        §10's pair is two reads and nothing else. Either way the only route to a
        trail with rows in it is to be handed an implementation already holding
        them, and :func:`seeded_read_trail` builds it so the three bindings cannot
        arrange three different premises for one clause.

        **The trail comes with it** for :attr:`decisions`' reason: ADR-0186 §3's
        local refusals are negative clauses — refused "before any I/O" — and an
        assertion that no read happened is worth nothing unless a case can see the
        log it did not reach.

        There is no unordered sibling to this fixture, and
        :class:`SeededReadTrail` records why: this store *states* its export's
        order, so the case that catches a relaying engine is the **direction** one
        rather than a double exercising a freedom the contract does not grant.
        """

    @pytest.fixture
    @abstractmethod
    def overfull_reads(self) -> AssistantEngine:
        """A subject at :data:`_TINY_LIMIT` holding :data:`_OVERFULL_READS` records.

        Enough that the whole trail does not fit the contract limit, and few enough
        that a single row does — :attr:`overfull_decisions`' shape, at the shared
        tiny limit rather than a bespoke one, because a read record carries no
        content (ADR-0185 §10) and so is a fraction of a ruling's size.
        """

    # --- the shape of the surface -----------------------------------------

    def test_it_satisfies_the_protocol(self, engine: AssistantEngine) -> None:
        """Structurally, at runtime — not merely by a type checker's reading."""
        assert isinstance(engine, AssistantEngine)

    def test_lifecycle_is_not_part_of_the_contract(self, engine: AssistantEngine) -> None:
        """ADR-0083 §8: an implementation without a lifecycle conforms.

        Asserted over the **Protocol** rather than over the subject, because a
        concrete engine may legitimately keep both methods — a Protocol constrains
        what an implementation must have, not what it may not. What must stay true
        is that nothing here obliges a client to have them, since a client that
        could call ``aclose()`` could shut down the hub from a spoke.
        """
        surface = {name for name in dir(AssistantEngine) if not name.startswith("_")}
        assert "start" not in surface
        assert "aclose" not in surface

    async def test_every_enumeration_returns_a_tuple(self, engine: AssistantEngine) -> None:
        """ADR-0085 §3b: a caller that mutated a returned page changed nothing.

        ``pending_confirmations`` is the one this pins: it returned a ``list``
        before, and a surface this size with one method returning a mutable
        page is a wart a spoke author has to remember.
        """
        assert isinstance(await engine.beliefs(), tuple)
        assert isinstance(await engine.questions(), tuple)
        assert isinstance(await engine.interrupted_questions(), tuple)
        assert isinstance(await engine.recent_conversations(), tuple)
        assert isinstance(await engine.pending_confirmations(), tuple)

    # --- clause 1: the page-size default is normative (§3a) ----------------

    @pytest.mark.parametrize(
        "method",
        ["beliefs", "questions", "interrupted_questions", "recent_conversations"],
    )
    def test_the_page_size_default_is_the_declared_one(
        self, engine: AssistantEngine, method: str
    ) -> None:
        """All four paging signatures default to ``DEFAULT_PAGE_SIZE``.

        Read off the signature rather than by counting a page, because the property
        is about what "not passed" *means*: an implementation whose own default were
        100 would return a different page for the same call, which is the divergence
        the limit was moved into the contract to prevent, arriving one field over.
        """
        parameter = inspect.signature(getattr(engine, method)).parameters["limit"]
        assert parameter.default == DEFAULT_PAGE_SIZE

    async def test_calling_without_a_limit_behaves_as_though_the_default_was_passed(
        self, engine: AssistantEngine
    ) -> None:
        """The clause itself, not merely the signature that advertises it."""
        assert await engine.beliefs() == await engine.beliefs(limit=DEFAULT_PAGE_SIZE)
        assert await engine.questions() == await engine.questions(limit=DEFAULT_PAGE_SIZE)
        assert await engine.interrupted_questions() == await engine.interrupted_questions(
            limit=DEFAULT_PAGE_SIZE
        )
        assert await engine.recent_conversations() == await engine.recent_conversations(
            limit=DEFAULT_PAGE_SIZE
        )

    # --- clause 2 and 4: identifiers (§3c, §9) -----------------------------

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    @pytest.mark.parametrize(
        "call",
        [
            "belief",
            "forget",
            "forget_question",
            "conversation",
            "forget_conversation",
        ],
    )
    async def test_a_blank_identifier_is_refused_locally(
        self, engine: AssistantEngine, call: str, blank: str
    ) -> None:
        """A blank id satisfies "an id is present" while identifying nothing.

        ``ValueError`` and deliberately not an
        :class:`~ai_assistant.core.errors.AssistantError`: it is a caller
        programming error rather than a condition of the system. Refused *before any
        I/O*, so a wire client refuses the same values without a round trip.
        """
        with pytest.raises(ValueError, match=r"\w"):
            await getattr(engine, call)(blank)

    async def test_a_blank_identifier_is_refused_on_the_keyword_selectors(
        self, engine: AssistantEngine
    ) -> None:
        """The two methods whose identifier is a keyword-only selector."""
        with pytest.raises(ValueError, match=r"\w"):
            await engine.converse("hello", timeout=_PATIENT, conversation_id="  ")
        with pytest.raises(ValueError, match=r"\w"):
            await engine.observe(conversation_id="  ")
        with pytest.raises(ValueError, match=r"\w"):
            await engine.answer("  ", accept=True)

    async def test_an_identifier_is_stripped_before_it_is_used(
        self, engine: AssistantEngine
    ) -> None:
        """§3c's load-bearing half: the *normalisation*, not only the refusal.

        A rule that said "reject blank" would leave stripping optional, and optional
        normalisation on an **identity** argument is worse than none: it makes the
        answer to ``belief(" rec-1 ")`` a property of which implementation you are
        holding. A wire client deserialising its arguments through ``Identifier``
        would find the record; an in-process engine handed the raw ``str`` would
        look up ``" rec-1 "`` and answer ``None``.
        """
        outcome = await engine.learn(_feedback("the office is in Boston"))
        record_id = outcome.results[0].record_id
        assert record_id is not None
        assert await engine.belief(f"  {record_id}  ") is not None

    @pytest.mark.parametrize("bad", [-1, 2**63])
    @pytest.mark.parametrize("argument", ["limit", "offset"])
    @pytest.mark.parametrize(
        "method", ["beliefs", "questions", "interrupted_questions", "recent_conversations"]
    )
    async def test_a_malformed_page_argument_is_refused_locally(
        self, engine: AssistantEngine, method: str, argument: str, bad: int
    ) -> None:
        """Refused rather than clamped (ADR-0073 §2), and before any I/O (§9)."""
        with pytest.raises(ValueError, match=r"\w"):
            await getattr(engine, method)(**{argument: bad})

    @pytest.mark.parametrize("bad", [1.5, True, "1", None])
    @pytest.mark.parametrize("argument", ["limit", "offset"])
    @pytest.mark.parametrize(
        "method", ["beliefs", "questions", "interrupted_questions", "recent_conversations"]
    )
    async def test_a_page_argument_that_is_not_an_integer_is_refused_locally(
        self, engine: AssistantEngine, method: str, argument: str, bad: object
    ) -> None:
        """The type, checked before the range and before any I/O.

        ``0 <= 1.5 < 2**63`` is *true*, so a range check alone lets a float through
        to the store, where it fails inside slice arithmetic — after I/O has begun,
        as a ``TypeError`` from somewhere the caller cannot place, and differently
        per implementation. ``True`` is worse: it is an ``int``, so it would be
        accepted and silently mean a page size of one, which is a wrong answer
        rather than a refusal.

        A wire client decoding a JSON ``1.5`` for ``limit`` meets the same value,
        which is why this is a contract clause and not one implementation's input
        hygiene.
        """
        with pytest.raises(TypeError, match=r"\w"):
            await getattr(engine, method)(**{argument: bad})

    # --- clause 3: the filters are materialised (§3d) ----------------------

    async def test_the_filters_are_materialised_before_the_first_await(
        self, engine: AssistantEngine
    ) -> None:
        """A caller that mutates the sequence mid-call cannot change its page (§3d).

        **The mutation has to land after the call has begun**, and getting that
        window right is the whole of the test. ADR-0065 is explicit that the
        boundary is "the coroutine's **first executed line**, not the call
        expression": calling an ``async def`` only builds a coroutine, so a
        mutation made between construction and the first ``await`` is captured
        whole and is *not* a tear — no invocation-time capture is claimed. So the
        call is scheduled and given a turn of the loop before the list is cleared,
        which puts the mutation squarely in the window §3d protects.

        An implementation that read ``bands`` after suspending would see the
        emptied list and return an empty page. :func:`page_after_mutating_the_filter`
        is shared with ``test_fake_engine``'s discrimination case, which runs it
        against a deliberately lazy subject and watches this assertion fail.
        """
        await engine.learn(_feedback("the office is in Boston"))
        page, control = await page_after_mutating_the_filter(engine)
        assert page == control

    async def test_an_empty_filter_selects_nothing_and_none_selects_everything(
        self, engine: AssistantEngine
    ) -> None:
        """ADR-0073 §2: ``None`` and empty are different answers, not one.

        The pair matters because a client serialising a ``None`` filter as an empty
        JSON array would turn "every band" into "no band" — a silently empty page
        for a call that asked for everything.
        """
        await engine.learn(_feedback("the office is in Boston"))
        assert await engine.beliefs(bands=[]) == ()
        assert await engine.beliefs(kinds=[]) == ()
        assert await engine.beliefs(bands=None, kinds=None) != ()

    # --- clause 5: the size limit, in both directions (§8c) ----------------

    async def test_an_oversized_argument_is_refused(self, tiny_engine: AssistantEngine) -> None:
        """The *going in* direction: refused before dispatch, with the number."""
        with pytest.raises(OversizedValueError) as caught:
            await tiny_engine.converse("x" * (_TINY_LIMIT * 4), timeout=_PATIENT)
        assert caught.value.limit == _TINY_LIMIT
        assert caught.value.size > _TINY_LIMIT
        assert caught.value.field == "utterance"

    async def test_an_oversized_result_is_refused(self, tiny_engine: AssistantEngine) -> None:
        """The *coming back* direction, which is the one ADR-0084 §4 insisted on.

        Without it a client is silently **more** capable than the engine it stands
        in for in one direction and less in the other: the in-process engine would
        hand a caller a value the wire client provably cannot deliver.

        **The argument object here is twelve bytes**, so nothing but the result can
        trip the limit: the page is built from beliefs each stored through a
        ``learn`` the bound comfortably admits, and then a listing whose whole
        request payload is ``{"offset":0}`` grows past it. An implementation that
        measured only its arguments passes every other case in this class and fails
        this one, which is the whole reason it is written this way round.

        ``field`` is ``None`` because a listing result is a bare JSON array with no
        member to name — ADR-0085 §9 says that case is reachable rather than
        defensive, and this is where it is reached.
        """
        for index in range(6):
            await tiny_engine.learn(_feedback(f"the office is in Boston, building {index}"))
        with pytest.raises(OversizedValueError) as caught:
            await tiny_engine.beliefs()
        assert caught.value.limit == _TINY_LIMIT
        assert caught.value.size > _TINY_LIMIT
        assert caught.value.field is None

    async def test_a_result_that_fits_is_returned(self, tiny_engine: AssistantEngine) -> None:
        """The discriminating half of the case above.

        One stored belief lists comfortably inside the bound, so the refusal above
        is about the page's size and not about ``beliefs()`` being refused
        unconditionally.
        """
        await tiny_engine.learn(_feedback("the office is in Boston"))
        assert len(await tiny_engine.beliefs()) == 1

    async def test_a_payload_inside_the_limit_is_admitted(
        self, tiny_engine: AssistantEngine
    ) -> None:
        """The limit refuses what it must and nothing else — the discriminating half.

        Without this, an implementation that refused *every* call would pass the two
        assertions above.
        """
        assert await tiny_engine.beliefs() == ()
        assert await tiny_engine.forget("no-such-record") is False

    async def test_the_refusal_names_the_limit_and_the_measured_size(
        self, tiny_engine: AssistantEngine
    ) -> None:
        """ADR-0085 §9: "too large" without a number is not actionable."""
        with pytest.raises(OversizedValueError) as caught:
            await tiny_engine.belief("z" * (_TINY_LIMIT * 4))
        assert caught.value.limit == _TINY_LIMIT
        assert caught.value.size == pytest.approx(caught.value.size)
        assert caught.value.field == "record_id"

    # --- §4a: the listing cannot ship the corpus ---------------------------

    async def test_the_listing_returns_summaries_and_carries_no_citation(
        self, engine: AssistantEngine
    ) -> None:
        """ADR-0077 §6's split, made structural (§4a).

        The listing "resolves *existence* and renders the count, the lost count, and
        the adjusted confidence"; the single-belief view "renders the surviving
        citations as readable evidence". This is the shape where the wrong behaviour
        is **unrepresentable** rather than merely detectable: a
        :class:`~ai_assistant.core.types.BeliefSummary` has nowhere to put a
        citation's content, so a conforming listing cannot over-deliver.
        """
        await engine.learn(_feedback("the office is in Boston"))
        page = await engine.beliefs()
        assert page
        for summary in page:
            assert isinstance(summary, BeliefSummary)
            assert not hasattr(summary, "evidence")

    async def test_the_same_three_names_read_alike_on_both_belief_types(
        self, engine: AssistantEngine
    ) -> None:
        """§4a's table: only the *category* of two of them changes, never the answer.

        That is what keeps a renderer from needing two code paths, and it is the
        reason ``unsupported`` stays derived on both — a field there would put a
        value on the wire a client can compute exactly, so one implementation could
        send it and another omit it, and the same call would measure two sizes.
        """
        outcome = await engine.learn(_feedback("the office is in Boston"))
        record_id = outcome.results[0].record_id
        assert record_id is not None
        summary = next(one for one in await engine.beliefs() if one.id == record_id)
        detail = await engine.belief(record_id)
        assert detail is not None
        assert summary.evidence_count == detail.evidence_count
        assert summary.lost_evidence == detail.lost_evidence
        assert summary.unsupported == detail.unsupported

    # --- ADR-0074 §1: an unknown conversation is refused, never started -----

    async def test_an_unknown_conversation_is_refused_rather_than_started(
        self, engine: AssistantEngine
    ) -> None:
        """ADR-0074 §1: refused, **not silently started**.

        Silently starting one turns a typo or a stale copy-paste into "my
        conversation vanished" and lands the user's continuation somewhere they
        cannot find. It is asserted of every implementation because a stand-in that
        started one instead would let a client's tests pass over the exact path the
        engine refuses — which is the substitutability this Protocol exists for,
        failing in the direction nobody looks.
        """
        with pytest.raises(UnknownConversationError):
            await engine.converse("hello", timeout=_PATIENT, conversation_id="no-such-id")
        with pytest.raises(UnknownConversationError):
            await engine.observe(conversation_id="no-such-id")

    async def test_a_turn_with_no_conversation_named_runs_in_one_it_minted(
        self, engine: AssistantEngine
    ) -> None:
        """The other side of the same rule: passing no id starts a conversation.

        Every turn runs under one and the outcome reports which (ADR-0074 §2),
        because a stateless client cannot keep it otherwise.
        """
        outcome = await engine.converse("hello", timeout=_PATIENT)
        assert outcome.conversation_id is not None
        continued = await engine.converse(
            "and again", timeout=_PATIENT, conversation_id=outcome.conversation_id
        )
        assert continued.conversation_id == outcome.conversation_id

    # --- ADR-0173 §4: the streaming turn call --------------------------------

    async def test_a_streamed_turn_ends_on_exactly_one_outcome(
        self, engine: AssistantEngine
    ) -> None:
        """§4: "zero or more chunks, then **exactly one** ``TurnOutcome``".

        Asserted of every implementation because the terminal value is what §3 makes
        authoritative: a stand-in that yielded two outcomes, or none, would leave a
        client either choosing between answers or holding none — and both are states
        the union's one-to-one map onto the frames is supposed to make unreachable.
        """
        produced = await _drain(engine.converse_streaming("hello", timeout=_PATIENT))
        assert produced, "a streamed turn yields at least its outcome"
        assert isinstance(produced[-1], TurnOutcome)
        assert all(isinstance(value, ReplyChunk) for value in produced[:-1])

    async def test_the_terminal_reply_is_the_join_of_the_chunks(
        self, engine: AssistantEngine
    ) -> None:
        """§3: where the exchange streamed chunks, ``reply`` is what they conveyed.

        "Joined in the order they were written" — so a chunk-reading client and a
        chunk-ignoring one hold the same answer, which is the whole reason §3 makes
        the terminal frame authoritative rather than the sequence. An implementation
        whose chunks say something the outcome does not repeat fails here.
        """
        produced = await _drain(engine.converse_streaming("hello", timeout=_PATIENT))
        outcome = produced[-1]
        assert isinstance(outcome, TurnOutcome)
        joined = "".join(value.text for value in produced[:-1] if isinstance(value, ReplyChunk))
        assert joined == (outcome.reply or "")

    async def test_a_streamed_turn_reports_the_conversation_it_ran_under(
        self, engine: AssistantEngine
    ) -> None:
        """§8: resume is carried identically — the same argument, the same id back.

        The milestone's own exit test is a *resumed* streamed turn, and ADR-0173 §8
        adds no history parameter and no second read to reach it: a second stream
        under the id the first returned continues that conversation.
        """
        first = await _outcome_of(engine.converse_streaming("hello", timeout=_PATIENT))
        assert first.conversation_id is not None
        second = await _outcome_of(
            engine.converse_streaming(
                "and again", timeout=_PATIENT, conversation_id=first.conversation_id
            )
        )
        assert second.conversation_id == first.conversation_id

    async def test_a_streamed_turn_refuses_an_unknown_conversation(
        self, engine: AssistantEngine
    ) -> None:
        """§4: "subject to every clause ``converse`` declares", refusals included.

        ADR-0074 §1's refusal is the one a streaming twin is most likely to lose,
        because it sits behind an iterator a lazy implementation never starts. So it
        is asserted by *driving* the iterator, which is what the Protocol tells a
        caller to do.
        """
        with pytest.raises(UnknownConversationError):
            await _outcome_of(
                engine.converse_streaming("hello", timeout=_PATIENT, conversation_id="no-such-id")
            )

    async def test_a_streamed_turn_refuses_a_blank_conversation_id_locally(
        self, engine: AssistantEngine
    ) -> None:
        """ADR-0085 §9 on the streaming entry: refused **before any I/O**.

        A refusal an implementation deferred into the iteration would still raise,
        so this asserts the stronger thing the clause actually says: the call itself
        raises, before anything is driven.
        """
        with pytest.raises(ValueError, match="conversation_id"):
            engine.converse_streaming("hello", timeout=_PATIENT, conversation_id="   ")

    async def test_a_streamed_turn_measures_its_arguments_like_the_whole_one(
        self, tiny_engine: AssistantEngine
    ) -> None:
        """Clause 5 on the streaming entry, in the argument direction.

        ADR-0173 §11 restates ADR-0085 §8c for a method with no single result, and
        the *argument* half is unchanged — so an utterance the whole call refuses is
        one the streaming call refuses too, and by the same class.

        **Driven rather than merely called**, unlike the blank-identifier case
        above, and the difference is ADR-0084 §3's rather than this suite's: the
        limit a client enforces is "the number it was told", which arrives in the
        handshake. A wire implementation cannot measure before it has connected, so
        requiring the refusal *from the call* would require it to be more eager than
        the contract is. A blank identifier needs no such knowledge, which is why
        ADR-0085 §9 puts that one before any I/O and not this one.
        """
        with pytest.raises(OversizedValueError):
            await _drain(tiny_engine.converse_streaming("x" * (_TINY_LIMIT + 1), timeout=_PATIENT))

    async def test_a_streamed_turn_is_closable_part_way(self, engine: AssistantEngine) -> None:
        """§4: a caller that stops reading closes, and closing must be supported.

        The clause obliges the *caller* to close, which is only meaningful if every
        implementation's iterator can be closed — and a client across a transport is
        where that is easiest to get wrong, since closing has a connection to hang
        up rather than a generator to finish.
        """
        stream = engine.converse_streaming("hello", timeout=_PATIENT)
        async with closing_stream(stream) as values:
            assert await anext(values) is not None

    # --- ADR-0078 §8: only an open question is answerable --------------------

    async def test_a_question_that_is_not_open_answers_not_open(
        self, engine: AssistantEngine
    ) -> None:
        """Rendering a non-open answer as anything else would claim a write.

        "That question is not open — absent, lapsed, already being answered, or
        already answered. Nothing was written." An id naming nothing is the case
        every implementation can be held to without seeding a queue.
        """
        outcome = await engine.answer("no-such-question", accept=True)
        assert outcome.kind is AnswerKind.NOT_OPEN
        assert outcome.record_id is None

    # --- ADR-0084 §7: an unresolvable token is its own refusal --------------

    async def test_an_unknown_continuation_is_its_own_typed_refusal(
        self, engine: AssistantEngine
    ) -> None:
        """Never a generic failure, and **never a denial** (ADR-0084 §7).

        An unresolvable token means nobody ruled on the action;
        :class:`~ai_assistant.core.errors.PermissionDeniedError` means somebody did
        and said no. Reporting one as the other tells a user their action was
        refused when it was merely forgotten — and the remedy differs: this one is
        answered by ``pending_confirmations()`` and a fresh token.
        """
        with pytest.raises(UnknownContinuationError):
            await engine.resume(
                ContinuationToken(handle="not-a-real-handle"), approved=True, timeout=_PATIENT
            )

    # --- ADR-0042 §4 and ADR-0052 §1: park, render, relay --------------------

    async def test_a_parked_egress_confirmation_carries_what_the_ruling_was_taken_over(
        self, parked_engine: AssistantEngine
    ) -> None:
        """ADR-0178 §1, §2: the content ADR-0148 §8's fourth clause requires.

        The connected account's identity and the binding's payload description,
        reaching the adapter as one member rather than four — a value that is
        either whole or absent, so a surface can never hold recipients and no
        account, or an account and no description.

        **Whole, not merely present.** The identity renders as something, the
        derived set is non-empty, and the excluded values are absent by
        construction: :class:`ConfirmationEgress` declares two fields and neither
        is a connection reference, a transport endpoint or a whole
        ``BoundAccount``.
        """
        pending = await parked_engine.pending_confirmations()
        assert len(pending) == 1
        egress = pending[0].egress
        assert egress is not None, "the fixture parks an egress call (ADR-0178 §3)"
        assert egress.account_identity.strip()
        assert egress.canonical_destination_set

    async def test_a_parked_confirmations_destination_set_is_the_bindings_own(
        self, parked_engine: AssistantEngine
    ) -> None:
        """ADR-0178 §3's correspondence, over any producer of the member.

        Two computations of one rule and no second rule: the set a confirmation
        derives corresponds member for member and **in the same order** to the set
        :attr:`~ai_assistant.core.types.EgressBinding.canonical_destination_set`
        derives from the same spans and account, the two differing only in that the
        account member carries the identity here and the whole ``BoundAccount``
        there.

        The binding is rebuilt here from the confirmation's *own* occurrences and
        identity, which is what makes the clause checkable from the surface at all:
        an adapter may not read a ``PermissionDecision`` (ADR-0042 §6), so the
        binding itself never crosses. The rebuilt account's ``reference`` is
        arbitrary and cannot affect the comparison — the account arm is a member
        only where the spans carry no destination, in which case it is the whole
        set.
        """
        pending = await parked_engine.pending_confirmations()
        egress = pending[0].egress
        assert egress is not None
        rebuilt = EgressBinding(
            spans=egress.spans,
            account=BoundAccount(identity=egress.account_identity, reference="conn-rebuilt"),
            transport_endpoint="test://rebuilt",
            planned_with_external_content=egress.planned_with_external_content,
        )

        ours = egress.canonical_destination_set
        theirs = rebuilt.canonical_destination_set
        assert len(ours) == len(theirs)
        for mine, other in zip(ours, theirs, strict=True):
            assert mine.protocol == other.protocol
            assert mine.canonical == other.canonical
            assert mine.account_identity == (
                None if other.account is None else other.account.identity
            )

    async def test_a_park_is_recovered_with_a_token_that_resolves(
        self, parked_engine: AssistantEngine
    ) -> None:
        """ADR-0052 §1's enumerate-and-re-mint, held over both implementations.

        The confirmation carries what a person needs to judge the action — the
        tool, what it does, the parameters it would run with, and the policy's own
        reason for asking — because the adapter may read neither the audit trail
        nor a ``PermissionDecision`` to recover any of it (ADR-0042 §6).
        """
        pending = await parked_engine.pending_confirmations()
        assert len(pending) == 1
        assert pending[0].reason
        assert pending[0].tool_description
        resumed = await parked_engine.resume(pending[0].token, approved=True, timeout=_PATIENT)
        assert resumed.step is not None

    async def test_a_resume_always_carries_its_resolved_step(
        self, parked_engine: AssistantEngine
    ) -> None:
        """ADR-0085 §4: the step is what a resume is *for*, so it is never ``None``.

        ``turn`` may legitimately be absent — a park recovered from durable state
        after a restart has no live turn, and fabricating one would misrepresent
        what the turn saw (ADR-0052 §3) — which is exactly why the step cannot be.
        A client handed neither has nothing to render.

        ``step_id`` names the plan step the pass drove, which is what turns "read
        ``state`` too" from advice into an addressable operation (ADR-0084 §8).
        """
        pending = await parked_engine.pending_confirmations()
        resumed = await parked_engine.resume(pending[0].token, approved=True, timeout=_PATIENT)
        assert resumed.step is not None
        assert resumed.step.step_id
        named = [
            execution
            for execution in resumed.step.state.steps
            if execution.step_id == resumed.step.step_id
        ]
        assert len(named) == 1, "step_id must address exactly one execution record"

    async def test_a_refusal_is_a_result_and_not_an_exception(
        self, parked_engine: AssistantEngine
    ) -> None:
        """ADR-0042 §4: only ``approved=False -> DENY`` is guaranteed, and DENY is a *ruling*.

        "The adapter conveys consent; the policy rules on it; the engine records and
        executes." A denial is therefore a
        :attr:`~ai_assistant.core.types.Disposition.DENIED` disposition in the
        outcome, never a raised
        :class:`~ai_assistant.core.errors.PermissionDeniedError` — an implementation
        that raised would hand a client a failure path the in-process engine does
        not have, and the CLI renders the outcome rather than catching anything.
        """
        pending = await parked_engine.pending_confirmations()
        resumed = await parked_engine.resume(pending[0].token, approved=False, timeout=_PATIENT)
        assert resumed.step is not None
        assert resumed.step.disposition is Disposition.DENIED
        assert resumed.step.confirmation is None

    # --- ADR-0197 §7 and §13: the routed resume, and how narrow it is --------

    async def test_a_routed_park_resumed_yes_performs_its_operation(
        self, routed_park: RoutedParkSubject
    ) -> None:
        """ADR-0197 §7: the operation runs only on a ``resume`` whose ``approved`` is ``True``.

        Three assertions, and each is one of the three respects §7 says a routed resume
        differs in. ``step`` is ``None`` and ``routed`` is present, which is ADR-0197 §8's
        mutual exclusion read from the resume end and the half ADR-0052 §3's "the step …
        is always present" no longer reaches. And the operation was **performed**, which
        is what makes the first two facts about a resume that did something rather than
        about a shape.

        The effect is read through the promoted surface rather than through a double, so
        the same case binds an in-process engine, a fake and a client over a socket: a
        destroyed belief is one ``belief`` no longer answers.
        """
        assert await routed_park.engine.belief(routed_park.belief_id) is not None

        resumed = await routed_park.engine.resume(
            routed_park.token, approved=True, timeout=_PATIENT
        )

        assert resumed.step is None
        assert resumed.routed is not None
        assert resumed.routed.outcome is RouteOutcome.PERFORMED
        assert resumed.turn is None
        assert await routed_park.engine.belief(routed_park.belief_id) is None

    async def test_a_routed_park_resumed_no_returns_its_refusal_and_performs_nothing(
        self, routed_park: RoutedParkSubject
    ) -> None:
        """ADR-0197 §7, §13: the refusal is **returned, never raised**.

        ``approved`` ``False`` yields ``RouteOutcome.REFUSED`` on that member and **no**
        :class:`~ai_assistant.core.errors.PermissionDeniedError`, because no
        ``ActionPolicy`` is consulted and no ``PermissionDecision`` is recorded — so
        there is no ruling for a refusal to *be*. That is ADR-0197 §13's partial
        supersession of ADR-0042 §4's "only ``approved=False → DENY`` is guaranteed",
        scoped to exactly this case.

        The ruling count is the assertion that separates "returned a refusal" from "ruled
        a denial and reported it": an implementation that ran the routed park through the
        permission layer would satisfy every other line here and leave a decision behind.
        """
        before = len(await routed_park.engine.export_decisions())

        resumed = await routed_park.engine.resume(
            routed_park.token, approved=False, timeout=_PATIENT
        )

        assert resumed.routed is not None
        assert resumed.routed.outcome is RouteOutcome.REFUSED
        assert resumed.step is None
        assert await routed_park.engine.belief(routed_park.belief_id) is not None
        assert len(await routed_park.engine.export_decisions()) == before

    async def test_a_routed_park_is_answered_once(self, routed_park: RoutedParkSubject) -> None:
        """ADR-0197 §7: one park yields one answer and at most one operation.

        The park is **claimed** before anything is performed, and the claim is what evicts
        it — so a second presentation of the token, whatever its ``approved`` value,
        resolves nothing and raises ``UnknownContinuationError``. Never a denial: nobody
        ruled on this action (ADR-0084 §7), and a routed park's unknown, expired,
        already-claimed and cross-restart token each yield the same refusal.
        """
        await routed_park.engine.resume(routed_park.token, approved=False, timeout=_PATIENT)

        with pytest.raises(UnknownContinuationError):
            await routed_park.engine.resume(routed_park.token, approved=True, timeout=_PATIENT)

    async def test_a_routed_park_is_not_listed_among_pending_confirmations(
        self, routed_park: RoutedParkSubject
    ) -> None:
        """ADR-0197 §7: ``pending_confirmations`` does **not** list a routed park.

        Refused rather than merely omitted, and §7 says why: an enumeration would have to
        render the card again, and §7's card is engine-assembled from a resolution the
        process still holds. What a lost routed park costs is one repeated sentence —
        nothing has happened yet — and that is stated as the trade rather than hidden.

        The listing's element type is the other half of the reason: ``pending_confirmations``
        answers ``Confirmation`` values, whose four content members are tool-shaped, and a
        routed act has no tool and no policy ruling to fill three of them with.
        """
        assert await routed_park.engine.pending_confirmations() == ()

    async def test_an_ordinary_parked_step_is_ruled_exactly_as_before(
        self, parked_engine: AssistantEngine
    ) -> None:
        """The case that pins ADR-0197 §13's supersession as **narrow** rather than general.

        Beside the two routed cases above, and "not decoration": without it the suite pins
        the new behaviour and not its scope, and an implementation that stopped carrying a
        step on *every* refusal would pass. A ``resume`` continuing a parked step still
        carries its ``step``, still carries no ``routed``, and is ruled exactly as ADR-0052
        §3 and ADR-0042 §4 ruled it.

        **ADR-0197 §12 writes this case as "still raises ``PermissionDeniedError``", and
        ADR-0197's own amendment of 2026-08-27 corrects it.** §7's "and to raise
        ``PermissionDeniedError`` exactly as it does today" is a description of the tree
        rather than a decision, and the tree returns a ruling: ADR-0042 §4 makes a denial a
        ``DENY`` *ruling* — "the adapter conveys consent; the policy rules on it; the
        engine records and executes" — and
        :meth:`test_a_refusal_is_a_result_and_not_an_exception` has pinned the consequence
        against every implementation since ADR-0084. §13's record on ADR-0042 is what
        leaves that guarantee whole here: it supersedes §4 **only** "as it reaches a resume
        answering a routed park".

        So this case pins the three facts the corrected reading leaves: the outcome still
        carries a ``step``, it carries **no** ``routed`` member, and **nothing is raised** —
        the last asserted by the call standing unwrapped, since a
        :class:`~ai_assistant.core.errors.PermissionDeniedError` here would fail the case
        outright. What the refusal *produces* stays the older case's to pin, which is what
        keeps this one about the **scope**: without it the suite would pin the new
        behaviour and not its narrowness, and an implementation that stopped carrying a
        step on **every** refusal would pass.
        """
        pending = await parked_engine.pending_confirmations()

        # Unwrapped deliberately: this call raising is the failure the case exists to
        # catch, so no `pytest.raises` may stand between it and the assertions below.
        resumed = await parked_engine.resume(pending[0].token, approved=False, timeout=_PATIENT)

        assert resumed.step is not None
        assert resumed.routed is None

    # --- ADR-0198 §§1-5: a settled park is restated, not refused -------------

    async def test_a_settled_token_restates_its_answer_rather_than_being_refused(
        self, settled_park: SettledParkSubject
    ) -> None:
        """ADR-0198 §§1-2: the replay is answered, and this is what it carries.

        **This case replaces the one that pinned the opposite**, and the reason the
        old ruling fell is the remedy rather than the refusal. ADR-0084 §7 gives a
        token the server cannot resolve one typed error whose remedy is
        ``pending_confirmations()`` — enumerate durable state and re-mint — and gives
        it *because* "the client's remedy is identical in both cases". A replay fails
        that test: ADR-0052 §1 step 2 skips a binding the trail no longer holds
        pending, so a settled binding is never listed and never re-minted, and a
        client told to enumerate finds an empty listing and cannot tell "my answer
        landed" from "the park is gone". So where the remedies diverge the engine
        answers instead of refusing.

        The shape asserted here is ADR-0170 §4's second one exactly, which §2 obeys
        rather than widens: ``turn`` ``None`` — even where the settled park was an
        in-process one, because retaining a ``TurnResult`` would keep a turn's context
        and memories alive for the life of the record and show a caller a turn this
        call did not drive — ``routed`` ``None``, ``reply`` ``None`` because the answer
        was composed once for the request that performed the act, and
        ``reply_degraded`` ``False`` because no answer was owed. The ``step`` carries
        the binding's immutable facts and a ``confirmation`` of ``None``, which the
        type's own validator already requires of a disposition that is not
        ``AWAITING_CONFIRMATION``.
        """
        restated = await settled_park.engine.resume(
            settled_park.token, approved=True, timeout=_PATIENT
        )

        assert restated.step is not None
        assert restated.step.disposition is Disposition.EXECUTED
        assert restated.step.confirmation is None
        assert restated.step.tool_id is not None
        assert restated.turn is None
        assert restated.routed is None
        assert restated.reply is None
        assert restated.reply_degraded is False

    async def test_a_restatement_performs_nothing_however_often_it_is_asked(
        self, settled_park: SettledParkSubject
    ) -> None:
        """ADR-0198 §3: one settled binding, one ruling and one execution attempt.

        The half of the pair that keeps the first case honest. Answering a replay is
        worth nothing — worse than the refusal it replaced — if answering it *does*
        anything: a second ``PermissionDecision`` would put two rulings under one
        binding that ADR-0044 §2b makes unrepeatable, and a second invocation would
        perform an act the user authorised once.

        Both are read through the promoted surface, so the same case binds an
        in-process engine, a fake and a client over a socket. The rows are compared
        against what the trail held **after the first resolution** rather than against
        a fixed count, because what §3 rules is that a restatement adds nothing — how
        many rows a conforming implementation records for the resolution itself is its
        own business, and a case asserting a number would be pinning one
        implementation's book-keeping on all three.

        The execution attempt is read off the restated ``state`` for the same reason:
        the step the settled binding names ran once, and a second run would show as a
        second attempt whatever else an implementation recorded.
        """
        rulings = await settled_park.engine.export_decisions()
        invocations = await settled_park.engine.export_invocations()

        first = await settled_park.engine.resume(
            settled_park.token, approved=True, timeout=_PATIENT
        )
        second = await settled_park.engine.resume(
            settled_park.token, approved=True, timeout=_PATIENT
        )

        assert await settled_park.engine.export_decisions() == rulings
        assert await settled_park.engine.export_invocations() == invocations
        assert first.step is not None
        assert second.step is not None
        assert second.step.disposition is first.step.disposition
        assert second.step.state.step(second.step.step_id) is not None
        assert second.step.state.step(second.step.step_id).attempts <= 1  # type: ignore[union-attr]

    async def test_a_restatement_is_returned_whatever_the_replay_s_approved_carries(
        self, settled_park: SettledParkSubject
    ) -> None:
        """ADR-0198 §1: the second ``approved`` is not compared against the first.

        The fixture answered the park with ``True``; this presents the **opposite**
        value. A park is answered once (ADR-0044 §2b), so a second answer is never
        honourable whatever it says, and the engine states what was decided rather
        than refusing to say — the recorded answer stands unchanged, and nothing about
        the contradicting call is recorded, performed or composed.

        **This is the clause an implementation is likeliest to narrow** to "the same
        answer twice", and every other case in this section passes under that
        narrowing because each of them presents one value twice. Without it, an engine
        that raised a second typed error on a disagreement would be conforming — and
        that shape is refused in ADR-0198's own ``Alternatives considered``, on the
        ground that an error tells a caller the binding was answered and never tells
        it *how*, while the token is opaque and the listing will not carry it, so the
        caller has no other way to ask.
        """
        rulings = await settled_park.engine.export_decisions()
        invocations = await settled_park.engine.export_invocations()

        restated = await settled_park.engine.resume(
            settled_park.token, approved=False, timeout=_PATIENT
        )

        assert restated.step is not None
        assert restated.step.disposition is Disposition.EXECUTED
        assert restated.reply is None
        assert restated.reply_degraded is False
        assert await settled_park.engine.export_decisions() == rulings
        assert await settled_park.engine.export_invocations() == invocations

    async def test_two_concurrent_resumes_of_one_token_both_get_the_settled_answer(
        self, settled_park: SettledParkSubject
    ) -> None:
        """ADR-0198 §1, §7: the race this decision exists to close, pinned.

        **The sequential cases cannot see it.** #1621's mechanism is a recovery
        listing overtaking a resume: an abandoned answer is still in transit, a
        listing that reaches the lock first legitimately returns the park as pending,
        and a second ``resume`` then races the first — whichever reaches the
        resolution first decides the park, and the loser used to raise. The gateway
        renders every ``AssistantError`` as a decline, which a browser reads as "the
        hub received the request and declined it": a denial announced for an action
        that ran, which ADR-0084 §7 refuses in terms.

        So both calls must come back with the one settled outcome and neither may
        raise. An implementation that installs the settled record **after** releasing
        the critical section — or evicts before installing — fails this
        deterministically, because the second call reaches the table between the two
        and finds nothing.

        **No consumer is exempted** (§7). This suite offers no capability skip, and
        the wire client opens one connection per call, so two concurrent ``resume``
        calls engage ADR-0084 §3's serial-connection rule not at all.
        """
        rulings = await settled_park.engine.export_decisions()

        first, second = await asyncio.gather(
            settled_park.engine.resume(settled_park.token, approved=True, timeout=_PATIENT),
            settled_park.engine.resume(settled_park.token, approved=False, timeout=_PATIENT),
        )

        assert first.step is not None
        assert second.step is not None
        assert first.step.disposition is Disposition.EXECUTED
        assert second.step.disposition is Disposition.EXECUTED
        assert first.step.step_id == second.step.step_id
        assert await settled_park.engine.export_decisions() == rulings

    async def test_a_restatement_reads_the_execution_and_refuses_to_state_what_it_cannot(
        self, settled_park_without_its_execution: SettledParkSubject
    ) -> None:
        """ADR-0198 §2: ``state`` is re-read, and an unreadable outcome is not stated.

        The subject's settled binding names an execution the plan store no longer
        holds. Presenting its token raises
        :class:`~ai_assistant.core.errors.PlanningError` — the same failure a
        *resolution* raises for the same condition — and the engine asserts nothing
        about the outcome, which is ADR-0139 §4's third limb arriving at the engine
        seam.

        **Without this an implementation that cached the ``StepOutcome`` at settlement
        passes every other case in this section** and answers with an
        ``ExecutionState`` the store has stopped holding. ``StepOutcome.state`` is
        defined as "the durable execution state after the last transition committed",
        and a cached value stops being that the moment anything else advances the
        execution; the ``Disposition`` beside it cannot go stale, because it is the
        gate's verdict on a decision ADR-0044 §2b makes unrepeatable, which is why one
        is read and the other retained.

        It reaches no runner, policy, tool or composer either, and the trail is the
        control that says so.
        """
        subject = settled_park_without_its_execution
        rulings = await subject.engine.export_decisions()
        invocations = await subject.engine.export_invocations()

        with pytest.raises(PlanningError):
            await subject.engine.resume(subject.token, approved=True, timeout=_PATIENT)

        assert await subject.engine.export_decisions() == rulings
        assert await subject.engine.export_invocations() == invocations

    async def test_retention_holds_no_ceiling_slot_and_discards_the_least_recently_settled(
        self, single_slot_parks: SingleSlotParkSubject
    ) -> None:
        """ADR-0198 §4: the bound is a count, it is the ceiling, and the oldest goes.

        Three facts over one subject built at :data:`SETTLED_SINGLE_SLOT`.

        **A settled record holds no slot at the ceiling.** That ceiling bounds
        *unanswered* parks, and a settled record is the opposite of one — counting it
        would let a client that answered every confirmation meet backpressure for
        having done so. The evidence is that the subject exists: at a ceiling of one,
        the second park could not have been admitted beside the first's retained
        record if that record occupied the slot. The first assertion below reads the
        other half of it, that the older record really is still retained at that
        point.

        **The retained set is bounded by the same number**, and **the discard is the
        least recently settled**. Settling the second binding fills the one place the
        set has, so the older token stops restating and meets
        ``UnknownContinuationError`` again — which is the behaviour every replay had
        before this decision, so the bound narrows the improvement and regresses
        nothing — while the newer one restates. An implementation that retained every
        record forever fails the third assertion; one that discarded the newest fails
        the fourth.

        Note what the first two calls establish before anything is crowded out: a
        restatement is a **read**, and it does not re-settle the record it reads. Were
        it to, the recency order these assertions depend on would be a different one.
        """
        engine = single_slot_parks.engine

        retained = await engine.resume(single_slot_parks.settled, approved=True, timeout=_PATIENT)
        assert retained.step is not None

        answered = await engine.resume(single_slot_parks.parked, approved=True, timeout=_PATIENT)
        assert answered.step is not None

        with pytest.raises(UnknownContinuationError):
            await engine.resume(single_slot_parks.settled, approved=True, timeout=_PATIENT)

        restated = await engine.resume(single_slot_parks.parked, approved=True, timeout=_PATIENT)
        assert restated.step is not None
        assert restated.step.step_id == answered.step.step_id

    async def test_a_settled_binding_is_not_listed_among_pending_confirmations(
        self, settled_park: SettledParkSubject
    ) -> None:
        """ADR-0198 §4: recovery neither lists a settled binding nor mints for one.

        ADR-0052 §1 step 2 skips a binding the trail no longer holds pending and that
        skip is unchanged, so a settled binding is never re-presented — which is the
        #257 hazard ADR-0044 §2b closes. It is also the reason the restatement had to
        be a ``resume`` rather than a listing: a listing that carried settled bindings
        would put a resolved action back in front of a user in the type whose whole
        purpose is "what you may still answer".

        The token still restates afterwards, which is what separates "not listed" from
        "reconciled away": an implementation whose recovery evicted the settled record
        as though it were a park would pass the first assertion and fail the second.
        """
        assert await settled_park.engine.pending_confirmations() == ()

        restated = await settled_park.engine.resume(
            settled_park.token, approved=True, timeout=_PATIENT
        )
        assert restated.step is not None

    # --- ADR-0074 §2: the listing is ordered by activity ---------------------

    async def test_conversations_are_listed_by_activity_and_not_by_last_turn(
        self, engine: AssistantEngine
    ) -> None:
        """Most recently active first, and the key is never "has a turn landed".

        Ordering by the latter would sink a conversation the user opened a minute
        ago below one they abandoned last week. It is held over every
        implementation because a stand-in that returned insertion order would let a
        client's ordering tests pass while production rendered stale conversations
        first — the failure is invisible until someone looks at a real listing.
        """
        first = (await engine.converse("one", timeout=_PATIENT)).conversation_id
        second = (await engine.converse("two", timeout=_PATIENT)).conversation_id
        assert first is not None
        assert second is not None
        assert [one.id for one in await engine.recent_conversations()] == [second, first]

        await engine.converse("again", timeout=_PATIENT, conversation_id=first)
        listed = await engine.recent_conversations()
        assert [one.id for one in listed] == [first, second]
        assert listed[0].last_active_at >= listed[1].last_active_at

    # --- forgetting something absent is not an error ------------------------

    async def test_forgetting_what_is_not_held_reports_false_rather_than_raising(
        self, engine: AssistantEngine
    ) -> None:
        """The user's intent — "let this not be held" — is already satisfied."""
        assert await engine.forget("no-such-record") is False
        assert await engine.forget_question("no-such-question") is False
        assert await engine.forget_conversation("no-such-conversation") is False

    async def test_reading_what_is_not_held_answers_none(self, engine: AssistantEngine) -> None:
        """An optional getter answers ``None``; it does not invent a record."""
        assert await engine.belief("no-such-record") is None
        assert await engine.conversation("no-such-conversation") is None

    # --- clause 6: an error's structured state survives (§10a) --------------

    def test_every_error_s_structured_state_round_trips_through_its_constructor(self) -> None:
        """ADR-0085 §10a, over **every** subtype rather than over a list of two.

        The wire reconstructs a declared failure "by calling the named type with the
        message positionally and the ``details`` members as keyword arguments", and
        ``details`` is "the exception's public attributes whose names match its
        constructor's keyword parameters". An attribute the constructor will not
        accept back under the same name breaks reconstruction, and nothing else
        would catch it.

        Walked rather than enumerated: ADR-0085 §4c's own lesson is that a field
        list rots and a rule survives, and a table of error types here would go
        stale the first time a structured error is added.
        """
        for name, kind in vars(error_module).items():
            if not (isinstance(kind, type) and issubclass(kind, AssistantError)):
                continue
            initialiser = kind.__init__
            if initialiser is AssistantError.__init__ or initialiser is object.__init__:
                continue  # carries a message and nothing else, so it sends no details
            if not _takes_a_message(initialiser):
                # §10a reconstructs "by calling the named type with the message
                # positionally", so a subtype whose initialiser takes no message
                # is not a failure that rule can reach at all. §9 gives the test
                # for which those are: the ones "no Protocol method declares".
                # ADR-0032 §1's `ClassifiedToolError` is the case — a carrier
                # `ToolInvoker.invoke` translates into a `ToolResult`, and which
                # "never escapes `invoke`", so nothing can hand one to the wire.
                #
                # **Asserted rather than skipped**, which is what keeps this a
                # rule rather than the stale table the docstring warns about: the
                # moment a Protocol method declares such a type, it owes §10a's
                # reconstructable shape and this fails until it has one.
                assert name not in _protocol_declarations(), (
                    f"{name} is named in core/protocols.py but its initialiser takes no "
                    f"message, so ADR-0085 §10a could not reconstruct it across the wire"
                )
                continue
            parameters = [
                parameter
                for parameter in inspect.signature(initialiser).parameters.values()
                if parameter.name not in {"self", "message"}
            ]
            sample = {parameter.name: _sample_for(parameter.name) for parameter in parameters}
            original = kind("the failure", **sample)
            details = {
                attribute: getattr(original, attribute)
                for attribute in sample
                if attribute != "details_elided"
            }
            rebuilt = kind("the failure", **details)
            for attribute in details:
                assert getattr(rebuilt, attribute) == getattr(original, attribute), (
                    f"{name}.{attribute} does not survive its own constructor"
                )

    def test_details_elided_is_false_on_every_in_process_raise(self) -> None:
        """ADR-0085 §10a: nothing elides in-process, so the marker is never set.

        It exists so a client whose reconstruction lost an exception's structured
        state can say so: ``unresolved_ids`` defaults to ``()``, so a reconstructed
        :class:`~ai_assistant.core.errors.UnresolvedEvidenceError` **without** the
        flag would tell a caller that nothing was unresolved at the exact moment
        that too much was.
        """
        assert UnresolvedEvidenceError("gone", ["a", "b"]).details_elided is False
        assert OversizedValueError("too big", limit=1, size=2, field=None).details_elided is False
        elided = UnresolvedEvidenceError("gone")
        elided.details_elided = True
        assert elided.unresolved_ids == ()
        assert elided.details_elided is True

    @pytest.mark.parametrize(
        "build",
        [
            lambda: AssistantError("bad \ud800"),
            lambda: UnresolvedEvidenceError("bad \ud800"),
            lambda: UnresolvedEvidenceError("fine", ["\ud800"]),
            lambda: OversizedValueError("fine", limit=1, size=2, field="\ud800"),
        ],
    )
    def test_an_error_carrying_unencodable_text_is_refused(
        self, build: Callable[[], AssistantError]
    ) -> None:
        """ADR-0085 §9: ``core/errors.py`` is outside #566's coverage guard.

        The guard in ``tests/core/test_text_encodability_coverage.py`` is scoped to
        ``core.types`` deliberately, so nothing mechanical enforces this one — it is
        a clause this suite carries. It matters because §10a's reduction cannot
        rescue it: the reduction *measures* a payload, and measuring means encoding,
        so an unencodable message fails **before** the rule that was supposed to
        handle an oversized error, and the declared exception reaches a caller as an
        undeclared transport failure.
        """
        with pytest.raises(ValueError, match="UTF-8 encoding"):
            build()

    # --- §4: admission, and what it never applies to -----------------------

    async def test_the_enumeration_offers_the_source_with_its_location(
        self, granting_engine: AssistantEngine
    ) -> None:
        """ADR-0097 §9: a client offers a choice among declared identities.

        And ADR-0102 §6: this response is the **only** carrier of a source's
        configured location, so a client has something to render before it grants.
        """
        offered = await granting_engine.grantable_sources()
        assert [one.source for one in offered] == [_SOURCE]
        assert offered[0].location
        assert offered[0].live is None

    async def test_a_source_no_reader_declares_is_ungrantable(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§4: any validated value that is not a held identity raises, and nothing is built.

        :class:`~ai_assistant.core.errors.UngrantableSourceError` specifically, and
        **not** ``InvalidGrantError``: ADR-0097 §10 scopes that class to "the store
        refused the record", and this refusal happens before a record exists. A
        caller given the wrong one is told to construct a different record when the
        actual remedy is to pick a different source.
        """
        with pytest.raises(UngrantableSourceError):
            await granting_engine.grant("no-such-source", scope=[GrantScope.FACET])
        assert await granting_engine.recent_grants() == ()

    async def test_a_source_differing_only_by_whitespace_is_refused_not_matched(
        self, granting_engine: AssistantEngine
    ) -> None:
        """ADR-0097 §10, and the reason ``source`` is not :data:`Identifier` (§2).

        **This is the clause the wire implementation could have failed alone**, and
        ADR-0102 §12 item 2 says so in as many words: ``wire/surface.py`` validates
        each argument against the Protocol's own annotation before dispatch, so an
        ``Identifier`` annotation would have arrived at the operation already
        stripped and *matched* — while the in-process engine, handed the string
        unvalidated, refused the same call. Two observable contracts for one call is
        the substitutability failure ADR-0084 §4 promotes this surface to prevent.
        """
        with pytest.raises(UngrantableSourceError):
            await granting_engine.grant(f"  {_SOURCE}  ", scope=[GrantScope.FACET])
        assert await granting_engine.recent_grants() == ()

    async def test_revoking_a_source_no_reader_declares_is_not_refused_for_that(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§4: ``revoke`` applies **no** admission check.

        A grant whose reader is later unconfigured must stay revocable — otherwise a
        configuration edit makes it permanently unrevokable, which is the failure
        ADR-0097 §4 refused when it declined an ordering invariant on ``decided_at``.
        Nothing leaks through the opening: the value finds no live grant, constructs
        nothing and records nothing.
        """
        assert await granting_engine.revoke("no-such-source") is None
        assert await granting_engine.recent_grants() == ()

    async def test_a_source_that_cannot_be_shown_is_neither_enumerated_nor_granted(
        self, defective_source_engine: AssistantEngine
    ) -> None:
        """ADR-0102 §12 item 2's clause, and §6 is what it enforces.

        A configured location with no UTF-8 encoding is the hazard itself and fails
        **closed**: the source is omitted and ``grant`` refuses it. Degrading
        ``location`` to ``None`` and granting anyway was ADR-0102 §6's first draft
        and is refused there, because it makes ADR-0097 §9a's two halves contradict
        each other — the source would be offered while no conforming client could
        grant it, and a client that ignored the disclosure clause would mint
        precisely the uninformed grant §9a exists to prevent.

        **A source whose declared identity is not in canonical form is covered by
        the same case** (§4), because it has the same two-sided answer and would
        otherwise need a fixture of its own for one assertion.

        The second half is the one an over-eager implementation fails: enumeration
        of the *others* is unaffected, so a defective source is omitted rather than
        taking the whole response down. An implementation that refused the call
        would pass the first half and fail here.

        Held in the **shared** suite rather than in the concrete implementation's
        own tests, which is where an earlier round of this lane put it: a future
        engine or spoke could breach the contract and still come back green, and
        the wire implementation is reachable only from here.
        """
        offered = await defective_source_engine.grantable_sources()

        assert [one.source for one in offered] == [_SOURCE]
        for ungrantable in (_UNWRITABLE_SOURCE, _NOT_CANONICAL):
            with pytest.raises(UngrantableSourceError):
                await defective_source_engine.grant(ungrantable, scope=[GrantScope.FACET])
        assert await defective_source_engine.recent_grants() == ()

    async def test_a_refusal_names_a_held_reader_and_never_an_unknown_value(
        self, defective_source_engine: AssistantEngine
    ) -> None:
        """ADR-0102 §4's fourth clause, which differentiates the *message*.

        One error **class** covers all three causes — §2a keeps
        ``UngrantableSourceError`` single because the caller's recourse is identical
        — but §4 is explicit that the message is not: "An ``UngrantableSourceError``
        raised because a *held* reader's declared name is inadmissible names that
        reader; one raised because no held reader declares the value names no value
        at all."

        The asymmetry is not decoration. A held reader's identity is a **declared
        constant** and therefore Tier 2 by ADR-0093 §7's construction, so naming it
        tells an operator which reader to fix. A value that names nothing is
        caller-supplied and may be a typo carrying personal data, which ADR-0097 §9
        forbids echoing "so a mistyped value cannot reach the log (ADR-0004 §5)".
        Collapsing the two into one anonymous message loses the operator's only
        pointer; collapsing them the other way leaks.

        **And no refusal carries a filesystem path** (§4, §6), which is the half a
        message naming the reader is most tempted to add.
        """
        with pytest.raises(UngrantableSourceError) as unknown:
            await defective_source_engine.grant("no-such-source", scope=[GrantScope.FACET])
        assert "no-such-source" not in str(unknown.value)

        for held in (_UNWRITABLE_SOURCE, _NOT_CANONICAL):
            with pytest.raises(UngrantableSourceError) as caught:
                await defective_source_engine.grant(held, scope=[GrantScope.FACET])
            assert held.strip() in str(caught.value)
            assert "/srv/" not in str(caught.value)

    async def test_the_good_source_beside_a_defective_one_still_grants(
        self, defective_source_engine: AssistantEngine
    ) -> None:
        """The discriminating half: the omissions above are not "everything is refused".

        Without this an implementation that answered every enumeration empty and
        refused every grant would satisfy the case above completely.
        """
        recorded = await defective_source_engine.grant(_SOURCE, scope=[GrantScope.FACET])
        assert recorded.source == _SOURCE
        assert (await defective_source_engine.grantable_sources())[0].live is not None

    # --- §5: who mints, and the store as arbiter ---------------------------

    async def test_a_second_grant_on_a_live_source_is_refused(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§5: the store is the arbiter, and its refusal propagates.

        Never retried and never converted into a success. ADR-0097 §10 makes
        ``record`` atomic over the live-grant check, so a lost race is a typed
        refusal rather than a second live grant, and the client's remedy is to
        re-read ``grantable_sources``.
        """
        await granting_engine.grant(_SOURCE, scope=[GrantScope.FACET])
        with pytest.raises(InvalidGrantError):
            await granting_engine.grant(_SOURCE, scope=[GrantScope.INGEST])

    async def test_revoking_with_no_live_grant_returns_none(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§5: where no member of ``GrantScope`` answers, nothing is recorded."""
        assert await granting_engine.revoke(_SOURCE) is None
        assert await granting_engine.recent_grants() == ()

    async def test_a_revocation_transcribes_the_grant_it_withdraws(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§5: the revoking record carries the grant's ``source`` and ``scope`` verbatim.

        ADR-0021 §1's reason for embedding a declaration rather than a name: the
        record says what was withdrawn without a join. The store verifies the
        transcription, which is why an implementation that got it wrong would be
        refused rather than silently recording a lie.
        """
        granted = await granting_engine.grant(_SOURCE, scope=[GrantScope.INGEST])
        withdrawn = await granting_engine.revoke(_SOURCE)
        assert withdrawn is not None
        assert withdrawn.revokes == granted.id
        assert withdrawn.source == granted.source
        assert withdrawn.scope == granted.scope

    @pytest.mark.parametrize("only", list(GrantScope))
    async def test_a_grant_naming_one_use_is_revocable_whichever_use_it_names(
        self, granting_engine: AssistantEngine, only: GrantScope
    ) -> None:
        """§5's sweep, and the wrong version passes every other test here.

        ``SourceGrants.live`` takes a ``use``, so an implementation querying only
        ``FACET`` resolves a ``FACET``-scoped grant and silently fails to find an
        ``INGEST``-only one — leaving it unrevokable while ``revoke`` reports
        success by returning ``None``. ADR-0102 §5 marks the sweep for exactly that
        reason: the wrong implementation is silent and generous-looking.

        **Parametrised over the enum rather than spelled per member**, which is the
        property ADR-0102 §5 claims for the sweep — it "stays total as the enum
        grows because it is written over the enum rather than over its members" —
        and which the case could not deliver while it named ``INGEST`` alone.
        ADR-0133 §6 asks by name for the ``NOTIFY`` case, "so ADR-0102 §5's sweep is
        held total over the member that was added rather than over the two that
        were there when it was written"; parametrising discharges that and stops
        the same debt accruing against a fourth member.

        One use at a time is the discriminating shape: a scope naming several
        would be found by an implementation sweeping any one of them.
        """
        await granting_engine.grant(_SOURCE, scope=[only])
        assert await granting_engine.revoke(_SOURCE) is not None

    async def test_a_grant_reaches_the_enumeration_as_live_and_a_revocation_clears_it(
        self, granting_engine: AssistantEngine
    ) -> None:
        """The round trip, without which every refusal above proves nothing.

        A suite that only asserted refusals would pass against an implementation
        that refused everything.
        """
        await granting_engine.grant(_SOURCE, scope=[GrantScope.FACET])
        live = (await granting_engine.grantable_sources())[0].live
        assert live is not None
        assert live.scope == (GrantScope.FACET,)

        await granting_engine.revoke(_SOURCE)
        assert (await granting_engine.grantable_sources())[0].live is None
        assert len(await granting_engine.recent_grants()) == 2

    async def test_liveness_is_stated_rather_than_derived_from_the_page(
        self, back_dated_engine: AssistantEngine
    ) -> None:
        """ADR-0102 §12's normative clause, and **nothing else in this list reaches it**.

        ADR-0097 §4 derives liveness from the ``revokes`` relation alone and is
        emphatic that "a revocation is never refused for its timestamp — including
        one that predates the grant it revokes", because ``decided_at`` is
        caller-supplied and a host clock corrected backwards would otherwise make a
        grant permanently unrevokable. ``recent_grants`` is ordered newest first by
        ``decided_at``, so on such a deployment a revoking record sorts **below** the
        grant it revokes and can fall outside a page that contains it.

        An implementation computing ``live`` by walking that page would then report
        a **withdrawn grant as live** — the one answer this whole contract exists to
        get right — and would pass every other clause in this class, because every
        other clause is about admission, refusal or paging. It would also fail only
        on the deployment where a clock moved, which is the failure that never shows
        up in a test unless a test is written for it.

        So the two halves are asserted together: the source is not live, **and**
        both records are still listed. Asserting only the first would pass against
        an implementation that had dropped the revoked grant from the record, which
        ADR-0097 §6 forbids — revocation retires nothing and the history stays whole.
        """
        granted = await back_dated_engine.grant(_SOURCE, scope=[GrantScope.FACET])
        withdrawn = await back_dated_engine.revoke(_SOURCE)
        assert withdrawn is not None
        # The premise the fixture exists to establish. Asserted rather than assumed,
        # because a fixture whose clock did *not* run backwards would leave every
        # assertion below true of an implementation this case is written to fail.
        assert withdrawn.decided_at < granted.decided_at
        # And the page really is ordered the way that misleads: the grant sorts
        # first, so an implementation reading liveness off the newest entry sees a
        # granting record and answers "live".
        page = await back_dated_engine.recent_grants()
        assert [record.id for record in page] == [granted.id, withdrawn.id]

        assert (await back_dated_engine.grantable_sources())[0].live is None

    async def test_the_record_is_ordered_newest_first_with_ids_breaking_ties(
        self, granting_engine: AssistantEngine
    ) -> None:
        """``SourceGrantStore.recent``'s order, as the surface relays it.

        Descending by ``decided_at``, ties broken by ``id`` **ascending**. The
        tie-break is what makes the order total rather than merely mostly
        determined, and it is the half a one-line ``sorted(..., reverse=True)`` over
        a compound key gets wrong: reversing the compound key reverses the tie-break
        with it, so two records at one instant come back in the opposite order the
        contract states. An implementation whose clock does not advance between two
        records — a fixed test clock, or a real one at any resolution — reaches that
        case immediately, and nothing else in this class would notice.
        """
        await granting_engine.grant(_SOURCE, scope=[GrantScope.FACET])
        await granting_engine.revoke(_SOURCE)
        page = await granting_engine.recent_grants()
        assert len(page) == 2
        # Composed as two stable sorts rather than one reversed compound key,
        # because that compound key is precisely the wrong answer being checked
        # for: ``reverse=True`` over ``(decided_at, id)`` reverses the tie-break
        # too.
        by_id = sorted(page, key=lambda record: record.id)
        assert list(page) == sorted(by_id, key=lambda record: record.decided_at, reverse=True)

    # --- ADR-0139 §1 and §2: what is authorised, read from the store ---------

    async def test_standing_grants_carries_a_grant_no_held_reader_declares(
        self, disagreeing_engine: AssistantEngine
    ) -> None:
        """The hole ADR-0139 exists to close, asserted from both sides at once.

        ``grantable_sources`` is keyed on the composition root, so a grant whose
        reader the hub no longer builds is **absent** from it; before this operation
        that grant was live, read-authorising and revocable, with nothing that would
        tell the user its name. The two answers here are disjoint, which is a
        legitimate state rather than a fault (ADR-0139 §1) — and an implementation
        that reconciled them, or that answered this from the held readers, would
        drop the one record the operation was added for.
        """
        offered = await disagreeing_engine.grantable_sources()
        standing = await disagreeing_engine.standing_grants()

        assert [each.source for each in offered] == [_SOURCE]
        assert [each.source for each in standing] == [_UNHELD_SOURCE]

    async def test_standing_grants_is_a_tuple_and_neither_answer_is_derived(
        self, disagreeing_engine: AssistantEngine
    ) -> None:
        """ADR-0139 §1: no implementation may derive either answer from the other.

        The property is stated over what a *caller* can observe, which is all a
        conformance suite can reach: a source enumerated as grantable and ungranted
        is not in the standing set, and a standing grant is not offered as something
        to grant. An implementation that merged the two would fail one of these
        whichever direction it merged in.
        """
        standing = await disagreeing_engine.standing_grants()

        assert isinstance(standing, tuple)
        assert _SOURCE not in {each.source for each in standing}
        assert _UNHELD_SOURCE not in {
            each.source for each in await disagreeing_engine.grantable_sources()
        }

    async def test_standing_grants_holds_one_record_per_source_and_drops_a_revoked_one(
        self, granting_engine: AssistantEngine
    ) -> None:
        """Every live grant, one per source, and nothing revoked (ADR-0139 §2).

        Driven across a full amend cycle — grant, revoke, grant again — because
        that is where the three properties come apart. After the second grant the
        source has **two granting records** on file and one live grant, so an
        implementation answering from the history rather than from the ``revokes``
        relation returns two rows for one source; one answering from the newest
        record per source returns one and gets the revoked case wrong. The count is
        asserted alongside ``recent_grants``' three, which is what pins that
        revocation retired nothing (ADR-0097 §6).
        """
        assert await granting_engine.standing_grants() == ()

        await granting_engine.grant(_SOURCE, scope=[GrantScope.FACET])
        assert [each.source for each in await granting_engine.standing_grants()] == [_SOURCE]

        await granting_engine.revoke(_SOURCE)
        assert await granting_engine.standing_grants() == ()

        await granting_engine.grant(_SOURCE, scope=[GrantScope.INGEST])
        standing = await granting_engine.standing_grants()
        assert [(each.source, each.scope) for each in standing] == [(_SOURCE, (GrantScope.INGEST,))]
        assert len(await granting_engine.recent_grants()) == 3

    async def test_standing_grants_states_liveness_rather_than_deriving_it(
        self, back_dated_engine: AssistantEngine
    ) -> None:
        """ADR-0139 §8's marked clause, and **nothing else in this list reaches it**.

        Its sibling one section up pins the same property for
        ``GrantableSource.live``; this pins it for the set, and the reason it is a
        separate case rather than a second assertion is that the failure mode is
        different in shape. Every other clause about ``standing_grants`` is about
        *membership* — is this record in the set — and an implementation computing
        the live set by walking records in ``decided_at`` order, taking the newest
        per source, passes all of them. It fails only where a revocation is
        timestamped **before** the grant it revokes, which ADR-0097 §4 permits
        explicitly and which arrives on any host whose clock was corrected
        backwards.

        Both halves are asserted, as they are for the page: the set is empty **and**
        both records are still on file, because an implementation that had deleted
        the revoked grant would otherwise satisfy the first.
        """
        granted = await back_dated_engine.grant(_SOURCE, scope=[GrantScope.FACET])
        withdrawn = await back_dated_engine.revoke(_SOURCE)
        assert withdrawn is not None
        assert withdrawn.decided_at < granted.decided_at

        assert await back_dated_engine.standing_grants() == ()
        assert {record.id for record in await back_dated_engine.recent_grants()} == {
            granted.id,
            withdrawn.id,
        }

    async def test_standing_grants_refuses_an_oversized_set_rather_than_truncating_it(
        self, overfull_granting_engine: AssistantEngine
    ) -> None:
        """ADR-0139 §8's second marked clause: refusal over completion.

        **Refusing rather than truncating is the whole of what distinguishes this
        operation**, and it is the one property no other case reaches. An
        implementation that returned the store's result unmeasured — skipping the
        size check the engine applies to its other operations — passes every
        membership, revocation and corrupt-store case in the list and fails only at
        a size an ordinary test never constructs. ADR-0085 §8's bound and ADR-0139
        §2's clause both already forbid it; what is missing without this case is any
        test that would notice.

        The refusal is typed, so a client renders it as a refusal and cannot mistake
        it for an empty set — which is the whole reason a page was declined. And the
        remedy stays available at the same limit: ``revoke``'s request and result
        are two small values (ADR-0102 §10), so a user who knows a source's name can
        still withdraw it through a frame too small to list what they authorise.
        """
        with pytest.raises(OversizedValueError):
            await overfull_granting_engine.standing_grants()

        # The bound is per-method, so the neighbouring reads still answer: a case
        # that only asserted the raise would pass against an implementation whose
        # limit was simply too small for anything at all.
        assert await overfull_granting_engine.recent_grants(limit=1) != ()

    # --- §2a and §10: the local refusals -----------------------------------

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    @pytest.mark.parametrize("call", ["grant", "revoke"])
    async def test_a_blank_source_is_refused_locally(
        self, granting_engine: AssistantEngine, call: str, blank: str
    ) -> None:
        """§2a: a caller programming error, refused before any I/O.

        ``ValueError`` and deliberately not an ``AssistantError``, exactly as a
        blank identifier is on the rest of the surface.
        """
        arguments = {"scope": [GrantScope.FACET]} if call == "grant" else {}
        with pytest.raises(ValueError, match=r"\w"):
            await getattr(granting_engine, call)(blank, **arguments)

    async def test_an_empty_or_duplicated_scope_is_refused_locally(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§2a, over ADR-0097 §2 and §10's two refusals.

        A grant naming no use authorises nothing and would still *read* as a grant —
        and worse, would occupy the source's one live-grant slot. A repeated member
        is a caller that has lost track of what it is asking for.
        """
        with pytest.raises(ValueError, match=r"\w"):
            await granting_engine.grant(_SOURCE, scope=[])
        with pytest.raises(ValueError, match=r"\w"):
            await granting_engine.grant(_SOURCE, scope=[GrantScope.FACET, GrantScope.FACET])
        assert await granting_engine.recent_grants() == ()

    @pytest.mark.parametrize("bad", [0, -1, 2**63])
    async def test_recent_grants_refuses_a_non_positive_limit_locally(
        self, granting_engine: AssistantEngine, bad: int
    ) -> None:
        """§10's local-refusal clause, and ``0`` is the case it exists for.

        ADR-0085 §9 admits a page argument in ``[0, 2**63)`` and
        ``SourceGrantStore.recent`` requires a strictly positive ``limit``, so
        ``recent_grants(limit=0)`` is well-formed under the surface rule and refused
        by the store. Refusing it locally in **both** implementations is §9's own
        clause — "neither is silently more permissive" — applied to the one argument
        where the two ranges do not coincide.
        """
        with pytest.raises(ValueError, match=r"\w"):
            await granting_engine.recent_grants(limit=bad)

    @pytest.mark.parametrize("bad", [1.5, True, "1", None])
    async def test_a_limit_that_is_not_an_integer_is_refused_locally(
        self, granting_engine: AssistantEngine, bad: object
    ) -> None:
        """The type before the range, for :meth:`beliefs`' reason.

        ``0 < 1.5 < 2**63`` is true, so a range check alone admits a float; and
        ``True`` is an ``int`` that would silently mean a page of one, which is a
        wrong answer rather than a refusal.
        """
        with pytest.raises(TypeError, match=r"\w"):
            # The wrong *type* is the point of the case, so the annotation is
            # deliberately violated here.
            await granting_engine.recent_grants(limit=bad)  # type: ignore[arg-type]

    def test_the_grant_page_size_default_is_the_declared_one(
        self, granting_engine: AssistantEngine
    ) -> None:
        """ADR-0085 §3a reaches ``recent_grants`` like every other paging method."""
        parameter = inspect.signature(granting_engine.recent_grants).parameters["limit"]
        assert parameter.default == DEFAULT_PAGE_SIZE

    async def test_every_grant_enumeration_returns_a_tuple(
        self, granting_engine: AssistantEngine
    ) -> None:
        """ADR-0085 §3b: a caller that mutated a returned page changed nothing."""
        assert isinstance(await granting_engine.grantable_sources(), tuple)
        assert isinstance(await granting_engine.recent_grants(), tuple)
        assert isinstance(await granting_engine.standing_grants(), tuple)

    # --- the connection surface (ADR-0151 §16 item 2) -----------------------
    #
    # **What a store cannot exhibit**, which is §16 item 2's own scoping of this
    # block: the local refusals ADR-0085 §9 requires of *every* implementation, and
    # the surface shape clauses of ADR-0151 §5, §8 and §9. ADR-0151 §7's
    # classification of a provisioning act's failures is a provisioner ruling and is
    # pinned against every ``ConnectionProvisioner`` in
    # ``tests/tools/connection_provisioner_contract.py``, where the write points it
    # classifies actually are.

    async def test_an_identity_equal_to_the_credential_is_refused_without_a_write(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0151 §5: refused locally, before any I/O, with nothing written.

        **The case ADR-0149 §4 exists for**: a person pastes a token into the
        identity field. Refusing it is what stops a secret being written verbatim
        into a Tier 1 store that is *not* the keyring — and the comparison is exact
        string equality, made before the first of ADR-0148 §6's three writes.

        The ``entries`` assertion is the load-bearing half. A refusal after the
        first write would still raise the right class while having appended a
        pending entry naming a reference nobody was told about.
        """
        pasted = "the-token-itself"

        with pytest.raises(UnusableIdentityError) as caught:
            await connections.engine.connect_account(
                identity=pasted, credential=_credential(pasted)
            )

        assert connections.provisioner.entries == []
        assert pasted not in str(caught.value)

    @pytest.mark.parametrize(
        "identity",
        [
            "two\nlines",
            "a\u0000b",
            "tab\there",
            "para\u2029break",
            "Alice\u202ebob",
            "zero\u200bwidth",
            "bom\ufeffed",
        ],
        ids=[
            "newline",
            "nul",
            "tab",
            "paragraph-separator",
            "bidi-override",
            "zero-width-space",
            "byte-order-mark",
        ],
    )
    async def test_an_identity_that_is_not_single_line_printable_is_refused(
        self, connections: ConnectionSubject, identity: str
    ) -> None:
        """ADR-0149 §4, ADR-0151 §5: no control character and no line break.

        Seven values rather than one, because a hand-rolled ``"\n" in identity``
        check agrees on the first and disagrees on every other — and because
        "control character" is routinely read as the ``Cc`` category alone, which
        the last three are not.

        **The bidi override is the one that matters most**, and it is a spoof
        rather than a hygiene case. ADR-0151 §5 requires every client accepting an
        identity to *display* it as part of the act, and ADR-0149 §4's third answer
        to a credential pasted into the identity field is precisely that the value
        is seen. ``U+202E`` reorders what is rendered, so an identity carrying one
        is shown as something other than what is recorded — the one ingredient that
        answer needs, removed. The zero-width space and the byte-order mark are the
        quieter half of the same class: two identities that render identically and
        are not equal, on a surface where ADR-0151 §3 compares by exact equality.
        """
        with pytest.raises(UnusableIdentityError):
            await connections.engine.connect_account(identity=identity, credential=_credential())

        assert connections.provisioner.entries == []

    async def test_an_identity_over_the_bound_is_refused_without_naming_its_length(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0151 §5: the bound is one ``core`` constant every implementation names.

        **Both halves.** ADR-0085 §9 requires the client and the in-process engine
        to refuse the same values, which is why the bound is in ``core`` rather than
        in the store; and ADR-0125 §6's discipline applies to the message — the
        constant may be named, the rejected value's own measurement may not, because
        a length is a derivation from a value this layer must not describe.
        """
        oversized = "a" * (ACCOUNT_IDENTITY_MAX_BYTES + 1)

        with pytest.raises(UnusableIdentityError) as caught:
            await connections.engine.connect_account(identity=oversized, credential=_credential())

        assert connections.provisioner.entries == []
        assert str(ACCOUNT_IDENTITY_MAX_BYTES + 1) not in str(caught.value)

    async def test_a_malformed_credential_is_refused_locally_without_naming_it(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0125 §3 and §6, reached through this surface for the first time.

        A ``ValueError`` rather than an ``AssistantError``, which is ADR-0085 §9's
        own split: a blank secret is a caller programming error, where an identity
        is a value a person typed. The message names neither the value nor its
        length.
        """
        # ``SecretStr`` directly, **not** through :func:`_credential`: constructing
        # the origin satisfies every static check while the ``Annotated`` alias's
        # validator never runs (ADR-0125 §3), which is exactly the value a seam has
        # to revalidate rather than trust. If this surface trusted the annotation,
        # a blank secret would reach the keyring.
        with pytest.raises(ValueError, match="blank"):
            await connections.engine.connect_account(identity="ada", credential=SecretStr("   "))

        assert connections.provisioner.entries == []

    async def test_a_connection_is_active_at_its_first_revision_under_a_minted_reference(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0151 §7: it returns only once ADR-0148 §6's third write has landed.

        And ADR-0151 §3: the reference is the hub's, so the caller learns it from
        the record rather than supplying it. ``connect_account`` takes no reference
        argument at all, which is what makes "I meant to replace and created a
        second connection" unreachable rather than merely visible.
        """
        record = await connections.engine.connect_account(
            identity=_IDENTITY, credential=_credential()
        )

        assert record.state is ProvisioningState.ACTIVE
        assert record.revision == 1
        assert record.reference

    async def test_the_identity_crosses_the_surface_byte_for_byte(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0151 §5: nothing strips, case-folds or Unicode-normalises it.

        **Two identities differing only by case, both carrying surrounding
        whitespace**, which is the pair that separates a conforming implementation
        from one that normalises somewhere on the path. It is the clause an
        *annotation* could defeat one layer below itself: ``Identifier`` strips, so
        had ``identity`` been annotated with it the wire client would have sent a
        stripped value while the in-process engine kept the caller's — ADR-0084 §4's
        substitutability failure arriving through a type.
        """
        first = await connections.engine.connect_account(
            identity=_IDENTITY, credential=_credential()
        )
        second = await connections.engine.connect_account(
            identity=_IDENTITY_OTHER_CASE, credential=_credential("another-secret")
        )

        assert first.identity == _IDENTITY
        assert second.identity == _IDENTITY_OTHER_CASE
        assert first.reference != second.reference
        assert {record.identity for record in await connections.engine.connected_accounts()} == {
            _IDENTITY,
            _IDENTITY_OTHER_CASE,
        }

    async def test_re_provisioning_a_reference_the_store_does_not_hold_is_refused(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0151 §2a: refused before the first write, so nothing is written.

        This is the typo ``connect_account`` cannot make (ADR-0151 §3): with a
        minted reference, aiming an act at a reference that does not exist is a
        typed refusal rather than a silent second connection.
        """
        with pytest.raises(UnknownConnectionError):
            await connections.engine.reprovision_account(
                _UNHELD_REFERENCE, identity=_IDENTITY, credential=_credential()
            )

        assert connections.provisioner.entries == []

    async def test_disconnecting_a_reference_the_store_never_held_removes_nothing(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0151 §8: ``None``, and **not** a report of a disconnection.

        A mistyped reference leaves no tombstone and creates no revision sequence
        (ADR-0149 §5), which is why this writes nothing at all rather than appending
        a removal entry for a reference that never existed.
        """
        assert await connections.engine.disconnect_account(_UNHELD_REFERENCE) is None
        assert connections.provisioner.entries == []

    async def test_disconnecting_twice_removes_a_record_once(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0151 §8: idempotent, and the second ``None`` says only that.

        The two ``None`` returns in this suite mean the same thing and come from
        different states — a reference the store never held, and one whose latest
        entry is already a removal — which is exactly why ``None`` may not be
        rendered as "the reference does not exist".
        """
        record = await connections.engine.connect_account(
            identity=_IDENTITY, credential=_credential()
        )

        removed = await connections.engine.disconnect_account(record.reference)
        again = await connections.engine.disconnect_account(record.reference)

        assert removed is not None
        assert removed.reference == record.reference
        assert removed.state is ProvisioningState.ACTIVE
        assert again is None
        assert await connections.engine.connected_accounts() == ()

    async def test_a_pending_reference_is_listed_with_its_state(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0151 §4: not omitted, not substituted for, not reported as connected.

        **Reachable without anyone doing anything wrong, and repaired by nothing.**
        ADR-0148 §6 rules an interrupted act "refused rather than reconciled", so a
        surface showing only active records would answer "what is connected"
        correctly and leave a user whose hub died mid-act with a reference that
        exists, is refused at every call, and appears nowhere they can see.
        """
        connections.provisioner.secrets.fail(SecretMethod.SET, Disclosure.VERBATIM)

        with pytest.raises(IncompleteProvisioningError) as caught:
            await connections.engine.connect_account(identity=_IDENTITY, credential=_credential())

        live = await connections.engine.connected_accounts()
        assert [record.reference for record in live] == [caught.value.reference]
        assert live[0].state is ProvisioningState.PENDING

    async def test_every_live_record_is_listed_whatever_the_hub_holds(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0139 §1, ADR-0151 §9: answered from the store and from nothing else.

        No tool is registered against any of these references and no integration
        exists — the tree holds none — so an implementation filtering by what the
        hub can currently offer would answer with nothing at all. A connection whose
        integration is not built is still a connection, and the disconnection is the
        owner's only remedy.
        """
        first = await connections.engine.connect_account(
            identity=_IDENTITY, credential=_credential()
        )
        second = await connections.engine.connect_account(
            identity="second-account", credential=_credential("second-secret")
        )

        live = await connections.engine.connected_accounts()

        assert {record.reference for record in live} == {first.reference, second.reference}

    async def test_the_history_carries_one_row_per_act_and_marks_a_removal(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0151 §4 and §9: one row per ``(reference, revision)``, newest first.

        ``account`` is ``None`` **exactly when** the act was a disconnection, which
        is the discriminator ADR-0151 §4 chose over a fourth promoted type: an enum
        would encode what one optional field already says unambiguously, and would
        invite the third ``ProvisioningState`` ADR-0149 §5 forbids.

        The store's entry granularity is ``tools``-internal and is **not** exposed —
        each act writes two entries and shows one row — which this asserts by
        counting rather than by reading the store.
        """
        record = await connections.engine.connect_account(
            identity=_IDENTITY, credential=_credential()
        )
        await connections.engine.reprovision_account(
            record.reference, identity=_IDENTITY, credential=_credential("rotated")
        )
        await connections.engine.disconnect_account(record.reference)

        acts = await connections.engine.recent_connection_acts()

        assert [(act.revision, act.account is None) for act in acts] == [
            (3, True),
            (2, False),
            (1, False),
        ]
        assert {act.reference for act in acts} == {record.reference}
        assert all(
            act.account is None
            or (act.account.reference == act.reference and act.account.revision == act.revision)
            for act in acts
        )

    async def test_the_history_is_bounded_by_the_limit(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0151 §9: newest first, so a bound keeps the newest rather than the oldest."""
        for index in range(3):
            await connections.engine.connect_account(
                identity=f"account-{index}", credential=_credential(f"secret-{index}")
            )

        page = await connections.engine.recent_connection_acts(limit=2)

        assert len(page) == 2
        assert [act.account.identity for act in page if act.account is not None] == [
            "account-2",
            "account-1",
        ]

    @pytest.mark.parametrize("limit", [0, -1])
    async def test_the_history_refuses_a_non_positive_limit_locally(
        self, connections: ConnectionSubject, limit: int
    ) -> None:
        """ADR-0151 §2a: stricter than ADR-0085 §9's ``[0, 2**63)``, in every implementation.

        ``limit=0`` is well-formed under the surface rule and refused by the store,
        so §9's "neither is silently more permissive" is satisfied by refusing it
        one step earlier — locally, before any I/O, which is what the untouched log
        below asserts.
        """
        with pytest.raises(ValueError, match="strictly positive"):
            await connections.engine.recent_connection_acts(limit=limit)

        assert connections.provisioner.entries == []

    async def test_an_oversized_credential_is_refused_with_nothing_written(
        self, tiny_connections: ConnectionSubject
    ) -> None:
        """ADR-0151 §11: fail closed, in **every** implementation.

        **The case that separates a bound from a serialisation accident.** The
        credential has no canonical projection at all (ADR-0151 §6), so an
        implementation measuring its argument object the obvious way measures
        everything *except* the credential — and then the wire client, which
        serialises for real, refuses a call the in-process engine has already
        carried out. That is ADR-0084 §4's substitutability failure with a Tier 0
        value inside it: the same request writes a credential to the keyring on one
        implementation and raises on the other.

        The credential here is well within :data:`SECRET_VALUE_MAX_BYTES`, so
        ``secret_value`` accepts it and the only thing that can refuse the call is
        the frame bound this clause is about.

        **Nothing written is the other half**, and it is why the provisioner comes
        with the subject: a refusal issued *after* ADR-0148 §6's first write would
        raise the right class while leaving a pending record naming a reference the
        caller was never told about.
        """
        oversized = "s" * _OVERSIZED_CREDENTIAL_BYTES
        assert _TINY_LIMIT < len(oversized.encode()) < SECRET_VALUE_MAX_BYTES

        with pytest.raises(OversizedValueError):
            await tiny_connections.engine.connect_account(
                identity="ada", credential=_credential(oversized)
            )

        assert tiny_connections.provisioner.entries == []
        assert await tiny_connections.engine.connected_accounts() == ()

    async def test_a_credential_inside_the_limit_is_admitted(
        self, tiny_connections: ConnectionSubject
    ) -> None:
        """The complement, without which the clause above is satisfied by refusing
        everything — which is the failure mode a fail-closed rule invites."""
        record = await tiny_connections.engine.connect_account(
            identity="ada", credential=_credential("small-secret")
        )

        assert record.state is ProvisioningState.ACTIVE

    async def test_the_size_refusal_discloses_a_recoverable_credential_length(
        self, tiny_connections: ConnectionSubject
    ) -> None:
        """**An accepted disclosure, pinned so it stays examined** (#1141).

        ADR-0125 §6 forbids a secret's *length* in an exception, and ADR-0151 §2a
        forbids "any part or derivation" of the credential in a class on this
        surface. ADR-0085 §10a, meanwhile, ratifies ``OversizedValueError.size`` as
        a measurement "the far side reconstructs" — and the two collide here,
        because the overhead around the credential is fixed and publicly derivable
        from the method name and the identity, both of which the caller supplied.
        So ``size`` yields the credential's byte length by subtraction.

        **This asserts the leak rather than its absence, deliberately.** The
        earlier version of this case asserted only that the literal length string
        was absent, which passes trivially because the number exposed is the
        *total* — so it read as a guarantee while testing nothing. Adversarial
        review found that, correctly. Writing the arithmetic down is what turns an
        unexamined property into a recorded one: if a later change removes the
        disclosure this fails and someone reads #1141, and if a later change
        *widens* it this still fails.

        **Waived rather than fixed, on three grounds** carried in #1141: the value
        reaches only the caller who supplied the credential and therefore already
        possesses it whole, so no recipient learns anything; §2a's reach over
        pre-existing `core` surface is under-determined, since its clause sits in
        the paragraph declaring the seven new classes and ``OversizedValueError``
        predates it; and the alternative — ``size: int | None`` — is contract
        surgery on ratified reconstructible surface, owing its own ADR.

        What is **not** waived is the message: it still names neither the value nor
        any part of it, and the largest-member field names ``credential`` as a
        *parameter name*, which ADR-0151 §6 requires anyway so that
        ``core/logging.py``'s key-name redaction covers it.
        """
        plaintext = "s" * _OVERSIZED_CREDENTIAL_BYTES

        with pytest.raises(OversizedValueError) as caught:
            await tiny_connections.engine.connect_account(
                identity="ada", credential=_credential(plaintext)
            )

        exposed = caught.value
        assert exposed.limit == _TINY_LIMIT
        assert exposed.field == "credential"
        # The disclosure, stated as arithmetic: the payload is the credential plus a
        # fixed envelope the caller can compute, so the length falls out.
        overhead = exposed.size - len(plaintext)
        assert 0 < overhead < 100, (
            "the overhead is small and fixed, which is what makes it derivable"
        )
        assert exposed.size - overhead == len(plaintext)

        # The message discloses no *part* of the value, which is the half that is
        # not waived — a prefix or a digest would be a different finding.
        rendered = str(exposed)
        assert plaintext not in rendered
        assert plaintext[:8] not in rendered

    async def test_no_result_on_this_surface_carries_a_credential(
        self, connections: ConnectionSubject
    ) -> None:
        """ADR-0149 §9, ADR-0151 §6: no response carries a credential or a derivation.

        Asserted over every result the surface can produce for an act that really
        wrote one, rather than over the type declarations — a field could be added
        that satisfies the annotations and still carried the value.
        """
        plaintext = "hunter2-correct-horse"
        record = await connections.engine.connect_account(
            identity=_IDENTITY, credential=_credential(plaintext)
        )
        live = await connections.engine.connected_accounts()
        acts = await connections.engine.recent_connection_acts()

        rendered = repr((record, live, acts))
        assert plaintext not in rendered
        assert "SecretStr" not in rendered

    # --- the audit trail's two reads (ADR-0186 §11) ------------------------
    #
    # **What a store cannot exhibit**, which is what puts these here rather than in
    # ``AuditTrailContract``. That is a different suite over a different contract
    # and it is indeed untouched; this one is subclassed by the concrete engine, by
    # the canonical fake **and** by ``HubClient``, so it is the only place a clause
    # binds all three. It is also the precedent ADR-0102 §12 item 2 set, for exactly
    # this reason — and it settles where the client's two methods land: the suite
    # runs against the client, so they cannot be deferred to a later lane without
    # this block going red the day it arrives.

    async def test_the_listing_and_the_export_share_one_total_order(
        self, decisions: DecisionSubject
    ) -> None:
        """ADR-0186 §2: ``decided_at`` descending, ties broken by ``id`` ascending, on both.

        **Determinism is not tidiness here, it is what the exit test is measured
        on.** Milestone 24 asks whether a history is *reconstructible* from the
        trail alone; two implementations handing back the same rows in different
        orders satisfy every other clause of ADR-0186 while giving two users two
        different accounts of the same events.
        """
        listed = await decisions.engine.recent_decisions()
        exported = await decisions.engine.export_decisions()

        assert tuple(row.id for row in listed) == _DECISION_ORDER
        assert tuple(row.id for row in exported) == _DECISION_ORDER

    async def test_the_tie_break_orders_two_rulings_made_at_one_instant(
        self, decisions: DecisionSubject, unordered_decisions: DecisionSubject
    ) -> None:
        """ADR-0186 §2, over rows that really share a ``decided_at``.

        "Newest first" is ambiguous between insertion order and decision time, and
        an ``id`` tie-break is what makes the order **total** rather than merely
        mostly determined (ADR-0021 §4). The pair is asserted on its own because a
        whole-sequence comparison passes for an implementation whose tie-break
        happens to agree with the order it was handed — here ``d-4`` is recorded
        **before** ``d-3`` and must still come second of the two, so a stable sort
        on ``decided_at`` alone answers them the wrong way round.

        **Over both bindings, because only one of them can fail.** A conforming
        trail's ``recent`` is *already* in this order (ADR-0021 §4 fixes it), so an
        engine with no tie-break of its own still answers correctly there; the
        unordered export is where the engine's own sort is the only thing deciding.
        The ordinary binding is kept because the other failure is real too — an
        implementation whose sort **destroys** an order the store had.
        """
        for subject in (decisions, unordered_decisions):
            exported = await subject.engine.export_decisions()
            tied = [row for row in exported if row.decided_at == _RULED_AT + timedelta(seconds=1)]

            assert [row.id for row in tied] == ["d-3", "d-4"]

    async def test_the_order_is_not_the_order_the_rulings_were_recorded_in(
        self, decisions: DecisionSubject, unordered_decisions: DecisionSubject
    ) -> None:
        """ADR-0186 §2: it orders the instant a ruling was **made**.

        ADR-0021 §4 chose ``decided_at`` over insertion order "precisely because
        they disagree", and this trail is seeded so that they do: ``d-2`` is
        recorded second and ruled first, ``d-1`` recorded first and ruled last. An
        implementation relaying the store's append order answers ``d-1, d-2, d-4,
        d-3`` and fails here — which is also why no surface may present a position
        as a claim about when anything was *done*.

        Over both bindings for the tie-break case's reason.
        """
        recorded = tuple(decision_id for decision_id, _offset in _SEEDED_DECISIONS)
        for subject in (decisions, unordered_decisions):
            exported = await subject.engine.export_decisions()

            assert tuple(row.id for row in exported) != recorded
            assert tuple(row.id for row in exported) == _DECISION_ORDER

    async def test_the_export_is_sorted_by_the_engine_and_not_relayed(
        self, unordered_decisions: DecisionSubject
    ) -> None:
        """ADR-0186 §2's second clause: the **engine** owes the sort.

        ``AuditTrail.export`` states no order and ADR-0186 adds none to it, so "an
        implementation relaying a store read that arrives unordered owes the sort,
        over a list it has already materialised". This is the one case that
        distinguishes an engine which sorts from one which relays: both shipped
        trails promise ``recent``'s order for ``export`` in their own docstrings, so
        every other case here passes for ``tuple(await trail.export())``.

        The trail is asked directly first, which is what stops the fixture being
        vacuous — a binding whose double had quietly started answering in order
        would make this assertion true for the wrong reason.
        """
        assert [row.id for row in await unordered_decisions.trail.export()] != list(
            _DECISION_ORDER
        ), "the fixture must exercise the store contract's freedom, or it tests nothing"

        exported = await unordered_decisions.engine.export_decisions()

        assert tuple(row.id for row in exported) == _DECISION_ORDER

    async def test_the_listing_is_a_prefix_of_the_export(self, decisions: DecisionSubject) -> None:
        """ADR-0186 §2: ``recent_decisions(limit=n)`` is the first ``n`` of the export.

        **The case nothing else would catch.** An implementation that sorted its
        listing and relayed an unordered export passes every construction case,
        every rendering case and every transport case, and hands two conforming
        implementations' users two different accounts of one history. It is also
        what makes the two answers *comparable*, which is why ADR-0186 §1 has the
        engine relay rather than compose: an engine that filtered or enriched either
        one would break this with no surface able to tell.
        """
        exported = await decisions.engine.export_decisions()

        for size in range(1, len(_DECISION_ORDER) + 1):
            page = await decisions.engine.recent_decisions(limit=size)
            assert page == exported[:size], f"the page of {size} is not the export's prefix"

    async def test_each_operation_reaches_its_own_store_read_and_no_other(
        self, decisions: DecisionSubject
    ) -> None:
        """ADR-0186 §1: the listing reads ``recent``, the export reads ``export``.

        Stated normatively and otherwise untestable by answers alone, because the two
        are indistinguishable over any trail small enough to write down. An
        ``export_decisions`` implemented as ``trail.recent(limit=50)`` agrees with a
        conforming one on every other fixture in this block and silently truncates a
        real trail at the default page — turning the artifact that discharges
        ADR-0004 §6 into exactly the partial export §3 forbids "without saying so".
        The mirror error is cheaper but still wrong: a listing served by loading the
        whole trail and slicing is a paging surface that lies about its cost
        (ADR-0102 §10).

        Asserted from the store's own read log rather than from row counts, so the
        case is exact rather than sized: it fails on the *first* call to the wrong
        method, whatever the trail happens to hold.
        """
        await decisions.engine.recent_decisions(limit=2)

        assert decisions.trail.reads == ["recent"]

        decisions.trail.reads.clear()
        await decisions.engine.export_decisions()

        assert decisions.trail.reads == ["export"]

    async def test_the_export_is_not_bounded_by_the_listing_s_default_page(
        self, decisions: DecisionSubject
    ) -> None:
        """ADR-0186 §3: the export is "bounded by nothing at the contract".

        The observable half of the clause above, over a trail larger than
        :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE` — the size at which a
        truncating implementation stops agreeing with a conforming one. Seeded by the
        case rather than by a fixture, because what every other case needs is a trail
        small enough to state ADR-0186 §2's order over by name.

        The prefix property is re-asserted at this size, and that is the point of
        doing it twice: it is the one place where "the listing is the first ``n`` of
        the export" and "the export is complete" can come apart, since over a trail
        that fits in one page a listing which *is* the whole trail satisfies the
        prefix rule vacuously.
        """
        for index in range(DEFAULT_PAGE_SIZE):
            await decisions.trail.record(
                _ruling(f"e-{index:03d}", at=_RULED_AT - timedelta(seconds=index + 1))
            )

        exported = await decisions.engine.export_decisions()

        assert len(exported) == len(_SEEDED_DECISIONS) + DEFAULT_PAGE_SIZE
        assert await decisions.engine.recent_decisions() == exported[:DEFAULT_PAGE_SIZE]

    @pytest.mark.parametrize("bad", [0, -1, 2**63])
    async def test_recent_decisions_refuses_a_non_positive_limit_locally(
        self, decisions: DecisionSubject, bad: int
    ) -> None:
        """ADR-0186 §3's local-refusal clause, and ``0`` is the case it exists for.

        Zero follows ADR-0151 §2a rather than ADR-0102 §10's compromise:
        ``AuditTrail.recent`` refuses a non-positive ``limit`` and ADR-0085 §9 would
        admit it, and ADR-0186 §3 resolves that by refusing it **locally in every
        implementation** rather than reproducing the live wart ``recent_grants``'
        own contract records.

        The untouched log is the half that says *locally*: a client that shipped
        ``limit=0`` to the hub would be exactly the silently more permissive
        implementation §9 forbids, and would leave a ``recent`` behind here.
        """
        with pytest.raises(ValueError, match=r"\w"):
            await decisions.engine.recent_decisions(limit=bad)

        assert decisions.trail.reads == []

    @pytest.mark.parametrize("bad", [1.5, True, "1", None])
    async def test_a_decision_limit_that_is_not_an_integer_is_refused_locally(
        self, decisions: DecisionSubject, bad: object
    ) -> None:
        """The type before the range, for :meth:`beliefs`' reason (ADR-0186 §3).

        ``0 < 1.5 < 2**63`` is true, so a range check alone admits a float; and
        ``True`` is an ``int`` that would silently mean a page of one, which is a
        wrong answer rather than a refusal.
        """
        with pytest.raises(TypeError, match=r"\w"):
            # The wrong *type* is the point of the case, so the annotation is
            # deliberately violated here.
            await decisions.engine.recent_decisions(limit=bad)  # type: ignore[arg-type]

        assert decisions.trail.reads == []

    def test_the_decision_page_size_default_is_the_declared_one(
        self, decisions: DecisionSubject
    ) -> None:
        """ADR-0085 §3a reaches ``recent_decisions`` like every other paging method."""
        parameter = inspect.signature(decisions.engine.recent_decisions).parameters["limit"]
        assert parameter.default == DEFAULT_PAGE_SIZE

    def test_the_export_takes_no_argument(self, decisions: DecisionSubject) -> None:
        """ADR-0186 §1 and §3: no ``limit``, no ``offset``, no filter, no cursor.

        Two operations rather than one, "because a single method cannot be both
        bounded and complete": a ``limit`` that could be omitted to mean everything
        would make the unbounded read of a Tier 1 store the *default* shape of the
        listing and hide a data-rights act inside a page query. Asserted over the
        signature because the failure is an argument being **added**, which no call
        that omits it would ever notice.
        """
        assert inspect.signature(decisions.engine.export_decisions).parameters == {}

    async def test_both_decision_reads_return_a_tuple(self, decisions: DecisionSubject) -> None:
        """ADR-0085 §3b: a caller that mutated what it was handed changed nothing."""
        assert isinstance(await decisions.engine.recent_decisions(), tuple)
        assert isinstance(await decisions.engine.export_decisions(), tuple)

    @pytest.mark.parametrize("operation", ["recent_decisions", "export_decisions"])
    async def test_a_trail_that_cannot_be_read_is_reported_as_the_failure_it_was(
        self, decisions: DecisionSubject, operation: str
    ) -> None:
        """The store's declared failure reaches the caller as itself, on both reads.

        ``AuditError`` is what ``AuditTrail.recent`` and ``export`` raise when "the
        trail cannot be read, or holds a row that no longer validates" — a corrupt
        or unopenable database, which is the one failure no sequence of surface calls
        produces. **A clause the shared suite is the only place for**, because the
        three implementations reach it by three different routes and could disagree
        without any of them looking wrong on its own: the in-process pair let the
        exception out of a relayed store call, while the client has to recognise the
        type on an error frame and rebuild it (ADR-0085 §10a fixes the wire's error
        vocabulary as "exactly the ``AssistantError`` subtree").

        **What it forecloses is a plausible kindness**: an implementation that
        answered ``()`` for an unreadable trail would tell a user their audit trail
        is *empty* — the one wrong answer this surface can give, since the whole
        value of the artifact is that its emptiness means nothing was ruled.

        The message is asserted too, because reconstruction that lost it would leave
        a caller holding the right class and no account of what went wrong.
        """
        decisions.trail.fail_with = AuditError("the trail could not be read")

        with pytest.raises(AuditError, match="could not be read"):
            await getattr(decisions.engine, operation)()

    async def test_an_export_too_large_for_the_frame_is_refused_whole(
        self, overfull_decisions: AssistantEngine
    ) -> None:
        """ADR-0186 §3: the oversized **result**, refused as an oversized argument is.

        The suite's own fifth clause applied to the largest result this surface can
        produce. An export concentrates a whole history in one frame where a
        confirmation concentrates one call, and §3 states the answer rather than
        waving at it: "No implementation truncates the artifact, samples it, or
        returns a partial export without saying so." A refusal is typed, so a client
        renders it as one and cannot mistake it for an empty trail — which is the
        whole reason an artifact was declined.

        The neighbouring read still answers at the same limit, which is the control:
        a case that only asserted the raise would pass against an implementation
        whose limit was simply too small for anything at all.
        """
        with pytest.raises(OversizedValueError):
            await overfull_decisions.export_decisions()

        assert await overfull_decisions.recent_decisions(limit=1) != ()

    # --- the read trail's two reads (ADR-0186 §10) -------------------------
    #
    # **The same block one store over**, and here for the block above's reason: this
    # suite is subclassed by the concrete engine, by the canonical fake **and** by
    # ``HubClient``, so it is the only place a clause binds all three, and it is
    # what settles that the client's two methods land in this change rather than a
    # later one.
    #
    # **What is not repeated here is as deliberate as what is.** ADR-0186 §10 binds
    # this pair to §2's determinism, §3's local refusal and §7's last two clauses,
    # and explicitly **not** to §7's egress content floor — "which is about a
    # binding no read record carries". So there is no case about an account
    # identity, a span, a destination set or a payload description below, and their
    # absence is the ADR read correctly rather than coverage missing.

    async def test_the_read_listing_and_the_export_share_one_total_order(
        self, reads: ReadSubject
    ) -> None:
        """ADR-0186 §10: newest-**recorded** first, on both.

        §10 binds this pair to §2's *determinism* while forbidding it to reshape
        §2's *order*, and this store's order is not §2's: ADR-0185 §6 orders it by
        recording order and rules out ``checked_at`` by name. So the shared order is
        the recorded sequence reversed, and both operations answer in it.
        """
        listed = await reads.engine.recent_reads()
        exported = await reads.engine.export_reads()

        assert tuple(row.id for row in listed) == _READ_ORDER
        assert tuple(row.id for row in exported) == _READ_ORDER

    async def test_the_read_order_is_never_derived_from_the_instant_a_row_carries(
        self, reads: ReadSubject
    ) -> None:
        """ADR-0185 §6, as this surface has to preserve it — the sharper double.

        **The case that separates a conforming implementation from the plausible
        wrong one**, and it is this pair's counterpart to the decision block's
        unordered double rather than a copy of it. There the store states no export
        order, so the risk is an engine that *relays*; here the store states one, so
        the risk is an engine that **sorts** — reaching for ``checked_at`` because
        that is the only instant on the row and because the sibling operation sorts
        by ``decided_at``.

        It would be wrong for a reason the fixture cannot show but ADR-0185 §6 states
        outright: ``checked_at`` is **caller-supplied**, so an order derived from it
        moves under a backwards clock correction — the same hazard that made the
        store key its own prune on recording order rather than on that instant,
        where "a prune keyed on it after a backwards clock correction deletes the
        rows it just wrote".

        Asserted in both directions. The fixture's own premise is checked first, so
        the case cannot pass by the two orders happening to agree; then each
        ``checked_at`` ordering is refuted by name, which a bare positive assertion
        would leave to inference.
        """
        by_instant = sorted(_SEEDED_READS, key=lambda row: row[1])
        assert tuple(row[0] for row in by_instant) != _READ_ORDER, (
            "the fixture must disagree with the instant ordering, or it tests nothing"
        )

        exported = await reads.engine.export_reads()
        answered = tuple(row.id for row in exported)

        assert answered == _READ_ORDER
        assert answered != tuple(row[0] for row in by_instant)
        assert answered != tuple(row[0] for row in reversed(by_instant))
        assert answered != tuple(sorted(_READ_ORDER))
        assert answered != tuple(sorted(_READ_ORDER, reverse=True))

    async def test_two_reads_checked_at_one_instant_keep_their_recording_order(
        self, reads: ReadSubject
    ) -> None:
        """ADR-0185 §6: a tie in ``checked_at`` is not a tie in this order at all.

        ``r-3`` and ``r-2`` share an instant and are recorded three rows apart, so an
        implementation that ordered by ``checked_at`` — with any tie-break, or with
        none and a stable sort — cannot put them in the recorded relation. The pair
        is asserted on its own because a whole-sequence comparison can pass for the
        wrong reason on a fixture where the two happen to coincide.

        **The asymmetry with the decision block is the point.** There the ``id``
        tie-break is what makes the order *total*; here the order is total by
        construction, because recording order is a sequence rather than a key, and
        nothing on the row is consulted at all.
        """
        exported = await reads.engine.export_reads()
        tied = [row.id for row in exported if row.checked_at == _CHECKED_AT + timedelta(seconds=2)]

        assert tied == ["r-2", "r-3"]

    async def test_the_read_export_is_reversed_and_not_relayed(self, reads: ReadSubject) -> None:
        """ADR-0186 §10: the **engine** owes the reversal.

        ``SourceReadTrail.export`` returns "every record the store holds, in
        recording order" — oldest first — while ``recent`` answers newest-recorded
        first. An implementation handing the store's list back as it arrived would
        return the exact **reverse** of the listing, and §2's prefix property would
        be gone with it.

        The trail is asked directly first, which is what stops the case being
        vacuous: it establishes that the store really did hand over the opposite
        order, so the engine's answer is evidence of a reversal rather than of a
        store that happened to agree.
        """
        relayed = [row.id for row in await reads.trail.export()]

        assert relayed == list(reversed(_READ_ORDER)), (
            "the fixture must exercise the store's stated order, or it tests nothing"
        )

        exported = await reads.engine.export_reads()

        assert tuple(row.id for row in exported) == _READ_ORDER

    async def test_the_read_listing_is_a_prefix_of_the_read_export(
        self, reads: ReadSubject
    ) -> None:
        """ADR-0186 §10 through §2's determinism: ``recent_reads(limit=n)`` is the first ``n``.

        **The case nothing else would catch.** An implementation that relayed the
        listing and relayed the export would answer both in a conforming-looking
        order and hand back one as the *reverse* of the other, which no single-call
        assertion notices. It is also what makes the two answers comparable, which
        is why §1 has the engine relay rather than compose — reasoning this pair
        mirrors rather than inherits, §10's inheritance list naming §2, §3, §7 and
        §8 alone.
        """
        exported = await reads.engine.export_reads()

        for size in range(1, len(_READ_ORDER) + 1):
            page = await reads.engine.recent_reads(limit=size)
            assert page == exported[:size], f"the page of {size} is not the export's prefix"

    async def test_each_read_operation_reaches_its_own_store_read_and_no_other(
        self, reads: ReadSubject
    ) -> None:
        """§10's pair mirrors §1's: the listing reads ``recent``, the export ``export``.

        Otherwise untestable by answers alone, because over a trail small enough to
        write down the two are indistinguishable. An ``export_reads`` implemented as
        ``trail.recent(limit=50)`` agrees with a conforming one on every other
        fixture in this block and silently truncates a real trail at the default
        page — turning the artifact ADR-0004 §6's export right reaches into exactly
        the partial export §3 forbids "without saying so". The mirror error is
        cheaper but still wrong: a listing served by loading the whole trail and
        slicing is a paging surface that lies about its cost (ADR-0102 §10), and on
        this store it would load a horizon of up to
        ``source_read_trail_max_rows`` rows to answer a page of fifty.

        Asserted from the store's own read log rather than from row counts, so the
        case fails on the *first* call to the wrong method, whatever the trail holds.
        """
        await reads.engine.recent_reads(limit=2)

        assert reads.trail.reads == ["recent"]

        reads.trail.reads.clear()
        await reads.engine.export_reads()

        assert reads.trail.reads == ["export"]

    async def test_the_read_export_is_not_bounded_by_the_listing_s_default_page(
        self, reads: ReadSubject
    ) -> None:
        """ADR-0186 §3 through §10: the export is "bounded by nothing at the contract".

        The observable half of the clause above, over a trail larger than
        :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE` — the size at which a
        truncating implementation stops agreeing with a conforming one. Seeded by
        the case rather than by a fixture, because what every other case needs is a
        trail small enough to state the order over by name.

        The prefix property is re-asserted at this size, and that is the point of
        doing it twice: over a trail that fits in one page a listing which *is* the
        whole trail satisfies the prefix rule vacuously.

        The rows are appended **after** the seeded four, so they are the *newest*
        recorded and the default page is entirely made of them — which is also what
        makes the assertion sensitive to the reversal, since a relaying export would
        put them at the far end instead.
        """
        for index in range(DEFAULT_PAGE_SIZE):
            await reads.trail.record(
                _attempt(f"x-{index:03d}", at=_CHECKED_AT + timedelta(seconds=index + 10))
            )

        exported = await reads.engine.export_reads()

        assert len(exported) == len(_SEEDED_READS) + DEFAULT_PAGE_SIZE
        assert await reads.engine.recent_reads() == exported[:DEFAULT_PAGE_SIZE]

    @pytest.mark.parametrize("bad", [0, -1, 2**63])
    async def test_recent_reads_refuses_a_non_positive_limit_locally(
        self, reads: ReadSubject, bad: int
    ) -> None:
        """ADR-0186 §3 through §10, and ``0`` is the case it exists for.

        ``SourceReadTrail.recent`` refuses a non-positive ``limit`` where ADR-0085
        §9 would admit zero, and §3 resolves that by refusing it **locally in every
        implementation** rather than reproducing the live wart ``recent_grants``'
        own contract records. The store's own reason is sharper than the audit
        trail's precedent: it "issues ``LIMIT ?`` against SQLite", which turns
        ``limit=-1`` into no limit at all — so a passed-through negative makes the
        one bounded read the unbounded read it exists to avoid.

        The untouched log is the half that says *locally*: a client that shipped
        ``limit=0`` to the hub would be exactly the silently more permissive
        implementation §9 forbids, and would leave a ``recent`` behind here.
        """
        with pytest.raises(ValueError, match=r"\w"):
            await reads.engine.recent_reads(limit=bad)

        assert reads.trail.reads == []

    @pytest.mark.parametrize("bad", [1.5, True, "1", None])
    async def test_a_read_limit_that_is_not_an_integer_is_refused_locally(
        self, reads: ReadSubject, bad: object
    ) -> None:
        """The type before the range, for :meth:`beliefs`' reason (ADR-0186 §3).

        ``0 < 1.5 < 2**63`` is true, so a range check alone admits a float; and
        ``True`` is an ``int`` that would silently mean a page of one, which is a
        wrong answer rather than a refusal.
        """
        with pytest.raises(TypeError, match=r"\w"):
            # The wrong *type* is the point of the case, so the annotation is
            # deliberately violated here.
            await reads.engine.recent_reads(limit=bad)  # type: ignore[arg-type]

        assert reads.trail.reads == []

    def test_the_read_page_size_default_is_the_declared_one(self, reads: ReadSubject) -> None:
        """ADR-0085 §3a reaches ``recent_reads`` like every other paging method.

        It is ``DEFAULT_PAGE_SIZE`` and not the store's own literal ``50``, even
        though the two are equal today: the surface's default is the constant, and a
        subject that had copied the number would drift the day ADR-0085 §3a's value
        moves.
        """
        parameter = inspect.signature(reads.engine.recent_reads).parameters["limit"]
        assert parameter.default == DEFAULT_PAGE_SIZE

    def test_the_read_export_takes_no_argument(self, reads: ReadSubject) -> None:
        """§10's pair mirrors §1's shape: no ``limit``, no cursor — and no ``source``.

        Two operations rather than one, and **two rather than three**: ADR-0185 §12
        left "a per-source query and a count … the surface ADR's to ask for if it
        needs them", and ADR-0186 §10 passed that question on rather than closing
        it — naming them "this surface's to ask for and not this document's to
        guess at" — so declining both was **this lane's** choice, on ADR-0045 §1's
        and ADR-0028 §7's surface-with-no-consumer rule. A ``source`` argument
        appearing here would therefore be a surface nobody asked for.
        Asserted over the signature because the failure is an argument being
        **added**, which no call that omits it would ever notice.
        """
        assert inspect.signature(reads.engine.export_reads).parameters == {}

    async def test_both_read_operations_return_a_tuple(self, reads: ReadSubject) -> None:
        """ADR-0085 §3b: a caller that mutated what it was handed changed nothing.

        Sharper than housekeeping on this pair: both store methods return a
        ``list``, and the export's implementation reverses one, so a subject
        handing back what it built is the likely mistake rather than a contrived
        one.
        """
        assert isinstance(await reads.engine.recent_reads(), tuple)
        assert isinstance(await reads.engine.export_reads(), tuple)

    @pytest.mark.parametrize("operation", ["recent_reads", "export_reads"])
    async def test_a_read_trail_that_cannot_be_read_is_reported_as_the_failure_it_was(
        self, reads: ReadSubject, operation: str
    ) -> None:
        """The store's declared failure reaches the caller as itself, on both reads.

        ``ReadTrailError`` is what ``SourceReadTrail``'s reads raise when the trail
        cannot be read — a corrupt or unopenable database, the one failure no
        sequence of surface calls produces. **A clause the shared suite is the only
        place for**, because the three implementations reach it by three different
        routes and could disagree without any of them looking wrong on its own: the
        in-process pair let the exception out of a relayed store call, while the
        client has to recognise the type on an error frame and rebuild it (ADR-0085
        §10a fixes the wire's error vocabulary as "exactly the ``AssistantError``
        subtree").

        **What it forecloses is a plausible kindness**, and it is worse here than on
        the audit trail. An implementation answering ``()`` for an unreadable trail
        would tell a user nothing has ever been read from their sources — and on
        this store an empty answer is *also* the truthful answer for a hub that has
        read nothing, so the two would be indistinguishable at the surface where the
        exit test is measured.

        ``ReadTrailError`` is **one class and not two** (ADR-0185 §12), so this case
        does not split by cause: under §5's fail-closed rule a caller's recourse is
        identical however the store failed.
        """
        reads.trail.fail_read()

        with pytest.raises(ReadTrailError, match=r"\w"):
            await getattr(reads.engine, operation)()

    async def test_a_read_export_too_large_for_the_frame_is_refused_whole(
        self, overfull_reads: AssistantEngine
    ) -> None:
        """ADR-0186 §3 through §10: the oversized **result**, refused whole.

        The suite's own fifth clause applied to the largest result this pair can
        produce. §3's answer is stated rather than waved at: "No implementation
        truncates the artifact, samples it, or returns a partial export without
        saying so." A refusal is typed, so a client renders it as one and cannot
        mistake it for an empty trail.

        **This store has a second remedy the audit trail has not**, and it is worth
        naming so a reader does not conclude the frame budget is the only knob:
        ``source_read_trail_max_rows`` bounds the trail itself (ADR-0185 §6), which
        is why an export here is a horizon rather than a history. Neither remedy is
        truncation, which is the clause.

        The neighbouring read still answers at the same limit, which is the control:
        a case that only asserted the raise would pass against an implementation
        whose limit was simply too small for anything at all.
        """
        with pytest.raises(OversizedValueError):
            await overfull_reads.export_reads()

        assert await overfull_reads.recent_reads(limit=1) != ()

    # --- the trail's two invocation reads (ADR-0192 §4, §9) ----------------
    #
    # **The engine operations' own obligations, pinned as conformance cases**,
    # because ADR-0192 §4 states them over "every implementation" and §9 says in
    # terms that "no adapter or store case reaches them". Three groups: the order,
    # the prefix invariant, and ``limit`` validation — "without them an engine that
    # forwards a ``limit`` straight through, or relays the store's order
    # unmaterialised, passes every adapter case §9 names while breaking §4's clauses
    # in terms". The surrounding cases are the decision block's, one row kind over,
    # for that block's stated reason: this suite is the only place a clause binds
    # the concrete engine, the canonical fake and ``HubClient`` at once.

    async def test_the_invocation_listing_and_export_share_one_total_order(
        self, invocations: InvocationSubject
    ) -> None:
        """ADR-0192 §4: ``recorded_at`` descending, ties broken by ``id`` ascending, on both.

        The order is the **operation's** guarantee "over a list it has
        materialised", which is why it is asserted here and not left to the store:
        two implementations handing back the same rows in different orders satisfy
        every other clause of §4 while giving two users two different accounts of
        what this system did.
        """
        listed = await invocations.engine.recent_invocations()
        exported = await invocations.engine.export_invocations()

        assert tuple(row.invocation.id for row in listed) == _INVOCATION_ORDER
        assert tuple(row.invocation.id for row in exported) == _INVOCATION_ORDER

    async def test_the_tie_break_orders_two_rows_recorded_at_one_instant(
        self, invocations: InvocationSubject
    ) -> None:
        """ADR-0192 §4, over rows that really share a ``recorded_at``.

        The pair is asserted on its own because a whole-sequence comparison passes
        for an implementation whose tie-break happens to agree with the order it was
        handed. Here ``i-4`` is appended **before** ``i-3`` and must still come
        second of the two, so an implementation "sorting on the instant alone or
        leaving insertion order for a tie" answers them the wrong way round (§9).

        **The sort key is the row's and not the join's** (ADR-0192 §2). ``id`` and
        ``recorded_at`` live on ``RecordedInvocation.invocation``; the join adds the
        tool, the capability and the egress boolean and restates neither. An
        implementation reaching for a top-level key finds none, and one keying on
        something the join added would order two rows of one attempt by a fact about
        the *decision*.
        """
        exported = await invocations.engine.export_invocations()
        tied = [
            row
            for row in exported
            if row.invocation.recorded_at == _RECORDED_AT + timedelta(seconds=1)
        ]

        assert [row.invocation.id for row in tied] == ["i-3", "i-4"]

    async def test_the_invocation_order_is_not_the_order_the_rows_were_appended_in(
        self, invocations: InvocationSubject
    ) -> None:
        """ADR-0192 §4: the listing orders the instant a row was **recorded**.

        The two disagree here by construction, and deliberately so: ADR-0192 §2 has
        the *ledger* decide every admission rule on its durable append order "so a
        wall clock that steps backwards cannot make a completed act stop being the
        most recent one", while §4's listing is ordered on ``recorded_at``. Both are
        true at once, and an implementation relaying the append order satisfies
        neither clause it thought it was satisfying.
        """
        exported = await invocations.engine.export_invocations()

        appended = tuple(row_id for row_id, _, _, _ in _SEEDED_INVOCATIONS)
        assert appended != _INVOCATION_ORDER, "the fixture must make the two disagree"
        assert tuple(row.invocation.id for row in exported) == _INVOCATION_ORDER

    async def test_the_invocation_listing_is_a_prefix_of_the_export(
        self, invocations: InvocationSubject
    ) -> None:
        """ADR-0192 §4: ``recent_invocations(limit=n)`` is the first ``n`` of the export.

        Asserted for an ``n`` **short of, equal to and past** the row count, which
        ADR-0192 §9 requires by name: at ``n`` past the count the two answers are
        the same whole sequence, and an implementation that padded, wrapped or
        raised there would be a page that lies about the trail rather than about
        itself.
        """
        exported = await invocations.engine.export_invocations()

        for size in range(1, len(_INVOCATION_ORDER) + 3):
            page = await invocations.engine.recent_invocations(limit=size)
            assert page == exported[:size], f"the page of {size} is not the export's prefix"

    async def test_each_invocation_operation_reaches_its_own_store_read_and_no_other(
        self, invocations: InvocationSubject
    ) -> None:
        """ADR-0192 §4: the listing reads ``recent_invocations``, the export reads its twin.

        The decision block's clause one row kind over, and it also pins the negative
        that matters most here: **neither operation reads the decision store**.
        ADR-0192 §4 has the engine relay precisely because the join is the store's,
        so an implementation that read rows and then read their decisions would
        leave ``recent`` or ``export`` in this log — and would have an ``await``
        between the two that a ``clear()`` can land in (§2).
        """
        await invocations.engine.recent_invocations(limit=2)

        assert invocations.trail.reads == ["recent_invocations"]

        invocations.trail.reads.clear()
        await invocations.engine.export_invocations()

        assert invocations.trail.reads == ["export_invocations"]

    async def test_the_invocation_export_is_not_bounded_by_the_listing_s_default_page(
        self, invocations: InvocationSubject
    ) -> None:
        """ADR-0192 §4: the export "takes no argument and pages nothing".

        The observable half of that clause, over a trail larger than
        :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE` — the size at which a
        truncating implementation stops agreeing with a conforming one, and the
        size at which an ``export_invocations`` written as
        ``recent_invocations(limit=50)`` turns the artifact discharging ADR-0004 §6
        into the partial export §4 forbids "without saying so".

        Seeded by the case rather than by a fixture, because what every other case
        needs is a trail small enough to state §4's order over by name. The rows are
        claims under fresh decisions for :data:`_SEEDED_INVOCATIONS`' reason: the
        ruled tool is side-effecting with ``Idempotency.NONE``, so ADR-0192 §1's
        consume admits one claim per authorisation.
        """
        for index in range(DEFAULT_PAGE_SIZE):
            decision_id = f"x-{index:03d}"
            await invocations.trail.record(
                _ruling(decision_id, at=_RULED_AT - timedelta(seconds=index + 1))
            )
            await invocations.trail.claim_invocation(
                decision=await _recorded(invocations.trail, decision_id)
            )
        invocations.trail.reads.clear()

        exported = await invocations.engine.export_invocations()

        assert len(exported) == len(_SEEDED_INVOCATIONS) + DEFAULT_PAGE_SIZE
        assert await invocations.engine.recent_invocations() == exported[:DEFAULT_PAGE_SIZE]

    @pytest.mark.parametrize("bad", [0, -1, 2**63])
    async def test_recent_invocations_refuses_a_non_positive_limit_locally(
        self, invocations: InvocationSubject, bad: int
    ) -> None:
        """ADR-0192 §4's local-refusal clause, over §9's enumerated values.

        ``AuditTrail.recent_invocations`` refuses a non-positive ``limit`` and
        ADR-0085 §9 would admit zero, and §4 resolves that by refusing it
        **locally in every implementation** — ``recent_decisions``' rule, stated
        again for this pair rather than inherited, because §4 states it in its own
        terms.

        The untouched log is the half that says *locally*: a client that shipped
        ``limit=0`` to the hub would be exactly the silently more permissive
        implementation ADR-0085 §9 forbids, and would leave a read behind here.
        """
        with pytest.raises(ValueError, match=r"\w"):
            await invocations.engine.recent_invocations(limit=bad)

        assert invocations.trail.reads == []

    @pytest.mark.parametrize("bad", [1.5, True, "1", None])
    async def test_an_invocation_limit_that_is_not_an_integer_is_refused_locally(
        self, invocations: InvocationSubject, bad: object
    ) -> None:
        """The type before the range (ADR-0192 §4, §9).

        ``0 < 1.5 < 2**63`` is true, so a range check alone admits a float; and
        ``True`` is an ``int`` that would silently mean a page of one, which is a
        wrong answer rather than a refusal. ADR-0192 §4 names the ``bool`` case
        explicitly for that reason.
        """
        with pytest.raises(TypeError, match=r"\w"):
            # The wrong *type* is the point of the case, so the annotation is
            # deliberately violated here.
            await invocations.engine.recent_invocations(limit=bad)  # type: ignore[arg-type]

        assert invocations.trail.reads == []

    def test_the_invocation_page_size_default_is_the_declared_one(
        self, invocations: InvocationSubject
    ) -> None:
        """ADR-0085 §3a reaches ``recent_invocations`` like every other paging method."""
        parameter = inspect.signature(invocations.engine.recent_invocations).parameters["limit"]
        assert parameter.default == DEFAULT_PAGE_SIZE

    def test_the_invocation_export_takes_no_argument(self, invocations: InvocationSubject) -> None:
        """ADR-0192 §4: no ``limit``, no ``offset``, no filter, no cursor.

        "There is no ``offset``" is the ADR's own sentence, and the export's
        argument list is where a later lane would put one. Asserted over the
        signature because the failure is an argument being **added**, which no call
        that omits it would ever notice.
        """
        assert inspect.signature(invocations.engine.export_invocations).parameters == {}

    async def test_both_invocation_reads_return_a_tuple(
        self, invocations: InvocationSubject
    ) -> None:
        """ADR-0085 §3b: a caller that mutated what it was handed changed nothing."""
        assert isinstance(await invocations.engine.recent_invocations(), tuple)
        assert isinstance(await invocations.engine.export_invocations(), tuple)

    async def test_neither_invocation_read_returns_a_mixed_sequence(
        self, invocations: InvocationSubject, decisions: DecisionSubject
    ) -> None:
        """ADR-0192 §4: two row kinds, two operations, two sequences.

        "No operation returns a mixed sequence; no lane widens ADR-0186 §1's return
        type or adds a ``ToolInvocation`` or a ``RecordedInvocation`` to what
        ``recent_decisions`` or ``export_decisions`` returns." Asserted over the
        **values** rather than over the annotations, because a widening arrives as a
        row of the wrong type in a real answer and an annotation a lane forgot to
        change would hide it.

        The decision half is asserted over a trail that holds invocation rows too,
        which is the only arrangement in which the mixing could happen at all: the
        rows are on one store, and §4's separation is a claim about the two
        operations rather than about two databases.
        """
        for row in await invocations.engine.recent_invocations():
            assert isinstance(row, RecordedInvocation)
        for row in await invocations.engine.export_invocations():
            assert isinstance(row, RecordedInvocation)

        for ruled in await invocations.engine.recent_decisions():
            assert isinstance(ruled, PermissionDecision)
        for ruled in await invocations.engine.export_decisions():
            assert isinstance(ruled, PermissionDecision)
        assert decisions.trail is not invocations.trail, "two subjects, so neither case is vacuous"

    @pytest.mark.parametrize("operation", ["recent_invocations", "export_invocations"])
    async def test_an_invocation_read_that_fails_is_reported_as_the_failure_it_was(
        self, invocations: InvocationSubject, operation: str
    ) -> None:
        """The store's declared failure reaches the caller as itself, on both reads.

        ``AuditError`` is what both invocation reads raise when the trail cannot be
        read **or holds a row it could not pair with a decision** — the corrupt
        state ADR-0192 §2's join reports rather than silently dropping. A clause the
        shared suite is the only place for, because the three implementations reach
        it by three different routes: the in-process pair let the exception out of a
        relayed store call, while the client has to recognise the type on an error
        frame and rebuild it (ADR-0085 §10a).

        What it forecloses is the same plausible kindness the decision case names:
        an implementation answering ``()`` for an unreadable trail would tell a user
        nothing ever ran, which is the one wrong answer this surface can give.
        """
        invocations.trail.fail_with = AuditError("the trail is not readable")

        with pytest.raises(AuditError):
            await getattr(invocations.engine, operation)()

    async def test_an_invocation_export_too_large_for_the_frame_is_refused_whole(
        self, overfull_invocations: AssistantEngine
    ) -> None:
        """ADR-0192 §4: the oversized **result**, refused whole and never truncated.

        "No implementation truncates the artifact, samples it, or returns a partial
        export without saying so", and the refusal is typed so a client renders it
        as one rather than mistaking it for a trail with nothing in it.

        The neighbouring read still answers at the same limit, which is the control:
        a case that only asserted the raise would pass against an implementation
        whose limit was simply too small for anything at all. That control is worth
        more here than on either other pair, because §4's ground for reusing
        ADR-0085 §8c unchanged is precisely that this projection is **small** — so a
        limit at which no single row fits would be testing a premise the ADR denies.
        """
        with pytest.raises(OversizedValueError):
            await overfull_invocations.export_invocations()

        assert await overfull_invocations.recent_invocations(limit=1) != ()

    # --- ADR-0194 §6: what the world has cost ---------------------------

    @pytest.fixture
    @abstractmethod
    def spending(self) -> SpendSubject:
        """A subject over a ledger configured with a **zero** ceiling on both periods.

        A fixture because nothing on this surface writes a row either, on
        :attr:`invocations`' reason and a sharper version of it: ADR-0194 §5 promotes
        exactly one operation and it is a read, the admission lives on ``SpendGate``
        behind the tool seam, and the appends live on ``InvocationLedger`` behind it.
        So the only route to a configured ledger is to be handed one.

        **Zero rather than a comfortable number**, because ADR-0194 §11 makes the
        consumer group carry that value through every seam it owns and it is the one
        a producer or a renderer testing falsiness gets wrong invisibly.
        """

    @pytest.fixture
    @abstractmethod
    def unconfigured_spending(self) -> SpendSubject:
        """A subject over a ledger with **no currency configured at all**.

        The other of ADR-0194 §5's two absences, and it needs its own subject
        because ``currency`` is what discriminates them: a case driven only against
        the configured one cannot tell "no total was computed" from "the period
        could not be measured".
        """

    @pytest.fixture
    @abstractmethod
    def indeterminate_spending(self) -> SpendSubject:
        """A subject whose current day holds an **open claim**, with only a day ceiling.

        ADR-0194 §2 makes such a period's accounted total indeterminate, and §11
        drives the periods **disagreeing**: the month carries no ceiling of its own,
        so §6's "no further call will be admitted" line is absent there and present
        on the day. A renderer printing it from the absence of a total alone tells a
        user their calls are blocked when they are not.
        """

    async def test_both_periods_come_back_in_the_ledgers_fixed_order(
        self, spending: SpendSubject
    ) -> None:
        """ADR-0194 §5: ``CALENDAR_DAY`` then ``CALENDAR_MONTH``, always both.

        Asserted as the **exact sequence** of ``period`` values rather than by
        looking each entry up, which is §11's own instruction: a producer returning
        the month first satisfies every totals and error-ordering clause here and
        changes what every reader of the surface sees.
        """
        totals = await spending.engine.spend_totals()

        assert tuple(total.period for total in totals) == (
            SpendPeriod.CALENDAR_DAY,
            SpendPeriod.CALENDAR_MONTH,
        )

    async def test_a_configured_ceiling_of_zero_survives_the_relay(
        self, spending: SpendSubject
    ) -> None:
        """ADR-0194 §11: the zero ceiling carried the rest of the way, seam by seam.

        Asserted on ``as_tuple()`` and never on truthiness or on the field's mere
        presence. A ``configured_ceiling or None`` anywhere between the store and
        here passes every admission clause — the gate still refuses correctly — and
        then tells a user their period has no ceiling while every priced call they
        make is being refused.
        """
        totals = await spending.engine.spend_totals()

        for total in totals:
            assert total.currency == SPEND_CURRENCY
            assert total.ceiling is not None
            assert total.ceiling.as_tuple() == SPEND_ZERO_CEILING.as_tuple()
            assert total.accounted is not None
            assert total.accounted.as_tuple() == Decimal("0").as_tuple()

    async def test_no_currency_configured_states_no_total_and_no_ceiling(
        self, unconfigured_spending: SpendSubject
    ) -> None:
        """ADR-0194 §5's *other* absence, and the discriminator that names it.

        Both entries still come back — "both entries whatever is configured" — and
        each carries ``currency=None``, which is what a reader reads to know that no
        sum was attempted rather than that one could not be completed.
        """
        totals = await unconfigured_spending.engine.spend_totals()

        assert len(totals) == 2
        for total in totals:
            assert total.currency is None
            assert total.ceiling is None
            assert total.accounted is None

    async def test_an_indeterminate_period_is_returned_and_not_raised(
        self, indeterminate_spending: SpendSubject
    ) -> None:
        """ADR-0194 §5: ``accounted=None`` beside a present ``currency``.

        An open claim states that an act may have happened and does not state what
        it cost, so the period cannot be measured — and the operation **returns**
        that rather than raising, because the value is still producible. §5 permits
        this member exactly one raised class and only where it cannot produce the
        values at all.

        The two periods are asserted to **disagree about the ceiling**, which is
        what §11 drives them for: the claim is in the day and therefore in the
        month, so both are indeterminate, but only the day carries a ceiling of its
        own — and §2 refuses on no other.
        """
        day, month = await indeterminate_spending.engine.spend_totals()

        assert day.currency == SPEND_CURRENCY
        assert day.accounted is None
        assert day.ceiling is not None
        assert month.currency == SPEND_CURRENCY
        assert month.accounted is None
        assert month.ceiling is None

    async def test_the_period_bounds_are_half_open_and_carry_their_own_offsets(
        self, spending: SpendSubject
    ) -> None:
        """ADR-0194 §1, §5: ``[start, end)``, with the offsets the producer resolved.

        The day sits inside the month, and each entry carries an offset for **each**
        end — a period containing a transition has different offsets at its two ends,
        which is the case a single offset would misrender and the reason two are
        carried rather than one.
        """
        day, month = await spending.engine.spend_totals()

        assert day.period_start < day.period_end
        assert month.period_start <= day.period_start
        assert day.period_end <= month.period_end
        for total in (day, month):
            assert abs(total.start_offset) < timedelta(hours=24)
            assert abs(total.end_offset) < timedelta(hours=24)

    async def test_a_spend_read_too_large_for_the_frame_is_refused_whole(
        self, overfull_spending: AssistantEngine
    ) -> None:
        """ADR-0194 §6: ``OversizedValueError``, declared and not disclaimed.

        §6 says the declaration is a real one rather than a formality: ADR-0194 §1
        bounds each contributing amount and nothing bounds the number of rows, so an
        accounted total is unbounded and a pair of them can outgrow the frame. The
        limit is what this fixture makes small; the reachability is what §6 declines
        to claim is remote.
        """
        with pytest.raises(OversizedValueError):
            await overfull_spending.spend_totals()

    @pytest.fixture
    @abstractmethod
    def overfull_spending(self) -> AssistantEngine:
        """A subject whose contract limit the two totals exceed."""


def backwards_clock() -> Callable[[], datetime]:
    """A clock whose every reading is **earlier** than the last.

    What :attr:`AssistantEngineContract.back_dated_engine` is built on, shared so
    the three bindings cannot arrange three different premises for one clause. It
    models a host clock that has been corrected backwards — the deployment ADR-0097
    §4 refuses to make a grant unrevokable on, and therefore the only deployment on
    which a liveness derived from ``decided_at`` gives a wrong answer.

    Steps by a whole second per reading, so the two records a grant/revoke pair
    mints are unambiguously ordered rather than separated by a resolution a
    serialiser might round away.

    Returns:
        A callable returning a strictly decreasing sequence of instants.
    """
    numbers = count(1)
    origin = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    return lambda: origin - timedelta(seconds=next(numbers))


async def page_after_mutating_the_filter(
    engine: AssistantEngine,
) -> tuple[tuple[BeliefSummary, ...], tuple[BeliefSummary, ...]]:
    """Run ``beliefs`` while emptying the list it was handed, and page it again.

    Shared with the discrimination case in ``test_fake_engine``, which is what
    makes the assertion above evidence rather than a tautology: a scenario nobody
    has watched fail is a scenario that agrees with whatever it is run against.

    Returns:
        The page from the mutated call, and the page the same filter yields when
        nothing touches it.
    """
    every_band = [BeliefBand.ASSERTED, BeliefBand.DERIVED, BeliefBand.ATTESTED]
    bands = list(every_band)
    running = asyncio.ensure_future(engine.beliefs(bands=bands))
    # One turn of the loop, so the call has reached its first suspension (or run to
    # completion) before the list is emptied — the window ADR-0065 §3d is about.
    await asyncio.sleep(0)
    bands.clear()
    page = await running
    return page, await engine.beliefs(bands=every_band)


def _takes_a_message(initialiser: object) -> bool:
    """Whether ``initialiser`` accepts ADR-0085 §10a's message as its first argument."""
    following = [
        parameter
        for parameter in inspect.signature(initialiser).parameters.values()  # type: ignore[arg-type]
        if parameter.name != "self"
    ]
    return bool(following) and following[0].name == "message"


def _protocol_declarations() -> str:
    """The source of ``core/protocols.py``, so a ``Raises:`` clause is searchable."""
    return inspect.getsource(protocols_module)


def _sample_for(parameter: str) -> object:
    """A plausible value for one structured-state parameter, by its declared shape.

    Deliberately shallow: what the round-trip test needs is *a* value the
    constructor accepts, not a realistic one. A parameter this does not know is
    given a string, which is what every operator-facing field on the hierarchy is.
    """
    if parameter in {"limit", "size"}:
        return 1
    if parameter.endswith("_ids"):
        return ("a", "b")
    return "text"
