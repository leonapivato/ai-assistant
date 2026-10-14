"""A programming defect told apart from an expected ending, and logged without its words (#2904).

An activation that cannot finish is answered the same whatever ended it, so a
``ValueError`` from a bug would read as a model's failure does. :func:`is_defect` is the
rule that tells them apart, and :func:`log_defect` the line a defect is logged under: by
its class and the frames it passed through, never its message (ADR-0314 §3:2).

Both live here, beneath the controller and the phase path alike, so the controller can
log the defect a stop would otherwise swallow (#2927) without importing the phase path,
which imports it.
"""

from __future__ import annotations

import traceback

import structlog

from ai_assistant.core.errors import AssistantError

__all__ = ["ToleratedStageError", "is_defect", "log_defect"]

_log = structlog.get_logger(__name__)


class ToleratedStageError(Exception):
    """A failure a failure-tolerant stage caught and carries on its tolerated result.

    Expected, never a defect (ADR-0281 §5): the stage recorded its decision in place of
    what failed, and the pass goes on while its deadline holds. Recall's digest failing
    is one (ADR-0308 §4:12-§4:13).
    """


def is_defect(failure: BaseException) -> bool:
    """Whether ``failure`` is a programming defect rather than an expected ending (#2904).

    An expected failure is one of the project's own errors — a model's, a store's, a
    refusal, a stop, each an :class:`~ai_assistant.core.errors.AssistantError` — or a
    timeout, or a failure a tolerant stage carries, such as recall's digest failing.
    Every other ``Exception``, such as the ``ValueError`` or ``KeyError`` a bug raises,
    is a defect. A cancellation is neither, and a group is a defect where any exception
    it holds is one.
    """
    if isinstance(failure, BaseExceptionGroup):
        return any(is_defect(one) for one in failure.exceptions)
    return isinstance(failure, Exception) and not isinstance(
        failure, AssistantError | TimeoutError | ToleratedStageError
    )


def log_defect(
    event: str, failure: BaseException, *, stage: str, activation_id: str | None
) -> None:
    """Log a defect at error level: where it was raised and its class, never its words.

    The line is the one the failure is always logged under, ``event``, raised to error
    level so a defect is told apart from an expected failure (#2904). It names the
    stage, the activation and the exception's class, and carries its traceback as the
    frames it passed through. Not its message, nor any chained exception's: a message
    can carry what the user or a model said, which no log holds (ADR-0314 §3:2). Nor
    through ``exc_info``: ``core/logging`` renders a traceback with the raising frames'
    locals, which hold the activation's own content.

    Args:
        event: The line's event name.
        failure: The defect.
        stage: The stage or the step it was raised in.
        activation_id: The activation it ended, where one was admitted.
    """
    _log.error(
        event,
        stage=stage,
        activation_id=activation_id,
        error=_named(failure),
        traceback="".join(_frames(failure)),
    )


def _named(failure: BaseException) -> str:
    """``failure``'s class, and a group's, with the classes it holds: never a message."""
    if isinstance(failure, BaseExceptionGroup):
        held = ", ".join(_named(one) for one in failure.exceptions)
        return f"{type(failure).__name__}({held})"
    return type(failure).__name__


def _frames(failure: BaseException) -> list[str]:
    """``failure``'s traceback as its frames and class, a group's with each it holds.

    Each frame is its file, line, function and source line; no message and no local
    is read. An exception a group holds is listed under it, indented, so a defect in a
    task group's child keeps its own class and the frames it was raised in.
    """
    lines = [
        *traceback.format_list(traceback.extract_tb(failure.__traceback__)),
        f"{type(failure).__qualname__}\n",
    ]
    if isinstance(failure, BaseExceptionGroup):
        for number, one in enumerate(failure.exceptions, start=1):
            lines.append(f"+ {number}/{len(failure.exceptions)}\n")
            lines.extend(f"| {line}" for line in "".join(_frames(one)).splitlines(keepends=True))
    return lines
