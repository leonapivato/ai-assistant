"""Tests for ADR-0159's conflict reconciler.

What ``ModelBackedReconciler`` owes is five clauses of ADR-0159 §3 — the certain
first rung, the spend condition, the bound in **both** directions, one request per
call, and never raising — plus ADR-0060 §1's cancellation exception. Every one of
them is observable against a recording double and none is observable from a
ruling, which is why they are pinned here rather than through the write path.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import (
    ConflictRelation,
    MemorySource,
    MemoryUpdateProposal,
    Message,
    Provenance,
    SemanticMemory,
)
from ai_assistant.memory._reconciler import ModelBackedReconciler
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryRecord

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_ROUTE = "anthropic:claude-x"


def _record(record_id: str, content: str | None = None) -> MemoryRecord:
    text = record_id if content is None else content
    return SemanticMemory(
        id=record_id,
        content=text,
        fact=text,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.6,
            last_updated=_WHEN,
            evidence=("episode-1",),
        ),
    )


def _proposal(record: MemoryRecord) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="because")


def _reply(**labels: str) -> str:
    return json.dumps(
        {"relations": [{"id": rid, "relation": value} for rid, value in labels.items()]}
    )


def _answering(labels: dict[str, str]) -> FakeModelProvider:
    """A provider that labels whatever it is asked about, plus ``labels``' extras."""

    def reply(_messages: Sequence[Message]) -> str:
        return _reply(**labels)

    return FakeModelProvider(reply=reply)


async def test_the_agrees_rung_labels_restates_with_no_model_call() -> None:
    """ADR-0159 §3's first clause, and the spend condition's other half.

    ADR-0121 §1's predicate *is* a reconciler answer, and it is the rung that makes
    the model's contribution additive: a verbatim restatement is certain, so it
    costs nothing and the model is never asked about it.
    """
    model = FakeModelProvider()
    reconciler = ModelBackedReconciler(model=model, route=_ROUTE)
    identical = _record("identical", "I prefer window seats")

    relations = await reconciler.reconcile(
        _proposal(_record("new", "I  PREFER   Window Seats ")), [identical]
    )

    assert relations == {"identical": ConflictRelation.RESTATES}
    assert model.call_count == 0


async def test_one_request_covers_every_member_it_consults_about() -> None:
    """ADR-0159 §3: at most one request per call, not one per member.

    Not only cost. A relation is a statement about a pair, but the *set* is what
    disambiguates it — shown three records together a labeller can see that two are
    a sequence and the third is the claim being restated. It is also what makes §6's
    latency statement a statement: one request under one deadline.
    """
    model = _answering({"a": "adds", "b": "contradicts", "c": "adds"})
    reconciler = ModelBackedReconciler(model=model, route=_ROUTE, max_conflicts=3)
    conflicts = [_record("a"), _record("b"), _record("c")]

    relations = await reconciler.reconcile(_proposal(_record("new")), conflicts)

    assert model.call_count == 1
    assert relations == {
        "a": ConflictRelation.ADDS,
        "b": ConflictRelation.CONTRADICTS,
        "c": ConflictRelation.ADDS,
    }


async def test_the_route_is_named_on_every_request() -> None:
    """ADR-0159 §3: a reconciler names the route it calls rather than inheriting it."""
    model = _answering({"a": "adds"})

    await ModelBackedReconciler(model=model, route=_ROUTE).reconcile(
        _proposal(_record("new")), [_record("a")]
    )

    assert model.calls[0].model == _ROUTE


async def test_only_kind_and_content_reach_the_prompt() -> None:
    """ADR-0159 §1: a relation is a property of those two and of nothing else.

    A retrieval score, a rank, a `Provenance` field, a band or a validity window in
    the prompt would be an invitation to derive a relation from something that
    cannot support one. The record's id is there because the reply has to name what
    it is answering about — and it is what the bound's response half is tested on.
    """
    model = _answering({"a": "adds"})
    conflict = _record("a", "Jon lost his job shortly before 21 June 2023")

    await ModelBackedReconciler(model=model, route=_ROUTE).reconcile(
        _proposal(_record("new", "Jon took a temporary job around mid-July 2023")), [conflict]
    )

    sent = "\n".join(m.content for m in model.calls[0].messages)
    assert conflict.content in sent
    assert "0.6" not in sent  # the confidence
    assert "episode-1" not in sent  # the evidence


async def test_the_request_covers_no_member_beyond_the_bound() -> None:
    """ADR-0159 §3's bound, in rank order and on the request side."""
    model = _answering({"a": "adds"})
    conflicts = [_record("a"), _record("b"), _record("c"), _record("beyond")]

    await ModelBackedReconciler(model=model, route=_ROUTE, max_conflicts=3).reconcile(
        _proposal(_record("new")), conflicts
    )

    sent = "\n".join(m.content for m in model.calls[0].messages)
    assert "beyond" not in sent
    assert sent.count("STORED BELIEF") == 3


async def test_a_volunteered_label_for_a_beyond_bound_member_is_discarded() -> None:
    """The bound's **response** half, which a test reading only the request cannot see.

    ADR-0159 §3 names this as the half a test forgets. Asking about three members
    does not stop a reply naming a fourth, and the fourth's id is a *valid* id — it
    is in the conflict set — so §8's ignore rule, stated over ids absent from
    `conflicts`, does not reach it. Installed, a volunteered `CONTRADICTS` would
    block a fold §4(a) would otherwise make: the bound failing in the one direction
    it exists to prevent.
    """
    model = _answering({"a": "restates", "beyond": "contradicts"})
    conflicts = [_record("a"), _record("b"), _record("c"), _record("beyond")]

    relations = await ModelBackedReconciler(model=model, route=_ROUTE, max_conflicts=3).reconcile(
        _proposal(_record("new")), conflicts
    )

    assert "beyond" not in relations
    assert relations == {"a": ConflictRelation.RESTATES}


async def test_a_label_for_a_member_the_rung_already_settled_is_discarded() -> None:
    """ADR-0159 §3: a model-supplied label reaches only a member consulted about.

    The certain rung is unconditional and the model can never overturn it, so a
    reply volunteering a relation for a record it was not shown changes nothing.
    """
    model = _answering({"identical": "contradicts", "other": "adds"})
    identical = _record("identical", "I prefer window seats")
    proposal = _proposal(_record("new", "I prefer window seats"))

    relations = await ModelBackedReconciler(model=model, route=_ROUTE).reconcile(
        proposal, [identical, _record("other")]
    )

    assert relations["identical"] is ConflictRelation.RESTATES
    assert relations["other"] is ConflictRelation.ADDS
    assert (
        "identical"
        not in "\n".join(m.content for m in model.calls[0].messages).split("STORED BELIEF")[1]
    )


async def test_a_label_naming_no_member_at_all_is_discarded() -> None:
    model = _answering({"ghost": "contradicts"})

    relations = await ModelBackedReconciler(model=model, route=_ROUTE).reconcile(
        _proposal(_record("new")), [_record("a")]
    )

    assert relations == {}


async def test_no_request_is_made_where_the_rung_settled_everything() -> None:
    """ADR-0159 §3: none where the rung labelled every member it would have asked about."""
    model = FakeModelProvider()
    same = "I prefer window seats"

    relations = await ModelBackedReconciler(model=model, route=_ROUTE).reconcile(
        _proposal(_record("new", same)), [_record("a", same), _record("b", same)]
    )

    assert model.call_count == 0
    assert set(relations) == {"a", "b"}


async def test_no_request_is_made_for_an_empty_conflict_set() -> None:
    model = FakeModelProvider()

    relations = await ModelBackedReconciler(model=model, route=_ROUTE).reconcile(
        _proposal(_record("new")), []
    )

    assert model.call_count == 0
    assert relations == {}


class _RaisingProvider:
    """A provider whose every call fails the way a dead route does."""

    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.calls = 0

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        """Fail, counting the attempt."""
        self.calls += 1
        raise self._error


@pytest.mark.parametrize(
    "error",
    [ModelError("the route is down"), TimeoutError("deadline"), RuntimeError("something else")],
    ids=["model-error", "self-issued-deadline", "unexpected"],
)
async def test_a_failed_request_yields_unlabelled_and_never_raises(error: Exception) -> None:
    """ADR-0159 §3's never-raises clause, over every failure it names.

    A model error, a timeout, an unreadable reply, an unroutable request — each
    yields unlabelled for every member it could not label, and the write proceeds on
    the relations the reconciler does hold. The timeout case is ADR-0060 §1's
    self-issued kind, which `models/` raises against its **own** deadline and which
    this clause classifies like any other failure.
    """
    identical = _record("identical", "I prefer window seats")
    conflicts = [identical, _record("other")]

    relations = await ModelBackedReconciler(model=_RaisingProvider(error), route=_ROUTE).reconcile(
        _proposal(_record("new", "I prefer window seats")), conflicts
    )

    assert relations == {"identical": ConflictRelation.RESTATES}


async def test_a_cancellation_from_outside_is_delivered_onward() -> None:
    """ADR-0060 §1's second clause, which ADR-0159 §3 excepts from never-raises.

    A `CancelledError` delivered from outside is never converted into an unlabelled
    member and never allowed to stand as a completed answer. It holds by
    construction — the guard is stated over `Exception` and a `CancelledError` is a
    `BaseException` — and that is exactly the property a later "tidy up the bare
    except" would break.
    """
    reconciler = ModelBackedReconciler(
        model=_RaisingProvider(asyncio.CancelledError()), route=_ROUTE
    )

    with pytest.raises(asyncio.CancelledError):
        await reconciler.reconcile(_proposal(_record("new")), [_record("a")])


@pytest.mark.parametrize(
    "content",
    [
        "I cannot help with that.",
        '{"relations": "not a list"}',
        '{"beliefs": []}',
        '{"relations": [{"id": "a", "relation": "sort-of"}]}',
        '{"relations": [["a", "adds"]]}',
        "",
    ],
    ids=["prose", "wrong-shape", "wrong-envelope", "unknown-relation", "not-objects", "empty"],
)
async def test_an_unreadable_reply_leaves_every_member_unlabelled(content: str) -> None:
    relations = await ModelBackedReconciler(
        model=FakeModelProvider(reply=content), route=_ROUTE
    ).reconcile(_proposal(_record("new")), [_record("a")])

    assert relations == {}


async def test_an_envelope_wrapped_in_prose_and_a_fence_is_still_read() -> None:
    """ADR-0071's scan: a model that wraps the object is tolerated, a decoy stepped over."""
    wrapped = 'Here you go {"note": "ignore me"} ```json\n' + _reply(a="adds") + "\n``` done"

    relations = await ModelBackedReconciler(
        model=FakeModelProvider(reply=wrapped), route=_ROUTE
    ).reconcile(_proposal(_record("new")), [_record("a")])

    assert relations == {"a": ConflictRelation.ADDS}


async def test_a_repeated_entry_takes_the_first_answer() -> None:
    """A reply naming one member twice is malformed, and the later entry never wins.

    Taking it would let a trailing `contradicts` overwrite an earlier `adds` — the
    one direction that destroys a record.
    """
    doubled = json.dumps(
        {
            "relations": [
                {"id": "a", "relation": "adds"},
                {"id": "a", "relation": "contradicts"},
            ]
        }
    )

    relations = await ModelBackedReconciler(
        model=FakeModelProvider(reply=doubled), route=_ROUTE
    ).reconcile(_proposal(_record("new")), [_record("a")])

    assert relations == {"a": ConflictRelation.ADDS}


@pytest.mark.parametrize("bound", [0, -1])
def test_a_non_positive_bound_is_refused_at_construction(bound: int) -> None:
    """ADR-0022 §4a: a bound the caller got wrong fails where it was set."""
    with pytest.raises(ValueError, match="at least 1"):
        ModelBackedReconciler(model=FakeModelProvider(), route=_ROUTE, max_conflicts=bound)


def test_a_boolean_bound_is_refused_at_construction() -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        ModelBackedReconciler(model=FakeModelProvider(), route=_ROUTE, max_conflicts=True)


def test_a_blank_route_is_refused_at_construction() -> None:
    """A reconciler *names* its route (ADR-0159 §3), so a blank one is not one."""
    with pytest.raises(ValueError, match="provider:model"):
        ModelBackedReconciler(model=FakeModelProvider(), route="  ")
