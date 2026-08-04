"""
Single-column (IEEE ~3.45in) mechanism figure for the multi-flow split.

Paper-ready companion to reports/multiflow_split_mechanism.png (the wide,
report-style version). Two stacked panels make the SPLIT DECISION visible as
bar length:

  (top)  Equal split       B_i = B/k              -> the 25-Gbps flow straggles
  (bottom) Proportional    B_i = B * rate_i/Sum   -> all flows finish together

Exact toy: one ring edge, k=4 sub-flows whose measured fair-share rates are
100/50/25/100 Gbps (Sum=275). Proportional shares = 4/11, 2/11, 1/11, 4/11 of B;
equal finish times 1/2/4/1 (100-Gbps flow = 1.0); proportional finish 400/275 =
1.45t -> x2.75. "rate_i" here is the max-min fair share each flow gets (the
rate[j] of Algorithm 1), not a link line rate.

Outputs (vector PDF preferred for LaTeX, PNG fallback) next to this script:
  fig_split_mechanism.pdf / .png

Run:  python build_split_mechanism_fig.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = Path(__file__).parent
BLUE, GREEN, RED, INK, GREY = "#1f4e78", "#2a7a2a", "#c0392b", "#24292e", "#9aa0a6"

matplotlib.rcParams.update({
    "font.size": 7.2, "axes.titlesize": 7.8, "pdf.fonttype": 42, "ps.fonttype": 42,
})


def main():
    bw = [100, 50, 25, 100]
    k = len(bw)
    eq_share = [1.0 / k] * k
    prop_share = [b / sum(bw) for b in bw]                 # 4/11, 2/11, 1/11, 4/11
    eq_lbl = ["B/4"] * k
    prop_lbl = ["4/11 B", "2/11 B", "1/11 B", "4/11 B"]
    t_equal = [100.0 / b for b in bw]                      # 1, 2, 4, 1
    T_prop = (k * 100.0) / sum(bw)                         # 1.4545
    speed = max(t_equal) / T_prop                          # 2.75
    lane_y = list(range(k - 1, -1, -1))

    fig, (axE, axP) = plt.subplots(2, 1, figsize=(3.45, 3.05))

    def panel(ax, share, lbl, base_col, straggler_idx, title, note):
        ax.set_xlim(0, 0.52); ax.set_ylim(-0.7, k - 0.35)
        ax.set_yticks(lane_y); ax.set_yticklabels([f"{b} Gbps" for b in bw], fontsize=6.6)
        ax.tick_params(left=False); ax.set_xticks([])
        for sp in ("top", "right", "bottom", "left"):
            ax.spines[sp].set_visible(False)
        for i, (y, s, f) in enumerate(zip(lane_y, share, lbl)):
            col = RED if i == straggler_idx else base_col
            ax.add_patch(Rectangle((0, y - 0.30), s, 0.60, facecolor=col,
                                   edgecolor="white", lw=0.5, alpha=0.93, zorder=3))
            ax.text(s + 0.012, y, f, ha="left", va="center", fontsize=6.6,
                    color=col, fontweight="bold")
        ax.set_title(title, color=INK, fontweight="bold", pad=3, loc="left")
        ax.text(0.52, -0.62, note, ha="right", va="center", fontsize=6.4,
                color=(RED if straggler_idx >= 0 else GREEN), fontweight="bold")

    panel(axE, eq_share, eq_lbl, BLUE, 2,
          r"Equal split:  $B_i = B/k$",
          "25-Gbps flow straggles → edge waits 4.0t")
    panel(axP, prop_share, prop_lbl, GREEN, -1,
          r"Proportional split:  $B_i = B\,r_i / \sum_j r_j$",
          f"all flows finish at {T_prop:.2f}t  (×{speed:.2f})")

    fig.tight_layout(pad=0.4, h_pad=1.3)
    fig.savefig(HERE / "fig_split_mechanism.pdf")
    fig.savefig(HERE / "fig_split_mechanism.png", dpi=300)
    plt.close(fig)
    print("wrote:", HERE / "fig_split_mechanism.pdf", "and .png")


if __name__ == "__main__":
    main()
