"""The message tools: ``text``, ``email``'s names, and what every message call shares (ADR-0357).

Saying something to someone is a call to a tool chosen by its modality (ADR-0357 §2:1):
``text`` for a short written message, ``email`` for an email. This module holds what the
phases, planning and authorizing read alike, and imports nothing of theirs:

- **``text``'s declaration** (§2:2), offered on every round (ADR-0356 §4:3), and the
  check of its arguments, which code makes because a ``text`` call is never selected or
  ruled on as a call (ADR-0356 §7:7).
- **Who it is for** (§2:3): ``to`` names a person as planning was shown them, and a name
  that fits no one comes back with who it could be, never a guess. The only person a
  message reaches today is the user, by the place their input came from or a place on
  the activation's place list (§1:4).
- **Where it goes** (§2:4): ``via`` names a place by its ``L`` label or a platform by
  name, and the platforms are named here, with how a result names them (§3:1).
- **The wording step** (§4): it passes the words through unchanged, ``exact`` or not,
  until the decision §4:5 names builds it.
- **The asking message** (§8): the round's one ``text`` call carrying ``asks``, and the
  fixed line and exact lines code appends after any rewording (§8:2, ADR-0321 §2:5).
- **``email``'s names** (§2:5-§2:10): the capability and its arguments, which the
  declaration in ``tools`` spells and authorizing's gate reads, pinned equal by test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    Idempotency,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "ASKS_ARGUMENT",
    "ATTACHMENTS_ARGUMENT",
    "BCC_ARGUMENT",
    "CC_ARGUMENT",
    "EMAIL_CAPABILITY",
    "EMAIL_CHANNEL_TYPE",
    "EXACT_ARGUMENT",
    "FROM_ARGUMENT",
    "FROM_ASSISTANT",
    "FROM_USER",
    "NEEDS_YOUR_YES",
    "PLACE_LABEL",
    "PLATFORMS",
    "SUBJECT_ARGUMENT",
    "TEXT_CALL",
    "TEXT_CAPABILITY",
    "THE_USER",
    "TO_ARGUMENT",
    "VIA_ARGUMENT",
    "WORDS_ARGUMENT",
    "TextArguments",
    "asks_named",
    "carries_asks",
    "emailed_to",
    "platform_name",
    "platform_type",
    "reworded",
    "text_arguments",
    "who_it_is_for",
    "with_question",
]

# --- the names ------------------------------------------------------------------------

TEXT_CAPABILITY: Final = "text"
TO_ARGUMENT: Final = "to"
WORDS_ARGUMENT: Final = "words"
VIA_ARGUMENT: Final = "via"
EXACT_ARGUMENT: Final = "exact"
ASKS_ARGUMENT: Final = "asks"

#: ``email`` (ADR-0357 §2:5), as ``tools``' declaration names it and its arguments.
EMAIL_CAPABILITY: Final = "email"
SUBJECT_ARGUMENT: Final = "subject"
CC_ARGUMENT: Final = "cc"
BCC_ARGUMENT: Final = "bcc"
ATTACHMENTS_ARGUMENT: Final = "attachments"
FROM_ARGUMENT: Final = "from"
#: The two addresses ``from`` names (§2:9): the assistant's own, or the user's.
FROM_ASSISTANT: Final = "assistant"
FROM_USER: Final = "user"

#: How planning is shown the person a message reaches, as the place window names them.
THE_USER: Final = "the user"

#: The platforms a ``text`` call may name in ``via`` (§2:2, §2:4), by name, each with
#: its channel type: the hub chat and the Telegram line as built.
PLATFORMS: Final[Mapping[str, str]] = {"hub_chat": "conversation", "telegram": "telegram"}

#: How a result names each platform, by channel type (§3:1).
_PLATFORM_NAMES: Final[Mapping[str, str]] = {
    "conversation": "the hub chat",
    "telegram": "Telegram",
    "email": "email",
}

#: The channel type an email's delivery names where it went (ADR-0357 §3:1): its
#: platform, with its recipients as the place.
EMAIL_CHANNEL_TYPE: Final = "email"

#: The owner's ruling on #3094 (2026-10-16): the one fixed line code puts above the exact
#: lines it appends to an asking message, so a question never goes out as a bare line.
NEEDS_YOUR_YES: Final = "Needs your yes:"

# --- text's declaration (§2:2) ---------------------------------------------------------

TEXT_CALL: Final = ToolDefinition(
    id=TEXT_CAPABILITY,
    capability=TEXT_CAPABILITY,
    description=(
        "Send a short written message to someone, in the system's own voice. It goes "
        "into the place the stimulus came from unless via names another, and the "
        "result says what was sent, where it went and how. Its words are sent as you "
        "write them; set exact where the wording itself must not change, such as a "
        "quote or a relayed message. Never claim to be human."
    ),
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.IRREVERSIBLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.WORLD,
    leaves_hub=False,
    result=CapabilityResult.NO_OUTSIDE_TEXT,
    outcome_can_be_unknown=True,
    safe_to_repeat=True,
    parameters_schema={
        "type": "object",
        "properties": {
            TO_ARGUMENT: {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Who it is for, as you were shown them: the person the system serves "
                    f"by their name, or {THE_USER!r}."
                ),
            },
            WORDS_ARGUMENT: {"type": "string", "minLength": 1, "description": "What to say."},
            VIA_ARGUMENT: {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Where it goes: a place on your place list, by its L label, or a "
                    "platform: " + " or ".join(sorted(PLATFORMS)) + "."
                ),
            },
            EXACT_ARGUMENT: {
                "type": "boolean",
                "description": "Send the words exactly as written.",
            },
            ASKS_ARGUMENT: {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
                "description": (
                    "The calls this message asks about, each by the ask_as reference its "
                    "result showed: an action that needs a yes before it runs. Explain "
                    "each in the message's own words, with the details that matter to "
                    "the person; the system adds its exact details after your words, so "
                    "never write them yourself, and never send them alone. One message a "
                    "round asks. Never approve anything on anyone's behalf: there is no "
                    "other route, no confirmation email, no link or code, and no step on "
                    "the person's end."
                ),
            },
        },
        "required": [TO_ARGUMENT, WORDS_ARGUMENT],
        "additionalProperties": False,
    },
)
"""``text``'s declaration (ADR-0357 §2:2), offered on every round (ADR-0356 §4:3).

It is never selected, ruled on or run as a call: the phases take each ``text`` call out
of the round's calls before authorizing, which checks it by its place alone as the
round's message is checked (ADR-0356 §7:7), and write it into its place under an effect
record as a message is written (§7:8). So nothing reads its egress fields, which declare
none: where a message may go is the message place check's, and its place's writer holds
the channel's rules (ADR-0306 §4:7, ADR-0292 §8:3).

``safe_to_repeat`` is set, so the offer adds no *deliberate repeat* mark: a message's
effect record is a message's, which carries no capability or values digest for
ADR-0306 §5:9's backstop to compare (ADR-0306 §6:1), so no repeat of one is refused as
*already done* (ADR-0357 §6:4 for ``text`` waits on #3548). The words of the rules
ADR-0357 §7:2 moves into this description ship in ADR-0356's P3 (ADR-0357 §7:3).
"""

# --- text's arguments -------------------------------------------------------------------

#: Why a ``text`` call runs nothing, by what was wrong with its arguments (§6:3).
_NO_WORDS: Final = f"{WORDS_ARGUMENT!r} is what the message says, and it said nothing"
_NO_ONE: Final = f"{TO_ARGUMENT!r} names who the message is for, as you were shown them"
_NOT_ONE_PLACE: Final = (
    f"{VIA_ARGUMENT!r} names one place, by its L label, or one platform, by its name"
)
_NOT_EXACT: Final = f"{EXACT_ARGUMENT!r} is true or false"
_NOT_ASKS: Final = (
    f"{ASKS_ARGUMENT!r} names the calls the message asks about, each by its ask_as reference"
)
_UNDECLARED: Final = (
    f"{TEXT_CAPABILITY} takes {TO_ARGUMENT}, {WORDS_ARGUMENT}, {VIA_ARGUMENT}, "
    f"{EXACT_ARGUMENT} and {ASKS_ARGUMENT}, and nothing else"
)
_DECLARED: Final = frozenset(
    {TO_ARGUMENT, WORDS_ARGUMENT, VIA_ARGUMENT, EXACT_ARGUMENT, ASKS_ARGUMENT}
)


@dataclass(frozen=True, slots=True)
class TextArguments:
    """A ``text`` call's arguments, checked (ADR-0357 §2:2).

    Attributes:
        to: Who it is for, as planning named them.
        words: What to say, as planning wrote it.
        via: Where it goes, as planning named it; ``None`` where it named nowhere, and
            the tool chooses (§2:4).
        exact: Whether the words go exactly as written (§4:2).
        asks: The references of the calls it asks about, as named (§8:1).
    """

    to: str
    words: str
    via: str | None = None
    exact: bool = False
    asks: tuple[str, ...] = ()


def text_arguments(arguments: Mapping[str, object]) -> TextArguments | str:  # noqa: PLR0911 — one refusal for each argument it checks
    """A ``text`` call's arguments, or why the call runs nothing (ADR-0357 §6:1, §6:3).

    ``text`` is never ruled on as a call, so its schema is checked here: a missing or
    wrong argument is never guessed, and an argument it does not declare is refused.

    Returns:
        The arguments, or the reason the call comes back.
    """
    if set(arguments) - _DECLARED:
        return _UNDECLARED
    words = arguments.get(WORDS_ARGUMENT)
    if not isinstance(words, str) or not words.strip():
        return _NO_WORDS
    to = arguments.get(TO_ARGUMENT)
    if not isinstance(to, str) or not to.strip():
        return _NO_ONE
    via = arguments.get(VIA_ARGUMENT)
    if VIA_ARGUMENT in arguments and (not isinstance(via, str) or not via.strip()):
        return _NOT_ONE_PLACE
    exact = arguments.get(EXACT_ARGUMENT, False)
    if not isinstance(exact, bool):
        return _NOT_EXACT
    asks = arguments.get(ASKS_ARGUMENT, ())
    if not isinstance(asks, list | tuple) or not all(
        isinstance(one, str) and one.strip() for one in asks
    ):
        return _NOT_ASKS
    return TextArguments(
        to=to,
        words=words,
        via=via.strip() if isinstance(via, str) else None,
        exact=exact,
        asks=tuple(str(one) for one in asks),
    )


def carries_asks(name: str, arguments: Mapping[str, object]) -> bool:
    """Whether a call is a ``text`` call carrying ``asks`` (ADR-0357 §8:1, §8:3).

    One whose ``asks`` is present and not empty, whatever it holds: a malformed one still
    makes the call the round's asking message, which then comes back for it.
    """
    if name != TEXT_CAPABILITY:
        return False
    asks = arguments.get(ASKS_ARGUMENT)
    return asks is not None and asks not in ([], ())


def asks_named(arguments: Mapping[str, object]) -> tuple[str, ...]:
    """The references a ``text`` call's ``asks`` names, or none where it is malformed."""
    asks = arguments.get(ASKS_ARGUMENT, ())
    if not isinstance(asks, list | tuple) or not all(isinstance(one, str) for one in asks):
        return ()
    return tuple(str(one) for one in asks)


# --- who it is for (§2:3) ---------------------------------------------------------------


def _bare(name: str) -> str:
    return " ".join(name.casefold().split())


def who_it_is_for(to: str, *, named: Sequence[str] = ()) -> str | None:
    """Why ``to`` reaches no one, or ``None`` where it names the user (ADR-0357 §2:3).

    The only person a message reaches today is the user (§1:4): named as planning is
    shown them, :data:`THE_USER` or ``user``, or by a name their profile gives,
    ``named``, whole or by its first word. A name that fits no one comes back with who it
    could be, never a guess.

    Args:
        to: Who the call says it is for.
        named: The names the user's profile gives them, as planning was shown them.

    Returns:
        ``None`` where ``to`` names the user; otherwise the reason the call comes back.
    """
    wanted = _bare(to)
    known = {_bare(THE_USER), "user"}
    for name in named:
        if name.strip():
            known.add(_bare(name))
            known.add(_bare(name).split(" ", 1)[0])
    if wanted in known:
        return None
    shown = ", ".join(repr(one.strip()) for one in named if one.strip())
    could_be = THE_USER if not shown else f"{THE_USER} ({shown})"
    return f"{TO_ARGUMENT!r} names no one a message here reaches: it could be {could_be}"


# --- where it goes (§2:4, §3:1) ---------------------------------------------------------

#: A place label, as planning names one in ``via`` (ADR-0350 §5:13).
PLACE_LABEL: Final = re.compile(r"L[1-9][0-9]{0,8}")


def platform_type(name: str) -> str | None:
    """The channel type of the platform ``name`` names, or ``None`` where it names none.

    Read with its case, its spaces and a leading *the* ignored, so "Telegram" and "the
    hub chat" name what ``telegram`` and ``hub_chat`` name.
    """
    bare = re.sub(r"[\s\-]+", "_", name.strip().casefold())
    return PLATFORMS.get(bare.removeprefix("the_"))


def platform_name(channel_type: str) -> str:
    """How a result names the platform of ``channel_type`` (ADR-0357 §3:1)."""
    return _PLATFORM_NAMES.get(channel_type, channel_type)


def emailed_to(arguments: Mapping[str, object]) -> str | None:
    """Where an email went, as its delivery names the place: its recipients, in order.

    ``to``, then ``cc``, then ``bcc``, each recipient once, joined by commas; ``None``
    where it names none (ADR-0357 §3:1).
    """
    named: list[str] = []
    for argument in (TO_ARGUMENT, CC_ARGUMENT, BCC_ARGUMENT):
        value = arguments.get(argument)
        values = [value] if isinstance(value, str) else value
        if isinstance(values, list | tuple):
            named.extend(one.strip() for one in values if isinstance(one, str) and one.strip())
    return ", ".join(dict.fromkeys(named)) or None


# --- the wording step (§4) and the asking message (§8:2) ---------------------------------


def reworded(words: str, *, exact: bool) -> str:
    """A message's words as the wording step renders them (ADR-0357 §4).

    Until the decision §4:5 names builds the step, every message's words are sent
    unchanged, ``exact`` or not, and ``exact`` changes nothing (§4:3).
    """
    del exact
    return words


def _bare_line(line: str) -> str:
    """A line as :func:`_without_fixed_line` compares it: no whitespace, colon or case."""
    return line.strip().removesuffix(":").rstrip().casefold()


def _without_fixed_line(text: str) -> str:
    """The words without a :data:`NEEDS_YOUR_YES` line of their own at their end (#3103).

    Planning is told it never writes the fixed line, and code is the backstop: a last
    line that is the fixed line, whatever its case, surrounding whitespace or missing
    colon, is dropped. Only the last line: a mention anywhere else is left as written.
    """
    lines = text.rstrip().splitlines(keepends=True)
    if lines and _bare_line(lines[-1]) == _bare_line(NEEDS_YOUR_YES):
        return "".join(lines[:-1])
    return text


def with_question(words: str, lines: str | None) -> str:
    """The asking message: its words, then the exact lines under the fixed line (§8:2).

    ``words`` are the words after any rewording, and the lines come after them, so the
    wording step never changes them (§4:4) and a message cut to fit loses them first. The
    fixed line comes after a blank line, whether or not there are words (#3094), and a
    copy of it ending the words is dropped, so it appears once (#3103). A message asking
    about nothing, ``lines`` ``None`` or empty, is its words as they are.
    """
    if not lines:
        return words
    text = _without_fixed_line(words)
    question = f"{NEEDS_YOUR_YES}\n{lines}"
    return f"{text.rstrip()}\n\n{question}" if text.strip() else question
