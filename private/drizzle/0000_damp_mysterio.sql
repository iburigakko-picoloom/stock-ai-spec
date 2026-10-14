CREATE TABLE `daily_snapshots` (
	`snapshot_id` text PRIMARY KEY NOT NULL,
	`source_snapshot_id` text,
	`as_of` text NOT NULL,
	`received_at` text NOT NULL,
	`payload_json` text NOT NULL
);
