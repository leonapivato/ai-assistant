"""One certificate and key on disk, for the gateway's own checks (ADR-0202).

**A self-signed pair is the right instrument here and this is not a contradiction
of §1.** ADR-0202 §1 refuses a self-signed certificate for a *deployment*, and it
is explicit about what that clause binds: "The clause above binds **the owner's
provisioning act and the design of any lane**, and it is not a start-time check. No
clause of this ADR requires the gateway to determine a certificate's issuer, its
provenance, or whether the name it carries is one the overlay assigned; the gateway
checks what §8 enumerates and nothing else, and a certificate that passes those
checks is bound whatever its origin." So a pair generated here exercises every
check the gateway actually makes, and a test that obtained one from a public
authority would exercise exactly the same ones — over the network, on a name it
does not own.

**Generated in-process rather than shelled out to ``openssl``.** ``cryptography``
is already a direct dependency of this project and the gateway itself reads
certificates with it, so the test needs no binary that may or may not be on the
machine running the suite. Elliptic-curve keys rather than RSA, because a P-256
key takes microseconds to generate and the harness makes a fresh pair per gateway.

**No temporary directory is created here.** Every function takes the directory to
write into, so the caller's ``tmp_path`` or ``TemporaryDirectory`` owns the
lifetime and nothing is left behind.

**Named ``gateway_tls``, not ``tls``**, for the reason ``gateway_timing.py`` gives
for its own name: the test tree carries no packages, so two modules of one name is
a ``mypy`` refusal rather than a preference.
"""

from __future__ import annotations

import datetime
import ipaddress
import ssl
from typing import TYPE_CHECKING, Final

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

#: How long a pair is valid for unless a case says otherwise. Long enough that a
#: suite running at any hour is inside it, short enough to be an ordinary figure.
_LIFETIME: Final = datetime.timedelta(days=30)

#: How far before "now" validity begins by default, so a machine whose clock is a
#: second behind the one that generated the pair is not inside the near bound's
#: refusal by accident.
_BACKDATE: Final = datetime.timedelta(minutes=5)


def issue_pair(  # noqa: PLR0913 — one keyword per property of a certificate a case varies
    directory: Path,
    *,
    names: Sequence[str] = (),
    addresses: Sequence[str] = (),
    issued_at: datetime.datetime | None = None,
    not_before: datetime.datetime | None = None,
    not_after: datetime.datetime | None = None,
    certificate_mode: int = 0o644,
    key_mode: int = 0o600,
    common_name: str | None = None,
) -> tuple[Path, Path]:
    """Write one self-signed certificate and its key into ``directory``.

    Args:
        directory: Where to write ``certificate.pem`` and ``key.pem``.
        names: The DNS names the certificate presents in its ``subjectAltName``.
        addresses: The IP addresses it presents there.
        issued_at: The instant the pair is issued at, which the two bounds are
            measured from, or ``None`` for the wall clock. A gateway under test
            usually reads an injected clock rather than this machine's, so a pair
            issued against the wall clock would be refused by ADR-0202 §8's near
            bound on the day the two disagree — which is a fault in the harness and
            not in the gateway.
        not_before: When validity begins, or ``None`` for five minutes before
            ``issued_at``.
        not_after: When it ends, or ``None`` for thirty days after it.
        certificate_mode: The certificate's permission bits. The default is what
            ADR-0202 §3 permits — world-readable, because the certificate is public
            by construction, and writable by nobody but its owner.
        key_mode: The key's permission bits. The default is §3's requirement: no
            permission at all to group or other.
        common_name: A subject common name to carry, or ``None`` for a subject
            naming nothing in particular. It is never a name the gateway reads —
            :func:`~ai_assistant.interfaces.gateway.tls._presented_names` takes the
            ``subjectAltName`` and nothing else — which is exactly what a case
            passing this asserts.

    Returns:
        The certificate's path and the key's path, in that order.
    """
    now = issued_at if issued_at is not None else datetime.datetime.now(datetime.UTC)
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, common_name or "a gateway under test")]
    )
    alternatives: list[x509.GeneralName] = [x509.DNSName(name) for name in names]
    alternatives.extend(x509.IPAddress(ipaddress.ip_address(one)) for one in addresses)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before if not_before is not None else now - _BACKDATE)
        .not_valid_after(not_after if not_after is not None else now + _LIFETIME)
    )
    if alternatives:
        builder = builder.add_extension(x509.SubjectAlternativeName(alternatives), critical=False)
    certificate = builder.sign(key, hashes.SHA256())
    certificate_path = directory / "certificate.pem"
    key_path = directory / "key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    certificate_path.chmod(certificate_mode)
    key_path.chmod(key_mode)
    return certificate_path, key_path


def browser_context(certificate: Path) -> ssl.SSLContext:
    """A client that trusts exactly this certificate and checks the name, as a browser does.

    Verification is left **on**, which is the whole point of driving the listener
    through one: a case that turned it off would pass against a gateway presenting
    anything at all, and the name binding ADR-0202 §6 exists to obtain would go
    untested. A self-signed leaf loaded as a trust anchor is accepted by OpenSSL as
    itself, so nothing here needs a separate authority.

    Args:
        certificate: The certificate the gateway serves, trusted as its own anchor.

    Returns:
        A client context that completes a handshake with that gateway and with
        nothing else.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(certificate))
    return context
