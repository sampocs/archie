import { useIsFocused } from "expo-router";
import Storage from "expo-sqlite/kv-store";
import { useCallback, useEffect, useRef, useState } from "react";

import { celebratedOn, DAY_DONE, storedCelebrations, type CelebrationKey } from "./celebrations";
import { doneTaskKinds, type TaskKind, type TodayTasks } from "./todayTasks";

// Phone-only, so it lives in the key-value store: what Today has celebrated, for one local day at a time.
const CELEBRATIONS_KEY = "today.celebrations";
// A half-loaded first render can look finished for a frame, so a finish is remembered only once it has held this long.
const SETTLE_MS = 600;
// The last task's own row plays first; then "Today's done" takes over.
const DAY_DONE_DELAY_MS = 900;

export type TodayCelebration = {
  // The tasks to draw: held as they were while Today is off screen, so a finish elsewhere plays on coming back.
  tasks: TodayTasks;
  // Whether a done row should pop as it appears (not yet celebrated today).
  isFresh: (kind: TaskKind) => boolean;
  showDayCard: boolean;
  celebrateDay: boolean;
  // Layout motion is held back until the first load has settled, so data arriving doesn't slide the screen about.
  settled: boolean;
};

/** Which of today's finishes still deserve their animation, remembered per local `day` (e.g. "2026-11-09"). */
export function useTodayCelebration(live: TodayTasks, day: string): TodayCelebration {
  const focused = useIsFocused();
  const shown = useRef(live);
  if (focused) shown.current = live;
  const tasks = shown.current;

  const [memory, setMemory] = useState(() => ({ day, keys: readCelebrated(day) }));
  const celebrated = memory.day === day ? memory.keys : readCelebrated(day);
  const remember = useCallback(
    (keys: CelebrationKey[]) => {
      const merged = [...readCelebrated(day), ...keys];
      Storage.setItemSync(CELEBRATIONS_KEY, storedCelebrations(day, merged));
      setMemory({ day, keys: new Set(merged) });
    },
    [day],
  );

  // Rows: a finish that has held for a moment is remembered, so later renders show it without motion.
  const fresh = doneTaskKinds(tasks).filter((kind) => !celebrated.has(kind));
  const freshKey = fresh.join(",");
  useEffect(() => {
    if (freshKey === "") return;
    const timer = setTimeout(() => remember(freshKey.split(",") as TaskKind[]), SETTLE_MS);
    return () => clearTimeout(timer);
  }, [freshKey, remember]);

  // The day: shortly after the last task finishes, the rows give way to "Today's done", once per day.
  const dayFresh = tasks.dayDone && !celebrated.has(DAY_DONE);
  const [playingDay, setPlayingDay] = useState(false);
  useEffect(() => {
    if (!dayFresh) return;
    const timer = setTimeout(() => {
      setPlayingDay(true);
      remember([DAY_DONE, ...doneTaskKinds(shown.current)]);
    }, DAY_DONE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [dayFresh, remember]);
  useEffect(() => {
    if (!tasks.dayDone) setPlayingDay(false);
  }, [tasks.dayDone]);

  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(true), SETTLE_MS);
    return () => clearTimeout(timer);
  }, []);

  return {
    tasks,
    isFresh: (kind) => settled && !celebrated.has(kind),
    showDayCard: tasks.dayDone && celebrated.has(DAY_DONE),
    celebrateDay: playingDay,
    settled,
  };
}

function readCelebrated(day: string): Set<CelebrationKey> {
  return celebratedOn(Storage.getItemSync(CELEBRATIONS_KEY), day);
}
