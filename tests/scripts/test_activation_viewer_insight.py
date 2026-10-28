"""The activation viewer's insight into how an activation was processed (ADR-0316 §3:3).

What code did with understanding's labels, computed from the labels the message showed
by ADR-0353 §9's rules, since the record keeps no resolution; the labels the message showed
that the reply names in no list; why a run was repaired; what each of recall's cues found;
each model call's time, tokens and estimated cost; and a thinking summary on any returned
entry that keeps one. The repaired activation is written by understanding's own stage
(``_insight_record``); the rules' every branch is held over a tagged message written here.
"""

from __future__ import annotations

import http.client
import json
import sys
from pathlib import Path
from typing import Any, Final

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _activation_record import iso, serving, viewer, write_record
from _insight_record import (
    FIRST_REPLY,
    GAP,
    INSIGHT,
    MEANING,
    MODEL,
    THINKING,
    write_insight,
)
from _tagged_record import KEPT_FACTS, PINNED

pytestmark = pytest.mark.integration


def _walk(record: Path, activation_id: str) -> dict[str, Any]:
    own = viewer.Record(record.parent).lines(activation_id)
    assert own is not None
    walked: dict[str, Any] = viewer.walk(own[0])
    return walked


def _step(walked: dict[str, Any], title: str) -> dict[str, Any]:
    (found,) = [one for one in walked["steps"] if one["title"] == title]
    return dict(found)


@pytest.fixture
def record(tmp_path: Path) -> Path:
    return write_insight(write_record(tmp_path))


# --- an estimate of what a call cost ----------------------------------------------------


def test_sonnet_5_5_s_rates_are_dated_beside_its_id() -> None:
    rates = viewer.MODEL_RATES["claude-sonnet-5-5"]
    assert (rates.input, rates.output, rates.cache_read, rates.cache_write) == (2, 10, 0.2, 2.5)
    assert rates.as_of == "2026-10-28"


def test_a_cost_prices_each_kind_of_input_at_its_own_rate() -> None:
    """Input counts its cache reads and writes, so only the rest is priced as input."""
    usage = {"input": 12_345, "output": 456, "cache read": 10_000, "cache write": 1_000}
    cost = viewer.estimated_cost("anthropic:claude-sonnet-5-5", usage)
    assert cost is not None
    assert cost["usd"] == pytest.approx((1_345 * 2 + 10_000 * 0.2 + 1_000 * 2.5 + 456 * 10) / 1e6)
    assert (cost["model"], cost["as_of"]) == ("claude-sonnet-5-5", "2026-10-28")


@pytest.mark.parametrize(
    ("model", "usage", "priced"),
    [
        ("claude-sonnet-5-5-20261001", {"input": 10}, True),
        ("claude-sonnet-5-5", {"output": 1}, True),
        ("anthropic:claude-haiku-4-5", {"input": 10}, False),
        ("fake:structured", {"input": 10}, False),
        (None, {"input": 10}, False),
        ("claude-sonnet-5-5", None, False),
    ],
)
def test_a_model_with_no_rates_kept_shows_its_tokens_alone(
    model: str | None, usage: dict[str, int] | None, *, priced: bool
) -> None:
    assert (viewer.estimated_cost(model, usage) is not None) is priced


# --- understanding: its repair, what code did with its labels, what it did not cite ------


def test_a_repaired_run_says_why_from_the_repair_s_own_request(record: Path) -> None:
    step = _step(_walk(record, INSIGHT), "Understanding")
    assert step["calls"] == 2
    repair = step["repair"]
    assert repair["labels"] == ["M9 in cites"]
    assert repair["first_failure"] is None
    assert json.loads(repair["first_reply"]) == json.loads(FIRST_REPLY)
    # The statement is the code's own, read from the record, never computed.
    assert '"M9"' in repair["statement"]
    assert "cites" in repair["statement"]


def test_the_labels_are_read_from_the_run_s_first_request(record: Path) -> None:
    """A repair's request ends with the statement, so its last user message is no message."""
    step = _step(_walk(record, INSIGHT), "Understanding")
    assert step["labels"] == {"M2": KEPT_FACTS[0], "M1": PINNED}


def test_what_code_did_with_each_label_is_computed_by_adr_0353_s_rules(record: Path) -> None:
    resolution = _step(_walk(record, INSIGHT), "Understanding")["resolution"]
    shown = {
        key: [(one["label"], one["outcome"]) for one in rows] for key, rows in resolution.items()
    }
    assert shown == {
        "cites": [("M2", "kept"), ("R4", "dropped"), ("M2", "again")],
        "belongs_to": [("M1", "dropped")],
        "meant_for": [("R1", "dropped")],
    }
    cited = resolution["cites"][0]
    assert (cited["text"], cited["where"]) == (KEPT_FACTS[0], "Recalled memories")
    assert "§9:11" in resolution["cites"][1]["why"]
    assert "remembered fact" in resolution["belongs_to"][0]["why"]
    assert resolution["belongs_to"][0]["where"] == "Always in mind"


def test_the_labels_shown_and_named_in_no_list_are_listed(record: Path) -> None:
    step = _step(_walk(record, INSIGHT), "Understanding")
    assert [(one["label"], one["text"]) for one in step["not_cited"]] == [("M3", KEPT_FACTS[1])]


_TAGGED: Final = """# The stimulus
A stimulus reached the system: one message Maren typed.
<said from="Maren">book it</said>
# Knowledge
## The situation
It is Monday.
## Stimulus origin knowledge
<message label="H1" from="Maren">the earlier message</message>
## Concurrent stimuli
<stimulus label="R1" origin="the hub chat" acted="no">
<said from="Maren">book a table</said>
</stimulus>
# Memory
## Always in mind
<memory label="M1" from="the system">Maren has a sister, Ana.</memory>
## Short-term memory
<stimulus label="P1" origin="the hub chat">
<said from="Maren">find flights</said>
</stimulus>
## Long-term memory
### Recalled memories
### Matters
<matter label="S1" about="a trip">
<summary from="the system">Trip to Lisbon</summary>
</matter>
## Stimulus origin memory
"""


def _resolved(reply: dict[str, Any], *, repaired: bool = False) -> dict[str, list[Any]]:
    body = {"messages": [{"role": "user", "content": _TAGGED}]}
    reading = viewer.reading_of(json.dumps({"understanding": "u", **reply}))
    assert reading is not None
    resolved = viewer.resolution_of(reading, viewer.shown_labels(body), repaired=repaired)
    return {key: [one["outcome"] for one in rows] for key, rows in resolved.items()}


def test_every_label_the_tagged_message_shows_is_read_with_its_section_and_tag() -> None:
    body = {"messages": [{"role": "user", "content": _TAGGED}]}
    assert [(one["label"], one["where"], one["tag"]) for one in viewer.shown_labels(body)] == [
        ("H1", "Stimulus origin knowledge", "message"),
        ("R1", "Concurrent stimuli", "stimulus"),
        ("M1", "Always in mind", "memory"),
        ("P1", "Short-term memory", "stimulus"),
        ("S1", "Matters", "matter"),
    ]


def test_belongs_to_links_a_matter_a_stimulus_and_running_work_and_drops_a_fact() -> None:
    """§9:12, §10:3: a place-window item links only where it does, which is not said."""
    assert _resolved({"belongs_to": ["S1", "P1", "R1", "M1", "H1", "R2"]})["belongs_to"] == [
        "kept",
        "kept",
        "kept",
        "dropped",
        "unknown",
        "dropped",
    ]


def test_meant_for_continues_only_a_shown_concurrent_stimulus() -> None:
    """§9:11, §10:4: any other label in it is dropped, with no repair."""
    assert _resolved({"meant_for": ["R1", "R2", "S1"]})["meant_for"] == [
        "kept",
        "dropped",
        "dropped",
    ]


@pytest.mark.parametrize(("repaired", "outcome"), [(False, "repair"), (True, "dropped")])
def test_a_label_naming_nothing_earns_the_repair_and_is_dropped_after_it(
    *, repaired: bool, outcome: str
) -> None:
    """§9:10: an R label naming nothing earns no repair (§9:11), any other does."""
    resolved = _resolved({"cites": ["H1", "X9", "R9"], "belongs_to": ["X9"]}, repaired=repaired)
    assert resolved["cites"] == ["kept", outcome, "dropped"]
    assert resolved["belongs_to"] == [outcome]


def test_a_reply_in_the_earlier_shape_has_no_resolution_but_its_uncited_labels() -> None:
    lines = [
        viewer.parse_line(
            n,
            json.dumps({"activation_id": "early", "recorded_at": iso(10 * n), **one}).encode(),
        )
        for n, one in enumerate(
            [
                {
                    "source": "understanding",
                    "kind": "given",
                    "body": {"messages": [{"role": "user", "content": _TAGGED}]},
                },
                {
                    "source": "understanding",
                    "kind": "returned",
                    "body": {"reply": json.dumps({"meaning": "m", "meaning_labels": ["S1"]})},
                },
            ]
        )
    ]
    step = _step(viewer.walk(lines), "Understanding")
    assert step["reading"]["shape"] == "earlier"
    assert step["resolution"] is None
    assert [one["label"] for one in step["not_cited"]] == ["H1", "R1", "M1", "P1"]


# --- recall: what each cue found ----------------------------------------------------------


def test_the_first_run_shows_what_its_cue_found_and_what_understanding_was_shown(
    record: Path,
) -> None:
    first = _step(_walk(record, INSIGHT), "Recall · first run")
    (cue,) = first["by_cue"]
    assert (cue["kinds"], cue["found"], cue["admitted"], cue["kept"]) == (
        ["activation_input"],
        3,
        2,
        2,
    )
    # Understanding's request showed both kept memories, so each find names its label.
    assert [(one["id"], one["label"], one["kept"]) for one in cue["finds"]] == [
        ("mem-lisbon", "M2", True),
        ("mem-may", "M3", True),
        ("mem-weather", None, False),
    ]


def test_the_second_run_shows_what_the_meaning_and_each_gap_found(record: Path) -> None:
    second = _step(_walk(record, INSIGHT), "Recall · second run")
    cues = [(one["text"], one["kinds"], one["listed"]) for one in second["by_cue"]]
    assert cues == [
        (MEANING, ["understood_meaning"], True),
        (GAP, ["understood_gap"], True),
        ("a cue the given entry never listed", [], False),
    ]
    _, gap, _ = second["by_cue"]
    assert [(one["id"], one["admitted"], one["kept"]) for one in gap["finds"]] == [
        ("mem-may", True, True),
        ("mem-june", False, False),
    ]


def test_a_cue_with_many_finds_lists_the_first_and_counts_the_rest() -> None:
    finds = [{"id": f"m{n}", "cue": "c", "band": "asserted"} for n in range(viewer.CUE_FINDS + 3)]
    lines = [
        viewer.parse_line(
            n,
            json.dumps({"activation_id": "many", "recorded_at": iso(10 * n), **one}).encode(),
        )
        for n, one in enumerate(
            [
                {"source": "recall", "kind": "given", "body": {"run": "first", "cues": []}},
                {"source": "recall", "kind": "returned", "body": {"finds": finds, "kept": []}},
            ]
        )
    ]
    (cue,) = _step(viewer.walk(lines), "Recall · first run")["by_cue"]
    assert (len(cue["finds"]), cue["more"], cue["listed"]) == (viewer.CUE_FINDS, 3, False)


# --- each call: its time, tokens, cost and thinking ------------------------------------


def test_each_call_of_a_step_shows_its_time_tokens_cost_and_thinking(record: Path) -> None:
    first, second = _step(_walk(record, INSIGHT), "Understanding")["spent"]
    assert first["usage"] == {
        "input": 12_345,
        "output": 456,
        "cache read": 10_000,
        "cache write": 1_000,
    }
    assert first["model"] == MODEL
    assert first["cost"]["usd"] == pytest.approx(0.01175)
    assert first["took"] == 1_000
    assert first["thinking"] is None
    assert second["usage"] == {"input": 2_000, "output": 100, "cache read": 0, "cache write": 0}
    assert second["thinking"] == THINKING


def test_a_structured_call_s_readable_view_shows_its_usage_cost_and_thinking(
    record: Path,
) -> None:
    own = viewer.Record(record.parent).lines(INSIGHT)
    assert own is not None
    returned = [
        one.line
        for one in own[0]
        if isinstance(one, viewer.Entry)
        and one.source == "understanding"
        and one.kind == "returned"
    ]
    view = viewer.model_call(own[0], returned[-1])
    assert view is not None
    did = view["did"]
    assert (did["model"], did["usage"]["input"]) == (MODEL, 2_000)
    assert did["cost"]["usd"] == pytest.approx((2_000 * 2 + 100 * 10) / 1e6)
    assert [(one["kind"], one["title"]) for one in did["parts"]] == [
        ("thinking", viewer.THINKING_TITLE),
        ("reply", "Reply"),
    ]
    assert did["parts"][0]["text"] == THINKING
    assert "usage_note" not in did


def test_a_planning_round_s_thinking_part_is_its_step_s_summary() -> None:
    response = {
        "parts": [
            {"part_kind": "thinking", "content": "Search first."},
            {"part_kind": "text", "content": "Looking."},
        ],
        "usage": {"input_tokens": 100, "output_tokens": 10},
        "model_name": "claude-sonnet-5-5-20261001",
    }
    rows = [
        {"source": "planning", "kind": "given", "body": {"messages": []}},
        {"source": "planning", "kind": "returned", "body": {"response": response}},
    ]
    lines = [
        viewer.parse_line(
            n, json.dumps({"activation_id": "plan", "recorded_at": iso(10 * n), **one}).encode()
        )
        for n, one in enumerate(rows)
    ]
    (spent,) = next(one for one in viewer.walk(lines)["steps"] if one["phase"] == "planning")[
        "spent"
    ]
    assert spent["thinking"] == "Search first."
    assert spent["cost"]["usd"] == pytest.approx((100 * 2 + 10 * 10) / 1e6)


@pytest.mark.parametrize(
    ("thinking", "shown"),
    [("one", "one"), (["one", "", "two"], "one\n\ntwo"), ("  ", None), (3, None), (None, None)],
)
def test_a_returned_entry_s_thinking_is_read_where_it_is_text(
    thinking: object, shown: str | None
) -> None:
    assert viewer.thinking_of({"thinking": thinking}) == shown


def test_a_usage_count_past_a_browser_s_numbers_is_no_count() -> None:
    """ADR-0316 §5:2: a hint not recognised, and no failure, here or in its cost."""
    body = {"usage": {"input_tokens": 10**400, "output_tokens": 5}, "model": MODEL}
    usage, model = viewer.spent_of("understanding", body)
    assert usage == {"output": 5}
    assert viewer.estimated_cost(model, usage) is not None


def test_the_walk_serves_what_it_computed(record: Path) -> None:
    with serving(record) as bound:
        connection = http.client.HTTPConnection("127.0.0.1", bound.port, timeout=10)
        try:
            connection.request(
                "GET", f"/api/walk?id={INSIGHT}", headers={"Host": f"127.0.0.1:{bound.port}"}
            )
            served = json.loads(connection.getresponse().read())
        finally:
            connection.close()
    step = next(one for one in served["steps"] if one["title"] == "Understanding")
    assert step["resolution"]["cites"][0]["outcome"] == "kept"
    assert step["spent"][1]["thinking"] == THINKING
