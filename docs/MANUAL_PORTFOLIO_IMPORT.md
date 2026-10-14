# App manual portfolio import

The owner enters holdings, accounts, available cash, investment budget and maximum
drawdown preference at `/portfolio` on the owner-private Site. No holdings is a valid
record. Null money and risk settings remain unknown; zero and odd-lot holdings are
preserved. Account numbers and brokerage credentials are not collected.

## Pull and acknowledgment

Set `STOCK_AI_PRIVATE_SITE_TOKEN` in process environment or an OS credential store,
then run:

```powershell
python -m stock_ai.cli ops pull-private-portfolio --database data/operations/stock-ai.sqlite3
```

The command only contacts the pinned private Site origin, refuses redirects, bounds
the export response, verifies the exact exported UTF-8 bytes and the original saved
revision hash, and validates the strict manual-input schema. It does not reserialize
JavaScript numbers before checking their hashes. Duplicate JSON keys, non-finite
numbers, invalid accounts, dangling holdings, future save times and stale revisions
are refused.

The Site requires its private access boundary plus a scoped proof:
`HMAC-SHA256(service token, "stock-ai-private-portfolio-v1")`. Runtime secrets hold
only the SHA256 digest of that proof (`STOCK_AI_PORTFOLIO_TOKEN_SHA256`) and the
explicitly pinned **per-Site** portfolio owner (`STOCK_AI_PORTFOLIO_OWNER_ID`). The
workspace account ID is not interchangeable with the per-Site visitor ID. There is
no owner selector in the export request. Other signed-in visitors and foreign origins
are refused. Service credentials stay in process memory and are never in source,
command arguments, browser code or the ledger. If the Site credential is deliberately
rotated, update the scoped digest and redeploy; no automatic rotation is performed.

The first verified import pins the local ledger's owner. Subsequent imports must use
that owner and advance the remote sequence. Intermediate versions may have been
saved while the PC was off; a sequence gap is allowed and is not proof that the entire
revision chain was observed. Same-version retries retain the first local receipt time.
Older versions, reused revisions and conflicting same-sequence contents are refused.
The import table participates in operational integrity checks, backup and restore.
Older schema backups remain verifiable before migration to schema version 3.

Only after the local SQLite transaction commits does the PC acknowledge the exact
revision and export hash. Failure to acknowledge leaves the local import intact;
retry the same command. The cloud receipt is immutable and applies only to that
owner and revision. A later saved revision returns to `PC取込待ち`. The app reload
button refreshes the displayed receipt. Imports run when this command is executed;
this change does not install a background scheduler.

## Meaning and remaining work

`PC取込済み` means the saved input was verified and stored on the PC. It does not mean
that personal comparison or a trading recommendation is ready. `missing_fields`
reports structural input gaps only, not model approval or tax/cost completeness.

`ImportedManualPortfolio.portfolio.holding_symbols` exposes every unique holding
for a later forecast/comparison adapter, including the same stock held in multiple
accounts. This input is kept separate from `PortfolioState`, recorded executions,
cash and tax ledgers. Import never resets those balances, invents realized gains or
NISA capacity, or turns a risk preference into a guaranteed drawdown bound. Before
using it for proposals, the pipeline still needs explicit execution reconciliation,
current prices and all-holdings forecasts, fee/tax settings, risk-policy mapping and
the existing model/evaluation adoption gates. Historical forecasts are not relabeled
with today's holdings. Original forecasts and scientific artifacts remain immutable.

No securities order is sent by this workflow.
