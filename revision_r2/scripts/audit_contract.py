"""人工字段核对合同：严格输入校验，独立编码，不调用被检验的机器解析器。

此模块只把读者明确录入的结构化答案转成约定数值，不读取报告或替代人判读。
范围取中点；计量单位统一为 nm；硬化率为明确硬化计数之和/总数。
人工参考不套用机器解析器的生理值截断，否则会隐藏该规则造成的错误。
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

FIELDS = [
    ("glomerulus_count", "肾小球总数", "Glomerulus count", "numeric"),
    ("sclerosis_rate", "肾小球硬化", "Sclerosis rate", "numeric"),
    ("mesangial_cell_count", "系膜细胞数/区", "Mesangial cell count", "numeric"),
    ("mesangial_matrix_grade", "系膜基质增生程度", "Mesangial matrix grade", "ordinal"),
    ("gbm_thickness_nm", "基底膜厚度", "GBM thickness", "numeric"),
    ("spike_presence", "钉突", "Spike presence", "binary"),
    ("foot_process_grade", "足突融合程度", "Foot-process grade", "ordinal"),
]
MATRIX_MAP = {
    "无增生": 0.0,
    "轻度": 1.0,
    "轻-中度": 1.5,
    "中度": 2.0,
    "中-重度": 2.5,
    "重度": 3.0,
}
SPIKE_MAP = {"形成": 1.0, "未见": 0.0}
FOOT_MAP = {
    "无融合": 0.0,
    "节段性或部分或少数": 1.0,
    "较广泛或大部分": 2.0,
    "广泛性": 3.0,
}
MISSING_TOKENS = frozenset({"未提及", "不明确"})
FIELD_KEYS = frozenset(f[0] for f in FIELDS)
NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
RANGE = rf"(?P<low>{NUMBER})(?:[-~—–至](?P<high>{NUMBER}))?"
FORBIDDEN_SOURCE = re.compile(
    r"pilot|synthetic|simulation|test[-_ ]?fixture|试读|模拟|合成", re.I
)


class AuditValidationError(ValueError):
    """输入不满足人工核对合同；禁止把失败转换成缺失。"""


def clean(value: object) -> str:
    """清理空值；空值仍须由调用者阻断，不构成有效缺失答案。"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _normalise(raw: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", clean(raw)))


def _midpoint(text: str, *, integer: bool = False) -> float:
    match = re.fullmatch(RANGE, text)
    if match is None:
        raise AuditValidationError("数值只能是单值或递增范围，例如 4 或 3-5")
    low = float(match.group("low"))
    high = float(match.group("high") or low)
    if not math.isfinite(low + high) or low > high:
        raise AuditValidationError("数值必须有限，且范围下限不能大于上限")
    if integer and (not low.is_integer() or not high.is_integer()):
        raise AuditValidationError("计数及其范围端点必须为整数")
    return (low + high) / 2


def _sclerosis_count(text: str) -> float:
    if text in {"未见硬化", "无硬化"}:
        return 0.0
    items = re.split(r"[,，;；、]", text)
    seen: set[str] = set()
    total = 0.0
    for item in items:
        match = re.fullmatch(r"(球性|节段性)(?:硬化)?(\d+)个?", item)
        if match is None or match.group(1) in seen:
            raise AuditValidationError(
                "硬化须填明确计数，如 球性1个，节段性2个；明确否定填 未见硬化；"
                "模糊表述选 不明确，并将原文放入备注"
            )
        seen.add(match.group(1))
        total += int(match.group(2))
    return total


def validate_answer(field: str, raw: object, total_raw: object = "") -> float:
    """校验一项答案并返回编码；合法显式缺失返回 NaN，其他失败抛异常。"""
    if field not in FIELD_KEYS:
        raise AuditValidationError(f"未知字段：{field}")
    text = _normalise(raw)
    if not text:
        raise AuditValidationError("尚未填写；报告未写请明确选择 未提及，不能留空")
    if text in MISSING_TOKENS:
        return float("nan")
    categories = {
        "mesangial_matrix_grade": MATRIX_MAP,
        "spike_presence": SPIKE_MAP,
        "foot_process_grade": FOOT_MAP,
    }
    if field in categories:
        if text not in categories[field]:
            raise AuditValidationError(f"{field} 不在允许选项中")
        return categories[field][text]
    if field == "glomerulus_count":
        return _midpoint(re.sub(r"个$", "", text), integer=True)
    if field == "mesangial_cell_count":
        text = re.sub(r"(?:个?[/／]?区|个)$", "", text)
        return _midpoint(text)
    if field == "gbm_thickness_nm":
        match = re.fullmatch(
            rf"({NUMBER}(?:[-~—–至]{NUMBER})?)(nm|μm|um|纳米|微米)", text, re.I
        )
        if match is None:
            raise AuditValidationError(
                "厚度须填数值/范围及单位，例如 500-1000nm 或 0.3-0.5μm"
            )
        value = _midpoint(match.group(1))
        if value <= 0:
            raise AuditValidationError("基底膜厚度必须大于零")
        return value * (1000 if match.group(2).lower() in {"μm", "um", "微米"} else 1)
    numerator = _sclerosis_count(text)
    denominator = validate_answer("glomerulus_count", total_raw)
    if math.isnan(denominator) or denominator == 0:
        if denominator == 0 and numerator > 0:
            raise AuditValidationError("总数为零而硬化计数大于零，请核对原文")
        return float("nan")
    if numerator > denominator:
        raise AuditValidationError(
            "硬化计数之和大于肾小球总数（范围按中点），请核对原文"
        )
    return numerator / denominator


def answer_status(field: str, raw: object, total_raw: object = "") -> str:
    """区分真实未提及、含糊描述和分母不足，避免统称解析失败。"""
    value = validate_answer(field, raw, total_raw)
    text = _normalise(raw)
    if text in MISSING_TOKENS:
        return text
    return "derived_missing_denominator" if math.isnan(value) else "value"


def validate_sample_answers(answers: Mapping[str, object]) -> dict[str, float]:
    """校验七字段；允许额外 note/备注，但字段键不能缺失。"""
    missing = FIELD_KEYS - set(answers)
    extra = set(answers) - FIELD_KEYS - {"note", "备注"}
    if missing or extra:
        raise AuditValidationError(
            f"字段不完整：缺少 {sorted(missing)}；多余 {sorted(extra)}"
        )
    total_raw = answers["glomerulus_count"]
    return {key: validate_answer(key, answers[key], total_raw) for key, *_ in FIELDS}


def sha256(path: Path) -> str:
    """计算来源文件的字节哈希。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_reader_metadata(
    metadata: Mapping[str, object], key_sha256: str, source_type: str = "human"
) -> None:
    """校验三人身份与声明；这里只校验本人声明的完整性，不能证明现实身份。"""
    if source_type not in {"human", "synthetic"}:
        raise AuditValidationError("来源只能为 human 或 synthetic")
    if (
        metadata.get("schema_version") != 1
        or metadata.get("source_type") != source_type
    ):
        raise AuditValidationError("缺少或不匹配的身份/来源合同")
    if metadata.get("audit_key_sha256") != key_sha256:
        raise AuditValidationError("读者声明未绑定当前抽样密钥")
    names: list[str] = []
    for role in ("reader1", "reader2", "adjudicator"):
        person = metadata.get(role)
        if not isinstance(person, dict):
            raise AuditValidationError(f"缺少具名 {role} 身份声明")
        name = clean(person.get("name"))
        if not name or name.casefold() in {
            "reader1",
            "reader2",
            "adjudicator",
            "待填写",
            "unknown",
        }:
            raise AuditValidationError(f"{role} 必须填写真实姓名")
        names.append(unicodedata.normalize("NFKC", name).casefold().replace(" ", ""))
        for flag in ("independent", "not_involved_in_extraction_rules"):
            if person.get(flag) is not True:
                raise AuditValidationError(f"{role} 尚未确认 {flag}")
        expected_human = source_type == "human"
        if person.get("human_reading_confirmed") is not expected_human:
            raise AuditValidationError(f"{role} 人工读取声明与来源不匹配")
        try:
            completed = datetime.fromisoformat(clean(person.get("completed_at")))
        except ValueError as exc:
            raise AuditValidationError(f"{role} 缺少有效完成时间") from exc
        if completed.tzinfo is None:
            raise AuditValidationError(f"{role} 完成时间须带时区")
    if len(set(names)) != 3:
        raise AuditValidationError("两位读者与仲裁者必须为三位不同的具名人员")


def validate_source_path(path: Path, source_type: str) -> None:
    """试读/合成路径不得作为正式人工证据。"""
    if source_type == "human" and FORBIDDEN_SOURCE.search(str(path.resolve())):
        raise AuditValidationError(f"人工证据禁止使用试读/合成来源：{path.name}")
