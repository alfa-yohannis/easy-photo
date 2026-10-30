"""Checks two rules of this project on every Python file of the app and its tests.

1. No nested calls: a call never has another call inside its arguments, so
   every intermediate result gets a name. Calls inside lambda bodies do not
   count, because the lambda is only defined there, not run.
2. Every module, class, function and method has a docstring.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_FOLDER = Path(__file__).resolve().parents[1]
CHECKED_FOLDERS = [APP_FOLDER / "src" / "easy_photo", APP_FOLDER / "tests"]


class NestedCallFinder(ast.NodeVisitor):
    """Collects the line numbers of calls that have another call inside their arguments."""

    def __init__(self) -> None:
        """Start with no findings."""
        self.lines: list[int] = []

    def visit_Call(self, node: ast.Call) -> None:
        """Look at the arguments of one call, then at the calls inside it.

        Args:
            node: The call.
        """
        arguments = list(node.args)
        for keyword in node.keywords:
            arguments.append(keyword.value)
        for argument in arguments:
            if self._contains_call(argument):
                self.lines.append(node.lineno)
                break
        self.generic_visit(node)

    def _contains_call(self, node: ast.AST) -> bool:
        """Tell whether an expression contains a call outside lambda bodies.

        Args:
            node: The expression.

        Returns:
            True when a call is found.
        """
        waiting = [node]
        while waiting:
            current = waiting.pop()
            if isinstance(current, ast.Call):
                return True
            if isinstance(current, ast.Lambda):
                continue
            children = ast.iter_child_nodes(current)
            waiting.extend(children)
        return False


def python_files() -> list[Path]:
    """All Python files that the rules apply to.

    Returns:
        The files, sorted.
    """
    files: list[Path] = []
    for folder in CHECKED_FOLDERS:
        found = folder.rglob("*.py")
        files.extend(found)
    files.sort()
    return files


def parse(path: Path) -> ast.Module:
    """Read and parse one Python file.

    Args:
        path: The file.

    Returns:
        Its syntax tree.
    """
    text = path.read_text(encoding="utf-8")
    file_name = str(path)
    return ast.parse(text, filename=file_name)


def test_there_are_files_to_check() -> None:
    """The rules must look at the real source folder, not an empty one."""
    files = python_files()
    assert len(files) > 20


def test_no_nested_calls() -> None:
    """No call has another call inside its arguments."""
    problems: list[str] = []
    for path in python_files():
        tree = parse(path)
        finder = NestedCallFinder()
        finder.visit(tree)
        relative = path.relative_to(APP_FOLDER)
        problems.extend(f"{relative}:{line}" for line in finder.lines)
    assert problems == []


def test_every_definition_has_a_docstring() -> None:
    """Every module, class, function and method has a docstring."""
    missing: list[str] = []
    for path in python_files():
        tree = parse(path)
        relative = path.relative_to(APP_FOLDER)
        if ast.get_docstring(tree) is None:
            missing.append(f"{relative} (module)")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if ast.get_docstring(node) is None:
                    missing.append(f"{relative}:{node.lineno} {node.name}")
    assert missing == []
