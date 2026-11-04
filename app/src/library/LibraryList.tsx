import { useRouter } from "expo-router";
import { ReactNode, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";

import { deleteSource, setPrimerOpened, setRead, type PrimerTarget } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { FinishSheet } from "@/ui/FinishSheet";
import { GroupedList } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";
import { ItemRow } from "@/ui/ItemRow";
import { ProcessingLine } from "@/ui/ProcessingLine";
import { SnoozeSheet } from "@/ui/SnoozeSheet";
import { SourceRow } from "@/ui/SourceRow";
import { StatusTagView } from "@/ui/StatusTagView";
import { useNow } from "@/ui/useNow";

import type { LibraryData, LibrarySource, TopicPrimerRow, TopicRow } from "./join";
import { ReorderableQueue } from "./ReorderableQueue";
import { matchesQuery, searchText } from "./search";
import {
  byWeek,
  entryKey,
  entrySnoozedUntil,
  filterCounts,
  filterEntries,
  LIBRARY_FILTERS,
  type LibraryEntry,
  type LibraryFilter,
} from "./sections";
import { formatReturnTime } from "./snooze";
import { SwipeRow, type SwipeAction } from "./SwipeRow";
import { isSnoozed, queueOrder, statusTag } from "./visibility";

type LibraryListProps = {
  data: LibraryData;
  query: string;
  filter: LibraryFilter;
  onFilterChange: (filter: LibraryFilter) => void;
};

type Sheet = { kind: "snooze"; target: PrimerTarget; id: string } | { kind: "finish"; id: string };

// Swipe buttons and sheets are opened from any row, so the list hands rows these instead of each owning a sheet.
type RowActions = { openSnooze: (target: PrimerTarget, id: string) => void; openFinish: (id: string) => void };

const FILTER_LABELS: Record<LibraryFilter, string> = {
  all: "All",
  queued: "Queued",
  done: "Done",
  inbox: "Inbox",
  primers: "Primers",
};

/** The Library list: filter chips over time sections (or the queue), or search results while a query is typed. */
export function LibraryList({ data, query, filter, onFilterChange }: LibraryListProps) {
  const theme = useTheme();
  const now = useNow();
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  const rowActions: RowActions = {
    openSnooze: (target, id) => {
      setSheet({ kind: "snooze", target, id });
      setSheetOpen(true);
    },
    openFinish: (id) => {
      setSheet({ kind: "finish", id });
      setSheetOpen(true);
    },
  };
  const searching = query.trim() !== "";

  return (
    <View style={{ gap: theme.spacing.section }}>
      {searching ? (
        <SearchResults data={data} query={query} rowActions={rowActions} />
      ) : (
        <>
          <FilterChips filter={filter} counts={filterCounts(data, now)} onChange={onFilterChange} />
          {filter === "queued" ? (
            <QueueBody data={data} now={now} rowActions={rowActions} />
          ) : (
            <WeekBody data={data} filter={filter} now={now} rowActions={rowActions} />
          )}
        </>
      )}
      {sheet?.kind === "snooze" ? (
        <SnoozeSheet target={sheet.target} id={sheet.id} visible={sheetOpen} onClose={() => setSheetOpen(false)} />
      ) : null}
      {sheet?.kind === "finish" ? (
        <FinishSheet key={sheet.id} sourceId={sheet.id} visible={sheetOpen} onClose={() => setSheetOpen(false)} />
      ) : null}
    </View>
  );
}

function FilterChips(props: {
  filter: LibraryFilter;
  counts: Record<LibraryFilter, number>;
  onChange: (filter: LibraryFilter) => void;
}) {
  const theme = useTheme();

  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: theme.spacing.sm }}>
      {LIBRARY_FILTERS.map((filter) => {
        const selected = filter === props.filter;
        return (
          <Pressable
            key={filter}
            testID={`filter-${filter}`}
            onPress={() => {
              haptic("selection");
              props.onChange(filter);
            }}
            style={{
              flexDirection: "row",
              gap: theme.spacing.xs,
              paddingHorizontal: theme.spacing.md,
              paddingVertical: 7,
              borderRadius: 999,
              backgroundColor: selected ? theme.colors.chrome : theme.colors.surface,
            }}
          >
            <Text variant="secondary" tone={selected ? "onChrome" : "ink2"}>
              {FILTER_LABELS[filter]}
            </Text>
            {filter === "all" ? null : (
              <Text
                testID={`filter-count-${filter}`}
                variant="secondary"
                tone={selected ? "onChrome" : "ink2"}
                style={{ opacity: 0.55 }}
              >
                {props.counts[filter]}
              </Text>
            )}
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

function QueueBody({ data, now, rowActions }: { data: LibraryData; now: Date; rowActions: RowActions }) {
  const queue = queueOrder(data.sources).filter((source) => !isSnoozed(source, now));
  const snoozed = byWeek(filterEntries(data, "queued"), now).snoozed;

  if (queue.length === 0 && snoozed.length === 0) return <EmptyFilter />;

  return (
    <>
      {queue.length > 0 ? (
        <GroupedList title="Your queue · drag to reorder">
          <ReorderableQueue
            sources={queue}
            renderRow={(source, _index, handle) => (
              <SwipeRow actions={swipeActions({ kind: "source", source }, "queued", rowActions)}>
                <LibraryItem source={source} trailing={handle} />
              </SwipeRow>
            )}
          />
        </GroupedList>
      ) : null}
      <SnoozedSection entries={snoozed} filter="queued" now={now} rowActions={rowActions} />
    </>
  );
}

function WeekBody(props: { data: LibraryData; filter: LibraryFilter; now: Date; rowActions: RowActions }) {
  const entries = filterEntries(props.data, props.filter);
  const sections = byWeek(entries, props.now);

  if (entries.length === 0) return <EmptyFilter />;

  const section = (title: string, sectionEntries: LibraryEntry[]): ReactNode =>
    sectionEntries.length === 0 ? null : (
      <GroupedList title={title}>
        {sectionEntries.map((entry) => (
          <EntryRow key={entryKey(entry)} entry={entry} filter={props.filter} rowActions={props.rowActions} />
        ))}
      </GroupedList>
    );

  return (
    <>
      {section("This week", sections.thisWeek)}
      {section("Earlier", sections.earlier)}
      <SnoozedSection entries={sections.snoozed} filter={props.filter} now={props.now} rowActions={props.rowActions} />
    </>
  );
}

function SnoozedSection(props: { entries: LibraryEntry[]; filter: LibraryFilter; now: Date; rowActions: RowActions }) {
  if (props.entries.length === 0) return null;

  return (
    <GroupedList testID="library-snoozed" title={`Snoozed · ${props.entries.length}`}>
      {props.entries.map((entry) => (
        <EntryRow
          key={entryKey(entry)}
          entry={entry}
          filter={props.filter}
          rowActions={props.rowActions}
          trailing={
            <Text variant="monoLabel" tone="ink3" style={{ textTransform: "none" }}>
              {formatReturnTime(new Date(entrySnoozedUntil(entry)!), props.now)}
            </Text>
          }
        />
      ))}
    </GroupedList>
  );
}

function SearchResults(props: { data: LibraryData; query: string; rowActions: RowActions }) {
  const matches = props.data.sources.filter((source) => matchesQuery(searchText(source), props.query));

  if (matches.length === 0) {
    return (
      <Text testID="library-search-empty" tone="ink2">
        No matches for “{props.query.trim()}”
      </Text>
    );
  }

  return (
    <GroupedList>
      {matches.map((source) => (
        <EntryRow key={source.id} entry={{ kind: "source", source }} filter="all" rowActions={props.rowActions} />
      ))}
    </GroupedList>
  );
}

function EntryRow(props: { entry: LibraryEntry; filter: LibraryFilter; rowActions: RowActions; trailing?: ReactNode }) {
  const { entry } = props;
  return (
    <SwipeRow actions={swipeActions(entry, props.filter, props.rowActions)}>
      {entry.kind === "source" ? (
        <LibraryItem source={entry.source} trailing={props.trailing} filter={props.filter} />
      ) : (
        <TopicPrimerItem primer={entry.primer} topic={entry.topic} trailing={props.trailing} />
      )}
    </SwipeRow>
  );
}

function LibraryItem(props: { source: LibrarySource; trailing?: ReactNode; filter?: LibraryFilter }) {
  const { source, trailing } = props;
  const theme = useTheme();
  const router = useRouter();
  const asPrimer = props.filter === "primers";
  const [expanded, setExpanded] = useState(false);

  return (
    <View testID={`source-${source.id}`}>
      <SourceRow
        source={source}
        testID={`source-row-${source.id}`}
        onPress={
          asPrimer
            ? () => router.push({ pathname: "/source/[id]", params: { id: source.id, primer: "1" } })
            : undefined
        }
        end={
          <View style={{ alignItems: "flex-end", gap: theme.spacing.xs }}>
            {trailing ?? <StatusTagView tag={asPrimer ? "Primer" : statusTag(source)} testID={`status-${source.id}`} />}
            {source.syncError ? (
              <Pressable testID={`source-error-${source.id}`} onPress={() => setExpanded((open) => !open)} hitSlop={8}>
                <Text variant="secondary" style={{ color: theme.signals.missed }}>
                  ⚠ Not synced
                </Text>
              </Pressable>
            ) : null}
          </View>
        }
      />
      {source.kind === "newsletter" ? (
        <Text testID={`source-sender-${source.id}`} variant="secondary" tone="ink3" numberOfLines={1}>
          {source.sender ?? "Newsletter"}
        </Text>
      ) : null}
      {source.syncError && expanded ? (
        <Text variant="secondary" tone="ink2">
          {source.syncError}
        </Text>
      ) : null}
      <ProcessingLine source={source} />
    </View>
  );
}

function TopicPrimerItem(props: { primer: TopicPrimerRow; topic: TopicRow; trailing?: ReactNode }) {
  const router = useRouter();
  const { primer, topic } = props;

  return (
    <ItemRow
      testID={`topic-primer-${primer.id}`}
      artwork={{ imageUrl: null, domain: topic.domain, monogram: "◆", unread: !primer.openedAt }}
      kicker={{ domain: topic.domain, suffix: "Topic primer" }}
      title={topic.name}
      meta="Primer"
      end={props.trailing ?? <StatusTagView tag="Primer" />}
      onPress={() => router.push({ pathname: "/topic/[id]", params: { id: topic.id } })}
    />
  );
}

function EmptyFilter() {
  return (
    <Text testID="library-empty" tone="ink2">
      Nothing here yet. Paste a link in ＋.
    </Text>
  );
}

/** The swipe buttons for a row: what fits its state, or none. Every action syncs right away. */
function swipeActions(entry: LibraryEntry, filter: LibraryFilter, rowActions: RowActions): SwipeAction[] {
  if (entry.kind === "topicPrimer") return primerActions("topic_primer", entry.primer.id, entry.primer.openedAt, rowActions);

  const source = entry.source;
  const snoozeAction: SwipeAction = {
    key: "snooze",
    label: "Snooze",
    tone: "neutral",
    testID: `swipe-snooze-${source.id}`,
    onPress: () => rowActions.openSnooze("source", source.id),
  };

  if (filter === "primers") return primerActions("source", source.id, source.primerOpenedAt, rowActions);
  if (source.state === "queued") {
    return [
      snoozeAction,
      {
        key: "finish",
        label: "Finished",
        tone: "gotIt",
        testID: `swipe-finish-${source.id}`,
        onPress: () => rowActions.openFinish(source.id),
      },
    ];
  }
  if (source.kind === "newsletter" && (source.state === "inbox" || source.state === "briefed")) {
    return [
      snoozeAction,
      {
        key: "read",
        label: source.readAt ? "Mark unread" : "Mark read",
        tone: "chrome",
        testID: `swipe-read-${source.id}`,
        onPress: () => {
          setRead(db, source.id, !source.readAt);
          haptic("light");
          requestSync();
        },
      },
    ];
  }
  if (source.state === "consumed") {
    return [
      {
        key: "delete",
        label: "Delete",
        tone: "missed",
        testID: `swipe-delete-${source.id}`,
        onPress: () => {
          deleteSource(db, source.id);
          haptic("success");
          requestSync();
        },
      },
    ];
  }
  return [];
}

function primerActions(target: PrimerTarget, id: string, openedAt: string | null, rowActions: RowActions): SwipeAction[] {
  return [
    {
      key: "snooze",
      label: "Snooze",
      tone: "neutral",
      testID: `swipe-snooze-${id}`,
      onPress: () => rowActions.openSnooze(target, id),
    },
    {
      key: "read",
      label: openedAt ? "Mark unread" : "Mark read",
      tone: "chrome",
      testID: `swipe-read-${id}`,
      onPress: () => {
        setPrimerOpened(db, target, id, !openedAt);
        haptic("light");
        requestSync();
      },
    },
  ];
}
