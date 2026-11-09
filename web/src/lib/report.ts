import { DOCUMENT_NAMES } from "@/lib/documents";
import type { ApprovalOut, CheckOut, EventOut, Readiness, Severity } from "@/lib/types";

/** How the readiness report words and groups what the API returns. */

export type Tab = "failed" | "confirm" | "passed";
export const TABS: { id: Tab; label: string; outcome: CheckOut["outcome"] }[] = [
  { id: "failed", label: "Failed", outcome: "fail" },
  { id: "confirm", label: "To confirm", outcome: "not_verified" },
  { id: "passed", label: "Passed", outcome: "pass" },
];

export function parseTab(value: string | undefined): Tab {
  return TABS.find((tab) => tab.id === value)?.id ?? "failed";
}

const SEVERITY_ORDER: Record<Severity, number> = { blocker: 0, major: 1, minor: 2, info: 3 };
export const SEVERITY_LABELS: Record<Severity, string> = {
  blocker: "Blocker",
  major: "Major",
  minor: "Minor",
  info: "Note",
};

/** The checks of one outcome, the most serious first, then by rule. */
export function checksFor(checks: CheckOut[], outcome: CheckOut["outcome"]): CheckOut[] {
  return checks
    .filter((check) => check.outcome === outcome)
    .sort(
      (a, b) =>
        SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] || a.rule_id.localeCompare(b.rule_id),
    );
}

/** One plain sentence on what the result means for filing. */
export function verdictSentence(readiness: Readiness | null, checks: CheckOut[]): string {
  const failed = checks.filter((c) => c.outcome === "fail");
  const blockers = failed.filter((c) => c.severity === "blocker").length;
  const unsure = checks.filter((c) => c.outcome === "not_verified").length;
  const confirm = unsure === 0 ? "" : ` ${unsure} ${unsure === 1 ? "check needs" : "checks need"} a person to confirm.`;
  if (readiness === null) return "This shipment hasn't been checked yet.";
  if (readiness === "ready") return `Every blocker and major check passed.${confirm}`;
  if (blockers > 0) {
    return `${blockers} blocker ${blockers === 1 ? "check" : "checks"} failed, so this shipment should not be filed yet.${confirm}`;
  }
  if (failed.length > 0) {
    return `${failed.length} ${failed.length === 1 ? "check" : "checks"} failed; fix ${failed.length === 1 ? "it" : "them"} before filing.${confirm}`;
  }
  return `No check failed, but some couldn't be decided.${confirm}`;
}

/** "commercial_invoice.exporter.gstin" as "Invoice". */
export function documentOf(path: string): string {
  const type = path.split(".")[0];
  return DOCUMENT_NAMES[type] ?? type;
}

/** The document, and the line for an item field: "commercial_invoice.lines[2].hs_code" as
 * "Invoice, line 3", so equal values on different lines are told apart. */
export function fieldLabel(path: string): string {
  const line = /\.lines\[(\d+)\]/.exec(path);
  return line ? `${documentOf(path)}, line ${Number(line[1]) + 1}` : documentOf(path);
}

export const RECIPIENTS: Record<string, string> = {
  exporter: "Your team",
  forwarder: "Forwarder",
  customs_broker: "Customs broker",
  buyer: "Buyer",
  certifier: "Certifying body",
};

export function initials(label: string): string {
  return label
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? "")
    .join("");
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** A run's event as a line of the shipment's activity; null for the ones it leaves out. */
export function eventLine(event: EventOut): { what: string; detail: string } | null {
  const d = event.data;
  switch (event.type) {
    case "run_started":
      return { what: d.trigger === "recheck" ? "Checked again" : "Checking started", detail: "" };
    case "files_uploaded":
      return { what: plural((d.files as string[]).length, "file uploaded", "files uploaded"), detail: (d.files as string[]).join(", ") };
    case "document_read":
      return { what: `Read ${String(d.file)}`, detail: (d.documents as string[]).map((t) => DOCUMENT_NAMES[t] ?? t).join(", ") };
    case "document_removed":
      return { what: `Removed ${String(d.file)}`, detail: "" };
    case "fields_extracted":
      return { what: plural(Number(d.fields), "field read", "fields read"), detail: "" };
    case "checks_done":
      return { what: "Checked", detail: `${plural((d.failed as string[]).length, "check", "checks")} failed` };
    case "messages_drafted":
      return {
        what: plural((d.recipients as string[]).length, "message drafted", "messages drafted"),
        detail: (d.recipients as string[]).map((r) => RECIPIENTS[r] ?? r).join(", "),
      };
    case "awaiting_review":
      return { what: "Waiting for your review", detail: "" };
    case "review_reopened":
      return { what: "Review reopened", detail: "Files changed" };
    case "waiting":
      return { what: "Waiting for the AI service", detail: "It answered busy; retrying" };
    case "run_failed":
      return { what: "Checking stopped", detail: String(d.error ?? "") };
    default:
      return null; // stage changes and decisions (shown from the approvals) are left out
  }
}

export function approvalLine(approval: ApprovalOut): { what: string; detail: string } {
  const by = `by ${approval.decided_by}`;
  switch (approval.action) {
    case "mark_ready":
      return { what: "Marked ready", detail: approval.reason ? `${by}: ${approval.reason}` : by };
    case "mark_needs_fix":
      return { what: "Sent back to fix", detail: by };
    case "approve_message":
      return { what: "Message approved", detail: by };
    case "discard_message":
      return { what: "Message discarded", detail: by };
  }
}
