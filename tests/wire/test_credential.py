"""The device credential: its entropy, its shape, and what the hub keeps of it.

ADR-0124 §6 fixes all three, and each clause here is one of them rather than a
property of the implementation that happened to satisfy it.
"""

from __future__ import annotations

import base64
import re
from typing import Final

from ai_assistant.wire.codec import CONNECT_PAYLOAD_BYTES, encode_projection
from ai_assistant.wire.credential import (
    CREDENTIAL_ENTROPY_BYTES,
    is_well_formed,
    mint_credential,
    verifier_for,
    verifies,
)
from ai_assistant.wire.envelope import MAX_IDENTIFIER_BYTES, connect_payload

#: ADR-0124 §6's floor: "a value of at least 128 bits drawn from the operating
#: system's cryptographic random source".
_MINIMUM_BITS: Final = 128


def test_a_credential_carries_at_least_the_entropy_the_clause_requires() -> None:
    """ADR-0124 §6: "at least 128 bits".

    Asserted on the **decoded** value rather than on the string's length, because
    the string is base64 and 43 characters of it are not 43 bytes of entropy — a
    scheme that encoded 8 bytes into a 43-character alphabet would pass a length
    check and miss the clause by a factor of four.
    """
    decoded = base64.urlsafe_b64decode(mint_credential() + "=")
    assert len(decoded) == CREDENTIAL_ENTROPY_BYTES
    assert len(decoded) * 8 >= _MINIMUM_BITS


def test_two_credentials_differ() -> None:
    """The discriminating half of the clause above: a constant would satisfy it.

    A thousand draws rather than two, so a generator seeded once per process — the
    classic way a random source stops being one — fails here rather than being
    discovered by a device that inherited another device's credential.
    """
    assert len({mint_credential() for _ in range(1000)}) == 1000


def test_the_scheme_admits_what_it_mints_and_nothing_shaped_differently() -> None:
    """ADR-0124 §7's well-formedness test, which decides a refusal before a verifier.

    The negatives are the ones a peer actually sends: an empty string, a truncated
    paste, one character too many, and a value carrying a character the alphabet
    does not have. Each must be refused, because §7 has them "refused as a
    credential that did not verify" with the value never reaching the comparison.
    """
    minted = mint_credential()
    assert is_well_formed(minted)
    assert not is_well_formed("")
    assert not is_well_formed(minted[:-1])
    assert not is_well_formed(minted + "x")
    assert not is_well_formed(minted[:-1] + "+")


def test_the_verifier_names_its_algorithm_and_does_not_contain_the_credential() -> None:
    """ADR-0124 §6: "the hub retains only a verifier from which the credential
    cannot be recovered, so the hub holds no device's Tier 0 secret at rest".

    Recovery is not something a test can disprove in general; what it can pin is the
    two things that would make it trivially false — the credential appearing in the
    stored value, and the value being something other than a fixed-width digest.
    """
    credential = mint_credential()
    verifier = verifier_for(credential)
    assert credential not in verifier
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", verifier)


def test_a_verifier_is_a_function_of_the_credential_alone() -> None:
    """No salt, deliberately, and the record depends on it.

    ADR-0124 §6 names a "cryptographic hash rather than a memory-hard password
    derivation" because "an attacker cannot enumerate the space at any work factor,
    and a memory-hard derivation on the hub's admission path is a cost paid on every
    connect for nothing". A verifier that varied per call would also make the
    registry's stored value unusable, which is what this pins.
    """
    credential = mint_credential()
    assert verifier_for(credential) == verifier_for(credential)
    assert verifier_for(credential) != verifier_for(mint_credential())


def test_verification_accepts_the_credential_and_refuses_every_other() -> None:
    """The two-sided property: a comparison that always said yes would pass one half."""
    credential = mint_credential()
    other = mint_credential()
    verifier = verifier_for(credential)
    assert verifies(credential, verifier)
    assert not verifies(other, verifier)
    assert not verifies(credential, verifier_for(other))


def test_verification_refuses_a_verifier_under_an_unknown_algorithm() -> None:
    """The algorithm tag is inside the compared bytes, which is why this holds.

    A scheme that split the tag off and compared digests alone could compare a
    ``sha256`` digest against something else of the same width and match. Here the
    tag travels with the digest, so a verifier this build cannot have written can
    only ever fail — which is the safe direction and ADR-0083 §6's test.
    """
    credential = mint_credential()
    stored = verifier_for(credential).removeprefix("sha256:")
    assert not verifies(credential, f"blake2b:{stored}")


def test_a_connect_payload_carrying_a_credential_stays_inside_the_ratified_bound() -> None:
    """ADR-0124 §6: the encoded form "leaves the connect payload within ADR-0085
    §8d's 256-byte bound, which this ADR does not raise".

    Measured at the **worst case the contract admits** — a client identifier at
    ADR-0085 §8d's own 64-byte bound — rather than at the identifier this tree
    happens to use, because a scheme that fitted only beside a short name would be
    one a conforming client could overflow.
    """
    payload = connect_payload(client="c" * MAX_IDENTIFIER_BYTES, credential=mint_credential())
    assert len(encode_projection(payload)) <= CONNECT_PAYLOAD_BYTES
