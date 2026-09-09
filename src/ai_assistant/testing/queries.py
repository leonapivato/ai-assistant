"""A canonical :class:`~ai_assistant.core.protocols.QueryComposer` fake (ADR-0231 §17).

The shared test double for the ``QueryComposer`` contract, so a subsystem that
services a search — `orchestration`'s read servicer — can exercise every branch of
its own pipeline without a model call and without importing the concrete composer
(``CLAUDE.md`` golden rule 1).

**It records what it was handed, and that is what makes ADR-0231 §18's arms
possible.** Test 4 asserts that the composer's own model call carried the utterance
and no byte of a record's span; test 4a asserts that the *searcher* received the
composer's output byte for byte, that a refused composition reaches ``request`` not
at all, and that no supply value appears in anything ``request`` received. The second
of those is asserted at a seam no signature can decide, so it needs a composer whose
answers a test chooses and whose inputs a test can read back: :attr:`
FakeQueryComposer.utterances` is that record.

It is scriptable to every state ADR-0231 §3 distinguishes, which is what a consumer
needs to drive its own disposition (§13):

* a **composed query**, per utterance or as one default answer for every utterance;
* a **refusal**, per utterance, into any :class:`QueryRefusal` member — so a consumer
  can reach each of the four ``COMPOSER_*`` dispositions without a model; and
* a composition **over the configured bound**, which this fake refuses
  :attr:`QueryRefusal.TOO_LONG` itself rather than truncating, exactly as §3 requires
  of a configured composer.

**And a fourth, which is what makes the cancellation clause testable at all.**
``compose`` runs inside a
:class:`~ai_assistant.testing.cancellation.SuspendableResource`, so a suite can arm
:meth:`FakeQueryComposer.suspend_next` and cancel a call that has *demonstrably*
arrived at an await. Without it the clause passes vacuously: a fake that completes
immediately can only be cancelled before it starts, which exercises none of the code
an implementation would use to catch a ``CancelledError`` during a model call and
convert it into a refusal.

**Not a fault injector.** Everything here conforms. A consumer that needs a composer
which *breaks* the contract on purpose — one returning an outcome carrying both
halves, or a query over the bound it was configured with — is testing a reaction to a
non-conforming producer and supplies its own stub for it. This fake must stay the
thing a conforming implementation is compared against.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final

from ai_assistant.core.types import QueryOutcome, QueryRefusal, encodable_text
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import SearchSupply
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: What this fake composes unless a test names something else. Distinctive enough
#: that a test asserting it reached a searcher is not asserting a coincidence.
DEFAULT_COMPOSED_QUERY: Final = "fake composed query"

#: ADR-0231 §5's named default for ``search_query_max_chars``, so a fake constructed
#: with no bound is bounded the way a default deployment is.
DEFAULT_QUERY_MAX_CHARS: Final = 256


@final
class FakeQueryComposer:
    """A scriptable, conforming ``QueryComposer`` over a mapping (ADR-0231 §17)."""

    def __init__(
        self,
        queries: Mapping[str, str] | None = None,
        *,
        query: str = DEFAULT_COMPOSED_QUERY,
        refusals: Mapping[str, QueryRefusal] | None = None,
        max_chars: int = DEFAULT_QUERY_MAX_CHARS,
    ) -> None:
        """Create a composer over a scripted set of answers.

        Args:
            queries: What this fake composes for a given utterance. An utterance
                with no entry gets ``query``.
            query: The composition every unscripted utterance gets. Non-blank, so a
                default this fake could not return is refused here rather than at
                the first call.
            refusals: Utterances whose composition refuses, and the class each
                refuses with, so a consumer can drive every :class:`QueryRefusal`
                member without a model. An utterance named here refuses **even
                where ``queries`` also names it**: a scripted refusal is the more
                specific instruction, and a fake that silently preferred the query
                would make a consumer's refusal branch untestable in the one case
                it is easiest to write by accident.
            max_chars: The bound this composer was configured with —
                ``Settings.search_query_max_chars`` (ADR-0231 §5). A scripted query
                beyond it is **refused** :attr:`QueryRefusal.TOO_LONG` at
                :meth:`compose`, never truncated, which is how a suite drives §3's
                refuse-rather-than-truncate clause over a subject whose answer it
                chose.

        Raises:
            TypeError: If ``max_chars`` is not an ``int`` (``bool`` included) — the
                type is part of the domain for the concrete composer's reason, and
                the canonical fake must not be the looser of the two; or if a value
                of ``refusals`` is not a :class:`QueryRefusal` member. ``QueryRefusal``
                is a ``StrEnum``, so ``"declined"`` compares equal to a member without
                being one, and a fake that took it would raise out of :meth:`compose`
                at the call it was scripted for.
            ValueError: If ``max_chars`` is below 1; or if ``query`` or any value of
                ``queries`` is blank or has no UTF-8 encoding — both halves of what
                :attr:`~ai_assistant.core.types.QueryOutcome.query` accepts, refused
                here because a fake configurable into a state it cannot answer from
                is one that raises out of :meth:`compose` at an arbitrary later call,
                which is the one thing ADR-0231 §3 says never leaves that member.
        """
        if isinstance(max_chars, bool) or type(max_chars) is not int:
            msg = f"max_chars must be an integer, got {max_chars!r}"
            raise TypeError(msg)
        if max_chars < 1:
            msg = f"max_chars must be at least 1, got {max_chars}"
            raise ValueError(msg)
        scripted = dict(queries or {})
        for utterance, composition in [*scripted.items(), ("", query)]:
            if not composition.strip():
                msg = (
                    f"a scripted composition must be non-blank, got "
                    f"{composition!r} for {utterance!r}"
                )
                raise ValueError(msg)
            try:
                encodable_text(composition)
            except ValueError as exc:
                # Both halves of what `QueryOutcome.query` accepts, decided here with
                # the field's own function: a fake scripted with a lone surrogate
                # would raise out of `compose` at an arbitrary later call, which is
                # the one thing ADR-0231 §3 says never leaves that member.
                msg = (
                    f"a scripted composition must have a UTF-8 encoding, got "
                    f"{composition!r} for {utterance!r}"
                )
                raise ValueError(msg) from exc
        self._queries = scripted
        self._query = query
        self._refusals = dict(refusals or {})
        for utterance, refusal in self._refusals.items():
            if type(refusal) is not QueryRefusal:
                # `QueryOutcome.refusal` is typed to the enum, so a plain string here
                # would raise out of `compose` at the call it was scripted for —
                # `type(...) is not` rather than `isinstance`, for `max_chars`'s
                # reason two guards up: the annotation already forbids this, so mypy
                # reads an `isinstance` narrowing as unreachable and this guard is
                # for the caller who ignored the annotation, which is the only
                # caller who can reach it.
                # again the one thing ADR-0231 §3 says never leaves that member, and
                # again in a fake whose whole job is to be the conforming subject. A
                # `StrEnum` makes this the easy mistake: `"declined"` *looks* like a
                # member and compares equal to one, and is not an instance of it.
                msg = (
                    f"a scripted refusal must be a QueryRefusal member, got "
                    f"{refusal!r} for {utterance!r}"
                )
                raise TypeError(msg)
        self._max_chars = max_chars
        self._resource = SuspendableResource()
        #: Every utterance this composer was handed, in call order. Appended to
        #: **after** the outcome is decided is not good enough for ADR-0231 §18's
        #: arms — a test asserting that a refused composition reached no searcher
        #: still wants to see that the composer itself was called — so it is
        #: appended on entry.
        #:
        #: **Still the utterances and not the supplies**, though ADR-0238 §2 widened
        #: what ``compose`` takes: this is the record ADR-0231 §18's test 4a reads to
        #: assert that no supply value reached the searcher, and a list of supplies
        #: would answer a different question. :attr:`supplies` beside it is the whole
        #: value, for a consumer that needs the records.
        self.utterances: list[str] = []
        #: Every supply this composer was handed, in call order — the whole value,
        #: beside :attr:`utterances`. It is what lets a consumer's test assert *which*
        #: records a servicing site put in front of a composer, which is the fact
        #: ADR-0238 §2's two admissible populations turn on.
        self.supplies: list[SearchSupply] = []

    @property
    def log(self) -> ResourceLog:
        """When each call was inside this fake's modelled resource (ADR-0060)."""
        return self._resource.log

    def suspend_next(self) -> LoopSuspension:
        """Arm the next :meth:`compose` to suspend inside the modelled resource.

        Returns:
            The handle a suite waits on and releases.

        Raises:
            RuntimeError: If a suspension is already armed.
        """
        return self._resource.suspend_next()

    async def compose(self, supply: SearchSupply, /) -> QueryOutcome:
        """Return the scripted composition for ``supply``, or its refusal.

        **One positional parameter and no keyword parameters**, which is the clause
        the safety claim rests on and the one the conformance suite checks against the
        runtime signature (ADR-0231 §3, kept by ADR-0238 §2). This fake holds no
        store, no policy and no listing — there is nothing else it *could* be handed.

        **Scripted by utterance, and the records are accepted and unused**, which
        mirrors the production composer under the contract lane: a supply carrying
        records and one carrying none compose identically. What the fake does record
        is both — the utterance in :attr:`utterances` and the whole value in
        :attr:`supplies` — so a consumer's test can assert which records a servicing
        site put in front of a composer without this fake having to interpret them.

        Args:
            supply: What this composition may be composed over.

        Returns:
            The outcome scripted for this supply's utterance: its refusal where one
            was scripted, :attr:`QueryRefusal.TOO_LONG` where the scripted composition
            is longer than this fake's bound, and otherwise that composition.

        Raises:
            CancelledError: Re-raised unchanged when a call armed by
                :meth:`suspend_next` is cancelled from outside while suspended, and
                converted into neither a query nor a refusal (ADR-0060, ADR-0231 §3).
        """
        utterance = supply.utterance
        self.utterances.append(utterance)
        self.supplies.append(supply)
        async with self._resource.held():
            refusal = self._refusals.get(utterance)
            if refusal is not None:
                return QueryOutcome(refusal=refusal)
            composed = self._queries.get(utterance, self._query)
            if len(composed) > self._max_chars:
                return QueryOutcome(refusal=QueryRefusal.TOO_LONG)
            return QueryOutcome(query=composed)
