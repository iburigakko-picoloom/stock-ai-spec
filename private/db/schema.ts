import { sqliteTable, text } from "drizzle-orm/sqlite-core";

export const snapshots = sqliteTable("daily_snapshots", {
  snapshotId: text("snapshot_id").primaryKey(),
  sourceSnapshotId: text("source_snapshot_id"),
  asOf: text("as_of").notNull(),
  receivedAt: text("received_at").notNull(),
  payloadJson: text("payload_json").notNull(),
});
