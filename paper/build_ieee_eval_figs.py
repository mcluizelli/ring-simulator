r"""
IEEE single-column evaluation figures for the INFOCOM paper (Overleaf).
Every number is read from a FROZEN results CSV — nothing hand-typed.

fig_gap_closure.pdf/.png : gap to the static full-concurrency local-model proportional-split reference over the same hashed paths at k=8,
    equal vs proportional split, per fabric x P (two panels: P=16 | P=64).
    Proportional collapses the equal-split gap to ~0 on every fabric;
    slightly negative bars = legitimate end-game contention decay.
    Data: results/v11.1_flexible_split_n1000/summary.csv
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
RESULTS = HERE.parent / "results"
FLEXIBLE_SPLIT_SOURCE = RESULTS / "v11.1_flexible_split_n1000" / "summary.csv"
CONGESTION_SOURCE = RESULTS / "v6.2_congestion_models_randomplacement_2026-07-27" / "summary.csv"
SATURATION_SOURCE = RESULTS / "v10.1_k_saturation_n1000" / "summary.csv"
CONTROLLER_SOURCE = RESULTS / "v5.9_controller_all_n1000" / "efficiency_summary.csv"

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


def _read_frozen_rows(
    path: Path,
    *,
    expected_rows: int,
    seed_field: str,
    expected_seeds: int,
) -> list[dict[str, str]]:
    """Read one exact frozen input and fail closed on a partial or wrong run."""
    if not path.is_file():
        raise FileNotFoundError(f"required frozen figure source is missing: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != expected_rows:
        raise RuntimeError(
            f"unexpected row count in {path}: {len(rows)} != {expected_rows}"
        )
    try:
        seed_counts = {int(float(row[seed_field])) for row in rows}
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid {seed_field!r} field in {path}") from exc
    if seed_counts != {expected_seeds}:
        raise RuntimeError(
            f"unexpected {seed_field} values in {path}: "
            f"{sorted(seed_counts)} != [{expected_seeds}]"
        )
    return rows


def _require_exact_keys(
    *,
    source: Path,
    observed: set[tuple[object, ...]],
    expected: set[tuple[object, ...]],
) -> None:
    """Reject a complete-looking CSV whose natural-key matrix is incomplete."""
    if observed != expected:
        missing = sorted(expected - observed, key=repr)
        extra = sorted(observed - expected, key=repr)
        raise RuntimeError(
            f"unexpected key matrix in {source}: missing={missing}, extra={extra}"
        )


def gap_closure():
    rows = _read_frozen_rows(
        FLEXIBLE_SPLIT_SOURCE, expected_rows=32, seed_field="n", expected_seeds=1000
    )
    s = {(r["fabric"], int(r["P"]), int(r["k"])): r for r in rows}
    _require_exact_keys(
        source=FLEXIBLE_SPLIT_SOURCE,
        observed=set(s),
        expected={(f, p, k) for f in FABS for p in (16, 64) for k in (2, 4, 8, 16)},
    )
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
        for xi, v in zip(x, gp):                     # negative bars carry labels too
            if v <= -0.5:
                ax.annotate(f"{v:.1f}", (xi + 0.19, v), textcoords="offset points",
                            xytext=(0, -8), ha="center", fontsize=6.8, color=PR)
        ax.axhline(0, color="grey", lw=0.7)
        ax.set_xticks(x); ax.set_xticklabels([SHORT[f] for f in FABS])
        ax.set_title(f"$P={P}$", pad=3)
        ax.grid(alpha=0.25, axis="y", lw=0.4)
        ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0].set_ylabel("(reference $-$ realized) / realized (\\%)" if matplotlib.rcParams["text.usetex"]
                       else "(reference $-$ realized) / realized (%)")
    axes[0].set_ylim(-11, 71)
    axes[0].set_yticks([-10, 0, 20, 40, 60])
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
    Data: the placement-fixed sweep
    results/v6.2_congestion_models_randomplacement_2026-07-27/summary.csv;
    columns speedup_mean / speedup_ci_low / speedup_ci_high per (model, k)."""
    frozen_rows = _read_frozen_rows(
        CONGESTION_SOURCE, expected_rows=16, seed_field="n_seeds", expected_seeds=100
    )
    print("  congestion source:", CONGESTION_SOURCE.parent.name)
    rows = {(r["model"], int(r["k"])): r for r in frozen_rows}
    KS = [1, 2, 4, 8]
    MODELS = [("hot_spot", "hot spot", "#1f4e78", "o"),
              ("onoff", "on/off", "#c0392b", "s"),
              ("iid", "i.i.d.", "#8a5aa8", "^"),
              ("microburst", "micro-burst", "#2a9d8f", "D")]
    _require_exact_keys(
        source=CONGESTION_SOURCE,
        observed=set(rows),
        expected={(model, k) for model, *_ in MODELS for k in KS},
    )
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
    ax.set_title("$P=16$", pad=3)
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
    (per-seed paired, 95% CI), dashed = static local-model reference (mean_opt_speedup).
    Data: results/v10.1_k_saturation_n1000/summary.csv (n=1000, frozen 2026-08-04;
    same code and SEED_BASE as v10.0, whose rows it reproduces bit-for-bit on the
    seeds they share -- so it also carries the topology numbers)."""
    rows = _read_frozen_rows(
        SATURATION_SOURCE, expected_rows=48, seed_field="n", expected_seeds=1000
    )
    s = {(r["fabric"], int(r["P"]), int(r["k"])): r for r in rows}
    KS = [1, 2, 4, 8, 16, 32]
    _require_exact_keys(
        source=SATURATION_SOURCE,
        observed=set(s),
        expected={(f, p, k) for f in FABS for p in (16, 64) for k in KS},
    )
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
            ax.plot(KS, opt, ls="--", lw=1.6, color=COLS[fab], alpha=0.85, zorder=4)
        ax.axhline(1.0, ls=":", color="grey", lw=0.7)
        ax.set_xscale("log", base=2)
        ax.set_xticks(KS); ax.set_xticklabels(KS)
        ax.minorticks_off()
        ax.set_xlabel("flows per ring edge $k$")
        if P == 64:
            ax.set_title("$P=64$  (y-scale differs)", pad=3)
            # A grey axhspan(1,5) used to shade the left panel's y-range here. It was
            # removed 2026-08-05: nothing in the legend, the titles or the caption said
            # what it meant, so it read as an unexplained band across half the panel.
            # the paper's key comparison, traced explicitly: realised 2:1/4:1
            # coincide at k=8 while their static local-model references diverge
            y_lo = float(s[("3tier_os4", 64, 8)]["speedup_mean"])
            y_hi = float(s[("3tier_os4", 64, 8)]["mean_opt_speedup"])
            ax.plot([8, 8], [y_lo + 0.12, y_hi - 0.08], ls=":", lw=1.0,
                    color="#24292e", zorder=5)
            # read from the same CSV as the curves -- never hand-typed, so the
            # annotation cannot drift when the source version changes
            r_os2 = float(s[("3tier_os2", 64, 8)]["speedup_mean"])
            b_os2 = float(s[("3tier_os2", 64, 8)]["mean_opt_speedup"])
            ax.annotate(f"realized coincide ({r_os2:.2f}$\\times$/{y_lo:.2f}$\\times$);\n"
                        f"refs diverge ({b_os2:.1f}$\\times$ vs {y_hi:.1f}$\\times$)",
                        xy=(8, (y_lo + y_hi) / 2), xytext=(1.05, 7.9),
                        fontsize=6.2, ha="left", va="top", color="#24292e",
                        arrowprops=dict(arrowstyle="->", lw=0.6, color="#6a737d",
                                        shrinkB=3))
        else:
            ax.set_title(f"$P={P}$", pad=3)
        ax.grid(alpha=0.25, lw=0.4)
        ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0].set_ylabel("speed-up vs. $k=1$")
    h, lb = axes[0].get_legend_handles_labels()
    import matplotlib.lines as mlines
    h.append(mlines.Line2D([], [], ls="--", lw=1.6, color="#6a737d", alpha=0.85))
    lb.append("static local-model reference (dashed, fabric colour)")
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
          "| references@k8 os2/os4:", f"{float(s[('3tier_os2',64,8)]['mean_opt_speedup']):.2f}",
          f"{float(s[('3tier_os4',64,8)]['mean_opt_speedup']):.2f}")
    print("wrote", HERE / "fig_saturation.pdf", "(+.png)")


def efficiency():
    """fig_efficiency: per-QP efficiency (speed-up / k), P=64, equal split.
    The 'why not brute-force k' visual: return per queue-pair collapses as k
    grows (4:1: 0.45 at k=8 -> 0.20 at k=32; leaf-spine 0.09).
    Data: results/v10.1_k_saturation_n1000/summary.csv (frozen)."""
    rows = _read_frozen_rows(
        SATURATION_SOURCE, expected_rows=48, seed_field="n", expected_seeds=1000
    )
    s = {(r["fabric"], int(r["P"]), int(r["k"])): r for r in rows}
    KS = [1, 2, 4, 8, 16, 32]
    _require_exact_keys(
        source=SATURATION_SOURCE,
        observed=set(s),
        expected={(f, p, k) for f in FABS for p in (16, 64) for k in KS},
    )
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
    ax.set_title("$P=64$, equal split", pad=3)
    ax.set_xlabel("flows per ring edge $k$")
    ax.set_ylabel("speed-up per queue-pair (speed-up$/k$)")
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
    """fig_controller: speed-up vs queue-pair cost at P=64.
    Each doubling of static k doubles the QP bill for diminishing returns; the adaptive
    controller (star) sits below the static curve at a lower QP cost — how much
    lower is load-dependent (see tracker A.5).
    Data: results/v5.9_controller_all_n1000/efficiency_summary.csv, where every
    static and adaptive row has n=1000."""
    rows = _read_frozen_rows(
        CONTROLLER_SOURCE,
        expected_rows=104,
        seed_field="n_seeds",
        expected_seeds=1000,
    )
    print("  controller source:", CONTROLLER_SOURCE.parent.name)
    observed_keys = {
        (
            row["experiment"],
            row["method"],
            int(float(row["ring_size"])),
            float(row["affected_fraction"]),
            row["k"],
        )
        for row in rows
    }
    static_keys = {
        ("static", "", p, af, str(k))
        for p in (4, 8, 16, 32, 64)
        for af in (0.0, 0.1, 0.3, 0.5)
        for k in (1, 2, 4, 8)
    }
    adaptive_keys = {
        ("adaptive", method, p, af, "")
        for method in ("adaptive", "baseline", "static(k=4)")
        for p in (16, 64)
        for af in (0.0, 0.1, 0.3, 0.5)
    }
    _require_exact_keys(
        source=CONTROLLER_SOURCE,
        observed=observed_keys,
        expected=static_keys | adaptive_keys,
    )
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
        s4y = pts[2][0]                        # static k=4 speed-up (at 256 QPs)
        # hollow star: stays visible even where it overlaps the static k=4 marker
        ax.plot([a[1]], [a[0]], marker="*", ms=11, markerfacecolor="none",
                mec=col, mew=1.3, ls="none", zorder=6,
                label="adaptive (same colour = same load)" if n == 0 else None)
        ax.annotate(f"{a[1]:.0f}", (a[1], a[0]), textcoords="offset points",
                    xytext=(-4, 7), ha="right", fontsize=6.2,
                    color=col, zorder=6)
        # leader from the static k=4 marker to its star, labelled with the QP saving
        ax.annotate("", xy=(a[1] * 1.03, a[0]), xytext=(256, s4y),
                    arrowprops=dict(arrowstyle="->", color=col, lw=0.7,
                                    shrinkA=3, shrinkB=1))
        sav = (1 - a[1] / 256.0) * 100
        if n == 0:      # blue: the leader is now near-horizontal (the star matches the
            # 256-QP point), so the label goes ABOVE it -- below would sit on the curve
            ax.annotate(f"$-{sav:.0f}\\%$ QPs", (a[1], a[0]),
                        textcoords="offset points", xytext=(16, 5),
                        ha="left", va="bottom", fontsize=6.2, color=col)
        else:           # red: clear of the 256 marker and of the red curve above it
            ax.annotate(f"$-{sav:.0f}\\%$ QPs", (256, s4y), textcoords="offset points",
                        xytext=(6, -9), ha="left", va="top",
                        fontsize=6.2, color=col)
    ax.set_xscale("log", base=2)
    ax.set_xticks([64, 128, 256, 512]); ax.set_xticklabels([64, 128, 256, 512])
    ax.minorticks_off()
    ax.set_title("$P=64$ ($n{=}1000$)", pad=3)
    ax.set_xlabel("total queue-pairs")
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
    for af in (0.1, 0.5):        # print exactly what the figure plots (AFS)
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
    ax.plot([16], [p16], marker="s", ms=6.5, color="#2a7a2a", mec="white", mew=1.4,
            ls="none", zorder=6)
    ax.plot([16], [p16], marker="s", ms=9, markerfacecolor="none", mec="#2a7a2a",
            mew=0.8, ls="none", zorder=5)
    # anchored two-leg annotation: the gain (vertical) and the QP saving (horizontal)
    ax.annotate("", xy=(16, p16), xytext=(16, e32),
                arrowprops=dict(arrowstyle="->", color="#24292e", lw=0.8, shrinkB=4))
    # computed from the plotted points, never hand-typed (a literal here would drift
    # silently the next time the source version changes)
    ax.annotate(f"$+{(p16 / e32 - 1) * 100:.1f}\\%$", (16, (e32 + p16) / 2), textcoords="offset points",
                xytext=(4, 0), fontsize=7, color="#24292e", ha="left", va="center")
    ax.annotate("", xy=(16, e32), xytext=(32, e32),
                arrowprops=dict(arrowstyle="->", color="#24292e", lw=0.8))
    ax.annotate("half the QPs", (22.6, e32), textcoords="offset points",
                xytext=(0, -9), fontsize=6.6, color="#24292e", ha="center")
    ax.set_title("oversub 4:1, $P=64$ ($n{=}1000$)", pad=3)
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
    controller()
    crossk_condensed()
