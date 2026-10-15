import test from "node:test";
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import { emptyPortfolio } from "../lib/portfolio.ts";
import { emptySettings, personalSettingsInput, validateSettingsPortfolio, inputGaps } from "../lib/personal-settings.ts";
import { settingsHash, exportSettings } from "../lib/settings-export.ts";

const revision = "a".repeat(64);
const account = { id: "00000000-0000-4000-8000-000000000001", name: "検証用口座", account_type: "taxable_specified",
  withholding_mode: "withholding", available_cash_yen: "999999999999.9998" };
const portfolio = { ...emptyPortfolio, accounts: [account] };
const draft = () => emptySettings(revision, portfolio);

test("unconfirmed personal amounts and no holdings stay unknown", () => {
  const input = personalSettingsInput.parse(emptySettings(revision, emptyPortfolio));
  assert.deepEqual(input.accounts, []);
  assert.equal(input.tax_year, null);
  assert.equal(input.cash_basis, null);
  assert.equal(input.cost_assumptions.commission_fixed_yen, null);
  assert.equal(input.tax_assumptions.taxable_rate_percent, null);
  assert.equal(input.research_conditions_reviewed, false);
  assert.ok(inputGaps(input, emptyPortfolio).includes("口座の登録"));
});
test("zero is explicit and independent from missing input", () => {
  const input = draft(); input.accounts[0].realized_gain_ytd = "0";
  const parsed = personalSettingsInput.parse(input);
  assert.equal(parsed.accounts[0].realized_gain_ytd, "0");
  assert.equal(parsed.accounts[0].realized_loss_ytd, null);
  assert.equal(parsed.accounts[0].pending_activity, "unknown");
});
test("portfolio revision and account membership must match exactly", () => {
  assert.equal(validateSettingsPortfolio(draft(), revision, portfolio), null);
  assert.ok(validateSettingsPortfolio(draft(), "b".repeat(64), portfolio));
  assert.ok(validateSettingsPortfolio({ ...draft(), accounts: [] }, revision, portfolio));
  assert.ok(validateSettingsPortfolio(draft(), revision, emptyPortfolio));
  assert.throws(() => personalSettingsInput.parse({ ...draft(), accounts: [...draft().accounts, ...draft().accounts] }));
});
test("non-NISA accounts cannot carry NISA capacity; NISA missing capacity stays missing", () => {
  const input = draft(); input.accounts[0].nisa_annual_capacity_user_input = "0";
  assert.ok(validateSettingsPortfolio(input, revision, portfolio));
  const nisa = { ...portfolio, accounts: [{ ...account, account_type: "nisa", withholding_mode: "not_applicable" }] };
  assert.equal(validateSettingsPortfolio(input, revision, nisa), null);
  assert.ok(inputGaps(input, nisa).some(value => value.includes("NISA残り枠")));
});
test("cash comparisons retain all four decimal places at the largest accepted amounts", () => {
  const input = draft(); input.cash_basis = "total_including_reserved";
  input.accounts[0].reserved_cash_yen = "999999999999.9999";
  assert.ok(validateSettingsPortfolio(personalSettingsInput.parse(input), revision, portfolio));
  input.accounts[0].reserved_cash_yen = "999999999999.9998";
  assert.equal(validateSettingsPortfolio(input, revision, portfolio), null);
  input.cash_basis = "deployable_after_reserved";
  input.accounts[0].reserved_cash_yen = "999999999999.9999";
  assert.equal(validateSettingsPortfolio(input, revision, portfolio), null);
});
test("zero commission requires a coherent affirmative confirmation", () => {
  const input = draft();
  Object.assign(input.cost_assumptions, { commission_fixed_yen: "0", commission_bps: "0.0000", minimum_commission_yen: "0" });
  assert.throws(() => personalSettingsInput.parse(input));
  input.cost_assumptions.zero_commission_confirmed = true;
  assert.doesNotThrow(() => personalSettingsInput.parse(input));
  input.cost_assumptions.commission_bps = "0.0001";
  assert.throws(() => personalSettingsInput.parse(input));
});
test("invalid numbers, impossible dates, hidden credentials and unknown policy versions fail", () => {
  for (const value of ["-1", "1e8", "NaN", "1,000", "1.12345", "1000000000000", 10]) {
    const input = draft(); input.accounts[0].realized_gain_ytd = value;
    assert.throws(() => personalSettingsInput.parse(input));
  }
  for (const date of ["2026-02-30", "2026-13-01", "2026-2-1"]) {
    const input = draft(); input.tax_assumptions.effective_from = date;
    assert.throws(() => personalSettingsInput.parse(input));
  }
  const input = draft(); input.tax_assumptions.taxable_rate_percent = "100.0001";
  assert.throws(() => personalSettingsInput.parse(input));
  assert.throws(() => personalSettingsInput.parse({ ...draft(), password: "forbidden" }));
  assert.throws(() => personalSettingsInput.parse({ ...draft(), research_decision_policy: "unreviewed-v3" }));
});
test("pending activity never counts as a reconciled account", () => {
  const input = draft();
  for (const value of ["unknown", "pending"]) {
    input.accounts[0].pending_activity = value;
    assert.ok(inputGaps(input, portfolio).some(value => value.includes("未反映取引")));
  }
  input.accounts[0].pending_activity = "none";
  assert.ok(!inputGaps(input, portfolio).some(value => value.includes("未反映取引")));
});
test("export authenticates exact revision bytes, preserving owner, parent and decimals", async () => {
  const settings = draft(); settings.accounts[0].realized_gain_ytd = "1.2345";
  const owner = "test-owner", parent = null;
  const id = await settingsHash(JSON.stringify({ owner, parent, settings }));
  const row = { revisionId: id, ownerId: owner, parentRevision: "initial", sequence: 3,
    savedAt: "2026-10-15T00:00:00.000Z", payloadJson: JSON.stringify(settings) };
  const envelope = await exportSettings(row), exported = JSON.parse(envelope.export_json);
  assert.equal(await settingsHash(envelope.export_json), envelope.export_sha256);
  assert.equal(exported.schema_version, "manual-personal-settings-export-v1");
  assert.equal(JSON.parse(exported.revision_json).settings.accounts[0].realized_gain_ytd, "1.2345");
  assert.equal(JSON.parse(exported.revision_json).parent, null);
  await assert.rejects(() => exportSettings({ ...row, ownerId: "another-owner" }));
  await assert.rejects(() => exportSettings({ ...row, parentRevision: "b".repeat(64) }));
  await assert.rejects(() => exportSettings({ ...row, payloadJson: JSON.stringify(draft()) }));
});
test("additive migration preserves previous records and atomically rejects stale settings writes", () => {
  const db = new DatabaseSync(":memory:");
  try {
    db.exec("PRAGMA foreign_keys=ON");
    const dir = new URL("../drizzle/", import.meta.url);
    for (const file of readdirSync(dir).filter(name => /^000[012]_.*\.sql$/.test(name)).sort()) db.exec(readFileSync(new URL(file, dir), "utf8"));
    db.exec("INSERT INTO daily_snapshots VALUES ('forecast',NULL,'test','test','original')");
    db.prepare("INSERT INTO portfolio_versions (revision_id,owner_id,parent_revision,saved_at,payload_json) VALUES (?,?,?,?,?)").run(revision,"owner","initial","test","original");
    for (const file of readdirSync(dir).filter(name => /^0003_.*\.sql$/.test(name))) db.exec(readFileSync(new URL(file, dir), "utf8"));
    const insert = db.prepare("INSERT INTO personal_settings_versions (revision_id,owner_id,parent_revision,portfolio_revision_id,saved_at,payload_json) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING");
    assert.equal(insert.run("s1","owner","initial",revision,"test","{}").changes,1);
    assert.equal(insert.run("stale","owner","initial",revision,"test","{}").changes,0);
    assert.equal(insert.run("s2","owner","s1",revision,"test","{}").changes,1);
    assert.equal(insert.run("s2","owner","s1",revision,"test","{}").changes,0);
    assert.throws(() => insert.run("bad","owner","s2","missing","test","{}"));
    assert.equal(db.prepare("SELECT payload_json FROM daily_snapshots").get().payload_json,"original");
    assert.equal(db.prepare("SELECT payload_json FROM portfolio_versions").get().payload_json,"original");
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM personal_settings_versions").get().n,2);
  } finally { db.close(); }
});
