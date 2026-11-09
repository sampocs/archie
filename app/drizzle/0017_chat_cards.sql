CREATE TABLE `card_set_proposals` (
	`id` text PRIMARY KEY NOT NULL,
	`conversation_id` text NOT NULL,
	`message_id` text NOT NULL,
	`title` text NOT NULL,
	`cheat_sheet` text NOT NULL,
	`cards` text NOT NULL,
	`status` text NOT NULL,
	`saved_source_id` text,
	`kept` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
ALTER TABLE `sources` ADD `chat_conversation_id` text;
--> statement-breakpoint
-- Card-set proposals and sources' chat_conversation_id reach this phone only through a full re-pull.
UPDATE sync_state SET position = 0;