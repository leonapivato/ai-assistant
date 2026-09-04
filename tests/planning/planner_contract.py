"""Shared conformance suite for the Planner Protocol (ADR-0014).

Every ``Planner`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`PlannerContract` and
overrides the ``planner`` fixture.

The contract is deliberately thin: *what* a planner decides is its own business
and cannot be asserted generically. What every planner owes its caller is a plan
that belongs to the goal it was asked about and is safe to treat as an audit
record — which is what this pins down.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    MAX_HOP_LABELS,
    CurrentContext,
    EpisodicMemory,
    Goal,
    MemorySource,
    Provenance,
    ReadKind,
    ReadRequest,
    ShownFile,
    TimeOfDay,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import Planner

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: A vocabulary to drive the contract over — two plausible advertised names.
#:
#: The contents decide nothing, and that is the point: ADR-0211 §9 item 2 forbids
#: this suite asserting *which* envelope an implementation returns for a goal, so
#: nothing below reads these names back. What is pinned is that a conforming
#: planner **accepts** the input the contract now requires.
_VOCABULARY = ("report_current_time", "send_email")


def _goal(goal_id: str = "g1") -> Goal:
    return Goal(
        id=goal_id,
        statement="relocate to Lisbon",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN
        ),
        created_at=_WHEN,
    )


def _context() -> CurrentContext:
    return CurrentContext(
        now=_WHEN,
        time_of_day=TimeOfDay.MORNING,
        is_weekend=False,
        within_working_hours=True,
    )


def _supply() -> tuple[EpisodicMemory, ...]:
    """A two-record supply, so a call has positions for ADR-0226 §3 to label.

    Episodes rather than beliefs so that the sequence is the shape ADR-0074 §5 puts
    first — a conversation tail — and every planner renders it the same way. What
    it holds decides nothing here: the suite never asserts what a planner asks
    about it, only what the shape of an ask may be.
    """
    return tuple(
        EpisodicMemory(
            id=f"e{ordinal}",
            content=f"Ada: turn {ordinal}.",
            occurred_at=_WHEN,
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_WHEN),
        )
        for ordinal in (1, 2)
    )


def _fourth_group() -> tuple[EpisodicMemory, ...]:
    """What a servicing appended, as a turn's **second** call is handed it.

    ADR-0228 §7: one fourth group, appended whole after the episodic supplement and
    never interleaved, holding the records **every** servicing of the turn returned in
    servicing order. What it holds decides nothing here — this suite asserts that a
    conforming planner accepts the widened input, not what it makes of it.
    """
    return tuple(
        EpisodicMemory(
            id=f"serviced-{ordinal}",
            content=f"Ada: the read returned {ordinal}.",
            occurred_at=_WHEN,
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.8, last_updated=_WHEN),
        )
        for ordinal in (1, 2)
    )


def _listing() -> tuple[ShownFile, ...]:
    """A three-entry listing, so a call has positions for ADR-0230 §2 to label.

    "Most recently modified first" is the fetcher's ordering (§6) and this sequence
    is written in it; nothing here asserts the order, because what a planner owes is
    to take the sequence **as handed** and derive its labels from position, not to
    have an opinion about how it was sorted. What the entries hold decides nothing:
    this suite asserts that a conforming planner accepts the widened input and that
    an ``entry`` it emits is an ordinal into it, never what it makes of a file.
    """
    return tuple(
        ShownFile(
            name=name,
            size_bytes=size,
            modified_at=datetime(2026, 1, 1, 12 - ordinal, tzinfo=UTC),
        )
        for ordinal, (name, size) in enumerate(
            (("quarterly-review.pdf", 4096), ("notes.md", 12), ("roster.txt", 300))
        )
    )


class PlannerContract:
    """Behaviour every ``Planner`` implementation must exhibit."""

    @pytest.fixture
    def planner(self) -> Planner:
        """Return the planner under test."""
        raise NotImplementedError

    async def test_plans_for_the_goal_it_was_given(self, planner: Planner) -> None:
        """A plan that does not name its goal cannot be resumed or audited."""
        plan = await planner.plan(_goal(), context=_context(), capabilities=_VOCABULARY)
        assert plan.goal_id == "g1"

    async def test_step_ids_are_unique(self, planner: Planner) -> None:
        plan = await planner.plan(_goal(), context=_context(), capabilities=_VOCABULARY)
        ids = [step.id for step in plan.steps]
        assert len(ids) == len(set(ids))

    async def test_the_returned_plan_is_frozen(self, planner: Planner) -> None:
        """The plan is an audit record, so it must not be editable after the fact."""
        plan = await planner.plan(_goal(), context=_context(), capabilities=_VOCABULARY)
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            plan.goal_id = "tampered"

    async def test_accepts_the_memories_the_pipeline_assembled(self, planner: Planner) -> None:
        """Memory is passed in, not fetched — it is what makes a plan personal.

        ``memories`` is **what the pipeline assembled for this turn**, which
        ADR-0074 §5 widened from "records retrieved as relevant, best first": the
        conversation's recent turns come first, in order, then the
        relevance-retrieved records, then — since ADR-0158 §5 — the episodic
        supplement. The signature did not change, so no triad is owed — but this
        suite's expectation moves with the wording, which is the review concern
        ``CONTRIBUTING.md`` names when a Protocol's meaning changes without its
        shape. What a conforming planner may **not** do is read a single relevance
        order across the sequence: for a user who changes the subject
        mid-conversation, the tail is not the most relevant thing the store holds,
        and the retrieved group is composed under the assembling consumer's
        precedence (ADR-0072 §5, ADR-0113 §6), relevance ordering the records only
        within one precedence band.
        """
        plan = await planner.plan(
            _goal(), context=_context(), memories=(), capabilities=_VOCABULARY
        )
        assert plan.goal_id == "g1"

    async def test_accepts_the_advertised_vocabulary(self, planner: Planner) -> None:
        """The vocabulary is pushed in, and a conforming planner takes it.

        ADR-0211 §1 makes ``capabilities`` a required, keyword-only input carrying
        what ``ToolRegistry.capabilities()`` answered for this turn — an open string
        vocabulary of which the registry is the authority (ADR-0016 §5). A planner
        neither re-derives it, nor fetches it, nor holds a registry, for the reason
        ADR-0014 §6 pushes ``context`` and ``memories`` in rather than letting a
        planner reach for them.

        **What is asserted is acceptance, and deliberately nothing more.** ADR-0211
        §9 item 2 forbids this suite asserting which envelope a given implementation
        returns for a given goal: the fake's plan is scripted and a model's is not,
        so an assertion that a vocabulary of two produces a plan would pass on one
        conforming implementation and fail on another. The behavioural question — is
        the goal one this vocabulary can carry? — is a model's judgement, which
        ADR-0211 §6's third clause declines to guarantee of any planner.
        """
        plan = await planner.plan(_goal(), context=_context(), capabilities=_VOCABULARY)
        assert plan.goal_id == "g1"

    async def test_an_empty_vocabulary_raises_nothing(self, planner: Planner) -> None:
        """The empty vocabulary is a legal input, never an error (ADR-0211 §6).

        A deployment with no builtin and no integration reaches it, and every fake
        and every case here exercises it, which is why it is ruled rather than left
        to an implementation's judgement. A conforming planner raises nothing,
        refuses nothing and enters no repair round on account of it: what an empty
        vocabulary means is that no step can be carried, so a decline is the only
        shape available — and *that* is an obligation on what the planner asks for,
        not a guarantee about what comes back, so it is not asserted here.
        """
        plan = await planner.plan(_goal(), context=_context(), capabilities=())
        assert plan.goal_id == "g1"

    async def test_the_vocabulary_need_not_be_a_tuple(self, planner: Planner) -> None:
        """``Sequence[str]`` is the contract, and a list satisfies it.

        ``ToolRegistry.capabilities()`` answers a tuple today, so an implementation
        could pass its whole test suite while quietly requiring one — indexing is
        common to both, and so is iteration, but ``isinstance(value, tuple)`` and
        equality against a tuple literal are not. A caller assembling the vocabulary
        by other means, or a fake handing over a list, would then fail against a
        planner that looked conforming. Pinned here rather than left to a reviewer's
        eye, because the divergence is invisible until the first caller hits it.
        """
        plan = await planner.plan(_goal(), context=_context(), capabilities=list(_VOCABULARY))
        assert plan.goal_id == "g1"

    # --- ADR-0226 §4: the widened return -----------------------------------
    # `Planner.plan` may now answer a plan carrying a `read_request`. §10 obliges
    # this suite to cover that widening, "so that every `Planner` implementation is
    # held to it — the model-backed planner and the canonical fake alike".

    @pytest.fixture
    def asking_planner(self) -> Planner | None:
        """The same implementation, arranged to emit a read request — or ``None``.

        **Optional by construction, because ADR-0226 §4 makes the field additive
        and defaulted.** A ``Planner`` that knows nothing of the envelope conforms
        and returns no request on any turn, so a suite that *required* every
        implementation to produce one would refuse a conforming planner. A subclass
        that can arrange an emission overrides this and the arms below bind on it;
        one that cannot leaves it, and they skip.

        Returns:
            A planner of the implementation under test that asks for a read, or
            ``None`` where the implementation never asks.
        """
        return None

    async def test_the_plan_says_whether_a_read_was_asked_for(self, planner: Planner) -> None:
        """The widened return, at its weakest and most total form (ADR-0226 §4).

        Whatever a planner decides, ``read_request`` is either ``None`` — "the
        planner asked for no read", which §4 makes the semantically correct answer
        and never an error — or a validated
        :class:`~ai_assistant.core.types.ReadRequest`. *Which* of the two is a
        judgement this suite may not assert, for ADR-0211 §9 item 2's reason: a
        scripted plan and a model's plan would answer differently for one goal and
        both would conform.
        """
        plan = await planner.plan(
            _goal(), context=_context(), memories=_supply(), capabilities=_VOCABULARY
        )
        assert plan.read_request is None or isinstance(plan.read_request, ReadRequest)

    async def test_a_request_it_returns_is_one_this_contract_admits(
        self, asking_planner: Planner | None
    ) -> None:
        """An emitted request is a *validated* model, arm by arm (ADR-0226 §§1-2, §6).

        Every condition here is one ``ReadRequest`` and ``ReadAsk`` enforce, which
        is the point: a planner can bypass them — ``model_construct`` skips
        validation, and an implementation assembling a request by hand could ship a
        two-ask ``SIGHTED_QUERY`` request or a three-label hop that no ``core`` test
        would ever see. Re-asserted here over what a planner actually returned, the
        conditions bind on the emission rather than only on the type.
        """
        if asking_planner is None:
            pytest.skip("this implementation never asks for a read (ADR-0226 §4)")
        plan = await asking_planner.plan(
            _goal(), context=_context(), memories=_supply(), capabilities=_VOCABULARY
        )
        request = plan.read_request
        assert request is not None, "the fixture promises an implementation that asks"

        kinds = [ask.kind for ask in request.asks]
        assert kinds, "a request carries at least one ask"
        assert len(set(kinds)) == len(kinds), "at most one ask of each kind"
        for ask in request.asks:
            assert ask.kind in set(ReadKind)
            if ask.kind is ReadKind.SIGHTED_QUERY:
                assert ask.query is not None
                assert ask.query.strip()
                assert ask.labels == ()
                assert ask.entry is None
            elif ask.kind is ReadKind.CITATION_HOP:
                assert ask.query is None
                assert 1 <= len(ask.labels) <= MAX_HOP_LABELS
                assert ask.entry is None
            else:
                # ADR-0230 §1: "one entry label and nothing else" — one file, never
                # two, and no argument belonging to another kind.
                assert ask.kind is ReadKind.LOCAL_FILE
                assert ask.entry is not None
                assert ask.entry.strip()
                assert ask.query is None
                assert ask.labels == ()

    async def test_a_request_it_returns_cannot_be_edited(
        self, asking_planner: Planner | None
    ) -> None:
        """ADR-0226 §11 item 15's first arm: a plan carrying a request is still frozen.

        The plan is an audit record (ADR-0014 §2) and the request is now part of
        what it records, so the freeze has to reach all the way down — the field on
        the plan, the request, and each ask. A frozen plan holding a mutable request
        would let a later stage rewrite what the planner asked for, after the
        decision it is a record of.
        """
        if asking_planner is None:
            pytest.skip("this implementation never asks for a read (ADR-0226 §4)")
        plan = await asking_planner.plan(
            _goal(), context=_context(), memories=_supply(), capabilities=_VOCABULARY
        )
        request = plan.read_request
        assert request is not None

        frozen = (ValidationError, AttributeError, TypeError)
        with pytest.raises(frozen):
            plan.read_request = None
        with pytest.raises(frozen):
            request.asks = ()
        with pytest.raises(frozen):
            request.asks[0].kind = ReadKind.SIGHTED_QUERY

    # --- ADR-0228 §§1, 7, 12: the widened input --------------------------------
    # §12 obliges this suite to cover the widening "so that every `Planner`
    # implementation is held to it through the `Test…Contract` subclasses that already
    # run it — a planner handed four groups plans over them and emits under the same
    # rules". This is the obligation ADR-0226 §10 put on its own lane for its own
    # widening, taken here for the same reason.

    async def test_it_plans_over_a_fourth_group(self, planner: Planner) -> None:
        """A turn's **second** call carries four groups, and a planner takes them.

        ADR-0228 §7 partially supersedes ADR-0226 §7's three-group restatement and
        ADR-0158 §5's clause behind it: on a turn that serviced a read, the loop may
        call the planner again over "the three groups the first call saw and the
        fourth group the servicing appended". The fourth group is appended whole after
        the episodic supplement and is never interleaved, so a planner that renders
        whatever sequence it is handed conforms exactly as it does today — which is
        what makes the widening break nothing.

        **What is asserted is acceptance**, for ADR-0211 §9 item 2's reason: which
        envelope an implementation returns for a goal is a judgement this suite may
        not assert, and a scripted plan and a model's plan would answer differently.
        """
        plan = await planner.plan(
            _goal(),
            context=_context(),
            memories=_supply() + _fourth_group(),
            capabilities=_VOCABULARY,
        )
        assert plan.goal_id == "g1"

    async def test_a_turn_may_put_two_requests_to_one_planner(self, planner: Planner) -> None:
        """§3's bound is two calls, so a planner may be asked twice on one turn.

        ADR-0228 §3 supersedes ADR-0226 §2's second-emission clause, which this
        contract's own docstring carried as "never a second request on the same turn".
        Each call is an ordinary call: the planner is **not told which iteration it is
        on** (§12), so the second is made exactly as the first is and this suite
        passes no signal that it is one.

        **And each plan is its own record.** ADR-0014 §2's "re-planning produces a
        *new* ``ActionPlan`` with a new ``id``" binds within a turn once a turn may
        plan twice, so two calls of one turn do not answer one id — which
        ``PlanStore.save_plan`` refuses outright, since ADR-0228 §5 rejects a
        ``supersedes`` naming the saving plan's own ``id``.
        """
        first = await planner.plan(
            _goal(), context=_context(), memories=_supply(), capabilities=_VOCABULARY
        )
        second = await planner.plan(
            _goal(),
            context=_context(),
            memories=_supply() + _fourth_group(),
            capabilities=_VOCABULARY,
        )
        assert first.goal_id == second.goal_id == "g1"
        assert first.id != second.id, "a turn's two plans are two records"

    async def test_a_label_indexes_the_sequence_passed_on_that_call(
        self, asking_planner: Planner | None
    ) -> None:
        """§8: ADR-0226 §3's scheme binds each call separately and as written.

        "The label of the record at 1-based index *n* of the ``memories`` sequence
        passed on **that call** is ``M`` followed by *n*." A planner emits over the
        sequence it was handed and never over a sequence from an earlier call, so a
        label it names on a call handed a fourth group is still an ordinal into
        **that** call's sequence — within range where it names a record at all.

        A label outside the shown set resolves to nothing and is discarded silently
        by the loop (ADR-0226 §3), so what a planner owes is the *form* and the
        origin, not a guarantee that every label lands.
        """
        if asking_planner is None:
            pytest.skip("this implementation never asks for a read (ADR-0226 §4)")
        supply = _supply() + _fourth_group()
        plan = await asking_planner.plan(
            _goal(), context=_context(), memories=supply, capabilities=_VOCABULARY
        )
        request = plan.read_request
        assert request is not None
        for ask in request.asks:
            if ask.kind is not ReadKind.CITATION_HOP:
                continue
            for label in ask.labels:
                assert label.startswith("M"), "the ordinal form ADR-0226 §3 fixes"
                assert label[1:].isdigit()
                assert label[1] != "0", "no padding, and no zeroth position"
                assert label not in {record.id for record in supply}, (
                    "a label is a position, never an identifier (ADR-0226 §3)"
                )

    # --- ADR-0230 §§2-3: the listing across the seam ---------------------------
    # §3 obliges Lane C2 to extend this suite "for the widened input, so the
    # model-backed planner and the canonical fake are both held to it", for the reason
    # ADR-0226 §10 gives — "a canonical fake updated without the suite is an unverified
    # fake". The widening is a **compatibility break** (§3, golden rule 5): a `plan`
    # declaring no `files` parameter does not conform, and these arms are where that is
    # held for every implementation rather than for the one this lane happened to edit.

    @pytest.fixture
    def file_asking_planner(self) -> Planner | None:
        """The same implementation, arranged to emit a ``LOCAL_FILE`` ask — or ``None``.

        Optional for ``asking_planner``'s reason and one step further: ADR-0230 §3
        makes ``files`` additive and defaulted, and §1 makes the kind an additive
        member, so a ``Planner`` that never names a file conforms exactly as one that
        never asks for a read does. A suite requiring an emission would refuse it.

        Returns:
            A planner of the implementation under test that names a file, or ``None``
            where the implementation never names one.
        """
        return None

    async def test_accepts_the_listing_it_was_shown(self, planner: Planner) -> None:
        """The listing is pushed in, and a conforming planner takes it (ADR-0230 §3).

        ``files`` carries "the planner-facing projection of a configured local root's
        entries, one per entry in the listing's own order", read once per turn by the
        loop and passed on every call. A planner neither reaches for one, holds a
        ``Fetcher``, nor opens anything — the same push ADR-0014 §6 makes for
        ``context`` and ``memories``, for the same reason.

        **What is asserted is acceptance**, and deliberately nothing more: ADR-0211 §9
        item 2 forbids this suite asserting which envelope an implementation returns
        for a goal, and whether a listing is worth naming is a model's judgement that
        §2 leaves to an implementation.
        """
        plan = await planner.plan(
            _goal(),
            context=_context(),
            memories=_supply(),
            capabilities=_VOCABULARY,
            files=_listing(),
        )
        assert plan.goal_id == "g1"

    async def test_an_empty_listing_raises_nothing(self, planner: Planner) -> None:
        """``()`` is a legal input and never an error (ADR-0230 §3).

        "``()`` means **no file is nameable on this turn** and is the semantically
        correct answer for a deployment with no fetcher wired and for a ``Planner``
        that knows nothing of this kind; no implementation reads it as an error, a
        degradation, or an instruction to fetch a default." It is also the default, so
        it is what every caller predating this widening supplies — which is why it is
        pinned rather than left to an implementation's judgement.
        """
        plan = await planner.plan(
            _goal(), context=_context(), memories=_supply(), capabilities=_VOCABULARY, files=()
        )
        assert plan.goal_id == "g1"

    async def test_the_listing_need_not_be_a_tuple(self, planner: Planner) -> None:
        """``Sequence[ShownFile]`` is the contract, and a list satisfies it.

        The loop projects a tuple today, so an implementation could pass its whole
        test suite while quietly requiring one — indexing and iteration are common to
        both, ``isinstance(value, tuple)`` and equality against a tuple literal are
        not. Pinned here for ``capabilities``' own reason: the divergence is invisible
        until the first caller that assembles the sequence by other means.
        """
        plan = await planner.plan(
            _goal(),
            context=_context(),
            memories=_supply(),
            capabilities=_VOCABULARY,
            files=list(_listing()),
        )
        assert plan.goal_id == "g1"

    async def test_a_file_it_names_is_an_ordinal_into_the_listing_it_was_shown(
        self, file_asking_planner: Planner | None
    ) -> None:
        """ADR-0230 §2's namer rule, asserted over what a planner actually emitted.

        "The label of the entry at 1-based index *n* of the sequence the loop passed
        is the ASCII string ``F`` followed by *n* in decimal with no padding. That is
        the whole of the scheme." ``F`` and not ``M`` because the two index different
        sequences, and a single namespace over both "would be a label whose meaning
        depends on which kind quoted it".

        **And a planner emits no filesystem address, in any form** (§2): not a path,
        not a name it composed, and not a file's own name copied out of the listing it
        was shown. That last arm is the one that fails on an implementation which
        rendered the listing correctly and then echoed a name back, which would look
        entirely reasonable in a prompt and reach nothing at all.

        What a planner owes is the form and the origin — not a guarantee that every
        label lands, since a label outside the shown set resolves to nothing and is
        discarded silently by the loop (§2).
        """
        if file_asking_planner is None:
            pytest.skip("this implementation never names a file (ADR-0230 §§1, 3)")
        shown = _listing()
        plan = await file_asking_planner.plan(
            _goal(),
            context=_context(),
            memories=_supply(),
            capabilities=_VOCABULARY,
            files=shown,
        )
        request = plan.read_request
        assert request is not None, "the fixture promises an implementation that names one"

        named = [ask for ask in request.asks if ask.kind is ReadKind.LOCAL_FILE]
        assert named, "the fixture promises a LOCAL_FILE ask"
        assert len(named) == 1, "at most one ask of each kind (ADR-0226 §2)"
        [ask] = named
        assert ask.entry is not None
        assert ask.entry.startswith("F"), "the ordinal form ADR-0230 §2 fixes"
        assert ask.entry[1:].isdigit()
        assert ask.entry[1] != "0", "no padding, and no zeroth position"
        assert ask.entry not in {one.name for one in shown}, (
            "a label is a position, never an address (ADR-0230 §2)"
        )
        assert "/" not in ask.entry
        assert "\\" not in ask.entry

    async def test_it_sets_no_supersedes(self, planner: Planner) -> None:
        """ADR-0228 §5: that field is the loop's, on every plan a planner returns.

        "The **one** field any other component ever sets is ``supersedes``, which §5
        gives to the loop and which is not a decision the planner is in a position to
        make": a planner has no opinion about which plan its output replaces, and it
        is not told which iteration it is on.

        A planner that sets one is **not** non-conforming in a way that fails a turn —
        the loop discards the value silently (§5), because "the turn is not the place
        to punish a planner's non-conformance" — but a conforming implementation
        leaves it alone, and this is where that is held.
        """
        plan = await planner.plan(
            _goal(),
            context=_context(),
            memories=_supply() + _fourth_group(),
            capabilities=_VOCABULARY,
        )
        assert plan.supersedes is None

    async def test_a_read_it_asks_for_never_becomes_a_step(
        self, asking_planner: Planner | None
    ) -> None:
        """ADR-0226 §11 item 15's second arm, at the seam that emits it (§4).

        "A ``ReadAsk`` is **not** a ``PlanStep``, and nothing drives it": reading
        the owner's own store is not an act in the world, so no ask is selected
        against the vocabulary, resolved to a tool, ruled on by the permission gate,
        or reaches an executor. At *this* seam that means one thing — an emitted ask
        appears in ``read_request`` and never in ``steps``, whatever it says. The
        turn-level half, that no registry, gate or executor sees one, is the loop's
        and is asserted there.
        """
        if asking_planner is None:
            pytest.skip("this implementation never asks for a read (ADR-0226 §4)")
        plan = await asking_planner.plan(
            _goal(), context=_context(), memories=_supply(), capabilities=_VOCABULARY
        )
        request = plan.read_request
        assert request is not None

        asked = {ask.query for ask in request.asks if ask.query is not None}
        asked |= {label for ask in request.asks for label in ask.labels}
        for step in plan.steps:
            assert step.capability not in asked
            assert step.intent not in asked
