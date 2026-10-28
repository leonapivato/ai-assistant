"""The digesting stage: outside text read for planning, as marked evidence (ADR-0308 §4).

One orchestration-local phase module (ADR-0309 §2:2), of the kind
:class:`~ai_assistant.orchestration.planning.PlanningStage` is. It holds an injected
``StructuredCompleter``, a seam onto the episode writer, the part size the composition root
sets and a clock, and it is **not a Protocol**. Each :meth:`DigestingStage.digest_result`
digests one result acting held (ADR-0308 §6:1) against the question the call was asked
with, and :meth:`DigestingStage.digest_recall` digests recall's outside memory records
against the latest understanding's meaning (§4:4); each records its digest with the
episode.

**One digest, no tools** (§4:1, §4:10). A result's outside records are read together in
one structured call, ``StructuredCompleter.complete_structured`` with :class:`DigestReply`
and no ``model=`` override, its value the parsed object (ADR-0354 §9:1). The reply is
read by ``core``'s one rule (ADR-0354 §3:4) and by nothing else here. The digest
answers the call's *looking for* and nothing else (§4:3), and remembers nothing between
calls (§4:16).

**Quoted source data, under labels local to the call** (§4:7 to §4:8). The records reach
the model in one JSON object, each attributed as outside content by the hub and never by
its text, under a label such as ``D1`` that no planning label can spell; a pull's answer
is attributed by its channel and its author, as the hub states them (ADR-0324 §2:4).
The instruction says the content is data and never instruction, that the digest answers
only the question, that each item rests on one record and names it, and that an empty
list is a valid answer. An item naming a label the call did not show is dropped (§4:14).

**The instruction is a template** (ADR-0334): the system message is rendered from
:data:`DIGESTING_PROMPT`'s template, which the composition root reads at start and hands
the stage, and this module keeps no copy of its text (§3:1).

**In parts** (§4:9). Where the records are longer than the part size, they are split
into parts, a record longer than a part across several, each part one call; the calls
run in parallel and their evidence is joined in part order. The digest has answered
only when every part has.

**Failure** (§4:11 to §4:13). A digest fails when a call raises, a reply does not parse,
or the deadline bounding it passes first. A returned ``invalid``, ``empty`` or ``cut`` is a
reply that does not parse, and a returned ``refused`` fails it as a raised
``ModelContentFilterError`` does, as a call that raised (ADR-0354 §9:2). A failed
digest records no evidence, and planning is told it could not read the result. The stage
is failure-tolerant: it returns the failure rather than raising it. Planning is never
given the raw content.

**Recall's digest** (§4:4). Recall's outside memory records, from both runs, go into
one digest once the second run has decided. The digest fetches them by id under
ADR-0282 §2:4-§2:8 through the fetch it is handed, inside its deadline, and reads each
record's fact; a fetch that raises ``MemoryStoreError`` fails the digest, as a call
that raises does. Where no record comes back to read, no call is made and no digest is
recorded: there is nothing to answer from, and an answered digest would say the
activation had read outside content it never read (§5:4).

**Labels** (§4:15, ADR-0307 §5:1). A kept item's source is recorded under the planning
label of the record its local label named: the result's R label, for a result held as
it arrived, which is one record, and a memory record's own M label, for recall's digest
and for a result of the assistant's own records. A result's digest names its result by
its R label too, and recall's names none. Each label is taken from the activation's
:class:`ActivationLabels` as the digest is recorded, and the labels it assigns are
recorded with it; a record no item names takes no label.

**A result held by id** (§6:2). A result of the assistant's own records, such as a
memory search, is held by the ids of its outside records; :meth:`DigestingStage.
digest_records` fetches them by id through the fetch it is handed and reads them as
recall's digest reads its own, under the result's R label. A follow-up's result is the
result it names, as held (§6:7), so it is digested as that result is, against the
follow-up's question.

**Recorded through a seam** (§5:2). The digest is appended through
:class:`DigestRecorder` before :meth:`DigestingStage.digest_result` returns. An append
that fails is a capture failure: it is logged and holds nothing back.

**It logs stage and code-owned reason only**, never the question, the records or the
reply (ADR-0275 §8).

**What it gives the diagnostic record** (ADR-0314 §4), through the sink the composition
root hands it where the record is on: each part's rendered prompt before its call, with
the template it was rendered from (ADR-0334 §8:2) and the reply's shape and version
(ADR-0354 §7:1), and once the call returns or fails, its reply with what came back with it
and the returned failure's kind where there is one (§7:2), the items dropped because their
source is not one of the call's labels, or the failure; and where a digest fails, the
reason it failed.
"""

from __future__ import annotations

import asyncio
import functools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Literal, Protocol

import structlog
from pydantic import BaseModel, ConfigDict, TypeAdapter

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.diagnostics import failure_body, write_diagnostic
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.prompts import PromptDeclaration
from ai_assistant.core.reply_shapes import reply_shape_version
from ai_assistant.core.types import (
    ActivationDigest,
    DiagnosticKind,
    DiagnosticSource,
    DigestOutcome,
    EvidenceItem,
    LabelKind,
    Message,
    NonBlankEncodableText,
    PlanningLabel,
    ReplyFailure,
    Role,
    label_prefix,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence

    from ai_assistant.core.prompts import PromptTemplate
    from ai_assistant.core.protocols import DiagnosticSink, StructuredCompleter
    from ai_assistant.core.types import Memory, StructuredReply
    from ai_assistant.orchestration.held_results import HeldResult

__all__ = [
    "DIGESTING_PROMPT",
    "ActivationLabels",
    "DigestFailure",
    "DigestRecorder",
    "DigestReply",
    "Digested",
    "DigestingStage",
]

_log = structlog.get_logger(__name__)

#: A label local to one digest call: ``D`` and a number, which no planning label spells.
_LOCAL_PREFIX: Final = "D"

_QUESTION: Final[TypeAdapter[str]] = TypeAdapter(NonBlankEncodableText)


# --- the activation's labels -------------------------------------------------------------


class ActivationLabels:
    """The activation's planning labels, as recorded and as assigned since (ADR-0307 §5:1).

    Each thing gets one label, the first time it is shown or named, and keeps it for the
    whole activation. Taking a label is synchronous, so digests running side by side on
    the one event loop never assign one number twice. The lane that wires the phases
    holds one per activation, seeds it from the episode's labels, and adds each round's.
    """

    def __init__(self, recorded: Iterable[PlanningLabel] = ()) -> None:
        """Start from the labels already recorded.

        Args:
            recorded: The labels the episode records, in the order assigned.

        Raises:
            ValueError: If two of them name one thing, or one names two.
        """
        self._labels: list[PlanningLabel] = []
        self._by_label: dict[str, PlanningLabel] = {}
        self._by_thing: dict[tuple[LabelKind, str], PlanningLabel] = {}
        self.add(recorded)

    @property
    def labels(self) -> tuple[PlanningLabel, ...]:
        """Every label held, in the order it was assigned."""
        return tuple(self._labels)

    def add(self, labels: Iterable[PlanningLabel]) -> None:
        """Hold labels assigned elsewhere, such as those a planning round assigned.

        A label already held for the same thing is passed over.

        Args:
            labels: The labels, in the order assigned.

        Raises:
            ValueError: If one names a thing another label already names, or spells a
                label already naming another thing.
        """
        for one in labels:
            held = self._by_label.get(one.label)
            if held == one:
                continue
            if held is not None or (one.kind, one.id) in self._by_thing:
                msg = "a label names one thing, and a thing takes one label"
                raise ValueError(msg)
            self._hold(one)

    def take(self, kind: LabelKind, thing: str) -> tuple[PlanningLabel, bool]:
        """The label ``thing`` holds, assigning the next of its kind where it has none.

        Args:
            kind: What kind of thing it is.
            thing: Its id, exactly as held.

        Returns:
            The label, and whether this call assigned it.
        """
        held = self._by_thing.get((kind, thing))
        if held is not None:
            return held, False
        prefix = label_prefix(kind)
        number = 1 + max(
            (int(one.label[len(prefix) :]) for one in self._labels if one.kind is kind),
            default=0,
        )
        assigned = PlanningLabel(label=f"{prefix}{number}", kind=kind, id=thing)
        self._hold(assigned)
        return assigned, True

    def _hold(self, one: PlanningLabel) -> None:
        self._labels.append(one)
        self._by_label[one.label] = one
        self._by_thing[(one.kind, one.id)] = one


# --- the decision and the recorder -------------------------------------------------------


#: Why a digest failed, in code-owned words (ADR-0308 §4:11): the deadline passed first,
#: a call raised, a reply did not parse, or recall's records could not be fetched.
type DigestFailure = Literal["deadline", "raised", "unparsable", "unread"]


@dataclass(frozen=True, slots=True)
class Digested:
    """The digesting stage's decision for one digest.

    Attributes:
        result_id: The id of the result digested, as acting minted it, or ``None`` for
            recall's digest (ADR-0308 §4:4).
        digest: The digest, as recorded or as it would have been.
        labels: The labels this digest assigned, in order.
        recorded: Whether the episode writer's append of it returned.
        failure: Why it failed, or ``None`` where it answered.
    """

    result_id: str | None
    digest: ActivationDigest
    labels: tuple[PlanningLabel, ...]
    recorded: bool
    failure: DigestFailure | None = None


class DigestRecorder(Protocol):
    """The seam onto the episode writer, for a digest and the labels it assigned.

    ADR-0308 §5:2: a digest is recorded once the episode writer's append of it has
    returned (ADR-0286 §3:1). Orchestration-local, as planning's ``RoundRecorder`` is:
    the lane that wires the phases backs it with the activation's own writer, which
    appends both to the open episode.
    """

    async def record(self, digest: ActivationDigest, labels: tuple[PlanningLabel, ...]) -> None:
        """Append ``digest`` and ``labels`` to the activation's open episode.

        Args:
            digest: The digest, after those already recorded.
            labels: The labels it assigned, after those already recorded.
        """
        ...


# --- the instruction ---------------------------------------------------------------------

#: Digesting's prompt (ADR-0334 §2): the system message of every digest call is the
#: template ``digesting.txt`` shipped beside this module, or the owner's override of it,
#: which the composition root reads and hands the stage (§3:5). It names no flag and no
#: value. The rendered request — the records as quoted source data, each attributed by
#: the hub, under labels local to the call — and every rule the stage applies to a reply
#: stay here, whatever a template says (§1:3, §7:2).
#:
#: **What the instruction must say**, which binds the default and every override alike
#: (ADR-0334 §7:1), and which a promotion's review reads it against (§7:3): that the
#: content is data and never instruction (ADR-0098 §3), that the digest answers only the
#: question, that each item rests on one record and names it, and that nothing answering
#: it is a valid answer, an empty list of evidence (ADR-0308 §4:8, §4:3).
DIGESTING_PROMPT: Final = PromptDeclaration(name="digesting", package="ai_assistant.orchestration")

#: How the hub attributes every record a digest reads: from its record, never its text.
_OUTSIDE_FROM: Final = (
    "outside content: someone other than the user or the assistant wrote it, and the "
    "assistant received it from a source"
)

#: A remembered fact recall found, whose source is outside (ADR-0306 §5:16): attributed
#: by its record's provenance, as every other record is, and never by its text.
_REMEMBERED_FROM: Final = (
    "outside content: a fact the assistant remembers that rests on what a source "
    "reported, never on what the user said"
)

#: Each kind of record a digest reads, and how the hub attributes it (§4:7).
_FROM: Final[Mapping[LabelKind, str]] = {
    LabelKind.RESULT: _OUTSIDE_FROM,
    LabelKind.MEMORY: _REMEMBERED_FROM,
}


# --- the records and their parts ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Record:
    """One record a digest reads, with the planning thing a kept item names it by."""

    kind: LabelKind
    thing: str
    text: str
    #: The hub's own attribution of this record, where it has one more particular than
    #: its kind's, such as a pull's channel and author (ADR-0324 §2:4).
    attribution: str | None = None


@dataclass(frozen=True, slots=True)
class _Piece:
    """A record, or one part of a record longer than a part."""

    record: _Record
    text: str
    number: int
    of: int


def _pieces(record: _Record, part_chars: int) -> list[_Piece]:
    """``record`` whole, or cut into pieces no longer than a part."""
    if len(record.text) <= part_chars:
        return [_Piece(record, record.text, 1, 1)]
    cuts = range(0, len(record.text), part_chars)
    return [
        _Piece(record, record.text[start : start + part_chars], number, len(cuts))
        for number, start in enumerate(cuts, 1)
    ]


def _parts(records: Sequence[_Record], part_chars: int) -> list[list[_Piece]]:
    """The records in parts of at most ``part_chars`` characters each, in order (§4:9)."""
    parts: list[list[_Piece]] = []
    current: list[_Piece] = []
    size = 0
    for record in records:
        for piece in _pieces(record, part_chars):
            if current and size + len(piece.text) > part_chars:
                parts.append(current)
                current, size = [], 0
            current.append(piece)
            size += len(piece.text)
    if current:
        parts.append(current)
    return parts


def _as_text(content: object) -> str:
    """A held result as text: a string as it arrived, and any other value as JSON."""
    if isinstance(content, str):
        return content
    return json.dumps(_thawed(content), ensure_ascii=False)


def _thawed(value: object) -> object:
    """A frozen JSON value as plain JSON, for rendering."""
    if isinstance(value, Mapping):
        return {str(key): _thawed(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_thawed(item) for item in value]
    return value


# --- the reply ---------------------------------------------------------------------------


class _ProposedItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)
    text: NonBlankEncodableText
    source: str


class DigestReply(BaseModel):
    """The digest's reply shape (ADR-0354 §9:1): its prompt's one object, of evidence items.

    Its field names are the ones the prompt asks for, and the schema sent for it carries
    nothing else (§3:2). A reply missing a field, or carrying a value of the wrong kind,
    does not validate, and does not parse (§4:11). An empty list of evidence is a valid
    answer (§4:8).
    """

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)
    evidence: tuple[_ProposedItem, ...]


class _PartFailed(Exception):  # noqa: N818 — a control-flow signal inside one digest, never raised out
    """A part failed for a reason §4:11 names, carried as a code-owned word.

    Only the three failures §4:11 names are carried this way: the deadline found
    passed, a call that raised, and a reply that did not parse. Anything else a part
    raises, such as a clock reading the stage cannot use, is not a failed digest and
    escapes the stage as itself.
    """

    def __init__(self, reason: DigestFailure) -> None:
        super().__init__(reason)
        self.reason: DigestFailure = reason


#: The reason a failed digest is logged under, where its parts failed for several.
_REASON_ORDER: Final[tuple[DigestFailure, ...]] = ("deadline", "raised", "unparsable")


def _failure_reason(failures: Sequence[_PartFailed]) -> DigestFailure:
    """The code-owned reason a failed digest is logged under, by :data:`_REASON_ORDER`."""
    reasons = {one.reason for one in failures}
    return next(reason for reason in _REASON_ORDER if reason in reasons)


@functools.cache
def _reply_shape() -> dict[str, str]:
    """The given entry's ``reply_shape``: the shape's name and version (ADR-0354 §7:1)."""
    return {"name": DigestReply.__name__, "version": reply_shape_version(DigestReply)}


def _exchange_of(
    reply: StructuredReply[DigestReply],
) -> dict[str, str | dict[str, int] | None]:
    """What a part's returned entry keeps of a structured call (ADR-0354 §7:2).

    The reply as the model wrote it, the model that answered, the mode, the finish reason,
    a refusal's statement and category, the usage, and the returned failure's kind where
    there is one.
    """
    exchange = reply.exchange
    held: dict[str, str | dict[str, int] | None] = {
        "reply": exchange.reply,
        "model": exchange.model,
        "mode": exchange.mode.value,
        "finish_reason": exchange.finish_reason,
        "refusal": exchange.refusal,
        "refusal_category": exchange.refusal_category,
        "usage": {
            "input_tokens": exchange.usage.input_tokens,
            "output_tokens": exchange.usage.output_tokens,
            "cache_read_tokens": exchange.usage.cache_read_tokens,
            "cache_write_tokens": exchange.usage.cache_write_tokens,
        },
    }
    if reply.failure is not None:
        held["failure"] = reply.failure.value
    return held


@dataclass(frozen=True, slots=True)
class _Kept:
    """One item a part kept: its text, and the record its local label named."""

    text: str
    record: _Record


def _kept(
    proposed: DigestReply, local: Mapping[str, _Record]
) -> tuple[list[_Kept], tuple[dict[str, str], ...]]:
    """The items a part kept, each beside the record its local label named, and those dropped.

    §4:14: an item naming a source the call did not show is dropped.
    """
    kept: list[_Kept] = []
    dropped: list[dict[str, str]] = []
    for item in proposed.evidence:
        record = local.get(item.source)
        if record is None:
            _log.info("digest_item_dropped", stage="digesting", reason="unknown_label")
            dropped.append({"source": item.source, "text": item.text})
            continue
        kept.append(_Kept(text=item.text, record=record))
    return kept, tuple(dropped)


# --- the stage ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _digest_of(result_id: str | None, question: str) -> dict[str, object]:
    """Which digest a diagnostic entry belongs to: its result, or none for recall's."""
    return {"result": result_id, "question": question}


class DigestingStage:
    """Digest one held result into marked evidence, recorded with the episode (ADR-0308 §4)."""

    def __init__(  # noqa: PLR0913 — the two seams, the part size, the prompt, the clock and the record
        self,
        *,
        provider: StructuredCompleter,
        recorder: DigestRecorder,
        part_chars: int,
        prompt: PromptTemplate,
        now: Callable[[], datetime] = _utcnow,
        diagnostics: DiagnosticSink | None = None,
    ) -> None:
        """Wire the stage to its seams, and to the part size the composition root sets.

        Args:
            provider: The structured seam a digest's calls go through (ADR-0354 §9:1).
            recorder: The seam that appends a digest to the episode.
            part_chars: ``DIGEST_PART_CHARS``, the most characters of records one call
                reads (§4:9); its value is #2589's.
            prompt: The template of :data:`DIGESTING_PROMPT`, default or override, as
                the composition root read it at start (ADR-0334 §3:5).
            now: The clock the deadline and ``recorded_at`` are read against.
            diagnostics: The diagnostic record's write seam (ADR-0314 §4:4), or
                ``None`` where the record is off.

        Raises:
            ValueError: If ``part_chars`` is not an integer of at least 1, or ``prompt``
                is not a template of :data:`DIGESTING_PROMPT`.
        """
        if type(part_chars) is not int or part_chars < 1:
            msg = "a digest's part size must be an integer of at least 1"
            raise ValueError(msg)
        if prompt.declaration != DIGESTING_PROMPT:
            msg = "the digesting stage renders the digesting prompt (ADR-0334 §2)"
            raise ValueError(msg)
        self._prompt = prompt
        self._provider = provider
        self._recorder = recorder
        self._part_chars = part_chars
        self._now = checked_clock(now, owner="DigestingStage")
        self._diagnostics = diagnostics

    async def digest_result(
        self,
        held: HeldResult,
        *,
        question: str,
        labels: ActivationLabels,
        deadline: datetime,
        attribution: str | None = None,
    ) -> Digested:
        """Digest ``held`` against ``question``, and record the digest with the episode.

        Never raises for a failure §4:11 names: a call that raised, a reply that did not
        parse, or the deadline passing first each make a failed digest, recorded and
        returned with no evidence.

        Args:
            held: The result acting held, as it arrived.
            question: What the call was looking for (ADR-0306 §2:9).
            labels: The activation's labels, which the digest takes its labels from.
            deadline: The instant bounding the digest: the one bounding its round's
                wait (ADR-0307 §8:2).
            attribution: The hub's attribution of the result, stated from its own data
                and never from the result's text, where it has one more particular than
                a result's: a pull's channel and author (ADR-0324 §2:4). ``None`` gives
                the record a result's attribution.

        Returns:
            The digest, the labels it assigned, and whether it was recorded.

        Raises:
            ValueError: If ``question`` is blank or not encodable text: planning's check
                refuses such a call before it runs, so this is the caller's error.
        """
        question = _QUESTION.validate_python(question)
        result_id = str(held.result_id)
        record = _Record(
            kind=LabelKind.RESULT,
            thing=result_id,
            text=_as_text(held.content),
            attribution=attribution,
        )
        kept = await self._read(question, [record], deadline, result_id=result_id)
        return await self._recorded(question, kept, labels, result_id=result_id)

    async def digest_recall(
        self,
        fetch: Callable[[], Awaitable[Sequence[Memory]]],
        *,
        question: str,
        labels: ActivationLabels,
        deadline: datetime,
    ) -> Digested | None:
        """Digest recall's outside memory records against ``question``, and record it (§4:4).

        One digest over every record ``fetch`` returns, both runs' together, each read
        by its fact and named by the record's own M label. Never raises for a failure
        §4:11 names, nor where the fetch raises ``MemoryStoreError``: each makes a
        failed digest, recorded and returned with no evidence.

        Args:
            fetch: Fetches the records by id under ADR-0282 §2:4-§2:8, the audience
                predicate applied again, and returns those to read, in recall's order.
                Awaited inside the deadline.
            question: The latest understanding's ``meaning``.
            labels: The activation's labels, which the digest takes its labels from.
            deadline: The instant bounding the digest, its fetch included.

        Returns:
            The digest, the labels it assigned, and whether it was recorded; or ``None``
            where the fetch returned no record to read, so no call was made and nothing
            was recorded.

        Raises:
            ValueError: If ``question`` is blank or not encodable text, which a recorded
                understanding's meaning never is.
        """
        return await self.digest_records(
            fetch, result_id=None, question=question, labels=labels, deadline=deadline
        )

    async def digest_records(
        self,
        fetch: Callable[[], Awaitable[Sequence[Memory]]],
        *,
        result_id: str | None,
        question: str,
        labels: ActivationLabels,
        deadline: datetime,
    ) -> Digested | None:
        """Digest memory records held by id against ``question``, and record it.

        Recall's digest (§4:4), where ``result_id`` is ``None``, and the digest of a
        result of the assistant's own records held by the ids of its outside records
        (§6:2), where it names that result: one digest over every record ``fetch``
        returns, each read by its fact and named by the record's own M label. Never
        raises for a failure §4:11 names, nor where the fetch raises
        ``MemoryStoreError``: each makes a failed digest, recorded and returned with no
        evidence.

        Args:
            fetch: Fetches the records by id under ADR-0282 §2:4-§2:8, the audience
                predicate applied again, and returns those to read, in order. Awaited
                inside the deadline.
            result_id: The id of the result held by id, which the digest names by its
                R label; ``None`` for recall's digest, which names none.
            question: What the digest answers.
            labels: The activation's labels, which the digest takes its labels from.
            deadline: The instant bounding the digest, its fetch included.

        Returns:
            The digest, the labels it assigned, and whether it was recorded; or ``None``
            where the fetch returned no record to read, so no call was made and nothing
            was recorded.

        Raises:
            ValueError: If ``question`` is blank or not encodable text: planning's check
                refuses such a call before it runs, and a recorded understanding's
                meaning never is.
        """
        question = _QUESTION.validate_python(question)
        result = None if result_id is None else str(result_id)
        fetched = await self._fetched(fetch, deadline)
        if isinstance(fetched, str):
            return await self._recorded(question, fetched, labels, result_id=result)
        records = [
            _Record(kind=LabelKind.MEMORY, thing=one.id, text=one.content) for one in fetched
        ]
        if not records:
            _log.info("digest_skipped", stage="digesting", reason="nothing_fetched")
            return None
        kept = await self._read(question, records, deadline, result_id=result)
        return await self._recorded(question, kept, labels, result_id=result)

    async def _fetched(
        self, fetch: Callable[[], Awaitable[Sequence[Memory]]], deadline: datetime
    ) -> Sequence[Memory] | DigestFailure:
        """Recall's records, fetched inside the deadline, or why they could not be."""
        remaining = (deadline - self._now()).total_seconds()
        if remaining <= 0:
            _log.info("digest_failed", stage="digesting", reason="deadline")
            return "deadline"
        try:
            async with asyncio.timeout(remaining):
                return await fetch()
        except TimeoutError:
            _log.info("digest_failed", stage="digesting", reason="deadline")
            return "deadline"
        except MemoryStoreError:
            # The records could not be read, so nothing answers from them (§4:13).
            _log.info("digest_failed", stage="digesting", reason="unread")
            return "unread"

    async def _recorded(
        self,
        question: str,
        kept: list[_Kept] | DigestFailure,
        labels: ActivationLabels,
        *,
        result_id: str | None,
    ) -> Digested:
        """The digest of what was ``kept``, or a failed one, recorded with its labels."""
        taken: list[PlanningLabel] = []

        def label(kind: LabelKind, thing: str) -> str:
            one, assigned = labels.take(kind, thing)
            if assigned:
                taken.append(one)
            return one.label

        # §4:15: labels are taken as the digest is recorded, synchronously, after the
        # calls; a result's own R label first, since the digest names it. Recall's
        # digest names no result.
        result_label = None if result_id is None else label(LabelKind.RESULT, result_id)
        failure: DigestFailure | None = None
        if isinstance(kept, str):
            failure = kept
            # ADR-0314 §4: the failure's reason, where the digest failed.
            await write_diagnostic(
                self._diagnostics,
                DiagnosticSource.DIGESTING,
                DiagnosticKind.RETURNED,
                lambda: {
                    **_digest_of(result_id, question),
                    "digest": "failed",
                    "reason": failure,
                },
            )
            digest = ActivationDigest(
                result=result_label,
                question=question,
                outcome=DigestOutcome.FAILED,
                recorded_at=self._now(),
            )
        else:
            digest = ActivationDigest(
                result=result_label,
                question=question,
                outcome=DigestOutcome.ANSWERED,
                evidence=tuple(
                    EvidenceItem(text=one.text, source=label(one.record.kind, one.record.thing))
                    for one in kept
                ),
                recorded_at=self._now(),
            )
        recorded = await self._record(digest, tuple(taken))
        return Digested(
            result_id=result_id,
            digest=digest,
            labels=tuple(taken),
            recorded=recorded,
            failure=failure,
        )

    async def _read(
        self,
        question: str,
        records: Sequence[_Record],
        deadline: datetime,
        *,
        result_id: str | None,
    ) -> list[_Kept] | DigestFailure:
        """Read ``records`` in parts, in parallel; their kept items in part order, or why not.

        A reason is a failed digest (§4:11): a part's call raised, its reply did not
        parse, or the deadline passed before every part answered. ``result_id`` names
        the digest in the diagnostic record, which the parts' entries carry.
        """
        parts = _parts(records, self._part_chars)
        # The budget is read after the parts are cut, so their cutting is inside it,
        # and each call reads the clock again before it is made (``_part``).
        remaining = (deadline - self._now()).total_seconds()
        if remaining <= 0:
            _log.info("digest_failed", stage="digesting", reason="deadline")
            return "deadline"
        escaped: Exception | None = None
        try:
            async with asyncio.timeout(remaining):
                return await self._every_part(question, parts, deadline, result_id)
        except TimeoutError:
            _log.info("digest_failed", stage="digesting", reason="deadline")
            return "deadline"
        except ExceptionGroup as group:
            failed, other = group.split(_PartFailed)
            if other is None and failed is not None:
                reason = _failure_reason(
                    [one for one in failed.exceptions if isinstance(one, _PartFailed)]
                )
                _log.info("digest_failed", stage="digesting", reason=reason)
                return reason
            # Not one of §4:11's failures, such as a clock reading the stage cannot
            # use: it escapes as itself, outside the handler, so its own cause stands.
            escaped = (other or group).exceptions[0]
        raise escaped

    async def _every_part(
        self,
        question: str,
        parts: Sequence[Sequence[_Piece]],
        deadline: datetime,
        result_id: str | None,
    ) -> list[_Kept]:
        """Every part's call, in parallel; the first to fail cancels the rest (§4:9)."""
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(
                    self._part(
                        question,
                        part,
                        deadline,
                        about={
                            **_digest_of(result_id, question),
                            "part": number,
                            "parts": len(parts),
                        },
                    )
                )
                for number, part in enumerate(parts, start=1)
            ]
        return [one for task in tasks for one in task.result()]

    async def _part(
        self,
        question: str,
        part: Sequence[_Piece],
        deadline: datetime,
        *,
        about: Mapping[str, object],
    ) -> list[_Kept]:
        """One part's call: its records under local labels, and the items it kept.

        ``about`` names the digest and the part in each diagnostic entry the part
        writes, so parts that run in parallel, each with labels from ``D1``, are told
        apart (ADR-0314 §4).

        Raises:
            _PartFailed: If the deadline has passed before the call is made; the call
                raised, ``CancelledError`` included where nothing cancelled this part,
                or the provider refused it; or the reply does not parse.
        """
        names: dict[_Record, str] = {}
        shown: list[dict[str, object]] = []
        for piece in part:
            name = names.setdefault(piece.record, f"{_LOCAL_PREFIX}{len(names) + 1}")
            one: dict[str, object] = {
                "label": name,
                "from": piece.record.attribution or _FROM[piece.record.kind],
                "text": piece.text,
            }
            if piece.of > 1:
                one["part"] = f"{piece.number} of {piece.of}"
            shown.append(one)
        document = {"question": question, "records": shown}
        # ADR-0335 §9:1: the prompt declares no flag, so the key records an empty set.
        instruction = self._prompt.rendered()
        messages = (
            Message(role=Role.SYSTEM, content=instruction.text),
            Message(role=Role.USER, content=json.dumps(document, ensure_ascii=True)),
        )
        if self._now() >= deadline:
            raise _PartFailed("deadline")
        await write_diagnostic(
            self._diagnostics,
            DiagnosticSource.DIGESTING,
            DiagnosticKind.GIVEN,
            lambda: {
                **about,
                "messages": [one.model_dump(mode="json") for one in messages],
                "prompt": instruction.provenance(),
                "reply_shape": _reply_shape(),
            },
        )
        try:
            reply = await self._provider.complete_structured(messages, DigestReply)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise  # the digest, or its group, was cancelled: let it unwind
            await self._part_failed(asyncio.CancelledError(), about)
            raise _PartFailed("raised") from None
        except Exception as exc:  # §4:11: a call that raises fails the digest, whatever it raised
            await self._part_failed(exc, about)
            raise _PartFailed("raised") from exc
        proposed = reply.value
        if proposed is None:
            # ADR-0354 §9:2, §7:2: the returned entry first, then the failure path: a
            # refusal where a raised one lands, any other kind where a reply that does not
            # parse does.
            await self._part_returned(reply, about, dropped=())
            if reply.failure is ReplyFailure.REFUSED:
                _log.info("digest_part_refused", stage="digesting", reason=reply.failure.value)
                raise _PartFailed("raised")
            raise _PartFailed("unparsable")
        kept, dropped = _kept(proposed, {name: record for record, name in names.items()})
        await self._part_returned(reply, about, dropped=dropped)
        return kept

    async def _part_failed(self, error: BaseException, about: Mapping[str, object]) -> None:
        """Write a part's returned entry as the failure its call ended in (§4)."""
        await write_diagnostic(
            self._diagnostics,
            DiagnosticSource.DIGESTING,
            DiagnosticKind.RETURNED,
            lambda: {**about, "failure": failure_body(error)},
        )

    async def _part_returned(
        self,
        reply: StructuredReply[DigestReply],
        about: Mapping[str, object],
        *,
        dropped: tuple[dict[str, str], ...],
    ) -> None:
        """Write a part's reply, what came with it, and the items dropped from it (§4)."""

        def body() -> dict[str, object]:
            return {**about, **_exchange_of(reply), "dropped": list(dropped)}

        await write_diagnostic(
            self._diagnostics, DiagnosticSource.DIGESTING, DiagnosticKind.RETURNED, body
        )

    async def _record(self, digest: ActivationDigest, labels: tuple[PlanningLabel, ...]) -> bool:
        """Append the digest; a failure is a capture failure that holds nothing back (§5:2)."""
        try:
            await self._recorder.record(digest, labels)
        except Exception:  # ADR-0286 §3:7: an append never fails processing
            _log.warning("activation_capture_degraded", stage="digesting", reason="append_failed")
            return False
        return True
