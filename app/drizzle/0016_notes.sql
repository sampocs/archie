ALTER TABLE `sources` ADD `note_markdown` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `note_edited_at` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `refreshed_at` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `refreshed_from_queue` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `sources` ADD `refresh_skipped_at` text;
--> statement-breakpoint
-- Sources' note fields reach this phone only through a full re-pull.
UPDATE sync_state SET position = 0;