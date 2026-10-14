# Actual forward ensemble evaluation — 2026-10-15

Source checkpoint `afa9a5fa4212ec7290d7e22f9e808d2fd0e808b9`; policy `daily-forward-crossfit-v1` and metric version `daily-development-metrics-v1`. All 18 original candidates and the complete frozen dataset identity were authenticated. No new base-model training, holdout scoring, model selection, adoption, personal portfolio modification or real order occurred.

The actual run succeeded. Its receipt is `artifacts\daily-ensemble\receipts\6495e0f60c41d57db025c00fe366dd21f2da24e0142402c99b5e7d4ee76f9c4d.json` (byte SHA256 `0e1047863dd57bfebd634291f966ad19173f8ad958d29d54bf4cb6089013eb14`). Full per-candidate, per-block and pooled metrics are in that local receipt; compact evidence is in [summary.json](summary.json).

A byte-identical [full receipt](6495e0f60c41d57db025c00fe366dd21f2da24e0142402c99b5e7d4ee76f9c4d.json) is retained here. [Code verification](test-verification.md): 24 added tests and all 650 tests pass; full coverage is 86.580618%. Ruff and mypy pass. No UI changes were needed.

## Common evaluation cohort

| Horizon | Rows | Dates | Evaluation range |
| --- | ---: | ---: | --- |
| 5d | 662,791 | 177 | 2025-04-23–2026-01-14 |
| 20d | 523,258 | 140 | 2025-04-11–2025-11-05 |

The earlier OOF half is burn-in, not included in these scores. All candidates, uniform means, learned variants and the additional existing simple baselines use these exact rows. Earlier full-OOF summaries have different cohorts and must not be directly compared to these figures.

## Results

| Metric / variant | 5d | 20d |
| --- | ---: | ---: |
| Return MSE: uniform | 0.003584581 | 0.018759990 |
| Return MSE: learned weights | 0.003584106 | 0.018743730 |
| Return MSE: calibrated rank | 0.003550247 | 0.019185402 |
| Return MSE: zero_return | 0.003576636 | 0.018931860 |
| Return MSE: momentum_20d | 0.020909742 | 0.036500153 |
| Return MSE: ridge_v0 | 0.003621642 | 0.018994157 |
| Mean daily Rank IC: uniform_rank | 0.068205240 | 0.099159097 |
| Mean daily Rank IC: weighted_rank | 0.085513889 | 0.106404454 |
| Brier: uniform_probability | 0.023965474 | 0.072873358 |
| Brier: weighted_probability | 0.024017685 | 0.072803876 |
| Brier: calibrated_probability | 0.025152375 | 0.077737791 |
| Log loss: uniform_probability | 0.105214752 | 0.263280992 |
| Log loss: weighted_probability | 0.105414009 | 0.263674220 |
| Log loss: calibrated_probability | 0.115278788 | 0.295698212 |
| ECE: uniform_probability | 0.014606100 | 0.047335739 |
| ECE: weighted_probability | 0.014955024 | 0.047236797 |
| ECE: calibrated_probability | 0.012828989 | 0.044896447 |
| Pinball: uniform_quantile | 0.007311650 | 0.014268948 |
| Lower-tail rate: uniform_quantile | 6.3651% | 6.4473% |
| Pinball: calibrated_quantile | 0.007743383 | 0.015830303 |
| Lower-tail rate: calibrated_quantile | 10.3106% | 13.2606% |

Learned rank weights improve pooled daily Rank IC over the uniform 18-component rank ensemble on both horizons. Raw-return weighting changes MSE only slightly; on 5d both uniform and learned raw-return predictions still have higher MSE than the zero-return forecast. The rank-to-return mapping improves 5d MSE but worsens 20d MSE versus the raw-return ensemble. Rank improvement is not evidence of better return magnitudes or economic performance.

Across the three chronological blocks, learned return weights improve MSE in 2/3 blocks on each horizon. Learned rank weights improve IC in 3/3 blocks on 5d and 2/3 on 20d. Isotonic improves Brier in 0/3 and 1/3 blocks respectively; quantile correction improves pinball in only 1/3 blocks on each horizon. Pooled improvement does not establish stability across all periods.

Isotonic calibration lowers pooled ECE but worsens Brier and log loss versus the uncalibrated learned probability on both horizons. Quantile correction worsens pooled pinball on both horizons: 5d lower-tail coverage moves close to 10%, while 20d moves to 13.26%. These mixed/negative results are retained; no calibration-success or adoption gate is passed.

Calibration residual absolute-radius coverage at 80%/90% is 81.85%/91.11% for 5d and 77.30%/88.69% for 20d. These are retrospective development diagnostics of marginal residual scales, not conditional coverage guarantees or standard errors.

## Chronology and numerical verification

| Horizon / fold | Weight fitting dates (count) | Calibration dates (count) | Evaluation dates (count) |
| --- | --- | --- | --- |
| 5d / 1 | 2024-07-31–2024-12-25 (101) | 2025-01-09–2025-04-14 (64) | 2025-04-23–2025-07-17 (59) |
| 5d / 2 | 2024-07-31–2025-03-28 (160) | 2025-04-08–2025-07-09 (64) | 2025-07-18–2025-10-15 (59) |
| 5d / 3 | 2024-07-31–2025-06-24 (219) | 2025-07-03–2025-10-06 (64) | 2025-10-16–2026-01-14 (59) |
| 20d / 1 | 2024-09-12–2024-12-13 (63) | 2025-01-21–2025-03-11 (34) | 2025-04-11–2025-06-19 (47) |
| 20d / 2 | 2024-09-12–2025-02-27 (110) | 2025-04-01–2025-05-21 (34) | 2025-06-20–2025-08-26 (46) |
| 20d / 3 | 2024-09-12–2025-05-08 (156) | 2025-06-09–2025-07-25 (34) | 2025-08-27–2025-11-05 (47) |

All 18 simplex fits converged with feasible nonnegative sum-one weights. Maximum normalized dual gap: `5.40124071691e-07` (required at most 2e-6). Endpoint and receipt-time inequalities were checked separately at both boundaries. Fitting target ranks exclude unreceived peers.

The old baseline files' exact keys, targets, as_of, endpoint and original fold match the new evaluation subset. Uniform-return/probability/quantile outputs agree within a maximum absolute difference of 2.23e-16. Byte hashes, raw-return/probability model replay and calibration interpolation pass. [verify_results.py](verify_results.py) reproduces those checks and evaluates old simple baselines on the new cohort. [verify_rank_replay.py](verify_rank_replay.py) and [replay.json](replay.json) additionally verify the persisted rank ensemble, return mapping, quantile offset and uncertainty fields.

## Limits and remaining work

These are research-only development comparisons on single-vintage data. Do not treat the differences as calibrated significance, realistic NAV, costs/taxes, personal suitability or latest forecasts. No bootstrap significance is claimed. Remaining rules/Elastic Net, stateful real-market/action/cost/tax validation, final selection, holdout access audit/evaluation, latest refit/inference and personal-input integration remain necessary. The complete approved plan is still active.
