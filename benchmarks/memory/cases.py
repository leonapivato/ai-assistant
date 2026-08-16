"""The corpus-neutral shape everything downstream reads.

**A case is one store's worth of work**: a conversation to ingest, and the questions
asked about it. That unit is chosen because the two corpora disagree about it and the
disagreement is structural rather than cosmetic — LoCoMo asks ~199 questions about
each of ten dialogues, so ten cases; LongMemEval gives *every question its own
haystack*, so fifty questions is fifty cases and fifty stores. A harness organised
around "the corpus" would have to special-case that; a harness organised around the
case does not, and the cost estimate falls out of the same count.

Types here are ``pydantic`` models to match the project's own convention for data
that crosses a boundary, and frozen because a case is read by the ingest path and the
answer path and neither owns it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BenchTurn(BaseModel):
    """One utterance in a benchmark conversation.

    Attributes:
        speaker: Who spoke, as the corpus names them.
        text: What was said.
        user_side: Whether this turn is the *user's* side of the exchange. The
            distinction is load-bearing rather than cosmetic: capture records a turn
            as one episode with a user half and an assistant half, so which side a
            corpus turn belongs on decides what the episode text looks like — and
            #1029's P6 is precisely the open question of whether assistant-side
            content survives ingestion symmetrically with user assertions.

            Under :attr:`BenchSession.user_supplied` every turn is the user's side,
            because the user supplied all of it; the field is still per turn because
            a genuine user↔assistant corpus needs it per turn.
        evidence_key: The corpus's own pointer to **this turn**, in the *same id
            space* as :attr:`BenchQuestion.evidence` — LoCoMo's ``dia_id``
            (``"D1:1"``), LongMemEval's answering session id. It is carried on the
            turn rather than derived downstream because it is the only place the two
            id spaces #1074 describes can be joined: a question's evidence names
            corpus turns, a retrieval returns generated record ids, and the bridge is
            "which captured episode did this corpus turn become". Ingestion knows
            that, and nothing later does.

            ``None`` where the corpus supplies no pointer for a turn — an honest
            absence rather than a synthesised key, because a fabricated pointer would
            join to a question's evidence by accident and report a retrieval that
            never happened.
    """

    model_config = ConfigDict(frozen=True)

    speaker: str
    text: str
    user_side: bool
    evidence_key: str | None = None


class BenchSession(BaseModel):
    """A contiguous conversation session, at a known time.

    Attributes:
        session_key: The corpus's own id for this session.
        occurred_at: When it happened, timezone-aware. Sessions are ingested in this
            order and the instant is carried into capture, because a corpus whose
            sessions span months is the entire point of a long-term-memory benchmark
            and collapsing them onto "now" would erase the axis being measured.
        turns: The utterances, in order.
        user_supplied: Whether this whole session is material the *user handed the
            assistant*, rather than a conversation between the user and the
            assistant.

            **It changes the shape of what capture records, which is why it is a
            field and not a comment.** A user↔assistant session folds into exchanges
            — a user half answered by an assistant half — and consecutive same-side
            utterances join into one half so a double turn is not lost
            (:func:`~benchmarks.memory.ingest.exchanges_of`). A supplied transcript
            has no assistant half at all: every utterance is the user's side, so that
            same fold would join an entire session into a *single* episode, collapse
            the observation windows it should have tiled, and destroy the per-turn
            resolution #1074's evidence join depends on. So a supplied session yields
            **one exchange per turn**, each with ``outcome=None``.

            It is stated per session rather than per corpus because it is a fact
            about the material, and per session rather than derived from "every turn
            is user-side" because those are different claims: a user↔assistant
            session that happens to contain no assistant turn is still not a supplied
            transcript, and reading the shape off the turns would silently make it
            one. ``False`` — a conversation the user actually had — is the default
            that every corpus but LoCoMo takes.
    """

    model_config = ConfigDict(frozen=True)

    session_key: str
    occurred_at: datetime
    turns: tuple[BenchTurn, ...]
    user_supplied: bool = False


class BenchQuestion(BaseModel):
    """One graded question.

    Attributes:
        question_id: Unique within the corpus.
        category: The corpus's own category label, unmapped. Deliberately not
            normalised into a shared taxonomy: #1029 predicts per-category and the
            two corpora's categories are not the same categories, so a mapping would
            be an interpretation smuggled in ahead of the results.
        question: The question as asked.
        answer: The reference answer.
        unanswerable: Whether the graded behaviour is abstention (#1029's P7).
        evidence: The corpus's pointers to the supporting turns, where it gives them
            — LoCoMo's ``dia_id`` list, LongMemEval's answering session ids. Carried
            through untouched because P8's retrieval-miss-versus-reader-error split
            is computed against them. Each pointer is joined to what was actually
            ingested through :attr:`BenchTurn.evidence_key`, which names the same
            pointers on the turns themselves (#1074).
        asked_at: When the question is posed, where the corpus says. LongMemEval
            gives one; LoCoMo does not, and ``None`` is the honest answer rather than
            a stand-in.
    """

    model_config = ConfigDict(frozen=True)

    question_id: str
    category: str
    question: str
    answer: str
    unanswerable: bool = False
    evidence: tuple[str, ...] = ()
    asked_at: datetime | None = None


class BenchCase(BaseModel):
    """One conversation and the questions asked about it — one store's worth of work.

    Attributes:
        corpus_key: Which corpus this came from.
        case_key: Unique within the corpus.
        sessions: The conversation, in time order.
        questions: What is asked about it.
    """

    model_config = ConfigDict(frozen=True)

    corpus_key: str
    case_key: str
    sessions: tuple[BenchSession, ...] = Field(min_length=1)
    questions: tuple[BenchQuestion, ...]

    @property
    def turn_count(self) -> int:
        """How many utterances the case ingests."""
        return sum(len(session.turns) for session in self.sessions)
