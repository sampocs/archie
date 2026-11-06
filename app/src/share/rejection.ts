// The server's reason for a share naming a collection it has never heard of.
const COLLECTION_NOT_FOUND = "collection not found";

/**
 * A collection created in the app but not yet pushed is unknown to the server, so sharing into it is rejected.
 * That is not a real refusal: "Open Archie" saves the link through the app's outbox, which orders the push.
 */
export function isUnpushedCollectionRejection(reason: string): boolean {
  return reason === COLLECTION_NOT_FOUND;
}
