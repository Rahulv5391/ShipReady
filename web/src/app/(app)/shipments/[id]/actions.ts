"use server";

import { revalidatePath } from "next/cache";

import { ApiError, api } from "@/lib/api";
import { reviewError } from "@/lib/review";

export type Outcome = { ok: true } | { error: string };

const json = (body: object): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/** Runs one review request, then has the shipment's pages read again so they show the result. */
async function act(shipmentId: string, request: () => Promise<unknown>): Promise<Outcome> {
  try {
    await request();
  } catch (error) {
    if (error instanceof ApiError) return { error: reviewError(error.status, error.message) };
    throw error;
  }
  revalidatePath(`/shipments/${shipmentId}`, "layout");
  return { ok: true };
}

/** Mark ready or send back to fix; a reason is required to mark ready while blockers fail. */
export async function decide(shipmentId: string, decision: "ready" | "needs_fix", reason: string): Promise<Outcome> {
  const trimmed = reason.trim();
  if (trimmed.length > 2000) return { error: "Keep the reason to 2,000 characters." };
  const path = decision === "ready" ? "mark-ready" : "mark-needs-fix";
  return act(shipmentId, () => api(`/shipments/${shipmentId}/${path}`, json(trimmed ? { reason: trimmed } : {})));
}

export async function checkAgain(shipmentId: string): Promise<Outcome> {
  return act(shipmentId, () => api(`/shipments/${shipmentId}/runs`, { method: "POST" }));
}

/** Takes a file out of the shipment; the rest are checked again. */
export async function removeDocument(shipmentId: string, documentId: string): Promise<Outcome> {
  return act(shipmentId, () => api(`/documents/${documentId}`, { method: "DELETE" }));
}

/** Saves edits to a draft when there are any, then approves or discards it if asked. */
export async function updateMessage(
  shipmentId: string,
  messageId: string,
  change: { subject?: string; body?: string; decision?: "approve" | "discard" },
): Promise<Outcome> {
  const edit = Object.fromEntries(
    Object.entries({ subject: change.subject, body: change.body }).filter((e): e is [string, string] => e[1] !== undefined),
  );
  if (Object.values(edit).some((text) => !text.trim())) return { error: "A message needs a subject and some text." };
  return act(shipmentId, async () => {
    if (Object.keys(edit).length > 0) {
      await api(`/messages/${messageId}`, { ...json(edit), method: "PATCH" });
    }
    if (change.decision) await api(`/messages/${messageId}/${change.decision}`, { method: "POST" });
  });
}
