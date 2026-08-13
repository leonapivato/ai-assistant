"""Golden rule 4, held on a tree `lint-imports` cannot see.

`[tool.importlinter] root_package = "ai_assistant"` builds its graph from that
package alone, so no contract constrains what `benchmarks/` imports. Extending
`root_packages` does not work: `uv run lint-imports` is a console script whose
`sys.path[0]` is the venv's `bin/`, so `benchmarks` is not importable there, and the
fix would have to be in the CI workflow. This is the same rule by a different
mechanism, and it runs under bare `pytest` wherever the suite runs.

It parses rather than imports, so a module that would raise on import is still
checked, and a lazily-imported provider SDK is still caught.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BENCHMARKS = Path(__file__).resolve().parent.parent.parent / "benchmarks"

#: The provider SDKs and vendor stacks golden rule 4 confines to `models/`, plus the
#: keyring ADR-0125 §8 confines to `secret_store`. Copied from the `provider SDKs are
#: confined to the models layer` contract in `pyproject.toml`; `test_forbidden_list_
#: matches_the_contract` below keeps the two in step.
FORBIDDEN_EXTERNAL = frozenset(
    {
        "pydantic_ai",
        "anthropic",
        "openai",
        "tiktoken",
        "fastembed",
        "huggingface_hub",
        "onnxruntime",
        "tokenizers",
        "keyring",
    }
)

#: Test-only doubles. Production code importing them fails `lint-imports` inside the
#: package; the harness is production-shaped tooling and the same ban applies to it,
#: because a benchmark that silently ran against `FakeMemoryStore` would report
#: numbers about nothing. The harness's own *tests* import them freely — this check
#: covers `benchmarks/`, not `tests/`.
FORBIDDEN_INTERNAL = frozenset({"ai_assistant.testing"})


def _modules() -> list[Path]:
    """Every Python module in the harness tree.

    Returns:
        The paths, sorted so a failure names the same file every run.
    """
    return sorted(BENCHMARKS.rglob("*.py"))


def _imported_roots(source: str) -> set[str]:
    """Every module name imported by ``source``, at any depth and any scope.

    Args:
        source: The module's text.

    Returns:
        Dotted names, as written.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            found.add(node.module)
    return found


def test_the_tree_has_modules_to_check() -> None:
    """A check that silently covers nothing is worse than no check."""
    assert len(_modules()) >= 10


@pytest.mark.parametrize("module", _modules(), ids=lambda path: path.name)
def test_no_module_imports_a_provider_sdk(module: Path) -> None:
    """Golden rule 4: no provider SDK outside `models/`, harness included."""
    for name in _imported_roots(module.read_text(encoding="utf-8")):
        root = name.split(".")[0]
        assert root not in FORBIDDEN_EXTERNAL, (
            f"{module.name} imports {name!r}. The harness reaches models through the "
            f"`ModelProvider` seam and embeddings through `Embedder`, never a vendor SDK."
        )


@pytest.mark.parametrize("module", _modules(), ids=lambda path: path.name)
def test_no_module_imports_the_testing_doubles(module: Path) -> None:
    """The canonical fakes stand in for real subsystems and must not be measured."""
    for name in _imported_roots(module.read_text(encoding="utf-8")):
        assert not any(
            name == banned or name.startswith(f"{banned}.") for banned in FORBIDDEN_INTERNAL
        ), (
            f"{module.name} imports {name!r}. A benchmark run against a test double "
            f"reports numbers about the double."
        )


def test_forbidden_list_matches_the_contract() -> None:
    """The copied list is the one `pyproject.toml` enforces inside the package.

    Read out of the file rather than out of an import, because `import-linter` offers
    no API for "what does this contract forbid" and the point is to notice the day
    somebody adds a vendor to the contract and not to this list.
    """
    text = (BENCHMARKS.parent / "pyproject.toml").read_text(encoding="utf-8")
    start = text.index('name = "provider SDKs are confined to the models layer"')
    block = text[start : text.index("[[tool.importlinter.contracts]]", start)]
    listed = {line.strip().strip('",') for line in block.splitlines() if line.startswith('    "')}
    declared = {name for name in listed if not name.startswith("ai_assistant")}
    assert declared <= FORBIDDEN_EXTERNAL, (
        f"the provider-SDK contract forbids {sorted(declared - FORBIDDEN_EXTERNAL)}, which "
        f"this check does not; add them to FORBIDDEN_EXTERNAL"
    )
