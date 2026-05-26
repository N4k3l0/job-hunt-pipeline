/**
 * ISO 3166-1 alpha-2 country list used by the profile preferences picker
 * AND the onboarding flow. Single source of truth so both surfaces stay
 * in sync as the supported set grows.
 *
 * The `coverage` field is honest: how well the discovery pipeline can
 * actually find jobs in that country.
 *   - "strong" — at least one source has a dedicated endpoint or
 *     category for the country (Adzuna direct, Undutchables for NL, etc.)
 *   - "remote" — only globally-remote sources will surface jobs tagged
 *     with the country (RemoteOK / Himalayas / Remotive / WWR). On-site
 *     local jobs unlikely to appear automatically; users can paste links
 *     via the bulk-URL import.
 *
 * Coverage is informational — users can pick anything. The UI just sets
 * expectations.
 */
export type CountryCoverage = "strong" | "remote";

export interface CountryOption {
  code: string;
  name: string;
  group: string;
  coverage: CountryCoverage;
}

export const COUNTRY_OPTIONS: CountryOption[] = [
  // High-priority sponsorship destinations (Adzuna-supported = strong)
  { code: "NL", name: "Netherlands", group: "Europe", coverage: "strong" },
  { code: "DE", name: "Germany", group: "Europe", coverage: "strong" },
  { code: "IE", name: "Ireland", group: "Europe", coverage: "remote" },
  { code: "GB", name: "United Kingdom", group: "Europe", coverage: "strong" },
  { code: "US", name: "United States", group: "Americas", coverage: "strong" },
  { code: "CA", name: "Canada", group: "Americas", coverage: "strong" },
  // Rest of Europe (Adzuna covers some, rest remote-only)
  { code: "FR", name: "France", group: "Europe", coverage: "strong" },
  { code: "ES", name: "Spain", group: "Europe", coverage: "remote" },
  { code: "PT", name: "Portugal", group: "Europe", coverage: "remote" },
  { code: "IT", name: "Italy", group: "Europe", coverage: "remote" },
  { code: "BE", name: "Belgium", group: "Europe", coverage: "remote" },
  { code: "LU", name: "Luxembourg", group: "Europe", coverage: "remote" },
  { code: "AT", name: "Austria", group: "Europe", coverage: "strong" },
  { code: "CH", name: "Switzerland", group: "Europe", coverage: "remote" },
  { code: "SE", name: "Sweden", group: "Europe", coverage: "remote" },
  { code: "DK", name: "Denmark", group: "Europe", coverage: "remote" },
  { code: "NO", name: "Norway", group: "Europe", coverage: "remote" },
  { code: "FI", name: "Finland", group: "Europe", coverage: "remote" },
  { code: "IS", name: "Iceland", group: "Europe", coverage: "remote" },
  { code: "PL", name: "Poland", group: "Europe", coverage: "remote" },
  { code: "CZ", name: "Czech Republic", group: "Europe", coverage: "remote" },
  { code: "EE", name: "Estonia", group: "Europe", coverage: "remote" },
  { code: "LV", name: "Latvia", group: "Europe", coverage: "remote" },
  { code: "LT", name: "Lithuania", group: "Europe", coverage: "remote" },
  // Asia-Pacific
  { code: "AU", name: "Australia", group: "Asia-Pacific", coverage: "strong" },
  { code: "NZ", name: "New Zealand", group: "Asia-Pacific", coverage: "remote" },
  { code: "SG", name: "Singapore", group: "Asia-Pacific", coverage: "remote" },
  { code: "JP", name: "Japan", group: "Asia-Pacific", coverage: "remote" },
  { code: "IN", name: "India", group: "Asia-Pacific", coverage: "remote" },
  { code: "AE", name: "United Arab Emirates", group: "Asia-Pacific", coverage: "remote" },
  // Africa (mostly remote-only coverage; local sources can be added on
  // request — Jobberman / MyJobMag scrapers would give strong NG support)
  { code: "NG", name: "Nigeria", group: "Africa", coverage: "remote" },
  { code: "KE", name: "Kenya", group: "Africa", coverage: "remote" },
  { code: "ZA", name: "South Africa", group: "Africa", coverage: "remote" },
  { code: "GH", name: "Ghana", group: "Africa", coverage: "remote" },
  { code: "EG", name: "Egypt", group: "Africa", coverage: "remote" },
  // Latin America (remote-only — Adzuna doesn't serve these)
  { code: "BR", name: "Brazil", group: "Latin America", coverage: "remote" },
  { code: "MX", name: "Mexico", group: "Latin America", coverage: "remote" },
  { code: "AR", name: "Argentina", group: "Latin America", coverage: "remote" },
  // Remote-anywhere sentinel
  { code: "WW", name: "Worldwide / Remote", group: "Other", coverage: "strong" },
];

/** Quick lookup by code. */
export const COUNTRY_BY_CODE: Record<string, CountryOption> = Object.fromEntries(
  COUNTRY_OPTIONS.map((c) => [c.code, c]),
);
