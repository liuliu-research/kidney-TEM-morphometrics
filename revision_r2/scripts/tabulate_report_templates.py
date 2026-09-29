"""按分期统计 8,113 条入模记录的报告模板格式（逐项式 vs 叙述式），只输出聚合计数。

模板判定只看版式标志（是否出现逐项标题“肾小球：”“肾小球硬化：”），不做任何字段判读。
另做一项仅供内部预期的模式搜索（叙述式报告开头是否写明肾小球个数/基质分级），
结果单独标记为 internal_expectation，不进入稿件。
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

DATA_ROOT = Path(os.environ["PATHOLOGY_V2_ROOT"]).expanduser().resolve()
os.environ["PATHOLOGY_V2_ROOT"] = str(DATA_ROOT)
PROJECT_ROOT = Path(os.environ.get("TEM_FROZEN_REPO", str(Path(__file__).resolve().parents[2]))).resolve()
REPO_SCRIPTS = PROJECT_ROOT / "scripts"
OUT = Path(os.environ["TEM_TEMPLATE_OUTPUT"]).expanduser().resolve()
sys.path.insert(0, str(REPO_SCRIPTS))
import remote_v2_modeling as rvm  # noqa: E402

ITEMISED = re.compile(r"肾小球[:：]\s*总数|肾小球硬化[:：]")
NARRATIVE_COUNT = re.compile(r"(\d+)\s*个肾小球")
NARRATIVE_MATRIX = re.compile(r"基质(无明显|未见明显|轻度|轻-中度|轻中度|中度|中-重度|中重度|重度)增生")


def locate(visit_id: str) -> Path:
    hits = list((DATA_ROOT / "肾病分类").glob(f"*/诊断报告/{visit_id}.txt"))
    if len(hits) != 1:
        raise SystemExit(f"[FAIL] 报告定位失败: {visit_id} -> {len(hits)}")
    return hits[0]


def main() -> None:
    linked, _ = rvm.build_dataset()
    by_split_template: dict[str, Counter] = {"development": Counter(), "temporal_test": Counter()}
    by_year_template: dict[int, Counter] = {}
    expectation = {"development": Counter(), "temporal_test": Counter()}
    for _, rec in linked.iterrows():
        text = locate(str(rec["visit_id"])).read_text(encoding="utf-8", errors="replace")
        template = "itemised" if ITEMISED.search(text) else "narrative"
        split = str(rec["split"])
        by_split_template[split][template] += 1
        year = int(str(rec["song_ymd"])[:4])
        by_year_template.setdefault(year, Counter())[template] += 1
        if template == "narrative":
            exp = expectation[split]
            exp["narrative_n"] += 1
            exp["narrative_states_glomerulus_count"] += bool(NARRATIVE_COUNT.search(text))
            exp["narrative_states_matrix_grade"] += bool(NARRATIVE_MATRIX.search(text))
            exp["legacy_table_has_glomerulus_count"] += int(not (rec["glomerulus_count"] != rec["glomerulus_count"]))
            exp["legacy_table_has_matrix_grade"] += int(not (rec["mesangial_matrix_grade"] != rec["mesangial_matrix_grade"]))
    payload = {
        "definition": {
            "itemised": "report contains the itemised headings '肾小球：总数' or '肾小球硬化：'",
            "narrative": "all other reports (running-text template)",
        },
        "by_split": {s: dict(c) for s, c in by_split_template.items()},
        "by_year": {str(y): dict(by_year_template[y]) for y in sorted(by_year_template)},
        "internal_expectation_not_for_manuscript": {s: dict(c) for s, c in expectation.items()},
        "n_records": int(len(linked)),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
