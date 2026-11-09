/** Shapes of the ShipReady API's answers (backend/src/shipready/api/schemas.py). */

export type Readiness = "ready" | "needs_fix" | "needs_review";

export type RunBrief = {
  status: "running" | "awaiting_review" | "done" | "failed";
  stage: "reading" | "extracting" | "checking" | "drafting" | null;
  error: string | null;
};

export type ShipmentListItem = {
  id: string;
  reference: string;
  mode: "sea" | "air" | "road" | "rail" | "courier" | null;
  status: string;
  error: string | null;
  readiness: Readiness | null;
  readiness_score: string | null; // a decimal, sent as text
  created_at: string;
  exporter: string | null;
  consignee: string | null;
  destination_country: string | null;
  port_of_loading: string | null;
  port_of_discharge: string | null;
  files: number;
  run: RunBrief | null;
  updated_at: string;
};

export type DocumentOut = {
  id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  status: "uploaded" | "processing" | "processed" | "failed";
  error: string | null;
  page_count: number | null;
};

export type UploadOut = {
  documents: DocumentOut[];
  duplicates: { filename: string; same_as: string }[];
};

export type RunOut = {
  id: string;
  status: RunBrief["status"];
  stage: RunBrief["stage"];
  error: string | null;
};

export type Severity = "blocker" | "major" | "minor" | "info";

export type FieldOut = {
  path: string;
  value: string;
  quote: string;
  document_id: string;
  page_no: number;
  box: { x0: number; y0: number; x1: number; y1: number } | null;
};

export type CheckOut = {
  rule_id: string;
  title: string;
  severity: Severity;
  outcome: "pass" | "fail" | "not_verified";
  message: string;
  evidence: FieldOut[];
  citations: { source_id: string; title: string; url: string; page: number | null; text: string }[];
  verification: "kept" | "misread" | null;
  critic_reason: string;
};

export type PartOut = { first_page: number; last_page: number; doc_type: string };

export type ShipmentDetail = ShipmentListItem & {
  documents: (DocumentOut & { parts: PartOut[] })[];
};

export type MessageOut = {
  id: string;
  recipient: string;
  subject: string;
  body: string;
  rule_ids: string[];
  status: "draft" | "approved" | "discarded";
};

export type ApprovalOut = {
  id: string;
  action: "mark_ready" | "mark_needs_fix" | "approve_message" | "discard_message";
  decided_by: string;
  reason: string | null;
  decided_at: string;
};

export type EventOut = { id: number; type: string; data: Record<string, unknown>; at: string };

export type PageOut = {
  page_no: number;
  width_px: number | null;
  height_px: number | null;
  text_source: "pdf_text" | "ocr" | "cells";
  has_image: boolean;
};
