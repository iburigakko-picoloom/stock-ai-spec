# Local CPU memory recovery, 2026-10-03

This change preserves the fixed research data, feature order and precision, folds,
seeds, 300 iterations, CPU thread count 1, model parameters, evaluation and locked
holdout. It does not adopt a Champion or silently repin the seven completed batches.

`research advanced --memory-scratch-root <local-directory>` explicitly enables:

- Full original Parquet byte and logical-content authentication, one column at a
  time, before exposing the required model/input-contract columns. Excluded columns
  remain authenticated. Original snapshot IDs and bundle formats are unchanged.
- Owned, dtype-preserving numeric arrays backed by local files. Completed row-copy
  arrays are flushed to disk so clean pages can be reclaimed. Mapped pages still use
  physical RAM while resident; this is not zero-memory storage.
- A single development selection, source release only with explicit ownership and
  one horizon, no wide feature materialization for already authenticated folds, and
  release of tuning/fold/diagnostic arrays as soon as they are no longer needed.

The public API retains its caller's input by default. Zero-size and extension/object
columns retain their existing handling. Scratch allocations keep their original dtype,
shape, C layout, row order and ndarray interface. Cleanup releases only owned files
whose mappings are no longer live. A receipt identifies any mappings still retained
by surviving views/exception tracebacks; these are left open rather than forcibly
invalidating a view. Failed scratch files can remain after process exit and must be
identified from their receipt before cleanup. The destination has about 212 GiB free
(09:40 JST); allocation requires at least its size plus 2 GiB of disk headroom.

The explicit CPU checkpoint bridge additionally binds supporting source-file hashes
and validates installed runtime versions when a plan/lineage is read. A genuine new
Git commit and new namespace are required. The original namespace, completed OOF,
failed attempts and Optuna durations/budgets remain unchanged.

## Evidence and limits

- Full original Build/V0/V1/V2/Dataset authentication and feature/dataset alignment
  succeeded at 09:25:30 JST in 113.9 s. The authenticating process peaked at
  1.134 GiB working set and 1.922 GiB private commit. No fit/import occurred.
- Final independent comparisons against the original source: 66 passed. This includes
  exact values/dtypes/order/hashes and complete small LightGBM/CatBoost OOF, reports,
  parameters, split boundaries and metrics, with both pandas ownership modes.
- Changed-code integration/checkpoint/CLI tests: 76 passed; production PIT/build
  authentication tests: 2 passed (9 deselected). Ruff and strict mypy: 50 source files.
- Small synthetic ranking measurements use the saved depth/learning-rate/L2, seed29,
  CPU1 and 41 features. The 20,000-row case uses 300 iterations; 40,000/80,000/160,000-row
  allocation probes use 5 iterations only in synthetic fixtures. Production stays 300.
  The 160,000-row (about 5% of the largest fold) fixture peaked at 0.422 GiB
+  working set / 1.101 GiB private commit in 41.8 s. These are evidence of sample
+  allocations, not a proven full-fold memory bound.
- Original dataset rows 4,058,130; development 3,544,857; largest outer training
  3,200,734 and validation 225,731. Projected float64 input has 42 numeric columns
  (about 1.270 GiB). Largest float32 train+validation input is 0.523 GiB. Those sizes
  exclude native CatBoost, index/object columns, temporary operations and OOF analysis.
- Classic alone was normally closed using its supported quit argument at 09:07 JST.
  At 09:36 JST the machine had 5.572 GiB physical memory available. Other applications
  and OS/pagefile/security settings were not changed. Stock tasks remain disabled.

Actual maximum-fold CatBoost memory and complete remaining wall time have not been
measured. No large production OOM attempt is authorized. The source change and a
reviewed import plan do not themselves prove sufficient RAM or completed learning.
Start at most one worker only after the required memory margin is demonstrated;
confirm its actual checkpoint update and record any imported versus newly fitted units.
Do not enable all four stock tasks. No orders, external upload, paid instance or cloud
account changes were made.

Logs: `docs/evidence/memory-recovery-20261003/`. Earlier source/checkpoint identities
and thin split/OOF evidence remain documented in D088 and the local workspace.
