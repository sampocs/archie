import { SseParser } from "./stream";

describe("SseParser", () => {
  it("turns frames into events, across chunk boundaries, and skips unknown or broken ones", () => {
    const parser = new SseParser();

    const first = parser.push('event: delta\ndata: {"block": 0, "text": "It bu');
    const second = parser.push('ys"}\n\nevent: mystery\ndata: {}\n\nevent: block\ndata: {broken\n\n');
    const third = parser.push('event: done\r\ndata: {"message_id": "m2"}\r\n\r\n');

    expect(first).toEqual([]);
    expect(second).toEqual([{ type: "delta", block: 0, text: "It buys" }]);
    expect(third).toEqual([{ type: "done", message_id: "m2" }]);
  });

  it("reads the card-set events: drafting_cards with no data fields, cards carrying the row", () => {
    const parser = new SseParser();
    const events = parser.push(
      'event: drafting_cards\ndata: {}\n\nevent: cards\ndata: {"id": "cs1", "title": "JWTs", "status": "proposed"}\n\n',
    );

    expect(events).toEqual([
      { type: "drafting_cards" },
      { type: "cards", id: "cs1", title: "JWTs", status: "proposed" },
    ]);
  });
});
