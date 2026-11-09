import { describe, expect, it } from "vitest";

import {
  approvalLine,
  checksFor,
  documentOf,
  eventLine,
  fieldLabel,
  initials,
  parseTab,
  verdictSentence,
} from "./report";
import type { CheckOut } from "./types";

function check(rule_id: string, outcome: CheckOut["outcome"], severity: CheckOut["severity"]): CheckOut {
  return {
    rule_id,
    title: rule_id,
    severity,
    outcome,
    message: "",
    evidence: [],
    citations: [],
    verification: null,
    critic_reason: "",
  };
}

const checks = [
  check("WT-01", "fail", "major"),
  check("ID-01", "fail", "blocker"),
  check("DOC-01", "fail", "blocker"),
  check("QTY-03", "not_verified", "minor"),
  check("HS-01", "pass", "blocker"),
];

describe("checksFor", () => {
  it("keeps one outcome, blockers first, then by rule", () => {
    expect(checksFor(checks, "fail").map((c) => c.rule_id)).toEqual(["DOC-01", "ID-01", "WT-01"]);
    expect(checksFor(checks, "pass").map((c) => c.rule_id)).toEqual(["HS-01"]);
  });
});

describe("verdictSentence", () => {
  it("says what failed blockers mean for filing, and what is left to confirm", () => {
    expect(verdictSentence("needs_fix", checks)).toBe(
      "2 blocker checks failed, so this shipment should not be filed yet. 1 check needs a person to confirm.",
    );
  });

  it("covers failures without blockers, a ready shipment and an unchecked one", () => {
    expect(verdictSentence("needs_fix", [check("WT-01", "fail", "major")])).toBe("1 check failed; fix it before filing.");
    expect(verdictSentence("ready", [check("HS-01", "pass", "blocker")])).toBe("Every blocker and major check passed.");
    expect(verdictSentence(null, [])).toBe("This shipment hasn't been checked yet.");
  });
});

describe("activity", () => {
  const event = (type: string, data: Record<string, unknown>) => ({ id: 1, type, data, at: "2026-11-10T10:00:00Z" });

  it("words the events a person cares about", () => {
    expect(eventLine(event("files_uploaded", { files: ["a.pdf", "b.docx"] }))).toEqual({
      what: "2 files uploaded",
      detail: "a.pdf, b.docx",
    });
    expect(eventLine(event("document_read", { file: "a.pdf", pages: 1, documents: ["commercial_invoice"] }))).toEqual({
      what: "Read a.pdf",
      detail: "Invoice",
    });
    expect(eventLine(event("messages_drafted", { recipients: ["forwarder", "customs_broker"] }))?.detail).toBe(
      "Forwarder, Customs broker",
    );
    expect(eventLine(event("checks_done", { failed: ["ID-01"] }))).toEqual({ what: "Checked", detail: "1 check failed" });
  });

  it("leaves out stage changes", () => {
    expect(eventLine(event("stage_started", { stage: "reading" }))).toBeNull();
  });

  it("names who decided, and why when they gave a reason", () => {
    const base = { id: "a", decided_by: "rahul@demoexports.in", decided_at: "2026-11-10T10:00:00Z" };
    expect(approvalLine({ ...base, action: "mark_ready", reason: "Broker confirmed by phone" })).toEqual({
      what: "Marked ready",
      detail: "by rahul@demoexports.in: Broker confirmed by phone",
    });
    expect(approvalLine({ ...base, action: "discard_message", reason: null }).what).toBe("Message discarded");
  });
});

describe("small helpers", () => {
  it("parses the tab, names documents and makes initials", () => {
    expect(parseTab("passed")).toBe("passed");
    expect(parseTab("toString")).toBe("failed");
    expect(documentOf("bill_of_lading.gross_weight_kg")).toBe("Bill of lading");
    expect(initials("Customs broker")).toBe("CB");
    expect(fieldLabel("commercial_invoice.lines[2].hs_code")).toBe("Invoice, line 3");
    expect(fieldLabel("shipping_bill.exporter.gstin")).toBe("Shipping bill");
  });
});
