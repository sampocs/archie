import { judgeSender, type SenderStatus } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { haptic } from "@/ui/haptics";

/** Allow or Block the sender of a pending newsletter (the Library card and the item page), then sync it. */
export function judgeNewsletterSender(sourceId: string, status: SenderStatus): void {
  judgeSender(db, sourceId, status);
  haptic("success");
  requestSync();
}
