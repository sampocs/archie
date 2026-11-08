CREATE TABLE `newsletter_senders` (
	`id` text PRIMARY KEY NOT NULL,
	`label` text NOT NULL,
	`status` text NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`change_seq` integer NOT NULL
);
--> statement-breakpoint
ALTER TABLE `sources` ADD `sender_address` text;--> statement-breakpoint
ALTER TABLE `sources` ADD `sender_pending` integer DEFAULT false NOT NULL;
--> statement-breakpoint
-- The new sender columns and table reach this phone only through a full re-pull.
UPDATE sync_state SET position = 0;