"""The scrub list, read as data and never run (40-BREADTH.md step 9; 3c's judgment, F1).

The companions' publisher (`deploy/privatecloudarchitect/companion/publish.py`) holds the estate identifiers that must
never reach a public page as `KILL_LIST`, a compiled regular expression, and the values spared as `KILLLIST_ALLOW`. The
gates once imported that module to read the two; a module import runs the file's top-level code, which the adopter's
companion must never do with a file it is passed (the open-audit rule), so the list is read with `ast` instead: the
pattern as a string literal with its named flags, the allowed values as a literal tuple. An adopter passes its own
list as a `.yaml` holding `kill` and `allow`. This module imports no renderer and reads no clock, so the drift loader
can use it to guard a line (drift.guard_lines).
"""

from __future__ import annotations

import ast
import re
from functools import lru_cache
from pathlib import Path

import yaml

LAYER = Path(__file__).resolve().parent.parent
ROOT = LAYER.parents[2]
KILL_LIST_PATH = ROOT / "deploy" / "privatecloudarchitect" / "companion" / "publish.py"

Lists = tuple[re.Pattern, tuple[str, ...]]


def _string_literal(node: ast.AST) -> str | None:
    """The text of a string literal, or of a concatenation of string literals (`"a" "b"` or `"a" + "b"`); None for
    anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _string_literal(node.left), _string_literal(node.right)
        return None if left is None or right is None else left + right
    return None


def _compiled(node: ast.AST) -> re.Pattern | None:
    """A `re.compile(<string literal>, re.FLAG | ...)` call read as data: the pattern and its named flags, nothing run."""
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "compile"
    ):
        return None
    if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "re") or not node.args:
        return None
    pattern = _string_literal(node.args[0])
    if pattern is None:
        return None
    flags = 0
    for extra in [*node.args[1:], *[k.value for k in node.keywords]]:
        for leaf in ast.walk(extra):
            if (
                isinstance(leaf, ast.Attribute)
                and isinstance(leaf.value, ast.Name)
                and leaf.value.id == "re"
            ):
                flag = getattr(re, leaf.attr, None)
                if not isinstance(flag, re.RegexFlag):
                    return None
                flags |= flag
            elif not isinstance(leaf, ast.BinOp | ast.BitOr | ast.Attribute | ast.Name | ast.Load):
                return None
    return re.compile(pattern, flags)


def kill_list_from(path: Path) -> Lists:
    """The scrub list read from a file as data, never run: a `.py` holding `KILL_LIST = re.compile(<string literal>,
    <re flags>)` and `KILLLIST_ALLOW = (<string literals>)`, read with `ast`; or a `.yaml` holding `kill` (a regular
    expression, matched without regard to case) and `allow` (a list of values spared). A file in neither form, or whose
    two values are not literals, is refused by name."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        kill = allow = None
        for node in ast.parse(text).body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                if node.targets[0].id == "KILL_LIST":
                    kill = _compiled(node.value)
                elif node.targets[0].id == "KILLLIST_ALLOW":
                    try:
                        value = ast.literal_eval(node.value)
                    except ValueError:
                        value = None
                    if isinstance(value, tuple | list) and all(isinstance(v, str) for v in value):
                        allow = tuple(value)
        if kill is None or allow is None:
            raise ValueError(
                f"{path}: KILL_LIST must be re.compile of a string literal and KILLLIST_ALLOW a tuple of string "
                "literals; neither is run"
            )
        return kill, allow
    if path.suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("kill"), str)
            or not isinstance(data.get("allow"), list)
            or not all(isinstance(v, str) for v in data["allow"])
        ):
            raise ValueError(
                f"{path}: a scrub list holds `kill` (a regular expression) and `allow` (a list of values)"
            )
        return re.compile(data["kill"], re.IGNORECASE), tuple(data["allow"])
    raise ValueError(
        f"{path}: a scrub list is a .py holding KILL_LIST and KILLLIST_ALLOW, or a .yaml holding kill and allow"
    )


@lru_cache(maxsize=8)
def default(path: Path | None = None) -> Lists:
    """The publisher's list, read as data; or the list at a passed path, cached by path."""
    return kill_list_from(path or KILL_LIST_PATH)


def caught(text: str, lists: Lists | None = None) -> int:
    """How many estate identifiers the list finds in a text, its allowed values spared; never which."""
    kill, allow = lists or default()
    for a in allow:
        text = text.replace(a, "")
    return len(kill.findall(text))
