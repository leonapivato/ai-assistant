"""The approvals panel as the page reads it: JSON views of ADR-0361 §8:4's answers.

**An enumeration, for ADR-0168 §6's reason**: what may appear on the page is decided
here rather than by whatever a future ``ApprovalPanelEntry`` carries. Each view names
the members the approvals panel renders, and nothing else crosses.

**Nothing here computes a value.** A request's text is its card's, rendered by the
engine through the one renderer every surface shows a request by (§2:11), and where it
stands is the engine's reading at the instant it read it, so the page, the card and the
command line cannot show one request two ways. The id that crosses is the one the
panel's tap names (§4:9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.types import ApprovalPanel, ApprovalPanelEntry, ApprovalPanelTap


def _instant(at: datetime | None) -> str | None:
    return None if at is None else at.isoformat()


def entry_view(entry: ApprovalPanelEntry) -> dict[str, Any]:
    """One request as the panel shows it: its card's text, its state and its times."""
    return {
        "request_id": entry.request_id,
        "text": entry.text,
        "state": entry.state.value,
        "written_at": entry.written_at.isoformat(),
        "expires_at": entry.expires_at.isoformat(),
        "answered_by": None if entry.answered_by is None else entry.answered_by.value,
        "answered_at": _instant(entry.answered_at),
    }


def panel_view(panel: ApprovalPanel) -> dict[str, Any]:
    """The pending requests, oldest first, and the most recently ended (§4:6)."""
    return {
        "pending": [entry_view(one) for one in panel.pending],
        "recent": [entry_view(one) for one in panel.recent],
    }


def tap_view(tapped: ApprovalPanelTap) -> dict[str, Any]:
    """What the panel's tap came to, and the request as the panel now shows it (§4:9)."""
    return {
        "answer": tapped.answer.value,
        "entry": None if tapped.entry is None else entry_view(tapped.entry),
    }
