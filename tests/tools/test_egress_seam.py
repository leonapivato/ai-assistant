"""The named egress seam, and the contract that pins it (ADR-0147 §3, issue #66).

Three properties, and they are not the same property:

1. **The seam exists and is inert.** ADR-0017 §2 leaves the `tools/` boundary
   approved and *undesignated*, and ADR-0147 §3 names it without designating it, so
   the module has to exist — a contract can only pin a module that is there — while
   holding nothing. "Holds nothing" is asserted against the module's own syntax
   tree rather than against its public names: a private helper, a raise-on-use stub
   or a status constant would each be something a later lane could read as the
   beginning of permission, and none of them shows up in ``__all__``.
2. **The contract exists, and exempts exactly one module.** Read out of
   ``pyproject.toml`` rather than out of ``import-linter``, for the reason
   ``tests/benchmarks/test_import_discipline.py`` gives for the same move: the
   library offers no API for "what does this contract forbid", and the point is to
   notice the day somebody edits it.
3. **The enumeration and the tree agree.** The contract names every module under
   `tools/` individually (``as_packages`` is false), which buys the seam's exemption
   and costs an entry per module. Nothing in ``import-linter`` notices a module that
   was never listed, so this is where forgetting is caught.

The last test is a second net rather than a restatement. It reads source text, so
it sees the two things the graph cannot: ``asyncio.subprocess``, which
``import-linter`` rejects as a subpackage of an external package and which the graph
squashes into the ``asyncio`` that ``tools/invocation.py`` legitimately imports for
ADR-0029 §4's deadline; and a lazy import inside a function body, which the graph
records but which is easy to write believing nothing sees it. It is still a net and
not a proof — ADR-0017 §4's wrapper and after-the-fact dependency both walk past it
— which is why ADR-0147 §3 states the prohibition as a rule binding an author and a
reviewer, separately from the check.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLS = _REPO_ROOT / "src" / "ai_assistant" / "tools"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

#: The seam ADR-0147 §3 names, and the one module the contract does not constrain.
SEAM = "ai_assistant.tools.egress"

#: The contract's name in `pyproject.toml`. A rename is a change to make here too.
CONTRACT = "network transports are confined to the tools egress seam"

#: The standard-library entries ADR-0147 §3 enumerates and `import-linter` can hold.
#: `asyncio.subprocess` is the fourth entry and is checked by
#: `test_no_other_tools_module_names_a_transport` instead — see this module's
#: docstring and the contract's own comment for why it cannot be here.
REQUIRED_STDLIB = frozenset({"socket", "ssl", "http", "urllib", "subprocess"})

#: Dotted names no `tools/` module but the seam may import, matched against an
#: import and every package containing it: the contract's own standard-library list
#: plus the entry it cannot express. `asyncio` itself is deliberately absent —
#: ADR-0029 §4's deadline runs on it, and forbidding the root would forbid the
#: timeout rather than a transport.
FORBIDDEN_NAMES = frozenset(REQUIRED_STDLIB | {"asyncio.subprocess"})


def _contract() -> dict[str, Any]:
    """The egress contract's table, read out of `pyproject.toml`.

    Returns:
        The contract's own mapping.

    Raises:
        AssertionError: If no contract carries the expected name.
    """
    contracts = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["tool"]["importlinter"][
        "contracts"
    ]
    for contract in contracts:
        if contract.get("name") == CONTRACT:
            return dict(contract)
    raise AssertionError(
        f"no import-linter contract named {CONTRACT!r} in pyproject.toml. ADR-0147 §3 "
        f"requires one, and issue #66 has been open since PR #64 waiting for it."
    )


def _modules() -> dict[str, Path]:
    """Every module under `tools/`, by the dotted name `import-linter` uses.

    Returns:
        Dotted name to path, the package's own ``__init__`` included under
        ``ai_assistant.tools``.
    """
    found: dict[str, Path] = {}
    for path in sorted(_TOOLS.rglob("*.py")):
        parts = path.relative_to(_TOOLS).with_suffix("").parts
        stem = parts[:-1] if parts[-1] == "__init__" else parts
        found[".".join(("ai_assistant", "tools", *stem))] = path
    return found


def _imported_names(source: str) -> set[str]:
    """Every module name imported by ``source``, at any depth and any scope.

    Args:
        source: The module's text.

    Returns:
        Dotted names, as written, with ``from x import y`` contributing both ``x``
        and ``x.y`` — the name is a module whenever the package exports one.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            found.update({node.module} | {f"{node.module}.{alias.name}" for alias in node.names})
    return found


def _containing_packages(name: str) -> set[str]:
    """``name`` and every package containing it.

    Args:
        name: A dotted module name.

    Returns:
        ``{"urllib", "urllib.parse"}`` for ``urllib.parse``, so a forbidden root
        catches a submodule the import graph would have squashed into it.
    """
    parts = name.split(".")
    return {".".join(parts[: index + 1]) for index in range(len(parts))}


def test_the_tree_has_modules_to_check() -> None:
    """A check that silently covers nothing is worse than no check."""
    assert SEAM in _modules()
    assert len(_modules()) >= 4


def test_the_seam_holds_nothing_but_its_docstring() -> None:
    """ADR-0147 §3 names the seam and designates nothing, so it transmits nothing.

    Asserted against the syntax tree, so *any* addition fails — an import, a
    constant, a stub that raises. The module's value is the name, which is what a
    contract can pin and what a designating ADR can attest against; a body would be
    a shape for a later lane to fill in, under an ADR that authorises no byte.
    """
    tree = ast.parse(_modules()[SEAM].read_text(encoding="utf-8"))

    assert ast.get_docstring(tree) is not None, "the seam's docstring is what it holds"
    assert len(tree.body) == 1, (
        "ai_assistant.tools.egress holds more than its docstring. ADR-0017 §3's "
        "fourteen conditions are undischarged and ADR-0147 §3 authorises no byte to "
        "leave from tools/; transport lands here when a designating ADR says so."
    )


def test_the_seam_docstring_records_that_it_is_undesignated() -> None:
    """The one thing a reader of this module must not have to look up.

    A module named ``egress`` in a package a roadmap item is about to grow reads as
    permission unless it says otherwise in its own text.
    """
    docstring = ast.get_docstring(ast.parse(_modules()[SEAM].read_text(encoding="utf-8")))

    assert docstring is not None
    assert "undesignated" in docstring
    assert "ADR-0017" in docstring


def test_the_contract_exempts_the_seam_and_nothing_else() -> None:
    """ADR-0147 §3: the contract binds every `tools/` module *except* the seam."""
    contract = _contract()

    assert contract["type"] == "forbidden"
    assert SEAM not in contract["source_modules"]
    assert set(contract["source_modules"]) == _modules().keys() - {SEAM}, (
        "the contract's source_modules and the modules on disk disagree. Every module "
        "under tools/ is named individually so the seam can be the one absence; a new "
        "module is an entry here, not something that silently escapes."
    )


def test_the_contract_is_configured_the_way_the_exemption_needs() -> None:
    """Two flags, each load-bearing, neither the default the rest of the file takes.

    ``as_packages`` false is what lets ``ai_assistant.tools`` be named without
    pulling the seam in as a descendant — with the default, the package's own
    ``__init__`` would either go unchecked or the exemption would be undone.
    ``allow_indirect_imports`` is the provider-SDK contract's idiom and is what
    permits ADR-0147 §3's own composition: MCP protocol handling sits outside the
    seam and imports it.
    """
    contract = _contract()

    assert str(contract["as_packages"]).lower() == "false"
    assert str(contract["allow_indirect_imports"]).lower() == "true"


def test_the_contract_forbids_the_transports_the_adr_enumerates() -> None:
    """ADR-0147 §3's "at minimum" list, minus the entry the tool cannot express.

    ADR-0017 §4's first two examples — ``urllib`` and the raw socket module — are
    named here on purpose: they are what makes this net cover the accident §4 says a
    contract cannot be trusted to catch in general.
    """
    forbidden = set(_contract()["forbidden_modules"])

    assert forbidden >= REQUIRED_STDLIB, (
        f"the contract does not forbid {sorted(REQUIRED_STDLIB - forbidden)}, which "
        f"ADR-0147 §3 enumerates as its minimum"
    )
    assert "httpx" in forbidden, "the realistic accident is a client library, not a socket"


@pytest.mark.parametrize(
    "module", sorted(_modules().keys() - {SEAM}), ids=lambda name: name.rsplit(".", 1)[-1]
)
def test_no_other_tools_module_names_a_transport(module: str) -> None:
    """The rule, over source text, including what the import graph flattens away."""
    for name in _imported_names(_modules()[module].read_text(encoding="utf-8")):
        offending = _containing_packages(name) & FORBIDDEN_NAMES
        assert not offending, (
            f"{module} imports {name!r}. ADR-0147 §3: no module under tools/ other "
            f"than {SEAM} opens a network connection or launches a subprocess, by any "
            f"route — and that seam is undesignated and transmits nothing."
        )
