import { describe, expect, it } from "vitest";

import { dayLabel, freshnessLabel, rowsLabel, siteOf } from "./sources";

describe("rowsLabel", () => {
  it("says a dataset is not loaded rather than showing zero", () => {
    expect(rowsLabel(0)).toBe("Not loaded");
  });

  it("counts one row, and groups large counts the Indian way", () => {
    expect(rowsLabel(1)).toBe("1 row");
    expect(rowsLabel(12431)).toBe("12,431 rows");
    expect(rowsLabel(1234567)).toBe("12,34,567 rows");
  });
});

describe("dayLabel", () => {
  it("writes the date with the month in words, on the same day in every time zone", () => {
    expect(dayLabel("2026-10-17")).toBe("17 Oct 2026");
    expect(dayLabel("2026-01-01")).toBe("1 Jan 2026");
  });
});

describe("freshnessLabel", () => {
  it("gives the download day and the load day", () => {
    expect(freshnessLabel("2026-10-25T07:44:00Z", "2026-11-10T05:00:00Z")).toBe(
      "Downloaded 25 Oct 2026, loaded 10 Nov 2026",
    );
    expect(freshnessLabel("2026-10-25T07:44:00Z", "2026-10-25T08:00:00Z")).toBe(
      "Downloaded 25 Oct 2026, loaded 25 Oct 2026",
    );
  });

  it("dates by India time, so a download late in the UTC day falls on the next Indian day", () => {
    expect(freshnessLabel("2026-10-24T20:00:00Z", "2026-10-24T20:05:00Z")).toBe(
      "Downloaded 25 Oct 2026, loaded 25 Oct 2026",
    );
  });

  it("is null when either time is unknown", () => {
    expect(freshnessLabel(null, null)).toBeNull();
    expect(freshnessLabel("2026-10-25T07:44:00Z", null)).toBeNull();
  });

  it("is null when an older API sends no times, rather than an invalid date", () => {
    expect(freshnessLabel(undefined, undefined)).toBeNull();
    expect(freshnessLabel("not a date", "2026-10-25T08:00:00Z")).toBeNull();
  });
});

describe("siteOf", () => {
  it("names the site without www", () => {
    expect(siteOf("https://www.dgft.gov.in/CP/?opt=itchs-import-export")).toBe("dgft.gov.in");
    expect(siteOf("https://content.dgft.gov.in/Website/HBP.pdf")).toBe("content.dgft.gov.in");
  });
});
