#!/usr/bin/env python3
"""Activation viewer: watch the diagnostic record's activations as they run (ADR-0316).

How to run it
-------------
Copy this one file to the server and start it there, **as the hub's user**, the one
account the record's files are readable by (ADR-0314 §2:3), with the hub's own Python::

    sudo -u <hub-user> <hub-python> -B activation_viewer.py <record-dir> [--port 8765]

``<record-dir>`` is the record's directory, ``<data_dir>/diagnostics``; a data directory
holding one is taken to mean it. The record has files only where the hub runs with
``ASSISTANT_DIAGNOSTIC_RECORD=true``. ``--port`` defaults to 8765. The viewer binds
``127.0.0.1`` alone, so reach it from your own machine through a tunnel::

    ssh -L 8765:127.0.0.1:8765 <server>

and open http://127.0.0.1:8765 in a browser there. Ctrl-C stops it.

It reads the record's files read-only and polls the directory, so an activation appears
and grows while it runs. It writes nothing, sends nothing anywhere, and prints only its
address and its failures by class, never anything an entry holds. ``-B`` keeps Python
from writing bytecode beside it.

What it is
----------
One file holding its server and its page, outside the ``ai_assistant`` package and
importing the standard library alone (ADR-0316 §2). It depends on ADR-0314 §6:2's line
alone: one JSON object holding ``activation_id``, ``source``, ``kind``, ``recorded_at``
and ``body``. The body keys it reads for the list and the timeline are hints (§5:2):
where one is missing, the hint is lost and the entry is still shown whole.

A model call (understanding's, a planning round's, a digest part's) also opens
readable: what it was told, split into its paragraphs; what it was given, its JSON a
key to a part; the tools it could call; what it did, part by part, with its usage
where the entry keeps one; and, for a planning round, what changed in its request
since the round before. Each part has its size, a token estimate, and a copy control;
the raw entries are one tab away.

An activation also walks, a step at a time, in its own order: what arrived, each run of
recall with what it kept, understanding's reading field by field, each planning round
with what came back from the round before and what it proposed, authorizing's verdicts,
acting and any digest, the end, and what the observer learned. Each step is a summary, and
opens its calls and entries in the drawer the timeline opens. Previous and Next, or the
arrow keys, move; the page's address names the step, as ``#<activation>/walk/<n>``.

What the observer learned from an activation is in the file beside its own,
``<activation_id>.observer.jsonl`` (ADR-0333 §3), joined to it by name and never listed as
an activation of its own. The activation's page shows it as a learning lane, attempt by
attempt, each on the observer's own instants, so it never widens the activation's
timeline; an activation whose own file is gone is shown with that lane alone. The
Learning view lists every activation the observer wrote about, its latest work first:
each finding's claim and outcome in short, a click from the scout's, framing's and each
placement's prompt and reply behind it (§5; ADR-0346 cut the commit step into framing and
placement, and a record from before it still shows its commit calls).

What a replay sent again over a copy of the hub's record is in a third file beside the
activation's, ``<activation_id>.replay.jsonl``, written by ``prompt_replay.py`` (ADR-0335
§6), and never listed as an activation of its own name. An activation with results is
marked in the list, and a model call's readable view shows each result that replays it
beside the original reply, headed by its prompt's name, version and origin, with the
candidate's instruction one click away (§6:4-§6:5). A run that sent a call several times
under one candidate (ADR-0337 §5:4) writes one result for each sample, and the samples
are shown together, under that candidate's one heading, each naming its sample. Where the
run asked the follow-up question (ADR-0337 §7), its answer as text, or its failure, is
shown beside the response it follows, with its version, and its question a click away.

What the owner's hub asked each recorded call afterwards, the follow-up question of
ADR-0337 §8, is in a fourth file beside the activation's, ``<activation_id>.followup.jsonl``,
joined to it by name and never listed as an activation of its own name (§8:17). A model
call's readable view shows each follow-up that follows it, its answer as text or its
failure, with the version of the follow-up prompt and the model it went to: a section of
its own beside the call, one click from it, and never on the timeline.
"""

from __future__ import annotations

import argparse
import bisect
import difflib
import hashlib
import itertools
import json
import math
import os
import re
import stat
import sys
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Final, override
from urllib.parse import parse_qs, urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

#: The one address the viewer binds (ADR-0316 §6:1). No option changes it.
HOST: Final = "127.0.0.1"

#: The port it listens on unless told otherwise.
DEFAULT_PORT: Final = 8765

#: Each activation's file's suffix (ADR-0314 §6:1).
SUFFIX: Final = ".jsonl"

#: The suffix of the file beside it holding what the observer learned from it (ADR-0333
#: §3:1). Never listed as an activation of its own name (§5:6).
OBSERVER_SUFFIX: Final = ".observer" + SUFFIX

#: The suffix of the file beside it holding what a replay sent again and got back (ADR-0335
#: §6:1). Never listed as an activation of its own name (§6:5).
REPLAY_SUFFIX: Final = ".replay" + SUFFIX

#: The suffix of the file beside it holding what the owner's hub asked its recorded calls
#: afterwards (ADR-0337 §8:12). Never listed as an activation of its own name (§8:17).
FOLLOW_UP_SUFFIX: Final = ".followup" + SUFFIX

#: The record's directory's name in a data directory (ADR-0314 §6:1).
RECORD_DIRECTORY: Final = "diagnostics"

#: The sources ADR-0314 §8 names; any other is shown in a lane of its own.
KNOWN_SOURCES: Final = frozenset(
    {"controller", "understanding", "recall", "planning", "authorizing", "digesting"}
)

#: The kinds ADR-0314 §8 names; any other is shown in a lane of its own.
KNOWN_KINDS: Final = frozenset({"given", "returned", "step"})

#: The phase lanes, in the order a pass runs them; a controller step for one of these
#: stages is drawn in its phase's lane, and every other step in the controller's.
PHASE_LANES: Final = ("recall", "understanding", "planning", "authorizing", "acting", "digesting")

#: Every lane the timeline always draws, in order (ADR-0316 §3:2).
LANES: Final = ("controller", *PHASE_LANES)

#: End rules under which the activation could not finish what it was asked: the badge
#: is read off the end entry alone (ADR-0317 §4:4). The round limit, a stage's failure,
#: a deadline (which ends ``stage_timed_out``) and the loop guard are ADR-0317 §3's
#: causes; a cancellation and a restart also cut the activation off before it finished.
#: A step that failed or timed out ends nothing where its stage tolerated it (ADR-0281
#: §5): the pass went on, and the step is shown as it ended.
COULD_NOT_FINISH_RULES: Final = frozenset(
    {
        "stage_failed",
        "stage_timed_out",
        "stage_repeated",
        "round_limit_reached",
        "interrupted",
        "hub_stopped",
    }
)

#: How much of the input the list shows.
INPUT_CHARS: Final = 160

#: The planning tool that carries a round's notes and mark, not a capability call.
ROUND_TOOL: Final = "planning_round"

#: Headers every response carries (ADR-0316 §6:5-§6:6).
SECURITY_HEADERS: Final = (
    ("Cache-Control", "no-store"),
    (
        "Content-Security-Policy",
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    ),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)

_READ_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC

#: What reading a line's JSON raises where it is not JSON, or nests too deep. Held as a
#: tuple so the file still parses on an interpreter older than the one it targets.
_UNPARSABLE: Final = (ValueError, RecursionError)
#: The largest whole number a browser's number holds exactly.
_SAFE_INTEGER: Final = 2**53 - 1

#: What reading an instant raises where a string is not one, or names no real instant.
_NO_INSTANT: Final = (ValueError, OverflowError, OSError)

#: What listing a record's directory raises where it does not exist yet.
_NO_DIRECTORY: Final = (FileNotFoundError, NotADirectoryError)

type Json = object
"""A value decoded from JSON: what an entry's body is."""


# --- reading the record ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Entry:
    """One line of ADR-0314 §6:2: an entry, read on the viewer's own terms.

    Attributes:
        line: Its line number in the file, from 0, which names it in a request.
        source: Who wrote it, known or not.
        kind: Given, returned, step, or a kind the viewer does not know.
        at: Its instant, as seconds since the epoch.
        recorded_at: Its instant as written.
        body: Its body, whole.
    """

    line: int
    source: str
    kind: str
    at: float
    recorded_at: str
    body: Json


@dataclass(frozen=True, slots=True)
class Truncation:
    """The file's truncation marker (ADR-0314 §6:3): the file's end, and when.

    Attributes:
        line: Its line number.
        at: Its instant, where it reads as one.
        truncated_at: Its instant as written.
    """

    line: int
    at: float | None
    truncated_at: str


type Line = Entry | Truncation | None
"""A complete line as the viewer reads it; ``None`` where it is unreadable."""


def instant(value: object) -> float | None:
    """An ISO 8601 instant as seconds since the epoch, or ``None`` where it is not one.

    Args:
        value: Anything a body holds.

    Returns:
        The instant, read as UTC where it names no offset.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    except _NO_INSTANT:
        return None


def _refuse_constant(name: str) -> object:
    msg = f"{name} is not JSON"
    raise ValueError(msg)


def _finite(text: str) -> float:
    """A JSON number as a float, refusing one too large to be finite, as ``1e400`` is."""
    value = float(text)
    if not math.isfinite(value):
        msg = "a number too large to be finite"
        raise ValueError(msg)
    return value


def parse_line(line: int, raw: bytes) -> Line:
    """Read one complete line (ADR-0316 §5).

    Args:
        line: Its line number in the file.
        raw: Its bytes, without the newline.

    Returns:
        The entry; the truncation marker; or ``None`` where the line is not one JSON
        object holding ``activation_id``, ``source``, ``kind``, ``recorded_at`` and
        ``body``, which counts as unreadable.
    """
    try:
        # NaN and the infinities are not JSON: a line holding one is unreadable, and
        # would otherwise reach the page as a body its JSON parser refuses.
        value = json.loads(raw, parse_constant=_refuse_constant, parse_float=_finite)
    except _UNPARSABLE:
        return None
    if not isinstance(value, dict):
        return None
    if value.get("truncated") is True and "source" not in value:
        written = value.get("truncated_at")
        text = written if isinstance(written, str) else ""
        return Truncation(line=line, at=instant(text), truncated_at=text)
    source, kind, recorded = value.get("source"), value.get("kind"), value.get("recorded_at")
    if not (
        isinstance(value.get("activation_id"), str)
        and isinstance(source, str)
        and isinstance(kind, str)
        and isinstance(recorded, str)
        and "body" in value
    ):
        return None
    at = instant(recorded)
    if at is None:
        return None
    return Entry(
        line=line, source=source, kind=kind, at=at, recorded_at=recorded, body=value["body"]
    )


def complete_lines(data: bytes, first: int = 0) -> tuple[list[Line], int]:
    """Every complete line of ``data``, read; a line with no newline yet is left alone.

    Args:
        data: Bytes read from a file, from a line's start.
        first: The line number of the first line in ``data``.

    Returns:
        The lines read, and how many bytes of ``data`` they took.
    """
    end = data.rfind(b"\n")
    if end < 0:
        return [], 0
    raws = data[:end].split(b"\n")
    return [parse_line(first + number, raw) for number, raw in enumerate(raws)], end + 1


def read_from(path: Path, offset: int) -> tuple[bytes, os.stat_result]:
    """Read a record file from ``offset``, read-only and never through a link.

    Args:
        path: The file, as the directory's listing named it.
        offset: Where to start.

    Returns:
        The bytes from ``offset`` to the end, and the file's status.

    Raises:
        OSError: If it cannot be opened, or is not a regular file.
    """
    descriptor = os.open(path, _READ_FLAGS)
    with os.fdopen(descriptor, "rb") as handle:
        status = os.fstat(handle.fileno())
        if not stat.S_ISREG(status.st_mode):
            msg = "not a regular file"
            raise OSError(msg)
        handle.seek(offset)
        return handle.read(), status


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, list) else ()


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def input_of(body: object) -> str | None:
    """The user's input in a rendered request, where the request shows it.

    Understanding's request carries it as ``input.text`` in its user message's JSON.
    The rendering is a hint (ADR-0316 §5:2): where it is not found, nothing is.

    Args:
        body: An understanding's or planning's given entry's body.

    Returns:
        The input's text, or ``None``.
    """
    document = _user_document(body)
    if document is None:
        return None
    received = document.get("input")
    if isinstance(received, str):
        return received
    return _text(_mapping(received).get("text"))


def _user_document(body: object) -> Mapping[str, object] | None:
    """A rendered request's last user message, read as the JSON object it carries."""
    for message in reversed(_sequence(_mapping(body).get("messages"))):
        shown = _mapping(message)
        content = _text(shown.get("content"))
        if shown.get("role") != "user" or content is None:
            continue
        try:
            document = json.loads(content)
        except _UNPARSABLE:
            return None
        return _mapping(document)
    return None


def arrival_of(lines: Sequence[Line]) -> dict[str, object] | None:
    """The activation's input as it arrived, read from the first request that shows it.

    The record keeps no entry of its own for the input, so this is read back from what a
    model was given: understanding's ``input``, or else the items of planning's place
    window marked as the input. The rendering is a hint (ADR-0316 §5:2): where neither is
    found, nothing is.

    Args:
        lines: The activation's complete lines.

    Returns:
        The input's text, where it came from and its messages with their instants, and
        which request it was read from; or ``None``.
    """
    for line in lines:
        if not isinstance(line, Entry) or line.kind != "given":
            continue
        document = _user_document(line.body)
        if document is None:
            continue
        if line.source == "understanding":
            received = _mapping(document.get("input"))
            text = _text(received.get("text"))
            if text is None:
                continue
            messages = [
                {
                    "position": _position(shown.get("position")),
                    "at": _ms(instant(shown.get("written_at"))),
                    "text": said,
                }
                for shown in map(_mapping, _sequence(received.get("messages")))
                if (said := _text(shown.get("text"))) is not None
            ]
            return {
                "from": "understanding",
                "line": line.line,
                "text": text,
                "received_as": _text(received.get("received_as")),
                "messages": messages,
            }
        if line.source == "planning":
            # Each message of the input is marked, a joined input's too: all of them, in
            # the window's order. The window shows no position, so none is shown.
            marked = [
                {"position": None, "at": _ms(instant(item.get("at"))), "text": said}
                for item in map(_mapping, _sequence(document.get("place_window")))
                if item.get("is_the_input") is True
                and (said := _text(item.get("text"))) is not None
            ]
            if marked:
                return {
                    "from": "planning",
                    "line": line.line,
                    "text": "\n".join(str(one["text"]) for one in marked),
                    "received_as": _text(_mapping(document.get("place")).get("description")),
                    "messages": marked,
                }
    return None


def _position(value: object) -> int | None:
    """A message's position where it is a whole number the page holds exactly, else none.

    Anything else is a hint not recognised (ADR-0316 §5:2): ``1e400`` decodes as an
    infinity, which no JSON response may carry. So it is dropped, and the message stays.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if abs(value) <= _SAFE_INTEGER else None


def _short(text: str, limit: int = INPUT_CHARS) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _ms(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds * 1000, 3)


def failed_digest(body: object) -> bool:
    """Whether a digesting returned entry says its digest, or a part of it, failed."""
    shown = _mapping(body)
    return shown.get("digest") == "failed" or "failure" in shown


# --- the list --------------------------------------------------------------------------


@dataclass(slots=True)
class Tally:
    """One activation's summary, fed its lines in order (ADR-0316 §3:1).

    Fed incrementally, so the list reads only what a file gained since it last looked.
    """

    activation_id: str
    first: float | None = None
    last: float | None = None
    ended: str | None = None
    ended_at: float | None = None
    input: str | None = None
    rounds: int = 0
    entries: int = 0
    unreadable: int = 0
    needs_you: bool = False
    refused: bool = False
    outside: bool = False
    could_not_finish: bool = False
    digest_failed: bool = False
    truncated: bool = False

    def _widen(self, *instants: float | None) -> None:
        for one in instants:
            if one is None:
                continue
            self.first = one if self.first is None else min(self.first, one)
            self.last = one if self.last is None else max(self.last, one)

    def feed(self, line: Line) -> None:
        """Take one more line into the summary."""
        if line is None:
            self.unreadable += 1
            return
        if isinstance(line, Truncation):
            self.truncated = True
            self._widen(line.at)
            return
        self.entries += 1
        self._widen(line.at)
        body = _mapping(line.body)
        if line.source == "controller" and line.kind == "step":
            self._step(body)
        elif line.source in {"understanding", "planning"} and line.kind == "given":
            if self.input is None:
                found = input_of(body)
                self.input = None if found is None else _short(found)
        elif line.source == "authorizing" and line.kind == "returned":
            self._authorized(body)
        elif line.source == "digesting" and line.kind == "returned" and failed_digest(body):
            self.digest_failed = True

    def _step(self, body: Mapping[str, object]) -> None:
        started, ended = instant(body.get("started_at")), instant(body.get("ended_at"))
        self._widen(started, ended)
        stage = body.get("stage")
        if stage == "planning":
            self.rounds += 1
        # Every hint is type-checked before it is used: a body of an unexpected shape
        # loses its hint and is still shown whole (ADR-0316 §5:2).
        if stage == "end":
            rule = _text(body.get("due"))
            self.ended, self.ended_at = rule, ended
            if rule in COULD_NOT_FINISH_RULES:
                self.could_not_finish = True

    def _authorized(self, body: Mapping[str, object]) -> None:
        for call in _sequence(body.get("calls")):
            verdict = _mapping(call).get("verdict")
            if verdict == "needs_you":
                self.needs_you = True
            elif verdict == "not_done":
                self.refused = True
        if _mapping(body.get("message")).get("allowed") is False:
            self.refused = True
        if body.get("read_outside_content") is True:
            self.outside = True

    def badges(self) -> list[str]:
        """The badges the list shows, in a fixed order."""
        shown = {
            "needs_you": self.needs_you,
            "outside_content": self.outside,
            "could_not_finish": self.could_not_finish,
            "digest_failed": self.digest_failed,
            "refused": self.refused,
            "truncated": self.truncated,
        }
        return [name for name, held in shown.items() if held]

    def summary(self) -> dict[str, object]:
        """What the list shows of this activation."""
        end = self.ended_at if self.ended_at is not None else self.last
        duration = None if self.first is None or end is None else end - self.first
        return {
            "id": self.activation_id,
            "start": _ms(self.first),
            "end": _ms(end),
            "last": _ms(self.last),
            "duration": _ms(duration),
            "input": self.input,
            "ended": self.ended,
            "rounds": self.rounds,
            "entries": self.entries,
            "unreadable": self.unreadable,
            "badges": self.badges(),
            "open": self.ended is None and not self.truncated,
        }


# --- the timeline ----------------------------------------------------------------------


def lane_of(entry: Entry) -> str:
    """The lane an entry is drawn in (ADR-0316 §3:2, §5:3)."""
    if entry.source == "controller" and entry.kind == "step":
        stage = _mapping(entry.body).get("stage")
        return stage if isinstance(stage, str) and stage in PHASE_LANES else "controller"
    if entry.kind not in KNOWN_KINDS:
        return f"{entry.source} · {entry.kind}"
    return entry.source


def _words(value: str) -> str:
    return value.replace("_", " ")


@dataclass(slots=True)
class _Timeline:
    """Builds one activation's timeline from its lines."""

    lines: Sequence[Line]
    entries: list[Entry] = field(default_factory=list)
    items: list[dict[str, object]] = field(default_factory=list)
    round_starts: list[float] = field(default_factory=list)
    spans: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    rounds: dict[int, dict[str, object]] = field(default_factory=dict)
    pairs: dict[int, int | None] = field(default_factory=dict)

    def round_of(self, at: float) -> int | None:
        number = bisect.bisect_right(self.round_starts, at)
        return number or None

    def build(self) -> None:
        self.entries = [one for one in self.lines if isinstance(one, Entry)]
        self._bound_rounds()
        given: dict[tuple[str, object, int | None], list[Entry]] = {}
        for entry in self.entries:
            if entry.source == "controller" and entry.kind == "step":
                self._step(entry)
            elif entry.source in KNOWN_SOURCES and entry.kind == "given":
                given.setdefault(self._pair_key(entry), []).append(entry)
            elif entry.source in KNOWN_SOURCES and entry.kind == "returned":
                # A response pairs only with a request inside the same step of its
                # stage, and with the latest still waiting there: a request whose
                # returned entry was never written (ADR-0314 §2:4) stays unanswered
                # rather than taking another step's or round's response.
                waiting = given.get(self._pair_key(entry))
                self._returned(entry, waiting.pop() if waiting else None)
            else:
                self._point(entry, entry.kind, f"{entry.source} {entry.kind}", "unknown")
        for waiting in given.values():
            for entry in waiting:
                self._call(entry, None)
        for line in self.lines:
            if isinstance(line, Truncation):
                self._truncation(line)

    def _step_of(self, stage: str, at: float) -> int | None:
        """Which recorded step of ``stage`` holds ``at``, by its place among them."""
        for number, (start, end) in enumerate(self.spans.get(stage, ())):
            if start <= at <= end:
                return number
        return None

    def _pair_key(self, entry: Entry) -> tuple[str, object, int | None]:
        return (entry.source, _pairing(entry), self._step_of(entry.source, entry.at))

    def _bound_rounds(self) -> None:
        """Where each planning round begins, from the steps and requests recorded.

        A recorded planning step is a round, from its start to its end, and holds the
        requests and responses written inside it. A planning request no step holds
        begins a round of its own: its step is still running, or its entry was never
        written (ADR-0314 §2:4). An entry belongs to the last round begun at or before
        it, so one missing entry costs its own round and never renumbers another.
        """
        for one in self.entries:
            body = _mapping(one.body)
            if one.source != "controller" or one.kind != "step":
                continue
            stage = _text(body.get("stage"))
            started, ended = instant(body.get("started_at")), instant(body.get("ended_at"))
            if stage is not None and started is not None and ended is not None:
                self.spans.setdefault(stage, []).append((started, ended))
        for spans in self.spans.values():
            spans.sort()
        bounds = [start for start, _end in self.spans.get("planning", ())]
        bounds += [
            one.at
            for one in self.entries
            if one.source == "planning"
            and one.kind == "given"
            and self._step_of("planning", one.at) is None
        ]
        self.round_starts = sorted(bounds)
        for number in range(1, len(bounds) + 1):
            self.rounds[number] = {"round": number, "calls": [], "verdicts": []}

    def _truncation(self, line: Truncation) -> None:
        at = line.at
        if at is None and self.entries:
            at = self.entries[-1].at
        if at is None:
            return
        self.items.append(
            {
                "lane": "controller",
                "type": "point",
                "kind": "truncated",
                "start": _ms(at),
                "end": _ms(at),
                "label": "truncated",
                "tone": "truncated",
                "lines": [line.line],
                "round": None,
            }
        )

    def _item(  # noqa: PLR0913 — every field an item carries
        self,
        entry: Entry,
        *,
        kind: str,
        start: float,
        end: float | None,
        label: str,
        tone: str,
        lines: list[int],
        lane: str | None = None,
    ) -> dict[str, object]:
        item: dict[str, object] = {
            "lane": lane_of(entry) if lane is None else lane,
            "type": "point" if end is not None and end == start and kind != "step" else "span",
            "kind": kind,
            "start": _ms(start),
            "end": _ms(end),
            "label": label,
            "tone": tone,
            "lines": lines,
            "round": self.round_of(start),
        }
        self.items.append(item)
        return item

    def _point(self, entry: Entry, kind: str, label: str, tone: str) -> None:
        self._item(
            entry,
            kind=kind,
            start=entry.at,
            end=entry.at,
            label=label,
            tone=tone,
            lines=[entry.line],
        )

    def _step(self, entry: Entry) -> None:
        body = _mapping(entry.body)
        stage = _text(body.get("stage")) or "step"
        started, ended = instant(body.get("started_at")), instant(body.get("ended_at"))
        outcome = _text(body.get("outcome")) or "unknown"
        if stage == "end" or started is None or ended is None:
            rule = _text(body.get("due"))
            label = f"end · {_words(rule)}" if stage == "end" and rule else _words(stage)
            at = ended if ended is not None else entry.at
            self._item(
                entry, kind="end" if stage == "end" else "step", start=at, end=at,
                label=label, tone="end" if stage == "end" else outcome, lines=[entry.line],
            )  # fmt: skip
            return
        label = _words(stage)
        number = self.round_of(started)
        if stage == "planning" and number is not None:
            label = f"round {number}"
            self.rounds[number]["step"] = {
                "start": _ms(started),
                "end": _ms(ended),
                "outcome": outcome,
                "line": entry.line,
            }
        self._item(
            entry, kind="step", start=started, end=ended, label=label, tone=outcome,
            lines=[entry.line],
        )  # fmt: skip

    def _returned(self, entry: Entry, given: Entry | None) -> None:
        if entry.source == "authorizing":
            self._authorized(entry)
            return
        self._call(given, entry) if given is not None else self._lone(entry)

    def _lone(self, entry: Entry) -> None:
        failed = "failure" in _mapping(entry.body) or (
            entry.source == "digesting" and failed_digest(entry.body)
        )
        self._point(entry, "returned", f"{entry.source} returned", "failed" if failed else "ok")
        if entry.source == "planning":
            self._round_response(entry)

    def _call(self, given: Entry, returned: Entry | None) -> None:
        body = _mapping(None if returned is None else returned.body)
        if returned is None:
            tone = "pending"
        elif "failure" in body or (given.source == "digesting" and failed_digest(body)):
            tone = "failed"
        else:
            tone = "ok"
        label = {
            "recall": "search",
            "understanding": "model call",
            "planning": "model call",
            "digesting": "digest part",
        }.get(given.source, given.source)
        if given.source == "recall":
            run = _text(_mapping(given.body).get("run"))
            label = f"{run} run" if run else label
        lines = [given.line] if returned is None else [given.line, returned.line]
        self.pairs[given.line] = None if returned is None else returned.line
        self._item(
            given, kind="call", start=given.at, end=None if returned is None else returned.at,
            label=label, tone=tone, lines=lines,
        )  # fmt: skip
        if given.source == "planning":
            number = self.round_of(given.at)
            if number is not None:
                self.rounds[number]["given"] = given.line
            if returned is not None:
                self._round_response(returned)

    def _round_response(self, entry: Entry) -> None:
        number = self.round_of(entry.at)
        if number is None:
            return
        held = self.rounds[number]
        held["returned"] = entry.line
        body = _mapping(entry.body)
        if "failure" in body:
            held["failure"] = _failure_text(body.get("failure"))
        texts: list[str] = []
        calls: list[dict[str, object]] = []
        thinking = False
        marked = False
        for part in _sequence(_mapping(body.get("response")).get("parts")):
            shown = _mapping(part)
            kind = shown.get("part_kind")
            if kind == "text" and isinstance(shown.get("content"), str):
                texts.append(str(shown["content"]))
            elif kind == "thinking":
                thinking = True
            elif kind == "tool-call":
                name = _text(shown.get("tool_name")) or "?"
                if name == ROUND_TOOL:
                    # The round's own tool: its `another_round` asks for another round.
                    arguments = _mapping(_arguments(shown.get("args")))
                    marked = marked or arguments.get("another_round") is True
                else:
                    calls.append({"id": _text(shown.get("tool_call_id")), "name": name})
        held["marked"] = marked
        held["text"] = "".join(texts)
        held["thinking"] = thinking
        held["calls"] = calls

    def _authorized(self, entry: Entry) -> None:
        body = _mapping(entry.body)
        verdicts = [
            {
                "call_id": _text(_mapping(one).get("call_id")),
                "name": _text(_mapping(one).get("name")),
                "verdict": _text(_mapping(one).get("verdict")),
                "reason": _text(_mapping(one).get("reason")),
            }
            for one in _sequence(body.get("calls"))
        ]
        shown = {one["verdict"] for one in verdicts}
        message = _mapping(body.get("message"))
        if "failure" in body:
            tone = "failed"
        elif "needs_you" in shown:
            tone = "needs_you"
        elif "not_done" in shown or message.get("allowed") is False:
            tone = "refused"
        else:
            tone = "ok"
        self._point(entry, "returned", "verdicts", tone)
        number = self.round_of(entry.at)
        if message.get("allowed") is True:
            # ADR-0316 §3:4: where authorizing allowed a message; acting and the message
            # writes write no entry, so nothing here says it was written.
            self._point(entry, "message", "message allowed", "message")
        held = self.rounds.get(number) if number is not None else None
        if held is not None:
            held["verdicts"] = verdicts
            held["authorizing"] = entry.line
            held["outside"] = body.get("read_outside_content") is True
            if message:
                held["message"] = {
                    "allowed": message.get("allowed") is True,
                    "reason": _text(message.get("reason")),
                }

    def result(self, activation_id: str) -> dict[str, object]:
        tally = Tally(activation_id)
        for line in self.lines:
            tally.feed(line)
        summary = tally.summary()
        known = set(LANES)
        extra = [
            one
            for one in dict.fromkeys(str(item["lane"]) for item in self.items)
            if one not in known
        ]
        truncation = next((one for one in self.lines if isinstance(one, Truncation)), None)
        return {
            "id": activation_id,
            "summary": summary,
            "arrival": arrival_of(self.lines),
            "start": summary["start"],
            "end": summary["end"],
            "lanes": [{"key": one, "known": True} for one in LANES]
            + [{"key": one, "known": False} for one in extra],
            "items": self.items,
            "rounds": [self.rounds[number] for number in sorted(self.rounds)],
            "entries": [
                {
                    "line": one.line,
                    "source": one.source,
                    "kind": one.kind,
                    "at": _ms(one.at),
                    "lane": lane_of(one),
                    "round": self.round_of(one.at),
                }
                for one in self.entries
            ],
            "truncated": None
            if truncation is None
            else {"at": _ms(truncation.at), "line": truncation.line},
            "unreadable": tally.unreadable,
        }


def _pairing(entry: Entry) -> object:
    """What pairs a returned entry with its given one: a digest's part, or nothing."""
    if entry.source != "digesting":
        return None
    body = _mapping(entry.body)
    return (repr(body.get("result")), repr(body.get("question")), repr(body.get("part")))


def _arguments(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except _UNPARSABLE:
            return None
    return value


def _failure_text(value: object) -> str:
    shown = _mapping(value)
    if shown:
        return " ".join(
            one for one in (_text(shown.get("class")), _text(shown.get("message"))) if one
        )
    return value if isinstance(value, str) else "failed"


def timeline(activation_id: str, lines: Sequence[Line]) -> dict[str, object]:
    """One activation's timeline: lanes, items, rounds and entries (ADR-0316 §3:2-§3:4).

    Args:
        activation_id: The activation, as its file is named.
        lines: Its file's complete lines, read.

    Returns:
        What the page draws. Times are milliseconds since the epoch; an item names the
        lines whose bodies a click shows.
    """
    built = _Timeline(lines)
    built.build()
    return built.result(activation_id)


# --- the learning lane and the overview (ADR-0333 §5) ------------------------------------
# What the observer learned from an activation is in the observer file beside the
# activation's own (ADR-0333 §3:1). Every key read here is a hint, as the timeline's are
# (ADR-0316 §5:2): a body of another shape loses its summary and is still shown whole.

#: The observer's steps that make a model call: the scout, framing and placement
#: (ADR-0346 §10:1), and ADR-0329 §9's commit step, which a record written before ADR-0346
#: still holds.
OBSERVER_CALLS: Final = frozenset({"scout", "commit", "framing", "placement"})

#: The steps whose call decides one finding, and whose given entry names it whole.
_FINDING_CALLS: Final = frozenset({"commit", "framing", "placement"})

#: What a write did, in short, by the operations it names, the first that applies.
_WRITE_WORDS: Final = (
    ("create", "memory created"),
    ("replace", "memory replaced"),
    ("mark_wrong", "memory marked wrong"),
    ("end", "memory ended"),
    ("raise_question", "question raised"),
    ("resolve_question", "question resolved"),
    ("add_support", "memory added to"),
)

#: Why a finding's commit wrote nothing, in short, by ``FindingUnwritten``'s values.
_UNWRITTEN_WORDS: Final = {
    "not_kept": "nothing in it was kept",
    "already_held": "already held as it would be written",
    "single_observation": "a single observation, left as evidence",
    "below_floor": "below the evidence floor",
    "check_failed": "failed a check",
    "refused": "the write path refused it",
    "asked": "the policy asked, naming no memory",
}

#: How much of a claim, a wording or a note the overview shows.
CLAIM_CHARS: Final = 240


def outcome_in_short(outcome: object) -> dict[str, object]:
    """A finding's outcome in short (ADR-0333 §5:5): what was kept, or that nothing was and why.

    Args:
        outcome: An outcome entry's ``outcome``, as the observation record gives it.

    Returns:
        ``kept``, the outcome in a few words, and, where nothing was kept, the reason's
        value and what it means.
    """
    held = _mapping(outcome)
    said: list[str] = []
    for write in _sequence(held.get("writes")):
        shown = _mapping(write)
        operations = {one for one in _sequence(shown.get("operations")) if isinstance(one, str)}
        word = next((text for kind, text in _WRITE_WORDS if kind in operations), None)
        if word is not None:
            said.append(word)
        if shown.get("track_record") is True:
            said.append("track record: held up")
        elif shown.get("track_record") is False:
            said.append("track record: let down")
    if said:
        return {"kept": True, "short": ", ".join(dict.fromkeys(said)), "reason": None, "why": None}
    reason = _text(held.get("unwritten"))
    why = (_UNWRITTEN_WORDS.get(reason) or _words(reason)) if reason else "no outcome recorded"
    return {"kept": False, "short": "nothing kept", "reason": reason, "why": why}


@dataclass(slots=True)
class _Try:
    """One attempt at the episode, as its entries name it (ADR-0333 §2:3)."""

    key: str
    episode: str | None
    started_at: str | None
    started: float | None
    first: float | None = None
    last: float | None = None
    ended: dict[str, object] | None = None
    items: list[dict[str, object]] = field(default_factory=list)
    scout: dict[str, int | None] = field(default_factory=dict)

    def widen(self, at: float) -> None:
        self.first = at if self.first is None else min(self.first, at)
        self.last = at if self.last is None else max(self.last, at)

    def shown(self, number: int) -> dict[str, object]:
        return {
            "key": self.key,
            "number": number,
            "episode": self.episode,
            "started_at": self.started_at,
            "start": _ms(self.first),
            "end": _ms(self.last),
            "ended": self.ended,
            "items": self.items,
        }


@dataclass(slots=True)
class Learned:
    """What one observer file says, fed its lines in order (ADR-0333 §5:2-§5:5).

    Fed incrementally, so the overview reads only what a file gained since it last
    looked; the activation's page feeds it the whole file. Its own instants are its
    own: nothing here reaches the activation's timeline or its row (§5:3).
    """

    activation_id: str
    entries: int = 0
    unreadable: int = 0
    truncated: bool = False
    latest: float | None = None
    episode: str | None = None
    dropped: int = 0
    tries: dict[str, _Try] = field(default_factory=dict)
    findings: list[dict[str, object]] = field(default_factory=list)
    current: dict[str, dict[str, object]] = field(default_factory=dict)
    waiting: dict[tuple[str, str, str | None], list[dict[str, object]]] = field(
        default_factory=dict
    )
    pairs: dict[int, int | None] = field(default_factory=dict)
    rows: list[dict[str, object]] = field(default_factory=list)

    def feed(self, line: Line) -> None:
        """Take one more line in."""
        if line is None:
            self.unreadable += 1
            return
        if isinstance(line, Truncation):
            self.truncated = True
            return
        self.entries += 1
        self.latest = line.at if self.latest is None else max(self.latest, line.at)
        body = _mapping(line.body)
        attempt = self._attempt(body)
        attempt.widen(line.at)
        stage = _text(body.get("stage"))
        self.rows.append(
            {"line": line.line, "stage": stage, "kind": line.kind, "at": _ms(line.at),
             "attempt": attempt.key}
        )  # fmt: skip
        if line.source != "observer" or stage is None:
            self._point(attempt, line, "unknown", f"{line.source} {line.kind}", "unknown")
        elif stage in OBSERVER_CALLS and line.kind in {"given", "returned"}:
            self._call(attempt, line, stage, body)
        elif line.kind == "step":
            self._step(attempt, line, stage, body)
        else:
            self._point(attempt, line, "unknown", f"{stage} {line.kind}", "unknown")

    def _attempt(self, body: Mapping[str, object]) -> _Try:
        episode, started_at = _text(body.get("episode")), _text(body.get("attempt_started_at"))
        if episode is not None:
            self.episode = episode
        key = f"{episode or ''}\0{started_at or ''}"
        held = self.tries.get(key)
        if held is None:
            held = _Try(key, episode, started_at, instant(started_at))
            self.tries[key] = held
        return held

    def _point(self, attempt: _Try, line: Entry, kind: str, label: str, tone: str) -> None:
        attempt.items.append(
            {"type": "point", "kind": kind, "start": _ms(line.at), "end": _ms(line.at),
             "label": label, "tone": tone, "lines": [line.line], "call": None}
        )  # fmt: skip

    def _call(self, attempt: _Try, line: Entry, stage: str, body: Mapping[str, object]) -> None:
        finding = _text(body.get("finding"))
        if finding is None:
            finding = _text(_mapping(body.get("finding")).get("id"))
        key = (attempt.key, stage, finding)
        if line.kind == "given":
            label = stage if finding is None else f"{stage} {finding}"
            item: dict[str, object] = {
                "type": "span", "kind": "call", "stage": stage, "start": _ms(line.at),
                "end": None, "label": label, "tone": "pending", "lines": [line.line],
                "call": line.line,
            }  # fmt: skip
            attempt.items.append(item)
            self.waiting.setdefault(key, []).append(item)
            self.pairs[line.line] = None
            if stage in _FINDING_CALLS and finding is not None and finding not in self.current:
                # Its findings entry is not in this file (written while the record was
                # off, say): the call's own given entry names the finding.
                self._stub(attempt, finding, _mapping(body.get("finding")).get("claim"))
            self._called(attempt, stage, finding, {"given": line.line, "returned": None})
            return
        waiting = self.waiting.get(key)
        if not waiting:
            failed = "failure" in body
            self._point(
                attempt, line, "returned", f"{stage} returned", "failed" if failed else "ok"
            )
            return
        item = waiting.pop()
        given = item["call"]
        assert isinstance(given, int)  # noqa: S101 — set just above, always a line
        item["end"] = _ms(line.at)
        item["tone"] = "failed" if "failure" in body else "ok"
        item["lines"] = [given, line.line]
        self.pairs[given] = line.line
        self._called(attempt, stage, finding, {"given": given, "returned": line.line})

    def _called(
        self, attempt: _Try, stage: str, finding: str | None, lines: dict[str, int | None]
    ) -> None:
        if stage == "scout":
            attempt.scout = lines
        elif finding is None or finding not in self.current:
            return
        elif stage == "placement":
            # One per memory framing kept (ADR-0346 §6:2): the returned entry closes the
            # placement its given entry opened.
            placements = self.current[finding]["placements"]
            assert isinstance(placements, list)  # noqa: S101 — set on every finding
            held = next((one for one in placements if one["given"] == lines["given"]), None)
            if held is None:
                placements.append(lines)
            else:
                held["returned"] = lines["returned"]
        else:
            self.current[finding][stage] = lines

    def _step(self, attempt: _Try, line: Entry, stage: str, body: Mapping[str, object]) -> None:
        if stage == "findings":
            proposed = [
                self._proposed(attempt, line, one) for one in _sequence(body.get("findings"))
            ]
            dropped = body.get("dropped")
            label = f"{len(proposed)} {'finding' if len(proposed) == 1 else 'findings'}"
            if isinstance(dropped, int) and not isinstance(dropped, bool) and dropped:
                label += f" · {dropped} dropped"
                self.dropped += dropped
            self._point(attempt, line, "findings", label, "findings")
        elif stage == "outcome":
            self._outcome(attempt, line, body)
        elif stage == "end":
            self._end(attempt, line, body)
        else:
            self._point(attempt, line, "unknown", _words(stage), "unknown")

    def _proposed(self, attempt: _Try, line: Entry, value: object) -> dict[str, object]:
        shown = _mapping(value)
        finding_id = _text(shown.get("id")) or f"#{len(self.findings) + 1}"
        record: dict[str, object] = {
            "id": finding_id,
            "claim": _text(shown.get("claim")),
            "parts": len(_sequence(shown.get("rests_on"))),
            "candidate": _text(shown.get("candidate")),
            "relied_on": _text(shown.get("relied_on")),
            "attempt": attempt.key,
            "findings_line": line.line,
            "scout": dict(attempt.scout),
            "commit": None,
            "framing": None,
            "placements": [],
            "outcome": None,
        }
        self.findings.append(record)
        self.current[finding_id] = record
        return record

    def _stub(self, attempt: _Try, finding_id: str, claim: object) -> dict[str, object]:
        """A finding no findings entry in this file named, known by its id and claim."""
        record: dict[str, object] = {
            "id": finding_id, "claim": _text(claim), "parts": None, "candidate": None,
            "relied_on": None, "attempt": attempt.key, "findings_line": None, "scout": {},
            "commit": None, "framing": None, "placements": [], "outcome": None,
        }  # fmt: skip
        self.findings.append(record)
        self.current[finding_id] = record
        return record

    def _outcome(self, attempt: _Try, line: Entry, body: Mapping[str, object]) -> None:
        finding_id = _text(body.get("finding")) or "?"
        record = self.current.get(finding_id)
        if record is None:
            # Its findings entry was never written, or is not this file's: the outcome
            # still names its claim.
            record = self._stub(attempt, finding_id, body.get("claim"))
        decided = _mapping(body.get("decided"))
        short = outcome_in_short(body.get("outcome"))
        held = _mapping(body.get("outcome"))
        record["outcome"] = {
            **short,
            **_decided_in_short(decided),
            "unclear": len(_sequence(held.get("unclear"))),
            "asked": len(_sequence(held.get("asked"))),
            "line": line.line,
            "attempt": attempt.key,
        }
        tone = "kept" if short["kept"] else "not_kept"
        self._point(attempt, line, "outcome", f"{finding_id} · {short['short']}", tone)

    def _end(self, attempt: _Try, line: Entry, body: Mapping[str, object]) -> None:
        end, state = _text(body.get("end")), _text(body.get("state"))
        failure = body.get("failure")
        attempt.ended = {
            "end": end,
            "state": state,
            "failure": None if failure is None else _failure_text(failure),
            "skipped": body.get("skipped") is not None,
            "line": line.line,
        }
        label = _words(state or end or "end")
        tone = {"failed": "failed", "held": "held"}.get(end or "", "end")
        self._point(attempt, line, "end", label, tone)

    def _ordered(self) -> list[_Try]:
        return sorted(
            self.tries.values(),
            key=lambda one: one.started if one.started is not None else math.inf,
        )

    def summary(self) -> dict[str, object]:
        """What the learning overview shows of this activation (ADR-0333 §5:4-§5:5)."""
        ordered = self._ordered()
        last = ordered[-1] if ordered else None
        ended = None if last is None else last.ended
        return {
            "id": self.activation_id,
            "latest": _ms(self.latest),
            "entries": self.entries,
            "unreadable": self.unreadable,
            "truncated": self.truncated,
            "episode": self.episode,
            "attempts": len(ordered),
            "failed": sum(1 for one in ordered if (one.ended or {}).get("end") == "failed"),
            "dropped": self.dropped,
            "state": None if ended is None else ended["state"],
            "end": None if ended is None else ended["end"],
            "failure": None if ended is None else ended["failure"],
            "findings": [_in_short(one) for one in self.findings],
        }

    def lane(self) -> dict[str, object]:
        """The learning lane an activation's page draws, grouped by attempt (§5:2)."""
        ordered = self._ordered()
        return {
            "latest": _ms(self.latest),
            "episode": self.episode,
            "attempts": [one.shown(number) for number, one in enumerate(ordered, 1)],
            "findings": self.findings,
            "entries": self.rows,
            "unreadable": self.unreadable,
            "truncated": self.truncated,
        }


def _decided_in_short(decided: Mapping[str, object]) -> dict[str, object]:
    """What a finding's calls decided, in short: an action, a wording and a note.

    Framing's (ADR-0346 §5): each memory it kept, joined, and its reason where it kept
    nothing, or how many memories a check refused. The commit step's, for a record written
    before ADR-0346: its action, its wording or a question's, and its note.
    """
    if "framed" in decided:
        framed = [_mapping(one) for one in _sequence(decided.get("framed"))]
        kept = [
            wording
            for one in framed
            if one.get("refused") is None and (wording := _text(one.get("wording")))
        ]
        refused = sum(1 for one in framed if one.get("refused") is not None)
        note = _text(decided.get("nothing"))
        if note is None and refused:
            note = f"{refused} framed {'memory' if refused == 1 else 'memories'} failed a check"
        return {"action": "frame", "wording": " · ".join(kept) or None, "note": note}
    action = _text(decided.get("action"))
    said = decided.get("asks") if action == "raise_question" else decided.get("wording")
    return {"action": action, "wording": _text(said), "note": _text(decided.get("note"))}


def _in_short(record: Mapping[str, object]) -> dict[str, object]:
    """A finding as the overview lists it: its claim and outcome in short, and its lines."""
    claim = _text(record.get("claim"))
    outcome = _mapping(record.get("outcome"))
    shown: dict[str, object] = {
        "id": record.get("id"),
        "claim": None if claim is None else _short(claim, CLAIM_CHARS),
        "findings_line": record.get("findings_line"),
        "scout": record.get("scout"),
        "commit": record.get("commit"),
        "framing": record.get("framing"),
        "placements": record.get("placements") or [],
        "outcome": None,
    }
    if outcome:
        wording, note = _text(outcome.get("wording")), _text(outcome.get("note"))
        shown["outcome"] = {
            **outcome,
            "wording": None if wording is None else _short(wording, CLAIM_CHARS),
            "note": None if note is None else _short(note, CLAIM_CHARS),
        }
    return shown


def learning_lane(activation_id: str, lines: Sequence[Line]) -> dict[str, object]:
    """An activation's learning lane, from its observer file's lines (ADR-0333 §5:2).

    Args:
        activation_id: The activation, as its observer file is named.
        lines: That file's complete lines, read.

    Returns:
        Its attempts, each with its own items over its own instants, its findings with
        their outcomes, and every entry; times are milliseconds since the epoch.
    """
    learned = Learned(activation_id)
    for line in lines:
        learned.feed(line)
    return learned.lane()


# --- the record's directory --------------------------------------------------------------


@dataclass(slots=True)
class _Watched:
    """What the list knows of one file: how far it has read it, and its summary."""

    identity: tuple[int, int]
    offset: int
    lines: int
    tally: Tally


@dataclass(slots=True)
class _WatchedLearning:
    """What the overview knows of one observer file: how far it has read it, and what."""

    identity: tuple[int, int]
    offset: int
    lines: int
    learned: Learned


class Record:
    """The record's directory, read-only, followed by polling (ADR-0316 §4).

    It opens files for reading alone and creates nothing; what it keeps between polls
    is in memory, per file, and dropped when the file is.
    """

    def __init__(self, root: Path) -> None:
        """Point the viewer at the record.

        Args:
            root: The record's directory, or a data directory holding one.
        """
        self._root = root
        self._lock = threading.Lock()
        self._watched: dict[str, _Watched] = {}
        self._learned: dict[str, _WatchedLearning] = {}

    @property
    def directory(self) -> Path:
        """The record's directory: ``root/diagnostics`` where that exists, else ``root``."""
        inner = self._root / RECORD_DIRECTORY
        return inner if inner.is_dir() else self._root

    def listing(self) -> dict[str, Path]:
        """Every activation's own file in the directory, by its id (ADR-0316 §6:3).

        Returns:
            Empty where the directory does not exist yet.
        """
        return self._scan()[0]

    def learned_listing(self) -> dict[str, Path]:
        """Every observer file in the directory, by its activation's id (ADR-0333 §5:1)."""
        return self._scan()[1]

    def replay_listing(self) -> dict[str, Path]:
        """Every replay's results file in the directory, by its activation's id (ADR-0335 §6:1)."""
        return self._scan()[2]

    def follow_up_listing(self) -> dict[str, Path]:
        """Every follow-up file in the directory, by its activation's id (ADR-0337 §8:17)."""
        return self._scan()[3]

    def _scan(
        self,
    ) -> tuple[dict[str, Path], dict[str, Path], dict[str, Path], dict[str, Path]]:
        """The directory's activations' own files, observer, results and follow-up files, by id.

        An observer file, a results file or a follow-up file is joined to its activation by
        name alone, and is never taken for an activation of its own name (ADR-0333 §5:1,
        §5:6; ADR-0335 §6:5; ADR-0337 §8:17).
        """
        own: dict[str, Path] = {}
        beside: dict[str, dict[str, Path]] = {
            OBSERVER_SUFFIX: {},
            REPLAY_SUFFIX: {},
            FOLLOW_UP_SUFFIX: {},
        }
        directory = self.directory
        try:
            with os.scandir(directory) as entries:
                for one in entries:
                    if not one.name.endswith(SUFFIX) or not one.is_file(follow_symlinks=False):
                        continue
                    suffix = next((each for each in beside if one.name.endswith(each)), SUFFIX)
                    held = beside.get(suffix, own)
                    held[one.name[: -len(suffix)]] = directory / one.name
        except _NO_DIRECTORY:
            return {}, {}, {}, {}
        return own, beside[OBSERVER_SUFFIX], beside[REPLAY_SUFFIX], beside[FOLLOW_UP_SUFFIX]

    def activations(self) -> dict[str, object]:
        """The list: every activation's summary, newest first, and a version for polling.

        An activation with a replay's results file is marked ``replayed`` (ADR-0335 §6:5).
        """
        listing, _, replayed, _ = self._scan()
        with self._lock:
            for gone in set(self._watched) - set(listing):
                del self._watched[gone]
            versions: list[str] = []
            for activation_id, path in sorted(listing.items()):
                try:
                    status = self._follow(activation_id, path)
                except OSError:
                    self._watched.pop(activation_id, None)
                    continue
                versions.append(f"{activation_id}\0{status.st_size}\0{status.st_mtime_ns}")
                if activation_id in replayed:
                    versions.append(f"{activation_id}\0replayed")
            summaries = [_marked(one.tally.summary(), replayed) for one in self._watched.values()]
        summaries.sort(key=lambda one: _sort_key(one.get("start")), reverse=True)
        version = hashlib.blake2b("\n".join(versions).encode(), digest_size=12).hexdigest()
        return {
            "version": version,
            "present": self.directory.is_dir(),
            "activations": summaries,
        }

    def _follow(self, activation_id: str, path: Path) -> os.stat_result:
        """Read what a file gained since the last poll, up to its last complete line."""
        watched = self._watched.get(activation_id)
        status = path.stat(follow_symlinks=False)
        identity = (status.st_dev, status.st_ino)
        if watched is not None and (
            watched.identity != identity or status.st_size < watched.offset
        ):
            watched = None
        if watched is None:
            watched = _Watched(identity, 0, 0, Tally(activation_id))
            self._watched[activation_id] = watched
        if status.st_size == watched.offset:
            return status
        data, status = read_from(path, watched.offset)
        read, taken = complete_lines(data, watched.lines)
        for line in read:
            watched.tally.feed(line)
        watched.offset += taken
        watched.lines += len(read)
        return status

    def lines(self, activation_id: str) -> tuple[list[Line], str] | None:
        """An activation's complete lines, read, and a version for polling.

        Args:
            activation_id: An id, looked up in the directory's listing and never used
                as a path.

        Returns:
            ``None`` where no file in the listing has that id.
        """
        return _whole(self.listing().get(activation_id))

    def learned_lines(self, activation_id: str) -> tuple[list[Line], str] | None:
        """An activation's observer file's complete lines, read, and a version.

        Args:
            activation_id: An id, looked up in the directory's listing and never used
                as a path.

        Returns:
            ``None`` where no observer file in the listing has that id.
        """
        return _whole(self.learned_listing().get(activation_id))

    def replay_lines(self, activation_id: str) -> tuple[list[Line], str] | None:
        """An activation's results file's complete lines, read, and a version.

        Args:
            activation_id: An id, looked up in the directory's listing and never used
                as a path.

        Returns:
            ``None`` where no results file in the listing has that id.
        """
        return _whole(self.replay_listing().get(activation_id))

    def follow_up_lines(self, activation_id: str) -> tuple[list[Line], str] | None:
        """An activation's follow-up file's complete lines, read, and a version.

        Args:
            activation_id: An id, looked up in the directory's listing and never used
                as a path.

        Returns:
            ``None`` where no follow-up file in the listing has that id.
        """
        return _whole(self.follow_up_listing().get(activation_id))

    def learning(self) -> dict[str, object]:
        """The learning overview: every activation with an observer file (ADR-0333 §5:4).

        Each observer file is followed as the list follows an activation's own file,
        reading only what it gained since the last poll; an activation's input comes
        from its own file's summary where that file is in the listing.

        Returns:
            Each activation's learning summary, newest observer entry first, and a
            version for polling.
        """
        own, learned, _, _ = self._scan()
        with self._lock:
            for gone in set(self._learned) - set(learned):
                del self._learned[gone]
            versions: list[str] = []
            summaries: list[dict[str, object]] = []
            for activation_id, path in sorted(learned.items()):
                try:
                    status = self._follow_learned(activation_id, path)
                except OSError:
                    self._learned.pop(activation_id, None)
                    continue
                versions.append(f"{activation_id}\0{status.st_size}\0{status.st_mtime_ns}")
                summary = self._learned[activation_id].learned.summary()
                summary["input"] = None
                summary["own"] = activation_id in own
                if activation_id in own:
                    try:
                        own_status = self._follow(activation_id, own[activation_id])
                    except OSError:
                        summary["own"] = False
                    else:
                        tally = self._watched[activation_id].tally
                        summary["input"] = tally.input
                        versions.append(f"{activation_id}\0own\0{own_status.st_size}")
                summaries.append(summary)
        summaries.sort(key=lambda one: _sort_key(one.get("latest")), reverse=True)
        version = hashlib.blake2b("\n".join(versions).encode(), digest_size=12).hexdigest()
        return {"version": version, "present": self.directory.is_dir(), "activations": summaries}

    def _follow_learned(self, activation_id: str, path: Path) -> os.stat_result:
        """Read what an observer file gained since the last poll, as :meth:`_follow` does."""
        watched = self._learned.get(activation_id)
        status = path.stat(follow_symlinks=False)
        identity = (status.st_dev, status.st_ino)
        if watched is not None and (
            watched.identity != identity or status.st_size < watched.offset
        ):
            watched = None
        if watched is None:
            watched = _WatchedLearning(identity, 0, 0, Learned(activation_id))
            self._learned[activation_id] = watched
        if status.st_size == watched.offset:
            return status
        data, status = read_from(path, watched.offset)
        read, taken = complete_lines(data, watched.lines)
        for line in read:
            watched.learned.feed(line)
        watched.offset += taken
        watched.lines += len(read)
        return status


def _marked(summary: dict[str, object], replayed: Mapping[str, Path]) -> dict[str, object]:
    """An activation's summary, marked where a replay's results file is beside it (§6:5)."""
    if summary.get("id") not in replayed:
        return {**summary, "replayed": False}
    badges = summary.get("badges")
    listed = list(badges) if isinstance(badges, list) else []
    return {**summary, "replayed": True, "badges": [*listed, "replayed"]}


def _whole(path: Path | None) -> tuple[list[Line], str] | None:
    """A listed file's complete lines, read, and a version for polling; ``None`` if gone."""
    if path is None:
        return None
    try:
        data, status = read_from(path, 0)
    except OSError:
        return None
    read, taken = complete_lines(data)
    return read, f"{status.st_ino}:{taken}:{status.st_mtime_ns}"


def _sort_key(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def entry_of(lines: Sequence[Line], number: int) -> dict[str, object] | None:
    """One line, whole, as a click shows it (ADR-0316 §3:3).

    Args:
        lines: The activation's complete lines.
        number: The line's number.

    Returns:
        ``None`` where there is no such line.
    """
    if not 0 <= number < len(lines):
        return None
    line = lines[number]
    if line is None:
        return {"line": number, "unreadable": True}
    if isinstance(line, Truncation):
        return {"line": number, "truncated_at": line.truncated_at, "at": _ms(line.at)}
    return {
        "line": number,
        "source": line.source,
        "kind": line.kind,
        "recorded_at": line.recorded_at,
        "at": _ms(line.at),
        "lane": lane_of(line),
        "body": line.body,
    }


# --- a model call, readable ------------------------------------------------------------
# What a model was told, given and offered, and what it did, read from a given entry and
# the returned entry paired with it, beside the bodies shown whole (ADR-0316 §3:3). Every
# key read here is a hint (§5:2): where one is missing or of another shape, its part is
# left out and said so, and the raw entries still show the bodies whole.

#: The sources whose given and returned entries are a model call.
MODEL_SOURCES: Final = frozenset({"understanding", "planning", "digesting"})

#: Characters per token, for the estimate the view shows where the record counts none.
CHARS_PER_TOKEN: Final = 4

#: The most parts a text or an object splits into; the rest is kept as one last part.
MAX_PARTS: Final = 400

#: The longest text either side of a changed part may be for its diff to be drawn.
DIFF_CHARS: Final = 400_000

#: The most lines one changed part's diff shows.
DIFF_LINES: Final = 800

#: The most lines either side of a changed part's middle may have for its diff to be
#: drawn, the lines both sides share at the start and the end set aside.
DIFF_SPAN: Final = 3_000

#: The lines of context a diff shows around each change.
DIFF_CONTEXT: Final = 2

#: How deep, and how many, a value's nested lists are counted.
LIST_DEPTH: Final = 6
LIST_PATHS: Final = 40

#: The longest line a block may be and still read as a heading.
HEADING_CHARS: Final = 80

#: What a returned entry that keeps the reply alone says of its usage (#3090).
NO_USAGE: Final = (
    "This entry records no token usage: understanding's and digesting's returned entries "
    "keep the reply alone (#3090)."
)

#: What the observer's returned entry, which keeps the reply alone, says of its usage.
NO_OBSERVER_USAGE: Final = (
    "This entry records no token usage: the observer's returned entries keep the reply "
    "alone (ADR-0333 §2:1)."
)

_BLANK_LINE: Final = re.compile(r"\n[ \t]*\n")
_MARKDOWN_HEADING: Final = re.compile(r"#{1,6}[ \t]+(\S.*?)[ \t#]*")

#: The usage a provider's response carries, as pydantic-ai names it, and as shown.
_USAGE_KEYS: Final = (
    ("input_tokens", "input"),
    ("output_tokens", "output"),
    ("cache_read_tokens", "cache read"),
    ("cache_write_tokens", "cache write"),
)


def estimate(chars: int) -> int:
    """A token count estimated from a length in characters: an estimate, never a count."""
    return math.ceil(chars / CHARS_PER_TOKEN)


def _sized(text: str, **shown: object) -> dict[str, object]:
    return {**shown, "text": text, "chars": len(text), "tokens": estimate(len(text))}


def _pretty(value: object) -> str:
    return json.dumps(value, indent=1, ensure_ascii=False)


def _sent(value: object) -> int:
    """A value's length as a request carries it: JSON, compact, ASCII with escapes."""
    return len(json.dumps(value, ensure_ascii=True))


def _object_in(text: str) -> dict[str, object] | None:
    """The JSON object a message's text is, or ``None`` where it is not one."""
    if not text.lstrip().startswith("{"):
        return None
    try:
        value = json.loads(text, parse_constant=_refuse_constant, parse_float=_finite)
    except _UNPARSABLE:
        return None
    return value if isinstance(value, dict) else None


def _readable(text: str) -> str:
    """A reply's text, laid out where it is JSON and kept as it is where it is not."""
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return text
    try:
        return _pretty(json.loads(stripped, parse_constant=_refuse_constant, parse_float=_finite))
    except _UNPARSABLE:
        return text


def _heading(line: str, *, alone: bool) -> str | None:
    """A block's first line as a heading, where the text makes it one.

    A Markdown heading is one wherever it stands; a short line standing alone as its
    block is one where it ends in a colon or is written in capitals.
    """
    stripped = line.strip()
    marked = _MARKDOWN_HEADING.fullmatch(stripped)
    if marked is not None:
        return marked.group(1)
    if not alone or len(stripped) > HEADING_CHARS:
        return None
    if stripped.endswith(":") or stripped.isupper():
        return stripped.rstrip(":").strip() or None
    return None


def instruction_sections(text: str) -> list[dict[str, object]]:
    """Instructions split into their parts: paragraphs, under the headings they have.

    Args:
        text: The instructions, as the request's system messages carry them.

    Returns:
        Each section's heading, or ``None`` before the first, and its parts, numbered
        in order across the sections, each with its size and a token estimate.
    """
    blocks = [one.strip("\n") for one in _BLANK_LINE.split(text.replace("\r\n", "\n"))]
    blocks = [one for one in blocks if one.strip()]
    sections: list[dict[str, object]] = [{"heading": None, "parts": []}]
    number = 0
    for index, block in enumerate(blocks):
        parts = _sequence_of(sections[-1])
        if number >= MAX_PARTS:
            parts.append(_sized("\n\n".join(blocks[index:]), n=number + 1, rest=True))
            break
        first, newline, after = block.partition("\n")
        found = _heading(first, alone=not newline)
        text = block
        if found is not None:
            sections.append({"heading": found, "parts": []})
            text = after.strip("\n")
            if not text.strip():
                continue
        number += 1
        _sequence_of(sections[-1]).append(_sized(text, n=number))
    return [one for one in sections if one["heading"] is not None or one["parts"]]


def _sequence_of(section: dict[str, object]) -> list[dict[str, object]]:
    parts = section["parts"]
    assert isinstance(parts, list)  # noqa: S101 — built just above, always a list
    return parts


def _kind_of(value: object) -> str:
    if isinstance(value, dict):
        return f"object · {len(value)} {'key' if len(value) == 1 else 'keys'}"
    if isinstance(value, list):
        return f"list · {len(value)} {'item' if len(value) == 1 else 'items'}"
    if isinstance(value, str):
        return "text"
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    return "number"


def nested_lists(value: object, path: str) -> list[dict[str, object]]:
    """Every list a value holds, by its path, with how many it holds.

    Args:
        value: A top-level value of a request's JSON.
        path: Its key.

    Returns:
        Each path's lists and their items in all, as ``stories[].notes`` for the
        notes of every story; at most :data:`LIST_PATHS` paths, :data:`LIST_DEPTH` deep.
    """
    found: dict[str, list[int]] = {}
    pending: list[tuple[object, str, int]] = [(value, path, 0)]
    while pending:
        one, where, depth = pending.pop()
        if depth > LIST_DEPTH:
            continue
        if isinstance(one, list):
            if where in found or len(found) < LIST_PATHS:
                found.setdefault(where, []).append(len(one))
            pending.extend((item, f"{where}[]", depth + 1) for item in reversed(one))
        elif isinstance(one, dict):
            pending.extend(
                (item, f"{where}.{key}", depth + 1) for key, item in reversed(one.items())
            )
    return [
        {"path": where, "lists": len(counts), "items": sum(counts)}
        for where, counts in found.items()
    ]


def _messages_of(body: object) -> list[tuple[str, object]] | None:
    listed = _mapping(body).get("messages")
    if not isinstance(listed, list):
        return None
    shown: list[tuple[str, object]] = []
    for one in listed:
        message = _mapping(one)
        role = message.get("role")
        shown.append((role if isinstance(role, str) else "message", message.get("content")))
    return shown


def _told(messages: Sequence[tuple[str, object]]) -> dict[str, object] | None:
    """What the request told the model: its system messages, split into their parts."""
    texts = [content for role, content in messages if role == "system"]
    if not texts:
        return None
    text = "\n\n".join(one if isinstance(one, str) else _pretty(one) for one in texts)
    return {
        "messages": len(texts),
        "chars": len(text),
        "tokens": estimate(len(text)),
        "sections": instruction_sections(text),
    }


def _given(messages: Sequence[tuple[str, object]]) -> list[dict[str, object]]:
    """What the request gave the model: every other message, its JSON split by key."""
    shown: list[dict[str, object]] = []
    others = [(role, content) for role, content in messages if role != "system"]
    for index, (role, content) in enumerate(others, 1):
        about: dict[str, object] = {"index": index, "role": role}
        if not isinstance(content, str):
            shown.append({**about, "form": "text", "odd": True, **_sized(_pretty(content))})
            continue
        document = _object_in(content)
        if document is None:
            shown.append({**about, "form": "text", **_sized(content)})
            continue
        keys: list[dict[str, object]] = []
        items = list(document.items())
        for key, value in items[:MAX_PARTS]:
            size = _sent(value)
            keys.append(
                {
                    "key": key,
                    "kind": _kind_of(value),
                    "chars": size,
                    "tokens": estimate(size),
                    "lists": nested_lists(value, key),
                    "text": _pretty(value),
                }
            )
        if len(items) > MAX_PARTS:
            rest = dict(items[MAX_PARTS:])
            keys.append({"key": "…", "kind": _kind_of(rest), "rest": True, **_sized(_pretty(rest))})
        shown.append(
            {
                **about,
                "form": "json",
                "chars": len(content),
                "tokens": estimate(len(content)),
                "keys": keys,
            }
        )
    return shown


def _tools(listed: object, origin: str) -> dict[str, object] | None:
    """The tools a request offered, by name and description, their schemas apart."""
    if not isinstance(listed, list):
        return None
    tools: list[dict[str, object]] = []
    for one in listed:
        tool = _mapping(one)
        name = _text(tool.get("name"))
        if not name:
            continue
        schema = tool.get("parameters")
        size = _sent(one)
        tools.append(
            {
                "name": name,
                "description": _text(tool.get("description")) or "",
                "schema": None if schema is None else _pretty(schema),
                "chars": size,
                "tokens": estimate(size),
                "reserved": name == ROUND_TOOL,
            }
        )
    return {"from": origin, "tools": tools, "unnamed": len(listed) - len(tools)}


def _usage(value: object) -> dict[str, int] | None:
    usage = _mapping(value)
    shown: dict[str, int] = {}
    for key, label in _USAGE_KEYS:
        count = usage.get(key)
        if isinstance(count, int) and not isinstance(count, bool):
            shown[label] = count
    return shown or None


def _arguments_text(raw: object, parsed: object) -> str:
    """A call's arguments as text: laid out where they read as JSON, as written where not."""
    if parsed is None and isinstance(raw, str):
        return raw
    return _pretty(raw if parsed is None else parsed)


def _round_tool_parts(raw: object, call_id: str | None) -> list[dict[str, object]]:
    """The round's own tool's call, as the notes and the asks it carries.

    Where its arguments are not of the tool's shape, as a round that did not read as one
    may hold, the call is also shown with its arguments as they were written.
    """
    parsed = _arguments(raw)
    held = _mapping(parsed)
    parts: list[dict[str, object]] = []
    notes, asks = held.get("notes"), held.get("asks")
    if isinstance(notes, str):
        parts.append(_sized(notes, kind="notes", title="Episode notes"))
    named = asks if isinstance(asks, list) and all(isinstance(one, str) for one in asks) else None
    if named is not None:
        parts.append({**_sized("\n".join(named), kind="asks", title="Asks named"), "items": named})
    shaped = (
        isinstance(parsed, dict)
        and not set(held) - {"notes", "asks"}
        and (notes is None or isinstance(notes, str))
        and (asks is None or named is not None)
    )
    if not shaped:
        title = f"Call · {ROUND_TOOL} · arguments not of its shape"
        parts.append(_sized(_arguments_text(raw, parsed), kind="call", title=title, id=call_id))
    return parts


def _response_part(part: object) -> list[dict[str, object]]:
    """One part of a provider's response, as the view shows it."""
    shown = _mapping(part)
    kind = shown.get("part_kind")
    content = shown.get("content")
    if kind == "text" and isinstance(content, str):
        return [_sized(content, kind="text", title="Text")]
    if kind == "thinking":
        text = content if isinstance(content, str) else ""
        return [_sized(text, kind="thinking", title="Thinking (the provider's summary)")]
    if kind == "tool-call":
        name = _text(shown.get("tool_name")) or "?"
        call_id = _text(shown.get("tool_call_id"))
        raw = shown.get("args")
        if name == ROUND_TOOL:
            return _round_tool_parts(raw, call_id)
        text = _arguments_text(raw, _arguments(raw))
        return [_sized(text, kind="call", title=f"Call · {name}", id=call_id)]
    title = kind if isinstance(kind, str) else "part"
    return [_sized(_pretty(part), kind="other", title=title)]


def _did(source: str, body: object) -> dict[str, object]:
    """What the model did: the response's parts in order, its usage, and any failure."""
    held = _mapping(body)
    parts: list[dict[str, object]] = []
    did: dict[str, object] = {"parts": parts}
    if "failure" in held:
        did["failure"] = _failure_text(held.get("failure"))
    if source == "planning":
        response = _mapping(held.get("response"))
        listed = response.get("parts")
        for part in _sequence(listed):
            parts.extend(_response_part(part))
        did["usage"] = _usage(response.get("usage"))
        if did["usage"] is None:
            did["usage_note"] = "This response records no token usage."
        did["read_as_round"] = held.get("read_as_round")
        did["finish_reason"] = _text(response.get("finish_reason"))
        did["model"] = _text(response.get("model_name"))
        if not isinstance(listed, list) and "failure" not in held:
            did["odd"] = "This entry holds no response parts to read."
        return did
    reply = held.get("reply")
    if isinstance(reply, str):
        parts.append(_sized(_readable(reply), kind="reply", title="Reply"))
    dropped = held.get("dropped")
    if isinstance(dropped, list) and dropped:
        parts.append(_sized(_pretty(dropped), kind="other", title="Dropped evidence"))
    if held.get("digest") == "failed":
        did["failure"] = "the digest failed" + (
            f": {held['reason']}" if isinstance(held.get("reason"), str) else ""
        )
    if not parts and "failure" not in did:
        did["odd"] = "This entry holds no reply to read."
    did["usage"] = None
    did["usage_note"] = NO_OBSERVER_USAGE if source == "observer" else NO_USAGE
    return did


def request_parts(body: object) -> dict[str, tuple[str, int]]:
    """A request's parts by name, for comparing it with another request.

    The instructions are one part, every top-level key of a message's JSON one, and
    every tool the request offered one.

    Returns:
        Each part's text as it is compared, a paragraph or a JSON line to a line, and
        its size as the view's other sections give it.
    """
    parts: dict[str, tuple[str, int]] = {}
    messages = _messages_of(body) or []
    told = [one if isinstance(one, str) else _pretty(one) for r, one in messages if r == "system"]
    if told:
        # One paragraph to a line, so the diff of a changed paragraph is that paragraph.
        joined = "\n\n".join(told)
        blocks = [one.strip("\n") for one in _BLANK_LINE.split(joined.replace("\r\n", "\n"))]
        parts["instructions"] = ("\n".join(one for one in blocks if one.strip()), len(joined))
    others = [(role, content) for role, content in messages if role != "system"]
    for index, (role, content) in enumerate(others, 1):
        prefix = "input" if len(others) == 1 else f"message {index} ({role})"
        document = _object_in(content) if isinstance(content, str) else None
        if document is None:
            text = content if isinstance(content, str) else _pretty(content)
            parts[prefix] = (text, len(text))
            continue
        for key, value in document.items():
            parts[f"{prefix} · {key}"] = (_pretty(value), _sent(value))
    for one in _sequence(_mapping(body).get("tools")):
        tool = _mapping(one)
        name = _text(tool.get("name"))
        if name:
            description = _text(tool.get("description")) or ""
            text = description + "\n\n" + _pretty(tool.get("parameters"))
            parts[f"tool · {name}"] = (text, _sent(one))
    return parts


def text_diff(before: str, after: str) -> dict[str, object]:
    """A changed part's line diff, unified, with two lines of context.

    The lines both sides share at their start and end are set aside first, and only
    what lies between them is matched, so a long part changed in one place costs that
    place alone. Where that middle is longer than :data:`DIFF_SPAN` lines either side,
    or either side is longer than :data:`DIFF_CHARS`, no diff is drawn: matching lines
    can cost the square of their number. The diff shown is cut at :data:`DIFF_LINES`.
    """
    too_large: dict[str, object] = {"lines": [], "cut": False, "too_large": True}
    if len(before) > DIFF_CHARS or len(after) > DIFF_CHARS:
        return too_large
    old, new = before.splitlines(), after.splitlines()
    shortest = min(len(old), len(new))
    head = 0
    while head < shortest and old[head] == new[head]:
        head += 1
    tail = 0
    while tail < shortest - head and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    if max(len(old), len(new)) - head - tail > DIFF_SPAN:
        return too_large
    start = max(0, head - DIFF_CONTEXT)
    kept = max(0, tail - DIFF_CONTEXT)
    diff = difflib.unified_diff(
        old[start : len(old) - kept], new[start : len(new) - kept], lineterm="", n=DIFF_CONTEXT
    )
    # The first two records are the file headers, there wherever anything differs.
    lines = [_moved(one, start) for one in itertools.islice(diff, 2, DIFF_LINES + 3)]
    return {"lines": lines[:DIFF_LINES], "cut": len(lines) > DIFF_LINES, "too_large": False}


_HUNK: Final = re.compile(r"@@ -(\d+)((?:,\d+)?) \+(\d+)((?:,\d+)?) @@")


def _moved(line: str, offset: int) -> str:
    """A hunk's header numbered from the part's first line, not the matched middle's."""
    if not offset or not line.startswith("@@"):
        return line
    found = _HUNK.fullmatch(line)
    if found is None:
        return line
    old, old_size, new, new_size = found.groups()
    return f"@@ -{int(old) + offset}{old_size} +{int(new) + offset}{new_size} @@"


def compare_requests(before: object, after: object) -> list[dict[str, object]]:
    """What changed from one request to the next, part by part.

    Args:
        before: The earlier request's body.
        after: The later request's body.

    Returns:
        Every part of either, in the later request's order and then the removed ones:
        added, removed, changed (with its diff) or unchanged, and its size.
    """
    old, new = request_parts(before), request_parts(after)
    shown: list[dict[str, object]] = []
    for name, (text, size) in new.items():
        if name not in old:
            shown.append({"part": name, "change": "added", "after": size})
            continue
        was, was_size = old[name]
        if was == text:
            shown.append({"part": name, "change": "unchanged", "after": size})
            continue
        shown.append(
            {
                "part": name,
                "change": "changed",
                "before": was_size,
                "after": size,
                "diff": text_diff(was, text),
            }
        )
    shown += [
        {"part": name, "change": "removed", "before": size}
        for name, (_text_of, size) in old.items()
        if name not in new
    ]
    return shown


def _about(source: str, body: object) -> dict[str, object]:
    """What names a call beside its round: a digest's question, result and part."""
    if source != "digesting":
        return {}
    held = _mapping(body)
    shown = {key: held[key] for key in ("question", "result") if isinstance(held.get(key), str)}
    part, parts = held.get("part"), held.get("parts")
    if isinstance(part, int) and isinstance(parts, int):
        shown["part"] = f"{part} of {parts}"
    return shown


def model_call(lines: Sequence[Line], number: int) -> dict[str, object] | None:
    """One model call, readable: told, given, offered, done, and changed since the last.

    Args:
        lines: The activation's complete lines.
        number: The line of the call's given entry or of its returned one.

    Returns:
        ``None`` where that line is no model source's given or returned entry; else the
        call's parts, each with its size, and what the record does not hold, said.
    """
    if not 0 <= number < len(lines):
        return None
    picked = lines[number]
    if not (
        isinstance(picked, Entry)
        and picked.source in MODEL_SOURCES
        and picked.kind in {"given", "returned"}
    ):
        return None
    built = _Timeline(lines)
    built.build()
    given, returned = _pair_of(built.pairs, lines, picked)
    anchor = given or picked
    view = _read_call(picked.source, given, returned)
    view["round"] = built.round_of(anchor.at) if picked.source == "planning" else None
    view["about"] = _about(picked.source, anchor.body)
    if given is not None and picked.source == "planning":
        view["changes"] = _changes(built, given)
    if returned is not None:
        view["tools"] = _tools(_mapping(returned.body).get("offered_tools"), "returned")
        if _mapping(returned.body).get("offered_tools_unprepared") is not None:
            _notes(view).append("The offered tools are as the round built them, not as prepared.")
    if view["tools"] is None and given is not None:
        view["tools"] = _tools(_mapping(given.body).get("tools"), "given")
    return view


def learning_call(lines: Sequence[Line], number: int) -> dict[str, object] | None:
    """One of the observer's model calls, readable as any other (ADR-0333 §5:2).

    Args:
        lines: The activation's observer file's complete lines.
        number: The line of the call's given entry or of its returned one.

    Returns:
        ``None`` where that line is no observer call's given or returned entry; else
        the call's parts as :func:`model_call` gives them, and which step, finding and
        attempt it was.
    """
    if not 0 <= number < len(lines):
        return None
    picked = lines[number]
    if not (
        isinstance(picked, Entry)
        and picked.source == "observer"
        and picked.kind in {"given", "returned"}
        and _text(_mapping(picked.body).get("stage")) in OBSERVER_CALLS
    ):
        return None
    learned = Learned("")
    for line in lines:
        learned.feed(line)
    given, returned = _pair_of(learned.pairs, lines, picked)
    anchor = _mapping((given or picked).body)
    view = _read_call("observer", given, returned)
    finding = anchor.get("finding")
    view["about"] = {
        "stage": _text(anchor.get("stage")),
        "finding": _text(_mapping(finding).get("id")) or _text(finding),
        "claim": _text(_mapping(finding).get("claim")),
        "episode": _text(anchor.get("episode")),
        "attempt": _text(anchor.get("attempt_started_at")),
    }
    return view


def _read_call(source: str, given: Entry | None, returned: Entry | None) -> dict[str, object]:
    """What any model call shows: told, given and done, and what the record lacks."""
    anchor = given or returned
    notes: list[str] = []
    view: dict[str, object] = {
        "source": source,
        "round": None,
        "given": None if given is None else given.line,
        "returned": None if returned is None else returned.line,
        "at": None if anchor is None else _ms(anchor.at),
        "took": None if given is None or returned is None else _ms(returned.at - given.at),
        "about": {},
        "prompt": None if given is None else prompt_of(given.body),
        "told": None,
        "input": None,
        "tools": None,
        "did": None,
        "changes": None,
        "notes": notes,
    }
    if given is None:
        notes.append("No given entry was recorded for this call: what it was told is not here.")
    else:
        messages = _messages_of(given.body)
        if messages is None:
            notes.append("The given entry holds no list of messages; the raw entry shows it.")
        else:
            view["told"] = _told(messages)
            view["input"] = _given(messages)
    if returned is None:
        notes.append("No returned entry was recorded for this call: what it did is not here.")
    else:
        view["did"] = _did(source, returned.body)
    return view


def prompt_of(body: object) -> dict[str, object] | None:
    """The prompt a given entry names (ADR-0334 §8:2): its name, version, origin and flags on.

    Args:
        body: A given entry's body.

    Returns:
        The prompt's name, version and origin, and the flags it was rendered with that
        were on; or ``None`` where the entry names no prompt.
    """
    named = _mapping(_mapping(body).get("prompt"))
    version = _text(named.get("version"))
    if version is None:
        return None
    flags = _mapping(named.get("flags"))
    return {
        "name": _text(named.get("name")),
        "version": version,
        "origin": _text(named.get("origin")),
        "flags_on": sorted(key for key, value in flags.items() if value is True),
    }


def _notes(view: Mapping[str, object]) -> list[str]:
    notes = view["notes"]
    assert isinstance(notes, list)  # noqa: S101 — built by _read_call, always a list
    return notes


def _pair_of(
    pairs: Mapping[int, int | None], lines: Sequence[Line], picked: Entry
) -> tuple[Entry | None, Entry | None]:
    """A call's given entry and its returned one, as the timeline or the lane paired them."""
    if picked.kind == "given":
        paired = pairs.get(picked.line)
        found = None if paired is None else lines[paired]
        return picked, found if isinstance(found, Entry) else None
    paired = next((one for one, back in pairs.items() if back == picked.line), None)
    found = None if paired is None else lines[paired]
    return (found if isinstance(found, Entry) else None), picked


def _changes(built: _Timeline, given: Entry) -> dict[str, object] | None:
    """What changed in a planning request since the request before it, if any."""
    earlier = [
        one
        for one in built.entries
        if one.source == "planning" and one.kind == "given" and one.line < given.line
    ]
    if not earlier:
        return None
    before = earlier[-1]
    return {
        "against": before.line,
        "against_round": built.round_of(before.at),
        "parts": compare_requests(before.body, given.body),
    }


# --- a replay's results, beside the call they replay ----------------------------------
# What ``prompt_replay.py`` sent again over a copy of the record and got back, one line of
# the activation's results file for each call and candidate (ADR-0335 §6:1). A result names
# the given entry it replays by its file and its line, from 0 as this viewer numbers lines
# (§6:2). Every key read here is a hint, as an entry's are (ADR-0316 §5:2).


def replays_of(
    lines: Sequence[Line], file: str, given: int, source: str
) -> list[dict[str, object]]:
    """Each result that replays the given entry at line ``given`` of ``file`` (§6:4).

    Args:
        lines: The activation's results file's complete lines.
        file: The name of the file the given entry is in: the activation's own, or its
            observer file.
        given: The given entry's line.
        source: Who wrote the given entry, which says how a reply reads.

    Returns:
        Each result, in the order written: its prompt's name, version and origin, the
        candidate's instruction, and what the model did, read as the original's is.
    """
    shown: list[dict[str, object]] = []
    for line in lines:
        if not isinstance(line, Entry) or line.source != "replay":
            continue
        body = _mapping(line.body)
        replays = _mapping(body.get("replays"))
        number = replays.get("line")
        if replays.get("file") == file and type(number) is int and number == given:
            shown.append(_replay_result(line, body, source))
    return shown


def _replay_result(line: Entry, body: Mapping[str, object], source: str) -> dict[str, object]:
    """One result as the call's view shows it, headed by its prompt (§6:4)."""
    candidate = _mapping(body.get("candidate"))
    recorded = _mapping(body.get("recorded_prompt"))
    instruction = _text(candidate.get("instruction"))
    flags = _mapping(body.get("flags"))
    sample, samples = body.get("sample"), body.get("samples")
    numbered = type(sample) is int and type(samples) is int
    return {
        "line": line.line,
        # The samples of one call under one candidate in one run share a set, which the
        # page shows together (ADR-0337 §5:4); a result naming no sample is a set alone.
        "set": json.dumps(
            [
                body.get("run"),
                body.get("prompt"),
                candidate.get("version"),
                candidate.get("origin"),
                candidate.get("file"),
                body.get("flags"),
            ],
            sort_keys=True,
            default=str,
        )
        if numbered
        else f"line:{line.line}",
        "sample": sample if numbered else None,
        "samples": samples if numbered else None,
        "at": _ms(line.at),
        "run": _text(body.get("run")),
        "prompt": _text(body.get("prompt")),
        "version": _text(candidate.get("version")),
        "origin": _text(candidate.get("origin")),
        "file": _text(candidate.get("file")),
        "recorded_version": _text(recorded.get("version")),
        "recorded_origin": _text(recorded.get("origin")),
        "flags": [f"{name}={value}" for name, value in flags.items()],
        "flags_from": _text(body.get("flags_from")),
        "model": _text(body.get("model")),
        "original_model": _text(body.get("original_model")),
        "instruction": None if instruction is None else _sized(instruction),
        "did": _did(source, body),
        "follow_up": _follow_up(body.get("follow_up")),
    }


def _follow_up(value: object) -> dict[str, object] | None:
    """The follow-up a run asked after this result's response, as text (ADR-0337 §6:5).

    Its answer as text, or its failure, with its version, origin, file and question;
    ``None`` where the result carries none.
    """
    held = _mapping(value)
    if not held:
        return None
    answer, question = held.get("answer"), _text(held.get("question"))
    return {
        "version": _text(held.get("version")),
        "origin": _text(held.get("origin")),
        "file": _text(held.get("file")),
        "question": None if question is None else _sized(question),
        "answer": _sized(answer) if isinstance(answer, str) else None,
        "failure": _failure_text(held.get("failure")) if "failure" in held else None,
    }


# --- the hub's follow-ups, beside the call they follow -------------------------------
# What the owner's hub asked a recorded call after it answered, one returned entry of the
# activation's follow-up file for each (ADR-0337 §8:9). An entry names the given entry it
# follows by its source, its instant and the step or part its body names (§8:10). Every
# key read here is a hint, as an entry's are (ADR-0316 §5:2).

#: What a follow-up entry may name of the given entry it follows, beside its source and
#: instant, each to be matched where it is named.
_FOLLOWS_NAMING: Final = ("stage", "result", "part", "parts")


def follow_ups_of(lines: Sequence[Line], given: Entry) -> list[dict[str, object]]:
    """Each follow-up entry that follows the given entry ``given`` (ADR-0337 §8:17).

    Args:
        lines: The activation's follow-up file's complete lines.
        given: The call's given entry, from the activation's own file or its observer file.

    Returns:
        Each follow-up, in the order written: the version and origin of the follow-up
        prompt, the model it went to, the version of the followed call's prompt, and its
        answer as text or its failure.
    """
    named = _mapping(given.body)
    shown: list[dict[str, object]] = []
    for line in lines:
        if not isinstance(line, Entry) or line.source != "follow_up" or line.kind != "returned":
            continue
        body = _mapping(line.body)
        follows = _mapping(body.get("follows"))
        if (
            follows.get("source") != given.source
            or instant(follows.get("recorded_at")) != given.at
            or any(follows.get(key) != named.get(key) for key in _FOLLOWS_NAMING if key in follows)
        ):
            continue
        shown.append(_hub_follow_up(line, body))
    return shown


def _hub_follow_up(line: Entry, body: Mapping[str, object]) -> dict[str, object]:
    """One follow-up as the call's view shows it, headed by the prompt it asked (§8:10)."""
    asked = _mapping(body.get("follow_up_prompt"))
    followed = _mapping(body.get("prompt"))
    answer = body.get("answer")
    return {
        "line": line.line,
        "at": _ms(line.at),
        "version": _text(asked.get("version")),
        "origin": _text(asked.get("origin")),
        "model": _text(body.get("model")),
        "followed_version": _text(followed.get("version")),
        "answer": _sized(answer) if isinstance(answer, str) else None,
        "failure": _failure_text(body.get("failure")) if "failure" in body else None,
    }


# --- walking one activation, a step at a time -------------------------------------------
# The activation in its own order, one step at a time, as a debugger steps through a
# finished run: what arrived, each phase's run with what it was given and what it decided,
# how it ended, and what the observer learned of it. A step is a summary of the few things
# that matter, and names the lines a click shows whole through the call view and the raw
# entries the timeline opens (ADR-0316 §3:3). Every key read here is a hint (§5:2): a body
# of another shape loses its summary, and its step is still walked, its entries a click
# away. Nothing here says why recall did not keep a find: the record does not hold it.

#: The phases whose given and returned entries a walk's step summarises.
WALK_SOURCES: Final = frozenset({"recall", "understanding", "planning", "authorizing", "digesting"})

#: How much of a long value a step shows: a result, a digest's evidence, a recalled item.
WALK_CHARS: Final = 600

#: How much of a recalled item's text a step shows: the hub cuts a fact shorter already.
RECALLED_CHARS: Final = 2_000

#: How much of the text a label names a step shows beside the label.
LABEL_CHARS: Final = 200

#: How deep a request's JSON is searched for the labels it shows.
LABEL_DEPTH: Final = 8

#: The keys understanding's reply carries (ADR-0353 §9:1); any other is named as other.
_REPLY_KEYS: Final = frozenset(
    {"understanding", "cites", "unclear", "belongs_to", "meant_for", "relayed"}
)

#: The keys of a reply written before ADR-0353, in the shape ADR-0276 §2 gave it; any
#: other is named as other. The record is never upgraded (ADR-0326 §8:1), so a reply
#: recorded then is shown in that shape (ADR-0353 §14:10).
_EARLIER_READING_KEYS: Final = frozenset(
    {
        "meaning",
        "meaning_ground",
        "meaning_labels",
        "references",
        "relationships",
        "unresolved",
        "story_labels",
        "answers",
        "continues",
    }
)

#: The earlier shape's keys that the reply's shape does not share: a reply holding one of
#: them and no ``understanding`` was written in the earlier shape.
_EARLIER_ONLY_KEYS: Final = _EARLIER_READING_KEYS - {"continues"}

#: The keys whose text stands for a labelled item, the first that is text.
_LABEL_TEXT_KEYS: Final = (
    "fact",
    "text",
    "summary",
    "meaning",
    "input",
    "excerpt",
    "asks",
    "question",
    "description",
    "shown",
)

#: Each stage's name in a step's title, where it is not the stage's own words.
_TITLES: Final = {
    "recall": "Recall",
    "understanding": "Understanding",
    "authorizing": "Authorizing",
    "acting": "Acting",
    "digesting": "Digesting",
}


@dataclass(slots=True)
class _Phase:
    """One run of a stage: its controller step, where one was recorded, and its entries."""

    stage: str
    start: float
    line: int
    step: Entry | None = None
    entries: list[Entry] = field(default_factory=list)


def walk(
    lines: Sequence[Line], learned: Sequence[Line] | None = None, *, own: bool = True
) -> dict[str, object]:
    """One activation's steps, in its own order, each in short (ADR-0316 §3:3).

    Args:
        lines: The activation's own file's complete lines.
        learned: Its observer file's complete lines, where it has one.
        own: Whether its own file is in the listing; where it is not, only what the
            observer learned is walked (ADR-0333 §5:6).

    Returns:
        Where the activation began, and its steps: the input, each phase's run in the
        order it began, the end, and each of the observer's attempts. Each step names
        the lines a click shows whole.
    """
    built = _Timeline(lines)
    built.build()
    tally = Tally("")
    for line in lines:
        tally.feed(line)
    steps: list[dict[str, object]] = []
    if own:
        phases, ended = _phases(built)
        arrival = arrival_of(lines)
        steps.append(
            {
                "phase": "input",
                "title": "Input",
                "start": tally.summary()["start"],
                "step": None,
                "arrival": arrival,
                "links": []
                if arrival is None
                else [
                    {
                        "label": "The request it was read from",
                        "lines": [arrival["line"]],
                        "call": arrival["line"],
                        "file": None,
                    }
                ],
            }
        )
        steps += [_phase_step(built, one) for one in phases]
        steps.append(_end_step(built, ended, tally))
    if learned is not None:
        steps += _learning_steps(learning_lane("", learned))
    return {"start": tally.summary()["start"], "own": own, "steps": steps}


def _phases(built: _Timeline) -> tuple[list[_Phase], Entry | None]:
    """Each run of a stage, in the order it began, and the end entry, where there is one.

    A controller step is a run of its stage, and holds its phase's entries written inside
    it. An entry no step of its phase holds, because its step is still running or its
    entry was never written (ADR-0314 §2:4), is a run of its own, its response with it,
    so a missing entry costs its own step and never another's.
    """
    phases: list[_Phase] = []
    spans: list[tuple[_Phase, float, float]] = []
    ended: Entry | None = None
    for entry in built.entries:
        if entry.source != "controller" or entry.kind != "step":
            continue
        body = _mapping(entry.body)
        stage = _text(body.get("stage")) or "step"
        if stage == "end":
            ended = entry
            continue
        started, finished = instant(body.get("started_at")), instant(body.get("ended_at"))
        phase = _Phase(stage, entry.at if started is None else started, entry.line, step=entry)
        phases.append(phase)
        if started is not None and finished is not None:
            spans.append((phase, started, finished))
    answered = {back: given for given, back in built.pairs.items() if back is not None}
    alone: dict[int, _Phase] = {}
    for entry in built.entries:
        if entry.source == "controller" and entry.kind == "step":
            continue
        host = next(
            (
                one
                for one, start, end in spans
                if one.stage == entry.source and start <= entry.at <= end
            ),
            None,
        )
        if host is None and entry.kind == "returned" and entry.line in answered:
            host = alone.get(answered[entry.line])
        if host is None:
            known = entry.source in WALK_SOURCES and entry.kind in KNOWN_KINDS
            host = _Phase(entry.source if known else lane_of(entry), entry.at, entry.line)
            phases.append(host)
            if entry.kind == "given":
                alone[entry.line] = host
        host.entries.append(entry)
    phases.sort(key=lambda one: (one.start, one.line))
    return phases, ended


def _step_facts(entry: Entry | None) -> dict[str, object] | None:
    """A controller step's rule, outcome, duration and failure, as a step's head shows them."""
    if entry is None:
        return None
    body = _mapping(entry.body)
    started, ended = instant(body.get("started_at")), instant(body.get("ended_at"))
    return {
        "line": entry.line,
        "due": _text(body.get("due")),
        "outcome": _text(body.get("outcome")),
        "took": None if started is None or ended is None else _ms(ended - started),
        "failure": _failure_text(body.get("failure")) if "failure" in body else None,
    }


def _links(built: _Timeline, phase: _Phase) -> list[dict[str, object]]:
    """What a step's clicks open: each model call readable, other entries whole, its step."""
    links: list[dict[str, object]] = []
    paired = set(built.pairs.values())
    calls = [
        one
        for one in phase.entries
        if one.source in MODEL_SOURCES
        and (one.kind == "given" or (one.kind == "returned" and one.line not in paired))
    ]
    for number, one in enumerate(calls, 1):
        back = built.pairs.get(one.line) if one.kind == "given" else None
        label = "The call, readable" if len(calls) == 1 else f"Call {number}, readable"
        lines = [one.line] if back is None else [one.line, back]
        links.append({"label": label, "lines": lines, "call": one.line, "file": None})
    shown = {line for link in links for line in _sequence(link["lines"])}
    others = [one.line for one in phase.entries if one.line not in shown]
    if others:
        label = "Its entry, whole" if len(others) == 1 else "Its entries, whole"
        links.append({"label": label, "lines": others, "call": None, "file": None})
    if phase.step is not None:
        links.append(
            {"label": "The step entry", "lines": [phase.step.line], "call": None, "file": None}
        )
    return links


def _phase_step(built: _Timeline, phase: _Phase) -> dict[str, object]:
    """One run of a stage as a walk's step: its head, its summary and its links."""
    number = built.round_of(phase.start) if phase.stage in {"planning", "authorizing"} else None
    title = _TITLES.get(phase.stage) or _words(phase.stage).capitalize()
    if number is not None:
        title = f"{'Planning' if phase.stage == 'planning' else 'Authorizing'} · round {number}"
    shown: dict[str, object] = {
        "phase": phase.stage,
        "title": title,
        "start": _ms(phase.start),
        "step": _step_facts(phase.step),
        "round": number,
        "links": _links(built, phase),
    }
    if phase.stage == "recall":
        shown |= _recall_step(built, phase)
        run = shown.get("run")
        if isinstance(run, str):
            shown["title"] = f"Recall · {_words(run)} run"
    elif phase.stage == "understanding":
        shown |= _understanding_step(phase)
    elif phase.stage == "planning":
        shown |= _planning_step(phase)
    elif phase.stage == "authorizing":
        shown |= _authorizing_step(phase)
    elif phase.stage == "digesting":
        shown |= _digesting_step(built, phase)
    return shown


def _last(phase: _Phase, kind: str) -> Entry | None:
    return next((one for one in reversed(phase.entries) if one.kind == kind), None)


def _first(phase: _Phase, kind: str) -> Entry | None:
    return next((one for one in phase.entries if one.kind == kind), None)


def _strings(value: object) -> list[str]:
    return [one for one in _sequence(value) if isinstance(one, str)]


def _number(value: object) -> float | None:
    """A number the page holds as one, or ``None``.

    An integer too large for a float, as a 401-digit one is, is a hint not recognised
    (ADR-0316 §5:2), and never a failure.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _cut(text: str, limit: int = WALK_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _item_text(item: Mapping[str, object], limit: int = WALK_CHARS) -> str:
    """What a labelled item of a request says: its text, or else its JSON, cut."""
    for key in _LABEL_TEXT_KEYS:
        said = _text(item.get(key))
        if said is not None:
            return _cut(said, limit)
    return _cut(_pretty({key: value for key, value in item.items() if key != "label"}), limit)


def _recall_step(built: _Timeline, phase: _Phase) -> dict[str, object]:
    """A recall run: its cues, how many it found, and what it kept with score and band.

    The text of what it kept is shown where a request after it holds it: understanding's
    request shows the first run's kept items in recall's order, each under a label and none
    by its id, leaving out what the request shows elsewhere and what was no longer held. So
    the two are joined, by order, only where that request shows exactly as many as were
    kept; else its items are listed apart, and nothing is said of which id each is.
    """
    given, returned = _first(phase, "given"), _last(phase, "returned")
    asked = _mapping(None if given is None else given.body)
    body = _mapping(None if returned is None else returned.body)
    finds = [_mapping(one) for one in _sequence(body.get("finds"))]
    bands: dict[str, list[str]] = {}
    for one in finds:
        found, band = _text(one.get("id")), _text(one.get("band"))
        if found is not None and band is not None and band not in bands.setdefault(found, []):
            bands[found].append(band)
    kept: list[dict[str, object]] = [
        {
            "id": _text(one.get("id")),
            "score": _number(one.get("score")),
            "bands": bands.get(_text(one.get("id")) or "", []),
            "found_by": _strings(one.get("found_by")),
            "label": None,
            "text": None,
        }
        for one in map(_mapping, _sequence(body.get("kept")))
    ]
    run = _text(asked.get("run"))
    listed = isinstance(body.get("finds"), list)
    return {
        "run": run,
        "cues": [
            {"text": _text(cue.get("text")), "kinds": _strings(cue.get("kinds"))}
            for cue in map(_mapping, _sequence(asked.get("cues")))
        ],
        "returned": returned is not None,
        "outcome": _text(body.get("outcome")),
        "found": len(finds) if listed else None,
        "admitted": sum(1 for one in finds if one.get("admitted") is True) if listed else None,
        "kept": kept,
        "failure": _failure_text(body.get("failure")) if "failure" in body else None,
        "shown": _recalled_shown(built, phase, run, kept),
    }


def _recalled_shown(
    built: _Timeline, phase: _Phase, run: str | None, kept: list[dict[str, object]]
) -> dict[str, object] | None:
    """The recalled section of the first request after a run, joined to it where it can be."""
    source = {"first": "understanding", "second": "planning"}.get(run or "")
    if source is None:
        return None
    after = max((one.line for one in phase.entries), default=phase.line)
    request = next(
        (
            one
            for one in built.entries
            if one.source == source and one.kind == "given" and one.line > after
        ),
        None,
    )
    document = None if request is None else _user_document(request.body)
    if request is None or document is None or "recalled" not in document:
        return None
    section = document.get("recalled")
    shown: dict[str, object] = {"from": source, "line": request.line, "said": None}
    if isinstance(section, str):
        return {**shown, "said": section, "items": [], "joined": False}
    items = [
        {"label": _text(one.get("label")), "text": _item_text(one, RECALLED_CHARS)}
        for one in map(_mapping, _sequence(section))
    ]
    joined = (
        source == "understanding"
        and bool(kept)
        and len(items) == len(kept)
        and all(item["label"] is not None for item in items)
    )
    if joined:
        for held, item in zip(kept, items, strict=True):
            held["label"], held["text"] = item["label"], item["text"]
    return {**shown, "items": [] if joined else items, "joined": joined}


def reading_of(reply: str) -> dict[str, object] | None:
    """Understanding's reply read field by field, in the shape it was written in.

    One enclosing Markdown code fence is set aside first, as the stage sets it aside. Each
    field is a hint (ADR-0316 §5:2): one of another shape is left out. A reply holding
    ``understanding``, or none of the earlier shape's own keys, is read in the reply's
    shape (ADR-0353 §9:1); any other in the earlier shape (ADR-0276 §2), since the record
    keeps what was written and is never upgraded (ADR-0353 §14:10). ``shape`` says which.

    Args:
        reply: The reply's text, as the returned entry keeps it.

    Returns:
        In the reply's shape: its understanding, what it cites, each unclear point with its
        readings, what it belongs to, what it is meant for and its relay mark. In the
        earlier shape: its meaning and ground, references, relationships, unresolved
        matters, answers, story links and the work it continues. Either with the keys it
        holds beside them; or ``None`` where the reply is no JSON object.
    """
    body = reply.strip()
    if body.startswith("```") and body.endswith("```") and len(body) >= 6:  # noqa: PLR2004 — two fences
        body = body[3:-3]
        newline = body.find("\n")
        if newline != -1 and body[:newline].strip() in {"", "json", "JSON"}:
            body = body[newline + 1 :]
    value = _object_in(body)
    if value is None:
        return None
    if "understanding" in value or not _EARLIER_ONLY_KEYS & value.keys():
        relayed = value.get("relayed")
        return {
            "shape": "reply",
            "understanding": _text(value.get("understanding")),
            "cites": _strings(value.get("cites")),
            "unclear": [
                {"gap": _text(one.get("gap")), "readings": _strings(one.get("readings"))}
                for one in map(_mapping, _sequence(value.get("unclear")))
            ],
            "belongs_to": _strings(value.get("belongs_to")),
            "meant_for": _strings(value.get("meant_for")),
            "relayed": relayed if isinstance(relayed, bool) else None,
            "other": sorted(key for key in value if key not in _REPLY_KEYS),
        }
    return {
        "shape": "earlier",
        "meaning": _text(value.get("meaning")),
        "ground": _text(value.get("meaning_ground")),
        "meaning_labels": _strings(value.get("meaning_labels")),
        "references": [
            {"phrase": _text(one.get("phrase")), "labels": _strings(one.get("labels"))}
            for one in map(_mapping, _sequence(value.get("references")))
        ],
        "relationships": [
            {
                "statement": _text(one.get("statement")),
                "ground": _text(one.get("ground")),
                "labels": _strings(one.get("labels")),
            }
            for one in map(_mapping, _sequence(value.get("relationships")))
        ],
        "unresolved": [
            {"matter": _text(one.get("matter")), "why": _text(one.get("why_it_matters"))}
            for one in map(_mapping, _sequence(value.get("unresolved")))
        ],
        "story_labels": _strings(value.get("story_labels")),
        "answers": [
            {
                "question": _text(one.get("question")),
                "parts": [
                    part
                    for part in _sequence(one.get("parts"))
                    if type(part) is int and abs(part) <= _SAFE_INTEGER
                ],
            }
            for one in map(_mapping, _sequence(value.get("answers")))
        ],
        "continues": _strings(value.get("continues")),
        "other": sorted(key for key in value if key not in _EARLIER_READING_KEYS),
    }


def _labels_used(reading: Mapping[str, object]) -> set[str]:
    if reading.get("shape") == "reply":
        return {
            *_strings(reading.get("cites")),
            *_strings(reading.get("belongs_to")),
            *_strings(reading.get("meant_for")),
        }
    used = set(_strings(reading.get("meaning_labels")))
    used |= set(_strings(reading.get("story_labels"))) | set(_strings(reading.get("continues")))
    for key in ("references", "relationships"):
        for one in map(_mapping, _sequence(reading.get(key))):
            used |= set(_strings(one.get("labels")))
    for one in map(_mapping, _sequence(reading.get("answers"))):
        question = _text(one.get("question"))
        if question is not None:
            used.add(question)
    return used


def labels_in(body: object, wanted: set[str]) -> dict[str, str]:
    """The text each wanted label names in a request: the item shown under it, in short.

    Args:
        body: A given entry's body.
        wanted: The labels to look for.

    Returns:
        Each label found, with its item's text cut to :data:`LABEL_CHARS`; a label the
        request does not show under that name is not there.
    """
    found: dict[str, str] = {}
    document = _user_document(body)
    pending: list[tuple[object, int]] = [] if document is None else [(document, 0)]
    while pending and len(found) < len(wanted):
        value, depth = pending.pop()
        if depth > LABEL_DEPTH:
            continue
        if isinstance(value, dict):
            label = _text(value.get("label"))
            if label in wanted and label not in found:
                found[label] = _item_text(value, LABEL_CHARS)
            pending.extend((one, depth + 1) for one in reversed(value.values()))
        elif isinstance(value, list):
            pending.extend((one, depth + 1) for one in reversed(value))
    return found


def _understanding_step(phase: _Phase) -> dict[str, object]:
    """Understanding's run: its reading of the input, field by field, with its labels' text."""
    given, returned = _last(phase, "given"), _last(phase, "returned")
    body = _mapping(None if returned is None else returned.body)
    reply = _text(body.get("reply"))
    reading = None if reply is None else reading_of(reply)
    labels = (
        {} if reading is None or given is None else labels_in(given.body, _labels_used(reading))
    )
    return {
        "calls": sum(1 for one in phase.entries if one.kind == "given"),
        "returned": returned is not None,
        "reading": reading,
        "reply": reply if reading is None else None,
        "labels": labels,
        "failure": _failure_text(body.get("failure")) if "failure" in body else None,
    }


def _result_in_short(value: object) -> dict[str, object] | None:
    held = _mapping(value)
    if not held:
        return None
    shown = held.get("value")
    text = shown if isinstance(shown, str) else _pretty(shown)
    return {"label": _text(held.get("label")), "text": _cut(text)}


def _planning_step(phase: _Phase) -> dict[str, object]:
    """A planning round: what came back from the round before, and what this one proposed."""
    given, returned = _first(phase, "given"), _last(phase, "returned")
    document = None if given is None else _user_document(given.body)
    rounds = _sequence(_mapping(document).get("rounds"))
    before = _mapping(rounds[-1]) if rounds else None
    body = _mapping(None if returned is None else returned.body)
    shown: dict[str, object] = {
        "request": document is not None,
        "first": document is not None and isinstance(document.get("rounds"), list) and not rounds,
        "before": None
        if before is None
        else {
            "round": _position(before.get("round")),
            "text": _text(before.get("text")),
            "text_was": _text(before.get("text_was")),
            "calls": [
                {
                    "capability": _text(one.get("capability")),
                    "outcome": _text(one.get("outcome")),
                    "because": _text(one.get("because")),
                    "result": _result_in_short(one.get("result")),
                }
                for one in map(_mapping, _sequence(before.get("calls")))
            ],
        },
        "evidence": [
            {
                "of": _text(one.get("digest_of")),
                "looking_for": _text(one.get("looking_for")),
                "digest": _cut(_pretty(one.get("digest"))),
            }
            for one in map(_mapping, _sequence(_mapping(document).get("evidence")))
        ],
        "returned": returned is not None,
        "failure": _failure_text(body.get("failure")) if "failure" in body else None,
        "read_as_round": body.get("read_as_round")
        if isinstance(body.get("read_as_round"), bool)
        else None,
    }
    return shown | _proposed(body)


def _proposed(body: Mapping[str, object]) -> dict[str, object]:
    """What a round's response proposed: its calls, its message, its notes and asks."""
    texts: list[str] = []
    calls: list[dict[str, object]] = []
    notes: str | None = None
    asks: list[str] | None = None
    another = False
    thinking = False
    for part in map(_mapping, _sequence(_mapping(body.get("response")).get("parts"))):
        kind = part.get("part_kind")
        if kind == "text" and isinstance(part.get("content"), str):
            texts.append(str(part["content"]))
        elif kind == "thinking":
            thinking = True
        elif kind == "tool-call":
            name = _text(part.get("tool_name")) or "?"
            raw = part.get("args")
            parsed = _arguments(raw)
            if name == ROUND_TOOL:
                held = _mapping(parsed)
                said = held.get("notes")
                listed = _strings(said)
                notes = said if isinstance(said, str) else "\n".join(listed) if listed else notes
                asked = held.get("asks")
                asks = _strings(asked) if isinstance(asked, list) else asks
                another = another or held.get("another_round") is True
            else:
                calls.append(
                    {
                        "name": name,
                        "id": _text(part.get("tool_call_id")),
                        "arguments": _arguments_text(raw, parsed),
                    }
                )
    return {
        "calls": calls,
        "message": "".join(texts),
        "notes": notes,
        "asks": asks,
        "another_round": another,
        "thinking": thinking,
    }


def _authorizing_step(phase: _Phase) -> dict[str, object]:
    """Authorizing's verdicts: each call's, and whether the round's message was allowed."""
    returned = _last(phase, "returned")
    body = _mapping(None if returned is None else returned.body)
    message = _mapping(body.get("message"))
    allowed = message.get("allowed")
    return {
        "returned": returned is not None,
        "verdicts": [
            {
                "name": _text(one.get("name")),
                "call_id": _text(one.get("call_id")),
                "verdict": _text(one.get("verdict")),
                "reason": _text(one.get("reason")),
            }
            for one in map(_mapping, _sequence(body.get("calls")))
        ],
        "message": None
        if not message
        else {
            "allowed": allowed if isinstance(allowed, bool) else None,
            "reason": _text(message.get("reason")),
            "place": _text(message.get("place")),
        },
        "outside": body.get("read_outside_content") is True,
        "failure": _failure_text(body.get("failure")) if "failure" in body else None,
    }


def _digesting_step(built: _Timeline, phase: _Phase) -> dict[str, object]:
    """Digesting's parts: each question, and its evidence or why it failed."""
    by_line = {one.line: one for one in built.entries}
    parts: list[dict[str, object]] = []
    used: set[int] = set()
    for one in phase.entries:
        if one.kind != "given":
            continue
        back = built.pairs.get(one.line)
        if back is not None:
            used.add(back)
        parts.append(
            _digest_part(_mapping(one.body), by_line.get(back) if back is not None else None)
        )
    parts += [
        _digest_part(_mapping(one.body), one)
        for one in phase.entries
        if one.kind == "returned" and one.line not in used
    ]
    return {"parts": parts}


def _digest_part(asked: Mapping[str, object], returned: Entry | None) -> dict[str, object]:
    body = _mapping(None if returned is None else returned.body)
    part, parts = asked.get("part"), asked.get("parts")
    numbered = type(part) is int and type(parts) is int
    reply = _text(body.get("reply"))
    why = _failure_text(body.get("failure")) if "failure" in body else _text(body.get("reason"))
    return {
        "question": _text(asked.get("question")),
        "result": _text(asked.get("result")),
        "part": f"{part} of {parts}" if numbered else None,
        "returned": returned is not None,
        "failed": returned is not None and failed_digest(body),
        "why": why,
        "evidence": None if reply is None else _cut(_readable(reply)),
    }


def _end_step(built: _Timeline, ended: Entry | None, tally: Tally) -> dict[str, object]:
    """How the activation ended: its end entry's rule, or that none was recorded."""
    truncation = next((one for one in built.lines if isinstance(one, Truncation)), None)
    body = _mapping(None if ended is None else ended.body)
    return {
        "phase": "end",
        "title": "The end",
        "start": None if ended is None else _ms(ended.at),
        "step": _step_facts(ended),
        "rule": _text(body.get("due")),
        "recorded": ended is not None,
        "truncated": None if truncation is None else {"at": _ms(truncation.at)},
        "unreadable": tally.unreadable,
        "links": []
        if ended is None
        else [{"label": "The end entry", "lines": [ended.line], "call": None, "file": None}],
    }


def _learning_steps(lane: Mapping[str, object]) -> list[dict[str, object]]:
    """Each of the observer's attempts at the activation, as a walk's last steps."""
    attempts = [_mapping(one) for one in _sequence(lane.get("attempts"))]
    findings = [_mapping(one) for one in _sequence(lane.get("findings"))]
    steps: list[dict[str, object]] = []
    for attempt in attempts:
        key = attempt.get("key")
        number = attempt.get("number")
        items = [_mapping(one) for one in _sequence(attempt.get("items"))]
        steps.append(
            {
                "phase": "learning",
                "title": "Learning" + (f" · attempt {number}" if len(attempts) > 1 else ""),
                "start": attempt.get("start"),
                "step": None,
                "attempt": number,
                "ended": attempt.get("ended"),
                "findings": [_in_short(one) for one in findings if one.get("attempt") == key],
                "links": [
                    {
                        "label": f"The {one.get('label')} call, readable"
                        if one.get("kind") == "call"
                        else f"The {one.get('label')} entry",
                        "lines": one.get("lines"),
                        "call": one.get("call"),
                        "file": "observer",
                    }
                    for one in items
                    if one.get("stage") == "scout" or one.get("kind") == "end"
                ],
            }
        )
    return steps


# --- the server ------------------------------------------------------------------------


def allowed_host(header: str | None, port: int) -> bool:
    """Whether a ``Host`` header names the viewer at its own port (ADR-0316 §6:2).

    Args:
        header: The request's ``Host``, or ``None`` where it sent none.
        port: The port the viewer is bound to.

    Returns:
        True for ``127.0.0.1:<port>`` and ``localhost:<port>`` alone.
    """
    if header is None:
        return False
    return header.strip().lower() in {f"127.0.0.1:{port}", f"localhost:{port}"}


class ViewerServer(ThreadingHTTPServer):
    """The viewer's server: loopback alone, one record (ADR-0316 §6)."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, record: Record, port: int, *, report: Callable[[str], None]) -> None:
        """Bind ``127.0.0.1`` at ``port``; nothing else can be asked for.

        Args:
            record: The record it serves.
            port: The port, or 0 for any free one.
            report: Where its failures are printed, by class alone.
        """
        self.record = record
        self.report = report
        super().__init__((HOST, port), ViewerHandler)
        if self.server_address[0] != HOST:  # pragma: no cover — a bind is to HOST alone
            msg = "the viewer binds 127.0.0.1 alone"
            raise ValueError(msg)

    @property
    def port(self) -> int:
        """The port it is bound to."""
        return int(self.server_address[1])

    @override
    def handle_error(self, request: object, client_address: object) -> None:
        """Print a request's failure by its class, never its content (ADR-0316 §6:8)."""
        failure = sys.exc_info()[1]
        self.report(f"a request failed: {type(failure).__name__}")


class ViewerHandler(BaseHTTPRequestHandler):
    """Answers ``GET`` from loopback names alone; refuses everything else."""

    server: ViewerServer
    server_version = "activation-viewer"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def __getattr__(self, name: str) -> Callable[[], None]:
        """Refuse every method but ``GET`` (ADR-0316 §6:3), however it is spelled."""
        if name.startswith("do_"):
            return self._refuse_method
        raise AttributeError(name)

    @override
    def log_message(self, format: str, *args: object) -> None:
        """Print nothing per request: a request names an activation (ADR-0316 §6:8)."""

    @override
    def end_headers(self) -> None:
        """Add the headers every response carries, refusals included."""
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        super().end_headers()

    def _refuse_method(self) -> None:
        self._send(HTTPStatus.METHOD_NOT_ALLOWED, b"GET only\n", "text/plain", allow=True)

    def _send(
        self, status: HTTPStatus, body: bytes, content_type: str, *, allow: bool = False
    ) -> None:
        if status is not HTTPStatus.OK:
            # A refused request may carry a body the viewer never reads.
            self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if allow:
            self.send_header("Allow", "GET")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        # ASCII with escapes: a lone surrogate an entry holds is sent as its escape,
        # which JSON admits, rather than failing to encode the whole response.
        body = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        self._send(status, body, "application/json")

    def do_GET(self) -> None:  # the base class's name
        """Serve the page, its assets, or the record's data."""
        if not allowed_host(self.headers.get("Host"), self.server.port):
            self._send(HTTPStatus.FORBIDDEN, b"loopback names only\n", "text/plain")
            return
        target = urlsplit(self.path)
        query = parse_qs(target.query, keep_blank_values=True)
        route = _ROUTES.get(target.path)
        if route is None:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        route(self, {key: values[0] for key, values in query.items() if values})

    def _page(self, _query: Mapping[str, str]) -> None:
        self._send(HTTPStatus.OK, PAGE.encode("utf-8"), "text/html")

    def _style(self, _query: Mapping[str, str]) -> None:
        self._send(HTTPStatus.OK, STYLE.encode("utf-8"), "text/css")

    def _script(self, _query: Mapping[str, str]) -> None:
        self._send(HTTPStatus.OK, SCRIPT.encode("utf-8"), "text/javascript")

    def _no_icon(self, _query: Mapping[str, str]) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _activations(self, query: Mapping[str, str]) -> None:
        listed = self.server.record.activations()
        if query.get("v") == listed["version"]:
            self._json({"version": listed["version"], "unchanged": True, "now": _now()})
            return
        self._json({**listed, "now": _now()})

    def _read(
        self, query: Mapping[str, str]
    ) -> tuple[tuple[list[Line], str] | None, tuple[list[Line], str] | None, str] | None:
        """An activation's own and observer files' lines, and their version.

        ``None`` where it has neither file, or its version is the one the page holds: each
        is answered here.
        """
        activation_id = query.get("id", "")
        read = self.server.record.lines(activation_id)
        learned = self.server.record.learned_lines(activation_id)
        if read is None and learned is None:
            self._json({"error": "no such activation"}, HTTPStatus.NOT_FOUND)
            return None
        version = "|".join("-" if one is None else one[1] for one in (read, learned))
        if query.get("v") == version:
            self._json({"version": version, "unchanged": True, "now": _now()})
            return None
        return read, learned, version

    def _activation(self, query: Mapping[str, str]) -> None:
        found = self._read(query)
        if found is None:
            return
        read, learned, version = found
        activation_id = query.get("id", "")
        shown = timeline(activation_id, [] if read is None else read[0])
        # ADR-0333 §5:6: an activation whose own file is absent is shown with its
        # learning lane alone, saying so.
        shown["own"] = read is not None
        shown["learning"] = None if learned is None else learning_lane(activation_id, learned[0])
        self._json({**shown, "version": version, "now": _now()})

    def _walk(self, query: Mapping[str, str]) -> None:
        found = self._read(query)
        if found is None:
            return
        read, learned, version = found
        shown = walk(
            [] if read is None else read[0],
            None if learned is None else learned[0],
            own=read is not None,
        )
        self._json({**shown, "version": version, "now": _now()})

    def _learning(self, query: Mapping[str, str]) -> None:
        listed = self.server.record.learning()
        if query.get("v") == listed["version"]:
            self._json({"version": listed["version"], "unchanged": True, "now": _now()})
            return
        self._json({**listed, "now": _now()})

    def _lines_of(self, query: Mapping[str, str]) -> tuple[list[Line], str] | None:
        """The asked file's lines: the observer file's where ``file=observer``."""
        record, activation_id = self.server.record, query.get("id", "")
        if query.get("file") == "observer":
            return record.learned_lines(activation_id)
        return record.lines(activation_id)

    def _call(self, query: Mapping[str, str]) -> None:
        read = self._lines_of(query)
        number = query.get("line", "")
        read_call = learning_call if query.get("file") == "observer" else model_call
        shown = read_call(read[0], int(number)) if read is not None and number.isdigit() else None
        if shown is None:
            self._json({"error": "no such model call"}, HTTPStatus.NOT_FOUND)
            return
        self._json(
            {
                **shown,
                "replays": self._replays(query, shown),
                "follow_ups": self._follow_ups(query, [] if read is None else read[0], shown),
            }
        )

    def _follow_ups(
        self, query: Mapping[str, str], lines: Sequence[Line], shown: Mapping[str, object]
    ) -> list[object]:
        """The follow-ups of the call's given entry, from its activation's follow-up file."""
        given = shown.get("given")
        if type(given) is not int or not 0 <= given < len(lines):
            return []
        entry = lines[given]
        if not isinstance(entry, Entry):
            return []
        read = self.server.record.follow_up_lines(query.get("id", ""))
        if read is None:
            return []
        return list(follow_ups_of(read[0], entry))

    def _replays(self, query: Mapping[str, str], shown: Mapping[str, object]) -> list[object]:
        """The results that replay the call's given entry, from its activation's results file."""
        given, source = shown.get("given"), shown.get("source")
        if type(given) is not int or not isinstance(source, str):
            return []
        activation_id = query.get("id", "")
        read = self.server.record.replay_lines(activation_id)
        if read is None:
            return []
        suffix = OBSERVER_SUFFIX if query.get("file") == "observer" else SUFFIX
        return list(replays_of(read[0], activation_id + suffix, given, source))

    def _entry(self, query: Mapping[str, str]) -> None:
        read = self._lines_of(query)
        number = query.get("line", "")
        shown = entry_of(read[0], int(number)) if read is not None and number.isdigit() else None
        if shown is None:
            self._json({"error": "no such entry"}, HTTPStatus.NOT_FOUND)
            return
        self._json(shown)


def _now() -> float | None:
    return _ms(datetime.now(UTC).timestamp())


_ROUTES: Final[dict[str, Callable[[ViewerHandler, Mapping[str, str]], None]]] = {
    "/": ViewerHandler._page,
    "/app.css": ViewerHandler._style,
    "/app.js": ViewerHandler._script,
    "/api/activations": ViewerHandler._activations,
    "/api/activation": ViewerHandler._activation,
    "/api/walk": ViewerHandler._walk,
    "/api/learning": ViewerHandler._learning,
    "/api/entry": ViewerHandler._entry,
    "/api/call": ViewerHandler._call,
    "/favicon.ico": ViewerHandler._no_icon,
}


# --- the page --------------------------------------------------------------------------
# Plain HTML, CSS and JavaScript, served from this file and loading nothing else. Every
# string taken from an entry reaches the page through ``textContent``, never as markup.

PAGE: Final = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Activation viewer</title>
<link rel="stylesheet" href="/app.css">
<script src="/app.js" defer></script>
</head>
<body>
<header class="top">
  <div class="brand">Activations</div>
  <nav class="views" aria-label="Views">
    <button class="view" id="view-activations" type="button"
      aria-pressed="true">Activations</button>
    <button class="view" id="view-learning" type="button" aria-pressed="false">Learning</button>
  </nav>
  <div class="status" id="status">connecting…</div>
</header>
<main class="layout">
  <section class="list-pane" aria-label="Activations">
    <ul class="list" id="list"></ul>
    <p class="empty" id="list-empty" hidden>No activations in the record yet.</p>
  </section>
  <section class="detail-pane" id="detail" aria-label="Activation">
    <p class="empty" id="detail-empty">Choose an activation.</p>
    <div id="detail-body" hidden>
      <button class="back" id="back" type="button">← Activations</button>
      <h1 class="input" id="d-input"></h1>
      <div class="meta" id="d-meta"></div>
      <div class="badges" id="d-badges"></div>
      <p class="note own-absent" id="d-own-absent" hidden></p>
      <nav class="modes" aria-label="How to read it">
        <button class="view" id="mode-overview" type="button" aria-pressed="true">Overview</button>
        <button class="view" id="mode-walk" type="button" aria-pressed="false"
          title="Step through it phase by phase (\u2190 and \u2192 move)">Walk through</button>
      </nav>
      <section class="card walk" id="walk-card" aria-label="Walk through" hidden>
        <div class="walk-bar">
          <button class="walk-nav" id="walk-prev" type="button">\u2190 Previous</button>
          <div class="walk-count" id="walk-count" aria-live="polite"></div>
          <button class="walk-nav" id="walk-next" type="button">Next \u2192</button>
        </div>
        <ol class="walk-steps" id="walk-steps" aria-label="Steps"></ol>
        <div class="walk-step" id="walk-step"></div>
      </section>
      <div id="overview">
      <div class="card" id="arrival-card" hidden>
        <div class="card-title">Input</div>
        <div id="arrival"></div>
      </div>
      <div class="card" id="timeline-card">
        <div class="card-title">Timeline</div>
        <div class="timeline" id="timeline"></div>
        <div class="legend" id="legend"></div>
      </div>
      <div class="card" id="learning-card" hidden>
        <div class="card-title">Learning</div>
        <div id="learning-lane"></div>
      </div>
      <div class="card" id="rounds-card">
        <div class="card-title">Rounds</div>
        <div id="rounds"></div>
      </div>
      <details class="card" id="entries-card">
        <summary class="card-title">Every entry</summary>
        <div id="entries"></div>
      </details>
      </div>
    </div>
  </section>
</main>
<main class="learning" id="learning" hidden aria-label="Learning">
  <div class="ov-head-block">
    <h1 class="ov-title">What the observer learned</h1>
    <p class="note">Every activation the observer wrote about, its latest work first: each finding
      the scout proposed, what framing kept of it or why not, and the prompt and reply behind
      each call.</p>
    <div class="ov-stats" id="ov-stats"></div>
    <div class="ov-tools">
      <div class="ov-filters" id="ov-filters"></div>
      <input class="ov-search" id="ov-search" type="search"
        placeholder="Filter by words in a claim, a wording or a note" aria-label="Filter findings">
    </div>
  </div>
  <div id="ov-list"></div>
  <p class="empty" id="ov-empty" hidden>No observer files in the record yet.</p>
</main>
<aside class="drawer" id="drawer" hidden>
  <div class="drawer-head">
    <div class="drawer-title" id="drawer-title"></div>
    <div class="drawer-tabs" id="drawer-tabs" hidden>
      <button class="tab" id="tab-read" type="button" aria-pressed="true">Readable</button>
      <button class="tab" id="tab-raw" type="button" aria-pressed="false">Raw entries</button>
    </div>
    <button class="close" id="drawer-close" type="button" aria-label="Close">&times;</button>
  </div>
  <div class="drawer-body" id="drawer-read" hidden></div>
  <div class="drawer-body" id="drawer-body"></div>
</aside>
</body>
</html>
"""

STYLE: Final = """
:root {
  color-scheme: light dark;
  --bg: #f6f7f9; --panel: #ffffff; --ink: #1d2330; --muted: #6a7282; --line: #e3e6ec;
  --hover: #eef1f6; --select: #e4ebfb; --accent: #3b6ee8;
  --controller: #8a93a6; --recall: #1f9e8f; --understanding: #3b82f6; --planning: #7c5cdb;
  --authorizing: #d4890f; --acting: #2f9d55; --digesting: #d14d7a; --unknown: #6b7280;
  --failed: #d23c3c; --needs: #d4890f; --outside: #7c5cdb; --refused: #c2410c;
  --scout: #0f8b8d; --commit: #6d5bd0; --kept: #2f9d55; --not-kept: #8a93a6;
  --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #12151b; --panel: #1a1e26; --ink: #e5e8ee; --muted: #9098a8; --line: #2a303b;
    --hover: #222834; --select: #263354; --accent: #7aa2ff;
    --controller: #7d869a; --recall: #34c3b1; --understanding: #6aa5ff; --planning: #a58bff;
    --authorizing: #f0a93a; --acting: #4cc27a; --digesting: #f07aa2; --unknown: #8b93a3;
    --failed: #ff6b6b; --needs: #f0a93a; --outside: #a58bff; --refused: #ff8a4c;
    --scout: #3cc4c6; --commit: #a493ff; --kept: #4cc27a; --not-kept: #8b93a3;
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; }
body {
  background: var(--bg); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.top {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 16px; border-bottom: 1px solid var(--line); background: var(--panel);
  position: sticky; top: 0; z-index: 5;
}
.brand { font-weight: 650; letter-spacing: .2px; }
.status { color: var(--muted); font-size: 12px; }
.status.live::before {
  content: ""; display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: var(--acting); margin-right: 6px; vertical-align: 1px;
}
.status.lost { color: var(--failed); }
.layout {
  display: grid;
  grid-template-columns: minmax(280px, 380px) 1fr;
  height: calc(100% - 45px);
}
.list-pane { border-right: 1px solid var(--line); overflow-y: auto; background: var(--panel); }
.detail-pane { overflow-y: auto; padding: 18px 22px 40px; min-width: 0; }
.list { list-style: none; margin: 0; padding: 0; }
.list li {
  padding: 10px 14px; border-bottom: 1px solid var(--line); cursor: pointer;
  display: grid; gap: 3px;
}
.list li:hover { background: var(--hover); }
.list li.selected { background: var(--select); }
.row1 {
  display: flex;
  gap: 10px;
  color: var(--muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.row1 .when { color: var(--ink); font-weight: 550; }
.row2 { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row2.none { color: var(--muted); font-style: italic; }
.row3 {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  align-items: center;
  font-size: 12px;
  color: var(--muted);
}
.empty { color: var(--muted); padding: 16px; }
.badges { display: flex; flex-wrap: wrap; gap: 5px; margin: 6px 0 14px; }
.badge {
  font-size: 11px; padding: 1px 7px; border-radius: 999px; border: 1px solid currentColor;
  white-space: nowrap; line-height: 16px;
}
.b-needs_you { color: var(--needs); } .b-outside_content { color: var(--outside); }
.b-could_not_finish { color: var(--failed); } .b-digest_failed { color: var(--digesting); }
.b-refused { color: var(--refused); } .b-truncated, .b-unreadable { color: var(--muted); }
.b-open { color: var(--accent); } .b-replayed { color: var(--accent); }
.back { display: none; }
h1.input {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 4px;
  white-space: pre-wrap;
  word-break: break-word;
}
h1.input.none { color: var(--muted); font-style: italic; }
.meta { color: var(--muted); display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; }
.meta b { color: var(--ink); font-weight: 600; }
.card {
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 14px; margin-top: 14px;
}
.card-title {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .6px;
  color: var(--muted);
  margin-bottom: 8px;
  cursor: default;
}
details.card > summary { cursor: pointer; margin-bottom: 0; }
.arrival-message { border-top: 1px solid var(--line); margin-top: 8px; padding-top: 6px; }
.arrival-message .m { color: var(--muted); font-size: 12px; }
details.card[open] > summary { margin-bottom: 8px; }
.timeline { position: relative; }
.tl-axis, .tl-lane { display: grid; grid-template-columns: 110px 1fr; align-items: center; }
.tl-axis { height: 20px; color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.tl-lane { min-height: 30px; border-top: 1px solid var(--line); }
.tl-label {
  font-size: 12px;
  color: var(--muted);
  padding-right: 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tl-label.has { color: var(--ink); }
.tl-track { position: relative; height: 30px; }
.tl-axis .tl-track { height: 20px; }
.tick { position: absolute; top: 2px; transform: translateX(-50%); white-space: nowrap; }
.tick:first-child { transform: none; }
.grid {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--line);
  pointer-events: none;
}
.bar {
  position: absolute; top: 6px; height: 18px; border-radius: 4px; min-width: 3px;
  cursor: pointer; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
  font-size: 11px; line-height: 18px; padding: 0 5px; color: #fff;
  background: var(--lane); opacity: .9;
}
/* A step and the model call inside it take bands of their own, so a call never covers
   its step and both stay clickable (ADR-0316 §3:3): the step above, the call below. */
.bar.step { opacity: .32; color: var(--ink); top: 3px; height: 11px; line-height: 11px;
  font-size: 10px; }
.bar.step.t-failed, .bar.step.t-timed_out { opacity: .9; background: var(--failed); color: #fff; }
.bar.call {
  top: 16px;
  height: 11px;
  line-height: 11px;
  font-size: 10px;
  opacity: 1;
  padding: 0 4px;
}
.bar.call.t-failed { background: var(--failed); }
.bar.call.t-pending {
  background: repeating-linear-gradient(
    45deg, var(--lane), var(--lane) 4px, transparent 4px, transparent 8px
  );
  color: var(--ink);
}
.bar:hover, .pt:hover { outline: 2px solid var(--accent); outline-offset: 1px; z-index: 3; }
.pt {
  position: absolute; top: 9px; width: 12px; height: 12px; margin-left: -6px;
  transform: rotate(45deg); background: var(--lane); border-radius: 2px; cursor: pointer;
  border: 2px solid var(--panel);
}
.pt.t-failed { background: var(--failed); } .pt.t-needs_you { background: var(--needs); }
.pt.t-refused { background: var(--refused); }
.pt.k-end { transform: none; border-radius: 50%; background: var(--ink); }
.pt.k-truncated {
  transform: none;
  width: 4px;
  margin-left: -2px;
  top: 2px;
  height: 26px;
  background: var(--failed);
  border: none;
  border-radius: 1px;
}
.pt.k-message {
  transform: none;
  border-radius: 3px;
  width: 16px;
  margin-left: -8px;
  height: 11px;
  top: 10px;
  background: transparent;
  border: 2px solid var(--acting);
}
.pt.k-message::after {
  content: "";
  position: absolute;
  left: 1px;
  right: 1px;
  top: 0;
  height: 5px;
  border-bottom: 2px solid var(--acting);
  border-left: 0;
  transform: skewY(20deg);
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 10px;
  color: var(--muted);
  font-size: 11px;
}
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.sw {
  width: 18px;
  height: 9px;
  border-radius: 2px;
  display: inline-block;
  background: var(--planning);
}
.sw.step {
  opacity: .32;
  } .sw.msg { background: transparent;
  border: 2px solid var(--acting);
  height: 10px;
  width: 14px;
}
.sw.dia { width: 9px; height: 9px; transform: rotate(45deg); }
.round { border-top: 1px solid var(--line); padding: 10px 0; cursor: pointer; }
.round:first-child { border-top: none; padding-top: 2px; }
.round:hover .round-head { color: var(--accent); }
.round-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; font-size: 13px; }
.round-head .n { font-weight: 650; color: var(--planning); }
.round-head .m { color: var(--muted); font-size: 12px; }
.round-text { white-space: pre-wrap; word-break: break-word; margin: 6px 0 2px; }
.round-text.none { color: var(--muted); font-style: italic; }
.chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.chip {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 4px;
  background: var(--hover);
  font-family: var(--mono);
}
.chip.v-allowed { color: var(--acting); } .chip.v-needs_you { color: var(--needs); }
.chip.v-not_done { color: var(--refused); }
.msg-note { font-size: 12px; color: var(--acting); margin-top: 6px; }
.msg-note.no { color: var(--refused); }
.entries { font-family: var(--mono); font-size: 12px; }
.entry-row {
  display: grid;
  grid-template-columns: 90px 110px 80px 1fr;
  gap: 8px;
  padding: 3px 4px;
  cursor: pointer;
  border-radius: 4px;
}
.entry-row:hover { background: var(--hover); }
.drawer {
  position: fixed; top: 0; right: 0; bottom: 0; width: min(720px, 100%); z-index: 10;
  background: var(--panel); border-left: 1px solid var(--line);
  box-shadow: -12px 0 30px rgba(0,0,0,.18); display: flex; flex-direction: column;
}
.drawer[hidden] { display: none; }
.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
}
.drawer-title { font-weight: 600; }
.close {
  background: none;
  border: none;
  color: var(--muted);
  font-size: 22px;
  cursor: pointer;
  line-height: 1;
}
.drawer-body { overflow-y: auto; padding: 8px 16px 40px; }
.sec { margin-top: 14px; }
.sec h3 {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .6px;
  color: var(--muted);
  margin: 0 0 6px;
}
.sec h4 { font-size: 13px; margin: 10px 0 4px; }
.kv { display: grid; grid-template-columns: max-content 1fr; gap: 3px 12px; font-size: 13px; }
.kv dt { color: var(--muted); } .kv dd { margin: 0; word-break: break-word; }
pre {
  font-family: var(--mono); font-size: 12px; background: var(--bg); border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 10px;
  margin: 4px 0;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 480px; overflow: auto;
}
.thinking { border-left: 3px solid var(--planning); }
.note { color: var(--muted); font-size: 12px; font-style: italic; }
button { font: inherit; }
.back {
  background: none;
  border: none;
  color: var(--accent);
  padding: 0;
  margin-bottom: 10px;
  cursor: pointer;
}
[hidden] { display: none !important; }
.drawer.wide { width: min(1100px, 100%); }
.drawer-head { gap: 10px; flex-wrap: wrap; }
.drawer-title { flex: 1 1 auto; min-width: 0; }
.drawer-tabs { display: flex; gap: 4px; }
.tab {
  border: 1px solid var(--line); background: none; color: var(--muted); border-radius: 6px;
  padding: 2px 10px; cursor: pointer; font-size: 12px;
}
.tab[aria-pressed="true"] {
  background: var(--select); color: var(--ink); border-color: var(--accent);
}
.call-head h2 { font-size: 16px; margin: 10px 0 2px; }
.call-head .m { color: var(--muted); font-size: 12px; }
.call-stats { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.call-nav { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 6px; }
.call-nav button {
  font-size: 12px; border: 1px solid var(--line); background: var(--bg); color: var(--accent);
  border-radius: 999px; padding: 1px 10px; cursor: pointer;
}
.call-sec { margin-top: 18px; scroll-margin-top: 8px; }
.replay { border-left: 3px solid var(--accent); padding: 2px 0 6px 10px; margin: 12px 0; }
.replay-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
.replay-head h4 { margin: 0; font-size: 13px; font-family: var(--mono); overflow-wrap: anywhere; }
.replay-head .m { color: var(--muted); font-size: 12px; }
.replay-head h5 { margin: 0; font-size: 12px; font-family: var(--mono); color: var(--muted); }
.replay-sample { border-top: 1px dashed var(--line); padding-top: 6px; margin-top: 8px; }
.follow-up { border-left: 2px dashed var(--accent); padding: 2px 0 2px 8px; margin: 8px 0 0; }
.call-sec > .sec-head {
  display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
  border-bottom: 1px solid var(--line); padding-bottom: 4px; margin-bottom: 6px;
}
.call-sec > .sec-head h3 {
  font-size: 12px; text-transform: uppercase; letter-spacing: .6px; color: var(--ink); margin: 0;
}
.call-sec > .sec-head .m { color: var(--muted); font-size: 12px; }
.call-sec > .sec-head .copy { margin-left: auto; }
.part-heading { font-size: 13px; margin: 12px 0 4px; color: var(--planning); }
.part {
  border: 1px solid var(--line); border-radius: 8px; margin: 6px 0; background: var(--panel);
  min-width: 0;
}
.part-head {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 4px 8px;
  font-size: 12px; color: var(--muted);
}
.part > .part-head { border-bottom: 1px solid var(--line); }
details.part:not([open]) > summary.part-head { border-bottom: none; }
details.part > summary { cursor: pointer; list-style: none; }
details.part > summary::-webkit-details-marker { display: none; }
details.part > summary::before { content: "\u25b8"; color: var(--muted); }
details.part[open] > summary::before { content: "\u25be"; }
.part-head .name { color: var(--ink); font-weight: 600; font-family: var(--mono); }
.part-head .end { margin-left: auto; display: inline-flex; align-items: center; gap: 8px; }
.part-head .size { font-variant-numeric: tabular-nums; white-space: nowrap; }
.part-head .tag {
  font-size: 11px; border: 1px solid currentColor; border-radius: 999px; padding: 0 6px;
}
.part-text { white-space: pre-wrap; word-break: break-word; padding: 6px 10px; line-height: 1.5; }
.part-text.thinking { border-left: 3px solid var(--planning); }
.part pre { margin: 6px 8px; }
.part .lists {
  font-size: 12px; color: var(--muted); padding: 4px 10px 0; font-family: var(--mono);
}
.copy {
  font-size: 11px; border: 1px solid var(--line); background: var(--bg); color: var(--ink);
  border-radius: 4px; padding: 0 7px; cursor: pointer; line-height: 18px;
}
.copy:hover { border-color: var(--accent); }
.fail { color: var(--failed); }
.diff span { display: block; }
.diff .add { color: var(--acting); background: rgba(47, 157, 85, .10); }
.diff .del { color: var(--failed); background: rgba(210, 60, 60, .10); }
.diff .hunk { color: var(--muted); }
.ch-added { color: var(--acting); } .ch-removed { color: var(--failed); }
.ch-changed { color: var(--needs); }
.asks { display: flex; flex-wrap: wrap; gap: 5px; padding: 6px 10px; }
.views { display: flex; gap: 4px; margin-right: auto; }
.view {
  border: 1px solid var(--line); background: none; color: var(--muted); border-radius: 6px;
  padding: 2px 10px; cursor: pointer; font-size: 12px;
}
.view[aria-pressed="true"] {
  background: var(--select); color: var(--ink); border-color: var(--accent);
}
.own-absent { margin: 4px 0 0; }
.ln-attempt { border-top: 1px solid var(--line); padding: 10px 0; }
.ln-attempt:first-child { border-top: none; padding-top: 2px; }
.ln-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; font-size: 13px; }
.ln-head .n { font-weight: 650; color: var(--scout); }
.ln-head .m { color: var(--muted); font-size: 12px; }
.ln-track {
  position: relative; height: 30px; margin: 6px 0 4px; border-radius: 4px;
  background: var(--bg); border: 1px solid var(--line);
}
.ln-track .bar.call { top: 9px; height: 12px; line-height: 12px; }
.ln-track .s-scout { --lane: var(--scout); } .ln-track .s-commit { --lane: var(--commit); }
.ln-track .s-framing, .ln-track .s-placement { --lane: var(--commit); }
.ln-track .pt { --lane: var(--scout); }
.pt.k-outcome.t-kept { background: var(--kept); }
.pt.k-outcome.t-not_kept { background: var(--not-kept); }
.pt.t-held { background: var(--needs); }
.ln-scale { display: flex; justify-content: space-between; color: var(--muted); font-size: 11px;
  font-variant-numeric: tabular-nums; }
.ln-entries { font-family: var(--mono); font-size: 12px; margin-top: 6px; }
.ln-steps { display: flex; flex-wrap: wrap; gap: 4px; margin: 4px 0 2px; }
.ln-steps .t-kept { color: var(--kept); } .ln-steps .t-not_kept { color: var(--muted); }
.ln-steps .t-failed { color: var(--failed); } .ln-steps .t-held { color: var(--needs); }
.ln-steps .t-end { color: var(--ink); }
.learning { height: calc(100% - 45px); overflow-y: auto; padding: 18px 22px 40px; }
.ov-head-block { max-width: 1180px; margin: 0 auto; }
.ov-title { font-size: 18px; margin: 0 0 4px; }
.ov-stats { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
.ov-tools { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 4px; }
.ov-filters { display: flex; flex-wrap: wrap; gap: 4px; }
.ov-search {
  flex: 1 1 240px; min-width: 0; font: inherit; font-size: 13px; padding: 4px 8px;
  border: 1px solid var(--line); border-radius: 6px; background: var(--panel); color: var(--ink);
}
#ov-list { max-width: 1180px; margin: 0 auto; }
.ov-card {
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 10px 14px; margin-top: 12px;
}
.ov-card-head { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; }
.ov-card-head .when { font-weight: 600; font-variant-numeric: tabular-nums; }
.ov-card-head .m { color: var(--muted); font-size: 12px; }
.ov-card-head .open-act { margin-left: auto; }
.ov-input { margin: 4px 0 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ov-input.none { color: var(--muted); font-style: italic; }
.b-processed { color: var(--kept); } .b-waiting { color: var(--needs); }
.b-stuck { color: var(--failed); } .b-skipped { color: var(--muted); }
.b-no_end { color: var(--muted); }
.findings { margin-top: 6px; }
.ov-finding {
  display: grid; grid-template-columns: 30px minmax(0, 1.25fr) minmax(0, 1fr) auto;
  gap: 4px 10px; align-items: start; padding: 6px 0; border-top: 1px solid var(--line);
}
.ov-finding .fid {
  font-family: var(--mono); font-size: 12px; color: var(--muted); padding-top: 1px;
}
.ov-finding .claim { word-break: break-word; }
.ov-finding .claim.none { color: var(--muted); font-style: italic; }
.ov-finding .result { font-size: 13px; word-break: break-word; }
.ov-finding .said { margin-top: 2px; }
.ov-finding .why { color: var(--muted); font-size: 12px; margin-top: 2px; }
.ov-finding .links { display: flex; flex-wrap: wrap; gap: 4px; justify-content: flex-end; }
.oc {
  font-size: 11px; padding: 1px 7px; border-radius: 999px; border: 1px solid currentColor;
  white-space: nowrap; display: inline-block; line-height: 16px;
}
.oc.kept { color: var(--kept); } .oc.not_kept { color: var(--not-kept); }
.oc.pending { color: var(--needs); }
.jump {
  font-size: 11px; border: 1px solid var(--line); background: var(--bg); color: var(--accent);
  border-radius: 999px; padding: 0 9px; cursor: pointer; line-height: 18px;
}
.jump:hover { border-color: var(--accent); }
.jump[disabled] { color: var(--muted); cursor: default; border-color: var(--line); }
.elsewhere { color: var(--muted); font-size: 12px; }
.modes { display: flex; gap: 4px; margin: 0 0 4px; }
.walk-bar { display: flex; align-items: center; gap: 8px; }
.walk-count {
  flex: 1 1 auto; text-align: center; color: var(--muted); font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.walk-nav {
  border: 1px solid var(--line); background: var(--bg); color: var(--accent); border-radius: 6px;
  padding: 3px 12px; cursor: pointer; font-size: 13px; white-space: nowrap;
}
.walk-nav:hover { border-color: var(--accent); }
.walk-nav[disabled] { color: var(--muted); cursor: default; border-color: var(--line); }
.walk-steps {
  list-style: none; display: flex; flex-wrap: wrap; gap: 4px; padding: 0; margin: 10px 0 4px;
}
.walk-pill {
  font-size: 11px; border: 1px solid var(--line); background: none; color: var(--muted);
  border-radius: 999px; padding: 1px 8px; cursor: pointer; max-width: 220px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; line-height: 16px;
}
.walk-pill[aria-current="step"] {
  background: var(--select); color: var(--ink); border-color: var(--accent);
}
.walk-step { min-width: 0; }
.walk-head h2 { font-size: 16px; margin: 12px 0 2px; }
.walk-head .m { color: var(--muted); font-size: 12px; }
.walk-item { border-top: 1px solid var(--line); padding: 6px 0; min-width: 0; }
.walk-item:first-of-type { border-top: none; }
.walk-item .m { color: var(--muted); font-size: 12px; }
.walk-item .id { font-family: var(--mono); font-size: 12px; overflow-wrap: anywhere; }
.walk-item .said { white-space: pre-wrap; word-break: break-word; margin-top: 2px; }
.walk-label { display: flex; gap: 8px; align-items: baseline; margin: 3px 0; min-width: 0; }
.walk-label .t { word-break: break-word; min-width: 0; }
.walk-links { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; }
@media (max-width: 760px) {
  .learning { padding: 14px 16px 40px; height: auto; overflow: visible; }
  .views { margin-right: 0; }
  .top { flex-wrap: wrap; }
  .ov-finding { grid-template-columns: 26px minmax(0, 1fr); }
  .ov-finding .result, .ov-finding .links { grid-column: 2; }
  .ov-finding .links { justify-content: flex-start; }
  .ov-card-head .open-act { margin-left: 0; }
}
@media (max-width: 760px) {
  .layout { grid-template-columns: 1fr; height: auto; }
  .list-pane { border-right: none; }
  .detail-pane { display: none; padding: 14px 16px 40px; }
  body.show-detail .list-pane { display: none; }
  body.show-detail .detail-pane { display: block; }
  .back { display: inline-block; }
  .tl-axis, .tl-lane { grid-template-columns: 78px 1fr; }
  .walk-pill { max-width: 150px; }
  .walk-nav { padding: 3px 8px; }
  .tl-label { font-size: 11px; }
  .entry-row { grid-template-columns: 70px 1fr; }
  .entry-row span:nth-child(3), .entry-row span:nth-child(4) { display: none; }
}
body.show-learning .layout { display: none; }
"""

SCRIPT: Final = r"""
"use strict";
(() => {
  const LANE_NAMES = {
    controller: "controller", recall: "recall", understanding: "understanding",
    planning: "planning", authorizing: "authorizing", acting: "acting", digesting: "digesting",
  };
  const BADGES = {
    needs_you: "needs you", outside_content: "outside content read",
    could_not_finish: "couldn't finish", digest_failed: "digest failed",
    refused: "refused", truncated: "truncated", replayed: "replayed",
  };
  const ENDINGS = {
    nothing_due: "finished", round_limit_reached: "round limit reached",
    stage_failed: "a stage failed", stage_timed_out: "a stage timed out",
    stage_repeated: "a stage repeated", interrupted: "interrupted", stopped: "stopped by you",
    hub_stopped: "hub stopped", no_text_input: "no text input",
    ended_before_controller: "ended before the controller",
  };
  const DASH = "\u2013";
  const OPEN_FOR_MS = 120000;
  // The reserved tool a planning round's notes ride on, as the record names it; a hint
  // (ADR-0316 \u00a75:2), so a record that names it otherwise loses its description alone.
  const ROUND_TOOL = "planning_round";
  const state = {
    listVersion: null, list: [], present: true, now: null, selected: null,
    detailVersion: null, detail: null, drawnOpen: false, listBusy: false, detailBusy: false,
    view: "activations", learningVersion: null, learning: [], learningPresent: true,
    learningBusy: false, filter: "all", search: "",
    // Walk mode: the step shown, from 1, or null for the overview; and the steps.
    walk: null, walkData: null, walkVersion: null, walkBusy: false,
  };
  // The hash that shows the learning overview: no activation id the hub mints is it.
  const LEARNING = "learning";

  const $ = (id) => document.getElementById(id);
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function words(value) { return String(value).replace(/_/g, " "); }
  function laneName(key) { return LANE_NAMES[key] || key; }
  function ending(rule) { return rule ? (ENDINGS[rule] || words(rule)) : null; }
  function duration(ms) {
    if (ms === null || ms === undefined || isNaN(ms)) return DASH;
    if (ms < 1000) return Math.round(ms) + " ms";
    if (ms < 60000) return (ms / 1000).toFixed(ms < 10000 ? 2 : 1) + " s";
    const m = Math.floor(ms / 60000);
    const s = Math.round((ms % 60000) / 1000);
    return m + " m " + s + " s";
  }
  function clock(ms, withDate) {
    if (ms === null || ms === undefined) return DASH;
    const d = new Date(ms);
    const time = d.toLocaleTimeString([], {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
    if (!withDate || d.toDateString() === new Date().toDateString()) return time;
    return d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + time;
  }
  function isOpen(summary) {
    return summary.open && state.now !== null && summary.last !== null
      && state.now - summary.last < OPEN_FOR_MS;
  }
  function badge(name, label) { return el("span", "badge b-" + name, label); }
  function badgesFor(summary, node) {
    if (isOpen(summary)) node.appendChild(badge("open", "running"));
    for (const name of summary.badges || []) {
      node.appendChild(badge(name, BADGES[name] || words(name)));
    }
    if (summary.unreadable) {
      node.appendChild(badge("unreadable", summary.unreadable + " unreadable"));
    }
  }
  function endingText(summary) {
    if (summary.ended) return ending(summary.ended);
    if (summary.badges && summary.badges.includes("truncated")) return "truncated";
    return isOpen(summary) ? "" : "no end recorded";
  }

  async function getJson(url) {
    const response = await fetch(url, { cache: "no-store", credentials: "same-origin" });
    if (response.status === 404) return null;
    if (!response.ok) throw new Error("status " + response.status);
    return response.json();
  }
  function status(text, cls) {
    const node = $("status");
    node.textContent = text;
    node.className = "status " + (cls || "");
  }
  function lost() { status("connection lost, retrying…", "lost"); }

  // --- the list ---------------------------------------------------------------------
  async function pollList() {
    if (state.listBusy) return;
    state.listBusy = true;
    try {
      let url = "/api/activations";
      if (state.listVersion) url += "?v=" + encodeURIComponent(state.listVersion);
      const data = await getJson(url);
      if (data) {
        state.now = data.now;
        if (!data.unchanged) {
          state.listVersion = data.version;
          state.list = data.activations || [];
          state.present = data.present;
        }
        renderList();
        const n = state.list.length;
        status("live · " + n + (n === 1 ? " activation" : " activations"), "live");
      }
    } catch (error) {
      lost();
    } finally {
      state.listBusy = false;
    }
  }
  function renderList() {
    const list = $("list");
    clear(list);
    const empty = $("list-empty");
    empty.hidden = state.list.length > 0;
    empty.textContent = state.present === false
      ? "The record's directory does not exist yet: no activation has been recorded."
      : "No activations in the record yet.";
    for (const one of state.list) {
      const item = el("li");
      if (one.id === state.selected) item.classList.add("selected");
      const row1 = el("div", "row1");
      row1.appendChild(el("span", "when", clock(one.start, true)));
      row1.appendChild(el("span", null, duration(one.duration)));
      row1.appendChild(el("span", null, one.rounds + (one.rounds === 1 ? " round" : " rounds")));
      item.appendChild(row1);
      const input = el("div", "row2" + (one.input ? "" : " none"), one.input || "input not shown");
      item.appendChild(input);
      const row3 = el("div", "row3");
      row3.appendChild(el("span", null, endingText(one)));
      badgesFor(one, row3);
      item.appendChild(row3);
      item.addEventListener("click", () => select(one.id));
      list.appendChild(item);
    }
  }

  // --- one activation ----------------------------------------------------------------
  // ``walk`` is the step to show, from 1, or null for the overview; left out, a change of
  // activation keeps the mode it is in, from its first step.
  function select(id, walk) {
    showView("activations");
    if (walk !== undefined) state.walk = walk;
    if (state.selected !== id) {
      if (walk === undefined && state.walk !== null) state.walk = 1;
      state.selected = id;
      state.detailVersion = null;
      state.detail = null;
      state.walkData = null;
      state.walkVersion = null;
      closeDrawer();
      renderWalk();
      // The previous activation's details come down at once: nothing of one
      // activation stays clickable while another's load.
      $("detail-body").hidden = true;
      const empty = $("detail-empty");
      empty.hidden = false;
      empty.textContent = "Loading\u2026";
    }
    writeHash();
    applyMode();
    document.body.classList.add("show-detail");
    renderList();
    pollDetail();
  }
  async function pollDetail() {
    if (!state.selected || state.detailBusy) return;
    state.detailBusy = true;
    const id = state.selected;
    try {
      let url = "/api/activation?id=" + encodeURIComponent(id);
      if (state.detailVersion) url += "&v=" + encodeURIComponent(state.detailVersion);
      const data = await getJson(url);
      if (id !== state.selected) return;
      if (data === null) {
        renderGone();
        return;
      }
      state.now = data.now;
      if (!data.unchanged) {
        state.detail = data;
        state.detailVersion = data.version;
        renderDetail();
      } else if (state.detail) {
        // An activation that stops writing stops being "running" with no new byte in
        // its file: redraw everything that says so once it lapses.
        const open = isOpen(state.detail.summary);
        if (open !== state.drawnOpen) renderDetail();
        else if (open) renderTimeline();
      }
    } catch (error) {
      lost();
    } finally {
      state.detailBusy = false;
    }
    // The walk is read from the same files: it is read again when they change.
    if (state.walk !== null && state.detail && state.walkVersion !== state.detailVersion) {
      pollWalk();
    }
  }
  function renderGone() {
    const empty = $("detail-empty");
    empty.hidden = false;
    empty.textContent = "That activation's files are gone: the record's window deleted them.";
    $("detail-body").hidden = true;
  }
  function renderDetail() {
    const d = state.detail;
    $("detail-empty").hidden = true;
    $("detail-body").hidden = false;
    const s = d.summary;
    const own = d.own !== false;
    // ADR-0333 \u00a75:6: an activation whose own file is absent shows its learning alone.
    for (const id of ["timeline-card", "rounds-card", "entries-card"]) $(id).hidden = !own;
    const absent = $("d-own-absent");
    absent.hidden = own;
    absent.textContent = own ? "" : "This activation's own record is absent: swept by the "
      + "record's window, never written, or written while the record was off. What the "
      + "observer learned from it is shown alone.";
    const input = $("d-input");
    input.textContent = s.input || (own ? "input not shown" : "own record absent");
    input.className = "input" + (s.input ? "" : " none");
    const meta = $("d-meta");
    clear(meta);
    const learning = d.learning;
    const pairs = own ? [
      ["started", clock(s.start, true)], ["took", duration(s.duration)], ["rounds", s.rounds],
      ["ended", endingText(s) || "not yet"], ["entries", s.entries],
    ] : [["learned", clock(learning ? learning.latest : null, true)],
      ["attempts", learning ? learning.attempts.length : 0]];
    for (const [k, v] of pairs) {
      const span = el("span", null, k + " ");
      span.appendChild(el("b", null, v));
      meta.appendChild(span);
    }
    const badges = $("d-badges");
    clear(badges);
    badgesFor(s, badges);
    state.drawnOpen = isOpen(s);
    applyMode();
    if (state.walk !== null) renderWalk();
    renderArrival();
    if (own) {
      renderTimeline();
      renderRounds();
      renderEntries();
    }
    renderLearningLane();
  }

  // The input as it arrived, read back from the first request that shows it: the record
  // keeps no entry of its own for it.
  function renderArrival() {
    const a = state.detail.arrival;
    const root = $("arrival");
    clear(root);
    $("arrival-card").hidden = !a;
    if (a) arrivalInto(root, a);
  }
  function arrivalInto(root, a) {
    const read = a.from === "understanding" ? "understanding's input" : "planning's place window";
    kv(root, [["where", a.received_as], ["read from", read + ", line " + a.line]]);
    const rows = a.messages || [];
    // Understanding shows the input's messages only where it has them: else, its text.
    if (!rows.length) root.appendChild(el("div", "part-text arrival-text", a.text));
    for (const m of rows) {
      const row = el("div", "arrival-message");
      const at = clock(m.at, true);
      row.appendChild(el("div", "m", m.position === null ? at : "#" + m.position + " · " + at));
      row.appendChild(el("div", "part-text", m.text === null ? DASH : m.text));
      root.appendChild(row);
    }
  }

  // --- the timeline ------------------------------------------------------------------
  // A step of 1, 2 or 5 times a power of ten, so no span draws more than seven ticks.
  function niceStep(span) {
    for (let base = 1; ; base *= 10) {
      for (const m of [1, 2, 5]) if (span / (base * m) <= 7) return base * m;
    }
  }
  function tickLabel(ms, step) {
    if (step < 1000) return ms + " ms";
    if (step < 60000) return +(ms / 1000).toFixed(3) + " s";
    if (step < 3600000) return +(ms / 60000).toFixed(3) + " m";
    if (step < 86400000) return +(ms / 3600000).toFixed(3) + " h";
    return +(ms / 86400000).toFixed(3) + " d";
  }
  function renderTimeline() {
    const d = state.detail;
    const root = $("timeline");
    clear(root);
    const start = d.start;
    let end = d.end;
    if (isOpen(d.summary) && state.now !== null) end = Math.max(end || start, state.now);
    if (start === null || end === null) {
      root.appendChild(el("p", "note", "No entries yet."));
      return;
    }
    const span = Math.max(end - start, 1);
    const pos = (t) => Math.min(100, Math.max(0, ((t - start) / span) * 100));
    const step = niceStep(span);
    const axis = el("div", "tl-axis");
    axis.appendChild(el("div", "tl-label"));
    const axisTrack = el("div", "tl-track");
    const grid = [];
    for (let t = 0; t <= span; t += step) {
      const tick = el("span", "tick", tickLabel(t, step));
      tick.style.left = pos(start + t) + "%";
      axisTrack.appendChild(tick);
      grid.push(pos(start + t));
    }
    axis.appendChild(axisTrack);
    root.appendChild(axis);
    const byLane = new Map();
    for (const item of d.items) {
      if (!byLane.has(item.lane)) byLane.set(item.lane, []);
      byLane.get(item.lane).push(item);
    }
    for (const lane of d.lanes) {
      const items = byLane.get(lane.key) || [];
      const row = el("div", "tl-lane");
      row.style.setProperty("--lane", "var(--" + (lane.known ? lane.key : "unknown") + ")");
      const label = el("div", "tl-label" + (items.length ? " has" : ""), laneName(lane.key));
      label.title = laneName(lane.key);
      row.appendChild(label);
      const track = el("div", "tl-track");
      for (const g of grid) {
        const line = el("div", "grid");
        line.style.left = g + "%";
        track.appendChild(line);
      }
      for (const item of drawOrder(items, end)) track.appendChild(drawItem(item, pos, end));
      row.appendChild(track);
      root.appendChild(row);
    }
    renderLegend();
  }
  // Steps first, then model calls, then entries' points, each later one drawn over the
  // earlier; within a layer the longer first, so nothing shorter is hidden under it. A
  // step and its call also take bands of their own (the stylesheet), so a call never
  // covers its step: every item stays clickable (ADR-0316 \u00a73:3).
  function drawOrder(items, end) {
    const layer = (item) => (item.type !== "span" ? 2 : item.kind === "step" ? 0 : 1);
    const width = (item) => (item.end === null ? end : item.end) - item.start;
    return items.slice().sort((a, b) => layer(a) - layer(b) || width(b) - width(a));
  }
  function drawItem(item, pos, end) {
    const tone = "t-" + item.tone;
    const itemEnd = item.end === null ? end : item.end;
    let node;
    if (item.type === "span") {
      const width = Math.max(0, pos(itemEnd) - pos(item.start));
      // A label is drawn only where the bar has room for it; the title always has it.
      node = el("div", "bar " + item.kind + " " + tone, width >= 6 ? item.label : null);
      node.style.width = width + "%";
    } else {
      node = el("div", "pt k-" + item.kind + " " + tone);
    }
    node.style.left = pos(item.start) + "%";
    let title = laneName(item.lane) + " · " + item.label;
    if (item.round) title += " · round " + item.round;
    const open = isOpen(state.detail.summary);
    if (item.type === "span" && item.end !== null) {
      title += " · " + duration(itemEnd - item.start);
    } else if (item.type === "span") {
      title += " · " + (open ? "running" : "no returned entry was recorded");
    }
    if (item.kind === "message") {
      title += " · allowed by authorizing; whether it was written is not recorded";
    }
    if (item.tone && !["ok", "done", "end", "pending"].includes(item.tone)) {
      title += " · " + words(item.tone);
    }
    node.title = title;
    const owner = state.detail.id;
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      openLines(owner, title, item.lines);
    });
    return node;
  }
  function renderLegend() {
    const legend = $("legend");
    clear(legend);
    const add = (cls, text) => {
      const s = el("span");
      s.appendChild(el("i", "sw " + cls));
      s.appendChild(document.createTextNode(text));
      legend.appendChild(s);
    };
    add("step", "controller step");
    add("", "model call or search");
    add("dia", "entry");
    add("msg", "message allowed (not a claim it was written)");
  }

  // --- rounds and entries ------------------------------------------------------------
  function roundHead(r) {
    const head = el("div", "round-head");
    head.appendChild(el("span", "n", "Round " + r.round));
    if (r.step) {
      let took = duration(r.step.end - r.step.start);
      if (r.step.outcome !== "done") took += " · " + words(r.step.outcome);
      head.appendChild(el("span", "m", took));
    }
    if (r.thinking) head.appendChild(el("span", "m", "thinking recorded"));
    if (r.marked) head.appendChild(el("span", "m", "marked"));
    if (r.outside) head.appendChild(badge("outside_content", "outside content read"));
    return head;
  }
  function renderRounds() {
    const d = state.detail;
    const root = $("rounds");
    clear(root);
    if (!d.rounds.length) {
      root.appendChild(el("p", "note", "No planning rounds."));
      return;
    }
    for (const r of d.rounds) {
      const box = el("div", "round");
      box.appendChild(roundHead(r));
      if (r.failure) {
        box.appendChild(el("div", "round-text none", "failed: " + r.failure));
      } else if (r.returned === undefined) {
        box.appendChild(el("div", "round-text none", "no response recorded yet"));
      } else {
        box.appendChild(el("div", "round-text" + (r.text ? "" : " none"), r.text || "no text"));
      }
      const chips = el("div", "chips");
      // A verdict belongs to its call by the provider's call id, never by the tool's
      // name: one round may call the same tool twice.
      const verdicts = new Map();
      for (const v of r.verdicts || []) if (v.call_id) verdicts.set(v.call_id, v.verdict);
      for (const call of r.calls || []) {
        const verdict = call.id ? verdicts.get(call.id) : undefined;
        const text = call.name + (verdict ? " · " + words(verdict) : "");
        chips.appendChild(el("span", "chip v-" + (verdict || "none"), text));
      }
      if (chips.childNodes.length) box.appendChild(chips);
      if (r.message && r.message.allowed) {
        box.appendChild(el("div", "msg-note",
          "message allowed by authorizing — whether it was written is not recorded"));
      } else if (r.message) {
        const why = r.message.reason ? ": " + r.message.reason : "";
        box.appendChild(el("div", "msg-note no", "message not allowed" + why));
      }
      const lines = [r.given, r.returned, r.authorizing].filter((one) => one !== undefined);
      box.addEventListener("click", () => openLines(d.id, "Round " + r.round, lines));
      root.appendChild(box);
    }
  }
  function renderEntries() {
    const d = state.detail;
    const root = $("entries");
    clear(root);
    root.className = "entries";
    for (const e of d.entries) {
      const row = el("div", "entry-row");
      row.appendChild(el("span", null, "+" + duration(e.at - d.start)));
      row.appendChild(el("span", null, e.source));
      row.appendChild(el("span", null, e.kind));
      row.appendChild(el("span", null, e.round ? "round " + e.round : ""));
      row.addEventListener("click", () => openLines(d.id, e.source + " " + e.kind, [e.line]));
      root.appendChild(row);
    }
    if (d.truncated) {
      root.appendChild(el("p", "note",
        "The file was truncated at " + clock(d.truncated.at) + ": nothing after it was written."));
    }
    if (d.unreadable) {
      root.appendChild(el("p", "note", d.unreadable + " unreadable line(s) were skipped."));
    }
  }

  // --- the learning lane (ADR-0333 §5:2-§5:3) -------------------------------------
  // Drawn over the observer's own instants, one attempt to a row, each row on its own
  // scale: an attempt can come days after the activation, and none of it widens the
  // activation's timeline, its duration or its row in the list.
  const STATES = { processed: "processed", waiting: "waiting", stuck: "stuck",
    skipped: "skipped" };
  function attemptEnding(ended) {
    if (!ended) return "no end recorded";
    let text = ended.skipped ? "skipped: nothing to read" : words(ended.state || ended.end || "");
    if (ended.end === "held") text = "held by the daily budget · " + words(ended.state || "");
    else if (ended.end === "failed") text = "failed · " + words(ended.state || "");
    return text;
  }
  function renderLearningLane() {
    const d = state.detail;
    const card = $("learning-card");
    const root = $("learning-lane");
    clear(root);
    const learning = d.learning;
    card.hidden = !learning;
    if (!learning) return;
    if (!learning.attempts.length) {
      root.appendChild(el("p", "note", "The observer file holds no entry yet."));
    }
    const byAttempt = new Map();
    for (const f of learning.findings) {
      if (!byAttempt.has(f.attempt)) byAttempt.set(f.attempt, []);
      byAttempt.get(f.attempt).push(f);
    }
    const numbers = new Map(learning.attempts.map((a) => [a.key, a.number]));
    for (const a of learning.attempts) {
      const box = el("div", "ln-attempt");
      const head = el("div", "ln-head");
      head.appendChild(el("span", "n", "Attempt " + a.number));
      head.appendChild(el("span", "m", clock(a.start, true)));
      if (a.end !== null && a.start !== null) {
        head.appendChild(el("span", "m", duration(a.end - a.start)));
      }
      const ending = el("span", "badge b-" + ((a.ended && a.ended.state) || "no_end"),
        attemptEnding(a.ended));
      head.appendChild(ending);
      box.appendChild(head);
      if (a.ended && a.ended.failure) box.appendChild(el("div", "fail", a.ended.failure));
      box.appendChild(learningTrack(d.id, a));
      for (const f of byAttempt.get(a.key) || []) {
        box.appendChild(findingRow(d.id, f, { full: true, numbers, here: a.key }));
      }
      root.appendChild(box);
    }
    const all = el("details", "ln-entries");
    const count = learning.entries.length;
    all.appendChild(el("summary", "note", "Every learning entry (" + count + ")"));
    for (const e of learning.entries) {
      const row = el("div", "entry-row");
      row.appendChild(el("span", null, clock(e.at)));
      row.appendChild(el("span", null, e.stage || "?"));
      row.appendChild(el("span", null, e.kind));
      row.appendChild(el("span", null, "attempt " + (numbers.get(e.attempt) || "?")));
      const call = e.kind === "step" ? null : callable(learning, e.line);
      row.addEventListener("click", () => openLines(d.id, "observer · " + (e.stage || e.kind),
        [e.line], { file: "observer", call }));
      all.appendChild(row);
    }
    if (learning.truncated) {
      all.appendChild(el("p", "note", "The observer file was truncated: nothing after its "
        + "marker was written."));
    }
    if (learning.unreadable) {
      all.appendChild(el("p", "note", learning.unreadable + " unreadable line(s) were skipped."));
    }
    root.appendChild(all);
  }
  // The given line of the call ``line`` belongs to, or null where it is no call's.
  function callable(learning, line) {
    for (const a of learning.attempts) {
      for (const item of a.items) {
        if (item.kind === "call" && item.lines.includes(line)) return item.call;
      }
    }
    return null;
  }
  function learningTrack(id, a) {
    const holder = el("div");
    const track = el("div", "ln-track");
    const start = a.start;
    const end = a.end === null ? start : a.end;
    const span = Math.max(end - start, 1);
    const pos = (t) => Math.min(100, Math.max(0, ((t - start) / span) * 100));
    for (const item of drawOrder(a.items, end)) {
      const tone = "t-" + item.tone;
      let node;
      if (item.type === "span") {
        const itemEnd = item.end === null ? end : item.end;
        const width = Math.max(0, pos(itemEnd) - pos(item.start));
        node = el("div", "bar call s-" + item.stage + " " + tone, width >= 8 ? item.label : null);
        node.style.width = width + "%";
      } else {
        node = el("div", "pt k-" + item.kind + " " + tone);
      }
      node.style.left = pos(item.start) + "%";
      let title = "observer · " + item.label;
      if (item.type === "span") {
        title += item.end === null ? " · no returned entry was recorded"
          : " · " + duration(item.end - item.start);
      }
      node.title = title;
      node.addEventListener("click", (event) => {
        event.stopPropagation();
        openLines(id, title, item.lines, { file: "observer", call: item.call });
      });
      track.appendChild(node);
    }
    holder.appendChild(track);
    const scale = el("div", "ln-scale");
    scale.appendChild(el("span", null, clock(start)));
    scale.appendChild(el("span", null, "+" + duration(end - start)));
    holder.appendChild(scale);
    // The attempt's step entries again, in order, as controls: several can share an
    // instant on the track, and each stays one click away.
    const steps = el("div", "ln-steps");
    for (const item of a.items) {
      if (item.type === "span") continue;
      const go = el("button", "jump t-" + item.tone, item.label);
      go.type = "button";
      go.addEventListener("click", () => openLines(id, "observer \u00b7 " + item.label, item.lines,
        { file: "observer", call: null }));
      steps.appendChild(go);
    }
    if (steps.childNodes.length) holder.appendChild(steps);
    return holder;
  }
  // One finding: its claim, what was kept of it or why not, and the jumps to the exact
  // prompt and reply behind it (ADR-0333 §5:5).
  function findingRow(id, f, opts) {
    const row = el("div", "ov-finding");
    row.appendChild(el("span", "fid", f.id));
    row.appendChild(el("div", "claim" + (f.claim ? "" : " none"), f.claim || "claim not recorded"));
    const result = el("div", "result");
    const o = f.outcome;
    if (!o) {
      result.appendChild(el("span", "oc pending", "no outcome yet"));
    } else {
      result.appendChild(el("span", "oc " + (o.kept ? "kept" : "not_kept"), o.short));
      if (o.kept && o.wording) {
        result.appendChild(el("div", "said", "“" + o.wording + "”"));
      }
      if (!o.kept && o.why) result.appendChild(el("div", "why", o.why));
      if (o.note) result.appendChild(el("div", "why", "note: " + o.note));
      if (opts.here && o.attempt && o.attempt !== opts.here && opts.numbers) {
        result.appendChild(el("div", "elsewhere",
          "decided in attempt " + (opts.numbers.get(o.attempt) || "?")));
      }
    }
    row.appendChild(result);
    const links = el("div", "links");
    const jump = (label, lines, call) => {
      const go = el("button", "jump", label);
      go.type = "button";
      const kept = lines.filter((one) => one !== null && one !== undefined);
      if (!kept.length) {
        go.disabled = true;
      } else {
        go.addEventListener("click", (event) => {
          event.stopPropagation();
          openLines(id, f.id + " · " + label.toLowerCase(), kept,
            { file: "observer", call: call === undefined ? null : call });
        });
      }
      links.appendChild(go);
    };
    const scout = f.scout || {};
    jump("Scout", [scout.given, scout.returned], scout.given);
    if (f.commit) {
      jump("Commit", [f.commit.given, f.commit.returned], f.commit.given);
    } else {
      const framing = f.framing || {};
      jump("Framing", [framing.given, framing.returned], framing.given);
    }
    arr(f.placements).forEach((one, at) => {
      const placed = obj(one);
      jump("Placement " + (at + 1), [placed.given, placed.returned], placed.given);
    });
    jump("Outcome", [f.findings_line, o ? o.line : null]);
    row.appendChild(links);
    return row;
  }

  // --- the learning overview (ADR-0333 §5:4-§5:5) ----------------------------------
  const FILTERS = [["all", "All findings"], ["kept", "Kept"], ["not_kept", "Not kept"],
    ["pending", "No outcome yet"], ["failed", "Failed attempts"]];
  function showView(view) {
    state.view = view;
    const learning = view === "learning";
    document.body.classList.toggle("show-learning", learning);
    $("learning").hidden = !learning;
    $("view-learning").setAttribute("aria-pressed", String(learning));
    $("view-activations").setAttribute("aria-pressed", String(!learning));
    if (learning) {
      closeDrawer();
      pollLearning();
    }
  }
  async function pollLearning() {
    if (state.view !== "learning" || state.learningBusy) return;
    state.learningBusy = true;
    try {
      let url = "/api/learning";
      if (state.learningVersion) url += "?v=" + encodeURIComponent(state.learningVersion);
      const data = await getJson(url);
      if (data && !data.unchanged) {
        state.learningVersion = data.version;
        state.learning = data.activations || [];
        state.learningPresent = data.present;
        renderLearning();
      }
    } catch (error) {
      lost();
    } finally {
      state.learningBusy = false;
    }
  }
  function matches(f) {
    const o = f.outcome;
    if (state.filter === "kept" && !(o && o.kept)) return false;
    if (state.filter === "not_kept" && !(o && !o.kept)) return false;
    if (state.filter === "pending" && o) return false;
    const needle = state.search.trim().toLowerCase();
    if (!needle) return true;
    const hay = [f.claim, o && o.wording, o && o.note, o && o.why].filter(Boolean)
      .join(" ").toLowerCase();
    return hay.includes(needle);
  }
  function renderLearning() {
    const list = $("ov-list");
    clear(list);
    const shown = state.learning;
    const findings = shown.flatMap((a) => a.findings);
    const kept = findings.filter((f) => f.outcome && f.outcome.kept).length;
    const notKept = findings.filter((f) => f.outcome && !f.outcome.kept).length;
    const stats = $("ov-stats");
    clear(stats);
    for (const text of [plural(shown.length, "activation", "activations"),
      plural(findings.length, "finding", "findings"), kept + " kept", notKept + " not kept",
      (findings.length - kept - notKept) + " with no outcome yet",
      plural(shown.reduce((n, a) => n + (a.failed || 0), 0), "failed attempt",
        "failed attempts")]) {
      stats.appendChild(el("span", "chip", text));
    }
    const filters = $("ov-filters");
    clear(filters);
    for (const [key, label] of FILTERS) {
      const b = el("button", "view", label);
      b.type = "button";
      b.setAttribute("aria-pressed", String(state.filter === key));
      b.addEventListener("click", () => { state.filter = key; renderLearning(); });
      filters.appendChild(b);
    }
    const empty = $("ov-empty");
    empty.hidden = shown.length > 0;
    empty.textContent = state.learningPresent === false
      ? "The record's directory does not exist yet: the observer has written nothing."
      : "No observer files in the record yet.";
    let drawnCards = 0;
    for (const a of shown) {
      const rows = a.findings.filter(matches);
      const failedOnly = state.filter === "failed";
      if (failedOnly ? !(a.failed || a.failure) : (!rows.length && (state.filter !== "all"
        || state.search.trim()))) continue;
      list.appendChild(overviewCard(a, failedOnly ? a.findings : rows));
      drawnCards += 1;
    }
    if (shown.length && !drawnCards) list.appendChild(el("p", "empty", "Nothing matches."));
  }
  function overviewCard(a, rows) {
    const card = el("article", "ov-card");
    const head = el("div", "ov-card-head");
    head.appendChild(el("span", "when", clock(a.latest, true)));
    head.appendChild(el("span", "badge b-" + (a.state || "no_end"),
      a.state ? (STATES[a.state] || words(a.state)) : "no end recorded"));
    head.appendChild(el("span", "m", plural(a.attempts, "attempt", "attempts")
      + (a.failed ? " · " + a.failed + " failed" : "")
      + (a.dropped ? " · " + plural(a.dropped, "proposal", "proposals")
        + " dropped by code" : "")));
    if (a.truncated) head.appendChild(badge("truncated", "truncated"));
    const open = el("button", "jump open-act", "Open activation →");
    open.type = "button";
    open.addEventListener("click", () => {
      location.hash = "#" + encodeURIComponent(a.id);
    });
    head.appendChild(open);
    card.appendChild(head);
    const input = a.input || (a.own ? "input not shown" : "own record absent");
    card.appendChild(el("div", "ov-input" + (a.input ? "" : " none"), input));
    if (a.failure) card.appendChild(el("div", "fail", "last attempt failed: " + a.failure));
    const box = el("div", "findings");
    for (const f of rows) box.appendChild(findingRow(a.id, f, {}));
    if (!a.findings.length) {
      box.appendChild(el("p", "note", a.state === "skipped"
        ? "Skipped by rule: nothing to read." : "No finding recorded."));
    }
    card.appendChild(box);
    return card;
  }

  // --- walk mode: one activation, a step at a time ------------------------------------
  // The activation in its own order, as a debugger steps through a finished run: each
  // step a summary, its entries one click away in the drawer the timeline opens.
  function writeHash() {
    if (!state.selected) return;
    let hash = "#" + encodeURIComponent(state.selected);
    if (state.walk !== null) hash += "/walk/" + state.walk;
    if (location.hash !== hash) history.replaceState(null, "", hash);
  }
  function applyMode() {
    const walking = state.walk !== null;
    $("overview").hidden = walking;
    $("walk-card").hidden = !walking;
    $("mode-overview").setAttribute("aria-pressed", String(!walking));
    $("mode-walk").setAttribute("aria-pressed", String(walking));
  }
  function setWalk(n) {
    const moved = n !== state.walk;
    state.walk = n;
    writeHash();
    applyMode();
    if (moved) closeDrawer();
    if (n === null) return;
    renderWalk();
    if (state.walkVersion === null || state.walkVersion !== state.detailVersion) pollWalk();
  }
  function moveWalk(by) {
    const steps = state.walkData ? state.walkData.steps || [] : [];
    if (state.walk === null || !steps.length) return;
    const n = Math.min(Math.max(state.walk + by, 1), steps.length);
    if (n !== state.walk) setWalk(n);
  }
  function walkKey(event) {
    if (state.walk === null || state.view !== "activations" || $("detail-body").hidden) return;
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const target = event.target;
    const tag = target && target.tagName ? target.tagName.toLowerCase() : "";
    if (["input", "textarea", "select"].includes(tag) || (target && target.isContentEditable)) {
      return;
    }
    event.preventDefault();
    moveWalk(event.key === "ArrowLeft" ? -1 : 1);
  }
  async function pollWalk() {
    if (state.walk === null || !state.selected || state.walkBusy) return;
    state.walkBusy = true;
    const id = state.selected;
    try {
      let url = "/api/walk?id=" + encodeURIComponent(id);
      if (state.walkVersion) url += "&v=" + encodeURIComponent(state.walkVersion);
      const data = await getJson(url);
      if (id !== state.selected) return;
      if (data === null) {
        renderGone();
        return;
      }
      if (!data.unchanged) {
        // The steps are this activation's: every link they draw opens this one's lines.
        state.walkData = { ...data, owner: id };
        state.walkVersion = data.version;
      }
      if (state.walk !== null) renderWalk();
    } catch (error) {
      lost();
    } finally {
      state.walkBusy = false;
    }
  }
  function renderWalk() {
    if (state.walk === null) return;
    const root = $("walk-step");
    const pills = $("walk-steps");
    clear(root);
    clear(pills);
    // Another activation's steps are never drawn under this one's, while its own load.
    const data = state.walkData && state.walkData.owner === state.selected
      ? state.walkData : null;
    const steps = data ? data.steps || [] : [];
    $("walk-prev").disabled = true;
    $("walk-next").disabled = true;
    $("walk-count").textContent = "";
    if (!data) {
      root.appendChild(el("p", "note", "Loading…"));
      return;
    }
    if (!steps.length) {
      root.appendChild(el("p", "note", "Nothing to walk: the record holds no entry of it yet."));
      return;
    }
    const n = Math.min(Math.max(state.walk, 1), steps.length);
    if (n !== state.walk) {
      state.walk = n;
      writeHash();
    }
    $("walk-count").textContent = "step " + n + " of " + steps.length;
    $("walk-prev").disabled = n <= 1;
    $("walk-next").disabled = n >= steps.length;
    steps.forEach((one, index) => {
      const holder = el("li");
      const go = el("button", "walk-pill", (index + 1) + " · " + one.title);
      go.type = "button";
      go.title = one.title;
      if (index + 1 === n) go.setAttribute("aria-current", "step");
      go.addEventListener("click", () => setWalk(index + 1));
      holder.appendChild(go);
      pills.appendChild(holder);
    });
    const shown = steps[n - 1];
    try {
      stepInto(root, shown, data);
    } catch (error) {
      root.appendChild(el("p", "note",
        "This step did not read as expected; its entries show it whole."));
      linksInto(root, shown, data.owner);
    }
  }
  function stepInto(root, s, data) {
    const head = el("div", "walk-head");
    head.appendChild(el("h2", null, s.title));
    const meta = [];
    if (s.phase === "learning") {
      meta.push(clock(s.start, true));
    } else if (s.start !== null && s.start !== undefined && data.start !== null) {
      meta.push("at +" + duration(s.start - data.start));
    }
    const st = s.step;
    if (st) {
      if (st.took !== null && st.took !== undefined && s.phase !== "end") {
        meta.push("took " + duration(st.took));
      }
      if (st.due && s.phase !== "end") meta.push("due: " + words(st.due));
      if (st.outcome && st.outcome !== "done") meta.push(words(st.outcome));
    } else if (!["input", "end", "learning"].includes(s.phase)) {
      meta.push("no step entry recorded for it");
    }
    head.appendChild(el("div", "m", meta.join(" · ")));
    root.appendChild(head);
    if (st && st.failure) root.appendChild(el("p", "fail", "the step failed: " + st.failure));
    const walker = WALKERS[s.phase];
    if (walker) walker(root, s, data.owner);
    else walkOther(root, s);
    linksInto(root, s, data.owner);
  }
  // ``owner`` is the activation the step is of: a link opens its lines, whatever is
  // selected when it is clicked.
  function linksInto(root, s, owner) {
    const links = s.links || [];
    if (!links.length) return;
    const row = el("div", "walk-links");
    for (const link of links) {
      const go = el("button", "jump", link.label);
      go.type = "button";
      go.addEventListener("click", () => openLines(owner, s.title + " · "
        + link.label, link.lines || [], { file: link.file || null,
        call: typeof link.call === "number" ? link.call : null }));
      row.appendChild(go);
    }
    root.appendChild(row);
  }
  function walkItem(parent) {
    const box = el("div", "walk-item");
    parent.appendChild(box);
    return box;
  }
  function failedInto(root, why) {
    if (why) root.appendChild(el("p", "fail", "failed: " + why));
  }
  // Each label a reading names, with the text its request shows under it, where it does.
  function labelsInto(parent, labels, known) {
    for (const label of labels) {
      const row = el("div", "walk-label");
      row.appendChild(el("span", "chip", label));
      if (known && known[label] !== undefined) row.appendChild(el("span", "t", known[label]));
      parent.appendChild(row);
    }
  }
  function walkRecall(root, s) {
    failedInto(root, s.failure);
    if (!s.returned) {
      root.appendChild(el("p", "note", "No returned entry was recorded: what it found is not "
        + "here."));
    }
    const found = s.found === null || s.found === undefined ? undefined
      : plural(s.found, "find", "finds") + (s.admitted === null ? ""
        : " · " + num(s.admitted) + " admitted");
    kv(root, [["outcome", s.outcome ? words(s.outcome) : undefined], ["found", found],
      ["kept", s.returned ? num(s.kept.length) : undefined]]);
    const cues = sec(root, "Cues");
    if (!s.cues.length) cues.appendChild(el("p", "note", "No cue recorded."));
    for (const cue of s.cues) {
      const one = walkItem(cues);
      one.appendChild(el("div", "said", cue.text === null ? DASH : cue.text));
      if (cue.kinds.length) one.appendChild(el("div", "m", cue.kinds.map(words).join(", ")));
    }
    const kept = sec(root, "Kept");
    if (!s.kept.length) {
      kept.appendChild(el("p", "note", s.returned ? "Nothing was kept." : "Not recorded."));
    }
    for (const k of s.kept) {
      const one = walkItem(kept);
      const facts = [k.score === null ? "no score" : "score " + k.score.toFixed(3)];
      if (k.bands.length) facts.push(k.bands.map(words).join(", "));
      if (k.found_by.length) facts.push("by " + k.found_by.map(words).join(", "));
      const line = el("div", "walk-label");
      if (k.label) line.appendChild(el("span", "chip", k.label));
      line.appendChild(el("span", "id", k.id === null ? "no id" : k.id));
      one.appendChild(line);
      one.appendChild(el("div", "m", facts.join(" · ")));
      if (k.text !== null) one.appendChild(el("div", "said", k.text));
    }
    const shown = s.shown;
    const whose = shown ? (shown.from === "understanding" ? "Understanding" : "Planning")
      + "\u2019s request (line " + shown.line + ")" : null;
    if (shown && shown.joined) {
      kept.appendChild(el("p", "note", "Each kept item\u2019s text is from " + whose
        + ", which showed every one of them, in recall\u2019s order, under the label beside it."));
    } else if (shown && shown.said !== null) {
      kept.appendChild(el("p", "note", whose + " said of what was recalled: " + shown.said));
    } else if (shown) {
      const box = sec(root, "What " + whose + " showed as recalled");
      box.appendChild(el("p", "note", shown.from === "planning"
        ? "It shows what both runs kept together, by label and never by id, so its items are "
          + "not joined to the ids above."
        : "It shows " + plural(shown.items.length, "item", "items") + " for "
          + plural(s.kept.length, "kept id", "kept ids") + ", by label and never by id, so "
          + "which item is which id is not known here."));
      if (!shown.items.length) box.appendChild(el("p", "note", "No item."));
      for (const one of shown.items) {
        const row = walkItem(box);
        labelsInto(row, [one.label || "no label"], null);
        row.appendChild(el("div", "said", one.text));
      }
    } else if (s.kept.length) {
      kept.appendChild(el("p", "note", "No request after it in the record shows the text of "
        + "what was kept."));
    }
    if (s.found !== null && s.found !== undefined && s.found > s.kept.length) {
      root.appendChild(el("p", "note", "The record does not say why a find was not kept."));
    }
  }
  function walkUnderstanding(root, s) {
    failedInto(root, s.failure);
    if (s.calls > 1) {
      root.appendChild(el("p", "note", s.calls + " calls: the reading shown is the last "
        + "reply\u2019s; each call is a click below."));
    }
    const r = s.reading;
    if (!r) {
      if (s.reply !== null && s.reply !== undefined) {
        root.appendChild(el("p", "note", "The reply did not read as one JSON object; it is "
          + "shown as written."));
        pre(root, s.reply);
      } else if (!s.failure) {
        root.appendChild(el("p", "note", s.returned ? "The returned entry holds no reply."
          : "No returned entry was recorded: what it read is not here."));
      }
      return;
    }
    const known = s.labels || {};
    const listed = (title, rows, draw) => {
      const box = sec(root, title);
      if (!rows.length) box.appendChild(el("p", "note", "none"));
      for (const row of rows) draw(walkItem(box), row);
    };
    if (r.shape === "reply") {
      // ADR-0353 §9:1: the reply's six keys, as it was written.
      const understood = sec(root, "Understanding");
      understood.appendChild(el("div", "said",
        r.understanding === null ? DASH : r.understanding));
      kv(understood, [["relayed", r.relayed === null ? null : (r.relayed ? "yes" : "no")]]);
      if (r.cites.length) {
        understood.appendChild(el("div", "m", "cites"));
        labelsInto(understood, r.cites, known);
      }
      listed("Unclear", r.unclear, (box, one) => {
        box.appendChild(el("div", "said", one.gap || DASH));
        for (const reading of one.readings) box.appendChild(el("div", "m", "reading: " + reading));
      });
      listed("Belongs to", r.belongs_to, (box, one) => labelsInto(box, [one], known));
      listed("Meant for", r.meant_for, (box, one) => labelsInto(box, [one], known));
      if (r.other.length) {
        root.appendChild(el("p", "note", "Keys the reply does not name: " + r.other.join(", ")));
      }
      return;
    }
    root.appendChild(el("p", "note", "Written in the reply\u2019s earlier shape, before "
      + "ADR-0353; shown as it was written."));
    const meaning = sec(root, "Meaning");
    meaning.appendChild(el("div", "said", r.meaning === null ? DASH : r.meaning));
    kv(meaning, [["ground", r.ground ? words(r.ground) : null]]);
    if (r.meaning_labels.length) {
      meaning.appendChild(el("div", "m", "rests on"));
      labelsInto(meaning, r.meaning_labels, known);
    }
    listed("References", r.references, (box, one) => {
      box.appendChild(el("div", "said", "“" + (one.phrase || DASH) + "”"));
      labelsInto(box, one.labels, known);
    });
    listed("Relationships", r.relationships, (box, one) => {
      box.appendChild(el("div", "said", one.statement || DASH));
      if (one.ground) box.appendChild(el("div", "m", "ground: " + words(one.ground)));
      labelsInto(box, one.labels, known);
    });
    listed("Unresolved", r.unresolved, (box, one) => {
      box.appendChild(el("div", "said", one.matter || DASH));
      if (one.why) box.appendChild(el("div", "m", "why it matters: " + one.why));
    });
    listed("Answers", r.answers, (box, one) => {
      labelsInto(box, [one.question || "no question named"], known);
      box.appendChild(el("div", "m", one.parts.length ? "parts " + one.parts.join(", ")
        : "no parts named"));
    });
    listed("Story links", r.story_labels, (box, one) => labelsInto(box, [one], known));
    listed("Continues", r.continues, (box, one) => labelsInto(box, [one], known));
    if (r.other.length) {
      root.appendChild(el("p", "note", "Keys the reading does not name: "
        + r.other.join(", ")));
    }
  }
  function walkPlanning(root, s) {
    failedInto(root, s.failure);
    const before = sec(root, s.before && s.before.round
      ? "What came back from round " + s.before.round : "What came back from the round before");
    if (s.before) {
      if (s.before.text !== null) {
        before.appendChild(el("div", "m", "its message"
          + (s.before.text_was ? " · " + s.before.text_was : "")));
        before.appendChild(el("div", "said", s.before.text));
      }
      if (!s.before.calls.length) before.appendChild(el("p", "note", "It proposed no call."));
      for (const call of s.before.calls) {
        const one = walkItem(before);
        one.appendChild(el("div", "said", (call.capability || "?") + " · "
          + (call.outcome || "no outcome shown")));
        if (call.because) one.appendChild(el("div", "m", "because: " + call.because));
        if (call.result) {
          one.appendChild(el("div", "m", "result" + (call.result.label ? " "
            + call.result.label : "")));
          pre(one, call.result.text);
        }
      }
    } else {
      before.appendChild(el("p", "note", s.first ? "The first round: none came before it."
        : s.request ? "Its request shows no earlier round."
          : "No request was recorded that shows what came before it."));
    }
    if (s.evidence.length) {
      const box = sec(root, "Evidence it was given");
      for (const one of s.evidence) {
        const row = walkItem(box);
        row.appendChild(el("div", "m", "digest of " + (one.of || "?")
          + (one.looking_for ? " · looking for: " + one.looking_for : "")));
        pre(row, one.digest);
      }
    }
    if (!s.returned) {
      root.appendChild(el("p", "note", "No returned entry was recorded: what it decided is "
        + "not here."));
      return;
    }
    const calls = sec(root, "Calls it proposed");
    if (!s.calls.length) calls.appendChild(el("p", "note", "none"));
    for (const call of s.calls) {
      const one = walkItem(calls);
      one.appendChild(el("div", "said", call.name + (call.id ? " · " + call.id : "")));
      pre(one, call.arguments);
    }
    const message = sec(root, "Its message");
    message.appendChild(s.message ? el("div", "said", s.message)
      : el("p", "note", "No message text."));
    if (s.notes !== null) sec(root, "Episode notes").appendChild(el("div", "said", s.notes));
    if (s.asks !== null) {
      const chips = el("div", "chips");
      for (const one of s.asks) chips.appendChild(el("span", "chip", one));
      if (!s.asks.length) chips.appendChild(el("span", "note", "none"));
      sec(root, "Asks").appendChild(chips);
    }
    const flags = [];
    if (s.another_round) flags.push("it asked for another round");
    if (s.thinking) flags.push("thinking recorded: the readable call shows it");
    if (s.read_as_round === false) flags.push("not read as a round");
    if (flags.length) root.appendChild(el("p", "note", flags.join(" · ")));
  }
  function walkAuthorizing(root, s) {
    failedInto(root, s.failure);
    if (!s.returned) {
      root.appendChild(el("p", "note", "No returned entry was recorded: its verdicts are not "
        + "here."));
      return;
    }
    if (s.outside) root.appendChild(badge("outside_content", "outside content read"));
    const calls = sec(root, "Each call\u2019s verdict");
    if (!s.verdicts.length) calls.appendChild(el("p", "note", "No call to check."));
    for (const v of s.verdicts) {
      const one = walkItem(calls);
      one.appendChild(el("span", "chip v-" + (v.verdict || "none"), (v.name || "call")
        + " · " + (v.verdict ? words(v.verdict) : "no verdict")));
      if (v.reason) one.appendChild(el("div", "m", v.reason));
    }
    const message = sec(root, "Its message");
    const m = s.message;
    if (!m) {
      message.appendChild(el("p", "note", "No message to check."));
    } else if (m.allowed) {
      message.appendChild(el("div", "msg-note", "allowed" + (m.place ? " into " + m.place : "")
        + " — whether it was written is not recorded"));
    } else {
      message.appendChild(el("div", "msg-note no", (m.allowed === false ? "not allowed"
        : "no verdict recorded") + (m.reason ? ": " + m.reason : "")));
    }
  }
  function walkActing(root) {
    root.appendChild(el("p", "note", "Acting writes no entry of its own: which calls ran and "
      + "whether the message was written are not recorded here."));
  }
  function walkDigesting(root, s) {
    if (!s.parts.length) root.appendChild(el("p", "note", "No digest entry recorded."));
    for (const p of s.parts) {
      const one = walkItem(root);
      kv(one, [["question", p.question || undefined], ["result", p.result || undefined],
        ["part", p.part || undefined]]);
      if (!p.returned) one.appendChild(el("p", "note", "No returned entry was recorded."));
      else if (p.failed) failedInto(one, p.why || "no reason recorded");
      if (p.evidence !== null) pre(one, p.evidence);
    }
  }
  function walkEnd(root, s) {
    const box = walkItem(root);
    if (s.recorded) {
      box.appendChild(el("div", "said", "Ended: " + (ending(s.rule) || "no rule recorded")));
    } else {
      const open = state.detail && isOpen(state.detail.summary);
      box.appendChild(el("p", "note", open ? "Still running: no end is recorded yet."
        : "No end recorded."));
    }
    if (s.truncated) {
      box.appendChild(el("p", "note", "The file was truncated at " + clock(s.truncated.at)
        + ": nothing after it was written."));
    }
    if (s.unreadable) {
      box.appendChild(el("p", "note", s.unreadable + " unreadable line(s) were skipped."));
    }
  }
  function walkLearning(root, s, owner) {
    const head = walkItem(root);
    head.appendChild(el("span", "badge b-" + ((s.ended && s.ended.state) || "no_end"),
      attemptEnding(s.ended)));
    if (s.ended && s.ended.failure) head.appendChild(el("div", "fail", s.ended.failure));
    const box = sec(root, "Findings");
    if (!s.findings.length) box.appendChild(el("p", "note", "No finding recorded."));
    for (const f of s.findings) box.appendChild(findingRow(owner, f, {}));
  }
  function walkInput(root, s) {
    if (s.arrival) {
      arrivalInto(root, s.arrival);
      return;
    }
    root.appendChild(el("p", "note", "No request in the record shows the input: the record "
      + "keeps no entry of its own for it, and reads it back from what understanding or "
      + "planning was given."));
  }
  function walkOther(root, s) {
    const st = s.step;
    kv(root, [["stage", words(s.phase)], ["due", st && st.due ? words(st.due) : undefined],
      ["outcome", st && st.outcome ? words(st.outcome) : undefined]]);
  }
  const WALKERS = {
    input: walkInput, recall: walkRecall, understanding: walkUnderstanding,
    planning: walkPlanning, authorizing: walkAuthorizing, acting: walkActing,
    digesting: walkDigesting, end: walkEnd, learning: walkLearning,
  };

  // --- details on click --------------------------------------------------------------
  let drawn = 0;
  // ``opts.file`` is "observer" for the observer file beside the activation's own
  // (ADR-0333 \u00a75:1), and ``opts.call`` the line of the model call the lines are, where
  // the caller knows it; else it is looked for among the activation's own entries.
  async function openLines(id, title, lines, opts) {
    const file = opts && opts.file ? opts.file : null;
    const suffix = file ? "&file=" + encodeURIComponent(file) : "";
    // Each opening is one generation: a load still in flight from an earlier click,
    // on this activation or another, finds its generation gone and draws nothing.
    const generation = ++drawn;
    $("drawer-title").textContent = title;
    const body = $("drawer-body");
    clear(body);
    clear($("drawer-read"));
    // A model call opens readable, its entries whole one tab away (ADR-0316 \u00a73:3).
    let call = opts && opts.call !== undefined ? opts.call : null;
    if (!file && !(opts && opts.call !== undefined)) call = callLine(id, lines);
    if (call === undefined) call = null;
    $("drawer-tabs").hidden = call === null;
    $("drawer").classList.toggle("wide", call !== null);
    showTab(call === null ? "raw" : "read");
    $("drawer").hidden = false;
    if (call !== null) loadCall(generation, id, call, suffix);
    for (const line of lines) {
      const holder = el("div");
      body.appendChild(holder);
      try {
        const url = "/api/entry?id=" + encodeURIComponent(id)
          + "&line=" + encodeURIComponent(line) + suffix;
        const entry = await getJson(url);
        if (generation !== drawn) return;
        if (entry === null) {
          holder.appendChild(el("p", "note", "That entry is no longer in the record."));
        } else {
          renderEntry(holder, entry);
        }
      } catch (error) {
        if (generation !== drawn) return;
        holder.appendChild(el("p", "note", "Could not load that entry."));
      }
    }
  }
  function closeDrawer() {
    drawn += 1;
    $("drawer").hidden = true;
  }

  function showTab(tab) {
    $("drawer-read").hidden = tab !== "read";
    $("drawer-body").hidden = tab !== "raw";
    $("tab-read").setAttribute("aria-pressed", String(tab === "read"));
    $("tab-raw").setAttribute("aria-pressed", String(tab === "raw"));
  }

  // --- a model call, readable --------------------------------------------------------
  const MODEL_SOURCES = ["understanding", "planning", "digesting"];
  const SOURCE_NAMES = { understanding: "Understanding", planning: "Planning",
    digesting: "Digesting", observer: "Observer" };
  // The first of the lines a click opens that is a model call's given or returned entry.
  function callLine(id, lines) {
    const d = state.detail;
    if (!d || d.id !== id) return null;
    for (const line of lines) {
      const e = d.entries.find((one) => one.line === line);
      if (e && MODEL_SOURCES.includes(e.source) && (e.kind === "given" || e.kind === "returned")) {
        return line;
      }
    }
    return null;
  }
  async function loadCall(generation, id, line, suffix) {
    const holder = $("drawer-read");
    holder.appendChild(el("p", "note", "Loading\u2026"));
    let view;
    try {
      view = await getJson("/api/call?id=" + encodeURIComponent(id)
        + "&line=" + encodeURIComponent(line) + (suffix || ""));
    } catch (error) {
      if (generation !== drawn) return;
      clear(holder);
      holder.appendChild(el("p", "note", "Could not load that call."));
      return;
    }
    if (generation !== drawn) return;
    clear(holder);
    if (view === null) {
      holder.appendChild(el("p", "note", "That call is no longer in the record."));
      return;
    }
    try {
      renderCall(holder, view);
    } catch (error) {
      holder.appendChild(el("p", "note",
        "This call did not read as expected; the raw entries show it whole."));
    }
  }
  function num(n) { return typeof n === "number" ? n.toLocaleString("en-US") : String(n); }
  function size(chars, tokens) {
    let text = num(chars) + " chars";
    if (tokens !== undefined && tokens !== null) {
      text += " \u00b7 \u2248" + num(tokens) + " tokens (est.)";
    }
    return text;
  }
  async function copyText(text, button) {
    let done = false;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        done = true;
      }
    } catch (error) {
      done = false;
    }
    if (!done) {
      const area = el("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        done = document.execCommand("copy");
      } catch (error) {
        done = false;
      }
      document.body.removeChild(area);
    }
    button.textContent = done ? "Copied" : "Copy failed";
    setTimeout(() => { button.textContent = "Copy"; }, 1500);
  }
  // A copy control: copies plain text, built when it is clicked.
  function copyButton(what, text) {
    const button = el("button", "copy", "Copy");
    button.type = "button";
    button.title = "Copy " + what + " as plain text";
    button.setAttribute("aria-label", "Copy " + what);
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      copyText(typeof text === "function" ? text() : text, button);
    });
    return button;
  }
  function callSec(holder, key, title, meta, copied) {
    const box = el("section", "call-sec");
    box.id = "call-" + key;
    const head = el("div", "sec-head");
    head.appendChild(el("h3", null, title));
    if (meta) head.appendChild(el("span", "m", meta));
    if (copied) head.appendChild(copyButton(title.toLowerCase(), copied));
    box.appendChild(head);
    holder.appendChild(box);
    return box;
  }
  // One part: a head naming it, its size and a copy control, and its text wrapped or laid
  // out; collapsed where it is long data rather than prose.
  function part(parent, opts) {
    const box = el(opts.collapsed === undefined ? "div" : "details", "part");
    if (opts.collapsed === false) box.open = true;
    const head = el(opts.collapsed === undefined ? "div" : "summary", "part-head");
    if (opts.name) head.appendChild(el("span", "name", opts.name));
    for (const tag of opts.tags || []) {
      head.appendChild(el("span", "tag " + (tag.cls || ""), tag.text));
    }
    if (opts.meta) head.appendChild(el("span", null, opts.meta));
    const end = el("span", "end");
    end.appendChild(el("span", "size", opts.size || ""));
    end.appendChild(copyButton(opts.what || opts.name || "this part", opts.copy));
    head.appendChild(end);
    box.appendChild(head);
    parent.appendChild(box);
    return box;
  }
  function prose(parent, text, cls) {
    parent.appendChild(el("div", "part-text" + (cls ? " " + cls : ""), text));
  }
  function plural(n, one, many) { return num(n) + " " + (n === 1 ? one : many); }

  function renderCall(holder, v) {
    const head = el("div", "call-head");
    let title = SOURCE_NAMES[v.source] || v.source;
    if (v.round) title += " \u00b7 round " + v.round;
    if (v.about && v.about.part) title += " \u00b7 part " + v.about.part;
    if (v.source === "observer" && v.about && v.about.stage) {
      title += " \u00b7 " + v.about.stage + (v.about.finding ? " " + v.about.finding : "");
    }
    head.appendChild(el("h2", null, title));
    const where = [];
    where.push(v.given === null ? "no given entry" : "given line " + v.given);
    where.push(v.returned === null ? "no returned entry" : "returned line " + v.returned);
    if (v.took !== null && v.took !== undefined) where.push("took " + duration(v.took));
    head.appendChild(el("div", "m", where.join(" \u00b7 ")));
    if (v.prompt) {
      const p = v.prompt;
      const origin = p.origin ? " (" + p.origin + ")" : "";
      const said = ["prompt " + (p.name || "") + " " + p.version + origin];
      if (p.flags_on && p.flags_on.length) said.push("flags on: " + p.flags_on.join(", "));
      head.appendChild(el("div", "m", said.join(" \u00b7 ")));
    }
    holder.appendChild(head);
    if (v.about && (v.about.question || v.about.result)) {
      kv(holder, [["question", v.about.question], ["result", v.about.result]]);
    }
    if (v.source === "observer" && v.about) {
      kv(holder, [["claim", v.about.claim || undefined], ["episode", v.about.episode],
        ["attempt started", v.about.attempt]]);
    }
    for (const note of v.notes || []) holder.appendChild(el("p", "note", note));
    const stats = el("div", "call-stats");
    const stat = (text) => stats.appendChild(el("span", "chip", text));
    if (v.told) stat("told " + size(v.told.chars, v.told.tokens));
    const input = v.input || [];
    if (input.length) {
      const chars = input.reduce((n, m) => n + (m.chars || 0), 0);
      stat("given " + size(chars, input.reduce((n, m) => n + (m.tokens || 0), 0)));
    }
    if (v.tools) stat(plural(v.tools.tools.length, "tool", "tools"));
    const usage = v.did && v.did.usage;
    if (usage) {
      stat(Object.entries(usage).map(([k, n]) => k + " " + num(n)).join(" \u00b7 ") + " tokens");
    }
    holder.appendChild(stats);
    const nav = el("nav", "call-nav");
    const keys = [["told", "Told"], ["given", "Given"], ["tools", "Could do"], ["did", "Did"]];
    if (v.source === "planning") keys.push(["changes", "Changed"]);
    if (v.replays && v.replays.length) keys.push(["replays", "Replays"]);
    if (v.follow_ups && v.follow_ups.length) keys.push(["follow-ups", "Follow-up"]);
    for (const [key, label] of keys) {
      const go = el("button", null, label);
      go.type = "button";
      go.addEventListener("click", () => {
        const target = document.getElementById("call-" + key);
        if (target) target.scrollIntoView({ block: "start" });
      });
      nav.appendChild(go);
    }
    holder.appendChild(nav);
    renderTold(holder, v);
    renderGiven(holder, v);
    renderTools(holder, v);
    renderDid(holder, v);
    if (v.source === "planning") renderChanges(holder, v);
    if (v.replays && v.replays.length) renderReplays(holder, v);
    if (v.follow_ups && v.follow_ups.length) renderFollowUps(holder, v);
  }

  // Why a request's part is not shown, where the record does not hold it to read.
  function unread(v, what) {
    if (v.given === null) return "No given entry was recorded, so what it was " + what
      + " is not here.";
    if (v.input === null) return "The given entry holds no list of messages to read; "
      + "the raw entries show it whole.";
    return null;
  }
  function renderTold(holder, v) {
    const told = v.told;
    const all = () => told.sections.map((s) => (s.heading ? s.heading + "\n\n" : "")
      + s.parts.map((p) => p.text).join("\n\n")).join("\n\n");
    const box = callSec(holder, "told", "What it was told",
      told ? size(told.chars, told.tokens) + " \u00b7 the instructions" : null, told ? all : null);
    if (!told) {
      box.appendChild(el("p", "note", unread(v, "told")
        || "This request carries no system message."));
      return;
    }
    for (const s of told.sections) {
      if (s.heading) box.appendChild(el("h4", "part-heading", s.heading));
      for (const p of s.parts) {
        const one = part(box, { name: p.rest ? "the rest" : "\u00b6" + p.n,
          what: "paragraph " + p.n, size: size(p.chars, p.tokens), copy: p.text });
        prose(one, p.text);
      }
    }
  }

  function keyText(k) { return JSON.stringify(k.key) + ": " + k.text; }
  function messageText(m) {
    return m.form === "json" ? m.keys.map(keyText).join("\n\n") : m.text;
  }
  function renderGiven(holder, v) {
    const input = v.input || [];
    const box = callSec(holder, "given", "What it was given",
      input.length ? plural(input.length, "message", "messages") + " after the instructions" : null,
      input.length ? () => input.map(messageText).join("\n\n") : null);
    if (!input.length) {
      box.appendChild(el("p", "note", unread(v, "given")
        || "This request carries no message beside its instructions."));
      return;
    }
    for (const m of input) {
      let label = (m.role || "message") + " message " + m.index;
      label += m.form === "json"
        ? " \u00b7 one JSON object, " + plural(m.keys.length, "key", "keys")
        : " \u00b7 text";
      if (m.odd) label += " \u00b7 its content is not text";
      const sub = el("div", "part-heading", label + " \u00b7 " + size(m.chars, m.tokens));
      box.appendChild(sub);
      if (m.form !== "json") {
        const one = part(box, { name: "text", what: "message " + m.index,
          size: size(m.chars, m.tokens), copy: m.text });
        prose(one, m.text);
        continue;
      }
      for (const k of m.keys) {
        const one = part(box, { name: k.key, meta: k.kind, collapsed: true,
          what: "\u201c" + k.key + "\u201d", size: size(k.chars, k.tokens), copy: keyText(k) });
        const lists = (k.lists || []).filter((l) => l.path !== k.key || k.lists.length > 1);
        if (lists.length) {
          const counted = lists.map((l) => l.path + ": " + plural(l.items, "item", "items")
            + (l.lists > 1 ? " in " + num(l.lists) + " lists" : ""));
          one.appendChild(el("div", "lists", counted.join(" \u00b7 ")));
        }
        pre(one, k.text);
      }
    }
  }

  function toolText(t) {
    return t.name + "\n\n" + t.description + (t.schema ? "\n\n" + t.schema : "");
  }
  function renderTools(holder, v) {
    const tools = v.tools;
    const list = tools ? tools.tools : [];
    let meta = null;
    if (tools) {
      meta = plural(list.length, "tool", "tools") + (tools.from === "returned"
        ? " \u00b7 as offered to the provider"
        : " \u00b7 as the request built them; no returned entry says what the provider was sent");
    }
    const box = callSec(holder, "tools", "What it could do", meta,
      list.length ? () => list.map(toolText).join("\n\n---\n\n") : null);
    if (!tools) {
      box.appendChild(el("p", "note", v.source === "planning"
        ? "No list of tools is recorded for this call."
        : "This call offers no tools: it is a completion."));
      return;
    }
    if (tools.unnamed) {
      box.appendChild(el("p", "note", plural(tools.unnamed, "tool", "tools")
        + " with no name are left out here; the raw entries show them."));
    }
    for (const t of list) {
      const tags = t.reserved ? [{ text: "reserved: the round's own tool" }] : [];
      const one = part(box, { name: t.name, tags, what: "tool " + t.name,
        size: size(t.chars, t.tokens), copy: toolText(t) });
      prose(one, t.description || "(no description)");
      if (t.schema) {
        const schema = el("details", "part");
        const summary = el("summary", "part-head");
        summary.appendChild(el("span", null, "Schema"));
        summary.appendChild(el("span", "size", num(t.schema.length) + " chars"));
        schema.appendChild(summary);
        pre(schema, t.schema);
        schema.style.margin = "4px 8px 8px";
        one.appendChild(schema);
      }
    }
  }

  function didText(p) { return p.title + "\n\n" + p.text; }
  function renderDid(holder, v) {
    const did = v.did;
    const box = callSec(holder, "did", "What it did",
      did ? plural(did.parts.length, "part", "parts") + " in order" : null,
      did && did.parts.length ? () => did.parts.map(didText).join("\n\n") : null);
    if (!did) {
      box.appendChild(el("p", "note",
        "No returned entry was recorded, so what it did is not here."));
      return;
    }
    didInto(box, did);
  }
  // What a model did, part by part: an original call's, or a replay's (ADR-0335 \u00a76:4).
  function didInto(box, did) {
    if (did.failure) box.appendChild(el("p", "fail", "failed: " + did.failure));
    if (did.odd) box.appendChild(el("p", "note", did.odd));
    if (did.usage) {
      kv(box, Object.entries(did.usage).map(([k, n]) => [k + " tokens", num(n)]));
    } else if (did.usage_note) {
      box.appendChild(el("p", "note", did.usage_note));
    }
    const facts = [["model", did.model], ["finish reason", did.finish_reason],
      ["read as a round", did.read_as_round]].filter(([, x]) => x !== undefined && x !== null);
    if (facts.length) kv(box, facts);
    did.parts.forEach((p, index) => {
      const one = part(box, { name: (index + 1) + " \u00b7 " + p.title, what: p.title.toLowerCase(),
        meta: p.id ? "call id " + p.id : null, size: size(p.chars, p.tokens), copy: didText(p) });
      if (p.kind === "asks") {
        const asks = el("div", "asks");
        for (const name of p.items || []) asks.appendChild(el("span", "chip", name));
        if (!(p.items || []).length) asks.appendChild(el("span", "note", "none"));
        one.appendChild(asks);
      } else if (p.kind === "call" || p.kind === "other" || p.kind === "reply") {
        pre(one, p.text);
      } else {
        prose(one, p.text || "(no text returned)", p.kind === "thinking" ? "thinking" : null);
      }
    });
  }

  // Each replay of this call beside the original reply, headed by its prompt's name, version
  // and origin, the candidate's instruction one click away (ADR-0335 \u00a76:4).
  function renderReplays(holder, v) {
    const box = callSec(holder, "replays", "Replayed",
      plural(v.replays.length, "result", "results") + " of a replay over a copy of the record");
    // The samples of one call under one candidate in one run are shown together, under the
    // candidate's one heading (ADR-0337 \u00a75:4).
    const sets = [];
    const bySet = new Map();
    for (const r of v.replays) {
      let held = bySet.get(r.set);
      if (!held) { held = []; bySet.set(r.set, held); sets.push(held); }
      held.push(r);
    }
    for (const samples of sets) {
      const r = samples[0];
      const one = el("div", "replay");
      const head = el("div", "replay-head");
      const named = [r.prompt || "prompt not named", r.version || "no version",
        r.origin || "origin not named"];
      head.appendChild(el("h4", null, named.join(" \u00b7 ")));
      head.appendChild(el("span", "m", clock(r.at, true)));
      one.appendChild(head);
      const flags = r.flags && r.flags.length ? r.flags.join(", ") : "none";
      kv(one, [["run", r.run], ["model", r.model],
        ["original model", r.original_model || "unknown"],
        ["recorded prompt", r.recorded_version
          ? r.recorded_version + " \u00b7 " + (r.recorded_origin || "origin not named")
          : "not recorded"],
        ["flags", r.flags_from ? flags + " (" + r.flags_from + ")" : flags],
        ["candidate file", r.file || undefined]]);
      if (r.flags_from === "stated") {
        one.appendChild(el("p", "note",
          "Rendered under flags the run stated: the entry records none."));
      }
      if (r.instruction) {
        const told = part(one, { name: "Candidate\u2019s instruction", collapsed: true,
          size: size(r.instruction.chars, r.instruction.tokens), copy: r.instruction.text,
          what: "the candidate\u2019s instruction" });
        prose(told, r.instruction.text);
      }
      if (r.sample === null || r.sample === undefined) {
        if (r.did) didInto(one, r.did);
        if (r.follow_up) followUpInto(one, r.follow_up);
      } else {
        for (const s of samples) {
          const sampled = el("div", "replay-sample");
          const named = el("div", "replay-head");
          named.appendChild(el("h5", null, "sample " + s.sample + " of " + s.samples));
          named.appendChild(el("span", "m", clock(s.at, true)));
          sampled.appendChild(named);
          if (s.did) didInto(sampled, s.did);
          if (s.follow_up) followUpInto(sampled, s.follow_up);
          one.appendChild(sampled);
        }
      }
      box.appendChild(one);
    }
  }

  // The follow-up asked after a replayed response: its answer as text, or its failure,
  // with its version, and its question one click away (ADR-0337 \u00a76:5).
  function followUpInto(parent, f, rows) {
    const box = el("div", "follow-up");
    const head = el("div", "replay-head");
    head.appendChild(el("h5", null, "follow-up \u00b7 " + (f.version || "no version")
      + " \u00b7 " + (f.origin || "origin not named")));
    box.appendChild(head);
    if (rows) kv(box, rows);
    if (f.failure) box.appendChild(el("p", "fail", "failed: " + f.failure));
    if (f.answer) {
      const said = part(box, { name: "Answer", what: "the follow-up\u2019s answer",
        size: size(f.answer.chars, f.answer.tokens), copy: f.answer.text });
      prose(said, f.answer.text || "(no text returned)");
    }
    if (f.question) {
      const asked = part(box, { name: "Question", collapsed: true,
        what: "the follow-up\u2019s question",
        size: size(f.question.chars, f.question.tokens), copy: f.question.text });
      prose(asked, f.question.text);
    }
    parent.appendChild(box);
  }

  // What the owner's hub asked this call after it answered: each answer as text, or its
  // failure, with the follow-up prompt's version and the model it went to, in a section of
  // its own beside the call and never on the timeline (ADR-0337 \u00a78:17).
  function renderFollowUps(holder, v) {
    const box = callSec(holder, "follow-ups", "Asked afterwards",
      plural(v.follow_ups.length, "follow-up", "follow-ups")
        + " the hub asked this call after it answered");
    for (const f of v.follow_ups) {
      followUpInto(box, f, [["asked", clock(f.at, true)], ["model", f.model || "not named"],
        ["followed prompt", f.followed_version || "no version"]]);
    }
  }

  function diffText(d) { return d.lines.join("\n"); }
  function renderChanges(holder, v) {
    const changes = v.changes;
    const moved = changes ? changes.parts.filter((p) => p.change !== "unchanged") : [];
    let meta = null;
    if (changes) {
      const count = (what) => changes.parts.filter((p) => p.change === what).length;
      const against = changes.against_round
        ? "round " + changes.against_round : "line " + changes.against;
      meta = "since " + against + "\u2019s request \u00b7 "
        + ["changed", "added", "removed", "unchanged"]
          .map((what) => count(what) + " " + what).join(", ");
    }
    const box = callSec(holder, "changes", "Round to round", meta,
      moved.length ? () => moved.map((p) => p.part + " (" + p.change + ")"
        + (p.diff ? "\n" + diffText(p.diff) : "")).join("\n\n") : null);
    if (!changes) {
      box.appendChild(el("p", "note", v.given === null
        ? "No given entry was recorded, so there is no request to compare."
        : "This is the activation's first planning request: there is none before it to compare."));
      return;
    }
    if (!moved.length) box.appendChild(el("p", "note", "Nothing in the request changed."));
    for (const p of moved) {
      const sizes = p.change === "changed" ? num(p.before) + " \u2192 " + num(p.after) + " chars"
        : num(p.change === "removed" ? p.before : p.after) + " chars";
      const one = part(box, { name: p.part, tags: [{ text: p.change, cls: "ch-" + p.change }],
        what: p.part + "\u2019s change", size: sizes,
        copy: p.diff ? diffText(p.diff) : p.part + " (" + p.change + ")" });
      if (!p.diff) {
        prose(one, p.change === "added" ? "New in this request; it is shown in full above."
          : "In the request before, and not in this one.");
        continue;
      }
      if (p.diff.too_large) {
        prose(one, "Too large to compare here; both requests show it whole.");
        continue;
      }
      if (!p.diff.lines.length) {
        prose(one, "Its lines are the same: only its line endings changed.");
        continue;
      }
      const shown = el("pre", "diff");
      for (const line of p.diff.lines) {
        const cls = line.startsWith("+") ? "add" : line.startsWith("-") ? "del"
          : line.startsWith("@@") ? "hunk" : null;
        shown.appendChild(el("span", cls, line || " "));
      }
      one.appendChild(shown);
      if (p.diff.cut) prose(one, "The diff is cut here; both requests show the part whole.");
    }
    const same = changes.parts.filter((p) => p.change === "unchanged");
    if (same.length) {
      box.appendChild(el("p", "note", "Unchanged: " + same.map((p) => p.part).join(", ")));
    }
  }

  function sec(parent, title) {
    const box = el("div", "sec");
    box.appendChild(el("h3", null, title));
    parent.appendChild(box);
    return box;
  }
  function kv(parent, rows) {
    const dl = el("dl", "kv");
    for (const [k, v] of rows) {
      if (v === undefined) continue;
      dl.appendChild(el("dt", null, k));
      const shown = v === null ? DASH : (typeof v === "object" ? JSON.stringify(v) : v);
      dl.appendChild(el("dd", null, shown));
    }
    parent.appendChild(dl);
  }
  function pretty(text) {
    if (typeof text !== "string") return JSON.stringify(text, null, 2);
    const trimmed = text.trim();
    if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
      try {
        return JSON.stringify(JSON.parse(trimmed), null, 2);
      } catch (error) {
        return text;
      }
    }
    return text;
  }
  function pre(parent, text, cls) { parent.appendChild(el("pre", cls || null, text)); }
  function obj(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }
  function arr(value) { return Array.isArray(value) ? value : []; }
  function failure(value) {
    if (value === undefined) return undefined;
    if (typeof value === "string") return value;
    const f = obj(value);
    return [f.class, f.message].filter(Boolean).join(": ") || JSON.stringify(value);
  }

  function renderEntry(holder, entry) {
    const title = entry.source ? entry.source + " · " + entry.kind : "line " + entry.line;
    const head = sec(holder, title);
    if (entry.unreadable) {
      head.appendChild(el("p", "note", "This line is not an entry the viewer can read."));
      return;
    }
    if (entry.truncated_at !== undefined) {
      head.appendChild(el("p", "note", "The file was truncated here, at " + entry.truncated_at
        + ". The store writes nothing after this line."));
      return;
    }
    kv(head, [["recorded", entry.recorded_at]]);
    const view = VIEWS[entry.source + "." + entry.kind];
    if (view && entry.body && typeof entry.body === "object") {
      try {
        view(holder, obj(entry.body));
      } catch (error) {
        holder.appendChild(el("p", "note",
          "This body did not read as expected; it is shown whole below."));
      }
    }
    pre(sec(holder, "Whole body"), JSON.stringify(entry.body, null, 2));
  }
  function messages(holder, b) {
    const list = arr(b.messages);
    if (!list.length) return;
    const box = sec(holder, "Messages");
    for (const m of list) {
      const one = obj(m);
      box.appendChild(el("h4", null, one.role || "message"));
      pre(box, pretty(one.content));
    }
  }
  function step(holder, b) {
    const start = Date.parse(b.started_at);
    const end = Date.parse(b.ended_at);
    kv(sec(holder, "Step"), [
      ["stage", b.stage], ["due to", b.due], ["outcome", b.outcome],
      ["took", isNaN(start) || isNaN(end) ? undefined : duration(end - start)],
      ["started", b.started_at], ["ended", b.ended_at],
      ["failure", failure(b.failure)],
    ]);
  }
  function recallFound(holder, b) {
    const box = sec(holder, "Found");
    kv(box, [
      ["outcome", b.outcome], ["finds", arr(b.finds).length], ["kept", arr(b.kept).length],
      ["failure", failure(b.failure)],
    ]);
    for (const k of arr(b.kept)) {
      const one = obj(k);
      pre(box, one.id + "  score " + one.score + "  by " + arr(one.found_by).join(", "));
    }
  }
  function planningResponse(holder, b) {
    const box = sec(holder, "Response");
    kv(box, [["read as a round", b.read_as_round], ["failure", failure(b.failure)]]);
    for (const p of arr(obj(b.response).parts)) {
      const part = obj(p);
      if (part.part_kind === "thinking") {
        box.appendChild(el("h4", null, "Thinking (the provider's summary)"));
        pre(box, part.content || "(no text returned)", "thinking");
      } else if (part.part_kind === "text") {
        box.appendChild(el("h4", null, "Text"));
        pre(box, part.content);
      } else if (part.part_kind === "tool-call") {
        box.appendChild(el("h4", null, "Call · " + part.tool_name));
        pre(box, pretty(part.args));
      }
    }
    offeredTools(holder, b);
  }
  // The tools the request offered the provider, in its order, the reserved one last
  // (#2894): their names, and the reserved tool's description. The schemas stay in the
  // whole body. A returned entry written before the list was kept has none, and shows
  // no section.
  function offeredTools(holder, b) {
    const tools = arr(b.offered_tools).map(obj);
    const names = tools.map((t) => t.name).filter((name) => typeof name === "string" && name);
    if (!names.length) return;
    const box = sec(holder, "Offered to the provider");
    kv(box, [["tools", names.join(", ")]]);
    for (const tool of tools) {
      if (tool.name !== ROUND_TOOL || typeof tool.description !== "string") continue;
      box.appendChild(el("h4", null, ROUND_TOOL + " · reserved: the round's own tool"));
      pre(box, tool.description);
    }
  }
  function verdicts(holder, b) {
    const box = sec(holder, "Verdicts");
    kv(box, [
      ["round", b.round], ["read outside content", b.read_outside_content],
      ["failure", failure(b.failure)],
    ]);
    for (const c of arr(b.calls)) {
      const call = obj(c);
      const heading = (call.name || "call") + " · " + words(call.verdict || "no verdict");
      box.appendChild(el("h4", null, heading));
      if (call.reason) box.appendChild(el("p", "note", call.reason));
      for (const k of arr(call.checks)) {
        const check = obj(k);
        pre(box, check.check + ": " + check.verdict + (check.reason ? " — " + check.reason : ""));
      }
    }
    if (b.message) {
      const m = obj(b.message);
      const mb = sec(holder, "Message");
      kv(mb, [["place", m.place], ["allowed", m.allowed], ["reason", m.reason || undefined]]);
      if (m.allowed) {
        mb.appendChild(el("p", "note", "Allowed by authorizing. Acting writes no entry, "
          + "so whether it was written is not recorded here."));
      }
    }
    const grounds = arr(b.grounds);
    if (grounds.length) {
      const gb = sec(holder, "Grounds for outside content");
      for (const g of grounds) {
        const one = obj(g);
        pre(gb, one.ground + (one.record ? "  ← " + one.record : ""));
      }
    }
  }
  function digestGiven(holder, b) {
    const part = b.part !== undefined ? b.part + " of " + b.parts : undefined;
    kv(sec(holder, "Digest"), [["question", b.question], ["result", b.result], ["part", part]]);
    messages(holder, b);
  }
  function digestReturned(holder, b) {
    const box = sec(holder, "Digest");
    kv(box, [
      ["question", b.question], ["result", b.result], ["digest", b.digest],
      ["reason", b.reason], ["failure", failure(b.failure)],
    ]);
    if (typeof b.reply === "string") {
      box.appendChild(el("h4", null, "Reply (evidence)"));
      pre(box, pretty(b.reply));
    }
    const dropped = arr(b.dropped);
    if (dropped.length) {
      box.appendChild(el("h4", null, "Dropped"));
      pre(box, JSON.stringify(dropped, null, 2));
    }
  }
  function supportsView(box, list) {
    for (const s of arr(list)) {
      const one = obj(s);
      const part = obj(one.part);
      const where = [part.part, part.episode, part.message, part.round, part.item]
        .filter((x) => x !== undefined && x !== null).join(" \u00b7 ");
      pre(box, where + "\n" + [one.direction, one.backs_as_worded ? "backs as worded" : null,
        one.how_sure, one.origin].filter(Boolean).join(" \u00b7 ")
        + (one.note ? "\nnote: " + one.note : ""));
    }
  }
  function observerStep(holder, b) {
    if (b.stage === "findings") {
      const box = sec(holder, "Findings");
      kv(box, [["episode", b.episode], ["attempt started", b.attempt_started_at],
        ["dropped", b.dropped]]);
      for (const f of arr(b.findings)) {
        const one = obj(f);
        box.appendChild(el("h4", null, (one.id || "finding") + " \u00b7 " + (one.claim || "")));
        const about = obj(one.annotations);
        kv(box, [["candidate", one.candidate || undefined],
          ["relied on", one.relied_on || undefined],
          ["rests on", arr(one.rests_on).length + " part(s)"],
          ["subjects", arr(about.subjects).join(", ") || undefined],
          ["involved", arr(about.involved).join(", ") || undefined],
          ["why", about.why || undefined],
          ["situations", arr(about.situations).join("; ") || undefined],
          ["narrowing", about.narrowing ? obj(about.narrowing).reach + ": "
            + obj(about.narrowing).note : undefined]]);
      }
      for (const d of arr(b.declines)) {
        const one = obj(d);
        kv(box, [["declined", one.candidate + " \u00b7 " + one.reason]]);
      }
      return;
    }
    if (b.stage === "outcome") {
      const box = sec(holder, "Outcome");
      const o = obj(b.outcome);
      kv(box, [["finding", b.finding], ["claim", b.claim], ["ruling", o.ruling],
        ["unwritten", o.unwritten || undefined],
        ["writes", arr(o.writes).map((w) => obj(w).memory + " (" + arr(obj(w).operations)
          .join(", ") + ")").join("; ") || undefined],
        ["asked", arr(o.asked).join("; ") || undefined]]);
      for (const u of arr(o.unclear)) {
        const one = obj(u);
        kv(box, [["unclear", one.memory + " \u00b7 " + one.wording + " \u00b7 " + one.note]]);
      }
      const d = obj(b.decided);
      if (b.decided && d.framed !== undefined) {
        const fb = sec(holder, "What framing decided");
        kv(fb, [["nothing kept, because", d.nothing || undefined],
          ["failed a check", d.failed || undefined]]);
        for (const n of arr(d.framed)) {
          const one = obj(n);
          fb.appendChild(el("h4", null, (one.refused ? "refused: " : "") + (one.wording || "")));
          if (one.refused) kv(fb, [["why", one.refused]]);
          const held = obj(one.framed);
          if (one.framed) {
            kv(fb, [["subjects", arr(held.subjects).join(", ") || undefined],
              ["involved", arr(held.involved).join(", ") || undefined],
              ["labels", arr(held.labels).join("; ") || undefined],
              ["marks", arr(held.marks).join(", ") || undefined],
              ["valid until", held.valid_until || undefined]]);
            supportsView(fb, held.supports);
          }
        }
        const pb = sec(holder, "What placement decided");
        for (const p of arr(d.placed)) {
          const one = obj(p);
          pb.appendChild(el("h4", null, one.wording || ""));
          kv(pb, [["ruling", one.ruling || undefined], ["refused", one.refused || undefined],
            ["held at", arr(one.kept).join(", ") || undefined]]);
          for (const r of arr(one.relations)) {
            const rel = obj(r);
            kv(pb, [[rel.relation, rel.memory + (rel.note ? " \u00b7 " + rel.note : "")]]);
          }
        }
      } else if (b.decided) {
        const db = sec(holder, "What the commit decided");
        kv(db, [["action", d.action], ["memory", d.memory], ["wording", d.wording],
          ["asks", d.asks], ["reason", d.reason], ["note", d.note],
          ["held up", d.held_up], ["retiring", d.retiring ? obj(d.retiring).kind + " "
            + obj(d.retiring).memory : undefined]]);
        supportsView(db, d.supports);
        if (d.support) supportsView(db, [d.support]);
      }
      return;
    }
    kv(sec(holder, "Attempt"), [["stage", b.stage], ["end", b.end], ["state", b.state],
      ["skipped", b.skipped], ["failure", failure(b.failure)], ["episode", b.episode],
      ["attempt started", b.attempt_started_at]]);
  }
  const VIEWS = {
    "observer.given": (holder, b) => {
      kv(sec(holder, "Call"), [["step", b.stage], ["episode", b.episode],
        ["attempt started", b.attempt_started_at],
        ["finding", b.finding
          ? obj(b.finding).id + " \u00b7 " + obj(b.finding).claim : undefined]]);
      messages(holder, b);
    },
    "observer.returned": (holder, b) => {
      const box = sec(holder, "Reply");
      kv(box, [["step", b.stage], ["finding", b.finding], ["failure", failure(b.failure)]]);
      if (typeof b.reply === "string") pre(box, pretty(b.reply));
    },
    "observer.step": observerStep,
    "controller.step": step,
    "understanding.given": messages,
    "understanding.returned": (holder, b) => {
      const box = sec(holder, "Reply");
      kv(box, [["failure", failure(b.failure)]]);
      if (typeof b.reply === "string") pre(box, pretty(b.reply));
    },
    "recall.given": (holder, b) => {
      const box = sec(holder, "Search");
      kv(box, [["run", b.run]]);
      for (const c of arr(b.cues)) {
        const cue = obj(c);
        pre(box, String(cue.text) + "\n— " + arr(cue.kinds).join(", "));
      }
    },
    "recall.returned": recallFound,
    "planning.given": (holder, b) => {
      const tools = arr(b.tools).map((t) => obj(t).name).filter(Boolean);
      if (tools.length) kv(sec(holder, "Offered tools"), [["tools", tools.join(", ")]]);
      messages(holder, b);
    },
    "planning.returned": planningResponse,
    "authorizing.returned": verdicts,
    "digesting.given": digestGiven,
    "digesting.returned": digestReturned,
  };

  // The hash names the learning overview, or an activation by its id and, in walk mode,
  // its step: "#<id>/walk/<n>". An id is written encoded, so a "/" in one never splits it.
  function fromHash() {
    const raw = location.hash.slice(1);
    if (!raw) return null;
    const [head, mode, step] = raw.split("/");
    let id;
    try {
      id = decodeURIComponent(head);
    } catch (error) {
      return null;
    }
    if (!id) return null;
    if (id === LEARNING && mode === undefined) return { learning: true };
    const n = parseInt(step, 10);
    return { id, walk: mode === "walk" ? (n >= 1 ? n : 1) : null };
  }
  document.addEventListener("DOMContentLoaded", () => {
    $("drawer-close").addEventListener("click", closeDrawer);
    $("tab-read").addEventListener("click", () => showTab("read"));
    $("tab-raw").addEventListener("click", () => showTab("raw"));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeDrawer();
      else if (event.key === "ArrowLeft" || event.key === "ArrowRight") walkKey(event);
    });
    $("mode-overview").addEventListener("click", () => setWalk(null));
    $("mode-walk").addEventListener("click", () => setWalk(state.walk || 1));
    $("walk-prev").addEventListener("click", () => moveWalk(-1));
    $("walk-next").addEventListener("click", () => moveWalk(1));
    $("back").addEventListener("click", () => {
      document.body.classList.remove("show-detail");
      closeDrawer();
    });
    window.addEventListener("hashchange", () => {
      const chosen = fromHash();
      if (!chosen) return;
      if (chosen.learning) {
        showView("learning");
      } else if (chosen.id !== state.selected) {
        select(chosen.id, chosen.walk);
      } else {
        showView("activations");
        if (chosen.walk !== state.walk) setWalk(chosen.walk);
      }
    });
    $("view-learning").addEventListener("click", () => { location.hash = "#" + LEARNING; });
    $("view-activations").addEventListener("click", () => {
      if (state.selected) {
        writeHash();
      } else {
        history.replaceState(null, "", location.pathname);
      }
      showView("activations");
    });
    $("ov-search").addEventListener("input", (event) => {
      state.search = event.target.value;
      renderLearning();
    });
    const initial = fromHash();
    if (initial && initial.learning) showView("learning");
    else if (initial) select(initial.id, initial.walk);
    pollList();
    setInterval(pollList, 2000);
    setInterval(pollDetail, 1500);
    setInterval(pollLearning, 2500);
  });
})();
"""


# --- running it --------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """The command line: the record's directory and the port, and nothing to bind with.

    Args:
        argv: The arguments, or ``None`` for the process's own.

    Returns:
        The parsed arguments.
    """
    first, _, rest = (__doc__ or "").partition("\n\n")
    usage, _, _ = rest.partition("What it is\n")
    parser = argparse.ArgumentParser(
        prog="activation_viewer.py",
        description=first,
        epilog=usage,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("record", type=Path, help="the record's directory, <data_dir>/diagnostics")
    parser.add_argument(
        "--port", type=_port, default=DEFAULT_PORT, help=f"the port (default {DEFAULT_PORT})"
    )
    return parser.parse_args(argv)


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:  # noqa: PLR2004 — the port range
        msg = "a port is 1 to 65535"
        raise argparse.ArgumentTypeError(msg)
    return port


def _print(message: str) -> None:
    print(f"activation viewer: {message}", file=sys.stderr, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Serve the record on loopback until interrupted.

    Args:
        argv: The arguments, or ``None`` for the process's own.

    Returns:
        The exit status.
    """
    sys.dont_write_bytecode = True
    arguments = parse_args(argv)
    record = Record(arguments.record)
    if not record.directory.is_dir():
        _print("the record's directory does not exist yet; the list stays empty until it does")
    try:
        server = ViewerServer(record, arguments.port, report=_print)
    except OSError as exc:
        _print(f"cannot listen on {HOST}:{arguments.port}: {type(exc).__name__}")
        return 1
    _print(f"serving http://{HOST}:{server.port} (Ctrl-C stops it)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
