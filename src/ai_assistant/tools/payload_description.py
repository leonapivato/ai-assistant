"""The deterministic account of what a call would transmit, span by span.

ADR-0148 §6's payload description, built by the producer that owes it: "produces
a deterministic description of its own payload" (Consequences). Four clauses of
§6 and one of ADR-0146 shape everything here.

**It is deterministic, and its inputs are exactly three.** §6: "a function of
exactly three things — the request's own arguments, each destination-bearing one
in **both** the supplied and the canonical form the request already carries for
it …, the provenance the request carries for their spans, and the registry's
definition for the bound tool — and of nothing else: no clock, no configuration,
no store read, no network." :func:`describe_payload` takes those three and reads
nothing else, so "two derivations of the description for one request agree" and
an approver, the seam and a later auditor can each re-derive and compare it. It
**derives** the destinations from the tool's own declaration rather than
accepting them, for the reason that function's docstring gives: a recipient set
handed in beside the arguments is bound by nothing and re-derivable by nobody.

**It covers every span, or the call is refused.** §6: "a span transmitted but not
covered is a defect rather than a permitted omission", and a request whose
description does not cover every span it would transmit "cannot be completed and
is refused **before the ruling**". So an argument the declaration does not name is
:class:`UndescribedSpanError`, deterministically, on every derivation — ADR-0148
§14's **omitted-span** case, which covers a selected record and a user-authored
free-text argument alike.

**Provenance is carried, never inferred.** ADR-0146 §2: "decided by **recorded
origin**, never by inspecting a span and never by matching it against anything
the user wrote", and "a span for which no origin was recorded is
**system-selected**". Both are here: the caller passes a mapping keyed by span,
and a span missing from it is system-selected — the fail-closed direction, and
"the clause most likely to be quietly dropped". ADR-0148 §14's
**carried-provenance** pair is the test: two requests with byte-identical
arguments produce **different** descriptions when the carried provenance differs.

**A user-authored free-text span states no tier.** ADR-0146 §5: a field
establishes a tier "only where every value it can hold carries the same tier by
what the field is for — a recipient address, an account identifier, a credential
reference", while "a message body, a note, a subject line" establishes none. Where
the field establishes one, the description states it whatever the provenance
(§5's second and third clauses); where it does not and the user composed the span,
the description states its provenance and its extent and **no tier**, which is the
honest description ADR-0146 §5 spells out: "the user's own words, verbatim, N
characters, to <destination>".

**It holds no content and no credential value.** A :class:`SpanDescription`
carries an extent, not the span. That is what makes it, in §6's words, "exactly
the artifact that is safe to keep where the content is not" — the departure from
ADR-0021 §1's posture that §6 argues for, and the reason "a hash defeats the
purpose" (#57) does not apply to it. Destinations are the deliberate exception:
§2's fourth clause requires both forms of each in the record.

**Nothing here is a `core` type and nothing here transmits.** Where the
description rides, and what type it is, is ADR-0148 §11's surface (a) — deferred
to its own contract ADR, with this module as the producer whose demands are meant
to shape it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ai_assistant.core.errors import ToolError
from ai_assistant.core.types import DataTier
from ai_assistant.tools.destination_arguments import DestinationDeclaration, select_destinations

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson
    from ai_assistant.tools.destinations import Destination


class DiscloserProvenance(StrEnum):
    """Who disclosed a span: the two values ADR-0146 §1 admits and no third.

    "Every span of content a component prepares for transmission across an egress
    boundary (ADR-0124 §1) has exactly one **discloser provenance**". There is no
    ``UNKNOWN`` member on purpose — an unrecorded origin is not a third state but
    :attr:`SYSTEM_SELECTED` (ADR-0146 §2), and a member standing for "not yet
    wired" is exactly the permissive default that clause exists to refuse.
    """

    USER_AUTHORED = "user_authored"
    """The user composed this span into the exchange being served (ADR-0146 §1)."""

    SYSTEM_SELECTED = "system_selected"
    """Every other case — including a span this system's model authored."""


class PayloadDescriptionError(ToolError):
    """A payload description cannot be derived for this call.

    ADR-0148 §1's third clause: "a description that cannot be derived — is
    **refused before the ruling**, and no ruling is sought for it."
    """


class UndescribedSpanError(PayloadDescriptionError):
    """The call would transmit a span the declaration does not cover (ADR-0148 §6).

    Its own type because it is the failure §6 singles out — "no approver is shown
    a description narrower than the payload" — and because ADR-0148 §14's
    omitted-span case asserts *this* refusal rather than a generic one.
    """


@dataclass(frozen=True, slots=True)
class SpanRef:
    """Where in a call's arguments one span sits.

    Provenance is "a property of a span, not of a message or a call" (ADR-0146
    §1), and an argument is not always one span: a recipient list carries one span
    per entry, and the mixed case — one address the user typed beside one the
    system chose — is the interesting one, exactly as ADR-0146 §1's assembled
    prompt is. So a span is identified by its argument *and* its position.

    Attributes:
        argument: The parameter the span sits in.
        index: Its position within a list-valued argument, or ``None`` where the
            argument's whole value is the span.
    """

    argument: str
    index: int | None = None


@dataclass(frozen=True, slots=True)
class SpanDescription:
    """What is said about one span: provenance, extent, and a tier or none.

    Attributes:
        span: Which span this describes.
        provenance: The carried discloser provenance (ADR-0146 §1, §2).
        characters: The span's extent, in Unicode code points. Code points rather
            than UTF-8 octets or grapheme clusters because it is what "N
            characters" means to the user reading the confirmation, and because
            it is a function of the value alone — an octet count would vary with
            an encoding choice nobody in the description records.
        tier: The tier the span's *field* establishes (ADR-0146 §5), or ``None``
            where no field establishes one. Never derived from the value: that is
            the inference ADR-0146 §2 forbids, and for a user-authored free-text
            span the absence is the whole point — "asserting Tier 1 would be
            asserting a fact nobody established".
    """

    span: SpanRef
    provenance: DiscloserProvenance
    characters: int
    tier: DataTier | None


@dataclass(frozen=True, slots=True)
class PayloadArgument:
    """One argument whose value the call transmits, and what its field establishes.

    Attributes:
        name: The parameter's name.
        establishes_tier: The tier every value this field can hold carries by what
            the field is for (ADR-0146 §5's first clause) — ``PERSONAL`` for a
            recipient address — or ``None`` where the field carries arbitrary text
            the user supplied, "however well the implementation knows what that
            field is for".
        multiple: Whether the value is a sequence, each entry its own span.
    """

    name: str
    establishes_tier: DataTier | None
    multiple: bool = False


def _checked_payload_name(member: PayloadArgument, tool_id: str) -> str:
    """Check one declared argument, and return the name it is keyed by.

    The ordering is adversarial round 8's: every member is checked before any of
    them is used, so an unhashable name reaches this refusal rather than a bare
    ``TypeError`` from ``set``. What it buys, and what it does not, is what
    :func:`~ai_assistant.tools.destination_arguments._checked_name` records — a
    caller who has silenced the type checker gets this package's refusal instead
    of an arbitrary Python error, and a declaration that is well-formed and wrong
    is still undetectable here (ADR-0148 §2, §8; ADR-0021 §1).

    Args:
        member: The entry to check.
        tool_id: The declaring tool, already checked, for the refusal's text.

    Returns:
        The argument's name.

    Raises:
        PayloadDescriptionError: If the entry is not a :class:`PayloadArgument`,
            has no usable name, or states an established tier that is not a
            :class:`~ai_assistant.core.types.DataTier`. No message renders the
            offending value.
    """
    argument: object = member
    if not isinstance(argument, PayloadArgument):
        msg = f"{tool_id}: a payload declaration holds transmitted arguments"
        raise PayloadDescriptionError(msg)
    name: object = argument.name
    if not isinstance(name, str) or not name:
        msg = f"{tool_id}: a transmitted argument has no name"
        raise PayloadDescriptionError(msg)
    tier: object = argument.establishes_tier
    if tier is not None and not isinstance(tier, DataTier):
        msg = (
            f"{tool_id}: a transmitted argument establishes something that is not a "
            f"data tier; ADR-0146 §5 admits a tier or none"
        )
        raise PayloadDescriptionError(msg)
    return name


@dataclass(frozen=True, slots=True)
class PayloadDeclaration:
    """Every argument one tool transmits, which is what "covers" is measured against.

    Attributes:
        tool_id: The ``ToolDefinition.id`` this declaration describes.
        arguments: The transmitted arguments, in the order the description lists
            them. Declaration order rather than the arguments' own iteration
            order, so the description is a function of the declaration and the
            values rather than of a mapping's insertion history.

    Raises:
        PayloadDescriptionError: If it names no argument, or names one twice.
    """

    tool_id: str
    arguments: tuple[PayloadArgument, ...]

    def __post_init__(self) -> None:
        """Refuse a declaration that could not describe a payload.

        Raises:
            PayloadDescriptionError: On an empty or duplicated declaration.
        """
        tool_id: object = self.tool_id
        if not isinstance(tool_id, str) or not tool_id:
            # Refused before it is rendered: every message below opens with it.
            msg = "a payload declaration names the tool it describes"
            raise PayloadDescriptionError(msg)
        # Snapshotted into a tuple **before** anything is checked, because a
        # `list` passed where the annotation says `tuple` leaves the caller
        # holding the container this type validated: replace an entry afterwards
        # and a declaration checked for one recipient set is used for another,
        # with no invariant re-run. Frozen protects the field, not the object the
        # field points at. Adversarial review found it on round 11.
        given: object = self.arguments
        if isinstance(given, str) or not isinstance(given, Sequence):
            msg = f"{tool_id}: a payload declaration holds a sequence of arguments"
            raise PayloadDescriptionError(msg)
        object.__setattr__(self, "arguments", tuple(given))
        if not self.arguments:
            msg = f"{tool_id}: a payload declaration names at least one argument"
            raise PayloadDescriptionError(msg)
        names = [_checked_payload_name(member, tool_id) for member in self.arguments]
        if len(set(names)) != len(names):
            msg = f"{tool_id}: a payload declaration names each argument once"
            raise PayloadDescriptionError(msg)


@dataclass(frozen=True, slots=True)
class EgressToolDeclaration:
    """One registered tool's whole declaration of what a call would transmit.

    The two halves are separate concepts — which arguments bear destinations is
    ADR-0148 §2's question and which spans are transmitted is §6's — and they are
    *bound into one value* so that no caller can pair one tool's recipients with
    another's payload. Adversarial review reached that pairing twice, from a
    different angle each time, which is what promoted it from a comparison inside
    :func:`describe_payload` to an invariant of a value: the halves are checked
    against each other **once, when the declaration is built**, so a tool whose
    declarations disagree does not load rather than describing a call wrongly at
    the moment one is made. That is ADR-0016 §1's own posture — "a tool that does
    not declare its reach does not load".

    **Where this stops, and why it stops there.** A caller can still construct a
    declaration that misdescribes its own tool: naming a body field as
    destination-bearing, or omitting a recipient field. Nothing in `tools/`
    detects that, and the corpus has already ruled why it does not have to.
    ADR-0148 §2's third clause calls it "a defect in the same class as a
    mis-declared ``discloses``", ADR-0148 §8 records that "nothing in ADR-0016
    detects a declaration that understates", and ADR-0021 §1 names the general
    shape: "a caller falsifying its own audit trail, not a policy subverting a
    gate, and no producer can prevent it". What *can* be prevented is two honest
    declarations being combined wrongly, and that is what this value does. The
    binding of a declaration to a registered tool is ADR-0148 §11's surface (b),
    which no lane may build against until its contract ADR has merged.

    Attributes:
        tool_id: The ``ToolDefinition.id`` both halves describe.
        payload: Every argument the call transmits.
        recipients: The destination-bearing subset of them (ADR-0148 §2).

    Raises:
        PayloadDescriptionError: If the halves name different tools, or if a
            destination-bearing argument is not one the payload declaration
            covers — a recipient transmitted and undescribed is the same defect
            as any other uncovered span (§6), and one wrong for every call that
            tool could make rather than for one.
    """

    tool_id: str
    payload: PayloadDeclaration
    recipients: DestinationDeclaration

    def __post_init__(self) -> None:
        """Check each field, then the two halves against each other, once.

        The fields are checked **before any of them is used or rendered**, which
        is the ordering the leaf declarations already keep and which adversarial
        review found missing here on round 9 — the wrapper being the type this
        lane added last, at round 3, and so the one the earlier sweep did not
        reach. What such a check buys and what it does not is recorded on
        :func:`_checked_payload_name`; the line this type keeps is the same one:
        a *declaration* is the tool author's text and may be named once it is
        known to be text, while a call's arguments and a carried provenance key
        are not and are never named.

        Raises:
            PayloadDescriptionError: If a field is malformed, if the halves are
                not both this tool's, or if a destination-bearing argument is not
                covered by the payload declaration.
        """
        tool_id: object = self.tool_id
        if not isinstance(tool_id, str) or not tool_id:
            msg = "an egress declaration names the tool it describes"
            raise PayloadDescriptionError(msg)
        payload: object = self.payload
        recipients: object = self.recipients
        if not isinstance(payload, PayloadDeclaration) or not isinstance(
            recipients, DestinationDeclaration
        ):
            msg = f"{tool_id}: an egress declaration holds a payload half and a recipient half"
            raise PayloadDescriptionError(msg)
        for half, name in ((payload.tool_id, "payload"), (recipients.tool_id, "recipient")):
            if half != tool_id:
                msg = f"{tool_id}: the {name} declaration is {half}'s, not this tool's"
                raise PayloadDescriptionError(msg)
        covered = {argument.name for argument in payload.arguments}
        bearing = {argument.name for argument in recipients.arguments}
        if not bearing <= covered:
            msg = (
                f"{tool_id}: {', '.join(sorted(bearing - covered))} bears destinations "
                f"and is not covered by the payload declaration"
            )
            raise PayloadDescriptionError(msg)


@dataclass(frozen=True, slots=True)
class PayloadDescription:
    """The whole account of one call's payload (ADR-0148 §6).

    Attributes:
        tool_id: The tool the description was derived for. Part of the value
            because §6 makes the registry's definition for the **bound** tool one
            of the description's three inputs, so a description handed to a
            different tool is detectably not that tool's.
        destinations: Every recipient the call selects, each in both its supplied
            and its canonical form (ADR-0148 §2's fourth clause). Occurrences
            rather than the de-duplicated set, so the alias case survives:
            ADR-0148 §14 fails "an implementation that records only the canonical
            form, and so does one that reconstructs a supplied form from it".
        spans: One entry per span the call transmits, in declaration order and
            then in the order the argument carried them.
    """

    tool_id: str
    destinations: tuple[Destination, ...]
    spans: tuple[SpanDescription, ...]


def _spans_of(argument: PayloadArgument, value: FrozenJson) -> tuple[tuple[SpanRef, str], ...]:
    """Split one argument's value into the spans it transmits.

    Args:
        argument: The declared argument.
        value: Its value in the call's parameters.

    Returns:
        Each span's reference beside the text it carries.

    Raises:
        PayloadDescriptionError: If the value is not text, or not a sequence of
            text where the declaration says it is a sequence. A non-text argument
            has no extent this seam will state, and stating one anyway — a
            rendered number's digit count, say — would be describing a span by
            guessing at how it will be serialised.
    """
    where = f"argument {argument.name!r}"
    if argument.multiple:
        # `str` is a `Sequence`; iterating one would make a span per character.
        if isinstance(value, str) or not isinstance(value, Sequence):
            msg = f"{where} is declared as a list of spans"
            raise PayloadDescriptionError(msg)
        spans: list[tuple[SpanRef, str]] = []
        for index, entry in enumerate(value):
            if not isinstance(entry, str):
                msg = f"{where} entry {index} is not text, so it has no described extent"
                raise PayloadDescriptionError(msg)
            spans.append((SpanRef(argument=argument.name, index=index), entry))
        return tuple(spans)
    if not isinstance(value, str):
        msg = f"{where} is not text, so it has no described extent"
        raise PayloadDescriptionError(msg)
    return ((SpanRef(argument=argument.name), value),)


def _checked_provenance(
    provenance: Mapping[SpanRef, DiscloserProvenance], declaration: EgressToolDeclaration
) -> dict[SpanRef, DiscloserProvenance]:
    """Check every carried entry before any of it reaches a description or a message.

    The annotation says :class:`SpanRef` to :class:`DiscloserProvenance`; a mapping
    arriving at run time says whatever it holds. That gap matters here more than it
    usually does, because the value being carried is the one ADR-0146 §2 makes
    fail-closed: a span with **no** recorded origin is system-selected, and an
    unrecognised value slipping through would be a third state the description
    records and no clause admits — the permissive default arriving by a different
    door. So it is checked, in the idiom `tools/registry.py` already uses for
    ``checked_timeout`` and ADR-0026 §2 for an injected clock. Adversarial review
    found it on round 4.

    Refused rather than defaulted, because a malformed entry is not "no origin was
    recorded" — it is a caller whose wiring is wrong, and ADR-0148 §1's third
    clause refuses a description that cannot be derived rather than deriving a
    plausible one.

    **The key is checked against the declaration before any part of it is named,**
    which is round 5's finding and the reason this function takes the declaration
    rather than the tool's id. ``SpanRef.argument`` is caller-supplied too, so a
    refusal that interpolated it would put arbitrary text — Tier 1 content
    included — into a message bound for a log, which is the leak `core/logging.py`
    names and `tools/invocation.py` declines to make with ``str(exc)``. An argument
    name that the *declaration* holds is safe to name, because the tool's author
    wrote it; anything else gets a fixed diagnostic and no interpolation at all.
    Once past this function every key names a declared argument, which is what
    makes the later refusals safe to be specific.

    Args:
        provenance: The carried mapping, as given.
        declaration: The bound tool's declaration, which supplies both the id for
            the refusal's text and the argument names a key may name.

    Returns:
        The same mapping, with every key and value checked.

    Raises:
        PayloadDescriptionError: If a key is not a :class:`SpanRef`, does not name
            an argument the payload declaration holds, or carries a position that
            is not an index; or if a value is not a :class:`DiscloserProvenance`.
    """
    tool_id = declaration.tool_id
    declared = {argument.name for argument in declaration.payload.arguments}
    checked: dict[SpanRef, DiscloserProvenance] = {}
    for key, value in provenance.items():
        span: object = key
        recorded: object = value
        if not isinstance(span, SpanRef):
            msg = f"{tool_id}: carried provenance is keyed by something that is not a span"
            raise PayloadDescriptionError(msg)
        argument: object = span.argument
        if not isinstance(argument, str) or argument not in declared:
            msg = (
                f"{tool_id}: carried provenance names an argument this tool does not "
                f"declare; it is not named here because it is not the tool author's text"
            )
            raise PayloadDescriptionError(msg)
        index: object = span.index
        if index is not None and (isinstance(index, bool) or not isinstance(index, int)):
            msg = f"{tool_id}: the provenance carried for {argument!r} has no usable position"
            raise PayloadDescriptionError(msg)
        if not isinstance(recorded, DiscloserProvenance):
            msg = (
                f"{tool_id}: the provenance carried for {argument!r} is not one of "
                f"the two states ADR-0146 §1 admits"
            )
            raise PayloadDescriptionError(msg)
        checked[span] = recorded
    return checked


def describe_payload(
    declaration: EgressToolDeclaration,
    parameters: Mapping[str, FrozenJson],
    *,
    provenance: Mapping[SpanRef, DiscloserProvenance],
) -> PayloadDescription:
    """Derive the description of what this call would transmit.

    Deterministic over ADR-0148 §6's three inputs and nothing else: the call's
    arguments, the provenance carried for their spans, and the tool's own
    declaration — which is what "the registry's definition for the bound tool"
    supplies to this derivation, namely which arguments are transmitted, which of
    them bear destinations, and what each field establishes.

    **The destinations are derived here rather than accepted from the caller,**
    and that is the repair for a real defect an earlier draft carried. Taking them
    as an argument left the description a function of the arguments *plus an
    independent value*, so a caller could hand over an empty tuple, or one naming
    a recipient the arguments never selected, and get back a description that
    passed every check in this module. That contradicts §6 in two places at once:
    "two derivations of the description for one request agree" — they would not —
    and the whole reason determinism is required, that the description is one "the
    approver, the seam and a later auditor can each re-derive and compare". A
    value nobody else can reproduce is exactly the "second, divergent account of
    the call" §6's determinism clause exists to prevent. Adversarial review found
    it on round 1, and rounds 2 and 3 walked the same defect down into the pair of
    declarations, which is why they now arrive as one checked value
    (:class:`EgressToolDeclaration`) rather than as two arguments this function
    compares.

    Args:
        declaration: The bound tool's declaration, whose halves were checked
            against each other when it was built.
        parameters: The call's arguments.
        provenance: The recorded origin of each span. A span absent from it is
            ``SYSTEM_SELECTED`` (ADR-0146 §2) — the fail-closed default, never a
            reason to inspect the value.

    Returns:
        The description, whose spans are in declaration order.

    Raises:
        UndescribedSpanError: If ``parameters`` carries an argument the
            declaration does not name — the span would be transmitted and not
            covered (ADR-0148 §6, §14).
        DestinationSelectionError: If the destinations cannot be read and
            canonicalised out of ``parameters`` (ADR-0148 §1's third clause).
        PayloadDescriptionError: If an argument's value is not text or a list of
            text, if a carried provenance entry is malformed or names an argument
            this tool does not declare, or if ``provenance`` names a span this call
            does not transmit.
            The last is refused rather than ignored: a carried provenance for a
            span that is not there means the caller and this derivation disagree
            about what the payload is, and the disagreement is exactly what a
            silent drop would hide.
    """
    carried = _checked_provenance(provenance, declaration)
    declared = {argument.name: argument for argument in declaration.payload.arguments}
    undescribed = set(parameters) - set(declared)
    if undescribed:
        # The count and the *declared* names, never the undeclared keys. This is
        # the one place `tools/builtin.py`'s `_reject_unknown` precedent does not
        # reach, and the difference is when each runs: that one is inside a
        # callable, so ADR-0145 has already refused an argument outside the
        # schema's `additionalProperties: false` and an unexpected key cannot be
        # there. This runs **before** the request is built (ADR-0148 §1), so the
        # keys are whatever produced them, and a key is a string a model can write
        # as freely as a value. Adversarial review found it on round 6.
        msg = (
            f"{declaration.tool_id}: {len(undescribed)} argument(s) would be "
            f"transmitted and are not covered by the payload declaration, which "
            f"covers {', '.join(sorted(declared))}"
        )
        raise UndescribedSpanError(msg)

    spans: list[SpanDescription] = []
    for argument in declaration.payload.arguments:
        if argument.name not in parameters:
            continue
        for span, text in _spans_of(argument, parameters[argument.name]):
            spans.append(
                SpanDescription(
                    span=span,
                    provenance=carried.get(span, DiscloserProvenance.SYSTEM_SELECTED),
                    characters=len(text),
                    tier=argument.establishes_tier,
                )
            )

    unknown = sorted(
        f"{span.argument}[{span.index}]" if span.index is not None else span.argument
        for span in set(carried) - {described.span for described in spans}
    )
    if unknown:
        msg = (
            f"{declaration.tool_id}: provenance was carried for {', '.join(unknown)}, "
            f"which this call does not transmit"
        )
        raise PayloadDescriptionError(msg)

    return PayloadDescription(
        tool_id=declaration.tool_id,
        destinations=select_destinations(declaration.recipients, parameters),
        spans=tuple(spans),
    )


__all__ = [
    "DiscloserProvenance",
    "EgressToolDeclaration",
    "PayloadArgument",
    "PayloadDeclaration",
    "PayloadDescription",
    "PayloadDescriptionError",
    "SpanDescription",
    "SpanRef",
    "UndescribedSpanError",
]
