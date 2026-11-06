import { MAX_TAKE_BODY_LENGTH } from "./takes";

/** Save needs a title and a body with something other than whitespace in them, and a body the server will accept. */
export function canSaveTake(input: { title: string; body: string }): boolean {
  const body = input.body.trim();
  return input.title.trim().length > 0 && body.length > 0 && Array.from(body).length <= MAX_TAKE_BODY_LENGTH;
}
