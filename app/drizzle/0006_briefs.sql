CREATE TABLE `briefs` (
	`id` text PRIMARY KEY NOT NULL,
	`status` text NOT NULL,
	`content` text,
	`source_ids` text NOT NULL,
	`since` text,
	`version` integer NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`done_at` text
);
--> statement-breakpoint
-- Briefs written before this phone had the table reach it only through a full re-pull.
UPDATE sync_state SET position = 0;