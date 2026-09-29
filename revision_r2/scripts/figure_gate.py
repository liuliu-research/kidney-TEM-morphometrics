"""Unchanged project figure gate; not a copied public implementation."""
import matplotlib.pyplot as plt
from figstyle import COL_W_IN

def rects_overlap(a, b, tol: float = 0.5) -> bool:
    return not (a.x1 - tol <= b.x0 or b.x1 - tol <= a.x0
                or a.y1 - tol <= b.y0 or b.y1 - tol <= a.y0)

def collect_texts(ax):
    texts = list(ax.texts)
    texts += ax.get_xticklabels() + ax.get_yticklabels()
    for item in (ax.title, ax.xaxis.label, ax.yaxis.label):
        if item.get_text():
            texts.append(item)
    leg = ax.get_legend()
    if leg is not None:
        texts += list(leg.get_texts())
        if leg.get_title() is not None and leg.get_title().get_text():
            texts.append(leg.get_title())
    return texts

def gate(fig) -> tuple[list[str], list[float], list[str]]:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    problems: list[str] = []

    w = fig.get_size_inches()[0]
    if abs(w - COL_W_IN) > 1e-6:
        problems.append(f"  [宽度] {w:.3f} in != {COL_W_IN} in")

    fonts, sizes = set(), []
    n_overlap = 0

    for ax_i, ax in enumerate(fig.axes):
        items = []
        for t in collect_texts(ax):
            s = t.get_text()
            if not s or not s.strip() or not t.get_visible():
                continue
            # axis("off") 的面板上残留的隐藏刻度不参与判定
            if not ax.axison and t in (ax.get_xticklabels() + ax.get_yticklabels()):
                continue
            fonts.add(t.get_fontname())
            sizes.append(round(t.get_fontsize(), 2))
            try:
                items.append((s, t.get_window_extent(renderer=renderer)))
            except Exception:  # noqa: BLE001
                continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if rects_overlap(items[i][1], items[j][1]):
                    n_overlap += 1
                    if n_overlap <= 6:
                        problems.append(
                            f"  [重叠] 子图#{ax_i}: "
                            f"{items[i][0][:34]!r} <-> {items[j][0][:34]!r}"
                        )
    if n_overlap > 6:
        problems.append(f"  [重叠] ……另有 {n_overlap - 6} 处")

    for t in fig.texts:
        if t.get_text().strip():
            fonts.add(t.get_fontname())
            sizes.append(round(t.get_fontsize(), 2))

    bad = {f for f in fonts if f != "Arial"}
    if bad:
        problems.append(f"  [字体] 非 Arial: {sorted(bad)}")
    if sizes and min(sizes) < 8.0 - 1e-6:
        problems.append(f"  [字号] 存在 < 8pt 的文字，最小 {min(sizes)}pt")

    return problems, sorted(set(sizes)), sorted(fonts)
