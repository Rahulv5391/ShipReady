import type { RuleOut } from "@/lib/types";

/** How the rulebook page groups and words the rules. */

// The catalogue's sections, by the letters a rule id starts with.
const AREAS: { name: string; prefixes: string[] }[] = [
  { name: "Quantities and values", prefixes: ["QTY", "VAL", "FX", "INC"] },
  { name: "Packages, weights and containers", prefixes: ["PKG", "WT", "CNT", "MRK"] },
  { name: "Classification and export policy", prefixes: ["HS", "POL", "DESC", "UQC"] },
  { name: "Parties and identifiers", prefixes: ["ID", "PTY"] },
  { name: "Invoice and GST", prefixes: ["INV", "GST"] },
  { name: "Routing and dates", prefixes: ["PORT", "DST", "DATE"] },
  { name: "Completeness", prefixes: ["DOC", "COO", "LC", "EML"] },
];
const OTHER = "Other checks";

export function areaOf(ruleId: string): string {
  const prefix = ruleId.split("-")[0];
  return AREAS.find((area) => area.prefixes.includes(prefix))?.name ?? OTHER;
}

/** The catalogue's check type in words: by code alone, by the AI alone, or both. */
export function howChecked(checkType: string): string {
  const parts = checkType.split("+");
  const byAi = parts.some((part) => part === "DEC" || part === "LLM");
  if (!byAi) return "Exact rules";
  return parts.includes("DET") ? "Rules, then the AI's judgement" : "The AI's judgement";
}

/** The rules matching a search (id, title, description or what it prevents), grouped by area
 * in the catalogue's order. */
export function groupRules(rules: RuleOut[], query = ""): { area: string; rules: RuleOut[] }[] {
  const q = query.trim().toLowerCase();
  const found = q
    ? rules.filter((rule) => [rule.id, rule.title, rule.description, rule.prevents].some((text) => text.toLowerCase().includes(q)))
    : rules;
  const groups = new Map<string, RuleOut[]>();
  for (const rule of found) {
    const area = areaOf(rule.id);
    groups.set(area, [...(groups.get(area) ?? []), rule]);
  }
  const order = [...AREAS.map((area) => area.name), OTHER];
  return [...groups.entries()]
    .sort(([a], [b]) => order.indexOf(a) - order.indexOf(b))
    .map(([area, list]) => ({ area, rules: list }));
}

/** Where a rule's entry is in the rulebook. */
export const ruleHref = (ruleId: string) => `/rules#${encodeURIComponent(ruleId)}`;
