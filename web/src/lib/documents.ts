/** What ShipReady accepts and calls things, shared by the upload page's server and browser code. */

// The API's limits (backend/src/shipready/api/uploads.py).
export const MAX_FILES = 30;
export const MAX_FILE_BYTES = 25 * 1024 * 1024;

export const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".xlsx", ".jpg", ".jpeg", ".png", ".tif", ".tiff"];
const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
export const ACCEPTED_TYPES = ["application/pdf", DOCX, XLSX, "image/jpeg", "image/png", "image/tiff"];
/** For <input accept>: only these can be chosen, so nothing is refused after choosing. */
export const ACCEPT = [...ACCEPTED_EXTENSIONS, ...ACCEPTED_TYPES].join(",");
/** What the Google Picker lists: the same types, and Google Docs and Sheets, which convert. */
export const DRIVE_TYPES = [
  ...ACCEPTED_TYPES,
  "application/vnd.google-apps.document",
  "application/vnd.google-apps.spreadsheet",
].join(",");

export function accepted(name: string): boolean {
  const lower = name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((extension) => lower.endsWith(extension));
}

/** A short label for the file's type, as the chosen-files list shows it. */
export function kindOf(name: string): string {
  const lower = name.toLowerCase();
  if (lower.endsWith(".pdf")) return "PDF";
  if (lower.endsWith(".docx")) return "Word";
  if (lower.endsWith(".xlsx")) return "Excel";
  if (lower.endsWith(".tif") || lower.endsWith(".tiff")) return "TIFF";
  return "Image";
}

export function sizeText(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const DOCUMENT_NAMES: Record<string, string> = {
  commercial_invoice: "Invoice",
  packing_list: "Packing list",
  purchase_order: "Purchase order",
  shipping_bill: "Shipping bill",
  bill_of_lading: "Bill of lading",
  air_waybill: "Airway bill",
  certificate_of_origin: "Certificate of origin",
  lut: "LUT acknowledgement",
  other: "Other document",
};
