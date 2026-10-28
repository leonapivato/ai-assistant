"""The observer's reply shapes: each step's reply as a closed shape (ADR-0354 §9:1, §9:7).

Every step's call, the scout's, framing's and placement's alike, is one structured call
with the shape this module gives it, and its reply is read by ``core``'s one rule alone
(ADR-0354 §3:4): nothing here reads a reply's text. A reply the rule refuses is no
proposal, never a partial one: the attempt fails and is retried (ADR-0329 §16:4).

**Today's types, restated.** Each shape is a subclass of the type the step's reader reads,
:class:`~ai_assistant.orchestration.observer.scout.ScoutReply`,
:class:`~ai_assistant.orchestration.observer.scout.PersonScoutReply`,
:class:`~ai_assistant.orchestration.observer.framing.FramingReply` or
:class:`~ai_assistant.orchestration.observer.placement.PlacementReply`, so a value is that
type and goes to its reader as it is, and the reader runs the checks it runs today. Six of
their fields hold an open value, any JSON at all, whose schema admits anything and could not
be closed (§2:3): the scout's ``narrowing`` and, under the person flag, ``restates`` and
``suggestions``; framing's ``style`` and ``pin``; and placement's ``answers``. Each shape
restates them as named properties, the ones the step's prompt describes (§9:7), so the
schema sent is closed at every depth. The field still holds what the reply wrote, as
today, so a reader that sets one malformed entry aside, or reads a narrowing failing
closed, does so as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Final

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, WithJsonSchema

from ai_assistant.core.types import ProfileField
from ai_assistant.orchestration.observer.framing import FramingReply, _FramedMemory
from ai_assistant.orchestration.observer.placement import PlacementReply
from ai_assistant.orchestration.observer.scout import (
    PersonScoutReply,
    ScoutReply,
    _PersonProposedFinding,
    _ProposedFinding,
)

if TYPE_CHECKING:
    from pydantic.json_schema import JsonSchemaValue

__all__ = [
    "FramingReplyShape",
    "PersonScoutReplyShape",
    "PlacementReplyShape",
    "ScoutReplyShape",
]


# --- what the prompts describe for each open value ------------------------------------


class _Narrowing(BaseModel):
    """A finding's narrowing as the scout's prompt writes it: ``{"reach", "note"}``."""

    model_config = ConfigDict(frozen=True)
    reach: str
    note: str


class _Setting(BaseModel):
    """A setting a finding only restates, as the scout's prompt writes it (ADR-0338 §9:3)."""

    model_config = ConfigDict(frozen=True)
    field: ProfileField
    value: str


class _Suggestion(BaseModel):
    """A field suggestion as the scout's prompt writes it (ADR-0338 §9:2)."""

    model_config = ConfigDict(frozen=True)
    field: ProfileField
    value: str
    part: str


class _Answer(BaseModel):
    """The open question a new memory answers, as placement's prompt writes it (§6:2)."""

    model_config = ConfigDict(frozen=True)
    memory: str
    question: str


def _restated(form: object) -> WithJsonSchema:
    """The schema of ``form``, every reference inlined, standing in for an open value's.

    The value is validated as it is today, any JSON; only the schema sent is this one, which
    :func:`~ai_assistant.core.reply_shapes.reply_schema` closes and strips of text (§3:2).
    """
    schema = TypeAdapter(form).json_schema()
    definitions = schema.pop("$defs", {})

    def inlined(value: JsonSchemaValue | list[object] | object) -> object:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                return inlined(definitions[reference.removeprefix("#/$defs/")])
            return {key: inlined(held) for key, held in value.items()}
        if isinstance(value, list):
            return [inlined(held) for held in value]
        return value

    restated = inlined(schema)
    assert isinstance(restated, dict)  # noqa: S101 — a type's schema is an object
    return WithJsonSchema(restated)


#: The scout's ``narrowing``: one object or null (ADR-0346 §4:2).
_NARROWING: Final = _restated(_Narrowing | None)
#: The scout's ``restates``, under the person flag: one setting or null (ADR-0338 §9:3).
_RESTATES: Final = _restated(_Setting | None)
#: The scout's ``suggestions``, under the person flag: a list of them, or null (§9:2).
_SUGGESTIONS: Final = _restated(tuple[_Suggestion, ...] | None)
#: Framing's ``style`` and ``pin``, under the person flag: true, false or null (§9:4-§9:5).
_JUDGED: Final = _restated(bool | None)
#: Placement's ``answers``: one object naming a memory and its question, or null (§6:2).
_ANSWERS: Final = _restated(_Answer | None)


# --- the shapes ---------------------------------------------------------------------


class _ScoutFinding(_ProposedFinding):
    narrowing: Annotated[JsonValue, _NARROWING] = None


class ScoutReplyShape(ScoutReply):
    """The scout's reply shape (ADR-0346 §4), its ``narrowing`` restated (§9:7)."""

    findings: tuple[_ScoutFinding, ...] = ()


class _PersonScoutFinding(_PersonProposedFinding):
    narrowing: Annotated[JsonValue, _NARROWING] = None
    restates: Annotated[JsonValue, _RESTATES] = None


class PersonScoutReplyShape(PersonScoutReply):
    """The scout's reply shape under the person flag (ADR-0338 §9:1-§9:3), restated (§9:7)."""

    findings: tuple[_PersonScoutFinding, ...] = ()
    suggestions: Annotated[JsonValue, _SUGGESTIONS] = None


class _FramedMemoryShape(_FramedMemory):
    style: Annotated[JsonValue, _JUDGED] = None
    pin: Annotated[JsonValue, _JUDGED] = None


class FramingReplyShape(FramingReply):
    """Framing's reply shape (ADR-0346 §5:2), its ``style`` and ``pin`` restated (§9:7)."""

    memories: tuple[_FramedMemoryShape, ...] = ()


class PlacementReplyShape(PlacementReply):
    """Placement's reply shape (ADR-0346 §6:2), its ``answers`` restated (§9:7)."""

    answers: Annotated[JsonValue, _ANSWERS] = None
