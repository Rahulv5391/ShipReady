import { describe, expect, it } from "vitest";

import { ACCEPT, DRIVE_TYPES, accepted, kindOf, sizeText } from "./documents";

describe("accepted", () => {
  it.each(["invoice.pdf", "PL.XLSX", "po.docx", "photo.jpeg", "scan.JPG", "bl.png", "fax.tif", "fax.tiff"])(
    "accepts %s",
    (name) => expect(accepted(name)).toBe(true),
  );

  it.each(["case.json", "old.doc", "sheet.xls", "notes.txt", "archive.zip", "pdf"])("leaves out %s", (name) =>
    expect(accepted(name)).toBe(false),
  );
});

describe("what the chooser and the Picker offer", () => {
  it("lists both extensions and types for the file chooser", () => {
    expect(ACCEPT).toContain(".docx");
    expect(ACCEPT).toContain("application/pdf");
  });

  it("adds Google Docs and Sheets in the Picker", () => {
    expect(DRIVE_TYPES).toContain("application/vnd.google-apps.document");
    expect(DRIVE_TYPES).toContain("application/vnd.google-apps.spreadsheet");
    expect(DRIVE_TYPES).not.toContain("application/vnd.google-apps.presentation");
  });
});

describe("labels", () => {
  it("names the kind of file", () => {
    expect(kindOf("a.pdf")).toBe("PDF");
    expect(kindOf("a.docx")).toBe("Word");
    expect(kindOf("a.xlsx")).toBe("Excel");
    expect(kindOf("a.tiff")).toBe("TIFF");
    expect(kindOf("a.jpg")).toBe("Image");
  });

  it("writes sizes in KB below a megabyte and MB above", () => {
    expect(sizeText(100)).toBe("1 KB");
    expect(sizeText(37 * 1024)).toBe("37 KB");
    expect(sizeText(2.5 * 1024 * 1024)).toBe("2.5 MB");
  });
});
