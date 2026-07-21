#!/usr/bin/env python3
"""Generate Code Reference pages for the Jekyll site from source.

Python is parsed with the standard `ast` module (module / class / function
docstrings, signatures). JavaScript is scanned for JSDoc (`/** ... */`) blocks
and the declaration that follows them. Nothing is imported or executed, so this
is safe to run against code that has external dependencies.

The generated Markdown carries just-the-docs front matter so the pages slot into
the "Code Reference" section. Run this before the Jekyll build (locally now, in
CI later); GitHub Pages cannot run it itself (safe mode forbids plugins).

Usage:  python3 docs/_tools/gen_code_docs.py [REPO_ROOT]
"""

from __future__ import annotations
import ast
import re
import sys
from pathlib import Path

# --- what to document: (title, output slug, nav_order, [source globs]) --------
GROUPS = [
    ("Backend · engine", "backend-engine", 1, ["backend/engine/*.py"]),
    ("Backend · API",    "backend-api",    2, ["backend/app.py"]),
    ("Frontend · lib",   "frontend-lib",   3, ["frontend/src/lib/*.js"]),
]

PARENT = "Code Reference"


# ---------------------------------------------------------------- Python -----
def py_signature(node: ast.AST) -> str:
    a = node.args
    parts: list[str] = []
    posonly = getattr(a, "posonlyargs", [])
    defaults = list(a.defaults)
    pos = posonly + a.args
    pad = len(pos) - len(defaults)
    for i, arg in enumerate(pos):
        s = arg.arg
        if arg.annotation is not None:
            s += ": " + ast.unparse(arg.annotation)
        di = i - pad
        if di >= 0:
            s += " = " + ast.unparse(defaults[di])
        parts.append(s)
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    for i, arg in enumerate(a.kwonlyargs):
        s = arg.arg
        d = a.kw_defaults[i]
        if d is not None:
            s += " = " + ast.unparse(d)
        parts.append(s)
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    return "(" + ", ".join(parts) + ")"


def py_file_md(path: Path, rel: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = [f"### `{rel}`\n"]
    mod = ast.get_docstring(tree)
    if mod:
        out.append(mod.strip() + "\n")

    def emit_fn(node, prefix=""):
        sig = py_signature(node)
        kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        out.append(f"#### `{prefix}{node.name}{sig}`\n")
        doc = ast.get_docstring(node)
        out.append((doc.strip() if doc else "_No description yet._") + "\n")

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            emit_fn(node)
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            out.append(f"#### `class {node.name}" + (f"({bases})" if bases else "") + "`\n")
            cdoc = ast.get_docstring(node)
            out.append((cdoc.strip() if cdoc else "_No description yet._") + "\n")
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    emit_fn(m, prefix=f"{node.name}.")
    return "\n".join(out)


# ------------------------------------------------------------------- JS -------
JSDOC = re.compile(r"/\*\*(.*?)\*/\s*\n\s*([^\n{;]+)", re.S)
DECL = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?"
    r"(?:(?:function\s+(?P<fn>\w+))|(?:class\s+(?P<cls>\w+))|"
    r"(?:const|let|var)\s+(?P<var>\w+)\s*=)"
)


def clean_jsdoc(block: str) -> str:
    lines = []
    for ln in block.strip().splitlines():
        lines.append(re.sub(r"^\s*\*?\s?", "", ln))
    return "\n".join(lines).strip()


def js_file_md(path: Path, rel: str) -> str:
    text = path.read_text(encoding="utf-8")
    out = [f"### `{rel}`\n"]
    # leading file-level block comment as a module description
    head = re.match(r"\s*/\*\*?(.*?)\*/", text, re.S) or re.match(r"\s*//.*", text)
    if head and head.re.pattern.startswith(r"\s*/\*"):
        out.append(clean_jsdoc(head.group(1)) + "\n")

    documented = []
    for m in JSDOC.finditer(text):
        decl = m.group(2).strip()
        dm = DECL.match(decl)
        name = dm and (dm.group("fn") or dm.group("cls") or dm.group("var"))
        if not name:
            continue
        documented.append(name)
        out.append(f"#### `{decl.rstrip('{( ')}`\n")
        out.append(clean_jsdoc(m.group(1)) + "\n")

    # list remaining exported declarations that had no JSDoc yet
    surface = []
    for m in re.finditer(r"^\s*export\s+(?:async\s+)?(?:function|class|const|let|var)\s+(\w+)",
                         text, re.M):
        if m.group(1) not in documented:
            surface.append(m.group(1))
    if surface:
        out.append("**Exports without documentation yet:** " +
                   ", ".join(f"`{s}`" for s in dict.fromkeys(surface)) + "\n")
    return "\n".join(out)


# ----------------------------------------------------------------- driver -----
def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    out_dir = root / "docs" / "code"
    out_dir.mkdir(parents=True, exist_ok=True)

    for title, slug, order, globs in GROUPS:
        files: list[Path] = []
        for g in globs:
            files.extend(sorted(root.glob(g)))
        body = []
        for f in files:
            rel = f.relative_to(root).as_posix()
            try:
                body.append(py_file_md(f, rel) if f.suffix == ".py" else js_file_md(f, rel))
            except Exception as ex:  # never let one file break the build
                body.append(f"### `{rel}`\n\n_Could not parse: {ex}_\n")
        page = (
            "---\n"
            f"title: {title}\n"
            f"parent: {PARENT}\n"
            f"nav_order: {order}\n"
            "---\n\n"
            f"# {title}\n\n"
            "*Generated from source by `docs/_tools/gen_code_docs.py`. "
            "Edit the docstrings in the code, then re-run the generator.*\n\n"
            + "\n---\n\n".join(body)
        )
        (out_dir / f"{slug}.md").write_text(page, encoding="utf-8")
        print(f"wrote docs/code/{slug}.md  ({len(files)} file(s))")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
