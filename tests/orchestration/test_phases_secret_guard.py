"""No Tier 0 value can reach the phases' model calls (ADR-0221 §7, carried to the phases).

ADR-0221 §7: capture "stores the reply without inspecting it for a Tier 0 value, and no
implementation adds such an inspection on this path". The reliance is that whatever
writes the reply is supplied nothing holding a Tier 0 value, which ADR-0004 §3 secures
by residency: Tier 0 secrets live in the OS keyring, are read through ``SecretStore`` by
``models/`` and ``tools/`` alone, and are in no record the reply's author is given.

§11 test 13 stated that reliance at the composing stage, by walking every model
reachable from ``ComposingStage.compose``. The composing stage retired at the cutover
(ADR-0309 §5) and that test went with it (#2935). Since the switch the reply is
planning's round text, and two more model calls write what the episode captures
beside it: understanding's record and a digest's evidence. So the same reliance is
stated here **at every seam where a phase hands a model its input, or captures what a
model wrote**, and the walk crosses dataclasses as well as pydantic models, because
the phases hand their inputs over in orchestration-local dataclasses (ADR-0309 §2:3).

Residency is not a property a test can assert directly, so what is asserted is the
**whole object graph** at those seams. Two assertions, failing for different reasons:
the **roster** fails when the graph grows, so a new type reaching a model is judged by
the lane that adds it rather than assumed; the **carrier** check fails when any field
of any type in it admits a Tier 0 carrier. Nothing here claims the fields are safe on
some other ground; it claims the set cannot grow, and no carrier can enter it, without
someone noticing.
"""

from __future__ import annotations

import collections.abc
import dataclasses
import datetime
import decimal
import sys
import typing
import zoneinfo
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from typing import (
    Annotated,
    Any,
    ForwardRef,
    Literal,
    NewType,
    TypeAliasType,
    TypeVar,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import BaseModel, SecretBytes, SecretStr

from ai_assistant.core import protocols as core_protocols
from ai_assistant.core import types as core_types
from ai_assistant.core.protocols import (
    ModelProvider,
    Secrets,
    SecretStore,
    ToolCallingCompleter,
)
from ai_assistant.orchestration import (
    digesting,
    disclosure,
    held_results,
    matters,
    person_block,
    story_links,
    task_scheduler,
    understanding,
)
from ai_assistant.orchestration.digesting import DigestingStage, DigestRecorder
from ai_assistant.orchestration.planning import PlanningStage, RoundRecorder
from ai_assistant.orchestration.understanding import UnderstandingStage
from ai_assistant.secret_store.backend import KeyringBackend
from ai_assistant.secret_store.store import KeyringSecretStore

#: Every type a Tier 0 value is held in or read through: pydantic's two secret types,
#: which :data:`~ai_assistant.core.types.SecretValue` is built on, the keyring seam's
#: two faces, and ``secret_store/``'s backend and store behind them.
_CARRIERS: frozenset[object] = frozenset(
    {SecretStr, SecretBytes, Secrets, SecretStore, KeyringBackend, KeyringSecretStore}
)

#: The leaf types a walked field may name besides an enumeration and a type the walk
#: crosses. A type outside them is one the walk cannot see into, so it is refused rather
#: than passed: a third-party object could carry anything.
_LEAVES: frozenset[type] = frozenset(
    {
        str,
        int,
        float,
        bool,
        type(None),
        datetime.datetime,
        datetime.timedelta,
        decimal.Decimal,
        # ADR-0353 §5:2: the zone understanding renders its times in, a key of the tz
        # database and its rules, read from the person's profile or the hub's settings.
        zoneinfo.ZoneInfo,
    }
)

#: The generic shapes a walked annotation may be built from. Each is walked through its
#: arguments; an origin outside them is one the walk has not been taught, so it is
#: refused rather than passed.
_SHAPES: frozenset[object] = frozenset(
    {
        tuple,
        list,
        dict,
        set,
        frozenset,
        collections.abc.Awaitable,
        collections.abc.Callable,
        collections.abc.Iterable,
        collections.abc.Mapping,
        collections.abc.Sequence,
        typing.Union,
    }
)

#: Where the seams' annotations resolve. They are written under ``from __future__
#: import annotations`` with names imported under ``TYPE_CHECKING``, so each owner's
#: own module namespace is laid over these.
_NAMES: dict[str, Any] = (
    vars(typing)
    | vars(collections.abc)
    | vars(core_types)
    | vars(core_protocols)
    | vars(disclosure)
    | vars(held_results)
    | vars(matters)
    | vars(person_block)
    | vars(story_links)
    | vars(task_scheduler)
)


def _hints(owner: Callable[..., object] | type) -> dict[str, object]:
    """``owner``'s resolved annotations, in its own module's namespace over ``_NAMES``."""
    return get_type_hints(owner, globalns=_NAMES | vars(sys.modules[owner.__module__]))


#: The seams, each a function whose parameters and return are read: so the roots are
#: read off the code rather than restated from memory.
#:
#: - **Understanding's request** — what :meth:`UnderstandingStage.understand` is handed,
#:   and the record it returns, which the episode captures; and the check of the
#:   structured reply its request comes back as (ADR-0354 §8:2), whose shape is the
#:   proposal.
#: - **Planning's request** — :meth:`PlanningStage.plan`'s inputs, from which the
#:   rendered request is built, and its decision; ``ToolCallingCompleter.respond``,
#:   which takes the rendered messages and the offered tools and returns the round; and
#:   ``RoundRecorder.record``, which captures the round into the episode.
#: - **Digesting's request, recall's digest among them** — the three entry points of
#:   :class:`DigestingStage`, what a part reads of its structured reply (ADR-0354 §7:2),
#:   and ``DigestRecorder.record``, which captures the digest.
_SEAMS: tuple[Callable[..., object], ...] = (
    UnderstandingStage.understand,
    ModelProvider.complete,
    understanding._returned,  # what understanding reads of its structured reply
    PlanningStage.plan,
    ToolCallingCompleter.respond,
    RoundRecorder.record,
    DigestingStage.digest_result,
    DigestingStage.digest_records,
    DigestingStage.digest_recall,
    DigestRecorder.record,
    digesting._exchange_of,  # what a digest part reads of its structured reply
)


def _annotation_types(annotation: object, seen: set[int] | None = None) -> list[object]:
    """Every type this annotation names, at any depth, with aliases followed.

    A PEP 695 alias is opaque to ``get_args`` — ``SecretValue`` is ``type SecretValue =
    Annotated[SecretStr, …]`` — so ``__value__`` is resolved; a union, a tuple element, a
    mapping value and an ``Annotated`` origin are all type arguments; a ``Callable``'s
    parameters arrive as a list, which ``get_args`` does not descend; and ``FrozenJson``
    names itself, so the walk stops at a cycle rather than at a recursion limit. A
    parameterized generic's **origin** is named too, so ``Envelope[str]`` reaches
    ``Envelope`` and its own fields rather than only ``str``. A ``Literal``'s arguments
    are values and an ``Annotated``'s metadata is not a type, so neither is descended: a
    string found is then a forward reference and nothing else. A ``NewType`` is followed
    to its supertype, and a type variable to its bound, its constraints and its default,
    since each admits what those admit.
    """
    seen = set() if seen is None else seen
    while isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__
    if id(annotation) in seen:
        return []
    seen.add(id(annotation))
    if isinstance(annotation, list):
        return [found for one in annotation for found in _annotation_types(one, seen)]
    found: list[object] = [annotation]
    for one in _beneath(annotation):
        found.extend(_annotation_types(one, seen))
    return found


def _beneath(annotation: object) -> list[object]:
    """What one annotation admits beneath itself, which the walk descends into."""
    if isinstance(annotation, NewType):
        return [annotation.__supertype__]
    if isinstance(annotation, TypeVar):
        default = [annotation.__default__] if annotation.has_default() else []
        return [*annotation.__constraints__, *default] + (
            [] if annotation.__bound__ is None else [annotation.__bound__]
        )
    origin = get_origin(annotation)
    if origin is Literal:
        return []
    if origin is Annotated:
        return list(get_args(annotation)[:1])
    return [*([] if origin is None else [origin]), *get_args(annotation)]


def _crossed(found: object) -> bool:
    """Whether the walk crosses ``found``: a type of this system's, or of this module's."""
    return (
        isinstance(found, type)
        and not issubclass(found, Enum)
        and (found.__module__.startswith("ai_assistant.") or found.__module__ == __name__)
    )


def _fields(found: type) -> dict[str, object]:
    """What ``found`` holds, by field: a model's fields, a dataclass's, or a constructor's.

    A Protocol is a handle rather than data and holds nothing the walk can read, so it is
    a leaf, named on the roster. A plain class is read by what its constructor takes,
    which is the only way data enters it.
    """
    if issubclass(found, BaseModel):
        # Resolve legitimate forward declarations before reading the fields, so this
        # guard does not depend on which model an earlier test instantiated.
        found.model_rebuild()
        return {name: field.annotation for name, field in found.model_fields.items()}
    if dataclasses.is_dataclass(found):
        hints = _hints(found)
        return {one.name: hints[one.name] for one in dataclasses.fields(found)}
    if getattr(found, "_is_protocol", False):
        return {}
    return {name: hint for name, hint in _hints(found.__init__).items() if name != "return"}


def _reachable(annotations: Sequence[object]) -> dict[str, type]:
    """Every type the walk crosses from ``annotations``, closed over their fields."""
    queue = [found for one in annotations for found in _annotation_types(one)]
    reached: dict[str, type] = {}
    while queue:
        found = queue.pop()
        if not _crossed(found):
            continue
        assert isinstance(found, type)
        name = found.__qualname__
        if name in reached:
            assert reached[name] is found, (
                f"two types named {name} reach the phases' models; the roster names "
                f"types by name, so qualify one here"
            )
            continue
        reached[name] = found
        queue.extend(named for one in _fields(found).values() for named in _annotation_types(one))
    return reached


def _seams_reach() -> dict[str, type]:
    """Every type reachable from the seams' parameters and returns."""
    return _reachable([one for seam in _SEAMS for one in _hints(seam).values()])


def _hole(found: object) -> str | None:  # noqa: PLR0911 — one answer per kind of annotation
    """Why the walk cannot see through ``found``, or ``None`` where it can.

    Closed rather than open: anything that is not a kind of annotation the walk was
    taught is a hole, so a wrapper nobody anticipated fails here instead of passing.
    """
    if isinstance(found, ForwardRef | str):
        return f"carries the unresolved forward reference {found!r}"
    if isinstance(found, type):
        if (
            found in _CARRIERS
            or found in _SHAPES
            or found in _LEAVES
            or _crossed(found)
            or issubclass(found, Enum)
        ):
            return None
        return f"names {found!r}, which the walk cannot see into"
    if isinstance(found, TypeVar):
        if found.__bound__ is None and not found.__constraints__:
            return f"names the type parameter {found!r}, which admits anything"
        return None
    if isinstance(found, NewType) or found is Ellipsis or get_origin(found) is not None:
        return None
    return f"carries {found!r}, an annotation the walk cannot read"


def _holes(annotations: Mapping[str, object]) -> list[str]:
    """Each annotation among ``annotations`` the walk cannot see through, and why."""
    return [
        f"{where} {why}"
        for where, annotation in annotations.items()
        for found in _annotation_types(annotation)
        if (why := _hole(found)) is not None
    ]


def _admitting(annotations: Mapping[str, object]) -> list[str]:
    """Each annotation among ``annotations`` admitting a Tier 0 carrier, with the carriers."""
    return [
        f"{where} admits {carriers}"
        for where, annotation in sorted(annotations.items())
        if (carriers := [one for one in _annotation_types(annotation) if one in _CARRIERS])
    ]


def _seam_annotations(seams: Sequence[Callable[..., object]]) -> dict[str, object]:
    """Every parameter and return annotation of ``seams``, by where it is written."""
    return {
        f"{seam.__qualname__}.{name}": annotation
        for seam in seams
        for name, annotation in _hints(seam).items()
    }


def _field_annotations(reached: Mapping[str, type]) -> dict[str, object]:
    """Every field annotation of every type in ``reached``, by where it is written."""
    return {
        f"{name}.{field_name}": annotation
        for name, model in reached.items()
        for field_name, annotation in _fields(model).items()
    }


def test_every_seam_resolves_and_names_what_it_is_handed() -> None:
    """A seam whose annotations named nothing would make the walk below vacuous."""
    for seam in _SEAMS:
        assert _hints(seam), f"{seam.__qualname__} has no annotations to read"


def test_the_phases_model_supply_is_enumerated_so_a_new_type_must_be_judged() -> None:
    """ADR-0221 §7's reliance, stated at the phases' seams rather than assumed.

    **The records** (carried from ADR-0221 §11 test 13, judged there and still true of
    their fields). ``EpisodicMemory`` with ``Provenance``, ``Attestation``,
    ``ReportedExtent``, ``Validity``, ``Placement`` and ``Capture`` hold Tier 1 memory
    text, identifiers, clocks and closed values. ``Memory`` (ADR-0328 §3), which took
    ``SemanticMemory``'s place in the graph, holds its wording and the envelope's
    fields, with ``MemorySupport``, its parts (``InputPart``, ``RoundMessagePart``,
    ``EvidenceItemPart``, ``ConfirmationPart``, ``RememberCallPart``, ``LegacyPart``, and
    ADR-0329 §9:7's ``ObserverInferencePart``, an episode address alone, and ADR-0338
    §4:4's ``PinPart``, a pin's id alone),
    ``MemoryOperation``, ``OpenQuestion`` and ``TrackRecordEntry``: episode addresses,
    positions, identifiers, clocks, closed values, notes in words and an
    ``Attestation``. A legacy support's ``carries`` is the record stored before ADR-0328
    as frozen JSON — Tier 1 memory text, which the type admits no carrier into.
    ``EpisodeProcessingRecord`` (ADR-0275) holds identifiers,
    closed values and clocks, and the trigger it recorded — ``RecordedChannelTrigger``
    with its input, channel, context items and reply kind, the user's own words among
    them, which ADR-0004 §1 puts in Tier 1. Its
    ``understanding`` (ADR-0276 §7), ``stages`` (ADR-0280 §7), ``recall`` (ADR-0281 §6),
    ``story_links`` (ADR-0300 §6:7), ``rounds`` and ``labels`` (ADR-0307 §10) and
    ``digests`` (ADR-0308 §7) each close their fields with ``extra="forbid"``: prose this
    system's own models wrote, excerpts cut from records already in this graph, labels,
    identifiers, clocks and closed values. Those collections were empty on every record
    when test 13 judged them; since the switch planning, understanding and digesting fill
    them, and what fills them is what this test walks.

    **What a model call is and returns.** ``Message`` is a role, text and a name.
    ``OfferedTool`` is a capability's name, its description and its argument schema as
    frozen JSON. ``RoundResponse`` is planning's text, its ``ProposedCall``s — a provider
    id, a capability name and arguments as frozen JSON — and its ``RoundContinuation``
    (ADR-0356 §6:1): a ``"provider:model"`` name and the provider's own response as frozen
    JSON, the thinking it wrote included: prose a model wrote, no carrier. The request is
    a ``PlanningExchange`` (ADR-0356 §5): planning's rendered instruction and briefing,
    the inputs judged here rendered as text, and each earlier ``ExchangeStep``, its
    response as above and its ``RoundReport`` of ``CallResult``s, code's text of what
    came of a call, and the news, code's text: text, identifiers, no carrier. The
    phases hold it as a ``PlanningWork`` (ADR-0356 §5, §6:4): that exchange, the tools
    offered and the last response, both judged here, a round's id and number, and a
    ``NewsShown`` of what the exchange has shown: identifiers, a count, a version, the
    place window's items judged here, and each earlier work's view as code's text. Each
    call's entry is a ``RecordedCall`` (ADR-0356 §8): identifiers, a capability's name, a
    closed outcome, code's reason, a clock, flags, and, for a message call, a
    ``RecordedDelivery``: the words the assistant sent, the ``ChannelIdentity`` they went
    to and a closed status, prose the model wrote and the place it went, no carrier. A
    ``MessageCallPart`` (§13) is an episode's address, a round's id and a call's id.
    What a done call showed, ``CallShowed`` (ADR-0358 §11:2-§11:4), is a flag and parts,
    each a ``ShownText``, code's or the result's own words with no record's content and
    no outside text held for a digest (§11:3), or a ``ShownRecord``, a closed kind, a
    record's id and a version: no carrier.
    The episode look-ups' results (ADR-0358 §7-§10), on ``CallOutcome``, are planning's
    own shapes: ``EpisodesFound``, a page of ``EpisodeShown``, each an ``EpisodicMemory``
    judged above and the ``MatterShown`` it belongs to, a story's id, a version, its
    summary's first line the tidy-up's model wrote and two flags; ``OlderHistory``, the
    ``PlaceItem`` and ``EpisodicMemory`` records judged above, a page and flags; and
    ``EpisodeRead``, the episode, the ``Memory`` records and ``MatterShown``s it names read
    again, and its full view: an ``EpisodeProjection``, which the windows' episodes already
    project to, with ``ProjectedRound``, ``ProjectedCall``, ``ProjectedProposal``,
    ``ProjectedUnderstanding``, ``ProjectedRecall`` and ``ProjectedJoin``, each positions,
    a capability's name, its recorded arguments as ``ProjectedText``, closed outcomes,
    code's reasons, a ``RecordedDelivery`` and a ``CallShowed`` judged above, the meanings
    and ``UnclearPoint``s understanding wrote, the ids recall kept, and an input's
    ``ChannelIdentity``, parties and words: what the same person's activations read and
    wrote, with no carrier.
    ``ProposedActivationUnderstanding`` with ``UnclearPoint`` (ADR-0353 §9:2, §9:3), and
    digesting's ``DigestReply`` and ``_ProposedItem``, are the parse of a reply: prose the
    model wrote, labels it was shown and a flag; the record keeps the same
    ``UnclearPoint``s. Understanding's comes back as a
    ``StructuredReply[ProposedActivationUnderstanding]`` (ADR-0354 §5:1): that value or a
    closed failure, and a ``ReplyExchange`` with ``ReplyUsage``, which hold the reply as
    the model wrote it, the model's name, closed values, a finish reason, a provider's
    statement of a refusal and token counts: prose a model wrote and counts, no carrier.

    **The capabilities planning is offered.** ``ToolDefinition`` with ``ToolCost`` is
    what a tool declares of itself: identifiers, closed values, the tiers it reaches as
    members of ``DataTier`` (a label, not a value of that tier), descriptions, a JSON
    schema, a ``Decimal`` and currency names. ``system_supplied`` names arguments the hub
    fills after the round is recorded; it holds names, never values. A credential a tool
    needs is read through ``Secrets`` inside ``tools/`` and is in no declaration.

    **Planning's own shapes** (ADR-0309 §2:3). ``PlanningInputs``, ``PlaceWindow``,
    ``PlaceItem``, ``CallOutcome``, ``DigestedEvidence``, ``DigestItem``,
    ``PlanningStories``, ``PlanningStory``, ``PlannedRound``, ``PlannedCall`` and
    ``RefusedCall`` hold identifiers, clocks, closed values, counts, the place's own
    text, prose the models wrote and the types above. **One field is worth naming**:
    ``CallOutcome.result``, with ``HeldResult.content`` on digesting's side, is what a
    tool returned, as frozen JSON. Its type admits no carrier, and a string inside it is
    text an integration answered, which residency keeps free of the credential the tool
    read to ask: the type check stops at that string, as test 13's did at the user's own
    words. ``RecordedCandidate`` (ADR-0329 §4:1, §4:4), on ``CallOutcome.candidate``, is
    a candidate's lookup: the ``Memory`` records judged above, or none where it failed.

    **The story views** (ADR-0300 §6, §8; ADR-0307 §6:1). ``ShortView`` and
    ``Candidates``, with ``StoryNote``, ``StorySummaryLine``, ``StoryStanding``,
    ``StoryHeader``, ``StoryStandingEffect``, ``StoryStandingEpisode``,
    ``StoryStandingEarlier`` and ``StoryRelated``, hold identifiers, clocks, counts,
    closed values, notes planning or the user wrote, and summary lines the tidy-up's
    model wrote. That is why the tidy-up is not a seam of its own here: what its model
    writes reaches planning only as these lines, which this walk already crosses.

    **Understanding's windows** (ADR-0276 §3, ADR-0293 §6:4). ``SuppliedWindow``
    and ``TranscriptWindow``, with ``TranscriptMessage`` and
    ``DeletedMessage``, are the channel's own material: the messages people wrote,
    their positions, authors and identifiers, and the records above. The Telegram
    line's window carries its messages as ``LineMessage`` (ADR-0323 §10): a position,
    a time, an author, the text and what it replies to; and its trigger records each
    message it took in as ``RecordedInputMessage``, with a forward's original sender as
    ``ClaimedAuthor`` — a name and an id Telegram reported (§4:10, §5:4). The bot's
    token never reaches any of them: the client binds it in ``tools/`` (§11:8). An input
    a merge brought (ADR-0349 §7:7, §7:21), a ``JoinedInput``, is a time, the
    ``ChannelIdentity`` it came from, its ``RecordedInputMessage``s and the identifier of
    the activation it was taken from: the user's words and identifiers, with no carrier.
    An in-progress entry (ADR-0349 §5:6), ``InProgressEntry``, and its planning-side
    ``RunningShown``, are an identifier, the ``ChannelIdentity`` that caused it, its input
    in brief read through the peer view, a flag and a closed origin, with when it arrived
    and each of its inputs as an ``EntryInput``, that brief or none and the input's
    parties (ADR-0353 §2:5-§2:7); an offer shown,
    ``OfferShown``, is an identifier, that brief input and the meaning understanding
    wrote. Another activation's own work, ``PeerView`` with ``PeerNotes``,
    ``PeerEffect``, ``ProjectedText`` and ``ProjectedEvidence``, held for planning as
    ``PeerShown`` (§6:7-§6:10), is that activation's input, its meaning, its notes and
    evidence as projected, and its effects by capability or message: what the same
    person's activations read and wrote, with no carrier. For a stop call it also holds
    what the stopped activation set up that is still live (ADR-0352 §3:1-§3:6),
    ``StillLive``: the ``TaskEntry`` and ``ActivationEntry`` records the list pull already
    carries, a ``StartingEntry`` that is a task's identifier alone, counts and a flag.

    **The audience** (ADR-0203, ADR-0204). ``UnboundedAudienceSupply`` and
    ``BoundedAudienceSupply`` filter what is rendered and are never rendered: a set of
    source names and a flag.

    **Digesting's own shapes** (ADR-0308 §4). ``HeldResult`` is identifiers and a
    result, judged above; ``Digested`` is the recorded digest, its labels and a
    code-owned failure word; ``ActivationLabels`` takes nothing but ``PlanningLabel``s.

    **The yes path's records** (ADR-0321 §2:8, §3:1). ``AskedCall`` is a call a round's
    message asked about: its part, the ``ToolDefinition`` judged above, the values it
    sends as frozen JSON (the arguments planning wrote and the hub filled, which a
    proposed call already carries), its ``EgressBinding`` and the ids of the assertions
    it replaces. The binding, with ``EgressDestination``, ``EgressSpan`` and
    ``BoundAccount``, is what a call discloses and to whom: destinations in their
    supplied and canonical forms, spans with their provenance and extent, and the
    account's connection reference and identity, which name a connection and are not
    its credential — that stays in the keyring, read by ``tools/`` alone. No answer
    pointer is in the graph: understanding records none until the authority run
    (ADR-0353 §11:2). On
    planning's side (ADR-0321 §2:8, §4:2), ``CallOutcome.request`` is an
    ``ActionRequest``: the ``ToolDefinition`` and ``EgressBinding`` judged here and the
    values as frozen JSON, exactly what the ``AskedCall`` made from it holds.
    ``QuestionPart`` is a round's id and a part number, and ``ApprovedAction`` pairs one
    with the ``AskedCall`` it names.

    **A ticket** (ADR-0361 §5:1). ``Ticket`` holds the ``ApprovalRequest`` a tap approved:
    the request's ids, its person, planning's ``why`` in its own words, instants, its
    states, the ``ApprovalTap`` that answered it (a closed giver and an instant), the
    ``ApprovalCard``s it was posted as (a place, a position and an opaque token minted
    for the card, naming no record, ADR-0323 §12:4), and its ``RequestedCall``: the same
    ``ToolDefinition``, frozen values and ``EgressBinding`` an ``AskedCall`` holds, judged
    above. Nothing of a credential. ``AskedIn`` (ADR-0322 §4:2), on the chat's window,
    is the question a message is: a round's id and part numbers.

    **The person block** (ADR-0338 §7). ``PersonBlock``, on understanding's ``person``
    and planning's, is a person's id, their ``Profile`` — five fields they typed, the
    person's own words, Tier 1 — the slot as ``KeptInMind``, each a ``Memory`` judged
    above and a flag, a count, and the ``ShownSuggestion``s, each a closed kind, a clock,
    a field and its value as text, or a ``Memory``. Nothing of a credential: the person
    model holds the person's own choices and pointers to memories (§10:3).

    **Recall is not a seam.** :class:`~ai_assistant.orchestration.recall.RecallStage`
    calls no model (ADR-0281 §3); what it decides reaches a model as
    ``ActivationRecall`` through understanding's ``recall`` and as records through
    planning's ``recalled``, both walked here.
    """
    reachable = _seams_reach()

    assert set(reachable) == {
        "ActionRequest",
        "AskedIn",
        "ActivationDigest",
        "ActivationLabels",
        "ActivationRecall",
        "ActivationUnderstanding",
        "ApprovalCard",
        "ApprovalRequest",
        "ApprovalTap",
        "ApprovedAction",
        "AskedCall",
        "Attestation",
        "BoundAccount",
        "BoundedAudienceSupply",
        "CallOutcome",
        "Candidates",
        "Capture",
        "ChannelContext",
        "ChannelContextItem",
        "ChannelIdentity",
        "ClaimedAuthor",
        "ConfirmationPart",
        "DeletedMessage",
        "DigestItem",
        "DigestReply",
        "Digested",
        "DigestedEvidence",
        "EgressBinding",
        "EgressDestination",
        "EgressSpan",
        "EpisodeProcessingRecord",
        "EpisodicMemory",
        "EvidenceItem",
        "EvidenceItemPart",
        "HeldResult",
        "InputPart",
        "JoinedInput",
        "KeptInMind",
        "LegacyPart",
        "LineMessage",
        "Memory",
        "MemoryOperation",
        "MemorySupport",
        # ADR-0345 §2, §7: a support's holder names an identifier the record carries, and
        # a label is a producer's wording, both judged as the memory's other text is.
        "SituationLabel",
        "SupportHolder",
        "Message",
        "NewConversation",
        "ObserverInferencePart",
        "OfferedTool",
        "OpenQuestion",
        "PersonBlock",
        "PinPart",
        "PlaceItem",
        "PlaceWindow",
        # ADR-0350 §4:6-§4:8, §5:10: the Task Scheduler's listing and the place list carry
        # ids, the hub's own renderings and a task's instruction as planning wrote it; a
        # text resting on outside content is withheld, and no credential reaches them.
        "ActivationEntry",
        "ListedPlace",
        "TaskEntry",
        "TaskListing",
        # ADR-0352 §3:1-§3:6: what a stopped activation set up, of the listing's records.
        "StartingEntry",
        "StillLive",
        "Placement",
        "PlannedCall",
        "PlannedRound",
        "PlanningInputs",
        "PlanningLabel",
        "PlanningRound",
        "PlanningStories",
        "PlanningStory",
        "Profile",
        "ProposedActivationUnderstanding",
        "StructuredReply[DigestReply]",
        "StructuredReply[ProposedActivationUnderstanding]",
        "ReplyExchange",
        "ReplyUsage",
        "ProposedCall",
        "Provenance",
        "QuestionPart",
        "RecalledItem",
        "RecordedCandidate",
        "RecordedChannelTrigger",
        "RecordedInputMessage",
        "RecordedSpeechInput",
        "RecordedTextInput",
        "RefusedCall",
        "RememberCallPart",
        "ReportedExtent",
        "RoundMessagePart",
        "RoundResponse",
        # ADR-0356 §5, §6:1, §13: planning's exchange, judged in the docstring above.
        "CallResult",
        "ExchangeStep",
        "PlanningExchange",
        "RoundContinuation",
        "RoundReport",
        # ADR-0356 §5, §8, §13: the work held, each call's entry and a message call's
        # part, judged in the docstring above.
        "MessageCallPart",
        "NewsShown",
        "PlanningWork",
        # ADR-0356 §5:5-§5:6, ADR-0360 §4: what the news compares against and reads again,
        # a matter as shown (``MatterSeen``: its summary's lines, note ids, a flag, an id
        # and a clock), a matter as the store holds it now (``StorySummaryState`` with
        # ``StorySummary``: the ``StoryHeader``, ``StoryNote`` and ``StorySummaryLine``
        # judged above, a version and a clock), and the person as the store holds them now
        # (``PersonNow``: the ``Profile`` and ``Memory`` records the person block carries):
        # no carrier.
        "MatterSeen",
        "PersonNow",
        "StorySummary",
        "StorySummaryState",
        "RecordedCall",
        "RecordedDelivery",
        # ADR-0358 §11:2-§11:4: what a done call showed, judged in the docstring above.
        "CallShowed",
        "ShownRecord",
        "ShownText",
        # ADR-0358 §7-§10: the episode look-ups' results, judged in the docstring above.
        "EpisodeProjection",
        "EpisodeRead",
        "EpisodeShown",
        "EpisodesFound",
        "MatterShown",
        "OlderHistory",
        "ProjectedCall",
        "ProjectedJoin",
        "ProjectedProposal",
        "ProjectedRecall",
        "ProjectedRound",
        "ProjectedUnderstanding",
        # ADR-0349 §5:6, §6:7-§6:10, §7:19: in-progress entries, an offer and another
        # activation's own work, judged in the docstring above.
        "InProgressEntry",
        "EntryInput",
        "OfferShown",
        "PeerEffect",
        "PeerNotes",
        "PeerShown",
        "PeerView",
        "ProjectedEvidence",
        "ProjectedText",
        "RequestedCall",
        "RunningShown",
        "ShortView",
        "ShownSuggestion",
        "SpokenReply",
        "StageEntry",
        "StoryHeader",
        "StoryMember",
        "StoryNote",
        "StoryRelated",
        "StoryStanding",
        "StoryStandingEarlier",
        "StoryStandingEffect",
        "StoryStandingEpisode",
        "StorySummaryLine",
        "StreamingTextReply",
        "SuppliedWindow",
        "Ticket",
        "ToolCost",
        "ToolDefinition",
        "TrackRecordEntry",
        "TranscriptMessage",
        "TranscriptWindow",
        "UnboundedAudienceSupply",
        "UnclearPoint",
        "UnderstandingReferent",
        "Validity",
        "WholeTextReply",
        "_ProposedItem",
    }, (
        "the whole graph the phases hand a model, or capture from one: a type that "
        "joined it is one ADR-0221 §7's reliance now rests on, so judge it and add it here"
    )

    # The seams' own annotations are checked as well as the types they reach: a carrier
    # written on a seam's parameter is the shortest way a secret could reach a model.
    annotations = _seam_annotations(_SEAMS) | _field_annotations(reachable)

    holes = _holes(annotations)
    assert not holes, (
        "an annotation the walk cannot see through could carry a secret past it unseen; "
        "rebuild the model, name the type where it is defined, or judge the new leaf: "
        f"{holes}"
    )

    carriers = _admitting(annotations)
    assert not carriers, (
        "ADR-0221 §7's reliance is that no model the phases call is supplied anything "
        "holding a Tier 0 value, and capture stores what they write without inspecting "
        f"it: {carriers}"
    )


# --- the walk sees what it guards ----------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Aliased:
    held: Mapping[str, tuple[core_types.SecretValue, ...]]


class _Handed:
    def __init__(self, read: Callable[[Secrets], None]) -> None:
        self.read = read


class _Nested(BaseModel):
    inner: tuple[_Aliased, ...] | None = None
    raw: list[SecretBytes] | None = None


def test_the_walk_finds_a_carrier_behind_an_alias_a_container_and_a_constructor() -> None:
    """Each way a carrier could hide from a shallower walk is a way this one finds it.

    An alias over ``SecretStr`` inside a mapping of tuples, on a dataclass reached only
    through a model; a ``Secrets`` handle in a ``Callable``'s parameter list, on a plain
    class read by its constructor; and ``SecretBytes`` in a list on a model.
    """
    reached = _reachable([_Nested | None, Sequence[_Handed]])

    assert set(reached) == {"Secrets", "_Aliased", "_Handed", "_Nested"}
    assert _admitting(_field_annotations(reached)) == [
        f"_Aliased.held admits {[SecretStr]}",
        f"_Handed.read admits {[Secrets]}",
        f"_Nested.raw admits {[SecretBytes]}",
    ]


@dataclasses.dataclass(frozen=True)
class _Envelope[T]:
    payload: T
    credential: SecretStr | None = None


def test_the_walk_crosses_a_parameterized_generic_to_its_own_fields() -> None:
    """``_Envelope[str]`` reaches ``_Envelope`` itself, so a carrier among its fields is found."""
    reached = _reachable([tuple[_Envelope[str], ...]])

    assert set(reached) == {"_Envelope"}
    assert _admitting(_field_annotations(reached)) == [f"_Envelope.credential admits {[SecretStr]}"]


async def _handed_a_secret(
    text: str,
    *,
    credential: SecretStr | None = None,
    keys: Sequence[core_types.SecretValue] = (),
) -> Mapping[str, SecretBytes]:
    raise NotImplementedError


def test_a_carrier_written_on_a_seam_itself_is_found() -> None:
    """A seam's own parameter or return is checked, not only the types it reaches."""
    assert _admitting(_seam_annotations([_handed_a_secret])) == [
        f"_handed_a_secret.credential admits {[SecretStr]}",
        f"_handed_a_secret.keys admits {[SecretStr]}",
        f"_handed_a_secret.return admits {[SecretBytes]}",
    ]


_Credential = NewType("_Credential", SecretStr)
_Anything = TypeVar("_Anything")


def _wrapped[B: SecretStr, C: (str, SecretBytes)](
    new_type: _Credential, bound: Sequence[B], constrained: C | None
) -> None:
    raise NotImplementedError


def test_a_carrier_behind_a_new_type_or_a_type_variable_is_found() -> None:
    """A ``NewType`` admits its supertype, and a type variable its bound and constraints."""
    assert _admitting(_seam_annotations([_wrapped])) == [
        f"_wrapped.bound admits {[SecretStr]}",
        f"_wrapped.constrained admits {[SecretBytes]}",
        f"_wrapped.new_type admits {[SecretStr]}",
    ]


def test_an_annotation_the_walk_cannot_read_is_a_hole_rather_than_a_pass() -> None:
    """What could admit a carrier unseen is refused: the hole check is closed, not open."""
    assert _holes(
        {
            "unbounded": _Anything,
            "any": Any,
            "foreign": collections.deque[str],
            "unresolved": ForwardRef("Elsewhere"),
            "unread": typing.ParamSpec("_Params"),
        }
    ) == [
        f"unbounded names the type parameter {_Anything!r}, which admits anything",
        f"any names {Any!r}, which the walk cannot see into",
        f"foreign names {collections.deque!r}, which the walk cannot see into",
        f"unresolved carries the unresolved forward reference {ForwardRef('Elsewhere')!r}",
        "unread carries ~_Params, an annotation the walk cannot read",
    ]
