"""The speech bound, and the classification a seam's failure is logged by.

A spoken turn ran two seam stages here under its caller's budget until ADR-0313
§3:1 retired ``converse_spoken``; what stays is what a notification's rendering
reads (ADR-0206), and the speech seams themselves stay for voice's own design
(§3:7).

**The classification is an identity-matched MRO walk over a mapping frozen at
import** (ADR-0200 §4), never the exception's ``__name__``, its module or its
message. This is ``models/routing.py``'s ``_classify`` applied one boundary
further out and for its reason: a speech implementation is a stranger, and the
class it raises can be named anything at all — including the name of a class this
build declares. Identity is what makes a look-alike unable to buy a
classification.

**Nothing here writes a message it did not author** (ADR-0200 §8). A seam's
exception carries arbitrary text and an implementation that interpolated the clip
it could not decode has put the recording inside it; so what is logged is the
project's own classification and never the seam's words.
"""

from __future__ import annotations

from typing import Final

from ai_assistant.core.errors import SpeechError, SpeechTimeoutError
from ai_assistant.core.types import SpeechFailure

__all__ = [
    "DEFAULT_MAX_SPOKEN_AUDIO_BYTES",
    "classify_speech_failure",
]

#: ADR-0200 §6's bound on a spoken recording **and** a spoken rendering, in bytes
#: of decoded audio, at the figure that ADR names — 512 KiB. An engine takes it as
#: a constructor argument so a deployment (and a test) can set it; this is what it
#: gets by saying nothing, and it is
#: ``Settings.hub_max_spoken_audio_bytes``'s own default.
#:
#: Spelled here rather than imported from ``core.config`` for
#: ``DEFAULT_MAX_PAYLOAD_BYTES``'s reason one module over: a figure the engine and
#: the canonical fake carry cannot be a settings read, since neither has a
#: ``Settings``. ``tests/orchestration/test_spoken_bounds.py`` pins the two
#: together, so the duplication cannot drift.
DEFAULT_MAX_SPOKEN_AUDIO_BYTES: Final[int] = 512 * 1024

#: One entry per class of the :class:`~ai_assistant.core.errors.SpeechError`
#: taxonomy ADR-0200 §1 fixes, **nearest first**, frozen at import.
#:
#: The order is the walk's: :func:`classify_speech_failure` takes the first entry
#: whose class *is* — by identity — a class in the caught exception's MRO, so a
#: ``SpeechTimeoutError`` matches its own row before it reaches the base's. A lane
#: that adds a third ``SpeechError`` subclass adds its row here **and** its
#: ``SpeechFailure`` member in the same change, which is the bijection ADR-0200 §4
#: states and ``tests/core/test_speech_errors.py`` enforces.
_CLASSIFICATIONS: Final[tuple[tuple[type[SpeechError], SpeechFailure], ...]] = (
    (SpeechTimeoutError, SpeechFailure.TIMED_OUT),
    (SpeechError, SpeechFailure.UNCLASSIFIED),
)


def classify_speech_failure(exc: BaseException) -> SpeechFailure:
    """Name a caught seam failure in this project's own vocabulary (ADR-0200 §4).

    Walks the exception's MRO and takes the nearest class :data:`_CLASSIFICATIONS`
    names, **matched by object identity**. A class an implementation happened to
    call ``SpeechTimeoutError``, or one that subclasses nothing this build
    declares, reaches the fallback: the value is what *this* build's taxonomy says,
    never what the raiser's naming implies.

    Args:
        exc: The exception the seam raised.

    Returns:
        The member naming it, or
        :attr:`~ai_assistant.core.types.SpeechFailure.UNCLASSIFIED` where the
        taxonomy does not reach it.
    """
    for kind in type(exc).__mro__:
        for known, member in _CLASSIFICATIONS:
            if kind is known:
                return member
    return SpeechFailure.UNCLASSIFIED
