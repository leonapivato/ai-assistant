"""How the observer reads a model's reply as one object of a shape (ADR-0329 §16:4).

Every step's reply is read here, the scout's, framing's and placement's alike. A reply
that does not parse is no proposal, never a partial one: the attempt fails and is retried
(§16:4). A key the reply's shape does not name is dropped rather than refusing the reply:
every field it does name is validated as before, so a reply missing a required field, or
carrying a value of the wrong kind, still fails whole. A model's stray key, such as a
``"command": null`` beside a finding's own, is no reason to discard its findings.

A reply with prose around its object is read for that object, not refused for the prose:
the whole reply first, then a fenced block, then the last object standing on its own in
the text. Each is validated exactly as a bare reply is. An object found in the text is
taken only where it names a field of the shape, so a stray ``{}`` or an unrelated object
in the prose is never read as an empty answer; and no container, an object or an array, is
ever looked inside, nor a fence opened within one, so a nested piece of a malformed answer
is never read as the answer. A fence only marks a block as a candidate: it never cuts the
search, so a container left open inside a block still holds what follows the block.
"""

from __future__ import annotations

import json
import re
from typing import Final

from pydantic import BaseModel, ValidationError

__all__ = ["parsed"]


#: A fence opening a block, its tag group 1. It is matched only where the walk stands in
#: the reply's prose, outside any container, so never within a JSON string. Its tag is one
#: word, so no bracket of the reply is ever taken for part of a tag.
_OPENING: Final = re.compile(r"```[ \t]*([\w.+-]*)[ \t]*\n")

#: The fence closing a block, alone on its line: a JSON string holds no raw newline, so
#: backticks inside a fenced object's string never close its block.
_CLOSING: Final = re.compile(r"^[ \t]*```[ \t]*$", re.MULTILINE)

#: The tags a block offered as the reply carries: none, or ``json``.
_JSON_TAGS: Final = frozenset({"", "json", "JSON"})


def parsed[T: BaseModel](content: str, shape: type[T]) -> T | None:
    """A reply as one object of ``shape``, or ``None``: never a partial one.

    The whole reply is read first, with one enclosing Markdown code fence removed, as the
    understanding stage and the tidy-up remove it: a deterministic normalization of a
    wrapper, not a repair. Where the whole reply is not that object, because the model
    wrote prose around it, the object is looked for in the text: a fenced block, the last
    that validates; else an object standing on its own in the text, the last that
    validates. An object found in the text counts only where it names a field of
    ``shape``, and nothing inside a container, an object or an array, is a candidate.

    Args:
        content: The model's reply.
        shape: The model the reply must validate as.

    Returns:
        The object, or ``None`` where neither the reply nor any object in it validates.
    """
    body = content.strip()
    if body.startswith("```") and body.endswith("```") and len(body) >= 6:  # noqa: PLR2004 — two fences
        body = body[3:-3]
        newline = body.find("\n")
        if newline != -1 and body[:newline].strip() in {"", "json", "JSON"}:
            body = body[newline + 1 :]
    whole = _validated(body, shape)
    if whole is not None:
        return whole
    # A JSON value holds no raw carriage return, so line endings are one kind for the search.
    fenced, objects = _candidates(re.sub(r"\r\n?", "\n", content))
    for candidate in (*reversed(fenced), *reversed(objects)):
        if not _names_a_field(candidate, shape):
            continue
        found = _validated(candidate, shape)
        if found is not None:
            return found
    return None


def _validated[T: BaseModel](text: str, shape: type[T]) -> T | None:
    """``text`` validated as ``shape``, or ``None``: the one validation every reading uses."""
    try:
        return shape.model_validate_json(text)
    except ValidationError, ValueError, RecursionError:
        return None


def _names_a_field(text: str, shape: type[BaseModel]) -> bool:
    """Whether ``text`` is a JSON object carrying a key ``shape`` names."""
    try:
        value = json.loads(text)
    except ValueError, RecursionError:
        return False
    if not isinstance(value, dict):
        return False
    named = set(shape.model_fields)
    named.update(f.alias for f in shape.model_fields.values() if f.alias is not None)
    return not named.isdisjoint(value)


def _candidates(text: str) -> tuple[list[str], list[str]]:
    """The fenced blocks' bodies and the top-level JSON objects in ``text``, each in order.

    One walk finds both, so they share one rule: nothing inside a container, an object or
    an array, is a candidate, and neither is a fence opened inside one. Each ``{`` or
    ``[`` the walk meets starts a container. One that decodes is passed whole, an object
    kept as a candidate and an array's members never; one that does not decode is skipped
    as far as its brackets balance. A container whose brackets never balance ends the
    walk, since everything after it may be inside it.

    A fence the walk meets outside any container opens a block, which runs to its closing
    fence, alone on its line, or where none closes it to the end. A block untagged or
    tagged ``json`` offers its body as a candidate. A fence changes nothing else: the walk
    goes on through the block as through any other text, a container opened in it still
    open past its closing fence, and steps over that closing fence rather than taking it
    for an opening one.
    """
    decoder = json.JSONDecoder()
    fenced: list[str] = []
    objects: list[str] = []
    closings: dict[int, int] = {}
    index = 0
    while index < len(text):
        if index in closings:
            index = closings[index]
            continue
        opening = _OPENING.match(text, index)
        if opening is not None:
            closing = _CLOSING.search(text, opening.end())
            if closing is not None:
                closings[closing.start()] = closing.end()
            if opening.group(1).strip() in _JSON_TAGS:
                fenced.append(
                    text[opening.end() : len(text) if closing is None else closing.start()]
                )
            index = opening.end()
            continue
        if text[index] not in "{[":
            index += 1
            continue
        end = _past_container(decoder, text, index, objects)
        if end is None:
            break
        index = end
    return fenced, objects


def _past_container(
    decoder: json.JSONDecoder, text: str, start: int, objects: list[str]
) -> int | None:
    """The index past the container at ``start``, keeping it in ``objects`` if an object.

    One that decodes is passed whole, an array's members never kept; one that does not is
    skipped as far as its brackets balance. ``None`` where they never balance.
    """
    try:
        value, end = decoder.raw_decode(text, start)
    except ValueError, RecursionError:
        return _balanced_end(text, start)
    if isinstance(value, dict):
        objects.append(text[start:end])
    return end


#: Each closing bracket, and the opening one it closes.
_OPENS: Final = {"}": "{", "]": "["}


def _balanced_end(text: str, start: int) -> int | None:
    """The index just past the bracket closing the one at ``start``, or ``None``.

    Brackets inside a JSON string, with its backslash escapes, are not counted. A closing
    bracket of the wrong kind is no balance: ``None``, as for one never closed.
    """
    stack: list[str] = []
    index = start
    while index < len(text):
        char = text[index]
        if char == '"':
            index = _past_string(text, index)
            continue
        if char in "{[":
            stack.append(char)
        elif char in _OPENS:
            if not stack or stack.pop() != _OPENS[char]:
                return None
            if not stack:
                return index + 1
        index += 1
    return None


def _past_string(text: str, start: int) -> int:
    """The index just past the JSON string opening at ``start``; the end where none closes."""
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == '"':
            return index + 1
        else:
            index += 1
    return len(text)
