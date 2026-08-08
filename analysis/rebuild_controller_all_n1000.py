"""Reconstruct the frozen v5.9 controller summary from its four source studies.

The default mode is read-only and requires byte-for-byte agreement with the
frozen target.  ``--output`` may write a copy outside ``results/`` for an
independent reproducibility check; frozen result directories are never edited.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
RESULTS = (ROOT / "results").resolve()
BASE = RESULTS / "v5.5_adaptive_n1000_placementfix" / "efficiency_summary.csv"
P64 = RESULTS / "v5.6_static_af_n1000" / "summary.csv"
P16 = RESULTS / "v5.8_static_af_p16_n1000" / "summary.csv"
SMALL_P = RESULTS / "v5.9_static_af_smallP_n1000" / "summary.csv"
TARGET = RESULTS / "v5.9_controller_all_n1000" / "efficiency_summary.csv"
EXPECTED_SHA256 = "c6185b831317628e3caa653215e24c320ed9abe2f7a12611ac1ad6872164d58b"
EXPECTED_FIELDS = (
    "ring_size",
    "k",
    "affected_fraction",
    "speedup",
    "speedup_ci_low",
    "speedup_ci_high",
    "n_seeds",
    "total_qps",
    "experiment",
    "method",
    "k_mean",
)


def _read_rows(path: Path) -> Tuple[Tuple[str, ...], List[Dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise RuntimeError(f"missing CSV header: {path}")
        return tuple(reader.fieldnames), [dict(row) for row in reader]


def _static_key(row: Mapping[str, str]) -> Tuple[str, str, str, str]:
    return (
        row["ring_size"],
        row["k"],
        row["affected_fraction"],
        row["experiment"],
    )


def _as_static_row(row: Mapping[str, str]) -> Dict[str, str]:
    return {
        "ring_size": row["ring_size"],
        "k": row["k"],
        "affected_fraction": row["affected_fraction"],
        "speedup": row["speedup"],
        "speedup_ci_low": row["speedup_ci_low"],
        "speedup_ci_high": row["speedup_ci_high"],
        "n_seeds": row["n_seeds"],
        "total_qps": row["total_qps"],
        "experiment": "static",
        "method": "",
        "k_mean": row["k"],
    }


def _replacement_rows() -> Dict[Tuple[str, str, str, str], Dict[str, str]]:
    replacements: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}
    expected_counts = {P64: 12, P16: 16, SMALL_P: 48}
    for path, expected_count in expected_counts.items():
        _, source_rows = _read_rows(path)
        if len(source_rows) != expected_count:
            raise RuntimeError(
                f"unexpected source row count for {path}: "
                f"{len(source_rows)} != {expected_count}"
            )
        for source in source_rows:
            row = _as_static_row(source)
            if row["n_seeds"] != "1000":
                raise RuntimeError(f"non-production seed count in {path}")
            key = _static_key(row)
            if key in replacements:
                raise RuntimeError(f"duplicate replacement key: {key}")
            replacements[key] = row
    if len(replacements) != 76:
        raise RuntimeError("controller merge must replace exactly 76 static rows")
    return replacements


def reconstruct_bytes() -> bytes:
    fields, rows = _read_rows(BASE)
    if fields != EXPECTED_FIELDS or len(rows) != 104:
        raise RuntimeError("unexpected v5.5 controller base schema or row count")

    replacements = _replacement_rows()
    output_rows: List[Dict[str, str]] = []
    used = set()
    for original in rows:
        key = _static_key(original)
        if key in replacements:
            output_rows.append(replacements[key])
            used.add(key)
        else:
            output_rows.append(original)
    if used != set(replacements):
        missing = sorted(set(replacements) - used)
        raise RuntimeError(f"replacement keys absent from v5.5 base: {missing}")

    counts = Counter(row["experiment"] for row in output_rows)
    if counts != Counter({"static": 80, "adaptive": 24}):
        raise RuntimeError(f"unexpected merged experiment counts: {counts}")
    if any(row["n_seeds"] != "1000" for row in output_rows):
        raise RuntimeError("merged controller summary is not uniformly n=1000")

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(EXPECTED_FIELDS),
        lineterminator="\r\n",
        extrasaction="raise",
    )
    writer.writeheader()
    writer.writerows(output_rows)
    payload = stream.getvalue().encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(f"reconstructed SHA-256 changed: {digest}")
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = reconstruct_bytes()
    frozen = TARGET.read_bytes()
    if frozen != payload:
        raise RuntimeError("frozen v5.9 controller summary differs from reconstruction")
    if args.output is not None:
        output = args.output.resolve()
        if output == RESULTS or RESULTS in output.parents:
            raise RuntimeError("refusing to write inside frozen results/")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
    print(f"PASS rows=104 bytes={len(payload)} sha256={EXPECTED_SHA256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
