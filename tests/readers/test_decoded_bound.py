"""ADR-0232's bound: what an extraction *parses*, counted before it parses it.

ADR-0230 §6 gave ``fetch_max_file_bytes`` two jobs — "the file's size on disk" and
"bounds the read **and the extraction's cost**" — and for a compressed format no
implementation can make both true (issue #2022). ADR-0232 keeps the file bound on the
read and adds ``fetch_max_decoded_bytes`` for the third quantity, with the parser as
its consumer: the decoded bytes an extraction **parses, summed once per parse**.

§8 is the list of arms this file owes, and it fixes how each is observed. **Every
refusal arm asserts that the parse was not entered, and none asserts a wall-clock
duration.** The observation is ``pypdf``'s own ``PageObject.extract_text`` — not called
for a page the bound refuses — which is deterministic, independent of the machine the
suite runs on, and proves exactly the property the arm is about. A wall-clock threshold
proves less and flakes: tight enough to catch the regression it would fail a descheduled
worker, loose enough not to it would pass a regression spending seconds again.

**Every arm runs with the other two bounds set high enough that only the one under test
can decide it** (§8 arm 7). An amplified stream yields far more text than 32 KiB, so an
arm left at the defaults would assert about ``fetch_max_content_bytes`` while naming
this one. Where the *default* is the subject — arms 10 and 12 — it is stated in the arm.

The fixtures are ADR-0232's own measured documents at test scale. Its figures — 313 s
for 16 MB of operators, 33.9 s for a form-carried 4 MB, 126.6 s for one 100 KB form
invoked five hundred times, 257.1 s for 2,000 pages sharing a 40 MB program — are the
*shape* of the finding rather than numbers a suite can assert, which is why each
document's amplification is an argument and each arm picks the smallest figure that
makes its own property decidable.
"""

from __future__ import annotations

import importlib.util
import io
from typing import TYPE_CHECKING, Final

import pypdf
import pytest
from fetch_fixtures import fetcher as build
from pdf_fixtures import (
    amplified_content_stream_pdf,
    capped_invocations_pdf,
    charged_font_programs_pdf,
    cmap_pages_pdf,
    content_array_pdf,
    drawing,
    extracted_text_of,
    form_carried_amplification_pdf,
    hollow_invocations_pdf,
    inherited_form_pdf,
    literal_do_pdf,
    minimal_pdf,
    no_resources_pdf,
    object_stream_and_cmap_pdf,
    oversized_content_array_pdf,
    pages_sharing_a_font,
    repeated_form_pdf,
    tounicode_font_pdf,
    type1_font_pages_pdf,
    unbuildable_font_pdf,
    unreadable_resources_pdf,
)
from pypdf import _cmap as cmap_module

from ai_assistant.core.types import FetchOutcome, FetchRefusal
from ai_assistant.readers import DEFAULT_FETCH_MAX_DECODED_BYTES

if TYPE_CHECKING:
    from pathlib import Path

#: Out of the way, for every arm whose subject is not the text bound.
UNBOUNDED_TEXT: Final = 1 << 40

#: Out of the way, for every arm whose subject is not the read bound.
UNBOUNDED_FILE: Final = 1 << 30

#: What ADR-0232 §3's walk stops descending at, mirroring the adopted extraction.
#: Pinned against ``pypdf``'s own constant below rather than trusted.
_CAP: Final = 5_000

#: How many members an array-based ``/Contents`` may carry before the adopted parser
#: refuses it outright. Pinned against ``pypdf``'s own constant below, like ``_CAP``.
_ARRAY_CAP: Final = 10_000

#: A word an arm can look for in a record, so "the text arrived" is checkable rather
#: than merely non-empty.
DISTINCTIVE: Final = "Ipsissima verba stroopwafel"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A directory of this test's own, since the fetcher holds a handle on one."""
    directory = tmp_path / "documents"
    directory.mkdir()
    return directory


@pytest.fixture
def parsed(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Every page ``pypdf``'s own ``extract_text`` was entered for.

    Counted on the **library's** method rather than on a substituted page collection: a
    double in place of it would exercise this file's scaffolding rather than the path a
    real document takes, which is the move ``test_local_file_fetcher.py`` makes for the
    same reason one bound over.
    """
    entered: list[object] = []
    real = pypdf.PageObject.extract_text

    def counted(self: object, *args: object, **kwargs: object) -> str:
        entered.append(self)
        return real(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pypdf.PageObject, "extract_text", counted)
    return entered


async def fetch(  # noqa: PLR0913 — a root, a document, its name and the three bounds
    root: Path,
    data: bytes,
    *,
    name: str = "document.pdf",
    max_decoded_bytes: int = DEFAULT_FETCH_MAX_DECODED_BYTES,
    max_content_bytes: int = UNBOUNDED_TEXT,
    max_file_bytes: int = UNBOUNDED_FILE,
) -> FetchOutcome:
    """Put ``data`` under ``root`` and fetch it, through the real fetcher.

    End to end rather than against ``_extract`` directly, because what ADR-0232 changes
    is the ``Fetcher`` **outcome**: a document that resolved to a record resolves to a
    ``TOO_LARGE`` refusal, and that is a fact about the seam rather than about a helper.

    **The entry is taken by ``name`` and not by position.** A listing is ordered most
    recently modified first with the *name* as the tie-break (``files.py``), so on a
    filesystem whose timestamps cannot separate two writes in the same test the first
    entry is whichever name sorts lower — not the document this call just wrote. Three
    arms here write a second document into the same root to state a property from both
    sides, and one of them, ``repeated.pdf`` after ``document.pdf``, would then assert
    the refusal against the admitted document and fail.
    """
    (root / name).write_bytes(data)
    subject = build(
        root,
        max_file_bytes=max_file_bytes,
        max_content_bytes=max_content_bytes,
        max_decoded_bytes=max_decoded_bytes,
    )
    try:
        listing = await subject.listing()
        entry = next(candidate for candidate in listing.entries if candidate.name == name)
        return await subject.fetch(listing, entry)
    finally:
        subject.close()


# --- §8 arms 1 to 3: the three amplifications, each refused before the parse ---


async def test_an_amplified_content_stream_is_refused_before_it_is_parsed(
    root: Path, parsed: list[object]
) -> None:
    """§8 arm 1 — #2022's own document, and the defect this bound exists to close.

    About 47 KB on disk, one page, 16 MB of decoded operators in its own ``/Contents``.
    Neither of ADR-0230 §6's figures reaches it: the file bound is satisfied by the
    compressed bytes, and the content bound is counted on extracted text, which exists
    only once the whole stream has been parsed. Measured at **313 s** and 737 MB of
    resident memory before this bound existed.
    """
    outcome = await fetch(root, amplified_content_stream_pdf())

    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert outcome.record is None
    assert parsed == []


async def test_a_form_carried_amplification_is_refused_and_contents_is_not_the_count(
    root: Path, parsed: list[object]
) -> None:
    """§8 arm 2 — "the arm that fails on any implementation counting ``/Contents``".

    The page's own content stream is seven bytes, ``/X1 Do``, on both documents here.
    What differs is the Form XObject those seven bytes invoke, which
    ``PageObject._extract_text__xform`` follows and parses as a content stream of its
    own — so the small one fetches and the large one is refused, and the quantity
    deciding it is not the page's ``/Contents`` at either end.
    """
    admitted = await fetch(root, form_carried_amplification_pdf(decoded_bytes=1_000))
    assert admitted.record is not None
    assert parsed != []

    refused = await fetch(root, form_carried_amplification_pdf(), name="amplified.pdf")
    assert refused.refusal is FetchRefusal.TOO_LARGE
    assert refused.record is None
    assert len(parsed) == 1, "the amplified document's page was parsed"


async def test_a_repeatedly_invoked_form_is_charged_once_per_invocation(
    root: Path, parsed: list[object]
) -> None:
    """§8 arm 3 — "the arm that fails on any implementation counting distinct streams".

    Both documents carry the **same** distinct decoded bytes: one 100 KB form and a
    page stream of ``/X1 Do`` lines. One invokes it once and one five hundred times,
    and the adopted version's cycle guard refuses only a *re-entrant* form, so the
    second is five hundred parses of the same stream. A walk counting distinct streams
    sees about 105 KB in both cases and admits both; a walk counting per parse sees
    50 MB in the second and refuses it.
    """
    once = await fetch(root, repeated_form_pdf(invocations=1))
    assert once.record is not None
    assert parsed != []

    many = await fetch(root, repeated_form_pdf(), name="repeated.pdf")
    assert many.refusal is FetchRefusal.TOO_LARGE
    assert many.record is None
    assert len(parsed) == 1, "the repeatedly-invoking document's page was parsed"


# --- §8 arm 4: the three documents an over-approximating walk refuses ---------


async def test_a_document_using_forms_legitimately_is_not_refused(root: Path) -> None:
    """§8 arm 4 — a small form invoked a few times fetches, and its text is recorded."""
    outcome = await fetch(root, repeated_form_pdf(form_bytes=1_000, invocations=5))

    assert outcome.record is not None
    assert outcome.record.content.count("A") > 100


async def test_a_literal_do_in_a_string_is_not_an_invocation(root: Path) -> None:
    """§8 arm 4 — "the arm that fails on any walk scanning bytes".

    A valid content stream can carry ``(Do) Tj`` with no form anywhere, and this page
    names no ``/XObject`` at all. Its counted quantity is its own stream and nothing
    else, because what counts as an invocation is the *adopted extraction's* answer
    rather than a second grammar's — the walk parses the stream with ``pypdf``'s own
    parser and takes the ``Do`` **operations** it reports.
    """
    outcome = await fetch(root, literal_do_pdf(), max_decoded_bytes=64)

    assert outcome.record is not None
    assert "Do" in outcome.record.content


async def test_a_form_named_in_inherited_resources_is_resolved_there(root: Path) -> None:
    """§8 arm 4 — "the arm that fails on any walk resolving an operand elsewhere".

    The page carries no ``/Resources`` of its own; the form is named on the ``/Pages``
    node it inherits from, which is where ``get_inherited(/Resources)`` finds it. A walk
    reading only the page's own dictionary resolves the operand to nothing, charges
    nothing, and admits a parse it was supposed to count — unsound in the direction the
    bound exists to close.
    """
    outcome = await fetch(root, inherited_form_pdf(form_text=DISTINCTIVE))

    assert outcome.record is not None
    assert DISTINCTIVE in outcome.record.content


# --- §8 arms 5 to 7: where the comparison sits, and what it is a total over ---


async def test_the_bound_is_a_running_total_and_refuses_at_the_crossing_page(
    root: Path, parsed: list[object]
) -> None:
    """§8 arm 5 — "the arm that fails on any implementation applying it per page".

    Three pages, each well inside the bound and each drawing rather than showing text,
    whose sum passes it. A per-page ceiling admits an unbounded document made of bounded
    pages, which is the defect ``fetch_max_content_bytes`` is already summed to avoid.
    """
    body = drawing(400_000)
    assert len(body) * 2 < DEFAULT_FETCH_MAX_DECODED_BYTES < len(body) * 3

    outcome = await fetch(root, pages_sharing_a_font([body] * 3))

    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert outcome.record is None
    assert len(parsed) == 2, "the crossing page and the one after it were not parsed"


async def test_the_comparison_sits_between_decoded_streams(root: Path) -> None:
    """§8 arm 6 — "the arm that fails on ``edb2345f`` as written".

    One page whose ``/Contents`` is an **array**. The first two members are ordinary and
    cross the bound between them; the third declares more decoded bytes than ``pypdf``'s
    own ``ZLIB_MAX_OUTPUT_LENGTH`` admits, so decoding it raises and the fetch would be
    ``EXTRACTION_FAILED``. An implementation summing a page's streams before comparing
    decodes all three and answers that; one comparing after each decoded stream refuses
    ``TOO_LARGE`` on the second and never touches the third.

    Asserted on **what was decoded** rather than on elapsed time, which is what §8's
    preamble asks of this arm: the class returned is itself the observation.
    """
    outcome = await fetch(root, content_array_pdf(part_bytes=600_000, undecodable_bytes=80_000_000))

    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert outcome.record is None


async def test_the_comparison_sits_between_charged_font_programs(
    root: Path, parsed: list[object]
) -> None:
    """Arm 6's property over the **other** counted input, which no arm here pinned.

    ADR-0232 §3's comparison clause names "a page's charged font programs" among what
    no implementation decodes several of and compares the sum of afterwards. Every font
    arm below charges **one** program per parse, so a regression batching a resource
    dictionary's programs and comparing once at the end of the loop would pass all of
    them: it would decode the second program before comparing, and where that program
    cannot decode it would answer ``EXTRACTION_FAILED`` instead of the ``TOO_LARGE``
    the first alone had already earned (issue #2046).

    One page, two charged ``/Type1`` fonts, no ``/Contents``. The first program crosses
    the bound on its own; the second declares more decoded bytes than ``pypdf``'s own
    ``ZLIB_MAX_OUTPUT_LENGTH`` admits, so decoding it raises. An implementation summing
    a resource dictionary's programs before comparing decodes both and answers the
    malformed class; one comparing after each decoded program refuses ``TOO_LARGE`` on
    the first and never touches the second. The class returned is the observation, as
    it is in the arm above.
    """
    program = 1_200_000
    assert program > DEFAULT_FETCH_MAX_DECODED_BYTES

    outcome = await fetch(
        root,
        charged_font_programs_pdf(program_bytes=program, undecodable_bytes=80_000_000),
    )

    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert outcome.record is None
    assert parsed == []


@pytest.mark.parametrize("over", [False, True])
async def test_the_boundary_value_extracts_and_one_byte_over_is_refused(
    root: Path, over: bool
) -> None:
    """§8 arm 7 — a document whose counted quantity is exactly the bound, both ways.

    The counted quantity here is one page's one content stream, so its decoded length
    *is* the charge and the boundary is a number this test knows rather than infers.
    """
    body = drawing(10_000)

    outcome = await fetch(
        root,
        pages_sharing_a_font([body]),
        max_decoded_bytes=len(body) - 1 if over else len(body),
    )

    if over:
        assert outcome.refusal is FetchRefusal.TOO_LARGE
        assert outcome.record is None
    else:
        assert outcome.record is not None


# --- §8 arms 8 and 9: the documents this bound must leave alone ---------------


async def test_a_document_inside_every_bound_is_unaffected(root: Path) -> None:
    """§8 arm 8 — every bound at its shipped default, and the text arrives whole."""
    lines = [DISTINCTIVE, "second line"]
    outcome = await fetch(
        root,
        minimal_pdf(lines),
        max_content_bytes=32 * 1024,
        max_file_bytes=4 * 1024 * 1024,
    )

    assert outcome.refusal is None
    assert outcome.record is not None
    assert outcome.record.content == extracted_text_of(lines)


@pytest.mark.parametrize("name", ["notes.txt", "notes.md"])
async def test_a_plain_text_file_over_the_decoded_bound_is_fetched(root: Path, name: str) -> None:
    """§8 arm 9 — "the arm that fails on any implementation applying it to a format
    with no decoding step".

    A text file's extraction parses the file's own bytes, which
    ``fetch_max_file_bytes`` already bounds at the read, so there is no ratio between
    bytes read and bytes parsed for a decoded bound to refuse. The counted quantity is
    **zero** and the bound is not consulted at all.
    """
    text = DISTINCTIVE + "x" * (2 * DEFAULT_FETCH_MAX_DECODED_BYTES)
    outcome = await fetch(root, text.encode("utf-8"), name=name, max_file_bytes=4 * 1024 * 1024)

    assert outcome.refusal is None
    assert outcome.record is not None
    assert outcome.record.content == text


# --- §8 arms 10 to 12: the font program, charged per parse and only where decoded ---


async def test_a_font_carried_amplification_is_refused_and_the_charge_is_per_page(
    root: Path, parsed: list[object]
) -> None:
    """§8 arm 10 — "the arm that fails on any implementation charging it once".

    Content-free pages sharing **one** ``/Type1`` font with a ``/FontFile`` and no
    ``/ToUnicode``. The adopted extraction rebuilds a stream's fonts on every
    ``_extract_text`` call, so the program is re-scanned once per page and the charge
    is the program times the page count — which is why the 0.217 MiB, 2,000-page,
    40 MB-program document ADR-0232 measured **fetched** after 257 s with nothing
    refusing it.

    The program here is comfortably **inside** the bound, which is the whole of the
    arm: charged once this document is admitted, charged per page it crosses at the
    fourth. It runs at the shipped default, because the default is what §2 argues.
    """
    program = 300_000
    assert program < DEFAULT_FETCH_MAX_DECODED_BYTES
    crossing = DEFAULT_FETCH_MAX_DECODED_BYTES // program + 1

    outcome = await fetch(
        root, type1_font_pages_pdf(pages=crossing + 4, fonts=1, program_bytes=program)
    )

    assert outcome.refusal is FetchRefusal.TOO_LARGE
    assert outcome.record is None
    assert len(parsed) == crossing - 1, (
        "the crossing page and every page after it must not have been parsed"
    )


async def test_a_font_program_the_extraction_never_decodes_is_charged_nothing(
    root: Path,
) -> None:
    """§8 arm 11 — "the arm that fails on any implementation charging ``/FontFile*``".

    A 2 MB ``/FontFile2`` on a font carrying a normal ``/ToUnicode``.
    ``Font.from_font_resource`` resolves a font file with ``get_object()``, which does
    not decode, and the one conditional decode in ``pypdf._font.py`` sits behind
    ``HAS_FONTTOOLS`` — ``False`` in this environment, which the last arm in this file
    pins. So nothing reads this program, and charging it would refuse on bytes the
    extraction never decodes. A *fetch* arm, because what it asserts is the absence of a
    charge and there is no refusal to observe.
    """
    outcome = await fetch(root, tounicode_font_pdf(program_bytes=2_000_000))

    assert outcome.refusal is None
    assert outcome.record is not None
    assert outcome.record.content == "A"


async def test_the_inputs_read_once_and_cached_are_not_charged(root: Path) -> None:
    """§8 arm 11 — the boundary §2 and §3 draw, and "the clause a later reader is most
    likely to widen back".

    A 2 MB compressed object stream and a 2 MB ``/ToUnicode`` CMap, both decoded whole
    during this fetch and both far over the bound, in a document of under 5 KB. Neither
    is charged, and the ground is neither their cost per byte nor any limit ``pypdf``
    happens to carry: each is read **once and cached**, so no per-parse multiplier acts
    on either. §10 defers both by name, with what fires them.

    The object stream is genuinely resolved rather than merely present — the page's font
    lives inside it, so the fetch below cannot succeed without
    ``PdfReader._get_object_from_stream`` having decoded it whole.
    """
    data = object_stream_and_cmap_pdf(objstm_bytes=2_000_000, cmap_bytes=2_000_000)
    resources = pypdf.PdfReader(io.BytesIO(data)).pages[0]["/Resources"]
    font = resources["/Font"]["/F1"]  # type: ignore[index]
    assert font["/BaseFont"] == "/Uncharged", "the object stream was not resolved"

    outcome = await fetch(root, data)

    assert outcome.refusal is None
    assert outcome.record is not None
    assert outcome.record.content == "A"


async def test_the_refused_ordinary_class_is_pinned_at_the_default(root: Path) -> None:
    """§8 arm 12 — so raising the default is a decision and not a discovery.

    ADR-0232 §2 accepts a real over-refusal and names the class in a table: documents of
    N pages carrying F ``/Type1`` fonts with ``/FontFile`` and no ``/ToUnicode``, which
    is dvips-era TeX output. A twenty-page paper with one font charges 0.67 MiB and is
    admitted; a thirty-page paper with a roman, an italic and a maths font charges
    3.00 MiB and is **refused** while costing 37 ms. Raising the figure to admit it was
    measured and is worse — 8 MiB multiplies the instruction worst case by about
    thirty-eight and 16 MiB readmits #2022's document whole — so the cost is accepted,
    and §10 defers the extractor change that removes it without moving the figure.
    """
    ordinary = type1_font_pages_pdf(pages=20, fonts=1, program_bytes=34 * 1024)
    admitted = await fetch(root, ordinary)
    assert admitted.refusal is None
    assert admitted.record is not None

    paper = type1_font_pages_pdf(pages=30, fonts=3, program_bytes=34 * 1024)
    refused = await fetch(root, paper, name="paper.pdf")
    assert refused.refusal is FetchRefusal.TOO_LARGE

    charge = 30 * 3 * 34 * 1024
    assert charge == 3_133_440, "§2's table records this class at 3.00 MiB"
    raised = await fetch(root, paper, name="raised.pdf", max_decoded_bytes=charge)
    assert raised.refusal is None
    assert raised.record is not None


# --- §8 arms 13 and 14: the walk stops where the extraction stops -------------


async def test_a_page_with_no_resource_context_is_charged_nothing(root: Path) -> None:
    """§8 arm 13 — "the arm that fails on any walk that decodes before it resolves".

    ``PageObject._extract_text`` reads ``get_inherited(/Resources)`` and returns the
    empty string **before it touches the content stream**, on the ground that no
    resources means no font and so no text. So this page's four megabytes of compressed
    operators are parsed **not at all**, and a walk charging them refuses a document
    ADR-0232 §2's stated quantity requires this seam to fetch. A *fetch* arm, and one of
    the pair that fails an implementation erring "safely" by over-charging.
    """
    outcome = await fetch(root, no_resources_pdf(decoded_bytes=4_000_000))

    assert outcome.refusal is None
    assert outcome.record is not None
    assert outcome.record.content == ""


@pytest.mark.parametrize("bound_at_the_capped_charge", [True, False])
async def test_invocations_past_the_libraries_cap_are_parses_that_never_happen(
    root: Path, bound_at_the_capped_charge: bool
) -> None:
    """§8 arm 13 — "the arm that fails on any walk charging parses the extraction skips".

    Past ``MAX_XFORM_INVOCATIONS_PER_EXTRACTION`` for one page the adopted extraction
    returns the empty string and **skips** the form rather than raising. This page
    invokes one small form two hundred times past that, so the charge over the
    invocations actually performed is inside the bound while the total over *all* of
    them is not.

    Pinned from both sides, because one alone is satisfied by a walk that charges too
    little as readily as by one that charges right: at the capped charge it fetches, and
    one byte under it is refused. A walk charging all 5,200 refuses at the first.
    """
    form_bytes, invocations = 28, _CAP + 200
    capped = _CAP * form_bytes + invocations * len(b"/X1 Do\n")
    assert capped < invocations * form_bytes + invocations * len(b"/X1 Do\n")

    outcome = await fetch(
        root,
        capped_invocations_pdf(form_bytes=form_bytes, invocations=invocations),
        max_decoded_bytes=capped if bound_at_the_capped_charge else capped - 1,
    )

    if bound_at_the_capped_charge:
        assert outcome.refusal is None
        assert outcome.record is not None
    else:
        assert outcome.refusal is FetchRefusal.TOO_LARGE


@pytest.mark.parametrize("hollow", [_CAP, _CAP - 1])
async def test_a_form_with_no_stream_data_still_spends_an_invocation(
    root: Path, hollow: int
) -> None:
    """The cap is spent by every invocation the extraction reaches, not only the ones
    this walk can descend into.

    ``_extract_text__xform`` reads ``/Subtype``, returns for an ``/Image``, checks the
    cycle and the cap, and **then** increments — before anything asks whether the object
    has data to parse. So a bare ``<< /Subtype /Form >>`` spends an invocation, and a
    page invoking one exactly ``_CAP`` times has no invocation left for the real form
    that follows: its extraction parses none of it and the document must fetch. One
    invocation fewer and the real form *is* parsed, so the same document is genuinely
    over the bound.

    Both sides, because either alone is passed by a walk that is wrong: skipping the
    hollow form without counting it refuses the first document — §3's named harm, "it
    refuses a document the stated quantity says must fetch" — and counting it without
    the second document would be satisfied by a walk that had stopped descending
    altogether.
    """
    outcome = await fetch(root, hollow_invocations_pdf(hollow=hollow, form_bytes=2_000_000))

    if hollow == _CAP:
        assert outcome.refusal is None
        assert outcome.record is not None
    else:
        assert outcome.refusal is FetchRefusal.TOO_LARGE
        assert outcome.record is None


def test_the_library_extracts_the_document_whose_cap_the_hollow_forms_exhaust() -> None:
    """The library fact the arm above rests on, asserted rather than assumed.

    ``pypdf`` alone returns text for the document whose hollow invocations exhaust the
    cap — it does not raise, and it never parses the real form behind them. Without this
    the arm above could be read as asserting only that *something* refused, rather than
    that the walk agreed with the extraction about which parses happen.
    """
    data = hollow_invocations_pdf(hollow=_CAP, form_bytes=2_000_000)

    reader = pypdf.PdfReader(io.BytesIO(data))

    assert reader.pages[0].extract_text() == ""


async def test_a_resource_context_that_cannot_be_read_fails_closed(
    root: Path, parsed: list[object]
) -> None:
    """§8 arm 14 — §3's one fail-closed branch, and the only clause that refuses
    ``EXTRACTION_FAILED``.

    A ``/Resources`` entry that is **present** and is not a dictionary: the walk cannot
    establish what the extraction will parse, so the fetch is refused rather than
    extracted on the hope. Deliberately **not** an absent context and **not** an operand
    naming no form — those are answers, the arms above fetch on both, and an
    implementation collapsing the three fails one of the two.

    ``pypdf`` itself is permissive here and returns a record, which is asserted rather
    than assumed: this is the arm that fails on any implementation following the adopted
    library's own path for a structure the walk did not understand.
    """
    data = unreadable_resources_pdf()
    permissive = pypdf.PdfReader(io.BytesIO(data)).pages[0].extract_text()
    assert permissive != "", "the library's own path returns text for this document"
    parsed.clear()  # that demonstration is this test's own and not the fetch's

    outcome = await fetch(root, data)

    assert outcome.refusal is FetchRefusal.EXTRACTION_FAILED
    assert outcome.record is None
    assert parsed == []


@pytest.mark.parametrize(
    ("members", "expected"),
    [
        (_ARRAY_CAP + 1, FetchRefusal.EXTRACTION_FAILED),
        (_ARRAY_CAP, FetchRefusal.TOO_LARGE),
    ],
)
async def test_a_content_array_the_parser_refuses_is_not_a_size_refusal(
    root: Path, parsed: list[object], members: int, expected: FetchRefusal
) -> None:
    """An array over the parser's own cardinality guard parses **nothing**, so the
    class is the malformed one and not the bound's.

    ``ContentStream.__init__`` compares the array's length against
    ``CONTENT_STREAM_ARRAY_MAX_LENGTH`` **before it resolves a member**, so the
    extraction of a page over it decodes not one byte. A walk charging the members
    first crosses the bound on the first of them and answers ``TOO_LARGE`` for a
    document the extraction refuses as malformed — the class confusion ADR-0232 §4
    exists to prevent, one structure over from the resource context above.

    **Both sides, because one alone passes an implementation that guesses.** The same
    document one member *under* the guard is one the extraction really does decode, and
    it really is over the bound, so it is ``TOO_LARGE``: a walk refusing every large
    array as malformed would fail here, and a walk charging first would fail above.
    Neither document is fetched by any reading — what is under test is only which
    refusal the operator is sent to.
    """
    data = oversized_content_array_pdf(members=members, decoded_bytes=2_000_000)

    outcome = await fetch(root, data)

    assert outcome.refusal is expected
    assert outcome.record is None
    assert parsed == []


def test_the_content_arrays_cardinality_guard_is_the_libraries_own() -> None:
    """The walk refuses the array where the extraction refuses it, in both directions.

    The sibling of the invocation-cap pin below, and pinned for the same reason: a
    *lowered* guard would leave the walk charging an array the extraction has stopped
    parsing, and a *raised* one would have it refuse an array the extraction parses
    happily — the first is the class confusion this arm is about and the second refuses
    a document ADR-0232 §2's stated quantity requires this seam to fetch.
    """
    from pypdf.generic._data_structures import (  # noqa: PLC0415 — read only to pin it
        CONTENT_STREAM_ARRAY_MAX_LENGTH,
    )

    assert _ARRAY_CAP == CONTENT_STREAM_ARRAY_MAX_LENGTH


def test_the_library_refuses_the_oversized_array_before_it_decodes_anything() -> None:
    """The library fact the arm above mirrors, asserted rather than assumed.

    ``pypdf`` alone raises for the document one member over the guard and returns text
    for the document one member under it — which is what makes the pair of refusal
    classes above the extraction's own rather than this walk's invention.
    """
    over = oversized_content_array_pdf(members=_ARRAY_CAP + 1, decoded_bytes=2_000)
    under = oversized_content_array_pdf(members=_ARRAY_CAP, decoded_bytes=2_000)

    with pytest.raises(Exception, match="Array-based stream"):
        pypdf.PdfReader(io.BytesIO(over)).pages[0].extract_text()

    assert pypdf.PdfReader(io.BytesIO(under)).pages[0].extract_text() == ""


# --- §8 arms 16 and 17, and the two library facts the walk mirrors ------------


def test_the_refusal_enumeration_did_not_grow() -> None:
    """§8 arm 16 — ``FetchRefusal`` stays closed at five members.

    ADR-0232 §4 adds none: a refusal on this bound is a ``TOO_LARGE``, which the audit's
    one field already carries and which ADR-0230 §6's enumeration already closes. A
    member meaning *your file was small on disk and large once decompressed* would be
    the same disclosure §6 declines to make about a file's type, one property over. The
    audit half of this arm is ADR-0232 §7's, which adds no field, event, key or emission
    point, so nothing in this diff reaches it.
    """
    assert len(FetchRefusal) == 5
    assert FetchRefusal.TOO_LARGE in set(FetchRefusal)


def test_font_tools_is_not_resolvable() -> None:
    """§8 arm 17 — the environment property ADR-0232 §3's predicate is stated for.

    ``_charged_font_program`` charges exactly ``pypdf._cmap._parse_to_unicode``'s
    condition for entering ``_type1_alternative``, and that is the **only** font-program
    decode ``extract_text`` reaches *in an environment without* ``fontTools``: were it
    resolvable, ``pypdf._font.py``'s ``HAS_FONTTOOLS`` branch would open a second decode
    under a different condition and the predicate would be incomplete.

    Pinned by a test rather than asserted in prose, which is the shape ADR-0230's Lane
    C1 used for the page-tree guards. ``fontTools`` is not in ``pyproject.toml`` or in
    ``uv.lock``; this fails if it ever arrives, which is what fires ADR-0232 §10's
    deferral of that case.
    """
    assert importlib.util.find_spec("fontTools") is None


def test_the_walks_invocation_cap_is_the_libraries_own() -> None:
    """The walk stops descending where the extraction does, in both directions.

    ADR-0232 §6 forbids leaning on a dependency's limit **as a bound this system states
    as its own**, and nothing here does: the bound is ``fetch_max_decoded_bytes`` and
    this system enforces it. What this number decides is only *which parses happen* —
    the same question the resource context decides — and a walk disagreeing with the
    extraction about that is unsound in one direction and over-refuses in the other. A
    lowered cap would make the walk charge parses that no longer happen; a raised one
    would make it miss parses that do. Either fails here rather than silently.
    """
    from pypdf._page import (  # noqa: PLC0415 — a private name, read only to pin it
        MAX_XFORM_INVOCATIONS_PER_EXTRACTION,
    )

    assert _CAP == MAX_XFORM_INVOCATIONS_PER_EXTRACTION


def test_the_shipped_default_is_the_figure_the_decision_names() -> None:
    """ADR-0232 §2 fixes 1 MiB by argument, so a drift here is a drift from the ADR.

    Thirty-two times ``fetch_max_content_bytes``, so the bound refuses only a document
    parsing more than thirty-two bytes of operators per byte of text it yields; and on
    the cost side, 1 MB of operators parsed in about 6 s against 313 s at 16 MB. An
    operator raising it buys superlinearly more.
    """
    assert DEFAULT_FETCH_MAX_DECODED_BYTES == 1024 * 1024


@pytest.mark.parametrize("over_the_bound", [True, False])
@pytest.mark.parametrize("subtype", [b"/Type1", b"/MMType1", b"/TrueType", b"/Type3", b"/Type0"])
async def test_a_font_the_extraction_cannot_build_precedes_the_content_charge(
    root: Path, parsed: list[object], over_the_bound: bool, subtype: bytes
) -> None:
    """§3's fail-closed branch reached through font *initialisation*, not resources.

    ``PageObject._extract_text`` builds a stream's fonts **before** it resolves the
    content key, and it swallows only ``AttributeError`` and ``TypeError`` while doing
    so. A ``/FontDescriptor`` naming a program under two ``/FontFile*`` keys makes
    ``Font._parse_font_descriptor`` raise ``PdfReadError``, so the page's content stream
    is parsed **not at all** — however large it is.

    A walk charging the content stream first therefore answers ``TOO_LARGE`` for a
    malformed document, which is exactly the class confusion ADR-0232 §4 exists to
    prevent: "report a size refusal as an extraction failure and that operator goes
    looking for corrupt files", and the reverse sends them to bounds that are not the
    problem. Both directions are run, because the class must not depend on the size of a
    stream nothing parses — and **every route the library reaches that raise by** is
    run, because there are three and a walk *stating* the condition rather than asking
    the library misses one at a time: three subtypes reach it whenever a
    ``/FontDescriptor`` is present; ``/Type3`` reaches it only where the font is
    *interpretable*, which with no ``/ToUnicode`` and no ``/CharProcs`` it is; and every
    other subtype reaches it through each ``/DescendantFonts`` entry, so a composite
    ``/Type0`` carries the malformed descriptor a level below where a top-level test
    looks. Rounds 3, 4 and 5 of this PR's review found those three in that order, which
    is why the implementation now calls ``Font.from_font_resource`` instead.
    """
    data = unbuildable_font_pdf(
        decoded_bytes=4_000_000 if over_the_bound else 1_000, subtype=subtype
    )
    with pytest.raises(Exception, match="More than one /FontFile"):
        pypdf.PdfReader(io.BytesIO(data)).pages[0].extract_text()
    parsed.clear()  # that demonstration is this test's own and not the fetch's

    outcome = await fetch(root, data)

    assert outcome.refusal is FetchRefusal.EXTRACTION_FAILED
    assert outcome.record is None
    assert parsed == []


async def test_the_walk_does_not_reparse_a_to_unicode_cmap(
    root: Path, parsed: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The walk adds no parse of an input ADR-0232 leaves uncharged and unbounded.

    A ``/ToUnicode`` CMap is decoded and **parsed** once per page — ``get_data`` caches
    the decompression, not ``prepare_cm``'s normalisation or the mapping dictionary it
    builds — and §2 and §10 leave it uncharged and unbounded by name. So a walk that
    established every font by building it would double a per-page cost this system does
    not govern, which is unratified work on the seam the bound exists to make honest.
    ``_establish_font`` therefore asks only about a font carrying no ``/ToUnicode``.

    Asserted on the **count of parses**, not on elapsed time: one per page extracted,
    never two. A duration would flake and would prove less, which is §8's own standard
    for every other arm here. That the per-page multiplier exists at all is issue #2042,
    which fires §10's deferral and is not this PR's to close.
    """
    prepared: list[object] = []
    real = cmap_module.prepare_cm

    def counted(font: object) -> bytes:
        prepared.append(font)
        return real(font)  # type: ignore[arg-type]

    monkeypatch.setattr(cmap_module, "prepare_cm", counted)
    pages = 3
    outcome = await fetch(root, cmap_pages_pdf(pages=pages, cmap_bytes=200_000))

    assert outcome.refusal is None
    assert outcome.record is not None
    assert len(parsed) == pages
    assert len(prepared) == pages, (
        f"the CMap was prepared {len(prepared)} times over {pages} extracted pages; "
        f"the walk must add no parse of an input the bound does not charge"
    )
