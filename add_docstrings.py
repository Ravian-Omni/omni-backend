#!/usr/bin/env python3
"""Script to add Google-style docstrings to Python files.

This script analyzes Python files and generates documentation templates
for functions and classes that are missing docstrings.
"""

import ast
import sys
from pathlib import Path
from typing import List


class DocstringChecker(ast.NodeVisitor):
    """Check Python files for missing docstrings.

    Attributes:
        missing: List of nodes missing docstrings.
        filename: Name of the file being checked.
    """

    def __init__(self, filename: str):
        """Initialize the docstring checker.

        Args:
            filename: Path to the file being checked.
        """
        self.missing: List[tuple] = []
        self.filename = filename

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definition nodes.

        Args:
            node: AST node for the function definition.
        """
        if not ast.get_docstring(node):
            self.missing.append(("function", node.name, node.lineno))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit async function definition nodes.

        Args:
            node: AST node for the async function definition.
        """
        if not ast.get_docstring(node):
            self.missing.append(("async function", node.name, node.lineno))
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit class definition nodes.

        Args:
            node: AST node for the class definition.
        """
        if not ast.get_docstring(node):
            self.missing.append(("class", node.name, node.lineno))
        self.generic_visit(node)


def check_file(filepath: Path) -> List[tuple]:
    """Check a single Python file for missing docstrings.

    Args:
        filepath: Path to the Python file.

    Returns:
        List of tuples (type, name, lineno) for missing docstrings.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(filepath))

        # Check module docstring
        missing = []
        if not ast.get_docstring(tree):
            missing.append(("module", filepath.name, 1))

        # Check functions and classes
        checker = DocstringChecker(str(filepath))
        checker.visit(tree)
        missing.extend(checker.missing)

        return missing
    except Exception as e:
        print(f"Error checking {filepath}: {e}")
        return []


def main():
    """Main entry point for the docstring checker."""
    src_dir = Path("src")
    if not src_dir.exists():
        print("src/ directory not found")
        return

    all_missing = []
    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        missing = check_file(py_file)
        if missing:
            all_missing.append((py_file, missing))

    if all_missing:
        print("\n=== Missing Docstrings ===\n")
        for filepath, missing in all_missing:
            print(f"\n{filepath}:")
            for item_type, name, lineno in missing:
                print(f"  Line {lineno}: {item_type} '{name}'")

        print(f"\nTotal files with missing docstrings: {len(all_missing)}")
    else:
        print("All files have docstrings!")


if __name__ == "__main__":
    main()
