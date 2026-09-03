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
"""

from __future__ import annotations

import io
import json
import logging
from typing import Final

import pypdf

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


def extract(data: bytes, suffix: str, *, max_rendered_bytes: int) -> str:
    """The text ``data`` encodes, refused if its rendering passes the bound.

    Args:
        data: The file's bytes, already bounded by ``fetch_max_file_bytes``.
        suffix: The entry's lowercased suffix, one of :data:`SUPPORTED_SUFFIXES`.
        max_rendered_bytes: ``fetch_max_content_bytes``.

    Returns:
        The file's text, verbatim, whose :func:`rendered_length` is at most
        ``max_rendered_bytes``.

    Raises:
        ExtractionFailedError: If the bytes are not the format the suffix names, or
            the library cannot decode them.
        ContentTooLargeError: If the rendering passes the bound. Raised as soon as it
            does, so no more of the text is produced than was needed to know.
        ValueError: If ``suffix`` is not supported. Unreachable from the fetch — the
            listing shows no other type, and ``fetch`` re-checks — and stated so that
            a future caller does not read a silent empty string as an answer.
    """
    if suffix in _TEXT_SUFFIXES:
        return _extract_text(data, max_rendered_bytes=max_rendered_bytes)
    if suffix == ".pdf":
        return _extract_pdf(data, max_rendered_bytes=max_rendered_bytes)
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


def _extract_pdf(data: bytes, *, max_rendered_bytes: int) -> str:
    """Extract a PDF's text a page at a time, refusing as soon as the bound passes.

    Page-at-a-time is what makes §6's "enforces the bound **while** extracting rather
    than after" true: the running total is checked after each page, so a document
    beyond the bound is refused with the pages past that point never produced.
    """
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        pages = list(reader.pages)
    except Exception as exc:  # a parser's own class is not this seam's vocabulary
        raise ExtractionFailedError(_UNDECODABLE) from exc
    produced: list[str] = []
    # The delimiters are paid once, up front, so the running comparison is against
    # the same number `rendered_length` would report for the whole.
    total = _DELIMITERS
    for index, page in enumerate(pages):
        try:
            page_text = page.extract_text()
        except Exception as exc:  # as above; every failure of extraction is one class
            raise ExtractionFailedError(_UNDECODABLE) from exc
        # `pypdf` joins nothing between pages, so a separator is ours to choose. A
        # newline is the minimum that keeps the last line of one page and the first
        # of the next from running into one word.
        piece = page_text if index == 0 else "\n" + page_text
        total += _rendered_body_length(piece)
        if total > max_rendered_bytes:
            raise ContentTooLargeError(_OVER_BOUND)
        produced.append(piece)
    return "".join(produced)


#: Payload-free messages. Each names the class and nothing about the file: ADR-0230 §6
#: is explicit that a refusal carries "no path, no name, no excerpt and no message from
#: an underlying library", and these strings are the only text that reaches a traceback
#: an operator might see.
_UNDECODABLE: Final = "the file could not be decoded as the format its suffix names"
_OVER_BOUND: Final = "the extracted text's rendering is over the configured bound"
