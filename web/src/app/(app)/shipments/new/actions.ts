"use server";

import { ApiError, api } from "@/lib/api";

export type Created = { id: string } | { error: string };

/** Creates the shipment the files will belong to (POST /shipments). */
export async function createShipment(reference: string, mode: "sea" | "air"): Promise<Created> {
  const trimmed = reference.trim();
  if (!trimmed) return { error: "Give the shipment a reference." };
  if (trimmed.length > 64) return { error: "Keep the reference to 64 characters." };
  try {
    const shipment = await api<{ id: string }>("/shipments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference: trimmed, mode }),
    });
    return { id: shipment.id };
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      return { error: `${trimmed} is already used. Pick another reference.` };
    }
    throw error;
  }
}
