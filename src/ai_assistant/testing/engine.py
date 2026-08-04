"""The canonical fake for :class:`~ai_assistant.core.protocols.AssistantEngine`.

``CONTRIBUTING.md`` -> "Adding a Protocol" makes a canonical fake one third of the
triad, and ADR-0087 §6 says what makes *this* one load-bearing rather than
convenient: it is the **second implementation** of the engine surface, arriving in
ADR-0084 §5's change 3 — before the hub, before the `wire` package, before any
client. §4 of ADR-0084 rules that the size limit is a clause "*every*
implementation enforces", with "the conformance suite … what holds them to it", so
this fake and the concrete
:class:`~ai_assistant.orchestration.engine.Engine` are the first two things ever
held to it together.

**It is a working in-memory engine rather than a recorder**, and that is
deliberate. A double that answered every call with a scripted value could satisfy
a suite while enforcing none of the five clauses ADR-0085 states over behaviour —
the page-size default, identifier validation and normalisation, pre-``await``
materialisation of the filters, local refusal of a malformed page argument, and
the size limit in both directions. Here ``learn`` really stores a belief,
``beliefs`` really pages it, ``forget`` really destroys it, so the suite can
exercise those clauses end to end against a subject it can also set up cheaply.

**It has no lifecycle, and that is the point of ADR-0083 §8.** There is no
``start`` and no ``aclose``: they are not on the Protocol, because a client that
could call ``aclose()`` could shut down the hub from a spoke. An implementation
without a lifecycle does not have to invent one to conform, and this is the
evidence that the Protocol really does leave it out.

Every scriptable behaviour is a plain attribute rather than a constructor
argument, so a test changes one thing without restating the rest.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING

from ai_assistant.core.errors import (
    InvalidGrantError,
    UngrantableSourceError,
    UnknownContinuationError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    ActionPlan,
    AnswerKind,
    AnswerOutcome,
    Belief,
    BeliefBand,
    BeliefSummary,
    Confirmation,
    ContinuationToken,
    ConversationDigest,
    ConversationSummary,
    CurrentContext,
    Disposition,
    ExecutionState,
    Goal,
    GrantableSource,
    GrantScope,
    IngestSummary,
    LearnDecision,
    LearnOutcome,
    MemoryKind,
    MemorySource,
    ObservationReport,
    Provenance,
    Question,
    QuestionState,
    SkipReason,
    SourceGrant,
    StepExecution,
    StepOutcome,
    StepStatus,
    TimeOfDay,
    TurnOutcome,
    TurnResult,
    encodable_text,
)
from ai_assistant.orchestration.payloads import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    check_arguments,
    check_payload,
    grant_scope,
    identifier,
    non_blank_text,
    page_argument,
    positive_page_argument,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import (
        EncodableText,
        FeedbackEvent,
        Identifier,
        NonBlankEncodableText,
    )

#: A fixed instant, so a fake engine's output is deterministic without a clock.
_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

#: How far each activity stamp advances per event. A logical clock rather than a
#: real one: it keeps the ordering deterministic and keeps the fake free of a wall
#: clock.
_TICK = timedelta(seconds=1)

#: The confidence a stored belief is held at here. Below 1.0 so a
#: ``DERIVED``-banded record would still validate, and unadjusted because nothing
#: in this fake loses evidence.
_CONFIDENCE = 0.9


class FakeAssistantEngine:
    """An in-memory :class:`~ai_assistant.core.protocols.AssistantEngine`.

    **It reaches for `orchestration.payloads` rather than growing its own
    encoder**, and ADR-0087 §7 is what makes that safe: conformance to the
    canonical encoding is defined by *output*, so "two encoders may exist without
    the contract weakening" — and one encoder cannot make two implementations
    disagree about which calls are refused, which is the property change 3 needs.
    ADR-0084 §6 places the codec in the `wire` package, which does not exist yet,
    and ADR-0085 §8c forecloses a ``core``-owned one; where the encoder finally
    lives is ADR-0087 §9's open question and change 4's to answer.

    Attributes:
        turn_outcome: What :meth:`converse` returns. Defaults to a turn whose plan
            had no step — a real ratified shape, not a stub.
        observation: What :meth:`observe` returns.
        answered: What :meth:`answer` returns, or ``None`` to synthesise one from
            the question's own state.
    """

    def __init__(self, *, max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES) -> None:
        """Create an engine holding nothing.

        Args:
            max_payload_bytes: The contract limit ADR-0085 §8c declares, in bytes.
                A conformance test sets it small so the boundary is cheap to reach;
                the default is ADR-0084 §3's 16 MiB frame size less §8b's 512-byte
                envelope reserve, which is what a deployment gets by saying nothing.
        """
        self._max_payload_bytes = max_payload_bytes
        self.beliefs_held: dict[str, Belief] = {}
        self.questions_open: dict[str, Question] = {}
        self.questions_interrupted: dict[str, Question] = {}
        #: Questions in a terminal state — declined, applied, stale, re-deferred.
        #: Neither enumeration shows one and :meth:`answer` refuses it, because
        #: "that question is not open" is what the surface has to say about it.
        self.questions_settled: dict[str, Question] = {}
        self.conversations_held: dict[str, ConversationDigest] = {}
        #: When each conversation was last active — set at creation and refreshed
        #: whenever a turn begins against it (ADR-0074 §2). Held beside the digests
        #: rather than on them because a
        #: :class:`~ai_assistant.core.types.ConversationDigest` is the deletion
        #: ceremony's shape and carries no activity stamp.
        self.activity: dict[str, datetime] = {}
        self._ticks = count(1)
        self.parked: dict[str, Confirmation] = {}
        self.turn_outcome: TurnOutcome | None = None
        self.observation: ObservationReport = ObservationReport()
        self.answered: AnswerOutcome | None = None
        #: The grantable sources this engine holds, by declared identity, each
        #: mapped to its configured location or to ``None`` where it has none
        #: (ADR-0102 §6). Scriptable with :meth:`hold_source`, so a client's own
        #: refusal paths — a source with a location and one without, granted and
        #: ungranted — are all reachable from a test (ADR-0102 §12 item 3).
        self.sources_held: dict[str, str | None] = {}
        #: Every grant and revocation this engine recorded, in the order it
        #: recorded them. Both kinds live here, because revocation is an **append**
        #: and never a mutation (ADR-0097 §4).
        self.grants_recorded: list[SourceGrant] = []
        #: What stamps ``decided_at`` on a grant or a revocation. Scriptable, and
        #: **that is what makes ADR-0102 §3's second clause testable at all**: the
        #: case that distinguishes a stated liveness from a derived one is a
        #: revocation timestamped *earlier* than the grant it revokes, which
        #: ADR-0097 §4 permits explicitly — and no sequence of surface calls can
        #: produce it, because the engine reads the clock. A test hands over one
        #: that runs backwards.
        #:
        #: **Fixed rather than ticking**, unlike the conversation activity stamp: a
        #: grant's ``decided_at`` is not an ordering invariant of anything (ADR-0097
        #: §4 derives liveness from ``revokes`` alone and never compares two
        #: instants), so a fake that advanced it would be asserting a sequence the
        #: contract does not have — and would put every record at its own instant,
        #: which is exactly where ``recent``'s ``id`` tie-break stops being
        #: exercised.
        self.grant_clock: Callable[[], datetime] = lambda: _AT
        #: Every call, in order, as ``(method, arguments)`` — so a test can assert
        #: what reached the engine without reaching into its state.
        self.calls: list[tuple[str, dict[str, object]]] = []

    # --- the two turn calls -----------------------------------------------

    def _resolve(self, conversation_id: str | None) -> str:
        """Continue the conversation named, or start one where none was (ADR-0074 §1).

        **An id this engine does not know is refused, not silently started.**
        Silently starting one turns a typo or a stale copy-paste into "my
        conversation vanished" and lands the user's continuation somewhere they
        cannot find — and a fake that started one instead would let a client's tests
        pass over the exact path the real engine refuses.
        """
        if conversation_id is None:
            return self.start_conversation(f"c-{len(self.conversations_held) + 1}")
        if conversation_id not in self.conversations_held:
            msg = f"no conversation {conversation_id!r}"
            raise UnknownConversationError(msg)
        self.activity[conversation_id] = self._tick()
        return conversation_id

    async def converse(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, as the Protocol declares it
        conversation_id: Identifier | None = None,
    ) -> TurnOutcome:
        """Run one turn against a conversation, minting one if none is named."""
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        check_arguments(
            "converse",
            max_bytes=self._max_payload_bytes,
            utterance=utterance,
            timeout=timeout,
            conversation_id=selected,
        )
        self.calls.append(("converse", {"utterance": utterance, "conversation_id": selected}))
        held = self._resolve(selected)
        outcome = self.turn_outcome or TurnOutcome(turn=_turn(utterance), conversation_id=held)
        return self._checked(outcome, "converse")

    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, as the Protocol declares it
    ) -> TurnOutcome:
        """Answer a parked confirmation, or refuse a token this engine cannot resolve."""
        check_arguments(
            "resume",
            max_bytes=self._max_payload_bytes,
            token=token,
            approved=approved,
            timeout=timeout,
        )
        self.calls.append(("resume", {"token": token.handle, "approved": approved}))
        if token.handle not in self.parked:
            msg = (
                "this token names no step awaiting confirmation in this engine; call "
                "pending_confirmations() to re-mint a token for any park that is still answerable"
            )
            raise UnknownContinuationError(msg)
        confirmation = self.parked.pop(token.handle)
        # **A denial is a result, not an exception** (ADR-0042 §4): the adapter
        # conveys consent, the policy rules on it, and the engine records and
        # executes. Only ``approved=False -> DENY`` is guaranteed; ``approved=True``
        # may still be refused. Raising here instead would give a client a failure
        # path the in-process engine does not have.
        resolved = StepOutcome(
            disposition=Disposition.EXECUTED if approved else Disposition.DENIED,
            state=ExecutionState(
                id=f"exec-{token.handle}",
                plan_id=f"plan-{token.handle}",
                steps=(
                    StepExecution(
                        step_id="step-1",
                        # A succeeded step names the decision that cleared it, and a
                        # denied one names why it was skipped: the type refuses a
                        # step that claims either without saying so (ADR-0004 §7).
                        status=StepStatus.SUCCEEDED if approved else StepStatus.SKIPPED,
                        attempts=1 if approved else 0,
                        approval_ref=f"decision-{token.handle}" if approved else None,
                        bound_tool=confirmation.tool_id if approved else None,
                        skip_reason=None if approved else SkipReason.APPROVAL_DENIED,
                        started_at=_AT if approved else None,
                        finished_at=_AT if approved else None,
                    ),
                ),
                updated_at=_AT,
            ),
            step_id="step-1",
            tool_id=confirmation.tool_id,
        )
        # ``turn`` is ``None`` here because this engine parks nothing from a live
        # turn — the shape a **recovered** park produces after a restart, which
        # ADR-0052 §3 ratifies. The *step* is what a resume is for and is always
        # present (ADR-0085 §4).
        return self._checked(TurnOutcome(turn=None, step=resolved), "resume")

    # --- the two accumulation legs ----------------------------------------

    async def learn(self, event: FeedbackEvent) -> LearnOutcome:
        """Fold one piece of feedback into memory, storing exactly one belief."""
        check_arguments("learn", max_bytes=self._max_payload_bytes, event=event)
        self.calls.append(("learn", {"event": event}))
        record_id = f"rec-{len(self.beliefs_held) + 1}"
        self.hold(record_id, content=event.content)
        outcome = LearnOutcome(
            results=(
                IngestSummary(
                    decision=LearnDecision.STORED,
                    record_id=record_id,
                    reason="the fake engine stores what it is told",
                ),
            )
        )
        return self._checked(outcome, "learn")

    async def observe(self, *, conversation_id: Identifier | None = None) -> ObservationReport:
        """Report what a passive observation pass would have done."""
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        check_arguments("observe", max_bytes=self._max_payload_bytes, conversation_id=selected)
        self.calls.append(("observe", {"conversation_id": selected}))
        if selected is not None and selected not in self.conversations_held:
            msg = f"no conversation {selected!r}"
            raise UnknownConversationError(msg)
        return self._checked(self.observation, "observe")

    # --- the inspection surface -------------------------------------------

    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[BeliefSummary, ...]:
        """List what is held, as summaries that carry counts and no citations."""
        # Materialised before the first await, so a caller that mutates the sequence
        # it passed cannot change which page it gets (ADR-0085 §3d). This engine
        # never suspends, which is one of the three ways ADR-0065 permits the clause
        # to be discharged; snapshotting anyway is what makes the property a
        # property of the code rather than of the fact that it happens not to await.
        selected_bands = None if bands is None else tuple(bands)
        selected_kinds = None if kinds is None else tuple(kinds)
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "beliefs",
            max_bytes=self._max_payload_bytes,
            bands=selected_bands,
            kinds=selected_kinds,
            limit=limit,
            offset=offset,
        )
        self.calls.append(("beliefs", {"bands": selected_bands, "kinds": selected_kinds}))
        matching = [
            _summary_of(belief)
            for belief in self.beliefs_held.values()
            if (selected_bands is None or belief.band in selected_bands)
            and (selected_kinds is None or belief.kind in selected_kinds)
        ]
        return self._checked(tuple(matching[offset : offset + limit]), "beliefs")

    async def belief(self, record_id: Identifier) -> Belief | None:
        """Read one belief with its citations, or ``None`` where none is held."""
        named = identifier(record_id, name="record_id")
        check_arguments("belief", max_bytes=self._max_payload_bytes, record_id=named)
        self.calls.append(("belief", {"record_id": named}))
        return self._checked(self.beliefs_held.get(named), "belief")

    async def forget(self, record_id: Identifier) -> bool:
        """Destroy one belief, reporting whether there was one to destroy."""
        named = identifier(record_id, name="record_id")
        check_arguments("forget", max_bytes=self._max_payload_bytes, record_id=named)
        self.calls.append(("forget", {"record_id": named}))
        return self._checked(self.beliefs_held.pop(named, None) is not None, "forget")

    # --- the deferred-question surface ------------------------------------

    async def questions(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[Question, ...]:
        """List the questions waiting for an answer."""
        self._check_page("questions", limit=limit, offset=offset)
        held = tuple(self.questions_open.values())
        return self._checked(held[offset : offset + limit], "questions")

    async def interrupted_questions(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[Question, ...]:
        """List the questions whose answer was begun and never recorded."""
        self._check_page("interrupted_questions", limit=limit, offset=offset)
        held = tuple(self.questions_interrupted.values())
        return self._checked(held[offset : offset + limit], "interrupted_questions")

    async def answer(self, question_id: Identifier, *, accept: bool) -> AnswerOutcome:
        """Answer one question, applying it or declining it."""
        named = identifier(question_id, name="question_id")
        check_arguments(
            "answer", max_bytes=self._max_payload_bytes, question_id=named, accept=accept
        )
        self.calls.append(("answer", {"question_id": named, "accept": accept}))
        if self.answered is not None:
            return self._checked(self.answered, "answer")
        question = self.questions_open.pop(named, None)
        if question is None:
            return self._checked(
                AnswerOutcome(kind=AnswerKind.NOT_OPEN, question_id=named), "answer"
            )
        if not accept:
            return self._checked(
                AnswerOutcome(kind=AnswerKind.REJECTED, question_id=named), "answer"
            )
        record_id = f"rec-{len(self.beliefs_held) + 1}"
        self.hold(record_id, content=question.content, kind=question.kind, band=question.band)
        return self._checked(
            AnswerOutcome(kind=AnswerKind.APPLIED, question_id=named, record_id=record_id), "answer"
        )

    async def forget_question(self, question_id: Identifier) -> bool:
        """Destroy one question, reporting whether there was one to destroy."""
        named = identifier(question_id, name="question_id")
        check_arguments("forget_question", max_bytes=self._max_payload_bytes, question_id=named)
        self.calls.append(("forget_question", {"question_id": named}))
        gone = (
            self.questions_open.pop(named, None)
            or self.questions_interrupted.pop(named, None)
            or self.questions_settled.pop(named, None)
        )
        return self._checked(gone is not None, "forget_question")

    # --- the conversation surface -----------------------------------------

    async def recent_conversations(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[ConversationSummary, ...]:
        """List conversations, in the order they were started."""
        self._check_page("recent_conversations", limit=limit, offset=offset)
        # **Activity descending, with the id breaking ties** (ADR-0074 §2). The
        # sort key is never ``last_turn_at``: ordering by "has a turn landed" would
        # sink a conversation the user opened a minute ago below one they abandoned
        # last week — and a fake that returned insertion order would let a client's
        # ordering tests pass while production rendered stale conversations first.
        ordered = sorted(
            self.conversations_held.values(),
            key=lambda digest: (self.activity[digest.id], digest.id),
            reverse=True,
        )
        held = tuple(
            ConversationSummary(
                id=digest.id,
                started_at=digest.started_at,
                last_active_at=self.activity[digest.id],
                last_turn_at=digest.last_turn_at,
            )
            for digest in ordered
        )
        return self._checked(held[offset : offset + limit], "recent_conversations")

    async def conversation(self, conversation_id: Identifier) -> ConversationDigest | None:
        """Show the count and span destroying one conversation would destroy."""
        named = identifier(conversation_id, name="conversation_id")
        check_arguments("conversation", max_bytes=self._max_payload_bytes, conversation_id=named)
        self.calls.append(("conversation", {"conversation_id": named}))
        return self._checked(self.conversations_held.get(named), "conversation")

    async def forget_conversation(self, conversation_id: Identifier) -> bool:
        """Destroy one conversation, reporting whether there was one to destroy."""
        named = identifier(conversation_id, name="conversation_id")
        check_arguments(
            "forget_conversation", max_bytes=self._max_payload_bytes, conversation_id=named
        )
        self.calls.append(("forget_conversation", {"conversation_id": named}))
        self.activity.pop(named, None)
        return self._checked(self.conversations_held.pop(named, None) is not None, "forget")

    # --- durable recovery --------------------------------------------------

    async def pending_confirmations(self) -> tuple[Confirmation, ...]:
        """Hand back every park that is still answerable, with a resolvable token."""
        self.calls.append(("pending_confirmations", {}))
        return self._checked(tuple(self.parked.values()), "pending_confirmations")

    # --- the grant surface (ADR-0102 §1) -----------------------------------

    async def grantable_sources(self) -> tuple[GrantableSource, ...]:
        """List the held sources, each with its location and its live grant.

        Every held source is enumerated, because :meth:`hold_source` refuses to
        hold one that could not be — see its own docstring for why the
        inadmissible cases are refused at the setter rather than modelled here.
        """
        self.calls.append(("grantable_sources", {}))
        return self._checked(
            tuple(
                GrantableSource(source=identity, location=location, live=self._live_grant(identity))
                for identity, location in self.sources_held.items()
            ),
            "grantable_sources",
        )

    async def grant(
        self, source: NonBlankEncodableText, *, scope: Sequence[GrantScope]
    ) -> SourceGrant:
        """Admit the source against the held identities, then record the grant.

        **``source`` is refused blank and normalised by nothing** (ADR-0102 §2), so
        this fake refuses ``grant(" calendar ")`` against a held ``"calendar"``
        exactly as the concrete engine does. Getting that wrong here would let a
        client's tests pass over the one path the wire annotation could have
        normalised, which is the direction nobody looks.
        """
        named = non_blank_text(source, name="source")
        uses = grant_scope(scope, name="scope")
        check_arguments("grant", max_bytes=self._max_payload_bytes, source=named, scope=uses)
        self.calls.append(("grant", {"source": named, "scope": uses}))
        if named not in self.sources_held:
            msg = (
                "no source by that name can be granted; call grantable_sources() and "
                "choose one of the identities it returns (ADR-0097 §9)"
            )
            raise UngrantableSourceError(msg)
        if self._live_grant(named) is not None:
            # What the store's atomic one-live-grant rule raises (ADR-0097 §10), so
            # the clause ADR-0102 §12 puts in the shared suite is reachable here.
            msg = f"the {named!r} source already has a live grant (ADR-0097 §4)"
            raise InvalidGrantError(msg)
        record = SourceGrant(
            id=f"grant-{len(self.grants_recorded) + 1}",
            source=named,
            scope=uses,
            decided_at=self.grant_clock(),
        )
        self.grants_recorded.append(record)
        return self._checked(record, "grant")

    async def revoke(self, source: NonBlankEncodableText) -> SourceGrant | None:
        """Withdraw the live grant on one source, applying **no** admission check.

        A value no held source declares is not refused for that (ADR-0102 §4): it
        finds no live grant and returns ``None``, which is what keeps a grant whose
        reader was later unconfigured revocable.
        """
        named = non_blank_text(source, name="source")
        check_arguments("revoke", max_bytes=self._max_payload_bytes, source=named)
        self.calls.append(("revoke", {"source": named}))
        live = self._live_grant(named)
        if live is None:
            return self._checked(None, "revoke")
        record = SourceGrant(
            id=f"grant-{len(self.grants_recorded) + 1}",
            source=live.source,
            scope=live.scope,
            decided_at=self.grant_clock(),
            revokes=live.id,
        )
        self.grants_recorded.append(record)
        return self._checked(record, "revoke")

    async def recent_grants(self, *, limit: int = DEFAULT_PAGE_SIZE) -> tuple[SourceGrant, ...]:
        """List every recorded grant and revocation, newest first."""
        positive_page_argument(limit, name="limit")
        check_arguments("recent_grants", max_bytes=self._max_payload_bytes, limit=limit)
        self.calls.append(("recent_grants", {"limit": limit}))
        # **Two sorts rather than one reversed key** (``SourceGrantStore.recent``):
        # the order is ``decided_at`` *descending* with ties broken by ``id``
        # *ascending*, and ``reverse=True`` over a compound key reverses **both**
        # — which puts ``grant-2`` above ``grant-1`` at one instant, the opposite
        # of what the contract states. Python's sort is stable, so sorting by the
        # tie-break first and the primary key second composes them correctly.
        by_id = sorted(self.grants_recorded, key=lambda record: record.id)
        ordered = sorted(by_id, key=lambda record: record.decided_at, reverse=True)
        return self._checked(tuple(ordered[:limit]), "recent_grants")

    def _live_grant(self, source: str) -> SourceGrant | None:
        """The grant on ``source`` no recorded revocation names (ADR-0097 §4).

        **Derived from the ``revokes`` relation alone**, never by comparing two
        ``decided_at`` values, which is what ADR-0102 §3's second normative clause
        exists for: a revocation timestamped *before* the grant it revokes is
        permitted, so a fake that ordered by time would report a withdrawn grant as
        live — on exactly the case the shared suite is written to reach.
        """
        revoked = {record.revokes for record in self.grants_recorded if record.revokes is not None}
        for record in self.grants_recorded:
            if record.source == source and record.revokes is None and record.id not in revoked:
                return record
        return None

    # --- setting one up ----------------------------------------------------

    def hold(
        self,
        record_id: str,
        *,
        content: str,
        kind: MemoryKind = MemoryKind.SEMANTIC,
        band: BeliefBand = BeliefBand.ASSERTED,
    ) -> Belief:
        """Put one belief in memory, and return it.

        The confidence is fixed and unadjusted: nothing here loses evidence, so
        there is no lost support for a presented value to have fallen with.
        """
        held = Belief(
            id=record_id,
            band=band,
            kind=kind,
            content=content,
            confidence=1.0 if band is BeliefBand.ASSERTED else _CONFIDENCE,
            last_updated=_AT,
        )
        self.beliefs_held[record_id] = held
        return held

    def _tick(self) -> datetime:
        """The next instant on this engine's logical clock.

        Strictly increasing rather than "one tick past whatever this conversation
        last had", which would let a continued conversation land *equal* to one
        started after it and leave the ordering to the tie-break.
        """
        return _AT + _TICK * next(self._ticks)

    def ask(self, question_id: str, *, content: str, state: QuestionState) -> Question:
        """Put one deferred question in the queue, and return it.

        ``state`` decides which enumeration it lands in, and **only ``OPEN`` is
        answerable**. An ``INTERRUPTED`` question is a *second*, separate list all
        the way to the surface, because offering it beside the answerable ones would
        present a claim that cannot be taken (ADR-0078 §8); every terminal state —
        declined, applied, stale, re-deferred — appears in neither list and answers
        ``NOT_OPEN``, because those are questions the user has no move left on.
        """
        question = Question(
            id=question_id,
            state=state,
            content=content,
            kind=MemoryKind.SEMANTIC,
            band=BeliefBand.ASSERTED,
            rationale="the fake engine was told to ask",
            reason="the policy wants a human answer",
            retires=(),
            asked_at=_AT,
            expires_at=None,
        )
        match state:
            case QuestionState.OPEN:
                self.questions_open[question_id] = question
            case QuestionState.INTERRUPTED:
                self.questions_interrupted[question_id] = question
            case _:
                self.questions_settled[question_id] = question
        return question

    def start_conversation(self, conversation_id: str) -> str:
        """Record one conversation, and return its id.

        Its activity stamp starts one tick later than the last conversation's, so
        "most recently active first" is a fact the ordering can be tested against
        rather than an accident of a fixed clock.
        """
        started = self._tick()
        self.conversations_held[conversation_id] = ConversationDigest(
            id=conversation_id, started_at=started, last_turn_at=None, recorded_turns=0
        )
        self.activity[conversation_id] = started
        return conversation_id

    def hold_source(self, identity: str, *, location: str | None = None) -> None:
        """Make one source **grantable**, with or without a configured location.

        The scriptable half ADR-0102 §12 item 3 asks for. A source held *without* a
        location is the case §6 makes grantable with ``location`` absent — nothing
        configured means the disclosure obligation is vacuous — and it is the case a
        client's "show it before you grant" test needs to distinguish from a source
        that has one.

        **The inadmissible cases are refused here rather than modelled** (ADR-0102
        §4, §6): an identity not in canonical form, and a location with no UTF-8
        encoding. Both are defects in a **reader**, and a fake engine has no readers
        — :class:`~ai_assistant.orchestration.grants.GrantOperations` must handle
        them because a real composition root can build such a reader, and its own
        tests reach them by constructing it directly.

        Refusing beats the two alternatives. **Modelling them** would put a second
        copy of §4's and §6's rules in a fake that no suite holds to them, which is
        the silent drift a canonical fake exists to prevent; and from a client's
        side both cases are observationally just "absent from the enumeration",
        which a test reaches by not holding the source at all. **Ignoring them** is
        worse still, and is what this refusal replaces: holding a location with no
        encoding made :meth:`grantable_sources` raise a ``ValidationError`` that no
        method on this surface declares, and holding ``" calendar "`` enumerated a
        stripped ``calendar`` that :meth:`grant` then refused — a fake advertising
        what it cannot do.

        Args:
            identity: The declared identity, as a reader's ``name`` would return it.
            location: Where the source reads from, or ``None`` where nothing is
                configured.

        Raises:
            ValueError: If ``identity`` is not admissible under ADR-0102 §4, or
                either value has no UTF-8 encoding. A test error rather than a state
                to model, so it is reported where it was made.
        """
        if not identity.strip() or identity != identity.strip():
            msg = (
                f"a grantable identity is non-blank and equals its own str.strip() "
                f"(ADR-0102 §4); {identity!r} is a reader defect, and a fake engine has "
                f"no readers — GrantOperations is what models that case"
            )
            raise ValueError(msg)
        encodable_text(identity)
        if location is not None:
            encodable_text(location)
        self.sources_held[identity] = location

    def hold_grant(
        self,
        identity: str,
        *,
        scope: Sequence[GrantScope] = (GrantScope.FACET,),
        decided_at: datetime | None = None,
        revokes: str | None = None,
    ) -> SourceGrant:
        """Append one grant or revocation directly, and return it.

        The **timestamp is settable** so a test can reach the one case ADR-0102 §3's
        second clause is about and nothing else reaches: a revocation whose
        ``decided_at`` is *earlier* than the grant it revokes, which ADR-0097 §4
        permits explicitly and which an implementation deriving liveness from a
        time-ordered page gets wrong.

        Args:
            identity: The source the record is about.
            scope: The uses. On a revoking record this must transcribe the revoked
                grant's scope verbatim, which is the store's own invariant.
            decided_at: When the user decided; defaults to this engine's logical
                clock.
            revokes: The id of the grant this record revokes, or ``None``.

        Returns:
            The appended record.
        """
        record = SourceGrant(
            id=f"grant-{len(self.grants_recorded) + 1}",
            source=identity,
            scope=tuple(scope),
            decided_at=decided_at if decided_at is not None else self._tick(),
            revokes=revokes,
        )
        self.grants_recorded.append(record)
        return record

    def park(self, handle: str, *, tool_id: str = "t-1") -> Confirmation:
        """Park one confirmation this engine will resolve, and return it."""
        confirmation = Confirmation(
            tool_id=tool_id,
            tool_description="a tool the fake engine parked",
            parameters={},
            reason="the policy wants a human answer",
            token=ContinuationToken(handle=handle),
        )
        self.parked[handle] = confirmation
        return confirmation

    # --- the clauses no type expresses -------------------------------------

    def _checked[T](self, result: T, method: str) -> T:
        """Refuse a result the contract does not admit, before returning it (§8c)."""
        check_payload(
            result, max_bytes=self._max_payload_bytes, subject=f"the result of {method}()"
        )
        return result

    def _check_page(self, method: str, *, limit: int, offset: int) -> None:
        """Refuse a malformed page argument locally, then measure the call."""
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(method, max_bytes=self._max_payload_bytes, limit=limit, offset=offset)
        self.calls.append((method, {"limit": limit, "offset": offset}))


def _summary_of(belief: Belief) -> BeliefSummary:
    """Project one held belief into the listing's summary (ADR-0085 §4a)."""
    return BeliefSummary(
        id=belief.id,
        band=belief.band,
        kind=belief.kind,
        content=belief.content,
        confidence=belief.confidence,
        last_updated=belief.last_updated,
        evidence_count=belief.evidence_count,
        lost_evidence=belief.lost_evidence,
        valid_until=belief.valid_until,
    )


def _turn(utterance: str) -> TurnResult:
    """A turn whose plan has no step — a real ratified shape, not a stub."""
    goal = Goal(
        id="g-1",
        statement=utterance,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AT),
        created_at=_AT,
    )
    return TurnResult(
        goal=goal,
        context=CurrentContext(
            now=_AT,
            time_of_day=TimeOfDay.AFTERNOON,
            is_weekend=False,
            within_working_hours=True,
        ),
        memories=(),
        plan=ActionPlan(id="p-1", goal_id=goal.id, steps=(), created_at=_AT),
    )


__all__ = ["FakeAssistantEngine"]
