"""Build privacy-preserving locked-registry source data and figures.

The script reads the locked registry and legacy morphometry table through
read-only SSH. Row-level data remain in remote memory; only aggregate JSON and
CSV source data are written locally. The paper window is 2014-05-01 through
2026-04-30 (actual observed dates 2014-05-08 through 2026-04-09).
Demographic and morphometric summaries use one earliest eligible
examination per patient; workload panels use all canonical examinations.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import shlex
import subprocess
import zlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

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
LONG_TAIL = [
    "AMY",
    "AAGN",
    "TMA",
    "HN",
    "MIDD",
    "FGN",
    "anti-GBM",
    "C3G",
]
FEATURE_LABELS = {
    "age": "Age",
    "sex": "Sex",
    "glom_total": "Glomerulus count",
    "sclerosis_pct": "Sclerosis rate",
    "mes_cells": "Mesangial cell count",
    "mes_matrix": "Mesangial matrix grade",
    "gbm_nm": "GBM thickness",
    "spike": "Spike presence",
    "fp_grade": "Foot-process grade",
}
FEATURE_ORDER = list(FEATURE_LABELS)
SERVICE_CAPACITY_PER_MONTH = 44.0
MIN_MORPH_N = 30


REMOTE_REGISTRY_CODE = r"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

DATA_ROOT_ENV = "PATHOLOGY_V2_ROOT"
if DATA_ROOT_ENV not in os.environ:
    raise RuntimeError(
        f"Set {DATA_ROOT_ENV} to the authorised controlled-data root."
    )
ROOT = Path(os.environ[DATA_ROOT_ENV]).expanduser().resolve()
REGISTRY = ROOT / "registry" / "patient_visit_registry.json"
START = datetime(2014, 5, 1)
END = datetime(2026, 4, 30, 23, 59, 59)
MAIN11 = [
    "IgAN", "IgAVN", "MCD", "MN", "MsPGN", "LN",
    "EPGN", "DKD", "TBMN", "FSGS", "MPGN",
]
LONG_TAIL = [
    "AMY", "AAGN", "TMA", "HN", "MIDD", "FGN", "anti-GBM", "C3G",
]
AGE_BINS = [
    ("0-9", 0, 9),
    ("10-17", 10, 17),
    ("18-39", 18, 39),
    ("40-59", 40, 59),
    ("60+", 60, 200),
]


def parse_date(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 8:
        return None
    try:
        return datetime.strptime(digits[:8], "%Y%m%d")
    except ValueError:
        return None


records = json.loads(REGISTRY.read_text(encoding="utf-8"))
canonical = [row for row in records if row.get("is_canonical")]
window = []
for stable_order, row in enumerate(canonical):
    date = parse_date(row.get("song_ymd"))
    if date is not None and START <= date <= END:
        internal_visit_key = str(row.get("visit_id") or row.get("visit_key") or "")
        window.append((date, internal_visit_key, stable_order, row))
window.sort(key=lambda item: (item[0], item[1], item[2]))

first_by_patient = {}
for date, internal_visit_key, stable_order, row in window:
    first_by_patient.setdefault(
        str(row.get("PT")), (date, internal_visit_key, stable_order, row)
    )
patient_first_main11 = [
    (date, internal_visit_key, stable_order, row)
    for date, internal_visit_key, stable_order, row in first_by_patient.values()
    if row.get("disease_code") in MAIN11
]

raw_class_counts = Counter(
    str(row.get("disease_code") or "(missing)") for _, _, _, row in window
)
class_groups = []
for disease in MAIN11:
    class_groups.append({
        "category": disease,
        "group_type": "main11",
        "n": int(raw_class_counts.get(disease, 0)),
    })
class_groups.append({
    "category": "Other",
    "group_type": "other",
    "n": int(raw_class_counts.get("其他", 0)),
})
class_groups.append({
    "category": "Long-tail (8)",
    "group_type": "long_tail",
    "n": int(sum(raw_class_counts.get(code, 0) for code in LONG_TAIL)),
})

age_distribution = []
sex_distribution = []
for disease in MAIN11:
    rows = [
        row
        for _, _, _, row in patient_first_main11
        if row.get("disease_code") == disease
    ]
    ages = [
        float(row["age"])
        for row in rows
        if isinstance(row.get("age"), (int, float)) and 0 <= float(row["age"]) <= 120
    ]
    for label, low, high in AGE_BINS:
        age_distribution.append({
            "disease": disease,
            "age_band": label,
            "n": int(sum(low <= age <= high for age in ages)),
            "age_nonmissing": len(ages),
            "cohort_n": len(rows),
        })
    age_distribution.append({
        "disease": disease,
        "age_band": "Missing",
        "n": int(len(rows) - len(ages)),
        "age_nonmissing": len(ages),
        "cohort_n": len(rows),
    })
    sexes = Counter(str(row.get("sex") or "") for row in rows)
    male = int(sexes.get("男", 0))
    female = int(sexes.get("女", 0))
    sex_distribution.append({
        "disease": disease,
        "male_n": male,
        "female_n": female,
        "missing_n": int(len(rows) - male - female),
        "nonmissing_n": male + female,
        "cohort_n": len(rows),
    })

annual_counts = Counter(date.year for date, _, _, _ in window)
year_month = Counter((date.year, date.month) for date, _, _, _ in window)
year_disease = defaultdict(Counter)
for date, _, _, row in window:
    year_disease[date.year][str(row.get("disease_code") or "(missing)")] += 1

annual = []
monthly = []
top_categories = []
for year in range(2014, 2027):
    observed_months = (
        list(range(5, 13))
        if year == 2014
        else (list(range(1, 5)) if year == 2026 else list(range(1, 13)))
    )
    annual_n = int(annual_counts.get(year, 0))
    annual.append({
        "year": year,
        "annual_checks": annual_n,
        "observed_months": len(observed_months),
        "partial_year": year in (2014, 2026),
        "boundary_month_note": (
            "May-Dec; first observed date May 8"
            if year == 2014
            else (
                "Jan-Apr; April observed only through day 9"
                if year == 2026
                else "full calendar year"
            )
        ),
        "mean_per_observed_month": annual_n / len(observed_months),
    })
    for month in range(1, 13):
        monthly.append({
            "year": year,
            "month": month,
            "observed": month in observed_months,
            "n": int(year_month.get((year, month), 0)) if month in observed_months else None,
        })
    counter = year_disease[year]
    top_all = counter.most_common(1)[0] if counter else ("", 0)
    main_counter = Counter({code: counter.get(code, 0) for code in MAIN11})
    top_main = main_counter.most_common(1)[0] if main_counter else ("", 0)
    top_categories.append({
        "year": year,
        "top_all_category": top_all[0],
        "top_all_n": int(top_all[1]),
        "top_main11_category": top_main[0],
        "top_main11_n": int(top_main[1]),
    })

quarterly = []
for year in range(2015, 2026):
    for quarter in range(1, 5):
        months = range((quarter - 1) * 3 + 1, quarter * 3 + 1)
        quarterly.append({
            "year": year,
            "quarter": f"Q{quarter}",
            "n": int(sum(year_month.get((year, month), 0) for month in months)),
        })

output = {
    "analysis": "privacy-preserving locked-registry aggregate source data",
    "privacy": {
        "row_level_output": False,
        "patient_identifiers_output": False,
        "raw_text_output": False,
        "remote_writes": False,
    },
    "cohort": {
        "window": "2014-05-01 through 2026-04-30",
        "actual_observed_dates": "2014-05-08 through 2026-04-09",
        "canonical_checks": len(window),
        "unique_patients": len(first_by_patient),
        "patient_first_main11": len(patient_first_main11),
        "first_exam_tie_break": (
            "exam date, deterministic internal visit key, then stable canonical order"
        ),
    },
    "class_groups": class_groups,
    "raw_class_counts": dict(raw_class_counts),
    "age_distribution": age_distribution,
    "sex_distribution": sex_distribution,
    "annual": annual,
    "monthly": monthly,
    "top_categories": top_categories,
    "quarterly_complete_years": quarterly,
}
print(json.dumps(output, ensure_ascii=False, allow_nan=False))
"""


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ssh-alias",
        help="Configured SSH alias for the authorised controlled host.",
    )
    parser.add_argument(
        "--remote-root",
        help="Authorised controlled-data root on the remote host.",
    )
    parser.add_argument("--remote-python", default="python3")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--reuse-aggregate",
        action="store_true",
        help="Reuse local aggregate JSON files if present.",
    )
    return parser.parse_args()


def remote_execute(
    code: str,
    ssh_alias: str,
    timeout: int,
    remote_root: str,
    remote_python: str,
) -> dict[str, Any]:
    """Execute aggregate-only code remotely without writing remote files."""
    payload = base64.b64encode(zlib.compress(code.encode("utf-8"), level=9)).decode(
        "ascii"
    )
    python_code = (
        "import base64,zlib;" f"exec(zlib.decompress(base64.b64decode('{payload}')))"
    )
    command = (
        f"PATHOLOGY_V2_ROOT={shlex.quote(remote_root)} "
        f"{shlex.quote(remote_python)} -c {shlex.quote(python_code)}"
    )
    process = subprocess.run(
        ["ssh", "-n", ssh_alias, command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            "远程只读聚合失败。末尾错误信息：\n" + process.stderr[-4000:]
        )
    text = process.stdout.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("远端未返回有效聚合 JSON。")
    return json.loads(text[start : end + 1])


def load_modeling_aggregate_code(work_root: Path, output_dir: Path) -> str:
    """Combine the final modeling linkage with an aggregate-only remote tail."""
    script_dir = Path(__file__).resolve().parent
    model_candidates = [
        work_root / "remote_v2_modeling.py",
        script_dir / "remote_v2_modeling.py",
    ]
    tail_candidates = [
        output_dir / "remote_model_aggregate_tail.py",
        script_dir / "remote_model_aggregate_tail.py",
    ]
    model_path = next(
        (path for path in model_candidates if path.exists()), model_candidates[0]
    )
    tail_path = next(
        (path for path in tail_candidates if path.exists()), tail_candidates[0]
    )
    if not model_path.exists():
        raise FileNotFoundError(f"未找到最终建模连接脚本：{model_path}")
    if not tail_path.exists():
        raise FileNotFoundError(f"未找到聚合尾脚本：{tail_path}")
    model_source = model_path.read_text(encoding="utf-8")
    aggregate_tail = tail_path.read_text(encoding="utf-8")
    return (
        "_MODEL_SOURCE = "
        + repr(model_source)
        + "\n_NAMESPACE = {'__name__': 'v2_modeling_embedded'}\n"
        + "exec(compile(_MODEL_SOURCE, 'remote_v2_modeling.py', 'exec'), _NAMESPACE)\n"
        + "exec(compile("
        + repr(aggregate_tail)
        + ", 'v2_figure_aggregate.py', 'exec'), _NAMESPACE)\n"
    )


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    """Write deterministic UTF-8 CSV source data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def wilson_interval(successes: int, total: int) -> tuple[float, float]:
    """Return a Wilson 95% interval for a binomial proportion."""
    if total <= 0:
        return (math.nan, math.nan)
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z**2 / total
    centre = (proportion + z**2 / (2 * total)) / denominator
    half = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z**2 / (4 * total**2))
        / denominator
    )
    return centre - half, centre + half


def derive_source_rows(
    registry: dict[str, Any], morph: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Convert aggregate JSON into figure-ready source-data rows."""
    cohort_n = int(registry["cohort"]["canonical_checks"])
    class_rows = []
    for row in registry["class_groups"]:
        item = dict(row)
        item["percent"] = item["n"] / cohort_n * 100
        class_rows.append(item)

    age_rows = []
    for row in registry["age_distribution"]:
        item = dict(row)
        denominator = (
            item["age_nonmissing"]
            if item["age_band"] != "Missing"
            else item["cohort_n"]
        )
        item["percent"] = item["n"] / denominator * 100 if denominator else math.nan
        age_rows.append(item)

    sex_rows = []
    for row in registry["sex_distribution"]:
        item = dict(row)
        total = int(item["nonmissing_n"])
        male = int(item["male_n"])
        low, high = wilson_interval(male, total)
        item["male_percent"] = male / total * 100 if total else math.nan
        item["male_ci_low"] = low * 100
        item["male_ci_high"] = high * 100
        sex_rows.append(item)

    monthly_rows = [dict(row) for row in registry["monthly"]]
    annual_rows = []
    capacity_rows = []
    for row in registry["annual"]:
        item = dict(row)
        item["window_status"] = "partial" if item["partial_year"] else "complete"
        annual_rows.append(item)
        rho = item["mean_per_observed_month"] / SERVICE_CAPACITY_PER_MONTH
        status = (
            "Exceeds assumed capacity"
            if rho >= 1
            else ("Near assumed capacity" if rho >= 0.85 else "Below assumed capacity")
        )
        capacity_rows.append(
            {
                "year": item["year"],
                "window_status": item["window_status"],
                "boundary_month_note": item["boundary_month_note"],
                "annual_checks": item["annual_checks"],
                "observed_months": item["observed_months"],
                "mean_checks_per_observed_month": item["mean_per_observed_month"],
                "assumed_service_capacity_per_month": SERVICE_CAPACITY_PER_MONTH,
                "rho": rho,
                "scenario_status": status,
                "interpretation": "scenario ratio; not observed turnaround time",
            }
        )

    missing_overall = []
    for feature in FEATURE_ORDER:
        values = morph["missingness"]["overall"][feature]
        missing_overall.append(
            {
                "feature": feature,
                "feature_label": FEATURE_LABELS[feature],
                "cohort_n": morph["dataset"]["n"],
                "available_n": values["available"],
                "missing_percent": values["missing_pct"],
                "available_percent": 100 - values["missing_pct"],
            }
        )

    availability_year = []
    for year, year_data in morph["missingness"]["by_year"].items():
        if not 2014 <= int(year) <= 2026:
            continue
        for feature in FEATURE_ORDER:
            missing = float(year_data["missing_pct"][feature])
            availability_year.append(
                {
                    "year": int(year),
                    "year_window_status": (
                        "partial" if int(year) in (2014, 2026) else "complete"
                    ),
                    "feature": feature,
                    "feature_label": FEATURE_LABELS[feature],
                    "cohort_n": int(year_data["n"]),
                    "available_percent": 100 - missing,
                    "missing_percent": missing,
                }
            )

    split_missing = []
    for feature in FEATURE_ORDER:
        for split, years in (
            ("development", range(2014, 2022)),
            ("temporal_test", range(2022, 2027)),
        ):
            total = 0
            missing_count = 0
            for year in years:
                data = morph["missingness"]["by_year"].get(str(year))
                if data is None:
                    continue
                n = int(data["n"])
                total += n
                missing_count += round(n * float(data["missing_pct"][feature]) / 100)
            split_missing.append(
                {
                    "split": split,
                    "years": "2014-2021" if split == "development" else "2022-2026-04",
                    "feature": feature,
                    "feature_label": FEATURE_LABELS[feature],
                    "cohort_n": total,
                    "missing_n": missing_count,
                    "missing_percent": missing_count / total * 100,
                    "available_percent": (total - missing_count) / total * 100,
                }
            )

    morph_rows = []
    stats = morph["figure2_available_case"]
    table1 = morph["table1"]
    feature_specs = [
        ("glomerulus_count", "Glomerulus count", "median", "count"),
        ("sclerosis_pct", "Sclerosis rate", "median", "%"),
        ("mesangial_cells", "Mesangial cell count", "median", "cells/region"),
        ("mesangial_matrix", "Mesangial matrix grade", "median", "grade 0-3"),
        ("gbm_nm", "GBM thickness", "median", "nm"),
    ]
    for disease in MAIN11:
        for key, label, statistic, unit in feature_specs:
            summary = (
                table1[disease][key]
                if key == "glomerulus_count"
                else stats[disease][key]
            )
            morph_rows.append(
                {
                    "disease": disease,
                    "feature": key,
                    "feature_label": label,
                    "n": int(summary["n"]),
                    "statistic": statistic,
                    "value": summary[statistic],
                    "q1": summary.get("q1"),
                    "q3": summary.get("q3"),
                    "unit": unit,
                    "sufficient_n": int(summary["n"]) >= MIN_MORPH_N,
                    "minimum_n_rule": MIN_MORPH_N,
                    "description_only": True,
                    "manual_parser_audit": False,
                    "manual_linkage_audit": False,
                }
            )
        foot = stats[disease]["foot_process"]
        foot_n = int(foot["n"])
        foot_mean = (
            sum(int(grade) * int(count) for grade, count in foot["counts"].items())
            / foot_n
            if foot_n
            else None
        )
        morph_rows.append(
            {
                "disease": disease,
                "feature": "foot_process_mean",
                "feature_label": "Foot-process grade",
                "n": foot_n,
                "statistic": "mean",
                "value": foot_mean,
                "q1": None,
                "q3": None,
                "unit": "grade 0-3",
                "sufficient_n": foot_n >= MIN_MORPH_N,
                "minimum_n_rule": MIN_MORPH_N,
                "description_only": True,
                "manual_parser_audit": False,
                "manual_linkage_audit": False,
            }
        )

    return {
        "figure1_class_counts": class_rows,
        "figure1_annual_volume": annual_rows,
        "figure1_age_distribution": age_rows,
        "figure1_sex_proportion": sex_rows,
        "figure1_year_month": monthly_rows,
        "figure2_missingness_overall": missing_overall,
        "figure2_availability_by_year": availability_year,
        "figure2_dev_test_missingness": split_missing,
        "figure2_available_case_morphometry": morph_rows,
        "figure4_annual_capacity": capacity_rows,
        "figure4_yearly_top_category": [
            dict(row) for row in registry["top_categories"]
        ],
        "figure4_quarterly_volume": [
            dict(row) for row in registry["quarterly_complete_years"]
        ],
    }


def save_source_data(source_dir: Path, rows: dict[str, list[dict[str, Any]]]) -> None:
    """Write all aggregate source-data tables."""
    fields = {
        "figure1_class_counts": ["category", "group_type", "n", "percent"],
        "figure1_annual_volume": [
            "year",
            "annual_checks",
            "observed_months",
            "partial_year",
            "window_status",
            "boundary_month_note",
            "mean_per_observed_month",
        ],
        "figure1_age_distribution": [
            "disease",
            "age_band",
            "n",
            "age_nonmissing",
            "cohort_n",
            "percent",
        ],
        "figure1_sex_proportion": [
            "disease",
            "male_n",
            "female_n",
            "missing_n",
            "nonmissing_n",
            "cohort_n",
            "male_percent",
            "male_ci_low",
            "male_ci_high",
        ],
        "figure1_year_month": ["year", "month", "observed", "n"],
        "figure2_missingness_overall": [
            "feature",
            "feature_label",
            "cohort_n",
            "available_n",
            "missing_percent",
            "available_percent",
        ],
        "figure2_availability_by_year": [
            "year",
            "year_window_status",
            "feature",
            "feature_label",
            "cohort_n",
            "available_percent",
            "missing_percent",
        ],
        "figure2_dev_test_missingness": [
            "split",
            "years",
            "feature",
            "feature_label",
            "cohort_n",
            "missing_n",
            "missing_percent",
            "available_percent",
        ],
        "figure2_available_case_morphometry": [
            "disease",
            "feature",
            "feature_label",
            "n",
            "statistic",
            "value",
            "q1",
            "q3",
            "unit",
            "sufficient_n",
            "minimum_n_rule",
            "description_only",
            "manual_parser_audit",
            "manual_linkage_audit",
        ],
        "figure4_annual_capacity": [
            "year",
            "window_status",
            "boundary_month_note",
            "annual_checks",
            "observed_months",
            "mean_checks_per_observed_month",
            "assumed_service_capacity_per_month",
            "rho",
            "scenario_status",
            "interpretation",
        ],
        "figure4_yearly_top_category": [
            "year",
            "top_all_category",
            "top_all_n",
            "top_main11_category",
            "top_main11_n",
        ],
        "figure4_quarterly_volume": ["year", "quarter", "n"],
    }
    for name, data in rows.items():
        write_csv(source_dir / f"{name}.csv", data, fields[name])
    write_csv(
        source_dir / "table3_scenario_capacity_source.csv",
        rows["figure4_annual_capacity"],
        fields["figure4_annual_capacity"],
    )


def configure_matplotlib() -> Any:
    """Configure a legible publication-style Matplotlib theme."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "Arial",
            "font.size": 12,
            "axes.titlesize": 13.5,
            "axes.labelsize": 12,
            "xtick.labelsize": 10.5,
            "ytick.labelsize": 10.5,
            "legend.fontsize": 10.5,
            "legend.title_fontsize": 10.5,
            "axes.linewidth": 0.9,
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
        }
    )
    return plt


def add_panel_label(axis: Any, letter: str) -> None:
    """Add a uniform black panel letter."""
    axis.text(
        -0.20,
        1.10,
        letter,
        transform=axis.transAxes,
        color="#000000",
        fontsize=18,
        fontweight="bold",
        ha="left",
        va="top",
        clip_on=False,
    )


def render_figure1(rows: dict[str, list[dict[str, Any]]], path: Path) -> None:
    """Render the five-panel v2 cohort and workload overview."""
    plt = configure_matplotlib()
    import numpy as np

    figure = plt.figure(figsize=(12, 11), constrained_layout=True)
    grid = figure.add_gridspec(3, 2, height_ratios=[1.05, 1.0, 1.05])
    ax_a = figure.add_subplot(grid[0, 0])
    ax_b = figure.add_subplot(grid[0, 1])
    ax_c = figure.add_subplot(grid[1, 0])
    ax_d = figure.add_subplot(grid[1, 1])
    ax_e = figure.add_subplot(grid[2, :])

    class_rows = rows["figure1_class_counts"]
    labels = [row["category"] for row in class_rows]
    counts = [row["n"] for row in class_rows]
    colors = [
        (
            "#356F9A"
            if row["group_type"] == "main11"
            else ("#8C8C8C" if row["group_type"] == "other" else "#D5A021")
        )
        for row in class_rows
    ]
    y = np.arange(len(labels))
    ax_a.barh(y, counts, color=colors, edgecolor="white", linewidth=0.5)
    ax_a.set_yticks(y, labels)
    ax_a.invert_yaxis()
    ax_a.set_xlabel("Canonical examinations, n")
    ax_a.set_title("Locked-registry class composition")
    ax_a.spines[["top", "right"]].set_visible(False)
    for index, row in enumerate(class_rows):
        ax_a.text(
            row["n"] + max(counts) * 0.012,
            index,
            f"{row['n']:,} ({row['percent']:.1f}%)",
            va="center",
            fontsize=10,
        )
    ax_a.set_xlim(0, max(counts) * 1.34)
    add_panel_label(ax_a, "A")

    annual = rows["figure1_annual_volume"]
    years = [row["year"] for row in annual]
    volumes = [row["annual_checks"] for row in annual]
    bars = ax_b.bar(years, volumes, color="#3F7CAC", edgecolor="#264E70", linewidth=0.5)
    for bar, row in zip(bars, annual):
        if row["partial_year"]:
            bar.set_hatch("///")
            bar.set_facecolor("#9BBBD4")
        ax_b.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(volumes) * 0.018,
            f"{row['annual_checks']:,}",
            ha="center",
            va="bottom",
            rotation=90,
            fontsize=10,
        )
    ax_b.set_xticks(years, [str(year)[-2:] for year in years])
    ax_b.set_xlabel("Calendar year (20xx)")
    ax_b.set_ylabel("Canonical examinations")
    ax_b.set_title("Annual workload (hatched = boundary-year window)")
    ax_b.spines[["top", "right"]].set_visible(False)
    ax_b.margins(y=0.13)
    add_panel_label(ax_b, "B")

    age_rows = rows["figure1_age_distribution"]
    age_bands = ["0-9", "10-17", "18-39", "40-59", "60+"]
    age_colors = ["#D8EAF2", "#A9D3E6", "#69AFCF", "#347FA8", "#174B6A"]
    bottom = np.zeros(len(MAIN11))
    for band, color in zip(age_bands, age_colors):
        values = [
            next(
                row["percent"]
                for row in age_rows
                if row["disease"] == disease and row["age_band"] == band
            )
            for disease in MAIN11
        ]
        ax_c.barh(MAIN11, values, left=bottom, color=color, label=band, height=0.72)
        bottom += np.asarray(values)
    ax_c.invert_yaxis()
    ax_c.set_ylim(len(MAIN11) - 0.4, -2.35)
    ax_c.set_xlim(0, 100)
    ax_c.set_xlabel("Age distribution among nonmissing values (%)")
    ax_c.set_title("Patient-first age distribution, main 11")
    ax_c.legend(
        title="Age (years)",
        ncol=5,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.015),
        borderaxespad=0,
    )
    ax_c.spines[["top", "right"]].set_visible(False)
    add_panel_label(ax_c, "C")

    sex_rows = rows["figure1_sex_proportion"]
    male_pct = [row["male_percent"] for row in sex_rows]
    lower = [row["male_percent"] - row["male_ci_low"] for row in sex_rows]
    upper = [row["male_ci_high"] - row["male_percent"] for row in sex_rows]
    yy = np.arange(len(MAIN11))
    ax_d.errorbar(
        male_pct,
        yy,
        xerr=[lower, upper],
        fmt="o",
        color="#214E6B",
        ecolor="#6D8796",
        capsize=2,
        markersize=4.5,
    )
    ax_d.axvline(50, color="#B8B8B8", linewidth=0.8, linestyle="--")
    ax_d.set_yticks(yy, MAIN11)
    ax_d.invert_yaxis()
    ax_d.set_xlim(0, 100)
    ax_d.set_xlabel("Male proportion among nonmissing sex (%)")
    ax_d.set_title("Patient-first sex distribution (Wilson 95% CI)")
    ax_d.spines[["top", "right"]].set_visible(False)
    for index, row in enumerate(sex_rows):
        ax_d.text(
            min(row["male_ci_high"] + 2, 96),
            index,
            f"n={row['nonmissing_n']:,}",
            va="center",
            fontsize=10,
        )
    add_panel_label(ax_d, "D")

    monthly = rows["figure1_year_month"]
    matrix = np.full((13, 12), np.nan)
    for row in monthly:
        matrix[row["year"] - 2014, row["month"] - 1] = (
            float(row["n"]) if row["observed"] else np.nan
        )
    masked = np.ma.masked_invalid(matrix)
    cmap = plt.get_cmap("YlGnBu").copy()
    cmap.set_bad("#ECECEC")
    image = ax_e.imshow(masked, aspect="auto", cmap=cmap, interpolation="nearest")
    ax_e.set_xticks(
        np.arange(12),
        [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ],
    )
    ax_e.set_yticks(np.arange(13), [str(year) for year in range(2014, 2027)])
    ax_e.set_xlabel("Month")
    ax_e.set_ylabel("Year")
    ax_e.set_title(
        "Canonical examinations by year and month "
        "(grey = outside window; 2026 Apr through day 9)"
    )
    threshold = float(np.nanmedian(matrix))
    for row_index in range(13):
        for column_index in range(12):
            value = matrix[row_index, column_index]
            text = "NA" if np.isnan(value) else str(int(value))
            if row_index == 12 and column_index == 3 and not np.isnan(value):
                text += "*"
            color = "#505050" if np.isnan(value) or value <= threshold else "white"
            ax_e.text(
                column_index,
                row_index,
                text,
                ha="center",
                va="center",
                fontsize=10,
                color=color,
            )
    figure.colorbar(image, ax=ax_e, shrink=0.82, label="Examinations, n")
    add_panel_label(ax_e, "E")

    figure.suptitle(
        "Locked-registry cohort and workload overview (2014-05 to 2026-04)",
        fontsize=17,
        fontweight="bold",
    )
    figure.savefig(path, dpi=600, bbox_inches="tight")
    plt.close(figure)


def render_figure2(rows: dict[str, list[dict[str, Any]]], path: Path) -> None:
    """Render the four-panel v2 data-quality figure."""
    plt = configure_matplotlib()
    import numpy as np

    figure, axes = plt.subplots(2, 2, figsize=(12, 9.4), constrained_layout=True)
    ax_a, ax_b, ax_c, ax_d = axes.flat

    overall = rows["figure2_missingness_overall"]
    labels = [row["feature_label"] for row in overall]
    missing = [row["missing_percent"] for row in overall]
    y = np.arange(len(labels))
    bars = ax_a.barh(y, missing, color="#B95C4B")
    ax_a.set_yticks(y, labels)
    ax_a.invert_yaxis()
    ax_a.set_xlim(0, 100)
    ax_a.set_xlabel("Missing values (%)")
    ax_a.set_title("Overall missingness of the nine inputs")
    ax_a.spines[["top", "right"]].set_visible(False)
    for bar, row in zip(bars, overall):
        ax_a.text(
            min(bar.get_width() + 1.2, 94),
            bar.get_y() + bar.get_height() / 2,
            f"{row['missing_percent']:.1f}%",
            va="center",
            fontsize=10,
        )
    add_panel_label(ax_a, "A")

    yearly = rows["figure2_availability_by_year"]
    years = list(range(2014, 2027))
    availability = np.full((len(FEATURE_ORDER), len(years)), np.nan)
    for row in yearly:
        availability[FEATURE_ORDER.index(row["feature"]), years.index(row["year"])] = (
            row["available_percent"]
        )
    image = ax_b.imshow(
        availability,
        aspect="auto",
        cmap="viridis",
        vmin=0,
        vmax=100,
        interpolation="nearest",
    )
    ax_b.set_xticks(np.arange(len(years)), [str(year)[-2:] for year in years])
    ax_b.set_yticks(np.arange(len(FEATURE_ORDER)), labels)
    ax_b.set_xlabel("Calendar year (20xx; 2014/2026 boundary years)")
    ax_b.set_title("Availability by year (%)")
    for row_index in range(availability.shape[0]):
        for column_index in range(availability.shape[1]):
            value = availability[row_index, column_index]
            ax_b.text(
                column_index,
                row_index,
                f"{value:.0f}",
                ha="center",
                va="center",
                fontsize=10,
                color="white" if value < 48 else "black",
            )
    figure.colorbar(image, ax=ax_b, shrink=0.78, label="Available (%)")
    add_panel_label(ax_b, "B")

    split = rows["figure2_dev_test_missingness"]
    development = {
        row["feature"]: row for row in split if row["split"] == "development"
    }
    temporal = {row["feature"]: row for row in split if row["split"] == "temporal_test"}
    for index, feature in enumerate(FEATURE_ORDER):
        left = development[feature]["missing_percent"]
        right = temporal[feature]["missing_percent"]
        ax_c.plot([left, right], [index, index], color="#B8B8B8", linewidth=1.2)
        ax_c.scatter(
            left,
            index,
            color="#355C7D",
            s=24,
            label="2014-2021" if index == 0 else None,
        )
        ax_c.scatter(
            right,
            index,
            color="#C06C84",
            s=24,
            label="2022-2026-04" if index == 0 else None,
        )
        ax_c.text(
            max(left, right) + 1.3,
            index,
            f"Δ {right - left:+.1f} pp",
            va="center",
            fontsize=10,
        )
    ax_c.set_yticks(np.arange(len(FEATURE_ORDER)), labels)
    ax_c.invert_yaxis()
    ax_c.set_xlim(0, 110)
    ax_c.set_xlabel("Missing values (%)")
    ax_c.set_title("Temporal drift in missingness")
    ax_c.legend(frameon=False, loc="lower right")
    ax_c.spines[["top", "right"]].set_visible(False)
    add_panel_label(ax_c, "C")

    morph = rows["figure2_available_case_morphometry"]
    display_features = [
        "mesangial_cells",
        "mesangial_matrix",
        "gbm_nm",
        "foot_process_mean",
    ]
    display_labels = [
        "Mesangial cells\n(median)",
        "Matrix grade\n(median)",
        "GBM, nm\n(median)",
        "Foot-process grade\n(mean)",
    ]
    raw = np.full((len(display_features), len(MAIN11)), np.nan)
    sample_n = np.zeros_like(raw)
    for row in morph:
        if row["feature"] not in display_features or not row["sufficient_n"]:
            continue
        i = display_features.index(row["feature"])
        j = MAIN11.index(row["disease"])
        raw[i, j] = float(row["value"])
        sample_n[i, j] = int(row["n"])
    scaled = np.full_like(raw, np.nan)
    for index in range(raw.shape[0]):
        valid = raw[index][~np.isnan(raw[index])]
        if len(valid) and float(valid.max()) > float(valid.min()):
            scaled[index] = (raw[index] - valid.min()) / (valid.max() - valid.min())
        elif len(valid):
            scaled[index][~np.isnan(raw[index])] = 0.5
    cmap = plt.get_cmap("PuBuGn").copy()
    cmap.set_bad("#E6E6E6")
    image_d = ax_d.imshow(
        np.ma.masked_invalid(scaled),
        aspect="auto",
        cmap=cmap,
        vmin=0,
        vmax=1,
        interpolation="nearest",
    )
    ax_d.set_xticks(np.arange(len(MAIN11)), MAIN11, rotation=45, ha="right")
    ax_d.set_yticks(np.arange(len(display_features)), display_labels)
    ax_d.set_title(f"Available-case morphology (only n≥{MIN_MORPH_N})")
    for i in range(raw.shape[0]):
        for j in range(raw.shape[1]):
            if np.isnan(raw[i, j]):
                text = "—"
                color = "#666666"
            else:
                value = raw[i, j]
                text = (
                    f"{value:.0f}"
                    if display_features[i] == "gbm_nm"
                    else f"{value:.1f}"
                )
                color = "white" if scaled[i, j] > 0.62 else "black"
            ax_d.text(j, i, text, ha="center", va="center", fontsize=10, color=color)
    figure.colorbar(image_d, ax=ax_d, shrink=0.78, label="Within-row relative scale")
    ax_d.text(
        0,
        -0.24,
        "Cells show raw values; colour is scaled within each feature.",
        transform=ax_d.transAxes,
        fontsize=10,
        va="top",
    )
    add_panel_label(ax_d, "D")

    figure.suptitle(
        f"Data-quality audit for the locked linked main-11 cohort "
        f"(n={overall[0]['cohort_n']:,}; through 2026-04)",
        fontsize=17,
        fontweight="bold",
    )
    figure.savefig(path, dpi=600, bbox_inches="tight")
    plt.close(figure)


def render_figure4(rows: dict[str, list[dict[str, Any]]], path: Path) -> None:
    """Render the four-panel workload and capacity scenario figure."""
    plt = configure_matplotlib()

    figure, axes = plt.subplots(2, 2, figsize=(12, 8.6), constrained_layout=True)
    ax_a, ax_b, ax_c, ax_d = axes.flat

    capacity = rows["figure4_annual_capacity"]
    years = [row["year"] for row in capacity]
    annual = [row["annual_checks"] for row in capacity]
    monthly_mean = [row["mean_checks_per_observed_month"] for row in capacity]
    bars = ax_a.bar(years, annual, color="#417B9B", edgecolor="#214E6B", linewidth=0.5)
    for bar, row in zip(bars, capacity):
        if row["window_status"] == "partial":
            bar.set_hatch("///")
            bar.set_facecolor("#A6C4D5")
    ax_a.set_ylabel("Annual examinations")
    ax_a.set_xlabel("Year")
    ax_a.set_xticks(years, [str(year)[-2:] for year in years])
    ax_a.set_title("Annual and observed-month workload")
    ax_a.spines["top"].set_visible(False)
    twin = ax_a.twinx()
    twin.plot(
        years, monthly_mean, color="#D67B2C", marker="o", linewidth=1.6, markersize=3.6
    )
    twin.set_ylabel("Mean per observed month", color="#A95A18")
    twin.tick_params(axis="y", colors="#A95A18")
    twin.spines["top"].set_visible(False)
    add_panel_label(ax_a, "A")

    top = rows["figure4_yearly_top_category"]
    categories = [row["top_all_category"] for row in top]
    values = [row["top_all_n"] for row in top]
    unique = list(dict.fromkeys(categories))
    palette = ["#355C7D", "#6C5B7B", "#C06C84", "#F67280", "#99B898"]
    color_map = {
        category: palette[index % len(palette)] for index, category in enumerate(unique)
    }
    bars_b = ax_b.bar(
        years, values, color=[color_map[category] for category in categories]
    )
    ax_b.set_xticks(years, [str(year)[-2:] for year in years])
    ax_b.set_xlabel("Year")
    ax_b.set_ylabel("Examinations in top class")
    ax_b.set_title("Most frequent locked-registry category by year")
    ax_b.spines[["top", "right"]].set_visible(False)
    for bar, category in zip(bars_b, categories):
        label = "Other" if category == "其他" else category
        ax_b.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(values) * 0.018,
            label,
            ha="center",
            va="bottom",
            rotation=90,
            fontsize=10,
        )
    ax_b.margins(y=0.17)
    add_panel_label(ax_b, "B")

    quarterly = rows["figure4_quarterly_volume"]
    complete_years = list(range(2015, 2026))
    quarter_colors = {
        "Q1": "#1B6CA8",
        "Q2": "#46A094",
        "Q3": "#E2A13A",
        "Q4": "#B85C5C",
    }
    for quarter in ("Q1", "Q2", "Q3", "Q4"):
        values_q = [
            next(
                row["n"]
                for row in quarterly
                if row["year"] == year and row["quarter"] == quarter
            )
            for year in complete_years
        ]
        ax_c.plot(
            complete_years,
            values_q,
            marker="o",
            markersize=3.6,
            linewidth=1.5,
            label=quarter,
            color=quarter_colors[quarter],
        )
    ax_c.set_xticks(complete_years, [str(year)[-2:] for year in complete_years])
    ax_c.set_xlabel("Complete calendar year (20xx)")
    ax_c.set_ylabel("Examinations per quarter")
    ax_c.set_title("Quarterly workload in complete years")
    ax_c.legend(frameon=False, ncol=4)
    ax_c.spines[["top", "right"]].set_visible(False)
    add_panel_label(ax_c, "C")

    rho = [row["rho"] for row in capacity]
    status_colors = [
        "#B04A4A" if value >= 1 else ("#D59A32" if value >= 0.85 else "#4C956C")
        for value in rho
    ]
    bars_d = ax_d.bar(years, rho, color=status_colors, edgecolor="white", linewidth=0.5)
    for bar, row in zip(bars_d, capacity):
        if row["window_status"] == "partial":
            bar.set_hatch("///")
        ax_d.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.035,
            f"{row['rho']:.2f}",
            ha="center",
            va="bottom",
            fontsize=10,
        )
    near_line = ax_d.axhline(
        0.85,
        color="#D59A32",
        linewidth=1.0,
        linestyle="--",
        label="Near-capacity threshold (ρ=0.85)",
    )
    capacity_line = ax_d.axhline(
        1,
        color="#333333",
        linewidth=1.0,
        linestyle="-.",
        label="Assumed-capacity boundary (ρ=1.00)",
    )
    ax_d.set_xticks(years, [str(year)[-2:] for year in years])
    ax_d.set_xlabel("Year")
    ax_d.set_ylabel("Scenario utilisation, ρ")
    ax_d.set_title("Capacity scenario (44 examinations/month assumed)")
    ax_d.legend(
        handles=[near_line, capacity_line],
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.17),
        ncol=2,
        borderaxespad=0,
        fontsize=9,
    )
    ax_d.spines[["top", "right"]].set_visible(False)
    ax_d.margins(y=0.12)
    ax_d.text(
        0,
        -0.38,
        "ρ = mean examinations per observed month / 44; "
        "April 2026 includes observations through day 9.",
        transform=ax_d.transAxes,
        fontsize=10,
        va="top",
    )
    add_panel_label(ax_d, "D")

    figure.suptitle(
        "Temporal workload and scenario capacity (2014-05 to 2026-04)",
        fontsize=17,
        fontweight="bold",
    )
    figure.savefig(path, dpi=600, bbox_inches="tight")
    plt.close(figure)


def validate(
    rows: dict[str, list[dict[str, Any]]],
    output_dir: Path,
    registry: dict[str, Any],
    morph: dict[str, Any],
) -> dict[str, Any]:
    """Run deterministic cross-source and privacy validation checks."""
    checks: list[dict[str, Any]] = []

    def record(
        name: str, passed: bool, detail: str, category: str = "arithmetic"
    ) -> None:
        checks.append(
            {
                "category": category,
                "name": name,
                "passed": bool(passed),
                "detail": detail,
            }
        )

    class_total = sum(row["n"] for row in rows["figure1_class_counts"])
    annual_total = sum(row["annual_checks"] for row in rows["figure1_annual_volume"])
    record(
        "class_total_equals_annual_total",
        class_total == annual_total,
        f"{class_total} vs {annual_total}",
    )
    record("paper_window_total", annual_total == 10933, f"total={annual_total}")
    cohort = registry["cohort"]
    record(
        "confirmed_registry_cohort_counts",
        int(cohort["canonical_checks"]) == 10933
        and int(cohort["unique_patients"]) == 10787
        and int(cohort["patient_first_main11"]) == 8208,
        (
            f"checks={cohort['canonical_checks']}; patients={cohort['unique_patients']}; "
            f"main11={cohort['patient_first_main11']}"
        ),
        "cross_source",
    )
    registry_main11 = int(registry["cohort"]["patient_first_main11"])
    linked_main11 = int(morph["dataset"]["n"])
    linked_eligible = int(morph["linkage"]["eligible"])
    split_counts = morph["dataset"]["split_counts"]
    record(
        "registry_modeling_linkage_cohort_match",
        registry_main11 == linked_eligible
        and linked_main11 == 8113
        and int(split_counts["development"]) == 5139
        and int(split_counts["temporal_test"]) == 2974,
        (
            f"eligible={registry_main11}; linked={linked_main11}; "
            f"development={split_counts['development']}; "
            f"temporal_test={split_counts['temporal_test']}"
        ),
        "cross_source",
    )

    monthly = rows["figure1_year_month"]
    annual_by_year = {
        row["year"]: row["annual_checks"] for row in rows["figure1_annual_volume"]
    }
    monthly_ok = all(
        sum(int(row["n"] or 0) for row in monthly if row["year"] == year) == annual_n
        for year, annual_n in annual_by_year.items()
    )
    record("monthly_sums_equal_annual", monthly_ok, "2014-2026")

    quarterly = rows["figure4_quarterly_volume"]
    quarterly_ok = all(
        sum(row["n"] for row in quarterly if row["year"] == year)
        == annual_by_year[year]
        for year in range(2015, 2026)
    )
    record("quarterly_sums_equal_annual", quarterly_ok, "complete years 2015-2025")

    table3 = rows["figure4_annual_capacity"]
    source_ok = all(
        row["annual_checks"] == annual_by_year[row["year"]]
        and abs(
            row["rho"]
            - row["mean_checks_per_observed_month"] / SERVICE_CAPACITY_PER_MONTH
        )
        < 1e-12
        for row in table3
    )
    record(
        "figure4d_table3_single_source",
        source_ok,
        "same annual-capacity rows",
        "cross_source",
    )
    figure4_source = output_dir / "source_data" / "figure4_annual_capacity.csv"
    table3_source = output_dir / "source_data" / "table3_scenario_capacity_source.csv"
    exact_file_match = (
        figure4_source.exists()
        and table3_source.exists()
        and figure4_source.read_bytes() == table3_source.read_bytes()
    )
    record(
        "figure4d_table3_source_files_identical",
        exact_file_match,
        "byte-identical aggregate CSV",
        "deterministic",
    )

    partial = {row["year"]: row["window_status"] for row in table3}
    partial_ok = partial.get(2014) == "partial" and partial.get(2026) == "partial"
    partial_ok = partial_ok and all(
        partial[year] == "complete" for year in range(2015, 2026)
    )
    record("partial_year_flags", partial_ok, "2014 and 2026 only")

    complete = [row for row in table3 if row["window_status"] == "complete"]
    near_count = sum(float(row["rho"]) >= 0.85 for row in complete)
    over_count = sum(float(row["rho"]) >= 1.0 for row in complete)
    record(
        "complete_year_capacity_threshold_counts",
        len(complete) == 11,
        f"complete_years=11; rho>=0.85: {near_count}; rho>=1.00: {over_count}",
    )

    registry_repeat = registry.get("determinism_repeat", {})
    morph_repeat = morph.get("determinism_repeat", {})
    deterministic_ok = bool(registry_repeat.get("exact_aggregate_match")) and bool(
        morph_repeat.get("exact_aggregate_match")
    )
    record(
        "independent_remote_aggregate_repeat",
        deterministic_ok,
        (
            f"registry={registry_repeat.get('exact_aggregate_match')}; "
            f"model_linkage={morph_repeat.get('exact_aggregate_match')}; "
            f"fingerprint={morph['dataset'].get('cohort_fingerprint_sha256', '')[:16]}"
        ),
        "deterministic",
    )

    prohibited = {
        "pt",
        "patient_id",
        "visit_id",
        "report_stem",
        "report_path",
        "path_no",
        "admission_no",
    }
    source_dir = output_dir / "source_data"
    bad_headers = []
    for csv_path in source_dir.glob("*.csv"):
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
        if prohibited.intersection(name.casefold() for name in header):
            bad_headers.append(csv_path.name)
    record(
        "no_identifier_columns",
        not bad_headers,
        ", ".join(bad_headers) or "none",
        "privacy",
    )

    def prohibited_json_keys(value: Any, prefix: str = "") -> list[str]:
        hits: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                key_path = f"{prefix}.{key}" if prefix else str(key)
                if str(key).casefold() in prohibited:
                    hits.append(key_path)
                hits.extend(prohibited_json_keys(child, key_path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                hits.extend(prohibited_json_keys(child, f"{prefix}[{index}]"))
        return hits

    bad_json_keys = prohibited_json_keys(registry) + prohibited_json_keys(morph)
    record(
        "aggregate_json_identifier_key_scan",
        not bad_json_keys,
        ", ".join(bad_json_keys) or "none",
        "privacy",
    )

    image_details = []
    image_ok = True
    from PIL import Image

    for name in ("Figure1_v2.png", "Figure2_v2.png", "Figure4_v2.png"):
        image_path = output_dir / name
        if not image_path.exists():
            image_ok = False
            image_details.append(f"{name}: missing")
            continue
        with Image.open(image_path) as image:
            width, height = image.size
        if width < 3000 or height < 2000:
            image_ok = False
        image_details.append(f"{name}: {width}x{height}")
    record("high_resolution_png", image_ok, "; ".join(image_details), "visual")

    passed = all(item["passed"] for item in checks)
    return {
        "passed": passed,
        "validation_categories": sorted({item["category"] for item in checks}),
        "checks": checks,
    }


def sha256(path: Path) -> str:
    """Return the SHA-256 hex digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(
    output_dir: Path,
    registry: dict[str, Any],
    morph: dict[str, Any],
    validation: dict[str, Any],
) -> None:
    """Write machine- and human-readable provenance manifests."""
    files = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("manifest"):
            continue
        if {".ruff_cache", "__pycache__"}.intersection(path.parts):
            continue
        files.append(
            {
                "path": path.relative_to(output_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    manifest = {
        "title": "Locked-registry descriptive figure source-data manifest",
        "cohort": registry["cohort"],
        "definitions": {
            "class_count_and_workload": "All canonical examinations in the paper window.",
            "demographics": "Earliest eligible canonical examination per patient, then main-11 restriction.",
            "morphometry": "Patient-first main-11, linked legacy table, available-case only.",
            "development_window": "2014-05 through 2021-12",
            "temporal_test_window": "2022-01 through 2026-04",
            "complete_years": "2015-2025",
            "partial_years": (
                "2014 (May-Dec) and 2026 (Jan-Apr; April only through day 9)"
            ),
            "capacity_scenario": "44 examinations/month; rho uses observed-month mean.",
        },
        "privacy": {
            "remote_access": "read-only SSH",
            "remote_writes": False,
            "local_row_level_data": False,
            "patient_identifiers": False,
            "raw_report_text": False,
        },
        "morphometry_boundaries": {
            "linked_percent": morph["linkage"]["linked_pct"],
            "minimum_display_n": MIN_MORPH_N,
            "available_case": True,
            "manual_linkage_audit": False,
            "manual_parser_audit": False,
            "inference": "descriptive only",
        },
        "validation": validation,
        "files": files,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Locked-registry descriptive figure manifest",
        "",
        f"- Paper window: {registry['cohort']['window']}",
        f"- Actual observed dates: {registry['cohort']['actual_observed_dates']}",
        f"- Canonical examinations: {registry['cohort']['canonical_checks']:,}",
        f"- Unique patients in window: {registry['cohort']['unique_patients']:,}",
        f"- Patient-first main-11 cohort: {registry['cohort']['patient_first_main11']:,}",
        f"- Final model-linked main-11 cohort: {morph['dataset']['n']:,} "
        f"({morph['linkage']['linked_pct']:.3f}% of eligible).",
        "- Remote access: read-only SSH; no remote writes.",
        "- Local outputs: aggregate-only; no identifiers, raw text, or patient rows.",
        "- Morphometry: available-case descriptive summaries only; parser and fallback linkage have no independent manual audit.",
        f"- Capacity scenario: {SERVICE_CAPACITY_PER_MONTH:.0f} examinations/month; not observed turnaround time.",
        "",
        "## Validation",
        "",
    ]
    for check in validation["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        lines.append(
            f"- [{mark}] [{check['category']}] {check['name']}: {check['detail']}"
        )
    lines.extend(["", "## Files", ""])
    for item in files:
        lines.append(
            f"- `{item['path']}` — {item['bytes']:,} bytes — SHA-256 `{item['sha256']}`"
        )
    (output_dir / "manifest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """Fetch aggregate data, create source CSVs, render figures, and validate."""
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    bundle_mode = (
        script_dir.name == "scripts"
        and (script_dir.parent / "aggregate_results").exists()
    )
    work_root = script_dir.parent
    output_dir = work_root / "reproduced_figures" if bundle_mode else script_dir
    source_dir = output_dir / "source_data"
    source_dir.mkdir(parents=True, exist_ok=True)
    aggregate_input_dir = work_root / "source_data" if bundle_mode else source_dir
    registry_input_json = aggregate_input_dir / "remote_registry_aggregate.json"
    morph_input_json = aggregate_input_dir / "remote_morphometry_aggregate.json"
    registry_json = source_dir / "remote_registry_aggregate.json"
    morph_json = source_dir / "remote_morphometry_aggregate.json"

    if not args.reuse_aggregate and not args.remote_root:
        raise ValueError("--remote-root is required unless --reuse-aggregate is used")
    if not args.reuse_aggregate and not args.ssh_alias:
        raise ValueError("--ssh-alias is required unless --reuse-aggregate is used")

    if args.reuse_aggregate and registry_input_json.exists():
        registry = json.loads(registry_input_json.read_text(encoding="utf-8"))
    else:
        registry = remote_execute(
            REMOTE_REGISTRY_CODE,
            args.ssh_alias,
            args.timeout,
            args.remote_root,
            args.remote_python,
        )
        registry_repeat = remote_execute(
            REMOTE_REGISTRY_CODE,
            args.ssh_alias,
            args.timeout,
            args.remote_root,
            args.remote_python,
        )
        registry["determinism_repeat"] = {
            "exact_aggregate_match": registry == registry_repeat,
            "repeat_sha256": hashlib.sha256(
                json.dumps(
                    registry_repeat,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
        registry_json.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if args.reuse_aggregate and morph_input_json.exists():
        morph = json.loads(morph_input_json.read_text(encoding="utf-8"))
    else:
        morph_code = load_modeling_aggregate_code(work_root, output_dir)
        morph = remote_execute(
            morph_code,
            args.ssh_alias,
            args.timeout,
            args.remote_root,
            args.remote_python,
        )
        morph_repeat = remote_execute(
            morph_code,
            args.ssh_alias,
            args.timeout,
            args.remote_root,
            args.remote_python,
        )
        morph["determinism_repeat"] = {
            "exact_aggregate_match": morph == morph_repeat,
            "repeat_sha256": hashlib.sha256(
                json.dumps(
                    morph_repeat,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
        morph_json.write_text(
            json.dumps(morph, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    rows = derive_source_rows(registry, morph)
    save_source_data(source_dir, rows)
    render_figure1(rows, output_dir / "Figure1_v2.png")
    render_figure2(rows, output_dir / "Figure2_v2.png")
    render_figure4(rows, output_dir / "Figure4_v2.png")
    validation = validate(rows, output_dir, registry, morph)
    (output_dir / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_manifest(output_dir, registry, morph, validation)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "canonical_checks": registry["cohort"]["canonical_checks"],
                "patient_first_main11": registry["cohort"]["patient_first_main11"],
                "model_linked_main11": morph["dataset"]["n"],
                "development": morph["dataset"]["split_counts"]["development"],
                "temporal_test": morph["dataset"]["split_counts"]["temporal_test"],
                "morphology_linked_pct": morph["linkage"]["linked_pct"],
                "validation_passed": validation["passed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not validation["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
