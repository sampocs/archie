CREATE TABLE `conversations` (
	`id` text PRIMARY KEY NOT NULL,
	`title` text NOT NULL,
	`about_kind` text,
	`about_source_id` text,
	`about_topic_primer_id` text,
	`about_take_id` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`deleted_at` text
);
--> statement-breakpoint
CREATE TABLE `messages` (
	`id` text PRIMARY KEY NOT NULL,
	`conversation_id` text NOT NULL,
	`role` text NOT NULL,
	`text` text NOT NULL,
	`segments` text,
	`web_search` integer DEFAULT 0 NOT NULL,
	`status` text NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
ALTER TABLE `cards` ADD `conversation_id` text;--> statement-breakpoint
ALTER TABLE `cards` ADD `message_id` text;
--> statement-breakpoint
-- Chats, their messages and the cards' chat columns reach this phone only through a full re-pull.
UPDATE sync_state SET position = 0;