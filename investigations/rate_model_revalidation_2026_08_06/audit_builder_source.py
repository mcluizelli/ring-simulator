"""Guard the Unit 2A figure-builder terminology-only allowlist."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path


PAIRS = [
    (
        "fig_gap_closure.pdf/.png : gap to the static optimal-split bound at k=8,",
        "fig_gap_closure.pdf/.png : gap to the static full-concurrency local-model proportional-split reference over the same hashed paths at k=8,",
    ),
    ("(bound $-$ realised) / realised (\\\\%)", "(reference $-$ realised) / realised (\\\\%)"),
    ("(bound $-$ realised) / realised (%)", "(reference $-$ realised) / realised (%)"),
    (
        "dashed = optimal-split ceiling (mean_opt_speedup).",
        "dashed = static local-model reference (mean_opt_speedup).",
    ),
    (
        "while their optimal-split bounds diverge",
        "while their static local-model references diverge",
    ),
    ("bounds diverge (", "refs diverge ("),
    (
        "optimal-split bound (dashed, fabric colour)",
        "static local-model reference (dashed, fabric colour)",
    ),
    ("| ceilings@k8 os2/os4:", "| references@k8 os2/os4:"),
]


def normalize_source(source: str) -> str:
    for index, (old, new) in enumerate(PAIRS):
        sentinel = f"__UNIT2A_TERM_{index}__"
        source = source.replace(new, sentinel).replace(old, sentinel)
    return source


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: audit_builder_source.py BUILDER OUTPUT_JSON")
    builder = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    raw = builder.read_bytes()
    source = raw.decode("utf-8")
    normalized = normalize_source(source)
    payload = {
        "builder": str(builder),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "digit_sequences": re.findall(r"\d+", source),
        "normalized_source_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "normalized_ast_sha256": hashlib.sha256(
            ast.dump(ast.parse(normalized), include_attributes=False).encode("utf-8")
        ).hexdigest(),
        "old_counts": [source.count(old) for old, _ in PAIRS],
        "new_counts": [source.count(new) for _, new in PAIRS],
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
