import { checksFor, documentOf } from "@/lib/report";
import type { CheckOut, FieldOut } from "@/lib/types";

/** How the evidence viewer lays a finding's values out on the pages they were read from. */

/** A value outlined on a page: numbered when the check read it, unnumbered when shown only
 * because every value read is outlined. */
type Mark = { n: number | null; field: FieldOut };

export type Sheet = { key: string; documentId: string; pageNo: number; label: string; marks: Mark[] };

const keyOf = (field: FieldOut) => `${field.document_id}:${field.page_no}`;

/** The pages holding the check's evidence, in the order the check names them, each with its
 * values numbered as in the list beside the pages. With `others`, every other value read on
 * those pages is outlined too. */
export function sheetsFor(check: CheckOut, others: FieldOut[] = []): Sheet[] {
  const sheets = new Map<string, Sheet>();
  check.evidence.forEach((field, index) => {
    const key = keyOf(field);
    let sheet = sheets.get(key);
    if (!sheet) {
      sheet = {
        key,
        documentId: field.document_id,
        pageNo: field.page_no,
        label: `${documentOf(field.path)}, page ${field.page_no}`,
        marks: [],
      };
      sheets.set(key, sheet);
    }
    sheet.marks.push({ n: index + 1, field });
  });
  const shown = new Set(check.evidence.map((field) => `${keyOf(field)}:${field.path}`));
  for (const field of others) {
    const sheet = sheets.get(keyOf(field));
    if (sheet && !shown.has(`${keyOf(field)}:${field.path}`)) sheet.marks.push({ n: null, field });
  }
  return [...sheets.values()];
}

/** The page shown alone (its position from 1), or null for all side by side. */
export function parseView(value: string | undefined, sheets: number): number | null {
  const n = Number(value);
  return Number.isInteger(n) && n >= 1 && n <= sheets && sheets > 1 ? n : null;
}

/** Where the finding sits among those a person works through (failed, then to confirm), and its
 * neighbours; null for a passed check. */
export function neighbours(
  checks: CheckOut[],
  ruleId: string,
): { position: number; total: number; previous: string | null; next: string | null } | null {
  const order = [...checksFor(checks, "fail"), ...checksFor(checks, "not_verified")].map((c) => c.rule_id);
  const index = order.indexOf(ruleId);
  if (index < 0) return null;
  return {
    position: index + 1,
    total: order.length,
    previous: index > 0 ? order[index - 1] : null,
    next: index < order.length - 1 ? order[index + 1] : null,
  };
}

const plain = (text: string) =>
  text.normalize("NFKC").replace(/[‐-―−]/g, "-").replace(/\s+/g, " ").trim().toLowerCase();

/** Whether the page prints the value differently enough to show it (a date written another way),
 * not merely with other spacing, dashes or capitals. */
export function printedDiffers(value: string, quote: string): boolean {
  return quote !== "" && plain(quote) !== plain(value);
}

export const TEXT_SOURCES: Record<string, string> = {
  pdf_text: "Digital PDF",
  ocr: "Scan, read with OCR",
  cells: "Spreadsheet cells",
};
