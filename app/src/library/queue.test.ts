import { dropIndex, positionAfterMove, positionBetween } from "./queue";

/** Reorders the positions the way the queue would after the move, to check the result stays sorted. */
function orderAfterMove(positions: number[], from: number, to: number): number[] {
  const moved = positionAfterMove(positions, from, to);
  const rest = positions.filter((_, index) => index !== from);
  return [...rest.slice(0, to), moved, ...rest.slice(to)];
}

const isStrictlyAscending = (values: number[]): boolean => values.every((value, i) => i === 0 || values[i - 1] < value);

describe("positionBetween", () => {
  it.each([
    [null, null, 0],
    [null, 5, 4],
    [5, null, 6],
    [1, 2, 1.5],
  ] as const)("(%p, %p) → %p", (above, below, expected) => {
    expect(positionBetween(above, below)).toBe(expected);
  });
});

describe("positionAfterMove", () => {
  const positions = [0, 1, 2, 3];

  it("moves the first item to the end", () => {
    expect(positionAfterMove(positions, 0, 3)).toBe(4);
    expect(isStrictlyAscending(orderAfterMove(positions, 0, 3))).toBe(true);
  });

  it("moves the last item to the top", () => {
    expect(positionAfterMove(positions, 3, 0)).toBe(-1);
  });

  it("moves a middle item down by one", () => {
    expect(positionAfterMove(positions, 1, 2)).toBe(2.5);
    expect(isStrictlyAscending(orderAfterMove(positions, 1, 2))).toBe(true);
  });

  it("swaps two items", () => {
    expect(positionAfterMove([0, 1], 0, 1)).toBe(2);
    expect(positionAfterMove([0, 1], 1, 0)).toBe(-1);
  });

  it("gives a lone item position 0", () => {
    expect(positionAfterMove([7], 0, 0)).toBe(0);
  });

  it("lands strictly between distinct neighbours after repeated halving", () => {
    let current = [0, 1, 2];
    for (let round = 0; round < 20; round += 1) current = orderAfterMove(current, 2, 1);
    expect(isStrictlyAscending(current)).toBe(true);
  });

  it("keeps equal neighbours' value when they tie", () => {
    // Two unpositioned-at-the-same-value neighbours: the midpoint equals both, so the order falls back to createdAt.
    expect(positionAfterMove([0, 3, 3], 0, 1)).toBe(3);
  });
});

describe("dropIndex", () => {
  const heights = [76, 76, 100, 76];

  it("stays put until the neighbour's middle is crossed", () => {
    expect(dropIndex(heights, 0, 37)).toBe(0);
    expect(dropIndex(heights, 0, 39)).toBe(1);
  });

  it("passes several rows of different heights", () => {
    expect(dropIndex(heights, 0, 76 + 51)).toBe(2);
    expect(dropIndex(heights, 0, 76 + 49)).toBe(1);
  });

  it("moves up", () => {
    expect(dropIndex(heights, 3, -51)).toBe(2);
    expect(dropIndex(heights, 3, -400)).toBe(0);
  });

  it("clamps at the ends", () => {
    expect(dropIndex(heights, 0, -200)).toBe(0);
    expect(dropIndex(heights, 3, 500)).toBe(3);
  });
});
