"""What the gateway refuses to start with, and what it reads (ADR-0202 §§2, 3, 6, 8).

**None of this needs a socket**, which is why it is a module of its own rather than
more cases in ``test_gateway_remote_listener``. Every clause here is decided before
anything is bound — §8: the gateway "refuses at start, before it binds or discloses
a bootstrap value" — so the subject is
:func:`~ai_assistant.interfaces.gateway.tls.remote_tls` and a directory of files.
What only a connection can show, the other module shows.

**Both halves of §8's split are tested, in the two places the split puts them.**
``Settings`` refuses "a value that is blank or has no UTF-8 form, and the three
combinations" — that is ``tests/core/test_gateway_settings.py``, where the model
lives. Everything "only the machine can answer" is here.

Marked ``integration`` because every case writes key material to the filesystem and
reads it back, which is what the marker names.
"""

from __future__ import annotations

import datetime
import os
import re
from typing import TYPE_CHECKING, Any, Final

import pytest
from gateway_timing import Clock, Timers
from gateway_tls import issue_pair

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.interfaces.gateway.server import Gateway
from ai_assistant.interfaces.gateway.tls import remote_tls
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

#: The overlay name the certificate is obtained for, and the one the owner configures.
_NAME: Final = "laptop.tail2e4542.ts.net"

#: An overlay address ``Settings`` admits. Nothing here binds it.
_OVERLAY: Final = "100.64.0.9"

#: What the clock reads. Certificates are issued against it rather than against the
#: wall clock, because ADR-0202 §8 measures validity from the injected clock.
_NOW: Final = Clock().reading


class _AnyAgent:
    """An overlay agent that is merely *present*.

    ADR-0174 §3 makes the agent the sole source of a browsing device's identity, and
    the gateway's constructor refuses a remote listener configured on without one —
    so a case about the certificate needs one to reach the certificate at all.
    Nothing here asks it anything: the identity query happens per connection and the
    bind confirmation happens at ``start_remote``, and this module binds nothing.
    """

    async def identify(self, host: str, port: int) -> str:
        """Never called from this module."""
        raise AssertionError(host, port)


def _settings(certificate: Path | str, key: Path | str, **overrides: Any) -> Settings:
    """Settings with the remote listener on and a pair configured."""
    overrides.setdefault("gateway_remote_host_names", (_NAME,))
    return Settings(
        gateway_remote_address=_OVERLAY,
        gateway_remote_tls_certificate=str(certificate),
        gateway_remote_tls_key=str(key),
        **overrides,
    )


def _read(certificate: Path | str, key: Path | str, **overrides: Any) -> Any:
    """Run the whole start-time read over one configured pair."""
    return remote_tls(_settings(certificate, key, **overrides), now=Clock())


# --- ADR-0202 §2 and §8: the pair exists, is readable, and is a pair ----------


def test_a_loopback_only_gateway_reads_nothing_and_touches_no_path() -> None:
    """§2 leaves the loopback listener untouched, and §8's paths are unset with the
    switch — so a gateway with no remote listener is byte for byte what it was, and
    this returns before a filesystem is involved at all."""
    assert remote_tls(Settings(), now=Clock()) is None


def test_an_absent_certificate_is_refused_at_start(tmp_path: Path) -> None:
    """§2: a gateway "whose certificate or key is absent … **does not start, and
    reports why**".

    It does not bind the loopback listener alone and continue, and it does not bind
    the remote listener without TLS — so the refusal is raised rather than logged.
    """
    _, key = issue_pair(tmp_path, names=(_NAME,), issued_at=_NOW)

    with pytest.raises(ConfigurationError, match="cannot be read"):
        _read(tmp_path / "absent.pem", key)


def test_an_absent_key_is_refused_at_start(tmp_path: Path) -> None:
    """The same clause on the other half of the pair."""
    certificate, key = issue_pair(tmp_path, names=(_NAME,), issued_at=_NOW)
    key.unlink()

    with pytest.raises(ConfigurationError, match="gateway_remote_tls_key"):
        _read(certificate, key)


def test_a_path_that_is_not_a_file_is_refused(tmp_path: Path) -> None:
    """A directory where a certificate should be is §2's "unusable" arriving early,
    and naming it that way is cheaper than an OpenSSL error about a directory."""
    _, key = issue_pair(tmp_path, names=(_NAME,), issued_at=_NOW)

    with pytest.raises(ConfigurationError, match="not a regular file"):
        _read(tmp_path, key)


def test_a_certificate_that_is_not_a_certificate_is_refused(tmp_path: Path) -> None:
    """§2's "unusable", reached from the certificate's own side.

    The ordinary way to get here is pointing the two settings at the same file, or at
    each other, so the refusal says which file it wanted where.
    """
    certificate, key = issue_pair(tmp_path, names=(_NAME,), issued_at=_NOW)
    certificate.write_bytes(b"not a certificate at all")

    with pytest.raises(ConfigurationError, match="not a PEM certificate"):
        _read(certificate, key)


def test_a_key_that_does_not_belong_to_the_certificate_is_refused(tmp_path: Path) -> None:
    """§2's "mismatched", and §8's "that the key matches the certificate".

    Two pairs issued for the same name, crossed. Every other check passes — both
    files exist, both are owned by this user, both are usable material, the
    certificate is in date and carries the configured name — so this is the one
    condition left, and it is the one an owner hits by copying one file from a backup.
    """
    certificate, _ = issue_pair(tmp_path, names=(_NAME,), issued_at=_NOW)
    other = tmp_path / "other"
    other.mkdir()
    _, stranger = issue_pair(other, names=(_NAME,), issued_at=_NOW)

    with pytest.raises(ConfigurationError, match="not a usable pair"):
        _read(certificate, stranger)


# --- ADR-0202 §3: ownership and mode, the key stricter than the certificate ---


def test_a_key_owned_by_another_user_is_refused(tmp_path: Path, monkeypatch: Any) -> None:
    """§3: the gateway refuses "a **key** file whose **owner is not the user the
    gateway runs as**".

    Driven by moving the *gateway* rather than the file, because a test cannot own a
    file as somebody else: the effective uid is what the predicate compares against,
    and reading it through ``os.geteuid`` is what makes that substitutable.
    """
    certificate, key = issue_pair(tmp_path, names=(_NAME,), issued_at=_NOW)
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)

    with pytest.raises(ConfigurationError, match="is owned by uid"):
        _read(certificate, key)


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o660, 0o601, 0o610])
def test_a_key_granting_anything_to_group_or_other_is_refused(tmp_path: Path, mode: int) -> None:
    """§3: the gateway refuses a key "whose mode grants any permission to group or
    other" — read, write and execute alike.

    This is ADR-0004 §4's owner-only posture ("owner-only file permissions (0600) in
    the user's data directory") applied to key material rather than to a store, and
    it is deliberately not a claim that no other user can read the key: an ACL
    survives an owner-only mode and §3 forbids any lane presenting the check as more
    than it is.
    """
    certificate, key = issue_pair(tmp_path, names=(_NAME,), issued_at=_NOW, key_mode=mode)

    with pytest.raises(ConfigurationError, match="gateway_remote_tls_key"):
        _read(certificate, key)


@pytest.mark.parametrize("mode", [0o664, 0o646, 0o622])
def test_a_certificate_writable_by_others_is_refused(tmp_path: Path, mode: int) -> None:
    """§3's certificate predicate, which "is **not** weaker than the key's by
    oversight, and adversarial review is why it is stated at all".

    ``wire/custody.py`` supplies ancestor conditions only, so a certificate owned by
    the gateway's user but group-writable in a safe directory would pass everything
    else this ADR asks — and another local user could replace it, before start, with
    one carrying the configured name and **this key's own public key**, which needs
    no access to the private key, signed by an authority no browser trusts. Every
    other check would pass and every browser would refuse the chain.
    """
    certificate, key = issue_pair(tmp_path, names=(_NAME,), issued_at=_NOW, certificate_mode=mode)

    with pytest.raises(ConfigurationError, match="gateway_remote_tls_certificate"):
        _read(certificate, key)


def test_a_world_readable_certificate_is_admitted(tmp_path: Path) -> None:
    """§3 permits it "because the certificate is public by construction (§4) and only
    its integrity is at stake".

    The discriminating half of the pair of predicates: were the certificate held to
    the key's condition, the ordinary ``0644`` an overlay agent writes would refuse
    every gateway.
    """
    certificate, key = issue_pair(tmp_path, names=(_NAME,), issued_at=_NOW, certificate_mode=0o644)

    assert _read(certificate, key) is not None


def test_a_pair_under_a_directory_anyone_can_replace_it_through_is_refused(
    tmp_path: Path,
) -> None:
    """§3: the gateway refuses "either path failing the custody conditions
    ``wire/custody.py`` already owns for a path trusted rather than authenticated".

    A world-writable directory with no sticky bit lets any local user rename the
    entry beneath it, which is precisely the property that walk exists to check — and
    the key file's own mode says nothing about it.
    """
    exposed = tmp_path / "exposed"
    exposed.mkdir()
    certificate, key = issue_pair(exposed, names=(_NAME,), issued_at=_NOW)
    exposed.chmod(0o777)

    with pytest.raises(ConfigurationError, match="sits under"):
        _read(certificate, key)


# --- ADR-0202 §8: the moment of binding is inside the validity period ---------


def test_an_expired_certificate_is_refused_and_the_bound_is_named(tmp_path: Path) -> None:
    """§2 names an expired certificate among the conditions a gateway does not start
    on, and §2's residual is stated rather than closed: it "takes the gateway down,
    including its loopback listener".

    The remedy in the message is the one §4 gives — renew, restart — because a
    renewed certificate "takes effect when the gateway is **next started**".
    """
    certificate, key = issue_pair(
        tmp_path,
        names=(_NAME,),
        issued_at=_NOW,
        not_before=_NOW - datetime.timedelta(days=90),
        not_after=_NOW - datetime.timedelta(seconds=1),
    )

    with pytest.raises(ConfigurationError, match="expired at"):
        _read(certificate, key)


def test_a_certificate_not_yet_in_force_is_refused_and_says_which_bound(
    tmp_path: Path,
) -> None:
    """§8: "one not yet in force is refused exactly as an expired one is, and the
    refusal names the bound it failed".

    §5 records that adversarial review found this on the ADR's sixth round: expiry
    alone left "a certificate whose validity had not begun" passing every check and
    binding a listener every browser rejects. A clock this machine disagrees with is
    the ordinary way there, "and it is the one case where the gateway's refusal is
    more useful than the browser's, because the gateway can say which bound failed
    and the browser cannot".
    """
    certificate, key = issue_pair(
        tmp_path,
        names=(_NAME,),
        issued_at=_NOW,
        not_before=_NOW + datetime.timedelta(days=1),
        not_after=_NOW + datetime.timedelta(days=90),
    )

    with pytest.raises(ConfigurationError, match="is not valid until"):
        _read(certificate, key)


def test_a_certificate_inside_both_bounds_is_admitted(tmp_path: Path) -> None:
    """The bounds are inclusive of everything between them, and nothing else here
    turns on the clock."""
    certificate, key = issue_pair(
        tmp_path,
        names=(_NAME,),
        issued_at=_NOW,
        not_before=_NOW - datetime.timedelta(seconds=1),
        not_after=_NOW + datetime.timedelta(seconds=1),
    )

    material = _read(certificate, key)

    assert material.not_before < _NOW < material.not_after


# --- ADR-0202 §6: every configured name is one the certificate presents -------


def test_an_empty_host_name_list_is_refused_under_a_configured_listener(
    tmp_path: Path,
) -> None:
    """§6: the gateway refuses "unless **every** element of
    ``gateway_remote_host_names`` is a name the configured certificate presents, and
    the list is non-empty".

    This supersedes one sentence of ADR-0174 §8 — "empty is the default, so a gateway
    configured on serves the address it bound and nothing else" — and §6 argues why:
    "the alternative — leaving the empty list to start a gateway no browser can reach
    — is the silent dead end §2 refuses one section earlier, and it would be worse
    here, because the owner's evidence would be a certificate warning on a phone".
    """
    certificate, key = issue_pair(tmp_path, names=(_NAME,), issued_at=_NOW)

    with pytest.raises(ConfigurationError, match="gateway_remote_host_names is empty"):
        _read(certificate, key, gateway_remote_host_names=())


def test_a_configured_name_the_certificate_does_not_present_is_named_in_the_refusal(
    tmp_path: Path,
) -> None:
    """§6: "It names the elements that failed."

    Every element rather than some, which §6 argues from a stale name left over from
    a rename: a list carrying one name the certificate covers and one it does not
    "starts a gateway whose list still carries an authority the certificate does not
    cover — a name ADR-0174 §6 dutifully admits as a `Host` value and no browser can
    ever reach".
    """
    certificate, key = issue_pair(tmp_path, names=(_NAME,), issued_at=_NOW)

    with pytest.raises(ConfigurationError, match=re.escape("['old.tail2e4542.ts.net']")):
        _read(certificate, key, gateway_remote_host_names=(_NAME, "old.tail2e4542.ts.net"))


def test_a_name_carried_only_in_the_common_name_does_not_count(tmp_path: Path) -> None:
    """A certificate presents its ``subjectAltName`` and nothing else.

    No browser has honoured a common name since 2017, so a gateway that read one
    would start on a configured authority every browser refuses — the silent dead end
    §6 exists to remove, reached by being generous about the wrong field.
    """
    certificate, key = issue_pair(tmp_path, names=(), issued_at=_NOW, common_name=_NAME)

    with pytest.raises(ConfigurationError, match="does not present"):
        _read(certificate, key)


def test_an_address_the_certificate_carries_counts_as_a_name_it_presents(
    tmp_path: Path,
) -> None:
    """A ``subjectAltName`` IP entry is an identity a browser matches an authority
    against, so an owner whose overlay wrote its address into the certificate is not
    refused for configuring it."""
    certificate, key = issue_pair(tmp_path, names=(_NAME,), addresses=(_OVERLAY,), issued_at=_NOW)

    material = _read(certificate, key, gateway_remote_host_names=(_NAME, _OVERLAY))

    assert material.names == (_NAME, _OVERLAY)


def test_the_comparison_is_literal(tmp_path: Path) -> None:
    """ADR-0174 §6's rule, which this section works inside rather than widening.

    Folding case here would admit a configured name against a certificate carrying
    its lower-cased form — and then no browser could reach it anyway, because the
    `Host` a browser sends is lower-cased and ADR-0174 §6 compares *that* literally
    against the same configured set. Passing here and failing there would rebuild the
    dead end §6 removes.
    """
    certificate, key = issue_pair(tmp_path, names=(_NAME,), issued_at=_NOW)

    with pytest.raises(ConfigurationError, match="does not present"):
        _read(certificate, key, gateway_remote_host_names=(_NAME.upper(),))


# --- where the refusal happens: at construction, before anything is minted ----


def test_the_gateway_refuses_in_its_constructor_before_it_binds_or_mints(
    tmp_path: Path,
) -> None:
    """§8: the gateway "refuses at start, **before it binds or discloses a bootstrap
    value**".

    :func:`~ai_assistant.interfaces.gateway.server.run_gateway` mints and discloses
    between the constructor and the bind, so a refusal raised at the bind would come
    after a value the owner had already been handed — and ADR-0182 §2 would leave
    them holding one that died with the process it never got.
    """
    certificate, key = issue_pair(tmp_path, names=("wrong.example.ts.net",), issued_at=_NOW)

    with pytest.raises(ConfigurationError, match="does not present"):
        Gateway(
            settings=_settings(certificate, key),
            engine=FakeAssistantEngine(),
            now=Clock(),
            defer=Timers(),
            bundle={},
            agent=_AnyAgent(),
        )
