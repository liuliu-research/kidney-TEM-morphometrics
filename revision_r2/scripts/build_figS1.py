# -*- coding: utf-8 -*-
"""Figure S1：由原 Figure 4 迁入补充材料，只改标题措辞（去掉 workload/scenario capacity 表述），数值与布局不变。

复用 大修/figures_rebuild 的样式与面板函数；门控判据同 build_all.py（宽 6.30 in、Arial、≥8 pt、文字包围盒零相交）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REBUILD = HERE
sys.path.insert(0, str(REBUILD))

import figure_gate as build_all  # noqa: E402
import build_fig4  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from figstyle import COL_W_IN, COLORS, FS_SUP, apply_style, panel_label, save, value_axis_grid  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

TITLE_A = "Annual and observed-month\nvolume"
TITLE_C = "Quarterly volume in\ncomplete years"
TITLE_D = "Ratio to assumed capacity\n(44 examinations/month)"
YLABEL_D = r"Volume-to-assumed-capacity ratio, $\rho$"
SUPTITLE = "Descriptive examination volume and assumed-capacity ratio (May 2014 to April 2026)"


def panel_d(ax) -> None:
    """2026-10-10 出版级重绘：单色柱（与面板 A 一致）、部分年份斜纹、两条参考线；
    不再使用三色评价式配色；逐年数值在 Table S6，不在图内标注，避免竖排数字与参考线相交。"""
    df = build_fig4.read("figure4_annual_capacity.csv")
    x = np.arange(len(df))
    rho = df["rho"].to_numpy(dtype=float)
    partial = df["window_status"].eq("partial").to_numpy()
    value_axis_grid(ax, "y")
    for xi, v, p in zip(x, rho, partial):
        ax.bar(xi, v, width=0.72, color=COLORS["blue"], zorder=2,
               edgecolor=COLORS["navy"] if p else "white", linewidth=0.5,
               hatch="///" if p else None, alpha=0.55 if p else 1.0)
    ax.axhline(0.85, color="#D9A521", lw=0.8, ls="--", zorder=1)
    ax.axhline(1.00, color="#333333", lw=0.8, ls="-.", zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels([str(y)[-2:] for y in df["year"]])
    ax.set_xlabel("Calendar year (20xx)")
    ax.set_ylabel(YLABEL_D)
    ax.set_ylim(0, 3.9)
    ax.set_yticks([0, 1, 2, 3])
    ax.set_title(TITLE_D)
    ax.legend(handles=[
        Line2D([], [], color="#D9A521", lw=0.8, ls="--", label=r"$\rho$ = 0.85 reference"),
        Line2D([], [], color="#333333", lw=0.8, ls="-.", label=r"$\rho$ = 1.00 (assumed capacity)"),
    ], loc="upper left", bbox_to_anchor=(0.0, 1.02), ncol=1)


def main() -> None:
    apply_style()
    fig = plt.figure(figsize=(COL_W_IN, 5.45), layout="constrained")
    fig.get_layout_engine().set(w_pad=0.045, h_pad=0.045, wspace=0.075, hspace=0.085)
    gs = fig.add_gridspec(2, 2)
    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[1, 0])
    ax_d = fig.add_subplot(gs[1, 1])
    build_fig4.panel_a(ax_a)
    build_fig4.panel_b(ax_b)
    build_fig4.panel_c(ax_c)
    panel_d(ax_d)
    ax_a.set_title(TITLE_A)
    ax_c.set_title(TITLE_C)
    for ax, letter in [(ax_a, "A"), (ax_b, "B"), (ax_c, "C"), (ax_d, "D")]:
        panel_label(ax, letter, dx=-0.185, dy=1.05)
    fig.suptitle(SUPTITLE, fontsize=FS_SUP, fontweight="bold")

    problems, sizes, fonts = build_all.gate(fig)
    report = {
        "canvas_in": [round(float(v), 3) for v in fig.get_size_inches()],
        "fonts": sorted(fonts),
        "min_font_pt": min(sizes) if sizes else None,
        "problems": problems,
    }
    print(report)
    if problems:
        raise SystemExit("[FAIL] Figure S1 门控未通过")
    output_dir = Path(os.environ.get("TEM_FIGURE_OUTPUT_DIR", str(HERE.parent / "generated_figures")))
    output_dir.mkdir(parents=True, exist_ok=True)
    save(fig, output_dir / "FigureS1.png")
    (output_dir / "FigureS1_gate.json").write_text(__import__("json").dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
