#!/usr/bin/env python3
"""Compare an expected final Nginx config with the active final config.

Comments, whitespace and line endings are ignored. Directive and block token
order is preserved because Nginx directive order can be significant.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path


EXIT_PREFLIGHT = 10
EXIT_CHANGED = 40
UNRESOLVED_TEMPLATE = re.compile(r"\$\{[^}]+}|\{\{[^}]+}}|@[A-Z][A-Z0-9_]*@")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    token: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0

    def flush() -> None:
        if token:
            tokens.append("".join(token))
            token.clear()

    while index < len(text):
        char = text[index]
        if escaped:
            token.append(char)
            escaped = False
        elif char == "\\":
            token.append(char)
            escaped = True
        elif quote:
            token.append(char)
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            token.append(char)
            quote = char
        elif char == "#":
            flush()
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        elif char.isspace():
            flush()
        elif char in "{};":
            flush()
            tokens.append(char)
        else:
            token.append(char)
        index += 1

    if quote:
        raise ValueError("unterminated quoted string")
    flush()
    return tokens


def token_lines(tokens: list[str]) -> list[str]:
    lines: list[str] = []
    directive: list[str] = []
    depth = 0
    for token in tokens:
        if token == "{":
            lines.append(f"{'  ' * depth}{' '.join(directive)} {{")
            directive.clear()
            depth += 1
        elif token == "}":
            if directive:
                lines.append(f"{'  ' * depth}{' '.join(directive)}")
                directive.clear()
            depth = max(0, depth - 1)
            lines.append(f"{'  ' * depth}}}")
        elif token == ";":
            lines.append(f"{'  ' * depth}{' '.join(directive)};")
            directive.clear()
        else:
            directive.append(token)
    if directive:
        lines.append(f"{'  ' * depth}{' '.join(directive)}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--active", type=Path, required=True)
    args = parser.parse_args()

    for label, path in (("expected", args.expected), ("active", args.active)):
        if not path.is_file():
            print(f"ERROR: Nginx {label} config missing: {path}", file=sys.stderr)
            return EXIT_PREFLIGHT

    expected_text = args.expected.read_text(encoding="utf-8-sig")
    active_text = args.active.read_text(encoding="utf-8-sig")
    if UNRESOLVED_TEMPLATE.search(expected_text):
        print(
            f"ERROR: Nginx expected config must be rendered before comparison: {args.expected}",
            file=sys.stderr,
        )
        return EXIT_PREFLIGHT

    try:
        expected_tokens = tokenize(expected_text)
        active_tokens = tokenize(active_text)
    except ValueError as exc:
        print(f"ERROR: invalid Nginx config while auditing {args.name}: {exc}", file=sys.stderr)
        return EXIT_PREFLIGHT

    if expected_tokens == active_tokens:
        print(f"nginxConfig={args.name} semantic=unchanged")
        return 0

    print(f"NGINX_CHANGE file={args.name} semantic=changed")
    for line in difflib.unified_diff(
        token_lines(active_tokens),
        token_lines(expected_tokens),
        fromfile=f"active:{args.active}",
        tofile=f"expected:{args.expected}",
        lineterm="",
    ):
        print(line)
    return EXIT_CHANGED


if __name__ == "__main__":
    raise SystemExit(main())
