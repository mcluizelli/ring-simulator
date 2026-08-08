"""Read-only audit of realised completion times against the frozen static reference.

This script imports no simulator code and writes no files.  It scans only frozen
CSVs, joins proportional and reference rows on (fabric, P, seed, k), and prints
deterministic JSON for the terminology gate.

Run from the ring-simulator repository root:

    python investigations/rate_model_revalidation_2026_08_06/audit_frozen_reference.py
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_rows(relative_path: str) -> list[dict[str, str]]:
    with (ROOT / relative_path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def scan_direct(relative_path: str, realised: str, reference: str) -> dict:
    rows = [row for row in read_rows(relative_path) if float(row[reference]) > 0]
    strict = [row for row in rows if float(row[realised]) < float(row[reference])]
    beyond_one_pct = [
        row for row in rows if float(row[realised]) < 0.99 * float(row[reference])
    ]
    worst = min(rows, key=lambda row: float(row[realised]) / float(row[reference]))
    return {
        "path": relative_path,
        "rows": len(rows),
        "strict_crossings": len(strict),
        "more_than_one_pct_below": len(beyond_one_pct),
        "minimum_ratio": float(worst[realised]) / float(worst[reference]),
    }


def reference_index(relative_path: str) -> dict[tuple[str, int, int, int], dict[str, str]]:
    return {
        (row["fabric"], int(row["P"]), int(row["seed"]), int(row["k"])): row
        for row in read_rows(relative_path)
    }


def join_proportional(equal_path: str, proportional_path: str) -> tuple[list[dict], dict]:
    equal = reference_index(equal_path)
    joined = []
    for row in read_rows(proportional_path):
        key = (row["fabric"], int(row["P"]), int(row["seed"]), int(row["k"]))
        if key not in equal:
            continue
        t_prop = float(row["t_prop"])
        opt_time = float(equal[key]["opt_time"])
        joined.append(
            {
                "fabric": key[0],
                "P": key[1],
                "seed": key[2],
                "k": key[3],
                "t_prop": t_prop,
                "opt_time": opt_time,
                "ratio": t_prop / opt_time,
            }
        )

    strict = [row for row in joined if row["t_prop"] < row["opt_time"]]
    beyond_one_pct = [
        row for row in joined if row["t_prop"] < 0.99 * row["opt_time"]
    ]
    worst = min(joined, key=lambda row: row["ratio"])
    summary = {
        "equal_path": equal_path,
        "proportional_path": proportional_path,
        "paired_rows": len(joined),
        "strict_crossings": len(strict),
        "more_than_one_pct_below": len(beyond_one_pct),
        "worst": worst,
    }
    return joined, summary


def cell_audit(joined: list[dict]) -> dict:
    cells: dict[tuple[str, int, int], list[dict]] = defaultdict(list)
    for row in joined:
        cells[(row["fabric"], row["P"], row["k"])].append(row)

    strict_counts = {
        f"{fabric}|P={P}|k={k}": sum(
            row["t_prop"] < row["opt_time"] for row in rows
        )
        for (fabric, P, k), rows in sorted(cells.items())
    }
    return {
        "total_cells": len(cells),
        "cells_with_strict_crossing": sum(count > 0 for count in strict_counts.values()),
        "cells_with_more_than_one_pct_crossing": sum(
            any(row["t_prop"] < 0.99 * row["opt_time"] for row in rows)
            for rows in cells.values()
        ),
        "strict_crossings_by_cell": strict_counts,
    }


def negative_summary_cells(relative_path: str) -> dict:
    rows = read_rows(relative_path)
    negative = [row for row in rows if float(row["mean_gap_prop_pct"]) < 0]
    k8 = [row for row in negative if int(row["k"]) == 8]

    def compact(row: dict[str, str]) -> dict:
        return {
            "fabric": row["fabric"],
            "P": int(row["P"]),
            "k": int(row["k"]),
            "mean_gap_prop_pct": float(row["mean_gap_prop_pct"]),
        }

    return {
        "path": relative_path,
        "total_cells": len(rows),
        "negative_mean_cells": [compact(row) for row in negative],
        "negative_k8_cells": [compact(row) for row in k8],
    }


def overlap_checks() -> dict:
    v110 = {
        (row["fabric"], int(row["P"]), int(row["seed"]), int(row["k"])): row["t_prop"]
        for row in read_rows("results/v11.0_flexible_split_2026-07-02/results.csv")
    }
    v111 = {
        (row["fabric"], int(row["P"]), int(row["seed"]), int(row["k"])): row["t_prop"]
        for row in read_rows("results/v11.1_flexible_split_n1000/results.csv")
    }
    v120 = {
        (row["fabric"], int(row["P"]), int(row["seed"]), int(row["k"])): row["t_prop"]
        for row in read_rows("results/v12.0_flexible_split_k32_2026-07-03/results.csv")
    }
    v121_rows = read_rows("results/v12.1_flagship_n1000_os4p64/results.csv")
    v101 = reference_index("results/v10.1_k_saturation_n1000/results.csv")

    shared_111_121 = 0
    equal_121_101 = 0
    for row in v121_rows:
        key = ("3tier_os4", 64, int(row["seed"]), int(row["k"]))
        if key in v111:
            assert row["t_prop"] == v111[key]
            shared_111_121 += 1
        assert float(row["t_equal"]) == float(v101[key]["t_sim"])
        equal_121_101 += 1

    assert all(v111[key] == value and v120[key] == value for key, value in v110.items())
    return {
        "v11_0_rows_identical_in_v11_1_and_v12_0": len(v110),
        "v11_1_rows_identical_in_v12_1": shared_111_121,
        "v12_1_equal_rows_identical_to_v10_1": equal_121_101,
    }


def main() -> None:
    direct_specs = [
        ("results/v1.0_validation_2026-04-09/baseline/results.csv", "simulated_time_s", "theoretical_time_s"),
        ("results/v1.0_validation_2026-04-13/baseline/results.csv", "simulated_time_s", "theoretical_time_s"),
        ("results/v1.0_validation_2026-04-09/congestion/results.csv", "simulated_time_s", "theoretical_time_no_cong_s"),
        ("results/v1.0_validation_2026-04-13/congestion/results.csv", "simulated_time_s", "theoretical_time_no_cong_s"),
        ("results/v3.0_allreduce_2026-04-13/validation/results.csv", "simulated_time_s", "theoretical_time_s"),
        ("results/v9.0_topology_2026-06-17/results.csv", "t_sim", "opt_time"),
        ("results/v10.0_k_saturation_2026-07-02/results.csv", "t_sim", "opt_time"),
        ("results/v10.1_k_saturation_n1000/results.csv", "t_sim", "opt_time"),
    ]
    proportional_specs = [
        ("results/v10.0_k_saturation_2026-07-02/results.csv", "results/v11.0_flexible_split_2026-07-02/results.csv"),
        ("results/v10.0_k_saturation_2026-07-02/results.csv", "results/v12.0_flexible_split_k32_2026-07-03/results.csv"),
        ("results/v10.1_k_saturation_n1000/results.csv", "results/v11.1_flexible_split_n1000/results.csv"),
    ]

    proportional = []
    v111_joined = None
    for equal_path, proportional_path in proportional_specs:
        joined, summary = join_proportional(equal_path, proportional_path)
        proportional.append(summary)
        if "v11.1_" in proportional_path:
            v111_joined = joined
    assert v111_joined is not None

    report = {
        "direct_reference_scans": [scan_direct(*spec) for spec in direct_specs],
        "proportional_scans": proportional,
        "v11_1_cells": cell_audit(v111_joined),
        "v11_1_negative_summary": negative_summary_cells(
            "results/v11.1_flexible_split_n1000/summary.csv"
        ),
        "overlap_checks": overlap_checks(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
