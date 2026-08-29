"""What a press does to the answer that is still being spoken (#1707, ADR-0216 §2).

**This module is the case #1707 was raised on**, and it is worth restating why a
reading of ``app.js`` cannot answer it. That issue's own words:

    a substring assertion that ``stopPlaying()`` precedes ``playing = mine`` pins
    the *shape* of a fix and cannot distinguish a working state machine from a
    broken one that spells itself the same way

Two lines in the right order are a fact about a file. Whether a press arriving
*during* a decode leaves a source to start afterwards is a fact about time, and
ADR-0216 §2 puts exactly that class here: "behaviour a reading of the file cannot
decide: ordering in time, concurrency, and what one handler does to a resource
another holds".

**Every wait below is on a condition the page exposes** — a source counted, a
decode settled, a panel shown — and never on a clock (ADR-0216 §7). The one
duration in the layer is how long the button is held, which is a property of the
recording rather than a synchronisation device.

**Nothing here fakes Web Audio.** The renderings are real WebM/Opus containers,
Chromium's own decoder decodes them, and its own scheduler starts and stops the
sources this module counts. The probe wraps ``decodeAudioData`` only to make one
real decode resolve late, which is the instrument #1707 asked for: "a fake
``AudioContext`` whose decode promise resolves after ``interruptPlayback()`` would
reveal whether no source starts".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from browser_drive import driving, rendering_of

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import Browser

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.usefixtures("hermetic_assistant_env"),
]

#: The first answer's rendering: long enough that it is still sounding when the
#: next press lands, whatever the machine is doing. Read back off the decoded
#: buffer, so a case can name *which* rendering a source was playing rather than
#: only that one was.
_FIRST = 8.0

#: The second answer's, deliberately a different length from the first.
_SECOND = 2.0

#: What the page writes under an answer whose playback a press ended (#1696).
#: Quoted rather than imported: it is the page's sentence, and a test that built it
#: from the same source the page does would agree with the page by construction.
_INTERRUPTED = "You pressed to talk, so this answer stopped being spoken."


async def test_a_press_over_a_live_playback_stops_it_and_says_so(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The interrupt reaches a source that is sounding, and the page accounts for it.

    #1696's ruling, from a real iPhone: "Pressing to talk over an answer that is
    still being spoken is the same act as speaking over a person: it ends what was
    being said." A source really started and was really stopped, and the sentence
    the owner reads afterwards is the page's own account of it.
    """
    async with driving(gateway_browser, tmp_path, renderings=(rendering_of(_FIRST),)) as drive:
        await drive.press()
        await drive.page.wait_for_function("() => window.__drive.starts.length === 1")
        sounding = await drive.starts()
        assert sounding[0]["duration"] == pytest.approx(_FIRST, abs=0.1)
        assert (await drive.probe())["stops"] == 0

        await drive.hold()
        await drive.page.wait_for_function("() => window.__drive.stops === 1")
        assert _INTERRUPTED in await drive.answer()
        await drive.release()


async def test_a_press_during_a_held_decode_leaves_no_source_to_start_afterwards(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """#1707's own example, and the one a substring assertion cannot reach.

    The first answer's decode is held open, so the press lands while the page holds
    a rendering that has not become a source yet. ``interruptPlayback`` clears the
    record before it stops anything, and ``playSpoken`` compares identity after the
    decode returns — so the overtaken rendering must start nothing when it finally
    resolves.

    Both decodes are driven to completion before the assertion, so this is not a
    race the case happens to win: the reading is taken after the browser has had
    the buffer in hand and declined to play it.
    """
    async with driving(
        gateway_browser,
        tmp_path,
        renderings=(rendering_of(_FIRST), rendering_of(_SECOND)),
    ) as drive:
        await drive.page.evaluate("window.__holdNextDecode()")
        await drive.press()
        await drive.page.wait_for_function("() => window.__drive.decodes === 1")
        assert await drive.starts() == []

        # The second press interrupts a rendering that is decoding rather than
        # sounding, and goes on to ask its own question — so the second answer is
        # what the page should be speaking when the first decode finally lands.
        await drive.press()
        await drive.page.wait_for_function("() => window.__drive.starts.length === 1")
        await drive.page.evaluate("window.__releaseHeldDecode()")
        await drive.page.wait_for_function("() => window.__drive.settled === 2")

        sounding = await drive.starts()
        assert len(sounding) == 1
        assert sounding[0]["duration"] == pytest.approx(_SECOND, abs=0.1)
        assert (await drive.probe())["stops"] == 0
