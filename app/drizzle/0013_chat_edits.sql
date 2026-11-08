CREATE TABLE `card_versions` (
	`id` text PRIMARY KEY NOT NULL,
	`card_id` text NOT NULL,
	`version` integer NOT NULL,
	`question` text NOT NULL,
	`answer` text NOT NULL,
	`origin` text NOT NULL,
	`instruction` text,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `edit_proposals` (
	`id` text PRIMARY KEY NOT NULL,
	`conversation_id` text NOT NULL,
	`message_id` text NOT NULL,
	`target_kind` text NOT NULL,
	`target_id` text NOT NULL,
	`title` text NOT NULL,
	`description` text NOT NULL,
	`base_version` integer NOT NULL,
	`before` text NOT NULL,
	`after` text NOT NULL,
	`status` text NOT NULL,
	`applied_version` integer,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
ALTER TABLE `artifacts` ADD `origin` text DEFAULT 'archie' NOT NULL;--> statement-breakpoint
ALTER TABLE `artifacts` ADD `instruction` text;--> statement-breakpoint
ALTER TABLE `cards` ADD `version` integer DEFAULT 1 NOT NULL;--> statement-breakpoint
ALTER TABLE `take_versions` ADD `origin` text DEFAULT 'owner' NOT NULL;--> statement-breakpoint
ALTER TABLE `topic_primers` ADD `origin` text DEFAULT 'archie' NOT NULL;--> statement-breakpoint
ALTER TABLE `topic_primers` ADD `instruction` text;
--> statement-breakpoint
-- Card versions and Ask's edit proposals reach this phone only through a full re-pull.
UPDATE sync_state SET position = 0;