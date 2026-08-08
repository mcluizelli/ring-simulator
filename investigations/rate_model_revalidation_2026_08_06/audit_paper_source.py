"""Emit deterministic paper-source guards for Unit 2A.

The guard records the ordered digit sequences and the exact comment-macro
blocks.  A before/after comparison therefore enforces the empty digit whitelist
and proves that the six JY, two IH, and one jose comments were not touched.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


MACROS = ("JY", "IH", "jose")


def escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def extract_blocks(text: str, macro: str) -> list[str]:
    token = f"\\{macro}{{"
    blocks: list[str] = []
    start = 0
    while True:
        begin = text.find(token, start)
        if begin < 0:
            return blocks
        depth = 0
        for index in range(begin + len(token) - 1, len(text)):
            char = text[index]
            if char == "{" and not escaped(text, index):
                depth += 1
            elif char == "}" and not escaped(text, index):
                depth -= 1
                if depth == 0:
                    blocks.append(text[begin : index + 1])
                    start = index + 1
                    break
        else:
            raise RuntimeError(f"unclosed {token} at character {begin}")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: audit_paper_source.py PAPER_TEX OUTPUT_JSON")
    paper = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    text = paper.read_text(encoding="utf-8")
    comments = {}
    for macro in MACROS:
        blocks = extract_blocks(text, macro)
        comments[macro] = {
            "count": len(blocks),
            "sha256": [hashlib.sha256(block.encode("utf-8")).hexdigest() for block in blocks],
        }
    payload = {
        "paper": str(paper),
        "paper_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "digit_sequences": re.findall(r"\d+", text),
        "comments": comments,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
