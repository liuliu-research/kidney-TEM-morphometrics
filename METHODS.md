# Frozen analysis specification

## Cohort and time boundary

- Source of truth: the locked second-extraction patient-visit registry with an
  April 2026 data freeze.
- Analysis window: May 2014–April 2026; actual dated observations run from
  8 May 2014 through 9 April 2026.
- Unit: one deterministically selected earliest canonical examination per
  patient. Ties on the earliest date are resolved by the internal visit key and
  then stable source order before identifiers are removed.
- Primary outcome set: IgAN, IgAVN, MCD, MN, MsPGN, LN, EPGN, DKD, TBMN,
  FSGS, and MPGN.
- Development period: May 2014–December 2021.
- Temporal test period: January 2022–April 2026.
- The same patient cannot appear in both periods.

## Deterministic linkage

The canonical registry is linked to the legacy report-feature table inside the
controlled server. Exact filename stems are preferred. Deterministic fallback
keys are used only when they resolve to a single registry record after stable
duplicate resolution. Direct identifiers, pseudonymous patient keys, visit
keys, and row-level values are removed before aggregate outputs leave the
server. An exact-stem-only sensitivity cohort is analysed separately.

## Predictors and preprocessing

The full model contains age, sex, glomerulus count, sclerosis rate, mesangial
cell count, mesangial matrix grade, GBM thickness, spike presence, and
foot-process grade. Median imputation and standardisation are fitted within
each training fold. Clinical-feature models do not receive missingness
indicators. A separate diagnostic baseline uses only nine missing/not-missing
flags.

## Models and evaluation

Six conventional classifiers are evaluated: multinomial logistic regression,
random forest, gradient boosting, radial-basis-function support-vector machine,
multilayer perceptron, and AdaBoost. Hyperparameters are selected by
three-fold stratified shuffled cross-validation in the development period with
macro-F1 as the selection score. The random seed is 20260722, and computation
uses one worker for deterministic ordering. The temporal test set is not used
for hyperparameter tuning.

Reported temporal metrics are accuracy, balanced accuracy, macro-F1, weighted
F1, and macro one-vs-rest AUC. Uncertainty is estimated with 300
class-stratified patient bootstrap replicates. Prespecified sensitivity analyses
include full features without age, age and sex only, seven report features
only, missingness only, exact-stem-only linkage, six direct binary random
forests, and four major referral-source holdouts. Referral-source holdouts are
not independent external validation because all reports were processed in one
ultrastructural pathology service.

## Capacity scenario

The secondary workload calculation uses aggregate canonical check counts and
fixed assumed capacity: two specialists, each processing 22 cases per month.
For each annual row, lambda is the count divided by the exposed calendar months
and rho is lambda divided by 44. Boundary years are marked partial; April 2026
contains observations only through 9 April and is not interpreted as a full
month or year. The calculation contains no patient-level turnaround times and
cannot demonstrate queues, understaffing, or intervention effects.

## Validation boundary

The locked label-rule development included adversarial review assistance, while
the frozen classifier itself is deterministic. The historical record does not
preserve a sufficiently precise tool/model version for that earlier assistance,
so no unsupported version is supplied. The report-feature parser has no
independent prespecified manual error matrix. Both limitations must remain
visible when interpreting the benchmark.
