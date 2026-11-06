CREATE TABLE `take_versions` (
	`id` text PRIMARY KEY NOT NULL,
	`take_id` text NOT NULL,
	`version` integer NOT NULL,
	`body` text,
	`raw_body` text NOT NULL,
	`cleaned` integer NOT NULL,
	`clean_failed` integer DEFAULT 0 NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `takes` (
	`id` text PRIMARY KEY NOT NULL,
	`kind` text NOT NULL,
	`title` text NOT NULL,
	`current_version` integer NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`deleted_at` text
);
--> statement-breakpoint
ALTER TABLE `cards` ADD `take_id` text;--> statement-breakpoint
ALTER TABLE `cards` ADD `take_version_id` text;
--> statement-breakpoint
-- Takes, their versions and the cards' take columns reach this phone only through a full re-pull.
UPDATE sync_state SET position = 0;
