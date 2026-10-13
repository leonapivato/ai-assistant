"""Nothing reads the diagnostic record back (ADR-0314 §3), held by the code's own shape.

ADR-0119 §7's trace store keeps its walk from the pipeline by a seam split and an import
contract. The record goes further: it has no read at all. So these cases pin, over the
source rather than over behaviour, that

* neither Protocol carries a read: each has exactly its one member;
* the store has no read either: its public surface is its two writes of a kind and its
  directory, and it opens no file for reading;
* the store's concrete is named by the composition root alone, and the record's
  directory by the composition root and the backup's exclusion alone (§3:3, §7:5).

``lint-imports``' "nothing imports the evaluation package" contract holds the import
half for every subsystem already; the scans below hold what an import contract cannot
see — a second name for the directory, or a read added to the store itself.
"""

from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path
from typing import Final

import ai_assistant
from ai_assistant.core.protocols import DiagnosticRetention, DiagnosticSink
from ai_assistant.evaluation import FileDiagnosticRecord
from ai_assistant.evaluation import diagnostic_record as store_module

_ROOT: Final = Path(ai_assistant.__file__).resolve().parent


def _members(protocol: type) -> set[str]:
    return {
        name
        for name, value in vars(protocol).items()
        if not name.startswith("_") and callable(value)
    }


def test_neither_protocol_carries_a_read() -> None:
    """§3:1: "No Protocol carries a read of the record"."""
    assert _members(DiagnosticSink) == {"write"}
    assert _members(DiagnosticRetention) == {"purge_before"}


def test_the_store_has_no_read_of_its_own() -> None:
    """§3:3: the store writes and deletes by age, and that is all it can do."""
    public = {
        name for name, _ in inspect.getmembers(FileDiagnosticRecord) if not name.startswith("_")
    }

    assert public == {"write", "purge_before", "directory"}


def test_the_store_opens_no_file_for_reading() -> None:
    """Not its own tail either: knowing a file is truncated is held in memory (§6:3)."""
    tree = ast.parse(inspect.getsource(store_module))
    reads = {"open", "read", "read_text", "read_bytes", "O_RDONLY", "O_RDWR", "readlines"}
    named = {
        node.attr if isinstance(node, ast.Attribute) else node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute | ast.Name)
    }
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }

    assert not (named & {"O_RDONLY", "O_RDWR"})
    assert not (calls & reads - {"open"}), calls & reads
    # Every ``open`` is ``os.open``, with one of two sets of flags: a file's, which are
    # write-only and appending, and the directory's, which open its listing alone.
    opened = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "open"
    ]
    assert [ast.unparse(node.func) for node in opened] == ["os.open"] * len(opened)
    assert {ast.unparse(node.args[1]) for node in opened} == {"_OPEN_FLAGS", "_DIRECTORY_FLAGS"}
    assert store_module._OPEN_FLAGS & os.O_ACCMODE == os.O_WRONLY
    assert store_module._OPEN_FLAGS & os.O_APPEND
    assert store_module._DIRECTORY_FLAGS & os.O_DIRECTORY


def _naming(*names: str) -> set[str]:
    """Every module under the package naming any of ``names``, by path."""
    found: set[str] = set()
    for path in sorted(_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            spelled = (
                node.id
                if isinstance(node, ast.Name)
                else node.attr
                if isinstance(node, ast.Attribute)
                else None
            )
            if spelled in names or (
                isinstance(node, ast.alias) and node.name.rsplit(".", 1)[-1] in names
            ):
                found.add(path.relative_to(_ROOT).as_posix())
                break
    return found


def test_only_the_composition_root_names_the_store() -> None:
    """§3:3: the store itself is handed to nothing; only the root builds it."""
    # The module defining it names it in no expression, so it is not in the set.
    assert _naming("FileDiagnosticRecord") == {"app/composition.py", "evaluation/__init__.py"}


def test_only_the_root_and_the_backups_exclusion_name_the_records_directory() -> None:
    """§3:4, §7:5: the owner reads it with the server's tools; the backup leaves it out."""
    assert _naming("diagnostic_record_directory", "DIAGNOSTIC_DIRECTORY") == {
        "app/__init__.py",
        "app/composition.py",
        "service/backup.py",
    }
