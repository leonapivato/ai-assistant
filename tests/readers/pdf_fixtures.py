"""Minimal, hand-built PDFs, so a fetch test's input is bytes it can reason about.

ADR-0230 §6 puts PDF on the first rung and §14 items 1 and 8 ask for tests over a
document whose text carries a distinctive word and over one whose *rendering* sits
exactly on a bound. Both need a PDF whose extracted text is known **exactly**, which
rules out a checked-in binary — a fixture nobody can read is a fixture nobody can
adjust, and a byte of it moving would move the extracted text with no diff worth
reading.

So the documents are built here, in the smallest form ``pypdf`` will read: a
catalogue, a page tree of one, one page with one Type 1 font, and a content stream of
``Tj`` operators. Nothing here is a general PDF writer and nothing should grow into
one; what it is for is producing a document whose text a test already knows.
"""

from __future__ import annotations

from typing import Final

#: The page box every document here uses. Arbitrary and irrelevant to extraction —
#: `pypdf` reads the content stream's operators, not the geometry — and stated once
#: so no reader wonders whether a number is load-bearing.
_MEDIA_BOX: Final = b"[0 0 612 792]"


def minimal_pdf(lines: list[str]) -> bytes:
    """One page whose extracted text is ``lines`` joined by newlines.

    ``pypdf`` renders each ``Tj`` on its own line and appends a trailing newline to
    the page, so a caller wanting to know the extracted text exactly should use
    :func:`extracted_text_of` rather than reconstructing the join by hand.

    Args:
        lines: The lines to show, each **ASCII** — a PDF string literal's encoding is
            its font's, and this fixture declares a standard Type 1 font whose
            encoding is Latin-1. A test needing an astral code point puts it in a
            ``.txt`` document instead, where the encoding is UTF-8 by decision
            (ADR-0230 §6).

    Returns:
        A complete PDF document, cross-reference table and all.
    """
    body = (
        b"BT /F1 24 Tf 72 700 Td "
        + b" ".join(b"(" + _escaped(line) + b") Tj 0 -30 Td" for line in lines)
        + b" ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox "
        + _MEDIA_BOX
        + b" /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream",
    ]
    return _assembled(objects)


def extracted_text_of(lines: list[str]) -> str:
    """What :func:`minimal_pdf` of ``lines`` extracts to, exactly.

    Stated as a function rather than left to each caller because the trailing newline
    is `pypdf`'s and not this fixture's: a test asserting on an exact length — §14
    item 8's at-the-limit arm — has to count it, and a test that reconstructed the
    join by hand would be asserting against its own guess at the library's behaviour.
    """
    return "".join(f"{line}\n" for line in lines)


def _escaped(line: str) -> bytes:
    """One line as a PDF string literal's contents.

    Three characters are special inside ``(…)`` and each is escaped with a backslash.
    Nothing else is: the fixture's inputs are ASCII by contract above.
    """
    encoded = line.encode("ascii")
    for special in (b"\\", b"(", b")"):
        encoded = encoded.replace(special, b"\\" + special)
    return encoded


def _assembled(objects: list[bytes]) -> bytes:
    """Wrap numbered objects in a header, a cross-reference table and a trailer."""
    document = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(document))
        document += str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    table = len(document)
    size = len(objects) + 1
    document += b"xref\n0 " + str(size).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        document += f"{offset:010d} 00000 n \n".encode()
    document += (
        b"trailer\n<< /Size "
        + str(size).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(table).encode()
        + b"\n%%EOF\n"
    )
    return bytes(document)


def amplified_page_tree_pdf(*, fan: int = 20, levels: int = 6) -> bytes:
    """A tiny document declaring an enormous page tree, for the traversal bound.

    ADR-0230 §6 states that ``fetch_max_file_bytes`` "bounds the read **and the
    extraction's cost**", which holds for text and Markdown because the work is
    proportional to the bytes. A PDF's page tree breaks that proportionality: each node
    here names the next ``fan`` times, so ``fan ** levels`` leaves are reachable from a
    document of about 1.4 KB, and ``/Count`` claims exactly that.

    It is a **fixture and not a fault injector**: what the test built around it asserts
    is that the adopted library refuses such a document, so a future version dropping
    one of its own traversal guards fails a test rather than shipping an amplification.
    """
    claimed = fan**levels
    objects: dict[int, bytes] = {1: b"<< /Type /Catalog /Pages 2 0 R >>"}
    for level in range(levels):
        number = 2 + level
        kid = f"{number + 1} 0 R".encode()
        objects[number] = (
            b"<< /Type /Pages /Count "
            + str(claimed).encode()
            + b" /Kids ["
            + b" ".join([kid] * fan)
            + b"] >>"
        )
    objects[2 + levels] = b"<< /Type /Page /Parent 2 0 R /MediaBox " + _MEDIA_BOX + b" >>"
    return _assembled([objects[number] for number in sorted(objects)])
