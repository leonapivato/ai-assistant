"""The read envelope where the engine decides what the turn stage is told (ADR-0226).

Three of ADR-0226 §11's tests are about what happens *above*
:meth:`~ai_assistant.orchestration.loop.LearningLoop.respond`, so they live here
rather than beside the servicer:

* **item 1** — the reply-vocabulary question answering through the hop, driven end
  to end through ``converse`` so that "the answer carries it" is the reply and not
  a seam. §11 calls this "the milestone's exit shape and the one test that fails if
  the hop is merely wired". **ADR-0227 §7 re-specifies it** and this module carries
  the re-specification: the fixture is shaped as ``Engine._capture`` writes an
  episode — the user's material in ``content``, the composed reply in ``outcome``,
  an ``ExchangeDisposition`` beside it — because "a fixture that carries in one
  field what production carries in another asserts nothing about production, however
  faithfully the rest of the path is wired". §7 requires the existing test
  **rewritten** rather than supplemented, "a second test beside a fixture that cannot
  fail is a test suite that reports two greens for one guarantee".
* **item 5**'s engine arm — ``converse_spoken`` declares its channel's audience
  unbounded (ADR-0200 §3), so its request is declined by the object the engine
  already mints rather than by a second fact it has to keep in step.
* **item 10**'s two post-plan arms — a turn rejected for capacity and a turn whose
  ``PlanStore.save_plan`` raises, both of which happen **after** the loop has
  planned and serviced, and neither of which may suppress §9's record.

Everything else §11 owes that lane is in ``test_loop_reads.py``.

**ADR-0227 §8's assertions 4, 5, 8 and 16 are here too**, for the same reason: each
is about a prompt the *engine* assembled from a supply the servicer built, so a case
that stopped at the loop would assert over a carrier nothing had rendered. §8's
assertions about the render rule itself — the tail, the ceiling, the cap, the counts
and the planner's assembler — are in ``test_composing.py``, and the carrier's own
order, deduplication and emptiness are in ``test_loop_reads.py``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog
from test_converse_spoken import _MP4, _recording
from test_engine import AT, PATIENT, Harness, NoStepPlanner, OneStepPlanner, confirmable
from test_engine_routing import _routed_harness, _router

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    ActionPlan,
    BeliefBand,
    EpisodicMemory,
    ExchangeDisposition,
    MemorySource,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadRequest,
    Role,
    SemanticMemory,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.reads import (
    READ_AUDIT_EVENT,
    Servicing,
    StopReason,
    TriggerOutcome,
)
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping, Sequence

    from ai_assistant.core.types import (
        CurrentContext,
        Goal,
        MemoryKind,
        MemoryRecord,
        MemorySearchResult,
        ShownFile,
    )

#: The token the assistant introduced and the user never used. §11 item 1's whole
#: premise is that a blind read keyed on the *question's* vocabulary cannot reach
#: the exchange holding it, because only ``content`` is embedded.
#:
#: **It lives in ``outcome`` and nowhere else** (ADR-0227 §7). ``Engine._capture``
#: writes ``outcome=composed.text`` and ``content=_exchange_of(...)``, so the
#: vocabulary of what the assistant *said* is in ``outcome`` and ``content`` carries
#: what the user said and what this system planned. Until ADR-0227 this constant sat
#: in the episode's ``content``, "where every group renders it" — so the assertion
#: was true of a record no capture site writes and the mechanism under test was never
#: exercised (#1944, and §7's reason for stating a rule rather than making a repair).
_LENDER: Final = "Brightpath Financial"

_QUESTION: Final = "which lender was recommended"

#: What the user said on the earlier turn, as ``_exchange_of`` renders it into
#: ``content``. It deliberately shares no term with :data:`_QUESTION`, which is what
#: makes the blind read reach the belief and not the exchange — "a question whose
#: answer shares no wording with the record that holds it is not a ranking problem".
_EARLIER: Final = "The user asked: help me pick a mortgage provider."

#: The utterance ``_routed_harness`` routes a ``forget`` on (ADR-0197 §1).
_ROUTED: Final = "please forget that preference"

#: A router reply that names no operation, which ADR-0197 §1 makes a **decline**.
_DECLINED: Final = json.dumps({"no_operation": True})


def _hop(*labels: str) -> ReadRequest:
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.CITATION_HOP, labels=labels),))


def _query(text: str) -> ReadRequest:
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=text),))


def _both(text: str, *labels: str) -> ReadRequest:
    """One ask of each kind, query first — so the servicing order is asserted, not the tuple's."""
    return ReadRequest(
        asks=(
            ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=text),
            ReadAsk(kind=ReadKind.CITATION_HOP, labels=labels),
        )
    )


class _AskingPlanner(NoStepPlanner):
    """``NoStepPlanner`` with a scripted request beside its plan, recording its supply.

    Subclassed rather than written out so the plan is the one every other engine
    case is built on: ADR-0226 §4's field is additive, so "a planner that emits a
    request" and "a planner" differ by one field and nothing else.
    """

    def __init__(self, request: ReadRequest | None) -> None:
        self._request = request
        self.calls: list[tuple[MemoryRecord, ...]] = []

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
    ) -> ActionPlan:
        self.calls.append(tuple(memories))
        plan = await super().plan(
            goal, context=context, memories=memories, capabilities=capabilities
        )
        return plan.model_copy(update={"read_request": self._request})


class _AskingOneStepPlanner(OneStepPlanner):
    """``OneStepPlanner`` with a request beside it — §11 item 10's capacity arm.

    ``_admit_and_reserve`` is reached only where the plan has a step, so the turn
    that meets backpressure has to be one the engine would otherwise have driven.
    """

    def __init__(self, request: ReadRequest) -> None:
        super().__init__()
        self._request = request

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
    ) -> ActionPlan:
        plan = await super().plan(
            goal, context=context, memories=memories, capabilities=capabilities
        )
        return plan.model_copy(update={"read_request": self._request})


def _belief(record_id: str, content: str, *, evidence: tuple[str, ...] = ()) -> SemanticMemory:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=Provenance(
            source=MemorySource.OBSERVED, confidence=0.6, last_updated=AT, evidence=evidence
        ),
    )


def _episode(
    record_id: str,
    content: str,
    *,
    outcome: str | None = None,
    disposition: ExchangeDisposition | None = None,
) -> EpisodicMemory:
    """One captured turn, shaped as ``Engine._capture`` writes one (ADR-0227 §7).

    ``content`` is the user's material and the plan's rationale; ``outcome`` is the
    composed reply; ``disposition`` is what became of the pass. A reply asserted to
    have reached a prompt goes in ``outcome`` on a record that also carries a
    ``disposition``, "because that is the combination the render rules turn on".
    """
    return EpisodicMemory(
        id=record_id,
        content=content,
        occurred_at=AT,
        outcome=outcome,
        disposition=disposition,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )


def _echoing_composer() -> ComposingStage:
    """A composing stage whose reply says whether the exchange reached the prompt.

    The point of driving item 1 through the engine rather than through the turn
    stage is that "the answer carries it" becomes an assertion about the answer. The
    model is a fake, so what it can honestly report is what it was *shown* — which
    is exactly the property the hop exists to produce.
    """

    def reply(messages: Sequence[Any]) -> str:
        prompt = "\n".join(str(message.content) for message in messages)
        return _LENDER if _LENDER in prompt else "I have no record of that."

    return ComposingStage(model=FakeModelProvider(reply=reply), streaming=FakeStreamingCompleter())


def _recorder() -> tuple[ComposingStage, FakeModelProvider]:
    """A real composing stage over a fake that keeps the prompt it was handed.

    ADR-0227 §7 forbids substituting "the renderer whose output the assertion is
    about", and permits a fake ``ModelProvider``: so the production
    :class:`~ai_assistant.orchestration.composing.ComposingStage` assembles the
    prompt and the fake merely records it.
    """
    model = FakeModelProvider("answer")
    return ComposingStage(model=model, streaming=FakeStreamingCompleter()), model


def _assembled(model: FakeModelProvider) -> str:
    """The one user-turn prompt the stage assembled, from the fake's own record."""
    assert len(model.calls) == 1
    return next(one.content for one in model.calls[0].messages if one.role is Role.USER)


def _reply_lines_of(prompt: str) -> list[str]:
    """Every reply line of a prompt, in the order it wrote them (ADR-0222 §1)."""
    return [row for row in prompt.splitlines() if row.startswith("    what the assistant replied")]


def _records(captured: Sequence[MutableMapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [event for event in captured if event["event"] == READ_AUDIT_EVENT]


def _record(captured: Sequence[MutableMapping[str, Any]]) -> Mapping[str, Any]:
    [only] = _records(captured)
    return only


def _serviced(captured: Sequence[MutableMapping[str, Any]], ordinal: int = 0) -> Mapping[str, Any]:
    """One servicing's entry in this turn's record (ADR-0228 §9)."""
    return _record(captured)["servicings"][ordinal]  # type: ignore[no-any-return]


# --------------------------------------------------------------------------- #
# §11 item 1: the reply-vocabulary question answers through the hop            #
# --------------------------------------------------------------------------- #


async def _seeded_store(*, content: str = _EARLIER) -> FakeMemoryStore:
    """A store holding the exchange and the belief that cites it.

    The belief carries the *question's* vocabulary and the episode carries the
    *answer's* — in ``outcome``, beside a ``disposition``, as ADR-0227 §7 requires and
    as ``Engine._capture`` writes one: "a question whose answer shares no wording with
    the record that holds it is not a ranking problem, and no allocation of a blind
    read fixes it".

    Args:
        content: What the episode's ``content`` says. The default shares no term with
            :data:`_QUESTION`, so the blind read cannot reach the exchange by any
            route; a case that wants the *episodic supplement* to pick it up passes
            one that does.
    """
    return await _seeded(FakeMemoryStore(now=lambda: AT), content=content)


async def _seeded[StoreT: FakeMemoryStore](store: StoreT, *, content: str = _EARLIER) -> StoreT:
    """Put :func:`_seeded_store`'s two records into ``store`` and hand it back.

    Separate from :func:`_seeded_store` so a case needing a *subclassed* store — one
    whose keyed load fails, say — holds the same two records without reaching into
    another store's internals for them.
    """
    await store.add(
        _episode(
            "episode-1",
            content,
            outcome=f"{_LENDER} is the best fit for your budget.",
            disposition=ExchangeDisposition.STEP_EXECUTED,
        )
    )
    await store.add(
        _belief(
            "belief-1",
            "the user asked about a lender for the house purchase",
            evidence=("episode-1",),
        )
    )
    return store


async def test_the_reply_vocabulary_question_answers_through_the_hop() -> None:
    """ADR-0226 §11 item 1 **as ADR-0227 §7 re-specifies it**: the exit shape, end to end.

    The blind read returns the belief and not the exchange — it is keyed on the
    question's words, and only ``content`` is embedded. The planner names that
    belief's label; the hop reaches the episode by pointer; and the answer carries
    it. #1844's sentence, mechanised: the hop "is **not a search**, so the reply's
    vocabulary never has to match anything; and it reaches the exchange by pointer,
    which is the only mechanism that answers 'which lender did you recommend?'"

    **This fails if the hop is merely wired**, which is why the assertion is the
    composed reply rather than the fourth group — and it now fails if the hop's yield
    is merely *supplied*, which is what #1944 records and what §7's fidelity rule
    exists to catch. The distinctive word is in the episode's ``outcome``, beside a
    ``disposition``, and absent from its ``content``: "the one combination no group
    but the tail renders" before ADR-0227 §1. The production
    :class:`~ai_assistant.orchestration.composing.ComposingStage` is on the path and
    the fake model reads the assembled prompt, so the answer can carry the word only
    if the renderer wrote it.
    """
    planner = _AskingPlanner(_hop("M1"))
    harness = Harness(memory=await _seeded_store(), planner=planner, composing=_echoing_composer())

    outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    planned = [record.id for record in planner.calls[0]]
    assert planned == ["belief-1"], "the blind read reached the belief and not the exchange"
    assert outcome.turn is not None
    assert [record.id for record in outcome.turn.memories] == ["belief-1", "episode-1"]
    assert _LENDER not in outcome.turn.memories[1].content, "the word is in `outcome` alone"
    assert outcome.reply == _LENDER


async def test_the_same_question_without_the_emission_cannot_answer() -> None:
    """The control that makes the case above a finding rather than a coincidence.

    The same store, the same question and the same composer — and a planner that
    asks for nothing. The exchange is unreachable, which is the system as it stands
    before this envelope and is what the +22.8 points of "hop" in the replay's split
    are made of.

    ADR-0227 §8 keeps it as assertion 2, "the control, unchanged in force": without
    it the case above would be a coincidence rather than a finding, since a composer
    that answered with the word for any reason would satisfy it.
    """
    harness = Harness(
        memory=await _seeded_store(),
        planner=_AskingPlanner(None),
        composing=_echoing_composer(),
    )

    outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    assert outcome.turn is not None
    assert [record.id for record in outcome.turn.memories] == ["belief-1"]
    assert outcome.reply == "I have no record of that."


# --------------------------------------------------------------------------- #
# ADR-0227 §8's assertions 4, 5, 8 and 16: the prompt the engine assembled      #
# --------------------------------------------------------------------------- #


#: The statement the sighted query is composed of in the partial-servicing case.
#: Matched exactly by :class:`_FailingQuery`, so the failure lands on the servicing's
#: own read and never on the turn's belief composition or its episodic supplement —
#: which a call counter could not separate, since the engine's loop runs both.
_SIGHTED: Final = "the exchange where a lender was named"


class _FailingKeyedLoad(FakeMemoryStore):
    """A store whose keyed load fails, so the servicing degrades (ADR-0226 §5)."""

    async def get_many(self, record_ids: Sequence[str]) -> dict[str, MemoryRecord]:
        del record_ids
        msg = "fake: the keyed load is unavailable"
        raise MemoryStoreError(msg)


class _FailingQuery(FakeMemoryStore):
    """A store whose ``search`` fails for the sighted query's own statement.

    ADR-0226 §6 services the hop first, so a store failing only on this text produces
    the **partial** servicing §5 names: a hop that returned records, and then a read
    that raised.
    """

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> MemorySearchResult:
        if query == _SIGHTED:
            msg = "fake: this band's read is unavailable"
            raise MemoryStoreError(msg)
        return await super().search(query, limit=limit, kinds=kinds, bands=bands)


async def test_a_record_both_kinds_reached_renders_once_at_the_hops_position() -> None:
    """ADR-0227 §8's assertion 4: ADR-0226 §7's union case, and §2 beside it.

    "A belief's cited evidence that the sighted query also returns" enters the fourth
    group once, at the hop's position, and its second arrival "consumes no slot of the
    budget". ADR-0227 §1 rules it a record the hop reached — "both kinds reaching one
    record is the hop reaching it" — so it is admitted by §1 and not by §2.

    **The shared record is a belief, and that is forced rather than chosen.** ADR-0226
    §6 services a ``SIGHTED_QUERY`` through ``assemble_by_band(… kinds=BELIEF_KINDS)``,
    so no query can return an episode — and an episode is the only record shape
    carrying an ``outcome`` and a ``disposition`` at all. What this case can therefore
    assert end to end is the half only the servicer decides: one bullet, at the hop's
    position, with no second copy. The reply-line half of §8's assertion 4 is
    ``test_composing.py``'s, over the carrier this servicing produces, because at the
    render site a union record and a hop-only record are the same input.

    **And §2 is asserted positively here** (§8's assertion 3, engine arm): the record
    the query alone returned renders its bullet and no reply line, and neither does
    the union record, because neither carries a reply to render.
    """
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(_belief("belief-1", "the user asked about a lender", evidence=("shared-1",)))
    # Neither of the two below shares a term with `_QUESTION`, so the blind read
    # reaches neither and both arrive through the servicing alone.
    await memory.add(_belief("shared-1", "an earlier exchange about mortgages"))
    await memory.add(_belief("query-1", "an earlier exchange about rates"))
    composing, model = _recorder()
    harness = Harness(
        memory=memory,
        planner=_AskingPlanner(_both("an earlier exchange", "M1")),
        composing=composing,
    )

    with structlog.testing.capture_logs() as captured:
        outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    assert outcome.turn is not None
    assert [record.id for record in outcome.turn.memories] == ["belief-1", "shared-1", "query-1"]
    serviced = _serviced(captured)
    assert serviced["new"] == 2, "the union record consumed one slot, not two"
    assert serviced["deduplicated"] == 1
    prompt = _assembled(model)
    assert prompt.count("an earlier exchange about mortgages") == 1, "one bullet"
    assert _reply_lines_of(prompt) == [], "neither belief carries a reply to render"


async def test_a_hop_record_the_supplement_already_held_renders_its_reply_where_it_sits() -> None:
    """ADR-0227 §8's assertion 5: the case a group-shaped test would miss.

    Here the episodic supplement has already picked the exchange up, so ADR-0226 §7's
    deduplication removes it from the fourth group and "the copy the supply already
    held keeps its position". §1's third clause renders it all the same: "a record the
    hop resolved through a named label's ``Provenance.evidence`` renders its reply
    whether it entered the fourth group or was deduplicated out against the
    pre-servicing supply".

    **This is the failure #1944 records, on a turn that looks like a success.** Under
    a group-shaped test the exact record the belief cites would render phrase-only
    whenever the supplement happened to have reached it first, "and no live probe
    would distinguish it from success" — which is why §1's test is why the record is
    there rather than which group it sits in.
    """
    memory = await _seeded_store(content=f"The user asked: {_QUESTION} for the house purchase?")
    composing, model = _recorder()
    harness = Harness(memory=memory, planner=_AskingPlanner(_hop("M1")), composing=composing)

    with structlog.testing.capture_logs() as captured:
        outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    assert outcome.turn is not None
    assert [record.id for record in outcome.turn.memories] == ["belief-1", "episode-1"]
    serviced = _serviced(captured)
    assert (serviced["new"], serviced["deduplicated"]) == (0, 1), (
        "no fourth group, and one duplicate"
    )
    (line,) = _reply_lines_of(_assembled(model))
    assert _LENDER in line, "the deduplicated-out record still renders its reply"


async def test_every_turn_that_serviced_no_hop_assembles_the_prompt_it_would_have() -> None:
    """ADR-0227 §8's assertion 8: the four empty cases render nothing.

    §3's carrier "is **empty** on every turn that did not fire, on a turn whose
    servicing ADR-0226 §5 declined, on a turn whose servicing failed or was partial …
    and on a turn whose hop resolved no live record. An empty set renders no reply
    line anywhere, and the assembled prompt is then byte-identical to what it is
    today."

    **The partial arm is the one with something to disclose**, and it is asserted
    here as well as at the carrier: on that turn the hop *did* reach the episode by
    pointer, and ADR-0226 §5 discarded what came back with the rest. Two independent
    things then keep the prompt unchanged — §3 empties the carrier at the servicer
    (``test_loop_reads.py``, which is the discriminating assertion), and the render
    site writes a line only for a record that is in the supply it was handed. This
    case is on the composed prompt, which is the guarantee §8's assertion 8 states and
    the one a reader of a probe would check.

    Each fired arm is compared against the **same store and the same question** under
    a planner that asks for nothing, which is what "byte-identical to today's" means
    operationally: the emission changed no byte of the prompt.
    """

    async def prompt_for(store: FakeMemoryStore, request: ReadRequest | None) -> str:
        composing, model = _recorder()
        harness = Harness(memory=store, planner=_AskingPlanner(request), composing=composing)
        await harness.engine.converse(_QUESTION, timeout=PATIENT)
        return _assembled(model)

    async def failing() -> _FailingKeyedLoad:
        return await _seeded(_FailingKeyedLoad(now=lambda: AT))

    async def partial() -> _FailingQuery:
        return await _seeded(_FailingQuery(now=lambda: AT))

    async def barren() -> FakeMemoryStore:
        store = FakeMemoryStore(now=lambda: AT)
        await store.add(
            _belief(
                "belief-1",
                "the user asked about a lender for the house purchase",
                evidence=("gone-1",),
            )
        )
        return store

    # Each pair is two identically seeded stores, asked the same question: once by a
    # planner that emitted a request and once by one that did not. A *fresh* store per
    # arm, because a turn captures its own episode — reusing one would compare a supply
    # of two records against a supply of one, rather than comparing two emissions.
    assert await prompt_for(await failing(), _hop("M1")) == await prompt_for(await failing(), None)
    assert await prompt_for(await barren(), _hop("M1")) == await prompt_for(await barren(), None)
    # The **partial** arm, and the one with something to leak: the hop resolves the
    # episode by pointer and *then* a query band raises. §5 discards what came back
    # with the rest, so a carrier surviving the discard would render the reply of a
    # record the supply no longer holds.
    partial_prompt = await prompt_for(await partial(), _both(_SIGHTED, "M1"))
    assert partial_prompt == await prompt_for(await partial(), None)
    assert _LENDER not in partial_prompt, "a discarded read discloses nothing"
    for store, request in (
        (await _seeded_store(), None),
        (await failing(), _hop("M1")),
        (await barren(), _hop("M1")),
        (await partial(), _both(_SIGHTED, "M1")),
    ):
        assert _reply_lines_of(await prompt_for(store, request)) == []


async def test_a_declined_servicing_assembles_a_prompt_with_no_reply_line() -> None:
    """ADR-0227 §8's assertion 8, on ADR-0226 §5's declined arm.

    ``converse_spoken``'s channel audience is unbounded, so the request is emitted and
    not serviced; §3's carrier is empty and ADR-0227 §10 records what follows — "this
    ADR reaches no unbounded-audience turn: a declined servicing reaches no record
    here, and the composed prompt on such a turn is byte-identical to today's".

    Compared against the same operation under a planner that asks for nothing, which
    is the same operational reading of "byte-identical" the case above takes.
    """

    async def spoken_prompt(request: ReadRequest | None) -> str:
        composing, model = _recorder()
        harness = Harness(
            memory=await _seeded_store(), planner=_AskingPlanner(request), composing=composing
        )
        await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)
        return _assembled(model)

    assert await spoken_prompt(_hop("M1")) == await spoken_prompt(None)
    assert _reply_lines_of(await spoken_prompt(_hop("M1"))) == []


async def test_no_identifier_the_hop_carried_reaches_a_prompt_a_log_or_the_audit() -> None:
    """ADR-0227 §8's assertion 16: §3's namer rule, on a turn that serviced a hop.

    "The identifiers in it are held data, used to decide which line the assembler
    writes, and they are rendered into no prompt, no log, no trace and no audit
    record." ADR-0226 §9's record carries "no identifier but the correlation id", as
    its own test asserts, and this ADR "introduces no second label scheme, adds no
    member to ``ReadKind``, and adds no marking to a ``MemoryRecord``".

    The reply *text* does reach the prompt — that is the whole decision — so the
    assertion is on the identifier, which is the value §3 keeps off every surface.
    """
    composing, model = _recorder()
    harness = Harness(
        memory=await _seeded_store(), planner=_AskingPlanner(_hop("M1")), composing=composing
    )

    with structlog.testing.capture_logs() as captured:
        outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    assert outcome.turn is not None
    prompt = _assembled(model)
    assert _LENDER in prompt, "the reply reached the prompt"
    assert "episode-1" not in prompt, "and its identifier did not"
    assert not any("episode-1" in json.dumps(event, default=str) for event in captured)
    # ADR-0228 §9 extends this record rather than replacing it: the per-servicing
    # counts became `servicings`, one entry per servicing, and two turn-level fields
    # joined them. Neither level carries an identifier but the correlation id.
    assert set(_record(captured)) == {
        "event",
        "log_level",
        "correlation_id",
        "trigger",
        "servicing",
        "planner_calls",
        "stop",
        "servicings",
    }
    assert set(_serviced(captured)) == {
        "kinds",
        "returned",
        "new",
        "deduplicated",
        "labels_unresolved",
        # ADR-0230 §9's one added field. It is a closed-enumeration member or absent,
        # and on this turn — a hop, with no ``LOCAL_FILE`` ask — it is absent, which
        # is one of the two cases §9 enumerates for an empty one.
        "refusal",
        # ADR-0231 §13's one added field, on the same terms: a closed-enumeration
        # member or absent, absent here because this turn carried no ``WEB_SEARCH``
        # ask. It is a **class** and carries no query, no fragment of one, no
        # length, no origin, no host, no address, no title, no snippet and no
        # provider message — which is why §9's no-copy rule admits it beside the
        # counts, and why this assertion still holds over the whole record.
        "disposition",
        "truncated_kinds",
        "failed",
        "failed_after_read_returned",
    }


# --------------------------------------------------------------------------- #
# §11 item 5's engine arm: converse_spoken declines                            #
# --------------------------------------------------------------------------- #


async def test_a_spoken_turn_services_nothing_and_records_the_emission_as_declined() -> None:
    """§11 item 5, on the operation ADR-0200 §3 declares unbounded.

    ADR-0203 §2's backfill clause is what decided this: on such a turn the planner
    judges sufficiency over a supply the subtraction has already thinned, so a read
    it emits "is shaped by what was withheld even though the planner never saw it".

    The engine derives the refusal from the supply object it already mints, which is
    what keeps §5 mechanical rather than remembered — and the emission is still
    recorded, because "what is scoped is the **servicing**, so the trigger goes on
    being measured on every channel".
    """
    planner = _AskingPlanner(_hop("M1"))
    harness = Harness(memory=await _seeded_store(), planner=planner)

    with structlog.testing.capture_logs() as captured:
        spoken = await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    turn = spoken.outcome.turn
    assert turn is not None
    assert turn.memories == planner.calls[0], "no fourth group"
    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["servicing"] == Servicing.DECLINED.value
    # Nothing was serviced, so ADR-0228 §9's sequence is empty — and this operation
    # neither iterates nor could: §2(c) admits a revision only where the request was
    # serviced, and §4 declares `converse_spoken` no planning budget at all (§2(a)).
    assert record["servicings"] == ()
    assert record["planner_calls"] == 1
    assert record["stop"] == StopReason.NOT_ITERATED.value
    assert len(planner.calls) == 1, "no spoken turn iterates (ADR-0228 §4)"


async def test_a_typed_turn_of_the_same_engine_is_serviced() -> None:
    """The pair to the case above: the scoping is the channel's and not the engine's.

    One engine, one planner, one store — and the request is serviced on ``converse``
    and declined on ``converse_spoken``. That is ADR-0199 §1's posture being a
    function of the output channel's audience alone.
    """
    planner = _AskingPlanner(_hop("M1"))
    harness = Harness(memory=await _seeded_store(), planner=planner)

    with structlog.testing.capture_logs() as captured:
        outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    assert outcome.turn is not None
    assert [record.id for record in outcome.turn.memories] == ["belief-1", "episode-1"]
    record = _record(captured)
    serviced = _serviced(captured)
    assert record["servicing"] == Servicing.SERVICED.value
    assert serviced["new"] == 1


# --------------------------------------------------------------------------- #
# §11 item 10's post-plan arms: the record is gated on nothing                 #
# --------------------------------------------------------------------------- #


async def test_a_turn_rejected_for_capacity_still_contributes_its_numerator() -> None:
    """§11 item 10's first arm, and §9's reason for it.

    ``AssistantEngine`` admits and reserves capacity **after** the loop has planned
    and serviced, "so a full system rejects a turn whose planner had already fired".
    Under a record gated on the turn completing, the fire rate would read low by
    exactly the number of turns that went wrong.
    """
    harness = Harness(
        tools=(confirmable(),),
        planner=_AskingOneStepPlanner(_query("an earlier exchange")),
        max_outstanding_confirmations=1,
    )
    parked = await harness.engine.converse("send one", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None

    with (
        structlog.testing.capture_logs() as captured,
        pytest.raises(RuntimeError, match="already awaiting an answer"),
    ):
        await harness.engine.converse("send two", timeout=PATIENT)

    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["servicing"] == Servicing.SERVICED.value


async def test_a_turn_whose_plan_cannot_be_persisted_still_contributes_its_numerator() -> None:
    """§11 item 10's second arm: a ``PlanStore.save_plan`` failure loses no record.

    §9 makes the emission "conditioned on nothing: not on the plan being persisted,
    not on the turn completing, and not on capacity being admitted". The record owes
    nothing to those later stages, "because it carries no reference into them".
    """
    harness = Harness(memory=await _seeded_store(), planner=_AskingPlanner(_hop("M1")))

    async def refuse(plan: ActionPlan) -> str:
        del plan
        msg = "fake: the plan store is unavailable"
        raise MemoryStoreError(msg)

    harness.plans.save_plan = refuse  # type: ignore[method-assign]

    with structlog.testing.capture_logs() as captured, pytest.raises(MemoryStoreError):
        await harness.engine.converse(_QUESTION, timeout=PATIENT)

    record = _record(captured)
    serviced = _serviced(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["servicing"] == Servicing.SERVICED.value
    assert serviced["new"] == 1


async def test_a_routed_pass_reaches_no_turn_stage_and_writes_no_record() -> None:
    """The reading this lane takes on a pass that never reaches a supply.

    ADR-0197 §1 ends the pipeline at a taken route: "no history is read, no goal is
    minted, no context is assembled, no memories are retrieved, no plan is made or
    driven". §9 puts the record in the turn — "at any point in the turn after the
    servicing decision is known" — and a routed pass has no servicing decision to
    make and no supply to judge, so it emits none rather than emitting a
    not-reached record from a second site.

    Recorded as a case rather than left implicit, because it is the one shape §8's
    three outcomes do not obviously classify, and a later lane should meet the
    reading rather than rediscover the question. A **declined** route is a turn like
    any other and does write one, which is the pair below.
    """
    harness = _routed_harness()

    with structlog.testing.capture_logs() as captured:
        outcome = await harness.engine.converse(_ROUTED, timeout=PATIENT)

    assert outcome.routed is not None, "the route was taken"
    assert _records(captured) == []


async def test_a_declined_route_runs_the_ordinary_pipeline_and_writes_one_record() -> None:
    """The pair to the case above: a declined route is a turn (ADR-0197 §1).

    "The pass proceeds exactly as it does today and the outcome it returns carries
    no trace of the stage having run" — so it reaches the turn stage, reaches the
    servicing decision, and contributes its denominator.
    """
    harness = _routed_harness(
        router=_router(_DECLINED), planner=_AskingPlanner(None), memory=await _seeded_store()
    )

    with structlog.testing.capture_logs() as captured:
        outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    assert outcome.routed is None, "the route was declined"
    assert _record(captured)["trigger"] == TriggerOutcome.NOT_FIRED.value


# --------------------------------------------------------------------------- #
# ADR-0229 §6: a label names a destination, and the hop reaches it             #
# --------------------------------------------------------------------------- #
#
# §6's tests 1, 2, 5 and 7 — each an assertion about a prompt the *engine*
# assembled from a supply the *servicer* built, which is what puts them here and
# not beside the carrier. Every one is subject to ADR-0227 §7's fidelity rule
# entire: the production :class:`ComposingStage` assembles the prompt, and the
# fixtures are shaped as ``Engine._capture`` writes an episode — the reply's
# distinctive word in ``outcome``, beside a ``disposition``, and absent from
# ``content``. Tests 3, 4, 6 and 7 assert over the carrier the servicer produced —
# which no engine-level case can see — and live in ``test_loop_reads.py``.


class _OmittingKeyedLoad(FakeMemoryStore):
    """A store whose keyed load omits one record it still holds (ADR-0226 §3).

    §3's third way of resolving to nothing is "a record ``MemoryStore.get_many``
    does not return", and ADR-0229 §4 keeps it entire: such a label reaches nothing
    at all, "even though the turn's supply still holds that record and still renders
    its bullet". A store that *raised* would degrade the whole servicing (§5) and so
    could not produce this case; one that drops a single identifier can.
    """

    def __init__(self, omitted: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._omitted = omitted

    async def get_many(self, record_ids: Sequence[str]) -> dict[str, MemoryRecord]:
        found = await super().get_many(record_ids)
        return {
            identifier: record
            for identifier, record in found.items()
            if identifier != self._omitted
        }


async def test_a_named_episode_in_the_supplement_renders_the_reply_it_carries() -> None:
    """ADR-0229 §6 test 1: #1960's probe, as a fixture. **This fails on ``origin/main``.**

    The exchange is in the **episodic supplement**, where ADR-0222 §2 renders it as a
    bullet with a ``how it turned out:`` phrase and no reply — "precisely the shape
    ``planning/planner.py``'s act-record guidance tells the planner to point at". The
    planner names that episode's own label, and no belief cites it, so the record
    holding the answer is zero edges away and a hop that could only travel outward
    reached nothing: on ``origin/main`` the carrier is empty and the word never
    reaches the prompt. That is #1960's audit line —
    ``returned=10 new=0 deduplicated=10`` beside *"I wasn't able to pull up that
    original reply"* — in fixture form.

    **No belief cites the episode, and that is the discriminating half.** ADR-0229 §5:
    "an exchange from this week that no observation pass has yet distilled into
    anything is reachable **only** by naming it", so there is no longer route to the
    same record for an implementation to take instead. The belief that *is* seeded
    cites nothing: it is
    :meth:`~ai_assistant.orchestration.loop.LearningLoop._supplement`'s separator, and
    a supply of episodes alone is one ADR-0074 §5 gives no supplement to.
    """
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(_belief("belief-1", "the user asked about a lender for the house purchase"))
    await memory.add(
        _episode(
            "episode-1",
            f"The user asked: {_QUESTION} for the house purchase?",
            outcome=f"{_LENDER} is the best fit for your budget.",
            disposition=ExchangeDisposition.STEP_EXECUTED,
        )
    )
    composing, model = _recorder()
    planner = _AskingPlanner(_hop("M2"))
    harness = Harness(memory=memory, planner=planner, composing=composing)

    outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    planned = [record.id for record in planner.calls[0]]
    assert planned == ["belief-1", "episode-1"], "the supplement held the exchange"
    assert outcome.turn is not None
    assert not any(record.provenance.evidence for record in outcome.turn.memories), "no citation"
    assert _LENDER not in outcome.turn.memories[1].content, "the word is in `outcome` alone"
    (line,) = _reply_lines_of(_assembled(model))
    assert _LENDER in line, "the record the label named rendered its reply"


async def test_a_belief_label_still_hops_to_its_evidence_and_adds_nothing_else() -> None:
    """ADR-0229 §6 test 2: the case ADR-0226 §2 was built for is untouched.

    A labelled belief citing an episode: the episode's reply renders exactly as it
    did, and the belief — now in the carrier ahead of its own evidence, because
    ADR-0229 §1 applies "no class, kind or field test at the servicer" — grows no
    line. ADR-0227 §1's field test decides that at the render site, over a
    ``disposition`` a ``SemanticMemory`` has no field for, and
    :func:`~ai_assistant.orchestration.composing._hop_reply_lines` skips an
    ineligible record before counting it against §4's cap.

    **The byte-identity is asserted against this very turn under the old carrier**,
    which is the only control that isolates what §1 widened: the same supply, the
    same production renderer, and a carrier holding the episode alone. Anything the
    named belief added would show up as a difference.
    """
    composing, model = _recorder()
    harness = Harness(
        memory=await _seeded_store(), planner=_AskingPlanner(_hop("M1")), composing=composing
    )

    outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    assert outcome.turn is not None
    assert [record.id for record in outcome.turn.memories] == ["belief-1", "episode-1"]
    (line,) = _reply_lines_of(_assembled(model))
    assert _LENDER in line, "the belief's evidence rendered its reply"

    control_stage, control = _recorder()
    await control_stage.compose(
        turn=outcome.turn, step=None, undriven=(), hop_reached=("episode-1",)
    )
    assert _assembled(model) == _assembled(control), "the belief added not one byte"


async def test_a_label_whose_record_the_keyed_load_omits_reaches_nothing() -> None:
    """ADR-0229 §6 test 5: §4's liveness case, which this ADR deliberately did not move.

    "A label whose record ``MemoryStore.get_many`` does not return resolved to
    **nothing**: it never enters this section's expansion sequence at all." The
    tempting answer — honouring the label from the supply's own copy, which the turn
    demonstrably has — is refused twice over: it would change what
    ``labels_unresolved`` counts, and it "would render, into a model prompt, the reply
    of a record the store no longer holds — reading a forgotten exchange back to the
    user by a route no forgetting mechanism is watching".

    So the supply still holds the episode and still renders its bullet, and the
    prompt carries no reply line at all.
    """
    memory = await _seeded(
        _OmittingKeyedLoad("episode-1", now=lambda: AT),
        content=f"The user asked: {_QUESTION} for the house purchase?",
    )
    composing, model = _recorder()
    harness = Harness(memory=memory, planner=_AskingPlanner(_hop("M2")), composing=composing)

    with structlog.testing.capture_logs() as captured:
        outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    assert outcome.turn is not None
    assert [record.id for record in outcome.turn.memories] == ["belief-1", "episode-1"]
    serviced = _serviced(captured)
    assert serviced["labels_unresolved"] == 1, "the label resolved to nothing"
    prompt = _assembled(model)
    assert _reply_lines_of(prompt) == [], "and the deleted record's reply reached no prompt"
    assert _LENDER not in prompt
