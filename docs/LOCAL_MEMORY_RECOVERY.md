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

## Actual single-worker resume, 10:40 JST confirmation

One independent worker was launched at 10:29 JST, with 6.015 GiB physical RAM free
against the 5.5 GiB preparation requirement. The four legacy tasks remained Disabled.
The genuine model/worker source pin is a68e8327914e265e6594e22e02f24bdbbfee39a5,
and the namespace is c7f55e2118c85e5711f00fba3ff2ed542584cf30b6ccc19b1a15cfc3ed6c89f2.
Original 15 units were imported from the original source, with no chained import.

Inputs authenticated at 10:31:56 JST. The new ranking fold6 unit became RUNNING at
10:32:32 JST. At 10:33:55 JST the actual fit-boundary free RAM was 3.668 GiB, passing
the 3.5 GiB condition. At 10:40:52 JST the matching actual worker PID11120 was alive,
with the ranking6 checkpoint still RUNNING. Working set was 3.838 GiB, peak working
set observed so far 5.641 GiB, private commit 3.646 GiB; system available RAM 2.753 GiB.
This is a single confirmation, not continuous PID/CPU monitoring, and not proof of
the full-run maximum. The initial worker-state file describes the last synchronous
entry phase; actual in-progress status is in checkpoint/fit receipts and the separate
active-resume-confirmation.json evidence.

The actual largest training-date group is 3,822 rows, below the synthetic 5,000-row
group used in memory probes. Exact original config/data/features/seed/precision and
CPU1/300 iterations were preserved. Original namespace/campaign hashes are unchanged;
new completed model folds remain zero, original h5 campaign remains 7/9. Seed43 and
h20 Final Candidate were not started. No additional app closure or OS setting change.

Existing saved ranking completion gaps increased from about 5.8 to 8.8 h over folds
2-5. Fold6 has about 7.6% more training rows than fold5; roughly 9-12 h is a conditional
estimate for ranking6 only. These gaps include preparation/I/O and possible interruptions.
The remaining large-loss/quantile/diagnostic work and seed43/h20 lack an adequate
end-to-end bound. Do not present this as the total completion time. Implementation
of this recovery milestone is complete; remaining model execution is computation,
with later campaign integration/Champion/holdout still separate.

The final documentation checkpoint can be newer than the frozen model pin: all src,
worker script and dependency files were verified unchanged from the genuine a68e832
model commit. The report/checkpoint provenance remains that exact source pin.


## 2026-10-03 19:10 JST: one explicitly authorized quantile continuation remains blocked

- ranking fold6 was saved at 15:59 JST. All 16 successful units were authenticated, including its 224,458 rows; each saved manifest/Parquet byte hash is unchanged after the continuation. The same `c7f55e2...` namespace was resumed: code/data/config were unchanged, so no new identity or chained import was fabricated. ranking6 remains attempt 1 and was reused without a new fit.
- The old worker exited after the 16:00 quantile1 pre-fit guard: 3.423523 GiB available versus the unchanged 3.5 GiB requirement. Previous progress, failure registry, logs, array receipt and ranking6 bundle were archived before the explicitly permitted single continuation.
- At 19:03 JST, actual stock workers were 0, all four legacy tasks Disabled, preparation RAM 6.033401 GiB (required 5.5), and the same genuine `a68e8327914e265e6594e22e02f24bdbbfee39a5` model/worker source and exact config were verified. One hidden worker was launched; full input authentication completed at 19:06.
- At 19:08:07 JST, quantile1 attempt 2 again failed BEFORE FIT: available 3.416367 GiB, shortfall 0.083633 GiB / 85.64 MiB. No native fit started. At 19:10:44 JST, worker count was 0; exit-time free RAM 6.199165 GiB is not fit-time headroom. No further retry was performed or scheduled.
- Previous ranking input matrices/preprocessor are explicitly deleted, and the fit guard runs gc/reap. The exit receipt has no ranking6-sized mapping. A fresh process that skips all ranking fits reproduced the shortfall, so old ranking native allocations alone cannot explain it. Current preparation, loaded OOF/model inputs and contemporaneous OS RAM are not separately measured at the guard.
- The observed preparation reduction was 2.617035 GiB. Under identical conditions, 6.117035 GiB preparation availability would only mathematically reach the 3.5 GiB boundary; this is not a safe retry threshold or a capacity guarantee. No threshold, dtype/precision, feature, seed, split/evaluation, CPU1 or 300-iteration change was made. No app exit, OS setting, authentication, billing, holdout opening or real order occurred.
- Verification: 16 saved fold bundles authenticated; all 16 byte hashes preserved; original checkpoint unchanged; prior failed registry is an unchanged prefix of the current registry. No code edit or new benchmark/test fit. Evidence: `docs/evidence/memory-recovery-20261003/quantile-once/` and the local one-attempt archive. Continuation is BLOCKED; full-run peak RAM and remaining runtime are unconfirmed.


## 2026-10-04 16:32 JST: final bounded continuation safely stopped; no native quantile fit

The 8d82fa6 OOF-buffer continuation started once at 16:27:56 JST, with preparation RAM 5.912430 GiB, stock workers0 and all four legacy tasks Disabled. All16 units were imported directly from native original15 plus a68 ranking6 into c424b0f8; each authenticated reload matched, and no chained import or source-pin rewrite was used. Full data authentication completed at 16:30:32. quantile1 reached the guard at 16:32:06: actual available 3.373367 GiB before and 3.433807 GiB after one unused-pool release, below the unchanged 3.5 GiB requirement by 67.78 MiB. Live Arrow bytes stayed 191165696. The worker recorded BLOCKED_BEFORE_FIT at 16:32:12 and had exited at the 16:32:20 observation. Native fits0, succeeded16, failed1, running0. Exit-time free RAM 6.140 GiB is not fit-time capacity.

The final one-time process snapshot confirms workers0 and legacy tasks Disabled. After exit, every old saved fold's manifest/Parquet byte hash is unchanged; all16 new saved folds were reauthenticated and their row counts/logical hashes match the original receipt. ranking6 remains the original 224458-row native a68 result. Original source namespace manifest/progress hashes are unchanged. All prior failure registry bytes are an unchanged prefix; five entries are retained. Model/worker/lock/config source remains exactly the genuine 8d82fa6 pin. Data,41 features,dtype,seed29,CPU1,300 iterations,split/evaluation,holdout and guard3.5 are unchanged. The 97 relevant tests,Ruff and strict mypy passed before launch.

The present authorization ends at this safe stop: no further fix/restart loop, automatic restart or learner schedule was created. The observed fit-time headroom increased relative to the preceding attempt, but differing OS availability means this is not a controlled causal RAM benchmark or a native peak guarantee. Quantile remains incomplete and no new native fit started today. Overall remaining calculation time, full-run peak memory and seed43/20-day completion time remain unconfirmed; do not invent completion percentages or days. Evidence: docs/evidence/memory-recovery-20261004/oof-buffer/final/ and the local runtime audit.


## 2026-10-04 18:26 JST: authorized normal Edge close; first native quantile fold completed

The user explicitly approved normal Edge closure and one stock continuation. UI Automation confirmed readonly email fields, empty editable password fields and no existing dialog; no input value was recorded. A normal window-close request at 18:16:54 closed all visible Edge windows without confirmation acceptance or force kill. Six background processes remained and were not killed. Actual available physical RAM rose from5.848602 to7.284618 GiB at the18:16:58 observation; this contemporaneous change is not an isolated causal memory benchmark. No other app,OS setting,history or data was changed.

All16 original results were reauthenticated before launch, each old byte hash unchanged, with source namespace manifest/progress unchanged. Resume the exact existing c424b0f8 checkpoint and genuine 8d82fa6 model pin, preserving the previous failed quantile1 attempt. No new namespace/import or scientific source change was needed. The preparation-only launch gate is7.0 GiB, a practical extra margin based on the preceding observed2.478622 GiB preparation-to-guard reduction; it is not a validated capacity requirement. The native fit guard remains3.5 GiB. Stock workers0 and all four old tasks Disabled were confirmed before one launch at18:20:40, with7.463245 GiB available. CPU1,300 iterations,41 features,data,dtype,seed29,split/evaluation and holdout remain unchanged. No recurring task was enabled or automatic restart created.

Full input authentication completed18:23:08. The first actual fit guard at18:24:35 passed with5.005829 GiB available, after the one permitted pressure-triggered unused Arrow release (before3.498837 GiB,live Arrow bytes unchanged191165696). Quantile fold1 completed and persisted at18:26:23: training2074895 rows,validation/OOF202496 rows,attempt2,SUCCEEDED,no import lineage. Its Parquet SHA256 ad9bcca5104742560e170c34a2ded062259ecaddff56c9a9e309b776366dbee8 matches the native manifest; logical frame hash6bc00d61927a736f80654fca108e34751ea2c002663c1750829a6eb43b0fca72. This proves a newly completed native fit; total saved units16 to17. The once-only2-second CPU sample at18:26:38 was after first-fold completion and showed the continued worker alive,CatBoost native module loaded,2.25 CPU seconds,WS3.586449 GiB,peak WS5.273209 GiB,private commit2.193943 GiB,system available4.125542 GiB. Commit is not physical RAM. Do not infer live fit solely from stale worker phase/training_started fields.

This is an active-run milestone, not full completion. Subsequent fold guards and checkpoint completion/safe stop remain to be observed at low frequency. No restart loop is authorized. The full native peak and overall quantile/large-loss/diagnostic/seed43/20-day ETA remain unconfirmed. The97 relevant tests,Ruff and strict mypy passed for the unchanged scientific source before the prior attempt; no new model benchmark or code change was performed here. Evidence: docs/evidence/memory-recovery-20261004/edge-resume/ and the local runtime audit.


## 2026-10-04 18:44 JST: all six native quantile folds saved

The same authorized single worker38000 completed quantile folds1-6; the last saved update is 2026-10-04T18:44:39.847454+09:00. Native quantile OOF totals 1,327,530.0 rows. Each of the six Parquet byte hashes matches its native manifest; no import lineage is present, and seed29/config/41-feature identities match. Total succeeded units22,failed0. The existing plan automatically proceeded into large_loss fold1; no new model configuration, extra worker or observer was created. All six quantile fit guards passed the unchanged3.5 GiB threshold; the sixth guard had4.505730 GiB available. The same genuine8d82fa6 model/worker/lock source remains unchanged. This is quantile phase completion, not full seed/campaign completion. Large-loss and fixed diagnostics/report verification remain. Continue the existing low-frequency observer until current execution completion/safe stop, with no automatic retry or additional task enablement. Evidence: docs/evidence/memory-recovery-20261004/edge-resume/quantile-phase/.
