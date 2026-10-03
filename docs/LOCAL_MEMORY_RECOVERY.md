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

## Fit-boundary guard and completed local import

At 09:59:25 JST the original 11 outer folds and four tuning units were imported and
reloaded exactly in namespace 9439a04d... under real source commit 2f955778.... All
four terminal Optuna trials and durations were retained. Original namespace/campaign
hashes stayed unchanged; no model was fitted. Fresh full input authentication was
repeated. The recovery process peaked at 1.444 GiB working set / 2.171 GiB private
commit in 145.4 s. The following guard source change uses another genuine source
commit and a separately authenticated destination; it must reuse the original source
again rather than silently change this imported namespace or chain its lineage.

The model receives exactly the same prepared float32 matrices. Once they are built,
original numeric feature columns in each owned train/validation copy are released;
only output/evidence keys and target/date contracts remain. The retained development
arrays and model input matrices remain available. Default caller data is unchanged.

`--minimum-fit-headroom-gib 3.5` with scratch storage checks free physical RAM once
immediately before each native fit, after collecting/reaping unused owned mappings.
If insufficient, it records the actual value and raises before native fitting. It does
not poll PID/CPU or impose an OS/process memory limit. The check is opt-in, currently
Windows-only, and records its timestamp in a local `.fit-headroom.json` receipt.

The 3.5 GiB threshold uses the 40k/80k/160k same-parameter CPU allocation samples:
remove known synthetic fixture buffer growth, use the larger remaining per-row working
set slope, scale to 3,200,734 rows, add 0.1 GiB fixed allowance and double the result.
The resulting native estimate is about 2.1 GiB, leaving about 1.4 GiB at the actual
fit boundary. This is a conservative inference, not a proven native hard bound.
The 20k/300-iteration probe additionally checks the production iteration setting at
small scale. Native growth at full scale remains an unresolved practical limit.

At 10:01 JST available physical RAM was 6.085 GiB. Start only one owned worker,
using the unchanged original configuration, genuine source pin and explicit source
import plan; no four-task reenable. Report actual guard results and first checkpoint
state separately from newly completed learning. On guard failure, stop without retries.
