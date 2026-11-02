"""The message tools: ``send_text``, ``send_email``'s names, and what both share (ADR-0357).

Saying something to someone is a call to a tool chosen by its modality (ADR-0357 §2:1):
``send_text`` for a text message into a connection, ``send_email`` for an email from an
email account (ADR-0364 §8:1). This module holds what the phases, planning and
authorizing read alike, and imports nothing of theirs:

- **``send_text``'s declaration** (ADR-0364 §9:1), offered on every round (ADR-0356
  §4:3), and the check of its arguments, which code makes because a ``send_text`` call is
  never selected or ruled on as a call (ADR-0356 §7:7). It takes ``connection``, an ``L``
  label checked by its pattern with no ``enum``, so the offered tools stay identical
  across works (§9:2), and ``words``. Who a message reaches is its connection's (§9:1).
- **Exact parts** (§9:6-§9:9): words mark a part to be sent exactly as written with an
  ``<exact>`` tag and its closing tag, a backslash before a tag sending it as literal text
  and two sending one backslash and leaving the tag a tag. :func:`exact_words` reads them
  and :func:`reworded` sends them.
- **The wording step** (ADR-0357 §4): until it is built, words are sent as written with
  the tags removed (ADR-0364 §9:9).
- **``send_email``'s names** (ADR-0357 §2:5-§2:10, ADR-0364 §9:11-§9:14): the capability
  and its arguments, which the declaration in ``tools`` spells and authorizing's gate
  reads, pinned equal by test.
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
    LabelKind,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "BCC_ARGUMENT",
    "CC_ARGUMENT",
    "CONNECTION_ARGUMENT",
    "EMAIL_CAPABILITY",
    "EMAIL_CHANNEL_TYPE",
    "EMAIL_LABEL_ARGUMENTS",
    "EXACT_CLOSE",
    "EXACT_OPEN",
    "FROM_ARGUMENT",
    "FROM_THE_PERSONS_ACCOUNT",
    "PLACE_LABEL",
    "SUBJECT_ARGUMENT",
    "TEXT_CALL",
    "TEXT_CAPABILITY",
    "TO_ARGUMENT",
    "WORDS_ARGUMENT",
    "ExactWords",
    "TextArguments",
    "emailed_to",
    "escaped_exact",
    "exact_words",
    "platform_name",
    "reworded",
    "text_arguments",
]

# --- the names ------------------------------------------------------------------------

TEXT_CAPABILITY: Final = "send_text"
WORDS_ARGUMENT: Final = "words"
CONNECTION_ARGUMENT: Final = "connection"

#: ``send_email`` (ADR-0357 §2:5, ADR-0364 §8:1), as ``tools``' declaration names it and
#: its arguments.
EMAIL_CAPABILITY: Final = "send_email"
TO_ARGUMENT: Final = "to"
SUBJECT_ARGUMENT: Final = "subject"
CC_ARGUMENT: Final = "cc"
BCC_ARGUMENT: Final = "bcc"
FROM_ARGUMENT: Final = "from"
#: What ``from`` carries once planning's check has mapped an email account's ``L`` label:
#: the person's own account, the one kind this build connects (ADR-0364 §9:11), as
#: ``tools``' ``FROM_THE_PERSONS_ACCOUNT`` spells it, pinned equal by test.
FROM_THE_PERSONS_ACCOUNT: Final = "user"

#: ``send_email``'s ``from`` names its account by the connection's ``L`` label (ADR-0364
#: §9:11), which planning's check maps to the connection it names (ADR-0307 §5:2).
EMAIL_LABEL_ARGUMENTS: Final[Mapping[str, Mapping[str, LabelKind]]] = {
    EMAIL_CAPABILITY: {FROM_ARGUMENT: LabelKind.PLACE},
}

#: How a result names each platform, by channel type (ADR-0357 §3:1).
_PLATFORM_NAMES: Final[Mapping[str, str]] = {
    "conversation": "the hub chat",
    "telegram": "Telegram",
    "email": "email",
}

#: The channel type an email's delivery names where it went (ADR-0357 §3:1): its
#: platform, with its recipients as the place.
EMAIL_CHANNEL_TYPE: Final = "email"

#: A connection's label, as a ``send_text`` call names one (ADR-0364 §9:2).
PLACE_LABEL: Final = re.compile(r"L[1-9][0-9]{0,8}")

# --- send_text's declaration (ADR-0364 §9:1) ---------------------------------------------

TEXT_CALL: Final = ToolDefinition(
    # ADR-0364 §8:1: renamed, keeping its declaration's other fields, its id among them.
    id="text",
    capability=TEXT_CAPABILITY,
    description=(
        "Send a text message from the system into one of its connections.\n"
        "\n"
        "outcome: done | not done | unknown | refused\n"
        "because: why, with not done, unknown or refused\n"
        "\n"
        "It acts outside the system and can't be undone. Safe to repeat."
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
            CONNECTION_ARGUMENT: {
                "type": "string",
                "pattern": "^L[1-9][0-9]*$",
                "description": (
                    "Which connection to send the text through. It must support text messages, "
                    "and the message must be for who it reaches."
                ),
            },
            WORDS_ARGUMENT: {
                "type": "string",
                "minLength": 1,
                "description": (
                    "What to say. Wrap any part that must be sent exactly as written, such as a "
                    "quote, in <exact>…</exact>; the rest may be reworded for the recipient and "
                    "the connection."
                ),
            },
        },
        "required": [CONNECTION_ARGUMENT, WORDS_ARGUMENT],
        "additionalProperties": False,
    },
)
"""``send_text``'s declaration (ADR-0364 §9:1), offered on every round (ADR-0356 §4:3).

It is never selected, ruled on or run as a call: the phases take each ``send_text`` call
out of the round's calls before authorizing, which checks it by its connection alone as
the round's message is checked (ADR-0356 §7:7), and write it into its place under an
effect record as a message is written (§7:8). So nothing reads its egress fields, which
declare none: where a message may go is the message place check's, and its place's writer
holds the channel's rules (ADR-0306 §4:7, ADR-0292 §8:3).

``safe_to_repeat`` is set, so the offer adds no *deliberate repeat* mark: a message's
effect record is a message's, which carries no capability or values digest for
ADR-0306 §5:9's backstop to compare (ADR-0306 §6:1). Its description is the coordinator's
agreed words (ADR-0364 §2:1, §5), its effects line written by hand until lane T2's
generator writes it (§7:1).
"""

# --- send_text's arguments -------------------------------------------------------------

#: Why a ``send_text`` call runs nothing, by what was wrong with its arguments.
_NO_WORDS: Final = f"{WORDS_ARGUMENT!r} is what the message says, and it said nothing"
_NOT_A_CONNECTION: Final = f"{CONNECTION_ARGUMENT!r} names one connection, by its L label"
_UNDECLARED: Final = (
    f"{TEXT_CAPABILITY} takes {CONNECTION_ARGUMENT} and {WORDS_ARGUMENT}, and nothing else"
)
_DECLARED: Final = frozenset({CONNECTION_ARGUMENT, WORDS_ARGUMENT})


@dataclass(frozen=True, slots=True)
class TextArguments:
    """A ``send_text`` call's arguments, checked (ADR-0364 §9:1).

    Attributes:
        connection: The connection it goes into, by the ``L`` label planning named.
        words: What to say, as planning wrote it, its exact parts marked.
    """

    connection: str
    words: str


def text_arguments(arguments: Mapping[str, object]) -> TextArguments | str:
    """A ``send_text`` call's arguments, or why the call runs nothing (ADR-0364 §9:1-§9:2).

    ``send_text`` is never ruled on as a call, so its schema is checked here: a missing or
    wrong argument is never guessed, and an argument it does not declare is refused.

    Returns:
        The arguments, or the reason the call comes back refused.
    """
    if set(arguments) - _DECLARED:
        return _UNDECLARED
    words = arguments.get(WORDS_ARGUMENT)
    if not isinstance(words, str) or not words.strip():
        return _NO_WORDS
    connection = arguments.get(CONNECTION_ARGUMENT)
    if not isinstance(connection, str) or PLACE_LABEL.fullmatch(connection) is None:
        return _NOT_A_CONNECTION
    return TextArguments(connection=connection, words=words)


# --- exact parts (ADR-0364 §9:6-§9:9) -----------------------------------------------------

EXACT_OPEN: Final = "<exact>"
EXACT_CLOSE: Final = "</exact>"

#: A tag with the run of backslashes before it.
_TAG: Final = re.compile(r"(\\*)(<exact>|</exact>)")

#: Why words with exact parts come back not done (§9:8).
_UNCLOSED: Final = f"an {EXACT_OPEN} tag is never closed"
_NESTED: Final = f"an {EXACT_OPEN} tag is opened inside a part already marked exact"
_STRAY_CLOSE: Final = f"a {EXACT_CLOSE} tag closes no {EXACT_OPEN} tag"


@dataclass(frozen=True, slots=True)
class ExactWords:
    """A message's words with their exact parts read out (ADR-0364 §9:6-§9:8).

    Attributes:
        text: The words with every tag removed and every escape resolved.
        parts: Each part marked exact, as it reads in ``text``, in order.
    """

    text: str
    parts: tuple[str, ...] = ()


def exact_words(words: str) -> ExactWords | str:
    """``words`` with their exact parts read out, or why they come back not done (§9:8).

    An ``<exact>`` tag opens a part and ``</exact>`` closes it. A run of backslashes before
    a tag sends half of them, rounded down, as backslashes; where the run is odd the tag is
    sent as literal text, and where it is even, two backslashes for one included, the tag
    stays a tag. An unclosed tag, a tag opened inside a marked part, and a closing tag with
    none open each come back not done.

    Returns:
        The words read out, or the reason they come back not done.
    """
    text: list[str] = []
    parts: list[str] = []
    part: list[str] | None = None
    at = 0
    for found in _TAG.finditer(words):
        slashes, tag = found.group(1), found.group(2)
        before = words[at : found.start()] + "\\" * (len(slashes) // 2)
        at = found.end()
        literal = len(slashes) % 2 == 1
        piece = before + (tag if literal else "")
        text.append(piece)
        if part is not None:
            part.append(piece)
        if literal:
            continue
        if tag == EXACT_OPEN:
            if part is not None:
                return _NESTED
            part = []
        else:
            if part is None:
                return _STRAY_CLOSE
            parts.append("".join(part))
            part = None
    if part is not None:
        return _UNCLOSED
    text.append(words[at:])
    return ExactWords(text="".join(text), parts=tuple(parts))


def escaped_exact(words: str) -> str:
    """``words`` wrapped whole in an exact part, any tag they hold escaped first (§8:6).

    Each tag already in them, with the run of backslashes before it, is written so that
    :func:`exact_words` reads it back as the same literal text: the run doubled and one
    backslash more. So the wrapped words read back as ``words`` exactly, one part whole.
    """
    escaped = _TAG.sub(lambda found: "\\" * (2 * len(found.group(1)) + 1) + found.group(2), words)
    return f"{EXACT_OPEN}{escaped}{EXACT_CLOSE}"


# --- the wording step (ADR-0357 §4, ADR-0364 §9:7, §9:9) -----------------------------------


def reworded(words: ExactWords) -> str:
    """A message's words as they are sent (ADR-0364 §9:7, §9:9).

    The wording step, once built (ADR-0357 §4:5), may reword what no exact part marks.
    Until then the words are sent as written, with the tags removed. Each marked part
    must appear verbatim in what is sent; where one does not, planning's words are sent
    unchanged instead, their tags removed either way.
    """
    sent = words.text
    if any(part not in sent for part in words.parts):
        return words.text
    return sent


# --- where it went (ADR-0357 §3:1) ---------------------------------------------------------


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
