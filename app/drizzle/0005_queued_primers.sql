ALTER TABLE `sources` DROP COLUMN `prep_me`;--> statement-breakpoint
ALTER TABLE `sources` ADD `primer_queue_position` real;--> statement-breakpoint
ALTER TABLE `sources` ADD `primer_snoozed_until` text;--> statement-breakpoint
-- New server columns on existing rows reach the phone only through a full re-pull.
UPDATE sync_state SET position = 0;