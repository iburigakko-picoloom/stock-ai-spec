import test from "node:test";
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { emptyPortfolio, portfolioInput, portfolioSave, portfolioResponse } from "../lib/portfolio.ts";

const account = { id: "00000000-0000-4000-8000-000000000001", name: "ローカル検証用",
  account_type: "taxable_specified", withholding_mode: "withholding", available_cash_yen: null };
const holding = { account_id: account.id, symbol: "7203", shares: 1, average_acquisition_price_yen: "1234.5678" };
const populated = { ...emptyPortfolio, holdings_status: "recorded", accounts: [account], holdings: [holding] };

test("no holdings can be saved without inventing capital or accounts", () => {
  assert.deepEqual(portfolioInput.parse(emptyPortfolio), emptyPortfolio);
  assert.equal(portfolioInput.parse({ ...emptyPortfolio, investment_budget_yen: "0" }).investment_budget_yen, "0");
  assert.equal(portfolioInput.parse(emptyPortfolio).investment_budget_yen, null);
  assert.equal(portfolioSave.parse({ expected_revision_id: null, portfolio: emptyPortfolio }).expected_revision_id, null);
});
test("preserves decimal money and actual odd-lot holdings", () => {
  const result = portfolioInput.parse(populated);
  assert.equal(result.holdings[0].shares, 1);
  assert.equal(result.holdings[0].average_acquisition_price_yen, "1234.5678");
});
test("rejects unsafe numeric forms, credentials and impossible risk settings", () => {
  for (const value of ["-1", "1e8", "NaN", "1,000", "1.12345", "1000000000000", 123])
    assert.throws(() => portfolioInput.parse({ ...emptyPortfolio, investment_budget_yen: value }));
  for (const value of [0, -1, 100.1, Infinity])
    assert.throws(() => portfolioInput.parse({ ...emptyPortfolio, maximum_drawdown_percent: value }));
  assert.throws(() => portfolioInput.parse({ ...emptyPortfolio, password: "not-permitted" }));
});
test("account types have coherent withholding settings", () => {
  assert.doesNotThrow(() => portfolioInput.parse({ ...emptyPortfolio,
    accounts: [{ ...account, account_type: "nisa", withholding_mode: "not_applicable" }] }));
  for (const entry of [{ ...account, account_type: "nisa" },
    { ...account, account_type: "taxable_general" }, { ...account, withholding_mode: "not_applicable" }])
    assert.throws(() => portfolioInput.parse({ ...emptyPortfolio, accounts: [entry] }));
});
test("rejects duplicate, dangling and incoherent holdings", () => {
  assert.throws(() => portfolioInput.parse({ ...populated, accounts: [] }));
  assert.throws(() => portfolioInput.parse({ ...populated, accounts: [account, account] }));
  assert.throws(() => portfolioInput.parse({ ...populated, holdings: [holding, holding] }));
  assert.throws(() => portfolioInput.parse({ ...populated, holdings_status: "none" }));
  assert.throws(() => portfolioInput.parse({ ...emptyPortfolio, holdings_status: "recorded" }));
  for (const shares of [0, -1, .5, Infinity])
    assert.throws(() => portfolioInput.parse({ ...populated, holdings: [{ ...holding, shares }] }));
});
test("same stock in two different accounts stays distinct", () => {
  const other = { ...account, id: "00000000-0000-4000-8000-000000000002" };
  const result = portfolioInput.parse({ ...populated, accounts: [account, other],
    holdings: [holding, { ...holding, account_id: other.id }] });
  assert.equal(result.holdings.length, 2);
});
test("response validation rejects malformed saved data", () => {
  assert.deepEqual(portfolioResponse.parse({ saved: null }), { saved: null });
  assert.throws(() => portfolioResponse.parse({ saved: { portfolio: populated } }));
});
test("additive migration preserves forecasts and atomically refuses stale revisions", () => {
  const db = new DatabaseSync(":memory:");
  try {
    db.exec(readFileSync(new URL("../drizzle/0000_damp_mysterio.sql", import.meta.url), "utf8"));
    db.exec("INSERT INTO daily_snapshots VALUES ('original', NULL, 'test', 'test', '{}')");
    db.exec(readFileSync(new URL("../drizzle/0001_giant_goliath.sql", import.meta.url), "utf8"));
    const insert = db.prepare("INSERT INTO portfolio_versions (revision_id,owner_id,parent_revision,saved_at,payload_json) VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING");
    assert.equal(insert.run("a", "owner-1", "initial", "test", "{}").changes, 1);
    assert.equal(insert.run("stale", "owner-1", "initial", "test", "{}").changes, 0);
    assert.equal(insert.run("b", "owner-1", "a", "test", "{}").changes, 1);
    assert.equal(insert.run("b", "owner-1", "a", "test", "{}").changes, 0);
    assert.equal(insert.run("c", "owner-2", "initial", "test", "{}").changes, 1);
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM daily_snapshots WHERE snapshot_id='original'").get().n, 1);
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM portfolio_versions WHERE owner_id='owner-1'").get().n, 2);
  } finally { db.close(); }
});
