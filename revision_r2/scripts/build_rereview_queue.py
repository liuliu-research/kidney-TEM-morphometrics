# -*- coding: utf-8 -*-
"""事后文本一致性检查：找出人工参考编码与报告原文明显矛盾的格子，生成仲裁人复裁队列。

规则（只看人工答案与原文，不看机器值）：
  A 任一字段：最终参考为具体值，但原文完全未出现该字段关键词 → 标记。
  B 钉突字段：按原文判定状态（钉突形成=存在；未见钉突/钉突（-）=不存在；含"钉"但无明确表述=不明确；
    不含"钉"=未提及），与最终参考状态不一致 → 标记。
输出 portal/runtime/rereview_queue.json（不含报告原文，门户按样本号加载）及回执；只读其他文件。
"""
import hashlib
import json
import os
import re
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("TEM_AUDIT_SOURCE_ROOT", str(HERE))).resolve()
EXPORTS = ROOT / "portal" / "runtime" / "exports"
KEY = ROOT / "audit_key_CONFIDENTIAL.json"
OUT = ROOT / "portal" / "runtime" / "rereview_queue.json"
RECEIPT = ROOT / "rereview_queue_receipt.json"
FIELDS = ["glomerulus_count", "sclerosis_rate", "mesangial_cell_count", "mesangial_matrix_grade", "gbm_thickness_nm", "spike_presence", "foot_process_grade"]
KEYWORDS = {"glomerulus_count": ["肾小球"], "sclerosis_rate": ["硬化"], "mesangial_cell_count": ["系膜细胞"], "mesangial_matrix_grade": ["基质"], "gbm_thickness_nm": ["基底膜"], "spike_presence": ["钉"], "foot_process_grade": ["足突"]}
MISSING = {"未提及", "不明确"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_reader(name: str) -> dict:
    ws = openpyxl.load_workbook(EXPORTS / f"{name}.xlsx", read_only=True)["读取表"]
    rows = list(ws.iter_rows(values_only=True))
    out = {}
    for r in rows[1:]:
        if r and r[0]:
            out[r[0]] = dict(zip(FIELDS, [str(v) if v is not None else "" for v in r[1:8]]))
    return out


def read_adjudication() -> dict:
    ws = openpyxl.load_workbook(EXPORTS / "adjudicator.xlsx", read_only=True)["裁定表"]
    rows = list(ws.iter_rows(values_only=True))
    return {(r[0], r[1]): {"reader1": r[2], "reader2": r[3], "value": r[4], "total": r[5], "reason": r[6]} for r in rows[1:] if r and r[0]}


def spike_text_state(text: str) -> str:
    """按含"钉"的逗号级子句判定，再看顿号级片段：疑似/可疑/不明显→不明确；
    片段或其前方有未见/无/（-）/未形成且片段无"形成"→不存在；片段有形成/可见→存在；其余→不明确。"""
    t = text.replace(" ", "")
    hedge = re.compile(r"疑似|可疑|可能|不明显|欠明显")
    negate = re.compile(r"未见|无钉|（-）|\(-\)|未形成|不伴")
    states = []
    for clause in re.split(r"[，,；;。]", t):
        if "钉" not in clause:
            continue
        segments = clause.split("、")
        for i, seg in enumerate(segments):
            if "钉" not in seg:
                continue
            before = "、".join(segments[:i])
            if hedge.search(seg):
                states.append("unclear")
            elif negate.search(seg):
                states.append("absent")
            elif "形成" in seg or "可见" in seg:
                states.append("present")
            elif negate.search(before):
                states.append("absent")
            else:
                states.append("unclear")
    if not states:
        return "none"
    if "present" in states:
        return "present"
    if "absent" in states and "unclear" not in states:
        return "absent"
    return "unclear"


def coded_state(field: str, value: str) -> str:
    if value == "未提及":
        return "none"
    if value == "不明确":
        return "unclear"
    if field == "spike_presence":
        return {"形成": "present", "未见": "absent"}.get(value, "value")
    return "value"


def main() -> None:
    key = json.load(open(KEY, encoding="utf-8"))
    rows = {r["sample_id"]: r for r in key["rows"]}
    r1, r2 = read_reader("reader1"), read_reader("reader2")
    adj = read_adjudication()
    flagged = []
    for sid in sorted(rows):
        text = rows[sid]["excerpt"]
        for field in FIELDS:
            a, b = r1[sid][field], r2[sid][field]
            if (sid, field) in adj:
                final, origin, reason = str(adj[(sid, field)]["value"]), "adjudication", str(adj[(sid, field)]["reason"] or "")
            else:
                # 门户按编码值判分歧；原始字符串不同但编码等价的格子未进入裁定，最终参考与门户一致取读者1。
                final, origin, reason = a, "consensus", ""
            flags = []
            if final not in MISSING and not any(k in text for k in KEYWORDS[field]):
                flags.append(f"参考为具体值“{final}”，但原文未出现“{'/'.join(KEYWORDS[field])}”")
            if field == "spike_presence":
                ts, cs = spike_text_state(text), coded_state(field, final)
                if ts != cs and not (ts == "unclear" and cs in {"unclear", "none"}):
                    label = {"present": "原文明写钉突形成", "absent": "原文明写未见钉突/钉突（-）", "unclear": "原文提到钉突但无明确表述", "none": "原文未出现“钉”字"}[ts]
                    flags.append(f"{label}，而参考编码为“{final}”")
            if flags:
                flagged.append({"sample_id": sid, "field": field, "origin": origin, "reader1": a, "reader2": b, "current_value": final, "current_reason": reason, "flag_reason": "；".join(dict.fromkeys(flags))})
    queue = {
        "schema_version": 1,
        "kind": "post_hoc_text_consistency_rereview",
        "packet_sha256": json.load(open(ROOT / "portal" / "config" / "access.json", encoding="utf-8"))["packet_sha256"],
        "rules": ["A: 任一字段参考为具体值但原文无该字段关键词", "B: 钉突字段原文状态与参考编码状态不一致"],
        "inputs_sha256": {"reader1.xlsx": sha(EXPORTS / "reader1.xlsx"), "reader2.xlsx": sha(EXPORTS / "reader2.xlsx"), "adjudicator.xlsx": sha(EXPORTS / "adjudicator.xlsx"), "audit_key": sha(KEY)},
        "cells": flagged,
    }
    OUT.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    RECEIPT.write_text(json.dumps({"queue_sha256": sha(OUT), "n_cells": len(flagged), "by_field": {f: sum(c["field"] == f for c in flagged) for f in FIELDS}, "by_origin": {o: sum(c["origin"] == o for c in flagged) for o in ("adjudication", "consensus")}}, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in flagged:
        print(c["sample_id"], c["field"], c["origin"], "|", c["reader1"], "/", c["reader2"], "->", c["current_value"], "|", c["flag_reason"])
    print("TOTAL", len(flagged), "queue sha", sha(OUT)[:16])


if __name__ == "__main__":
    main()
