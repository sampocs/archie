/** The fixed domain list, in the same order as `archie_shared.domains.Domain` (a Python test checks they match). */
export const DOMAINS = [
  "Macro",
  "Finance",
  "Trading",
  "Crypto",
  "Startups",
  "AI",
  "Politics",
  "Geopolitics",
  "Sports",
  "Geography",
  "History",
  "Software engineering",
  "Other",
] as const;

export type DomainName = (typeof DOMAINS)[number];

export function asDomain(value: string | null): DomainName {
  return (DOMAINS as readonly string[]).includes(value ?? "") ? (value as DomainName) : "Other";
}
