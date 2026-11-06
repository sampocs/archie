import * as Notifications from "expo-notifications";

import * as schema from "@/db/schema";
import { makeTestDb } from "@/db/testDb";

import { cancelReminders, scheduleReminders } from "./reminderScheduler";

jest.mock("expo-notifications", () => ({
  SchedulableTriggerInputTypes: { DATE: "date" },
  getPermissionsAsync: jest.fn(),
  requestPermissionsAsync: jest.fn(),
  cancelAllScheduledNotificationsAsync: jest.fn(),
  scheduleNotificationAsync: jest.fn(),
}));

// useReviewData imports the app database, which opens a native file; the tests pass their own in-memory one.
jest.mock("@/db/client", () => ({ db: {} }));

const mocked = jest.mocked(Notifications);

/** A consumed source with one new (so always due) card: the plan has a reminder for each of the next days. */
function seedDueCard() {
  const db = makeTestDb();
  db.insert(schema.sources)
    .values({
      id: "s1",
      url: "https://example.com/a",
      kind: "article",
      state: "consumed",
      intent: "queue",
      createdAt: "2026-11-01T00:00:00Z",
      updatedAt: "2026-11-01T00:00:00Z",
      processing: "ready",
    })
    .run();
  db.insert(schema.cards)
    .values({ id: "c1", sourceId: "s1", kind: "concept", question: "Q?", answer: "A.", createdAt: "2026-11-01T00:00:00Z" })
    .run();
  return db;
}

/** Notification calls in order, as "cancel" / "schedule". */
function callLog(): string[] {
  const entries = [
    ...mocked.cancelAllScheduledNotificationsAsync.mock.invocationCallOrder.map((order) => ({ order, name: "cancel" })),
    ...mocked.scheduleNotificationAsync.mock.invocationCallOrder.map((order) => ({ order, name: "schedule" })),
  ];
  return entries.sort((left, right) => left.order - right.order).map((entry) => entry.name);
}

function scheduledAfterLastCancel(): number {
  const log = callLog();
  return log.length - 1 - log.lastIndexOf("cancel");
}

/** Makes the permission check wait until the returned function is called, so calls truly overlap. */
function holdPermissionCheck(): () => void {
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  mocked.getPermissionsAsync.mockImplementation(async () => {
    await gate;
    return { granted: true } as Notifications.NotificationPermissionsStatus;
  });
  return release;
}

beforeEach(() => {
  jest.resetAllMocks();
  mocked.getPermissionsAsync.mockResolvedValue({ granted: true } as Notifications.NotificationPermissionsStatus);
  mocked.cancelAllScheduledNotificationsAsync.mockResolvedValue(undefined);
  mocked.scheduleNotificationAsync.mockResolvedValue("id");
});

describe("reminder calls are serialized", () => {
  it("leaves one plan's worth of reminders when two calls overlap", async () => {
    const db = seedDueCard();
    await scheduleReminders(db);
    const onePlan = scheduledAfterLastCancel();
    expect(onePlan).toBeGreaterThan(0);
    jest.clearAllMocks();

    const release = holdPermissionCheck();
    const first = scheduleReminders(db);
    const second = scheduleReminders(db);
    release();
    await Promise.all([first, second]);

    expect(scheduledAfterLastCancel()).toBe(onePlan);
  });

  it("lets a cancel issued right after a schedule call win", async () => {
    const db = seedDueCard();
    const release = holdPermissionCheck();

    const scheduling = scheduleReminders(db);
    const cancelling = cancelReminders();
    release();
    await Promise.all([scheduling, cancelling]);

    expect(callLog().at(-1)).toBe("cancel");
  });

  it("keeps running calls after one fails", async () => {
    const db = seedDueCard();
    mocked.getPermissionsAsync.mockRejectedValueOnce(new Error("boom"));

    await scheduleReminders(db);
    await scheduleReminders(db);

    expect(mocked.scheduleNotificationAsync).toHaveBeenCalled();
  });
});
