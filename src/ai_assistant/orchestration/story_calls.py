"""Planning's story calls that write, from a start to a grouping.

Start, note, link, unlink, tidy-up, move, merge, split and group: ADR-0300 §10:2-§10:6,
ADR-0303 §9:1-§9:4, ADR-0306 §3, ADR-0307 §5. Planning chooses each of these calls,
authorizing checks it by rule, and acting runs it (ADR-0300 §10:5). Each is an
**inside action** (ADR-0292 §12:1): its effect is the assistant's own records, it never
leaves the hub, it returns nothing and its outcome is never unknown. Acting reaches the
runner, :class:`StoryCalls`, through its own-records seam and never through
``ToolInvoker`` (ADR-0306 §3:3).

**Three parts, one module**, as :mod:`~ai_assistant.orchestration.remembering` is: the
declarations (:data:`STORY_CALLS`), which of their arguments name things by label
(:data:`STORY_LABEL_ARGUMENTS`), and the runner, which also makes the hub's check of a
move or a split before it is authorized (:meth:`StoryCalls.refusal`). The read of a
story's page is a later lane's.

| Call | Takes | Safe to repeat |
| --- | --- | --- |
| :data:`START_STORY` | its first notes; optionally the story it sits inside | No |
| :data:`NOTE_STORY` | a story, and the note | Yes |
| :data:`LINK_STORY` | a story, and this activation, an activation or a story | Yes |
| :data:`UNLINK_STORY` | a story, and this activation, an activation or a story it holds | Yes |
| :data:`TIDY_STORY` | a story | Yes |
| :data:`MOVE_STORY` | the story moved from, the story moved to, episodes, notes | Yes |
| :data:`MERGE_STORY` | the story absorbed, and the story it joins | Yes |
| :data:`SPLIT_STORY` | the story, the episodes and stories that leave, notes | Yes |
| :data:`GROUP_STORY` | the stories grouped; optionally the larger story's first notes | No |

**Stories are named by label** (ADR-0307 §5). Planning writes an ``S`` label where a
call names a story and an ``E`` label where it names another activation, by its
episode; planning's own check maps each to the id it names before authorizing, and
refuses whole a call naming a label it was never shown (§5:3), so the runner is handed
ids. A link or an unlink naming neither a story nor an episode names this activation.
The notes a move or a split carries are named by the ``N`` labels planning's story view
renders (ADR-0303 §9:4, ADR-0307 §5:5), each the note's id as text.

**A move or a split naming a note not held is refused whole, twice over** (ADR-0307
§5:3-§5:4). Before authorizing, :meth:`StoryCalls.refusal` checks each note it names
against the story it moves from as the stories stand then, and the phases' glue refuses
the call with the reason, so it runs nothing and brings a round. Then the store refuses
such a call again inside its own transaction (``note_not_held``), since the call's actor
is ``planning``, so a note moved away between the two, by another call of the round or by
the matters pass, still refuses the whole call. **On a pass that may not show a record
placed for the owner alone, a move or a split carries members only** (§6:5): the same
check refuses one naming notes, with the reason, and planning may make it again without
them.

**What the hub fills** (ADR-0254 §3, ADR-0306 §2:10). Under the names remembering gives
them, so authorizing fills them as it fills remembering's: ``episode``, the address of
this activation's episode, which every call but the tidy-up takes; and
``rests_on_outside_content``, whether this activation's record says it has read outside
content when the round was authorized (ADR-0306 §4:5), which a call writing a note
takes. Authorizing computes it from :mod:`~ai_assistant.orchestration.outside_content`'s
rules, the one place outside content is counted, and it is the **note's mark**: a note
planning writes in an activation that has read outside content is marked, by the hub's
record and never by planning's judgment (ADR-0303 §3:1, §9:3). The duplicate backstop
never compares either (ADR-0306 §2:10), so two identical starts are one start's values.

**Start is not safe to repeat** (ADR-0306 §3:1). Its call gets an effect record, and
acting's duplicate backstop refuses a second identical start in the matter as already
done (§5:9). It creates the story with this activation as its member (ADR-0300 §10:3),
writes its first notes, and, where it names one, links it into the story it sits inside.
Everything it names is checked first, so a start naming a story that is not there
starts nothing. **A start is not reported not done once its story exists**: where its
first notes or its place cannot then be written, the runner raises
:class:`StartUnfinishedError` and acting leaves its effect record unfinished, which the
backstop counts as done and nobody reports as done (§5:6, §5:11).

**Merged stories are followed, never written** (ADR-0289 §3). A story a call names that
has been merged since planning was shown it is followed to the story it was merged into,
whose members and notes it now holds; a member story a split or a group names is followed
too. **The story a merge absorbs is the exception**: it is named as it is, so a merge
repeated after the first, or naming a story merged elsewhere since, is refused by the
store as ``merged_story`` and changes nothing (ADR-0303 §9's table), rather than merging
whatever that story went into.

**A group starts a story, as a start does** (ADR-0303 §9). It is not safe to repeat, so
acting's backstop refuses a second identical grouping as already done; it creates the
larger story holding the stories named, then writes its first notes, and once that story
exists it is never reported not done (:class:`StartUnfinishedError`). A split starts one
too, in the store's one transaction, so nothing of it can be left half written.

**The tidy-up** (ADR-0307 §7, ADR-0300 §10:4) runs :class:`~ai_assistant.orchestration.
story_tidy_up.StoryTidyUp` on the story, and its outcome is what that operation wrote to
the story's version log, never the episode. That nothing waits for it, the next round
and the activation's end included, is the phases' glue's to keep: it starts this call
on its own and does not await it (ADR-0306 §3:3, ADR-0307 §7:2).

**Who wrote it, and on whose behalf.** Every write is made with the actor ``planning``
and this activation as its trigger (ADR-0300 §3:15), and every note by the author
``planning``, recording the activation it was written during (ADR-0303 §4:7, §9:3).

**Planning still writes on an owner-only pass.** On a pass that may not show a record
placed for the owner alone, planning can still write notes and change stories (ADR-0307
§6:5); only a move or a split is held to members alone there, as above.

**It logs stage and code-owned reason only**, never a note or a story (ADR-0275 §8).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import MemoryStoreError, StoryStoreError
from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    STORY_NOTE_MAX_CHARS,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    LabelKind,
    Reversibility,
    RiskLevel,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.remembering import EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT
from ai_assistant.orchestration.stories import episode_address, unknown_activation
from ai_assistant.orchestration.story_tidy_up import TidyUpResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.protocols import MemoryStore, StoryStore
    from ai_assistant.core.types import FrozenJson, ProposedCall, StoryOutcome, ToolCall
    from ai_assistant.orchestration.story_tidy_up import StoryTidyUp

__all__ = [
    "EPISODES_ARGUMENT",
    "GROUP_STORY",
    "GROUP_STORY_CAPABILITY",
    "INSIDE_ARGUMENT",
    "INTO_ARGUMENT",
    "LINK_STORY",
    "LINK_STORY_CAPABILITY",
    "MEMBER_EPISODE_ARGUMENT",
    "MEMBER_STORY_ARGUMENT",
    "MERGE_STORY",
    "MERGE_STORY_CAPABILITY",
    "MOVE_STORY",
    "MOVE_STORY_CAPABILITY",
    "NOTES_ARGUMENT",
    "NOTE_ARGUMENT",
    "NOTE_STORY",
    "NOTE_STORY_CAPABILITY",
    "SPLIT_STORY",
    "SPLIT_STORY_CAPABILITY",
    "START_NOTES_MAX",
    "START_STORY",
    "START_STORY_CAPABILITY",
    "STORIES_ARGUMENT",
    "STORY_ARGUMENT",
    "STORY_CALLS",
    "STORY_CALL_CAPABILITIES",
    "STORY_LABEL_ARGUMENTS",
    "TIDY_STORY",
    "TIDY_STORY_CAPABILITY",
    "TO_ARGUMENT",
    "UNLINK_STORY",
    "UNLINK_STORY_CAPABILITY",
    "StartUnfinishedError",
    "StoryCalls",
]

_log = structlog.get_logger(__name__)

#: The capabilities, each the id of its one declaration.
START_STORY_CAPABILITY: Final = "start_story"
NOTE_STORY_CAPABILITY: Final = "note_story"
LINK_STORY_CAPABILITY: Final = "link_story"
UNLINK_STORY_CAPABILITY: Final = "unlink_story"
TIDY_STORY_CAPABILITY: Final = "tidy_story"
MOVE_STORY_CAPABILITY: Final = "move_story"
MERGE_STORY_CAPABILITY: Final = "merge_stories"
SPLIT_STORY_CAPABILITY: Final = "split_story"
GROUP_STORY_CAPABILITY: Final = "group_stories"

#: The argument naming the story a call writes to, by its ``S`` label.
STORY_ARGUMENT: Final = "story"

#: A note call's note.
NOTE_ARGUMENT: Final = "note"

#: A start's or a group's first notes, as text; the notes a move or a split carries,
#: by their ``N`` labels.
NOTES_ARGUMENT: Final = "notes"

#: The story a move goes to, by its ``S`` label.
TO_ARGUMENT: Final = "to"

#: The story a merge joins, by its ``S`` label.
INTO_ARGUMENT: Final = "into"

#: The activations a move or a split carries, by their episodes' ``E`` labels.
EPISODES_ARGUMENT: Final = "episodes"

#: The member stories a split carries, or the stories a group puts under a new one, by
#: their ``S`` labels.
STORIES_ARGUMENT: Final = "stories"

#: The story a start sits inside, by its ``S`` label.
INSIDE_ARGUMENT: Final = "inside"

#: The story a link or an unlink names as the member, by its ``S`` label.
MEMBER_STORY_ARGUMENT: Final = "member_story"

#: The activation a link or an unlink names as the member, by its episode's ``E`` label.
MEMBER_EPISODE_ARGUMENT: Final = "member_episode"

#: The most first notes one start carries. The page's tidy-up condenses them, so this
#: bounds one call rather than the page; several matters are several starts.
START_NOTES_MAX: Final = 8

_EPISODE_PREFIX: Final = episode_address("")

_NOTE_SCHEMA: Final[dict[str, FrozenJson]] = {
    "type": "string",
    "minLength": 1,
    "maxLength": STORY_NOTE_MAX_CHARS,
}

_STORY_SCHEMA: Final[dict[str, FrozenJson]] = {
    "type": "string",
    "minLength": 1,
    "description": "The story, by the S label you were shown it under.",
}


def _labels(description: str, *, min_items: int = 0) -> dict[str, FrozenJson]:
    """An argument naming several things by their labels."""
    schema: dict[str, FrozenJson] = {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
        "uniqueItems": True,
        "description": description,
    }
    if min_items:
        schema["minItems"] = min_items
    return schema


_CARRIED_NOTES: Final = _labels(
    "The story's notes that go with it, by their N labels; each must be on the story it "
    "leaves. Name none to leave every note where it is."
)


def _declared(  # noqa: PLR0913 — one keyword per property a story call varies
    capability: str,
    description: str,
    *,
    properties: Mapping[str, FrozenJson],
    required: tuple[str, ...],
    system_supplied: tuple[str, ...],
    safe_to_repeat: bool,
    idempotency: Idempotency,
) -> ToolDefinition:
    """One story call's declaration, the class's five properties as ADR-0306 §3:1 rules.

    - ``effect=OWN_RECORDS``, ``leaves_hub=False``, ``result=NONE`` and
      ``outcome_can_be_unknown=False``: §3:1, for every story call that writes.
    - ``side_effecting=True`` with ``writes=(PERSONAL,)``: it writes the assistant's
      records of the user's matters, which ADR-0306 §2:5 requires of an effect that is
      not none; ``reads=(PERSONAL,)`` for the stories it reads first.
    - ``reversibility=RECOVERABLE``: a story change can be undone by another change,
      and a note is never removed.
    - ``risk_level=LOW``, ``discloses=()``, ``cost=FREE``: nothing leaves the device and
      nothing is spent.
    """
    schema: dict[str, FrozenJson] = {
        "type": "object",
        "properties": dict(properties),
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return ToolDefinition(
        id=capability,
        capability=capability,
        description=description,
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.RECOVERABLE,
        side_effecting=True,
        reads=(DataTier.PERSONAL,),
        writes=(DataTier.PERSONAL,),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=idempotency,
        effect=CapabilityEffect.OWN_RECORDS,
        leaves_hub=False,
        result=CapabilityResult.NONE,
        outcome_can_be_unknown=False,
        safe_to_repeat=safe_to_repeat,
        system_supplied=system_supplied,
        parameters_schema=schema,
    )


_EPISODE_FILLED: Final[dict[str, FrozenJson]] = {"type": "string", "minLength": 1}
_MARK_FILLED: Final[dict[str, FrozenJson]] = {"type": "boolean"}

_MEMBER_PROPERTIES: Final[dict[str, FrozenJson]] = {
    STORY_ARGUMENT: _STORY_SCHEMA,
    MEMBER_STORY_ARGUMENT: {
        "type": "string",
        "minLength": 1,
        "description": "A story as the member, by its S label. Name this or member_episode.",
    },
    MEMBER_EPISODE_ARGUMENT: {
        "type": "string",
        "minLength": 1,
        "description": (
            "An activation as the member, by its episode's E label. Name this or "
            "member_story; name neither for this activation."
        ),
    },
    EPISODE_ARGUMENT: _EPISODE_FILLED,
}

START_STORY: Final = _declared(
    START_STORY_CAPABILITY,
    (
        "Start a story when someone takes up a matter that will come up again, with "
        "its first notes. This activation joins it. Name the story it sits inside, if "
        "the person frames it so."
    ),
    properties={
        NOTES_ARGUMENT: {
            "type": "array",
            "items": _NOTE_SCHEMA,
            "minItems": 1,
            "maxItems": START_NOTES_MAX,
            "description": "The story's first notes: what the matter is, and what is open.",
        },
        INSIDE_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "description": "The larger story it sits inside, by its S label.",
        },
        EPISODE_ARGUMENT: _EPISODE_FILLED,
        OUTSIDE_CONTENT_ARGUMENT: _MARK_FILLED,
    },
    required=(NOTES_ARGUMENT, EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT),
    system_supplied=(EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT),
    safe_to_repeat=False,
    idempotency=Idempotency.NONE,
)
"""Start a story (ADR-0300 §10:3): not safe to repeat, so acting's backstop refuses a
second identical start in the matter as already done (ADR-0306 §3:1, §5:9)."""

NOTE_STORY: Final = _declared(
    NOTE_STORY_CAPABILITY,
    (
        "Write a note on a story's page: what its records cannot show and the matter "
        "needs, such as what is open, what you are waiting on, who will do what, why "
        "something was decided, or what comes next. Your text outside a call stays "
        "with this episode and never reaches a story."
    ),
    properties={
        STORY_ARGUMENT: _STORY_SCHEMA,
        NOTE_ARGUMENT: {**_NOTE_SCHEMA, "description": "The note, as it should read later."},
        EPISODE_ARGUMENT: _EPISODE_FILLED,
        OUTSIDE_CONTENT_ARGUMENT: _MARK_FILLED,
    },
    required=(STORY_ARGUMENT, NOTE_ARGUMENT, EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT),
    system_supplied=(EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT),
    safe_to_repeat=True,
    idempotency=Idempotency.NONE,
)
"""Write a note on a story (ADR-0300 §10:2, ADR-0303 §9:3), safe to repeat as ruled."""

LINK_STORY: Final = _declared(
    LINK_STORY_CAPABILITY,
    (
        "Link this activation, another activation or a story into a story, where it "
        "belongs to that matter."
    ),
    properties=_MEMBER_PROPERTIES,
    required=(STORY_ARGUMENT, EPISODE_ARGUMENT),
    system_supplied=(EPISODE_ARGUMENT,),
    safe_to_repeat=True,
    idempotency=Idempotency.NATURAL,
)
"""Link to a story (ADR-0300 §10:3): a member already there is passed over."""

UNLINK_STORY: Final = _declared(
    UNLINK_STORY_CAPABILITY,
    (
        "Remove this activation, another activation or a story from a story it is in, "
        "where it does not belong to that matter. Do it only where someone asked for "
        "it, or the work in hand needs it now."
    ),
    properties=_MEMBER_PROPERTIES,
    required=(STORY_ARGUMENT, EPISODE_ARGUMENT),
    system_supplied=(EPISODE_ARGUMENT,),
    safe_to_repeat=True,
    idempotency=Idempotency.NATURAL,
)
"""Unlink from a story (ADR-0303 §9:1): a member the story no longer holds is passed
over, and no note moves (§6:4)."""

TIDY_STORY: Final = _declared(
    TIDY_STORY_CAPABILITY,
    (
        "Tidy a story's summary: rewrite it from its notes and episodes since it was "
        "last tidied. Do it only where someone asked for it, or the work in hand "
        "needs it now. It runs on its own, brings no further round, and how it went "
        "is not shown to you. A tidy-up reads only what came since the last, so after "
        "moving a note away, tidy the story it left so its summary drops it."
    ),
    properties={STORY_ARGUMENT: _STORY_SCHEMA},
    required=(STORY_ARGUMENT,),
    system_supplied=(),
    safe_to_repeat=True,
    idempotency=Idempotency.NATURAL,
)
"""Tidy a story's page (ADR-0300 §10:4, ADR-0307 §7): planning's choice, never added by
rule."""

MOVE_STORY: Final = _declared(
    MOVE_STORY_CAPABILITY,
    (
        "Move activations, notes, or both, from one story to another, where they "
        "belong to the other matter. Do it only where someone asked for it, or the "
        "work in hand needs it now. It carries only the notes you name by their N "
        "labels, each on the story it leaves; one naming a note that story does not "
        "hold is refused whole. To move something a story's summary holds, read the "
        "story, find the note it came from, if one did, and name that note rather "
        "than restating it as a new note; then note on the story it left where that "
        "went, and tidy that story."
    ),
    properties={
        STORY_ARGUMENT: {**_STORY_SCHEMA, "description": "The story they leave, by its S label."},
        TO_ARGUMENT: {**_STORY_SCHEMA, "description": "The story they go to, by its S label."},
        EPISODES_ARGUMENT: _labels("The activations that go, by their episodes' E labels."),
        NOTES_ARGUMENT: _CARRIED_NOTES,
        EPISODE_ARGUMENT: _EPISODE_FILLED,
    },
    required=(STORY_ARGUMENT, TO_ARGUMENT, EPISODE_ARGUMENT),
    system_supplied=(EPISODE_ARGUMENT,),
    safe_to_repeat=True,
    idempotency=Idempotency.NATURAL,
)
"""Move members (ADR-0303 §9:1): a repeat names members the first story no longer holds
and is refused, changing nothing."""

MERGE_STORY: Final = _declared(
    MERGE_STORY_CAPABILITY,
    (
        "Merge one story into another when they are one matter: its activations, "
        "stories and every note join the other. Do it only where someone asked for "
        "it, or the work in hand needs it now."
    ),
    properties={
        STORY_ARGUMENT: {**_STORY_SCHEMA, "description": "The story absorbed, by its S label."},
        INTO_ARGUMENT: {**_STORY_SCHEMA, "description": "The story it joins, by its S label."},
        EPISODE_ARGUMENT: _EPISODE_FILLED,
    },
    required=(STORY_ARGUMENT, INTO_ARGUMENT, EPISODE_ARGUMENT),
    system_supplied=(EPISODE_ARGUMENT,),
    safe_to_repeat=True,
    idempotency=Idempotency.NATURAL,
)
"""Merge stories (ADR-0303 §9:1): a repeat names a merged story and is refused, changing
nothing."""

SPLIT_STORY: Final = _declared(
    SPLIT_STORY_CAPABILITY,
    (
        "Split activations or stories off a story into a new story of their own, "
        "where they are a matter apart. Do it only where someone asked for it, or the "
        "work in hand needs it now. It carries only the notes you name by their N "
        "labels, each on the story it leaves; one naming a note that story does not "
        "hold is refused whole."
    ),
    properties={
        STORY_ARGUMENT: {**_STORY_SCHEMA, "description": "The story split, by its S label."},
        EPISODES_ARGUMENT: _labels("The activations that leave, by their episodes' E labels."),
        STORIES_ARGUMENT: _labels("The stories it holds that leave, by their S labels."),
        NOTES_ARGUMENT: _CARRIED_NOTES,
        EPISODE_ARGUMENT: _EPISODE_FILLED,
    },
    required=(STORY_ARGUMENT, EPISODE_ARGUMENT),
    system_supplied=(EPISODE_ARGUMENT,),
    safe_to_repeat=True,
    idempotency=Idempotency.NATURAL,
)
"""Split a story (ADR-0303 §9:1): a repeat names members the story no longer holds and is
refused, changing nothing."""

GROUP_STORY: Final = _declared(
    GROUP_STORY_CAPABILITY,
    (
        "Group stories under a new, larger story, where they are parts of one bigger "
        "matter. Do it only where someone asked for it, or the work in hand needs it "
        "now."
    ),
    properties={
        STORIES_ARGUMENT: _labels("The stories grouped, by their S labels.", min_items=1),
        NOTES_ARGUMENT: {
            "type": "array",
            "items": _NOTE_SCHEMA,
            "maxItems": START_NOTES_MAX,
            "description": "The larger story's first notes, if any: what the bigger matter is.",
        },
        EPISODE_ARGUMENT: _EPISODE_FILLED,
        OUTSIDE_CONTENT_ARGUMENT: _MARK_FILLED,
    },
    required=(STORIES_ARGUMENT, EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT),
    system_supplied=(EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT),
    safe_to_repeat=False,
    idempotency=Idempotency.NONE,
)
"""Group stories under a larger one (ADR-0303 §9:1): not safe to repeat, so a second
identical grouping is refused as already done (ADR-0306 §3:1, §5:9)."""

#: Every story call this module declares, in the order planning is offered them.
STORY_CALLS: Final = (
    START_STORY,
    NOTE_STORY,
    LINK_STORY,
    UNLINK_STORY,
    TIDY_STORY,
    MOVE_STORY,
    MERGE_STORY,
    SPLIT_STORY,
    GROUP_STORY,
)

#: The capabilities, by name.
STORY_CALL_CAPABILITIES: Final = tuple(str(one.capability) for one in STORY_CALLS)

#: Which arguments of each story call name things by label, and what each names
#: (ADR-0307 §5:2): planning's own check maps them to ids before authorizing.
STORY_LABEL_ARGUMENTS: Final[Mapping[str, Mapping[str, LabelKind]]] = {
    START_STORY_CAPABILITY: {INSIDE_ARGUMENT: LabelKind.STORY},
    NOTE_STORY_CAPABILITY: {STORY_ARGUMENT: LabelKind.STORY},
    LINK_STORY_CAPABILITY: {
        STORY_ARGUMENT: LabelKind.STORY,
        MEMBER_STORY_ARGUMENT: LabelKind.STORY,
        MEMBER_EPISODE_ARGUMENT: LabelKind.EPISODE,
    },
    UNLINK_STORY_CAPABILITY: {
        STORY_ARGUMENT: LabelKind.STORY,
        MEMBER_STORY_ARGUMENT: LabelKind.STORY,
        MEMBER_EPISODE_ARGUMENT: LabelKind.EPISODE,
    },
    TIDY_STORY_CAPABILITY: {STORY_ARGUMENT: LabelKind.STORY},
    MOVE_STORY_CAPABILITY: {
        STORY_ARGUMENT: LabelKind.STORY,
        TO_ARGUMENT: LabelKind.STORY,
        EPISODES_ARGUMENT: LabelKind.EPISODE,
        NOTES_ARGUMENT: LabelKind.NOTE,
    },
    MERGE_STORY_CAPABILITY: {STORY_ARGUMENT: LabelKind.STORY, INTO_ARGUMENT: LabelKind.STORY},
    SPLIT_STORY_CAPABILITY: {
        STORY_ARGUMENT: LabelKind.STORY,
        EPISODES_ARGUMENT: LabelKind.EPISODE,
        STORIES_ARGUMENT: LabelKind.STORY,
        NOTES_ARGUMENT: LabelKind.NOTE,
    },
    GROUP_STORY_CAPABILITY: {STORIES_ARGUMENT: LabelKind.STORY},
}

#: The calls that carry notes from one story to another, which the hub checks before
#: authorizing (ADR-0307 §5:3).
_CARRYING: Final = frozenset({MOVE_STORY_CAPABILITY, SPLIT_STORY_CAPABILITY})

#: How many notes one page of the hub's not-held check reads.
_NOTES_PAGE: Final = MAX_STORY_PAGE

#: The tidy-up's results under which the call is done: it wrote, or had nothing it
#: may fold in yet, or a run already on the story takes in what is pending (§5:10).
_TIDIED: Final = frozenset(
    {
        TidyUpResult.WRITTEN,
        TidyUpResult.NOTHING_TO_READ,
        TidyUpResult.OUTSIDE_ONLY,
        TidyUpResult.BUSY,
    }
)


class StartUnfinishedError(StoryStoreError):
    """A start or a group created its story, then could not write the rest it carries.

    The start happened, so it is neither not done, which would let the duplicate
    backstop admit an identical start that makes a second story, nor done, which its
    first notes or its place are not. Raised out of the runner, so acting leaves the
    effect record it was claimed under unfinished: counted as done by the backstop and
    never reported as done (ADR-0306 §5:6, §5:11). A ``StoryStoreError``, since what
    it means is that the store did not take what it had just admitted.
    """


class _NotDone(Exception):  # noqa: N818 — a control-flow signal inside the runner, never raised out
    """A call that cannot be done, with its code-owned kind and operator-facing message."""

    def __init__(self, kind: ToolFailureKind, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.reason = reason


def _not_done(kind: ToolFailureKind, message: str) -> ToolResult:
    return ToolResult(outcome=ToolOutcome.FAILED, failure=ToolFailure(kind=kind, message=message))


def _malformed(what: str) -> _NotDone:
    return _NotDone(ToolFailureKind.INVALID_REQUEST, what, reason="malformed")


def _text(parameters: Mapping[str, FrozenJson], name: str) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not value.strip():
        raise _malformed(f"a story call's {name!r} is non-blank text")
    return value


def _optional_text(parameters: Mapping[str, FrozenJson], name: str) -> str | None:
    if parameters.get(name) is None:
        return None
    return _text(parameters, name)


def _activation_of_episode(episode_id: str) -> str | None:
    """The activation whose episode ``episode_id`` is, or ``None`` where it is no one's."""
    if not episode_id.startswith(_EPISODE_PREFIX):
        return None
    activation = episode_id.removeprefix(_EPISODE_PREFIX)
    return activation or None


class StoryCalls:
    """Run planning's story calls against the story store (ADR-0306 §3:3).

    Structurally acting's ``OwnRecordsCalls``: one runner for every story call, which
    the composition root hands acting's own-records seam under each capability's name.
    Acting awaits it to its end, with no deadline and no cancellation, and its outcome
    is what the store answered: ``succeeded`` where the call was done, ``failed`` with
    a code-owned kind otherwise, never ``indeterminate``.
    """

    def __init__(
        self, *, stories: StoryStore, memory: MemoryStore, tidy_up: StoryTidyUp | None = None
    ) -> None:
        """Wire the runner to the stores it writes and reads, and to the tidy-up.

        Args:
            stories: The story store every call writes.
            memory: The memory store an activation member's episode is checked in
                before a create or a link (ADR-0289 §4).
            tidy_up: The tidy-up operation, the one the deployment holds, so at most
                one run is on a story at a time (ADR-0300 §5:10); ``None`` where none
                is wired, and a tidy-up call is then not done.
        """
        self._stories = stories
        self._memory = memory
        self._tidy_up = tidy_up

    async def run(self, call: ToolCall) -> ToolResult:
        """Run the story call ``call`` carries, and say what the store answered.

        Args:
            call: The authorized story call, its labels already ids.

        Returns:
            ``succeeded`` with no output where the call was done; ``failed`` where it
            is not a story call, is malformed, names what is not there, or the store
            refused it or could not be reached, and nothing was written.

        Raises:
            StartUnfinishedError: If a start or a group created its story and then
                could not write all its first notes, or a start could not place it
                inside the larger one. Acting then leaves the call's effect record
                unfinished, which the duplicate backstop counts as done and which is
                never reported as done (ADR-0306 §5:6, §5:11), so an identical call
                is not made again.
        """
        try:
            await self._dispatch(call)
        except StartUnfinishedError:
            # Raised on, so acting leaves the start's effect record unfinished (§5:6).
            _log.warning("story_call_unfinished", stage="acting", reason="start_unfinished")
            raise
        except _NotDone as refused:
            _log.info("story_call_not_done", stage="acting", reason=refused.reason)
            return _not_done(refused.kind, str(refused))
        except StoryStoreError, MemoryStoreError:
            _log.warning("story_call_not_done", stage="acting", reason="store_failed")
            return _not_done(ToolFailureKind.INTERNAL, "the story store could not be written")
        except ValueError:
            # The store's own refusal of a malformed argument (ADR-0289 §3).
            _log.info("story_call_not_done", stage="acting", reason="malformed")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "the call's arguments are malformed")
        return ToolResult(outcome=ToolOutcome.SUCCEEDED)

    async def _dispatch(self, call: ToolCall) -> None:
        """Run the call its capability names; a capability no story call has is not done."""
        capability = str(call.request.tool.capability)
        parameters = call.request.parameters
        if capability == START_STORY_CAPABILITY:
            await self._start(call)
        elif capability == NOTE_STORY_CAPABILITY:
            await self._note(parameters)
        elif capability in {LINK_STORY_CAPABILITY, UNLINK_STORY_CAPABILITY}:
            await self._membership(parameters, link=capability == LINK_STORY_CAPABILITY)
        elif capability == TIDY_STORY_CAPABILITY:
            await self._tidy(parameters)
        elif capability in _REORGANISING:
            await self._reorganise(capability, parameters)
        elif capability == GROUP_STORY_CAPABILITY:
            await self._group(parameters)
        else:
            raise _NotDone(
                ToolFailureKind.INVALID_REQUEST, "not a story call", reason="not_a_story_call"
            )

    # --- the calls ---

    async def _start(self, call: ToolCall) -> None:
        """Start a story with this activation and its first notes (ADR-0300 §10:3)."""
        parameters = call.request.parameters
        notes = parameters.get(NOTES_ARGUMENT)
        if (
            not isinstance(notes, tuple | list)
            or not notes
            or len(notes) > START_NOTES_MAX
            or not all(isinstance(one, str) and one.strip() for one in notes)
        ):
            raise _malformed("a start carries its first notes, each non-blank text")
        activation = self._activation(parameters)
        outside = self._mark(parameters)
        inside = _optional_text(parameters, INSIDE_ARGUMENT)
        larger = None if inside is None else await self._current(inside)
        own = StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation)
        await self._episode_held(own)
        created = await self._stories.create([own], actor=StoryActor.PLANNING, trigger=activation)
        if created.story_id is None:
            raise _refused("the story store refused the start")
        started = str(created.story_id)
        try:
            await self._started(started, notes, activation, outside=outside, larger=larger)
        except (_NotDone, StoryStoreError, MemoryStoreError, ValueError) as exc:
            # The story exists, so the start happened, though not whole: never reported
            # as not done, which the duplicate backstop would let an identical start
            # repeat, and never as done (ADR-0306 §5:6, §5:11).
            msg = "a story was started, but its first notes or its place were not all written"
            raise StartUnfinishedError(msg) from exc

    async def _started(
        self,
        started: str,
        notes: Sequence[FrozenJson],
        activation: str,
        *,
        outside: bool,
        larger: str | None,
    ) -> None:
        """Write a started story's first notes, then place it inside the larger one."""
        for note in notes:
            written = await self._stories.append_note(
                started,
                str(note),
                author=StoryNoteAuthor.PLANNING,
                written_during=activation,
                outside=outside,
            )
            if written.note is None:
                raise _refused("a first note was refused")
        if larger is not None:
            linked = await self._stories.link(
                larger,
                [StoryMember(kind=StoryMemberKind.STORY, id=started)],
                actor=StoryActor.PLANNING,
                trigger=activation,
            )
            if linked.story_id is None:
                raise _refused("the story was not placed inside the larger one")

    async def _note(self, parameters: Mapping[str, FrozenJson]) -> None:
        """Write a note by ``planning`` on a story, with its mark (ADR-0303 §9:3)."""
        story = await self._current(_text(parameters, STORY_ARGUMENT))
        note = _text(parameters, NOTE_ARGUMENT)
        activation = self._activation(parameters)
        written = await self._stories.append_note(
            story,
            note,
            author=StoryNoteAuthor.PLANNING,
            written_during=activation,
            outside=self._mark(parameters),
        )
        if written.note is None:
            raise _refused("the story store refused the note")

    async def _membership(self, parameters: Mapping[str, FrozenJson], *, link: bool) -> None:
        """Link a member into a story, or unlink one from it (ADR-0300 §10:3, ADR-0303 §9:1).

        The member is the story or the activation the call names, or this activation
        where it names neither. A linked activation's episode is checked first
        (ADR-0289 §4); an unlinked one's is not, since a member whose episode is
        forgotten may still be removed.
        """
        story = await self._current(_text(parameters, STORY_ARGUMENT))
        activation = self._activation(parameters)
        member = await self._member(parameters, activation)
        if link:
            await self._episode_held(member)
            outcome = await self._stories.link(
                story, [member], actor=StoryActor.PLANNING, trigger=activation
            )
        else:
            outcome = await self._stories.unlink(
                story, [member], actor=StoryActor.PLANNING, trigger=activation
            )
        if outcome.story_id is None:
            raise _refused("the story store refused the change")

    async def _tidy(self, parameters: Mapping[str, FrozenJson]) -> None:
        """Run the tidy-up on a story; what it wrote is in the story's version log (§7)."""
        if self._tidy_up is None:
            raise _NotDone(ToolFailureKind.UNAVAILABLE, "no tidy-up is wired", reason="no_tidy_up")
        story = await self._current(_text(parameters, STORY_ARGUMENT))
        outcome = await self._tidy_up.run(story)
        if outcome.result not in _TIDIED:
            raise _NotDone(
                ToolFailureKind.REFUSED,
                f"the tidy-up wrote nothing: {outcome.result.value}",
                reason=f"tidy_up_{outcome.result.value}",
            )

    async def _reorganise(self, capability: str, parameters: Mapping[str, FrozenJson]) -> None:
        """Move, merge or split, as the store does each in one transaction (ADR-0303 §9:1)."""
        activation = self._activation(parameters)
        if capability == MERGE_STORY_CAPABILITY:
            outcome = await self._merge(parameters, activation)
        elif capability == MOVE_STORY_CAPABILITY:
            outcome = await self._move(parameters, activation)
        else:
            outcome = await self._split(parameters, activation)
        if outcome.story_id is None:
            raise _store_refused(outcome)

    async def _merge(self, parameters: Mapping[str, FrozenJson], activation: str) -> StoryOutcome:
        """Merge one story into another; every note goes with it (ADR-0303 §6:3).

        The story absorbed is named as it is, never followed: one merged since is refused
        as merged, so a repeat changes nothing (ADR-0303 §9's table).
        """
        absorbed = _text(parameters, STORY_ARGUMENT)
        into = await self._current(_text(parameters, INTO_ARGUMENT))
        return await self._stories.merge(
            absorbed, into, actor=StoryActor.PLANNING, trigger=activation
        )

    async def _move(self, parameters: Mapping[str, FrozenJson], activation: str) -> StoryOutcome:
        """Move activation members, notes, or both, to another story (ADR-0303 §6)."""
        source = await self._current(_text(parameters, STORY_ARGUMENT))
        target = await self._current(_text(parameters, TO_ARGUMENT))
        episodes = _episode_members(parameters)
        notes = _note_ids(parameters)
        if not episodes and not notes:
            raise _malformed("a move names the episodes or the notes that go")
        if target == source:
            raise _NotDone(
                ToolFailureKind.INVALID_REQUEST,
                "a move goes from one story to another; these are one story now",
                reason="same_story",
            )
        return await self._stories.move(
            source, target, episodes, actor=StoryActor.PLANNING, trigger=activation, notes=notes
        )

    async def _split(self, parameters: Mapping[str, FrozenJson], activation: str) -> StoryOutcome:
        """Split members off a story into a new one, with the notes named (ADR-0303 §6)."""
        source = await self._current(_text(parameters, STORY_ARGUMENT))
        members = [*_episode_members(parameters), *await self._story_members(parameters)]
        notes = _note_ids(parameters)
        if not members:
            raise _malformed("a split names the episodes or the stories that leave")
        return await self._stories.split(
            source, members, actor=StoryActor.PLANNING, trigger=activation, notes=notes
        )

    async def _group(self, parameters: Mapping[str, FrozenJson]) -> None:
        """Group stories under a new larger one, then write its first notes (ADR-0303 §9:1).

        Everything is checked first, so a group naming a story not there makes nothing;
        once the larger story exists, a first note not written leaves the call
        unfinished, never not done, as a start does (ADR-0306 §5:6, §5:11).
        """
        notes = parameters.get(NOTES_ARGUMENT) or ()
        if (
            not isinstance(notes, tuple | list)
            or len(notes) > START_NOTES_MAX
            or not all(isinstance(one, str) and one.strip() for one in notes)
        ):
            raise _malformed("a group's first notes are each non-blank text")
        activation = self._activation(parameters)
        outside = self._mark(parameters)
        grouped = await self._story_members(parameters)
        if not grouped:
            raise _malformed("a group names the stories it groups")
        created = await self._stories.create(grouped, actor=StoryActor.PLANNING, trigger=activation)
        if created.story_id is None:
            raise _store_refused(created)
        try:
            for note in notes:
                written = await self._stories.append_note(
                    str(created.story_id),
                    str(note),
                    author=StoryNoteAuthor.PLANNING,
                    written_during=activation,
                    outside=outside,
                )
                if written.note is None:
                    raise _refused("a first note was refused")
        except (_NotDone, StoryStoreError, MemoryStoreError, ValueError) as exc:
            msg = "stories were grouped, but the larger story's first notes were not all written"
            raise StartUnfinishedError(msg) from exc

    async def _story_members(self, parameters: Mapping[str, FrozenJson]) -> list[StoryMember]:
        """The stories a split or a group names, each followed through its merges, once."""
        named = _ids(parameters, STORIES_ARGUMENT)
        current = [await self._current(one) for one in named]
        return [StoryMember(kind=StoryMemberKind.STORY, id=one) for one in dict.fromkeys(current)]

    # --- the hub's check before authorizing ---

    async def refusal(
        self,
        call: ProposedCall,
        *,
        owner_records: bool,
        labels: Mapping[str, str] | None = None,
    ) -> str | None:
        """Why a move or a split must be refused whole before it is authorized, if it must.

        ADR-0307 §5:3-§5:4, §6:5. Made on the call as planning's own check left it, its
        labels ids, against the stories as they stand now: a move or a split naming a
        note the story it moves from does not hold is refused, and so is one naming any
        note on a pass that may not show a record placed for the owner alone, where it
        carries members only. Where the stories cannot be read, it is refused too: the
        check fails closed. Every other call, and a move or a split naming no note,
        passes; what else is wrong with it is the runner's to find.

        Args:
            call: The call, its labels already ids.
            owner_records: Whether this pass may show a record placed for the owner
                alone.
            labels: Each note's label, by its id as text, so the reason names the note
                as planning was shown it.

        Returns:
            The reason, in code-owned words planning is shown, or ``None``.
        """
        if call.name not in _CARRYING:
            return None
        try:
            return await self._checked(call, owner_records=owner_records, labels=labels or {})
        except _NotDone as refused:
            return str(refused)
        except StoryStoreError:
            _log.warning("story_call_unchecked", stage="planning", reason="store_failed")
            return "the stories could not be read, so the notes named could not be checked"

    async def _checked(
        self, call: ProposedCall, *, owner_records: bool, labels: Mapping[str, str]
    ) -> str | None:
        """:meth:`refusal`'s reason, raising what it could not decide."""
        named = _note_ids(call.arguments)
        if not named:
            return None
        if not owner_records:
            return (
                "on this pass a move or a split carries members only: name no notes, "
                "and every note stays where it is"
            )
        source = await self._current(_text(call.arguments, STORY_ARGUMENT))
        missing = await self._not_held(source, named)
        if not missing:
            return None
        shown = labels.get(str(missing[0]), "a note named")
        return f"{shown} is not on the story it would leave, so nothing was moved"

    async def _not_held(self, story_id: str, named: Sequence[int]) -> list[int]:
        """The notes of ``named`` that ``story_id`` does not hold now, in the order named."""
        wanted = set(named)
        cursor: int | None = None
        while wanted:
            page = await self._stories.notes(story_id, cursor=cursor, limit=_NOTES_PAGE)
            if page is None:
                break
            wanted -= {one.note_id for one in page.notes}
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        return [one for one in dict.fromkeys(named) if one in wanted]

    # --- the parts ---

    @staticmethod
    def _activation(parameters: Mapping[str, FrozenJson]) -> str:
        """This activation, from the episode address the hub filled."""
        activation = _activation_of_episode(_text(parameters, EPISODE_ARGUMENT))
        if activation is None:
            raise _malformed("a story call names this activation's episode")
        return activation

    @staticmethod
    def _mark(parameters: Mapping[str, FrozenJson]) -> bool:
        """The note's mark, as the hub filled it from the activation's record (§3:1)."""
        outside = parameters.get(OUTSIDE_CONTENT_ARGUMENT)
        if not isinstance(outside, bool):
            raise _malformed("a story call writing a note carries the hub's mark")
        return outside

    async def _member(self, parameters: Mapping[str, FrozenJson], activation: str) -> StoryMember:
        """The member a link or an unlink names, or this activation where it names none."""
        story = _optional_text(parameters, MEMBER_STORY_ARGUMENT)
        episode = _optional_text(parameters, MEMBER_EPISODE_ARGUMENT)
        if story is not None and episode is not None:
            raise _malformed("a link or an unlink names one member: a story or an episode")
        if story is not None:
            return StoryMember(kind=StoryMemberKind.STORY, id=await self._current(story))
        if episode is None:
            return StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation)
        named = _activation_of_episode(episode)
        if named is None:
            raise _NotDone(
                ToolFailureKind.INVALID_REQUEST,
                "the episode named is no activation's, and a story holds only activations",
                reason="not_an_activation",
            )
        return StoryMember(kind=StoryMemberKind.ACTIVATION, id=named)

    async def _episode_held(self, member: StoryMember) -> None:
        """Refuse an activation member with no episode, before it is linked (ADR-0289 §4)."""
        if await unknown_activation(self._memory, [member]) is not None:
            raise _NotDone(
                ToolFailureKind.INVALID_REQUEST,
                "the activation named has no episode",
                reason="unknown_activation",
            )

    async def _current(self, story_id: str) -> str:
        """The story ``story_id`` names as it stands now, followed through its merges.

        Followed to the story that is not merged, however many merges that takes: the
        store bounds no chain. A merged story is never a merge target (ADR-0289 §3), so
        a story met twice is the store contradicting itself, raised as its failure
        rather than followed for ever, as ``story_links`` stops on a target named twice.
        """
        current = story_id
        followed: set[str] = set()
        while current not in followed:
            followed.add(current)
            header = await self._stories.header(current)
            if header is None:
                raise _NotDone(
                    ToolFailureKind.INVALID_REQUEST,
                    "the story named is not there",
                    reason="unknown_story",
                )
            if header.merged_into is None:
                return current
            current = str(header.merged_into)
        msg = "the story store's merges do not end"
        raise StoryStoreError(msg)


def _refused(message: str) -> _NotDone:
    return _NotDone(ToolFailureKind.REFUSED, message, reason="store_refused")


#: The calls :meth:`StoryCalls._reorganise` runs.
_REORGANISING: Final = frozenset(
    {MOVE_STORY_CAPABILITY, MERGE_STORY_CAPABILITY, SPLIT_STORY_CAPABILITY}
)


def _store_refused(outcome: StoryOutcome) -> _NotDone:
    """The store's refusal, named by its code-owned reason (ADR-0289 §3)."""
    reason = "refused" if outcome.refusal is None else outcome.refusal.reason.value
    return _NotDone(
        ToolFailureKind.REFUSED,
        f"the story store refused it: {reason}",
        reason=f"store_{reason}",
    )


def _ids(parameters: Mapping[str, FrozenJson], name: str) -> list[str]:
    """The ids a list argument names, none where it is absent."""
    value = parameters.get(name)
    if value is None:
        return []
    if not isinstance(value, tuple | list) or not all(
        isinstance(one, str) and one.strip() for one in value
    ):
        raise _malformed(f"a story call's {name!r} is a list of labels")
    return [str(one) for one in value]


def _episode_members(parameters: Mapping[str, FrozenJson]) -> list[StoryMember]:
    """The activations a move or a split names by their episodes, once each."""
    members: list[StoryMember] = []
    for episode in dict.fromkeys(_ids(parameters, EPISODES_ARGUMENT)):
        activation = _activation_of_episode(episode)
        if activation is None:
            raise _NotDone(
                ToolFailureKind.INVALID_REQUEST,
                "the episode named is no activation's, and a story holds only activations",
                reason="not_an_activation",
            )
        members.append(StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation))
    return members


def _note_ids(parameters: Mapping[str, FrozenJson]) -> list[int]:
    """The notes a move or a split names, each a note's id as its ``N`` label names it."""
    ids: list[int] = []
    for one in _ids(parameters, NOTES_ARGUMENT):
        if not one.isdigit() or int(one) < 1:
            raise _malformed("a note is named by the N label it was shown under")
        ids.append(int(one))
    return ids
