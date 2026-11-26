"""ADR-0383 §9:1's named test: no read under ``orchestration/`` goes round the filter.

**What it fails on.** Any class or function under ``src/ai_assistant/orchestration/``
that takes or holds one of the six store Protocols of §7:1 or ``MemoryWriter`` unbound,
save the holder that binds stores for a pass, the holders §7:8, §7:12 and §7:13 name, the
holders ADR-0387 §7:4 admits for the conversation store alone, and a closed list of
holders not yet converted, each naming the lane of milestone 22 that removes it. The
list only shrinks: an entry that no longer holds a store fails too, so a lane that
converts a holder takes its entry off in the same change.

**How it reads "takes or holds".** By annotation, which strict typing makes total: every
parameter and return of every function and method, and every annotated name, a class's
fields and ``self.x: T`` among them, is read for a store Protocol's name anywhere in it —
``X | None``, a container of one, a quoted forward reference. A lambda's parameters carry
no annotation, so a lambda holds nothing but what its enclosing holder holds. A holder is
the top-level class or function of its module that the annotation sits in, so a method, a
nested function and a closure count toward the class or function that encloses them.
``Bound[X]`` (``orchestration.bound_stores.Bound``) is read as bound: it marks a parameter
handed a store :class:`BoundStores` gave for a sight, and is read as nothing else.
**A store under another name is read as the store**: an import under another name
(``from … import MemoryStore as Store``) and an alias anywhere in the package (``type
Store = MemoryStore``, ``Store: TypeAlias = …``, ``Store = MemoryStore``, an ``if
TYPE_CHECKING:`` block's included) whose value names a store unbound, imports and
aliases read together, so an alias of a renamed import or of another alias is one
too. An alias's own definition is a name for a shape, not a holder, and is not read as
one.

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

import ai_assistant
import ai_assistant.orchestration

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

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
    # §7:8: the hub chat's reader's intake, a sensor's finding of what is due (ADR-0293
    # §1:2): what waits (`untaken_messages`), its marking (`take_in`) and, at the engine's
    # start and each sweep, `notice_awaiting`. Its window reads through the holder (§7:9,
    # milestone 22's B8b).
    "chat.py:ChatReader": "§7:8",
    # §7:8: the line's reader's read of the chat's last activation before its first
    # poll, the engine's start's (`_after_restart`). Its window reads through the holder
    # (§7:9, B8b).
    "telegram.py:TelegramReader": "§7:8",
    # §7:12: called, it walks the store it holds for the observer's finding of what is
    # due, the window an episode must have left (ADR-0329 §7:1, §15:3); the windows
    # stage walks it bound (`walk`).
    "understanding.py:RecentEpisodes": "§7:12",
    # §7:8: the restart's close of the episodes a dead process left open, the engine's
    # start's (ADR-0286 §7), which ADR-0387 §7 leaves as it is.
    "activation_writer.py:OpenEpisodes": "§7:8",
    # §7:8: the person-model store handed to the zone picker the Task Scheduler sensor's
    # push reads. A work's block, pins and reads go through the holder (B8e), and the
    # owner's panel through `bound` blocks, the owner's sight's (ADR-0385 §3:1, B10f);
    # calls with no sight on blocks never bound are the canonical fake engine's alone.
    "person_block.py:PersonBlocks": "§7:8",
    # §7:8: removing finished tasks, `tidy` and `parent_ended` (ADR-0384 §2's table). A
    # work's task calls read through the holder (B8d), and the operations from outside,
    # the owner's own acts (ADR-0350 §10), through it by the sight handed them (B10f).
    "task_manager.py:TaskManager": "§7:8",
    # §7:8: `outside_a_work`, the Task Scheduler sensor's push of a due occurrence; `of`
    # reads by a work's sight (B8d) or the owner's (B10f).
    "task_rules.py:PersonZones": "§7:8",
    # §7:8: the line's reader's own reads, a sensor's, which no owner's act reaches: the
    # cards' edits after each poll and its first read after a start (`refresh`,
    # `_settle`), and a tap arriving on the line (`tap`), answered by the check. A work's
    # card is recorded through the plan store bound to its sight (`post`, B8d), and the
    # line's window reads the cards bound (`on_line`, B8b).
    "telegram.py:TelegramCards": "§7:8",
}

#: The holders that make ADR-0387 §3's writes of a work's own turn and answer its §4:2,
#: which §7:4 lets hold the conversation store unbound, each for those alone and handing
#: it to no stage. Each holds the conversation store and no other store unbound.
OWN_TURN_HOLDERS: Final[dict[str, str]] = {
    # §3:1: a message into one of the work's own places; every other place through the
    # store bound to its sight (§3:2).
    "chat.py:ChatWriter": "ADR-0387 §7:4",
    # §3:1: recording the turn; the episode is read and written bound (ADR-0383 §7:4).
    "activation_writer.py:ActivationWriter": "ADR-0387 §7:4",
    # §4:2: whether one of the work's own places stands; every other place bound (§4:3).
    "task_manager.py:PlaceLists": "ADR-0387 §7:4",
}

#: Holders not yet converted, each with the lane of milestone 22 that removes it (#3711):
#: B9 the observer's pin pass and the upcoming-event producer's writes, B10e the owner's
#: own acts on conversations (ADR-0385); B8b's windows, B8c's stories, B8d's authorizing,
#: acting, approvals and tasks, B8e's look-ups, person block and matters, B8f's writes of
#: a work's own turn, B9a's observer reads, B9b's upkeep runs and a tidy-up a work asks
#: for, B10b's owner's acts on memory and stories, and B10f's on notifications, the
#: profile, the approvals panel and tasks are converted, save the parts named here for a
#: later lane.
#: A holder more than one lane converts names the last of them. **Only shrinks.** A holder
#: whose last unbound read is one §7:8, §7:12 or §7:13 names moves to
#: :data:`NAMED_BY_THE_DECISION` in the lane that converts the rest: the observer's finding
#: of what is due (§7:12, §7:13), the engine's start and ADR-0384 §2's unchanged jobs
#: (§7:8).
NOT_YET_CONVERTED: Final[dict[str, str]] = {
    "change_stream.py:ChangeStream": "B10e",
    # The surface's acts (B10e); its sweeps are §7:8's. Its `begin`, which marks the
    # trigger's conversation active as a work's turn begins, is admitted by ADR-0387 §7:4.
    "conversations.py:ConversationLifecycle": "B10e",
    "conversations.py:conversation_state": "B10e",
    "conversations.py:episodes_on_place": "B10e",
    "conversations.py:_open_on": "B10e",
    "conversations.py:_shown_ending": "B10e",
    "conversations.py:_older_ending": "B10e",
    "conversations.py:_judged": "B10e",
    "conversations.py:_last_taker": "B10e",
    # Every lane from B8b to B10e converts a use; its start is §7:8's. The owner's acts on
    # memory and stories (B10b), and on notifications, the profile and the approvals panel
    # (B10f), read through the holder, bound to the owner's sight.
    "engine.py:Engine": "B10e",
    # The upcoming-event producer's writes (ADR-0132): it reads a source, not a store, so
    # ADR-0384 §2's table makes it no upkeep run, and no clause yet gives it a sight. It
    # reads the owner's zone from the person-model store and rules into the notification
    # store unbound, as the pin pass beside it awaits a decision (B9).
    "notifications.py:NotificationWriteStage": "B9",
    # The producer's zone pick, built by the write stage over its unbound person-model
    # store; the reconsideration picks through the store bound to its run's sight (B9b).
    "notifications.py:RulingPolicy": "B9",
    # The pin pass (ADR-0338 §9:6) reads every person's pins, tied to no one ended work,
    # so ADR-0383 §6:7 gives it no sight; it writes through a stage over the unbound
    # writer, which `writes.py:MemoryWriteStage` marks `Bound`.
    "observer/person.py:PinConfirmations": "B9",
    # Its runs read and write through the holder, bound to each episode's sight (B9a).
    # What it holds unbound: the finding of what is due (§7:12), the budget's figure
    # (§8:5), the pin pass's stores and write stage (B9), and the stores a holder is
    # built over where none is handed.
    "observer/stage.py:Observer": "B9",
}

_LANES: Final = frozenset({"B9", "B10e"})
_ROOT: Final = Path(ai_assistant.orchestration.__file__).parent


def _stores_named(annotation: ast.expr, names: frozenset[str] = STORES) -> Iterator[str]:
    """Each store ``annotation`` names unbound, by any of ``names``, a quoted one's included."""
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
    if isinstance(node, ast.Name) and node.id in names:
        yield node.id
    if isinstance(node, ast.Attribute) and node.attr in names:
        yield node.attr
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.expr):
            yield from _stores_named(child, names)


def _alias_values(tree: ast.Module) -> Iterator[tuple[str, ast.expr]]:
    """Each alias ``tree`` defines, by name, with what it names.

    A ``type`` statement and an assignment of one name, annotated (``TypeAlias``) or
    plain, wherever each sits: a conditional block's and a function's included; and each
    name an import gives another (``from … import MemoryStore as Store`` names
    ``MemoryStore``).
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
            yield node.name.id, node.value
        elif isinstance(node, ast.ImportFrom):
            for one in node.names:
                if one.asname is not None:
                    yield one.asname, ast.Name(id=one.name)
    for statement in ast.walk(tree):
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
        ):
            yield statement.target.id, statement.value
        elif isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            (target,) = statement.targets
            if isinstance(target, ast.Name):
                yield target.id, statement.value


def store_aliases(trees: Iterable[ast.Module]) -> frozenset[str]:
    """Every name a store is known by anywhere in ``trees``: its own, each alias whose
    value names one unbound, and each name one is imported under.

    Imports and aliases are read together to a fixed point, so an alias of a renamed
    import, a renamed import of an alias and an alias of an alias are each one. By name
    alone, which can only over-read: a name some module gives a store is read as one
    everywhere.
    """
    values = [one for tree in trees for one in _alias_values(tree)]
    names: frozenset[str] = STORES
    while True:
        grown = names | {name for name, value in values if any(_stores_named(value, names))}
        if grown == names:
            return names
        names = grown


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


def _parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def unbound_holders(root: Path = _ROOT) -> dict[str, frozenset[str]]:
    """Every holder under ``root`` that takes or holds a store unbound, with the stores.

    Keyed ``<module path>:<top-level name>``, the module path relative to ``root``.
    """
    found: dict[str, frozenset[str]] = {}
    modules = {
        path.relative_to(root).as_posix(): ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(root.rglob("*.py"))
    }
    # Aliases are read across the whole package, so one ``core`` or another subsystem
    # defines and ``orchestration`` imports is a store's name here too.
    package = Path(ai_assistant.__file__).parent
    aliases = store_aliases(
        (*modules.values(), *(_parsed(path) for path in sorted(package.rglob("*.py"))))
    )
    for module, tree in modules.items():
        names = aliases
        for top in tree.body:
            name = _holder(top)
            if name is None:
                continue
            stores = frozenset(
                store
                for node in ast.walk(top)
                for annotation in _annotations(node)
                for store in _stores_named(annotation, names)
            )
            if stores:
                found[f"{module}:{name}"] = stores
    return found


def test_no_holder_outside_the_lists_takes_or_holds_a_store_unbound() -> None:
    """§9:1: a stage holds the holder that gives a store only for a sight, never a store."""
    allowed = {THE_HOLDER, *NAMED_BY_THE_DECISION, *OWN_TURN_HOLDERS, *NOT_YET_CONVERTED}
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
        key
        for key in (THE_HOLDER, *NAMED_BY_THE_DECISION, *OWN_TURN_HOLDERS, *NOT_YET_CONVERTED)
        if key not in held
    )
    assert gone == [], "these hold no store unbound any more: take them off the list"


def test_every_unconverted_holder_names_a_lane_and_none_is_named_twice() -> None:
    assert set(NOT_YET_CONVERTED.values()) <= _LANES
    named = (set(NOT_YET_CONVERTED), set(NAMED_BY_THE_DECISION), set(OWN_TURN_HOLDERS))
    assert all(not one & other for one in named for other in named if one is not other)
    assert THE_HOLDER not in {*NOT_YET_CONVERTED, *OWN_TURN_HOLDERS}


def test_the_holders_of_a_works_own_turn_hold_the_conversation_store_alone() -> None:
    """ADR-0387 §7:4, §8: the chat writer, the episode writer and the place lists hold the
    conversation store unbound for a work's own turn alone; every other store they read
    is bound (B8f), and no other holder is admitted by that clause."""
    held = unbound_holders()
    assert {key: held.get(key) for key in OWN_TURN_HOLDERS} == dict.fromkeys(
        OWN_TURN_HOLDERS, frozenset({"ConversationStore"})
    )
    assert set(OWN_TURN_HOLDERS.values()) == {"ADR-0387 §7:4"}


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


def test_the_holders_b8e_converted_hold_no_store() -> None:
    """The look-ups, the person block's check and matters (milestone 22's B8e) read
    through the holder alone; ``PersonBlocks`` keeps the owner's panel's unbound reads."""
    held = unbound_holders()
    for converted in (
        "lookups.py:LookUps",
        "lookups.py:ConnectionSearch",
        "episode_lookups.py:EpisodeLookUpReads",
        "matters.py:Matters",
        "matter_calls.py:MatterCalls",
        "person_block.py:still_held",
        "person_calls.py:PersonModelCalls",
    ):
        assert converted not in held
        assert converted not in NOT_YET_CONVERTED


def test_the_holders_b8d_converted_hold_no_store() -> None:
    """A work's authorizing, acting, approval calls and the phases' own reads (milestone
    22's B8d) read through the holder alone."""
    held = unbound_holders()
    for converted in (
        "acting.py:ActingStage",
        "approval_calls.py:ApprovalCalls",
        "authorizer.py:AuthorizingStage",
        "phase_path.py:PhasePath",
    ):
        assert converted not in held
        assert converted not in NOT_YET_CONVERTED


#: The methods of each holder that keeps a store unbound for reads outside a work, which
#: alone may reach it (B8d): every other method is a work's, and reads through the holder.
_OUTSIDE_A_WORK: Final[dict[tuple[str, str], tuple[frozenset[str], frozenset[str]]]] = {
    # §7:8: removing finished tasks (ADR-0384 §2's table). The operations from outside
    # (ADR-0350 §10), the owner's own acts, read through the holder by the sight handed
    # them (B10f).
    ("task_manager.py", "TaskManager"): (
        frozenset({"_plans"}),
        frozenset({"__init__", "tidy", "parent_ended"}),
    ),
    # §7:8: the task sensor's push; the owner's replace reads `of` by its sight (B10f).
    ("task_rules.py", "PersonZones"): (
        frozenset({"_people"}),
        frozenset({"__init__", "outside_a_work"}),
    ),
}


def test_a_works_task_calls_reach_no_store_unbound() -> None:
    """§7:7: the Task Manager's and the zones' methods a work reaches read through the
    holder; the unbound store is reached only by the reads made outside a work (B8d)."""
    reaches: dict[str, list[str]] = {}
    for (module, holder), (attributes, outside) in _OUTSIDE_A_WORK.items():
        tree = _parsed(_ROOT / module)
        (cls,) = (one for one in tree.body if isinstance(one, ast.ClassDef) and one.name == holder)
        methods = {
            node.name: node
            for node in cls.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        assert outside <= set(methods), f"{holder} no longer has {sorted(outside - set(methods))}"
        reaches[f"{module}:{holder}"] = sorted(
            name
            for name, node in methods.items()
            if name not in outside
            and any(
                isinstance(inner, ast.Attribute)
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "self"
                and inner.attr in attributes
                for inner in ast.walk(node)
            )
        )
    assert reaches == {key: [] for key in reaches}


#: The stores a channel's reader holds unbound for its §7:8 reads, by the attribute each
#: is held under, which no read made for a work's window may reach (milestone 22's B8b).
_INTAKE_STORES: Final = frozenset({"_conversations", "_memory", "_plans"})

#: The methods that read a work's window, by module and class (§7:9).
_WINDOW_READS: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("chat.py", "ChatReader"): frozenset({"windowed", "_window", "_links", "_taken_in"}),
    ("telegram.py", "TelegramReader"): frozenset(
        {"windowed", "_window", "_episode_items", "_input_message", "_replied"}
    ),
    ("telegram.py", "TelegramCards"): frozenset({"on_line", "_posted_words"}),
}


def _unbound_reaches(path: Path, holder: str, methods: frozenset[str]) -> dict[str, set[str]]:
    """Each of ``methods`` of ``holder`` that reaches a store its class holds unbound."""
    tree = _parsed(path)
    (cls,) = (one for one in tree.body if isinstance(one, ast.ClassDef) and one.name == holder)
    found: dict[str, set[str]] = {}
    seen: set[str] = set()
    for node in cls.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or node.name not in methods:
            continue
        seen.add(node.name)
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Attribute)
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "self"
                and inner.attr in _INTAKE_STORES
            ):
                found.setdefault(node.name, set()).add(inner.attr)
    assert seen == methods, f"{holder} no longer has {sorted(methods - seen)}"
    return found


def test_the_channel_readers_read_a_works_window_through_the_holder_alone() -> None:
    """§7:9: the readers keep their intake unbound (§7:8), and their window reads reach no
    store but one the holder bound to the work's sight, handed in per read (B8b)."""
    reaches = {
        f"{module}:{holder}": _unbound_reaches(_ROOT / module, holder, methods)
        for (module, holder), methods in _WINDOW_READS.items()
    }
    assert reaches == {key: {} for key in reaches}


def test_the_story_stages_hold_no_store() -> None:
    """A work's story reads and story calls (milestone 22's B8c) read through the holder."""
    held = unbound_holders()
    for converted in (
        "story_links.py:StoryCandidates",
        "story_links.py:StoryLinksStage",
        "story_links.py:_Writes",
        "story_links.py:admitted_episodes",
        "phase_path.py:StoryReads",
        "story_calls.py:_Held",
    ):
        assert converted not in held
        assert converted not in NOT_YET_CONVERTED


def test_the_observer_s_reads_for_an_ended_work_hold_no_store() -> None:
    """The observer's reading, placement, writing and person reads, and the write stage
    (milestone 22's B9a), take the stores the holder binds to an episode's sight alone;
    the observer itself keeps the due-finding's, the budget's and the pin pass's."""
    held = unbound_holders()
    for converted in (
        "authorizer.py:read_outside_content",
        "observer/person.py:person_of",
        "observer/placement.py:compacted",
        "observer/placement.py:retrieved",
        "observer/reading.py:EpisodeReader",
        "observer/reading.py:_shown_notes",
        "observer/reading.py:_stories_to_search",
        "observer/reading.py:_story_notes",
        "observer/stage.py:_Seen",
        "observer/writing.py:FindingWriter",
        "writes.py:MemoryWriteStage",
    ):
        assert converted not in held
        assert converted not in NOT_YET_CONVERTED


def test_the_upkeep_runs_and_a_works_tidy_up_hold_no_store() -> None:
    """The matters pass, the scheduled tidy-up, the tidy-up itself, the readers of
    ``story_flags`` and the story calls (milestone 22's B9b) take the holder or a store it
    bound to a run's or a work's sight alone; the reconsideration reads through the engine's
    holder, and ``RulingPolicy`` keeps the upcoming-event producer's unbound store (B9)."""
    held = unbound_holders()
    for converted in (
        "matters_pass.py:MattersPass",
        "matters_pass.py:_apply",
        "matters_pass.py:_held_notes",
        "matters_pass.py:_members",
        "matters_pass.py:_settled",
        "story_calls.py:StoryCalls",
        "story_flags.py:read_headers",
        "story_flags.py:read_log",
        "story_flags.py:read_records",
        "story_flags.py:read_versions",
        "story_flags.py:recorded_decisions",
        "story_flags.py:reread",
        "story_tidy_up.py:ScheduledTidyUp",
        "story_tidy_up.py:StoryTidyUp",
        "story_tidy_up.py:_linked_at",
        "upkeep.py:UpkeepRun",
        "upkeep.py:upkeep_run",
    ):
        assert converted not in held
        assert converted not in NOT_YET_CONVERTED
    assert not any(lane == "B9b" for lane in NOT_YET_CONVERTED.values())


def test_the_helpers_of_the_owners_acts_on_memory_and_stories_hold_no_store() -> None:
    """The story surface's checks and views, where a matter stands and the pending
    candidates (milestone 22's B10b) take stores the holder bound to a sight alone: the
    owner's act's (ADR-0385 §3:1) or a work's (ADR-0383 §7:7). No holder is left to B10,
    and what is left of the owner's acts is B10e's."""
    held = unbound_holders()
    for converted in (
        "candidates.py:pending_candidates",
        "candidates.py:held_candidates",
        "candidates.py:_page_candidates",
        "candidates.py:_approved_candidates",
        "stories.py:unknown_activation",
        "stories.py:of_another_home",
        "stories.py:resolved_view",
        "stories.py:owner_summary",
        "stories.py:_all_notes",
        "story_standing.py:story_standing",
        "story_standing.py:_shown",
        "story_standing.py:_done",
        "story_standing.py:_related",
        "story_standing.py:_member_count",
    ):
        assert converted not in held
        assert converted not in NOT_YET_CONVERTED
    assert "B10" not in NOT_YET_CONVERTED.values()


def test_the_owners_acts_on_notifications_the_profile_approvals_and_tasks_hold_no_store() -> None:
    """The written preferences, the approvals panel's read, tap and card facts (milestone
    22's B10f) take stores the holder bound to the owner's sight alone (ADR-0385 §3:1);
    the person block, the Task Manager, the zones and the line's cards keep only §7:8's."""
    held = unbound_holders()
    for converted in (
        "engine.py:_written_preferences",
        "engine.py:approval_panel",
        "engine.py:episode_card_facts",
        "engine.py:tap_on_approval_panel",
    ):
        assert converted not in held
        assert converted not in NOT_YET_CONVERTED
    for left in (
        "person_block.py:PersonBlocks",
        "task_manager.py:TaskManager",
        "task_rules.py:PersonZones",
        "telegram.py:TelegramCards",
    ):
        assert NAMED_BY_THE_DECISION[left] == "§7:8"
    assert held["task_manager.py:TaskManager"] == frozenset({"PlanStore"})


def test_the_reading_sees_every_shape_a_store_is_held_in(tmp_path: Path) -> None:
    """The scan reads a union, a container, a quoted name, a field, a return, a nested
    function, a store imported under another name and an alias of one; it reads
    ``Bound[...]``, and a ``type`` alias's own definition, as nothing."""
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
from ai_assistant.core.protocols import MemoryStore as Store
type Kept = StoryStore
Plain = PlanStore
class Renamed:
    def __init__(self, memory: Store, stories: Kept, plans: list[Plain]) -> None: ...
from ai_assistant.core.protocols import ConversationStore as ImportedChat
type AliasedChat = ImportedChat
if TYPE_CHECKING:
    from ai_assistant.core.protocols import NotificationStore as Held
    Notes: TypeAlias = Held
class Chained:
    def __init__(self, chat: AliasedChat, notes: Notes) -> None: ...
def local() -> None:
    Local = PersonModelStore
    def inner(people: Local) -> None: ...
"""
    (tmp_path / "held.py").write_text(source, encoding="utf-8")
    assert unbound_holders(tmp_path) == {
        "held.py:Field": frozenset({"StoryStore"}),
        "held.py:Attribute": frozenset({"PlanStore"}),
        "held.py:many": frozenset({"ConversationStore"}),
        "held.py:gives": frozenset({"NotificationStore"}),
        "held.py:Closes": frozenset({"MemoryWriter"}),
        "held.py:handed": frozenset({"PersonModelStore"}),
        "held.py:walks": frozenset({"Walk"}),
        "held.py:Renamed": frozenset({"Store", "Kept", "Plain"}),
        "held.py:Chained": frozenset({"AliasedChat", "Notes"}),
        "held.py:local": frozenset({"Local"}),
    }
