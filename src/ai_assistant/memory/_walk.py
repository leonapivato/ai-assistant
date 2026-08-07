"""The walk surface's argument checks and its opaque position token (ADR-0114).

Shared by this package's two stores, which differ in *where* the order key comes
from — a ``rowid`` in the persistent store, an issued counter in the in-memory
one — and agree about everything else. ``ai_assistant.testing``'s canonical fake
carries its own copy rather than importing this, for the reason
``_check_page_bounds`` is already triplicated: golden rule 1 forbids
``ai_assistant.testing`` importing a subsystem.

**Why a token rather than the bare order key.** ADR-0114 §2 binds a position to
the walk it was issued for, so the cursor advance can refuse one presented to a
different walk. With a bare key as the token, a caller holding walk ``A``'s
legitimate position for record 50 can hand it to walk ``B``'s advance, and a
conforming store records ``B`` at 50 and never processes records 1-50 — every one
of them skipped, ``B`` reporting healthy progress, and nothing distinguishing the
call from a correct one. Making the walk recoverable from the token turns that
obligation into a check, which is the right instrument wherever a check is
available. It buys nothing against a *forged* token and does not try to: ADR-0114
§2 declines authentication outright, and a caller that synthesises a position has
broken the contract in a way no implementation is obliged to notice.
"""

from __future__ import annotations

import json
from typing import Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import NonBlankEncodableText, WalkPosition

#: One past the largest ``limit`` :meth:`MemoryStore.walk_records` accepts — the
#: signed 64-bit ceiling a SQLite bind parameter tops out at, matching
#: ``scheduler_chunk_size``'s own bound so a configured chunk size is always an
#: admissible limit and the two figures cannot disagree (ADR-0114 §6).
_LIMIT_BOUND: Final = 2**63

#: The validator :data:`NonBlankEncodableText` applies, run explicitly on entry.
#: These aliases are pydantic ``Annotated`` validators and Python runs nothing for
#: an ordinary method call, so the annotation states the intent and this check is
#: what enforces it (ADR-0114 §5) — the shape ``wire/codec.py`` and
#: ``orchestration/grants.py`` already use at this kind of seam.
_WALK_NAME: Final = TypeAdapter[str](NonBlankEncodableText)


def check_walk_name(walk: str) -> str:
    r"""Refuse a walk name that is empty, whitespace-only or unencodable.

    Checked **before** the name reaches a query, a key or any stored state, so an
    inadmissible name is refused identically on every backend. Without it the
    backends disagree about what a ``str`` is: ``walk_records("\ud800", …)`` is an
    ordinary Python call, and SQLite cannot UTF-8 encode a lone surrogate when
    binding it while an in-memory store accepts it happily.

    Returns:
        The name, unchanged. Never normalised: two names differing only in case
        or spacing are two walks, because a store that quietly merged them would
        merge two jobs' positions and skip records for one of them (ADR-0114 §5).

    Raises:
        ValueError: If ``walk`` is not
            :data:`~ai_assistant.core.types.NonBlankEncodableText`.
    """
    try:
        return _WALK_NAME.validate_python(walk)
    except ValidationError as exc:
        msg = f"walk name must be non-blank encodable text, got {walk!r}"
        raise ValueError(msg) from exc


def check_walk_limit(limit: int) -> int:
    """Refuse a chunk limit that is not exactly an ``int`` in ``[1, 2**63)``.

    "Exactly an ``int``" excludes ``bool``, which is the case that matters most:
    it is an ``int`` subclass, so ``True`` satisfies every range comparison and
    would quietly become a one-record chunk — the reason ``core/config.py``'s
    integer settings are ``_IntegerSetting`` rather than bare ``int``. Zero is
    refused with the rest rather than answering with an empty page as
    ``list_beliefs`` does: a chunk that examines nothing carries no position, and
    an absent position *means the walk is exhausted*, so a job configured to a
    zero chunk would report a completed walk having read nothing (ADR-0114 §6).

    Raises:
        ValueError: If ``limit`` is not exactly an ``int``, or is outside
            ``[1, 2**63)``. Raised rather than clamped, because both ends are
            places two backends silently disagree.
    """
    if type(limit) is not int:
        msg = f"limit must be exactly an int, got {type(limit).__name__}: {limit!r}"
        raise ValueError(msg)
    if not 1 <= limit < _LIMIT_BOUND:
        msg = f"limit must be in [1, 2**63), got {limit}"
        raise ValueError(msg)
    return limit


def resume_key(recorded: str | None, *, issued_through: int) -> int:
    """Read a recorded position back, restarting the walk on anything unusable.

    A position that is absent, unreadable, malformed, written in a form this
    build does not understand, or not supported by the store's contents is
    **discarded and the walk restarts from the first record** — the store does not
    raise, does not refuse to open, and does not report a state fault (ADR-0114
    §4, ADR-0111 §7). A cursor holds no evidence and answers no query, so
    discarding one returns nothing wrong to any client and costs only the repeated
    walk ADR-0111 §3 already accepted; refusing over one would take a resident
    process down over scaffolding.

    **A well-formed number can be unsupported too, and that case is the dangerous
    one.** A position above every key the store has ever issued names a range no
    record can ever occupy: §1's guarantee is that each new key exceeds every key
    already issued, so a cursor beyond the high-water mark sits above all of them
    for good. The walk then answers "nothing left to examine" on every run while
    the store fills up behind it — ADR-0111 §7's "Nothing may resume from a
    position the store's contents do not support", and the silent skip the whole
    contract exists to prevent, arriving through the cursor itself.

    **The ceiling is the high-water mark and deliberately not ``max`` of the keys
    present.** Walking to the end and then deleting the top records leaves a
    position above everything the store now holds, and that position is perfectly
    good: §2 makes a position a bound rather than a reference, and §1's
    never-reissued key is what makes the next record land above it. Ceiling on
    what is *present* would rewind that walk and re-read every surviving record.

    Args:
        recorded: The stored position, or ``None`` where the walk has none.
        issued_through: The largest key this store has ever issued — SQLite's
            ``sqlite_sequence`` high-water mark, an in-memory store's own counter.
            ``0`` where it has issued none.

    Returns:
        The recorded key, or ``0`` — the position before the first record, which
        is what "no recorded position" means. Never a sentinel: there is no
        integer below the order's floor to use as one, and the obvious choice
        silently skips every record at or below it (ADR-0104 §2).
    """
    if recorded is None:
        return 0
    try:
        key = int(recorded)
    except TypeError, ValueError:
        return 0
    if not 0 <= key <= issued_through:
        return 0
    return key


def mint_position(walk: str, key: int) -> WalkPosition:
    """Encode ``key`` as a position bound to ``walk``.

    JSON rather than a delimiter join, so a walk name containing the delimiter
    cannot make one position parse as another's. The result is non-blank and
    encodable whenever ``walk`` is, which :func:`check_walk_name` has established
    by the time any caller here reaches this.
    """
    return WalkPosition(token=json.dumps({"w": walk, "k": key}, ensure_ascii=False))


def read_position(walk: str, position: object) -> int:
    """Decode ``position``'s order key, refusing anything not this walk's.

    Validates the argument itself before reading any field, because a frozen
    model is not a validated one at the call site:
    ``WalkPosition.model_construct(token=…)`` builds an instance without running
    its validator — that is what ``model_construct`` is for — so a malformed
    token, or none at all, reaches the store with the declared type satisfied.
    Reading ``position.token`` first would reach ``AttributeError`` instead, which
    ADR-0114 §6a makes a breach rather than a variant.

    The rule is **general over malformation and stops exactly there**: what a
    store can decide from the argument is refused, and a well-formed token naming
    the right walk that no chunk read ever issued is left undetected by design
    (ADR-0114 §2).

    Raises:
        ValueError: If ``position`` is not a
            :class:`~ai_assistant.core.types.WalkPosition`, carries no usable
            token, or is bound to a different walk.
    """
    if not isinstance(position, WalkPosition):
        msg = f"position must be a WalkPosition, got {type(position).__name__}"
        raise ValueError(msg)
    token = getattr(position, "token", None)
    if not isinstance(token, str):
        msg = "position carries no token"
        raise ValueError(msg)
    try:
        # `json.JSONDecodeError` is itself a `ValueError`, but it is re-raised as
        # this module's own so the message names the argument rather than a column
        # offset in an encoding the caller is forbidden to know about.
        decoded = json.loads(token)
    except ValueError as exc:
        msg = f"position token is malformed: {token!r}"
        raise ValueError(msg) from exc
    if not isinstance(decoded, dict) or type(decoded.get("k")) is not int:
        msg = f"position token is malformed: {token!r}"
        raise ValueError(msg)
    issued_for = decoded.get("w")
    if issued_for != walk:
        msg = f"position was issued for walk {issued_for!r}, not {walk!r}"
        raise ValueError(msg)
    return int(decoded["k"])
