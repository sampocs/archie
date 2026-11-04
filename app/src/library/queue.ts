/** Queue positions: lower is higher in the queue; a move sends the midpoint of the new neighbours. */

export function positionBetween(above: number | null, below: number | null): number {
  if (above === null && below === null) return 0;
  if (above === null) return below! - 1;
  if (below === null) return above + 1;
  return (above + below) / 2;
}

/** The moved item's new position: the midpoint of its new neighbours once it is taken out of the list. */
export function positionAfterMove(positions: number[], from: number, to: number): number {
  const rest = positions.filter((_, index) => index !== from);
  return positionBetween(to > 0 ? rest[to - 1] : null, to < rest.length ? rest[to] : null);
}

/**
 * Where a dragged row lands: it passes a neighbour once its moving edge crosses that neighbour's middle.
 * Runs on the UI thread while dragging, so rows of different heights shift at the right moment.
 */
export function dropIndex(heights: number[], from: number, translationY: number): number {
  "worklet";
  let index = from;
  let travelled = Math.abs(translationY);
  const step = translationY > 0 ? 1 : -1;
  while (index + step >= 0 && index + step < heights.length && travelled > heights[index + step] / 2) {
    travelled -= heights[index + step];
    index += step;
  }
  return index;
}
