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
