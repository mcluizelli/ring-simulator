"""
Single-column (IEEE ~3.45in) mechanism figure for the multi-flow split: fig_split_mechanism.

Design settled 2026-08-05, third redesign, chosen BY READER TEST rather than by designer
preference. Record of how we got here, so it is not relitigated:

  v1  bars, length = completion time, in-bar label = byte share. The actual reader asked
      "what is being compared between the rows, and what is the x axis?" - the two
      questions this design cannot answer structurally.
  v2  cumulative bytes-vs-time lines (slope = rate, height = share, stop = finish; all
      three quantities geometric). Rejected: the reader said plainly he did not
      understand it. Optimising for "everything geometric" is a designer's virtue, not
      a reader's.
  v2b capacity-utilization lanes (height = rate, area = bytes, hatched idle). Rejected on
      review: the straggler - the story's protagonist - is the THINNEST lane (10% of the
      stack), and the "idle capacity" framing conflates the k=1 motivation ("paths sit
      idle", abstract) with the split question, which is about k open flows.
  v3  THIS: paired bars, one row per sub-flow, the two policies compared inside each row.
      The reader reinvented this structure unprompted ("for each one, compare the split
      and the proportional"). Row = one sub-flow labelled by its path's rate; blue =
      equal split, green = proportional (named directly on row 1, no legend); bar length
      = time to send the share it was given; the % label IS the share. The straggler is
      the longest bar on the page, and the honest price - fast flows work LONGER under
      proportional - is visible in every upper row.

Rates 32/24/16/8 Gbps: four DISTINCT rates (two equal rates once drew as one line and
made k=4 look like k=3), summing to 80 <= the 100 Gbps access link that all four
sub-flows of one ring edge share (the earlier 100/50/25/100 summed to 275 Gbps, which
the paper's own model forbids). Ratios give round shares 40/30/20/10% and:

    t       = the 32 Gbps flow's equal-split time
    equal   : times 1t / 1.33t / 2t / 4t  -> the edge waits 4.0t for the 8G path
    prop    : every time = share/rate     -> all four finish at 1.6t
    speed-up 4.0/1.6 = 2.5 = sum(f)/(k*min f), exactly Proposition 1's penalty (80/32).

Outputs: fig_split_mechanism.pdf / .png next to this script.
Run:  python build_split_mechanism_fig.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = Path(__file__).parent
BLUE, GREEN, RED, INK = "#1f4e78", "#2a7a2a", "#c0392b", "#24292e"

matplotlib.rcParams.update({
    "font.size": 7.0, "axes.titlesize": 7.0, "pdf.fonttype": 42, "ps.fonttype": 42,
})


def main():
    bw = [32, 24, 16, 8]
    k = len(bw)
    t_eq = [max(bw) / b for b in bw]              # 1, 1.33, 2, 4  (units of t)
    t_prop = k * max(bw) / sum(bw)                # 1.6
    speed = max(t_eq) / t_prop                    # 2.5
    eq_pct = [25] * k
    prop_pct = [round(100 * b / sum(bw)) for b in bw]   # 40, 30, 20, 10
    assert sum(prop_pct) == 100 and abs(speed - sum(bw) / (k * min(bw))) < 1e-9

    fig, ax = plt.subplots(figsize=(3.45, 2.30))
    h, gap = 0.32, 0.05
    for i, b in enumerate(bw):
        y = k - 1 - i
        eq_col = RED if b == min(bw) else BLUE    # the straggler sets the equal finish
        ax.add_patch(Rectangle((0, y + gap), t_eq[i], h, facecolor=eq_col,
                               edgecolor="white", lw=0.5, zorder=3))
        ax.add_patch(Rectangle((0, y - gap - h), t_prop, h, facecolor=GREEN,
                               edgecolor="white", lw=0.5, zorder=3))
        ax.text(t_eq[i] + 0.07, y + gap + h / 2, f"{eq_pct[i]}%", va="center",
                ha="left", fontsize=6.0, color=eq_col)
        ax.text(t_prop + 0.07, y - gap - h / 2, f"{prop_pct[i]}%", va="center",
                ha="left", fontsize=6.0, color=GREEN)

    # policies named on the first row's own bars - direct labelling, no legend to decode
    ax.text(0.05, k - 1 + gap + h / 2, "equal split", va="center", ha="left",
            fontsize=5.8, color="white", zorder=4)
    ax.text(0.05, k - 1 - gap - h / 2, "proportional", va="center", ha="left",
            fontsize=5.8, color="white", zorder=4)

    ax.axvline(max(t_eq), ls="--", lw=1.0, color=RED, zorder=5)
    ax.axvline(t_prop, ls="--", lw=1.0, color=GREEN, zorder=5)
    ax.text(t_prop - 0.08, k - 0.08, "all four done, 1.6t", ha="right", va="bottom",
            fontsize=6.2, color=GREEN)
    ax.text(max(t_eq) - 0.08, k - 0.08, "last one done, 4.0t", ha="right", va="bottom",
            fontsize=6.2, color=RED)
    ax.annotate("", xy=(max(t_eq), -0.58), xytext=(t_prop, -0.58),
                arrowprops=dict(arrowstyle="<->", color=INK, lw=0.9))
    ax.text(2.95, -0.52, f"the edge is freed ×{speed:.1f} sooner",
            ha="center", va="bottom", fontsize=6.6, color=INK)

    ax.set_yticks(range(k - 1, -1, -1))
    ax.set_yticklabels([f"{b} Gbps" for b in bw], fontsize=6.6)
    ax.set_ylabel("four sub-flows of one ring edge,\nby what each path carries",
                  fontsize=6.0, linespacing=1.25)
    ax.set_xlim(0, 4.95)
    ax.set_ylim(-0.72, k + 0.28)
    ax.set_xticks([0, 1, 2, 3, 4])
    ax.set_xticklabels(["0", "1t", "2t", "3t", "4t"], fontsize=6.6)
    ax.set_xlabel("time to send its share   (t = the 32 Gbps flow's equal-split time)",
                  fontsize=5.9)
    ax.tick_params(left=False)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    fig.tight_layout(pad=0.4)
    fig.savefig(HERE / "fig_split_mechanism.pdf")
    fig.savefig(HERE / "fig_split_mechanism.png", dpi=300)
    plt.close(fig)
    print("wrote:", HERE / "fig_split_mechanism.pdf", "and .png",
          f"| equal={[round(t, 2) for t in t_eq]}t prop={t_prop}t speed=x{speed:.1f}",
          f"| shares {prop_pct}% vs rates {bw}")


if __name__ == "__main__":
    main()
