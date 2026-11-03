// Counts sign-outs. A sync run captures the epoch when it starts and its local writes are dropped once the epoch has
// moved on, so a run in flight during sign-out cannot write the old account's data into the freshly wiped database.
// Kept standalone so both `auth/session` and `sync/*` can import it without a cycle.
let epoch = 0;

export function getSessionEpoch(): number {
  return epoch;
}

export function bumpSessionEpoch(): void {
  epoch += 1;
}
