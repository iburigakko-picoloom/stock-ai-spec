# Daily development OOF adapter

`research daily-oof` authenticates one explicitly named family/seed at each of the 5d and 20d horizons. It produces a historical, research-only day receipt. It neither selects the best model nor generates a current forecast. Original candidate reports and the legacy 1d/5d/20d adapter remain unchanged.

## Source and time contract

The frozen feature selection, campaign, report, OOF content and Production Dataset identities must agree. Dataset authentication recomputes the complete logical content hash, one column at a time, including protected rows. This hash-only authentication is distinct from evaluating holdout outcomes. The subsequent analytical query returns only development OOF keys and their prediction/label-availability timestamps, with both feature and label-end dates before the frozen holdout boundary. Dataset bytes are checked again after projection. Rehashing modified metadata cannot conceal a change to the frozen dataset identity.

Close-feature dates must precede their decision date. All tasks and both horizons must share the exact aware decision timestamp. Requesting a day inside the holdout fails. No nearest-date substitution, horizon substitution or averaging of candidate identities is performed.

The 20d risk scale is expanding residual RMSE, using only outcomes whose declared receipt time is strictly earlier than the decision and whose label endpoint is before the decision's local date. Equality at the receipt cutoff is excluded. The default minimum is 20 distinct eligible feature dates; this is a configurable research cold-start guard, not evidence that the risk estimate is statistically sufficient. The model identity binds this parameter and both report IDs. This pooled scale is not a standard error of the mean, a calibrated confidence interval, or ensemble disagreement; the legacy `standard_error` field carries an explicit warning, and disagreement is zero for this single-candidate adapter.

Prediction v2 retains 5d and 20d, sets 1d to null, and uses 20d downside quantile and large-loss probability. The receipt retains the source threshold and quantile alpha. Missing horizons and insufficient history become named blocks. An explicitly requested holding without any forecast also becomes a block.

## Decision integration

`propose_daily_oof` requires an exact shared timestamp for the forecasts, portfolio and known market snapshot, a 0/0/1 horizon policy, security/price evidence, and a non-earlier proposal timestamp. It compares explicit new candidates plus every holding across account buckets. A holding without a usable forecast stops the whole comparison. It never drops that position or fabricates a zero-return forecast.

Known market marks update a validated copy of the portfolio; the input state and cost basis remain intact. The existing engine applies its configured cost/tax and discrete-lot policy. The result is a research proposal, not a fill, not a personal recommendation and not an update to the manual execution ledger. Continuous strategy-to-NAV execution, authenticated historical market/actions, personal settings and final adoption remain separate work.

## Invocation

```powershell
.venv/Scripts/python.exe -m stock_ai research daily-oof --feature-selection <frozen-json> --candidate-campaign <h5-manifest> --candidate-campaign <h20-manifest> --dataset <content-addressed-parquet> --family lightgbm --seed 17 --as-of 2025-11-06T11:30:00+09:00 --output-root <receipt-directory>
```

The family/seed above is a wiring example, not a selected winner. Receipts are immutable and bind the adapter source bytes. Test coverage includes authenticated fixture bundles, altered protected-column detection despite rewritten file/metadata hashes, exact receipt cutoffs, future-outcome mutation invariance, Arrow microsecond timestamps, cold start, missing holdings and actual engine comparison with opposing 5d/20d forecasts.
