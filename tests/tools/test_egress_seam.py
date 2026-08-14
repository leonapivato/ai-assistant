"""The named egress seam, and the contract that pins it (ADR-0147 §3, issue #66).

Three properties, and they are not the same property:

1. **The seam exists and is inert.** ADR-0017 §2 leaves the `tools/` boundary
   approved and *undesignated*, and ADR-0147 §3 names it without designating it, so
   the module has to exist — a contract can only pin a module that is there — while
   transmitting nothing.

   **This used to be asserted as emptiness, and it is now asserted as inertness.**
   The old check pinned the module's syntax tree to a single node, on the stated
   ground that a body "would be a shape for a later lane to fill in". That was a
   proxy: the property ADR-0017 §2 and ADR-0147 §3 actually state is that **no
   byte leaves**, and emptiness was one way of buying it. Once the transport lands
   — which it must, because ADR-0017 §3's conditions 5, 8 and 12 are properties of
   *code* that a designating ADR has to attest against — the proxy has to be
   replaced by the thing it stood for, not dropped. So three checks stand in its
   place: no module outside the seam names the transport, so nothing in production
   constructs one; no registered tool is bound to a callable that could reach it;
   and inside the seam exactly one function opens a connection, so the boundary
   still has one place to pin.
2. **The contract exists, and exempts exactly one module.** Read out of
   ``pyproject.toml`` rather than out of ``import-linter``, for the reason
   ``tests/benchmarks/test_import_discipline.py`` gives for the same move: the
   library offers no API for "what does this contract forbid", and the point is to
   notice the day somebody edits it.
3. **The enumeration and the tree agree.** The contract names every module under
   `tools/` individually (``as_packages`` is false), which buys the seam's exemption
   and costs an entry per module. Nothing in ``import-linter`` notices a module that
   was never listed, so this is where forgetting is caught.

The source-reading test is a second net rather than a restatement. It reads names, so
it reaches the two subprocess routes no import contract can express: ``asyncio``'s —
``asyncio.subprocess``, which ``import-linter`` rejects as a subpackage of an external
package, and the ``create_subprocess_*`` functions the package exports at its root,
both squashed into the ``asyncio`` that ``tools/invocation.py`` legitimately imports
for ADR-0029 §4's deadline — and the ``os`` process launchers, which are not modules
at all, so the name shows up only at a call. Both sets are derived from the running
interpreter rather than hand-listed, because a hand list is exactly what the second
review round found incomplete.

**And the enumeration is checked against the dependency closure, not against itself.**
``test_every_runtime_dependency_is_classified`` walks the runtime requirement graph
and fails on any package this file has not sorted into transport-bearing or not, so a
new dependency is a decision rather than an omission — which is the mechanical half of
ADR-0147 §3's clause obliging the lane that adds a transport to extend the list.

**What none of this sees, stated rather than implied.** ``getattr(os, "system")``, a
launcher or a client reached through a local wrapper or a callable passed in, a
transport inside a package classified as not transport-bearing, and a dev-only
dependency (outside the runtime closure by construction). It is a net and not a proof,
which is ADR-0017 §4's own accounting, and it is why ADR-0147 §3 states the
prohibition as a rule binding an author and a reviewer *separately* from the check: a
clause claiming these tests pinned the universal rule would claim exactly the proof
§4 denies.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.metadata
import importlib.util
import os
import tomllib
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement

from ai_assistant.testing import FakeMemoryStore
from ai_assistant.tools.builtin import build_default_registry
from ai_assistant.tools.send_email import SEND_EMAIL_ID, SendEmail, UndesignatedSeamError

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

#: The two entries the contract carries ahead of the dependency. `openai` and
#: `huggingface_hub` both reach for these under optional extras, so an extra flipping
#: on must not silently widen the seam; neither resolves in this environment today.
FORWARD_LOOKING = frozenset({"aiohttp", "websockets"})

#: The `os` process launchers, **derived from the running interpreter** rather than
#: hand-listed — the hand list missed `execvpe`, `spawnve` and four others. Not
#: modules, so no import contract can name them, and `import os` is not itself a
#: reason to fail anything: the name shows up at an attribute or a `from os import …`.
#: `startfile` is added by name because it exists only on Windows.
OS_LAUNCHERS = frozenset(
    {name for name in dir(os) if name.startswith(("exec", "spawn", "posix_spawn", "fork", "popen"))}
    | {"system", "startfile"}
)

#: `asyncio`'s subprocess surface: the submodule ADR-0147 §3 names, plus the two
#: functions the package exports at its root, which are how a launch is actually
#: written. Derived the same way and for the same reason as `OS_LAUNCHERS`.
ASYNCIO_LAUNCHERS = frozenset(
    {"subprocess"} | {name for name in dir(asyncio) if name.startswith("create_subprocess")}
)

#: Dotted names no `tools/` module but the seam may reach for, matched against the
#: name and every package containing it. `asyncio` and `os` are deliberately absent as
#: *roots* — ADR-0029 §4's deadline runs on the first and the second is the standard
#: library's front door, so forbidding either would forbid the timeout and `os.path`
#: rather than a transport.
FORBIDDEN_NAMES = frozenset(
    REQUIRED_STDLIB
    | {f"asyncio.{name}" for name in ASYNCIO_LAUNCHERS}
    | {f"os.{name}" for name in OS_LAUNCHERS}
)

#: The roots whose *attributes* the source scan follows, because the module itself is
#: legitimate and only some of its members are not.
WATCHED_ROOTS = frozenset({"asyncio", "os"})

#: Runtime dependencies whose own purpose includes moving bytes over a connection, by
#: distribution name. `test_every_runtime_dependency_is_classified` fails on anything
#: in the closure that is in neither this set nor `NOT_TRANSPORT_BEARING`, so a new
#: dependency has to be sorted into one of them.
TRANSPORT_BEARING = frozenset(
    {
        "anthropic",
        "anyio",
        "fastembed",
        "fsspec",
        "genai_prices",
        "hf_xet",
        "httpcore",
        "httpcore2",
        "httpx",
        "httpx2",
        "huggingface_hub",
        "openai",
        "pydantic_ai_slim",
        "requests",
        "tiktoken",
        "tokenizers",
        "urllib3",
    }
)

#: Where a distribution's name is not the name a module imports.
IMPORT_NAME = {"pydantic_ai_slim": "pydantic_ai"}

#: The rest of the runtime closure, classified and not forbidden. Four groups, and the
#: grouping is the argument: packages that hold no I/O at all; `h11`, `certifi` and
#: `truststore`, which serve a transport without being one; `jeepney` and
#: `secretstorage`, which speak D-Bus over a local socket rather than off the device;
#: and the residue whose *purpose* is something else but which holds an incidental
#: fetch — `numpy`'s `DataSource`, `jsonschema`'s legacy remote-`$ref` resolver,
#: `pygments`, `tqdm`, `opentelemetry_api`, `onnxruntime`. Forbidding that last group
#: to `tools/` would be a rule about arithmetic and progress bars, and would be worked
#: around the first time somebody wanted one. It is the residue ADR-0017 §4 means by
#: "a net, not a proof", and it rests on ADR-0147 §3's first clause.
NOT_TRANSPORT_BEARING = frozenset(
    {
        "annotated_doc",
        "annotated_types",
        "attrs",
        "certifi",
        "cffi",
        "charset_normalizer",
        "click",
        "cryptography",
        "distro",
        "docstring_parser",
        "filelock",
        "flatbuffers",
        "griffelib",
        "h11",
        "icalendar",
        "idna",
        "jaraco_classes",
        "jaraco_context",
        "jaraco_functools",
        "jeepney",
        "jiter",
        "jsonschema",
        "jsonschema_specifications",
        "keyring",
        "logfire_api",
        "loguru",
        "markdown_it_py",
        "mdurl",
        "mmh3",
        "more_itertools",
        "numpy",
        "onnxruntime",
        "opentelemetry_api",
        "packaging",
        "pillow",
        "protobuf",
        "py_rust_stemmers",
        "pycparser",
        "pydantic",
        "pydantic_core",
        "pydantic_graph",
        "pydantic_settings",
        "pygments",
        "python_dateutil",
        "python_dotenv",
        "pywin32_ctypes",
        "pyyaml",
        "referencing",
        "regex",
        "rich",
        "rpds_py",
        "secretstorage",
        "shellingham",
        "six",
        "sniffio",
        "sqlite_vec",
        "structlog",
        "tqdm",
        "truststore",
        "typer",
        "typing_extensions",
        "typing_inspection",
        "tzdata",
    }
)


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


def _reached_names(source: str) -> set[str]:
    """Every dotted name ``source`` reaches for, at any depth and any scope.

    Imports at any nesting, ``from x import y`` as both ``x`` and ``x.y``, and
    attribute access on whatever local name a `WATCHED_ROOTS` package is bound to — so
    ``import os as _os`` followed by ``_os.system(…)`` reads as ``os.system``. It sees
    names, so ``getattr`` and a local wrapper are outside it.

    Args:
        source: The module's text.

    Returns:
        Dotted names, as written, with an attribute on a watched root normalised back
        to that root's real name.
    """
    tree = ast.parse(source)
    found: set[str] = set()
    bindings: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
                root = alias.name.split(".")[0]
                if root in WATCHED_ROOTS:
                    bindings[alias.asname or root] = root
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            found.update({node.module} | {f"{node.module}.{alias.name}" for alias in node.names})

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in bindings
        ):
            found.add(f"{bindings[node.value.id]}.{node.attr}")

    return found


def _runtime_closure() -> set[str]:
    """Every distribution this project's runtime dependencies pull in, transitively.

    Runtime rather than the whole lock: dev tooling is not in a deployed install, so a
    `tools/` module could not import it there however transport-bearing it is.

    Returns:
        Normalised distribution names, this project's own excluded.
    """
    declared = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
    installed = {
        _normalise(dist.metadata["Name"]): dist
        for dist in importlib.metadata.distributions()
        if dist.metadata["Name"]
    }

    seen: set[str] = set()
    pending = [Requirement(text) for text in declared]
    while pending:
        requirement = pending.pop()
        name = _normalise(requirement.name)
        if name in seen:
            continue
        seen.add(name)
        for text in installed[name].requires or [] if name in installed else []:
            dependency = Requirement(text)
            if dependency.marker is None or any(
                dependency.marker.evaluate({"extra": extra})
                for extra in {"", *(requirement.extras or set())}
            ):
                pending.append(dependency)
    return seen


def _normalise(name: str) -> str:
    """A distribution name in the one spelling this module compares by.

    Args:
        name: A distribution name as declared or as installed.

    Returns:
        Lower case, with separators folded to underscores.
    """
    return name.lower().replace("-", "_").replace(".", "_")


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


def test_no_production_module_outside_the_seam_names_the_transport() -> None:
    """**No production construction site exists**, which is what makes it inert.

    This check replaces one that asserted the seam's syntax tree held a single
    node. That pin was standing in for a property rather than being one: its own
    docstring gave the reason — a body "would be a shape for a later lane to fill
    in" — and the property it was buying was that the seam **transmits nothing**,
    which ADR-0017 §2 states and ADR-0147 §3 restates in a marked clause.

    Emptiness is one way to buy that and it is not the only one. What actually has
    to hold is that nothing a running system constructs can reach a socket, and
    the direct form of that is this: no module under ``src/ai_assistant`` other
    than the seam so much as *names* the transport, so nothing builds one, nothing
    imports one, and no composition root wires one. A lane that later wires it is
    the designating lane, and this test is what it has to come here and change.

    The scan reads names, so it shares :func:`_reached_names`'s blind spots — a
    ``getattr``, a name assembled at runtime. That is ADR-0017 §4's "net, not a
    proof" for the third time in this file, and it is stated rather than implied.
    """
    named = {
        "SmtpEgressTransport",
        "SmtpEndpoint",
        "OutboundEmail",
        "open_smtp_channel",
        "parse_smtp_endpoint",
    }
    offenders: dict[str, set[str]] = {}
    for path in sorted((_REPO_ROOT / "src" / "ai_assistant").rglob("*.py")):
        if path == _modules()[SEAM]:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = {
            node.id if isinstance(node, ast.Name) else node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Name | ast.Attribute)
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        if found & named:
            offenders[str(path.relative_to(_REPO_ROOT))] = found & named

    assert not offenders, (
        f"{offenders} name the egress transport. ADR-0017 §2 leaves the tools/ "
        f"boundary approved and undesignated and ADR-0147 §3 authorises no byte to "
        f"leave from tools/, so the transport is constructed nowhere in production. "
        f"The lane that wires it is the one a designating ADR licenses, and it "
        f"changes this test."
    )


def test_exactly_one_place_in_the_seam_opens_a_connection() -> None:
    """The boundary is pinnable only while there is one place to pin.

    Issue #66 asks for a name "precise enough for an import-linter contract to pin
    the module", and ADR-0147 §3's own argument for one module rather than a
    package is that a boundary growing with the code is one the contract stops
    describing. The same argument one level down: a seam with two socket sites has
    two places a policy can differ, which is #83's third bullet — "if each
    integration builds its own client, this is unenforceable by construction" —
    arriving inside the seam instead of outside it.
    """
    tree = ast.parse(_modules()[SEAM].read_text(encoding="utf-8"))
    opening = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(
            isinstance(inner, ast.Attribute) and inner.attr == "open_connection"
            for inner in ast.walk(node)
        )
    }

    assert opening == {"open_smtp_channel"}, (
        f"{sorted(opening)} open a connection. Exactly one function in the seam "
        f"does, so the pin has one place to live and a test has one place to "
        f"substitute (ADR-0147 §3, issue #83)."
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


async def test_no_registered_tool_can_reach_the_transport() -> None:
    """The other half of inertness: nothing an ``invoke`` can reach transmits.

    The static scan above says no module *names* the transport; this says the
    running system has no tool bound to a callable that could. ``send_email`` is
    the integration a designating ADR would register, and it is deliberately
    absent from the default registry *and* refuses when called — two independent
    reasons, which is what ``send_email.py``'s own docstring records.
    """
    registry = build_default_registry(memory=FakeMemoryStore())

    assert SEND_EMAIL_ID not in {tool.id for tool in await registry.all_tools()}
    with pytest.raises(UndesignatedSeamError):
        await SendEmail()({"to": ["someone@example.invalid"]}, idempotency_key=None)


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


def test_every_runtime_dependency_is_classified() -> None:
    """ADR-0147 §3's extension clause, as a check rather than as a hope.

    "The lane that adds any further transport-bearing dependency adds it to that
    enumeration in the same change" is a rule binding a lane, and a lane that never
    looks at the enumeration does not know it is bound. This is what makes it look:
    a dependency nobody classified fails here, and classifying it either extends the
    contract or records in `NOT_TRANSPORT_BEARING` why it need not.

    Subset rather than equality, because the closure is platform-dependent —
    `secretstorage` and `jeepney` are Linux-only and `pywin32_ctypes` is not.
    """
    unclassified = _runtime_closure() - TRANSPORT_BEARING - NOT_TRANSPORT_BEARING

    assert not unclassified, (
        f"{sorted(unclassified)} entered the runtime dependency closure without being "
        f"classified. Add each to TRANSPORT_BEARING — and to the contract's "
        f"forbidden_modules — or to NOT_TRANSPORT_BEARING with the reason."
    )


def test_the_contract_forbids_every_transport_bearing_dependency() -> None:
    """The classification above, joined to the contract it is supposed to drive."""
    forbidden = set(_contract()["forbidden_modules"])
    expected = {IMPORT_NAME.get(name, name) for name in TRANSPORT_BEARING & _runtime_closure()}

    assert expected <= forbidden, (
        f"the contract does not forbid {sorted(expected - forbidden)}, which this file "
        f"classifies as transport-bearing runtime dependencies"
    )


def test_every_forbidden_name_is_a_module_that_exists() -> None:
    """A misspelt entry is a silently inert one, which is the list's failure mode.

    ``import-linter`` only checks forbidden modules that are *in the graph*, and the
    graph holds an external package only once something imports it — so ``htpx`` in
    the list below would break nothing, fail nothing, and protect nothing. Resolving
    each name against the installed environment is what turns that into a failure.
    The two forward-looking entries are exempt by name rather than by pattern: they
    are listed precisely because they are not dependencies *yet*.
    """
    forbidden = set(_contract()["forbidden_modules"])
    missing = {
        name
        for name in forbidden - FORWARD_LOOKING
        if importlib.util.find_spec(name) is None  # pragma: no branch
    }

    assert not missing, (
        f"the contract forbids {sorted(missing)}, which resolve to nothing here. A "
        f"forbidden module absent from the graph is skipped, so a typo disarms the "
        f"entry silently; add it to FORWARD_LOOKING if the absence is deliberate."
    )


@pytest.mark.parametrize(
    "module", sorted(_modules().keys() - {SEAM}), ids=lambda name: name.rsplit(".", 1)[-1]
)
def test_no_other_tools_module_names_a_transport(module: str) -> None:
    """The rule, over source text, including the routes no import contract can name."""
    for name in _reached_names(_modules()[module].read_text(encoding="utf-8")):
        offending = _containing_packages(name) & FORBIDDEN_NAMES
        assert not offending, (
            f"{module} reaches {name!r}. ADR-0147 §3: no module under tools/ other "
            f"than {SEAM} opens a network connection or launches a subprocess, by any "
            f"route — and that seam is undesignated and transmits nothing."
        )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import socket", "socket"),
        ("import urllib.request", "urllib"),
        ("from http import client", "http"),
        ("import os\nos.system('x')", "os.system"),
        ("import os as _os\n_os.execvpe('x', [], {})", "os.execvpe"),
        ("import os.path\nos.spawnve('x', [], {})", "os.spawnve"),
        ("from os import execve", "os.execve"),
        ("import asyncio\nasyncio.create_subprocess_exec('x')", "asyncio.create_subprocess_exec"),
        ("from asyncio import create_subprocess_shell", "asyncio.create_subprocess_shell"),
        ("from asyncio import subprocess", "asyncio.subprocess"),
        ("def f():\n    import socket\n    return socket", "socket"),
    ],
    ids=lambda value: value if value.count("\n") == 0 and value.islower() else None,
)
def test_the_scanner_catches_each_form_a_launch_is_written_in(source: str, expected: str) -> None:
    """The net's own regression cases, one per shape the second round turned up.

    Standard-library names only: a third-party transport is the *contract's* to catch,
    including a lazy import inside a function body, which the graph records.

    Every launcher named here is one CPython defines on every platform, because the
    sets it is checked against are derived from the running interpreter — `spawnlpe`
    and the other `p` variants exist only where `os.spawnvp` does, so a case built on
    one would assert about the platform rather than about the scanner.
    """
    reached = {name for raw in _reached_names(source) for name in _containing_packages(raw)}

    assert expected in reached & FORBIDDEN_NAMES


@pytest.mark.parametrize(
    "source",
    [
        "import os\nos.path.join('a', 'b')",
        "import asyncio\nasyncio.timeout(1)",
        "import asyncio\nawait asyncio.sleep(1)",
        "from datetime import UTC",
    ],
)
def test_the_scanner_leaves_the_legitimate_neighbours_alone(source: str) -> None:
    """`os` and `asyncio` are not forbidden roots, and the timeout is ADR-0029 §4's."""
    reached = {name for raw in _reached_names(source) for name in _containing_packages(raw)}

    assert not reached & FORBIDDEN_NAMES
