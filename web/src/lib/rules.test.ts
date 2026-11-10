import { describe, expect, it } from "vitest";

import { areaOf, groupRules, howChecked, ruleHref } from "./rules";
import type { RuleOut } from "./types";

function rule(id: string, title = id, extra: Partial<RuleOut> = {}): RuleOut {
  return { id, title, description: "", check_type: "DET", severity: "major", prevents: "", source: "", ...extra };
}

describe("areaOf", () => {
  it("places a rule by its id's letters", () => {
    expect(areaOf("VAL-03")).toBe("Quantities and values");
    expect(areaOf("DATE-01")).toBe("Routing and dates");
    expect(areaOf("NEW-01")).toBe("Other checks");
  });
});

describe("howChecked", () => {
  it("words each check type", () => {
    expect(howChecked("DET")).toBe("Exact rules");
    expect(howChecked("DEC")).toBe("The AI's judgement");
    expect(howChecked("LLM")).toBe("The AI's judgement");
    expect(howChecked("DET+DEC")).toBe("Rules, then the AI's judgement");
    expect(howChecked("LLM+DET")).toBe("Rules, then the AI's judgement");
  });
});

describe("groupRules", () => {
  const rules = [rule("DOC-01"), rule("QTY-01", "Quantities match", { prevents: "Shipping bill query" }), rule("VAL-03", "Unit prices"), rule("NEW-01")];

  it("groups by area in the catalogue's order, unknown areas last", () => {
    expect(groupRules(rules).map((g) => [g.area, g.rules.map((r) => r.id)])).toEqual([
      ["Quantities and values", ["QTY-01", "VAL-03"]],
      ["Completeness", ["DOC-01"]],
      ["Other checks", ["NEW-01"]],
    ]);
  });

  it("searches ids, titles and what a rule prevents, ignoring case", () => {
    expect(groupRules(rules, " val-0").flatMap((g) => g.rules.map((r) => r.id))).toEqual(["VAL-03"]);
    expect(groupRules(rules, "query").flatMap((g) => g.rules.map((r) => r.id))).toEqual(["QTY-01"]);
    expect(groupRules(rules, "nothing like it")).toEqual([]);
  });
});

it("links to a rule's entry", () => {
  expect(ruleHref("VAL-03")).toBe("/rules#VAL-03");
});
