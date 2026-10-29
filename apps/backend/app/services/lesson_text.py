"""Plain-text projection of a text lesson's Tiptap block doc.

AI-drafted text lessons keep their content only in ``data["blocks"]`` (a
Tiptap / ProseMirror JSON doc) with an empty ``body_markdown``; the Studio
editor fills ``body_markdown`` only when someone saves the lesson
(``blocksToMarkdown`` in apps/frontend/src/lib/lesson/blocks.ts). The
embedding pipeline needs the text either way, so :func:`blocks_to_text`
walks the same node types that serializer covers and returns readable text:
headings keep a ``#`` marker, list items a ``-`` / ``1.`` marker, code
blocks their code, images their alt text. Marks (bold, links) are dropped
because they add nothing to an embedding. Unknown nodes (e.g. the
renderer-only ``callout``) contribute their children, so content is never
silently lost.

The doc comes from an LLM (``TiptapDoc`` validates only the root), so every
node is treated as untrusted: anything that isn't the expected shape is
skipped, a block misplaced inside inline content gets its own line, docs too
deep to recurse fall back to a flat walk, and malformed input returns ""
instead of raising, so one bad lesson can't abort a course's indexing.
"""

from __future__ import annotations

import json
from typing import Any

_BLOCK_KINDS = frozenset(
    {
        "paragraph",
        "heading",
        "bulletList",
        "orderedList",
        "listItem",
        "blockquote",
        "codeBlock",
        "image",
        "horizontalRule",
    }
)
_INLINE_KINDS = frozenset({"text", "hardBreak"})


def blocks_to_text(doc: Any) -> str:
    """Return the readable text of a Tiptap doc, or "" if there is none."""
    try:
        if isinstance(doc, str):
            doc = json.loads(doc)
        if not isinstance(doc, dict):
            return ""
        try:
            return _join_blocks(_children(doc), "\n\n")
        except RecursionError:
            return _flat_text(doc)
    except (ValueError, TypeError, RecursionError):
        return ""


def _flat_text(doc: dict[str, Any]) -> str:
    """Iterative fallback for docs nested too deep to recurse: every text and alt, space-separated."""
    out: list[str] = []
    stack: list[Any] = [doc]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            out.append(node["text"])
        attrs = node.get("attrs")
        if (
            node.get("type") == "image"
            and isinstance(attrs, dict)
            and isinstance(attrs.get("alt"), str)
        ):
            out.append(attrs["alt"])
        content = node.get("content")
        if isinstance(content, list):
            stack.extend(reversed(content))
    return " ".join(" ".join(out).split())


def _kind(node: dict[str, Any]) -> str | None:
    """The node's type, or None when it isn't a string (an LLM can emit any JSON there)."""
    kind = node.get("type")
    return kind if isinstance(kind, str) else None


def _children(node: Any) -> list[dict[str, Any]]:
    content = node.get("content") if isinstance(node, dict) else None
    if not isinstance(content, list):
        return []
    return [c for c in content if isinstance(c, dict)]


def _join_blocks(nodes: list[dict[str, Any]], sep: str) -> str:
    # Consecutive inline nodes directly under a block container are one run of
    # text, so marks that split a word don't get a separator inserted inside it.
    parts: list[str] = []
    run: list[dict[str, Any]] = []
    for n in nodes:
        if _kind(n) in _INLINE_KINDS:
            run.append(n)
            continue
        if run:
            parts.append(_inline({"content": run}))
            run = []
        parts.append(_block(n))
    if run:
        parts.append(_inline({"content": run}))
    return sep.join(p for p in parts if p).strip()


def _inline(node: dict[str, Any]) -> str:
    return _inline_raw(node).strip()


def _inline_raw(node: dict[str, Any]) -> str:
    # Whitespace is kept until the top level, so text split across wrappers
    # (links, mentions) keeps its spaces.
    out: list[str] = []
    for child in _children(node):
        kind = _kind(child)
        if kind == "text":
            text = child.get("text")
            out.append(text if isinstance(text, str) else "")
        elif kind == "hardBreak":
            out.append("\n")
        elif kind in _BLOCK_KINDS:
            out.append(f"\n{_block(child)}\n")
        else:
            out.append(_inline_raw(child))
    return "".join(out)


def _raw_text(node: dict[str, Any]) -> str:
    """Code-block text: raw, line breaks kept, nested nodes included."""
    out: list[str] = []
    for c in _children(node):
        kind = _kind(c)
        if kind == "text":
            s = c.get("text")
            out.append(s if isinstance(s, str) else "")
        elif kind == "hardBreak":
            out.append("\n")
        else:
            out.append(_raw_text(c) + ("\n" if kind in _BLOCK_KINDS else ""))
    return "".join(out)


def _block(node: dict[str, Any]) -> str:
    kind = _kind(node)
    raw_attrs = node.get("attrs")
    attrs: dict[str, Any] = raw_attrs if isinstance(raw_attrs, dict) else {}
    if kind == "paragraph":
        return _inline(node)
    if kind == "heading":
        text = _inline(node)
        try:
            level = min(6, max(1, int(attrs.get("level", 2))))
        except (TypeError, ValueError, OverflowError):
            level = 2
        return f"{'#' * level} {text}" if text else ""
    if kind == "bulletList":
        items = [_list_item(li) for li in _children(node)]
        return "\n".join(f"- {t}" for t in items if t)
    if kind == "orderedList":
        try:
            start = int(attrs.get("start", 1))
        except (TypeError, ValueError, OverflowError):
            start = 1
        items = [t for t in (_list_item(li) for li in _children(node)) if t]
        return "\n".join(f"{start + i}. {t}" for i, t in enumerate(items))
    if kind == "listItem":
        return _list_item(node)
    if kind == "blockquote":
        inner = _join_blocks(_children(node), "\n\n")
        return "\n".join(f"> {line}" for line in inner.split("\n")) if inner else ""
    if kind == "codeBlock":
        return _raw_text(node).strip("\n")
    if kind == "image":
        alt = attrs.get("alt")
        return alt.strip() if isinstance(alt, str) else ""
    if kind == "text":
        raw = node.get("text")
        return raw.strip() if isinstance(raw, str) else ""
    if kind in ("horizontalRule", "hardBreak"):
        return ""
    # Unknown or renderer-only block: keep whatever it wraps.
    return _join_blocks(_children(node), "\n\n")


def _list_item(node: dict[str, Any]) -> str:
    """A list item holds block children; collapse them onto one line, as the editor's serializer does."""
    return _join_blocks(_children(node), " ")
