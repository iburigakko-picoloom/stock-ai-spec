# Manual portfolio import: release and live verification

Main implementation checkpoint: `c0f6a81`; CLI credential-redaction checkpoint:
`5be26b4`. Site source: `0073ca93f1cf2fcc8947f7d15fda86615bc56261`.
The private deployment succeeded at environment revision 1. See `release.json`.

The real owner profile was imported without editing its financial fields:
no holdings, zero accounts, null investment budget and null risk preference.
Exact original revision and export hashes were verified across TypeScript and
Python. Repeating the import returned the same local record and first receipt
timestamp. Other local ledger counts were unchanged; backup integrity passed.
See `live-receipt.json`. No service credential, scoped proof, owner ID, account
name or raw financial payload is included in these evidence files.

Anonymous, platform-token-only, scoped-proof-only and foreign-Origin requests
all returned HTTP 401. Browser verification showed `PC取込待ち` before import,
then `PC取込済み: 2026/10/15 6:57:15 JST` after reloading saved inputs. At a 390px
viewport override, document client/scroll widths both measured 375px, with no
horizontal overflow. The temporary viewport override was reset.

Verification completed:

- Initial related Python suite: 56 passed (manual input plus operational store).
- Final manual-input/CLI suite: 38 passed, including credential-redaction failure.
- Private Node schema/auth/export/migration suite: 12 passed.
- Whole-repository Ruff: passed. Mypy: passed, 61 source modules.
- Private ESLint, TypeScript no-emit and production build: passed.

Full regression was completed after explicit goal resumption: **688 passed**,
1259 warnings, 817.92 seconds, coverage **86.74%**. Source `5be26b417e383f918581bfba657e8bbd2e9b6f2f`.
Log `.demo-artifacts/tests-manual-portfolio-full-resume.log` and coverage
`.demo-artifacts/coverage-manual-portfolio-full-resume.json` are hashed in
`verification.json`. The previous handle was missing and a fresh authorized
process check confirmed zero Python processes before restarting; no duplicate
test worker was started.

The earlier run was interrupted at 19% after a runtime/tool refresh. A separate
process check at that time was not executed because usage limits prevented
automatic approval review. After goal resumption, the authorized read-only check
succeeded. Earlier incomplete logs remain preserved; no approval bypass occurred.

This milestone stores verified inputs, not a reconciled live portfolio or approved
recommendation. Fees, tax, execution reconciliation, current predictions and final
model adoption remain unfinished. The overall Goal remains active. No order sent.
