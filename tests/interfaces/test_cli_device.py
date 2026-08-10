"""The adapter's half of the hop: which hub, and the two acts at this device.

Three things, all of them thin (golden rule 3): choosing the transport from
configuration (ADR-0124 §1), storing what the hub disclosed at enrolment (§6), and
removing it again (§8). The logic each wraps lives in ``wire``; what is asserted
here is that the adapter wires it, renders it, and adds nothing.
"""

from __future__ import annotations

import asyncio
from io import StringIO
from typing import TYPE_CHECKING

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import SecretScope
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeSecretStore
from ai_assistant.wire import HubEngineClient, RemoteHubEngineClient
from ai_assistant.wire.credential import mint_credential
from ai_assistant.wire.enrolment import enrolment_name, read_enrolment

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path

HUB = "nQ8xYt2CNTRL"


@pytest.fixture
def rendered(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Capture what the adapter printed.

    Wide, because the assertions below are about sentences: Rich wraps at the
    console's width, and a check for a phrase that landed across a line break would
    fail on the rendering rather than on the behaviour.
    """
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=200))
    return buffer


@pytest.fixture
def secrets(monkeypatch: pytest.MonkeyPatch) -> FakeSecretStore:
    """The device's ``ENROLMENT`` store, standing in for the keyring-backed one.

    Substituted at the one function that composes it, which is also the assertion
    that there *is* one such function: an adapter that built a store at each call
    site would not be reachable this way.
    """
    store = FakeSecretStore(scope=SecretScope.ENROLMENT)
    monkeypatch.setattr(cli, "_enrolment_secrets", lambda _settings: store)
    return store


# --- which hub a command talks to (ADR-0124 §1) ------------------------------


def test_no_remote_address_gives_a_client_of_the_hub_on_this_machine(tmp_path: Path) -> None:
    """The default, and the one every existing command already had."""
    client = cli._client_for(Settings(data_dir=tmp_path))

    assert isinstance(client, HubEngineClient)
    assert client.socket_path == tmp_path / "hub.sock"


def test_a_remote_address_gives_a_client_of_a_hub_on_another_machine(
    tmp_path: Path, secrets: FakeSecretStore
) -> None:
    """And it is given the reading face and nothing wider (ADR-0125 §8).

    The connect path "is given ``Secrets`` and nothing wider" — a client that held
    the whole seam could delete the credential it reads, and neither the type system
    nor review would notice.
    """
    del secrets
    settings = Settings(data_dir=tmp_path, remote_hub_address="100.64.1.7", remote_hub_port=50084)

    client = cli._client_for(settings)

    assert isinstance(client, RemoteHubEngineClient)
    assert client.destination.host == "100.64.1.7"
    assert client.destination.port == 50084


def test_a_destination_no_conforming_hub_holds_is_refused_before_anything_opens(
    tmp_path: Path,
) -> None:
    """Refused where the destination is composed, which is before any I/O.

    ADR-0124 §2 forbids a listener to bind a public address, so a client pointed at
    one is pointed at something that is not this hub — and the refusal is a sentence
    rather than a connection attempt to whatever *is* there.
    """
    settings = Settings(data_dir=tmp_path, remote_hub_address="8.8.8.8")

    with pytest.raises(ConfigurationError):
        cli._client_for(settings)


def test_the_two_transports_are_not_a_fallback_for_one_another(tmp_path: Path) -> None:
    """ADR-0084 §9's rule applied to the choice: a remote hub is never silently local.

    A client that fell back would serve the wrong store, from the wrong device,
    while looking like success — which is the one failure mode ruling 4 exists to
    prevent.
    """
    settings = Settings(data_dir=tmp_path, remote_hub_address="100.64.1.7")

    assert not isinstance(cli._client_for(settings), HubEngineClient)


# --- enrolment intake at the device (ADR-0124 §6) ----------------------------


def test_enrolment_stores_both_values_and_says_what_it_bound(
    tmp_path: Path, secrets: FakeSecretStore, rendered: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hand-off, performed at the device, with the credential off the command line.

    It arrives on standard input rather than as an argument: a Tier 0 value in
    ``argv`` is in the shell's history and in every process listing on the machine,
    which is the disclosure ADR-0124 §6 spends a section confining.
    """
    _settings(monkeypatch, tmp_path)
    credential = mint_credential()

    result = CliRunner().invoke(
        cli.app, ["device", "enrol", HUB, "--credential-stdin"], input=f"{credential}\n"
    )

    assert result.exit_code == 0, result.output
    assert HUB in rendered.getvalue()
    assert "ASSISTANT_REMOTE_HUB_ADDRESS" in rendered.getvalue()


def test_the_credential_is_prompted_for_without_echo_by_default(
    tmp_path: Path, secrets: FakeSecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No flag, no argument: the owner is asked, and what they type is not shown.

    ``--credential-stdin`` exists for a scripted run; the default has to be the one
    an owner performing this once will reach for, and it must not put a Tier 0 value
    into ``argv`` or into the terminal's scrollback.
    """
    _settings(monkeypatch, tmp_path)
    credential = mint_credential()

    result = CliRunner().invoke(cli.app, ["device", "enrol", HUB], input=f"{credential}\n")

    assert result.exit_code == 0, result.output
    assert credential not in result.output
    assert await_sync(read_enrolment(secrets)).credential.get_secret_value() == credential


def test_enrolment_puts_the_pair_where_the_connect_path_reads_it(
    tmp_path: Path, secrets: FakeSecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end through the seam, so intake and the connect-path read agree.

    Asserted through :func:`~ai_assistant.wire.enrolment.read_enrolment` rather than
    by inspecting two entries, because agreeing on the names is exactly what the two
    halves of this could get wrong independently.
    """
    _settings(monkeypatch, tmp_path)
    credential = mint_credential()

    CliRunner().invoke(
        cli.app, ["device", "enrol", HUB, "--credential-stdin"], input=f"{credential}\n"
    )

    held = await_sync(read_enrolment(secrets))
    assert held.hub_identity == HUB
    assert held.credential.get_secret_value() == credential


def test_the_credential_is_never_echoed_by_the_adapter(
    tmp_path: Path, secrets: FakeSecretStore, rendered: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not on success, and not in what the runner captured from the terminal.

    ADR-0124 §6: the credential "is never written to any database this system opens,
    never committed, and never reaches a log, an audit record or an error message".
    A terminal's scrollback is the surface an owner actually looks at.
    """
    del secrets
    _settings(monkeypatch, tmp_path)
    credential = mint_credential()

    result = CliRunner().invoke(
        cli.app, ["device", "enrol", HUB, "--credential-stdin"], input=f"{credential}\n"
    )

    assert credential not in rendered.getvalue()
    assert credential not in result.output


def test_a_mistyped_credential_is_refused_and_nothing_is_stored(
    tmp_path: Path, secrets: FakeSecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal now, rather than a hub's refusal at the first connect."""
    _settings(monkeypatch, tmp_path)

    result = CliRunner().invoke(
        cli.app, ["device", "enrol", HUB, "--credential-stdin"], input="not-a-credential\n"
    )

    assert result.exit_code == 1
    assert await_sync(secrets.get(enrolment_name())) is None


def test_a_keyring_that_cannot_be_reached_is_reported_rather_than_swallowed(
    tmp_path: Path, secrets: FakeSecretStore, rendered: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0125 §7's legible refusal, all the way out to the exit code.

    "A headless deployment with no keyring now has a defined behaviour — a legible
    refusal rather than a silent plaintext fallback." The adapter's job is to render
    it, not to reinterpret it.
    """
    _settings(monkeypatch, tmp_path)
    secrets.become_unavailable()

    result = CliRunner().invoke(
        cli.app, ["device", "enrol", HUB, "--credential-stdin"], input=f"{mint_credential()}\n"
    )

    assert result.exit_code == 1
    assert "keyring" in rendered.getvalue().lower()


# --- unenrolment at the device (ADR-0124 §8) ---------------------------------


def test_unenrolment_removes_the_pair_and_says_what_it_removed(
    tmp_path: Path, secrets: FakeSecretStore, rendered: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8's device-side act, which "needs no hub" — nothing here opens a connection.

    And it reports rather than asserts, which is ADR-0124 §8's own standard for the
    hub-side delete applied on this side of the device boundary.
    """
    _settings(monkeypatch, tmp_path)
    CliRunner().invoke(
        cli.app, ["device", "enrol", HUB, "--credential-stdin"], input=f"{mint_credential()}\n"
    )

    result = CliRunner().invoke(cli.app, ["device", "unenrol"])

    assert result.exit_code == 0, result.output
    assert await_sync(secrets.get(enrolment_name())) is None
    assert "the credential and the hub identity" in rendered.getvalue()


def test_unenrolment_says_that_the_hub_still_holds_the_enrolment(
    tmp_path: Path, secrets: FakeSecretStore, rendered: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two levers "are independent acts and neither substitutes for the other" (§8).

    "The tempting operating shortcut is to revoke at the overlay alone" — and its
    mirror here is to read this act as a revocation. A surface that let an owner
    believe that would leave a live credential whose only remaining protection is a
    network membership.
    """
    _settings(monkeypatch, tmp_path)
    CliRunner().invoke(
        cli.app, ["device", "enrol", HUB, "--credential-stdin"], input=f"{mint_credential()}\n"
    )

    CliRunner().invoke(cli.app, ["device", "unenrol"])

    assert "revoke it there" in rendered.getvalue()


def test_unenrolment_on_a_device_that_holds_nothing_is_not_a_failure(
    tmp_path: Path, secrets: FakeSecretStore, rendered: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "It works whether or not the enrolment it removes is still live" (§8).

    The case an owner reaches for it in is usually one where something has already
    gone wrong, so a non-zero exit for "there was nothing there" would be the wrong
    surface for it.
    """
    del secrets
    _settings(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli.app, ["device", "unenrol"])

    assert result.exit_code == 0, result.output
    assert "held no enrolment" in rendered.getvalue()


def test_an_unreachable_secrets_is_not_reported_as_an_empty_device(
    tmp_path: Path, secrets: FakeSecretStore, rendered: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two answers ADR-0125 §7 keeps apart, at the surface an owner reads.

    "This device is not enrolled" and "this device's keyring is locked" must not be
    one sentence: an owner told the first would stop looking, believing a purge had
    happened that had not.
    """
    _settings(monkeypatch, tmp_path)
    secrets.become_unavailable()

    result = CliRunner().invoke(cli.app, ["device", "unenrol"])

    assert result.exit_code == 1
    assert "held no enrolment" not in rendered.getvalue()


# --- the adapter's own wiring -------------------------------------------------


def test_the_store_the_adapter_composes_is_enrolment_scoped_and_installation_bound(
    tmp_path: Path,
) -> None:
    """The two facts ADR-0125 §2 binds to an instance, chosen where they are known.

    The installation is the resolved ``data_dir``, so a second data directory on one
    machine holds a different entry — the keyring is per OS user, not per data
    directory, and a QA hub's enrolment would otherwise overwrite the owner's real
    one at intake and delete it at unenrolment.
    """
    store = cli._enrolment_secrets(Settings(data_dir=tmp_path))

    assert store._scope is SecretScope.ENROLMENT
    assert store._installation == str(tmp_path)


def test_no_setting_supplies_the_enrolled_hub_identity() -> None:
    """ADR-0124 §4's third clause, as an absence, because that is its whole content.

    > The enrolled hub identity is held beside the credential… and it is **not an
    > ordinary configuration value**. Changing the client's destination address does
    > not change the identity the clause above requires it to match, and **no
    > configuration setting may override that identity**.

    That is what stops §4's second clause from being circular: an attacker with an
    editor moves the destination and leaves the check that destination has to pass
    exactly where it was. A ``Settings`` field for it would hand them both halves.
    """
    identity_shaped = {
        name
        for name in Settings.model_fields
        if "identity" in name or ("hub" in name and "identity" in name)
    }

    assert identity_shaped == set()


def _settings(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> None:
    """Point the adapter at a data directory and silence logging configuration."""
    monkeypatch.setattr(cli, "load_settings", lambda: Settings(data_dir=data_dir))
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)


def await_sync[T](awaitable: Coroutine[object, object, T]) -> T:
    """Drive one coroutine to completion from a synchronous test.

    The commands under test are synchronous — they call ``asyncio.run`` themselves —
    so the assertions about what they left behind cannot be made from inside a
    running loop.
    """
    return asyncio.run(awaitable)
