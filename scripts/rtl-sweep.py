"""One-shot codemod: directional Tailwind classes → logical-property
equivalents. Tailwind compiles ``ps-N`` / ``me-N`` / ``start-N`` to
``padding-inline-start`` / ``margin-inline-end`` / ``inset-inline-start``,
which the browser flips automatically under ``dir="rtl"``.

Safe rewrites (handled here):
  pl-N → ps-N        ml-N → ms-N        rounded-l-N → rounded-s-N
  pr-N → pe-N        mr-N → me-N        rounded-r-N → rounded-e-N
  left-N → start-N   right-N → end-N
  text-left → text-start   text-right → text-end

Skipped:
  Inline `style={{ left: ... }}` — JS positioning is intentional.
  Anything inside a string literal that obviously isn't a class.

Usage: ``py scripts/rtl-sweep.py [--check]``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPLACEMENTS = [
    # `(?<![\w-])` so we don't rewrite `top-left-radius` (not a class
    # anyway, but defensive) or `data-left-rail` etc.
    (re.compile(r"(?<![\w-])pl-(\d+(?:\.\d+)?|\[[^\]]+\])"), r"ps-\1"),
    (re.compile(r"(?<![\w-])pr-(\d+(?:\.\d+)?|\[[^\]]+\])"), r"pe-\1"),
    (re.compile(r"(?<![\w-])ml-(\d+(?:\.\d+)?|\[[^\]]+\]|auto)"), r"ms-\1"),
    (re.compile(r"(?<![\w-])mr-(\d+(?:\.\d+)?|\[[^\]]+\]|auto)"), r"me-\1"),
    (re.compile(r"(?<![\w-])left-(\d+(?:\.\d+)?|\[[^\]]+\])"), r"start-\1"),
    (re.compile(r"(?<![\w-])right-(\d+(?:\.\d+)?|\[[^\]]+\])"), r"end-\1"),
    (re.compile(r"(?<![\w-])text-left\b"), "text-start"),
    (re.compile(r"(?<![\w-])text-right\b"), "text-end"),
    (re.compile(r"(?<![\w-])rounded-l-"), "rounded-s-"),
    (re.compile(r"(?<![\w-])rounded-r-"), "rounded-e-"),
]


def rewrite(text: str) -> tuple[str, int]:
    n = 0
    for pat, repl in REPLACEMENTS:
        text, count = pat.subn(repl, text)
        n += count
    return text, n


def main(check: bool) -> int:
    root = Path("apps/frontend/src")
    total = 0
    touched = 0
    for p in root.rglob("*.tsx"):
        s = p.read_text(encoding="utf-8")
        new, n = rewrite(s)
        if n:
            total += n
            touched += 1
            if not check:
                p.write_text(new, encoding="utf-8")
            print(f"  {n:3d} {p}")
    print(f"\n{total} rewrites across {touched} files")
    if check and total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv))
