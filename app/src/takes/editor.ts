/** Save needs both a title and a body with something other than whitespace in them. */
export function canSaveTake(input: { title: string; body: string }): boolean {
  return input.title.trim().length > 0 && input.body.trim().length > 0;
}
