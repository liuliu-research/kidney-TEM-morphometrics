"""复用历史图1生成器，仅修订两处标题，冻结数据与历史文件。"""

from __future__ import annotations

import hashlib
import os
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
import numpy as np

WORK = Path(__file__).resolve().parents[1]
PROJECT = WORK
LEGACY = PROJECT / "scripts"
OUT = Path(os.environ.get("TEM_FIGURE_OUTPUT_DIR", str(WORK / "generated_figures")))
EXPECTED = {
    "build_fig1.py": "9e9eb1b31f1fa70686cc3e9e1f6b0d9c27a9700cc4b9ef483a68436f501083be",
    "figstyle.py": "e6273ed23cf60dc2913a0524f16ecc98df8f67028b3d29506c3edf1ccb117b20",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def data_digest(fig) -> str:
    """绑定图元数值、坐标范围和非标题文字，不包含允许改动的标题。"""
    digest = hashlib.sha256()
    for ax in fig.axes:
        digest.update(repr((ax.get_xlim(), ax.get_ylim())).encode())
        digest.update(repr((ax.get_xlabel(), ax.get_ylabel())).encode())
        for label in [*ax.texts, *ax.get_xticklabels(), *ax.get_yticklabels()]:
            digest.update(repr((label.get_text(), label.get_position())).encode())
        for patch in ax.patches:
            digest.update(np.asarray(patch.get_path().vertices).tobytes())
            digest.update(
                np.asarray(patch.get_patch_transform().get_matrix()).tobytes()
            )
        for line in ax.lines:
            digest.update(np.asarray(line.get_xydata()).tobytes())
        for item in ax.collections:
            digest.update(np.asarray(item.get_offsets()).tobytes())
            if hasattr(item, "get_segments"):
                for segment in item.get_segments():
                    digest.update(np.asarray(segment).tobytes())
        for item in ax.images:
            arr = np.ma.asarray(item.get_array())
            digest.update(np.asarray(arr.data).tobytes())
            digest.update(np.ma.getmaskarray(arr).tobytes())
    return digest.hexdigest()


def main() -> None:
    for name, expected in EXPECTED.items():
        if sha(LEGACY / name) != expected:
            raise RuntimeError(f"历史生成器已改变，需重新审阅：{name}")
    spec = importlib.util.spec_from_file_location(
        "r2_legacy_fig1", LEGACY / "build_fig1.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inputs = {str(path): sha(path) for path in sorted(module.SRC.glob("figure1_*.csv"))}
    if len(inputs) != 5:
        raise RuntimeError("图1源CSV数量与已审阅输入不一致")
    original_save = module.save
    module.OUT = OUT
    receipt = {}

    def save_revision(fig, path):
        old_panel = "Annual workload\n(hatched = partial boundary year)"
        old_title = (
            "Locked-registry cohort and workload overview (May 2014 to April 2026)"
        )
        if (
            fig.axes[1].get_title() != old_panel
            or fig._suptitle.get_text() != old_title
        ):
            raise RuntimeError("图1标题与已审阅版本不一致")
        before = data_digest(fig)
        fig.axes[1].set_title(
            "Annual examination volume\n(hatched = partial boundary year)"
        )
        fig._suptitle.set_text(
            "Locked-registry cohort and examination volume (May 2014 to April 2026)"
        )
        after = data_digest(fig)
        if before != after:
            raise RuntimeError("标题更新意外改变了数值图元或其他标签")
        receipt.update(
            numeric_artist_sha256_before=before,
            numeric_artist_sha256_after=after,
            canvas_inches=fig.get_size_inches().tolist(),
            updated_titles=[fig._suptitle.get_text(), fig.axes[1].get_title()],
        )
        original_save(fig, path)

    module.save = save_revision
    module.main()
    if any(sha(Path(path)) != checksum for path, checksum in inputs.items()):
        raise RuntimeError("只读源CSV发生变化")
    receipt.update(
        status="PASS_LABEL_ONLY_DATA_INVARIANT",
        created_at=datetime.now(timezone.utc).isoformat(),
        source_csv_sha256=inputs,
        legacy_code_sha256=EXPECTED,
        adapter_sha256=sha(Path(__file__)),
        matplotlib_version=matplotlib.__version__,
        output_sha256={
            name: sha(OUT / name) for name in ("Figure1.png", "Figure1.pdf")
        },
        scope="仅两处图题；数据图元不变；未验证人工审计或投稿就绪",
    )
    (OUT / "figure1_label_revision.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {"status": receipt["status"], "output": str(OUT)}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
