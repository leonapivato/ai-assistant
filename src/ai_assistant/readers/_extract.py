"""The three formats ADR-0230 §6 puts on the first rung, and the bound on their text.

**Plain text, Markdown and PDF, and nothing else.** Any other file is *not listed*
(``files.py``), so there is no authentic entry naming one and no
``UNSUPPORTED_TYPE`` refusal to carry — an entry a caller assembles for a ``.docx``
under the root is refused ``NOT_FOUND`` by §4's membership clause, exactly as an
entry for a file the cap left out is.

**Extraction is a decoding and never a rendering** (§5): a deterministic,
library-performed transformation of bytes into the text they encode. No model is on
this path — nothing summarises, abridges, rewrites, annotates or classifies the text
between the file and the record — which is what lets ADR-0226 §1's refusal of "a
payload, a rendering, a summary or free text of any kind" stay satisfied.

**The bound is counted on the *quoted rendering*, and enforced while extracting.**
``fetch_max_content_bytes`` is measured on ``json.dumps`` at its default
``ensure_ascii=True``, its two delimiters included, because that is what the prompt
will carry. ADR-0222 §4 ruled the same question for a rendered reply and ADR-0230 §6
takes its reasoning: "a newline costs two output characters, a BMP code point six and
an astral one — an emoji — twelve, because ``json.dumps`` writes it as two surrogate
escapes rather than one. A ceiling on **source** characters would admit a span six or
twelve times this long while claiming to admit this much; counted on the output there
is nothing left to get wrong." A source-*byte* bound is the same defect one unit over:
32 KiB of emoji is 8,192 code points and renders as 96 KiB of escapes.

**The transform is written out here rather than imported**, which is ADR-0222 §4's own
instruction where three subsystems already hold their own copy: what is shared is that
ADR's number and this one's, not a module across a boundary golden rule 1 forbids
crossing. A fourth copy is the established shape and not a new coupling.

**Counted as it is produced, not after it is materialised** (§6). A PDF is read a page
at a time and the running total is checked after each; a text file is decoded whole,
because there is nothing to decode it in pieces *from* — its bytes are already bounded
by ``fetch_max_file_bytes``, so the worst case is the twelve-fold expansion of a
4 MiB file, which is materialised and discarded rather than put anywhere.

**A bound is enforced by refusing, never by truncating** (§6). Nothing here returns a
prefix, a first page, a first *n* bytes, an abridgement or a "first part of" record,
and nothing records a truncation flag in place of refusing. This is where the seam
departs from ADR-0222 §4 and the difference is the point: a reply exists and must be
rendered somehow, so §4 keeps its longest fitting prefix and marks the elision; a file
need not be fetched at all, and a model handed the first 32 KiB of a 90-page report
answers *about the report*, in the assistant's own voice, having seen a third of it.

**The text bound is not the only one, because the text is not the only cost**
(ADR-0232). ``fetch_max_content_bytes`` is counted on what reaches the prompt, which
for a compressed format exists only once the whole stream has been parsed — so it is
checked *after* the work it would have refused. ``fetch_max_decoded_bytes`` is the
third quantity with the third consumer: the decoded bytes the extraction **parses,
summed once per parse**, compared before each decoded stream is parsed. Plain text and
Markdown have no decoding step and count zero for it, so a ``.txt`` file larger than
that figure and inside ``fetch_max_file_bytes`` is fetched rather than refused;
:func:`_extract_pdf` is where the count is real.
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import pypdf
from pypdf._font import Font
from pypdf.generic import (
    ArrayObject,
    ContentStream,
    DictionaryObject,
    NameObject,
    StreamObject,
    is_null_or_none,
)

if TYPE_CHECKING:
    from pypdf.generic import PdfObject

# **`pypdf`'s own logging is silenced, and that is ADR-0004 §5 rather than tidiness.**
# The library reports a malformed document by logging it — "invalid pdf header",
# "Ignoring wrong pointing object" — through the standard `logging` module, at
# WARNING, with the offending bytes sometimes in the message. ADR-0004 §5's rule is
# that logs never contain Tier 1 data, and ADR-0230 §6 is explicit that a refusal
# "carries no path, no name, no excerpt and no message from an underlying library".
# Raising the level on that library's own root logger is the narrowest instrument
# that holds both, and it has to be the **level** rather than a filter: `pypdf`
# emits through `logging.getLogger(source)` where `source` is the emitting module —
# `pypdf._reader`, `pypdf.generic._data_structures` — so a filter installed on the
# parent never sees a child's record, while a level set there is the effective level
# every child inherits. Nothing else in this process is touched: the name is scoped
# to the library, and this project's own logging is `structlog` over the root.
#
# Nothing is lost that this seam owed anyone. What the caller gets is
# `EXTRACTION_FAILED`, which is the whole of what ADR-0230 lets a refusal say.
logging.getLogger("pypdf").setLevel(logging.CRITICAL + 1)

#: The file suffixes this rung reads, lowercased, mapped to nothing but their own
#: membership. Matched on the suffix and never on content sniffing: a listing has to
#: decide what to show *before* opening anything, and a decision that needed the bytes
#: would put a read where §6 has none.
SUPPORTED_SUFFIXES: Final = frozenset({".txt", ".md", ".markdown", ".pdf"})

#: The suffixes whose bytes are simply UTF-8 text. Markdown is deliberately in here
#: rather than given a renderer: what §5 requires is the file's text **verbatim**, and
#: a Markdown document's text is its source.
_TEXT_SUFFIXES: Final = frozenset({".txt", ".md", ".markdown"})

#: What the two JSON string delimiters cost, counted because §6 includes them.
_DELIMITERS: Final = 2

#: The keys the walk reads from a page and from a form. Spelled once, because a
#: typo in either would silently make the walk charge nothing.
_CONTENTS: Final = "/Contents"
_RESOURCES: Final = "/Resources"

#: How many Form XObject invocations the adopted extraction performs for one page
#: before it stops descending. Past this ``PageObject._extract_text__xform``
#: returns the empty string and **skips** the form — it does not raise — so
#: invocations past it are parses that never happen, and a walk charging them would
#: refuse a document ADR-0232 §2's stated quantity requires this seam to fetch (§3).
#:
#: **Pinned by a test rather than asserted here** (ADR-0232 §6, and Lane C1's own
#: shape for the page-tree guards): ``tests/readers/test_decoded_bound.py`` fails if
#: ``pypdf._page.MAX_XFORM_INVOCATIONS_PER_EXTRACTION`` stops being this number, in
#: either direction — a lowered cap would make this walk over-charge and a raised one
#: would make it under-charge. Mirroring the exit is **not** the reliance ADR-0232 §6
#: forbids: that clause forbids leaning on a dependency's limit *as a bound this
#: system states as its own*, and the bound here is ``fetch_max_decoded_bytes``,
#: which this module enforces. What this figure decides is only *which parses
#: happen*, which is the same question the resource context decides.
_MAX_XFORM_INVOCATIONS: Final = 5_000

#: How many members an array-based ``/Contents`` may carry before the adopted
#: extraction refuses it. ``ContentStream.__init__`` compares the array's length
#: against this **before it resolves or decodes a single member** and raises, so a
#: page over it is one whose extraction parses nothing at all — and a walk charging
#: its members first would answer ``TOO_LARGE`` for a document the extraction refuses
#: as malformed, which is the class confusion ADR-0232 §4 exists to prevent. The walk
#: therefore asks the same question in the same place.
#:
#: **Pinned by a test rather than asserted here**, exactly as the invocation cap above
#: is: ``tests/readers/test_decoded_bound.py`` fails if
#: ``pypdf.generic._data_structures.CONTENT_STREAM_ARRAY_MAX_LENGTH`` stops being this
#: number, in either direction. Mirroring it is not the reliance ADR-0232 §6 forbids —
#: what it decides is only *which parses happen*, the same question the resource
#: context and the invocation cap decide, and the bound this module states as its own
#: is still ``fetch_max_decoded_bytes``.
_MAX_CONTENT_ARRAY_MEMBERS: Final = 10_000


class ExtractionFailedError(Exception):
    """The file is of a supported format and its text could not be decoded.

    ``EXTRACTION_FAILED`` at the seam (ADR-0230 §6). Carries no message from the
    underlying library and no fragment of the file: a refusal "names a **class** and
    carries no path, no name, no excerpt and no message from an underlying library",
    so nothing that crosses this boundary may carry one.
    """


class ContentTooLargeError(Exception):
    """The extracted text's quoted rendering exceeded ``fetch_max_content_bytes``.

    ``TOO_LARGE`` at the seam (ADR-0230 §6), and raised **while** extracting rather
    than after, so a file beyond the bound is refused without the whole of its text
    having been materialised.
    """


def rendered_length(text: str) -> int:
    """How many bytes ``text`` occupies once quoted for a prompt (ADR-0230 §6).

    ``json.dumps`` at its default ``ensure_ascii=True``, both delimiters included. The
    rendering is pure ASCII, so its character count and its byte count are one number
    and ``fetch_max_content_bytes``'s name stays honest.
    """
    return len(json.dumps(text))


def _rendered_body_length(text: str) -> int:
    """The rendering's length without its delimiters, so pieces can be summed.

    ``ensure_ascii=True`` escapes each code point independently, so the rendering of a
    concatenation is the concatenation of the renderings. A Python ``str`` holds code
    points rather than UTF-16 units, so splitting one never splits an astral character
    across two pieces and the sum is exact rather than approximate.
    """
    return len(json.dumps(text)) - _DELIMITERS


def extract(data: bytes, suffix: str, *, max_rendered_bytes: int, max_decoded_bytes: int) -> str:
    """The text ``data`` encodes, refused if either bound passes.

    Args:
        data: The file's bytes, already bounded by ``fetch_max_file_bytes``.
        suffix: The entry's lowercased suffix, one of :data:`SUPPORTED_SUFFIXES`.
        max_rendered_bytes: ``fetch_max_content_bytes``, on the quoted rendering.
        max_decoded_bytes: ``fetch_max_decoded_bytes``, on the decoded bytes this
            extraction **parses**, summed once per parse (ADR-0232 §2). **Plain text
            and Markdown count zero for it and never consult it**: their extraction
            has no decoding step — the extractor parses the file's own bytes, which
            ``fetch_max_file_bytes`` already bounds at the read — so there is no
            ratio between bytes read and bytes parsed for the bound to refuse (§3).

    Returns:
        The file's text, verbatim, whose :func:`rendered_length` is at most
        ``max_rendered_bytes``.

    Raises:
        ExtractionFailedError: If the bytes are not the format the suffix names, if
            the library cannot decode them, or if the walk cannot establish what the
            extraction will parse (ADR-0232 §3's one fail-closed branch).
        ContentTooLargeError: If either bound passes. Raised as soon as it does, so
            no more of the text is produced — and no more of the document parsed —
            than was needed to know.
        ValueError: If ``suffix`` is not supported. Unreachable from the fetch — the
            listing shows no other type, and ``fetch`` re-checks — and stated so that
            a future caller does not read a silent empty string as an answer.
    """
    if suffix in _TEXT_SUFFIXES:
        return _extract_text(data, max_rendered_bytes=max_rendered_bytes)
    if suffix == ".pdf":
        return _extract_pdf(
            data,
            max_rendered_bytes=max_rendered_bytes,
            max_decoded_bytes=max_decoded_bytes,
        )
    msg = f"no extraction is defined for the {suffix!r} suffix"
    raise ValueError(msg)


def _extract_text(data: bytes, *, max_rendered_bytes: int) -> str:
    """Decode UTF-8 strictly, then check the bound.

    **Strictly**, with no replacement characters and no encoding guess: §5 requires
    the file's text *verbatim*, and a decode that substituted U+FFFD for bytes it did
    not understand would put text in a record that is not what the file holds. A file
    that is not UTF-8 is a failed extraction rather than a mangled success.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = "the file's bytes are not valid UTF-8"
        raise ExtractionFailedError(msg) from exc
    if rendered_length(text) > max_rendered_bytes:
        raise ContentTooLargeError(_OVER_BOUND)
    return text


class _Budget:
    """The running total of decoded bytes this fetch's extraction will parse.

    One object for the whole fetch, so the bound is a total across pages rather than
    a per-page ceiling: "a per-page bound would admit an unbounded document made of
    bounded pages, which is the defect ``fetch_max_content_bytes`` is already summed
    to avoid" (ADR-0232 §3).

    Every charge is followed **immediately** by the comparison, which is what puts a
    refusal before the *next* decode rather than after a page's streams have been
    summed. That is §3's own correction to the repair this walk descends from: a
    page's ``/Contents`` may be an array, and summing before comparing materialises
    every stream of it at the adopted library's 75 MB per-stream ceiling.
    """

    __slots__ = ("_limit", "total")

    def __init__(self, limit: int) -> None:
        self._limit = limit
        #: What has been charged so far. Read by nothing in production; a test's
        #: window onto the running total.
        self.total = 0

    def charge(self, count: int) -> None:
        """Add ``count`` decoded bytes, and refuse the moment the total passes.

        Raises:
            ContentTooLargeError: As soon as the total is over ``max_decoded_bytes``.
        """
        self.total += count
        if self.total > self._limit:
            raise ContentTooLargeError(_OVER_BOUND)


@dataclass(slots=True)
class _Walk:
    """One page's walk: what it charges to, and what it has to remember.

    ``pypdf`` builds one traversal state per :meth:`pypdf.PageObject.extract_text`
    call and threads it through the whole descent, so its invocation count is
    aggregate over a page's forms rather than per form and starts again at the next
    page, while its cycle guard is a **path** — added on the way down and discarded on
    the way back up — so a *re-entrant* form is skipped and five hundred *sequential*
    invocations of one form are five hundred parses. Both are mirrored here, which is
    what makes the walk stop charging exactly where the extraction stops descending.

    Attributes:
        pdf: The reader every indirect object resolves against — the extraction's own,
            so the walk sees the same cached objects it will.
        budget: The running total for the whole fetch, which refuses as it passes.
        performed: How many form invocations this page's extraction has performed.
        path: The forms currently being walked, held by identity.
    """

    pdf: object
    budget: _Budget
    performed: int = 0
    path: list[PdfObject] = field(default_factory=list)


def _resource_context(obj: DictionaryObject) -> DictionaryObject | None:
    """The inherited ``/Resources`` the extraction will resolve, or ``None``.

    ``PageObject._extract_text`` reads ``get_inherited(/Resources)`` and returns the
    empty string **before it touches the content stream** where the answer is absent
    or empty, on the ground that no resources means no font and so no text. So a page
    carrying megabytes of compressed operators and no resource context parses *zero*
    bytes, and charging it would refuse a document ADR-0232 §2's stated quantity
    requires this seam to fetch (§3).

    Returns:
        The resource dictionary, or ``None`` where the extraction parses nothing from
        this object. ``None`` is **an answer** — the walk asked, and no parse
        follows — and never a failure to establish.

    Raises:
        ExtractionFailedError: Where the context is *present but structurally
            unreadable* — an entry that is not a dictionary. That is §3's one
            fail-closed branch, and the line it draws is between a question answered
            "none" and a question the walk could not ask at all: the first two fetch
            with nothing charged, and only the third refuses. A document refused here
            is one the extraction was about to spend an unknown amount on.
    """
    resources = obj.get_inherited(_RESOURCES, None)
    if is_null_or_none(resources):
        return None
    resolved = resources.get_object()
    if not isinstance(resolved, DictionaryObject):
        raise ExtractionFailedError(_UNREADABLE_CONTEXT)
    return resolved or None


def _content_of(
    obj: DictionaryObject, *, is_page: bool
) -> tuple[PdfObject | None, list[StreamObject]]:
    """What the extraction will hand to its content-stream parser, and its streams.

    ``_extract_text`` takes a page's ``/Contents`` and an XObject *itself*, resolves
    it, and hands it to ``ContentStream``, which concatenates an array's members and
    skips a member that is not a stream. Anything it cannot use at all — an absent
    key, a null, an object with no data — leaves that object's extraction returning
    the empty string, and a parse that does not happen costs nothing to charge for.

    **An array over the library's own cardinality guard is the one shape that is not
    an answer**, and it is asked about here because here is where the extraction asks:
    ``ContentStream.__init__`` compares ``len`` against
    :data:`_MAX_CONTENT_ARRAY_MEMBERS` before it resolves a member, so the extraction
    parses nothing at all for such a page. Charging the members first would refuse a
    malformed document as ``TOO_LARGE`` — a document over *both* is refused either
    way, so the divergence is one of class, but §4's own reasoning about sending an
    operator to their bounds when the answer is a corrupt file applies unchanged. The
    guard costs a ``len`` on an array already resolved and decodes nothing, which is
    what makes mirroring it affordable where mirroring the ``/ToUnicode`` parse is not
    (:func:`_establish_font`).

    Returns:
        The object to parse, and the streams the extraction will decode in the order
        it decodes them. Both empty where nothing is parsed.

    Raises:
        ExtractionFailedError: Where an array-based ``/Contents`` carries more members
            than the extraction's own parser admits.
    """
    try:
        content = obj[_CONTENTS].get_object() if is_page else obj
    except AttributeError, KeyError:
        return None, []
    if isinstance(content, ArrayObject):
        if len(content) > _MAX_CONTENT_ARRAY_MEMBERS:
            raise ExtractionFailedError(_UNPARSEABLE_CONTENT_ARRAY)
        members = [part.get_object() for part in content]
        return content, [part for part in members if isinstance(part, StreamObject)]
    if isinstance(content, StreamObject):
        return content, [content]
    return None, []


def _charged_font_program(font: PdfObject) -> StreamObject | None:
    """The embedded font program this font's extraction will decode, if any.

    ``pypdf._cmap._parse_to_unicode``'s own condition for entering
    ``_type1_alternative``, key for key: no ``/ToUnicode``, ``/Subtype`` equal to
    ``/Type1``, and a ``/FontDescriptor`` carrying a ``/FontFile``. Each is a property
    of the font dictionary the walk has already resolved, so the charge is decided
    **before anything is decoded** and is the extraction's own condition rather than a
    forecast of it (ADR-0232 §3). ``Font.from_font_resource`` resolves a
    ``/FontFile*`` with ``get_object()``, which does **not** decode, so a font with a
    normal ``/ToUnicode`` and a large ``/FontFile2`` is charged nothing — a bound
    counting those unconditionally would refuse on bytes the extraction never reads.

    **It is complete only because ``fontTools`` is absent from this environment**, so
    ``pypdf._font.py``'s conditional decode cannot execute and ``_type1_alternative``
    is the only font-program decode ``extract_text`` reaches (ADR-0232 §6).
    ``tests/readers/test_decoded_bound.py`` fails if that stops being true.

    Returns:
        The stream whose decoded length is charged, or ``None`` where the extraction
        decodes no program for this font.
    """
    if not isinstance(font, DictionaryObject):
        return None
    if "/ToUnicode" in font or font.get("/Subtype", "") != "/Type1":
        return None
    if "/FontDescriptor" not in font:
        return None
    descriptor = font["/FontDescriptor"]
    if not isinstance(descriptor, DictionaryObject):
        return None
    program = descriptor.get("/FontFile")
    if program is None or is_null_or_none(program):
        return None
    resolved = program.get_object()
    return resolved if isinstance(resolved, StreamObject) else None


def _establish_font(font: PdfObject) -> None:
    """Build this font the way the extraction does, so its failures are its own.

    ``PageObject._extract_text`` builds a stream's fonts **before** it resolves the
    content key, and it swallows only ``AttributeError`` and ``TypeError`` while doing
    so. Anything else leaves the page's extraction having parsed nothing at all — so a
    walk that went on to charge the content stream would answer ``TOO_LARGE`` for a
    document the extraction refuses as malformed, which is the class confusion ADR-0232
    §4 exists to prevent: it sends an operator to their bounds when the answer is a
    corrupt file, and §4's own reasoning about the opposite mistake applies unchanged.

    **This calls the library's own builder rather than predicting it**, which is the
    same standard §3 sets for the content-stream half — "a walk that disagreed would
    refuse documents this ADR requires it to fetch", and the instrument that makes the
    walk agree is the extraction's own. Three successive attempts to state the
    condition instead were each incomplete in one more place: the duplicate
    ``/FontFile*`` raise in ``_parse_font_descriptor``, then ``/Type3``'s conditional
    route into it, then ``/DescendantFonts`` — where a composite font reaches the same
    raise through each descendant, and an unrecognised ``/Subtype`` with no
    ``/DescendantFonts`` raises ``KeyError`` on the way. An enumeration of a
    dependency's control flow has no test that can show it complete, because
    completeness is a property of that dependency's source; asking it is exact by
    construction and gets smaller with every version.

    **It is asked only of a font carrying no ``/ToUnicode``, and that boundary is the
    bound's own rather than a convenience.** Building a font parses its ``/ToUnicode``
    CMap — ``get_data`` caches the decompression, not ``prepare_cm``'s normalisation or
    the mapping dictionary it builds — and that CMap is an input ADR-0232 §2 and §10
    leave **uncharged and unbounded by name**. Asking here would double a per-page cost
    this system does not govern: ten pages sharing a 2 MB CMap measured 0.092 s under
    the extraction alone and 0.161 s with the ask, which is unratified work added to the
    seam this bound exists to make honest. Where there is no ``/ToUnicode``, the only
    input building the font reads is the ``/Type1`` program the caller has **just
    charged**, so what doubles is a quantity the bound governs — which is exactly the
    price §3 already accepts for parsing a content stream twice. That the extraction
    re-parses the CMap per page at all is issue #2042, which fires §10's deferral and is
    not this lane's to close.

    **Two residuals follow, both stated rather than hidden, and both on a document that
    is refused either way** (issue #2043). A font *with* a ``/ToUnicode`` is not
    established here, so one that is also unbuildable lets the content stream be
    charged. And a font program is charged *before* this runs, because §3 requires the
    comparison to precede the work it bounds — "the total is compared before the
    operators it counts are parsed" — so a document whose charged programs alone cross
    the bound crosses first. Both report ``TOO_LARGE`` where the extraction alone would
    report ``EXTRACTION_FAILED``; §3's harm clause is about refusing a document "the
    stated quantity says must fetch", and no reading fetches either. Closing them means
    parsing an unbounded input, or scanning a program before charging it, which is the
    property that makes the bound a bound.

    Raises:
        ExtractionFailedError: Where the extraction's own font initialisation raises
            anything it would not itself swallow.
    """
    if not isinstance(font, DictionaryObject) or "/ToUnicode" in font:
        return
    try:
        Font.from_font_resource(font)
    except AttributeError, TypeError:
        # `_extract_text` swallows exactly these while building a font and carries on
        # to parse the content stream, so this is a parse that *does* happen.
        return
    except Exception as exc:  # a parser's own class is not this seam's vocabulary
        raise ExtractionFailedError(_UNBUILDABLE_FONT) from exc


def _charge_font_programs(resources: DictionaryObject, budget: _Budget) -> None:
    """Charge every font program this one parse will decode, one decode at a time.

    Charged **per parse** rather than per distinct program, because the adopted
    extraction rebuilds a stream's fonts on every ``_extract_text`` call while
    ``get_data`` caches only the decompression: what repeats is the scan of the
    program's clear part, once per page. "A quantity charged once when the extraction
    pays it many times is not a bound" (ADR-0232 §3) — a 0.217 MiB document of 2,000
    content-free pages sharing a 40 MB program **fetched** after 257 s when it was
    measured, with a bound on instructions alone standing at zero throughout.
    """
    fonts = resources.get("/Font")
    if fonts is None or is_null_or_none(fonts):
        return
    resolved = fonts.get_object()
    if not isinstance(resolved, DictionaryObject):
        return
    for name in list(resolved):
        try:
            font = resolved[name]
        except AttributeError, TypeError, KeyError:
            # `_extract_text` swallows exactly this while building its fonts, so a
            # font it cannot resolve is a font it decodes no program for.
            continue
        program = _charged_font_program(font)
        if program is not None:
            budget.charge(len(program.get_data()))
        _establish_font(font)


def _invoked_form(
    resources: DictionaryObject, operands: list[PdfObject]
) -> DictionaryObject | None:
    """The Form XObject a ``Do`` descends into, resolved where the extraction does.

    The operand is resolved against the **inherited** ``/Resources`` of the object
    whose stream is being walked — a page's for a page's content stream, a form's own
    for a form's — because that is where ``_extract_text__xform`` resolves it. An
    operand naming no entry there adds nothing, **and that is soundness rather than
    optimism**: a name that is not there for the walk is not there for the extraction,
    the descent does not happen, and a parse that does not happen costs nothing to
    charge for (ADR-0232 §3). An ``/Image`` is not a form and is not parsed.

    **A form carrying no stream data is still an invocation**, which is why this
    answers the object the extraction reached rather than only the ones it can parse.
    ``_extract_text__xform`` reads ``/Subtype``, returns for an ``/Image``, checks the
    cycle and the cap, and *then* increments its count — before anything asks whether
    the object has data to parse. So five thousand invocations of a bare
    ``<< /Subtype /Form >>`` exhaust the cap exactly as five thousand real ones do, and
    a walk skipping them without counting would descend into a form the extraction
    skips and refuse a document ADR-0232 §2's stated quantity requires this seam to
    fetch. What such a form costs is decided one level up and is not zero by
    assumption: the extraction builds a resource dictionary's fonts *before* it
    resolves any content, so :func:`_charge_parse` charges those programs and then
    finds nothing to parse (:func:`_content_of`).

    Returns:
        The object the extraction's descent reaches, or ``None`` where it descends
        nowhere at all.
    """
    try:
        xobjects = resources["/XObject"]
        if not isinstance(xobjects, DictionaryObject):
            return None
        form = xobjects[operands[0]]
        if not isinstance(form, DictionaryObject):
            return None
        is_image = form["/Subtype"] == NameObject("/Image")
    except Exception:
        # `_extract_text` catches exactly this around its own descent, logs it, and
        # carries on with no form parsed — including a form with no `/Subtype` at
        # all. The walk agrees with the extraction about which parses happen or it
        # is not a bound on what the extraction parses.
        return None
    return None if is_image else form


def _charge_parse(obj: DictionaryObject, walk: _Walk, *, is_page: bool) -> None:
    """Charge one parse and everything reached from it, refusing as the bound passes.

    ADR-0232 §3's named construction, which is required to have the property rather
    than to be this shape: resolve the inherited resources and **stop there, charging
    nothing, where the extraction would**; otherwise add each charged font program's
    length and compare, add each decoded stream's length and compare, then parse the
    stream **with the adopted library's own content-stream parser**, take the ``Do``
    operations it reports, resolve each against those same resources, and recurse.

    **Fonts are charged and built before the content stream because that is the order
    the extraction works in**, and the order decides a *class* rather than a number: a
    page whose font initialisation raises is a page whose content stream the extraction
    parses not at all, so charging that stream would answer ``TOO_LARGE`` where the
    document is malformed (:func:`_establish_font`).

    **The library's own parser rather than a second grammar**, which costs an admitted
    document a second parse and is the price of agreement. A stream can carry the
    literal text ``(Do)`` with no form anywhere, and a walk scanning bytes would charge
    a descent that never happens; a walk resolving operands somewhere other than where
    the extraction resolves them gets the inherited case wrong in the other direction.
    The doubling is bounded by the bound, which is what makes it affordable.

    Args:
        obj: The page or form whose parse is being charged.
        walk: This page's reader, running total, invocation count and path.
        is_page: Whether ``obj``'s stream is named by ``/Contents`` (a page) or is
            ``obj`` itself (a form).

    Raises:
        ContentTooLargeError: The moment the running total passes the bound.
        ExtractionFailedError: Where a resource context is present and unreadable,
            where a font the extraction cannot build precedes the content charge, or
            where an array-based ``/Contents`` is over the parser's own cardinality
            guard — each a page whose extraction parses nothing at all.
    """
    resources = _resource_context(obj)
    if resources is None:
        return
    # Fonts first, because that is the order `_extract_text` works in: it builds a
    # stream's fonts before it resolves the content key, and a failure there leaves
    # the page's extraction having parsed nothing. Within the pair the order is not
    # ADR-0232 §3's to fix — "the property is required and no construction is" — and
    # what it does fix, that each decode is followed by its own comparison, holds
    # either way round.
    _charge_font_programs(resources, walk.budget)
    content, streams = _content_of(obj, is_page=is_page)
    for stream in streams:
        walk.budget.charge(len(stream.get_data()))
    if content is None:
        return
    for operands, operator in ContentStream(content, walk.pdf, "bytes").operations:
        if operator != b"Do":
            continue
        form = _invoked_form(resources, operands)
        if form is None or any(walked is form for walked in walk.path):
            continue
        if walk.performed >= _MAX_XFORM_INVOCATIONS:
            # The extraction returns the empty string and **skips** the form past
            # this point rather than raising, so these are parses that never happen.
            continue
        # Counted here, before anything asks what this form holds, because that is
        # where `_extract_text__xform` counts it: a form with no stream data is an
        # invocation the extraction spends and this walk must spend too
        # (`_invoked_form`).
        walk.performed += 1
        walk.path.append(form)
        try:
            _charge_parse(form, walk, is_page=False)
        finally:
            walk.path.pop()


def _charge_page(page: pypdf.PageObject, budget: _Budget) -> None:
    """Charge everything this page's extraction will parse, before it is entered.

    Whether the whole of a page's count is established before ``extract_text`` is
    entered is not a choice this seam has: the extraction follows a ``Do`` into a form
    and parses it inside the same call, so there is no seam between that form's decode
    and its parse to sit in. The count is therefore established for the page and every
    parse reached from it before the page's extraction begins — which is the same
    shape as the page loop one level up, and is why this is a bound on an *input*
    rather than an observation of work in progress (ADR-0232 §5).
    """
    _charge_parse(page, _Walk(pdf=page.pdf, budget=budget), is_page=True)


def _extract_pdf(data: bytes, *, max_rendered_bytes: int, max_decoded_bytes: int) -> str:
    """Extract a PDF's text a page at a time, refusing as soon as a bound passes.

    Page-at-a-time is what makes §6's "enforces the bound **while** extracting rather
    than after" true of the text: the running total is checked after each page, so a
    document beyond the bound is refused with the pages past that point never
    extracted.

    **Iterated rather than materialised.** ``list(reader.pages)`` builds every page
    object before the loop applies any bound, so a document beyond the bound would
    already have cost what building that collection costs. Iterating extracts one
    page's text at a time and stops on the first page that carries the total past the
    bound.

    **The page tree's own traversal is bounded by the library, and that is checked
    rather than assumed.** ``pypdf`` resolves a document's page count before it will
    yield a page, whichever way the collection is approached — so the question is what
    stops a document inside ``fetch_max_file_bytes`` that declares a page tree far
    larger than its own bytes, by naming one shared node many times. The answer is
    three guards in ``pypdf._doc_common._flatten``, all present in the version this
    project pins: ``PAGE_TREE_MAX_ENTRIES`` (100,000) counted across the **whole**
    traversal, ``PAGE_TREE_MAX_DEPTH`` (100), and a visited set refusing a cycle. Each
    raises, and each raise lands in this function's own ``except`` as
    ``EXTRACTION_FAILED``.

    ``tests/readers/test_local_file_fetcher.py`` builds the amplified document —
    roughly 1.4 KB claiming 64,000,000 pages — and asserts it is refused, so this is a
    property of the pinned dependency that a future version dropping a guard would fail
    on rather than a claim this docstring makes on its own.

    **What the parse costs is bounded before the parse, and by a figure of its own**
    (ADR-0232, closing issue #2022). A page's content stream arrives Flate compressed,
    and a run of one repeated operator compresses about 340:1. So a **47 KB** document,
    well inside the 4 MiB default, holds 16 MB of operators, and parsing them into
    ``pypdf``'s own objects cost **313 s** and **737 MB** of resident memory when it was
    measured — superlinearly: 1 MB of operators took 6 s and 4 MB took 29 s. Neither of
    ADR-0230 §6's figures reaches it. The file bound is satisfied by the *compressed*
    bytes, and ``fetch_max_content_bytes`` is counted on extracted *text*, which exists
    only once the whole stream has been parsed.

    So :func:`_charge_page` establishes what a page's extraction will parse **before**
    ``extract_text`` is entered for it, against ``fetch_max_decoded_bytes`` — a running
    total over the whole fetch, compared after each decoded stream and before the next
    is decoded, and refused as ``TOO_LARGE``. The same 47 KB document is refused in a
    hundredth of a second.

    **What is counted, established against ``pypdf`` 6.16.2 rather than recalled**
    (ADR-0232 §6 requires this record at the code, and requires a later lane to
    re-establish it against whatever ``uv.lock`` then fixes):

    * **Every content stream the extraction parses, once per parse.** A page's own,
      and every Form XObject reached from it, once for each ``Do`` that invokes it.
      ``PageObject._extract_text__xform`` follows each ``Do`` into the named form and
      parses it as a content stream of its own, so a **12,453 B** document whose
      ``/Contents`` decodes to **ten bytes** cost **33.9 s**; and the descent is per
      *invocation*, its cycle guard refusing only a **re-entrant** form, so a
      **1,173 B** file invoking one 100 KB form five hundred times has 105 KB of
      *distinct* decoded bytes and cost **126.6 s**.
    * **The embedded font program of each font the extraction re-parses per page** —
      ``_cmap._parse_to_unicode``'s own three keys, in :func:`_charged_font_program`.
      The extraction rebuilds a stream's fonts on every ``_extract_text`` call and
      ``get_data`` caches only the decompression, so the scan of the program's clear
      part repeats once per page: a **0.217 MiB** document of 2,000 content-free pages
      sharing a 40 MB program **fetched** after **257 s** with nothing refusing it.

    **What is decoded and is *not* charged, which is a boundary rather than a gap**
    (ADR-0232 §2, §3, and deferred by name in §10). A compressed **object stream**
    (``/ObjStm``) is decoded whole by ``PdfReader._get_object_from_stream`` during
    ordinary indirect-object resolution — before any per-page loop, so before any
    total exists — and a font's **``/ToUnicode`` CMap** is decoded once. Each is read
    **once and cached**, so no per-parse multiplier acts on either, and that absence is
    the whole of the ground: not their cost per byte, and not any limit the library
    happens to carry. Neither is bounded by anything this system owns, and
    ``fetch_max_file_bytes`` does not bound them — it bounds the bytes **read from
    disk**, and a small ``/ObjStm`` can expand to tens of MiB.

    **The residual this leaves is stated rather than hidden.** Obtaining a stream's
    decoded length requires decoding it, and the adopted library's interface decodes
    whole streams, so one stream's decoded bytes are materialised before the comparison
    that refuses them. What bounds *that* is ``pypdf``'s own ceiling and not this
    system: 6.16.2 caps a Flate decode at ``ZLIB_MAX_OUTPUT_LENGTH`` (75,000,000 bytes)
    and raises past it, with the same ceiling on ``LZW``, ``RunLength``, ``JBIG2`` and
    the array-based path, and each raise lands in this function's ``except`` as
    ``EXTRACTION_FAILED``. That is **evidence about a resolved version and never a
    bound this system relies on** (ADR-0232 §6); ``pypdf`` is adopted ranged, so
    nothing this project declares carries it.

    **Measuring the length costs the extraction nothing**, which is why the comparison
    can sit before the parse rather than being a second decode: ``pypdf`` caches a
    stream's decoded bytes on the object, so the ``extract_text()`` that follows reads
    the same bytes. That is a property of the adopted version, and it is why the check
    is cheap — never why it is correct.

    **The visitor route was tried first and does not work**, which is worth recording so
    it is not tried again: ``extract_text(visitor_text=…)`` reports a fragment per
    *text-block flush* — ``BT``/``ET``/``cm``/``Tf`` — not per operator, so a single
    ``BT … ET`` block holding 90,909 ``Tj`` operators calls it exactly twice, and both
    calls come after the parse the cost is in. Measured with the guard in place, the
    47 KB document's numbers did not move. **And no deadline replaces it** (ADR-0232
    §5): the 313 s is spent inside one uninterruptible call on a *single-page*
    document, so a clock could only be read where the byte total already is, and it
    would make the outcome a function of machine load where ADR-0230 §6 requires the
    extraction to be deterministic for a given file.
    """
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        pages = reader.pages
    except Exception as exc:  # a parser's own class is not this seam's vocabulary
        raise ExtractionFailedError(_UNDECODABLE) from exc
    produced: list[str] = []
    # The delimiters are paid once, up front, so the running comparison is against
    # the same number `rendered_length` would report for the whole.
    total = _DELIMITERS
    # One budget for the whole document: the decoded bound is a running total across
    # pages, never a per-page ceiling (ADR-0232 §3).
    budget = _Budget(max_decoded_bytes)
    index = 0
    while True:
        try:
            page = pages[index]
        except IndexError:
            return "".join(produced)
        except Exception as exc:  # as above; every failure of extraction is one class
            raise ExtractionFailedError(_UNDECODABLE) from exc
        try:
            _charge_page(page, budget)
        except ContentTooLargeError, ExtractionFailedError:
            # Both are already this seam's vocabulary: the first is the bound
            # refusing, the second is §3's fail-closed branch. Neither is a library
            # class to translate, and neither may be swallowed by the clause below.
            raise
        except Exception as exc:  # as above
            raise ExtractionFailedError(_UNDECODABLE) from exc
        try:
            page_text = page.extract_text()
        except Exception as exc:  # as above
            raise ExtractionFailedError(_UNDECODABLE) from exc
        # `pypdf` joins nothing between pages, so a separator is ours to choose. A
        # newline is the minimum that keeps the last line of one page and the first
        # of the next from running into one word.
        piece = page_text if index == 0 else "\n" + page_text
        total += _rendered_body_length(piece)
        if total > max_rendered_bytes:
            raise ContentTooLargeError(_OVER_BOUND)
        produced.append(piece)
        index += 1


#: Payload-free messages. Each names the class and nothing about the file: ADR-0230 §6
#: is explicit that a refusal carries "no path, no name, no excerpt and no message from
#: an underlying library", and these strings are the only text that reaches a traceback
#: an operator might see.
_UNDECODABLE: Final = "the file could not be decoded as the format its suffix names"
_OVER_BOUND: Final = "the extraction is over a configured bound"
_UNREADABLE_CONTEXT: Final = "a resource context is present and cannot be read"
_UNBUILDABLE_FONT: Final = "a font in the resource context could not be built"
_UNPARSEABLE_CONTENT_ARRAY: Final = "a content array carries more members than can be parsed"
