"""The vendored speech models: their pins, their digests, and how a build gets them.

ADR-0200 §13 requires the speech lane to exercise each seam end to end "over the
real implementation, offline, with no credential read and no socket opened". A
model that is fetched on first use cannot satisfy that, so the two speech models
are **build inputs**, on ADR-0024's terms taken whole: each is pinned to an
immutable revision, every file is verified against a recorded SHA-256 at build
time, and the verified bytes are packaged into the wheel *and* the sdist. No
``ai_assistant`` runtime code fetches a speech artifact.

## Why this module duplicates ``embedding_artifact.py``'s mechanics

The hatchling build hook (``hatch_build.py``) loads both files **by path**,
before the package is installed and without importing ``ai_assistant`` at all —
that is what keeps one copy of the pins, the constants the build verifies against
being literally the constants the runtime resolves its paths from. The cost is
that neither file may import the other, or anything else from this project, at
import time; so the staging-and-verifying mechanics are written twice rather than
shared, and the failure type here is :class:`SpeechArtifactError` rather than an
``AssistantError``. The alternative — one module holding both subjects — was
rejected because ADR-0024 owns ``embedding_artifact.py`` and its constants are
about an *embedding space*, whose identity feeds ``model_id`` and whose drift
forces a re-embedding. Nothing of that is true of a speech model, and folding the
two together would put a re-embedding trigger next to weights that cannot cause
one.

``huggingface_hub`` is imported inside :func:`hf_download` and nowhere else, so
importing this module never pulls a network client into a runtime process.

## Two artifacts, not one, and the same rules for each

Each :class:`SpeechArtifact` below is a whole vendored directory: a repository, a
commit, and the SHA-256 of every file as shipped.

**The digests live in a JSON file beside this one rather than in it**, which is
where this module departs from ``embedding_artifact.py`` and why. That artifact
is five files and its manifest reads as five lines of a decision. One of these is
**361** — a phoneme model plus the pronunciation data its grapheme-to-phoneme pass
needs — and 361 lines of hex inlined here would bury the pins, the reasoning and
the acquisition seam under data nobody reads. Nothing is weakened by the move: the
manifests are checked into git like any other source, they are read from a path
derived from this file's own location, and every file in a destination is still
re-hashed against them. What changes is only where the bytes are written down.

:func:`ensure_artifact`
downloads only what is missing, into a temporary directory that is moved into
place only once every file matches the manifest, and then re-hashes **every** file
in the destination — because an sdist or a stale staging directory can carry a
corrupted file that no download would ever replace. Presence is not trust
(ADR-0024 §5).
"""

from __future__ import annotations

import functools
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Directory inside this package that every vendored artifact is staged under —
#: the embedding model's and both speech models' alike.
VENDOR_DIRECTORY_NAME = "_vendor"

#: Directory beside this module holding one JSON manifest per artifact, named for
#: the artifact's vendored directory. Checked into version control, unlike the
#: artifacts themselves.
MANIFEST_DIRECTORY_NAME = "speech_manifests"

_READ_CHUNK = 1 << 20

#: How many hex characters of the manifest digest go into an artifact's id. The
#: same figure ``embedding_artifact.py`` uses, for the same reason: long enough
#: that a collision is not a real failure mode, short enough to stay readable.
_DIGEST_PREFIX = 16


class SpeechArtifactError(Exception):
    """A vendored speech artifact is missing, unverifiable, or does not match its pin.

    Deliberately **not** an ``AssistantError``: this module is loaded by path from
    the build hook, before ``ai_assistant`` is importable, so it cannot reach
    ``ai_assistant.core.errors``. It never escapes to a caller of either speech
    contract either — the implementations in this package translate it into a
    ``SpeechError`` at their seam, which is where a caller's ``except
    SpeechError`` has to be sufficient (ADR-0200 §1).
    """


@dataclass(frozen=True)
class SpeechArtifact:
    """One vendored model directory, pinned to the exact bytes shipped.

    Attributes:
        directory_name: What the directory is called under ``_vendor/``, and the
            stem of the JSON manifest that records its digests.
        repo_id: The Hugging Face repository the files come from.
        revision: The immutable commit they are pinned to, so that a moved
            default branch does not change what a build produces.
    """

    directory_name: str
    repo_id: str
    revision: str

    @property
    def manifest(self) -> Mapping[str, str]:
        """Every file shipped from ``repo_id``, mapped to the SHA-256 of its bytes.

        The *bytes*, not the revision: a re-pin that changes them changes what
        runs, and the check is against these rather than against the commit.

        Returns:
            File name relative to the artifact directory, to lowercase hex digest.

        Raises:
            SpeechArtifactError: If the manifest file is missing or unreadable.
        """
        return _manifest_of(self.directory_name)


@functools.cache
def _manifest_of(directory_name: str) -> Mapping[str, str]:
    """Read one artifact's recorded digests, cached for the process's lifetime.

    Cached because both the build hook and every verification read it, and the
    file cannot change under a running process in any way that a re-read would
    legitimately pick up: it is source, not state.

    Args:
        directory_name: The artifact's vendored directory name.

    Returns:
        The recorded manifest, read-only.

    Raises:
        SpeechArtifactError: If the manifest is missing, unreadable, or is not a
            JSON object of strings.
    """
    path = Path(__file__).resolve().parent / MANIFEST_DIRECTORY_NAME / f"{directory_name}.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = f"could not read the recorded manifest for {directory_name!r} from {path}"
        raise SpeechArtifactError(msg) from exc
    if not isinstance(document, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in document.items()
    ):
        msg = f"the recorded manifest for {directory_name!r} is not an object of strings"
        raise SpeechArtifactError(msg)
    return MappingProxyType(dict(document))


#: The speech-recognition model. Moonshine tiny (English), int8-quantised, in the
#: four-file layout its runtime expects. Chosen for a push-to-talk rung because it
#: consumes a **variable-length** recording rather than padding every clip to a
#: fixed window, and returns cased, punctuated text — which is what makes a
#: transcript worth showing back to the person who spoke it (ADR-0200 §4).
MOONSHINE_TINY_EN_INT8 = SpeechArtifact(
    directory_name="moonshine-tiny-en-int8",
    repo_id="csukuangfj/sherpa-onnx-moonshine-tiny-en-int8",
    revision="bf2b762c076d8ea61e2af0b3851c9564fb77552e",
)

#: The speech-synthesis model. A Piper VITS voice, with the espeak-ng data its
#: grapheme-to-phoneme pass reads.
#:
#: **The phoneme voice was chosen over the lexicon voice on a measurement, and the
#: measurement is the reason this artifact is 361 files.** The obvious cheaper
#: candidate — a VITS model driven from a CMU pronunciation lexicon, three files
#: and no phoneme data — silently **drops every word the lexicon does not
#: contain**: "you have a meeting with Sam at 3pm" renders without "3pm", and an
#: unknown name renders without the name. ADR-0200 §4 makes it this seam's
#: obligation that the audio is an audible rendering *of the text*, and a
#: synthesizer that omits the time from an appointment does not discharge it —
#: for a personal assistant the out-of-vocabulary words are precisely the names,
#: numbers and abbreviations the answer is about. The phoneme voice renders all
#: three test phrases whole, and does it about seventeen times faster.
VITS_PIPER_EN_US_AMY_LOW = SpeechArtifact(
    directory_name="vits-piper-en_US-amy-low",
    repo_id="csukuangfj/vits-piper-en_US-amy-low",
    revision="76da6ca287517a49f58b943c4c4fdb0c1e94d61f",
)

#: Every speech artifact this distribution ships. The build hook iterates this, so
#: adding a third model is a constant here and no change to the hook.
SPEECH_ARTIFACTS: tuple[SpeechArtifact, ...] = (MOONSHINE_TINY_EN_INT8, VITS_PIPER_EN_US_AMY_LOW)


class Download(Protocol):
    """Fetch one file of the pinned revision into ``destination``.

    The acquisition seam ADR-0024 §4 keeps inside ``models/``. The build hook
    calls it; a test substitutes a recorder, so "the build requested the
    *recorded commit*" is an assertion rather than a hope.
    """

    def __call__(self, *, repo_id: str, filename: str, revision: str, destination: Path) -> None:
        """Write ``filename`` at ``revision`` from ``repo_id`` to ``destination``."""
        ...


def hf_download(*, repo_id: str, filename: str, revision: str, destination: Path) -> None:
    """Download one pinned file from the Hugging Face Hub.

    The only egress in this module, and it runs at build time only. The import is
    function-local so that importing this module — which every runtime path does —
    never loads a network client.

    Args:
        repo_id: The Hugging Face repository.
        filename: The file to fetch.
        revision: The immutable commit to fetch it at.
        destination: The path to write the bytes to.

    Raises:
        SpeechArtifactError: If the download fails for any reason.
    """
    from huggingface_hub import hf_hub_download  # noqa: PLC0415  # build-time only, by design

    try:
        cached = hf_hub_download(repo_id=repo_id, filename=filename, revision=revision)
        shutil.copyfile(cached, destination)
    except Exception as exc:  # every failure is the same failure here
        msg = f"could not download {filename!r} from {repo_id!r} at {revision}"
        raise SpeechArtifactError(msg) from exc


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


def manifest_digest(artifact: SpeechArtifact) -> str:
    """Return a deterministic digest over one artifact's recorded manifest.

    The identity of *the bytes shipped* rather than of the revision, which is a
    separate constant that can drift from the digests recorded alongside it.

    Args:
        artifact: The artifact to digest.

    Returns:
        The lowercase hex digest of the canonicalised manifest.
    """
    canonical = "".join(
        f"{name}\0{artifact.manifest[name]}\n" for name in sorted(artifact.manifest)
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def artifact_id(artifact: SpeechArtifact) -> str:
    """Return a stable identifier for the exact weights an artifact ships.

    Not an embedding-space identity and deliberately not shaped like one: nothing
    downstream is invalidated when speech weights are re-pinned, so this folds in
    no library versions and triggers no migration. It exists so that an operator
    reading a log or a test asserting "this is the model that ran" names bytes
    rather than a directory.

    Args:
        artifact: The artifact to identify.

    Returns:
        An identifier of the form ``name@<manifest digest prefix>``.
    """
    return f"{artifact.directory_name}@{manifest_digest(artifact)[:_DIGEST_PREFIX]}"


def packaged_artifact_dir(artifact: SpeechArtifact) -> Path:
    """Return the directory an artifact is loaded from at runtime.

    A function rather than a constant so the build hook can derive the packaged
    destination from it — the path the build writes to and the path the
    implementation reads from are the same expression, not two that have to be
    kept in step.

    Args:
        artifact: The artifact whose directory is wanted.

    Returns:
        The vendored directory inside this package.
    """
    return Path(__file__).resolve().parent / VENDOR_DIRECTORY_NAME / artifact.directory_name


def missing_files(artifact: SpeechArtifact, directory: Path) -> list[str]:
    """Return the manifest entries absent from ``directory``, sorted.

    Args:
        artifact: The artifact whose manifest to check against.
        directory: The directory to inspect.

    Returns:
        The names of the missing files.
    """
    return sorted(name for name in artifact.manifest if not (directory / name).is_file())


def verify_artifact(artifact: SpeechArtifact, directory: Path) -> None:
    """Re-hash every manifest file in ``directory`` and reject any that differs.

    Presence is not trust (ADR-0024 §5): a file already staged, or one unpacked
    from an sdist, is hashed here exactly as a freshly downloaded one is.

    Args:
        artifact: The artifact whose manifest to verify against.
        directory: The directory holding the artifact.

    Raises:
        SpeechArtifactError: If a file is missing, unreadable, or its digest does
            not match the recorded manifest.
    """
    for name in sorted(artifact.manifest):
        path = directory / name
        if not path.is_file():
            msg = (
                f"speech artifact {artifact.directory_name!r} is incomplete: "
                f"{name!r} is missing from {directory}"
            )
            raise SpeechArtifactError(msg)
        try:
            actual = sha256_of(path)
        except OSError as exc:
            msg = f"could not read speech artifact file {path}"
            raise SpeechArtifactError(msg) from exc
        expected = artifact.manifest[name]
        if actual != expected:
            msg = (
                f"speech artifact file {name!r} does not match its recorded digest: "
                f"expected {expected}, got {actual}"
            )
            raise SpeechArtifactError(msg)


def ensure_artifact(
    artifact: SpeechArtifact, directory: Path, *, download: Download = hf_download
) -> None:
    """Make ``directory`` hold the verified artifact, fetching only what is absent.

    Build-time only. Missing files are downloaded at the artifact's pinned
    revision into a temporary directory and verified there; only a fully matching
    set is moved into place, so a digest mismatch leaves nothing staged. Every
    file in the destination is then re-hashed, so an already-present but corrupted
    file fails the build rather than being shipped.

    Args:
        artifact: The artifact to acquire.
        directory: Where it must end up.
        download: The acquisition seam. Substituted in tests.

    Raises:
        SpeechArtifactError: If a download fails, or if any file does not match
            the recorded manifest.
    """
    absent = missing_files(artifact, directory)
    if absent:
        _stage(artifact, directory, absent, download)
    verify_artifact(artifact, directory)


def _stage(artifact: SpeechArtifact, directory: Path, names: list[str], download: Download) -> None:
    """Download ``names``, verify them in isolation, then move them into place."""
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ai-assistant-speech-artifact-") as staging:
        staged = Path(staging)
        for name in names:
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            download(
                repo_id=artifact.repo_id,
                filename=name,
                revision=artifact.revision,
                destination=target,
            )
            if not target.is_file():
                msg = f"the acquisition seam did not produce {name!r}"
                raise SpeechArtifactError(msg)
            actual = sha256_of(target)
            expected = artifact.manifest[name]
            if actual != expected:
                msg = (
                    f"downloaded {name!r} does not match its recorded digest: "
                    f"expected {expected}, got {actual}"
                )
                raise SpeechArtifactError(msg)
        for name in names:
            destination = directory / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged / name), str(destination))
