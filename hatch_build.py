"""Hatchling build hook: acquire and verify the vendored embedding model.

ADR-0024 §4. The embedding model is a build input, so *the build* fetches it —
pinned to an immutable revision, verified against the recorded SHA-256 manifest,
and packaged into the wheel and the sdist alike. This file is the "thin
build-time adapter" the ADR describes; every decision it enforces lives in
``src/ai_assistant/models/embedding_artifact.py``, which it loads **by path**
because ``ai_assistant`` is not importable while its own distribution is being
built. One copy of the pins, two callers.

Only the trigger moved. Acquisition stays owned by ``models/``, which is why
``huggingface_hub`` is reached through that module's seam rather than imported
here.

The staged directory is deliberately outside version control (§4), so the two
build targets are told about it explicitly:

- the **wheel** gets it at ``ai_assistant/models/_vendor/...``;
- the **sdist** gets it at ``src/ai_assistant/models/_vendor/...``, so a
  ``--no-binary`` build from the sdist finds the artifact already present,
  verifies it, and fetches nothing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

if TYPE_CHECKING:
    from types import ModuleType

#: Path of the pins/acquisition module, relative to the project root.
_ARTIFACT_MODULE = Path("src") / "ai_assistant" / "models" / "embedding_artifact.py"

#: Where the package root sits inside each build target's output.
_PACKAGE_ROOT_IN_TARGET = {"wheel": Path("ai_assistant"), "sdist": Path("src") / "ai_assistant"}


def _load_artifact_module(root: Path) -> ModuleType:
    """Import the pins module from source, without importing ``ai_assistant``.

    Args:
        root: The project root being built.

    Returns:
        The loaded module.

    Raises:
        RuntimeError: If the module cannot be loaded from ``root``.
    """
    path = root / _ARTIFACT_MODULE
    spec = importlib.util.spec_from_file_location("_ai_assistant_embedding_artifact", path)
    if spec is None or spec.loader is None:
        msg = f"could not load the embedding artifact pins from {path}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EmbeddingArtifactHook(BuildHookInterface[Any]):
    """Stage the verified embedding model and include it in the build."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Acquire, verify and force-include the artifact for the current target.

        Args:
            version: ``"standard"`` or ``"editable"``.
            build_data: Hatchling's mutable build description.

        Raises:
            RuntimeError: If this hook is asked to build an unknown target.
        """
        root = Path(self.root).resolve()
        artifact = _load_artifact_module(root)

        # Derived from the runtime accessor, not restated: the directory the
        # build writes is by construction the directory the embedder reads, so
        # "packages the wrong path" is not expressible here.
        source: Path = artifact.packaged_artifact_dir()
        relative = source.relative_to(root / "src" / "ai_assistant")

        # Acquire-and-verify runs for *every* build, editable included: it is
        # what makes `uv sync` leave a working tree that can embed offline.
        artifact.ensure_artifact(source)

        if version == "editable":
            # An editable install already resolves `ai_assistant` to the source
            # tree, where the artifact now is. Copying 58 MiB into site-packages
            # as well would duplicate it in every developer's environment for no
            # benefit — and ADR-0015 gives every agent its own clone.
            return

        package_root = _PACKAGE_ROOT_IN_TARGET.get(self.target_name)
        if package_root is None:
            msg = f"the embedding artifact hook does not know target {self.target_name!r}"
            raise RuntimeError(msg)
        force_include: dict[str, str] = build_data.setdefault("force_include", {})
        force_include[str(source)] = str(package_root / relative)
