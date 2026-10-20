#!/usr/bin/env python3
r"""Prompt replay: judge a candidate prompt on calls the hub has already made (ADR-0335).

How to run it
-------------
On the owner's hub's server, **as the hub's user**, with the hub's own Python, which has
``ai_assistant`` installed (§2:5). The provider's key comes from the environment, and is
the owner's own (§8:1); nothing else is read from it::

    sudo -u <hub-user> <hub-python> -B prompt_replay.py copy <data-dir> <copy-dir>
    sudo -u <hub-user> --preserve-env=ANTHROPIC_API_KEY <hub-python> -B prompt_replay.py \
        replay <copy-dir> --model anthropic:claude-sonnet-5-5 \
        --candidate <draft>/planning.txt --candidate recorded
    sudo -u <hub-user> --preserve-env=ANTHROPIC_API_KEY <hub-python> -B prompt_replay.py \
        rerun <copy-dir> --model anthropic:claude-sonnet-5-5 --episode-limit 1
    sudo -u <hub-user> <hub-python> -B prompt_replay.py delete <copy-dir>

Then start ``activation_viewer.py`` over ``<copy-dir>``: each result is shown beside the
reply it replays.

``copy`` copies the live data directory into a new directory only the hub's user can read
(§3:2): each database by SQLite's online backup from a read-only connection, each file of
the diagnostic record up to its last complete line, every other file whole, and the lock,
the sockets, SQLite's side files and symbolic links skipped. It writes nothing in the live
directory and takes no lock there, and it writes a marker into the copy last, so a copy
that did not finish carries none (§3:3).

``replay`` re-sends given entries of understanding, of each planning round, of each digest
part and of the observer's scout and commit calls (§4:1), each with a candidate's
instruction in place of its system message and everything else as recorded, through the
package's own model layer, to the one model the run names (§4:7). A candidate is a
template file, ``<prompt>.txt``, checked as the hub checks an override (§4:3), or
``recorded``, the call's own instruction, which is the control. It counts the calls before
it sends any and sends none past its bound, 100 unless ``--bound`` says otherwise (§8:2,
§8:3). Each result is one line of ``<activation_id>.replay.jsonl`` in the copy's record
(§6:1).

``rerun`` composes the package over the copy with the record on and the copy's own
overrides, and runs the observer alone until no episode is due or the bound stops it
(§7:1). It reads no setting from the environment or from an ``.env`` file, so it never sees
the live hub's connections, line or search (§7:3).

``delete`` deletes a copy. A copy is deleted when its review ends, and replay and rerun
refuse one older than the retention ``copy`` recorded in it (§3:6).

What it prints is counts, file names, prompt names, versions and failures by class, and
never anything an entry or a reply holds (§5:3).

What it is
----------
One program outside the ``ai_assistant`` package, which nothing in the package imports or
starts (§2:1, §2:2), and which adds no dependency (§2:3). Unlike the viewer it imports
``ai_assistant``: to send through the package's model layer, to check and render a
template by ADR-0334's form, and to compose the observer (§2's note). It runs no tool,
authorizes nothing and sends no message; a planning response's calls and message are
recorded as proposed, and nothing else is done with them (§5:1).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import secrets
import shutil
import sqlite3
import stat
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, cast, override

from pydantic import ValidationError

from ai_assistant.app import build_engine, composition
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.diagnostics import failure_body
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.prompts import PromptOrigin, PromptTemplate
from ai_assistant.core.types import Message, OfferedTool, Role
from ai_assistant.evaluation.diagnostic_record import OBSERVER_SUFFIX, SUFFIX
from ai_assistant.models import (
    PydanticAIProvider,
    PydanticAIToolCallingCompleter,
    ensure_credential_available,
    ensure_vendor_available,
)
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock
from ai_assistant.wire.address import ADMIN_SOCKET_FILENAME, SOCKET_FILENAME

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterator, Mapping, Sequence

    from pydantic_ai import models
    from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

    from ai_assistant.core.prompts import PromptDeclaration
    from ai_assistant.models.tool_calling import ReplayedRound
    from ai_assistant.orchestration.engine import Engine
    from ai_assistant.orchestration.observer.stage import RunOutcome

#: The marker file every copy carries, written last (§3:3).
MARKER: Final = "PROMPT_REPLAY_COPY"

#: The record's directory in a data directory (ADR-0314 §6:1).
RECORD_DIRECTORY: Final = composition.DIAGNOSTIC_DIRECTORY

#: A results file's suffix (§6:1). The viewer never lists one as an activation (§6:5).
REPLAY_SUFFIX: Final = ".replay" + SUFFIX

#: The source and the kind a result is written under (§6:1).
REPLAY_SOURCE: Final = "replay"
REPLAY_KIND: Final = "returned"

#: How many calls a run makes at most, unless it names another bound (§8:2).
DEFAULT_BOUND: Final = 100

#: How long a call may take before it is recorded as failed.
DEFAULT_TIMEOUT_SECONDS: Final = 300.0

#: The candidate that is the call's own recorded instruction (§4:2).
RECORDED: Final = "recorded"

#: The sources whose given entries are replayed (§4:1).
SOURCES: Final = ("understanding", "planning", "digesting", "observer")

#: The observer's steps that make a model call (ADR-0333 §2:2).
OBSERVER_CALLS: Final = frozenset({"scout", "commit"})

#: What the copy step never copies by name: the instance lock and the hub's sockets.
_SKIPPED_NAMES: Final = frozenset({LOCK_FILENAME, SOCKET_FILENAME, ADMIN_SOCKET_FILENAME})

#: SQLite's side files: never copied, and their presence decides how a database is read.
_SIDECARS: Final = ("-wal", "-shm", "-journal")

_DIRECTORY_MODE: Final = 0o700
_FILE_MODE: Final = 0o600
_READ_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_APPEND_FLAGS: Final = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
_CREATE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC

#: What a flag's value may be spelled as on the command line.
_TRUE: Final = frozenset({"true", "yes", "1", "on"})
_FALSE: Final = frozenset({"false", "no", "0", "off"})


class ReplayError(Exception):
    """A refusal: its message names files, prompts and defects, never what they hold."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- the copy (§3) -------------------------------------------------------------------------


@dataclass(slots=True)
class CopyCounts:
    """What a copy took, in counts: what ``copy`` prints."""

    databases: int = 0
    record_files: int = 0
    files: int = 0
    skipped: int = 0


@dataclass(frozen=True, slots=True)
class CopyMark:
    """What a copy's marker says: when it was made, and how long it may be kept (§3:6)."""

    made_at: datetime
    retention: timedelta


def copy_data_dir(
    live: Path,
    destination: Path,
    *,
    retention: timedelta,
    now: Callable[[], datetime] = _utcnow,
) -> CopyCounts:
    """Copy the live data directory into a new owner-only directory (§3:2, §3:3).

    Args:
        live: The hub's data directory, read and never written.
        destination: The copy's directory, which must not exist yet; its parent must.
        retention: How long the copy may be kept, recorded in its marker (§3:6).
        now: The clock the marker is stamped from.

    Returns:
        What was copied and skipped, in counts.

    Raises:
        ReplayError: If the live directory is not one, the destination exists or lies
            inside it, or a file could not be copied; nothing is left at the destination.
    """
    source = live.resolve()
    if not source.is_dir():
        msg = f"{live} is not a directory"
        raise ReplayError(msg)
    target = destination.absolute()
    if target.exists() or target.is_symlink():
        msg = f"{destination} already exists; a copy goes into a new directory"
        raise ReplayError(msg)
    if target.resolve().is_relative_to(source) or source.is_relative_to(target.resolve()):
        msg = f"{destination} and {live} may not lie one inside the other"
        raise ReplayError(msg)
    counts = CopyCounts()
    previous = os.umask(0o077)
    try:
        target.mkdir(mode=_DIRECTORY_MODE)
        try:
            target.chmod(_DIRECTORY_MODE)
            _copy_directory(source, target, counts, in_record=False, top=True)
            marker = {"made_at": now().isoformat(), "retention_seconds": retention.total_seconds()}
            _write_new(target / MARKER, (json.dumps(marker) + "\n").encode("ascii"))
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise
    finally:
        os.umask(previous)
    return counts


def _copy_directory(
    source: Path, target: Path, counts: CopyCounts, *, in_record: bool, top: bool
) -> None:
    """Copy one directory's entries, never following a link (§3:2)."""
    with os.scandir(source) as listing:
        entries = sorted(listing, key=lambda one: one.name)
    for entry in entries:
        name = entry.name
        info = entry.stat(follow_symlinks=False)
        if (top and name in _SKIPPED_NAMES | {MARKER}) or name.endswith(_SIDECARS):
            counts.skipped += 1
        elif stat.S_ISDIR(info.st_mode):
            inner = target / name
            inner.mkdir(mode=_DIRECTORY_MODE)
            inner.chmod(_DIRECTORY_MODE)
            record = in_record or (top and name == RECORD_DIRECTORY)
            _copy_directory(source / name, inner, counts, in_record=record, top=False)
        elif not stat.S_ISREG(info.st_mode):
            # A socket, a link, a pipe or a device: none is data a replay reads.
            counts.skipped += 1
        elif in_record:
            data = _read_regular(source / name)
            _write_new(target / name, data[: data.rfind(b"\n") + 1])
            counts.record_files += 1
        elif name.endswith(".db"):
            _backup_database(source / name, target / name)
            counts.databases += 1
        else:
            _write_new(target / name, _read_regular(source / name))
            counts.files += 1


def _backup_database(source: Path, target: Path) -> None:
    """Copy one database consistently, writing nothing beside the live one (§3:2).

    Where its WAL side files are there, a writer has it open: SQLite's online backup reads
    it from a read-only connection through them. Where none is, the database is whole in
    its file, and is read as immutable, which creates no side file in the live directory;
    a side file appearing during the read means a writer opened it, and the read is
    repeated through the side files.

    Raises:
        ReplayError: If its side files are in any other state, or it cannot be read.
    """
    for _ in range(2):
        present = _sidecars(source)
        if present == {"-wal", "-shm"}:
            query = "mode=ro"
        elif not present:
            query = "mode=ro&immutable=1"
        else:
            msg = f"{source} has SQLite side files in an unexpected state; copy again shortly"
            raise ReplayError(msg)
        try:
            _backup(f"{source.as_uri()}?{query}", target)
        except sqlite3.Error as exc:
            msg = f"{source} could not be copied: {type(exc).__name__}"
            raise ReplayError(msg) from None
        if present or not _sidecars(source):
            target.chmod(_FILE_MODE)
            return
        target.unlink()
    msg = f"{source} kept changing while it was copied; copy again shortly"
    raise ReplayError(msg)


def _sidecars(database: Path) -> set[str]:
    return {one for one in _SIDECARS if os.path.lexists(f"{database}{one}")}


def _backup(uri: str, target: Path) -> None:
    reader = sqlite3.connect(uri, uri=True)
    try:
        writer = sqlite3.connect(target)
        try:
            reader.backup(writer)
        finally:
            writer.close()
    finally:
        reader.close()


def _read_regular(path: Path) -> bytes:
    """A regular file's bytes, opened without following a link.

    Raises:
        ReplayError: If it is not a regular file, or cannot be read.
    """
    try:
        descriptor = os.open(path, _READ_FLAGS)
    except OSError as exc:
        msg = f"{path} could not be read: {exc.strerror}"
        raise ReplayError(msg) from None
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            msg = f"{path} is not a regular file"
            raise ReplayError(msg)
        return handle.read()


def _write_new(path: Path, data: bytes) -> None:
    """Write a new owner-only file, refusing one already there or a link in its place."""
    descriptor = os.open(path, _CREATE_FLAGS, _FILE_MODE)
    with os.fdopen(descriptor, "wb") as handle:
        os.fchmod(handle.fileno(), _FILE_MODE)
        handle.write(data)


def read_mark(copy: Path) -> CopyMark:
    """A copy's marker, or a refusal naming the directory where it carries none (§3:3).

    Raises:
        ReplayError: If ``copy`` carries no readable marker.
    """
    try:
        held = json.loads(_read_regular(copy / MARKER))
        made_at = datetime.fromisoformat(held["made_at"])
        retention = timedelta(seconds=float(held["retention_seconds"]))
    except (ReplayError, ValueError, KeyError, TypeError) as exc:
        msg = f"{copy} carries no replay copy's marker, so it is no copy this tool made"
        raise ReplayError(msg) from exc
    if made_at.tzinfo is None:
        made_at = made_at.replace(tzinfo=UTC)
    return CopyMark(made_at=made_at, retention=retention)


@contextlib.contextmanager
def held_copy(copy: Path, *, now: Callable[[], datetime] = _utcnow) -> Iterator[CopyMark]:
    """Hold a copy's instance lock for the whole run, after checking its marker and age.

    Args:
        copy: The copy's directory.
        now: The clock its age is read on.

    Yields:
        The copy's marker.

    Raises:
        ReplayError: If it carries no marker (§3:3), is older than its retention (§3:6),
            or another process holds its lock (§3:4).
    """
    mark = read_mark(copy)
    age = now() - mark.made_at
    if age > mark.retention:
        msg = (
            f"{copy} was made {_days(age)} ago, past its retention of {_days(mark.retention)}: "
            f"delete it with `prompt_replay.py delete {copy}` and make a new copy (ADR-0335 §3:6)"
        )
        raise ReplayError(msg)
    lock = InstanceLock(copy / LOCK_FILENAME, follow_symlinks=False)
    try:
        acquired = lock.acquire()
    except OSError as exc:
        msg = f"{copy}'s instance lock could not be opened: {exc.strerror}"
        raise ReplayError(msg) from None
    if not acquired:
        msg = f"another process holds {copy}'s instance lock"
        raise ReplayError(msg)
    try:
        yield mark
    finally:
        lock.release()


def delete_copy(copy: Path) -> None:
    """Delete a copy this tool made, under its lock (§3:6).

    Raises:
        ReplayError: If ``copy`` carries no marker, or a run holds its lock.
    """
    read_mark(copy)
    lock = InstanceLock(copy / LOCK_FILENAME, follow_symlinks=False)
    if not lock.acquire():
        msg = f"another process holds {copy}'s instance lock"
        raise ReplayError(msg)
    try:
        shutil.rmtree(copy)
    finally:
        lock.release()


def _days(span: timedelta) -> str:
    days = span.total_seconds() / 86_400
    return f"{days:.1f} days"


# --- the given entries (§4:1) --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Given:
    """One given entry a replay may re-send, and where it is (§6:2).

    Attributes:
        file: Its file's name in the record.
        activation_id: The activation it was written under, which names its file.
        line: Its line in the file, from 0, as the viewer numbers lines.
        recorded_at: Its instant, as written.
        source: Who wrote it.
        stage: The observer's step, or ``None`` for any other source.
        body: Its body, whole.
        original_model: The model its returned entry names, or ``None`` where none does.
    """

    file: str
    activation_id: str
    line: int
    recorded_at: str
    source: str
    stage: str | None
    body: Mapping[str, object]
    original_model: str | None = None


def read_givens(
    record: Path,
    *,
    activations: frozenset[str] | None = None,
    sources: frozenset[str] = frozenset(SOURCES),
) -> list[Given]:
    """Every given entry of a model call in the record, in file and line order.

    Args:
        record: The copy's record directory.
        activations: The activations to read, or ``None`` for every one.
        sources: The sources to read.

    Returns:
        The entries, each with the model its returned entry names where it names one.
    """
    found: list[Given] = []
    for name, activation_id, observer in _record_files(record):
        if activations is not None and activation_id not in activations:
            continue
        lines = _complete_lines(_read_regular(record / name))
        found.extend(_givens_of(name, activation_id, lines, observer=observer, sources=sources))
    return found


def _record_files(record: Path) -> list[tuple[str, str, bool]]:
    """Each activation's file and observer file, never a results file: name, id, observer."""
    files: list[tuple[str, str, bool]] = []
    try:
        with os.scandir(record) as listing:
            names = sorted(one.name for one in listing if one.is_file(follow_symlinks=False))
    except FileNotFoundError:
        return files
    for name in names:
        if not name.endswith(SUFFIX) or name.endswith(REPLAY_SUFFIX):
            continue
        if name.endswith(OBSERVER_SUFFIX):
            files.append((name, name[: -len(OBSERVER_SUFFIX)], True))
        else:
            files.append((name, name[: -len(SUFFIX)], False))
    return files


def _complete_lines(data: bytes) -> list[dict[str, object] | None]:
    """Every complete line, read as one JSON object, or ``None`` where it is not one."""
    end = data.rfind(b"\n")
    if end < 0:
        return []
    read: list[dict[str, object] | None] = []
    for raw in data[:end].split(b"\n"):
        try:
            value = json.loads(raw)
        except ValueError, RecursionError:
            read.append(None)
            continue
        read.append(value if isinstance(value, dict) else None)
    return read


def _givens_of(
    name: str,
    activation_id: str,
    lines: Sequence[dict[str, object] | None],
    *,
    observer: bool,
    sources: frozenset[str],
) -> list[Given]:
    """One file's given entries of model calls, planning's paired with its returned entry."""
    found: list[Given] = []
    unpaired: int | None = None
    for number, line in enumerate(lines):
        if line is None:
            continue
        body = line.get("body")
        if unpaired is not None and _planning_returned(line) and isinstance(body, dict):
            found[unpaired] = _with_model(found[unpaired], body)
            unpaired = None
        given = _given_of(name, activation_id, number, line, observer=observer)
        if given is None or given.source not in sources:
            continue
        found.append(given)
        if given.source == "planning":
            unpaired = len(found) - 1
    return found


def _planning_returned(line: Mapping[str, object]) -> bool:
    return line.get("source") == "planning" and line.get("kind") == "returned"


def _given_of(
    name: str, activation_id: str, number: int, line: Mapping[str, object], *, observer: bool
) -> Given | None:
    """The line as a model call's given entry, or ``None`` where it is not one.

    An activation's own file holds understanding's, planning's and digesting's; its
    observer file the scout's and the commit step's (ADR-0333 §3:1).
    """
    source, body, recorded_at = line.get("source"), line.get("body"), line.get("recorded_at")
    if line.get("kind") != "given" or not isinstance(body, dict) or not isinstance(source, str):
        return None
    stage = body.get("stage") if observer else None
    if observer:
        if source != "observer" or stage not in OBSERVER_CALLS:
            return None
    elif source not in SOURCES or source == "observer":
        return None
    return Given(
        file=name,
        activation_id=activation_id,
        line=number,
        recorded_at=recorded_at if isinstance(recorded_at, str) else "",
        source=source,
        stage=stage if isinstance(stage, str) else None,
        body=body,
    )


def _with_model(given: Given, returned: Mapping[str, object]) -> Given:
    response = returned.get("response")
    model = response.get("model_name") if isinstance(response, dict) else None
    if not isinstance(model, str):
        return given
    return Given(
        file=given.file,
        activation_id=given.activation_id,
        line=given.line,
        recorded_at=given.recorded_at,
        source=given.source,
        stage=given.stage,
        body=given.body,
        original_model=model,
    )


# --- prompts and candidates (§4:2-§4:5) ----------------------------------------------------


def declared_prompts() -> dict[str, PromptDeclaration]:
    """Every prompt the package this runs from declares, by name (ADR-0334 §2)."""
    return {one.name: one for one in composition.PROMPTS}


def recorded_prompt(given: Given) -> Mapping[str, object] | None:
    """The ``prompt`` key the given entry carries (ADR-0334 §8:2), where it carries one."""
    held = given.body.get("prompt")
    return held if isinstance(held, dict) and isinstance(held.get("name"), str) else None


def prompt_name(given: Given, declared: Mapping[str, PromptDeclaration]) -> str | None:
    """The prompt an entry's instruction was rendered from, where it can be named.

    Named by the entry's ``prompt`` key; an entry written before ADR-0334 carries none,
    and is taken to be of the declared prompt named as its source writes it,
    ``<source>`` or, for the observer, ``observer_<step>``, where the package declares one.
    """
    held = recorded_prompt(given)
    if held is not None:
        return cast("str", held["name"])
    inferred = given.source if given.stage is None else f"{given.source}_{given.stage}"
    return inferred if inferred in declared else None


def recorded_flags(given: Given) -> dict[str, bool] | None:
    """The flags the code computed for the call, where the entry records them (§9:1)."""
    held = recorded_prompt(given)
    flags = None if held is None else held.get("flags")
    if not isinstance(flags, dict) or not all(isinstance(one, bool) for one in flags.values()):
        return None
    return {str(name): bool(value) for name, value in flags.items()}


@dataclass(frozen=True, slots=True)
class Candidate:
    """One candidate instruction (§4:2).

    Attributes:
        template: The template, or ``None`` for the recorded instruction.
        origin: ``override``, ``default`` or ``recorded`` (§6:2).
        file: The template file as named on the command line, or ``None``.
        values: The values the package supplies for the template's prompt.
    """

    template: PromptTemplate | None
    origin: str
    file: str | None = None
    values: Mapping[str, str] = field(default_factory=dict)

    @property
    def prompt(self) -> str | None:
        """The prompt it is a template of, or ``None`` for the recorded instruction."""
        return None if self.template is None else self.template.name

    def label(self) -> str:
        """How it is printed: its file name, prompt, version and origin, or ``recorded``."""
        if self.template is None:
            return RECORDED
        return f"{self.file} ({self.template.name} {self.template.version}, {self.origin})"


def load_candidate(spec: str, declared: Mapping[str, PromptDeclaration]) -> Candidate:
    """A candidate from the command line: ``recorded``, or a template file (§4:2, §4:3).

    A template file is ``<prompt>.txt``, checked as the hub checks an override's content
    against what the package declares (ADR-0334 §5:1). Its origin is ``default`` where it
    lies where its prompt's default ships, in the installed package or a checkout of the
    repository, and ``override`` anywhere else.

    Raises:
        ReplayError: Naming the file and its defect and never its content: it is not a
            regular file, names no prompt the package declares, or is not a well-formed
            template of its prompt.
    """
    if spec == RECORDED:
        return Candidate(template=None, origin=RECORDED)
    path = Path(spec)
    declaration = next((one for one in declared.values() if one.filename == path.name), None)
    if declaration is None:
        msg = f"the candidate {spec} names no prompt this package declares"
        raise ReplayError(msg)
    data = _read_regular(path)
    shipped = tuple(declaration.package.split("."))
    origin = (
        PromptOrigin.DEFAULT
        if path.absolute().parent.parts[-len(shipped) :] == shipped
        else PromptOrigin.OVERRIDE
    )
    try:
        template = PromptTemplate.parse(declaration, data, origin=origin)
    except ConfigurationError as exc:
        msg = f"the candidate {spec}: {exc}"
        raise ReplayError(msg) from None
    return Candidate(
        template=template, origin=origin.value, file=spec, values=supplied_values(declaration)
    )


def supplied_values(declaration: PromptDeclaration) -> dict[str, str]:
    """The values the package supplies for a prompt's template (§4:4).

    A value is code-owned text the module sending the prompt hands its template as one
    mapping of exactly the names the prompt declares. It is found there: in the modules of
    the prompt's package that hold its declaration, the one such mapping.

    Raises:
        ReplayError: If no such mapping, or more than one, is found.
    """
    if not declaration.values:
        return {}
    found: dict[int, Mapping[str, str]] = {}
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "")
        package = declaration.package
        if not isinstance(name, str) or not (name == package or name.startswith(package + ".")):
            continue
        held = list(vars(module).values())
        if not any(one is declaration for one in held):
            continue
        for one in held:
            if _values_mapping(one, declaration.values):
                found[id(one)] = cast("Mapping[str, str]", one)
    if len(found) != 1:
        msg = f"the values the package supplies for the prompt {declaration.name} were not found"
        raise ReplayError(msg)
    return dict(next(iter(found.values())))


def _values_mapping(value: object, names: frozenset[str]) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == names
        and all(isinstance(one, str) for one in value.values())
    )


def parse_flags(
    stated: Sequence[str], declared: Mapping[str, PromptDeclaration]
) -> dict[str, dict[str, bool]]:
    """The flags a run states, ``<prompt>.<flag>=true|false``, by prompt (§4:5).

    A run that states any flag of a prompt states every flag the prompt declares, since a
    template is rendered with exactly those.

    Raises:
        ReplayError: If one is malformed, names an undeclared prompt or flag, or leaves a
            declared flag of its prompt unstated.
    """
    flags: dict[str, dict[str, bool]] = {}
    for one in stated:
        named, _, value = one.partition("=")
        prompt, _, flag = named.partition(".")
        if prompt not in declared or flag not in declared[prompt].flags:
            msg = f"the stated flag {named} names no flag a declared prompt has"
            raise ReplayError(msg)
        if value.lower() not in _TRUE | _FALSE:
            msg = f"the stated flag {named} is given no true or false value"
            raise ReplayError(msg)
        flags.setdefault(prompt, {})[flag] = value.lower() in _TRUE
    for prompt, given in flags.items():
        missing = declared[prompt].flags - set(given)
        if missing:
            msg = f"the stated flags of {prompt} leave {len(missing)} of its flags unstated"
            raise ReplayError(msg)
    return flags


# --- planning a run (§4, §8:3) ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Planned:
    """One call a run will send: one request and one candidate (§4:10).

    Attributes:
        givens: The given entries it replays: one, or each that holds the same request,
            as a call the observer wrote under several activations does (§4:11).
        candidate: The candidate.
        prompt: The prompt's name, or ``None`` where the entry's cannot be named.
        instruction: The rendered or recorded instruction it sends.
        flags: The flags it was rendered under, or ``None``.
        flags_from: ``recorded``, ``stated`` or ``none`` (the prompt declares none), or
            ``None`` where nothing was rendered and the entry records no flags.
        messages: The request, its system message the candidate's.
        tools: The tools a planning round offered, as recorded; ``None`` for a completion.
    """

    givens: tuple[Given, ...]
    candidate: Candidate
    prompt: str | None
    instruction: str
    flags: Mapping[str, bool] | None
    flags_from: str | None
    messages: tuple[Message, ...]
    tools: tuple[OfferedTool, ...] | None


@dataclass(slots=True)
class Plan:
    """What a run would send, and what it left out by class."""

    calls: list[Planned] = field(default_factory=list)
    entries: int = 0
    requests: int = 0
    left_out: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True, slots=True)
class _Request:
    messages: tuple[Message, ...]
    system: int
    tools: tuple[OfferedTool, ...] | None


def plan_run(
    givens: Sequence[Given],
    candidates: Sequence[Candidate],
    *,
    declared: Mapping[str, PromptDeclaration],
    stated: Mapping[str, Mapping[str, bool]],
) -> Plan:
    """Every call the run would send: each distinct request for each candidate (§4:10).

    A template candidate is sent for the entries of its own prompt; the recorded
    instruction for every entry. Entries holding the same request are one call, whose
    result is written under each (§4:11).
    """
    plan = Plan(entries=len(givens))
    groups: dict[str, list[Given]] = {}
    for given in givens:
        groups.setdefault(_request_key(given), []).append(given)
    plan.requests = len(groups)
    for group in groups.values():
        first = group[0]
        request = _request(first)
        if request is None:
            plan.left_out["unreadable request"] += 1
            continue
        name = prompt_name(first, declared)
        for candidate in candidates:
            if candidate.template is not None and candidate.prompt != name:
                continue
            planned = _planned(tuple(group), candidate, name, request, stated)
            if planned is None:
                plan.left_out["no flags recorded or stated"] += 1
            else:
                plan.calls.append(planned)
    return plan


def _request_key(given: Given) -> str:
    body = given.body
    held = {
        "source": given.source,
        "stage": given.stage,
        "messages": body.get("messages"),
        "tools": body.get("tools"),
        "finding": body.get("finding"),
    }
    return json.dumps(held, sort_keys=True, ensure_ascii=True)


def _request(given: Given) -> _Request | None:
    """The entry's request rebuilt as the package's types, or ``None`` where it is not one.

    It must hold exactly one system message, the instruction a candidate replaces (§4:1).
    """
    listed = given.body.get("messages")
    if not isinstance(listed, list):
        return None
    offered = given.body.get("tools")
    if given.source == "planning" and not isinstance(offered, list):
        return None
    try:
        messages = tuple(Message.model_validate(one) for one in listed)
        tools = (
            tuple(OfferedTool.model_validate(one) for one in offered)
            if isinstance(offered, list) and given.source == "planning"
            else None
        )
    except ValidationError:
        return None
    system = [index for index, one in enumerate(messages) if one.role is Role.SYSTEM]
    if len(system) != 1:
        return None
    return _Request(messages=messages, system=system[0], tools=tools)


def _planned(
    givens: tuple[Given, ...],
    candidate: Candidate,
    name: str | None,
    request: _Request,
    stated: Mapping[str, Mapping[str, bool]],
) -> Planned | None:
    recorded = recorded_flags(givens[0])
    original = request.messages[request.system]
    if candidate.template is None:
        instruction = original.content
        flags: Mapping[str, bool] | None = recorded
        flags_from = None if recorded is None else "recorded"
    else:
        rendered = _rendered(candidate.template, candidate.values, recorded, stated)
        if rendered is None:
            return None
        instruction, flags, flags_from = rendered
    messages = list(request.messages)
    messages[request.system] = Message(role=Role.SYSTEM, content=instruction, name=original.name)
    return Planned(
        givens=givens,
        candidate=candidate,
        prompt=name,
        instruction=instruction,
        flags=flags,
        flags_from=flags_from,
        messages=tuple(messages),
        tools=request.tools,
    )


def _rendered(
    template: PromptTemplate,
    values: Mapping[str, str],
    recorded: Mapping[str, bool] | None,
    stated: Mapping[str, Mapping[str, bool]],
) -> tuple[str, Mapping[str, bool], str] | None:
    """A template rendered under the flags recorded for the call, or else stated (§4:4, §4:5).

    Returns:
        The instruction, its flags and where they came from; ``None`` where the call
        records no flags its prompt declares and the run states none.
    """
    declared = template.declaration.flags
    if not declared:
        flags: Mapping[str, bool] = {}
        flags_from = "none"
    elif recorded is not None and declared <= recorded.keys():
        flags = {one: recorded[one] for one in declared}
        flags_from = "recorded"
    elif template.name in stated:
        flags = dict(stated[template.name])
        flags_from = "stated"
    else:
        return None
    return template.render(flags=flags, values=values), flags, flags_from


# --- sending (§4:6-§4:12) --------------------------------------------------------------------


class Caller(Protocol):
    """How a replay sends a call: through the package's own model layer, to one model."""

    @property
    def model_name(self) -> str:
        """The run's one model, as each result names it (§6:2)."""
        ...

    async def complete(self, messages: Sequence[Message]) -> str:
        """Send a completion and return its reply's text."""
        ...

    async def replay_round(
        self, messages: Sequence[Message], tools: Sequence[OfferedTool]
    ) -> ReplayedRound:
        """Send a planning round through the completer's replay seam (§4:8)."""
        ...


class ModelCaller:
    """The package's model layer, sending every call to one named model (§4:6-§4:8).

    A completion goes through :class:`PydanticAIProvider`, as understanding's, a digest
    part's and the observer's calls go, with no routing and no retry; a planning round
    goes through the completer's replay seam, which sends it as it is sent with the record
    on. Neither is handed a sink, and nothing binds an activation (§4:12).
    """

    def __init__(self, model: models.Model | str, *, timeout: float) -> None:
        """Name the run's model and how long a call may take.

        Args:
            model: The one model every call goes to, which nothing falls back from.
            timeout: Seconds a call may take before it is recorded as failed.
        """
        self._model = model
        self._timeout = timeout
        self._provider = PydanticAIProvider(model)
        self._completer = PydanticAIToolCallingCompleter(model)

    @property
    def model_name(self) -> str:
        """The run's model, as named."""
        return self._model if isinstance(self._model, str) else self._model.model_name

    async def complete(self, messages: Sequence[Message]) -> str:
        """Send a completion once, to the run's model alone."""
        async with asyncio.timeout(self._timeout):
            reply = await self._provider.complete(messages)
        return reply.content

    async def replay_round(
        self, messages: Sequence[Message], tools: Sequence[OfferedTool]
    ) -> ReplayedRound:
        """Send a planning round once, to the run's model alone, as recorded."""
        async with asyncio.timeout(self._timeout):
            return await self._completer.replay_round(messages, tools, model=self._model)


@dataclass(slots=True)
class Sent:
    """What a run sent, in counts and file names: what ``replay`` prints."""

    calls: int = 0
    replied: int = 0
    failed: Counter[str] = field(default_factory=Counter)
    files: set[str] = field(default_factory=set)


async def send_plan(
    plan: Plan,
    caller: Caller,
    record: Path,
    *,
    run: str,
    now: Callable[[], datetime] = _utcnow,
) -> Sent:
    """Send each planned call once, and write its result under each entry it replays.

    A call is sent once for each candidate and its one response recorded; nothing is
    continued (§4:10). A call that fails is recorded as failed (§4:7).
    """
    sent = Sent()
    for planned in plan.calls:
        outcome = await _outcome(planned, caller)
        sent.calls += 1
        failure = outcome.get("failure")
        if isinstance(failure, dict) and "response" not in outcome:
            sent.failed[str(failure.get("class"))] += 1
        else:
            sent.replied += 1
        for given in planned.givens:
            line = {
                "activation_id": given.activation_id,
                "source": REPLAY_SOURCE,
                "kind": REPLAY_KIND,
                "recorded_at": now().isoformat(),
                "body": {**result_body(given, planned, run, caller.model_name), **outcome},
            }
            sent.files.add(append_result(record, given.activation_id, line))
    return sent


async def _outcome(planned: Planned, caller: Caller) -> dict[str, object]:
    """The reply as text, or the planning response whole, or the failure (§6:2)."""
    try:
        if planned.tools is None:
            return {"reply": await caller.complete(planned.messages)}
        replayed = await caller.replay_round(planned.messages, planned.tools)
    except Exception as exc:  # every failure of the one model is recorded (§4:7)
        return {"failure": failure_body(exc)}
    held: dict[str, object] = {
        "response": replayed.response,
        "read_as_round": replayed.failure is None,
    }
    if replayed.failure is not None:
        held["failure"] = failure_body(replayed.failure)
    return held


def result_body(given: Given, planned: Planned, run: str, model: str) -> dict[str, object]:
    """What a result names, apart from the reply (§6:2)."""
    recorded = recorded_prompt(given)
    template = planned.candidate.template
    if template is not None:
        version: object = template.version
    else:
        version = None if recorded is None else recorded.get("version")
    return {
        "replays": {
            "file": given.file,
            "line": given.line,
            "recorded_at": given.recorded_at,
            "source": given.source,
            "stage": given.stage,
        },
        "run": run,
        "prompt": planned.prompt,
        "recorded_prompt": None
        if recorded is None
        else {"version": recorded.get("version"), "origin": recorded.get("origin")},
        "candidate": {
            "version": version,
            "origin": planned.candidate.origin,
            "file": planned.candidate.file,
            "instruction": planned.instruction,
        },
        "flags": None if planned.flags is None else dict(planned.flags),
        "flags_from": planned.flags_from,
        "model": model,
        "original_model": given.original_model,
        "original_model_known": given.original_model is not None,
    }


def append_result(record: Path, activation_id: str, line: Mapping[str, object]) -> str:
    """Append one result line whole to the activation's results file (§6:1, §6:3).

    Returns:
        The results file's name.

    Raises:
        ReplayError: If the id cannot name a file, or the line could not be written whole;
            a line written in part is cut back.
    """
    if not activation_id or "/" in activation_id or "\0" in activation_id:
        msg = "an entry's activation id cannot name a results file"
        raise ReplayError(msg)
    name = activation_id + REPLAY_SUFFIX
    data = (json.dumps(line, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
    descriptor = os.open(record / name, _APPEND_FLAGS, _FILE_MODE)
    try:
        os.fchmod(descriptor, _FILE_MODE)
        size = os.fstat(descriptor).st_size
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(descriptor, view) :]
        except OSError as exc:
            os.ftruncate(descriptor, size)
            msg = f"a result could not be written to {name}: {exc.strerror}"
            raise ReplayError(msg) from None
    finally:
        os.close(descriptor)
    return name


# --- the replay command ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplayOptions:
    """What a replay run was asked for."""

    copy: Path
    model: str
    candidates: tuple[str, ...] = (RECORDED,)
    activations: frozenset[str] | None = None
    sources: frozenset[str] = frozenset(SOURCES)
    prompts: frozenset[str] | None = None
    flags: tuple[str, ...] = ()
    bound: int = DEFAULT_BOUND
    count_only: bool = False
    timeout: float = DEFAULT_TIMEOUT_SECONDS


async def replay(
    options: ReplayOptions,
    *,
    report: Callable[[str], None],
    caller: Caller | None = None,
    now: Callable[[], datetime] = _utcnow,
) -> int:
    """Run a replay over a copy: count, refuse past the bound, then send (§4, §8:3).

    Args:
        options: What was asked for.
        report: Where counts, names and failure classes are printed (§5:3).
        caller: How calls are sent; the run's model through the package's model layer
            where ``None``.
        now: The clock results are stamped from.

    Returns:
        The exit status: 0 where every call was sent, 1 where the bound refused the run.

    Raises:
        ReplayError: Where the run is refused before anything is sent.
    """
    declared = declared_prompts()
    candidates = [load_candidate(one, declared) for one in options.candidates]
    stated = parse_flags(options.flags, declared)
    with held_copy(options.copy, now=now) as mark:
        report(f"copy {options.copy}: made {_days(now() - mark.made_at)} ago")
        record = options.copy / RECORD_DIRECTORY
        prompts = options.prompts
        templates = {one.prompt for one in candidates if one.prompt is not None}
        if prompts is None and templates:
            prompts = frozenset(templates)
            report(f"entries of the candidates' prompts only: {', '.join(sorted(templates))}")
        givens = [
            one
            for one in read_givens(record, activations=options.activations, sources=options.sources)
            if prompts is None or prompt_name(one, declared) in prompts
        ]
        plan = plan_run(givens, candidates, declared=declared, stated=stated)
        _report_plan(plan, candidates, givens, options.bound, report)
        if len(plan.calls) > options.bound:
            report(f"refused: {len(plan.calls)} calls exceed the bound of {options.bound}")
            return 1
        if options.count_only or not plan.calls:
            return 0
        if caller is None:
            _check_model(options.model)
            caller = ModelCaller(options.model, timeout=options.timeout)
        run = f"{now().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
        sent = await send_plan(plan, caller, record, run=run, now=now)
    _report_sent(sent, run, report)
    return 0


def _check_model(model: str) -> None:
    """Refuse a model whose vendor is missing or holds no key, before anything is sent."""
    try:
        ensure_vendor_available(model)
        ensure_credential_available(model)
    except ConfigurationError as exc:
        msg = f"the model {model} cannot be used: {type(exc).__name__}"
        raise ReplayError(msg) from None


def _report_plan(
    plan: Plan,
    candidates: Sequence[Candidate],
    givens: Sequence[Given],
    bound: int,
    report: Callable[[str], None],
) -> None:
    files = len({one.file for one in givens})
    report(
        f"{plan.entries} given entries in {files} files, {plan.requests} distinct requests; "
        f"candidates: {'; '.join(one.label() for one in candidates)}"
    )
    stated = sum(1 for one in plan.calls if one.flags_from == "stated")
    report(f"{len(plan.calls)} calls to send (bound {bound}); {stated} under stated flags")
    for reason, count in sorted(plan.left_out.items()):
        report(f"left out: {count} ({reason})")


def _report_sent(sent: Sent, run: str, report: Callable[[str], None]) -> None:
    report(f"run {run}: {sent.calls} calls sent, {sent.replied} replied")
    for failure, count in sorted(sent.failed.items()):
        report(f"failed: {count} ({failure})")
    report(f"results in {len(sent.files)} files: {', '.join(sorted(sent.files))}")


# --- the rerun (§7) -------------------------------------------------------------------------


class _StatedSettings(Settings):
    """Settings from what the rerun states alone: no environment, ``.env`` or secrets.

    The rerun runs as the hub's user on the hub's server, where the environment or an
    ``.env`` file may hold the live hub's line, connections and search. A copy composed
    with them could reach a live line (§7:3), so this reads none of them.
    """

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Only what was passed to the constructor."""
        del settings_cls, env_settings, dotenv_settings, file_secret_settings
        return (init_settings,)


@dataclass(frozen=True, slots=True)
class RerunOptions:
    """What a rerun was asked for."""

    copy: Path
    model: str
    bound: int = DEFAULT_BOUND
    episode_limit: int | None = None
    timezone: str = "UTC"
    embedder: EmbedderKind = EmbedderKind.ON_DEVICE


def rerun_settings(options: RerunOptions) -> Settings:
    """The settings a rerun composes the package with, and nothing from the environment.

    The record is on and the copy's overrides are read (§7:1); every model call goes to the
    run's one model, with no fallback; the observer's daily budget is the bound (§8:4).
    """
    return _StatedSettings(
        data_dir=options.copy,
        diagnostic_record=True,
        prompt_overrides=True,
        default_model=options.model,
        fallback_models=(),
        observer_scout_model=options.model,
        observer_commit_model=options.model,
        observer_daily_calls=options.bound,
        timezone=options.timezone,
        embedder=options.embedder,
    )


@contextlib.contextmanager
def narrowed_episode_window(limit: int | None) -> Iterator[int]:
    """The episode selector's bound, narrowed for the composition built inside (§7:4).

    Yields:
        The bound the composition is built with.
    """
    held = vars(composition)
    name = "UNDERSTANDING_EPISODE_LIMIT"
    original = cast("int", held[name])
    if limit is None or limit >= original:
        yield original
        return
    held[name] = limit
    try:
        yield limit
    finally:
        held[name] = original


async def rerun(
    options: RerunOptions,
    *,
    report: Callable[[str], None],
    build: Callable[[Settings], Engine] = build_engine,
    check_model: Callable[[str], None] = _check_model,
    now: Callable[[], datetime] = _utcnow,
) -> int:
    """Rerun the observer over a copy until no episode is due or the bound stops it (§7).

    It composes the package over the copy and calls the observer alone: it does not start
    the engine, so no reader, line or conversation sweep runs (§7:3).

    Returns:
        The exit status, 0.

    Raises:
        ReplayError: Where the run is refused before anything is sent.
    """
    with held_copy(options.copy, now=now) as mark:
        report(f"copy {options.copy}: made {_days(now() - mark.made_at)} ago")
        check_model(options.model)
        settings = rerun_settings(options)
        report(f"the observer's daily budget is set to the bound, {options.bound} calls")
        original = composition.UNDERSTANDING_EPISODE_LIMIT
        with narrowed_episode_window(options.episode_limit) as limit:
            if limit != original:
                report(f"the episode selector's bound is narrowed from {original} to {limit}")
            engine = build(settings)
        try:
            await _observe(engine, report)
        finally:
            await engine.aclose()
    return 0


async def _observe(engine: Engine, report: Callable[[str], None]) -> None:
    """Run the observer until a run finds nothing due, is busy, or the budget holds it."""
    runs = 0
    while True:
        outcome: RunOutcome = await engine.observe_episodes()
        runs += 1
        report(
            f"observer run {runs}: {outcome.processed} processed, {outcome.skipped} skipped, "
            f"{outcome.waiting} waiting, {outcome.stuck} stuck"
            + (", held by the budget" if outcome.held else "")
        )
        done = outcome.processed + outcome.skipped + outcome.waiting + outcome.stuck
        if outcome.held or outcome.busy or done == 0:
            return


# --- the command line ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Read the command line.

    Args:
        argv: The arguments, ``sys.argv[1:]`` where ``None``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="prompt_replay.py",
        description="Judge a candidate prompt on calls the hub has already made (ADR-0335).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    copying = commands.add_parser("copy", help="copy the live data directory (§3)")
    copying.add_argument("live", type=Path)
    copying.add_argument("destination", type=Path)
    copying.add_argument(
        "--retention-days",
        type=_positive_float,
        default=_default_retention().total_seconds() / 86_400,
        help="how long the copy may be kept: the hub's diagnostic_retention (default 30)",
    )
    replaying = commands.add_parser("replay", help="re-send recorded calls (§4)")
    replaying.add_argument("copy", type=Path)
    _model_and_bound(replaying)
    replaying.add_argument("--candidate", action="append", default=None)
    replaying.add_argument("--activation", action="append", default=None)
    replaying.add_argument("--source", action="append", choices=SOURCES, default=None)
    replaying.add_argument("--prompt", action="append", default=None)
    replaying.add_argument("--flag", action="append", default=[])
    replaying.add_argument("--count", action="store_true", help="count the calls and stop")
    replaying.add_argument("--timeout", type=_positive_float, default=DEFAULT_TIMEOUT_SECONDS)
    rerunning = commands.add_parser("rerun", help="rerun the observer over a copy (§7)")
    rerunning.add_argument("copy", type=Path)
    _model_and_bound(rerunning)
    rerunning.add_argument("--episode-limit", type=_positive_int, default=None)
    rerunning.add_argument("--timezone", default="UTC")
    rerunning.add_argument(
        "--embedder", choices=[one.value for one in EmbedderKind], default=EmbedderKind.ON_DEVICE
    )
    deleting = commands.add_parser("delete", help="delete a copy (§3:6)")
    deleting.add_argument("copy", type=Path)
    return parser.parse_args(argv)


def _model_and_bound(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", required=True, help="the one model every call goes to")
    parser.add_argument("--bound", type=_positive_int, default=DEFAULT_BOUND)


def _default_retention() -> timedelta:
    return cast("timedelta", Settings.model_fields["diagnostic_retention"].default)


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        msg = "must be at least 1"
        raise argparse.ArgumentTypeError(msg)
    return number


def _positive_float(value: str) -> float:
    number = float(value)
    if not number > 0:
        msg = "must be positive"
        raise argparse.ArgumentTypeError(msg)
    return number


def _print(message: str) -> None:
    print(f"prompt_replay: {message}", flush=True)


def run_command(arguments: argparse.Namespace, *, report: Callable[[str], None]) -> int:
    """Run one parsed command.

    Returns:
        The exit status.

    Raises:
        ReplayError: Where the command is refused.
    """
    command = arguments.command
    if command == "copy":
        retention = timedelta(days=arguments.retention_days)
        counts = copy_data_dir(arguments.live, arguments.destination, retention=retention)
        report(
            f"copied into {arguments.destination}: {counts.databases} databases, "
            f"{counts.record_files} record files, {counts.files} other files; "
            f"{counts.skipped} skipped; keep it no longer than {_days(retention)}"
        )
        return 0
    if command == "delete":
        delete_copy(arguments.copy)
        report(f"deleted {arguments.copy}")
        return 0
    return asyncio.run(_run_async(arguments, report=report))


def _run_async(
    arguments: argparse.Namespace, *, report: Callable[[str], None]
) -> Coroutine[object, object, int]:
    if arguments.command == "rerun":
        return rerun(
            RerunOptions(
                copy=arguments.copy,
                model=arguments.model,
                bound=arguments.bound,
                episode_limit=arguments.episode_limit,
                timezone=arguments.timezone,
                embedder=EmbedderKind(arguments.embedder),
            ),
            report=report,
        )
    return replay(
        ReplayOptions(
            copy=arguments.copy,
            model=arguments.model,
            candidates=tuple(arguments.candidate or (RECORDED,)),
            activations=None if arguments.activation is None else frozenset(arguments.activation),
            sources=frozenset(arguments.source or SOURCES),
            prompts=None if arguments.prompt is None else frozenset(arguments.prompt),
            flags=tuple(arguments.flag),
            bound=arguments.bound,
            count_only=arguments.count,
            timeout=arguments.timeout,
        ),
        report=report,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool.

    Args:
        argv: The arguments, ``sys.argv[1:]`` where ``None``.

    Returns:
        The exit status: 0 done, 1 refused.
    """
    arguments = parse_args(argv)
    try:
        return run_command(arguments, report=_print)
    except ReplayError as exc:
        _print(f"refused: {exc}")
    except OSError as exc:
        # A file system's refusal names its file and its reason, and nothing it holds.
        _print(f"failed: {type(exc).__name__} on {exc.filename}: {exc.strerror}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
