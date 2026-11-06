CREATE TABLE `collection_items` (
	`id` text PRIMARY KEY NOT NULL,
	`collection_id` text NOT NULL,
	`url` text NOT NULL,
	`kind` text NOT NULL,
	`title` text,
	`author` text,
	`image_url` text,
	`duration_seconds` integer,
	`note` text,
	`metadata_status` text DEFAULT 'pending' NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`deleted_at` text
);
--> statement-breakpoint
CREATE TABLE `collections` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`position` real NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`deleted_at` text
);
--> statement-breakpoint
-- An older build ignores unknown pull keys, so collection rows pulled before this table existed come only through a re-pull.
UPDATE sync_state SET position = 0;
