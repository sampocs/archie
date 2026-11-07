ALTER TABLE `sources` ADD `published_at` text;
--> statement-breakpoint
-- Sources' published_at reaches this phone only through a full re-pull.
UPDATE sync_state SET position = 0;