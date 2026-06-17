"""
Plot the v7 microburst confirmation: two panels per intensity.
  Panel A — cooldown sweep at sub-ms bursts: adaptive speedup vs cooldown, with
            the static k=8 reference (shows cooldown is the lever, reaching k=8).
  Panel B — duration at matched aggregate: static-k8 and adaptive-default speedup
            at 0.1 / 1 / 5 ms bursts (shows the controller is not worse at sub-ms).

Usage:  python analysis/plot_microburst_confirm.py <results_dir> [<results_dir2> ...]
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def load(d):
    s = {}
    with open(Path(d) / "summary.csv") as f:
        for r in csv.DictReader(f):
            s[r["run_type"]] = {k: float(v) for k, v in r.items() if k != "run_type"}
    return s


def panel_cooldown(ax, s, title):
    # cooldown in ms: adaptDef=10, CD5=5, CD2=2, CD1=1 ; aggr shown separately
    order = [("adaptDef", 10.0), ("adaptCD5", 5.0), ("adaptCD2", 2.0), ("adaptCD1", 1.0)]
    xs = [c for _, c in order]
    ys = [s[f"dur2_{n}"]["speedup_mean"] for n, _ in order]
    lo = [s[f"dur2_{n}"]["speedup_mean"] - s[f"dur2_{n}"]["ci_low"] for n, _ in order]
    hi = [s[f"dur2_{n}"]["ci_high"] - s[f"dur2_{n}"]["speedup_mean"] for n, _ in order]
    ax.errorbar(xs, ys, yerr=[lo, hi], marker="o", color="#1f4e78", capsize=3,
                label="adaptive (vary cooldown)")
    # aggressive variant as a star at x=1 (0.5ms window)
    a = s["dur2_adaptAggr"]
    ax.errorbar([0.7], [a["speedup_mean"]],
                yerr=[[a["speedup_mean"] - a["ci_low"]], [a["ci_high"] - a["speedup_mean"]]],
                marker="*", markersize=13, color="#6aa84f", capsize=3, label="aggressive (0.5ms win)")
    k8 = s["dur2_k8"]["speedup_mean"]
    ax.axhline(k8, ls="--", color="#c0392b", lw=1.2, label=f"static k=8 ({k8:.2f}x)")
    ax.axhline(1.0, ls=":", color="grey", lw=1)
    ax.set_xscale("log"); ax.set_xticks([0.7, 1, 2, 5, 10])
    ax.set_xticklabels(["aggr", "1", "2", "5", "10"])
    ax.invert_xaxis()
    ax.set_xlabel("controller cooldown (ms)  — shorter →")
    ax.set_ylabel("speedup vs k=1 (paired, 95% CI)")
    ax.set_title(title)
    ax.legend(fontsize=8); ax.grid(alpha=0.3)


def panel_duration(ax, s, title):
    durs = [("dur2", "0.1ms\n(sub-ms)"), ("dur20", "1ms\n(=window)"), ("dur100", "5ms\n(>>window)")]
    x = np.arange(len(durs)); w = 0.36
    for off, key, col, lab in [(-w/2, "k8", "#c0392b", "static k=8"),
                               (+w/2, "adaptDef", "#1f4e78", "adaptive (default cd)")]:
        ys = [s[f"{d}_{key}"]["speedup_mean"] for d, _ in durs]
        lo = [s[f"{d}_{key}"]["speedup_mean"] - s[f"{d}_{key}"]["ci_low"] for d, _ in durs]
        hi = [s[f"{d}_{key}"]["ci_high"] - s[f"{d}_{key}"]["speedup_mean"] for d, _ in durs]
        ax.bar(x + off, ys, w, yerr=[lo, hi], capsize=3, color=col, label=lab, alpha=0.85)
    ax.axhline(1.0, ls=":", color="grey", lw=1)
    ax.set_xticks(x); ax.set_xticklabels([l for _, l in durs])
    ax.set_xlabel("burst duration (aggregate congestion matched)")
    ax.set_ylabel("speedup vs k=1 (paired, 95% CI)")
    ax.set_title(title); ax.legend(fontsize=8); ax.grid(alpha=0.3, axis="y")


def main():
    dirs = sys.argv[1:] or [str(Path(__file__).resolve().parents[1] / "results"
            / "v7.0_microburst_confirm_2026-06-17" / u) for u in ("util30", "util45")]
    for d in dirs:
        s = load(d)
        util_tag = Path(d).name
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
        panel_cooldown(ax1, s, "A. Cooldown is the lever (sub-ms bursts)")
        panel_duration(ax2, s, "B. Sub-ms not worse than long bursts")
        fig.suptitle(f"Microburst ({util_tag}): controller reacts to sub-ms bursts; "
                     "cooldown (not duration) is the limit", fontsize=11, y=1.02)
        fig.tight_layout()
        out = Path(d) / "microburst_confirm.png"
        fig.savefig(out, dpi=200, bbox_inches="tight")
        print(f"Plot saved: {out}")


if __name__ == "__main__":
    main()
