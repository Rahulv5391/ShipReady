import { describe, expect, it } from "vitest";

import { countryName, progress, timeAgo } from "./format";
import type { ShipmentListItem } from "./types";

function item(change: Partial<ShipmentListItem>): ShipmentListItem {
  return {
    id: "8362c5a8-3947-43df-bf38-492051dc32ab",
    reference: "SG42-0004",
    mode: "sea",
    status: "RECEIVED",
    error: null,
    readiness: null,
    readiness_score: null,
    created_at: "2026-11-10T10:00:00Z",
    exporter: null,
    consignee: null,
    destination_country: null,
    port_of_loading: null,
    port_of_discharge: null,
    files: 0,
    run: null,
    updated_at: "2026-11-10T10:00:00Z",
    ...change,
  };
}

describe("countryName", () => {
  it("names a country from its code, in any case", () => {
    expect(countryName("NL")).toBe("Netherlands");
    expect(countryName("gb")).toBe("United Kingdom");
  });

  it("keeps a code it does not know, and nothing stays nothing", () => {
    expect(countryName("not a code")).toBe("not a code");
    expect(countryName(null)).toBeNull();
  });
});

describe("timeAgo", () => {
  const now = Date.parse("2026-11-10T12:00:00Z");
  it.each([
    ["2026-11-10T11:59:30Z", "Just now"],
    ["2026-11-10T11:50:00Z", "10 minutes ago"],
    ["2026-11-10T09:00:00Z", "3 hours ago"],
    ["2026-11-09T11:00:00Z", "yesterday"],
    ["2026-11-03T12:00:00Z", "7 days ago"],
  ])("%s is %s", (iso, expected) => {
    expect(timeAgo(iso, now)).toBe(expected);
  });
});

describe("progress", () => {
  it("asks for files when there is no run yet", () => {
    expect(progress(item({}))).toEqual({ title: "No files yet", detail: "Add the shipment's documents", tone: "idle" });
  });

  it("names the stage of a running run, with its files", () => {
    const running = item({ files: 1, run: { status: "running", stage: "extracting", error: null } });
    expect(progress(running)).toEqual({ title: "Reading the fields", detail: "1 file", tone: "running" });
  });

  it("waits for a person once the run is in review", () => {
    const review = item({ files: 5, run: { status: "awaiting_review", stage: null, error: null } });
    expect(progress(review).title).toBe("Waiting for you");
  });

  it("shows why a run stopped", () => {
    const failed = item({ run: { status: "failed", stage: null, error: "lut.pdf could not be read" } });
    expect(progress(failed)).toEqual({ title: "Could not finish", detail: "lut.pdf could not be read", tone: "fix" });
  });
});
