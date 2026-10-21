# Daily forward cross-fitting

## Independent prediction population (D216)

`crossfit_population_panel` is the separate development API for recovered full-fold
predictions. The original CLI and `daily-forward-crossfit-v1` identities remain
unchanged. The caller authenticates an independent eligible population, its
predictable subset and each `PopulationComponent` source. Every component must
cover exactly the ordered predictable keys: symbol, trading date, decision time,
horizon, original fold and data snapshot. Missing features remain explicit
eligible-population abstentions. Missing future labels never remove predictions
from the within-date ranking population.

The full original OOF date grid supplies the same three forward splits, purge,
embargo and minimum 20 fitting/calibration dates. Do not apply cross-fitting again
to just the saved later-half evaluation dates. Fit, calibration and scoring masks
use mature evaluable labels separately; top 10/20 are selected before the scoring
mask, and a missing selected label makes that top-return diagnostic incomplete.
Execution and valuation eligibility are not inferred from these masks.

The receipt pins component order and sources, population/key hashes, all split
boundaries, recipes, weights, calibration and units. Composition uses Python
float sequential summation in component order, matching the mobile research
schema. Optional risk components may be absent. A receipt declares the compared
and expected component IDs and any missing candidates; it never certifies the
complete 18-configuration matrix by itself or grants adoption. The authenticated
real-data runner must establish that matrix separately.

`research crossfit-daily-ensemble` authenticates the frozen dataset, feature selection and all 18 original 5d/20d candidates. It writes new, immutable development diagnostics; it does not finalize a selection, open the holdout, adopt a model or change original predictions.

```text
stock-ai research crossfit-daily-ensemble \
  --feature-selection <frozen-feature-selection.json> \
  --candidate-campaign <completed-candidate-campaign.json> \
  --candidate-campaign <other-completed-candidate-campaign.json> \
  --dataset <frozen-dataset.parquet> \
  --output-root artifacts/daily-ensemble
```

## Fixed policy: daily-forward-crossfit-v1

Use three consecutive evaluation blocks beginning at one half, two thirds and five sixths of the original OOF dates. Integer boundaries round down. The final boundary is the end of development OOF. The preceding one fifth of all OOF dates is each block's calibration window. The earlier prefix is the weight-fitting window. These choices are fixed before the real run; they are not optimized using the resulting scores.

At both boundaries exclude at least the horizon's number of observed OOF dates, labels whose endpoints reach the next window, and outcomes not received strictly before its first decision timestamp. Require at least 20 eligible dates in each fitting and calibration window. Date-based embargo is conservative across missing OOF dates, but does not prove market-calendar completeness. Fit, calibration and evaluation do not overlap within a block. Earlier evaluation outcomes may enter a later fit only after they mature. Every scored row appears exactly once; the first half is burn-in. All individual and ensemble comparisons use that identical later-half cohort.

The source dataset's complete logical identity is authenticated, including protected rows, without scoring holdout outcomes. Only exact development OOF keys are projected into the evaluator. Require exact symbol/date/as_of/target/label-end/original-fold alignment across every candidate and all four tasks, including ranking. Require aware times, one increasing cutoff per feature date, available features, and label receipts no earlier than the endpoint's local midnight or later than the snapshot cutoff. The midnight check is only a lower bound; this historical source does not provide authenticated intraday endpoint receipt evidence. Preserve the SINGLE_VINTAGE_AS_REVISED limitation.

## Models and units

- Returns: learn nonnegative, sum-one weights over all nine raw-return forecasts using row-equal MSE.
- Ranking: independently transform nine regression and nine ranking outputs to within-date average percentile ranks, `(rank_pct - 0.5) * 2`, then learn simplex weights against within-date outcome ranks. Training outcome ranks use only received fitting rows, so an unavailable peer's outcome cannot affect a received row's rank target. Prediction ranks use the available same-day cross-section. This rank transform is not exactly zero-mean for finite cross-sections.
- Large loss: learn simplex weights over the nine original probabilities using Brier loss. Use the exact original `target <= threshold` event, including equality.
- Quantile: retain the fixed mean of all nine original forecasts. Quantile weights are not learned in this version.

The quadratic objectives accumulate exact Gram statistics over all fitting rows in bounded blocks. A common training-target centering/scaling preserves MSE on the simplex. SLSQP uses maximum 500 iterations and tolerance 1e-12. Require success, feasibility and normalized convex dual gap at most 2e-6. Save weights, residual MSE, center, scale, iterations and gap. No thinning, random splitting, tuning budget or new base-model fitting is introduced.

On the separate calibration window, fit a nonnegative-slope least-squares map from ensemble rank to fractional return, monotone isotonic probability calibration with constant endpoint extrapolation, and the empirical linear-interpolated alpha quantile of residuals as an additive offset to the uniform quantile. Save mapping coefficients, isotonic knots, event counts and quantile offset. A single-class isotonic fit is an explicitly identified constant.

Rank-to-return calibration residual RMSE and absolute residual quantiles at 80%/90% are in fractional-return units. They are residual scales, not standard errors, conditional interval guarantees or conformal guarantees. Later evaluation measures their coverage. An additional diagnostic compares candidate-return disagreement with absolute return error. These diagnostics do not automatically add a penalty to the portfolio engine.

## Output and interpretation

Each horizon saves all original candidate predictions on the scored rows, keys, receipt times, original and meta fold, and the new forecasts in a byte-addressed Parquet. The receipt preserves all input hashes, source hashes, dependency versions, row/key digests, split boundaries, exclusion counts, fitting/calibration parameters and pooled/per-block metrics. CLI attempts have separate STARTED and SUCCEEDED/FAILED records.

Use `daily-development-metrics-v1`. Ranking reports explicitly identify score units and omit the meaningless MSE between a rank score and a raw return. Return reports keep MSE; Brier/log loss/ECE and pinball/strict/inclusive coverage retain their established definitions. Component Pearson correlations are pooled diagnostics of the original output values; constant pairs are null. One quantile cannot establish noncrossing. Probability calibration can worsen later scores; no improvement is presumed.

These are development prediction comparisons. Stateful NAV, other rules/Elastic Net, transaction/tax assumptions, final selection and single-use holdout evaluation, latest inference and the connection to personal inputs remain separate work. Do not compare these later-half scores to previously published full-OOF averages as if they used the same cohort.
