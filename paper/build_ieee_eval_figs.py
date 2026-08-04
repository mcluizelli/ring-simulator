"""
IEEE single-column evaluation figures for the INFOCOM paper (Overleaf).
Every number is read from a FROZEN results CSV — nothing hand-typed.

fig_gap_closure.pdf/.png : gap to the static optimal-split bound at k=8,
    equal vs proportional split, per fabric x P (two panels: P=16 | P=64).
    Proportional collapses the equal-split gap to ~0 on every fabric;
    slightly negative bars = legitimate end-game contention decay.
    Data: results/v11.0_flexible_split_2026-07-02/summary.csv
    (columns mean_gap_equal_pct / mean_gap_prop_pct at k=8).

Style: serif (Times-like), 7-8pt, 3.45in wide -> \columnwidth of IEEEtran
conference 10pt. Vector PDF for the paper + PNG preview.

Run:  python build_ieee_eval_figs.py
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).parent
RES = HERE.parent / "results" / "v11.0_flexible_split_2026-07-02"  # ring-simulator/results

EQ, PR, INK = "#b06f00", "#2a7a2a", "#24292e"
FABS = ["3tier_nb", "3tier_os2", "3tier_os4", "2tier"]
SHORT = {"3tier_nb": "NB", "3tier_os2": "2:1", "3tier_os4": "4:1", "2tier": "LS"}

matplotlib.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8,
    "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "legend.fontsize": 7,
    "pdf.fonttype": 42, "ps.fonttype": 42,
})


def gap_closure():
    src = RES / "summary.csv"
    s = {(r["fabric"], int(r["P"]), int(r["k"])): r for r in csv.DictReader(open(src))}
    fig, axes = plt.subplots(1, 2, figsize=(3.45, 2.1), sharey=True)
    for ax, P in zip(axes, (16, 64)):
        ge = [float(s[(f, P, 8)]["mean_gap_equal_pct"]) for f in FABS]
        gp = [float(s[(f, P, 8)]["mean_gap_prop_pct"]) for f in FABS]
        x = np.arange(len(FABS))
        ax.bar(x - 0.19, ge, 0.38, color=EQ, label="equal")
        ax.bar(x + 0.19, gp, 0.38, color=PR, label="proportional")
        for xi, v in zip(x, ge):
            if v >= 3:
                ax.annotate(f"{v:.1f}", (xi - 0.19, v), textcoords="offset points",
                            xytext=(0, 1.5), ha="center", fontsize=6.8, color=EQ)
        ax.axhline(0, color="grey", lw=0.7)
        ax.set_xticks(x); ax.set_xticklabels([SHORT[f] for f in FABS])
        ax.set_title(f"$P={P}$", pad=3)
        ax.grid(alpha=0.25, axis="y", lw=0.4)
        ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0].set_ylabel("gap to optimal split (\\%)" if matplotlib.rcParams["text.usetex"]
                       else "gap to optimal split (%)")
    axes[0].set_ylim(-9, 71)
    axes[0].legend(loc="upper left", frameon=False, handlelength=1.2,
                   borderaxespad=0.1, labelspacing=0.3)
    fig.tight_layout(pad=0.3, w_pad=0.8)
    fig.savefig(HERE / "fig_gap_closure.pdf")
    fig.savefig(HERE / "fig_gap_closure.png", dpi=300)
    plt.close(fig)
    # provenance echo for verification
    for P in (16, 64):
        row = [(SHORT[f], f"{float(s[(f,P,8)]['mean_gap_equal_pct']):.2f}",
                f"{float(s[(f,P,8)]['mean_gap_prop_pct']):.2f}") for f in FABS]
        print(f"P={P}:", row)
    print("wrote", HERE / "fig_gap_closure.pdf", "(+.png)")


def congestion_models():
    """fig_speedup_by_model: speed-up vs k per congestion regime (P=16, af=0.3).
    Data: the placement-fixed sweep results/v6.2_congestion_models_randomplacement_*
    (falls back to the superseded v6.1_*, whose ring was pod-local — see the BUGFIX
    note in experiments/experiment_congestion_models.py);
    columns speedup_mean / speedup_ci_low / speedup_ci_high per (model, k)."""
    RES_ROOT = HERE.parent / "results"
    cands = sorted(RES_ROOT.glob("v6.2_congestion_models_*")) or \
            sorted(RES_ROOT.glob("v6.1_congestion_models_*"))
    if not cands:
        raise SystemExit("no v6.x_congestion_models_* results folder found")
    src = cands[-1] / "summary.csv"
    print("  congestion source:", src.parent.name)
    rows = {(r["model"], int(r["k"])): r for r in csv.DictReader(open(src))}
    KS = [1, 2, 4, 8]
    MODELS = [("hot_spot", "hot-spot", "#1f4e78", "o"),
              ("onoff", "on/off", "#c0392b", "s"),
              ("iid", "i.i.d.", "#8a5aa8", "^"),
              ("microburst", "micro-burst", "#2a9d8f", "D")]
    fig, ax = plt.subplots(figsize=(3.45, 2.15))
    for key, lbl, col, mk in MODELS:
        ys = [float(rows[(key, k)]["speedup_mean"]) for k in KS]
        lo = [float(rows[(key, k)]["speedup_ci_low"]) for k in KS]
        hi = [float(rows[(key, k)]["speedup_ci_high"]) for k in KS]
        ax.plot(KS, ys, marker=mk, ms=3.2, lw=1.1, color=col, label=lbl)
        ax.fill_between(KS, lo, hi, color=col, alpha=0.15, lw=0)
    ax.axhline(1.0, ls=":", color="grey", lw=0.7)
    ax.set_xscale("log", base=2)
    ax.set_xticks(KS); ax.set_xticklabels(KS)
    ax.minorticks_off()
    ax.set_xlabel("flows per ring edge $k$")
    ax.set_ylabel("speed-up vs.\\ $k=1$" if matplotlib.rcParams["text.usetex"]
                  else "speed-up vs. $k=1$")
    ax.grid(alpha=0.25, lw=0.4)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.legend(loc="upper left", frameon=False, handlelength=1.6,
              borderaxespad=0.2, labelspacing=0.3)
    fig.tight_layout(pad=0.3)
    fig.savefig(HERE / "fig_speedup_by_model.pdf")
    fig.savefig(HERE / "fig_speedup_by_model.png", dpi=300)
    plt.close(fig)
    for key, lbl, _, _ in MODELS:
        print(lbl, [f"{float(rows[(key,k)]['speedup_mean']):.3f}" for k in KS])
    print("wrote", HERE / "fig_speedup_by_model.pdf", "(+.png)")


def saturation():
    """fig_saturation: the unified topology + k-saturation figure* (double column).
    Speed-up vs k (1..32), 4 fabrics x P in {16,64}; solid = realised equal-split
    (per-seed paired, 95% CI), dashed = optimal-split ceiling (mean_opt_speedup).
    Data: results/v10.0_k_saturation_2026-07-02/summary.csv (frozen; bit-identical
    to v9.0 at every shared k<=8 cell, so it also carries the topology numbers)."""
    src = HERE.parent / "results" / "v10.0_k_saturation_2026-07-02" / "summary.csv"
    s = {(r["fabric"], int(r["P"]), int(r["k"])): r for r in csv.DictReader(open(src))}
    KS = [1, 2, 4, 8, 16, 32]
    FABLBL = {"3tier_nb": "non-blocking", "3tier_os2": "oversub 2:1",
              "3tier_os4": "oversub 4:1", "2tier": "leaf-spine"}
    COLS = {"3tier_nb": "#6a737d", "3tier_os2": "#1f4e78",
            "3tier_os4": "#c0392b", "2tier": "#2a7a2a"}
    MKS = {"3tier_nb": "o", "3tier_os2": "v", "3tier_os4": "s", "2tier": "^"}
    fig, axes = plt.subplots(1, 2, figsize=(7.16, 2.55))
    for ax, P in zip(axes, (16, 64)):
        for fab in FABS:
            ys = [float(s[(fab, P, k)]["speedup_mean"]) for k in KS]
            lo = [ys[i] - float(s[(fab, P, k)]["ci_low"]) for i, k in enumerate(KS)]
            hi = [float(s[(fab, P, k)]["ci_high"]) - ys[i] for i, k in enumerate(KS)]
            opt = [float(s[(fab, P, k)]["mean_opt_speedup"]) for k in KS]
            mfc = "white" if fab == "3tier_os4" else COLS[fab]
            ax.errorbar(KS, ys, yerr=[lo, hi], marker=MKS[fab], ms=3.4, lw=1.15,
                        markerfacecolor=mfc, color=COLS[fab], capsize=1.6,
                        elinewidth=0.7, label=FABLBL[fab], zorder=3)
            ax.plot(KS, opt, ls="--", lw=0.9, color=COLS[fab], alpha=0.45, zorder=2)
        ax.axhline(1.0, ls=":", color="grey", lw=0.7)
        ax.set_xscale("log", base=2)
        ax.set_xticks(KS); ax.set_xticklabels(KS)
        ax.minorticks_off()
        ax.set_xlabel("flows per ring edge $k$")
        ax.set_title(f"$P={P}$", pad=3)
        ax.grid(alpha=0.25, lw=0.4)
        ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0].set_ylabel("speed-up vs. $k=1$")
    h, lb = axes[0].get_legend_handles_labels()
    import matplotlib.lines as mlines
    h.append(mlines.Line2D([], [], ls="--", lw=0.9, color="#6a737d", alpha=0.6))
    lb.append("optimal-split bound")
    axes[0].legend(h, lb, loc="upper left", frameon=False, handlelength=1.7,
                   borderaxespad=0.2, labelspacing=0.3)
    fig.tight_layout(pad=0.3, w_pad=1.2)
    fig.savefig(HERE / "fig_saturation.pdf")
    fig.savefig(HERE / "fig_saturation.png", dpi=300)
    plt.close(fig)
    for P in (16, 64):
        print(f"P={P} k=8:", [f"{FABLBL[f]}={float(s[(f,P,8)]['speedup_mean']):.2f}" for f in FABS])
    print("P=64 os4 16->32:", f"{float(s[('3tier_os4',64,16)]['speedup_mean']):.2f}",
          "->", f"{float(s[('3tier_os4',64,32)]['speedup_mean']):.2f}",
          "| ceilings@k8 os2/os4:", f"{float(s[('3tier_os2',64,8)]['mean_opt_speedup']):.2f}",
          f"{float(s[('3tier_os4',64,8)]['mean_opt_speedup']):.2f}")
    print("wrote", HERE / "fig_saturation.pdf", "(+.png)")


def efficiency():
    """fig_efficiency: per-QP efficiency (speed-up / k), P=64, equal split.
    The 'why not brute-force k' visual: return per queue-pair collapses as k
    grows (4:1: 0.45 at k=8 -> 0.20 at k=32; leaf-spine 0.09).
    Data: results/v10.0_k_saturation_2026-07-02/summary.csv (frozen)."""
    src = HERE.parent / "results" / "v10.0_k_saturation_2026-07-02" / "summary.csv"
    s = {(r["fabric"], int(r["P"]), int(r["k"])): r for r in csv.DictReader(open(src))}
    KS = [1, 2, 4, 8, 16, 32]
    FABLBL = {"3tier_nb": "non-blocking", "3tier_os2": "oversub 2:1",
              "3tier_os4": "oversub 4:1", "2tier": "leaf-spine"}
    COLS = {"3tier_nb": "#6a737d", "3tier_os2": "#1f4e78",
            "3tier_os4": "#c0392b", "2tier": "#2a7a2a"}
    MKS = {"3tier_nb": "o", "3tier_os2": "v", "3tier_os4": "s", "2tier": "^"}
    fig, ax = plt.subplots(figsize=(3.45, 2.05))
    for fab in FABS:
        eff = [float(s[(fab, 64, k)]["speedup_mean"]) / k for k in KS]
        mfc = "white" if fab == "3tier_os4" else COLS[fab]
        ax.plot(KS, eff, marker=MKS[fab], ms=3.2, lw=1.1, color=COLS[fab],
                markerfacecolor=mfc, label=FABLBL[fab])
    ax.set_xscale("log", base=2)
    ax.set_xticks(KS); ax.set_xticklabels(KS)
    ax.minorticks_off()
    ax.set_xlabel("flows per ring edge $k$")
    ax.set_ylabel("speed-up per queue-pair")
    ax.set_ylim(0, 1.05)
    ax.grid(alpha=0.25, lw=0.4)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.legend(loc="upper right", frameon=False, handlelength=1.6,
              borderaxespad=0.2, labelspacing=0.3)
    fig.tight_layout(pad=0.3)
    fig.savefig(HERE / "fig_efficiency.pdf")
    fig.savefig(HERE / "fig_efficiency.png", dpi=300)
    plt.close(fig)
    for fab in FABS:
        e8 = float(s[(fab, 64, 8)]["speedup_mean"]) / 8
        e32 = float(s[(fab, 64, 32)]["speedup_mean"]) / 32
        print(f"{FABLBL[fab]}: eff@k8={e8:.3f} eff@k32={e32:.3f}")
    print("wrote", HERE / "fig_efficiency.pdf", "(+.png)")


def controller():
    """fig_controller: speed-up vs queue-pair cost at P=16.
    Static k=1..8 doubles the QP bill for diminishing returns; the adaptive
    controller (star) sits below the static curve at a lower QP cost — how much
    lower is load-dependent (see tracker A.5).
    Data: the placement-fixed run results/v5.4_headline_n1000_placementfix/
    efficiency_summary.csv (static+adaptive rebuilt from v5.3/v5.4). Falls back to
    the superseded v5.1, whose ring was pod-local and inflated the QP saving."""
    _fixed = HERE.parent / "results" / "v5.4_headline_n1000_placementfix" / "efficiency_summary.csv"
    src = _fixed if _fixed.exists() else \
        HERE.parent / "results" / "v5.1_crosspod_n1000_2026-05-06" / "efficiency_summary.csv"
    print("  controller source:", src.parent.name)
    rows = list(csv.DictReader(open(src)))
    PRING = 64            # cross-pod scale: where selective flow-opening actually pays
    def stat(af, k):
        for r in rows:
            if (r["experiment"] == "static" and int(float(r["ring_size"])) == PRING
                    and r["k"] and int(float(r["k"])) == k
                    and abs(float(r["affected_fraction"]) - af) < 1e-9):
                return float(r["speedup"]), float(r["total_qps"])
        return None
    def adap(af):
        for r in rows:
            if (r["experiment"] == "adaptive" and r.get("method") == "adaptive"
                    and int(float(r["ring_size"])) == PRING
                    and abs(float(r["affected_fraction"]) - af) < 1e-9):
                return float(r["speedup"]), float(r["total_qps"]), float(r["k_mean"])
        return None
    AFS = [(0.1, "#1f4e78", "o", "10\\% affected" if matplotlib.rcParams["text.usetex"] else "10% affected"),
           (0.5, "#c0392b", "s", "50\\% affected" if matplotlib.rcParams["text.usetex"] else "50% affected")]
    fig, ax = plt.subplots(figsize=(3.45, 2.15))
    for n, (af, col, mk, lbl) in enumerate(AFS):
        pts = [stat(af, k) for k in (1, 2, 4, 8)]
        xs = [p[1] for p in pts]; ys = [p[0] for p in pts]
        ax.plot(xs, ys, marker=mk, ms=3.2, lw=1.1, color=col, label="static, " + lbl)
        a = adap(af)
        # label the star ONCE so the legend explains both without duplicating the entry
        ax.plot([a[1]], [a[0]], marker="*", ms=9, color=col, mec="black", mew=0.4,
                ls="none", zorder=5,
                label="adaptive (same colour = same load)" if n == 0 else None)
    ax.set_xscale("log", base=2)
    ax.set_xticks([64, 128, 256, 512]); ax.set_xticklabels([64, 128, 256, 512])
    ax.minorticks_off()
    ax.set_xlabel("total queue-pairs ($P{\\cdot}k$)" if False else "total queue-pairs")
    ax.set_ylabel("speed-up vs. $k=1$")
    ax.grid(alpha=0.25, lw=0.4)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.legend(loc="lower right", frameon=False, handlelength=1.6,
              borderaxespad=0.2, labelspacing=0.3)
    fig.tight_layout(pad=0.3)
    fig.savefig(HERE / "fig_controller.pdf")
    fig.savefig(HERE / "fig_controller.png", dpi=300)
    plt.close(fig)
    for af in (0.3, 0.5):
        s4 = stat(af, 1)
        print(f"af={af}: static", [(k, f"{stat(af,k)[0]:.3f}@{stat(af,k)[1]:.0f}qp") for k in (1,2,4,8)],
              "| adaptive", f"{adap(af)[0]:.3f}@{adap(af)[1]:.2f}qp kmean={adap(af)[2]:.2f}")
    a = adap(0.5); s = stat(0.5, 4)
    print(f"ratio adaptive/static-k4 @af0.5: {a[0]/s[0]:.3f} | qp ratio {a[1]/s[1]:.3f}")
    print("wrote", HERE / "fig_controller.pdf", "(+.png)")


def crossk_condensed():
    """fig_crossk: the hero cross-k visual — os4/P64, equal vs proportional to
    k=32; proportional@16 clears equal@32 (+11.7% at half the QPs).
    Data: results/v12.1_flagship_n1000_os4p64/crossk_n1000.csv (n=1000, production)."""
    src = HERE.parent / "results" / "v12.1_flagship_n1000_os4p64" / "crossk_n1000.csv"
    rows = [r for r in csv.DictReader(open(src))
            if r["fabric"] == "3tier_os4" and int(r["P"]) == 64]
    ks = [int(r["k"]) for r in rows]
    eq = [float(r["equal_speedup"]) for r in rows]
    pr = [float(r["prop_speedup"]) for r in rows]
    d = dict(zip(ks, zip(eq, pr)))
    fig, ax = plt.subplots(figsize=(3.45, 2.15))
    ax.plot(ks, eq, marker="o", ms=3.2, lw=1.1, color="#1f4e78", label="equal split")
    ax.plot(ks, pr, marker="s", ms=3.2, lw=1.1, ls="--", color="#2a7a2a",
            label="proportional split")
    e32 = d[32][0]; p16 = d[16][1]
    ax.axhline(e32, ls=":", lw=0.8, color="#1f4e78", alpha=0.7)
    ax.annotate("equal @ $k{=}32$", (1.15, e32), textcoords="offset points",
                xytext=(0, 3), fontsize=7, color="#1f4e78")
    ax.plot([16], [p16], marker="s", ms=5.5, color="#2a7a2a", mec="black", mew=0.5, ls="none", zorder=5)
    ax.annotate("$+11.7\\%$ at half the QPs", (16, p16), textcoords="offset points",
                xytext=(-86, 6), fontsize=7, color="#2a7a2a")
    ax.set_xscale("log", base=2)
    ax.set_xticks(ks); ax.set_xticklabels(ks)
    ax.minorticks_off()
    ax.set_xlabel("flows per ring edge $k$")
    ax.set_ylabel("speed-up vs. $k=1$")
    ax.grid(alpha=0.25, lw=0.4)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.legend(loc="lower right", frameon=False, handlelength=1.7,
              borderaxespad=0.2, labelspacing=0.3)
    fig.tight_layout(pad=0.3)
    fig.savefig(HERE / "fig_crossk.pdf")
    fig.savefig(HERE / "fig_crossk.png", dpi=300)
    plt.close(fig)
    print("os4/P64 equal:", [f"{v:.3f}" for v in eq])
    print("os4/P64 prop: ", [f"{v:.3f}" for v in pr])
    print(f"prop@16={p16:.3f} equal@32={e32:.3f} ratio={p16/e32:.3f}")
    print("wrote", HERE / "fig_crossk.pdf", "(+.png)")


if __name__ == "__main__":
    gap_closure()
    congestion_models()
    saturation()
    efficiency()
    controller()
    crossk_condensed()
