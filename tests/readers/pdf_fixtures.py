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

import zlib
from dataclasses import dataclass
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


def _assembled(objects: list[bytes], *, root: int = 1) -> bytes:
    """Wrap numbered objects in a header, a cross-reference table and a trailer.

    ``root`` is the catalogue's object number, and it is a parameter rather than the
    constant 1 because :class:`_Objects` lets a builder claim numbers for the objects a
    page refers to *before* the page tree exists. A trailer naming the wrong object is
    not a broken fixture — ``pypdf`` recovers by scanning for a ``/Catalog`` — which is
    exactly why it has to be right: a document that reaches the extractor through the
    library's **repair** path is not the document the test means to be asserting about.
    """
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
        + b" /Root "
        + reference(root)
        + b" >>\nstartxref\n"
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


# --- ADR-0232's documents: what an extraction *parses*, and what it does not ---
#
# Everything below builds a document whose **decoded, parsed** byte count is known
# from its inputs, so an arm can state the charge it expects rather than discover it.
# The two halves ADR-0232 §3 counts are built separately and composed: content-stream
# instructions (a page's own, and every Form XObject reached from it once per `Do`),
# and the embedded font program of a `/Type1` font with a `/FontFile` and no
# `/ToUnicode`, which the extraction re-parses on every page.
#
# **They are the measured documents at test scale.** The ADR's figures — 313 s for
# 16 MB of operators, 33.9 s for a form-carried 4 MB, 126.6 s for one 100 KB form
# invoked five hundred times, 257.1 s for 2,000 pages sharing a 40 MB program — are
# the *shape* of the finding rather than numbers a suite can assert, and §8 says so in
# terms: every refusal arm observes that the parse was not entered, never a duration.
# So each builder takes its amplification as an argument, and an arm picks the
# smallest figure that makes its own property decidable.


class _Objects:
    """A numbered PDF object table, so a fixture can name a reference before it exists.

    ``_assembled`` numbers objects by their position, and object 1 must be the
    catalogue because the trailer names it. A builder that hand-counted object numbers
    would be one insertion away from a document whose references point at the wrong
    thing and whose test then asserts about a document nobody meant.
    """

    def __init__(self) -> None:
        self._bodies: list[bytes | None] = []

    def reserve(self) -> int:
        """Claim the next object number without saying what it holds yet."""
        self._bodies.append(None)
        return len(self._bodies)

    def put(self, number: int, body: bytes) -> bytes:
        """Fill a reserved number, and answer the reference to it."""
        self._bodies[number - 1] = body
        return reference(number)

    def add(self, body: bytes) -> bytes:
        """Append an object, and answer the reference to it."""
        return self.put(self.reserve(), body)

    def build(self, *, root: int) -> bytes:
        """The assembled document, whose trailer names ``root`` as the catalogue."""
        assert all(body is not None for body in self._bodies), "a reserved object is unfilled"
        return _assembled([body for body in self._bodies if body is not None], root=root)


def reference(number: int) -> bytes:
    """``N 0 R``, spelled once."""
    return f"{number} 0 R".encode()


def stream_object(body: bytes, *, entries: bytes = b"", compress: bool = True) -> bytes:
    """A stream object carrying ``body``, Flate compressed unless told otherwise.

    Compression is the default because it is what makes these documents *amplified*:
    the file bound is satisfied by the compressed bytes while the extraction parses the
    decoded ones, which is the whole of #2022.
    """
    data = zlib.compress(body, 9) if compress else body
    filter_entry = b" /Filter /FlateDecode" if compress else b""
    return (
        b"<< /Length "
        + str(len(data)).encode()
        + filter_entry
        + entries
        + b" >>\nstream\n"
        + data
        + b"\nendstream"
    )


def operators(decoded_bytes: int) -> bytes:
    """A content stream of about ``decoded_bytes`` of nothing but repeated ``Tj``.

    The adversarial density: a run of one repeated operator compresses about 340:1, so
    the document carrying this is roughly ``decoded_bytes / 340`` on disk. Its exact
    length is what a caller asserts against, so it is returned rather than described.
    """
    unit = b" (AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA) Tj 0 -1 Td"
    return b"BT /F1 24 Tf 72 700 Td" + unit * (decoded_bytes // len(unit)) + b" ET"


def drawing(decoded_bytes: int) -> bytes:
    """A content stream of about ``decoded_bytes`` of operators that **show no text**.

    :func:`operators`'s sibling, for the arms whose subject is the *charge* rather than
    the text: a stream of ``Tj`` yields text in proportion to its length, so an arm
    using one has to raise ``fetch_max_content_bytes`` out of the way, and one carrying
    hundreds of thousands of bytes would materialise hundreds of thousands of
    characters to prove something about a byte count.
    """
    unit = b"0 0 m 1 1 l S\n"
    return unit * (decoded_bytes // len(unit))


#: A Type 1 font the extraction decodes **no** program for: no ``/FontDescriptor``,
#: so ``_type1_alternative`` returns before it reads anything.
PLAIN_FONT: Final = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"


def type1_program(size: int) -> bytes:
    """An embedded Type 1 font program of exactly ``size`` decoded bytes.

    ``_type1_alternative`` splits the program on ``eexec\\n``, takes the clear part,
    splits *that* on ``/Encoding`` and scans the remainder line by line. The shape here
    is a real one — a clear part with an ``/Encoding`` array and one ``dup`` — padded to
    length with a comment line, so the extraction reads it exactly as it would read a
    dvips-era font and the decoded length is a number the test chose.
    """
    head = b"%!PS-AdobeFont-1.0\n/Encoding 256 array\ndup 65 /A put\nreadonly def\n"
    tail = b"\neexec\n" + b"\x00" * 16
    padding = size - len(head) - len(tail)
    assert padding >= 1, "the program is smaller than its own shape"
    return head + b"%" + b"P" * (padding - 1) + tail


@dataclass(frozen=True)
class Page:
    """One page of a built document, stated as what the extraction will find on it.

    Attributes:
        contents: The decoded content-stream bodies, in order. More than one makes the
            page's ``/Contents`` an **array**, which is the shape ADR-0232 §8 arm 6 is
            about; ``None`` gives the page no ``/Contents`` key at all, which is a
            legal empty page and the shape a font-only charge needs.
        fonts: Font resource bodies by name, already assembled.
        forms: Form XObject references by name, as the page's ``/XObject``.
        resources: Overrides the whole resource dictionary. ``None`` builds one from
            ``fonts`` and ``forms``; ``OMITTED`` gives the page no ``/Resources`` key,
            which is what makes its extraction return before it touches the stream.
    """

    contents: list[bytes] | None = None
    fonts: dict[str, bytes] | None = None
    forms: dict[str, bytes] | None = None
    resources: bytes | None = None


#: A resource dictionary a page deliberately does **not** carry. Distinct from
#: ``None``, which means "build one from the fonts and forms" — and from
#: :data:`EMPTY_RESOURCES`, which carries one that answers "nothing".
OMITTED: Final = b"<<OMITTED>>"

#: What :func:`dictionary_of` answers for nothing at all. A page whose fonts and forms
#: are both empty gets **no** ``/Resources`` key rather than an empty one, so a fixture
#: has to ask for the empty case by name.
_EMPTY_DICTIONARY: Final = b"<< >>"

#: A resource context that is present and answers "nothing". ADR-0232 §3 puts this on
#: the *fetch* side of its line: the walk asked, no parse follows, and the extraction
#: skips exactly there.
EMPTY_RESOURCES: Final = _EMPTY_DICTIONARY


def document(
    pages: list[Page],
    *,
    objects: _Objects | None = None,
    tree_resources: bytes | None = None,
) -> bytes:
    """A document of ``pages``, with a page tree of one level.

    Args:
        pages: What each page carries. Every font body and form reference in them has
            already been added to ``objects``.
        objects: The table those bodies were added to, so a caller that needed to name
            an object before the page existed can hand it back. A fresh one otherwise.
        tree_resources: A ``/Resources`` dictionary on the ``/Pages`` node, which every
            page **inherits** where it carries none of its own. That is the arm ADR-0232
            §8 item 4 asks for: a walk resolving an operand anywhere other than where
            ``get_inherited`` resolves it fails on this and on nothing else.

    Returns:
        The assembled document.
    """
    table = objects if objects is not None else _Objects()
    catalogue = table.reserve()
    tree = table.reserve()
    numbers = [table.reserve() for _ in pages]
    for number, page in zip(numbers, pages, strict=True):
        table.put(number, _page_body(page, tree=tree, objects=table))
    table.put(catalogue, b"<< /Type /Catalog /Pages " + reference(tree) + b" >>")
    table.put(
        tree,
        b"<< /Type /Pages /Kids ["
        + b" ".join(reference(number) for number in numbers)
        + b"] /Count "
        + str(len(numbers)).encode()
        + (b" /Resources " + tree_resources if tree_resources is not None else b"")
        + b" >>",
    )
    return table.build(root=catalogue)


def _page_body(page: Page, *, tree: int, objects: _Objects) -> bytes:
    """One ``/Page`` dictionary, with its content streams added to the table."""
    body = b"<< /Type /Page /Parent " + reference(tree) + b" /MediaBox " + _MEDIA_BOX
    resources = page.resources if page.resources is not None else resource_dictionary(page)
    if resources not in (OMITTED, _EMPTY_DICTIONARY):
        body += b" /Resources " + resources
    if page.contents is not None:
        streams = [objects.add(stream_object(part)) for part in page.contents]
        body += b" /Contents " + (
            streams[0] if len(streams) == 1 else b"[" + b" ".join(streams) + b"]"
        )
    return body + b" >>"


def resource_dictionary(page: Page) -> bytes:
    """A ``/Resources`` dictionary from a page's fonts and forms."""
    return dictionary_of({"/Font": page.fonts, "/XObject": page.forms})


def dictionary_of(entries: dict[str, dict[str, bytes] | None]) -> bytes:
    """A PDF dictionary of the named sub-dictionaries that have anything in them."""
    body = b"<<"
    for key, members in entries.items():
        if members:
            body += (
                b" "
                + key.encode()
                + b" <<"
                + b"".join(b" " + name.encode() + b" " + value for name, value in members.items())
                + b" >>"
            )
    return body + b" >>"


def form_object(body: bytes, *, resources: bytes) -> bytes:
    """A Form XObject stream carrying ``body`` and resolving names against its own."""
    return stream_object(
        body,
        entries=b" /Type /XObject /Subtype /Form /Resources " + resources,
    )


def amplified_content_stream_pdf(*, decoded_bytes: int = 16_000_000) -> bytes:
    """One page whose Flate-compressed content stream decodes to ``decoded_bytes``.

    The compression bomb the *page-tree* fixture above is not. That one hides a huge
    page count in a small file; this one hides a huge **content stream** in one, and
    neither of ADR-0230 §6's two figures sees it on its own: the file bound is
    satisfied by the compressed bytes, and the content bound is counted on extracted
    text, which exists only after the whole stream has been parsed into operators.

    At the default this is #2022's own document — about 47 KB on disk against a 16 MB
    stream that took 313 s and 737 MB of resident memory to parse before ADR-0232's
    bound existed.
    """
    objects = _Objects()
    font = objects.add(PLAIN_FONT)
    return document(
        [Page(contents=[operators(decoded_bytes)], fonts={"/F1": font})],
        objects=objects,
    )


def form_carried_amplification_pdf(*, decoded_bytes: int = 4_000_000) -> bytes:
    """A page whose ``/Contents`` is a handful of bytes and whose form is megabytes.

    ``PageObject._extract_text__xform`` follows each ``Do`` into the named form and
    parses it as a content stream of its own, so a count over ``/Contents`` alone sees
    a handful of bytes here and admits the whole parse. ADR-0232's Context measured the
    shape at 33.9 s unbounded from a 12,453 B file.
    """
    objects = _Objects()
    font = objects.add(PLAIN_FONT)
    form = objects.add(
        form_object(operators(decoded_bytes), resources=dictionary_of({"/Font": {"/F1": font}}))
    )
    return document(
        [Page(contents=[b"/X1 Do\n"], fonts={"/F1": font}, forms={"/X1": form})],
        objects=objects,
    )


def repeated_form_pdf(*, form_bytes: int = 100_000, invocations: int = 500) -> bytes:
    """A page invoking **one** form many times, so its *distinct* bytes stay small.

    The adopted version's cycle guard refuses only a *re-entrant* form, so N sequential
    ``Do``s of one form are N parses of it. At the defaults this is the 1,173 B document
    of ADR-0232's Context: 105 KB of distinct decoded bytes, 50 MB parsed, 126.6 s
    unbounded — and the document any implementation counting distinct streams once
    admits whole.
    """
    objects = _Objects()
    font = objects.add(PLAIN_FONT)
    form = objects.add(
        form_object(operators(form_bytes), resources=dictionary_of({"/Font": {"/F1": font}}))
    )
    return document(
        [
            Page(
                contents=[b"/X1 Do\n" * invocations],
                fonts={"/F1": font},
                forms={"/X1": form},
            )
        ],
        objects=objects,
    )


def type1_font_pages_pdf(*, pages: int, fonts: int, program_bytes: int) -> bytes:
    """``pages`` content-free pages sharing ``fonts`` charged ``/Type1`` programs.

    Each font carries a ``/FontFile`` and **no** ``/ToUnicode`` and has ``/Subtype``
    ``/Type1``, which is ``pypdf._cmap._parse_to_unicode``'s exact condition for
    entering ``_type1_alternative`` and reading the program. The extraction rebuilds a
    stream's fonts on every ``_extract_text`` call, so the program is re-scanned once
    per page and the charge is ``pages * fonts * program_bytes``.

    Two classes are built from this one shape and ADR-0232 §2 keeps them apart
    deliberately: the amplified one — thousands of pages sharing a huge program, the
    0.217 MiB document that *fetched* after 257.1 s — and the **ordinary** one, a
    thirty-page paper with a roman, an italic and a maths font, which §2's table
    records as refused at 3.00 MiB while costing 37 ms.
    """
    objects = _Objects()
    program = objects.add(stream_object(type1_program(program_bytes)))
    descriptor = objects.add(
        b"<< /Type /FontDescriptor /FontName /Charged /Flags 4 /FontFile " + program + b" >>"
    )
    resources = {
        f"/F{index}": objects.add(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Charged /FontDescriptor "
            + descriptor
            + b" >>"
        )
        for index in range(1, fonts + 1)
    }
    return document([Page(fonts=resources) for _ in range(pages)], objects=objects)


def tounicode_font_pdf(*, program_bytes: int) -> bytes:
    """A page whose large ``/FontFile2`` belongs to a font carrying a ``/ToUnicode``.

    ``Font.from_font_resource`` resolves a ``/FontFile*`` with ``get_object()``, which
    does **not** decode, and the one conditional decode in ``pypdf._font.py`` sits
    behind ``HAS_FONTTOOLS``, which is ``False`` here. So this program is never read,
    and an implementation charging ``/FontFile*`` unconditionally would refuse on bytes
    the extraction never decodes (ADR-0232 §8 arm 11).
    """
    objects = _Objects()
    program = objects.add(stream_object(b"\x00" * program_bytes))
    descriptor = objects.add(
        b"<< /Type /FontDescriptor /FontName /Uncharged /Flags 4 /FontFile2 " + program + b" >>"
    )
    cmap = objects.add(stream_object(_TO_UNICODE))
    font = objects.add(
        b"<< /Type /Font /Subtype /TrueType /BaseFont /Uncharged /FontDescriptor "
        + descriptor
        + b" /ToUnicode "
        + cmap
        + b" >>"
    )
    return document(
        [Page(contents=[b"BT /F1 24 Tf (A) Tj ET"], fonts={"/F1": font})], objects=objects
    )


#: The smallest ``/ToUnicode`` CMap ``pypdf`` will read as one.
_TO_UNICODE: Final = (
    b"/CIDInit /ProcSet findresource begin\n"
    b"12 dict begin begincmap\n"
    b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
    b"1 beginbfrange\n<41> <41> <0041>\nendbfrange\n"
    b"endcmap end end\n"
)


def pages_sharing_a_font(bodies: list[bytes]) -> bytes:
    """One page per body, each carrying that body's stream and one uncharged font.

    The plainest shape a charge arm can be built on: the counted quantity is exactly the
    sum of the bodies' lengths, because the font meets none of ADR-0232 §3's three keys
    and nothing else on the page decodes. A page needs *some* non-empty resource
    context or its extraction returns before it touches the stream, which is why the
    font is here at all.
    """
    objects = _Objects()
    font = objects.add(PLAIN_FONT)
    return document(
        [Page(contents=[body], fonts={"/F1": font}) for body in bodies], objects=objects
    )


def literal_do_pdf() -> bytes:
    """A page whose content stream carries the literal text ``(Do)`` and no form.

    The two bytes ``Do`` inside a string literal are not an invocation, and the page
    names no ``/XObject`` at all. A walk scanning bytes for ``Do`` charges a descent
    that never happens and refuses a document ADR-0232 §2 requires this seam to fetch;
    a walk deciding by the extraction's own grammar charges the page's stream and
    nothing else (§8 arm 4).
    """
    objects = _Objects()
    font = objects.add(PLAIN_FONT)
    body = b"BT /F1 24 Tf 72 700 Td (Do) Tj (Do Do Do) Tj ET"
    return document([Page(contents=[body], fonts={"/F1": font})], objects=objects)


def inherited_form_pdf(*, form_text: str) -> bytes:
    """A page invoking a form named in resources it **inherits** through the page tree.

    ``PageObject._extract_text`` resolves ``get_inherited(/Resources)``, so a page
    carrying no resource dictionary of its own resolves ``/X1`` against its parent's.
    A walk looking only at the page's own dictionary finds no form, charges nothing,
    and admits the parse — which is the wrong answer in the unsound direction.
    """
    objects = _Objects()
    font = objects.add(PLAIN_FONT)
    form = objects.add(
        form_object(
            b"BT /F1 24 Tf 72 700 Td (" + form_text.encode("ascii") + b") Tj ET",
            resources=dictionary_of({"/Font": {"/F1": font}}),
        )
    )
    return document(
        [Page(contents=[b"/X1 Do\n"], resources=OMITTED)],
        objects=objects,
        tree_resources=dictionary_of({"/Font": {"/F1": font}, "/XObject": {"/X1": form}}),
    )


def content_array_pdf(*, part_bytes: int, undecodable_bytes: int) -> bytes:
    """One page whose ``/Contents`` is an array whose **last** member cannot decode.

    Two ordinary streams of ``part_bytes`` each, then one declaring more decoded bytes
    than ``pypdf``'s own per-stream ceiling admits, so decoding it raises
    ``LimitReachedError`` and the fetch would be ``EXTRACTION_FAILED``. An
    implementation summing a page's streams before comparing — which is what the
    removed repair `edb2345f` did — decodes all three and answers that; one comparing
    after each decoded stream refuses ``TOO_LARGE`` on the second and never touches the
    third (ADR-0232 §8 arm 6).
    """
    objects = _Objects()
    font = objects.add(PLAIN_FONT)
    parts = [operators(part_bytes), operators(part_bytes), bytes(undecodable_bytes)]
    return document([Page(contents=parts, fonts={"/F1": font})], objects=objects)


def oversized_content_array_pdf(*, members: int, decoded_bytes: int) -> bytes:
    """One page whose ``/Contents`` array carries ``members`` references.

    The first names a stream decoding to ``decoded_bytes``; every one after it names a
    single shared fourteen-byte stream, so the *cardinality* is the amplification and
    the document stays small enough to build in a test. ``ContentStream.__init__``
    compares the array's length against ``CONTENT_STREAM_ARRAY_MAX_LENGTH`` before it
    resolves a member, so above that the extraction parses nothing at all while the
    first member alone would carry a walk past the bound — which is what makes this the
    document separating a class-faithful walk from one that charges first.

    Built by hand rather than through :func:`document`, because :class:`Page` gives each
    member its own object and this needs one object named many times.
    """
    objects = _Objects()
    catalogue = objects.reserve()
    tree = objects.reserve()
    page = objects.reserve()
    font = objects.add(PLAIN_FONT)
    first = objects.add(stream_object(drawing(decoded_bytes)))
    shared = objects.add(stream_object(b"0 0 m 1 1 l S\n"))
    objects.put(
        page,
        b"<< /Type /Page /Parent "
        + reference(tree)
        + b" /MediaBox "
        + _MEDIA_BOX
        + b" /Resources << /Font << /F1 "
        + font
        + b" >> >> /Contents ["
        + b" ".join([first, *[shared] * (members - 1)])
        + b"] >>",
    )
    objects.put(catalogue, b"<< /Type /Catalog /Pages " + reference(tree) + b" >>")
    objects.put(tree, b"<< /Type /Pages /Kids [" + reference(page) + b"] /Count 1 >>")
    return objects.build(root=catalogue)


def unreadable_resources_pdf() -> bytes:
    """A page whose ``/Resources`` entry is present and is **not a dictionary**.

    ADR-0232 §3's one fail-closed branch, and the one structure that cannot be confused
    with either answer beside it: an *absent* context and an operand naming *no* entry
    are answers the walk got, and both fetch. This is a question the walk cannot ask at
    all. ``pypdf`` itself is permissive here — ``"/Font" in`` an array is simply
    ``False``, so it parses the page and returns text — which is what makes this arm
    fail on any implementation that follows the library's own path (§8 arm 14).
    """
    objects = _Objects()
    return document(
        [Page(contents=[b"BT /F1 24 Tf 72 700 Td (unreadable) Tj ET"], resources=b"[/Bogus]")],
        objects=objects,
    )


def no_resources_pdf(*, decoded_bytes: int) -> bytes:
    """A page carrying megabytes of compressed operators and **no** ``/Resources``.

    ``PageObject._extract_text`` reads ``get_inherited(/Resources)`` and returns the
    empty string before it touches the content stream, on the ground that no resources
    means no font and so no text. So this document parses **zero** bytes, and a walk
    that decoded and charged the stream before resolving the resources would refuse a
    document ADR-0232 §2's stated quantity requires this seam to fetch (§8 arm 13).
    """
    objects = _Objects()
    return document([Page(contents=[operators(decoded_bytes)], resources=OMITTED)], objects=objects)


def capped_invocations_pdf(*, form_bytes: int, invocations: int) -> bytes:
    """A page invoking one small form past ``MAX_XFORM_INVOCATIONS_PER_EXTRACTION``.

    Past 5,000 invocations for a page the adopted extraction returns the empty string
    and **skips** the form rather than raising, so those are parses that never happen.
    A walk charging them refuses a document the extraction would have fetched, which is
    the "erring safely" error ADR-0232 §8 arm 13 exists to fail.

    The form draws a line rather than showing text, so what the invocation count decides
    here is the *charge* alone — thousands of copies of a text-carrying form would be
    refused by ``fetch_max_content_bytes`` and the arm would assert about that instead.
    It still carries a resource dictionary — a bare ``/ProcSet``, with no fonts to
    build — because a form whose inherited resources are absent or empty is not parsed
    at all and its charge would be zero however many times it were invoked.
    """
    objects = _Objects()
    drawn = b"0 0 m 1 1 l S\n"
    form = objects.add(
        form_object(drawn * (form_bytes // len(drawn)), resources=b"<< /ProcSet [/PDF] >>")
    )
    return document(
        [Page(contents=[b"/X1 Do\n" * invocations], forms={"/X1": form})],
        objects=objects,
    )


def object_stream_and_cmap_pdf(*, objstm_bytes: int, cmap_bytes: int) -> bytes:
    """A document whose large ``/ObjStm`` and large ``/ToUnicode`` are both decoded.

    The two decoded inputs ADR-0232 deliberately does **not** charge, in one document,
    both far over the bound and both inside ``fetch_max_file_bytes``. The object stream
    is decoded whole by ``PdfReader._get_object_from_stream`` during ordinary
    indirect-object resolution — before any per-page loop, so before any total exists —
    and it really is resolved here, because the page's font lives inside it. The CMap is
    decoded by ``_cmap.prepare_cm``. Each is read **once and cached**, so no per-parse
    multiplier acts on either, and that absence is the whole of the ground for leaving
    them out (§2, §3, §10). This document **fetches**, and the clause it pins is the one
    a later reader is most likely to widen back (§8 arm 11).

    It needs a **cross-reference stream** rather than the classic table every other
    fixture here uses, because an object inside an ``/ObjStm`` is reachable only through
    a type-2 entry, which a classic table has no way to spell.
    """
    cmap = _TO_UNICODE + b"\n%" + b"C" * max(cmap_bytes - len(_TO_UNICODE) - 2, 1)
    font_body = b"<< /Type /Font /Subtype /TrueType /BaseFont /Uncharged /ToUnicode 6 0 R >>"
    header = b"4 0 "
    objstm_data = header + font_body
    objstm_data += b"\n%" + b"S" * max(objstm_bytes - len(objstm_data) - 2, 1)
    bodies = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox "
        + _MEDIA_BOX
        + b" /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        5: stream_object(b"BT /F1 24 Tf 72 700 Td (A) Tj ET"),
        6: stream_object(cmap),
        7: stream_object(
            objstm_data,
            entries=b" /Type /ObjStm /N 1 /First " + str(len(header)).encode(),
        ),
    }
    return _assembled_with_xref_stream(bodies, compressed={4: (7, 0)}, root=1)


def _assembled_with_xref_stream(
    bodies: dict[int, bytes], *, compressed: dict[int, tuple[int, int]], root: int
) -> bytes:
    """Wrap numbered objects in a header and a PDF 1.5 cross-reference **stream**.

    Args:
        bodies: The objects written into the file, by number.
        compressed: Objects living inside an object stream, by number, as
            ``(object stream number, index within it)``.
        root: The catalogue's object number.

    Returns:
        The assembled document.
    """
    document = bytearray(b"%PDF-1.5\n")
    offsets: dict[int, int] = {}
    for number in sorted(bodies):
        offsets[number] = len(document)
        document += str(number).encode() + b" 0 obj\n" + bodies[number] + b"\nendobj\n"
    table_number = max([*bodies, *compressed]) + 1
    size = table_number + 1
    entries = bytearray(b"\x00" + (0).to_bytes(4, "big") + (65535).to_bytes(2, "big"))
    for number in range(1, size):
        if number in compressed:
            container, index = compressed[number]
            entries += b"\x02" + container.to_bytes(4, "big") + index.to_bytes(2, "big")
        else:
            offset = len(document) if number == table_number else offsets[number]
            entries += b"\x01" + offset.to_bytes(4, "big") + (0).to_bytes(2, "big")
    start = len(document)
    document += (
        str(table_number).encode()
        + b" 0 obj\n"
        + stream_object(
            bytes(entries),
            entries=b" /Type /XRef /Size "
            + str(size).encode()
            + b" /W [1 4 2] /Root "
            + reference(root)
            + b"",
        )
        + b"\nendobj\n"
    )
    document += b"startxref\n" + str(start).encode() + b"\n%%EOF\n"
    return bytes(document)


def unbuildable_font_pdf(*, decoded_bytes: int, subtype: bytes = b"/Type1") -> bytes:
    """A page whose font names a program under **two** ``/FontFile*`` keys.

    ``Font._parse_font_descriptor`` raises ``PdfReadError`` on that, and
    ``PageObject._extract_text`` builds a stream's fonts **before** it resolves the
    content key while swallowing only ``AttributeError`` and ``TypeError`` — so the
    page's content stream is parsed not at all, however large it is. A walk charging
    the stream first answers ``TOO_LARGE`` for a document that is malformed, which is
    the class confusion ADR-0232 §4 exists to prevent.

    ``subtype`` is a parameter because the library reaches that raise by **three**
    different routes, and a walk stating the condition instead of asking the library
    misses one of them at a time: ``/Type1``, ``/MMType1`` and ``/TrueType`` reach it
    whenever a ``/FontDescriptor`` is present; ``/Type3`` reaches it only where the font
    is *interpretable*, which with no ``/ToUnicode`` and no ``/CharProcs`` it is, since
    ``all(...)`` over nothing is true; and every **other** subtype reaches it through
    each entry of ``/DescendantFonts``, so a composite ``/Type0`` carries the malformed
    descriptor a level down where a top-level ``/FontDescriptor`` test does not look.
    """
    objects = _Objects()
    program = objects.add(stream_object(type1_program(2_000)))
    descriptor = objects.add(
        b"<< /Type /FontDescriptor /FontName /Twice /Flags 4 /FontFile "
        + program
        + b" /FontFile2 "
        + program
        + b" >>"
    )
    if subtype == b"/Type0":
        # A composite font carries no descriptor of its own: `from_font_resource`
        # reaches `_parse_font_descriptor` through each `/DescendantFonts` entry.
        descendant = objects.add(
            b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /Twice"
            b" /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >>"
            b" /FontDescriptor " + descriptor + b" >>"
        )
        font = objects.add(
            b"<< /Type /Font /Subtype /Type0 /BaseFont /Twice /Encoding /Identity-H"
            b" /DescendantFonts [" + descendant + b"] >>"
        )
    else:
        font = objects.add(
            b"<< /Type /Font /Subtype "
            + subtype
            + b" /BaseFont /Twice /FontDescriptor "
            + descriptor
            + b" >>"
        )
    return document(
        [Page(contents=[operators(decoded_bytes)], fonts={"/F1": font})], objects=objects
    )


def cmap_pages_pdf(*, pages: int, cmap_bytes: int) -> bytes:
    """``pages`` pages sharing one font whose ``/ToUnicode`` CMap is ``cmap_bytes``.

    The input ADR-0232 leaves uncharged and unbounded, in the shape that shows what it
    costs: the extraction re-parses that CMap once per page, so a walk establishing
    every font by building it would double a per-page cost this system does not govern.
    The padding is one ``%``-prefixed line, which ``process_cm_line`` returns on at
    once, so what the arm measures is the normalisation rather than a contrived parse.
    """
    objects = _Objects()
    cmap = objects.add(stream_object(_TO_UNICODE + b"\n%" + b"C" * cmap_bytes))
    font = objects.add(
        b"<< /Type /Font /Subtype /TrueType /BaseFont /Mapped /ToUnicode " + cmap + b" >>"
    )
    return document(
        [Page(contents=[b"BT /F1 24 Tf (A) Tj ET"], fonts={"/F1": font}) for _ in range(pages)],
        objects=objects,
    )
