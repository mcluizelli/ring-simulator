"""
analyze_v5.py — re-run the efficiency analysis pointed at the v5 results
folder produced by run_v5_parallel.py.

Usage:
    python analyze_v5.py [folder-name]

Default folder: v5.1_crosspod_n1000_2026-05-06

Produces:
  * tradeoff_static_speedup_vs_qps.png        (uses bootstrap 95% CI)
  * tradeoff_adaptive_vs_static.png           (uses bootstrap 95% CI)
  * tradeoff_allreduce_speedup_vs_qps.png     (uses bootstrap 95% CI)
  * speedup_vs_k_per_ringsize.png             (uses bootstrap 95% CI)
  * histogram_speedup_per_seed.png            (NEW — per-seed distribution)
  * efficiency_summary.csv                    (with CI columns)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import analyze_efficiency as ae

# v5.1 confined the ring to one pod (tracker A.5), under-reporting every cell.
# v5.3 is the placement-fixed run with the same static/adaptive/allreduce layout.
DEFAULT_TAG = "v5.3_placementfix_n100"

# ─── Bootstrap CI helpers ───────────────────────────────────────────

def _bootstrap_ci(values, n_boot=2000, ci=0.95, rng=None):
    """Return (mean, ci_low, ci_high) using percentile bootstrap."""
    values = np.asarray(values)
    values = values[~np.isnan(values)]
    if len(values) == 0:
        return float("nan"), float("nan"), float("nan")
    if len(values) == 1:
        v = float(values[0])
        return v, v, v
    rng = rng or np.random.default_rng(42)
    n = len(values)
    means = np.array([
        rng.choice(values, size=n, replace=True).mean()
        for _ in range(n_boot)
    ])
    lo = np.percentile(means, (1 - ci) / 2 * 100)
    hi = np.percentile(means, (1 + ci) / 2 * 100)
    return float(values.mean()), float(lo), float(hi)


def _aggregate_with_bootstrap(df, group_keys, time_col, baseline_filter,
                               extra_aggs=None):
    """Aggregate per cell with per-seed paired speedup + bootstrap CI."""
    pair_keys = [k for k in ["seed", "run", "ring_size", "affected_fraction", "msg_bytes"]
                 if k in df.columns]
    join_keys = [k for k in ["ring_size", "affected_fraction", "msg_bytes"]
                 if k in df.columns]
    seed_key = "seed" if "seed" in df.columns else "run"

    base = df[baseline_filter(df)][[seed_key] + join_keys + [time_col]].copy()
    base = base.rename(columns={time_col: "T_base_seed"})
    df = df.merge(base, on=[seed_key] + join_keys, how="left")
    df["speedup_per_seed"] = df["T_base_seed"] / df[time_col]

    rng = np.random.default_rng(42)
    rows = []
    for keys, sub in df.groupby(group_keys):
        if not isinstance(keys, tuple):
            keys = (keys,)
        sp = sub["speedup_per_seed"].dropna().values
        sp_mean, sp_lo, sp_hi = _bootstrap_ci(sp, n_boot=2000, rng=rng)
        t_arr = sub[time_col].dropna().values
        t_mean, t_lo, t_hi = _bootstrap_ci(t_arr, n_boot=2000, rng=rng)
        row = dict(zip(group_keys, keys))
        row.update({
            "T_mean": t_mean,
            "T_ci_low": t_lo,
            "T_ci_high": t_hi,
            "T_min": float(np.min(t_arr)) if len(t_arr) else float("nan"),
            "T_max": float(np.max(t_arr)) if len(t_arr) else float("nan"),
            "speedup": sp_mean,
            "speedup_ci_low": sp_lo,
            "speedup_ci_high": sp_hi,
            "speedup_low": float(np.min(sp)) if len(sp) else float("nan"),
            "speedup_high": float(np.max(sp)) if len(sp) else float("nan"),
            "n_seeds": int(len(sub)),
        })
        if "total_qps" in sub.columns:
            row["total_qps"] = float(sub["total_qps"].mean())
            row["total_qps_std"] = float(sub["total_qps"].std())
        if extra_aggs:
            for col, op in extra_aggs.items():
                row[col] = op(sub)
        rows.append(row)
    return pd.DataFrame(rows)


# ─── Loaders (replace ae.load_*) ────────────────────────────────────

def load_static_v5():
    df = pd.read_csv(ae.STATIC_CSV)
    df["total_qps"] = df["ring_size"] * df["flows_per_neighbor"]
    return _aggregate_with_bootstrap(
        df,
        group_keys=["ring_size", "flows_per_neighbor", "affected_fraction"],
        time_col="completion_time_s",
        baseline_filter=lambda d: d["flows_per_neighbor"] == 1,
    )


def load_adaptive_v5():
    df = pd.read_csv(ae.ADAPTIVE_CSV)
    df["total_qps"] = df["ring_size"] * df["final_k_mean"]
    pair_key = "run"
    base = df[df["method"] == "baseline"][
        [pair_key, "ring_size", "affected_fraction", "completion_time_s"]
    ].rename(columns={"completion_time_s": "T_base_seed"})
    df = df.merge(base, on=[pair_key, "ring_size", "affected_fraction"], how="left")
    df["speedup_per_seed"] = df["T_base_seed"] / df["completion_time_s"]

    rng = np.random.default_rng(42)
    rows = []
    for keys, sub in df.groupby(["ring_size", "method", "affected_fraction"]):
        sp = sub["speedup_per_seed"].dropna().values
        sp_mean, sp_lo, sp_hi = _bootstrap_ci(sp, n_boot=2000, rng=rng)
        t_arr = sub["completion_time_s"].values
        t_mean, t_lo, t_hi = _bootstrap_ci(t_arr, n_boot=2000, rng=rng)
        row = dict(zip(["ring_size", "method", "affected_fraction"], keys))
        row.update({
            "T_mean": t_mean, "T_ci_low": t_lo, "T_ci_high": t_hi,
            "T_min": float(np.min(t_arr)), "T_max": float(np.max(t_arr)),
            "speedup": sp_mean, "speedup_ci_low": sp_lo, "speedup_ci_high": sp_hi,
            "speedup_low": float(np.min(sp)) if len(sp) else float("nan"),
            "speedup_high": float(np.max(sp)) if len(sp) else float("nan"),
            "total_qps": float(sub["total_qps"].mean()),
            "total_qps_std": float(sub["total_qps"].std()),
            "k_mean": float(sub["final_k_mean"].mean()),
            "k_mean_std": float(sub["final_k_mean"].std()),
            "k_max": float(sub["final_k_max"].mean()),
            "n_seeds": int(len(sub)),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def load_allreduce_v5():
    df = pd.read_csv(ae.ALLREDUCE_CSV)
    df["total_qps"] = df["ring_size"] * df["flows_per_neighbor"]
    res = _aggregate_with_bootstrap(
        df,
        group_keys=["ring_size", "flows_per_neighbor", "msg_bytes", "affected_fraction"],
        time_col="allreduce_time_s",
        baseline_filter=lambda d: d["flows_per_neighbor"] == 1,
        extra_aggs={"p99_step": lambda s: float(s["p99_step_s"].mean())},
    )
    return res


# ─── Plot replacements that prefer bootstrap CI ─────────────────────

def _patch_plots():
    """Monkey-patch ae's plots to use bootstrap CI for vertical bars."""
    import inspect, re
    n_label = _detect_n_label()

    def _patched_source(plot_fn):
        src = inspect.getsource(plot_fn)
        # Use bootstrap CI columns instead of min/max for vertical bars
        src = src.replace('sub["speedup_low"]',  'sub["speedup_ci_low"]')
        src = src.replace('sub["speedup_high"]', 'sub["speedup_ci_high"]')
        src = src.replace('d["speedup_low"]',   'd["speedup_ci_low"]')
        src = src.replace('d["speedup_high"]',  'd["speedup_ci_high"]')
        # In allreduce plot, the inner aggregate must include CI columns
        src = src.replace(
            'speedup_low=("speedup_low", "min"),\n                speedup_high=("speedup_high", "max"),',
            'speedup_ci_low=("speedup_ci_low", "min"),\n                speedup_ci_high=("speedup_ci_high", "max"),'
        )
        # Update label text in the y-axis caption
        src = re.sub(r"min/max across \d+ seeds",
                     f"95% bootstrap CI, n≈{n_label}",
                     src)
        src = re.sub(r"min/max across 3 seeds",
                     f"95% bootstrap CI, n≈{n_label}",
                     src)
        src = re.sub(r"n=3 simulator runs", f"n≈{n_label} seeds", src)
        # For adaptive_vs_static panel: switch bar yerr from min/max to CI
        src = src.replace("sub_all[\"T_min\"].values  * 1000",
                          "sub_all[\"T_ci_low\"].values  * 1000")
        src = src.replace("sub_all[\"T_max\"].values  * 1000",
                          "sub_all[\"T_ci_high\"].values  * 1000")
        ns = {}
        exec(src, ae.__dict__, ns)
        return ns[plot_fn.__name__]

    ae.plot_static_tradeoff   = _patched_source(ae.plot_static_tradeoff)
    ae.plot_adaptive_vs_static = _patched_source(ae.plot_adaptive_vs_static)
    ae.plot_speedup_vs_k_per_P = _patched_source(ae.plot_speedup_vs_k_per_P)
    ae.plot_allreduce_tradeoff = _patched_source(ae.plot_allreduce_tradeoff)


def _detect_n_label():
    df_static_raw = pd.read_csv(ae.STATIC_CSV)
    n = df_static_raw.groupby(
        ["flows_per_neighbor", "ring_size", "affected_fraction"]
    ).size().median()
    return int(n)


# ─── Per-seed speedup histogram (NEW plot) ──────────────────────────

def plot_speedup_histogram(out_dir: Path):
    """Histogram of per-seed speedup at P=16, multiple methods, cong=0.5.

    Shows the FULL distribution, not just mean+range. Reveals per-seed
    behaviour (e.g. negative-speedup seeds, multi-modal distributions).
    """
    df_static = pd.read_csv(ae.STATIC_CSV)
    df_adaptive = pd.read_csv(ae.ADAPTIVE_CSV)

    P_TARGET = 16
    CONG_TARGET = 0.5

    # --- per-seed paired speedup for static ---
    s = df_static[df_static["ring_size"] == P_TARGET].copy()
    s["total_qps"] = s["ring_size"] * s["flows_per_neighbor"]
    base_s = s[s["flows_per_neighbor"] == 1][
        ["seed", "affected_fraction", "completion_time_s"]
    ].rename(columns={"completion_time_s": "T_base"})
    s = s.merge(base_s, on=["seed", "affected_fraction"], how="left")
    s["speedup"] = s["T_base"] / s["completion_time_s"]
    s = s[s["affected_fraction"] == CONG_TARGET]

    # --- per-seed paired speedup for adaptive ---
    a = df_adaptive[df_adaptive["ring_size"] == P_TARGET].copy()
    base_a = a[a["method"] == "baseline"][
        ["run", "affected_fraction", "completion_time_s"]
    ].rename(columns={"completion_time_s": "T_base"})
    a = a.merge(base_a, on=["run", "affected_fraction"], how="left")
    a["speedup"] = a["T_base"] / a["completion_time_s"]
    a = a[a["affected_fraction"] == CONG_TARGET]

    # --- collect distributions ---
    distributions = []
    for k in sorted(s["flows_per_neighbor"].unique()):
        if k == 1:
            continue
        vals = s[s["flows_per_neighbor"] == k]["speedup"].dropna().values
        if len(vals):
            distributions.append((f"Static k={int(k)}", vals, "#4472C4"))
    if "adaptive" in a["method"].unique():
        vals = a[a["method"] == "adaptive"]["speedup"].dropna().values
        if len(vals):
            distributions.append(("Adaptive", vals, "#ED7D31"))

    if not distributions:
        print("[histogram] no data for P=16 cong=0.5; skipping")
        return None

    n_label = max(len(v) for _, v, _ in distributions)
    fig, ax = plt.subplots(figsize=(9.5, 6.0))
    bins = np.linspace(0.3, 3.5, 50)
    for label, vals, color in distributions:
        ax.hist(vals, bins=bins, alpha=0.55, label=f"{label}  (n={len(vals)})",
                color=color, edgecolor="black", linewidth=0.4, density=True)
        # Mean line
        ax.axvline(vals.mean(), color=color, linestyle="--", linewidth=1.4, alpha=0.85)

    ax.axvline(1.0, color="grey", linestyle=":", linewidth=1.0, alpha=0.7)
    ax.text(1.0, ax.get_ylim()[1] * 0.97, "  baseline",
            ha="left", va="top", fontsize=9, color="#555555")

    ax.set_xlabel("Per-seed speedup vs. baseline (T_baseline / T_method, paired by seed)",
                  fontsize=11)
    ax.set_ylabel("Density (probability)", fontsize=11)
    ax.set_title(
        f"Speedup distribution at P={P_TARGET}, {int(CONG_TARGET*100)}% congestion  "
        f"(n≈{n_label} per method)",
        fontsize=12, pad=10)
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)

    fig.text(0.5, 0.01,
             "Dashed lines = means.  Distributions to the right of 1.0 = improvement.  "
             "A small tail < 1.0 means some seeds where multi-flow hurt.",
             ha="center", va="bottom", fontsize=8, style="italic", color="#555555")
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    out_path = out_dir / "histogram_speedup_per_seed.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# ─── Main ───────────────────────────────────────────────────────────

def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TAG
    base = ae.RESULTS / tag
    if not base.exists():
        print(f"ERROR: folder does not exist: {base}")
        sys.exit(1)

    ae.OUT = base
    ae.OUT.mkdir(parents=True, exist_ok=True)
    ae.STATIC_CSV = base / "static" / "results.csv"
    ae.ADAPTIVE_CSV = base / "adaptive" / "results.csv"
    ae.ALLREDUCE_CSV = base / "allreduce" / "results.csv"

    missing = [p for p in [ae.STATIC_CSV, ae.ADAPTIVE_CSV, ae.ALLREDUCE_CSV]
               if not p.exists()]
    if missing:
        print("ERROR: missing input files:")
        for p in missing:
            print(f"  - {p}")
        sys.exit(1)

    n_label = _detect_n_label()
    ae.PLOT_FOOTNOTE = (
        f"P = ring size (workers).  k = parallel RDMA flows per ring edge "
        f"(multi-flow parameter).  Total QPs = P × k_mean.  "
        f"Topology: TOPO_K=16 Fat-Tree, 1024 hosts; ring fits in one pod for P ≤ 64.  "
        f"Run: {tag} (n≈{n_label}; bars = bootstrap 95% CI)."
    )

    print(f"Using folder: {base}")
    print(f"Detected n_seeds: {n_label}")
    print()

    # Load with bootstrap CI
    df_static = load_static_v5()
    df_adaptive = load_adaptive_v5()
    df_allreduce = load_allreduce_v5()
    print(f"Loaded: static={len(df_static)} cells, "
          f"adaptive={len(df_adaptive)} cells, "
          f"allreduce={len(df_allreduce)} cells")
    print()

    # Patch plotting functions to use CI columns
    _patch_plots()

    paths = []
    paths.append(ae.plot_static_tradeoff(df_static));       print(f"Wrote: {paths[-1]}")
    paths.append(ae.plot_adaptive_vs_static(df_adaptive));  print(f"Wrote: {paths[-1]}")
    paths.append(ae.plot_allreduce_tradeoff(df_allreduce)); print(f"Wrote: {paths[-1]}")
    paths.append(ae.plot_speedup_vs_k_per_P(df_static));    print(f"Wrote: {paths[-1]}")

    # NEW per-seed histogram
    hist_path = plot_speedup_histogram(base)
    if hist_path:
        paths.append(hist_path)
        print(f"Wrote: {hist_path}")

    # Summary CSV with CI columns
    static_sum = df_static.copy(); static_sum["experiment"] = "static"
    static_sum = static_sum.rename(columns={"flows_per_neighbor": "k"})
    adaptive_sum = df_adaptive.copy(); adaptive_sum["experiment"] = "adaptive"
    ar_sum = df_allreduce.copy(); ar_sum["experiment"] = "allreduce"
    ar_sum = ar_sum.rename(columns={"flows_per_neighbor": "k"})
    summary_path = base / "efficiency_summary.csv"
    pd.concat([static_sum, adaptive_sum, ar_sum], ignore_index=True).to_csv(
        summary_path, index=False)
    print(f"Wrote: {summary_path}")

    # Headline
    print()
    print(f"=== Headline numbers (P=16, n≈{n_label} seeds; bars = 95% bootstrap CI) ===")
    s50 = static_sum[(static_sum["ring_size"] == 16)
                     & (static_sum["affected_fraction"] == 0.5)]
    if not s50.empty:
        print("\nStatic @ 50% congestion:")
        for _, r in s50.sort_values("k").iterrows():
            print(f"  k={int(r['k']):2d}  qps={int(r['total_qps']):3d}  "
                  f"T={r['T_mean']*1000:5.1f}ms [{r['T_ci_low']*1000:5.1f}..{r['T_ci_high']*1000:5.1f}]  "
                  f"speedup={r['speedup']:.2f}× [{r['speedup_ci_low']:.2f}..{r['speedup_ci_high']:.2f}]")
    a50 = adaptive_sum[(adaptive_sum["ring_size"] == 16)
                       & (adaptive_sum["affected_fraction"] == 0.5)]
    if not a50.empty:
        print("\nAdaptive @ 50% congestion (P=16):")
        for _, r in a50.iterrows():
            print(f"  {r['method']:14s}  qps={r['total_qps']:5.1f}±{r.get('total_qps_std',0):4.1f}  "
                  f"k_mean={r.get('k_mean',float('nan')):.2f}±{r.get('k_mean_std',0):.2f}  "
                  f"k_max={r.get('k_max',float('nan')):.2f}  "
                  f"T={r['T_mean']*1000:5.1f}ms  "
                  f"speedup={r['speedup']:.2f}× [{r['speedup_ci_low']:.2f}..{r['speedup_ci_high']:.2f}]")

    # Cross-pod cell if available
    s64 = static_sum[(static_sum["ring_size"] == 64)
                     & (static_sum["affected_fraction"] == 0.5)]
    if not s64.empty:
        print("\nStatic @ P=64 cross-pod, 50% congestion:")
        for _, r in s64.sort_values("k").iterrows():
            print(f"  k={int(r['k']):2d}  qps={int(r['total_qps']):3d}  "
                  f"T={r['T_mean']*1000:5.1f}ms  "
                  f"speedup={r['speedup']:.2f}× [{r['speedup_ci_low']:.2f}..{r['speedup_ci_high']:.2f}]")

    print("\nDone.")


if __name__ == "__main__":
    main()
