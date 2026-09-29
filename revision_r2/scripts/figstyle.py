# -*- coding: utf-8 -*-
"""iScience 大修图形统一样式。

设计原则
--------
1. 画布宽度固定为 6.30 英寸（160 mm），与 manuscript docx 正文栏宽完全一致。
   图片以原尺寸插入 docx（缩放 = 1.000），因此脚本里的 8 pt 就是页面上真实的 8 pt。
   这是本轮修订的核心：旧版把 17 英寸画布压缩到 6.3 英寸，13 pt 落到纸面只剩 4.8 pt。
2. 全部文字 Arial 8 pt；子图标识 Arial 10 pt 纯黑加粗，置于坐标区外左上角。
3. 网格线永远在数据之下；热图强制关闭网格（否则网格线会穿过单元格数字）。
4. 图例一律无边框、无阴影，且放进专门留出的空白带，不与数据争位置。
5. 不使用 seaborn 的 talk/notebook context —— 那会按比例放大字号，破坏物理尺寸对应关系。
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

# ---------------------------------------------------------------- 尺寸常量
COL_W_IN = 6.30  # docx 正文栏宽 = 160 mm
DPI = 600

# ---------------------------------------------------------------- 字号常量
FS_BASE = 8.0   # 全部正文、刻度、图例、标注
FS_PANEL = 10.0  # 子图标识 A/B/C…
FS_SUP = 9.0     # 总标题

# ---------------------------------------------------------------- 配色
# 沿用原图色板，保证与已发布的 source_data / 前序版本视觉一致
COLORS = {
    "navy": "#25476A",
    "blue": "#4C78A8",
    "teal": "#2A9D8F",
    "orange": "#E28E2C",
    "red": "#C44E52",
    "green": "#4E9F6B",
    "purple": "#6B5B95",
    "pink": "#C97B93",
    "grey": "#8C8C8C",
    "light": "#EAF0F6",
    "grid": "#D6DBE1",
    "axis": "#4D4D4D",
}


def apply_style() -> None:
    """把统一样式写入 rcParams。每个绘图脚本开头调用一次。"""

    plt.rcParams.update(
        {
            # 字体
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial"],
            "font.size": FS_BASE,
            "axes.titlesize": FS_BASE,
            "axes.labelsize": FS_BASE,
            "xtick.labelsize": FS_BASE,
            "ytick.labelsize": FS_BASE,
            "legend.fontsize": FS_BASE,
            "figure.titlesize": FS_SUP,
            "axes.titleweight": "bold",
            "mathtext.fontset": "custom",
            "mathtext.rm": "Arial",
            "mathtext.it": "Arial:italic",
            "mathtext.bf": "Arial:bold",
            # 线宽（按物理尺寸缩小，避免 8pt 字配粗线显得笨重）
            "axes.linewidth": 0.6,
            "grid.linewidth": 0.4,
            "lines.linewidth": 1.0,
            "patch.linewidth": 0.5,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "xtick.major.size": 2.2,
            "ytick.major.size": 2.2,
            "xtick.major.pad": 1.8,
            "ytick.major.pad": 1.8,
            # 网格
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": COLORS["grid"],
            "grid.linestyle": "-",
            "grid.alpha": 1.0,
            # 边框：只留左、下
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": COLORS["axis"],
            "axes.labelpad": 2.0,
            "axes.titlepad": 3.0,
            # 图例：无边框、无阴影
            "legend.frameon": False,
            "legend.handlelength": 1.4,
            "legend.handletextpad": 0.5,
            "legend.columnspacing": 1.0,
            "legend.labelspacing": 0.35,
            "legend.borderaxespad": 0.2,
            # 输出
            "figure.dpi": DPI,
            "savefig.dpi": DPI,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.pad_inches": 0.0,
            "pdf.fonttype": 42,  # 嵌入 TrueType，投稿要求可编辑字体
            "ps.fonttype": 42,
        }
    )


def panel_label(ax, letter: str, dx: float = -0.10, dy: float = 1.06) -> None:
    """在子图左上角外侧放置纯黑加粗标识，永远不压数据。"""

    ax.text(
        dx,
        dy,
        letter,
        transform=ax.transAxes,
        fontsize=FS_PANEL,
        fontweight="bold",
        color="#000000",
        ha="left",
        va="bottom",
    )


def clean_heatmap_axes(ax) -> None:
    """热图专用：彻底关掉网格并恢复四边框，避免网格线穿过单元格数字。"""

    ax.grid(False)
    ax.set_axisbelow(False)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.6)
        spine.set_color(COLORS["axis"])


def value_axis_grid(ax, axis: str = "y") -> None:
    """只保留与数值轴垂直的网格线，且置于数据之下。"""

    ax.grid(False)
    ax.grid(True, axis=axis, color=COLORS["grid"], linewidth=0.4, zorder=0)
    ax.set_axisbelow(True)


def save(fig, path, *, width_in: float = COL_W_IN) -> None:
    """保存前断言画布宽度未被改动，确保插入 docx 时缩放为 1.000。"""

    actual = fig.get_size_inches()[0]
    if abs(actual - width_in) > 1e-6:
        raise ValueError(f"画布宽度被改动：{actual} != {width_in}")
    # 不使用 bbox_inches='tight'，否则输出尺寸会偏离 6.30 英寸
    path = str(path)
    fig.savefig(path, dpi=DPI, facecolor="white")
    if path.lower().endswith(".png"):
        fig.savefig(path[:-4] + ".pdf", facecolor="white")
    plt.close(fig)
