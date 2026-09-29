"""事后敏感性分析：补齐旧结构化步骤对叙述式模板的覆盖缺口后重抽七个字段并重跑模型。

原则：
- 字段语义与冻结解析器完全一致（复用 remote_v2_modeling 的 parse_* 函数）；
- 只在旧结构化表单元格为空时，才用叙述式模板的确定性模式从报告原文补一个"单元格"；
- 队列、分期、标签、模型、网格、种子与 bootstrap 均不变；
- 只输出聚合 JSON，不输出任何行级记录。
同时把重抽取值写入审计密钥（reextracted 字段），供同一份人工读取表一并验证。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.base import clone
from sklearn.exceptions import ConvergenceWarning

DATA_ROOT = Path(os.environ["PATHOLOGY_V2_ROOT"]).expanduser().resolve()
os.environ["PATHOLOGY_V2_ROOT"] = str(DATA_ROOT)
OUT_NAME = os.environ.get("REEXTRACT_OUT_NAME", "reextraction_sensitivity_results.json")
SKIP_KEY = os.environ.get("REEXTRACT_SKIP_KEY", "1") == "1"
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = Path(os.environ.get("TEM_FROZEN_REPO", str(Path(__file__).resolve().parents[2]))).resolve()
REPO_SCRIPTS = PROJECT_ROOT / "scripts"
FROZEN = PROJECT_ROOT / "aggregate_results" / "v2_modeling_results.json"
AUDIT_DIR = Path(os.environ.get("TEM_AUDIT_OUTPUT_DIR", str(HERE.parent / "controlled_runtime")))
OUT_JSON = Path(os.environ["TEM_REEXTRACTION_OUTPUT"]).expanduser().resolve()
sys.path.insert(0, str(REPO_SCRIPTS))
import remote_v2_modeling as rvm  # noqa: E402

CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
RE_BODY_START = re.compile(r"(电镜[下]?观察[^\n]*[:：]?|肾小球[:：]\s*总数)")
RE_DIAG = re.compile(r"电镜诊断")
RE_GLOM_NARR = re.compile(r"([0-9]+|[一二两三四五六七八九十]+)\s*个肾小球")
RE_GLOM_ITEM = re.compile(r"肾小球[:：]\s*总数\s*([^\n。；;，,]{1,12})")
RE_SCLER_ITEM = re.compile(r"肾小球硬化[:：]\s*([^\n]{1,60})")
RE_SCLER_NARR_CN = re.compile(r"([0-9]+|[一二两三四五六七八九十]+)\s*个肾小球(?:呈|为|见)?(?:球性硬化|球性纤维化)")
RE_MATRIX_AFTER = re.compile(r"基质(?!内)([^，,；;。\n]{0,15})")
RE_MATRIX_ANY = re.compile(r"(无明显增生|未见明显增生|不增生|无增生|轻[-~—至]?中度增生|轻中度增生|中[-~—至]?重度增生|中重度增生|轻度增生|中度增生|重度增生)")
RE_GBM_PAREN = re.compile(r"基底膜[^，,；;。（(\n]{0,6}[（(]([^）)]{1,30})[）)]")
RE_GBM_INLINE = re.compile(r"基底膜[^，,；;。\n]{0,6}?(\d+(?:\.\d+)?(?:\s*[-~—至]\s*\d+(?:\.\d+)?)?\s*(?:nm|μm|um|微米|纳米))")
RE_MES_CELLS = re.compile(r"(\d+(?:\.\d+)?\s*(?:[-~—至]\s*\d+(?:\.\d+)?)?\s*个?\s*/\s*区)")
RE_SPIKE_CLAUSE = re.compile(r"[^，,；;。\n]*钉突[^，,；;。\n]*")
RE_FOOT_CLAUSE = re.compile(r"足突[^，,；;。\n]{0,30}")


def cn_int(token: str) -> float:
    if token.isdigit():
        return float(token)
    if token == "十":
        return 10.0
    if len(token) == 1:
        return float(CN_NUM.get(token, float("nan")))
    if token.startswith("十"):
        return 10.0 + CN_NUM.get(token[1:], 0)
    if token.endswith("十"):
        return 10.0 * CN_NUM.get(token[0], 0)
    return float("nan")


def observation_body(text: str) -> str:
    """只保留电镜观察描述（去抬头、去诊断与签名）。"""

    text = unicodedata.normalize("NFC", text)
    start = RE_BODY_START.search(text)
    body = text[start.start():] if start else text
    diag = RE_DIAG.search(body)
    if diag:
        body = body[: diag.start()]
    return body


def narrative_cells(body: str) -> dict[str, str | None]:
    """从报告观察段产生与旧结构化表同语义的七个"单元格"文本。"""

    cells: dict[str, str | None] = {c: None for c in rvm.RAW_MORPH_COLUMNS}
    m = RE_GLOM_ITEM.search(body)
    if m:
        cells["肾小球总数"] = m.group(1)
    else:
        m = RE_GLOM_NARR.search(body)
        if m:
            value = cn_int(m.group(1))
            if value == value:
                cells["肾小球总数"] = f"{int(value)}个"
    m = RE_SCLER_ITEM.search(body)
    if m:
        cells["肾小球硬化"] = m.group(1)
    else:
        m = RE_SCLER_NARR_CN.search(body)
        if m:
            value = cn_int(m.group(1))
            if value == value:
                cells["肾小球硬化"] = f"球性{int(value)}个"
        else:
            explicit = re.search(r"(?<!趋于)(?<!接近)(?<!缺血性)球性(?:硬化)?\s*\d+\s*个|节段性(?:硬化)?\s*\d+\s*个", body)
            if explicit:
                cells["肾小球硬化"] = body[max(0, explicit.start() - 12): explicit.end() + 12]
    m = RE_MES_CELLS.search(body)
    if m:
        cells["系膜细胞数/区"] = m.group(1)
    matrix = None
    for m in RE_MATRIX_AFTER.finditer(body):
        probe = "基质" + m.group(1)
        if rvm.parse_matrix_grade(probe) == rvm.parse_matrix_grade(probe):
            matrix = probe
            break
    if matrix is None:
        clause = re.search(r"系膜[^；;。\n]*", body)
        if clause:
            m = RE_MATRIX_ANY.search(clause.group(0))
            if m:
                matrix = m.group(1)
    cells["系膜基质增生程度"] = matrix
    m = RE_GBM_PAREN.search(body)
    if m:
        cells["基底膜厚度"] = m.group(1)
    else:
        m = RE_GBM_INLINE.search(body)
        if m:
            cells["基底膜厚度"] = m.group(1)
    m = RE_SPIKE_CLAUSE.search(body)
    if m:
        cells["钉突有无"] = m.group(0)
    m = RE_FOOT_CLAUSE.search(body)
    if m:
        cells["足突融合程度"] = m.group(0)
    return cells


def parse_cells(cells: dict[str, Any]) -> dict[str, float]:
    return {
        "glomerulus_count": rvm.parse_glomerulus_count(cells["肾小球总数"]),
        "sclerosis_rate": rvm.parse_sclerosis_rate(cells["肾小球硬化"], cells["肾小球总数"]),
        "mesangial_cell_count": rvm.parse_mesangial_cells(cells["系膜细胞数/区"]),
        "mesangial_matrix_grade": rvm.parse_matrix_grade(cells["系膜基质增生程度"]),
        "gbm_thickness_nm": rvm.parse_gbm(cells["基底膜厚度"]),
        "spike_presence": rvm.parse_spike(cells["钉突有无"]),
        "foot_process_grade": rvm.parse_foot_process(cells["足突融合程度"]),
    }


def locate(visit_id: str) -> Path:
    hits = list((DATA_ROOT / "肾病分类").glob(f"*/诊断报告/{visit_id}.txt"))
    if len(hits) != 1:
        raise SystemExit(f"[FAIL] 报告定位失败: {visit_id} -> {len(hits)}")
    return hits[0]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    warnings.filterwarnings("ignore", category=ConvergenceWarning)
    warnings.filterwarnings("ignore", category=FutureWarning)
    started = time.perf_counter()
    linked, audit = rvm.build_dataset()
    legacy = pd.read_excel(rvm.MORPHOMETRY, sheet_name="分类汇总")
    fill_counts: dict[str, Counter] = {s: Counter() for s in ["development", "temporal_test"]}
    reextracted: dict[int, dict[str, float]] = {}
    template_counts: dict[str, Counter] = {s: Counter() for s in ["development", "temporal_test"]}
    for idx, rec in linked.iterrows():
        legacy_row = legacy.loc[int(rec["legacy_index"])]
        cells = {c: (None if pd.isna(legacy_row[c]) else str(legacy_row[c])) for c in rvm.RAW_MORPH_COLUMNS}
        text = locate(str(rec["visit_id"])).read_text(encoding="utf-8", errors="replace")
        body = observation_body(text)
        template = "itemised" if re.search(r"肾小球[:：]\s*总数|肾小球硬化[:：]", text) else "narrative"
        template_counts[str(rec["split"])][template] += 1
        derived = narrative_cells(body)
        for column in rvm.RAW_MORPH_COLUMNS:
            if cells[column] is None and derived.get(column):
                cells[column] = derived[column]
                fill_counts[str(rec["split"])][column] += 1
        reextracted[int(idx)] = parse_cells(cells)
    for key in rvm.MORPH:
        linked[key] = [reextracted[int(i)][key] for i in linked.index]
    for column in rvm.FULL:
        linked[f"missing__{column}"] = linked[column].isna().astype(float)

    missingness = {
        split: {col: round(float(linked.loc[linked["split"] == split, col].isna().mean() * 100), 3) for col in rvm.FULL}
        for split in ["development", "temporal_test"]
    }
    dev = linked.loc[linked["split"] == "development"].copy()
    test = linked.loc[linked["split"] == "temporal_test"].copy()
    y_dev = dev["disease_code"].to_numpy()
    y_test = test["disease_code"].to_numpy()
    feature_sets = {
        "full": rvm.FULL,
        "full_minus_age": rvm.FULL_MINUS_AGE,
        "age_sex_only": rvm.AGE_SEX,
        "morphometry_only": rvm.MORPH,
        "missingness_only_diagnostic": rvm.MISSINGNESS,
    }
    specs = rvm.model_specs("full")
    results: dict[str, Any] = {}
    for fs_name, columns in feature_sets.items():
        rvm.progress(f"Feature set: {fs_name}")
        results[fs_name] = {}
        models = specs if fs_name == "full" else {"random_forest": specs["random_forest"]}
        for model_name, (estimator, grid, use_weight) in models.items():
            _, result = rvm.train_one(model_name, clone(estimator), grid, use_weight, dev[columns], y_dev, test[columns], y_test, n_boot=300)
            results[fs_name][model_name] = result

    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    comparison = {}
    for model_name in specs:
        comparison[model_name] = {
            "frozen_macro_f1": frozen["model_results"]["full"][model_name]["temporal_test"]["macro_f1"],
            "frozen_ci": frozen["model_results"]["full"][model_name]["temporal_test"]["bootstrap_95ci"]["macro_f1"],
            "reextracted_macro_f1": results["full"][model_name]["temporal_test"]["macro_f1"],
            "reextracted_ci": results["full"][model_name]["temporal_test"]["bootstrap_95ci"]["macro_f1"],
            "frozen_macro_auc": frozen["model_results"]["full"][model_name]["temporal_test"]["macro_ovr_auc"],
            "reextracted_macro_auc": results["full"][model_name]["temporal_test"]["macro_ovr_auc"],
        }
    output = rvm.clean_json(
        {
            "report_type": "post_hoc_template_aware_reextraction_sensitivity",
            "generated_date": "2026-09-29",
            "privacy": {"row_level_records_exported": False, "patient_identifiers_exported": False, "output_scope": "aggregate JSON only"},
            "definition": {
                "rule": "Legacy structured cells were kept unchanged; only empty cells were filled from the report observation text with deterministic patterns for the narrative template; all field encodings reuse the frozen parser functions.",
                "unchanged": ["cohort", "patient-level split", "labels", "models", "grids", "seed 20260722", "300 bootstrap replicates"],
                "registry_sha256": sha256_file(rvm.REGISTRY),
                "morphometry_sha256": sha256_file(rvm.MORPHOMETRY),
                "frozen_results_sha256": sha256_file(FROZEN),
            },
            "runtime": {
                "platform": __import__("platform").platform(),
                "machine": __import__("platform").machine(),
                "python": __import__("platform").python_version(),
                "numpy": __import__("numpy").__version__,
                "pandas": pd.__version__,
                "sklearn": __import__("sklearn").__version__,
            },
            "template_counts": {s: dict(c) for s, c in template_counts.items()},
            "cells_filled_from_text": {s: dict(c) for s, c in fill_counts.items()},
            "feature_missingness_pct_frozen": frozen["audit"]["feature_missingness_pct"],
            "feature_missingness_pct_reextracted": missingness,
            "model_results": results,
            "comparison_full_feature_set": comparison,
            "runtime_seconds": round(time.perf_counter() - started, 1),
        }
    )
    OUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    if SKIP_KEY:
        print(json.dumps({k: output[k] for k in ["runtime", "template_counts", "cells_filled_from_text", "feature_missingness_pct_reextracted", "comparison_full_feature_set", "runtime_seconds"]}, ensure_ascii=False, indent=2))
        return
    key_path = AUDIT_DIR / "audit_key_CONFIDENTIAL.json"
    key = json.loads(key_path.read_text(encoding="utf-8"))
    for row in key["rows"]:
        values = reextracted[int(row["linked_index"])]
        row["reextracted"] = {k: (None if v != v else float(v)) for k, v in values.items()}
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    manifest_path = AUDIT_DIR / "audit_sample_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outputs"]["key_sha256"] = sha256_file(key_path)
    manifest["outputs"]["key_includes_reextracted_values"] = True
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: output[k] for k in ["template_counts", "cells_filled_from_text", "feature_missingness_pct_reextracted", "comparison_full_feature_set", "runtime_seconds"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
