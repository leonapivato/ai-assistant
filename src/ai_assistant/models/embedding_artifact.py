"""The vendored embedding model: its pins, its digests, and how a build gets it.

ADR-0024 makes the on-device embedding model a **build input**. No
``ai_assistant`` runtime code fetches a model artifact: the artifact is pinned to
an immutable revision, every file is verified against a recorded SHA-256 at build
time, and the verified bytes are packaged into the wheel *and* the sdist. This
module holds that decision — the pins (§2), the acquisition seam (§4), and the
identity ``FastEmbedEmbedder.model_id`` reports (§2).

## Why this module imports nothing from ``ai_assistant``

The hatchling build hook (``hatch_build.py``) loads this file **by path**, before
the package is installed and without importing ``ai_assistant`` at all. That is
what keeps one copy of the pins: the constants the build verifies against are
literally the constants the runtime resolves its identity from. The cost is that
this module may use only the standard library at import time, so its failure type
is :class:`ArtifactError` rather than an ``AssistantError`` — see its docstring.
``huggingface_hub`` is imported inside :func:`hf_download` and nowhere else, so
importing this module never pulls a network client into a runtime process.

## Acquisition, and why presence is not trust

:func:`ensure_artifact` is the whole of the build-time contract. It downloads
only what is missing, into a temporary directory that is moved into place only
once every file matches the manifest — a mismatch therefore fails the build
leaving nothing staged. It then re-hashes **every** file in the destination,
including files that were already there, because an sdist or a stale staging
directory can carry a corrupted file that no download would ever replace.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import shutil
import tempfile
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The one fastembed model this product ships. ADR-0024 §6: there is one build
#: input, not a family, so ``FastEmbedEmbedder`` serves only this name.
VENDORED_MODEL_NAME = "BAAI/bge-small-en-v1.5"

#: The Hugging Face repository fastembed sources that model's ONNX export from.
ARTIFACT_REPO_ID = "qdrant/bge-small-en-v1.5-onnx-q"

#: The immutable commit the artifact is pinned to. A moved default branch does
#: not change what a build produces (ADR-0024 §2).
ARTIFACT_REVISION = "52398278842ec682c6f32300af41344b1c0b0bb2"

#: Directory name the artifact is vendored under, inside this package.
VENDOR_DIRECTORY_NAME = "bge-small-en-v1.5"

#: Every file fastembed requests for the vendored model, mapped to the SHA-256 of
#: the exact bytes this product ships. These are the *actual bytes*, not the
#: revision: a re-pin that changes them must move ``model_id`` (ADR-0024 §2).
ARTIFACT_MANIFEST: Mapping[str, str] = MappingProxyType(
    {
        "config.json": "13582bcf2effc85b7bf3d3f5532e686bc1c9ce86bb009d10f0ec33cbe92299dd",
        "model_optimized.onnx": (
            "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431"
        ),
        "special_tokens_map.json": (
            "5d5b662e421ea9fac075174bb0688ee0d9431699900b90662acd44b2a350503a"
        ),
        "tokenizer.json": "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
        "tokenizer_config.json": "0b29c7bfc889e53b36d9dd3e686dd4300f6525110eaa98c76a5dafceb2029f53",
    }
)

#: The behaviour-affecting stack ADR-0024 §3 audits and exact-pins: fastembed
#: (pooling and the on-disk layout), tokenizers (preprocessing), onnxruntime
#: (inference kernels) and numpy (the normalisation of this model's output).
#: Pinning prevents drift *within* a release; feeding these versions into
#: ``model_id`` detects it *across* one.
AUDITED_PACKAGES: tuple[str, ...] = ("fastembed", "numpy", "onnxruntime", "tokenizers")

#: The ONNX execution provider, pinned to CPU (ADR-0024 §3). ``Device.AUTO``
#: would let the same store's embedding space shift the moment the machine gains
#: a GPU, which is exactly the silent same-id/different-vectors corruption
#: ``model_id`` exists to prevent.
EXECUTION_PROVIDERS: tuple[str, ...] = ("CPUExecutionProvider",)

#: How many hex characters of each digest go into ``model_id``. 64 bits per
#: component: long enough that a collision is not a real failure mode, short
#: enough that the identifier stays readable in a store's metadata column.
_DIGEST_PREFIX = 16

_READ_CHUNK = 1 << 20


class ArtifactError(Exception):
    """The vendored artifact is missing, unverifiable, or does not match its pin.

    Deliberately **not** an ``AssistantError``: this module is loaded by path
    from the build hook, before ``ai_assistant`` is importable, so it cannot
    reach ``ai_assistant.core.errors``. It never escapes to a caller of the
    ``Embedder`` contract either — ``FastEmbedEmbedder`` translates it into
    ``ModelError`` at the seam, which is where a caller's ``except ModelError``
    has to be sufficient.
    """


class Download(Protocol):
    """Fetch one file of the pinned revision into ``destination``.

    The seam ADR-0024 §4 keeps inside ``models/``. The build hook calls it; a
    test substitutes a recorder so "the build requested the *recorded commit*"
    is an assertion rather than a hope.
    """

    def __call__(self, *, repo_id: str, filename: str, revision: str, destination: Path) -> None:
        """Write ``filename`` at ``revision`` from ``repo_id`` to ``destination``."""
        ...


def hf_download(*, repo_id: str, filename: str, revision: str, destination: Path) -> None:
    """Download one pinned file from the Hugging Face Hub.

    The only egress in this module, and it runs at build time only. The import is
    function-local so that importing this module — which every runtime path
    does — never loads a network client.

    Args:
        repo_id: The Hugging Face repository.
        filename: The file to fetch.
        revision: The immutable commit to fetch it at.
        destination: The path to write the bytes to.

    Raises:
        ArtifactError: If the download fails for any reason.
    """
    from huggingface_hub import hf_hub_download  # noqa: PLC0415  # build-time only, by design

    try:
        cached = hf_hub_download(repo_id=repo_id, filename=filename, revision=revision)
        shutil.copyfile(cached, destination)
    except Exception as exc:  # every failure is the same failure here
        msg = f"could not download {filename!r} from {repo_id!r} at {revision}"
        raise ArtifactError(msg) from exc


def sha256_of(path: Path) -> str:
    """Return the hex SHA-256 of a file, read incrementally.

    Args:
        path: The file to hash.

    Returns:
        The lowercase hex digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_digest() -> str:
    """Return a deterministic digest over the recorded SHA-256 manifest.

    This is the identity of *the bytes shipped*, which is what ADR-0024 §2
    requires ``model_id`` to carry — not :data:`ARTIFACT_REVISION`, a separate
    constant that can drift from the digests it was recorded alongside.

    Returns:
        The lowercase hex digest of the canonicalised manifest.
    """
    canonical = "".join(
        f"{name}\0{ARTIFACT_MANIFEST[name]}\n" for name in sorted(ARTIFACT_MANIFEST)
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def stack_digest(versions: Mapping[str, str]) -> str:
    """Return a deterministic digest over the audited behaviour-affecting versions.

    Args:
        versions: Package name to version, for every name in
            :data:`AUDITED_PACKAGES`.

    Returns:
        The lowercase hex digest of the canonicalised versions.

    Raises:
        ArtifactError: If any audited package is missing from ``versions``.
    """
    missing = [name for name in AUDITED_PACKAGES if name not in versions]
    if missing:
        msg = f"no version recorded for audited package(s): {', '.join(sorted(missing))}"
        raise ArtifactError(msg)
    canonical = "".join(f"{name}\0{versions[name]}\n" for name in sorted(AUDITED_PACKAGES))
    return hashlib.sha256(canonical.encode()).hexdigest()


def installed_audited_versions() -> dict[str, str]:
    """Return the installed version of every audited package.

    Read from installed metadata rather than restated as constants, so the
    identity reflects the stack that will actually run — which is the point of
    ADR-0024 §2's "advancing across installs *and* across a store's upgrade".

    Returns:
        Package name to installed version.

    Raises:
        ArtifactError: If an audited package is not installed.
    """
    versions: dict[str, str] = {}
    for name in AUDITED_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            msg = f"audited package {name!r} is not installed"
            raise ArtifactError(msg) from exc
    return versions


def embedding_space_id(versions: Mapping[str, str] | None = None) -> str:
    """Return the identifier of the embedding space the vendored model defines.

    Three components, each of which must be able to move it on its own
    (ADR-0024 §2): the model name, a digest over the shipped bytes, and a digest
    over the audited behaviour-affecting versions. A store tags its vectors with
    this, so re-pinned weights or an upgraded stack are detected as "re-embedding
    is required" instead of silently ranking old vectors against new queries.

    Args:
        versions: The audited versions to fold in. Defaults to the installed
            ones; a test passes its own to prove independence.

    Returns:
        A stable identifier of the form ``name@<manifest>+<stack>``.

    Raises:
        ArtifactError: If an audited version cannot be determined.
    """
    resolved = installed_audited_versions() if versions is None else versions
    manifest = manifest_digest()[:_DIGEST_PREFIX]
    stack = stack_digest(resolved)[:_DIGEST_PREFIX]
    return f"{VENDORED_MODEL_NAME}@{manifest}+{stack}"


def packaged_artifact_dir() -> Path:
    """Return the directory the packaged artifact is loaded from at runtime.

    A function rather than a constant so the build hook can derive the packaged
    destination from it — the path the build writes to and the path the runtime
    reads from are the same expression, not two that have to be kept in step.

    Returns:
        The vendored model directory inside this package.
    """
    return Path(__file__).resolve().parent / "_vendor" / VENDOR_DIRECTORY_NAME


def missing_files(directory: Path) -> list[str]:
    """Return the manifest entries that are absent from ``directory``, sorted.

    Args:
        directory: The directory to inspect.

    Returns:
        The names of the missing files.
    """
    return sorted(name for name in ARTIFACT_MANIFEST if not (directory / name).is_file())


def verify_artifact(directory: Path) -> None:
    """Re-hash every manifest file in ``directory`` and reject any that differs.

    Presence is not trust (ADR-0024 §5): a file already staged, or one unpacked
    from an sdist, is hashed here exactly as a freshly downloaded one is.

    Args:
        directory: The directory holding the artifact.

    Raises:
        ArtifactError: If a file is missing, unreadable, or its digest does not
            match the recorded manifest.
    """
    for name in sorted(ARTIFACT_MANIFEST):
        path = directory / name
        if not path.is_file():
            msg = f"embedding model artifact is incomplete: {name!r} is missing from {directory}"
            raise ArtifactError(msg)
        try:
            actual = sha256_of(path)
        except OSError as exc:
            msg = f"could not read embedding model artifact file {path}"
            raise ArtifactError(msg) from exc
        expected = ARTIFACT_MANIFEST[name]
        if actual != expected:
            msg = (
                f"embedding model artifact file {name!r} does not match its recorded "
                f"digest: expected {expected}, got {actual}"
            )
            raise ArtifactError(msg)


def ensure_artifact(directory: Path, *, download: Download = hf_download) -> None:
    """Make ``directory`` hold the verified artifact, fetching only what is absent.

    Build-time only. Missing files are downloaded at :data:`ARTIFACT_REVISION`
    into a temporary directory and verified there; only a fully matching set is
    moved into place, so a digest mismatch leaves nothing staged. Every file in
    the destination is then re-hashed, so an already-present but corrupted file
    fails the build rather than being shipped.

    Args:
        directory: Where the artifact must end up.
        download: The acquisition seam. Substituted in tests.

    Raises:
        ArtifactError: If a download fails, or if any file does not match the
            recorded manifest.
    """
    absent = missing_files(directory)
    if absent:
        _stage(directory, absent, download)
    verify_artifact(directory)


def _stage(directory: Path, names: list[str], download: Download) -> None:
    """Download ``names``, verify them in isolation, then move them into place."""
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ai-assistant-artifact-") as staging:
        staged = Path(staging)
        for name in names:
            target = staged / name
            download(
                repo_id=ARTIFACT_REPO_ID,
                filename=name,
                revision=ARTIFACT_REVISION,
                destination=target,
            )
            if not target.is_file():
                msg = f"the acquisition seam did not produce {name!r}"
                raise ArtifactError(msg)
            actual = sha256_of(target)
            expected = ARTIFACT_MANIFEST[name]
            if actual != expected:
                msg = (
                    f"downloaded {name!r} does not match its recorded digest: "
                    f"expected {expected}, got {actual}"
                )
                raise ArtifactError(msg)
        for name in names:
            shutil.move(str(staged / name), str(directory / name))
