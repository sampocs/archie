ALTER TABLE `sources` ADD `confirm_url` text;
--> statement-breakpoint
-- Sources' confirm_url reaches this phone only through a full re-pull.
UPDATE sync_state SET position = 0;