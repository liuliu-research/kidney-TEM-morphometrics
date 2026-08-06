#!/usr/bin/env python3
"""锁定病理数据地基的只读、患者级、聚合建模复核。

本脚本设计为经 SSH 标准输入在远端执行。它只读取锁定 registry 和旧形态
表，在内存中完成连接、解析、训练和评估，最终仅向 stdout 写一个不含患者标识
的聚合 JSON。进度写入 stderr；远端不创建任何文件。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import unicodedata
import warnings
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.ensemble import (
    AdaBoostClassifier,
    GradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.utils.class_weight import compute_sample_weight

SEED = 20260722
DATA_ROOT_ENV = "PATHOLOGY_V2_ROOT"
if DATA_ROOT_ENV not in os.environ:
    raise RuntimeError(
        f"Set {DATA_ROOT_ENV} to the authorised controlled-data root."
    )
ROOT = Path(os.environ[DATA_ROOT_ENV]).expanduser().resolve()
REGISTRY = ROOT / "registry" / "patient_visit_registry.json"
MORPHOMETRY = ROOT / "分类数据" / "肾脏疾病分类汇总.xlsx"
WINDOW_START = pd.Timestamp("2014-05-01")
WINDOW_END = pd.Timestamp("2026-04-30")
DEV_END = pd.Timestamp("2021-12-31")

MAIN11 = [
    "IgAN",
    "IgAVN",
    "MCD",
    "MN",
    "MsPGN",
    "LN",
    "EPGN",
    "DKD",
    "TBMN",
    "FSGS",
    "MPGN",
]
HEADLINE6 = ["IgAN", "IgAVN", "MCD", "MN", "LN", "FSGS"]

AGE_SEX = ["age", "sex_binary"]
MORPH = [
    "glomerulus_count",
    "sclerosis_rate",
    "mesangial_cell_count",
    "mesangial_matrix_grade",
    "gbm_thickness_nm",
    "spike_presence",
    "foot_process_grade",
]
FULL = AGE_SEX + MORPH
FULL_MINUS_AGE = ["sex_binary"] + MORPH
MISSINGNESS = [f"missing__{column}" for column in FULL]

RAW_MORPH_COLUMNS = [
    "肾小球总数",
    "肾小球硬化",
    "系膜细胞数/区",
    "系膜基质增生程度",
    "基底膜厚度",
    "钉突有无",
    "足突融合程度",
]


def progress(message: str) -> None:
    """把不含记录级内容的进度信息写入 stderr。"""

    print(message, file=sys.stderr, flush=True)


def clean_json(value: Any) -> Any:
    """递归转换 NumPy/Pandas 类型，并将非有限数改为 null。"""

    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def normalize_text(value: Any) -> str:
    """统一全半角、空白和大小写。"""

    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return re.sub(r"\s+", "", text)


def normalize_stem(value: Any) -> str:
    """生成不含路径和扩展名的稳定文件 stem。"""

    if pd.isna(value):
        return ""
    name = str(value).replace("\\", "/").rsplit("/", 1)[-1]
    return normalize_text(Path(name).stem)


def extract_old_p(value: Any) -> str:
    """从文件名提取首个旧报告编码；不把该编码输出到结果。"""

    text = unicodedata.normalize("NFKC", "" if pd.isna(value) else str(value)).upper()
    match = re.search(r"P\s*\d{4,}", text)
    return re.sub(r"\s+", "", match.group(0)) if match else ""


def normalize_sex(value: Any) -> str:
    """将性别保守归一为 M/F/空。"""

    text = normalize_text(value)
    if text in {"男", "男性", "m", "male", "1", "1.0"}:
        return "M"
    if text in {"女", "女性", "f", "female", "0", "0.0"}:
        return "F"
    return ""


def parse_date_series(series: pd.Series) -> pd.Series:
    """宽容解析日期，但不猜测无法识别的值。"""

    return pd.to_datetime(series, errors="coerce", format="mixed").dt.normalize()


def numeric_midpoint(value: Any, require_unit: bool = False) -> float:
    """从单值或范围中提取中点。"""

    if pd.isna(value):
        return float("nan")
    text = unicodedata.normalize("NFKC", str(value)).lower().strip()
    if not text or text in {"-", "--", "/", "nan", "none"}:
        return float("nan")
    if require_unit and not re.search(r"nm|μm|um|微米|纳米", text):
        return float("nan")
    numbers = [float(v) for v in re.findall(r"(?<![a-z])\d+(?:\.\d+)?", text)]
    if not numbers:
        return float("nan")
    result = float(np.mean(numbers[:2])) if len(numbers) >= 2 else numbers[0]
    if re.search(r"μm|um|微米", text):
        result *= 1000.0
    return result


def parse_glomerulus_count(value: Any) -> float:
    """解析肾小球总数。"""

    result = numeric_midpoint(value)
    return result if 0 <= result <= 100 else float("nan")


def parse_age_value(value: Any) -> float:
    """解析旧表年龄字段中的数值或“岁”后缀。"""

    if pd.isna(value):
        return float("nan")
    text = unicodedata.normalize("NFKC", str(value))
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return float("nan")
    result = float(match.group(0))
    return result if 0 <= result <= 110 else float("nan")


def parse_sclerosis_rate(sclerosis: Any, total: Any) -> float:
    """解析球性+节段性硬化肾小球占所见肾小球比例。"""

    denominator = parse_glomerulus_count(total)
    if not math.isfinite(denominator) or denominator <= 0 or pd.isna(sclerosis):
        return float("nan")
    text = unicodedata.normalize("NFKC", str(sclerosis))
    # 只接受明确写出的“球性”和“节段性”计数，趋于/接近/疑似不猜测。
    global_match = re.search(
        r"(?<!趋于)(?<!接近)(?<!缺血性)球性(?:硬化)?\s*(\d+(?:\.\d+)?)\s*个", text
    )
    segmental_match = re.search(r"节段性(?:硬化)?\s*(\d+(?:\.\d+)?)\s*个", text)
    if global_match is None and segmental_match is None:
        return float("nan")
    numerator = 0.0
    if global_match is not None:
        numerator += float(global_match.group(1))
    if segmental_match is not None:
        numerator += float(segmental_match.group(1))
    rate = numerator / denominator
    return rate if 0 <= rate <= 1 else float("nan")


def parse_mesangial_cells(value: Any) -> float:
    """解析每区系膜细胞数，范围取中点。"""

    if pd.isna(value):
        return float("nan")
    text = unicodedata.normalize("NFKC", str(value))
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*[-~—至]\s*(\d+(?:\.\d+)?)\s*个?\s*/?\s*区", text
    )
    if match:
        result = (float(match.group(1)) + float(match.group(2))) / 2.0
    else:
        match = re.search(r"(\d+(?:\.\d+)?)\s*个?\s*/?\s*区", text)
        if not match:
            return float("nan")
        result = float(match.group(1))
    return result if 0 <= result <= 30 else float("nan")


def parse_matrix_grade(value: Any) -> float:
    """将系膜基质增生程度保守映射到 0–3 的序数量表。"""

    if pd.isna(value):
        return float("nan")
    text = normalize_text(value)
    # 优先寻找“基质”之后的局部描述，减少把细胞增生误当基质增生。
    if "基质" in text:
        text = text[text.find("基质") :]
    if re.search(r"无(?:明显)?增生|未见(?:明显)?增生|不增生", text):
        return 0.0
    if re.search(r"中[-~—至]?重度增生|中重度增生", text):
        return 2.5
    if re.search(r"轻[-~—至]?中度增生|轻中度增生", text):
        return 1.5
    if "重度增生" in text:
        return 3.0
    if "中度增生" in text:
        return 2.0
    if "轻度增生" in text:
        return 1.0
    return float("nan")


def parse_gbm(value: Any) -> float:
    """解析 GBM 厚度并统一为 nm。"""

    result = numeric_midpoint(value, require_unit=True)
    return result if 50 <= result <= 5000 else float("nan")


def parse_spike(value: Any) -> float:
    """解析钉突形成（1）、明确未见（0），模糊措辞留空。"""

    if pd.isna(value):
        return float("nan")
    text = normalize_text(value)
    if not text or text in {"-", "--", "/"}:
        return float("nan")
    if re.search(r"无钉突|未见钉突|钉突(?:未|不)形成", text):
        return 0.0
    if re.search(r"形成不明显|疑似|可能", text):
        return float("nan")
    if "形成" in text or "钉突" in text:
        return 1.0
    return float("nan")


def parse_foot_process(value: Any) -> float:
    """将足突融合程度保守映射到 0–3 的序数量表。"""

    if pd.isna(value):
        return float("nan")
    text = normalize_text(value)
    if re.search(r"无融合|未见(?:明显)?融合|足突(?:未|不)融合", text):
        return 0.0
    if re.search(r"广泛性?融合|广泛融合", text):
        if re.search(r"较广泛|大部分", text):
            return 2.0
        return 3.0
    if re.search(r"较广泛|大部分融合", text):
        return 2.0
    if re.search(r"节段性?融合|部分性?融合|少数融合|小节段", text):
        return 1.0
    return float("nan")


def build_unique_map(values: pd.Series) -> dict[str, int]:
    """仅保留出现一次的非空字符串键。"""

    buckets: dict[str, list[int]] = defaultdict(list)
    for idx, key in values.items():
        if key:
            buckets[str(key)].append(int(idx))
    return {key: rows[0] for key, rows in buckets.items() if len(rows) == 1}


def build_linkage(
    registry: pd.DataFrame,
    legacy: pd.DataFrame,
) -> tuple[dict[int, int], dict[int, str], dict[str, Any]]:
    """按预先约定的四级唯一键完成一对一连接。"""

    reg = registry.copy()
    old = legacy.copy()
    reg["_stem"] = reg["report_stem"].map(normalize_stem)
    old["_stem"] = old["文件名称"].map(normalize_stem)
    reg["_old_p"] = reg["old_P"].map(extract_old_p)
    old["_old_p"] = old["文件名称"].map(extract_old_p)
    reg["_sex"] = reg["sex"].map(normalize_sex)
    old["_sex"] = old["性别"].map(normalize_sex)
    reg["_date"] = parse_date_series(reg["song_ymd"])
    old_date = parse_date_series(old["日期"])
    old_time = parse_date_series(old["时间"])
    old["_date"] = old_date.fillna(old_time)
    reg["_birth"] = pd.to_numeric(reg["birth_year_merged"], errors="coerce")
    old_age = old["年龄"].map(parse_age_value)
    old["_birth"] = old["_date"].dt.year - old_age

    candidates: dict[int, list[tuple[int, int, str]]] = defaultdict(list)

    # 1. 对每个旧表行，其 stem 在 registry 中只有一个候选即接受。
    # 旧表可有重复行；最后再按形态字段完整度选一条，因此不能在旧表侧先去重。
    reg_stem_buckets: dict[str, list[int]] = defaultdict(list)
    for ridx, key in reg["_stem"].items():
        if key:
            reg_stem_buckets[str(key)].append(int(ridx))
    for oidx, key in old["_stem"].items():
        hits = reg_stem_buckets.get(str(key), []) if key else []
        if len(hits) == 1:
            candidates[int(oidx)].append((1, hits[0], "exact_stem"))

    # 2. old_P + date，双方组合键均须唯一。
    reg_key2 = reg.apply(
        lambda r: (
            f"{r['_old_p']}|{r['_date'].date()}"
            if r["_old_p"] and pd.notna(r["_date"])
            else ""
        ),
        axis=1,
    )
    old_key2 = old.apply(
        lambda r: (
            f"{r['_old_p']}|{r['_date'].date()}"
            if r["_old_p"] and pd.notna(r["_date"])
            else ""
        ),
        axis=1,
    )
    reg2_buckets: dict[str, list[int]] = defaultdict(list)
    for ridx, key in reg_key2.items():
        if key:
            reg2_buckets[str(key)].append(int(ridx))
    for oidx, key in old_key2.items():
        hits = reg2_buckets.get(str(key), []) if key else []
        if len(hits) == 1:
            candidates[int(oidx)].append((2, hits[0], "old_p_date"))

    # 3. old_P + sex + birth year ±1。候选并集必须唯一。
    reg_triplets: dict[tuple[str, str, int], list[int]] = defaultdict(list)
    for ridx, row in reg.iterrows():
        if row["_old_p"] and row["_sex"] and pd.notna(row["_birth"]):
            reg_triplets[(row["_old_p"], row["_sex"], int(row["_birth"]))].append(
                int(ridx)
            )
    for oidx, row in old.iterrows():
        if not row["_old_p"] or not row["_sex"] or pd.isna(row["_birth"]):
            continue
        union: set[int] = set()
        birth = int(row["_birth"])
        for delta in (-1, 0, 1):
            union.update(
                reg_triplets.get((row["_old_p"], row["_sex"], birth + delta), [])
            )
        if len(union) == 1:
            candidates[int(oidx)].append((3, next(iter(union)), "old_p_sex_birth_pm1"))

    # 4. old_P 在 canonical registry 中唯一；旧表重复行留到最终完整度决策。
    reg4 = build_unique_map(reg["_old_p"])
    for oidx, key in old["_old_p"].items():
        if key and key in reg4:
            candidates[int(oidx)].append((4, reg4[str(key)], "unique_old_p"))

    # 每个旧表行按最高优先级选一个 registry；同一 registry 多旧行时，选择
    # 7 个源字段非空最多者，再按方法优先级和旧表稳定行序。
    tentative: list[tuple[int, int, int, str, int]] = []
    for oidx, choices in candidates.items():
        best_priority = min(item[0] for item in choices)
        best_regs = {item[1] for item in choices if item[0] == best_priority}
        if len(best_regs) != 1:
            continue
        ridx = next(iter(best_regs))
        method = next(
            item[2] for item in choices if item[0] == best_priority and item[1] == ridx
        )
        completeness = int(old.loc[oidx, RAW_MORPH_COLUMNS].notna().sum())
        tentative.append((ridx, oidx, best_priority, method, completeness))

    by_reg: dict[int, list[tuple[int, int, int, str, int]]] = defaultdict(list)
    for item in tentative:
        by_reg[item[0]].append(item)
    links: dict[int, int] = {}
    link_methods: dict[int, str] = {}
    method_counts: Counter[str] = Counter()
    duplicate_old_rows_resolved = 0
    for ridx, choices in by_reg.items():
        if len(choices) > 1:
            duplicate_old_rows_resolved += len(choices) - 1
        winner = sorted(choices, key=lambda x: (-x[4], x[2], x[1]))[0]
        links[int(ridx)] = int(winner[1])
        link_methods[int(ridx)] = winner[3]
        method_counts[winner[3]] += 1

    audit = {
        "canonical_registry_rows": int(len(reg)),
        "legacy_rows": int(len(old)),
        "linked_registry_rows": int(len(links)),
        "linked_pct": round(100.0 * len(links) / len(reg), 3),
        "method_counts": dict(method_counts),
        "duplicate_old_rows_resolved": duplicate_old_rows_resolved,
        "publication_caveat": (
            "Fallback links (all methods other than exact_stem) require a manually "
            "audited linkage sample before inferential publication use."
        ),
    }
    return links, link_methods, audit


def build_dataset() -> tuple[pd.DataFrame, dict[str, Any]]:
    """载入、患者首诊去重、连接旧形态字段并解析成 9 个输入。"""

    progress("Loading canonical registry and legacy morphometry workbook...")
    records = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry = pd.DataFrame(records)
    registry = (
        registry.loc[registry["is_canonical"].astype(bool)]
        .copy()
        .reset_index(drop=True)
    )
    legacy = pd.read_excel(MORPHOMETRY, sheet_name="分类汇总")
    links, link_methods, linkage_audit = build_linkage(registry, legacy)

    registry["date"] = parse_date_series(registry["song_ymd"])
    in_window = registry["date"].between(WINDOW_START, WINDOW_END, inclusive="both")
    window = registry.loc[in_window].copy()
    window = window.sort_values(["date", "visit_id"], kind="stable")
    first = window.drop_duplicates(subset=["PT"], keep="first").copy()
    first_main = first.loc[first["disease_code"].isin(MAIN11)].copy()
    first_main["registry_index"] = first_main.index.astype(int)
    first_main["legacy_index"] = first_main["registry_index"].map(links)
    linked = first_main.loc[first_main["legacy_index"].notna()].copy()
    linked["legacy_index"] = linked["legacy_index"].astype(int)
    linked["link_method"] = linked["registry_index"].map(link_methods)
    old_rows = legacy.loc[linked["legacy_index"], RAW_MORPH_COLUMNS].reset_index(
        drop=True
    )
    linked = linked.reset_index(drop=True)

    linked["age"] = pd.to_numeric(linked["age"], errors="coerce")
    linked["age"] = linked["age"].where(linked["age"].between(0, 110))
    linked["sex_binary"] = linked["sex"].map(normalize_sex).map({"M": 1.0, "F": 0.0})
    linked["glomerulus_count"] = old_rows["肾小球总数"].map(parse_glomerulus_count)
    linked["sclerosis_rate"] = [
        parse_sclerosis_rate(s, n)
        for s, n in zip(old_rows["肾小球硬化"], old_rows["肾小球总数"], strict=True)
    ]
    linked["mesangial_cell_count"] = old_rows["系膜细胞数/区"].map(
        parse_mesangial_cells
    )
    linked["mesangial_matrix_grade"] = old_rows["系膜基质增生程度"].map(
        parse_matrix_grade
    )
    linked["gbm_thickness_nm"] = old_rows["基底膜厚度"].map(parse_gbm)
    linked["spike_presence"] = old_rows["钉突有无"].map(parse_spike)
    linked["foot_process_grade"] = old_rows["足突融合程度"].map(parse_foot_process)
    for column in FULL:
        linked[f"missing__{column}"] = linked[column].isna().astype(float)
    linked["split"] = np.where(
        linked["date"] <= DEV_END, "development", "temporal_test"
    )

    audit = {
        "v2_source": {
            "registry": str(REGISTRY),
            "morphometry": str(MORPHOMETRY),
            "access": "read_only_in_memory",
            "sklearn_version": sklearn.__version__,
        },
        "task": {
            "class_set": MAIN11,
            "headline6": HEADLINE6,
            "patient_unit": "earliest canonical check per PT within paper window",
            "window": [str(WINDOW_START.date()), str(WINDOW_END.date())],
            "development": [str(WINDOW_START.date()), str(DEV_END.date())],
            "temporal_test": ["2022-01-01", str(WINDOW_END.date())],
            "seed": SEED,
        },
        "linkage": linkage_audit,
        "counts": {
            "canonical_checks_in_window": int(len(window)),
            "actual_first_dated_check": str(window["date"].min().date()),
            "actual_last_dated_check": str(window["date"].max().date()),
            "unique_patients_first_check": int(len(first)),
            "main11_first_check_patients": int(len(first_main)),
            "main11_linked_patients": int(len(linked)),
            "main11_linkage_pct": round(100.0 * len(linked) / len(first_main), 3),
            "development": int((linked["split"] == "development").sum()),
            "temporal_test": int((linked["split"] == "temporal_test").sum()),
        },
        "class_counts": {
            split: {
                label: int(count)
                for label, count in linked.loc[linked["split"] == split, "disease_code"]
                .value_counts()
                .reindex(MAIN11, fill_value=0)
                .items()
            }
            for split in ["development", "temporal_test"]
        },
        "feature_missingness_pct": {
            split: {
                col: round(
                    float(
                        linked.loc[linked["split"] == split, col].isna().mean() * 100
                    ),
                    3,
                )
                for col in FULL
            }
            for split in ["development", "temporal_test"]
        },
        "feature_definitions": {
            "age": "registry age in years",
            "sex_binary": "M=1, F=0; other/missing imputed within fold",
            "glomerulus_count": "reported TEM glomerulus count",
            "sclerosis_rate": "(explicit global + segmental sclerotic counts) / TEM glomerulus count",
            "mesangial_cell_count": "reported range midpoint per region",
            "mesangial_matrix_grade": "conservative ordinal 0/1/1.5/2/2.5/3",
            "gbm_thickness_nm": "reported single value or range midpoint, normalized to nm",
            "spike_presence": "explicit absent=0, explicit formed=1, ambiguous=missing",
            "foot_process_grade": "none=0, focal/partial=1, mostly=2, diffuse=3",
        },
    }
    return linked, audit


def make_imputer() -> SimpleImputer:
    """构建保留全空特征的折内中位数插补器。"""

    return SimpleImputer(strategy="median", keep_empty_features=True)


def model_specs(mode: str) -> dict[str, tuple[Any, dict[str, list[Any]], bool]]:
    """返回模型、内层小网格和是否传入平衡样本权重。"""

    specs: dict[str, tuple[Any, dict[str, list[Any]], bool]] = {
        "logistic_regression": (
            LogisticRegression(
                class_weight="balanced",
                max_iter=3000,
                random_state=SEED,
                solver="lbfgs",
            ),
            {"model__C": [0.1, 1.0, 10.0]},
            False,
        ),
        "random_forest": (
            RandomForestClassifier(
                n_estimators=300,
                class_weight="balanced_subsample",
                random_state=SEED,
                n_jobs=1,
            ),
            {"model__max_depth": [None, 12], "model__min_samples_leaf": [1, 5]},
            False,
        ),
        "gradient_boosting": (
            GradientBoostingClassifier(random_state=SEED),
            {
                "model__n_estimators": [100, 200],
                "model__learning_rate": [0.05, 0.1],
                "model__max_depth": [2],
            },
            True,
        ),
    }
    if mode == "full":
        specs.update(
            {
                "svm_rbf": (
                    SVC(
                        kernel="rbf",
                        class_weight="balanced",
                        probability=True,
                        random_state=SEED,
                    ),
                    {"model__C": [0.5, 2.0], "model__gamma": ["scale"]},
                    False,
                ),
                "mlp": (
                    MLPClassifier(
                        # sklearn 1.8 的 early-stopping 路径对字符串多分类标签
                        # 调用 np.isnan；关闭该路径并由外层 CV 负责选择。
                        early_stopping=False,
                        max_iter=300,
                        random_state=SEED,
                        learning_rate_init=0.001,
                    ),
                    {
                        "model__hidden_layer_sizes": [(64,), (64, 32)],
                        "model__alpha": [0.0001, 0.001],
                    },
                    False,
                ),
                "adaboost": (
                    AdaBoostClassifier(random_state=SEED),
                    {
                        "model__n_estimators": [100, 200],
                        "model__learning_rate": [0.5, 1.0],
                    },
                    True,
                ),
            }
        )
    return specs


def align_probabilities(estimator: Any, probabilities: np.ndarray) -> np.ndarray:
    """把 estimator.classes_ 的概率列对齐到 MAIN11。"""

    aligned = np.zeros((len(probabilities), len(MAIN11)), dtype=float)
    classes = list(estimator.classes_)
    for j, label in enumerate(MAIN11):
        if label in classes:
            aligned[:, j] = probabilities[:, classes.index(label)]
    return aligned


def multiclass_auc(y_true: np.ndarray, probabilities: np.ndarray) -> float:
    """计算 11 类 OVR macro-AUROC；测试缺类时返回 NaN。"""

    if set(MAIN11) - set(y_true):
        return float("nan")
    y_matrix = np.column_stack([(y_true == label).astype(int) for label in MAIN11])
    return float(roc_auc_score(y_matrix, probabilities, average="macro"))


def aggregate_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    probabilities: np.ndarray,
) -> dict[str, Any]:
    """生成聚合指标、逐类指标和混淆矩阵。"""

    precision, recall, f1, support = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=MAIN11,
        zero_division=0,
    )
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "macro_f1": float(
            f1_score(y_true, y_pred, labels=MAIN11, average="macro", zero_division=0)
        ),
        "weighted_f1": float(
            f1_score(y_true, y_pred, average="weighted", zero_division=0)
        ),
        "macro_ovr_auc": multiclass_auc(y_true, probabilities),
        "per_class": {
            label: {
                "precision": float(precision[i]),
                "recall": float(recall[i]),
                "f1": float(f1[i]),
                "support": int(support[i]),
            }
            for i, label in enumerate(MAIN11)
        },
        "confusion_matrix_rows_true_cols_pred": confusion_matrix(
            y_true, y_pred, labels=MAIN11
        )
        .astype(int)
        .tolist(),
    }


def bootstrap_ci(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    probabilities: np.ndarray,
    n_boot: int,
) -> dict[str, list[float]]:
    """按类别分层患者 bootstrap，保证每次重采样保留全部类别。"""

    rng = np.random.default_rng(SEED)
    groups = {label: np.flatnonzero(y_true == label) for label in MAIN11}
    values: dict[str, list[float]] = defaultdict(list)
    for _ in range(n_boot):
        indices = np.concatenate(
            [
                rng.choice(group, size=len(group), replace=True)
                for group in groups.values()
            ]
        )
        rng.shuffle(indices)
        yt = y_true[indices]
        yp = y_pred[indices]
        pr = probabilities[indices]
        values["accuracy"].append(float(accuracy_score(yt, yp)))
        values["balanced_accuracy"].append(float(balanced_accuracy_score(yt, yp)))
        values["macro_f1"].append(
            float(f1_score(yt, yp, labels=MAIN11, average="macro", zero_division=0))
        )
        values["macro_ovr_auc"].append(multiclass_auc(yt, pr))
    return {
        name: [float(np.nanpercentile(data, 2.5)), float(np.nanpercentile(data, 97.5))]
        for name, data in values.items()
    }


def train_one(
    model_name: str,
    estimator: Any,
    grid: dict[str, list[Any]],
    use_sample_weight: bool,
    x_dev: pd.DataFrame,
    y_dev: np.ndarray,
    x_test: pd.DataFrame,
    y_test: np.ndarray,
    n_boot: int,
) -> tuple[GridSearchCV, dict[str, Any]]:
    """内层 CV 选参、重拟合并在时间外测试集上评估。"""

    pipeline = Pipeline(
        [
            ("imputer", make_imputer()),
            ("scaler", StandardScaler()),
            ("model", estimator),
        ]
    )
    cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=SEED)
    search = GridSearchCV(
        pipeline,
        grid,
        scoring="f1_macro",
        cv=cv,
        n_jobs=1,
        refit=True,
        error_score="raise",
        return_train_score=False,
    )
    fit_kwargs: dict[str, Any] = {}
    if use_sample_weight:
        fit_kwargs["model__sample_weight"] = compute_sample_weight("balanced", y_dev)
    started = time.perf_counter()
    search.fit(x_dev, y_dev, **fit_kwargs)
    elapsed = time.perf_counter() - started
    prediction = search.predict(x_test)
    probabilities = align_probabilities(
        search.best_estimator_, search.predict_proba(x_test)
    )
    metrics = aggregate_metrics(y_test, prediction, probabilities)
    metrics["bootstrap_95ci"] = bootstrap_ci(
        y_test, prediction, probabilities, n_boot=n_boot
    )
    result = {
        "best_inner_cv_macro_f1": float(search.best_score_),
        "best_params": search.best_params_,
        "fit_seconds": round(elapsed, 3),
        "temporal_test": metrics,
    }
    progress(
        f"{model_name}: CV={search.best_score_:.4f}, "
        f"test macro-F1={metrics['macro_f1']:.4f}, {elapsed:.1f}s"
    )
    return search, result


def exact_stem_only_sensitivity(
    data: pd.DataFrame,
    n_boot: int,
) -> dict[str, Any]:
    """在无需 fallback 的精确文件 stem 连接子集中复核预设 RF。"""

    exact = data.loc[data["link_method"] == "exact_stem"].copy()
    dev = exact.loc[exact["split"] == "development"]
    test = exact.loc[exact["split"] == "temporal_test"]
    y_dev = dev["disease_code"].to_numpy()
    y_test = test["disease_code"].to_numpy()
    missing_dev = sorted(set(MAIN11) - set(y_dev))
    missing_test = sorted(set(MAIN11) - set(y_test))
    output: dict[str, Any] = {
        "definition": "linked by a unique normalized report filename stem; no fallback key",
        "n_total": int(len(exact)),
        "n_development": int(len(dev)),
        "n_temporal_test": int(len(test)),
        "class_counts": {
            split: {
                label: int(count)
                for label, count in exact.loc[exact["split"] == split, "disease_code"]
                .value_counts()
                .reindex(MAIN11, fill_value=0)
                .items()
            }
            for split in ["development", "temporal_test"]
        },
        "missing_classes_development": missing_dev,
        "missing_classes_temporal_test": missing_test,
    }
    if missing_dev or missing_test:
        output["status"] = "not_fitted_missing_class"
        return output
    estimator, grid, use_weight = model_specs("minimal")["random_forest"]
    _, result = train_one(
        model_name="random_forest_exact_stem_only",
        estimator=clone(estimator),
        grid=grid,
        use_sample_weight=use_weight,
        x_dev=dev[FULL],
        y_dev=y_dev,
        x_test=test[FULL],
        y_test=y_test,
        n_boot=n_boot,
    )
    output["status"] = "fitted"
    output["random_forest_full_features"] = result
    return output


def binary_metrics(y_true: np.ndarray, probability: np.ndarray) -> dict[str, float]:
    """计算二分类聚合指标。"""

    prediction = (probability >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, prediction, labels=[0, 1]).ravel()
    return {
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "average_precision": float(average_precision_score(y_true, probability)),
        "f1_at_0_5": float(f1_score(y_true, prediction, zero_division=0)),
        "sensitivity_at_0_5": float(recall_score(y_true, prediction, zero_division=0)),
        "specificity_at_0_5": float(tn / (tn + fp)) if (tn + fp) else float("nan"),
        "support_positive": int(y_true.sum()),
        "support_negative": int((1 - y_true).sum()),
    }


def direct_binary_analysis(
    x_dev: pd.DataFrame,
    y_dev: np.ndarray,
    x_test: pd.DataFrame,
    y_test: np.ndarray,
    rf_search: GridSearchCV,
) -> dict[str, Any]:
    """训练 6 个直接二分类 RF，并与多分类 RF 的 OVR 输出比较。"""

    multiclass_prob = align_probabilities(
        rf_search.best_estimator_, rf_search.predict_proba(x_test)
    )
    base_params = rf_search.best_params_
    output: dict[str, Any] = {}
    for label in HEADLINE6:
        y_dev_bin = (y_dev == label).astype(int)
        y_test_bin = (y_test == label).astype(int)
        model = RandomForestClassifier(
            n_estimators=300,
            class_weight="balanced_subsample",
            random_state=SEED,
            n_jobs=1,
            max_depth=base_params.get("model__max_depth"),
            min_samples_leaf=base_params.get("model__min_samples_leaf", 1),
        )
        pipeline = Pipeline(
            [
                ("imputer", make_imputer()),
                ("scaler", StandardScaler()),
                ("model", model),
            ]
        )
        pipeline.fit(x_dev, y_dev_bin)
        direct_prob = pipeline.predict_proba(x_test)[
            :, list(pipeline.classes_).index(1)
        ]
        ovr_prob = multiclass_prob[:, MAIN11.index(label)]
        output[label] = {
            "direct_binary_rf": binary_metrics(y_test_bin, direct_prob),
            "multiclass_rf_ovr_output": binary_metrics(y_test_bin, ovr_prob),
        }
    return output


def present_class_auc(y_true: np.ndarray, probabilities: np.ndarray) -> float:
    """来源留一中仅对测试集存在且有正负例的类别计算平均 OVR AUC。"""

    aucs: list[float] = []
    for j, label in enumerate(MAIN11):
        binary = (y_true == label).astype(int)
        if binary.min() == binary.max():
            continue
        aucs.append(float(roc_auc_score(binary, probabilities[:, j])))
    return float(np.mean(aucs)) if aucs else float("nan")


def loho_analysis(
    data: pd.DataFrame,
    rf_search: GridSearchCV,
) -> dict[str, Any]:
    """对四个主要转诊来源做患者级来源留一运输验证。"""

    candidates = data.loc[
        data["hospital"].notna() & (data["hospital"].astype(str).str.len() > 0)
    ]
    top_hospitals = candidates["hospital"].value_counts().head(4).index.tolist()
    best_params = rf_search.best_params_
    output: dict[str, Any] = {}
    for hospital in top_hospitals:
        train = data.loc[data["hospital"] != hospital]
        test = data.loc[data["hospital"] == hospital]
        model = RandomForestClassifier(
            n_estimators=300,
            class_weight="balanced_subsample",
            random_state=SEED,
            n_jobs=1,
            max_depth=best_params.get("model__max_depth"),
            min_samples_leaf=best_params.get("model__min_samples_leaf", 1),
        )
        pipeline = Pipeline(
            [
                ("imputer", make_imputer()),
                ("scaler", StandardScaler()),
                ("model", model),
            ]
        )
        pipeline.fit(train[FULL], train["disease_code"].to_numpy())
        pred = pipeline.predict(test[FULL])
        prob = align_probabilities(pipeline, pipeline.predict_proba(test[FULL]))
        present = sorted(set(test["disease_code"]), key=MAIN11.index)
        output[str(hospital)] = {
            "train_n": int(len(train)),
            "test_n": int(len(test)),
            "test_present_classes": present,
            "test_class_counts": {
                k: int(v)
                for k, v in test["disease_code"]
                .value_counts()
                .reindex(MAIN11, fill_value=0)
                .items()
            },
            "accuracy": float(accuracy_score(test["disease_code"], pred)),
            "balanced_accuracy_present_classes": float(
                balanced_accuracy_score(test["disease_code"], pred)
            ),
            "macro_f1_all11": float(
                f1_score(
                    test["disease_code"],
                    pred,
                    labels=MAIN11,
                    average="macro",
                    zero_division=0,
                )
            ),
            "macro_f1_present_classes": float(
                f1_score(
                    test["disease_code"],
                    pred,
                    labels=present,
                    average="macro",
                    zero_division=0,
                )
            ),
            "mean_ovr_auc_present_classes": present_class_auc(
                test["disease_code"].to_numpy(), prob
            ),
        }
    return {
        "interpretation": (
            "Cross-referral-source transport validation within one regional ultrastructural "
            "service; it is not independent external-laboratory validation."
        ),
        "holdouts": output,
    }


def run(mode: str, n_boot: int) -> dict[str, Any]:
    """执行 minimal 或 full 复核。"""

    started = time.perf_counter()
    data, audit = build_dataset()
    if mode == "audit":
        return clean_json(
            {
                "report_type": "v2_read_only_linkage_audit",
                "mode": mode,
                "audit": audit,
                "runtime_seconds": round(time.perf_counter() - started, 3),
            }
        )
    dev = data.loc[data["split"] == "development"].copy()
    test = data.loc[data["split"] == "temporal_test"].copy()
    y_dev = dev["disease_code"].to_numpy()
    y_test = test["disease_code"].to_numpy()
    missing_dev = set(MAIN11) - set(y_dev)
    missing_test = set(MAIN11) - set(y_test)
    if missing_dev or missing_test:
        raise RuntimeError(
            f"Temporal split is missing classes: dev={sorted(missing_dev)}, test={sorted(missing_test)}"
        )

    feature_sets = {
        "full": FULL,
        "full_minus_age": FULL_MINUS_AGE,
        "age_sex_only": AGE_SEX,
        "morphometry_only": MORPH,
        "missingness_only_diagnostic": MISSINGNESS,
    }
    specs = model_specs(mode)
    results: dict[str, Any] = {}
    fitted_full: dict[str, GridSearchCV] = {}
    for feature_set_name, columns in feature_sets.items():
        progress(f"Feature set: {feature_set_name} ({len(columns)} variables)")
        results[feature_set_name] = {}
        for model_name, (estimator, grid, use_weight) in specs.items():
            try:
                search, result = train_one(
                    model_name=model_name,
                    estimator=clone(estimator),
                    grid=grid,
                    use_sample_weight=use_weight,
                    x_dev=dev[columns],
                    y_dev=y_dev,
                    x_test=test[columns],
                    y_test=y_test,
                    n_boot=n_boot,
                )
                results[feature_set_name][model_name] = result
                if feature_set_name == "full":
                    fitted_full[model_name] = search
            except Exception as exc:  # noqa: BLE001 - 保留其他模型结果后继续
                progress(f"{model_name} failed: {type(exc).__name__}: {exc}")
                results[feature_set_name][model_name] = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:500],
                }

    output: dict[str, Any] = {
        "report_type": "v2_read_only_patient_level_model_reanalysis",
        "mode": mode,
        "generated_date": "2026-07-22",
        "privacy": {
            "row_level_records_exported": False,
            "patient_identifiers_exported": False,
            "remote_files_written": False,
            "output_scope": "aggregate JSON only",
        },
        "audit": audit,
        "analysis_protocol": {
            "split": "patient-level earliest canonical check; 2014-2021 development, 2022-2026-04 test",
            "preprocessing": "median imputation and standardization fitted within each CV fold",
            "missingness_note": (
                "The clinical-feature models did not add missingness indicators. A separate "
                "missingness-only diagnostic baseline used nine binary missing/not-missing flags."
            ),
            "inner_cv": "3-fold stratified shuffled CV, macro-F1 selection",
            "bootstrap": f"{n_boot} class-stratified patient bootstrap replicates",
            "model_selection_note": (
                "The temporal test set was not used for tuning. Random forest was prespecified "
                "for direct-binary and source-holdout analyses."
            ),
        },
        "model_results": results,
        "limitations": [
            "Disease labels are rule-derived from report content and are not an independent pathology gold standard.",
            "Fallback morphometry linkage is not manually audited; exact-stem-only sensitivity analysis remains necessary before publication.",
            "Strong calendar-template drift and differential feature missingness can affect transport performance.",
            "GBM thickness and spike formation are sparsely documented; fold-contained imputation does not recover absent measurements.",
            "Source holdouts share one regional ultrastructural service and are not independent external-center validation.",
        ],
    }

    if mode == "full":
        rf_search = fitted_full["random_forest"]
        progress("Running exact-stem-only random-forest sensitivity analysis...")
        output["exact_stem_only_sensitivity"] = exact_stem_only_sensitivity(
            data, n_boot=n_boot
        )
        progress("Running six direct binary headline classifiers...")
        output["headline6_direct_binary"] = direct_binary_analysis(
            dev[FULL], y_dev, test[FULL], y_test, rf_search
        )
        progress("Running four major-source leave-one-hospital-out analyses...")
        output["major_source_loho"] = loho_analysis(data, rf_search)

    output["runtime_seconds"] = round(time.perf_counter() - started, 3)
    return clean_json(output)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["audit", "minimal", "full"], default="full")
    parser.add_argument("--bootstrap", type=int, default=300)
    return parser.parse_args()


def main() -> None:
    """脚本入口。"""

    args = parse_args()
    warnings.filterwarnings("ignore", category=ConvergenceWarning)
    warnings.filterwarnings("ignore", category=FutureWarning)
    result = run(mode=args.mode, n_boot=args.bootstrap)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
