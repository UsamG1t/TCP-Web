#!/usr/bin/env python3
"""Generate Code Reference pages for the Jekyll site from source.

Three source languages are handled:

- **Python** — parsed with the standard `ast` module; module, class and function
  docstrings are extracted along with real signatures.
- **JavaScript** — scanned for JSDoc (`/** ... */`) blocks and the declaration
  that follows each one. Tags such as `@param` and `@returns` are rendered as
  Markdown rather than dumped verbatim.
- **Svelte** — the `<!-- @component -->` comment becomes the component's
  description, `export let` declarations are listed as props, and the `<script>`
  block is then processed as JavaScript.

Nothing is imported or executed, so this is safe to run against code with
external dependencies and against components that need a browser.

Run it before the Jekyll build (locally now, in CI later); GitHub Pages cannot
run it itself, since its native build forbids plugins.

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
    ("Backend · API", "backend-api", 2, ["backend/app.py"]),
    ("Frontend · lib", "frontend-lib", 3,
     ["frontend/src/lib/*.js", "frontend/src/main.js"]),
    ("Frontend · components", "frontend-components", 4,
     ["frontend/src/App.svelte", "frontend/src/components/*.svelte"]),
]

PARENT = "Code Reference"


# ---------------------------------------------------------------- Python -----
def py_signature(node: ast.AST) -> str:
    """Rebuild a function's parameter list from the syntax tree."""
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
    """Render one Python module as a Markdown section."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = [f"### `{rel}`\n"]
    mod = ast.get_docstring(tree)
    if mod:
        out.append(mod.strip() + "\n")

    def emit_fn(node, prefix=""):
        sig = py_signature(node)
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


# ------------------------------------------------------------ JSDoc parsing --
JSDOC_BLOCK = re.compile(r"/\*\*(.*?)\*/", re.S)

DECL = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:"
    r"function\s+(?P<fn>[\w$]+)"
    r"|class\s+(?P<cls>[\w$]+)"
    r"|(?:const|let|var)\s+(?P<var>[\w$]+)"
    r"|(?P<method>[\w$]+)\s*\("
    r")"
)

TAG_LINE = re.compile(r"^\s*@(\w+)\s*(.*)$")
# name description — name may be [optional] or [optional=default]
TAG_REST = re.compile(r"^(?P<name>\[[^\]]+\]|[\w$.]+)?\s*-?\s*(?P<desc>.*)$", re.S)


def split_type(value: str):
    """Peel a leading `{Type}` off a tag's text.

    Brace counting rather than a regular expression, because JSDoc types are
    frequently object shapes — `{{x: number, y: number}}` — and matching up to
    the first closing brace would truncate them.
    """
    v = value.lstrip()
    if not v.startswith("{"):
        return "", v
    depth = 0
    for i, ch in enumerate(v):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return v[1:i], v[i + 1:].lstrip()
    return "", v


def clean_block(block: str) -> str:
    """Strip the leading asterisks from a JSDoc block's lines."""
    return "\n".join(re.sub(r"^\s*\*?\s?", "", ln) for ln in block.strip().splitlines()).strip()


def clean_html_comment(block: str) -> str:
    """Dedent an HTML comment's body without touching its Markdown.

    Unlike JSDoc, a `<!-- @component -->` comment has no leading asterisks, so
    the JSDoc cleaner must not be used on it: it would eat the first character
    of any line starting with `*`, which is exactly how Markdown writes bold
    text and bullet lists.
    """
    lines = block.strip("\n").rstrip().split("\n")
    indents = [len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()]
    pad = min(indents) if indents else 0
    return "\n".join(ln[pad:] if len(ln) >= pad else ln for ln in lines).strip()


def split_tags(body: str):
    """Split a cleaned JSDoc body into its description and its tags.

    A tag's text continues onto following lines until the next tag starts, so
    wrapped descriptions survive intact.
    """
    desc, tags, cur = [], [], None
    for ln in body.split("\n"):
        m = TAG_LINE.match(ln)
        if m:
            if cur:
                tags.append(cur)
            cur = [m.group(1), m.group(2)]
        elif cur is not None:
            cur[1] += " " + ln.strip()
        else:
            desc.append(ln)
    if cur:
        tags.append(cur)
    return "\n".join(desc).strip(), tags


def render_tags(tags) -> str:
    """Turn JSDoc tags into Markdown.

    `@param` and `@property` become bullet lists (nested when the name is
    dotted, as with destructured options), `@returns` and `@throws` become
    labelled paragraphs. Unknown tags are passed through so nothing is silently
    lost.
    """
    params, props, out = [], [], []
    for tag, value in tags:
        typ, rest = split_type(value.strip())
        m = TAG_REST.match(rest)
        typ = typ.strip()
        name = (m.group("name") or "").strip() if m else ""
        desc = " ".join((m.group("desc") or "").split()) if m else rest

        if tag in ("param", "arg", "argument", "property", "prop"):
            optional = name.startswith("[")
            clean_name = name.strip("[]")
            default = ""
            if "=" in clean_name:
                clean_name, default = clean_name.split("=", 1)
            bits = f"`{clean_name}`"
            if typ:
                bits += f" (`{typ}`)"
            if optional:
                bits += " *optional*"
            if default:
                bits += f", default `{default}`"
            line = f"- {bits} — {desc}" if desc else f"- {bits}"
            if "." in clean_name:            # nested option: indent under its parent
                line = "  " + line
            (props if tag in ("property", "prop") else params).append(line)
        elif tag in ("returns", "return"):
            label = f"**Returns** (`{typ}`)" if typ else "**Returns**"
            text = " ".join(x for x in (name, desc) if x).strip()
            out.append(f"{label} — {text}" if text else label)
        elif tag == "throws":
            label = f"**Throws** (`{typ}`)" if typ else "**Throws**"
            text = " ".join(x for x in (name, desc) if x).strip()
            out.append(f"{label} — {text}" if text else label)
        elif tag == "type":
            out.append(f"**Type** — `{typ}`" if typ else "")
        elif tag in ("typedef", "component"):
            continue                          # handled by the caller
        else:
            text = " ".join(x for x in (name, desc) if x).strip()
            out.append(f"**{tag}** — {text}" if text else f"**{tag}**")

    parts = []
    if params:
        parts.append("**Parameters**\n\n" + "\n".join(params))
    if props:
        parts.append("**Properties**\n\n" + "\n".join(props))
    parts += [o for o in out if o]
    return "\n\n".join(parts)


def render_doc(body: str) -> str:
    """Render one JSDoc comment body as Markdown."""
    desc, tags = split_tags(clean_block(body))
    rendered = render_tags(tags)
    return (desc + ("\n\n" + rendered if rendered else "")).strip()


def js_entries(text: str, skip_span=None):
    """Yield `(kind, name, heading, markdown)` for each documented declaration.

    `kind` is `"type"` for a `@typedef` block and `"decl"` for anything else,
    so the caller can format type definitions differently from declarations.
    `name` is the bare identifier, `heading` the full declaration line.

    `skip_span` excludes the file-level comment so it is not attributed to
    whatever happens to follow it.
    """
    for m in JSDOC_BLOCK.finditer(text):
        if skip_span and m.start() == skip_span[0]:
            continue
        body = m.group(1)
        cleaned = clean_block(body)

        td = re.search(r"@typedef\s+(.*)", cleaned)
        if td:
            _, rest = split_type(td.group(1))
            tname = re.match(r"[\w$]+", rest)
            if tname:
                yield "type", tname.group(0), tname.group(0), render_doc(body)
                continue

        after = text[m.end():]
        decl_line = ""
        for ln in after.split("\n"):
            if ln.strip():
                decl_line = ln
                break
        d = DECL.match(decl_line)
        if not d:
            continue
        name = d.group("fn") or d.group("cls") or d.group("var") or d.group("method")
        heading = decl_line.strip()
        heading = re.split(r"\s*[={]", heading)[0].strip() if d.group("var") else heading
        heading = heading.rstrip("{ ").rstrip()
        if heading.endswith("("):
            heading = heading[:-1]
        yield "decl", name, heading or name, render_doc(body)


def js_file_md(path: Path, rel: str) -> str:
    """Render one JavaScript module as a Markdown section."""
    text = path.read_text(encoding="utf-8")
    out = [f"### `{rel}`\n"]

    head = re.match(r"\s*/\*\*(.*?)\*/", text, re.S)
    skip = None
    if head:
        out.append(render_doc(head.group(1)) + "\n")
        skip = (head.start(), head.end())

    documented = set()
    for kind, name, heading, doc in js_entries(text, skip_span=skip):
        title = f"type `{heading}`" if kind == "type" else f"`{heading}`"
        out.append(f"#### {title}\n")
        out.append((doc or "_No description yet._") + "\n")
        documented.add(name)

    missing = [m.group(1) for m in
               re.finditer(r"^\s*export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([\w$]+)",
                           text, re.M)
               if m.group(1) not in documented]
    if missing:
        out.append("**Exports without documentation yet:** " +
                   ", ".join(f"`{s}`" for s in dict.fromkeys(missing)) + "\n")
    return "\n".join(out)


# ---------------------------------------------------------------- Svelte -----
COMPONENT_COMMENT = re.compile(r"<!--\s*@component(.*?)-->", re.S)
SCRIPT_BLOCK = re.compile(r"<script[^>]*>(.*?)</script>", re.S)
PROP = re.compile(r"^\s*export\s+let\s+([\w$]+)\s*(?:=\s*([^;]+))?;", re.M)


def svelte_file_md(path: Path, rel: str) -> str:
    """Render one Svelte component as a Markdown section.

    The `<!-- @component -->` comment is Svelte's own documentation convention —
    editors show it on hover — so it doubles as the component's description
    here. Props are listed from their `export let` declarations, whether or not
    each one carries its own JSDoc.
    """
    text = path.read_text(encoding="utf-8")
    out = [f"### `{rel}`\n"]

    comment = COMPONENT_COMMENT.search(text)
    if comment:
        out.append(clean_html_comment(comment.group(1)) + "\n")

    script = "\n".join(m.group(1) for m in SCRIPT_BLOCK.finditer(text))

    props = PROP.findall(script)
    if props:
        listed = ", ".join(
            f"`{n}`" + (f" (default `{d.strip()}`)" if d else "") for n, d in props
        )
        out.append(f"**Props:** {listed}\n")

    for kind, name, heading, doc in js_entries(script):
        title = f"type `{heading}`" if kind == "type" else f"`{heading}`"
        out.append(f"#### {title}\n")
        out.append((doc or "_No description yet._") + "\n")
    return "\n".join(out)


# ----------------------------------------------------------------- driver -----
def render_file(f: Path, root: Path) -> str:
    """Dispatch one source file to the renderer for its language."""
    rel = f.relative_to(root).as_posix()
    try:
        if f.suffix == ".py":
            return py_file_md(f, rel)
        if f.suffix == ".svelte":
            return svelte_file_md(f, rel)
        return js_file_md(f, rel)
    except Exception as ex:                    # never let one file break the build
        return f"### `{rel}`\n\n_Could not parse: {ex}_\n"


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    out_dir = root / "docs" / "code"
    out_dir.mkdir(parents=True, exist_ok=True)

    for title, slug, order, globs in GROUPS:
        files: list[Path] = []
        for g in globs:
            files.extend(sorted(root.glob(g)))
        body = [render_file(f, root) for f in files]
        page = (
            "---\n"
            f"title: {title}\n"
            f"parent: {PARENT}\n"
            f"nav_order: {order}\n"
            "---\n\n"
            f"# {title}\n\n"
            "*Generated from source by `docs/_tools/gen_code_docs.py`. "
            "Edit the comments in the code, then re-run the generator.*\n\n"
            + "\n---\n\n".join(body)
        )
        (out_dir / f"{slug}.md").write_text(page, encoding="utf-8")
        print(f"wrote docs/code/{slug}.md  ({len(files)} file(s))")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
