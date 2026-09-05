"""A canonical :class:`~ai_assistant.core.protocols.WebSearcher` fake (ADR-0231 §17).

The shared test double for the ``WebSearcher`` contract, so a subsystem that
services a search — `orchestration`'s read servicer — can exercise every branch of
its own pipeline without a provider, a credential or a channel, and without
importing the concrete searcher (``CLAUDE.md`` golden rule 1).

**It records what it was handed, and that is what makes ADR-0231 §18's arms
possible.** Arm 4a asserts that the string :meth:`FakeWebSearcher.request` received
is byte-identical to the query that turn's composition returned, that a refused
composition reaches ``request`` **not at all**, and that no supply value appears in
anything ``request`` received; arm 3 asserts that a second servicing's ruling stops
before :meth:`FakeWebSearcher.search` is reached. None of those can be asserted
against a searcher whose inputs a test cannot read back, so
:attr:`FakeWebSearcher.requested` and :attr:`FakeWebSearcher.searched` are that
record — appended **on entry**, because a test asserting that a call did not happen
wants the absence of a row rather than the absence of a *completed* one.

It is scriptable to every state ADR-0231 §10 distinguishes, which is what a consumer
needs to drive its own disposition (§13):

* **no account connected** — ``origin=None``, so :meth:`request` answers ``None``,
  which is the configuration fact §17 makes it answer and never a failure;
* **records**, per query or as one default answer for every query, each carrying a
  content a test chose so that an assertion about a reply is not an assertion about
  a coincidence; and
* a **refusal**, per query, into any :class:`SearchRefusal` member — so a consumer
  can reach each of the five dispositions §13 carries across without a provider.

**And a fourth, which is what makes the cancellation clause testable at all.**
:meth:`search` runs inside a
:class:`~ai_assistant.testing.cancellation.SuspendableResource`, so a suite can arm
:meth:`FakeWebSearcher.suspend_next` and cancel a call that has *demonstrably*
arrived at an await. Without it the clause passes vacuously: a fake that completes
immediately can only be cancelled before it starts, which exercises none of the code
an implementation would use to catch a ``CancelledError`` during a provider call and
convert it into a refusal.

**The two bounds are the fake's own, for the concrete searcher's reasons** (§17).
``SearchOutcome`` carries neither, so a suite reads them off the harness rather than
off a value: this fake mints at most :attr:`FakeWebSearcher.max_results` records and
**drops** — never truncates — one whose content passes its content bound, yielding
:attr:`SearchRefusal.NO_RESULT` where that takes the last one with it, which is
ADR-0231 §10's rule stated over an answer a test chose.

**Not a fault injector.** Everything here conforms. A consumer that needs a searcher
which *breaks* the contract on purpose — one whose ``name`` moves between calls, one
minting a record attested to some other instant, one returning an outcome carrying
both halves — is testing a reaction to a non-conforming producer and supplies its own
stub for it. This fake must stay the thing a conforming implementation is compared
against; two of those three are unconstructable anyway, which is the point of
``SearchOutcome`` enforcing them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from ai_assistant.core.types import (
    ActionRequest,
    Attestation,
    CostBasis,
    DataTier,
    Idempotency,
    MemorySource,
    Provenance,
    Reversibility,
    RiskLevel,
    SearchOutcome,
    SearchRefusal,
    SemanticMemory,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.testing.cancellation import SuspendableResource
from ai_assistant.testing.spend import countable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.types import FrozenJson, MemoryRecord, ToolCall
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: The id this fake's declaration carries. Distinct from the production searcher's,
#: because a fake standing in for one is not that one: a test that asserted an id
#: would otherwise pass against either and mean nothing about which was wired.
FAKE_WEB_SEARCH_ID: Final = "fake_web_search"

#: The source instance a fake searcher names itself, which is what a minted record's
#: ``Attestation.reported_by`` carries (ADR-0231 §10). Non-blank and unchanged by
#: ``Identifier``'s own validation, which §17 requires of every ``WebSearcher``.
DEFAULT_SEARCH_SOURCE_NAME: Final = "fake web search"

#: The origin a fake searcher's request names unless a test says otherwise. A
#: reserved-for-documentation host, so nothing here resolves anywhere real even if
#: some future consumer forgot to inject a transport.
DEFAULT_SEARCH_ORIGIN: Final = "https://search.example.com"

#: What one search brings back unless a test scripts something else. Distinctive
#: enough that an assertion that it reached a reply is not an assertion about a
#: coincidence, and shaped as ADR-0231 §10 shapes a content: a title, an address and
#: a snippet, one per line.
DEFAULT_SEARCH_CONTENT: Final = (
    "Torre dos Clérigos\nhttps://example.com/clerigos\nA baroque bell tower in Porto."
)

#: ADR-0231 §5's named default for ``search_max_results``, so a fake constructed with
#: no bound is bounded the way a default deployment is. It is also §5's **ceiling** —
#: "§10's figure is the ceiling and the setting narrows it, never widens it" — and
#: this fake refuses a larger one for that reason: a canonical fake configurable into
#: a state no deployment can be in would let a consumer's test pass over a supply this
#: system can never actually assemble, which is what would make §11's precedence look
#: satisfied while a search took a third of ADR-0226 §6's budget of ten.
DEFAULT_MAX_RESULTS: Final = 3

#: ADR-0231 §5's named default for ``search_max_result_chars``, likewise.
DEFAULT_MAX_RESULT_CHARS: Final = 2048

#: The instant a fake response declares unless a test names another. Fixed, because
#: ADR-0092 §3 makes it the *provider's* statement: a fake reading a clock here would
#: be the substitute §10 forbids, wearing a double's clothes.
DEFAULT_REPORTED_AT: Final = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

#: ADR-0038 §2a's figure for an attested producer, which every one of them carries.
_ATTESTED_CONFIDENCE: Final = 0.9

#: The declaration this fake's :meth:`FakeWebSearcher.request` carries by value. Its
#: safety fields are the production declaration's, argued in ADR-0231 §5, because a
#: fake ruled on more leniently than the real thing would let a consumer's policy
#: test pass for a reason no deployment enjoys. Its schema declares exactly two
#: arguments: an origin bearing both egress keywords, and a query bearing neither.
FAKE_WEB_SEARCH: Final = ToolDefinition(
    id=FAKE_WEB_SEARCH_ID,
    capability="web_search",
    description="Ask the connected search account one question and read its results.",
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=True,
    reads=(DataTier.SECRET,),
    writes=(),
    discloses=(DataTier.PERSONAL,),
    cost=ToolCost(basis=CostBasis.UNKNOWN),
    idempotency=Idempotency.NONE,
    parameters_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "origin": {
                "type": "string",
                # Spelled rather than imported, so that the canonical fake reaches
                # into no subsystem: ADR-0152 §3 fixes both keyword names, and
                # `tests/testing/test_fake_web_searcher.py` asserts these two equal
                # the constants `tools/` reads them by, which is what stops the two
                # spellings drifting without anything noticing.
                "x-egress-destination": "https",
                "x-egress-tier": "operational",
            },
            "query": {"type": "string"},
        },
        "required": ["origin", "query"],
        "additionalProperties": False,
    },
)


def _check_bounds(max_results: int, max_result_chars: int) -> None:
    """Refuse a bound outside ADR-0231 §5's stated domain for it.

    Args:
        max_results: ``Settings.search_max_results``.
        max_result_chars: ``Settings.search_max_result_chars``.

    Raises:
        TypeError: If either is not an ``int``, ``bool`` included — the type is part of
            the domain for the concrete searcher's reason, and the canonical fake must
            not be the looser of the two.
        ValueError: If either is below 1, or if ``max_results`` is above
            :data:`DEFAULT_MAX_RESULTS`, which is §5's whole stated domain and not
            merely its default.
    """
    for label, bound, ceiling in (
        ("max_results", max_results, DEFAULT_MAX_RESULTS),
        ("max_result_chars", max_result_chars, None),
    ):
        if isinstance(bound, bool) or type(bound) is not int:
            msg = f"{label} must be an integer, got {bound!r}"
            raise TypeError(msg)
        if bound < 1:
            msg = f"{label} must be at least 1, got {bound}"
            raise ValueError(msg)
        if ceiling is not None and bound > ceiling:
            msg = f"{label} must be at most {ceiling} (ADR-0231 §5), got {bound}"
            raise ValueError(msg)


#: ISO-4217's alphabetic form is three letters — ``ToolCost.currency``'s own rule
#: (ADR-0016 §4), which ADR-0236 §2 says is the code's whole domain here too.
_CURRENCY_CODE_LENGTH: Final = 3


def _checked_cost(amount: Decimal | None, currency: str | None) -> ToolCost | None:
    """The declared cost a configured fake carries, or ``None`` for absence.

    ADR-0236 §7's parity clause: this fake takes "the same pair, in the same domain,
    and builds its declaration the same way", and it is "refused every state a
    deployment cannot be in". The module's own posture is what governs — a fake
    *"ruled on more leniently than the real thing would let a consumer's policy test
    pass for a reason no deployment enjoys"* — and a fake that could be made
    **cheaper** to rule on than any deployment can be is exactly that failure, on the
    one field ADR-0236 moves.

    **A ``FREE`` basis is refused by there being no parameter that could ask for
    one** (§3), which is the structural form of the prohibition rather than a check:
    the two states this returns are the whole of what a deployment can reach.

    **The countability predicate is imported and not restated.**
    :func:`ai_assistant.testing.spend.countable` is ADR-0194 §1's predicate as this
    package already states it, and reaching for it here crosses no subsystem boundary
    — which is why the production builder needs its own statement and this fake does
    not.

    Args:
        amount: ``Settings.web_search_cost_per_call``, or ``None``.
        currency: ``Settings.web_search_cost_currency``, or ``None``.

    Returns:
        The ``PER_CALL`` cost where both are given, and ``None`` where neither is.

    Raises:
        TypeError: If ``amount`` is not an exact ``Decimal``. The type is part of the
            domain for the two bounds' reason, and the canonical fake must not be the
            looser of the two.
        ValueError: If exactly one of the two is given; if ``amount`` is non-finite,
            negative, or not countable under ADR-0194 §1; or if ``currency`` is not
            exactly three uppercase ASCII letters.
    """
    if (amount is None) != (currency is None):
        given = "cost_per_call" if currency is None else "cost_currency"
        missing = "cost_currency" if currency is None else "cost_per_call"
        msg = (
            f"{given} is given and {missing} is not; a declared per-call cost needs both "
            f"the figure and the ISO-4217 code it is denominated in (ADR-0236 §1)"
        )
        raise ValueError(msg)
    if amount is None or currency is None:
        return None
    if type(amount) is not Decimal:
        msg = f"cost_per_call must be a Decimal, got {amount!r}"
        raise TypeError(msg)
    if not amount.is_finite():
        msg = f"cost_per_call must be finite (ADR-0236 §2), got {amount!r}"
        raise ValueError(msg)
    if amount < 0:
        msg = f"cost_per_call must not be negative (ADR-0236 §2), got {amount!r}"
        raise ValueError(msg)
    if not countable(amount):
        msg = (
            f"cost_per_call must be countable — below 1E15 and to at most nine "
            f"fractional digits (ADR-0194 §1), got {amount!r}"
        )
        raise ValueError(msg)
    if len(currency) != _CURRENCY_CODE_LENGTH or not (
        currency.isascii() and currency.isupper() and currency.isalpha()
    ):
        msg = f"cost_currency must be three uppercase ASCII letters (ISO-4217), got {currency!r}"
        raise ValueError(msg)
    return ToolCost(basis=CostBasis.PER_CALL, amount=amount, currency=currency)


def _check_source(name: str, origin: str | None, reported_at: datetime) -> None:
    """Refuse a source this fake could not mint an attested record for.

    Every one of these is refused **where it is configured** rather than where it would
    bite, which is the whole posture of a canonical fake: a state this fake cannot
    answer from is one that raises out of :meth:`FakeWebSearcher.search` at an
    arbitrary later call, and ADR-0231 §17 says only a cancellation leaves that member.

    Args:
        name: The source instance.
        origin: The connected account's origin, or ``None`` for none.
        reported_at: The instant a scripted response declares.

    Raises:
        ValueError: If ``name`` is blank or is a value ``Identifier`` would strip —
            §17's clause, and §10 requires this value and a record's ``reported_by``
            to be **equal**, so a searcher named ``" search "`` would mint one no
            equality could hold; if ``origin`` is present and blank; or if
            ``reported_at`` is not timezone-aware, which ``UtcInstant`` refuses in
            every field this fake puts it in.
    """
    if not name.strip():
        msg = f"name must be non-blank, got {name!r}"
        raise ValueError(msg)
    if name.strip() != name:
        msg = f"name must be a value Identifier accepts unchanged, got {name!r}"
        raise ValueError(msg)
    if origin is not None and not origin.strip():
        msg = f"origin must hold text, or be None entirely, got {origin!r}"
        raise ValueError(msg)
    if reported_at.tzinfo is None or reported_at.utcoffset() is None:
        msg = f"reported_at must be timezone-aware, got {reported_at!r}"
        raise ValueError(msg)


@final
class FakeWebSearcher:
    """A scriptable, conforming ``WebSearcher`` over a mapping (ADR-0231 §17)."""

    def __init__(  # noqa: PLR0913 — a script, an identity, an origin, a refusal script, an instant, two bounds, ADR-0236 §7's cost pair and an id factory; each is one knob a consumer sets on its own
        self,
        contents: Mapping[str, Sequence[str]] | None = None,
        *,
        name: str = DEFAULT_SEARCH_SOURCE_NAME,
        origin: str | None = DEFAULT_SEARCH_ORIGIN,
        results: Sequence[str] = (DEFAULT_SEARCH_CONTENT,),
        refusals: Mapping[str, SearchRefusal] | None = None,
        reported_at: datetime = DEFAULT_REPORTED_AT,
        max_results: int = DEFAULT_MAX_RESULTS,
        max_result_chars: int = DEFAULT_MAX_RESULT_CHARS,
        cost_per_call: Decimal | None = None,
        cost_currency: str | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Create a searcher over a scripted set of answers.

        Args:
            contents: What this searcher brings back for a given query — one
                content per record, in the order they are minted. A query with no
                entry gets ``results``.
            name: The source instance this searcher names itself, and what a minted
                record's ``reported_by`` carries. Non-blank and unchanged by
                ``Identifier``'s validation, checked here rather than at the first
                mint (ADR-0231 §17).
            origin: The origin :meth:`request` names, or ``None`` for a deployment
                that connected no search account — under which :meth:`request`
                answers ``None`` and :meth:`search` is unreachable, because there is
                no request to rule on.
            results: The contents every unscripted query gets.
            refusals: Queries whose search refuses, and the class each refuses with,
                so a consumer can drive every :class:`SearchRefusal` member without a
                provider. A query named here refuses **even where ``contents`` also
                names it**: a scripted refusal is the more specific instruction, and
                a fake that silently preferred the records would make a consumer's
                refusal branch untestable in the one case it is easiest to write by
                accident.
            reported_at: The instant a scripted response declares, on the provider's
                own clock (ADR-0231 §10, ADR-0092 §3). Timezone-aware, which
                ``UtcInstant`` requires and this refuses at construction rather than
                at a mint. Every minted record is attested to it, which
                ``SearchOutcome`` enforces anyway.
            max_results: The bound this searcher was configured with —
                ``Settings.search_max_results``. At most this many records are
                minted, whatever a script named. From 1 to
                :data:`DEFAULT_MAX_RESULTS`, which is ADR-0231 §5's whole stated
                domain and not merely its default.
            max_result_chars: ``Settings.search_max_result_chars``, counted on the
                quoted rendering as ADR-0230 §6 counts it. A scripted content beyond
                it is **dropped** at :meth:`search`, never truncated.
            cost_per_call: ``Settings.web_search_cost_per_call`` — the operator's own
                per-call figure, which this fake's declaration then carries as a
                ``PER_CALL`` cost (ADR-0236 §1, §7). Set it with ``cost_currency`` or
                not at all; with neither, the declaration carries
                :data:`FAKE_WEB_SEARCH`'s own ``UNKNOWN`` cost, which is the state
                ADR-0236 §4 governs and the one every existing consumer keeps.
            cost_currency: ``Settings.web_search_cost_currency`` — the ISO-4217 code
                that figure is denominated in. **There is no argument of any name
                that produces a ``FREE`` basis** (ADR-0236 §3): a deployment asserting
                a free tier states a zero figure with the currency it is denominated
                in, and this fake takes exactly that.
            id_factory: Mints each record's id. Defaults to a fresh UUID hex, and is
                injectable so a suite can assert over a value it chose.

        Raises:
            TypeError: If ``max_results`` or ``max_result_chars`` is not an ``int``
                (``bool`` included), if ``cost_per_call`` is not a ``Decimal``, or if
                a value of ``refusals`` is not a
                :class:`SearchRefusal` member. ``SearchRefusal`` is a ``StrEnum``, so
                ``"no_result"`` compares equal to a member without being one, and a
                fake that took it would raise out of :meth:`search` at the call it
                was scripted for.
            ValueError: If ``max_results`` or ``max_result_chars`` is below 1, if
                ``max_results`` is above ADR-0231 §5's ceiling of three, if
                ``reported_at`` is not timezone-aware, if
                ``name`` is blank or is a value ``Identifier`` would strip, if
                ``origin`` is present and blank, or if the cost pair is outside
                ADR-0236 §2's domain — exactly one of the two given, a non-finite,
                negative or uncountable amount, or a malformed currency code. Each is
                a state this fake could not answer from, refused here rather than at
                an arbitrary later call — which is the one thing ADR-0231 §17 says
                never leaves either member.
        """
        _check_bounds(max_results, max_result_chars)
        _check_source(name, origin, reported_at)
        cost = _checked_cost(cost_per_call, cost_currency)
        #: This fake's own registered declaration, built per instance exactly as
        #: `build_web_search_integration` builds the production one (ADR-0236 §1):
        #: the module constant is never mutated, and where the pair is unset the
        #: constant itself is carried rather than an equal copy of it.
        self._declaration = (
            FAKE_WEB_SEARCH if cost is None else FAKE_WEB_SEARCH.model_copy(update={"cost": cost})
        )
        self._name = name
        self._origin = origin
        self._contents = {query: tuple(scripted) for query, scripted in (contents or {}).items()}
        self._results = tuple(results)
        self._refusals = dict(refusals or {})
        for query, refusal in self._refusals.items():
            if type(refusal) is not SearchRefusal:
                # `SearchOutcome.refusal` is typed to the enum, so a plain string
                # would raise out of `search` at the call it was scripted for.
                # `type(...) is not` rather than `isinstance`, because the annotation
                # already forbids this and mypy reads an `isinstance` narrowing as
                # unreachable: this guard is for the caller who ignored it, who is
                # the only caller who can reach it.
                msg = (
                    f"a scripted refusal must be a SearchRefusal member, got "
                    f"{refusal!r} for {query!r}"
                )
                raise TypeError(msg)
        self._reported_at = reported_at
        self._max_results = max_results
        self._max_result_chars = max_result_chars
        self._id_factory = id_factory
        self._resource = SuspendableResource()
        #: Every query this searcher's :meth:`request` was handed, in call order.
        #: Appended on entry, so ADR-0231 §18's arm 4a can assert what a *refused*
        #: composition did not produce as well as what a successful one did.
        self.requested: list[str] = []
        #: Every call this searcher's :meth:`search` was handed, in call order.
        #: Appended on entry, so arm 3's "``search`` is never reached" is the absence
        #: of a row rather than the absence of a completed one.
        self.searched: list[ToolCall] = []

    @property
    def name(self) -> str:
        """The configured source this searcher serves (ADR-0231 §10, §17)."""
        return self._name

    @property
    def log(self) -> ResourceLog:
        """When each call was inside this fake's modelled resource (ADR-0060)."""
        return self._resource.log

    def suspend_next(self) -> LoopSuspension:
        """Arm the next :meth:`search` to suspend inside the modelled resource.

        Returns:
            The handle a suite waits on and releases.

        Raises:
            RuntimeError: If a suspension is already armed.
        """
        return self._resource.suspend_next()

    async def request(self, query: str, /) -> ActionRequest | None:
        """Propose the search ``query`` would make, or answer that there is none.

        **One positional parameter and no keyword parameters**, which the
        conformance suite checks against the runtime signature. This fake holds no
        store, no supply and no listing — there is nothing else it *could* be handed.

        Args:
            query: The query one composition wrote.

        Returns:
            The request to rule on, carrying this fake's own declaration — which is
            :data:`FAKE_WEB_SEARCH` where no cost was configured and its ``PER_CALL``
            twin where one was (ADR-0236 §1) — or ``None`` where this fake was built
            with no connected account.
        """
        self.requested.append(query)
        if self._origin is None:
            return None
        parameters: dict[str, FrozenJson] = {"origin": self._origin, "query": query}
        return ActionRequest(tool=self._declaration, parameters=parameters)

    async def search(self, call: ToolCall, /) -> SearchOutcome:
        """Return the scripted answer for the query ``call`` carries.

        Args:
            call: The authorised call. Its ``request.parameters["query"]`` is what
                selects the scripted answer, so a test scripts by the query it
                expects to have been composed.

        Returns:
            The outcome scripted for that query: its refusal where one was scripted,
            :attr:`SearchRefusal.NO_RESULT` where every scripted content is beyond
            this fake's content bound, and otherwise up to ``max_results`` records
            carrying those contents in order.

        Raises:
            CancelledError: Re-raised unchanged when a call armed by
                :meth:`suspend_next` is cancelled from outside while suspended, and
                converted into neither an outcome nor a refusal (ADR-0060, §17).
        """
        self.searched.append(call)
        async with self._resource.held():
            query = call.request.parameters.get("query")
            refusal = self._refusals.get(query) if isinstance(query, str) else None
            if refusal is not None:
                return SearchOutcome(refusal=refusal)
            scripted = (
                self._contents.get(query, self._results)
                if isinstance(query, str)
                else self._results
            )
            minted = tuple(
                self._mint(content)
                for content in scripted[: self._max_results]
                # ADR-0231 §10's drop, counted on the quoted rendering: the siblings
                # are still minted, and where this takes the last one the search
                # yielded nothing rather than failing.
                if len(json.dumps(content)) <= self._max_result_chars
            )
            if not minted:
                return SearchOutcome(refusal=SearchRefusal.NO_RESULT)
            return SearchOutcome(reported_at=self._reported_at, records=minted)

    def _mint(self, content: str) -> MemoryRecord:
        """One ``SEMANTIC``, ``EXTERNAL``-sourced record carrying ``content``.

        Args:
            content: The transcription this record carries, verbatim.

        Returns:
            The record, attested to this fake's own report instant.
        """
        return SemanticMemory(
            id=self._id_factory() if self._id_factory is not None else uuid4().hex,
            content=content,
            fact=content,
            provenance=Provenance(
                source=MemorySource.EXTERNAL,
                confidence=_ATTESTED_CONFIDENCE,
                evidence=(),
                last_updated=self._reported_at,
                last_confirmed_at=self._reported_at,
                attestation=Attestation(
                    reported_by=self._name,
                    reported_at=self._reported_at,
                    # This producer states no position for a result in the source's
                    # own world, and a rank is not a pair of instants (ADR-0117 §2).
                    extent=None,
                ),
                # Asserts nothing in this band (ADR-0106 §1): the externality this
                # record carries is `MemorySource.EXTERNAL`, which `band_of` places
                # in `ATTESTED`, and this field is the `DERIVED` band's question.
                derived_from_external=False,
            ),
            topics=(),
            about_person=None,
        )


__all__ = [
    "DEFAULT_MAX_RESULTS",
    "DEFAULT_MAX_RESULT_CHARS",
    "DEFAULT_REPORTED_AT",
    "DEFAULT_SEARCH_CONTENT",
    "DEFAULT_SEARCH_ORIGIN",
    "DEFAULT_SEARCH_SOURCE_NAME",
    "FAKE_WEB_SEARCH",
    "FAKE_WEB_SEARCH_ID",
    "FakeWebSearcher",
]
