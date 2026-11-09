import { describe, expect, it } from "vitest";

import { tokenExpired } from "./token";

const now = Date.UTC(2026, 10, 10, 12);
const encode = (claims: object) =>
  btoa(JSON.stringify(claims)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const token = (claims: object) => `header.${encode(claims)}.signature`;

describe("tokenExpired", () => {
  it("accepts a token that has not expired", () => {
    expect(tokenExpired(token({ exp: now / 1000 + 60 }), now)).toBe(false);
  });

  it("refuses an expired token, and one expiring this second", () => {
    expect(tokenExpired(token({ exp: now / 1000 - 1 }), now)).toBe(true);
    expect(tokenExpired(token({ exp: now / 1000 }), now)).toBe(true);
  });

  it.each([
    ["no payload", "just-one-part"],
    ["a payload that is not JSON", "header.bm90IGpzb24.signature"],
    ["no expiry", token({ sub: "rahul@demoexports.in" })],
    ["an expiry that is not a number", token({ exp: "tomorrow" })],
  ])("treats %s as expired", (_, value) => {
    expect(tokenExpired(value, now)).toBe(true);
  });
});
