"""The form a model call's instruction is written in, and nothing that reads a file (ADR-0334).

Each prompt's instruction is a template file shipped beside the module that sends it,
which the owner's hub may replace with a file of its data directory (§3). Reading those
files is the composition root's (§3:5); what a template *is* — how it is parsed,
checked against what its prompt declares, versioned and rendered — is here, once, so
that ``orchestration`` and ``memory`` render templates without importing each other. It
does no I/O: :meth:`PromptTemplate.parse` takes the file's bytes.

**The form** (§4:1). A template is UTF-8 text. ``$name`` or ``${name}`` is replaced by
the value of that name, and ``$$`` by one ``$``. A line holding only ``$if name``,
``$if not name``, ``$else`` or ``$end`` opens, divides or closes a block, which is
included where the flag's value says; blocks nest. Nothing else is interpreted.

**What a line is.** A line break ends a line, and the rendered text is the included
lines joined by line breaks, so a template's final line break is no part of what is
sent: the file's last line ends the text whether or not an editor added one. A directive
line is removed whole, its line break with it.

**Flags and values are the code's** (§4:2, §4:3). A prompt declares the closed set of
flags and values its template may name (:class:`PromptDeclaration`); a template may name
fewer and never one it does not declare. A flag stands only in a directive and a value
only in a substitution, so a template neither prints a condition nor branches on text
the code supplies. :meth:`PromptTemplate.render` takes every declared flag and value,
and no other, so a call cannot leave one for the template to guess.

**A defect names its line and never the text** (§5:1, §5:2). An override is Tier 1, and
the refusal that names its defect is logged, so no message here quotes what a line
holds — not even the name it got wrong.

**The version** (§8:1) is the first twelve hexadecimal digits of the SHA-256 of the
file's bytes, whether the file is a default or an override.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Never

from ai_assistant.core.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "PROMPT_OVERRIDE_DIRECTORY",
    "PromptDeclaration",
    "PromptOrigin",
    "PromptTemplate",
]

#: The directory of ``Settings.data_dir`` an override is read from (§3:3).
PROMPT_OVERRIDE_DIRECTORY: Final = "prompts"

#: How a template file is named, default or override: ``<name>.txt`` (§3:3).
_SUFFIX: Final = ".txt"

#: How many hexadecimal digits of the file's SHA-256 a version keeps (§8:1).
_VERSION_DIGITS: Final = 12

#: A flag's or a value's name, and a prompt's.
_NAME: Final = r"[A-Za-z_][A-Za-z0-9_]*"
_NAME_PATTERN: Final = re.compile(_NAME)

#: The words a directive is spelled with, which no flag or value may be named.
_DIRECTIVE_WORDS: Final = frozenset({"if", "else", "end"})

_IF: Final = re.compile(rf"\$if (not )?({_NAME})")
_ELSE: Final = "$else"
_END: Final = "$end"

#: One ``$`` and what follows it on a text line: ``$$``, ``$name``, ``${name}``, or none
#: of them, which is a defect.
_DOLLAR: Final = re.compile(rf"\$(?:(\$)|({_NAME})|\{{({_NAME})\}})?")


class PromptOrigin(StrEnum):
    """Where a template's text came from (§8:2)."""

    DEFAULT = "default"
    OVERRIDE = "override"


@dataclass(frozen=True, slots=True)
class PromptDeclaration:
    """One prompt: its name, where its default ships, and what its template may name.

    Declared in the module that sends the prompt (ADR-0334 §2:1), and read by the
    composition root, which loads the default and any override against it (§3:5).

    Attributes:
        name: The prompt's name, §2's first column, which also names its file.
        package: The package its default ships in, beside the module that sends it
            (§3:1), as :func:`importlib.resources.files` takes it.
        flags: The conditions the code computes for a call, which a template may
            branch on.
        values: The text the code owns, which a template may print.
    """

    name: str
    package: str
    flags: frozenset[str] = frozenset()
    values: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Refuse a declaration no template could be checked against.

        Raises:
            ValueError: If a name is not an identifier, is a directive's word, or is
                declared as both a flag and a value.
        """
        for one in (self.name, *self.flags, *self.values):
            if not _NAME_PATTERN.fullmatch(one) or one in _DIRECTIVE_WORDS:
                msg = f"{one!r} cannot name a prompt, a flag or a value (ADR-0334 §4:1)"
                raise ValueError(msg)
        if self.flags & self.values:
            msg = f"the prompt {self.name} declares a name as both a flag and a value"
            raise ValueError(msg)

    @property
    def filename(self) -> str:
        """The template file's name, default and override alike: ``<name>.txt``."""
        return f"{self.name}{_SUFFIX}"


@dataclass(frozen=True, slots=True)
class _Value:
    """A substitution: the value of ``name``, supplied by the code."""

    name: str


#: One text line: its literal runs and its substitutions, in order.
type _Line = tuple[str | _Value, ...]


@dataclass(frozen=True, slots=True)
class _Block:
    """A conditional block: ``then`` where the flag's value is ``wanted``, else ``otherwise``."""

    flag: str
    wanted: bool
    then: tuple[_Node, ...]
    otherwise: tuple[_Node, ...]


type _Node = _Line | _Block


@dataclass(slots=True)
class _Open:
    """A block being parsed: its directive's line, and the lines read so far."""

    line: int
    flag: str
    wanted: bool
    then: list[_Node]
    otherwise: list[_Node] | None = None

    def body(self) -> list[_Node]:
        """Where the next node goes: the ``$else`` half once one was read."""
        return self.then if self.otherwise is None else self.otherwise


class PromptTemplate:
    """One prompt's template, parsed and checked against its declaration (§4).

    Built only by :meth:`parse`, which refuses a template that names what its prompt
    does not declare, leaves a block unbalanced, or holds a ``$`` of no form (§5:1).
    """

    __slots__ = ("_nodes", "declaration", "origin", "version")

    def __init__(
        self,
        declaration: PromptDeclaration,
        nodes: tuple[_Node, ...],
        *,
        version: str,
        origin: PromptOrigin,
    ) -> None:
        """Hold a parsed template; use :meth:`parse` to build one."""
        self.declaration = declaration
        self.version = version
        self.origin = origin
        self._nodes = nodes

    @property
    def name(self) -> str:
        """The prompt's name (§2)."""
        return self.declaration.name

    def provenance(self) -> dict[str, str]:
        """The ``prompt`` key a given entry carries (§8:2): name, version and origin."""
        return {"name": self.name, "version": self.version, "origin": self.origin.value}

    @classmethod
    def parse(
        cls, declaration: PromptDeclaration, data: bytes, *, origin: PromptOrigin
    ) -> PromptTemplate:
        """Parse a template file's bytes against what its prompt declares.

        Args:
            declaration: The prompt the file is the template of.
            data: The file's bytes, exactly as read.
            origin: Whether the file is the shipped default or an override.

        Returns:
            The template, versioned from ``data``.

        Raises:
            ConfigurationError: Naming the defect and its line, never the text: the
                bytes are not UTF-8 or hold only whitespace; a line names a flag or a
                value the prompt does not declare, a value where a flag belongs or a
                flag where a value belongs; a block is left unbalanced; or a ``$`` is
                none of the form's (§5:1).
        """
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            msg = "is not UTF-8"
            raise ConfigurationError(msg) from None
        if not text.strip():
            msg = "holds only whitespace"
            raise ConfigurationError(msg)
        lines = text.split("\n")
        if lines[-1] == "":
            lines.pop()
        nodes = _Parser(declaration).parse(lines)
        version = hashlib.sha256(data).hexdigest()[:_VERSION_DIGITS]
        return cls(declaration, nodes, version=version, origin=origin)

    def render(
        self, *, flags: Mapping[str, bool] | None = None, values: Mapping[str, str] | None = None
    ) -> str:
        """The instruction this template gives under ``flags``, with ``values`` printed.

        Args:
            flags: Every flag the prompt declares, as the code computed it for this call.
            values: Every value the prompt declares, as the code supplies it.

        Returns:
            The included lines, joined by line breaks.

        Raises:
            ValueError: If ``flags`` or ``values`` is not exactly what the prompt
                declares: the code supplies every one (§4:2).
        """
        given_flags = dict(flags or {})
        given_values = dict(values or {})
        if set(given_flags) != self.declaration.flags:
            msg = f"the prompt {self.name} is rendered with exactly the flags it declares"
            raise ValueError(msg)
        if set(given_values) != self.declaration.values:
            msg = f"the prompt {self.name} is rendered with exactly the values it declares"
            raise ValueError(msg)
        out: list[str] = []
        _emit(self._nodes, given_flags, given_values, out)
        return "\n".join(out)


def _emit(
    nodes: tuple[_Node, ...], flags: Mapping[str, bool], values: Mapping[str, str], out: list[str]
) -> None:
    """Append the text lines ``nodes`` include under ``flags``, values printed."""
    for node in nodes:
        if isinstance(node, _Block):
            chosen = node.then if flags[node.flag] is node.wanted else node.otherwise
            _emit(chosen, flags, values, out)
        else:
            out.append(
                "".join(values[one.name] if isinstance(one, _Value) else one for one in node)
            )


class _Parser:
    """One template's lines into nodes, against one declaration."""

    def __init__(self, declaration: PromptDeclaration) -> None:
        self._declaration = declaration

    def parse(self, lines: list[str]) -> tuple[_Node, ...]:
        """The template's nodes.

        Raises:
            ConfigurationError: At the first defect, naming its line.
        """
        top: list[_Node] = []
        stack: list[_Open] = []
        for number, line in enumerate(lines, start=1):
            body = stack[-1].body() if stack else top
            opened = _IF.fullmatch(line)
            if opened is not None:
                flag = opened.group(2)
                self._check_flag(flag, number)
                stack.append(_Open(number, flag, wanted=opened.group(1) is None, then=[]))
            elif line == _ELSE:
                if not stack:
                    _defect(number, "an $else stands in no block, so the blocks are unbalanced")
                if stack[-1].otherwise is not None:
                    _defect(number, "a second $else in one block leaves it unbalanced")
                stack[-1].otherwise = []
            elif line == _END:
                if not stack:
                    _defect(number, "an $end closes no block, so the blocks are unbalanced")
                closed = stack.pop()
                (stack[-1].body() if stack else top).append(
                    _Block(
                        flag=closed.flag,
                        wanted=closed.wanted,
                        then=tuple(closed.then),
                        otherwise=tuple(closed.otherwise or ()),
                    )
                )
            else:
                body.append(self._text_line(line, number))
        if stack:
            _defect(stack[-1].line, "a block opened here is never closed")
        return tuple(top)

    def _check_flag(self, name: str, number: int) -> None:
        if name in self._declaration.values:
            _defect(number, "a block names a value where only a flag may stand")
        if name not in self._declaration.flags:
            _defect(number, "a block names a flag its prompt does not declare")

    def _text_line(self, line: str, number: int) -> _Line:
        parts: list[str | _Value] = []
        literal: list[str] = []
        at = 0
        for found in _DOLLAR.finditer(line):
            literal.append(line[at : found.start()])
            at = found.end()
            escaped, bare, braced = found.groups()
            if escaped is not None:
                literal.append("$")
                continue
            name = bare or braced
            if name is None:
                _defect(number, "a $ is none of $$, $name, ${name} or a block's line")
            if name in self._declaration.flags:
                _defect(number, "a flag is printed where only a value may stand")
            if name not in self._declaration.values:
                _defect(number, "names a flag or value its prompt does not declare")
            parts.extend(("".join(literal), _Value(name)))
            literal.clear()
        literal.append(line[at:])
        parts.append("".join(literal))
        return tuple(part for part in parts if part != "")


def _defect(number: int, what: str) -> Never:
    """Refuse the template at line ``number``, saying what is wrong and quoting nothing."""
    msg = f"line {number}: {what}"
    raise ConfigurationError(msg)
