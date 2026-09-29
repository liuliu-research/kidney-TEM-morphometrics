# -*- coding: utf-8 -*-
"""Figure S1：由原 Figure 4 迁入补充材料，只改标题措辞（去掉 workload/scenario capacity 表述），数值与布局不变。

复用 大修/figures_rebuild 的样式与面板函数；门控判据同 build_all.py（宽 6.30 in、Arial、≥8 pt、文字包围盒零相交）。
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
REBUILD = HERE
sys.path.insert(0, str(REBUILD))

import figure_gate as build_all  # noqa: E402
import build_fig4  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from figstyle import COL_W_IN, FS_SUP, apply_style, panel_label, save  # noqa: E402

TITLE_A = "Annual and observed-month\nvolume"
TITLE_C = "Quarterly volume in\ncomplete years"
TITLE_D = "Ratio to assumed capacity\n(44 examinations/month)"
YLABEL_D = r"Volume-to-assumed-capacity ratio, $\rho$"
SUPTITLE = "Descriptive examination volume and assumed-capacity ratio (May 2014 to April 2026)"


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
    build_fig4.panel_d(ax_d)
    ax_a.set_title(TITLE_A)
    ax_c.set_title(TITLE_C)
    ax_d.set_title(TITLE_D)
    ax_d.set_ylabel(YLABEL_D)
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
