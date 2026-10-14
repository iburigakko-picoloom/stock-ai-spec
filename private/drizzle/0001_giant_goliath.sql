CREATE TABLE `portfolio_versions` (
	`sequence` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`revision_id` text NOT NULL,
	`owner_id` text NOT NULL,
	`parent_revision` text NOT NULL,
	`saved_at` text NOT NULL,
	`payload_json` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `portfolio_versions_revision_id_unique` ON `portfolio_versions` (`revision_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `portfolio_owner_parent` ON `portfolio_versions` (`owner_id`,`parent_revision`);