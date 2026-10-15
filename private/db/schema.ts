import { integer, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

export const snapshots = sqliteTable("daily_snapshots", {
  snapshotId: text("snapshot_id").primaryKey(),
  sourceSnapshotId: text("source_snapshot_id"),
  asOf: text("as_of").notNull(),
  receivedAt: text("received_at").notNull(),
  payloadJson: text("payload_json").notNull(),
});

// Append-only revisions; one child per owner/parent prevents stale overwrites.
export const portfolioVersions = sqliteTable("portfolio_versions", {
  sequence: integer("sequence").primaryKey({ autoIncrement: true }),
  revisionId: text("revision_id").notNull().unique(),
  ownerId: text("owner_id").notNull(),
  parentRevision: text("parent_revision").notNull(),
  savedAt: text("saved_at").notNull(),
  payloadJson: text("payload_json").notNull(),
}, table => [uniqueIndex("portfolio_owner_parent").on(table.ownerId, table.parentRevision)]);

// Import receipts never modify a saved portfolio or an original forecast.
export const portfolioImports = sqliteTable("portfolio_imports", {
  revisionId: text("revision_id").primaryKey().references(() => portfolioVersions.revisionId),
  ownerId: text("owner_id").notNull(),
  exportSha256: text("export_sha256").notNull(),
  importedAt: text("imported_at").notNull(),
  acknowledgedAt: text("acknowledged_at").notNull(),
});

// Supplemental inputs reference the reviewed portfolio revision; existing input remains immutable.
export const personalSettingsVersions = sqliteTable("personal_settings_versions", {
  sequence: integer("sequence").primaryKey({ autoIncrement: true }),
  revisionId: text("revision_id").notNull().unique(),
  ownerId: text("owner_id").notNull(),
  parentRevision: text("parent_revision").notNull(),
  portfolioRevisionId: text("portfolio_revision_id").notNull().references(() => portfolioVersions.revisionId),
  savedAt: text("saved_at").notNull(),
  payloadJson: text("payload_json").notNull(),
}, table => [uniqueIndex("personal_settings_owner_parent").on(table.ownerId, table.parentRevision)]);
