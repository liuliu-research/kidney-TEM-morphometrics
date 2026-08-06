# Deterministic extraction rules for the seven TEM report fields

This document is an English reference for the rule-based extraction implemented in
`scripts/remote_v2_modeling.py`. The source reports are written in Chinese, so the
regular expressions match Chinese clinical phrases; the tables below give the literal
pattern, its English meaning, and the value it produces.

Two conventions apply throughout:

* **No guessing.** Where a report is ambiguous, hedged, or uses a qualifier that the
  rule does not explicitly recognise, the field is returned as *missing* rather than
  imputed. Missingness is therefore a property of the report text, not of the parser's
  confidence.
* **Text is normalised first** (`normalize_text`): Unicode NFKC folding (which unifies
  full-width and half-width characters), case folding, and removal of all whitespace.

Raw source columns consumed by the parser (`RAW_MORPH_COLUMNS`):
`肾小球总数`, `肾小球硬化`, `系膜细胞数/区`, `系膜基质增生程度`, `基底膜厚度`,
`钉突有无`, `足突融合程度`.

---

## 1. Glomerulus count — `glomerulus_count`

`parse_glomerulus_count` takes the numeric midpoint of the field and accepts the result
only if it lies in **[0, 100]**; otherwise the field is missing.

Midpoint rule (`numeric_midpoint`): all numbers in the string are extracted; if two or
more are present, the mean of the **first two** is used (so a written range such as
"3–5" yields 4); if one is present, it is used directly.

## 2. Sclerosis rate — `sclerosis_pct`

Numerator = explicitly counted globally sclerotic glomeruli **plus** explicitly counted
segmentally sclerotic glomeruli. Denominator = the parsed glomerulus count.

| Pattern | English meaning | Contribution |
|---|---|---|
| `(?<!趋于)(?<!接近)(?<!缺血性)球性(?:硬化)?\s*(\d+)\s*个` | "*N* globally sclerotic (glomeruli)", **not** preceded by "tending toward", "approaching", or "ischaemic" | adds *N* |
| `节段性(?:硬化)?\s*(\d+)\s*个` | "*N* segmentally sclerotic (glomeruli)" | adds *N* |

The three negative lookbehinds are the negation guards: a report saying *tending toward
global sclerosis* or *ischaemic global sclerosis* does **not** contribute a count. If
neither explicit count is present the field is missing, and a computed rate outside
[0, 1] is discarded.

## 3. Mesangial cell count — `mesangial_cells`

Numeric midpoint of the reported per-region range (source column `系膜细胞数/区`,
"mesangial cells per region"), so a reported range such as "1–2" yields 1.5.

## 4. Mesangial matrix grade — `mesangial_matrix` (ordinal 0–3)

The parser first truncates the text to the part **after** the token `基质` ("matrix")
when that token is present. This prevents a description of *cell* proliferation from
being read as *matrix* proliferation.

| Pattern | English meaning | Value |
|---|---|---|
| `无(?:明显)?增生` / `未见(?:明显)?增生` / `不增生` | no (obvious) proliferation / none seen | 0 |
| `轻度增生` | mild proliferation | 1 |
| `轻[-~—至]?中度增生` | mild-to-moderate | 1.5 |
| `中度增生` | moderate | 2 |
| `中[-~—至]?重度增生` | moderate-to-severe | 2.5 |
| `重度增生` | severe | 3 |
| anything else | — | missing |

Compound grades are tested **before** their single-grade substrings, so
"mild-to-moderate" is not captured as "moderate".

## 5. GBM thickness — `gbm_thickness_nm`

A unit is **required**: the string must contain one of `nm`, `μm`, `um`, `微米`
(micrometre) or `纳米` (nanometre). Values written in micrometres are multiplied by
1000. The midpoint rule above applies to ranges. The result is accepted only if it
lies in **[50, 5000] nm**; otherwise the field is missing.

## 6. Spike presence — `spike_present` (binary)

| Pattern | English meaning | Value |
|---|---|---|
| `无钉突` / `未见钉突` / `钉突(?:未\|不)形成` | no spikes / none seen / spikes not formed | 0 |
| `形成不明显` / `疑似` / `可能` | formation not obvious / suspected / possible | **missing** |
| contains `形成` or `钉突` (after the above) | spikes formed | 1 |
| empty, `-`, `--`, `/` | — | missing |

The hedged wordings are deliberately mapped to *missing* rather than to 0 or 1.

## 7. Foot-process grade — `foot_process_grade` (ordinal 0–3)

| Pattern | English meaning | Value |
|---|---|---|
| `无融合` / `未见(?:明显)?融合` / `足突(?:未\|不)融合` | no effacement / none (obvious) seen | 0 |
| `节段性?融合` / `部分性?融合` / `少数融合` / `小节段` | segmental / partial / few / small-segment effacement | 1 |
| `较广泛` / `大部分融合` | fairly extensive / mostly effaced | 2 |
| `广泛性?融合` | extensive/diffuse effacement | 3 |
| anything else | — | missing |

Where a report contains both `广泛` and a moderating qualifier (`较广泛`, `大部分`),
the moderated value 2 is returned rather than 3.

## 8. Demographics

* **Sex** (`sex_binary`): `男` / `男性` / `m` / `male` / `1` → male;
  `女` / `女性` / `f` / `female` / `0` → female; anything else missing.
* **Age**: numeric value, tolerating a trailing `岁` ("years").

---

## Derived model inputs

The nine modelling inputs are age, sex, and the seven fields above. Two derived feature
sets are also defined in the script: `FULL_MINUS_AGE` (sex plus the seven TEM fields)
and `MISSINGNESS` (binary indicators `missing__<column>` for each of the nine inputs),
which supports the missingness-only ablation reported in the paper.

## What these rules do **not** establish

The rules are deterministic and auditable, but they have **not** been validated against
a blinded manual re-abstraction of the source reports. No field-level error matrix or
inter-rater agreement estimate is available. The quantitative statements that *can* be
made about extraction and linkage quality — the composition of the record-linkage keys
and the sensitivity of the reported results to linkage ambiguity — are given in the
manuscript and in `aggregate_results/`.
