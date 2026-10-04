# Completed human-audit aggregate projection

The frozen audit contains 200 reports: 100 development and 100 temporal-test
reports, each independently read for seven fields and then adjudicated by a third
reader. The private source passed the existing scoring contract. Participant
declarations are not independent real-world identity authentication.

`aggregate_results/audit_results.json` is an allowlisted projection of that verified
source. It contains sample/split counts, pre-adjudication agreement, adjudication
totals and missingness-status counts, the unchanged validation/tolerance definitions,
and both extraction pipelines' field aggregates. Each pipeline retains all three
strata (all, development, temporal_test), disagreement counts, percentages and Wilson
95% confidence limits. The production scorer supplies these values; projection does
not recompute, round or impute any value.

Both `disagreement_flags` and its legacy alias `linkage_flags` omit `sample_ids`.
Their retained counts describe multiple-field disagreement, not demonstrated linkage
errors. Names, signatures, individual answers, source paths, input/workbook hashes,
and the complete private provenance object are not distributed. Scientific scorer
and contract SHA-256 values are retained; the existing SOURCE_PROVENANCE.json records
the public code's path adaptations.

The combined 200-report error rates describe the balanced audit sample, not a
prevalence-weighted estimate for all 8,113 modeled patients. Missing or ambiguous
report text does not establish clinical absence. Agreement does not establish
diagnostic accuracy, external validation or clinical utility. Raw clinical records
and signed source evidence remain under controlled access.

The original DOI 10.5281/zenodo.21825234 archives v1.0.0 only and does not include
these new human-audit aggregates. This repository increment does not mint a new DOI
or modify frozen v1.0.0. The existing MIT license covers the code and aggregates,
not the underlying clinical reports or signed evidence.
