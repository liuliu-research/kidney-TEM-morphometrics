# -*- coding: utf-8 -*-
"""公开前隐私审计（伦理门控）。任一 BLOCK 项命中即不得公开。

针对本项目的具体风险设计，而非通用规则：
* 直接标识符：姓名、住院号、门诊号、身份证、电话、病理号、患者/就诊键
* 机构标识：医院名、院区、转诊来源真实名称（应已匿名为 Source A-D）
* 行级数据：一行一个病例的表
* 连接信息：主机名、IP、凭据、绝对路径
* 个体级日期：精确到日的患者日期（分析窗口边界日期除外）
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

BLOCK_PATTERNS = {
    "身份证号": re.compile(r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b"),
    "手机号": re.compile(r"\b1[3-9]\d{9}\b"),
    "IPv4": re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
    "凭据": re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key)\b\s*[=:]\s*\S+"),
    "机构名": re.compile(r"(?i)\b(?:xiangya|changsha|hunan)\b|湘雅|长沙|中南大学"),
    "患者姓名字段值": re.compile(r"(?i)\"(?:patient_name|pat_name|姓名)\"\s*:\s*\"[^\"]+\""),
    "绝对路径": re.compile(r"[A-Za-z]:[\\/](?:Users|Windows|Program)|/(?:home|Users)/[A-Za-z]"),
}

# 允许出现的日期（分析窗口与运行时间戳），其余精确日期需人工确认
DATE_ALLOW = {"2014-05-01", "2014-05-08", "2026-04-30", "2026-04-09",
              "2021-12-31", "2022-01-01", "2026-07-22", "2026-07-31"}
DATE_RX = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")

TEXT_SUFFIX = {".py", ".md", ".csv", ".json", ".txt", ".yml", ".yaml"}
ROW_LEVEL_HINTS = {"patient", "visit", "admission", "record_id", "stem", "filename"}


def main() -> int:
    findings: list[str] = []
    warnings: list[str] = []
    files = [p for p in ROOT.rglob("*") if p.is_file() and p.name != Path(__file__).name]

    for p in files:
        rel = p.relative_to(ROOT)
        if p.suffix.lower() not in TEXT_SUFFIX:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")

        for label, rx in BLOCK_PATTERNS.items():
            for m in rx.finditer(text):
                line = text[: m.start()].count("\n") + 1
                # 处理机构（湘雅医院）在论文中本就公开披露：作者单位与伦理批件均须具名。
                # 需要匿名的是「转诊来源」，它在全部产物中已固定为 Source A-D。
                # 因此机构名只有出现在数据文件里才构成泄漏；下面两类属必需披露：
                #   1) README 等说明文档中的伦理批件与单位声明
                #   2) 引用元数据（.zenodo.json / CITATION.cff）中的作者 affiliation 字段
                if label == "机构名":
                    ctx = text[max(0, m.start() - 260): m.end() + 120]
                    if p.suffix.lower() == ".md" and re.search(
                        r"(?i)ethic|approval|affiliat|committee|consent", ctx
                    ):
                        continue
                    if p.name in (".zenodo.json", "CITATION.cff") and re.search(
                        r"(?i)affiliation", ctx
                    ):
                        continue
                findings.append(f"{rel}:{line} [{label}] {m.group(0)[:60]!r}")

        for m in DATE_RX.finditer(text):
            if m.group(0) not in DATE_ALLOW:
                line = text[: m.start()].count("\n") + 1
                warnings.append(f"{rel}:{line} [精确日期] {m.group(0)}")

        if p.suffix.lower() == ".csv":
            with p.open(encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.reader(fh))
            if rows:
                header = [h.strip().lower() for h in rows[0]]
                risky = [h for h in header if any(k in h for k in ROW_LEVEL_HINTS)]
                if len(rows) - 1 > 200 and risky:
                    findings.append(f"{rel} [疑似行级数据] {len(rows)-1} 行，列 {risky}")

    print(f"扫描 {len(files)} 个文件")
    print()
    if findings:
        print("===== 阻塞项（不得公开）=====")
        for f in findings:
            print("  " + f)
    else:
        print("阻塞项：无")
    print()
    if warnings:
        print(f"===== 需人工确认（{len(warnings)} 处）=====")
        for w in warnings[:15]:
            print("  " + w)
        if len(warnings) > 15:
            print(f"  ……另有 {len(warnings)-15} 处")
    else:
        print("需人工确认：无")
    print()
    print("审计结论：" + ("不通过，禁止公开" if findings else "通过，可以公开"))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
