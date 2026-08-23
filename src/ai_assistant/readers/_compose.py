"""The one shape rule both readers apply to the text they compose (#1449).

**The rule.** A reader's composed ``content`` is **one line**. Every character the
source supplies that would end a line is removed; **every other byte is preserved
verbatim**, the quotation mark included. Nothing is substituted, nothing is
escaped, and nothing is collapsed — a removal is the whole of it.

**Why the reader's own rendering shape is the reader's.** ADR-0183 §8's first
clause is that a reader's rendering of a proposal's content is a *composition* —
the reader's sentence, with the source's spans inside it. The reader's own
vocabulary contains no line break, so a break in the output is a line structure
the **source** chose for a string the **reader** authored. ADR-0183 §3 denies a
source's bytes any standing they try to buy from inside the source; the shape of
the reader's own composition is not the one place they get it. That is the ground,
and it is the only one claimed.

**What this is emphatically not, stated here because ADR-0183 §8 says the
alternative is the worse error.** This is not an escaping, not a sanitisation, and
not a defence. Every clause of §8 binds unchanged over what comes out of here:

* the composition **confers no structure a consumer may rely on** and is not a
  trust boundary;
* the external span inside it is **not separately addressable**, and no consumer
  may locate it by the quotation marks or by any other artefact of the phrasing;
* the whole string is external content under ADR-0098 §1, and each consumer's
  conformance with ADR-0098 §2 or §7 is that consumer's own, established there and
  **not here**.

**The quotation mark is deliberately untouched, and so is every other control
character.** ADR-0183 §8 names delimiting untrusted text with a delimiter untrusted
text may contain as not a defence, and its alternatives-considered refuses a
sanitisation step at this seam on the ground that "a sanitised span *looks* safe,
which is how a consumer stops doing its own escaping". Stripping the quotation
mark, ``NUL``, ``U+007F`` or the rest of the C0 set would be that error wearing a
tidier face — a partial filter that reads as a control-character defence while
being none. So they are preserved, and the property this module does guarantee is
narrow enough to state honestly: one line, and nothing else.

**Why it is here rather than twice.** #1449's divergence was that
``EmailReader._unfolded`` removed CR and LF from a header value and the calendar
path removed nothing equivalent, with nothing in the corpus saying which was
right. Converging them buys no consumer anything — neither output is safer than
the other — and that is not the reason. The reason is that two readers rendering
equivalent source shapes differently leaves a third reader nothing to copy, and
ADR-0183's consequences put "what it renders" among the four questions a new
reader must answer in its own text. One function is one answer.

**Email's behaviour is unchanged by construction.** RFC 5322 unfolding *is* this
rule for a header value — delete the break, keep the whitespace — which is why a
folded ``Subject`` still arrives as ``"…runs on  and is folded…"`` with both
spaces. Substituting a space for the break, rather than removing it, would have
changed that and would have put a character in the span that the source did not
write.
"""

from __future__ import annotations

from typing import Final

#: Every character :meth:`str.splitlines` treats as ending a line, which is the
#: set this module removes and the definition it is testable against. Taking
#: Python's own boundary set rather than an enumeration of our own means the
#: property — ``len(one_line(text).splitlines()) <= 1`` — is decided by the same
#: table that decides the assertion, so the two cannot drift apart.
#:
#: The C1 and Unicode members are the ones a hand-written ``\r``/``\n`` pair
#: misses: ``U+0085`` NEL, and ``U+2028``/``U+2029``, which a renderer and a
#: ``splitlines`` alike count as breaks even though a naive strip leaves them.
_LINE_BOUNDARIES: Final = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")

#: The removal, precomputed once. ``str.translate`` over a mapping to ``None`` is
#: one pass and allocates one string, which matters at a seam that runs it per
#: field per occurrence, under the product of ``calendar_max_entries`` and
#: ``calendar_max_expansion``.
_REMOVALS: Final = {ord(character): None for character in _LINE_BOUNDARIES}


def one_line(text: str) -> str:
    """``text`` with every line boundary removed and everything else preserved.

    Idempotent, and total over every ``str``: it removes characters and adds
    none, so it can neither create a boundary nor make an encodable string
    unencodable (a lone surrogate stays exactly as unencodable as it arrived —
    ``EncodableText`` is the type's own guard and this is not a second one).

    Args:
        text: One source-derived span, as the reader's parser returned it.

    Returns:
        The same text with the characters in :data:`_LINE_BOUNDARIES` deleted.
        Every other character survives, including the quotation mark, ``NUL``
        and ``U+007F`` — see this module's docstring for why that is the point
        rather than an omission.
    """
    return text.translate(_REMOVALS)
