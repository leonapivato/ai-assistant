"""Where the artifact's key comes from, and where it deliberately does not.

ADR-0123 §5 is the clause the artifact's usefulness rests on: "The artifact's key
is derived from a passphrase. The tool never derives a key from machine-bound
material — a keyring-generated secret, a host identifier, a file in the data
directory — whether alone or as the sole secret input." The reason is stated
plainly there and is worth repeating where the code is: a key that lives only on
the laptop being backed up "protects nothing that matters: the thief gets the
artifact without the key, which is the case encryption is for, and the owner
whose laptop died gets the artifact without the key too, which is the case the
backup is for."

**Three sources, and none of them is this machine.** An interactive prompt, a
file the operator names, or a passphrase this tool generates and shows them. The
first is the default because it leaves no copy anywhere; the second is what makes
an unattended run possible, which §10's "a scheduler outside the hub that stops
it, runs the tool and starts it is a deployment arrangement this ADR permits"
needs and which the residue named there — "a backup nobody schedules still
lapses" — is the cost of not having; the third exists because §5 makes displaying
a generated passphrase a refusal rather than a courtesy.

**What is not here is the OS keyring cache, and that is a decision.** §5 says the
tool *may* cache the passphrase in the keyring — permissive, not required — and
the machinery that clause presumes does not exist yet: ADR-0004 §3's
``SecretStore`` has no contract on ``main``, and the ADR that would give it one is
in flight in another lane. Building a private keyring seam here would be
inventing the surface that decision is about, and adding a keyring dependency to
carry it. ``--passphrase-file`` buys the unattended run the cache was wanted for
without either. Filed rather than silently skipped; see the lane's PR.
"""

from __future__ import annotations

import getpass
import secrets
import sys
from typing import TYPE_CHECKING, Final

from ai_assistant.service.refusal import RefusalError

if TYPE_CHECKING:
    from pathlib import Path

#: The alphabet a generated passphrase is drawn from: lowercase and digits, with
#: the four characters that are read wrong off a screen removed (``l``/``1``,
#: ``o``/``0``). A passphrase an operator mistypes off their own note is a
#: passphrase they do not have.
_ALPHABET: Final = "abcdefghijkmnpqrstuvwxyz23456789"

#: Eight groups of five, hyphenated. 40 characters over a 32-symbol alphabet is
#: 200 bits, which is far past what scrypt needs to be the binding constraint,
#: and the grouping is what makes it transcribable onto paper — which is where
#: §5 wants it, since "the only custodian with a fate independent of the machine
#: is the person".
_GROUPS: Final = 8
_GROUP_SIZE: Final = 5

#: What a run using a supplied passphrase is told, every time. §5 puts the
#: obligation on the operator and requires the tool to keep it in front of them
#: rather than in a document: "a passphrase held only on this machine does not
#: survive the loss of this machine".
CUSTODY_REMINDER: Final = (
    "This passphrase is the only key to this artifact. Nothing on this machine can "
    "recover it, and a passphrase kept only on this machine does not survive losing "
    "this machine — keep a copy somewhere else."
)


def generate() -> str:
    """Mint a passphrase from the system CSPRNG.

    Returns:
        Eight hyphen-separated groups of five characters.
    """
    groups = [
        "".join(secrets.choice(_ALPHABET) for _ in range(_GROUP_SIZE)) for _ in range(_GROUPS)
    ]
    return "-".join(groups)


def resolve(*, source: Path | None, generated: bool, confirm: bool) -> str:
    """Obtain the passphrase for this run, by whichever route was asked for.

    Args:
        source: A file to read it from, or ``None``.
        generated: Whether to mint one and show it to the operator.
        confirm: Whether an interactive prompt should ask twice. True when the
            passphrase is about to key an artifact and a typo would produce one
            nobody can open; false when it is being used to open one, where a
            typo is simply a refusal.

    Returns:
        The passphrase.

    Raises:
        RefusalError: If the file cannot be read or is empty, if a prompt's two
            entries disagree, if an empty passphrase is entered, or if a
            generated passphrase cannot be shown to the operator.
    """
    if generated:
        return _generated()
    if source is not None:
        return _from_file(source)
    return _prompted(confirm=confirm)


def _generated() -> str:
    """Mint a passphrase and display it, refusing if it cannot be displayed.

    §5: "Where the tool generates a passphrase rather than receiving one, it
    displays that passphrase to the operator in the run that generates it, and
    refuses to write the artifact if it cannot." A tool that generated a key,
    filed it somewhere and reported success would have produced an artifact whose
    only key is on the machine the artifact exists to survive.

    It goes to **stderr**, not stdout: a scheduled run redirecting stdout to a
    log would otherwise write the artifact's only key into that log, and the one
    person who must see it is the one sitting at the terminal.
    """
    passphrase = generate()
    try:
        print("\n  the passphrase for this backup, shown once:\n", file=sys.stderr)
        print(f"      {passphrase}\n", file=sys.stderr)
        print(f"  {CUSTODY_REMINDER}\n", file=sys.stderr)
        sys.stderr.flush()
    except OSError as exc:
        msg = (
            "a passphrase was generated but could not be shown to you, so the artifact "
            "would have no key you hold; nothing was written"
        )
        raise RefusalError(msg) from exc
    return passphrase


def _from_file(source: Path) -> str:
    """Read a passphrase from the file the operator named.

    The first line only, with its terminator removed and nothing else stripped —
    a passphrase may legitimately begin or end with a space, and quietly trimming
    one would produce a file that opens nothing.
    """
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"the passphrase file {source} could not be read: {exc}"
        raise RefusalError(msg) from exc
    passphrase = text.split("\n", 1)[0].removesuffix("\r")
    if not passphrase:
        msg = f"the passphrase file {source} is empty, or its first line is"
        raise RefusalError(msg)
    return passphrase


def _prompted(*, confirm: bool) -> str:
    """Ask at the terminal, twice when a typo would be unrecoverable."""
    try:
        passphrase = getpass.getpass("passphrase: ")
        if confirm and getpass.getpass("passphrase (again): ") != passphrase:
            msg = "the two passphrases do not match; nothing was written"
            raise RefusalError(msg)
    except (EOFError, OSError) as exc:
        msg = (
            "no passphrase could be read from the terminal; pass --passphrase-file to run "
            "this unattended, or --generate-passphrase to have one minted and shown"
        )
        raise RefusalError(msg) from exc
    if not passphrase:
        msg = "an empty passphrase is not a key; nothing was written"
        raise RefusalError(msg)
    return passphrase
