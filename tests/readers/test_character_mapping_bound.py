"""ADR-0234's bound: the `/ToUnicode` CMap, charged on two quantities rather than one.

ADR-0232 §10 deferred a font's `/ToUnicode` CMap on exactly one ground — "each is read
**once** and cached, so no per-parse multiplier acts on either" — and that ground is
false for the CMap: `PageObject._extract_text` rebuilds a stream's fonts on **every**
call, so `prepare_cm`'s normalisation and `_parse_to_unicode`'s dictionary build repeat
once for every page. ADR-0234 §1 brings it inside the bound.

**Two quantities, because neither is a function of the other.** `pypdf`'s
`parse_bfrange` builds `b - a + 1` mappings from one range line, so 65,000 mappings
arrive in 927,031 bytes of `bfchar` or in **178** of `bfrange` — a factor of about
5,200. A byte charge on this input would be "a number that looks like a bound, is
checkable, and is not a function of the cost it claims to bound": the document §5's
table ends on charges 450,000 bytes, under half the byte default, and costs four and a
half minutes. So the CMap's decoded bytes join `fetch_max_decoded_bytes` and the
mappings its parse builds take `fetch_max_character_mappings`, and **arms 2 and 3 are
what pin the two fields as two** — one fails every byte-only implementation, the other
every mappings-only one.

§7 is the list of arms this file owes, and ADR-0232 §8's preamble governs every one of
them: **every refusal arm asserts that the parse was not entered** — `pypdf`'s own
`PageObject.extract_text` not called for the crossing page — **and none asserts a
wall-clock duration**. Every arm runs with the bounds it is not about set high enough
that only the one under test can decide it.

The fixtures are ADR-0234's own measured documents rebuilt at test scale, and two of
them reproduce its figures exactly: `bfrange_cmap(90_000)` builds 90,000 mappings and
leaves a dictionary of 65,536, and forty pages sharing one 3,000-mapping `bfchar` CMap
charge 120,000 mappings. Where a figure is an *elapsed time* it is the shape of the
finding rather than something a suite asserts.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Final

import pypdf
import pytest
from fetch_fixtures import fetcher as build
from pdf_fixtures import (
    SMALLEST_TO_UNICODE,
    bfchar_cmap,
    bfrange_cmap,
    cmap_pages_pdf,
    drawing,
    mapped_font_pages_pdf,
    named_to_unicode_pages_pdf,
    object_stream_and_cmap_pdf,
    pages_sharing_a_font,
    type1_font_pages_pdf,
    unbuildable_font_pdf,
    unselected_cmap_font_pdf,
)
from pypdf import _cmap as cmap_module
from pypdf.errors import LimitReachedError
from pypdf.generic import DictionaryObject, NameObject, StreamObject

from ai_assistant.core.types import FetchOutcome, FetchRefusal
from ai_assistant.readers import (
    DEFAULT_FETCH_MAX_CHARACTER_MAPPINGS,
    DEFAULT_FETCH_MAX_DECODED_BYTES,
)

if TYPE_CHECKING:
    from pathlib import Path

#: Out of the way, for every arm whose subject is not the text bound.
UNBOUNDED_TEXT: Final = 1 << 40

#: Out of the way, for every arm whose subject is not the read bound.
UNBOUNDED_FILE: Final = 1 << 30

#: Out of the way, for every arm whose subject is the *mapping* term. ADR-0234 §7 arms
#: 2, 4, 5, 7, 8 and 10 all run with the byte bound raised, because "arms 2 and 3
#: together are what pin the two fields as two" and an arm left at the byte default
#: could be passed by an implementation that never counted a mapping.
UNBOUNDED_BYTES: Final = 1 << 40

#: Out of the way, for every arm whose subject is the *byte* term.
UNBOUNDED_MAPPINGS: Final = 1 << 40

#: What ``prepare_cm`` builds for a ``/ToUnicode`` that is not a stream, pinned against
#: the library below rather than trusted.
_SYNTHESISED: Final = 2


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A directory of this test's own, since the fetcher holds a handle on one."""
    directory = tmp_path / "documents"
    directory.mkdir()
    return directory


@pytest.fixture
def parsed(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Every page ``pypdf``'s own ``extract_text`` was entered for.

    Counted on the **library's** method rather than on a substituted page collection, for
    ``test_decoded_bound.py``'s reason one bound over: a double in place of it would
    exercise this file's scaffolding rather than the path a real document takes.
    """
    entered: list[object] = []
    real = pypdf.PageObject.extract_text

    def counted(self: object, *args: object, **kwargs: object) -> str:
        entered.append(self)
        return real(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pypdf.PageObject, "extract_text", counted)
    return entered


async def fetch(  # noqa: PLR0913 — a root, a document, its name and the four bounds
    root: Path,
    data: bytes,
    *,
    name: str = "document.pdf",
    max_character_mappings: int = DEFAULT_FETCH_MAX_CHARACTER_MAPPINGS,
    max_decoded_bytes: int = DEFAULT_FETCH_MAX_DECODED_BYTES,
    max_content_bytes: int = UNBOUNDED_TEXT,
    max_file_bytes: int = UNBOUNDED_FILE,
) -> FetchOutcome:
    """Put ``data`` under ``root`` and fetch it, through the real fetcher.

    End to end rather than against ``_extract`` directly, because what ADR-0234 changes
    is the ``Fetcher`` **outcome**: a document that resolved to a record resolves to a
    ``TOO_LARGE`` refusal. The entry is taken by ``name`` and not by position, since a
    listing's order is by modification time with the name as the tie-break and several
    arms here write two documents into one root.
    """
    (root / name).write_bytes(data)
    subject = build(
        root,
        max_file_bytes=max_file_bytes,
        max_content_bytes=max_content_bytes,
        max_decoded_bytes=max_decoded_bytes,
        max_character_mappings=max_character_mappings,
    )
    try:
        listing = await subject.listing()
        entry = next(candidate for candidate in listing.entries if candidate.name == name)
        return await subject.fetch(listing, entry)
    finally:
        subject.close()


def counts_of(cmap: bytes) -> tuple[int, int, int]:
    """What one CMap costs, taken from the library's own parse of it.

    Returns:
        Its decoded length, the mappings its parse **builds**, and the size of the
        dictionary that survives — three numbers rather than one because ADR-0234 §2
        turns on the first two being independent and §7 arm 4 on the last two differing.
    """
    document = mapped_font_pages_pdf(pages=1, cmap=cmap)
    reader = pypdf.PdfReader(io.BytesIO(document))
    font = reader.pages[0]["/Resources"]["/Font"]["/F1"]  # type: ignore[index]
    assert isinstance(font, DictionaryObject)
    stream = font["/ToUnicode"]
    assert isinstance(stream, StreamObject)
    surviving, built = cmap_module._parse_to_unicode(font)
    return len(stream.get_data()), len(built), len(surviving)


# --- §7 arm 1: the amplification, refused, and charged per font-build ---------


async def test_a_cmap_carried_amplification_is_refused_and_the_charge_is_per_build(
    root: Path, parsed: list[object]
) -> None:
    """§7 arm 1 — "the arm that fails on any implementation charging a distinct CMap a
    single time", and on any charging no CMap at all.

    Content-free pages sharing **one** font whose ``/ToUnicode`` is a 3,000-mapping
    ``bfchar`` CMap of about 42 KB. ``_extract_text`` rebuilds a stream's fonts on every
    call, so the CMap is decoded and re-normalised once per page and the charge is its
    length times the page count. Charged once it is 42 KB and this document is admitted;
    charged per build it crosses 1 MiB at the twenty-fifth page.

    **Pinned from both sides**: the same document at one page fetches, which is what
    makes the refusal a statement about the multiplier rather than about the CMap's own
    size. It runs at the shipped byte default, because the default is what ADR-0232 §2
    argues, and with the mapping bound raised so only the byte term can decide it.
    """
    cmap = bfchar_cmap(3_000)
    decoded, _, _ = counts_of(cmap)
    assert decoded < DEFAULT_FETCH_MAX_DECODED_BYTES, "one CMap must be inside the bound"
    crossing = DEFAULT_FETCH_MAX_DECODED_BYTES // decoded + 1

    refused = await fetch(
        root,
        mapped_font_pages_pdf(pages=crossing + 3, cmap=cmap),
        max_character_mappings=UNBOUNDED_MAPPINGS,
    )

    assert refused.refusal is FetchRefusal.TOO_LARGE
    assert refused.record is None
    assert len(parsed) == crossing - 1, (
        "the crossing page and every page after it must not have been parsed"
    )

    parsed.clear()
    admitted = await fetch(
        root,
        mapped_font_pages_pdf(pages=1, cmap=cmap),
        name="one-page.pdf",
        max_character_mappings=UNBOUNDED_MAPPINGS,
    )

    assert admitted.refusal is None
    assert admitted.record is not None


# --- §7 arms 2 and 3: the two quantities, each bounded where the other cannot --


async def test_the_mapping_term_is_bounded_where_the_byte_term_cannot_reach_it(
    root: Path, parsed: list[object]
) -> None:
    """§7 arm 2 — "the arm that fails every byte-only implementation".

    A ``/ToUnicode`` of **178 bytes** declaring 24,000 mappings through ``bfrange`` range
    lines, shared across twenty pages. The mapping total passes
    ``fetch_max_character_mappings`` at the seventeenth page while the byte total — under
    four kilobytes — sits four hundred times inside ``fetch_max_decoded_bytes``. It runs
    with the byte bound **raised**, so that only the mapping bound can decide it and an
    implementation charging the CMap's bytes faithfully still fails here.

    This is the arm ADR-0234's second field exists for: ``parse_bfrange`` builds
    ``b - a + 1`` mappings from a twenty-byte line, so a range declares mappings at a rate
    no byte count tracks.
    """
    cmap = bfrange_cmap(24_000)
    decoded, built, _ = counts_of(cmap)
    assert decoded == 178, "the range form is what makes the byte total say nothing"
    crossing = DEFAULT_FETCH_MAX_CHARACTER_MAPPINGS // built + 1
    pages = crossing + 3

    outcome = await fetch(
        root,
        mapped_font_pages_pdf(pages=pages, cmap=cmap),
        max_decoded_bytes=UNBOUNDED_BYTES,
    )

    assert pages * decoded < DEFAULT_FETCH_MAX_DECODED_BYTES, (
        "the byte total must sit far inside the sibling bound, or this arm proves nothing"
    )
    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert outcome.record is None
    assert len(parsed) == crossing - 1


async def test_the_byte_term_is_bounded_where_the_mapping_term_cannot_reach_it(
    root: Path, parsed: list[object]
) -> None:
    """§7 arm 3 — "the arm that fails a mappings-only implementation".

    The converse: a ``/ToUnicode`` of several hundred kilobytes declaring **one**
    mapping, shared across enough pages that the byte total passes
    ``fetch_max_decoded_bytes`` while the mapping total sits four figures inside
    ``fetch_max_character_mappings``. It runs with the mapping bound raised.

    The byte term is charged even though it is cheap — about 0.004 s per decoded MB per
    page against 1.4 s per MB for operators — because it is separately amplified by the
    page count, and ADR-0232 §2 has already ruled on what that is worth: "cheap per byte
    times an unbounded page count is not cheap". Held at 1,800 mappings a CMap's marginal
    cost still runs 0.006 s a page at 25 KB to 0.037 s at 8 MB.
    """
    cmap_bytes = 400_000
    crossing = DEFAULT_FETCH_MAX_DECODED_BYTES // cmap_bytes + 1

    outcome = await fetch(
        root,
        cmap_pages_pdf(pages=crossing + 2, cmap_bytes=cmap_bytes),
        max_character_mappings=UNBOUNDED_MAPPINGS,
    )

    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert outcome.record is None
    assert len(parsed) == crossing - 1


# --- §7 arm 4: the mappings built, not the dictionary that survives -----------


async def test_the_count_is_the_mappings_built_and_not_the_dictionary_kept(
    root: Path, parsed: list[object]
) -> None:
    """§7 arm 4 — "the arm that fails an implementation taking the size of the
    surviving dictionary", which is the obvious thing to reach for.

    A CMap whose ranges wrap the two-byte code space declares more mappings than it
    leaves keys: **90,000 built against 65,536 kept**, which is ADR-0234's own measured
    pair reproduced here. ``_check_mapping_size`` counts the former, ``Font``'s
    ``character_map`` carries the latter, and only the former is what the build costs —
    a CMap sending two source codes to one key pays for both, because the cost is in the
    insertions.

    So the bound is set **between** the two counts. An implementation counting the
    surviving dictionary admits this document; one counting the insertions refuses it,
    with the page never parsed.
    """
    cmap = bfrange_cmap(90_000)
    _, built, kept = counts_of(cmap)
    assert (built, kept) == (90_000, 65_536), "ADR-0234 §7 arm 4's measured pair"
    between = (built + kept) // 2

    outcome = await fetch(
        root,
        mapped_font_pages_pdf(pages=1, cmap=cmap),
        max_character_mappings=between,
        max_decoded_bytes=UNBOUNDED_BYTES,
    )

    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert outcome.record is None
    assert parsed == []


# --- §7 arm 5: a name-valued `/ToUnicode`, both ways -------------------------


@pytest.mark.parametrize("just_under", [True, False])
async def test_a_name_valued_to_unicode_is_charged_two_mappings_a_build(
    root: Path, parsed: list[object], just_under: bool
) -> None:
    """§7 arm 5 — "the arm that fails an implementation exempting a non-stream
    ``/ToUnicode``", and the boundary is exactly two mappings a build.

    One font **object** under five resource names, on three pages: ``_extract_text``
    builds every *entry* of the ``/Font`` dictionary, so the extraction performs fifteen
    builds and ``prepare_cm`` parses its synthesised literal fifteen times. Nothing is
    decoded for it — the literal is the library's own 44 bytes — but the two mappings
    that literal declares are built every time, and the number of font-builds is a
    quantity the document controls entirely.

    Refused just under twice the build count and fetched just at it, with the byte bound
    raised so only the mapping bound can decide it. One mapping under the whole document's
    charge is crossed on its **last** page, so the two pages before it are extracted and
    the crossing one is not — which is the same statement as ``parsed == []`` on an arm
    whose first page crosses, in the form this document's arithmetic takes.
    """
    pages, names = 3, 5
    builds = pages * names
    charge = builds * _SYNTHESISED

    outcome = await fetch(
        root,
        named_to_unicode_pages_pdf(pages=pages, names=names),
        max_character_mappings=charge - 1 if just_under else charge,
        max_decoded_bytes=UNBOUNDED_BYTES,
    )

    if just_under:
        assert outcome.refusal is FetchRefusal.TOO_LARGE
        assert outcome.record is None
        assert len(parsed) == pages - 1
    else:
        assert outcome.refusal is None
        assert outcome.record is not None
        assert len(parsed) == pages


async def test_a_name_valued_to_unicode_is_charged_no_decoded_bytes(
    root: Path,
) -> None:
    """§7 arm 5's second half — "the arm that fails an implementation charging the
    synthesised literal's bytes, which are never decoded".

    The same document at a raised mapping bound fetches with a byte bound of **one**.
    ``prepare_cm`` reads no stream for a ``/ToUnicode`` that is not one, so there is no
    decoded length to charge, and the pages are content-free so nothing else is charged
    either — which makes a byte bound of 1 the sharpest form this can take.
    """
    outcome = await fetch(
        root,
        named_to_unicode_pages_pdf(pages=3, names=5),
        max_character_mappings=UNBOUNDED_MAPPINGS,
        max_decoded_bytes=1,
    )

    assert outcome.refusal is None
    assert outcome.record is not None


# --- §7 arm 6: the predicate is `/ToUnicode` present, in both directions ------


async def test_a_font_that_is_not_type1_is_charged_its_cmap(
    root: Path, parsed: list[object]
) -> None:
    """§7 arm 6's first half — "the arm that fails any implementation carrying ADR-0232
    §3's three-key font-program predicate over to this input".

    A ``/TrueType`` font with a ``/ToUnicode`` and no ``/FontDescriptor`` at all. The
    program predicate begins with *no* ``/ToUnicode``, tests ``/Subtype`` for ``/Type1``
    and requires a ``/FontDescriptor`` carrying a ``/FontFile``; this one meets none of
    that and is charged anyway, because ADR-0234 §1's predicate is "``/ToUnicode``
    present and resolving to a stream, and that is the whole of it".
    """
    cmap = bfrange_cmap(1_000)
    _, built, _ = counts_of(cmap)

    outcome = await fetch(
        root,
        mapped_font_pages_pdf(pages=1, cmap=cmap),
        max_character_mappings=built - 1,
        max_decoded_bytes=UNBOUNDED_BYTES,
    )

    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert outcome.record is None
    assert parsed == []


async def test_a_font_with_no_to_unicode_is_charged_no_mapping(root: Path) -> None:
    """§7 arm 6's second half — ADR-0232 §8 arm 10 still passing, one bound over.

    A document of ``/Type1`` fonts carrying ``/FontFile`` programs and **no**
    ``/ToUnicode`` fetches with ``fetch_max_character_mappings`` set to **one**: nothing
    on this path builds a mapping, because ``_parse_to_unicode`` returns before
    ``prepare_cm`` where the key is absent. An implementation charging every font
    something would fail here, and a ``.txt`` or ``.md`` file is never refused on this
    bound for the same reason (ADR-0234 §2).
    """
    outcome = await fetch(
        root,
        type1_font_pages_pdf(pages=4, fonts=2, program_bytes=2_000),
        max_character_mappings=1,
    )

    assert outcome.refusal is None
    assert outcome.record is not None


@pytest.mark.parametrize("suffix", [".txt", ".md"])
async def test_a_text_file_is_never_refused_on_the_mapping_bound(root: Path, suffix: str) -> None:
    """ADR-0234 §2's plain-text clause, in ADR-0232 §3's own words.

    "For plain text and Markdown the counted quantity is zero, and no implementation
    checks ``fetch_max_character_mappings`` on those formats": their extraction has no
    decoding step, so it builds no mapping. Asserted at a bound of one, which is the
    lowest a deployment can configure.
    """
    outcome = await fetch(
        root,
        b"Ipsissima verba stroopwafel",
        name=f"note{suffix}",
        max_character_mappings=1,
        max_decoded_bytes=1,
    )

    assert outcome.refusal is None
    assert outcome.record is not None
    assert outcome.record.content == "Ipsissima verba stroopwafel"


# --- §7 arms 7 and 8: per font-build, and every entry ------------------------


@pytest.mark.parametrize("between_one_and_two", [True, False])
async def test_two_fonts_sharing_one_cmap_are_charged_twice(
    root: Path, parsed: list[object], between_one_and_two: bool
) -> None:
    """§7 arm 7 — "the arm that fails an implementation charging a CMap once per parse
    rather than once per font-build", which is the reading ADR-0234 §3 forbids.

    One page whose resource context carries **two** font dictionaries naming the *same*
    ``/ToUnicode`` stream. ``PageObject._extract_text`` builds every entry of the
    ``/Font`` dictionary, so it parses that CMap twice on that page, and the count is a
    property of the stream while the charge is a property of the build. An
    implementation charging one CMap once per page under-charges by the number of fonts
    sharing it.

    Refused at a figure between one and two times the count, and fetched at twice it.
    """
    cmap = bfrange_cmap(1_000)
    _, built, _ = counts_of(cmap)
    configured = 2 * built - 1 if between_one_and_two else 2 * built

    outcome = await fetch(
        root,
        mapped_font_pages_pdf(pages=1, cmap=cmap, fonts=2),
        max_character_mappings=configured,
        max_decoded_bytes=UNBOUNDED_BYTES,
    )

    if between_one_and_two:
        assert outcome.refusal is FetchRefusal.TOO_LARGE
        assert outcome.record is None
        assert parsed == []
    else:
        assert outcome.refusal is None
        assert outcome.record is not None


@pytest.mark.parametrize("under_the_count", [True, False])
async def test_a_font_the_operators_never_select_is_charged(
    root: Path, parsed: list[object], under_the_count: bool
) -> None:
    """§7 arm 8 — "the arm that fails an implementation charging only the fonts the
    content stream selects", which would under-charge every parse.

    A page whose content stream names ``/F1`` — a plain font with no ``/ToUnicode`` —
    while ``/F2`` carries the CMap and is named by no ``Tf`` at all. ``_extract_text``
    builds the whole ``/Font`` dictionary **before** it resolves the content key, so the
    predicate ADR-0234 §1 fixes needs no forecast of which fonts the operators select.

    Both sides, because the refusal alone would pass an implementation that refused
    everything.
    """
    cmap = bfrange_cmap(1_000)
    _, built, _ = counts_of(cmap)

    outcome = await fetch(
        root,
        unselected_cmap_font_pdf(cmap=cmap),
        max_character_mappings=built - 1 if under_the_count else built,
        max_decoded_bytes=UNBOUNDED_BYTES,
    )

    if under_the_count:
        assert outcome.refusal is FetchRefusal.TOO_LARGE
        assert outcome.record is None
        assert parsed == []
    else:
        assert outcome.refusal is None
        assert outcome.record is not None


# --- §7 arm 9: #2043's first residual, closed by §4's unconditional establishment ---


@pytest.mark.parametrize("over_the_bound", [True, False])
@pytest.mark.parametrize("subtype", [b"/Type1", b"/MMType1", b"/TrueType", b"/Type3", b"/Type0"])
async def test_an_unbuildable_to_unicode_font_is_extraction_failed(
    root: Path, parsed: list[object], over_the_bound: bool, subtype: bytes
) -> None:
    """§7 arm 9 — "the arm that fails an implementation keeping the ``/ToUnicode``
    exclusion", and #2043's first residual closed as a **consequence** of §4.

    A font carrying a perfectly readable ``/ToUnicode`` *and* a ``/FontDescriptor``
    naming one program under two ``/FontFile*`` keys, which makes
    ``Font._parse_font_descriptor`` raise ``PdfReadError``. ``_extract_text`` builds a
    stream's fonts before it resolves the content key and swallows only
    ``AttributeError`` and ``TypeError``, so the page's content stream is parsed **not at
    all** — however large it is.

    Before ADR-0234, ``_establish_font`` was asked only of a font carrying **no**
    ``/ToUnicode``, so this document's content stream was charged and it was refused
    ``TOO_LARGE`` where the extraction alone answers ``EXTRACTION_FAILED`` — the class
    confusion ADR-0232 §4 exists to prevent, which "sends an operator to their bounds
    when the answer is a corrupt file". Both directions of the content stream's size are
    run, because the class must not depend on the size of a stream nothing parses, and
    every route the library reaches that raise by is run, for the reason
    ``test_decoded_bound.py``'s sibling arm gives.
    """
    data = unbuildable_font_pdf(
        decoded_bytes=4_000_000 if over_the_bound else 1_000,
        subtype=subtype,
        to_unicode=True,
    )
    with pytest.raises(Exception, match="More than one /FontFile"):
        pypdf.PdfReader(io.BytesIO(data)).pages[0].extract_text()
    parsed.clear()  # that demonstration is this test's own and not the fetch's

    outcome = await fetch(root, data)

    assert outcome.refusal is FetchRefusal.EXTRACTION_FAILED
    assert outcome.record is None
    assert parsed == []


# --- §7 arms 10 and 11: the boundary, and a document inside every bound -------


@pytest.mark.parametrize("one_over", [True, False])
async def test_the_boundary_value_extracts_and_one_mapping_over_is_refused(
    root: Path, parsed: list[object], one_over: bool
) -> None:
    """§7 arm 10 — the boundary value, both ways, for the new field.

    A document whose mapping charge is *exactly* ``fetch_max_character_mappings``
    extracts, and one mapping over is refused. The pair is what makes the comparison a
    ``>`` rather than a ``>=``: an off-by-one in either direction fails exactly one of
    these and neither alone would show it.
    """
    cmap = bfrange_cmap(1_000)
    _, built, _ = counts_of(cmap)
    pages = 4
    charge = pages * built

    outcome = await fetch(
        root,
        mapped_font_pages_pdf(pages=pages, cmap=cmap),
        max_character_mappings=charge - 1 if one_over else charge,
        max_decoded_bytes=UNBOUNDED_BYTES,
    )

    if one_over:
        assert outcome.refusal is FetchRefusal.TOO_LARGE
        assert outcome.record is None
        assert len(parsed) == pages - 1
    else:
        assert outcome.refusal is None
        assert outcome.record is not None
        assert len(parsed) == pages


async def test_a_document_inside_every_bound_is_unaffected(root: Path) -> None:
    """§7 arm 11 — the fetch arm, at the shipped defaults.

    A few pages carrying an ordinary ``/ToUnicode`` CMap: its text reaches the record
    whole, with no bound having refused anything. This is what makes every refusal arm
    above a statement about the amplification rather than about the mechanism existing.
    """
    text = "Ipsissima verba stroopwafel"
    body = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()

    outcome = await fetch(
        root, mapped_font_pages_pdf(pages=3, cmap=bfchar_cmap(200), contents=body)
    )

    assert outcome.refusal is None
    assert outcome.record is not None
    assert outcome.record.content.count(text) == 3


# --- §7 arm 12: ADR-0232 §8 arm 11's CMap half, replaced ---------------------


@pytest.mark.parametrize("raised", [False, True])
async def test_the_object_streams_cmap_sibling_refuses_at_the_defaults(
    root: Path, raised: bool
) -> None:
    """§7 arm 12's CMap half — "the boundary this ADR draws where ADR-0232 drew the
    other one, and the clause a later reader is most likely to widen back".

    The very document ADR-0232 §8 arm 11 asserted **fetches** with neither input charged:
    a 2 MB compressed object stream and a 2 MB ``/ToUnicode`` CMap, both decoded whole
    during the fetch, in a file of under 5 KB. Its ``/ObjStm`` half is unchanged and
    stays a fetch arm in ``test_decoded_bound.py`` — ADR-0234 §6 re-states that deferral
    on a measurement rather than firing it — and its CMap half is now a **refusal**,
    fetching only with both of ADR-0234's figures raised.

    The object stream is genuinely resolved rather than merely present: the page's font
    lives inside it, so neither outcome below is reachable without
    ``_get_object_from_stream`` having decoded it whole.
    """
    data = object_stream_and_cmap_pdf(objstm_bytes=2_000_000, cmap_bytes=2_000_000)
    resources = pypdf.PdfReader(io.BytesIO(data)).pages[0]["/Resources"]
    font = resources["/Font"]["/F1"]  # type: ignore[index]
    assert font["/BaseFont"] == "/Uncharged", "the object stream was not resolved"

    outcome = await fetch(
        root,
        data,
        max_decoded_bytes=UNBOUNDED_BYTES if raised else DEFAULT_FETCH_MAX_DECODED_BYTES,
        max_character_mappings=(
            UNBOUNDED_MAPPINGS if raised else DEFAULT_FETCH_MAX_CHARACTER_MAPPINGS
        ),
    )

    if raised:
        assert outcome.refusal is None
        assert outcome.record is not None
        assert outcome.record.content == "A"
    else:
        assert outcome.refusal is FetchRefusal.TOO_LARGE
        assert outcome.record is None


# --- §7 arm 13: the refused ordinary class, and §5's headline document --------


async def test_the_refused_ordinary_class_is_pinned_at_the_defaults(root: Path) -> None:
    """§7 arm 13 — so that raising a default stays a decision and not a discovery.

    §5 names this class and chooses it rather than overlooking it: a forty-page document
    carrying one 3,000-mapping subset font, an entirely ordinary shape, is **refused** on
    the **byte** figure — about 43 KB of CMap charged forty times. It is a larger
    over-refusal than ADR-0232 §2's, because CMap bytes cost about 0.004 s per decoded MB
    per page against 1.4 s per MB for operators, and a smaller one in the currency that
    decides whether an over-refusal is tolerable: §2 accepted refusing a thirty-page paper
    that cost 37 ms, and this document costs 0.388 s.

    Its **mapping** charge is 120,000 — inside the mapping figure, which is §5's own
    point that "the byte charge over-states its cost about fifty-fold; the mapping charge
    tracks it to three figures" and is an argument for the extractor fix §9 defers rather
    than against charging the bytes.
    """
    cmap = bfchar_cmap(3_000)
    decoded, built, _ = counts_of(cmap)
    pages = 40
    charge = pages * decoded

    assert pages * built == 120_000, "§5's table records this class at 120,000 mappings"
    assert charge < 1_716_440 * 1.05, "§5's table records its byte charge at 1,716,440"

    refused = await fetch(root, mapped_font_pages_pdf(pages=pages, cmap=cmap))
    assert refused.refusal is FetchRefusal.TOO_LARGE
    assert refused.record is None

    raised = await fetch(
        root,
        mapped_font_pages_pdf(pages=pages, cmap=cmap),
        name="raised.pdf",
        max_decoded_bytes=charge,
    )
    assert raised.refusal is None
    assert raised.record is not None


async def test_the_document_that_cost_four_and_a_half_minutes_is_refused(
    root: Path, parsed: list[object]
) -> None:
    """§5's last row, "this ADR in one line", at the shipped defaults.

    Two thousand content-free pages sharing one ``bfrange`` CMap declaring **90,000**
    mappings: a file of a few hundred kilobytes whose byte charge is under half the byte
    default and which ``extract_text`` spends **four and a half minutes** on, yielding no
    text at all. Nothing but the mapping figure catches it — 0.14 to 0.19 s a page
    throughout, and the page count is bounded by nothing but the file bound.

    **Asserted over behaviour and never over a duration** (ADR-0232 §8's preamble): what
    this arm pins is that the mapping bound and not the byte bound is what refuses it,
    and that the crossing page and every page after it are never parsed. Measured on this
    machine while the lane ran, it refuses in about 1.2 s where the extraction alone costs
    about 286 s — the refusal is not "before the first page", because 90,000 mappings a
    page against a 400,000 figure crosses at the fifth.
    """
    cmap = bfrange_cmap(90_000)
    decoded, built, _ = counts_of(cmap)
    pages = 2_000
    crossing = DEFAULT_FETCH_MAX_CHARACTER_MAPPINGS // built + 1

    data = mapped_font_pages_pdf(pages=pages, cmap=cmap)
    assert pages * decoded < DEFAULT_FETCH_MAX_DECODED_BYTES // 2, (
        "the byte charge must sit under half the byte default, or this is not §5's row"
    )

    outcome = await fetch(root, data)

    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert outcome.record is None
    assert len(parsed) == crossing - 1


# --- §7 arm 15, and the library facts §8 has this lane re-establish -----------


def test_the_refusal_enumeration_did_not_grow() -> None:
    """§7 arm 15 — ``FetchRefusal`` stays closed at five members.

    ADR-0234 §4 adds none, over **either** of its fields: "an extraction refused on
    either field of this decision yields the ``FetchRefusal`` member ``TOO_LARGE``", and
    ADR-0232 §4's ruling that the class does not disclose which of the three bounds
    refused now reads over four. ADR-0232 §7's audit is untouched by that — no field, no
    event, no key and no emission point — so nothing in this diff reaches it, and the
    audit half of this arm is ``tests/orchestration/test_loop_fetch.py``'s.
    """
    assert len(FetchRefusal) == 5
    assert FetchRefusal.TOO_LARGE in set(FetchRefusal)


def test_the_shipped_default_is_the_figure_the_decision_names() -> None:
    """ADR-0234 §5 fixes 400,000 by argument, so a drift here is a drift from the ADR.

    At the dearest form ``pypdf`` will build a mapping from — ``bfchar``, 3.24 µs each —
    400,000 mappings is about 1.30 s of dictionary build, against about 1.4 s for the
    megabyte of ``Tj`` operators ``fetch_max_decoded_bytes``'s own default admits. **The
    two bounds' worst cases are matched deliberately**: an operator who has accepted one
    has accepted the other. It is a matching and not a derivation — ADR-0234 §2 forbids
    computing either figure from the other, and an operator who moves one moves nothing
    else.
    """
    assert DEFAULT_FETCH_MAX_CHARACTER_MAPPINGS == 400_000


def test_the_synthesised_literal_declares_two_mappings() -> None:
    """The library fact ``_SYNTHESISED_MAPPINGS`` mirrors, asserted rather than assumed.

    ``prepare_cm`` synthesises ``beginbfrange\\n<0000> <0001> <0000>\\nendbfrange`` for a
    ``/ToUnicode`` that is not a stream — 44 bytes, one range line, **two** mappings — and
    ADR-0234 §1 fixes the charge at that number. A release changing the literal in either
    direction fails here rather than silently under- or over-charging every font-build in
    the class ADR-0234 §9 records as the deferred fourth quantity.
    """
    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/TrueType")
    font[NameObject("/ToUnicode")] = NameObject("/Identity-H")

    literal = cmap_module.prepare_cm(font)
    _, built = cmap_module._parse_to_unicode(font)

    assert len(built) == _SYNTHESISED
    assert b"beginbfrange" in literal, "the branch that reads no stream is the one pinned"


def test_the_libraries_mapping_ceiling_raise_reaches_this_seam(root: Path) -> None:
    """ADR-0234 §3's checked fact: the walk answers the class the extraction answers.

    ``pypdf`` 6.16.2 caps a CMap at ``MAPPING_DICTIONARY_SIZE_LIMIT`` and **raises**
    ``LimitReachedError`` past it, and that raise propagates **out of** ``extract_text``.
    So ``_extract_pdf``'s own ``except`` answers ``EXTRACTION_FAILED`` for such a document
    today, and the walk's establishing parse meeting the same raise answers the same
    class — "no document changes class on account of this ADR's establishing parse".

    That ceiling is **evidence about the version this project resolves** and never a bound
    this system states as its own (ADR-0232 §6): ADR-0234 argues from none of it, and a
    release that raised, lowered or removed it would change no clause. What is asserted
    here is only that the library still raises, and that the raise still reaches this
    seam as one class.
    """
    over = cmap_module.MAPPING_DICTIONARY_SIZE_LIMIT + 1
    data = mapped_font_pages_pdf(pages=1, cmap=bfrange_cmap(over))

    with pytest.raises(LimitReachedError):
        pypdf.PdfReader(io.BytesIO(data)).pages[0].extract_text()


async def test_the_libraries_mapping_ceiling_is_one_class_through_this_seam(
    root: Path,
) -> None:
    """The other half of the arm above, over the ``Fetcher`` outcome.

    The walk reaches ``_parse_to_unicode`` before the extraction does, so the raise lands
    in :func:`_mapping_count`'s translation rather than in ``_extract_pdf``'s — and the
    class an operator sees is the same either way. Run at raised figures, so that what
    decides the outcome is the library's ceiling and not one of ours.
    """
    over = cmap_module.MAPPING_DICTIONARY_SIZE_LIMIT + 1

    outcome = await fetch(
        root,
        mapped_font_pages_pdf(pages=1, cmap=bfrange_cmap(over)),
        max_character_mappings=UNBOUNDED_MAPPINGS,
        max_decoded_bytes=UNBOUNDED_BYTES,
    )

    assert outcome.refusal is FetchRefusal.EXTRACTION_FAILED
    assert outcome.record is None


async def test_the_walk_parses_a_shared_cmap_at_most_once_per_font_per_fetch(
    root: Path, parsed: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0234 §3's ceiling: **at most F + 1 per fetch**, and never once per parse.

    The successor to ADR-0232's arm asserting the walk parsed a CMap not at all. §3 fixes
    a ceiling rather than an instrument: the walk asks ``_parse_to_unicode`` once per
    *stream* for the count and ``from_font_resource`` once per *font* for the
    establishment, both memoised for the fetch, so a CMap named by F distinct fonts is
    parsed by the walk at most **F + 1** times against the extraction's F times **per
    page**.

    So on this document — two fonts sharing one CMap over six pages — the extraction
    prepares it twelve times and the walk at most three, for fifteen in all. A walk
    asking per parse would prepare it twenty-four times, which is the multiplier this
    bound exists to refuse; asserted on the **count of parses** and never on elapsed time,
    which is §8's own standard for every arm here.
    """
    prepared: list[object] = []
    real = cmap_module.prepare_cm

    def counted(font: object) -> bytes:
        prepared.append(font)
        return real(font)  # type: ignore[arg-type]

    monkeypatch.setattr(cmap_module, "prepare_cm", counted)
    pages, fonts = 6, 2
    outcome = await fetch(
        root,
        mapped_font_pages_pdf(pages=pages, cmap=bfrange_cmap(100), fonts=fonts),
        max_character_mappings=UNBOUNDED_MAPPINGS,
        max_decoded_bytes=UNBOUNDED_BYTES,
    )

    assert outcome.refusal is None
    assert len(parsed) == pages
    by_the_extraction = pages * fonts
    ceiling = by_the_extraction + fonts + 1
    assert len(prepared) <= ceiling, (
        f"the CMap was prepared {len(prepared)} times; the walk may add at most "
        f"{fonts} + 1 to the extraction's {by_the_extraction} (ADR-0234 §3)"
    )
    assert len(prepared) > by_the_extraction, (
        "the walk must parse it at all — the establishing parse is what §3 requires"
    )
    assert len(prepared) < by_the_extraction * 2, (
        f"a walk asking per parse would prepare it {by_the_extraction * 2} times; that "
        f"multiplier is the whole of what ADR-0234 §3's two memos exist to remove"
    )


@pytest.mark.parametrize("pages", [1, 5, 20, 50])
def test_the_object_stream_is_resolved_once_whatever_the_page_count(pages: int) -> None:
    """ADR-0234 §6's measurement, re-established here against what ``uv.lock`` fixes.

    ADR-0232 §10 deferred the object stream and the CMap in one class, on one sentence —
    "each is read once and cached, so no per-parse multiplier acts on either" — and only
    one of them was ever true. ``PdfReader._get_object_from_stream`` parses every object
    in a stream in one pass and caches each through ``cache_indirect_object``, and
    ``get_object`` consults that cache before it reaches the stream at all.

    So it is entered **once** at 1, 5, 20 and 50 pages of a document whose page font lives
    inside a 2 MB ``/ObjStm`` — flat where the CMap's per-page cost is linear, which is
    the whole of the difference between the two halves of that class and the ground
    ADR-0234 §6 re-states the deferral on. What fires it is unchanged: a measurement
    showing it re-read or re-parsed per page, which this is the absence of.
    """
    entered: list[object] = []
    real = pypdf.PdfReader._get_object_from_stream

    def counted(self: object, indirect_reference: object) -> object:
        entered.append(indirect_reference)
        return real(self, indirect_reference)  # type: ignore[arg-type]

    data = object_stream_and_cmap_pdf(
        objstm_bytes=2_000_000, cmap_bytes=len(SMALLEST_TO_UNICODE), pages=pages
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(pypdf.PdfReader, "_get_object_from_stream", counted)
        reader = pypdf.PdfReader(io.BytesIO(data))
        for page in reader.pages:
            page.extract_text()

    assert len(entered) == 1, (
        f"the object stream was decoded {len(entered)} times over {pages} pages; "
        f"ADR-0234 §6's deferral rests on that number not moving with the page count"
    )


def test_every_font_is_built_before_the_content_key_is_resolved() -> None:
    """The library fact ADR-0234 §1's predicate rests on, re-established at the code.

    "``PageObject._extract_text`` iterates the whole ``/Font`` resource dictionary and
    calls ``Font.from_font_resource`` on each, swallowing only ``AttributeError`` and
    ``TypeError``, **before** it resolves the content key." So the CMap parse happens for
    every font the walk can already see, and the predicate needs no forecast of which
    fonts the operators will select.

    Observed rather than read: a page whose ``/Contents`` names an object that does not
    exist still builds its fonts, which is only possible if the build precedes the
    resolution. ``pages_sharing_a_font`` is the control — a page whose content *does*
    resolve, so the assertion below is about the order and not about fonts being built.
    """
    prepared: list[object] = []
    real = cmap_module.prepare_cm

    def counted(font: object) -> bytes:
        prepared.append(font)
        return real(font)  # type: ignore[arg-type]

    data = unselected_cmap_font_pdf(cmap=SMALLEST_TO_UNICODE)
    reader = pypdf.PdfReader(io.BytesIO(data))
    page = reader.pages[0]
    del page[pypdf.generic.NameObject("/Contents")]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cmap_module, "prepare_cm", counted)
        assert page.extract_text() == ""

    assert len(prepared) == 1, (
        "the font carrying the CMap was built even though the content key resolved to "
        "nothing, which is what makes ADR-0234 §1's predicate complete"
    )


async def test_the_two_bounds_are_two_and_neither_absorbs_the_other(root: Path) -> None:
    """ADR-0234 §2's "neither field may absorb the other's quantity", from both sides.

    The same document, at a byte bound that admits it and a mapping bound that does not,
    and then the reverse. If either figure were computed from the other — or if mappings
    were converted into notional bytes and charged to ``fetch_max_decoded_bytes`` — one of
    these four outcomes would be wrong, because "an exchange rate between the two would
    make an operator's byte figure govern a quantity that is not bytes, at a ratio no
    operator chose and no document respects".
    """
    cmap = bfrange_cmap(20_000)
    decoded, built, _ = counts_of(cmap)
    pages = 4
    bytes_charge, mapping_charge = pages * decoded, pages * built
    document = mapped_font_pages_pdf(pages=pages, cmap=cmap)

    admitted = await fetch(
        root,
        document,
        max_decoded_bytes=bytes_charge,
        max_character_mappings=mapping_charge,
    )
    on_mappings = await fetch(
        root,
        document,
        name="mappings.pdf",
        max_decoded_bytes=bytes_charge,
        max_character_mappings=mapping_charge - 1,
    )
    on_bytes = await fetch(
        root,
        document,
        name="bytes.pdf",
        max_decoded_bytes=bytes_charge - 1,
        max_character_mappings=mapping_charge,
    )

    assert admitted.refusal is None
    assert on_mappings.refusal is FetchRefusal.TOO_LARGE
    assert on_bytes.refusal is FetchRefusal.TOO_LARGE
    assert bytes_charge * 100 < mapping_charge, (
        "the two totals must be orders apart, or this document could not tell the fields "
        "apart at all"
    )


async def test_a_document_charging_neither_quantity_is_untouched(root: Path) -> None:
    """The control for the whole file: ADR-0232's own arms still pass unchanged.

    A page of drawing operators and one font meeting neither ADR-0232 §3's three keys nor
    ADR-0234 §1's predicate is charged its content stream and nothing else, at a mapping
    bound of one. ADR-0234 "adds nothing to the walk's shape and no new instrument" — the
    CMap is a further charge at a point the walk already stood at.
    """
    body = drawing(10_000)

    outcome = await fetch(
        root,
        pages_sharing_a_font([body]),
        max_character_mappings=1,
        max_decoded_bytes=len(body),
    )

    assert outcome.refusal is None
    assert outcome.record is not None
