"""仅用自造合成夹具验证人工审计合同；不读取原报告或生成真实人工结果。"""

from __future__ import annotations

import argparse
import copy
import json
import math
import tempfile
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from audit_contract import (
    FIELDS,
    AuditValidationError,
    answer_status,
    sha256,
    validate_answer,
    validate_reader_metadata,
    validate_sample_answers,
    validate_source_path,
)
from compare_audit import (
    aggregate_results,
    load_key,
    reader_label,
    run,
    validate_verified_audit_result,
    validate_workbook_source,
)

HERE = Path(__file__).resolve().parent
ANSWERS = {
    "glomerulus_count": "10",
    "sclerosis_rate": "球性1个，节段性2个",
    "mesangial_cell_count": "3-5",
    "mesangial_matrix_grade": "轻度",
    "gbm_thickness_nm": "0.3-0.5μm",
    "spike_presence": "未见",
    "foot_process_grade": "节段性或部分或少数",
}
EXPECTED = {
    "glomerulus_count": 10.0,
    "sclerosis_rate": 0.3,
    "mesangial_cell_count": 4.0,
    "mesangial_matrix_grade": 1.0,
    "gbm_thickness_nm": 400.0,
    "spike_presence": 0.0,
    "foot_process_grade": 1.0,
}


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def workbook(
    path: Path, data: pd.DataFrame, role: str, name: str, key_hash: str
) -> None:
    provenance = {
        "schema_version": 1,
        "source_type": "synthetic",
        "role": role,
        "reader_name": name,
        "audit_key_sha256": key_hash,
    }
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        data.to_excel(
            writer,
            sheet_name="裁定表" if role == "adjudicator" else "读取表",
            index=False,
        )
        pd.DataFrame(provenance.items(), columns=["字段", "值"]).to_excel(
            writer, sheet_name="审计来源", index=False
        )


@pytest.fixture
def bundle():
    # 测试临时制品在本项目内生成，且始终显式标注synthetic。
    with tempfile.TemporaryDirectory(
        prefix="_synthetic_contract_", dir=HERE
    ) as directory:
        root = Path(directory)
        key = root / "synthetic_key.json"
        rows = [
            {
                "sample_id": f"S{number:03d}",
                "split": "development" if number < 100 else "temporal_test",
                "link_method": "synthetic_fixture",
                "parsed": dict(EXPECTED),
                "reextracted": dict(EXPECTED),
            }
            for number in range(200)
        ]
        write_json(key, {"rows": rows})
        frame = pd.DataFrame(
            [
                {
                    "样本号": row["sample_id"],
                    **{col: ANSWERS[field] for field, col, *_ in FIELDS},
                }
                for row in rows
            ]
        )
        readers = root / "synthetic_readers.json"
        metadata = {
            "schema_version": 1,
            "source_type": "synthetic",
            "audit_key_sha256": sha256(key),
        }
        for role, name in (
            ("reader1", "合成甲"),
            ("reader2", "合成乙"),
            ("adjudicator", "合成丙"),
        ):
            metadata[role] = {
                "name": name,
                "independent": True,
                "not_involved_in_extraction_rules": True,
                "human_reading_confirmed": False,
                "completed_at": "2026-09-29T09:00:00+09:00",
            }
            if role != "adjudicator":
                path = root / f"{role}.xlsx"
                workbook(path, frame, role, name, sha256(key))
                metadata[role]["worksheet_sha256"] = sha256(path)
        write_json(readers, metadata)
        args = argparse.Namespace(
            key=key,
            readers=readers,
            reader1=root / "reader1.xlsx",
            reader2=root / "reader2.xlsx",
            adjudication=None,
            out=root / "synthetic_result.json",
            label="synthetic",
        )
        yield args, metadata, frame


def update_reader(args, metadata, frame, role="reader2") -> None:
    path = getattr(args, role)
    workbook(path, frame, role, metadata[role]["name"], sha256(args.key))
    metadata[role]["worksheet_sha256"] = sha256(path)
    write_json(args.readers, metadata)


def set_adjudication(args, metadata, rows) -> None:
    args.adjudication = args.out.parent / "adjudication.xlsx"
    workbook(
        args.adjudication,
        pd.DataFrame(rows),
        "adjudicator",
        metadata["adjudicator"]["name"],
        sha256(args.key),
    )
    metadata["adjudication_sha256"] = sha256(args.adjudication)
    write_json(args.readers, metadata)


@pytest.mark.parametrize(
    "field,raw,total,value",
    [
        ("glomerulus_count", "3-5个", "", 4),
        ("glomerulus_count", "150", "", 150),
        ("mesangial_cell_count", "3–5个/区", "", 4),
        ("mesangial_cell_count", "35", "", 35),
        ("gbm_thickness_nm", "500-1000nm", "", 750),
        ("gbm_thickness_nm", "0.3-0.5µm", "", 400),
        ("gbm_thickness_nm", "5纳米", "", 5),
        ("sclerosis_rate", "球性1个，节段性2个", "10", 0.3),
        ("sclerosis_rate", "球性1个", "10", 0.1),
        ("sclerosis_rate", "未见硬化", "10", 0),
        ("mesangial_matrix_grade", "中-重度", "", 2.5),
        ("spike_presence", "形成", "", 1),
        ("foot_process_grade", "广泛性", "", 3),
    ],
)
def test_independent_numeric_and_category_contract(field, raw, total, value):
    assert validate_answer(field, raw, total) == value


@pytest.mark.parametrize(
    "field,raw,total",
    [
        ("glomerulus_count", "", ""),
        ("glomerulus_count", None, ""),
        ("glomerulus_count", "nan", ""),
        ("glomerulus_count", "-", ""),
        ("glomerulus_count", "4-2", ""),
        ("glomerulus_count", "3.2", ""),
        ("mesangial_cell_count", "3-5-7", ""),
        ("gbm_thickness_nm", "300", ""),
        ("gbm_thickness_nm", "0nm", ""),
        ("gbm_thickness_nm", "约300nm", ""),
        ("sclerosis_rate", "接近球性硬化1个", "10"),
        ("sclerosis_rate", "球性1个，球性2个", "10"),
        ("sclerosis_rate", "球性11个", "10"),
        ("sclerosis_rate", "球性1个", ""),
        ("sclerosis_rate", "球性1个", "0"),
        ("sclerosis_rate", "0.1", "10"),
        ("mesangial_matrix_grade", "轻中度", ""),
        ("spike_presence", "0", ""),
        ("foot_process_grade", "可能广泛性", ""),
    ],
)
def test_invalid_never_turns_into_missing(field, raw, total):
    with pytest.raises(AuditValidationError):
        validate_answer(field, raw, total)


def test_explicit_missing_and_undefined_denominator_are_distinct():
    assert math.isnan(validate_answer("gbm_thickness_nm", "未提及"))
    assert answer_status("gbm_thickness_nm", "不明确") == "不明确"
    assert (
        answer_status("sclerosis_rate", "球性1个", "未提及")
        == "derived_missing_denominator"
    )
    assert validate_sample_answers(ANSWERS) == EXPECTED
    with pytest.raises(AuditValidationError):
        validate_sample_answers({"glomerulus_count": "10"})


def test_human_disagreement_not_hidden_by_machine_tolerance():
    second = dict(ANSWERS, gbm_thickness_nm="405nm")
    assert reader_label("gbm_thickness_nm", ANSWERS) != reader_label(
        "gbm_thickness_nm", second
    )
    assert reader_label(
        "gbm_thickness_nm", dict(ANSWERS, gbm_thickness_nm="未提及")
    ) != reader_label("gbm_thickness_nm", dict(ANSWERS, gbm_thickness_nm="不明确"))


def test_full_synthetic_run_is_deterministic_and_not_human(bundle):
    args, _, _ = bundle
    result = run(args)
    digest = sha256(args.out)
    assert run(args) == result
    assert sha256(args.out) == digest
    assert result["label"] == "synthetic"
    assert result["status"] == "SYNTHETIC_TEST_ONLY"
    assert result["dual_reader"] is True and result["n"] == 200
    assert result["pipelines"]["frozen_pipeline"]["error_pct_range"] == [0, 0]
    with pytest.raises(AuditValidationError):
        validate_verified_audit_result(args.out)
    args.out = args.out.with_name("audit_results.json")
    with pytest.raises(AuditValidationError):
        run(args)


def test_pilot_or_renamed_synthetic_cannot_be_human(bundle):
    args, _, _ = bundle
    with pytest.raises(AuditValidationError):
        validate_source_path(Path("pilot") / "renamed.xlsx", "human")
    with pytest.raises(AuditValidationError):
        validate_workbook_source(
            args.reader1, "reader1", "合成甲", sha256(args.key), "human"
        )
    args.label = "human"
    with pytest.raises(AuditValidationError):
        run(args)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra", "blank"])
def test_exact_ids_fail_closed(bundle, mutation):
    args, metadata, frame = bundle
    if mutation == "missing":
        frame = frame.iloc[:-1]
    elif mutation == "duplicate":
        frame.loc[1, "样本号"] = frame.loc[0, "样本号"]
    elif mutation == "extra":
        frame.loc[1, "样本号"] = "S999"
    else:
        frame.loc[1, "样本号"] = ""
    update_reader(args, metadata, frame)
    with pytest.raises(AuditValidationError):
        run(args)


def test_blank_field_and_invalid_enum_fail_before_output(bundle):
    args, metadata, frame = bundle
    for value in ("", "not a category"):
        frame.loc[0, "钉突"] = value
        update_reader(args, metadata, frame)
        with pytest.raises(AuditValidationError):
            run(args)
        assert not args.out.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "absent_role",
        "same_name",
        "no_independence",
        "no_timestamp",
        "wrong_hash",
        "false_human",
    ],
)
def test_identity_contract_blocks_missing_or_invalid_declarations(bundle, mutation):
    args, metadata, _ = bundle
    if mutation == "absent_role":
        metadata.pop("adjudicator")
    elif mutation == "same_name":
        metadata["adjudicator"]["name"] = metadata["reader1"]["name"]
    elif mutation == "no_independence":
        metadata["reader2"]["independent"] = False
    elif mutation == "no_timestamp":
        metadata["reader2"]["completed_at"] = ""
    elif mutation == "wrong_hash":
        metadata["audit_key_sha256"] = "0" * 64
    else:
        metadata["reader1"]["human_reading_confirmed"] = True
    with pytest.raises(AuditValidationError):
        validate_reader_metadata(metadata, sha256(args.key), "synthetic")


def test_workbook_mutation_breaks_hash_binding(bundle):
    args, _, _ = bundle
    book = load_workbook(args.reader1)
    book["读取表"]["B2"] = "12"
    book.save(args.reader1)
    book.close()
    with pytest.raises(AuditValidationError, match="绑定"):
        run(args)


def test_key_duplicate_and_partial_reextraction_block(bundle):
    args, _, _ = bundle
    base = json.loads(args.key.read_text(encoding="utf-8"))
    broken = copy.deepcopy(base)
    broken["rows"][1]["sample_id"] = broken["rows"][0]["sample_id"]
    write_json(args.key, broken)
    with pytest.raises(AuditValidationError):
        load_key(args.key)
    base["rows"][0].pop("reextracted")
    write_json(args.key, base)
    with pytest.raises(AuditValidationError):
        load_key(args.key)


def test_adjudication_requires_every_difference_value_and_reason(bundle):
    args, metadata, frame = bundle
    frame.loc[0, "钉突"] = "形成"
    update_reader(args, metadata, frame)
    with pytest.raises(AuditValidationError, match="待具名仲裁"):
        run(args, write=False)
    assert not (args.out.parent / "audit_adjudication_todo.xlsx").exists()
    good = {
        "样本号": "S000",
        "字段": "spike_presence",
        "读者1": "未见",
        "读者2": "形成",
        "裁定值": "未见",
        "裁定依据": "合成测试：显式否定",
    }
    for column in ("裁定值", "裁定依据"):
        broken = dict(good, **{column: ""})
        set_adjudication(args, metadata, [broken])
        with pytest.raises(AuditValidationError):
            run(args)
    set_adjudication(args, metadata, [good, good])
    with pytest.raises(AuditValidationError, match="重复"):
        run(args)
    set_adjudication(args, metadata, [good])
    result = run(args)
    assert result["adjudication"]["n_resolved"] == 1
    assert (
        result["inter_reader_before_adjudication"]["spike_presence"][
            "percent_agreement"
        ]
        == 99.5
    )
    assert (
        result["pipelines"]["frozen_pipeline"]["fields"]["spike_presence"]["all"][
            "error_n"
        ]
        == 0
    )


def test_adjudication_rejects_stale_answers_or_extra_pairs(bundle):
    args, metadata, frame = bundle
    frame.loc[0, "钉突"] = "形成"
    update_reader(args, metadata, frame)
    good = {
        "样本号": "S000",
        "字段": "spike_presence",
        "读者1": "未见",
        "读者2": "形成",
        "裁定值": "未见",
        "裁定依据": "合成测试",
    }
    for broken in (
        dict(good, 读者1="不明确"),
        dict(good, 样本号="S001"),
        dict(good, 裁定值="INVALID"),
    ):
        set_adjudication(args, metadata, [broken])
        with pytest.raises(AuditValidationError):
            run(args)


def test_missingness_reason_difference_requires_adjudication(bundle):
    args, metadata, frame = bundle
    frame.loc[0, "基底膜厚度"] = "未提及"
    update_reader(args, metadata, frame, "reader1")
    frame.loc[0, "基底膜厚度"] = "不明确"
    update_reader(args, metadata, frame, "reader2")
    with pytest.raises(AuditValidationError, match="待具名仲裁"):
        run(args, write=False)


def test_no_machine_parser_dependency():
    for name in ("audit_contract.py", "compare_audit.py"):
        source = (HERE / name).read_text(encoding="utf-8")
        assert "remote_v2_modeling" not in source
        assert "rvm." not in source


def test_relabelled_synthetic_result_never_becomes_verified_human(bundle):
    args, _, _ = bundle
    result = run(args)
    result["label"] = "human"
    result["status"] = "VERIFIED"
    write_json(args.out, result)
    with pytest.raises(AuditValidationError):
        validate_verified_audit_result(args.out)


def test_error_categories_denominators_and_disagreement_flags():
    rows = {
        f"S{number:03d}": {
            "split": "development" if number < 100 else "temporal_test",
            "parsed": dict(EXPECTED),
            "link_method": "synthetic_fixture",
        }
        for number in range(200)
    }
    human = {sid: dict(EXPECTED) for sid in rows}
    rows["S000"]["parsed"]["glomerulus_count"] = 9.0
    rows["S000"]["parsed"]["gbm_thickness_nm"] = None
    rows["S000"]["parsed"]["mesangial_matrix_grade"] = 2.0
    human["S000"]["foot_process_grade"] = float("nan")
    result = aggregate_results(rows, human)["frozen_pipeline"]
    assert result["fields"]["glomerulus_count"]["all"]["value_differs"] == 1
    assert (
        result["fields"]["gbm_thickness_nm"]["all"]["parser_missing_reader_value"] == 1
    )
    assert (
        result["fields"]["foot_process_grade"]["all"]["parser_value_reader_missing"]
        == 1
    )
    assert result["fields"]["foot_process_grade"]["all"]["error_pct"] == 0.5
    assert result["fields"]["foot_process_grade"]["development"]["error_pct"] == 1.0
    assert result["fields"]["foot_process_grade"]["temporal_test"]["error_pct"] == 0.0
    assert result["disagreement_flags"]["n_records"] == 1
    assert result["disagreement_flags"]["sample_ids"] == ["S000"]
    assert (
        "not evidence of linkage error"
        in result["disagreement_flags"]["interpretation"]
    )


def test_failed_inputs_do_not_replace_previous_output(bundle):
    args, metadata, frame = bundle
    run(args)
    previous = args.out.read_bytes()
    frame.loc[0, "钉突"] = ""
    update_reader(args, metadata, frame)
    with pytest.raises(AuditValidationError):
        run(args)
    assert args.out.read_bytes() == previous
