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

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ai_assistant.core.errors import UnknownContinuationError
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
    Goal,
    IngestSummary,
    LearnDecision,
    LearnOutcome,
    MemoryKind,
    MemorySource,
    ObservationReport,
    Provenance,
    Question,
    QuestionState,
    TimeOfDay,
    TurnOutcome,
    TurnResult,
)
from ai_assistant.orchestration.payloads import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    check_arguments,
    check_payload,
    identifier,
    page_argument,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import timedelta

    from ai_assistant.core.types import EncodableText, FeedbackEvent, Identifier

#: A fixed instant, so a fake engine's output is deterministic without a clock.
_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

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
        self.conversations_held: dict[str, ConversationDigest] = {}
        self.parked: dict[str, Confirmation] = {}
        self.turn_outcome: TurnOutcome | None = None
        self.observation: ObservationReport = ObservationReport()
        self.answered: AnswerOutcome | None = None
        #: Every call, in order, as ``(method, arguments)`` — so a test can assert
        #: what reached the engine without reaching into its state.
        self.calls: list[tuple[str, dict[str, object]]] = []

    # --- the two turn calls -----------------------------------------------

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
            limit=self._max_payload_bytes,
            utterance=utterance,
            timeout=timeout,
            conversation_id=selected,
        )
        self.calls.append(("converse", {"utterance": utterance, "conversation_id": selected}))
        if selected is not None and selected not in self.conversations_held:
            self.start_conversation(selected)
        held = selected if selected is not None else self.start_conversation("c-1")
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
            "resume", limit=self._max_payload_bytes, token=token, approved=approved, timeout=timeout
        )
        self.calls.append(("resume", {"token": token.handle, "approved": approved}))
        if token.handle not in self.parked:
            msg = (
                "this token names no step awaiting confirmation in this engine; call "
                "pending_confirmations() to re-mint a token for any park that is still answerable"
            )
            raise UnknownContinuationError(msg)
        del self.parked[token.handle]
        return self._checked(TurnOutcome(turn=None), "resume")

    # --- the two accumulation legs ----------------------------------------

    async def learn(self, event: FeedbackEvent) -> LearnOutcome:
        """Fold one piece of feedback into memory, storing exactly one belief."""
        check_arguments("learn", limit=self._max_payload_bytes, event=event)
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
        check_arguments("observe", limit=self._max_payload_bytes, conversation_id=selected)
        self.calls.append(("observe", {"conversation_id": selected}))
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
            limit=self._max_payload_bytes,
            bands=selected_bands,
            kinds=selected_kinds,
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
        check_arguments("belief", limit=self._max_payload_bytes, record_id=named)
        self.calls.append(("belief", {"record_id": named}))
        return self._checked(self.beliefs_held.get(named), "belief")

    async def forget(self, record_id: Identifier) -> bool:
        """Destroy one belief, reporting whether there was one to destroy."""
        named = identifier(record_id, name="record_id")
        check_arguments("forget", limit=self._max_payload_bytes, record_id=named)
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
        check_arguments("answer", limit=self._max_payload_bytes, question_id=named, accept=accept)
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
        check_arguments("forget_question", limit=self._max_payload_bytes, question_id=named)
        self.calls.append(("forget_question", {"question_id": named}))
        gone = self.questions_open.pop(named, None) or self.questions_interrupted.pop(named, None)
        return self._checked(gone is not None, "forget_question")

    # --- the conversation surface -----------------------------------------

    async def recent_conversations(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[ConversationSummary, ...]:
        """List conversations, in the order they were started."""
        self._check_page("recent_conversations", limit=limit, offset=offset)
        held = tuple(
            ConversationSummary(
                id=digest.id,
                started_at=digest.started_at,
                last_active_at=digest.started_at,
                last_turn_at=digest.last_turn_at,
            )
            for digest in self.conversations_held.values()
        )
        return self._checked(held[offset : offset + limit], "recent_conversations")

    async def conversation(self, conversation_id: Identifier) -> ConversationDigest | None:
        """Show the count and span destroying one conversation would destroy."""
        named = identifier(conversation_id, name="conversation_id")
        check_arguments("conversation", limit=self._max_payload_bytes, conversation_id=named)
        self.calls.append(("conversation", {"conversation_id": named}))
        return self._checked(self.conversations_held.get(named), "conversation")

    async def forget_conversation(self, conversation_id: Identifier) -> bool:
        """Destroy one conversation, reporting whether there was one to destroy."""
        named = identifier(conversation_id, name="conversation_id")
        check_arguments("forget_conversation", limit=self._max_payload_bytes, conversation_id=named)
        self.calls.append(("forget_conversation", {"conversation_id": named}))
        return self._checked(self.conversations_held.pop(named, None) is not None, "forget")

    # --- durable recovery --------------------------------------------------

    async def pending_confirmations(self) -> tuple[Confirmation, ...]:
        """Hand back every park that is still answerable, with a resolvable token."""
        self.calls.append(("pending_confirmations", {}))
        return self._checked(tuple(self.parked.values()), "pending_confirmations")

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

    def ask(self, question_id: str, *, content: str, state: QuestionState) -> Question:
        """Put one deferred question in the queue, and return it.

        ``state`` decides which enumeration it lands in: an ``INTERRUPTED``
        question is a *second*, separate list all the way to the surface, because
        offering it beside the answerable ones would present a claim that cannot be
        taken (ADR-0078 §8).
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
        if state is QuestionState.INTERRUPTED:
            self.questions_interrupted[question_id] = question
        else:
            self.questions_open[question_id] = question
        return question

    def start_conversation(self, conversation_id: str) -> str:
        """Record one conversation, and return its id."""
        self.conversations_held[conversation_id] = ConversationDigest(
            id=conversation_id, started_at=_AT, last_turn_at=None, recorded_turns=0
        )
        return conversation_id

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
        check_payload(result, limit=self._max_payload_bytes, subject=f"the result of {method}()")
        return result

    def _check_page(self, method: str, *, limit: int, offset: int) -> None:
        """Refuse a malformed page argument locally, then measure the call."""
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(method, limit=self._max_payload_bytes, offset=offset)
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
