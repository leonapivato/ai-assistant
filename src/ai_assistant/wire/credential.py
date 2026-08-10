"""The device credential: what it is, how it is minted, how it is checked.

ADR-0124 §6 fixes the shape and §7 fixes what the wire may carry, and both live
here rather than beside the enrolment record because **the credential is a
wire-carried value**: its well-formedness is what §7 tests *before* a verifier is
consulted, and that test has to be available to the frame reader
(:mod:`ai_assistant.wire.envelope`) which cannot import the hub.

**The verifier is a plain cryptographic hash and that is a ruling, not a
shortcut** (ADR-0124 §6):

    "Use Argon2" is correct advice about a secret a human chose and wrong about
    128 bits of ``urandom``: an attacker cannot enumerate the space at any work
    factor, and a memory-hard derivation on the hub's admission path is a cost
    paid on every connect for nothing.

What a comparison can still leak is timing, so :func:`verifies` compares in
constant time.

**The encoded form is chosen to fit ADR-0085 §8d's 256-byte connect payload**,
which ADR-0124 §6 declines to raise: 32 bytes of ``urandom`` render as 43
``base64url`` characters, so a connect payload carrying a client identifier and a
credential is comfortably inside the bound. A scheme whose credential does not fit
— a certificate chain, a signed token carrying claims — is refused by that clause
rather than by amending ADR-0085.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Final

#: How many bytes of the operating system's cryptographic random source one
#: credential is drawn from. ADR-0124 §6 requires **at least 128 bits**; 256 is
#: taken because it costs nine characters of a payload with room to spare and
#: removes any argument about the margin.
CREDENTIAL_ENTROPY_BYTES: Final[int] = 32

#: The length of the encoded form — ``base64url`` of
#: :data:`CREDENTIAL_ENTROPY_BYTES` with no padding, which is what
#: :func:`secrets.token_urlsafe` produces.
CREDENTIAL_CHARACTERS: Final[int] = 43

#: The scheme §6 mints, as a pattern. ADR-0124 §7 refuses "a string that is not a
#: well-formed value of the scheme §6 mints" *as a credential that did not
#: verify*, and the value "never reaches the verifier or the comparison" — so this
#: has to be decidable from the string alone, with no enrolment record in hand.
_WELL_FORMED: Final = re.compile(rf"\A[A-Za-z0-9_-]{{{CREDENTIAL_CHARACTERS}}}\Z")

#: The verifier's algorithm tag, written into every verifier. Naming the algorithm
#: in the stored value is what makes a later change legible: a verifier whose tag
#: this build does not know is state this build cannot serve correctly, which is
#: ADR-0083 §6's test rather than a silent mis-comparison.
_ALGORITHM: Final = "sha256"


def mint_credential() -> str:
    """Draw one credential from the operating system's random source.

    Returns:
        The credential, in the encoded form the connect frame carries. It is
        disclosed to the owner once and never again (ADR-0124 §6) — the caller is
        the only place it exists in this process, and the hub retains only
        :func:`verifier_for` of it.
    """
    return secrets.token_urlsafe(CREDENTIAL_ENTROPY_BYTES)


def is_well_formed(value: str) -> bool:
    """Whether a string is a value of the scheme :func:`mint_credential` mints.

    Args:
        value: The candidate, already known to be a string.

    Returns:
        Whether it is well formed.
    """
    return _WELL_FORMED.match(value) is not None


def verifier_for(credential: str) -> str:
    """The value the hub retains, from which the credential cannot be recovered.

    Args:
        credential: The credential just minted.

    Returns:
        ``"sha256:<hex>"`` — the algorithm tag and the digest.
    """
    digest = hashlib.sha256(credential.encode("utf-8")).hexdigest()
    return f"{_ALGORITHM}:{digest}"


def verifies(credential: str, verifier: str) -> bool:
    """Whether a presented credential matches a stored verifier, in constant time.

    **The comparison is over the encoded verifier rather than over raw digests**,
    which keeps the algorithm tag inside the compared bytes: a verifier stored
    under an algorithm this build does not know can then only ever fail to match,
    where a scheme that split the tag off and compared the digests alone could
    compare a ``sha256`` digest against something else of the same width.

    Args:
        credential: What the connect frame carried. Well-formedness is the
            caller's to establish first (ADR-0124 §7): a malformed value never
            reaches this comparison.
        verifier: What the enrolment record holds.

    Returns:
        Whether the two agree.
    """
    return hmac.compare_digest(verifier_for(credential), verifier)
