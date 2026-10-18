"""A fake sign-in edge: a test key, and the assertions it signs (ADR-0327 §6).

A plain module beside ``gateway_mint`` and ``gateway_timing``, and for the same
reason: ``mypy`` refuses a second ``conftest.py`` where the test tree carries no
packages.

**The real edge is the private repository's** (ADR-0327 §2:1, §14:3), so what stands
in for it here is the one thing a gateway ever sees of it: a compact JWS signed with
Ed25519 over the claims §6 checks, carried in one ``Edge-Assertion`` header. The key
pair is generated per edge, so no private key is written into this repository — the
"detect private key" hook would refuse one, and rightly.

**Every way of being wrong is a keyword**, so a case that is about one condition
states that condition and inherits everything else from an assertion the gateway
accepts. That is what keeps a refusal case from passing for the wrong reason: the
only thing wrong with the token it sends is the thing it names.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

if TYPE_CHECKING:
    from datetime import datetime

#: The claims a configured gateway in these tests holds an assertion to.
ISSUER: Final = "https://signin.example.test"
AUDIENCE: Final = "hub-owner-01"
SUBJECT: Final = "acct_7f3a9c02"

#: The door's public hostname, which the hosted listener admits as its `Host`.
DOOR: Final = "door.example.test"

#: The origin a page through the door has (ADR-0327 §7:3).
DOOR_ORIGIN: Final = f"https://{DOOR}"

#: The hosted browser device the operator names (ADR-0327 §10).
HOSTED_DEVICE: Final = "web-owner"

#: A marker no claim can be set to, for "leave this claim out".
OMIT: Final = object()


def b64url(raw: bytes) -> str:
    """Unpadded base64url, the encoding compact JWS and RFC 8037's ``x`` use."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def segment(value: Any) -> str:
    """One JSON value as a JWS segment."""
    return b64url(json.dumps(value, separators=(",", ":")).encode("utf-8"))


@dataclass
class FakeEdge:
    """One edge: its key, and what it signs.

    Attributes:
        key: The private key it signs with, generated for this edge alone.
    """

    key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)

    @property
    def public_key(self) -> str:
        """The public key, in the form ``gateway_edge_public_keys`` takes."""
        raw = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return b64url(raw)

    def settings(self, **overrides: Any) -> dict[str, Any]:
        """The hosted listener's settings, configured for this edge.

        Args:
            **overrides: Any field to replace.

        Returns:
            Keyword arguments for ``Settings``.
        """
        return {
            "gateway_hosted_address": "127.0.0.1",
            "gateway_hosted_host_name": DOOR,
            "gateway_hosted_device": HOSTED_DEVICE,
            "gateway_edge_public_keys": (self.public_key,),
            "gateway_edge_issuer": ISSUER,
            "gateway_edge_audience": AUDIENCE,
            "gateway_edge_subject": SUBJECT,
            **overrides,
        }

    def sign(  # noqa: PLR0913 — one keyword per claim a case may get wrong
        self,
        now: datetime,
        *,
        header: dict[str, Any] | None = None,
        iss: object = ISSUER,
        aud: object = AUDIENCE,
        sub: object = SUBJECT,
        iat: object = None,
        exp: object = None,
        lifetime: float = 30.0,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """One assertion, as the edge attaches it to a request it forwards.

        Args:
            now: The instant it is issued at, unless ``iat`` says otherwise.
            header: The JWS header, or ``None`` for ``{"alg": "EdDSA", "typ": "JWT"}``.
            iss: The issuer, or :data:`OMIT`.
            aud: The audience, or :data:`OMIT`.
            sub: The subject, or :data:`OMIT`.
            iat: The issued-at time, ``None`` for ``now``, or :data:`OMIT`.
            exp: The expiry, ``None`` for ``iat + lifetime``, or :data:`OMIT`.
            lifetime: Seconds from ``iat`` to ``exp`` where ``exp`` is ``None``.
            extra: Further claims.

        Returns:
            The compact JWS.
        """
        issued = now.timestamp() if iat is None else iat
        expires = exp
        if exp is None:
            expires = issued + lifetime if isinstance(issued, int | float) else OMIT
        claims: dict[str, Any] = {
            "iss": iss,
            "aud": aud,
            "sub": sub,
            "iat": issued,
            "exp": expires,
            **(extra or {}),
        }
        body = {name: value for name, value in claims.items() if value is not OMIT}
        return self.sign_raw(header or {"alg": "EdDSA", "typ": "JWT"}, segment(body))

    def sign_raw(self, header: dict[str, Any], claims_segment: str) -> str:
        """Sign an already-encoded claims segment under ``header``.

        Args:
            header: The JWS header.
            claims_segment: The encoded claims.

        Returns:
            The compact JWS.
        """
        signed = f"{segment(header)}.{claims_segment}"
        return f"{signed}.{b64url(self.key.sign(signed.encode('ascii')))}"
