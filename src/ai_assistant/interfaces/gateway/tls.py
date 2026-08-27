"""The remote browser listener's TLS material, read once at start (ADR-0202).

**What this module is.** ADR-0202 §1 has the gateway's remote browser listener
serve HTTPS and terminate TLS "in the gateway's own process", on a certificate the
overlay obtained for the machine's own overlay name. This module is everything
between the two ``Settings`` paths and the :class:`ssl.SSLContext` the listener
binds with: the refusals §§2, 3, 6 and 8 put at start, and the three facts §5
discloses.

**Why it is a module of its own rather than four functions in ``server.py``.**
Everything here is decided before a socket exists and never again — §4: "The
gateway reads the certificate and the key when it binds and does not re-read them
while it runs; no clause of this ADR obliges a reload, and no lane may present the
gateway as renewing, watching or reloading anything." Keeping it apart is what
makes that readable: there is one entry point, it is called once, and nothing in
the request path can reach the filesystem through it.

**When it runs, which is earlier than "at bind" sounds.** §8 requires the gateway
to refuse "at start, before it binds or discloses a bootstrap value", so
:func:`remote_tls` is called from :class:`~.server.Gateway`'s constructor — before
ADR-0182 §1's mint act is installed, before ADR-0168 §5's value is minted, and
before either listener is bound. The only thing between it and the bind is that
mint, which §8 orders after it, so the pair is still read exactly once and still
read for the bind alone.

**Every refusal here is a stay-down deployment fault** (ADR-0083 §5) and reaches
the owner as ADR-0168 §5's shape — "does not start, and reports why". §2 admits no
softer outcome: "It does not bind the loopback listener alone and continue, and it
does not bind the remote listener without TLS."

**What is deliberately not checked, because §1 says so in terms.** No clause of
ADR-0202 "requires the gateway to determine a certificate's issuer, its provenance,
or whether the name it carries is one the overlay assigned; the gateway checks what
§8 enumerates and nothing else, and a certificate that passes those checks is bound
whatever its origin". §1's issuance and public-trust requirements bind the owner's
provisioning act and this lane's design; they are not start-time checks and no
function here pretends to make one.
"""

from __future__ import annotations

import os
import ssl
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from cryptography import x509

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.wire.custody import displayable, first_ancestor_fault

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from collections.abc import Callable
    from datetime import datetime

    from ai_assistant.core.config import Settings

#: Every permission bit outside the owner's. The key file may carry none of them
#: (ADR-0202 §3), because the key is Tier 0 under ADR-0004 §1 and this is ADR-0004
#: §4's ``0600`` posture applied to key material rather than to a store.
_ANY_PERMISSION_TO_OTHERS: Final = stat.S_IRWXG | stat.S_IRWXO

#: The write bits outside the owner's. The certificate carries the weaker of the two
#: conditions, "while permitting it to be world-readable, because the certificate is
#: public by construction (§4) and only its integrity is at stake".
_WRITE_BY_OTHERS: Final = stat.S_IWGRP | stat.S_IWOTH


@dataclass(frozen=True, slots=True)
class RemoteTls:
    """One certificate and key, read and checked, with what §5 discloses about them.

    Attributes:
        context: The context the remote listener terminates TLS with. Built once,
            holding the certificate chain and the private key, and never rebuilt
            (§4).
        names: The identities the certificate presents to a browser — its
            ``subjectAltName`` entries and nothing else. §6's check is made against
            this, and §5 discloses it.
        not_before: The instant the certificate's validity begins.
        not_after: The instant it ends. §5 discloses this one, because §4 puts
            renewal in the owner's hands and "what makes that workable rather than a
            trap is that every start tells the owner how long they have".
        path: Where the certificate was read from, so a refusal about it names the
            file without the caller carrying the path alongside.
    """

    context: ssl.SSLContext
    names: tuple[str, ...]
    not_before: datetime
    not_after: datetime
    path: Path

    def refuse_outside_its_validity(self, instant: datetime) -> None:
        """Refuse unless ``instant`` lies inside both bounds (ADR-0202 §8).

        > … that the moment of binding lies **inside the certificate's validity
        > period at both bounds** — one not yet in force is refused exactly as an
        > expired one is, and the refusal names the bound it failed.

        **Both bounds, and the near one is not hypothetical** (§5). Adversarial
        review on the ADR found that an earlier draft enumerated expiry alone, so "a
        certificate whose validity had not begun passed every check and bound a
        listener every browser rejects". A certificate issued against a clock this
        machine disagrees with is the ordinary way to arrive there, "and it is the
        one case where the gateway's refusal is more useful than the browser's,
        because the gateway can say which bound failed and the browser cannot".

        **Asked twice, and :meth:`~.server.Gateway.start_remote` carries why.** §8's
        sentence puts this check "at start, before it binds or discloses a bootstrap
        value" *and* states it about "the moment of binding", and those cannot both
        be literal once a bootstrap value is disclosed in between. Asking at both
        moments satisfies both halves: everything the configuration itself gets
        wrong is refused before the owner is handed anything, and a clock that moved
        in the interval is caught before the listener binds. It reads nothing off the
        filesystem either way — the bounds are the ones parsed at start — so §4's
        "does not re-read them while it runs" is untouched.

        Args:
            instant: The reading of the gateway's own clock.

        Raises:
            ConfigurationError: If the certificate is not yet in force, or has
                expired.
        """
        shown = displayable(self.path)
        if instant < self.not_before:
            msg = (
                f"gateway_remote_tls_certificate={shown} is not valid until "
                f"{self.not_before.isoformat()}, and it is now {instant.isoformat()}. "
                f"Every browser would refuse it, so the gateway does not bind a listener "
                f"with it (ADR-0202 §2, §8). Usually this machine's clock is behind the "
                f"one the certificate was issued against"
            )
            raise ConfigurationError(msg)
        if instant > self.not_after:
            msg = (
                f"gateway_remote_tls_certificate={shown} expired at "
                f"{self.not_after.isoformat()}, and it is now {instant.isoformat()}. "
                f"Renew it with your overlay and start the gateway again — a renewed "
                f"certificate takes effect at the next start (ADR-0202 §4) — or unset "
                f"ASSISTANT_GATEWAY_REMOTE_ADDRESS together with both paths to serve "
                f"browsers over the loopback listener alone (ADR-0202 §2)"
            )
            raise ConfigurationError(msg)


def remote_tls(settings: Settings, *, now: Callable[[], datetime]) -> RemoteTls | None:
    """Read the configured pair, or refuse to start (ADR-0202 §§2, 3, 6, 8).

    The checks run in §8's own order — "existence, custody and permissions (§3),
    that the key matches the certificate, that the moment of binding lies **inside
    the certificate's validity period at both bounds** … and §6's name check" —
    because each later one is only meaningful once the earlier has passed, and
    because an owner fixing them one at a time is told about the outermost first.

    Args:
        settings: The loaded configuration. ``gateway_remote_address`` is the
            switch, and ``Settings`` has already refused every combination where the
            two paths and the switch disagree (§8).
        now: The clock, injected, and the same one the gateway reads everywhere
            else. §8's validity check is about "the moment of binding", so it is a
            reading of this and never of the wall clock directly.

    Returns:
        The material the listener binds with, or ``None`` where no remote browser
        listener is configured — in which case nothing is read and no path is
        touched, which is what keeps ADR-0168 §2's loopback-only gateway byte for
        byte what it was.

    Raises:
        ConfigurationError: On every condition §§2, 3 and 6 refuse at start. Each is
            a stay-down fault: restarting unchanged never succeeds, and what has to
            change is the configuration, the files' permissions, or the certificate
            the owner installed.
    """
    if settings.gateway_remote_address is None:
        return None
    if settings.gateway_remote_tls_certificate is None or settings.gateway_remote_tls_key is None:
        # Unreachable through `Settings`, which refuses the pairing at load (§8).
        # Stated rather than asserted, because a gateway composed from a `Settings`
        # built some other way must still not bind a door with no certificate.
        msg = (
            "gateway_remote_address is set, so the remote browser listener serves "
            "HTTPS and nothing else (ADR-0202 §2) — but no certificate and key were "
            "configured. Set gateway_remote_tls_certificate and gateway_remote_tls_key"
        )
        raise ConfigurationError(msg)
    certificate_path = Path(settings.gateway_remote_tls_certificate)
    key_path = Path(settings.gateway_remote_tls_key)
    _refuse_material_another_user_controls(
        certificate_path, setting="gateway_remote_tls_certificate", secret=False
    )
    _refuse_material_another_user_controls(key_path, setting="gateway_remote_tls_key", secret=True)
    certificate = _read_the_certificate(certificate_path)
    material = RemoteTls(
        context=_build_the_context(certificate_path, key_path),
        names=_presented_names(certificate),
        not_before=certificate.not_valid_before_utc,
        not_after=certificate.not_valid_after_utc,
        path=certificate_path,
    )
    material.refuse_outside_its_validity(now())
    _refuse_a_configured_name_the_certificate_does_not_carry(
        settings, material.names, certificate_path
    )
    return material


def _refuse_material_another_user_controls(path: Path, *, setting: str, secret: bool) -> None:
    """Hold one file to §3's ownership-and-mode predicate and to the custody walk.

    > The gateway refuses at start a **key** file whose **owner is not the user the
    > gateway runs as**, or whose mode grants any permission to group or other. It
    > refuses a **certificate** file on the same ownership condition and on a
    > **writability** one — no group or other write — while permitting it to be
    > world-readable, because the certificate is public by construction (§4) and only
    > its integrity is at stake. It refuses either path failing the custody
    > conditions ``wire/custody.py`` already owns for a path trusted rather than
    > authenticated. It reports which condition failed and on which path. (§3)

    **The certificate's own predicate is not an oversight and adversarial review is
    why it exists** (§3). ``wire/custody.py`` supplies ancestor conditions only, so a
    certificate owned by the gateway's user but group-writable in a safe directory
    would otherwise pass everything else this ADR asks — and another local user could
    replace it, before start, with one carrying the configured name and this key's own
    public key, signed by an authority no browser trusts. Every other check would pass
    and every browser would refuse the chain.

    **What this is not** (§3, ADR-0084 §1). It is ownership and mode, "and it is
    deliberately not a claim that no other user can read the key": a POSIX ACL
    survives an owner-only mode, no ACL-aware check exists in this tree, and no
    caller may present this as establishing that the key is unreadable by other
    users.

    Args:
        path: The configured path.
        setting: The setting that named it, for a refusal an owner can act on.
        secret: Whether this is the key, which takes the stricter mode condition.

    Raises:
        ConfigurationError: If the file is absent, is not a regular file, is owned by
            another user, grants more than §3 allows, or sits under an ancestor an
            untrusted user could replace it through.
    """
    shown = displayable(path)
    try:
        info = path.stat()
    except OSError as exc:
        msg = (
            f"{setting}={shown} cannot be read: {displayable(exc.strerror)}. The remote "
            f"browser listener serves HTTPS and has no plain-HTTP fallback, so a gateway "
            f"that cannot read its certificate or key does not start (ADR-0202 §2). "
            f"Obtain the pair for this machine's own overlay name and point both settings "
            f"at the files your overlay wrote, or unset ASSISTANT_GATEWAY_REMOTE_ADDRESS "
            f"together with both paths"
        )
        raise ConfigurationError(msg) from exc
    if not stat.S_ISREG(info.st_mode):
        msg = (
            f"{setting}={shown} is not a regular file, so it is not the certificate or "
            f"key the overlay wrote there (ADR-0202 §3). Point the setting at the file "
            f"itself rather than at the directory holding it"
        )
        raise ConfigurationError(msg)
    euid = os.geteuid()
    if info.st_uid != euid:
        msg = (
            f"{setting}={shown} is owned by uid {info.st_uid} and this gateway runs as "
            f"uid {euid}. ADR-0202 §3 requires both files to be owned by the user the "
            f"gateway runs as, because the private key is Tier 0 (ADR-0004 §1) and the "
            f"certificate's integrity decides which chain a browser is offered. Obtain "
            f"the pair as the user that runs the gateway, or chown both files to it"
        )
        raise ConfigurationError(msg)
    forbidden = _ANY_PERMISSION_TO_OTHERS if secret else _WRITE_BY_OTHERS
    mode = stat.S_IMODE(info.st_mode)
    if mode & forbidden:
        allowed = "0600" if secret else "0644"
        grants = (
            "any permission to group or other" if secret else "write permission to group or other"
        )
        because = (
            "the private key is Tier 0 and this is ADR-0004 §4's owner-only posture "
            "applied to key material"
            if secret
            else "another local user could otherwise replace it, before start, with a "
            "certificate carrying the configured name and this key's own public key, "
            "signed by an authority no browser trusts (ADR-0202 §3)"
        )
        msg = (
            f"{setting}={shown} has mode {mode:04o}, which grants {grants}. ADR-0202 §3 "
            f"refuses it, because {because}. Run `chmod {allowed}` on it"
        )
        raise ConfigurationError(msg)
    try:
        fault = first_ancestor_fault(path)
    except OSError as exc:
        msg = (
            f"{setting}={shown} could not have its ancestry checked: "
            f"{displayable(exc.strerror)} at {displayable(exc.filename)}. ADR-0202 §3 "
            f"holds both paths to the custody conditions this system already applies to "
            f"a path trusted rather than authenticated, and a directory that cannot be "
            f"read cannot be judged"
        )
        raise ConfigurationError(msg) from exc
    if fault is not None:
        detail = (
            f"is writable by others without the sticky bit (mode {fault.mode:04o})"
            if fault.kind == "replaceable"
            else f"is owned by uid {fault.uid}, which is neither root nor this process's"
        )
        msg = (
            f"{setting}={shown} sits under {displayable(fault.ancestor)}, which {detail}, "
            f"so an untrusted user could replace the file before the gateway opens it "
            f"(ADR-0202 §3). Move the pair somewhere only you can write — the same "
            f"condition the data directory and the overlay agent socket are held to"
        )
        raise ConfigurationError(msg)


def _read_the_certificate(path: Path) -> x509.Certificate:
    """Parse the leaf certificate, which is what a browser is asked to trust.

    **The leaf and not the chain.** A file the overlay wrote may carry the leaf
    followed by an issuing certificate; the leaf is the first, it is the one that
    carries the names §6 checks and the validity §8 checks, and it is the one whose
    expiry §5 discloses. Everything after it is presented by :meth:`ssl.SSLContext.
    load_cert_chain` and needs no reading here.

    Args:
        path: The configured certificate path, already held to §3's predicate.

    Returns:
        The leaf certificate.

    Raises:
        ConfigurationError: If the file cannot be read, or carries no certificate
            this system can parse — §2's "unusable", reached from the certificate's
            own side.
    """
    shown = displayable(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        msg = (
            f"gateway_remote_tls_certificate={shown} cannot be read: "
            f"{displayable(exc.strerror)}. A gateway whose certificate is unreadable "
            f"does not start and does not fall back to plain HTTP (ADR-0202 §2)"
        )
        raise ConfigurationError(msg) from exc
    try:
        return x509.load_pem_x509_certificate(raw)
    except ValueError as exc:
        msg = (
            f"gateway_remote_tls_certificate={shown} is not a PEM certificate this "
            f"system can read ({exc}). ADR-0202 §2 refuses an unusable certificate at "
            f"start rather than binding a listener no browser can complete a handshake "
            f"with; point the setting at the certificate your overlay wrote, not at the "
            f"key and not at a request"
        )
        raise ConfigurationError(msg) from exc


def _build_the_context(certificate_path: Path, key_path: Path) -> ssl.SSLContext:
    """Build the one context the listener terminates TLS with (ADR-0202 §1, §2).

    **This is also where the pair is proved to be a pair.** ``load_cert_chain``
    refuses a key that does not belong to the certificate, which is §2's "mismatched"
    and §8's "that the key matches the certificate" — a check made by OpenSSL over
    the two files rather than restated here, because a second implementation of it
    would be a second thing to get wrong.

    **Client certificates are not requested and none is checked.** ADR-0174 §3
    already decides who may connect, from the overlay agent on this machine and from
    nothing the peer asserts, and §5 of ADR-0202 orders that check *ahead* of the
    handshake. A TLS-level client requirement would be a second admission rule
    answering a question already answered.

    Args:
        certificate_path: The certificate, and any chain after it.
        key_path: Its private key.

    Returns:
        A server context holding both.

    Raises:
        ConfigurationError: If the key does not belong to the certificate, if either
            file is not usable material, or if either cannot be read.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(certfile=str(certificate_path), keyfile=str(key_path))
    except ssl.SSLError as exc:
        msg = (
            f"gateway_remote_tls_certificate={displayable(certificate_path)} and "
            f"gateway_remote_tls_key={displayable(key_path)} are not a usable pair "
            f"({exc}). Either the key does not belong to the certificate or one of the "
            f"two is not material this system can load, and ADR-0202 §2 refuses both at "
            f"start rather than binding a listener that could never complete a "
            f"handshake. Point the two settings at the certificate and the key your "
            f"overlay wrote for this machine, in that order"
        )
        raise ConfigurationError(msg) from exc
    except OSError as exc:
        # `ssl.SSLError` is itself an `OSError`, so this arm is reached only by a
        # genuine filesystem failure between §3's check and this read.
        msg = (
            f"the remote browser listener's certificate or key could not be read: "
            f"{displayable(exc.strerror)} at {displayable(exc.filename)}. A gateway that "
            f"cannot read them does not start (ADR-0202 §2)"
        )
        raise ConfigurationError(msg) from exc
    return context


def _presented_names(certificate: x509.Certificate) -> tuple[str, ...]:
    """What the certificate offers a browser as its identity, in the browser's terms.

    **``subjectAltName`` and nothing else.** No browser has honoured a common name
    since 2017, so admitting one here would start a gateway whose configured
    authority every browser refuses — the silent dead end §6 exists to remove,
    reached by being generous about the wrong field.

    **DNS names and IP addresses both**, because both are identities a browser
    matches an authority against, and an overlay that writes its own address into the
    certificate should not have its owner refused for it. Everything else a
    ``subjectAltName`` can carry — an email address, a URI — names nothing a browser
    compares a host against and is left out.

    Args:
        certificate: The leaf.

    Returns:
        The names, in the order the certificate carries them. Empty where the
        certificate has no ``subjectAltName`` at all, which §6 then refuses against
        the owner's configured list.
    """
    try:
        alternative = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return ()
    presented = alternative.value
    return (
        *presented.get_values_for_type(x509.DNSName),
        *(str(address) for address in presented.get_values_for_type(x509.IPAddress)),
    )


def _refuse_a_configured_name_the_certificate_does_not_carry(
    settings: Settings, names: tuple[str, ...], path: Path
) -> None:
    """Refuse a host-name list the certificate does not cover (ADR-0202 §6).

    > The gateway refuses at start, and reports why, unless **every** element of
    > ``gateway_remote_host_names`` is a name the configured certificate presents,
    > and the list is non-empty. It names the elements that failed.

    **Every element rather than one, and adversarial review on the ADR is why** (§6).
    Asking only that *some* configured name match "starts a gateway whose list still
    carries an authority the certificate does not cover — a name ADR-0174 §6
    dutifully admits as a `Host` value and no browser can ever reach". A stale name
    left over from a rename is the ordinary way to get one.

    **Non-empty, which supersedes one sentence of ADR-0174 §8** (§6, §10 of
    ADR-0202). Empty is still the default for a gateway whose remote listener is off;
    a gateway configured *on* with an empty list does not start, because the
    alternative "leaves the empty list to start a gateway no browser can reach".

    **Compared literally, which is ADR-0174 §6's own rule and is the stricter
    reading on purpose.** Folding case here would admit a configured
    ``Laptop.tailnet.ts.net`` against a certificate carrying
    ``laptop.tailnet.ts.net`` — and then no browser could reach it anyway, because
    the `Host` a browser sends is lower-cased and ADR-0174 §6 compares *that*
    literally against the same configured set. A comparison that passed here and
    failed there would rebuild the dead end this section removes. Wildcards are
    likewise not expanded: this system authors no host-matching rules, and an owner
    whose certificate carries one names the covered name in the setting.

    Args:
        settings: The loaded configuration, for the configured list.
        names: What :func:`_presented_names` read off the certificate.
        path: The certificate's path, for a refusal that names the file.

    Raises:
        ConfigurationError: If the list is empty, or carries an element the
            certificate does not present.
    """
    configured = settings.gateway_remote_host_names
    shown = displayable(path)
    if not configured:
        msg = (
            f"gateway_remote_host_names is empty while the remote browser listener is "
            f"configured on. The listener now serves HTTPS, so a browser reaches it at a "
            f"name the certificate carries and not at the address it bound, and a gateway "
            f"with no configured name is one no browser can reach (ADR-0202 §6). Set "
            f"ASSISTANT_GATEWAY_REMOTE_HOST_NAMES to the name your certificate was "
            f"obtained for — {shown} presents {list(names)}"
        )
        raise ConfigurationError(msg)
    uncovered = [name for name in configured if name not in names]
    if uncovered:
        msg = (
            f"gateway_remote_host_names carries {uncovered}, which "
            f"gateway_remote_tls_certificate={shown} does not present — it presents "
            f"{list(names)}. A browser refuses the certificate before the request "
            f"exists, so every one of those names is an authority the gateway would "
            f"admit a `Host` for and no browser could ever reach (ADR-0202 §6). Remove "
            f"the uncovered names, or obtain a certificate that covers them"
        )
        raise ConfigurationError(msg)
