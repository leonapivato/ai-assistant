"""Tests for the artifact's age v1 container (ADR-0123 §4).

**The first two tests are §4's normative clause, run on every push.** "Before
this decision's implementation is complete, an artifact written by this tool is
decrypted and unpacked by an independent implementation of the age format, and an
artifact written by that implementation is read by this tool." The independent
implementation is ``pyrage``, which binds Rust ``rage`` and shares no code with
:mod:`ai_assistant.service.agev1`; §4's reasoning is exactly why a self round trip
would not do — "An implementation of age v1 that round-trips against itself
proves nothing about the recovery path the format was chosen for; one that
round-trips against a foreign implementation proves the whole of it."

A pinned test vector could have discharged only one direction of it. Our
ciphertext is randomised per run — a fresh file key, a fresh scrypt salt, a fresh
payload nonce — so "ours, read by theirs" is not expressible as a fixed vector and
needs the foreign implementation present when the test runs.

Everything is written at a low work factor. The format carries its own in the
header, so a reader spends what the artifact declares rather than what this module
defaults to, and a suite at the real default would spend half a gigabyte per
artifact for no additional coverage.
"""

from __future__ import annotations

import base64
import hashlib
import io
import string

import pyrage
import pytest

from ai_assistant.service.agev1 import (
    CHUNK_BYTES,
    DEFAULT_WORK_FACTOR,
    MAX_WORK_FACTOR,
    AgeError,
    DecryptingReader,
    EncryptingWriter,
    scrypt_maxmem,
)

_KEYPHRASE = "correct horse battery staple"

#: Cheap enough to run hundreds of times, and structurally identical to the real
#: one: only ``N`` changes.
_TEST_WORK_FACTOR = 8

#: The sizes where the chunking can go wrong: empty, a single byte, and each side
#: of every chunk boundary the writer holds back a buffer at.
_SIZES = [0, 1, CHUNK_BYTES - 1, CHUNK_BYTES, CHUNK_BYTES + 1, 2 * CHUNK_BYTES, 2 * CHUNK_BYTES + 7]

#: The sizes the *foreign* implementation writes at. Fewer, because `rage` offers
#: no way to lower its work factor and each artifact therefore costs the real
#: 1.3 seconds twice over. An empty payload and a multi-chunk one with a partial
#: last chunk are what the reader's chunking can get wrong; the boundary sweep
#: above already covers the rest of it against artifacts this module writes.
_FOREIGN_SIZES = [0, 2 * CHUNK_BYTES + 7]

#: Standard base64's alphabet, which age uses without padding.
_B64_ALPHABET = (string.ascii_uppercase + string.ascii_lowercase + string.digits + "+/").encode(
    "ascii"
)


def _encrypt(
    plaintext: bytes, *, key_phrase: str = _KEYPHRASE, work_factor: int | None = None
) -> bytes:
    """Seal ``plaintext`` with this module, at the cheap work factor by default."""
    out = io.BytesIO()
    with EncryptingWriter(out, key_phrase, work_factor=work_factor or _TEST_WORK_FACTOR) as writer:
        writer.write(plaintext)
    return out.getvalue()


def _decrypt(artifact: bytes, *, key_phrase: str = _KEYPHRASE) -> bytes:
    """Open ``artifact`` with this module."""
    return DecryptingReader(io.BytesIO(artifact), key_phrase).read() or b""


@pytest.mark.parametrize("size", _SIZES)
def test_an_artifact_this_module_writes_is_read_by_an_independent_implementation(size: int) -> None:
    """ADR-0123 §4's first direction: ours out, ``rage`` in."""
    plaintext = hashlib.sha256(str(size).encode()).digest() * (size // 32 + 1)
    plaintext = plaintext[:size]

    artifact = _encrypt(plaintext)

    assert pyrage.passphrase.decrypt(artifact, _KEYPHRASE) == plaintext


@pytest.mark.parametrize("size", _FOREIGN_SIZES)
def test_an_artifact_an_independent_implementation_writes_is_read_by_this_module(size: int) -> None:
    """ADR-0123 §4's second direction: ``rage`` out, ours in."""
    plaintext = bytes(range(256)) * (size // 256 + 1)
    plaintext = plaintext[:size]

    artifact = pyrage.passphrase.encrypt(plaintext, _KEYPHRASE)

    assert _decrypt(artifact) == plaintext


def test_the_independent_implementation_refuses_a_wrong_passphrase_for_our_artifact() -> None:
    """The key is the passphrase and nothing else, which is what §5 rests on."""
    artifact = _encrypt(b"the accumulated model")

    with pytest.raises(pyrage.DecryptError):
        pyrage.passphrase.decrypt(artifact, "not the passphrase")


@pytest.mark.parametrize("size", _SIZES)
def test_a_round_trip_through_this_module_returns_the_bytes(size: int) -> None:
    """The self round trip, which is necessary and — per §4 — nothing like sufficient."""
    plaintext = b"x" * size

    assert _decrypt(_encrypt(plaintext)) == plaintext


def test_the_writer_emits_ciphertext_before_the_stream_is_closed() -> None:
    """Streaming, not buffering: ADR-0123 §2 forecloses holding the whole thing.

    Written as an observation of the output rather than of memory: after three
    chunks have been handed to the writer, at least two chunks' worth of
    ciphertext is already on the far side of it.
    """
    out = io.BytesIO()
    writer = EncryptingWriter(out, _KEYPHRASE, work_factor=_TEST_WORK_FACTOR)
    header_and_nonce = out.tell()

    writer.write(b"a" * (3 * CHUNK_BYTES))

    assert out.tell() - header_and_nonce >= 2 * CHUNK_BYTES
    writer.close()


def test_a_wrong_passphrase_is_refused_rather_than_returning_rubbish() -> None:
    artifact = _encrypt(b"the accumulated model")

    with pytest.raises(AgeError, match="passphrase"):
        _decrypt(artifact, key_phrase="not the passphrase")


def test_a_flipped_payload_byte_is_refused() -> None:
    """§4: "a truncated artifact, a flipped byte and a spliced-in chunk all fail"."""
    artifact = bytearray(_encrypt(b"the accumulated model"))
    artifact[-1] ^= 0x01

    with pytest.raises(AgeError, match="authentication"):
        _decrypt(bytes(artifact))


def test_a_truncated_payload_is_refused() -> None:
    """The last chunk carries a flag, so a truncation cannot pose as an ending."""
    artifact = _encrypt(b"m" * (2 * CHUNK_BYTES))

    with pytest.raises(AgeError):
        _decrypt(artifact[: len(artifact) - CHUNK_BYTES])


def test_a_spliced_chunk_is_refused() -> None:
    """Chunk nonces are positional, so a chunk moved or duplicated fails to open."""
    artifact = _encrypt(b"m" * (3 * CHUNK_BYTES))
    # The payload starts after the MAC line, which is the first newline following
    # the `--- ` marker; the ciphertext below it is binary and may contain any
    # byte, so it cannot be found by splitting on newlines.
    payload_at = artifact.index(b"\n", artifact.index(b"--- ")) + 1
    head, body = artifact[:payload_at], artifact[payload_at:]
    sealed = CHUNK_BYTES + 16
    nonce, chunks = body[:16], body[16:]
    spliced = nonce + chunks[sealed : 2 * sealed] + chunks[:sealed] + chunks[2 * sealed :]

    with pytest.raises(AgeError, match="authentication"):
        _decrypt(head + spliced)


def test_an_altered_header_is_refused_by_its_mac() -> None:
    """The header is authenticated, so a work factor or salt cannot be edited in place."""
    artifact = _encrypt(b"the accumulated model")
    mac_at = artifact.index(b"--- ")
    payload_at = artifact.index(b"\n", mac_at) + 1
    forged = base64.b64encode(b"\x00" * 32).rstrip(b"=")

    with pytest.raises(AgeError, match="MAC"):
        _decrypt(artifact[:mac_at] + b"--- " + forged + b"\n" + artifact[payload_at:])


def test_a_file_that_is_not_age_is_refused_at_its_first_line() -> None:
    with pytest.raises(AgeError, match="version line"):
        _decrypt(b"this is not an age file\n")


def test_an_artifact_with_no_scrypt_recipient_is_refused() -> None:
    """A passphrase reader reads passphrase artifacts, and says so rather than guessing."""
    artifact = _encrypt(b"the accumulated model")
    swapped = artifact.replace(b"-> scrypt ", b"-> X25519 ", 1)

    with pytest.raises(AgeError, match="scrypt recipient"):
        _decrypt(swapped)


def test_a_work_factor_above_the_ceiling_is_refused_before_any_memory_is_spent() -> None:
    """The header is unauthenticated until its key is derived, so the cost is capped."""
    artifact = _encrypt(b"the accumulated model")
    absurd = artifact.replace(
        f" {_TEST_WORK_FACTOR}\n".encode(), f" {MAX_WORK_FACTOR + 20}\n".encode(), 1
    )

    with pytest.raises(AgeError, match=f"1..{MAX_WORK_FACTOR}"):
        _decrypt(absurd)


def test_a_non_canonical_base64_encoding_is_refused() -> None:
    """age requires canonical encodings; two spellings of one header carry two MACs."""
    artifact = _encrypt(b"the accumulated model")
    salt = artifact.split(b"\n")[1].split(b" ")[2]
    # A 16-byte value's last base64 character carries two significant bits and
    # four that must be zero, so a canonical last character always sits at a
    # multiple of 16 in the alphabet. The next character along decodes to the
    # same 16 bytes with those four bits dirty, which is exactly the
    # non-canonical spelling age requires a reader to reject.
    dirty = _B64_ALPHABET[_B64_ALPHABET.index(salt[-1]) + 1 :][:1]
    replacement = salt[:-1] + dirty

    with pytest.raises(AgeError, match="canonically encoded"):
        _decrypt(artifact.replace(salt, replacement, 1))


def test_an_empty_passphrase_is_refused_at_the_writer() -> None:
    with pytest.raises(ValueError, match="empty passphrase"):
        EncryptingWriter(io.BytesIO(), "", work_factor=_TEST_WORK_FACTOR)


def test_a_work_factor_the_reader_would_refuse_is_refused_at_the_writer() -> None:
    """Writing what nothing can read back is the one asymmetry worth closing early."""
    with pytest.raises(ValueError, match="outside"):
        EncryptingWriter(io.BytesIO(), _KEYPHRASE, work_factor=MAX_WORK_FACTOR + 1)


def test_the_highest_work_factor_this_module_accepts_has_an_expressible_memory_budget() -> None:
    """The ceiling is real, and it is CPython's rather than a taste.

    ``hashlib.scrypt`` refuses a ``maxmem`` at or above 2 GiB, and it refuses it on
    the argument alone — so this reproduces the failure at ``N=2`` instead of
    allocating the gigabyte the real derivation would. Without it, an artifact at
    :data:`MAX_WORK_FACTOR` would fail to open on the recovery machine, which is
    the one place a surprise is unaffordable.
    """
    budget = scrypt_maxmem(1 << MAX_WORK_FACTOR)

    hashlib.scrypt(b"x", salt=b"y", n=2, r=8, p=1, dklen=32, maxmem=budget)


def test_the_default_work_factor_is_one_this_module_reads_back() -> None:
    """The write and read ceilings are asymmetric, and the default sits under both."""
    assert 1 <= DEFAULT_WORK_FACTOR <= MAX_WORK_FACTOR


def test_an_artifact_declares_the_work_factor_it_was_written_at() -> None:
    artifact = _encrypt(b"the accumulated model", work_factor=9)

    assert artifact.split(b"\n")[1].endswith(b" 9")


def test_an_oversized_header_line_is_refused_before_it_is_allocated() -> None:
    """The header is parsed before it can be authenticated, so its cost is capped.

    age's MAC covers the header, and the key that checks the MAC comes *out* of
    the header — so a reader has no way to authenticate before parsing. An
    unbounded ``readline`` on a line with no terminator allocates the whole line,
    which is a recovery machine's memory spent on an artifact it is about to
    refuse anyway.
    """
    absurd = b"age-encryption.org/v1\n-> scrypt " + b"A" * (2 * 1024 * 1024)

    with pytest.raises(AgeError, match="runs past"):
        _decrypt(absurd)


def test_a_stanza_body_that_never_ends_is_refused() -> None:
    """The body loop's only exit is a short line, so an artifact that never writes
    one runs it forever — the same hazard as the line length, one level up.
    """
    endless = (
        b"age-encryption.org/v1\n"
        + b"-> scrypt "
        + base64.b64encode(b"\x00" * 16).rstrip(b"=")
        + b" 8\n"
        + (b"A" * 64 + b"\n") * 500
    )

    with pytest.raises(AgeError, match="body lines"):
        _decrypt(endless)


def test_a_legitimate_header_is_nowhere_near_the_bounds() -> None:
    """The bounds are headroom, not a constraint the format bumps into."""
    artifact = _encrypt(b"the accumulated model")
    header = artifact[: artifact.index(b"\n", artifact.index(b"--- ")) + 1]

    lines = header.split(b"\n")
    assert max(len(line) for line in lines) < 128
    assert len(lines) < 8
