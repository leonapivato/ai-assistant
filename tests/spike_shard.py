"""SPIKE (do not merge): split the suite across CI jobs, evidence kept whole in shard 0."""

import zlib

import pytest

_TRIAD = "tests/core/test_protocol_triad.py"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    count = config.getoption("shard_count")
    if not count:
        return
    index = config.getoption("shard_index")
    from test_protocol_triad import static_candidacy  # noqa: PLC0415

    seen: dict[type, bool] = {}
    pinned: list[bool] = []
    for item in items:
        cls = getattr(item, "cls", None)
        if cls is not None and cls not in seen:
            seen[cls] = bool(static_candidacy(cls))
        pinned.append(item.nodeid.startswith(_TRIAD) or (cls is not None and seen[cls]))
    evidence = sum(pinned)
    rest = len(items) - evidence
    target = len(items) / count
    # Shard 0's share of the unpinned items is what is left of its target after the
    # evidence; the others split the remainder evenly. Cut points over [0, 1).
    first = max(0.0, target - evidence) / rest if rest else 0.0
    cuts = [first + i * (1 - first) / (count - 1) for i in range(1, count)] if count > 1 else []
    keep: list[pytest.Item] = []
    drop: list[pytest.Item] = []
    for item, pin in zip(items, pinned, strict=True):
        if pin:
            shard = 0
        else:
            mark = item.get_closest_marker("xdist_group")
            key = item.nodeid
            if mark is not None:
                key = str(mark.args[0] if mark.args else mark.kwargs.get("name"))
            point = (zlib.crc32(key.encode()) % 100_000) / 100_000
            shard = sum(point >= cut for cut in [first, *cuts[:-1]]) if count > 1 else 0
        (keep if shard == index else drop).append(item)
    items[:] = keep
    if drop:
        config.hook.pytest_deselected(items=drop)
