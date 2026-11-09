import { describe, expect, it } from "vitest";

import { messageText, reviewError } from "./review";

describe("reviewError", () => {
  it.each([
    [409, "blocker checks fail (DOC-01, POL-01); give a reason to mark it ready anyway", "Blocker checks still fail. Give a reason to mark it ready anyway."],
    [409, "the shipment is not awaiting review", "This shipment isn't waiting for review any more. Reload to see where it is."],
    [409, "a run of this shipment is in progress", "It's being checked already."],
    [409, "the shipment's files are not all read", "Some files are still being read. Try again in a moment."],
    [409, "the message is already approved", "This message was approved already. Reload the page."],
    [404, "message not found", "This shipment or message no longer exists. Reload the page."],
    [503, "the work queue is unavailable", "ShipReady's work queue isn't answering. Try again in a minute."],
  ])("words a %i (%s)", (status, detail, expected) => {
    expect(reviewError(status, detail)).toBe(expected);
  });

  it("passes on a reason it has no words for", () => {
    expect(reviewError(422, "body: field required")).toBe("body: field required");
    expect(reviewError(500, "")).toBe("That didn't work. Try again.");
  });
});

describe("messageText", () => {
  it("puts the subject first, as pasted into an email", () => {
    expect(messageText(" SG42-0009: corrections ", "Hello,\n\nThanks\n\n")).toBe("Subject: SG42-0009: corrections\n\nHello,\n\nThanks\n");
  });
});
