"""The backup artifact's container: age version 1, streamed (ADR-0123 §4).

§4 fixes the format and leaves the implementation to this lane: "A backup
artifact is a single regular file: a ``tar`` stream of the copied files and the
§6 manifest, encrypted whole in the **age version 1** format with an scrypt
passphrase recipient."

**Why the format is implemented here rather than delegated whole.** §4's reason
for adopting a standard format is recovery — "A recovery machine with a working
``age`` or ``rage`` binary can open an age file when this tool is the thing that
is missing" — so what matters is that the bytes are age v1, not which code
produced them. The one library that would have produced them for us, ``pyrage``,
exposes passphrase encryption only as ``bytes -> bytes``; its streaming pair
reaches x25519 and ssh recipients and no scrypt one. Taking it would mean holding
the whole data directory in memory, and §2 forecloses that in as many words:
"buffering a whole data directory in memory is not a design, and staging the
plaintext breaks §4's clause". So the framing — header, HKDF, ``STREAM`` nonces —
is here, over ``cryptography``'s ChaCha20-Poly1305 and CPython's own ``scrypt``,
and ``pyrage`` is the *independent* implementation §4's interop clause requires
(``tests/service/test_agev1.py`` runs the round trip both ways, on every CI run).

**Streaming is the whole point of the shape.** :class:`EncryptingWriter` is a
write-only binary stream a ``tarfile`` in ``w|`` mode writes into, and
:class:`DecryptingReader` is a read-only one a ``tarfile`` in ``r|`` mode reads
out of. Neither ever holds more than one 64 KiB chunk, so the artifact's size is
bounded by the disk and not by memory.

**What this module refuses.** Every parse failure is an :class:`AgeError`, and
the tools above turn it into a refusal rather than a traceback: a wrong
passphrase, a truncated payload, a flipped byte, a spliced chunk, a header MAC
that does not verify, a non-canonical base64 encoding, or a work factor larger
than :data:`MAX_WORK_FACTOR`. That is §4's "a truncated artifact, a flipped byte
and a spliced-in chunk all fail to decrypt instead of yielding a shorter or
altered directory", made concrete.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
from typing import TYPE_CHECKING, Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from ai_assistant.service.refusal import RefusalError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType
    from typing import BinaryIO, Self

#: The format's first line, which is also its whole version statement.
_VERSION_LINE: Final = b"age-encryption.org/v1"

#: The scrypt recipient's stanza tag, and the label mixed into its salt.
_SCRYPT_TAG: Final = "scrypt"

#: How many space-separated fields an scrypt stanza's argument line has:
#: ``->``, the tag, the salt and the work factor.
_STANZA_FIELDS: Final = 4
_SCRYPT_LABEL: Final = b"age-encryption.org/v1/scrypt"

#: scrypt's block-size and parallelism parameters, fixed by the age v1 spec.
_SCRYPT_R: Final = 8
_SCRYPT_P: Final = 1

#: The file key's length, and the AEAD's key and tag lengths, all in bytes.
_FILE_KEY_BYTES: Final = 16
_KEY_BYTES: Final = 32
_TAG_BYTES: Final = 16

#: The payload nonce that seeds the ``STREAM`` key derivation.
_PAYLOAD_NONCE_BYTES: Final = 16

#: ``STREAM``'s plaintext chunk size. Fixed by the format, not tunable.
CHUNK_BYTES: Final = 64 * 1024

#: How wide a stanza body's base64 lines are. A body ends at the first line
#: narrower than this, which is why a body whose length is an exact multiple
#: needs a trailing empty line.
_BODY_COLUMNS: Final = 64

#: What the tool writes with, which is what ``rage`` writes with — checked, not
#: assumed: an artifact from ``pyrage.passphrase.encrypt`` carries ``-> scrypt
#: <salt> 19``. Matching it means an artifact this tool writes costs a recovery
#: machine exactly what any other age artifact would, roughly a second and
#: 512 MiB while the key is derived.
DEFAULT_WORK_FACTOR: Final = 19

#: The largest work factor this tool will *read*. Asymmetric on purpose: the
#: header is attacker-controlled until its MAC verifies, and the MAC cannot be
#: checked until the key is derived — so an artifact declaring 40 would have this
#: process allocate a terabyte before it could refuse. 20 is one doubling above
#: what is written, which is also the ceiling CPython's ``scrypt`` can express:
#: its ``maxmem`` must stay under 2 GiB, and 21 needs more than that.
MAX_WORK_FACTOR: Final = 20


class AgeError(RefusalError):
    """An artifact is not readable as age v1, or not with this passphrase.

    Carries no distinction between "wrong passphrase" and "corrupt header",
    because the format offers none: the scrypt stanza's body is an AEAD
    ciphertext, so a wrong key and a damaged body fail identically.
    """


def _b64(raw: bytes) -> str:
    """Encode as age's unpadded standard base64."""
    return base64.b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str, *, what: str) -> bytes:
    """Decode age's unpadded standard base64, refusing a non-canonical encoding.

    Args:
        text: The encoded text, without padding.
        what: What is being decoded, for the diagnostic.

    Returns:
        The decoded bytes.

    Raises:
        AgeError: If it does not decode, or if re-encoding it does not reproduce
            the input. The age spec requires canonical encodings, and accepting a
            non-canonical one would make an artifact's bytes ambiguous — two
            spellings of one header would carry two different MACs.
    """
    try:
        raw = base64.b64decode(text + "=" * (-len(text) % 4), validate=True)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        msg = f"the artifact's {what} is not valid base64"
        raise AgeError(msg) from exc
    if _b64(raw) != text:
        msg = f"the artifact's {what} is not canonically encoded"
        raise AgeError(msg)
    return raw


def _hkdf(ikm: bytes, salt: bytes, info: bytes) -> bytes:
    """HKDF-SHA256 down to one 32-byte block, which is all age ever asks for.

    Args:
        ikm: The input keying material — always the file key here.
        salt: The extract salt: empty for the header key, the payload nonce for
            the payload key.
        info: The label, ``b"header"`` or ``b"payload"``.

    Returns:
        32 bytes of output keying material.
    """
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()


def scrypt_maxmem(n: int) -> int:
    """The memory budget CPython's ``scrypt`` must be given for this ``N``.

    OpenSSL refuses to allocate past ``maxmem``, whose default (32 MiB) is below
    what any realistic work factor needs — and it also refuses a ``maxmem`` at or
    above 2 GiB. So the budget is scrypt's own working-set formula rather than a
    round number with slack: a doubling of it would be over that ceiling at
    :data:`MAX_WORK_FACTOR`, and every artifact at the highest work factor this
    tool accepts would then fail to open on the recovery machine, which is the
    worst place to find out.

    Args:
        n: scrypt's cost parameter, ``1 << work_factor``.

    Returns:
        The budget, in bytes.
    """
    return 128 * _SCRYPT_R * (n + _SCRYPT_P + 2)


def _scrypt_key(passphrase: str, salt: bytes, work_factor: int) -> bytes:
    """Derive the stanza's wrapping key, exactly as age v1 specifies.

    Args:
        passphrase: The operator's passphrase, encoded UTF-8.
        salt: The stanza's 16 random bytes, *before* the label is prepended.
        work_factor: log2 of scrypt's ``N``.

    Returns:
        The 32-byte key that wraps the file key.
    """
    n = 1 << work_factor
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=_SCRYPT_LABEL + salt,
        n=n,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_BYTES,
        maxmem=scrypt_maxmem(n),
    )


def _chunk_nonce(counter: int, *, final: bool) -> bytes:
    """``STREAM``'s per-chunk nonce: an 11-byte counter and a last-chunk flag.

    Args:
        counter: The chunk's zero-based index.
        final: Whether this is the payload's last chunk.

    Returns:
        The 12-byte nonce.

    Raises:
        AgeError: If the counter has run past what 11 bytes can hold. Unreachable
            for any artifact a filesystem can store — it is 16 exabytes of
            plaintext — and refused rather than silently wrapped, because a
            wrapped counter reuses a nonce.
    """
    if counter >= 1 << 88:
        msg = "the payload is longer than the age v1 chunk counter can address"
        raise AgeError(msg)
    return counter.to_bytes(11, "big") + (b"\x01" if final else b"\x00")


class EncryptingWriter(io.RawIOBase):
    """A write-only stream that lands age v1 ciphertext in ``out``.

    Used as ``tarfile.open(fileobj=writer, mode="w|")``, so the archive is built
    and encrypted in one pass and never exists in plaintext anywhere — which is
    what ADR-0123 §2 requires when it rules out staging the plaintext.

    **Closing is part of the format, not just tidiness.** ``STREAM``'s last chunk
    carries a flag that marks it as last, and nothing else does; a writer that is
    dropped without :meth:`close` produces a file that no reader will accept.
    Using it as a context manager is what makes that hard to get wrong.
    """

    def __init__(
        self, out: BinaryIO, passphrase: str, *, work_factor: int = DEFAULT_WORK_FACTOR
    ) -> None:
        """Derive the keys, write the header and the payload nonce.

        Args:
            out: Where the ciphertext goes. Written to immediately.
            passphrase: The operator's passphrase (ADR-0123 §5).
            work_factor: log2 of scrypt's ``N``. Lowered only by tests, which
                would otherwise spend a second and 256 MiB per artifact.

        Raises:
            ValueError: If the passphrase is empty, or the work factor is outside
                what this module reads back.
        """
        super().__init__()
        # Set before anything can raise: `io.RawIOBase.__del__` calls `close`,
        # and a half-built writer whose `close` raises `AttributeError` turns a
        # clean refusal into an unraisable exception at garbage-collection time.
        # `True` rather than `False`, so that close on a writer that never got a
        # header emits no final chunk into a stream that has no payload.
        self._finished = True
        if not passphrase:
            msg = "an age v1 artifact cannot be keyed to an empty passphrase"
            raise ValueError(msg)
        if not 1 <= work_factor <= MAX_WORK_FACTOR:
            msg = f"work factor {work_factor} is outside 1..{MAX_WORK_FACTOR}"
            raise ValueError(msg)

        self._out = out
        self._buffer = bytearray()
        self._counter = 0

        file_key = os.urandom(_FILE_KEY_BYTES)
        salt = os.urandom(_FILE_KEY_BYTES)
        wrapping_key = _scrypt_key(passphrase, salt, work_factor)
        wrapped = ChaCha20Poly1305(wrapping_key).encrypt(b"\x00" * 12, file_key, None)

        header = bytearray(_VERSION_LINE + b"\n")
        header += f"-> {_SCRYPT_TAG} {_b64(salt)} {work_factor}\n".encode("ascii")
        for line in _wrap_body(_b64(wrapped)):
            header += line.encode("ascii") + b"\n"
        header += b"---"
        mac = hmac.new(_hkdf(file_key, b"", b"header"), bytes(header), hashlib.sha256).digest()
        out.write(bytes(header) + b" " + _b64(mac).encode("ascii") + b"\n")

        nonce = os.urandom(_PAYLOAD_NONCE_BYTES)
        out.write(nonce)
        self._aead = ChaCha20Poly1305(_hkdf(file_key, nonce, b"payload"))
        self._finished = False

    def writable(self) -> bool:
        """This stream is write-only."""
        return True

    def write(self, b: object, /) -> int:
        """Buffer plaintext, emitting every whole chunk that is not the last.

        Args:
            b: A bytes-like object of plaintext.

        Returns:
            How many bytes were accepted, which is always all of them.

        Raises:
            ValueError: If the stream has already been closed.
        """
        if self._finished:
            msg = "this age v1 writer is closed"
            raise ValueError(msg)
        data = bytes(memoryview(b))  # type: ignore[arg-type]
        self._buffer += data
        # Strictly greater, never `>=`: a chunk held back here may still turn out
        # to be the last one, and the last chunk is the only one whose nonce
        # carries the final flag. Emitting an exactly-full buffer eagerly would
        # leave an empty final chunk, which the format allows only for an
        # entirely empty payload.
        while len(self._buffer) > CHUNK_BYTES:
            self._emit(bytes(self._buffer[:CHUNK_BYTES]), final=False)
            del self._buffer[:CHUNK_BYTES]
        return len(data)

    def close(self) -> None:
        """Emit the final chunk and mark it as final. Idempotent."""
        if not self._finished:
            self._finished = True
            self._emit(bytes(self._buffer), final=True)
            self._buffer.clear()
        super().close()

    def __enter__(self) -> Self:
        """Return this writer, so ``with`` reads naturally."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Seal the payload on the way out, including on an exception.

        Sealing after a failure costs nothing and is not a claim the artifact is
        good: the caller above removes the temporary file on every refusal path
        (ADR-0123 §2), so a sealed-but-abandoned stream never becomes an artifact.
        """
        self.close()

    def _emit(self, plaintext: bytes, *, final: bool) -> None:
        """Seal one chunk under its own nonce and write it out."""
        nonce = _chunk_nonce(self._counter, final=final)
        self._out.write(self._aead.encrypt(nonce, plaintext, None))
        self._counter += 1


def _wrap_body(encoded: str) -> list[str]:
    """Split a stanza body into age's 64-column lines.

    A body ends at the first line shorter than 64 columns, so a body whose
    encoding is an exact multiple of 64 needs an explicit empty line after it —
    without which a reader would keep consuming the header's next line as body.

    Args:
        encoded: The body's base64, unpadded.

    Returns:
        The lines, without their terminators.
    """
    lines = [encoded[i : i + _BODY_COLUMNS] for i in range(0, len(encoded), _BODY_COLUMNS)]
    if not lines or len(lines[-1]) == _BODY_COLUMNS:
        lines.append("")
    return lines


class DecryptingReader(io.RawIOBase):
    """A read-only stream of the plaintext inside an age v1 artifact.

    Used as ``tarfile.open(fileobj=reader, mode="r|")``. The header is parsed and
    its MAC verified in the constructor, so an artifact that is not ours, not age
    v1, or not this passphrase's fails before a single archive member is seen.

    Args:
        src: The artifact, opened for buffered binary reading. ``readline`` is
            used for the header and ``read`` for the payload, so it must be a
            buffered stream rather than a raw one.
        passphrase: The operator's passphrase.

    Raises:
        AgeError: If the header is not age v1, carries anything but a single
            scrypt recipient, declares a work factor outside 1..
            :data:`MAX_WORK_FACTOR`, or fails its MAC — which is also what a
            wrong passphrase looks like.
    """

    def __init__(self, src: BinaryIO, passphrase: str) -> None:
        """Parse and authenticate the header, then derive the payload key."""
        super().__init__()
        self._src = src
        file_key = self._read_header(passphrase)
        nonce = _read_exactly(src, _PAYLOAD_NONCE_BYTES)
        if len(nonce) != _PAYLOAD_NONCE_BYTES:
            msg = "the artifact ends before its payload nonce; it is truncated"
            raise AgeError(msg)
        self._aead = ChaCha20Poly1305(_hkdf(file_key, nonce, b"payload"))
        self._counter = 0
        self._pending = bytearray()
        self._ahead: bytes | None = None
        self._drained = False

    def readable(self) -> bool:
        """This stream is read-only."""
        return True

    def readinto(self, b: object, /) -> int:
        """Fill ``b`` with plaintext, decrypting further chunks as needed.

        Args:
            b: A writable buffer.

        Returns:
            How many bytes were written into it; ``0`` at the end of the payload.
        """
        target = memoryview(b).cast("B")  # type: ignore[arg-type]
        while not self._pending and not self._drained:
            self._decrypt_next()
        take = min(len(target), len(self._pending))
        target[:take] = self._pending[:take]
        del self._pending[:take]
        return take

    def _read_header(self, passphrase: str) -> bytes:
        """Parse the header, verify its MAC and unwrap the file key."""
        raw = bytearray()
        first = self._src.readline()
        raw += first
        if first.rstrip(b"\n") != _VERSION_LINE:
            msg = (
                "this file does not start with age v1's version line, so it is not a "
                "backup artifact this tool wrote"
            )
            raise AgeError(msg)

        salt, work_factor, wrapped = self._read_scrypt_stanza(raw)

        mac_line = self._src.readline()
        if not mac_line.startswith(b"--- "):
            msg = "the artifact's header does not end with its MAC line"
            raise AgeError(msg)
        raw += b"---"
        declared = _unb64(mac_line[4:].rstrip(b"\n").decode("ascii", "replace"), what="header MAC")

        wrapping_key = _scrypt_key(passphrase, salt, work_factor)
        try:
            file_key = ChaCha20Poly1305(wrapping_key).decrypt(b"\x00" * 12, wrapped, None)
        except InvalidTag as exc:
            msg = (
                "the artifact's file key does not unwrap with this passphrase — either "
                "the passphrase is wrong or the artifact's header is damaged"
            )
            raise AgeError(msg) from exc
        expected = hmac.new(_hkdf(file_key, b"", b"header"), bytes(raw), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, declared):
            msg = "the artifact's header MAC does not verify; the header has been altered"
            raise AgeError(msg)
        return file_key

    def _read_scrypt_stanza(self, raw: bytearray) -> tuple[bytes, int, bytes]:
        """Read the one recipient stanza age v1 allows an scrypt artifact.

        The spec makes an scrypt stanza exclusive — an artifact carrying one may
        carry no other recipient — so "exactly one, and it is scrypt" is the
        format's own rule rather than a narrowing of it.
        """
        line = self._src.readline()
        raw += line
        parts = line.rstrip(b"\n").decode("ascii", "replace").split(" ")
        if len(parts) != _STANZA_FIELDS or parts[0] != "->" or parts[1] != _SCRYPT_TAG:
            msg = (
                "the artifact is not encrypted to a passphrase: its header carries no "
                "single scrypt recipient, which is the only recipient this tool reads"
            )
            raise AgeError(msg)
        salt = _unb64(parts[2], what="scrypt salt")
        if len(salt) != _FILE_KEY_BYTES:
            msg = f"the artifact's scrypt salt is {len(salt)} bytes, not {_FILE_KEY_BYTES}"
            raise AgeError(msg)
        try:
            work_factor = int(parts[3])
        except ValueError as exc:
            msg = f"the artifact's scrypt work factor {parts[3]!r} is not a number"
            raise AgeError(msg) from exc
        if not 1 <= work_factor <= MAX_WORK_FACTOR:
            msg = (
                f"the artifact declares scrypt work factor {work_factor}, outside the "
                f"1..{MAX_WORK_FACTOR} this tool will spend on an unauthenticated header"
            )
            raise AgeError(msg)

        body = "".join(self._read_body_lines(raw))
        wrapped = _unb64(body, what="scrypt stanza body")
        if len(wrapped) != _FILE_KEY_BYTES + _TAG_BYTES:
            msg = f"the artifact's wrapped file key is {len(wrapped)} bytes, not 32"
            raise AgeError(msg)
        return salt, work_factor, wrapped

    def _read_body_lines(self, raw: bytearray) -> Iterator[str]:
        """Yield a stanza body's base64 lines, stopping at the first short one."""
        while True:
            line = self._src.readline()
            if not line:
                msg = "the artifact's header ends mid-stanza; it is truncated"
                raise AgeError(msg)
            raw += line
            text = line.rstrip(b"\n").decode("ascii", "replace")
            yield text
            if len(text) < _BODY_COLUMNS:
                return

    def _decrypt_next(self) -> None:
        """Decrypt one chunk, using a one-chunk lookahead to spot the last one.

        ``STREAM`` marks the final chunk in its nonce, so a reader cannot know
        which chunk is final until it has looked past it. Holding exactly one
        ciphertext chunk in hand is what turns "is there more?" into a question
        the stream can answer without seeking — which matters, because the
        artifact is read once, forward, straight into ``tarfile``.
        """
        sealed = self._ahead if self._ahead is not None else _read_exactly(self._src, _sealed())
        self._ahead = None
        if not sealed:
            msg = "the artifact's payload is empty; it is truncated"
            raise AgeError(msg)
        following = _read_exactly(self._src, _sealed())
        final = not following
        if not final:
            self._ahead = following
            if len(sealed) != _sealed():
                msg = "the artifact's payload has a short chunk before its last; it is damaged"
                raise AgeError(msg)
        try:
            plaintext = self._aead.decrypt(_chunk_nonce(self._counter, final=final), sealed, None)
        except InvalidTag as exc:
            msg = (
                f"the artifact's payload fails authentication at chunk {self._counter}; it "
                f"has been truncated, altered or spliced"
            )
            raise AgeError(msg) from exc
        self._counter += 1
        self._pending += plaintext
        self._drained = final


def _sealed() -> int:
    """One chunk's size on the wire: its plaintext plus its authentication tag."""
    return CHUNK_BYTES + _TAG_BYTES


def _read_exactly(src: BinaryIO, count: int) -> bytes:
    """Read up to ``count`` bytes, looping past short reads.

    ``read(n)`` is allowed to return fewer bytes than asked for without being at
    the end of the stream, and treating a short read as the end is how a payload
    silently loses its last chunks.

    Args:
        src: The stream to read from.
        count: How many bytes are wanted.

    Returns:
        Exactly ``count`` bytes, or fewer only at the end of the stream.
    """
    out = bytearray()
    while len(out) < count:
        block = src.read(count - len(out))
        if not block:
            break
        out += block
    return bytes(out)
