CREATE TABLE `artifacts` (
	`id` text PRIMARY KEY NOT NULL,
	`source_id` text NOT NULL,
	`kind` text NOT NULL,
	`version` integer NOT NULL,
	`content` text NOT NULL,
	`is_current` integer NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `cards` (
	`id` text PRIMARY KEY NOT NULL,
	`source_id` text NOT NULL,
	`kind` text NOT NULL,
	`question` text NOT NULL,
	`answer` text NOT NULL,
	`created_at` text NOT NULL,
	`deleted_at` text
);
--> statement-breakpoint
ALTER TABLE `sources` ADD `processing` text DEFAULT 'pending' NOT NULL;--> statement-breakpoint
ALTER TABLE `sources` ADD `processing_error` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `reaction` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `note` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `prep_me` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `sources` ADD `merged_into_id` text;