import { queueEntries } from "./menuVisibility";

describe("queueEntries", () => {
  it("offers a link both entries, whether or not its primer exists", () => {
    expect(queueEntries({ kind: "article" }, null)).toEqual({ snooze: true, queuePrimer: true });
    expect(queueEntries({ kind: "article" }, 400)).toEqual({ snooze: true, queuePrimer: true });
  });

  it("never offers a book snooze", () => {
    expect(queueEntries({ kind: "book" }, 400).snooze).toBe(false);
  });

  it("offers a book its primer only once the primer exists", () => {
    expect(queueEntries({ kind: "book" }, null).queuePrimer).toBe(false);
    expect(queueEntries({ kind: "book" }, 400).queuePrimer).toBe(true);
  });

  it("offers a note or a chat item neither", () => {
    for (const kind of ["note", "chat"]) {
      expect(queueEntries({ kind }, 400)).toEqual({ snooze: false, queuePrimer: false });
    }
  });
});
