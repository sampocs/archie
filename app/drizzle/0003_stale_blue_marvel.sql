CREATE TABLE `topic_primers` (
	`id` text PRIMARY KEY NOT NULL,
	`topic_id` text NOT NULL,
	`version` integer NOT NULL,
	`is_current` integer NOT NULL,
	`content` text NOT NULL,
	`opened_at` text,
	`snoozed_until` text,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `topics` (
	`id` text PRIMARY KEY NOT NULL,
	`domain` text NOT NULL,
	`name` text NOT NULL,
	`origin` text NOT NULL,
	`removed_at` text,
	`merged_into_id` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`primer_requested_at` text
);
--> statement-breakpoint
ALTER TABLE `sources` ADD `domain` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `topic_id` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `image_url` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `queue_position` real;--> statement-breakpoint
ALTER TABLE `sources` ADD `read_at` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `snoozed_until` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `primer_opened_at` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `newsletter_kind` text;