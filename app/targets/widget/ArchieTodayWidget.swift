import Security
import SwiftUI
import WidgetKit

// MARK: - Snapshot model

struct RingState: Decodable {
  let progress: Double
  let done: Bool
}

struct DayRings: Decodable {
  let cards: RingState?
  let notes: RingState?
  let brief: RingState?
}

struct DaySnapshot: Decodable {
  let day: String
  let rings: DayRings
}

struct Snapshot: Decodable {
  let version: Int
  let days: [DaySnapshot]
}

/// What a single widget render shows: known rings for a day, or nil when the day is unknown.
struct TodayEntry: TimelineEntry {
  let date: Date
  let rings: DayRings?
}

// MARK: - Keychain

enum SnapshotStore {
  static let service = "com.sampocs.archie.widget"
  static let account = "today"
  static let accessGroup = "3W3H65F89G.com.sampocs.archie.shared"

  static func load() -> Snapshot? {
    let query: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: account,
      kSecAttrAccessGroup as String: accessGroup,
      kSecReturnData as String: true,
      kSecMatchLimit as String: kSecMatchLimitOne,
    ]
    var result: AnyObject?
    guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
      let data = result as? Data,
      let snapshot = try? JSONDecoder().decode(Snapshot.self, from: data),
      snapshot.version == 1
    else { return nil }
    return snapshot
  }
}

// MARK: - Timeline

struct TodayProvider: TimelineProvider {
  func placeholder(in context: Context) -> TodayEntry {
    TodayEntry(
      date: Date(),
      rings: DayRings(
        cards: RingState(progress: 0.6, done: false),
        notes: RingState(progress: 1, done: true),
        brief: nil))
  }

  func getSnapshot(in context: Context, completion: @escaping (TodayEntry) -> Void) {
    completion(timelineEntries(now: Date()).first ?? placeholder(in: context))
  }

  func getTimeline(in context: Context, completion: @escaping (Timeline<TodayEntry>) -> Void) {
    completion(Timeline(entries: timelineEntries(now: Date()), policy: .never))
  }

  // The app refreshes the snapshot (and reloads timelines) whenever it can; between those, the entries roll the
  // day over at local midnight so the widget never shows yesterday's rings as today's.
  private func timelineEntries(now: Date) -> [TodayEntry] {
    let calendar = Calendar.current
    let snapshot = SnapshotStore.load()
    let today = calendar.startOfDay(for: now)
    let tomorrow = calendar.date(byAdding: .day, value: 1, to: today) ?? now.addingTimeInterval(86_400)
    let dayAfter = calendar.date(byAdding: .day, value: 2, to: today) ?? tomorrow.addingTimeInterval(86_400)

    return [
      TodayEntry(date: now, rings: rings(in: snapshot, on: today, calendar: calendar)),
      TodayEntry(date: tomorrow, rings: rings(in: snapshot, on: tomorrow, calendar: calendar)),
      TodayEntry(date: dayAfter, rings: nil),
    ]
  }

  private func rings(in snapshot: Snapshot?, on date: Date, calendar: Calendar) -> DayRings? {
    guard let snapshot else { return nil }
    let key = Self.dayKey(for: date, calendar: calendar)
    return snapshot.days.first { $0.day == key }?.rings
  }

  private static func dayKey(for date: Date, calendar: Calendar) -> String {
    let parts = calendar.dateComponents([.year, .month, .day], from: date)
    return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
  }
}

// MARK: - Views

struct ProgressRing: View {
  let symbol: String
  let ring: RingState?
  let dayKnown: Bool

  private let diameter: CGFloat = 44
  private let stroke: CGFloat = 4.5

  var body: some View {
    ZStack {
      Circle().stroke(Color.primary.opacity(0.22), lineWidth: stroke)

      if let ring {
        Circle()
          .trim(from: 0, to: ring.done ? 1 : max(0, min(1, ring.progress)))
          .stroke(Color.primary, style: StrokeStyle(lineWidth: stroke, lineCap: .round))
          .rotationEffect(.degrees(-90))
      }

      if ring?.done == true {
        Image(systemName: "checkmark").font(.system(size: 17, weight: .bold))
      } else {
        Image(systemName: symbol)
          .font(.system(size: 16, weight: .semibold))
          .opacity(dayKnown && ring == nil ? 0.4 : 1)
      }
    }
    .frame(width: diameter, height: diameter)
    .padding(stroke / 2)
  }
}

struct TodayWidgetView: View {
  let entry: TodayEntry

  var body: some View {
    HStack(spacing: 0) {
      Spacer(minLength: 0)
      ProgressRing(symbol: "rectangle.stack", ring: entry.rings?.cards, dayKnown: entry.rings != nil)
      Spacer(minLength: 0)
      ProgressRing(symbol: "book.closed", ring: entry.rings?.notes, dayKnown: entry.rings != nil)
      Spacer(minLength: 0)
      ProgressRing(symbol: "cup.and.saucer", ring: entry.rings?.brief, dayKnown: entry.rings != nil)
      Spacer(minLength: 0)
    }
    .widgetBackground()
  }
}

extension View {
  @ViewBuilder
  func widgetBackground() -> some View {
    if #available(iOS 17.0, *) {
      self.containerBackground(for: .widget) { Color.clear }
    } else {
      self
    }
  }
}

struct ArchieTodayWidget: Widget {
  let kind = "ArchieTodayWidget"

  var body: some WidgetConfiguration {
    StaticConfiguration(kind: kind, provider: TodayProvider()) { entry in
      TodayWidgetView(entry: entry)
    }
    .configurationDisplayName("Archie")
    .description("Today's cards, notes and brief.")
    .supportedFamilies([.accessoryRectangular])
  }
}
