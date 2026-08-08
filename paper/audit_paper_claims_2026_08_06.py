"""Read-only numerical gate for the active INFOCOM paper.

The gate reads the frozen CSVs and current paper sources, but writes nothing.
With ``--deep-model`` it also reconstructs the initial rate snapshots used by
the 40,000-cell equal-split validation.  That reconstruction is deterministic;
it is not a new experiment and it does not invoke a transfer simulation.

Run from the ring-simulator repository root::

    python paper/audit_paper_claims_2026_08_06.py --deep-model
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import multiprocessing as mp
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
OVERLEAF = PROJECT_ROOT / "paper-overleaf"
HISTORICAL_PAPER_PASS_SIM_HASH = (
    "815d499af4bc3ba5387428dcda6e618f537c758a9a0ceea2d2c605831cf9e60e"
)
CURRENT_SIM_HASH = "96505cefe2e5aa761b80080d77145bfd384c688ce4a8ca5792f8f7ce17ef59bd"
MANIFEST_HASH = "09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e"

FAILURES: list[str] = []
PASSES: list[str] = []


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rows(relative_path: str, *, project_relative: bool = False) -> list[dict[str, str]]:
    base = PROJECT_ROOT if project_relative else ROOT
    with (base / relative_path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def one(data: list[dict[str, str]], **match: object) -> dict[str, str]:
    found = [
        row
        for row in data
        if all(row[key] == str(value) for key, value in match.items())
    ]
    if len(found) != 1:
        raise AssertionError(f"expected one row for {match}, found {len(found)}")
    return found[0]


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSES.append(label)
    else:
        FAILURES.append(f"{label}: {detail}" if detail else label)


def close(label: str, actual: float, expected: float, tolerance: float = 1e-12) -> None:
    check(label, math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance),
          f"actual={actual!r}, expected={expected!r}")


def boot(values: list[float], n_boot: int = 5000, seed: int = 42) -> tuple[float, float, float]:
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.array([
        rng.choice(array, len(array), replace=True).mean() for _ in range(n_boot)
    ])
    return (
        float(array.mean()),
        float(np.percentile(means, 2.5)),
        float(np.percentile(means, 97.5)),
    )


def audit_integrity() -> None:
    close(
        "current sim.py SHA-256",
        1.0 if sha256(ROOT / "sim.py") == CURRENT_SIM_HASH else 0.0,
        1.0,
    )

    manifest = ROOT / "investigations/rate_model_revalidation_2026_08_06/frozen_csv_sha256.txt"
    data_lines = [
        line for line in manifest.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    check("frozen manifest contains 63 CSVs", len(data_lines) == 63, str(len(data_lines)))
    check(
        "frozen manifest aggregate hash",
        hashlib.sha256("\n".join(data_lines).encode("utf-8")).hexdigest() == MANIFEST_HASH,
    )

    byte_total = 0
    for line in data_lines:
        expected_hash, expected_bytes, relative_path = line.split(maxsplit=2)
        path = ROOT / relative_path
        byte_total += path.stat().st_size
        check(f"frozen CSV hash: {relative_path}", sha256(path) == expected_hash)
        check(
            f"frozen CSV bytes: {relative_path}",
            path.stat().st_size == int(expected_bytes),
        )
    check("frozen CSV total bytes", byte_total == 21_210_573, str(byte_total))


def audit_headline_and_regimes() -> None:
    headline = rows("results/v5.4_headline_n1000_placementfix/summary.csv")
    value = float(one(headline, ring_size=64, k=8, affected_fraction=0.5)["speedup"])
    check("headline speed-up rounds to 2.84x", round(value, 2) == 2.84, str(value))

    congestion = rows("results/v6.2_congestion_models_randomplacement_2026-07-27/summary.csv")
    expected = {"hot_spot": 3.05, "onoff": 2.78, "iid": 1.33, "microburst": 1.25}
    for model, rounded in expected.items():
        value = float(one(congestion, model=model, k=8)["speedup_mean"])
        check(f"{model} k=8 rounds to {rounded:.2f}x", round(value, 2) == rounded, str(value))

    old = rows("results/v5.3_placementfix_n100/static/results.csv")
    index = {
        (int(row["run"]), int(row["ring_size"]), float(row["affected_fraction"]),
         int(row["flows_per_neighbor"])): float(row["completion_time_s"])
        for row in old
    }
    n100 = [
        index[(seed, 64, 0.5, 1)] / index[(seed, 64, 0.5, 8)]
        for seed in sorted({key[0] for key in index if key[1:] == (64, 0.5, 1)})
    ]
    check("headline n=100 cell has 100 paired seeds", len(n100) == 100, str(len(n100)))
    check("headline n=100 mean rounds to 2.865x", round(float(np.mean(n100)), 3) == 2.865,
          str(float(np.mean(n100))))


def audit_placement_and_background() -> None:
    summary = rows("results/placement_policies_n1000/summary.csv")
    expected = {"compact_pod": 2.46, "random": 3.58, "spread": 3.43}
    for policy, rounded in expected.items():
        value = float(one(summary, policy=policy)["speedup_k8"])
        check(f"placement {policy} rounds to {rounded:.2f}x", round(value, 2) == rounded,
              str(value))

    raw = rows("results/placement_policies_n1000/results.csv")
    times = {
        (row["policy"], int(row["seed"]), int(row["k"])): float(row["t"])
        for row in raw
    }
    seeds = sorted({seed for policy, seed, k in times if policy == "random" and k == 1})
    random_speedup = [times[("random", seed, 1)] / times[("random", seed, 8)] for seed in seeds]
    spread_speedup = [times[("spread", seed, 1)] / times[("spread", seed, 8)] for seed in seeds]
    mean, low, high = boot([a - b for a, b in zip(random_speedup, spread_speedup)])
    check("placement comparison has 1,000 paired seeds", len(seeds) == 1000, str(len(seeds)))
    check("random-minus-spread mean rounds to 0.16", round(mean, 2) == 0.16, str(mean))
    check("random-minus-spread CI rounds to [0.08, 0.23]",
          (round(low, 2), round(high, 2)) == (0.08, 0.23), f"[{low}, {high}]")

    background = rows("results/v13.0_background_n1000/summary.csv")
    expected_pct = {
        (1, 200): 1.4, (1, 500): 3.5, (1, 1000): 6.7,
        (4, 200): 0.7, (4, 500): 1.5, (4, 1000): 2.8,
    }
    for (k, fps), rounded in expected_pct.items():
        value = float(one(background, ring_size=16, k=k, arrival_rate_fps=fps)["pct_change_mean"])
        check(f"background k={k}, {fps} fps rounds to {rounded:.1f}%",
              round(value, 1) == rounded, str(value))
    k1 = float(one(background, ring_size=16, k=1, arrival_rate_fps=1000)["pct_change_mean"])
    k4 = float(one(background, ring_size=16, k=4, arrival_rate_fps=1000)["pct_change_mean"])
    check("background reduction rounds to 2.4x", round(k1 / k4, 1) == 2.4, str(k1 / k4))


def audit_saturation_and_occupancy() -> None:
    saturation = rows("results/v10.1_k_saturation_n1000/summary.csv")
    os4_p64 = [one(saturation, fabric="3tier_os4", P=64, k=k) for k in (1, 2, 4, 8, 16, 32)]
    actual = [round(float(row["speedup_mean"]), 2) for row in os4_p64]
    check("P=64 4:1 speed-up table", actual == [1.00, 1.69, 2.47, 3.62, 5.00, 6.61], str(actual))
    os2_k8 = one(saturation, fabric="3tier_os2", P=64, k=8)
    os4_k8 = one(saturation, fabric="3tier_os4", P=64, k=8)
    check("P=64 k=8 realized values round to 3.58x/3.62x",
          (round(float(os2_k8["speedup_mean"]), 2), round(float(os4_k8["speedup_mean"]), 2))
          == (3.58, 3.62))
    check("P=64 k=8 references round to 3.9x/6.0x",
          (round(float(os2_k8["mean_opt_speedup"]), 1),
           round(float(os4_k8["mean_opt_speedup"]), 1)) == (3.9, 6.0))

    kstar = rows("reports/k_optimal/stage3_kstar_rule_n1000/kstar_table.csv", project_relative=True)
    expected_kstar = {
        ("3tier_nb", 16): ("4", 1.27, 0.317),
        ("3tier_os2", 16): ("8", 2.30, 0.288),
        ("3tier_os4", 16): ("unsat(>32)", 4.61, 0.144),
        ("2tier", 16): ("8", 1.71, 0.214),
        ("3tier_nb", 64): ("8", 2.05, 0.257),
        ("3tier_os2", 64): ("16", 3.99, 0.249),
        ("3tier_os4", 64): ("unsat(>32)", 6.61, 0.206),
        ("2tier", 64): ("unsat(>32)", 2.80, 0.088),
    }
    for (fabric, p), (k, speedup, efficiency) in expected_kstar.items():
        row = one(kstar, fabric=fabric, P=p)
        check(f"k* label {fabric}/P={p}", row["kstar"] == k, row["kstar"])
        close(f"k* speed-up {fabric}/P={p}", float(row["speedup_at_kstar"]), speedup, 1e-9)
        close(f"k* efficiency {fabric}/P={p}", float(row["per_QP_eff_at_kstar"]), efficiency, 1e-9)

    occupancy = rows("reports/k_optimal/stage1_analytic_ke/ke_table.csv", project_relative=True)
    max_dev = max(float(row["deviation_pct"]) for row in occupancy)
    close("occupancy model worst deviation is 1.60%", max_dev, 1.60, 1e-12)
    crosspod = one(occupancy, context="3tier_crosspod", M=64, k=8)
    samepod = one(occupancy, context="3tier_samepod_crosstor", M=8, k=8)
    check("k=8 path effectiveness rounds to 95%/66%",
          (round(float(crosspod["efficiency_pct"])), round(float(samepod["efficiency_pct"])))
          == (95, 66))

    formula = [64 * (1 - (63 / 64) ** k) for k in (1, 2, 4, 8, 16, 32)]
    check("P=64 distinct-path table follows occupancy formula",
          [round(value, 1) for value in formula] == [1.0, 2.0, 3.9, 7.6, 14.3, 25.3])


def audit_split_and_crossings() -> None:
    equal_rows = rows("results/v10.1_k_saturation_n1000/results.csv")
    equal = {
        (row["fabric"], int(row["P"]), int(row["seed"]), int(row["k"])): row
        for row in equal_rows
    }
    prop_rows = rows("results/v11.1_flexible_split_n1000/results.csv")
    joined = []
    for row in prop_rows:
        key = (row["fabric"], int(row["P"]), int(row["seed"]), int(row["k"]))
        if key in equal:
            joined.append((float(row["t_prop"]), float(equal[key]["t_sim"]),
                           float(equal[key]["opt_time"])))
    check("flexible-split join has 32,000 paired rows", len(joined) == 32_000, str(len(joined)))
    slower = sum(t_prop > t_equal + 1e-15 for t_prop, t_equal, _ in joined)
    check("proportional is never slower than equal at the same k", slower == 0, str(slower))
    crossings = sum(t_prop < reference for t_prop, _, reference in joined)
    beyond_one = sum(t_prop < 0.99 * reference for t_prop, _, reference in joined)
    check("proportional strict reference crossings are 9,440", crossings == 9_440, str(crossings))
    check("proportional >1% reference crossings are 7,335", beyond_one == 7_335,
          str(beyond_one))

    gap = rows("results/v11.1_flexible_split_n1000/summary.csv")
    row = one(gap, fabric="3tier_os4", P=64, k=8)
    check("largest stated equal gap rounds to 67.5%",
          round(float(row["mean_gap_equal_pct"]), 1) == 67.5,
          row["mean_gap_equal_pct"])
    check("plotted proportional gap is -2.6456%",
          round(float(row["mean_gap_prop_pct"]), 4) == -2.6456,
          row["mean_gap_prop_pct"])

    crossk = rows("results/v12.1_flagship_n1000_os4p64/crossk_n1000.csv")
    equal32 = float(one(crossk, fabric="3tier_os4", P=64, k=32)["equal_speedup"])
    prop16 = float(one(crossk, fabric="3tier_os4", P=64, k=16)["prop_speedup"])
    prop8 = float(one(crossk, fabric="3tier_os4", P=64, k=8)["prop_speedup"])
    check("cross-k values round to 7.29x and 6.53x",
          (round(prop16, 2), round(equal32, 2)) == (7.29, 6.53))
    check("cross-k ratio-of-means advantage rounds to 11.7%",
          round((prop16 / equal32 - 1) * 100, 1) == 11.7,
          str((prop16 / equal32 - 1) * 100))
    check("proportional k=8 is 94% of equal k=32",
          round(prop8 / equal32 * 100) == 94, str(prop8 / equal32 * 100))

    ci = one(rows("results/v12.1_flagship_n1000_os4p64/flagship_ci.csv"),
             metric="equal@32 / prop@16")
    check("cross-k mean paired ratio rounds to 1.116",
          round(float(ci["mean_of_ratios"]), 3) == 1.116,
          ci["mean_of_ratios"])
    check("cross-k ratio of means rounds to 1.117",
          round(float(ci["ratio_of_means"]), 3) == 1.117,
          ci["ratio_of_means"])
    check("cross-k paired CI rounds to [1.109, 1.124]",
          (round(float(ci["ci_low"]), 3), round(float(ci["ci_high"]), 3))
          == (1.109, 1.124))


def audit_controller() -> None:
    data = rows("results/v5.9_controller_all_n1000/efficiency_summary.csv")

    def static(p: int, affected: float, k: int) -> dict[str, str]:
        return one(data, ring_size=p, affected_fraction=affected, k=k, experiment="static")

    def adaptive(p: int, affected: float) -> dict[str, str]:
        return one(data, ring_size=p, affected_fraction=affected,
                   experiment="adaptive", method="adaptive")

    def paired_control(p: int, affected: float) -> dict[str, str]:
        return one(data, ring_size=p, affected_fraction=affected,
                   experiment="adaptive", method="static(k=4)")

    p16 = adaptive(16, 0.5)
    p16_control = paired_control(16, 0.5)
    check("P=16 adaptive rounds to 2.08x at 58 QPs",
          (round(float(p16["speedup"]), 2), round(float(p16["total_qps"]))) == (2.08, 58))
    check("P=16 paired static control rounds to 2.26x at 64 QPs",
          (round(float(p16_control["speedup"]), 2), round(float(p16_control["total_qps"])))
          == (2.26, 64))
    check("P=16 independent static sweep is 2.22x (distinct estimator)",
          round(float(static(16, 0.5, 4)["speedup"]), 2) == 2.22)

    p64_10 = adaptive(64, 0.1)
    p64_50 = adaptive(64, 0.5)
    check("P=64 10% adaptive rounds to 2.03x at 131 QPs",
          (round(float(p64_10["speedup"]), 2), round(float(p64_10["total_qps"])))
          == (2.03, 131))
    check("P=64 10% static k=2 rounds to 1.52x at 128 QPs",
          (round(float(static(64, 0.1, 2)["speedup"]), 2),
           round(float(static(64, 0.1, 2)["total_qps"]))) == (1.52, 128))
    check("P=64 50% adaptive rounds to 2.11x at 237 QPs",
          (round(float(p64_50["speedup"]), 2), round(float(p64_50["total_qps"])))
          == (2.11, 237))
    check("P=64 50% static k=4 rounds to 2.15x at 256 QPs",
          (round(float(static(64, 0.5, 4)["speedup"]), 2),
           round(float(static(64, 0.5, 4)["total_qps"]))) == (2.15, 256))


_DEEP_TOPOS: dict[str, object] = {}
_DEEP_HOSTS3: list[str] = []


def _deep_init() -> None:
    global _DEEP_TOPOS, _DEEP_HOSTS3
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from sim import FatTree

    _DEEP_TOPOS = {
        "3tier_nb": FatTree(16, n_tiers=3, oversub=1.0),
        "3tier_os2": FatTree(16, n_tiers=3, oversub=2.0),
        "3tier_os4": FatTree(16, n_tiers=3, oversub=4.0),
        "2tier": FatTree(16, n_tiers=2, oversub=1.0),
    }
    _DEEP_HOSTS3 = list(_DEEP_TOPOS["3tier_nb"].hosts)


def _deep_cell(task: tuple[str, int, int]) -> list[tuple[str, int, int, int, float, float]]:
    from sim import Flow5Tuple

    fabric, p, seed = task
    topo = _DEEP_TOPOS[fabric]
    host_set = topo.hosts if fabric == "2tier" else _DEEP_HOSTS3
    ring = random.Random(9000 + seed).sample(host_set, p)
    paths = [
        [
            topo.ecmp_pick_path(Flow5Tuple(
                src=ring[i], dst=ring[(i + 1) % p],
                sport=10000 + i * 100 + j, dport=20000, proto=6,
            ))
            for j in range(32)
        ]
        for i in range(p)
    ]

    result = []
    for k in (2, 4, 8, 16, 32):
        contention: dict[tuple[str, str], int] = defaultdict(int)
        for logical_paths in paths:
            for path in logical_paths[:k]:
                for edge in zip(path[:-1], path[1:]):
                    contention[edge] += 1

        equal_rates = []
        proportional_rates = []
        for logical_paths in paths:
            rates = [
                min(topo.edge_of[edge] / contention[edge]
                    for edge in zip(path[:-1], path[1:]))
                for path in logical_paths[:k]
            ]
            equal_rates.append(k * min(rates))
            proportional_rates.append(sum(rates))
        result.append((
            fabric, p, seed, k,
            (64 * 1024 * 1024) / min(equal_rates),
            (64 * 1024 * 1024) / min(proportional_rates),
        ))
    return result


def audit_deep_model(workers: int) -> None:
    frozen = {
        (row["fabric"], int(row["P"]), int(row["seed"]), int(row["k"])): row
        for row in rows("results/v10.1_k_saturation_n1000/results.csv")
    }
    tasks = [
        (fabric, p, seed)
        for fabric in ("3tier_nb", "3tier_os2", "3tier_os4", "2tier")
        for p in (16, 64)
        for seed in range(1000)
    ]
    reconstructed = []
    with mp.Pool(processes=workers, initializer=_deep_init) as pool:
        for batch in pool.imap_unordered(_deep_cell, tasks, chunksize=8):
            reconstructed.extend(batch)

    errors = []
    one_sided = 0
    reference_mismatch = 0
    predicted_gap = []
    for fabric, p, seed, k, predicted_equal, reconstructed_reference in reconstructed:
        row = frozen[(fabric, p, seed, k)]
        simulated = float(row["t_sim"])
        frozen_reference = float(row["opt_time"])
        if not math.isclose(reconstructed_reference, frozen_reference,
                            rel_tol=1e-13, abs_tol=1e-15):
            reference_mismatch += 1
        error_pct = (simulated / predicted_equal - 1) * 100
        errors.append(error_pct)
        if predicted_equal <= simulated + 1e-15:
            one_sided += 1
        if fabric == "3tier_os4" and p == 64 and k == 8:
            predicted_gap.append((predicted_equal / reconstructed_reference - 1) * 100)

    check("deep model reconstructed 40,000 cells", len(reconstructed) == 40_000,
          str(len(reconstructed)))
    check("deep model reproduces every frozen static reference", reference_mismatch == 0,
          str(reference_mismatch))
    check("deep equal-time prediction is one-sided in every cell",
          one_sided == 40_000, str(one_sided))
    check("deep equal-time maximum error rounds to 0.80%",
          round(max(errors), 2) == 0.80, str(max(errors)))
    check("deep equal-time mean error rounds to 0.46%",
          round(float(np.mean(errors)), 2) == 0.46, str(float(np.mean(errors))))
    check("deep P=64 4:1 k=8 predicted gap rounds to 67.2%",
          round(float(np.mean(predicted_gap)), 1) == 67.2,
          str(float(np.mean(predicted_gap))))


def audit_source_contract() -> None:
    tex = (OVERLEAF / "paper_infocom.tex").read_text(encoding="utf-8")
    check("paper contains no live reviewer macros", all(token not in tex for token in ("\\JY{", "\\IH{", "\\jose{")))
    check("paper source contains no em-dash token", "---" not in tex)
    check("paper names the local allocator", "link-local equal-share bottleneck-rate model" in tex)
    check("paper does not call the reference an optimal-split bound", "optimal-split bound" not in tex)
    check("paper states both message-size regimes",
          "$64$~MiB per ring edge" in tex
          and "$256$~MiB per ring edge" in tex
          and "$256$~MiB total All-Reduce payload" in tex)
    check("paper distinguishes cross-k estimands",
          "ratio of $1.117$" in tex and "mean paired ratio is $1.116$" in tex)
    check("paper distinguishes controller seed families",
          "paired within its own seed family" in tex
          and "the curves and stars are separate experiments" in tex)
    check("paper scopes the headline to ring-step completion time",
          "$2.84\\times$ ring-step" in tex
          and "$2.84\\times$ end-to-end" not in tex)
    check("paper distinguishes transfer unit from full All-Reduce",
          "one simultaneous ring-neighbor transfer" in tex
          and "full pipelined $2(P{-}1)$-step All-Reduce" in tex)
    check("paper calls split rows paired configurations",
          "$32{,}000$ paired configurations" in tex
          and "$32{,}000$ paired runs" not in tex)
    check("paper defines standard speed-up estimator",
          "mean of the per-seed ratios" in tex
          and "$T_s(1)/T_s(k)$" in tex)
    check("paper states controller timing and cap",
          "$1$~ms window" in tex and "$10$~ms cooldown" in tex
          and "$k_{\\max}{=}4$" in tex)
    check("paper defines path effectiveness and occupancy sample",
          "path effectiveness as $\\hat{m}(k)/k$" in tex
          and "$300$ host" in tex)
    check("paper names NCCL split mode rather than current default",
          "NCCL split mode" in tex and "NCCL default" not in tex)
    check("paper restricts the offline search to uniform k",
          "uniform static" in tex and "uniform\nsubspace $k_e{=}k$" in tex)
    check("paper discloses exact model-rate feedback",
          "exact\ncurrent model rate" in tex
          and "estimator delay and noise" in tex)
    check("paper states background flow-size distribution",
          "mean $50$~MiB" in tex and "$\\sigma{=}1$" in tex
          and "$p_{\\rm local}{=}0.5$" in tex)
    check("paper states congestion-process parameters",
          "$p_{\\rm on}{=}0.01$" in tex and "$p_{\\rm off}{=}0.005$" in tex
          and "probability $0.001$" in tex)
    check("paper scopes analytic distinct paths row",
          "analytic $\\hat{m}_{64}$" in tex
          and "not a placement average" in tex)
    check("paper scopes changes to sender side",
          "none of these network-side changes" in tex
          and "confined to sender-side scheduling" in tex)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deep-model", action="store_true",
                        help="reconstruct the deterministic 40,000 initial snapshots")
    parser.add_argument("--workers", type=int, default=max(1, min(8, mp.cpu_count() or 1)))
    args = parser.parse_args()

    audit_integrity()
    audit_headline_and_regimes()
    audit_placement_and_background()
    audit_saturation_and_occupancy()
    audit_split_and_crossings()
    audit_controller()
    audit_source_contract()
    if args.deep_model:
        audit_deep_model(args.workers)

    for label in PASSES:
        print(f"PASS  {label}")
    for failure in FAILURES:
        print(f"FAIL  {failure}")
    print(f"\nSUMMARY: {len(PASSES)} passed, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
