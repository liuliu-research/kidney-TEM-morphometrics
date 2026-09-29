# -*- coding: utf-8 -*-
"""Figure 4：描述性工作量与固定产能情景（A-D 四个子图）。

数值全部来自已发布的去标识化聚合源数据 CSV，脚本不做任何再计算。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figstyle import (  # noqa: E402
    COL_W_IN, COLORS, FS_BASE, FS_SUP, apply_style, panel_label, save,
    value_axis_grid,
)
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "source_data"
OUT = HERE.parent / "generated_figures"

# 上游源数据中该类别名为中文"其他"，图面统一显示为 Other（与既往版本一致）
CATEGORY_DISPLAY = {"其他": "Other"}
CATEGORY_COLORS = {"Other": COLORS["navy"], "IgAVN": COLORS["purple"],
                   "IgAN": COLORS["pink"]}
QUARTER_COLORS = {"Q1": COLORS["blue"], "Q2": COLORS["teal"],
                  "Q3": COLORS["orange"], "Q4": COLORS["red"]}
STATUS_COLORS = {
    "Below assumed capacity": COLORS["green"],
    "Near assumed capacity": "#D9A521",
    "Exceeds assumed capacity": COLORS["red"],
}


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(SRC / name, encoding="utf-8-sig")


# ------------------------------------------------------------------ A
def panel_a(ax) -> None:
    """年度检查量与每观测月均量（双纵轴）。"""
    df = read("figure4_annual_capacity.csv")
    x = np.arange(len(df))
    vals = df["annual_checks"].to_numpy(dtype=float)
    partial = df["window_status"].eq("partial").to_numpy()
    mean_month = df["mean_checks_per_observed_month"].to_numpy(dtype=float)

    value_axis_grid(ax, "y")
    for xi, v, p in zip(x, vals, partial):
        ax.bar(xi, v, width=0.72, color=COLORS["blue"], zorder=2,
               edgecolor=COLORS["navy"] if p else "white", linewidth=0.5,
               hatch="///" if p else None, alpha=0.55 if p else 1.0)

    ax.set_xticks(x)
    ax.set_xticklabels([str(y)[-2:] for y in df["year"]])
    ax.set_xlabel("Calendar year (20xx)")
    ax.set_ylabel("Annual examinations")
    ax.set_ylim(0, vals.max() * 1.30)

    ax2 = ax.twinx()
    ax2.grid(False)
    ax2.spines["right"].set_visible(True)
    ax2.spines["right"].set_linewidth(0.6)
    ax2.spines["right"].set_color(COLORS["orange"])
    ax2.plot(x, mean_month, color=COLORS["orange"], lw=1.1, marker="o", ms=2.6,
             zorder=4, clip_on=False)
    ax2.set_ylabel("Mean per observed month", color=COLORS["orange"])
    ax2.tick_params(axis="y", colors=COLORS["orange"], length=2.2, width=0.6)
    ax2.set_ylim(0, mean_month.max() * 1.30)

    ax.set_title("Annual and observed-month\nworkload")
    ax.legend(handles=[
        Patch(facecolor=COLORS["blue"], label="Annual examinations"),
        Line2D([], [], color=COLORS["orange"], lw=1.1, marker="o", ms=2.6,
               label="Mean per observed month"),
    ], loc="upper left", bbox_to_anchor=(0.0, 1.02), ncol=1)


# ------------------------------------------------------------------ B
def panel_b(ax) -> None:
    """各年最常见的锁定登记库类别（用图例替代柱上竖排文字）。"""
    df = read("figure4_yearly_top_category.csv")
    cats = [CATEGORY_DISPLAY.get(c, c) for c in df["top_all_category"]]
    x = np.arange(len(df))
    vals = df["top_all_n"].to_numpy(dtype=float)

    value_axis_grid(ax, "y")
    ax.bar(x, vals, width=0.72, zorder=2, edgecolor="white", linewidth=0.4,
           color=[CATEGORY_COLORS[c] for c in cats])

    ax.set_xticks(x)
    ax.set_xticklabels([str(y)[-2:] for y in df["year"]])
    ax.set_xlabel("Calendar year (20xx)")
    ax.set_ylabel("Examinations in top class")
    ax.set_ylim(0, vals.max() * 1.34)
    ax.set_title("Most frequent locked-registry\ncategory by year")

    seen, handles = [], []
    for c in cats:
        if c not in seen:
            seen.append(c)
            handles.append(Patch(facecolor=CATEGORY_COLORS[c], label=c))
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.0, 1.02),
              ncol=3, handlelength=1.0, columnspacing=0.7, handletextpad=0.35)


# ------------------------------------------------------------------ C
def panel_c(ax) -> None:
    """完整日历年的季度工作量。"""
    df = read("figure4_quarterly_volume.csv")
    years = sorted(df["year"].unique())
    x = np.arange(len(years))

    value_axis_grid(ax, "y")
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        sub = df[df["quarter"] == q].set_index("year").reindex(years)
        ax.plot(x, sub["n"].to_numpy(dtype=float), lw=1.1, marker="o", ms=2.6,
                color=QUARTER_COLORS[q], label=q, zorder=3)

    ax.set_xticks(x)
    ax.set_xticklabels([str(y)[-2:] for y in years])
    ax.set_xlabel("Complete calendar year (20xx)")
    ax.set_ylabel("Examinations per quarter")
    ax.set_ylim(0, df["n"].max() * 1.32)
    ax.set_title("Quarterly workload in\ncomplete years")
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 1.02), ncol=4,
              handlelength=1.1, columnspacing=0.8, handletextpad=0.35)


# ------------------------------------------------------------------ D
def panel_d(ax) -> None:
    """固定产能假设下的工作量-产能比 rho。"""
    df = read("figure4_annual_capacity.csv")
    x = np.arange(len(df))
    rho = df["rho"].to_numpy(dtype=float)
    partial = df["window_status"].eq("partial").to_numpy()

    value_axis_grid(ax, "y")
    for xi, v, p, st in zip(x, rho, partial, df["scenario_status"]):
        ax.bar(xi, v, width=0.72, color=STATUS_COLORS[st], zorder=2,
               edgecolor="#4D4D4D" if p else "white", linewidth=0.5,
               hatch="///" if p else None, alpha=0.62 if p else 1.0)
        # 白色描边（非阴影）：使竖排数值与其下方的参考虚线清晰分离
        ax.text(xi, v + 0.05, f"{v:.2f}", ha="center", va="bottom",
                rotation=90, fontsize=FS_BASE, color="#222222", zorder=5,
                path_effects=[pe.withStroke(linewidth=1.8, foreground="white")])

    ax.axhline(0.85, color="#D9A521", lw=0.8, ls="--", zorder=1)
    ax.axhline(1.00, color="#333333", lw=0.8, ls="-.", zorder=1)

    ax.set_xticks(x)
    ax.set_xticklabels([str(y)[-2:] for y in df["year"]])
    ax.set_xlabel("Calendar year (20xx)")
    ax.set_ylabel(r"Scenario utilisation, $\rho$")
    ax.set_ylim(0, 4.35)
    ax.set_yticks([0, 1, 2, 3])
    ax.set_title("Capacity scenario\n(44 examinations/month assumed)")
    ax.legend(handles=[
        Line2D([], [], color="#D9A521", lw=0.8, ls="--",
               label=r"Near-capacity threshold ($\rho$ = 0.85)"),
        Line2D([], [], color="#333333", lw=0.8, ls="-.",
               label=r"Assumed-capacity boundary ($\rho$ = 1.00)"),
        Patch(facecolor="white", edgecolor="#4D4D4D", hatch="///",
              label="Partial boundary year"),
    ], loc="upper left", bbox_to_anchor=(0.0, 1.02), ncol=1)


def main() -> None:
    apply_style()
    OUT.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(COL_W_IN, 5.45), layout="constrained")
    fig.get_layout_engine().set(w_pad=0.045, h_pad=0.045, wspace=0.075, hspace=0.085)

    gs = fig.add_gridspec(2, 2)
    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[1, 0])
    ax_d = fig.add_subplot(gs[1, 1])

    panel_a(ax_a)
    panel_b(ax_b)
    panel_c(ax_c)
    panel_d(ax_d)

    for ax, letter in [(ax_a, "A"), (ax_b, "B"), (ax_c, "C"), (ax_d, "D")]:
        panel_label(ax, letter, dx=-0.185, dy=1.05)

    fig.suptitle("Temporal workload and scenario capacity "
                 "(May 2014 to April 2026)",
                 fontsize=FS_SUP, fontweight="bold")

    w, h = fig.get_size_inches()
    print(f"Figure 4 画布 {w:.3f} x {h:.3f} in")
    save(fig, OUT / "Figure4.png")


if __name__ == "__main__":
    main()
