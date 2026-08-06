# Report-derived TEM morphometrics for 11-class glomerular disease phenotyping

Analysis code and de-identified aggregate source data for:

> Liu L., Zhang Q., Li J., Liu Z., Liu J., Li X., Wang H., Wang W., Wang H., and Wang J.
> *Limited temporal generalization of report-derived TEM morphometrics for 11-class
> glomerular disease phenotyping.* Submitted to **iScience**.

Locked registry: 10,933 canonical transmission electron microscopy (TEM) examinations
from 10,787 patients, 1 May 2014 – 30 April 2026 (actual dated observations 2014-05-08
to 2026-04-09). Patient-first main 11-class task: 8,208 patients, of whom 8,113 linked
to the legacy morphometry table and entered modelling (5,139 development through 2021;
2,974 temporal test from 2022).

---

## Privacy and ethics

**This repository contains no patient-level data.**

The original TEM pathology reports are clinical records and cannot be redistributed.
All row-level processing — linkage, parsing, training and evaluation — ran in memory on
the authorised controlled host, reached over read-only SSH; only aggregate JSON and CSV
summaries were ever written out. The published tables are counts, proportions, medians,
correlation coefficients and model metrics.

Specifically, this repository contains no names, no medical record or admission numbers,
no visit or patient keys, no dates of birth, no individual-level dates, no contact
details, and no referring-institution names. Referral sources appear only as anonymised
labels *Source A*–*Source D*. The privacy gate that enforced this is
`scripts/finalize_bundle.py`; its PASS records are in
`aggregate_results/reproducibility_bundle_self_test.json` and
`aggregate_results/v2_modeling_validation.json`.

The study was approved by the Clinical Medical Ethics Committee, Xiangya Hospital,
Central South University (Approval No. 2024030202), with waiver of individual informed
consent for retrospective anonymised analysis.

Requests for controlled access to the underlying records should be directed to the lead
contact and remain subject to ethics, institutional data-governance and legal approval.

---

## Layout

| Path | Contents |
|---|---|
| `scripts/remote_v2_modeling.py` | Deterministic extraction, record linkage, model fitting and evaluation. Runs on the controlled host; emits aggregate JSON only. |
| `scripts/build_v2_descriptive_figures.py` | Figures 1, 2 and 4 from aggregate results. |
| `scripts/build_v2_model_figure.py` | Figure 3 from aggregate results. |
| `scripts/finalize_bundle.py` | Privacy scan, manifest and self-test. |
| `scripts/remote_model_aggregate_tail.py` | Aggregation helper. |
| `source_data/` | Per-panel source tables for every figure, plus the two aggregate JSON files behind them. |
| `aggregate_results/` | Full model results, per-algorithm temporal metrics, ablations, direct-binary and referral-source holdout tables, and validation records. |
| `figures/` | Publication figures as submitted (600 dpi, Arial 8 pt, 160 mm column width). |
| `EXTRACTION_RULES.md` | English reference for the Chinese-language extraction rules. |
| `METHODS.md` | Condensed methods for the frozen re-analysis. |
| `data_dictionary.csv` | Variable definitions. |

The extraction regular expressions match Chinese clinical phrases because the source
reports are Chinese. `EXTRACTION_RULES.md` gives each pattern, its English meaning, and
the value it produces, including the negation guards that force ambiguous wordings to
*missing* rather than to a guessed value.

## Reproducing the reported figures and tables

```bash
python -m pip install -r requirements.txt
python scripts/build_v2_model_figure.py
python scripts/build_v2_descriptive_figures.py
```

Both scripts read only from `aggregate_results/` and `source_data/`, so they run
anywhere without access to the controlled host. `scripts/remote_v2_modeling.py` is
included for inspection and audit; it requires the controlled host and cannot be run
against public data.

Random seed 20260722 is fixed throughout. Software versions are pinned in
`requirements.txt`; the analysis environment used Python 3.13, NumPy 2.2.5,
pandas 3.0.1, scikit-learn 1.8.0, SciPy 1.17.1, matplotlib 3.10.8 and seaborn 0.13.2.

## Key reported results

| Quantity | Value |
|---|---|
| Highest temporal-test macro-F1 (gradient boosting) | 0.353 (95% CI 0.336–0.369) |
| Prespecified primary model (random forest) macro-F1 | 0.319 (95% CI 0.302–0.336) |
| Random-forest macro-AUC (one-vs-rest) | 0.834 (95% CI 0.821–0.847) |
| Feature-set ablation (random forest) | all nine inputs 0.319; without age 0.267; age + sex only 0.162; seven TEM fields only 0.261; missingness indicators only 0.067 |
| Direct binary random forests, six headline classes | ROC-AUC 0.826–0.947; average precision 0.117–0.737 |
| Referral-source holdouts | macro-F1 0.283–0.391; mean one-vs-rest AUC 0.785–0.861 |
| Exact-filename-link sensitivity subset | n = 6,609 (4,080 development, 2,529 temporal test); macro-F1 0.311 |

## Record linkage

Registry records were linked to the legacy morphometry table by unique normalised report
filename stem, then by deterministic fallback keys. Of 10,794 linked registry rows:

| Key | n | % |
|---|---|---|
| Exact filename stem | 8,892 | 82.4 |
| Old code + sex + birth year ±1 | 1,059 | 9.8 |
| Unique old code | 835 | 7.7 |
| Old code + date | 8 | 0.1 |

612 duplicate legacy rows were resolved deterministically. The exact-stem-only
sensitivity analysis in the table above quantifies how much the reported result depends
on the fallback keys.

## Licence

Released under the MIT Licence (see `LICENSE`). The licence covers the code and the
aggregate tables in this repository only; it does not extend to the underlying clinical
records, which are not distributed here.
