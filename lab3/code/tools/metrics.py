"""Count application source separately from tests, tooling, blanks, and docs."""

import ast
import io
import json
import tokenize
from pathlib import Path


def file_metrics(path):
    """Return reproducible physical line counts, not GUI-generated-code totals."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text)
    doc_lines = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                docstring = node.body[0]
                doc_lines.update(range(docstring.lineno, docstring.end_lineno + 1))
    comment_lines = set()
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            index = token.start[0]
            if lines[index - 1].lstrip().startswith("#"):
                comment_lines.add(index)
    counted = sum(
        bool(line.strip()) and index not in doc_lines | comment_lines
        for index, line in enumerate(lines, 1)
    )
    return {
        "file": path.name,
        "physical": len(lines),
        "nonblank": sum(bool(x.strip()) for x in lines),
        "excluding_blank_comment_docstring": counted,
    }


def main():
    root = Path(__file__).resolve().parents[1]
    files = [file_metrics(path) for path in sorted((root / "campus_market").glob("*.py"))]
    runtime_files = [item for item in files if item["file"] != "demo.py"]
    counted = sum(item["excluding_blank_comment_docstring"] for item in runtime_files)
    print(
        json.dumps(
            {
                "scope": "campus_market/*.py excluding demo.py; excludes tests, tools, UML, build artifacts",
                "method": "physical lines minus blanks, comment-only lines, and AST docstrings; includes embedded SQL",
                "files": files,
                "physical_total": sum(item["physical"] for item in runtime_files),
                "source_total": counted,
                "requirement_gt_1500": counted > 1500,
                "gui_generated_lines": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if counted <= 1500:
        raise SystemExit("Application source does not meet the coursework size requirement")


if __name__ == "__main__":
    main()
