import { ReactNode, useEffect, useMemo, useRef } from "react";
import { StyleSheet, View } from "react-native";
import { GestureDetector, usePanGesture } from "react-native-gesture-handler";
import Animated, { useAnimatedStyle, useSharedValue, withSpring, withTiming, type SharedValue } from "react-native-reanimated";
import { scheduleOnRN } from "react-native-worklets";

import { setQueuePosition } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

import type { LibrarySource } from "./join";
import { dropIndex, positionAfterMove } from "./queue";

type ReorderableQueueProps = {
  sources: LibrarySource[];
  // `handle` is the row's drag handle; the row places it as its trailing view.
  renderRow: (source: LibrarySource, index: number, handle: ReactNode) => ReactNode;
};

// The expected row height; each row reports its real one once laid out.
export const QUEUE_ROW_HEIGHT = 76;
const NOT_DRAGGING = -1;
const SHIFT_MS = 150;
const RELEASE_FALLBACK_MS = 600;

type DragState = {
  from: SharedValue<number>;
  to: SharedValue<number>;
  translationY: SharedValue<number>;
  heights: SharedValue<number[]>;
};

/** The queue in order, reordered by dragging a row's ≡ handle; rows in between slide aside while dragging. */
export function ReorderableQueue({ sources, renderRow }: ReorderableQueueProps) {
  const theme = useTheme();
  const from = useSharedValue(NOT_DRAGGING);
  const to = useSharedValue(NOT_DRAGGING);
  const translationY = useSharedValue(0);
  const heights = useSharedValue<number[]>([]);
  const drag = useMemo<DragState>(() => ({ from, to, translationY, heights }), [from, to, translationY, heights]);
  const order = sources.map((source) => source.id).join(",");
  const latestOrder = useRef(order);
  latestOrder.current = order;

  function release(): void {
    drag.from.value = NOT_DRAGGING;
    drag.to.value = NOT_DRAGGING;
    drag.translationY.value = 0;
  }

  // A move lands once the reordered list arrives; only then does the dragged row let go of its offset.
  useEffect(() => {
    release();
    drag.heights.value = sources.map((_, index) => drag.heights.value[index] ?? QUEUE_ROW_HEIGHT);
    // The shared values are stable; the order is what matters.
  }, [order]);

  function onMove(moveFrom: number, moveTo: number): void {
    const positions = sources.map((source, index) => source.queuePosition ?? index);
    setQueuePosition(db, sources[moveFrom].id, positionAfterMove(positions, moveFrom, moveTo));
    haptic("light");
    requestSync();

    // Tied positions can leave the order unchanged; let go anyway rather than leave the row hanging.
    const orderAtMove = order;
    setTimeout(() => {
      if (latestOrder.current === orderAtMove && drag.from.value === moveFrom) release();
    }, RELEASE_FALLBACK_MS);
  }

  function onLayoutRow(index: number, height: number): void {
    const heights = [...drag.heights.value];
    heights[index] = height;
    drag.heights.value = heights;
  }

  return (
    <View>
      {sources.map((source, index) => (
        <QueueRow
          key={source.id}
          index={index}
          drag={drag}
          onMove={onMove}
          onLayout={(height) => onLayoutRow(index, height)}
          divider={index > 0 ? theme.colors.line : null}
        >
          {(handle) => renderRow(source, index, handle)}
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
  children: (handle: ReactNode) => ReactNode;
};

function QueueRow({ index, drag, onMove, onLayout, divider, children }: QueueRowProps) {
  const theme = useTheme();

  const panConfig = useMemo(
    () => ({
      activeOffsetY: [-6, 6] as [number, number],
      failOffsetX: [-20, 20] as [number, number],
      onActivate: () => {
        "worklet";
        drag.from.value = index;
        drag.to.value = index;
        drag.translationY.value = 0;
        scheduleOnRN(haptic, "selection");
      },
      onUpdate: (event: { translationY: number }) => {
        "worklet";
        drag.translationY.value = event.translationY;
        drag.to.value = dropIndex(drag.heights.value, index, event.translationY);
      },
      onDeactivate: () => {
        "worklet";
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
    if (from === NOT_DRAGGING) return { transform: [{ translateY: 0 }], zIndex: 0, shadowOpacity: 0 };
    if (from === index) return { transform: [{ translateY: drag.translationY.value }], zIndex: 1, shadowOpacity: 0.18 };

    // Rows between the dragged row's start and its drop point slide over by its height.
    const to = drag.to.value;
    const draggedHeight = drag.heights.value[from] ?? QUEUE_ROW_HEIGHT;
    const passedDown = from < to && index > from && index <= to;
    const passedUp = to < from && index >= to && index < from;
    const shift = passedDown ? -draggedHeight : passedUp ? draggedHeight : 0;
    return { transform: [{ translateY: withTiming(shift, { duration: SHIFT_MS }) }], zIndex: 0, shadowOpacity: 0 };
  });

  const handle = (
    <GestureDetector gesture={pan}>
      <View testID={`queue-handle-${index}`} hitSlop={12} style={{ paddingLeft: theme.spacing.sm }}>
        <Text tone="ink3" style={{ fontSize: 18 }}>
          ≡
        </Text>
      </View>
    </GestureDetector>
  );

  return (
    <Animated.View
      testID={`queue-row-${index}`}
      onLayout={(event) => onLayout(event.nativeEvent.layout.height)}
      style={[
        {
          backgroundColor: theme.colors.surface,
          shadowColor: theme.colors.ink,
          shadowRadius: 10,
          shadowOffset: { width: 0, height: 4 },
        },
        divider ? { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: divider } : null,
        animatedStyle,
      ]}
    >
      {children(handle)}
    </Animated.View>
  );
}
