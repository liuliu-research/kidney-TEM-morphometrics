# ruff: noqa: F821
"""Aggregate-only tail executed after ``remote_v2_modeling.py`` in one namespace.

This file is not run directly. The local figure builder combines it with the
final modeling/linkage implementation, compresses the code, and executes it in
remote memory through read-only SSH. Only the final aggregate JSON is emitted.
"""

from collections import Counter as _Counter
from hashlib import sha256 as _sha256


def _summary(series):
    """Return aggregate numeric summary statistics."""
    values = series.dropna().astype(float)
    if values.empty:
        return {
            "n": 0,
            "mean": None,
            "sd": None,
            "median": None,
            "q1": None,
            "q3": None,
        }
    return {
        "n": int(len(values)),
        "mean": float(values.mean()),
        "sd": float(values.std(ddof=1)) if len(values) > 1 else None,
        "median": float(values.median()),
        "q1": float(values.quantile(0.25)),
        "q3": float(values.quantile(0.75)),
    }


data, audit = build_dataset()
safe = pd.DataFrame(
    {
        "year": data["date"].dt.year.astype(int),
        "disease": data["disease_code"].astype(str),
        "split": data["split"].astype(str),
        "age": data["age"],
        "sex": data["sex_binary"],
        "glom_total": data["glomerulus_count"],
        "sclerosis_pct": data["sclerosis_rate"] * 100.0,
        "mes_cells": data["mesangial_cell_count"],
        "mes_matrix": data["mesangial_matrix_grade"],
        "gbm_nm": data["gbm_thickness_nm"],
        "spike": data["spike_presence"],
        "fp_grade": data["foot_process_grade"],
    }
)
features = [
    "age",
    "sex",
    "glom_total",
    "sclerosis_pct",
    "mes_cells",
    "mes_matrix",
    "gbm_nm",
    "spike",
    "fp_grade",
]

missingness = {
    "overall": {
        feature: {
            "available": int(safe[feature].notna().sum()),
            "missing_pct": float(safe[feature].isna().mean() * 100),
        }
        for feature in features
    },
    "by_year": {
        str(int(year)): {
            "n": int(len(frame)),
            "missing_pct": {
                feature: float(frame[feature].isna().mean() * 100)
                for feature in features
            },
        }
        for year, frame in safe.groupby("year", sort=True)
    },
}

table1 = {}
figure2 = {}
groups = [("Full main-11 linked cohort", safe)] + [
    (disease, safe.loc[safe["disease"] == disease]) for disease in MAIN11
]
for name, frame in groups:
    sex_values = frame["sex"].dropna()
    table1[name] = {
        "n": int(len(frame)),
        "age": _summary(frame["age"]),
        "male_n": int((sex_values == 1).sum()),
        "sex_nonmissing": int(len(sex_values)),
        "male_pct_nonmissing": (
            float((sex_values == 1).mean() * 100) if len(sex_values) else None
        ),
        "gbm_nm": _summary(frame["gbm_nm"]),
        "glomerulus_count": _summary(frame["glom_total"]),
    }
    if name == "Full main-11 linked cohort":
        continue
    fp_counts = _Counter(int(value) for value in frame["fp_grade"].dropna())
    fp_total = int(sum(fp_counts.values()))
    figure2[name] = {
        "n": int(len(frame)),
        "gbm_nm": _summary(frame["gbm_nm"]),
        "mesangial_cells": _summary(frame["mes_cells"]),
        "sclerosis_pct": _summary(frame["sclerosis_pct"]),
        "mesangial_matrix": _summary(frame["mes_matrix"]),
        "spike": {
            "n": int(frame["spike"].notna().sum()),
            "positive_n": int((frame["spike"] == 1).sum()),
            "positive_pct": (
                float((frame["spike"].dropna() == 1).mean() * 100)
                if frame["spike"].notna().any()
                else None
            ),
        },
        "foot_process": {
            "n": fp_total,
            "counts": {str(grade): int(fp_counts.get(grade, 0)) for grade in range(4)},
            "percent": {
                str(grade): (
                    float(fp_counts.get(grade, 0) / fp_total * 100)
                    if fp_total
                    else None
                )
                for grade in range(4)
            },
        },
    }

fingerprint_material = "\n".join(
    sorted(
        f"{date.date()}|{visit_id}|{disease}|{legacy_index}"
        for date, visit_id, disease, legacy_index in zip(
            data["date"],
            data["visit_id"],
            data["disease_code"],
            data["legacy_index"],
            strict=True,
        )
    )
)
main11_pct = float(audit["counts"]["main11_linkage_pct"])
output = {
    "analysis": "locked-registry final-model linked main-11 descriptive aggregate",
    "privacy": {
        "row_level_output": False,
        "identifiers_output": False,
        "raw_text_output": False,
        "remote_writes": False,
    },
    "task_definition": {
        "classes": MAIN11,
        "cohort": (
            "Earliest canonical examination per patient from 2014-05 through "
            "2026-04, linked with the final deterministic modeling rules."
        ),
        "first_exam_tie_break": (
            "exam date, deterministic internal visit_id, then stable source order"
        ),
        "available_case_policy": (
            "No imputation for descriptive morphometry; each statistic reports its own n."
        ),
        "parser_note": (
            "Final conservative modeling parser; fallback linkage lacks independent manual audit."
        ),
    },
    "linkage": {
        "linked": int(audit["counts"]["main11_linked_patients"]),
        "eligible": int(audit["counts"]["main11_first_check_patients"]),
        "linked_pct": main11_pct,
        "registry_linked_rows": int(audit["linkage"]["linked_registry_rows"]),
        "registry_linked_pct": float(audit["linkage"]["linked_pct"]),
        "method_counts": audit["linkage"]["method_counts"],
        "duplicate_old_rows_resolved": audit["linkage"]["duplicate_old_rows_resolved"],
        "publication_caveat": audit["linkage"]["publication_caveat"],
    },
    "dataset": {
        "n": int(len(safe)),
        "year_min": int(safe["year"].min()),
        "year_max": int(safe["year"].max()),
        "class_counts": {
            disease: int((safe["disease"] == disease).sum()) for disease in MAIN11
        },
        "split_counts": {
            split: int((safe["split"] == split).sum())
            for split in ("development", "temporal_test")
        },
        "cohort_fingerprint_sha256": _sha256(
            fingerprint_material.encode("utf-8")
        ).hexdigest(),
    },
    "missingness": missingness,
    "table1": table1,
    "figure2_available_case": figure2,
    "modeling_audit_counts": audit["counts"],
}
print(json.dumps(clean_json(output), ensure_ascii=False, allow_nan=False))
