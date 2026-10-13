"""What one captured episode records, after ADR-0221's capture flip (§12, Lane E).

Three facts move at the capture point and this module is where each is pinned.
``outcome`` stops carrying one of sixteen constant phrases and carries **the
composed reply, whole** (§1); what became of the pass is recorded; and
``capture.modality`` carries how the user material the episode renders reached this
system (§5). Since ADR-0284 §5 the second fact is the verdict on the ``drive`` or
``routing`` stage entry that reached it, and the episode carries no ``disposition``
(§5:3), so each case reads the verdicts off the stage record.

ADR-0221 §11's tests 1, 2, 3, 10, 11, 12, 13, 14 and 15 live here, each named in the
case that discharges it, plus issue #1873's population — a record carrying a verdict
beside an ``outcome`` of ``None``, which this flip is the first thing in the system
to write.

**§11's test 4 has been deleted, and this is where it was.** It asserted that a
distinctive span in a captured reply reached no prompt the observer, the planner or
the composer assembled, and §11 named it in terms as "the test a reader lane must
consciously delete". ADR-0222 §8 performs that deletion — "it is performed here
rather than left to the implementing lane's discretion" — because §1 and §3 now
render the reply in the conversation tail and in the observation batch. What replaces
it is not nothing: §8's assertion 10 keeps test 4's *shape* over the population §2
keeps phrase-only, at each request assembler, which is why the deletion is a
narrowing rather than an abandonment. The positive half is asserted end to end here,
in the case below that used to be test 4.

**Test 14 is untouched and is the case ADR-0222 most easily breaks**, so §8's
assertion 12 restates it over the change's own surface: the capture path and the
render sites emit no log event whose payload contains the reply's text, elided or
whole. The observation path and its render site were retired by ADR-0285 §1.
Rendering a reply into a prompt is not a licence to log it (ADR-0004 §5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ForwardRef, TypeAliasType, get_args, get_type_hints

from pydantic import BaseModel, SecretStr

from ai_assistant.core import types as core_types
from ai_assistant.core.protocols import SecretStore
from ai_assistant.core.types import (
    EpisodicMemory,
)
from ai_assistant.orchestration import composing
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.testing import (
    FakeModelProvider,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from test_engine import (
        Harness,
    )

    from ai_assistant.core.types import (
        MemoryRecord,
    )


def _episodes(records: Sequence[MemoryRecord]) -> list[EpisodicMemory]:
    """Every episode among ``records``, in the order the store returned them."""
    return [record for record in records if isinstance(record, EpisodicMemory)]


async def _captured(harness: Harness) -> list[EpisodicMemory]:
    """Every episode the harness's memory store holds, in write order."""
    return _episodes(await harness.memory.export())


def _replying(reply: str) -> ComposingStage:
    """A composing stage whose whole-answer seam returns ``reply``."""
    return ComposingStage(model=FakeModelProvider(reply), streaming=FakeStreamingCompleter())


# --- §11 test 13: the Tier 0 reliance, at the seam it rests on -----------------


def _annotation_types(annotation: object, seen: set[int] | None = None) -> list[object]:
    """Every type this annotation names, at any depth, with aliases followed.

    Three things make a hand-written walk necessary rather than fussy, and each of them
    is a way a shallower check would answer "no secret here" about an annotation that
    has one.

    - **A PEP 695 alias is opaque to ``get_args``.** ``SecretValue`` is
      ``type SecretValue = Annotated[SecretStr, …]``, and ``get_args`` of a
      ``TypeAliasType`` is empty — so a walk that did not resolve ``__value__`` would
      stop at the alias and never see :class:`~pydantic.SecretStr`. That is not
      hypothetical: it is how the first version of this test passed with a
      ``SecretValue`` field added to :class:`~ai_assistant.core.types.Goal`.
    - **A union, a tuple element and a mapping value are all type arguments**, so one
      recursion over ``get_args`` reaches every position a field can hold a value in.
    - **Some aliases in this module are recursive** — ``FrozenJson`` names itself — so
      the walk carries the identities it has already resolved and stops at a cycle
      rather than at a recursion limit.
    """
    seen = set() if seen is None else seen
    while isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__
    if id(annotation) in seen:
        return []
    seen.add(id(annotation))
    found: list[object] = [annotation]
    for argument in get_args(annotation):
        found.extend(_annotation_types(argument, seen))
    return found


def _models_in(annotation: object) -> list[type[BaseModel]]:
    """Every pydantic model this annotation names, at any depth."""
    return [
        found
        for found in _annotation_types(annotation)
        if isinstance(found, type) and issubclass(found, BaseModel)
    ]


def _reachable_from_the_composing_stage() -> dict[str, type[BaseModel]]:
    """Every model reachable from what ``ComposingStage.compose`` is handed on a turn.

    Starts at the method's own resolved parameter annotations — so the roster is read
    off the seam rather than restated from memory — and closes over each model's fields
    transitively. ``get_type_hints`` is given both modules' namespaces because the
    signature is written under ``from __future__ import annotations`` and names types
    from each.
    """
    hints = get_type_hints(ComposingStage.compose, globalns=vars(core_types) | vars(composing))
    queue = [
        model
        for name, annotation in hints.items()
        if name != "return"
        for model in _models_in(annotation)
    ]
    reached: dict[str, type[BaseModel]] = {}
    while queue:
        model = queue.pop()
        if model.__name__ in reached:
            continue
        # Resolve legitimate forward declarations before walking the graph;
        # this guard must not depend on which model earlier tests instantiated.
        model.model_rebuild()
        reached[model.__name__] = model
        for field in model.model_fields.values():
            queue.extend(_models_in(field.annotation))
    return reached


def test_the_composing_stages_supply_is_enumerated_so_a_new_field_must_be_judged() -> None:
    """§11 test 13: §7's reliance, stated rather than assumed.

    §7: capture "stores the reply without inspecting it for a Tier 0 value, and no
    implementation adds such an inspection on this path. The reliance is that the
    composing stage is supplied nothing holding a Tier 0 value, which ADR-0004 §3
    secures by residency: Tier 0 secrets live in the OS keyring, are read through
    ``SecretStore`` by ``models/`` and ``tools/`` alone, and are in no record, facet,
    plan or step account the composing stage is given."

    Residency is not a property a test can assert directly, so what is asserted is the
    **whole object graph** the stage is handed: the four arguments it takes on a turn,
    and every model reachable from them transitively. A guard over the top-level models
    alone would miss the case that matters — a secret-carrying field added to ``Goal``,
    to a facet, or to a provenance would reach the composer while a shallow roster still
    passed.

    Two assertions, and they fail for different reasons. The **roster** fails when the
    graph grows: a new model reaching the stage is a new thing to judge, and §7 makes
    that judgement the implementing lane's rather than an assumption left implicit. The
    **carrier** check fails when any field on any of them admits ``SecretStr`` — which
    is what :data:`~ai_assistant.core.types.SecretValue` is built on and what every
    Tier 0 value in this system is typed with.

    Nothing here claims the fields listed are safe on some other ground; it claims the
    set cannot grow, and no secret can enter it, without someone noticing.

    **``ReadAsk`` and ``ReadRequest`` joined the graph with ADR-0226 §4**, because
    ``ActionPlan`` gained ``read_request`` and the plan is one of the four arguments
    the stage takes. The judgement §7 asks of the lane that grows the graph, made
    rather than assumed: between them they carry a kind from a closed enum, a query
    the planner composed, and labels that are ordinals into this turn\'s ``memories``
    — text this system\'s own planner wrote, on models that admit no ``SecretStr``
    and hold no store. The carrier check below is what keeps that true rather than
    merely stated.

    **``StructuredAsk`` and ``TimeWindow`` joined it with ADR-0240 §2**, because
    ``ReadAsk`` gained ``structure``. The same judgement, made again rather than
    inherited: between them they carry two ``datetime`` values and three tuples of
    label text the planner composed from the records it was shown — no store, no
    handle, no token, no field admitting a ``SecretStr``, and nothing a caller
    supplies. ``TimeWindow`` is the type ADR-0237 §2 minted for ``MemoryStore``'s own
    filter axis and reaches this graph unchanged (ADR-0240 §2's no-second-window-type
    clause), so what is new here is a path to it and not a second shape of it.

    **``OutboundStatement`` joined it with ADR-0264 §6**, because the stage gained the
    ``outbound`` keyword. The judgement §7 asks of the lane that grows the graph, made
    rather than assumed: ADR-0264 §4 closes the model at three fields and states the bar
    over them in terms — "no destination, no host, no origin, no provider name, no
    connection reference, no account identity, no tool identifier, no query and no
    fragment of one, no record, no title, no snippet, no monetary figure, no duration,
    no ``Settings`` field name, no ``SearchDisposition`` value, no record id, no decision
    id and no instant". What is left is two ``StrEnum`` members and a bounded ``int``,
    none of which admits a ``SecretStr``, and the model sets ``extra="forbid"`` so a
    fourth field is unconstructable rather than unnoticed. The carrier check below is
    what keeps that true rather than merely stated.

    **``AuthorizationProjection``, ``CoverageView`` and ``ValueBound`` joined it with
    ADR-0254 §11**, because ``Confirmation`` — already in this graph through
    ``StepOutcome`` — gained ``authorization``. The judgement §7 asks of the lane that
    grows the graph, made rather than assumed. ADR-0254 §11 closes each of the three
    models at its stated fields with ``extra="forbid"``, and states the bar over them in
    terms: the projection *"carries **no** goal id, no authorization id, no
    ``BoundAccount``, no connection reference, no ``SecretName`` and no transport
    endpoint"*, and names no identifier of any kind. What is left is an argument **key**
    at depth one, a value the record already holds — which is a
    :data:`~ai_assistant.core.types.FrozenJsonValue`, the same type ``PlanStep``'s own
    ``parameters`` are built on and already in this graph — a bound of three closed
    kinds carrying a currency code, two ``Decimal`` limits, two instants, an IANA zone
    name and a tuple of terms, a span of the **user's own words**, and one instant. None
    of those fields admits a ``SecretStr``, and the carrier check below is what keeps
    that true rather than merely stated.

    **The span is the one member worth naming explicitly**, because it is text a person
    typed rather than text this system composed. It is Tier 1 and not Tier 0 — ADR-0004
    §1 puts the user's own words there, and ADR-0254 §16 says so of this very store in
    terms — and residency is what §7's reliance rests on: a Tier 0 secret lives in the
    OS keyring, is read through ``SecretStore`` by ``models/`` and ``tools/`` alone, and
    reaches an ``Authorization``'s basis by no route at all. A ``Confirmation``'s
    ``parameters`` already put the user's own argument values in front of this stage.

    **``BriefAction`` joined it with ADR-0265 §4**, because ``GoalBrief`` gained
    ``actions`` and the brief is one of the four arguments the stage takes. The same
    judgement, made rather than inherited: §4 closes the model at two fields and states
    the bar over them in terms — no ``IntendedAction.id``, no effect, no execution, no
    step, no outcome and no indication of whether the action has already been
    performed. What is left is prose this system's own planner proposed and a tuple of
    the brief's own ``C``/``S``/``D`` labels, which are ordinals into the current
    revision, minted per call and persisted nowhere. Neither field admits a
    ``SecretStr``, and the model sets ``extra="forbid"``.

    **``QuoteView`` joined it with ADR-0267 §7**, because ``AuthorizationProjection``
    gained ``quote`` and the projection already rides inside a ``Confirmation`` here.
    The same judgement, made rather than inherited: §7 closes the model at three fields
    and states the bar over them in terms — no digest, no intended action, no plan, no
    step, no goal id and no authorization id. What is left is a ``Decimal`` the
    provider's own output carried, a three-letter currency code and one instant. None
    admits a ``SecretStr``, and the model sets ``extra="forbid"``. **It is ``None`` on
    every projection this tree renders**, its producer being ADR-0254 §20's Lane 2
    (ADR-0267 §11) — the field is in the graph as a shape, and the judgement is made
    now rather than left to the lane that fills it.

    **``ActivationUnderstanding``, ``UnderstandingReferent``, ``UnderstandingReference``,
    ``UnderstandingRelationship`` and ``UnresolvedMatter`` joined it with ADR-0276 §7**,
    because ``EpisodeProcessingRecord`` — in this graph since ADR-0275 — gained
    ``understanding``. The judgement §7 asks of the lane that grows the graph, made
    rather than assumed: ADR-0276 §2 closes each of the five at its stated fields with
    ``extra="forbid"`` and states what the record carries — *"no goal id, no attempt id,
    no plan id and no label"*. What is left is a version number, one instant, two members
    of closed enumerations, prose ``orchestration`` copied from this system's own
    understanding stage, and per referent a kind from a closed literal, an episode's
    stored address or an item's id, a source rendering, and an excerpt of at most 240
    characters that ``orchestration`` cut from material already in front of this stage
    — a channel item or a record this same graph carries. None of those fields admits a
    ``SecretStr``. **Every ``understanding`` is empty on every record this tree
    captures**, its producer being ADR-0276 §8's step 3 — the field is in the graph as
    a shape, and the judgement is made now rather than left to the lane that fills it.

    **``StageEntry`` joined it with ADR-0280 §7**, because ``EpisodeProcessingRecord``
    gained ``stages``. The judgement, made rather than assumed: ADR-0280 §6 closes the
    entry at five fields with ``extra="forbid"`` — three members of closed enumerations
    and two clock readings — and states that an entry carries no stage result and never
    the error a failed stage raised. None of those fields admits a ``SecretStr`` or any
    text. **Every ``stages`` is empty on every record this tree captures**, its producer
    being ADR-0280 §8's step 2.

    **``ActivationRecall`` and ``RecalledItem`` joined it with ADR-0281 §6**, because
    ``EpisodeProcessingRecord`` gained ``recall``. The judgement, made rather than
    assumed: both close their fields with ``extra="forbid"``. They hold members of closed
    enumerations, a stored memory id, a bounded excerpt taken from a stored memory
    record's own text (never an outside episode's raw input, ADR-0281 §6), two
    structured-origin values and an ``Attestation``, which is already in this graph.
    None admits a ``SecretStr``, and the excerpt is the same Tier 1 memory text the
    graph already reaches through ``SemanticMemory`` and ``EpisodicMemory``. **Every
    ``recall`` is ``None`` on every record this tree captures**, its producer being
    ADR-0281 §8's step 3.

    **``ConversationInputOptions``, ``TurnReference`` and ``SpokenDeliveryReport`` left
    it with ADR-0284 §3:1**, because ``RecordedChannelTrigger`` lost ``conversation``,
    the one path by which the composing stage's graph reached them.

    **``StoryMember`` joined it with ADR-0300 §6:7**, because ``ActivationUnderstanding``
    — in this graph since ADR-0276 §7 — gained ``story_links``. The judgement, made
    rather than assumed: ADR-0289 §2 closes the model at two fields with
    ``extra="forbid"``, a member of a closed enumeration and an identifier — a story
    id the story store minted or an activation id the hub minted — and §2:7 holds that
    no field of a story holds free text. Neither admits a ``SecretStr``. **Every
    ``story_links`` is empty on every record a deployment without the story-links stage
    captures**, and on one with it each link names a story or an activation and nothing
    of what either holds.

    **``PlanningRound``, ``ProposedCall`` and ``PlanningLabel`` joined it with ADR-0307
    §10**, because ``EpisodeProcessingRecord`` gained ``rounds`` and ``labels``. The
    judgement, made rather than assumed: each closes its fields with ``extra="forbid"``.
    A round holds an id, the round it follows, a clock reading, its text, its notes and
    two booleans; a proposed call a provider id, a capability name and its arguments as
    frozen JSON; a label a label, a member of a closed enumeration and the id it names.
    None admits a ``SecretStr``: the text, the notes and the arguments are what the
    planning model wrote, the same Tier 1 text the graph already reaches through
    ``EpisodicMemory.outcome``. **Every ``rounds`` and ``labels`` is empty on every
    record this tree captures**, their producer being the planning stage the cutover
    switches on (ADR-0309 §2:6).

    **``ActivationDigest`` and ``EvidenceItem`` joined it with ADR-0308 §7**, because
    ``EpisodeProcessingRecord`` gained ``digests``. The judgement, made rather than
    assumed: each closes its fields with ``extra="forbid"``. A digest holds a label, the
    question planning asked, a member of a closed enumeration, its items and a clock
    reading; an item its text, a label and a mark fixed true. Neither admits a
    ``SecretStr``: the question is what the planning model wrote, and an item's text is
    what the digest model wrote of outside content, marked as such. **Every ``digests``
    is empty on every record this tree captures**, their producer being the digesting
    stage the cutover switches on (ADR-0309 §2:6).
    """
    # ADR-0275: processing metadata joins the in-process record graph. Its
    # fields are identifiers, closed values, clocks and caller-supplied Tier 1
    # text; none admits SecretStr or a store. It is excluded from model prompts
    # by explicit projections, exercised below over planner/composer/observer.
    reachable = _reachable_from_the_composing_stage()

    assert set(reachable) == {
        "ActivationDigest",
        "ActivationLinks",
        "ActivationRecall",
        "ActivationUnderstanding",
        "RecalledItem",
        "ChannelContext",
        "ChannelContextItem",
        "ChannelIdentity",
        "EpisodeProcessingRecord",
        "EvidenceItem",
        "NewConversation",
        "ParkedBinding",
        "PlanningLabel",
        "PlanningRound",
        "ProposedCall",
        "RecordedChannelTrigger",
        "RecordedResumeTrigger",
        "RecordedSpeechInput",
        "RecordedTextInput",
        "SpokenReply",
        "StreamingTextReply",
        "WholeTextReply",
        "ActionPlan",
        "Attestation",
        "AuthorizationProjection",
        "CoverageView",
        "QuoteView",
        "ValueBound",
        "CalendarFacet",
        "Capture",
        "Confirmation",
        "ConfirmationEgress",
        "ContinuationToken",
        "CurrentContext",
        "EgressDestination",
        "EgressSpan",
        "EmailFacet",
        "BriefAction",
        "BriefElement",
        "EpisodicMemory",
        "ExecutionState",
        "GoalBrief",
        "Placement",
        "PlanInterpretation",
        "PlanStep",
        "PreferenceMemory",
        "ProceduralMemory",
        "Provenance",
        "ReadAsk",
        "ReadRequest",
        "ReportedExtent",
        "ResultReference",
        "OutboundStatement",
        "SemanticMemory",
        "SpokenDelivery",
        "StageEntry",
        "StoryMember",
        "StepCondition",
        "StepExecution",
        "StepFailure",
        "StepOutcome",
        "StepOutputRef",
        "StepVerification",
        "StructuredAsk",
        "TimeWindow",
        "TurnResult",
        "UnderstandingReference",
        "UnderstandingReferent",
        "UnderstandingRelationship",
        "UnresolvedMatter",
        "Validity",
    }, (
        "the whole graph the composing stage is supplied on a turn — the records, the "
        "facets, the plan and the step account, and everything they carry. A model that "
        "joined it is a model ADR-0221 §7's reliance now rests on"
    )

    for name, model in sorted(reachable.items()):
        for field_name, field in model.model_fields.items():
            resolved = _annotation_types(field.annotation)
            # An unresolved forward reference is a hole in this check rather than a
            # clean field: the walk cannot see through a `ForwardRef`, so a secret
            # behind one would pass silently. Refusing it is what keeps the assertion
            # below meaning what it says.
            assert not any(isinstance(found, ForwardRef) for found in resolved), (
                f"{name}.{field_name} carries an unresolved forward reference, so the "
                f"walk below cannot see what it admits; rebuild the model or name the "
                f"type where it is defined"
            )
            carriers = [found for found in resolved if found in {SecretStr, SecretStore}]
            assert not carriers, (
                f"{name}.{field_name} admits {carriers}; ADR-0221 §7's reliance is that "
                f"the composing stage is supplied nothing holding a Tier 0 value, and "
                f"this field would carry one straight into the composed reply"
            )
