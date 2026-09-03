"""The promoted engine surface is closed under ``core`` (ADR-0085 §5).

ADR-0084 §4 bounds the promoted set by "the *transitive closure* of what the
Protocol's methods name, not just the types they return", and gives the mechanical
reason: promote a type while something its fields reach stays in `orchestration`,
and ``core`` imports `orchestration`, which golden rule 2 forbids and
``lint-imports`` fails.

**``lint-imports`` catches that one type at a time and only once someone writes the
import.** This catches it as a property: it walks the declared field graph out from
every signature on it and asserts every type it reaches is declared in
``core.types``. A type left behind fails here naming itself, rather than as an
architecture violation several edits later.

**It is a walk rather than a list, deliberately.** ADR-0085 §4c records what
happened to the one field list that ADR: it was falsified in a single review round,
having missed ``MemoryBase.id`` and ``Provenance.evidence`` — "a rule over 'every
string' survives, and a list of fields rots". The same argument applies one level
up, so the closure is checked by walking rather than by an enumeration this module
would have to maintain. The names the corpus has promoted are asserted *reachable*,
which is a different claim: it catches a type an ADR promoted and an implementation
forgot, and it cannot go stale in the direction that matters, because a type nobody
reaches is caught by the walk being closed.

**The set the corpus has promoted is now two ADRs' and not one's.** ADR-0085 §5
gathered twenty-four for fifteen methods; ADR-0102 §3 adds ``GrantableSource`` for
the four grant operations, and §13 applies ADR-0070 §1's test to ADR-0085 §1's "and
nothing else" and concludes no supersession is owed — what that exclusion excludes
is *lifecycle*, named in the paragraph it introduces, and the closed graph the
title claims is a property of the **types** rather than of the method count.
ADR-0102 §3 shows the walk from ``GrantableSource`` terminating in ``core`` on
every branch, and the assertions below are what check that claim rather than take
it.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import AsyncIterator, Sequence
from types import UnionType
from typing import Final, get_args, get_origin, get_type_hints

import pytest
from pydantic import BaseModel

from ai_assistant.core import protocols as protocols_module
from ai_assistant.core import types as core_types
from ai_assistant.core.protocols import AssistantEngine

#: ``core/protocols.py`` imports the promoted types under ``TYPE_CHECKING``, so the
#: names in its annotations are not in its module globals at runtime. Resolving them
#: needs ``core.types``' namespace handed in explicitly — and, since ADR-0173 §4 put
#: a method returning an async iterator on the surface, that name too.
_NAMESPACE: Final = {
    **vars(core_types),
    **vars(protocols_module),
    "AsyncIterator": AsyncIterator,
}

#: What the corpus has promoted, ADR by ADR. **The opening total is deleted rather
#: than refreshed**: the set below is the roster and ``len(PROMOTED)`` is a fact the
#: tree carries, while the numeral that stood here had gone stale by four before this
#: change and would have gone stale by five with it (`CONTRIBUTING.md` -> "No state
#: claims in living documents"). The per-ADR ordinals below are not that kind of
#: claim — each names *which* entry an ADR added, which is what a reader checking a
#: promotion against its ADR needs.
#:
#: Twenty-four are ADR-0085 §5's own walk:
#: thirteen from ``engine.py`` (of which ``BeliefSummary`` is new, §4a), six from
#: ``questions.py``, one from ``runner.py``, one from ``loop.py``, two from
#: ``observation.py`` and one from ``conversations.py``. The twenty-fifth is
#: ADR-0102 §3's ``GrantableSource``, which the four grant operations name. The last
#: eight are ADR-0130 §9's, which the five notification operations name: the held
#: record, the candidate it carries, the two enumerations naming a ruling, the
#: standing-preferences value, its per-class row, the reach level that row holds, and
#: the quiet window. §9 promotes them by requiring the five methods to be
#: ``AssistantEngine`` members — "These are contract surface, because
#: ``AssistantEngine`` is a Protocol in ``core/protocols.py``" — so the same walk
#: that caught ``GrantableSource`` is what makes them checkable rather than asserted.
#:
#: The thirty-fourth is ADR-0131 §4's ``NotificationDelivery``, which
#: ``next_notification`` returns: the wrapper that pairs one delivery attempt's
#: identifier with the candidate ADR-0130 already promoted. Its own §4 declares the
#: model field by field for the reason ADR-0085 §3 spells out every signature —
#: "this block is what an implementation is generated from" — and it nests
#: ``NotificationCandidate``, so the walk terminates in types already here.
#: ``NotificationEnqueue`` is deliberately **not** among them: ADR-0131 §3b puts it
#: on ``NotificationOutbox``, which §3b rules "is **not** on ``AssistantEngine`` and
#: nothing it carries crosses the wire", so it is `core` surface that this walk is
#: right not to reach.
#:
#: The last three are ADR-0151 §4's, which the five connection operations name: the
#: two-member provisioning state, the live record, and the act. §4 fixes the set at
#: three and says why the fourth was refused — a ``ConnectionActKind`` enum
#: discriminating a provisioning act from a removal would encode what
#: ``ConnectionAct.account`` being absent already says unambiguously, on a surface
#: whose size is a contract clause, and an enum is the shape that invites the third
#: member ADR-0149 §5 forbids.
#:
#: ``SecretValue`` is **not** among them and its absence is the contract rather than
#: an omission (ADR-0151 §6): it is an ``Annotated`` alias over ``SecretStr``, it is
#: reached only as an *argument* and never as a field of any promoted model, and
#: ADR-0087's canonical projection is deliberately not extended to it. No response
#: on this surface carries a credential value or any value derived from one.
#:
#: The thirty-eighth is ADR-0173 §2's ``ReplyChunk``, which ``converse_streaming``
#: yields before its terminal ``TurnOutcome``. §2 declares it member by member — one
#: member, ``text``, and a stated refusal of the two a reader expects, a sequence
#: number and a final-frame flag — so the walk terminates in ``core`` immediately.
#: It is reached through the *union inside* an ``AsyncIterator``, which is the first
#: annotation on this surface the walk has had to go through two parameterised forms
#: to reach; that it arrives is what makes ADR-0173 §4's return type checkable here
#: rather than asserted.
#:
#: ``SourceGrant`` and ``GrantScope`` are **not** here and that is not an omission:
#: they predate this block (ADR-0097 §2) and are ``core`` leaves the walk terminates
#: at, exactly as :func:`_declared_by_this_change` sorts them.
#:
#: ``SourceReadRecord`` and ``ReadOutcome`` are **not** here for that same reason and
#: it is worth saying, because they are the first types the walk reaches through a
#: method ADR-0186 §10 added rather than through one that predates the block. They
#: are ADR-0185 §12's, declared ahead of :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`
#: in source order, so :func:`_declared_by_this_change` already sorts them as leaves
#: — which is the whole of the test and not a loophole: ADR-0085 §5's property is
#: that ``core`` is closed under its own field graph, and a type declared in
#: ``core.types`` before this block was already inside that closure the day it
#: landed. Listing them here would assert their reachability twice while leaving
#: ``SourceGrant`` asserted once, for no difference in what is checked.
#:
#: The thirty-ninth is ADR-0189 §3's ``Warrant``, which ``Retirement.warrant``
#: names: the standing a retired record is held with, whether its warrant rests on
#: recorded external content, and the attestation on the attested band. It is the
#: one genuinely new type in that decision — ADR-0189 §2's other six additions are
#: fields on models already here, and the ``Attestation`` three of them carry was
#: already inside this closure through ``TurnResult.memories -> MemoryRecord ->
#: Provenance``, which is why §2 could project it whole at no cost to the graph.
#: The walk reaches it through **two** optional hops, ``Question.retires ->
#: Retirement.warrant``, and terminates immediately: ``BeliefBand``, ``bool`` and
#: ``Attestation`` are all already here.
#: The fortieth and forty-first are ADR-0192 §4's ``RecordedInvocation`` and the
#: ``ToolInvocation`` it carries: the row this system writes when it spends an
#: authorisation on an act, joined to the tool identifier, the capability and the
#: egress boolean its decision fixes. The walk reaches them through
#: ``recent_invocations`` and ``export_invocations``, and it terminates there —
#: ``ToolOutcome``, ``ToolFailureKind`` and ``ToolCost`` are all already inside this
#: closure through ``StepOutcome`` and ``ToolDefinition``, and the row carries
#: nothing else.
#:
#: The forty-second and forty-third are ADR-0194 §5's ``SpendTotal`` and the
#: ``SpendPeriod`` it names: what one calendar period has cost, its bounds, the
#: offsets in force at them, and the ceiling and currency configured for it. The
#: walk reaches them through ``spend_totals`` and terminates there — ``Decimal``,
#: ``timedelta``, ``UtcInstant`` and ``EncodableText`` are scalars ADR-0087 §2c
#: spells rather than promoted models, and the row carries nothing else.
#: ``SpendAdmissionHandle`` is **not** here and its absence is decided rather than
#: overlooked: ADR-0194 §5 makes the handle opaque and confines it to the seam
#: between the invoker and its gate, so it "reaches no record, no surface and no
#: wire frame" and no adapter, engine or client ever holds one.
#:
#: **The paired lane owed the placement and this one owes the entry**, which is the
#: mechanism working rather than two lanes remembering. They are declared *after*
#: :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`, so
#: :func:`_declared_by_this_change` counts them and
#: :func:`test_the_promoted_set_is_the_one_the_adrs_gathered` failed the moment the
#: walk reached them — the failure this lane resolved by adding them here. Declared
#: ahead of that boundary they would have been sorted as pre-existing leaves and
#: this check would never have asked.
#:
#: The last four are ADR-0197 §8's — ``RoutedOperation``, which ``TurnOutcome.routed``
#: names, and the three values it carries: ``RoutableOperation``, ``RouteOutcome`` and
#: the ``OperationConfirmation`` a routed park is answered through. The walk reaches
#: them through ``converse``, ``converse_streaming`` and ``resume`` alike, and
#: terminates immediately: ``ContinuationToken`` is already here, and
#: ``RoutedListing``'s seven arms are ``Belief``, ``Question``, ``PermissionDecision``,
#: ``RecordedInvocation``, ``SourceGrant``, ``SourceReadRecord`` and ``SpendTotal`` —
#: every one of them already inside this closure, which is exactly what ADR-0197 §8
#: means by "it mints no payload type of its own".
#:
#: ``RoutedOperationRecord`` and ``RouteApproval`` are **not** here, and their absence
#: is ADR-0197 §9 rather than an omission: that section mints the routing trail's row
#: and gives ``AssistantEngine`` **no method** for it, so nothing on this surface
#: returns one and the walk is right not to reach it. They are ``core`` surface the
#: read-surface ADR §11 defers will promote when it gives them a door.
#:
#: The three after those are ADR-0200's — ``SpokenTurn``, which ``converse_spoken``
#: returns, and the ``SpokenAudio`` and ``SpokenAudioFormat`` it carries. The walk
#: reaches ``SpokenTurn`` through that method's return annotation and its argument
#: annotations alike, and terminates almost immediately: ``TurnOutcome`` is already
#: here, ``NonBlankEncodableText`` is a scalar, and ``SpokenAudio`` carries exactly
#: two members — ``SpokenAudioFormat``, a closed ``StrEnum``, and ``Base64Audio``,
#: which is an ``Annotated`` refinement of a scalar rather than a promoted model and
#: so is a leaf ADR-0087 §2c already spells.
#:
#: ``SpeechFailure`` is **not** here and its absence is the shape of ADR-0200 §4
#: rather than an omission: it is carried by
#: :class:`~ai_assistant.core.errors.TranscriptionFailedError`, an *exception*, and
#: reaches a client through ADR-0085 §10a's error payload rather than through any
#: method's return type. The walk is over the field graph of what the surface
#: returns, so it is right not to reach it; what holds it to the surface is
#: ``wire/errors.py``'s reconstruction, which
#: ``test_every_error_s_structured_state_round_trips_through_its_constructor``
#: exercises over every subtype.
#:
#: ``SpokenRendering`` is ADR-0206 §6's, reached through the ``spoken_rendering``
#: member it gives ``NotificationDelivery``, and it is the second type this roster
#: gains through that already-promoted wrapper. It is a closed ``StrEnum`` whose four
#: serialized values §6 fixes by name, so the walk terminates at it immediately — the
#: shape ``SpokenAudioFormat`` already has here. The member beside it, ``spoken``, is
#: a ``SpokenAudio | None``, and ``SpokenAudio`` is already on this roster, so the
#: rest of ADR-0206 §6's addition reaches no type this list did not already name.
#:
#: The last three are ADR-0225 §10's — ``TranscriptEntry``, which the archive's
#: addressed read and its two enumerating reads return; ``TranscriptHit``, which the
#: search returns; and ``TranscriptArchiveSize``, which §6's size report returns.
#: §10 declares all three field by field and fixes each as additive-only, and the
#: walk terminates at every one of them immediately: ``Identifier``,
#: ``EncodableText``, ``UtcInstant``, ``int`` and ``bool`` are scalars ADR-0087 §2c
#: spells, and ``ExchangeDisposition`` is a closed ``StrEnum`` already inside this
#: closure through ``TurnOutcome``.
#:
#: **Neither archive Protocol is on this surface and neither type it is keyed by is
#: minted here**, which is §10's split rather than an omission. ``TranscriptArchive``
#: and ``TranscriptArchiveWriter`` are seams the *hub* holds — the engine's wide one
#: and capture's narrow one — and nothing on this surface returns either or names
#: one in an argument. What crosses is the three values above, on the seven methods
#: ADR-0225 §14 adds and on no other.
PROMOTED: Final[frozenset[str]] = frozenset(
    {
        "TranscriptArchiveSize",
        "TranscriptEntry",
        "TranscriptHit",
        "SpokenRendering",
        "SpokenTurn",
        "SpokenAudio",
        "SpokenAudioFormat",
        "RoutedOperation",
        "RoutableOperation",
        "RouteOutcome",
        "OperationConfirmation",
        "SpendTotal",
        "SpendPeriod",
        "ToolInvocation",
        "RecordedInvocation",
        "ContinuationToken",
        "Confirmation",
        "StepOutcome",
        "TurnOutcome",
        "LearnDecision",
        "QueueOutcome",
        "QueuedQuestion",
        "IngestSummary",
        "LearnOutcome",
        "Evidence",
        "BeliefSummary",
        "Belief",
        "ConversationSummary",
        "QuestionState",
        "Retirement",
        "SuccessorLink",
        "Question",
        "AnswerKind",
        "AnswerOutcome",
        "Disposition",
        "TurnResult",
        "ObservedProposal",
        "ObservationReport",
        "ConversationDigest",
        "GrantableSource",
        "HeldNotification",
        "NotificationCandidate",
        "NotificationDelivery",
        "NotificationCondition",
        "NotificationDispositionKind",
        "NotificationPreferences",
        "ClassReach",
        "NotificationReach",
        "QuietWindow",
        "ProvisioningState",
        "ConnectedAccount",
        "ConnectionAct",
        "ReplyChunk",
        "Warrant",
    }
)

#: The modules a reached type may legitimately be declared in. ``builtins`` covers
#: ``bool``/``int``/``str``, and the two stdlib modules cover ``datetime`` and
#: ``timedelta``, which :data:`~ai_assistant.core.types.UtcInstant` and the
#: ``timeout`` argument reach.
#:
#: ``decimal`` joins them for ADR-0186 §1's two audit reads. Their
#: ``PermissionDecision`` embeds a whole ``ToolDefinition`` by value (ADR-0021 §1),
#: whose ``ToolCost.amount`` is a ``Decimal`` — ADR-0016 §4's choice, so a money
#: figure is not a binary float. It is a **pre-existing** ``core`` leaf reached for
#: the first time rather than anything this change declared: nothing moved into
#: ``core`` and the closure stays closed under golden rule 2, which is the only
#: property this list exists to protect. Adding it here rather than to
#: :data:`PROMOTED` is what the split means — that set is the *promoted models*, and
#: a stdlib scalar is not one.
_ALLOWED_MODULES: Final[frozenset[str]] = frozenset(
    {"builtins", "datetime", "decimal", "enum", "types", "typing"}
)


def _method_names() -> list[str]:
    """Every public method the Protocol declares."""
    return sorted(name for name in vars(AssistantEngine) if not name.startswith("_"))


def _reachable() -> set[type]:
    """Walk the declared field graph out from every signature on the surface.

    The walk follows a field's **annotation to its declared type**, stops at
    anything it has already seen, and **never follows a method** — which is what
    makes it terminate and what leaves the projection helpers behind (ADR-0085 §5,
    §6a). ``MemoryRecord``'s four-member union is followed through
    :func:`typing.get_args` rather than enumerated, for the same reason.
    """
    seen: set[type] = set()
    pending: list[object] = []
    for name in _method_names():
        method = getattr(AssistantEngine, name)
        pending.extend(get_type_hints(method, globalns=_NAMESPACE).values())
    while pending:
        annotation = pending.pop()
        origin = get_origin(annotation)
        if origin in {UnionType, typing.Union} or origin in {tuple, list, Sequence}:
            pending.extend(get_args(annotation))
            continue
        if get_args(annotation):  # Annotated[...] and every other parameterised form
            pending.extend(get_args(annotation))
            continue
        if not isinstance(annotation, type) or annotation in seen:
            continue
        seen.add(annotation)
        if issubclass(annotation, BaseModel):
            pending.extend(get_type_hints(annotation, globalns=_NAMESPACE).values())
    return seen


def test_every_type_the_surface_reaches_is_declared_in_core() -> None:
    """The closure is closed, which is what golden rule 2 needs it to be.

    A promoted type whose field reached back into `orchestration` would put
    ``core -> orchestration`` in the import graph. This says so as a property of
    the graph rather than waiting for the import to be written.
    """
    stray = sorted(
        f"{reached.__module__}.{reached.__qualname__}"
        for reached in _reachable()
        if reached.__module__ != core_types.__name__
        and reached.__module__.split(".")[0] not in _ALLOWED_MODULES
    )
    assert not stray, f"the surface reaches types outside core.types: {stray}"


def test_the_walk_reaches_every_promoted_type() -> None:
    """Every promoted type is really on the surface.

    The complement of the test above: that one catches a type left behind, this
    one catches a type the ADR promoted and an implementation never wired up — a
    ``Question`` that no method returns is a type nobody can obtain.
    """
    reached = {kind.__name__ for kind in _reachable()}
    missing = sorted(PROMOTED - reached)
    assert not missing, (
        f"ADR-0085 §5 promotes these and the surface reaches none of them: {missing}"
    )


def test_the_promoted_set_is_the_one_the_adrs_gathered() -> None:
    """No further type slipped onto the surface unreviewed.

    ADR-0085 §5's walk is the *complete* graph, and ADR-0015 §5's point is that no
    lane authors ``core`` contract surface unreviewed. A type reachable from these
    signatures that no ADR named is exactly that, so it fails here rather than
    merely growing ``core/types.py`` — which is what caught ``GrantableSource``
    when ADR-0102 added it, and is why this check earns its keep rather than
    merely restating :data:`PROMOTED`.

    The pre-existing ``core`` leaves the walk terminates at are excluded by name
    from the comparison rather than listed: they are whatever ``core.types`` held
    before this change, which is a fact the tree carries and not a list this module
    maintains.
    """
    surface = {kind.__name__ for kind in _reachable() if kind.__module__ == core_types.__name__}
    unexpected = sorted(surface & _declared_by_this_change() - PROMOTED)
    assert not unexpected, (
        f"these reach the surface and ADR-0085 §5 does not name them: {unexpected}"
    )


def _declared_by_this_change() -> set[str]:
    """The names ADR-0085 §5 moved, as the source line order records them.

    Everything declared **after** :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`
    is the promoted block; everything before it predates this change and is a leaf
    the walk terminates at (ADR-0085 §5: "``core`` is already closed under its own
    field graph, which is exactly what ADR-0068 established").
    """
    source = inspect.getsource(core_types)
    boundary = source.index("DEFAULT_PAGE_SIZE: Final[int] = 50")
    tail = source[boundary:]
    return {
        name
        for name, value in vars(core_types).items()
        if isinstance(value, type)
        and value.__module__ == core_types.__name__
        and f"class {name}(" in tail
    }


@pytest.mark.parametrize("name", sorted(PROMOTED))
def test_no_promoted_type_was_left_behind_in_orchestration(name: str) -> None:
    """A type declared in both places is two types, and the wire would see both.

    ADR-0084 §4's "relocating an enum is not redefining it" holds only if the
    relocation is a *move*. A leftover declaration in `orchestration` would be a
    second class with the same name and the same member values, ``!=`` to the
    promoted one, and a client validating against the wrong one would refuse a
    perfectly good payload.
    """
    from ai_assistant import orchestration  # noqa: PLC0415 — asserted about, not used

    assert not hasattr(orchestration, name)


def test_the_walk_really_is_transitive() -> None:
    """The recursion goes past the first level, which is the whole claim (§5).

    A walk that stopped at the returned types would pass every assertion above
    while proving nothing: the twenty-four are all directly named, so a one-level
    walk reaches them too. These five are reachable **only** through two or more
    field hops — ``StepFailure`` and ``ToolFailureKind`` through
    ``StepOutcome.state -> ExecutionState -> StepExecution``, ``Provenance`` and
    ``Validity`` through ``TurnOutcome.turn -> TurnResult.memories ->
    MemoryRecord``, and ``PlanStep`` through ``TurnResult.plan -> ActionPlan``.
    """
    reached = {kind.__name__ for kind in _reachable()}
    assert {"StepFailure", "ToolFailureKind", "Provenance", "Validity", "PlanStep"} <= reached


def test_the_surface_carries_the_methods_the_adrs_fixed() -> None:
    """The count, which the conformance suite needs a number to be complete against.

    ``start`` and ``aclose`` are ruled off the Protocol by ADR-0084 §5, so the
    promoted surface is what the contract ADRs put on it and nothing else:
    ADR-0085 §1's fifteen, plus ADR-0102 §1's four, plus ADR-0130 §9's five —
    a read of the held notifications, a dismissal, a per-notification delete, and
    a read and a write of the standing preferences — plus ADR-0131 §4's one, the
    long poll a notification travels on, plus ADR-0139 §2's one, what the user
    currently authorises read from the grant store. **Reconsideration is not among
    them and may not become one**: ADR-0130 §5 puts it on the concrete
    ``orchestration`` engine, where ADR-0083 §8 puts a maintenance surface, and
    states that "no client asks for it and no interface adapter may drive it".

    ADR-0085 §11b recorded fifteen as
    a correction of ADR-0084 §5's "around nineteen" — a count, not a decision, and
    §5's argument did not rest on the figure. It does not rest on this one either;
    what the number is for is making a *complete* suite something a reader can
    check, since a method nobody bound to the shared contract is a method no
    implementation is held to.

    ADR-0151 §1's five take it to thirty-one: connecting an account,
    re-provisioning one, disconnecting one, and the two listings ADR-0139 §1 keeps
    apart because neither derives the other.

    ADR-0173 §4's ``converse_streaming`` takes it to thirty-two, and it is the first
    addition that is a *second entry on an existing call* rather than a new
    capability: "``converse`` is unchanged — same name, same signature, same clauses,
    same one result frame", and the streaming twin "composes with rather than
    replaces" it (ADR-0042 §5). ``resume`` deliberately gains none, so the count
    moves by one and not two.

    ADR-0186 §1's two take it to thirty-four: ``recent_decisions``, the bounded
    listing of what the permission layer ruled, and ``export_decisions``, the
    whole-trail read that discharges ADR-0004 §6's portability obligation for that
    store. **Two rather than one**, because a single method whose ``limit`` could be
    omitted to mean everything would make the unbounded read of a Tier 1 store the
    default shape of the listing (ADR-0021 §4 declines that in terms) and would
    destroy §2's prefix property, since one method cannot be both a page and the
    whole. Three of ``AuditTrail``'s five reads are deliberately **not** here and
    §4 gives each its own reason — ``resolution_of`` answers a question the user
    cannot ask, ``record`` would let a client append to the audit record of what was
    permitted, ``clear`` would put an irreversible destruction of the whole record
    one request away on a remote transport — while ``get`` is deferred with its
    trigger rather than refused.

    ADR-0186 §10's two take it to thirty-six: ``recent_reads`` and ``export_reads``,
    the same pair one store over, relaying ADR-0185 §12's ``SourceReadTrail``. Two
    for §1's reason exactly, and the pair's own §12 chance to ask for more was
    **declined by this lane rather than forbidden to it**: ADR-0185 §12 left "a
    per-source query and a count … the surface ADR's to ask for if it needs them",
    and §10 passes that choice to the lane rather than closing it, so the two absent
    methods are a decision made here on ADR-0045 §1's and ADR-0028 §7's
    surface-with-no-consumer rule — the same rule ADR-0185 §12 cited when it
    declined them one level down — with ADR-0186 §1's second clause as the precedent
    for the shape. ``SourceReadTrail.record`` and ``clear`` stay unpromoted on §4's
    reasoning read one store over. Neither of the two is a browser operation, by
    ADR-0177 §1's own closed enumeration rather than by any inheritance, so its
    thirty is unmoved.

    ADR-0192 §4's two take it to thirty-eight: ``recent_invocations`` and
    ``export_invocations``, the audit trail's **third** pair and its second row
    kind — what this system did on an authorisation, where the pair above says what
    was decided about one. Two for ADR-0186 §1's reason exactly, and *two
    operations rather than one interleaved listing* for a reason of §4's own: a
    mixed sequence would have to change what ``recent_decisions`` returns, which
    ADR-0186 §1's first clause fixes, and would put ADR-0188 §7's merge inside the
    contract — "at which point either this record is rendered as a ruling, which is
    false, or the rulings are rendered as transmissions". ``AuditTrail``'s
    ``open_invocations`` is deliberately **not** here, and its reason is
    ``resolution_of``'s one row kind over: it answers no question a user can ask —
    it is the exact set ADR-0192 §3's recovery scan is written against, reserving
    every id it returns — and promoting it would put a claim-reservation call one
    request away on a remote transport. Neither of the two is a browser operation,
    by ADR-0177 §1's own closed enumeration, so its thirty is unmoved.

    ADR-0194 §6's **one** takes it to thirty-nine: ``spend_totals``, what each
    calendar period has cost. One rather than a pair, because there is no unbounded
    half to have: it returns exactly two values whatever is configured, so the
    bounded/unbounded split ADR-0186 §1 draws for a *listing* has nothing to divide.
    ``SpendGate``'s two members are deliberately **not** here and neither is any
    "amount remaining" read: ADR-0194 §5 gives the engine a ``SpendLedger`` and
    never a gate, because an adapter able to call the admission has acquired the
    ability to spend a budget. It is not a browser operation either — ADR-0194 §6
    and §11 say so in terms, adding no gateway route, argument or call — so
    ADR-0177 §1's thirty is unmoved again.

    ADR-0200 §3's ``converse_spoken`` takes it to forty, and it is the second
    addition that is a *further entry on an existing call* rather than a new
    capability — ``converse`` and ``converse_streaming`` are untouched, "same names,
    same signatures, same clauses, same results", and a caller that wants no speech
    calls one of them and observes nothing this decision adds. It is also the **first
    addition since ADR-0177 §1 that moves that ADR's browser count**: §12(a)
    partially supersedes §1's enumeration for exactly this member, taking thirty to
    thirty-one, where every addition above left it unmoved. ``resume`` gains no
    spoken twin, and neither speech Protocol is on this surface at all — ADR-0200 §2
    keeps the whole composition behind this one method.

    **This assertion is now also #1125's answer.** ``core/types.py`` and
    ``wire/surface.py`` each carried a prose count of this surface that had gone
    stale by seven; both now name this check instead of restating a number, which
    is `CONTRIBUTING.md` -> "No state claims in living documents" applied to a
    comment in ``src/``.

    ADR-0217 §7's two take it to forty-two: ``guard`` and ``unguard``, the owner's
    explicit placement act on a record already in the store. **Two members and not one
    with a mode**, which ADR-0197 §3's second clause requires of anything in the routed
    vocabulary — an operation taking "a second varying argument … a scope, a mode" is
    outside it — and which §7 states rather than leaves to be inferred: "no lane
    collapses them into one taking a placement". No ``MemoryStore``, ``MemoryWriter``,
    ``ContextProvider``, ``Planner`` or ``NotificationPolicy`` member joins them: §7 is
    explicit that whether the store needs an operation to perform the write "is an
    implementation question inside ``memory/`` that this ADR does not settle", and
    ADR-0219 settled it one door over. Neither is a browser operation, by ADR-0177 §1's
    own closed enumeration, so its thirty-one is unmoved.

    ADR-0225 §14's **seven** take it to forty-nine: the transcript archive's four
    reads, its two destroys and §6's size report. **Seven and not six**, because §6
    makes the size report "a surface operation of its own and not metadata hung on the
    reads" — "a lane that ships the reads without the report has not shipped this
    section" — so the report is on this surface beside them rather than a field on
    ``TranscriptHit`` or ``TranscriptEntry``. And **two destroys and not one**: §5
    gives the archive an address-scoped and a conversation-scoped destroy, each
    resolved inside the archive against its own entries, and neither is reachable
    through ``forget`` or ``forget_conversation`` — those two cascade *into* the
    archive on their way to destroying a belief or a conversation, while these reach an
    entry whose episode the horizon has already evicted.

    **No ``append`` joins them, and that is the ADR's own clause rather than an
    omission** (ADR-0225 §10). ``AssistantEngine`` holds the **wide** seam, which
    carries no write: §1 reserves writing to capture, on the narrow
    ``TranscriptArchiveWriter`` ``ConversationLifecycle`` holds, and a wide face that
    inherited the writer "would give ``AssistantEngine`` an ``append``" — the
    capability split defeated by the convenience that looked like tidiness. Neither
    archive Protocol is on this surface at all; what is here is what a *user* reaches.

    None of the seven is a browser operation either: ADR-0225 §8 requires the CLI and
    *permits* a gateway page "as its own lane touching ``interfaces/`` alone", so
    ADR-0177 §1's thirty-one is unmoved again.
    """
    assert len(_method_names()) == 49


def test_a_streaming_method_declares_its_union_chunk_first_terminal_last() -> None:
    """The convention ``wire.surface`` derives its two adapters from (ADR-0173 §4).

    §4 maps the yielded union onto the frames one-to-one — "a ``ReplyChunk`` is a
    chunk frame, the ``TurnOutcome`` is the terminal result frame" — and
    ``wire.surface`` reads which is which off the annotation's own order rather than
    naming either type. That makes the mapping total by construction, and it makes
    the *order* load-bearing: a second streaming method declared
    ``TurnOutcome | ReplyChunk`` would send chunk payloads in result frames, with
    nothing but a client's validation failure to say so.

    So it is pinned here, beside the Protocol, rather than left to be discovered.
    The set is read off the surface, so a second streaming method is covered the day
    it lands.
    """
    from ai_assistant.wire.surface import STREAMING_METHODS  # noqa: PLC0415 — asserted about

    assert {"converse_streaming"} == STREAMING_METHODS
    for name in sorted(STREAMING_METHODS):
        annotation = get_type_hints(getattr(AssistantEngine, name), globalns=_NAMESPACE)["return"]
        assert get_origin(annotation) is AsyncIterator
        members = get_args(get_args(annotation)[0])
        assert len(members) == 2, f"{name}() yields {len(members)} types; §4's union has two"
        chunk, terminal = members
        assert chunk is core_types.ReplyChunk
        assert terminal is core_types.TurnOutcome


def test_the_promoted_surface_and_the_protocol_version_are_both_pinned() -> None:
    """ADR-0124 §9: changing the promoted method set bumps ``PROTOCOL_VERSION``.

    The rule reaches "any change to the promoted surface's method set", and its
    prose is explicit that this is not an oversight to be forgiven: "adding a
    method bumps… A sixteenth method on the promoted surface is a request an
    older hub answers with a failure the client did not ask for." ADR-0130 §9's
    five took the surface to twenty-four and the version to 3; ADR-0131 §4's
    ``next_notification`` takes it to twenty-five and the version to 4.

    **The two numbers do not move in lockstep, and this pin never asserted that
    they did.** ADR-0124 §9 has a second limb — "a change to a wire-carried
    ``core`` type that makes a value one peer emits invalid for the other" — and
    ADR-0133 §6 fires it for the ``NOTIFY`` member of ``GrantScope``, taking the
    version to 5 with the method set unmoved at twenty-five. So a mismatch here
    is not evidence of a fault in either direction: it is a lane being made to
    look at ADR-0124 §9 and say which limb it is under. ADR-0139 §2's
    ``standing_grants`` is back under the **first** limb, and takes the surface to
    twenty-six and the version to 6. ADR-0170 §3 is under the **second** limb again,
    and it is the clearest case the corpus has: ``TurnOutcome`` gains ``reply`` and
    ``reply_degraded``, ``TurnOutcome`` is ``extra="forbid"``, and
    ``wire.surface.return_adapter`` validates a result against the method's declared
    return annotation — so an older client handed a ``TurnOutcome`` carrying
    ``reply`` fails with ``extra_forbidden`` on that member. The method set does not
    move for it and the version goes to 8.

    **ADR-0173 §11 is the first bump under both limbs at once**, and it moves both
    numbers: ``converse_streaming`` takes the method set to thirty-two (first limb),
    and ``FrameKind.CHUNK`` is a frame an old peer cannot decode at all — an unknown
    ``kind`` closes the connection with no response (ADR-0084 §3) — which is the
    second limb reached at the framing layer rather than inside a payload. So the
    version goes to 9, and a lane that moved only one of these two numbers would
    still be made to read ADR-0124 §9 by this pin.

    **ADR-0178 §6 is under the second limb alone**, and it moves only the version.
    ``Confirmation`` gains ``egress`` — the account identity and payload description
    ADR-0148 §8's fourth clause requires a ``CONFIRM`` on an egress call to name.
    ``Confirmation`` is ``extra="forbid"``, ``return_adapter`` validates every result
    against the declared return annotation, and ``wire.codec``'s ``project`` renders a
    model by ``model_dump()``, which includes a ``None`` member rather than omitting it
    — so a version 10 hub emits ``"egress": null`` on **every** confirmation and a
    version 9 client fails ``extra_forbidden`` on it. The promoted method set does not
    move, so the version goes to 10 against thirty-two methods, and ADR-0178 §6 states
    the bump in the deciding ADR rather than leaving a lane to discover it here.

    **ADR-0181 §3 is under the second limb too**, and moves only the version.
    ``ConfirmationEgress`` gains ``planned_with_external_content``, **required with
    no default**, so it bites in both directions: a version 11 client decoding a
    version 10 hub's confirmation fails ``missing``, and a version 10 client decoding
    a version 11 hub's fails ``extra_forbidden`` on the member it does not declare.
    The promoted method set does not move, so the version goes to 11 against
    thirty-two methods, and ADR-0181's Consequences state the bump in the deciding
    ADR rather than leaving a lane to discover it here.

    **ADR-0186 §1 is back under the first limb**, and it is the first change since
    ADR-0173 §11 to move the method set at all. ``recent_decisions`` and
    ``export_decisions`` take it to thirty-four, so the version goes to 12 —
    ``wire/surface.METHODS`` is derived from the Protocol, so a version 12 client
    sending ``export_decisions`` to a version 11 hub is refused there. **No
    wire-carried ``core`` type changes for it**, which is what makes this the first
    limb alone: ``PermissionDecision`` is untouched and reaches the surface by being
    named in a return annotation rather than by being minted, so a version 11 peer's
    trouble is the unknown *method*, never an unknown member. ADR-0186 §5 states the
    bump in the deciding ADR and §11 puts it on the implementing lane, rather than
    leaving either to be discovered here.

    **ADR-0189 §2 is under the second limb again**, and moves only the version, to
    13 against the same thirty-four methods. The four user-facing projections gain
    the origin of what they show — ``attestation`` and
    ``rests_on_recorded_external_content`` on ``Belief``, ``BeliefSummary`` and
    ``Question``, and ``warrant`` on ``Retirement`` — and ADR-0178 §6's reading of
    the tree carries over unchanged: all four set ``extra="forbid"``,
    ``return_adapter`` validates every result against the declared return
    annotation, and ``wire.codec``'s ``project`` renders a model by ``model_dump()``,
    which includes a ``None`` member rather than omitting it. So a version 13 hub
    emits the new members on **every** belief, question and retirement, and a version
    12 client fails ``extra_forbidden`` on them. It is 10's shape rather than 11's:
    every field is additive with a default (ADR-0189 §9), so the reverse direction
    decodes to the defaults instead of failing ``missing``, and one direction biting
    is all ADR-0124 §9 asks for. ADR-0189 §9 states the bump in the deciding ADR and
    puts it on the contract lane.

    **ADR-0186 §10 is back under the first limb**, and takes the method set to
    thirty-six and the version to 14. ``recent_reads`` and ``export_reads`` are the
    read trail's half of the same decision, so the reasoning at 12 carries over
    without amendment: ``wire.surface``'s ``METHODS`` is derived from the Protocol,
    so a version 14 client sending ``export_reads`` to a version 13 hub is refused
    there, and **no wire-carried ``core`` type changes for it** —
    ``SourceReadRecord`` and ``ReadOutcome`` were promoted by ADR-0185 and reach
    this surface by being named in a return annotation rather than by being minted,
    so a version 13 peer's trouble is the unknown *method* and never an unknown
    member. The obligation is ADR-0124 §9's own — it reaches any change to the
    promoted method set directly — and ADR-0186 §5's third clause is the precedent
    for putting the note on the change that adds the methods, not a clause §10
    carries over.

    **ADR-0192 §4 is under the first limb, and under the second as well** — the
    second time a bump has had two grounds rather than one, ADR-0173 §11 being the
    first. ``recent_invocations`` and ``export_invocations`` take the method set to
    thirty-eight and the version to 15, and the first limb decides it on 12's and
    14's reasoning without amendment: ``wire/surface.METHODS`` is derived from the
    Protocol, so a version 15 client sending ``export_invocations`` to a version 14
    hub is refused there. The second limb is reached because a wire-carried ``core``
    type really did change — ``ToolResult`` gained ``incurred_cost`` in ADR-0192's
    paired lane — and ADR-0192 §9 puts that arithmetic here rather than there: "a
    bump is owed at the surface group whether or not the field reached the wire
    earlier — ADR-0124 §9's obligation is on whoever moves the set." So this entry
    carries no "no ``core`` type changes for it" sentence, unlike 12's and 14's.
    ``ToolInvocation`` and ``RecordedInvocation`` are new *promoted* types rather
    than new wire declarations, reaching the surface by being named in a return
    annotation, exactly as ``Warrant`` did at 13.

    **ADR-0194 §5 is under both limbs too, and says so itself** — the third bump
    with two grounds, and the first where the deciding ADR enumerates them rather
    than leaving a lane to. ``spend_totals`` takes the method set to thirty-nine and
    the version to 16 under the first limb, on 12's, 14's and 15's reasoning
    unchanged. The second limb is the **codec's domain widening**: ``project``
    raised ``TypeError`` on a ``Decimal`` before and encodes one after, so a version
    16 peer may emit a ``PER_CALL`` ``Decimal`` inside a ``PermissionDecision`` that
    a version 15 peer refuses. ADR-0194 §11 forbids splitting the codec widening
    into an earlier change for exactly this reason: two bumps where the topology
    needs one. ADR-0087 §8's first case is **not** met — no conforming encoder
    emitted any bytes for a ``Decimal`` before, so no ratified vector's spelling
    moves — and §5 states that it is not a defence, because ADR-0124 §9 asks what a
    new peer may *send* rather than whether an old spelling moved.

    **ADR-0197 §8 is under the second limb alone**, and moves only the version, to 17
    against the same thirty-nine methods. ``TurnOutcome`` gains ``routed``, and 10's
    and 13's reading of the tree carries over unchanged: ``TurnOutcome`` is
    ``extra="forbid"``, ``return_adapter`` validates every result against the method's
    declared return annotation, and ``wire.codec``'s ``project`` renders a model by
    ``model_dump()``, which includes a ``None`` member rather than omitting it — so a
    version 17 hub emits ``"routed": null`` on **every** turn and a version 16 client
    fails ``extra_forbidden`` on it. The field is additive with a default, so the
    reverse direction decodes to the default instead of failing ``missing``, and one
    direction biting is all ADR-0124 §9 asks for. The promoted **method set does not
    move**: ADR-0197 §9 mints a routing trail and gives ``AssistantEngine`` no method
    for it, and §11 is explicit that this decision changes no method signature on the
    surface — what it moves is one method's *contract*, ``resume``'s, which is a
    different claim and not one ADR-0124 §9 reaches. ADR-0197 §8 states the bump in
    the deciding ADR and §12 puts it on the implementing lane, rather than leaving
    either to be discovered here.

    **ADR-0200 §3 is under the first limb**, and moves both numbers: the method set
    to forty and the version to 18. It is the first-limb reading 12, 14, 15 and
    ADR-0194 §5 all took — ``wire.surface``'s ``METHODS`` is derived from the
    Protocol, so a version 18 client sending ``converse_spoken`` to a version 17 hub
    is refused at the handshake rather than at the call. The **second** limb is
    deliberately not met and ADR-0200 §9 is why: audio crosses as
    :data:`~ai_assistant.core.types.Base64Audio`, which is text, so ADR-0087 §2c's
    scalar table gains no row, ``project`` gains no branch, and no existing frame's
    encoding moves. One limb is all ADR-0124 §9 needs, and naming which one is what
    this pin exists to make a lane do.

    **ADR-0205 §1 is under the first limb, and moves only the version, to 19 against
    the same forty methods.** That limb reaches "any change to the promoted surface's
    method set **or to a method's arguments or results**", and this decision changes
    both halves of the second clause on one method: ``converse_spoken`` gains a fifth
    argument, ``delivery``, and ``SpokenTurn`` gains a fifth member, ``episode_id``.
    It bites in both directions, which no earlier entry's argument half did.
    ``wire.surface``'s argument adapter is derived from the method's own signature, so
    a version 19 client sending ``delivery`` to a version 18 hub is refused there; and
    ``SpokenTurn`` is ``extra="forbid"`` while ``project`` renders a model by
    ``model_dump()``, so a version 19 hub emits ``"episode_id": null`` on **every**
    spoken turn and a version 18 client fails ``extra_forbidden`` on it — 13's reading
    of the tree, on a result 18 had just added. The method **set** does not move:
    ADR-0205 §1 adds an argument to an operation that already exists and §10 records
    ADR-0177 §1 as untouched, since its enumeration counts operations. The
    **second** limb is deliberately not met and ADR-0205 §9 is why: the report is "a
    frozen model of scalars, with ``timedelta`` on ADR-0087 §2e's duration form and a
    ``StrEnum`` as ``SpokenAudioFormat`` already is", so ADR-0087 §2c's scalar table
    gains no row and ``project`` gains no branch.

    **ADR-0207 §7 is under the second limb alone**, and moves only the version, to
    20 against the same forty methods. ``SpokenTurn`` gains no member and loses none
    (ADR-0207 §5); what moves is **which of its shapes the type admits** — on a live
    confirmation park, ``spoken`` may carry a rendering beside an ``outcome`` whose
    ``reply`` is ``None``, and ``spoken_degraded`` may be ``True`` there. That is a
    limb the corpus has been caught by before, and ADR-0124 §9 names the case: the
    rule bumps "whether the change **widens or narrows** the type", because read as
    "narrowing bumps, widening is safe" it would have got ADR-0122's widening wrong.
    The bite is one-directional and one direction is all §9 asks for: a version 20 hub
    emitting a parked turn that carries a rendering is reconstructed through a version
    19 client's copy of the *old* validator — ``wire/client.py``'s ``converse_spoken``
    is annotated ``-> SpokenTurn`` and "a result payload takes the shape of the
    method's own declared return annotation" (ADR-0085 §10) — and raises there. The
    **first** limb is deliberately not met: no method is added, and no method's
    arguments or results change type. ADR-0207 §7 states the bump in the deciding ADR
    and puts it on the implementing lane, and it also fixes the arithmetic against
    ADR-0205's concurrent bump — "whichever lands second reads the constant as it then
    stands and adds one, and each writes its own note".

    **ADR-0206 §1 and §6 are under both limbs at once**, the fourth bump with two
    grounds after 9, 15 and 16, and they move only the version, to 21 against the
    same forty methods. The **first** limb reaches "any change to the promoted
    surface's method set **or to a method's arguments or results**", which is the
    clause ADR-0205 §1's entry at 19 is the precedent for, and this decision changes
    both halves of it on one method: ``next_notification`` gains a keyword-only
    ``plays``, and ``NotificationDelivery`` gains ``spoken`` and ``spoken_rendering``.
    It bites in both directions for 19's reasons — ``wire.surface``'s argument adapter
    is derived from the signature, so a version 21 client sending ``plays`` to a
    version 20 hub is refused there; and ``NotificationDelivery`` is ``extra="forbid"``
    while ``project`` renders a model by ``model_dump()``, so a version 21 hub emits
    both members on **every** delivery and a version 20 client fails
    ``extra_forbidden`` on them. The **second** limb is reached as well, because
    ``SpokenRendering`` is a new wire-carried ``core`` type minted by this decision
    rather than one already crossing — ADR-0087 §2c's scalar table gains no row for it,
    a ``StrEnum`` being a shape the codec already carries, which is why naming the limb
    costs nothing beyond saying so. The **method set does not move**: §1 adds an
    argument to an operation that already exists and declines a sibling operation
    outright, and ADR-0177 §1's browser enumeration stands at thirty-one, since
    ``next_notification`` "is not one" of those and ADR-0206 §2 keeps it that way.

    **ADR-0219 §6 is under the first limb alone**, and moves only the version, to 22
    against the same forty methods — the first entry here whose ground is an **error
    class** rather than a method, an argument or a result. ``core/errors.py`` gains
    :class:`~ai_assistant.core.errors.MemoryStoreStaleError`, which
    ``AssistantEngine.learn`` can emit under the ``MemoryStoreError`` it already
    declares (ADR-0219 §5); ``wire/errors.py`` renders a code as the exception type's
    own *concrete* class name, never flattened to a declared base, because doing so
    would hand a client "a classification the server did not make" (ADR-0077 §3); and
    the decode side resolves that code with ``getattr(core_errors, code, None)``,
    raising ``ProtocolError`` when it cannot. So a version 22 hub emits a frame a
    version 21 peer refuses, one-directionally, which is all §9 asks. The **field**
    beside it is deliberately *not* a ground, and ADR-0219 §6 runs the test on it
    separately: ``MemoryBase.revision`` is additive and defaulted on a type that does
    not set ``extra="forbid"``, which is ADR-0213 §11's ruling on the same envelope,
    and the reverse direction does not exist because no ``AssistantEngine`` method
    takes a ``MemoryRecord`` as an argument. The **second** limb is not met: no
    wire-carried type is minted and ADR-0087 §2c's scalar table gains no row.

    **ADR-0217 §9 is under the second limb alone**, and moves only the version, to 23
    against the same forty methods — its own §7 adds two methods, but those are a
    later change with a bump of their own (§11's ordering). What fires the limb here
    is a **removal**: ``MemoryBase`` gains ``placement`` and ``Provenance`` loses
    ``supplied_withheld_content``. ADR-0213 §11 ruled no bump for *adding* ``topics``
    to the same envelope, because "an older peer decoding a newer hub's record ignores
    a member it does not know" — and a removed member is not ignored, its default is
    *read*. Neither type sets ``extra="forbid"``, so no decode fails in either
    direction, which is precisely the hazard: a peer at 22 reads
    ``supplied_withheld_content`` as its ``False`` default on a record whose placement
    is ``OWNER``, and a peer at 23 reads the default placement on a record an older
    hub had narrowed. Both are §9's "accepted with a different meaning", on the one
    value where the meaning lost is the restrictive one. The types are wire-carried
    through ``TurnResult.memories``, which ADR-0210 §8 reasons from in terms.

    **ADR-0217 §7 is under the second limb too**, and moves only the version, to 24
    against the same forty methods — the second of the three bumps §9 spends, and
    the first here whose ground is a member of an **argument** rather than of a
    result. ``FeedbackEvent`` gains ``guarded``, the owner's explicit act placing
    what a piece of feedback establishes for themselves alone, and
    ``AssistantEngine.learn`` takes a whole ``FeedbackEvent``. ``FeedbackEvent``
    does not set ``extra="forbid"``, so a client at 24 sending ``guarded: true`` to
    a hub at 23 is **not refused** — it is accepted with the member ignored, the
    owner's act recorded nowhere and the record left speakable on a channel of
    unbounded audience. That is §9's "accepted with a different meaning" again,
    with the direction reversed: 23's hazard is an old peer misreading a result,
    and this one is an old hub misreading an instruction. ADR-0213 §11's ruling on
    a defaulted addition is not reached, because it reasons about a *result* an
    older peer merely ignores and nothing acts on. The **method set does not
    move** — ``learn`` already exists and its signature is unchanged, the member
    riding the event the Protocol already takes — and ADR-0087 §2c's scalar table
    gains no row, ``bool`` being a shape ``project`` already carries.

    **ADR-0217 §7's two acts are under the first limb**, and they are the first
    change since ADR-0200 §3 to move the method set: ``guard`` and ``unguard`` take it
    to **forty-two** and the version to 25. ADR-0210 §8 names that limb in terms —
    "§9's reach is the frame — its encoding, the validity of a wire-carried ``core``
    type, and **the promoted surface's method set**" — and ``wire.surface.METHODS`` is
    derived from the Protocol, so a peer at 25 naming ``guard`` reaches a hub at 24
    that does not serve it. It is the **third and last** of the three bumps ADR-0217
    §9 spends, each on its own ground and in its own change, and the only one of them
    under this limb.

    **The return type is deliberately not the ground**, and the distinction is worth
    stating because it is a ``core`` model: ``Placement`` has crossed the wire since
    23, inside ``MemoryBase.placement``, so it is minted here by nothing and ADR-0087
    §2c's scalar table gains no row. What is new is a *method* that returns it. A
    member added to ``Placement`` itself would be the second limb again and would owe
    the test afresh.

    **ADR-0225 §14's seven are under the first limb too**, and they take the set to
    **forty-nine** and the version to 26: four reads, two destroys and a size report,
    all on the transcript archive. §14 states the obligation rather than weighing it —
    "Lane C moves ``PROTOCOL_VERSION``. Adding a method to the engine surface is a
    method-set change, and the obligation falls on the change that adds the method, in
    that same change" — and it states the other half too, that the archive's own store
    lane "moves it not at all: no type it adds crosses ``wire/`` or ``service/``".

    **The three new ``core`` models are not a second ground**, and it is worth
    separating because ADR-0124 §9's second limb is about exactly this shape.
    ``TranscriptEntry``, ``TranscriptHit`` and ``TranscriptArchiveSize`` arrive **on
    the new methods only**, so no value a version 25 peer emits or decodes changes
    shape: an old hub cannot be sent one, because it declines the method first. A
    member added to any of the three later would be the second limb and would owe this
    test afresh.

    **ADR-0228 §6 is under the second limb and moves the version alone**, to **27**,
    with the method set unmoved at forty-nine. ``ActionPlan`` gains ``supersedes``
    (§5); ``ActionPlan`` is carried to a client inside ``TurnOutcome.turn.plan``;
    ``wire/codec.py``'s projection dumps **every** field of a model, defaults
    included; and ``ActionPlan`` sets ``extra="forbid"``. So a peer whose
    ``ActionPlan`` predates the field fails to decode every ``TurnOutcome`` a newer
    hub sends, on every turn rather than on a revising one. ADR-0228 §12 adds no
    Protocol, no member to one and no parameter to any signature, which is why the
    first limb is not reached — and §6 is explicit that no lane reads it as authority
    for bumping on a defaulted addition *alone*: what obliges the move is the
    conjunction, and ADR-0213 §11's no-bump ruling stands for the case it decided,
    which the version log distinguishes on the express ground that neither type there
    sets ``extra="forbid"``.

    **ADR-0124 §9 decides no mechanical check and creates none**, saying one is
    owed and leaving its shape open. This is not that check — it is a *pin*, and
    a deliberately crude one: it fails when either number moves, which is the
    moment a lane touching either has to read that rule rather than discover it
    in review. The real check is #872's and is still owed.
    """
    from ai_assistant.wire.envelope import PROTOCOL_VERSION  # noqa: PLC0415 — asserted about

    assert (len(_method_names()), PROTOCOL_VERSION) == (49, 27), (
        "the promoted method set and the protocol version are pinned together "
        "(ADR-0124 §9); move either and this pin makes you name the limb you are "
        "under — the method set, or a wire-carried core type"
    )


#: ADR-0085 §6b's twelve derived predicates. **The list is normative there** — "a
#: triad implementation that carried a subset would leave the CLI reading an
#: attribute that is not there" — so it is spelled out rather than derived, which
#: is the one place in this module an enumeration is the right shape.
DERIVED_PREDICATES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("IngestSummary", "stored"),
        ("LearnOutcome", "stored"),
        ("Evidence", "lost"),
        ("Belief", "evidence_count"),
        ("Belief", "lost_evidence"),
        ("Belief", "unsupported"),
        ("BeliefSummary", "unsupported"),
        ("ObservedProposal", "stored"),
        ("ObservedProposal", "evidence_count"),
        ("ObservedProposal", "inspectable"),
        ("ObservationReport", "stored"),
        ("ObservationReport", "discarded"),
    }
)


@pytest.mark.parametrize(("owner", "predicate"), sorted(DERIVED_PREDICATES))
def test_every_derived_predicate_is_a_plain_property(owner: str, predicate: str) -> None:
    """§6b: a ``@property``, and deliberately **not** a ``computed_field``.

    A ``computed_field`` would put the value on the wire, which is two sources of
    truth for a fact the fields already carry — and a client that trusted the
    transmitted copy over its own recomputation would be trusting a value nothing
    validates. It also moves the boundary: a value a client can compute exactly but
    one implementation sends and another omits makes the same call measure two
    different sizes against the contract limit.
    """
    model = getattr(core_types, owner)
    assert isinstance(getattr(model, predicate), property), (
        f"{owner}.{predicate} must exist and be a plain property"
    )
    assert predicate not in model.model_computed_fields
    assert predicate not in model.model_fields


@pytest.mark.parametrize("name", sorted(PROMOTED))
def test_no_promoted_model_serialises_a_derived_value(name: str) -> None:
    """The rule behind the list: **nothing** on this surface is a computed field.

    Stated over every promoted model rather than over the twelve, so a thirteenth
    predicate added as a ``computed_field`` fails here even though no list names
    it — which is the failure mode ADR-0085 §4c records an enumeration having.
    """
    model = getattr(core_types, name)
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        return  # a StrEnum has no fields to serialise
    assert model.model_computed_fields == {}
