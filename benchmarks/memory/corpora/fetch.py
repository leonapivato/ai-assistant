"""Acquire a corpus non-interactively, verify it, and cache it.

**Verification is not optional and there is no bypass.** A file whose digest does not
match the pin in :mod:`~benchmarks.memory.corpora.provenance` is deleted and the
fetch fails, because the alternative — scoring a pre-registered prediction against
bytes nobody has identified — is the failure this whole module exists to prevent.

Nothing fetched here is committed. The cache is a directory under this tree that
git ignores, so the corpora are a build input in the shape the vendored embedding
model already is: fetched from a pinned revision, verified against a recorded digest,
never in the history.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from benchmarks.memory.corpora.provenance import Corpus, CorpusFile

#: Where fetched corpora live, beside this package and ignored by git.
DEFAULT_CACHE: Final = Path(__file__).resolve().parent.parent.parent / ".corpora"

#: Read size for the streaming download and for hashing. Large enough that a 278 MiB
#: file is not a million syscalls, small enough that nothing here holds a corpus in
#: memory — which matters because the largest artifact is 2.7 GiB.
_CHUNK: Final = 1 << 20

#: Seconds any single socket operation may block before the transfer is abandoned.
#:
#: **A per-operation bound, not a total-transfer one, and the distinction is the whole
#: reason a number is safe here.** The largest pinned artifact is 2.7 GiB, so a cap on
#: how long a download may take would refuse a slow but perfectly healthy connection.
#: What this bounds is how long the socket may deliver *nothing*, which no honest
#: transfer does. Without it `urlopen` inherits the global default of ``None`` and a
#: peer that completes the handshake and then stalls hangs `fetch` — and with it the
#: `run` command, which fetches on the way in — with no output and no exception path
#: ever reached.
_SOCKET_TIMEOUT: Final = 60.0


class CorpusFetchError(RuntimeError):
    """A corpus could not be acquired, or the bytes were not the pinned bytes."""


def cached_path(file: CorpusFile, *, cache: Path | None = None) -> Path:
    """Where a corpus file is (or would be) cached.

    Args:
        file: The artifact.
        cache: Cache root, defaulting to :data:`DEFAULT_CACHE`.

    Returns:
        The absolute path, whether or not anything is there yet.
    """
    return (cache or DEFAULT_CACHE) / file.name


def digest_of(path: Path) -> str:
    """The SHA-256 of a file, streamed.

    Args:
        path: The file to hash.

    Returns:
        Lowercase hex.
    """
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            hasher.update(chunk)
    return hasher.hexdigest()


def ensure_file(file: CorpusFile, *, cache: Path | None = None) -> Path:
    """Return a verified local copy of ``file``, downloading it if needed.

    A cached copy is re-verified rather than trusted: a truncated download from an
    interrupted earlier run is exactly the case a cache-hit-means-done rule gets
    wrong, and hashing costs seconds against a download that costs minutes.

    Args:
        file: The artifact to acquire.
        cache: Cache root, defaulting to :data:`DEFAULT_CACHE`.

    Returns:
        The path to the verified file.

    Raises:
        CorpusFetchError: If the download failed, or if the bytes do not match the
            pinned digest. In the second case the offending file is removed first,
            so a retry does not resume from a copy already known to be wrong.
    """
    target = cached_path(file, cache=cache)
    if target.exists():
        found = digest_of(target)
        if found == file.sha256:
            return target
        target.unlink()

    target.parent.mkdir(parents=True, exist_ok=True)
    # **A staging path unique to this process, not one derived from the target.** Two
    # concurrent fetches of the same corpus that shared a `.partial` would have one
    # verify and publish the inode the other is still writing through — corrupting the
    # cache *after* the digest check that is supposed to make it trustworthy, and then
    # hashing a path that no longer exists. With distinct names each process verifies
    # its own bytes, and `Path.replace` publishes atomically, so the loser of the race
    # simply overwrites identical verified content.
    handle, staged_name = tempfile.mkstemp(
        dir=target.parent, prefix=f"{target.name}.", suffix=".partial"
    )
    os.close(handle)
    partial = Path(staged_name)
    # `mkstemp` has already created the file, so *every* exit that is not a successful
    # publish has to remove it — including the ones that raise before a byte is
    # written, such as `_download`'s scheme check. Without this a rejected URL leaves
    # a stray staging file in the cache on every attempt.
    try:
        _download(file.url, partial)
        found = digest_of(partial)
        if found != file.sha256:
            msg = (
                f"{file.name}: downloaded bytes do not match the pinned digest "
                f"(expected {file.sha256}, got {found}). The pin names an immutable "
                f"revision, so this is a corrupted transfer or a changed pin, never a "
                f"legitimately updated corpus."
            )
            raise CorpusFetchError(msg)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def ensure_corpus(corpus: Corpus, *, cache: Path | None = None) -> dict[str, Path]:
    """Acquire and verify every file of a corpus.

    Args:
        corpus: The corpus to acquire.
        cache: Cache root, defaulting to :data:`DEFAULT_CACHE`.

    Returns:
        Each file's name mapped to its verified path.

    Raises:
        CorpusFetchError: As :func:`ensure_file`.
    """
    return {file.name: ensure_file(file, cache=cache) for file in corpus.files}


def _download(url: str, target: Path) -> None:
    """Stream ``url`` to ``target``.

    Args:
        url: An ``https`` URL naming a pinned revision.
        target: Where to write.

    Raises:
        CorpusFetchError: If the scheme is not ``https``, or the transfer failed — a
            stall included, since :data:`_SOCKET_TIMEOUT` turns one into a
            ``TimeoutError``, which is an ``OSError`` and so takes the same path as any
            other broken transfer.
    """
    if not url.startswith("https://"):
        # Checked rather than assumed, because everything downstream trusts these
        # bytes: an `http` or `file` URL would make the digest pin the only thing
        # standing between the harness and unauthenticated data, and a pin can be
        # edited in the same diff that edits the URL.
        msg = f"refusing to fetch a corpus over a non-https URL: {url!r}"
        raise CorpusFetchError(msg)
    request = urllib.request.Request(  # noqa: S310 — the `https` scheme is checked immediately above
        url, headers={"User-Agent": "ai-assistant-benchmarks"}
    )
    try:
        with (
            urllib.request.urlopen(request, timeout=_SOCKET_TIMEOUT) as response,  # noqa: S310 — as above
            target.open("wb") as handle,
        ):
            shutil.copyfileobj(response, handle, _CHUNK)
    except (urllib.error.URLError, OSError) as exc:
        target.unlink(missing_ok=True)
        msg = f"could not fetch {url}: {exc}"
        raise CorpusFetchError(msg) from exc
