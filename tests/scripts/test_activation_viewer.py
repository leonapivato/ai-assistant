"""Tests for ``scripts/activation_viewer.py`` (ADR-0316).

The viewer is loaded by its path, as every script here is: it is no package, and
nothing in ``ai_assistant`` may import it (§2:4). Its records are written with ADR-0314's
own store, so a change to the line the viewer reads fails here (§7:2), and the server
is bound for real on loopback, so §6's refusals and headers are pinned as a browser
meets them (§7:3).
"""

from __future__ import annotations

import ast
import hashlib
import http.client
import inspect
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _operator_recipes import SCRIPTS

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

from _activation_record import (
    ACTIVATION,
    FOREIGN_LINES,
    HOSTILE,
    PRIVATE,
    at,
    iso,
    serving,
    step,
    viewer,
    write_record,
)


@pytest.fixture
def record(tmp_path: Path) -> Path:
    """A record written by ADR-0314's store, plus the lines it cannot write."""
    return write_record(tmp_path)


@pytest.fixture
def server(record: Path) -> Iterator[Any]:
    """The viewer bound on loopback at a free port, over ``record``'s data directory."""
    with serving(record) as bound:
        yield bound


_SOURCE = SCRIPTS / "activation_viewer.py"
_PACKAGE = Path(__file__).parents[2] / "src" / "ai_assistant"


def _request(
    port: int, path: str, *, method: str = "GET", host: str | None = "default"
) -> tuple[int, Mapping[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        if host is not None:
            connection.putheader("Host", f"127.0.0.1:{port}" if host == "default" else host)
        connection.endheaders()
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def _get_json(port: int, path: str) -> Any:
    status, headers, body = _request(port, path)
    assert status == 200, body
    assert headers["Content-Type"].startswith("application/json")
    return json.loads(body)


def _summary(port: int, activation_id: str) -> Any:
    listed = _get_json(port, "/api/activations")["activations"]
    return next(one for one in listed if one["id"] == activation_id)


def _snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    return {
        str(path.relative_to(root)): (
            path.stat().st_mode,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "",
        )
        for path in sorted(root.rglob("*"))
    }


# --- §2, §7:1: what it is and where it lives ----------------------------------------------


def test_it_imports_the_standard_library_alone() -> None:
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import"
            assert node.module is not None
            imported.add(node.module.split(".")[0])
    assert imported, "the scan found no imports at all"
    foreign = {name for name in imported if name not in sys.stdlib_module_names}
    assert foreign <= {"__future__"}, foreign


def test_nothing_in_the_package_names_it() -> None:
    naming = [
        path
        for path in _PACKAGE.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and b"activation_viewer" in path.read_bytes()
    ]
    assert naming == []


# --- §6: what it may not do -----------------------------------------------------------------


def test_it_binds_loopback_alone_and_takes_no_address(record: Path) -> None:
    assert viewer.HOST == "127.0.0.1"
    assert "host" not in inspect.signature(viewer.ViewerServer).parameters
    bound = viewer.ViewerServer(viewer.Record(record), 0, report=lambda _line: None)
    try:
        assert bound.server_address[0] == "127.0.0.1"
    finally:
        bound.server_close()
    for option in ("--host", "--bind", "--address"):
        with pytest.raises(SystemExit):
            viewer.parse_args([str(record), option, "0.0.0.0"])  # noqa: S104 — the refused bind


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "evil.example:{port}",
        "127.0.0.1:1",
        "localhost",
        "0.0.0.0:{port}",
        "[::1]:{port}",
        "",
    ],
)
def test_it_refuses_a_host_that_is_not_its_own_loopback_name(server: Any, host: str) -> None:
    status, headers, body = _request(
        server.port, "/api/activations", host=host.format(port=server.port)
    )
    assert status == 403
    assert b"act-1" not in body
    assert headers["Cache-Control"] == "no-store"


def test_it_refuses_a_request_with_no_host(server: Any) -> None:
    status, _headers, _body = _request(server.port, "/", host=None)
    assert status == 403


def test_it_answers_both_loopback_names(server: Any) -> None:
    for host in (
        f"127.0.0.1:{server.port}",
        f"localhost:{server.port}",
        f"LOCALHOST:{server.port}",
    ):
        status, _headers, _body = _request(server.port, "/", host=host)
        assert status == 200


@pytest.mark.parametrize(
    "method", ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "BREW"]
)
def test_it_answers_get_alone(server: Any, method: str) -> None:
    status, headers, _body = _request(server.port, "/api/activations", method=method)
    assert status == 405
    assert headers["Allow"] == "GET"
    assert headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/app.js",
        "/app.css",
        "/favicon.ico",
        "/api/activations",
        "/api/activation?id=act-1",
        "/nowhere",
    ],
)
def test_every_response_carries_no_store_and_a_self_only_policy(server: Any, path: str) -> None:
    _status, headers, _body = _request(server.port, path)
    assert headers["Cache-Control"] == "no-store"
    policy = headers["Content-Security-Policy"]
    assert "default-src 'none'" in policy
    assert "script-src 'self'" in policy
    assert "connect-src 'self'" in policy
    assert "http" not in policy
    assert "*" not in policy
    assert "unsafe" not in policy
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_the_page_loads_nothing_it_does_not_serve(server: Any) -> None:
    for path in ("/", "/app.js", "/app.css"):
        _status, _headers, body = _request(server.port, path)
        assert b"http://" not in body
        assert b"https://" not in body
        assert b"//cdn" not in body


def test_an_activation_is_named_by_a_listed_id_never_a_path(server: Any, record: Path) -> None:
    (record.parent / "elsewhere.jsonl").write_text(
        json.dumps(
            {
                "activation_id": "x",
                "source": "planning",
                "kind": "given",
                "recorded_at": iso(0),
                "body": {},
            }
        )
        + "\n"
    )
    for name in ("../elsewhere", "..%2Felsewhere", "/etc/passwd", "act-1.jsonl", "act-1/..", ""):
        status, _headers, _body = _request(server.port, f"/api/activation?id={name}")
        assert status == 404, name
        status, _headers, _body = _request(server.port, f"/api/entry?id={name}&line=0")
        assert status == 404, name


def test_serving_leaves_the_record_unchanged(server: Any, record: Path) -> None:
    root = record.parent.parent
    before = _snapshot(root)
    for path in (
        "/",
        "/app.js",
        "/app.css",
        "/api/activations",
        "/api/activations?v=stale",
        "/api/activation?id=act-1",
        "/api/activation?id=act-2",
        "/api/entry?id=act-1&line=0",
        "/api/entry?id=act-2&line=1",
    ):
        _request(server.port, path)
    assert _snapshot(root) == before


# --- §3, §5: reading the store's record -----------------------------------------------------


def test_it_reads_the_stores_lines_the_marker_and_what_it_does_not_know(record: Path) -> None:
    read = viewer.Record(record).lines("act-1")
    assert read is not None
    lines, _version = read
    entries = [one for one in lines if isinstance(one, viewer.Entry)]
    assert len(entries) == len(ACTIVATION) + len(FOREIGN_LINES)
    assert entries[0].source == "understanding"
    assert entries[0].kind == "given"
    assert entries[0].at == at(10).timestamp()
    assert [(one.source, one.kind) for one in entries[-2:]] == [
        ("planning", "pondered"),
        ("oracle", "given"),
    ]
    # The line that is not JSON is counted; the line with no newline yet is not read.
    assert lines.count(None) == 1
    assert len(lines) == len(ACTIVATION) + len(FOREIGN_LINES) + 1

    marked = viewer.Record(record).lines("act-2")
    assert marked is not None
    last = marked[0][-1]
    assert isinstance(last, viewer.Truncation)
    assert last.at == at(100_500).timestamp()


def test_the_list_shows_each_activations_flow_newest_first(server: Any) -> None:
    listed = _get_json(server.port, "/api/activations")
    assert [one["id"] for one in listed["activations"]] == ["act-2", "act-1"]
    first = listed["activations"][1]
    assert first["input"] == HOSTILE
    assert first["ended"] == "nothing_due"
    assert first["rounds"] == 2
    assert first["duration"] == pytest.approx(1901 - 5)
    assert first["unreadable"] == 1
    assert first["open"] is False
    assert set(first["badges"]) == {"needs_you", "outside_content", "digest_failed"}
    second = listed["activations"][0]
    assert second["badges"] == ["truncated"]
    assert second["input"] == "hello"
    # Polling with the version it was given costs nothing and says so.
    again = _get_json(server.port, f"/api/activations?v={listed['version']}")
    assert again["unchanged"] is True


def test_the_badges_cover_a_refusal_and_a_stage_that_failed() -> None:
    tally = viewer.Tally("a")
    body = {"calls": [{"verdict": "not_done"}], "message": {"allowed": False}}
    tally.feed(viewer.Entry(0, "authorizing", "returned", 1.0, "", body))
    tally.feed(viewer.Entry(1, "controller", "step", 2.0, "", step("end", "stage_failed", 2, 2)))
    assert set(tally.badges()) == {"refused", "could_not_finish"}


def test_the_timeline_draws_one_lane_per_source_and_planning_by_round(server: Any) -> None:
    shown = _get_json(server.port, "/api/activation?id=act-1")
    lanes = [lane["key"] for lane in shown["lanes"]]
    assert lanes[:7] == [
        "controller",
        "recall",
        "understanding",
        "planning",
        "authorizing",
        "acting",
        "digesting",
    ]
    assert lanes[7:] == ["planning · pondered", "oracle"]
    items = shown["items"]
    rounds = [one for one in items if one["lane"] == "planning" and one["kind"] == "step"]
    assert [one["label"] for one in rounds] == ["round 1", "round 2"]
    assert rounds[0]["start"] == pytest.approx(at(410).timestamp() * 1000)
    assert rounds[0]["end"] == pytest.approx(at(901).timestamp() * 1000)
    calls = [one for one in items if one["lane"] == "planning" and one["kind"] == "call"]
    assert [one["round"] for one in calls] == [1, 2]
    assert len(calls[0]["lines"]) == 2
    acting = [one for one in items if one["lane"] == "acting"]
    assert len(acting) == 1
    failed = [one for one in items if one["lane"] == "digesting" and one["kind"] == "call"]
    assert failed[0]["tone"] == "failed"
    assert shown["rounds"][0]["text"] == "Looking that up. " + PRIVATE
    assert shown["rounds"][0]["calls"] == [
        {"id": "c1", "name": "web_search"},
        {"id": "c2", "name": "web_search"},
    ]
    assert shown["rounds"][0]["marked"] is True
    assert shown["rounds"][0]["thinking"] is True
    assert [(one["call_id"], one["verdict"]) for one in shown["rounds"][0]["verdicts"]] == [
        ("c1", "allowed"),
        ("c2", "needs_you"),
    ]
    assert shown["rounds"][1]["marked"] is False
    assert shown["rounds"][1]["text"] == "Here is the answer."
    assert shown["unreadable"] == 1


def test_a_message_is_marked_allowed_and_never_claimed_written(server: Any) -> None:
    shown = _get_json(server.port, "/api/activation?id=act-1")
    marks = [one for one in shown["items"] if one["kind"] == "message"]
    assert len(marks) == 1
    assert marks[0]["lane"] == "authorizing"
    assert marks[0]["label"] == "message allowed"
    assert shown["rounds"][1]["message"] == {"allowed": True, "reason": None}
    assert "written" not in json.dumps(shown).replace("not recorded", "")
    assert "whether it was written is not recorded" in viewer.SCRIPT


def test_the_truncation_marker_is_the_files_end(server: Any) -> None:
    shown = _get_json(server.port, "/api/activation?id=act-2")
    assert shown["truncated"]["at"] == pytest.approx(at(100_500).timestamp() * 1000)
    assert shown["summary"]["badges"] == ["truncated"]
    marker = _get_json(server.port, f"/api/entry?id=act-2&line={shown['truncated']['line']}")
    assert marker["truncated_at"].startswith("2026-10-13T09:01:40.500000")


def test_a_click_shows_a_body_whole(server: Any) -> None:
    entry = _get_json(server.port, "/api/entry?id=act-1&line=4")
    assert entry["source"] == "planning"
    assert entry["kind"] == "returned"
    assert entry["body"] == ACTIVATION[4][3]
    missing, _headers, _body = _request(server.port, "/api/entry?id=act-1&line=999")
    assert missing == 404


# --- §4: near-live --------------------------------------------------------------------------


def test_it_follows_the_directory_as_it_changes(server: Any, record: Path) -> None:
    def ids() -> list[str]:
        return [one["id"] for one in _get_json(server.port, "/api/activations")["activations"]]

    line = json.dumps(
        {
            "activation_id": "act-3",
            "source": "controller",
            "kind": "step",
            "recorded_at": iso(200_000),
            "body": {},
        }
    )
    fresh = record / "act-3.jsonl"
    fresh.write_text(line[:20])
    assert "act-3" in ids()
    assert _summary(server.port, "act-3")["entries"] == 0
    with fresh.open("a") as handle:
        handle.write(line[20:] + "\n")
    assert _summary(server.port, "act-3")["entries"] == 1
    fresh.unlink()
    (record / "act-2.jsonl").unlink()
    assert ids() == ["act-1"]
    gone, _headers, _body = _request(server.port, "/api/activation?id=act-2")
    assert gone == 404


def test_a_record_not_yet_created_lists_nothing(tmp_path: Path) -> None:
    listed = viewer.Record(tmp_path / "missing").activations()
    assert listed["activations"] == []
    assert listed["present"] is False
    assert not (tmp_path / "missing").exists()


# --- §6:7-§6:8: text, never markup; nothing printed from an entry ---------------------------


def test_entry_text_is_served_as_data_and_rendered_as_text(server: Any) -> None:
    status, headers, body = _request(server.port, "/api/entry?id=act-1&line=0")
    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert headers["X-Content-Type-Options"] == "nosniff"
    # The page holds no entry: everything reaches it through fetch as JSON.
    _status, _headers, page = _request(server.port, "/")
    assert HOSTILE.encode() not in page
    # And the script puts every string into the page as text, never as markup.
    for sink in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "Function(",
    ):
        assert sink not in viewer.SCRIPT, sink
    assert "textContent" in viewer.SCRIPT
    assert json.loads(body)["body"]["messages"][1]["content"].find("<script>") >= 0


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.mark.timeout(60)
def test_run_from_the_command_line_it_prints_its_address_and_no_entry(record: Path) -> None:
    port = _free_port()
    process = subprocess.Popen(  # noqa: S603 — this interpreter and the script, by path
        [sys.executable, "-B", str(_SOURCE), str(record), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                status, _headers, _body = _request(port, "/api/activations")
                break
            except OSError:
                assert time.monotonic() < deadline, "the viewer did not start"
                time.sleep(0.1)
        assert status == 200
        for path in (
            "/api/activation?id=act-1",
            "/api/entry?id=act-1&line=4",
            "/api/entry?id=act-1&line=x",
        ):
            _request(port, path)
        _request(port, "/", method="POST")
        _request(port, "/", host="evil.example")
    finally:
        process.terminate()
        stdout, stderr = process.communicate(timeout=10)
    printed = stdout + stderr
    assert f"http://127.0.0.1:{port}".encode() in printed
    for content in (PRIVATE, "act-1", "Looking that up", "hello"):
        assert content.encode() not in printed


def test_help_says_how_to_run_it() -> None:
    result = subprocess.run(  # noqa: S603 — this interpreter and the script, by path
        [sys.executable, "-B", str(_SOURCE), "--help"], capture_output=True, text=True, check=True
    )
    for needed in ("ssh -L 8765:127.0.0.1:8765", "--port", "hub's user", "diagnostics"):
        assert needed in result.stdout, needed


# --- §5:2: a hint lost, never an activation ------------------------------------------------

#: Values no source writes today, in every place a hint is read.
_ODD: tuple[object, ...] = ([], {}, 1, None, "text", [{}], {"x": []})

_HINT_KEYS = (
    "stage",
    "due",
    "outcome",
    "started_at",
    "ended_at",
    "failure",
    "messages",
    "calls",
    "message",
    "read_outside_content",
    "digest",
    "response",
    "result",
    "question",
    "part",
    "run",
    "grounds",
)

_SOURCES = ("controller", "understanding", "recall", "planning", "authorizing", "digesting")


def _odd_lines() -> list[bytes]:
    shapes: list[object] = [*_ODD]
    shapes += [dict.fromkeys(_HINT_KEYS, odd) for odd in _ODD]
    shapes += [
        {"response": {"parts": [odd, {"part_kind": "tool-call", "args": odd}]}} for odd in _ODD
    ]
    shapes += [{"calls": [odd], "message": odd} for odd in _ODD]
    lines: list[bytes] = []
    for number, body in enumerate(shapes):
        for source in _SOURCES:
            for kind in ("given", "returned", "step"):
                line = {
                    "activation_id": "odd",
                    "source": source,
                    "kind": kind,
                    "recorded_at": iso(number),
                    "body": body,
                }
                lines.append(json.dumps(line).encode())
    return lines


def test_a_body_of_an_unexpected_shape_loses_its_hint_and_nothing_else() -> None:
    lines = [viewer.parse_line(number, raw) for number, raw in enumerate(_odd_lines())]
    assert None not in lines
    tally = viewer.Tally("odd")
    for line in lines:
        tally.feed(line)
    json.dumps(tally.summary(), allow_nan=False)
    shown = viewer.timeline("odd", lines)
    json.dumps(shown, allow_nan=False)
    assert len(shown["entries"]) == len(lines)


def test_one_odd_activation_leaves_the_list_and_the_others_whole(server: Any, record: Path) -> None:
    (record / "odd.jsonl").write_bytes(b"\n".join(_odd_lines()) + b"\n")
    listed = {one["id"] for one in _get_json(server.port, "/api/activations")["activations"]}
    assert listed == {"act-1", "act-2", "odd"}
    assert _get_json(server.port, "/api/activation?id=odd")["id"] == "odd"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_line_holding_a_constant_json_does_not_have_is_unreadable(constant: str) -> None:
    raw = '{"activation_id": "a", "source": "planning", "kind": "given", '
    raw += f'"recorded_at": "{iso(0)}", "body": {{"x": {constant}}}}}'
    assert viewer.parse_line(0, raw.encode()) is None


def test_a_string_that_names_no_instant_is_no_instant() -> None:
    values: tuple[object, ...] = ("", "not a time", "2026-13-40T00:00:00", [], None, 7)
    for value in values:
        assert viewer.instant(value) is None


def test_a_number_too_large_to_be_finite_makes_its_line_unreadable() -> None:
    raw = '{"activation_id": "a", "source": "planning", "kind": "given", '
    raw += f'"recorded_at": "{iso(0)}", "body": {{"x": 1e400}}}}'
    assert viewer.parse_line(0, raw.encode()) is None


def test_a_lone_surrogate_in_an_entry_is_served_not_fatal(server: Any, record: Path) -> None:
    # The input as understanding's request carries it: JSON inside a message's content,
    # here with a lone surrogate escaped in it.
    content = '{"input": {"text": "before \\ud800 after"}}'
    line = {
        "activation_id": "lone",
        "source": "understanding",
        "kind": "given",
        "recorded_at": iso(300_000),
        "body": {"messages": [{"role": "user", "content": content}]},
    }
    (record / "lone.jsonl").write_text(json.dumps(line) + "\n")
    shown = _summary(server.port, "lone")
    assert shown["input"] == "before \ud800 after"
    assert _summary(server.port, "act-1")["rounds"] == 2
    entry = _get_json(server.port, "/api/entry?id=lone&line=0")
    assert entry["body"]["messages"][0]["content"] == content


def test_a_request_whose_response_was_never_written_keeps_no_later_response() -> None:
    lines = [
        viewer.Entry(0, "planning", "given", 1.0, "", {"messages": []}),
        # Round 1's returned entry was never written (ADR-0314 §2:4).
        viewer.Entry(1, "planning", "given", 5.0, "", {"messages": []}),
        viewer.Entry(2, "planning", "returned", 6.0, "", {"response": {"parts": []}}),
    ]
    shown = viewer.timeline("a", lines)
    calls = [one for one in shown["items"] if one["kind"] == "call"]
    assert [(one["round"], one["lines"], one["tone"]) for one in calls] == [
        (2, [1, 2], "ok"),
        (1, [0], "pending"),
    ]
    assert "returned" not in shown["rounds"][0]
    assert shown["rounds"][1]["returned"] == 2
