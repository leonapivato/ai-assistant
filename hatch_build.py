"""Hatchling build hook: acquire and verify the vendored models.

ADR-0024 §4. The embedding model is a build input, so *the build* fetches it —
pinned to an immutable revision, verified against the recorded SHA-256 manifest,
and packaged into the wheel and the sdist alike. This file is the "thin
build-time adapter" the ADR describes; every decision it enforces lives in
``src/ai_assistant/models/embedding_artifact.py``, which it loads **by path**
because ``ai_assistant`` is not importable while its own distribution is being
built. One copy of the pins, two callers.

Since ADR-0200 the two **speech** models are build inputs on the same terms and
for a reason of their own: ADR-0200 §13 requires each speech seam exercised end to
end "offline, with no credential read and no socket opened", which a model fetched
on first use cannot satisfy. Their pins live in
``src/ai_assistant/models/speech_artifact.py``, loaded by path for the same reason
and iterated rather than named here, so a third speech model is a constant there
and no change to this file.

Only the trigger moved. Acquisition stays owned by ``models/``, which is why
``huggingface_hub`` is reached through those modules' seams rather than imported
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
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

if TYPE_CHECKING:
    from types import ModuleType

#: Path of the embedding pins/acquisition module, relative to the project root.
_ARTIFACT_MODULE = Path("src") / "ai_assistant" / "models" / "embedding_artifact.py"

#: Path of the speech pins/acquisition module, relative to the project root.
_SPEECH_ARTIFACT_MODULE = Path("src") / "ai_assistant" / "models" / "speech_artifact.py"

#: Where the package root sits inside each build target's output.
_PACKAGE_ROOT_IN_TARGET = {"wheel": Path("ai_assistant"), "sdist": Path("src") / "ai_assistant"}


def _load_module(path: Path, name: str) -> ModuleType:
    """Import a pins module from source, without importing ``ai_assistant``.

    Args:
        path: The module file to load.
        name: The name to load it under, unique per module so two pins modules
            do not displace one another in ``sys.modules``.

    Returns:
        The loaded module.

    Raises:
        RuntimeError: If the module cannot be loaded from ``path``.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        msg = f"could not load the artifact pins from {path}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    # Registered before execution, which is importlib's own recipe for loading a
    # module by path and not decoration: `dataclasses` resolves a field's type by
    # looking its class's module up in `sys.modules`, so a pins module holding a
    # dataclass fails at import without this. Under a private name, so nothing a
    # build imports normally can be displaced by it.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ModelArtifactHook(BuildHookInterface[Any]):
    """Stage every verified model artifact and include it in the build."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Acquire, verify and force-include every artifact for the current target.

        Args:
            version: ``"standard"`` or ``"editable"``.
            build_data: Hatchling's mutable build description.

        Raises:
            RuntimeError: If this hook is asked to build an unknown target.
        """
        root = Path(self.root).resolve()
        embedding = _load_module(root / _ARTIFACT_MODULE, "_ai_assistant_embedding_artifact")
        speech = _load_module(root / _SPEECH_ARTIFACT_MODULE, "_ai_assistant_speech_artifact")

        # Derived from each runtime accessor, not restated: the directory the
        # build writes is by construction the directory the implementation reads,
        # so "packages the wrong path" is not expressible here.
        #
        # Acquire-and-verify runs for *every* build, editable included: it is
        # what makes `uv sync` leave a working tree that can embed and speak
        # offline.
        sources: list[Path] = [embedding.packaged_artifact_dir()]
        embedding.ensure_artifact(sources[0])
        for artifact in speech.SPEECH_ARTIFACTS:
            directory: Path = speech.packaged_artifact_dir(artifact)
            speech.ensure_artifact(artifact, directory)
            sources.append(directory)

        if version == "editable":
            # An editable install already resolves `ai_assistant` to the source
            # tree, where the artifacts now are. Copying them into site-packages
            # as well would duplicate hundreds of megabytes in every developer's
            # environment for no benefit — and ADR-0015 gives every agent its own
            # clone.
            return

        package_root = _PACKAGE_ROOT_IN_TARGET.get(self.target_name)
        if package_root is None:
            msg = f"the model artifact hook does not know target {self.target_name!r}"
            raise RuntimeError(msg)
        force_include: dict[str, str] = build_data.setdefault("force_include", {})
        for source in sources:
            relative = source.relative_to(root / "src" / "ai_assistant")
            force_include[str(source)] = str(package_root / relative)
