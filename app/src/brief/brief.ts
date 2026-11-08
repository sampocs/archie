/** The newsletter brief's stored JSON, and the labels and choices Today and the brief screen derive from it. */

import type * as schema from "@/db/schema";
import { readingMinutes, wordCount } from "@/library/primer";
import { recentDayLabel } from "@/today/todayLabels";
import { DOMAINS, type DomainName } from "@/topics/domains";

export type BriefRow = typeof schema.briefs.$inferSelect;
type SourceRow = typeof schema.sources.$inferSelect;

export type BriefStory = {
  headline: string;
  body: string;
  // "Why it matters"; may be empty.
  why: string;
  detail: string;
  importance: number;
  source_ids: string[];
};
export type BriefContent = {
  // Stored already ordered (domains by their top story, stories by importance): shown as is.
  domains: { domain: string; stories: BriefStory[] }[];
  also: { text: string; source_ids: string[] }[];
  essays: { source_id: string; pitch: string }[];
};

/** A story with its place in display order (the story page's address) and its domain. */
export type NumberedStory = { index: number; domain: DomainName; story: BriefStory };

/** What Today shows for the brief: the preview, "Writing your brief…" with how many newsletters wait, or nothing. */
export type TodayBrief =
  | { kind: "ready"; brief: BriefRow; content: BriefContent }
  | { kind: "writing"; newsletters: number }
  | null;

export type PreviewLines = { headlines: string[]; more: string | null };

const BRIEF_STATUS_OPEN = "open";
const PREVIEW_HEADLINES = 3;
// A failed or unsupported newsletter has no text to brief, so it never makes a brief "writing".
const UNBRIEFABLE_PROCESSING = new Set(["failed", "unsupported"]);
const WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

export function parseBriefContent(content: string | null): BriefContent | null {
  return content === null ? null : (JSON.parse(content) as BriefContent);
}

/** The domain's display name, matched case-insensitively as the server's `parse_domain` does; unknown is Other. */
export function briefDomain(raw: string): DomainName {
  const wanted = raw.trim().toLowerCase();
  return DOMAINS.find((domain) => domain.toLowerCase() === wanted) ?? "Other";
}

/** Every story in display order, numbered from 0 across domains. */
export function storiesInOrder(content: BriefContent): NumberedStory[] {
  const stories = content.domains.flatMap((group) =>
    group.stories.map((story) => ({ domain: briefDomain(group.domain), story })),
  );
  return stories.map((entry, index) => ({ index, ...entry }));
}

/** Minutes to read the brief straight through: story bodies, their "why" and the also lines at 220 words a minute. */
export function briefReadingMinutes(content: BriefContent): number {
  const stories = content.domains.flatMap((group) => group.stories);
  const texts = [...stories.flatMap((story) => [story.body, story.why]), ...content.also.map((line) => line.text)];
  return readingMinutes(texts.reduce((words, text) => words + wordCount(text), 0));
}

/** "since today", "since yesterday", else "since Mon": the oldest covered newsletter, by the phone's calendar. */
export function briefSinceLabel(since: string, now: Date): string {
  const sinceDay = startOfDay(new Date(since));
  const today = startOfDay(now);
  if (sinceDay.getTime() === today.getTime()) return "since today";

  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (sinceDay.getTime() === yesterday.getTime()) return "since yesterday";
  return `since ${recentDayLabel(since, now)}`;
}

/** "Wednesday's brief", named for the phone's today. */
export function briefTitle(now: Date): string {
  return `${WEEKDAY_NAMES[now.getDay()]}'s brief`;
}

export function storyCountLabel(count: number): string {
  return `${count} ${count === 1 ? "story" : "stories"}`;
}

export function essayCountLabel(count: number): string {
  return `${count} ${count === 1 ? "essay" : "essays"}`;
}

/** The preview card's first headlines and its "+ 3 more, and 2 essays" line (null when nothing else is in it). */
export function previewLines(content: BriefContent): PreviewLines {
  const stories = storiesInOrder(content);
  const hidden = stories.length - PREVIEW_HEADLINES;
  const essays = content.essays.length;
  const headlines = stories.slice(0, PREVIEW_HEADLINES).map((entry) => entry.story.headline);

  if (hidden > 0 && essays > 0) return { headlines, more: `+ ${hidden} more, and ${essayCountLabel(essays)}` };
  if (hidden > 0) return { headlines, more: `+ ${hidden} more` };
  if (essays > 0) return { headlines, more: `+ ${essayCountLabel(essays)}` };
  return { headlines, more: null };
}

/**
 * Today's brief card. The open brief's content wins; without it, newsletters the server will brief (inbox, not failed,
 * however old, and not a signup confirmation, which is never briefed) mean one is being written. `sources` are the phone's non-deleted ones.
 */
export function todayBrief(
  briefs: BriefRow[],
  sources: Pick<SourceRow, "kind" | "state" | "processing" | "confirmUrl">[],
): TodayBrief {
  const open = briefs.find((brief) => brief.status === BRIEF_STATUS_OPEN);
  const content = open ? parseBriefContent(open.content) : null;
  if (open && content) return { kind: "ready", brief: open, content };

  const newsletters = sources.filter(
    (source) =>
      source.kind === "newsletter" &&
      source.state === "inbox" &&
      source.confirmUrl === null &&
      !UNBRIEFABLE_PROCESSING.has(source.processing),
  ).length;
  return newsletters > 0 ? { kind: "writing", newsletters } : null;
}

/** Whether the brief is the open one, the only one Done applies to. */
export function isOpenBrief(brief: BriefRow): boolean {
  return brief.status === BRIEF_STATUS_OPEN;
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}
