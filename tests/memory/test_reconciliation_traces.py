"""ADR-0164's ten reconciliation keys, read off the ``MEMORY_WRITE`` trace.

#1209 asks a question the stream could not answer: pilot-4 reported 1,051
``ACCEPT`` rulings, 6 ``REINFORCE`` and **zero** ``SUPERSEDE``, and two
incompatible readings fit that exactly — either the reconciler labelled a member
``CONTRADICTS`` and ADR-0159 §4's purity conditions refused the supersession, or
the reconciler never said it. These keys are what separates them, so the cases
here are written against the **emitted trace** and never against the writer's
internals: what a reader of ``traces.db`` can conclude is the whole product.

Two properties run through all of it and are worth stating once:

* **Two units.** The four proposal keys count proposals; the six pair keys count
  one proposal against one member of its resolved conflict set. A proposal that
  clears ADR-0159 §2's invocation condition with an *empty* conflict set is
  ``reconciled`` and offers no pair at all — the common case, not an edge one.
* **Present with zeros wherever a reading is taken, absent only where none is.**
  The ten ride the statement that writes the six ``decisions_*`` keys, so no
  crossing carries one set without the other.

``test_reconciler.py`` holds the other side of the seam — which outcome
``ModelBackedReconciler`` reports, and when — because that is a fact only the
reconciler holds. Here it is what the *writer* does with a report, conforming or
not.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.core.errors import UnresolvedEvidenceError
from ai_assistant.core.types import (
    ConflictRelation,
    EpisodicMemory,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
    SourceReading,
    TraceKind,
    TraceOutcome,
)
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor, traces
from ai_assistant.memory._reconciler import (
    ModelBackedReconciler,
    ReconcilerOutcome,
    ReconcilerReport,
)
from ai_assistant.testing import FakeMemoryPolicy, FakeModelProvider, FakeTraceSink

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore
    from ai_assistant.core.types import EvaluationTrace, MemoryRecord

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_EPISODE = "episode-1"
_ROUTE = "anthropic:claude-x"
_SOURCE = "reader:test"

#: The contents these cases plant. Kept together because every case depends on
#: them landing in one conflict set at :data:`_THRESHOLD`, and a content edited in
#: place would silently shrink the set a case is counting pairs over.
_MORNING = "user prefers morning meetings"
_AFTERNOON = "user prefers afternoon meetings"
_FRIDAYS = "user prefers morning meetings on fridays"
_WINTER = "user prefers morning meetings in winter"
_TEA = "user prefers morning meetings with tea"

#: Low enough that the contents above are one another's conflicts, which is what
#: makes a *pair* count observable at all.
_THRESHOLD = 0.5


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


def _prov(source: MemorySource = MemorySource.OBSERVED) -> Provenance:
    return Provenance(
        source=source,
        confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.6,
        last_updated=_WHEN,
        evidence=(_EPISODE,),
    )


async def _plant_episode(store: MemoryStore) -> None:
    """Store the episode every proposal here cites, so the citation resolves.

    ``OBSERVED`` is in the ``DERIVED`` band, where ADR-0072 §3 obliges a citation
    and the admissibility floor rejects one that cites nothing — and that floor is
    *inside* ADR-0159 §2's invocation condition, so a proposal citing nothing would
    never be reconciled and every count here would be zero for the wrong reason.
    """
    await store.add(
        EpisodicMemory(
            id=_EPISODE,
            content="the exchange the proposals cite",
            occurred_at=_WHEN,
            provenance=_prov(),
        )
    )


def _belief(
    record_id: str, content: str, *, source: MemorySource = MemorySource.OBSERVED
) -> MemoryRecord:
    return PreferenceMemory(
        id=record_id, content=content, preference=content, provenance=_prov(source)
    )


def _proposal(record: MemoryRecord) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="because")


def _writer(
    store: MemoryStore,
    sink: FakeTraceSink,
    *,
    reconciler: Any = None,
    policy: MemoryPolicy | None = None,
) -> MemoryIngestor:
    return MemoryIngestor(
        traces_sink=sink,
        store=store,
        policy=policy if policy is not None else DefaultMemoryPolicy(),
        now=_fixed_now,
        conflict_threshold=_THRESHOLD,
        reconciler=reconciler,
    )


async def _planted(*beliefs: MemoryRecord) -> InMemoryMemoryStore:
    store = InMemoryMemoryStore(now=_fixed_now)
    await _plant_episode(store)
    for belief in beliefs:
        await store.add(belief)
    return store


def _only(sink: FakeTraceSink) -> EvaluationTrace:
    """The one ``MEMORY_WRITE`` trace the sink holds (ADR-0119 §5's one-crossing rule)."""
    written = [trace for trace in sink.recorded if trace.kind is TraceKind.MEMORY_WRITE]
    assert len(written) == 1, f"expected exactly one write trace, got {len(written)}"
    return written[0]


def _ten(trace: EvaluationTrace) -> dict[str, int]:
    """The ten keys, asserted **present** before any case reads one of them.

    ADR-0164 §3 makes presence-with-zeros the ruled shape wherever a reading is
    taken, so a case that read one key with ``.get(key, 0)`` would pass just as
    happily on a trace that omitted the other nine — which is the emitter failing
    at exactly the thing this section is about.
    """
    missing = [key for key in traces.RECONCILIATION_METRICS if key not in trace.metrics]
    assert not missing, f"a reading was taken, so these should be present: {missing}"
    return {key: int(trace.metrics[key]) for key in traces.RECONCILIATION_METRICS}


@pytest.fixture
def sink() -> FakeTraceSink:
    """The sink an emitter's test is handed: append only, read back by the test."""
    return FakeTraceSink()


# --- the doubles --------------------------------------------------------------


class _Reporting:
    """Returns fixed labels under a chosen report, conforming or not.

    The outcome set is taken whole rather than as one member, because ADR-0164 §3
    rules on a report naming **none** of the three and on one naming **more than
    one**, and neither shape is expressible where a double can only name one.
    """

    def __init__(
        self,
        labels: Mapping[str, object],
        outcomes: frozenset[object] = frozenset({ReconcilerOutcome.ANSWERED}),
    ) -> None:
        self._labels = dict(labels)
        self._outcomes = outcomes
        self.calls = 0

    async def reconcile(
        self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
    ) -> ReconcilerReport:
        """Answer with this double's fixed labels and report."""
        self.calls += 1
        return ReconcilerReport(
            relations=self._labels,  # type: ignore[arg-type]  # a case may plant a non-member
            outcomes=self._outcomes,  # type: ignore[arg-type]  # or a non-outcome
        )


class _ByRank:
    """Labels members by their **rank** in the conflict set it is handed.

    The beyond-the-bound case needs a label for a member the reconciler's bound
    could not have covered, and rank is the only handle on that: the writer holds
    no consulted set, and which id sorts fourth is the store's answer rather than
    the test's.
    """

    def __init__(self, labels: Mapping[int, object]) -> None:
        self._labels = dict(labels)

    async def reconcile(
        self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
    ) -> ReconcilerReport:
        """Answer for the ranks this double was built with."""
        return ReconcilerReport(
            relations={conflicts[rank].id: label for rank, label in self._labels.items()},  # type: ignore[misc]
            outcomes=frozenset({ReconcilerOutcome.ANSWERED}),
        )


class _Raising:
    """A reconciler that raises, which ADR-0159 §3 forbids and §6 absorbs anyway."""

    async def reconcile(
        self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
    ) -> ReconcilerReport:
        """Fail the way a non-conforming component does."""
        msg = "a non-conforming reconciler"
        raise RuntimeError(msg)


class _Returning:
    """A reconciler that returns something unusable instead of raising."""

    def __init__(self, answer: object) -> None:
        self._answer = answer

    async def reconcile(
        self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
    ) -> ReconcilerReport:
        """Hand back whatever this double was built with."""
        return self._answer  # type: ignore[return-value]  # deliberately non-conforming


class _Hostile(dict[str, ConflictRelation]):
    """A mapping that will not be read — the third shape the writer's guard absorbs."""

    def __contains__(self, key: object) -> bool:
        """Refuse the lookup ``_relations_for`` makes."""
        msg = "this mapping refuses to be read"
        raise RuntimeError(msg)


class _NoReport:
    """A report **missing** where one was due: the relations, and nothing beside."""

    def __init__(self, labels: Mapping[str, ConflictRelation]) -> None:
        self.relations = dict(labels)


class _RaisingProvider:
    """A provider whose every call fails the way a dead route does."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages: Sequence[object], *, model: str | None = None) -> object:
        """Fail, counting the attempt."""
        self.calls += 1
        msg = "the route is down"
        raise RuntimeError(msg)


def _labelling(**labels: str) -> FakeModelProvider:
    """A provider replying with ADR-0159 §3's envelope for ``labels``."""
    reply = json.dumps(
        {"relations": [{"id": rid, "relation": value} for rid, value in labels.items()]}
    )
    return FakeModelProvider(reply=reply)


# --- the rung split, which is the whole point ---------------------------------


async def test_a_certain_label_is_counted_as_certain_and_under_no_model_key(
    sink: FakeTraceSink,
) -> None:
    """ADR-0164 §7's first pinned test, and the trap the Consequences name.

    The merged mapping and the rung split are two views of one determination, and
    an implementation that starts counting the merged one passes every test that
    does not specifically distinguish them. So the reconciler here **also** returns
    a label for the member the certain predicate settled: ADR-0159 §3 rules that
    rung unconditional and discards such a label, and the count records the label
    that *stands*. A merged counter would report a model ``CONTRADICTS`` for a pair
    no model was even asked about.
    """
    store = await _planted(_belief("same", _MORNING))
    reconciler = _Reporting({"same": ConflictRelation.CONTRADICTS})

    await _writer(store, sink, reconciler=reconciler).ingest(_proposal(_belief("new", _MORNING)))

    counts = _ten(_only(sink))
    assert counts[traces.RELATIONS_CERTAIN_RESTATES] == 1
    assert counts[traces.RELATION_METRICS[ConflictRelation.RESTATES]] == 0
    assert counts[traces.RELATION_METRICS[ConflictRelation.CONTRADICTS]] == 0
    assert counts[traces.RELATIONS_OFFERED] == 1
    assert counts[traces.RELATIONS_UNLABELLED] == 0


async def test_a_model_contradiction_is_counted_on_a_crossing_ruled_accept(
    sink: FakeTraceSink,
) -> None:
    """The pilot-4 shape this ADR exists to make readable (#1209).

    A run reporting zero supersessions beside a **positive**
    ``relations_model_contradicts`` says a model contradiction stood and that no
    supersession followed it; a zero there says the reconciler never returned one.
    Today both present as an unremarkable run of ``ACCEPT``s, which is exactly the
    crossing driven here.
    """
    store = await _planted(_belief("stale", _MORNING))
    reconciler = _Reporting({"stale": ConflictRelation.CONTRADICTS})
    writer = _writer(
        store, sink, reconciler=reconciler, policy=FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)
    )

    result = await writer.ingest(_proposal(_belief("new", _AFTERNOON)))

    assert result.decision.kind is MemoryDecisionKind.ACCEPT
    trace = _only(sink)
    assert trace.metrics["decisions_accept"] == 1
    assert trace.metrics["decisions_supersede"] == 0
    counts = _ten(trace)
    assert counts[traces.RELATION_METRICS[ConflictRelation.CONTRADICTS]] == 1
    assert counts[traces.RELATIONS_CERTAIN_RESTATES] == 0
    assert counts[traces.RELATIONS_UNLABELLED] == 0
    assert counts[traces.RECONCILED] == 1
    assert counts[traces.RECONCILER_FAILED] == 0


async def test_the_five_label_keys_partition_the_offered_pairs(sink: FakeTraceSink) -> None:
    """ADR-0164 §3: every offered pair is counted under exactly one of the five.

    Driven over a crossing carrying one of each interesting kind — a pair the
    certain rung settled, a pair a model labelled, and a pair nobody labelled — so
    the sum is an identity the emitter has to hold rather than an accident of three
    zeros.
    """
    store = await _planted(
        _belief("same", _MORNING), _belief("other", _AFTERNOON), _belief("fridays", _FRIDAYS)
    )
    reconciler = _Reporting({"other": ConflictRelation.ADDS})
    writer = _writer(
        store, sink, reconciler=reconciler, policy=FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)
    )

    await writer.ingest(_proposal(_belief("new", _MORNING)))

    counts = _ten(_only(sink))
    labelled = (
        counts[traces.RELATIONS_CERTAIN_RESTATES]
        + counts[traces.RELATIONS_UNLABELLED]
        + sum(counts[key] for key in traces.RELATION_METRICS.values())
    )
    assert counts[traces.RELATIONS_OFFERED] == 3
    assert labelled == counts[traces.RELATIONS_OFFERED]
    assert counts[traces.RELATIONS_CERTAIN_RESTATES] == 1
    assert counts[traces.RELATION_METRICS[ConflictRelation.ADDS]] == 1
    assert counts[traces.RELATIONS_UNLABELLED] == 1


async def test_every_count_is_a_non_negative_integer_and_never_a_boolean(
    sink: FakeTraceSink,
) -> None:
    """ADR-0164 §2 adopts ADR-0120 §2's count rule rather than restating it.

    ``bool`` is an ``int`` in Python, so a key that started carrying a flag would
    satisfy every arithmetic assertion above while making the measure that reads it
    count ``True`` as one. The predicate is stated here rather than imported from
    ``evaluation``: golden rule 1 forbids ``memory`` naming that subsystem, and one
    ADR's rule holding of another ADR's keys is a property, not a shared call.
    """
    store = await _planted(_belief("same", _MORNING), _belief("other", _AFTERNOON))
    reconciler = _Reporting({"other": ConflictRelation.ADDS})

    await _writer(store, sink, reconciler=reconciler).ingest(_proposal(_belief("new", _MORNING)))

    metrics = _only(sink).metrics
    for key in traces.RECONCILIATION_METRICS:
        value = metrics[key]
        assert isinstance(value, int), key
        assert not isinstance(value, bool), key
        assert value >= 0, key


# --- the four proposal keys ---------------------------------------------------


async def test_an_empty_conflict_set_is_reconciled_offers_no_pair_and_asks_nothing(
    sink: FakeTraceSink,
) -> None:
    """ADR-0164 §3's two-unit clause and the path that dominates the population.

    ``_may_reconcile``'s ``all(...)`` over an empty sequence is vacuously true, so a
    proposal with no conflicts **is** reconciled and contributes nothing to
    ``relations_offered`` — which is why ``reconciled`` is the wrong denominator for
    any relation figure. It also reaches the reconciler with nothing to consult
    about, so it counts under ``reconciler_unconsulted``: an implementation reading
    that key as "certainty settled it" gets this, the common case, wrong. The pair
    of keys is what tells the two apart, and neither does it alone.
    """
    store = await _planted()
    model = FakeModelProvider()
    reconciler = ModelBackedReconciler(model=model, route=_ROUTE)

    await _writer(store, sink, reconciler=reconciler).ingest(_proposal(_belief("new", _MORNING)))

    counts = _ten(_only(sink))
    assert model.call_count == 0
    assert counts[traces.RECONCILED] == 1
    assert counts[traces.RELATIONS_OFFERED] == 0
    assert counts[traces.RECONCILER_UNCONSULTED] == 1
    assert counts[traces.RECONCILER_ABSENT] == 0
    assert counts[traces.RECONCILER_FAILED] == 0


async def test_a_writer_holding_no_reconciler_counts_absent_and_keeps_the_certain_rung(
    sink: FakeTraceSink,
) -> None:
    """ADR-0159 §6's ratified floor, visible in the stream for the first time.

    The deployment with no reconciler injected is the one ADR-0164 §4 says a
    policy-side emitter would report as an empty reconciliation: ``decide`` is
    handed ``None`` while this writer holds the certain rung's labels. Reading the
    writer's own mapping is what makes the pair keys tell the truth here.

    ``reconciler_unconsulted`` stays at zero on the same trace, which is the one
    overlap the two keys' wording invites: "no request was made" is true of this
    crossing, and the key that says it is a statement about a reconciler that *ran*.
    """
    store = await _planted(_belief("same", _MORNING))
    policy = FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)

    await _writer(store, sink, reconciler=None, policy=policy).ingest(
        _proposal(_belief("new", _MORNING))
    )

    assert policy.calls[0].relations is None, "ADR-0161 §4: decide is handed None"
    counts = _ten(_only(sink))
    assert counts[traces.RECONCILER_ABSENT] == 1
    assert counts[traces.RECONCILER_UNCONSULTED] == 0
    assert counts[traces.RECONCILER_FAILED] == 0
    assert counts[traces.RECONCILED] == 1
    assert counts[traces.RELATIONS_CERTAIN_RESTATES] == 1
    assert counts[traces.RELATIONS_OFFERED] == 1


async def test_a_reconciler_that_raises_counts_as_failed(sink: FakeTraceSink) -> None:
    """ADR-0159 §6 through the writer's guard, now counted rather than only absorbed."""
    store = await _planted(_belief("same", _MORNING), _belief("other", _AFTERNOON))

    await _writer(store, sink, reconciler=_Raising()).ingest(_proposal(_belief("new", _MORNING)))

    counts = _ten(_only(sink))
    assert counts[traces.RECONCILER_FAILED] == 1
    assert counts[traces.RELATIONS_CERTAIN_RESTATES] == 1, "the rung never depended on it"
    assert counts[traces.RELATIONS_UNLABELLED] == 1


async def test_a_provider_that_raises_is_counted_through_the_real_reconciler(
    sink: FakeTraceSink,
) -> None:
    """The finding ADR-0164 nearly got wrong, pinned where a stub cannot reach.

    ``ModelBackedReconciler.reconcile`` absorbs a provider failure **itself**, so
    the writer's guard never sees one and a key counted at the writer alone could
    not have distinguished a failed determination from a silent model. That is why
    §3 takes the outcome across the reconciler seam at all, and why this case drives
    a raising ``ModelProvider`` rather than a reconciler double.
    """
    store = await _planted(_belief("stale", _MORNING))
    provider = _RaisingProvider()
    reconciler = ModelBackedReconciler(model=provider, route=_ROUTE)  # type: ignore[arg-type]

    await _writer(store, sink, reconciler=reconciler).ingest(_proposal(_belief("new", _AFTERNOON)))

    assert provider.calls == 1, "the request was attempted"
    counts = _ten(_only(sink))
    assert counts[traces.RECONCILER_FAILED] == 1
    assert counts[traces.RECONCILER_UNCONSULTED] == 0
    assert counts[traces.RELATIONS_UNLABELLED] == 1


async def test_a_readable_empty_answer_carries_no_qualifier_at_all(sink: FakeTraceSink) -> None:
    """The conforming "nothing to add", and the arithmetic that makes it readable.

    An asked-and-empty reply and a reconciler that never asked hand the writer the
    same empty mapping. ADR-0164 §7 requires this case through the **real**
    reconciler on a readable empty response for exactly that reason: an
    implementation reading it as ``reconciler_unconsulted`` would pass every other
    case here while emitting a trace that denies the request was made. All three
    qualifiers at zero is what says the model rung answered — the answered count has
    no key of its own, being ``reconciled`` less the three.
    """
    store = await _planted(_belief("stale", _MORNING))
    model = FakeModelProvider(reply='{"relations": []}')
    reconciler = ModelBackedReconciler(model=model, route=_ROUTE)

    await _writer(store, sink, reconciler=reconciler).ingest(_proposal(_belief("new", _AFTERNOON)))

    assert model.call_count == 1
    counts = _ten(_only(sink))
    assert counts[traces.RECONCILED] == 1
    assert counts[traces.RECONCILER_ABSENT] == 0
    assert counts[traces.RECONCILER_FAILED] == 0
    assert counts[traces.RECONCILER_UNCONSULTED] == 0
    assert counts[traces.RELATIONS_OFFERED] == 1
    assert counts[traces.RELATIONS_UNLABELLED] == 1


async def test_a_set_the_certain_rung_settled_counts_unconsulted_with_no_request(
    sink: FakeTraceSink,
) -> None:
    """ADR-0159 §3's other half of the one-request clause, counted.

    Read beside ``relations_offered``, which is positive here and zero in the empty
    case above: the pair separates "certainty settled the set" from "there was
    nothing to settle", and neither key says it alone.
    """
    store = await _planted(_belief("same", _MORNING), _belief("twin", _MORNING))
    model = FakeModelProvider()
    reconciler = ModelBackedReconciler(model=model, route=_ROUTE)

    await _writer(store, sink, reconciler=reconciler).ingest(_proposal(_belief("new", _MORNING)))

    assert model.call_count == 0
    counts = _ten(_only(sink))
    assert counts[traces.RECONCILER_UNCONSULTED] == 1
    assert counts[traces.RELATIONS_OFFERED] == 2
    assert counts[traces.RELATIONS_CERTAIN_RESTATES] == 2
    assert counts[traces.RELATIONS_UNLABELLED] == 0


# --- what a non-conforming determination does, and does not, install ----------


async def test_a_value_equal_to_a_relation_but_not_one_leaves_the_member_unlabelled(
    sink: FakeTraceSink,
) -> None:
    """ADR-0164 §3's installing-on-identity clause, and why it is not defensive typing.

    ``ConflictRelation`` is a ``StrEnum``, so the bare string ``"contradicts"``
    compares equal to ``CONTRADICTS`` **and hashes with it**: a metric mapping keyed
    by the enum would find it and count it, while ``DefaultMemoryPolicy``'s ``is
    ConflictRelation.CONTRADICTS`` would not — the instrument reporting a model
    contradiction the arm never saw, silently, about the same pair. Installing on
    the test the policy already applies closes it, and **no ruling moves**: such a
    value is unlabelled to the arm today by that same ``is``.

    It also costs the crossing no trace, which is the other half. A value equal to
    *no* member would make the metric mapping raise, and ADR-0119 §5 turns a mapper
    that raises into a lost trace rather than a lost write — one non-conforming
    reconciler costing the whole crossing's record.
    """
    store = await _planted(_belief("stale", _MORNING))
    reconciler = _Reporting({"stale": "contradicts"})

    await _writer(store, sink, reconciler=reconciler).ingest(_proposal(_belief("new", _AFTERNOON)))

    trace = _only(sink)
    assert trace.outcome is TraceOutcome.OK, "the crossing kept its trace"
    counts = _ten(trace)
    assert counts[traces.RELATION_METRICS[ConflictRelation.CONTRADICTS]] == 0
    assert counts[traces.RELATIONS_UNLABELLED] == 1
    assert counts[traces.RECONCILER_FAILED] == 1


async def test_one_non_member_value_discards_the_whole_mapping(sink: FakeTraceSink) -> None:
    """ADR-0164 §3's whole-mapping clause: partial trust is what would make it lie.

    A mapping carrying one valid ``ADDS`` beside one bare ``"contradicts"`` could
    install the valid label and count its proposal ``reconciler_failed`` — and then
    one trace would say a model label stood *and*, through the answered arithmetic,
    that no model rung answered on that proposal. Discarding it whole keeps both
    statements true, and it is the shape the guard already has: ``except Exception:
    return own`` discards the entire determination, not the member that failed.
    """
    store = await _planted(_belief("other", _AFTERNOON), _belief("fridays", _FRIDAYS))
    reconciler = _Reporting({"other": ConflictRelation.ADDS, "fridays": "contradicts"})
    writer = _writer(
        store, sink, reconciler=reconciler, policy=FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)
    )

    await writer.ingest(_proposal(_belief("new", _MORNING)))

    counts = _ten(_only(sink))
    assert counts[traces.RELATIONS_OFFERED] == 2
    assert counts[traces.RELATIONS_UNLABELLED] == 2, "neither installed"
    assert all(counts[key] == 0 for key in traces.RELATION_METRICS.values())
    assert counts[traces.RECONCILER_FAILED] == 1


async def test_a_beyond_bound_non_member_value_discards_the_within_bound_label_too(
    sink: FakeTraceSink,
) -> None:
    """The writer reads the resolved conflict set and holds no consulted set.

    On a conflict set longer than ``reconciler_max_conflicts`` a returned mapping
    pairing a valid label for a member **within** the bound with a non-member value
    for one **beyond** it installs neither. There is nothing here to except the
    second entry with: ``_relations_for`` ranges over ``conflicts`` and never over a
    consulted set, because it is not the layer that knows one — and a mapping still
    carrying such an entry is already the output of a reconciler ADR-0159 §3
    obliged to discard it before returning.

    What the writer should do with a **well-formed** beyond-bound label is ADR-0159's
    enforcement question; ADR-0164 §9 declines it and issue #1225 records it, so
    nothing here pins an answer to it.
    """
    store = await _planted(
        _belief("a", _MORNING),
        _belief("b", _FRIDAYS),
        _belief("c", _WINTER),
        _belief("d", _TEA),
    )
    bound = 3
    reconciler = _ByRank({0: ConflictRelation.ADDS, bound: "contradicts"})
    writer = _writer(
        store, sink, reconciler=reconciler, policy=FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)
    )

    result = await writer.ingest(_proposal(_belief("new", _AFTERNOON)))

    assert len(result.conflicts) > bound, "the set has to outrun the bound to make the point"
    counts = _ten(_only(sink))
    assert counts[traces.RELATIONS_UNLABELLED] == counts[traces.RELATIONS_OFFERED]
    assert all(counts[key] == 0 for key in traces.RELATION_METRICS.values())
    assert counts[traces.RECONCILER_FAILED] == 1


@pytest.mark.parametrize(
    "outcome",
    [ReconcilerOutcome.UNCONSULTED, ReconcilerOutcome.FAILED],
    ids=["unconsulted", "failed"],
)
async def test_a_report_claiming_less_than_its_labels_discards_them(
    outcome: ReconcilerOutcome, sink: FakeTraceSink
) -> None:
    """ADR-0164 §3's coherence clause: the two combinations that deny themselves.

    Without it a reconciler could report that it never asked and hand back labels
    anyway, and the two halves of one trace would contradict each other — leaving a
    reader no conclusion to draw from a positive contradiction count, which is the
    one conclusion this instrument exists to make drawable. The guard is
    deliberately one-directional: it catches a report that **under**claims beside
    labels that stand, and it cannot catch a reconciler reporting an answer it never
    obtained, which no writer-side check can.
    """
    store = await _planted(_belief("stale", _MORNING))
    reconciler = _Reporting({"stale": ConflictRelation.CONTRADICTS}, frozenset({outcome}))

    await _writer(store, sink, reconciler=reconciler).ingest(_proposal(_belief("new", _AFTERNOON)))

    counts = _ten(_only(sink))
    assert counts[traces.RELATION_METRICS[ConflictRelation.CONTRADICTS]] == 0
    assert counts[traces.RELATIONS_UNLABELLED] == 1
    assert counts[traces.RECONCILER_FAILED] == 1
    assert counts[traces.RECONCILER_UNCONSULTED] == 0


def _mappings() -> dict[str, object]:
    """Every mapping shape a non-conforming report may arrive beside.

    ADR-0164 §7 states the report rule as a **rule** rather than a list of cells, so
    the cases below are its cross product with the report shapes: an empty mapping,
    a well-formed one, one carrying a non-member value, and one of the shapes the
    writer's guard already absorbs. A report shape paired with a mapping shape named
    nowhere is covered by the same rule and needs no case of its own.

    The empty one is not padding: "nothing installs" is vacuous where there is
    nothing to install, and ``reconciler_failed`` at one is then the only observable
    an implementation that validated the report only when labels were present would
    fail.

    Returns:
        The mapping shapes, by id.
    """
    return {
        "empty-mapping": {},
        "valid-label": {"other": ConflictRelation.ADDS},
        "non-member-value": {"other": "adds"},
        "hostile-mapping": _Hostile(),
    }


@pytest.mark.parametrize("labels", _mappings().values(), ids=_mappings().keys())
@pytest.mark.parametrize(
    "outcomes",
    [
        None,
        frozenset(),
        frozenset({"answered"}),
        frozenset({ReconcilerOutcome.ANSWERED, ReconcilerOutcome.UNCONSULTED}),
    ],
    ids=["missing", "names-none", "names-a-non-outcome", "names-more-than-one"],
)
async def test_a_report_naming_other_than_exactly_one_outcome_fails_in_whole(
    outcomes: frozenset[object] | None, labels: object, sink: FakeTraceSink
) -> None:
    """ADR-0164 §3 and §7 as one rule, over every shape a report can arrive in.

    A report from a reconciler that **ran** names exactly one of its three outcomes.
    One that is missing where one was due, names none of them, or names more than
    one is non-conforming *in whole*: the mapping it accompanies installs nothing,
    every member it would have labelled stays unlabelled, and the proposal counts
    under ``reconciler_failed``. A report naming more than one is no more usable for
    carrying a valid outcome among them, because nothing says which of them to read
    — and that is what stops two implementations reporting one unusable report
    differently.

    The certain rung's labels survive all of it, which is the property that keeps
    ADR-0159 §6's floor intact: they never depended on a reconciler.
    """
    store = await _planted(_belief("same", _MORNING), _belief("other", _AFTERNOON))
    # ``None`` is the report **missing** where one was due, which no report object
    # can express: the double carries the relations and nothing beside them.
    reconciler: object = (
        _NoReport(labels)  # type: ignore[arg-type]  # deliberately non-conforming
        if outcomes is None
        else _Reporting(labels, outcomes)  # type: ignore[arg-type]
    )

    await _writer(store, sink, reconciler=reconciler).ingest(_proposal(_belief("new", _MORNING)))

    counts = _ten(_only(sink))
    assert counts[traces.RECONCILER_FAILED] == 1
    assert all(counts[key] == 0 for key in traces.RELATION_METRICS.values())
    assert counts[traces.RELATIONS_CERTAIN_RESTATES] == 1, "the certain rung is retained"
    assert counts[traces.RELATIONS_UNLABELLED] == 1, "the remaining offered pair is unlabelled"
    assert counts[traces.RELATIONS_OFFERED] == 2


@pytest.mark.parametrize(
    "answer",
    [
        None,
        "not a mapping",
        42,
        ReconcilerReport(relations=_Hostile(), outcomes=frozenset({ReconcilerOutcome.ANSWERED})),
    ],
    ids=["none", "a-string", "an-int", "a-mapping-that-will-not-be-read"],
)
async def test_the_shapes_the_guard_already_absorbs_are_counted_as_failed(
    answer: object, sink: FakeTraceSink
) -> None:
    """The three **non-raising** shapes, which are where today's silent fallback lives.

    ADR-0164 §7 names them because an implementation could keep the existing
    ``return own`` on each and still pass every other case here: the ingest degrades
    correctly and nothing is counted at all. A reconciler that *returns* something
    unusable is as non-conforming as one that raises (ADR-0159 §3), so it counts the
    same, and the ingest is refused on none of them (§6).
    """
    store = await _planted(_belief("same", _MORNING), _belief("other", _AFTERNOON))

    result = await _writer(store, sink, reconciler=_Returning(answer)).ingest(
        _proposal(_belief("new", _MORNING))
    )

    assert result.decision.kind is not MemoryDecisionKind.REJECT, "no ingest is refused (§6)"
    counts = _ten(_only(sink))
    assert counts[traces.RECONCILER_FAILED] == 1
    assert counts[traces.RELATIONS_CERTAIN_RESTATES] == 1
    assert counts[traces.RELATIONS_UNLABELLED] == 1


# --- where the ten are present, and where they are absent ---------------------


async def test_a_proposal_the_invocation_condition_excludes_contributes_zero_to_the_ten(
    sink: FakeTraceSink,
) -> None:
    """ADR-0159 §2's condition excluded it, so nothing was determined about it.

    ``proposals`` still counts it, and the complement of ``reconciled`` is therefore
    already on the trace — which is why ADR-0164 §3 emits no key for a difference of
    two the trace carries. A ``USER_ASSERTED`` proposal is ADR-0121 §2's arm: no
    relation is computed, no request is made, and ``decide`` is called with ``None``.
    """
    store = await _planted(_belief("same", _MORNING))
    reconciler = _Reporting({"same": ConflictRelation.ADDS})

    await _writer(store, sink, reconciler=reconciler).ingest(
        _proposal(_belief("new", _MORNING, source=MemorySource.USER_ASSERTED))
    )

    trace = _only(sink)
    assert trace.metrics[traces.PROPOSALS] == 1
    assert reconciler.calls == 0
    assert _ten(trace) == dict.fromkeys(traces.RECONCILIATION_METRICS, 0)


async def test_a_crossing_that_reconciled_nothing_emits_ten_zeros_and_not_ten_absences(
    sink: FakeTraceSink,
) -> None:
    """ADR-0119 §3 read in the direction the emitter can get wrong.

    §3's substitution is available both ways. A crossing whose proposals ADR-0159 §2
    all excluded **did** evaluate the invocation condition, on every proposal, and
    found none admitted; ``reconciled = 0`` is that finding. Making the ten absent
    here would record it identically to a crossing that faulted before any reading
    was taken — and "the reconciler was never reached" and "the trace never got that
    far" call for opposite responses.

    The six ``decisions_*`` keys are the anchor: the ten are present on exactly the
    crossings they are present on, so the two sets are asserted together.
    """
    store = await _planted()
    reading = SourceReading(
        source=_SOURCE,
        read_at=_fixed_now(),
        proposals=(
            _proposal(_belief("one", _MORNING, source=MemorySource.USER_ASSERTED)),
            _proposal(_belief("two", _AFTERNOON, source=MemorySource.USER_ASSERTED)),
        ),
        coverage=None,
    )

    await _writer(store, sink).ingest_reading(reading)

    trace = _only(sink)
    assert trace.metrics[traces.PROPOSALS] == 2
    assert all(key in trace.metrics for key in traces.DECISION_METRICS.values())
    assert _ten(trace) == dict.fromkeys(traces.RECONCILIATION_METRICS, 0)


async def test_a_reading_that_refuses_half_way_files_the_first_proposals_relation_keys(
    sink: FakeTraceSink,
) -> None:
    """§3 binds the ten to the observation the six ``decisions_*`` keys ride.

    ADR-0115 §3 leaves the proposals ingested before a raise applied, and ADR-0119
    §5's partial reading is what stops the trace denying them. The relation keys
    have to travel on that same reading: a fault path carrying the decision counts
    of a proposal whose reconciliation it then reported as unobserved would split one
    observation across two answers.
    """
    store = await _planted(_belief("stale", _MORNING))
    reconciler = _Reporting({"stale": ConflictRelation.CONTRADICTS})
    unwarranted = SemanticMemory(
        id="derived",
        content="a conclusion drawn from nothing",
        fact="a conclusion drawn from nothing",
        provenance=Provenance(
            source=MemorySource.INFERRED,
            confidence=0.6,
            last_updated=_WHEN,
            evidence=("missing",),
        ),
    )
    reading = SourceReading(
        source=_SOURCE,
        read_at=_fixed_now(),
        proposals=(_proposal(_belief("new", _AFTERNOON)), _proposal(unwarranted)),
        coverage=None,
    )
    writer = _writer(
        store, sink, reconciler=reconciler, policy=FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)
    )

    with pytest.raises(UnresolvedEvidenceError):
        await writer.ingest_reading(reading)

    trace = _only(sink)
    assert trace.outcome is TraceOutcome.REFUSED
    assert trace.metrics[traces.PROPOSALS] == 2
    assert trace.metrics["decisions_accept"] == 1
    counts = _ten(trace)
    assert counts[traces.RECONCILED] == 1
    assert counts[traces.RELATION_METRICS[ConflictRelation.CONTRADICTS]] == 1
    assert counts[traces.RELATIONS_OFFERED] == 1


async def test_a_crossing_that_took_no_reading_carries_none_of_the_ten(
    sink: FakeTraceSink,
) -> None:
    """The other side of §3's presence rule, and the distinction it protects.

    A bare ``ingest`` that raises leaves no reading at all — the entry quantities
    are the whole of its fault path — so the ten are **absent**, exactly as the six
    ``decisions_*`` keys are. That is what makes the ten zeros above mean "the
    condition was evaluated and admitted nothing" rather than "the trace never got
    that far".
    """
    store = await _planted()
    unwarranted = SemanticMemory(
        id="derived",
        content="a conclusion drawn from nothing",
        fact="a conclusion drawn from nothing",
        provenance=Provenance(
            source=MemorySource.INFERRED,
            confidence=0.6,
            last_updated=_WHEN,
            evidence=("missing",),
        ),
    )

    with pytest.raises(UnresolvedEvidenceError):
        await _writer(store, sink).ingest(_proposal(unwarranted))

    trace = _only(sink)
    assert trace.metrics[traces.PROPOSALS] == 1
    assert not [key for key in traces.RECONCILIATION_METRICS if key in trace.metrics]
    assert not [key for key in traces.DECISION_METRICS.values() if key in trace.metrics]
