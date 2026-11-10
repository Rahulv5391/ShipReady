import { describe, expect, it } from "vitest";

import { dayLabel, rowsLabel, siteOf } from "./sources";

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

describe("siteOf", () => {
  it("names the site without www", () => {
    expect(siteOf("https://www.dgft.gov.in/CP/?opt=itchs-import-export")).toBe("dgft.gov.in");
    expect(siteOf("https://content.dgft.gov.in/Website/HBP.pdf")).toBe("content.dgft.gov.in");
  });
});
