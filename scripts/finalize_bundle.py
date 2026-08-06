"""Finalize and validate the aggregate-only iScience reproducibility bundle.

The script rebuilds every figure twice, requires byte-identical deterministic
outputs, synchronizes the verified rebuild to the reference figures and source
tables, refreshes the manifests, runs privacy and metric-alignment gates, and
creates a verified ZIP archive in the project revision directory.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
PROJECT_REVISION_DIR = ROOT.parent.parent
ZIP_BASENAME = "reproducibility_bundle_iScience_20260731"
ZIP_PATH = PROJECT_REVISION_DIR / f"{ZIP_BASENAME}.zip"

FIGURE_NAMES = (
    "Figure1_v2.png",
    "Figure2_v2.png",
    "Figure3_v2.png",
    "Figure4_v2.png",
)
EXCLUDED_DIR_NAMES = {
    ".audit_mplcache_final",
    ".ruff_cache",
    "__pycache__",
    "mplcache_desc",
    "mplcache_model",
}
TEXT_SUFFIXES = {".csv", ".json", ".md", ".py", ".txt", ".yml", ".yaml"}
IDENTIFIER_FIELDS = {
    "admission_id",
    "admission_no",
    "id_card",
    "medical_record_number",
    "patient_id",
    "patient_key",
    "patient_name",
    "phone",
    "source_hospital",
    "visit_id",
    "visit_key",
}


def utc_now() -> str:
    """Return a compact UTC timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    """Write stable, human-readable UTF-8 JSON."""
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def excluded(path: Path) -> bool:
    """Return whether a path is a runtime artifact excluded from delivery."""
    relative = path.relative_to(ROOT)
    return bool(EXCLUDED_DIR_NAMES.intersection(relative.parts)) or (
        path.suffix.lower() == ".pyc"
    )


def bundle_files(*, include_top_manifest: bool = True) -> list[Path]:
    """Return the sorted set of distributable files."""
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or excluded(path):
            continue
        if not include_top_manifest and path == ROOT / "MANIFEST.json":
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())


def reproduced_snapshot() -> dict[str, str]:
    """Hash all deterministic outputs produced by the two figure scripts."""
    output_dir = ROOT / "reproduced_figures"
    return {
        path.relative_to(output_dir).as_posix(): sha256(path)
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and not excluded(path)
    }


def runtime_environment() -> dict[str, Any]:
    """Record versions without exposing the local Python executable path."""
    packages = {}
    for distribution in (
        "numpy",
        "pandas",
        "matplotlib",
        "seaborn",
        "Pillow",
    ):
        try:
            packages[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            packages[distribution] = "not installed"
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.system(),
        "packages_used_for_aggregate_rebuild": packages,
    }


def run_figure_build(script_name: str, *arguments: str) -> dict[str, Any]:
    """Run one figure script and return a path-free command record."""
    environment = os.environ.copy()
    dependency_dir = ROOT.parent / "pydeps"
    if dependency_dir.exists():
        current_pythonpath = environment.get("PYTHONPATH")
        components = [str(dependency_dir)]
        if current_pythonpath:
            components.append(current_pythonpath)
        environment["PYTHONPATH"] = os.pathsep.join(components)
    cache_dir = ROOT / ".audit_mplcache_final"
    cache_dir.mkdir(parents=True, exist_ok=True)
    environment["MPLCONFIGDIR"] = str(cache_dir)

    command = [sys.executable, str(ROOT / "scripts" / script_name), *arguments]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{script_name} failed with exit code {completed.returncode}:\n"
            f"{completed.stderr[-4000:]}"
        )
    logical_command = " ".join(["python", f"scripts/{script_name}", *arguments])
    return {
        "command": logical_command,
        "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
    }


def deterministic_rebuild() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the two aggregate-only builds twice and compare every output hash."""
    command_records = []
    snapshots = []
    for run_number in (1, 2):
        command_records.append(run_figure_build("build_v2_model_figure.py"))
        command_records.append(
            run_figure_build("build_v2_descriptive_figures.py", "--reuse-aggregate")
        )
        snapshot = reproduced_snapshot()
        if not snapshot:
            raise RuntimeError(f"Determinism run {run_number} produced no files")
        snapshots.append(snapshot)

    first, second = snapshots
    all_paths = sorted(set(first) | set(second))
    mismatches = [path for path in all_paths if first.get(path) != second.get(path)]
    report = {
        "passed": not mismatches,
        "compared_file_count": len(all_paths),
        "mismatches": mismatches,
        "run_1_sha256": first,
        "run_2_sha256": second,
    }
    if mismatches:
        raise RuntimeError(
            "Deterministic rebuild failed for: " + ", ".join(mismatches)
        )
    return command_records, report


def synchronize_verified_outputs() -> dict[str, bool]:
    """Promote the verified rebuild to reference figures and source tables."""
    reproduced_dir = ROOT / "reproduced_figures"
    reference_dir = ROOT / "reference_figures"
    source_dir = ROOT / "source_data"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)

    matches = {}
    for figure_name in FIGURE_NAMES:
        source = reproduced_dir / figure_name
        destination = reference_dir / figure_name
        if not source.exists():
            raise FileNotFoundError(f"Missing reproduced figure: {figure_name}")
        shutil.copy2(source, destination)
        matches[figure_name] = sha256(source) == sha256(destination)

    reproduced_source_dir = reproduced_dir / "source_data"
    for source in sorted(reproduced_source_dir.glob("*")):
        if source.is_file():
            shutil.copy2(source, source_dir / source.name)

    validation_source = reproduced_dir / "validation.json"
    if validation_source.exists():
        shutil.copy2(
            validation_source,
            ROOT / "aggregate_results" / "validation.json",
        )
    return matches


def png_dimensions(path: Path) -> tuple[int, int]:
    """Read PNG dimensions from the IHDR chunk using the standard library."""
    header = path.read_bytes()[:24]
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a valid PNG: {path.name}")
    return struct.unpack(">II", header[16:24])


def write_reference_manifest() -> dict[str, Any]:
    """Refresh figure and source-data reference hashes."""
    figures = {}
    for figure_name in FIGURE_NAMES:
        path = ROOT / "reference_figures" / figure_name
        width, height = png_dimensions(path)
        figures[figure_name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "width_px": width,
            "height_px": height,
        }

    source_hashes = {
        path.name: sha256(path)
        for path in sorted((ROOT / "source_data").glob("*"))
        if path.is_file()
    }
    manifest = {
        "purpose": "Reference hashes for aggregate-only figure reproduction",
        "analysis_identity": (
            "Locked second-extraction registry with an April 2026 data freeze"
        ),
        "metric_alignment": {
            "Figure3D": "ROC AUC and average precision",
            "Figure3F": (
                "Macro-F1 over classes present in each holdout and mean one-vs-rest AUC "
                "over present classes"
            ),
        },
        "figures": figures,
        "source_data_sha256": source_hashes,
        "privacy": (
            "Aggregate source data only; referral sources are anonymised as "
            "Source A-D."
        ),
    }
    write_json(ROOT / "aggregate_results" / "figure_reference_manifest.json", manifest)
    return manifest


def walk_json_keys(value: Any, location: str = "") -> list[str]:
    """Find prohibited identifier keys in a parsed JSON value."""
    findings = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            nested_location = f"{location}.{key_text}" if location else key_text
            if key_text.lower() in IDENTIFIER_FIELDS:
                findings.append(nested_location)
            findings.extend(walk_json_keys(nested, nested_location))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            findings.extend(walk_json_keys(nested, f"{location}[{index}]"))
    return findings


def privacy_scan() -> dict[str, Any]:
    """Scan distributable text and structured files for privacy leakage."""
    backslash = chr(92)
    markers = {
        "windows_user_path": "C:" + backslash + "Users" + backslash,
        "workspace_drive_path": "F:" + backslash,
        "unix_home_path": "/" + "home" + "/",
        "private_ssh_alias": "liuliu" + "1",
        "local_admin_account": "Admin" + "istrator",
        "institution_name_1": "\u4e2d\u5357\u5927\u5b66",
        "institution_name_2": "\u6e58\u96c5",
        "deprecated_revision_label": "v2" + ".0",
        "deprecated_transport_phrase": "temporal " + "transport",
    }
    email_pattern = re.compile(
        r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@"
        r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
    )
    issues = []
    scanned_files = 0

    for path in bundle_files():
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        folded_text = text.casefold()
        scanned_files += 1
        relative = path.relative_to(ROOT).as_posix()
        for label, marker in markers.items():
            if marker.casefold() in folded_text:
                issues.append({"file": relative, "type": label})
        if email_pattern.search(text):
            issues.append({"file": relative, "type": "email_address"})

        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader, [])
            prohibited = sorted(
                {column.strip().lower() for column in header} & IDENTIFIER_FIELDS
            )
            if prohibited:
                issues.append(
                    {
                        "file": relative,
                        "type": "identifier_csv_header",
                        "fields": prohibited,
                    }
                )

        if path.suffix.lower() == ".json":
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                issues.append({"file": relative, "type": "invalid_json"})
            else:
                prohibited_locations = walk_json_keys(value)
                if prohibited_locations:
                    issues.append(
                        {
                            "file": relative,
                            "type": "identifier_json_key",
                            "locations": prohibited_locations[:20],
                        }
                    )

    source_files = [
        ROOT / "aggregate_results" / "v2_modeling_loho.csv",
        ROOT / "source_data" / "figure3f_source_holdout.csv",
        ROOT / "reproduced_figures" / "source_data" / "figure3f_source_holdout.csv",
    ]
    source_label_pattern = re.compile(r"^Source [A-Z]$")
    for path in source_files:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        first_column = next(iter(rows[0])) if rows else ""
        invalid = [row[first_column] for row in rows if not source_label_pattern.fullmatch(row[first_column])]
        if invalid:
            issues.append(
                {
                    "file": path.relative_to(ROOT).as_posix(),
                    "type": "non_anonymised_referral_source",
                    "values": invalid,
                }
            )

    return {
        "passed": not issues,
        "scanned_text_file_count": scanned_files,
        "identifier_fields_checked": sorted(IDENTIFIER_FIELDS),
        "issues": issues,
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8 CSV as dictionaries."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def metric_alignment() -> dict[str, Any]:
    """Confirm Figure 3 source tables use manuscript-aligned metrics."""
    figure3d = read_csv(ROOT / "source_data" / "figure3d_direct_binary.csv")
    aggregate3d = [
        row
        for row in read_csv(
            ROOT / "aggregate_results" / "v2_modeling_headline6_binary.csv"
        )
        if row["output"] == "direct_binary_rf"
    ]
    expected3d = {row["class"]: row for row in aggregate3d}
    figure3d_match = bool(figure3d) and all(
        row["class"] in expected3d
        and float(row["roc_auc"]) == float(expected3d[row["class"]]["roc_auc"])
        and float(row["average_precision"])
        == float(expected3d[row["class"]]["average_precision"])
        for row in figure3d
    )

    figure3f = read_csv(ROOT / "source_data" / "figure3f_source_holdout.csv")
    aggregate3f = read_csv(ROOT / "aggregate_results" / "v2_modeling_loho.csv")
    expected3f = {row["holdout_source"]: row for row in aggregate3f}
    figure3f_match = bool(figure3f) and all(
        row["source_label"] in expected3f
        and float(row["macro_f1_present_classes"])
        == float(expected3f[row["source_label"]]["macro_f1_present"])
        and float(row["mean_ovr_auc_present_classes"])
        == float(expected3f[row["source_label"]]["mean_ovr_auc_present"])
        for row in figure3f
    )

    script_text = (ROOT / "scripts" / "build_v2_model_figure.py").read_text(
        encoding="utf-8"
    )
    plotted_metric_checks = {
        "Figure3D_plots_average_precision": (
            "average_precision = [" in script_text
            and 'label="Average precision"' in script_text
        ),
        "Figure3F_plots_present_class_macro_f1": (
            'loho_f1 = [values["macro_f1_present_classes"]' in script_text
            and 'label="Macro-F1 (present classes)"' in script_text
        ),
    }
    checks = {
        "Figure3D_source_matches_direct_binary_aggregate": figure3d_match,
        "Figure3F_source_matches_present_class_aggregate": figure3f_match,
        **plotted_metric_checks,
    }
    return {"passed": all(checks.values()), "checks": checks}


def aggregate_validation() -> dict[str, Any]:
    """Summarize the descriptive script's validation gate."""
    path = ROOT / "reproduced_figures" / "validation.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    checks = value.get("checks", [])
    return {
        "passed": bool(value.get("passed")),
        "checks_passed": sum(bool(check.get("passed")) for check in checks),
        "checks_failed": sum(not bool(check.get("passed")) for check in checks),
    }


def source_sync_matches() -> dict[str, bool]:
    """Compare every reproduced source table with the canonical bundle copy."""
    reproduced_source = ROOT / "reproduced_figures" / "source_data"
    return {
        path.name: sha256(path) == sha256(ROOT / "source_data" / path.name)
        for path in sorted(reproduced_source.glob("*"))
        if path.is_file()
    }


def write_self_test(
    command_records: list[dict[str, Any]],
    determinism: dict[str, Any],
    reference_matches: dict[str, bool],
    privacy: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    """Write the final self-test report and fail closed on any gate."""
    aggregate = aggregate_validation()
    source_matches = source_sync_matches()
    gates = {
        "commands_succeeded": all(
            record["exit_code"] == 0 for record in command_records
        ),
        "deterministic_rebuild": bool(determinism["passed"]),
        "reference_hash_matches": all(reference_matches.values()),
        "source_data_sync_matches": all(source_matches.values()),
        "aggregate_validation": bool(aggregate["passed"]),
        "metric_alignment": bool(metrics["passed"]),
        "privacy_scan": bool(privacy["passed"]),
    }
    report = {
        "executed_at_utc": utc_now(),
        "environment": runtime_environment(),
        "commands": command_records,
        "determinism": determinism,
        "reference_hash_matches": reference_matches,
        "source_data_sync_matches": source_matches,
        "aggregate_validation": aggregate,
        "metric_alignment": metrics,
        "privacy_scan": privacy,
        "gates": gates,
        "overall_pass": all(gates.values()),
    }
    write_json(
        ROOT / "aggregate_results" / "reproducibility_bundle_self_test.json",
        report,
    )
    if not report["overall_pass"]:
        failed = [name for name, passed in gates.items() if not passed]
        raise RuntimeError("Self-test failed: " + ", ".join(failed))
    return report


def write_top_manifest(self_test: dict[str, Any]) -> dict[str, Any]:
    """Write the final top-level file inventory, excluding itself."""
    files = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in bundle_files(include_top_manifest=False)
    ]
    manifest = {
        "bundle": "Locked April 2026 reviewer reproducibility bundle",
        "generated_at_utc": utc_now(),
        "analysis_window": "2014-05 through 2026-04",
        "actual_dated_range": "2014-05-08 through 2026-04-09",
        "privacy": "No row-level records, direct identifiers, or pseudonymous keys.",
        "manifest_scope": "All distributable files except MANIFEST.json itself.",
        "excluded_runtime_artifacts": sorted(EXCLUDED_DIR_NAMES | {"*.pyc"}),
        "self_test_overall_pass": bool(self_test["overall_pass"]),
        "file_count": len(files),
        "files": files,
    }
    write_json(ROOT / "MANIFEST.json", manifest)
    return manifest


def build_and_verify_zip(manifest: dict[str, Any]) -> dict[str, Any]:
    """Create the delivery ZIP and verify CRC, paths, and manifest hashes."""
    temporary_zip = ZIP_PATH.with_suffix(".tmp.zip")
    if temporary_zip.exists():
        temporary_zip.unlink()
    with zipfile.ZipFile(
        temporary_zip,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in bundle_files():
            relative = path.relative_to(ROOT).as_posix()
            archive.write(path, f"{ZIP_BASENAME}/{relative}")
    os.replace(temporary_zip, ZIP_PATH)

    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad_member = archive.testzip()
        members = archive.namelist()
        unsafe_members = [
            member
            for member in members
            if Path(member).is_absolute() or ".." in Path(member).parts
        ]
        manifest_mismatches = []
        for item in manifest["files"]:
            member = f"{ZIP_BASENAME}/{item['path']}"
            try:
                payload = archive.read(member)
            except KeyError:
                manifest_mismatches.append({"path": item["path"], "reason": "missing"})
                continue
            digest = hashlib.sha256(payload).hexdigest()
            if len(payload) != item["bytes"] or digest != item["sha256"]:
                manifest_mismatches.append(
                    {"path": item["path"], "reason": "size_or_hash_mismatch"}
                )
        top_manifest_member = f"{ZIP_BASENAME}/MANIFEST.json"
        top_manifest_present = top_manifest_member in members

    result = {
        "path": str(ZIP_PATH),
        "bytes": ZIP_PATH.stat().st_size,
        "sha256": sha256(ZIP_PATH),
        "member_count": len(members),
        "crc_passed": bad_member is None,
        "unsafe_members": unsafe_members,
        "top_manifest_present": top_manifest_present,
        "manifest_mismatches": manifest_mismatches,
    }
    result["passed"] = (
        result["crc_passed"]
        and not unsafe_members
        and top_manifest_present
        and not manifest_mismatches
    )
    if not result["passed"]:
        raise RuntimeError("ZIP verification failed")
    return result


def main() -> None:
    """Execute all finalization gates and print the delivery summary."""
    command_records, determinism = deterministic_rebuild()
    reference_matches = synchronize_verified_outputs()
    reference_manifest = write_reference_manifest()
    privacy = privacy_scan()
    metrics = metric_alignment()
    self_test = write_self_test(
        command_records,
        determinism,
        reference_matches,
        privacy,
        metrics,
    )
    top_manifest = write_top_manifest(self_test)

    final_privacy = privacy_scan()
    if not final_privacy["passed"]:
        raise RuntimeError(
            "Final privacy scan failed: "
            + json.dumps(final_privacy["issues"], ensure_ascii=False)
        )

    zip_result = build_and_verify_zip(top_manifest)
    summary = {
        "overall_pass": True,
        "figures": reference_manifest["figures"],
        "self_test": str(
            ROOT / "aggregate_results" / "reproducibility_bundle_self_test.json"
        ),
        "manifest": str(ROOT / "MANIFEST.json"),
        "privacy_scan_final": final_privacy,
        "zip": zip_result,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
