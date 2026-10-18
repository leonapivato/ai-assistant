"""What the gateway accepts as the sign-in edge's assertion (ADR-0327 §6).

**The edge is the sign-in service in front of the door** (§2:1): a program outside
this repository that holds a person's sign-in, routes each signed-in account to that
person's gateway, and attaches to every request it forwards an **assertion** it signs
— "a value the edge signs and attaches to one request it forwards, stating which
account is signed in and for which hub" (§2:4). The gateway checks every one itself,
"because any process on the box can reach a loopback port and set a header, and none
can forge the edge's signature without the edge's private key".

**The check is closed, and it is all here.** A JSON Web Token in compact JWS form, in
exactly one ``Edge-Assertion`` header (§6:1); signed with Ed25519 and nothing else,
the algorithm never taken from the token (§6:2); verified only against the keys the
operator configured, a ``jwk``, ``jku``, ``x5u``, ``x5c`` or ``kid`` member deciding
nothing (§6:3); and accepted only on its issuer, its audience as one string, its
subject, and its times read with no leeway (§6:6 to §6:10). Each failure is one
:class:`AssertionFault`, the first the check reaches, and §7:7 records which.

**Nothing here fetches anything** (§3:4): the keys arrive as configuration, decoded
once when the gateway is built.

**The assertion is Tier 0 and this module is its whole custody** (§9). It is held in
a local for the length of one call and is placed in no exception, no log record and
no return value: :func:`check_assertion` answers with a fault or with nothing, and no
path through it raises with the token's bytes in hand. "No failure of the check
admits anything" (§6:14), so a failure this module did not foresee is a refusal too.

**No library parses the token**, deliberately. A general JOSE library is built to do
what §6:2 and §6:3 forbid — choose an algorithm from the header, find a key from it —
and its defaults are the attack surface those two clauses close. What §6 needs is
three base64url segments, two JSON objects and one Ed25519 verification, which
``cryptography`` (already a dependency, ADR-0202) provides.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ai_assistant.core.errors import ConfigurationError

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from datetime import datetime, timedelta

    from ai_assistant.core.config import Settings

#: The request header the edge carries its assertion in (ADR-0327 §6:1), lower-cased
#: as :meth:`.http.Request.header` reads names.
ASSERTION_HEADER: Final = "edge-assertion"

#: The one algorithm §6:2 admits, as a JWS header names it (RFC 8037 §3.1).
_ALGORITHM: Final = "EdDSA"

#: How many bytes an Ed25519 signature is (RFC 8032 §5.1.6).
_SIGNATURE_BYTES: Final = 64

#: One unpadded base64url segment, the only alphabet compact JWS uses (RFC 7515 §2).
#: Checked before decoding, because the standard library's decoder discards a
#: character outside its alphabet rather than refusing it.
_SEGMENT: Final = re.compile(r"[A-Za-z0-9_-]+")

#: How many dot-separated segments a compact JWS carries (RFC 7515 §7.1).
_SEGMENTS: Final = 3


class AssertionFault(StrEnum):
    """Which check an assertion failed: ADR-0327 §7:7's seven conditions.

    "The condition names which check failed: no assertion, a malformed one, its
    signature, its issuer, its audience, its subject, or its times." The values are
    what the admission record carries; a browser is told none of them (§7:6).
    """

    ABSENT = "assertion-absent"
    """No ``Edge-Assertion`` header, or more than one (§6:1)."""

    MALFORMED = "assertion-malformed"
    """Not a compact JWS whose header and claims are each one JSON object."""

    SIGNATURE = "assertion-signature"
    """Not an Ed25519 signature that one configured key verifies (§6:2, §6:3)."""

    ISSUER = "assertion-issuer"
    """``iss`` is not ``gateway_edge_issuer`` (§6:6)."""

    AUDIENCE = "assertion-audience"
    """``aud`` is not the one string ``gateway_edge_audience`` (§6:7)."""

    SUBJECT = "assertion-subject"
    """``sub`` is not ``gateway_edge_subject`` (§6:8)."""

    TIMES = "assertion-times"
    """``iat``, ``exp`` or ``nbf`` puts the assertion outside its life (§6:10)."""


@dataclass(frozen=True)
class EdgeTerms:
    """What a hosted listener holds an assertion to, read once from configuration.

    Attributes:
        keys: The edge's public keys (§6:3, §6:4). Decoded at start and never
            replaced: "No request on any listener may add to, remove from or replace
            the set" (§6:5).
        issuer: ``gateway_edge_issuer``.
        audience: ``gateway_edge_audience``.
        subject: ``gateway_edge_subject``. Never logged and never in a record (§7:8).
        max_age: ``gateway_edge_assertion_max_age``.
    """

    keys: tuple[Ed25519PublicKey, ...]
    issuer: str
    audience: str
    subject: str
    max_age: timedelta

    def __repr__(self) -> str:
        """Name the terms without the subject, which §7:8 keeps out of every record."""
        return f"EdgeTerms(keys={len(self.keys)}, max_age={self.max_age!r})"


def edge_terms(settings: Settings) -> EdgeTerms | None:
    """The terms the hosted listener checks against, or ``None`` where it is off.

    ``Settings`` has already refused a partial configuration (§6:12, §6:13) and every
    key that is not 32 bytes of unpadded base64url. What is left is turning the text
    into keys, which is a fact about ``cryptography`` rather than about the string.

    Args:
        settings: The loaded configuration.

    Returns:
        The terms, or ``None`` where ``gateway_hosted_address`` is unset.

    Raises:
        ConfigurationError: If a key cannot be loaded as an Ed25519 public key, which
            is a stay-down fault: a door configured with it refuses every request.
    """
    if settings.gateway_hosted_address is None:
        return None
    issuer = settings.gateway_edge_issuer
    audience = settings.gateway_edge_audience
    subject = settings.gateway_edge_subject
    if issuer is None or audience is None or subject is None:  # pragma: no cover
        msg = "the hosted listener is configured on without the edge's claims"
        raise ConfigurationError(msg)
    keys: list[Ed25519PublicKey] = []
    for position, text in enumerate(settings.gateway_edge_public_keys):
        raw = _decoded(text)
        try:
            if raw is None:
                raise ValueError(text)
            keys.append(Ed25519PublicKey.from_public_bytes(raw))
        except ValueError as exc:
            msg = (
                f"gateway_edge_public_keys[{position}] is not a usable Ed25519 public key "
                f"(ADR-0327 §6:4), so the door would refuse everything it signs"
            )
            raise ConfigurationError(msg) from exc
    return EdgeTerms(
        keys=tuple(keys),
        issuer=issuer,
        audience=audience,
        subject=subject,
        max_age=settings.gateway_edge_assertion_max_age,
    )


def check_assertion(token: str | None, *, terms: EdgeTerms, now: datetime) -> AssertionFault | None:
    """Decide one request's assertion (ADR-0327 §6), or say which check it failed.

    **The order is the order a refusal is recorded in**, "the first the gateway
    evaluates that the request fails" (ADR-0168 §6:10): presence, form, signature,
    then the claims. The signature is verified before a claim is read, so nothing an
    unauthenticated peer wrote into the payload is parsed at all.

    Args:
        token: The single ``Edge-Assertion`` value, or ``None`` where the request
            carried none or more than one (:meth:`.http.Request.header`).
        terms: What the assertion is held to.
        now: The gateway's present time. No leeway is applied: "the edge and the
            gateway read one clock, on one box" (§6:10).

    Returns:
        ``None`` where the assertion is accepted, and otherwise the fault.
    """
    if token is None:
        return AssertionFault.ABSENT
    try:
        return _check(token, terms=terms, now=now)
    except Exception:  # §6:14: "No failure of the check admits anything"
        return AssertionFault.MALFORMED


def _check(token: str, *, terms: EdgeTerms, now: datetime) -> AssertionFault | None:  # noqa: PLR0911 — one return per check §6 orders, and the order is the point
    """:func:`check_assertion`'s body, which may raise and is refused if it does."""
    segments = token.split(".")
    if len(segments) != _SEGMENTS:
        return AssertionFault.MALFORMED
    encoded_header, encoded_claims, encoded_signature = segments
    header = _object(encoded_header)
    signature = _decoded(encoded_signature)
    if header is None or signature is None or _segment(encoded_claims) is None:
        return AssertionFault.MALFORMED
    # RFC 7515 §4.1.11: a `crit` naming an extension the recipient does not
    # understand makes the token invalid, and this recipient understands none.
    if "crit" in header:
        return AssertionFault.MALFORMED
    # §6:2: Ed25519 and nothing else, and never the algorithm the token names. The
    # header's `alg` is read only to refuse a token that claims another one, `none`
    # included; the verification below is Ed25519 whatever it said.
    if header.get("alg") != _ALGORITHM or len(signature) != _SIGNATURE_BYTES:
        return AssertionFault.SIGNATURE
    signed = f"{encoded_header}.{encoded_claims}".encode("ascii")
    if not any(_verifies(key, signature, signed) for key in terms.keys):
        return AssertionFault.SIGNATURE
    claims = _object(encoded_claims)
    if claims is None:
        return AssertionFault.MALFORMED
    return _claims_fault(claims, terms=terms, now=now)


def _claims_fault(  # noqa: PLR0911 — one return per claim §6:6 to §6:10 checks
    claims: dict[str, Any], *, terms: EdgeTerms, now: datetime
) -> AssertionFault | None:
    """§6:6 to §6:10, on claims whose signature has verified."""
    if claims.get("iss") != terms.issuer or not isinstance(claims.get("iss"), str):
        return AssertionFault.ISSUER
    # §6:7: "An `aud` that is a list is refused, so one assertion never admits to two
    # hubs" — the type is checked, and a list holding only this audience is refused.
    audience = claims.get("aud")
    if not isinstance(audience, str) or audience != terms.audience:
        return AssertionFault.AUDIENCE
    subject = claims.get("sub")
    if not isinstance(subject, str) or subject != terms.subject:
        return AssertionFault.SUBJECT
    issued = _instant(claims, "iat")
    expires = _instant(claims, "exp")
    present = now.timestamp()
    if issued is None or expires is None:
        return AssertionFault.TIMES
    if "nbf" in claims:
        not_before = _instant(claims, "nbf")
        if not_before is None or not_before > present:
            return AssertionFault.TIMES
    if issued > present or expires <= present:
        return AssertionFault.TIMES
    if expires - issued > terms.max_age.total_seconds():
        return AssertionFault.TIMES
    return None


def _instant(claims: dict[str, Any], name: str) -> float | None:
    """A NumericDate claim (RFC 7519 §2), or ``None`` where it is absent or not one.

    A ``bool`` is an ``int`` to Python and is not a date to anyone, so it is refused;
    a non-finite number never reaches here, because :func:`_object` refuses ``NaN``
    and the infinities as it parses.
    """
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _verifies(key: Ed25519PublicKey, signature: bytes, signed: bytes) -> bool:
    """Whether one configured key verifies the signature over the signing input."""
    try:
        key.verify(signature, signed)
    except InvalidSignature:
        return False
    return True


def _segment(text: str) -> str | None:
    """``text`` where it is one non-empty unpadded base64url segment, else ``None``."""
    return text if _SEGMENT.fullmatch(text) else None


def _decoded(text: str) -> bytes | None:
    """The bytes one base64url segment encodes, or ``None`` where it is not one."""
    if _segment(text) is None:
        return None
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError:
        return None


def _object(text: str) -> dict[str, Any] | None:
    """One segment decoded as exactly one JSON object, or ``None``.

    **A member named twice is refused rather than resolved**, for the reason
    :meth:`.http.Request.header` refuses a repeated header: a parser that took the
    last of two ``sub`` members would let whoever wrote the object choose which one
    it is judged on, and a second parser reading the first would judge another.
    ``NaN`` and the infinities are refused for the same reason — they are not JSON
    (RFC 8259 §6), and a time compared against one is no comparison.
    """
    raw = _decoded(text)
    if raw is None:
        return None
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_members,
        parse_constant=_no_constant,
    )
    return value if isinstance(value, dict) else None


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object, refusing a member named twice."""
    built: dict[str, Any] = {}
    for name, value in pairs:
        if name in built:
            msg = "a member is named twice"
            raise ValueError(msg)
        built[name] = value
    return built


def _no_constant(name: str) -> Any:
    """Refuse ``NaN``, ``Infinity`` and ``-Infinity``, which are not JSON."""
    msg = f"{name} is not a JSON number"
    raise ValueError(msg)


__all__ = [
    "ASSERTION_HEADER",
    "AssertionFault",
    "EdgeTerms",
    "check_assertion",
    "edge_terms",
]
