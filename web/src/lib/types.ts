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
