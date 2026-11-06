ALTER TABLE `sources` ADD `favorited_at` text;
--> statement-breakpoint
-- Sources' favorited_at reaches this phone only through a full re-pull.
UPDATE sync_state SET position = 0;
