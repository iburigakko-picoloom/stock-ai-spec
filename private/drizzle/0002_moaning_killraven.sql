CREATE TABLE `portfolio_imports` (
	`revision_id` text PRIMARY KEY NOT NULL,
	`owner_id` text NOT NULL,
	`export_sha256` text NOT NULL,
	`imported_at` text NOT NULL,
	`acknowledged_at` text NOT NULL,
	FOREIGN KEY (`revision_id`) REFERENCES `portfolio_versions`(`revision_id`) ON UPDATE no action ON DELETE no action
);
