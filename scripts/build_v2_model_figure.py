"""Build the patient-level temporal-validation figure from locked aggregate results.

The script never reads or writes patient-level identifiers.  Every plotted value is
loaded from the privacy-screened aggregate modeling JSON produced by
``remote_v2_modeling.py``.  Source-data tables are emitted beside the figure so the
plotted values can be checked independently.
"""

from __future__ import annotations

import csv
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from matplotlib.patches import Patch

SCRIPT_DIR = Path(__file__).resolve().parent
BUNDLE_MODE = (
    SCRIPT_DIR.name == "scripts" and (SCRIPT_DIR.parent / "aggregate_results").exists()
)
ROOT = SCRIPT_DIR.parent
RESULTS = ROOT / (
    "aggregate_results/v2_modeling_results.json"
    if BUNDLE_MODE
    else "logs/v2_modeling_results.json"
)
OUT_DIR = ROOT / "reproduced_figures" if BUNDLE_MODE else SCRIPT_DIR
SOURCE_DIR = OUT_DIR / "source_data"
FIGURE = OUT_DIR / "Figure3_v2.png"
MANIFEST = OUT_DIR / "Figure3_v2_manifest.json"
PRIMARY_MODEL_KEY = "random_forest"

CLASS_ORDER = [
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

MODEL_LABELS = {
    "logistic_regression": "Logistic\nregression",
    "random_forest": "Random\nforest",
    "gradient_boosting": "Gradient\nboosting",
    "svm_rbf": "RBF SVM",
    "mlp": "MLP",
    "adaboost": "AdaBoost",
}

FEATURE_LABELS = {
    "full": "Age + sex +\n7 TEM features",
    "full_minus_age": "Sex + 7\nTEM features",
    "age_sex_only": "Age + sex",
    "morphometry_only": "7 TEM\nfeatures",
    "missingness_only_diagnostic": "Missingness\nonly",
}

COLORS = {
    "navy": "#25476A",
    "blue": "#4C78A8",
    "teal": "#2A9D8F",
    "orange": "#E28E2C",
    "red": "#C44E52",
    "grey": "#8C8C8C",
    "light": "#EAF0F6",
}


def load_results() -> dict[str, Any]:
    """Load and minimally validate the aggregate modeling result."""

    if not RESULTS.exists() or RESULTS.stat().st_size == 0:
        raise FileNotFoundError(f"Final modeling result is unavailable: {RESULTS}")
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    required = {
        "audit",
        "analysis_protocol",
        "model_results",
        "headline6_direct_binary",
        "major_source_loho",
    }
    missing = required.difference(data)
    if missing:
        raise ValueError(f"Modeling result is incomplete: {sorted(missing)}")
    counts = data["audit"]["counts"]
    if counts.get("temporal_test", 0) <= 0 or counts.get("development", 0) <= 0:
        raise ValueError("Development or temporal-test cohort is empty")
    return data


def write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    """Write a UTF-8 source-data table."""

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def png_dimensions(path: Path) -> tuple[int, int]:
    """Read width and height directly from a PNG IHDR chunk."""

    header = path.read_bytes()[:24]
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a valid PNG file: {path}")
    return struct.unpack(">II", header[16:24])


def panel_label(
    ax: plt.Axes,
    label: str,
    *,
    x: float = -0.22,
    y: float = 1.11,
) -> None:
    """Place a consistent panel label."""

    ax.text(
        x,
        y,
        label,
        transform=ax.transAxes,
        color="#000000",
        fontsize=20,
        fontweight="bold",
        va="top",
    )


def build_figure(data: dict[str, Any]) -> dict[str, Any]:
    """Create Figure 3 and return a machine-readable plotting manifest."""

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", context="talk")
    plt.rcParams.update(
        {
            "font.family": "Arial",
            "font.size": 13,
            "axes.titlesize": 14.5,
            "axes.titleweight": "bold",
            "axes.labelsize": 13.5,
            "xtick.labelsize": 11.5,
            "ytick.labelsize": 11.5,
            "legend.fontsize": 10.5,
        }
    )

    fig = plt.figure(figsize=(17, 10.5))
    grid = fig.add_gridspec(
        2,
        3,
        width_ratios=[1.02, 1.15, 1.18],
        left=0.055,
        right=0.975,
        bottom=0.07,
        top=0.88,
        wspace=0.30,
        hspace=0.44,
    )
    axes = [fig.add_subplot(grid[row, col]) for row in range(2) for col in range(3)]
    ax_a, ax_b, ax_c, ax_d, ax_e, ax_f = axes

    # A. Cohort construction.
    counts = data["audit"]["counts"]
    flow = [
        ("Canonical checks\n2014-05 to 2026-04", counts["canonical_checks_in_window"]),
        ("Patient-first\nrecords", counts["unique_patients_first_check"]),
        ("Main 11 disease\nphenotypes", counts["main11_first_check_patients"]),
        ("Linked\nmodel cohort", counts["main11_linked_patients"]),
    ]
    ax_a.set_xlim(0, 1)
    ax_a.set_ylim(0, 1)
    ax_a.axis("off")
    y_positions = np.linspace(0.84, 0.18, len(flow))
    for index, ((label, value), y_value) in enumerate(zip(flow, y_positions)):
        color = COLORS["navy"] if index == len(flow) - 1 else COLORS["light"]
        text_color = "white" if index == len(flow) - 1 else COLORS["navy"]
        ax_a.text(
            0.5,
            y_value,
            f"{label}\n$\\bf{{n={value:,}}}$",
            ha="center",
            va="center",
            color=text_color,
            bbox={
                "boxstyle": "round,pad=0.55",
                "facecolor": color,
                "edgecolor": COLORS["navy"],
                "linewidth": 1.6,
            },
        )
        if index < len(flow) - 1:
            ax_a.annotate(
                "",
                xy=(0.5, y_positions[index + 1] + 0.09),
                xytext=(0.5, y_value - 0.09),
                arrowprops={"arrowstyle": "-|>", "color": COLORS["grey"], "lw": 1.6},
            )
    ax_a.text(
        0.5,
        -0.04,
        f"Development: n={counts['development']:,} (through 2021)\n"
        f"Temporal test: n={counts['temporal_test']:,} (2022 to 2026-04)",
        ha="center",
        va="bottom",
        fontsize=11.5,
    )
    ax_a.set_title("Patient-level cohort\nconstruction", pad=12)
    panel_label(ax_a, "A")
    write_csv(
        SOURCE_DIR / "figure3a_cohort_flow.csv",
        ["stage", "n"],
        [[label.replace("\n", " "), value] for label, value in flow]
        + [
            ["Development", counts["development"]],
            ["Temporal test", counts["temporal_test"]],
        ],
    )

    # B. Temporal performance of all evaluated models using the full feature set.
    full = data["model_results"]["full"]
    model_keys = [key for key in MODEL_LABELS if key in full]
    macro_f1 = [full[key]["temporal_test"]["macro_f1"] for key in model_keys]
    ci = [
        full[key]["temporal_test"]["bootstrap_95ci"]["macro_f1"] for key in model_keys
    ]
    error_low = [value - interval[0] for value, interval in zip(macro_f1, ci)]
    error_high = [interval[1] - value for value, interval in zip(macro_f1, ci)]
    if PRIMARY_MODEL_KEY not in model_keys:
        raise ValueError(
            f"Prespecified primary model is unavailable: {PRIMARY_MODEL_KEY}"
        )
    primary_key = PRIMARY_MODEL_KEY
    highest_observed_key = max(
        model_keys,
        key=lambda key: full[key]["temporal_test"]["macro_f1"],
    )
    bar_colors = [
        COLORS["orange"] if key == primary_key else COLORS["blue"] for key in model_keys
    ]
    x_values = np.arange(len(model_keys))
    ax_b.bar(x_values, macro_f1, color=bar_colors, edgecolor="white", width=0.72)
    ax_b.errorbar(
        x_values,
        macro_f1,
        yerr=[error_low, error_high],
        fmt="none",
        ecolor="#333333",
        capsize=4,
        linewidth=1.4,
    )
    for x_value, score in zip(x_values, macro_f1):
        ax_b.text(x_value, score + 0.018, f"{score:.3f}", ha="center", fontsize=11.5)
    ax_b.set_xticks(x_values, [MODEL_LABELS[key] for key in model_keys])
    ax_b.set_ylabel("Macro-F1")
    ax_b.set_ylim(0, max(0.5, max(interval[1] for interval in ci) + 0.08))
    ax_b.set_title("Temporal test performance\n(full feature set)")
    ax_b.legend(
        handles=[
            Patch(
                facecolor=COLORS["orange"],
                label="Prespecified primary model",
            )
        ],
        loc="upper right",
        frameon=False,
    )
    ax_b.grid(axis="x", visible=False)
    panel_label(ax_b, "B")
    write_csv(
        SOURCE_DIR / "figure3b_temporal_models.csv",
        ["model", "macro_f1", "ci95_lower", "ci95_upper", "macro_ovr_auc"],
        [
            [
                key,
                full[key]["temporal_test"]["macro_f1"],
                ci_value[0],
                ci_value[1],
                full[key]["temporal_test"]["macro_ovr_auc"],
            ]
            for key, ci_value in zip(model_keys, ci)
        ],
    )

    # C. Row-normalised temporal confusion matrix for the prespecified primary model.
    primary_test = full[primary_key]["temporal_test"]
    confusion = np.asarray(
        primary_test["confusion_matrix_rows_true_cols_pred"], dtype=float
    )
    if confusion.shape != (len(CLASS_ORDER), len(CLASS_ORDER)):
        raise ValueError(f"Unexpected confusion-matrix shape: {confusion.shape}")
    row_sums = confusion.sum(axis=1, keepdims=True)
    normalised = np.divide(
        confusion, row_sums, out=np.zeros_like(confusion), where=row_sums > 0
    )
    sns.heatmap(
        normalised,
        ax=ax_c,
        cmap="Blues",
        vmin=0,
        vmax=1,
        square=True,
        cbar_kws={"label": "Row proportion", "shrink": 0.78},
        xticklabels=CLASS_ORDER,
        yticklabels=CLASS_ORDER,
    )
    ax_c.set_xlabel("Predicted phenotype")
    ax_c.set_ylabel("True phenotype")
    ax_c.tick_params(axis="x", rotation=50)
    ax_c.tick_params(axis="y", rotation=0)
    ax_c.set_title("Temporal confusion matrix:\nprespecified random forest")
    panel_label(ax_c, "C", x=-0.25, y=1.13)
    write_csv(
        SOURCE_DIR / "figure3c_confusion_matrix_row_normalized.csv",
        ["true_class"] + CLASS_ORDER,
        [
            [class_name] + list(normalised[index])
            for index, class_name in enumerate(CLASS_ORDER)
        ],
    )

    # D. Direct binary discrimination for the six prespecified headline classes.
    binary = data["headline6_direct_binary"]
    binary_classes = [
        class_name
        for class_name in ["IgAN", "IgAVN", "MCD", "MN", "LN", "FSGS"]
        if class_name in binary
    ]
    auc = [
        binary[class_name]["direct_binary_rf"]["roc_auc"]
        for class_name in binary_classes
    ]
    average_precision = [
        binary[class_name]["direct_binary_rf"]["average_precision"]
        for class_name in binary_classes
    ]
    x_values = np.arange(len(binary_classes))
    width = 0.36
    ax_d.bar(x_values - width / 2, auc, width, label="ROC AUC", color=COLORS["teal"])
    ax_d.bar(
        x_values + width / 2,
        average_precision,
        width,
        label="Average precision",
        color=COLORS["orange"],
    )
    ax_d.set_xticks(x_values, binary_classes)
    ax_d.set_ylim(0, 1.18)
    ax_d.set_ylabel("Discrimination")
    ax_d.set_title("Prespecified direct binary\nrandom forests")
    ax_d.legend(
        loc="upper center",
        ncol=2,
        frameon=False,
    )
    ax_d.grid(axis="x", visible=False)
    panel_label(ax_d, "D")
    write_csv(
        SOURCE_DIR / "figure3d_direct_binary.csv",
        [
            "class",
            "roc_auc",
            "average_precision",
            "f1_at_0_5",
            "sensitivity_at_0_5",
            "specificity_at_0_5",
            "support_positive",
            "support_negative",
        ],
        [
            [
                class_name,
                binary[class_name]["direct_binary_rf"]["roc_auc"],
                binary[class_name]["direct_binary_rf"]["average_precision"],
                binary[class_name]["direct_binary_rf"]["f1_at_0_5"],
                binary[class_name]["direct_binary_rf"]["sensitivity_at_0_5"],
                binary[class_name]["direct_binary_rf"]["specificity_at_0_5"],
                binary[class_name]["direct_binary_rf"]["support_positive"],
                binary[class_name]["direct_binary_rf"]["support_negative"],
            ]
            for class_name in binary_classes
        ],
    )

    # E. Feature-set sensitivity for the prespecified primary algorithm.
    feature_sets = [key for key in FEATURE_LABELS if key in data["model_results"]]
    feature_scores = [
        data["model_results"][feature_set][primary_key]["temporal_test"]["macro_f1"]
        for feature_set in feature_sets
    ]
    y_values = np.arange(len(feature_sets))
    colors = [
        COLORS["orange"] if key == "full" else COLORS["blue"] for key in feature_sets
    ]
    ax_e.barh(y_values, feature_scores, color=colors, height=0.66)
    for y_value, score in zip(y_values, feature_scores):
        ax_e.text(score + 0.008, y_value, f"{score:.3f}", va="center", fontsize=11.5)
    ax_e.set_yticks(y_values, [FEATURE_LABELS[key] for key in feature_sets])
    ax_e.invert_yaxis()
    ax_e.set_xlabel("Temporal macro-F1")
    ax_e.set_xlim(0, max(0.5, max(feature_scores) + 0.09))
    ax_e.set_title("Feature-set sensitivity\n(random forest)")
    ax_e.grid(axis="y", visible=False)
    panel_label(ax_e, "E")
    write_csv(
        SOURCE_DIR / "figure3e_feature_set_sensitivity.csv",
        ["feature_set", "model", "macro_f1", "macro_ovr_auc"],
        [
            [
                feature_set,
                primary_key,
                data["model_results"][feature_set][primary_key]["temporal_test"][
                    "macro_f1"
                ],
                data["model_results"][feature_set][primary_key]["temporal_test"][
                    "macro_ovr_auc"
                ],
            ]
            for feature_set in feature_sets
        ],
    )

    # F. Cross-referral-source generalization analysis; labels are anonymised.
    holdouts = data["major_source_loho"]["holdouts"]
    source_rows = list(holdouts.items())
    source_labels = [f"Source {chr(65 + index)}" for index in range(len(source_rows))]
    loho_f1 = [values["macro_f1_present_classes"] for _, values in source_rows]
    loho_auc = [values["mean_ovr_auc_present_classes"] for _, values in source_rows]
    y_values = np.arange(len(source_rows))
    ax_f.scatter(
        loho_f1,
        y_values,
        s=110,
        label="Macro-F1 (present classes)",
        color=COLORS["red"],
        zorder=3,
    )
    ax_f.scatter(
        loho_auc,
        y_values,
        s=110,
        label="Mean one-vs-rest AUC",
        color=COLORS["teal"],
        zorder=3,
    )
    for y_value, f1_score, auc_score in zip(y_values, loho_f1, loho_auc):
        ax_f.plot(
            [f1_score, auc_score], [y_value, y_value], color="#C7C7C7", lw=2, zorder=1
        )
    ax_f.set_yticks(y_values, source_labels)
    # Leave a dedicated band below Source D for the legend, so neither symbol is hidden.
    ax_f.set_ylim(len(source_rows) - 0.05, -0.35)
    ax_f.set_xlim(0, 1.02)
    ax_f.set_xlabel("Performance")
    ax_f.set_title("Referral-source holdout\n(random forest)")
    ax_f.legend(
        loc="lower right",
        bbox_to_anchor=(0.98, 0.01),
        ncol=1,
        frameon=False,
        fontsize=9.5,
    )
    ax_f.grid(axis="y", visible=False)
    panel_label(ax_f, "F")
    write_csv(
        SOURCE_DIR / "figure3f_source_holdout.csv",
        [
            "source_label",
            "train_n",
            "test_n",
            "present_classes_n",
            "macro_f1_present_classes",
            "mean_ovr_auc_present_classes",
        ],
        [
            [
                label,
                values["train_n"],
                values["test_n"],
                len(values["test_present_classes"]),
                values["macro_f1_present_classes"],
                values["mean_ovr_auc_present_classes"],
            ]
            for label, (_, values) in zip(source_labels, source_rows)
        ],
    )

    fig.suptitle(
        "Temporal generalization of report-derived TEM phenotypes",
        fontsize=20,
        fontweight="bold",
        y=0.965,
    )
    fig.savefig(FIGURE, dpi=600, facecolor="white")
    plt.close(fig)

    sha256 = hashlib.sha256(FIGURE.read_bytes()).hexdigest()
    width_px, height_px = png_dimensions(FIGURE)
    source_files = sorted(SOURCE_DIR.glob("figure3*.csv"))
    return {
        "figure": FIGURE.name,
        "sha256": sha256,
        "input": str(RESULTS.relative_to(ROOT)),
        "input_sha256": hashlib.sha256(RESULTS.read_bytes()).hexdigest(),
        "primary_model_full_features": primary_key,
        "highest_observed_temporal_macro_f1_model": highest_observed_key,
        "selection_note": (
            "Random forest was prespecified for the primary confusion matrix, "
            "feature-set sensitivity, direct-binary, and source-holdout analyses; "
            "the highest observed temporal-test model was not used for tuning."
        ),
        "counts": counts,
        "image": {
            "width_px": width_px,
            "height_px": height_px,
            "dpi": 600,
        },
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_data": [path.name for path in source_files],
        "source_data_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_files
        },
        "privacy": "Aggregate values only; referral sources anonymised as Source A-D.",
    }


def main() -> None:
    """Build the figure and write its manifest."""

    data = load_results()
    manifest = build_figure(data)
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
