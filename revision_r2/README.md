# R2 additions — completed human-audit aggregates

Same manuscript/repository: Limited temporal generalization of report-derived TEM
morphometrics for 11-class glomerular disease phenotyping.

This directory contains the incremental R2 additions to the existing repository.
It does not replace frozen v1.0.0 or DOI 10.5281/zenodo.21825234 and does not claim
a complete v1.1.0 release. The independent 200-report, seven-field dual-reader audit
and third-reader adjudication are complete. De-identified human-audit aggregates
are included in aggregate_results/audit_results.json; see AUDIT_AGGREGATES.md.
Individual answers and signed evidence are not included. Synthetic tests are
software checks, not human observations.

Included: current audit contract/scoring and synthetic tests; actual sampling,
template-counting and post-hoc re-extraction scripts; current Figure 1 and S1 with
project plotting dependencies and aggregate inputs; authoritative remote sensitivity
result, local cross-check, sanitized comparison/template/sample-commitment JSON.
All retained JSON values equal their sources exactly, without re-rounding.
SOURCE_PROVENANCE.json binds hashes and path/output adaptations. Scientific parser,
model, grid, seed and coding functions remain unchanged. The existing frozen parser
is referenced, not copied. The remote result is authoritative. RF/GB differ across
multiple metrics; their cause is not established. No clinical utility is claimed.

Remote runtime is recorded in the sensitivity JSON (Python 3.13.9, NumPy 2.4.2,
pandas 3.0.1, scikit-learn 1.8.0). Figure revision used matplotlib 3.11.0 and Arial.
Local synthetic-test success does not establish another full-analysis reproduction.

## Checks without clinical data

From this directory, using the existing dependencies plus pytest:

    python -B -m pytest -q -p no:cacheprovider scripts/test_audit_contract.py
    python -B scripts/compare_audit.py --help
    python -B scripts/rebuild_figure1_labels.py
    python -B scripts/build_figS1.py

Figures regenerate to generated_figures/, never over the frozen copies.
TEM_FIGURE_OUTPUT_DIR can select a different project output directory.

## Controlled execution and privacy

Clinical scripts require PATHOLOGY_V2_ROOT to name an authorized private data root.
The frozen dependency defaults to the parent repository; TEM_FROZEN_REPO overrides
that location when testing a staged candidate. Sampling requires TEM_AUDIT_OUTPUT_DIR;
template counting requires TEM_TEMPLATE_OUTPUT; re-extraction requires
TEM_REEXTRACTION_OUTPUT. Supply existing private output directories outside the
publication tree. For genuine audit scoring, TEM_AUDIT_SOURCE_ROOT must name the
authorized private source directory containing all reader/key evidence. The
published sample commitment remains fixed. No clinical full run is implied.
Re-extraction defaults to REEXTRACT_SKIP_KEY=1 (aggregate only); private-key update
requires explicit opt-in and TEM_AUDIT_OUTPUT_DIR. Do not regenerate or replace the
active frozen sample after readers have started.

No report, clinical workbook, patient row, individual answer, named-reader signature,
private invitation, portal runtime or local absolute path is included. Pseudonymous
clinical records are not universally anonymous. Underlying records remain subject
to the approved controlled-access route.

The internal audit_results.json retains named-reader provenance and paths and MUST
NOT be uploaded verbatim. The public file is an allowlisted aggregate projection;
all retained counts, percentages, confidence limits and agreement statistics equal
the verified private result without re-rounding. Participant identities, signatures,
workbook commitments, local paths and record-level sample identifiers are excluded.
Private evidence and its binding hashes remain controlled. Scientific code hashes
and the projection method are public. Website infrastructure is excluded.
This incremental package inherits the existing repository MIT license; the license
does not cover underlying clinical records.
