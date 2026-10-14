import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { contentHash, canExportPortfolio, exportPortfolio, importAcknowledgment } from "../lib/portfolio-export.ts";
import { emptyPortfolio } from "../lib/portfolio.ts";

const owner = "test-owner";
const token = createHmac("sha256", "test-secret").update("stock-ai-private-portfolio-v1").digest("hex");
const url = "https://example.invalid/api/portfolio/export";
test("scoped proof requires the pinned owner and rejects browser cross-origin/other-user requests", async () => {
  const hash = await contentHash(token);
  const make = extra => new Request(url, { headers: { "X-Stock-AI-Portfolio-Access": token, ...extra } });
  assert.equal(await canExportPortfolio(make({}), owner, hash), true);
  assert.equal(await canExportPortfolio(make({ "oai-authenticated-user-id": owner }), owner, hash), true);
  assert.equal(await canExportPortfolio(make({ "oai-authenticated-user-id": "other" }), owner, hash), false);
  assert.equal(await canExportPortfolio(make({ origin: "https://other.invalid" }), owner, hash), false);
  assert.equal(await canExportPortfolio(new Request(url), owner, hash), false);
  assert.equal(await canExportPortfolio(make({}), undefined, hash), false);
  assert.equal(await canExportPortfolio(make({}), owner, undefined), false);
  assert.equal(await canExportPortfolio(make({}), owner, "f".repeat(64)), false);
  assert.equal(await canExportPortfolio(make({ "X-Stock-AI-Portfolio-Access": "Bearer secret" }), owner, hash), false);
});
test("export preserves exact saved bytes and authenticates the original revision", async () => {
  const portfolio = { ...emptyPortfolio, maximum_drawdown_percent: 1e-7 };
  const revisionJson = JSON.stringify({ owner, parent: null, portfolio });
  const row = { revisionId: await contentHash(revisionJson), sequence: 2, ownerId: owner,
    parentRevision: "initial", savedAt: "2026-01-01T00:00:00.000Z", payloadJson: JSON.stringify(portfolio) };
  const envelope = await exportPortfolio(row);
  assert.equal(await contentHash(envelope.export_json), envelope.export_sha256);
  assert.equal(JSON.parse(envelope.export_json).revision_json, revisionJson);
  assert.deepEqual(await exportPortfolio(row), envelope);
  await assert.rejects(exportPortfolio({ ...row, ownerId: "other" }), /revision content/);
  await assert.rejects(exportPortfolio({ ...row, payloadJson: "{}" }), /revision content/);
  await assert.rejects(exportPortfolio({ ...row, parentRevision: "a".repeat(64) }), /revision content/);
});
test("ack schema accepts UTC offsets and refuses extra fields, missing hashes and naive times", () => {
  const ack = { revision_id: "a".repeat(64), export_sha256: "b".repeat(64), imported_at: "2026-01-01T09:00:00+09:00" };
  assert.deepEqual(importAcknowledgment.parse(ack), ack);
  for (const invalid of [{ ...ack, owner: "other" }, { ...ack, revision_id: "bad" },
    { ...ack, imported_at: "2026-01-01T00:00:00" }]) assert.throws(() => importAcknowledgment.parse(invalid));
});
test("additive receipts preserve forecasts and revisions; an old receipt cannot acknowledge a new revision", () => {
  const db = new DatabaseSync(":memory:");
  try {
    db.exec("PRAGMA foreign_keys=ON");
    for (const filename of ["0000_damp_mysterio.sql", "0001_giant_goliath.sql", "0002_moaning_killraven.sql"])
      db.exec(readFileSync(new URL(`../drizzle/${filename}`, import.meta.url), "utf8"));
    db.prepare("INSERT INTO daily_snapshots VALUES ('original',NULL,'test','test','{}')").run();
    const version = db.prepare("INSERT INTO portfolio_versions (revision_id,owner_id,parent_revision,saved_at,payload_json) VALUES (?,?,?,?,?)");
    version.run("a", owner, "initial", "test", JSON.stringify(emptyPortfolio));
    const insert = db.prepare("INSERT INTO portfolio_imports VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING");
    assert.equal(insert.run("a", owner, "hash", "first", "test").changes, 1);
    assert.equal(insert.run("a", owner, "hash", "retry", "test").changes, 0);
    assert.throws(() => insert.run("unknown", owner, "hash", "test", "test"));
    version.run("b", owner, "a", "test", JSON.stringify(emptyPortfolio));
    const receipt = db.prepare("SELECT * FROM portfolio_imports WHERE owner_id=? AND revision_id=?");
    assert.equal(receipt.get(owner, "a").imported_at, "first");
    assert.equal(receipt.get(owner, "b"), undefined);
    assert.equal(receipt.get("other", "a"), undefined);
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM daily_snapshots").get().n, 1);
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM portfolio_versions").get().n, 2);
  } finally { db.close(); }
});
