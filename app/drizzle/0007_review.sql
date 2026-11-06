CREATE TABLE `review_settings` (
	`id` integer PRIMARY KEY NOT NULL,
	`reminder_enabled` integer NOT NULL,
	`reminder_minutes` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `reviews` (
	`id` text PRIMARY KEY NOT NULL,
	`card_id` text NOT NULL,
	`grade` text NOT NULL,
	`graded_by` text NOT NULL,
	`answer` text,
	`missing` text,
	`was_due` integer NOT NULL,
	`reviewed_at` text NOT NULL,
	`state_before` text NOT NULL,
	`state_after` text NOT NULL,
	`replaces_review_id` text
);
--> statement-breakpoint
PRAGMA foreign_keys=OFF;--> statement-breakpoint
CREATE TABLE `__new_cards` (
	`id` text PRIMARY KEY NOT NULL,
	`source_id` text,
	`topic_primer_id` text,
	`brief_id` text,
	`kind` text NOT NULL,
	`question` text NOT NULL,
	`answer` text NOT NULL,
	`created_at` text NOT NULL,
	`deleted_at` text,
	`fsrs_state` text DEFAULT 'new' NOT NULL,
	`stability` real,
	`difficulty` real,
	`due_at` text,
	`last_review_at` text,
	`reps` integer DEFAULT 0 NOT NULL,
	`lapses` integer DEFAULT 0 NOT NULL,
	`expires_at` text
);
--> statement-breakpoint
INSERT INTO `__new_cards`("id", "source_id", "kind", "question", "answer", "created_at", "deleted_at") SELECT "id", "source_id", "kind", "question", "answer", "created_at", "deleted_at" FROM `cards`;--> statement-breakpoint
DROP TABLE `cards`;--> statement-breakpoint
ALTER TABLE `__new_cards` RENAME TO `cards`;--> statement-breakpoint
PRAGMA foreign_keys=ON;--> statement-breakpoint
ALTER TABLE `sources` ADD `cards_off` integer DEFAULT 0 NOT NULL;
--> statement-breakpoint
-- Cards' FSRS state and origins, and sources' cards_off, reach this phone only through a full re-pull.
UPDATE sync_state SET position = 0;
