CREATE TABLE `personal_settings_versions` (
	`sequence` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`revision_id` text NOT NULL,
	`owner_id` text NOT NULL,
	`parent_revision` text NOT NULL,
	`portfolio_revision_id` text NOT NULL,
	`saved_at` text NOT NULL,
	`payload_json` text NOT NULL,
	FOREIGN KEY (`portfolio_revision_id`) REFERENCES `portfolio_versions`(`revision_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `personal_settings_versions_revision_id_unique` ON `personal_settings_versions` (`revision_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `personal_settings_owner_parent` ON `personal_settings_versions` (`owner_id`,`parent_revision`);