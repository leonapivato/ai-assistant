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
#: The longest passphrase this tool will use, from **any** source.
#:
#: It exists because a passphrase file with no line break at all would otherwise
#: be read whole into memory — but it is applied to the prompt as well, and that
#: is the part that matters. A bound on one source alone breaks §5's recovery
#: path: a passphrase long enough to be typed at the backup and *not* long enough
#: to be read back from a file is a passphrase that keys an artifact nothing can
#: open. What can write has to be able to read.
_MAX_PASSPHRASE_BYTES: Final = 4096

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
        passphrase = _generated()
    elif source is not None:
        passphrase = _from_file(source)
    else:
        passphrase = _prompted(confirm=confirm)
    _refuse_oversized(passphrase)
    return passphrase


def _refuse_oversized(passphrase: str) -> None:
    """Hold every source to one length, so what wrote an artifact can open it.

    Checked on the passphrase rather than on the bytes a particular source read,
    because a terminator is not part of it: a maximum-length passphrase saved as
    a file's first line is one byte longer *as a line*, and refusing that is
    refusing to open an artifact the same passphrase wrote.

    Args:
        passphrase: The passphrase this run obtained.

    Raises:
        RefusalError: If it is longer than :data:`_MAX_PASSPHRASE_BYTES` encoded,
            or is not encodable at all.
    """
    try:
        encoded = len(passphrase.encode("utf-8"))
    except UnicodeEncodeError as exc:
        # A terminal can hand back bytes that do not decode, and Python carries
        # them as lone surrogates in an otherwise ordinary `str`. Encoding one is
        # a `UnicodeEncodeError`, which is a `ValueError` and so is caught by
        # neither entry point — a traceback where an operator needs a sentence.
        # The passphrase itself is never echoed: it is the thing being protected.
        msg = (
            "the passphrase contains characters that are not valid text, so it cannot be "
            "used as a key; retype it, or supply it with --passphrase-file"
        )
        raise RefusalError(msg) from exc
    if encoded > _MAX_PASSPHRASE_BYTES:
        msg = (
            f"the passphrase is {encoded} bytes, past the {_MAX_PASSPHRASE_BYTES} this tool "
            f"uses from any source; a longer one could key an artifact it could not then "
            f"read back from a file"
        )
        raise RefusalError(msg)


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
        with source.open("rb") as handle:
            # The *first line*, read as bytes and decoded on its own. Decoding the
            # whole file first makes anything after that line able to refuse the
            # backup — a stray byte past the passphrase is not a reason a recovery
            # cannot happen, and this is a file an operator may well have appended
            # a note to.
            # One past the bound *and* its terminator, so a maximum-length
            # passphrase written as a line is read whole and only something
            # genuinely longer is cut short — `resolve` is what judges the length,
            # on the passphrase rather than on the line.
            line = handle.readline(_MAX_PASSPHRASE_BYTES + 2)
    except OSError as exc:
        msg = f"the passphrase file {source} could not be read: {exc}"
        raise RefusalError(msg) from exc
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = f"the passphrase file {source} does not begin with UTF-8 text: {exc}"
        raise RefusalError(msg) from exc
    passphrase = text.removesuffix("\n").removesuffix("\r")
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
    except (EOFError, OSError, UnicodeDecodeError) as exc:
        msg = (
            "no passphrase could be read from the terminal; pass --passphrase-file to run "
            "this unattended, or --generate-passphrase to have one minted and shown"
        )
        raise RefusalError(msg) from exc
    if not passphrase:
        msg = "an empty passphrase is not a key; nothing was written"
        raise RefusalError(msg)
    return passphrase
