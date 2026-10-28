"""The activation viewer's display of a replay's results (ADR-0335 §6:4, §6:5).

The results are written by ``scripts/prompt_replay.py`` itself over a copy of a record
written with ADR-0314's own store, with a fake model behind the package's model layer, so
a change to the line either side reads fails here. The viewer is bound for real on
loopback over the copy, as over any record (ADR-0316 §2:5).
"""

from __future__ import annotations

import asyncio
import http.client
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

sys.path.insert(0, str(Path(__file__).parent))
from _activation_record import serving
from _replay_record import (
    ACT_A,
    ACT_B,
    PLANNING_TOLD,
    SCOUT_TOLD,
    UNDERSTANDING_TOLD,
    Model,
    make_copy,
    now,
    replay_tool,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic_ai.messages import ModelMessage

pytestmark = pytest.mark.integration

#: An understanding candidate with no flag in it.
CANDIDATE = "A candidate understanding instruction."

#: The lines of activation A's own file: understanding's given and returned entries, then
#: planning's, then a digest part's.
UNDERSTANDING_GIVEN, PLANNING_GIVEN, PLANNING_RETURNED, DIGEST_GIVEN = 0, 2, 3, 4


def _run(copy: Path, caller: Any = None, **options: Any) -> None:
    status = asyncio.run(
        replay_tool.replay(
            replay_tool.ReplayOptions(copy=copy, model="fake:model", **options),
            report=lambda _: None,
            caller=Model().caller() if caller is None else caller,
            now=now,
        )
    )
    assert status == 0


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """A copy with results: activation A's planning round and understanding call, and the
    scout's call under both activations; activation B's own understanding call has none."""
    made = make_copy(tmp_path)
    candidate = tmp_path / "understanding.txt"
    candidate.write_text(CANDIDATE)
    _run(made, sources=frozenset({"planning", "observer"}))
    _run(
        made,
        candidates=(str(candidate), "recorded"),
        activations=frozenset({ACT_A}),
    )
    return made


@pytest.fixture
def server(copy: Path) -> Iterator[Any]:
    """The viewer on loopback over the copy's record."""
    with serving(copy / "diagnostics") as bound:
        yield bound


def _json(port: int, path: str) -> Any:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
        response = connection.getresponse()
        assert response.status == 200
        return json.loads(response.read())
    finally:
        connection.close()


def _listed(port: int) -> dict[str, dict[str, Any]]:
    return {one["id"]: one for one in _json(port, "/api/activations")["activations"]}


def test_a_results_file_is_never_listed_and_its_activation_is_marked(
    server: Any, copy: Path
) -> None:
    assert (copy / "diagnostics" / f"{ACT_A}.replay.jsonl").is_file()

    listed = _listed(server.port)

    assert set(listed) == {ACT_A, ACT_B}
    assert listed[ACT_A]["replayed"] is True
    assert "replayed" in listed[ACT_A]["badges"]
    # B's own file has no result, but the scout's call it read for does.
    assert listed[ACT_B]["replayed"] is True


def test_an_activation_without_results_is_not_marked(tmp_path: Path) -> None:
    made = make_copy(tmp_path)
    _run(made, activations=frozenset({ACT_A}), sources=frozenset({"digesting"}))

    with serving(made / "diagnostics") as bound:
        listed = _listed(bound.port)

    assert listed[ACT_B]["replayed"] is False
    assert "replayed" not in listed[ACT_B]["badges"]


def test_a_planning_rounds_view_shows_its_result_beside_the_reply(server: Any) -> None:
    for line in (PLANNING_GIVEN, PLANNING_RETURNED):
        view = _json(server.port, f"/api/call?id={ACT_A}&line={line}")

        (result,) = view["replays"]
        assert result["prompt"] == "planning"
        assert (result["version"], result["origin"]) == ("0123456789ab", "recorded")
        assert result["recorded_version"] == "0123456789ab"
        assert result["instruction"]["text"] == PLANNING_TOLD
        assert result["model"] == "function:answer:"
        assert result["original_model"] == "claude-original"
        texts = [one["text"] for one in result["did"]["parts"]]
        assert any(one.startswith("a replayed reply") for one in texts)
        assert view["did"]["parts"][0]["text"].startswith("done")


def test_an_understanding_calls_view_shows_each_candidate_headed_by_its_prompt(
    server: Any,
) -> None:
    view = _json(server.port, f"/api/call?id={ACT_A}&line={UNDERSTANDING_GIVEN}")

    by_origin = {one["origin"]: one for one in view["replays"]}
    assert set(by_origin) == {"override", "recorded"}
    templated = by_origin["override"]
    assert templated["prompt"] == "understanding"
    assert templated["instruction"]["text"] == CANDIDATE
    # ADR-0353 §8:3: understanding declares no flag, so the candidate renders under none.
    assert templated["flags"] == []
    assert templated["flags_from"] == "none"
    assert by_origin["recorded"]["instruction"]["text"] == UNDERSTANDING_TOLD
    assert by_origin["recorded"]["did"]["parts"][0]["kind"] == "reply"


def test_a_call_with_no_result_shows_none(server: Any) -> None:
    view = _json(server.port, f"/api/call?id={ACT_A}&line={DIGEST_GIVEN}")

    assert view["replays"] == []


def test_the_observers_call_shows_the_result_written_under_each_activation(
    server: Any,
) -> None:
    for activation_id in (ACT_A, ACT_B):
        view = _json(server.port, f"/api/call?id={activation_id}&line=0&file=observer")

        (result,) = view["replays"]
        assert result["instruction"]["text"] == SCOUT_TOLD
        assert result["did"]["parts"][0]["text"].startswith("a replayed reply")


def test_a_result_naming_another_file_or_line_is_not_shown(copy: Path) -> None:
    results = copy / "diagnostics" / f"{ACT_A}.replay.jsonl"
    rewritten = results.read_text().replace(f'"file":"{ACT_A}.jsonl"', '"file":"elsewhere.jsonl"')
    results.write_text(rewritten)

    with serving(copy / "diagnostics") as bound:
        view = _json(bound.port, f"/api/call?id={ACT_A}&line={PLANNING_GIVEN}")
        observed = _json(bound.port, f"/api/call?id={ACT_A}&line=0&file=observer")

    assert view["replays"] == []
    assert len(observed["replays"]) == 1


# --- ADR-0337 §5:4: a call's samples shown together -----------------------------------------


def test_a_calls_samples_share_one_set_each_naming_its_sample(tmp_path: Path) -> None:
    made = make_copy(tmp_path)
    _run(made, sources=frozenset({"planning"}), samples=3)
    _run(made, sources=frozenset({"planning"}), samples=2)

    with serving(made / "diagnostics") as bound:
        view = _json(bound.port, f"/api/call?id={ACT_A}&line={PLANNING_GIVEN}")

    shown = view["replays"]
    assert [(one["sample"], one["samples"]) for one in shown] == [
        (1, 3),
        (2, 3),
        (3, 3),
        (1, 2),
        (2, 2),
    ]
    sets = [one["set"] for one in shown]
    assert len(set(sets[:3])) == 1
    assert len(set(sets[3:])) == 1
    assert sets[0] != sets[3]
    assert all(one["did"]["parts"] for one in shown)


def test_a_result_naming_no_sample_is_a_set_of_its_own(copy: Path) -> None:
    results = copy / "diagnostics" / f"{ACT_A}.replay.jsonl"
    rewritten = results.read_text().replace('"sample":1,"samples":1,', "")
    results.write_text(rewritten)

    with serving(copy / "diagnostics") as bound:
        view = _json(bound.port, f"/api/call?id={ACT_A}&line={UNDERSTANDING_GIVEN}")

    shown = view["replays"]
    assert [one["sample"] for one in shown] == [None, None]
    assert len({one["set"] for one in shown}) == 2


# --- ADR-0337 §6:5: a replayed response's follow-up shown as text ----------------------------


def test_a_samples_follow_up_is_shown_beside_it_as_text(tmp_path: Path) -> None:
    made = make_copy(tmp_path)
    model = Model()
    _run(made, model.caller(), sources=frozenset({"planning"}), samples=2, follow_up="")
    default = replay_tool.load_follow_up("", replay_tool.declared_prompts())
    assert default is not None

    with serving(made / "diagnostics") as bound:
        view = _json(bound.port, f"/api/call?id={ACT_A}&line={PLANNING_GIVEN}")

    for shown in view["replays"]:
        asked = shown["follow_up"]
        assert asked["answer"]["text"] == model.reply
        assert asked["failure"] is None
        assert asked["question"]["text"] == default.question
        assert asked["version"] == default.candidate.template.version
        assert asked["origin"] == "default"


def test_a_follow_up_that_failed_is_shown_as_its_failure(tmp_path: Path) -> None:
    made = make_copy(tmp_path)

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if any(isinstance(one, ModelResponse) for one in messages):
            raise ModelHTTPError(status_code=429, model_name="named")
        return ModelResponse(parts=[TextPart("a reply")])

    caller = replay_tool.ModelCaller(FunctionModel(answer), timeout=10)
    _run(made, caller, sources=frozenset({"digesting"}), follow_up="")

    with serving(made / "diagnostics") as bound:
        view = _json(bound.port, f"/api/call?id={ACT_A}&line={DIGEST_GIVEN}")

    (shown,) = view["replays"]
    assert shown["follow_up"]["answer"] is None
    assert shown["follow_up"]["failure"].startswith("ModelRateLimitError")


def test_a_result_with_no_follow_up_shows_none(server: Any) -> None:
    view = _json(server.port, f"/api/call?id={ACT_A}&line={PLANNING_GIVEN}")

    assert [one["follow_up"] for one in view["replays"]] == [None]
