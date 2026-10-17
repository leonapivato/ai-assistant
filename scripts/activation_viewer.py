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
"""

from __future__ import annotations

import argparse
import bisect
import difflib
import hashlib
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
    for message in reversed(_sequence(_mapping(body).get("messages"))):
        shown = _mapping(message)
        content = _text(shown.get("content"))
        if shown.get("role") != "user" or content is None:
            continue
        try:
            document = json.loads(content)
        except _UNPARSABLE:
            return None
        received = _mapping(document).get("input")
        if isinstance(received, str):
            return received
        return _text(_mapping(received).get("text"))
    return None


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


# --- the record's directory --------------------------------------------------------------


@dataclass(slots=True)
class _Watched:
    """What the list knows of one file: how far it has read it, and its summary."""

    identity: tuple[int, int]
    offset: int
    lines: int
    tally: Tally


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

    @property
    def directory(self) -> Path:
        """The record's directory: ``root/diagnostics`` where that exists, else ``root``."""
        inner = self._root / RECORD_DIRECTORY
        return inner if inner.is_dir() else self._root

    def listing(self) -> dict[str, Path]:
        """Every activation's file in the directory, by its id (ADR-0316 §6:3).

        Returns:
            Empty where the directory does not exist yet.
        """
        found: dict[str, Path] = {}
        directory = self.directory
        try:
            with os.scandir(directory) as entries:
                for one in entries:
                    if one.name.endswith(SUFFIX) and one.is_file(follow_symlinks=False):
                        found[one.name[: -len(SUFFIX)]] = directory / one.name
        except _NO_DIRECTORY:
            return {}
        return found

    def activations(self) -> dict[str, object]:
        """The list: every activation's summary, newest first, and a version for polling."""
        listing = self.listing()
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
            summaries = [one.tally.summary() for one in self._watched.values()]
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
        path = self.listing().get(activation_id)
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


def _round_tool_parts(arguments: object, call_id: str | None) -> list[dict[str, object]]:
    """The round's own tool's call, as the notes and the asks it carries."""
    held = _mapping(arguments)
    parts: list[dict[str, object]] = []
    notes = held.get("notes")
    if isinstance(notes, str):
        parts.append(_sized(notes, kind="notes", title="Episode notes"))
    asks = held.get("asks")
    if isinstance(asks, list):
        named = [one if isinstance(one, str) else _pretty(one) for one in asks]
        parts.append({**_sized("\n".join(named), kind="asks", title="Asks named"), "items": named})
    if not isinstance(arguments, dict) or set(held) - {"notes", "asks"}:
        parts.append(
            _sized(_pretty(arguments), kind="call", title=f"Call · {ROUND_TOOL}", id=call_id)
        )
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
        arguments = _arguments(shown.get("args"))
        if name == ROUND_TOOL:
            return _round_tool_parts(arguments, call_id)
        shown_args = shown.get("args") if arguments is None else arguments
        return [_sized(_pretty(shown_args), kind="call", title=f"Call · {name}", id=call_id)]
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
    did["usage_note"] = NO_USAGE
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
    """A changed part's line diff, unified, cut at :data:`DIFF_LINES` lines."""
    if len(before) > DIFF_CHARS or len(after) > DIFF_CHARS:
        return {"lines": [], "cut": False, "too_large": True}
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=2)
    lines = [one for one in diff if not one.startswith(("--- ", "+++ "))]
    return {"lines": lines[:DIFF_LINES], "cut": len(lines) > DIFF_LINES, "too_large": False}


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
    given, returned = _pair_of(built, lines, picked)
    anchor = given or picked
    notes: list[str] = []
    view: dict[str, object] = {
        "source": picked.source,
        "round": built.round_of(anchor.at) if picked.source == "planning" else None,
        "given": None if given is None else given.line,
        "returned": None if returned is None else returned.line,
        "at": _ms(anchor.at),
        "took": None if given is None or returned is None else _ms(returned.at - given.at),
        "about": _about(picked.source, anchor.body),
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
        if picked.source == "planning":
            view["changes"] = _changes(built, given)
    if returned is None:
        notes.append("No returned entry was recorded for this call: what it did is not here.")
    else:
        view["did"] = _did(picked.source, returned.body)
        view["tools"] = _tools(_mapping(returned.body).get("offered_tools"), "returned")
        if _mapping(returned.body).get("offered_tools_unprepared") is not None:
            notes.append("The offered tools are as the round built them, not as prepared.")
    if view["tools"] is None and given is not None:
        view["tools"] = _tools(_mapping(given.body).get("tools"), "given")
    return view


def _pair_of(
    built: _Timeline, lines: Sequence[Line], picked: Entry
) -> tuple[Entry | None, Entry | None]:
    """A call's given entry and its returned one, as the timeline paired them."""
    if picked.kind == "given":
        paired = built.pairs.get(picked.line)
        found = None if paired is None else lines[paired]
        return picked, found if isinstance(found, Entry) else None
    paired = next((one for one, back in built.pairs.items() if back == picked.line), None)
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

    def _activation(self, query: Mapping[str, str]) -> None:
        activation_id = query.get("id", "")
        read = self.server.record.lines(activation_id)
        if read is None:
            self._json({"error": "no such activation"}, HTTPStatus.NOT_FOUND)
            return
        lines, version = read
        if query.get("v") == version:
            self._json({"version": version, "unchanged": True, "now": _now()})
            return
        self._json({**timeline(activation_id, lines), "version": version, "now": _now()})

    def _call(self, query: Mapping[str, str]) -> None:
        read = self.server.record.lines(query.get("id", ""))
        number = query.get("line", "")
        shown = model_call(read[0], int(number)) if read is not None and number.isdigit() else None
        if shown is None:
            self._json({"error": "no such model call"}, HTTPStatus.NOT_FOUND)
            return
        self._json(shown)

    def _entry(self, query: Mapping[str, str]) -> None:
        read = self.server.record.lines(query.get("id", ""))
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
      <div class="card">
        <div class="card-title">Timeline</div>
        <div class="timeline" id="timeline"></div>
        <div class="legend" id="legend"></div>
      </div>
      <div class="card">
        <div class="card-title">Rounds</div>
        <div id="rounds"></div>
      </div>
      <details class="card">
        <summary class="card-title">Every entry</summary>
        <div id="entries"></div>
      </details>
    </div>
  </section>
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
  --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #12151b; --panel: #1a1e26; --ink: #e5e8ee; --muted: #9098a8; --line: #2a303b;
    --hover: #222834; --select: #263354; --accent: #7aa2ff;
    --controller: #7d869a; --recall: #34c3b1; --understanding: #6aa5ff; --planning: #a58bff;
    --authorizing: #f0a93a; --acting: #4cc27a; --digesting: #f07aa2; --unknown: #8b93a3;
    --failed: #ff6b6b; --needs: #f0a93a; --outside: #a58bff; --refused: #ff8a4c;
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
.b-open { color: var(--accent); }
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
.bar.step { opacity: .32; color: var(--ink); }
.bar.step.t-failed, .bar.step.t-timed_out { opacity: .9; background: var(--failed); color: #fff; }
.bar.call {
  top: 9px;
  height: 12px;
  line-height: 12px;
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
@media (max-width: 760px) {
  .layout { grid-template-columns: 1fr; height: auto; }
  .list-pane { border-right: none; }
  .detail-pane { display: none; padding: 14px 16px 40px; }
  body.show-detail .list-pane { display: none; }
  body.show-detail .detail-pane { display: block; }
  .back { display: inline-block; }
  .tl-axis, .tl-lane { grid-template-columns: 78px 1fr; }
  .tl-label { font-size: 11px; }
  .entry-row { grid-template-columns: 70px 1fr; }
  .entry-row span:nth-child(3), .entry-row span:nth-child(4) { display: none; }
}
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
    refused: "refused", truncated: "truncated",
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
  };

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
  function select(id) {
    if (state.selected !== id) {
      state.selected = id;
      state.detailVersion = null;
      state.detail = null;
      closeDrawer();
      // The previous activation's details come down at once: nothing of one
      // activation stays clickable while another's load.
      $("detail-body").hidden = true;
      const empty = $("detail-empty");
      empty.hidden = false;
      empty.textContent = "Loading\u2026";
    }
    const hash = "#" + encodeURIComponent(id);
    if (location.hash !== hash) history.replaceState(null, "", hash);
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
  }
  function renderGone() {
    const empty = $("detail-empty");
    empty.hidden = false;
    empty.textContent = "That activation's file is gone: the record's window deleted it.";
    $("detail-body").hidden = true;
  }
  function renderDetail() {
    const d = state.detail;
    $("detail-empty").hidden = true;
    $("detail-body").hidden = false;
    const s = d.summary;
    const input = $("d-input");
    input.textContent = s.input || "input not shown";
    input.className = "input" + (s.input ? "" : " none");
    const meta = $("d-meta");
    clear(meta);
    const pairs = [
      ["started", clock(s.start, true)], ["took", duration(s.duration)], ["rounds", s.rounds],
      ["ended", endingText(s) || "not yet"], ["entries", s.entries],
    ];
    for (const [k, v] of pairs) {
      const span = el("span", null, k + " ");
      span.appendChild(el("b", null, v));
      meta.appendChild(span);
    }
    const badges = $("d-badges");
    clear(badges);
    badgesFor(s, badges);
    state.drawnOpen = isOpen(s);
    renderTimeline();
    renderRounds();
    renderEntries();
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
      const ordered = items.slice().sort((a, b) => (a.kind === "call") - (b.kind === "call"));
      for (const item of ordered) track.appendChild(drawItem(item, pos, end));
      row.appendChild(track);
      root.appendChild(row);
    }
    renderLegend();
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

  // --- details on click --------------------------------------------------------------
  let drawn = 0;
  async function openLines(id, title, lines) {
    // Each opening is one generation: a load still in flight from an earlier click,
    // on this activation or another, finds its generation gone and draws nothing.
    const generation = ++drawn;
    $("drawer-title").textContent = title;
    const body = $("drawer-body");
    clear(body);
    clear($("drawer-read"));
    // A model call opens readable, its entries whole one tab away (ADR-0316 \u00a73:3).
    const call = callLine(id, lines);
    $("drawer-tabs").hidden = call === null;
    $("drawer").classList.toggle("wide", call !== null);
    showTab(call === null ? "raw" : "read");
    $("drawer").hidden = false;
    if (call !== null) loadCall(generation, id, call);
    for (const line of lines) {
      const holder = el("div");
      body.appendChild(holder);
      try {
        const url = "/api/entry?id=" + encodeURIComponent(id)
          + "&line=" + encodeURIComponent(line);
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
    digesting: "Digesting" };
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
  async function loadCall(generation, id, line) {
    const holder = $("drawer-read");
    holder.appendChild(el("p", "note", "Loading\u2026"));
    let view;
    try {
      view = await getJson("/api/call?id=" + encodeURIComponent(id)
        + "&line=" + encodeURIComponent(line));
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
    head.appendChild(el("h2", null, title));
    const where = [];
    where.push(v.given === null ? "no given entry" : "given line " + v.given);
    where.push(v.returned === null ? "no returned entry" : "returned line " + v.returned);
    if (v.took !== null && v.took !== undefined) where.push("took " + duration(v.took));
    head.appendChild(el("div", "m", where.join(" \u00b7 ")));
    holder.appendChild(head);
    if (v.about && (v.about.question || v.about.result)) {
      kv(holder, [["question", v.about.question], ["result", v.about.result]]);
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
  const VIEWS = {
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

  function fromHash() {
    const raw = location.hash.slice(1);
    if (!raw) return null;
    try {
      return decodeURIComponent(raw);
    } catch (error) {
      return null;
    }
  }
  document.addEventListener("DOMContentLoaded", () => {
    $("drawer-close").addEventListener("click", closeDrawer);
    $("tab-read").addEventListener("click", () => showTab("read"));
    $("tab-raw").addEventListener("click", () => showTab("raw"));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeDrawer();
    });
    $("back").addEventListener("click", () => {
      document.body.classList.remove("show-detail");
      closeDrawer();
    });
    window.addEventListener("hashchange", () => {
      const chosen = fromHash();
      if (chosen && chosen !== state.selected) select(chosen);
    });
    const initial = fromHash();
    if (initial) select(initial);
    pollList();
    setInterval(pollList, 2000);
    setInterval(pollDetail, 1500);
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
