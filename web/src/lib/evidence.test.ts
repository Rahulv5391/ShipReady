import { describe, expect, it } from "vitest";

import { neighbours, parseView, printedDiffers, sheetsFor } from "./evidence";
import type { CheckOut, FieldOut } from "./types";

const INVOICE = "11111111-1111-4111-8111-111111111111";
const BILL = "22222222-2222-4222-8222-222222222222";
const box = { x0: 0.1, y0: 0.1, x1: 0.3, y1: 0.12 };

function field(path: string, document_id: string, page_no = 1): FieldOut {
  return { path, value: "v", quote: "v", document_id, page_no, box };
}

function check(rule_id: string, outcome: CheckOut["outcome"], evidence: FieldOut[] = []): CheckOut {
  return {
    rule_id,
    title: rule_id,
    severity: "blocker",
    outcome,
    message: "",
    evidence,
    citations: [],
    verification: null,
    critic_reason: "",
  };
}

const gstin = check("ID-02", "fail", [
  field("commercial_invoice.exporter.gstin", INVOICE),
  field("shipping_bill.exporter.gstin", BILL),
  field("commercial_invoice.lines[0].hs_code", INVOICE),
]);

describe("sheetsFor", () => {
  it("puts each value on its page, numbered in the order the check names them", () => {
    const sheets = sheetsFor(gstin);
    expect(sheets.map((s) => s.label)).toEqual(["Invoice, page 1", "Shipping bill, page 1"]);
    expect(sheets[0].marks.map((m) => m.n)).toEqual([1, 3]);
    expect(sheets[1].marks.map((m) => m.n)).toEqual([2]);
  });

  it("outlines the other values on those pages without numbers, and only those", () => {
    const others = [
      field("commercial_invoice.exporter.gstin", INVOICE), // already evidence
      field("commercial_invoice.invoice_number", INVOICE),
      field("commercial_invoice.bank.account", INVOICE, 2), // another page
    ];
    const [invoice] = sheetsFor(gstin, others);
    expect(invoice.marks.map((m) => [m.n, m.field.path])).toEqual([
      [1, "commercial_invoice.exporter.gstin"],
      [3, "commercial_invoice.lines[0].hs_code"],
      [null, "commercial_invoice.invoice_number"],
    ]);
  });

  it("has no pages for a check that read nothing", () => {
    expect(sheetsFor(check("DOC-01", "fail"))).toEqual([]);
  });
});

describe("parseView", () => {
  it("shows one page only when there is more than one, and the number is in range", () => {
    expect(parseView("2", 2)).toBe(2);
    expect(parseView(undefined, 2)).toBeNull();
    expect(parseView("3", 2)).toBeNull();
    expect(parseView("0", 2)).toBeNull();
    expect(parseView("1.5", 2)).toBeNull();
    expect(parseView("1", 1)).toBeNull();
  });
});

describe("neighbours", () => {
  const checks = [check("WT-01", "fail"), gstin, check("QTY-03", "not_verified"), check("HS-01", "pass")];

  it("walks the failed findings, then those to confirm", () => {
    expect(neighbours(checks, "ID-02")).toEqual({ position: 1, total: 3, previous: null, next: "WT-01" });
    expect(neighbours(checks, "QTY-03")).toEqual({ position: 3, total: 3, previous: "WT-01", next: null });
  });

  it("leaves passed checks out", () => {
    expect(neighbours(checks, "HS-01")).toBeNull();
  });
});

describe("printedDiffers", () => {
  it("shows the printed text only when it says the value another way", () => {
    expect(printedDiffers("2026-10-14", "14-Oct-2026")).toBe(true);
    expect(printedDiffers("Ladies handbags, genuine leather - Tote", "Ladies  handbags, genuine leather – Tote")).toBe(false);
    expect(printedDiffers("Stewart and Sons", "STEWART AND SONS")).toBe(false);
    expect(printedDiffers("42022110", "")).toBe(false);
  });
});
