export type DiffLine = { kind: "same" | "removed" | "added"; text: string };
export type ShownLine = DiffLine | { kind: "gap"; count: number };

/** `before` and `after` compared line by line (longest common subsequence): kept, removed and added, in order. */
export function lineDiff(before: string[], after: string[]): DiffLine[] {
  // common[i][j]: how many lines before[i..] and after[j..] share, in order.
  const common = Array.from({ length: before.length + 1 }, () => new Array<number>(after.length + 1).fill(0));
  for (let i = before.length - 1; i >= 0; i--) {
    for (let j = after.length - 1; j >= 0; j--) {
      common[i][j] = before[i] === after[j] ? common[i + 1][j + 1] + 1 : Math.max(common[i + 1][j], common[i][j + 1]);
    }
  }

  // Walk the table; on a tie the removal comes first, so a changed line reads old-then-new.
  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < before.length && j < after.length) {
    if (before[i] === after[j]) {
      lines.push({ kind: "same", text: before[i] });
      i++;
      j++;
    } else if (common[i + 1][j] >= common[i][j + 1]) {
      lines.push({ kind: "removed", text: before[i] });
      i++;
    } else {
      lines.push({ kind: "added", text: after[j] });
      j++;
    }
  }
  return [
    ...lines,
    ...before.slice(i).map((text) => ({ kind: "removed" as const, text })),
    ...after.slice(j).map((text) => ({ kind: "added" as const, text })),
  ];
}

/** Unchanged runs folded into counted gaps, keeping `context` unchanged lines on each side of a change. */
export function foldUnchanged(lines: DiffLine[], context = 1): ShownLine[] {
  const changed = lines.map((line) => line.kind !== "same");
  const shown: ShownLine[] = [];
  lines.forEach((line, index) => {
    const nearChange = changed.slice(Math.max(0, index - context), index + context + 1).some(Boolean);
    if (nearChange) {
      shown.push(line);
      return;
    }
    const last = shown.at(-1);
    if (last && last.kind === "gap") last.count += 1;
    else shown.push({ kind: "gap", count: 1 });
  });
  return shown;
}
