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

:func:`ensure_artifact`
downloads only what is missing, into a temporary directory that is moved into
place only once every file matches the manifest, and then re-hashes **every** file
in the destination — because an sdist or a stale staging directory can carry a
corrupted file that no download would ever replace. Presence is not trust
(ADR-0024 §5).

**And a file the manifest does not name is refused rather than ignored**, which
is the half a per-file check does not give on its own. The build force-includes
the whole vendored *directory*, so anything sitting in it is packaged — a file
left behind by an earlier pin, or one an attacker with write access to the tree
dropped there. Verifying only the named files would let such a file ship under
this project's name with no digest, no notice and no mention in the manifest,
which is exactly what "the SHA-256 of every file as shipped" is supposed to
foreclose. This lane met the shape rather than imagining it: dropping two files
from a manifest left them on disk and staged for packaging until they were
removed by hand.
"""

from __future__ import annotations

import hashlib
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
        directory_name: What the directory is called under ``_vendor/``.
        repo_id: The Hugging Face repository the files come from.
        revision: The immutable commit they are pinned to, so that a moved
            default branch does not change what a build produces.
        manifest: Every file this product ships from that repository, mapped to
            the SHA-256 of the exact bytes shipped. The *bytes*, not the
            revision: a re-pin that changes them changes what runs, and the check
            is against these rather than against the commit.
    """

    directory_name: str
    repo_id: str
    revision: str
    manifest: Mapping[str, str]


#: The speech-recognition model. Moonshine tiny (English), int8-quantised, in the
#: four-file layout its runtime expects. Chosen for a push-to-talk rung because it
#: consumes a **variable-length** recording rather than padding every clip to a
#: fixed window, and returns cased, punctuated text — which is what makes a
#: transcript worth showing back to the person who spoke it (ADR-0200 §4).
MOONSHINE_TINY_EN_INT8 = SpeechArtifact(
    directory_name="moonshine-tiny-en-int8",
    repo_id="csukuangfj/sherpa-onnx-moonshine-tiny-en-int8",
    revision="bf2b762c076d8ea61e2af0b3851c9564fb77552e",
    manifest=MappingProxyType(
        {
            "cached_decode.int8.onnx": (
                "2aff28bba6a03d8dcf5c9feac45462629bae37317442299f28115ad09da773f6"
            ),
            "encode.int8.onnx": (
                "8774dfba578de027ec6595c2c654a0836434489bc963a0db124a7f181f571acb"
            ),
            "preprocess.onnx": ("f33addce61a143460fe753b5ee5b7db255e5140b5b779c065b94f6c83ff0bf4e"),
            "tokens.txt": ("1165c2aeb9f72f457a83be2d459a09054f27490acd9b41bd43794dfd25e296ea"),
            "uncached_decode.int8.onnx": (
                "216737000dd5881a17aa043f6bbd286add33e4c3b0ae257153e2ec15438bdc41"
            ),
        }
    ),
)

#: The speech-synthesis model, int8-quantised. Its licence is why it is this one
#: and not either of the two obvious alternatives, and its input is why it is
#: eight files rather than three hundred and sixty.
#:
#: **It takes text directly**, indexed against a unicode table it ships, so it
#: needs no grapheme-to-phoneme dictionary at all. That is what rules out the
#: near miss: every phoneme voice in this family reads its pronunciation from an
#: **espeak-ng data directory**, which is several hundred files of *GPL-3.0*
#: material — and vendoring GPL-3.0 data into an MIT distribution is a licensing
#: decision this lane has no standing to take in passing, on top of the
#: corresponding-source obligation it would carry.
#:
#: **The other alternative, a VITS voice driven from a CMU pronunciation lexicon,
#: is permissively licensed and was rejected on a measurement**: it silently
#: **drops every word its lexicon does not contain**. "You have a meeting with Sam
#: at 3pm" renders without the time, and an unfamiliar name renders without the
#: name. ADR-0200 §4 makes it this seam's obligation that the audio is an audible
#: rendering *of the text*, and for a personal assistant the out-of-vocabulary
#: words are exactly the names, numbers and abbreviations the answer is about.
#: This model renders all of them, and its own ``LICENSE`` file ships with it.
SUPERTONIC_3_INT8 = SpeechArtifact(
    directory_name="supertonic-3-int8",
    repo_id="csukuangfj2/sherpa-onnx-supertonic-3-tts-int8-2026-05-11",
    revision="cca5a0e6c96e1d2c720986bf7e75fcc81dee3ae4",
    manifest=MappingProxyType(
        {
            "LICENSE": ("0dfe0d0ba84416fe3879d9a34f4909d8d0137c78d1e95834177b0414ac096fa2"),
            "duration_predictor.int8.onnx": (
                "c3eb91414d5ff8a7a239b7fe9e34e7e2bf8a8140d8375ffb14718b1c639325db"
            ),
            "text_encoder.int8.onnx": (
                "c7befd5ea8c3119769e8a6c1486c4edc6a3bc8365c67621c881bbb774b9902ff"
            ),
            "tts.json": ("42078d3aef1cd43ab43021f3c54f47d2d75ceb4e75f627f118890128b06a0d09"),
            "unicode_indexer.bin": (
                "8402ca48e5189a8950138580b0fff64db6f072f24ac07cd54ba8b2fbb9883b30"
            ),
            "vector_estimator.int8.onnx": (
                "20cd86fa5c6effedfda0e7cffe5b0569ca401c440a0c3a1d72bf39286c0db3fd"
            ),
            "vocoder.int8.onnx": (
                "e923d60f53f95eb1ce235f1dc33ec56d9c057823c96fa6f8acf98f32b0da6152"
            ),
            "voice.bin": ("67d5209b0ee8ce6c74105ffbe12fe6a7628aea3b4ba2fcb308a4a67938a93ce8"),
        }
    ),
)

#: Every speech artifact this distribution ships. The build hook iterates this, so
#: adding a third model is a constant here and no change to the hook.
SPEECH_ARTIFACTS: tuple[SpeechArtifact, ...] = (MOONSHINE_TINY_EN_INT8, SUPERTONIC_3_INT8)


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


def unexpected_files(artifact: SpeechArtifact, directory: Path) -> list[str]:
    """Return the files in ``directory`` the manifest does not name, sorted.

    Args:
        artifact: The artifact whose manifest to check against.
        directory: The directory to inspect.

    Returns:
        Their paths relative to ``directory``, with ``/`` separators as the
        manifest spells them.
    """
    if not directory.is_dir():
        return []
    named = set(artifact.manifest)
    return sorted(
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.relative_to(directory).as_posix() not in named
    )


def verify_artifact(artifact: SpeechArtifact, directory: Path) -> None:
    """Check ``directory`` holds the manifest's files, their bytes, and nothing else.

    Presence is not trust (ADR-0024 §5): a file already staged, or one unpacked
    from an sdist, is hashed here exactly as a freshly downloaded one is. Absence
    of anything else is checked too, because the build packages the whole
    directory — see this module's docstring for why that is not a nicety.

    Args:
        artifact: The artifact whose manifest to verify against.
        directory: The directory holding the artifact.

    Raises:
        SpeechArtifactError: If a file is missing, unreadable, carries a digest
            the manifest does not record, or is not named by the manifest at all.
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
    unexpected = unexpected_files(artifact, directory)
    if unexpected:
        msg = (
            f"speech artifact {artifact.directory_name!r} holds "
            f"{len(unexpected)} file(s) its manifest does not name, and the build "
            f"packages the whole directory: {', '.join(unexpected)}. Remove them, or "
            f"record them in the manifest if they are meant to ship."
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
