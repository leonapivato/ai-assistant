"""ADR-0383 §9:1's named test: no read under ``orchestration/`` goes round the filter.

**What it fails on.** Any class or function under ``src/ai_assistant/orchestration/``
that takes or holds one of the six store Protocols of §7:1 or ``MemoryWriter`` unbound,
save the holder that binds stores for a pass, the holders §7:8, §7:12 and §7:13 name, and
a closed list of holders not yet converted, each naming the lane of milestone 22 that
removes it. The list only shrinks: an entry that no longer holds a store fails too, so a
lane that converts a holder takes its entry off in the same change.

**How it reads "takes or holds".** By annotation, which strict typing makes total: every
parameter and return of every function and method, and every annotated name, a class's
fields and ``self.x: T`` among them, is read for a store Protocol's name anywhere in it —
``X | None``, a container of one, a quoted forward reference. A lambda's parameters carry
no annotation, so a lambda holds nothing but what its enclosing holder holds. A holder is
the top-level class or function of its module that the annotation sits in, so a method, a
nested function and a closure count toward the class or function that encloses them.
``Bound[X]`` (``orchestration.bound_stores.Bound``) is read as bound: it marks a parameter
handed a store :class:`BoundStores` gave for a sight, and is read as nothing else. A
``type`` alias is a name for a shape, not a holder, and is not read.

**Closures** (the inventory's caveat). A closure made under ``orchestration/`` reaches a
store only through a value its enclosing class or function holds, and that holder's
annotation is read here: the closures milestone 22's inventory names (``ChangeStream``'s
``state_of``, ``Matters``' ``set_up``, the readers' ``written`` and ``writers``,
``attach_connections`` and ``attach_approvals``) each reach a store through ``Engine``,
``ConversationLifecycle``, ``TaskManager`` or ``PhasePath``, all on the list below. What
this test cannot see is a callable built **outside** ``orchestration/``, by the
composition root, that closes over an unbound store and is handed in typed as a plain
``Callable``; the root builds none for a converted stage (``test_composition`` holds the
converted stages' wiring).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Final

import ai_assistant.orchestration

if TYPE_CHECKING:
    from collections.abc import Iterator

#: §7:1's six store Protocols, and ``MemoryWriter``.
STORES: Final = frozenset(
    {
        "MemoryStore",
        "StoryStore",
        "ConversationStore",
        "PlanStore",
        "PersonModelStore",
        "NotificationStore",
        "MemoryWriter",
    }
)

#: The mark of a parameter handed a store bound to a sight (``bound_stores.Bound``).
BOUND_MARK: Final = "Bound"

#: The holder that binds stores for a pass (§9:1).
THE_HOLDER: Final = "bound_stores.py:BoundStores"

#: The holders §7:8, §7:12 and §7:13 name, each with its clause: they read unbound for
#: good.
NAMED_BY_THE_DECISION: Final[dict[str, str]] = {
    # §7:8: "a sensor's finding of what is due" (`look`) and "the engine's start" (its
    # `settle_restart` and the `confirm` that settles one occurrence).
    "task_sensor.py:TaskSchedulerSensor": "§7:8",
    # §7:8: the approvals sensor's finding of what is due (`look`), the engine's start
    # (`settle_restart`), and voiding a held ticket, which ADR-0384 §2's table leaves
    # unchanged.
    "approval_sensor.py:ApprovalsSensor": "§7:8",
}

#: Holders not yet converted, each with the lane of milestone 22 that removes it (#3711):
#: B8b the channel readers' windows, B8c look-ups, stories, the person block and matters,
#: B8d the plan store's users, authorizing, acting, tasks, approvals and the holders
#: ADR-0387 names, B9 the observer and the upkeep runs, B10 the owner's own acts
#: (ADR-0385). A holder more than one lane converts names the last of them. **Only
#: shrinks.** A holder whose last unbound read is one §7:8, §7:12 or §7:13 names moves
#: to :data:`NAMED_BY_THE_DECISION` in the lane that converts the rest: the observer's
#: finding of what is due (§7:12, §7:13), the engine's start and ADR-0384 §2's unchanged
#: jobs (§7:8).
NOT_YET_CONVERTED: Final[dict[str, str]] = {
    "acting.py:ActingStage": "B8d",
    # The work's own episode (B8d, ADR-0387); closing open episodes is §7:8's.
    "activation_writer.py:ActivationWriter": "B8d",
    "approval_calls.py:ApprovalCalls": "B8d",
    "authorizer.py:AuthorizingStage": "B8d",
    # Authorizing's (B8d) and the observer's reading's (B9).
    "authorizer.py:read_outside_content": "B9",
    # The phases' pending candidates (B8d) and the owner's (B10).
    "candidates.py:pending_candidates": "B10",
    "candidates.py:held_candidates": "B10",
    "candidates.py:_page_candidates": "B10",
    "candidates.py:_approved_candidates": "B10",
    "change_stream.py:ChangeStream": "B10",
    "chat.py:ChatReader": "B8b",
    # The phases' message writer, a work's turn in its own place (ADR-0387).
    "chat.py:ChatWriter": "B8d",
    # The surface's acts (B10); its sweeps are §7:8's.
    "conversations.py:ConversationLifecycle": "B10",
    "conversations.py:conversation_state": "B10",
    "conversations.py:episodes_on_place": "B10",
    "conversations.py:_open_on": "B10",
    "conversations.py:_shown_ending": "B10",
    "conversations.py:_older_ending": "B10",
    "conversations.py:_judged": "B10",
    "conversations.py:_last_taker": "B10",
    # Every lane from B8b to B10 converts a use; its start is §7:8's.
    "engine.py:Engine": "B10",
    "engine.py:_written_preferences": "B10",
    "engine.py:approval_panel": "B10",
    "engine.py:episode_card_facts": "B10",
    "engine.py:tap_on_approval_panel": "B10",
    "episode_lookups.py:EpisodeLookUpReads": "B8c",
    "lookups.py:ConnectionSearch": "B8c",
    "lookups.py:LookUps": "B8c",
    "matters.py:Matters": "B8c",
    "matters_pass.py:MattersPass": "B9",
    # The upcoming-event producer's writer and the reconsideration's policy.
    "notifications.py:NotificationWriteStage": "B9",
    "notifications.py:RulingPolicy": "B9",
    "observer/person.py:PinConfirmations": "B9",
    "observer/person.py:person_of": "B9",
    "observer/placement.py:compacted": "B9",
    "observer/placement.py:retrieved": "B9",
    "observer/reading.py:EpisodeReader": "B9",
    "observer/reading.py:_shown_notes": "B9",
    "observer/reading.py:_stories_to_search": "B9",
    "observer/reading.py:_story_notes": "B9",
    # Its runs' reads (B9); its finding of what is due is §7:12's.
    "observer/stage.py:Observer": "B9",
    "observer/writing.py:FindingWriter": "B9",
    # The person block (B8c) and the person panel (B10).
    "person_block.py:PersonBlocks": "B10",
    "person_block.py:still_held": "B8c",
    "phase_path.py:PhasePath": "B8d",
    "phase_path.py:StoryReads": "B8c",
    # Planning's story calls (B8c) and the engine's story methods (B10).
    "stories.py:unknown_activation": "B10",
    "stories.py:of_another_home": "B10",
    "stories.py:resolved_view": "B10",
    "stories.py:owner_summary": "B10",
    "stories.py:_all_notes": "B10",
    "story_calls.py:StoryCalls": "B8c",
    # The matters pass and the scheduled tidy-up (B9), and a work's tidy-up (B8c).
    "story_flags.py:read_headers": "B9",
    "story_flags.py:read_log": "B9",
    "story_flags.py:read_records": "B9",
    "story_flags.py:read_versions": "B9",
    "story_flags.py:recorded_decisions": "B9",
    "story_flags.py:reread": "B9",
    "story_links.py:StoryCandidates": "B8c",
    "story_links.py:StoryLinksStage": "B8c",
    "story_links.py:_Writes": "B8c",
    "story_links.py:admitted_episodes": "B8c",
    # The phases' story views (B8c) and the engine's story standing (B10).
    "story_standing.py:story_standing": "B10",
    "story_standing.py:_shown": "B10",
    "story_standing.py:_done": "B10",
    "story_standing.py:_related": "B10",
    "story_standing.py:_member_count": "B10",
    "story_tidy_up.py:StoryTidyUp": "B9",
    "story_tidy_up.py:ScheduledTidyUp": "B9",
    "task_manager.py:PlaceLists": "B8d",
    "task_manager.py:TaskManager": "B8d",
    "task_rules.py:PersonZones": "B8d",
    # The line's cards: a work's approval (B8d), the line's window (B8b), the owner's tap
    # (B10).
    "telegram.py:TelegramCards": "B10",
    "telegram.py:TelegramReader": "B8b",
    # The observer's use of the one selector; the windows stage walks it bound.
    "understanding.py:RecentEpisodes": "B9",
    "writes.py:MemoryWriteStage": "B9",
}

_LANES: Final = frozenset({"B8b", "B8c", "B8d", "B9", "B10"})
_ROOT: Final = Path(ai_assistant.orchestration.__file__).parent


def _stores_named(annotation: ast.expr) -> Iterator[str]:
    """Each store Protocol ``annotation`` names unbound, a quoted one's included."""
    node: ast.expr = annotation
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:  # a `Literal`'s text, not a quoted name
            return
    if isinstance(node, ast.Subscript):
        marked = node.value
        if (isinstance(marked, ast.Name) and marked.id == BOUND_MARK) or (
            isinstance(marked, ast.Attribute) and marked.attr == BOUND_MARK
        ):
            return
    if isinstance(node, ast.Name) and node.id in STORES:
        yield node.id
    if isinstance(node, ast.Attribute) and node.attr in STORES:
        yield node.attr
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.expr):
            yield from _stores_named(child)


def _annotations(node: ast.AST) -> Iterator[ast.expr]:
    """Every annotation one node carries: a function's parameters and return, a name's."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        arguments = node.args
        every = (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *(one for one in (arguments.vararg, arguments.kwarg) if one is not None),
        )
        yield from (one.annotation for one in every if one.annotation is not None)
        if not isinstance(node, ast.Lambda) and node.returns is not None:
            yield node.returns
    elif isinstance(node, ast.AnnAssign):
        yield node.annotation


def _holder(top: ast.stmt) -> str | None:
    """The name a top-level statement holds under, where it can hold anything."""
    if isinstance(top, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return top.name
    if isinstance(top, ast.AnnAssign) and isinstance(top.target, ast.Name):
        return top.target.id
    return None


def unbound_holders(root: Path = _ROOT) -> dict[str, frozenset[str]]:
    """Every holder under ``root`` that takes or holds a store unbound, with the stores.

    Keyed ``<module path>:<top-level name>``, the module path relative to ``root``.
    """
    found: dict[str, frozenset[str]] = {}
    for path in sorted(root.rglob("*.py")):
        module = path.relative_to(root).as_posix()
        for top in ast.parse(path.read_text(encoding="utf-8")).body:
            name = _holder(top)
            if name is None:
                continue
            stores = frozenset(
                store
                for node in ast.walk(top)
                for annotation in _annotations(node)
                for store in _stores_named(annotation)
            )
            if stores:
                found[f"{module}:{name}"] = stores
    return found


def test_no_holder_outside_the_lists_takes_or_holds_a_store_unbound() -> None:
    """§9:1: a stage holds the holder that gives a store only for a sight, never a store."""
    allowed = {THE_HOLDER, *NAMED_BY_THE_DECISION, *NOT_YET_CONVERTED}
    stray = {key: sorted(stores) for key, stores in unbound_holders().items() if key not in allowed}
    assert stray == {}, (
        "these take or hold a store unbound: read through the holder "
        "(orchestration.bound_stores.BoundStores) by the pass's sight, or mark a store "
        "handed per call `Bound[...]`"
    )


def test_every_entry_still_holds_a_store_so_the_list_only_shrinks() -> None:
    """An entry whose holder no longer holds a store comes off the list in the same change."""
    held = unbound_holders()
    gone = sorted(
        key for key in (THE_HOLDER, *NAMED_BY_THE_DECISION, *NOT_YET_CONVERTED) if key not in held
    )
    assert gone == [], "these hold no store unbound any more: take them off the list"


def test_every_unconverted_holder_names_a_lane_and_none_is_named_twice() -> None:
    assert set(NOT_YET_CONVERTED.values()) <= _LANES
    assert not set(NOT_YET_CONVERTED) & set(NAMED_BY_THE_DECISION)
    assert THE_HOLDER not in NOT_YET_CONVERTED


def test_the_stages_this_lane_converted_hold_no_store() -> None:
    """Recall and the windows (milestone 22's B8a) read through the holder alone."""
    held = unbound_holders()
    for converted in (
        "recall.py:RecallStage",
        "understanding.py:WindowsStage",
        "understanding.py:fetch_held",
    ):
        assert converted not in held
        assert converted not in NOT_YET_CONVERTED


def test_the_reading_sees_every_shape_a_store_is_held_in(tmp_path: Path) -> None:
    """The scan reads a union, a container, a quoted name, a field, a return and a nested
    function, and reads ``Bound[...]`` and a ``type`` alias as nothing."""
    source = """
type Walk = Callable[[MemoryStore], None]
class Field:
    store: StoryStore | None
class Attribute:
    def __init__(self, plans: "protocols.PlanStore") -> None:
        self.plans = plans
def many(stores: Sequence[ConversationStore]) -> None: ...
def gives() -> NotificationStore: ...
def bound(memory: Bound[MemoryStore]) -> Bound[StoryStore]: ...
def walks(walk: Walk) -> None: ...
class Closes:
    def make(self) -> object:
        def inner(writer: MemoryWriter) -> None: ...
        return inner
handed: PersonModelStore
"""
    (tmp_path / "held.py").write_text(source, encoding="utf-8")
    assert unbound_holders(tmp_path) == {
        "held.py:Field": frozenset({"StoryStore"}),
        "held.py:Attribute": frozenset({"PlanStore"}),
        "held.py:many": frozenset({"ConversationStore"}),
        "held.py:gives": frozenset({"NotificationStore"}),
        "held.py:Closes": frozenset({"MemoryWriter"}),
        "held.py:handed": frozenset({"PersonModelStore"}),
    }
