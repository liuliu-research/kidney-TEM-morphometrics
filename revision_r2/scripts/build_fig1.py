# -*- coding: utf-8 -*-
"""Figure 1：锁定登记库队列构成与工作量（A-E 五个子图）。

数值全部来自已发布的去标识化聚合源数据 CSV，脚本不做任何再计算。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figstyle import (  # noqa: E402
    COL_W_IN, COLORS, FS_BASE, FS_SUP, apply_style, clean_heatmap_axes,
    panel_label, save, value_axis_grid,
)
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "source_data"
OUT = HERE.parent / "generated_figures"

MAIN11 = ["IgAN", "IgAVN", "MCD", "MN", "MsPGN", "LN",
          "EPGN", "DKD", "TBMN", "FSGS", "MPGN"]
AGE_BANDS = ["0-9", "10-17", "18-39", "40-59", "60+"]
AGE_COLORS = ["#DCEBF5", "#A7CCE3", "#6BA5CA", "#3B7CA8", "#1F4E6E"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(SRC / name, encoding="utf-8-sig")


# ------------------------------------------------------------------ A
def panel_a(ax) -> None:
    """全部 10,933 次检查的类别构成。"""
    df = read("figure1_class_counts.csv")
    labels, vals, pcts, cols = [], [], [], []
    for _, r in df.iterrows():
        name = str(r["category"])
        labels.append("Long-tail (8)" if name.startswith("Long-tail") else name)
        vals.append(int(r["n"]))
        pcts.append(float(r["percent"]))
        cols.append({"main11": COLORS["blue"], "other": COLORS["grey"],
                     "long_tail": COLORS["orange"]}[r["group_type"]])

    y = np.arange(len(labels))
    xmax = max(vals) * 1.06
    value_axis_grid(ax, "x")
    ax.barh(y, vals, height=0.68, color=cols, edgecolor="white",
            linewidth=0.4, zorder=2)

    # 长柱标签放柱内（白字），短柱放柱外（黑字），避免标签越出坐标区
    for yi, v, p in zip(y, vals, pcts):
        text = f"{v:,} ({p:.1f}%)"
        if v > 0.46 * xmax:
            ax.text(v - 0.012 * xmax, yi, text, va="center", ha="right",
                    fontsize=FS_BASE, color="white", zorder=3)
        else:
            ax.text(v + 0.012 * xmax, yi, text, va="center", ha="left",
                    fontsize=FS_BASE, color="#222222", zorder=3)

    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlim(0, xmax)
    ax.set_xticks([0, 1000, 2000])
    ax.set_xlabel("Canonical examinations, n")
    ax.set_title("Locked-registry class composition")


# ------------------------------------------------------------------ B
def panel_b(ax) -> None:
    """按日历年的检查量，斜纹表示不完整的边界年。"""
    df = read("figure1_annual_volume.csv")
    x = np.arange(len(df))
    vals = df["annual_checks"].to_numpy()
    partial = df["partial_year"].astype(str).str.lower().eq("true").to_numpy()

    value_axis_grid(ax, "y")
    for xi, v, p in zip(x, vals, partial):
        ax.bar(xi, v, width=0.72, color=COLORS["blue"], zorder=2,
               edgecolor=COLORS["navy"] if p else "white", linewidth=0.5,
               hatch="///" if p else None, alpha=0.55 if p else 1.0)
        ax.text(xi, v + 0.02 * vals.max(), f"{v:,}", ha="center", va="bottom",
                rotation=90, fontsize=FS_BASE, color="#222222")

    ax.set_xticks(x)
    ax.set_xticklabels([str(y)[-2:] for y in df["year"]])
    ax.set_ylim(0, vals.max() * 1.40)
    ax.set_xlabel("Calendar year (20xx)")
    ax.set_ylabel("Canonical examinations")
    ax.set_title("Annual workload\n(hatched = partial boundary year)")


# ------------------------------------------------------------------ C
def panel_c(ax) -> None:
    """主 11 类的患者优先年龄分布（堆叠百分比）。"""
    df = read("figure1_age_distribution.csv")
    pivot = df.pivot_table(index="disease", columns="age_band",
                           values="percent", aggfunc="sum").reindex(MAIN11)
    pivot = pivot[AGE_BANDS]
    y = np.arange(len(MAIN11))

    value_axis_grid(ax, "x")
    left = np.zeros(len(MAIN11))
    for band, colour in zip(AGE_BANDS, AGE_COLORS):
        vals = pivot[band].to_numpy(dtype=float)
        ax.barh(y, vals, left=left, height=0.70, color=colour,
                edgecolor="white", linewidth=0.35, label=band, zorder=2)
        left += vals

    ax.set_yticks(y)
    ax.set_yticklabels(MAIN11)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Age distribution among non-missing values (%)")
    ax.set_title("Patient-first age distribution, main 11")
    ax.legend(title="Age (years)", loc="lower center",
              bbox_to_anchor=(0.5, 1.10), ncol=5, handlelength=0.9,
              columnspacing=0.6, handletextpad=0.35,
              title_fontsize=FS_BASE, alignment="center")


# ------------------------------------------------------------------ D
def panel_d(ax) -> None:
    """主 11 类的男性比例与 Wilson 95% 置信区间。"""
    df = read("figure1_sex_proportion.csv").set_index("disease").reindex(MAIN11)
    y = np.arange(len(MAIN11))
    p = df["male_percent"].to_numpy(dtype=float)
    lo = p - df["male_ci_low"].to_numpy(dtype=float)
    hi = df["male_ci_high"].to_numpy(dtype=float) - p

    value_axis_grid(ax, "x")
    ax.errorbar(p, y, xerr=[lo, hi], fmt="o", ms=3.2, color=COLORS["navy"],
                ecolor=COLORS["navy"], elinewidth=0.8, capsize=1.6,
                capthick=0.8, zorder=3, linestyle="none")
    ax.axvline(50, color=COLORS["grey"], lw=0.6, ls="--", zorder=1)

    # n 标签统一右对齐到固定列，互不干扰
    for yi, n in zip(y, df["nonmissing_n"].astype(int)):
        ax.text(103, yi, f"n = {n:,}", va="center", ha="left",
                fontsize=FS_BASE, color="#222222")

    ax.set_yticks(y)
    ax.set_yticklabels(MAIN11)
    ax.invert_yaxis()
    ax.set_xlim(0, 132)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Male proportion among non-missing sex (%)")
    ax.set_title("Patient-first sex distribution (Wilson 95% CI)")


# ------------------------------------------------------------------ E
def panel_e(ax, cax) -> None:
    """按年-月的检查量热图，窗口外单元格置灰。"""
    df = read("figure1_year_month.csv")
    years = sorted(df["year"].unique())
    mat = np.full((len(years), 12), np.nan)
    for _, r in df.iterrows():
        if str(r["observed"]).lower() == "true" and pd.notna(r["n"]):
            mat[years.index(r["year"]), int(r["month"]) - 1] = float(r["n"])

    norm = Normalize(vmin=np.nanmin(mat), vmax=np.nanmax(mat))
    cmap = plt.get_cmap("YlGnBu").copy()
    cmap.set_bad("#E8E8E8")  # 分析窗口之外
    im = ax.imshow(np.ma.masked_invalid(mat), cmap=cmap, norm=norm, aspect="auto")
    clean_heatmap_axes(ax)

    for i in range(len(years)):
        for j in range(12):
            v = mat[i, j]
            if np.isnan(v):
                ax.text(j, i, "NA", ha="center", va="center",
                        fontsize=FS_BASE, color="#8A8A8A")
            else:
                # 自适应字色，保证任何底色上都可读
                ax.text(j, i, f"{int(v)}", ha="center", va="center",
                        fontsize=FS_BASE,
                        color="white" if norm(v) > 0.58 else "#1A1A1A")

    ax.set_xticks(np.arange(12))
    ax.set_xticklabels(MONTHS)
    ax.set_yticks(np.arange(len(years)))
    ax.set_yticklabels([str(y) for y in years])
    ax.tick_params(length=1.4, pad=1.2)
    ax.set_xlabel("Month")
    ax.set_ylabel("Year")
    ax.set_title("Canonical examinations by year and month "
                 "(grey = outside analysis window; April 2026 ends on day 9)")

    cb = ax.figure.colorbar(im, cax=cax)
    cb.set_label("Examinations, n", fontsize=FS_BASE)
    cb.ax.tick_params(labelsize=FS_BASE, length=1.4, pad=1.0, width=0.6)
    cb.outline.set_linewidth(0.6)
    cb.outline.set_edgecolor(COLORS["axis"])


def main() -> None:
    apply_style()
    OUT.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(COL_W_IN, 8.10), layout="constrained")
    fig.get_layout_engine().set(w_pad=0.045, h_pad=0.045, wspace=0.05, hspace=0.06)

    gs = fig.add_gridspec(3, 2, height_ratios=[0.95, 0.95, 1.32])
    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[1, 0])
    ax_d = fig.add_subplot(gs[1, 1])
    sub_e = gs[2, :].subgridspec(1, 2, width_ratios=[1, 0.022], wspace=0.02)
    ax_e = fig.add_subplot(sub_e[0, 0])
    cax_e = fig.add_subplot(sub_e[0, 1])

    panel_a(ax_a)
    panel_b(ax_b)
    panel_c(ax_c)
    panel_d(ax_d)
    panel_e(ax_e, cax_e)

    for ax, letter, dx, dy in [
        (ax_a, "A", -0.34, 1.05), (ax_b, "B", -0.26, 1.05),
        (ax_c, "C", -0.22, 1.22), (ax_d, "D", -0.22, 1.05),
        (ax_e, "E", -0.075, 1.03),
    ]:
        panel_label(ax, letter, dx=dx, dy=dy)

    fig.suptitle("Locked-registry cohort and workload overview "
                 "(May 2014 to April 2026)",
                 fontsize=FS_SUP, fontweight="bold")

    w, h = fig.get_size_inches()
    print(f"Figure 1 画布 {w:.3f} x {h:.3f} in")
    save(fig, OUT / "Figure1.png")


if __name__ == "__main__":
    main()
