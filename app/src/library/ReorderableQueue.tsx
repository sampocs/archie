import { ReactNode, useEffect, useMemo, useRef } from "react";
import { StyleSheet, View } from "react-native";
import { GestureDetector, usePanGesture } from "react-native-gesture-handler";
import Animated, { useAnimatedStyle, useSharedValue, withSpring, withTiming, type SharedValue } from "react-native-reanimated";
import { scheduleOnRN } from "react-native-worklets";

import { setQueuePosition } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

import { dropIndex, positionAfterMove } from "./queue";
import type { QueueEntry } from "./visibility";

type ReorderableQueueProps = {
  entries: QueueEntry[];
  renderRow: (entry: QueueEntry, index: number) => ReactNode;
};

// The expected row height; each row reports its real one once laid out.
export const QUEUE_ROW_HEIGHT = 76;
const NOT_DRAGGING = -1;
const SHIFT_MS = 150;
const LIFT_SCALE = 1.02;
// Holding a row this long lifts it; moving first scrolls or swipes instead.
const LIFT_AFTER_MS = 300;
const RELEASE_FALLBACK_MS = 600;

type DragState = {
  from: SharedValue<number>;
  to: SharedValue<number>;
  translationY: SharedValue<number>;
  heights: SharedValue<number[]>;
};

/**
 * The queue in order (sources and queued primers), reordered by pressing and holding a row, then dragging it; rows in
 * between slide aside while dragging.
 */
export function ReorderableQueue({ entries, renderRow }: ReorderableQueueProps) {
  const theme = useTheme();
  const from = useSharedValue(NOT_DRAGGING);
  const to = useSharedValue(NOT_DRAGGING);
  const translationY = useSharedValue(0);
  const heights = useSharedValue<number[]>([]);
  const drag = useMemo<DragState>(() => ({ from, to, translationY, heights }), [from, to, translationY, heights]);
  const order = entries.map((entry) => entry.key).join(",");
  const latestOrder = useRef(order);
  latestOrder.current = order;
  // Row heights live on the JS side and are copied to the UI thread: reading a shared value on the JS thread returns
  // the UI thread's copy, which lags behind the JS thread's own writes, so building the array there loses rows.
  const heightsById = useRef(new Map<string, number>());

  function publishHeights(): void {
    drag.heights.value = entries.map((entry) => heightsById.current.get(entry.key) ?? QUEUE_ROW_HEIGHT);
  }

  function release(): void {
    drag.from.value = NOT_DRAGGING;
    drag.to.value = NOT_DRAGGING;
    drag.translationY.value = 0;
  }

  // A move lands once the reordered list arrives; only then does the dragged row let go of its offset.
  useEffect(() => {
    release();
    publishHeights();
    // The shared values are stable; the order is what matters.
  }, [order]);

  function onMove(moveFrom: number, moveTo: number): void {
    // Sources and primers share one position space; the moved entry says which of its source's positions changes.
    const positions = entries.map((entry, index) => entry.position ?? index);
    const moved = entries[moveFrom];
    const target = moved.kind === "primer" ? "source_primer" : "source";
    setQueuePosition(db, moved.source.id, positionAfterMove(positions, moveFrom, moveTo), target);
    haptic("light");
    requestSync();

    // Tied positions can leave the order unchanged; let go anyway rather than leave the row hanging.
    const orderAtMove = order;
    setTimeout(() => {
      if (latestOrder.current === orderAtMove && drag.from.value === moveFrom) release();
    }, RELEASE_FALLBACK_MS);
  }

  function onLayoutRow(id: string, height: number): void {
    heightsById.current.set(id, height);
    publishHeights();
  }

  return (
    <View>
      {entries.map((entry, index) => (
        <QueueRow
          key={entry.key}
          index={index}
          drag={drag}
          onMove={onMove}
          onLayout={(height) => onLayoutRow(entry.key, height)}
          divider={index > 0 ? theme.colors.line : null}
        >
          {renderRow(entry, index)}
        </QueueRow>
      ))}
    </View>
  );
}

type QueueRowProps = {
  index: number;
  drag: DragState;
  onMove: (from: number, to: number) => void;
  onLayout: (height: number) => void;
  divider: string | null;
  children: ReactNode;
};

function QueueRow({ index, drag, onMove, onLayout, divider, children }: QueueRowProps) {
  const theme = useTheme();

  const surface = theme.colors.surface;

  const panConfig = useMemo(
    () => ({
      activateAfterLongPress: LIFT_AFTER_MS,
      onActivate: () => {
        "worklet";
        drag.from.value = index;
        drag.to.value = index;
        drag.translationY.value = 0;
        scheduleOnRN(haptic, "light");
      },
      onUpdate: (event: { translationY: number }) => {
        "worklet";
        drag.translationY.value = event.translationY;
        drag.to.value = dropIndex(drag.heights.value, index, event.translationY);
      },
      onDeactivate: () => {
        "worklet";
        // A deactivation can arrive again after this row has already let go; only the row being dragged may move.
        if (drag.from.value !== index) return;
        const to = drag.to.value;
        if (to !== index) {
          scheduleOnRN(onMove, index, to);
          return;
        }
        drag.translationY.value = withSpring(0, { duration: 250 }, () => {
          drag.from.value = NOT_DRAGGING;
          drag.to.value = NOT_DRAGGING;
        });
      },
    }),
    [drag, index, onMove],
  );
  const pan = usePanGesture(panConfig);

  const animatedStyle = useAnimatedStyle(() => {
    const from = drag.from.value;
    if (from === NOT_DRAGGING) return { transform: [{ translateY: 0 }, { scale: 1 }], zIndex: 0, shadowOpacity: 0, backgroundColor: "transparent" };
    if (from === index) {
      return {
        transform: [{ translateY: drag.translationY.value }, { scale: LIFT_SCALE }],
        zIndex: 1,
        shadowOpacity: 0.18,
        backgroundColor: surface,
      };
    }

    // Rows between the dragged row's start and its drop point slide over by its height.
    const to = drag.to.value;
    const draggedHeight = drag.heights.value[from] ?? QUEUE_ROW_HEIGHT;
    const passedDown = from < to && index > from && index <= to;
    const passedUp = to < from && index >= to && index < from;
    const shift = passedDown ? -draggedHeight : passedUp ? draggedHeight : 0;
    return {
      transform: [{ translateY: withTiming(shift, { duration: SHIFT_MS }) }, { scale: 1 }],
      zIndex: 0,
      shadowOpacity: 0,
      backgroundColor: "transparent",
    };
  });
  // The hairline is hidden on the lifted row, whose card edge replaces it.
  const dividerStyle = useAnimatedStyle(() => ({ opacity: drag.from.value === index ? 0 : 1 }));

  return (
    <GestureDetector gesture={pan}>
      <Animated.View
        testID={`queue-row-${index}`}
        onLayout={(event) => onLayout(event.nativeEvent.layout.height)}
        style={[
          {
            // The row bleeds out to the surrounding card's edges (undoing its padding), so a lifted row is the full
            // card width; the padding puts the content back where it sat.
            marginHorizontal: -theme.spacing.lg,
            paddingHorizontal: theme.spacing.lg,
            borderRadius: theme.radii.card,
            shadowColor: theme.colors.ink,
            shadowRadius: 10,
            shadowOffset: { width: 0, height: 4 },
          },
          animatedStyle,
        ]}
      >
        {divider ? (
          <Animated.View
            pointerEvents="none"
            style={[
              {
                position: "absolute",
                top: 0,
                left: theme.spacing.lg,
                right: theme.spacing.lg,
                height: StyleSheet.hairlineWidth,
                backgroundColor: divider,
              },
              dividerStyle,
            ]}
          />
        ) : null}
        {children}
      </Animated.View>
    </GestureDetector>
  );
}
